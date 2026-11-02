"""Replay the failure mechanism: correct SAM masks lost to their larger plate."""
import numpy as np
from types import SimpleNamespace
from manual2ar.modules.inspection.tracker import InspectionTracker
from manual2ar_inference.engines.initialization import exclusive_initial_masks
from tests.backend.inspection.test_pipeline import config


def test_disjoint_memory_preserves_nested_foreground_and_original_identity_order():
    plate=np.zeros((120,160),bool);plate[5:115,5:155]=True
    obj=np.zeros_like(plate);obj[40:80,50:100]=True
    residue=np.zeros_like(plate);residue[20:23,80:95]=True
    masks=[plate,obj,residue]
    # Equal foreground probabilities in overlapping memory select the plate's
    # first object ID, reproducing the observed disappearing-foreground failure.
    raw=np.argmax(np.stack([np.zeros_like(plate),*masks]),axis=0)
    assert not (raw==2).any() and not (raw==3).any()
    exclusive,metrics=exclusive_initial_masks(masks)
    labels=np.argmax(np.stack([np.zeros_like(plate),*exclusive]),axis=0)
    assert (labels==2).sum()==obj.sum() and (labels==3).sum()==residue.sum()
    assert (labels==1).sum()==plate.sum()-obj.sum()-residue.sum()
    assert not np.any(np.sum(exclusive,axis=0)>1) and metrics['overlap_pixels']==obj.sum()+residue.sum()
    assert np.array_equal(masks[0],plate)  # Raw evidence is unchanged.


def test_local_foreground_first_order_supports_running_legacy_gpu(monkeypatch,tmp_path):
    tracker=InspectionTracker('opencv',config());tracker.provider='sam31_cutie';seen=[]
    tracker.engine=SimpleNamespace(prepare=lambda image,items,*args:seen.extend(c.component_id for c in items))
    items=[SimpleNamespace(component_id='build_plate',bbox_0_1000=[0,0,1000,1000]),SimpleNamespace(component_id='foreign_object_1',bbox_0_1000=[20,20,300,300]),SimpleNamespace(component_id='residue_2',bbox_0_1000=[40,40,60,80])]
    tracker.prepare(b'image',items,tmp_path,None,0)
    assert seen==['residue_2','foreign_object_1','build_plate']
    assert items[0].component_id=='build_plate'


def test_known_unlocalized_object_is_not_relabelled_as_new_unknown():
    from manual2ar.modules.inspection.scene_watch import PlateSceneWatch
    plate=np.zeros((240,320),bool);plate[12:228,16:304]=True
    watch=PlateSceneWatch({'scene_watch_enabled':True,'scene_candidate_confirm_frames':2})
    watch.prime({'build_plate':plate},[{'kind':'foreign_object','found':True,'tracking_ready':False,'bbox_0_1000':[350,350,600,600]}])
    changed=plate.copy();changed[90:135,120:180]=False
    assert watch.update({'build_plate':changed})==[]
    assert watch.update({'build_plate':changed})==[]
    changed[50:75,230:255]=False
    watch.update({'build_plate':changed});assert len(watch.update({'build_plate':changed}))==1
