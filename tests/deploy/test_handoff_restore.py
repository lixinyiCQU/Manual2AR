import hashlib
import json
from pathlib import Path
import pytest


from tools import handoff_restore as restore


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding='utf-8')


def configured_root(tmp_path):
    repo = tmp_path / restore.REPOSITORY
    write(repo / 'configs/app.example.json', {
        'backend': {}, 'vlm': {'api_key': 'example-only'}, 'paths': {}, 'gpu': {}, 'modules': {}})
    (tmp_path / 'Manual2AR-Data').mkdir()
    return repo


def frozen_root(tmp_path, monkeypatch):
    frozen = tmp_path / restore.FROZEN
    files = {}
    for i in range(388):
        path = frozen / 'trials' / (str(i) + '.json')
        write(path, {'trial': i})
        files[str(path.relative_to(frozen))] = restore.digest(path)
    write(frozen / 'plan.json', {'schedule': []})
    files['plan.json'] = restore.digest(frozen / 'plan.json')
    write(frozen / 'evidence-manifest.json', {'files': files})
    monkeypatch.setattr(restore, 'FROZEN_MANIFEST_SHA256', restore.digest(frozen / 'evidence-manifest.json'))
    monkeypatch.setattr(restore, 'FROZEN_PLAN_SHA256', restore.digest(frozen / 'plan.json'))
    write(tmp_path / 'payload.txt', 'saved development')
    payload = tmp_path / 'payload.txt'
    write(tmp_path / 'manifests/files.json', {'schema_version': 'manual2ar-handoff-files-v1',
        'files': {'payload.txt': {'size': payload.stat().st_size, 'sha256': restore.digest(payload)}}})
    return frozen


def test_configure_is_relative_private_and_refuses_overwrite(tmp_path):
    repo = configured_root(tmp_path)
    original = repo / 'configs/app.example.json'
    before = original.read_bytes()
    target = restore.configure(tmp_path)
    config = json.loads(target.read_bytes())
    assert config['vlm']['api_key'] == ''
    assert config['backend'] == {'host': '127.0.0.1', 'port': 8011, 'public_url': 'http://127.0.0.1:8011'}
    assert config['paths']['runtime'] == '../../Manual2AR-Data/runs/u7-pipeline'
    assert target.stat().st_mode & 0o777 == 0o600
    assert original.read_bytes() == before
    with pytest.raises(ValueError, match='exists'):
        restore.configure(tmp_path)
    restore.configure(tmp_path, force=True)
    assert not (repo / 'configs/inference.connection.local.json').exists()


def test_verify_preserves_frozen_files_and_detects_changes(tmp_path, monkeypatch):
    frozen = frozen_root(tmp_path, monkeypatch)
    assert restore.verify(tmp_path)['frozen_files'] == 389
    (frozen / 'trials/7.json').write_bytes(b'changed')
    with pytest.raises(ValueError, match='Frozen evaluation file'):
        restore.verify(tmp_path)


def test_verify_detects_handoff_size_or_hash_change(tmp_path, monkeypatch):
    frozen_root(tmp_path, monkeypatch)
    payload = tmp_path / 'payload.txt'
    payload.write_bytes(b'x' * payload.stat().st_size)
    with pytest.raises(ValueError, match='Handoff file missing or changed'):
        restore.verify(tmp_path)


def test_verify_rejects_traversal_and_symbolic_links(tmp_path, monkeypatch):
    frozen_root(tmp_path, monkeypatch)
    manifest = tmp_path / 'manifests/files.json'
    expected = {'size': 0, 'sha256': hashlib.sha256(b'').hexdigest()}
    write(manifest, {'schema_version': 'manual2ar-handoff-files-v1', 'files': {'../escape': expected}})
    with pytest.raises(ValueError, match='Invalid relative path'):
        restore.verify(tmp_path)
    external = tmp_path.parent / (tmp_path.name + '-outside')
    external.write_bytes(b'')
    (tmp_path / 'linked').symlink_to(external)
    write(manifest, {'schema_version': 'manual2ar-handoff-files-v1', 'files': {'linked': expected}})
    with pytest.raises(ValueError, match='Symbolic links'):
        restore.verify(tmp_path)


def test_configure_force_never_follows_symlink(tmp_path):
    repo = configured_root(tmp_path)
    outside = tmp_path / 'private-original.json'
    outside.write_text('keep me')
    (repo / 'configs/app.local.json').symlink_to(outside)
    with pytest.raises(ValueError, match='Symbolic links'):
        restore.configure(tmp_path, force=True)
    assert outside.read_text() == 'keep me'


def test_launcher_preserves_original_build_and_uses_product_exporter(tmp_path, monkeypatch):
    repo = configured_root(tmp_path)
    python = repo/'.venv/bin/python'; python.parent.mkdir(parents=True); python.touch()
    build = tmp_path/'Manual2AR-Data/builds/u7-pipeline/Manual2AR-Windows'
    write(build/'backend.launch.json', {'worktree': '/original-machine'})
    write(build/'delivery.json', {'original': True})
    original = restore.digest(build/'backend.launch.json')
    calls = []
    def export(args, **kwargs):
        calls.append((args, kwargs))
        write(Path(args[-1])/'backend.launch.json', {'worktree': str(repo)})
    monkeypatch.setattr(restore.subprocess, 'run', export)
    target = restore.launcher(tmp_path)
    assert restore.digest(build/'backend.launch.json') == original
    assert restore.digest(target/'backend.launch.original.json') == original
    assert json.loads((target/'migration.json').read_bytes())['rebuilt_frontend'] is False
    assert 'verify_build(ROOT,target)' in calls[0][0][3]
    assert 'export_backend_launcher' in calls[0][0][3]
    with pytest.raises(ValueError, match='exists'):
        restore.launcher(tmp_path)
