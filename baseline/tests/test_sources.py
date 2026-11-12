import json
from pathlib import Path
import pytest
from manual2ar_baseline.sources import digest, encoded, parsed, retrieve


@pytest.fixture
def archive(tmp_path):
    root=tmp_path/'official'; run=root/'runs'/'snapshot'; run.mkdir(parents=True)
    url='https://wiki.bambulab.com/zh/a1-mini/manual/assembly'
    image_url='https://wiki.bambulab.com/part.png'
    html='<html><body><div class="contents"><h2>安装机械支架</h2><h3>1. 操作支架底座</h3><p>使用两颗 M3-8 螺丝。</p><img src="/part.png"><h3>2. 操作料盘支架</h3><p>向下滑入。</p><h2>拆卸机械支架</h2><h3>1. 操作支架底座</h3><p>使用两颗 M3-8 螺丝。</p><h3>2. 操作料盘支架</h3><p>向下滑出。</p></div></body></html>'
    def obj(name,raw):
        path=root/'objects'/name; path.parent.mkdir(exist_ok=True); path.write_bytes(raw)
        return dict(path=str(path.relative_to(root)),sha256=digest(raw),bytes=len(raw))
    dom=obj('page.html',html.encode()); image=obj('part.png',b'controlled-image-bytes')
    raw_blocks,raw_images=parsed(html,url)
    blocks=[dict(ordinal=n,kind=k,text=text,heading_path=heading,dom_path=selector,text_sha256=digest(text.encode())) for n,k,text,heading,selector in raw_blocks]
    extraction=run/'pages'/'article'/'extraction.json'; extraction.parent.mkdir(parents=True)
    extraction.write_bytes(encoded(dict(blocks=blocks,assets=[dict(url=u,heading_path=h,kind='image') for u,h in raw_images])))
    page=dict(status='archived',artifact_dir=str(extraction.parent.relative_to(root)),response=dict(body=dom,rendered_dom=dom))
    value=dict(pages={url:page},assets={image_url:dict(status='archived',body=image)})
    path=run/'archive.json'; path.write_bytes(encoded(value))
    manifest=tmp_path/'manifest.json'; manifest.write_bytes(encoded(dict(archive_sha256=digest(path.read_bytes()))))
    return path,manifest,root,extraction,image


def test_goal_retrieves_complete_parent_and_only_official_records(archive):
    path,manifest,root,extraction,image=archive
    sources,source_root,metadata=retrieve(path,manifest,'我已完成拆卸，现在希望安装机械支架')
    assert metadata['parent_heading']==['安装机械支架']
    assert len(sources.records)==5 and len(sources.images)==1
    assert any('两颗 M3-8' in r.text for r in sources.records)
    assert any('向下滑入' in r.text for r in sources.records)
    assert source_root==root and sources.source_selection=='unconfirmed'
    assert {r.kind for r in sources.records}=={'official'}


def test_archive_hash_is_pinned(archive):
    path,manifest,*_=archive; path.write_bytes(path.read_bytes()+b' ')
    with pytest.raises(ValueError,match='archive hash'):retrieve(path,manifest,'安装机械支架')


def test_heading_metadata_is_verified_against_dom(archive):
    path,manifest,root,extraction,image=archive
    value=json.loads(extraction.read_bytes()); value['blocks'][1]['heading_path']=['安装别的部件']; extraction.write_bytes(encoded(value))
    with pytest.raises(ValueError,match='original DOM'):retrieve(path,manifest,'安装机械支架')


def test_selected_image_hash_is_checked(archive):
    path,manifest,root,extraction,image=archive; (root/image['path']).write_bytes(b'changed')
    with pytest.raises(ValueError,match='object hash'):retrieve(path,manifest,'安装机械支架')


def test_ambiguous_component_only_query_is_rejected(archive):
    path,manifest,*_=archive
    with pytest.raises(ValueError,match='Ambiguous'):retrieve(path,manifest,'机械支架')


def test_explicit_removal_does_not_select_installation(archive):
    path,manifest,*_=archive
    sources,_,metadata=retrieve(path,manifest,'现在希望拆卸机械支架')
    assert metadata['parent_heading']==['拆卸机械支架']
    assert not sources.images


def test_completion_goal_uses_explicit_assembly_context_without_treating_claim_as_evidence(archive):
    path,manifest,*_=archive
    sources,_,metadata=retrieve(path,manifest,'我已完成底座，现在希望完成机械支架',assembly_context=True)
    assert metadata['goal']=='安装机械支架' and metadata['parent_heading']==['安装机械支架']
    assert metadata['intent_interpretation']=='completion_phrase_in_explicit_assembly_context'
    assert any('向下滑入' in r.text for r in sources.records)


@pytest.mark.parametrize('query',['我不希望安装机械支架','我希望不要安装机械支架','我不想拆卸机械支架'])
def test_negated_goal_is_not_reversed_into_an_operation(archive,query):
    path,manifest,*_=archive
    with pytest.raises(ValueError,match='Negated'):
        retrieve(path,manifest,query,assembly_context=True)


def test_goal_metadata_cannot_inject_a_user_completion_claim(archive):
    from manual2ar_baseline.compiler import verify_origin
    path,manifest,*_=archive
    sources,root,metadata=retrieve(path,manifest,'安装机械支架',assembly_context=True)
    metadata['goal']='我已完成底座，只需支架'
    with pytest.raises(ValueError,match='pinned original'):
        verify_origin(sources,root,metadata)


def test_unknown_component_does_not_match_only_the_installation_verb(archive):
    path,manifest,*_=archive
    with pytest.raises(ValueError,match='No matching'):
        retrieve(path,manifest,'我希望安装空调')
