"""Demo scripts are explicit, isolated and subject to the real scheduler's gates."""
import base64
from copy import deepcopy
import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from manual2ar.application.config import load, for_module
from manual2ar.modules.guidance.server import create_app
from manual2ar_baseline.gt import digest
from tools.build.prepare_u7_demo import prepare
from .test_baseline_ar import Facts, NeverLegacyModel
from manual2ar.modules.guidance.spatial.simulation import jpeg

API = '/api/guidance/u7-demo'


@pytest.fixture
def demo(tmp_path):
    config = for_module(load(),'guidance');config['runtime_dir'] = str(tmp_path/'runtime')
    app = create_app(config,NeverLegacyModel());service = app.state.u7_demo
    pictures = []
    for i,identity in enumerate(['base_ready','holder_ready']):
        path = tmp_path/(identity+'.jpg');path.write_bytes(jpeg(30+i))
        pictures.append((identity,identity,path))
    prepare(service.assets,pictures)
    facts = Facts();service.photo_client = facts
    with TestClient(app) as client:yield client,service,facts


def stamp(reply):
    return {**{k:reply['execution'][k] for k in ['session_id','task_sha256','epoch','revision']},
            'source_sha256':reply['source_sha256']}


def photo(client, reply, scene):
    catalog = client.get(API+'/catalog').json()
    sha = next(r['sha256'] for r in catalog['scenes'] if r['id']==scene)
    command = dict(stamp(reply),scene_id=scene);command['source_sha256'] = sha
    result = client.post(API+'/sessions/'+reply['execution']['session_id']+'/photo',json=command)
    assert result.status_code == 200,result.text
    return result.json()


def manual(client,reply):
    command = dict(stamp(reply),condition_ids=[c['id'] for c in reply['execution']['manual_conditions']],confirmed=True)
    result = client.post(API+'/sessions/'+reply['execution']['session_id']+'/manual',json=command)
    assert result.status_code == 200,result.text
    return result.json()


def test_official_steps_are_available_before_photos_or_session_creation(demo):
    client,service,facts=demo
    response=client.get(API+'/catalog')
    assert response.status_code==200
    steps=response.json()['official_steps']
    assert [s['node_id'] for s in steps]==['install_base','install_holder']
    assert 'M3-8' in steps[0]['instruction'] and '滑入' in steps[1]['instruction']
    assert not service.sessions and facts.calls==0


@pytest.mark.parametrize('intent,targets',[
    ('安装料盘支架',['install_base','install_holder']),
    ('安装支架底座',['install_base']),
    ('滑入料盘支架',['install_holder']),
    ('滑入料盘底座',['install_holder']),
    ('安装料盘底座及滑入料盘支架',['install_base','install_holder'])])
def test_selected_goals_complete_without_calling_a_model(demo,intent,targets):
    client,service,facts = demo
    result = client.post(API+'/sessions',json=dict(intent=intent,mode='scripted'))
    assert result.status_code == 201,result.text
    reply = result.json();sid = reply['execution']['session_id']
    assert reply['execution']['target_node_ids'] == targets
    assert reply['execution']['completed_state_ids'] == []
    reply = photo(client,reply,'base_ready')
    assert len(reply['execution']['manual_conditions']) == 2
    forged = dict(stamp(reply),confirmed=True,condition_ids=['c.holder.direction'])
    assert client.post(API+'/sessions/'+sid+'/manual',json=forged).status_code == 409
    before = deepcopy(reply)
    reply = manual(client,reply)
    if targets == ['install_base']:
        assert reply['execution']['complete']
    else:
        assert reply['execution']['action_id'] == 'holder.slide'
        original = service.sessions[sid].baseline.stamp()
        ar = client.post(API+'/sessions/'+sid+'/ar',json=stamp(reply))
        assert ar.status_code == 200,ar.text
        assert ar.json()['presentation']['presentation_id'] == 'u7.holder_slide'
        assert ar.json()['illustrative_only']
        assert service.sessions[sid].baseline.stamp() == original
        stale = client.post(API+'/sessions/'+sid+'/manual',json=dict(stamp(before),confirmed=True,
                            condition_ids=[c['id'] for c in before['execution']['manual_conditions']]))
        assert stale.status_code == 409
        # A failed same-step photo must keep completed base evidence.
        reply = photo(client,reply,'base_ready')
        assert reply['execution']['completed_state_ids'] == ['install_base']
        reply = photo(client,reply,'holder_ready')
        assert reply['execution']['baseline_mode'] == 'ask_manual'
        assert any(c['retained'] for c in reply['execution']['scene_conditions'] if c['id'].startswith('c.base.'))
        # Scripted whole-scene occlusion retains only the already verified base.
        reply = manual(client,reply)
        assert reply['execution']['complete']
    assert facts.calls == 0 and reply['mode'] == 'scripted'
    records = list((service.root/'runs'/sid).glob('*.json'))
    assert all(json.loads(p.read_bytes())['excluded_from_research_evaluation'] for p in records)
    assert client.delete(API+'/sessions/'+sid).status_code == 204


