"""U7 semantics: find BOTH physical parts, independently assess visible final installation."""
import base64
import json
from typing import Literal
from pydantic import BaseModel,ConfigDict,Field,model_validator
from .localization import LocatedTarget
from .vision_context import write


class PartObservation(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    component_id:Literal['spool_holder_base','external_spool_holder']
    status:Literal['found','unseen','uncertain']
    confidence:float=Field(ge=0,le=1)
    evidence:str=Field(max_length=500)
    bbox_0_1000:list[int]=Field(max_length=4)
    foreground_point_0_1000:list[int]=Field(max_length=2)
    axis_start_0_1000:list[int]=Field(max_length=2)
    axis_end_0_1000:list[int]=Field(max_length=2)

    @model_validator(mode='after')
    def geometry(self):
        LocatedTarget(action_id='u7.parts',target_id=self.component_id,status=self.status,confidence=self.confidence,bbox_0_1000=self.bbox_0_1000,foreground_point_0_1000=self.foreground_point_0_1000)
        for point in [self.axis_start_0_1000,self.axis_end_0_1000]:
            if point and (len(point)!=2 or any(not 0<=p<=1000 for p in point)):raise ValueError('Invalid image-space axis')
        if bool(self.axis_start_0_1000)!=bool(self.axis_end_0_1000):raise ValueError('Axis endpoints must be supplied together')
        return self


class PartsObservation(BaseModel):
    model_config=ConfigDict(extra='forbid')
    parts:list[PartObservation]=Field(min_length=2,max_length=2)
    next_action:str=Field(max_length=500)
    @model_validator(mode='after')
    def identities(self):
        if {p.component_id for p in self.parts}!={'spool_holder_base','external_spool_holder'}:raise ValueError('Return exactly both U7 parts')
        return self


class InstallationObservation(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    status:Literal['completed','not_completed','uncertain']
    confidence:float=Field(ge=0,le=1)
    evidence:str=Field(max_length=700)
    next_action:str=Field(max_length=500)


def normalize_parts(reply):
    # Accept only the observed equivalent keyed shape; all semantics/geometry still pass the strict schema.
    ids=('spool_holder_base','external_spool_holder')
    if isinstance(reply,dict) and set(reply)=={*ids,'next_action'} and all(isinstance(reply[k],dict) for k in ids):
        parts=[]
        for identity in ids:
            value=dict(reply[identity])
            if 'component_id' in value and value['component_id']!=identity:return reply
            value['component_id']=identity;parts.append(value)
        reply={'parts':parts,'next_action':reply['next_action']}
    if isinstance(reply,dict) and isinstance(reply.get('parts'),list):
        reply={**reply,'parts':[dict(p) if isinstance(p,dict) else p for p in reply['parts']]}
        for part in reply['parts']:
            if isinstance(part,dict):
                for key in ('axis_start_0_1000','axis_end_0_1000'):
                    if key in part and part[key] is None:part[key]=[]
    return reply


PARTS_PROMPT='''请在第一张当前照片中分别找到 Bambu Lab A1 mini 的两个真实部件，不判断安装完成：
1. spool_holder_base：Z轴立柱侧面的灰色或深灰色小矩形底座，通常可见上下两颗黑色螺丝。它不是白色塑料件，也不是整条金属立柱。第二张官方局部图展示该底座。
2. external_spool_holder：可拆卸的白色料盘支架，带三角支撑、长圆柱料盘轴及端部圆盘。它可能放在打印机旁的桌面、拿在手上，也可能已安装；不要把立柱、工具头、线束、料卷或旁边蓝色装置当作它。第三张官方局部图展示该支架。
两部件可分开摆放，不要求接触。已装支架可能挡住底座，底座不可见时返回 unseen，不能编造它的位置。所有框、前景点及轴点都必须用第一张原图的左上角原点、0..1000坐标；第二三张仅用于外观参考。bbox=[left,top,right,bottom]，前景点必须位于真实可见材料上。
支架可见时，若能辨认，axis_start取三角支撑的安装接合端，axis_end取料盘轴自由端的圆盘；这是二维方向提示，不是三维姿态。无法辨认方向则两者都留空。底座不需要轴点。对每个部件返回 found/unseen/uncertain，不能因为用户标定点或另一部件存在就断言 found。用简短中文描述证据及补拍指导。输出根对象必须是 {"parts":[两部件对象],"next_action":"简短建议"}；每个对象包含 component_id；不可用轴点写空数组，不写 null。'''

INSTALL_PROMPT='''只判断第一张当前照片中 A1 mini 外挂料盘支架的最终可见安装状态，不找螺丝位置、不分割、不判断扭矩：
completed：白色料盘支架已从立柱上的安装位置伸出，安装端与打印机立柱的底座区域有清楚可见的连接，形态与第二张官方安装示例一致，且无明显脱离或大幅倾斜。底座会被装好的支架遮住，不要求看见底座螺丝、隐藏插槽、卡扣或细微缝隙。
not_completed：支架仍独立放在桌面、拿在手中未连接，或明显未接到打印机上。
uncertain：支架或安装连接区域不在画面中、被手/物体严重挡住，当前视角无法区分连接与仅靠在一起。
不能仅因画面中同时出现打印机和支架就判定完成，也不能因为螺丝被正常遮挡而拒绝完成。只关注最终外观连接。安装示例是外观参考，所有证据必须来自当前照片。输出简短中文 evidence 和 next_action；完成时明确写“料盘支架已安装到打印机上，可见连接符合本步要求”。结论仅限可见安装状态，不表示机械锁紧或安全放行。'''


def identify(client,config,raw,reference_base,reference_holder,folder,action_id="holder.slide"):
    images=[base64.b64encode(b).decode() for b in [raw,reference_base,reference_holder]]
    write(folder/'request.json',{'purpose':'u7_parts','image_count':3,'current_image_index':0,'reference_indices':[1,2]})
    prompt=PARTS_PROMPT+('\n当前是安装底座步骤：只定位灰色双螺丝底座；白色支架返回 unseen，下一步给出简短的底座安装指导。' if action_id=='holder.base' else '\n当前是滑入支架步骤：分别高亮灰色底座与白色料盘支架，指导用户对准导向槽从上往下滑入。')
    (folder/'input.jpg').write_bytes(raw);(folder/'prompt.txt').write_text(prompt)
    reply=client.chat_structured(prompt=prompt,schema=PartsObservation.model_json_schema(),images_base64=images,max_tokens=2000)
    write(folder/'model_reply.json',reply);answer=PartsObservation.model_validate(normalize_parts(reply))
    minimum=config['verification']['minimum_confidence']
    for p in answer.parts:
        if p.confidence<minimum:p.status='uncertain';p.bbox_0_1000=[];p.foreground_point_0_1000=[];p.axis_start_0_1000=[];p.axis_end_0_1000=[]
    write(folder/'result.json',answer.model_dump());return answer


def installation(client,config,raw,reference,folder):
    (folder/'input.jpg').write_bytes(raw);(folder/'prompt.txt').write_text(INSTALL_PROMPT)
    reply=client.chat_structured(prompt=INSTALL_PROMPT,schema=InstallationObservation.model_json_schema(),images_base64=[base64.b64encode(b).decode() for b in [raw,reference]],max_tokens=1200)
    write(folder/'model_reply.json',reply);answer=InstallationObservation.model_validate(reply)
    if answer.confidence<config['verification']['minimum_confidence'] or not answer.evidence.strip():answer.status='uncertain'
    write(folder/'result.json',answer.model_dump());return answer.model_dump()


BASE_PROMPT='''只判断第一张当前照片中 A1 mini 料盘支架底座是否已完成可见安装，第二张是底座外观参考。
目标是 Z 轴立柱背面的灰色/深灰色小矩形固定底座，不是整条立柱，也不是白色可拆卸料盘支架。
completed：灰色底座已贴靠在立柱正确安装区域，上下两颗固定螺丝均可见且处于安装孔位，未见明显缺件、脱离或倾斜。
not_completed：底座尚未接到立柱上、明显缺少螺丝或存在明显脱离/倾斜。
uncertain：底座或两个固定螺丝不可见、被手或已安装的白色支架遮挡、画质或视角不足。不能因为打印机或白色支架存在就推断底座检查通过。
只检查可见安装状态，不判断扭矩、螺丝是否真正拧紧、隐藏卡扣或内部结构。用户仍需按官方步骤人工确认机械紧固。
用简短中文返回 evidence 和 next_action。完成时明确说明“底座可见安装状态符合，可以继续安装料盘支架”；不确定时请用户补拍立柱背面的灰色底座及上下两颗螺丝。'''


def base_installation(client,config,raw,reference,folder):
    (folder/'input.jpg').write_bytes(raw);(folder/'prompt.txt').write_text(BASE_PROMPT)
    reply=client.chat_structured(prompt=BASE_PROMPT,schema=InstallationObservation.model_json_schema(),images_base64=[base64.b64encode(b).decode() for b in [raw,reference]],max_tokens=1200)
    write(folder/'model_reply.json',reply);answer=InstallationObservation.model_validate(reply)
    if answer.confidence<config['verification']['minimum_confidence'] or not answer.evidence.strip():answer.status='uncertain'
    write(folder/'result.json',answer.model_dump());return answer.model_dump()


def load_references(config):
    import hashlib
    from manual2ar.resources import ResourceStore
    root=ResourceStore.configured(config).path('task.unboxing.spatial').parent/'vision'
    manifest=json.loads((root/'references.json').read_text())['references'];result={}
    for key,value in manifest.items():
        raw=(root/value['file']).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=value['sha256']:raise ValueError('U7 reference checksum mismatch')
        result[key]=raw
    return result
