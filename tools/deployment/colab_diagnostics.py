"""Dedicated model-free experiments; never overwrite the business connection."""
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import tempfile
import uuid

from .colab import Orchestrator,DIAGNOSTIC_DEFAULTS,REMOTE_LOG_DEFAULTS,redact
from tools.build.colab_diagnostics import bundle_bytes
from deploy.common.files import private_json


def experiment(host,release=False):
    settings=host.c.get('diagnostics',DIAGNOSTIC_DEFAULTS)
    logs=host.c.get('remote_logs',REMOTE_LOG_DEFAULTS)
    config={**host.c,'session_name':settings['session_name'],'remote_root':'/content/Manual2ARDiagnostics'}
    job=Orchestrator(config,app=host.app)
    job.logs=host.logs/'diagnostics'/settings['suite'];job.logs.mkdir(parents=True,exist_ok=True)
    if release:return job.release()
    with job.locked():
        job.cli.setup();job.cli.run(['sessions'])
        if not job.cli.record():
            if host.cli.record():raise RuntimeError('业务推理运行时仍有记录；请先明确释放它，再启动独立诊断。不会自动停止业务 GPU')
            print('申请独立 '+config['gpu']+' 诊断实例；不加载模型。',flush=True)
            job.cli.run(['new','-s',config['session_name'],'--gpu',config['gpu']],timeout=180)
        job.cli.run(['drivemount','-s',config['session_name']],interactive=True)
        with tempfile.TemporaryDirectory(dir=job.cache) as directory:
            directory=Path(directory);bundle=directory/'diagnostics.zip';bundle.write_bytes(bundle_bytes())
            remote='/content/manual2ar-diagnostics-source.zip';job.cli.run(['upload','-s',config['session_name'],str(bundle),remote])
            nonce=uuid.uuid4().hex;script=directory/'launch.py'
            script.write_text('''import pathlib,sys,zipfile,hashlib,json,importlib
root=pathlib.Path('/content/Manual2ARDiagnostics');root.mkdir(parents=True,exist_ok=True)
archive=pathlib.Path('''+repr(remote)+''')
if hashlib.sha256(archive.read_bytes()).hexdigest()!='''+repr(hashlib.sha256(bundle.read_bytes()).hexdigest())+''':raise ValueError('Source SHA mismatch')
with zipfile.ZipFile(archive) as bundle:bundle.extractall(root)
sys.path.insert(0,str(root));importlib.invalidate_caches()
for name in list(sys.modules):
 if name=='deploy' or name.startswith('deploy.'):del sys.modules[name]
from deploy.colab.diagnostics import launch
from deploy.common.files import private_json
try:
 value=launch(root,'''+repr(settings)+','+repr(logs)+''')
 value['request_id']='''+repr(nonce)+'''
except Exception as error:value={'state':'failed','error_type':type(error).__name__,'request_id':''' +repr(nonce)+'''}
private_json(root/'diagnostic-receipt.json',value)
''')
            job.cli.execute(script)
            receipt=directory/'receipt.json';job.cli.download(job.remote('diagnostic-receipt.json'),receipt)
            value=json.loads(receipt.read_text())
            if value.get('request_id')!=nonce or value.get('state')!='observing':raise RuntimeError('诊断任务未确认启动：'+value.get('error_type','unknown'))
            private_json(job.logs/'receipt.json',value)
            print('无模型诊断已开始；Drive 留存：'+value['destination'],flush=True)
            print('Ctrl+C 只停止本地观察；记录器将在设定时长结束。释放请运行「Colab: 释放诊断运行时」。',flush=True)
    # Control-plane/file observations only; no periodic notebook execution.
    deadline=host.clock()+(settings['duration_minutes']+2)*60
    while host.clock()<deadline:
        job.cli.run(['status','-s',config['session_name']],timeout=30)
        if not job.cli.record():
            private_json(job.logs/'result.json',{'at':datetime.now(timezone.utc).isoformat(),'state':'runtime_no_longer_listed','termination_reason':'not_provided'})
            print('当前账号不再返回诊断实例；请查看 Drive 的最后遥测，平台未提供终止原因。');return
        with tempfile.TemporaryDirectory(dir=job.cache) as directory:
            path=Path(directory)/'retention.json'
            job.cli.download(job.remote('retention-status.json'),path)
            value=json.loads(path.read_text());private_json(job.logs/'latest.json',value)
            print(redact(json.dumps(value,ensure_ascii=False)),flush=True)
            if value.get('state')=='ended':
                print('观察时长已完成；GPU 尚未释放，请运行释放诊断运行时任务。');return
        host.sleep(host.c.get('monitor_seconds',30))
    print('本地观察超时；请检查 Drive 日志并显式释放诊断实例。')
