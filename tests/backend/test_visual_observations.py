"""Queries never carry expected answers; software derives acceptance from typed findings."""
from copy import deepcopy
import json
import pytest
from manual2ar.modules.guidance.observations import Spec,Rule,Finding,Findings,evaluate,validate_contract,ObservationContract
from tests.backend.test_wiki_to_ar import setup,question,completed
from tests.backend.test_pipeline_ablation import EnhancedVLM,approve
from tests.backend.test_stateful_pipeline import assess


def spec(predicate='instance_enumeration'):
 return Spec(id='q1',inspection_id='S1-C1',predicate=predicate,feature_ids=['screw'],region_definition='已辨认底座的两个安装区域')
def rule(expected='2'):
 return Rule(spec_id='q1',expected=expected,origin='explicit',citation_ids=['citation'],rationale='受控来源')
def finding(**changes):
 value=dict(spec_id='q1',observability='observable',coverage='complete',region_bbox=dict(bbox=[0,0,1000,1000]),instances=[dict(bbox=[100,100,200,200]),dict(bbox=[100,300,200,400])],evidence='可见两个分离实例')
 value.update(changes);return Finding(**value)


@pytest.mark.parametrize('observable,coverage,count,expected_status',[
 ('observable','complete',2,'completed'),('observable','complete',1,'not_completed'),
 ('occluded','partial',1,'uncertain'),('unresolved_identity','complete',2,'uncertain'),('observable','unknown',0,'uncertain')])
def test_count_is_computed_and_requires_visibility(observable,coverage,count,expected_status):
 f=finding(observability=observable,coverage=coverage);f.instances=f.instances[:count]
 assert evaluate(spec(),rule(),f)==expected_status


def test_image_relation_is_computed_without_model_verdict():
 s=spec('relative_position_2d');s.feature_ids=['a','b']
 f=finding(instances=[],feature_boxes=[dict(bbox=[100,100,200,200]),dict(bbox=[400,100,500,200])])
 assert evaluate(s,rule('left'),f)=='completed'
 assert evaluate(s,rule('right'),f)=='not_completed'
 with pytest.raises(ValueError):Findings.model_validate(dict(source_sha256='a'*64,findings=[{**f.model_dump(),'status':'completed'}]))


def generate(setup,fake=None):
 c,p,_=setup;fake=fake or EnhancedVLM();p.client=fake
 value=c.post('/api/guidance/pipeline/jobs',json={**question(),'experiment':{'stateful_planning':True,'visual_observation_contract':True}}).json()
 return completed(c,value['id']),fake


def test_structured_observations_drive_scene_and_verification_without_expected_leak(setup):
 c,p,_=setup;job,fake=generate(setup);assert job['status']=='ready',job
 assert job['candidate']['observation_contract'] and not any(q['schema']['title']=='TaskScene' for q in fake.calls)
 candidate=p.candidates[job['id']];api,sid=approve(c,job);assess(c,api)
 response=c.post(api+'/verify',json={'action_id':'holder.base','client_frame_id':1});assert response.status_code==200,response.text
 out=response.json();assert out['manual_pending'] and out['execution']['completed_state_ids']==[]
 for call in fake.calls:
  if call['schema']['title']=='Findings':
   query=json.JSONDecoder().raw_decode(call['prompt'].split('QUERY:')[1])[0]
   assert 'rules' not in query and 'expected' not in call['prompt']
   assert '底座贴合立柱' not in call['prompt']
 assert not any(q['schema']['title']=='SceneCheck' for q in fake.calls)
 path=candidate.compile/'observations/acceptance_rules.json';path.write_text(path.read_text()+' ')
 assert c.get('/api/guidance/pipeline/jobs/'+job['id']).status_code==409


