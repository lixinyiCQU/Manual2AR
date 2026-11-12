"""Official compilation activates the baseline runtime with generated IDs, never GT fallback."""
import json
import time

from fastapi.testclient import TestClient
import pytest

from manual2ar.application.config import for_module, load
from manual2ar.modules.guidance.server import create_app
from manual2ar.modules.guidance import baseline_spatial, official_compiler
from manual2ar.modules.guidance.spatial.simulation import calibration, targets
from baseline.tests.test_compiler import FakeClient, official_fixture
from tests.backend.guidance.test_baseline_ar import NeverLegacyModel, frame


@pytest.fixture
def compiled(tmp_path, monkeypatch):
    sources, root, proposal, _ = official_fixture(tmp_path, count=2)
    config = for_module(load(), 'guidance')
    config['runtime_dir'] = str(tmp_path / 'runtime')
    app = create_app(config, NeverLegacyModel(), wiki_settings={'archive': 'controlled-fixture'})
    manager = app.state.official_compiler
    manager.compiler_client = FakeClient(proposal)
    monkeypatch.setattr(official_compiler, 'retrieve', lambda *a, **k: (sources, root, {'method': 'controlled-official-fixture'}))
    def no_gt(*args, **kwargs):
        raise AssertionError('Compiled runtime tried to read GT')
    monkeypatch.setattr(baseline_spatial, 'load_bundle', no_gt)
    with TestClient(app) as client:
        response = client.post('/api/guidance/compiled/jobs', json={'intent': '我已完成底座，现在希望安装夹具手柄'})
        assert response.status_code == 202, response.text
        identity = response.json()['id']
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            result = client.get('/api/guidance/compiled/jobs/' + identity).json()
            if result['status'] not in ('queued', 'compiling'):
                break
            time.sleep(.01)
        yield client, manager, identity, result


class VisibleFacts:
    kind = 'controlled_provider'
    connected = False
    def call(self, prompt, schema, images):
        query = json.JSONDecoder().raw_decode(prompt.split('QUERY:', 1)[1])[0]
        rows = []
        for q in query['queries']:
            row = dict(query_id=q['id'], observability='observable', coverage='complete', region={'xyxy':[0,0,1000,1000]},
                value='seated' if q['kind']=='mount_relation' else ('connected' if self.connected else 'separate') if q['kind']=='connection_relation' else 'instances',
                evidence_boxes=[{'xyxy':[100,100,900,900]}], instances=[], evidence='受控可见事实，不是实物标签')
            if q['kind']=='fastener_instances':
                row.update(evidence_boxes=[], instances=[dict(location=slot, box={'xyxy':[200,100+i*300,300,200+i*300]}) for i,slot in enumerate(q['location_ids'])])
            rows.append(row)
        return json.dumps(dict(evidence_image_id='current_scene', source_sha256=query['source_sha256'], findings=rows)), dict(model='controlled',usage={})


def test_compiled_candidate_preview_and_generated_state_loop(compiled):
    client, manager, identity, result = compiled
    assert result['status']=='ready', result
    assert result['gt_used_as_input'] is False and 'fasten_fixture' in result['preview']
    path='/api/guidance/compiled/jobs/'+identity
    assert client.post(path+'/use',json=dict(manifest_sha256='0'*64,acknowledge_experimental=True)).status_code==409
    used=client.post(path+'/use',json=dict(manifest_sha256=result['manifest_sha256'],acknowledge_experimental=True))
    assert used.status_code==200, used.text
    prefix=used.json()['spatial_prefix']
    runtime=manager.runtimes[identity]
    assert runtime.task.id=='fixture.attach_handle'
    assert client.get(prefix+'/config').json()['task_origin']=='automatic_official_compilation'
    assert client.get(prefix+'/official-images/figure.fixture').status_code==200
    runtime.photo_client=VisibleFacts()
    for group,value in [('cameras',calibration()),('rigs',targets(runtime.actions))]:
        runtime.store_profile(runtime.profile(group,'compiled-camera'),value)
    begin=client.post(prefix+'/sessions',json=dict(camera_id='compiled-camera',rig_id='compiled-camera',reuse_targets=True,visual_client_revision='machine-workframe-v1'))
    assert begin.status_code==201,begin.text
    api=prefix+'/sessions/'+begin.json()['session_id']
    assert begin.json()['execution']['scope']=='experimental_compiled_photo_analysis'
    assert frame(client,api,1).status_code==200
    checked=client.post(api+'/verify',json=dict(action_id='holder.base',client_frame_id=1))
    assert checked.status_code==200,checked.text
    token=checked.json()['execution']
    assert token['state_id']=='fasten_fixture' and token['baseline_mode']=='ask_manual'
    wrong=dict(action_id=token['action_id'],epoch=token['epoch'],revision=token['revision'],session_id='ar.another_session',
        task_sha256=token['task_sha256'],condition_ids=token['condition_ids'],statement='受控的跨会话旧确认')
    assert client.post(api+'/manual-conditions',json=wrong).status_code==409
    wrong.update(session_id=token['session_id'],task_sha256='0'*64)
    assert client.post(api+'/manual-conditions',json=wrong).status_code==409
    for _ in range(2):
        response=client.post(api+'/manual-conditions',json=dict(action_id=token['action_id'],epoch=token['epoch'],revision=token['revision'],
            session_id=token['session_id'],task_sha256=token['task_sha256'],condition_ids=token['condition_ids'],statement='受控操作者确认当前项'))
        assert response.status_code==200,response.text
        token=response.json()['execution']
    assert token['state_id']=='insert_handle' and token['baseline_mode']=='operate'
    runtime.photo_client.connected=True
    assert frame(client,api,2,'holder.slide').status_code==200
    final=client.post(api+'/verify',json=dict(action_id='holder.slide',client_frame_id=2)).json()['execution']
    assert final['complete'] and final['completed_state_ids']==['fasten_fixture','insert_handle']
    candidate=manager.root/identity/'candidate/task.json'
    candidate.write_bytes(candidate.read_bytes()+b' ')
    assert client.post(api+'/verify',json=dict(action_id='holder.slide',client_frame_id=2)).status_code==409


