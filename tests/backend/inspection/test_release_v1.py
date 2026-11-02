"""V1: plate-scoped removal and clean rechecks without SAM initialization."""
import copy,json
import numpy as np
import pytest
from tests.backend.inspection.test_pipeline import env,inspect,observation,frame,FakeTracker
from manual2ar_contracts.gpu import decode_labels
from manual2ar.modules.inspection.plate_scope import disjoint_boxes


def move(tracker,key,box):
    tracker.sessions[key]=box
    m=np.zeros((240,320),bool);a,b,c,d=box;m[b*240//1000:d*240//1000,a*320//1000:c*320//1000]=True
    tracker.shared_masks[key]=m


def track(env,initial,index=2):
    response=env[0].post(env[1]+'/frames',json=frame(index,initial['check_id']))
    assert response.status_code==200,response.text
    return response.json()


@pytest.mark.parametrize('box',[[960,350,999,600],[0,350,40,600],[350,0,600,40],[350,960,600,999]])
def test_outside_any_current_plate_edge_is_removed_and_not_drawn(env,box):
    first=inspect(env);move(env[3][-1],'foreign_object_1',box);result=track(env,first)
    assert result['decision']['status']=='known_anomalies_removed'
    assert result['public_result']['status']=='known_anomalies_removed'
    assert result['public_result']['foreign_object_state']=='removed'
    assert result['tracking_state']=='tracking'
    item=result['objects'][1];assert item['plate_relation']=='outside' and not item['tracking_ready'] and item['tracker_ready']
    assert 'foreign_object_1' not in decode_labels(result['label_map'],320,240)
    assert result['decision']['snapshot_semantic_anomaly_ids']==['foreign_object_1'] and result['decision']['semantic_anomaly_ids']==[]
    # An off-plate object can be forgotten without reactivating its old warning.
    env[3][-1].fail.add('foreign_object_1');later=track(env,first,3)
    assert later['decision']['status']=='known_anomalies_removed'


def test_partial_overlap_remains_on_plate_and_tracking_loss_is_not_removal(env):
    first=inspect(env);move(env[3][-1],'foreign_object_1',[900,350,999,600]);overlap=track(env,first)
    assert overlap['decision']['status']=='anomaly_detected' and overlap['objects'][1]['tracking_ready']
    env[3][-1].fail.add('foreign_object_1');lost=track(env,first,3)
    assert lost['decision']['removed_anomaly_ids']==[] and lost['decision']['status']=='anomaly_detected'


def test_returning_object_reactivates_warning(env):
    first=inspect(env);move(env[3][-1],'foreign_object_1',[960,350,999,600]);assert track(env,first)['decision']['status']=='known_anomalies_removed'
    move(env[3][-1],'foreign_object_1',[350,350,600,600]);back=track(env,first,3)
    assert back['decision']['status']=='anomaly_detected' and back['decision']['removed_anomaly_ids']==[]
    assert back['objects'][1]['tracking_ready'] and back['public_result']['foreign_object_state']=='fail'


def test_scope_uses_current_plate_box_not_initial_vlm_box(env):
    first=inspect(env);tracker=env[3][-1]
    move(tracker,'build_plate',[100,100,500,900]);move(tracker,'foreign_object_1',[600,350,800,600])
    assert track(env,first)['decision']['status']=='known_anomalies_removed'


def test_plate_loss_cannot_prove_removal(env):
    first=inspect(env);tracker=env[3][-1];move(tracker,'foreign_object_1',[960,350,999,600]);tracker.fail.add('build_plate')
    result=track(env,first);assert result['decision']['removed_anomaly_ids']==[]
    assert result['decision']['status']=='anomaly_detected'


def test_removing_one_target_does_not_clear_remaining_residue(env):
    extra=copy.deepcopy(observation()['anomalies'][0]);extra.update(kind='residue',bbox_0_1000=[650,650,700,700],target_point_0_1000=[675,675]);env[2].value['anomalies'].append(extra)
    first=inspect(env);move(env[3][-1],'foreign_object_1',[960,350,999,600]);result=track(env,first)
    assert result['decision']['status']=='anomaly_detected' and result['public_result']['foreign_object_state']=='removed'
    assert result['public_result']['residue_state']=='fail'


def test_save_and_report_use_the_removal_frame_but_keep_original_observation(env):
    first=inspect(env);move(env[3][-1],'foreign_object_1',[960,350,999,600]);result=track(env,first)
    client,url,*_=env;assert client.post(url+'/evidence',json={'check_id':first['check_id']}).status_code==200
    root=env[4].log_root/url.rsplit('/',1)[-1];summary=json.loads((root/'evidence'/first['check_id']/'summary.json').read_text())
    assert summary['status']=='known_anomalies_removed'
    assert json.loads((root/first['check_id']/'decision.json').read_text())['status']=='anomaly_detected'
    assert json.loads((root/first['check_id']/'resolution.json').read_text())['decision']['removed_anomaly_ids']==['foreign_object_1']
    html=client.get(url+'/report').text;assert '已移出打印板' in html and '/resolution.jpg' in html
    assert client.get(url+'/'+first['check_id']+'/resolution.jpg').status_code==200


def test_clean_recheck_reuses_only_plate_tracking_and_never_prepares_or_starts(env):
    first=inspect(env);tracker=env[3][-1]
    def forbidden(*a):raise AssertionError('Clean recheck must not initialize segmentation')
    tracker.prepare=tracker.start=forbidden;env[2].value=observation(False)
    second=env[0].post(env[1]+'/inspect',json=frame(2)).json()
    assert second['segmentation_skipped'] and second['segmentation_ms']==0
    assert second['decision']['status']=='no_visible_anomaly' and second['active_tracks']==1
    assert second['objects'][0]['segmentation_status']=='reused_tracking'
    assert 'foreign_object_1' in tracker.closed and second['check_id']!=first['check_id']


def test_clean_recheck_without_usable_old_track_returns_semantics_without_sam(env):
    inspect(env);env[3][-1].fail.add('build_plate');env[2].value=observation(False)
    second=env[0].post(env[1]+'/inspect',json=frame(2)).json()
    assert second['segmentation_skipped'] and second['segmentation_ms']==0
    assert second['decision']['status']=='no_visible_anomaly' and second['active_tracks']==0
    assert second['label_map'] is None and second['public_result']['visual_state']=='not_required'
    assert not second['decision']['clear_checks']['plate_boundary_mask_usable']
    assert second['decision']['clear_checks']['plate_localization_usable']


@pytest.mark.parametrize('change',[{'confidence':.2},{'surface_assessment':'uncertain'},{'coverage':'partial','view_issues':['glare']}])
def test_skipping_segmentation_is_not_automatic_clearance(env,change):
    inspect(env);env[2].value=observation(False);env[2].value.update(change)
    second=env[0].post(env[1]+'/inspect',json=frame(2)).json()
    assert second['segmentation_skipped'] and second['decision']['status']=='insufficient_evidence'
    if change.get('surface_assessment')=='uncertain':assert second['public_result']['foreign_object_state']=='unknown'


def test_candidate_still_triggers_segmentation(env):
    inspect(env);env[2].value['anomalies'][0]['on_plate']='uncertain'
    second=env[0].post(env[1]+'/inspect',json=frame(2)).json()
    assert not second['segmentation_skipped'] and second['decision']['status']=='insufficient_evidence'


def test_unknown_new_object_blocks_removed_completion_until_recheck(env):
    first=inspect(env);tracker=env[3][-1];move(tracker,'foreign_object_1',[960,350,999,600]);tracker.shared_masks['build_plate'][60:90,210:240]=False
    track(env,first);changed=track(env,first,3)
    assert changed['public_result']['status']=='scene_changed'
    tracker.shared_masks['build_plate'][60:90,210:240]=True
    assert track(env,first,4)['public_result']['status']=='recheck_required'
