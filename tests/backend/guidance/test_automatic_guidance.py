"""Controlled RGB/geometry tests. No private image or real model is sent."""
import hashlib
import json
import time
import numpy as np
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from manual2ar_contracts.automatic_guidance import FunctionalObservation,GuidanceRecipe
from manual2ar_contracts.machine_frame import MachineFrame
from manual2ar_perception.spatial import project
from manual2ar.modules.guidance.spatial.simulation import calibration,jpeg
from tests.backend.guidance.test_spatial import app,begin,frame


def prepare(app,c,monkeypatch,guide=True):
    service=app.state.spatial;api=begin(c,'camera');s=service.sessions[api.split('/')[-1]];s.calibration=calibration()
    service.config['vlm']['api_key']='controlled-test-key'
    world={'screw_upper':[.04,.05,.18],'screw_lower':[.04,.05,.15]}
    if guide:world.update(guide_top=[.055,.05,.19],guide_bottom=[.055,.05,.14])
    locations={}
    for i,x in [(1,-.13),(2,.13)]:
        pose=np.diag([1.,-1.,-1.,1.]);pose[:3,3]=[x,.02,.7]
        raw=jpeg(i);sha=hashlib.sha256(raw).hexdigest()
        s.frames[i]={'raw':raw,'sha256':sha,'number':i,'pose':{'transform':pose,'reprojection_px':.1},'at':time.monotonic(),'size':(960,720),'action_id':'holder.base','target_id':'main'}
        locations[sha]=dict(zip(world,project(list(world.values()),pose,np.array(s.calibration['matrix']),np.zeros(5)).tolist()))
    def observe(client,config,raw,reference,folder):return locations[hashlib.sha256(raw).hexdigest()],'两颗螺丝可见。'
    monkeypatch.setattr('manual2ar.modules.guidance.spatial.automatic_vision.observe',observe)
    reference=c.post(api+'/automatic/reference',json={'client_frame_id':1,'placement_confirmed':True})
    assert reference.status_code==200,reference.text
    return service,api,s,locations


def pair(c,api):
    views=[]
    for i in [1,2]:
        r=c.post(api+'/automatic/views',json={'action_id':'holder.base','client_frame_id':i})
        assert r.status_code==200,r.text
        views.append(r.json()['view_id'])
    return dict(action_id='holder.base',first_view=views[0],second_view=views[1],second_frame=2)


def test_from_zero_two_photos_configures_all_u7_anchors_but_never_verifies(app,monkeypatch):
    with TestClient(app) as c:
        service,api,s,_=prepare(app,c,monkeypatch)
        assert s.machine_frame['placement_method']=='printed_reference'
        assert len(s.machine_frame['source_frame_sha256'])==1 and s.targets=={}
        r=c.post(api+'/automatic/candidates',json=pair(c,api));assert r.status_code==200,r.text
        candidate=r.json();assert candidate['target_count']==3 and candidate['slide_ready']
        assert s.targets=={} and not s.u7_checks
        assert c.post(api+'/automatic/confirm',json={'candidate_id':candidate['candidate_id'],'confirmed':False}).status_code==422
        assert c.post(api+'/automatic/confirm',json={'candidate_id':candidate['candidate_id'],'confirmed':True}).status_code==200
        assert len(s.targets)==3 and not s.u7_checks
        assert np.allclose(s.targets['holder.base']['points_m'][1],[.04,.05,.18])
        assert np.allclose(s.targets['holder.slide']['points_m'][1],[.055,.05,.14])
        # Preconfiguring a second animation cannot bypass base installation verification.
        assert c.post(api+'/frames',json=frame(number=3,action='holder.slide')).status_code==409
        assert c.post(api+'/automatic/confirm',json={'candidate_id':candidate['candidate_id'],'confirmed':True}).status_code==409
        assert service.profile('rigs',s.rig).is_file()


def test_invisible_guide_preserves_screws_and_offers_explicit_direction_illustration(app,monkeypatch):
    with TestClient(app) as c:
        _,api,s,_=prepare(app,c,monkeypatch,False)
        candidate=c.post(api+'/automatic/candidates',json=pair(c,api)).json()
        assert candidate['target_count']==2 and candidate['slide_ready'] and candidate['slide_illustrative']
        assert c.post(api+'/automatic/confirm',json={'candidate_id':candidate['candidate_id'],'confirmed':True}).status_code==200
        assert 'holder.slide' not in s.targets


