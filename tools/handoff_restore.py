#!/usr/bin/env python3
"""Verify a handoff, or create this machine's private configuration. Standard library only."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tempfile


REPOSITORY = 'workspace/Manual2AR-U7-Pipeline'
FROZEN = 'Manual2AR-Data/runs/baseline/transfer-20261111-v1'
FROZEN_MANIFEST_SHA256 = 'e11f726dfc2a9c059ea6fe6efd19739a4dddab12fc861b9c090b90d7938390d3'
FROZEN_PLAN_SHA256 = '103aa4d9941b08e3ff13f3505d1fab25e9e255404ebd085d0437d0c0a5b97136'


def checked(root, relative):
    """Only canonical relative paths, with no symbolic link at any component."""
    if not isinstance(relative, str) or not relative or '\\' in relative or '\0' in relative:
        raise ValueError('Invalid relative path in handoff')
    name = PurePosixPath(relative)
    if name.is_absolute() or '..' in name.parts or ':' in relative or str(name) != relative or relative == '.':
        raise ValueError('Invalid relative path in handoff')
    path = root
    for part in name.parts:
        path = path / part
        if path.is_symlink():
            raise ValueError('Symbolic links are not accepted in handoff inputs')
    return path


def root_path(value):
    root = Path(value).absolute()
    if root.is_symlink() or not root.is_dir():
        raise ValueError('Handoff root must be an existing real directory')
    return root.resolve()


def digest(path):
    sha = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            sha.update(chunk)
    return sha.hexdigest()


def verify(value):
    root = root_path(value)
    manifest = json.loads(checked(root, 'manifests/files.json').read_bytes())
    if manifest.get('schema_version') != 'manual2ar-handoff-files-v1' or not isinstance(manifest.get('files'), dict):
        raise ValueError('Unsupported handoff manifest')
    total = 0
    for relative, expected in manifest['files'].items():
        if not isinstance(expected, dict) or type(expected.get('size')) is not int or expected['size'] < 0:
            raise ValueError('Invalid file size in handoff manifest')
        if not isinstance(expected.get('sha256'), str) or not re.fullmatch('[0-9a-f]{64}', expected['sha256']):
            raise ValueError('Invalid fingerprint in handoff manifest')
        path = checked(root, relative)
        if not path.is_file() or path.stat().st_size != expected['size'] or digest(path) != expected['sha256']:
            raise ValueError('Handoff file missing or changed: ' + relative)
        total += expected['size']
    frozen = checked(root, FROZEN)
    original_manifest = checked(frozen, 'evidence-manifest.json')
    plan = checked(frozen, 'plan.json')
    if digest(original_manifest) != FROZEN_MANIFEST_SHA256 or digest(plan) != FROZEN_PLAN_SHA256:
        raise ValueError('Frozen evaluation manifest or plan fingerprint changed')
    files = json.loads(original_manifest.read_bytes()).get('files')
    if not isinstance(files, dict) or len(files) != 389:
        raise ValueError('Frozen evaluation must contain 389 registered files')
    for relative, expected in files.items():
        path = checked(frozen, relative)
        if not path.is_file() or digest(path) != expected:
            raise ValueError('Frozen evaluation file missing or changed: ' + relative)
    return dict(files=len(manifest['files']), bytes=total, frozen_files=len(files))


def configure(value, force=False):
    root = root_path(value)
    repo = checked(root, REPOSITORY)
    template = checked(repo, 'configs/app.example.json')
    target = checked(repo, 'configs/app.local.json')
    data = checked(root, 'Manual2AR-Data')
    if not data.is_dir():
        raise ValueError('Manual2AR-Data directory is missing')
    if target.exists() and not force:
        raise ValueError('Local configuration exists; use --force only to replace this configuration')
    config = json.loads(template.read_bytes())
    config['backend'].update(host='127.0.0.1', port=8011, public_url='http://127.0.0.1:8011')
    config['vlm']['api_key'] = ''
    for key, relative in {
        'wiki_archive': 'sources/bambu-wiki/runs/20261024T145623Z_e2655a/archive.json',
        'runtime': 'runs/u7-pipeline', 'builds': 'builds/u7-pipeline', 'cache': 'cache/u7-pipeline'
    }.items():
        config['paths'][key] = Path(os.path.relpath(data / relative, repo)).as_posix()
    config['paths'].update(resources='resources', static_images='resources/samples', renderer_python='.venv/bin/python')
    config['gpu']['connection_file'] = 'configs/inference.connection.local.json'
    descriptor, temporary = tempfile.mkstemp(dir=target.parent, prefix='.app.local.', suffix='.tmp')
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            json.dump(config, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
        os.replace(temporary, target)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return target


def launcher(value):
    root = root_path(value)
    repo = checked(root, REPOSITORY)
    source = checked(root, 'Manual2AR-Data/builds/u7-pipeline/Manual2AR-Windows')
    target = checked(root, 'Launch/Manual2AR-Windows')
    # A freshly created venv normally links its interpreter to the host Python.
    python = repo/'.venv/bin/python'
    if not python.is_file():raise ValueError('Run bash run.sh setup in the source repository first')
    if target.exists():raise ValueError('Launch directory exists; keep it or move it aside before regenerating')
    for path in source.rglob('*'):
        if path.is_symlink():raise ValueError('Original desktop build must not contain symlinks')
    shutil.copytree(source, target)
    shutil.copyfile(target/'backend.launch.json', target/'backend.launch.original.json')
    code = (
        'import os,sys; from pathlib import Path; '
        'from manual2ar.application.config import load; from manual2ar.paths import ROOT; '
        'from tools.build.desktop_provenance import verify_build; '
        'from tools.build.spatial_delivery import export_backend_launcher; '
        'target=Path(sys.argv[1]); config=load(); verify_build(ROOT,target); '
        'export_backend_launcher(target,ROOT,config["backend"]["public_url"],os.environ.get("WSL_DISTRO_NAME",""))'
    )
    subprocess.run([str(python), '-B', '-c', code, str(target)], cwd=repo, check=True)
    migration = dict(schema_version='manual2ar-handoff-launch-v1',
                     original_build='Manual2AR-Data/builds/u7-pipeline/Manual2AR-Windows',
                     original_descriptor_sha256=digest(source/'backend.launch.json'),
                     relocated_descriptor_sha256=digest(target/'backend.launch.json'),
                     original_delivery_proof_preserved=True, rebuilt_frontend=False,
                     notice='Frontend is the preserved validated build; only the backend launcher was relocated.')
    (target/'migration.json').write_text(json.dumps(migration, indent=2)+'\n', encoding='utf-8')
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    setup = commands.add_parser('configure')
    setup.add_argument('handoff_root')
    setup.add_argument('--force', action='store_true')
    check = commands.add_parser('verify')
    check.add_argument('handoff_root')
    launch = commands.add_parser('launcher')
    launch.add_argument('handoff_root')
    args = parser.parse_args()
    try:
        if args.command == 'verify':
            print(json.dumps(verify(args.handoff_root), ensure_ascii=False))
            print('Verification passed. This checks preserved bytes, not hardware performance.')
        elif args.command == 'configure':
            configure(args.handoff_root, args.force)
            print('Created configs/app.local.json: loopback port 8011, no API key.')
            print('Original experiments and builds were not changed. GPU credentials were not created.')
            print('After run.sh setup and sync, run: python3 handoff.py launcher <handoff-root>')
        else:
            print(launcher(args.handoff_root))
            print('Original build evidence preserved. Backend descriptor recomputed from this source tree.')
    except (OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError) as error:
        parser.exit(1, 'Handoff operation failed: ' + str(error) + '\n')


if __name__ == '__main__':
    main()
