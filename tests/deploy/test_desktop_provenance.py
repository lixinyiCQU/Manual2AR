"""A current source tree must never certify a stale or edited Windows Player."""
import shutil
import subprocess
from pathlib import Path
import pytest
from tools.build.desktop_provenance import project_inputs, check_inputs, seal_build, verify_build, repository_sources


@pytest.fixture
def built(tmp_path):
    root=tmp_path/'repo';source=root/'apps/unity/Manual2AR'
    for relative in ['Assets/Guide.cs','Assets/StreamingAssets/App.json','Packages/manifest.json','ProjectSettings/ProjectVersion.txt']:
        p=source/relative;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('original')
    project=tmp_path/'isolated';shutil.copytree(source,project)
    player=tmp_path/'player'
    for relative in ['Manual2AR.exe','Manual2AR_Data/Managed/Assembly-CSharp.dll']:
        p=player/relative;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'compiled')
    expected=project_inputs(source)
    seal_build(root,project,player,expected,{'runtime_errors':0,'scenes':4})
    return root,source,project,player,expected


def test_matching_build_accepts_delivery_extras(built):
    root,source,project,player,expected=built
    (player/'使用说明.md').write_text('User documentation')
    assert verify_build(root,player)['frontend_inputs']==expected


@pytest.mark.parametrize('change',['script','config','added','removed'])
def test_stale_player_rejected_after_any_unity_input_change(built,change):
    root,source,project,player,expected=built
    if change=='script':(source/'Assets/Guide.cs').write_text('new code')
    elif change=='config':(source/'Assets/StreamingAssets/App.json').write_text('new endpoint')
    elif change=='added':(source/'Assets/New.cs').write_text('new code')
    else:(source/'Assets/Guide.cs').unlink()
    with pytest.raises(ValueError,match='inputs differ'):verify_build(root,player)


def test_build_rejects_input_changes_during_compilation(built):
    root,source,project,player,expected=built
    (project/'Assets/Guide.cs').write_text('different compiled code')
    with pytest.raises(ValueError,match='inputs changed'):check_inputs(root,project,expected)


def test_build_rejects_unexpected_staged_code(built):
    root,source,project,player,expected=built
    (project/'Assets/Unexpected.cs').write_text('extra runtime code')
    with pytest.raises(ValueError,match='inputs changed'):check_inputs(root,project,expected)


@pytest.mark.parametrize('change',['dll','missing','added'])
def test_edited_or_incomplete_payload_rejected(built,change):
    root,source,project,player,expected=built
    if change=='dll':(player/'Manual2AR_Data/Managed/Assembly-CSharp.dll').write_bytes(b'old build')
    elif change=='missing':(player/'Manual2AR.exe').unlink()
    else:(player/'Manual2AR_Data/Managed/Extra.dll').write_bytes(b'extra assembly')
    with pytest.raises(ValueError,match='payload'):verify_build(root,player)


def test_legacy_build_without_record_is_not_trusted(tmp_path):
    with pytest.raises(ValueError,match='No verified'):verify_build(tmp_path,tmp_path)


def test_repository_fingerprints_include_new_source_and_skip_private_settings(tmp_path):
    subprocess.run(['git','init','-q',str(tmp_path)],check=True)
    (tmp_path/'.gitignore').write_text('*.local.json\n')
    (tmp_path/'new.py').write_text('source')
    (tmp_path/'app.local.json').write_text('private settings')
    assert set(repository_sources(tmp_path))=={'.gitignore','new.py'}
