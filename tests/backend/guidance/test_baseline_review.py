"""Human review and archive imports: controlled labels, no real reviewer/model/camera."""
from copy import deepcopy
import json
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from manual2ar.application.config import for_module, load
from manual2ar.modules.guidance.server import create_app
from manual2ar.modules.guidance.baseline_review import BaselineReview
from manual2ar_baseline import evaluation
from manual2ar_baseline.gt import digest, encoded
from manual2ar_baseline.provider import Settings
from baseline.tests.test_compiler import FakeClient, official_fixture
from tests.backend.guidance.test_baseline_ar import NeverLegacyModel


API = '/api/guidance/reviews/controlled-review'


def review_archive(tmp_path, monkeypatch):
    tmp_path.mkdir(parents=True, exist_ok=True)
    sources, source_root, proposal, capabilities = official_fixture(tmp_path, count=2)
    url = sources.records[0].source_url
    monkeypatch.setattr(evaluation, 'retrieve', lambda *a, **k: (sources, source_root,
        dict(method='independent-controlled-fixture', source_url=url, parent_heading=['安装夹具手柄'], goal='安装夹具手柄')))
    suite = tmp_path / 'suite.json'
    suite.write_bytes(encoded(dict(schema_version='baseline-transfer-suite-v1', id='controlled-review', scope='controlled_not_human_evidence',
        cases=[dict(id='fixture', split='seen_control', device_id='controlled', device_path='/zh/a1-mini/', intent='安装夹具手柄',
                    expected_source_url=url, expected_heading=['安装夹具手柄'], scope_note='受控验证，不是实际审核') ])))
    settings = Settings(base_url='https://example.invalid/v1', model='controlled', api_key='not-a-real-key')
    folder = tmp_path / 'frozen'
    evaluation.make_plan(suite, source_root/'official.json', capabilities, capabilities, settings, folder,
                         repeats=2, repo_root=Path(__file__).resolve().parents[3])
    evaluation.run_plan(folder, settings, client_factory=lambda: FakeClient(proposal))
    (folder/'evidence-manifest.json').write_bytes(encoded(dict(files=evaluation.files(folder))))
    spec = dict(id='controlled-review', title='受控审核验证', folder='frozen',
        plan_sha256=digest((folder/'plan.json').read_bytes()), archive_manifest_sha256=digest((folder/'evidence-manifest.json').read_bytes()),
        experiment_trials=['fixture.r01','fixture.r02'])
    return folder, spec


@pytest.fixture
def setup(tmp_path, monkeypatch):
    folder, spec = review_archive(tmp_path/'archive', monkeypatch)
    config = for_module(load(),'guidance');config['runtime_dir']=str(tmp_path/'runtime')
    app = create_app(config, NeverLegacyModel())
    service = app.state.baseline_review;service.specs=[];service.register(folder,spec)
    original = evaluation.files(folder)
    with TestClient(app) as client:
        yield client,service,app,folder,config
    assert evaluation.files(folder)==original


def submission(candidate, *, verdict='approved'):
    label = deepcopy(candidate['label'])
    label.update(reviewer='controlled-test-not-real-review',note='Synthetic review regression',decision=verdict,
                 **dict.fromkeys(evaluation.RUBRIC,'pass'))
    if verdict=='rejected':label['requirements']='fail'
    return dict(plan_sha256=candidate['plan_sha256'],revision=candidate['revision'],label=label)


def test_reviewable_list_original_sources_and_pinned_images(setup):
    client,_,_,_,_=setup
    catalog=client.get('/api/guidance/reviews').json()
    assert catalog['contract']=='baseline-review-v1' and catalog['plans'][0]['human_rate']=='未评价'
    listing=client.get(API).json();assert listing['scheduled']==2 and listing['reviewed']==0
    value=client.get(API+'/trials/fixture.r01').json()
    assert value['contract_pass'] and value['can_experiment'] and '2 颗 M3-8' in value['official_text']
    assert '夹具手柄' in value['text'] and '视觉：' in value['text']
    picture=value['images'][0];raw=client.get(picture['url'])
    assert raw.status_code==200 and digest(raw.content)==picture['sha256']
    assert client.get(API+'/trials/fixture.r01/images/official-missing.jpg').status_code==404
    assert client.get(API+'/trials/not-a-trial').status_code==404


