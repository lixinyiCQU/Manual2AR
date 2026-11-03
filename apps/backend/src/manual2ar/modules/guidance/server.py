"""Module-two API with legacy unboxing compatibility and explicit task selection."""
from contextlib import asynccontextmanager
from html import escape
import re
import mimetypes
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from manual2ar_contracts.identity import FrameIdentity
from .service import GuidanceService
from .registry import UNBOX


class Start(BaseModel):
    model_config = ConfigDict(extra='forbid')
    task_id: str = Field(min_length=1, max_length=100)
    variant_id: str | None = Field(default=None, max_length=100)


class Command(BaseModel):
    model_config = ConfigDict(extra='forbid')
    state_id: str = Field(pattern=r'^[A-Z][0-9]{1,3}$')
    revision: int = Field(ge=0)


class Browse(Command):
    target_state_id: str = Field(pattern=r"^[A-Z][0-9]{1,3}$")
    substep_id: str | None = Field(default=None,pattern=r"^[A-Z][0-9]{1,3}-S[1-9][0-9]*$")

    @field_validator('substep_id',mode='before')
    @classmethod
    def empty_substep(cls,value):
        # Unity JsonUtility serializes a null string as an empty string.
        return None if value == '' else value


class Confirm(Command):
    inspection_id: str = Field(pattern=r'^[A-Z][0-9]{1,3}-C[1-9][0-9]*$')
    confirmed: bool = Field(strict=True)


class Capture(Command,FrameIdentity):
    inspection_id: str = Field(pattern=r'^[A-Z][0-9]{1,3}-C[1-9][0-9]*$')
    image_base64: str = Field(min_length=32, max_length=14_000_000)
    source_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    client_frame_id: int = Field(ge=1)


class Action(Command):
    confirmed: bool = Field(default=False, strict=True)


