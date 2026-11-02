"""Pinned public SAM3.1 source, size/SHA verification, atomic publication."""
from pathlib import Path
import hashlib
import json
import shutil
import urllib.request
from manual2ar_inference.artifacts import dump,file_digest


def verified_fetch(spec,path):
    path=Path(path)
    if path.exists():
        if path.stat().st_size==spec['size'] and file_digest(path)==spec['sha256']:return
        raise ValueError('Existing checkpoint failed size/SHA validation: '+path.name+'; move it aside before retrying')
    path.parent.mkdir(parents=True,exist_ok=True);temporary=path.with_suffix(path.suffix+'.part')
    try:
        fingerprint=hashlib.sha256();size=0
        with urllib.request.urlopen(spec['url'],timeout=120) as response,temporary.open('wb') as target:
            while chunk:=response.read(4*1024*1024):
                size+=len(chunk)
                if size>spec['size']:raise ValueError('Weight download exceeds expected size')
                fingerprint.update(chunk);target.write(chunk)
        if size!=spec['size'] or fingerprint.hexdigest()!=spec['sha256']:raise ValueError('Weight download size/SHA mismatch')
        temporary.replace(path)
    finally:temporary.unlink(missing_ok=True)


def prepare_sam31(config,root):
    sources=json.loads(Path(__import__('manual2ar_inference.engines',fromlist=['']).__file__).with_name('sam31_sources.json').read_text())
    path=Path(root)/config['sam3_checkpoint'];verified_fetch(sources['weights'],path)
    verified_fetch(sources['license'],path.with_suffix('.LICENSE'))
    dump(path.with_suffix('.source.json'),sources)
    return sources
