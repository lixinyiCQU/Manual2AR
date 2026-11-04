"""Same-photo context and safe diagnostics for explicit learner photo requests."""
import base64
import hashlib
import json
import cv2
import numpy as np
from pydantic import ValidationError


def write(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def prepare(raw,anchors,folder):
    images=[base64.b64encode(raw).decode()]
    meta={'source_sha256':hashlib.sha256(raw).hexdigest(),'anchors_0_1000':anchors,
        'hint_source':'user_authored_points_not_visual_confirmation','image_count':1}
    if anchors:
        image=cv2.imdecode(np.frombuffer(raw,np.uint8),cv2.IMREAD_COLOR);h,w=image.shape[:2]
        points=np.asarray([a['point_0_1000'] for a in anchors])*[w/1000,h/1000]
        margin=max(60,int(max(w,h)*.18));lo=np.maximum(0,np.floor(points.min(axis=0)-margin)).astype(int)
        hi=np.minimum([w,h],np.ceil(points.max(axis=0)+margin)).astype(int)
        x,y=lo;r,b=hi
        crop=image[y:b,x:r].copy()
        for i,(px,py) in enumerate(points):
            cv2.drawMarker(crop,(round(px-x),round(py-y)),(255,220,0),cv2.MARKER_CROSS,16,2)
            cv2.putText(crop,str(i+1),(round(px-x)+10,round(py-y)-8),cv2.FONT_HERSHEY_SIMPLEX,.6,(255,220,0),2)
        encoded=cv2.imencode('.jpg',crop,[cv2.IMWRITE_JPEG_QUALITY,92])[1].tobytes()
        (folder/'roi.jpg').write_bytes(encoded);images.append(base64.b64encode(encoded).decode())
        meta.update(image_count=2,crop_xyxy_0_1000=[round(x/w*1000),round(y/h*1000),round(r/w*1000),round(b/h*1000)],roi_sha256=hashlib.sha256(encoded).hexdigest())
    write(folder/'vision_context.json',meta)
    prompt=('\n当前图像约定：第一张是本次原始照片。若有第二张，它只是同一照片的局部放大，'
        '十字是用户设定的位置提示，不是实物，也不是识别正确或安装完成的证据。'
        '必须辨认提示附近的真实目标；提示与实物不符则返回不确定。'
        '所有返回框和点一律使用第一张原图的0..1000坐标，不能使用局部图坐标。'
        '\n当前照片位置上下文：'+json.dumps(meta,ensure_ascii=False))
    return images,prompt,meta


def failure(folder,error):
    # Never persist request headers, keys, image data URLs or arbitrary error text.
    value={'error_type':type(error).__name__,'code':str(getattr(error,'code','invalid_response'))}
    response=getattr(error,'response',None)
    if response is not None and isinstance(getattr(response,'status_code',None),int):value['http_status']=response.status_code
    if isinstance(error,ValidationError):
        value['validation']=[{'path':list(e['loc']),'type':e['type']} for e in error.errors(include_input=False,include_url=False)]
    write(folder/'error.json',value)
    return value
