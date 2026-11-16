"""Conditional guidance changes recommendations, never accepted completion facts."""
from copy import deepcopy
from pathlib import Path

import pytest

from manual2ar_baseline.gt import TaskDefinition, load_bundle
from manual2ar_baseline.planning import remaining_plan
from manual2ar_baseline.state import Session


BUNDLE = Path(__file__).resolve().parents[1] / 'ground_truth/u7/v1/state-validation'


def session(policy='evidence_guided', target=None, task=None):
    task = task or load_bundle(BUNDLE)[1]
    return Session(task, 'planning', '安装料盘支架', target_node_ids=target, guidance_policy=policy)


def observe(value, readings):
    return value.apply(dict(id='photo.' + str(value.revision), **value.stamp(), kind='observation',
        origin='controlled_annotation', frame_id=value.last_frame + 1, source_sha256='a' * 64,
        values={cid:dict(value=truth, reason=reason) for cid, (truth, reason) in readings.items()}))


def confirm(value, node_id):
    return value.apply(dict(id='manual.' + str(value.revision), **value.stamp(), kind='manual',
        origin='controlled_operator', statement='Controlled explicit confirmation',
        values={cid:'true' for cid in value.nodes[node_id].completion_ids
                if value.conditions[cid].channel == 'manual'}))


def verified_base(value):
    observe(value, {cid:('true', 'observed') for cid in value.nodes['install_base'].completion_ids
                   if value.conditions[cid].channel == 'vision'})
    confirm(value, 'install_base')


def test_partial_positive_evidence_selects_verification_without_changing_old_policy():
    modes = {}
    for policy in ('strict', 'scene_guided', 'evidence_guided'):
        value = session(policy)
        verified_base(value)
        observe(value, {'c.holder.connection':('true', 'observed'),
                        'c.holder.appearance':('unknown', 'insufficient_detail')})
        modes[policy] = value.plan()['mode']
        assert value.plan()['completed_node_ids'] == ['install_base']
    assert modes == {'strict':'request_view', 'scene_guided':'operate', 'evidence_guided':'request_view'}


def test_explicit_negative_still_receives_operation_and_unknown_child_can_receive_guidance():
    value = session()
    verified_base(value)
    assert value.plan()['mode'] == 'operate'
    observe(value, {'c.holder.connection':('true', 'observed'),
                    'c.holder.appearance':('false', 'observed')})
    assert value.plan()['mode'] == 'operate'
    assert not value.completed()['install_holder']


def test_manual_cannot_override_missing_visual_evidence():
    value = session()
    verified_base(value)
    observe(value, {'c.holder.connection':('true', 'observed'),
                    'c.holder.appearance':('unknown', 'insufficient_detail')})
    before = value.plan()
    with pytest.raises(ValueError, match='visual/prerequisite'):
        confirm(value, 'install_holder')
    assert value.plan() == before


def test_conditional_operation_still_requires_runtime_authorization_after_manual_rejection():
    value=session();verified_base(value)
    observe(value,{'c.holder.connection':('true','observed'),
                   'c.holder.appearance':('unknown','insufficient_detail')})
    value.apply(dict(id='reject.direction',**value.stamp(),kind='manual',origin='controlled_operator',
                     statement='Direction explicitly rejected in software control',values={'c.holder.direction':'false'}))
    result=remaining_plan(value)
    assert result['current_action']['mode']=='request_view'
    operations=[b for b in result['remaining_steps'][0]['branches'] if b['mode']=='operate']
    assert operations
    assert all(b['when']['requires_runtime_mode']=='operate' and b['when']['requires_runtime_node_id']=='install_holder'
               for b in operations)
    assert not value.completed()['install_holder']


@pytest.mark.parametrize('reason,word', [('occluded','角度'), ('out_of_frame','拍入'),
    ('unresolved_identity','身份'), ('insufficient_detail','靠近')])
def test_information_action_uses_bound_observation_limit_and_keeps_source_trace(reason, word):
    value = session()
    observe(value, {'c.base.mount':('true', 'observed'),
                    'c.base.screws':('unknown', reason), 'c.base.appearance':('unknown', reason)})
    result = remaining_plan(value)
    action = result['current_action']
    assert action['mode'] == 'request_view'
    assert action['condition_ids'] == ['c.base.screws', 'c.base.appearance']
    assert {h['reason'] for h in action['observation_hints']} == {reason}
    for hint in action['observation_hints']:
        assert word in hint['instruction']
        assert hint['source_sha256'] == 'a' * 64 and hint['evidence_id'] == 'photo.0'
        assert hint['requirement_ids'] == value.conditions[hint['condition_id']].requirement_ids
        assert hint['source_ids']


def test_remaining_plan_is_read_only_conditional_and_preserves_narrow_scope():
    value = session(target=['install_base'])
    before = deepcopy(value.__dict__)
    result = remaining_plan(value)
    assert value.__dict__ == before
    assert result['task_sha256'] == value.task_sha and result['revision'] == value.revision
    assert result['needed_node_ids'] == ['install_base']
    assert [step['node_id'] for step in result['remaining_steps']] == ['install_base']
    assert all(step['conditional'] and all(branch['conditional'] for branch in step['branches'])
               for step in result['remaining_steps'])
    result['remaining_steps'][0]['completion_condition_ids'].clear()
    assert value.__dict__ == before
    verified_base(value)
    assert remaining_plan(value)['current_action']['mode'] == 'complete'
    assert remaining_plan(value)['remaining_steps'] == []


def test_slide_goal_preserves_dependency_and_no_installation_is_predicted():
    value = session(target=['install_holder'])
    result = remaining_plan(value)
    assert result['target_node_ids'] == ['install_holder']
    base, holder = result['remaining_steps']
    assert base['prerequisite_only'] and not holder['prerequisite_only']
    assert holder['depends_on'] == ['install_base']
    manual = next(b for b in holder['branches'] if b['mode'] == 'ask_manual')
    assert manual['when']['all_completed_node_ids'] == ['install_base']
    assert set(manual['when']['all_true_condition_ids']) >= {'c.holder.connection', 'c.holder.appearance'}
    assert result['metadata']['execution_does_not_confirm_completion']
    assert result['metadata']['uncertainty_probabilities'] == 'not_calibrated'


def test_planning_uses_graph_and_condition_channels_instead_of_u7_identifiers():
    raw = load_bundle(BUNDLE)[1].model_dump()
    nodes = {n['id']:'operation.' + str(i) for i,n in enumerate(raw['nodes'])}
    conditions = {c['id']:'condition.' + str(i) for i,c in enumerate(raw['conditions'])}
    for condition in raw['conditions']:
        condition['id'] = conditions[condition['id']]
    for node in raw['nodes']:
        node['id'] = nodes[node['id']]
        node['depends_on'] = [nodes[n] for n in node['depends_on']]
        node['precondition_ids'] = [conditions[c] for c in node['precondition_ids']]
        node['completion_ids'] = [conditions[c] for c in node['completion_ids']]
    raw['goal_condition_ids'] = [conditions[c] for c in raw['goal_condition_ids']]
    value = session(task=TaskDefinition.model_validate(raw), target=[nodes['install_holder']])
    result = remaining_plan(value)
    assert result['needed_node_ids'] == list(nodes.values())
    assert result['current_action']['condition_ids'] == [c.id for c in value.task.conditions
        if c.channel == 'vision' and c.id in value.nodes[nodes['install_base']].completion_ids]
    assert all(step['source_ids'] for step in result['remaining_steps'])
