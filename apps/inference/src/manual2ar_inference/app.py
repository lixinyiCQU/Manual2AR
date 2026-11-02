"""Serialized GPU operations, persistent per-session Cutie memory and idle expiry."""
from contextlib import asynccontextmanager
from pathlib import Path
from time import monotonic,perf_counter
import asyncio
import hmac
import json
import os
import threading
import uuid
from types import SimpleNamespace
from datetime import datetime,timezone

import numpy as np
from fastapi import Body,Depends,FastAPI,Header,HTTPException,Query
from manual2ar_contracts.gpu import PROTOCOL,Start,Frame,decode_image,decode_jpeg,encode_labels,targets_sha
from .engines.engine import Models,available


def create_app(config,engine=None):
    token=config['api_token']
    if len(token)<24:raise ValueError('Set a random service token of at least 24 characters')
    if not 1<=config['maximum_sessions']<=8 or not 10<=config['session_idle_seconds']<=3600:raise ValueError('Invalid session limits')
    if engine is None:
        tune=config['cutie']
        if tune['max_internal_size'] not in (-1,256,320,480,640) or tune['mem_every'] not in (5,10):raise ValueError('Invalid Cutie performance preset')
    lock=threading.RLock();sessions={};model=engine if engine is not None else Models(config)
    log_root=Path(config['log_root']);log_root.mkdir(parents=True,exist_ok=True)

    def log(event,**data):
        with (log_root/'events.jsonl').open('a',encoding='utf-8') as file:
            file.write(json.dumps(dict(utc=datetime.now(timezone.utc).isoformat(),event=event,**data),ensure_ascii=False)+'\n')

    def drop(identity,reason):
        state=sessions.pop(identity,None)
        if state is not None:model.close(state['engine']);log('session.close',session_id=identity,reason=reason)

    def sweep():
        now=monotonic()
        for identity,state in list(sessions.items()):
            if now-state['last_active']>config['session_idle_seconds']:drop(identity,'idle_timeout')

    @asynccontextmanager
    async def lifespan(app):
        async def clean_idle():
            while True:
                await asyncio.sleep(10)
                await asyncio.to_thread(expire)
        def expire():
            with lock:sweep()
        task=asyncio.create_task(clean_idle())
        try:yield
        finally:
            task.cancel()
            try:await task
            except asyncio.CancelledError:pass
            with lock:
                for identity in list(sessions):drop(identity,'service_shutdown')

    def authorize(authorization:str=Header(default='')):
        if not hmac.compare_digest(authorization,'Bearer '+token):raise HTTPException(401,'Invalid GPU service token')

    app=FastAPI(title='Module-one SAM3.1 + Cutie',docs_url=None,redoc_url=None,openapi_url=None,lifespan=lifespan,dependencies=[Depends(authorize)])
    app.state.sessions=sessions

    def decode(request):
        try:return decode_image(request)
        except Exception:raise HTTPException(400,'Invalid JPEG or source fingerprint')

    def response(identity,state,request,masks,metrics,started):
        h,w=state['shape']; expected={t['component_id'] for t in state['targets']}
        if set(masks)!=expected or any(np.asarray(m).shape!=(h,w) for m in masks.values()):raise ValueError('Model mask contract mismatch')
        encoding=perf_counter();encoded=encode_labels(masks)
        metrics={**metrics,'mask_encode_ms':(perf_counter()-encoding)*1000,'gpu_request_ms':(perf_counter()-started)*1000}
        value=dict(protocol=PROTOCOL,session_id=identity,frame_id=request.frame_id,source_sha256=request.source_sha256,
            targets_sha256=state['targets_sha256'],width=w,height=h,label_map=encoded,metrics=metrics)
        log('frame.complete',session_id=identity,frame_id=request.frame_id,source_sha256=request.source_sha256,
            mask_pixels={key:int(np.asarray(mask).astype(bool).sum()) for key,mask in masks.items()},metrics=metrics)
        state.update(last_active=monotonic(),frame_id=request.frame_id,last_sha=request.source_sha256,last_response=value)
        return value

    @app.get('/health')
    def health():
        ready,reason=(True,None) if engine is not None else available(config)
        return dict(protocol=PROTOCOL,available=ready,reason=reason,engine='sam31-cutie-stream-v2',
            models_loaded=getattr(model,'network',None) is not None,maximum_sessions=config['maximum_sessions'],initialization_policy='smaller-visible-instances-first-v1')

    @app.post('/v1/ping')
    def ping(body:bytes=Body(default=b'',media_type='application/octet-stream')):
        from fastapi.responses import Response
        if len(body)>131072:raise HTTPException(413,'Probe too large')
        return Response(body,media_type='application/octet-stream')

    @app.post('/v1/warmup')
    def warmup():
        if not lock.acquire(blocking=False):raise HTTPException(409,'GPU busy')
        try:
            elapsed=model.ensure_loaded() if engine is None else 0
            return dict(model_load_ms=elapsed,model_info=getattr(model,'info',None))
        finally:lock.release()

    @app.post('/v1/sessions',status_code=201)
    def start(request:Start):
        entered=perf_counter();image=decode(request);decode_ms=(perf_counter()-entered)*1000
        if not lock.acquire(blocking=False):raise HTTPException(429,'GPU busy; retry initialization')
        try:
            sweep()
            if len(sessions)>=config['maximum_sessions']:raise HTTPException(429,'Close an older GPU session')
            identity=uuid.uuid4().hex;targets=[t.model_dump() for t in request.targets];started=perf_counter();state=None
            try:
                session,masks,metrics=model.start(image,targets)
                state=dict(engine=session,shape=image.shape[:2],targets=targets,targets_sha256=targets_sha(targets),last_active=monotonic())
                metrics['jpeg_decode_ms']=decode_ms
                value=response(identity,state,request,masks,metrics,started);sessions[identity]=state
                return value
            except Exception as error:
                if state:model.close(state['engine'])
                log('model.error',stage='initialize',error_type=type(error).__name__)
                raise HTTPException(503,'SAM3.1/Cutie initialization failed; inspect GPU log')
        finally:lock.release()

    @app.post('/v1/sessions/{identity}/frames')
    def step(identity:str,request:Frame):
        entered=perf_counter();image=decode(request)
        return advance(identity,request,image,(perf_counter()-entered)*1000)

    @app.post('/v1/sessions/{identity}/frames/jpeg')
    def jpeg_step(identity:str,body:bytes=Body(media_type='image/jpeg'),frame_id:int=Query(ge=1,le=1000000),source_sha256:str=Query(pattern=r'^[a-f0-9]{64}$')):
        if len(body)>2000000:raise HTTPException(413,'JPEG too large')
        request=SimpleNamespace(frame_id=frame_id,source_sha256=source_sha256)
        entered=perf_counter()
        try:image=decode_jpeg(body,source_sha256)
        except Exception:raise HTTPException(400,'Invalid JPEG or fingerprint')
        return advance(identity,request,image,(perf_counter()-entered)*1000)

    def advance(identity,request,image,decode_ms=0):
        if not lock.acquire(blocking=False):raise HTTPException(409,'GPU busy; submit a fresh frame after completion')
        try:
            sweep();state=sessions.get(identity)
            if state is None:raise HTTPException(404,'GPU session expired; recognize again')
            if request.frame_id==state['frame_id'] and request.source_sha256==state['last_sha']:return state['last_response']
            if request.frame_id!=state['frame_id']+1:raise HTTPException(409,'Out-of-order GPU frame')
            if image.shape[:2]!=state['shape']:raise HTTPException(409,'Frame dimensions changed; recognize again')
            started=perf_counter()
            try:
                masks,metrics=model.step(state['engine'],image)
                metrics['jpeg_decode_ms']=decode_ms
                return response(identity,state,request,masks,metrics,started)
            except Exception as error:
                drop(identity,'model_error');log('model.error',stage='tracking',error_type=type(error).__name__)
                raise HTTPException(503,'Cutie memory invalidated after inference error; recognize again')
        finally:lock.release()

    @app.delete('/v1/sessions/{identity}',status_code=204)
    def close(identity:str):
        with lock:drop(identity,'client_close')

    return app


def main():
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--work-dir',type=Path,default=Path.cwd())
    args=parser.parse_args()
    config=json.loads(args.config.read_text())
    for key in ('sam3_checkpoint','cutie_checkpoint','log_root'):
        config[key]=str((args.work_dir/config[key]).resolve())
    config['environment_lock']=str(args.work_dir/'gpu_environment.lock.json')
    if len(config.get('api_token',''))<24:raise ValueError('Set a private api_token of at least 24 characters in the inference config file')
    import uvicorn
    uvicorn.run(create_app(config),host=config['host'],port=config['port'])


if __name__=='__main__':main()
