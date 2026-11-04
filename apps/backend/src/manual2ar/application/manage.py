"""Build public assets and run the composed application from one configuration."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import zipfile
from . import ROOT
from .config import load, for_module, public, resolve


def sync(c):
    from manual2ar.modules.learning.knowledge import KnowledgeStore
    from manual2ar.modules.learning.manage import public as learning_public
    from manual2ar.modules.guidance.manage import public as guidance_public
    from manual2ar.modules.guidance.registry import TaskRegistry
    from manual2ar.modules.inspection.manage import public as inspection_public
    target = ROOT / 'apps/unity/Manual2AR/Assets/StreamingAssets'
    target.mkdir(parents=True, exist_ok=True)
    current={'Services.json','App.json','Learning.json','LearningKnowledge.json','LearningImages','Guidance.json',
             'GuidanceCatalog.json','GuidanceReferences','Inspection.json','InspectionCatalog.json'}
    for old in target.iterdir():
        if old.name not in current and old.name.removesuffix('.meta') not in current:
            if old.is_dir():shutil.rmtree(old)
            else:old.unlink()
    def export(name, value):
        (target / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    export('App.json', public(c))
    from .services import ServiceRegistry
    export('Services.json',ServiceRegistry(c).catalog())
    for name, renderer, filename in [('learning', learning_public, 'Learning.json'),
                                     ('guidance', guidance_public, 'Guidance.json'),
                                     ('inspection', inspection_public, 'Inspection.json')]:
        export(filename, renderer(for_module(c, name)))
    if resolve(c['paths']['wiki_archive']).is_file():
        store = KnowledgeStore(for_module(c, 'learning'))
        try:
            export('LearningKnowledge.json', store.bundle)
            pictures = target / 'LearningImages'
            if pictures.exists(): shutil.rmtree(pictures)
            pictures.mkdir()
            for identity in store.images:
                (pictures / (identity + '.png')).write_bytes(store.image_bytes(identity))
        finally: store.wiki.close()
    else:
        # Do not leave a stale knowledge pack if the source is intentionally removed.
        (target / 'LearningKnowledge.json').unlink(missing_ok=True)
    registry = TaskRegistry(for_module(c, 'guidance'))
    export('GuidanceCatalog.json', registry.catalog())
    pictures = target / 'GuidanceReferences'
    if pictures.exists(): shutil.rmtree(pictures)
    pictures.mkdir()
    hashes = {}
    for task in registry.packages.values():
        for name, item in task.images.items():
            if name in hashes and hashes[name] != item['sha256']:
                raise ValueError('Reference image identity collision')
            hashes[name] = item['sha256']
            (pictures / name).write_bytes(task.checked_file(item['path'], item['sha256']))
    from manual2ar.resources import ResourceStore
    store=ResourceStore.configured(for_module(c,'learning'))
    shutil.copyfile(store.path('module.inspection.catalog'), target / 'InspectionCatalog.json')
    fonts=ROOT/'apps/unity/Manual2AR/Assets/Manual2AR/Resources/Fonts'
    fonts.mkdir(parents=True,exist_ok=True)
    for name in ['NotoSansCJKsc-Regular.otf','OFL.txt']:
        shutil.copyfile(store.path('ui.font').parent/name, fonts/name)
    # Portable, verified runtime assets; no Blender installation or SDK is required by Unity.
    from manual2ar.visuals.library import VisualAssetLibrary
    library=VisualAssetLibrary(store.path('visual.guidance.catalog'))
    visual=ROOT/'apps/unity/Manual2AR/Assets/Manual2AR/Resources/VisualGuidance'
    if visual.exists():shutil.rmtree(visual)
    visual.mkdir(parents=True)
    shutil.copyfile(library.path,visual/'catalog.json')
    for asset in library.catalog.assets:
        target=visual/asset.mesh.path;target.parent.mkdir(exist_ok=True)
        shutil.copyfile(library.path.parent/asset.mesh.path,target)
    refs=store.path('task.unboxing.spatial').parent/'vision'
    dest=visual/'references';dest.mkdir(exist_ok=True)
    for name in ['base_reference.jpg','holder_reference.jpg','installation_reference.jpg']:shutil.copyfile(refs/name,dest/name)
    print('统一公开配置与教学资料已生成；未导出凭据。')


def package(c):
    sync(c)
    output = resolve(c['paths']['builds'])
    output.mkdir(parents=True, exist_ok=True)
    target = output / 'Manual2AR'
    if target.exists(): shutil.rmtree(target)
    source = ROOT / 'apps/unity/Manual2AR'
    for name in ['Assets', 'Packages', 'ProjectSettings']:
        shutil.copytree(source / name, target / name)
    (target / 'START_HERE_ZH.md').write_text(
        '# Manual2AR Unity 前端\n\n'
        '在 Unity Hub 中添加本文件夹，使用 Unity 2022.3.34f1 打开。\n'
        '打开 Assets/Manual2AR/Scenes/Welcome.unity，再按 Play。\n\n'
        '后端位于源码工作树 '+ROOT.name+'；在 WSL 的源码目录运行 `bash run.sh start`。\n'
        '本包连接的后端地址为：'+c['backend']['public_url']+'。\n\n'
        'API Key、GPU 连接和其他参数只修改源码目录的 configs/app.local.json；修改后运行 `bash run.sh package` 更新本包。\n'
        '云端视觉服务使用源码中的 deploy/colab/Manual2AR_GPU.ipynb。\n'
        '主页可选择部件认知、操作指导和打印状态检查。\n',encoding='utf-8')
    with (target/'START_HERE_ZH.md').open('a',encoding='utf-8') as guide:
        guide.write('\n开箱指导：Welcome → 操作指导 → 打印机开箱 → 外挂料盘／单机；U4—U7 可进入空间指导。\n'
                    '选择相机；有有效位置时自动循环示意。首次实机使用先完成相机标定和作用点设置。\n'
                    '完整说明见源码 docs/MODULE_TWO_UNBOXING_PROTOTYPE.md。\n')
    archive = output / 'Manual2AR-Unity.zip'
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as z:
        for p in sorted(target.rglob('*')):
            if p.is_file(): z.write(p, Path(target.name) / p.relative_to(target))
    print(archive)
    return archive


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['start', 'sync', 'package'])
    args = parser.parse_args()
    c = load()
    if args.command == 'start':
        sync(c)
        import uvicorn
        from .server import create_app
        uvicorn.run(create_app(c), host=c['backend']['host'], port=c['backend']['port'])
    elif args.command == 'sync': sync(c)
    else: package(c)

if __name__ == '__main__': main()
