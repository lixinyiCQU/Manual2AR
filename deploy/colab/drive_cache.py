"""Drive stores immutable artifacts; Python, CUDA and inference stay on local SSD.

Standard-library only: this module runs in the notebook kernel, not GPU Python.
No virtualenv relocation and no API tokens or connection URLs in Drive caches.
"""
from pathlib import Path
from time import perf_counter
import hashlib
import json
import os
import platform
import secrets
import shutil
import subprocess
import sys
import tarfile
import tempfile
import uuid
import zipfile
from email.parser import BytesParser

from .environment import prepare_environment, run_logged

SETTINGS = ('precision', 'cutie', 'maximum_sessions', 'session_idle_seconds',
            'initialization_timeout_seconds', 'retain_initial_images')


def sha(path):
    with Path(path).open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def publish_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.part')
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2))
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def copy_verified(source, target, expected=None):
    """One sequential Drive read/write; publish only after size/SHA verification."""
    source, target = Path(source), Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + '.' + uuid.uuid4().hex + '.part')
    fingerprint = hashlib.sha256()
    size = 0
    try:
        with source.open('rb') as src, temporary.open('wb') as dst:
            while chunk := src.read(8 * 1024 * 1024):
                dst.write(chunk)
                fingerprint.update(chunk)
                size += len(chunk)
        result = dict(size=size, sha256=fingerprint.hexdigest())
        if expected and any(result[k] != expected[k] for k in ('size', 'sha256')):
            raise ValueError('Cache size/SHA mismatch: ' + source.name)
        temporary.replace(target)
        return result
    finally:
        temporary.unlink(missing_ok=True)


def unpack_wheels(archive, target):
    """Do not extract links, directories or paths supplied by cache metadata."""
    target = Path(target)
    target.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, 'r:') as bundle:
        for item in bundle.getmembers():
            name = Path(item.name)
            if not item.isfile() or len(name.parts) != 1 or name.name != item.name:
                raise ValueError('Invalid wheel archive member')
            if name.name != 'requirements.lock' and name.suffix != '.whl':
                raise ValueError('Unexpected wheel archive member')
            with bundle.extractfile(item) as src, (target / name.name).open('wb') as dst:
                shutil.copyfileobj(src, dst)
    if not (target / 'requirements.lock').is_file():
        raise ValueError('Cached dependency lock missing')


def validate_wheelhouse(folder, pins):
    """Sdists are insufficient for an offline restore: require every locked wheel."""
    import re
    normalize = lambda value: re.sub(r'[-_.]+', '-', value).lower()
    available = set()
    for path in Path(folder).glob('*.whl'):
        try:
            with zipfile.ZipFile(path) as wheel:
                metadata = next(name for name in wheel.namelist() if name.endswith('.dist-info/METADATA'))
                value = BytesParser().parsebytes(wheel.read(metadata))
                if not value['Name'] or not value['Version']:
                    raise ValueError('Missing package metadata')
                available.add((normalize(value['Name']), value['Version']))
        except (zipfile.BadZipFile, StopIteration) as error:
            raise ValueError('Invalid cached wheel: ' + path.name) from error
    missing = [pin for pin in pins if tuple([normalize(pin.split('==')[0]), pin.split('==')[1]]) not in available]
    if missing:
        raise ValueError('Offline wheel cache incomplete: ' + ', '.join(missing))


