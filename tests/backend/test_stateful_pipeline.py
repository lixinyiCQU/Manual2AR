"""Initial scene proposals cannot authorize completion; same task supports different现场 states."""
import json
from copy import deepcopy
import pytest
from tests.backend.test_wiki_to_ar import setup,question,completed
from tests.backend.test_pipeline_ablation import EnhancedVLM,approve
from tests.backend.guidance.test_spatial import frame


def generate(setup,modes=None):
 c,p,_=setup;fake=EnhancedVLM();fake.scene_states=modes or {};p.client=fake
 command=question();command['intent']='我已经安装了支架底座，现在我要安装料盘支架';command['experiment']={'stateful_planning':True}
 id=c.post('/api/guidance/pipeline/jobs',json=command).json()['id'];value=completed(c,id);assert value['status']=='ready',value
 return value,fake


def assess(c,api,action='holder.base',number=1):
 f=frame(action=action,number=number);assert c.post(api+'/frames',json=f).status_code==200
 r=c.post(api+'/assess',json={'action_id':action,'client_frame_id':number});assert r.status_code==200,r.text
 return r.json()


def verify(c,api,action='holder.base',number=1):
 r=c.post(api+'/verify',json={'action_id':action,'client_frame_id':number});assert r.status_code==200,r.text
 value=r.json()
 if value['manual_pending']:
  r=c.post(api+'/manual-conditions',json={'action_id':action,'inspection_ids':value['manual_pending'],'confirmed':True});assert r.status_code==200,r.text;value=r.json()
 return value


def test_full_manual_is_separate_from_claims_and_photo_state(setup):
 c,p,_=setup;value,fake=generate(setup)
 folder=p.root/'jobs'/value['id'];request=json.loads((folder/'compile/request.json').read_text())
 assert '我已经安装' not in json.dumps(request,ensure_ascii=False)
 assert len(value['candidate']['states'])==2
 assert value['candidate']['execution_plan']['completion_authorized'] is False
 assert [s['mode'] for s in value['candidate']['execution_plan']['steps']]==['check','operate']
 titles=[k['schema']['title'] for k in fake.calls];assert titles.index('TaskScene')>titles.index('DirectDraft')
 session,sid=approve(c,value);service=p.spatial[value['id']]
 assert c.get(session.rsplit('/sessions/',1)[0]+'/config').json()['runtime_contract']=='compiled-spatial-v3'
 s=service.sessions[sid];assert not service.execution(s)['completed_state_ids'] and service.execution(s)['needs_assessment']
 assert c.post(session+'/frames',json=frame(action='holder.slide')).status_code==409
 assert c.post(session+'/frames',json=frame(action='holder.base')).status_code==200
 assert c.post(session+'/verify',json={'action_id':'holder.base','client_frame_id':1}).status_code==409


@pytest.mark.parametrize('base,holder,first_mode,next_mode',[
 ('unsatisfied','unsatisfied','operate','operate'),
 ('satisfied','unsatisfied','check','operate'),
 ('satisfied','satisfied','check','check'),
 ('unknown','unknown','observe','observe'),
])
def test_scene_configuration_changes_plan_without_reinstalling_or_skipping(setup,base,holder,first_mode,next_mode):
 c,p,_=setup;value,fake=generate(setup,{'S1':base,'S2':holder});session,sid=approve(c,value)
 a=assess(c,session);assert a['execution']['mode']==first_mode and a['execution']['completed_state_ids']==[]
 # No position markers or calibration are needed for photo verification.
 out=verify(c,session);assert out['execution']['action_id']=='holder.slide' and out['execution']['needs_assessment']
 assert out['execution']['completed_state_ids']==['S1']
 a=assess(c,session,'holder.slide',2);assert a['execution']['mode']==next_mode
 done=verify(c,session,'holder.slide',2);assert done['execution']['complete'] and done['execution']['completed_state_ids']==['S1','S2']
 assert c.post(session+'/verify',json={'action_id':'holder.slide','client_frame_id':2}).status_code==409


def test_failed_visual_check_does_not_unlock_manual_or_next_action(setup):
 c,p,_=setup;value,fake=generate(setup);session,sid=approve(c,value);assess(c,session)
 fake.verdicts=['not_completed'];r=c.post(session+'/verify',json={'action_id':'holder.base','client_frame_id':1}).json()
 assert r['status']=='not_completed' and not r['manual_pending'] and r['execution']['mode']=='operate'
 assert r['execution']['completed_state_ids']==[]
 assert c.post(session+'/frames',json=frame(action='holder.slide',number=2)).status_code==409
 assert c.post(session+'/manual-conditions',json={'action_id':'holder.base','inspection_ids':['S1-C2'],'confirmed':True}).status_code==409


