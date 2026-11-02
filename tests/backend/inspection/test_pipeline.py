"""Task decisions, frame identity and failure isolation; no remote calls."""
import base64,copy,hashlib,io,json
from types import SimpleNamespace
import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from manual2ar.modules.inspection.server import create_app
from manual2ar.modules.inspection.tracker import InspectionTracker,PlateCpuTracker
from manual2ar_contracts.gpu import decode_labels
from manual2ar_contracts.perception import GuidanceTarget

from manual2ar.paths import ROOT
from manual2ar.application.config import for_module

def config():
    c=for_module(json.loads((ROOT/'configs/app.example.json').read_text()),'inspection')
    c['vlm']['api_key']='test-private-key'
    return c

def observation(anomaly=True):
    plate=dict(found=True,confidence=.97,bbox_0_1000=[50,50,950,950],target_point_0_1000=[200,200],evidence='完整打印板可见',polygon_0_1000=[[50,50],[950,50],[950,950],[50,950]])
    item=dict(found=True,confidence=.96,bbox_0_1000=[350,350,600,600],target_point_0_1000=[450,450],evidence='黑色物体放在板面',kind='foreign_object',description='黑色工具',on_plate='yes')
    return dict(plate=plate,coverage='full',surface_assessment='anomaly' if anomaly else 'clear',confidence=.96,anomalies=[item] if anomaly else [],limitations=[],next_action='取下工具后重新检查' if anomaly else '未见可见残料')

def jpeg():
    rng=np.random.default_rng(13)
    a=np.full((240,320,3),25,np.uint8)
    a[12:228,16:304]=rng.integers(145,210,(216,288,3),dtype=np.uint8)
    a[84:144,112:192]=rng.integers(10,55,(60,80,3),dtype=np.uint8)
    buf=io.BytesIO();Image.fromarray(a).save(buf,'JPEG',quality=95)
    return buf.getvalue()

def frame(i=1,check=None):
    body=jpeg()
    return dict(image_base64=base64.b64encode(body).decode(),source_sha256=hashlib.sha256(body).hexdigest(),client_frame_id=i,check_id=check)

class FakeVLM:
    def __init__(self,value=None):self.value=value or observation();self.calls=[];self.fail=False
    def chat_structured(self,**kwargs):
        self.calls.append(kwargs)
        if self.fail:raise RuntimeError('test-private-key')
        return copy.deepcopy(self.value)

