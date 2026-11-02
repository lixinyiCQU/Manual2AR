"""GPU-only evidence helpers; never import the local teaching backend."""
import hashlib,json
from pathlib import Path
from manual2ar_contracts.gpu import Target

def dump(path,value):
    Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
def file_digest(path):
    with Path(path).open('rb') as source:return hashlib.file_digest(source,'sha256').hexdigest()
def validate_targets(targets):
    items=[Target.model_validate(t).model_dump() for t in targets]
    if not 1<=len(items)<=8 or len({t['component_id'] for t in items})!=len(items):raise ValueError('Invalid target identities')
    return items
