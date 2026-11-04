"""Standalone Blender exporter for manually edited teaching meshes.

Blender --background --python export_blend.py -- --input asset.blend --root asset.id --output mesh.json
The named root defines the functional origin and local axes. Bone/deformation clips are not supported in v1.
"""
import argparse
import json
from pathlib import Path
import sys
import bpy


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--input',type=Path,required=True);parser.add_argument('--root',required=True);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args(sys.argv[sys.argv.index('--')+1:])
    bpy.ops.wm.open_mainfile(filepath=str(args.input),use_scripts=False);bpy.context.scene.frame_set(1);bpy.context.view_layer.update()
    root=bpy.data.objects.get(args.root)
    if root is None:raise ValueError('Missing functional asset root')
    parts=[];depsgraph=bpy.context.evaluated_depsgraph_get();inverse=root.matrix_world.inverted()
    for obj in sorted([root,*root.children_recursive],key=lambda o:o.name):
        if obj.type!='MESH':continue
        if any(m.type=='ARMATURE' for m in obj.modifiers):raise ValueError('Bake a static teaching pose; skeleton clips need a future importer')
        evaluated=obj.evaluated_get(depsgraph);mesh=evaluated.to_mesh()
        try:
            mesh.calc_loop_triangles();transform=inverse@evaluated.matrix_world
            material=obj.data.materials[0] if obj.data.materials else None
            color=[round(float(v),6) for v in material.diffuse_color] if material else [.88,.94,.96,1]
            parts.append({'id':obj.name,'vertices':[round(float(v),8) for vertex in mesh.vertices for v in transform@vertex.co],'triangles':[int(i) for tri in mesh.loop_triangles for i in tri.vertices],'color':color})
        finally:evaluated.to_mesh_clear()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps({'schema_version':'manual2ar-asset-mesh-v1','asset_id':args.root,'parts':parts},ensure_ascii=False,separators=(',',':'),allow_nan=False)+'\n',encoding='utf-8')
    print('MANUAL2AR_EXPORTED',args.output)


if __name__=='__main__':main()
