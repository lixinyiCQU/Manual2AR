"""Free-browsing teaching contract, isolated from the earlier gated tasks."""
from pydantic import BaseModel, Field
from fastapi import HTTPException
from manual2ar.modules.guidance.task import TaskPackage
from manual2ar.modules.guidance.engine import GuideService, now
from .lesson import substep_caption
from . import u7_sequence as sequence


class Substep(BaseModel):
    id: str
    title: str
    instruction: str
    reference_images: list[str] = Field(default_factory=list)
    citation_ids: list[str] = Field(default_factory=list)


class TutorialCard(BaseModel):
    title: str
    reference_images: list[str]
    substeps: list[Substep] = Field(default_factory=list)
    applicability_note: str = ''
    optional: bool = False
    official_heading: str


class TutorialTaskPackage(TaskPackage):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        if self.params.get('navigation_policy')!='free' or self.params.get('verification_role')!='advisory':
            raise ValueError('Tutorial contract must separate browsing and visual advice')
        self.cards={key:TutorialCard.model_validate(value) for key,value in self.params['presentation'].items()}
        for state in self.document.states:
            card=self.cards[state.state_id]
            if len(state.observation_nodes)!=1:raise ValueError('One final-outcome advisory observation per chapter')
            seen=set()
            for sub in card.substeps:
                if not sub.id.startswith(state.state_id+'-S') or sub.id in seen:raise ValueError('Invalid substep identity')
                seen.add(sub.id)
                for citation in sub.citation_ids:
                    if citation not in self.evidence['evidence']:raise ValueError('Missing substep citation')
            for image in [*card.reference_images,*[p for sub in card.substeps for p in sub.reference_images]]:
                if image not in self.evidence['images']:raise ValueError('Missing substep image')
        for item in self.images.values():
            for frame in item.get('animation_frames',[]):
                if frame['path'] not in self.evidence['images']:raise ValueError('Missing GIF frame atlas')

    def photo(self,relative):
        item=self.evidence['images'][relative];name=relative.rsplit('/',1)[-1]
        result={'id':name,'url':self.reference_prefix+name,'local_file':self.local_reference_dir+'/'+name,
                'sha256':item['sha256'],'caption':'官方参考图','source_url':item['source_page']}
        result['animation_frames']=[]
        for frame in item.get('animation_frames',[]):
            atlas=self.evidence['images'][frame['path']];filename=frame['path'].rsplit('/',1)[-1]
            result['animation_frames'].append({'url':self.reference_prefix+filename,
                'local_file':self.local_reference_dir+'/'+filename,'sha256':atlas['sha256'],
                'duration_ms':frame['duration_ms'],'uv':frame['uv']})
        return result

    def images_for(self,state):return [self.photo(p) for p in self.cards[state.state_id].reference_images]

    def presentation(self,state,pending):
        card=self.cards[state.state_id]
        # Deliberately bypass the legacy U9-specific power-on UI rule.
        return {'title':card.title,'instruction':state.instruction,'warnings':[], 'tools':[], 'materials':[],
                'display_conditions':[], 'images':self.images_for(state),'sources':self.sources_for(state),
                'applicability_note':card.applicability_note,'optional':card.optional}

    def catalog(self):
        value=super().catalog()
        value.update(navigation_policy='free',verification_role='advisory',official_source=self.params['official_source'])
        for step in value['steps']:
            step['optional']=self.cards[step['id']].optional
            step['substeps']=[{'id':s.id,'title':s.title} for s in self.cards[step['id']].substeps]
        return value


