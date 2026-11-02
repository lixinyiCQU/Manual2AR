"""Recorded failure modes, perspective support and independent service states."""
import copy
import json
import cv2
import numpy as np
import pytest
from pydantic import ValidationError
from manual2ar.integrations.vlm.client import VisionError
from manual2ar.modules.inspection.contracts import Observation
from manual2ar.modules.inspection.normalization import normalize_observation
from manual2ar.modules.inspection.plate_scope import update_scope
from tests.backend.inspection.test_pipeline import env, inspect, observation


@pytest.mark.parametrize('alias,canonical',[('bbox_0_0_1000','bbox_0_1000'),('target_point_0_000','target_point_0_1000')])
def test_observed_key_typo_is_repaired_without_second_model_request(env,alias,canonical):
    value=env[2].value;value['plate'][alias]=value['plate'].pop(canonical)
    initial=copy.deepcopy(value)
    result=inspect(env)
    assert len(env[2].calls)==1
    assert result['decision']['status']=='anomaly_detected'
    assert result['public_result']['foreign_object_state']=='fail'
    assert value==initial
    root=env[4].log_root/env[1].rsplit('/',1)[-1]/result['check_id']
    assert json.loads((root/'normalization_1.json').read_text())[0]['to']==canonical
    assert alias in json.loads((root/'vlm_raw_1.json').read_text())['plate']


def test_alias_cannot_override_conflicting_geometry_or_unknown_fields():
    value=observation();value['plate']['bbox_0_0_1000']=[0,0,1000,1000]
    normalized,_=normalize_observation(value)
    with pytest.raises(ValidationError):Observation.model_validate(normalized)
    value=observation();value['plate']['random_geometry']=[1,2,3,4]
    with pytest.raises(ValidationError):Observation.model_validate(normalize_observation(value)[0])


def test_redundant_misspelled_null_does_not_discard_valid_canonical_point(env):
    env[2].value['plate']['target_point_0_000']=None
    point=env[2].value['plate']['target_point_0_1000']
    result=inspect(env)
    assert result['decision']['status']=='anomaly_detected'
    assert result['objects'][0]['target_point_0_1000']==point
    assert len(env[2].calls)==1


def test_invalid_geometry_stays_invalid_and_returns_specific_failure(env):
    env[2].value['plate']['bbox_0_1000']=[900,50,100,950]
    result=inspect(env)
    assert result['public_result']['status']=='service_unavailable'
    assert result['public_result']['failure_code']=='invalid_response'
    assert len(env[2].calls)==2
    assert '几何校验' in env[2].calls[1]['prompt']
    assert not result['objects']


@pytest.mark.parametrize('code',['network','credentials','timeout','rate_limited'])
def test_user_error_is_enumerated_and_does_not_leak_api_details(env,code):
    def fail(**kwargs):raise VisionError('PRIVATE KEY and raw API error',code=code)
    env[2].chat_structured=fail
    result=inspect(env)
    assert result['public_result']['failure_code']==code
    assert 'PRIVATE' not in json.dumps(result)
    assert result['public_result']['status']=='service_unavailable'


def test_oblique_plate_with_foreign_object_is_detected_without_top_down_gate(env):
    env[2].value['plate'].update(polygon_0_1000=[[250,100],[750,100],[950,950],[50,950]],bbox_0_1000=[50,100,950,950],target_point_0_1000=[250,750])
    result=inspect(env)
    assert result['decision']['status']=='anomaly_detected'
    assert result['public_result']['plate_state']=='pass'
    assert result['objects'][1]['tracking_ready']


def masks_and_rows(box):
    plate=np.zeros((200,200),np.uint8)
    cv2.fillConvexPoly(plate,np.array([[70,20],[130,20],[185,180],[15,180]],np.int32),1)
    obj=np.zeros_like(plate);x,y,w,h=box;obj[y:y+h,x:x+w]=1
    rows=[dict(id='build_plate',kind='plate',tracking_ready=True,bbox_0_1000=[75,100,930,905]),
          dict(id='foreign_object_1',kind='foreign_object',tracking_ready=True,bbox_0_1000=[x*5,y*5,(x+w)*5,(y+h)*5])]
    return rows,{'build_plate':plate.astype(bool),'foreign_object_1':obj.astype(bool)}


def test_outside_trapezoid_but_inside_axis_box_is_removed():
    rows,masks=masks_and_rows((25,30,12,12));removed=set()
    assert update_scope(rows,masks,removed)
    assert removed=={'foreign_object_1'} and rows[1]['scope_evidence']['overlap_pixels']==0
    assert 'foreign_object_1' not in masks


@pytest.mark.parametrize('box',[(85,60,15,15),(60,45,20,20)])
def test_holes_or_partial_contact_do_not_prove_removal(box):
    rows,masks=masks_and_rows(box);masks['build_plate']&=~masks['foreign_object_1']
    removed=set();update_scope(rows,masks,removed)
    assert not removed and rows[1]['tracking_ready']


def test_cropped_plate_cannot_certify_off_plate():
    rows,masks=masks_and_rows((0,30,10,10));masks['build_plate'][0,100]=True
    removed=set();update_scope(rows,masks,removed)
    assert not removed
