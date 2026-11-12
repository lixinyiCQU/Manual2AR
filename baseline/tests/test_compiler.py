"""Independent compiler regressions: local official fixtures, no GT task inputs."""
from copy import deepcopy
import io
import json
from pathlib import Path

from PIL import Image
import pytest

from manual2ar_baseline.compiler import Proposal, SemanticCheck, compile_task, load_compilation
from manual2ar_baseline.gt import Sources, TaskDefinition, digest, encoded
from manual2ar_baseline.sources import parsed, retrieve


CATALOG = Path(__file__).resolve().parents[1] / 'capabilities/v1.json'


class FakeClient:
    kind = 'independent_controlled_compiler'

    def __init__(self, proposal, faithful=True):
        self.proposal = deepcopy(proposal)
        self.faithful = faithful
        self.calls = []

    def call(self, prompt, schema, images):
        self.calls.append((prompt, len(images)))
        if 'task' in schema.get('properties', {}):
            result = self.proposal
        else:
            result = SemanticCheck(faithful=self.faithful, problems=[] if self.faithful else ['官方要求未得到完整表达']).model_dump()
        return json.dumps(result, ensure_ascii=False), dict(model='controlled', usage={})


def official_fixture(tmp_path, count=3):
    root = tmp_path / 'official'
    root.mkdir()
    first = f'使用 {count} 颗 M3-8 螺丝将底座固定到立柱，拧紧。请注意安装方向。'
    second = '将夹具手柄从上向下滑入底座。'
    source_path = root / 'official.json'
    source_path.write_bytes(encoded(dict(paragraphs=[first, second])))
    stream = io.BytesIO()
    Image.new('RGB', (128, 128), 'gray').save(stream, 'PNG')
    picture = root / 'fixture.png'
    picture.write_bytes(stream.getvalue())
    sources = Sources.model_validate(dict(schema_version='baseline-sources-v1', source_selection='unconfirmed',
        artifacts=[dict(id='text.file', path='official.json', sha256=digest(source_path.read_bytes())),
                   dict(id='image.file', path='fixture.png', sha256=digest(picture.read_bytes()))],
        records=[dict(id=identity, artifact_id='text.file', locator=f'json:/paragraphs/{index}', kind='official',
                      text=text, text_sha256=digest(text.encode()), citation_id=identity, source_url='https://wiki.bambulab.com/zh/a1-mini/manual/fixture')
                 for index, (identity, text) in enumerate([('official.anchor', first), ('official.handle', second)])],
        images=[dict(id='figure.fixture', artifact_id='image.file', source_ids=['official.anchor', 'official.handle'], source_url='https://wiki.bambulab.com/fixture.png')]))
    objects = [dict(id=identity, name=name, aliases=[], source_ids=[source]) for identity, name, source in
               [('fixture', '控制夹具底座', 'official.anchor'), ('mast', '立柱', 'official.anchor'), ('handle', '夹具手柄', 'official.handle')]]
    requirements = [dict(id=identity, kind=kind, source_id=source, quote=quote) for identity, kind, source, quote in [
        ('r.anchor', 'operation', 'official.anchor', '将底座固定到立柱'),
        ('r.number', 'specification', 'official.anchor', f'{count} 颗'),
        ('r.material', 'material_selection', 'official.anchor', 'M3-8'),
        ('r.tight', 'outcome', 'official.anchor', '拧紧'),
        ('r.facing', 'outcome', 'official.anchor', '请注意安装方向'),
        ('r.insert', 'operation', 'official.handle', '从上向下滑入底座')]]
    def condition(identity, statement, requirements, channel='vision'):
        return dict(id=identity, statement=statement, object_ids=['fixture', 'mast'] if identity != 'k.handle' else ['handle', 'fixture'],
                    requirement_ids=requirements, channel=channel, scope='visible_state' if channel == 'vision' else 'nonvisual_confirmation',
                    basis='normalization_proposal', standard_status='needs_visual_standard' if channel == 'vision' else 'manual_definition',
                    definition=statement)
    conditions = [condition('k.contact', '底座可见贴靠立柱', ['r.anchor']),
                  condition('k.bolts', '固定件位于各自孔位', ['r.number']),
                  condition('k.tight', '实际机械固定已经核实', ['r.tight'], 'manual'),
                  condition('k.facing', '安装方向已对照官方要求确认', ['r.facing'], 'manual'),
                  condition('k.handle', '夹具手柄与底座可见连接', ['r.insert'])]
    task = TaskDefinition.model_validate(dict(schema_version='baseline-task-v1', id='fixture.attach_handle', version='controlled-independent-v1',
        device_id='independent_fixture', title='安装控制夹具', scope='完整的底座和手柄装配任务', objects=objects,
        requirements=requirements, conditions=conditions,
        nodes=[dict(id='fasten_fixture', instruction=first, object_ids=['fixture', 'mast'], requirement_ids=['r.anchor', 'r.number', 'r.material', 'r.tight', 'r.facing'],
                    depends_on=[], precondition_ids=[], completion_ids=['k.contact', 'k.bolts', 'k.tight', 'k.facing']),
               dict(id='insert_handle', instruction=second, object_ids=['handle', 'fixture'], requirement_ids=['r.insert'],
                    depends_on=['fasten_fixture'], precondition_ids=[], completion_ids=['k.handle'])], goal_condition_ids=['k.handle']))
    def query(identity, kind, objects, locations=None):
        value = dict(id=identity, kind=kind, object_ids=objects, instruction='只采集该区域实际可见事实，未知须明确报告', reference_ids=['figure.fixture'])
        if locations:
            value['location_ids'] = locations
        return value
    locations = [f'position.{i+1}' for i in range(count)]
    proposal = Proposal.model_validate(dict(task=task.model_dump(),
        methods={'k.contact': 'vision.mount_relation', 'k.bolts': 'vision.fastener_instances', 'k.tight': 'manual.mechanical_security', 'k.facing': 'manual.direction', 'k.handle': 'vision.connection_relation'},
        references=[dict(image_id='figure.fixture')],
        queries=[query('observe.contact', 'mount_relation', ['fixture', 'mast']), query('observe.bolts', 'fastener_instances', ['fixture'], locations),
                 query('observe.handle', 'connection_relation', ['handle', 'fixture'])],
        rules=[dict(query_id='observe.contact', condition_id='k.contact', expected_value='seated'),
               dict(query_id='observe.bolts', condition_id='k.bolts', expected_locations=locations),
               dict(query_id='observe.handle', condition_id='k.handle', expected_value='connected')],
        presentations=[dict(node_id='fasten_fixture', action_id='holder.base', presentation_id='u7.holder_base'),
                       dict(node_id='insert_handle', action_id='holder.slide', presentation_id='u7.holder_slide')])).model_dump()
    catalog = tmp_path / 'capabilities.json'
    catalog.write_bytes(CATALOG.read_bytes())
    return sources, root, proposal, catalog


