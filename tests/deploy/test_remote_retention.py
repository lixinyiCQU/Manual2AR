"""Persistence survives abrupt runtime loss without retaining private payloads."""
import base64
import io
import json
from pathlib import Path
import subprocess
import sys
import zipfile

import pytest

from deploy.colab import retention,diagnostics
from tools.build.colab_diagnostics import build,bundle_bytes,ROOT,SOURCES
from tools.deployment.colab import validate_config


def test_remote_snapshot_retains_logs_but_excludes_config_keys_and_images(tmp_path,monkeypatch):
    root=tmp_path/'runtime';root.mkdir();drive=tmp_path/'drive'
    (root/'configs').mkdir();(root/'configs/inference.local.json').write_text(json.dumps({'api_token':'private-token-123'}))
    (root/'service.log').write_text('operation completed\nBearer private-token-123\n')
    (root/'input.png').write_bytes(b'PRIVATE-IMAGE')
    monkeypatch.setattr(retention.subprocess,'run',lambda *a,**kw:subprocess.CompletedProcess(a,0,'T4, 1024 MiB, 15360 MiB, 12 %'))
    result=retention.persist(root,drive)
    assert result['memory']['MemTotal_KiB']>0 and result['boot_id']
    assert 'T4' in result['gpu']
    text=(drive/'logs/service.log').read_text()
    assert 'operation completed' in text and 'private-token-123' not in text
    assert not list(drive.rglob('*.png')) and not (drive/'logs/configs').exists()
    assert len((drive/'observations.jsonl').read_text().splitlines())==1
    assert (drive/'latest.json').stat().st_mode&0o777==0o600


def test_snapshot_is_bounded_and_does_not_copy_private_symlinks(tmp_path,monkeypatch):
    root=tmp_path/'runtime';root.mkdir();drive=tmp_path/'drive'
    (root/'service.log').write_text('old\n'+'z'*280000+'\nlast complete line\n')
    private=root/'private.json';private.write_text('NEVER COPY')
    (root/'gpu_service.log').symlink_to(private)
    monkeypatch.setattr(retention.subprocess,'run',lambda *a,**kw:subprocess.CompletedProcess(a,0,'T4'))
    retention.persist(root,drive)
    assert (drive/'logs/service.log').stat().st_size<=262144
    assert 'last complete line' in (drive/'logs/service.log').read_text()
    assert not (drive/'logs/gpu_service.log').exists()


def test_no_gpu_is_a_recorded_diagnostic_not_a_model_install(tmp_path,monkeypatch):
    def missing(*a,**kw):raise FileNotFoundError('nvidia-smi')
    monkeypatch.setattr(retention.subprocess,'run',missing)
    assert retention.sample(tmp_path)['gpu_error']=='FileNotFoundError'


def test_diagnostic_suite_is_finite_and_cannot_start_model_or_tunnel(tmp_path,monkeypatch):
    calls=[]
    monkeypatch.setattr(diagnostics,'start_recorder',lambda root,logs,minutes:calls.append((logs,minutes)) or str(tmp_path/'drive'))
    value=diagnostics.launch(tmp_path,{'suite':'session_lifecycle','duration_minutes':1,'sample_seconds':5},{'path':'/content/drive/MyDrive/logs'})
    assert value['models_loaded'] is False and value['public_tunnel'] is False
    assert calls[0][1]==1 and calls[0][0]['interval_seconds']==5
    with pytest.raises(ValueError):diagnostics.launch(tmp_path,{'suite':'arbitrary.path'}, {})


def test_diagnostic_package_contains_only_audited_standard_library_sources(tmp_path):
    with zipfile.ZipFile(io.BytesIO(bundle_bytes())) as bundle:
        assert set(bundle.namelist())==set(SOURCES)
        assert not any('manual2ar_inference' in name or name.endswith(('.pt','.png','.local.json')) for name in bundle.namelist())
        bundle.extractall(tmp_path)
    # Import in an isolated process with no project/GPU packages in sys.path.
    subprocess.run([sys.executable,'-I','-c','import sys;sys.path.insert(0,'+repr(str(tmp_path))+');from deploy.colab.diagnostics import SUITES;assert "session_lifecycle" in SUITES'],check=True,capture_output=True)


def test_diagnostic_notebook_compiles_and_uses_same_runtime_package():
    p=build();notebook=json.loads(p.read_text());payload=None
    import ast
    for cell in notebook['cells']:
        if cell['cell_type']!='code':continue
        code=''.join(cell['source']);compile(code,str(p),'exec')
        assert not cell['outputs'] and cell['execution_count'] is None
        for node in ast.parse(code).body:
            if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='PAYLOAD' for t in node.targets):payload=ast.literal_eval(node.value)
    with zipfile.ZipFile(io.BytesIO(base64.b64decode(payload))) as bundle:
        assert bundle.read('deploy/colab/retention.py')==(ROOT/'deploy/colab/retention.py').read_bytes()


