"""Select immutable archived sections; never crawl a website or invent source IDs."""
import hashlib
import json
from pathlib import Path
from manual2ar.knowledge.wiki import canonical


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def select(wiki, urls, sections=(), max_images=8):
    if not 0 <= max_images <= 16:
        raise ValueError('max_images must be between 0 and 16')
    evidence, images, pages, matched = {}, {}, [], set()
    for url in dict.fromkeys(urls):
        identity = wiki.by_url.get(canonical(url, page=True))
        if identity is None:
            raise ValueError('Page is not in the archived Wiki: '+url)
        record = wiki.page(identity)
        extracted = wiki.extraction(identity)
        response = record['page']['response']
        dom = response.get('rendered_dom', response['body'])
        selected = []
        for block in extracted['blocks']:
            hits = [s for s in sections if s in block['heading_path']]
            matched.update(hits)
            if sections and not hits:
                continue
            text = block['text']
            if hashlib.sha256(text.encode()).hexdigest() != block['text_sha256']:
                raise ValueError('Archived text hash mismatch')
            citation = block.get('citation_id') or fingerprint([record['url'], dom['sha256'], block['ordinal']])[:24]
            item = {k:block[k] for k in ('ordinal', 'kind', 'text', 'text_sha256', 'heading_path', 'dom_path', 'html_line')}
            item.update(citation_id=citation, source_url=record['url'], body_sha256=response['body']['sha256'],
                        dom_sha256=dom['sha256'], snapshot_id=wiki.archive_path.parent.name,
                        captured_at=record['page'].get('completed_at'))
            if citation in evidence and evidence[citation] != item:
                raise ValueError('Citation identity collision')
            evidence[citation] = item
            selected.append(citation)
        pages.append(dict(url=record['url'], title=record['title'], citation_ids=selected))
        for asset in extracted['assets']:
            if asset['kind'] != 'image' or (sections and not any(s in asset['heading_path'] for s in sections)):
                continue
            found = next((a for a in wiki.assets.values() if canonical(a['url']) == canonical(asset['url'])), None)
            if found is None:
                continue
            obj = found['object']
            path = wiki.object_path(obj)
            key = obj['sha256']
            if key not in images:
                images[key] = dict(id=key, path=str(path), sha256=key, source_page=record['url'],
                                   heading_path=asset['heading_path'], alt=asset.get('alt', ''), source_url=asset['url'])
    if set(sections)-matched:
        raise ValueError('Unknown exact section heading: '+', '.join(sorted(set(sections)-matched)))
    if not evidence:
        raise ValueError('No official evidence selected')
    if sum(len(e['text']) for e in evidence.values()) > 60000:
        raise ValueError('Source exceeds 60000 characters; select a smaller task/section')
    selected_images = list(images.values())[:max_images]
    bundle = dict(schema_version='manual2ar-compiler-source-v1', archive_sha256=wiki.snapshot_sha256,
                  pages=pages, evidence=evidence, images=selected_images, omitted_images=max(0,len(images)-len(selected_images)))
    logical = {**bundle, 'images':[{k:v for k,v in item.items() if k!='path'} for item in selected_images]}
    bundle['revision'] = fingerprint(logical)
    return bundle


def model_source(bundle):
    return {k:bundle[k] for k in ('pages','evidence','omitted_images')} | {
        'images':[dict(image_index=i+1, **{k:v for k,v in image.items() if k!='path'})
                  for i,image in enumerate(bundle['images'])]}
