"""Exercise actual task contracts/API with controlled VLM results; never use cloud services."""
import base64
import hashlib
import io
import json
from pathlib import Path
import re
import threading
from time import monotonic
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from manual2ar.modules.guidance.registry import TaskRegistry, UNBOX, FIRST, LOAD, UNLOAD
from manual2ar.modules.guidance.server import create_app
from manual2ar.application.config import for_module
from manual2ar.paths import ROOT


class VisualClient:
    def __init__(self):
        self.calls=[];self.status='completed';self.confidence=.95;self.block=None;self.error=False
    def chat_structured(self,**args):
        self.calls.append(args)
        if self.block:self.block[0].set();self.block[1].wait(5)
        if self.error:raise RuntimeError('HTTP 401 PRIVATE-REMOTE-CONTENT')
        node=re.search(r'观察点[=：]([A-Z]\d+-C\d+)',args['prompt']).group(1)
        return {'status':self.status,'matched_step_id':node.split('-')[0],'inspection_id':node,
                'evidence':'受控输出：当前要求的区域清楚可见。','confidence':self.confidence,
                'manual_page':None,'manual_section':'受控验证','safe_to_advance':True,
                'next_action':'按当前指导补拍。','component_boxes_0_1000':[]}


@pytest.fixture(scope='module')
def registry():return TaskRegistry()


@pytest.fixture
def guide(tmp_path,registry):
    c=for_module(json.loads((ROOT/'configs/app.example.json').read_text()),'guidance');c['vlm']['api_key']='PRIVATE-TEST-KEY'
    fake=VisualClient();app=create_app(c,client=fake,log_root=tmp_path)
    # Task registry is immutable; the application still owns its own run engines.
    with TestClient(app) as client:yield client,fake,app.state.guidance,tmp_path


def cmd(v):return {'state_id':v['state_id'],'revision':v['revision']}
def url(v,tail=''):return '/api/guidance/runs/'+v['run_id']+('/'+tail if tail else '')
def start(client,task=FIRST,variant=None):
    args={'task_id':task}
    if variant is not None:args['variant_id']=variant
    r=client.post('/api/guidance/runs',json=args);assert r.status_code==201,r.text
    return r.json()
def confirm(client,v):
    r=client.post(url(v,'confirm'),json={**cmd(v),'inspection_id':v['pending_id'],'confirmed':True})
    assert r.status_code==200,r.text
    return r.json()
def advance(client,v):
    r=client.post(url(v,'advance'),json=cmd(v));assert r.status_code==200,r.text
    return r.json()
def action(client,v,name,confirmed=False):
    r=client.post(url(v,'actions/'+name),json={**cmd(v),'confirmed':confirmed});assert r.status_code==200,r.text
    return r.json()
def capture(v):
    file=io.BytesIO();Image.new('RGB',(64,48),(80,90,100)).save(file,'JPEG');raw=file.getvalue()
    return {**cmd(v),'inspection_id':v['pending_id'],'client_frame_id':max(0,v['last_client_frame_id'])+1,
            'image_base64':base64.b64encode(raw).decode(),'source_sha256':hashlib.sha256(raw).hexdigest()}
def tick(client,v):
    if v.get('navigation_policy')=='free':return advance(client,v)
    if not v['pending_id']:return advance(client,v)
    if v['channel']=='manual':return confirm(client,v)
    r=client.post(url(v,'verify'),json=capture(v));assert r.status_code==200,r.text
    return r.json()
def finish(client,v):
    for _ in range(80):
        if v['completed']:return v
        v=tick(client,v)
    raise AssertionError('Task did not terminate')
def p3(client):
    v=start(client)
    while v['state_id']!='P3':v=tick(client,v)
    return v


@pytest.mark.parametrize('task,variant,count',[(UNBOX,'standalone_unboxing',13),(UNBOX,'ams_lite_unboxing',13),(FIRST,'first_print_sd',4),
    (FIRST,'first_print_studio',4),(LOAD,'load_external_spool',6),(UNLOAD,'unload_external',5)])
