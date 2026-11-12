"""Explicit curated U7 demonstration and isolated real-photo sessions over approved GT."""
import base64
from contextlib import suppress
from copy import copy, deepcopy
import io
import json
from pathlib import Path
import threading
from types import SimpleNamespace
from typing import Literal
import uuid

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
import numpy as np
from PIL import Image
from pydantic import Field

from manual2ar_baseline.goals import resolve_goal
from manual2ar_baseline.gt import Strict, Digest, Identity, digest, encoded
from manual2ar_baseline.photos import observe, confirm
from manual2ar_baseline.provider import CompatibleClient, Settings, ModelError
from manual2ar_baseline.state import Session
from .spatial.service import atomic_json

PREFIX = '/api/guidance/u7-demo'


class Start(Strict):
    intent: str = Field(min_length=2, max_length=1000)
    mode: Literal['scripted', 'live'] = 'scripted'


class Stamp(Strict):
    session_id: Identity
    task_sha256: Digest
    epoch: int = Field(ge=0)
    revision: int = Field(ge=0)
    source_sha256: str = Field(default='', max_length=64)


class Photo(Stamp):
    scene_id: str = Field(default='', max_length=80)
    image_base64: str = Field(default='', max_length=3_000_000)


class Manual(Stamp):
    condition_ids: list[Identity] = Field(min_length=1, max_length=16)
    confirmed: Literal[True]


class Illustration(Stamp):
    anchor_x: float = Field(default=.45, ge=.05, le=.95)
    anchor_y: float = Field(default=.34, ge=.05, le=.95)


