"""Join pipeline timings with front-end frame receipts; no accuracy claims."""
import csv
import hashlib
import html
import json
from manual2ar.paths import ROOT


def register(value,knowledge,provider):
    path=value.log.path/'manifest.json'
    manifest=json.loads(path.read_text())
    files=list((ROOT/'apps/backend/src/manual2ar/modules/learning').glob('*.py'))+list((ROOT/'packages/perception/src/manual2ar_perception').glob('*.py'))+list((ROOT/'apps/inference/src/manual2ar_inference/engines').glob('*.py'))
    scripts=ROOT/'apps/unity/Manual2AR/Assets/Manual2AR/Scripts/Learning'
    files.extend(scripts.glob('*.cs'))
    from manual2ar.resources import ResourceStore
    selected=ResourceStore.configured(value.tracker.config).path('device.knowledge')
    files.append(selected)
    files=[p for p in files if p.is_file()]
    from .manage import public
    config=value.tracker.config
    manifest['public_config']=public(config)
    manifest['performance']=config.get('performance',{})
    manifest['learning']={'knowledge_revision':knowledge.revision,'first_mask':provider,'tracking':value.tracker.health()['tracking'],
        'cpu_tracking':config['cpu_tracking'],
        'cutie_tracking':{k:v for k,v in config['cutie_tracking'].items() if k!='connection_file'},
        'source_sha256':{(p.relative_to(ROOT).as_posix() if p.is_relative_to(ROOT) else p.name):hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
        'scope':'one visible instance per eight configured types; eight verbatim official knowledge entries; no ground-truth accuracy'}
    path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')


def report(value):
    with value.log.lock:
        events=[]
        for line in (value.log.path/'events.jsonl').read_text().splitlines():
            try:events.append(json.loads(line))
            except ValueError:continue
    requests={};checks={}
    for e in events:
        name=e.get('event')
        if name=='learning.input':requests.setdefault(e['client_frame_id'],{}).update(input=e)
        elif name=='learning.response':requests.setdefault(e['client_frame_id'],{}).update(response=e)
        elif name=='frontend.render':requests.setdefault(e['client_frame_id'],{}).update(render=e)
        elif name=='segmentation.result':checks.setdefault(e['check_id'],[]).append(e)
    rows=[]
    for client_id,parts in requests.items():
        source=parts.get('input',{});reply=parts.get('response',{});render=parts.get('render',{})
        rendered=render.get('results',[])
        rows.append({'client_frame_id':client_id,'check_id':reply.get('check_id',''),'mode':source.get('stage',''),
            'source':source.get('source',''),'vlm_ms':reply.get('vlm_ms',''),'backend_total_ms':reply.get('elapsed_ms',''),
            'frontend_roundtrip_ms':render.get('request_ms',''),'render_attempted':sum(bool(r.get('attempted')) for r in rendered),
            'frontend_decode_ms':round(sum(r.get('decode_ms',0) for r in rendered),2),
            'capture_encode_ms':render.get('capture_encode_ms',''),'frame_age_ms':render.get('frame_age_ms',''),
            'active_sessions':reply.get('active_sessions',''),'batch_metrics':reply.get('batch_metrics',{}),
            'render_passed':sum(bool(r.get('passed')) for r in rendered),
            'source_identity_ok':bool(render) and source.get('source_sha256')==render.get('source_sha256'),
            'source_sha256':source.get('source_sha256',''),'render_received':bool(render)})
    columns=['client_frame_id','check_id','mode','source','vlm_ms','backend_total_ms','frontend_roundtrip_ms','frontend_decode_ms','render_attempted','render_passed','source_identity_ok','source_sha256','render_received','capture_encode_ms','frame_age_ms','active_sessions','batch_metrics']
    with (value.log.path/'learning_requests.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=columns);writer.writeheader();writer.writerows(rows)
    from .performance import write_report
    performance=write_report(value.log.path,events)
    providers=[e for e in events if e.get('event') in ('learning.segmenter','learning.segmenter_error','segmentation.prepare_error','learning.cutie_frame','learning.cutie_error','learning.cutie_cleanup_error')]
    receipts=[e for e in events if e.get('event')=='frontend.render']
    result={'performance':performance,'requests':rows,'initial_segmentation':checks,'segmenter_events':providers,'frontend_receipts':receipts,'events':len(events),
        'interpretation':'render_passed means PNG decoded and layers set, not a completed Unity Canvas/GPU draw. Frame identity and stage acceptance are not semantic accuracy or segmentation IoU.'}
    (value.log.path/'learning_report.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    table='<table><tr>'+''.join('<th>'+html.escape(c)+'</th>' for c in columns[:11])+'</tr>'
    for row in rows:table+='<tr>'+''.join('<td>'+html.escape(str(row[c]))+'</td>' for c in columns[:11])+'</tr>'
    table+='</table>'
    details='<h2>分割提供方耗时与错误</h2><pre>'+html.escape(json.dumps(providers,ensure_ascii=False,indent=2))+'</pre>'
    details+=''.join('<h2>'+html.escape(check)+'</h2><p><a href="'+check+'/boxes.jpg">VLM框与点</a> · <a href="'+check+'/overlay.jpg">通过门限的分割</a> · <a href="'+check+'/vlm_raw.json">VLM原始输出</a> · <a href="'+check+'/summary.json">规则结果</a></p><pre>'+html.escape(json.dumps(items,ensure_ascii=False,indent=2))+'</pre>' for check,items in checks.items())
    details+='<h2>Unity 图层接收回执（不代表画布已完成绘制）</h2><p>render_passed 仅表示 PNG 解码并设置图层成功。之后的 Canvas 裁剪、网格更新仍可能报错；画面异常时请同时查看 Unity Console / Editor.log。旧客户端可能将 JSON null 解码为空对象，导致 render_attempted 虚高。</p><pre>'+html.escape(json.dumps(receipts,ensure_ascii=False,indent=2))+'</pre>'
    (value.log.path/'learning_report.html').write_text('<!doctype html><meta charset="utf-8"><title>模块一流水线诊断</title><style>body{font:15px/1.6 sans-serif;margin:24px}table{border-collapse:collapse}td,th{border:1px solid #bbc;padding:6px}pre{white-space:pre-wrap}</style><h1>模块一流水线诊断</h1><p>VLM、初始分割、CPU或Cutie跟踪及Unity显示分别记录。帧身份一致和门限通过不等于识别准确。</p><p><a href="learning_requests.csv">请求CSV</a> · <a href="learning_report.json">完整规则与指标</a> · <a href="events.jsonl">事件流</a> · <a href="knowledge_snapshot.json">本次知识版本</a> · <a href="report.html">原始视觉报告</a></p>'+table+details,encoding='utf-8')
