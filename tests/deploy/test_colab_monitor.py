"""Observe loss/recovery without GPU allocation, kernel keepalives or credentials."""
import json
from pathlib import Path
import subprocess

import httpx
import pytest

from tools.deployment.colab import ROOT,Orchestrator,validate_config
from tools.deployment.colab_monitor import observe,watch,diagnose


def monitored(tmp_path,checker=None):
    from deploy.colab.worker import private_json
    config=json.loads((ROOT/'configs/colab.example.json').read_text())
    class CLI:
        def __init__(self):
            self.current={'accelerator':'T4','endpoint':'owned-runtime'}
            self.calls=[];self.missing=False;self.failure=None
        def record(self):return self.current
        def run(self,args,**kw):
            self.calls.append(tuple(args))
            if self.failure:raise self.failure
            if self.missing:self.current=None
        def execute(self,path,timeout=30):
            self.calls.append(('exec',))
            self.script=path.read_text()
        def download(self,remote,local):
            self.calls.append(('download',Path(remote).name))
            assert remote.endswith('/diagnosis.json')
            local.write_text(json.dumps({'processes':{'service':True,'tunnel':False},'local_service':{'available':True}}))
    cli=CLI()
    app={'paths':{'cache':str(tmp_path/'cache'),'runtime':str(tmp_path/'runs')},'gpu':{'connection_file':str(tmp_path/'connection.json')}}
    host=Orchestrator(config,app,cli,checker or (lambda _: {'available':True,'models_loaded':True}))
    private_json(host.connection,{'url':'https://private.example','api_token':'never-include-this-token','protocol':'unused-by-fake'})
    import hashlib
    private_json(host.logs/'installation.json',{'runtime_id':'owned-runtime','connection_sha256':hashlib.sha256(host.connection.read_bytes()).hexdigest()})
    return host,cli


def test_ready_observation_does_not_execute_notebook_or_log_credentials(tmp_path):
    host,cli=monitored(tmp_path)
    result=observe(host)
    assert result['state']=='ready' and result['models_loaded']
    assert cli.calls==[('status','-s',host.c['session_name'])]
    for p in [host.logs/'monitor-events.jsonl',host.logs/'monitor-status.json']:
        text=p.read_text()
        assert 'never-include' not in text and 'private.example' not in text
        assert 'at' in text
        assert p.stat().st_mode&0o777==0o600


def test_runtime_disappears_only_after_successful_control_plane_query(tmp_path):
    host,cli=monitored(tmp_path);cli.missing=True
    result=observe(host)
    assert result['state']=='runtime_gone' and result['runtime_present'] is False
    assert result['runtime_id']
    assert all(c[0]=='status' for c in cli.calls)


def test_api_timeout_is_not_misreported_as_runtime_recycling(tmp_path):
    host,cli=monitored(tmp_path);cli.failure=subprocess.TimeoutExpired('status',30)
    result=observe(host)
    assert result['state']=='check_failed' and result['runtime_present'] is None
    assert cli.record()


def test_tls_failure_keeps_runtime_and_connection_and_is_not_recycling(tmp_path):
    def fails(_):raise httpx.ConnectError('SSL EOF')
    host,cli=monitored(tmp_path,fails);old=host.connection.read_bytes()
    result=observe(host)
    assert result['state']=='public_unreachable' and result['network_hint']=='tls'
    assert result['runtime_present'] is True and cli.record()
    assert old==host.connection.read_bytes()


def test_public_auth_failure_is_distinct_from_network_failure(tmp_path):
    def unauthorized(_):
        r=httpx.Response(401,request=httpx.Request('GET','https://private.example/health'))
        r.raise_for_status()
    host,_=monitored(tmp_path,unauthorized)
    assert observe(host)['state']=='public_auth_error'


