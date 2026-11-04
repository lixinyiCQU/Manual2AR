"""Validate a manually exported mesh and update its registered hash/version. No renderer edits."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
from manual2ar.paths import ROOT
from manual2ar_contracts.visual_assets import AssetMesh
from manual2ar.visuals.library import VisualAssetLibrary


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--mesh',type=Path,required=True);parser.add_argument('--version',required=True);args=parser.parse_args()
    mesh=AssetMesh.model_validate_json(args.mesh.read_bytes());folder=ROOT/'resources/visuals/v1';catalog=json.loads((folder/'catalog.json').read_text())
    asset=next((a for a in catalog['assets'] if a['id']==mesh.asset_id),None)
    if asset is None:raise ValueError('Register metadata, functional anchors and clips in catalog.json before importing a new ID')
    if args.version==asset['version']:raise ValueError('Use a new semantic version when replacing published geometry')
    asset['version']=args.version;asset['mesh'].update(sha256=hashlib.sha256(args.mesh.read_bytes()).hexdigest(),vertices=sum(len(p.vertices)//3 for p in mesh.parts),triangles=sum(len(p.triangles)//3 for p in mesh.parts))
    with tempfile.TemporaryDirectory() as temp:
        staged=Path(temp)/'library';shutil.copytree(folder,staged);shutil.copyfile(args.mesh,staged/asset['mesh']['path']);(staged/'catalog.json').write_text(json.dumps(catalog,ensure_ascii=False,separators=(',',':'))+'\n')
        VisualAssetLibrary(staged/'catalog.json')
        shutil.copyfile(staged/asset['mesh']['path'],folder/asset['mesh']['path']);shutil.copyfile(staged/'catalog.json',folder/'catalog.json')
    print('Imported verified asset:',mesh.asset_id,args.version,'; sync and restart backend before testing')


if __name__=='__main__':main()
