"""Bounded, opt-in paper-inspired stages over the same evidence and U7 capabilities."""
import base64
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
from typing import Literal
import cv2
import numpy as np
from PIL import Image
from pydantic import BaseModel,ConfigDict,Field
from manual2ar.knowledge.compilation.models import Claim
from manual2ar.knowledge.compilation.source import model_source,fingerprint
from manual2ar.knowledge.wiki import write_json
from manual2ar_contracts.guidance_display import GuidanceDisplay,ImperativeInstruction
from .spatial.u7_vision import PartsObservation,PartObservation

class Strict(BaseModel):model_config=ConfigDict(extra='forbid')
class ImageDescription(Strict):
 image_id:str
 description:str=Field(min_length=1,max_length=700)
class Descriptions(Strict):items:list[ImageDescription]=Field(max_length=8)
class SceneAlignment(PartsObservation):
 evidence_image_id:Literal['current_scene']
 source_sha256:str
 current_capability:Literal['holder.base','holder.slide','unknown']
 state:Literal['not_started','in_progress','completed','wrong_operation','uncertain']
 relations:list[str]=Field(max_length=12)
 unknowns:list[str]=Field(max_length=12)
class SemanticReview(Strict):
 accepted:bool
 issues:list[str]=Field(max_length=20)
 required_fixes:list[Claim]=Field(max_length=30)
class RegionChoice(Strict):
 component_id:Literal['spool_holder_base','external_spool_holder']
 region_id:int=Field(ge=0,le=30)
 status:Literal['found','unseen','uncertain']
 confidence:float=Field(ge=0,le=1)
 evidence:str=Field(max_length=500)
 foreground_point_0_1000:list[int]=Field(max_length=2)
class RegionChoices(Strict):
 parts:list[RegionChoice]=Field(min_length=2,max_length=2)
 next_action:str=Field(max_length=500)
class MaskDecision(Strict):
 component_id:Literal['spool_holder_base','external_spool_holder']
 decision:Literal['keep','replace','reject']
 reason:str=Field(max_length=500)
 bbox_0_1000:list[int]=Field(max_length=4)
 foreground_point_0_1000:list[int]=Field(max_length=2)
class MaskReview(Strict):decisions:list[MaskDecision]=Field(max_length=2)


def enc(raw):return base64.b64encode(raw).decode()
def ask(client,folder,name,schema,prompt,images,*,max_repairs=0):
 if max_repairs not in (0,1):raise ValueError('At most one local schema repair')
 folder=Path(folder);folder.mkdir(parents=True,exist_ok=True);error='';previous=None
 for attempt in range(max_repairs+1):
  stem=name if attempt==0 else name+'-repair-'+str(attempt)
  text=prompt+('\n前次返回不是有效的业务对象。返回符合schema的实例，不要返回JSON Schema。\nPREVIOUS_REJECTED:'+json.dumps(previous,ensure_ascii=False)+'\nVALIDATION_ERROR:'+error if error else '')
  (folder/(stem+'.prompt.txt')).write_text(text);write_json(folder/(stem+'.schema.json'),schema.model_json_schema())
  write_json(folder/(stem+'.images.json'),[dict(index=i+1,sha256=hashlib.sha256(raw).hexdigest()) for i,raw in enumerate(images)])
  raw=client.chat_structured(prompt=text,schema=schema.model_json_schema(),images_base64=[enc(x) for x in images],max_tokens=3500)
  write_json(folder/(stem+'.raw.json'),raw);previous=raw
  try:return schema.model_validate(raw)
  except ValueError as exc:
   error=str(exc)[:2000]
   if attempt==max_repairs:raise


def option_images(index,options):
 result=[]
 for option in options:
  bundle=index.bundle_for(option['url'],option['heading'])
  image=next(iter(bundle['images']),None)
  if image and image['id'] not in {i['id'] for i in result}:result.append(image)
 return result[:8]


def enrich_options(client,index,options,folder,cache):
 images=option_images(index,options);cache=Path(cache);cache.mkdir(parents=True,exist_ok=True)
 model=getattr(getattr(client,'client',client),'model','configured-model')
 key=fingerprint(dict(version='derived-image-v1',model=model,archive=index.wiki.snapshot_sha256,images=[i['id'] for i in images]))
 path=cache/(key+'.json')
 if not images:return options
 cache_hit=path.exists()
 if cache_hit:value=Descriptions.model_validate(json.loads(path.read_text()))
 else:
  value=ask(client,folder,'image-enrichment',Descriptions,
   '按图像顺序描述每张官方图片里的部件形态、连接关系与操作示意，用于检索。不得把示范当作当前用户已完成。'
   'image_id仅取给定ID；不补写工具规格、紧固程度或隐藏状态。输出是派生描述，不是官方原文。\n'+
   json.dumps([dict(index=n+1,image_id=i['id'],heading=i['heading_path']) for n,i in enumerate(images)],ensure_ascii=False),[Path(i['path']).read_bytes() for i in images])
  if {x.image_id for x in value.items}!={i['id'] for i in images}:raise ValueError('Enrichment image identity mismatch')
  write_json(path,value.model_dump())
 write_json(Path(folder)/'image-enrichment.json',dict(source_role='model_derived_not_official',cache_key=key,cache_hit=cache_hit,**value.model_dump()))
 for option in options:
  ids={i['id'] for i in index.bundle_for(option['url'],option['heading'])['images']}
  option['derived_image_descriptions']=[i.model_dump() for i in value.items if i.image_id in ids]
 return options