def test_registered_variants_complete_independently(guide,task,variant,count):
    client,fake,_,_=guide;v=start(client,task,variant)
    assert v['step_count']==count and v['task_id']==task
    finished=finish(client,v);assert finished['status']=='completed'
    assert len(fake.calls)==(1 if task==LOAD else 0)
    assert client.get(url(finished,'report')).status_code==200


def test_catalog_and_reject_other_hardware_or_paths(guide):
    client,_,_,_=guide;c=client.get('/api/guidance/tasks').json()
    assert len(c['tasks'])==4
    assert {t['id'] for t in c['tasks']}=={UNBOX,FIRST,LOAD,UNLOAD}
    for task,variant in [('bambu_a1_mini_ams_lite','ams_lite'),(LOAD,'load_supplied_sample'),(UNBOX,'../../file')]:
        assert client.post('/api/guidance/runs',json={'task_id':task,'variant_id':variant}).status_code==422
    assert client.post('/api/guidance/runs',json={'task_id':LOAD,'parent_run_id':'forged'}).status_code==422
    for card in c['tasks']:assert client.get(card['thumbnail']['url']).status_code==200


def test_direct_readiness_has_no_fake_child_or_model_calls(guide):
    client,fake,service,_=guide;v=p3(client);v=confirm(client,v)
    assert v['can_advance'] and not v['child_receipts'] and not fake.calls
    _,engine,run=service.parts(v['run_id']);record=run.results['P3-C1']
    assert record['completion_source']=='manual_assertion' and not record['related_child_runs']
    assert finish(client,v)['completed']


def test_load_child_parent_guard_and_explicit_return_confirmation(guide):
    client,_,_,_=guide;parent=p3(client);old=parent
    child=action(client,parent,'guided_load');assert child['parent_run_id']==parent['run_id']
    waiting=client.get(url(parent)).json();assert waiting['status']=='waiting_child' and not waiting['can_advance']
    assert client.post(url(old,'confirm'),json={**cmd(old),'inspection_id':'P3-C1','confirmed':True}).status_code==409
    for op in ('advance','back','recheck'):assert client.post(url(waiting,op),json=cmd(waiting)).status_code==409
    assert client.post(url(child,'actions/return_parent'),json=cmd(child)).status_code==409
    child=finish(client,child);parent=action(client,child,'return_parent')
    assert parent['state_id']=='P3' and parent['pending_id']=='P3-C1' and not parent['can_advance']
    assert len(parent['child_receipts'])==1 and parent['child_receipts'][0]['status']=='completed'
    assert confirm(client,parent)['can_advance']
    assert client.post(url(child,'actions/return_parent'),json=cmd(child)).status_code==409


def test_replace_unload_then_load_not_auto_ready(guide):
    client,_,_,_=guide;parent=p3(client);unload=action(client,parent,'guided_replace')
    assert unload['task_id']==UNLOAD
    unload=finish(client,unload);parent=action(client,unload,'return_parent')
    assert parent['status']=='waiting_child' and parent['pending_id']=='P3-C1' and not parent['can_advance']
    assert {a['id'] for a in parent['available_actions']}=={'start_next','stop_sequence'}
    child=action(client,parent,'start_next');assert child['task_id']==LOAD
    child=finish(client,child);parent=action(client,child,'return_parent')
    assert parent['status']=='running' and not parent['can_advance']
    assert [r['task_id'] for r in parent['child_receipts']]==[UNLOAD,LOAD]
    assert confirm(client,parent)['can_advance']


