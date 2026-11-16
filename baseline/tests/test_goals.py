"""Goal alignment uses official source quotes and graph structure, never GT IDs."""
from copy import deepcopy

import pytest

from manual2ar_baseline.goals import goal_candidates, hierarchy, resolve_goal
from manual2ar_baseline.gt import Source, TaskDefinition, digest, encoded, load_bundle
from test_compiler import FakeClient, official_fixture
from manual2ar_baseline.compiler import compile_task


@pytest.fixture
def procedure(tmp_path):
    sources, _, proposal, _ = official_fixture(tmp_path)
    return TaskDefinition.model_validate(proposal['task']), sources


def test_parent_and_child_targets_keep_task_bytes_and_source_quotes(procedure):
    task, sources = procedure
    before = encoded(task.model_dump())
    parent = resolve_goal(task, sources, '我希望安装控制夹具')
    base = resolve_goal(task, sources, '安装底座')
    slide = resolve_goal(task, sources, '滑入夹具手柄')
    assert parent.selected_node_ids == ['fasten_fixture', 'insert_handle']
    assert base.selected_node_ids == ['fasten_fixture']
    assert slide.selected_node_ids == ['insert_handle']
    assert parent.level == 'task' and base.level == slide.level == 'operation'
    assert encoded(task.model_dump()) == before
    assert {parent.task_sha256, base.task_sha256, slide.task_sha256} == {digest(before)}
    assert slide.title == '从上向下滑入底座'
    assert slide.source_ids == ['official.handle']


def test_destination_phrase_has_explicit_interpretation(procedure):
    task, sources = procedure
    selection = resolve_goal(task, sources, '滑入底座')
    assert selection.selected_node_ids == ['insert_handle']
    assert '原话按官方唯一对应动作解释' in selection.interpretation
    assert selection.query == '滑入底座'


@pytest.mark.parametrize('query', ['滑入打印板', '滑入螺丝', '滑入M3-8螺丝', '滑入立柱', '不要安装底座', '开箱', '安装空调', '安装底座然后滑入打印板'])
def test_unrelated_or_unrepresented_scope_requires_clarification(procedure, query):
    task, sources = procedure
    with pytest.raises(ValueError):
        resolve_goal(task, sources, query)


def test_user_completion_claim_never_selects_a_different_graph_or_sets_facts(procedure):
    task, sources = procedure
    selection = resolve_goal(task, sources, '我已完成底座，现在希望安装控制夹具')
    assert selection.selected_node_ids == [n.id for n in task.nodes]
    assert selection.model_dump().keys() == {'task_sha256', 'query', 'title', 'level', 'selected_node_ids', 'source_ids', 'interpretation'}


def test_hierarchy_leaves_are_official_operations_not_check_conditions(procedure):
    task, sources = procedure
    tree = hierarchy(task, sources)
    assert [row['id'] for row in tree['children']] == ['fasten_fixture', 'insert_handle']
    assert tree['children'][1]['depends_on'] == ['fasten_fixture']
    assert '拧紧' not in [row['title'] for row in tree['children']]
    changed = task.model_dump()
    changed['requirements'][0]['quote'] = '伪造官方操作'
    with pytest.raises(ValueError, match='quote'):
        hierarchy(TaskDefinition.model_validate(changed), sources)


def test_verbatim_official_instruction_and_explicit_actor_destination(procedure):
    task, sources = procedure
    assert resolve_goal(task, sources, task.nodes[0].instruction).selected_node_ids == ['fasten_fixture']
    assert resolve_goal(task, sources, task.nodes[1].instruction).selected_node_ids == ['insert_handle']
    assert resolve_goal(task, sources, '把夹具手柄滑入底座').selected_node_ids == ['insert_handle']
    assert resolve_goal(task, sources, '将夹具手柄从上向下滑入底座').selected_node_ids == ['insert_handle']
    for query in ('把螺丝滑入底座', '把夹具手柄滑入打印板'):
        with pytest.raises(ValueError):
            resolve_goal(task, sources, query)


