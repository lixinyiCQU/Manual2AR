"""Source-bound unboxing expansion and moving-part pose lifetime regressions."""
import json
import uuid
import pytest
from fastapi.testclient import TestClient
from manual2ar.modules.guidance.server import create_app
from manual2ar.modules.guidance.spatial.models import Begin,Save,Author
from tests.backend.guidance.test_spatial import app,begin,frame,NoVLM,calibration


def fixture_target():
    return {'points_m':[[.09,.03,.025],[.09,-.045,.025]],'marker_id':23,'marker_length_m':.08}


def profiles(service,values):
    rig=service.profile('rigs','a1-mini');rig.parent.mkdir(parents=True,exist_ok=True);rig.write_text(json.dumps(values))
    camera=service.profile('cameras','test-webcam');camera.parent.mkdir(parents=True,exist_ok=True);camera.write_text(json.dumps(calibration()))
    return rig


def test_four_chapters_have_ten_units_and_official_verification_channels(app):
    s=app.state.spatial;plan=s.catalog();assert [c['id'] for c in plan['chapters']]==['U4','U5','U6','U7']
    assert len(plan['actions'])==10
    _,task=s.registry.resolve(plan['task_id'],plan['variant_id'])
    for action in plan['actions']:
        state=next(v for v in task.document.states if v.state_id==action['chapter_id'])
        assert state.observation_nodes[0].verification_channel==action['verification_mode']
        assert action['editorial_decomposition']
        assert all(identity in s.actions for identity in action.get('invalidates_actions',[]))
    assert len(s.actions['zlock.remove']['target_instances'])==4
    assert len(s.actions['bed.tighten']['target_instances'])==3
    assert s.actions['toolhead.tie']['kind']=='cut'
    assert s.actions['packing.foam']['kind']=='highlight'


@pytest.mark.parametrize('action,target,kind,label',[
    ('zlock.remove','fourth','fasten','限制螺丝 4'),
    ('toolhead.tie','main','cut','工具头运输扎带'),
    ('packing.foam','rail','highlight','导轨保护泡棉'),
    ('bed.tighten','third','fasten','热床螺丝 3')])
def test_new_actions_have_independent_visible_replay_targets(app,action,target,kind,label):
    with TestClient(app) as c:
        api=begin(c);result=c.post(api+'/frames',json=frame(action=action,target_id=target))
        assert result.status_code==200,result.text
        result=result.json();assert result['visual']['kind']==kind and result['visual']['label']==label
        assert result['target_ready']
        if kind=='highlight':assert len(result['lines'])==1 and not result['visual']['trajectory']


def test_bed_tightening_never_calls_vlm_or_claims_torque_verified(app):
    with TestClient(app) as c:
        api=begin(c)
        r=c.post(api+'/verify',json={'action_id':'bed.tighten','client_frame_id':1})
        assert r.status_code==409 and '人工确认' in r.json()['detail']
        event={'event_id':uuid.uuid4().hex,'name':'user_marked','action_id':'bed.tighten','client_frame_id':0}
        assert c.post(api+'/events',json=event).json()['operation_verified'] is False
        assert not app.state.guidance.meta


def test_authoring_one_new_position_does_not_authorize_unconfirmed_old_positions(app):
    s=app.state.spatial;profiles(s,{'holder.slide':fixture_target()})
    identity=s.begin(Begin(visual_client_revision="machine-workframe-v1",camera_id='test-webcam',reuse_targets=False))['session_id'];session=s.sessions[identity];session.u7_checks={'base':{'status':'completed','basis':'controlled geometry fixture'}}
    candidate=uuid.uuid4().hex;session.candidates[candidate]={**fixture_target(),'action_id':'purge.slide','target_id':'main'}
    s.save(identity,Save(candidate_id=candidate,confirmed=True))
    with TestClient(app) as c:
        api='/api/guidance/spatial/sessions/'+identity
        old=c.post(api+'/frames',json=frame(action='holder.slide')).json()
        new=c.post(api+'/frames',json=frame(number=2,action='purge.slide')).json()
        assert not old['target_configured'] and not old['target_ready']
        assert new['target_ready']


def test_user_reported_toolhead_movement_invalidates_related_points_persistently(app):
    s=app.state.spatial;rig=profiles(s,{key:fixture_target() for key in ['toolhead.tie','toolhead.slide','holder.slide']});original=rig.read_bytes()
    with TestClient(app) as c:
        api=begin(c,'camera',u7_fixture_verified=True,reuse_targets=True)
        for i in [1,2]:assert c.post(api+'/frames',json=frame(number=i,action='toolhead.tie')).status_code==200
        identity=api.rsplit('/',1)[-1];candidate=uuid.uuid4().hex
        s.sessions[identity].candidates[candidate]={**fixture_target(),'action_id':'toolhead.tie','target_id':'main','target_epoch':''}
        moved=c.post(api+'/frames',json=frame(number=3,action='toolhead.slide')).json()
        event={'event_id':uuid.uuid4().hex,'name':'user_marked','action_id':'toolhead.slide','client_frame_id':3,'source_sha256':moved['source_sha256']}
        result=c.post(api+'/events',json=event).json();assert result['relocation_required'] and not result['operation_verified']
        stale_candidate=c.post(api+'/targets/confirm',json={'candidate_id':candidate,'confirmed':True})
        assert stale_candidate.status_code==409 and '设置期间' in stale_candidate.json()['detail']
        stale=c.post(api+'/targets',json={'action_id':'toolhead.tie','first_frame':1,'second_frame':2,'first_points':[{'x':100,'y':100},{'x':130,'y':130}],'second_points':[{'x':120,'y':100},{'x':150,'y':130}]})
        assert stale.status_code==409 and '移动前' in stale.json()['detail']
        blocked=c.post(api+'/frames',json=frame(number=4,action='toolhead.tie')).json()
        assert blocked['state']=='relocation_required' and blocked['visual'] is None and blocked['requires_relocation']
        unaffected=c.post(api+'/frames',json=frame(number=5,action='holder.slide')).json()
        assert unaffected['target_ready']
    assert rig.read_bytes()==original
    restarted=create_app(s.config,NoVLM())
    with TestClient(restarted) as c:
        api=begin(c,'camera',u7_fixture_verified=True,reuse_targets=True)
        assert c.post(api+'/frames',json=frame(action='toolhead.tie')).json()['state']=='relocation_required'


def test_replay_movement_never_invalidates_physical_rig_profiles(app,tmp_path):
    with TestClient(app) as c:
        api=begin(c)
        r=c.post(api+'/events',json={'event_id':uuid.uuid4().hex,'name':'user_marked','action_id':'toolhead.slide','client_frame_id':0})
        assert r.json()['relocation_required']
    assert not app.state.spatial.profile('rig-validity','a1-mini').exists()
