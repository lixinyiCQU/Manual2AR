import copy,json
import pytest
from pydantic import ValidationError
from manual2ar_contracts.guidance_display import GuidanceDisplay
from manual2ar.modules.guidance.spatial.display import DisplayCatalog
from manual2ar.resources import ResourceStore
from manual2ar.visuals.library import VisualAssetLibrary


def payload():
    store=ResourceStore.configured();return json.loads((store.path('task.unboxing.spatial').parent/'display.json').read_text())


def test_two_imperatives_have_separate_semantic_fields_and_no_status():
    for key,data in payload().items():
        value=GuidanceDisplay.model_validate(data)
        assert value.instruction.position_m is None
        assert value.instruction.sentence==('在支架底座上，用内六角扳手拧紧两颗底座螺丝，使底座贴合并固定。' if key=='holder.base' else '对准底座导槽，将料盘支架滑入支架底座，直至滑到底部。')
        assert len({item.id for item in value.legend})==len(value.legend)
        assert 'status' not in value.model_dump()


@pytest.mark.parametrize('field,value',[('sentence','已经安装完成'),('actor','<script>'),('position_m',[0,0,2]),('position_m',[float('nan'),0,0])])
def test_invalid_future_agent_output_is_rejected(field,value):
    data=copy.deepcopy(payload()['holder.base']);data['source']='agent';data['instruction'][field]=value
    with pytest.raises(ValidationError):GuidanceDisplay.model_validate(data)


def test_unknown_model_cannot_enter_catalog(tmp_path):
    data=payload();data['holder.base']['legend'][0]['asset_id']='unreviewed-model'
    path=tmp_path/'display.json';path.write_text(json.dumps(data))
    lib=VisualAssetLibrary(ResourceStore.configured().path('visual.guidance.catalog'))
    with pytest.raises(ValueError,match='Unknown legend asset'):DisplayCatalog(path,lib,data)
