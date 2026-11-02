"""Prepare the exported GPU folder on Colab/Runpod, never on the local backend.

Configuration lives in cloud/config.local.json. Resolved repository commits and
package versions are locked for auditing; reruns reuse cloned sources/weights.
"""
from pathlib import Path
import hashlib
import json
import os
import secrets
import shutil
import subprocess
import sys
import urllib.request
from .files import private_json

ROOT=Path.cwd().resolve()
STAGE='preflight'


def stage(name):
    global STAGE
    STAGE=name
    print('\n[bootstrap] '+name,flush=True)


def validate_python(version):
    if tuple(version[:2])!=(3,12):
        raise SystemExit('This pinned environment requires Python 3.12 (NumPy 1.26.4 does not support Python 3.13+). Re-upload the updated notebook: it creates .gpu-venv automatically.')


def command(args,**kwargs):subprocess.run(args,check=True,**kwargs)


def source_install_command(name,folder):
    # Hatchling's editable build needs `editables` when build isolation is off.
    # Install pinned inference wheels; no editable training repository required.
    args=[sys.executable,'-m','pip','install','-v','--no-deps','--no-build-isolation']
    if name not in ('cutie','ultralytics'):args.append('-e')
    return args+[str(folder)]


def sha(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def fetch(url,path):
    if path.exists():return
    path.parent.mkdir(parents=True,exist_ok=True);temporary=path.with_suffix(path.suffix+'.part')
    try:
        with urllib.request.urlopen(url,timeout=120) as source,temporary.open('wb') as target:shutil.copyfileobj(source,target)
        temporary.rename(path)
    finally:temporary.unlink(missing_ok=True)


def main():
    os.chdir(ROOT)
    stage('Check Python version and NVIDIA GPU')
    print('Interpreter: '+sys.executable+'; Python: '+sys.version.split()[0],flush=True)
    validate_python(sys.version_info)
    path=ROOT/'configs/inference.local.json'
    config=json.loads((path if path.exists() else ROOT/'configs/inference.example.json').read_text())
    if not config['api_token']:config['api_token']=secrets.token_urlsafe(32)
    private_json(path,config)
    if shutil.which('nvidia-smi') is None:raise SystemExit('Select an NVIDIA GPU runtime before installing this service')
    command(['nvidia-smi','--query-gpu=name,memory.total','--format=csv,noheader'])
    stage('Install PyTorch and torchvision')
    command([sys.executable,'-m','pip','install','torch==2.7.1','torchvision==0.22.1','--index-url','https://download.pytorch.org/whl/cu126'])
    stage('Install inference dependencies')
    command([sys.executable,'-m','pip','install','-r','deploy/common/requirements.txt'])
    stage('Check CUDA and model hardware requirements')
    import torch
    if not torch.cuda.is_available():raise SystemExit('CUDA unavailable; check GPU assignment and driver compatibility with CUDA 12.6')
    repositories={'ultralytics':('https://github.com/ultralytics/ultralytics.git','ultralytics'),
        'cutie':('https://github.com/hkchengrex/Cutie.git','Cutie')}
    lock={}
    for name,(url,subfolder) in repositories.items():
        stage('Clone and install '+name)
        folder=ROOT/'gpu_repos'/subfolder;folder.parent.mkdir(exist_ok=True)
        if not folder.exists():
            command(['git','clone','--filter=blob:none',url,str(folder)])
            command(['git','checkout',config['revisions'][name]],cwd=folder)
        lock[name]=subprocess.check_output(['git','rev-parse','HEAD'],cwd=folder,text=True).strip()
        if len(config['revisions'][name])==40 and lock[name]!=config['revisions'][name]:
            raise SystemExit('Cached repository revision differs from config: '+name+'; use a fresh GPU folder')
        environment=os.environ.copy()
        command(source_install_command(name,folder),env=environment)
    stage('Verify Cutie package and bundled configuration')
    command([sys.executable,'-c','import cutie; from manual2ar_inference.engines.engine import cutie_config_dir; print("Cutie config:",cutie_config_dir(cutie))'])
    stage('Download and verify fixed SAM3.1 weights')
    from deploy.common.weights import prepare_sam31
    prepare_sam31(config,ROOT)
    stage('Download Cutie weights')
    fetch('https://github.com/hkchengrex/Cutie/releases/download/v1.0/cutie-base-mega.pth',ROOT/config['cutie_checkpoint'])
    weights={key:sha(ROOT/config[key]) for key in ('sam3_checkpoint','cutie_checkpoint')}
    stage('Write environment lock')
    versions=subprocess.check_output([sys.executable,'-m','pip','freeze'],text=True).splitlines()
    (ROOT/'gpu_environment.lock.json').write_text(json.dumps(dict(repositories=lock,weights_sha256=weights,
        package_versions=[s for s in versions if 'gpu_repos' not in s],python=sys.version),indent=2))
    print('GPU environment prepared. Configure service URL in the downloaded connection file; credentials were not printed.')


if __name__=='__main__':
    try:main()
    except (Exception,SystemExit) as error:
        print(f'\n[bootstrap FAILED] Stage: {STAGE}; {type(error).__name__}. Inspect bootstrap.log.',file=sys.stderr,flush=True)
        sys.exit(1)
