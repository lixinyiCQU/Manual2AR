"""Fixed SAM3.1 image initializer + Cutie memory; bounded, measured GPU work."""
from contextlib import nullcontext
from pathlib import Path
from time import perf_counter
import gc
import importlib.util
import json
import subprocess
import sys
import tempfile
import numpy as np
from PIL import Image
from ..artifacts import dump,file_digest
from .initialization import exclusive_initial_masks


def cutie_config_dir(package):
    for location in package.__path__:
        folder=Path(location)/'config'
        if (folder/'eval_config.yaml').is_file():return folder.resolve()
    raise FileNotFoundError('Cutie config/eval_config.yaml missing')


def available(config):
    try:
        import torch
        if not torch.cuda.is_available():return False,'CUDA unavailable'
        for name in ('ultralytics','cutie'):
            if importlib.util.find_spec(name) is None:return False,'Missing package: '+name
        for name in ('sam3_checkpoint','cutie_checkpoint'):
            if not Path(config[name]).is_file():return False,'Missing checkpoint: '+name
        return True,None
    except ImportError:return False,'PyTorch unavailable'


def resolved_precision(config,torch):
    precision=config['precision']
    if precision=='auto':
        return 'bfloat16' if torch.cuda.get_device_capability()[0]>=8 and torch.cuda.is_bf16_supported() else 'float16'
    if precision not in ('float32','float16','bfloat16'):raise ValueError('Invalid Cutie precision')
    return precision


