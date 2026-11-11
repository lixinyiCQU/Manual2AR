"""Session-local plan execution over compiled states; source and claims never mark steps done."""
import json
import time
import uuid
from copy import deepcopy
from types import SimpleNamespace
from fastapi import HTTPException
from manual2ar.knowledge.wiki import write_json
from manual2ar.knowledge.compilation.compiler import NONVISUAL
from .pipeline_spatial import ExperimentSpatial
from .scene_planning import assess,plan_for


class StatefulSpatial(ExperimentSpatial):
 def __init__(self,*args):
  super().__init__(*args)
  self.execution_plan=json.loads((self.candidate.run/'execution-plan.json').read_text())
  self.order=[r['action_id'] for r in self.execution_plan['steps']]
  first=self.states[self.order[0]]
  self.external=[]
  # A fragment's unproven prerequisites are a separate gate, not a missing hardcoded base step.
  for i,condition in enumerate(first.preconditions):
   for suffix,channel,text in (('V','vision','仅检查以下前置条件的可见状态，遮挡返回不确定：'+condition),('M','manual',condition)):
    if channel=='vision' and NONVISUAL.search(condition):continue
    self.external.append(SimpleNamespace(inspection_id=first.state_id+'-P'+str(i+1)+suffix,verification_channel=channel,condition=text))

 def ledger(self,s):
  if not hasattr(s,'execution'):
   s.execution=dict(index=0,done=[],assessed=False,revision=0,suggestions=deepcopy(self.execution_plan['steps']),
    prerequisites=not bool(self.external),assessment_inflight=False,prerequisite_check=False)
  return s.execution

 def execution(self,s):
  ledger=self.ledger(s);i=ledger['index'];complete=i>=len(self.order);i=min(i,len(self.order)-1)
  step=ledger['suggestions'][i];mode='complete' if complete else 'check' if not ledger['prerequisites'] else step['mode'] if ledger['assessed'] else 'observe'
  return dict(contract='manual2ar-execution-plan-v1',state_id=step['state_id'],action_id=step['action_id'],mode=mode,
   reason='当前任务的核验条件均已满足。' if complete else '需要在当前画面核查剩余任务的前置条件。' if not ledger['prerequisites'] else step['reason'] if ledger['assessed'] else '请先用当前画面评估现场；原照片不授权完成。',
   complete=complete,needs_assessment=not ledger['assessed'],prerequisite_only=not ledger['prerequisites'],
   completed_state_ids=list(ledger['done']),remaining_state_ids=[v['state_id'] for v in ledger['suggestions'][ledger['index']:]])

 def catalog(self):
  return {**super().catalog(),'runtime_contract':'compiled-spatial-v3','stateful_runtime':True,'execution_plan':self.execution_plan}

 def sequence_status(self,tutorial_run_id=''):
  return dict(enforced=False,base_approved=False,holder_approved=False,message='请按本候选的当前执行计划进行操作或核验；完成状态不从旧教程继承。')

 def begin(self,command):
  value=super().begin(command)
  with self.session(value['session_id']) as s:value['execution']=self.execution(s)
  return value

 def u7_progress(self,session,callback=None):
  value=super().u7_progress(session,callback)
  if not isinstance(value,dict):return value
  return {**value,'enforced':False,'execution':self.execution(session)}

 def require_u7(self,session,action_id):
  if action_id!=self.execution(session)['action_id']:raise HTTPException(409,'请先完成当前计划中的操作或核验，不可跳过前置状态。')

 def frame(self,identity,request):
  value=super().frame(identity,request)
  with self.session(identity) as s:
   execution=self.execution(s);value['execution']=execution
   if execution['mode']!='operate':
    value.update(visual=None,companion_visuals=[],machine_axes=[],reference_axes=[])
  return value

 def assess_scene(self,identity,request):
  frame=self.photo_frame(identity,request)
  with self.session(identity) as s:
   ledger=self.ledger(s)
   if ledger['assessment_inflight'] or ledger.get('verifying'):raise HTTPException(409,'当前现场仍在评估或核验。')
   ledger['assessment_inflight']=True;revision=ledger['revision'];epoch=getattr(s,'compiled_epoch',0)
  folder=self.root/'runs'/identity/('assessment-'+uuid.uuid4().hex)
  try:
   result=assess(self.client,frame['raw'],self.candidate,folder,self.config['verification']['minimum_confidence'])
   proposed=plan_for(self.candidate,result)
   with self.session(identity) as s:
    ledger=self.ledger(s);latest=s.frames.get(s.last)
    if ledger['revision']!=revision or getattr(s,'compiled_epoch',0)!=epoch or not latest or latest['action_id']!=request.action_id or time.monotonic()-frame['at']>120:
     raise HTTPException(409,'现场评估期间步骤已改变或照片过期，请重拍。')
    ledger.update(suggestions=proposed['steps'],assessed=True,revision=revision+1);s.compiled_check=None
    self.event(s,'execution.assessed',dict(source_sha256=frame['sha256'],client_frame_id=request.client_frame_id,execution=self.execution(s)))
    return dict(action_id=request.action_id,source_sha256=frame['sha256'],client_frame_id=request.client_frame_id,execution=self.execution(s),assessment=result)
  except HTTPException:raise
  except Exception:
   raise HTTPException(502,'现场对齐未取得有效证据，请重新评估；未放行任何步骤。') from None
  finally:
   with self.lock:current=self.sessions.get(identity)
   if current:
    with current.lock:self.ledger(current)['assessment_inflight']=False

 def verification_nodes(self,session,state):
  ledger=self.ledger(session);ledger['prerequisite_check']=not ledger['prerequisites']
  return self.external if ledger['prerequisite_check'] else super().verification_nodes(session,state)

 def verification_prompt(self,state,node):
  if node in self.external:return '当前任务原文：'+state.manual_provenance.source_text+'\n本地观察策略：'+node.condition+'\n不能通过照片证明机械紧固或历史操作。'
  return super().verification_prompt(state,node)

 def verify_u7(self,identity,request):
  with self.session(identity) as s:
   ledger=self.ledger(s)
   if self.execution(s)['complete']:raise HTTPException(409,'当前任务已完成，请返回或生成新的任务。')
   if not ledger['assessed']:raise HTTPException(409,'请先评估当前现场，再进行安装核验。')
   if ledger['assessment_inflight'] or ledger.get('verifying'):raise HTTPException(409,'请等待当前现场评估或核验完成。')
   ledger['verifying']=True
  try:return super().verify_u7(identity,request)
  finally:self.end_verification(identity)

 def confirm_manual(self,identity,command):
  with self.session(identity) as s:
   ledger=self.ledger(s)
   if ledger['assessment_inflight'] or ledger.get('verifying'):raise HTTPException(409,'请等待当前现场评估或核验完成。')
   ledger['verifying']=True
  try:return super().confirm_manual(identity,command)
  finally:self.end_verification(identity)

 def end_verification(self,identity):
  with self.lock:session=self.sessions.get(identity)
  if session:
   with session.lock:self.ledger(session)['verifying']=False

 def finish_check(self,s,action_id):
  value=super().finish_check(s,action_id);ledger=self.ledger(s);i=ledger['index']
  prerequisite=ledger['prerequisite_check']
  if value['status']=='completed':
   if prerequisite:ledger['prerequisites']=True
   else:
    state_id=self.states[action_id].state_id
    if state_id not in ledger['done']:ledger['done'].append(state_id)
    ledger['index']=min(i+1,len(self.order));ledger['assessed']=False
  elif not value['manual_pending']:
   # A failed prerequisite never becomes an invitation to execute the dependent action.
   ledger['suggestions'][i].update(mode='operate' if value['status']=='not_completed' and not prerequisite else 'observe',reason=value['evidence']+'\n'+value['next_action'])
  ledger['revision']+=1
  value.update(execution=self.execution(s),prerequisite_only=prerequisite)
  self.event(s,'execution.updated',dict(status=value['status'],source_sha256=value['source_sha256'],execution=value['execution'],prerequisite_only=prerequisite))
  write_json(self.root/'runs'/s.identity/'execution-state.json',dict(**value['execution'],last_check_photo=value['source_sha256']))
  return value
