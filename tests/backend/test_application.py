"""Cross-module integration with explicit synthetic providers, never external inference."""
import ast
import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import threading
import time
from types import SimpleNamespace
import pytest
from fastapi.testclient import TestClient
from manual2ar.application import ROOT
from manual2ar.application.config import for_module
from manual2ar.application.server import create_app
from tests.backend.inspection.test_pipeline import FakeVLM, FakeTracker, frame, jpeg


class Knowledge:
    def __init__(self):
        self.revision='fixture-knowledge'
        self.bundle={'schema_version':'learning-knowledge-v3','revision':self.revision,'cards':[]}
        self.cards={};self.images={};self.sources={}
        self.wiki=SimpleNamespace(close=lambda:None)


class ComponentVLM:
    provider='qwen';model='controlled-learning';base_url='https://fixture.invalid'
    def __init__(self,block=None):self.block=block;self.calls=0
    def configuration_status(self):return True,None
    def chat_structured(self,**kwargs):
        self.calls+=1
        if self.block:self.block[0].set();self.block[1].wait(8)
        return {'components':[{'component_id':'toolhead','found':True,'confidence':.98,
                'bbox_0_1000':[350,350,600,600],'target_point_0_1000':[450,450],'visible_evidence':'synthetic'}]}


def configuration(tmp_path):
    c=json.loads((ROOT/'configs/app.example.json').read_text())
    c['vlm']['api_key']='fixture-secret-do-not-export'
    c['paths']['runtime']=str(tmp_path/'runs')
    c['paths']['cache']=str(tmp_path/'cache')
    c['paths']['wiki_archive']=str(tmp_path/'missing/archive.json')
    photos=tmp_path/'photos';photos.mkdir(exist_ok=True);(photos/'sample.jpg').write_bytes(jpeg())
    c['paths']['static_images']=str(photos)
    for name in ('learning','inspection'):c['modules'][name]['provider']='opencv'
    return c


def application(c,learning=None):
    return create_app(c,clients={'learning':learning or ComponentVLM(),'guidance':FakeVLM(),'inspection':FakeVLM()},
                      knowledge_store=Knowledge(),tracker_factory=lambda _:FakeTracker())


def test_one_origin_routes_and_three_independent_registries(tmp_path):
    c=configuration(tmp_path);app=application(c)
    with TestClient(app) as client:
        assert [x['id'] for x in client.get('/api/app/modules').json()['modules']]==['learning','guidance','inspection']
        for name in ('learning','guidance','inspection'):
            public=client.get(f'/api/{name}/config');assert public.status_code==200,public.text
            assert public.json()['backend_url']=='http://127.0.0.1:8010'
            assert c['vlm']['api_key'] not in public.text and 'api_key' not in public.text
        learn=client.post('/api/learning/runs',json={'provider':'opencv','source':'camera'}).json()['run_id']
        inspect=client.post('/api/inspection/runs',json={'provider':'opencv','source':'camera'}).json()['run_id']
        guide=client.post('/api/guidance/runs',json={'task_id':'a1_mini_standalone_unboxing_v1'}).json()['run_id']
        assert len({learn,inspect,guide})==3
        assert client.post(f'/api/inspection/runs/{learn}/inspect',json=frame()).status_code==404
        result=client.post(f'/api/inspection/runs/{inspect}/inspect',json=frame())
        assert result.status_code==200,result.text
        assert result.json()['public_result']['status']=='anomaly_detected'
        recognition=client.post(f'/api/learning/runs/{learn}/locate',json={'client_frame_id':1,'image_base64':frame()['image_base64']})
        assert recognition.status_code==200,recognition.text
        assert recognition.json()['source_sha256']==frame()['source_sha256']
        assert len(recognition.json()['results'])==8
        assert client.get(f'/api/guidance/runs/{guide}').status_code==200
        for module,identity in [('learning',learn),('guidance',guide),('inspection',inspect)]:
            assert client.delete(f'/api/{module}/runs/{identity}').status_code==204
            assert client.delete(f'/api/{module}/runs/{identity}').status_code==204


def test_missing_knowledge_disables_only_learning(tmp_path):
    c=configuration(tmp_path)
    with TestClient(create_app(c)) as client:
        cards=client.get('/api/app/modules').json()['modules']
        assert not cards[0]['available'] and cards[1]['available'] and cards[2]['available']
        assert client.get('/api/learning/knowledge').status_code==503
        assert client.get('/api/guidance/tasks').status_code==200
        assert client.get('/api/inspection/tasks').status_code==200


