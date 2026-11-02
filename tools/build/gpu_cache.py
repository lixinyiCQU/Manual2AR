"""Add Colab Drive startup caching while retaining the canonical inference bundle."""
from pathlib import Path
import argparse
import json

ROOT = Path(__file__).resolve().parents[2]


def build(source, destination):
    notebook = json.loads(Path(source).read_text())
    found = set()
    for cell in notebook['cells']:
        if cell['cell_type'] != 'code':
            continue
        text = ''.join(cell['source'])
        if 'CUTIE_PRECISION =' in text:
            text += '''
# Drive 缓存；首次需要在Google弹窗授权挂载。模型/性能选项继续使用上面的表单。
USE_DRIVE_CACHE = True  # @param {type:"boolean"}
DRIVE_CACHE_ROOT = "/content/drive/MyDrive/Manual2AR/cache-v1"  # @param {type:"string"}
CACHE_ENVIRONMENT = True  # @param {type:"boolean"}
FORCE_REBUILD_ENV = False  # @param {type:"boolean"}
'''
            found.add('parameters')
        if 'SOURCE_ZIP' in text and 'archive.extractall(BASE)' in text:
            anchor = 'config=json.loads(config_path.read_text())'
            setup = '''if USE_DRIVE_CACHE:
    try:
        from google.colab import drive
    except ImportError:
        raise RuntimeError('Drive缓存版需要Colab；其他平台请取消USE_DRIVE_CACHE。')
    drive.mount('/content/drive')
    cache_path=pathlib.Path(DRIVE_CACHE_ROOT).expanduser().resolve()
    if not cache_path.is_relative_to(pathlib.Path('/content/drive').resolve()):
        raise ValueError('DRIVE_CACHE_ROOT必须位于已挂载的/content/drive内。')
else:
    cache_path=None
from deploy.colab.drive_cache import DriveCache
drive_cache=DriveCache(BASE,cache_path,cache_environment=CACHE_ENVIRONMENT)
config=drive_cache.settings(json.loads(config_path.read_text()))'''
            if anchor not in text:
                raise ValueError('Unsupported source notebook configuration cell')
            text = text.replace(anchor, setup, 1)
            text += "\nprint('Drive配置恢复后，由本次表单覆盖性能选项；API token不写入Drive。')\n"
            found.add('bundle')
        if 'GPU_PYTHON=prepare_environment(BASE)' in text:
            text = text.replace('    GPU_PYTHON=prepare_environment(BASE)\n    run_logged([GPU_PYTHON,\'-u\',\'-m\',\'deploy.common.bootstrap\'],BASE,\'Install shared Cutie service\')',
                                '    GPU_PYTHON=drive_cache.prepare(force=FORCE_REBUILD_ENV)')
            if 'GPU_PYTHON=prepare_environment(BASE)' in text:
                raise ValueError('Unsupported bootstrap cell')
            found.add('bootstrap')
        if "warm_request=urllib.request.Request" in text:
            text += '\n# Persist small torchvision/ResNet downloads made during Cutie warmup.\ndrive_cache.save_auxiliary()\n'
            found.add('warmup')
        cell['source'] = text.splitlines(True)
        cell['outputs'] = []
        cell['execution_count'] = None
        cell['metadata'] = {}
    if found != {'parameters', 'bundle', 'bootstrap', 'warmup'}:
        raise ValueError('Notebook layout differs: ' + repr(found))
    introduction = '''# Manual2AR：Google Drive 持久缓存启动版

从规范推理源码生成，保留 SAM3.1 + Cutie 及性能表单。

首次：挂载Drive → 常规安装/下载 → 缓存模型和锁定的wheel安装包 → 启动服务。首次建立环境缓存可能更久，并占用数GB至十几GB云盘空间，实际大小见startup_cache.json。

后续：挂载Drive → 校验并复制模型/安装包到Colab本地SSD → 在本地离线安装 → 启动服务。
不直接从Drive执行venv，不保证零安装、零网络或秒开。若本机缺Python3.12，仍可能需要获取解释器；首次SAM3.1加载、CUDA初始化和编译不会消失。

参数优先级：原始默认配置 → Drive里的settings.json → 本次Notebook表单。token/临时服务URL不缓存；新运行时仍下载新的连接JSON给本地后端。实验录像和现场图片不自动上传Drive。

`CACHE_ENVIRONMENT=False`仅缓存模型/配置，适合云盘空间不足时。`FORCE_REBUILD_ENV=True`只在修复环境时启用，成功后改回False。
依赖、源码revision、Python目标版本、CPU架构或系统兼容条件变化时使用不同环境缓存，不错误复用旧包。没有GPU时不会跳过检查。

缓存只减少启动安装/下载等待，不改变推理速度、公网往返或Colab回收策略。首次Drive授权需要本人在Google弹窗确认。
'''
    notebook['cells'].insert(0, dict(cell_type='markdown', metadata={}, source=introduction.splitlines(True)))
    notebook['metadata'].pop('widgets', None)
    notebook['metadata'].setdefault('colab', {})['name'] = Path(destination).name
    for cell in notebook['cells']:
        if cell['cell_type'] == 'code':
            compile(''.join(cell['source']), str(destination), 'exec')
    Path(destination).parent.mkdir(parents=True, exist_ok=True)
    Path(destination).write_text(json.dumps(notebook, ensure_ascii=False, indent=1))
    return Path(destination)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('source', type=Path)
    parser.add_argument('--output', type=Path, default=ROOT / 'deploy/colab/Manual2AR_GPU.ipynb')
    args = parser.parse_args()
    print(build(args.source, args.output))


if __name__ == '__main__':
    main()
