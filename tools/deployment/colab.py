"""File-configured Colab orchestration for VS Code / WSL. No teaching API changes."""
import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path,PurePosixPath
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from urllib.parse import urlsplit

import httpx
from manual2ar.application.config import load as load_app,resolve
from manual2ar.paths import ROOT
from manual2ar_contracts.gpu import PROTOCOL
from tools.build.inference_bundle import gpu_bundle
from deploy.colab.worker import private_json

CLI_VERSION='0.7.5'


def load_config(path=None):
    path=Path(path or ROOT/'configs/colab.local.json')
    if not path.exists():
        private_json(path,json.loads((ROOT/'configs/colab.example.json').read_text()))
    c=json.loads(path.read_text());validate_config(c);return c


def validate_url(url):
    parsed=urlsplit(url)
    if (parsed.scheme not in ('https','http') or not parsed.netloc or parsed.username or parsed.password
        or parsed.query or parsed.fragment or parsed.path not in ('','/')):
        raise ValueError('GPU 地址必须是没有路径、凭据或查询参数的 HTTP(S) 地址')
    if parsed.scheme=='http' and parsed.hostname not in ('127.0.0.1','localhost','::1'):
        raise ValueError('公网 GPU 地址必须使用 HTTPS')
    return url.rstrip('/')


def validate_config(c):
    if c.get('schema_version')!='manual2ar-colab-v1':raise ValueError('Unsupported Colab configuration')
    if not re.fullmatch(r'[a-z][a-z0-9-]{0,47}',c['session_name']):raise ValueError('Invalid session_name')
    if c['gpu'] not in ('T4','L4','G4','A100','H100'):raise ValueError('Invalid GPU; no implicit hardware fallback')
    if c['auth'] not in ('oauth2','adc') or c['cli_version']!=CLI_VERSION:raise ValueError('Unsupported CLI/auth configuration')
    root=PurePosixPath(c['remote_root'])
    if root.parent!=PurePosixPath('/content') or root.name in ('drive','sample_data') or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]*',root.name):
        raise ValueError('remote_root must be a dedicated directory directly under /content')
    for key,lo,hi in [('startup_timeout_seconds',60,7200),('poll_seconds',1,60)]:
        if type(c[key]) is not int or not lo<=c[key]<=hi:raise ValueError('Invalid '+key)
    if c['public_url']:validate_url(c['public_url'])
    drive=c['drive_cache'];p=PurePosixPath(drive['path'])
    if set(drive)!={'enabled','path','cache_environment'}:raise ValueError('Unknown Drive cache field')
    if not p.is_relative_to('/content/drive/MyDrive') or '..' in p.parts:raise ValueError('Invalid Drive cache path')
    for key in ('enabled','cache_environment'):
        if type(drive[key]) is not bool:raise ValueError('Invalid Drive switch')
    infer=c['inference'];tune=infer['cutie']
    if set(infer)!={'precision','cutie','retain_initial_images'} or set(tune)!={'max_internal_size','mem_every','channels_last','compile_encoder'}:
        raise ValueError('Unknown inference option; credentials must not be uploaded')
    if infer['precision'] not in ('auto','float16','float32','bfloat16'):raise ValueError('Invalid precision')
    if tune['max_internal_size'] not in (-1,256,320,480,640) or tune['mem_every'] not in (5,10):raise ValueError('Invalid Cutie preset')
    for value in [infer['retain_initial_images'],tune['channels_last'],tune['compile_encoder']]:
        if type(value) is not bool:raise ValueError('Invalid inference switch')
    # No API key or service token belongs in the orchestration config.
    if set(c)-{'schema_version','session_name','gpu','auth','client_oauth_config','cli_version','remote_root',
               'startup_timeout_seconds','poll_seconds','public_url','drive_cache','inference'}:
        raise ValueError('Unknown Colab configuration field')


