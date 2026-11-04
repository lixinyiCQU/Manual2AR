"""U7 order is server-owned, shared between tutorial/spatial, and driven only by a base VLM pass."""
import uuid
import pytest
from fastapi import HTTPException
from tests.backend.guidance.test_workflow import guide,registry,start,cmd,url,capture,UNBOX
from tests.backend.guidance.test_spatial import begin,frame
from manual2ar.modules.guidance import u7_sequence as sequence


def browse(c,v,sub='U7-S1'):
    r=c.post(url(v,'browse'),json={**cmd(v),'target_state_id':'U7','substep_id':sub});assert r.status_code==200,r.text;return r.json()


def verify(c,v):
    r=c.post(url(v,'verify'),json=capture(v));assert r.status_code==200,r.text;return r.json()


@pytest.mark.parametrize('variant',['standalone_unboxing','ams_lite_unboxing'])
def test_tutorial_base_verification_unlocks_only_after_valid_vlm_pass(guide,variant):
    c,fake,_,_=guide;v=browse(c,start(c,UNBOX,variant));assert v['substeps'][1]['locked'] and not v['can_advance']
    assert c.post(url(v,'browse'),json={**cmd(v),'target_state_id':'U7','substep_id':'U7-S2'}).status_code==409
    assert c.post(url(v,'advance'),json=cmd(v)).status_code==409
    fake.status='uncertain';v=verify(c,v);assert not v['u7_sequence']['base_approved']
    fake.status='completed';v=verify(c,v);assert v['u7_sequence']['base_approved'] and not v['substeps'][1]['locked']
    assert '两颗' in fake.calls[-1]['prompt'] and len(fake.calls[-1]['images_base64'])==2
    v=c.post(url(v,'advance'),json=cmd(v)).json();assert v['selected_substep_id']=='U7-S2'
    v=verify(c,v);assert v['u7_sequence']['holder_approved'] and '最终可见安装状态' in fake.calls[-1]['prompt']
    v=browse(c,v);v=c.post(url(v,'recheck'),json=cmd(v)).json();assert not v['u7_sequence']['base_approved'] and not v['u7_sequence']['holder_approved']
    assert c.post(url(v,'browse'),json={**cmd(v),'target_state_id':'U7','substep_id':'U7-S2'}).status_code==409


def test_spatial_camera_guard_and_shared_tutorial_approval(guide):
    c,fake,_,_=guide;v=browse(c,start(c,UNBOX,'standalone_unboxing'));api=begin(c,'camera',tutorial_run_id=v['run_id'])
    assert c.post(api+'/frames',json=frame(action='holder.slide')).status_code==409
    # A manual operation marker is not a VLM pass.
    c.post(api+'/events',json={'event_id':uuid.uuid4().hex,'action_id':'holder.base','target_id':'main','name':'user_marked','client_frame_id':0})
    assert not c.get(url(v)).json()['u7_sequence']['base_approved']
    assert c.post(api+'/frames',json=frame(action='holder.base')).status_code==200
    checked=c.post(api+'/verify',json={'action_id':'holder.base','client_frame_id':1});assert checked.status_code==200,checked.text
    assert checked.json()['scope']=='visible_base_installation' and checked.json()['u7_sequence']['base_approved']
    parent=c.get(url(v)).json();assert parent['u7_sequence']['base_approved'] and parent['revision']>v['revision']
    assert c.post(api+'/frames',json=frame(number=2,action='holder.slide')).status_code==200
    another=begin(c,'camera',tutorial_run_id=v['run_id']);assert c.post(another+'/frames',json=frame(action='holder.slide')).status_code==200
    new=begin(c,'camera');assert c.post(new+'/frames',json=frame(action='holder.slide')).status_code==409
    fake.error=True;c.post(api+'/frames',json=frame(number=3,action='holder.base'))
    assert c.post(api+'/verify',json={'action_id':'holder.base','client_frame_id':3}).status_code==502
    assert not c.get(url(v)).json()['u7_sequence']['base_approved']
    assert c.post(another+'/frames',json=frame(number=2,action='holder.slide')).status_code==409


def test_simulation_does_not_unlock_real_tutorial(guide):
    c,_,_,_=guide;v=start(c,UNBOX,'standalone_unboxing');api=begin(c,'replay',tutorial_run_id=v['run_id'])
    reply=c.post(api+'/frames',json=frame(action='holder.slide'));assert reply.status_code==200
    assert reply.json()['u7_sequence']['enforced'] is False
    assert c.post(api+'/verify',json={'action_id':'holder.base','client_frame_id':1}).status_code==409
    assert not c.get(url(v)).json()['u7_sequence']['base_approved']


def test_late_base_result_cannot_overwrite_newer_check():
    from types import SimpleNamespace
    owner=SimpleNamespace(u7_checks={});old=sequence.start(owner,'holder.base');new=sequence.start(owner,'holder.base')
    with pytest.raises(HTTPException):sequence.finish(owner,'holder.base',old,{'status':'completed'})
    sequence.finish(owner,'holder.base',new,{'status':'uncertain'});assert not sequence.state(owner)['base_approved']


def test_completed_without_visible_evidence_cannot_unlock(guide):
    c,fake,_,_=guide;v=browse(c,start(c,UNBOX,'standalone_unboxing'))
    fake.chat_structured=lambda **kwargs:{'status':'completed','confidence':1,'evidence':'','next_action':''}
    v=verify(c,v);assert not v['u7_sequence']['base_approved'] and v['observations'][0]['status']=='uncertain'
