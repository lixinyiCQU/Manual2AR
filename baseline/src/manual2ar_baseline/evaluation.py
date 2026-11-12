"""Frozen, repeated transfer evaluation. Human labels never approve a runtime task."""
from collections import Counter
from datetime import datetime, timezone
import importlib.metadata
import json
from pathlib import Path
import platform
import time
from typing import Literal

from pydantic import Field, model_validator

from .compiler import Proposal, compile_task, lower, render_resources
from .gt import Digest, Identity, Sources, Strict, Text, digest, encoded
from .provider import CompatibleClient
from .sources import retrieve


class Case(Strict):
    id: Identity = Field(max_length=95)
    split: Literal['seen_control', 'unseen_task', 'unseen_device']
    device_id: Text
    device_path: Text
    intent: Text
    expected_source_url: Text
    expected_heading: list[Text] = Field(min_length=1)
    scope_note: Text


class Suite(Strict):
    schema_version: Literal['baseline-transfer-suite-v1']
    id: Identity
    scope: Text
    cases: list[Case] = Field(min_length=1)

    @model_validator(mode='after')
    def distinct(self):
        if len({c.id for c in self.cases}) != len(self.cases):
            raise ValueError('Duplicate evaluation case ID')
        return self


RUBRIC = ('task_scope', 'requirements', 'dependencies', 'verification')


class HumanLabel(Strict):
    trial_id: Identity
    compilation_manifest_sha256: Digest
    task_sha256: Digest
    decision: Literal['pending', 'approved', 'rejected'] = 'pending'
    reviewer: str = ''
    note: str = ''
    task_scope: Literal['pending', 'pass', 'fail'] = 'pending'
    requirements: Literal['pending', 'pass', 'fail'] = 'pending'
    dependencies: Literal['pending', 'pass', 'fail'] = 'pending'
    verification: Literal['pending', 'pass', 'fail'] = 'pending'

    @model_validator(mode='after')
    def reviewed(self):
        values = [getattr(self, key) for key in RUBRIC]
        if self.decision != 'pending' and (not self.reviewer.strip() or not self.note.strip() or 'pending' in values):
            raise ValueError('Reviewed labels require reviewer, note and all rubric answers')
        if self.decision == 'approved' and set(values) != {'pass'}:
            raise ValueError('Approval requires every rubric item to pass')
        if self.decision == 'rejected' and 'fail' not in values:
            raise ValueError('Rejection requires a failed rubric item')
        return self


class HumanLabels(Strict):
    schema_version: Literal['baseline-transfer-labels-v1']
    plan_sha256: Digest
    labels: list[HumanLabel]


def now():
    return datetime.now(timezone.utc).isoformat()


def read(path):
    return json.loads(path.read_bytes())


def write(path, value):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_bytes(encoded(value))
    temporary.replace(path)


def files(folder):
    return {str(p.relative_to(folder)): digest(p.read_bytes()) for p in sorted(folder.rglob('*')) if p.is_file()}


def implementation():
    root = Path(__file__).parent
    return {p.name: digest(p.read_bytes()) for p in sorted(root.glob('*.py'))}


def public_settings(settings):
    # Credentials are neither exported nor hashed; changing a key does not change the method.
    result = settings.model_dump(exclude={'api_key', 'base_url'})
    result['endpoint_sha256'] = digest(settings.base_url.encode())
    return dict(**result, max_tokens=16000, http_retry=0, repair_limit_per_phase=1,
                python=platform.python_version(), dependencies={n: importlib.metadata.version(n) for n in ('pydantic', 'Pillow')})