@pytest.mark.parametrize('key,value',[
    ('remote_logs',{'enabled':True,'path':'/tmp/escape','interval_seconds':15}),
    ('remote_logs',{'enabled':True,'path':'/content/drive/MyDrive/logs','interval_seconds':0}),
    ('diagnostics',{'suite':'other.path','session_name':'test','duration_minutes':30,'sample_seconds':15}),
    ('diagnostics',{'suite':'session_lifecycle','session_name':'manual2ar-integrated','duration_minutes':30,'sample_seconds':15}),
])
def test_untrusted_diagnostic_configuration_rejected(key,value):
    config=json.loads((ROOT/'configs/colab.example.json').read_text());config[key]=value
    with pytest.raises(ValueError):validate_config(config)


def test_diagnostic_run_task_is_separate_from_business_start():
    tasks=json.loads((ROOT/'Manual2AR.code-workspace').read_text())['tasks']['tasks']
    by_label={t['label']:t for t in tasks}
    assert by_label['Colab: 无模型诊断实验']['args'][-1]=='colab-test-runtime'
    assert by_label['Colab: 释放诊断运行时']['args'][-1]=='colab-release-diagnostic'


@pytest.mark.parametrize('force',[False,True])
def test_recorder_leaves_evidence_after_process_termination(tmp_path,force):
    import time
    with zipfile.ZipFile(io.BytesIO(bundle_bytes())) as archive:archive.extractall(tmp_path/'runtime')
    root=tmp_path/'runtime';destination=tmp_path/'persistent'
    child=subprocess.Popen([sys.executable,'-I','-c',
        'import sys;sys.path.insert(0,'+repr(str(root))+');from deploy.colab.retention import run;run('+repr(str(root))+','+repr(str(destination))+',5,1)'],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    try:
        deadline=time.monotonic()+5
        while not (destination/'latest.json').exists() and time.monotonic()<deadline:
            if child.poll() is not None:pytest.fail(child.stderr.read().decode())
            time.sleep(.02)
        assert (destination/'latest.json').exists()
        if force:child.kill()
        else:child.terminate()
        child.wait(timeout=5)
        assert (destination/'observations.jsonl').is_file()
        if force:assert not (destination/'end.json').exists()
        else:assert json.loads((destination/'end.json').read_text())['reason']=='signal_15'
    finally:
        if child.poll() is None:child.kill();child.wait()
        child.stderr.close()


def test_task_launches_only_diagnostic_alias_and_never_installs_connection(tmp_path,monkeypatch):
    import ast
    from contextlib import nullcontext
    from types import SimpleNamespace
    from tools.deployment import colab_diagnostics as host_module
    config=json.loads((ROOT/'configs/colab.example.json').read_text())
    class CLI:
        def __init__(self):self.owned=None;self.calls=[];self.nonce=None
        def setup(self):pass
        def record(self):return self.owned
        def run(self,args,**kw):
            self.calls.append(args)
            if args[0]=='new':self.owned={'endpoint':'diagnostic-vm'}
        def execute(self,path):
            tree=ast.parse(path.read_text());compile(tree,str(path),'exec')
            for node in ast.walk(tree):
                if isinstance(node,ast.Assign) and any(isinstance(t,ast.Subscript) and isinstance(t.slice,ast.Constant) and t.slice.value=='request_id' for t in node.targets):self.nonce=ast.literal_eval(node.value)
        def download(self,remote,local):
            value={'state':'observing','request_id':self.nonce,'destination':'/content/drive/MyDrive/test'} if remote.endswith('diagnostic-receipt.json') else {'state':'ended'}
            local.write_text(json.dumps(value))
    cli=CLI();job=SimpleNamespace(c=config,cache=tmp_path/'cache',cli=cli,locked=nullcontext,remote=lambda name:'/content/Manual2ARDiagnostics/'+name)
    job.cache.mkdir()
    host=SimpleNamespace(c=config,app={},logs=tmp_path/'logs',clock=lambda:0,sleep=lambda _:None,cli=SimpleNamespace(record=lambda:None))
    received=[]
    monkeypatch.setattr(host_module,'Orchestrator',lambda c,app:received.append(c) or job)
    host_module.experiment(host)
    assert received[0]['session_name']=='manual2ar-diagnostics'
    assert any(c[0]=='new' and c[2]=='manual2ar-diagnostics' for c in cli.calls)
    assert not any('manual2ar-integrated' in c for c in cli.calls)
    assert not list(tmp_path.rglob('inference.connection.local.json'))
