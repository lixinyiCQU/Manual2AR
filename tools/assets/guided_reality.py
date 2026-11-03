"""Import one reviewed FBX; never execute upstream code or import a Quest project.

The complete upstream checkout stays outside this worktree. Imported experimental
assets are ignored by Git. This does not assign a license to upstream material.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from manual2ar.paths import ROOT

PIN='478d9d7318b175c65715650ab4d45ae36433d8a0'
URL='https://github.com/AdaZhao1211/Guided-Reality-Unity'


def import_arrow(source):
    source=Path(source).resolve()
    commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=source,text=True).strip()
    if commit!=PIN:raise ValueError('Expected reviewed Guided Reality commit '+PIN)
    relative=Path('Assets/Resources/GuidanceModels/downArrow.fbx')
    raw=(source/relative).read_bytes()
    tracked=subprocess.check_output(['git','show',PIN+':'+relative.as_posix()],cwd=source)
    if raw!=tracked:raise ValueError('Local FBX differs from reviewed commit')
    target=ROOT/'apps/unity/Manual2AR/Assets/Manual2AR/Resources/GuidanceLocal'
    target.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(source/relative,target/'downArrow.fbx')
    manifest={'schema_version':'manual2ar-local-reference-asset-v1','source':URL,'commit':PIN,
        'file':relative.as_posix(),'sha256':hashlib.sha256(raw).hexdigest(),
        'usage':'local_experiment_only','license_status':'not_specified_in_reviewed_repository',
        'runtime_asset':'movement_arrow','adapter':'mesh normalization and same-frame calibrated projection',
        'upstream_code_executed':False}
    (target/'provenance.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    return target


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    args=parser.parse_args()
    print(import_arrow(args.source))


if __name__=='__main__':main()