def align_scene(client,raw,bundle,folder):
 refs=bundle['images'][:4];sha=hashlib.sha256(raw).hexdigest()
 answer=ask(client,folder,'scene-alignment',SceneAlignment,
  '第一张是当前现场，后续为官方参考图。只在第一张中找灰色料盘支架底座spool_holder_base和白色料盘支架external_spool_holder。'
  '打印机底部小黑孔不是灰色双螺丝底座。遮挡时unknown，不能猜不可见连接。'
  '按官方图文对应部件、可见连接关系和当前阶段；状态仅是待核验建议，不跳过前置条件，不推断扭矩。'
  'bbox和前景点仅用第一张0..1000坐标；found须有有效框和材料内点。evidence_image_id=current_scene。'
  '\nsource_sha256='+sha+'\n官方证据：'+json.dumps(model_source(bundle),ensure_ascii=False),[raw]+[Path(i['path']).read_bytes() for i in refs])
 if answer.source_sha256!=sha:raise ValueError('Scene alignment belongs to another photo')
 write_json(Path(folder)/'scene-alignment.json',answer.model_dump());return answer.model_dump()


def review_task(client,bundle,compile_folder,folder,name='semantic-review'):
 proc=json.loads((Path(compile_folder)/'task/procedure.json').read_text())
 answer=ask(client,folder,name,SemanticReview,
  '审核候选任务的语义，而不只检查JSON。逐项比较官方动作、数量规格、方向、警告、必要依赖和完成条件。'
  '特别检查：孔位对齐不等于螺丝已安装；运动方向不等于最终相对位置；不可从照片判断紧固/隐藏锁止。'
  '每个完成条件只能包含一个核验渠道：可见外观用vision，实际紧固等用独立manual条件。补充人工条件时保留有依据的可见条件。'
  '仅在文字中说需人工确认、却仍挂在vision条件下不算实现人工门控；不要推断资料未支持的卡扣或锁止要求。'
  '只有官方明确支持的事实才能补回。图示解释用inferred及对应image_ids，不把观察策略标成官方要求。'
  'required_fixes中每项是带出处的具体修正，使用SOURCE已有的citation_ids和image_ids。'
  'accepted=true时issues及required_fixes必须为空；无法证实就拒绝，不使用人工U7答案。'
  '\nSOURCE:'+json.dumps(model_source(bundle),ensure_ascii=False)+'\nCANDIDATE:'+json.dumps(proc,ensure_ascii=False),
  [Path(i['path']).read_bytes() for i in bundle['images'][:8]])
 from manual2ar.knowledge.compilation.compiler import check_claims
 check_claims(answer.required_fixes,bundle)
 if answer.accepted and (answer.issues or answer.required_fixes):raise ValueError('Contradictory semantic review')
 write_json(Path(folder)/(name+'.json'),answer.model_dump());return answer


def build_display(client,state,capability,template,library,folder):
 instruction=ask(client,folder,'display-'+state.state_id,ImperativeInstruction,
  '把候选指导简写为祈使句的五个字段：状语adverbial、主体actor、动作action、宾语object、验收acceptance。'
  '只转述给定候选要求，不加新条件、工具规格或状态结论；actor_mode为tool或moving_object。'
  'position_m=null，sentence为空交给渲染器组句。不要放当前步骤名、核验结果或操作历史。'
  '可复用图例：'+json.dumps(template['legend'],ensure_ascii=False)+'\n候选：'+state.model_dump_json(),[])
 data=deepcopy(template);data.update(action_id=capability,source='agent',instruction=instruction.model_dump())
 profile=GuidanceDisplay.model_validate(data)
 if any(i.kind=='model' and i.asset_id not in library.assets for i in profile.legend):raise ValueError('Unknown display asset')
 write_json(Path(folder)/('display-'+state.state_id+'.json'),profile.model_dump());return profile