def test_unresolved_orientation_never_falls_back_to_free_text(setup):
 class Missing(EnhancedVLM):
  def chat_structured(self,**kw):
   value=super().chat_structured(**kw)
   if kw['schema']['title']=='ObservationContract':
    value['specs'][0].update(predicate='unsupported',feature_ids=[],limitation='缺少已定义的非对称朝向参照特征')
   return value
 c,p,_=setup;job,fake=generate(setup,Missing());assert job['status']=='unsupported',job
 assert '非对称朝向参照特征' in job['message']
 assert job['candidate']['binding_issues'][0]['code']=='undefined_visual_standard'
 r=c.post('/api/guidance/pipeline/jobs/'+job['id']+'/approve',json=dict(confirmed=True,procedure_sha256=job['procedure_sha256']))
 assert r.status_code==409
 assert not any(q['schema']['title'] in ('Findings','SceneCheck','TaskScene') for q in fake.calls)


@pytest.mark.parametrize('mutation',['wrong_photo','duplicate_instances','extra_verdict'])
def test_bad_findings_cannot_unlock_step(setup,mutation):
 c,p,_=setup;job,fake=generate(setup);api,sid=approve(c,job);assess(c,api)
 original=fake.chat_structured
 def invalid(**kw):
  value=original(**kw)
  if kw['schema']['title']=='Findings':
   if mutation=='wrong_photo':value['source_sha256']='f'*64
   elif mutation=='extra_verdict':value['findings'][0]['status']='completed'
   else:value['findings'][0]['instances']*=2
  return value
 fake.chat_structured=invalid
 r=c.post(api+'/verify',json={'action_id':'holder.base','client_frame_id':1});assert r.status_code==502,r.text
 assert p.spatial[job['id']].execution(p.spatial[job['id']].sessions[sid])['completed_state_ids']==[]


def test_absence_without_region_evidence_is_unknown():
 assert evaluate(spec('feature_presence'),rule('absent'),finding(instances=[],region_bbox=None))=='uncertain'


def test_schema_output_has_one_bounded_repair_and_retains_both_outputs(tmp_path):
 from manual2ar.modules.guidance.enhancements import ask
 from manual2ar.modules.guidance.pipeline import SectionSelection
 class Provider:
  calls=0
  def chat_structured(self,**kw):
   self.calls+=1
   return kw['schema'] if self.calls==1 else dict(section_id=0,sufficient=True,reason='返回业务实例')
 client=Provider();answer=ask(client,tmp_path,'selection',SectionSelection,'选择资料',[],max_repairs=1)
 assert answer.section_id==0 and client.calls==2
 assert (tmp_path/'selection.raw.json').exists() and (tmp_path/'selection-repair-1.raw.json').exists()


def test_semantic_coverage_rejection_prevents_weakened_contract(setup):
 class Reject(EnhancedVLM):
  def chat_structured(self,**kw):
   if kw['schema']['title']=='SemanticReview' and 'OBSERVATION_CONTRACT:' in kw['prompt']:
    self.calls.append(kw);return dict(accepted=False,issues=['存在不能证明连接'],required_fixes=[])
   return super().chat_structured(**kw)
 c,p,_=setup;job,_=generate(setup,Reject())
 assert job['status']=='unsupported' and '存在不能证明连接' in job['message']
 assert not job['candidate']['spatial_ready']


def test_invalid_feature_identity_is_reported_without_entering_ar(setup):
 class Invalid(EnhancedVLM):
  def chat_structured(self,**kw):
   value=super().chat_structured(**kw)
   if kw['schema']['title']=='ObservationContract':value['features'][0]['component_id']='source:另一个部件'
   return value
 c,p,_=setup;job,fake=generate(setup,Invalid())
 assert job['status']=='unsupported' and job['candidate']['binding_issues'][0]['code']=='invalid_observation_spec'
 folder=p.candidates[job['id']].compile/'observations'
 assert (folder/'compile-0.raw.json').exists() and (folder/'compile-1.raw.json').exists()
 assert job['candidate']['observation_contract'] is None
