"""Three-stage manual compilation with bounded repair and field-level evidence lineage."""
import base64
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import re
import shutil
import time
from PIL import Image
from manual2ar.knowledge.wiki import write_json
from manual2ar.modules.guidance.models import ProcedureDocument
from .models import Claim, ExtractedActions, DraftGraph, DraftObservations, DirectDraft
from . import prompts
from .source import fingerprint, model_source


NONVISUAL = re.compile(r'紧固|人工(?:确认|核实)|机械锁止|扭矩|断电|无电|内部.{0,8}(卡|锁|紧)|牢固|稳固|校准.{0,5}(完成|成功)|初始化.{0,5}完成|温度|已(?:从|经从).{0,30}(滑入|移动|旋转)|已使用.{0,25}固定|已.{0,8}(拧紧|锁紧)')


def claims(value, prefix=''):
    if isinstance(value, Claim):
        yield prefix, value
    elif isinstance(value, list):
        for i,item in enumerate(value):yield from claims(item, prefix+'/'+str(i))
    elif hasattr(type(value), 'model_fields'):
        for key in type(value).model_fields:yield from claims(getattr(value,key),prefix+'/'+key)


def check_claims(value, bundle):
    for path, claim in claims(value):
        if len(claim.citation_ids)!=len(set(claim.citation_ids)):
            raise ValueError('Duplicate citation at '+path)
        if any(c not in bundle['evidence'] for c in claim.citation_ids):
            raise ValueError('Unknown citation at '+path)
        if any(i not in {image['id'] for image in bundle['images']} for i in claim.image_ids):
            raise ValueError('Unknown source image at '+path)
        if not claim.text.strip() or not claim.rationale.strip():
            raise ValueError('Blank claim at '+path)


def check_graph(graph, bundle, locked=None):
    check_claims(graph, bundle)
    ids=[s.action_id for s in graph.states]
    if len(set(ids))!=len(ids) or any(not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,39}',i) for i in ids):
        raise ValueError('Invalid or duplicate action identity')
    if locked is not None and ids!=[a.action_id for a in locked.actions]:
        raise ValueError('Locked action order/coverage changed')
    for state in graph.states:
        if len(set(state.target_components))!=len(state.target_components) or not all(
            re.fullmatch(r'(source|target):\S.{0,159}',c) for c in state.target_components):
            raise ValueError('Targets require unique source:/target: names')
        if not any(c.startswith('source:') for c in state.target_components):
            raise ValueError('Action lacks manipulated source object')
        before={c.text.strip() for c in state.preconditions}
        after={c.text.strip() for c in state.postconditions}
        wrong={c.text.strip() for c in state.wrong_states}
        if before & after or after & wrong or before & wrong or len(after)!=len(state.postconditions):
            raise ValueError('Repeated or contradictory state condition lists')
        if state.instruction.origin=='observation_policy':
            raise ValueError('Observation policy cannot become equipment instruction')
    return graph


def check_observations(value, graph, bundle):
    check_claims(value,bundle)
    states={s.action_id:s for s in graph.states};seen=set();errors=[]
    for node in value.observations:
        key=(node.action_id,node.postcondition_index)
        if key in seen or node.action_id not in states:
            raise ValueError('Duplicate or unknown observation identity')
        state=states[node.action_id]
        if node.postcondition_index>=len(state.postconditions):
            raise ValueError('Unknown postcondition index')
        seen.add(key)
        if len(node.component_ids)!=len(set(node.component_ids)) or not set(node.component_ids)<=set(state.target_components):
            raise ValueError('Observation component is outside locked action')
        if any(c.origin!='observation_policy' for c in (node.capture_instruction,node.visibility_limit)):
            raise ValueError('Capture/visibility guidance must be marked observation_policy')
        if node.verification_channel!='vision' and node.visualization!='none':
            errors.append(f'{node.action_id}/{node.postcondition_index}: Invisible condition cannot display a visual proof; set visualization=none')
        if node.verification_channel=='vision' and NONVISUAL.search(state.postconditions[node.postcondition_index].text):
            errors.append(f'{node.action_id}/{node.postcondition_index}: Nonvisual condition requires manual/sensor verification; separate visible appearance from actual mechanical fastening')
    expected={(s.action_id,i) for s in graph.states for i in range(len(s.postconditions))}
    if seen!=expected:
        raise ValueError('Every locked postcondition needs exactly one observation')
    if errors:raise ValueError('; '.join(errors))
    return value


