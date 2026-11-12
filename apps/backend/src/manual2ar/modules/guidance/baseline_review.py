"""Read frozen evaluations, save versioned human labels, and open registered experiments."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import threading
import uuid

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import Field

from manual2ar.paths import ROOT
from manual2ar_baseline.compiler import Proposal
from manual2ar_baseline.evaluation import HumanLabel, HumanLabels, check_plan, metrics, verify_trial
from manual2ar_baseline.gt import Digest, Strict, Sources, digest, encoded
from manual2ar_baseline.vision import Protocol
from .official_compiler import Use
from .spatial.service import atomic_json


class Review(Strict):
    plan_sha256: Digest
    revision: int = Field(ge=0)
    label: HumanLabel


class Experiment(Use):
    plan_sha256: Digest


METHODS = {'vision.mount_relation':'视觉：安装位置与贴靠', 'vision.connection_relation':'视觉：外部连接',
    'vision.fastener_instances':'视觉：固定件位置联合检查', 'vision.appearance':'视觉：可见外观',
    'manual.direction':'人工：对照官方方向', 'manual.mechanical_security':'人工：实际机械紧固',
    'manual.other':'人工：官方明确要求的检查', 'unsupported':'当前方法不支持'}
KINDS = {'operation':'操作', 'outcome':'结果要求', 'specification':'数量等要求', 'material_selection':'选材',
         'applicability':'适用范围', 'observation_boundary':'观察边界'}
EXPECTED = {'seated':'可见安装贴合', 'connected':'清楚可见连接', 'separate':'可见分离', 'absent':'未安装',
    'no_visible_anomaly':'未见明显异常', 'visible_detachment':'可见脱离', 'visible_tilt':'可见倾斜', 'visible_missing_part':'可见缺件'}
GAPS = {'unsupported_ar_coverage':'现有 AR 资产未覆盖完整任务', 'unsupported_ar_action':'存在未登记的 AR 动作',
        'unsupported_roi_parent_mapping':'无法唯一关联局部检查与整图定位区域', 'unresolved_task_definition':'存在尚未定义的任务条件'}


class BaselineReview:
    def __init__(self, config, compiler):
        self.compiler = compiler
        self.root = Path(config['runtime_dir']) / 'baseline-review'
        self.archive_root = Path(config['runtime_dir']).resolve().parent / 'baseline'
        self.specs = json.loads((ROOT / 'resources/evaluation/v1/catalog.json').read_bytes())['plans']
        self.plans = {}
        self.lock = threading.RLock()

    def register(self, folder, spec):
        """Trusted local registration only; the HTTP API never accepts filesystem paths."""
        raw = (folder / 'evidence-manifest.json').read_bytes()
        if digest(raw) != spec['archive_manifest_sha256'] or digest((folder / 'plan.json').read_bytes()) != spec['plan_sha256']:
            raise ValueError('Evaluation registration fingerprints differ')
        manifest = json.loads(raw)
        for name, sha in manifest['files'].items():
            path = (folder / name).resolve()
            path.relative_to(folder.resolve())
            if digest(path.read_bytes()) != sha:
                raise ValueError('Frozen evaluation file changed')
        plan = check_plan(folder)
        for trial in plan['schedule']:
            verify_trial(folder / 'trials' / trial['id'], spec['plan_sha256'])
        results = json.loads((folder / 'report/results.json').read_bytes())
        if results['plan_sha256'] != spec['plan_sha256']:
            raise ValueError('Evaluation report belongs to a different plan')
        self.plans[spec['id']] = dict(folder=folder, spec=deepcopy(spec), manifest=manifest, plan=plan, results=results)

    def plan(self, identity):
        if identity not in self.plans:
            spec = next((s for s in self.specs if s['id'] == identity), None)
            if spec is None:
                raise HTTPException(404, '没有该评价集。')
            folder = (self.archive_root / spec['folder']).resolve()
            folder.relative_to(self.archive_root.resolve())
            if not folder.is_dir():
                raise HTTPException(503, '本机尚未安装这份评价归档。')
            try:
                self.register(folder, spec)
            except (OSError, ValueError, KeyError):
                raise HTTPException(409, '评价归档未通过固定版本校验。') from None
        value = self.plans[identity]
        try:
            valid = digest((value['folder'] / 'evidence-manifest.json').read_bytes()) == value['spec']['archive_manifest_sha256']
        except OSError:
            valid = False
        if not valid:
            raise HTTPException(409, '评价归档版本已改变。')
        return value

    def checked(self, plan, name):
        if name not in plan['manifest']['files']:
            raise HTTPException(404, '没有这份评价材料。')
        path = (plan['folder'] / name).resolve()
        path.relative_to(plan['folder'].resolve())
        try:
            raw = path.read_bytes()
        except OSError:
            raise HTTPException(409, '原始评价材料暂不可读取。') from None
        if digest(raw) != plan['manifest']['files'].get(name):
            raise HTTPException(409, '原始评价材料已改变，请恢复冻结版本。')
        return raw

    def labels(self, identity):
        plan = self.plan(identity)
        path = self.root / identity / 'current.json'
        if path.exists():
            try:
                value = json.loads(path.read_bytes())
                labels = HumanLabels.model_validate(value['labels'])
                if type(value['revision']) is not int or value['revision'] < 1:
                    raise ValueError('Invalid review revision')
            except (OSError, ValueError, KeyError):
                raise HTTPException(409, '人工审核记录未通过校验，请保留历史记录后恢复。') from None
            if labels.plan_sha256 != plan['spec']['plan_sha256']:
                raise HTTPException(409, '人工审核记录与归档版本不一致。')
            expected = HumanLabels.model_validate_json(self.checked(plan, 'report/human-labels.json'))
            binding = lambda items: {l.trial_id:(l.task_sha256,l.compilation_manifest_sha256) for l in items}
            if len(labels.labels) != len(expected.labels) or binding(labels.labels) != binding(expected.labels):
                raise HTTPException(409, '人工审核标签的候选绑定不完整或已改变。')
            return value
        labels = HumanLabels.model_validate_json(self.checked(plan, 'report/human-labels.json'))
        return dict(revision=0, labels=labels.model_dump())

    def summary(self, identity):
        plan = self.plan(identity)
        current = self.labels(identity)
        rows = deepcopy(plan['results']['rows'])
        decisions = {l['trial_id']:l['decision'] for l in current['labels']['labels']}
        for row in rows:
            row['human'] = decisions.get(row['trial_id'], 'pending')
        value = metrics(rows, len(plan['plan']['schedule']))
        return dict(id=identity, title=plan['spec']['title'], revision=current['revision'], scheduled=value['scheduled'],
            contract_pass=value['vlm_compile_success']['numerator'], reviewed=value['human_review_coverage']['numerator'],
            approved=value['human_approval_given_review']['numerator'],
            human_rate=('未评价' if value['human_approval_given_review']['rate'] is None else f"{value['human_approval_given_review']['rate']:.0%}"))

    def catalog(self):
        output = []
        for identity in dict.fromkeys([s['id'] for s in self.specs] + list(self.plans)):
            try:
                output.append(dict(**self.summary(identity), available=True))
            except (HTTPException, OSError, ValueError):
                spec = next((s for s in self.specs if s['id']==identity), {'title':identity})
                output.append(dict(id=identity, title=spec['title'], available=False))
        return dict(contract='baseline-review-v1', plans=output)

    def trials(self, identity):
        plan = self.plan(identity)
        current = self.labels(identity)
        cases = {c['id']:c for c in plan['plan']['cases']}
        labels = {l['trial_id']:l for l in current['labels']['labels']}
        rows = []
        for row in plan['results']['rows']:
            case = cases[row['case_id']]
            rows.append(dict(trial_id=row['trial_id'], intent=case['intent'], device=case['device_id'],
                repeat=row['repeat'], status=row['status'], contract_pass=row['contract_pass'],
                decision=labels.get(row['trial_id'], {}).get('decision','pending'),
                can_experiment=row['trial_id'] in plan['spec']['experiment_trials'] and row['experimental_ready']))
        return dict(**self.summary(identity), trials=rows)

    def candidate(self, identity, trial):
        plan = self.plan(identity)
        row = next((r for r in plan['results']['rows'] if r['trial_id'] == trial), None)
        if row is None:
            raise HTTPException(404, '没有该生成尝试。')
        case = next(c for c in plan['plan']['cases'] if c['id']==row['case_id'])
        prefix = f'trials/{trial}/compilation/'
        result = dict(plan_sha256=plan['spec']['plan_sha256'], trial_id=trial, intent=case['intent'],
            scope=case['scope_note'], status=row['status'], contract_pass=row['contract_pass'],
            can_experiment=trial in plan['spec']['experiment_trials'] and row['experimental_ready'],
            revision=self.labels(identity)['revision'], task_sha256=row['task_sha256'],
            compilation_manifest_sha256=row['compilation_manifest_sha256'], text='', official_text='', images=[])
        if not row['contract_pass']:
            result['text'] = '本次未形成通过契约的候选，不计人工审核通过率。\n\n'
            if row['status']=='retrieval_failed':
                retrieval = json.loads(self.checked(plan, f"inputs/{row['case_id']}/retrieval.json"))
                result['text'] += '实际检索：' + retrieval['source_url'] + '\n' + ' → '.join(retrieval['parent_heading'])
                result['text'] += '\n预定范围：' + case['expected_source_url'] + '\n' + ' → '.join(case['expected_heading'])
            else:
                failure = json.loads(self.checked(plan, prefix+'failure.json'))
                result['text'] += failure['detail']
            return result
        try:
            verify_trial(plan['folder'] / 'trials' / trial, plan['spec']['plan_sha256'])
        except (OSError, ValueError):
            raise HTTPException(409, '候选的原始试次证据已改变。') from None
        proposal = Proposal.model_validate_json(self.checked(plan, prefix+'proposal.json'))
        task = proposal.task
        protocol = Protocol.model_validate_json(self.checked(plan, prefix+'protocol.json'))
        sources = Sources.model_validate_json(self.checked(plan, prefix+'sources.json'))
        result['official_text'] = '\n\n'.join(f"{s.text}\n来源：{s.source_url}" for s in sources.records)
        text = ['操作与依赖']
        node_names = {n.id:n.instruction for n in task.nodes}
        conditions = {c.id:c.statement for c in task.conditions}
        for i, node in enumerate(task.nodes,1):
            dependencies = '；'.join(node_names[n] for n in node.depends_on) or '无'
            text += [f'{i}. {node.instruction}\n前置操作：{dependencies}\n完成条件：'+'；'.join(conditions[c] for c in node.completion_ids)]
            if node.precondition_ids:
                text += ['执行前需满足：'+'；'.join(conditions[c] for c in node.precondition_ids)]
        text += ['任务目标：'+'；'.join(conditions[c] for c in task.goal_condition_ids)]
        text += ['', '检查条件']
        reqs = {r.id:r for r in task.requirements}
        for i, condition in enumerate(task.conditions,1):
            rules = [r for r in proposal.rules if r.condition_id==condition.id]
            details = [f"{i}. {condition.statement}", METHODS[proposal.methods[condition.id]], condition.definition,
                       '依据：' + '；'.join(reqs[r].quote for r in condition.requirement_ids)]
            for rule in rules:
                query = next(q for q in proposal.queries if q.id==rule.query_id)
                details += ['观察：' + query.instruction, '判定：' + (EXPECTED[rule.expected_value] if rule.expected_value else '可见固定件须联合覆盖位置：' + '、'.join(rule.expected_locations))]
            text.append('\n'.join(details))
        text += ['', '官方要求映射'] + [KINDS[r.kind] + '：' + r.quote for r in task.requirements]
        if protocol.refinement:
            queries = {q.id:q for q in protocol.queries}
            text += ['', '实际图像检查流程：先定位“'+queries[protocol.refinement.source_query_id].instruction+'”，再在裁剪区域检查“'
                     +'；'.join(queries[q].instruction for q in protocol.refinement.detail_query_ids)+'”。裁剪不产生新拍摄视角；看不清或无法定位时保留未知。']
        text += ['', '能力缺口与生成限制'] + [GAPS.get(d,d) for d in row['diagnostics']] + proposal.limitations
        result['text'] = '\n\n'.join(text)
        for name in sorted(plan['manifest']['files']):
            if name.startswith(prefix+'official-') and name.endswith('.jpg'):
                result['images'].append(dict(url=f'/api/guidance/reviews/{identity}/trials/{trial}/images/{Path(name).name}', sha256=plan['manifest']['files'][name]))
        result['label'] = next(l for l in self.labels(identity)['labels']['labels'] if l['trial_id']==trial)
        return result

    def save(self, identity, trial, command):
        with self.lock:
            candidate = self.candidate(identity, trial)
            label = command.label
            if (not candidate['contract_pass'] or command.plan_sha256 != candidate['plan_sha256'] or label.trial_id != trial
                    or label.task_sha256 != candidate['task_sha256'] or label.compilation_manifest_sha256 != candidate['compilation_manifest_sha256']):
                raise HTTPException(409, '审核意见不属于当前候选版本。')
            current = self.labels(identity)
            if command.revision != current['revision']:
                raise HTTPException(409, '审核记录已被另一窗口更新，请刷新后再保存。')
            next_labels = deepcopy(current['labels'])
            next_labels['labels'] = [label.model_dump() if l['trial_id']==trial else l for l in next_labels['labels']]
            value = dict(revision=current['revision']+1, saved_at=datetime.now(timezone.utc).isoformat(), labels=next_labels)
            atomic_json(self.root / identity / 'history' / (f"{value['revision']:06d}-" + uuid.uuid4().hex + '.json'), value)
            atomic_json(self.root / identity / 'current.json', value)
            return self.summary(identity)

    def export(self, identity):
        with self.lock:
            value = self.labels(identity)
            folder = self.root / identity / 'exports' / (f"r{value['revision']:06d}-" + uuid.uuid4().hex[:8])
            atomic_json(folder / 'human-labels.json', value['labels'])
            atomic_json(folder / 'summary.json', self.summary(identity))
            return dict(message='审核标签与统计已导出。', path=str(folder), labels=value['labels'], summary=self.summary(identity))

    def experiment(self, identity, trial, command):
        with self.lock:
            candidate = self.candidate(identity,trial)
            if (not candidate['can_experiment'] or command.plan_sha256 != candidate['plan_sha256']
                    or command.manifest_sha256 != candidate['compilation_manifest_sha256']):
                raise HTTPException(409, '该候选没有登记为可执行的 U7 实验版本。')
            plan = self.plan(identity)
            job = uuid.uuid5(uuid.NAMESPACE_URL, candidate['plan_sha256'] + '/' + trial).hex
            folder = plan['folder'] / 'trials' / trial / 'compilation'
            try:
                repeat = next(r['repeat'] for r in plan['results']['rows'] if r['trial_id']==trial)
                self.compiler.import_candidate(folder, identity=job, expected_sha256=command.manifest_sha256,
                    provenance=dict(plan_sha256=candidate['plan_sha256'], trial_id=trial, intent=candidate['intent'], title=f'U7 自动候选 · 第 {repeat} 次'))
                return self.compiler.use(job, Use(manifest_sha256=command.manifest_sha256, acknowledge_experimental=True))
            except (OSError, ValueError):
                raise HTTPException(409, '候选或其官方来源不再满足执行契约。') from None


def install(app, config, compiler):
    service = BaselineReview(config, compiler)
    api = APIRouter(prefix='/api/guidance/reviews', tags=['baseline-human-review'])
    @api.get('')
    def catalog():return service.catalog()
    @api.get('/{identity}')
    def trials(identity:str):return service.trials(identity)
    @api.get('/{identity}/trials/{trial}')
    def candidate(identity:str,trial:str):return service.candidate(identity,trial)
    @api.post('/{identity}/trials/{trial}/review')
    def save(identity:str,trial:str,command:Review):return service.save(identity,trial,command)
    @api.post('/{identity}/trials/{trial}/use')
    def experiment(identity:str,trial:str,command:Experiment):return service.experiment(identity,trial,command)
    @api.post('/{identity}/export')
    def export(identity:str):return service.export(identity)
    @api.get('/{identity}/trials/{trial}/images/{name}')
    def image(identity:str,trial:str,name:str):
        plan=service.plan(identity)
        if not name.startswith('official-') or '/' in name or not name.endswith('.jpg'):
            raise HTTPException(404)
        service.candidate(identity,trial)
        return Response(service.checked(plan,f'trials/{trial}/compilation/{name}'),media_type='image/jpeg',headers={'Cache-Control':'no-store'})
    app.include_router(api)
    return service
