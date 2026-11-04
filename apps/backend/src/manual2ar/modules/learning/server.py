"""Module-one API: cited knowledge, static originals, recognition and paired tracking."""
from contextlib import asynccontextmanager
from datetime import datetime,timezone
from pathlib import Path
from time import time
import base64
import hashlib
import json
import re
import threading
import uuid
from fastapi import Body,FastAPI, HTTPException,Query
from fastapi.responses import FileResponse, HTMLResponse, Response
from pydantic import BaseModel,Field,model_validator,AliasChoices
from .manage import public
from .recognition import create_pipeline,ImageRequest,LocateRequest
from manual2ar.infrastructure.diagnostics import dump
from .knowledge import KnowledgeStore
from manual2ar.integrations.perception.provider import LearningTracker
from .frame_pipeline import process_frame
from . import telemetry
from .performance import pack_reply,flush_evidence

EXTENSIONS={'.png','.jpg','.jpeg','.webp','.bmp','.tif','.tiff'}


class Begin(BaseModel):
    provider:str=Field(default='sam31_cutie',pattern=r'^(auto|opencv|sam31_cutie)$')
    source:str=Field(default='camera',pattern=r'^(camera|static)$')


class Frame(BaseModel):
    image_base64:str|None=Field(default=None,max_length=16000000)
    source_image_id:str|None=Field(default=None,max_length=64)
    client_frame_id:int=Field(default=1,ge=1,le=10000000)
    expected_source_sha256:str|None=Field(default=None,pattern=r'^[a-f0-9]{64}$',validation_alias=AliasChoices('expected_source_sha256','source_sha256'))
    capture_time_ms:float=Field(default=0,ge=0)
    @model_validator(mode='after')
    def one_source(self):
        if bool(self.image_base64)==bool(self.source_image_id):raise ValueError('Supply exactly one image source')
        if self.image_base64 and len(self.image_base64)<32:raise ValueError('Invalid image payload')
        return self


class Event(BaseModel):
    event:str=Field(pattern=r'^(camera.ready|camera.stop|input.select|provider.select|frontend.render|frontend.select|frontend.save|learning.detail|learning.source|learning.library|frontend.performance)$')
    data:dict=Field(default_factory=dict)


