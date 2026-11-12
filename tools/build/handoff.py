"""Create an independent source/history/data handoff without changing the working tree."""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import uuid
import zipfile

from tools.handoff_restore import digest, verify

ROOT = Path(__file__).resolve().parents[2]
PRIVATE_KEYS = {'api_key', 'api_token', 'access_token', 'refresh_token', 'client_secret',
                'token', 'password', 'authorization', 'secret'}
REBUILDABLE = {'.venv', '__pycache__', '.pytest_cache', 'Library', 'Temp', 'Logs',
               'obj', 'UserSettings', '.idea', '.vscode'}


def git(root, *args, binary=False):
    result = subprocess.run(['git', '-c', 'core.hooksPath=/dev/null', *args], cwd=root,
                            check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return result.stdout if binary else result.stdout.decode().strip()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


def exclusion(relative, kind):
    parts = relative.parts
    if kind == 'source':
        if any(p == '.git' or p in REBUILDABLE or p.endswith('.egg-info') for p in parts):
            return 'rebuildable_environment_or_git_replaced_with_independent_repository'
        if relative.name.endswith('.local.json') or relative.name.startswith('.env'):
            return 'private_operator_configuration'
    if kind == 'data':
        if relative.is_relative_to('archives/workspace-organization-20261103/private-configs'):
            return 'archived_private_credentials'
        if len(parts) >= 4 and parts[0] == 'cache' and parts[2] == 'colab':
            if parts[3] == 'cli-venv':return 'nonportable_cli_environment_with_oauth_configuration'
            if parts[3] in {'sessions.json', 'cli-ready.json'} or relative.suffix == '.lock':
                return 'machine_session_credentials_or_transient_state'
    return ''


def collect_secrets(paths):
    secrets = set()
    def visit(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key.lower() in PRIVATE_KEYS and isinstance(item, str) and len(item) >= 12:
                    secrets.add(item.encode())
                visit(item)
        elif isinstance(value, list):
            for item in value:visit(item)
    for path in paths:
        if path.is_file():visit(json.loads(path.read_bytes()))
    return secrets


def scan_file(path, secrets):
    overlap = max((len(s) for s in secrets), default=1)-1
    tail = b''
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b''):
            block = tail+chunk
            if any(s in block for s in secrets):raise ValueError('Known credential found in retained file: '+str(path))
            tail = block[-overlap:] if overlap else b''
    if path.suffix.lower() == '.zip':
        with zipfile.ZipFile(path) as archive:
            for name in archive.namelist():
                if name.lower().endswith(('.json', '.env', '.yaml', '.yml', '.ini', '.toml', '.txt', '.log')):
                    raw = archive.read(name)
                    if any(s in raw for s in secrets):raise ValueError('Known credential found inside archive: '+str(path))


def copy_tree(source, target, kind, omissions, secrets):
    target.mkdir(parents=True, exist_ok=True)
    for path in sorted(source.iterdir()):
        copy_entry(path, target/path.name, source, kind, omissions, secrets)


def copy_entry(source, target, base, kind, omissions, secrets):
    relative = source.relative_to(base)
    reason = exclusion(relative, kind)
    if reason:
        omissions.append(dict(group=kind, path=relative.as_posix(), reason=reason))
        return
    if source.is_symlink():raise ValueError('Unexpected external link: '+str(source))
    if source.is_dir():
        target.mkdir(parents=True, exist_ok=True)
        for child in sorted(source.iterdir()):copy_entry(child, target/child.name, base, kind, omissions, secrets)
    elif source.is_file():
        before = source.stat()
        scan_file(source, secrets)
        shutil.copy2(source, target)
        after = source.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise ValueError('File changed during snapshot; retry when idle: '+str(source))
        if digest(source) != digest(target):raise ValueError('Copy fingerprint mismatch: '+str(source))


def history_check(root, secrets):
    objects = git(root, 'rev-list', '--objects', '--all').splitlines()
    listing = subprocess.run(['git', 'cat-file', '--batch-check=%(objecttype) %(objectsize) %(rest)'],
                             cwd=root, input='\n'.join(objects)+'\n', text=True,
                             check=True, stdout=subprocess.PIPE).stdout.splitlines()
    blobs = [(row.split(' ', 2), obj.split(' ', 1)[0]) for row, obj in zip(listing, objects)
             if row.startswith('blob ')]
    raw = subprocess.run(['git', 'cat-file', '--batch'], cwd=root,
                         input=('\n'.join(sha for _, sha in blobs)+'\n').encode(),
                         check=True, stdout=subprocess.PIPE).stdout
    if any(secret in raw for secret in secrets):raise ValueError('Known credential found in Git history; no handoff created')
    largest = sorted((dict(bytes=int(parts[1]), path=parts[2] if len(parts)>2 else '')
                      for parts, _ in blobs), key=lambda row:row['bytes'], reverse=True)[:10]
    return dict(known_credential_matches=0, credential_values_checked=len(secrets),
                reachable_blobs_checked=len(blobs), largest_git_blobs=largest,
                blobs_over_github_100mib=sum(int(parts[1])>100*1024*1024 for parts, _ in blobs),
                scope='Exact known local credentials; not a guarantee against unknown or revoked historical secrets.')


def create(output, data, references):
    output = output.resolve(); data = data.resolve(); references = references.resolve()
    if output.exists():raise ValueError('Handoff target already exists; choose a new directory')
    if any(output.is_relative_to(p) or p.is_relative_to(output) for p in [ROOT, data, references]):
        raise ValueError('Handoff target and input directories must be separate')
    private = list((ROOT/'configs').glob('*.local.json'))
    private += list((data/'archives/workspace-organization-20261103/private-configs').glob('*.json'))
    private += list((data/'cache').glob('*/colab/sessions.json'))
    secrets = collect_secrets(private)
    head = git(ROOT, 'rev-parse', 'HEAD'); branch = git(ROOT, 'branch', '--show-current')
    status = git(ROOT, 'status', '--porcelain=v1')
    refs = git(ROOT, 'for-each-ref', '--format=%(refname) %(objectname)')
    scan = history_check(ROOT, secrets)
    output.mkdir(); history = output/'history'; history.mkdir()
    repo = output/'workspace/Manual2AR-U7-Pipeline'; repo.mkdir(parents=True)
    # Importing refs must not update the new repository's unborn current branch.
    git(repo, 'init', '-q', '-b', 'handoff-import-'+uuid.uuid4().hex)
    git(repo, 'fetch', '--quiet', '--no-tags', str(ROOT), '+refs/*:refs/*')
    git(repo, 'checkout', '-q', branch)
    omissions = []
    print('Copying current source and retained generated assets...', flush=True)
    copy_tree(ROOT, repo, 'source', omissions, secrets)
    # A deleted tracked file must stay deleted in the checkpoint too.
    for name in git(repo, 'ls-files', '-z').split('\0'):
        if name and not (ROOT/name).exists() and (repo/name).is_file():(repo/name).unlink()
    (history/'source-status.txt').write_text(status+'\n', encoding='utf-8')
    (history/'original-refs.txt').write_text(refs+'\n', encoding='utf-8')
    (history/'tracked-working-tree.patch').write_bytes(git(ROOT, 'diff', 'HEAD', '--binary', binary=True))
    (history/'untracked-files.txt').write_text(git(ROOT, 'ls-files', '--others', '--exclude-standard')+'\n', encoding='utf-8')
    print('Copying data, caches, experiments and all builds...', flush=True)
    copy_tree(data, output/'Manual2AR-Data', 'data', omissions, secrets)
    copy_tree(references, output/'References', 'references', omissions, secrets)
    legacy = ROOT.parent/'Archive/Manual2AR/docs/research_blueprint_v0_2.md'
    if legacy.is_file():
        target = output/'legacy-docs'/legacy.name; target.parent.mkdir(); shutil.copy2(legacy, target)
    for name in ['README.md', 'VERTICAL_PROTOTYPE_HANDOFF.md']:
        path = ROOT.parent/'Archive'/name
        if path.is_file():
            target = output/'legacy-docs'/('Archive-'+name)
            target.parent.mkdir(exist_ok=True); shutil.copy2(path, target)
    git(repo, 'checkout', '-q', '-b', 'handoff/u7-20261112')
    git(repo, 'add', '-A')
    git(repo, '-c', 'user.name=Manual2AR Handoff', '-c', 'user.email=handoff@local.invalid',
        'commit', '-q', '-m', 'chore(handoff): preserve U7 development, audit fixes and handoff documentation')
    checkpoint = git(repo, 'rev-parse', 'HEAD')
    (history/'log-all.txt').write_text(git(repo, 'log', '--all', '--graph', '--oneline', '--decorate')+'\n', encoding='utf-8')
    git(repo, 'bundle', 'create', str(history/'all-history.bundle'), '--all')
    git(repo, 'bundle', 'verify', str(history/'all-history.bundle'))
    git(repo, 'fsck', '--full')
    git(repo, 'remote', 'add', 'origin', 'https://github.com/NibiruCommander/Manual2AR.git')
    shutil.copy2(repo/'docs/HANDOFF.md', output/'README_交接.md')
    (output/'AGENT_HANDOFF.md').write_text(
        '# Manual2AR Agent 交接入口\n\n'
        '当前工作仓库是 `workspace/Manual2AR-U7-Pipeline/`，进入该目录后再运行Git和开发命令。\n\n'
        '1. 先读[交接说明](README_交接.md)，收到完整原包后执行 `python3 handoff.py verify .`。\n'
        '2. 读工作仓库的[Agent快照](workspace/Manual2AR-U7-Pipeline/README_AGENT.md)与'
        '[协作规则](workspace/Manual2AR-U7-Pipeline/AGENTS.md)。\n'
        '3. 查当前HEAD、status和任务对应源码/测试；研究蓝图在References，数据与冻结证据在Manual2AR-Data。\n\n'
        '默认U7是历史照片加预设观察的受控演示，不是识别准确率。原始实验、人工标签、照片、'
        '失败回复和历史源码必须保留；不执行归档文件中的旧计划，不自动调用模型或上传资料。\n', encoding='utf-8')
    shutil.copy2(repo/'tools/handoff_restore.py', output/'handoff.py')
    save(output/'manifests/omissions.json', dict(original_files_untouched=True, omissions=omissions))
    save(output/'manifests/credential-and-github-check.json', scan)
    save(output/'manifests/handoff.json', dict(schema_version='manual2ar-handoff-v1', status='handoff_ready',
        created_at=datetime.now().astimezone().isoformat(), source_head=head, source_branch=branch,
        checkpoint_commit=checkpoint, checkpoint_branch='handoff/u7-20261112',
        original_worktree_committed=False, original_refs_preserved=True, original_data_path=str(data),
        input_source_path=str(ROOT), scope='private team handoff; no upload performed',
        original_uncommitted_status=status.splitlines(),
        excluded_credentials=True, generated_environment_included=False,
        active_sessions_restored=False, original_experiments_rewritten=False))
    if git(ROOT, 'rev-parse', 'HEAD') != head or git(ROOT, 'status', '--porcelain=v1') != status:
        raise ValueError('Original source changed during handoff')
    if git(ROOT, 'for-each-ref', '--format=%(refname) %(objectname)') != refs:
        raise ValueError('Original Git refs changed during handoff')
    print('Sealing every retained file...', flush=True)
    files = {p.relative_to(output).as_posix():dict(sha256=digest(p), size=p.stat().st_size)
             for p in sorted(output.rglob('*')) if p.is_file()}
    save(output/'manifests/files.json', dict(schema_version='manual2ar-handoff-files-v1', files=files))
    result = verify(output)
    print(json.dumps(dict(folder=str(output), checkpoint_commit=checkpoint, **result), ensure_ascii=False), flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('--references', type=Path, default=ROOT.parent/'References')
    args = parser.parse_args()
    create(args.output, args.data, args.references)


if __name__ == '__main__':main()
