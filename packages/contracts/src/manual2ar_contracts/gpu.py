"""Bounded, frame-identified contract; imports no local teaching application."""
import base64
import hashlib
import io
import json

import numpy as np
from PIL import Image
from pydantic import BaseModel, Field, model_validator

PROTOCOL = 'manual2ar-learning-cutie-v2'


def sha(data): return hashlib.sha256(data).hexdigest()
def targets_sha(targets):
    return sha(json.dumps(targets, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode())


class Target(BaseModel):
    component_id: str = Field(pattern=r'^[a-z][a-z0-9_]{0,63}$')
    bbox_0_1000: list[int] = Field(min_length=4, max_length=4)
    target_point_0_1000: list[int] = Field(min_length=2, max_length=2)

    @model_validator(mode='after')
    def geometry(self):
        a,b,c,d = self.bbox_0_1000; x,y = self.target_point_0_1000
        if not 0 <= a < c <= 1000 or not 0 <= b < d <= 1000 or not a <= x <= c or not b <= y <= d:
            raise ValueError('Invalid normalized box/point')
        return self


class Frame(BaseModel):
    image_base64: str = Field(min_length=32, max_length=2800000)
    source_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    frame_id: int = Field(ge=0, le=1000000)


class Start(Frame):
    targets: list[Target] = Field(min_length=1, max_length=8)

    @model_validator(mode='after')
    def unique(self):
        if self.frame_id != 0 or len({t.component_id for t in self.targets}) != len(self.targets):
            raise ValueError('Start at frame zero with unique target IDs')
        return self


def decode_image(request):
    return decode_jpeg(base64.b64decode(request.image_base64, validate=True),request.source_sha256)


def decode_jpeg(body,fingerprint):
    if len(body) > 2000000 or sha(body) != fingerprint:
        raise ValueError('Input frame fingerprint/size mismatch')
    with Image.open(io.BytesIO(body)) as image:
        if image.format != 'JPEG' or min(image.size) < 16 or max(image.size) > 1280:
            raise ValueError('Use JPEG with sides 16..1280')
        return np.array(image.convert('RGB'))


def encode_mask(mask):
    buffer = io.BytesIO()
    Image.fromarray(np.asarray(mask, dtype=np.uint8)*255).save(buffer, format='PNG', compress_level=1)
    return base64.b64encode(buffer.getvalue()).decode()


def decode_mask(encoded, width, height):
    if len(encoded) > 2400000: raise ValueError('Mask payload exceeds limit')
    body = base64.b64decode(encoded, validate=True)
    with Image.open(io.BytesIO(body)) as image:
        if image.format != 'PNG' or image.size != (width, height) or image.mode != 'L':
            raise ValueError('Unexpected binary mask dimensions/format')
        value = np.array(image)
    if not np.isin(value, [0,255]).all(): raise ValueError('Mask must be binary')
    return value > 127


def encode_labels(masks):
    identities=list(masks)
    if not 1<=len(identities)<=8:raise ValueError('Invalid label count')
    shape=np.asarray(masks[identities[0]]).shape
    labels=np.zeros(shape,np.uint8)
    for i,key in enumerate(identities,1):
        mask=np.asarray(masks[key],bool)
        if mask.shape!=shape or np.any((labels>0)&mask):raise ValueError('Label masks overlap or differ in shape')
        labels[mask]=i
    buffer=io.BytesIO();Image.fromarray(labels).save(buffer,format='PNG',compress_level=1)
    return dict(png_base64=base64.b64encode(buffer.getvalue()).decode(),
        labels=[dict(component_id=key,label_id=i) for i,key in enumerate(identities,1)])

def decode_labels(value,width,height):
    ids=value['labels'];keys=[x['component_id'] for x in ids];numbers=[x['label_id'] for x in ids]
    if not 1<=len(ids)<=8 or len(set(keys))!=len(keys) or numbers!=list(range(1,len(ids)+1)):raise ValueError('Invalid label mapping')
    encoded=value['png_base64']
    if len(encoded)>2400000:raise ValueError('Label payload exceeds limit')
    with Image.open(io.BytesIO(base64.b64decode(encoded,validate=True))) as image:
        if image.format!='PNG' or image.mode!='L' or image.size!=(width,height):raise ValueError('Invalid label image')
        labels=np.array(image)
    if not np.isin(labels,[0]+numbers).all():raise ValueError('Undeclared label ID')
    return {key:labels==i for key,i in zip(keys,numbers)}
