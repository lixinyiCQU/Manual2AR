"""The installed GPU API starts independently of the repository and CUDA hardware."""
import json
from pathlib import Path
import socket
import subprocess
import sys
import time

import httpx
from manual2ar.paths import ROOT


def test_explicit_inference_config_and_work_dir_start_without_repository_cwd(tmp_path):
    config=json.loads((ROOT/'configs/inference.example.json').read_text())
    with socket.socket() as reserved:
        reserved.bind(('127.0.0.1',0));port=reserved.getsockname()[1]
    config.update(host='127.0.0.1',port=port,api_token='test-only-private-inference-token')
    path=tmp_path/'inference.local.json';path.write_text(json.dumps(config))
    work=tmp_path/'worker';work.mkdir()
    with (tmp_path/'server.log').open('w') as log:
        process=subprocess.Popen([sys.executable,'-B','-m','manual2ar_inference.app',
            '--config',str(path),'--work-dir',str(work)],cwd=tmp_path,stdout=log,stderr=subprocess.STDOUT)
        try:
            deadline=time.monotonic()+15
            with httpx.Client(base_url=f'http://127.0.0.1:{port}',trust_env=False,timeout=1) as client:
                while time.monotonic()<deadline:
                    assert process.poll() is None,(tmp_path/'server.log').read_text()
                    try:response=client.get('/health',headers={'Authorization':'Bearer '+config['api_token']});break
                    except httpx.TransportError:time.sleep(.1)
                else:raise AssertionError('Inference service did not start')
                assert response.status_code==200,response.text
                assert response.json()['protocol']=='manual2ar-learning-cutie-v2'
                assert client.get('/health').status_code==401
            assert (work/config['log_root']).is_dir()
        finally:
            process.terminate()
            try:process.wait(timeout=10)
            except subprocess.TimeoutExpired:process.kill();process.wait()
