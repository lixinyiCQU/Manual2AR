"""Controlled API loop over actual U7 assets and synthetic calibrated frames; no hardware claim."""
import base64
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from manual2ar.application.config import load, for_module
from manual2ar.modules.guidance.server import create_app
from manual2ar.modules.guidance.spatial.simulation import calibration, jpeg, targets
from manual2ar_baseline.ar import Bindings


PREFIX = '/api/guidance/baseline/spatial'


class NeverLegacyModel:
    def chat_structured(self, **kwargs):
        raise AssertionError('Baseline verification must not use legacy completion prompts')


class Facts:
    kind = 'controlled_provider'

    def __init__(self):
        self.base = False
        self.holder = False
        self.hidden = False
        self.calls = 0
        self.callback = None

    def call(self, prompt, schema, images):
        self.calls += 1
        if self.callback:
            self.callback()
        query = json.JSONDecoder().raw_decode(prompt.split('QUERY:', 1)[1])[0]
        rows = []
        for q in query['queries']:
            value = {'mount_relation': 'seated' if self.base else 'absent', 'connection_relation': 'connected' if self.holder else 'separate',
                     'appearance': 'no_visible_anomaly', 'fastener_instances': 'instances'}[q['kind']]
            row = dict(query_id=q['id'], observability='observable', coverage='complete', region={'xyxy': [0, 0, 1000, 1000]},
                       value=value, evidence_boxes=[{'xyxy': [100, 100, 900, 900]}], instances=[], evidence='受控事实，不是照片真值')
            if q['kind'] == 'fastener_instances':
                row.update(evidence_boxes=[], instances=[dict(location=slot, box={'xyxy': box}) for slot, box in
                    [('upper_hole', [200, 200, 300, 300]), ('lower_hole', [200, 600, 300, 700])]])
            if self.hidden and q['id'].startswith('base_'):
                row.update(observability='occluded', coverage='unknown', region=None, value='unresolved', instances=[], evidence_boxes=[])
            rows.append(row)
        return json.dumps(dict(evidence_image_id='current_scene', source_sha256=query['source_sha256'], findings=rows)), dict(model='controlled', usage={})


@pytest.fixture
def setup(tmp_path):
    config = for_module(load(), 'guidance')
    config['runtime_dir'] = str(tmp_path)
    app = create_app(config, NeverLegacyModel())
    service = app.state.baseline_spatial
    provider = Facts()
    service.photo_client = provider
    for group, value in [('cameras', calibration()), ('rigs', targets(service.actions))]:
        path = service.reference_profiles / group / 'test.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))
    originals = {p: p.read_bytes() for p in service.reference_profiles.rglob('*.json')}
    with TestClient(app) as client:
        begin = client.post(PREFIX + '/sessions', json=dict(camera_id='test', rig_id='test', reuse_targets=True,
            visual_client_revision='machine-workframe-v1'))
        assert begin.status_code == 201, begin.text
        sid = begin.json()['session_id']
        assert service.sessions[sid].baseline.id == 'ar.' + sid
        yield client, service, provider, PREFIX + '/sessions/' + sid
    assert all(p.read_bytes() == raw for p, raw in originals.items())


def frame(client, api, number, action='holder.base', raw=None):
    raw = raw if raw is not None else jpeg(30)
    return client.post(api + '/frames', json=dict(client_frame_id=number, action_id=action,
        image_base64=base64.b64encode(raw).decode(), source_sha256=hashlib.sha256(raw).hexdigest()))


def check(client, api, number, action='holder.base'):
    response = client.post(api + '/verify', json=dict(client_frame_id=number, action_id=action))
    assert response.status_code == 200, response.text
    return response.json()['execution']


def manual(client, api, token):
    return client.post(api + '/manual-conditions', json=dict(action_id=token['action_id'], epoch=token['epoch'],
        revision=token['revision'], condition_ids=token['condition_ids'], statement='受控操作者明确确认此项'))