def test_connection_from_another_runtime_is_never_probed(tmp_path):
    host,cli=monitored(tmp_path,lambda _:pytest.fail('stale endpoint probed'))
    cli.current['endpoint']='new-runtime'
    assert observe(host)['state']=='connection_unverified'


def test_legacy_receipt_without_runtime_identity_requires_reverification(tmp_path):
    host,_=monitored(tmp_path,lambda _:pytest.fail('unbound endpoint probed'))
    path=host.logs/'installation.json';receipt=json.loads(path.read_text());receipt.pop('runtime_id')
    path.write_text(json.dumps(receipt))
    assert observe(host)['state']=='connection_unverified'


def test_no_local_record_never_allocates_or_triggers_login(tmp_path):
    host,cli=monitored(tmp_path);cli.current=None
    assert observe(host)['state']=='not_tracked'
    assert cli.calls==[]


def test_watch_interval_and_history_without_lifecycle_mutations(tmp_path):
    host,cli=monitored(tmp_path);waits=[];host.sleep=waits.append
    watch(host,max_samples=3)
    assert waits==[30,30]
    assert len((host.logs/'monitor-events.jsonl').read_text().splitlines())==3
    assert all(c[0]=='status' for c in cli.calls)
    with (host.cache/'operation.lock').open('a') as stream:
        import fcntl
        fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)


def test_monitor_does_not_block_explicit_release_or_stop_lock(tmp_path):
    host,_=monitored(tmp_path)
    with host.locked():watch(host,max_samples=1)


def test_second_monitor_is_rejected_without_requests(tmp_path):
    import fcntl
    host,cli=monitored(tmp_path)
    with (host.cache/'monitor.lock').open('a') as stream:
        fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
        with pytest.raises(RuntimeError,match='监控'):watch(host,max_samples=1)
    assert not cli.calls


@pytest.mark.parametrize('interval',[0,5,301,True])
def test_monitor_rejects_excessive_polling_and_invalid_config(interval):
    config=json.loads((ROOT/'configs/colab.example.json').read_text());config['monitor_seconds']=interval
    with pytest.raises(ValueError):validate_config(config)


def test_diagnose_is_user_requested_one_shot_local_health_and_process_check(tmp_path):
    host,cli=monitored(tmp_path);saved=[]
    host.collect_logs=lambda:saved.append(True)
    result=diagnose(host)
    assert result['local_service']['available'] and not result['processes']['tunnel']
    assert saved==[True] and sum(c[0]=='exec' for c in cli.calls)==1
    assert 'nvidia-smi' in cli.script and '/health' in cli.script
    assert 'while ' not in cli.script and 'stop(' not in cli.script
    assert (host.logs/'diagnosis.json').is_file()


def test_workspace_default_start_keeps_monitor_visible():
    tasks=json.loads((ROOT/'Manual2AR.code-workspace').read_text())['tasks']['tasks']
    by_label={t['label']:t for t in tasks}
    assert by_label['Colab: 启动 GPU']['args'][-1]=='colab-start-watch'
    assert by_label['Colab: 持续监控']['args'][-1]=='colab-watch'
    assert by_label['Colab: 诊断连接与进程']['args'][-1]=='colab-diagnose'


def test_watch_archives_fault_once_and_redacts_without_executing_kernel(tmp_path):
    def fails(_):raise httpx.ConnectError('SSL EOF')
    host,cli=monitored(tmp_path,fails);host.sleep=lambda _:None
    original=cli.run
    def run(args,**kw):
        original(args,**kw)
        if args[0]=='download':Path(args[-1]).write_text('Bearer never-include-this-token service unavailable')
    cli.run=run
    watch(host,max_samples=3)
    captures=list((host.logs/'monitor-captures').iterdir())
    assert len(captures)==1
    assert len([c for c in cli.calls if c[0]=='download'])==3
    assert all(c[0] in ('status','download') for c in cli.calls)
    assert 'never-include' not in (captures[0]/'service.log').read_text()
    assert (captures[0]/'observation.json').is_file()
