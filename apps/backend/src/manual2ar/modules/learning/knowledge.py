"""V3: eight verbatim introductions; further reading points to offline Wiki."""
import hashlib
import io
import json
from PIL import Image
from manual2ar.resources import ResourceStore
from manual2ar.knowledge.wiki import OfflineWiki, canonical, read_json, write_json


class KnowledgeStore:
    def __init__(self, config):
        self.wiki = OfflineWiki(config['knowledge']['offline_wiki'])
        selection = ResourceStore.configured(config).json('device.knowledge')
        self.images = {}
        self.png_cache = {}
        self.cards = {}
        self.sources = {}
        audit = dict(snapshot_sha256=hashlib.sha256(self.wiki.archive_path.read_bytes()).hexdigest(),
                     selection=selection, components={}, source_archive=str(self.wiki.archive_path))
        intro = selection['intro_url']
        device_text, refs = self.wiki.paragraphs(intro, selection['device_ordinals'])
        audit['device'] = refs
        for item in selection['cards']:
            url = item.get('url', intro)
            description, evidence = self.wiki.paragraphs(url, item['ordinals'])
            if item.get('verbatim_quote'):
                quote=item['verbatim_quote']
                if len(description)!=1 or quote not in description[0]:raise ValueError('Function excerpt is not a continuous original quote')
                description=[quote]
            for text, original in zip(description,evidence):original['display_text']=text
            page_id = self.wiki.by_url[canonical(url, page=True)]
            more = [dict(category='部件介绍', **self.wiki.destination(url, item['anchor']))]
            for identity, p in self.wiki.pages.items():
                title = p['title'].replace(' ', '')
                if identity != page_id and any(word.replace(' ', '') in title for word in item['topics']):
                    category = '常见问题' if '/troubleshooting/' in p['url'] else '使用与维护'
                    more.append(dict(category=category, **self.wiki.destination(p['url'])))
            pictures = []
            for reference in item['reference_images']:
                asset = next((a for a in self.wiki.assets.values() if a['object']['sha256']==reference['sha256']),None)
                if asset is None:raise ValueError('V1 reference image is missing from the offline snapshot')
                path = self.wiki.object_path(asset['object'])
                identity = asset['object']['sha256']
                self.images[identity] = path
                pictures.append(dict(id=identity, local_file='LearningImages/'+identity+'.png',
                                     url='/api/learning/knowledge/images/'+identity, caption='官方参考图'))
            self.cards[item['id']] = dict(id=item['id'], target_id=item['id'], name=item['name'], english=item['english'],
                                         description=description, images=pictures, more_information=more)
            audit['components'][item['id']] = evidence
            for e in evidence + refs:
                self.sources[e['citation_id']] = e
        public = dict(schema_version='learning-knowledge-v3', title='A1 mini 部件认知', device_name='Bambu Lab A1 mini',
                      device_description=device_text, device_more_information=[self.wiki.destination(intro)],
                      cards=list(self.cards.values()))
        self.revision = hashlib.sha256(json.dumps(public, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        self.bundle = dict(revision=self.revision, **public)
        audit['knowledge_revision'] = self.revision
        audit['reference_images'] = {item['id']:item['reference_images'] for item in selection['cards']}
        write_json(self.wiki.cache/'knowledge.audit.json', audit)

    def evidence(self, citation):
        return self.sources[citation]

    def image_bytes(self, identity):
        if identity not in self.png_cache:
            with Image.open(self.images[identity]) as picture:
                picture.seek(0)
                image = picture.convert('RGB')
                image.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
                out = io.BytesIO()
                image.save(out, format='PNG')
                self.png_cache[identity] = out.getvalue()
        return self.png_cache[identity]