def test_cancel_load_after_unload_keeps_not_ready(guide):
    client,_,_,_=guide;parent=p3(client);d=finish(client,action(client,parent,'guided_replace'))
    parent=action(client,d,'return_parent');load=action(client,parent,'start_next')
    r=client.post(url(load,'cancel'),json=cmd(load));assert r.status_code==200
    parent=r.json();assert parent['status']=='running' and not parent['can_advance']
    assert [r['status'] for r in parent['child_receipts']]==['completed','cancelled']
    assert '准备仍需' in parent['flow_notice']
    assert client.post(url(parent,'advance'),json=cmd(parent)).status_code==409


def test_cancelled_child_does_not_become_completed_child_evidence(guide):
    client,_,service,_=guide;parent=p3(client);child=action(client,parent,'guided_load')
    parent=client.post(url(child,'cancel'),json=cmd(child)).json()
    parent=confirm(client,parent)
    _,_,run=service.parts(parent['run_id'])
    assert run.results['P3-C1']['completion_source']=='manual_assertion'
    assert not run.results['P3-C1']['related_child_runs']


def test_stop_sequence_and_completed_child_whole_flow_cancel(guide):
    client,_,_,_=guide;parent=p3(client);d=finish(client,action(client,parent,'guided_replace'))
    parent=action(client,d,'return_parent');parent=action(client,parent,'stop_sequence')
    assert parent['status']=='running' and parent['pending_id']=='P3-C1'
    child=finish(client,action(client,parent,'guided_load'))
    r=client.post(url(child,'cancel-flow'),json=cmd(child));assert r.status_code==200
    assert r.json()['status']=='cancelled'
    assert r.json()['child_receipts'][-1]['status']=='completed'


@pytest.mark.parametrize('task,state,target',[(LOAD,'L6','L5'),(UNLOAD,'D4','D2')])
def test_retry_requires_device_confirmation_and_invalidates(guide,task,state,target):
    client,_,service,_=guide;v=start(client,task)
    while v['state_id']!=state:v=tick(client,v)
    assert client.post(url(v,'actions/retry'),json=cmd(v)).status_code==400
    v=action(client,v,'retry',True);assert v['state_id']==target and not v['can_advance']
    _,engine,run=service.parts(v['run_id']);assert target+'-C1' not in run.results


@pytest.mark.parametrize('mode',['uncertain','wrong_operation','low_confidence','provider_error'])
def test_load_visual_rejection_cannot_be_manually_bypassed(guide,mode):
    client,fake,_,_=guide;v=advance(client,confirm(client,start(client,LOAD)))
    assert v['state_id']=='L2'
    if mode=='low_confidence':fake.confidence=.1
    elif mode=='provider_error':fake.error=True
    else:fake.status=mode
    assert client.post(url(v,'confirm'),json={**cmd(v),'inspection_id':v['pending_id'],'confirmed':True}).status_code==409
    r=client.post(url(v,'verify'),json=capture(v));assert r.status_code==200
    after=r.json();assert not after['can_advance'] and after['pending_id']=='L2-C1'
    assert 'PRIVATE-REMOTE' not in r.text
    assert client.post(url(after,'advance'),json=cmd(after)).status_code==409


def test_per_node_prompt_frame_echo_and_session_isolation(guide):
    client,fake,_,_=guide;load=advance(client,confirm(client,start(client,LOAD)))
    other=start(client,UNLOAD);before=client.get(url(other)).json()
    frame=capture(load);view=client.post(url(load,'verify'),json=frame).json()
    assert 'L2-C1' in fake.calls[-1]['prompt'] and len(fake.calls[-1]['images_base64'])==1
    item=view['observations'][0];assert item['source_sha256']==frame['source_sha256']
    assert client.get(item['image_url']).status_code==200
    assert client.get(url(other)).json()['state_id']==before['state_id']
    assert client.post(url(load,'verify'),json=frame).status_code==409
    assert client.post(url(other,'actions/guided_load'),json=cmd(other)).status_code==409


