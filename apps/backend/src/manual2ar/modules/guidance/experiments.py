"""Frozen experiment selections and actual-call accounting. Correctness gates are never ablated."""
import base64
import hashlib
import json
from pathlib import Path
import threading
import time
from typing import Literal
from pydantic import BaseModel,ConfigDict,Field,model_validator


FEATURES={
 'visual_observation_contract':('严格视觉观察契约','对象/特征/观察查询与验收规则分离；未定义朝向标准明确拒绝'),
 'stateful_planning':('现场驱动执行规划','完整任务→参考辅助状态对齐→剩余操作/核验；用户声明不直接放行'),
 'hierarchical_evidence':('层级证据检索','HiKEY：任务章节、父级警告与关联图片'),
 'image_enrichment':('官方图片语义增强','MIDR：缓存派生图像描述，保留原始出处'),
 'visual_reranking':('现场图文流程匹配','CoP：候选流程与现场原图直接匹配'),
 'scene_alignment':('部件与当前状态对齐','CoP / CheckManual：现场部件ID、关系、状态与未知项'),
 'staged_compilation':('分阶段任务编译','动作证据→状态图→观察点'),
 'semantic_review':('条件覆盖审核与修复','PROC2PDDL：要求、依赖、可观察性和出处检查，一次修复'),
 'region_alignment':('编号区域部件对应','CheckManual：候选区域编号后再映射部件'),
 'mask_refinement':('掩膜检查与修正','VASA：检查掩膜与部件语义，最多一次重新分割'),
 'temporal_verification':('多帧一致核验','IndustReal：三张不同现场帧的一致证据；不检查扭矩'),
 'contextual_display':('结构化AR图例与指令','Guided Reality / JARVIS：模型图例、颜色及目标旁祈使句'),
}


class Features(BaseModel):
 model_config=ConfigDict(extra='forbid')
 visual_observation_contract:bool=False
 stateful_planning:bool=False
 text_only:bool=False
 hierarchical_evidence:bool=False
 image_enrichment:bool=False
 visual_reranking:bool=False
 scene_alignment:bool=False
 staged_compilation:bool=False
 semantic_review:bool=False
 region_alignment:bool=False
 mask_refinement:bool=False
 temporal_verification:bool=False
 contextual_display:bool=False

 @model_validator(mode='after')
 def compatible(self):
  if self.text_only and (self.visual_reranking or self.scene_alignment or self.stateful_planning):
   raise ValueError('Text-only planning cannot also inspect the scene for reranking/alignment')
  return self

 def label(self):
  return '+'.join(k for k,v in self.model_dump().items() if v) or 'baseline-v1.2'


class HumanReview(BaseModel):
 model_config=ConfigDict(extra='forbid')
 task_planning:Literal['unrated','pass','fail']='unrated'
 component_binding:Literal['unrated','pass','fail']='unrated'
 guidance:Literal['unrated','pass','fail']='unrated'
 verification:Literal['unrated','pass','fail']='unrated'
 notes:str=Field(default='',max_length=3000)
 review_seconds:float=Field(default=0,ge=0,le=86400)


def catalog():
 return dict(contract='manual2ar-ablation-v1',default=Features().model_dump(),
  features=[dict(id=k,label=v[0],description=v[1]) for k,v in FEATURES.items()],
  controls=[dict(id='text_only',label='移除规划现场图',description='规划不看现场图；官方资料图和AR现场核验保持不变')],
  presets={'baseline':Features().model_dump(),'full':Features(**dict.fromkeys(FEATURES,True)).model_dump()},
  invariant_gates=['photo/frame/hash identity','source provenance','scene-only verification','explicit geometry authorization','uncertain never advances'])


class RecordedClient:
 def __init__(self,client,folder,stage='pipeline'):
  self.client=client;self.folder=Path(folder);self.stage=stage;self.lock=threading.Lock()
 def chat_structured(self,**kwargs):
  start=time.perf_counter();identity=hashlib.sha256((str(time.time_ns())+self.stage).encode()).hexdigest()[:16]
  path=self.folder/'calls'/identity;path.mkdir(parents=True)
  (path/'prompt.txt').write_text(kwargs['prompt'])
  (path/'schema.json').write_text(json.dumps(kwargs['schema'],ensure_ascii=False,indent=2))
  row=dict(id=identity,stage=self.stage,schema=kwargs['schema'].get('title'),
   images=[hashlib.sha256(base64.b64decode(b)).hexdigest() for b in kwargs.get('images_base64',[])],
   max_tokens=kwargs.get('max_tokens'),usage_tokens=None,fee=None)
  try:
   result=self.client.chat_structured(**kwargs)
   (path/'response.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));row['status']='success';return result
  except Exception as error:row.update(status='failed',error_type=type(error).__name__,error_code=getattr(error,'code','provider_failure'));raise
  finally:
   row['elapsed_ms']=round((time.perf_counter()-start)*1000)
   with self.lock:
    with (self.folder/'calls.jsonl').open('a') as stream:stream.write(json.dumps(row,ensure_ascii=False)+'\n')


def call_summary(folder):
 p=Path(folder)/'calls.jsonl';rows=[]
 if p.exists():
  for line in p.read_text().splitlines():
   try:rows.append(json.loads(line))
   except json.JSONDecodeError:continue
 started={p.name for p in (Path(folder)/'calls').glob('*') if p.is_dir()};finished={r['id'] for r in rows}
 return dict(logical_calls=len(started|finished),incomplete_calls=len(started-finished),upstream_http_attempts=None,failed_calls=sum(x['status']!='success' for x in rows),
  call_elapsed_ms=sum(x['elapsed_ms'] for x in rows),usage_tokens=None,fee=None)
