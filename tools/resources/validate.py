"""Validate configured resource paths and all compiled tutorial references."""
import hashlib
from manual2ar.application.config import load,for_module,resolve
from manual2ar.modules.guidance.registry import TaskRegistry
from manual2ar.resources import ResourceStore

def main():
    config=load();store=ResourceStore.configured(for_module(config,'learning'))
    for identity in store.entries:
        if not store.path(identity).is_file():raise ValueError('Missing resource: '+identity)
    tasks=TaskRegistry(for_module(config,'guidance'))
    from manual2ar.visuals.library import VisualAssetLibrary
    library=VisualAssetLibrary(store.path('visual.guidance.catalog'))
    for action in store.json('task.unboxing.spatial')['actions']:
        if 'machine_motion' in action:
            from manual2ar_contracts.machine_frame import MotionParameters
            MotionParameters.model_validate(action['machine_motion'])
        identity=action.get('visual_guidance',{}).get('presentation_id')
        if identity and identity not in library.presentations:raise ValueError('Unknown visual presentation')
    archive=resolve(config['paths']['wiki_archive'])
    manifest=store.json('source.bambu_wiki.manifest')
    if archive.is_file():
        if hashlib.sha256(archive.read_bytes()).hexdigest()!=manifest['archive_sha256']:raise ValueError('Wiki snapshot SHA256 mismatch')
        status='Wiki snapshot matches recorded SHA256'
    else:status='Wiki snapshot not installed; learning will be unavailable'
    print(f'{len(store.entries)} resources, {len(tasks.packages)} task variants verified; {status}')

if __name__=='__main__':main()
