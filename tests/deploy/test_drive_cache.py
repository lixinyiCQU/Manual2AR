"""No Drive authorization, downloads or GPU: exercise real artifact boundaries."""
from pathlib import Path
import ast
import base64
import hashlib
import io
import json
import tarfile
import zipfile

import pytest

from deploy.colab.drive_cache import DriveCache, copy_verified, publish_json, unpack_wheels, validate_wheelhouse
from tools.build.gpu_cache import build, ROOT


@pytest.fixture
def local(tmp_path):
    root = tmp_path / 'runtime'
    cloud = root / 'configs'
    cloud.mkdir(parents=True)
    config = json.loads((ROOT / 'configs/inference.example.json').read_text())
    config['api_token'] = 'PRIVATE-TOKEN-MUST-NOT-BE-CACHED'
    publish_json(cloud / 'inference.local.json', config)
    for name in ('deploy/common/requirements.txt','deploy/common/bootstrap.py','deploy/colab/environment.py'):
        path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('fixture '+name)
    data = b'fixture SAM3.1 checkpoint'
    publish_json(root / 'manual2ar_inference/engines/sam31_sources.json', dict(weights=dict(size=len(data), sha256=hashlib.sha256(data).hexdigest())))
    for field, body in [('sam3_checkpoint', data), ('cutie_checkpoint', b'fixture Cutie checkpoint')]:
        path = root / config[field]
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(body)
    return root, tmp_path / 'drive', config


def test_model_restore_validates_hash_and_repairs_corrupt_cache(local):
    root, drive, config = local
    first = DriveCache(root, drive)
    first.save_models()
    expected = {field: (root / config[field]).read_bytes() for field in ('sam3_checkpoint', 'cutie_checkpoint')}
    for field in expected:
        (root / config[field]).unlink()
    restored = DriveCache(root, drive)
    restored.restore_models()
    assert all((root / config[k]).read_bytes() == value for k, value in expected.items())
    key = first._model_specs()[0][0]
    checkpoint = root / config['sam3_checkpoint']
    cached = drive / 'models' / key / checkpoint.name
    cached.write_bytes(b'x' * cached.stat().st_size)
    checkpoint.unlink()
    bad = DriveCache(root, drive)
    bad.restore_models()
    assert not checkpoint.exists() and key in bad.bad
    checkpoint.write_bytes(expected['sam3_checkpoint'])
    bad.save_models()
    assert cached.read_bytes() == expected['sam3_checkpoint']


def test_verified_copy_never_publishes_corrupt_payload(tmp_path):
    src, dst = tmp_path / 'source', tmp_path / 'target'
    src.write_bytes(b'bad');dst.write_bytes(b'known-good')
    with pytest.raises(ValueError):
        copy_verified(src, dst, dict(size=3, sha256='0' * 64))
    assert dst.read_bytes() == b'known-good'
    assert not list(tmp_path.glob('*.part'))


def test_offline_cache_requires_built_wheels_not_just_downloaded_sdists(tmp_path):
    (tmp_path / 'iopath-0.1.10.tar.gz').write_bytes(b'source distribution')
    with pytest.raises(ValueError, match='iopath==0.1.10'):
        validate_wheelhouse(tmp_path, ['iopath==0.1.10'])
    with zipfile.ZipFile(tmp_path / 'iopath-0.1.10-py3-none-any.whl', 'w') as wheel:
        wheel.writestr('iopath-0.1.10.dist-info/METADATA', 'Name: iopath\nVersion: 0.1.10\n')
    validate_wheelhouse(tmp_path, ['iopath==0.1.10'])


def test_cache_key_changes_for_dependencies_not_performance(local):
    root, drive, config = local
    cache = DriveCache(root, drive)
    original = cache.environment_key()[0]
    config['cutie']['mem_every'] = 10
    config['precision'] = 'float32'
    publish_json(cache.config_path, config)
    assert cache.environment_key()[0] == original
    (root / 'deploy/common/requirements.txt').write_text('changed dependency')
    assert cache.environment_key()[0] != original


def test_restore_wheel_archive_and_detect_corruption(local):
    root, drive, _ = local
    cache = DriveCache(root, drive)
    key, _ = cache.environment_key()
    folder = drive / 'environments' / key
    folder.mkdir(parents=True)
    archive = folder / 'wheels.tar'
    with tarfile.open(archive, 'w:') as tar:
        for name, data in [('requirements.lock', b'fixture==1\n'), ('fixture.whl', b'wheel payload')]:
            item = tarfile.TarInfo(name);item.size = len(data)
            tar.addfile(item, io.BytesIO(data))
    publish_json(folder / 'manifest.json', dict(archive=dict(size=archive.stat().st_size, sha256=hashlib.sha256(archive.read_bytes()).hexdigest())))
    wheels = cache.restore_environment()
    assert (wheels / 'fixture.whl').read_bytes() == b'wheel payload'
    archive.write_bytes(b'broken cache')
    assert cache.restore_environment() is None and key in cache.bad