def test_installed_holder_in_fresh_session_cannot_skip_hidden_base(demo):
    client,service,facts = demo
    reply = client.post(API+'/sessions',json=dict(intent='安装料盘支架')).json()
    reply = photo(client,reply,'holder_ready')
    assert reply['execution']['completed_state_ids'] == []
    assert reply['execution']['baseline_mode'] == 'request_view'
    assert '前一步待确认' in reply['execution']['user_summary']
    assert not reply['execution']['manual_conditions']
    result = client.post(API+'/sessions/'+reply['execution']['session_id']+'/ar',json=stamp(reply))
    assert result.status_code == 409 and facts.calls == 0


def test_real_photo_mode_cannot_consume_presets_or_bad_hash_and_preserves_failure(demo):
    client,service,facts = demo
    reply = client.post(API+'/sessions',json=dict(intent='安装料盘支架',mode='live')).json()
    sid = reply['execution']['session_id'];raw = jpeg(30)
    bad = dict(stamp(reply),scene_id='base_ready')
    assert client.post(API+'/sessions/'+sid+'/photo',json=bad).status_code == 422
    command = dict(stamp(reply),image_base64=base64.b64encode(raw).decode(),source_sha256='0'*64)
    assert client.post(API+'/sessions/'+sid+'/photo',json=command).status_code == 409
    command['source_sha256'] = digest(raw);facts.base = True
    result = client.post(API+'/sessions/'+sid+'/photo',json=command)
    assert result.status_code == 200,result.text
    assert facts.calls > 0 and result.json()['mode'] == 'live'
    latest = result.json();before = service.sessions[sid].baseline.stamp()
    def fail():raise ValueError('controlled provider failed')
    facts.callback = fail
    command.update(stamp(latest));command['source_sha256'] = digest(raw)
    assert client.post(API+'/sessions/'+sid+'/photo',json=command).status_code == 502
    assert service.sessions[sid].baseline.stamp() == before and not service.sessions[sid].busy


def test_scene_regression_does_not_reuse_a_later_positive_observation(demo):
    client,service,_ = demo
    reply = client.post(API+'/sessions',json=dict(intent='安装料盘支架')).json()
    reply = photo(client,reply,'holder_ready')
    assert any(c['value']=='true' for c in reply['execution']['scene_conditions'] if c['id']=='c.holder.connection')
    reply = photo(client,reply,'base_ready')
    reply = manual(client,reply)
    assert reply['execution']['mode']=='operate' and reply['execution']['action_id']=='holder.slide'


