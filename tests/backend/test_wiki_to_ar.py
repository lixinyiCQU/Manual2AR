"""Source-to-AR contract tests; controlled inference is never hardware proof."""
import base64
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import time
from types import SimpleNamespace
import uuid
from PIL import Image
import pytest
from fastapi.testclient import TestClient
from manual2ar.application.config import for_module
from manual2ar.application.server import create_app
from manual2ar.knowledge.extract import extract,canonical
from manual2ar.knowledge.retrieval import EvidenceIndex
from tests.backend.test_application import configuration,Knowledge,ComponentVLM
from tests.backend.inspection.test_pipeline import FakeVLM,FakeTracker
from tests.backend.guidance.test_spatial import frame


def wiki(tmp_path):
    url='https://wiki.example/zh/a1-mini/manual/assembly'
    html='<article><h2>安装料盘支架</h2><h3>1. 固定底座</h3><p>使用两颗M3-8螺丝固定料盘支架底座，注意安装方向。</p><img src="/reference.jpg"><h3>2. 滑入支架</h3><p>从上向下滑入料盘支架，方向应匹配底座插槽。</p><h2>连接电源</h2><p>连接电源并启动设备。</p></article>'
    ex,_=extract(html,url);record=dict(url=url,title='安装设备',page=dict(response={'body':{'sha256':'body'}},completed_at='date'))
    photo=tmp_path/'official.jpg';Image.new('RGB',(320,240),'blue').save(photo,'JPEG')
    return SimpleNamespace(pages={'p':record},by_url={canonical(url,page=True):'p'},snapshot_sha256='archive',
        archive_path=tmp_path/'snapshot/archive.json',assets={'image':dict(url='https://wiki.example/reference.jpg',object={'sha256':hashlib.sha256(photo.read_bytes()).hexdigest()})},
        object_path=lambda _:photo,page=lambda _:record,extraction=lambda _:deepcopy(ex))


class GeneratedVLM:
    def __init__(self):self.calls=[];self.fail=False;self.unsupported=False
    def chat_structured(self,**kw):
        self.calls.append(kw)
        if self.fail:raise RuntimeError('provider secret must not escape')
        title=kw['schema'].get('title')
        if title=='SectionSelection':return dict(section_id=0,sufficient=True,reason='受控选择安装章节')
        if title=='Scene':return dict(retrieval_query='安装料盘支架 底座',visible_parts=['底座'],uncertainties=['紧固未知'],summary='可见底座，紧固程度未知。')
        if title=='DirectDraft':
            source=json.JSONDecoder().raw_decode(kw['prompt'].split('\nSOURCE:\n')[1])[0];citation=next(iter(source['evidence']))
            def claim(text,origin='inferred'):return dict(text=text,origin=origin,citation_ids=[citation],rationale='受控原文解释')
            states=[];observations=[]
            for i,instruction in enumerate(('用两颗M3-8螺丝固定料盘支架底座','从上向下滑入料盘支架')):
                action='base' if i==0 else 'slide';component='source:底座' if i==0 else 'source:料盘支架'
                after=['底座贴合立柱','底座已真正紧固'] if i==0 else ['支架与底座连接']
                states.append(dict(action_id=action,instruction=claim(instruction,'explicit'),preconditions=[],postconditions=[claim(v) for v in after],wrong_states=[],warnings=[],target_components=[component]))
                for j,value in enumerate(after):
                    channel='manual' if j==1 else 'vision'
                    observations.append(dict(action_id=action,postcondition_index=j,component_ids=[component],viewpoint='front',
                        capture_instruction=claim('拍清连接处','observation_policy'),visibility_limit=claim('遮挡时不确定','observation_policy'),
                        evidence_type='connection',visualization='none' if channel=='manual' else 'mask',verification_channel=channel,requires_same_frame=False))
            return dict(states=states,observations=observations,limitations=[])
        if title=='Bindings':return dict(states=[dict(state_id='S'+str(i+1),capability='unsupported' if self.unsupported else cap,
            component_ids=['spool_holder_base'] if i==0 else ['external_spool_holder','spool_holder_base'],rationale='受控语义绑定') for i,cap in enumerate(('holder.base','holder.slide'))])
        if title=='SceneCheck':
            identity=json.JSONDecoder().raw_decode(kw['prompt'].split('照片身份：')[1])[0]
            return dict(**identity,evidence_image_id='current_scene',evidence_bbox_0_1000=[100,100,400,600],
                status='completed',confidence=.95,evidence='受控现场可见连接',next_action='请人工确认紧固')
        return dict(status='completed',confidence=.95,evidence='受控可见连接',next_action='请人工确认紧固')


