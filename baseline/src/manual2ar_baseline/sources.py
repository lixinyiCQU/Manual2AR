"""Read-only retrieval of whole task sections from a pinned official offline archive."""
from collections import Counter
from html.parser import HTMLParser
import json
import math
from pathlib import Path
import re
from urllib.parse import quote, urldefrag, urljoin, urlsplit

from manual2ar_baseline.gt import Artifact, ReferenceImage, Source, Sources, digest, encoded

BLOCK = {'p','li','table','pre','blockquote','figcaption',*(f'h{i}' for i in range(1,7))}
HIDDEN = {'script','style','noscript','nav','header','footer','button','form','template'}
VOID = {'area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'}


class Node:
    def __init__(self, tag='root', attrs=(), parent=None):
        self.tag, self.attrs, self.parent, self.children = tag, dict(attrs), parent, []
    def walk(self):
        yield self
        for child in self.children:
            if isinstance(child, Node): yield from child.walk()
    def text(self, skip=False):
        if self.tag in HIDDEN or 'toc-anchor' in (self.attrs.get('class') or '').split(): return ''
        pieces = []
        for child in self.children:
            if isinstance(child,str): pieces.append(child)
            elif not (skip and child.tag in BLOCK):
                sep = ' ' if child.tag in BLOCK | {'div','section','br','hr','tr','td','th','dt','dd'} else ''
                pieces.append(sep + child.text(skip) + sep)
        return re.sub(r'\s+', ' ', ''.join(pieces)).strip()
    def selector(self):
        pieces=[]; node=self
        while node.parent:
            peers=[c for c in node.parent.children if isinstance(c,Node) and c.tag==node.tag]
            pieces.append(f'{node.tag}:nth-of-type({peers.index(node)+1})'); node=node.parent
        return ' > '.join(reversed(pieces))


class Parser(HTMLParser):
    def __init__(self, source):
        super().__init__(convert_charrefs=True); self.root=Node(); self.stack=[self.root]; self.feed(source); self.close()
    def handle_starttag(self, tag, attrs):
        node=Node(tag,attrs,self.stack[-1]); self.stack[-1].children.append(node)
        if tag not in VOID: self.stack.append(node)
    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag,attrs)
        if tag not in VOID: self.handle_endtag(tag)
    def handle_endtag(self, tag):
        for i in range(len(self.stack)-1,0,-1):
            if self.stack[i].tag==tag: del self.stack[i:]; break
    def handle_data(self, data): self.stack[-1].children.append(data)


def canonical(url, base=''):
    url=urldefrag(urljoin(base,url.strip()))[0]; parsed=urlsplit(url)
    if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password: return None
    return quote(url,safe="/%:@!$&'()*+,;=-._~?")


def parsed(source, url):
    tree=Parser(source).root; nodes=list(tree.walk())
    content=next((n for n in nodes if 'contents' in (n.attrs.get('class') or '').split()), None)
    if content is None: content=next((n for tag in ('article','main') for n in nodes if n.tag==tag),None)
    if content is None: raise ValueError('Official article content missing')
    blocks=[]; images=[]; headings=[]
    for node in content.walk():
        ancestors=[]; parent=node.parent
        while parent: ancestors.append(parent.tag); parent=parent.parent
        if set(ancestors) & HIDDEN: continue
        if node.tag in BLOCK and 'table' not in ancestors:
            text=node.text(node.tag not in {'table','pre','blockquote'})
            if re.fullmatch('h[1-6]',node.tag):
                headings=[h for h in headings if h[0]<int(node.tag[1])]+[(int(node.tag[1]),text)]
            if text: blocks.append((len(blocks)+1,node.tag,text,[h[1] for h in headings],node.selector()))
        if node.tag=='img':
            values=[v for k,v in node.attrs.items() if k in ('src','data-src')]
            values += [p.strip().split()[0] for k in ('srcset','data-srcset') for p in (node.attrs.get(k) or '').split(',') if p.strip()]
            for value in values:
                link=canonical(value,url)
                if link: images.append((link,[h[1] for h in headings]))
        elif node.attrs.get('poster'):
            link=canonical(node.attrs['poster'],url)
            if link: images.append((link,[h[1] for h in headings]))
    return blocks,images


