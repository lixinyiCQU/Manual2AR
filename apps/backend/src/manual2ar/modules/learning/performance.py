"""Bounded evidence jobs, compact masks and reproducible latency summaries."""
from concurrent.futures import ThreadPoolExecutor,wait
from threading import BoundedSemaphore
from pathlib import Path
import base64,csv,json
import cv2
import numpy as np
from manual2ar_contracts.gpu import encode_labels

_POOL=ThreadPoolExecutor(max_workers=1,thread_name_prefix='learning-evidence')
_SLOTS=BoundedSemaphore(2)


def sample_without_io_lock(value,image):
    with value.log.lock:
        if value.log.frames>=value.log.settings['max_sample_frames']:return None
        value.log.frames+=1;index=value.log.frames
    folder=value.log.path/'tracking'/f'{index:05d}'
    folder.mkdir(parents=True);(folder/'input.jpg').write_bytes(image)
    return folder


def submit_evidence(value,job):
    if not _SLOTS.acquire(blocking=False):
        value.log.event('performance.evidence_dropped',{'reason':'bounded_writer_busy'});return False
    def work():
        from time import perf_counter
        started=perf_counter()
        try:job()
        except Exception as error:value.log.event('performance.evidence_error',{'error_type':type(error).__name__})
        finally:
            value.log.event('performance.evidence_written',{'elapsed_ms':(perf_counter()-started)*1000})
            _SLOTS.release()
    jobs=[f for f in getattr(value,'evidence_jobs',[]) if not f.done()]
    jobs.append(_POOL.submit(work));value.evidence_jobs=jobs
    return True


def flush_evidence(value):wait(getattr(value,'evidence_jobs',[]))


def pack_reply(reply,masks=None):
    """Only accepted masks travel to the frontend. No duplicate per-object PNGs."""
    selected={}
    for row in reply['results']:
        if not row.get('tracking_ready'):continue
        tracked=row.get('tracked');key=row['component_id']
        if not tracked:continue
        if masks is not None:
            mask=np.asarray(masks[key],bool)
        else:
            body=base64.b64decode(tracked['overlay_png_base64'])
            im=cv2.imdecode(np.frombuffer(body,np.uint8),cv2.IMREAD_UNCHANGED)
            if im is None:raise ValueError('Missing initial mask')
            roi=tracked.get('mask_roi_xywh')
            mask=im[:,:,3]>0 if im.ndim==3 else im>0
            if roi:
                canvas=np.zeros((tracked['mask_frame_height'],tracked['mask_frame_width']),bool)
                x,y,w,h=roi;canvas[y:y+h,x:x+w]=mask;mask=canvas
        selected[key]=mask
    if selected:
        h,w=next(iter(selected.values())).shape
        reply['label_map']={**encode_labels(selected),'width':w,'height':h}
    else:reply['label_map']=None
    for row in reply['results']:
        if row.get('tracked'):row['tracked']['overlay_png_base64']=''
    return reply


def percentile(values,p):
    clean=[float(v) for v in values if isinstance(v,(int,float)) and np.isfinite(v)]
    return round(float(np.percentile(clean,p)),3) if clean else None


def summarize(events):
    """Durations only cross clock domains as differences measured on one host."""
    joins={};windows=[]
    for event in events:
        kind=event.get('event');fid=event.get('client_frame_id')
        if kind=='frontend.performance':windows.append(event)
        if fid is not None:
            row=joins.setdefault(fid,{})
            if kind=='learning.input':row['input']=event
            elif kind=='learning.response':row['response']=event
            elif kind=='frontend.render':row['render']=event
    rows=[]
    for fid,group in joins.items():
        inp=group.get('input',{});response=group.get('response',{});render=group.get('render',{});batch=response.get('batch_metrics',{})
        cloud=batch.get('http_roundtrip_ms');gpu=batch.get('gpu_request_ms')
        rows.append(dict(client_frame_id=fid,stage=inp.get('stage'),source_sha256=inp.get('source_sha256'),
            source_identity_ok=bool(render) and render.get('source_sha256')==inp.get('source_sha256'),
            backend_ms=response.get('elapsed_ms'),request_ms=render.get('request_ms'),frame_age_ms=render.get('frame_age_ms'),
            capture_encode_ms=render.get('capture_encode_ms'),overlay_apply_ms=render.get('overlay_apply_ms'),
            stale_rejected=render.get('stale_rejected',False),cloud_roundtrip_ms=cloud,gpu_request_ms=gpu,
            cloud_residual_ms=max(0,cloud-gpu) if isinstance(cloud,(int,float)) and isinstance(gpu,(int,float)) else None,
            gpu_forward_ms=batch.get('gpu_forward_ms'),infer_ms=batch.get('infer_ms'),jpeg_decode_ms=batch.get('jpeg_decode_ms'),
            mask_encode_ms=batch.get('mask_encode_ms'),backend_encode_ms=batch.get('backend_encode_ms'),
            upload_bytes=batch.get('upload_bytes'),download_bytes=batch.get('download_bytes'),precision=batch.get('precision')))
    steady=[x for x in rows if x['stage']=='tracking']
    metrics={key:dict(p50=percentile([x.get(key) for x in steady],50),p95=percentile([x.get(key) for x in steady],95))
        for key in ['backend_ms','request_ms','frame_age_ms','capture_encode_ms','overlay_apply_ms','cloud_roundtrip_ms','gpu_request_ms','cloud_residual_ms','gpu_forward_ms','infer_ms','backend_encode_ms']}
    return dict(schema='learning-performance-v1',requests=rows,steady_frames=len(steady),latency_ms=metrics,
        frontend_windows=windows,stale_rejected=sum(x['stale_rejected'] for x in steady),
        caveats=['cloud_residual includes transport, JSON, JPEG decode, client mask decode and scheduling; it is not one-way network latency',
            'render receipt means textures applied, not GPU presentation; capture time is Unity acquisition time, not sensor exposure time',
            'no IoU or accuracy without human ground truth; historical reports lack render FPS and cannot establish Unity rendering rate'])


def write_report(folder,events):
    folder=Path(folder);result=summarize(events)
    (folder/'performance_summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    rows=result['requests']
    if rows:
        with (folder/'performance_frames.csv').open('w',encoding='utf-8-sig',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    return result


def main():
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('runs',nargs='+',type=Path);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    results=[]
    for path in args.runs:
        events=[json.loads(line) for line in (path/'events.jsonl').read_text().splitlines() if line.strip()]
        results.append(dict(run=path.name,**summarize(events)))
    args.output.mkdir(parents=True,exist_ok=True)
    (args.output/'comparison.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    columns=['run','steady_frames','frame_age_ms_p50','frame_age_ms_p95','cloud_roundtrip_ms_p50','infer_ms_p50','stale_rejected']
    with (args.output/'comparison.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=columns);writer.writeheader()
        for result in results:
            writer.writerow(dict(run=result['run'],steady_frames=result['steady_frames'],stale_rejected=result['stale_rejected'],
                **{key:result['latency_ms'][key.rsplit('_',1)[0]][key.rsplit('_',1)[1]] for key in columns[2:-1]}))
    print(args.output/'comparison.csv')


if __name__=='__main__':main()
