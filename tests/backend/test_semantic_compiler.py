"""Same runtime contract, different devices/sources; no live models, network or private archive."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from manual2ar.knowledge.extract import extract
from manual2ar.knowledge.compilation.source import select,fingerprint
from manual2ar.knowledge.compilation.models import DraftGraph,DraftObservations
from manual2ar.knowledge.compilation.compiler import Compiler,check_graph,check_observations,load_example
from manual2ar.modules.guidance.task import TaskPackage


def claim(text,origin='explicit'):
    return dict(text=text,origin=origin,citation_ids=['c1'],rationale='依据原文，策略性表述另行审核')


def graph():
    return dict(states=[dict(action_id='open',instruction=claim('打开设备盖板'),preconditions=[],
        postconditions=[claim('盖板处于打开位置','inferred')],wrong_states=[claim('盖板仍然关闭','inferred')],
        target_components=['source:盖板'],warnings=[claim('请勿触碰内部导轨')])],limitations=[])


def observations():
    return dict(observations=[dict(action_id='open',postcondition_index=0,component_ids=['source:盖板'],viewpoint='front',
        capture_instruction=claim('从正面拍清盖板','observation_policy'),evidence_type='position',visualization='box',
        verification_channel='vision',requires_same_frame=False,visibility_limit=claim('遮挡或模糊时返回不确定','observation_policy'))])


def bundle():
    value=dict(schema_version='manual2ar-compiler-source-v1',archive_sha256='archive',pages=[],images=[],omitted_images=0,
        evidence={'c1':dict(citation_id='c1',text='打开盖板。请勿触碰内部导轨。',heading_path=['开启盖板'],
            source_url='https://example.com/manual',body_sha256='body',snapshot_id='snapshot',captured_at='date')})
    value['revision']=fingerprint(value);return value


REQUEST=dict(device_id='test_equipment',device_name='测试设备',task_id='open_cover',title='打开盖板',applicability='测试版本')
SETTINGS=dict(model='fake-model',temperature=0)


class Fake:
    def __init__(self,replies):self.replies=list(replies);self.calls=[]
    def chat_structured(self,**kwargs):
        self.calls.append(kwargs);return deepcopy(self.replies.pop(0))


def compiled(tmp_path,mode='staged'):
    g=graph();o=observations()
    replies=[{**g,**o}] if mode=='direct' else [dict(actions=[dict(action_id='open',instruction=claim('打开设备盖板'),target_components=['source:盖板'])],limitations=[]),g,o]
    fake=Fake(replies);folder=tmp_path/mode
    Compiler(fake,SETTINGS).compile(bundle(),REQUEST,folder,mode)
    return folder,fake


@pytest.mark.parametrize('mode',['direct','staged'])
def test_both_modes_export_existing_task_contract_with_lineage(tmp_path,mode):
    folder,fake=compiled(tmp_path,mode);task=TaskPackage(folder/'task')
    assert len(task.document.states)==1 and task.document.task.initial_state=='S1'
    assert task.document.task.parameters['compilation_status']=='draft_requires_review'
    state=task.document.states[0];assert state.instruction=='打开设备盖板' and len(state.observation_nodes)==1
    assert state.observation_nodes[0].condition==state.postconditions[0]
    prompt,_=task.prompt(state,state.observation_nodes[0]);assert state.postconditions[0] in prompt
    assert task.sources_for(state)[0]['text']=='打开盖板。请勿触碰内部导轨。'
    lineage=json.loads((folder/'lineage.json').read_text())
    assert lineage['/states/0/postconditions/0']['origin']=='inferred'
    assert json.loads((folder/'review.json').read_text())['status']=='pending'
    assert len(fake.calls)==(1 if mode=='direct' else 3)


def test_locked_action_graph_cannot_be_reordered_or_expanded():
    g=DraftGraph.model_validate(graph());locked=SimpleNamespace(actions=[SimpleNamespace(action_id='other')])
    with pytest.raises(ValueError,match='Locked'):check_graph(g,bundle(),locked)


@pytest.mark.parametrize('mutation,match',[
    ('missing','Every'),('duplicate','Duplicate'),('unknown_component','component'),('invisible','Invisible'),('nonvisual','Nonvisual'),('origin','observation_policy')])
def test_observation_constraints_never_use_legacy_auto_fill(mutation,match):
    g=graph();o=observations()
    if mutation=='missing':
        g['states'][0]['postconditions'].append(claim('第二个条件'))
    if mutation=='duplicate':o['observations']*=2
    if mutation=='unknown_component':o['observations'][0]['component_ids']=['source:其他物体']
    if mutation=='invisible':o['observations'][0]['verification_channel']='manual'
    if mutation=='nonvisual':g['states'][0]['postconditions']=[claim('螺丝扭矩符合要求')]
    if mutation=='origin':o['observations'][0]['capture_instruction']['origin']='explicit'
    with pytest.raises(ValueError,match=match):check_observations(DraftObservations.model_validate(o),DraftGraph.model_validate(g),bundle())


def test_unknown_citation_and_repeated_semantics_rejected():
    g=graph();g['states'][0]['instruction']['citation_ids']=['fabricated']
    with pytest.raises(ValueError,match='Unknown citation'):check_graph(DraftGraph.model_validate(g),bundle())
    g=graph();g['states'][0]['preconditions']=g['states'][0]['postconditions']
    with pytest.raises(ValueError,match='Repeated'):check_graph(DraftGraph.model_validate(g),bundle())


def test_repair_is_bounded_and_does_not_emit_partial_task(tmp_path):
    g=graph();bad={**g,**observations()};bad['observations'][0]['component_ids']=['source:bad']
    fake=Fake([bad,bad]);folder=tmp_path/'failed'
    with pytest.raises(ValueError,match='validation failed'):
        Compiler(fake,SETTINGS).compile(bundle(),REQUEST,folder,'direct')
    assert len(fake.calls)==2 and not (folder/'task').exists()
    assert json.loads((folder/'run.json').read_text())['status']=='failed'
    assert (folder/'direct-1.response.json').is_file()


def test_same_contract_transfers_without_device_specific_branch(tmp_path):
    request={**REQUEST,'device_id':'oven','device_name':'烤箱','task_id':'oven_open'}
    fake=Fake([{**graph(),**observations()}]);folder=tmp_path/'oven'
    Compiler(fake,SETTINGS).compile(bundle(),request,folder,'direct')
    task=TaskPackage(folder/'task');assert task.document.device.device_id=='oven'
    assert 'Bambu' not in fake.calls[0]['prompt'] and 'U7' not in fake.calls[0]['prompt']


def test_few_shot_requires_review_and_refuses_target_leakage(tmp_path):
    folder,_=compiled(tmp_path)
    with pytest.raises(ValueError,match='approved'):load_example(folder,bundle())
    path=folder/'review.json';review=json.loads(path.read_text());review.update(status='approved',reviewer='human-test');path.write_text(json.dumps(review))
    with pytest.raises(ValueError,match='leaks'):load_example(folder,bundle())
    other=bundle();other['evidence']={'different':other['evidence']['c1']}
    assert load_example(folder,other)['draft_sha256']==review['draft_sha256']
    review['draft_sha256']='wrong';path.write_text(json.dumps(review))
    with pytest.raises(ValueError,match='approved'):load_example(folder,other)



def test_output_never_overwrites_existing_run(tmp_path):
    folder,_=compiled(tmp_path)
    with pytest.raises(ValueError,match='overwritten'):Compiler(Fake([]),SETTINGS).compile(bundle(),REQUEST,folder)


def wiki_fixture(tmp_path):
    text='<article><h2>A</h2><p>第一动作，请保持设备固定并仔细阅读对应的操作指导。</p><h3>A1</h3><p>子动作。</p><h2>B</h2><p>其他。</p></article>'
    extracted,_=extract(text,'https://example.com/manual')
    return SimpleNamespace(by_url={'https://example.com/manual':'id'},snapshot_sha256='archive',archive_path=tmp_path/'snapshot/archive.json',assets={},
        page=lambda _:dict(url='https://example.com/manual',title='手册',page=dict(response={'body':{'sha256':'body'}},completed_at='date')),
        extraction=lambda _:extracted)


def test_source_selects_exact_heading_with_children_and_verifies_hashes(tmp_path):
    wiki=wiki_fixture(tmp_path);source=select(wiki,['https://example.com/manual'],['A'])
    texts=[b['text'] for b in source['evidence'].values()]
    assert '子动作。' in texts and '其他。' not in texts
    assert source['revision']==select(wiki,['https://example.com/manual'],['A'])['revision']
    with pytest.raises(ValueError,match='Unknown exact'):select(wiki,['https://example.com/manual'],['missing'])
    bad=wiki.extraction('id');bad['blocks'][1]['text']='changed';wiki.extraction=lambda _:bad
    with pytest.raises(ValueError,match='hash mismatch'):select(wiki,['https://example.com/manual'])


def test_rejected_reply_is_included_in_bounded_repair(tmp_path):
    good={**graph(),**observations()};bad=deepcopy(good);bad['states'][0]['instruction']['citation_ids']=['wrong']
    fake=Fake([bad,good]);folder=tmp_path/'repaired'
    Compiler(fake,SETTINGS).compile(bundle(),REQUEST,folder,'direct')
    assert len(fake.calls)==2 and 'PREVIOUS_REJECTED_OUTPUT' in fake.calls[1]['prompt']
    assert json.loads((folder/'run.json').read_text())['calls'][0]['status']=='rejected'


def test_image_references_and_historical_action_are_not_fabricated():
    g=graph();g['states'][0]['instruction']['image_ids']=['not-supplied']
    with pytest.raises(ValueError,match='Unknown source image'):check_graph(DraftGraph.model_validate(g),bundle())
    g=graph();g['states'][0]['postconditions']=[claim('支架已从上向下滑入底座')]
    with pytest.raises(ValueError,match='Nonvisual'):check_observations(DraftObservations.model_validate(observations()),DraftGraph.model_validate(g),bundle())


def test_provider_failure_is_recorded_without_export_or_validation_retry(tmp_path):
    class Offline:
        def chat_structured(self,**kwargs):raise RuntimeError('simulated provider outage')
    folder=tmp_path/'offline'
    with pytest.raises(RuntimeError):Compiler(Offline(),SETTINGS).compile(bundle(),REQUEST,folder,'direct')
    run=json.loads((folder/'run.json').read_text());assert run['status']=='failed'
    assert len(run['calls'])==1 and run['calls'][0]['status']=='provider_failed'
    assert not (folder/'task').exists()
