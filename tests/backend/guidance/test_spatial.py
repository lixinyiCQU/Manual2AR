"""Physical geometry and API regressions; all images are synthetic, never private uploads."""
import base64
import hashlib
import json
import time
import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient
from manual2ar.application.config import load,for_module
from manual2ar.modules.guidance.server import create_app
from manual2ar.modules.guidance.spatial.simulation import calibration,jpeg,pose
from manual2ar.modules.guidance.spatial.models import Begin,Author,Save
from manual2ar_perception.spatial import detect_pose,project,triangulate


class NoVLM:
    def chat_structured(self,**kwargs):raise AssertionError('Spatial positioning must not call VLM')


@pytest.fixture
def app(tmp_path):
    config=for_module(load(),'guidance');config['runtime_dir']=str(tmp_path)
    return create_app(config,NoVLM())


def frame(raw=None,number=1,action='purge.slide',**extra):
    raw=raw or jpeg(30)
    return {**dict(client_frame_id=number,image_base64=base64.b64encode(raw).decode(),
                source_sha256=hashlib.sha256(raw).hexdigest(),action_id=action),**extra}


def begin(client,mode='replay',**extra):
    result=client.post('/api/guidance/spatial/sessions',json=dict(camera_id='test-webcam',mode=mode,**extra))
    assert result.status_code==201,result.text
    return '/api/guidance/spatial/sessions/'+result.json()['session_id']


@pytest.mark.parametrize('index',[0,30,80,150,220])
def test_actual_marker_detector_and_metric_pose(index):
    c=calibration();image=cv2.imdecode(np.frombuffer(jpeg(index),np.uint8),cv2.IMREAD_COLOR)
    detected,status=detect_pose(image,np.array(c['matrix']),np.array(c['distortion']))
    assert status=='tracking'
    assert np.linalg.norm(detected['transform'][:3,3]-pose(index)[:3,3])<.004
    # Project a target away from marker, so translation/rotation errors cannot hide in its corners.
    expected=project([[.09,-.045,.025]],pose(index),np.array(c['matrix']),np.array(c['distortion']))
    observed=project([[.09,-.045,.025]],detected['transform'],np.array(c['matrix']),np.array(c['distortion']))
    assert np.linalg.norm(expected-observed)<5


def test_triangulation_recovers_metric_targets_with_distortion_and_rejects_weak_views():
    c=calibration();matrix=np.array(c['matrix']);distortion=np.array([-.12,.04,.001,-.002,0])
    a=np.diag([1.,-1.,-1.,1.]);a[:3,3]=[-.13,.02,.6]
    b=a.copy();b[:3,3]=[.13,.02,.6]
    points=np.array([[.07,.03,.01],[.08,-.045,.025]])
    p=project(points,a,matrix,distortion);q=project(points,b,matrix,distortion)
    recovered,quality=triangulate(p,a,q,b,matrix,distortion)
    assert np.max(np.abs(np.array(recovered)-points))<.0001
    assert quality['minimum_ray_angle_deg']>5
    with pytest.raises(ValueError,match='视角差'):triangulate(p,a,p,a,matrix,distortion)
    q[0,1]+=50
    with pytest.raises(ValueError):triangulate(p,a,q,b,matrix,distortion)


def test_replay_pipeline_identity_loss_recovery_and_no_real_profiles(app,tmp_path):
    with TestClient(app) as client:
        api=begin(client)
        result=client.post(api+'/frames',json=frame()).json()
        assert result['state']=='tracking' and result['target_ready'] and len(result['lines'])==3
        assert len(result['pose']['matrix'])==16
        assert result['source_sha256']==frame()['source_sha256']
        white=cv2.imencode('.jpg',np.full((720,960,3),255,np.uint8))[1].tobytes()
        missing=client.post(api+'/frames',json=frame(white,2)).json()
        assert missing['state']=='marker_missing' and missing['lines']==[] and missing['pose'] is None
        recovered=client.post(api+'/frames',json=frame(number=3,action='purge.fasten')).json()
        assert recovered['state']=='tracking' and len(recovered['lines'])>20
        assert client.post(api+'/calibration',json={}).status_code==422
        assert client.post(api+'/verify',json={'action_id':'purge.slide','client_frame_id':3}).status_code==409
        assert not (tmp_path/'guidance-spatial/profiles').exists()
        assert client.delete(api).status_code==204
        assert client.post(api+'/frames',json=frame(number=4)).status_code==404


