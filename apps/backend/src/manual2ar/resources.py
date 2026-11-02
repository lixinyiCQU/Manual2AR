"""Resolve versioned teaching resources independently of Python code locations."""
import json
from pathlib import Path

class ResourceStore:
    def __init__(self, root):
        self.root = Path(root).resolve()
        catalog = json.loads((self.root / 'catalog.json').read_text(encoding='utf-8'))
        if catalog['schema_version'] != 'manual2ar-resources-v1':
            raise ValueError('Unsupported resource catalog')
        self.entries = catalog['resources']

    def inside(self, relative):
        path = (self.root / relative).resolve()
        path.relative_to(self.root)
        return path

    def path(self, identity):
        return self.inside(self.entries[identity])

    def json(self, identity):
        return json.loads(self.path(identity).read_text(encoding='utf-8'))

    @classmethod
    def configured(cls, config=None):
        if config and config.get('resources_dir'):
            return cls(config['resources_dir'])
        from manual2ar.paths import ROOT
        return cls(ROOT / 'resources')
