from pathlib import Path
"""Public settings for this module; private configuration is owned by application."""
HERE=Path(__file__).parent

def public(c):
    from manual2ar.application.public import camera_settings as original
    return {**original(c),'catalog_file':'GuidanceCatalog.json',
            'ui_width':c.get('display',{}).get('width',1920),'ui_height':c.get('display',{}).get('height',1080)}
