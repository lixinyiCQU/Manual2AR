"""Validated asset registry and declarative scene composition; no Blender/runtime SDK dependency."""
import hashlib
import json
import numpy as np
from manual2ar_contracts.visual_assets import AssetCatalog, AssetMesh, VisualPresentation


class VisualAssetLibrary:
    def __init__(self, catalog_path):
        self.path=catalog_path
        self.sha256=hashlib.sha256(catalog_path.read_bytes()).hexdigest()
        self.catalog=AssetCatalog.model_validate_json(catalog_path.read_bytes())
        self.assets={a.id:a for a in self.catalog.assets}
        self.presentations={p.id:p for p in self.catalog.presentations}
        for asset in self.catalog.assets:
            path=(catalog_path.parent/asset.mesh.path).resolve();path.relative_to(catalog_path.parent.resolve())
            raw=path.read_bytes()
            if hashlib.sha256(raw).hexdigest()!=asset.mesh.sha256:raise ValueError('Visual mesh hash mismatch: '+asset.id)
            mesh=AssetMesh.model_validate_json(raw)
            if mesh.asset_id!=asset.id or len({p.id for p in mesh.parts})!=len(mesh.parts):raise ValueError('Visual mesh identity mismatch')
            if sum(len(p.triangles)//3 for p in mesh.parts)!=asset.mesh.triangles or sum(len(p.vertices)//3 for p in mesh.parts)!=asset.mesh.vertices:raise ValueError('Visual mesh budget mismatch')
            for clip in asset.clips:
                if any(t.target!='*' and t.target not in {p.id for p in mesh.parts} for t in clip.tracks):raise ValueError('Unknown animation part')

    def descriptor(self):
        return {'library_id':self.catalog.library_id,'version':self.catalog.version,'catalog_sha256':self.sha256}

    def compose(self, identity, points, basis, printer_basis=None):
        spec=self.presentations[identity];start,end=np.asarray(points);delta=end-start;length=np.linalg.norm(delta);instances=[]
        for layer in spec.layers:
            definition=self.assets[layer.asset_id]
            extent=np.clip(length*layer.extent_ratio,layer.minimum_extent_m,layer.maximum_extent_m)
            placement=np.eye(4);placement[:3,:3]=basis*(extent/definition.nominal_axis_m);placement[:3,3]=start if layer.anchor=='start' else end
            from manual2ar_perception.spatial import rotation
            placement[:3,:3]=(printer_basis@rotation(layer.printer_rotation_degrees) if printer_basis is not None and layer.printer_rotation_degrees is not None else basis@rotation(layer.rotation_degrees))*(extent/definition.nominal_axis_m)
            path=delta.tolist() if any(t.kind=='path' for c in definition.clips if c.id==layer.clip_id for t in c.tracks) else [0.,0.,0.]
            instances.append({'id':layer.id,'asset_id':definition.id,'asset_version':definition.version,'mesh_sha256':definition.mesh.sha256,'clip_id':layer.clip_id,'reference_from_asset':placement.ravel().tolist(),'path_m':path,'opacity':layer.opacity,'reverse_with_rotation':layer.reverse_with_rotation})
        return VisualPresentation(**{'library_id':self.catalog.library_id,'library_version':self.catalog.version,'catalog_sha256':self.sha256,'presentation_id':spec.id,'duration_seconds':spec.duration_seconds,'instances':instances}).model_dump()
