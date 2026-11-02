"""Self-contained shared GPU service; excludes local keys and experiment data."""
import base64
import json
import zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]


from .inference_bundle import gpu_bundle

def build():
    cells=[]
    def md(text):cells.append(dict(cell_type='markdown',metadata={},source=text.splitlines(True)))
    def code(text):cells.append(dict(cell_type='code',metadata={},execution_count=None,outputs=[],source=text.splitlines(True)))
    md('''# Manual2AR 共享视觉：SAM3.1 + Cutie 持续会话服务

选择 NVIDIA GPU 运行时，然后 Run all。Notebook 自动准备独立 Python3.12、SAM3.1 FP16首帧初始化、Cutie Mega；T4默认使用Cutie FP16，可切换FP32做对照。无需私有仓库、千问Key或Hugging Face授权。本服务与旧跟踪对比服务协议不同，支持一个会话内的多目标持续记忆：首帧SAM3.1分割，之后每个新帧仅运行Cutie。模型在服务进程内常驻，会话记忆相互独立，闲置5分钟释放。

服务源码已内嵌。下载新连接文件放到本地 `configs/inference.connection.local.json`，在共享视觉选择 SAM3.1 + Cutie。只有本地主动识别、跟踪时才上传图像；GPU日志默认记录指纹、面积、耗时和错误，不保存原图。静态图片也可识别分割，但不模拟运动。

Runpod可填已有Pod的HTTP8021 HTTPS代理地址；本笔记本不申请或停止收费资源。''')
    code('''PUBLIC_GPU_URL = ""  # @param {type:"string"}
CUTIE_PRECISION = "auto"  # @param ["auto", "float32", "float16", "bfloat16"]
CUTIE_SHORT_SIDE = -1  # @param [-1, 320, 256]
CUTIE_MEM_EVERY = 5  # @param [5, 10]
CHANNELS_LAST = False  # @param {type:"boolean"}
COMPILE_ENCODER = False  # @param {type:"boolean"}
RETAIN_INITIAL_IMAGES = False  # @param {type:"boolean"}
# Colab留空自动创建临时隧道；Runpod填 https://<POD_ID>-8021.proxy.runpod.net
''')
    encoded=base64.b64encode(gpu_bundle().read_bytes()).decode()
    code('''import base64,io,json,os,pathlib,sys,zipfile
BASE=pathlib.Path('/content/Manual2ARLearningPerformanceV2') if pathlib.Path('/content').exists() else pathlib.Path.cwd()/'Manual2ARLearningPerformanceV2'
BASE.mkdir(parents=True,exist_ok=True)
SOURCE_ZIP="'''+encoded+'''"
with zipfile.ZipFile(io.BytesIO(base64.b64decode(SOURCE_ZIP))) as archive:archive.extractall(BASE)
required=['manual2ar_inference/engines/sam31_sources.json','configs/inference.example.json','deploy/common/requirements.txt','manual2ar_inference/engines/sam31_image.py','deploy/common/weights.py']
missing=[name for name in required if not (BASE/name).is_file()]
if missing:raise RuntimeError('Notebook源码包缺少文件，请重新下载新版笔记本：'+', '.join(missing))
os.chdir(BASE)
config_path=BASE/'configs/inference.local.json'
if not config_path.exists():
    config_path.write_bytes((BASE/'configs/inference.example.json').read_bytes())
config_path.chmod(0o600)
config=json.loads(config_path.read_text())
config['precision']=CUTIE_PRECISION
config['cutie'].update(max_internal_size=int(CUTIE_SHORT_SIDE),mem_every=int(CUTIE_MEM_EVERY),channels_last=CHANNELS_LAST,compile_encoder=COMPILE_ENCODER)
config['retain_initial_images']=RETAIN_INITIAL_IMAGES
config_path.write_text(json.dumps(config,indent=2))
print('源码与性能参数已准备；模型固定SAM3.1 + Cutie。')
''')
    code('''import shutil
from deploy.colab.environment import prepare_environment,run_logged,child_environment
(BASE/'bootstrap.log').write_text('Notebook Python: '+sys.version+'\\n')
try:
    if not shutil.which('nvidia-smi'):raise RuntimeError('请先选择NVIDIA GPU运行时。')
    GPU_PYTHON=prepare_environment(BASE)
    run_logged([GPU_PYTHON,'-u','-m','deploy.common.bootstrap'],BASE,'Install shared Cutie service')
except Exception:
    print('安装失败，实际错误及最后输出见上方；完整日志在 bootstrap.log。')
    try:
        from google.colab import files
        files.download(str(BASE/'bootstrap.log'))
    except Exception:print('可从左侧文件浏览器下载 bootstrap.log。')
    raise
''')
    code('''import subprocess,time,urllib.request
if 'service' in globals() and service is not None and service.poll() is None:
    service.terminate();service.wait(timeout=15)
config=json.loads(config_path.read_text())
service_log=open(BASE/'gpu_service.log','w')
service=subprocess.Popen([GPU_PYTHON,'-u','-m','manual2ar_inference.app','--config',str(config_path),'--work-dir',str(BASE)],env=child_environment(),stdout=service_log,stderr=subprocess.STDOUT)
health=None
for _ in range(120):
    if service.poll() is not None:raise RuntimeError('服务退出，请查看 gpu_service.log。')
    try:
        request=urllib.request.Request('http://127.0.0.1:'+str(config['port'])+'/health',headers={'Authorization':'Bearer '+config['api_token']})
        with urllib.request.urlopen(request,timeout=2) as response:health=json.load(response)
        break
    except Exception:time.sleep(.5)
if health is None:raise RuntimeError('服务未就绪，请查看 gpu_service.log。')
if not health.get('available'):raise RuntimeError('GPU模型不可用：'+str(health.get('reason')))
print(json.dumps(health,ensure_ascii=False,indent=2))
warm_request=urllib.request.Request('http://127.0.0.1:'+str(config['port'])+'/v1/warmup',data=b'{}',headers={'Authorization':'Bearer '+config['api_token'],'Content-Type':'application/json'})
with urllib.request.urlopen(warm_request,timeout=300) as response:warm=json.load(response)
print('Cutie权重已预加载；首次SAM3.1初始化、CUDA内核和可选编译仍有冷启动。',round(warm['model_load_ms']),'ms')
''')
    code('''import re
if 'tunnel' in globals() and tunnel is not None and tunnel.poll() is None:tunnel.terminate()
tunnel=None
if PUBLIC_GPU_URL:
    public_url=PUBLIC_GPU_URL.rstrip('/')
else:
    binary=BASE/'cloudflared'
    if not binary.exists():
        urllib.request.urlretrieve('https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64',binary)
        binary.chmod(0o700)
    tunnel_log_path=BASE/'tunnel.log';tunnel_log=open(tunnel_log_path,'w')
    tunnel=subprocess.Popen([str(binary),'tunnel','--url','http://127.0.0.1:'+str(config['port']),'--no-autoupdate'],stdout=tunnel_log,stderr=subprocess.STDOUT)
    public_url=None
    for _ in range(120):
        match=re.search(r'https://[a-z0-9-]+\\.trycloudflare\\.com',tunnel_log_path.read_text(errors='replace'))
        if match:public_url=match.group(0);break
        if tunnel.poll() is not None:break
        time.sleep(.5)
    if not public_url:raise RuntimeError('临时隧道失败，请查看 tunnel.log。')
connection=BASE/'cutie.connection.local.json'
connection.write_text(json.dumps(dict(url=public_url,api_token=config['api_token'],protocol='manual2ar-learning-cutie-v2'),indent=2));connection.chmod(0o600)
print('服务地址：',public_url)
print('将连接文件放在本地 configs/inference.connection.local.json；不要提交Git或公开token。')
try:
    from google.colab import files
    files.download(str(connection))
except ImportError:print('请从Jupyter文件浏览器下载 cutie.connection.local.json。')
''')
    md('''## 使用与停止

本地：`bash run.sh start`，Unity打开Welcome场景，选择CPU或SAM3.1+Cutie，启动摄像头/加载静态图，再点击识别。重新识别、清除、切换输入或引擎会关闭旧会话。云端异常不回退CPU；请查看本次诊断日志。

首次模型加载会比较慢。当前使用无积压的顺序会话，Unity实时预览独立刷新；标签图单独更新，超过配置年龄即隐藏。configs/app.local.json的performance.preview_mode可选live或paired；paired只用于检查同帧对齐。云端延迟仍限制结果更新率，尚未承诺端到端实时性能。

默认保持原始尺寸、每5帧更新记忆。480不会缩小640×360录像；320/256、channels_last、编码器编译、记忆间隔10须逐项验证质量。更改参数后Run all下载新连接文件。GPU日志包含H2D、CUDA计时、D2H、显存、图像解码、标签图编码；本地性能报告加入往返及Unity回执。

停止下方服务后，Colab还需断开并删除运行时；Runpod还需在平台停止/终止Pod，关闭服务不等于停止资源计费。''')
    code('''STOP_SERVICE=False  # @param {type:"boolean"}
if STOP_SERVICE:
    service.terminate()
    if tunnel is not None:tunnel.terminate()
    print('已请求停止服务；请在平台另行确认GPU资源状态。')
''')
    value=dict(cells=cells,metadata=dict(colab=dict(name='Manual2AR_Learning_Cutie_GPU.ipynb',provenance=[]),accelerator='GPU',
        kernelspec=dict(display_name='Python 3',language='python',name='python3')),nbformat=4,nbformat_minor=5)
    path=Path(__import__('tempfile').gettempdir())/'Manual2AR-GPU-base.ipynb';path.write_text(json.dumps(value,ensure_ascii=False,indent=1),encoding='utf-8')
    for cell in cells:
        if cell['cell_type']=='code':compile(''.join(cell['source']),str(path),'exec')
    print(path)


if __name__=='__main__':build()
