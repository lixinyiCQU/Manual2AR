"""Stage-correlated, bounded image capture with human-readable reports."""
from datetime import datetime, timezone
from pathlib import Path
import base64, hashlib, html, json, threading, uuid
from importlib.metadata import version
import cv2
import numpy as np

def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding='utf-8')

def metadata(tracked):
    return tracked.model_dump(exclude={'overlay_png_base64', 'polygon_0_1000'})

class RunLog:
    def __init__(self, root: Path, config: dict, source_files):
        self.id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ_') + uuid.uuid4().hex[:12]
        self.path = root / self.id
        self.path.mkdir(parents=True)
        self.lock = threading.RLock()
        self.frames = 0
        self.settings = config['logging']
        dump(self.path / 'manifest.json', {'run_id': self.id, 'public_config': config['public'],
             'source_sha256': {str(p.name): hashlib.sha256(p.read_bytes()).hexdigest() for p in source_files},
             'runtime_versions': {name:version(name) for name in ('fastapi','pydantic','numpy','opencv-python-headless','pillow')},
             'scope': 'one visible instance per type; image-space prototype; no safety approval'})
        dump(self.path / 'human_review.json', {'reviewed': False, 'notes': '', 'component_labels': {}})
        self.event('run.start', {})

    def event(self, name, data):
        row = {'utc': datetime.now(timezone.utc).isoformat(), 'event': name, **data}
        with self.lock:
            with (self.path / 'events.jsonl').open('a', encoding='utf-8') as f:
                f.write(json.dumps(row, ensure_ascii=False, default=str) + '\n')
        if name not in ('tracking.component', 'frontend.render'):
            print('[Components] ' + json.dumps(row, ensure_ascii=False, default=str), flush=True)

    def sample(self, image):
        with self.lock:
            if self.frames >= self.settings['max_sample_frames']: return None
            self.frames += 1
            folder = self.path / 'tracking' / f'{self.frames:05d}'
            folder.mkdir(parents=True)
            (folder / 'input.jpg').write_bytes(image)
            return folder

    def report(self):
        # Filenames are generated locally; no user/model HTML is inserted unescaped.
        links = []
        for p in sorted(self.path.glob('locate_*/summary.json')):
            value = json.loads(p.read_text())
            folder = p.parent.name
            links.append(f'<h2>{html.escape(folder)}</h2><a href="{folder}/boxes.jpg">VLM boxes</a> · '
                f'<a href="{folder}/overlay.jpg">accepted masks</a> · <a href="{folder}/vlm_raw.json">VLM JSON</a>'
                f'<br><img style="max-width:46%" src="{folder}/boxes.jpg"><img style="max-width:46%" src="{folder}/overlay.jpg">'
                f'<pre>{html.escape(json.dumps(value,ensure_ascii=False,indent=2))}</pre>')
        (self.path / 'report.html').write_text('<!doctype html><meta charset="utf-8"><title>Component diagnostics</title>'
            '<h1>多部件阶段诊断</h1><p>模型输出与几何门限不等于真实标注。请填写 human_review.json。'
            '前端显示回执见 events.jsonl，跟踪样本见 tracking/。</p>'
            '<p><a href="frontend_latest.jpg">前端最近保存截图（如已保存）</a></p>' + ''.join(links), encoding='utf-8')

def draw_boxes(image, candidates):
    canvas = cv2.imdecode(np.frombuffer(image, np.uint8), cv2.IMREAD_COLOR)
    h,w = canvas.shape[:2]
    for c in candidates:
        if not c.found: continue
        x1,y1,x2,y2 = [round(v * (w if i%2==0 else h)/1000) for i,v in enumerate(c.bbox_0_1000)]
        cv2.rectangle(canvas,(x1,y1),(x2,y2),(0,200,255),2)
        p = c.target_point_0_1000
        cv2.circle(canvas,(round(p[0]*w/1000),round(p[1]*h/1000)),4,(0,0,255),-1)
        cv2.putText(canvas,c.component_id,(x1,max(15,y1)),cv2.FONT_HERSHEY_SIMPLEX,.5,(0,0,200),1)
    return canvas

def save_masks(folder, image, rows):
    canvas = cv2.imdecode(np.frombuffer(image,np.uint8),cv2.IMREAD_COLOR)
    palette = [(255,200,0),(0,220,255),(220,80,200),(80,220,80),(0,100,255),(200,120,0),(180,180,40),(120,80,255)]
    for index,row in enumerate(rows):
        t = row.get('tracked')
        if not t or not t.overlay_png_base64: continue
        png = base64.b64decode(t.overlay_png_base64)
        (folder / (row['component_id'] + '_mask.png')).write_bytes(png)
        if not row.get('tracking_ready'): continue
        mask = cv2.imdecode(np.frombuffer(png,np.uint8),cv2.IMREAD_UNCHANGED)
        if mask is None or mask.shape[:2] != canvas.shape[:2]: continue
        active = mask[:,:,3]>0 if mask.ndim==3 and mask.shape[2]==4 else (mask.max(axis=2)>0 if mask.ndim==3 else mask>0)
        canvas[active] = (canvas[active]*.55 + np.array(palette[index%8])*.45).astype(np.uint8)
    cv2.imwrite(str(folder / 'overlay.jpg'),canvas)
