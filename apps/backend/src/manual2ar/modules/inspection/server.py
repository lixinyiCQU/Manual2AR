"""Independent module-three API; no global import of learning.server/config."""
from pathlib import Path
from html import escape
from contextlib import asynccontextmanager
import base64,hashlib,io,json,re,shutil
from fastapi import FastAPI,HTTPException,Request
from fastapi.responses import Response,HTMLResponse
from PIL import Image,ImageOps
from .contracts import Begin,Frame,ClientEvent,SaveEvidence,StartCheck,ConfirmOcclusion
from .presentation import public_result,user_title
from .service import InspectionService
from .manage import public
from .progress import InspectionJobs


def create_app(config,client=None,tracker_factory=None,log_root=None):
    service=InspectionService(config,client,tracker_factory,log_root)
    jobs=InspectionJobs(service)
    @asynccontextmanager
    async def lifespan(app):
        yield
        jobs.shutdown()
    app=FastAPI(title='Manual2AR 模块三 · 打印状态检查',lifespan=lifespan);app.state.inspection=service;app.state.inspection_jobs=jobs
    from manual2ar.resources import ResourceStore
    resources=ResourceStore.configured(config)
    catalog=resources.json('module.inspection.catalog');evidence=resources.json('task.plate_surface.evidence')
    def images():
        folder=Path(config['static_images']['folder']).resolve();found={}
        if not folder.is_dir():return found
        for p in sorted(folder.iterdir()):
            if p.suffix.lower() not in ('.jpg','.jpeg','.png') or not p.is_file() or not p.resolve().is_relative_to(folder):continue
            key=hashlib.sha256(p.name.encode()).hexdigest()[:16];found[key]=p
            if len(found)>=config['static_images']['max_count']:break
        return found
    @app.get('/health')
    def health():return {'status':'ok','module':'module-three','module_version':Path(__file__).with_name('VERSION').read_text().strip(),'vlm_configured':bool(config['vlm']['api_key'].strip()),'default_provider':config['segmentation']['default_provider'],'cloud_connection_file_present':Path(config['cutie_tracking']['connection_file']).is_file()}
    @app.get('/api/inspection/config')
    def settings():return public(config)
    @app.get('/api/inspection/tasks')
    def tasks():return catalog
    @app.get('/api/inspection/evidence')
    def sources():return evidence
    @app.get('/api/inspection/images')
    def static_images():return {'images':[{'id':key,'name':path.name,'url':'/api/inspection/images/'+key} for key,path in images().items()]}
    @app.get('/api/inspection/images/{identity}')
    def photo(identity:str):
        path=images().get(identity)
        if path is None:raise HTTPException(404,'没有这张测试图。')
        try:
            with Image.open(path) as im:
                im=ImageOps.exif_transpose(im).convert('RGB');im.thumbnail((1280,1280));buf=io.BytesIO();im.save(buf,'JPEG',quality=90)
        except Exception:raise HTTPException(422,'图像读取失败。') from None
        return Response(buf.getvalue(),media_type='image/jpeg')
    @app.post('/api/inspection/runs',status_code=201)
    def begin(request:Begin):return service.begin(request)
    @app.post('/api/inspection/runs/{identity}/inspect')
    def inspect(identity:str,request:Frame):
        if jobs.busy(identity):raise HTTPException(409,'本次检查仍在处理。')
        return service.inspect(identity,request)
    @app.post('/api/inspection/runs/{identity}/checks',status_code=202)
    def submit_check(identity:str,request:StartCheck):return jobs.submit(identity,request)
    @app.get('/api/inspection/runs/{identity}/checks/{job_id}')
    def check_progress(identity:str,job_id:str,after_revision:int=0):
        if after_revision<0:raise HTTPException(422,'进度版本无效。')
        return jobs.get(identity,job_id,after_revision)
    @app.delete('/api/inspection/runs/{identity}/checks/{job_id}',status_code=204)
    def cancel_check(identity:str,job_id:str):jobs.cancel(identity,job_id)
    @app.post('/api/inspection/runs/{identity}/confirm-occlusion')
    def confirm_occlusion(identity:str,request:ConfirmOcclusion):
        if jobs.busy(identity):raise HTTPException(409,'请等待本次检查完成。')
        return service.confirm_occlusion(identity,request)
    @app.post('/api/inspection/runs/{identity}/frames')
    def track(identity:str,request:Frame):
        if jobs.busy(identity):raise HTTPException(409,'请等待本次检查完成。')
        return service.track(identity,request)
    @app.post('/api/inspection/runs/{identity}/frames/jpeg')
    async def track_jpeg(identity:str,request:Request,client_frame_id:int,check_id:str,source_sha256:str):
        if jobs.busy(identity):raise HTTPException(409,'请等待本次检查完成。')
        if request.headers.get('content-type','').split(';')[0]!='image/jpeg':raise HTTPException(415,'请发送JPEG图像。')
        if int(request.headers.get('content-length','0'))>2000000:raise HTTPException(413,'图像过大。')
        body=await request.body()
        if len(body)>2000000:raise HTTPException(413,'图像过大。')
        try:frame=Frame(image_base64=base64.b64encode(body).decode(),source_sha256=source_sha256,client_frame_id=client_frame_id,check_id=check_id)
        except ValueError:raise HTTPException(422,'图像标识无效。') from None
        from starlette.concurrency import run_in_threadpool
        return await run_in_threadpool(service.track,identity,frame)
    @app.delete('/api/inspection/runs/{identity}',status_code=204)
    def close(identity:str):jobs.close_run(identity)
    @app.post('/api/inspection/runs/{identity}/events',status_code=204)
    def event(identity:str,request:ClientEvent):
        if len(json.dumps(request.data))>12000:raise HTTPException(413,'事件过大。')
        service.get(identity).log.event(request.event,request.data)
    def saved_run(identity):
        if not re.fullmatch(r'[a-f0-9]{32}',identity):raise HTTPException(404)
        folder=service.log_root/identity
        if not (folder/'session.json').is_file():raise HTTPException(404)
        return folder
    @app.post('/api/inspection/runs/{identity}/evidence')
    def save_evidence(identity:str,request:SaveEvidence):
        run=service.get(identity);service.acquire(run)
        try:
            source=run.log.path/request.check_id
            if not (source/'decision.json').is_file():raise HTTPException(404,'本次检查记录尚未生成。')
            decision=json.loads((source/'decision.json').read_text())
            objects=json.loads((source/'objects.json').read_text()) if (source/'objects.json').is_file() else []
            resolution=json.loads((source/'resolution.json').read_text()) if (source/'resolution.json').is_file() else None
            if resolution:decision=resolution['decision'];objects=resolution['objects']
            dest=run.log.path/'evidence'/request.check_id;dest.mkdir(parents=True,exist_ok=True)
            for name in ('input.jpg','overlay.jpg'):
                picture=source/('resolution_'+name if resolution else name)
                if picture.is_file():shutil.copyfile(picture,dest/name)
            summary={'task':'打印板异物与残料','checked_at':decision.get('checked_at'),**public_result(decision,objects)}
            if resolution:summary.update(resolution['public_result'],checked_at=resolution['at'],source_sha256=resolution['source_sha256'],client_frame_id=resolution['client_frame_id'],evidence_type='plate_scope_update')
            (dest/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
            run.log.event('evidence.saved',{'check_id':request.check_id})
            return {'saved':True}
        finally:run.lock.release()
    @app.get('/api/inspection/runs/{identity}/report',response_class=HTMLResponse)
    def report(identity:str):
        folder=saved_run(identity);sections=[]
        for p in sorted(folder.glob('check_*/decision.json'),key=lambda p:p.stat().st_mtime):
            d=json.loads(p.read_text());name=p.parent.name
            picture='<img src="/api/inspection/runs/'+identity+'/'+name+'/overlay.jpg" style="max-width:95%">' if (p.parent/'overlay.jpg').is_file() else ''
            objects=json.loads((p.parent/'objects.json').read_text()) if (p.parent/'objects.json').is_file() else []
            if (p.parent/'resolution.json').is_file():
                resolved=json.loads((p.parent/'resolution.json').read_text());d={**resolved['decision'],'checked_at':resolved['at']};objects=resolved['objects'];picture='<img src="/api/inspection/runs/'+identity+'/'+name+'/resolution.jpg" style="max-width:95%">'
            visible=public_result(d,objects);hint='部分边缘被遮挡或未入镜，请补拍。' if visible['recheck_reason']=='incomplete_view' else '场景变化后，请重新检查。'
            if (p.parent/'resolution.json').is_file():visible=resolved['public_result']
            manual='<p>本次通过包含用户对打印头左上角遮挡区域的人工确认。</p>' if d.get('occlusion_confirmed') else ''
            sections.append('<article><h2>'+user_title(visible['status'])+'</h2><p>'+escape(d.get('checked_at',''))+'</p>'+picture+manual+'<p>'+hint+'</p></article>')
        sources={q['source_url']:q['title'] for q in evidence['quotes']}
        links=''.join('<p><a href="'+escape(url,quote=True)+'">'+escape(title)+'</a></p>' for url,title in sources.items())
        return '<!doctype html><meta charset="utf-8"><title>板面检查记录</title><style>body{font:18px sans-serif;background:#081724;color:#eff9ff;padding:25px}a{color:#46cedf}article{margin:30px 0}</style><h1>打印板检查记录</h1><p>结果对应检查时的照片；场景变化后请重新检查。</p>'+''.join(sections)+'<h2>官方资料</h2>'+links
    @app.get('/api/inspection/runs/{identity}/{check}/overlay.jpg')
    def overlay(identity:str,check:str):
        if not re.fullmatch(r'check_[a-f0-9]{16}',check):raise HTTPException(404)
        p=saved_run(identity)/check/'overlay.jpg'
        if not p.is_file():raise HTTPException(404)
        return Response(p.read_bytes(),media_type='image/jpeg')
    @app.get('/api/inspection/runs/{identity}/{check}/resolution.jpg')
    def resolution_overlay(identity:str,check:str):
        if not re.fullmatch(r'check_[a-f0-9]{16}',check):raise HTTPException(404)
        path=saved_run(identity)/check/'resolution_overlay.jpg'
        if not path.is_file():raise HTTPException(404)
        return Response(path.read_bytes(),media_type='image/jpeg')
    return app