def test_real_camera_never_uses_guessed_intrinsics_or_targets(app):
    with TestClient(app) as client:
        api=begin(client,'camera')
        reply=client.post(api+'/frames',json=frame()).json()
        assert reply['state']=='camera_calibration_required' and reply['lines']==[]
        assert client.post(api+'/calibration',json={}).status_code==422
        assert client.post(api+'/frames',json=frame(number=2,source_sha256='0'*64)).status_code==409
        # A still-valid frame cannot silently be checked with another action's prompt.
        mismatch=client.post(api+'/verify',json={'action_id':'holder.slide','client_frame_id':1})
        assert mismatch.status_code==409 and '其他动作' in mismatch.json()['detail']


def test_contract_rejects_stale_frames_wrong_resolution_unknown_actions_and_nonfinite_pixels(app):
    with TestClient(app) as client:
        api=begin(client)
        assert client.post(api+'/frames',json=frame()).status_code==200
        assert client.post(api+'/frames',json=frame()).status_code==409
        assert client.post(api+'/frames',json=frame(number=2,action='arbitrary')).status_code==422
        small=cv2.imencode('.jpg',np.zeros((480,640,3),np.uint8))[1].tobytes()
        assert client.post(api+'/frames',json=frame(small,2)).status_code==409
        assert client.post(api+'/frames',json={**frame(number=2),'unrecognised':1}).status_code==422
        assert client.post('/api/guidance/spatial/sessions',json={'camera_id':'../escape'}).status_code==422


def test_explicit_two_view_authoring_and_confirmed_profile_reuse(app,tmp_path):
    service=app.state.spatial
    start=service.begin(Begin(camera_id='real-camera'));identity=start['session_id'];s=service.sessions[identity]
    s.calibration=calibration();s.mode='camera';s.size=(960,720)
    a=np.diag([1.,-1.,-1.,1.]);a[:3,3]=[-.13,.02,.6];b=a.copy();b[:3,3]=[.13,.02,.6]
    points=[[.07,.03,.01],[.08,-.045,.025]];c=calibration();matrix=np.array(c['matrix']);distortion=np.array(c['distortion'])
    for index,transform in [(1,a),(2,b)]:
        raw=jpeg(index);s.frames[index]={'raw':raw,'pose':{'transform':transform},'size':(960,720),'sha256':hashlib.sha256(raw).hexdigest(),'at':time.monotonic(),'action_id':'purge.slide'}
    def wire(values):return [{'x':float(x),'y':float(y)} for x,y in values]
    candidate=service.author(identity,Author(action_id='purge.slide',first_frame=1,second_frame=2,
        first_points=wire(project(points,a,matrix,distortion)),second_points=wire(project(points,b,matrix,distortion))))
    assert not service.profile('rigs','a1-mini').exists()
    service.save(identity,Save(candidate_id=candidate['candidate_id'],confirmed=True))
    profile=json.loads(service.profile('rigs','a1-mini').read_text())
    assert np.allclose(profile['purge.slide']['points_m'],points,atol=.0001)
    assert len(list((tmp_path/'guidance-spatial/runs'/identity).rglob('view-*.jpg')))==2
    again=service.begin(Begin(camera_id='real-camera'))
    assert again['has_saved_targets'] and not again['target_reuse_confirmed']
    service.pin(identity,1)
    assert s.pinned==[1]


