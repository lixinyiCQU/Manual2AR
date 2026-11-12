"""Goal scope and guidance are independent of completion; controlled photos only."""
import json

import pytest

from tests.backend.guidance.test_baseline_ar import setup, frame, manual, PREFIX


@pytest.mark.parametrize('question,target,needed', [
    ('安装料盘支架', ['install_base', 'install_holder'], ['install_base', 'install_holder']),
    ('安装支架底座', ['install_base'], ['install_base']),
    ('滑入料盘底座', ['install_holder'], ['install_base', 'install_holder']),
])
def test_three_goals_base_photo_manuals_and_scoped_ar(setup, question, target, needed):
    client, service, facts, _ = setup
    preview = client.post(PREFIX + '/goal-preview', json={'intent':question})
    assert preview.status_code == 200 and preview.json()['status'] == 'matched', preview.text
    assert preview.json()['selected_node_ids'] == target
    if question.startswith('滑入'):
        assert '解释为' in preview.json()['interpretation']
    begin = client.post(PREFIX + '/sessions', json=dict(camera_id='test', rig_id='test', reuse_targets=True,
        goal_intent=question, visual_client_revision='machine-workframe-v1'))
    assert begin.status_code == 201, begin.text
    token = begin.json()['execution']
    assert token['target_node_ids'] == target and token['needed_node_ids'] == needed
    assert token['baseline_mode'] == 'request_view' and not token['guidance_ready']
    api = PREFIX + '/sessions/' + begin.json()['session_id']
    seen = []
    original = facts.call
    facts.base = True
    def unknown_holder(prompt, schema, images):
        query = json.JSONDecoder().raw_decode(prompt.split('QUERY:',1)[1])[0]
        seen.extend(q['kind'] for q in query['queries'])
        response, metadata = original(prompt,schema,images)
        result = json.loads(response)
        for q, row in zip(query['queries'], result['findings']):
            if q['kind'] == 'connection_relation':
                row.update(observability='insufficient_detail', coverage='unknown', region=None,
                           value='unresolved', evidence_boxes=[], instances=[])
        return json.dumps(result),metadata
    facts.call = unknown_holder
    assert frame(client,api,1).status_code == 200
    response = client.post(api+'/verify',json=dict(action_id='holder.base',client_frame_id=1))
    assert response.status_code == 200,response.text
    token = response.json()['execution']
    assert token['baseline_mode'] == 'ask_manual' and '待人工核对' in token['task_summary']
    if len(needed) == 1:
        assert 'connection_relation' not in seen
    for _ in range(2):
        reply = manual(client,api,token)
        assert reply.status_code == 200, reply.text
        token = reply.json()['execution']
    assert token['completed_state_ids'] == ['install_base']
    if target == ['install_base']:
        assert token['complete'] and token['remaining_state_ids'] == []
        assert token['action_id'] == 'holder.base'
        assert not token['guidance_ready']
    else:
        assert token['action_id'] == 'holder.slide' and token['guidance_ready'] and not token['complete']
        assert '尚未确认' in token['reason'] and 'AR 指导' in token['task_summary']
        assert token['remaining_state_ids'] == ['install_holder']
        assert frame(client,api,2,'holder.slide').json()['visual']['presentation']['presentation_id'] == 'u7.holder_slide'
        seen.clear()
        retry = client.post(api+'/verify',json=dict(action_id='holder.slide',client_frame_id=2))
        assert retry.status_code == 200, retry.text
        assert seen == ['connection_relation', 'appearance']
        assert retry.json()['execution']['completed_state_ids'] == ['install_base']
        # A deliberate whole-scene re-assessment must still deliver new counter-evidence.
        facts.base = False
        reassess = client.post(api+'/assess',json=dict(action_id='holder.slide',client_frame_id=2))
        assert reassess.status_code == 200,reassess.text
        assert reassess.json()['execution']['completed_state_ids'] == []
        assert reassess.json()['execution']['action_id'] == 'holder.base'
        assert '已通过操作需要重新核实' in reassess.json()['feedback']
        assert '原人工确认事件仍保留' in reassess.json()['feedback']
        assert len([event for event in service.sessions[begin.json()['session_id']].baseline.events if event['kind']=='manual'])==2
    goal_record = service.root/'runs'/begin.json()['session_id']/'goal.json'
    assert json.loads(goal_record.read_bytes())['selected_node_ids'] == target


def test_unmatched_goal_does_not_create_or_expand_session(setup):
    client,service,_,_=setup
    before = set(service.sessions)
    for query in ('安装切刀', '开箱', '滑入螺丝', '不要安装料盘支架'):
        preview = client.post(PREFIX+'/goal-preview',json={'intent':query})
        assert preview.status_code == 200 and preview.json()['status'] == 'clarification_required',preview.text
        begin = client.post(PREFIX+'/sessions',json=dict(camera_id='test',goal_intent=query,
            visual_client_revision='machine-workframe-v1'))
        assert begin.status_code == 422
    assert set(service.sessions) == before


def test_failed_current_check_keeps_manual_evidence_and_names_current_step(setup):
    client,service,facts,api=setup
    facts.base=True
    assert frame(client,api,1).status_code==200
    token=client.post(api+'/verify',json=dict(action_id='holder.base',client_frame_id=1)).json()['execution']
    for _ in range(2):token=manual(client,api,token).json()['execution']
    assert token['action_id']=='holder.slide'
    assert frame(client,api,2,'holder.slide').status_code==200
    live=service.sessions[api.rsplit('/',1)[-1]].baseline
    before=live.plan()
    def failure():raise ValueError('controlled model failure')
    facts.callback=failure
    result=client.post(api+'/verify',json=dict(action_id='holder.slide',client_frame_id=2))
    assert result.status_code==502 and '第2/2步' in result.json()['detail']
    assert '人工确认' in result.json()['detail'] and live.plan()==before
