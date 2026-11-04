"""Finite, model-free diagnostic suites shared by Notebook and CLI."""
import json
from pathlib import Path

from deploy.common.files import private_json
from .retention import start_recorder,utc


def session_lifecycle(root,settings,logs):
    private_json(root/'diagnostic-status.json',{'at':utc(),'suite':'session_lifecycle','state':'starting',
        'models_loaded':False,'public_tunnel':False,'duration_minutes':settings['duration_minutes']})
    destination=start_recorder(root,logs,minutes=settings['duration_minutes'])
    value={'at':utc(),'suite':'session_lifecycle','state':'observing','models_loaded':False,
           'public_tunnel':False,'destination':destination,'duration_minutes':settings['duration_minutes']}
    private_json(root/'diagnostic-status.json',value)
    return value


# Add a named suite here when implementing another diagnostic; never load paths from config.
SUITES={'session_lifecycle':session_lifecycle}


def launch(root,settings,logs):
    if settings.get('suite') not in SUITES:raise ValueError('Unknown diagnostic suite')
    for key,lo,hi in [('duration_minutes',1,120),('sample_seconds',5,300)]:
        if type(settings[key]) is not int or not lo<=settings[key]<=hi:raise ValueError('Invalid '+key)
    logs={**logs,'enabled':True,'interval_seconds':settings['sample_seconds']}
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    return SUITES[settings['suite']](root,settings,logs)