def redact(text,secrets=()):
    for value in secrets:
        if value:text=text.replace(value,'[REDACTED]')
    text=re.sub(r'(?i)(Bearer\s+)\S+',r'\1[REDACTED]',text)
    text=re.sub(r'(?i)([\"\']?(?:api_token|access_token|refresh_token|token|api_key)[\"\']?\s*[:=]\s*)[\"\']?[^\s,}\"\']+',r'\1[REDACTED]',text)
    text=re.sub(r'(https?://[^\s?]+)\?[^\s]+',r'\1?[REDACTED]',text)
    return text


def validate_connection(value):
    if value.get('protocol')!=PROTOCOL:raise ValueError('GPU 协议不匹配，保留原连接文件')
    validate_url(value['url']);token=value.get('api_token','')
    if not isinstance(token,str) or not 24<=len(token)<=512 or any(c.isspace() for c in token):
        raise ValueError('GPU 服务令牌无效')


def check_connection(value):
    validate_connection(value);token=value['api_token']
    with httpx.Client(timeout=20,follow_redirects=False) as client:
        response=client.get(value['url'].rstrip('/')+'/health',headers={'Authorization':'Bearer '+token})
        response.raise_for_status();health=response.json()
    if health.get('protocol')!=PROTOCOL or health.get('available') is not True:
        raise ValueError('GPU 服务尚不可用，保留原连接文件')
    return health


def install_connection(candidate,target,checker=check_connection):
    if candidate.stat().st_size>16384:raise ValueError('Connection file too large')
    value=json.loads(candidate.read_text());validate_connection(value);health=checker(value)
    if health.get('protocol')!=PROTOCOL or health.get('available') is not True:raise ValueError('GPU health is not ready')
    private_json(target,{k:value[k] for k in ['url','api_token','protocol']})
    return health


class CLI:
    def __init__(self,c,cache,log):
        self.config=c;self.cache=cache;self.log=log
        self.python=cache/'cli-venv/bin/python';self.state=cache/'sessions.json'

    def setup(self):
        lock=ROOT/'deploy/colab/requirements-cli.lock'
        fingerprint=hashlib.sha256(lock.read_bytes()).hexdigest()
        marker=self.cache/'cli-ready.json'
        if self.python.exists() and marker.is_file():
            saved=json.loads(marker.read_text())
            probe=subprocess.run([str(self.python),'-B','-c',"import importlib.metadata;print(importlib.metadata.version('google-colab-cli'))"],capture_output=True,text=True)
            if saved.get('lock_sha256')==fingerprint and probe.returncode==0 and probe.stdout.strip()==CLI_VERSION:return
        self.cache.mkdir(parents=True,exist_ok=True);self.cache.chmod(0o700)
        uv=shutil.which('uv')
        if uv:
            if not self.python.exists():subprocess.run([uv,'venv','--python','3.12',str(self.python.parents[1])],check=True)
            subprocess.run([uv,'pip','sync','--python',str(self.python),str(lock)],check=True)
        else:
            interpreter=shutil.which('python3.12')
            if not interpreter:raise RuntimeError('请先安装 Python 3.12 或 uv，再运行 Colab 初始化任务')
            if not self.python.exists():subprocess.run([interpreter,'-m','venv',str(self.python.parents[1])],check=True)
            subprocess.run([str(self.python),'-m','pip','install','-r',str(lock)],check=True)
        private_json(marker,{'cli_version':CLI_VERSION,'lock_sha256':fingerprint})

    def args(self,command):
        if not self.python.is_file():raise RuntimeError('先运行「Colab: 初始化工具」')
        args=[str(self.python),'-B','-m','colab_cli.cli','--auth',self.config['auth'],'--config',str(self.state)]
        if self.config['client_oauth_config']:
            args+=['--client-oauth-config',str(resolve(self.config['client_oauth_config']))]
        return args+command

    def run(self,command,timeout=90,interactive=False):
        args=self.args(command)
        if interactive:
            # OAuth codes are entered in the user's VS Code terminal, never logged.
            result=subprocess.run(args,check=False)
        else:
            result=subprocess.run(args,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                                  text=True,timeout=timeout)
            if result.returncode:
                self.log('CLI '+command[0]+' 失败：'+redact(result.stdout[-1800:]))
        for p in [self.state,Path.home()/'.config/colab-cli/token.json']:
            if p.is_file():p.chmod(0o600)
        if result.returncode:
            output=getattr(result,'stdout','') or ''
            if command[0]=='new' and ('Service Unavailable' in output or '503' in output):
                raise RuntimeError('Colab 当前无法分配 '+self.config['gpu']+' GPU（503 Service Unavailable）；请稍后重试。无需重新登录，不会自动升级 GPU')
            if 'appears to be lost (404/401)' in output:
                raise RuntimeError('本项目 Colab 运行时连接已失效，CLI 已清除失效记录；再次启动会申请新的运行时')
            raise RuntimeError('Colab '+command[0]+' 未完成；如需要授权，请运行「Colab: 登录 Google」。其他错误见本地日志。')
        return result

    def record(self):
        try:return json.loads(self.state.read_text()).get(self.config['session_name'])
        except FileNotFoundError:return None

    def execute(self,path,timeout=60):
        self.run(['exec','-s',self.config['session_name'],'-f',str(path),'--timeout',str(timeout)],timeout=timeout+30)

    def download(self,remote,local):
        self.run(['download','-s',self.config['session_name'],remote,str(local)])


