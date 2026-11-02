"""Novel mask holes are provisional scene changes, never semantic proof."""
import numpy as np
from manual2ar.modules.inspection.scene_watch import PlateSceneWatch

def plate():
    mask=np.zeros((240,320),bool);mask[12:228,16:304]=True;return mask

def test_new_hole_needs_two_frames_and_is_removed_with_current_evidence():
    watch=PlateSceneWatch();mask=plate();watch.prime({'build_plate':mask})
    mask[80:110,210:240]=False
    assert watch.update({'build_plate':mask})==[]
    proposals=watch.update({'build_plate':mask})
    assert len(proposals)==1 and proposals[0]['label_code']=='unclassified_object'
    assert proposals[0]['bbox_0_1000']==[656,333,750,458]
    assert watch.update({'build_plate':plate()})==[]

def test_known_object_holes_and_initial_holes_are_not_new_instances():
    mask=plate();mask[80:110,210:240]=False
    known=np.zeros_like(mask);known[80:110,210:240]=True
    watch=PlateSceneWatch();watch.prime({'build_plate':mask,'foreign_object_1':known})
    for _ in range(3):assert watch.update({'build_plate':mask,'foreign_object_1':known})==[]
    # When the semantic track is gone, the gap is now unexplained.
    assert watch.update({'build_plate':mask})==[]
    assert len(watch.update({'build_plate':mask}))==1
    watch.prime({'build_plate':mask})
    for _ in range(3):assert watch.update({'build_plate':mask})==[]

def test_open_edge_notch_missing_plate_and_disabled_watch_do_not_invent_targets():
    mask=plate();mask[12:45,140:170]=False
    watch=PlateSceneWatch();watch.prime({'build_plate':plate()})
    for _ in range(3):assert watch.update({'build_plate':mask})==[]
    assert watch.update({})==[]
    watch=PlateSceneWatch({'scene_watch_enabled':False});mask[80:120,210:240]=False
    for _ in range(3):assert watch.update({'build_plate':mask})==[]

def test_multiple_initial_cutouts_remain_background_context():
    mask=plate()
    for x in [50,100,150,200]:mask[70:85,x:x+15]=False
    watch=PlateSceneWatch();watch.prime({'build_plate':mask})
    for _ in range(3):assert watch.update({'build_plate':mask})==[]
