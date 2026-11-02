"""Per-client proxy policy; never alter process environment or TLS verification."""
import socket
from urllib.parse import urlsplit
import urllib.request

MODES = {'auto', 'system', 'direct'}


def local_proxy(url):
    parts = urlsplit(url)
    if urllib.request.proxy_bypass(parts.hostname):
        return None
    proxy = urllib.request.getproxies().get(parts.scheme)
    if not proxy:
        return None
    endpoint = urlsplit(proxy)
    if endpoint.hostname not in ('localhost', '127.0.0.1', '::1'):
        return None
    return endpoint.hostname, endpoint.port or (443 if endpoint.scheme == 'https' else 80)


def trust_environment(url, mode='auto'):
    if mode not in MODES:
        raise ValueError('proxy_mode must be auto, system or direct')
    if mode != 'auto':
        return mode == 'system'
    proxy = local_proxy(url)
    if proxy:
        try:
            with socket.create_connection(proxy, timeout=.3):
                pass
        except OSError:
            return False
    return True
