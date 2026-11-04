"""Background Colab preparation and GPU worker supervision; no teaching dependencies.

Only status.json and inference.connection.local.json are exchanged with the host.
PID ownership is verified with Linux boot/start identities before stopping a child.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import signal
import subprocess
import sys
import tempfile
import time
import urllib.request


def private_json(path, value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(prefix=path.name+'.',dir=path.parent)
    try:
        os.fchmod(fd,0o600)
        with os.fdopen(fd,'w') as stream:
            json.dump(value,stream,ensure_ascii=False,indent=2);stream.flush();os.fsync(stream.fileno())
        os.replace(name,path)
    finally:
        Path(name).unlink(missing_ok=True)


def process_identity(pid):
    try:
        stat=Path(f'/proc/{pid}/stat').read_text().rsplit(')',1)[1].split()
        if stat[0]=='Z':return None
        return {'pid':pid,'boot':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                'start':stat[19]}
    except (OSError,ValueError,IndexError):return None


def alive(identity):
    return bool(identity) and process_identity(identity['pid'])==identity


def stop_owned(identity):
    if not alive(identity):return False
    # Each managed child was spawned in its own process session.
    try:group=os.getpgid(identity['pid'])
    except ProcessLookupError:return False
    if group!=identity['pid']:raise RuntimeError('Process group ownership mismatch')
    try:os.killpg(identity['pid'],signal.SIGTERM)
    except ProcessLookupError:return True
    for _ in range(30):
        if not alive(identity):return True
        time.sleep(.1)
    if alive(identity):
        try:os.killpg(identity['pid'],signal.SIGKILL)
        except ProcessLookupError:pass
    return True


def read(path, default=None):
    try:return json.loads(Path(path).read_text())
    except FileNotFoundError:return default


def stop(root):
    root=Path(root);state=read(root/'worker-processes.local.json',{})
    # Stop installation first so it cannot launch a new service after this action.
    for role in ['launcher','tunnel','service','recorder']:
        stop_owned(state.get(role))
    (root/'inference.connection.local.json').unlink(missing_ok=True)
    private_json(root/'status.json',{'state':'stopped','stage':'stopped'})


def api(root, route, method='GET'):
    config=read(root/'configs/inference.local.json')
    req=urllib.request.Request('http://127.0.0.1:'+str(config['port'])+route,
        data=b'{}' if method=='POST' else None,
        headers={'Authorization':'Bearer '+config['api_token'],'Content-Type':'application/json'},method=method)
    with urllib.request.urlopen(req,timeout=600 if method=='POST' else 3) as response:
        return json.load(response)


def spawn(root, role, args):
    from deploy.colab.environment import child_environment
    with (root/(role+'.log')).open('a') as log:
        child=subprocess.Popen(args,cwd=root,env=child_environment(),stdout=log,
                               stderr=subprocess.STDOUT,start_new_session=True)
    state=read(root/'worker-processes.local.json',{})
    state[role]=process_identity(child.pid);private_json(root/'worker-processes.local.json',state)
    return child


def run(root):
    from deploy.colab.drive_cache import DriveCache
    from deploy.colab.environment import redact
    root=Path(root).resolve();os.chdir(root)
    options=read(root/'launch-options.json');stage='preparing'
    def status(value, **extra):
        nonlocal stage
        stage=value
        private_json(root/'status.json',{'state':'starting','stage':value,
                     'bundle_sha256':options['bundle_sha256'],'options_sha256':options['options_sha256'],**extra})
    try:
        status('preparing_environment')
        if not __import__('shutil').which('nvidia-smi'):raise RuntimeError('No NVIDIA runtime assigned')
        config=read(root/'configs/inference.local.json',read(root/'configs/inference.example.json'))
        config['api_token']=config.get('api_token') or secrets.token_urlsafe(32)
        config['precision']=options['inference']['precision']
        config['cutie'].update(options['inference']['cutie'])
        config['retain_initial_images']=options['inference']['retain_initial_images']
        # Runtime address and evidence root are deployment-owned.
        config.update(host='127.0.0.1',port=8021,log_root='gpu_data/learning_cutie')
        private_json(root/'configs/inference.local.json',config)
        drive=options['drive_cache']
        if drive['enabled'] and not Path('/content/drive/MyDrive').is_dir():
            raise RuntimeError('Drive not mounted; use the VS Code Drive task first')
        cache=DriveCache(root,drive['path'] if drive['enabled'] else None,drive['cache_environment'])
        os.environ['TORCH_HOME']=str(root/'.torch-cache')
        key=cache.environment_key()[0];marker=read(root/'environment-ready.json',{})
        python=root/'.gpu-venv/bin/python'
        if python.exists() and marker.get('key')==key:
            # A process restart on the same VM should not reinstall its environment.
            cache._validate_python(str(python))
        else:
            python=Path(cache.prepare());private_json(root/'environment-ready.json',{'key':key})
        status('loading_models')
        service=spawn(root,'service',[str(python),'-B','-u','-m','manual2ar_inference.app',
            '--config',str(root/'configs/inference.local.json'),'--work-dir',str(root)])
        health=None
        for _ in range(120):
            if service.poll() is not None:raise RuntimeError('GPU service exited; inspect service.log')
            try:health=api(root,'/health');break
            except Exception:time.sleep(.5)
        if not health or not health.get('available'):raise RuntimeError('GPU model dependencies or checkpoints unavailable')
        api(root,'/v1/warmup','POST')
        cache.save_auxiliary()
        status('opening_connection')
        public=options['public_url']
        if not public:
            binary=root/'cloudflared'
            if not binary.exists():
                urllib.request.urlretrieve('https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64',binary)
                binary.chmod(0o700)
            (root/'tunnel.log').write_text('')
            tunnel=spawn(root,'tunnel',[str(binary),'tunnel','--url','http://127.0.0.1:8021','--no-autoupdate'])
            for _ in range(120):
                if tunnel.poll() is not None:raise RuntimeError('Tunnel exited; inspect tunnel.log')
                match=re.search(r'https://[a-z0-9-]+\.trycloudflare\.com',(root/'tunnel.log').read_text(errors='replace'))
                if match:public=match.group(0);break
                time.sleep(.5)
            if not public:raise RuntimeError('Tunnel did not return an address')
        private_json(root/'inference.connection.local.json',{
            'url':public,'api_token':config['api_token'],'protocol':health['protocol']})
        private_json(root/'status.json',{'state':'ready','stage':'ready','bundle_sha256':options['bundle_sha256'],
            'options_sha256':options['options_sha256'],'models_loaded':True,
            'remote_logs':read(root/'retention-status.json',{})})
    except BaseException as error:
        # Preserve a useful private log, but status/host receipts contain no token.
        detail=redact(type(error).__name__+': '+str(error),root)
        print(detail,flush=True)
        state=read(root/'worker-processes.local.json',{})
        for role in ['tunnel','service']:stop_owned(state.get(role))
        (root/'inference.connection.local.json').unlink(missing_ok=True)
        private_json(root/'status.json',{'state':'failed','stage':stage,
                     'error_type':type(error).__name__,'error_message':detail[-4000:]})
        stop_owned(state.get('recorder'))
        raise


def launch(root, options):
    """Called in the remote notebook kernel; returns immediately for host polling."""
    root=Path(root).resolve();state=read(root/'worker-processes.local.json',{})
    previous=read(root/'status.json',{})
    same=all(previous.get(k)==options[k] for k in ['bundle_sha256','options_sha256'])
    if previous.get('state')=='ready' and same and alive(state.get('service')) and (options['public_url'] or alive(state.get('tunnel'))):
        try:
            if api(root,'/health').get('available'):return 'reused'
        except Exception:pass
    if alive(state.get('launcher')):
        if same:return 'preparing'
        raise RuntimeError('A different deployment is preparing; stop it before retrying')
    stop(root)
    from deploy.colab.retention import start_recorder
    start_recorder(root,options.get('remote_logs',{'enabled':False}))
    private_json(root/'launch-options.json',options)
    private_json(root/'status.json',{'state':'starting','stage':'queued',
        'bundle_sha256':options['bundle_sha256'],'options_sha256':options['options_sha256']})
    spawn(root,'launcher',[sys.executable,'-B','-u','-m','deploy.colab.worker','start','--root',str(root)])
    return 'started'


def main():
    parser=argparse.ArgumentParser();parser.add_argument('command',choices=['start','stop']);parser.add_argument('--root',type=Path,required=True)
    args=parser.parse_args()
    run(args.root) if args.command=='start' else stop(args.root)

if __name__=='__main__':main()
