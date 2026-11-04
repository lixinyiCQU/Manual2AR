"""Two-part perception, final-state-only advice, cancellation and framing are independent of authoring."""
import base64
import json
import time
from types import SimpleNamespace
import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient
from tests.backend.guidance.test_spatial import app,begin,frame


class VLM:
    def __init__(self,status='completed'):self.calls=[];self.status=status
    def chat_structured(self,**request):
        self.calls.append(request)
        if request['schema'].get('properties',{}).get('parts'):
            def part(identity,box,point,a,b):return dict(component_id=identity,status='found',confidence=.96,evidence='可见真实部件。',bbox_0_1000=box,foreground_point_0_1000=point,axis_start_0_1000=a,axis_end_0_1000=b)
            return {'parts':[part('spool_holder_base',[600,300,650,450],[625,375],[],[]),part('external_spool_holder',[100,600,400,800],[250,700],[380,700],[120,700])],'next_action':'两个部件均可见。'}
        return {'status':self.status,'confidence':.95,'evidence':'支架已连接到打印机。' if self.status=='completed' else '支架仍单独放在桌面。','next_action':'可继续学习。'}


class GPU:
    instances=[]
    def __init__(self,*args,**kwargs):self.http=SimpleNamespace(timeout=0);self.closed=False;self.targets=None;GPU.instances.append(self)
    def health(self):return {'available':True}
    def start(self,raw,targets):self.targets=targets;return self.masks(raw),{'metrics':{}}
    def masks(self,raw):
        image=cv2.imdecode(np.frombuffer(raw,np.uint8),cv2.IMREAD_COLOR);h,w=image.shape[:2];out={}
        for target in self.targets:
            x,y,r,b=np.asarray(target['bbox_0_1000'])*[w,h,w,h]/1000;mask=np.zeros((h,w),bool);mask[int(y):int(b),int(x):int(r)]=True;out[target['component_id']]=mask
        return out
    def step(self,raw,index):return self.masks(raw),{'metrics':{}}
    def close(self):self.closed=True


def wait(client,url,phases):
    deadline=time.monotonic()+10
    while time.monotonic()<deadline:
        r=client.get(url);assert r.status_code==200,r.text;value=r.json()
        if value['phase'] in phases:return value
        time.sleep(.02)
    raise AssertionError('Parts job did not reach '+str(phases)+': '+str(value))


def setup(service,spy):
    service.client=spy;service.part_tracking.vlm=spy;service.config['vlm']['api_key']='test-only';service.part_tracking.client_factory=GPU


def test_two_parts_use_reference_images_and_one_gpu_session(app):
    service=app.state.spatial;spy=VLM();setup(service,spy)
    with TestClient(app) as c:
        api=begin(c,'camera',u7_fixture_verified=True);raw=frame(action='holder.slide');assert c.post(api+'/frames',json=raw).status_code==200
        response=c.post(api+'/locate',json={'action_id':'holder.slide','client_frame_id':1}).json();job=response['job_id']
        value=wait(c,api+'/parts/'+job,{'tracking'})
        assert {p['component_id'] for p in value['parts']}=={'spool_holder_base','external_spool_holder'}
        assert len(spy.calls)==1 and len(spy.calls[0]['images_base64'])==3
        assert '灰色' in spy.calls[0]['prompt'] and '桌面' in spy.calls[0]['prompt']
        holder=next(p for p in value['parts'] if p['component_id']=='external_spool_holder')
        assert holder['proxy']['coordinate_space']=='image_proxy' and holder['proxy']['illustrative_only']
        second=frame(action='holder.slide',number=2);c.post(api+'/frames',json=second)
        tracked=c.post(api+'/parts/'+job+'/frames',json={'action_id':'holder.slide','client_frame_id':2}).json()
        assert tracked['source_sha256']==second['source_sha256'] and tracked['client_frame_id']==2 and tracked['overlay_png_base64']
        assert len(spy.calls)==1 and not (service.root/'profiles').exists() and not app.state.guidance.meta
        assert c.post(api+'/parts/'+job+'/frames',json={'action_id':'holder.slide','client_frame_id':2}).status_code==409
        c.delete(api+'/parts');assert c.get(api+'/parts/'+job).status_code==409