def question():
    stream=io.BytesIO();Image.new('RGB',(320,240),'white').save(stream,'JPEG');raw=stream.getvalue()
    return dict(intent='我要安装料盘支架',image_base64=base64.b64encode(raw).decode(),source_sha256=hashlib.sha256(raw).hexdigest(),
        client_frame_id=1,capture_id=uuid.uuid4().hex,camera_signature='controlled-camera')


def completed(client,identity):
    deadline=time.monotonic()+10
    while time.monotonic()<deadline:
        value=client.get('/api/guidance/pipeline/jobs/'+identity).json()
        if value['status'] in ('ready','unsupported','failed','approved'):return value
        time.sleep(.02)
    raise AssertionError('job did not finish')


@pytest.fixture
def setup(tmp_path,monkeypatch):
    fake=GeneratedVLM();c=configuration(tmp_path)
    app=create_app(c,clients={'learning':ComponentVLM(),'guidance':fake,'inspection':FakeVLM()},knowledge_store=Knowledge(),tracker_factory=lambda _:FakeTracker())
    service=app.state.modules['guidance'].state.pipeline;service.index=EvidenceIndex(wiki(tmp_path))
    with TestClient(app) as client:yield client,service,fake


def test_retrieves_parent_task_with_both_actions_not_unrelated_chapters(tmp_path):
    index=EvidenceIndex(wiki(tmp_path));bundle=index.retrieve('安装料盘支架底座',tmp_path)
    text='\n'.join(e['text'] for e in bundle['evidence'].values())
    assert '从上向下滑入' in text and '两颗M3-8' in text and '连接电源并启动' not in text
    assert len(json.loads((tmp_path/'retrieval.json').read_text())['selected'])==1


def test_question_to_generated_candidate_and_isolated_ar_routes(setup):
    client,service,fake=setup;command=question();response=client.post('/api/guidance/pipeline/jobs',json=command)
    assert response.status_code==202,response.text
    value=completed(client,response.json()['id']);assert value['status']=='ready',value
    candidate=value['candidate'];identity=value['id'];api=f'/api/guidance/pipeline/candidates/{identity}/spatial'
    assert value['source_sha256']==command['source_sha256'] and value['capture_id']==command['capture_id']
    assert client.get(api+'/config').status_code==404
    bad=client.post('/api/guidance/pipeline/jobs/'+identity+'/approve',json={'confirmed':True,'procedure_sha256':'0'*64})
    assert bad.status_code==409
    assert client.post('/api/guidance/pipeline/jobs/'+identity+'/approve',json={'confirmed':True,'procedure_sha256':candidate['procedure_sha256']}).status_code==200
    plan=client.get(api+'/config').json();assert [a['instruction'] for a in plan['actions']]==[s['instruction'] for s in candidate['states']]
    s=client.post(api+'/sessions',json={'camera_id':'fixture','mode':'camera','visual_client_revision':'machine-workframe-v1'}).json()['session_id']
    session=api+'/sessions/'+s
    assert client.post(session+'/frames',json=frame(action='holder.slide')).status_code==409
    assert client.post(session+'/frames',json=frame(action='holder.base')).status_code==200
    checked=client.post(session+'/verify',json={'action_id':'holder.base','client_frame_id':1}).json()
    assert checked['status']=='uncertain' and checked['manual_pending']==['S1-C2']
    assert not checked['u7_sequence']['base_approved']
    checked=client.post(session+'/manual-conditions',json={'confirmed':True,'action_id':'holder.base','inspection_ids':['S1-C2']}).json()
    assert checked['u7_sequence']['base_approved']
    assert client.post(session+'/frames',json=frame(number=2,action='holder.slide')).status_code==200
    # Recognition/verification are driven by generated task conditions, not authored U7 acceptance.
    assert '底座贴合立柱' in fake.calls[-1]['prompt']
    assert not list((service.root.parent/'guidance').glob('*/flow.json'))


