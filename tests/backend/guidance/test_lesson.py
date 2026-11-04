"""Reviewed reading content retains source binding and separates actions from notices."""
from copy import deepcopy
import hashlib
import pytest
from tests.backend.guidance.test_workflow import guide,registry,start
from tests.backend.guidance.test_tutorial import browse
from manual2ar.modules.guidance.lesson import source_fields,source_hash
from manual2ar.modules.guidance.registry import UNBOX


def texts(lesson,kind):
    return '\n'.join(b['text'] for s in lesson['sections'] if s['kind']==kind for b in s['blocks'])


def test_every_registered_page_has_reviewed_sections_and_intact_sources(guide):
    _,fake,service,_=guide;count=0
    for (_,variant),engine in service.engines.items():
        task=engine.task;identity=engine.begin()['run_id'];run=engine.get(identity)
        for index,state in enumerate(task.document.states):
            run.index=index;card=getattr(task,'cards',{}).get(state.state_id)
            selecteds=[s.id for s in card.substeps] if card and card.substeps else ['']
            for selected in selecteds:
                if card:
                    engine.ensure(run)
                    if selected:run.tutorial_substeps[state.state_id]=selected
                p=engine.view(run)['presentation'];lesson=service.lessons.compose(variant,state.state_id,selected,p,task)
                assert lesson['reviewed'] and lesson['sections'];count+=1
                spec=service.lessons.bundle['cards'][variant+'/'+state.state_id+'/'+(selected or '-')]
                fields=source_fields(p,task,spec['source_refs']);assert source_hash(fields)==lesson['source_sha256']
                for block in spec['blocks']:
                    a,b=block['source_span'];assert hashlib.sha256(fields[block['source_field']][a:b].encode()).hexdigest()==block['span_sha256']
                    assert all(c in task.evidence['evidence'] for c in block['citation_ids'])
                assert all(s['kind'] in ('scope','precondition','action','materials','caution','note') for s in lesson['sections'])
    assert count==57 and not fake.calls


def test_purge_steps_and_parallelism_notice_are_separate(guide):
    c,fake,_,_=guide;run=browse(c,start(c,UNBOX),'U6');lesson=run['presentation']['lesson']
    assert '从后往前' in texts(lesson,'action') and 'M3-12' in texts(lesson,'action')
    assert '平行' not in texts(lesson,'action') and '碰撞' in texts(lesson,'caution')
    assert len(next(s for s in lesson['sections'] if s['kind']=='action')['blocks'])==2
    assert run['can_advance'] and run['user_marked_step_ids']==[] and not fake.calls


def test_handling_warning_is_visible_and_single_machine_does_not_instruct_removing_ams(guide):
    c,_,_,_=guide;run=browse(c,start(c,UNBOX),'U2','U2-S2');lesson=run['presentation']['lesson']
    assert 'AMS lite 和打印机' not in texts(lesson,'action')
    assert '请勿用手提起 X 轴导轨' in texts(lesson,'caution')
    assert '在开箱过程中需要被移除' in texts(lesson,'caution')


def test_power_prerequisites_precede_power_action_and_film_warning_reappears_at_film_step(guide):
    c,_,_,_=guide;run=browse(c,start(c,UNBOX),'U10');lesson=run['presentation']['lesson']
    kinds=[s['kind'] for s in lesson['sections']]
    assert kinds.index('precondition')<kinds.index('action')
    assert '保护泡沫' in texts(lesson,'precondition') and '安全空间' in texts(lesson,'precondition')
    assert '4-pin' not in texts(lesson,'action')
    run=browse(c,run,'U8');assert '保留最后一层' in texts(run['presentation']['lesson'],'caution')


def test_changed_source_cannot_silently_keep_old_editorial_classification(guide):
    c,_,service,_=guide;run=start(c,UNBOX);_,engine,_=service.parts(run['run_id'])
    p=deepcopy(run['presentation']);p['instruction']+='源文本已变化'
    with pytest.raises(ValueError,match='source changed'):
        service.lessons.compose('standalone_unboxing','U1','',p,engine.task)


def test_applicability_is_preserved_in_one_supplement_instead_of_scope_card(guide):
    c,_,service,_=guide;run=browse(c,start(c,UNBOX),'U7','U7-S1');lesson=run['presentation']['lesson']
    assert not any(section['kind']=='scope' for section in lesson['sections'])
    notes=[section for section in lesson['sections'] if section['kind']=='note'];assert len(notes)==1
    _,engine,_=service.parts(run['run_id'])
    card=service.lessons.bundle['cards']['standalone_unboxing/U7/U7-S1']
    original=[block['text'] for block in card['blocks'] if block['kind']=='scope']
    assert original and all(text in texts(lesson,'note') for text in original)
    assert lesson['source_sha256']==card['source_sha256']
