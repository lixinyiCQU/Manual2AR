"""Run inside Blender: deterministic low-detail teaching meshes, editable sources and previews."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
import bpy
from mathutils import Vector


def mesh_object(name, vertices, faces):
    mesh=bpy.data.meshes.new(name);mesh.from_pydata(vertices,[],faces);mesh.update()
    obj=bpy.data.objects.new(name,mesh);bpy.context.collection.objects.link(obj);return obj


def primitive(p):
    shape=p['shape']
    if shape=='box':
        bpy.ops.mesh.primitive_cube_add(size=1,location=p['position']);obj=bpy.context.object
        obj.scale=p['size'];bpy.ops.object.transform_apply(location=False,rotation=False,scale=True)
        if p.get('bevel'):
            mod=obj.modifiers.new('Teaching soft edges','BEVEL');mod.width=p['bevel'];mod.segments=1;bpy.ops.object.modifier_apply(modifier=mod.name)
    elif shape=='rod':
        a,b=Vector(p['a']),Vector(p['b']);delta=b-a
        bpy.ops.mesh.primitive_cylinder_add(vertices=p.get('sides',12),radius=p['radius'],depth=delta.length,location=(a+b)*.5)
        obj=bpy.context.object;obj.rotation_mode='QUATERNION';obj.rotation_quaternion=Vector((0,0,1)).rotation_difference(delta.normalized())
    elif shape=='arc':
        vertices=[];faces=[];start,end=map(math.radians,[p['start_deg'],p['end_deg']]);steps=max(12,int(abs(end-start)*8))
        for i in range(steps+1):
            angle=start+(end-start)*i/steps
            for y,r in [(-p['depth']/2,p['radius']-p['width']/2),(-p['depth']/2,p['radius']+p['width']/2),(p['depth']/2,p['radius']-p['width']/2),(p['depth']/2,p['radius']+p['width']/2)]:vertices.append((math.cos(angle)*r,y,math.sin(angle)*r))
        for i in range(steps):
            a=i*4;b=a+4
            faces.extend([(a,b,b+1,a+1),(a+2,a+3,b+3,b+2),(a,a+2,b+2,b),(a+1,b+1,b+3,a+3)])
        if abs(p['end_deg']-p['start_deg'])<359.9:faces.extend([(0,1,3,2),(steps*4,steps*4+2,steps*4+3,steps*4+1)])
        obj=mesh_object(p['id'],vertices,faces)
    elif shape=='arrow_head':
        # Tangent to the positive-Y rotation; no ambiguous screen-clockwise rule.
        angle=math.radians(p['angle_deg']);tip=Vector(p['position']);tangent=Vector((math.sin(angle),0,-math.cos(angle)));side=Vector((math.cos(angle),0,math.sin(angle)))
        obj=mesh_object(p['id'],[tip+tangent*p['size'],tip-tangent*p['size']*.7+side*p['size']*.65,tip-tangent*p['size']*.7-side*p['size']*.65],[(0,1,2)])
    elif shape=='arrow':
        poly=[Vector((x,y,0)) for x,y in [(0,0),(-.012,-.018),(-.004,-.018),(-.004,-.055),(.004,-.055),(.004,-.018),(.012,-.018)]]
        count=len(poly);vertices=[(v.x,v.y,z) for z in [-.001,.001] for v in poly];faces=[]
        for ids in [(0,1,6),(2,3,4),(2,4,5)]:
            faces.extend([tuple(reversed(ids)),tuple(i+count for i in ids)])
        for i in range(count):j=(i+1)%count;faces.append((i,j,j+count,i+count))
        obj=mesh_object(p['id'],vertices,faces)
    else:raise ValueError('Unknown primitive '+shape)
    obj.name=p['id'];return obj


def dump(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,separators=(',',':'),allow_nan=False)+'\n',encoding='utf-8')


def main():
    args=argparse.ArgumentParser();args.add_argument('--recipe',required=True,type=Path);args.add_argument('--addon',type=Path);args.add_argument('--output',required=True,type=Path);args.add_argument('--preview',action='store_true');c=args.parse_args(sys.argv[sys.argv.index('--')+1:])
    recipe=json.loads(c.recipe.read_text(encoding='utf-8'))
    recipe_sources={asset['id']:c.recipe.name for asset in recipe['assets']}
    if c.addon:
        addon=json.loads(c.addon.read_text(encoding='utf-8'))
        recipe['assets'].extend(addon['assets'])
        recipe['presentations'].extend(addon['presentations'])
        recipe_sources.update({asset['id']:c.addon.name for asset in addon['assets']})
    out=c.output;out.mkdir(parents=True,exist_ok=True);(out/'meshes').mkdir(exist_ok=True)
    catalog={'schema_version':'manual2ar-visual-library-v1','library_id':'manual2ar.unboxing' if c.addon else 'manual2ar.teaching','version':'1.0.0' if c.addon else '1.2.0','style_id':'clear-instruction-v1','coordinate_convention':'right_handed_xyz_metres_functional_origin_positive_y','assets':[],'presentations':recipe['presentations']}
    for spec in recipe['assets']:
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.context.preferences.filepaths.save_version=0
        scene=bpy.context.scene;scene.unit_settings.system='METRIC';scene.unit_settings.scale_length=1
        parts=[];objects=[]
        for p in spec['parts']:
            obj=primitive(p);bpy.context.view_layer.update();objects.append(obj);color=recipe['palette'][p['color']]
            material=bpy.data.materials.new(p['color']);material.diffuse_color=color;material.use_nodes=True
            bsdf=material.node_tree.nodes.get('Principled BSDF');bsdf.inputs['Base Color'].default_value=color;bsdf.inputs['Roughness'].default_value=.65
            obj.data.materials.append(material);obj.data.calc_loop_triangles()
            vertices=[round(float(v),8) for vertex in obj.data.vertices for v in obj.matrix_world@vertex.co]
            triangles=[int(i) for tri in obj.data.loop_triangles for i in tri.vertices]
            parts.append({'id':p['id'],'vertices':vertices,'triangles':triangles,'color':color})
        filename=spec['id']+'.json';raw={'schema_version':'manual2ar-asset-mesh-v1','asset_id':spec['id'],'parts':parts};mesh_path=out/'meshes'/filename
        if c.addon and recipe_sources[spec['id']]==c.addon.name:
            mesh_path.write_bytes((json.dumps(raw,ensure_ascii=False,separators=(',',':'),allow_nan=False)+'\n').encode('utf-8'))
        else:
            dump(mesh_path,raw)
        asset={k:spec[k] for k in ['id','label','category','nominal_axis_m','anchors','clips']}
        asset.update(version='1.0.0',units='metres',geometry_accuracy='teaching_proxy',source_recipe='recipes/'+recipe_sources[spec['id']],license='project-authored',mesh={'path':'meshes/'+filename,'sha256':hashlib.sha256((out/'meshes'/filename).read_bytes()).hexdigest(),'triangles':sum(len(p['triangles'])//3 for p in parts),'vertices':sum(len(p['vertices'])//3 for p in parts)})
        catalog['assets'].append(asset)
        root=bpy.data.objects.new(spec['id'],None);scene.collection.objects.link(root);root['asset_id']=spec['id'];root['units']='metres';root['accuracy']='teaching_proxy'
        for obj in objects:obj.parent=root
        # Editable example clips; runtime clips in catalog remain the normative playback source.
        scene.render.fps=30;scene.frame_start=1;scene.frame_end=37
        if any(t['kind']=='rotate' for clip in spec['clips'] for t in clip['tracks']):
            root.rotation_euler=(0,0,0);root.keyframe_insert('rotation_euler',frame=1);root.rotation_euler=(0,math.tau,0);root.keyframe_insert('rotation_euler',frame=37)
        elif any(t['kind']=='path' for clip in spec['clips'] for t in clip['tracks']):
            root.location=(0,0,0);root.keyframe_insert('location',frame=1);root.location=(0,.05,0);root.keyframe_insert('location',frame=37)
        root.asset_mark();root.asset_data.description=spec['label']+' — metre-scaled illustrative teaching asset'
        scene.frame_set(1)
        bpy.ops.object.select_all(action='DESELECT');root.select_set(True)
        for obj in objects:obj.select_set(True)
        bpy.ops.export_scene.fbx(filepath=str(out/(spec['id']+'.fbx')),use_selection=True,object_types={'EMPTY','MESH'},add_leaf_bones=False,bake_anim=True,axis_forward='-Z',axis_up='Y')
        # Camera/light belong to the editable preview file, never the runtime mesh export.
        vertices=[obj.matrix_world@v.co for obj in objects for v in obj.data.vertices];centre=sum(vertices,Vector())/len(vertices);extent=max((v-centre).length for v in vertices)
        bpy.ops.object.camera_add(location=centre+Vector((1.4,.5,1.8))*extent*3);camera=bpy.context.object;camera.rotation_euler=(centre-camera.location).to_track_quat('-Z','Y').to_euler();camera.data.type='ORTHO';camera.data.ortho_scale=extent*2.7;scene.camera=camera
        for offset,energy,size in [((1,1,2),2,.3),((-1,-1,1),.7,.3)]:
            bpy.ops.object.light_add(type='AREA',location=centre+Vector(offset)*.25);light=bpy.context.object;light.data.energy=energy;light.data.shape='DISK';light.data.size=size;light.rotation_euler=(centre-light.location).to_track_quat('-Z','Y').to_euler()
        scene.world=bpy.data.worlds.new('Teaching background');scene.world.use_nodes=True;scene.world.node_tree.nodes['Background'].inputs[0].default_value=(.018,.035,.055,1);scene.world.node_tree.nodes['Background'].inputs[1].default_value=.4
        scene.render.engine='CYCLES';scene.cycles.device='CPU';scene.cycles.samples=12;scene.render.resolution_x=512;scene.render.resolution_y=384;scene.render.resolution_percentage=100
        scene.view_settings.view_transform='Standard';scene.render.image_settings.file_format='PNG';scene.render.filepath=str(out/(spec['id']+'.png'))
        bpy.ops.wm.save_as_mainfile(filepath=str(out/(spec['id']+'.blend')))
        if c.preview:bpy.ops.render.render(write_still=True)
    dump(out/'catalog.json',catalog)
    print('MANUAL2AR_LIBRARY_BUILT',len(catalog['assets']),'assets')


if __name__=='__main__':main()
