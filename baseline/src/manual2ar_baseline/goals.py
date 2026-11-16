"""Resolve a user goal against an unchanged, source-backed procedure graph."""
import re
from typing import Literal

from pydantic import Field

from .gt import Digest, Identity, Strict, Text, digest, encoded, validate_mapping


class GoalSelection(Strict):
    task_sha256: Digest
    query: Text
    title: Text
    level: Literal['task', 'operation']
    selected_node_ids: list[Identity] = Field(min_length=1)
    source_ids: list[Identity] = Field(min_length=1)
    interpretation: Text


def _compact(text):
    return re.sub(r'[\s\W_的]+', '', text).lower()


def _goal(query, *, allow_multiple=False, normalize_language=True):
    if re.search(r'不希望|不想|不要|不需要|不打算|无需|不用|别(?:安装|滑入|拆卸)', query):
        raise ValueError('目标包含否定或限制，请明确本次要执行的操作。')
    # A completion claim remains text; it never supplies a condition fact.
    goal = re.split(r'希望|想要|接下来(?:请)?|现在(?:请)?', query)[-1]
    if normalize_language:
        goal = re.sub(r'^(?:请问|请教|我(?:要|想)?|请|帮我|只(?:需|想)?|完成|装好|组装|怎么|如何|怎样)+', '', goal.strip())
        goal = re.sub(r'[？?。！!]+$', '', goal.strip())
        suffix = re.fullmatch(r'(.+?)(?:怎么|如何|怎样)(安装|固定|滑入|插入)(?:好)?', goal)
        if suffix:
            goal = suffix[2] + suffix[1]
        goal = re.sub(r'^装上', '安装', goal)
        # Punctuation separates user goals only after the exact official instruction check.
        if allow_multiple:
            goal = re.sub(r'[，,；;]|后(?=(?:安装|固定|滑入|插入|将|把))', '以及', goal)
    goal = re.sub(r'^(?:我(?:要|想)?|请|帮我|只(?:需|想)?|完成|装好|组装)+', '', goal.strip())
    if not allow_multiple and re.search(r'[，,；;]|然后|以及|并且', goal):
        raise ValueError('存在多个操作目标，请选择一个目标或完整任务。')
    return _compact(goal)


def hierarchy(task, sources):
    """Official operation quotes are the leaves; checks are never extra steps."""
    validate_mapping(sources, task)
    requirements = {r.id: r for r in task.requirements}
    records = {r.id: r for r in sources.records}
    headings = []
    for rid in task.policy_requirement_ids:
        row = requirements[rid]
        # Only an explicit numbered-step heading is distinguishable from optional applicability prose here.
        match = re.fullmatch(r'第\s*\d+\s*步\s*[：:]\s*(\S.*)', row.quote.strip())
        if row.kind == 'applicability' and match and row.quote.strip() == records[row.source_id].text.strip():
            headings.append((match[1], row.source_id))
    bound_heading = len({_compact(title) for title, _ in headings}) == 1
    if bound_heading:
        official_title = headings[0][0]
        if _compact(re.sub(r'^第\s*\d+\s*步\s*[：:]\s*', '', task.title)) != _compact(official_title):
            raise ValueError('任务标题超出了官方章节范围，请重新核对编译结果。')
    else:
        official_title = task.title
    children = []
    for node in task.nodes:
        operations = [requirements[r] for r in node.requirement_ids if requirements[r].kind == 'operation']
        if not operations:
            raise ValueError('操作缺少可追溯的官方操作原文：' + node.id)
        children.append(dict(id=node.id, title='；'.join(r.quote for r in operations), instruction=node.instruction,
                             source_ids=list(dict.fromkeys(r.source_id for r in operations)), depends_on=node.depends_on))
    source_ids = list(dict.fromkeys(requirements[r].source_id for r in task.policy_requirement_ids))
    return dict(id=task.id, title=official_title, source_ids=source_ids, children=children,
                title_basis='official_numbered_heading' if bound_heading else 'compiled_task_summary')


def _matches(fragment, name):
    """Allow omitted noun modifiers, but every requested character must remain."""
    fragment, name = _compact(fragment), _compact(name)
    if len(fragment) < 2:
        return False
    if fragment in name:
        return True
    iterator = iter(name)
    return all(any(character == item for item in iterator) for character in fragment)


