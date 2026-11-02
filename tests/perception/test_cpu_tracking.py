"""Behavioral regressions for moving, hidden and mismatched camera frames."""
from pathlib import Path
import sys
sys.path[:0]=[str(Path(__file__).resolve().parents[2]),str(Path(__file__).resolve().parents[2])]
import base64
from unittest.mock import patch
import cv2
import numpy as np
import pytest
from manual2ar_contracts.perception import GuidanceTarget
from manual2ar_perception.cpu_tracker import CpuLearningTracker


def encode(image):
    return cv2.imencode('.jpg',image,[cv2.IMWRITE_JPEG_QUALITY,95])[1].tobytes()


def scene():
    rng=np.random.default_rng(51)
    image=np.full((240,360,3),190,np.uint8)
    texture=rng.integers(20,235,(80,96,3),dtype=np.uint8)
    image[75:155,65:161]=cv2.GaussianBlur(texture,(3,3),0.5)
    mask=np.zeros(image.shape[:2],np.uint8);mask[75:155,65:161]=255
    return image,mask


def initialized(settings=None):
    image,mask=scene()
    tracker=CpuLearningTracker(settings)
    tracker.external_masks={'toolhead':mask}
    session,tracked=tracker.start(encode(image),'intro_toolhead',[181,312,447,646],
        GuidanceTarget(expected_component_id='intro_toolhead',target_point_0_1000=[310,480],
            expected_area_ratio_min=0.001,expected_area_ratio_max=0.5))
    assert tracked.mask_quality_passed
    return tracker,session,image,mask


def translated(image,dx):
    return cv2.warpAffine(image,np.float32([[1,0,dx],[0,1,0]]),(image.shape[1],image.shape[0]),borderValue=(190,190,190))


def test_motion_can_leave_initial_semantic_box_without_mutating_evidence():
    tracker,session,image,mask=initialized()
    initial=tracker._states[session].semantic_box
    for dx in range(6,85,6):
        tracked=tracker.update(session,encode(translated(image,dx)))
        assert tracked.status=='tracking',tracked.motion_diagnostics
    assert tracker._states[session].semantic_box==initial
    assert tracker.motion[session].initial_point==[310,480]
    assert tracked.bbox_0_1000[0]>380
    assert tracked.motion_diagnostics['current_motion_box_pixels'][0][0]>initial[0]+70


def test_uncertain_mask_is_hidden_and_short_occlusion_recovers():
    tracker,session,image,_=initialized()
    t0=tracker.motion[session].last_accepted
    blank=np.full_like(image,190)
    hidden=tracker.update_many([session],encode(blank),now=t0+0.1)[session]
    assert hidden.tracking_state=='recovering'
    assert hidden.retained_for_recovery and not hidden.overlay_png_base64
    recovered=tracker.update_many([session],encode(translated(image,4)),now=t0+0.3)[session]
    assert recovered.status=='tracking',recovered.motion_diagnostics
    assert recovered.relocalization_count==1


def test_expired_recovery_cannot_reappear_on_a_late_good_frame():
    tracker,session,image,_=initialized({'recovery_seconds':0.3})
    t0=tracker.motion[session].last_accepted
    tracker.update_many([session],encode(np.full_like(image,190)),now=t0+0.1)
    late=tracker.update_many([session],encode(image),now=t0+0.5)[session]
    assert late.tracking_state=='lost' and not late.retained_for_recovery
    assert not late.overlay_png_base64


def test_scene_cut_is_not_reported_as_valid_tracking():
    tracker,session,image,_=initialized()
    changed=np.random.default_rng(99).integers(0,255,image.shape,dtype=np.uint8)
    result=tracker.update(session,encode(changed))
    assert result.status=='lost' and not result.mask_quality_passed
    assert result.mask_quality_reasons


def test_one_frame_decode_and_two_lk_calls_for_multiple_objects():
    tracker,session,image,mask=initialized()
    tracker.external_masks['x_axis']=mask
    other,_=tracker.start(encode(image),'intro_x_axis',[181,312,447,646],
        GuidanceTarget(expected_component_id='intro_x_axis',target_point_0_1000=[310,480],
            expected_area_ratio_min=0.001,expected_area_ratio_max=0.5))
    with patch.object(tracker,'_decode',wraps=tracker._decode) as decode,patch.object(cv2,'calcOpticalFlowPyrLK',wraps=cv2.calcOpticalFlowPyrLK) as lk:
        output=tracker.update_many([session,other],encode(translated(image,5)))
    assert all(t.status=='tracking' for t in output.values())
    assert decode.call_count==1
    assert lk.call_count==2


def test_roi_mask_roundtrip_preserves_global_position():
    tracker,session,image,_=initialized()
    result=tracker.update(session,encode(translated(image,5)))
    x,y,w,h=result.mask_roi_xywh
    roi=cv2.imdecode(np.frombuffer(base64.b64decode(result.overlay_png_base64),np.uint8),cv2.IMREAD_UNCHANGED)
    assert roi.shape==(h,w,4)
    full=np.zeros((result.mask_frame_height,result.mask_frame_width),np.uint8)
    full[y:y+h,x:x+w]=roi[:,:,3]
    actual=tracker._states[session].mask>0
    assert np.array_equal(full>0,actual)


def test_frame_size_change_requires_new_initialization():
    tracker,session,image,_=initialized()
    result=tracker.update(session,encode(cv2.resize(image,(180,120))))
    assert result.tracking_state=='lost' and not result.retained_for_recovery
    assert 'frame_dimensions_changed' in result.mask_quality_reasons


def test_textureless_region_does_not_receive_synthetic_tracking_points():
    tracker,session,image,_=initialized()
    state=tracker._states[session]
    state.gray[:]=128
    state.points=tracker._points(state.gray,state.mask)
    result=tracker.update(session,encode(np.full_like(image,128)))
    assert not result.mask_quality_passed
    assert 'insufficient_trackable_points' in result.mask_quality_reasons


def test_cpu_setting_bounds_are_checked():
    with pytest.raises(ValueError):
        CpuLearningTracker({'minimum_inlier_ratio':0.1})
    with pytest.raises(ValueError):
        CpuLearningTracker({'target_fps':float('nan')})


def test_low_texture_surface_uses_its_silhouette_without_accepting_blank_occlusion():
    previous=np.full((120,160),210,np.uint8)
    mask=np.zeros_like(previous);mask[30:90,40:110]=255
    previous[mask>0]=90
    matrix=np.float32([[1,0,5],[0,1,0]])
    current=cv2.warpAffine(previous,matrix,(160,120),borderValue=210)
    correlation,support=CpuLearningTracker._appearance(previous,current,mask,matrix)
    assert correlation>0.99 and support=='silhouette_1px'
    correlation,_=CpuLearningTracker._appearance(previous,np.full_like(previous,90),mask,matrix)
    assert correlation is None