class DriveCache:
    def __init__(self, root, cache_root=None, cache_environment=True):
        self.root = Path(root).resolve()
        self.cache = Path(cache_root).resolve() if cache_root else None
        self.cache_environment = cache_environment
        self.bad = set()
        self.events = []
        self.config_path = self.root / 'configs/inference.local.json'
        self.started = perf_counter()

    def event(self, stage, **data):
        value = dict(stage=stage, elapsed_seconds=round(perf_counter() - self.started, 3), **data)
        self.events.append(value)
        publish_json(self.root / 'startup_cache.json', dict(events=self.events))
        print('[Drive cache] ' + json.dumps(value, ensure_ascii=False), flush=True)

    def settings(self, defaults):
        result = dict(defaults)
        path = self.cache / 'settings.json' if self.cache else None
        if path and path.is_file():
            try:
                saved = json.loads(path.read_text())
                result.update({k: saved[k] for k in SETTINGS if k in saved})
            except (OSError, ValueError):
                self.event('settings', status='invalid; using notebook defaults')
        return result

    def environment_key(self):
        config = json.loads(self.config_path.read_text())
        files = ('deploy/common/requirements.txt','deploy/common/bootstrap.py','deploy/colab/environment.py','manual2ar_inference/engines/sam31_sources.json')
        spec = dict(schema=1, python='3.12', machine=platform.machine(), libc=platform.libc_ver(),
                    os_release=Path('/etc/os-release').read_text() if Path('/etc/os-release').exists() else platform.system(),
                    revisions=config['revisions'],
                    sources={name: sha(self.root / name) for name in files})
        key = hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()
        return key, spec

    def _model_specs(self):
        config = json.loads(self.config_path.read_text())
        sources = json.loads((self.root / 'manual2ar_inference/engines/sam31_sources.json').read_text())
        return [
            ('sam31-' + sources['weights']['sha256'], config['sam3_checkpoint'], sources['weights']),
            ('cutie-' + config['revisions']['cutie'], config['cutie_checkpoint'], None),
        ]

    def restore_models(self):
        if not self.cache:
            return
        for key, relative, expected in self._model_specs():
            target = self.root / relative
            folder = self.cache / 'models' / key
            manifest = folder / 'manifest.json'
            if target.is_file():
                self.event('model', model=target.name, status='local file; bootstrap validates SAM3.1')
                continue
            if not manifest.exists():
                self.event('model', model=target.name, status='cache miss')
                continue
            try:
                records = json.loads(manifest.read_text())['files']
                if expected and any(records[target.name][k] != expected[k] for k in ('size', 'sha256')):
                    raise ValueError('SAM3.1 cache version mismatch')
                for name, record in records.items():
                    if name not in (target.name, target.with_suffix('.LICENSE').name, target.with_suffix('.source.json').name):
                        raise ValueError('Unexpected model cache file')
                    copy_verified(folder / name, target.parent / name, record)
                if not target.is_file():
                    raise ValueError('Cached checkpoint missing')
                self.event('model', model=target.name, status='restored', bytes=target.stat().st_size)
            except (OSError, ValueError, KeyError):
                target.unlink(missing_ok=True)
                self.bad.add(key)
                self.event('model', model=target.name, status='invalid cache; bootstrap will download')

    def save_models(self):
        if not self.cache:
            return
        for key, relative, expected in self._model_specs():
            checkpoint = self.root / relative
            folder = self.cache / 'models' / key
            if (folder / 'manifest.json').is_file() and key not in self.bad:
                continue
            files = {}
            for source in (checkpoint, checkpoint.with_suffix('.LICENSE'), checkpoint.with_suffix('.source.json')):
                if source.is_file():
                    files[source.name] = copy_verified(source, folder / source.name, expected if source == checkpoint else None)
            if checkpoint.name not in files:
                raise FileNotFoundError(checkpoint.name)
            publish_json(folder / 'manifest.json', dict(files=files))
            self.event('model', model=checkpoint.name, status='saved', bytes=files[checkpoint.name]['size'])

    def restore_environment(self):
        if not self.cache or not self.cache_environment:
            return None
        key, _ = self.environment_key()
        folder = self.cache / 'environments' / key
        manifest = folder / 'manifest.json'
        if not manifest.exists():
            self.event('environment', status='cache miss', key=key[:12])
            return None
        try:
            record = json.loads(manifest.read_text())['archive']
            archive = self.root / '.wheelhouse.tar'
            copy_verified(folder / 'wheels.tar', archive, record)
            with tempfile.TemporaryDirectory(dir=self.root, prefix='.wheels-') as temporary:
                unpack_wheels(archive, temporary)
                destination = self.root / '.wheelhouse'
                destination.mkdir(exist_ok=True)
                for path in Path(temporary).iterdir():
                    path.replace(destination / path.name)
            archive.unlink()
            self.event('environment', status='restored', key=key[:12], bytes=record['size'])
            return destination
        except (OSError, ValueError, KeyError, tarfile.TarError):
            self.bad.add(key)
            self.event('environment', status='invalid cache; rebuilding', key=key[:12])
            return None

    def _offline_python(self, wheels):
        python = self.root / '.gpu-venv/bin/python'
        if not python.exists():
            tools = self.root / '.bootstrap-tools'
            uv = tools / 'bin/uv'
            if not uv.exists():
                run_logged([sys.executable, '-m', 'pip', 'install', '--no-index', '--find-links', str(wheels),
                            '--target', str(tools), 'uv==0.9.5'], self.root, 'Restore Python environment manager')
            # Never relocate a venv. Interpreter acquisition may still need the network.
            run_logged([str(uv), 'venv', '--python', '3.12', str(self.root / '.gpu-venv')], self.root, 'Create local Python 3.12 venv')
        run_logged([sys.executable, '-m', 'pip', '--python', str(python), 'install', '--no-index',
                    '--find-links', str(wheels), 'pip'], self.root, 'Seed local pip from cache')
        # The lock enumerates the validated inference environment. Source wheels
        # deliberately omit unused training dependencies, as bootstrap does.
        run_logged([str(python), '-m', 'pip', 'install', '--no-index', '--find-links', str(wheels),
                    '--no-deps', '-r', str(wheels / 'requirements.lock')], self.root, 'Install locked dependencies offline')
        return str(python)

    def save_environment(self, python):
        key, spec = self.environment_key()
        folder = self.cache / 'environments' / key
        if (folder / 'manifest.json').is_file() and key not in self.bad:
            return
        wheels = self.root / '.wheelhouse'
        wheels.mkdir(exist_ok=True)
        code = "import importlib.metadata as m,json;print(json.dumps(sorted({d.metadata['Name']+'=='+d.version for d in m.distributions()})))"
        pins = json.loads(subprocess.check_output([python, '-c', code], text=True))
        (wheels / 'requirements.lock').write_text('\n'.join(pins) + '\n')
        config = json.loads(self.config_path.read_text())
        for name, subfolder in [('cutie', 'Cutie'), ('ultralytics', 'ultralytics')]:
            source = self.root / 'gpu_repos' / subfolder
            revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=source, text=True).strip()
            if revision != config['revisions'][name]:
                raise ValueError('Refusing to cache unpinned inference source')
            run_logged([python, '-m', 'pip', 'wheel', '--no-deps', '--no-build-isolation', '-w', str(wheels), str(source)],
                       self.root, 'Cache pinned ' + name + ' wheel')
        downloads = [p for p in pins if p.split('==')[0].lower() not in ('cutie', 'ultralytics')]
        run_logged([python, '-m', 'pip', 'wheel', '--no-deps', '--wheel-dir', str(wheels),
                    '--extra-index-url', 'https://download.pytorch.org/whl/cu126', *downloads, 'uv==0.9.5'],
                   self.root, 'Build offline dependency cache (first run only)')
        validate_wheelhouse(wheels, [*pins, 'uv==0.9.5'])
        archive = self.root / '.wheelhouse.tar'
        with tarfile.open(archive, 'w:') as bundle:
            for path in sorted(wheels.iterdir()):
                if path.name == 'requirements.lock' or path.suffix == '.whl':
                    bundle.add(path, arcname=path.name, recursive=False)
        record = copy_verified(archive, folder / 'wheels.tar')
        publish_json(folder / 'manifest.json', dict(spec=spec, archive=record, packages=pins))
        archive.unlink()
        self.event('environment', status='saved', key=key[:12], bytes=record['size'])

    def prepare(self, force=False):
        os.environ['TORCH_HOME'] = str(self.root / '.torch-cache')
        self.restore_models()
        key, _ = self.environment_key()
        marker = self.root / '.drive-cache-ready.json'
        python = str(self.root / '.gpu-venv/bin/python')
        restored = False
        local_reused = False
        # Re-running cells in the same VM should not copy gigabytes from Drive.
        if self.cache and self.cache_environment and not force and Path(python).exists() and marker.exists():
            try:
                saved = json.loads(marker.read_text())
                if saved['environment_key'] == key and (self.cache / 'environments' / key / 'manifest.json').is_file():
                    self._validate_python(python)
                    restored = True
                    local_reused = True
                    self.event('environment', status='local environment reused', key=key[:12])
            except (OSError, ValueError, KeyError, RuntimeError):
                pass
        wheels = None if force or restored else self.restore_environment()
        if wheels:
            try:
                python = self._offline_python(wheels)
                self._validate_python(python)
                restored = True
            except (OSError, RuntimeError, subprocess.SubprocessError):
                self.bad.add(self.environment_key()[0])
                self.event('environment', status='offline restore failed; using bootstrap')
        if not restored:
            python = prepare_environment(self.root)
            run_logged([python, '-u', '-m', 'deploy.common.bootstrap'], self.root, 'Install module-one Cutie service')
        else:
            config = json.loads(self.config_path.read_text())
            if not config.get('api_token'):
                config['api_token'] = secrets.token_urlsafe(32)
                publish_json(self.config_path, config)
                self.config_path.chmod(0o600)
            # A wheel hit does not imply a checkpoint hit. Keep download/SHA checks.
            code = "from pathlib import Path;import json;from deploy.common.weights import prepare_sam31;from deploy.common.bootstrap import fetch;root=Path.cwd();c=json.loads((root/'configs/inference.local.json').read_text());prepare_sam31(c,root);fetch('https://github.com/hkchengrex/Cutie/releases/download/v1.0/cutie-base-mega.pth',root/c['cutie_checkpoint'])"
            run_logged([python, '-c', code], self.root, 'Validate or fetch model files')
            if not local_reused or not (self.root / 'gpu_environment.lock.json').exists():
                config = json.loads(self.config_path.read_text())
                key, _ = self.environment_key()
                cached = json.loads((self.cache / 'environments' / key / 'manifest.json').read_text())
                publish_json(self.root / 'gpu_environment.lock.json', dict(
                    repositories=config['revisions'], package_versions=cached['packages'],
                    weights_sha256={name: sha(self.root / config[name]) for name in ('sam3_checkpoint', 'cutie_checkpoint')},
                    source='verified Drive wheel archive', cache_key=key))
        if self.cache:
            try:
                config = json.loads(self.config_path.read_text())
                publish_json(self.cache / 'settings.json', {k: config[k] for k in SETTINGS if k in config})
                self.save_models()
                if self.cache_environment:
                    if force:
                        self.bad.add(self.environment_key()[0])
                    self.save_environment(python)
            except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
                self.event('cache_write', status='failed; service can still start', error_type=type(error).__name__)
        self.restore_auxiliary()
        publish_json(marker, dict(environment_key=key))
        self.event('ready', offline_dependencies=restored, python=python)
        return python

    def _validate_python(self, python):
        code = "import torch,torchvision,cutie,ultralytics,json;from pathlib import Path;from ultralytics.models.sam import SAM3Predictor;assert torch.cuda.is_available();assert torch.__version__.startswith('2.7.1');assert torchvision.__version__.startswith('0.22.1');assert torch.version.cuda=='12.6';assert ultralytics.__version__==json.loads(Path('manual2ar_inference/engines/sam31_sources.json').read_text())['ultralytics_version']"
        run_logged([python, '-c', code], self.root, 'Validate cached CUDA dependencies')

    def restore_auxiliary(self):
        if not self.cache:
            return
        folder = self.cache / 'torch-hub'
        path = folder / 'manifest.json'
        if not path.exists():
            return
        try:
            for name, record in json.loads(path.read_text())['files'].items():
                if Path(name).name != name:
                    raise ValueError('Invalid auxiliary checkpoint name')
                target = self.root / '.torch-cache/hub/checkpoints' / name
                if not target.exists():
                    copy_verified(folder / name, target, record)
        except (OSError, ValueError, KeyError):
            self.event('torch_hub', status='cache incomplete; upstream may download missing weights')

    def save_auxiliary(self):
        if not self.cache:
            return
        try:
            folder = self.cache / 'torch-hub'
            files = {}
            previous = json.loads((folder / 'manifest.json').read_text()).get('files', {}) if (folder / 'manifest.json').is_file() else {}
            for source in sorted((self.root / '.torch-cache/hub/checkpoints').glob('*')):
                if source.is_file() and source.suffix in ('.pt', '.pth'):
                    record = dict(size=source.stat().st_size, sha256=sha(source))
                    cached = folder / source.name
                    if previous.get(source.name) == record and cached.is_file() and cached.stat().st_size == record['size']:
                        files[source.name] = record
                    else:
                        files[source.name] = copy_verified(source, cached, record)
            if files:
                publish_json(folder / 'manifest.json', dict(files=files))
                self.event('torch_hub', status='saved', files=len(files))
        except (OSError, ValueError) as error:
            self.event('torch_hub', status='save failed', error_type=type(error).__name__)
