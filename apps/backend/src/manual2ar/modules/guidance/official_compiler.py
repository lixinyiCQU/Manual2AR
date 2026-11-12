"""Compile pinned official evidence into isolated baseline runtimes, without GT inputs."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import shutil
import threading
import uuid
from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import Field

from manual2ar.paths import ROOT
from manual2ar_baseline.compiler import check_artifacts, compile_task, load_compilation, render_resources
from manual2ar_baseline.gt import Digest, Strict, digest
from manual2ar_baseline.provider import CompatibleClient, ModelError, Settings
from manual2ar_baseline.sources import retrieve
from .baseline_spatial import BaselineSpatial, install as install_spatial
from .spatial.service import atomic_json


class Compile(Strict):
    intent: str = Field(min_length=2, max_length=1000)


class Use(Strict):
    manifest_sha256: Digest
    acknowledge_experimental: Literal[True]


class OfficialCompiler:
    def __init__(self, app, config, registry, client, wiki_settings):
        self.app, self.config, self.registry, self.client = app, config, registry, client
        self.wiki_settings = wiki_settings
        self.root = Path(config['runtime_dir']) / 'official-compilation'
        self.lock = threading.RLock()
        self.executor = ThreadPoolExecutor(max_workers=1)
        self.jobs, self.runtimes = {}, {}
        self.compiler_client = None
        self.closed = False

    def view(self, identity):
        with self.lock:
            if identity not in self.jobs:
                raise HTTPException(404, '编译记录不在本次服务会话中。')
            value = dict(self.jobs[identity])
        folder = self.root / identity / 'candidate'
        if value['status'] in ('ready', 'blocked', 'active') and (folder / 'REVIEW.md').is_file():
            try:
                check_artifacts(folder, allow_blocked=True)
            except (OSError, ValueError):
                value.update(status='blocked', message='候选文件已改变或未完整封存，请重新生成。')
                return value
            value['preview'] = (folder / 'REVIEW.md').read_text()
            if value.get('diagnostics'):
                value['preview'] += '\n\n## 运行入口诊断\n' + '\n'.join('- ' + d for d in value['diagnostics'])
            value['manifest_sha256'] = digest((folder / 'manifest.json').read_bytes())
        return value

    def update(self, identity, **values):
        with self.lock:
            self.jobs[identity].update(values)
            atomic_json(self.root / identity / 'job.json', self.jobs[identity])

    def start(self, intent):
        if not self.wiki_settings:
            raise HTTPException(503, '尚未配置官方离线资料。')
        with self.lock:
            if self.closed:
                raise HTTPException(503, '服务正在关闭。')
            if len(self.jobs) >= 16:
                raise HTTPException(429, '本次会话的编译记录已达上限，请先保存审核资料后重启服务。')
            if any(j['status'] in ('queued', 'compiling') for j in self.jobs.values()):
                raise HTTPException(409, '请等待当前官方资料编译完成。')
            identity = uuid.uuid4().hex
            self.jobs[identity] = dict(id=identity, intent=intent, status='queued', message='等待检索官方完整章节。', gt_used_as_input=False)
            self.update(identity)
            self.executor.submit(self.run, identity)
        return self.view(identity)

    def run(self, identity):
        candidate = self.root / identity / 'candidate'
        try:
            self.update(identity, status='compiling', message='正在检索官方章节并编译、复核任务。')
            intent = self.jobs[identity]['intent']
            sources, source_root, retrieval = retrieve(self.wiki_settings['archive'],
                ROOT / 'resources/sources/bambu_wiki/manifest.json', intent, assembly_context=True)
            provider = self.compiler_client or CompatibleClient(Settings.model_validate(
                {k: self.config['vlm'][k] for k in Settings.model_fields if k in self.config['vlm']}), max_tokens=16000)
            result = compile_task(sources, source_root, retrieval, intent, ROOT / 'baseline/capabilities/v1.json', provider,
                candidate, ar_resources=render_resources(ROOT))
            if result['status'] != 'experimental_ready':
                self.update(identity, status='blocked', message='任务候选已保留，存在语义问题或能力缺口，不能进入执行。', diagnostics=result['diagnostics'])
                return
            # Validate actual asset capacity before offering an executable preview; do not rewrite the compiled graph.
            try:
                probe = BaselineSpatial(self.config, self.registry, self.client, compilation=candidate)
                probe.part_tracking.shutdown()
            except ValueError as error:
                self.update(identity, status='blocked', message='任务候选已保留，但现有 AR 不能执行其全部定义；请查看能力缺口。',
                    diagnostics=['runtime_binding:' + str(error)[:300]])
                return
            self.update(identity, status='ready', message='候选已生成，请阅读任务、条件和出处后选择是否试用。')
        except Exception as error:
            self.update(identity, status='blocked' if (candidate / 'manifest.json').is_file() else 'failed',
                message='未能取得可执行的官方任务候选；请明确操作目标或检查资料、模型及 AR 能力。未回退到 GT。', error_type=type(error).__name__)

    def use(self, identity, command):
        with self.lock:
            value = self.view(identity)
            if self.closed or value['status'] not in ('ready', 'active') or value.get('manifest_sha256') != command.manifest_sha256:
                raise HTTPException(409, '候选状态或指纹已改变，请重新阅读审核结果。')
            candidate = self.root / identity / 'candidate'
            try:
                load_compilation(candidate)
                if identity not in self.runtimes:
                    prefix = '/api/guidance/compiled/jobs/' + identity + '/spatial'
                    self.runtimes[identity] = install_spatial(self.app, self.config, self.registry, self.client, compilation=candidate, prefix=prefix)
                else:
                    self.runtimes[identity].check_definition()
                self.runtimes[identity].experiment_title = self.jobs[identity].get('provenance', {}).get('title', '')
                self.runtimes[identity].default_goal_intent = self.jobs[identity].get('intent', '')
                atomic_json(self.root / identity / 'preview-acknowledgement.json', dict(
                    manifest_sha256=command.manifest_sha256, scope='user_selected_experimental_preview_not_semantic_approval', acknowledge_experimental=True))
            except (OSError, ValueError):
                raise HTTPException(409, '候选或其来源不再满足执行契约。') from None
            self.update(identity, status='active', message='已打开独立的自动编译实验任务。', spatial_prefix='/api/guidance/compiled/jobs/' + identity + '/spatial')
            return self.view(identity)

    def import_candidate(self, candidate, *, identity, provenance, expected_sha256):
        """Copy an explicitly registered frozen candidate; no model call or re-sealing."""
        with self.lock:
            if self.closed:
                raise HTTPException(503, '服务正在关闭。')
            if digest((candidate / 'manifest.json').read_bytes()) != expected_sha256:
                raise HTTPException(409, '归档候选指纹已改变。')
            load_compilation(candidate)
            target = self.root / identity / 'candidate'
            if target.exists():
                if digest((target / 'manifest.json').read_bytes()) != expected_sha256:
                    raise HTTPException(409, '已导入的实验候选版本不一致。')
                load_compilation(target)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                temporary = target.parent / ('import-' + uuid.uuid4().hex)
                try:
                    shutil.copytree(candidate, temporary)
                    load_compilation(temporary)
                    if digest((temporary / 'manifest.json').read_bytes()) != expected_sha256:
                        raise ValueError('Candidate changed during import')
                    temporary.rename(target)
                finally:
                    if temporary.exists():
                        shutil.rmtree(temporary)
            if identity not in self.jobs:
                probe = BaselineSpatial(self.config, self.registry, self.client, compilation=target)
                probe.part_tracking.shutdown()
                self.jobs[identity] = dict(id=identity, status='ready', intent=provenance['intent'],
                    message='已装载原始自动生成候选，可进入现场实验。', gt_used_as_input=False, provenance=provenance)
                self.update(identity)
            return self.view(identity)

    def close(self):
        with self.lock:
            self.closed = True
        self.executor.shutdown(wait=False, cancel_futures=True)
        for service in self.runtimes.values():
            for identity in list(service.sessions):
                service.close(identity)
            service.part_tracking.shutdown()


def install(app, config, registry, client, wiki_settings):
    service = OfficialCompiler(app, config, registry, client, wiki_settings)
    api = APIRouter(prefix='/api/guidance/compiled/jobs', tags=['official-baseline-compilation'])
    @api.post('', status_code=202)
    def compile_official(command: Compile):
        return service.start(command.intent)
    @api.get('/{identity}')
    def status(identity: str):
        return service.view(identity)
    @api.get('/{identity}/review', response_class=PlainTextResponse)
    def review(identity: str):
        value = service.view(identity)
        return value.get('preview', value['message'])
    @api.post('/{identity}/use')
    def use(identity: str, command: Use):
        return service.use(identity, command)
    app.include_router(api)
    return service