@pytest.mark.parametrize('name,kind', [('../escape.whl', 'file'), ('link.whl', 'symlink')])
def test_wheel_extraction_rejects_paths_and_symlinks(tmp_path, name, kind):
    archive = tmp_path / 'bad.tar'
    with tarfile.open(archive, 'w:') as tar:
        item = tarfile.TarInfo(name)
        if kind == 'symlink':
            item.type = tarfile.SYMTYPE;item.linkname = '/etc/passwd'
        tar.addfile(item)
    with pytest.raises(ValueError):
        unpack_wheels(archive, tmp_path / 'extract')
    assert not (tmp_path / 'escape.whl').exists()


def test_saved_settings_cannot_override_token_or_model(local):
    root, drive, config = local
    publish_json(drive / 'settings.json', dict(api_token='injected token', sam3_checkpoint='/wrong.pt', precision='float32'))
    restored = DriveCache(root, drive).settings(config)
    assert restored['api_token'] == config['api_token']
    assert restored['sam3_checkpoint'] == config['sam3_checkpoint']
    assert restored['precision'] == 'float32'


def test_same_runtime_does_not_recopy_or_reinstall_environment(local, monkeypatch):
    from deploy.colab import drive_cache
    root, drive, config = local
    cache = DriveCache(root, drive)
    key, _ = cache.environment_key()
    python = root / '.gpu-venv/bin/python'
    python.parent.mkdir(parents=True);python.write_bytes(b'fixture interpreter')
    publish_json(root / '.drive-cache-ready.json', dict(environment_key=key))
    publish_json(drive / 'environments' / key / 'manifest.json', dict(packages=['fixture==1']))
    monkeypatch.setattr(cache, '_validate_python', lambda python: None)
    monkeypatch.setattr(cache, 'restore_environment', lambda: pytest.fail('Do not copy the archive in the same runtime'))
    monkeypatch.setattr(cache, '_offline_python', lambda wheels: pytest.fail('Do not reinstall in the same runtime'))
    monkeypatch.setattr(drive_cache, 'run_logged', lambda *args: None)
    assert cache.prepare() == str(python)
    assert any(e.get('status') == 'local environment reused' for e in cache.events)
    settings = (drive / 'settings.json').read_text()
    assert config['api_token'] not in settings and 'api_token' not in settings


def test_derived_notebook_keeps_original_sources_and_parameters(tmp_path):
    from tools.build.gpu_base import build as base_build
    import tempfile
    base_build()
    original = Path(tempfile.gettempdir()) / 'Manual2AR-GPU-base.ipynb'
    before = original.read_bytes()
    source = json.loads(before)
    # Use a user-edited form, not the repository defaults.
    for cell in source['cells']:
        if cell['cell_type'] == 'code' and 'CUTIE_PRECISION =' in ''.join(cell['source']):
            cell['source'] = ''.join(cell['source']).replace('CUTIE_PRECISION = "auto"', 'CUTIE_PRECISION = "float16"').splitlines(True)
    user = tmp_path / 'user.ipynb'
    user.write_text(json.dumps(source))
    destination = tmp_path / 'cached.ipynb'
    build(user, destination)
    assert original.read_bytes() == before
    result = json.loads(destination.read_text())
    all_code = '\n'.join(''.join(c['source']) for c in result['cells'] if c['cell_type'] == 'code')
    assert 'CUTIE_PRECISION = "float16"' in all_code
    assert 'drive.mount' in all_code and 'GPU_PYTHON=drive_cache.prepare' in all_code
    assert 'USE_DRIVE_CACHE = False' in all_code and 'PERSIST_REMOTE_LOGS = False' in all_code
    assert "connection=BASE/'inference.connection.local.json'" in all_code
    assert "processes['tunnel']" in all_code and "processes['service']" in all_code
    for cell in result['cells']:
        if cell['cell_type'] != 'code':
            continue
        assert not cell['outputs'] and cell['execution_count'] is None
        compile(''.join(cell['source']), 'cached-notebook', 'exec')
        for node in ast.parse(''.join(cell['source'])).body:
            if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'SOURCE_ZIP' for t in node.targets):
                with zipfile.ZipFile(io.BytesIO(base64.b64decode(ast.literal_eval(node.value)))) as archive:
                    assert archive.read('deploy/colab/drive_cache.py') == (ROOT / 'deploy/colab/drive_cache.py').read_bytes()
                    assert 'manual2ar_inference/engines/sam31_sources.json' in archive.namelist()
