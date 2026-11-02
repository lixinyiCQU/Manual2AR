"""Export user-facing desktop demo extras outside source; never copies operator secrets."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
from manual2ar.application.config import load,resolve
from manual2ar.paths import ROOT
from manual2ar.modules.guidance.spatial.printing import sheets


def main():
    config=load();builds=resolve(config['paths']['builds']);target=builds/'Manual2AR-Windows'
    if not (target/'Manual2AR.exe').is_file():raise ValueError('Build Windows Player before packaging delivery extras')
    (target/'空间定位与相机标定.pdf').write_bytes(sheets())
    shutil.copyfile(ROOT/'docs/MODULE_TWO_SPATIAL_DEMO.md',target/'使用说明.md')
    shutil.copyfile(ROOT/'docs/MODULE_TWO_SPATIAL_PROGRESS.md',target/'实测审计与更新.md')
    shutil.copyfile(ROOT/'docs/UNBOXING_SPATIAL_EXTENSION.md',target/'开箱扩展说明.md')
    shutil.copyfile(ROOT/'deploy/windows/Start-Desktop.ps1',target/'Start-Desktop.ps1')
    launcher=b'@echo off\r\npowershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Start-Desktop.ps1"'
    (target/'启动空间演示.cmd').write_bytes(launcher+b' -SpatialDemo\r\nif errorlevel 1 pause\r\n')
    (target/'启动教学系统.cmd').write_bytes(launcher+b'\r\nif errorlevel 1 pause\r\n')
    distro=os.environ.get('WSL_DISTRO_NAME','Ubuntu')
    if any(c in distro for c in '"\r\n'):raise ValueError('Invalid WSL distribution name')
    (target/'启动后端.cmd').write_bytes(('@echo off\r\nwsl.exe -d "'+distro+'" --cd "'+str(ROOT)+'" bash run.sh start\r\npause\r\n').encode('utf-8'))
    # Canonical source manifest makes an uncommitted build reviewable without a Git mutation.
    paths=[]
    for relative in ['apps/backend/src/manual2ar/modules/guidance/spatial',
                     'apps/unity/Manual2AR/Assets/Manual2AR/Scripts/Guidance/Spatial',
                     'resources/tasks/bambu_a1_mini/unboxing/spatial']:
        paths.extend(p for p in (ROOT/relative).rglob('*') if p.is_file() and '__pycache__' not in p.parts)
    paths.extend(ROOT/p for p in ['packages/perception/src/manual2ar_perception/spatial.py','packages/contracts/src/manual2ar_contracts/spatial.py',
        'apps/backend/src/manual2ar/modules/guidance/server.py','apps/backend/src/manual2ar/application/manage.py',
        'apps/unity/Manual2AR/Assets/Manual2AR/Scripts/Guidance/PrinterGuidanceController.cs',
        'apps/unity/Manual2AR/Assets/Manual2AR/Scripts/Editor/AppEditorSetup.cs',
        'apps/unity/Manual2AR/Assets/Manual2AR/Scripts/Common/AppIconGraphic.cs',
        'apps/unity/Manual2AR/Assets/Manual2AR/Scenes/SpatialGuidance.unity',
        'docs/MODULE_TWO_SPATIAL_DEMO.md','docs/MODULE_TWO_SPATIAL_PROGRESS.md','docs/UNBOXING_SPATIAL_EXTENSION.md','tools/evaluation/spatial_recording.py','tests/backend/guidance/test_spatial.py','tests/backend/guidance/test_unboxing_extension.py',
        'tests/unity/ProductValidation.cs','tools/build/validate_desktop.py','tools/build/WindowsPlayerBuild.cs',
        'tools/build/spatial_delivery.py','resources/catalog.json','README.md',
        'deploy/windows/Start-Desktop.ps1',
        'apps/unity/Manual2AR/Assets/Manual2AR/Scripts/Common/WindowsLocalBootstrap.cs',
        'apps/unity/Manual2AR/Assets/Manual2AR/Scripts/Common/WindowsLocalBootstrap.cs.meta'])
    sources={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}
    proof_path=builds/'validation-camera-fix/hardware-proof.json'
    proof=json.loads(proof_path.read_text()) if proof_path.is_file() else {}
    capture_tested=(proof.get('local_capture_success') is True
        and proof.get('launcher_sha256')==hashlib.sha256((ROOT/'deploy/windows/Start-Desktop.ps1').read_bytes()).hexdigest()
        and proof.get('camera_adapter_sha256')==hashlib.sha256((ROOT/'apps/unity/Manual2AR/Assets/Manual2AR/Scripts/Guidance/Spatial/SpatialCamera.cs').read_bytes()).hexdigest())
    manifest={'schema_version':'manual2ar-spatial-delivery-v1','baseline':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'changes_committed':False,'source_sha256':sources,'backend_url':config['backend']['public_url'],
        'physical_camera_tested':capture_tested,'physical_spatial_accuracy_tested':False,'real_vlm_calls_in_validation':0,
        'validation_folders':[p.name for p in sorted(builds.glob('validation-spatial-*'))]}
    (target/'delivery.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    archive=shutil.make_archive(str(builds/'Manual2AR-Windows'),'zip',target.parent,target.name)
    print(archive)


if __name__=='__main__':main()
