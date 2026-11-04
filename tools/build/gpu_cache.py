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
USE_DRIVE_CACHE = False  # @param {type:"boolean"}
DRIVE_CACHE_ROOT = "/content/drive/MyDrive/Manual2AR/cache-v1"  # @param {type:"string"}
CACHE_ENVIRONMENT = True  # @param {type:"boolean"}
FORCE_REBUILD_ENV = False  # @param {type:"boolean"}
PERSIST_REMOTE_LOGS = False  # @param {type:"boolean"}
REMOTE_LOG_INTERVAL = 15  # @param {type:"integer"}
'''
            found.add('parameters')
        if 'SOURCE_ZIP' in text and 'archive.extractall(BASE)' in text:
            anchor = 'config=json.loads(config_path.read_text())'
            setup = '''if USE_DRIVE_CACHE or PERSIST_REMOTE_LOGS:
    try:
        from google.colab import drive
    except ImportError:
        raise RuntimeError('Drive留存需要Colab；其他平台请取消USE_DRIVE_CACHE和PERSIST_REMOTE_LOGS。')
    drive.mount('/content/drive')
    cache_path=pathlib.Path(DRIVE_CACHE_ROOT).expanduser().resolve() if USE_DRIVE_CACHE else None
    if cache_path is not None and not cache_path.is_relative_to(pathlib.Path('/content/drive').resolve()):
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
            text += "\nfrom deploy.colab.retention import start_recorder\nif not 5<=REMOTE_LOG_INTERVAL<=300:raise ValueError('日志间隔需在5至300秒')\nretention_path=start_recorder(BASE,{'enabled':PERSIST_REMOTE_LOGS,'path':'/content/drive/MyDrive/Manual2AR/logs','interval_seconds':REMOTE_LOG_INTERVAL})\nprint('远端日志留存目录：',retention_path)\n"
            found.add('bundle')
        if 'GPU_PYTHON=prepare_environment(BASE)' in text:
            text = text.replace('    GPU_PYTHON=prepare_environment(BASE)\n    run_logged([GPU_PYTHON,\'-u\',\'-m\',\'deploy.common.bootstrap\'],BASE,\'Install shared Cutie service\')',
                                '    GPU_PYTHON=drive_cache.prepare(force=FORCE_REBUILD_ENV)')
            if 'GPU_PYTHON=prepare_environment(BASE)' in text:
                raise ValueError('Unsupported bootstrap cell')
            found.add('bootstrap')
        if "warm_request=urllib.request.Request" in text:
            text=text.replace('health=None\n',"from deploy.colab.worker import read,private_json,process_identity\nprocesses=read(BASE/'worker-processes.local.json',{})\nprocesses['service']=process_identity(service.pid)\nprivate_json(BASE/'worker-processes.local.json',processes)\nhealth=None\n",1)
            text += '\n# Persist small torchvision/ResNet downloads made during Cutie warmup.\ndrive_cache.save_auxiliary()\n'
            found.add('warmup')
        if "connection=BASE/'inference.connection.local.json'" in text:
            text += "\nfrom deploy.colab.worker import read,private_json,process_identity\nprocesses=read(BASE/'worker-processes.local.json',{})\nprocesses['tunnel']=process_identity(tunnel.pid) if tunnel is not None else None\nprivate_json(BASE/'worker-processes.local.json',processes)\n"
        if 'STOP_SERVICE=False' in text:
            text += "\nif STOP_SERVICE:\n    from deploy.colab.worker import read,stop_owned\n    stop_owned(read(BASE/'worker-processes.local.json',{}).get('recorder'))\n"
        cell['source'] = text.splitlines(True)
        cell['outputs'] = []
        cell['execution_count'] = None
        cell['metadata'] = {}
    if found != {'parameters', 'bundle', 'bootstrap', 'warmup'}:
        raise ValueError('Notebook layout differs: ' + repr(found))
    introduction = '''# Manual2AR：手动运行的 SAM3.1 + Cutie GPU 服务

1. 在 Google Colab 中上传本笔记本（仅这一份文件），选择 T4 GPU 运行时。
2. 默认参数即可，点击「全部运行」。无需 Colab CLI、私有仓库授权或本地 API Key。
3. 等待安装、预加载及 HTTPS 隧道启动，浏览器会下载 `inference.connection.local.json`。如果下载被阻止，从左侧文件浏览器的 `/content/Manual2ARLearningPerformanceV2/` 下载同名文件。
4. 将文件放到本地项目 `configs/inference.connection.local.json`，覆盖旧连接；浏览器追加的 `(1)` 等后缀要移除。重启本地后端，在 Unity 中重新识别，旧跟踪会话不能继续使用。
5. 使用期间保留 Colab 页面。实验结束后通过 Colab 菜单断开并删除运行时；停止 Python 服务不等于释放 GPU。

默认不挂载 Google Drive、不创建云盘缓存、不持续写入云盘日志；首次启动需要联网安装依赖和下载模型，等待可能较久。若要复用已有缓存，可勾选 `USE_DRIVE_CACHE`；若需要持续留存远端日志，可勾选 `PERSIST_REMOTE_LOGS`，两者均会请求 Drive 授权。

连接文件含访问令牌，请仅保存在本地 configs 中，不上传 Git、不发送到聊天。千问 API Key 仍保留在本地项目配置中，不上传至 Colab。

### 可选 Drive 缓存

`DRIVE_CACHE_ROOT` 默认沿用 `/content/drive/MyDrive/Manual2AR/cache-v1`。启用后校验并复制模型、锁定的 wheel 安装包到 Colab 本地磁盘，在本地安装和执行；不直接从 Drive 执行 venv。

首次建立环境缓存可能占用数 GB 至十几 GB 云盘空间。`CACHE_ENVIRONMENT=False` 仅缓存模型与配置；`FORCE_REBUILD_ENV=True` 仅在修复环境时使用，成功后恢复 False。

参数优先级：原始默认配置 → 已启用的 Drive 配置缓存 → 本次表单。令牌及临时服务地址不进入缓存；每次新运行时都需下载新的连接文件。现场图像不自动上传 Drive。

缓存只减少安装、下载等待，不保证零网络、秒开或避免 Colab 回收。手动启动也不承诺固定会话时长。
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