class Models:
    def __init__(self,config):
        self.config=config;self.network=None;self.cfg=None;self.info=None

    def context(self):
        import torch
        precision=resolved_precision(self.config,torch)
        return nullcontext() if precision=='float32' else torch.autocast('cuda',dtype=getattr(torch,precision))

    def ensure_loaded(self):
        import torch
        if self.network is not None:return 0.
        ready,reason=available(self.config)
        if not ready:raise RuntimeError(reason)
        from cutie.model.cutie import CUTIE
        from cutie.inference.utils.args_utils import get_dataset_cfg
        from hydra import initialize_config_dir,compose
        from omegaconf import open_dict
        import cutie
        started=perf_counter()
        with initialize_config_dir(str(cutie_config_dir(cutie)),version_base='1.3.2'):
            cfg=compose(config_name='eval_config')
        get_dataset_cfg(cfg)
        tuning=self.config['cutie']
        with open_dict(cfg):
            cfg.weights=self.config['cutie_checkpoint'];cfg.mem_every=tuning['mem_every'];cfg.use_long_term=tuning['use_long_term']
        network=CUTIE(cfg).cuda().eval()
        network.load_weights(torch.load(cfg.weights,map_location='cpu',weights_only=True))
        if tuning['channels_last']:network.pixel_encoder.to(memory_format=torch.channels_last)
        if tuning['compile_encoder']:
            # Only this shape-stable path; Cutie's recurrent memory stays eager.
            network.encode_image=torch.compile(network.encode_image,mode='reduce-overhead')
        torch.cuda.synchronize()
        lock=Path(self.config.get('environment_lock','gpu_environment.lock.json'))
        self.info=dict(engine='sam31-cutie-stream-v2',device=torch.cuda.get_device_name(),torch=torch.__version__,cuda=torch.version.cuda,
            precision=resolved_precision(self.config,torch),cutie_settings=tuning,
            checkpoint_sha256={key:file_digest(self.config[key]) for key in ('sam3_checkpoint','cutie_checkpoint')},
            adapter_sha256={p.name:file_digest(p) for p in Path(__file__).parent.glob('*.py')},
            environment=json.loads(lock.read_text()) if lock.exists() else None)
        self.network,self.cfg=network,cfg
        return (perf_counter()-started)*1000

    def processor(self):
        from cutie.inference.inference_core import InferenceCore
        processor=InferenceCore(self.network,cfg=self.cfg)
        processor.max_internal_size=self.config['cutie']['max_internal_size']
        return processor

    def propagate(self,processor,image,initial=None):
        import torch
        torch.cuda.synchronize();started=perf_counter()
        with torch.inference_mode(),self.context():
            transfer=perf_counter();tensor=torch.from_numpy(np.ascontiguousarray(image)).permute(2,0,1).cuda().float()/255
            torch.cuda.synchronize();h2d_ms=(perf_counter()-transfer)*1000
            initial_tensor=None if initial is None else torch.from_numpy(np.stack(initial).astype(np.float32)).cuda()
            begin=torch.cuda.Event(enable_timing=True);end=torch.cuda.Event(enable_timing=True)
            begin.record()
            if initial_tensor is None:prob=processor.step(tensor)
            else:prob=processor.step(tensor,initial_tensor,objects=list(range(1,len(initial)+1)),idx_mask=False)
            end.record();end.synchronize();forward_ms=begin.elapsed_time(end)
            if not torch.isfinite(prob).all():raise ValueError('Nonfinite Cutie probabilities; choose float32 and re-test')
            download=perf_counter();labels=processor.output_prob_to_mask(prob).cpu().numpy();torch.cuda.synchronize()
            d2h_ms=(perf_counter()-download)*1000
        return labels,dict(infer_ms=(perf_counter()-started)*1000,h2d_ms=h2d_ms,gpu_forward_ms=forward_ms,d2h_ms=d2h_ms,
            precision=resolved_precision(self.config,torch),allocated_bytes=torch.cuda.memory_allocated(),reserved_bytes=torch.cuda.memory_reserved(),
            peak_allocated_bytes=torch.cuda.max_memory_allocated(),peak_reserved_bytes=torch.cuda.max_memory_reserved())

    def start(self,image,targets):
        import torch
        started=perf_counter()
        # Initialization is isolated from Cutie imports and releases its own CUDA
        # context on exit. Only one session is allowed by the default service.
        folder=Path(self.config['log_root'])/'initializations';folder.mkdir(parents=True,exist_ok=True)
        dest=Path(tempfile.mkdtemp(prefix='sam31_',dir=folder));Image.fromarray(image).save(dest/'input.png')
        job=dict(image=str((dest/'input.png').resolve()),output=str(dest.resolve()),checkpoint=str(Path(self.config['sam3_checkpoint']).resolve()),
            targets=targets,precision='float16')
        dump(dest/'job.json',job)
        t0=perf_counter()
        with (dest/'initializer.log').open('w') as log:
            subprocess.run([sys.executable,'-m','manual2ar_inference.engines.sam31_image',str(dest/'job.json')],check=True,
                timeout=self.config.get('initialization_timeout_seconds',300),stdout=log,stderr=subprocess.STDOUT)
        initialize_ms=(perf_counter()-t0)*1000
        evidence=json.loads((dest/'initialization.json').read_text())
        initial=[np.array(Image.open(dest/'initial'/(t['component_id']+'.png')))>127 for t in targets]
        initial,overlap_policy=exclusive_initial_masks(initial)
        dump(dest/'exclusive_initialization.json',overlap_policy)
        # Never silently seed an erased instance into persistent memory.
        # Raw input retention is opt-in; masks and timings remain reproducible.
        if not self.config.get('retain_initial_images',False):(dest/'input.png').unlink()
        if any(not m.any() for m in initial):raise ValueError('An initial instance disappeared after overlap resolution')
        load_ms=self.ensure_loaded();processor=self.processor();torch.cuda.reset_peak_memory_stats()
        labels,timing=self.propagate(processor,image,initial)
        state=dict(processor=processor,targets=targets)
        return state,{t['component_id']:labels==i for i,t in enumerate(targets,1)},dict(**timing,model_load_ms=load_ms,
            initialize_ms=initialize_ms,total_initialize_ms=(perf_counter()-started)*1000,model_info=self.info,
            sam_initial_scores={x['component_id']:x['model_score'] for x in evidence['targets']},initialization=evidence,exclusive_initialization=overlap_policy,
            quality_scope='SAM estimates and area gates are not human-validated semantic accuracy')

    def step(self,session,image):
        labels,metrics=self.propagate(session['processor'],image)
        return {t['component_id']:labels==i for i,t in enumerate(session['targets'],1)},metrics

    def close(self,session):
        session.clear()
        gc.collect()