@pytest.mark.parametrize('stage',['health','start'])
def test_gpu_unavailable_automatically_uses_cpu_and_cools_down(app,stage):
    class Offline(GPU):
        def health(self):
            if stage=='health':raise ConnectionError('offline')
            return super().health()
        def start(self,raw,targets):raise ConnectionError('segmentation offline')
    service=app.state.spatial;setup(service,VLM());service.part_tracking.client_factory=Offline
    with TestClient(app) as c:
        api=begin(c,'camera',u7_fixture_verified=True);c.post(api+'/frames',json=frame(action='holder.slide'))
        job=c.post(api+'/locate',json={'action_id':'holder.slide','client_frame_id':1}).json()['job_id']
        value=wait(c,api+'/parts/'+job,{'tracking'})
        assert value['provider']=='opencv' and value['fallback_used']
        assert '本机 CPU' in value['next_action']
        # Blank fixture images must not become synthetic rectangular masks.
        assert all(p['status']=='lost' for p in value['parts'])
        assert GPU.instances[-1].closed
        count=len(GPU.instances);retry_at=service.part_tracking.gpu_retry_at
        c.post(api+'/locate',json={'action_id':'holder.slide','client_frame_id':1})
        second=service.part_tracking.jobs[api.split('/')[-1]].identity
        assert wait(c,api+'/parts/'+second,{'tracking'})['provider']=='opencv'
        assert len(GPU.instances)==count
        assert service.part_tracking.gpu_retry_at==retry_at
        service.part_tracking.gpu_retry_at=0
        service.part_tracking.client_factory=GPU
        third=c.post(api+'/locate',json={'action_id':'holder.slide','client_frame_id':1}).json()['job_id']
        assert wait(c,api+'/parts/'+third,{'tracking'})['provider']=='sam31_cutie'


def test_cancellation_discards_a_late_vlm_result(app):
    import threading
    started=threading.Event();finish=threading.Event()
    class Slow(VLM):
        def chat_structured(self,**kwargs):started.set();finish.wait(2);return super().chat_structured(**kwargs)
    service=app.state.spatial;setup(service,Slow());count=len(GPU.instances)
    with TestClient(app) as c:
        api=begin(c,'camera',u7_fixture_verified=True);c.post(api+'/frames',json=frame(action='holder.slide'))
        job=c.post(api+'/locate',json={'action_id':'holder.slide','client_frame_id':1}).json()['job_id'];assert started.wait(1)
        c.delete(api+'/parts');finish.set();time.sleep(.1)
        assert c.get(api+'/parts/'+job).status_code==409 and len(GPU.instances)==count


def test_final_installation_check_does_not_segment_or_demand_hidden_screws(app):
    service=app.state.spatial;spy=VLM('not_completed');setup(service,spy)
    with TestClient(app) as c:
        api=begin(c,'camera',u7_fixture_verified=True);c.post(api+'/frames',json=frame(action='holder.slide'))
        for expected in ['not_completed','completed']:
            spy.status=expected;result=c.post(api+'/verify',json={'action_id':'holder.slide','client_frame_id':1}).json()
            assert result['status']==expected and result['scope']=='visible_final_installation'
        assert len(spy.calls[-1]['images_base64'])==2 and '不要求看见底座螺丝' in spy.calls[-1]['prompt']
        assert not service.part_tracking.jobs and not app.state.guidance.meta


def test_old_camera_client_cannot_silently_render_legacy_assets(app):
    with TestClient(app) as c:
        r=c.post('/api/guidance/spatial/sessions',json={'camera_id':'old-client','mode':'camera'})
        assert r.status_code==409 and '旧版本' in r.json()['detail']


def test_xyz_adjustment_preserves_authored_positions_and_exposes_axes(app):
    service=app.state.spatial
    with TestClient(app) as c:
        api=begin(c);before=c.post(api+'/frames',json=frame(action='holder.base')).json()
        r=c.post(api+'/orientation',json={'action_id':'holder.base','rotation_degrees':[0,90,0],'rotation_sign':-1});assert r.status_code==200
        after=c.post(api+'/frames',json=frame(action='holder.base',number=2)).json()
        assert len(after['visual']['axes'])==3 and after['orientation']['rotation_sign']==-1
        a=np.array(before['visual']['presentation']['instances'][0]['reference_from_asset']).reshape(4,4);b=np.array(after['visual']['presentation']['instances'][0]['reference_from_asset']).reshape(4,4)
        assert np.allclose(a[:3,3],b[:3,3]) and not np.allclose(a[:3,:3],b[:3,:3])
        assert all(p['rotation_sign']==-1 for p in after['visual']['presentation']['instances'])
        assert not service.profile('rigs','a1-mini').exists()


def test_portrait_crop_is_accepted_and_same_session_ratio_change_is_rejected(app):
    image=np.full((480,270,3),180,np.uint8);raw=cv2.imencode('.jpg',image)[1].tobytes()
    with TestClient(app) as c:
        api=begin(c,'camera',u7_fixture_verified=True);r=c.post(api+'/frames',json=frame(raw=raw));assert r.status_code==200,r.text
        assert (r.json()['width'],r.json()['height'])==(270,480)
        assert c.post(api+'/frames',json=frame(number=2)).status_code==409


