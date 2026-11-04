"""Observe real runtime/service availability; never allocate or simulate activity."""
from datetime import datetime,timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

import httpx

from .colab import redact
from deploy.colab.worker import private_json


def utc():return datetime.now(timezone.utc).isoformat()


def runtime_id(record):
    endpoint=record.get('endpoint') if record else None
    return hashlib.sha256(endpoint.encode()).hexdigest()[:12] if endpoint else None


def observe(host):
    before=host.cli.record()
    value={'at':utc(),'session':host.c['session_name'],'runtime_id':runtime_id(before),
           'runtime_present':None,'public_health':False}
    try:
        if not before:
            value.update(state='not_tracked',runtime_present=False)
        else:
            host.cli.run(['status','-s',host.c['session_name']],timeout=30)
            record=host.cli.record()
            if not record:
                value.update(state='runtime_gone',runtime_present=False)
            else:
                value.update(runtime_present=True,runtime_id=runtime_id(record))
                receipt_path=host.logs/'installation.json'
                receipt=json.loads(receipt_path.read_text()) if receipt_path.is_file() else {}
                current=hashlib.sha256(host.connection.read_bytes()).hexdigest() if host.connection.is_file() else None
                if not current or receipt.get('connection_sha256')!=current or receipt.get('runtime_id')!=record.get('endpoint'):
                    value['state']='connection_unverified'
                else:
                    health=host.checker(json.loads(host.connection.read_text()))
                    value.update(state='ready',public_health=True,models_loaded=bool(health.get('models_loaded')))
    except httpx.HTTPStatusError as error:
        code=error.response.status_code
        state=('public_auth_error' if code in (401,403) else 'public_unreachable') if value['runtime_present'] is True else 'check_failed'
        value.update(state=state,http_status=code)
    except httpx.TransportError as error:
        value.update(state='public_unreachable' if value['runtime_present'] is True else 'check_failed',error_type=type(error).__name__)
        # Save categories, never request URLs, headers or credentials.
        reason=str(error.__cause__ or error).lower()
        value['network_hint']='tls' if 'ssl' in reason or 'tls' in reason else ('dns' if 'name' in reason and 'resol' in reason else 'transport')
    except Exception as error:
        value.update(state='check_failed',error_type=type(error).__name__)
    value['finished_at']=utc()
    private_json(host.logs/'monitor-status.json',value)
    with (host.logs/'monitor-events.jsonl').open('a') as stream:
        os.fchmod(stream.fileno(),0o600)
        stream.write(json.dumps(value,ensure_ascii=False)+'\n')
    return value


MESSAGES={
    'ready':'GPU 服务可用',
    'runtime_gone':'当前账号不再返回本项目运行时；可能已回收、外部释放或切换了账号',
    'not_tracked':'没有本项目会话记录；未申请 GPU',
    'connection_unverified':'运行时存在，当前连接尚未验证或属于另一运行时',
    'public_unreachable':'运行时存在，但公网服务不可达；不能据此判定 GPU 已回收',
    'public_auth_error':'运行时存在，公网服务拒绝鉴权；请检查连接配置',
    'check_failed':'状态查询失败；尚不能判断运行时是否存在',
}


def display(value):
    at=datetime.fromisoformat(value['at']).astimezone().isoformat(timespec='seconds')
    print('['+at+'] '+MESSAGES[value['state']]+
          (' ('+value['error_type']+')' if value.get('error_type') else ''),flush=True)


def capture_logs(host,value):
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    destination=host.logs/'monitor-captures'/stamp
    private_json(destination/'observation.json',value)
    secrets=[]
    try:secrets=[json.loads(host.connection.read_text()).get('api_token','')]
    except (OSError,ValueError):pass
    print('正在保存异常现场日志（不执行笔记本代码）…',flush=True)
    with tempfile.TemporaryDirectory(dir=host.cache) as directory:
        for name in ('status.json','service.log','tunnel.log'):
            path=Path(directory)/name
            try:
                host.cli.run(['download','-s',host.c['session_name'],host.remote(name),str(path)],timeout=15)
                text=redact(path.read_text(errors='replace'),secrets)
                target=destination/name;target.write_text(text[-65536:]);target.chmod(0o600)
            except (RuntimeError,OSError,subprocess.TimeoutExpired):continue
    print('异常现场：'+str(destination),flush=True)


def watch(host,max_samples=None):
    # A separate lock allows explicit stop/release while observation is running.
    with (host.cache/'monitor.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise RuntimeError('本工作树已有 Colab 监控正在运行')
        interval=host.c.get('monitor_seconds',30)
        print(f'每轮查询完成后等待 {interval} 秒；Ctrl+C 仅停止监控，不释放 GPU。日志：{host.logs}',flush=True)
        count=0;previous=None
        while True:
            value=observe(host);display(value);count+=1
            signature=(value['runtime_id'],value['state'])
            if signature!=previous and value['state'] in ('public_unreachable','public_auth_error'):
                capture_logs(host,value)
            previous=signature
            if max_samples is not None and count>=max_samples:return
            host.sleep(interval)


def diagnose(host):
    """One user-requested inspection, rather than repeated notebook executions."""
    value=observe(host);display(value)
    if value['runtime_present'] is not True:return value
    with host.locked(),tempfile.TemporaryDirectory(dir=host.cache) as directory:
        directory=Path(directory);request=directory/'diagnose.py'
        request.write_text('''from pathlib import Path
import sys,subprocess,json
root=Path('''+repr(host.c['remote_root'])+''')
sys.path.insert(0,str(root))
from deploy.colab.worker import read,alive,api,private_json
state=read(root/'worker-processes.local.json',{})
result={'processes':{k:alive(state.get(k)) for k in ('launcher','service','tunnel')}}
try:
    health=api(root,'/health')
    result['local_service']={'available':health.get('available'),'models_loaded':health.get('models_loaded')}
except Exception as error:result['local_service_error']=type(error).__name__
try:
    probe=subprocess.run(['nvidia-smi','--query-gpu=memory.used,memory.total,utilization.gpu','--format=csv,noheader'],capture_output=True,text=True,timeout=5)
    result['gpu_memory_and_utilization']=probe.stdout.strip() if probe.returncode==0 else 'unavailable'
except Exception as error:result['gpu_probe_error']=type(error).__name__
private_json(root/'diagnosis.json',result)
''')
        host.cli.execute(request,timeout=30)
        report=directory/'diagnosis.json';host.cli.download(host.remote('diagnosis.json'),report)
        result=json.loads(report.read_text())
        # Remote output is untrusted; copy only the intended diagnostic fields.
        allowed=('processes','local_service','local_service_error','gpu_memory_and_utilization','gpu_probe_error')
        result={k:result[k] for k in allowed if k in result};result['at']=utc()
        private_json(host.logs/'diagnosis.json',result)
        print(redact(json.dumps(result,ensure_ascii=False)),flush=True)
        host.collect_logs()
    return result
