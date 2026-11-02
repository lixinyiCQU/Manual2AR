"""User entry, evidence versions and service composition never expose private config."""
from copy import deepcopy
import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from manual2ar.application.services import ServiceRegistry
from manual2ar.paths import ROOT
from tests.backend.test_application import configuration,application


def test_services_list_binds_snapshot_and_reuses_module_page(tmp_path):
    config=configuration(tmp_path)
    with TestClient(application(config)) as client:
        listing=client.get('/api/app/services')
        assert listing.status_code==200
        data=listing.json();assert not data['import_available']
        assert data['schema_version']=='manual2ar-services-v1'
        service=data['services'][0]
        assert service['id']=='bambu-a1-mini'
        assert service['snapshot_version']=='20261024T145623Z_e2655a'
        assert service['backend_url']==config['backend']['public_url']
        assert [m['scene'] for m in service['modules']]==['PrinterLearning','PrinterGuidance','PrinterInspection']
        assert client.get('/api/app/services/bambu-a1-mini').json()==service
        assert client.get('/api/app/services/not-imported').status_code==404
        for secret in ('api_key','api_token','snapshot_resource',str(ROOT),config['vlm']['api_key']):
            assert secret not in listing.text


def registry_config(tmp_path):
    config=json.loads((ROOT/'configs/app.example.json').read_text())
    resources=tmp_path/'resources';resources.mkdir()
    (resources/'catalog.json').write_text(json.dumps({'schema_version':'manual2ar-resources-v1','resources':{'app.services':'services.json','snapshot':'snapshot.json'}}))
    (resources/'snapshot.json').write_text(json.dumps({'snapshot_id':'fixture-v2','archive_sha256':'f'*64}))
    doc=json.loads((ROOT/'resources/services/catalog.json').read_text())
    item=doc['services'][0];item['snapshot_resource']='snapshot'
    other=deepcopy(item);other.update(id='second-task-service',title='第二个教学服务',headline='同一页面，独立内容',module_ids=['guidance'],backend_url='https://teaching.example.test')
    doc['services'].append(other)
    (resources/'services.json').write_text(json.dumps(doc))
    config['paths']['resources']=str(resources)
    return config,resources,doc


def test_additional_service_uses_own_modules_and_endpoint_without_new_scene(tmp_path):
    config,resources,doc=registry_config(tmp_path)
    registry=ServiceRegistry(config)
    second=registry.detail('second-task-service')
    assert second['snapshot_version']=='fixture-v2'
    assert second['modules'][0]['scene']=='PrinterGuidance'
    assert len(second['modules'])==1 and second['backend_url']=='https://teaching.example.test'


@pytest.mark.parametrize('change', ['duplicate','unknown-module','url-credentials','duplicate-module'])
def test_invalid_service_bindings_are_rejected(tmp_path,change):
    config,resources,doc=registry_config(tmp_path)
    if change=='duplicate':doc['services'][1]['id']=doc['services'][0]['id']
    if change=='unknown-module':doc['services'][0]['module_ids']=['arbitrary-scene']
    if change=='url-credentials':doc['services'][0]['backend_url']='https://private:secret@example.test'
    if change=='duplicate-module':doc['services'][0]['module_ids']=['learning','learning']
    (resources/'services.json').write_text(json.dumps(doc))
    with pytest.raises(ValueError):ServiceRegistry(config)
