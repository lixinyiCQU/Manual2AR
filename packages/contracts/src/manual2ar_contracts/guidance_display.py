"""Scene text is a legend or an imperative; never an observation/check verdict."""
from typing import Literal
from pydantic import BaseModel,ConfigDict,Field,model_validator
import math

class DisplayModel(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)

class LegendItem(DisplayModel):
    id:str=Field(min_length=1,max_length=60)
    label:str=Field(min_length=1,max_length=24)
    kind:Literal['model','highlight']
    asset_id:str=''
    component_id:str=''
    terms:list[str]=Field(default_factory=list,max_length=6)
    color:list[float]=Field(default_factory=lambda:[.1,.8,.9],min_length=3,max_length=3)
    @model_validator(mode='after')
    def icon(self):
        if self.kind=='model' and not self.asset_id:raise ValueError('Model legend requires an asset')
        if any(not term or len(term)>24 or any(c in term for c in '<>\r\n') for term in self.terms):raise ValueError('Color terms must be short plain text')
        if any(not 0<=v<=1 for v in self.color):raise ValueError('Invalid legend color')
        return self

class ImperativeInstruction(DisplayModel):
    adverbial:str=Field(min_length=1,max_length=24)
    actor_mode:Literal['tool','moving_object']
    actor:str=Field(min_length=1,max_length=20)
    action:str=Field(min_length=1,max_length=20)
    object:str=Field(min_length=1,max_length=20)
    acceptance:str=Field(min_length=1,max_length=24)
    anchor:Literal['operation_target']='operation_target'
    position_m:list[float]|None=Field(default=None,min_length=3,max_length=3)
    sentence:str=''
    @model_validator(mode='after')
    def imperative(self):
        fields=[self.adverbial,self.actor,self.action,self.object,self.acceptance]
        if any(any(ch in value for ch in '<>\n\r') for value in fields):raise ValueError('Instruction must be plain single-line text')
        sentence=f'{self.adverbial}，'+('用' if self.actor_mode=='tool' else '将')+f'{self.actor}{self.action}{self.object}，{self.acceptance}。'
        if self.sentence and self.sentence!=sentence:raise ValueError('Sentence must follow the imperative contract')
        self.sentence=sentence
        if self.position_m is not None and (not all(math.isfinite(v) for v in self.position_m) or sum(v*v for v in self.position_m)>1):raise ValueError('Instruction anchor outside calibrated work area')
        return self

class GuidanceDisplay(DisplayModel):
    schema_version:Literal['manual2ar-guidance-display-v1']='manual2ar-guidance-display-v1'
    action_id:str=Field(min_length=1,max_length=60)
    source:Literal['authored','agent']='authored'
    legend:list[LegendItem]=Field(min_length=1,max_length=6)
    instruction:ImperativeInstruction
    @model_validator(mode='after')
    def identities(self):
        if len({i.id for i in self.legend})!=len(self.legend):raise ValueError('Duplicate legend identity')
        colors={}
        for item in self.legend:
            for term in item.terms:
                if term in colors and colors[term]!=item.color:raise ValueError('Ambiguous term color')
                colors[term]=item.color
        if any(any(c in i.label for c in '<>\r\n') for i in self.legend):raise ValueError('Legend labels must be plain single-line text')
        return self
