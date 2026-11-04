"""Persist bounded diagnostic logs and telemetry; no inference or keepalive calls."""
import argparse
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
import uuid

from deploy.common.files import private_json,private_text
from .environment import child_environment,redact
from .worker import alive,process_identity,read,stop_owned

FILES=('launcher.log','bootstrap.log','service.log','gpu_service.log','tunnel.log',
       'status.json','startup_cache.json','gpu_data/learning_cutie/events.jsonl',
       'diagnostic-events.jsonl','diagnostic-status.json')


def utc():return datetime.now(timezone.utc).isoformat()


def sample(root):
    root=Path(root);state=read(root/'worker-processes.local.json',{})
    result={'at':utc(),'uptime_seconds':float(Path('/proc/uptime').read_text().split()[0]),
            'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
            'processes':{name:alive(state.get(name)) for name in ('launcher','service','tunnel')}}
    memory={}
    for line in Path('/proc/meminfo').read_text().splitlines():
        key,_,value=line.partition(':')
        if key in ('MemTotal','MemAvailable','SwapFree'):memory[key+'_KiB']=int(value.split()[0])
    result['memory']=memory
    disk=os.statvfs(root)
    result['disk_available_bytes']=disk.f_bavail*disk.f_frsize
    try:
        gpu=subprocess.run(['nvidia-smi','--query-gpu=name,memory.used,memory.total,utilization.gpu','--format=csv,noheader'],
                           capture_output=True,text=True,timeout=5)
        result['gpu']=gpu.stdout.strip() if gpu.returncode==0 else 'unavailable'
    except (OSError,subprocess.TimeoutExpired) as error:result['gpu_error']=type(error).__name__
    return result


def persist(root,destination):
    root,destination=Path(root),Path(destination);destination.mkdir(parents=True,exist_ok=True)
    record=sample(root)
    for name in FILES:
        source=root/name
        if not source.is_file() or source.is_symlink():continue
        try:
            with source.open('rb') as stream:
                size=source.stat().st_size
                if size>262144:stream.seek(size-262144);stream.readline()
                text=stream.read(262144).decode('utf-8',errors='replace')
            private_text(destination/'logs'/name,redact(text,root))
        except OSError as error:record.setdefault('copy_errors',{})[name]=type(error).__name__
    with (destination/'observations.jsonl').open('a') as stream:
        os.fchmod(stream.fileno(),0o600)
        stream.write(json.dumps(record,ensure_ascii=False)+'\n');stream.flush()
    private_json(destination/'latest.json',record)
    return record


def run(root,destination,interval,minutes):
    root,destination=Path(root),Path(destination);stopped=threading.Event();reason='duration_completed'
    def terminate(signum,frame):
        nonlocal reason
        reason='signal_'+str(signum);stopped.set()
    for sig in (signal.SIGINT,signal.SIGTERM):signal.signal(sig,terminate)
    started=time.monotonic()
    private_json(destination/'run.json',{'started_at':utc(),'duration_minutes':minutes,'interval_seconds':interval,
                                        'policy':'passive_observation_no_kernel_keepalive'})
    while True:
        try:
            record=persist(root,destination)
            private_json(root/'retention-status.json',{'at':record['at'],'state':'recording','destination':str(destination)})
        except Exception as error:
            private_json(root/'retention-status.json',{'at':utc(),'state':'write_failed','error_type':type(error).__name__,
                                                     'destination':str(destination)})
        remaining=minutes*60-(time.monotonic()-started)
        if remaining<=0 or stopped.wait(min(interval,remaining)):break
    try:
        persist(root,destination)
        private_json(destination/'end.json',{'at':utc(),'reason':reason})
        private_json(root/'retention-status.json',{'at':utc(),'state':'ended','reason':reason,'destination':str(destination)})
    except OSError:pass


def start_recorder(root,settings,minutes=720):
    root=Path(root).resolve()
    if not settings.get('enabled',False):return None
    path=Path(settings['path']).resolve()
    if not path.is_relative_to('/content/drive/MyDrive') or not Path('/content/drive/MyDrive').is_dir():
        raise RuntimeError('Persistent remote logs require an authorized mounted Google Drive')
    previous=read(root/'worker-processes.local.json',{})
    stop_owned(previous.get('recorder'))
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8]
    destination=path/root.name/stamp;destination.mkdir(parents=True,exist_ok=True)
    with (root/'recorder.log').open('a') as log:
        child=subprocess.Popen([sys.executable,'-B','-u','-m','deploy.colab.retention','--root',str(root),
            '--destination',str(destination),'--interval',str(settings['interval_seconds']),'--minutes',str(minutes)],
            cwd=root,env=child_environment(),stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    previous['recorder']=process_identity(child.pid);private_json(root/'worker-processes.local.json',previous)
    private_json(root/'retention-status.json',{'at':utc(),'state':'starting','destination':str(destination)})
    return str(destination)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--destination',type=Path,required=True);parser.add_argument('--interval',type=int,default=15)
    parser.add_argument('--minutes',type=int,default=720);args=parser.parse_args()
    if not 5<=args.interval<=300 or not 1<=args.minutes<=720:parser.error('Invalid observation duration/interval')
    run(args.root,args.destination,args.interval,args.minutes)

if __name__=='__main__':main()
