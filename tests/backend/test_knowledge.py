"""Optional installed-dataset integration: no web, no VLM, no GPU."""
import hashlib
import json
import pytest
from manual2ar.application import ROOT
from manual2ar.application.config import for_module, resolve
from manual2ar.modules.learning.knowledge import KnowledgeStore


def test_installed_official_snapshot_still_matches_eight_component_cards(tmp_path):
    c=json.loads((ROOT/'configs/app.example.json').read_text())
    archive=resolve(c['paths']['wiki_archive'])
    if not archive.is_file():pytest.skip('Install the versioned official Wiki resource pack to run this integration check')
    manifest=json.loads((ROOT/'resources/sources/bambu_wiki/manifest.json').read_text())
    assert hashlib.sha256(archive.read_bytes()).hexdigest()==manifest['archive_sha256']
    c['paths']['runtime']=str(tmp_path)
    c['paths']['cache']=str(tmp_path/'cache')
    store=KnowledgeStore(for_module(c,'learning'))
    try:
        assert len(store.bundle['cards'])==8
        audit=json.loads((store.wiki.cache/'knowledge.audit.json').read_text())
        for card in store.bundle['cards']:
            evidence=audit['components'][card['id']]
            assert card['description']==[e['display_text'] for e in evidence]
            assert all(e['display_text'] in e['text'] for e in evidence)
            for photo in card['images']:
                assert store.image_bytes(photo['id']).startswith(b'\x89PNG')
        for unwanted in ('source_archive','snapshot_sha256','review_notes','api_key'):
            assert unwanted not in json.dumps(store.bundle)
    finally:store.wiki.close()


def test_installed_wiki_article_renders_with_packaged_chinese_font(tmp_path):
    import time
    c=json.loads((ROOT/'configs/app.example.json').read_text())
    if not resolve(c['paths']['wiki_archive']).is_file():pytest.skip('Official Wiki resource pack not installed')
    c['paths']['runtime']=str(tmp_path)
    c['paths']['cache']=str(tmp_path/'cache')
    store=KnowledgeStore(for_module(c,'learning'))
    try:
        identity=store.bundle['device_more_information'][0]['page_id']
        html=store.wiki.article_html(identity)
        assert '/api/learning/wiki/font' in html and 'font-family:Manual2ARUI' in html
        result=store.wiki.render(identity);until=time.monotonic()+90
        while result['state'] in ('queued','rendering') and time.monotonic()<until:
            time.sleep(.1);result=store.wiki.render(identity)
        assert result['state']=='ready',result
        assert result['tiles'] and (store.wiki.render_folder(identity)/'0000.jpg').is_file()
    finally:store.wiki.close()
