"""Explicit human review may supplement ONLY the normal toolhead corner occlusion."""
import json
import pytest
from tests.backend.inspection.test_pipeline import env,inspect,observation,frame,FakeTracker


def eligible(vlm):
    vlm.value=observation(False);vlm.value.update(coverage='partial',surface_assessment='uncertain',view_issues=['toolhead_upper_left'],visible_surface_assessment='clear')


def confirm(env,result,**change):
    data={'check_id':result['check_id'],'inspection_source_sha256':result['source_sha256'],'confirmed':True,**change}
    return env[0].post(env[1]+'/confirm-occlusion',json=data)


def test_normal_corner_occlusion_requires_user_and_remains_partial_in_evidence(env):
    eligible(env[2]);result=inspect(env)
    assert result['decision']['status']=='insufficient_evidence'
    assert result['public_result']['status']=='needs_user_confirmation'
    assert result['public_result']['requires_occlusion_confirmation']
    approved=confirm(env,result);assert approved.status_code==200,approved.text
    data=approved.json();assert data['decision']['status']=='no_visible_anomaly'
    assert data['public_result']['occlusion_confirmed'] and not data['public_result']['requires_occlusion_confirmation']
    assert not data['decision']['clear_checks']['full_surface_visible']
    assert data['public_result']['status']=='no_visible_anomaly'
    assert data['decision']['manual_confirmation']['type']=='toolhead_upper_left'
    # A later tracking frame uses the current image hash, but approval remains
    # tied to the original checked image, never to an arbitrary camera frame.
    tracked=env[0].post(env[1]+'/frames',json=frame(2,result['check_id'])).json()
    assert tracked['public_result']['occlusion_confirmed']
    assert '人工确认' in env[0].get(env[1]+'/report').text or '本次检查未见明显异常' in env[0].get(env[1]+'/report').text


@pytest.mark.parametrize('changes',[
 {'view_issues':['toolhead_upper_left','glare']},{'view_issues':['cropped']},
 {'view_issues':['other_occlusion']},{'view_issues':[]},
 {'visible_surface_assessment':'uncertain'}, {'surface_assessment':'anomaly'},
 {'confidence':.3},{'coverage':'uncertain'},
])
def test_other_view_failures_cannot_be_overridden(env,changes):
    eligible(env[2]);env[2].value.update(changes);result=inspect(env)
    assert not result['public_result']['requires_occlusion_confirmation']
    assert confirm(env,result).status_code==409


def test_detected_object_or_uncertain_candidate_blocks_confirmation(env):
    eligible(env[2]);env[2].value['anomalies']=observation()['anomalies'];result=inspect(env)
    assert confirm(env,result).status_code==409
    env[2].value['anomalies'][0]['on_plate']='uncertain'
    second=env[0].post(env[1]+'/inspect',json=frame(2)).json()
    assert not second['public_result']['requires_occlusion_confirmation']
    assert confirm(env,second).status_code==409


def test_reused_plate_and_stale_confirmation_are_separated(env):
    eligible(env[2]);first=inspect(env)
    assert confirm(env,first,inspection_source_sha256='0'*64).status_code==409
    assert confirm(env,first,confirmed=False).status_code==422
    env[4].tracker_factory=lambda _:FakeTracker(fail=['build_plate'])
    second=env[0].post(env[1]+'/inspect',json=frame(2)).json()
    assert second['segmentation_skipped'] and second['public_result']['requires_occlusion_confirmation']
    assert confirm(env,first).status_code==409 and confirm(env,second).status_code==200


def test_new_object_revokes_pending_confirmation_and_earlier_manual_pass(env):
    eligible(env[2]);result=inspect(env);assert confirm(env,result).status_code==200
    tracker=env[3][-1];tracker.shared_masks['build_plate'][60:90,210:240]=False
    env[0].post(env[1]+'/frames',json=frame(2,result['check_id']))
    changed=env[0].post(env[1]+'/frames',json=frame(3,result['check_id'])).json()
    assert changed['public_result']['status']=='scene_changed'
    assert not changed['public_result']['requires_occlusion_confirmation']
    assert not changed['public_result']['occlusion_confirmed']
    assert confirm(env,result).status_code==409
    tracker.shared_masks['build_plate'][60:90,210:240]=True
    removed=env[0].post(env[1]+'/frames',json=frame(4,result['check_id'])).json()
    assert removed['public_result']['status']=='recheck_required'


def test_tracking_loss_pauses_confirmation_in_both_api_and_public_ui(env):
    eligible(env[2]);initial=inspect(env);env[3][-1].lost=True
    result=env[0].post(env[1]+'/frames',json=frame(2,initial['check_id'])).json()
    assert not result['public_result']['requires_occlusion_confirmation']
    assert result['public_result']['status']=='recheck_required'
    assert confirm(env,initial).status_code==409