def test_bad_photo_and_hash_never_call_model(setup):
    client,_,fake=setup;command=question();command['source_sha256']='0'*64
    assert client.post('/api/guidance/pipeline/jobs',json=command).status_code==422
    assert fake.calls==[]


def test_provider_failure_retained_without_handwritten_fallback(setup):
    client,service,fake=setup;fake.fail=True
    identity=client.post('/api/guidance/pipeline/jobs',json=question()).json()['id'];value=completed(client,identity)
    assert value['status']=='failed' and 'candidate' not in value and 'secret' not in json.dumps(value)
    assert (service.root/'jobs'/identity/'failure.json').exists()


def test_unsupported_binding_does_not_launch_u7(setup):
    client,_,fake=setup;fake.unsupported=True
    identity=client.post('/api/guidance/pipeline/jobs',json=question()).json()['id'];value=completed(client,identity)
    assert value['status']=='unsupported' and not value['candidate']['spatial_ready']
    assert client.get(f'/api/guidance/pipeline/candidates/{identity}/spatial/config').status_code==404


def test_candidate_edits_invalidate_approval(setup):
    client,service,_=setup
    identity=client.post('/api/guidance/pipeline/jobs',json=question()).json()['id'];value=completed(client,identity)
    path=service.root/'jobs'/identity/'compile/task/procedure.json';path.write_bytes(path.read_bytes()+b' ')
    assert client.post('/api/guidance/pipeline/jobs/'+identity+'/approve',json={'confirmed':True,'procedure_sha256':value['candidate']['procedure_sha256']}).status_code==409


def test_resume_restores_photo_and_task_without_generating_again(setup):
    client,service,fake=setup
    assert client.get('/api/guidance/pipeline/jobs/latest').json()['status']=='empty'
    command=question();identity=client.post('/api/guidance/pipeline/jobs',json=command).json()['id']
    value=completed(client,identity);calls=len(fake.calls)
    resumed=client.get('/api/guidance/pipeline/jobs/latest').json()
    assert resumed['id']==identity and resumed['candidate']['procedure_sha256']==value['candidate']['procedure_sha256']
    assert resumed['camera_signature']==command['camera_signature']
    photo=client.get('/api/guidance/pipeline/jobs/'+identity+'/scene')
    assert photo.status_code==200 and photo.headers['cache-control']=='no-store'
    assert hashlib.sha256(photo.content).hexdigest()==command['source_sha256']
    assert len(fake.calls)==calls and value['status']=='ready'
    (service.root/'jobs'/identity/'scene.jpg').write_bytes(b'changed')
    assert client.get('/api/guidance/pipeline/jobs/'+identity+'/scene').status_code==409


def test_ready_task_can_resume_after_backend_restart(setup):
    from manual2ar.modules.guidance.server import create_app as guidance_app
    client,service,fake=setup
    command=question();identity=client.post('/api/guidance/pipeline/jobs',json=command).json()['id'];value=completed(client,identity)
    calls=len(fake.calls)
    app=guidance_app(service.config,fake,wiki_settings=service.wiki_settings)
    with TestClient(app) as restored:
        latest=restored.get('/api/guidance/pipeline/jobs/latest').json()
        assert latest['status']=='ready' and latest['id']==identity
        assert latest['candidate']['procedure_sha256']==value['candidate']['procedure_sha256']
        assert hashlib.sha256(restored.get('/api/guidance/pipeline/jobs/'+identity+'/scene').content).hexdigest()==command['source_sha256']
    assert len(fake.calls)==calls


def approved_runtime(setup):
    client,pipeline,fake=setup
    identity=client.post('/api/guidance/pipeline/jobs',json=question()).json()['id'];value=completed(client,identity)
    assert client.post('/api/guidance/pipeline/jobs/'+identity+'/approve',json={'confirmed':True,'procedure_sha256':value['candidate']['procedure_sha256']}).status_code==200
    api=f'/api/guidance/pipeline/candidates/{identity}/spatial'
    spatial=pipeline.spatial[identity]
    sid=client.post(api+'/sessions',json={'camera_id':'fixture','visual_client_revision':'machine-workframe-v1'}).json()['session_id']
    return client,pipeline,fake,spatial,api+'/sessions/'+sid,sid


