"""Load the audited contract and resolve server-owned Prompt/image bindings."""
from pathlib import Path
import hashlib
import json
from manual2ar.modules.guidance.models import ProcedureDocument

from manual2ar.resources import ResourceStore


def digest(data): return hashlib.sha256(data).hexdigest()


class TaskPackage:
    def __init__(self, root=None, procedure_file='procedure.json',
                 reference_prefix='/api/guidance/references/', local_reference_dir='GuidanceReferences'):
        self.root = Path(root).resolve() if root is not None else ResourceStore.configured().inside('tasks/bambu_a1_mini/unboxing/v2')
        procedure_path = (self.root/procedure_file).resolve()
        procedure_path.relative_to(self.root)
        self.reference_prefix = reference_prefix
        self.local_reference_dir = local_reference_dir
        self.bytes = procedure_path.read_bytes()
        self.revision = digest(self.bytes)
        self.document = ProcedureDocument.model_validate_json(self.bytes)
        self.params = self.document.task.parameters
        self.evidence = json.loads((self.root/'evidence.json').read_text())
        self.images = {Path(p).name: item for p, item in self.evidence['images'].items()}
        if len(self.images) != len(self.evidence['images']):
            raise ValueError('Reference image names must be unique')
        self.prompts = {}
        for state in self.document.states:
            for node in state.observation_nodes:
                if node.verification_channel != 'vision': continue
                binding = self.params['inspection_prompts'][node.inspection_id]
                if binding['state_id'] != state.state_id: raise ValueError('Prompt state mismatch')
                body = self.checked_file(binding['path'], binding['sha256'])
                if node.condition not in body.decode('utf-8'): raise ValueError('Prompt condition mismatch')
                self.prompts[node.inspection_id] = (body.decode('utf-8'), binding)
        for image in self.images.values(): self.checked_file(image['path'], image['sha256'])

    def checked_file(self, relative, expected):
        path = (self.root/relative).resolve()
        path.relative_to(self.root)
        data = path.read_bytes()
        if digest(data) != expected: raise ValueError('Task binding hash mismatch: '+relative)
        return data

    def prompt(self, state, node):
        if node not in state.observation_nodes or node.verification_channel != 'vision':
            raise ValueError('Only the current visual observation may call VLM')
        text, binding = self.prompts[node.inspection_id]
        # Detect source edits while a server/session is running as well.
        self.checked_file(binding['path'], binding['sha256'])
        return text, binding

    def images_for(self, state):
        result = []
        for relative in self.params['presentation'][state.state_id]['reference_images']:
            item = self.evidence['images'][relative]
            name = Path(relative).name
            result.append({'id': name, 'url': self.reference_prefix+name,
                           'local_file': self.local_reference_dir+'/'+name,
                           'sha256': item['sha256'],
                           'caption': ' / '.join(item['heading_path']), 'source_url': item['source_page']})
        return result

    def sources_for(self, state):
        ids = list(dict.fromkeys(c for source in [state.manual_provenance, *[n.manual_provenance for n in state.observation_nodes]]
                                for c in source.citation_ids))
        return [{'id': c, 'text': self.evidence['evidence'][c]['text'],
                 'url': self.evidence['evidence'][c]['source_url'],
                 'captured_at': self.evidence['evidence'][c]['captured_at'],
                 'body_sha256': self.evidence['evidence'][c]['body_sha256']} for c in ids]

    def catalog(self):
        sections = []
        for state in self.document.states:
            for source in self.sources_for(state):
                quote = self.evidence['evidence'][source['id']]
                heading = ' / '.join(quote.get('heading_path', []))
                # Exact archived headings and excerpts, not generated task titles.
                if heading and not any(x['title'] == heading and x['url'] == source['url'] for x in sections):
                    sections.append({'title': heading, 'url': source['url'], 'quote': source['text'],
                                     'citation_id': source['id'], 'captured_at': source['captured_at']})
        return {'task_id': self.document.task.task_id, 'task_revision': self.revision,
                'title': self.params['title'], 'scope': self.params['description'],
                'entry_requirements': self.params.get('entry_requirements', []),
                'official_sections': sections,
                'steps': [{'id': s.state_id, 'title': self.params['presentation'][s.state_id]['title'],
                           'channel': 'vision' if any(n.verification_channel == 'vision' for n in s.observation_nodes) else 'manual'}
                          for s in self.document.states]}

    def presentation(self, state, pending):
        spec = self.params['presentation'][state.state_id]
        instruction = state.instruction
        if state.state_id == 'U9':
            if pending is not None and pending.inspection_id == 'U9-C1':
                instruction = '先保持未通电：逐处复核运输固定和全部保护泡沫已移除，并确认热床运动方向有足够空间、布线妥当。完成复核后再确认，本页此时不执行通电。'
            else:
                instruction = '通电前复核已确认。现在连接电源并按下背面电源开关，观察打印机是否正常启动，再确认本项。'
        return {'title': spec['title'], 'instruction': instruction,
                'warnings': spec.get('display_warnings', state.warnings), 'tools': spec['tools'], 'materials': spec['materials'],
                'display_conditions': [{'id': key, 'text': text} for key,text in spec.get('display_conditions', {}).items()],
                'images': self.images_for(state), 'sources': self.sources_for(state)}