def test_official_action_provenance_and_printable_dimensions(app):
    service=app.state.spatial
    plan=service.catalog();assert len(plan['actions'])==10
    root=service.store.root/'tasks/bambu_a1_mini/unboxing/v2'
    evidence=json.loads((root/'evidence.json').read_text())
    for action in plan['actions']:
        assert action['official_text']==evidence['evidence'][action['citation_ids'][0]]['text']
        assert all((root/p).is_file() for p in action['reference_images'])
    assert '从上向下' in next(a for a in plan['actions'] if a['action_id']=='holder.slide')['instruction']
    with TestClient(app) as client:
        pdf=client.get('/api/guidance/spatial/print.pdf')
        assert pdf.status_code==200 and pdf.content.startswith(b'%PDF') and len(pdf.content)>20000


def test_calibration_solves_diverse_views_and_binds_capture_resolution(app):
    from manual2ar.modules.guidance.spatial.printing import PATTERN,SQUARE
    service=app.state.spatial;identity=service.begin(Begin(camera_id='calibrated-camera'))['session_id'];s=service.sessions[identity]
    s.size=(960,720);c=calibration();matrix=np.array(c['matrix']);distortion=np.zeros(5)
    objects=np.zeros((PATTERN[0]*PATTERN[1],3),np.float32);objects[:,:2]=np.mgrid[:9,:6].T.reshape(-1,2)*SQUARE
    for i in range(18):
        rotation=np.array([.08+(i%3)*.12,-.2+(i%4)*.12,-.08+(i%2)*.16])
        translation=np.array([-.17+(i%3)*.065,-.12+(i%4)*.032,.34+(i%2)*.10])
        pixels=cv2.projectPoints(objects,rotation,translation,matrix,distortion)[0].reshape(-1,2)
        assert np.min(pixels)>=0 and np.max(pixels[:,0])<960 and np.max(pixels[:,1])<720
        s.samples.append(pixels)
    result=service.calibrate(identity)
    assert result['views']==18 and result['rms_px']<.01
    assert np.allclose(s.calibration['matrix'],matrix,atol=.1)
    saved=json.loads(service.profile('cameras','calibrated-camera').read_text())
    assert saved['width']==960 and saved['height']==720 and saved['square_m']==.02


def test_chessboard_capture_requires_full_grid_and_different_view(app):
    from manual2ar.modules.guidance.spatial.printing import PATTERN
    service=app.state.spatial;identity=service.begin(Begin(camera_id='checkerboard'))['session_id'];s=service.sessions[identity]
    image=np.full((720,960,3),255,np.uint8)
    for y in range(7):
        for x in range(10):
            if (x+y)%2==0:cv2.rectangle(image,(180+x*50,150+y*50),(229+x*50,199+y*50),(0,0,0),-1)
    service.add_sample(s,image)
    assert len(s.samples)==1 and s.samples[0].shape==(PATTERN[0]*PATTERN[1],2)
    from fastapi import HTTPException
    with pytest.raises(HTTPException,match='太相似'):service.add_sample(s,image)


def test_optional_check_reuses_v1_chapter_prompt_and_identity_without_progress_mutation(tmp_path):
    class Client:
        call=None
        def chat_structured(self,**kw):
            self.call=kw
            return {'status':'completed','matched_step_id':'U7','inspection_id':'U7-C1',
                'evidence':'底座贴合，支架已滑入。','confidence':.9,'next_action':'可继续查看教程。','component_boxes_0_1000':[]}
    config=for_module(load(),'guidance');config['runtime_dir']=str(tmp_path);config['vlm']['api_key']='local-test-only'
    spy=Client();app=create_app(config,spy)
    with TestClient(app) as client:
        api=begin(client,'camera');reply=client.post(api+'/frames',json=frame(action='holder.slide')).json()
        result=client.post(api+'/verify',json={'action_id':'holder.slide','client_frame_id':1})
        assert result.status_code==200,result.text
        assert result.json()['advisory_only'] and result.json()['source_sha256']==reply['source_sha256']
        assert len(spy.call['images_base64'])==1 and 'U7-C1' in spy.call['prompt']
        assert len(app.state.guidance.meta)==0


