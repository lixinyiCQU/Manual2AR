"""Explicit photo guidance: same-frame ROI, honest evidence, complete failure records."""
import json
from pathlib import Path
from fastapi.testclient import TestClient
from manual2ar.integrations.vlm.client import VisionError
from tests.backend.guidance.test_spatial import app,begin,frame
from tests.backend.guidance.test_unboxing_extension import profiles,fixture_target


class Locator:
    def __init__(self,fail=False):self.calls=[];self.fail=fail
    def chat_structured(self,**kwargs):
        self.calls.append(kwargs)
        if self.fail:raise VisionError('do not persist private transport data','timeout')
        return {'action_id':'holder.base','target_id':'main','status':'uncertain','confidence':.8,
            'bbox_0_1000':[],'foreground_point_0_1000':[], 'evidence':'螺丝被支架遮挡。','next_action':'请从安装面侧面补拍。'}


def test_location_uses_only_confirmed_positions_and_same_frame_crop(app):
    service=app.state.spatial;profiles(service,{'holder.base':fixture_target()})
    spy=Locator();service.client=spy;service.config['vlm']['api_key']='test-only'
    with TestClient(app) as c:
        api=begin(c,'camera',reuse_targets=True);request=frame(action='holder.base')
        c.post(api+'/frames',json=request)
        answer=c.post(api+'/locate',json={'action_id':'holder.base','target_id':'main','client_frame_id':1})
        assert answer.status_code==200 and answer.json()['evidence']=='螺丝被支架遮挡。'
        assert len(spy.calls[0]['images_base64'])==2
        assert '不能使用局部图坐标' in spy.calls[0]['prompt']
        folder=next((service.root/'runs'/api.rsplit('/',1)[-1]).glob('locate-*'))
        context=json.loads((folder/'vision_context.json').read_text())
        assert context['source_sha256']==request['source_sha256']
        assert context['anchors_0_1000'][0]['target_id']=='main'
        assert (folder/'roi.jpg').is_file() and (folder/'model_reply.json').is_file()
        assert not service.registry is None and not app.state.guidance.meta


def test_unconfirmed_saved_points_are_never_sent_as_current_context(app):
    service=app.state.spatial;profiles(service,{'holder.base':fixture_target()})
    spy=Locator();service.client=spy;service.config['vlm']['api_key']='test-only'
    with TestClient(app) as c:
        api=begin(c,'camera',reuse_targets=False);c.post(api+'/frames',json=frame(action='holder.base'))
        assert c.post(api+'/locate',json={'action_id':'holder.base','client_frame_id':1}).status_code==200
        assert len(spy.calls[0]['images_base64'])==1


def test_failed_model_call_has_safe_error_artifact_and_event(app):
    service=app.state.spatial;service.client=Locator(True);service.config['vlm']['api_key']='test-only'
    with TestClient(app) as c:
        api=begin(c,'camera');c.post(api+'/frames',json=frame(action='holder.base'))
        assert c.post(api+'/locate',json={'action_id':'holder.base','client_frame_id':1}).status_code==502
        root=service.root/'runs'/api.rsplit('/',1)[-1];folder=next(root.glob('locate-*'))
        error=json.loads((folder/'error.json').read_text());assert error=={'error_type':'VisionError','code':'timeout'}
        assert 'private transport' not in (folder/'error.json').read_text()
        assert any(json.loads(line)['event']=='vision.failed' for line in (root/'events.jsonl').read_text().splitlines())


def test_server_advertises_current_visual_revision_and_short_cycle(app):
    with TestClient(app) as c:
        assert c.get('/api/guidance/spatial/config').json()['visual_revision']=='mesh-loop-v2'
        api=begin(c);r=c.post(api+'/frames',json=frame(action='holder.base')).json()
        assert r['visual']['asset']['asset_id']=='hex_key' and r['visual']['duration_seconds']==1.2


def test_candidate_far_from_authored_position_is_not_shown_as_found(app):
    class WrongRegion(Locator):
        def chat_structured(self,**kwargs):
            return {'action_id':'holder.base','target_id':'main','status':'found','confidence':.99,
                'bbox_0_1000':[1,1,30,30],'foreground_point_0_1000':[15,15]}
    service=app.state.spatial;profiles(service,{'holder.base':fixture_target()})
    service.client=WrongRegion();service.config['vlm']['api_key']='test-only'
    with TestClient(app) as c:
        api=begin(c,'camera',reuse_targets=True);c.post(api+'/frames',json=frame(action='holder.base'))
        value=c.post(api+'/locate',json={'action_id':'holder.base','client_frame_id':1}).json()
        assert value['status']=='uncertain' and not value['box_lines'] and not value['outlines']
        assert '不一致' in value['evidence']


def test_number_only_wiki_heading_has_source_based_selector_caption():
    from manual2ar.modules.guidance.lesson import substep_caption
    assert substep_caption('2.','从上向下滑入料盘支架。\n请确保方向匹配。')=='从上向下滑入料盘支架'
    assert substep_caption('1. 安装底座','其他内容')=='安装底座'
