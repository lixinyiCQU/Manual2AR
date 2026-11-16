"""Read-only conditional guidance over accepted facts; never predicts future success."""


def _sources(session, requirement_ids):
    requirements = {row.id: row for row in session.task.requirements}
    return list(dict.fromkeys(requirements[rid].source_id for rid in requirement_ids))


def observation_hints(session, condition_ids):
    """Use the recorded observation limit, without inventing visibility or camera poses."""
    events = {event['id']: event for event in session.events if event['kind'] == 'observation'}
    suggestions = {
        'occluded': '请换一个能看清该部位的角度补拍；不要由遮挡推断安装状态。',
        'out_of_frame': '请将该部位及周边安装区域拍入画面。',
        'unresolved_identity': '请补拍部件特征及周边安装位置，先确认目标身份。',
        'insufficient_detail': '请靠近补拍该部位，保持清晰并包含周边安装位置。',
        'not_observed': '请拍摄该部位及周边安装区域。',
    }
    hints = []
    for identity in condition_ids:
        condition, fact = session.conditions[identity], session.facts[identity]
        if condition.channel != 'vision' or fact.value != 'unknown':
            continue
        event = events.get(fact.evidence_id, {})
        reason = event.get('values', {}).get(identity, {}).get('reason', 'not_observed')
        hints.append(dict(condition_id=identity, statement=condition.statement, reason=reason,
                          instruction=suggestions.get(reason, suggestions['not_observed']),
                          requirement_ids=list(condition.requirement_ids),
                          source_ids=_sources(session, condition.requirement_ids),
                          evidence_id=fact.evidence_id, source_sha256=event.get('source_sha256')))
    return hints


def remaining_plan(session):
    """Describe current guidance and guarded alternatives; operation is not completion."""
    plan = session.plan()
    current = dict(mode=plan['mode'], node_id=plan['node_id'], condition_ids=list(plan['condition_ids']),
                   reason=plan['reason'], observation_hints=observation_hints(session, plan['condition_ids']))
    steps = []
    for identity in plan['needed_node_ids']:
        if plan['node_states'][identity] == 'verified':
            continue
        node = session.nodes[identity]
        dependencies = [n for n in session.order if n in session.dependencies[identity]]
        visual = [c for c in node.completion_ids if session.conditions[c].channel == 'vision']
        manual = [c for c in node.completion_ids if session.conditions[c].channel == 'manual']
        unknown = [c for c in node.precondition_ids + visual
                   if session.conditions[c].channel == 'vision' and session.facts[c].value == 'unknown']
        pending = [c for c in dict.fromkeys(node.precondition_ids + node.completion_ids)
                   if session.facts[c].value != 'true']
        branches = []
        if unknown:
            branches.append(dict(mode='request_view', condition_ids=list(dict.fromkeys(unknown)), conditional=True,
                when=dict(all_completed_node_ids=dependencies, any_unknown_condition_ids=list(dict.fromkeys(unknown))),
                reason='若这些视觉条件仍未知，补充对应现场证据；不将未知当作未安装。',
                observation_hints=observation_hints(session, list(dict.fromkeys(unknown)))))
        branches.append(dict(mode='operate', condition_ids=list(node.completion_ids), conditional=True,
            when=dict(all_completed_node_ids=dependencies, all_true_condition_ids=list(node.precondition_ids),
                      requires_runtime_mode='operate', requires_runtime_node_id=identity,
                      any_false_condition_ids=list(node.completion_ids)),
            reason='若前置满足且本步有明确未满足条件，按官方操作完成或调整，再核验结果。'))
        if session.guidance_policy in ('scene_guided', 'evidence_guided') and dependencies and visual:
            uncertainty = ('all_unknown_condition_ids' if session.guidance_policy == 'evidence_guided'
                           else 'any_unknown_condition_ids')
            branches.append(dict(mode='operate', condition_ids=list(visual), conditional=True,
                when=dict(all_completed_node_ids=dependencies, all_true_condition_ids=list(node.precondition_ids),
                          requires_runtime_mode='operate', requires_runtime_node_id=identity,
                          requires_scene_observation=True, **{uncertainty: list(visual)}),
                reason='若符合当前策略的未知条件且前置已核实，可查看操作指导；查看指导不证明已安装。'))
        if manual:
            branches.append(dict(mode='ask_manual', condition_ids=list(manual), conditional=True,
                when=dict(all_completed_node_ids=dependencies,
                          requires_runtime_mode='ask_manual', requires_runtime_node_id=identity,
                          all_true_condition_ids=list(dict.fromkeys(node.precondition_ids + visual)),
                          any_not_true_condition_ids=list(manual)),
                reason='只有前置及规定视觉条件满足后，才可逐项确认这些人工条件。'))
        if visual:
            branches.append(dict(mode='verify', condition_ids=list(visual), conditional=True,
                when=dict(operator_reports_operation_done_node_id=identity),
                reason='操作完成后重新核验；操作声明、动画和计划本身都不写入完成事实。'))
        requirement_ids = list(dict.fromkeys(node.requirement_ids +
            [rid for cid in node.precondition_ids + node.completion_ids for rid in session.conditions[cid].requirement_ids]))
        steps.append(dict(node_id=identity, instruction=node.instruction, status=plan['node_states'][identity],
                          prerequisite_only=session.target_node_ids is not None and identity not in session.target_node_ids,
                          depends_on=dependencies, requirement_ids=requirement_ids,
                          source_ids=_sources(session, requirement_ids),
                          completion_condition_ids=list(node.completion_ids), pending_condition_ids=pending,
                          conditional=True, branches=branches))
    return dict(schema_version='baseline-remaining-plan-v1', **session.stamp(), guidance_policy=session.guidance_policy,
                target_node_ids=plan['target_node_ids'], needed_node_ids=list(plan['needed_node_ids']),
                current_action=current, remaining_steps=steps,
                metadata=dict(planner='deterministic_conditional_guidance_not_a_pomdp_solver',
                              optimality='not_claimed', uncertainty_probabilities='not_calibrated',
                              execution_does_not_confirm_completion=True,
                              observation_hints_are_capture_targets_not_observation_scope=True,
                              future_branches='conditional_alternatives_not_a_fixed_future_sequence'))