def make_plan(suite_path, archive, manifest, capabilities, settings, output, *, repeats=3, repo_root):
    if type(repeats) is not int or not 1 <= repeats <= 100:
        raise ValueError('Repeats must be an integer from 1 to 100')
    suite = Suite.model_validate_json(suite_path.read_bytes())
    output.mkdir(parents=True, exist_ok=False)
    inputs = output / 'inputs'
    inputs.mkdir()
    snapshot = inputs / 'implementation/manual2ar_baseline'
    snapshot.mkdir(parents=True)
    for module in Path(__file__).parent.glob('*.py'):
        (snapshot / module.name).write_bytes(module.read_bytes())
    write(inputs / 'suite.json', suite.model_dump())
    (inputs / 'capabilities.json').write_bytes(capabilities.read_bytes())
    cases = []
    for case in suite.cases:
        folder = inputs / case.id
        folder.mkdir()
        selected = dict(retrieval_pass=False, admissible=False, error_type=None)
        try:
            sources, root, metadata = retrieve(archive, manifest, case.intent, device_path=case.device_path, assembly_context=True)
            write(folder / 'sources.json', sources.model_dump())
            write(folder / 'retrieval.json', metadata)
            write(folder / 'source-root.json', str(root))
            selected.update(retrieval_pass=metadata['source_url'] == case.expected_source_url and metadata['parent_heading'] == case.expected_heading,
                            admissible=len(sources.images) <= 8 and sum(len(s.text) for s in sources.records) <= 60000)
        except (OSError, ValueError, KeyError) as error:
            selected['error_type'] = type(error).__name__
            selected['detail'] = str(error)[:2000] if isinstance(error, ValueError) else 'source_unavailable'
        write(folder / 'selection.json', selected)
        cases.append(dict(**case.model_dump(), **selected))
    schedule = [dict(id=f'{case.id}.r{repeat:02d}', case_id=case.id, repeat=repeat) for repeat in range(1, repeats + 1) for case in suite.cases]
    plan = dict(schema_version='baseline-transfer-plan-v1', suite_id=suite.id, created_at=now(), scope=suite.scope,
                repeats=repeats, archive_path=str(archive.resolve()), manifest_path=str(manifest.resolve()),
                archive_sha256=digest(archive.read_bytes()), trust_manifest_sha256=digest(manifest.read_bytes()),
                method=public_settings(settings), implementation=implementation(), ar_resources=render_resources(repo_root),
                cases=cases, schedule=schedule, inputs=files(inputs), stop_on_success=False,
                no_gt_input=True, model_training_novelty='unknown', hardware_evaluation=False)
    write(output / 'plan.json', plan)
    return plan


def check_plan(folder, settings=None, *, check_code=False):
    plan = read(folder / 'plan.json')
    if plan['schema_version'] != 'baseline-transfer-plan-v1' or files(folder / 'inputs') != plan['inputs']:
        raise ValueError('Evaluation plan input files changed')
    suite = Suite.model_validate_json((folder / 'inputs/suite.json').read_bytes())
    expected = [dict(id=f'{c.id}.r{r:02d}', case_id=c.id, repeat=r) for r in range(1, plan['repeats'] + 1) for c in suite.cases]
    if expected != plan['schedule'] or plan['stop_on_success'] is not False:
        raise ValueError('Evaluation schedule changed')
    if settings is not None and public_settings(settings) != plan['method']:
        raise ValueError('Model settings differ from the frozen evaluation method; create a new plan')
    if check_code and implementation() != plan['implementation']:
        raise ValueError('Implementation changed; use a new plan instead of mixing methods')
    if check_code and (platform.python_version() != plan['method']['python'] or
                      any(importlib.metadata.version(n) != version for n, version in plan['method']['dependencies'].items())):
        raise ValueError('Evaluation Python/dependency versions changed')
    return plan


class RecordedClient:
    def __init__(self, client, folder):
        self.client, self.folder, self.kind, self.count = client, folder, client.kind, 0
        folder.mkdir()

    def call(self, prompt, schema, images):
        self.count += 1
        path = self.folder / f'{self.count:02d}.json'
        record = dict(started_at=now(), returned=False, prompt_sha256=digest(prompt.encode()),
                      schema_sha256=digest(encoded(schema)), images_sha256=[digest(raw) for raw in images])
        write(path, record)
        started = time.monotonic()
        try:
            response, metadata = self.client.call(prompt, schema, images)
            record.update(returned=True, provider=metadata)
            return response, metadata
        except Exception as error:
            record['error_type'] = type(error).__name__
            raise
        finally:
            record['elapsed_ms'] = round(1000 * (time.monotonic() - started))
            write(path, record)


