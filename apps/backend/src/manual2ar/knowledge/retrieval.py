"""Local, source-preserving BM25 retrieval over the device's archived chapters."""
from collections import Counter
import hashlib
import math
import re
from pathlib import Path
from .compilation.source import fingerprint, select
from .wiki import write_json


def terms(text):
    text=text.lower()
    words=re.findall(r'[a-z0-9]+(?:[-_.][a-z0-9]+)*',text)
    for span in re.findall(r'[\u3400-\u9fff]+',text):
        if len(span)==1:words.append(span)
        for size in (2,3,4):words.extend(span[i:i+size] for i in range(len(span)-size+1))
    return words


class EvidenceIndex:
    def __init__(self,wiki):
        self.wiki=wiki;self.sections=[]
        # Device/language filtering is explicit; there is no preselected U7 page.
        for identity,record in sorted(wiki.pages.items()):
            if '/zh/a1-mini/' not in record['url']:continue
            groups={}
            for block in wiki.extraction(identity)['blocks']:
                heading=tuple(block['heading_path'])
                if len(heading)>1 and re.match(r'^\d+[.、．]',heading[-1]):heading=heading[:-1]
                groups.setdefault(heading,[]).append(block['text'])
            for heading,blocks in groups.items():
                if not heading:continue
                text='\n'.join(blocks)
                self.sections.append(dict(url=record['url'],title=record['title'],heading=list(heading),
                    text=text,counts=Counter(terms(' '.join(heading)*3+' '+text)),length=len(terms(text))))
        self.df=Counter(t for row in self.sections for t in row['counts'])
        self.average=sum(r['length'] for r in self.sections)/max(1,len(self.sections))

    def bundle_for(self,url,heading,hierarchy=False):
        part=select(self.wiki,[url],[heading[-1]],max_images=8)
        if not hierarchy:return part
        whole=select(self.wiki,[url],max_images=8)
        def inside(path):return path[:len(heading)]==heading
        evidence={k:v for k,v in whole['evidence'].items() if inside(v['heading_path']) or
            (heading[:len(v['heading_path'])]==v['heading_path'] and re.search('注意|警告|禁止|必须',v['text']))}
        part['evidence']=evidence;part['images']=[i for i in part['images'] if inside(i['heading_path'])]
        for page in part['pages']:page['citation_ids']=[k for k,v in evidence.items() if v['source_url']==page['url']]
        return part

    def retrieve(self,query,folder,limit=1,reranker=None,*,hierarchy=False,enrich=None):
        query_terms=set(terms(query));ranked=[];n=len(self.sections)
        for row in self.sections:
            score=0.
            for term in query_terms:
                tf=row['counts'].get(term,0)
                if tf:score+=math.log(1+(n-self.df[term]+.5)/(self.df[term]+.5))*tf*2.2/(tf+1.2*(.25+.75*row['length']/max(1,self.average)))
            if score:ranked.append((score,row))
        ranked.sort(key=lambda v:(-v[0],v[1]['url'],v[1]['heading']))
        if not ranked:raise ValueError('没有找到匹配的设备资料，请明确部件与安装目标。')
        lexical=list(ranked)
        if hierarchy:
            documents={}
            for score,row in ranked:documents.setdefault(row['url'],[]).append(score)
            top=sorted(documents,key=lambda u:(-max(documents[u])-.15*sum(documents[u][:3]),u))[:3]
            ranked=[pair for pair in ranked if pair[1]['url'] in top]
        if reranker:
            options=[dict(section_id=i,url=row['url'],heading=row['heading'],excerpt=row['text'][:1800]) for i,(_,row) in enumerate(ranked[:8])]
            if enrich:options=enrich(options)
            write_json(Path(folder)/'retrieval-candidates.json',options)
            index=reranker(options)
            if not isinstance(index,int) or isinstance(index,bool) or not 0<=index<len(options):raise ValueError('Invalid section selection')
            ranked=[ranked[index]]
        chosen=[];evidence={};images={};pages=[]
        for score,row in ranked:
            if len(chosen)>=limit or score<ranked[0][0]*.60:break
            # A parent includes children; avoid charging the same evidence twice.
            if any(row['url']==c['url'] and row['heading'][:len(c['heading'])]==c['heading'] for c in chosen):continue
            heading=row['heading']
            # Numbered subheadings describe a single action; retrieve their whole task section.
            if len(heading)>1 and re.match(r'^\d+[.、．]',heading[-1]):heading=heading[:-1]
            part=self.bundle_for(row['url'],heading,hierarchy)
            if sum(len(e['text']) for e in {**evidence,**part['evidence']}.values())>24000:continue
            evidence.update(part['evidence']);pages.extend(part['pages'])
            for image in part['images']:images.setdefault(image['id'],image)
            chosen.append(dict(url=row['url'],heading=heading,score=round(score,5),reason='BM25命中，按原任务章节补全段落、子节与图片'))
        if not evidence:raise ValueError('相关章节超出输入预算，请缩小安装目标。')
        bundle=dict(schema_version='manual2ar-compiler-source-v1',archive_sha256=self.wiki.snapshot_sha256,
            evidence=evidence,pages=pages,images=list(images.values())[:8],omitted_images=max(0,len(images)-8))
        bundle['revision']=fingerprint({**bundle,'images':[{k:v for k,v in i.items() if k!='path'} for i in bundle['images']]})
        write_json(Path(folder)/'retrieval.json',dict(query=query,method='hierarchical-bm25-v1' if hierarchy else 'bm25-section-cjk2-4-v1',
            filter='/zh/a1-mini/',indexed_sections=n,selected=chosen,
            ranked=[dict(url=r['url'],heading=r['heading'],score=round(s,5)) for s,r in lexical[:10]],
            source_revision=bundle['revision'],archive_sha256=self.wiki.snapshot_sha256))
        write_json(Path(folder)/'evidence-bundle.json',bundle)
        return bundle
