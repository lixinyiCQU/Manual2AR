"""Export user-facing desktop demo extras outside source; never copies operator secrets."""
import hashlib
import json
import os
import shutil
import subprocess
from manual2ar.application.config import load,resolve
from manual2ar.paths import ROOT
from manual2ar.modules.guidance.spatial.printing import sheets
from manual2ar.application.manage import sync
from .desktop_provenance import verify_build, repository_sources, PROOF, fingerprint


def main():
    config=load();builds=resolve(config['paths']['builds']);target=builds/'Manual2AR-Windows'
    sync(config)
    build=verify_build(ROOT,target)
    (target/'空间定位与相机标定.pdf').write_bytes(sheets())
    # Historical audits are archived outside source and are not user-facing delivery files.
    for name in ['实测审计与更新.md','开箱扩展说明.md','模块二开箱原型.md','U4视觉指导.md',
                 'U7实测说明.md','U7测试审计与更新.md','U7视觉资产库使用说明.md','U7资产实测审计.md',
                 'U7引导式安装.md','画面显示契约.md','U7动作管理.md','打印机工作坐标与动作参数.md']:
        (target/name).unlink(missing_ok=True)
    shutil.copyfile(ROOT/'docs/OPERATIONS.md',target/'使用说明.md')
    shutil.copyfile(ROOT/'deploy/windows/Start-Desktop.ps1',target/'Start-Desktop.ps1')
    launcher=b'@echo off\r\npowershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Start-Desktop.ps1"'
    (target/'启动空间演示.cmd').write_bytes(launcher+b' -SpatialDemo\r\nif errorlevel 1 pause\r\n')
    (target/'启动教学系统.cmd').write_bytes(launcher+b'\r\nif errorlevel 1 pause\r\n')
    distro=os.environ.get('WSL_DISTRO_NAME','Ubuntu')
    if any(c in distro for c in '"\r\n'):raise ValueError('Invalid WSL distribution name')
    (target/'启动后端.cmd').write_bytes(('@echo off\r\nwsl.exe -d "'+distro+'" --cd "'+str(ROOT)+'" bash run.sh start\r\npause\r\n').encode('utf-8'))
    sources=repository_sources(ROOT)
    committed=not subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True).strip()
    proof_path=builds/'validation-camera-fix/hardware-proof.json'
    proof=json.loads(proof_path.read_text()) if proof_path.is_file() else {}
    capture_tested=(proof.get('local_capture_success') is True
        and proof.get('launcher_sha256')==hashlib.sha256((ROOT/'deploy/windows/Start-Desktop.ps1').read_bytes()).hexdigest()
        and proof.get('camera_adapter_sha256')==hashlib.sha256((ROOT/'apps/unity/Manual2AR/Assets/Manual2AR/Scripts/Guidance/Spatial/SpatialCamera.cs').read_bytes()).hexdigest())
    manifest={'schema_version':'manual2ar-spatial-delivery-v1','baseline':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'frontend_assembly_sha256':hashlib.sha256((target/'Manual2AR_Data/Managed/Assembly-CSharp.dll').read_bytes()).hexdigest(),
        'changes_committed':committed,'source_sha256':sources,'backend_url':config['backend']['public_url'],
        'desktop_build_sha256':fingerprint(target/PROOF),'validated_frontend_inputs':len(build['frontend_inputs']),
        'physical_camera_tested':capture_tested,'physical_spatial_accuracy_tested':False,'real_vlm_calls_in_validation':0,
        'validation_folders':[p.name for p in sorted(builds.glob('validation-spatial-*'))]}
    from manual2ar.visuals.library import VisualAssetLibrary
    library=VisualAssetLibrary(ROOT/'resources/visuals/v1/catalog.json')
    manifest['visual_asset_library']={**library.descriptor(),'asset_ids':list(library.assets),'presentation_ids':list(library.presentations),'scope':'U7 only','source_worktree':str(ROOT)}
    local=ROOT/'apps/unity/Manual2AR/Assets/Manual2AR/Resources/GuidanceLocal/provenance.json'
    manifest['local_reference_assets']=json.loads(local.read_text()) if local.is_file() else None
    (target/'delivery.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    archive=shutil.make_archive(str(builds/'Manual2AR-Windows'),'zip',target.parent,target.name)
    print(archive)


if __name__=='__main__':main()