def provenance(citation_ids, bundle):
    ids=list(dict.fromkeys(citation_ids));rows=[bundle['evidence'][c] for c in ids]
    first=rows[0]
    return dict(page=None,section=' / '.join(first['heading_path']) or '官方资料',source_type='wiki',
        source_url=first['source_url'],source_text='\n'.join(r['text'] for r in rows),citation_ids=ids,snapshot_id=first['snapshot_id'])


def assemble(graph, observations, bundle, request):
    lineage={};states=[]
    for i,state in enumerate(graph.states):
        identity=f'S{i+1}'
        source_ids=[]
        for path,claim in claims(state):
            source_ids.extend(claim.citation_ids)
            lineage['/states/'+str(i)+path]=claim.model_dump()
        nodes=[]
        for j,condition in enumerate(state.postconditions):
            node=next(n for n in observations.observations if (n.action_id,n.postcondition_index)==(state.action_id,j))
            ids=condition.citation_ids+node.capture_instruction.citation_ids+node.visibility_limit.citation_ids
            for field in ('capture_instruction','visibility_limit'):
                lineage[f'/states/{i}/observation_nodes/{j}/{field}']=getattr(node,field).model_dump()
            nodes.append(dict(inspection_id=f'{identity}-C{j+1}',condition=condition.text,component_ids=node.component_ids,
                viewpoint=node.viewpoint,capture_instruction=node.capture_instruction.text+'\n'+node.visibility_limit.text,
                evidence_type=node.evidence_type,visualization=node.visualization,verification_channel=node.verification_channel,
                manual_provenance=provenance(ids,bundle),requires_same_frame=node.requires_same_frame))
        states.append(dict(state_id=identity,step_index=i,state_type='action',instruction=state.instruction.text,
            **{k:[c.text for c in getattr(state,k)] for k in ('preconditions','postconditions','wrong_states','warnings')},
            target_components=state.target_components,manual_provenance=provenance(source_ids,bundle),
            verification='按观察点核验；证据不足返回 uncertain；不可见条件须人工或传感器确认。',
            next_on_success=f'S{i+2}' if i+1<len(graph.states) else None,observation_nodes=nodes))
    for path,claim in claims(graph.limitations,'/limitations'):lineage[path]=claim.model_dump()
    document=ProcedureDocument.model_validate(dict(schema_version='0.9',
        device=dict(device_id=request['device_id'],name=request['device_name']),
        task=dict(task_id=request['task_id'],manual_id=bundle['revision'],initial_state='S1',terminal_states=[f'S{len(states)}'],
                  parameters={'compilation_status':'draft_requires_review','applicability':request['applicability']}),states=states))
    return document,lineage


def encoded_images(bundle):
    result=[]
    for item in bundle['images']:
        raw=Path(item['path']).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=item['sha256']:raise ValueError('Source image changed')
        with Image.open(io.BytesIO(raw)) as image:
            image.seek(0);image=image.convert('RGB');image.thumbnail((1400,1400))
            stream=io.BytesIO();image.save(stream,format='JPEG',quality=90)
            result.append(base64.b64encode(stream.getvalue()).decode())
    return result


def load_example(folder, bundle):
    folder=Path(folder)
    review=json.loads((folder/'review.json').read_text())
    draft=json.loads((folder/'draft.json').read_text());source=json.loads((folder/'source.json').read_text())
    if review.get('status')!='approved' or not review.get('reviewer') or review.get('draft_sha256')!=fingerprint(draft) or review.get('source_revision')!=source['revision']:
        raise ValueError('Few-shot example must have a source-bound, independently approved draft')
    if set(source['evidence']) & set(bundle['evidence']):raise ValueError('Few-shot example leaks target evidence')
    return dict(source=model_source(source),draft=draft,source_revision=source['revision'],draft_sha256=fingerprint(draft))


