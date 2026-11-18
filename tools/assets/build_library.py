"""Author the local teaching library with Blender; commit portable meshes, keep sources/previews external."""
import argparse
import hashlib
import html
import json
from pathlib import Path
import shutil
import subprocess
from manual2ar.paths import ROOT
from manual2ar.visuals.library import VisualAssetLibrary


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--blender',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);parser.add_argument('--unboxing',action='store_true',help='Build the extended photo-plane library; preserve the reviewed U7 catalog and meshes');parser.add_argument('--preview',action='store_true');args=parser.parse_args()
    output=args.output.resolve()
    if output==ROOT or output.is_relative_to(ROOT):raise ValueError('Editable sources/previews must be outside the source worktree')
    recipe=ROOT/"resources/visuals/v1/recipes/u7.json"
    addon=recipe.parent/"unboxing.json"
    style=ROOT/"resources/visuals/v1/style.json"
    if json.loads(recipe.read_text())["palette"]!=json.loads(style.read_text())["palette"]:raise ValueError("Recipe violates the shared style palette")
    def native(p):return subprocess.check_output(['wslpath','-w',str(p)],text=True).strip() if args.blender.suffix.lower()=='.exe' else str(p)
    command=[str(args.blender),'--background','--factory-startup','--python-exit-code','1','--python',native(ROOT/'tools/assets/blender_library.py'),'--','--recipe',native(recipe),'--output',native(output)]
    if args.unboxing:command.extend(['--addon',native(addon)])
    if args.preview:command.append('--preview')
    subprocess.run(command,check=True)
    target=ROOT/'resources/visuals/v1'
    catalog_name='unboxing.catalog.json' if args.unboxing else 'catalog.json'
    catalog=json.loads((output/'catalog.json').read_bytes())
    shared=set()
    if args.unboxing:
        original=VisualAssetLibrary(target/'catalog.json')
        # Use the exact published mesh bytes and metadata even across Blender/platform versions.
        shared=set(original.assets)
        catalog['assets']=[asset for asset in catalog['assets'] if asset['id'] not in shared]
        catalog['assets'][:0]=json.loads(original.path.read_bytes())['assets']
        for asset in original.catalog.assets:
            shutil.copyfile(target/asset.mesh.path, output/asset.mesh.path)
    (output/'catalog.json').write_text(json.dumps(catalog,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    library=VisualAssetLibrary(output/'catalog.json')
    for asset in library.catalog.assets:
        if asset.id not in shared:
            shutil.copyfile(output/asset.mesh.path,target/asset.mesh.path)
    shutil.copyfile(output/'catalog.json',target/catalog_name)
    manifest={'schema_version':'manual2ar-asset-build-v1','recipe_sha256':hashlib.sha256(recipe.read_bytes()).hexdigest(),'generator_sha256':hashlib.sha256((ROOT/'tools/assets/blender_library.py').read_bytes()).hexdigest(),'style_sha256':hashlib.sha256(style.read_bytes()).hexdigest(),'catalog_sha256':library.sha256,'files':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in output.iterdir() if p.suffix in ('.blend','.fbx','.png')}}
    if args.unboxing:manifest['addon_sha256']=hashlib.sha256(addon.read_bytes()).hexdigest()
    (output/'build-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    cards=[]
    for a in catalog['assets']:
        name=html.escape(a['id']);label=html.escape(a['label'])
        cards.append(f'<article><h2>{label}</h2><img src="{name}.png" alt="{label}"><p>{name} · {a["mesh"]["triangles"]} triangles</p><a href="{name}.blend">Blender source</a> · <a href="{name}.fbx">FBX</a></article>')
    (output/'index.html').write_text('<!doctype html><html lang="zh"><meta charset="utf-8"><title>Manual2AR teaching asset library</title><style>body{background:#081620;color:#eef8fc;font:18px system-ui;padding:30px}main{display:flex;flex-wrap:wrap;gap:24px}article{background:#102b38;border-radius:20px;padding:20px;width:360px}img{width:100%}a{color:#35d5ec}</style><h1>Manual2AR · 开箱教学资产</h1><p>统一简化示意模型；不作为尺寸、安装完成或扭矩的证据。</p><main>'+''.join(cards)+'</main></html>',encoding='utf-8')
    print('Validated portable catalog/meshes:',target)
    print('Editable Blender/FBX/previews:',output)


if __name__=='__main__':main()
