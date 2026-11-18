"""Every authored unboxing action must resolve to its source, variant, mesh and animated clip."""
import json
from pathlib import Path

import numpy as np

from manual2ar.visuals.library import VisualAssetLibrary
from manual2ar_contracts.visual_assets import VisualPresentation


ROOT = Path(__file__).resolve().parents[3]
TASK = ROOT / 'resources/tasks/bambu_a1_mini/unboxing'
VISUALS = ROOT / 'resources/visuals/v1'


def load(path):
    return json.loads(path.read_bytes())


def test_source_bindings_cover_both_official_variants():
    catalog = load(TASK / 'ar/v1/catalog.json')
    evidence = load(TASK / 'v2/evidence.json')
    actions = {a['action_id']: a for a in catalog['actions']}
    assert len(actions) == len(catalog['actions'])
    bound = set()
    for filename in ['procedure.json', 'variants/ams_lite.procedure.json']:
        procedure = load(TASK / 'v2' / filename)
        params = procedure['task']['parameters']
        chapters = catalog['variants'][params['variant_id']]
        assert list(chapters) == [s['state_id'] for s in procedure['states']]
        for chapter, entry in chapters.items():
            card = params['presentation'][chapter]
            assert entry['actions'] or entry['reason']
            assert len(entry['actions']) == len(set(entry['actions']))
            for identity in entry['actions']:
                bound.add(identity)
                action = actions[identity]
                assert action['citation_ids'] and set(action['citation_ids']) <= evidence['evidence'].keys()
                assert action['visual_check'] or action['manual_checks']
                assert action['target'] and action['instruction']
                substeps = {sub['id']: sub for sub in card['substeps']}
                scope = substeps[action['substep_id']] if action['substep_id'] else card
                ref = action['reference_image']
                if ref:
                    assert ref in scope['reference_images'] and ref in evidence['images']
                    assert (TASK / 'v2' / ref).is_file()
                assert np.isclose(np.linalg.norm(action['illustration_direction']), 1.)
    assert bound == actions.keys()
    for variant in catalog['variants']:
        assert catalog['variants'][variant]['U3']['actions'] == []
    assert 'ams.tube1' in catalog['variants']['ams_lite_unboxing']['U9']['actions']
    assert 'ams.tube1' not in catalog['variants']['standalone_unboxing']['U9']['actions']


def test_every_action_produces_valid_presentation_with_playable_motion():
    catalog = load(TASK / 'ar/v1/catalog.json')
    library = VisualAssetLibrary(VISUALS / 'unboxing.catalog.json')
    assert library.catalog.library_id == 'manual2ar.unboxing'
    expected = {action['presentation_id'] for action in catalog['actions']}
    assert expected == library.presentations.keys()
    for action in catalog['actions']:
        spec = library.presentations[action['presentation_id']]
        assert set(spec.citation_ids) == set(action['citation_ids'])
        assert any(
            clip.tracks for layer in spec.layers for clip in library.assets[layer.asset_id].clips
            if clip.id == layer.clip_id
        )
        dx, dy = action['illustration_direction']
        basis = np.array([[dy, dx, 0.], [-dx, dy, 0.], [0., 0., 1.]])
        end = np.array([.03, .02, 0.])
        start = end - .07 * basis[:, 1]
        result = VisualPresentation.model_validate(library.compose(spec.id, [start, end], basis))
        assert result.illustrative_only and result.catalog_sha256 == library.sha256
        for instance in result.instances:
            if np.linalg.norm(instance.path_m):
                assert np.allclose(instance.path_m, end - start)


def test_extended_library_reuses_the_reviewed_u7_geometry_and_presentations():
    original = VisualAssetLibrary(VISUALS / 'catalog.json')
    extended = VisualAssetLibrary(VISUALS / 'unboxing.catalog.json')
    assert original.sha256 == load(ROOT / 'baseline/ground_truth/u7/v1/ar-bindings.json')['resources']['resources/visuals/v1/catalog.json']
    assert original.catalog.library_id != extended.catalog.library_id
    assert all(extended.assets[key] == model for key, model in original.assets.items())
    assert all(extended.presentations[key] == scene for key, scene in original.presentations.items())