def test_animation_samples_metric_path_before_perspective_projection():
    from manual2ar_perception.spatial import visual_geometry
    from manual2ar_contracts.spatial import GuidanceVisual
    c=calibration();matrix=np.array(c['matrix']);distortion=np.array(c['distortion']);transform=pose(20)
    points=np.array([[.06,.04,.01],[.1,-.04,.17]])
    visual=GuidanceVisual(**visual_geometry(points,'slide',transform,matrix,distortion),label='插槽')
    assert len(visual.trajectory)==33 and visual.illustrative_only
    actual=np.array([visual.trajectory[16].x,visual.trajectory[16].y])
    expected=project([np.mean(points,axis=0)],transform,matrix,distortion)[0]
    assert np.allclose(actual,expected)
    ends=project(points,transform,matrix,distortion)
    assert np.linalg.norm(actual-np.mean(ends,axis=0))>1
    tool=GuidanceVisual(**visual_geometry(points,'fasten',transform,matrix,distortion),label='螺丝')
    assert len(tool.tool_lines)==2 and not tool.trajectory


def test_saved_primary_target_survives_upgrade_and_occlusion_without_reauthoring(app):
    service=app.state.spatial
    # Same schema as the user's pre-animation target, no target_id or visual fields.
    original={'holder.slide':{'points_m':[[.09,.03,.025],[.09,-.045,.025]],'marker_id':23,'marker_length_m':.08}}
    path=service.profile('rigs','a1-mini');path.parent.mkdir(parents=True);path.write_text(json.dumps(original));before=path.read_bytes()
    camera=service.profile('cameras','test-webcam');camera.parent.mkdir(parents=True);camera.write_text(json.dumps(calibration()))
    with TestClient(app) as client:
        api=begin(client,'camera',reuse_targets=True)
        result=client.post(api+'/frames',json=frame(action='holder.slide')).json()
        assert result['target_configured'] and result['target_ready'] and result['target_id']=='main'
        assert result['visual']['label']=='支架滑入方向'
        blank=cv2.imencode('.jpg',np.full((720,960,3),255,np.uint8))[1].tobytes()
        hidden=client.post(api+'/frames',json=frame(blank,number=2,action='holder.slide')).json()
        assert hidden['target_configured'] and not hidden['target_ready'] and hidden['visual'] is None
    assert path.read_bytes()==before


def test_two_screw_positions_are_independent_and_have_bound_frame_identity(app):
    with TestClient(app) as client:
        api=begin(client)
        first=client.post(api+'/frames',json=frame(action='holder.base')).json()
        second=client.post(api+'/frames',json=frame(number=2,action='holder.base',target_id='second')).json()
        assert first['target_id']=='main' and second['target_id']=='second'
        assert first['visual']['label']=='底座螺丝 1' and second['visual']['label']=='底座螺丝 2'
        assert np.linalg.norm([first['visual']['anchor'][axis]-second['visual']['anchor'][axis] for axis in ['x','y']])>20
        assert client.post(api+'/frames',json=frame(number=3,action='purge.slide',target_id='second')).status_code==422


def test_animation_and_human_mark_events_never_become_verification_results(app):
    import uuid
    with TestClient(app) as client:
        api=begin(client);reply=client.post(api+'/frames',json=frame()).json()
        event={'event_id':uuid.uuid4().hex,'name':'animation_finished','action_id':'purge.slide','target_id':'main',
               'client_frame_id':1,'source_sha256':reply['source_sha256'],'progress':1,'request_ms':80,'presentation_fps':8}
        response=client.post(api+'/events',json=event)
        assert response.status_code==200 and response.json()['operation_verified'] is False
        assert client.post(api+'/events',json=event).json()['duplicate']
        wrong={**event,'event_id':uuid.uuid4().hex,'source_sha256':'0'*64}
        assert client.post(api+'/events',json=wrong).status_code==409
        mark={**event,'event_id':uuid.uuid4().hex,'name':'user_marked'}
        assert client.post(api+'/events',json=mark).json()['operation_verified'] is False
        assert not app.state.guidance.meta
        folder=app.state.spatial.root/'runs'/api.rsplit('/',1)[-1]
        rows=[json.loads(line) for line in (folder/'events.jsonl').read_text().splitlines()]
        assert len([e for e in rows if e['event']=='interaction.animation_finished'])==1
        assert not list(folder.rglob('input.jpg'))
