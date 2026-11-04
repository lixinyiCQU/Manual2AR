"""Integrated tutorial/spatial lifecycle and native-provider contract boundaries."""
import uuid
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from manual2ar_contracts.spatial import CaptureSnapshot
from tests.backend.guidance.test_spatial import app, begin, frame

TASK='a1_mini_standalone_unboxing_v1'


def tutorial(c,variant='standalone_unboxing'):
    r=c.post('/api/guidance/runs',json={'task_id':TASK,'variant_id':variant})
    assert r.status_code==201,r.text
    return r.json()


def event(c,api,name='user_marked',**kwargs):
    return c.post(api+'/events',json={'event_id':uuid.uuid4().hex,'action_id':'holder.slide',
        'target_id':'main','name':name,'client_frame_id':0,**kwargs})


def test_source_bound_actions_are_discoverable_without_camera_or_vlm(app):
    with TestClient(app) as c:
        run=tutorial(c);assert len(run['task_info']['steps'])==13
        assert sum(s['spatial_mode']=='marker' for s in run['task_info']['steps'])==4
        r=c.post('/api/guidance/runs/'+run['run_id']+'/browse',json={
            'state_id':run['state_id'],'revision':run['revision'],'target_state_id':'U4','substep_id':'U4-S3'})
        v=r.json()['spatial_guidance'];assert v['current_action_ids']==['toolhead.slide','packing.foam']
        assert len(v['actions'])==4
        assert all(a['substep_id'].startswith('U4-S') for a in v['actions'])
        assert c.get('/api/guidance/spatial/capabilities').json()['native_ar_available'] is False


def test_bound_replay_records_do_not_confirm_operation_or_advance_tutorial(app):
    with TestClient(app) as c:
        run=tutorial(c);api=begin(c,tutorial_run_id=run['run_id'])
        assert c.post(api+'/frames',json=frame(action='holder.slide')).status_code==200
        command={'event_id':uuid.uuid4().hex}
        assert event(c,api,**command).status_code==200
        assert event(c,api,**command).json()['duplicate']
        after=c.get('/api/guidance/runs/'+run['run_id']).json()
        assert after['revision']==run['revision'] and after['state_id']==run['state_id']
        assert after['user_marked_step_ids']==[] and after['observations']==run['observations']
        records=after['spatial_guidance']['learning_records'];assert len(records)==1
        assert records[0]['mode']=='replay' and records[0]['operation_verified'] is False
        assert records[0]['substep_id']=='U7-S2'
        html=c.get('/api/guidance/runs/'+run['run_id']+'/report').text
        assert '空间指导记录' in html and '模拟回放' in html
        c.delete(api)
        # A new spatial session resumes the same learning record, not an old pose.
        second=begin(c,tutorial_run_id=run['run_id'])
        assert second!=api
        assert len(c.get('/api/guidance/runs/'+run['run_id']).json()['spatial_guidance']['learning_records'])==1


def test_ams_preserves_official_content_without_wrong_variant_spatial_actions(app):
    with TestClient(app) as c:
        variant=next(v['id'] for t in c.get('/api/guidance/tasks').json()['tasks'] if t['id']==TASK for v in t['variants'] if v['id']!='standalone_unboxing')
        run=tutorial(c,variant)
        assert len(run['task_info']['steps'])==13
        assert not run['spatial_guidance']['available'] and not run['spatial_guidance']['actions']
        r=c.post('/api/guidance/spatial/sessions',json={'camera_id':'synthetic','mode':'replay','tutorial_run_id':run['run_id']})
        assert r.status_code==409


def test_closed_tutorial_cannot_accept_late_spatial_interaction(app):
    with TestClient(app) as c:
        run=tutorial(c);api=begin(c,tutorial_run_id=run['run_id'])
        r=c.post('/api/guidance/runs/'+run['run_id']+'/cancel-flow',json={'state_id':run['state_id'],'revision':run['revision']})
        assert r.status_code==200
        assert event(c,api).status_code==409
        assert c.post(api+'/frames',json=frame()).status_code==409
        assert c.delete(api).status_code==204


def snapshot(request,**kwargs):
    return {'provider_id':'synthetic','client_frame_id':request['client_frame_id'],
        'source_sha256':request['source_sha256'],'width':960,'height':720,
        'capture_monotonic_ms':1234,**kwargs}


def test_frozen_capture_is_bound_to_image_and_native_provider_not_silently_enabled(app):
    with TestClient(app) as c:
        api=begin(c);request=frame()
        r=c.post(api+'/frames',json={**request,'snapshot':snapshot(request,width=720)})
        assert r.status_code==409
        assert c.post(api+'/frames',json={**request,'snapshot':snapshot(request)}).status_code==200
        request=frame(number=2)
        native=snapshot(request,provider_id='arkit',reference_space_id='ar-session-1',
            camera_intrinsics=[850,0,480,0,850,360,0,0,1],world_from_camera=[1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1])
        assert c.post(api+'/frames',json={**request,'snapshot':native}).status_code==422


@pytest.mark.parametrize('changes',[{'provider_id':'arkit'}, {'world_from_camera':[1]*16},
    {'world_from_camera':[-1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1]}, {'capture_monotonic_ms':float('nan')}])
def test_native_snapshot_rejects_missing_or_invalid_spatial_data(changes):
    with pytest.raises(ValidationError):CaptureSnapshot.model_validate(snapshot(frame(),**changes))


class Locator:
    def __init__(self,visible=True):self.calls=[];self.visible=visible
    def chat_structured(self,**kwargs):
        self.calls.append(kwargs)
        return {'action_id':'toolhead.slide','target_id':'main','status':'found' if self.visible else 'unseen',
            'confidence':.95,'bbox_0_1000':[600,300,750,600] if self.visible else [],
            'foreground_point_0_1000':[675,450] if self.visible else []}


@pytest.mark.parametrize('visible',[True,False])
def test_photo_localization_is_action_specific_and_never_a_placement_or_check(app,visible):
    client=Locator(visible);app.state.spatial.client=client;app.state.spatial.config['vlm']['api_key']='test-only'
    with TestClient(app) as c:
        run=tutorial(c);api=begin(c,'camera',tutorial_run_id=run['run_id'])
        request=frame(action='toolhead.slide');assert c.post(api+'/frames',json=request).status_code==200
        r=c.post(api+'/locate',json={'action_id':'toolhead.slide','target_id':'main','client_frame_id':1})
        assert r.status_code==200,r.text
        value=r.json();assert value['metric_placement'] is False and value['source_sha256']==request['source_sha256']
        assert len(value['box_lines'])==(4 if visible else 0)
        prompt=client.calls[0]['prompt'];assert '向左' in prompt and 'NOT installation verification' in prompt
        assert len(client.calls[0]['images_base64'])==1
        # No target/camera profiles are created and the tutorial never advances.
        assert not list((app.state.spatial.root/'profiles').rglob('*.json'))
        updated=c.get('/api/guidance/runs/'+run['run_id']).json()
        assert updated['revision']==run['revision'] and updated['observations']==run['observations']
        assert updated['spatial_guidance']['learning_records'][0]['event']=='location_preview'