def _resolve_goal(task, sources, query, *, use_aliases=True, normalize_language=True, alternatives=False):
    """Conservative lexical alignment; unclear goals require an explicit choice."""
    tree = hierarchy(task, sources)
    goal = _goal(query, allow_multiple=True, normalize_language=normalize_language)
    raw_goal = _goal(query, allow_multiple=True, normalize_language=False)
    if len(goal) < 2:
        raise ValueError('请说明本次要安装的部件或执行的动作。')
    task_title = _compact(re.sub(r'^第\s*\d+\s*步[：:]?', '', task.title))
    task_sources = list(dict.fromkeys(tree['source_ids'] + [s for row in tree['children'] for s in row['source_ids']]))
    common = dict(task_sha256=digest(encoded(task.model_dump())), query=query)
    if goal == task_title or goal == re.sub(r'^(?:安装|组装)', '', task_title):
        return GoalSelection(**common, title=task.title, level='task', selected_node_ids=[n.id for n in task.nodes],
                             source_ids=task_sources, interpretation='按官方完整任务执行；现场状态决定哪些操作仍需完成。')
    operations = {row['id']: row for row in tree['children']}
    objects = {obj.id: obj for obj in task.objects}
    nodes = {node.id: node for node in task.nodes}
    conditions = {row.id: row for row in task.conditions}
    requirements = {row.id: row for row in task.requirements}
    records = {row.id: row for row in sources.records}
    exact = [node for node in task.nodes if raw_goal == _compact(operations[node.id]['title'])
             or raw_goal == _compact(node.instruction)
             and any(node.instruction in records[requirements[r].source_id].text for r in node.requirement_ids)]
    if len(exact) == 1:
        row = operations[exact[0].id]
        return GoalSelection(**common, title=row['title'], level='operation', selected_node_ids=[exact[0].id],
                             source_ids=row['source_ids'], interpretation='按所述官方操作原文执行；仅补足其必要前置操作。')
    clauses = re.split(r'以及|并且|然后|[及和与，,；;]', goal)
    if len(clauses) > 1:
        if any(not clause for clause in clauses) or len(clauses) > len(task.nodes):
            raise ValueError('请明确各个操作目标，或选择官方完整任务。')
        selections = [resolve_goal(task, sources, clause, use_aliases=use_aliases, normalize_language=normalize_language) for clause in clauses]
        selected = {n for item in selections for n in item.selected_node_ids}
        ordered = [n.id for n in task.nodes if n.id in selected]
        return GoalSelection(**common, title=task.title if len(ordered) == len(task.nodes) else '；'.join(operations[n]['title'] for n in ordered),
            level='task' if len(ordered) == len(task.nodes) else 'operation', selected_node_ids=ordered,
            source_ids=list(dict.fromkeys(s for item in selections for s in item.source_ids)),
            interpretation='已将各个目标对应到官方操作；按依赖顺序执行，仅补足必要前置。')
    # A verbatim official instruction may contain punctuation; unrelated compound goals still need a choice.
    goal = _goal(query, normalize_language=normalize_language)
    # Specific action words disambiguate destination nouns, e.g. “slide into base”.
    # Object terms such as “可拆卸白色料盘支架” contain verbs without requesting those actions.
    terms = {_compact(term) for obj in task.objects for term in [obj.name] + (obj.aliases if use_aliases else [])}
    noun_spans = [match.span() for term in terms if term for match in re.finditer(re.escape(term), goal)]
    actions = [match.group() for match in re.finditer(r'滑入|滑出|插入|拔出|放入|装入|拆卸|拆除|移除|卸下|固定|连接', goal)
               if not any(a <= match.start() and match.end() <= b for a,b in noun_spans)]
    if len(set(actions)) > 1:
        raise ValueError('目标包含多个动作，请选择官方任务或一个具体操作。')
    verb = actions[0] if actions else None
    noun = goal.replace(verb, '', 1) if verb else re.sub(r'^(?:安装|组装)', '', goal)
    grammar = re.fullmatch(r'(?:将|把)(.+?)(?:从[上下左右前后]向[上下左右前后])?'
                           + re.escape(verb) + r'(.+)', goal) if verb else None

    def alias_match(fragment, obj):
        fragment, name = _compact(fragment), _compact(obj.name)
        return use_aliases and any(_matches(fragment, alias) and
            (fragment == _compact(alias) or any(name[i:i+2] in fragment for i in range(len(name)-1)))
            for alias in obj.aliases)

    def object_match(fragment, identity):
        obj = objects[identity]
        return _matches(fragment, obj.name) or alias_match(fragment, obj)

    def destination_matches(node, destination):
        guards = [set(conditions[cid].object_ids) for cid in node.precondition_ids]
        allowed = set.intersection(*guards) if guards else set()
        named_guard = len(allowed) == 1 and any(object_match(destination, oid) for oid in allowed)
        quoted = operations[node.id]['title']
        explicit = verb is not None and verb + destination in _compact(quoted)
        return named_guard or explicit

    candidates = []
    for node in task.nodes:
        label = operations[node.id]['title']
        if verb and verb not in _compact(label):
            continue
        inherited = {oid for dependency in node.depends_on for oid in nodes[dependency].object_ids}
        introduced = set(node.object_ids) - inherited
        targets = introduced or set(node.object_ids)
        actor = re.search(r'(?:将|把)(.+?)(?:从[上下左右前后]向[上下左右前后])?(?:安装|固定|滑入|插入|连接)', label)
        if actor is None:
            actor = re.search(r'(?:将|把)(.+?)(?:从[上下左右前后]向[上下左右前后])?(?:安装|固定|滑入|插入|连接)', node.instruction)
        if actor is None:
            actor = re.search(r'(?:安装|固定|滑入|插入)([^，。；;]+)', label)
        if actor:
            named_actors = {oid for oid in targets if object_match(actor[1], oid)}
            targets = named_actors or targets
        named = any(object_match(noun, oid) for oid in targets)
        if grammar:
            named = (any(object_match(grammar[1], oid) for oid in targets)
                     and destination_matches(node, grammar[2]))
        direct = goal == _compact(label)
        if named or direct:
            candidates.append(node)
    interpreted = False
    if not candidates and verb:
        action_candidates = [n for n in task.nodes if verb in _compact(operations[n.id]['title'])]
        if len(action_candidates) == 1 and destination_matches(action_candidates[0], noun):
            candidates, interpreted = action_candidates, True
    if len(candidates) != 1 and not (alternatives and candidates):
        raise ValueError('无法唯一对应到官方操作，请选择完整任务或明确具体操作。')
    selections = []
    for node in candidates:
        row = operations[node.id]
        fragments = [grammar[1], grammar[2]] if grammar else [noun]
        alias_sources = [source for oid in node.object_ids for fragment in fragments
                         if not _matches(fragment, objects[oid].name) and alias_match(fragment, objects[oid])
                         for source in objects[oid].source_ids]
        explanation = ('原话按官方唯一对应动作解释为“' + row['title'] + '”；所提部件作为操作关联位置，并非新的安装步骤。'
                   if interpreted else ('候选为' if alternatives and len(candidates) > 1 else '本次目标为')
                   + '官方子操作“' + row['title'] + '”；仅补足其必要前置操作。')
        selections.append(GoalSelection(**common, title=row['title'], level='operation', selected_node_ids=[node.id],
                         source_ids=list(dict.fromkeys(row['source_ids'] + alias_sources)), interpretation=explanation))
    return selections if alternatives else selections[0]