def test_candidate_inherits_camera_only_and_old_geometry_is_quarantined(setup):
    client,pipeline,fake=setup
    original=Path(pipeline.config['runtime_dir'])/'guidance-spatial/profiles'
    groups=('cameras','rigs','machines','motions','orientations','rig-validity')
    for name in groups:
        folder=original/name;folder.mkdir(parents=True);(folder/'fixture.json').write_text('{}')
    _,_,_,spatial,session,sid=approved_runtime(setup)
    assert spatial.profile('cameras','fixture').exists()
    assert all(not (spatial.root/'profiles'/group).exists() for group in groups if group!='cameras')
    assert all((original/group/'fixture.json').read_text()=='{}' for group in groups)
    # Simulate a candidate created by the previous implementation, without its new policy.
    (spatial.root/'profile-policy.json').unlink()
    for group in groups[1:]:spatial.store_profile(spatial.profile(group,'a1-mini'),{'old_scene':True})
    from manual2ar.modules.guidance.pipeline_spatial import ExperimentSpatial
    restored=ExperimentSpatial(pipeline.config,pipeline.registry,fake,spatial.candidate)
    try:
        assert restored.profile('cameras','fixture').exists()
        assert all(not (restored.root/'profiles'/group).exists() for group in groups[1:])
        saved=list((restored.root/'backups').rglob('a1-mini.json'))
        assert len(saved)==5 and all(json.loads(p.read_text())=={'old_scene':True} for p in saved)
    finally:restored.part_tracking.shutdown()


def test_candidate_own_positions_survive_restart_but_need_explicit_start(setup):
    from manual2ar.modules.guidance.spatial.simulation import calibration,targets
    from manual2ar.modules.guidance.pipeline_spatial import ExperimentSpatial
    client,pipeline,fake,spatial,_,_=approved_runtime(setup)
    spatial.store_profile(spatial.profile('cameras','fixture'),calibration())
    spatial.store_profile(spatial.profile('rigs','a1-mini'),targets(spatial.actions))
    restored=ExperimentSpatial(pipeline.config,pipeline.registry,fake,spatial.candidate)
    try:
        assert restored.profile('rigs','a1-mini').exists()
        api=f'/api/guidance/pipeline/candidates/{spatial.candidate.identity}/spatial'
        result=client.post(api+'/sessions',json={'camera_id':'fixture','visual_client_revision':'machine-workframe-v1','reuse_targets':True}).json()
        assert result['has_saved_targets'] and not result['target_reuse_confirmed']
        session=api+'/sessions/'+result['session_id']
        view=client.post(session+'/frames',json=frame(action='holder.base')).json()
        assert view['visual'] is None and not view['target_ready'] and view['preflight']['can_start']
        assert client.post(session+'/reuse',json={'confirmed':True}).status_code==200
        view=client.post(session+'/frames',json=frame(number=2,action='holder.base')).json()
        assert view['visual'] is not None and view['target_ready']
        assert client.post(api+'/sessions',json={'camera_id':'fixture','mode':'replay'}).status_code==409
    finally:restored.part_tracking.shutdown()


def test_verification_sends_only_current_photo_and_binds_evidence(setup):
    client,_,fake,spatial,session,sid=approved_runtime(setup)
    assert spatial.candidate.task.images_for(spatial.states['holder.base'])
    sent=frame(action='holder.base');client.post(session+'/frames',json=sent)
    response=client.post(session+'/verify',json={'action_id':'holder.base','client_frame_id':1})
    assert response.status_code==200,response.text
    call=fake.calls[-1]
    assert call['schema']['title']=='SceneCheck' and call['images_base64']==[sent['image_base64']]
    assert response.json()['manual_pending']==['S1-C2']
    events=[json.loads(row) for row in (spatial.root/'runs'/sid/'events.jsonl').read_text().splitlines()]
    result=next(e for e in events if e['event']=='compiled.verification')['results'][0]
    assert result['evidence_image_id']=='current_scene' and result['source_sha256']==sent['source_sha256']
    assert result['evidence_bbox_0_1000']==[100,100,400,600]


@pytest.mark.parametrize('changed',[
    {'source_sha256':'0'*64},{'inspection_id':'other-condition'},
    {'evidence_image_id':'official_reference'},{'evidence_bbox_0_1000':[]},
    {'evidence_bbox_0_1000':[0,0,1001,900]},{'evidence':''}])