class U7Demo:
    def __init__(self, config, definition):
        self.definition = definition
        self.config = config
        self.root = Path(config['runtime_dir']) / 'u7-demo'
        self.assets = self.root / 'assets-v1'
        self.sessions = {}
        self.lock = threading.RLock()
        self.photo_client = None

    def scenes(self):
        path = self.assets / 'manifest.json'
        if not path.is_file():
            return []
        manifest = json.loads(path.read_bytes())
        if (manifest.get('purpose') != 'curated_demo_not_evaluation'
                or manifest.get('task_sha256') != self.definition.bindings.task_sha256):
            raise HTTPException(409, '演示素材标识无效。')
        return manifest['scenes']

    def scene(self, identity):
        row = next((r for r in self.scenes() if r['id'] == identity), None)
        if row is None:
            raise HTTPException(404, '没有这张演示照片。')
        path = (self.assets / row['file']).resolve()
        if path.parent != self.assets.resolve():
            raise HTTPException(409, '演示素材路径无效。')
        raw = path.read_bytes()
        if digest(raw) != row['sha256']:
            raise HTTPException(409, '演示照片已改变，请重新准备素材。')
        return row, raw

    def catalog(self):
        d = self.definition
        return dict(task_sha256=d.bindings.task_sha256, task_origin='approved_u7_gt',
                    scope='U7：安装底座、滑入支架', asset_library=d.asset_library.descriptor(),
                    official_steps=d.goal_preview(d.task.title)['official_steps'],
                    scenes=[dict(id=r['id'], title=r['title'], sha256=r['sha256'],
                                 url=PREFIX+'/scenes/'+r['id']+'.jpg') for r in self.scenes()],
                    questions=['安装料盘支架', '安装支架底座', '滑入料盘支架', '安装料盘底座及滑入料盘支架'],
                    mode_notice='历史照片使用预设观察，仅展示流程；实时拍摄调用真实模型。')

    def start(self, command):
        d = self.definition
        try:
            goal = resolve_goal(d.task, d.sources, command.intent)
        except ValueError as error:
            raise HTTPException(422, str(error)) from None
        identity = 'demo.'+uuid.uuid4().hex
        ledger = Session(d.task, identity, command.intent,
                         evidence_mode='controlled_facts_only' if command.mode == 'scripted' else 'experimental_photo_analysis',
                         target_node_ids=goal.selected_node_ids, guidance_policy='scene_guided')
        row = SimpleNamespace(baseline=ledger, baseline_goal=goal, baseline_visual_details={}, mode=command.mode,
                              lock=threading.RLock(), busy=False, closed=False, source_sha='', size=None)
        with self.lock:
            if len(self.sessions) >= 64:
                raise HTTPException(409, '演示会话过多，请关闭不用的任务后重试。')
            self.record(row, 'start', dict(intent=command.intent, goal=goal.model_dump()))
            self.sessions[identity] = row
        return self.reply(row)

    def get(self, identity):
        with self.lock:
            row = self.sessions.get(identity)
        if row is None or row.closed:
            raise HTTPException(404, '演示会话已关闭，请重新生成计划。')
        return row

    def check(self, row, command, *, photo=False):
        if row.closed or row.busy or row.baseline.stamp() != {k:getattr(command, k) for k in row.baseline.stamp()}:
            raise HTTPException(409, '任务或进度已改变，请使用当前窗口。')
        if not photo and (not row.source_sha or command.source_sha256 != row.source_sha):
            raise HTTPException(409, '操作不属于当前照片。')

    def record(self, row, action, payload):
        folder = self.root / 'runs' / row.baseline.id
        try:
            atomic_json(folder / (uuid.uuid4().hex+'.json'), dict(action=action, mode=row.mode,
                        excluded_from_research_evaluation=True, **row.baseline.stamp(),
                        execution=self.definition.execution(row), payload=payload))
        except OSError:
            raise HTTPException(503, '无法保存记录，请检查磁盘空间后重试；原进度保留。') from None

    def reply(self, row):
        value = self.definition.execution(row)
        tree = self.definition.goal_preview(row.baseline.intent)
        return dict(mode=row.mode, task_origin='approved_u7_gt', execution=value, source_sha256=row.source_sha,
                    official_steps=tree['official_steps'],
                    observation_notice='历史照片 · 预设观察（演示）' if row.mode == 'scripted' else '真实模型观察 · 请核对结果',
                    placement_notice='照片上的 AR 动画示意，不表示已完成实机空间标定。')

    def photo(self, identity, command):
        row = self.get(identity)
        with row.lock:
            self.check(row, command, photo=True)
            scene = None
            if row.mode == 'scripted':
                if not command.scene_id or command.image_base64:
                    raise HTTPException(422, '预设观察只接受清单中的历史照片。')
                scene, raw = self.scene(command.scene_id)
                if command.source_sha256 != digest(raw):
                    raise HTTPException(409, '演示照片与预设记录不匹配。')
            else:
                if command.scene_id:
                    raise HTTPException(422, '真实模型模式不能使用预设状态。')
                try:
                    raw = base64.b64decode(command.image_base64, validate=True)
                except ValueError:
                    raise HTTPException(422, '照片格式无效。') from None
                if digest(raw) != command.source_sha256:
                    raise HTTPException(409, '照片校验失败。')
            try:
                with Image.open(io.BytesIO(raw)) as image:
                    if image.format != 'JPEG' or not (160 <= image.width <= 1280 and 160 <= image.height <= 1280):
                        raise ValueError('JPEG size')
                    image.load(); size = image.size
            except (OSError, ValueError):
                raise HTTPException(422, '请使用边长160至1280像素的JPEG照片。') from None
            old = row.baseline.stamp()
            prepared = deepcopy(row.baseline)
            plan = prepared.plan()
            # Selecting a scripted scene is a whole-scene change, including regressions.
            owners = prepared.needed if row.mode == 'scripted' or prepared.last_frame == 0 else {plan['node_id']}
            if plan['mode'] == 'complete':
                raise HTTPException(409, '本次目标已完成，请重新生成计划。')
            ids = {c for n in owners for c in prepared.nodes[n].completion_ids if prepared.conditions[c].channel == 'vision'}
            row.busy = True
        folder = self.root / 'runs' / identity / ('photo-'+uuid.uuid4().hex)
        try:
            folder.mkdir(parents=True)
            (folder/'input.jpg').write_bytes(raw)
            if scene:
                values = {c:scene['readings'][c] for c in ids}
                event = dict(id='demo.'+uuid.uuid4().hex, **old, kind='observation', origin='controlled_annotation',
                             frame_id=prepared.last_frame+1, source_sha256=digest(raw), values=values)
                prepared.apply(event)
                details = {c:dict(evidence_id=event['id'], evidence=scene['explanation']) for c in ids}
                atomic_json(folder/'preset-observation.json', dict(excluded_from_evaluation=True,
                            source='curated_script_not_vlm_or_human_ground_truth', scene_id=scene['id'], event=event))
            else:
                client = self.photo_client or self.definition.photo_client or CompatibleClient(Settings.model_validate(
                    {k:self.config['vlm'][k] for k in Settings.model_fields if k in self.config['vlm']}))
                observe(prepared, self.definition.sources, self.definition.protocol, folder/'input.jpg',
                        self.definition.reference_root, folder/'observation', client, condition_ids=ids)
                evaluated = json.loads((folder/'observation/evaluated.json').read_bytes())
                event = prepared.events[-1]
                details = {d['condition_id']:dict(evidence_id=event['id'], evidence=d['evidence']) for d in evaluated['details']}
            with row.lock:
                if row.closed or row.baseline.stamp() != old:
                    raise HTTPException(409, '会话已改变，本次照片未更新进度。')
                pending = copy(row)
                pending.baseline_visual_details = dict(row.baseline_visual_details)
                # Preserve explanations only when the corresponding fact was actually updated.
                for c, detail in details.items():
                    if prepared.facts[c].evidence_id == event['id']:
                        pending.baseline_visual_details[c] = detail
                pending.baseline = prepared; pending.source_sha = digest(raw); pending.size = size
                reply = self.reply(pending)
                self.record(pending, 'photo', dict(source_sha256=pending.source_sha, observation=str(folder)))
                # This receipt commits the photo record; rejected attempts are not accepted evidence.
                atomic_json(folder/'acceptance.json', dict(accepted=True, excluded_from_research_evaluation=True,
                            input_stamp=old, source_sha256=pending.source_sha, mode=row.mode))
                row.baseline = pending.baseline; row.baseline_visual_details = pending.baseline_visual_details
                row.source_sha = pending.source_sha; row.size = pending.size
                return reply
        except HTTPException:
            with suppress(OSError):atomic_json(folder/'rejected.json', dict(state_unchanged=True))
            raise
        except (ValueError, OSError, ModelError):
            with suppress(OSError):atomic_json(folder/'rejected.json', dict(state_unchanged=True))
            raise HTTPException(502, '本次未能确认，请调整取景后重试；原进度保留。') from None
        finally:
            with row.lock:row.busy = False

    def manual(self, identity, command):
        row = self.get(identity)
        with row.lock:
            self.check(row, command)
            execution = self.definition.execution(row)
            expected = [c['id'] for c in execution['manual_conditions']]
            if execution['baseline_mode'] != 'ask_manual' or command.condition_ids != expected:
                raise HTTPException(409, '请只确认当前操作列出的全部项目。')
            prepared = deepcopy(row.baseline)
            if row.mode == 'scripted':
                prepared.apply(dict(id='manual.'+uuid.uuid4().hex, **prepared.stamp(), kind='manual',
                                    origin='controlled_operator', statement='演示者明确勾选当前全部人工项目；非研究标签',
                                    values={c:'true' for c in expected}))
            else:
                try:
                    confirm(prepared, self.definition.protocol, expected, '操作者明确勾选当前全部人工项目',
                            self.root/'runs'/identity/('manual-'+uuid.uuid4().hex))
                except OSError:
                    raise HTTPException(503, '无法保存确认，请检查磁盘空间后重试；原进度保留。') from None
            pending = copy(row); pending.baseline = prepared
            reply = self.reply(pending)
            self.record(pending, 'manual', dict(condition_ids=expected))
            row.baseline = prepared
            return reply

    def illustration(self, identity, command):
        row = self.get(identity)
        with row.lock:
            self.check(row, command)
            execution = self.definition.execution(row)
            if not execution['guidance_ready'] or row.size is None:
                raise HTTPException(409, '当前没有需要演示的操作。')
            binding = next(p for p in self.definition.bindings.presentations if p.node_id == execution['state_id'])
            width, height = row.size; focal = max(width, height)*1.5
            x = (command.anchor_x*width-width/2)/focal
            y = (command.anchor_y*height-height/2)/focal
            points = [[x, y-.07, 0], [x, y, 0]]
            presentation = self.definition.asset_library.compose(binding.presentation_id, points, np.eye(3))
            reference = 'demo-photo-'+row.source_sha[:16]
            presentation['reference_space_id'] = reference
            matrix = np.eye(4);matrix[2,3] = 1
            result = dict(**row.baseline.stamp(), source_sha256=row.source_sha, action_id=binding.action_id,
                          presentation=presentation, width=width, height=height,
                          projection=dict(intrinsics=[focal,0,width/2,0,focal,height/2,0,0,1],
                                          camera_from_marker=matrix.ravel().tolist(), distortion=[]),
                          illustrative_only=True, placement_method='explicit_photo_illustration_not_metric_registration')
            self.record(row, 'ar_illustration', dict(source_sha256=row.source_sha, action_id=binding.action_id))
            return result

    def close(self, identity):
        row = self.get(identity)
        with row.lock:
            self.record(row, 'close', {})
            row.closed = True
        with self.lock:self.sessions.pop(identity, None)


def install(app, config, definition):
    service = U7Demo(config, definition)
    api = APIRouter(prefix=PREFIX, tags=['curated-u7-demo'])

    @api.get('/catalog')
    def catalog():return service.catalog()

    @api.get('/scenes/{scene_id}.jpg')
    def scene(scene_id: str):return Response(service.scene(scene_id)[1], media_type='image/jpeg')

    @api.post('/sessions', status_code=201)
    def start(command: Start):return service.start(command)

    @api.post('/sessions/{identity}/photo')
    def photo(identity: str, command: Photo):return service.photo(identity, command)

    @api.post('/sessions/{identity}/manual')
    def manual(identity: str, command: Manual):return service.manual(identity, command)

    @api.post('/sessions/{identity}/ar')
    def ar(identity: str, command: Illustration):return service.illustration(identity, command)

    @api.delete('/sessions/{identity}', status_code=204)
    def close(identity: str):service.close(identity)

    app.include_router(api)
    return service