def create_app(config,client=None,knowledge_store=None):
    pipeline=create_pipeline(config,client)
    knowledge=knowledge_store or KnowledgeStore(config)
    states={}
    state_lock=threading.RLock()

    def static_files():
        root=Path(config['static_images']['folder']).resolve()
        paths=root.rglob('*') if config['static_images']['recursive'] else root.glob('*')
        found={}
        for p in sorted(paths):
            if not p.is_file() or p.suffix.lower() not in EXTENSIONS:continue
            try:p.resolve().relative_to(root)
            except ValueError:continue
            name=p.relative_to(root).as_posix()
            stat=p.stat()
            identity=hashlib.sha256((name+':'+str(stat.st_mtime_ns)+':'+str(stat.st_size)).encode()).hexdigest()[:24]
            found[identity]=(p,name)
            if len(found)>=config['static_images']['max_count']:break
        return found


    def static_image(identity):
        item=static_files().get(identity)
        if item is None:raise HTTPException(404,'静态图片不存在，请刷新列表')
        path,name=item
        if path.stat().st_size>12000000:raise HTTPException(413,'静态图片文件超过12MB，请先缩小原图')
        body=path.read_bytes()
        request=pipeline.ImageRequest(image_base64=base64.b64encode(body).decode())
        normalized=pipeline.image_bytes(request)
        return body,normalized,name


    def state(run):
        value=pipeline.get_run(run)
        with state_lock:
            s=states.get(run)
            if s is None:raise HTTPException(404,'会话已关闭，请重新打开输入')
            s['last_active']=time()
        return value,s


    def resolve(request):
        if request.source_image_id:
            original,normalized,name=static_image(request.source_image_id)
            if request.expected_source_sha256 and request.expected_source_sha256!=hashlib.sha256(original).hexdigest():
                raise HTTPException(409,'原始图片在预览后发生变化，请刷新并重新加载')
            return pipeline.ImageRequest(image_base64=base64.b64encode(original).decode()),{
                'source':'static','source_image_id':request.source_image_id,'source_name':name,
                'source_sha256':hashlib.sha256(original).hexdigest(),'normalized_sha256':hashlib.sha256(normalized).hexdigest()}
        image=pipeline.ImageRequest(image_base64=request.image_base64)
        normalized=pipeline.image_bytes(image)
        source_hash=hashlib.sha256(base64.b64decode(request.image_base64)).hexdigest()
        if request.expected_source_sha256 and request.expected_source_sha256!=source_hash:raise HTTPException(409,'输入帧SHA256不一致，请重新采集')
        return image,{'source':'camera','source_sha256':source_hash,
            'normalized_sha256':hashlib.sha256(normalized).hexdigest()}


    @asynccontextmanager
    async def lifespan(app):
        yield
        for identity in list(states):end(identity)
        knowledge.wiki.close()


    app=FastAPI(title='Manual2AR 模块一：部件认知',lifespan=lifespan)


    @app.get('/health')
    def health():
        ready,reason=pipeline.vision.configuration_status()
        return {'status':'ok','task':'component-learning','vlm_configured':ready,'reason':reason,
            'knowledge_revision':knowledge.revision,'cards':len(knowledge.cards),
            'default_provider':config['segmentation']['default_provider']}


    @app.get('/api/learning/config')
    def settings():return public(config)


    @app.get('/api/learning/knowledge')
    def bundle():return knowledge.bundle


    @app.get('/learning',response_class=HTMLResponse)
    def reader():return (Path(__file__).parents[2]/'knowledge/templates/reader.html').read_text(encoding='utf-8')


    def wiki_page(identity):
        try:return knowledge.wiki.page(identity)
        except KeyError:raise HTTPException(404,'页面不在当前离线快照中')


    @app.get('/api/learning/wiki/resolve')
    def wiki_resolve(url:str):
        from urllib.parse import urlsplit,unquote
        if len(url)>2048:raise HTTPException(422,'官方资料链接过长')
        try:return knowledge.wiki.destination(url,unquote(urlsplit(url).fragment))
        except (KeyError,ValueError):raise HTTPException(404,'该指南不在当前离线快照中') from None

    @app.get('/api/learning/wiki/pages/{identity}/html',response_class=HTMLResponse)
    def wiki_html(identity:str):
        wiki_page(identity)
        return HTMLResponse(knowledge.wiki.article_html(identity),headers={'X-Content-Type-Options':'nosniff'})


    @app.get('/api/learning/wiki/pages/{identity}/render')
    def wiki_render(identity:str):
        wiki_page(identity)
        return knowledge.wiki.render(identity)


    @app.get('/api/learning/wiki/pages/{identity}/tiles/{number}')
    def wiki_tile(identity:str,number:int):
        wiki_page(identity)
        rendered=knowledge.wiki.render(identity)
        if rendered['state']!='ready':raise HTTPException(409,'文章仍在准备中')
        if not 0<=number<len(rendered['tiles']):raise HTTPException(404,'页面图块不存在')
        return FileResponse(knowledge.wiki.render_folder(identity)/f'{number:04d}.jpg',media_type='image/jpeg')


    @app.get('/api/learning/wiki/assets/{identity}')
    def wiki_asset(identity:str):
        item=knowledge.wiki.assets.get(identity)
        if item is None:raise HTTPException(404,'离线附件不存在')
        mime=item['mime'] if item['mime'].startswith('image/') else 'application/octet-stream'
        return FileResponse(knowledge.wiki.object_path(item['object']),media_type=mime,headers={'X-Content-Type-Options':'nosniff'})

    @app.get('/api/learning/wiki/font')
    def wiki_font():
        return FileResponse(Path(config['knowledge']['offline_wiki']['font_file']),media_type='font/otf')


    @app.get('/api/learning/knowledge/images/{identity}')
    def photo(identity:str):
        if identity not in knowledge.images:raise HTTPException(404,'Unknown knowledge image')
        return Response(knowledge.image_bytes(identity),media_type='image/png')


    @app.get('/api/learning/evidence/{citation}')
    def quote(citation:str):
        if citation not in knowledge.sources:raise HTTPException(404,'Unknown citation')
        return knowledge.evidence(citation)


    @app.get('/api/learning/images')
    def images():
        return {'images':[{'id':i,'name':name,'preview_url':'/api/learning/images/'+i+'/preview'} for i,(p,name) in static_files().items()]}


    @app.get('/api/learning/images/{identity}/preview')
    def preview(identity:str):
        original,normalized,name=static_image(identity)
        return Response(normalized,media_type='image/jpeg',headers={'X-Source-SHA256':hashlib.sha256(original).hexdigest()})


    @app.post('/api/learning/runs',status_code=201)
    def begin(request:Begin):
        for identity,s in list(states.items()):
            if time()-s['last_active']>3600:
                end(identity)
                with state_lock:states.pop(identity,None)
        automatic=request.provider=='auto'
        selected='sam31_cutie' if automatic else request.provider
        fallback_reason=None
        if selected=='sam31_cutie':
            try:
                from manual2ar.integrations.perception.client import CutieClient
                connection=json.loads(Path(config['cutie_tracking']['connection_file']).read_text())
                probe=CutieClient(connection,timeout=3)
                try:
                    if automatic:probe.health()
                finally:probe.close()
            except Exception as error:
                if not automatic:raise HTTPException(400,'请启动共享GPU服务，并在 configs/inference.connection.local.json 放入连接文件。')
                selected='opencv';fallback_reason=type(error).__name__
        with pipeline.registry_lock:
            if len(pipeline.runs)>=32:raise HTTPException(429,'请关闭较早的演示会话')
            value=pipeline.Run(log_root=Path(config['runtime_dir'])/'learning',tracker_instance=LearningTracker(selected,config))
            value.automatic_provider=automatic
            value.provider_fallback=bool(fallback_reason)
            pipeline.runs[value.log.id]=value
        with state_lock:states[value.log.id]={'source':request.source,'provider':selected,'automatic':automatic,'last_active':time()}
        dump(value.log.path/'knowledge_snapshot.json',knowledge.bundle)
        telemetry.register(value,knowledge,selected)
        if fallback_reason:value.log.event('provider.fallback',{'stage':'connect','from':'sam31_cutie','to':'opencv','reason':fallback_reason})
        value.log.event('learning.run',{'knowledge_revision':knowledge.revision,'input_source':request.source,
            'first_mask':selected,'tracking':value.tracker.health()['tracking'],'knowledge_schema':knowledge.bundle['schema_version']})
        value.log.report()
        return {'run_id':value.log.id,'knowledge_revision':knowledge.revision,'provider':selected,'automatic':automatic,'fallback_used':value.provider_fallback}


    @app.delete('/api/learning/runs/{run}',status_code=204)
    def end(run:str):
        with pipeline.registry_lock:value=pipeline.runs.pop(run,None)
        with state_lock:states.pop(run,None)
        if value:
            value.closed=True
            def cleanup():
                with value.lock:
                    value.tracker.shutdown()
                    pipeline.close_sessions(value)
                    flush_evidence(value)
                    telemetry.report(value)
                    value.log.event('run.stop',{})
            threading.Thread(target=cleanup,name='learning-session-close',daemon=True).start()


    @app.post('/api/learning/runs/{run}/locate')
    def locate(run:str,request:Frame):
        value,s=state(run)
        ready,reason=pipeline.vision.configuration_status()
        if not ready:raise HTTPException(503,'请在 configs/app.local.json 中填写 vlm.api_key，再重启后端')
        image,source=resolve(request)
        if source['source']!=s['source']:raise HTTPException(409,'输入类型已变化，请建立新会话')
        value.log.event('learning.input',{'client_frame_id':request.client_frame_id,'stage':'locate','capture_time_ms':request.capture_time_ms,**source})
        reply=pipeline.locate(run,pipeline.LocateRequest(image_base64=image.image_base64))
        s['provider']=value.tracker.provider
        if s['provider']=='sam31_cutie' and config['performance']['compact_masks']:pack_reply(reply)
        reply.update(client_frame_id=request.client_frame_id,source_sha256=source['source_sha256'],
            first_mask_provider=s['provider'],knowledge_revision=knowledge.revision,fallback_used=getattr(value,'provider_fallback',False))
        value.log.event('learning.response',{'client_frame_id':request.client_frame_id,'check_id':reply['check_id'],
            'vlm_ms':reply['vlm_ms'],'elapsed_ms':reply['elapsed_ms']})
        return reply


    @app.post('/api/learning/runs/{run}/frames')
    def frame(run:str,request:Frame):
        return tracking_frame(run,request)


    @app.post('/api/learning/runs/{run}/frames/jpeg')
    def raw_frame(run:str,body:bytes=Body(media_type='image/jpeg'),client_frame_id:int=Query(ge=1),
                  expected_source_sha256:str=Query(pattern=r'^[a-f0-9]{64}$'),capture_time_ms:float=Query(default=0,ge=0)):
        if len(body)>2000000:raise HTTPException(413,'Tracking JPEG too large')
        request=Frame.model_construct(client_frame_id=client_frame_id,expected_source_sha256=expected_source_sha256,capture_time_ms=capture_time_ms)
        return tracking_frame(run,request,body)


    def tracking_frame(run,request,body=None):
        value,s=state(run)
        if s['source']!='camera' or request.source_image_id:raise HTTPException(409,'静态图片不执行运动跟踪')
        # Frames are already JPEG-encoded by Unity. Validate identity and image header
        # without re-encoding the image; the tracker decodes the frame exactly once.
        from PIL import Image
        import io
        try:
            image=body if body is not None else base64.b64decode(request.image_base64,validate=True)
            with Image.open(io.BytesIO(image)) as header:
                w,h=header.size
                if header.format!='JPEG' or not 16<=min(w,h) or max(w,h)>1280:
                    raise ValueError('Use JPEG frames with longest side <=1280')
        except Exception:
            raise HTTPException(400,'Invalid tracking JPEG or frame size')
        source={'source':'camera','source_sha256':hashlib.sha256(image).hexdigest()}
        if request.expected_source_sha256 and request.expected_source_sha256!=source['source_sha256']:
            raise HTTPException(409,'Input frame SHA256 mismatch')
        value.log.event('learning.input',{'client_frame_id':request.client_frame_id,'stage':'tracking','capture_time_ms':request.capture_time_ms,**source})
        reply=process_frame(value,image,request.client_frame_id)
        if getattr(value,'automatic_provider',False) and s['provider']=='sam31_cutie' and reply.get('batch_metrics',{}).get('error_type'):
            with value.lock:
                if value.closed:raise HTTPException(409,'会话已结束。')
                pipeline.close_sessions(value);value.tracker.shutdown()
                value.tracker=LearningTracker('opencv',config);s['provider']='opencv';value.provider_fallback=True
                value.log.event('provider.fallback',{'stage':'tracking','from':'sam31_cutie','to':'opencv','reason':reply['batch_metrics']['error_type']})
            reply=pipeline.locate(run,pipeline.LocateRequest(image_base64=base64.b64encode(image).decode()))
            reply.update(active_sessions=len(value.sessions),batch_metrics={'provider':'opencv','relocalized_after_fallback':True})
        reply.update(first_mask_provider=s['provider'],fallback_used=getattr(value,'provider_fallback',False))
        reply.update(run_id=run,client_frame_id=request.client_frame_id,source_sha256=source['source_sha256'])
        value.log.event('learning.response',{'client_frame_id':request.client_frame_id,'check_id':reply['check_id'],
            'elapsed_ms':reply['elapsed_ms'],'active_sessions':reply['active_sessions'],'batch_metrics':reply['batch_metrics']})
        return reply


    @app.post('/api/learning/runs/{run}/events',status_code=204)
    def event(run:str,request:Event):
        value,s=state(run)
        if len(json.dumps(request.data))>30000:raise HTTPException(413,'Event too large')
        value.log.event(request.event,request.data)


    @app.post('/api/learning/runs/{run}/clear',status_code=204)
    def clear(run:str):
        value,_=state(run)
        with value.lock:value.tracker.shutdown()
        flush_evidence(value)
        telemetry.report(value)
        pipeline.clear(run)


    @app.post('/api/learning/runs/{run}/screenshot')
    def screenshot(run:str,request:ImageRequest):
        value,s=state(run)
        image=pipeline.image_bytes(request)
        with value.lock:
            folder=value.log.path/'screenshots';folder.mkdir(exist_ok=True)
            name=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ_')+uuid.uuid4().hex[:6]+'.jpg'
            (folder/name).write_bytes(image)
            (value.log.path/'frontend_latest.jpg').write_bytes(image)
            value.log.event('frontend.save',{'file':'screenshots/'+name,'knowledge_revision':knowledge.revision})
            value.log.report()
        return {'file':'screenshots/'+name}


    @app.get('/api/learning/runs/{run}/files/{filename:path}')
    def artifact(run:str,filename:str):
        value,s=state(run)
        if filename in ('learning_report.html','learning_report.json','learning_requests.csv','performance_summary.json','performance_frames.csv'):telemetry.report(value)
        p=(value.log.path/filename).resolve()
        try:p.relative_to(value.log.path.resolve())
        except ValueError:raise HTTPException(404,'Unknown artifact')
        if not p.is_file() or p.suffix.lower() not in ('.html','.jpg','.png','.json','.jsonl','.txt','.csv'):
            raise HTTPException(404,'Unknown artifact')
        return FileResponse(p)

    app.state.pipeline=pipeline
    app.state.knowledge=knowledge
    app.state.learning_states=states
    app.state.close_run=end
    return app