def test_foreign_or_missing_evidence_cannot_unlock_next_step(setup,monkeypatch,changed):
    client,_,fake,spatial,session,sid=approved_runtime(setup)
    original=fake.chat_structured
    def invalid(**kwargs):
        answer=original(**kwargs)
        if kwargs['schema']['title']=='SceneCheck':answer.update(changed)
        return answer
    monkeypatch.setattr(fake,'chat_structured',invalid)
    client.post(session+'/frames',json=frame(action='holder.base'))
    assert client.post(session+'/verify',json={'action_id':'holder.base','client_frame_id':1}).status_code==502
    assert not spatial.u7_progress(spatial.sessions[sid])['base_approved']
    assert client.post(session+'/frames',json=frame(number=2,action='holder.slide')).status_code==409


def test_failed_visual_check_never_prompts_or_accepts_manual_override(setup,monkeypatch):
    client,_,fake,spatial,session,sid=approved_runtime(setup)
    original=fake.chat_structured
    def incomplete(**kwargs):
        result=original(**kwargs)
        if kwargs['schema']['title']=='SceneCheck':result['status']='not_completed'
        return result
    monkeypatch.setattr(fake,'chat_structured',incomplete)
    client.post(session+'/frames',json=frame(action='holder.base'))
    result=client.post(session+'/verify',json={'action_id':'holder.base','client_frame_id':1}).json()
    assert result['status']=='not_completed' and result['manual_pending']==[]
    assert client.post(session+'/manual-conditions',json={'confirmed':True,'action_id':'holder.base','inspection_ids':['S1-C2']}).status_code==409


def test_manual_confirmation_cannot_reuse_another_target_context(setup):
    client,_,_,spatial,session,sid=approved_runtime(setup)
    client.post(session+'/frames',json=frame(action='holder.base'))
    client.post(session+'/verify',json={'action_id':'holder.base','client_frame_id':1})
    client.post(session+'/frames',json=frame(number=2,action='holder.base',target_id='second'))
    client.post(session+'/frames',json=frame(number=3,action='holder.base'))
    assert client.post(session+'/manual-conditions',json={'confirmed':True,'action_id':'holder.base','inspection_ids':['S1-C2']}).status_code==409
    assert not spatial.u7_progress(spatial.sessions[sid])['base_approved']


def test_late_failed_request_does_not_erase_newer_check(setup,monkeypatch):
    import threading
    from concurrent.futures import ThreadPoolExecutor
    client,_,fake,spatial,session,sid=approved_runtime(setup)
    original=fake.chat_structured;entered=threading.Event();release=threading.Event();calls=0
    def delayed(**kwargs):
        nonlocal calls
        if kwargs['schema']['title']=='SceneCheck':
            calls+=1
            if calls==1:
                entered.set();assert release.wait(5);raise RuntimeError('old request failed')
        return original(**kwargs)
    monkeypatch.setattr(fake,'chat_structured',delayed)
    client.post(session+'/frames',json=frame(action='holder.base'))
    with ThreadPoolExecutor(max_workers=1) as pool:
        old=pool.submit(client.post,session+'/verify',json={'action_id':'holder.base','client_frame_id':1})
        try:
            assert entered.wait(5)
            assert client.post(session+'/verify',json={'action_id':'holder.base','client_frame_id':1}).status_code==200
            result=client.post(session+'/manual-conditions',json={'confirmed':True,'action_id':'holder.base','inspection_ids':['S1-C2']})
            assert result.json()['u7_sequence']['base_approved']
        finally:release.set()
        assert old.result().status_code==502
    assert spatial.u7_progress(spatial.sessions[sid])['base_approved']


def test_late_success_after_target_roundtrip_is_rejected(setup,monkeypatch):
    client,_,fake,spatial,session,sid=approved_runtime(setup)
    original=fake.chat_structured
    def switch_targets(**kwargs):
        result=original(**kwargs)
        if kwargs['schema']['title']=='SceneCheck':
            client.post(session+'/frames',json=frame(number=2,action='holder.base',target_id='second'))
            client.post(session+'/frames',json=frame(number=3,action='holder.base'))
        return result
    monkeypatch.setattr(fake,'chat_structured',switch_targets)
    client.post(session+'/frames',json=frame(action='holder.base'))
    assert client.post(session+'/verify',json={'action_id':'holder.base','client_frame_id':1}).status_code==409
    assert not spatial.u7_progress(spatial.sessions[sid])['base_approved']
    assert client.post(session+'/manual-conditions',json={'confirmed':True,'action_id':'holder.base','inspection_ids':['S1-C2']}).status_code==409


