"""Stage boundaries and races, controlled locally without cloud requests."""
import copy,time,uuid
from threading import Event
import pytest
from fastapi.testclient import TestClient
from manual2ar.modules.inspection.server import create_app
from tests.backend.inspection.test_pipeline import config,FakeVLM,FakeTracker,frame,observation

class GateTracker(FakeTracker):
    def __init__(self,entered,release):super().__init__();self.entered=entered;self.release=release
    def prepare(self,*args):
        self.entered.set()
        assert self.release.wait(5),'test GPU gate timed out'

@pytest.fixture
def staged(tmp_path):
    entered=Event();release=Event();vlm=FakeVLM();trackers=[]
    def factory(_):
        t=GateTracker(entered,release);trackers.append(t);return t
    app=create_app(config(),vlm,factory,tmp_path/'runs')
    with TestClient(app) as c:
        url='/api/inspection/runs/'+c.post('/api/inspection/runs',json={'provider':'opencv'}).json()['run_id']
        try:yield c,url,app,vlm,entered,release,trackers
        finally:
            release.set()
            deadline=time.monotonic()+3
            while app.state.inspection_jobs.busy(url.rsplit('/',1)[-1]) and time.monotonic()<deadline:time.sleep(.005)

def start(c,url,index=1,job=None):
    body={**frame(index),'request_id':job or uuid.uuid4().hex}
    response=c.post(url+'/checks',json=body)
    assert response.status_code==202,response.text
    return response.json(),body

def until(c,url,job,phase,revision=0):
    deadline=time.monotonic()+4;events=[]
    while time.monotonic()<deadline:
        r=c.get(url+'/checks/'+job,params={'after_revision':revision});assert r.status_code==200,r.text
        value=r.json()
        if value['revision']>revision:events.append(value);revision=value['revision']
        if value['phase']==phase:return value,events
        if value['finished']:pytest.fail(str(value))
        time.sleep(.005)
    pytest.fail('progress timeout: '+phase)

def test_boxes_published_before_gpu_without_mutable_mask_leak(staged):
    c,url,app,vlm,entered,release,_=staged
    first,body=start(c,url);assert first['phase']=='queued';assert entered.wait(2)
    early,events=until(c,url,body['request_id'],'segmenting')
    assert [e['phase'] for e in events]==['queued','recognizing','segmenting']
    r=early['result'];assert r['stage']=='localization' and r['label_map'] is None
    assert r['public_result']['status']=='localizing' and r['public_result']['foreign_object_state']=='fail'
    assert all(o['found'] and o['bbox_0_1000'] and not o['tracking_ready'] for o in r['objects'])
    assert c.post(url+'/frames',json=frame(2,r['check_id'])).status_code==409
    assert c.post(url+'/inspect',json=frame(2)).status_code==409
    release.set();final,_=until(c,url,body['request_id'],'completed',early['revision'])
    assert final['result']['label_map'] and final['result']['active_tracks']==2
    for key in ('check_id','source_sha256','client_frame_id'):assert final[key]==early[key]
    replay,_=until(c,url,body['request_id'],'segmenting')
    assert all(not o['tracking_ready'] for o in replay['result']['objects'])
    assert c.post(url+'/frames',json=frame(2,final['check_id'])).status_code==200


def test_fast_completion_still_replays_stages_and_clean_is_not_early(staged):
    c,url,app,vlm,_,release,_=staged;release.set();vlm.value=observation(False)
    _,body=start(c,url);final,events=until(c,url,body['request_id'],'completed')
    assert [e['phase'] for e in events]==['queued','recognizing','segmenting','completed']
    early=events[2]['result'];assert early['decision']['status']=='inspection_pending'
    assert early['public_result']['foreign_object_state']==early['public_result']['residue_state']=='unknown'
    assert final['result']['decision']['status']=='no_visible_anomaly'


def test_gpu_failure_retains_boxes_and_warning(staged):
    c,url,app,_,_,_,_=staged
    class Down(FakeTracker):
        def prepare(self,*a):raise ConnectionError('private failure text')
    app.state.inspection.tracker_factory=lambda _:Down()
    _,body=start(c,url);final,events=until(c,url,body['request_id'],'completed')
    assert any(e['phase']=='segmenting' for e in events)
    result=final['result'];assert result['decision']['status']=='anomaly_detected' and result['active_tracks']==0
    assert result['objects'][1]['bbox_0_1000'] and result['public_result']['foreign_object_state']=='fail'
    assert 'private failure text' not in str(final)


def test_cancel_during_gpu_never_publishes_late_completion(staged):
    c,url,app,_,entered,release,_=staged
    _,body=start(c,url);assert entered.wait(2)
    job=body['request_id'];assert c.delete(url+'/checks/'+job).status_code==204
    assert c.get(url+'/checks/'+job).json()['phase']=='cancelled'
    release.set();identity=url.rsplit('/',1)[-1];deadline=time.monotonic()+2
    while app.state.inspection_jobs.busy(identity) and time.monotonic()<deadline:time.sleep(.005)
    record=app.state.inspection_jobs.jobs[job]
    assert [e['phase'] for e in record.events]==['queued','recognizing','segmenting','cancelled']
    run=app.state.inspection.get(identity);assert not run.sessions and not run.objects