class FakeTracker:
    def __init__(self,fail=(),lost=False):
        self.engine=self;self.local=self;self.shared_masks={};self.sessions={};self.fail=set(fail);self.lost=lost;self.closed=[];self.last_batch_metrics={}
    def prepare(self,*args):pass
    def start(self,image,identity,box,target):
        key=identity.removeprefix('intro_');self.sessions[key]=box
        mask=np.zeros((240,320),bool);a,b,c,d=box;mask[b*240//1000:d*240//1000,a*320//1000:c*320//1000]=True;self.shared_masks[key]=mask
        return key,self.result(key)
    def result(self,key):
        accepted=key not in self.fail and not self.lost
        return SimpleNamespace(status='tracking' if accepted else 'lost',mask_quality_passed=accepted,quality=.95 if accepted else 0,mask_quality_reasons=[] if accepted else ['test_mask_rejected'],mask_area_ratio=float(self.shared_masks[key].mean()),prompt_containment=1,overlay_png_base64='',requires_redetection=not accepted,retained_for_recovery=False,tracking_state='tracking' if accepted else 'lost',bbox_0_1000=self.sessions[key])
    def update_many(self,sessions,image):return {s:self.result(s) for s in sessions}
    def close(self,s):self.closed.append(s)
    def shutdown(self):self.closed.extend(self.sessions)

@pytest.fixture
def env(tmp_path):
    vlm=FakeVLM();trackers=[]
    def factory(provider):
        t=FakeTracker();trackers.append(t);return t
    app=create_app(config(),vlm,factory,tmp_path/'runs')
    with TestClient(app) as client:
        identity=client.post('/api/inspection/runs',json={'source':'camera','provider':'opencv'}).json()['run_id']
        yield client,'/api/inspection/runs/'+identity,vlm,trackers,app.state.inspection

def inspect(env):
    client,url,*_=env;r=client.post(url+'/inspect',json=frame());assert r.status_code==200,r.text;return r.json()

def test_current_frame_only_non_orange_anomaly_and_overlap_labels(env):
    data=inspect(env);assert data['decision']['status']=='anomaly_detected'
    call=env[2].calls[0];assert len(call['images_base64'])==1
    assert base64.b64decode(call['images_base64'][0])==jpeg()
    masks=decode_labels(data['label_map'],320,240)
    assert masks['foreign_object_1'][110,150] and not masks['build_plate'][110,150]
    assert data['source_sha256']==frame()['source_sha256']

def test_segmentation_failure_does_not_remove_semantic_warning(env):
    env[4].tracker_factory=lambda provider:FakeTracker(fail=['foreign_object_1'])
    data=inspect(env)
    assert data['decision']['status']=='anomaly_detected'
    item=data['objects'][1];assert not item['tracking_ready'] and item['bbox_0_1000']
    assert data['decision']['semantic_anomaly_ids']==['foreign_object_1']

@pytest.mark.parametrize('change',[{'coverage':'partial'},{'surface_assessment':'uncertain'},{'confidence':.4}])
def test_clear_requires_sufficient_evidence(env,change):
    env[2].value=observation(False);env[2].value.update(change)
    assert inspect(env)['decision']['status']=='insufficient_evidence'

def test_partial_clear_has_explicit_visible_scope_without_full_plate_release(env):
    env[2].value=observation(False);env[2].value['coverage']='partial'
    data=inspect(env)
    assert data['decision']['status']=='insufficient_evidence'
    assert data['public_result']['status']=='visible_surface_clear'
    assert data['public_result']['foreign_object_state']=='visible_pass'
    assert data['public_result']['recheck_reason']=='incomplete_view'
    assert '可见板面未见明显异常' in env[0].get(env[1]+'/report').text

def test_partial_uncertain_is_not_promoted_to_clear(env):
    env[2].value=observation(False);env[2].value.update(coverage='partial',surface_assessment='uncertain')
    data=inspect(env)
    assert data['public_result']['status']=='insufficient_evidence'
    assert data['public_result']['foreign_object_state']=='not_observed'
    assert data['public_result']['recheck_reason']=='incomplete_view'

def test_no_visible_anomaly_is_snapshot_only_and_requires_plate_mask(env):
    env[2].value=observation(False);data=inspect(env)
    assert data['decision']['status']=='no_visible_anomaly'
    assert '不表示可开始打印' in data['decision']['scope']

def test_clear_without_plate_mask_stays_unknown(env):
    env[2].value=observation(False);env[4].tracker_factory=lambda _:FakeTracker(fail=['build_plate'])
    assert inspect(env)['decision']['status']=='insufficient_evidence'

def test_plate_recognition_not_erased_when_cloud_initialization_fails(env):
    class Unavailable(FakeTracker):
        def prepare(self,*args):raise ConnectionError('controlled segmentation outage')
    env[4].tracker_factory=lambda _:Unavailable()
    result=inspect(env)
    assert result['public_result']['plate_state']=='pass'
    assert result['public_result']['visual_state']=='unavailable'
    assert result['decision']['status']=='anomaly_detected' and result['active_tracks']==0
    assert all(o['segmentation_status']=='service_error' for o in result['objects'])

def test_recognized_plate_without_safe_foreground_point_preserves_semantics(env):
    env[2].value['plate']['target_point_0_1000']=None
    result=inspect(env)
    assert result['public_result']['plate_state']=='pass'
    assert result['objects'][0]['reasons']==['vlm_point_unavailable']
    assert result['decision']['status']=='anomaly_detected'
    assert result['objects'][1]['tracking_ready']

def test_plate_positive_point_over_object_is_repaired_once(env):
    original=env[2].chat_structured
    def reply(**kwargs):
        value=original(**kwargs)
        if len(env[2].calls)==1:value['plate']['target_point_0_1000']=[450,450]
        return value
    env[2].chat_structured=reply
    result=inspect(env)
    assert len(env[2].calls)==2
    assert '裸露' in env[2].calls[1]['prompt']
    assert result['objects'][0]['tracking_ready']
    assert result['decision']['status']=='anomaly_detected'

def test_failed_point_repair_keeps_anomaly_but_does_not_segment_wrong_plate(env):
    env[2].value['plate']['target_point_0_1000']=[450,450]
    result=inspect(env)
    assert len(env[2].calls)==2
    assert result['public_result']['plate_state']=='pass'
    assert result['objects'][0]['reasons']==['plate_point_overlaps_anomaly_box']
    assert result['objects'][1]['tracking_ready']
    assert result['decision']['status']=='anomaly_detected'

def test_failed_point_repair_request_preserves_valid_first_observation(env):
    original=env[2].chat_structured
    def reply(**kwargs):
        if env[2].calls:raise TimeoutError('controlled repair timeout')
        value=original(**kwargs);value['plate']['target_point_0_1000']=[450,450];return value
    env[2].chat_structured=reply
    result=inspect(env)
    assert result['decision']['status']=='anomaly_detected'
    assert result['public_result']['plate_state']=='pass'
    assert result['objects'][0]['segmentation_status']=='prompt_ambiguous'

def test_outside_objects_ignored_but_uncertain_surface_not_cleared(env):
    env[2].value['anomalies'][0]['on_plate']='no'
    assert inspect(env)['decision']['status']=='insufficient_evidence'

def test_tracking_loss_never_clears_previous_anomaly(env):
    data=inspect(env);env[3][-1].lost=True
    r=env[0].post(env[1]+'/frames',json=frame(2,data['check_id']));assert r.status_code==200
    assert r.json()['decision']['status']=='anomaly_detected'
    assert r.json()['tracking_state']=='needs_reinspection' and not r.json()['label_map']

def test_temporary_loss_retains_session_and_recovers_while_other_target_tracks(env):
    data=inspect(env);tracker=env[3][-1];original=tracker.result
    def recovering(key):
        value=original(key)
        if key=='foreign_object_1':
            value.status='lost';value.mask_quality_passed=False;value.requires_redetection=True;value.tracking_state='recovering';value.retained_for_recovery=True
        return value
    tracker.result=recovering
    partial=env[0].post(env[1]+'/frames',json=frame(2,data['check_id'])).json()
    assert partial['active_tracks']==2 and partial['tracking_state']=='partial'
    assert partial['public_result']['plate_state']=='pass'
    assert 'foreign_object_1' not in decode_labels(partial['label_map'],320,240)
    tracker.result=original
    recovered=env[0].post(env[1]+'/frames',json=frame(3,data['check_id'])).json()
    assert recovered['tracking_state']=='tracking' and recovered['active_tracks']==2
    assert recovered['decision']['status']=='anomaly_detected'
    assert decode_labels(recovered['label_map'],320,240)['foreign_object_1'].any()

def test_new_untracked_object_gets_candidate_label_after_old_object_lost(env):
    data=inspect(env);tracker=env[3][-1]
    tracker.fail.add('foreign_object_1');tracker.shared_masks['build_plate'][60:90,210:240]=False
    first=env[0].post(env[1]+'/frames',json=frame(2,data['check_id'])).json()
    assert first['scene_candidates']==[]
    second=env[0].post(env[1]+'/frames',json=frame(3,data['check_id'])).json()
    assert len(second['scene_candidates'])==1
    assert second['public_result']['unclassified_count']==1
    assert second['public_result']['recheck_reason']=='new_object'
    assert second['decision']['status']=='anomaly_detected'
    assert second['objects'][1]['bbox_0_1000'] is None

def test_new_candidate_overrides_stale_clean_ui_without_fabricating_vlm_detection(env):
    env[2].value=observation(False);data=inspect(env);tracker=env[3][-1]
    tracker.shared_masks['build_plate'][60:90,210:240]=False
    env[0].post(env[1]+'/frames',json=frame(2,data['check_id']))
    result=env[0].post(env[1]+'/frames',json=frame(3,data['check_id'])).json()
    assert result['decision']['status']=='no_visible_anomaly'
    assert result['public_result']['status']=='scene_changed'
    assert result['public_result']['foreign_object_state']=='unclassified'
    assert result['public_result']['residue_state']=='unknown'
    assert result['public_result']['unclassified_count']==1

def test_binary_jpeg_tracking_has_same_identity_guards(env):
    data=inspect(env);client,url,*_=env;body=jpeg()
    query={'client_frame_id':2,'check_id':data['check_id'],'source_sha256':hashlib.sha256(body).hexdigest()}
    response=client.post(url+'/frames/jpeg',params=query,content=body,headers={'Content-Type':'image/jpeg'})
    assert response.status_code==200 and response.json()['tracking_state']=='tracking'
    assert response.json()['source_sha256']==query['source_sha256']
    query['client_frame_id']=3;query['source_sha256']='0'*64
    assert client.post(url+'/frames/jpeg',params=query,content=body,headers={'Content-Type':'image/jpeg'}).status_code==422
    assert client.post(url+'/frames/jpeg',params=query,content=body,headers={'Content-Type':'text/plain'}).status_code==415

def test_full_foreground_tracking_artifact_hidden_without_clearing_semantics(env):
    data=inspect(env);tracker=env[3][-1]
    for mask in tracker.shared_masks.values():mask[:]=True
    r=env[0].post(env[1]+'/frames',json=frame(2,data['check_id'])).json()
    assert r['decision']['status']=='anomaly_detected' and not r['label_map']
    assert r['tracking_state']=='needs_reinspection'
    assert all('current_mask_has_no_boundary_evidence' in row['reasons'] for row in r['objects'])

def test_periodic_reinspection_replaces_version_and_old_frames_rejected(env):
    data=inspect(env);env[2].value=observation(False)
    new=env[0].post(env[1]+'/inspect',json=frame(2)).json()
    assert new['check_id']!=data['check_id'] and new['decision']['status']=='no_visible_anomaly'
    assert 'foreign_object_1' in env[3][-1].closed
    assert new['segmentation_skipped'] and new['objects'][0]['segmentation_status']=='reused_tracking'
    assert env[0].post(env[1]+'/frames',json=frame(3,data['check_id'])).status_code==409
    assert env[0].post(env[1]+'/frames',json=frame(2,new['check_id'])).status_code==409

def test_source_hash_rejected_before_inference(env):
    body=frame();body['source_sha256']='0'*64
    assert env[0].post(env[1]+'/inspect',json=body).status_code==422
    assert not env[2].calls

def test_service_failure_no_keys_or_false_clear(env):
    env[2].fail=True;data=inspect(env)
    assert data['decision']['status']=='service_unavailable' and data['active_tracks']==0
    assert all('test-private-key' not in p.read_text() for p in env[4].log_root.rglob('*.json*'))

def test_placeholder_cannot_start_and_public_settings_no_credentials(env):
    client=env[0]
    assert client.post('/api/inspection/runs',json={'task_id':'nozzle_blob'}).status_code==409
    assert 'test-private-key' not in client.get('/api/inspection/config').text
    assert sum(x['available'] for x in client.get('/api/inspection/tasks').json()['tasks'])==1

def test_report_and_evidence_survive_closing_session(env):
    data=inspect(env);env[0].delete(env[1]);report=env[0].get(env[1]+'/report')
    assert report.status_code==200
    assert env[0].get(env[1]+'/'+data['check_id']+'/overlay.jpg').status_code==200
    assert env[1]+'/'+data['check_id']+'/overlay.jpg' in report.text

def test_release_summary_and_report_do_not_expose_model_authored_text(env):
    sentinel='DO_NOT_SHOW_MODEL_REPLY'
    env[2].value['next_action']=sentinel;env[2].value['limitations']=[sentinel];env[2].value['anomalies'][0]['description']=sentinel
    data=inspect(env)
    assert data['public_result']['status']=='anomaly_detected'
    assert data['public_result']['foreign_object_state']=='fail'
    assert sentinel not in json.dumps(data['public_result'])
    html=env[0].get(env[1]+'/report').text
    assert sentinel not in html and 'clear_checks' not in html and '<pre>' not in html
    # The original observation is still available in local research logs.
    path=next(env[4].log_root.glob('*/check_*/observation.json'))
    assert sentinel in path.read_text()

def test_save_evidence_creates_customer_summary_without_model_reply(env):
    data=inspect(env);client,url,*_=env
    saved=client.post(url+'/evidence',json={'check_id':data['check_id']})
    assert saved.status_code==200 and saved.json()['saved']
    dest=env[4].log_root/url.rsplit('/',1)[-1]/'evidence'/data['check_id']
    assert (dest/'input.jpg').is_file() and (dest/'overlay.jpg').is_file()
    summary=json.loads((dest/'summary.json').read_text())
    assert summary['status']=='anomaly_detected' and 'next_action' not in summary
    assert client.post(url+'/evidence',json={'check_id':'check_'+'0'*16}).status_code==404

def test_invalid_geometry_retried_then_rejected(env):
    env[2].value['plate']['bbox_0_1000']=[500,500,10,10]
    assert inspect(env)['decision']['status']=='service_unavailable'
    assert len(env[2].calls)==2

def test_low_self_reported_confidence_cannot_erase_detected_anomaly(env):
    env[2].value['anomalies'][0]['confidence']=.2
    result=inspect(env)
    assert result['decision']['status']=='anomaly_detected'
    assert result['objects'][1]['tracking_ready']

def test_uncertain_ownership_retains_candidate_and_never_reports_clear(env):
    env[2].value['surface_assessment']='clear'
    env[2].value['anomalies'][0]['on_plate']='uncertain'
    result=inspect(env)
    assert result['decision']['status']=='insufficient_evidence'
    assert result['objects'][1]['semantic_status']=='candidate'
    assert not result['decision']['clear_checks']['no_confirmed_or_uncertain_anomaly']

def test_fixed_pixel_fraction_rules_removed_but_point_and_box_still_checked():
    from manual2ar.modules.inspection.rules import initial_mask_quality
    settings=config()['inspection'];mask=np.zeros((100,100),np.uint8);mask[50,50]=255
    state=SimpleNamespace(mask=mask,semantic_box=[45,45,55,55],guidance_target=GuidanceTarget(expected_component_id='intro_residue_1',target_point_0_1000=[500,500]))
    assert initial_mask_quality(state,settings)[0]
    state.mask[:]=255
    assert 'segmentation_has_no_background' in initial_mask_quality(state,settings)[1]
    state.mask[:]=0;state.mask[:10,:10]=255
    assert 'mask_leaves_prompt_region' in initial_mask_quality(state,settings)[1]

def test_real_cpu_large_plate_and_black_object_segmentation_and_motion(tmp_path):
    c=config();tracker=InspectionTracker('opencv',c);plate_mask=np.zeros((240,320),np.uint8);plate_mask[12:228,16:304]=255
    # Inject a known remote-style plate mask to isolate the 55% legacy cap.
    tracker.local.external_masks={'build_plate':plate_mask}
    target=GuidanceTarget(expected_component_id='intro_build_plate',target_point_0_1000=[200,200],expected_area_ratio_min=.00003,expected_area_ratio_max=.98)
    s,p=tracker.start(jpeg(),'intro_build_plate',[50,50,950,950],target)
    assert p.mask_quality_passed and p.mask_area_ratio>.55,p.mask_quality_reasons
    # Real GrabCut, using a non-orange foreground, then real LK on translated image.
    tracker.local.external_masks=None
    target=target.model_copy(update={'expected_component_id':'intro_foreign_object_1','target_point_0_1000':[450,450]})
    identity,obj=tracker.start(jpeg(),'intro_foreign_object_1',[350,350,600,600],target)
    assert obj.mask_quality_passed,obj.mask_quality_reasons
    mask=tracker.local._states[identity].mask>0
    expected=np.zeros((240,320),bool);expected[84:144,112:192]=True
    assert (mask&expected).sum()/max(1,(mask|expected).sum())>.85
    a=cv2.imdecode(np.frombuffer(jpeg(),np.uint8),cv2.IMREAD_COLOR)
    shifted=cv2.warpAffine(a,np.float32([[1,0,3],[0,1,2]]),(320,240))
    ok,body=cv2.imencode('.jpg',shifted);assert ok
    moved=tracker.update_many([s,identity],body.tobytes())
    assert moved[identity].status=='tracking',moved[identity].mask_quality_reasons
    assert moved[identity].bbox_0_1000[0]>obj.bbox_0_1000[0]

def test_real_cpu_service_tracks_and_recovers_after_occluded_frame(tmp_path):
    c=config();app=create_app(c,FakeVLM(),log_root=tmp_path/'runs')
    def payload(body,index,check):return {'client_frame_id':index,'check_id':check,'source_sha256':hashlib.sha256(body).hexdigest(),'image_base64':base64.b64encode(body).decode()}
    with TestClient(app) as client:
        identity=client.post('/api/inspection/runs',json={'provider':'opencv','source':'camera'}).json()['run_id'];api='/api/inspection/runs/'+identity
        initial=client.post(api+'/inspect',json=frame()).json()
        assert initial['active_tracks']==2,initial
        source=cv2.imdecode(np.frombuffer(jpeg(),np.uint8),cv2.IMREAD_COLOR)
        for i,shift in [(2,3),(3,None),(4,6)]:
            image=np.full_like(source,70) if shift is None else cv2.warpAffine(source,np.float32([[1,0,shift],[0,1,2]]),(320,240))
            ok,body=cv2.imencode('.jpg',image);assert ok
            result=client.post(api+'/frames',json=payload(body.tobytes(),i,initial['check_id'])).json()
            assert result['decision']['status']=='anomaly_detected'
            assert result['active_tracks']==2,result
            if shift is None:assert result['tracking_state']=='recovering' and not result['label_map']
            else:assert result['tracking_state']=='tracking',result
        assert decode_labels(result['label_map'],320,240)['foreign_object_1'].any()

def test_actual_cloud_adapter_initialization_and_persistent_step_with_mock_transport(tmp_path,monkeypatch):
    from manual2ar_contracts.gpu import Start
    class Remote:
        def __init__(self,connection,timeout):self.http=SimpleNamespace(timeout=timeout)
        def health(self):return {'protocol':'manual2ar-learning-cutie-v2'}
        def probe(self):return []
        def start(self,image,targets):
            Start(image_base64=base64.b64encode(image).decode(),source_sha256=hashlib.sha256(image).hexdigest(),frame_id=0,targets=targets)
            self.targets=targets;self.masks={}
            for t in targets:
                mask=np.zeros((240,320),bool);a,b,c,d=t['bbox_0_1000'];mask[b*240//1000:d*240//1000,a*320//1000:c*320//1000]=True;self.masks[t['component_id']]=mask
            return self.masks,{'metrics':{},'http_roundtrip_ms':1}
        def step(self,image,index):
            return self.masks,{'metrics':{},'http_roundtrip_ms':1,'source_sha256':hashlib.sha256(image).hexdigest(),'targets_sha256':'controlled'}
        def close(self):pass
    monkeypatch.setattr('manual2ar.integrations.perception.remote_tracker.CutieClient',Remote)
    c=config();connection=tmp_path/'connection.json';connection.write_text('{}');c['cutie_tracking']['connection_file']=str(connection)
    with TestClient(create_app(c,FakeVLM(),log_root=tmp_path/'runs')) as client:
        identity=client.post('/api/inspection/runs',json={'provider':'sam31_cutie','source':'camera'}).json()['run_id'];api='/api/inspection/runs/'+identity
        data=client.post(api+'/inspect',json=frame()).json()
        assert data['decision']['status']=='anomaly_detected' and data['active_tracks']==2,data
        result=client.post(api+'/frames',json=frame(2,data['check_id'])).json()
        assert result['tracking_state']=='tracking' and result['active_tracks']==2
        assert result['decision']['status']=='anomaly_detected'
        assert decode_labels(result['label_map'],320,240)['foreign_object_1'].any()