def numbered_alignment(client,raw,base,holder,answer,folder):
 image=cv2.imdecode(np.frombuffer(raw,np.uint8),cv2.IMREAD_COLOR);h,w=image.shape[:2];boxes=[]
 for p in answer.parts:
  if p.bbox_0_1000:boxes.append(p.bbox_0_1000)
 contours,_=cv2.findContours(cv2.Canny(cv2.cvtColor(image,cv2.COLOR_BGR2GRAY),50,140),cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
 for c in sorted(contours,key=cv2.contourArea,reverse=True):
  x,y,bw,bh=cv2.boundingRect(c)
  if .0004<bw*bh/(w*h)<.45 and min(bw,bh)>=8:
   box=[round(x/w*1000),round(y/h*1000),round((x+bw)/w*1000),round((y+bh)/h*1000)]
   if box not in boxes:boxes.append(box)
  if len(boxes)>=24:break
 marked=image.copy()
 for n,(x,y,r,b) in enumerate(boxes,1):
  p=(int(x*w/1000),int(y*h/1000));q=(int(r*w/1000),int(b*h/1000));cv2.rectangle(marked,p,q,(0,210,255),2);cv2.putText(marked,str(n),(p[0],max(16,p[1])),cv2.FONT_HERSHEY_SIMPLEX,.6,(0,0,255),2)
 ok,jpeg=cv2.imencode('.jpg',marked)
 if not ok:raise ValueError('Cannot render numbered regions')
 (Path(folder)/'numbered-regions.jpg').write_bytes(jpeg.tobytes());write_json(Path(folder)/'numbered-regions.json',dict(provider='vlm_boxes+opencv_contours',boxes=boxes))
 selected=ask(client,folder,'region-alignment',RegionChoices,
  '第一张是当前现场，第二张是相同现场的编号候选框，第三张灰色底座参考、第四张白色支架参考。'
  '为两个固定部件选择现场框ID并给出第一张图0..1000材料内前景点foreground_point_0_1000；region_id=0表示没有可靠候选，点为空。不要选择小黑孔、整条立柱或桌面。'
  '看不到就返回unseen/uncertain；这只是身份对应，不判断安装完成。\n'+json.dumps(dict(regions={str(i+1):b for i,b in enumerate(boxes)})),
  [raw,jpeg.tobytes(),base,holder])
 if {p.component_id for p in selected.parts}!={'spool_holder_base','external_spool_holder'}:raise ValueError('Region mapping lacks parts')
 parts=[]
 for p in selected.parts:
  found=p.status=='found' and 1<=p.region_id<=len(boxes)
  box=boxes[p.region_id-1] if found else []
  if p.status=='found' and not found:raise ValueError('Unknown numbered region')
  parts.append(PartObservation(component_id=p.component_id,status=p.status,confidence=p.confidence,evidence=p.evidence,bbox_0_1000=box,
   foreground_point_0_1000=p.foreground_point_0_1000 if found else [],axis_start_0_1000=[],axis_end_0_1000=[]))
 return PartsObservation(parts=parts,next_action=selected.next_action)


def review_masks(client,raw,observations,masks,folder):
 active={name for name,mask in masks.items() if mask.any()}
 if not active:
  write_json(Path(folder)/'mask-review.json',dict(status='no_working_mask',decisions=[]));return observations
 image=cv2.imdecode(np.frombuffer(raw,np.uint8),cv2.IMREAD_COLOR);marked=image.copy()
 for n,(name,mask) in enumerate(masks.items()):
  color=np.array([(0,220,255),(255,190,30)][n%2]);marked[mask]=(marked[mask]*.45+color*.55).astype(np.uint8)
 ok,jpeg=cv2.imencode('.jpg',marked)
 if not ok:raise ValueError('Cannot inspect masks')
 (Path(folder)/'working-mask.jpg').write_bytes(jpeg.tobytes())
 decision=ask(client,folder,'mask-review',MaskReview,
  '第一张是原始现场，第二张是同一现场当前工作掩膜。检查掩膜是否覆盖指定部件而非小孔/机架/背景。'
  'keep保留、reject不可见/错误、replace给第一张图的替代框与材料内点；坐标0..1000。不得判断安装完成。'
  'replace只允许真实可见位置，不猜遮挡。不需要替换时框和点为空数组。只返回下列非空掩膜的决定：'+json.dumps(sorted(active))+'\n'+json.dumps([p.model_dump() for p in observations],ensure_ascii=False),[raw,jpeg.tobytes()])
 parts={p.component_id:p.model_copy(deep=True) for p in observations};seen=set()
 for item in decision.decisions:
  if item.component_id not in parts or item.component_id in seen:raise ValueError('Unknown/duplicate mask decision')
  seen.add(item.component_id);p=parts[item.component_id]
  if item.decision=='reject':p.status='uncertain';p.bbox_0_1000=[];p.foreground_point_0_1000=[];p.axis_start_0_1000=[];p.axis_end_0_1000=[]
  if item.decision=='replace':
   p.status='found';p.bbox_0_1000=item.bbox_0_1000;p.foreground_point_0_1000=item.foreground_point_0_1000;p.axis_start_0_1000=[];p.axis_end_0_1000=[]
  parts[item.component_id]=PartObservation.model_validate(p.model_dump())
 if seen!={name for name,mask in masks.items() if mask.any()}:raise ValueError('Review must cover every nonempty working mask')
 return list(parts.values())