@pytest.mark.parametrize('fault',['same_view','wrong_frame','stale','changed_profile','bad_geometry'])
def test_rejects_bad_or_stale_correspondence_without_writing_targets(app,monkeypatch,fault):
    with TestClient(app) as c:
        service,api,s,_=prepare(app,c,monkeypatch);command=pair(c,api)
        if fault=='same_view':command['second_view']=command['first_view']
        if fault=='wrong_frame':command['second_frame']=1
        if fault=='stale':s.automatic_views[command['first_view']]['created']-=301
        if fault=='changed_profile':service.store_profile(service.profile('motions',s.rig),{})
        if fault=='bad_geometry':s.automatic_views[command['second_view']]['points']['screw_upper'][1]+=100
        r=c.post(api+'/automatic/candidates',json=command)
        assert r.status_code in (409,422),r.text
        assert not s.targets and not service.profile('rigs',s.rig).exists()


def test_backup_reset_preserves_intrinsics_and_invalidates_pending_candidates(app,monkeypatch):
    with TestClient(app) as c:
        service,api,s,_=prepare(app,c,monkeypatch)
        service.store_profile(service.profile('cameras',s.camera),s.calibration)
        cmd=pair(c,api);candidate=c.post(api+'/automatic/candidates',json=cmd).json()
        old=service.profile('machines',s.rig).read_bytes()
        result=c.post(api+'/automatic/reset',json={'confirmed':True});assert result.status_code==200
        backup=service.root/'profile-backups'/result.json()['backup_id']
        assert (backup/'machines.json').read_bytes()==old
        assert s.calibration and service.profile('cameras',s.camera).is_file()
        assert not s.machine_frame and not s.targets and not s.frames
        assert c.post(api+'/automatic/confirm',json={'candidate_id':candidate['candidate_id'],'confirmed':True}).status_code==409


def test_manual_override_and_concurrent_edit_are_preserved(app,monkeypatch):
    with TestClient(app) as c:
        service,api,s,_=prepare(app,c,monkeypatch)
        manual={'points_m':[[.1,.1,.1],[.1,.2,.1]],'target_label':'manual'}
        s.targets['holder.base']=manual;s.authorized.add('holder.base')
        service.store_profile(service.profile('rigs',s.rig),s.targets)
        candidate=c.post(api+'/automatic/candidates',json=pair(c,api)).json()
        assert candidate['target_count']==2
        assert c.post(api+'/automatic/confirm',json={'candidate_id':candidate['candidate_id'],'confirmed':True}).status_code==200
        assert s.targets['holder.base']==manual
        # A changed motion profile cannot silently become the basis of an old preview.
        candidate=c.post(api+'/automatic/candidates',json=pair(c,api)).json()
        service.store_profile(service.profile('motions',s.rig),{'changed':'another editor'})
        assert c.post(api+'/automatic/confirm',json={'candidate_id':candidate['candidate_id'],'confirmed':True}).status_code==409


def test_reference_requires_confirmation_and_does_not_erase_existing_targets(app,monkeypatch):
    with TestClient(app) as c:
        _,api,s,_=prepare(app,c,monkeypatch)
        assert c.post(api+'/automatic/reference',json={'client_frame_id':1,'placement_confirmed':False}).status_code==422
        s.targets['holder.base']={'manual':True}
        assert c.post(api+'/automatic/reference',json={'client_frame_id':1,'placement_confirmed':True}).status_code==409
        assert s.targets['holder.base']=={'manual':True}
        assert c.get('/api/guidance/spatial/workboard.pdf').content.startswith(b'%PDF')


def test_zoomed_features_are_mapped_back_to_original_frame(app,tmp_path):
    from manual2ar.modules.guidance.spatial.automatic_vision import observe
    class VLM:
        def __init__(self):self.calls=0
        def chat_structured(self,**kw):
            self.calls+=1;assert len(kw['images_base64'])==2
            if self.calls==1:return {'action_id':'holder.base','target_id':'base','status':'found','confidence':.99,'evidence':'灰色底座','next_action':'','bbox_0_1000':[400,350,600,650],'foreground_point_0_1000':[500,500]}
            return {'points':[dict(id=k,status='found',point_0_1000=[500,y],confidence=.99,evidence='真实可见') for k,y in [('screw_upper',250),('screw_lower',750),('guide_top',100),('guide_bottom',900)]],'next_action':'可核对'}
    config=app.state.spatial.config
    model=VLM();points,_=observe(model,config,jpeg(1),app.state.spatial.references['base'],tmp_path)
    metadata=json.loads((tmp_path/'features.json').read_text());x,y,r,b=metadata['crop_rect']
    assert np.allclose(points['screw_upper'],[x+.5*(r-x),y+.25*(b-y)])
    assert model.calls==2 and (tmp_path/'features-preview.jpg').is_file()
    bad={'points':[dict(id='screw_upper',status='unseen',point_0_1000=[500,500],confidence=.9,evidence='不可见')]*4,'next_action':''}
    with pytest.raises(ValidationError):FunctionalObservation.model_validate(bad)