def compile_fixture(tmp_path, fixture, *, mutate=None, faithful=True):
    sources, root, proposal, catalog = fixture
    proposal = deepcopy(proposal)
    if mutate:
        mutate(proposal)
    client = FakeClient(proposal, faithful)
    output = tmp_path / 'compiled'
    result = compile_task(sources, root, {'method': 'independent-controlled-fixture'}, '我已完成底座，现在希望安装夹具手柄', catalog, client, output)
    return result, output, client


@pytest.mark.parametrize('count', [2, 3])
def test_official_count_is_data_and_compiled_task_loads(tmp_path, count):
    result, output, client = compile_fixture(tmp_path, official_fixture(tmp_path, count))
    assert result['status'] == 'experimental_ready' and len(client.calls) == 2
    sources, task, protocol, bindings, root = load_compilation(output)
    assert {node.id for node in task.nodes} == {'fasten_fixture', 'insert_handle'}
    assert task.nodes[1].depends_on == ['fasten_fixture']
    assert len(next(rule for rule in protocol.rules if rule.condition_id == 'k.bolts').expected_locations) == count
    assert bindings.task_sha256 == protocol.task_sha256
    review = json.loads((output / 'review.json').read_bytes())
    assert review['semantic_reviewer'] == 'model_only_not_human' and review['gt_used_as_input'] is False


