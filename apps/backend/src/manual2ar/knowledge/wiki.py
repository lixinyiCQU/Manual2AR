"""Verbatim component text and an offline article index. No LLM or embeddings.

Public reader objects contain only teaching content and local destinations.
Original hashes, paragraph identities and editorial selection remain in audit.
"""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import unquote, urlsplit
import hashlib
import html
import json
import subprocess
import tempfile
import threading

from manual2ar.knowledge.extract import Parser, canonical, extract, offline_html

PREFIX = '/api/learning/wiki'


def sha(body):
    return hashlib.sha256(body).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=path.parent,prefix=path.name+'.',suffix='.tmp',delete=False) as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2))
        temporary=Path(stream.name)
    temporary.replace(path)


class OfflineWiki:
    def __init__(self, settings):
        self.settings = settings
        self.archive_path = Path(settings['archive']).resolve()
        self.archive = read_json(self.archive_path)
        self.snapshot_sha256 = sha(self.archive_path.read_bytes())
        self.root = self.archive_path.parents[2]
        self.cache = Path(settings['cache_dir']).resolve()
        self.cache.mkdir(parents=True, exist_ok=True)
        self.pages = {}
        self.by_url = {}
        self.assets = {}
        self.extractions = {}
        self.checked = set()
        self.lock = threading.RLock()
        self.jobs = {}
        self.executor = None
        for url, page in self.archive['pages'].items():
            if page['status'] != 'archived':
                continue
            identity = sha(url.encode())[:20]
            self.pages[identity] = dict(page=page, url=url, id=identity,
                                       title=page['title'].split(' | Bambu Lab Wiki')[0])
            self.by_url[canonical(url, page=True)] = identity
        for url, asset in self.archive['assets'].items():
            obj = asset.get('body', asset.get('response', {}).get('body'))
            if asset['status'] == 'archived' and obj:
                self.assets[sha(url.encode())[:24]] = dict(url=url, object=obj, mime=asset.get('mime', 'application/octet-stream'))

    def object_path(self, obj):
        path = (self.root / obj['path']).resolve()
        path.relative_to(self.root.resolve())
        if path not in self.checked:
            if path.stat().st_size != obj['bytes'] or sha(path.read_bytes()) != obj['sha256']:
                raise ValueError('Offline source integrity mismatch')
            self.checked.add(path)
        return path

    def page(self, identity):
        if identity not in self.pages:
            raise KeyError('Page not present in offline snapshot')
        return self.pages[identity]

    def extraction(self, identity):
        if identity not in self.extractions:
            p = self.page(identity)['page']
            self.object_path(p['response']['body'])
            dom = self.object_path(p['response'].get('rendered_dom', p['response']['body']))
            artifact = (self.root / p['artifact_dir']).resolve()
            artifact.relative_to(self.root.resolve())
            extracted = read_json(artifact / 'extraction.json')
            fresh, _ = extract(dom.read_text(encoding='utf-8'), self.page(identity)['url'])
            if [(b['ordinal'], b['kind'], b['text']) for b in extracted['blocks']] != [(b['ordinal'], b['kind'], b['text']) for b in fresh['blocks']]:
                raise ValueError('Derived paragraphs differ from the captured original DOM')
            self.extractions[identity] = extracted
        return self.extractions[identity]

    def destination(self, url, anchor=''):
        identity = self.by_url[canonical(url, page=True)]
        p = self.page(identity)
        return dict(title=p['title'], page_id=identity, anchor=anchor,
                    url=PREFIX + '/pages/' + identity + '/html' + ('#' + anchor if anchor else ''))

    def paragraphs(self, url, ordinals):
        identity = self.by_url[canonical(url, page=True)]
        blocks = {b['ordinal']: b for b in self.extraction(identity)['blocks']}
        values = []
        audit = []
        for number in ordinals:
            block = blocks[number]
            if block['kind'] != 'p' or sha(block['text'].encode()) != block['text_sha256']:
                raise ValueError('Verbatim paragraph selection is invalid')
            values.append(block['text'])
            audit.append({**block, 'source_url':url})
        return values, audit

    def article_html(self, identity, for_render=False):
        record = self.page(identity)
        p = record['page']
        dom = self.object_path(p['response'].get('rendered_dom', p['response']['body']))
        _, content = extract(dom.read_text(encoding='utf-8'), record['url'])
        if content is None:
            raise ValueError('Archived article content missing')
        assets = {}
        needed = {canonical(a['url'], record['url']) for a in self.extraction(identity)['assets']}
        for key, asset in self.assets.items():
            if canonical(asset['url'], record['url']) not in needed:
                continue
            obj = asset['object']
            # Only local, already archived objects are rendered. Missing assets
            # remain explicitly marked by the original offline exporter.
            if for_render:
                value = self.object_path(obj).as_uri()
            else:
                value = PREFIX + '/assets/' + key
            assets[canonical(asset['url'], record['url'])] = value
        paths = {url: PREFIX + '/pages/' + key + '/html' for url, key in self.by_url.items()}
        source = offline_html(content, record['url'], assets, paths)
        # Reuse the original safe article DOM without its developer evidence
        # banner. No paragraph, heading, image order or table text is rewritten.
        marker = '离线阅读派生件；原始响应与渲染 DOM 请见本目录证据记录。</p>'
        body = source.split(marker, 1)[1]
        tree = Parser(body).root
        for node in tree.walk():
            if node.tag != 'a':
                continue
            href = node.attrs.get('href', '')
            if href and not href.startswith(('#', PREFIX+'/pages/', PREFIX+'/assets/')):
                node.attrs.update(href='#', **{'data-unavailable':'true', 'title':'当前离线快照未包含此链接'})
        body = tree.serialize()
        font=Path(self.settings['font_file'])
        font_url=font.as_uri() if for_render else PREFIX+'/font'
        style = ('@font-face{font-family:Manual2ARUI;src:url("'+font_url+'")}body{margin:0;padding:32px;background:#fff;color:#202124;'
                 'font:20px/1.8 Manual2ARUI,sans-serif;overflow-wrap:anywhere}'
                 'h1{font-size:30px}h2{font-size:27px}h3{font-size:24px}'
                 'img{max-width:100%;height:auto}table{border-collapse:collapse;max-width:100%}'
                 'td,th{border:1px solid #bbb;padding:8px}a{color:#086cb3}'
                 'blockquote{border-left:4px solid #e8b73d;padding:8px 20px;background:#fff8df}'
                 'pre{white-space:pre-wrap}iframe,video{display:none}')
        return ('<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
                '<meta name="viewport" content="width=device-width,initial-scale=1">'
                '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; '
                'img-src \'self\' data: file:; font-src \'self\' file:; style-src \'unsafe-inline\'; base-uri \'none\'; form-action \'none\'">'
                '<title>' + html.escape(record['title']) + '</title><style>' + style + '</style>'
                '<body><h1>' + html.escape(record['title']) + '</h1>' + body + '</body></html>')

    def render_folder(self, identity):
        p = self.page(identity)['page']['response']
        signature = sha(json.dumps(dict(snapshot=self.snapshot_sha256,dom=p.get('rendered_dom', p['body'])['sha256'],
                                       settings=self.settings['render'],
                                       renderer=sha((Path(__file__).with_name('render.py')).read_bytes()),
                                       adapter=sha(Path(__file__).read_bytes())), sort_keys=True).encode())[:24]
        return self.cache / identity / signature

    def render(self, identity):
        folder = self.render_folder(identity)
        manifest = folder / 'page.json'
        with self.lock:
            if manifest.is_file():
                return dict(state='ready', **read_json(manifest))
            key = str(folder)
            job = self.jobs.get(key)
            if job is None:
                if self.executor is None:
                    self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='offline-wiki')
                self.jobs[key] = dict(state='queued', title=self.page(identity)['title'])
                self.executor.submit(self._render, identity, folder)
            return dict(self.jobs[key])

    def _render(self, identity, folder):
        key = str(folder)
        self.jobs[key] = dict(state='rendering', title=self.page(identity)['title'])
        try:
            folder.mkdir(parents=True, exist_ok=True)
            source = folder / 'article.html'
            source.write_text(self.article_html(identity, for_render=True), encoding='utf-8')
            write_json(folder / 'job.json', dict(page_id=identity, title=self.page(identity)['title'],
                       source=str(source), output=str(folder), settings=self.settings['render'],
                       pages={k:dict(title=v['title']) for k,v in self.pages.items()},
                       allowed_asset_root=str(self.root / 'objects'),
                       allowed_font=str(Path(self.settings['font_file']))))
            python = Path(self.settings['renderer_python'])
            if not python.is_file():
                raise RuntimeError('Offline renderer is not installed; run bash run.sh setup')
            result = subprocess.run([str(python), str(Path(__file__).with_name('render.py')), str(folder/'job.json')],
                                    capture_output=True, text=True, timeout=180)
            (folder/'renderer.log').write_text(result.stdout + result.stderr, encoding='utf-8')
            if result.returncode or not (folder/'page.json').is_file():
                raise RuntimeError('Offline article renderer failed; inspect backend renderer.log')
            self.jobs[key] = dict(state='ready')
        except Exception as error:
            self.jobs[key] = dict(state='failed', title=self.page(identity)['title'], message=str(error)[:250])

    def close(self):
        if self.executor is not None:
            self.executor.shutdown(wait=True, cancel_futures=True)
            self.executor = None
            self.jobs.clear()
