"""Same-photo experiment batches. Dry plan by default; --run calls models, never approves AR."""
import argparse
import csv
import io
import json
from pathlib import Path
import time
import urllib.request
from manual2ar.modules.guidance.experiments import Features,FEATURES


def methods(matrix=False):
 full=Features(**dict.fromkeys(FEATURES,True)).model_dump()
 result={'baseline':Features().model_dump(),'full':full,'text_only':Features(text_only=True).model_dump()}
 if matrix:
  result.update({'only-'+k:Features(**{k:True}).model_dump() for k in FEATURES})
  result.update({'without-'+k:{**full,k:False} for k in FEATURES})
 return result


def request(origin,path,body=None):
 op=urllib.request.build_opener(urllib.request.ProxyHandler({}))
 req=urllib.request.Request(origin.rstrip('/')+'/api/guidance/pipeline'+path,
  data=None if body is None else json.dumps(body).encode(),headers={'Content-Type':'application/json'})
 with op.open(req,timeout=30) as response:return json.load(response)


def export(origin,output):
 result=request(origin,'/experiments/results');(output/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
 rows=[]
 for value in result['rows']:
  rows.append({k:value.get(k) for k in ('id','status','method','source_sha256','procedure_sha256','elapsed_seconds')}|
   value.get('cost',{})|{k:value['human_review'].get(k,'unrated') for k in ('task_planning','component_binding','guidance','verification')})
 if rows:
  with (output/'results.csv').open('w',newline='',encoding='utf-8-sig') as stream:
   writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
 return result


def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--job',required=True);parser.add_argument('--output',type=Path,required=True)
 parser.add_argument('--url',default='http://127.0.0.1:8011');parser.add_argument('--matrix',action='store_true');parser.add_argument('--run',action='store_true')
 args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True);path=args.output/'batch.json'
 plan=dict(source_job=args.job,methods=methods(args.matrix),runs={})
 if path.exists():
  previous=json.loads(path.read_text())
  if any(previous[k]!=plan[k] for k in ('source_job','methods')):raise ValueError('Use a new output directory for another experiment definition')
  plan=previous
 def save():path.write_text(json.dumps(plan,ensure_ascii=False,indent=2))
 save()
 if not args.run:print(str(path)+' (dry plan; --run starts model calls)');return
 source=request(args.url,'/jobs/'+args.job)
 for name,features in plan['methods'].items():
  if name not in plan['runs']:
   created=request(args.url,'/jobs/'+args.job+'/repeat',features)
   plan['runs'][name]=dict(id=created['id']);save()
  identity=plan['runs'][name]['id'];deadline=time.monotonic()+1800
  while True:
   result=request(args.url,'/jobs/'+identity)
   if result['source_sha256']!=source['source_sha256']:raise ValueError('Paired experiment photo mismatch')
   plan['runs'][name].update(status=result['status'],elapsed_seconds=result.get('elapsed_seconds'),cost=result.get('cost'));save()
   if result['status'] in ('ready','failed','unsupported','approved'):break
   if time.monotonic()>deadline:raise TimeoutError('Job retained; repeat this command to resume polling')
   time.sleep(1)
  print(name,identity,result['status'],flush=True)
 export(args.url,args.output)


if __name__=='__main__':main()