@pytest.mark.parametrize('mutation,message', [
    (lambda p: p['task']['requirements'][0].update(quote='官方未出现的任意要求'), 'quote'),
    (lambda p: p['rules'][1].update(expected_locations=['position.1']), 'official count'),
])
def test_fabricated_quote_and_wrong_fastener_count_are_rejected(tmp_path, mutation, message):
    fixture = official_fixture(tmp_path)
    with pytest.raises(ValueError, match=message):
        compile_fixture(tmp_path, fixture, mutate=mutation)
    manifest = json.loads((tmp_path / 'compiled/manifest.json').read_bytes())
    assert manifest['status'] == 'failed'
    assert (tmp_path / 'compiled/compile-response-1.txt').is_file()


def visual_tightness(proposal):
    condition = next(c for c in proposal['task']['conditions'] if c['id'] == 'k.tight')
    condition.update(channel='vision', scope='visible_state', standard_status='needs_visual_standard')
    proposal['methods']['k.tight'] = 'vision.appearance'
    proposal['queries'].append(dict(id='observe.tightness', kind='appearance', object_ids=['fixture'], instruction='观察外部状态', reference_ids=['figure.fixture']))
    proposal['rules'].append(dict(query_id='observe.tightness', condition_id='k.tight', expected_value='no_visible_anomaly'))


def test_real_mechanical_security_cannot_be_discharged_by_appearance(tmp_path):
    with pytest.raises(ValueError, match='Nonvisual'):
        compile_fixture(tmp_path, official_fixture(tmp_path), mutate=visual_tightness)


def test_material_selection_cannot_become_rgb_completion(tmp_path):
    def mutation(proposal):
        next(c for c in proposal['task']['conditions'] if c['id'] == 'k.bolts')['requirement_ids'].append('r.material')
    with pytest.raises(ValueError, match='Material selection'):
        compile_fixture(tmp_path, official_fixture(tmp_path), mutate=mutation)


def test_declared_completion_cannot_remove_required_dependency_closure(tmp_path):
    def mutation(proposal):
        proposal['task']['nodes'][1]['depends_on'] = []
    with pytest.raises(ValueError, match='goal/dependency closure'):
        compile_fixture(tmp_path, official_fixture(tmp_path), mutate=mutation)


def test_unsupported_ar_preserves_compiled_nodes_but_blocks_execution(tmp_path):
    result, output, _ = compile_fixture(tmp_path, official_fixture(tmp_path), mutate=lambda p: p.update(presentations=[]))
    assert result['status'] == 'blocked' and 'unsupported_ar_coverage' in result['diagnostics']
    assert len(json.loads((output / 'task.json').read_bytes())['nodes']) == 2
    with pytest.raises(ValueError, match='blocked'):
        load_compilation(output)


def test_failed_semantic_review_is_preserved_and_blocks_loading(tmp_path):
    result, output, _ = compile_fixture(tmp_path, official_fixture(tmp_path), faithful=False)
    assert result['status'] == 'blocked' and any(d.startswith('semantic:') for d in result['diagnostics'])
    assert json.loads((output / 'review.json').read_bytes())['semantic']['faithful'] is False
    with pytest.raises(ValueError, match='blocked'):
        load_compilation(output)


def test_changed_compiled_artifact_is_rejected(tmp_path):
    _, output, _ = compile_fixture(tmp_path, official_fixture(tmp_path))
    task_file = output / 'task.json'
    task_file.write_bytes(task_file.read_bytes() + b' ')
    with pytest.raises(ValueError, match='artifact changed'):
        load_compilation(output)


def test_fastener_only_query_uses_the_unique_mount_relation_of_its_own_operation(tmp_path):
    def separate_objects(proposal):
        proposal['task']['objects'].append(dict(id='bolts',name='固定螺丝',aliases=[],source_ids=['official.anchor']))
        proposal['task']['nodes'][0]['object_ids'].append('bolts')
        next(c for c in proposal['task']['conditions'] if c['id']=='k.bolts')['object_ids']=['bolts']
        proposal['queries'][1]['object_ids']=['bolts']
    result,output,_=compile_fixture(tmp_path,official_fixture(tmp_path),mutate=separate_objects)
    assert result['status']=='experimental_ready'
    _,_,protocol,_,_=load_compilation(output)
    assert protocol.refinement.source_query_id=='observe.contact'
    assert protocol.refinement.detail_query_ids==['observe.bolts']