def test_current_operation_manual_batch_is_atomic_and_cannot_include_future_conditions(setup):
    client,service,facts,api=setup
    facts.base=True
    assert frame(client,api,1).status_code==200
    assert facts.calls==0  # Camera frames alone never authorize a model observation.
    token=check(client,api,1)
    assert len(token['manual_conditions'])==2
    assert all(row['value']=='true' for row in token['visual_conditions'])
    assert all('受控事实' in row['evidence'] for row in token['visual_conditions'])
    assert {row['id'] for row in token['visual_conditions']}=={'c.base.mount','c.base.screws','c.base.appearance'}
    command=dict(action_id=token['action_id'],epoch=token['epoch'],revision=token['revision'],
        condition_ids=[row['id'] for row in token['manual_conditions']],session_id=token['session_id'],
        task_sha256=token['task_sha256'],statement='受控操作者逐项确认当前全部条件，并非实物验收')
    forged=deepcopy(command);forged['condition_ids'].append('c.holder.direction')
    assert client.post(api+'/manual-conditions',json=forged).status_code==409
    response=client.post(api+'/manual-conditions',json=command)
    assert response.status_code==200,response.text
    result=response.json()['execution']
    assert result['revision']==token['revision']+1 and result['action_id']=='holder.slide'
    assert result['completed_state_ids']==['install_base']
    live=service.sessions[api.rsplit('/',1)[-1]].baseline
    events=[e for e in live.events if e['kind']=='manual']
    assert len(events)==1 and len(events[0]['values'])==2
    assert client.post(api+'/manual-conditions',json=command).status_code==409
    fresh=client.post(PREFIX+'/sessions',json=dict(camera_id='test',rig_id='test',visual_client_revision='machine-workframe-v1')).json()['execution']
    assert all(row['value']=='unknown' and not row['evidence'] for row in fresh['visual_conditions'])


def test_scene_overview_keeps_later_visible_result_when_prerequisite_is_unknown(setup):
    client,service,facts,api=setup
    facts.base=True;facts.holder=True
    original=facts.call
    def unclear_screws(prompt,schema,images):
        raw,meta=original(prompt,schema,images)
        query=json.JSONDecoder().raw_decode(prompt.split('QUERY:',1)[1])[0]
        value=json.loads(raw)
        for q,row in zip(query['queries'],value['findings']):
            if q['kind']=='fastener_instances':
                row.update(observability='insufficient_detail',coverage='unknown',region=None,
                           value='unresolved',evidence_boxes=[],instances=[])
        return json.dumps(value),meta
    facts.call=unclear_screws
    assert frame(client,api,1).status_code==200
    token=check(client,api,1)
    assert token['action_id']=='holder.base' and not token['complete']
    assert any(r['id']=='c.holder.connection' and r['value']=='true' for r in token['scene_conditions'])
    assert not any(r['id']=='c.holder.connection' for r in token['visual_conditions'])
    assert '第2步（料盘支架）' in token['user_summary'] and '可见检查通过，前一步待确认' in token['user_summary']
    assert '未确认' in token['user_feedback'] and len(token['user_feedback'])<70
    assert not token['manual_conditions']


def test_missing_evidence_boxes_return_actionable_feedback_and_release_busy_state(setup):
    client,service,facts,api=setup
    facts.base=True
    original=facts.call
    def missing(prompt,schema,images):
        raw,metadata=original(prompt,schema,images)
        value=json.loads(raw)
        for finding in value['findings']:
            if finding['value']!='instances':finding['evidence_boxes']=[]
        return json.dumps(value),metadata
    facts.call=missing
    assert frame(client,api,1).status_code==200
    response=client.post(api+'/verify',json=dict(action_id='holder.base',client_frame_id=1))
    assert response.status_code==200,response.text
    result=response.json()
    assert result['execution']['baseline_mode']=='request_view'
    assert '模型未提供现场证据框' in result['feedback'] and '局部螺丝检查未执行' in result['feedback']
    assert facts.calls==2
    sid=api.rsplit('/',1)[-1]
    assert not service.sessions[sid].baseline_busy
    facts.call=original
    assert frame(client,api,2).status_code==200
    recovered=client.post(api+'/verify',json=dict(action_id='holder.base',client_frame_id=2))
    assert recovered.status_code==200 and recovered.json()['execution']['baseline_mode']=='ask_manual'


