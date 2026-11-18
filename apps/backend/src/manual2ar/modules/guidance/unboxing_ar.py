"""Photo-plane illustrations and action evidence bound to the active official tutorial."""
import base64
from copy import deepcopy
import hashlib
import io
import json
import math
from typing import Literal
import uuid

from fastapi import HTTPException
import numpy as np
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field, create_model

from manual2ar.resources import ResourceStore
from manual2ar.visuals.library import VisualAssetLibrary
from manual2ar_baseline.photos import observe, confirm
from manual2ar_baseline.provider import CompatibleClient, ModelError, Settings
from manual2ar_baseline.state import Session
from manual2ar_baseline.vision import photo as normalized_photo
from .registry import UNBOX
from .spatial.service import atomic_json
from .spatial.vision_context import failure
from . import u7_sequence


class ActionStamp(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    state_id: str = Field(pattern=r'^U[0-9]{1,3}$')
    revision: int = Field(ge=0)
    variant_id: str = Field(min_length=1, max_length=80)
    substep_id: str = Field(max_length=24)
    action_id: str = Field(min_length=1, max_length=80)


class ActionPhoto(ActionStamp):
    client_frame_id: int = Field(ge=1)
    source_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    image_base64: str = Field(min_length=32, max_length=14_000_000)


class ActionManual(ActionStamp):
    source_sha256: str = Field(pattern=r'^([a-f0-9]{64})?$')
    confirmed_checks: list[str] = Field(min_length=1, max_length=16)


class ActionIllustration(ActionStamp):
    source_sha256: str = Field(pattern=r'^([a-f0-9]{64})?$')
    width: int = Field(ge=1, le=16384)
    height: int = Field(ge=1, le=16384)
    anchor_x: float = Field(ge=0, le=1)
    anchor_y: float = Field(ge=0, le=1)


class Finding(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    status: Literal['supported', 'contradicted', 'unknown']
    evidence: str = Field(min_length=1, max_length=500)
    confidence: float = Field(ge=0, le=1)
    next_action: str = Field(max_length=400)


def action_prompt(task, variant, chapter, action, sha):
    """Keep operator-only conditions explicitly outside the model's authority."""
    source = task.evidence['evidence']
    payload = dict(variant_id=variant, chapter_id=chapter, action_id=action['action_id'],
                   source_sha256=sha, target=action['target'], visual_check=action['visual_check'],
                   operator_only=action['manual_checks'],
                   official_fragments=[{'id': key, 'text': source[key]['text']} for key in action['citation_ids']])
    return ('核验 A1 mini 开箱的一个可见结果。第一张是本次现场照片。若有第二张，它是官方参考图，只解释零件外观。'
            '先从现场辨认目标及安装区域，再判断 visual_check 中的全部要求。直接看清并全部满足填 supported，'
            '有可见反证填 contradicted，目标不明、被挡、模糊、角度不足或只能推测时填 unknown。'
            '不要根据参考图、动作说明或用户的期望补全事实。照片不能证明拧紧、力度、过程、通电安全或画面外的状态。'
            'operator_only 留给用户现场核实。用一两句中文描述能看到的依据，必要时指出要补拍的部位。'
            '逐字返回请求中的 action_id 和 source_sha256。\n' + json.dumps(payload, ensure_ascii=False))


U7_NODES = {'holder.base': 'install_base', 'holder.slide': 'install_holder'}


class UnboxingAR:
    schema = 'manual2ar-unboxing-photo-ar-v1'

    def __init__(self, service, definition):
        self.service = service
        self.definition = definition
        store = ResourceStore.configured(service.config)
        self.library = VisualAssetLibrary(store.path('visual.unboxing.catalog'))
        raw = store.path('task.unboxing.ar').read_bytes()
        self.catalog_sha256 = hashlib.sha256(raw).hexdigest()
        catalog = json.loads(raw)
        self.actions = {a['action_id']: a for a in catalog['actions']}
        self.variants = catalog['variants']
        if (catalog['schema_version'] != 'manual2ar-unboxing-ar-v1'
                or len(self.actions) != len(catalog['actions'])
                or set(self.variants) != {variant for task_id, variant in service.registry.packages if task_id == UNBOX}):
            raise ValueError('Invalid unboxing AR catalog')
        self.reference_hashes = set()
        used = set()
        for variant, chapters in self.variants.items():
            _, task = service.registry.resolve(UNBOX, variant)
            self.reference_hashes.update(item['sha256'] for item in task.evidence['images'].values())
            if set(chapters) != set(task.cards):
                raise ValueError('Incomplete unboxing AR chapter coverage')
            for chapter, item in chapters.items():
                ids = item['actions']
                if not ids and not item['reason'] or len(ids) != len(set(ids)):
                    raise ValueError('Invalid chapter action coverage')
                card = task.cards[chapter]
                for key in ids:
                    a = self.actions[key]
                    used.add(key)
                    if (a['substep_id'] not in ({s.id for s in card.substeps} or {''})
                            or not a['citation_ids'] or not set(a['citation_ids']) <= task.evidence['evidence'].keys()
                            or a['reference_image'] and a['reference_image'] not in task.evidence['images']
                            or a['presentation_id'] not in self.library.presentations
                            or not a['visual_check'] and not a['manual_checks']
                            or len(set(a['manual_checks'])) != len(a['manual_checks'])
                            or len(a['illustration_direction']) != 2
                            or not math.isclose(math.hypot(*a['illustration_direction']), 1., abs_tol=.001)):
                        raise ValueError('Invalid unboxing action binding: '+variant+'/'+chapter+'/'+key)
        if used != self.actions.keys():
            raise ValueError('Unbound unboxing action')

    def attach(self, value, task, run):
        if value['task_id'] != UNBOX:
            return
        chapters = self.variants[value['variant_id']]
        chapter_id, selected = value['state_id'], value['selected_substep_id']
        chapter = chapters[chapter_id]
        records = getattr(run, 'photo_ar_records', {})
        chapter_records = records.get(chapter_id, {})
        actions = []
        for key in chapter['actions']:
            a = self.actions[key]
            if a['substep_id'] == selected:
                ref = a['reference_image']
                actions.append({**a, 'reference': task.photo(ref) if ref else None,
                                'status': 'unassessed' if a['visual_check'] else 'needs_manual',
                                'evidence': '', 'next_action': '', 'source_sha256': '',
                                **chapter_records.get(key, {})})
        statuses = {}
        for row in value['chapter_completion']:
            cid = row['state_id']
            scope = chapters[cid]['actions']
            required = [k for k in scope if not self.actions[k]['optional']]
            checked = records.get(cid, {})
            complete = bool(scope) and all(checked.get(k, {}).get('status') == 'verified' for k in (required or scope))
            statuses[cid] = 'verified' if complete else 'in_progress' if checked else 'unassessed'
            # Optional advice embedded in the safety preamble cannot sign off that preamble.
            if checked and cid != 'U1':
                row.update(completed=complete, source='photo_ar_checks')
        reason = chapter['reason']
        if chapter_id == 'U7' and selected == 'U7-S2' and not (
                getattr(run, 'photo_ar_u7', None) and run.photo_ar_u7.completed()['install_base']):
            actions = []
            reason = '请返回底座步骤，在开箱 AR 中拍照并核实底座。'
        value['photo_ar'] = dict(schema_version=self.schema, asset_library=self.library.descriptor(),
                                reason=reason, actions=actions, chapter_status=statuses[chapter_id],
                                verified_actions=sum(row['status'] == 'verified'
                                    for group in records.values() for row in group.values()),
                                total_actions=sum(len(item['actions']) for item in chapters.values()))

    def current(self, identity, command):
        m, engine, run = self.service.validate(identity, command)
        if m['task_id'] != UNBOX or m['variant_id'] != command.variant_id:
            raise HTTPException(409, '动作不属于本次开箱版本。')
        card = engine.task.cards[command.state_id]
        sub = run.tutorial_substeps.get(command.state_id, card.substeps[0].id if card.substeps else '')
        if (command.substep_id != sub or command.action_id not in self.variants[m['variant_id']][command.state_id]['actions']
                or self.actions[command.action_id]['substep_id'] != sub):
            raise HTTPException(409, '请重新选择当前章节的动作。')
        if command.action_id == 'holder.slide':
            ledger = getattr(run, 'photo_ar_u7', None)
            if ledger is None or not ledger.completed()['install_base']:
                raise HTTPException(409, '请先在开箱 AR 中拍照并核实底座。')
        return m, engine, run, self.actions[command.action_id]

    def illustration(self, identity, c):
        with self.service.lock:
            _, _, _, a = self.current(identity, c)
            focal = max(c.width, c.height)*1.5
            end = np.array([(c.anchor_x-.5)*c.width/focal, (c.anchor_y-.5)*c.height/focal, 0.])
            dx, dy = a['illustration_direction']
            basis = np.array([[dy, dx, 0.], [-dx, dy, 0.], [0., 0., 1.]])
            presentation = self.library.compose(a['presentation_id'], [end-.07*basis[:,1], end], basis)
            presentation['reference_space_id'] = 'unboxing-photo-'+(c.source_sha256[:16] or 'preview')
            transform = np.eye(4); transform[2,3] = 1.
            return dict(**c.model_dump(), run_id=identity, illustrative_only=True, presentation=presentation,
                        projection=dict(intrinsics=[focal,0,c.width/2,0,focal,c.height/2,0,0,1],
                                        camera_from_marker=transform.ravel().tolist(), distortion=[]))

    def generic_photo(self, engine, a, c, image, folder):
        task = engine.task
        prompt = action_prompt(task, c.variant_id, c.state_id, a, c.source_sha256)
        contract = create_model('UnboxingActionFinding', __base__=Finding,
                                action_id=(Literal[c.action_id], ...), source_sha256=(Literal[c.source_sha256], ...))
        (folder/'prompt.txt').write_text(prompt, encoding='utf-8')
        atomic_json(folder/'schema.json', contract.model_json_schema())
        images = [image]
        if a['reference_image']:
            path = a['reference_image']
            raw = task.checked_file(path, task.evidence['images'][path]['sha256'])
            reference, _ = normalized_photo(raw, longest=engine.config['verification']['max_image_side'])
            images.append(reference)
            (folder/'reference.jpg').write_bytes(reference)
        try:
            raw = engine.client.chat_structured(prompt=prompt, schema=contract.model_json_schema(),
                images_base64=[base64.b64encode(b).decode() for b in images],
                max_tokens=engine.config['verification']['max_tokens'])
            finding = contract.model_validate(raw)
        except Exception as exc:
            failure(folder, exc)
            raise HTTPException(502, '视觉服务未返回有效结果，进度已保留，可重新核验。') from None
        atomic_json(folder/'finding.json', finding.model_dump())
        status = finding.status
        evidence = finding.evidence.strip()
        if finding.confidence < engine.config['verification']['minimum_confidence'] or not finding.evidence.strip():
            status = 'unknown'
            evidence = '本次照片未取得足够的可见依据。'
        if status == 'supported':
            phase = 'needs_manual' if a['manual_checks'] else 'verified'
            next_action = '请核实所列人工项目。' if a['manual_checks'] else ''
        else:
            phase = 'needs_photo' if status == 'unknown' else 'not_met'
            next_action = a['instruction'] if status == 'contradicted' else ('请补拍'+a['target']+'。')
        return dict(status=phase, evidence=evidence, next_action=next_action, source_sha256=c.source_sha256)

    def reviewed_u7(self, run, c, folder, photo):
        d = self.definition
        ledger = deepcopy(getattr(run, 'photo_ar_u7', None))
        if ledger is None:
            ledger = Session.from_bundle(d.bundle, 'unbox.'+run.id, d.task.title,
                evidence_mode='experimental_photo_analysis', guidance_policy='evidence_guided')
        if photo:
            provider = d.photo_client or CompatibleClient(Settings.model_validate(
                {k: d.config['vlm'][k] for k in Settings.model_fields if k in d.config['vlm']}))
            observe(ledger, d.sources, d.protocol, folder/'capture.original', d.reference_root, folder/'observation', provider)
        else:
            node = ledger.nodes[U7_NODES[c.action_id]]
            manual_ids = [cid for cid in node.completion_ids if ledger.conditions[cid].channel == 'manual']
            confirm(ledger, d.protocol, manual_ids, '；'.join(c.confirmed_checks), folder/'confirmation')
        records = {}
        done = ledger.completed()
        for action_id, node_id in U7_NODES.items():
            node = ledger.nodes[node_id]
            facts = [ledger.facts[cid] for cid in node.completion_ids if ledger.conditions[cid].channel == 'vision']
            unknown = [ledger.conditions[cid].statement for cid in node.completion_ids
                       if ledger.conditions[cid].channel == 'vision' and ledger.facts[cid].value == 'unknown']
            if done[node_id]:
                status = 'verified'
                evidence = '沿用本会话已核实的底座记录，当前有遮挡。' if any(f.retained_on for f in facts) else '视觉与人工条件已核实。'
            elif any(f.value == 'false' for f in facts):
                status, evidence = 'not_met', '现场存在与安装要求不符的可见条件。'
            elif unknown:
                status, evidence = 'needs_photo', '仍需看清：'+'、'.join(unknown)
            elif node_id == 'install_holder' and not done['install_base']:
                status, evidence = 'needs_photo', '支架可见，先核实底座。'
            else:
                status, evidence = 'needs_manual', '可见安装条件已满足，请核实列出的人工项目。'
            next_action = '' if status == 'verified' else (self.actions[action_id]['instruction'] if status == 'not_met' else evidence)
            records[action_id] = dict(status=status, evidence=evidence, next_action=next_action, source_sha256=c.source_sha256)
        return records, ledger

    def evidence(self, identity, c, *, photo):
        with self.service.lock:
            m, engine, run, a = self.current(identity, c)
            records = deepcopy(getattr(run, 'photo_ar_records', {}))
            checked = records.setdefault(c.state_id, {})
            prev = checked.get(c.action_id, {})
            if photo:
                if not a['visual_check']:
                    raise HTTPException(409, '此动作需现场人工核实。')
                if c.client_frame_id <= run.last_frame or prev.get('source_sha256') == c.source_sha256:
                    raise HTTPException(409, '请重新拍摄本次现场照片。')
                if c.source_sha256 in self.reference_hashes:
                    raise HTTPException(422, '官方参考图仅供演示，请拍摄现场。')
                if not engine.config['vlm']['api_key'].strip():
                    raise HTTPException(503, '请先配置视觉模型服务。')
            else:
                if (prev.get('status') == 'verified' or not a['manual_checks'] or c.confirmed_checks != a['manual_checks']
                    or a['visual_check'] and prev.get('status') != 'needs_manual'
                    or c.source_sha256 != prev.get('source_sha256', '')):
                    raise HTTPException(409, '请在当前现场结果下逐项确认所列项目。')
            m['busy'] = True
        owns_busy = True
        folder = run.folder/('ar-'+uuid.uuid4().hex)
        try:
            folder.mkdir()
            request = c.model_dump(exclude={'image_base64'})
            atomic_json(folder/'request.json', {**request, 'run_id': identity, 'task_revision': engine.task.revision,
                        'action_catalog_sha256': self.catalog_sha256, 'visual_catalog_sha256': self.library.sha256, 'action': a,
                        'official_reference_sha256': engine.task.evidence['images'].get(a['reference_image'], {}).get('sha256'),
                        'excluded_from_research_evaluation': True, 'kind': 'photo' if photo else 'manual'})
            if photo:
                image, _ = engine.decode(c.image_base64, c.source_sha256)
                original = base64.b64decode(c.image_base64, validate=True)
                with Image.open(io.BytesIO(original)) as source:
                    if source.format not in ('JPEG','PNG') or min(source.size) < 32:
                        raise HTTPException(422, '请上传有效的 JPEG 或 PNG 现场照片。')
                (folder/'capture.original').write_bytes(original)
                (folder/'scene.jpg').write_bytes(image)
            ledger = None
            if c.action_id in U7_NODES:
                try:
                    updated, ledger = self.reviewed_u7(run, c, folder, photo)
                except (ValueError, ModelError) as exc:
                    failure(folder, exc)
                    raise HTTPException(502, 'U7 核验未取得有效结果，请重试。') from None
                checked.update(updated)
            elif photo:
                checked[c.action_id] = self.generic_photo(engine, a, c, image, folder)
            else:
                checked[c.action_id] = dict(status='verified', source_sha256=c.source_sha256,
                    evidence=prev.get('evidence') or '已人工核实所列项目。', next_action='', confirmed_checks=c.confirmed_checks)
            with self.service.lock:
                if identity in self.service.closing or run.revision != c.revision or run.closed:
                    raise HTTPException(409, '任务已变化，此结果未写入。')
                atomic_json(folder/'acceptance.json', dict(run_id=identity, revision=c.revision+1,
                            results=checked, source_sha256=c.source_sha256))
                run.photo_ar_records = records
                if ledger is not None:
                    run.photo_ar_u7 = ledger
                    for key, value in updated.items():
                        stage = u7_sequence.stage(key)
                        run.u7_checks.pop('pending_'+stage, None)
                        run.u7_checks[stage] = dict(status='completed' if value['status']=='verified' else 'uncertain',
                                                    evidence=value['evidence'], source_sha256=value['source_sha256'])
                    if not ledger.completed()['install_base']:
                        run.tutorial_substeps['U7'] = 'U7-S1'
                if photo:
                    run.last_frame = c.client_frame_id
                run.revision += 1
                m['busy'] = False
                owns_busy = False
                return self.service._view(identity)
        except OSError:
            raise HTTPException(503, '无法保存本次核验，请检查存储空间后重试。') from None
        finally:
            if owns_busy:
                with self.service.lock:
                    m['busy'] = False
                    if identity in self.service.closing:
                        self.service.close(identity)
