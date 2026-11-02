"""Export the canonical inference runtime for Colab, containers or SSH hosts."""
import json
import zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]

def gpu_bundle():
    target=Path(__import__('tempfile').gettempdir())/'Manual2AR-GPU-source.zip';target.parent.mkdir(parents=True,exist_ok=True)
    mapping={}
    for prefix,folder in [('manual2ar_inference','apps/inference/src/manual2ar_inference'),('manual2ar_contracts','packages/contracts/src/manual2ar_contracts')]:
        for source in sorted((ROOT/folder).rglob('*')):
            if source.is_file() and source.suffix in ('.py','.json'):
                mapping[prefix+'/'+source.relative_to(ROOT/folder).as_posix()]=source.relative_to(ROOT).as_posix()
    for folder in ['deploy/common','deploy/colab']:
        for source in sorted((ROOT/folder).glob('*.py')):mapping[source.relative_to(ROOT).as_posix()]=source.relative_to(ROOT).as_posix()
    mapping['deploy/__init__.py']='deploy/__init__.py'
    for name in ['deploy/hpc/run.sh','deploy/hpc/README.md']:
        mapping[name]=name
    mapping['deploy/common/requirements.txt']='apps/inference/requirements-gpu.txt'
    mapping['configs/inference.example.json']='configs/inference.example.json'
    import hashlib
    manifest={name:dict(source=source,sha256=hashlib.sha256((ROOT/source).read_bytes()).hexdigest()) for name,source in mapping.items()}
    with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as archive:
        for name,source in mapping.items():archive.write(ROOT/source,name)
        archive.writestr('bundle.manifest.json',json.dumps(manifest,sort_keys=True,indent=2))
    return target


def main():
    from manual2ar.application.config import load, resolve
    import shutil
    c=load();dest=resolve(c['paths']['builds'])/'Manual2AR-Inference.zip'
    dest.parent.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(gpu_bundle(),dest)
    print(dest)

if __name__=='__main__':main()
