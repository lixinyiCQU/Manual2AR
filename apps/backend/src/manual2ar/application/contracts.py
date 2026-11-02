"""Public cross-module identity. Task outcomes remain module-owned."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from manual2ar_contracts.identity import FrameIdentity

class ModuleDefinition(BaseModel):
    id: Literal['learning', 'guidance', 'inspection']
    title: str
    description: str
    scene: str
    api_prefix: str
    available: bool = True
    status_message: str = ''

MODULES = [
    ModuleDefinition(id='learning', title='部件认知', description='认识 A1 mini 的主要部件，查看官方介绍与相机标注。', scene='PrinterLearning', api_prefix='/api/learning'),
    ModuleDefinition(id='guidance', title='操作指导', description='按官方步骤学习开箱、首次打印、进料和退料。', scene='PrinterGuidance', api_prefix='/api/guidance'),
    ModuleDefinition(id='inspection', title='打印状态检查', description='拍照检查打印板上的异物与残料，并跟踪处理过程。', scene='PrinterInspection', api_prefix='/api/inspection'),
]
