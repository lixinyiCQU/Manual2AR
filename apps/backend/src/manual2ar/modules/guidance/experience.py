"""Source-bound action discovery, records and explicitly sourced chapter completion.

The tutorial owns chapter navigation; spatial providers own positioning. This
bridge binds their identities without making a replay or animation a visual pass.
"""
from copy import deepcopy
from datetime import datetime, timezone
from fastapi import HTTPException
from manual2ar.resources import ResourceStore


class UnboxingExperience:
    def __init__(self, guidance):
        self.guidance = guidance
        self.plan = ResourceStore.configured(guidance.config).json('task.unboxing.spatial')
        _, task = guidance.registry.resolve(self.plan['task_id'], self.plan['variant_id'])
        task.spatial_chapters={a['chapter_id'] for a in self.plan['actions']}
        self.actions = {}
        for original in self.plan['actions']:
            action = deepcopy(original)
            card = task.cards[action['chapter_id']]
            matches = [s.id for s in card.substeps if set(s.citation_ids) & set(action['citation_ids'])]
            action['substep_id'] = matches[0] if matches else ''
            if card.substeps and not matches:
                raise ValueError('Spatial action must map to an official substep')
            for citation in action['citation_ids']:
                if citation not in task.evidence['evidence']:
                    raise ValueError('Spatial action has no official source')
            self.actions[action['action_id']] = action

    def catalog(self):
        return {**self.plan, 'actions': list(self.actions.values())}

    def context(self, identity):
        with self.guidance.lock:
            meta, engine, run = self.guidance.parts(identity)
            if (meta['task_id'], meta['variant_id']) != (self.plan['task_id'], self.plan['variant_id']):
                raise HTTPException(409, '此版本提供官方图文指导；当前空间动作仅适用于单机开箱。')
            if meta['status'] != 'running' or meta['returned']:
                raise HTTPException(409, '当前教程已结束，请重新进入开箱任务。')
            return {'tutorial_run_id': identity, 'task_id': meta['task_id'],
                    'variant_id': meta['variant_id'], 'task_revision': engine.task.revision}

    def attach(self, value, meta, engine, run):
        supported = (meta['task_id'], meta['variant_id']) == (self.plan['task_id'], self.plan['variant_id'])
        all_actions = list(self.actions.values()) if supported else []
        chapter_actions = [a for a in all_actions if a['chapter_id'] == value['state_id']]
        selected = value.get('selected_substep_id', '')
        current = [a for a in chapter_actions if not selected or a['substep_id'] == selected]
        value['spatial_guidance'] = {'available': bool(chapter_actions), 'actions': chapter_actions,
            'current_action_ids': [a['action_id'] for a in current],
            'scope_label': 'Windows 摄像头 · 有标记空间指导' if chapter_actions else '官方图文指导',
            'learning_records': getattr(run, 'spatial_learning', []),
            'record_url': '/api/guidance/runs/' + run.id + '/report'}
        completion=[]
        for chapter in value['task_info']['steps']:
            spatial=any(a['chapter_id']==chapter['id'] for a in all_actions)
            chapter['spatial_mode']='marker' if spatial else 'official'
            if spatial and chapter['id']=='U7':
                from . import u7_sequence
                done=u7_sequence.state(run)['holder_approved']
            elif spatial:
                state=next(v for v in engine.task.document.states if v.state_id==chapter['id'])
                observed=getattr(run,'spatial_checks',{}).get(chapter['id'])
                done=observed.get('status')=='completed' if observed is not None else all(run.results.get(n.inspection_id,{}).get('status')=='completed' and run.results.get(n.inspection_id,{}).get('channel')=='vision' for n in state.observation_nodes)
            else:done=chapter['id'] in getattr(run,'tutorial_marks',{})
            completion.append({'state_id':chapter['id'],'completed':bool(done),'source':'visual_verification' if spatial else 'user_confirmation'})
        value['chapter_completion']=completion
        return value

    def record(self, context, session_id, mode, action, target_id, name, details=None):
        if not context:
            return
        identity = context['tutorial_run_id']
        with self.guidance.lock:
            self.context(identity)
            _, engine, run = self.guidance.parts(identity)
            engine.acquire(run)
            try:
                if not hasattr(run, 'spatial_learning'):
                    run.spatial_learning = []
                item = {'session_id': session_id, 'mode': mode, 'action_id': action['action_id'],
                    'chapter_id': action['chapter_id'], 'substep_id': action['substep_id'],
                    'target_id': target_id, 'event': name, 'at': datetime.now(timezone.utc).isoformat(),
                    'operation_verified': False, **(details or {})}
                if name=='chapter_advice' and mode=='camera' and details:
                    run.spatial_checks[action['chapter_id']]={'status':details.get('advice_status','uncertain'),'source_sha256':details.get('source_sha256','')}
                run.spatial_learning.append(item)
                # Bound the response; full records remain in append-only events.jsonl.
                run.spatial_learning = run.spatial_learning[-100:]
                engine.event(run, 'spatial.' + name, item)
                engine.save(run)
            finally:
                run.lock.release()

    def u7_progress(self,context,callback=None):
        from . import u7_sequence as sequence
        with self.guidance.lock:
            self.context(context['tutorial_run_id']);_,engine,run=self.guidance.parts(context['tutorial_run_id'])
            engine.acquire(run)
            try:
                result=callback(run) if callback else sequence.state(run)
                if callback:
                    run.revision+=1;engine.event(run,'u7.sequence_changed',sequence.state(run));engine.save(run)
                return result
            finally:run.lock.release()
