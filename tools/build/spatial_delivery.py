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
    shutil.copyfile(ROOT/'docs/MODULE_TWO_UNBOXING_PROTOTYPE.md',target/'模块二开箱原型.md')
    shutil.copyfile(ROOT/'docs/U4_VISUAL_GUIDANCE.md',target/'U4视觉指导.md')
    shutil.copyfile(ROOT/'docs/U7_VISUAL_GUIDANCE.md',target/'U7实测说明.md')
    shutil.copyfile(ROOT/'docs/U7_TEST_REVIEW.md',target/'U7测试审计与更新.md')
    shutil.copyfile(ROOT/'docs/VISUAL_ASSET_LIBRARY.md',target/'U7视觉资产库使用说明.md')
    shutil.copyfile(ROOT/'docs/U7_ASSET_TEST_REVIEW.md',target/'U7资产实测审计.md')
    shutil.copyfile(ROOT/'docs/U7_GUIDED_FLOW.md',target/'U7引导式安装.md')
    shutil.copyfile(ROOT/'docs/GUIDANCE_DISPLAY_CONTRACT.md',target/'画面显示契约.md')
    shutil.copyfile(ROOT/'docs/U7_ACTION_MANAGEMENT.md',target/'U7动作管理.md')
    shutil.copyfile(ROOT/'docs/PRINTER_WORK_COORDINATES.md',target/'打印机工作坐标与动作参数.md')
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
                     'apps/backend/src/manual2ar/visuals',
                     'apps/unity/Manual2AR/Assets/Manual2AR/Scripts/VisualGuidance',
                     'resources/visuals',
                     'apps/unity/Manual2AR/Assets/Manual2AR/Scripts/Guidance/Spatial',
                     'resources/tasks/bambu_a1_mini/unboxing/spatial']:
        paths.extend(p for p in (ROOT/relative).rglob('*') if p.is_file() and '__pycache__' not in p.parts)
    paths.extend(ROOT/p for p in ['packages/perception/src/manual2ar_perception/spatial.py','packages/contracts/src/manual2ar_contracts/spatial.py',
        'apps/backend/src/manual2ar/modules/guidance/server.py','apps/backend/src/manual2ar/modules/guidance/service.py','apps/backend/src/manual2ar/modules/guidance/lesson.py','apps/backend/src/manual2ar/modules/guidance/experience.py','apps/backend/src/manual2ar/application/manage.py',
        'apps/unity/Manual2AR/Assets/Manual2AR/Scripts/Guidance/PrinterGuidanceController.cs','apps/unity/Manual2AR/Assets/Manual2AR/Scripts/Guidance/PrinterGuidanceLayout.cs','apps/unity/Manual2AR/Assets/Manual2AR/Scripts/Guidance/PrinterGuidanceLesson.cs','apps/unity/Manual2AR/Assets/Manual2AR/Scripts/Guidance/PrinterGuidanceLesson.cs.meta','apps/unity/Manual2AR/Assets/Manual2AR/Scripts/Guidance/LessonReadableText.cs','apps/unity/Manual2AR/Assets/Manual2AR/Scripts/Guidance/LessonReadableText.cs.meta','apps/unity/Manual2AR/Assets/Manual2AR/Scripts/Guidance/PrinterGuidanceLayout.cs.meta','apps/unity/Manual2AR/Assets/Manual2AR/Scripts/Guidance/GuidanceStepView.cs','apps/unity/Manual2AR/Assets/Manual2AR/Scripts/Guidance/PrinterGuidanceModels.cs','apps/unity/Manual2AR/Assets/Manual2AR/Scripts/Guidance/PrinterUnboxingModels.cs',
        'apps/unity/Manual2AR/Assets/Manual2AR/Scripts/Editor/AppEditorSetup.cs',
        'apps/unity/Manual2AR/Assets/Manual2AR/Scripts/Common/AppIconGraphic.cs',
        'apps/unity/Manual2AR/Assets/Manual2AR/Scenes/SpatialGuidance.unity',
        'docs/MODULE_TWO_UNBOXING_PROTOTYPE.md','docs/MODULE_TWO_SPATIAL_DEMO.md','docs/MODULE_TWO_SPATIAL_PROGRESS.md','docs/UNBOXING_SPATIAL_EXTENSION.md','tools/evaluation/spatial_recording.py','tests/backend/guidance/test_spatial.py','tests/backend/guidance/test_unboxing_extension.py','tests/backend/guidance/test_experience.py','tests/backend/guidance/test_lesson.py','resources/modules/guidance_lessons.v1.json',
        'tests/unity/ProductValidation.cs','tools/build/validate_desktop.py','tools/build/WindowsPlayerBuild.cs',
        'tools/build/spatial_delivery.py','resources/catalog.json','README.md',
        'deploy/windows/Start-Desktop.ps1',
        'apps/unity/Manual2AR/Assets/Manual2AR/Scripts/Common/WindowsLocalBootstrap.cs',
        'apps/unity/Manual2AR/Assets/Manual2AR/Scripts/Common/WindowsLocalBootstrap.cs.meta'])
    paths.extend(ROOT/p for p in ['docs/U4_VISUAL_GUIDANCE.md','docs/U7_VISUAL_GUIDANCE.md','tests/backend/guidance/test_visual_assets.py',
        'tools/assets/guided_reality.py','apps/unity/Manual2AR/Assets/Manual2AR/Scripts/Editor/GuidanceLocalAssetImport.cs'])
    paths.extend(ROOT/p for p in ['docs/U7_TEST_REVIEW.md','tests/backend/guidance/test_vision_context.py',
        'apps/unity/Manual2AR/Assets/Manual2AR/Scripts/Common/AppDropdown.cs',
        'apps/unity/Manual2AR/Assets/Manual2AR/Scripts/Common/AppDropdown.cs.meta'])
    paths.extend(ROOT/p for p in ['apps/unity/Manual2AR/Assets/Manual2AR/Scripts/Common/AppModalBackdrop.cs','apps/unity/Manual2AR/Assets/Manual2AR/Scripts/Common/AppModalBackdrop.cs.meta','apps/unity/Manual2AR/Assets/Manual2AR/Scripts/Guidance/PrinterGuidanceWiki.cs','apps/unity/Manual2AR/Assets/Manual2AR/Scripts/Guidance/PrinterGuidanceWiki.cs.meta','apps/unity/Manual2AR/Assets/Manual2AR/Scripts/Learning/PrinterLearningWikiView.cs','apps/unity/Manual2AR/Assets/Manual2AR/Scripts/Learning/PrinterLearningController.cs','apps/unity/Manual2AR/Assets/Manual2AR/Scripts/Inspection/PrinterInspectionController.cs','apps/backend/src/manual2ar/modules/learning/server.py','tests/backend/test_knowledge.py', 'docs/U7_GUIDED_FLOW.md','tests/serve_product.py','tests/backend/guidance/test_tutorial.py','apps/unity/Manual2AR/Assets/Manual2AR/Scripts/Common/AppShell.cs','docs/U7_ACTION_MANAGEMENT.md','docs/VISUAL_ASSET_LIBRARY.md','packages/contracts/src/manual2ar_contracts/visual_assets.py',
        'tools/assets/build_library.py','tools/assets/blender_library.py','tools/assets/export_blend.py','tools/assets/import_mesh.py','tests/backend/guidance/test_asset_library.py','tests/backend/guidance/test_u7_parts.py','tests/backend/guidance/test_machine_frame.py','tests/backend/guidance/test_u7_sequence.py','tests/backend/guidance/test_workflow.py','apps/backend/src/manual2ar/modules/guidance/u7_sequence.py','apps/backend/src/manual2ar/modules/guidance/tutorial.py','apps/backend/src/manual2ar/modules/guidance/engine.py','packages/contracts/src/manual2ar_contracts/machine_frame.py','docs/PRINTER_WORK_COORDINATES.md','docs/U7_ASSET_TEST_REVIEW.md','apps/backend/src/manual2ar/application/config.py','apps/backend/src/manual2ar/application/defaults/guidance.json'])
    paths.extend(ROOT/p for p in ['apps/backend/src/manual2ar/integrations/perception/cpu_client.py','tests/backend/guidance/test_cpu_mask_client.py'])
    paths.extend(ROOT/p for p in ['packages/contracts/src/manual2ar_contracts/guidance_display.py','tests/backend/guidance/test_display_contract.py','docs/GUIDANCE_DISPLAY_CONTRACT.md'])
    sources={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}
    proof_path=builds/'validation-camera-fix/hardware-proof.json'
    proof=json.loads(proof_path.read_text()) if proof_path.is_file() else {}
    capture_tested=(proof.get('local_capture_success') is True
        and proof.get('launcher_sha256')==hashlib.sha256((ROOT/'deploy/windows/Start-Desktop.ps1').read_bytes()).hexdigest()
        and proof.get('camera_adapter_sha256')==hashlib.sha256((ROOT/'apps/unity/Manual2AR/Assets/Manual2AR/Scripts/Guidance/Spatial/SpatialCamera.cs').read_bytes()).hexdigest())
    manifest={'schema_version':'manual2ar-spatial-delivery-v1','baseline':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'frontend_assembly_sha256':hashlib.sha256((target/'Manual2AR_Data/Managed/Assembly-CSharp.dll').read_bytes()).hexdigest(),
        'changes_committed':False,'source_sha256':sources,'backend_url':config['backend']['public_url'],
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