class Compiler:
    def __init__(self, client, settings, max_repairs=1):
        if max_repairs not in (0,1):raise ValueError('Allow at most one bounded repair per stage')
        self.client,self.settings,self.max_repairs=client,settings,max_repairs

    def compile(self,bundle,request,output,mode='staged',examples=()):
        if mode not in ('direct','staged'):raise ValueError('Unknown compiler mode')
        folder=Path(output).resolve()
        if folder.exists() and any(folder.iterdir()):raise ValueError('Output must be new or empty; no previous result is overwritten')
        folder.mkdir(parents=True,exist_ok=True)
        if not all(str(request.get(k,'')).strip() for k in ('device_id','device_name','task_id','title','applicability')):
            raise ValueError('Explicit device, task scope/title and applicability are required')
        examples=[load_example(p,bundle) for p in examples]
        images=encoded_images(bundle);calls=[]
        write_json(folder/'source.json',bundle);write_json(folder/'request.json',request)
        manifest=dict(schema_version='manual2ar-compilation-run-v1',status='running',mode=mode,prompt_version=prompts.VERSION,
            source_revision=bundle['revision'],model=self.settings['model'],temperature=self.settings.get('temperature',0),
            enable_thinking=self.settings.get('enable_thinking',False),compiler_sha256=fingerprint({p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(__file__).parent.glob('*.py')}),
            example_revisions=[e['source_revision'] for e in examples],started_at=datetime.now(timezone.utc).isoformat(),calls=calls)
        write_json(folder/'run.json',manifest)
        base=prompts.COMMON+'\nREQUEST:\n'+json.dumps(request,ensure_ascii=False)+'\nSOURCE:\n'+json.dumps(model_source(bundle),ensure_ascii=False)
        if examples:base+='\nREVIEWED_EXAMPLES (different tasks; never copy their IDs/citations):\n'+json.dumps(examples,ensure_ascii=False)

        def stage(name,instruction,model,validate):
            text=base+'\n'+instruction;error='';previous=None
            for attempt in range(self.max_repairs+1):
                prompt=text+('\nPREVIOUS_REJECTED_OUTPUT:\n'+json.dumps(previous,ensure_ascii=False)+'\nVALIDATION_ERROR:\n'+error+'\n只修复本阶段输出，不修改锁定内容。' if error else '')
                stem=f'{name}-{attempt}';(folder/(stem+'.prompt.txt')).write_text(prompt)
                write_json(folder/(stem+'.schema.json'),model.model_json_schema());started=time.perf_counter()
                row=dict(stage=name,attempt=attempt,image_count=len(images));calls.append(row)
                try:
                    raw=self.client.chat_structured(prompt=prompt,schema=model.model_json_schema(),images_base64=images,max_tokens=14000)
                    write_json(folder/(stem+'.response.json'),raw);previous=raw
                    answer=model.model_validate(raw);validate(answer)
                    row.update(status='accepted',elapsed_ms=round((time.perf_counter()-started)*1000))
                    write_json(folder/'run.json',manifest);return answer
                except ValueError as exc:
                    # Only local schema/contract failures are repairable. Provider failures retain their own retry policy.
                    error=str(exc)[:3000];row.update(status='rejected',error=error,elapsed_ms=round((time.perf_counter()-started)*1000))
                    write_json(folder/'run.json',manifest)
                except Exception as exc:
                    row.update(status='provider_failed',error_type=type(exc).__name__,elapsed_ms=round((time.perf_counter()-started)*1000))
                    write_json(folder/'run.json',manifest);raise
            raise ValueError('Compiler validation failed at '+name+': '+error)
        try:
            if mode=='direct':
                def validate_direct(value):
                    check_graph(value,bundle);check_observations(value,value,bundle)
                direct=stage('direct',prompts.GRAPH+'\n'+prompts.OBSERVE+'\n'+prompts.DIRECT,DirectDraft,validate_direct)
                graph=DraftGraph(states=direct.states,limitations=direct.limitations)
                observations=DraftObservations(observations=direct.observations)
            else:
                def validate_extract(value):
                    check_claims(value,bundle)
                    ids=[a.action_id for a in value.actions]
                    if len(ids)!=len(set(ids)):raise ValueError('Duplicate extracted action')
                extracted=stage('extract',prompts.EXTRACT,ExtractedActions,validate_extract)
                write_json(folder/'action_evidence.json',extracted.model_dump())
                graph=stage('graph',prompts.GRAPH+'\nLOCKED_ACTIONS:\n'+extracted.model_dump_json(),DraftGraph,
                            lambda v:check_graph(v,bundle,extracted))
                known={(c.text,tuple(c.citation_ids)) for c in graph.limitations}
                graph.limitations.extend(c for c in extracted.limitations if (c.text,tuple(c.citation_ids)) not in known)
                observations=stage('observe',prompts.OBSERVE+'\nLOCKED_GRAPH:\n'+graph.model_dump_json(),DraftObservations,
                                   lambda v:check_observations(v,graph,bundle))
            write_json(folder/'draft.json',{**graph.model_dump(),**observations.model_dump()})
            document,lineage=assemble(graph,observations,bundle,request)
            write_json(folder/'lineage.json',lineage)
            self.export(folder,document,bundle,request)
            used={c for row in lineage.values() for c in row['citation_ids']}
            warnings=[dict(field=path,reason='推导或观察策略需审核') for path,c in lineage.items() if c['origin']!='explicit']
            write_json(folder/'review.json',dict(status='pending',reviewer='',draft_sha256=fingerprint(json.loads((folder/'draft.json').read_text())),
                source_revision=bundle['revision'],semantic_entailment_checked=False,items=warnings,
                unchecked_source_ids=sorted(set(bundle['evidence'])-used)))
            manifest.update(status='draft_requires_review',states=len(document.states),observations=len(observations.observations),
                citation_reference_validity=1.0,semantic_support_accuracy=None,elapsed_ms=sum(c['elapsed_ms'] for c in calls),
                procedure_sha256=hashlib.sha256((folder/'task/procedure.json').read_bytes()).hexdigest())
            write_json(folder/'run.json',manifest)
            return folder
        except Exception as exc:
            manifest.update(status='failed',error_type=type(exc).__name__)
            write_json(folder/'run.json',manifest)
            raise

    @staticmethod
    def export(folder,document,bundle,request):
        root=folder/'task';root.mkdir();params=document.task.parameters
        params.update(title=request['title'],description=request['applicability'],presentation={},inspection_prompts={})
        images={}
        for item in bundle['images']:
            name=item['sha256'][:24]+Path(item['path']).suffix.lower();relative='references/'+name
            (root/'references').mkdir(exist_ok=True);shutil.copyfile(item['path'],root/relative)
            images[relative]={**{k:v for k,v in item.items() if k!='path'},'path':relative}
        for state in document.states:
            urls={bundle['evidence'][c]['source_url'] for c in state.manual_provenance.citation_ids}
            headings={tuple(bundle['evidence'][c]['heading_path'][:1]) for c in state.manual_provenance.citation_ids}
            references=[p for p,v in images.items() if v['source_page'] in urls and tuple(v['heading_path'][:1]) in headings]
            index=state.step_index
            lineage=json.loads((folder/'lineage.json').read_text())
            selected={image for path,claim in lineage.items() if path.startswith(f'/states/{index}/') for image in claim.get('image_ids',[])}
            if selected:references=[p for p,v in images.items() if v['id'] in selected]
            params['presentation'][state.state_id]=dict(title=state.instruction,tools=[],materials=[],reference_images=references)
            for node in state.observation_nodes:
                if node.verification_channel!='vision':continue
                text=(f'仅核验当前可见事实。步骤={state.state_id}；观察点={node.inspection_id}。\n条件：{node.condition}\n'
                      f'拍摄与证据边界：{node.capture_instruction}\n证据不足/遮挡返回uncertain，不当作操作错误；明确矛盾返回wrong_operation；可见条件满足返回completed。'
                      '\n不得从照片推断扭矩、隐藏卡紧或设备安全状态。请用中文说明可见证据及下一步建议。\n官方上下文：'+node.manual_provenance.source_text)
                relative='prompts/'+node.inspection_id+'.txt';(root/'prompts').mkdir(exist_ok=True);body=text.encode();(root/relative).write_bytes(body)
                params['inspection_prompts'][node.inspection_id]=dict(state_id=state.state_id,path=relative,sha256=hashlib.sha256(body).hexdigest())
        write_json(root/'procedure.json',document.model_dump())
        write_json(root/'evidence.json',dict(evidence=bundle['evidence'],images=images))
