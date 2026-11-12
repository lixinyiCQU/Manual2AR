"""Copy two named historical photos into the isolated demo; labels are scripts, not GT."""
from pathlib import Path
import json
from PIL import Image
from manual2ar.application.config import load, for_module
from manual2ar.paths import ROOT
from manual2ar_baseline.gt import digest, encoded, load_bundle


def prepare(target, pictures):
    target = Path(target);target.mkdir(parents=True, exist_ok=True)
    _, task = load_bundle(ROOT/'baseline/ground_truth/u7/v1/state-validation')
    scenes = []
    for identity, title, path in pictures:
        path = Path(path);raw = path.read_bytes()
        with Image.open(path) as image:width,height = image.size
        readings = {}
        for condition in task.conditions:
            if condition.channel != 'vision':continue
            base = condition.id.startswith('c.base.')
            if identity == 'holder_ready' and base:
                value, reason = 'unknown', 'occluded'
            else:
                value, reason = ('true' if base or condition.id != 'c.holder.connection' else 'false'), 'observed'
                if identity == 'holder_ready':value = 'true'
            readings[condition.id] = dict(value=value, reason=reason)
        filename = identity+'.jpg';(target/filename).write_bytes(raw)
        scenes.append(dict(id=identity,title=title,file=filename,sha256=digest(raw),width=width,height=height,
            historical_source=str(path), readings=readings,
            explanation='演示脚本提供的预设观察，不是模型回复，也不是独立人工标注。'))
    (target/'manifest.json').write_text(json.dumps(dict(purpose='curated_demo_not_evaluation',
        task_source='approved_u7_gt', task_sha256=digest(encoded(task.model_dump())), scenes=scenes),ensure_ascii=False,indent=2)+'\n')
    return target


def main():
    config = for_module(load(), 'guidance')
    runtime = Path(config['runtime_dir'])
    source = runtime/'baseline-ar/compiled-27d794c731445f059bb08dc351b99bea/runs'
    pictures = [
        ('base_ready','底座已装，支架待滑入',source/'e6528303b12e4297adc05a0d32927244/check-748ffa351d224ea59a75b7b68e8f07fe/input.jpg'),
        ('holder_ready','支架已装，底座固定处被遮挡',source/'f21d045922c44703bcce49e05315a7b8/check-c1be622740574269bcf460c0c85c5795/input.jpg')]
    print(prepare(runtime/'u7-demo/assets-v1',pictures))


if __name__ == '__main__':main()
