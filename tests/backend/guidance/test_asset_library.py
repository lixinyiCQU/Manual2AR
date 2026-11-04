"""Portable assets must be bounded, reproducible and unable to assert installation success."""
import hashlib
import json
from pathlib import Path
import numpy as np
import pytest
from fastapi.testclient import TestClient
from manual2ar.resources import ResourceStore
from manual2ar.visuals.library import VisualAssetLibrary
from manual2ar.modules.guidance.spatial.visuals import compose
from manual2ar_contracts.visual_assets import VisualPresentation, AssetCatalog, AssetMesh
from tests.backend.guidance.test_spatial import app,begin,frame,calibration,pose


def library():return VisualAssetLibrary(ResourceStore.configured().path('visual.guidance.catalog'))


def test_catalog_assets_are_bounded_and_originally_authored():
    lib=library();assert len(lib.assets)==6
    for asset in lib.assets.values():
        assert asset.license=='project-authored' and asset.geometry_accuracy=='teaching_proxy'
        assert asset.mesh.triangles<=2400 and asset.units=='metres'
    assert {p.id for p in lib.catalog.presentations}=={'u7.holder_base','u7.holder_slide'}


@pytest.mark.parametrize('action,identity',[('holder.base','u7.holder_base'),('holder.slide','u7.holder_slide')])
def test_end_to_end_u7_preserves_identity_and_authored_reference(app,action,identity):
    with TestClient(app) as client:
        descriptor=client.get('/api/guidance/spatial/config').json()['asset_library']
        api=begin(client);response=client.post(api+'/frames',json=frame(action=action)).json()
        visual=response['visual'];p=VisualPresentation.model_validate(visual['presentation'])
        assert p.presentation_id==identity and p.catalog_sha256==descriptor['catalog_sha256']
        assert p.reference_space_id=='calibrated-marker' and p.illustrative_only
        assert len(p.instances)==(4 if action=='holder.base' else 3) and response['source_sha256']==frame(action=action)['source_sha256']
        assert not app.state.guidance.meta


def test_tool_tip_and_slide_path_do_not_depend_on_mesh_origin_guessing(app):
    points=np.array([[.08,.04,.02],[.08,-.03,.02]]);c=calibration();lib=library()
    for key in ['holder.base','holder.slide']:
        visual=compose(app.state.spatial.actions[key],'目标',points,pose(0),np.array(c['matrix']),np.zeros(5),lib)
        p=visual['presentation'];item=p['instances'][0];t=np.asarray(item['reference_from_asset']).reshape(4,4)
        assert np.allclose(t[:3,3],points[1] if key=='holder.base' else points[0])
        assert np.allclose(t[:3,1]/np.linalg.norm(t[:3,1]),(1 if key=='holder.base' else -1)*(points[1]-points[0])/np.linalg.norm(points[1]-points[0]))
        if key=='holder.slide':assert np.allclose(t[:3,3]+item['path_m'],points[1])


def test_hash_mismatch_is_rejected_before_client_export(tmp_path):
    import shutil
    original=library().path;shutil.copytree(original.parent,tmp_path/'assets');p=tmp_path/'assets/meshes/tool.hex_driver.json';p.write_bytes(p.read_bytes()+b' ')
    with pytest.raises(ValueError,match='hash mismatch'):VisualAssetLibrary(tmp_path/'assets/catalog.json')


def test_registry_rejects_unknown_clips_and_bad_transforms():
    payload=json.loads(library().path.read_text());payload['presentations'][0]['layers'][0]['clip_id']='invented'
    with pytest.raises(ValueError,match='Unknown asset/clip'):AssetCatalog.model_validate(payload)
    lib=library();p=lib.compose('u7.holder_base',np.array([[0,0,0],[0,.08,0]]),np.eye(3));p['instances'][0]['reference_from_asset'][0]=-1
    with pytest.raises(ValueError,match='positive uniform scale'):VisualPresentation.model_validate(p)


def test_mesh_invalid_topology_cannot_enter_library():
    asset=library().assets['tool.hex_driver'];payload=json.loads((library().path.parent/asset.mesh.path).read_text());payload['parts'][0]['triangles'][0]=999999
    with pytest.raises(ValueError,match='topology'):AssetMesh.model_validate(payload)


def test_exported_tool_shaft_reaches_functional_tip_along_declared_axis():
    lib=library();a=lib.assets['tool.hex_driver'];mesh=AssetMesh.model_validate_json((lib.path.parent/a.mesh.path).read_bytes())
    shaft=np.asarray(next(p for p in mesh.parts if p.id=='shaft').vertices).reshape(-1,3)
    # Catches Blender's unevaluated object matrix exporting a Z-cylinder instead of a Y tool.
    assert abs(shaft[:,1].max())<1e-6 and abs(shaft[:,1].min()+.07)<1e-6
    assert np.ptp(shaft[:,0])<.004 and np.ptp(shaft[:,2])<.004


def test_other_chapters_keep_existing_asset_contract(app):
    with TestClient(app) as client:
        api=begin(client);r=client.post(api+'/frames',json=frame(action='zlock.remove')).json()
        assert r['visual']['presentation'] is None and r['visual']['asset']['asset_id']=='hex_key'


def test_two_screws_share_frame_but_require_independent_authorized_anchors(app):
    with TestClient(app) as client:
        api=begin(client);service=app.state.spatial;s=service.sessions[api.split('/')[-1]]
        both=client.post(api+'/frames',json=frame(action='holder.base')).json()
        assert len(both['companion_visuals'])==1
        assert both['visual']['label']=='底座螺丝 1' and both['companion_visuals'][0]['label']=='底座螺丝 2'
        assert both['visual']['anchor']!=both['companion_visuals'][0]['anchor']
        s.authorized.remove('holder.base::second')
        assert client.post(api+'/frames',json=frame(number=2,action='holder.base')).json()['companion_visuals']==[]
        s.authorized.add('holder.base::second');s.invalidated['holder.base::second']={'reason':'moved'}
        assert client.post(api+'/frames',json=frame(number=3,action='holder.base')).json()['companion_visuals']==[]



def test_u7_display_contains_only_legend_and_one_registered_imperative(app):
    from manual2ar_contracts.guidance_display import GuidanceDisplay
    with TestClient(app) as client:
        api=begin(client)
        for i,action in enumerate(['holder.base','holder.slide'],1):
            reply=client.post(api+'/frames',json=frame(action=action,number=i)).json()
            visual=reply['visual'];display=GuidanceDisplay.model_validate(visual['display'])
            assert not visual['text_labels']
            assert display.action_id==action and len(display.legend)==4
            assert len(display.instruction.position_m)==3
            assert display.instruction.sentence.endswith('。')
            assert ('，用' if action=='holder.base' else '，将') in display.instruction.sentence
            assert not any(word in str(display.model_dump()) for word in ['检查通过','1/2','2/2','倒计时'])