def test_destination_cannot_be_arbitrary_object_in_one_of_many_guards(procedure):
    task, sources = procedure
    value = task.model_dump()
    value['nodes'][1]['precondition_ids'] = ['k.contact', 'k.bolts', 'k.facing']
    # Only the actual base object is common across these conditions; the mast is incidental.
    next(c for c in value['conditions'] if c['id'] == 'k.bolts')['object_ids'] = ['fixture']
    guarded = TaskDefinition.model_validate(value)
    assert resolve_goal(guarded, sources, '滑入控制夹具底座').selected_node_ids == ['insert_handle']
    with pytest.raises(ValueError):
        resolve_goal(guarded, sources, '滑入立柱')


def test_official_numbered_heading_cannot_be_replaced_by_broader_generated_title(procedure):
    task, sources = procedure
    value = task.model_dump()
    copied = sources.model_copy(deep=True)
    text = '第 7 步：安装控制夹具'
    copied.records.append(Source(id='official.heading', artifact_id='text.file', locator='json:/heading',
        kind='official', text=text, text_sha256=digest(text.encode())))
    value['requirements'].append(dict(id='r.heading', kind='applicability', source_id='official.heading', quote=text))
    value['policy_requirement_ids'] = ['r.heading']
    assert hierarchy(TaskDefinition.model_validate(value), copied)['title_basis'] == 'official_numbered_heading'
    value['title'] = '开箱'
    with pytest.raises(ValueError, match='章节范围'):
        resolve_goal(TaskDefinition.model_validate(value), copied, '开箱')


def test_compiler_uses_parent_scope_and_preserves_narrow_user_goal(tmp_path):
    sources, root, proposal, catalog = official_fixture(tmp_path)
    client = FakeClient(proposal)
    result = compile_task(sources, root, dict(method='independent-controlled-fixture',
        parent_heading=['安装控制夹具'], goal='安装底座'), '安装底座', catalog, client, tmp_path / 'compiled')
    assert result['status'] == 'experimental_ready'
    assert '\nOFFICIAL_TARGET:安装控制夹具\nUSER_GOAL:安装底座\n' in client.calls[0][0]
    assert len(proposal['task']['nodes']) == 2


def test_short_component_phrase_and_destination_derive_from_names_not_ids(procedure):
    task, sources = procedure
    value = deepcopy(task.model_dump())
    # Different names in a controlled fixture exercise U7-shaped noun omissions.
    source = sources.model_copy(deep=True)
    source.records[0].text = source.records[0].text.replace('底座', '料盘支架底座')
    source.records[0].text_sha256 = digest(source.records[0].text.encode())
    value['objects'][0]['name'] = '料盘支架底座'
    for requirement in value['requirements']:
        if requirement['source_id'] == 'official.anchor':
            requirement['quote'] = requirement['quote'].replace('底座', '料盘支架底座')
    value['title'] = '安装料盘支架'
    value['nodes'][1]['precondition_ids'] = ['k.contact']
    next(c for c in value['conditions'] if c['id'] == 'k.contact')['object_ids'] = ['fixture']
    renamed = TaskDefinition.model_validate(value)
    assert resolve_goal(renamed, source, '安装支架底座').selected_node_ids == ['fasten_fixture']
    assert resolve_goal(renamed, source, '滑入料盘底座').selected_node_ids == ['insert_handle']


def aliases(task, **values):
    value = task.model_dump()
    for obj in value['objects']:
        if obj['id'] in values:
            obj['aliases'] = values[obj['id']]
    return TaskDefinition.model_validate(value)


@pytest.fixture
def u7():
    from pathlib import Path
    sources, task = load_bundle(Path(__file__).resolve().parents[1]/'ground_truth/u7/v1/state-validation')
    return task, sources


@pytest.mark.parametrize('query,expected', [
    ('安装灰色底座', ['install_base']),
    ('安装深灰色底座', ['install_base']),
    ('把白色支架滑入底座', ['install_holder']),
    ('滑入灰色底座', ['install_holder']),
    ('安装底座后滑入支架', ['install_base', 'install_holder']),
    ('安装底座，滑入支架', ['install_base', 'install_holder']),
    ('请问如何安装灰色底座？', ['install_base']),
    ('我想装上灰色底座', ['install_base']),
    ('料盘支架怎么安装？', ['install_base', 'install_holder']),
    ('底座怎样固定？', ['install_base']),
])
def test_reviewed_u7_aliases_and_safe_question_forms(u7, query, expected):
    task, sources = u7
    before = encoded(task.model_dump())
    result = resolve_goal(task, sources, query)
    assert result.selected_node_ids == expected and result.query == query
    assert result.task_sha256 == digest(before) and encoded(task.model_dump()) == before