def test_factories_and_vlm_configuration_do_not_share_mutable_state(tmp_path,monkeypatch):
    c=configuration(tmp_path)
    monkeypatch.setenv('DASHSCOPE_API_KEY','wrong-environment-secret')
    from manual2ar.integrations.vlm.audit import AuditedVision
    model=AuditedVision(for_module(c,'learning')['vlm'])
    assert model._client.api_key==c['vlm']['api_key']
    a,b=application(c),application(c)
    with TestClient(a) as first,TestClient(b) as second:
        identity=first.post('/api/learning/runs',json={'provider':'opencv','source':'camera'}).json()['run_id']
        assert identity in a.state.modules['learning'].state.pipeline.runs
        assert identity not in b.state.modules['learning'].state.pipeline.runs
        assert second.post(f'/api/learning/runs/{identity}/clear').status_code==404


def test_leaving_while_learning_vlm_is_pending_drops_late_result(tmp_path):
    c=configuration(tmp_path);entered,release=threading.Event(),threading.Event()
    app=application(c,ComponentVLM((entered,release)))
    with TestClient(app) as client,ThreadPoolExecutor(max_workers=1) as pool:
        run=client.post('/api/learning/runs',json={'provider':'opencv','source':'camera'}).json()['run_id']
        pending=pool.submit(client.post,f'/api/learning/runs/{run}/locate',json={'client_frame_id':1,'image_base64':frame()['image_base64']})
        try:
            assert entered.wait(3)
            started=time.monotonic()
            assert client.delete(f'/api/learning/runs/{run}').status_code==204
            assert time.monotonic()-started<1
        finally:release.set()
        assert pending.result(timeout=5).status_code==409


def test_uniform_errors_have_identity_and_never_echo_request_payload(tmp_path):
    c=configuration(tmp_path)
    with TestClient(application(c)) as client:
        response=client.post('/api/inspection/runs',json={'api_key':'sensitive-invalid-input'})
        assert response.status_code==422
        assert len(response.headers['X-Request-ID'])==32
        assert response.json()['error']['request_id']==response.headers['X-Request-ID']
        assert 'sensitive-invalid-input' not in response.text


def test_module_dependencies_do_not_import_other_business_modules():
    forbidden={'learning':{'guidance','inspection','components','unboxing'},
               'guidance':{'learning','inspection','components','unboxing'},
               'inspection':{'learning','guidance','components','unboxing'}}
    for module,names in forbidden.items():
        paths=list((ROOT/'apps/backend/src/manual2ar/modules'/module).glob('*.py'))
        assert paths
        for path in paths:
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node,ast.ImportFrom) and node.level==0 and node.module:
                    assert not any(node.module == 'manual2ar.modules.'+name or node.module.startswith('manual2ar.modules.'+name+'.') for name in names),(path,node.module)


def test_advanced_settings_are_isolated_and_invalid_keys_fail(tmp_path):
    from manual2ar.application.config import validate
    c=configuration(tmp_path)
    c['modules']['learning']['settings']={'performance':{'preview_mode':'paired'},'cpu_tracking':{'target_fps':5}}
    validate(c)
    assert for_module(c,'learning')['performance']['preview_mode']=='paired'
    assert for_module(c,'inspection')['cpu_tracking']['target_fps']==10
    c['modules']['learning']['settings']['accidental_typo']=True
    with pytest.raises(ValueError):validate(c)


def test_build_scene_list_is_exact_and_all_asset_guids_are_unique():
    import re
    project=ROOT/'apps/unity/Manual2AR'
    scenes=re.findall(r'^    path: (.+)$',(project/'ProjectSettings/EditorBuildSettings.asset').read_text(),re.M)
    assert [Path(p).stem for p in scenes]==['Welcome','PrinterLearning','PrinterGuidance','PrinterInspection']
    assert all((project/p).is_file() for p in scenes)
    guids=[]
    for path in (project/'Assets/Manual2AR').rglob('*.meta'):
        guids.extend(re.findall(r'^guid: ([a-f0-9]{32})$',path.read_text(),re.M))
    assert len(guids)==len(set(guids))


