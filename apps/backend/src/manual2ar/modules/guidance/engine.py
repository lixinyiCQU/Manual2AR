"""Server-owned progress, explicit human confirmations and per-node VLM checks."""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic, perf_counter
import base64
import binascii
import hashlib
import io
import json
import re
import logging
from pydantic import ValidationError
import threading
import uuid
import cv2
import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError
from fastapi import HTTPException
from .verification import result_contract, bound_prompt
from manual2ar.integrations.vlm.client import QwenChatCompletionsClient
from .task import TaskPackage


def now(): return datetime.now(timezone.utc).isoformat()


@dataclass
class Run:
    id: str
    folder: Path
    index: int = 0
    revision: int = 0
    completed: bool = False
    closed: bool = False
    results: dict = field(default_factory=dict)
    u7_checks: dict = field(default_factory=dict)
    spatial_checks: dict = field(default_factory=dict)
    last_frame: int = -1
    last_active: float = field(default_factory=monotonic)
    lock: object = field(default_factory=threading.Lock)


class GuideService:
    def __init__(self, config, task=None, client=None, log_root=None,
                 api_prefix='/api/guidance/runs', config_label='configs/app.local.json'):
        self.config = config
        self.api_prefix = api_prefix
        self.config_label = config_label
        self.task = task or TaskPackage()
        if client is None:
            client = QwenChatCompletionsClient(config['vlm'])
        self.client = client
        self.log_root = Path(log_root or Path(config['runtime_dir'])/'guidance')
        self.runs = {}
        self.registry_lock = threading.Lock()

    def event(self, run, name, data):
        with (run.folder/'events.jsonl').open('a', encoding='utf-8') as f:
            f.write(json.dumps({'at': now(), 'event': name, 'run_id': run.id,
                                'revision': run.revision, 'data': data}, ensure_ascii=False)+'\n')

    def begin(self):
        with self.registry_lock:
            idle = self.config['sessions']['idle_minutes']*60
            for key, old in list(self.runs.items()):
                if monotonic()-old.last_active > idle and old.lock.acquire(blocking=False):
                    try:
                        old.closed = True
                        self.event(old, 'session.expired', {})
                        self.runs.pop(key, None)
                    finally: old.lock.release()
            if len(self.runs) >= self.config['sessions']['max_runs']:
                raise HTTPException(429, '会话数量已达上限，请结束旧会话。')
            identity = uuid.uuid4().hex
            folder = self.log_root/identity
            folder.mkdir(parents=True)
            run = Run(identity, folder)
            self.runs[identity] = run
            (folder/'procedure.json').write_bytes(self.task.bytes)
            (folder/'session.json').write_text(json.dumps({'run_id': identity, 'task_revision': self.task.revision,
                'created_at': now(), 'model': self.config['vlm']['model']}, ensure_ascii=False, indent=2))
            self.event(run, 'session.started', {})
            return self.view(run)

    def get(self, identity):
        run = self.runs.get(identity)
        if run is None or run.closed: raise HTTPException(404, '会话不存在或已结束，请重新开始。')
        run.last_active = monotonic()
        return run

    def state(self, run): return self.task.document.states[run.index]

    def pending(self, run):
        return next((n for n in self.state(run).observation_nodes if run.results.get(n.inspection_id, {}).get('status') != 'completed'), None)

    def view(self, run):
        state = self.state(run)
        pending = None if run.completed else self.pending(run)
        observations = []
        for node in state.observation_nodes:
            saved = run.results.get(node.inspection_id, {})
            condition = node.condition
            if state.state_id == 'U9' and node.inspection_id == 'U9-C2' and pending and pending.inspection_id == 'U9-C1':
                condition = '先完成通电前复核，之后显示本项。'
            observations.append({'id': node.inspection_id, 'condition': condition,
                'channel': node.verification_channel, 'status': saved.get('status', 'not_started'),
                'evidence': saved.get('evidence', ''), 'correction': saved.get('correction', ''),
                'confidence': saved.get('confidence'), 'frame_id': saved.get('frame_id', 0),
                'source_sha256': saved.get('source_sha256', ''),
                'image_url': saved.get('image_url', ''), 'segmentation': saved.get('segmentation', ''),
                'failure_kind': saved.get('failure_kind', ''), 'elapsed_ms': saved.get('elapsed_ms', 0)})
        return {'run_id': run.id, 'revision': run.revision, 'task_revision': self.task.revision,
                'state_id': state.state_id, 'step_index': run.index, 'step_count': len(self.task.document.states),
                'completed': run.completed, 'can_advance': pending is None and not run.completed,
                'can_back': run.index > 0, 'pending_id': pending.inspection_id if pending else '',
                'channel': pending.verification_channel if pending else '',
                'capture_instruction': pending.capture_instruction if pending and pending.verification_channel == 'vision' else '',
                'current_condition': pending.condition if pending else '',
                'presentation': self.task.presentation(state, pending), 'observations': observations}

    def check(self, run, command, observation=True):
        if run.closed: raise HTTPException(404, '会话已结束。')
        if command.revision != run.revision or command.state_id != self.state(run).state_id:
            raise HTTPException(409, '页面进度已变化，请同步后重试。')
        if run.completed: raise HTTPException(409, '本任务已经完成。')
        pending = self.pending(run)
        if observation and (pending is None or command.inspection_id != pending.inspection_id):
            raise HTTPException(409, '当前待核验观察点已变化，请同步后重试。')
        return pending

    def acquire(self, run):
        if not run.lock.acquire(blocking=False): raise HTTPException(409, '当前核验仍在处理中，请稍后同步。')

    def save(self, run):
        run.last_active = monotonic()
        temp = run.folder/'progress.tmp'
        temp.write_text(json.dumps(self.view(run), ensure_ascii=False, indent=2))
        temp.replace(run.folder/'progress.json')

    def confirm(self, identity, command):
        run = self.get(identity); self.acquire(run)
        try:
            node = self.check(run, command)
            if node.verification_channel != 'manual': raise HTTPException(409, '本观察点必须拍照检查，不能用人工确认替代。')
            if not command.confirmed: raise HTTPException(400, '请明确确认本项已完成。')
            run.results[node.inspection_id] = {'status': 'completed', 'channel': 'manual', 'confidence': None,
                'evidence': '用户明确确认：'+node.condition, 'confirmed_at': now(), 'actor': 'user'}
            run.revision += 1
            self.event(run, 'manual.confirmed', {'inspection_id': node.inspection_id, **run.results[node.inspection_id]})
            self.save(run)
            return self.view(run)
        finally: run.lock.release()

    def decode(self, encoded, expected_hash):
        try:
            data = base64.b64decode(encoded, validate=True)
            if not data or len(data) > 10_000_000: raise ValueError()
            sha = hashlib.sha256(data).hexdigest()
            if sha != expected_hash: raise HTTPException(422, '图像哈希不匹配，请重新拍摄。')
            with Image.open(io.BytesIO(data)) as source:
                if source.width*source.height > 16_000_000: raise ValueError()
                upright = ImageOps.exif_transpose(source).convert('RGB')
                upright.thumbnail((self.config['verification']['max_image_side'],)*2)
                out = io.BytesIO(); upright.save(out, format='JPEG', quality=92)
            return out.getvalue(), sha
        except HTTPException: raise
        except (ValueError, OSError, UnidentifiedImageError, Image.DecompressionBombError, binascii.Error):
            raise HTTPException(422, '图片无效或尺寸过大，请重新拍摄。') from None

    def annotate(self, image, boxes, folder):
        canvas = cv2.imdecode(np.frombuffer(image, np.uint8), cv2.IMREAD_COLOR)
        height, width = canvas.shape[:2]
        report = []
        original = canvas.copy()
        for i, box in enumerate(boxes[:8]):
            x1, y1, x2, y2 = box.bbox_0_1000
            if not (0 <= x1 < x2 <= 1000 and 0 <= y1 < y2 <= 1000): continue
            a, b, c, d = int(x1*width/1000), int(y1*height/1000), min(width, int(x2*width/1000)), min(height, int(y2*height/1000))
            if min(c-a, d-b) < 5: continue
            area = 0
            if self.config['visualization']['grabcut']:
                try:
                    # Optional display mask; no semantic result depends on it.
                    mask = np.zeros((height, width), np.uint8)
                    cv2.grabCut(original, mask, (a,b,c-a,d-b), np.zeros((1,65),np.float64), np.zeros((1,65),np.float64), 2, cv2.GC_INIT_WITH_RECT)
                    on = (mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD)
                    area = int(np.count_nonzero(on))
                    if 0 < area < height*width*.9:
                        canvas[on] = (canvas[on]*.65+np.array([220,190,0])*.35).astype(np.uint8)
                        cv2.imwrite(str(folder/f'mask_{i}.png'), on.astype(np.uint8)*255)
                except cv2.error: area = 0
            cv2.rectangle(canvas, (a,b), (c,d), (230,210,0), 2)
            cv2.putText(canvas, str(i+1), (a,max(18,b)), cv2.FONT_HERSHEY_SIMPLEX, .7, (230,210,0), 2)
            report.append({'component': box.component_id, 'box': box.bbox_0_1000, 'display_mask_pixels': area})
        cv2.imwrite(str(folder/'annotated.jpg'), canvas)
        return report

    def verify(self, identity, command):
        run = self.get(identity); self.acquire(run)
        try:
            node = self.check(run, command)
            if node.verification_channel != 'vision': raise HTTPException(409, '本步只需用户确认，不需要拍摄或调用VLM。')
            if command.client_frame_id <= run.last_frame: raise HTTPException(409, '旧的拍摄帧不能重复用于新检查。')
            if not self.config['vlm']['api_key'].strip(): raise HTTPException(503, '请在'+self.config_label+'填写vlm.api_key。')
            image, original_hash = self.decode(command.image_base64, command.source_sha256)
            state = self.state(run)
            try:
                prompt, binding = self.task.prompt(state, node)
            except ValueError:
                raise HTTPException(503, '任务Prompt文件已变化，请审核并重启后端；本次未调用模型。') from None
            prompt = bound_prompt(prompt, self.task.document.task.task_id, state, node)
            contract = result_contract(state.state_id, node.inspection_id)
            check_id = uuid.uuid4().hex[:16]
            folder = run.folder/check_id; folder.mkdir()
            (folder/'input.jpg').write_bytes(image)
            (folder/'prompt.txt').write_text(prompt, encoding='utf-8')
            metadata = {'state_id': state.state_id, 'inspection_id': node.inspection_id,
                'client_frame_id': command.client_frame_id, 'source_sha256': original_hash,
                'input_sha256': hashlib.sha256(image).hexdigest(), 'prompt_sha256': binding['sha256'],
                'prompt_version': binding['prompt_version'], 'model': self.config['vlm']['model'], 'image_count': 1}
            (folder/'request.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2))
            self.event(run, 'vision.request', metadata)
            run.last_frame = command.client_frame_id
            started = perf_counter(); result = None; error_type = None; error_code = None
            attempts = []
            for attempt in range(2):
                try:
                    attempt_prompt = prompt if attempt == 0 else prompt + '\n上次输出字段或身份不符合Schema。本次请严格照抄上述两个ID，以当前图像重做判断，返回精简JSON。'
                    (folder/f'prompt-{attempt+1}.txt').write_text(attempt_prompt, encoding='utf-8')
                    raw = self.client.chat_structured(prompt=attempt_prompt, schema=contract.model_json_schema(),
                        images_base64=[base64.b64encode(image).decode()], max_tokens=self.config['verification']['max_tokens'])
                    # Preserve malformed application responses for diagnosis; never API headers/errors.
                    encoded = json.dumps(raw, ensure_ascii=False, indent=2)
                    key = self.config['vlm']['api_key']
                    if key: encoded = encoded.replace(key, '[REDACTED]')
                    (folder/f'model_response-{attempt+1}.json').write_text(encoded, encoding='utf-8')
                    result = contract.model_validate(raw)
                    (folder/'model_result.json').write_text(result.model_dump_json(indent=2), encoding='utf-8')
                    attempts.append({'attempt': attempt+1, 'status': 'valid'})
                    break
                except ValidationError as error:
                    fields = [{'field': '.'.join(map(str, item['loc']))[:100], 'type': item['type']}
                              for item in error.errors(include_input=False, include_context=False)][:20]
                    error_type = 'ValidationError'
                    attempts.append({'attempt': attempt+1, 'status': 'invalid_contract', 'fields': fields})
                except Exception as error:
                    error_type = type(error).__name__
                    match = re.search(r'HTTP (\d{3})\b', str(error))
                    error_code = match.group(1) if match else None
                    attempts.append({'attempt': attempt+1, 'status': 'provider_error', 'type': error_type, 'http': error_code})
                    break
            (folder/'diagnostics.json').write_text(json.dumps(attempts, ensure_ascii=False, indent=2), encoding='utf-8')
            elapsed = round((perf_counter()-started)*1000, 1)
            valid_identity = result is not None and result.matched_step_id == state.state_id and result.inspection_id == node.inspection_id
            status = result.status if valid_identity else 'uncertain'
            failure_kind = '' if result is not None else ('invalid_contract' if error_type == 'ValidationError' else 'provider_error')
            reason = ('模型回复格式未通过校验，已保留诊断记录。请重新检查；持续出现时联系维护人员。' if failure_kind == 'invalid_contract' else '视觉服务请求失败，请稍后重试；无需因此重新安装部件。')
            if result is None and error_code:
                reason = '视觉服务返回HTTP '+error_code+'。请在配置文件核对Key、模型权限或额度后重试。'
            evidence = result.evidence.strip() if valid_identity else reason
            if status == 'completed' and (result.confidence < self.config['verification']['minimum_confidence'] or not evidence):
                status = 'uncertain'; evidence = '可见证据或模型置信度不足。'+evidence
            if status not in ('completed', 'wrong_operation', 'uncertain'): status = 'uncertain'
            correction = result.next_action.strip() if valid_identity and status != 'completed' else ''
            if status != 'completed' and not correction:
                correction = '请重试本次检查；若持续失败，请查看后端诊断日志。' if failure_kind else '请对照参考图检查，并按指定角度补拍当前局部。'
            boxes = [b for b in result.component_boxes_0_1000 if b.component_id in node.component_ids] if valid_identity else []
            try: annotations = self.annotate(image, boxes, folder)
            except Exception:
                annotations = []; (folder/'annotated.jpg').write_bytes(image)
            saved = {'status': status, 'channel': 'vision', 'confidence': result.confidence if valid_identity else 0,
                'evidence': evidence, 'correction': correction, 'frame_id': command.client_frame_id,
                'image_url': f'{self.api_prefix}/{run.id}/captures/{check_id}', 'check_id': check_id,
                'source_sha256': original_hash, 'segmentation': 'display_only' if annotations else 'no_annotation',
                'annotations': annotations, 'elapsed_ms': elapsed, 'failure_kind': failure_kind, 'attempts': len(attempts),
                'service_error_type': error_type if result is None else None,
                'service_error_code': error_code, 'checked_at': now()}
            run.results[node.inspection_id] = saved
            run.revision += 1
            (folder/'decision.json').write_text(json.dumps(saved, ensure_ascii=False, indent=2))
            logging.getLogger(__name__).warning('vision.check task=%s state=%s node=%s status=%s failure=%s attempts=%s elapsed_ms=%s log=%s',
                self.task.document.task.task_id, state.state_id, node.inspection_id, status, failure_kind or 'none', len(attempts), elapsed, folder)
            self.event(run, 'vision.decision', {'inspection_id': node.inspection_id, **saved})
            self.save(run)
            return self.view(run)
        finally: run.lock.release()

    def navigate(self, identity, command, action):
        run = self.get(identity); self.acquire(run)
        try:
            self.check(run, command, observation=False)
            if action == 'advance':
                if self.pending(run) is not None: raise HTTPException(409, '本步仍有必要观察点未通过。')
                if run.index == len(self.task.document.states)-1: run.completed = True
                else: run.index += 1
            else:
                if action == 'back' and run.index == 0: raise HTTPException(409, '已经是第一步。')
                if action == 'back': run.index -= 1
                invalidate = {n.inspection_id for s in self.task.document.states[run.index:] for n in s.observation_nodes}
                run.results = {k: v for k,v in run.results.items() if k not in invalidate}
            run.revision += 1
            self.event(run, 'progress.'+action, {'state_id': self.state(run).state_id, 'completed': run.completed})
            self.save(run)
            return self.view(run)
        finally: run.lock.release()
