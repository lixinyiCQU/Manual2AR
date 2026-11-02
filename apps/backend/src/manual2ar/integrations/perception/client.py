"""One authenticated persistent GPU session; no comparison-job API or fallback."""
import base64
from time import perf_counter
from urllib.parse import urlparse
import httpx
from manual2ar_contracts.gpu import PROTOCOL, decode_labels, sha, targets_sha
from manual2ar.infrastructure.network import trust_environment


class CutieClient:
    def __init__(self, connection, timeout=30, transport=None):
        parts=urlparse(connection['url'])
        if parts.scheme not in ('https','http') or not parts.netloc or parts.username or parts.password or parts.query or parts.fragment:
            raise ValueError('Invalid GPU URL')
        if connection.get('protocol') != PROTOCOL:
            raise ValueError('Use a module-one Cutie connection file, not a tracking-comparison/static service')
        if len(connection.get('api_token','')) < 24: raise ValueError('GPU service token missing')
        self.http=httpx.Client(base_url=connection['url'].rstrip('/'),timeout=timeout,transport=transport,
            trust_env=trust_environment(connection['url'],connection.get('proxy_mode','auto')) if transport is None else False,
            headers={'Authorization':'Bearer '+connection['api_token']},follow_redirects=False)
        self.session=None; self.geometry=None; self.identities=[]; self.dimensions=None

    def health(self):
        r=self.http.get('/health');r.raise_for_status(); value=r.json()
        if value.get('protocol') != PROTOCOL or not value.get('available'):
            raise ValueError('Module-one Cutie GPU service is unavailable or protocol differs')
        return value

    def probe(self):
        samples=[]
        for size in (0,65536):
            started=perf_counter();r=self.http.post('/v1/ping',content=b'0'*size,headers={'Content-Type':'application/octet-stream'});r.raise_for_status()
            if r.content!=b'0'*size:raise ValueError('GPU probe mismatch')
            samples.append(dict(bytes_each_direction=size,roundtrip_ms=(perf_counter()-started)*1000))
        return samples

    def _request(self, image, index, path, targets=None):
        payload=dict(source_sha256=sha(image),frame_id=index)
        if targets is not None:payload.update(targets=targets,image_base64=base64.b64encode(image).decode())
        started=perf_counter()
        if targets is None:
            r=self.http.post(path+'/jpeg',content=image,params=dict(frame_id=index,source_sha256=payload['source_sha256']),headers={'Content-Type':'image/jpeg'})
        else:r=self.http.post(path,json=payload)
        r.raise_for_status()
        if len(r.content)>20000000:raise ValueError('GPU response exceeds limit')
        value=r.json()
        if value.get('protocol') != PROTOCOL or value.get('source_sha256') != sha(image) or value.get('frame_id') != index:
            raise ValueError('GPU response frame identity mismatch')
        if value.get('targets_sha256') != self.geometry or (self.session and value.get('session_id') != self.session):
            raise ValueError('GPU response session/target identity mismatch')
        width,height=value['width'],value['height']
        if self.dimensions and self.dimensions != (width,height): raise ValueError('GPU response dimensions changed')
        decode_started=perf_counter()
        masks=decode_labels(value['label_map'],width,height)
        if set(masks)!=set(self.identities):raise ValueError('GPU returned unexpected object IDs')
        value['metrics'].update(client_mask_decode_ms=(perf_counter()-decode_started)*1000,upload_bytes=len(image),download_bytes=len(r.content))
        value['http_roundtrip_ms']=round((perf_counter()-started)*1000,3)
        return masks,value

    def start(self, image, targets):
        from PIL import Image
        import io
        with Image.open(io.BytesIO(image)) as source:self.dimensions=source.size
        self.geometry=targets_sha(targets);self.identities=[t['component_id'] for t in targets]
        masks,value=self._request(image,0,'/v1/sessions',targets)
        identity=value.get('session_id','')
        if len(identity)!=32 or any(c not in '0123456789abcdef' for c in identity):raise ValueError('Invalid remote session ID')
        self.session=identity
        return masks,value

    def step(self, image, frame_id):
        if not self.session: raise ValueError('Remote session is closed')
        return self._request(image,frame_id,'/v1/sessions/'+self.session+'/frames')

    def close(self):
        try:
            if self.session:
                response=self.http.delete('/v1/sessions/'+self.session,timeout=5)
                response.raise_for_status()
        finally:
            self.session=None;self.http.close()