def test_aliases_work_for_non_u7_tasks_and_preserve_object_provenance(procedure):
    task, sources = procedure
    task = aliases(task, fixture=['红色安装座'], handle=['长握柄'])
    assert resolve_goal(task, sources, '安装红色安装座').selected_node_ids == ['fasten_fixture']
    selected = resolve_goal(task, sources, '把长握柄滑入底座')
    assert selected.selected_node_ids == ['insert_handle']
    assert 'official.handle' in selected.source_ids
    with pytest.raises(ValueError):
        resolve_goal(task, sources, '安装红色安装座', use_aliases=False)


def test_alias_collision_requires_a_choice_with_parent_and_leaf_sources(procedure):
    task, sources = procedure
    task = aliases(task, fixture=['装配件'], handle=['装配件'])
    with pytest.raises(ValueError, match='唯一'):
        resolve_goal(task, sources, '安装装配件')
    choices = goal_candidates(task, sources, '安装装配件')
    assert [c['level'] for c in choices] == ['task', 'operation', 'operation']
    assert [c['selected_node_ids'] for c in choices] == [['fasten_fixture', 'insert_handle'], ['fasten_fixture'], ['insert_handle']]
    assert all(c['source_ids'] and c['task_sha256'] == digest(encoded(task.model_dump())) for c in choices)
    assert all('confidence' not in c and 'probability' not in c for c in choices)
    assert all(resolve_goal(task, sources, c['title']).selected_node_ids == c['selected_node_ids'] for c in choices)


@pytest.mark.parametrize('query', ['安装白色物体', '安装白色', '安装两个底座', '不要安装灰色底座',
                                  '卸下白色支架', '开箱', '安装Z轴立柱', '把白色支架滑入打印板'])
def test_aliases_do_not_authorize_color_context_objects_quantities_or_unsupported_actions(u7, query):
    task, sources = u7
    with pytest.raises(ValueError):
        resolve_goal(task, sources, query)
    assert goal_candidates(task, sources, query) == []


def test_goal_ablation_switches_and_vague_clarification_leave_task_unchanged(u7):
    task, sources = u7
    assert resolve_goal(task, sources, '安装灰色底座', normalize_language=False).selected_node_ids == ['install_base']
    with pytest.raises(ValueError):
        resolve_goal(task, sources, '请问如何安装灰色底座？', normalize_language=False)
    with pytest.raises(ValueError):
        resolve_goal(task, sources, '安装灰色底座', use_aliases=False)
    choices = goal_candidates(task, sources, '下一步怎么做')
    assert len(choices) == 3 and choices[0]['level'] == 'task'
    assert goal_candidates(task, sources, '安装支架底座')[0]['selected_node_ids'] == ['install_base']
    result = resolve_goal(task, sources, '我已完成底座，现在希望安装灰色底座')
    assert result.selected_node_ids == ['install_base'] and 'events' not in result.model_dump()
def test_reviewed_alias_verb_is_not_interpreted_as_a_second_requested_action():
    from pathlib import Path
    from manual2ar_baseline.gt import load_bundle
    sources,task=load_bundle(Path(__file__).resolve().parents[1]/'ground_truth/u7/v1/state-validation')
    assert resolve_goal(task,sources,'把可拆卸白色料盘支架滑入底座').selected_node_ids==['install_holder']
    with pytest.raises(ValueError):resolve_goal(task,sources,'拆卸可拆卸白色料盘支架')


def test_source_candidate_titles_can_be_selected_without_changing_scope(u7):
    task,sources=u7
    choices=goal_candidates(task,sources,'下一步怎么做')
    for choice in choices:
        assert resolve_goal(task,sources,choice['title']).selected_node_ids==choice['selected_node_ids']
