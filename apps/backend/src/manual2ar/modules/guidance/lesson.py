"""Reviewed reading layer. Immutable procedures, evidence and checks stay intact."""
from copy import deepcopy
import hashlib
import json
import re
from manual2ar.resources import ResourceStore


KINDS=('scope','precondition','action','materials','caution','note')
TITLES={'scope':'适用版本','precondition':'操作前注意','action':'操作指导',
        'materials':'配件清单','caution':'注意事项','note':'补充说明'}


def substep_caption(title,instruction):
    """Readable source excerpt; retain the immutable original heading separately."""
    def clean(value):return re.sub(r'^\s*\d+\s*[.)、．：:]*\s*','',value.strip())
    value=clean(title)
    if len(value)<2:
        value=next((clean(line) for line in instruction.splitlines() if clean(line)),'')
    value=re.split(r'[。；\n]',value,maxsplit=1)[0]
    return value if len(value)<=36 else value[:36]+'…'


def source_fields(presentation, task, refs=None):
    result={key:presentation.get(key,'') or '' for key in ('instruction','chapter_context','applicability_note')}
    for key in ('warnings','tools','materials'):
        result[key]='\n\n'.join(presentation.get(key) or [])
    for name,ref in (refs or {}).items():
        state=next(s for s in task.document.states if s.state_id==ref['state_id'])
        result[name]=state.instruction.split('\n\n')[ref['paragraph']]
    return result


def source_hash(fields):
    return hashlib.sha256(json.dumps(fields,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


class LessonPresenter:
    def __init__(self, config):
        self.bundle=ResourceStore.configured(config).json('module.guidance.lessons')
        if self.bundle['schema_version']!='manual2ar-reviewed-lessons-v1':raise ValueError('Unsupported lesson bundle')

    def compose(self, variant, state_id, selected, presentation, task):
        key=variant+'/'+state_id+'/'+(selected or '-')
        card=self.bundle['cards'].get(key)
        if card is None:
            # New, unreviewed tasks retain all text, without pretending to have editorial review.
            return {'schema_version':'manual2ar-lesson-v1','reviewed':False,'chapter_title':presentation['title'],
                'step_title':'','sections':[{'kind':'action','title':'操作指导',
                    'blocks':[{'text':presentation['instruction']}]},
                    {'kind':'caution','title':'注意事项','blocks':[{'text':s} for s in presentation.get('warnings',[])]}]}
        fields=source_fields(presentation,task,card.get('source_refs'))
        if source_hash(fields)!=card['source_sha256']:
            raise ValueError('Reviewed lesson source changed; review the reading layer: '+key)
        sections=[]
        for kind in KINDS:
            blocks=[];seen=set()
            for block in card['blocks']:
                if block['kind']!=kind:continue
                raw=fields[block['source_field']];a,b=block['source_span']
                if hashlib.sha256(raw[a:b].encode()).hexdigest()!=block['span_sha256']:
                    raise ValueError('Lesson source span mismatch: '+key)
                # Repeated original notices can share one display item, with both citations retained.
                normalized=re.sub(r'\s+','',block['text'])
                if normalized in seen:continue
                seen.add(normalized);blocks.append(deepcopy(block))
            if blocks:sections.append({'kind':kind,'title':TITLES[kind],'blocks':blocks})
        return {'schema_version':'manual2ar-lesson-v1','reviewed':True,'revision':self.bundle['revision'],
            'chapter_title':presentation['title'].strip().rstrip('。：：'),
            'step_title':card['step_title'],'sections':sections,'source_sha256':card['source_sha256']}
