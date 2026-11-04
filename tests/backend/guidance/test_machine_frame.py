"""Work-frame registration, independent motion and safe coexistence with learned/segmented parts."""
import hashlib
import time
import json
import numpy as np
import pytest
from pydantic import ValidationError
from fastapi.testclient import TestClient
from manual2ar_contracts.machine_frame import MachineFrame
from manual2ar.modules.guidance.spatial.machine import from_points
from manual2ar_perception.spatial import project
from manual2ar.modules.guidance.spatial.simulation import calibration,jpeg,targets
from tests.backend.guidance.test_spatial import app,begin,frame


def prepare(service,c,points=None):
    api=begin(c,'camera',u7_fixture_verified=True);s=service.sessions[api.split('/')[-1]];s.calibration=calibration()
    s.targets=targets(service.actions);s.authorized=set(s.targets)
    a=np.diag([1.,-1.,-1.,1.]);a[:3,3]=[-.13,.02,.6];b=a.copy();b[:3,3]=[.13,.02,.6]
    points=points if points is not None else np.array([[.04,.02,.01],[.12,.02,.01],[.04,.02,.11]])
    for number,pose in [(1,a),(2,b)]:
        raw=jpeg(number);s.frames[number]={'raw':raw,'pose':{'transform':pose},'size':(960,720),'sha256':hashlib.sha256(raw).hexdigest(),'at':time.monotonic(),'action_id':'holder.slide','target_id':'main'}
    def pixels(pose):return [{'x':float(x),'y':float(y)} for x,y in project(points,pose,np.array(s.calibration['matrix']),np.zeros(5))]
    return api,s,dict(first_frame=1,second_frame=2,first_points=pixels(a),second_points=pixels(b))


def register(c,api,command):
    r=c.post(api+'/machine/candidates',json=command);assert r.status_code==200,r.text
    candidate=r.json();saved=c.post(api+'/machine/confirm',json={'candidate_id':candidate['candidate_id'],'confirmed':True});assert saved.status_code==200,saved.text
    return candidate,saved.json()['frame']


def test_two_view_machine_registration_requires_confirmation_and_reuse(app):
    service=app.state.spatial
    with TestClient(app) as c:
        api,s,command=prepare(service,c)
        candidate=c.post(api+'/machine/candidates',json=command).json()
        assert s.machine_frame is None and not service.profile('machines','a1-mini').exists()
        assert len(candidate['preview_axes'])==3
        assert c.post(api+'/machine/confirm',json={'candidate_id':candidate['candidate_id'],'confirmed':False}).status_code==422
        c.post(api+'/machine/confirm',json={'candidate_id':candidate['candidate_id'],'confirmed':True})
        t=np.array(s.machine_frame['marker_from_machine']).reshape(4,4)
        assert np.allclose(t[:3,:3],np.eye(3)) and np.allclose(t[:3,3],[.04,.02,.01])
        assert not service.profile('rigs','a1-mini').exists() and not service.profile('cameras','test-webcam').exists()
        other=begin(c,'camera',u7_fixture_verified=True);assert service.sessions[other.split('/')[-1]].machine_frame is None
        authorized=begin(c,'camera',u7_fixture_verified=True,reuse_targets=True);assert service.sessions[authorized.split('/')[-1]].machine_frame['frame_id']==candidate['frame_id']
        reply=c.post(api+'/frames',json=frame(number=3,action='holder.slide')).json()
        assert len(reply['machine_axes'])==3 and reply['visual']['machine_frame_id']==candidate['frame_id']
        tool=c.post(api+'/frames',json=frame(number=4,action='holder.base')).json()['visual']
        basis=np.array(tool['presentation']['instances'][0]['reference_from_asset']).reshape(4,4)[:3,:3];assert np.allclose(basis[:,1]/np.linalg.norm(basis[:,1]),[0,-1,0])


