"""Frozen, CPU-only replay of cached observations; no inferred visual ground truth."""
import argparse
from collections import Counter, defaultdict
import csv
import importlib.util
from importlib.metadata import version
from itertools import combinations, product
import json
from pathlib import Path
import shutil
import sys
import time

from manual2ar.paths import ROOT
from manual2ar_baseline.gt import Sources, TaskDefinition, digest, encoded
from manual2ar_baseline.photos import check_run
from manual2ar_baseline.state import Session


METHODS = {'scene_guided': ('scene_guided', False), 'evidence_policy_only': ('evidence_guided', False),
           'conditional_plan_only': ('scene_guided', True), 'evidence_guided': ('evidence_guided', True)}
GOAL_METHODS = {'lexical_before': None, 'new_no_alias_no_normalization': (False,False),
                'aliases_only': (True,False), 'normalization_only': (False,True), 'source_grounded': (True,True)}


def read(path):
    return json.loads(Path(path).read_bytes())


def write(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_bytes(encoded(value))


def rate(numerator, denominator):
    return dict(numerator=numerator, denominator=denominator,
                rate=numerator / denominator if denominator else None)


def goal_suite():
    """Source-derived development expectations, not independent human annotations."""
    full, base, holder = ['install_base', 'install_holder'], ['install_base'], ['install_holder']
    examples = [
        ('安装料盘支架', full), ('我希望安装料盘支架', full),
        ('安装支架底座', base), ('安装料盘底座', base),
        ('安装灰色底座', base), ('安装深灰色底座', base),
        ('滑入料盘支架', holder), ('滑入料盘底座', holder),
        ('把可拆卸白色料盘支架滑入底座', holder), ('把白色支架滑入底座', holder),
        ('安装料盘底座及滑入料盘支架', full), ('安装底座后滑入支架', full),
        ('料盘支架怎么安装？', full), ('我想知道如何安装灰色底座', base),
        ('底座应该怎么安装？', base), ('底座已经装好，现在希望滑入料盘支架', holder),
    ]
    rows = [dict(query=q, expected='matched', target_node_ids=nodes) for q, nodes in examples]
    rows += [dict(query=q, expected='clarification_required', candidate_targets=[full, holder])
             for q in ['安装支架', '下一步怎么做']]
    rows += [dict(query=q, expected='rejected') for q in
             ['拆卸底座', '安装喷嘴', '开箱', '安装打印机立柱', '安装Z轴立柱',
              '安装2个底座', '安装两颗螺丝', '不要安装底座，只滑入支架', '不需要安装料盘支架']]
    for row in rows:
        row['query_origin'] = ('cached_historical_goal' if row['query'] in ['我希望安装料盘支架','滑入料盘支架']
                               else 'source_derived_development_variation_or_prior_control_question')
    return dict(label_origin='researcher_defined_source_backed_development_expectations',
                independent_human_labels=False, held_out=False, rows=rows)


def inventory(data):
    counts, records, excluded = Counter(), [], []
    for name in ['baseline', 'u7-pipeline', 'dev', 'integrated']:
        for path in sorted((data/'runs'/name).rglob('request.json')):
            request = read(path)
            if not isinstance(request, dict) or request.get('kind') != 'photo_observation':
                continue
            relative = path.relative_to(data).as_posix()
            counts['all_photo_requests'] += 1
            reason = ('derived_review_copy' if 'reviews' in path.parts else
                      'demo_excluded' if 'u7-demo' in path.parts else
                      'controlled_provider' if request.get('provider_kind') == 'controlled_provider' else
                      'other_provider' if request.get('provider_kind') != 'compatible_http' else None)
            if reason:
                counts[reason] += 1; excluded.append(dict(path=relative, reason=reason)); continue
            folder = path.parent; manifest = read(folder/'manifest.json') if (folder/'manifest.json').is_file() else {}
            record = dict(path=relative, request=request, status=manifest.get('status', 'incomplete'),
                          host=folder.name == 'observation', accepted=False, integrity='not_successful')
            if record['status'] == 'success':
                try:
                    check_run(folder); record['integrity'] = 'valid'
                except (ValueError, OSError) as error:
                    record['integrity'] = type(error).__name__
            receipt_path = folder.parent/'acceptance.json'
            if record['host'] and receipt_path.is_file():
                receipt = read(receipt_path)
                expected = {k: request[k] for k in ['session_id', 'task_sha256', 'epoch', 'revision']}
                record['accepted'] = (receipt.get('accepted') is True and record['integrity'] == 'valid'
                    and receipt.get('input_stamp') == expected
                    and receipt.get('capture_sha256') == request['capture_sha256']
                    and receipt.get('observation_manifest_sha256') == digest((folder/'manifest.json').read_bytes()))
                record['receipt_valid'] = record['accepted']
            records.append(record)
    return records, dict(counts), excluded


def manual_receipt(snapshot, telemetry):
    if not snapshot.get('events') or snapshot['events'][-1]['kind'] != 'manual': return False
    event = snapshot['events'][-1]
    stamp = {k:event[k] for k in ['session_id', 'task_sha256', 'epoch', 'revision']}
    stamp['revision'] += 1
    return any(row.get('event') == 'baseline.manual.accepted'
               and all(row.get('execution', {}).get(k) == value for k,value in stamp.items())
               and set(row.get('condition_ids', [])) == set(event['values']) for row in telemetry)


def prepare(data, output, baseline_goals):
    data, output = Path(data).resolve(), Path(output).resolve()
    if (output/'plan.json').exists():
        raise FileExistsError('Use a new experiment directory; never replace a frozen plan')
    records, counts, excluded = inventory(data)
    definitions = [ROOT/'baseline/ground_truth/u7/v1/state-validation',
                   data/'runs/baseline/transfer-20261111-v1/trials/a1mini-u7-control.r02/compilation']
    tasks, inputs = {}, {}
    def include(path):
        path = Path(path).resolve(); inputs[str(path)] = digest(path.read_bytes())
    for index, folder in enumerate(definitions):
        task, sources = read(folder/'task.json'), read(folder/'sources.json')
        sha = digest(encoded(task)); tasks[sha] = dict(task=task, sources=sources,
            origin='approved_gt' if index == 0 else 'automatic_candidate')
        include(folder/'task.json'); include(folder/'sources.json')
    for row in records:
        folder = (data/row['path']).parent
        for path in folder.rglob('*'):
            if path.is_file(): include(path)
        if row['host'] and (folder.parent/'acceptance.json').is_file(): include(folder.parent/'acceptance.json')
        # Manual snapshots belong only to this host session, never to another physical setup.
        if row['accepted']:
            row['manual_snapshots'] = []
            telemetry_path = folder.parent.parent/'events.jsonl'
            telemetry = [json.loads(line) for line in telemetry_path.read_text().splitlines()] if telemetry_path.is_file() else []
            if telemetry_path.is_file(): include(telemetry_path)
            for path in sorted(folder.parent.parent.glob('manual-*/session.json')):
                try: check_run(path.parent)
                except (ValueError, OSError): continue
                if not manual_receipt(read(path), telemetry): continue
                for artifact in path.parent.iterdir():
                    if artifact.is_file(): include(artifact)
                row['manual_snapshots'].append(str(path.resolve()))
    human_path = data/'runs/dev/baseline-review/transfer-20261111-v1/current.json'
    human = read(human_path); include(human_path)
    frozen_root = data/'runs/baseline/transfer-20261111-v1'
    protected = [p for p in sorted(frozen_root.rglob('*')) if p.is_file()]
    frozen_manifest=read(frozen_root/'evidence-manifest.json')
    for name,sha in frozen_manifest['files'].items():
        if digest((frozen_root/name).read_bytes())!=sha:raise ValueError('Original frozen experiment changed: '+name)
    for path in protected: include(path)
    before = output/'inputs/baseline-goals.py'; before.parent.mkdir(parents=True, exist_ok=True)
    if Path(baseline_goals).resolve() != before.resolve(): shutil.copyfile(baseline_goals, before)
    include(before)
    before_state=output/'inputs/baseline-state.py'
    shutil.copyfile(Path(baseline_goals).with_name('state.py'), before_state); include(before_state)
    for path in sorted((ROOT/'baseline/src/manual2ar_baseline').glob('*.py')):
        include(path); shutil.copyfile(path, output/'inputs'/path.name)
        include(output/'inputs'/path.name)
    for name in ['u7_demo.py','baseline_spatial.py']:
        path=ROOT/'apps/backend/src/manual2ar/modules/guidance'/name
        include(path);shutil.copyfile(path,output/'inputs'/('host-'+name));include(output/'inputs'/('host-'+name))
    include(Path(__file__))
    shutil.copyfile(__file__, output/'inputs/evaluation-driver.py')
    plan = dict(schema_version='online-planning-replay-v1', data_root=str(data), tasks=tasks,
        records=records, inventory=counts, excluded=excluded, goal_suite=goal_suite(),
        baseline_goals=str(before), baseline_state=str(before_state), methods=METHODS,goal_methods=GOAL_METHODS,input_sha256=inputs,
        human_review=human, new_model_calls=0, gpu_required=False,
        environment=dict(python=sys.version,pydantic=version('pydantic'),pillow=version('pillow')),
        protected_frozen_files=len(protected),original_frozen_manifest_files=len(frozen_manifest['files']),
        visual_accuracy=None, independent_progress_accuracy=None, planning_optimality=None)
    write(output/'plan.json', plan)
    (output/'plan.sha256').write_text(digest((output/'plan.json').read_bytes())+'\n')
    return plan


def replay(task, snapshot, policy, session_type=Session):
    session = session_type(task, snapshot['session_id'], snapshot['intent'],
        evidence_mode=snapshot['evidence_mode'], target_node_ids=snapshot.get('target_node_ids'), guidance_policy=policy)
    for event in snapshot['events']:
        session.apply(event)
    return session


def planning_row(session, structured=True):
    from manual2ar_baseline.planning import remaining_plan
    plan = session.plan(); node = session.nodes.get(plan['node_id']); completed = session.completed()
    visual = [c for c in node.completion_ids if session.conditions[c].channel == 'vision'] if node else []
    unknown = [c for c in visual if session.facts[c].value == 'unknown']
    values = [session.facts[c].value for c in visual]
    premature = plan['mode'] == 'operate' and node is not None and (
        any(not completed[d] for d in session.dependencies[node.id]) or
        any(session.facts[c].value != 'true' for c in node.precondition_ids))
    illegal_manual = plan['mode'] == 'ask_manual' and node is not None and (
        any(session.facts[c].value != 'true' for c in visual) or any(not completed[d] for d in session.dependencies[node.id]))
    illegal_complete = plan['mode'] == 'complete' and not all(completed[n] for n in session.needed)
    before = session.stamp(), dict(session.facts)
    result = remaining_plan(session) if structured else None
    assert before == (session.stamp(), session.facts), 'Planning changed accepted facts'
    action = result['current_action'] if result else plan
    requested = set(action['condition_ids']) & set(unknown) if action['mode'] == 'request_view' else set()
    remaining = {n for n in session.needed if not completed[n]}
    represented = {s['node_id'] for s in result['remaining_steps']} if result else ({node.id} if node else set())
    return dict(policy=session.guidance_policy, mode=action['mode'], node_id=action['node_id'],
        condition_ids=action['condition_ids'], partial_positive_operation=(action['mode'] == 'operate'
            and 'true' in values and 'unknown' in values and 'false' not in values),
        guard_violations=int(premature)+int(illegal_manual)+int(illegal_complete),
        unknown_condition_covered=len(requested), unknown_condition_needed=len(unknown) if action['mode']=='request_view' else 0,
        remaining_nodes_covered=len(represented & remaining), remaining_nodes_needed=len(remaining),
        extra_plan_nodes=len(represented-remaining), observation_hints=action.get('observation_hints', []),
        structured=result)


def control_snapshots(task):
    """Enumerated rule states; never described as real scenes or operator labels."""
    vision = [c.id for c in task.conditions if c.channel == 'vision']
    for index, values in enumerate(product(['true', 'false', 'unknown'], repeat=len(vision))):
        for target in ([task.nodes[0].id], [task.nodes[-1].id], [n.id for n in task.nodes]):
            session = Session(task, 'control.'+str(index), task.title, target_node_ids=target, guidance_policy='scene_guided')
            session.apply(dict(id='observation', **session.stamp(), kind='observation', origin='controlled_annotation',
                frame_id=1, source_sha256='a'*64, values={c:dict(value=v, reason='insufficient_detail' if v=='unknown' else 'observed')
                                                       for c,v in zip(vision, values)}))
            yield session
            for identity in session.order:
                if identity not in session.needed: continue
                node = session.nodes[identity]
                manual = [c for c in node.completion_ids if session.conditions[c].channel == 'manual']
                if not manual or any(not session.completed()[d] for d in session.dependencies[identity]): continue
                if any(session.facts[c].value != 'true' for c in node.completion_ids if session.conditions[c].channel=='vision'): continue
                session.apply(dict(id='manual.'+identity, **session.stamp(), kind='manual', origin='controlled_operator',
                    statement='Enumerated software control, not an actual operator confirmation', values={c:'true' for c in manual}))
                yield session


def summarize(rows):
    return dict(states=len(rows), modes=dict(Counter(r['mode'] for r in rows)),
        guard_violations=sum(r['guard_violations'] for r in rows),
        partial_positive_operation_suggestions=sum(r['partial_positive_operation'] for r in rows),
        unresolved_condition_coverage=rate(sum(r['unknown_condition_covered'] for r in rows),sum(r['unknown_condition_needed'] for r in rows)),
        remaining_plan_coverage=rate(sum(r['remaining_nodes_covered'] for r in rows),sum(r['remaining_nodes_needed'] for r in rows)),
        extra_plan_nodes=sum(r['extra_plan_nodes'] for r in rows))


def run(output):
    from manual2ar_baseline.goals import resolve_goal, goal_candidates
    output = Path(output);raw=(output/'plan.json').read_bytes()
    if digest(raw)!=(output/'plan.sha256').read_text().strip():raise ValueError('Frozen plan changed')
    plan=json.loads(raw);data=Path(plan['data_root'])
    if (output/'results.json').exists(): raise FileExistsError('Do not overwrite experiment results')
    for name, sha in plan['input_sha256'].items():
        if digest(Path(name).read_bytes()) != sha: raise ValueError('Frozen input changed: '+name)
    spec = importlib.util.spec_from_file_location('manual2ar_baseline._frozen_goals', plan['baseline_goals'])
    old = importlib.util.module_from_spec(spec); sys.modules[spec.name] = old; spec.loader.exec_module(old)
    spec = importlib.util.spec_from_file_location('manual2ar_baseline._frozen_state', plan['baseline_state'])
    old_state = importlib.util.module_from_spec(spec);sys.modules[spec.name]=old_state;spec.loader.exec_module(old_state)
    tasks = {sha:TaskDefinition.model_validate(row['task']) for sha,row in plan['tasks'].items()}
    gt_sha = next(sha for sha,row in plan['tasks'].items() if row['origin']=='approved_gt'); gt = tasks[gt_sha]
    sources = Sources.model_validate(plan['tasks'][gt_sha]['sources'])
    goal_rows = []
    for method, flags in GOAL_METHODS.items():
        for row in plan['goal_suite']['rows']:
            selected, candidates = None, []
            try:
                selected = (old.resolve_goal(gt,sources,row['query']) if method=='lexical_before' else
                    resolve_goal(gt,sources,row['query'],use_aliases=flags[0],normalize_language=flags[1]))
            except ValueError:
                if method!='lexical_before': candidates=goal_candidates(gt,sources,row['query'],use_aliases=flags[0],normalize_language=flags[1])
            matched = selected.selected_node_ids if selected else None
            coverage = all(any(c['selected_node_ids']==target for c in candidates) for target in row.get('candidate_targets',[]))
            safe_choice = matched==row.get('target_node_ids') if row['expected']=='matched' else matched is None
            correct = (safe_choice and coverage if row['expected']=='clarification_required' else
                       safe_choice and not candidates if row['expected']=='rejected' else safe_choice)
            goal_rows.append(dict(method=method, query=row['query'], expected=row['expected'], selected=matched,
                correct=correct, safe_auto_choice=safe_choice, candidate_count=len(candidates), candidate_coverage=coverage if row['expected']=='clarification_required' else None))
    replay_rows, errors, snapshots, consistency = [], [], {}, defaultdict(list)
    observations, provider_calls = [], []
    for record in plan['records']:
        folder=(data/record['path']).parent; request=record['request']
        for path in folder.rglob('*provider-*.json'):
            value=read(path);metadata={k:value.get(k) for k in ['model','elapsed_ms','usage']}
            metadata['stage']='detail' if path.name.startswith('detail-provider-') else 'coarse'
            provider_calls.append(metadata)
        if record['integrity']!='valid': continue
        evaluated=read(folder/'evaluated.json'); observations.append(dict(record=record, evaluated=evaluated))
        provider=read(folder/'provider-0.json') if (folder/'provider-0.json').is_file() else {}
        model_signature=tuple(provider.get(k) for k in ['model','temperature','enable_thinking','response_format'])
        for cid,reading in evaluated['readings'].items():
            key=(request['task_sha256'],request['source_sha256'],request.get('observation_protocol_sha256',request['protocol_sha256']),
                 request.get('implementation_sha256'),model_signature,cid)
            consistency[key].append(reading['value'])
        if not record['accepted']: continue
        for path in [str(folder/'session.json')]+record.get('manual_snapshots',[]):
            snapshot=read(path)
            key=(snapshot['task_sha256'],snapshot['session_id'],tuple(e['id'] for e in snapshot['events']))
            if key in snapshots: continue
            snapshots[key]=snapshot
            for method, (policy, structured) in METHODS.items():
                try:
                    session=replay(tasks[snapshot['task_sha256']],snapshot,policy,old_state.Session if policy=='scene_guided' else Session)
                    result=planning_row(session,structured=structured)
                    result.update(method=method,group=plan['tasks'][snapshot['task_sha256']]['origin'],session_id=session.id,
                                  revision=session.revision, snapshot_path=path)
                    replay_rows.append(result)
                except (ValueError,KeyError) as error:
                    errors.append(dict(path=path,method=method,error=str(error)))
    controls=[]; started=time.perf_counter()
    for session in control_snapshots(gt):
        snapshot=dict(session_id=session.id,intent=session.intent,evidence_mode=session.evidence_mode,
                      target_node_ids=session.target_node_ids,events=session.events)
        for method, (policy, structured) in METHODS.items():
            target=replay(gt,snapshot,policy,old_state.Session if policy=='scene_guided' else Session)
            result=planning_row(target,structured=structured);result['method']=method
            controls.append(result)
    elapsed=time.perf_counter()-started
    metrics={}
    for name, rows in [('cached_accepted_replay',replay_rows),('enumerated_software_controls',controls)]:
        metrics[name]={method:summarize([r for r in rows if r['method']==method]) for method in METHODS}
    readings=[reading['value'] for row in observations for reading in row['evaluated']['readings'].values()]
    pairs=[(a,b) for values in consistency.values() for a,b in combinations(values,2)]
    human=Counter(row['decision'] for row in plan['human_review']['labels']['labels'])
    usage=[p['usage']['total_tokens'] for p in provider_calls if isinstance(p.get('usage'),dict) and 'total_tokens' in p['usage']]
    protocol_groups={}
    for protocol_id in sorted({read((data/r['path']).parent/'protocol.json').get('id','unknown') for r in plan['records']}):
        group=[r for r in plan['records'] if read((data/r['path']).parent/'protocol.json').get('id','unknown')==protocol_id]
        values=[v['value'] for o in observations if o['record'] in group for v in o['evaluated']['readings'].values()]
        protocol_groups[protocol_id]=dict(requests=len(group),statuses=dict(Counter(r['status'] for r in group)),
            valid=sum(r['integrity']=='valid' for r in group),accepted=sum(r['accepted'] for r in group),
            unknown_rate=rate(values.count('unknown'),len(values)))
    for name,sha in plan['input_sha256'].items():
        if digest(Path(name).read_bytes()) != sha:raise ValueError('Input changed during replay: '+name)
    results=dict(inventory=plan['inventory'], real_requests=len(plan['records']),
        unique_capture_sha256=len({r['request']['capture_sha256'] for r in plan['records']}),
        statuses=dict(Counter(r['status'] for r in plan['records'])), valid_successful_runs=len(observations),
        accepted_observations=sum(r['accepted'] for r in plan['records']),
        observed_condition_values=dict(Counter(readings)), unknown_rate=rate(readings.count('unknown'),len(readings)),
        repeat_output_exact_agreement=rate(sum(a==b for a,b in pairs),len(pairs)),
        repeat_output_true_false_conflicts=sum({a,b}=={'true','false'} for a,b in pairs),
        repeated_condition_groups=sum(len(v)>1 for v in consistency.values()),
        consistency_scope='same image/task/observation protocol/implementation/model parameters; prompts may differ',
        protocol_groups=protocol_groups,protected_frozen_files_verified=plan['protected_frozen_files'],
        historical_cost=dict(provider_records=len(provider_calls),stages=dict(Counter(p['stage'] for p in provider_calls)),
                             usage_reported=len(usage),reported_total_tokens=sum(usage),
                             reported_elapsed_ms=sum(p['elapsed_ms'] for p in provider_calls if isinstance(p.get('elapsed_ms'),(int,float)))),
        existing_compilation_human_review=dict(human),goal_development_results=goal_rows,metrics=metrics,
        replay_snapshots=len(snapshots),replay_errors=errors,control_cpu_seconds=elapsed,
        replay_historical_sessions=len({(s['task_sha256'],s['session_id']) for s in snapshots.values()}),
        replay_snapshot_kinds=dict(Counter(s['events'][-1]['kind'] for s in snapshots.values())),
        cached_by_origin={origin:{p:summarize([r for r in replay_rows if r['method']==p and r['group']==origin]) for p in METHODS}
                          for origin in {r['group'] for r in replay_rows}},
        visual_accuracy=None,progress_accuracy=None,real_assembly_success=None,planning_optimality=None,
        new_model_calls=0,gpu_calls=0,independent_photo_labels=0)
    write(output/'results.json',results);write(output/'replay.json',replay_rows);write(output/'controls.json',controls)
    with (output/'goals.csv').open('w',newline='',encoding='utf-8-sig') as file:
        writer=csv.DictWriter(file,fieldnames=list(goal_rows[0]));writer.writeheader();writer.writerows(goal_rows)
    annotations={};missing_annotation_images=[]
    for record in plan['records']:
        request=record['request'];key=request['task_sha256']+':'+request['capture_sha256']
        image=(data/record['path']).parent/'capture.original'
        if not image.is_file() or digest(image.read_bytes())!=request['capture_sha256']:
            missing_annotation_images.append(record['path']);continue
        if key not in annotations:
            annotations[key]=dict(task_sha256=request['task_sha256'],capture_sha256=request['capture_sha256'],
                image=str(image),reviewer='',note='',
                conditions={c.id:'unrated' for c in tasks[request['task_sha256']].conditions if c.channel=='vision'},
                criteria=[dict(condition_id=c.id,statement=c.statement,requirement_ids=c.requirement_ids)
                          for c in tasks[request['task_sha256']].conditions if c.channel=='vision'])
    write(output/'independent-photo-labels.template.json',dict(status='unrated',includes_failed_model_requests=True,
          missing_or_invalid_images=missing_annotation_images,items=list(annotations.values())))
    report(output,results)
    return results


def report(output, results):
    lines=['# 在线目标与条件规划：缓存重放试验','',
        '本轮是开发诊断与软件控制试验。历史模型输出不是视觉真值，枚举状态不是实拍样本；没有独立标签的准确率保持未评价。','',
        f"非演示真实请求：{results['real_requests']}；不同照片字节SHA：{results['unique_capture_sha256']}（不代表独立设备或装配状态）。",
        f"完整且哈希有效的成功记录：{results['valid_successful_runs']}；宿主接受记录：{results['accepted_observations']}。",
        f"重放{results['replay_snapshots']}个快照，来自{results['replay_historical_sessions']}个历史会话；快照类型{results['replay_snapshot_kinds']}。正式GT仅2快照，其余38来自自动候选r02，不是40个独立场景。",
        f"历史成功记录的条件输出：{results['observed_condition_values']}；未知{results['unknown_rate']['numerator']}/{results['unknown_rate']['denominator']}（{results['unknown_rate']['rate']:.1%}）。这不是错误率。",'',
        '## 按历史协议分组（不同样本、实现，不作因果对比）','',
        '| 协议 | 请求 | 成功/失败 | 宿主接受 | 未知条件输出 |','|---|---:|---:|---:|---:|']
    for name,row in results['protocol_groups'].items():
        unknown=row['unknown_rate'];statuses=row['statuses']
        lines.append(f"| {name} | {row['requests']} | {statuses.get('success',0)}/{statuses.get('failed',0)} | {row['accepted']} | {unknown['numerator']}/{unknown['denominator']} |")
    lines += ['',
        '## 来源约束的目标定位（研究者编写的开发预期，非留出准确率）','',
        '| 方法 | 明确目标命中 | 不支持问法拒绝 | 歧义候选覆盖 | 严格符合开发预期 |','|---|---:|---:|---:|---:|']
    for method in GOAL_METHODS:
        rows=[r for r in results['goal_development_results'] if r['method']==method]
        ambiguous=[r for r in rows if r['candidate_coverage'] is not None]
        matched=[r for r in rows if r['expected']=='matched'];rejected=[r for r in rows if r['expected']=='rejected']
        lines.append(f"| {method} | {sum(r['correct'] for r in matched)}/{len(matched)} | {sum(r['correct'] for r in rejected)}/{len(rejected)} | {sum(r['candidate_coverage'] for r in ambiguous)}/{len(ambiguous)} | {sum(r['correct'] for r in rows)}/{len(rows)} |")
    lines+=['','## 同一事件输入下的规划对照','','部分正证据操作建议是重复安装风险代理，不是已证实的实际冗余操作。', '',
        '| 数据 | 策略 | 状态数 | 门控违规 | 部分正证据时仍建议操作 | 补拍状态数 | 未知条件请求覆盖 | 剩余操作表示覆盖 |',
        '|---|---|---:|---:|---:|---:|---|---|']
    for dataset, methods in results['metrics'].items():
        for method, row in methods.items():
            u,r=row['unresolved_condition_coverage'],row['remaining_plan_coverage']
            lines.append(f"| {dataset} | {method} | {row['states']} | {row['guard_violations']} | {row['partial_positive_operation_suggestions']} | {row['modes'].get('request_view',0)} | {u['numerator']}/{u['denominator']} | {r['numerator']}/{r['denominator']} |")
    lines+=['','缓存回放分别按正式GT与自动编译候选分组保存在 results.json，不把两者条件混用。后续计划是条件分支，不是保证成功的固定操作序列。',
        f"重放错误：{len(results['replay_errors'])}；控制枚举CPU时间：{results['control_cpu_seconds']:.3f}s（不是模型/GPU推理耗时）。",'',
        f"同图共享条件输出：{results['repeated_condition_groups']}组重复条件，配对完全一致{results['repeat_output_exact_agreement']['numerator']}/{results['repeat_output_exact_agreement']['denominator']}，真/假冲突{results['repeat_output_true_false_conflicts']}。限定同图、任务、观测协议、实现和模型参数，问句/上下文仍可能不同；不代表视觉正确率。",'',
        '## 历史成本和标签边界','',
        f"历史有{results['historical_cost']['provider_records']}份调用记录（整图/修复{results['historical_cost']['stages'].get('coarse',0)}、局部{results['historical_cost']['stages'].get('detail',0)}），有用量记录{results['historical_cost']['usage_reported']}份，报告token合计{results['historical_cost']['reported_total_tokens']}、elapsed_ms求和{results['historical_cost']['reported_elapsed_ms']}（不是墙钟耗时或完整账单）。本轮新模型调用0、GPU调用0。",
        f"既有编译候选审核：{results['existing_compilation_human_review']}，仅评价编译候选，不是视觉标签。",'',
        '视觉准确率、真实进度准确率、真实装配成功率、AR空间精度与交互最优性均未评价。独立图像标签模板无模型预测值，等待实际审核。',
        '未知条件覆盖的分母仅包含该方法推荐补拍的快照。控制组新策略额外选择4个补拍状态，不能把324与328当作同一分母；缓存组两者均14个补拍状态、27个未知条件。',
        '真实缓存未出现“部分正证据仍建议操作”情形，动作分布无变化；该改进仅在控制状态中得到验证。剩余操作表示覆盖衡量输出完整性，不代表实际执行成功。',
        '758个控制状态包括3^5×3=729个初始视觉三值/目标组合和29个合法正向人工确认后的状态，未穷举人工否定或时序回退。',
        '原始照片、失败记录、冻结编译评价和既有人审均只读；所有输入SHA和代码快照见 plan.json 与 inputs/。']
    (output/'REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('command',choices=['prepare','run'])
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--data',type=Path)
    parser.add_argument('--baseline-goals',type=Path);args=parser.parse_args()
    if args.command=='prepare':
        if args.data is None or args.baseline_goals is None:parser.error('prepare requires --data and --baseline-goals')
        prepare(args.data,args.output,args.baseline_goals)
    else:run(args.output)
    print(args.output)


if __name__=='__main__':main()