def test_scene_is_provisional_and_artifact_changes_reject_approval(setup):
 c,p,_=setup;value,fake=generate(setup)
 path=p.root/'jobs'/value['id']/'scene-state.json';path.write_text(path.read_text()+' ')
 r=c.post('/api/guidance/pipeline/jobs/'+value['id']+'/approve',json={'confirmed':True,'procedure_sha256':value['candidate']['procedure_sha256']})
 assert r.status_code==409


def test_per_node_binding_accepts_single_action_without_inventing_base_state(setup,tmp_path):
 from manual2ar.knowledge.compilation.binding import bind
 c,p,_=setup;value,fake=generate(setup);source=p.candidates[value['id']].compile/'task/procedure.json';proc=json.loads(source.read_text())
 proc['states']=proc['states'][:1];folder=tmp_path/'fragment';(folder/'task').mkdir(parents=True);(folder/'task/procedure.json').write_text(json.dumps(proc))
 class One:
  def chat_structured(self,**kw):return {'states':[dict(state_id='S1',capability='holder.slide',component_ids=['external_spool_holder'],rationale='单个滑入节点')]}
 result=bind(folder,One(),dynamic=True)
 assert result['spatial_ready'] and len(result['states'])==1 and result['states'][0]['capability']=='holder.slide'


def test_single_remaining_action_loads_and_checks_external_prerequisite(setup):
 c,p,_=setup
 class Fragment(EnhancedVLM):
  def chat_structured(self,**kw):
   title=kw['schema']['title']
   if title=='DirectDraft':
    result=super().chat_structured(**kw);state=result['states'][1];state['preconditions']=[{**state['instruction'],'text':'底座已安装于立柱。','origin':'inferred'}]
    result['states']=[state];result['observations']=[n for n in result['observations'] if n['action_id']=='slide'];return result
   if title=='Bindings':
    self.calls.append(kw);return {'states':[dict(state_id='S1',capability='holder.slide',component_ids=['external_spool_holder'],rationale='剩余滑入动作')]}
   return super().chat_structured(**kw)
 fake=Fragment();p.client=fake;command={**question(),'experiment':{'stateful_planning':True}}
 id=c.post('/api/guidance/pipeline/jobs',json=command).json()['id'];value=completed(c,id);assert value['status']=='ready',value
 session,sid=approve(c,value)
 assert c.get(session.rsplit('/sessions/',1)[0]+'/sequence').json()['enforced'] is False
 assess(c,session,'holder.slide')
 r=c.post(session+'/verify',json={'action_id':'holder.slide','client_frame_id':1}).json()
 assert r['prerequisite_only'] and r['manual_pending'] and r['execution']['completed_state_ids']==[]
 r=c.post(session+'/manual-conditions',json={'action_id':'holder.slide','inspection_ids':r['manual_pending'],'confirmed':True}).json()
 assert r['status']=='completed' and r['prerequisite_only'] and not r['execution']['complete']
 out=verify(c,session,'holder.slide');assert out['execution']['complete']


def test_claim_conflict_is_recorded_without_official_citation_or_completion(setup):
 c,p,_=setup
 class Conflict(EnhancedVLM):
  def chat_structured(self,**kw):
   result=super().chat_structured(**kw)
   if kw['schema']['title']=='TaskScene':result['user_claims']=[dict(state_id='S1',quote='我已经安装了支架底座',completed=True)]
   return result
 fake=Conflict();fake.scene_states={'S1':'unsatisfied','S2':'unsatisfied'};p.client=fake
 command={**question(),'intent':'我已经安装了支架底座，现在我要安装料盘支架','experiment':{'stateful_planning':True}}
 id=c.post('/api/guidance/pipeline/jobs',json=command).json()['id'];value=completed(c,id)
 assert value['status']=='ready',value
 step=value['candidate']['execution_plan']['steps'][0];assert step['claim_conflict'] and step['mode']=='operate'
 claims=json.loads((p.root/'jobs'/id/'scene-state.json').read_text())['user_claims']
 assert claims==[dict(state_id='S1',quote='我已经安装了支架底座',completed=True)]


