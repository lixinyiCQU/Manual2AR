"""Automatic transport policy falls back on service failure, preserving VLM evidence."""
import json
from fastapi.testclient import TestClient
from manual2ar_contracts.gpu import PROTOCOL
from tests.backend.test_application import configuration,application,ComponentVLM
from tests.backend.inspection.test_pipeline import frame


def cloud_config(tmp_path,monkeypatch):
    config=configuration(tmp_path)
    path=tmp_path/'worker.connection.local.json'
    path.write_text(json.dumps({'protocol':PROTOCOL,'url':'https://controlled.invalid','api_token':'test-only-token-at-least-24-characters'}))
    config['gpu']['connection_file']=str(path)
    class Probe:
        def __init__(self,connection,timeout):assert timeout==3
        def health(self):return {'available':True,'protocol':PROTOCOL}
        def close(self):pass
    monkeypatch.setattr('manual2ar.integrations.perception.client.CutieClient',Probe)
    return config


def test_auto_missing_connection_uses_cpu_and_explicit_cloud_still_reports_error(tmp_path):
    config=configuration(tmp_path);config['gpu']['connection_file']=str(tmp_path/'missing.json')
    model=ComponentVLM()
    with TestClient(application(config,model)) as client:
        created=client.post('/api/learning/runs',json={'provider':'auto','source':'camera'})
        assert created.status_code==201
        run=created.json();assert run['provider']=='opencv' and run['fallback_used']
        assert model.calls==0
        data=client.post('/api/learning/runs/'+run['run_id']+'/locate',json={'client_frame_id':1,'image_base64':frame()['image_base64']})
        assert data.status_code==200,data.text
        assert data.json()['first_mask_provider']=='opencv' and model.calls==1
        assert client.post('/api/learning/runs',json={'provider':'sam31_cutie','source':'camera'}).status_code==400


def test_cloud_initialization_failure_reuses_one_vlm_call_and_same_frame(tmp_path,monkeypatch):
    from manual2ar.integrations.perception.provider import LearningTracker
    config=cloud_config(tmp_path,monkeypatch);model=ComponentVLM();original=LearningTracker.prepare
    def prepare(self,*args,**kwargs):
        if self.provider=='sam31_cutie':raise TimeoutError('controlled GPU failure')
        return original(self,*args,**kwargs)
    monkeypatch.setattr(LearningTracker,'prepare',prepare)
    with TestClient(application(config,model)) as client:
        run=client.post('/api/learning/runs',json={'provider':'auto','source':'camera'}).json()
        assert run['provider']=='sam31_cutie'
        result=client.post('/api/learning/runs/'+run['run_id']+'/locate',json={'client_frame_id':1,'image_base64':frame()['image_base64']})
        assert result.status_code==200,result.text
        value=result.json()
        assert value['first_mask_provider']=='opencv' and value['fallback_used']
        assert model.calls==1 and value['source_sha256']==frame()['source_sha256']
        assert not any(row['stage']=='segmentation_error' for row in value['results'])


def test_vlm_failure_does_not_claim_offline_recognition_or_retry_provider(tmp_path):
    config=configuration(tmp_path);config['gpu']['connection_file']=str(tmp_path/'missing.json')
    class BrokenVLM(ComponentVLM):
        def chat_structured(self,**kwargs):self.calls+=1;raise RuntimeError('controlled VLM outage')
    model=BrokenVLM()
    with TestClient(application(config,model)) as client:
        run=client.post('/api/learning/runs',json={'provider':'auto','source':'camera'}).json()
        result=client.post('/api/learning/runs/'+run['run_id']+'/locate',json={'client_frame_id':1,'image_base64':frame()['image_base64']})
        assert result.status_code==502 and model.calls==1


def test_live_gpu_outage_relocalizes_current_frame_before_cpu_tracking(tmp_path,monkeypatch):
    import httpx
    import numpy as np
    from manual2ar_inference.app import create_app as gpu_app
    from manual2ar.integrations.perception.client import CutieClient as RealClient
    token='test-only-token-at-least-24-characters'
    class GPU:
        def start(self,image,targets):
            h,w=image.shape[:2];masks={}
            for target in targets:
                a,b,c,d=np.rint(np.array(target['bbox_0_1000'])*[w,h,w,h]/1000).astype(int)
                mask=np.zeros((h,w),bool);mask[b:d,a:c]=True;masks[target['component_id']]=mask
            return masks,masks,{}
        def step(self,state,image):raise RuntimeError('controlled cloud outage')
        def close(self,state):pass
    app=gpu_app(dict(api_token=token,maximum_sessions=1,session_idle_seconds=300,log_root=str(tmp_path/'gpu')),GPU())
    config=cloud_config(tmp_path,monkeypatch);model=ComponentVLM()
    with TestClient(app) as remote:
        def transport(request):
            response=remote.request(request.method,request.url.raw_path.decode(),headers=dict(request.headers),content=request.content)
            return httpx.Response(response.status_code,content=response.content,headers=response.headers)
        class Bridge(RealClient):
            def __init__(self,connection,timeout):super().__init__(connection,timeout,httpx.MockTransport(transport))
        monkeypatch.setattr('manual2ar.integrations.perception.remote_tracker.CutieClient',Bridge)
        with TestClient(application(config,model)) as client:
            run=client.post('/api/learning/runs',json={'provider':'auto','source':'camera'}).json()
            url='/api/learning/runs/'+run['run_id']
            data={'client_frame_id':1,'image_base64':frame()['image_base64']}
            first=client.post(url+'/locate',json=data)
            assert first.status_code==200,first.text
            assert any(row['tracking_ready'] for row in first.json()['results']),first.text
            assert model.calls==1
            next_frame=client.post(url+'/frames',json={**data,'client_frame_id':2})
            assert next_frame.status_code==200,next_frame.text
            value=next_frame.json()
            assert value['first_mask_provider']=='opencv' and value['fallback_used']
            assert value['check_id']!=first.json()['check_id']
            assert value['source_sha256']==frame()['source_sha256'] and value['client_frame_id']==2
            assert value['batch_metrics']['relocalized_after_fallback']
            assert model.calls==2
