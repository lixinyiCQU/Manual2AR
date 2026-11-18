"""Exercise the normal tutorial run against distinct controlled scene/model observations."""
import base64
import hashlib
import json

import pytest

from manual2ar.modules.guidance.registry import UNBOX
from manual2ar.modules.guidance.spatial.simulation import jpeg
from .test_baseline_ar import Facts
from .test_tutorial import browse
from .test_workflow import guide, registry, start, url


def stamp(v, key):
    return dict(state_id=v['state_id'], revision=v['revision'], variant_id=v['variant_id'],
                substep_id=v['selected_substep_id'], action_id=key)


def find(v, key):
    return next(a for a in v['photo_ar']['actions'] if a['action_id'] == key)


def capture(v, key, color=30, raw=None):
    raw = jpeg(color) if raw is None else raw
    return dict(**stamp(v,key), source_sha256=hashlib.sha256(raw).hexdigest(),
                image_base64=base64.b64encode(raw).decode(), client_frame_id=max(0, v['last_client_frame_id'])+1)


def mark(v, key):
    a = find(v, key)
    return dict(**stamp(v,key), source_sha256=a['source_sha256'], confirmed_checks=a['manual_checks'])


def post(c, v, route, body, code=200):
    r = c.post(url(v, route), json=body)
    assert r.status_code == code, r.text
    return r.json()


def finding(status='supported', *, wrong_sha=False, confidence=.99):
    def call(**kwargs):
        assert len(kwargs['images_base64']) == 2
        assert all(base64.b64decode(raw).startswith(b'\xff\xd8') for raw in kwargs['images_base64'])
        ids = kwargs['schema']['properties']
        return dict(status=status, action_id=ids['action_id']['const'],
                    source_sha256='0'*64 if wrong_sha else ids['source_sha256']['const'],
                    evidence='受控可见依据', confidence=confidence, next_action='请拍清指定区域')
    return call


@pytest.mark.parametrize('variant,chapter,found,absent',[
    ('standalone_unboxing','U9','external.tube','ams.seat'),
    ('ams_lite_unboxing','U9','ams.seat','external.tube')])
def test_normal_entry_branch_action_and_read_only_illustration(guide,variant,chapter,found,absent):
    client, fake, _, _ = guide
    v = browse(client,start(client,UNBOX,variant),chapter)
    a = find(v,found); sha = '4'*64
    command = dict(**stamp(v,found), source_sha256=sha, anchor_x=.63, anchor_y=.7, width=960, height=540)
    shown = post(client,v,'ar-illustration',command)
    assert shown['illustrative_only'] and shown['source_sha256'] == sha
    assert shown['presentation']['presentation_id'] == a['presentation_id']
    assert shown['presentation']['catalog_sha256'] == v['photo_ar']['asset_library']['catalog_sha256']
    assert shown['presentation']['instances'] and len(shown['projection']['intrinsics']) == 9
    assert client.get(url(v)).json()['revision'] == v['revision'] and not fake.calls
    post(client,v,'ar-illustration',{**command,'action_id':absent},409)
    post(client,v,'ar-illustration',{**command,'width':0},422)
    v = browse(client,v,'U3')
    assert not v['photo_ar']['actions'] and v['photo_ar']['reason']