def test_no_global_lock_across_vlm_and_busy_flow_cannot_cancel(guide):
    client,fake,_,_=guide;parent=p3(client);load=action(client,parent,'guided_load')
    load=advance(client,confirm(client,load));entered,release=threading.Event(),threading.Event();fake.block=(entered,release)
    result=[];thread=threading.Thread(target=lambda:result.append(client.post(url(load,'verify'),json=capture(load))))
    thread.start();assert entered.wait(3)
    try:
        assert client.post(url(load,'cancel'),json=cmd(load)).status_code==409
        current=client.get(url(parent)).json()
        assert client.post(url(current,'cancel-flow'),json=cmd(current)).status_code==409
        other=start(client,UNLOAD);assert confirm(client,other)['can_advance']
    finally:release.set();thread.join(5)
    assert result and result[0].status_code==200


def test_idle_cleanup_removes_whole_flow_without_dangling_parent(guide):
    client,_,service,_=guide;parent=p3(client);child=action(client,parent,'guided_load')
    service.meta[parent['run_id']]['last_active']=monotonic()-100000
    start(client,UNLOAD)
    assert client.get(url(parent)).status_code==404 and client.get(url(child)).status_code==404


def test_ended_records_release_capacity_but_keep_disk_logs(guide):
    client,_,service,folder=guide
    service.config['sessions']['max_runs']=4
    ended=start(client,UNLOAD)
    assert client.post(url(ended,'cancel-flow'),json=cmd(ended)).status_code==200
    for _ in range(4):start(client,UNLOAD)
    assert client.get(url(ended)).status_code==404
    assert (folder/ended['run_id']/'events.jsonl').exists()



def test_task_boundaries_and_official_overview(guide):
    client,_,service,_=guide
    unbox=start(client,UNBOX); first=start(client,FIRST)
    assert [s['id'] for s in first['task_info']['steps']]==['P3','P4','P5','P6']
    assert unbox['step_count']==13 and first['step_count']==4
    assert first['task_info']['entry_requirements']
    info=unbox['task_info'];assert '外挂料盘' in info['title']
    assert any('初始化和校准' in s['title'] for s in info['steps'])
    for section in info['official_sections']:
        assert section['url'].startswith('https://wiki.bambulab.com/')
        assert section['citation_id'] and section['captured_at'] and section['quote']
    _,engine,_=service.parts(unbox['run_id'])
    assert engine.task.params['presentation']['U11']['reference_images']
    assert any('初始化' in engine.task.cards[s.state_id].title for s in engine.task.document.states)


@pytest.mark.parametrize('recover',[True,False])
def test_malformed_identity_is_retried_but_never_silently_relabelled(guide,recover):
    client,fake,_,root=guide;v=advance(client,confirm(client,start(client,LOAD)))
    original=fake.chat_structured;attempts=[]
    def faulty(**args):
        result=original(**args);attempts.append(args)
        if len(attempts)==1 or not recover:result['matched_step_id']='L2-C1'
        return result
    fake.chat_structured=faulty
    response=client.post(url(v,'verify'),json=capture(v));assert response.status_code==200
    after=response.json();node=after['observations'][0]
    assert len(attempts)==2 and after['can_advance']==recover
    assert node['failure_kind']==('' if recover else 'invalid_contract')
    schema=attempts[-1]['schema']['properties']
    assert schema['matched_step_id']['const']=='L2' and schema['inspection_id']['const']=='L2-C1'
    assert not {'manual_page','manual_section','predicates'} & schema.keys()
    diagnostics=list((root/v['run_id']).glob('*/diagnostics.json'));assert len(diagnostics)==1
    recorded=json.loads(diagnostics[0].read_text());assert recorded[0]['status']=='invalid_contract'
    assert recorded[0]['fields'][0]['field']=='matched_step_id'
    assert list((root/v['run_id']).glob('*/model_response-1.json'))
    for path in root.rglob('*.json*'):assert 'PRIVATE-TEST-KEY' not in path.read_text()
