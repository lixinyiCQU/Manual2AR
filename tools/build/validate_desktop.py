"""Real Windows Unity check from WSL; isolated project and outputs, no source Library.

Example: python -B -m tools.build.validate_desktop --unity /mnt/e/.../Unity.exe
 --project /mnt/c/.../Manual2AR-Validation --build
"""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import urllib.request
from manual2ar.application.config import load,resolve
from manual2ar.application.manage import package
from manual2ar.paths import ROOT
from .desktop_provenance import project_inputs, check_inputs, seal_build


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--unity',type=Path,required=True)
    parser.add_argument('--project',type=Path,required=True);parser.add_argument('--build',action='store_true')
    args=parser.parse_args();config=load();builds=resolve(config['paths']['builds'])
    output=builds/('validation-spatial-'+datetime.now().strftime('%Y%m%d-%H%M%S'));output.mkdir(parents=True)
    project=args.project.absolute()
    if project==ROOT or project.is_relative_to(ROOT):raise ValueError('Validation project must be outside source worktree')
    package(config);project.mkdir(parents=True,exist_ok=True)
    inputs=project_inputs(ROOT/'apps/unity/Manual2AR')
    for name in ['Assets','Packages','ProjectSettings']:
        if (project/name).exists():shutil.rmtree(project/name)
        shutil.copytree(builds/'Manual2AR'/name,project/name)
    editor=project/'Assets/Editor';editor.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(ROOT/'tests/unity/ProductValidation.cs',editor/'ProductValidation.cs')
    shutil.copyfile(ROOT/'tools/build/WindowsPlayerBuild.cs',editor/'WindowsPlayerBuild.cs')
    def override(value):
        if isinstance(value,dict):
            for k,v in value.items():
                if k=='backend_url':value[k]='http://127.0.0.1:18010'
                else:override(v)
        elif isinstance(value,list):
            for v in value:override(v)
    for file in (project/'Assets/StreamingAssets').glob('*.json'):
        value=json.loads(file.read_text());override(value);file.write_text(json.dumps(value,ensure_ascii=False),encoding='utf-8')
    validation=project/'Validation'
    if validation.exists():shutil.rmtree(validation)
    def win(path):return subprocess.check_output(['wslpath','-w',str(path)],text=True).strip()
    environment={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'}
    with (output/'backend.log').open('w') as log:
        server=subprocess.Popen([sys.executable,'-B','-m','tests.serve_product'],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,env=environment)
        try:
            direct=urllib.request.build_opener(urllib.request.ProxyHandler({}))
            for attempt in range(60):
                if server.poll() is not None:raise RuntimeError('Controlled backend exited; see backend.log')
                try:
                    direct.open('http://127.0.0.1:18010/health',timeout=1).close();break
                except OSError:time.sleep(.5)
            else:raise RuntimeError('Controlled backend did not start')
            result=subprocess.run([str(args.unity),'-batchmode','-projectPath',win(project),'-executeMethod','ProductValidation.Run','-logFile',win(output/'unity.log')],timeout=300)
            if validation.exists():shutil.copytree(validation,output/'screenshots')
            if result.returncode or not (validation/'success.json').is_file():raise RuntimeError('Unity check failed; see unity.log and screenshots/errors.txt')
        finally:
            server.terminate()
            try:server.wait(timeout=10)
            except subprocess.TimeoutExpired:server.kill();server.wait()
    if args.build:
        # Production player uses actual operator configuration, not controlled provider URLs.
        for file in (builds/'Manual2AR/Assets/StreamingAssets').glob('*.json'):
            shutil.copyfile(file,project/'Assets/StreamingAssets'/file.name)
        check_inputs(ROOT,project,inputs)
        player=project/'Player'
        if player.exists():shutil.rmtree(player)
        player.mkdir()
        result=subprocess.run([str(args.unity),'-batchmode','-quit','-projectPath',win(project),'-executeMethod','WindowsPlayerBuild.Build',
            '--manual2ar-output',win(player/'Manual2AR.exe'),'-logFile',win(output/'build.log')],timeout=600)
        if result.returncode:raise RuntimeError('Windows build failed; see build.log')
        seal_build(ROOT,project,player,inputs,json.loads((validation/'success.json').read_text()))
        target=builds/'Manual2AR-Windows'
        if target.exists():shutil.rmtree(target)
        shutil.copytree(player,target)
        shutil.make_archive(str(builds/'Manual2AR-Windows'),'zip',target.parent,target.name)
    print(output)


if __name__=='__main__':main()
