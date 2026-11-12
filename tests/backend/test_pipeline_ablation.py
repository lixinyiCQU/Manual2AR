"""Opt-in stages, paired input identities, and falsifiable controls; no external inference."""
import cv2
import base64
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import time
from PIL import Image
import numpy as np
import pytest
from tests.backend.test_wiki_to_ar import setup,question,completed,GeneratedVLM
from tests.backend.guidance.test_spatial import frame
from manual2ar.modules.guidance.experiments import FEATURES,Features


class EnhancedVLM(GeneratedVLM):
 def __init__(self):super().__init__();self.reject_reviews=0;self.review_calls=0;self.verdicts=[]
 def chat_structured(self,**kw):
  title=kw['schema']['title']
  if title=='ObservationContract':
   self.calls.append(kw)
   rows=json.JSONDecoder().raw_decode(kw['prompt'].split('CONDITIONS:\n')[1])[0]
   # Controlled schema fixture only; semantic fidelity of generated specs requires a separate human evaluation.
   features=[];specs=[];rules=[]
   for i,row in enumerate(rows):
    node=row['node'];fid='feature_'+str(i);sid='spec_'+node['inspection_id'];ids=node['manual_provenance']['citation_ids']
    features.append(dict(id=fid,component_id=node['component_ids'][0],description='受控部件外观',citation_ids=ids,image_ids=[]))
    specs.append(dict(id=sid,inspection_id=node['inspection_id'],predicate='feature_presence',feature_ids=[fid],region_definition='受控画面部件区域',coordinate_frame='image_upright',limitation=''))
    rules.append(dict(spec_id=sid,expected='present',origin='observation_policy',citation_ids=ids,rationale='受控验收规则'))
   return dict(features=features,specs=specs,rules=rules)
  if title=='Findings':
   self.calls.append(kw);query=json.JSONDecoder().raw_decode(kw['prompt'].split('QUERY:')[1])[0];out=[]
   for spec in query['specs']:
    state='S1' if 'S1' in spec['inspection_id'] else 'S2';status=getattr(self,'scene_states',{}).get(state,'satisfied')
    out.append(dict(spec_id=spec['id'],observability='occluded' if status=='unknown' else 'observable',coverage='partial' if status=='unknown' else 'complete',region_bbox=dict(bbox=[0,0,1000,1000]),instances=[dict(bbox=[100,100,300,500])] if status=='satisfied' else [],feature_boxes=[],text=None,evidence='受控现场可见事实'))
   return dict(source_sha256=query['source_sha256'],findings=out)
  if title in ('ExtractedActions','DraftGraph','DraftObservations'):
   direct=super().chat_structured(**{**kw,'schema':{'title':'DirectDraft'}});self.calls[-1]=kw
   if title=='ExtractedActions':return dict(actions=[{k:s[k] for k in ('action_id','instruction','target_components')} for s in direct['states']],limitations=[])
   return {k:direct[k] for k in (('states','limitations') if title=='DraftGraph' else ('observations',))}
  if title in ('Scene','SectionSelection','DirectDraft','Bindings','SceneCheck'):
   result=super().chat_structured(**kw)
   if title=='SceneCheck' and self.verdicts:result['status']=self.verdicts.pop(0)
   return result
  if title=='TaskScene':
   result=self.chat_structured(**{**kw,'schema':{'title':'PartsObservation'}});self.calls[-1]=kw
   context=json.JSONDecoder().raw_decode(kw['prompt'].split('完整流程：')[1])[0]
   result.update(evidence_image_id='current_scene',source_sha256=hashlib.sha256(base64.b64decode(kw['images_base64'][0])).hexdigest(),user_claims=[],conditions=[])
   for state in context:
    for node in state['conditions']:
     status=getattr(self,'scene_states',{}).get(state['state_id'],'satisfied' if state['state_id']=='S1' else 'unsatisfied') if node['channel']=='vision' else 'unknown'
     result['conditions'].append(dict(inspection_id=node['inspection_id'],status=status,confidence=.95,evidence='受控现场条件',bbox_0_1000=[100,100,400,600] if status!='unknown' else []))
   return result
  self.calls.append(kw)
  if title=='Descriptions':
   rows=json.loads(kw['prompt'].split('\n')[-1]);return {'items':[dict(image_id=r['image_id'],description='官方示范的灰色固定底座和白色支架。') for r in rows]}
  if title in ('SceneAlignment','PartsObservation'):
   def part(id,box):return dict(component_id=id,status='found',confidence=.95,evidence='受控现场部件',bbox_0_1000=box,foreground_point_0_1000=[(box[0]+box[2])//2,(box[1]+box[3])//2],axis_start_0_1000=[],axis_end_0_1000=[])
   d=dict(parts=[part('spool_holder_base',[600,300,650,450]),part('external_spool_holder',[100,600,400,800])],next_action='拍清当前连接')
   if title=='SceneAlignment':d.update(evidence_image_id='current_scene',source_sha256=hashlib.sha256(base64.b64decode(kw['images_base64'][0])).hexdigest(),current_capability='holder.base',state='uncertain',relations=['支架与底座分离'],unknowns=['机械紧固未知'])
   return d
  if title=='SemanticReview':
   self.review_calls+=1
   if self.review_calls<=self.reject_reviews:
    source=json.JSONDecoder().raw_decode(kw['prompt'].split('\nSOURCE:')[1])[0];id=next(iter(source['evidence']))
    return dict(accepted=False,issues=['需要明确可见连接条件'],required_fixes=[dict(text='仅核验可见连接',origin='observation_policy',citation_ids=[id],rationale='受控修正')])
   return dict(accepted=True,issues=[],required_fixes=[])
  if title=='ImperativeInstruction':
   base='"state_id":"S1"' in kw['prompt']
   return dict(adverbial='在底座上' if base else '对准连接处',actor_mode='tool' if base else 'moving_object',actor='内六角扳手' if base else '料盘支架',action='固定' if base else '滑入',object='底座螺丝' if base else '底座',acceptance='保持贴合',position_m=None,sentence='')
  if title=='RegionChoices':return dict(parts=[dict(component_id=id,region_id=i,status='found',confidence=.95,evidence='对应编号区域',foreground_point_0_1000=point) for id,i,point in [('spool_holder_base',1,[625,375]),('external_spool_holder',2,[250,700])]],next_action='保持部件入镜')
  if title=='MaskReview':
   active=json.JSONDecoder().raw_decode(kw['prompt'].split('只返回下列非空掩膜的决定：')[1])[0]
   return dict(decisions=[dict(component_id=id,decision='keep',reason='受控检查通过',bbox_0_1000=[],foreground_point_0_1000=[]) for id in active])
  raise AssertionError('Unexpected enhanced schema '+title)


def generate(setup,features):
 c,p,f=setup;fake=EnhancedVLM();p.client=fake
 response=c.post('/api/guidance/pipeline/jobs',json={**question(),'experiment':features})
 assert response.status_code==202,response.text
 value=completed(c,response.json()['id']);return value,fake


def approve(c,value):
 id=value['id'];r=c.post('/api/guidance/pipeline/jobs/'+id+'/approve',json={'confirmed':True,'procedure_sha256':value['candidate']['procedure_sha256']})
 assert r.status_code==200,r.text
 api=f'/api/guidance/pipeline/candidates/{id}/spatial'
 sid=c.post(api+'/sessions',json={'camera_id':'fixture','visual_client_revision':'machine-workframe-v1'}).json()['session_id']
 return api+'/sessions/'+sid,sid


def test_all_off_matches_frozen_four_call_baseline(setup):
 c,p,_=setup;value,fake=generate(setup,{})
 assert value['status']=='ready' and value['method']=='baseline-v1.2'
 assert [call['schema']['title'] for call in fake.calls]==['Scene','SectionSelection','DirectDraft','Bindings']
 assert len(fake.calls[0]['images_base64'])==1 and fake.calls[1]['images_base64']==[]
 assert value['cost']['logical_calls']==4 and value['cost']['usage_tokens'] is None
 assert p.candidates[value['id']].compile.name=='compile'
 assert not list((p.root/'jobs'/value['id']).glob('display-*.json'))


@pytest.mark.parametrize('feature',list(FEATURES)+['text_only'])
def test_each_switch_is_independently_runnable_and_persisted(setup,feature):
 c,p,_=setup;value,fake=generate(setup,{feature:True})
 assert value['status']=='ready',value
 record=json.loads((p.root/'jobs'/value['id']/'experiment.json').read_text())
 assert record['features'][feature] and sum(record['features'].values())==1
 assert not record['manual_ground_truth_used'] and record['implementation_sha256']
 titles=[call['schema']['title'] for call in fake.calls]
 expected={'image_enrichment':'Descriptions','scene_alignment':'SceneAlignment','semantic_review':'SemanticReview','staged_compilation':'ExtractedActions','contextual_display':'ImperativeInstruction'}
 if feature in expected:assert expected[feature] in titles
 if feature=='visual_reranking':assert len(next(call for call in fake.calls if call['schema']['title']=='SectionSelection')['images_base64'])>=2
 if feature=='text_only':assert fake.calls[0]['images_base64']==[]
 if feature=='hierarchical_evidence':assert json.loads((p.root/'jobs'/value['id']/'retrieval.json').read_text())['method']=='hierarchical-bm25-v1'
 session,sid=approve(c,value);service=p.spatial[value['id']]
 assert bool(service.displays.profiles)==(feature=='contextual_display')
 assert bool(service.part_tracking.review)==(feature=='mask_refinement')


def test_full_path_runs_all_planning_stages_and_reuses_enrichment(setup):
 c,p,_=setup;features=dict.fromkeys(FEATURES,True);value,fake=generate(setup,features)
 assert value['status']=='ready',value
 folder=p.root/'jobs'/value['id'];assert (folder/'scene-state.json').exists() and (folder/'semantic-review.json').exists()
 assert len([p for p in folder.glob('display-*.json') if p.name in ('display-S1.json','display-S2.json')])==2
 first=sum(call['schema']['title']=='Descriptions' for call in fake.calls)
 reply=c.post('/api/guidance/pipeline/jobs/'+value['id']+'/repeat',json=features);again=completed(c,reply.json()['id'])
 assert again['status']=='ready',again
 assert sum(call['schema']['title']=='Descriptions' for call in fake.calls)==first
 assert again['source_sha256']==value['source_sha256'] and again['id']!=value['id']
 record=json.loads((p.root/'jobs'/again['id']/'experiment.json').read_text())
 assert record['comparison_group']==json.loads((folder/'experiment.json').read_text())['comparison_group']


def test_semantic_review_retains_rejected_draft_and_binds_only_revised_task(setup):
 c,p,_=setup;fake=EnhancedVLM();fake.reject_reviews=1;p.client=fake
 identity=c.post('/api/guidance/pipeline/jobs',json={**question(),'experiment':{'semantic_review':True}}).json()['id'];value=completed(c,identity)
 assert value['status']=='ready',value
 assert p.candidates[identity].compile.name=='compile-revised'
 assert (p.root/'jobs'/identity/'compile/task/procedure.json').exists()
 assert (p.root/'jobs'/identity/'compile-revised/binding/result.json').exists()
 assert not (p.root/'jobs'/identity/'compile/binding').exists()


def test_review_still_rejected_cannot_enter_ar(setup):
 c,p,_=setup;fake=EnhancedVLM();fake.reject_reviews=10;p.client=fake
 identity=c.post('/api/guidance/pipeline/jobs',json={**question(),'experiment':{'semantic_review':True}}).json()['id'];value=completed(c,identity)
 assert value['status']=='failed' and value['failed_stage']=='reviewing' and 'candidate' not in value
 assert c.get('/api/guidance/pipeline/candidates/'+identity+'/spatial/config').status_code==404


def test_invalid_switches_and_text_only_conflicts_are_rejected_before_model(setup):
 c,p,f=setup
 for features in ({'unknown':True},{'text_only':True,'scene_alignment':True},{'text_only':True,'visual_reranking':True}):
  assert c.post('/api/guidance/pipeline/jobs',json={**question(),'experiment':features}).status_code==422
 assert f.calls==[]


def test_operator_reviews_not_ready_status_determine_success_rate(setup):
 c,p,_=setup;value,fake=generate(setup,{})
 assert c.get('/api/guidance/pipeline/experiments/results').json()['human_metrics']['task_planning']['success_rate'] is None
 api='/api/guidance/pipeline/jobs/'+value['id']+'/review'
 assert c.post(api,json={'task_planning':'pass','review_seconds':12}).status_code==200
 assert c.post(api,json={'task_planning':'fail'}).status_code==200
 result=c.get('/api/guidance/pipeline/experiments/results').json()
 assert result['human_metrics']['task_planning']==dict(rated=1,passed=0,success_rate=0)
 assert len(list((p.root/'jobs'/value['id']/'human-reviews').glob('*.json')))==2
 assert c.get('/api/guidance/pipeline/jobs/'+value['id']).json()['status']=='ready'


@pytest.mark.parametrize('statuses,expected',[(['completed']*3,'uncertain'),(['completed','not_completed','completed'],'uncertain'),(['not_completed']*3,'not_completed')])
def test_temporal_verification_checks_distinct_frames_and_keeps_manual_gate(setup,statuses,expected):
 c,p,_=setup;value,fake=generate(setup,{'temporal_verification':True});session,sid=approve(c,value);sp=p.spatial[value['id']]
 for i in range(3):
  stream=io.BytesIO();Image.new('RGB',(320,240),(i*80,20,30)).save(stream,'JPEG');c.post(session+'/frames',json=frame(raw=stream.getvalue(),number=i+1,action='holder.base'))
 with sp.session(sid) as s:
  s.frames[1]['at']-=.8;s.frames[2]['at']-=.4
 fake.verdicts=list(statuses);result=c.post(session+'/verify',json={'action_id':'holder.base','client_frame_id':3})
 assert result.status_code==200,result.text
 body=result.json();assert body['status']==expected and not body['u7_sequence']['base_approved']
 checks=[call for call in fake.calls if call['schema']['title']=='SceneCheck'];assert len(checks)==3
 assert all(len(call['images_base64'])==1 for call in checks)
 assert len({hashlib.sha256(base64.b64decode(call['images_base64'][0])).hexdigest() for call in checks})==3
 if statuses==['completed']*3:assert body['manual_pending']==['S1-C2']


def test_temporal_verification_does_not_count_duplicate_still_as_three_samples(setup):
 c,p,_=setup;value,fake=generate(setup,{'temporal_verification':True});session,sid=approve(c,value)
 for i in range(3):c.post(session+'/frames',json=frame(number=i+1,action='holder.base'))
 assert c.post(session+'/verify',json={'action_id':'holder.base','client_frame_id':3}).status_code==409
 assert not [call for call in fake.calls if call['schema']['title']=='SceneCheck']


def test_numbered_regions_and_working_mask_review_execute_real_visual_calls(setup,tmp_path):
 from manual2ar.modules.guidance.enhancements import numbered_alignment,review_masks
 from manual2ar.modules.guidance.spatial.u7_vision import PartsObservation
 c,p,_=setup;value,fake=generate(setup,{})
 raw=base64.b64decode(frame()['image_base64']);kwargs=dict(prompt='',schema=PartsObservation.model_json_schema(),images_base64=[base64.b64encode(raw).decode()])
 initial=PartsObservation.model_validate(fake.chat_structured(**kwargs));folder=tmp_path/'regions';folder.mkdir()
 answer=numbered_alignment(fake,raw,raw,raw,initial,folder)
 assert len(answer.parts)==2 and (folder/'numbered-regions.jpg').exists()
 masks={part.component_id:np.ones(cv2.imdecode(np.frombuffer(raw,np.uint8),cv2.IMREAD_COLOR).shape[:2],bool) for part in answer.parts}
 checked=review_masks(fake,raw,answer.parts,masks,folder)
 assert len(checked)==2 and (folder/'working-mask.jpg').exists()
 assert [call['schema']['title'] for call in fake.calls][-2:]==['RegionChoices','MaskReview']


def test_oracle_control_is_separate_and_never_counted_as_automatic_success(setup):
 c,p,f=setup;result=c.post('/api/guidance/pipeline/experiments/oracle',json=question())
 assert result.status_code==201,result.text
 assert not result.json()['counts_as_automatic_planning'] and f.calls==[]
 rows=c.get('/api/guidance/pipeline/experiments/results').json()
 assert len(rows['oracle_controls'])==1 and rows['rows']==[]


def test_cli_matrix_contains_baseline_full_single_and_leave_one_out():
 from tools.evaluation.pipeline_ablation import methods
 matrix=methods(True)
 assert len(matrix)==3+2*len(FEATURES)
 assert not any(matrix['baseline'].values())
 for name in FEATURES:
  assert sum(matrix['only-'+name].values())==1 and sum(matrix['without-'+name].values())==len(FEATURES)-1


def test_geometry_control_is_explicit_same_photo_and_never_overwrites(setup):
 from manual2ar.modules.guidance.pipeline import Question
 c,p,_=setup;source,_=generate(setup,{})
 api,sid=approve(c,source);spatial=p.spatial[source['id']]
 spatial.store_profile(spatial.profile('rigs','a1-mini'),{'targets':[]})
 command=question();command['geometry_reference']=source['id']
 assert c.post('/api/guidance/pipeline/jobs',json=command).status_code==409
 assert c.delete(api).status_code==204
 command['intent']='另一个目标';assert c.post('/api/guidance/pipeline/jobs',json=command).status_code==409
 command['intent']=source['intent'];p.client=EnhancedVLM()
 created=c.post('/api/guidance/pipeline/jobs',json=command);assert created.status_code==202,created.text
 target=completed(c,created.json()['id']);assert target['status']=='ready',target
 assert target['method'].endswith('+oracle_geometry')
 assert c.post('/api/guidance/pipeline/jobs/'+target['id']+'/approve',json={'confirmed':True,'procedure_sha256':target['candidate']['procedure_sha256']}).status_code==200
 marker=p.spatial[target['id']].root/'geometry-reference.json'
 assert json.loads(marker.read_text())['counts_as_automatic_geometry'] is False
 assert p.spatial[target['id']].profile('rigs','a1-mini').read_bytes()==spatial.profile('rigs','a1-mini').read_bytes()
 assert c.get('/api/guidance/pipeline/experiments/results').json()['methods'][target['method']]['human_metrics']['task_planning']['rated']==0


@pytest.mark.parametrize('decision',['replace','reject'])
def test_mask_review_correction_runs_once_and_closes_old_provider(setup,decision):
 from tests.backend.guidance.test_u7_parts import GPU,wait
 c,p,_=setup;value,fake=generate(setup,{'mask_refinement':True});api,sid=approve(c,value);service=p.spatial[value['id']]
 tracker=service.part_tracking;tracker.config={**tracker.config,'gpu_connection_file':str(p.root/'test-gpu.json')};Path(tracker.config['gpu_connection_file']).write_text('{}');tracker.client_factory=GPU
 calls=[];before=len(GPU.instances)
 def revise(raw,parts,masks,folder):
  calls.append(1);out=[p.model_copy(deep=True) for p in parts]
  for part in out:
   if part.status!='found':continue
   if decision=='reject':part.status='uncertain';part.bbox_0_1000=[];part.foreground_point_0_1000=[]
   else:part.bbox_0_1000=[600,300,700,450]
  return out
 tracker.review=revise
 assert c.post(api+'/frames',json=frame(action='holder.base')).status_code==200
 created=c.post(api+'/locate',json={'action_id':'holder.base','client_frame_id':1});assert created.status_code==200,created.text
 job=created.json()['job_id'];out=wait(c,api+'/parts/'+job,{'tracking','not_found','failed','segmentation_unavailable'})
 assert calls==[1] and out['phase']==('tracking' if decision=='replace' else 'not_found'),out
 assert len(GPU.instances)-before==(2 if decision=='replace' else 1)
 deadline=time.monotonic()+2
 while not GPU.instances[before].closed and time.monotonic()<deadline:time.sleep(.01)
 assert GPU.instances[before].closed


def test_cost_keeps_interrupted_calls_separate_from_provider_failures(tmp_path):
 from manual2ar.modules.guidance.experiments import call_summary
 (tmp_path/'calls'/'interrupted').mkdir(parents=True)
 result=call_summary(tmp_path)
 assert result['logical_calls']==1 and result['incomplete_calls']==1 and result['failed_calls']==0
 assert result['usage_tokens'] is None
