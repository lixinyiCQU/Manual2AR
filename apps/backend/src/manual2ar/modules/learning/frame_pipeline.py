"""Module-one batched frames; legacy component/plate/guidance routes are untouched."""
from time import perf_counter
import base64
import cv2
import numpy as np
from fastapi import HTTPException
from manual2ar.infrastructure.diagnostics import metadata, dump, save_masks
from .performance import submit_evidence,pack_reply,sample_without_io_lock


def sampled_masks(folder, image, rows):
    """Expand ROI masks only for sampled evidence, not on the hot response path."""
    expanded=[]
    for row in rows:
        tracked=row.get('tracked')
        if tracked is not None and tracked.overlay_png_base64 and tracked.mask_roi_xywh:
            x,y,w,h=tracked.mask_roi_xywh
            roi=cv2.imdecode(np.frombuffer(base64.b64decode(tracked.overlay_png_base64),np.uint8),cv2.IMREAD_UNCHANGED)
            canvas=np.zeros((tracked.mask_frame_height,tracked.mask_frame_width,4),np.uint8)
            canvas[y:y+h,x:x+w]=roi
            _,png=cv2.imencode('.png',canvas,[cv2.IMWRITE_PNG_COMPRESSION,1])
            tracked=tracked.model_copy(update={'overlay_png_base64':base64.b64encode(png).decode()})
        expanded.append({**row,'tracked':tracked})
    save_masks(folder,image,expanded)


def process_frame(value, image, client_frame_id):
    if not value.lock.acquire(blocking=False):
        raise HTTPException(409,'Run busy; send the next fresh frame after this request')
    try:
        if value.closed:
            raise HTTPException(409,'Run closed')
        if client_frame_id <= getattr(value,'last_tracking_client_frame',-1):
            raise HTTPException(409,'Out-of-order frame rejected')
        started=perf_counter()
        value.last_tracking_client_frame=client_frame_id
        value.frame+=1
        sessions=list(value.sessions)
        output=value.tracker.update_many(sessions,image) if sessions else {}
        shared=getattr(value.tracker.engine,'shared_masks',None)
        rows=[]
        for session in sessions:
            identity=value.sessions[session]
            tracked=output[session]
            ready=(tracked.status=='tracking' and tracked.mask_quality_passed and (bool(tracked.overlay_png_base64) or bool(shared and value.sessions[session] in shared)))
            retained=tracked.retained_for_recovery
            row=dict(component_id=identity,session_id=session,tracked=tracked,tracking_ready=ready,
                retained_for_recovery=retained,stage=tracked.tracking_state,
                error=None if ready else ';'.join(tracked.mask_quality_reasons))
            if not ready and not retained:
                value.tracker.close(session)
                value.sessions.pop(session,None)
                value.log.event('tracking.lost',dict(frame_id=value.frame,component_id=identity,reason=row['error']))
            elif retained:
                value.log.event('learning.tracking_uncertain',dict(frame_id=value.frame,component_id=identity,reason=row['error']))
            value.log.event('tracking.component',dict(frame_id=value.frame,check_id=value.check,
                **{k:v for k,v in row.items() if k!='tracked'},mask=metadata(tracked)))
            rows.append(row)
        batch=value.tracker.local.last_batch_metrics
        value.log.event('learning.tracking_batch',dict(frame_id=value.frame,client_frame_id=client_frame_id,**batch))
        # Evidence IO runs in a globally bounded worker. Masks belong to this
        # frame; no worker reads a mutable tracker state after the next update.
        evidence_started=perf_counter()
        wire_rows=[{k:(v.model_dump() if k=='tracked' and v else v) for k,v in row.items()} for row in rows]
        reply=dict(frame_id=value.frame,check_id=value.check,results=wire_rows,active_sessions=len(value.sessions))
        encode_started=perf_counter()
        compact=shared is not None and value.tracker.config.get('performance',{}).get('compact_masks',True)
        if compact:pack_reply(reply,shared)
        encode_ms=(perf_counter()-encode_started)*1000
        if started-value.last_sample>=value.log.settings['sample_interval_seconds']:
            value.last_sample=started
            frame_index=value.frame;check=value.check;frozen_reply=dict(reply)
            # Capture bounded, already encoded evidence; no per-object hot-path re-encoding.
            def evidence():
                sample=sample_without_io_lock(value,image)
                if sample:
                    label=frozen_reply.get('label_map')
                    if label:(sample/'labels.png').write_bytes(base64.b64decode(label['png_base64']))
                    else:sampled_masks(sample,image,rows)
                    dump(sample/'metrics.json',dict(frame_id=frame_index,check_id=check,components=[
                        {k:(metadata(v) if k=='tracked' and v else v) for k,v in row.items()} for row in rows],
                        labels=label['labels'] if label else None))
            if value.tracker.config.get('performance',{}).get('evidence_async',True):submit_evidence(value,evidence)
            else:evidence()
        reply.update(elapsed_ms=round((perf_counter()-started)*1000,2),
            batch_metrics={**batch,'backend_encode_ms':round(encode_ms,3),'evidence_submit_ms':round((perf_counter()-evidence_started)*1000,3)})
        return reply
    finally:
        value.lock.release()
