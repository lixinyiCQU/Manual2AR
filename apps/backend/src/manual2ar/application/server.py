"""Composition only: module routes, state, providers and lifetimes stay independent."""
from contextlib import AsyncExitStack, asynccontextmanager
from copy import deepcopy
import uuid
import logging
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from .config import load, for_module, public, validate
from .contracts import MODULES, FrameIdentity


def create_app(config=None, clients=None, knowledge_store=None, tracker_factory=None):
    from manual2ar.modules.learning.server import create_app as learning_app
    from manual2ar.modules.guidance.server import create_app as guidance_app
    from manual2ar.modules.inspection.server import create_app as inspection_app
    config = deepcopy(config or load())
    validate(config)
    clients = clients or {}
    children = {}
    unavailable = {}
    try:
        children['learning'] = learning_app(for_module(config, 'learning'), clients.get('learning'), knowledge_store)
    except FileNotFoundError:
        unavailable['learning'] = '官方离线资料尚未安装，请配置资料路径。'
    children['guidance'] = guidance_app(for_module(config, 'guidance'), clients.get('guidance'))
    children['inspection'] = inspection_app(for_module(config, 'inspection'), clients.get('inspection'), tracker_factory)

    @asynccontextmanager
    async def lifespan(app):
        async with AsyncExitStack() as stack:
            for child in children.values():
                await stack.enter_async_context(child.router.lifespan_context(child))
            yield

    app = FastAPI(title='Manual2AR', version='0.1.0', lifespan=lifespan)
    app.state.modules = children
    app.state.config = config

    @app.middleware('http')
    async def request_identity(request: Request, call_next):
        supplied = request.headers.get('X-Request-ID', '')
        request.state.request_id = supplied if len(supplied) == 32 and all(c in '0123456789abcdef' for c in supplied) else uuid.uuid4().hex
        response = await call_next(request)
        response.headers['X-Request-ID'] = request.state.request_id
        response.headers['X-Manual2AR-API-Version'] = '1'
        return response

    @app.exception_handler(HTTPException)
    async def http_error(request, error):
        return JSONResponse(status_code=error.status_code, content={
            'detail': str(error.detail), 'error': {'code': f'http_{error.status_code}',
            'request_id': getattr(request.state, 'request_id', ''), 'retryable': error.status_code in (409, 429, 502, 503, 504)}})

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, error):
        return JSONResponse(status_code=422, content={'detail': '请求格式不正确，请刷新页面后重试。',
            'error': {'code': 'invalid_request', 'request_id': getattr(request.state, 'request_id', ''), 'retryable': False}})

    @app.exception_handler(Exception)
    async def unexpected_error(request, error):
        request_id=getattr(request.state,'request_id','')
        logging.getLogger(__name__).error('Unhandled request id=%s error_type=%s',request_id,type(error).__name__)
        return JSONResponse(status_code=500,content={'detail':'服务暂时未能完成请求，请稍后重试。',
            'error':{'code':'internal_error','request_id':request_id,'retryable':True}})

    @app.get('/health')
    def health():
        return {'status': 'ok', 'version': '0.1.0', 'api_version': '1',
                'modules': {m.id: {'available': m.id in children, 'reason': unavailable.get(m.id, '')} for m in MODULES},
                'vlm_configured': bool(config['vlm']['api_key'].strip())}

    @app.get('/api/app/config')
    def settings(): return public(config)

    @app.get('/api/app/modules')
    def modules():
        return {'schema_version': 'manual2ar-modules-v1', 'modules': [
            m.model_copy(update={'available': m.id in children, 'status_message': unavailable.get(m.id, '')}).model_dump() for m in MODULES]}

    from .services import ServiceRegistry
    service_registry=ServiceRegistry(config)
    def service_availability():
        return {m.id:{'available':m.id in children,'status_message':unavailable.get(m.id,'')} for m in MODULES}

    @app.get('/api/app/services')
    def services():return service_registry.catalog(service_availability())

    @app.get('/api/app/services/{identity}')
    def teaching_service(identity:str):return service_registry.detail(identity,service_availability())

    @app.get('/api/app/contracts')
    def contracts():
        return {'schema_version': 'manual2ar-contract-v1', 'frame_identity': FrameIdentity.model_json_schema(),
                'coordinates': {'range': [0, 1000], 'origin': 'top-left', 'box': ['left', 'top', 'right', 'bottom'],
                                'image': 'upright submitted image; result source_sha256 must match display input'},
                'outcomes': {'learning': 'recognition', 'guidance': 'tutorial / task progress', 'inspection': 'snapshot assessment / target resolution'},
                'gpu_protocol': 'manual2ar-learning-cutie-v2'}

    for name, child in children.items():
        for route in child.routes:
            if route.path == '/health':
                app.add_api_route(f'/api/{name}/health', route.endpoint, methods=['GET'], tags=[name])
            elif route.path not in ('/openapi.json', '/docs', '/docs/oauth2-redirect', '/redoc'):
                app.router.routes.append(route)
    if 'learning' not in children:
        @app.api_route('/api/learning/{path:path}', methods=['GET', 'POST', 'DELETE'])
        def no_knowledge(path: str): raise HTTPException(503, unavailable['learning'])
    return app
