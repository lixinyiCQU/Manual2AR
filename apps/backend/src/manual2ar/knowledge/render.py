"""Isolated Chromium worker: offline article pixels + local link hit areas."""
from pathlib import Path
from urllib.parse import unquote, urlsplit
import json
import base64
import math
import re
import sys


def render(job):
    from playwright.sync_api import sync_playwright
    source = Path(job['source']).resolve()
    output = Path(job['output']).resolve()
    asset_root = Path(job['allowed_asset_root']).resolve()
    font=Path(job['allowed_font']).resolve() if job.get('allowed_font') else None
    width = job['settings']['width']
    tile_height = job['settings']['tile_height']
    blocked = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, args=['--no-sandbox', '--allow-file-access-from-files'])
        page = browser.new_page(viewport=dict(width=width, height=900), device_scale_factor=1)
        def guard(route):
            url = urlsplit(route.request.url)
            if url.scheme == 'data':
                route.continue_(); return
            if url.scheme == 'file':
                path = Path(unquote(url.path)).resolve()
                if path == source or path == font or path.is_relative_to(asset_root):
                    route.continue_(); return
            blocked.append(route.request.url)
            route.abort()
        page.route('**/*', guard)
        page.goto(source.as_uri(), wait_until='load', timeout=60000)
        page.wait_for_function('Array.from(document.images).every(i => i.complete)', timeout=60000)
        page.evaluate('document.fonts.ready')
        missing = page.evaluate('Array.from(document.images).filter(i=>!i.naturalWidth).map(i=>i.getAttribute("src"))')
        if missing:
            raise ValueError('Archived images failed to render: '+str(len(missing)))
        height = math.ceil(page.evaluate('document.documentElement.scrollHeight'))
        if height > 150000:
            raise ValueError('Article exceeds renderer height budget; open offline HTML instead')
        anchors = page.evaluate('''() => Array.from(document.querySelectorAll('[id]')).map(e=>({
            id:e.id,y:e.getBoundingClientRect().top+scrollY,title:e.textContent.trim().replace(/^¶\\s*/,''),
            is_heading:/^H[1-4]$/.test(e.tagName)}))''')
        raw_links = page.evaluate('''() => Array.from(document.querySelectorAll('a[href]')).flatMap(a=>
            Array.from(a.getClientRects()).map(r=>({href:a.getAttribute('href'),title:a.textContent.trim(),
            unavailable:a.dataset.unavailable==='true',x:r.x,y:r.y+scrollY,width:r.width,height:r.height})))''')
        links = []
        for item in raw_links:
            match = re.match(r'^/api/learning/wiki/pages/([a-f0-9]+)/html(?:#(.*))?$', item['href'])
            target = match[1] if match else job['page_id']
            anchor = unquote(match[2] or '') if match else unquote(item['href'][1:])
            available = not item['unavailable'] and (match is not None or item['href'].startswith('#')) and target in job['pages']
            links.append({k:item[k] for k in ['x','y','width','height','title']} |
                         dict(page_id=target if available else '', anchor=anchor))
        tiles = []
        cdp = page.context.new_cdp_session(page)
        for number, y in enumerate(range(0, height, tile_height)):
            h = min(tile_height, height-y)
            name = f'{number:04d}.jpg'
            screenshot = cdp.send('Page.captureScreenshot', dict(format='jpeg', quality=92,
                                  captureBeyondViewport=True, fromSurface=True,
                                  clip=dict(x=0, y=y, width=width, height=h, scale=1)))
            (output/name).write_bytes(base64.b64decode(screenshot['data']))
            tiles.append(dict(index=number, y=y, height=h, url=f"/api/learning/wiki/pages/{job['page_id']}/tiles/{number}"))
        browser.close()
    value = dict(page_id=job['page_id'], title=job['title'], width=width, height=height,
                 tile_height=tile_height, tiles=tiles, anchors=anchors, links=links)
    temporary = output/'page.tmp'
    temporary.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False), encoding='utf-8')
    temporary.replace(output/'page.json')
    (output/'audit.json').write_text(json.dumps(dict(blocked_requests=blocked,missing_images=missing), ensure_ascii=False))


if __name__ == '__main__':
    render(json.loads(Path(sys.argv[1]).read_text(encoding='utf-8')))