def test_delayed_old_job_cleanup_does_not_cancel_replacement(app):
    service=app.state.spatial;setup(service,VLM())
    with TestClient(app) as c:
        api=begin(c,'camera',u7_fixture_verified=True);c.post(api+'/frames',json=frame(action='holder.slide'))
        first=c.post(api+'/locate',json={'action_id':'holder.slide','client_frame_id':1}).json()['job_id']
        wait(c,api+'/parts/'+first,{'tracking'})
        c.post(api+'/frames',json=frame(action='holder.slide',number=2))
        second=c.post(api+'/locate',json={'action_id':'holder.slide','client_frame_id':2}).json()['job_id']
        assert c.delete(api+'/parts',params={'job_id':first}).status_code==204
        assert wait(c,api+'/parts/'+second,{'tracking'})['job_id']==second


def test_base_step_only_initializes_base_and_does_not_unlock_on_recognition(app):
    service=app.state.spatial;spy=VLM();setup(service,spy)
    with TestClient(app) as c:
        api=begin(c,'camera');c.post(api+'/frames',json=frame(action='holder.base'))
        job=c.post(api+'/locate',json={'action_id':'holder.base','client_frame_id':1}).json()['job_id']
        value=wait(c,api+'/parts/'+job,{'tracking'})
        assert [v['component_id'] for v in GPU.instances[-1].targets]==['spool_holder_base']
        assert '安装底座步骤' in spy.calls[0]['prompt']
        assert not service.u7_progress(service.sessions[api.split('/')[-1]])['base_approved']
        assert value['guidance']


def test_gpu_tracking_disconnect_falls_back_from_last_mask(app):
    class Disconnect(GPU):
        def step(self,raw,index):raise ConnectionError('offline during tracking')
    service=app.state.spatial;setup(service,VLM());service.part_tracking.client_factory=Disconnect
    with TestClient(app) as c:
        api=begin(c,'camera',u7_fixture_verified=True);c.post(api+'/frames',json=frame(action='holder.slide'))
        job=c.post(api+'/locate',json={'action_id':'holder.slide','client_frame_id':1}).json()['job_id']
        assert wait(c,api+'/parts/'+job,{'tracking'})['provider']=='sam31_cutie'
        second=frame(action='holder.slide',number=2);c.post(api+'/frames',json=second)
        tracked=c.post(api+'/parts/'+job+'/frames',json={'action_id':'holder.slide','client_frame_id':2}).json()
        assert tracked['phase']=='tracking' and tracked['provider']=='opencv'
        assert tracked['client_frame_id']==2 and tracked['source_sha256']==second['source_sha256']
        assert len(service.part_tracking.jobs)==1
        c.delete(api+'/parts')


def test_missing_gpu_connection_file_also_uses_cpu(app):
    service=app.state.spatial;setup(service,VLM())
    service.part_tracking.config['gpu_connection_file']=str(service.root/'absent.json')
    with TestClient(app) as c:
        api=begin(c,'camera',u7_fixture_verified=True);c.post(api+'/frames',json=frame(action='holder.slide'))
        job=c.post(api+'/locate',json={'action_id':'holder.slide','client_frame_id':1}).json()['job_id']
        assert wait(c,api+'/parts/'+job,{'tracking'})['provider']=='opencv'


def test_failed_reidentification_and_verification_preserve_active_tracker(app):
    service=app.state.spatial;spy=VLM('not_completed');setup(service,spy)
    with TestClient(app) as c:
        api=begin(c,'camera',u7_fixture_verified=True);c.post(api+'/frames',json=frame(action='holder.slide'))
        first=c.post(api+'/locate',json={'action_id':'holder.slide','client_frame_id':1}).json()['job_id']
        wait(c,api+'/parts/'+first,{'tracking'})
        check=c.post(api+'/verify',json={'action_id':'holder.slide','client_frame_id':1}).json()
        assert check['status']=='not_completed' and c.get(api+'/parts/'+first).json()['phase']=='tracking'
        class Broken(VLM):
            def chat_structured(self,**kwargs):raise ValueError('Controlled VLM parse failure')
        service.part_tracking.vlm=Broken()
        c.post(api+'/frames',json=frame(action='holder.slide',number=2))
        candidate=c.post(api+'/locate',json={'action_id':'holder.slide','client_frame_id':2}).json()['job_id']
        wait(c,api+'/parts/'+candidate,{'failed'});c.delete(api+'/parts',params={'job_id':candidate})
        tracked=c.post(api+'/parts/'+first+'/frames',json={'action_id':'holder.slide','client_frame_id':2})
        assert tracked.status_code==200 and tracked.json()['phase']=='tracking' and tracked.json()['overlay_png_base64']
        c.delete(api+'/parts');assert c.get(api+'/parts/'+first).status_code==409
