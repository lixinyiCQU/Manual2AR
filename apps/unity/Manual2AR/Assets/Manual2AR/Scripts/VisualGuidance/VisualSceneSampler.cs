using System;
using System.Collections.Generic;
using UnityEngine;

namespace Manual2AR.VisualGuidance {
 /// <summary>One deterministic animation evaluator shared by RGB and future native-AR rendering.</summary>
 public sealed class VisualSceneSampler {
  public sealed class PartPose {public string InstanceId,AssetId;public Vector3[] Vertices;public int[] Triangles;public Color Color;internal int Instance,Part;internal VisualAssetLibrary.Model Model;internal AssetClip Clip;}
  readonly List<PartPose> output=new List<PartPose>();string identity;
  public static float Phase(AssetTrack track,float phase){float x=Mathf.Clamp01((phase-track.start)/(track.end-track.start));return track.easing=="smoothstep"?x*x*(3-2*x):x;}
  public IList<PartPose> Sample(VisualPresentation presentation,float phase){
   if(!VisualAssetLibrary.Validate(presentation)){output.Clear();identity=null;return output;}
   string key=presentation.catalog_sha256+":"+presentation.presentation_id;
   if(key!=identity){
    output.Clear();identity=key;
    for(int i=0;i<presentation.instances.Length;i++){
     var instance=presentation.instances[i];var model=VisualAssetLibrary.Get(instance.asset_id,presentation.library_id);var clip=Array.Find(model.Definition.clips,c=>c.id==instance.clip_id);
     for(int part=0;part<model.Mesh.parts.Length;part++)output.Add(new PartPose{InstanceId=instance.id,AssetId=instance.asset_id,Instance=i,Part=part,Model=model,Clip=clip,Vertices=new Vector3[model.Vertices[part].Length],Triangles=model.Mesh.parts[part].triangles});
    }
   }
   foreach(var part in output){
    var instance=presentation.instances[part.Instance];var placement=VisualAssetLibrary.Matrix(instance.reference_from_asset);var source=part.Model.Vertices[part.Part];var mesh=part.Model.Mesh.parts[part.Part];Vector3 shift=Vector3.zero;float alpha=instance.visible?instance.opacity:0;Matrix4x4 local=Matrix4x4.identity;float time=Mathf.Max(0,phase)*instance.speed;float componentPhase=instance.playing?(time<=1?time:Mathf.Repeat(time,1)):0;
    foreach(var track in part.Clip.tracks??new AssetTrack[0]){
     if(track.target!="*"&&track.target!=mesh.id)continue;float t=Phase(track,componentPhase);
     if(track.kind=="rotate"){if(instance.reverse_with_rotation&&instance.rotation_sign<0){var axis=VisualAssetLibrary.Vector(track.axis).normalized;var perpendicular=Vector3.Cross(axis,Mathf.Abs(axis.x)<.9f?Vector3.right:Vector3.up).normalized;local=Matrix4x4.Rotate(Quaternion.AngleAxis(180,perpendicular))*local;}var pivot=VisualAssetLibrary.Vector(track.pivot_m);local=Matrix4x4.Translate(pivot)*Matrix4x4.Rotate(Quaternion.AngleAxis(track.degrees*t*instance.rotation_sign*instance.rotation_scale,VisualAssetLibrary.Vector(track.axis)))*Matrix4x4.Translate(-pivot)*local;}
     else if(track.kind=="path")shift=VisualAssetLibrary.Vector(instance.path_m)*t;
     else if(track.kind=="opacity")alpha*=Mathf.Lerp(track.from_value,track.to_value,t);
    }
    var combined=placement*local;
    for(int i=0;i<source.Length;i++)part.Vertices[i]=combined.MultiplyPoint3x4(source[i])+shift;
    part.Color=new Color(mesh.color[0],mesh.color[1],mesh.color[2],mesh.color[3]*alpha);
   }
   return output;
  }
 }
}