def test_closed_session_rejects_late_live_observation(demo):
    client,service,facts = demo
    reply = client.post(API+'/sessions',json=dict(intent='安装料盘支架',mode='live')).json()
    sid = reply['execution']['session_id'];row = service.sessions[sid];before = row.baseline.stamp()
    def close():
        facts.callback=None
        service.close(sid)
    facts.callback=close;raw=jpeg(30)
    command=dict(stamp(reply),image_base64=base64.b64encode(raw).decode(),source_sha256=digest(raw))
    result=client.post(API+'/sessions/'+sid+'/photo',json=command)
    assert result.status_code==409 and row.baseline.stamp()==before and row.closed


@pytest.mark.parametrize('failure', ['directory', 'image', 'record', 'acceptance'])
def test_photo_storage_failure_keeps_stamp_and_allows_same_request_retry(demo, monkeypatch, failure):
    from manual2ar.modules.guidance import u7_demo
    client, service, _ = demo
    reply = client.post(API+'/sessions', json=dict(intent='安装料盘支架')).json()
    sid = reply['execution']['session_id']; row = service.sessions[sid]
    before = row.baseline.stamp()
    scene = client.get(API+'/catalog').json()['scenes'][0]
    command = dict(stamp(reply), scene_id=scene['id']); command['source_sha256'] = scene['sha256']
    mkdir, write, atomic = Path.mkdir, Path.write_bytes, u7_demo.atomic_json
    def fail_directory(path, *args, **kwargs):
        if path.name.startswith('photo-'):raise OSError('controlled full disk')
        return mkdir(path, *args, **kwargs)
    def fail_image(path, data):
        if path.name == 'input.jpg':raise OSError('controlled full disk')
        return write(path, data)
    def fail_record(path, value):
        if ((failure == 'record' and value.get('action') == 'photo')
                or (failure == 'acceptance' and Path(path).name == 'acceptance.json')):
            raise OSError('controlled full disk')
        return atomic(path, value)
    with monkeypatch.context() as patch:
        if failure == 'directory':patch.setattr(Path, 'mkdir', fail_directory)
        elif failure == 'image':patch.setattr(Path, 'write_bytes', fail_image)
        else:patch.setattr(u7_demo, 'atomic_json', fail_record)
        result = client.post(API+'/sessions/'+sid+'/photo', json=command)
    assert result.status_code in (502, 503)
    assert row.baseline.stamp() == before and not row.busy
    assert row.source_sha == '' and row.baseline_visual_details == {}
    assert not list((service.root/'runs'/sid).glob('photo-*/acceptance.json'))
    assert client.post(API+'/sessions/'+sid+'/photo', json=command).status_code == 200


def test_failed_start_manual_and_close_records_never_publish_state(demo, monkeypatch):
    from manual2ar.modules.guidance import u7_demo
    client, service, _ = demo
    atomic = u7_demo.atomic_json
    failing_action = 'start'
    def fail(path, value):
        if value.get('action') == failing_action:raise OSError('controlled full disk')
        return atomic(path, value)
    monkeypatch.setattr(u7_demo, 'atomic_json', fail)
    assert client.post(API+'/sessions', json=dict(intent='安装料盘支架')).status_code == 503
    assert not service.sessions
    failing_action = ''
    reply = client.post(API+'/sessions', json=dict(intent='安装料盘支架')).json()
    reply = photo(client, reply, 'base_ready')
    sid = reply['execution']['session_id']; row = service.sessions[sid]
    before = row.baseline.stamp()
    command = dict(stamp(reply), confirmed=True,
                   condition_ids=[c['id'] for c in reply['execution']['manual_conditions']])
    failing_action = 'manual'
    assert client.post(API+'/sessions/'+sid+'/manual', json=command).status_code == 503
    assert row.baseline.stamp() == before
    failing_action = ''
    assert client.post(API+'/sessions/'+sid+'/manual', json=command).status_code == 200
    failing_action = 'close'
    assert client.delete(API+'/sessions/'+sid).status_code == 503
    assert service.get(sid) is row and not row.closed
    failing_action = ''
    assert client.delete(API+'/sessions/'+sid).status_code == 204
