"""Exercise either visual module through the same API used by Unity."""
import argparse
import base64
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import cv2
import httpx
import numpy as np
from manual2ar.application.config import load,resolve
from manual2ar_contracts.gpu import decode_labels


def main():
    parser=argparse.ArgumentParser(description='对配置的静态图片目录运行统一后端，不在命令行填写凭据。')
    parser.add_argument('--module',choices=['learning','inspection'],required=True)
    args=parser.parse_args();c=load();module=args.module
    output=resolve(c['paths']['runtime'])/'static'/module/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    output.mkdir(parents=True,exist_ok=True);summary=[]
    with httpx.Client(base_url=c['backend']['public_url'],timeout=900) as client:
        response=client.get(f'/api/{module}/images');response.raise_for_status();images=response.json()['images']
        for index,item in enumerate(images,1):
            folder=output/f'{index:03d}';folder.mkdir();picture=client.get(item.get('preview_url') or item['url']);picture.raise_for_status();body=picture.content
            (folder/'input.jpg').write_bytes(body)
            fingerprint=picture.headers.get('X-Source-SHA256') or hashlib.sha256(body).hexdigest()
            start=client.post(f'/api/{module}/runs',json={'source':'static','provider':c['modules'][module]['provider']});start.raise_for_status();run=start.json()['run_id'];url=f'/api/{module}/runs/{run}'
            try:
                payload={'client_frame_id':1}
                if module=='learning':payload.update(source_image_id=item['id'],expected_source_sha256=fingerprint)
                else:payload.update(source_sha256=fingerprint,image_base64=base64.b64encode(body).decode())
                result=client.post(url+('/locate' if module=='learning' else '/inspect'),json=payload);result.raise_for_status();data=result.json()
                if data['source_sha256']!=fingerprint:raise ValueError('响应对应的图像发生变化')
                (folder/'result.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
                canvas=cv2.imdecode(np.frombuffer(body,np.uint8),cv2.IMREAD_COLOR)
                label=data.get('label_map')
                if label:
                    masks=decode_labels(label,label['width'],label['height'])
                    h,w=next(iter(masks.values())).shape;canvas=cv2.resize(canvas,(w,h))
                    colors=[(210,190,20),(55,80,255),(90,200,100),(220,110,160)]
                    for i,(identity,mask) in enumerate(masks.items()):
                        color=np.array(colors[i%len(colors)],np.uint8);canvas[mask]=(.65*canvas[mask]+.35*color).astype(np.uint8)
                        cv2.drawContours(canvas,cv2.findContours(mask.astype(np.uint8),cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)[0],-1,tuple(int(v) for v in color),2)
                else:
                    # CPU learning results carry individual RGBA mask textures.
                    for row in data.get('results',[]):
                        tracked=row.get('tracked') or {};encoded=tracked.get('overlay_png_base64')
                        if not row.get('tracking_ready') or not encoded:continue
                        mask=cv2.imdecode(np.frombuffer(base64.b64decode(encoded),np.uint8),cv2.IMREAD_UNCHANGED)
                        if mask is not None and mask.ndim==3 and mask.shape[2]==4:
                            area=mask[:,:,3]>0
                            if area.shape==canvas.shape[:2]:canvas[area]=(.65*canvas[area]+.35*np.array([190,210,40])).astype(np.uint8)
                cv2.imwrite(str(folder/'overlay.jpg'),canvas)
                summary.append({'image':item['name'],'run_id':run,'check_id':data['check_id'],'source_sha256':fingerprint,'folder':folder.name})
            finally:client.delete(url)
    (output/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n');print(output)

if __name__=='__main__':main()
