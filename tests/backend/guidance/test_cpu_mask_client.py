"""CPU mask adapter: actual GrabCut, moving objects, loss and GPU handover."""
import cv2
import numpy as np
from manual2ar.integrations.perception.cpu_client import CpuMaskClient


def encode(image):
    return cv2.imencode('.jpg',image,[cv2.IMWRITE_JPEG_QUALITY,95])[1].tobytes()


def scene():
    image=np.full((240,360,3),210,np.uint8)
    rng=np.random.default_rng(17)
    image[65:145,50:130]=rng.integers(15,120,(80,80,3),dtype=np.uint8)
    image[160:210,230:320]=rng.integers(20,100,(50,90,3),dtype=np.uint8)
    targets=[{'component_id':'spool_holder_base','bbox_0_1000':[139,271,361,604],'target_point_0_1000':[250,440]},
             {'component_id':'external_spool_holder','bbox_0_1000':[639,667,889,875],'target_point_0_1000':[760,770]}]
    return image,targets


def test_actual_grabcut_two_parts_track_motion_and_hide_occlusion():
    image,targets=scene();client=CpuMaskClient()
    masks,_=client.start(encode(image),targets)
    assert all(mask.sum()>2000 for mask in masks.values())
    moved=cv2.warpAffine(image,np.float32([[1,0,8],[0,1,0]]),(360,240),borderValue=(210,210,210))
    tracked,_=client.step(encode(moved),1)
    for name,mask in masks.items():
        assert tracked[name].any()
        assert abs(np.nonzero(tracked[name])[1].mean()-np.nonzero(mask)[1].mean()-8)<2
    hidden,_=client.step(encode(np.full_like(image,210)),2)
    assert all(not mask.any() for mask in hidden.values())
    client.close();assert not client.tracker._states and not client.sessions


def test_gpu_handover_uses_last_positions_not_original_vlm_boxes():
    image,targets=scene();image=np.roll(image,100,axis=1)
    mask=np.zeros((240,360),bool);mask[65:145,150:230]=True
    client=CpuMaskClient()
    initial,_=client.start(encode(image),targets[:1],{'spool_holder_base':mask})
    assert initial['spool_holder_base'].any()
    assert np.array_equal(initial['spool_holder_base'],mask)
    moved=np.roll(image,5,axis=1)
    result,_=client.step(encode(moved),1)
    assert result['spool_holder_base'].any()
    assert abs(np.nonzero(result['spool_holder_base'])[1].mean()-194.5)<2
    client.close()