def test_changed_candidate_cannot_be_activated(compiled):
    client,manager,identity,result=compiled
    assert result['status']=='ready',result
    candidate=manager.root/identity/'candidate/task.json'
    candidate.write_bytes(candidate.read_bytes()+b' ')
    response=client.post('/api/guidance/compiled/jobs/'+identity+'/use',json=dict(manifest_sha256=result['manifest_sha256'],acknowledge_experimental=True))
    assert response.status_code==409 and identity not in manager.runtimes


def test_compiler_exception_is_terminal_and_never_uses_gt(compiled):
    client,manager,_,_=compiled
    class Broken:
        kind='controlled_failure'
        def call(self,*args):
            raise RuntimeError('controlled failure')
    manager.compiler_client=Broken()
    response=client.post('/api/guidance/compiled/jobs',json={'intent':'安装夹具手柄'})
    assert response.status_code==202
    path='/api/guidance/compiled/jobs/'+response.json()['id']
    for _ in range(100):
        result=client.get(path).json()
        if result['status'] not in ('queued','compiling'):
            break
        time.sleep(.01)
    assert result['status'] in ('failed','blocked') and result['error_type']=='RuntimeError'
    assert result['gt_used_as_input'] is False


def test_candidate_changed_during_observation_cannot_commit(compiled):
    client,manager,identity,result=compiled
    used=client.post('/api/guidance/compiled/jobs/'+identity+'/use',json=dict(manifest_sha256=result['manifest_sha256'],acknowledge_experimental=True))
    assert used.status_code==200,used.text
    prefix=used.json()['spatial_prefix']
    runtime=manager.runtimes[identity]
    candidate=manager.root/identity/'candidate/task.json'
    class Tamper(VisibleFacts):
        changed=False
        def call(self,*args):
            if not self.changed:
                candidate.write_bytes(candidate.read_bytes()+b' ')
                self.changed=True
            return super().call(*args)
    runtime.photo_client=Tamper()
    begin=client.post(prefix+'/sessions',json=dict(camera_id='controlled',visual_client_revision='machine-workframe-v1'))
    assert begin.status_code==201,begin.text
    identity=begin.json()['session_id'];api=prefix+'/sessions/'+identity
    assert frame(client,api,1).status_code==200
    live=runtime.sessions[identity].baseline
    assert client.post(api+'/verify',json=dict(action_id='holder.base',client_frame_id=1)).status_code==409
    assert live.revision==0 and runtime.sessions[identity].baseline.revision==0
    assert not list((runtime.root/'runs'/identity).rglob('acceptance.json'))


def test_new_protocol_with_same_task_cannot_replace_an_active_compilation(compiled):
    from manual2ar_baseline.compiler import Proposal,lower,load_compilation,seal
    from manual2ar_baseline.gt import Sources,encoded
    client,manager,identity,result=compiled
    path='/api/guidance/compiled/jobs/'+identity
    used=client.post(path+'/use',json=dict(manifest_sha256=result['manifest_sha256'],acknowledge_experimental=True))
    assert used.status_code==200,used.text
    folder=manager.root/identity/'candidate'
    task_before=(folder/'task.json').read_bytes()
    proposal=Proposal.model_validate_json((folder/'proposal.json').read_bytes())
    proposal.queries[0].instruction+='；请补充关系证据。'
    protocol,_=lower(proposal,Sources.model_validate_json((folder/'sources.json').read_bytes()),json.loads((folder/'capabilities.json').read_bytes()))
    (folder/'proposal.json').write_bytes(encoded(proposal.model_dump()))
    (folder/'protocol.json').write_bytes(encoded(protocol.model_dump()))
    seal(folder,'experimental_ready')
    load_compilation(folder)
    assert (folder/'task.json').read_bytes()==task_before
    prefix=used.json()['spatial_prefix']
    assert client.post(prefix+'/sessions',json=dict(camera_id='controlled',visual_client_revision='machine-workframe-v1')).status_code==409
    current=client.get(path).json()
    assert client.post(path+'/use',json=dict(manifest_sha256=current['manifest_sha256'],acknowledge_experimental=True)).status_code==409