def test_expired_photo_result_clears_pending_without_unlocking(setup,monkeypatch):
    client,_,fake,spatial,session,sid=approved_runtime(setup)
    original=fake.chat_structured
    def expired(**kwargs):
        result=original(**kwargs)
        if kwargs['schema']['title']=='SceneCheck':
            from manual2ar.modules.guidance import pipeline_spatial
            clock=time.monotonic
            monkeypatch.setattr(pipeline_spatial,'time',SimpleNamespace(monotonic=lambda:clock()+121))
        return result
    monkeypatch.setattr(fake,'chat_structured',expired)
    client.post(session+'/frames',json=frame(action='holder.base'))
    assert client.post(session+'/verify',json={'action_id':'holder.base','client_frame_id':1}).status_code==409
    assert not spatial.u7_progress(spatial.sessions[sid])['base_approved']
    assert 'pending_base' not in spatial.sessions[sid].u7_checks


def test_old_photo_cannot_start_new_check_after_target_roundtrip(setup):
    client,_,fake,spatial,session,sid=approved_runtime(setup)
    client.post(session+'/frames',json=frame(action='holder.base'))
    client.post(session+'/frames',json=frame(number=2,action='holder.base',target_id='second'))
    client.post(session+'/frames',json=frame(number=3,action='holder.base'))
    calls=len(fake.calls)
    assert client.post(session+'/verify',json={'action_id':'holder.base','client_frame_id':1}).status_code==409
    assert len(fake.calls)==calls and 'pending_base' not in spatial.sessions[sid].u7_checks


def test_candidate_edits_cannot_be_confirmed_manually(setup):
    client,_,_,spatial,session,sid=approved_runtime(setup)
    client.post(session+'/frames',json=frame(action='holder.base'))
    checked=client.post(session+'/verify',json={'action_id':'holder.base','client_frame_id':1})
    assert checked.json()['manual_pending']==['S1-C2']
    path=spatial.candidate.run/'compile/task/procedure.json';path.write_bytes(path.read_bytes()+b' ')
    assert client.post(session+'/manual-conditions',json={'confirmed':True,'action_id':'holder.base','inspection_ids':['S1-C2']}).status_code==409
    assert not spatial.u7_progress(spatial.sessions[sid])['base_approved']


@pytest.mark.parametrize('artifact',['task/procedure.json','binding/result.json'])
def test_candidate_integrity_survives_process_restart(setup,artifact):
    from manual2ar.modules.guidance.server import create_app as guidance_app
    client,service,fake=setup
    identity=client.post('/api/guidance/pipeline/jobs',json=question()).json()['id'];value=completed(client,identity)
    assert value['candidate']['integrity_policy']=='persistent_manifest'
    assert client.post('/api/guidance/pipeline/jobs/'+identity+'/approve',json=dict(confirmed=True,procedure_sha256=value['procedure_sha256'])).status_code==200
    candidate=service.candidates[identity];path=candidate.compile/artifact;path.write_text(path.read_text()+' ')
    app=guidance_app(service.config,fake,wiki_settings=service.wiki_settings)
    with TestClient(app) as restored:
        record=restored.get('/api/guidance/pipeline/jobs/'+identity).json()
        assert record['status']=='failed' and record['failure_code']=='candidate_integrity'
        assert restored.get('/api/guidance/pipeline/candidates/'+identity+'/spatial/config').status_code==404


def test_malformed_manifest_quarantines_candidate_without_stopping_backend(setup):
    from manual2ar.modules.guidance.server import create_app as guidance_app
    client,service,fake=setup
    identity=client.post('/api/guidance/pipeline/jobs',json=question()).json()['id'];completed(client,identity)
    service.candidates[identity].manifest.write_text('[]')
    with TestClient(guidance_app(service.config,fake,wiki_settings=service.wiki_settings)) as restored:
        record=restored.get('/api/guidance/pipeline/jobs/'+identity).json()
        assert record['status']=='failed' and record['failure_code']=='candidate_integrity'
