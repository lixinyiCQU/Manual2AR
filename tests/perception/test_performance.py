"""Performance contracts with fake cloud models and real HTTP serialization."""
import base64,json,threading
from types import SimpleNamespace
from pathlib import Path
import numpy as np
import pytest
from manual2ar_contracts.gpu import encode_labels,decode_labels
from manual2ar.modules.learning.performance import summarize,submit_evidence,flush_evidence
from manual2ar_inference.engines.engine import resolved_precision


def test_label_map_roundtrip_and_unknown_id_rejection():
    masks={'x_axis':np.zeros((20,30),bool),'toolhead':np.zeros((20,30),bool)}
    masks['x_axis'][1:3,1:5]=True;masks['toolhead'][5:10,6:12]=True
    value=encode_labels(masks);decoded=decode_labels(value,30,20)
    assert all(np.array_equal(decoded[key],masks[key]) for key in masks)
    value['labels'][0]['label_id']=7
    with pytest.raises(ValueError):decode_labels(value,30,20)
    with pytest.raises(ValueError):decode_labels(encode_labels(masks),31,20)


def test_label_map_rejects_overlap():
    mask=np.ones((20,30),bool)
    with pytest.raises(ValueError,match='overlap'):encode_labels({'a':mask,'b':mask})


def test_perf_statistics_exclude_initialization_and_do_not_mix_clock_domains():
    events=[]
    for fid,stage,age,cloud,gpu_time in [(1,'locate',10000,9900,9000),(2,'tracking',700,600,100),(3,'tracking',900,800,100)]:
        events.extend([dict(event='learning.input',client_frame_id=fid,stage=stage,source_sha256='abc',capture_time_ms=1e20),
            dict(event='learning.response',client_frame_id=fid,batch_metrics=dict(http_roundtrip_ms=cloud,gpu_request_ms=gpu_time)),
            dict(event='frontend.render',client_frame_id=fid,frame_age_ms=age,source_sha256='abc',stale_rejected=fid==3)])
    result=summarize(events)
    assert result['latency_ms']['frame_age_ms']['p50']==800
    assert result['latency_ms']['cloud_residual_ms']['p50']==600
    assert result['steady_frames']==2 and result['stale_rejected']==1
    assert all(row['source_identity_ok'] for row in result['requests'])


def test_bounded_evidence_drops_without_blocking_and_flushes():
    class Log:
        def __init__(self):self.events=[]
        def event(self,name,data):self.events.append((name,data))
    value=SimpleNamespace(log=Log());gate=threading.Event()
    try:
        assert submit_evidence(value,lambda:gate.wait(5))
        assert submit_evidence(value,lambda:None)
        assert not submit_evidence(value,lambda:pytest.fail('Bounded queue must not execute this task'))
        assert any(x[0]=='performance.evidence_dropped' for x in value.log.events)
    finally:gate.set();flush_evidence(value)
    assert sum(x[0]=='performance.evidence_written' for x in value.log.events)==2


def test_auto_precision_uses_fp16_on_t4_and_records_fp32_override():
    torch=SimpleNamespace(cuda=SimpleNamespace(get_device_capability=lambda:(7,5),is_bf16_supported=lambda:True))
    assert resolved_precision(dict(precision='auto'),torch)=='float16'
    assert resolved_precision(dict(precision='float32'),torch)=='float32'
    torch.cuda.get_device_capability=lambda:(8,6)
    assert resolved_precision(dict(precision='auto'),torch)=='bfloat16'


def test_selected_sam31_adapter_preserves_box_point_and_mask_identity(tmp_path):
    from PIL import Image
    from manual2ar_inference.engines.sam31_image import segment
    from contextlib import nullcontext
    class Tensor:
        def __init__(self,data):self.data=np.asarray(data)
        def detach(self):return self
        def cpu(self):return self
        def float(self):return self
        def numpy(self):return self.data
        def __getitem__(self,key):return Tensor(self.data[key])
    observed=[]
    class Predictor:
        torch_dtype='torch.float16';imgsz=[1008,1008];features={}
        def __init__(self,overrides):assert overrides['quantize']==16
        def setup_model(self,verbose):pass
        def set_image(self,path):pass
        def inference_features(self,features,shape,**kwargs):
            observed.append(kwargs)
            masks=np.zeros((2,120,160),bool);masks[1,24:96,32:112]=True
            boxes=np.zeros((2,6));boxes[:,4]=[.1,.9]
            return Tensor(masks),Tensor(boxes)
    cuda=SimpleNamespace(is_available=lambda:True,synchronize=lambda:None,reset_peak_memory_stats=lambda:None,
        max_memory_allocated=lambda:10,max_memory_reserved=lambda:20)
    torch=SimpleNamespace(cuda=cuda,inference_mode=nullcontext)
    image=tmp_path/'image.png';Image.new('RGB',(160,120)).save(image);checkpoint=tmp_path/'sam3.1_multiplex.pt';checkpoint.write_bytes(b'fake')
    targets=[dict(component_id=key,bbox_0_1000=[200,200,700,800],target_point_0_1000=[450,500]) for key in ['toolhead']]
    result=segment(dict(image=str(image),checkpoint=str(checkpoint),output=str(tmp_path/'output'),targets=targets),Predictor,torch)
    assert result['targets'][0]['model_score']==.9 and result['targets'][0]['component_id']=='toolhead'
    np.testing.assert_allclose(observed[0]['bboxes'],[[32,24,112,96]])
    np.testing.assert_allclose(observed[0]['points'],[[[72,60]]])
    assert Image.open(tmp_path/'output/initial/toolhead.png').getpixel((40,40))==255