def dispatch_script(root,archive,options):
    """Only audited inference source and non-secret deployment settings cross the boundary."""
    return '''import hashlib,importlib,json,os,pathlib,sys,zipfile
root=pathlib.Path('''+repr(root)+''')
archive=pathlib.Path('''+repr(archive)+''')
options='''+repr(options)+'''
root.mkdir(parents=True,exist_ok=True)
ack=root/'dispatch.json'
def dispatch():
    if hashlib.sha256(archive.read_bytes()).hexdigest()!=options['bundle_sha256']:
        raise ValueError('Bundle transport SHA mismatch')
    with zipfile.ZipFile(archive) as z:
        manifest=json.loads(z.read('bundle.manifest.json'))
        if set(z.namelist())!=set(manifest)|{'bundle.manifest.json'}:raise ValueError('Unexpected bundle members')
        for name,item in manifest.items():
            p=(root/name).resolve();p.relative_to(root.resolve())
            if name.startswith('/') or '..' in pathlib.PurePosixPath(name).parts:raise ValueError('Unsafe archive path')
            if (z.getinfo(name).external_attr>>16)&0o170000==0o120000:raise ValueError('Archive symlink rejected')
            if hashlib.sha256(z.read(name)).hexdigest()!=item['sha256']:raise ValueError('Bundle source SHA mismatch')
        if str(root) not in sys.path:sys.path.insert(0,str(root))
        if (root/'deploy/colab/worker.py').is_file():
            from deploy.colab import worker
            importlib.reload(worker)
            processes=worker.read(root/'worker-processes.local.json',{})
            state=worker.read(root/'status.json',{})
            same=all(state.get(k)==options[k] for k in ('bundle_sha256','options_sha256'))
            if worker.alive(processes.get('launcher')):
                if not same:raise RuntimeError('Another deployment is preparing; stop it first')
                return 'preparing'
            if same and state.get('state')=='ready' and worker.alive(processes.get('service')):
                if options['public_url'] or worker.alive(processes.get('tunnel')):
                    try:
                        if worker.api(root,'/health').get('available'):return 'reused'
                    except Exception:pass
            worker.stop(root)
        for name in z.namelist():
            p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(z.read(name))
    importlib.invalidate_caches()
    for name in list(sys.modules):
        if name=='deploy' or name.startswith('deploy.'):del sys.modules[name]
    from deploy.colab.worker import launch
    return launch(root,options)
try:
    result={'ok':True,'decision':dispatch(),'dispatch_id':options.get('dispatch_id','')}
except Exception as error:
    result={'ok':False,'error_type':type(error).__name__,'dispatch_id':options.get('dispatch_id','')}
ack.write_text(json.dumps(result));ack.chmod(0o600)
'''