class TutorialService(GuideService):
    """Navigation never invokes VLM or manufactures an operation/check success."""
    def ensure(self,run):
        if not hasattr(run,'tutorial_visits'):
            run.tutorial_visits={self.state(run).state_id};run.tutorial_marks={};run.tutorial_substeps={}

    def pending(self,run):
        return None if run.completed else self.state(run).observation_nodes[0]

    def view(self,run):
        self.ensure(run);value=super().view(run);state=self.state(run);card=self.task.cards[state.state_id]
        selected=run.tutorial_substeps.get(state.state_id,card.substeps[0].id if card.substeps else '')
        value['substeps']=[{'id':s.id,'title':s.title,'display_title':substep_caption(s.title,s.instruction)} for s in card.substeps]
        value['selected_substep_id']=selected
        if sequence.enabled(self.task):
            value['u7_sequence']=sequence.state(run)
            for substep in value['substeps']:
                substep['locked']=state.state_id=='U7' and substep['id']=='U7-S2' and not value['u7_sequence']['base_approved']
        if selected:
            sub=next(s for s in card.substeps if s.id==selected)
            first=self.task.evidence['evidence'][card.substeps[0].citation_ids[0]]['ordinal']
            context=[self.task.evidence['evidence'][c] for c in state.manual_provenance.citation_ids]
            value['presentation']['chapter_context']='\n\n'.join(dict.fromkeys(b['text'] for b in context if b['ordinal']<first and b['kind'] not in ('h2','h3','table')))
            value['presentation']['instruction']=sub.instruction
            value['presentation']['images']=[self.task.photo(p) for p in sub.reference_images]
            value['presentation']['substep_title']=sub.title
        value.update(navigation_policy='free',verification_role='advisory',
            visited_step_ids=sorted(run.tutorial_visits),user_marked_step_ids=list(run.tutorial_marks),
            can_advance=not run.completed,can_back=run.index>0,
            completion_source='tutorial_browsing_finished' if run.completed else '')
        if state.state_id=='U7' and sequence.enabled(self.task):
            key=sequence.stage(selected);record=run.u7_checks.get(key,{})
            condition='灰色底座已安装到立柱，上下两颗螺丝在位且可见。' if key=='base' else '白色料盘支架已连接到立柱底座。'
            value['current_condition']=condition
            value['capture_instruction']='从立柱背面拍清灰色底座和上下两颗固定螺丝，避免手或支架遮挡。' if key=='base' else '拍清白色支架与立柱的最终连接位置。'
            for observation in value['observations']:
                observation.update(status=record.get('status','not_started'),evidence=record.get('evidence',''),correction=record.get('correction',''),condition=condition)
                for field in ['frame_id','source_sha256','image_url','failure_kind']:observation[field]=record.get(field,0 if field=='frame_id' else '')
            if key=='base':value['can_advance']=value['u7_sequence']['base_approved']
        return value

    def confirm(self,identity,command):
        run=self.get(identity);self.acquire(run)
        try:
            self.check(run,command)
            if not command.confirmed:raise HTTPException(400,'请明确标记已操作，或直接浏览下一步。')
            if self.state(run).state_id in getattr(self.task,'spatial_chapters',set()):raise HTTPException(409,'本章通过空间指导的视觉核验记录完成状态，不能用手动标记替代。')
            self.ensure(run);run.tutorial_marks[self.state(run).state_id]={'at':now(),'actor':'user','basis':'self_report'}
            run.revision+=1;self.event(run,'tutorial.user_marked',{'state_id':self.state(run).state_id,'not_a_visual_pass':True})
            self.save(run);return self.view(run)
        finally:run.lock.release()

    def annotate(self,image,boxes,folder):
        # This tutorial asks VLM for final-outcome advice only. No segmentation,
        # tracking, or generated highlight is presented as installation evidence.
        (folder/'annotated.jpg').write_bytes(image)
        return []

    def _select(self,run,target,substep=None):
        state=next((s for s in self.task.document.states if s.state_id==target),None)
        if state is None:raise HTTPException(422,'当前教程没有这个章节。')
        card=self.task.cards[target]
        if substep is not None and substep not in {s.id for s in card.substeps}:
            raise HTTPException(422,'分步骤不属于所选章节。')
        self.ensure(run)
        if target=='U7' and sequence.enabled(self.task):
            effective=substep or run.tutorial_substeps.get('U7','U7-S1')
            if substep is None and effective=='U7-S2' and not sequence.state(run)['base_approved']:effective=substep='U7-S1'
            sequence.require(run,effective)
        before=self.state(run).state_id;run.index=self.task.document.states.index(state);run.completed=False
        if substep is not None:run.tutorial_substeps[target]=substep
        run.tutorial_visits.add(target);run.revision+=1
        self.event(run,'tutorial.navigated',{'from':before,'to':target,'substep_id':substep,'verification_gate':False})
        self.save(run);return self.view(run)

    def browse(self,identity,command):
        run=self.get(identity);self.acquire(run)
        try:
            if command.state_id!=self.state(run).state_id or command.revision!=run.revision:
                raise HTTPException(409,'页面已更新，请重新连接后操作。')
            return self._select(run,command.target_state_id,command.substep_id)
        finally:run.lock.release()

    def navigate(self,identity,command,action):
        run=self.get(identity);self.acquire(run)
        try:
            self.check(run,command,observation=False);self.ensure(run)
            if action=='advance' and self.state(run).state_id=='U7' and sequence.enabled(self.task) and run.tutorial_substeps.get('U7','U7-S1')=='U7-S1':
                return self._select(run,'U7','U7-S2')
            if action=='advance':
                if run.index<len(self.task.document.states)-1:
                    return self._select(run,self.task.document.states[run.index+1].state_id)
                run.completed=True;run.revision+=1
                self.event(run,'tutorial.browsing_finished',{'operation_complete':False,'visual_verified':False})
            elif action=='back':
                if self.state(run).state_id=='U7' and sequence.enabled(self.task) and run.tutorial_substeps.get('U7')=='U7-S2':return self._select(run,'U7','U7-S1')
                if run.index==0:raise HTTPException(409,'已经是第一章。')
                return self._select(run,self.task.document.states[run.index-1].state_id)
            elif action=='recheck':
                run.spatial_checks.pop(self.state(run).state_id,None)
                if self.state(run).state_id=='U7' and sequence.enabled(self.task):sequence.reset(run,run.tutorial_substeps.get('U7','U7-S1'))
                run.results.pop(self.state(run).observation_nodes[0].inspection_id,None);run.revision+=1
                self.event(run,'tutorial.advice_cleared',{'state_id':self.state(run).state_id})
            else:raise HTTPException(422,'不支持的教程操作。')
            self.save(run);return self.view(run)
        finally:run.lock.release()

    def verify(self,identity,command):
        run=self.get(identity)
        if self.state(run).state_id!='U7' or not sequence.enabled(self.task):return super().verify(identity,command)
        import uuid,time
        from pathlib import Path
        from .spatial.u7_vision import base_installation,installation,load_references
        from .spatial.vision_context import failure
        self.acquire(run)
        try:
            node=self.check(run,command);selected=run.tutorial_substeps.get('U7','U7-S1');sequence.require(run,selected)
            if command.client_frame_id<=run.last_frame:raise HTTPException(409,'请重新拍摄当前分步骤。')
            if not self.config['vlm']['api_key'].strip():raise HTTPException(503,'请在配置文件填写 VLM API Key。')
            raw,sha=self.decode(command.image_base64,command.source_sha256);token=sequence.start(run,selected)
            folder=run.folder/uuid.uuid4().hex[:16];folder.mkdir();(folder/'annotated.jpg').write_bytes(raw)
            refs=load_references(self.config);started=time.perf_counter();error=False
            try:
                answer=base_installation(self.client,self.config,raw,refs['base'],folder) if selected=='U7-S1' else installation(self.client,self.config,raw,refs['installation'],folder)
            except Exception as exc:
                failure(folder,exc);error=True;answer={'status':'uncertain','confidence':0,'evidence':'视觉服务暂不可用，请重新拍照检查。','next_action':'请稍后重试。'}
            saved={'status':'wrong_operation' if answer['status']=='not_completed' else answer['status'],'channel':'vision','confidence':answer['confidence'],
                'evidence':answer['evidence'],'correction':answer['next_action'],'frame_id':command.client_frame_id,'source_sha256':sha,
                'check_id':folder.name,'image_url':f'{self.api_prefix}/{run.id}/captures/{folder.name}',
                'substep_id':selected,'failure_kind':'provider_error' if error else '', 'checked_at':now(),'elapsed_ms':round((time.perf_counter()-started)*1000)}
            sequence.finish(run,selected,token,saved);run.results[node.inspection_id]=saved;run.last_frame=command.client_frame_id;run.revision+=1
            self.event(run,'u7.installation_checked',saved);self.save(run);return self.view(run)
        finally:run.lock.release()