def test_chinese_official_fastener_count_is_not_assumed_to_be_two(tmp_path):
    sources,root,proposal,catalog=official_fixture(tmp_path,count=3)
    text=json.loads((root/'official.json').read_bytes())
    text['paragraphs'][0]=text['paragraphs'][0].replace('3 颗','三颗')
    (root/'official.json').write_bytes(encoded(text))
    sources.artifacts[0].sha256=digest((root/'official.json').read_bytes())
    sources.records[0].text=text['paragraphs'][0]
    sources.records[0].text_sha256=digest(sources.records[0].text.encode())
    next(r for r in proposal['task']['requirements'] if r['id']=='r.number')['quote']='三颗'
    _,output,_=compile_fixture(tmp_path,(sources,root,proposal,catalog))
    assert len(load_compilation(output)[2].rules[1].expected_locations)==3


def test_user_completion_claim_is_recorded_but_not_sent_to_task_compiler(tmp_path):
    sources,root,proposal,catalog=official_fixture(tmp_path,count=2)
    client=FakeClient(proposal)
    output=tmp_path/'claim-separated'
    compile_task(sources,root,{'goal':'安装夹具手柄'},'我已完成底座，现在希望安装夹具手柄',catalog,client,output)
    assert all('我已完成底座' not in prompt for prompt,_ in client.calls)
    assert json.loads((output/'request.json').read_bytes())['intent'].startswith('我已完成底座')


def test_compile_and_load_do_not_read_ground_truth_files(tmp_path, monkeypatch):
    fixture = official_fixture(tmp_path)
    seen = []
    original = Path.read_bytes
    def audited_read(path):
        seen.append(str(path.resolve()))
        assert 'ground_truth' not in path.parts, f'GT input leaked: {path}'
        return original(path)
    monkeypatch.setattr(Path, 'read_bytes', audited_read)
    _, output, _ = compile_fixture(tmp_path, fixture)
    load_compilation(output)
    assert any(path.endswith('official.json') for path in seen)
    assert any(path.endswith('compiler.py') for path in seen)
    assert seen and not any('ground_truth' in path for path in seen)


def test_retrieval_keeps_whole_official_parent_and_validates_image(tmp_path):
    sources, source_root, _, _ = official_fixture(tmp_path)
    root = tmp_path / 'archive'
    run = root / 'runs' / 'controlled'
    run.mkdir(parents=True)
    url = 'https://wiki.bambulab.com/zh/a1-mini/manual/fixture'
    html = '<article><h2>安装控制夹具</h2><h3>1. 固定底座</h3><p>使用 3 颗螺丝固定底座。</p><img src="/fixture.png"><h3>2. 插入手柄</h3><p>从上向下滑入手柄。</p></article>'
    def artifact(name, raw):
        path = root / 'objects' / name
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(raw)
        return dict(path=str(path.relative_to(root)), sha256=digest(raw), bytes=len(raw))
    dom = artifact('page.html', html.encode())
    image = artifact('fixture.png', (source_root / 'fixture.png').read_bytes())
    blocks, images = parsed(html, url)
    extraction = run / 'pages' / 'fixture' / 'extraction.json'
    extraction.parent.mkdir(parents=True)
    extraction.write_bytes(encoded(dict(blocks=[dict(ordinal=n, kind=k, text=t, heading_path=h, dom_path=p, text_sha256=digest(t.encode())) for n,k,t,h,p in blocks],
        assets=[dict(url=u, heading_path=h, kind='image') for u,h in images])))
    archive = run / 'archive.json'
    archive.write_bytes(encoded(dict(pages={url:dict(status='archived',artifact_dir=str(extraction.parent.relative_to(root)),response=dict(body=dom,rendered_dom=dom))},
        assets={'https://wiki.bambulab.com/fixture.png':dict(status='archived',body=image)})))
    manifest = tmp_path / 'manifest.json'
    manifest.write_bytes(encoded(dict(archive_sha256=digest(archive.read_bytes()))))
    records, _, metadata = retrieve(archive, manifest, '我已完成底座，现在希望安装控制夹具')
    assert metadata['parent_heading'] == ['安装控制夹具']
    assert any('3 颗' in r.text for r in records.records) and any('向下滑入' in r.text for r in records.records)
    (root / image['path']).write_bytes(b'changed')
    with pytest.raises(ValueError, match='object hash'):
        retrieve(archive, manifest, '安装控制夹具')
