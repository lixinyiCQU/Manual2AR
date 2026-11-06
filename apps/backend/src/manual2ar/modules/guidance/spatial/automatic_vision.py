"""Two-stage RGB grounding: base ROI then functional points. No inferred depth."""
import base64
import cv2
import numpy as np
from manual2ar_contracts.automatic_guidance import FunctionalObservation
from .localization import LocatedTarget
from .vision_context import write

FEATURE_PROMPT = '''第一张是当前照片中灰色料盘支架底座的放大裁剪图，第二张仅为官方外观参考。
只定位第一张中的真实可见功能点，不判断安装完成、不估计三维位置或尺寸。
screw_upper/screw_lower 是底座上沿真实立柱方向较高/较低的两颗螺丝的头部中心；不要把孔、反光或相邻机架螺丝算入。
guide_top/guide_bottom 是灰色底座同一条可见竖直外轮廓边的上/下角点，用于沿底座边缘示意上下方向；不要求存在凸起滑轨，不寻找隐藏插槽或卡扣。只标真实可见的外边缘角点；不能辨认时返回 unseen，不能用螺丝中心代替。
每个点都返回 status、point_0_1000、confidence、evidence。坐标为第一张裁剪图左上角原点的 0..1000；不可见/不确定时坐标为空。必须返回四种不同的点，不要猜遮挡位置。'''


def observe(client, config, raw, reference, folder):
    coarse = ('Locate only the visible grey/dark-grey rectangular two-screw spool-holder base on '
              'the Bambu Lab A1 mini Z column in image 1. Image 2 is an appearance reference. '
              'Exclude the whole column and white holder. Return action_id=holder.base, target_id=base; '
              'status found/unseen/uncertain; bbox_0_1000=[left,top,right,bottom] and an interior '
              'foreground_point_0_1000 in image 1, Chinese evidence and next_action. Do not invent occluded material.')
    def encoded(b): return base64.b64encode(b).decode()
    (folder/'input.jpg').write_bytes(raw)
    write(folder/'request.json', {'purpose':'automatic_u7_features', 'image_count_per_request':2})
    (folder/'base-prompt.txt').write_text(coarse, encoding='utf-8')
    reply = client.chat_structured(prompt=coarse, schema=LocatedTarget.model_json_schema(), images_base64=[encoded(raw),encoded(reference)], max_tokens=1200)
    write(folder/'base-reply.json',reply)
    base=LocatedTarget.model_validate(reply)
    minimum=config['verification']['minimum_confidence']
    if (base.action_id,base.target_id)!=('holder.base','base') or base.status!='found' or base.confidence<minimum:
        raise ValueError('未能可靠找到灰色底座；请拍清底座与两颗螺丝。')
    image=cv2.imdecode(np.frombuffer(raw,np.uint8),cv2.IMREAD_COLOR);h,w=image.shape[:2]
    x,y,r,b=np.array(base.bbox_0_1000)*[w,h,w,h]/1000
    pad=max(8,(r-x)*.15);x,y=max(0,int(x-pad)),max(0,int(y-pad));r,b=min(w,int(r+pad)),min(h,int(b+pad))
    if min(r-x,b-y)<16:raise ValueError('底座在画面中太小，请靠近后重新拍摄。')
    crop=image[y:b,x:r];crop=cv2.resize(crop,None,fx=max(1,640/max(crop.shape[:2])),fy=max(1,640/max(crop.shape[:2])))
    ok,jpeg=cv2.imencode('.jpg',crop)
    if not ok:raise ValueError('无法生成局部定位图。')
    (folder/'crop.jpg').write_bytes(jpeg.tobytes());(folder/'features-prompt.txt').write_text(FEATURE_PROMPT,encoding='utf-8')
    reply=client.chat_structured(prompt=FEATURE_PROMPT,schema=FunctionalObservation.model_json_schema(),images_base64=[encoded(jpeg.tobytes()),encoded(reference)],max_tokens=2400)
    write(folder/'features-reply.json',reply);answer=FunctionalObservation.model_validate(reply)
    pixels={}
    for point in answer.points:
        if point.status=='found' and point.confidence>=minimum:
            px,py=point.point_0_1000;pixels[point.id]=[x+px*(r-x)/1000,y+py*(b-y)/1000]
    if not {'screw_upper','screw_lower'}<=pixels.keys():raise ValueError('两颗螺丝未同时辨认清楚；请靠近、避开遮挡后补拍。')
    write(folder/'features.json',{'crop_rect':[x,y,r,b],'points_pixels':pixels,'observation':answer.model_dump()})
    annotated=image.copy()
    for name,point in pixels.items():
        p=tuple(np.rint(point).astype(int));cv2.drawMarker(annotated,p,(0,255,255),cv2.MARKER_CROSS,16,2);cv2.putText(annotated,name,(p[0]+5,p[1]-7),cv2.FONT_HERSHEY_SIMPLEX,.4,(0,255,255),1)
    cv2.imwrite(str(folder/'features-preview.jpg'),annotated)
    return pixels,answer.next_action
