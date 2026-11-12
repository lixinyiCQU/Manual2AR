"""Copy beside baseline/tests/test_compiler.py; no GT, network or physical evidence."""
from copy import deepcopy
import json

import pytest

from manual2ar_baseline.compiler import compile_task
from manual2ar_baseline.provider import ModelError
from test_compiler import FakeClient, official_fixture


class SemanticTimeout(FakeClient):
    def call(self, prompt, schema, images):
        if 'task' not in schema.get('properties', {}):
            self.calls.append((prompt, len(images)))
            raise ModelError('Model connection failed or timed out')
        return super().call(prompt, schema, images)


class OneRepair(FakeClient):
    def call(self, prompt, schema, images):
        if not self.calls:
            self.calls.append((prompt, len(images)))
            return '{"not_a_proposal": true}', dict(model='controlled', usage={})
        return super().call(prompt, schema, images)


def test_valid_proposal_remains_reviewable_after_semantic_timeout(tmp_path):
    sources, root, proposal, catalog = official_fixture(tmp_path)
    output = tmp_path / 'candidate'
    client = SemanticTimeout(proposal)
    with pytest.raises(ModelError):
        compile_task(sources, root, {'method': 'independent-controlled-fixture'},
                     '安装控制夹具', catalog, client, output)
    assert len(client.calls) == 2
    assert json.loads((output / 'manifest.json').read_bytes())['status'] == 'failed'
    assert json.loads((output / 'proposal.json').read_bytes())['task'] == proposal['task']
    assert json.loads((output / 'task.json').read_bytes()) == proposal['task']
    assert (output / 'protocol.json').is_file()
    assert (output / 'compile-response-0.txt').is_file()
    assert (output / 'failure.json').is_file()


def test_uncovered_ar_preserves_successful_task_and_protocol(tmp_path):
    sources, root, proposal, catalog = official_fixture(tmp_path)
    proposal = deepcopy(proposal)
    proposal['presentations'] = []
    client = FakeClient(proposal)
    output = tmp_path / 'candidate'
    result = compile_task(sources, root, {'method': 'independent-controlled-fixture'},
                          '安装控制夹具', catalog, client, output)
    assert result['status'] == 'blocked'
    assert result['diagnostics'] == ['unsupported_ar_coverage']
    assert json.loads((output / 'task.json').read_bytes()) == proposal['task']
    assert json.loads((output / 'review.json').read_bytes())['semantic']['faithful'] is True
    assert (output / 'protocol.json').is_file()


def test_one_explicit_repair_has_three_calls_and_one_candidate(tmp_path):
    sources, root, proposal, catalog = official_fixture(tmp_path)
    client = OneRepair(proposal)
    output = tmp_path / 'candidate'
    result = compile_task(sources, root, {'method': 'independent-controlled-fixture'},
                          '安装控制夹具', catalog, client, output)
    assert result['status'] == 'experimental_ready'
    assert len(client.calls) == 3  # rejected compile, repaired compile, semantic
    assert len(list(output.glob('compile-response-*.txt'))) == 2
    assert len(list(output.glob('semantic-response-*.txt'))) == 1
    assert [p.name for p in tmp_path.glob('candidate*')] == ['candidate']
