"""Repeated evaluation bookkeeping with controlled official fixtures; no network."""
from copy import deepcopy
import json

import pytest

import manual2ar_baseline.evaluation as evaluation
from manual2ar_baseline.gt import digest, encoded
from manual2ar_baseline.provider import Settings
from test_compiler import FakeClient, official_fixture
from test_compiler_stages import OneRepair, SemanticTimeout


def prepared(tmp_path, monkeypatch, *, repeats=3, wrong_source=False):
    sources, root, proposal, catalog = official_fixture(tmp_path)
    metadata = dict(method='independent-controlled-fixture', goal='安装夹具手柄',
                    source_url='https://wiki.bambulab.com/fixture', parent_heading=['安装夹具手柄'])
    monkeypatch.setattr(evaluation, 'retrieve', lambda *a, **k: (sources, root, deepcopy(metadata)))
    suite = tmp_path / 'suite.json'
    suite.write_bytes(encoded(dict(schema_version='baseline-transfer-suite-v1', id='controlled-suite', scope='controlled_not_physical',
        cases=[dict(id='fixture', split='unseen_device', device_id='fixture', device_path='/zh/fixture/', intent='安装夹具手柄',
                    expected_source_url='https://wiki.bambulab.com/wrong' if wrong_source else metadata['source_url'],
                    expected_heading=metadata['parent_heading'], scope_note='controlled fixture, no novelty claim') ])))
    archive, manifest = tmp_path / 'archive.json', tmp_path / 'manifest.json'
    archive.write_bytes(b'{}'); manifest.write_bytes(b'{}')
    settings = Settings(base_url='https://example.com/v1', model='controlled', api_key='secret-not-exported')
    folder = tmp_path / 'evaluation'
    evaluation.make_plan(suite, archive, manifest, catalog, settings, folder, repeats=repeats,
                         repo_root=evaluation.Path(__file__).resolve().parents[2])
    return folder, settings, proposal


def test_fixed_repeats_success_never_stops_early_and_repair_is_not_another_trial(tmp_path, monkeypatch):
    folder, settings, proposal = prepared(tmp_path, monkeypatch)
    clients = []
    def factory():
        client = OneRepair(proposal); clients.append(client); return client
    summary = evaluation.run_plan(folder, settings, client_factory=factory)
    value = summary['overall']
    assert len(clients) == 3 and [len(c.calls) for c in clients] == [3, 3, 3]
    assert value['vlm_compile_success'] == dict(numerator=3, denominator=3, rate=1.0)
    assert value['first_response_contract']['numerator'] == 0
    assert value['http_attempts'] == 9 and value['returned_model_calls'] == 9
    assert value['human_approval_given_review']['rate'] is None
    assert value['human_approved_over_scheduled']['rate'] is None
    assert value['human_review_coverage']['denominator'] == 3
    assert 'secret-not-exported' not in (folder / 'plan.json').read_text()
    evaluation.run_plan(folder, settings, client_factory=lambda: pytest.fail('Completed trial called twice'))


def test_compile_pass_ar_coverage_and_semantic_transport_are_separate(tmp_path, monkeypatch):
    folder, settings, proposal = prepared(tmp_path, monkeypatch, repeats=2)
    no_ar = deepcopy(proposal); no_ar['presentations'] = []
    clients = iter([FakeClient(no_ar), SemanticTimeout(proposal)])
    summary = evaluation.run_plan(folder, settings, client_factory=lambda: next(clients))
    value = summary['overall']
    assert value['vlm_compile_success']['numerator'] == 2
    assert value['ar_catalog_covered']['numerator'] == 1
    assert value['same_model_semantic_pass']['numerator'] == 1
    assert value['experimental_ready']['numerator'] == 0
    assert summary['rows'][1]['semantic_model_pass'] is None
    assert len(json.loads((folder / 'report/human-labels.json').read_bytes())['labels']) == 2


def test_wrong_retrieval_stays_in_scheduled_denominator_without_model_calls(tmp_path, monkeypatch):
    folder, settings, _ = prepared(tmp_path, monkeypatch, wrong_source=True)
    result = evaluation.run_plan(folder, settings, client_factory=lambda: pytest.fail('Wrong source sent to compiler'))
    value = result['overall']
    assert value['statuses'] == {'retrieval_failed': 3}
    assert value['vlm_compile_success']['denominator'] == 3
    assert value['vlm_compile_success_given_model_attempt']['rate'] is None
    assert result['retrieval_selection'] == dict(numerator=0, denominator=1, rate=0.0)


