"""Author the local U7 library with Blender; commit portable meshes, keep sources/previews external."""
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
    parser=argparse.ArgumentParser();parser.add_argument('--blender',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);parser.add_argument('--preview',action='store_true');args=parser.parse_args()
    output=args.output.absolute()
    if output==ROOT or output.is_relative_to(ROOT):raise ValueError('Editable sources/previews must be outside the source worktree')
    recipe=ROOT/"resources/visuals/v1/recipes/u7.json"
    style=ROOT/"resources/visuals/v1/style.json"
    if json.loads(recipe.read_text())["palette"]!=json.loads(style.read_text())["palette"]:raise ValueError("Recipe violates the shared style palette")
    def native(p):return subprocess.check_output(['wslpath','-w',str(p)],text=True).strip() if args.blender.suffix.lower()=='.exe' else str(p)
    command=[str(args.blender),'--background','--factory-startup','--python-exit-code','1','--python',native(ROOT/'tools/assets/blender_library.py'),'--','--recipe',native(ROOT/'resources/visuals/v1/recipes/u7.json'),'--output',native(output)]
    if args.preview:command.append('--preview')
    subprocess.run(command,check=True)
    VisualAssetLibrary(output/'catalog.json')
    target=ROOT/'resources/visuals/v1'
    shutil.copyfile(output/'catalog.json',target/'catalog.json');shutil.copytree(output/'meshes',target/'meshes',dirs_exist_ok=True)
    manifest={'schema_version':'manual2ar-asset-build-v1','recipe_sha256':hashlib.sha256(recipe.read_bytes()).hexdigest(),'generator_sha256':hashlib.sha256((ROOT/'tools/assets/blender_library.py').read_bytes()).hexdigest(),'style_sha256':hashlib.sha256(style.read_bytes()).hexdigest(),'catalog_sha256':hashlib.sha256((target/'catalog.json').read_bytes()).hexdigest(),'files':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in output.iterdir() if p.suffix in ('.blend','.fbx','.png')}}
    (output/'build-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    cards=[]
    for a in json.loads((target/'catalog.json').read_text())['assets']:
        name=html.escape(a['id']);label=html.escape(a['label'])
        cards.append(f'<article><h2>{label}</h2><img src="{name}.png" alt="{label}"><p>{name} · {a["mesh"]["triangles"]} triangles</p><a href="{name}.blend">Blender source</a> · <a href="{name}.fbx">FBX</a></article>')
    (output/'index.html').write_text('<!doctype html><html lang="zh"><meta charset="utf-8"><title>Manual2AR U7 asset library</title><style>body{background:#081620;color:#eef8fc;font:18px system-ui;padding:30px}main{display:flex;flex-wrap:wrap;gap:24px}article{background:#102b38;border-radius:20px;padding:20px;width:360px}img{width:100%}a{color:#35d5ec}</style><h1>Manual2AR · U7 教学资产</h1><p>统一简化示意模型；不作为尺寸、安装完成或扭矩的证据。</p><main>'+''.join(cards)+'</main></html>',encoding='utf-8')
    print('Validated portable catalog/meshes:',target)
    print('Editable Blender/FBX/previews:',output)


if __name__=='__main__':main()