def test_visual_checks_multi_manual_stale_and_wrong_model_identity(guide, monkeypatch):
    c, fake, _, folder = guide
    v = browse(c,start(c,UNBOX),'U4','U4-S1'); key='zlock.remove'
    post(c,v,'ar-manual',mark(v,key),409)
    ref = c.get(find(v,key)['reference']['url']).content
    post(c,v,'ar-photo',capture(v,key,raw=ref),422)
    monkeypatch.setattr(fake,'chat_structured',finding(wrong_sha=True))
    post(c,v,'ar-photo',capture(v,key),502)
    assert c.get(url(v)).json()['revision'] == v['revision']
    monkeypatch.setattr(fake,'chat_structured',finding('contradicted'))
    v = post(c,v,'ar-photo',capture(v,key))
    assert find(v,key)['status']=='not_met'
    post(c,v,'ar-manual',mark(v,key),409)
    post(c,v,'ar-photo',capture(v,key),409)
    monkeypatch.setattr(fake,'chat_structured',finding(confidence=.01))
    v=post(c,v,'ar-photo',capture(v,key,31))
    assert find(v,key)['status']=='needs_photo'
    post(c,v,'ar-manual',mark(v,key),409)
    monkeypatch.setattr(fake,'chat_structured',finding())
    v=post(c,v,'ar-photo',capture(v,key,32))
    assert find(v,key)['status']=='needs_manual'
    post(c,v,'ar-manual',{**mark(v,key),'source_sha256':'0'*64},409)
    post(c,v,'ar-manual',{**mark(v,key),'confirmed_checks':['错误的条件']},409)
    v=post(c,v,'ar-manual',mark(v,key))
    assert find(v,key)['status']=='verified' and v['photo_ar']['chapter_status']=='in_progress'
    assert '开箱 AR 动作核验' in c.get(url(v,'report')).text
    attempts=list((folder/v['run_id']).glob('ar-*/request.json'))
    assert attempts and all('action_catalog_sha256' in json.loads(p.read_bytes()) for p in attempts)


def test_manual_only_and_storage_failure_keeps_previous_state(guide,monkeypatch):
    c,fake,_,_=guide; v=browse(c,start(c,UNBOX),'U5'); key='bed.tighten'
    post(c,v,'ar-photo',capture(v,key),409)
    from manual2ar.modules.guidance import unboxing_ar as ar
    original=ar.atomic_json
    def fail(path, value):
        if path.name=='acceptance.json':raise OSError('test')
        original(path,value)
    monkeypatch.setattr(ar,'atomic_json',fail)
    post(c,v,'ar-manual',mark(v,key),503)
    assert c.get(url(v)).json()['revision']==v['revision']
    monkeypatch.setattr(ar,'atomic_json',original)
    v=post(c,v,'ar-manual',mark(v,key))
    assert v['photo_ar']['chapter_status']=='verified' and find(v,key)['status']=='verified' and not fake.calls
    assert next(r for r in v['chapter_completion'] if r['state_id']=='U5')['source']=='photo_ar_checks'


def test_u7_tutorial_uses_reviewed_ledger_and_rolls_back_on_contradiction(guide):
    c,fake,service,_=guide
    facts=Facts();facts.base=True;service.photo_ar.definition.photo_client=facts
    v=browse(c,start(c,UNBOX,'ams_lite_unboxing'),'U7')
    v=post(c,v,'ar-photo',capture(v,'holder.base'))
    assert find(v,'holder.base')['status']=='needs_manual' and not v['u7_sequence']['base_approved']
    post(c,v,'ar-manual',{**mark(v,'holder.base'),'confirmed_checks':find(v,'holder.base')['manual_checks'][:1]},409)
    v=post(c,v,'ar-manual',mark(v,'holder.base'))
    assert v['u7_sequence']['base_approved']
    v=browse(c,v,'U7','U7-S2')
    facts.holder=True;facts.hidden=True
    v=post(c,v,'ar-photo',capture(v,'holder.slide',31))
    assert find(v,'holder.slide')['status']=='needs_manual'
    v=post(c,v,'ar-manual',mark(v,'holder.slide'))
    assert v['photo_ar']['chapter_status']=='verified' and v['u7_sequence']['holder_approved']
    facts.hidden=False;facts.base=False
    v=post(c,v,'ar-photo',capture(v,'holder.slide',32))
    assert v['selected_substep_id']=='U7-S1' and v['photo_ar']['chapter_status']!='verified'
    assert not v['u7_sequence']['base_approved'] and not fake.calls
