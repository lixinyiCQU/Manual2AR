"""Migration boundaries: resource injection, editable installs and deployable bundles."""
import ast
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

import pytest
from manual2ar.paths import ROOT
from manual2ar.application.config import load,for_module
from manual2ar.resources import ResourceStore
from manual2ar.modules.guidance.registry import TaskRegistry
from tools.build.inference_bundle import gpu_bundle


def test_resource_registry_rejects_directory_escape(tmp_path):
    (tmp_path/'catalog.json').write_text(json.dumps(dict(schema_version='manual2ar-resources-v1',resources={'bad':'../outside.json'})))
    with pytest.raises(ValueError):ResourceStore(tmp_path).path('bad')


def test_tutorial_registry_uses_configured_resources_not_workspace(tmp_path):
    shutil.copytree(ROOT/'resources',tmp_path/'resources')
    catalog=tmp_path/'resources/modules/guidance.json'
    value=json.loads(catalog.read_text());value['tasks']=value['tasks'][:1];value['tasks'][0]['title']='Isolated catalog'
    catalog.write_text(json.dumps(value))
    registry=TaskRegistry({'resources_dir':str(tmp_path/'resources')})
    assert len(registry.catalog()['tasks'])==1
    assert registry.catalog()['tasks'][0]['title']=='Isolated catalog'
    assert len(TaskRegistry().catalog()['tasks'])==4


def test_backend_loads_explicit_config_outside_workspace(tmp_path):
    config=json.loads((ROOT/'configs/app.example.json').read_text())
    for key in config['paths']:config['paths'][key]=str(ROOT/config['paths'][key])
    (tmp_path/'configs').mkdir();path=tmp_path/'configs/app.local.json';path.write_text(json.dumps(config))
    code="""
import json,sys
from manual2ar.application.config import load,for_module
from manual2ar.application.server import create_app
from manual2ar.modules.guidance.registry import TaskRegistry
c=load(sys.argv[1])
assert len(TaskRegistry(for_module(c,'guidance')).catalog()['tasks'])==4
app=create_app(c)
assert len(app.state.modules)==3
print('installed backend created')
"""
    result=subprocess.run([sys.executable,'-B','-c',code,str(path)],cwd=tmp_path,capture_output=True,text=True)
    assert result.returncode==0,result.stderr


def test_runtime_and_shared_packages_obey_dependency_direction():
    roots={
        'packages/contracts/src':{'manual2ar','manual2ar_perception','manual2ar_inference','deploy'},
        'packages/perception/src':{'manual2ar','manual2ar_inference','deploy'},
        'apps/inference/src':{'manual2ar','manual2ar_perception','deploy','google'},
    }
    for folder,forbidden in roots.items():
        paths=list((ROOT/folder).rglob('*.py'));assert paths
        for path in paths:
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node,ast.ImportFrom) and not node.level and node.module:
                    assert node.module.split('.')[0] not in forbidden,(path,node.module)
                elif isinstance(node,ast.Import):
                    assert all(n.name.split('.')[0] not in forbidden for n in node.names),path


def test_inference_export_is_self_contained_and_records_canonical_sources(tmp_path):
    with zipfile.ZipFile(gpu_bundle()) as bundle:
        manifest=json.loads(bundle.read('bundle.manifest.json'))
        assert set(bundle.namelist())==set(manifest)|{'bundle.manifest.json'}
        for name,item in manifest.items():
            assert '.local.' not in name and not name.endswith('.ipynb')
            body=bundle.read(name)
            assert body==(ROOT/item['source']).read_bytes()
            assert hashlib.sha256(body).hexdigest()==item['sha256']
        assert 'deploy/hpc/run.sh' in manifest
        bundle.extractall(tmp_path)
    code="""
from pathlib import Path
import manual2ar_inference.app as app
import manual2ar_contracts.gpu as protocol
assert Path(app.__file__).is_relative_to(Path.cwd())
assert Path(protocol.__file__).is_relative_to(Path.cwd())
assert protocol.PROTOCOL=='manual2ar-learning-cutie-v2'
"""
    result=subprocess.run([sys.executable,'-B','-c',code],cwd=tmp_path,capture_output=True,text=True)
    assert result.returncode==0,result.stderr


def test_connection_export_preserves_protocol_and_private_permissions(tmp_path):
    path=tmp_path/'service.json';token='controlled-test-only-private-token'
    path.write_text(json.dumps({'api_token':token}));output=tmp_path/'worker.connection.local.json'
    result=subprocess.run([sys.executable,'-B','-m','deploy.common.launch','connection','--config',str(path),
        '--work-dir',str(tmp_path),'--public-url','http://127.0.0.1:8021','--output',str(output)],cwd=ROOT,capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    assert token not in result.stdout and token not in result.stderr
    value=json.loads(output.read_text())
    assert value['api_token']==token and value['protocol']=='manual2ar-learning-cutie-v2'
    assert output.stat().st_mode&0o777==0o600


def test_unity_generated_assets_are_ignored_but_font_guids_are_source():
    names=['configs/app.local.json','configs/inference.connection.local.json',
           'apps/unity/Manual2AR/Assets/StreamingAssets/App.json',
           'apps/unity/Manual2AR/Assets/Manual2AR/Resources/Fonts/NotoSansCJKsc-Regular.otf']
    for name in names:
        assert subprocess.run(['git','check-ignore','-q',name],cwd=ROOT).returncode==0,name
    meta=ROOT/'apps/unity/Manual2AR/Assets/Manual2AR/Resources/Fonts/NotoSansCJKsc-Regular.otf.meta'
    assert meta.is_file()
    assert subprocess.run(['git','check-ignore','-q',str(meta)],cwd=ROOT).returncode==1


def test_notebook_embeds_the_same_service_bundle_without_local_settings():
    notebook=json.loads((ROOT/'deploy/colab/Manual2AR_GPU.ipynb').read_text())
    for cell in notebook['cells']:
        if cell['cell_type']!='code':continue
        code=''.join(cell['source']);compile(code,'notebook','exec')
        for node in ast.parse(code).body:
            if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='SOURCE_ZIP' for t in node.targets):
                with zipfile.ZipFile(io.BytesIO(base64.b64decode(ast.literal_eval(node.value)))) as bundle:
                    manifest=json.loads(bundle.read('bundle.manifest.json'))
                    for name,item in manifest.items():assert bundle.read(name)==(ROOT/item['source']).read_bytes()
                return
    pytest.fail('Missing canonical inference bundle')
