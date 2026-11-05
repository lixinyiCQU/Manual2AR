"""Export only standard-library diagnostics; no model runtime or credentials."""
import base64
import io
import json
from pathlib import Path
import zipfile
from deploy.colab.diagnostics import SUITES

ROOT=Path(__file__).resolve().parents[2]
SOURCES=('deploy/__init__.py','deploy/common/files.py','deploy/colab/environment.py',
         'deploy/colab/worker.py','deploy/colab/retention.py','deploy/colab/diagnostics.py')


def bundle_bytes():
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED) as archive:
        for name in SOURCES:archive.writestr(zipfile.ZipInfo(name,date_time=(1980,1,1,0,0,0)),(ROOT/name).read_bytes(),compress_type=zipfile.ZIP_DEFLATED)
    return stream.getvalue()


def build(destination=None):
    cells=[]
    def cell(kind,text):
        value={'cell_type':kind,'metadata':{},'source':text.splitlines(True)}
        if kind=='code':compile(text,'diagnostics-notebook','exec');value.update(execution_count=None,outputs=[])
        cells.append(value)
    cell('markdown','''# Manual2AR：无模型会话终止诊断

选择 T4 后 Run all。只记录真实遥测、系统内存与 GPU 状态，不安装或加载 SAM/Cutie，不开 HTTP 服务或隧道。
先在当前 Workspace 运行任务「Colab: 无模型诊断实验」，与本笔记本使用同一份诊断代码。参数在 configs/colab.local.json 的 diagnostics 中设置。

默认观察 30 分钟，采集进程在后台运行，Notebook 单元会返回；不会执行伪计算、模拟点击或保活循环。
请保持实验条件一致：不要在同一运行时启动其他工作，也不要中途手动删除它。另行记录启动途径（网页或 CLI）。
Google Drive 会请求本人授权。运行时被删除后重新挂载 Drive，查看每次实验目录的 latest.json、observations.jsonl 和 end.json。
缺少 end.json 只说明没有记录到正常结束，不能单独证明平台杀进程；断电、Drive 写入失败等也可能导致记录缺失。
''')
    cell('code','''SUITE = "session_lifecycle"  # @param ["session_lifecycle"]
DURATION_MINUTES = 30  # @param {type:"integer"}
SAMPLE_SECONDS = 15  # @param {type:"integer"}
DRIVE_LOG_ROOT = "/content/drive/MyDrive/Manual2AR/logs"  # @param {type:"string"}
'''.replace('["session_lifecycle"]',json.dumps(list(SUITES))))
    encoded=base64.b64encode(bundle_bytes()).decode()
    cell('code','''import base64,io,os,pathlib,sys,zipfile,json
from google.colab import drive
drive.mount('/content/drive')
ROOT=pathlib.Path('/content/Manual2ARDiagnostics')
ROOT.mkdir(parents=True,exist_ok=True)
PAYLOAD="'''+encoded+'''"
with zipfile.ZipFile(io.BytesIO(base64.b64decode(PAYLOAD))) as archive:archive.extractall(ROOT)
os.chdir(ROOT)
sys.path.insert(0,str(ROOT))
from deploy.colab.diagnostics import launch
settings={'suite':SUITE,'duration_minutes':DURATION_MINUTES,'sample_seconds':SAMPLE_SECONDS}
result=launch(ROOT,settings,{'enabled':True,'path':DRIVE_LOG_ROOT,'interval_seconds':SAMPLE_SECONDS})
print(json.dumps(result,ensure_ascii=False,indent=2))
print('观察已在后台开始；本单元返回不是测试结束。请查看 Drive 中该实验目录。')
''')
    cell('markdown','''## 查看结果与解释

下方单元可手动再次运行查看最新状态；Run all 不会等待 30 分钟。
`end.json: duration_completed` 表示记录器达到预定时长；`signal_15` 表示记录到 SIGTERM，不能据此判断发起者。
运行时突然消失时，最多可能丢失最后一个采集周期以及 Drive 尚未落盘的数据，平台不一定提供终止原因。
把本实验与加载模型的业务会话对比，可缩小模型/显存问题与运行时平台策略的范围，不是保活方案。
观察完成不会自动释放 GPU，请在 Colab 删除运行时，或通过 Workspace 的「Colab: 释放诊断运行时」任务释放 CLI 创建的诊断实例。
后续诊断通过 deploy/colab/diagnostics.py 的 SUITES 增加命名诊断项，复用同一份留存与导出流程。
''')
    cell('code',"print((ROOT/'retention-status.json').read_text())\n")
    value={'nbformat':4,'nbformat_minor':5,'metadata':{'accelerator':'GPU',
        'colab':{'name':'Manual2AR_Diagnostics.ipynb'},'kernelspec':{'display_name':'Python 3','language':'python','name':'python3'}},'cells':cells}
    if destination is None:
        from manual2ar.application.config import load,resolve
        destination=resolve(load()['paths']['builds'])/'Manual2AR_Diagnostics.ipynb'
    target=Path(destination);target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(value,ensure_ascii=False,indent=1)+'\n');return target

if __name__=='__main__':print(build())
