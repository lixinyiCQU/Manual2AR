"""Teaching models must reuse calibrated geometry and explicit target lifetimes."""
import numpy as np
import pytest
from fastapi.testclient import TestClient
from manual2ar.modules.guidance.spatial.visuals import compose
from manual2ar_perception.spatial import project
from tests.backend.guidance.test_spatial import app, begin, frame, calibration, pose


@pytest.mark.parametrize('action,asset,motion',[
    ('zlock.remove','hex_key','loosen'),
    ('toolhead.tie','scissors','cut'),
    ('toolhead.slide','movement_arrow','translate'),
    ('holder.base','hex_key','tighten'),
    ('holder.slide','movement_arrow','translate')])
def test_mesh_placement_matches_authoring_and_frozen_camera(app,action,asset,motion):
    service=app.state.spatial;c=calibration();matrix=np.array(c['matrix']);distortion=np.array([.1,-.02,.003,.004,0.])
    points=np.array([[.06,.04,.01],[.1,-.04,.10]])
    camera=pose(20)
    result=compose(service.actions[action],'测试目标',points,camera,matrix,distortion)
    assert result['asset']['asset_id']==asset and result['asset']['motion']==motion
    transform=np.array(result['asset']['marker_from_asset']).reshape(4,4)
    origin=points[0] if motion=='translate' else points[1]
    assert np.allclose(transform[:3,3],origin)
    # Local +Y must point from authored handle/start towards target, not screen-left.
    assert np.allclose(transform[:3,1]/np.linalg.norm(transform[:3,1]),(points[1]-points[0])/np.linalg.norm(points[1]-points[0]))
    assert np.linalg.det(transform[:3,:3])>0
    assert np.allclose(np.array(result['projection']['camera_from_marker']).reshape(4,4),camera)
    projected=project([points[1]],camera,matrix,distortion)[0]
    assert np.allclose([result['anchor']['x'],result['anchor']['y']],projected)
    assert result['illustrative_only']
    if motion=='translate':assert np.allclose(origin+result['asset']['translation_m'],points[1])


def test_u4_four_screws_get_distinct_asset_tips_and_frame_identity(app):
    with TestClient(app) as client:
        api=begin(client);tips=[]
        for number,target in enumerate(['main','second','third','fourth'],1):
            r=client.post(api+'/frames',json=frame(number=number,action='zlock.remove',target_id=target)).json()
            assert r['target_ready'] and r['target_id']==target and r['client_frame_id']==number
            tips.append(np.array(r['visual']['asset']['marker_from_asset']).reshape(4,4)[:3,3])
        assert len({tuple(p) for p in tips})==4
        assert not app.state.guidance.meta


def test_foam_does_not_invent_shape_or_unboxing_motion(app):
    s=app.state.spatial;c=calibration()
    result=compose(s.actions['packing.foam'],'工具头泡棉',[[.09,.03,.025],[.09,-.045,.025]],pose(0),np.array(c['matrix']),np.zeros(5))
    assert result['kind']=='highlight' and result['asset'] is None and not result['trajectory']


def test_legacy_actions_keep_their_previous_visual_contract(app):
    with TestClient(app) as client:
        api=begin(client)
        r=client.post(api+'/frames',json=frame(action='purge.slide')).json()
        assert r['visual']['asset'] is None and r['visual']['projection'] is None
        assert len(r['visual']['trajectory'])==33


def test_invalid_axis_cannot_generate_asset(app):
    s=app.state.spatial;c=calibration()
    with pytest.raises(ValueError,match='Invalid authored'):
        compose(s.actions['zlock.remove'],'螺丝',[[0,0,0],[0,0,0]],pose(0),np.array(c['matrix']),np.zeros(5))


def test_replay_left_move_is_horizontal_without_changing_real_rig(app):
    from manual2ar.modules.guidance.spatial.simulation import targets
    samples=targets(app.state.spatial.actions)
    start,end=np.asarray(samples['toolhead.slide']['points_m'])
    assert end[0]<start[0] and np.allclose(start[1:],end[1:])
    assert not app.state.spatial.profile('rigs','a1-mini').exists()


def test_u7_screws_are_independent_and_tighten_not_loosen(app):
    with TestClient(app) as client:
        api=begin(client);results=[]
        for number,target in enumerate(['main','second'],1):
            r=client.post(api+'/frames',json=frame(number=number,action='holder.base',target_id=target)).json()
            assert r['target_ready'] and r['visual']['asset']['motion']=='tighten'
            results.append(r['visual']['asset']['marker_from_asset'])
        assert results[0]!=results[1]
        assert not app.state.guidance.meta


def test_u7_setup_guides_use_visible_points_and_localized_prompt(app):
    from manual2ar.modules.guidance.spatial.localization import prompt_for
    for key in ['holder.base','holder.slide']:
        action=app.state.spatial.actions[key]
        assert len(action['authoring_points'])==2 and action['capture_guidance'] and action['ready_hint']
        prompt=prompt_for(action,action['target_instances'][0])
        assert action['localization_context'] in prompt and 'NOT installation verification' in prompt
        assert 'unseen' in prompt and 'occluded' in prompt
    assert '螺丝中心' in app.state.spatial.actions['holder.base']['authoring_points'][1]
    assert '上端' in app.state.spatial.actions['holder.slide']['authoring_points'][0]


def test_u7_replay_has_downward_path_and_never_writes_physical_profile(app):
    from manual2ar.modules.guidance.spatial.simulation import targets
    values=targets(app.state.spatial.actions)
    start,end=np.asarray(values['holder.slide']['points_m'])
    assert start[1]>end[1] and np.allclose(start[[0,2]],end[[0,2]])
    assert not app.state.spatial.profile('rigs','a1-mini').exists()
