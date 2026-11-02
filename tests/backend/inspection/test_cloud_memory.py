"""Real local/GPU HTTP contracts and adapter, with an explicit deterministic GPU."""
import hashlib
import json
from types import SimpleNamespace
import httpx
import numpy as np
from fastapi.testclient import TestClient
from manual2ar_inference.engines.initialization import exclusive_initial_masks
from manual2ar_inference.app import create_app as gpu_app
from manual2ar.integrations.perception.client import CutieClient
from manual2ar.modules.inspection.server import create_app
from tests.backend.inspection.test_pipeline import config,FakeVLM,frame


def test_overlap_resolution_reaches_persistent_memory_through_actual_http_and_adapter(tmp_path,monkeypatch):
    token='test-only-token-with-more-than-24-characters'
    class Model:
        def __init__(self):self.order=None;self.steps=0
        def start(self,image,targets):
            self.order=[t['component_id'] for t in targets];h,w=image.shape[:2];sam=[]
            for t in targets:
                a,b,c,d=np.rint(np.array(t['bbox_0_1000'])*[w,h,w,h]/1000).astype(int);mask=np.zeros((h,w),bool);mask[b:d,a:c]=True;sam.append(mask)
            exclusive,policy=exclusive_initial_masks(sam)
            state={'masks':{t['component_id']:m for t,m in zip(targets,exclusive)}}
            return state,state['masks'],{'exclusive_initialization':policy}
        def step(self,state,image):self.steps+=1;return state['masks'],{}
        def close(self,state):state.clear()
    model=Model();app=gpu_app(dict(api_token=token,maximum_sessions=1,session_idle_seconds=300,log_root=str(tmp_path/'gpu')),model)
    with TestClient(app) as remote:
        def transport(request):
            response=remote.request(request.method,request.url.raw_path.decode(),headers=dict(request.headers),content=request.content)
            return httpx.Response(response.status_code,content=response.content,headers=response.headers)
        class Bridge(CutieClient):
            def __init__(self,connection,timeout):super().__init__(connection,timeout,httpx.MockTransport(transport))
        monkeypatch.setattr('manual2ar.integrations.perception.remote_tracker.CutieClient',Bridge)
        c=config();connection=tmp_path/'connection.json';connection.write_text(json.dumps(dict(protocol='manual2ar-learning-cutie-v2',url='https://test-only',api_token=token)))
        c['cutie_tracking']['connection_file']=str(connection)
        with TestClient(create_app(c,FakeVLM(),log_root=tmp_path/'local')) as local:
            run=local.post('/api/inspection/runs',json={'provider':'sam31_cutie','source':'camera'}).json()['run_id'];url='/api/inspection/runs/'+run
            result=local.post(url+'/inspect',json=frame());assert result.status_code==200,result.text
            initial=result.json();assert initial['active_tracks']==2,initial
            assert model.order==['foreign_object_1','build_plate']
            assert all(o['tracking_ready'] for o in initial['objects'])
            for i in range(2,5):
                value=local.post(url+'/frames',json=frame(i,initial['check_id']));assert value.status_code==200,value.text
                assert value.json()['tracking_state']=='tracking' and value.json()['active_tracks']==2
            assert model.steps==3
            assert local.delete(url).status_code==204


def test_new_drive_notebook_contains_patched_gpu_source():
    import ast,base64,io,zipfile
    from pathlib import Path
    from manual2ar.paths import ROOT as root;nb=json.loads((root/'deploy/colab/Manual2AR_GPU.ipynb').read_text())
    for cell in nb['cells']:
        if cell['cell_type']!='code':continue
        code=''.join(cell['source']);compile(code,'notebook','exec')
        for node in ast.parse(code).body:
            if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='SOURCE_ZIP' for t in node.targets):
                with zipfile.ZipFile(io.BytesIO(base64.b64decode(ast.literal_eval(node.value)))) as z:
                    manifest=json.loads(z.read('bundle.manifest.json'))
                    assert 'manual2ar_inference/engines/initialization.py' in manifest
                    assert 'deploy/colab/drive_cache.py' in manifest
                    for file,item in manifest.items():
                        body=z.read(file)
                        assert body==(root/item['source']).read_bytes()
                        assert hashlib.sha256(body).hexdigest()==item['sha256']

                return
    raise AssertionError('Embedded GPU source missing')
