"""Shared whitelist for camera settings exported to Unity."""
def camera_settings(c):
    return {'backend_url': c['backend']['public_url'].rstrip('/'),
            'camera_name': c['camera']['name'], 'camera_width': c['camera']['width'],
            'camera_height': c['camera']['height'], 'camera_fps': c['camera']['fps'],
            'request_timeout_seconds': int(c['vlm']['timeout_seconds']) * 3 + 60}