def resolve_goal(task, sources, query, *, use_aliases=True, normalize_language=True):
    return _resolve_goal(task, sources, query, use_aliases=use_aliases, normalize_language=normalize_language)


def goal_candidates(task, sources, query, *, use_aliases=True, normalize_language=True):
    """Source-backed choices for clarification, without confidence or authorization."""
    tree = hierarchy(task, sources)
    vague = _compact(query) in {'安装', '怎么安装', '如何安装', '怎么做', '下一步', '下一步怎么做'}
    try:
        result = _resolve_goal(task, sources, query, use_aliases=use_aliases,
                               normalize_language=normalize_language, alternatives=True)
    except ValueError:
        if not vague:
            return []
        result = [GoalSelection(task_sha256=digest(encoded(task.model_dump())), query=query, title=row['title'],
            level='operation', selected_node_ids=[row['id']], source_ids=row['source_ids'],
            interpretation='请明确是否以此官方子操作为目标；选择不会确认现场进度。') for row in tree['children']]
    if not isinstance(result, list):
        return [result.model_dump()]
    if len(result) > 1:
        result.insert(0, GoalSelection(task_sha256=digest(encoded(task.model_dump())), query=query, title=task.title,
            level='task', selected_node_ids=[n.id for n in task.nodes],
            source_ids=list(dict.fromkeys(tree['source_ids'] + [s for row in tree['children'] for s in row['source_ids']])),
            interpretation='也可选择官方完整任务；选择后仍需核实现场进度。'))
    return [row.model_dump() for row in result]