def test_latest_pending_inspection_wins_and_old_cancel_does_not_erase_it(staged):
    c,url,app,vlm,entered,release,_=staged
    _,one=start(c,url);assert entered.wait(2)
    _,two=start(c,url,2);_,three=start(c,url,3)
    assert c.get(url+'/checks/'+one['request_id']).json()['phase']=='cancelled'
    assert c.get(url+'/checks/'+two['request_id']).json()['phase']=='cancelled'
    vlm.value=observation(False);release.set();last,_=until(c,url,three['request_id'],'completed')
    assert last['result']['decision']['status']=='no_visible_anomaly'
    assert len(vlm.calls)==2
    assert c.delete(url+'/checks/'+one['request_id']).status_code==204
    assert c.get(url+'/checks/'+three['request_id']).json()['phase']=='queued'  # ordered replay
    assert app.state.inspection.get(url.rsplit('/',1)[-1]).check_id==last['check_id']


def test_cancel_overtakes_post_and_duplicate_post_is_idempotent(staged):
    c,url,app,vlm,_,release,_=staged
    key=uuid.uuid4().hex;assert c.delete(url+'/checks/'+key).status_code==204
    result,body=start(c,url,job=key);assert result['cancelled'] and not vlm.calls
    release.set();first,body=start(c,url,2)
    again=c.post(url+'/checks',json=body);assert again.status_code==202 and again.json()['check_id']==first['check_id']
    until(c,url,body['request_id'],'completed');assert len(vlm.calls)==1
    changed={**body,'client_frame_id':3};assert c.post(url+'/checks',json=changed).status_code==409
    assert c.post(url+'/checks',json={**frame(1),'request_id':uuid.uuid4().hex}).status_code==409
    assert c.get(url+'/checks/'+body['request_id'],params={'after_revision':-1}).status_code==422


def test_close_during_gpu_returns_without_waiting_and_keeps_cancellation(staged):
    c,url,app,_,entered,release,_=staged
    _,body=start(c,url);assert entered.wait(2)
    assert c.delete(url).status_code==204
    assert c.get(url+'/checks/'+body['request_id']).json()['cancelled']
    assert c.post(url+'/checks',json={**frame(2),'request_id':uuid.uuid4().hex}).status_code==404
    release.set()


def test_cancel_during_vlm_does_not_start_gpu(staged):
    c,url,app,vlm,gpu,release,_=staged
    entered=Event();vlm_release=Event();original=vlm.chat_structured
    def gated(**kwargs):
        entered.set();assert vlm_release.wait(3);return original(**kwargs)
    vlm.chat_structured=gated
    try:
        _,body=start(c,url);assert entered.wait(2);c.delete(url+'/checks/'+body['request_id'])
    finally:vlm_release.set();release.set()
    until(c,url,body['request_id'],'cancelled');assert not gpu.is_set()


def test_vlm_slot_released_while_another_run_segments(staged):
    c,url,app,vlm,entered,release,_=staged
    _,one=start(c,url);assert entered.wait(2)
    second='/api/inspection/runs/'+c.post('/api/inspection/runs',json={'provider':'opencv'}).json()['run_id']
    _,two=start(c,second)
    early,_=until(c,second,two['request_id'],'segmenting');assert len(vlm.calls)==2
    release.set();until(c,url,one['request_id'],'completed');until(c,second,two['request_id'],'completed')


def test_hash_and_owner_are_checked_before_any_inference(staged):
    c,url,app,vlm,_,release,_=staged
    bad={**frame(),'source_sha256':'0'*64,'request_id':uuid.uuid4().hex}
    assert c.post(url+'/checks',json=bad).status_code==422 and not vlm.calls
    release.set();first,body=start(c,url)
    other='/api/inspection/runs/'+c.post('/api/inspection/runs',json={'provider':'opencv'}).json()['run_id']
    assert c.get(other+'/checks/'+body['request_id']).status_code==404
    assert c.post(other+'/checks',json=body).status_code==409
    until(c,url,body['request_id'],'completed')


def test_unexpected_failure_after_localization_returns_preserved_snapshot(staged):
    c,url,app,_,_,release,_=staged
    def fail_wire(*a):raise RuntimeError('private provider details')
    app.state.inspection._wire=fail_wire;release.set()
    _,body=start(c,url);last,_=until(c,url,body['request_id'],'failed')
    assert last['error']=='inspection_failed' and last['result']['stage']=='localization'
    assert last['result']['public_result']['foreign_object_state']=='fail'
    assert all(not o['tracking_ready'] for o in last['result']['objects'])
    assert 'private provider details' not in str(last)
    deadline=time.monotonic()+2;identity=url.rsplit('/',1)[-1]
    while app.state.inspection_jobs.busy(identity) and time.monotonic()<deadline:time.sleep(.005)
    assert not app.state.inspection.get(identity).sessions


def test_clean_recheck_completes_without_a_segmenting_event(staged):
    c,url,app,vlm,_,release,_=staged;release.set()
    _,first=start(c,url);until(c,url,first['request_id'],'completed')
    vlm.value=observation(False);_,second=start(c,url,2)
    final,events=until(c,url,second['request_id'],'completed')
    assert [e['phase'] for e in events]==['queued','recognizing','completed']
    assert final['result']['segmentation_skipped'] and final['result']['segmentation_ms']==0
    assert final['result']['decision']['status']=='no_visible_anomaly'
