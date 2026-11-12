"""Bind the Windows payload to the Unity inputs that actually passed validation."""
import hashlib
import json
import subprocess
from pathlib import Path


PROOF = 'desktop-build.json'
FOLDERS = ('Assets', 'Packages', 'ProjectSettings')


def fingerprint(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def repository_sources(root):
    names = subprocess.check_output(['git', 'ls-files', '-c', '-o', '--exclude-standard', '-z'], cwd=root)
    return {name: fingerprint(Path(root) / name) for name in sorted(set(names.decode().split('\0')))
            if name and (Path(root) / name).is_file()}


def project_inputs(project):
    project = Path(project)
    return {p.relative_to(project).as_posix(): fingerprint(p)
            for folder in FOLDERS for p in sorted((project / folder).rglob('*')) if p.is_file()}


def check_inputs(root, project, expected):
    current = project_inputs(Path(root) / 'apps/unity/Manual2AR')
    compiled = project_inputs(project)
    helpers = {'Assets/Editor/ProductValidation.cs', 'Assets/Editor/UiGalleryValidation.cs', 'Assets/Editor/WikiPipelineValidation.cs', 'Assets/Editor/WindowsPlayerBuild.cs'}
    extra = set(compiled) - set(expected)
    if (not expected or current != expected or any(compiled.get(k) != v for k, v in expected.items())
            or any(k not in helpers and not k.endswith('.meta') for k in extra)):
        raise ValueError('Unity inputs changed during validation/build; rebuild the Windows Player')


def seal_build(root, project, player, expected, validation):
    check_inputs(root, project, expected)
    player = Path(player)
    if validation.get('runtime_errors') != 0 or validation.get('scenes', 0) < 4:
        raise ValueError('Windows build requires successful four-scene validation')
    for name in ('Manual2AR.exe', 'Manual2AR_Data/Managed/Assembly-CSharp.dll'):
        if not (player / name).is_file():
            raise ValueError('Windows build payload is incomplete')
    proof = {'schema_version': 'manual2ar-desktop-build-v1', 'frontend_inputs': expected,
             'compiled_project_sha256': project_inputs(project),
             'player_sha256': {p.relative_to(player).as_posix(): fingerprint(p)
                               for p in sorted(player.rglob('*')) if p.is_file() and p.name != PROOF},
             'validation': validation}
    (player / PROOF).write_text(json.dumps(proof, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return proof


def verify_build(root, player):
    player = Path(player)
    path = player / PROOF
    if not path.is_file():
        raise ValueError('No verified desktop build record; run tools.build.validate_desktop --build first')
    proof = json.loads(path.read_text(encoding='utf-8'))
    if proof.get('schema_version') != 'manual2ar-desktop-build-v1':
        raise ValueError('Unsupported desktop build record; rebuild the Windows Player')
    if project_inputs(Path(root) / 'apps/unity/Manual2AR') != proof.get('frontend_inputs'):
        raise ValueError('Current Unity inputs differ from the Windows Player; rebuild before packaging')
    roots = {Path(name).parts[0] for name in proof.get('player_sha256', {})}
    actual = {p.relative_to(player).as_posix() for p in player.rglob('*')
              if p.is_file() and p.relative_to(player).parts[0] in roots}
    if actual != set(proof.get('player_sha256', {})):
        raise ValueError('Windows payload files changed; rebuild before packaging')
    for name, digest in proof.get('player_sha256', {}).items():
        p = (player / name).resolve()
        if not p.is_relative_to(player.resolve()) or not p.is_file() or fingerprint(p) != digest:
            raise ValueError('Windows payload changed or is incomplete; rebuild before packaging')
    for name in ('Manual2AR.exe', 'Manual2AR_Data/Managed/Assembly-CSharp.dll'):
        if name not in proof.get('player_sha256', {}):
            raise ValueError('Windows build record is incomplete; rebuild before packaging')
    return proof