def test_machine_axis_motion_is_metric_and_keeps_existing_target_endpoints(app):
    service=app.state.spatial
    with TestClient(app) as c:
        api,s,command=prepare(service,c);_,machine=register(c,api,command)
        original=json.loads(json.dumps(s.targets))
        parameters={'enabled':True,'axis':'Z','direction':-1,'distance_mm':55,'duration_seconds':2.3,'rotation_degrees':180,'rotation_sign':-1}
        assert c.post(api+'/motion',json={'action_id':'holder.slide','parameters':parameters}).status_code==200
        result=c.post(api+'/frames',json=frame(number=3,action='holder.slide')).json();visual=result['visual'];scene=visual['presentation'];moving=scene['instances'][0]
        assert visual['duration_seconds']==2.3 and scene['duration_seconds']==2.3
        assert np.allclose(moving['path_m'],[0,0,-.055])
        start=np.array(moving['reference_from_asset']).reshape(4,4)[:3,3]
        assert np.allclose(start+moving['path_m'],original['holder.slide']['points_m'][1])
        assert all(i['rotation_sign']==-1 and i['rotation_scale']==.5 for i in scene['instances'])
        assert visual['label'].endswith('−Z') and s.targets==original and not app.state.guidance.meta
        # Parameters are shared by a task action, not duplicated per screw.
        parameters.update(axis='X',direction=1)
        c.post(api+'/motion',json={'action_id':'holder.base','parameters':parameters})
        for frame_id,target in [(4,'main'),(5,'second')]:
            value=c.post(api+'/frames',json=frame(number=frame_id,action='holder.base',target_id=target)).json()['visual']
            t=np.array(value['presentation']['instances'][0]['reference_from_asset']).reshape(4,4);axis=t[:3,1]/np.linalg.norm(t[:3,1]);assert np.allclose(axis,[1,0,0])
            assert all(i['rotation_scale']==.5 for i in value['presentation']['instances'])
        parameters['rotation_degrees']=45
        c.post(api+'/motion',json={'action_id':'holder.base','parameters':parameters})
        half=c.post(api+'/frames',json=frame(number=6,action='holder.base')).json()['visual']
        assert all(i['rotation_scale']==.125 for i in half['presentation']['instances'])
        assert s.targets==original


def test_no_machine_frame_preserves_old_axis_and_blocks_enabled_parameters(app):
    with TestClient(app) as c:
        api=begin(c)
        assert c.post(api+'/motion',json={'action_id':'holder.slide','parameters':{'enabled':True}}).status_code==409
        assert c.post(api+'/motion',json={'action_id':'holder.slide','parameters':{'enabled':False}}).status_code==200
        r=c.post(api+'/frames',json=frame(action='holder.slide')).json();assert r['target_ready'] and not r['machine_axes'] and r['visual']['machine_frame_id']==''
        assert c.post(api+'/motion',json={'action_id':'zlock.remove','parameters':{'enabled':False}}).status_code==422
        for invalid in [{'axis':'Q'},{'distance_mm':1000},{'duration_seconds':0},{'rotation_degrees':720}]:
            assert c.post(api+'/motion',json={'action_id':'holder.slide','parameters':invalid}).status_code==422
        assert not app.state.spatial.profile('motions','a1-mini').exists()


def test_parallel_axis_clicks_and_weak_views_are_rejected(app):
    service=app.state.spatial
    with TestClient(app) as c:
        api,s,command=prepare(service,c,points=np.array([[.04,.02,.01],[.12,.02,.01],[.15,.02,.01]]))
        r=c.post(api+'/machine/candidates',json=command);assert r.status_code==422 and '垂直' in r.json()['detail']
        assert not service.profile('machines','a1-mini').exists()
        command['second_frame']=1;command['second_points']=command['first_points'];assert c.post(api+'/machine/candidates',json=command).status_code==409
        command['first_points'][0]['x']=1500;command['second_frame']=2;assert c.post(api+'/machine/candidates',json=command).status_code==422


def test_machine_frame_is_right_handed_and_orthogonal_not_a_pose_guess():
    t,angle=from_points([[0,0,0],[.1,0,0],[.005,0,.1]])
    assert np.allclose(t[:3,:3].T@t[:3,:3],np.eye(3)) and np.isclose(np.linalg.det(t[:3,:3]),1) and 85<angle<90
    with pytest.raises(ValueError):from_points([[0,0,0],[.1,0,0],[.09,0,.001]])
    t[0,0]*=-1
    with pytest.raises(ValidationError):MachineFrame(marker_id=23,marker_length_m=.08,marker_from_machine=t.ravel().tolist(),frame_id='a'*32,source_frame_sha256=['b'*64,'c'*64],quality={})


def test_failed_registration_keeps_both_views_and_all_point_diagnostics(app):
    service=app.state.spatial
    with TestClient(app) as c:
        api,s,command=prepare(service,c)
        command['second_points'][0]['y']+=20
        reply=c.post(api+'/machine/candidates',json=command)
        assert reply.status_code==422 and '重投影偏差' in reply.json()['detail']
        assert '诊断编号' in reply.json()['detail']
        folder=next((service.root/'runs'/api.split('/')[-1]).glob('machine-*'))
        data=json.loads((folder/'diagnostic.json').read_text())
        assert data['status']=='rejected' and len(data['points'])==3
        assert data['points'][0]['accepted'] is False and max(data['points'][0]['reprojection_px'])>3
        assert all(point['accepted'] for point in data['points'][1:])
        assert data['frames'][0]['pose']['transform']==s.frames[1]['pose']['transform'].tolist()
        assert data['calibration']==s.calibration and data['point_labels']==['O','+X','+Z']
        assert (folder/'view-1.jpg').read_bytes()==s.frames[1]['raw']
        assert (folder/'view-2.jpg').read_bytes()==s.frames[2]['raw']
        assert (folder/'view-1-clicks.jpg').is_file() and (folder/'view-2-clicks.jpg').is_file()
        assert 'O 点' in reply.json()['detail']
        assert not (folder/'candidate.json').exists() and not s.machine_candidates and s.machine_frame is None
        assert not service.profile('machines','a1-mini').exists()


