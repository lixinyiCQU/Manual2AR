"""Exercise deployment boundaries without Google credentials, external GPUs or uploads."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile

import httpx
import pytest
from deploy.colab import worker
from tools.deployment import colab


def settings():return json.loads((colab.ROOT/'configs/colab.example.json').read_text())
def connection():return {'url':'https://worker.example','api_token':'test-only-token-at-least-24-chars','protocol':colab.PROTOCOL}
def health():return {'available':True,'protocol':colab.PROTOCOL,'models_loaded':True}


@pytest.mark.parametrize('change',[
    {'gpu':'bad-typo'}, {'remote_root':'/content'}, {'remote_root':'/content/drive'},
    {'remote_root':'/content/../other'}, {'public_url':'https://user:password@example.com'},
    {'public_url':'http://public.example'}, {'cli_version':'latest'}, {'api_key':'must-not-upload'}])
def test_rejects_unsafe_or_unexpected_config(change):
    c=settings();c.update(change)
    with pytest.raises(ValueError):colab.validate_config(c)


def test_extra_nested_secrets_cannot_be_uploaded():
    c=settings();c['inference']['api_key']='private'
    with pytest.raises(ValueError):colab.validate_config(c)


def test_health_failure_keeps_original_connection_bytes_and_permissions(tmp_path):
    old=tmp_path/'current.local.json';old.write_bytes(b'previous');old.chmod(0o600)
    candidate=tmp_path/'candidate';candidate.write_text(json.dumps(connection()))
    def failed(value):raise RuntimeError('offline')
    with pytest.raises(RuntimeError):colab.install_connection(candidate,old,failed)
    assert old.read_bytes()==b'previous' and old.stat().st_mode&0o777==0o600
    colab.install_connection(candidate,old,lambda _:health())
    assert json.loads(old.read_text())==connection() and old.stat().st_mode&0o777==0o600


@pytest.mark.parametrize('changes',[{'protocol':'old'},{'api_token':'short'},{'url':'https://x.example/path'},{'url':'https://x.example/?secret=x'}])
def test_invalid_connection_never_reaches_health_or_replaces_file(tmp_path,changes):
    value=connection();value.update(changes);p=tmp_path/'candidate';p.write_text(json.dumps(value));target=tmp_path/'current';target.write_text('old')
    with pytest.raises(ValueError):colab.install_connection(p,target,lambda _:pytest.fail('invalid credentials reached HTTP'))
    assert target.read_text()=='old'


def test_real_http_health_adapter_does_not_follow_redirects(monkeypatch):
    actual=httpx.Client;requests=[]
    def transport(request):
        requests.append(request)
        assert request.headers['authorization']=='Bearer '+connection()['api_token']
        return httpx.Response(302,headers={'location':'https://another.example/steal'})
    monkeypatch.setattr(colab.httpx,'Client',lambda **kw:actual(transport=httpx.MockTransport(transport),**kw))
    with pytest.raises(httpx.HTTPStatusError):colab.check_connection(connection())
    assert len(requests)==1


def test_secret_and_oauth_query_redaction():
    value=colab.redact('Bearer abc123 https://login.example/a?state=private "api_token": "supersecret"', ['extra-private'])
    assert 'abc123' not in value and 'state=private' not in value and 'supersecret' not in value


class FakeCLI:
    def __init__(self):self.calls=[];self.owned=None;self.options=None;self.fail_health=False;self.failed_worker=False;self.steps=0;self.stop_id=None
    def setup(self):self.calls.append(('setup',))
    def record(self):return self.owned
    def run(self,args,**kw):
        self.calls.append(tuple(args))
        if args[0]=='new':self.owned={'accelerator':'T4'}
        if args[0]=='stop':self.owned=None
    def execute(self,path,timeout=60):
        text=path.read_text();self.calls.append(('exec',))
        # The driver transmits settings in generated Python, without credentials.
        if 'request_id=' in text:
            import ast
            node=next(n for n in ast.parse(text).body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='request_id' for t in n.targets))
            self.stop_id=ast.literal_eval(node.value)
        if 'options=' in text:
            import ast
            node=next(n for n in ast.parse(text).body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='options' for t in n.targets))
            self.options=ast.literal_eval(node.value)
            assert 'api_key' not in text
    def download(self,remote,local):
        self.calls.append(('download',remote));name=Path(remote).name
        if name=='stop-receipt.json':value={'request_id':self.stop_id,'ok':True}
        elif name=='dispatch.json':value={'ok':True,'dispatch_id':self.options['dispatch_id']}
        elif name=='status.json':
            self.steps+=1
            value={'state':'failed' if self.failed_worker else 'ready','stage':'loading_models',
                **{k:self.options[k] for k in ['bundle_sha256','options_sha256']}}
        else:value=connection()
        local.write_text(json.dumps(value))


def host(tmp_path,fake=None,checker=None):
    app={'paths':{'cache':str(tmp_path/'cache'),'runtime':str(tmp_path/'runs')},'gpu':{'connection_file':str(tmp_path/'connection.local.json')}}
    fake=fake or FakeCLI()
    return colab.Orchestrator(settings(),app,fake,checker or (lambda _:health())),fake


def test_first_start_and_second_start_reuse_session_and_do_not_upload_private_files(tmp_path):
    h,cli=host(tmp_path);h.start();h.start()
    assert sum(c[0]=='new' for c in cli.calls)==1
    assert json.loads(h.connection.read_text())==connection()
    assert all('config.local' not in arg and 'app.local' not in arg for call in cli.calls for arg in call)
    assert 'api_token' not in (h.logs/'status.json').read_text()
    uploads=[c for c in cli.calls if c[0]=='upload'];assert len(uploads)==2
    assert cli.options['inference']==settings()['inference']


def test_bootstrap_failure_does_not_remove_previous_connection(tmp_path):
    h,cli=host(tmp_path);h.connection.write_text('previous connection');cli.failed_worker=True
    with pytest.raises(RuntimeError,match='loading_models'):h.start()
    assert h.connection.read_text()=='previous connection'
    assert not any(call[0]=='stop' for call in cli.calls)
    assert (h.logs/'remote-status.json').is_file()
    assert any(call[0]=='download' and call[1].endswith('/launcher.log') for call in cli.calls)


def test_log_collection_reports_missing_remote_logs(tmp_path):
    h,cli=host(tmp_path);cli.owned={'accelerator':'T4'}
    def missing(*args):raise RuntimeError('runtime lost')
    cli.download=missing
    with pytest.raises(RuntimeError,match='未能获取任何远端日志'):h.collect_logs()


def test_worker_retains_redacted_environment_failure_before_runtime_recycling(tmp_path,monkeypatch,capsys):
    from deploy.colab.drive_cache import DriveCache
    import shutil
    config=json.loads((colab.ROOT/'configs/inference.example.json').read_text())
    config['api_token']='private-token-never-in-diagnostics'
    worker.private_json(tmp_path/'configs/inference.local.json',config)
    options={k:settings()[k] for k in ['inference','drive_cache','public_url']}
    options.update(bundle_sha256='source',options_sha256='settings')
    worker.private_json(tmp_path/'launch-options.json',options)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(shutil,'which',lambda _: '/usr/bin/nvidia-smi')
    def failure(_):raise RuntimeError('dependency failed '+config['api_token'])
    monkeypatch.setattr(DriveCache,'environment_key',failure)
    with pytest.raises(RuntimeError):worker.run(tmp_path)
    state=json.loads((tmp_path/'status.json').read_text())
    assert state['stage']=='preparing_environment' and state['state']=='failed'
    assert 'dependency failed' in state['error_message']
    assert config['api_token'] not in json.dumps(state)+capsys.readouterr().out


def test_different_gpu_does_not_allocate_or_delete_another_session(tmp_path):
    h,cli=host(tmp_path);cli.owned={'accelerator':'L4'}
    with pytest.raises(RuntimeError,match='GPU'):h.start()
    assert not any(c[0] in ('new','stop') for c in cli.calls)


def test_release_only_operates_on_named_project_session(tmp_path):
    h,cli=host(tmp_path);cli.owned={'accelerator':'T4'};h.release()
    assert cli.calls==[('sessions',),('stop','-s','manual2ar-integrated'),('sessions',)]
    h.release();assert len(cli.calls)==3


def test_release_prunes_recycled_vm_without_stopping_other_runtimes(tmp_path):
    h,cli=host(tmp_path);cli.owned={'accelerator':'T4'}
    def run(args,**kw):
        cli.calls.append(tuple(args))
        assert args==['sessions']
        cli.owned=None
    cli.run=run;h.release()
    assert json.loads((h.logs/'status.json').read_text())['state']=='released'


@pytest.mark.parametrize('disappears',[True,False])
def test_release_verifies_server_after_failed_unassign(tmp_path,disappears):
    h,cli=host(tmp_path);cli.owned={'accelerator':'T4'}
    checks=0
    def run(args,**kw):
        nonlocal checks
        cli.calls.append(tuple(args))
        if args[0]=='stop':raise RuntimeError('unassign failed')
        checks+=1
        if checks==2 and disappears:cli.owned=None
    cli.run=run
    if disappears:
        h.release()
        assert json.loads((h.logs/'status.json').read_text())['state']=='released'
    else:
        with pytest.raises(RuntimeError,match='unassign failed'):h.release()
        assert cli.record()
    assert sum(call[0]=='stop' for call in cli.calls)==1


def test_concurrent_start_is_rejected_before_cli_or_upload(tmp_path):
    h,cli=host(tmp_path)
    with h.locked():
        with pytest.raises(RuntimeError,match='进行中'):h.start()
    assert not cli.calls


def test_cli_entrypoint_uses_pinned_installed_module_and_isolated_session_store(tmp_path):
    c=colab.CLI(settings(),tmp_path,lambda _:None);c.python.parent.mkdir(parents=True);c.python.touch()
    args=c.args(['status','-s','manual2ar-integrated'])
    assert args[args.index('-m')+1]=='colab_cli.cli'
    assert args[args.index('--config')+1]==str(tmp_path/'sessions.json')


@pytest.mark.parametrize('command,output,message',[
    (['new'],'ColabRequestError: Service Unavailable','无需重新登录'),
    (['exec'],"Session appears to be lost (404/401)",'连接已失效'),
])
def test_cli_distinguishes_capacity_and_lost_runtime_from_login(tmp_path,monkeypatch,command,output,message):
    c=colab.CLI(settings(),tmp_path,lambda _:None)
    c.python.parent.mkdir(parents=True);c.python.touch()
    monkeypatch.setattr(subprocess,'run',lambda *a,**kw:subprocess.CompletedProcess(a,1,output))
    with pytest.raises(RuntimeError,match=message):c.run(command)


def test_worker_cannot_kill_a_recycled_or_unowned_pid(tmp_path):
    child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'],start_new_session=True)
    try:
        identity=worker.process_identity(child.pid);wrong={**identity,'start':'wrong-generation'}
        assert not worker.stop_owned(wrong) and child.poll() is None
        assert worker.stop_owned(identity)
        child.wait(timeout=5)
    finally:
        if child.poll() is None:child.kill();child.wait()


def test_worker_reuses_only_identical_live_service_and_tunnel(tmp_path,monkeypatch):
    options={'bundle_sha256':'a','options_sha256':'b','public_url':''}
    worker.private_json(tmp_path/'status.json',{'state':'ready',**options})
    worker.private_json(tmp_path/'worker-processes.local.json',{'service':{'pid':1},'tunnel':{'pid':2}})
    monkeypatch.setattr(worker,'alive',lambda x:bool(x));monkeypatch.setattr(worker,'api',lambda *args:health())
    monkeypatch.setattr(worker,'spawn',lambda *args:pytest.fail('reused service restarted'))
    assert worker.launch(tmp_path,options)=='reused'


def test_different_bundle_cannot_replace_inflight_installation(tmp_path,monkeypatch):
    worker.private_json(tmp_path/'status.json',{'state':'starting','bundle_sha256':'old','options_sha256':'old'})
    worker.private_json(tmp_path/'worker-processes.local.json',{'launcher':{'pid':1}})
    monkeypatch.setattr(worker,'alive',lambda x:bool(x))
    with pytest.raises(RuntimeError,match='different deployment'):worker.launch(tmp_path,{'bundle_sha256':'new','options_sha256':'new'})


def test_dispatch_checks_source_hashes_before_extracting_or_running(tmp_path):
    root=tmp_path/'worker';archive=tmp_path/'source.zip'
    with zipfile.ZipFile(archive,'w') as z:
        z.writestr('bundle.manifest.json',json.dumps({'../escape.py':{'sha256':'invalid'}}));z.writestr('../escape.py','bad')
    options={'bundle_sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'options_sha256':'options'}
    code=colab.dispatch_script(str(root),str(archive),options)
    result=subprocess.run([sys.executable,'-B','-c',code],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    assert json.loads((root/'dispatch.json').read_text())['ok'] is False
    assert not (tmp_path/'escape.py').exists()


def test_workspace_tasks_are_file_configured_and_run_inside_project():
    workspace=json.loads((colab.ROOT/'Manual2AR.code-workspace').read_text())
    tasks=workspace['tasks']['tasks']
    assert {t['args'][-1] for t in tasks}>={'colab-start','colab-status','colab-release','colab-login'}
    assert all(t['type']=='process' and t['command']=='bash' and t['options']['cwd']=='${workspaceFolder:Manual2AR}' for t in tasks)


def test_stale_dispatch_receipt_cannot_install_connection(tmp_path):
    h,cli=host(tmp_path);h.connection.write_text('old');original=cli.download
    def stale(remote,local):
        original(remote,local)
        if remote.endswith('/dispatch.json'):local.write_text(json.dumps({'ok':True,'dispatch_id':'old-request'}))
    cli.download=stale
    with pytest.raises(RuntimeError,match='本次请求'):h.start()
    assert h.connection.read_text()=='old'


def test_stop_service_requires_matching_remote_receipt(tmp_path):
    h,cli=host(tmp_path);cli.owned={'accelerator':'T4'};h.stop_service()
    assert not any(call[0]=='stop' for call in cli.calls)
    assert json.loads((h.logs/'status.json').read_text())['state']=='stopped'
    original=cli.download
    def stale(remote,local):
        original(remote,local)
        if remote.endswith('/stop-receipt.json'):local.write_text(json.dumps({'ok':True,'request_id':'old'}))
    cli.download=stale
    with pytest.raises(RuntimeError,match='停止请求'):h.stop_service()


def test_new_https_connection_retries_transient_errors_before_install(tmp_path):
    attempts=[]
    def check(value):
        attempts.append(value)
        if len(attempts)<3:raise httpx.ConnectError('DNS is propagating')
        return health()
    h,cli=host(tmp_path,checker=check);h.sleep=lambda _:None;h.start()
    assert len(attempts)==3 and json.loads(h.connection.read_text())==connection()
