"""Narrow U7 prerequisite: visible base installation must pass before holder insertion."""
import uuid
from fastapi import HTTPException

BASE='holder.base'
HOLDER='holder.slide'
MESSAGE='请先安装料盘支架底座，并拍照通过底座可见安装检查，再进入安装料盘支架。'


def enabled(task):
    card=getattr(task,'cards',{}).get('U7')
    return bool(card and len(card.substeps)>=2 and '料盘支架' in card.title)


def stage(selected):return 'holder' if selected in ('U7-S2',HOLDER) else 'base'


def state(owner,enforced=True):
    checks=getattr(owner,'u7_checks',{})
    approved=checks.get('base',{}).get('status')=='completed' and not checks.get('pending_base')
    return {'enforced':enforced,'base_approved':bool(approved),'holder_approved':checks.get('holder',{}).get('status')=='completed' and bool(approved),
            'message':'底座可见安装检查已通过，可以安装料盘支架。' if approved else MESSAGE,
            'base_result':checks.get('base'),'holder_result':checks.get('holder')}


def require(owner,selected,enforced=True):
    if enforced and stage(selected)=='holder' and not state(owner)['base_approved']:raise HTTPException(409,MESSAGE)


def start(owner,selected):
    if not hasattr(owner,'u7_checks'):owner.u7_checks={}
    key=stage(selected);token=uuid.uuid4().hex;owner.u7_checks['pending_'+key]=token
    owner.u7_checks.pop(key,None)
    if key=='base':
        owner.u7_checks.pop('holder',None);owner.u7_checks.pop('pending_holder',None)
        if hasattr(owner,'tutorial_substeps'):owner.tutorial_substeps['U7']='U7-S1'
    return token


def finish(owner,selected,token,result):
    key=stage(selected)
    if owner.u7_checks.get('pending_'+key)!=token:raise HTTPException(409,'此核验已被更新的拍照替代，请重新检查。')
    owner.u7_checks.pop('pending_'+key,None);owner.u7_checks[key]={**result,'status':'wrong_operation' if result.get('status')=='not_completed' else result.get('status','uncertain')}
    return state(owner)


def reset(owner,selected):
    start(owner,selected);owner.u7_checks.pop('pending_'+stage(selected),None)