@pytest.mark.parametrize('category',['highlight','movement','gesture','tool','context'])
def test_five_visual_categories_share_recipe_contract(category):
    value=GuidanceRecipe(id='test.recipe',category=category,action_id='holder.base',target_ids=['main'],feature_ids=['screw_upper'],presentation_id='u7.holder_base',operation='highlight',direction_source='none',citation_ids=['official'])
    assert value.illustrative_only


def test_unreliable_optional_guide_does_not_discard_reliable_screws(app,monkeypatch):
    with TestClient(app) as c:
        _,api,s,_=prepare(app,c,monkeypatch)
        command=pair(c,api)
        s.automatic_views[command['second_view']]['points']['guide_top'][1]+=100
        r=c.post(api+'/automatic/candidates',json=command);assert r.status_code==200,r.text
        assert r.json()['target_count']==2 and r.json()['slide_illustrative']


def test_edits_from_other_session_before_observation_are_merged(app,monkeypatch):
    with TestClient(app) as c:
        service,api,s,_=prepare(app,c,monkeypatch)
        other={'purge.slide':{'points_m':[[0,0,.1],[.1,0,.1]],'target_label':'other editor'}}
        service.store_profile(service.profile('rigs',s.rig),other)
        candidate=c.post(api+'/automatic/candidates',json=pair(c,api)).json()
        assert c.post(api+'/automatic/confirm',json={'candidate_id':candidate['candidate_id'],'confirmed':True}).status_code==200
        assert s.targets['purge.slide']==other['purge.slide']


def test_old_screws_only_profiles_supply_runtime_illustration_without_rewriting_them(app,monkeypatch):
    with TestClient(app) as c:
        service,api,s,_=prepare(app,c,monkeypatch,False)
        candidate=c.post(api+'/automatic/candidates',json=pair(c,api)).json()
        c.post(api+'/automatic/confirm',json={'candidate_id':candidate['candidate_id'],'confirmed':True})
        path=service.profile('rigs',s.rig);before=path.read_bytes()
        s.u7_checks={'base':{'status':'completed'}}
        result=c.post(api+'/frames',json=frame(number=3,action='holder.slide')).json()
        assert result['target_ready'],result
        assert result['placement_method']=='base_reference_illustration'
        assert '不代表' in result['placement_note']
        assert result['visual']['presentation']['presentation_id']=='u7.holder_slide'
        assert path.read_bytes()==before and 'holder.slide' not in s.targets
        target=service.automatic.slide_reference(s)
        assert np.allclose(target['points_m'][1],[.04,.05,.165])
        # Cache preview is allowed before explicit reuse, but live geometry is not activated.
        other=begin(c,'camera',u7_fixture_verified=True)
        other_s=service.sessions[other.split('/')[-1]];other_s.calibration=calibration()
        preview=c.post(other+'/frames',json=frame(action='holder.slide')).json()
        assert preview['preflight']['can_start'] and not preview['target_ready']
        assert c.post(other+'/reuse',json={'confirmed':True}).status_code==200
        assert c.post(other+'/frames',json=frame(number=2,action='holder.slide')).json()['target_ready']
        s.invalidated['holder.base']='moved'
        assert service.automatic.slide_reference(s) is None


def test_slide_reference_refuses_wrong_machine_or_bad_screw_geometry():
    from manual2ar.modules.guidance.spatial.placement import slide_illustration
    machine={'frame_id':'a'*32,'marker_from_machine':np.eye(4).ravel().tolist()}
    def target(z):return dict(marker_id=23,marker_length_m=.08,machine_frame_id='a'*32,points_m=[[.04,.1,z],[.04,.05,z]])
    targets={'holder.base':target(.18),'holder.base::second':target(.15)}
    assert slide_illustration(targets,machine)
    targets['holder.base']['machine_frame_id']='b'*32;assert slide_illustration(targets,machine) is None
    targets['holder.base']['machine_frame_id']='a'*32
    targets['holder.base::second']['points_m'][1][2]=.2
    assert slide_illustration(targets,machine) is None