def test_learning_uses_shared_gpu_protocol_and_binary_tracking(tmp_path,monkeypatch):
    import cv2
    import httpx
    import numpy as np
    from manual2ar_inference.app import create_app as gpu_app
    from manual2ar.integrations.perception.client import CutieClient
    class Model:
        def __init__(self):self.starts=0;self.steps=0;self.closed=0
        def start(self,image,targets):
            self.starts+=1;h,w=image.shape[:2];masks={}
            for t in targets:
                a,b,c,d=np.rint(np.array(t['bbox_0_1000'])*[w,h,w,h]/1000).astype(int)
                mask=np.zeros((h,w),bool);mask[b:d,a:c]=True;masks[t['component_id']]=mask
            return {'masks':masks},masks,{}
        def step(self,state,image):self.steps+=1;return state['masks'],{}
        def close(self,state):self.closed+=1;state.clear()
    model=Model();token='fixture-service-token-123456789012345'
    remote_app=gpu_app({'api_token':token,'maximum_sessions':2,'session_idle_seconds':300,'log_root':str(tmp_path/'gpu')},model)
    c=configuration(tmp_path);c['modules']['learning']['provider']='sam31_cutie'
    connection=tmp_path/'connection.local.json';connection.write_text(json.dumps({'url':'https://fixture.invalid','api_token':token,'protocol':'manual2ar-learning-cutie-v2'}));c['gpu']['connection_file']=str(connection)
    with TestClient(remote_app) as remote:
        def transport(request):
            r=remote.request(request.method,request.url.raw_path.decode(),headers=dict(request.headers),content=request.content)
            return httpx.Response(r.status_code,content=r.content,headers=r.headers)
        class Bridge(CutieClient):
            def __init__(self,connection,timeout=30):super().__init__(connection,timeout,httpx.MockTransport(transport))
        monkeypatch.setattr('manual2ar.integrations.perception.remote_tracker.CutieClient',Bridge)
        monkeypatch.setattr('manual2ar.integrations.perception.client.CutieClient',Bridge)
        with TestClient(application(c)) as client:
            run=client.post('/api/learning/runs',json={'provider':'sam31_cutie','source':'camera'}).json()['run_id'];url=f'/api/learning/runs/{run}'
            result=client.post(url+'/locate',json={'client_frame_id':1,'image_base64':frame()['image_base64']})
            assert result.status_code==200,result.text
            assert any(x['tracking_ready'] for x in result.json()['results'])
            body=jpeg();fingerprint=hashlib.sha256(body).hexdigest()
            tracked=client.post(url+'/frames/jpeg',content=body,headers={'Content-Type':'image/jpeg'},params={'client_frame_id':2,'expected_source_sha256':fingerprint})
            assert tracked.status_code==200,tracked.text
            assert tracked.json()['source_sha256']==fingerprint and tracked.json()['label_map']
            assert model.starts==1 and model.steps==1
            assert client.post(url+'/frames/jpeg',content=body,headers={'Content-Type':'image/jpeg'},params={'client_frame_id':3,'expected_source_sha256':'0'*64}).status_code==409
            client.delete(url)
            until=time.monotonic()+2
            while not model.closed and time.monotonic()<until:time.sleep(.01)
            assert model.closed==1


def test_learning_static_original_fingerprint_and_alias_are_checked(tmp_path):
    c=configuration(tmp_path)
    with TestClient(application(c)) as client:
        image=client.get('/api/learning/images').json()['images'][0]
        preview=client.get(image['preview_url']);fingerprint=preview.headers['X-Source-SHA256']
        run=client.post('/api/learning/runs',json={'provider':'opencv','source':'static'}).json()['run_id']
        data={'source_image_id':image['id'],'client_frame_id':1,'source_sha256':fingerprint}
        response=client.post(f'/api/learning/runs/{run}/locate',json=data)
        assert response.status_code==200,response.text
        assert response.json()['source_sha256']==fingerprint
        data['source_sha256']='0'*64
        assert client.post(f'/api/learning/runs/{run}/locate',json=data).status_code==409


@pytest.mark.parametrize('module',['learning','inspection'])
def test_standalone_static_runner_uses_product_api_and_writes_visualization(tmp_path,monkeypatch,module):
    import httpx
    from tools.evaluation import static_test
    c=configuration(tmp_path)
    original=httpx.Client
    with TestClient(application(c)) as api:
        def transport(request):
            result=api.request(request.method,request.url.raw_path.decode(),content=request.content,headers=dict(request.headers))
            return httpx.Response(result.status_code,content=result.content,headers=result.headers)
        monkeypatch.setattr(static_test,'load',lambda:c)
        monkeypatch.setattr(static_test.httpx,'Client',lambda **kwargs:original(**kwargs,transport=httpx.MockTransport(transport)))
        monkeypatch.setattr('sys.argv',['static_test','--module',module])
        static_test.main()
    outputs=list((Path(c['paths']['runtime'])/'static'/module).glob('*/001/overlay.jpg'))
    assert len(outputs)==1 and outputs[0].stat().st_size>100
    assert (outputs[0].parent/'result.json').is_file()
