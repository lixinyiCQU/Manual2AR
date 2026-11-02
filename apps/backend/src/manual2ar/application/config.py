"""One file for operator configuration; module defaults are implementation details."""
from copy import deepcopy
import json
import math
from pathlib import Path
from urllib.parse import urlsplit
from . import ROOT

MODULES = ('learning', 'guidance', 'inspection')
TUNABLE = {'cpu_tracking','cutie_tracking','performance','inspection','verification','sessions','logging',
           'minimum_confidence','maximum_mask_iou','segmentation'}


def merge_settings(defaults, overrides):
    for key,value in overrides.items():
        if key not in defaults:
            raise ValueError('Unknown module setting: '+key)
        original=defaults[key]
        if isinstance(original,dict):
            if not isinstance(value,dict):raise ValueError('Expected setting object: '+key)
            merge_settings(original,value)
        elif isinstance(original,bool):
            if not isinstance(value,bool):raise ValueError('Expected boolean setting: '+key)
            defaults[key]=value
        elif isinstance(original,(int,float)):
            if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<0:
                raise ValueError('Invalid numeric setting: '+key)
            if isinstance(original,int) and not isinstance(value,int):
                raise ValueError('Expected integer setting: '+key)
            defaults[key]=value
        elif isinstance(value,type(original)):defaults[key]=value
        else:raise ValueError('Invalid setting type: '+key)


def load(path=None):
    path = Path(path or ROOT / 'configs/app.local.json')
    if not path.is_file():
        raise ValueError('请复制 configs/app.example.json 为 configs/app.local.json，并在文件中填写配置。')
    value = json.loads(path.read_text(encoding='utf-8'))
    base=path.absolute().parent.parent
    for key, item in value['paths'].items():
        value['paths'][key]=str((base/item).absolute())
    value['gpu']['connection_file']=str((base/value['gpu']['connection_file']).absolute())
    validate(value)
    return value


def validate(c):
    from manual2ar_perception.cpu_settings import validate as cpu_validate
    url = urlsplit(c['backend']['public_url'])
    if url.scheme not in ('http', 'https') or not url.netloc or url.query or url.fragment:
        raise ValueError('backend.public_url must be an HTTP(S) origin')
    if not 1 <= c['backend']['port'] <= 65535:
        raise ValueError('Invalid backend.port')
    if not all(isinstance(c['camera'][k], int) and c['camera'][k] > 0 for k in ('width', 'height', 'fps')):
        raise ValueError('Invalid camera settings')
    if not c['vlm']['base_url'].startswith('https://') or c['vlm']['timeout_seconds'] <= 0:
        raise ValueError('Invalid VLM URL or timeout')
    if c['vlm'].get('proxy_mode','system') not in ('auto','system','direct'):
        raise ValueError('vlm.proxy_mode must be auto, system or direct')
    if set(c['modules']) != set(MODULES):
        raise ValueError('Exactly learning, guidance, inspection must be configured')
    for name in MODULES:
        if not c['modules'][name]['model']:
            raise ValueError('Each module needs a model')
        if name != 'guidance' and c['modules'][name]['provider'] not in ('opencv', 'sam31_cutie'):
            raise ValueError('Invalid segmentation provider')
        settings=c['modules'][name].get('settings',{})
        if not isinstance(settings,dict) or not set(settings)<=TUNABLE:
            raise ValueError('Unknown module setting section')
        value=for_module(c,name)
        if name!='guidance':
            cpu_validate(value['cpu_tracking'])
            if not 1<=value['cutie_tracking']['target_fps']<=15 or not 1<=value['cutie_tracking']['request_timeout_seconds']<=60:
                raise ValueError('Invalid GPU tracking limits')
        if name=='inspection':
            limits=value['inspection']
            if not 1<=limits['tracking_fps']<=15 or not 1<=limits['max_runs']<=16:
                raise ValueError('Invalid inspection limits')
            for key in ['clear_plate_confidence_min','clear_scene_confidence_min','minimum_tracking_quality','mask_prompt_containment_min']:
                if not 0<=limits[key]<=1:raise ValueError('Invalid inspection threshold')
        if name=='guidance' and not 0<value['verification']['minimum_confidence']<=1:
            raise ValueError('Invalid guidance confidence threshold')
    if not 1280 <= c['display']['width'] <= 3840 or not 720 <= c['display']['height'] <= 2160:
        raise ValueError('Invalid display dimensions')
    cpu_validate(json.loads((Path(__file__).parent / 'defaults/learning.json').read_text())['cpu_tracking'])


def resolve(path):
    return (ROOT / path).resolve()


def for_module(c, name):
    if name not in MODULES:
        raise ValueError('Unknown module')
    value = json.loads((Path(__file__).parent / f'defaults/{name}.json').read_text())
    merge_settings(value, c['modules'][name].get('settings',{}))
    value['backend'] = deepcopy(c['backend'])
    value['camera'] = deepcopy(c['camera'])
    value['display'] = deepcopy(c['display'])
    value['vlm'] = {**value['vlm'], **c['vlm'], 'model': c['modules'][name]['model']}
    value['runtime_dir'] = str(resolve(c['paths']['runtime']))
    value['resources_dir'] = str(resolve(c['paths'].get('resources','resources')))
    if name != 'guidance':
        value['segmentation']['default_provider'] = c['modules'][name]['provider']
        value['cutie_tracking']['connection_file'] = str(resolve(c['gpu']['connection_file']))
        value['static_images']['folder'] = str(resolve(c['paths']['static_images']))
    if name == 'learning':
        wiki = value['knowledge']['offline_wiki']
        wiki.update(archive=str(resolve(c['paths']['wiki_archive'])),
                    cache_dir=str(resolve(c['paths'].get('cache',c['paths']['runtime'])) / 'wiki'),
                    font_file=str(resolve(c['paths'].get('resources','resources'))/'shared/fonts/NotoSansCJKsc-Regular.otf'),
                    renderer_python=str((ROOT / c['paths']['renderer_python']).absolute()))
    return value


def public(c):
    """Whitelist: no model credentials, connection token or workstation paths."""
    return {'schema_version': 'manual2ar-app-v1', 'backend_url': c['backend']['public_url'].rstrip('/'),
            'ui_width': c['display']['width'], 'ui_height': c['display']['height'],
            'camera_name': c['camera']['name'], 'camera_width': c['camera']['width'],
            'camera_height': c['camera']['height'], 'camera_fps': c['camera']['fps']}
