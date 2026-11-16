"""Cache provenance is an evaluation boundary, independent of model quality."""
from pathlib import Path

import pytest

from manual2ar_baseline.gt import digest, encoded
from manual2ar_baseline.photos import seal
from tools.evaluation.online_planning import inventory, manual_receipt, run


def cached(root, name, *, provider='compatible_http', status='success', accepted=False):
    folder=root/'runs/baseline'/name;folder.mkdir(parents=True)
    request=dict(kind='photo_observation',provider_kind=provider,session_id='session',task_sha256='a'*64,
                 epoch=0,revision=0,capture_sha256='b'*64,source_sha256='c'*64)
    for filename,value in [('request.json',request),('session.json',{}),('protocol.json',{}),('plan.json',{}),
                           ('evaluated.json',{'readings':{}})]:
        (folder/filename).write_bytes(encoded(value))
    seal(folder,status)
    if accepted:
        (folder.parent/'acceptance.json').write_bytes(encoded(dict(accepted=True,
            input_stamp={k:request[k] for k in ['session_id','task_sha256','epoch','revision']},
            capture_sha256=request['capture_sha256'],observation_manifest_sha256=digest((folder/'manifest.json').read_bytes()))))
    return folder


def test_inventory_excludes_presets_controls_and_derived_copies_and_requires_receipts(tmp_path):
    cached(tmp_path,'host/check/observation',accepted=True)
    cached(tmp_path,'standalone')
    cached(tmp_path,'failed/check/observation',status='failed',accepted=True)
    cached(tmp_path,'u7-demo/photo/observation',accepted=True)
    cached(tmp_path,'reviews/copied')
    cached(tmp_path,'controlled',provider='controlled_provider')
    records,counts,excluded=inventory(tmp_path)
    assert len(records)==3 and sum(r['accepted'] for r in records)==1
    failed=next(r for r in records if r['status']=='failed')
    assert not failed['accepted'] and failed['integrity']=='not_successful'
    assert {r['reason'] for r in excluded}=={'demo_excluded','derived_review_copy','controlled_provider'}
    assert counts['all_photo_requests']==6


def test_changed_cache_bytes_cannot_be_replayed_as_accepted(tmp_path):
    folder=cached(tmp_path,'host/check/observation',accepted=True)
    (folder/'evaluated.json').write_text('{"readings":{"forged":true}}')
    records,_,_=inventory(tmp_path)
    assert records[0]['integrity']=='ValueError' and not records[0]['accepted']


def test_manual_snapshot_needs_matching_host_acceptance_and_post_revision():
    event=dict(kind='manual',session_id='session',task_sha256='a'*64,epoch=1,revision=2,values={'secure':'true'})
    snapshot=dict(events=[event])
    telemetry=[dict(event='baseline.manual.accepted',condition_ids=['secure'],
                    execution=dict(session_id='session',task_sha256='a'*64,epoch=1,revision=3))]
    assert manual_receipt(snapshot,telemetry)
    telemetry[0]['execution']['revision']=2
    assert not manual_receipt(snapshot,telemetry)
    telemetry[0]['execution']['revision']=3;telemetry[0]['execution']['session_id']='other'
    assert not manual_receipt(snapshot,telemetry)


def test_frozen_plan_rejects_changed_inputs_before_running_methods(tmp_path):
    artifact=tmp_path/'input.json';artifact.write_text('{}')
    (tmp_path/'plan.json').write_bytes(encoded(dict(data_root=str(tmp_path),input_sha256={str(artifact):digest(artifact.read_bytes())})))
    (tmp_path/'plan.sha256').write_text(digest((tmp_path/'plan.json').read_bytes()))
    artifact.write_text('[]')
    with pytest.raises(ValueError,match='Frozen input changed'):run(tmp_path)


def test_frozen_plan_cannot_silently_change_its_denominator(tmp_path):
    plan=tmp_path/'plan.json';plan.write_text('{"records":[]}')
    (tmp_path/'plan.sha256').write_text(digest(plan.read_bytes()))
    plan.write_text('{"records":[{}]}')
    with pytest.raises(ValueError,match='Frozen plan changed'):run(tmp_path)
