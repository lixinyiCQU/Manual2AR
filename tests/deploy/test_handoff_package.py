"""Preserve dirty development and history without copying operator credentials."""
import json
from pathlib import Path
import pytest
from tools.build import handoff


def test_pack_is_independent_and_preserves_original_dirty_state(tmp_path, monkeypatch):
    source = tmp_path/'original'; source.mkdir()
    handoff.git(source, 'init', '-q', '-b', 'lixin/u7-end-to-end')
    (source/'.gitignore').write_text('configs/*.local.json\n.venv/\nassets/generated/\n')
    (source/'main.py').write_text('old\n')
    handoff.git(source, 'add', '.')
    handoff.git(source, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@local.invalid', 'commit', '-qm', 'original')
    before_head = handoff.git(source, 'rev-parse', 'HEAD')
    handoff.git(source, 'branch', 'main')
    handoff.git(source, 'tag', 'fixture-v1')
    (source/'main.py').write_text('current\n'); (source/'untracked.py').write_text('new work\n')
    for name in ['docs/HANDOFF.md', 'README_AGENT.md', 'AGENTS.md', 'tools/handoff_restore.py', 'assets/generated/mesh.json']:
        path = source/name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text('preserve\n')
    (source/'configs').mkdir()
    (source/'configs/app.local.json').write_text(json.dumps({'api_key':'private-fixture-do-not-copy'}))
    data = tmp_path/'data'; data.mkdir(); (data/'evidence.json').write_text('raw failure retained\n')
    reference = tmp_path/'references'; reference.mkdir(); (reference/'blueprint.md').write_text('research')
    status = handoff.git(source, 'status', '--porcelain=v1')
    monkeypatch.setattr(handoff, 'ROOT', source)
    monkeypatch.setattr(handoff, 'verify', lambda root:dict(files=1, frozen_files=389))
    output = tmp_path/'delivery'; handoff.create(output, data, reference)
    repo = output/'workspace/Manual2AR-U7-Pipeline'
    assert (repo/'.git').is_dir() and not (repo/'configs/app.local.json').exists()
    assert (repo/'untracked.py').read_text() == 'new work\n'
    assert (repo/'assets/generated/mesh.json').is_file()
    assert handoff.git(repo, 'status', '--porcelain=v1') == ''
    assert handoff.git(repo, 'rev-parse', 'HEAD^') == before_head
    assert handoff.git(repo, 'rev-parse', 'refs/heads/main') == before_head
    assert handoff.git(repo, 'rev-parse', 'refs/tags/fixture-v1') == before_head
    assert handoff.git(source, 'rev-parse', 'HEAD') == before_head
    assert handoff.git(source, 'status', '--porcelain=v1') == status
    assert (output/'history/all-history.bundle').is_file()
    assert 'workspace/Manual2AR-U7-Pipeline/README_AGENT.md' in (output/'AGENT_HANDOFF.md').read_text()
    assert (output/'Manual2AR-Data/evidence.json').read_bytes() == (data/'evidence.json').read_bytes()
    manifest = json.loads((output/'manifests/files.json').read_bytes())
    assert 'workspace/Manual2AR-U7-Pipeline/untracked.py' in manifest['files']
    assert 'workspace/Manual2AR-U7-Pipeline/configs/app.local.json' not in manifest['files']


def test_history_scan_detects_a_deleted_known_secret(tmp_path):
    handoff.git(tmp_path, 'init', '-q')
    token = b'known-realistic-credential-123456789'; path = tmp_path/'old.txt'; path.write_bytes(token)
    handoff.git(tmp_path, 'add', '.')
    handoff.git(tmp_path, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@local.invalid', 'commit', '-qm', 'old')
    path.write_text('removed from current source')
    with pytest.raises(ValueError, match='Git history'):
        handoff.history_check(tmp_path, {token})


def test_only_machine_credentials_are_excluded_not_frozen_run_locks():
    assert handoff.exclusion(Path('cache/integrated/colab/sessions.json'), 'data')
    assert handoff.exclusion(Path('archives/workspace-organization-20261103/private-configs/app.local.json'), 'data')
    assert handoff.exclusion(Path('cache/integrated/colab/cli-venv/bin/python'), 'data')
    assert not handoff.exclusion(Path('runs/baseline/transfer-20261111-v1/run.lock'), 'data')
    assert handoff.exclusion(Path('cache/dev/python-venv/bin/python'), 'data')
    assert not handoff.exclusion(Path('cache/u7-pipeline/wiki/index.json'), 'data')