def test_closed_loop_reuses_both_presentations_and_only_evidence_advances(setup):
    client, service, facts, api = setup
    initial = frame(client, api, 1).json()
    assert initial['visual'] is None and initial['execution']['baseline_mode'] == 'request_view'
    assert frame(client, api, 2, 'holder.slide').status_code == 409
    operate = check(client, api, 1)
    assert operate['baseline_mode'] == 'operate'
    rendered = frame(client, api, 2).json()
    assert rendered['visual']['presentation']['presentation_id'] == 'u7.holder_base'
    revision = operate['revision']
    event = client.post(api + '/events', json=dict(event_id='a'*32, name='animation_finished', action_id='holder.base',
        client_frame_id=2, source_sha256=rendered['source_sha256']))
    assert event.status_code == 200 and not event.json()['operation_verified']
    assert frame(client, api, 3).json()['execution']['revision'] == revision
    facts.base = True
    token = check(client, api, 3)
    assert token['baseline_mode'] == 'ask_manual' and token['condition_ids'] == ['c.base.direction']
    token = manual(client, api, token).json()['execution']
    assert token['condition_ids'] == ['c.base.secure']
    token = manual(client, api, token).json()['execution']
    assert token['action_id'] == 'holder.slide' and token['completed_state_ids'] == ['install_base']
    holder = frame(client, api, 4, 'holder.slide').json()
    assert holder['visual']['presentation']['presentation_id'] == 'u7.holder_slide'
    facts.holder = facts.hidden = True
    token = check(client, api, 4, 'holder.slide')
    assert token['baseline_mode'] == 'ask_manual' and token['condition_ids'] == ['c.holder.direction']
    token = manual(client, api, token).json()['execution']
    assert token['complete'] and token['completed_state_ids'] == ['install_base', 'install_holder']
    assert frame(client, api, 5, 'holder.slide').json()['visual'] is None
    assert list(service.root.rglob('acceptance.json'))


def test_installed_holder_in_new_session_never_skips_hidden_base(setup):
    client, service, facts, api = setup
    facts.base = facts.holder = facts.hidden = True
    frame(client, api, 1)
    token = check(client, api, 1)
    assert token['baseline_mode'] == 'request_view' and token['condition_ids'] == ['c.base.mount']
    assert token['completed_state_ids'] == []
    assert manual(client, api, token).status_code == 409


def test_stale_manual_wrong_conditions_and_cross_step_photos_are_rejected(setup):
    client, service, facts, api = setup
    facts.base = True
    frame(client, api, 1)
    token = check(client, api, 1)
    bad = deepcopy(token)
    bad['condition_ids'] = ['c.base.secure']
    assert manual(client, api, bad).status_code == 409
    assert manual(client, api, token).status_code == 200
    assert manual(client, api, token).status_code == 409
    assert client.post(api + '/verify', json=dict(client_frame_id=1, action_id='holder.slide')).status_code == 409


def test_model_failure_and_late_results_cannot_advance(setup):
    client, service, facts, api = setup
    frame(client, api, 1)
    session = service.sessions[api.rsplit('/', 1)[1]]
    original = session.baseline.stamp()
    def fail():
        raise ValueError('controlled provider failure')
    facts.callback = fail
    assert client.post(api + '/verify', json=dict(client_frame_id=1, action_id='holder.base')).status_code == 502
    assert session.baseline.stamp() == original and not session.baseline_busy
    def change():
        facts.callback = None
        session.baseline.apply(dict(id='change', **session.baseline.stamp(), kind='context_change', context_id='new', reason='受控上下文变化'))
    facts.callback = change
    assert client.post(api + '/verify', json=dict(client_frame_id=1, action_id='holder.base')).status_code == 409
    assert session.baseline.plan()['completed_node_ids'] == []
    assert list(service.root.rglob('rejected.json'))


def test_marker_loss_hides_geometry_and_asset_binding_is_frozen(setup):
    client, service, facts, api = setup
    frame(client, api, 1)
    check(client, api, 1)
    assert frame(client, api, 2).json()['visual'] is not None
    blank = cv2.imencode('.jpg', np.full((720, 960, 3), 255, np.uint8))[1].tobytes()
    hidden = frame(client, api, 3, raw=blank).json()
    assert hidden['visual'] is None and hidden['pose'] is None
    bindings = service.bindings.model_copy(deep=True)
    bindings.presentations[0].presentation_id = 'u7.holder_slide'
    with pytest.raises(ValueError, match='mismatch'):
        bindings.check(service.task, Path.cwd(), service.actions, service.asset_library)


def test_baseline_has_independent_progress_and_profile_reset_does_not_reimport(setup):
    client, service, facts, api = setup
    sid = api.rsplit('/', 1)[1]
    assert sid not in client.app.state.spatial.sessions
    copied = service.profile('rigs', 'test')
    assert copied.is_file()
    copied.unlink()
    again = client.post(PREFIX + '/sessions', json=dict(camera_id='test', rig_id='test', visual_client_revision='machine-workframe-v1'))
    assert again.status_code == 201 and not copied.exists()
    assert again.json()['execution']['revision'] == 0
