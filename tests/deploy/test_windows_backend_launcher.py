"""Generated launchers carry data, not shell-interpolated WSL names or source paths."""
import json
from tools.build.spatial_delivery import export_backend_launcher
from manual2ar.paths import ROOT


def test_backend_launcher_keeps_paths_in_json_and_resolves_wsl_at_runtime(tmp_path):
    worktree='/home/test/Manual2AR Worktree'
    export_backend_launcher(tmp_path,worktree,'http://localhost:8010','Removed-Ubuntu')
    cmd=(tmp_path/'启动后端.cmd').read_bytes()
    assert b'Start-Backend.ps1' in cmd and b'wsl.exe -d' not in cmd
    assert b'Removed-Ubuntu' not in cmd and worktree.encode() not in cmd
    data=json.loads((tmp_path/'backend.launch.json').read_text())
    from manual2ar.modules.guidance.pipeline import Pipeline
    assert data==dict(worktree=worktree,backend_url='http://localhost:8010',distribution_hint='Removed-Ubuntu',backend_revision=Pipeline.source_revision())
    assert (tmp_path/'Start-Backend.ps1').read_bytes()==(ROOT/'deploy/windows/Start-Backend.ps1').read_bytes()
