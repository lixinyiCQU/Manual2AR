from pathlib import Path
"""Public settings for this module; private configuration is owned by application."""
HERE=Path(__file__).parent

def public(c):
    return {'module_version':(HERE/'VERSION').read_text().strip(),'backend_url':c['backend']['public_url'].rstrip('/'),'default_provider':c['segmentation']['default_provider'],
        'camera_name':c['camera']['name'],'camera_width':c['camera']['width'],'camera_height':c['camera']['height'],'camera_fps':c['camera']['fps'],
        'capture_max_side':min(1280,c['cpu_tracking']['capture_max_side']),'jpeg_quality':78,
        'request_timeout_seconds':max(180,c['vlm']['timeout_seconds']*3+c['cutie_tracking']['initialization_timeout_seconds']+30),
        'tracking_request_timeout_seconds':c['cpu_tracking']['request_timeout_seconds'] if c['segmentation']['default_provider']=='opencv' else c['cutie_tracking']['request_timeout_seconds']+5,'tracking_interval_seconds':1/c['inspection']['tracking_fps'],
        'rescan_seconds':c['inspection']['rescan_seconds'],'continuous_monitoring':c['inspection'].get('continuous_monitoring',False),'max_overlay_age_ms':c['performance']['max_overlay_age_ms'],'progress_poll_seconds':.25,'telemetry_seconds':c['performance'].get('telemetry_seconds',5),'target_render_fps':c['performance'].get('target_render_fps',60),'live_preview_inset':c['performance'].get('live_preview_inset',True)}