def test_interrupted_attempt_is_consumed_instead_of_silently_retried(tmp_path, monkeypatch):
    folder, settings, proposal = prepared(tmp_path, monkeypatch, repeats=2)
    (folder / 'trials/fixture.r01').mkdir(parents=True)
    result = evaluation.run_plan(folder, settings, client_factory=lambda: FakeClient(proposal))
    assert result['overall']['statuses'] == {'interrupted': 1, 'experimental_ready': 1}
    assert result['overall']['vlm_compile_success']['denominator'] == 2


def test_human_review_is_bound_to_task_and_plan_and_pending_is_not_failure(tmp_path, monkeypatch):
    folder, settings, proposal = prepared(tmp_path, monkeypatch, repeats=2)
    evaluation.run_plan(folder, settings, client_factory=lambda: FakeClient(proposal))
    labels = json.loads((folder / 'report/human-labels.json').read_bytes())
    labels['labels'][0].update(decision='approved', reviewer='independent-human', note='Checked original official instructions',
                              **dict.fromkeys(evaluation.RUBRIC, 'pass'))
    path = tmp_path / 'labels.json'; path.write_bytes(encoded(labels))
    value = evaluation.report(folder, tmp_path / 'rated-report', labels_path=path)['overall']
    assert value['human_approval_given_review'] == dict(numerator=1, denominator=1, rate=1.0)
    assert value['human_review_coverage'] == dict(numerator=1, denominator=2, rate=.5)
    assert value['human_approved_over_scheduled']['rate'] is None
    labels['labels'][0]['task_sha256'] = '0' * 64; path.write_bytes(encoded(labels))
    with pytest.raises(ValueError, match='sealed candidate'):
        evaluation.report(folder, tmp_path / 'invalid-report', labels_path=path)


@pytest.mark.parametrize('mutation', [lambda l: l.update(reviewer=''), lambda l: l.update(requirements='fail'), lambda l: l.update(note='')])
def test_invalid_approval_is_rejected(mutation):
    label = dict(trial_id='trial', compilation_manifest_sha256='0'*64, task_sha256='1'*64,
                 decision='approved', reviewer='human', note='reviewed', **dict.fromkeys(evaluation.RUBRIC, 'pass'))
    mutation(label)
    with pytest.raises(ValueError): evaluation.HumanLabel.model_validate(label)


def test_changed_evidence_and_changed_method_cannot_be_mixed(tmp_path, monkeypatch):
    folder, settings, proposal = prepared(tmp_path, monkeypatch, repeats=1)
    changed = settings.model_copy(update={'model': 'another-model'})
    with pytest.raises(ValueError, match='settings differ'):
        evaluation.run_plan(folder, changed)
    original = evaluation.implementation()
    monkeypatch.setattr(evaluation, 'implementation', lambda: {**original, 'state.py': 'changed'})
    with pytest.raises(ValueError, match='Implementation changed'):
        evaluation.run_plan(folder, settings)
    monkeypatch.setattr(evaluation, 'implementation', lambda: original)
    evaluation.run_plan(folder, settings, client_factory=lambda: FakeClient(proposal))
    (folder / 'trials/fixture.r01/compilation/task.json').write_bytes(b'{}')
    with pytest.raises(ValueError, match='evidence changed'):
        evaluation.report(folder, tmp_path / 'tampered-report')


def test_unstarted_evaluation_does_not_report_a_failure_rate(tmp_path, monkeypatch):
    folder, _, _ = prepared(tmp_path, monkeypatch)
    summary = evaluation.report(folder, tmp_path / 'before-run')
    assert summary['overall']['completed'] == 0
    assert summary['overall']['vlm_compile_success']['rate'] is None
    assert summary['at_least_one_contract_per_complete_case']['rate'] is None
    assert summary['complete_case_coverage']['numerator'] == 0


def test_interrupted_atomic_result_write_can_be_resumed_without_another_call(tmp_path, monkeypatch):
    folder, settings, _ = prepared(tmp_path, monkeypatch, repeats=1)
    trial = folder / 'trials/fixture.r01'
    trial.mkdir(parents=True)
    (trial / 'result.json.tmp').write_bytes(b'{"unfinished": true}')
    summary = evaluation.run_plan(folder, settings, client_factory=lambda: pytest.fail('Interrupted attempt retried'))
    assert summary['overall']['statuses'] == {'interrupted': 1}
    assert (trial / 'interrupted-result-1.json').read_bytes() == b'{"unfinished": true}'
    evaluation.verify_trial(trial, digest((folder / 'plan.json').read_bytes()))


def test_two_runners_cannot_consume_the_same_trial(tmp_path, monkeypatch):
    import fcntl
    folder, settings, _ = prepared(tmp_path, monkeypatch, repeats=1)
    with (folder / 'run.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(ValueError, match='running worker'):
            evaluation.run_plan(folder, settings, client_factory=lambda: pytest.fail('Concurrent trial started'))
