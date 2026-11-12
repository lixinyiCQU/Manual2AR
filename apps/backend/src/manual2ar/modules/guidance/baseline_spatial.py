"""Host adapter: baseline owns evidence; existing spatial code owns calibrated rendering."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import time
import uuid

from fastapi import HTTPException
from pydantic import Field

from manual2ar.paths import ROOT
from manual2ar_baseline.ar import Bindings
from manual2ar_baseline.gt import Digest, Identity, Strict, Text, digest, encoded, load_bundle
from manual2ar_baseline.goals import hierarchy, resolve_goal
from manual2ar_baseline.photos import confirm, observe
from manual2ar_baseline.provider import CompatibleClient, ModelError, Settings
from manual2ar_baseline.state import Session as EvidenceSession
from manual2ar_baseline.vision import Protocol
from .spatial.service import SpatialService, atomic_json
from .spatial.models import Verify


class Manual(Strict):
    action_id: Text
    epoch: int = Field(ge=0)
    revision: int = Field(ge=0)
    condition_ids: list[Identity] = Field(min_length=1, max_length=16)
    statement: Text
    session_id: Identity | None = None
    task_sha256: Digest | None = None


class GoalRequest(Strict):
    intent: str = Field(min_length=2, max_length=1000)


class BaselineSpatial(SpatialService):
    def __init__(self, config, registry, client, *, compilation=None, prefix='/api/guidance/baseline/spatial'):
        super().__init__(config, registry, client)
        self.reference_profiles = self.root / 'profiles'
        self.root = Path(config['runtime_dir']) / 'baseline-ar'
        self.compilation = compilation
        self.prefix = prefix
        self.reference_root = ROOT
        if compilation is None:
            gt = ROOT / 'baseline/ground_truth/u7/v1'
            self.bundle = gt / 'state-validation'
            self.sources, self.task = load_bundle(self.bundle)
            self.protocol = Protocol.model_validate_json((gt / 'visual-protocol-roi.json').read_bytes())
            self.bindings = Bindings.model_validate_json((gt / 'ar-bindings.json').read_bytes())
        else:
            from manual2ar_baseline.compiler import load_compilation
            self.compilation_sha = digest((compilation / 'manifest.json').read_bytes())
            self.sources, self.task, self.protocol, self.bindings, self.reference_root = load_compilation(compilation)
            if digest((compilation / 'manifest.json').read_bytes()) != self.compilation_sha:
                raise ValueError('Compilation changed while loading')
            self.root = self.root / ('compiled-' + compilation.parent.name)
        self.protocol.check(self.sources, self.task)
        hierarchy(self.task, self.sources)
        self.bindings.check(self.task, ROOT, self.actions, self.asset_library)
        ids = {p.action_id for p in self.bindings.presentations}
        self.plan = deepcopy(self.plan)
        self.plan['actions'] = [a for a in self.plan['actions'] if a['action_id'] in ids]
        self.plan['chapters'] = [c for c in self.plan['chapters'] if c['id'] == 'U7']
        self.actions = {a['action_id']: a for a in self.plan['actions']}
        if compilation is not None:
            nodes = {n.id: n for n in self.task.nodes}
            for binding in self.bindings.presentations:
                action = self.actions[binding.action_id]
                node = nodes[binding.node_id]
                action.update(instruction=node.instruction, official_text='\n'.join(r.quote for r in self.task.requirements if r.id in node.requirement_ids),
                    reference_images=[prefix + '/official-images/' + image.id for image in self.sources.images], primary_reference_index=0,
                    citation_ids=[s.citation_id for s in self.sources.records])
                checks = [r for r in self.protocol.rules if r.condition_id in node.completion_ids and r.expected_locations]
                if checks and any(len(r.expected_locations) > len(action['target_instances']) for r in checks):
                    raise ValueError('Existing AR action has too few target instances for the compiled task')
        self.photo_client = None

    def ledger(self, session):
        if not hasattr(session, 'baseline'):
            if self.compilation is None:
                session.baseline = EvidenceSession.from_bundle(self.bundle, 'ar.' + session.identity, self.task.title,
                    evidence_mode='experimental_photo_analysis', guidance_policy='scene_guided')
            else:
                from manual2ar_baseline.compiler import load_compilation
                _, task, _, _, _ = load_compilation(self.compilation)
                session.baseline = EvidenceSession(task, 'ar.' + session.identity, self.task.title,
                    evidence_mode='experimental_compiled_photo_analysis', guidance_policy='scene_guided')
            session.baseline_busy = False
        return session.baseline

    def execution(self, session):
        live = self.ledger(session)
        value = self.bindings.execution(live)
        selection = getattr(session, 'baseline_goal', None)
        value['goal_title'] = selection.title if selection else self.task.title
        statuses = {'verified':'本会话已核验通过', 'blocked':'前置操作待完成', 'not_completed':'视觉初筛未通过，待操作或复核',
                    'suspected_installed':'疑似完成，待人工确认', 'unknown':'现场状态尚未确认'}
        steps = value['steps']
        current = next((s for s in steps if s['current']), None)
        visual_node = live.nodes[current['node_id']] if current else live.nodes[value['state_id']]
        observed = getattr(session, 'baseline_visual_details', {})
        value['visual_conditions'] = []
        for c in visual_node.completion_ids:
            if live.conditions[c].channel != 'vision':
                continue
            fact, detail = live.facts[c], observed.get(c, {})
            evidence = detail.get('evidence', '') if fact.evidence_id is not None and fact.evidence_id == detail.get('evidence_id') else ''
            value['visual_conditions'].append(dict(id=c, statement=live.conditions[c].statement, value=fact.value,
                evidence=evidence, retained=fact.retained_on is not None))
        if value['baseline_mode'] == 'ask_manual':
            value['manual_conditions'] = [dict(id=c, statement=live.conditions[c].statement)
                for c in visual_node.completion_ids if live.conditions[c].channel == 'manual' and live.facts[c].value != 'true']
        value['current_step'] = ('第' + str(current['index']) + '/' + str(current['total']) + '步：' + current['instruction']) if current else '本次目标已完成'
        value['guidance_ready'] = value['guidance_allowed']
        official = ' → '.join(n.instruction for n in self.task.nodes)
        lines = ['本次目标：' + value['goal_title'], '官方操作流程：' + official, '现场进度：']
        for step in steps:
            label = '前置核实' if step['prerequisite_only'] else str(step['index']) + '/' + str(step['total'])
            lines.append(label + ' · ' + step['instruction'] + '：' + statuses[step['status']])
        remaining = [s['instruction'] for s in steps if s['status'] != 'verified']
        lines.append('剩余操作：' + (' → '.join(remaining) if remaining else '无，本次目标已完成'))
        if current:
            node = live.nodes[current['node_id']]
            supported = [live.conditions[c].statement for c in node.completion_ids
                         if live.conditions[c].channel == 'vision' and live.facts[c].value == 'true']
            if supported:
                lines.append('照片支持的可见状态：' + '；'.join(supported))
        if value['baseline_mode'] == 'ask_manual':
            pending = [live.conditions[c].statement for c in live.nodes[current['node_id']].completion_ids
                       if live.conditions[c].channel == 'manual' and live.facts[c].value != 'true'] if current else []
            lines.append('待人工核对：' + '；'.join(pending))
        elif value['guidance_ready']:
            lines.append('下一步：进入当前操作的 AR 指导；操作后再核验完成状态。')
        elif value['needs_assessment']:
            lines.append('请先拍摄现场，判断已有进度。')
        value['task_summary'] = '\n'.join(lines)
        value['scene_conditions'] = []
        overview = ['目标：' + value['goal_title']]
        objects = {o.id: o.name for o in self.task.objects}
        for step in steps:
            node = live.nodes[step['node_id']]
            visible = [c for c in node.completion_ids if live.conditions[c].channel == 'vision']
            rows = []
            for c in visible:
                fact, detail = live.facts[c], observed.get(c, {})
                evidence = detail.get('evidence', '') if fact.evidence_id is not None and fact.evidence_id == detail.get('evidence_id') else ''
                rows.append(dict(id=c, statement=live.conditions[c].statement, value=fact.value, evidence=evidence,
                                 retained=fact.retained_on is not None, step_index=step['index']))
            value['scene_conditions'].extend(rows)
            status = ('已完成' if step['status'] == 'verified' else
                      ('可见检查通过，前一步待确认' if step['status'] == 'blocked' else '可见检查通过，待人工确认') if visible and all(live.facts[c].value == 'true' for c in visible) else
                      '可见检查未通过' if any(live.facts[c].value == 'false' for c in visible) else '有部位未确认')
            overview.append('第' + str(step['index']) + '步（' + objects[node.object_ids[0]] + '）：' + status)
        value['user_summary'] = '\n'.join(overview)
        if value['complete']:
            feedback = '核验完成。'
        elif value['needs_assessment']:
            feedback = '请拍摄安装现场，点击“评估现场”。'
        elif value['baseline_mode'] == 'ask_manual':
            feedback = '当前步骤的照片检查通过。\n请核实下方人工项目。'
        elif any(r['value'] == 'false' for r in value['visual_conditions']):
            feedback = '本步尚未通过。\n请检查安装位置，调整后重新拍照。'
        else:
            feedback = '本步仍有部位未确认。\n请拍清未确认的部位后重拍。'
        value['user_feedback'] = feedback
        return value

    def goal_preview(self, intent):
        self.check_definition()
        try:
            selection = resolve_goal(self.task, self.sources, intent)
        except ValueError as error:
            return dict(status='clarification_required', requested_intent=intent, goal_title='', interpretation='',
                        message=str(error), selected_node_ids=[], official_steps=[], task_sha256=self.bindings.task_sha256)
        probe = EvidenceSession(self.task, 'preview.goal', intent, target_node_ids=selection.selected_node_ids)
        return dict(status='matched', requested_intent=intent, goal_title=selection.title, interpretation=selection.interpretation,
                    message='已对应官方任务；现场照片决定当前进度，所述完成情况不会自动记为已完成。',
                    selected_node_ids=selection.selected_node_ids, task_sha256=selection.task_sha256,
                    official_steps=[dict(node_id=n, instruction=probe.nodes[n].instruction, is_target=n in selection.selected_node_ids,
                                         prerequisite_only=n not in selection.selected_node_ids) for n in probe.order if n in probe.needed])

    def check_definition(self):
        if self.compilation is not None:
            from manual2ar_baseline.compiler import load_compilation
            try:
                if digest((self.compilation / 'manifest.json').read_bytes()) != self.compilation_sha:
                    raise ValueError('Compiled manifest revision changed')
                _, task, _, _, _ = load_compilation(self.compilation)
                if digest(encoded(task.model_dump())) != self.bindings.task_sha256:
                    raise ValueError('Compiled revision changed')
            except (OSError, ValueError):
                raise HTTPException(409, '编译任务或其官方来源已改变，请重新生成并核对候选。') from None

    def catalog(self):
        return {**super().catalog(), 'runtime_contract': 'baseline-ar-v1', 'stateful_runtime': True,
                'explicit_scene_assessment': True, 'batch_manual_confirmation': True,
                'task_sha256': self.bindings.task_sha256,
                'print_url': self.prefix + '/print.pdf', 'task_origin': 'automatic_official_compilation' if self.compilation else 'gt_reference',
                'experiment_title': getattr(self, 'experiment_title', ''),
                'default_goal_intent': getattr(self, 'default_goal_intent', self.task.title),
                'goal_overview': '官方操作流程：' + ' → '.join(n.instruction for n in self.task.nodes),
                'goal_hierarchy': hierarchy(self.task, self.sources)}

    def sequence_status(self, tutorial_run_id=''):
        return dict(enforced=False, base_approved=False, holder_approved=False,
                    message='基线会话独立核验，不继承原教程完成记录。')

    def u7_progress(self, session, callback=None):
        if callback is not None:
            raise HTTPException(409, '此入口只接受基线条件证据。')
        return {**self.sequence_status(), 'execution': self.execution(session)}

    def begin(self, command):
        self.check_definition()
        if command.tutorial_run_id:
            raise HTTPException(422, '基线入口不绑定旧教程进度。')
        selection = None
        if command.goal_intent.strip():
            try:
                selection = resolve_goal(self.task, self.sources, command.goal_intent.strip())
            except ValueError as error:
                raise HTTPException(422, str(error)) from None
        # Copy once per camera/rig, including empty profiles, so a reset never reimports old geometry.
        with self.profile_lock:
            for group, identity in [('cameras', command.camera_id)] + [(g, command.rig_id) for g in ('rigs', 'machines', 'motions', 'orientations', 'rig-validity')]:
                target = self.profile(group, identity)
                marker = target.with_suffix('.imported.json')
                if not marker.exists() and not target.exists():
                    source = self.reference_profiles / group / (identity + '.json')
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if source.exists():
                        shutil.copyfile(source, target)
                    atomic_json(marker, dict(source=str(source), sha256=digest(source.read_bytes()) if source.exists() else None))
        result = super().begin(command)
        with self.session(result['session_id']) as session:
            if selection:
                previous = self.ledger(session)
                session.baseline = EvidenceSession(previous.task, previous.id, selection.query, evidence_mode=previous.evidence_mode,
                    target_node_ids=selection.selected_node_ids, guidance_policy='scene_guided')
                session.baseline_goal = selection
                record = dict(**selection.model_dump(), guidance_policy='scene_guided', scope='immutable_session_goal_not_completion_evidence')
                atomic_json(self.root / 'runs' / session.identity / 'goal.json', record)
                self.event(session, 'baseline.goal.selected', dict(goal=record, execution=self.execution(session)))
            result['execution'] = self.execution(session)
            result['u7_sequence'] = self.u7_progress(session)
        return result

    def require_u7(self, session, action_id):
        if action_id != self.execution(session)['action_id']:
            raise HTTPException(409, '请按基线当前步骤核验，不能跳过或沿用旧步骤。')

    def frame(self, identity, request):
        with self.session(identity) as session:
            result = super().frame(identity, request)
            result['execution'] = self.execution(session)
            if result['execution']['mode'] != 'operate' or session.baseline_busy:
                result.update(visual=None, companion_visuals=[], lines=[], machine_axes=[], reference_axes=[])
            return result

    def check_reply(self, session, request, frame=None):
        execution = self.execution(session)
        return dict(action_id=request.action_id, target_id=getattr(request, 'target_id', 'main'),
                    client_frame_id=frame['client_frame_id'] if frame else 0,
                    source_sha256=frame['sha256'] if frame else '', execution=execution,
                    status='completed' if execution['complete'] else 'uncertain',
                    evidence=execution['reason'], next_action=execution['reason'],
                    scope=self.ledger(session).evidence_mode, u7_sequence=self.u7_progress(session))

    def verify(self, identity, request, *, reassess=False):
        self.check_definition()
        with self.session(identity) as session:
            frame = self.photo_frame(identity, request)
            live = self.ledger(session)
            if session.baseline_busy:
                raise HTTPException(409, '请等待当前核验完成。')
            session.baseline_busy = True
            prepared = deepcopy(live)
            stamp = live.stamp()
            current = live.plan()
            owners = live.needed if reassess or live.last_frame == 0 or current['mode'] == 'complete' else {current['node_id']}
            conditions_to_observe = {c for n in owners if n in live.nodes for c in live.nodes[n].completion_ids
                                     if live.conditions[c].channel == 'vision'}
            if not conditions_to_observe:
                session.baseline_busy = False
                raise HTTPException(409, '当前操作没有可执行的视觉检查，请核对任务方法。')
        folder = self.root / 'runs' / identity / ('check-' + uuid.uuid4().hex)
        image = folder / 'input.jpg'
        try:
            folder.mkdir(parents=True)
            image.write_bytes(frame['raw'])
            provider = self.photo_client
            if provider is None:
                provider = CompatibleClient(Settings.model_validate({k: self.config['vlm'][k] for k in Settings.model_fields if k in self.config['vlm']}))
            observe(prepared, self.sources, self.protocol, image, self.reference_root, folder / 'observation', provider,
                    condition_ids=conditions_to_observe)
            evaluated = json.loads((folder / 'observation/evaluated.json').read_bytes())
            conditions = {c.id:c.statement for c in self.task.conditions}
            reasons = {'missing_evidence_box':'模型未提供现场证据框，本项保留未知',
                'insufficient_detail':'细节或可靠定位不足，目前无法判断', 'occluded':'目标被遮挡，目前无法判断',
                'out_of_frame':'检查区域未入镜，目前无法判断', 'unresolved_identity':'无法确认目标身份'}
            next_plan = prepared.plan()
            reconsidered = [n for n in live.plan()['completed_node_ids'] if n not in next_plan['completed_node_ids']]
            next_node = prepared.nodes.get(next_plan['node_id'])
            relevant = set(next_node.completion_ids + next_node.precondition_ids) if next_node else set()
            messages = ['检查项：' + conditions[d['condition_id']] + '\n当前结果：' + reasons.get(d.get('diagnostic',d['reason']),'当前证据不足，请补充清晰画面')
                        for d in evaluated['details'] if d['value']=='unknown' and d['condition_id'] in relevant]
            detail_skipped = (folder / 'observation/detail-skipped.json').exists()
            with self.session(identity) as session:
                self.check_definition()
                latest = session.frames.get(session.last)
                if (self.ledger(session).stamp() != stamp or not latest or latest['action_id'] != request.action_id
                        or time.monotonic() - frame['at'] > 120):
                    raise HTTPException(409, '核验期间会话或步骤改变，请重新拍照；未推进状态。')
                # A successful photo artifact is only a proposal until this host receipt accepts it.
                atomic_json(folder / 'acceptance.json', dict(accepted=True, input_stamp=stamp,
                    capture_sha256=frame['sha256'], observation_manifest_sha256=digest((folder / 'observation/manifest.json').read_bytes()),
                    execution=self.bindings.execution(prepared), assessment_scope='all_needed' if reassess else 'initial_scope' if live.last_frame == 0 else 'current_operation'))
                self.event(session, 'baseline.observation.accepted', dict(execution=self.bindings.execution(prepared), capture_sha256=frame['sha256']))
                details = dict(getattr(session, 'baseline_visual_details', {}))
                event_id = prepared.events[-1]['id']
                for row in evaluated['details']:
                    if prepared.facts[row['condition_id']].evidence_id == event_id:
                        details[row['condition_id']] = dict(evidence_id=event_id, evidence=row['evidence'])
                session.baseline_visual_details = details
                session.baseline = prepared
                reply = self.check_reply(session, request, frame)
                heading = {'request_view':'需要补充当前操作的证据', 'ask_manual':'请逐项人工确认', 'operate':'可以开始当前操作，尚未验收', 'complete':'本会话条件已满足'}.get(reply['execution']['baseline_mode'],'任务定义需要核查')
                reply['feedback'] = '本次照片核验：' + heading + '。\n' + reply['execution']['reason']
                if messages:
                    reply['feedback'] += '\n\n' + '\n'.join(messages)
                if reconsidered:
                    reply['feedback'] += '\n\n当前证据变化，以下已通过操作需要重新核实：' + '；'.join(prepared.nodes[n].instruction for n in reconsidered)
                    reply['feedback'] += '\n原人工确认事件仍保留；当前视觉证据不足或存在反证，不能继续沿用其完成状态。'
                if detail_skipped:
                    reply['feedback'] += '\n局部螺丝检查未执行：没有可靠且足够大的底座证据区域。请拍清底座；放大整图不能补出原本缺失的细节。'
                return reply
        except HTTPException:
            atomic_json(folder / 'rejected.json', dict(accepted=False, reason='session_or_frame_changed'))
            raise
        except (OSError, ValueError, ModelError):
            atomic_json(folder / 'rejected.json', dict(accepted=False, reason='observation_failed'))
            failed = folder / 'observation' / 'failure.json'
            failure = json.loads(failed.read_bytes()) if failed.is_file() else {}
            invalid = failure.get('stage') in ('model_observation', 'detail_observation') and failure.get('error_type') in ('ValueError', 'ValidationError')
            diagnosis = '视觉观察未满足核验契约（事实或证据框不一致）' if invalid else '未取得有效视觉证据'
            with self.session(identity) as session:
                retained = self.execution(session)
            raise HTTPException(502, diagnosis + '；本次未更新进度。\n保留状态：' + retained['current_step'] + '\n可重新拍照；已接受的人工确认不会因本次请求失败而丢失。') from None
        finally:
            with self.lock:
                current = self.sessions.get(identity)
            if current:
                with current.lock:
                    current.baseline_busy = False

    def manual(self, identity, request):
        self.check_definition()
        with self.session(identity) as session:
            live = self.ledger(session)
            self.require_u7(session, request.action_id)
            expected = live.plan()
            node = live.nodes.get(expected['node_id'])
            batch = [c for c in node.completion_ids if live.conditions[c].channel == 'manual' and live.facts[c].value != 'true'] if node else []
            if self.compilation is not None and (request.session_id, request.task_sha256) != (live.id, live.task_sha):
                raise HTTPException(409, '人工确认属于另一编译任务或会话，请使用当前确认窗口。')
            if (session.baseline_busy or (request.epoch, request.revision) != (live.epoch, live.revision)
                    or expected['mode'] != 'ask_manual'
                    or request.condition_ids not in (expected['condition_ids'], batch)):
                raise HTTPException(409, '人工确认已失效，或不是当前待确认条件；请重新核验。')
            folder = self.root / 'runs' / identity / ('manual-' + uuid.uuid4().hex)
            prepared = deepcopy(live)
            try:
                confirm(prepared, self.protocol, request.condition_ids, request.statement, folder)
            except ValueError:
                raise HTTPException(409, '前置或视觉条件尚未满足，不能人工放行。') from None
            self.event(session, 'baseline.manual.accepted', dict(condition_ids=request.condition_ids, execution=self.bindings.execution(prepared)))
            session.baseline = prepared
            reply = self.check_reply(session, request)
            reply['feedback'] = '人工确认已记录。\n' + reply['execution']['current_step'] + '\n' + reply['execution']['reason']
            return reply


def install(app, config, registry, client, *, compilation=None, prefix='/api/guidance/baseline/spatial'):
    from .spatial.router import router
    service = BaselineSpatial(config, registry, client, compilation=compilation, prefix=prefix)
    api, _ = router(config, registry, client, service=service, prefix=prefix)
    if compilation is not None:
        from fastapi.responses import Response
        @api.get('/official-images/{image_id}')
        def official_image(image_id: str):
            image = next((i for i in service.sources.images if i.id == image_id), None)
            if image is None:
                raise HTTPException(404, 'Unknown official image')
            artifact = next(a for a in service.sources.artifacts if a.id == image.artifact_id)
            path = (service.reference_root / artifact.path).resolve()
            path.relative_to(service.reference_root.resolve())
            raw = path.read_bytes()
            if digest(raw) != artifact.sha256:
                raise HTTPException(409, 'Official reference changed')
            return Response(raw, media_type='image/png' if raw.startswith(b'\x89PNG') else 'image/jpeg')
    @api.post('/sessions/{identity}/assess')
    def assess(identity: str, command: Verify):
        return service.verify(identity, command, reassess=True)

    @api.post('/goal-preview')
    def goal_preview(command: GoalRequest):
        return service.goal_preview(command.intent)

    @api.post('/sessions/{identity}/manual-conditions')
    def manual(identity: str, command: Manual):
        return service.manual(identity, command)

    app.include_router(api)
    return service
