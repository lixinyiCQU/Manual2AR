"""Immutable per-variant packages; API input only selects from this server whitelist."""
from pathlib import Path
import json
from fastapi import HTTPException
from .task import TaskPackage
from manual2ar.resources import ResourceStore

UNBOX = 'a1_mini_standalone_unboxing_v1'
FIRST = 'a1_mini_first_print_external_v1'
LOAD = 'a1_mini_load_external_v1'
UNLOAD = 'a1_mini_unload_external_v1'


class TaskRegistry:
    def __init__(self, config=None):
        store = ResourceStore.configured(config)
        self.entries = store.json('module.guidance.catalog')['tasks']
        self.packages = {}
        for entry in self.entries:
            root = store.inside(entry['root'])
            for variant in entry['variants']:
                prefix = f"/api/guidance/tasks/{entry['id']}/variants/{variant['id']}/references/"
                from .tutorial import TutorialTaskPackage
                package_class = TutorialTaskPackage if entry.get('package_type') == 'tutorial_v2' else TaskPackage
                task = package_class(root, variant['procedure'], prefix, 'GuidanceReferences')
                if task.document.task.task_id != entry['id']: raise ValueError('Catalog task identity mismatch')
                states = {s.state_id: s for s in task.document.states}
                visited = []; cursor = task.document.task.initial_state
                while cursor is not None:
                    if cursor in visited or cursor not in states: raise ValueError('Invalid task graph')
                    visited.append(cursor); cursor = states[cursor].next_on_success
                if set(visited) != set(states) or visited[-1] not in task.document.task.terminal_states:
                    raise ValueError('Task has unreachable/nonterminal states')
                # The existing engine is deliberately reused for linear, compiled variants.
                if visited != [s.state_id for s in task.document.states]: raise ValueError('Variant must be linear')
                self.packages[(entry['id'], variant['id'])] = task

    def entry(self, task_id):
        entry = next((e for e in self.entries if e['id'] == task_id), None)
        if entry is None: raise HTTPException(422, '不支持的任务；请选择当前目录支持的A1 mini任务。')
        return entry

    def resolve(self, task_id, variant_id=None):
        entry = self.entry(task_id)
        variant_id = variant_id or entry['default_variant']
        package = self.packages.get((task_id, variant_id))
        if package is None: raise HTTPException(422, '不支持的任务变体；请返回任务页选择支持的版本。')
        return variant_id, package

    def catalog(self):
        tasks = []
        for entry in self.entries:
            variants = []
            for v in entry['variants']:
                package = self.packages[(entry['id'], v['id'])]
                variants.append({'id': v['id'], 'title': v['title'], 'task_revision': package.revision,
                                 'step_count': len(package.document.states)})
            default = self.packages[(entry['id'], entry['default_variant'])]
            photo = next(p for p in default.images.values() if Path(p['path']).name == entry['thumbnail'])
            tasks.append({'id': entry['id'], 'title': entry['title'], 'description': entry['description'],
                          'default_variant': entry['default_variant'], 'variants': variants,
                          'thumbnail': {'url': default.reference_prefix+entry['thumbnail'],
                                        'local_file': 'GuidanceReferences/'+entry['thumbnail'], 'sha256': photo['sha256']}})
        return {'title': '模块二：操作指导', 'scope': 'Bambu Lab A1 mini · 外挂料盘 / AMS lite 开箱', 'tasks': tasks}