def run_plan(folder, settings, *, client_factory=None):
    # The experiment is a single writer; a second runner must not consume an in-flight trial.
    import fcntl
    with (folder / 'run.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('This evaluation plan already has a running worker') from None
        return _run_plan(folder, settings, client_factory=client_factory)


def _run_plan(folder, settings, *, client_factory=None):
    plan = check_plan(folder, settings, check_code=True)
    plan_sha = digest((folder / 'plan.json').read_bytes())
    trials = folder / 'trials'
    trials.mkdir(exist_ok=True)
    cases = {c['id']: c for c in plan['cases']}
    for trial in plan['schedule']:
        check_plan(folder, settings, check_code=True)
        path = trials / trial['id']
        if (path / 'result.json').exists():
            verify_trial(path, plan_sha)
            continue
        interrupted = path.exists()
        path.mkdir(exist_ok=True)
        result = dict(**trial, plan_sha256=plan_sha, started_at=now(), status='interrupted' if interrupted else 'running')
        if not interrupted:
            write(path / 'started.json', result)
            case = cases[trial['case_id']]
            try:
                if not case['retrieval_pass']:
                    result['status'] = 'retrieval_failed'
                elif not case['admissible']:
                    result['status'] = 'input_unsupported'
                else:
                    sources, root, metadata = retrieve(plan['archive_path'], plan['manifest_path'], case['intent'], device_path=case['device_path'], assembly_context=True)
                    frozen = folder / 'inputs' / case['id']
                    if sources.model_dump() != read(frozen / 'sources.json') or metadata != read(frozen / 'retrieval.json'):
                        raise ValueError('Official inputs changed after evaluation freeze')
                    client = RecordedClient(client_factory() if client_factory else CompatibleClient(settings, max_tokens=16000), path / 'calls')
                    compiled = compile_task(sources, root, metadata, case['intent'], folder / 'inputs/capabilities.json', client,
                                            path / 'compilation', ar_resources=plan['ar_resources'])
                    result['status'] = compiled['status']
            except KeyboardInterrupt:
                result['status'] = 'interrupted'
                finish_trial(path, result)
                raise
            except Exception as error:
                result.update(status='failed', error_type=type(error).__name__)
        finish_trial(path, result)
        print(trial['id'] + ': ' + result['status'], flush=True)
    return report(folder, folder / 'report') if not (folder / 'report').exists() else None


def finish_trial(path, result):
    temporary = path / 'result.json.tmp'
    if temporary.exists():
        index = 1
        while (path / f'interrupted-result-{index}.json').exists():
            index += 1
        temporary.rename(path / f'interrupted-result-{index}.json')
    result.update(finished_at=now(), evidence=files(path))
    write(path / 'result.json', result)


def verify_trial(path, plan_sha):
    result = read(path / 'result.json')
    actual = files(path)
    actual.pop('result.json')
    if result['plan_sha256'] != plan_sha or actual != result['evidence']:
        raise ValueError('Evaluation trial evidence changed: ' + path.name)
    return result


def trial_row(path, result):
    compiled = path / 'compilation'
    contract = (compiled / 'compile-stage.json').exists() and read(compiled / 'compile-stage.json')['contract_pass'] is True
    diagnostics = read(compiled / 'compile-stage.json')['diagnostics'] if contract else []
    semantic = read(compiled / 'review.json')['semantic']['faithful'] if (compiled / 'review.json').exists() else None
    calls = [read(p) for p in sorted((path / 'calls').glob('*.json'))]
    usage = Counter()
    for call in calls:
        usage.update(call.get('provider', {}).get('usage', {}))
    row = dict(trial_id=result['id'], case_id=result['case_id'], repeat=result['repeat'], status=result['status'],
               contract_pass=bool(contract), compile_first_response_pass=bool(contract and not (compiled / 'compile-response-1.txt').exists()),
               method_supported=bool(contract and not any(not d.startswith('unsupported_ar_') for d in diagnostics)),
               ar_catalog_covered=bool(contract and not any(d.startswith('unsupported_ar_') for d in diagnostics)),
               semantic_model_pass=semantic, experimental_ready=result['status'] == 'experimental_ready',
               http_attempts=len(calls), returned_model_calls=sum(c['returned'] for c in calls),
               usage_reported_calls=sum(bool(c.get('provider', {}).get('usage')) for c in calls), usage=dict(usage),
               diagnostics=diagnostics, compilation_manifest_sha256=None, task_sha256=None, human='pending')
    if (compiled / 'failure.json').exists():
        row['failure'] = read(compiled / 'failure.json')
    if contract:
        proposal = Proposal.model_validate_json((compiled / 'proposal.json').read_bytes())
        protocol, checked = lower(proposal, Sources.model_validate_json((compiled / 'sources.json').read_bytes()), read(compiled / 'capabilities.json'))
        if checked != diagnostics or proposal.task.model_dump() != read(compiled / 'task.json') or protocol.model_dump() != read(compiled / 'protocol.json'):
            raise ValueError('Evaluation compiled-stage contract mismatch')
        row.update(task_sha256=digest(encoded(proposal.task.model_dump())),
                   compilation_manifest_sha256=digest((compiled / 'manifest.json').read_bytes()) if (compiled / 'manifest.json').exists() else None,
                   nodes=len(proposal.task.nodes), conditions=dict(Counter(c.channel for c in proposal.task.conditions)))
    return row


def ratio(numerator, denominator):
    return dict(numerator=numerator, denominator=denominator, rate=numerator / denominator if denominator else None)


def metrics(rows, scheduled):
    reviewed = [r for r in rows if r['human'] != 'pending']
    approved = sum(r['human'] == 'approved' for r in reviewed)
    contracts = sum(r['contract_pass'] for r in rows)
    reviewable = sum(r['contract_pass'] and bool(r['compilation_manifest_sha256']) for r in rows)
    final_approval = ratio(approved, scheduled)
    if len(reviewed) != reviewable or len(rows) != scheduled or not reviewed:
        final_approval['rate'] = None
    result = dict(scheduled=scheduled, completed=len(rows), model_attempted_trials=sum(r['http_attempts'] > 0 for r in rows),
                statuses=dict(Counter(r['status'] for r in rows)),
                vlm_compile_success=ratio(contracts, scheduled),
                vlm_compile_success_given_model_attempt=ratio(contracts, sum(r['http_attempts'] > 0 for r in rows)),
                first_response_contract=ratio(sum(r['compile_first_response_pass'] for r in rows), scheduled),
                method_supported=ratio(sum(r['method_supported'] for r in rows), scheduled),
                ar_catalog_covered=ratio(sum(r['ar_catalog_covered'] for r in rows), scheduled),
                same_model_semantic_pass=ratio(sum(r['semantic_model_pass'] is True for r in rows), contracts),
                experimental_ready=ratio(sum(r['experimental_ready'] for r in rows), scheduled),
                reviewable=reviewable, human_review_coverage=ratio(len(reviewed), reviewable), human_approval_given_review=ratio(approved, len(reviewed)),
                human_approved_over_scheduled=final_approval,
                http_attempts=sum(r['http_attempts'] for r in rows), returned_model_calls=sum(r['returned_model_calls'] for r in rows),
                usage_reported_calls=sum(r['usage_reported_calls'] for r in rows),
                usage=dict(sum((Counter(r['usage']) for r in rows), Counter())))
    if len(rows) != scheduled:
        for key, value in result.items():
            if isinstance(value, dict) and 'rate' in value and key not in ('human_review_coverage', 'human_approval_given_review'):
                value['rate'] = None
    return result


def report(folder, output, *, labels_path=None):
    plan = check_plan(folder, check_code=True)
    plan_sha = digest((folder / 'plan.json').read_bytes())
    cases = {c['id']: c for c in plan['cases']}
    rows = []
    for trial in plan['schedule']:
        path = folder / 'trials' / trial['id']
        if (path / 'result.json').exists():
            result = verify_trial(path, plan_sha)
            if any(result[key] != trial[key] for key in trial):
                raise ValueError('Trial does not match the frozen schedule')
            rows.append(dict(**trial_row(path, result), split=cases[trial['case_id']]['split']))
    reviewable = {r['trial_id']: r for r in rows if r['contract_pass'] and r['compilation_manifest_sha256']}
    if labels_path:
        labels = HumanLabels.model_validate_json(labels_path.read_bytes())
        if labels.plan_sha256 != plan_sha or len({l.trial_id for l in labels.labels}) != len(labels.labels):
            raise ValueError('Labels belong to a different plan or contain duplicate trials')
        for label in labels.labels:
            row = reviewable.get(label.trial_id)
            if row is None or any(getattr(label, k) != row[k] for k in ('compilation_manifest_sha256', 'task_sha256')):
                raise ValueError('Human label does not match a sealed candidate')
            row['human'] = label.decision
    summary = dict(schema_version='baseline-transfer-results-v1', plan_sha256=plan_sha, scope=plan['scope'],
                   method=plan['method'], overall=metrics(rows, len(plan['schedule'])),
                   by_split={split: metrics([r for r in rows if r['split'] == split], sum(cases[t['case_id']]['split'] == split for t in plan['schedule'])) for split in sorted({c['split'] for c in cases.values()})},
                   by_case={cid: metrics([r for r in rows if r['case_id'] == cid], plan['repeats']) for cid in cases},
                   retrieval_selection=ratio(sum(c['retrieval_pass'] for c in cases.values()), len(cases)),
                   rows=rows, hardware_tested=False, semantic_accuracy=None)
    complete_cases = [cid for cid in cases if sum(r['case_id'] == cid for r in rows) == plan['repeats']]
    summary['complete_case_coverage'] = ratio(len(complete_cases), len(cases))
    summary['at_least_one_contract_per_complete_case'] = ratio(sum(any(r['contract_pass'] for r in rows if r['case_id'] == cid) for cid in complete_cases), len(complete_cases))
    output.mkdir(parents=True, exist_ok=False)
    write(output / 'results.json', summary)
    template = HumanLabels(schema_version='baseline-transfer-labels-v1', plan_sha256=plan_sha,
        labels=[HumanLabel(trial_id=r['trial_id'], compilation_manifest_sha256=r['compilation_manifest_sha256'], task_sha256=r['task_sha256']) for r in reviewable.values()])
    write(output / 'human-labels.json', template.model_dump())
    if labels_path:
        (output / 'submitted-labels.json').write_bytes(labels_path.read_bytes())
    sheets = output / 'review'
    sheets.mkdir()
    for row in reviewable.values():
        compiled = folder / 'trials' / row['trial_id'] / 'compilation'
        proposal = Proposal.model_validate_json((compiled / 'proposal.json').read_bytes())
        task = proposal.task
        sources = Sources.model_validate_json((compiled / 'sources.json').read_bytes())
        records = {s.id: s for s in sources.records}
        case = cases[row['case_id']]
        sheet = ['# ' + row['trial_id'], '', '本页供人工独立核对，不使用同模型的语义复核作为答案。', '',
                 '目标：' + case['intent'], '', '限定范围：' + case['scope_note'], '',
                 '任务 SHA：`' + row['task_sha256'] + '`', '', '## 原始官方章节', '']
        for source in sources.records:
            sheet += [source.text, '', f'出处：[官方原文]({source.source_url})；`{source.id}`', '']
        for picture in sorted(compiled.glob('official-*.jpg')):
            sheet += ['![官方参考图](' + str(picture) + ')', '']
        sheet += ['## 生成的操作与依赖', '']
        for node in task.nodes:
            sheet += [f'- `{node.id}`：{node.instruction}；依赖：{", ".join(node.depends_on) or "无"}；完成条件：{", ".join(node.completion_ids)}']
        sheet += ['', '## 生成的要求', '']
        for requirement in task.requirements:
            sheet += [f'- `{requirement.id}` [{requirement.kind}]：{requirement.quote}（{records[requirement.source_id].id}）']
        sheet += ['', '## 生成的检查条件', '']
        for condition in task.conditions:
            sheet += [f'- `{condition.id}` [{condition.channel} / {proposal.methods[condition.id]}]：{condition.statement}；要求：{", ".join(condition.requirement_ids)}；定义：{condition.definition}']
        sheet += ['', '## 观察、判定及能力缺口', '', '```json', json.dumps(dict(queries=[q.model_dump() for q in proposal.queries],
                    rules=[r.model_dump() for r in proposal.rules], diagnostics=row['diagnostics'], limitations=proposal.limitations), ensure_ascii=False, indent=2), '```', '',
                  '请在 human-labels.json 的本次 trial_id 下填写四项、decision、reviewer、note。没有现场资料就不判断实物正确或视觉准确率。', '']
        (sheets / (row['trial_id'] + '.md')).write_text('\n'.join(sheet), encoding='utf-8')
    lines = ['# 未见任务与设备评价', '', plan['scope'], '',
        '固定排程全部计入分母；格式修复是同一次生成尝试。编译成功指提案通过契约，不代表语义正确；同模型复核、方法能力及AR目录覆盖分别统计。', '',
        '| 分组 | 已结束/排程 | 编译契约 | 方法支持 | AR目录覆盖 | 可试用 | 人审覆盖 | 人审通过 |',
        '| --- | --- | --- | --- | --- | --- | --- | --- |']
    def display(value):
        return f"{value['numerator']}/{value['denominator']}" if value['rate'] is not None else f"未评价（已计 {value['numerator']}/{value['denominator']}）"
    for name, value in [('全部', summary['overall']), *summary['by_split'].items()]:
        lines.append('| ' + ' | '.join([name, f"{value['completed']}/{value['scheduled']}", *[display(value[k]) for k in ('vlm_compile_success', 'method_supported', 'ar_catalog_covered', 'experimental_ready', 'human_review_coverage', 'human_approval_given_review')]]) + ' |')
    lines += ['', '## 固定任务范围与检索', '', '| 任务 | 分组 | 检索 | 评价范围 |', '| --- | --- | --- | --- |']
    for case in cases.values():
        lines.append(f"| {case['id']} | {case['split']} | {case['retrieval_pass']} | {case['scope_note']} |")
    lines += ['', '期望 URL 与标题只作检索后的评价，不指定检索结果，也不送入编译提示。错页、范围不全或缺失来源的试次保留，不调用模型编译错误材料。',
              '', '## 逐次结果', '', '| 尝试 | 状态 | 编译契约 | 人工 | 审核材料 |', '| --- | --- | --- | --- | --- |']
    for row in rows:
        path = folder / 'trials' / row['trial_id'] / 'compilation'
        destination = sheets / (row['trial_id'] + '.md') if row['trial_id'] in reviewable else path
        lines.append(f"| {row['trial_id']} | {row['status']} | {row['contract_pass']} | {row['human']} | [产物]({destination}) |")
    lines += ['', '## 人工审核', '', '编辑 human-labels.json 的副本，不修改原始候选。四项均逐一对照原文与图片：', '',
        '- task_scope：任务、设备、选中章节范围正确；没有把局部操作冒称整页流程。',
        '- requirements：要求忠实完整，数量／选材／可选项无误，没有编造或漏项。',
        '- dependencies：操作顺序、前置依赖、目标闭包正确，未因用户声明跳过节点。',
        '- verification：视觉、人工、未知及能力缺口合理，没有以外观代替紧固等隐藏状态。', '',
        '每项取 pending/pass/fail；decision 为 pending/approved/rejected。提交决定须填 reviewer、note，批准要求四项全部 pass，拒绝至少一项 fail。',
        '请逐次审核而非只挑成功样本。人工结果只用于离线评价，不激活AR或改写GT。', '',
        '逐次审核页在 review/，包括原文、官方图片、操作、要求和视觉规则；完整产物保留在各试次 compilation/。',
        '尚无物理现场或视觉标签评价；同模型复核不充当人工标签。样本量小，重复共享相同来源，不视为独立设备样本。', '']
    (output / 'REPORT.md').write_text('\n'.join(lines), encoding='utf-8')
    write(output / 'evidence-manifest.json', dict(plan_sha256=plan_sha, files=files(output)))
    return summary
