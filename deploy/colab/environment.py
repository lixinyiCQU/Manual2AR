"""Standard-library-only Colab setup, independent of the notebook Python version."""
from pathlib import Path
import json
import os
import re
import subprocess
import sys


def child_environment():
    environment = os.environ.copy()
    for key in ('PYTHONPATH', 'PYTHONHOME', 'VIRTUAL_ENV'):
        environment.pop(key, None)
    environment['PYTHONUNBUFFERED'] = '1'
    return environment


def config_secrets(root):
    path = Path(root) / 'configs/inference.local.json'
    try:
        config = json.loads(path.read_text())
        return tuple(config[key] for key in ('api_token','hf_token') if isinstance(config.get(key),str) and config[key])
    except FileNotFoundError:return ()
    except (OSError,ValueError,TypeError):return None


def redact(text, root, known_secrets=None):
    values=config_secrets(root) if known_secrets is None else known_secrets
    if values is None:
        return '[Output withheld: configuration temporarily unreadable]\n'
    for value in values:text=text.replace(value,'[REDACTED]')
    text = re.sub(r'(?i)(Bearer\s+)\S+', r'\1[REDACTED]', text)
    return re.sub(r'\bhf_[A-Za-z0-9]+\b', '[REDACTED]', text)


def run_logged(args, root, stage):
    """Stream both output channels and retain the real failure, not only its exit code."""
    root = Path(root)
    # Snapshot before spawning the child that may replace its configuration.
    # Never let a transient JSON read failure terminate the installation.
    known_secrets=config_secrets(root)
    if known_secrets is None:raise RuntimeError('Invalid inference configuration before '+stage)
    log_path = root / 'bootstrap.log'
    with log_path.open('a', encoding='utf-8') as log:
        title = f'\n=== {stage} ===\n'
        print(title, flush=True)
        log.write(title)
        log.flush()
        process = subprocess.Popen(args, cwd=root, env=child_environment(),
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   text=True, encoding='utf-8', errors='replace', bufsize=1)
        try:
            for line in process.stdout:
                line = redact(line, root, known_secrets)
                print(line, end='', flush=True)
                log.write(line)
                log.flush()
            code = process.wait()
        except BaseException:
            process.terminate()
            process.wait()
            raise
        finally:
            process.stdout.close()
    if code:
        tail = '\n'.join(log_path.read_text().splitlines()[-35:])
        raise RuntimeError(f'{stage} failed (exit {code}). Full log: {log_path}\n{tail}')


def prepare_environment(root):
    """Install a separate 3.12 interpreter even when Colab's kernel uses 3.13+."""
    root = Path(root)
    if sys.platform != 'linux':
        raise RuntimeError('This notebook requires a Linux Colab/Runpod GPU runtime.')
    python = root / '.gpu-venv/bin/python'
    if not python.exists():
        tools = root / '.bootstrap-tools'
        uv = tools / 'bin/uv'
        if not uv.exists():
            run_logged([sys.executable, '-m', 'pip', 'install', '--disable-pip-version-check',
                        '--target', str(tools), 'uv==0.9.5'], root, 'Install isolated Python manager')
        run_logged([str(uv), 'venv', '--python', '3.12', '--seed', str(root / '.gpu-venv')],
                   root, 'Prepare GPU Python 3.12 environment')
    run_logged([str(python), '-c',
                "import sys, pip; print('GPU Python:', sys.version); "
                "assert sys.version_info[:2] == (3, 12), 'GPU environment must use Python 3.12'"],
               root, 'Check GPU interpreter and pip')
    return str(python)
