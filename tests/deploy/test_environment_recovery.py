"""Regressions for the observed Drive restore and logging failures."""
import json
from pathlib import Path
import subprocess
import sys
import threading
import zipfile

from deploy.common.files import private_json
from deploy.colab.environment import redact,run_logged
from deploy.colab.drive_cache import DriveCache


def test_logging_survives_child_truncating_configuration(tmp_path,capsys):
    token='secret-known-before-bootstrap'
    private_json(tmp_path/'configs/inference.local.json',{'api_token':token})
    code="from pathlib import Path;p=Path('configs/inference.local.json');p.write_text('');print('install continued '+"+repr(token)+",flush=True)"
    run_logged([sys.executable,'-c',code],tmp_path,'reproduce config race')
    output=capsys.readouterr().out+(tmp_path/'bootstrap.log').read_text()
    assert 'install continued' in output and token not in output
    assert '[REDACTED]' in output
    assert 'Output withheld' in redact('possibly sensitive',tmp_path)


def test_atomic_config_replacement_never_exposes_empty_json(tmp_path):
    path=tmp_path/'private.json';private_json(path,{'value':0})
    stopped=threading.Event();errors=[]
    def reader():
        while not stopped.is_set():
            try:json.loads(path.read_text())
            except Exception as error:errors.append(error)
    thread=threading.Thread(target=reader);thread.start()
    try:
        for i in range(60):private_json(path,{'value':i})
    finally:stopped.set();thread.join()
    assert not errors and path.stat().st_mode&0o777==0o600
    assert not list(tmp_path.glob('private.json.*'))


def test_offline_restore_installs_pinned_wheel_without_training_dependencies(tmp_path,monkeypatch):
    from deploy.colab import drive_cache
    wheels=tmp_path/'wheels';wheels.mkdir()
    # The inference environment intentionally excludes this unused training dep.
    wheel=wheels/'restore_fixture-1.0-py3-none-any.whl'
    with zipfile.ZipFile(wheel,'w') as z:
        z.writestr('restore_fixture/__init__.py','READY=True\n')
        prefix='restore_fixture-1.0.dist-info/'
        z.writestr(prefix+'METADATA','Metadata-Version: 2.1\nName: restore-fixture\nVersion: 1.0\nRequires-Dist: nonexistent-training-av-dependency>=999\n')
        z.writestr(prefix+'WHEEL','Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\nTag: py3-none-any\n')
        z.writestr(prefix+'RECORD','')
    (wheels/'requirements.lock').write_text('restore-fixture==1.0\n')
    python=tmp_path/'.gpu-venv/bin/python';python.parent.mkdir(parents=True);python.touch()
    target=tmp_path/'installed'
    def execute(args,root,stage):
        if stage=='Install locked dependencies offline':
            subprocess.run([sys.executable,*args[1:],'--target',str(target)],check=True,capture_output=True,text=True)
    monkeypatch.setattr(drive_cache,'run_logged',execute)
    DriveCache(tmp_path)._offline_python(wheels)
    assert (target/'restore_fixture/__init__.py').is_file()