def test_new_scene_assessment_invalidates_pending_manual_confirmation(setup):
 c,p,_=setup;value,fake=generate(setup);session,sid=approve(c,value);assess(c,session)
 pending=c.post(session+'/verify',json={'action_id':'holder.base','client_frame_id':1}).json();assert pending['manual_pending']
 assert c.post(session+'/assess',json={'action_id':'holder.base','client_frame_id':1}).status_code==200
 response=c.post(session+'/manual-conditions',json={'action_id':'holder.base','inspection_ids':pending['manual_pending'],'confirmed':True})
 assert response.status_code==409 and p.spatial[value['id']].execution(p.spatial[value['id']].sessions[sid])['completed_state_ids']==[]


def test_assessment_cannot_race_inflight_verification(setup):
 import threading
 from concurrent.futures import ThreadPoolExecutor
 c,p,_=setup;value,fake=generate(setup);session,sid=approve(c,value);assess(c,session)
 entered=threading.Event();release=threading.Event();original=fake.chat_structured
 def block(**kw):
  if kw['schema']['title']=='SceneCheck':entered.set();assert release.wait(5)
  return original(**kw)
 fake.chat_structured=block
 with ThreadPoolExecutor(max_workers=1) as pool:
  future=pool.submit(c.post,session+'/verify',json={'action_id':'holder.base','client_frame_id':1})
  try:
   assert entered.wait(3)
   assert c.post(session+'/assess',json={'action_id':'holder.base','client_frame_id':1}).status_code==409
  finally:release.set()
  assert future.result().status_code==200


class ManualOnly(EnhancedVLM):
 def chat_structured(self,**kw):
  result=super().chat_structured(**kw)
  if kw['schema']['title']=='DirectDraft':
   result['states'][0]['postconditions']=result['states'][0]['postconditions'][1:]
   result['observations']=[n for n in result['observations'] if n['action_id']!='base' or n['verification_channel']=='manual']
   for n in result['observations']:
    if n['action_id']=='base':n['postcondition_index']=0
  return result


def test_manual_only_step_enters_ar_without_fake_visual_evidence(setup):
 c,p,_=setup;fake=ManualOnly();p.client=fake
 command={**question(),'experiment':{'stateful_planning':True,'temporal_verification':True}}
 id=c.post('/api/guidance/pipeline/jobs',json=command).json()['id'];value=completed(c,id)
 assert value['status']=='ready',value
 assert value['candidate']['verification_contract']['states'][0]['mode']=='manual'
 assert value['candidate']['execution_plan']['steps'][0]['mode']=='check'
 session,sid=approve(c,value);assess(c,session)
 before=len([v for v in fake.calls if v['schema']['title']=='SceneCheck'])
 response=c.post(session+'/verify',json={'action_id':'holder.base','client_frame_id':1})
 assert response.status_code==200,response.text
 pending=response.json();assert pending['manual_pending'] and pending['status']=='uncertain'
 assert pending['execution']['completed_state_ids']==[]
 assert len([v for v in fake.calls if v['schema']['title']=='SceneCheck'])==before
 assert c.post(session+'/manual-conditions',json={'action_id':'holder.base','inspection_ids':[], 'confirmed':True}).status_code==409
 done=c.post(session+'/manual-conditions',json={'action_id':'holder.base','inspection_ids':pending['manual_pending'],'confirmed':True})
 assert done.status_code==200,done.text
 assert done.json()['execution']['completed_state_ids']==['S1']


@pytest.mark.parametrize('channel,code',[('sensor','unsupported_evidence_channel'),('', 'missing_conditions')])
def test_unsupported_or_empty_conditions_have_precise_diagnostics(channel,code):
 from manual2ar.knowledge.compilation.binding import verification_contract
 nodes=[dict(inspection_id='S1-C1',verification_channel=channel)] if channel else []
 contract,issues=verification_contract({'states':[dict(state_id='S1',observation_nodes=nodes)]})
 assert issues[0]['code']==code and issues[0]['state_id']=='S1'


def test_visible_condition_cannot_hide_manual_requirement():
 from manual2ar.knowledge.compilation.binding import verification_contract
 _,issues=verification_contract({'states':[dict(state_id='S2',observation_nodes=[dict(inspection_id='S2-C1',verification_channel='vision',condition='支架到位（机械锁止需人工确认）')])]})
 assert issues[0]['code']=='nonvisual_in_vision'
