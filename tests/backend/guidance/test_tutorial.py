"""Official hierarchy, evidence completeness and advisory navigation behavior."""
import json
from pathlib import Path
import pytest
from tests.backend.guidance.test_workflow import guide,registry,start,cmd,url,confirm,advance,capture
from manual2ar.modules.guidance.registry import UNBOX,FIRST


def browse(client,v,target,sub=None):
    body={**cmd(v),'target_state_id':target}
    if sub is not None:body['substep_id']=sub
    r=client.post(url(v,'browse'),json=body);assert r.status_code==200,r.text
    return r.json()


@pytest.mark.parametrize('variant',['standalone_unboxing','ams_lite_unboxing'])
def test_free_browse_without_fake_success(guide,variant):
    client,fake,service,folder=guide;v=start(client,UNBOX,variant)
    v=browse(client,v,'U13');assert v['can_advance']
    assert not any(n['status']=='completed' for n in v['observations'])
    v=advance(client,v);assert v['completed'] and v['completion_source']=='tutorial_browsing_finished'
    assert not v['user_marked_step_ids'] and not fake.calls
    v=browse(client,v,'U1');assert v['status']=='running' and not v['completed']
    _,engine,run=service.parts(v['run_id']);assert not run.results
    assert '未标记' in client.get(url(v,'report')).text


def test_substep_identity_and_references_follow_selection(guide):
    client,fake,_,_=guide;v=browse(client,start(client,UNBOX),'U4')
    assert len(v['substeps'])==3
    first=v['presentation']['images'];v=browse(client,v,'U4','U4-S3')
    assert v['selected_substep_id']=='U4-S3' and v['presentation']['images']!=first
    assert '减震泡棉' in v['presentation']['substep_title']
    gif=next(p for p in v['presentation']['images'] if p['animation_frames'])
    assert len(gif['animation_frames'])==273
    frame=gif['animation_frames'][0];assert client.get(frame['url']).status_code==200
    assert client.post(url(v,'browse'),json={**cmd(v),'target_state_id':'U4','substep_id':'U2-S1'}).status_code==422
    assert client.post(url(v,'browse'),json={**cmd(v),'target_state_id':'U999'}).status_code==422
    empty=client.post(url(v,'browse'),json={**cmd(v),'target_state_id':'U2','substep_id':''})
    assert empty.status_code==200 and empty.json()['state_id']=='U2'
    assert not fake.calls


@pytest.mark.parametrize('status',['uncertain','wrong_operation','provider_error'])
def test_visual_advice_does_not_block_or_mark_operation(guide,status):
    client,fake,service,_=guide;v=browse(client,start(client,UNBOX),'U4','U4-S2')
    if status=='provider_error':fake.error=True
    else:fake.status=status
    r=client.post(url(v,'verify'),json=capture(v));assert r.status_code==200
    after=r.json();assert after['can_advance'] and not after['user_marked_step_ids']
    assert after['observations'][0]['status']!='completed'
    # One chapter-wide final inspection, independent of the selected substep.
    assert '本章完成后的可见最终状态' in fake.calls[-1]['prompt']
    assert len(fake.calls[-1]['images_base64'])==1
    jumped=browse(client,after,'U11');assert jumped['state_id']=='U11'
    assert client.post(url(after,'browse'),json={**cmd(after),'target_state_id':'U1'}).status_code==409
    back=browse(client,jumped,'U4');assert back['observations'][0]['status']!='completed'


def test_marking_and_successful_visual_advice_are_separate(guide):
    client,fake,service,_=guide;v=browse(client,start(client,UNBOX),'U4')
    v=client.post(url(v,'verify'),json=capture(v)).json()
    assert v['observations'][0]['status']=='completed' and not v['user_marked_step_ids']
    v=browse(client,v,'U1');v=confirm(client,v)
    assert v['user_marked_step_ids']==['U1'] and v['observations'][0]['status']=='not_started'
    _,engine,run=service.parts(v['run_id']);assert 'U1-C1' not in run.results


def test_ams_and_single_spool_content_are_not_mixed(registry):
    single=registry.resolve(UNBOX,'standalone_unboxing')[1];ams=registry.resolve(UNBOX,'ams_lite_unboxing')[1]
    titles=lambda task:[task.cards[s.state_id].title for s in task.document.states]
    assert '组装 AMS lite' not in titles(single) and '组装 AMS lite' in titles(ams)
    assert '附录：安装外挂料盘和初次打印' in titles(single) and '附录：安装外挂料盘和初次打印' not in titles(ams)
    inventory=lambda t:next(s for s in t.document.states if t.cards[s.state_id].title=='检查包装盒中的配件')
    assert 'combo 版本：' not in inventory(single).instruction and '单机版本：' not in inventory(ams).instruction
    holder=next(c for c in ams.cards.values() if c.title=='安装料盘支架');assert holder.optional
    power=next(s for s in single.document.states if '通电' in single.cards[s.state_id].title)
    assert '4pin' not in power.instruction


def test_all_official_images_and_subheadings_are_preserved(registry):
    root=Path('resources/tasks/bambu_a1_mini/unboxing/v2')
    coverage=json.loads((root/'image_coverage.json').read_text())['images'];assert len(coverage)==62
    packages=[registry.resolve(UNBOX,v)[1] for v in ('standalone_unboxing','ams_lite_unboxing')]
    used={p for task in packages for card in task.cards.values() for p in card.reference_images}
    assert all(item['display_path'] in used for item in coverage)
    for item in coverage:
        assert item['original_sha256']==packages[0].evidence['images'][item['original_path']]['sha256']
    for task in packages:
        for state in task.document.states:
            assert len(state.observation_nodes)==1
            assert all(n.verification_channel=='manual' for n in state.observation_nodes) if '校准' in task.cards[state.state_id].title else True


def test_tutorial_uses_vlm_only_and_does_not_segment_returned_boxes(guide):
    client,fake,service,folder=guide;v=browse(client,start(client,UNBOX),'U4')
    original=fake.chat_structured
    def boxed(**kwargs):
        data=original(**kwargs);data['component_boxes_0_1000']=[{'component_id':'target:本章安装区域','bbox_0_1000':[100,100,800,800]}];return data
    fake.chat_structured=boxed
    response=client.post(url(v,'verify'),json=capture(v));assert response.status_code==200
    view=response.json();assert view['observations'][0]['segmentation']=='no_annotation'
    image=client.get(view['observations'][0]['image_url']).content
    assert image==next((folder/v['run_id']).glob('*/input.jpg')).read_bytes()
