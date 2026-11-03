"""Coordinate isolated task engines without sharing mutable progress or trusting client completion."""
from copy import deepcopy
from datetime import datetime, timezone
import json
import threading
from time import monotonic
import uuid
from fastapi import HTTPException
from manual2ar.modules.guidance.engine import GuideService
from .registry import TaskRegistry, FIRST, LOAD, UNLOAD


class GuidanceService:
    def __init__(self, config, client=None, log_root=None, registry=None):
        from pathlib import Path
        self.config = config
        self.registry = registry or TaskRegistry(config)
        self.engines = {}
        engine_config = deepcopy(config)
        # Flow lifetime/limits are owned by this coordinator, including suspended parents.
        engine_config['sessions'] = {'max_runs': config['sessions']['max_runs'], 'idle_minutes': 10**9}
        for key, task in self.registry.packages.items():
            from .tutorial import TutorialService
            engine_class = TutorialService if task.params.get("navigation_policy") == "free" else GuideService
            self.engines[key] = engine_class(engine_config, task, client,
                log_root or Path(config['runtime_dir'])/'guidance',
                api_prefix='/api/guidance/runs', config_label='configs/app.local.json')
        self.meta = {}
        self.closing = set()
        self.lock = threading.RLock()
        from .experience import UnboxingExperience
        self.experience = UnboxingExperience(self)
        from .lesson import LessonPresenter
        self.lessons = LessonPresenter(config)

    def parts(self, identity):
        item = self.meta.get(identity)
        if item is None: raise HTTPException(404, '任务记录不存在或已过期，请返回任务选择页。')
        engine = self.engines[(item['task_id'], item['variant_id'])]
        run = engine.get(identity)
        root = item
        while root['parent_run_id']: root = self.meta[root['parent_run_id']]
        root['last_active'] = monotonic()
        return item, engine, run

    def event(self, identity, name, data):
        item, engine, run = self.parts(identity)
        engine.event(run, name, {'task_id': item['task_id'], 'variant_id': item['variant_id'],
                               'parent_run_id': item['parent_run_id'], **data})

    def save(self, identity):
        _, _, run = self.parts(identity)
        (run.folder/'flow.json').write_text(json.dumps(self._view(identity), ensure_ascii=False, indent=2), encoding='utf-8')

    def cleanup(self):
        # Called under the coordinator lock; expired flows are removed as a unit.
        idle = self.config['sessions']['idle_minutes']*60
        for identity, item in list(self.meta.items()):
            if item['parent_run_id'] or monotonic()-item['last_active'] < idle: continue
            members = [identity]+[k for k,m in self.meta.items() if m['parent_run_id'] == identity]
            if any(self.meta[k]['busy'] for k in members): continue
            self.drop_flow(identity,'flow.expired')
        while len(self.meta)>=self.config['sessions']['max_runs']:
            ended=[(m['last_active'],k) for k,m in self.meta.items()
                   if not m['parent_run_id'] and m['status'] in ('completed','cancelled') and not m['busy']]
            if not ended: break
            self.drop_flow(min(ended)[1],'flow.evicted')

    def drop_flow(self, identity, event):
        members=[identity]+[k for k,m in self.meta.items() if m['parent_run_id']==identity]
        for key in reversed(members):
            _,engine,run=self.parts(key)
            engine.event(run,event,{'disk_records_preserved':True})
            engine.runs.pop(key,None);self.meta.pop(key,None)

    def _create(self, task_id, variant_id=None, parent=None, action_id='', context=None):
        variant, task = self.registry.resolve(task_id, variant_id)
        self.cleanup()
        if len(self.meta) >= self.config['sessions']['max_runs']:
            raise HTTPException(429, '任务记录已达上限，请结束旧指导或稍后重试。')
        engine = self.engines[(task_id, variant)]
        response = engine.begin(); identity = response['run_id']
        self.meta[identity] = {'task_id': task_id, 'variant_id': variant, 'status': 'running', 'busy': False,
            'parent_run_id': parent or '', 'action_id': action_id, 'context': context or uuid.uuid4().hex,
            'active_child': '', 'queue': [], 'receipts': [], 'returned': False, 'notice': '',
            'last_active': monotonic(), 'return_binding': None}
        self.event(identity, 'task.started', {'device_context_id': self.meta[identity]['context'], 'task_revision': task.revision})
        self.save(identity)
        return identity

    def begin(self, task_id, variant_id=None):
        with self.lock:
            self.cleanup()
            identity = self._create(task_id, variant_id)
            return self._view(identity)

    def actions(self, identity):
        m, _, run = self.parts(identity)
        if m['busy'] or m['returned'] or m['status'] == 'cancelled': return []
        if m['status'] == 'completed':
            if m['parent_run_id']: return [{'id': 'return_parent', 'label': '返回首次打印，复核耗材准备'}]
            if m['task_id'] == UNLOAD: return [{'id': 'open_load', 'label': '继续进料指导'}]
            if m['task_id'] == LOAD: return [{'id': 'open_first_print', 'label': '开始首次打印指导'}]
            return []
        if m['status'] == 'waiting_child':
            if m['active_child']: return [{'id': 'resume_child', 'label': '继续当前进料／退料指导'}]
            if m['queue']: return [{'id': 'start_next', 'label': '退料已完成，开始进料指导'},
                                   {'id': 'stop_sequence', 'label': '我自行处理后续操作，返回确认'}]
        if m['task_id'] == FIRST and self.engines[(m['task_id'],m['variant_id'])].state(run).state_id == 'P3':
            engine = self.engines[(m['task_id'],m['variant_id'])]
            pending = engine.pending(run)
            if pending and pending.inspection_id == 'P3-C1':
                return [{'id': 'guided_load', 'label': '需要进料指导'},
                        {'id': 'guided_replace', 'label': '需要先退料，再进料'}]
        if (m['task_id'], self.engines[(m['task_id'],m['variant_id'])].state(run).state_id) in ((LOAD,'L6'),(UNLOAD,'D4')):
            return [{'id': 'retry', 'label': '已在设备选择重试，重新按步骤操作'}]
        return []

    def _view(self, identity):
        m, engine, run = self.parts(identity)
        value = engine.view(run)
        entry = self.registry.entry(m['task_id'])
        parent_title = self.registry.entry(self.meta[m['parent_run_id']]['task_id'])['title'] if m['parent_run_id'] else ''
        value.update(task_id=m['task_id'], variant_id=m['variant_id'], status=m['status'],
            parent_run_id=m['parent_run_id'], device_context_id=m['context'],
            flow_label=(parent_title+' → ' if parent_title else '')+entry['title'],
            task_info=engine.task.catalog(), completion_scope=engine.task.params.get('completion_scope', ''),
            available_actions=self.actions(identity), child_receipts=m['receipts'],
            flow_notice=m['notice'], last_client_frame_id=run.last_frame,
            can_cancel=m['status'] in ('running','waiting_child') and not m['busy'],
            can_advance=value['can_advance'] and m['status']=='running' and not m['busy'])
        if m['status'] != 'running':
            value['channel'] = ''; value['capture_instruction'] = ''; value['can_back'] = False
        value['presentation']['lesson']=self.lessons.compose(m['variant_id'],value['state_id'],
            value.get('selected_substep_id',''),value['presentation'],engine.task)
        return self.experience.attach(value, m, engine, run)

    def view(self, identity):
        with self.lock:
            m, engine, run = self.parts(identity)
            if m['busy']: raise HTTPException(409, '当前检查仍在处理，请稍后同步。')
            engine.acquire(run)
            try: return self._view(identity)
            finally: run.lock.release()

    def validate(self, identity, command, active=True):
        m, engine, run = self.parts(identity)
        if identity in self.closing or m['parent_run_id'] in self.closing:
            raise HTTPException(409,'任务已结束。')
        if m['busy']: raise HTTPException(409, '当前任务正在处理中，请稍后同步。')
        if command.revision != run.revision or command.state_id != engine.state(run).state_id:
            raise HTTPException(409, '任务进度已变化，请同步后重试。')
        if active and (m['status'] != 'running' or m['returned']):
            raise HTTPException(409, '当前任务正在等待子任务或已结束，不能推进。')
        return m, engine, run

    def mutate(self, identity, command, action):
        with self.lock:
            m, engine, run = self.validate(identity, command)
            m['busy'] = True
        try:
            # Do not hold a global lock across a cloud request. Other sessions remain usable.
            if action == 'confirm': engine.confirm(identity, command)
            elif action == 'verify': engine.verify(identity, command)
            else: engine.navigate(identity, command, action)
            with self.lock:
                if run.completed: m['status'] = 'completed'
                if action == 'confirm' and m['task_id'] == FIRST and command.state_id == 'P3':
                    record = run.results['P3-C1']
                    record['related_child_runs'] = [r['run_id'] for r in m['receipts'] if r['status']=='completed']
                    record['completion_source'] = 'manual_after_child' if record['related_child_runs'] else 'manual_assertion'
                    self.event(identity, 'readiness.confirmed', {'completion_source': record['completion_source'],
                                                              'related_child_runs': record['related_child_runs']})
                    engine.save(run)
                m['busy'] = False
                self.save(identity)
                return self._view(identity)
        finally:
            with self.lock:
                m['busy'] = False
                for root in list(self.closing):
                    self.close(root)

    def close(self,identity):
        with self.lock:
            if identity not in self.meta:return
            root=identity
            while self.meta[root]['parent_run_id']:root=self.meta[root]['parent_run_id']
            members=[k for k,m in self.meta.items() if k==root or m['parent_run_id']==root]
            if any(self.meta[k]['busy'] for k in members):
                self.closing.add(root)
                return
            self.closing.discard(root)
            self.drop_flow(root,'flow.closed')

    def browse(self, identity, command):
        with self.lock:
            m,engine,run=self.validate(identity,command,active=False)
            if engine.task.params.get('navigation_policy')!='free':raise HTTPException(409,'本任务尚未开放自由浏览。')
            if m['status'] not in ('running','completed') or m['returned']:raise HTTPException(409,'当前教程已经结束或被取消。')
            m['busy']=True
        try:
            engine.browse(identity,command)
            with self.lock:
                m['status']='running';m['busy']=False;self.save(identity);return self._view(identity)
        finally:
            with self.lock:m['busy']=False

    def _start_child(self, parent_id, task_id):
        parent, engine, run = self.parts(parent_id)
        if parent['active_child']: raise HTTPException(409, '已有子任务在执行。')
        # No parent mutation until child allocation succeeds.
        child_id = self._create(task_id, parent=parent_id, action_id=parent['action_id'], context=parent['context'])
        parent['active_child'] = child_id; parent['status'] = 'waiting_child'; run.revision += 1
        parent['notice']='正在执行'+self.registry.entry(task_id)['title']+'指导，完成后返回耗材准备。'
        self.meta[child_id]['return_binding'] = {'parent_revision': run.revision,
            'parent_state': engine.state(run).state_id, 'parent_task_revision': engine.task.revision,
            'nonce': uuid.uuid4().hex}
        self.event(parent_id, 'child.started', {'child_run_id': child_id, 'child_task_id': task_id})
        self.save(parent_id); self.save(child_id)
        return self._view(child_id)

    def _return(self, child_id, cancelled=False):
        child, child_engine, child_run = self.parts(child_id)
        parent_id = child['parent_run_id']
        if not parent_id or child['returned']: raise HTTPException(409, '没有可返回的父任务。')
        parent, engine, run = self.parts(parent_id)
        binding = child['return_binding']
        if (parent['status']!='waiting_child' or parent['active_child']!=child_id or
            binding is None or binding['parent_revision']!=run.revision or
            binding['parent_state']!=engine.state(run).state_id or binding['parent_task_revision']!=engine.task.revision or
            parent['context']!=child['context']):
            raise HTTPException(409, '父子任务关系已变化，不能复用旧返回结果。')
        if not cancelled and not child_run.completed: raise HTTPException(409, '子任务尚未完成。')
        child['returned'] = True; child_run.revision += 1
        child['status'] = 'cancelled' if cancelled else 'completed'
        parent['receipts'].append({'run_id': child_id, 'task_id': child['task_id'],
            'title': self.registry.entry(child['task_id'])['title'], 'status': child['status'],
            'task_revision': child_engine.task.revision, 'recorded_at': datetime.now(timezone.utc).isoformat()})
        parent['active_child'] = ''; run.revision += 1
        if cancelled:
            parent['queue'] = []; parent['status'] = 'running'
            parent['notice'] = '子任务已取消，耗材准备仍需你确认；已完成退料时，请先完成后续进料。'
        elif parent['queue']:
            parent['notice'] = '退料指导已完成，尚未进料。请继续进料指导，或自行完成后再确认。'
        else:
            parent['status'] = 'running'
            parent['notice'] = '进料指导已完成。请复核当前设备的耗材准备，再确认本项。'
        self.event(child_id, 'child.cancelled' if cancelled else 'child.returned', {'parent_run_id': parent_id})
        self.event(parent_id, 'parent.resumed', {'child_run_id': child_id, 'child_status': child['status']})
        self.save(child_id); self.save(parent_id)
        return self._view(parent_id)

    def action(self, identity, command, action_id):
        with self.lock:
            m, engine, run = self.validate(identity, command, active=False)
            if action_id not in {a['id'] for a in self.actions(identity)}: raise HTTPException(409, '当前页面不允许此操作。')
            if action_id in ('guided_load','guided_replace'):
                old_queue, old_action = list(m['queue']), m['action_id']
                m['action_id'] = action_id
                sequence = [LOAD] if action_id=='guided_load' else [UNLOAD,LOAD]
                m['queue'] = sequence[1:]
                try: return self._start_child(identity, sequence[0])
                except Exception:
                    m['queue'], m['action_id'] = old_queue, old_action
                    raise
            if action_id == 'return_parent': return self._return(identity)
            if action_id == 'resume_child': return self._view(m['active_child'])
            if action_id == 'start_next':
                task_id = m['queue'][0]
                result = self._start_child(identity, task_id)
                m['queue'].pop(0); self.save(identity)
                return result
            if action_id == 'stop_sequence':
                m['queue'] = []; m['status'] = 'running'; run.revision += 1
                m['notice'] = '后续引导已停止，请自行完成进料后再确认耗材准备。'
                self.event(identity, 'children.stopped', {}); self.save(identity)
                return self._view(identity)
            if action_id in ('open_load','open_first_print'):
                new_id = self._create(LOAD if action_id=='open_load' else FIRST, context=m['context'])
                self.event(identity, 'task.followup', {'next_run_id': new_id})
                return self._view(new_id)
            if action_id == 'retry':
                if not command.confirmed: raise HTTPException(400, '请先在设备选择重试，再确认返回相应操作步骤。')
                target = 'L5' if m['task_id']==LOAD else 'D2'
                engine.acquire(run)
                try:
                    index = next(i for i,s in enumerate(engine.task.document.states) if s.state_id==target)
                    invalidate = {n.inspection_id for s in engine.task.document.states[index:] for n in s.observation_nodes}
                    run.results = {k:v for k,v in run.results.items() if k not in invalidate}
                    run.index = index; run.revision += 1
                    self.event(identity, 'progress.retry', {'target_state': target, 'device_retry_confirmed': True})
                    engine.save(run); self.save(identity)
                    return self._view(identity)
                finally: run.lock.release()

    def cancel(self, identity, command, whole_flow=False):
        with self.lock:
            m, engine, run = self.validate(identity, command, active=False)
            if whole_flow:
                if m['returned']: raise HTTPException(409, '该子任务已经返回，不能使用旧页面结束父任务。')
                root_id = m['parent_run_id'] or identity
                root, _, _ = self.parts(root_id)
                if root['status'] in ('completed','cancelled'): raise HTTPException(409, '当前指导已经结束。')
                active = root['active_child']
                if active:
                    if self.meta[active]['busy']: raise HTTPException(409, '子任务仍在检查，暂不能结束。')
                    _, _, active_run = self.parts(active)
                    self._return(active, cancelled=not active_run.completed)
                m, engine, run = self.parts(root_id)
                m['queue'] = []; m['active_child'] = ''; m['status'] = 'cancelled'; run.revision += 1
                self.event(root_id, 'flow.cancelled', {}); self.save(root_id)
                return self._view(root_id)
            if m['status'] in ('completed','cancelled') or m['returned']:
                raise HTTPException(409, '当前指导已经结束。')
            if m['parent_run_id']: return self._return(identity, cancelled=True)
            if m['active_child']: raise HTTPException(409, '请先结束当前子任务，或结束整个指导。')
            m['status'] = 'cancelled'; run.revision += 1
            self.event(identity, 'task.cancelled', {}); self.save(identity)
            return self._view(identity)