def create_app(config, client=None, log_root=None):
    from .manage import public
    service = GuidanceService(config, client=client, log_root=log_root)
    from .spatial.router import router as spatial_router
    spatial_api, spatial = spatial_router(config, service.registry, next(iter(service.engines.values())).client, service.experience)
    @asynccontextmanager
    async def lifespan(app):
        yield
        for identity in list(spatial.sessions):spatial.close(identity)
        for identity in list(service.meta):service.close(identity)
    app = FastAPI(title='Manual2AR 模块二：操作指导',lifespan=lifespan)
    app.state.guidance = service
    app.state.spatial = spatial
    app.include_router(spatial_api)

    @app.get('/health')
    def health(): return {'status':'ok', 'module':'operation-guidance', 'scope':'external_spool_and_ams_lite_unboxing',
                          'task_count':len(service.registry.entries), 'vlm_configured':bool(config['vlm']['api_key'].strip())}

    @app.get('/api/guidance/config')
    def settings(): return public(config)

    @app.get('/api/guidance/tasks')
    def tasks(): return service.registry.catalog()

    @app.get('/api/guidance/tasks/{task_id}/variants/{variant_id}/references/{name}')
    def photo(task_id:str, variant_id:str, name:str):
        _, task = service.registry.resolve(task_id, variant_id)
        item = task.images.get(name)
        if item is None: raise HTTPException(404, '当前任务没有这张参考图。')
        return Response(task.checked_file(item['path'], item['sha256']),
                        media_type=mimetypes.guess_type(name)[0] or 'application/octet-stream')

    @app.post('/api/guidance/runs',status_code=201)
    def begin(command:Start): return service.begin(command.task_id,command.variant_id)

    @app.get('/api/guidance/runs/{identity}')
    def get(identity:str): return service.view(identity)

    @app.post('/api/guidance/runs/{identity}/browse')
    def browse(identity:str,command:Browse): return service.browse(identity,command)

    @app.post('/api/guidance/runs/{identity}/confirm')
    def confirm(identity:str,command:Confirm): return service.mutate(identity,command,'confirm')

    @app.post('/api/guidance/runs/{identity}/verify')
    def verify(identity:str,command:Capture): return service.mutate(identity,command,'verify')

    @app.post('/api/guidance/runs/{identity}/advance')
    def advance(identity:str,command:Command): return service.mutate(identity,command,'advance')

    @app.post('/api/guidance/runs/{identity}/back')
    def back(identity:str,command:Command): return service.mutate(identity,command,'back')

    @app.post('/api/guidance/runs/{identity}/recheck')
    def recheck(identity:str,command:Command): return service.mutate(identity,command,'recheck')

    @app.post('/api/guidance/runs/{identity}/actions/{action_id}')
    def action(identity:str,action_id:str,command:Action): return service.action(identity,command,action_id)

    @app.post('/api/guidance/runs/{identity}/cancel')
    def cancel(identity:str,command:Command): return service.cancel(identity,command)

    @app.post('/api/guidance/runs/{identity}/cancel-flow')
    def cancel_flow(identity:str,command:Command): return service.cancel(identity,command,whole_flow=True)

    @app.get('/api/guidance/runs/{identity}/captures/{check_id}')
    def capture(identity:str,check_id:str):
        with service.lock:
            _,_,run=service.parts(identity)
            if not re.fullmatch('[a-f0-9]{16}',check_id): raise HTTPException(404)
            path=run.folder/check_id/'annotated.jpg'
            if not path.exists(): raise HTTPException(404)
            return FileResponse(path,media_type='image/jpeg',headers={'Cache-Control':'no-store'})

    @app.get('/api/guidance/runs/{identity}/report',response_class=HTMLResponse)
    def report(identity:str):
        with service.lock:
            m,engine,run=service.parts(identity)
            if m['busy']: raise HTTPException(409,'当前检查仍在进行，请稍后查看记录。')
            rows=[]
            for state in engine.task.document.states:
                for node in state.observation_nodes:
                    record=run.results.get(node.inspection_id,{})
                    image='<br><img style="width:100%;max-width:700px" src="'+escape(record['image_url'],quote=True)+'">' if record.get('image_url') else ''
                    rows.append('<tr><td>'+escape(node.inspection_id)+'</td><td>'+escape(node.verification_channel)+'</td><td>'+escape(record.get('status','not_started'))+'</td><td>'+escape(node.condition)+'<p>'+escape(record.get('evidence',''))+'</p><p>'+escape(record.get('correction',''))+'</p>'+image+'</td></tr>')
            tutorial=''
            spatial_rows=[]
            for item in getattr(run, 'spatial_learning', []):
                label='模拟回放' if item['mode']=='replay' else '实机指导'
                action=service.experience.actions.get(item['action_id'],{})
                target=next((t['label'] for t in action.get('target_instances',[]) if t['id']==item['target_id']),'操作位置')
                event_label={'play':'播放示意','pause':'暂停','replay':'重新播放','animation_finished':'示意结束','user_marked':'用户标记已操作','target_selected':'切换位置','tracking_hidden':'提示已隐藏','chapter_advice':'章级拍照参考','location_preview':'拍照找位置'}.get(item['event'],'指导交互')
                spatial_rows.append('<tr><td>'+escape(item['chapter_id'])+'</td><td>'+escape(action.get('title','操作指导'))+'</td><td>'+escape(target)+'</td><td>'+label+'</td><td>'+event_label+'</td></tr>')
            spatial_report=('<h2>空间指导记录</h2><p>播放、用户操作标记与章级拍照建议分别记录；模拟回放不作为实机操作或安装合格的证据。</p><table><tr><th>章节</th><th>动作</th><th>位置</th><th>模式</th><th>事件</th></tr>'+''.join(spatial_rows)+'</table>') if spatial_rows else ''
            if engine.task.params.get('navigation_policy')=='free':
                engine.ensure(run)
                rows_intro=[]
                for state in engine.task.document.states:
                    title=engine.task.cards[state.state_id].title
                    seen='已浏览' if state.state_id in run.tutorial_visits else '未浏览'
                    marked='用户标记已操作' if state.state_id in run.tutorial_marks else '未标记'
                    rows_intro.append('<tr><td>'+escape(title)+'</td><td>'+seen+'</td><td>'+marked+'</td></tr>')
                tutorial='<p>这是教程浏览与拍照建议记录。浏览、用户自行标记和AI参考意见分别记录；结束浏览不表示设备已安装或检查合格。</p><table><tr><th>章节</th><th>浏览</th><th>用户标记</th></tr>'+''.join(rows_intro)+'</table>'
            links=''
            for child in m['receipts']:
                links+='<li><a href="/api/guidance/runs/'+escape(child['run_id'],quote=True)+'/report">'+escape(child['title'])+'</a> · '+escape(child['status'])+'</li>'
            return '<!doctype html><meta charset="utf-8"><title>操作指导记录</title><style>body{font:17px sans-serif;background:#081828;color:#e7f7ff;padding:24px}a{color:#36d6eb}td,th{border:1px solid #285066;padding:12px;vertical-align:top}table{border-collapse:collapse}</style><h1>'+escape(service.registry.entry(m['task_id'])['title'])+'</h1><p>任务版本：'+escape(engine.task.revision)+'<br>人工确认与视觉结果分别记录；指导完成不等于成品质量通过。</p>'+tutorial+spatial_report+'<ul>'+links+'</ul><table><tr><th>观察点</th><th>通道</th><th>状态</th><th>条件与证据</th></tr>'+''.join(rows)+'</table>'

    @app.delete('/api/guidance/runs/{identity}',status_code=204)
    def close(identity:str):
        service.close(identity)
    return app