def test_labels_persist_export_and_do_not_modify_frozen_results(setup):
    client,service,app,folder,config=setup
    value=client.get(API+'/trials/fixture.r01').json()
    response=client.post(API+'/trials/fixture.r01/review',json=submission(value))
    assert response.status_code==200,response.text
    assert response.json()['reviewed']==1 and response.json()['approved']==1
    assert response.json()['human_rate']=='100%'
    fresh=BaselineReview(config,app.state.official_compiler);fresh.specs=[];fresh.register(folder,service.plans['controlled-review']['spec'])
    assert fresh.candidate('controlled-review','fixture.r01')['label']['decision']=='approved'
    exported=client.post(API+'/export').json()
    assert exported['labels']['labels'][0]['decision']=='approved'
    assert exported['labels']['labels'][1]['decision']=='pending'
    assert Path(exported['path'],'human-labels.json').exists()
    assert json.loads((folder/'report/human-labels.json').read_bytes())['labels'][0]['decision']=='pending'


def test_stale_window_wrong_binding_and_invalid_approval_are_rejected(setup):
    client,service,_,_,_=setup
    value=client.get(API+'/trials/fixture.r01').json();body=submission(value)
    for key in ('task_sha256','compilation_manifest_sha256'):
        wrong=deepcopy(body);wrong['label'][key]='0'*64
        assert client.post(API+'/trials/fixture.r01/review',json=wrong).status_code==409
    wrong=deepcopy(body);wrong['label']['requirements']='pending'
    assert client.post(API+'/trials/fixture.r01/review',json=wrong).status_code==422
    assert client.post(API+'/trials/fixture.r01/review',json=body).status_code==200
    assert client.post(API+'/trials/fixture.r01/review',json=body).status_code==409
    latest=client.get(API+'/trials/fixture.r01').json()
    assert client.post(API+'/trials/fixture.r01/review',json=submission(latest,verdict='rejected')).status_code==200
    assert len(list((service.root/'controlled-review/history').glob('*.json')))==2


def test_both_registered_candidates_enter_separate_unknown_sessions_without_compiling(setup):
    client,_,app,folder,_=setup
    manager=app.state.official_compiler
    class NoCompile:
        def call(self,*args):raise AssertionError('Archive activation called model')
    manager.compiler_client=NoCompile()
    jobs=[]
    for trial in ('fixture.r01','fixture.r02'):
        value=client.get(API+'/trials/'+trial).json()
        command=dict(plan_sha256=value['plan_sha256'],manifest_sha256=value['compilation_manifest_sha256'],acknowledge_experimental=True)
        used=client.post(API+'/trials/'+trial+'/use',json=command)
        assert used.status_code==200,used.text
        jobs.append(used.json()['id']);prefix=used.json()['spatial_prefix']
        config=client.get(prefix+'/config').json()
        assert config['task_sha256']==value['task_sha256'] and config['task_origin']=='automatic_official_compilation'
        session=client.post(prefix+'/sessions',json=dict(camera_id='controlled-review',mode='camera',visual_client_revision='machine-workframe-v1'))
        assert session.status_code==201,session.text
        assert session.json()['execution']['baseline_mode']=='request_view'
        assert (manager.root/jobs[-1]/'candidate/manifest.json').read_bytes()==(folder/'trials'/trial/'compilation/manifest.json').read_bytes()
    assert len(set(jobs))==2 and client.get(API).json()['reviewed']==0


def test_changed_archive_and_changed_import_are_blocked(setup):
    client,_,app,folder,_=setup
    value=client.get(API+'/trials/fixture.r01').json()
    command=dict(plan_sha256=value['plan_sha256'],manifest_sha256=value['compilation_manifest_sha256'],acknowledge_experimental=True)
    used=client.post(API+'/trials/fixture.r01/use',json=command).json()
    target=app.state.official_compiler.root/used['id']/'candidate/task.json'
    target.write_bytes(b'{}')
    assert client.post(API+'/trials/fixture.r01/use',json=command).status_code==409
    original=(folder/'trials/fixture.r01/compilation/task.json').read_bytes()
    try:
        (folder/'trials/fixture.r01/compilation/task.json').write_bytes(b'{}')
        assert client.get(API+'/trials/fixture.r01').status_code==409
    finally:(folder/'trials/fixture.r01/compilation/task.json').write_bytes(original)