def terms(text):
    text=text.lower(); result=re.findall(r'[a-z0-9]+(?:[-_.][a-z0-9]+)*',text)
    for span in re.findall(r'[\u3400-\u9fff]+',text):
        for n in (2,3,4): result.extend(span[i:i+n] for i in range(len(span)-n+1))
    return result


def retrieve(archive_path, manifest_path, query, *, device_path='/zh/a1-mini/', source_url=None, assembly_context=False):
    if re.search(r'不希望|不想|不要|不需要|不打算|无需|不用|别(?:安装|拆除|拆卸)',query):
        raise ValueError('Negated or constrained operation goal requires clarification')
    archive_path,manifest_path=Path(archive_path).resolve(),Path(manifest_path).resolve()
    manifest=json.loads(manifest_path.read_bytes()); raw=archive_path.read_bytes(); archive_sha=digest(raw)
    if archive_sha!=manifest['archive_sha256']: raise ValueError('Official archive hash mismatch')
    archive=json.loads(raw); root=archive_path.parents[2]; rows=[]; pages={}
    def checked(obj):
        path=(root/obj['path']).resolve(); path.relative_to(root)
        value=path.read_bytes()
        if digest(value)!=obj['sha256'] or len(value)!=obj['bytes']: raise ValueError('Archived object hash mismatch')
        return path,value
    for url,page in sorted(archive['pages'].items()):
        if page.get('status')!='archived' or device_path not in url or (source_url and url!=source_url): continue
        if urlsplit(url).scheme!='https' or urlsplit(url).hostname!='wiki.bambulab.com': raise ValueError('Non-official page in archive')
        response=page['response']; checked(response['body']); dom= response.get('rendered_dom',response['body']); _,html=checked(dom)
        extraction=(root/page['artifact_dir']/'extraction.json').resolve(); extraction.relative_to(root)
        xraw=extraction.read_bytes(); value=json.loads(xraw); fresh,images=parsed(html.decode('utf-8'),url)
        observed=[(b['ordinal'],b['kind'],b['text'],b['heading_path'],b['dom_path']) for b in value['blocks']]
        if observed!=fresh or [(a['url'],a['heading_path']) for a in value['assets'] if a['kind']=='image']!=images:
            raise ValueError('Derived extraction differs from original DOM')
        if any(digest(b['text'].encode())!=b['text_sha256'] for b in value['blocks']): raise ValueError('Source text hash mismatch')
        pages[url]=(page,value,extraction,digest(xraw),dom)
        groups={}
        for i,b in enumerate(value['blocks']):
            heading=b['heading_path']
            if len(heading)>1 and re.match(r'^\d+[.、．]',heading[-1]): heading=heading[:-1]
            if heading: groups.setdefault(tuple(heading),[]).append(i)
        for heading,indexes in groups.items():
            text='\n'.join(value['blocks'][i]['text'] for i in indexes)
            rows.append(dict(url=url,heading=list(heading),text=text,counts=Counter(terms(' '.join(heading)*3+' '+text)),length=len(terms(text))))
    goal=re.split(r'(?:希望|想要|接下来(?:请)?|现在(?:请)?)',query)[-1].split('，')[0].split(',')[0]
    interpretation='literal_operation_goal'
    if assembly_context and not re.search('安装|拆除|拆卸|卸下|移除',goal) and re.match(r'^(完成|装好|组装)',goal):
        goal='安装'+re.sub(r'^(完成|装好|组装)(?:对)?','',goal)
        interpretation='completion_phrase_in_explicit_assembly_context'
    direction='remove' if re.search('拆除|拆卸|卸下|移除',goal) else 'install' if '安装' in goal else None
    if direction and re.search('拆除|拆卸|卸下|移除',goal) and '安装' in goal: raise ValueError('Ambiguous installation/removal goal')
    salient=set(terms(re.sub(r'安装|拆除|拆卸|卸下|移除|希望|想要|完成|现在|已经|请|我|的|了', '', goal)))
    if not salient: raise ValueError('Specify the target component')
    df=Counter(t for row in rows for t in row['counts']); avg=sum(r['length'] for r in rows)/max(1,len(rows)); ranked=[]
    for row in rows:
        if len(salient & row['counts'].keys()) < max(1, len(salient)*.25): continue
        title=' '.join(row['heading']); removal=bool(re.search('拆除|拆卸|卸下|移除',title))
        if direction=='install' and removal or direction=='remove' and not removal: continue
        score=0.
        for term in set(terms(goal)):
            tf=row['counts'].get(term,0)
            if tf: score+=math.log(1+(len(rows)-df[term]+.5)/(df[term]+.5))*tf*2.2/(tf+1.2*(.25+.75*row['length']/max(1,avg)))
        if score: ranked.append((score,row))
    ranked.sort(key=lambda pair:(-pair[0],pair[1]['url'],pair[1]['heading']))
    if not ranked: raise ValueError('No matching official task section')
    score,selected=ranked[0]
    if direction is None and any(s>=score*.85 and bool(re.search('拆除|拆卸|卸下|移除',' '.join(r['heading'])))!=bool(re.search('拆除|拆卸|卸下|移除',' '.join(selected['heading']))) for s,r in ranked[1:]):
        raise ValueError('Ambiguous installation/removal goal; specify the operation')
    url,heading=selected['url'],selected['heading']; page,value,extraction,xsha,dom=pages[url]
    indexes=[i for i,b in enumerate(value['blocks']) if b['heading_path'][:len(heading)]==heading]
    artifacts=[Artifact(id='archive',path=str(archive_path.relative_to(root)),sha256=archive_sha),Artifact(id='extraction',path=str(extraction.relative_to(root)),sha256=xsha)]
    for label,obj in [('body',page['response']['body']),('dom',dom)]: artifacts.append(Artifact(id=label,path=obj['path'],sha256=obj['sha256']))
    records=[]; associations={}
    for i in indexes:
        b=value['blocks'][i]; citation=digest(json.dumps([url,dom['sha256'],b['ordinal']],ensure_ascii=False,sort_keys=True).encode())[:24]
        identity='official.'+citation; associations[i]=identity
        records.append(Source(id=identity,artifact_id='extraction',locator=f'json:/blocks/{i}/text',kind='official',text=b['text'],text_sha256=b['text_sha256'],citation_id=citation,source_url=url))
    pictures=[]; seen=set()
    for image in value['assets']:
        if image['kind']!='image' or image['heading_path'][:len(heading)]!=heading: continue
        asset=archive['assets'].get(image['url'])
        if not asset or asset.get('status')!='archived': raise ValueError('Selected official image is not archived')
        obj=asset.get('body',asset.get('response',{}).get('body')); checked(obj)
        if obj['sha256'] in seen: continue
        seen.add(obj['sha256']); identity='image.'+obj['sha256']
        artifacts.append(Artifact(id=identity,path=obj['path'],sha256=obj['sha256']))
        owners=[associations[i] for i in indexes if value['blocks'][i]['heading_path']==image['heading_path']] or list(associations.values())
        pictures.append(ReferenceImage(id=identity,artifact_id=identity,source_ids=owners,source_url=image['url']))
    sources=Sources(schema_version='baseline-sources-v1',source_selection='unconfirmed',artifacts=artifacts,records=records,images=pictures)
    metadata=dict(method='official-parent-section-bm25-v1',query=query,goal=goal,archive_sha256=archive_sha,source_url=url,parent_heading=heading,
                  archive_path=str(archive_path),manifest_path=str(manifest_path),manifest_sha256=digest(manifest_path.read_bytes()),device_path=device_path,
                  assembly_context=assembly_context,intent_interpretation=interpretation,
                  extraction_sha256=xsha,source_revision=digest(encoded(sources.model_dump())),ranked=[dict(score=round(s,5),url=r['url'],heading=r['heading']) for s,r in ranked[:5]])
    return sources,root,metadata