def test_component_actions_are_independent_persisted_and_bounded(app):
    service=app.state.spatial
    with TestClient(app) as c:
        api,s,command=prepare(service,c);register(c,api,command)
        original=json.loads(json.dumps(s.targets))
        baseline=c.post(api+'/frames',json=frame(number=3,action='holder.slide')).json()['visual']['presentation']
        settings={'enabled':True,'axis':'Z','direction':-1,'distance_mm':60,'components':[
            {'id':'moving_holder','rotation_degrees':[0,180,0],'offset_mm':[10,0,0],'scale':1.5,'playing':False,'speed':2},
            {'id':'direction','visible':False}]}
        reply=c.post(api+'/motion',json={'action_id':'holder.slide','parameters':settings});assert reply.status_code==200,reply.text
        result=c.post(api+'/frames',json=frame(number=4,action='holder.slide')).json()['visual']['presentation']
        before=np.array(baseline['instances'][0]['reference_from_asset']).reshape(4,4)
        after=np.array(result['instances'][0]['reference_from_asset']).reshape(4,4)
        assert np.allclose(after[:3,3]-before[:3,3],[.01,0,0])
        assert np.isclose(np.linalg.norm(after[:3,0])/np.linalg.norm(before[:3,0]),1.5)
        assert result['instances'][0]['path_m']==baseline['instances'][0]['path_m']
        assert not result['instances'][0]['playing'] and result['instances'][0]['speed']==2
        assert not result['instances'][2]['visible'] and result['instances'][1]==baseline['instances'][1]
        assert s.targets==original
        fresh=begin(c,'camera',u7_fixture_verified=True);assert service.sessions[fresh.split('/')[-1]].motion_parameters['holder.slide']['components'][0]['scale']==1.5
        for components in [[{'id':'invented'}],[{'id':'direction','speed':0}],[{'id':'direction','rotation_degrees':[0,181,0]}],[{'id':'direction'},{'id':'direction'}]]:
            assert c.post(api+'/motion',json={'action_id':'holder.slide','parameters':{'components':components}}).status_code==422


def test_holder_is_upright_and_outward_while_path_still_moves_down(app):
    with TestClient(app) as c:
        api,s,command=prepare(app.state.spatial,c);register(c,api,command)
        visual=c.post(api+'/frames',json=frame(number=3,action='holder.slide')).json()['visual']
        item=visual['presentation']['instances'][0];rotation=np.array(item['reference_from_asset']).reshape(4,4)[:3,:3]
        assert rotation[0,0]<0 and rotation[2,1]>0
        assert np.allclose(item['path_m'],[0,0,-.06])
        assert c.post(api+'/motion',json={'action_id':'holder.slide','parameters':{'axis':'Z','direction':1,'distance_mm':60}}).status_code==200
        reversed_item=c.post(api+'/frames',json=frame(number=5,action='holder.slide')).json()['visual']['presentation']['instances'][0]
        assert np.allclose(np.array(reversed_item['reference_from_asset']).reshape(4,4)[:3,:3],rotation)
        assert np.allclose(reversed_item['path_m'],[0,0,.06])
        arrow=c.post(api+'/frames',json=frame(number=6,action='holder.base')).json()['visual']['presentation']['instances'][1]
        assert arrow['reverse_with_rotation']


def test_preflight_previews_cache_but_requires_marker_and_explicit_reuse(app):
    service=app.state.spatial
    with TestClient(app) as c:
        api,s,command=prepare(service,c);_,machine=register(c,api,command)
        s.authorized.clear();s.machine_frame=None;s.saved_machine=machine
        reply=c.post(api+'/frames',json=frame(number=3,action='holder.slide')).json()
        assert reply['preflight']['can_start'] and reply['preflight']['has_cached_machine']
        assert not reply['target_ready'] and reply['visual'] is None
        assert c.post(api+'/reuse',json={'confirmed':False}).status_code==422
        assert c.post(api+'/reuse',json={'confirmed':True}).status_code==200
        reply=c.post(api+'/frames',json=frame(number=4,action='holder.slide')).json()
        assert reply['target_ready'] and s.machine_frame['frame_id']==machine['frame_id']
        assert reply['visual']['text_labels']==[]
        instruction=reply['visual']['display']['instruction']
        assert instruction['anchor']=='operation_target' and len(instruction['position_m'])==3
        s.frames[s.last]['pose']=None
        assert c.post(api+'/reuse',json={'confirmed':True}).status_code==409
