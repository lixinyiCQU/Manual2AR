"""SAM3.1 image-only initializer, isolated process releases all VRAM before Cutie.

Uses the pinned Ultralytics interactive image predictor, never its video tracker.
"""
from pathlib import Path
from time import perf_counter
import argparse
import json
import os
import numpy as np
from PIL import Image
from ..artifacts import dump,validate_targets,file_digest
from .initialization import select_candidate,save_initialization


def segment(job,predictor_factory=None,torch_module=None):
    if torch_module is None:import torch as torch_module
    torch=torch_module
    if not torch.cuda.is_available():raise RuntimeError('CUDA required; CPU fallback is disabled')
    if predictor_factory is None:
        import ultralytics
        sources=json.loads(Path(__file__).with_name('sam31_sources.json').read_text())
        if ultralytics.__version__!=sources['ultralytics_version']:raise RuntimeError('Ultralytics version differs from pinned source')
        from ultralytics.models.sam import SAM3Predictor
        predictor_factory=SAM3Predictor
    image=Path(job['image']);output=Path(job['output']);output.mkdir(parents=True,exist_ok=True)
    checkpoint=Path(job['checkpoint'])
    if not checkpoint.is_file():raise FileNotFoundError('SAM3.1 checkpoint missing')
    targets=validate_targets(job['targets']);width,height=Image.open(image).size
    dtype=job.get('precision','float16')
    if dtype not in ('float16','float32'):raise ValueError('SAM3.1 image precision must be float16 or float32')
    torch.cuda.reset_peak_memory_stats();started=perf_counter()
    predictor=predictor_factory(overrides=dict(model=str(checkpoint),device=0,imgsz=1008,quantize=16 if dtype=='float16' else None,
        task='segment',mode='predict',save=False,verbose=False,compile=False,retina_masks=True))
    predictor.setup_model(verbose=False);torch.cuda.synchronize();load_ms=(perf_counter()-started)*1000
    if str(predictor.torch_dtype)!='torch.'+dtype:raise RuntimeError('Requested initializer precision was not applied')
    t0=perf_counter();predictor.set_image(str(image));torch.cuda.synchronize();encode_ms=(perf_counter()-t0)*1000
    masks=[];scores=[];candidates=[];decode_ms=0
    for target in targets:
        box=np.asarray([target['bbox_0_1000']],np.float32)*[width,height,width,height]/1000
        point=np.asarray([[target['target_point_0_1000']]],np.float32)*[width,height]/1000
        t0=perf_counter()
        with torch.inference_mode():
            predicted,boxes=predictor.inference_features(predictor.features,(height,width),dst_shape=predictor.imgsz,
                bboxes=box,points=point,labels=[[1]],multimask_output=True)
        torch.cuda.synchronize();decode_ms+=(perf_counter()-t0)*1000
        if predicted is None:raise ValueError('SAM3.1 returned no initialization mask')
        mask,best,values=select_candidate(predicted.detach().cpu().numpy(),boxes[:,4].detach().float().cpu().numpy(),height,width)
        masks.append(mask);scores.append(values[best]);candidates.append(dict(component_id=target['component_id'],selected_mask=best,scores=values))
    metadata=dict(initializer='ultralytics_sam31_image',initializer_precision=dtype,internal_image_size=list(predictor.imgsz),
        checkpoint_sha256=file_digest(checkpoint),input_sha256=file_digest(image),
        model_load_ms=load_ms,image_encode_ms=encode_ms,prompt_decode_ms=decode_ms,
        initialization_ms=encode_ms+decode_ms,peak_allocated_bytes=torch.cuda.max_memory_allocated(),
        peak_reserved_bytes=torch.cuda.max_memory_reserved(),candidates=candidates,
        prompt_policy='frozen Qwen Max box+positive point; multimask argmax model score',
        implementation='SAM3.1 checkpoint interactive image head only; no Multiplex tracking in this initializer')
    value=save_initialization(output,targets,masks,scores,metadata)
    if any(not m.any() for m in masks):raise ValueError('SAM3.1 selected an empty initial mask; inspect initialization.json')
    return value


def main():
    parser=argparse.ArgumentParser();parser.add_argument('job');args=parser.parse_args()
    job=json.loads(Path(args.job).read_text());output=Path(job['output'])
    os.environ['YOLO_CONFIG_DIR']=str(output/'ultralytics_settings');os.environ['YOLO_AUTOINSTALL']='false'
    try:segment(job)
    except Exception as error:
        dump(output/'initializer_failure.json',dict(error_type=type(error).__name__,message=str(error)[:1000]))
        raise


if __name__=='__main__':main()
