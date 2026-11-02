"""Small per-observation wire contract; no unrelated procedure-engine fields."""
from typing import Literal
from pydantic import BaseModel, Field, create_model
from manual2ar_contracts.perception import ComponentBox


class ObservationResult(BaseModel):
    status: Literal['completed', 'wrong_operation', 'uncertain']
    matched_step_id: str
    inspection_id: str
    evidence: str
    confidence: float = Field(ge=0, le=1)
    next_action: str
    component_boxes_0_1000: list[ComponentBox] = Field(default_factory=list)


def result_contract(state_id, inspection_id):
    return create_model('CurrentObservationResult', __base__=ObservationResult,
        matched_step_id=(Literal[state_id], ...), inspection_id=(Literal[inspection_id], ...))


def bound_prompt(text, task_id, state, node):
    """Keep source Prompt verbatim, append explicit request identity and example."""
    import json
    example = {'status': 'uncertain', 'matched_step_id': state.state_id,
        'inspection_id': node.inspection_id, 'evidence': '请描述本次图像中的实际可见证据。',
        'confidence': 0.0, 'next_action': '证据不足时说明具体补拍区域。', 'component_boxes_0_1000': []}
    return text + '\n\n本次接口输出约束（以此处的精简JSON Schema为准）：\n' + (
        f'任务ID={task_id}，仅为上下文，绝不能填入matched_step_id。\n'
        f'matched_step_id必须逐字等于"{state.state_id}"；inspection_id必须逐字等于"{node.inspection_id}"。\n'
        'evidence和next_action必须用中文。status仅可为completed、wrong_operation、uncertain。不要返回旧执行器的额外字段。\n'
        '以下仅示范字段及身份，不是检查结论；必须根据当前图像重新判断：\n' + json.dumps(example, ensure_ascii=False))