class Orchestrator:
    def __init__(self,c,app=None,cli=None,checker=check_connection,clock=time.monotonic,sleep=time.sleep):
        self.c=c;self.app=app or load_app();self.checker=checker;self.clock=clock;self.sleep=sleep
        self.cache=resolve(self.app['paths']['cache'])/'colab';self.logs=resolve(self.app['paths']['runtime'])/'colab'
        for p in [self.cache,self.logs]:p.mkdir(parents=True,exist_ok=True);p.chmod(0o700)
        self.connection=resolve(self.app['gpu']['connection_file']);self.cli=cli or CLI(c,self.cache,self.log)

    def log(self,text):
        with (self.logs/'launcher.log').open('a') as stream:stream.write(redact(text)+'\n')

    def stage(self,state,message):
        print(message,flush=True);self.log(message)
        private_json(self.logs/'status.json',{'state':state,'message':message,'session':self.c['session_name']})

    def remote(self,name):return self.c['remote_root']+'/'+name

    @contextmanager
    def locked(self):
        with (self.cache/'operation.lock').open('a') as stream:
            try:fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:raise RuntimeError('本项目已有 Colab 操作进行中；可运行状态或日志任务查看')
            try:yield
            finally:fcntl.flock(stream,fcntl.LOCK_UN)

    def start(self):
        with self.locked():
            self.stage('checking','1/6 检查工具与 Google 授权…');self.cli.setup()
            self.cli.run(['sessions'])  # Refreshes/prunes stale assignments without allocating a runtime.
            record=self.cli.record()
            if record and record.get('accelerator')!=self.c['gpu']:
                raise RuntimeError('已有本项目会话的 GPU 与配置不同；请先明确释放该会话，再启动')
            if not record:
                self.stage('allocating','2/6 申请 '+self.c['gpu']+' GPU；不自动升级或购买算力…')
                self.cli.run(['new','-s',self.c['session_name'],'--gpu',self.c['gpu']],timeout=180)
                if not self.cli.record():raise RuntimeError('CLI 未记录成功分配的项目会话')
            else:self.stage('reusing','2/6 复用本项目现有 Colab 会话…')
            if self.c['drive_cache']['enabled']:
                self.stage('mounting','挂载 Drive 缓存；如出现 Google 授权，请在终端完成…')
                self.cli.run(['drivemount','-s',self.c['session_name']],interactive=True)
            self.stage('uploading','3/6 打包并上传推理源码；不上传 API Key、Wiki 或现场图片…')
            with tempfile.TemporaryDirectory(dir=self.cache,prefix='deploy-') as tmp:
                tmp=Path(tmp);bundle=gpu_bundle();remote_zip='/content/'+self.c['session_name']+'-source.zip'
                self.cli.run(['upload','-s',self.c['session_name'],str(bundle),remote_zip])
                options={k:self.c[k] for k in ['inference','drive_cache','public_url']}
                options['options_sha256']=hashlib.sha256(json.dumps(options,sort_keys=True).encode()).hexdigest()
                options['bundle_sha256']=hashlib.sha256(bundle.read_bytes()).hexdigest()
                options['dispatch_id']=uuid.uuid4().hex
                dispatch=tmp/'dispatch.py';dispatch.write_text(dispatch_script(self.c['remote_root'],remote_zip,options))
                self.cli.execute(dispatch)
                ack=tmp/'dispatch.json';self.cli.download(self.remote('dispatch.json'),ack)
                receipt=json.loads(ack.read_text())
                if receipt.get('dispatch_id')!=options['dispatch_id'] or not receipt.get('ok'):
                    raise RuntimeError('远端部署没有确认本次请求；可能有另一个部署进行中，请查看状态')
                self.stage('starting','4/6 远端准备环境、加载模型；首次安装可能较久…')
                deadline=self.clock()+self.c['startup_timeout_seconds'];last=None
                while self.clock()<deadline:
                    status_file=tmp/'status.json';self.cli.download(self.remote('status.json'),status_file)
                    if status_file.stat().st_size>16384:raise ValueError('Remote status too large')
                    state=json.loads(status_file.read_text())
                    if state['state']=='failed':
                        # Save diagnostics while the ephemeral runtime still exists.
                        private_json(self.logs/'remote-status.json',state)
                        try:self.collect_logs()
                        except Exception as error:self.log('自动收集日志未完成：'+redact(str(error)))
                        if state.get('error_message'):print('远端原因：'+redact(state['error_message'])[-4000:])
                        raise RuntimeError('远端在 '+state.get('stage','unknown')+' 阶段失败；详情见 '+str(self.logs))
                    if state['state']=='stopped':raise RuntimeError('远端服务已停止')
                    if state.get('stage')!=last:
                        last=state.get('stage');self.stage('starting','远端进度：'+str(last))
                    if state['state']=='ready':
                        if any(state.get(k)!=options[k] for k in ['bundle_sha256','options_sha256']):raise RuntimeError('收到另一版本的部署状态，拒绝覆盖连接')
                        break
                    self.sleep(self.c['poll_seconds'])
                else:raise TimeoutError('启动等待超时；远端任务可能仍在运行，再次启动会尝试复用，不会额外申请 GPU')
                self.stage('validating','5/6 自动获取连接文件并验证 GPU 协议与服务状态…')
                candidate=tmp/'inference.connection.local.json'
                self.cli.download(self.remote('inference.connection.local.json'),candidate);candidate.chmod(0o600)
                for attempt in range(4):
                    try:
                        install_connection(candidate,self.connection,self.checker);break
                    except (httpx.TransportError,httpx.HTTPStatusError) as error:
                        status=getattr(getattr(error,'response',None),'status_code',None)
                        if attempt==3 or (status is not None and status not in (502,503,504)):raise
                        self.stage('validating','等待新建 HTTPS 连接可达，再次检查…');self.sleep(3)
                private_json(self.logs/'installation.json',{'session':self.c['session_name'],
                    'connection_sha256':hashlib.sha256(self.connection.read_bytes()).hexdigest(),
                    'bundle_sha256':options['bundle_sha256']})
            self.stage('ready','6/6 GPU 就绪，连接文件已自动更新。请在 Unity 中重新开始识别；旧跟踪会话不可继续复用。')

    def status(self):
        print('本项目会话：'+self.c['session_name'])
        if not self.cli.record():print('本地没有本项目运行时记录；不会自动创建 GPU。');return
        self.cli.run(['status','-s',self.c['session_name']])
        if not self.cli.record():print('本项目运行时已回收；未自动重新分配。');return
        receipt=self.logs/'installation.json'
        current=hashlib.sha256(self.connection.read_bytes()).hexdigest() if self.connection.is_file() else None
        if not receipt.is_file() or json.loads(receipt.read_text()).get('connection_sha256')!=current:
            print('当前后端连接尚未确认为本次 Colab 部署；请启动 GPU，成功后会自动更新。');return
        if not self.connection.is_file():print('运行时存在，但尚未安装通过验证的服务连接。');return
        try:
            health=self.checker(json.loads(self.connection.read_text()))
            print('GPU HTTP 服务可用；模型已加载：'+str(health.get('models_loaded',False)))
        except Exception:print('GPU HTTP 服务暂不可达或尚未就绪；可查看日志或重新启动。')

    def stop_service(self):
        with self.locked():
            if not self.cli.record():print('没有本项目会话；未操作其他运行时。');return
            request_id=uuid.uuid4().hex
            with tempfile.TemporaryDirectory(dir=self.cache) as tmp:
                p=Path(tmp)/'stop.py'
                code="import pathlib,sys,json\nroot="+repr(self.c['remote_root'])+"\nrequest_id="+repr(request_id)
                code+="\nsys.path.insert(0,root)\nif (pathlib.Path(root)/'deploy/colab/worker.py').is_file():\n from deploy.colab.worker import stop\n stop(root)\n"
                code+="p=pathlib.Path(root)/'stop-receipt.json'\np.parent.mkdir(parents=True,exist_ok=True)\np.write_text(json.dumps({'request_id':request_id,'ok':True}));p.chmod(0o600)\n"
                p.write_text(code);self.cli.execute(p)
                receipt=Path(tmp)/'receipt.json';self.cli.download(self.remote('stop-receipt.json'),receipt)
                value=json.loads(receipt.read_text())
                if value.get('request_id')!=request_id or value.get('ok') is not True:
                    raise RuntimeError('远端没有确认本次停止请求；未报告服务已停止')
            self.stage('stopped','已停止本项目推理服务；Colab 运行时仍保留，释放请运行「停止并释放」任务。')

    def release(self):
        with self.locked():
            if not self.cli.record():print('没有本项目会话；未操作其他运行时。');return
            # Local records outlive recycled VMs. Reconcile before destructive calls.
            self.cli.run(['sessions'])
            if not self.cli.record():
                self.stage('released','服务器确认本项目运行时已不存在，已清理过期记录。');return
            try:
                self.cli.run(['stop','-s',self.c['session_name']],timeout=120)
            except (RuntimeError,subprocess.TimeoutExpired):
                # The VM may disappear between the check and unassign, or the
                # request may succeed despite a lost response. Verify, never guess.
                self.cli.run(['sessions'])
                if self.cli.record():raise
                self.stage('released','服务器确认本项目运行时已释放，已清理本地记录。');return
            self.cli.run(['sessions'])
            if self.cli.record():raise RuntimeError('CLI 仍保留本项目会话，未能确认运行时释放')
            self.stage('released','已请求释放本项目 Colab 运行时；临时文件与会话状态会随运行时删除。')

    def collect_logs(self):
        if not self.cli.record():raise RuntimeError('尚无本项目会话')
        secrets=[]
        if self.connection.is_file():
            try:secrets.append(json.loads(self.connection.read_text()).get('api_token',''))
            except ValueError:pass
        collected=[]
        with tempfile.TemporaryDirectory(dir=self.cache) as tmp:
            for name in ['status.json','launcher.log','bootstrap.log','service.log','tunnel.log']:
                p=Path(tmp)/name
                try:self.cli.download(self.remote(name),p)
                except RuntimeError:continue
                text=redact(p.read_text(errors='replace'),secrets)
                (self.logs/('remote-'+name)).write_text(text)
                collected.append(name)
                if name in ('status.json','launcher.log'):print(text[-4000:])
        if not collected:
            raise RuntimeError('未能获取任何远端日志；运行时可能已回收，或连接已失效。本地已有日志保留在 '+str(self.logs))
        print('脱敏日志：'+str(self.logs))


def main():
    os.umask(0o077)
    parser=argparse.ArgumentParser();parser.add_argument('command',choices=['setup','login','start','status','stop-service','release','logs']);parser.add_argument('--config',type=Path)
    args=parser.parse_args()
    try:
        if sys.platform!='linux':raise RuntimeError('请在 VS Code 的 WSL 窗口打开项目；官方 CLI 不支持原生 Windows')
        c=load_config(args.config);host=Orchestrator(c)
        if args.command=='setup':host.cli.setup();print('Colab 工具已安装；所有参数只需编辑 configs/colab.local.json。')
        elif args.command=='login':
            with host.locked():host.cli.setup();host.cli.run(['sessions'],interactive=True)
        else:getattr(host,{'stop-service':'stop_service','logs':'collect_logs'}.get(args.command,args.command))()
    except KeyboardInterrupt:
        print('本地等待已取消。远端可能仍在准备；再次启动可复用，或明确停止并释放。');raise SystemExit(130)
    except Exception as error:
        message='Colab 操作未完成：'+redact(str(error))
        if 'host' in locals():host.stage('failed',message)
        else:print(message,file=sys.stderr)
        raise SystemExit(1)

if __name__=='__main__':main()
