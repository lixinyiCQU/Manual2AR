using System;
using System.Collections.Generic;
using UnityEngine;

namespace Manual2AR.Spatial {
 /// <summary>Normalized illustration meshes. Tip at origin, shaft toward -Y.
 /// Tools are independently authored; the optional arrow is a local reference asset.
 /// No camera, task state, network, or installation-check dependencies.</summary>
 public static class SpatialAssetGeometry {
  public sealed class Part {
   public Vector3[] vertices;public int[] triangles;public Color color;
   public int movingLeaf; // Scissor leaves rotate about their own pivot, never the scene.
  }
  public sealed class Model {public Part[] parts;public string provenance;}
  static readonly Dictionary<string,Model> cache=new Dictionary<string,Model>();
  static readonly Color Metal=new Color(.92f,.94f,.98f,.96f),Gold=new Color(1,.73f,.22f,.96f);
  static readonly Color Handle=new Color(.12f,.72f,.83f,.98f);
  public static Model Get(string identity){
   if(cache.TryGetValue(identity,out var found))return found;
   Model value;
   if(identity=="hex_key")value=Hex();else if(identity=="scissors")value=Scissors();
   else if(identity=="movement_arrow")value=ImportedArrow()??Arrow();else return null;
   cache.Add(identity,value);return value;
  }
  public static Vector3 Animate(Vector3 vertex,Part part,string motion,float progress){
   progress=Mathf.Clamp01(progress);
   if(motion=="loosen"||motion=="tighten"){
    // An illustrative partial turn, not a required angle or completed screw action.
    float degrees=(motion=="loosen"?-1:1)*360*progress;
    return Quaternion.AngleAxis(degrees,Vector3.up)*vertex;
   }
   if(motion=="cut"&&part.movingLeaf!=0){
    Vector3 pivot=new Vector3(0,-.47f,0);float angle=18*(.5f+.5f*Mathf.Cos(progress*Mathf.PI*2));
    return pivot+Quaternion.AngleAxis(part.movingLeaf*angle,Vector3.forward)*(vertex-pivot);
   }
   return vertex;
  }
  static Model Hex(){
   return new Model{provenance="manual2ar-procedural-hex-v1",parts=new[]{
    Rod(new Vector3(0,-.82f,0),Vector3.zero,.035f,Gold,6),
    Rod(new Vector3(-.44f,-.82f,0),new Vector3(0,-.82f,0),.035f,Gold,6)}};
  }
  static Model Scissors(){
   var parts=new List<Part>();
   for(int leaf=-1;leaf<=1;leaf+=2){
    float z=leaf*.018f;
    parts.Add(new Part{vertices=new[]{new Vector3(0,0,z),new Vector3(-.07f,-.47f,z),new Vector3(.055f,-.47f,z)},triangles=new[]{0,1,2},color=Metal,movingLeaf=leaf});
    var stem=Rod(new Vector3(0,-.47f,z),new Vector3(0,-.68f,z),.035f,Metal,8);stem.movingLeaf=leaf;parts.Add(stem);
    var grip=Ring(new Vector3(0,-.80f,z),.105f,.145f,.035f,Handle);grip.movingLeaf=leaf;parts.Add(grip);
   }
   parts.Add(Rod(new Vector3(0,-.47f,-.06f),new Vector3(0,-.47f,.06f),.055f,Gold,12));
   return new Model{parts=parts.ToArray(),provenance="manual2ar-procedural-scissors-v1"};
  }
  static Part Rod(Vector3 a,Vector3 b,float radius,Color color,int sides){
   Vector3 axis=(b-a).normalized,reference=Mathf.Abs(axis.z)<.9f?Vector3.forward:Vector3.right;
   Vector3 x=Vector3.Cross(axis,reference).normalized,y=Vector3.Cross(axis,x);
   var vertices=new Vector3[2*sides+2];var triangles=new List<int>();
   vertices[2*sides]=a;vertices[2*sides+1]=b;
   for(int i=0;i<sides;i++){
    float angle=i*Mathf.PI*2/sides;Vector3 d=radius*(x*Mathf.Cos(angle)+y*Mathf.Sin(angle));
    vertices[i]=a+d;vertices[i+sides]=b+d;int j=(i+1)%sides;
    triangles.AddRange(new[]{i,j,i+sides,j,j+sides,i+sides,2*sides,j,i,2*sides+1,i+sides,j+sides});
   }
   return new Part{vertices=vertices,triangles=triangles.ToArray(),color=color};
  }
  static Part Ring(Vector3 centre,float rx,float ry,float thickness,Color color){
   const int count=28;var vertices=new Vector3[count*2];var triangles=new List<int>();
   for(int i=0;i<count;i++){
    float angle=i*Mathf.PI*2/count;Vector3 outer=new Vector3(rx*Mathf.Cos(angle),ry*Mathf.Sin(angle),0);
    Vector3 inner=new Vector3((rx-thickness)*Mathf.Cos(angle),(ry-thickness)*Mathf.Sin(angle),0);
    vertices[i*2]=centre+outer;vertices[i*2+1]=centre+inner;int j=(i+1)%count;
    triangles.AddRange(new[]{i*2,j*2,i*2+1,j*2,j*2+1,i*2+1});
   }
   return new Part{vertices=vertices,triangles=triangles.ToArray(),color=color};
  }
  static Model Arrow(){
   var v=new[]{new Vector3(0,0,0),new Vector3(-.24f,-.34f,0),new Vector3(-.09f,-.34f,0),new Vector3(-.09f,-1,0),new Vector3(.09f,-1,0),new Vector3(.09f,-.34f,0),new Vector3(.24f,-.34f,0)};
   return new Model{provenance="manual2ar-procedural-arrow-v1",parts=new[]{new Part{vertices=v,triangles=new[]{0,1,2,0,2,5,0,5,6,2,3,4,2,4,5},color=new Color(.1f,.92f,1,.94f)}}};
  }
  static Model ImportedArrow(){
   var prefab=Resources.Load<GameObject>("GuidanceLocal/downArrow");if(prefab==null)return null;
   var vertices=new List<Vector3>();var triangles=new List<int>();
   foreach(var filter in prefab.GetComponentsInChildren<MeshFilter>(true)){
    var mesh=filter.sharedMesh;if(mesh==null||!mesh.isReadable)continue;
    int offset=vertices.Count;var transform=prefab.transform.worldToLocalMatrix*filter.transform.localToWorldMatrix;
    foreach(var vertex in mesh.vertices)vertices.Add(transform.MultiplyPoint3x4(vertex));
    foreach(int index in mesh.triangles)triangles.Add(offset+index);
   }
   if(vertices.Count<3||vertices.Count>12000)return null;
   var bounds=new Bounds(vertices[0],Vector3.zero);foreach(var vertex in vertices)bounds.Encapsulate(vertex);
   var axes=new[]{0,1,2};Array.Sort(axes,(a,b)=>bounds.size[b].CompareTo(bounds.size[a]));
   int forward=axes[0],side=axes[1],normal=axes[2];float length=bounds.size[forward];if(length<.0001f)return null;
   // Determine the narrow tip end rather than assume the FBX's authoring axes.
   float lowMin=float.MaxValue,lowMax=float.MinValue,highMin=float.MaxValue,highMax=float.MinValue;
   foreach(var v in vertices){
    if(v[forward]<bounds.min[forward]+length*.04f){lowMin=Mathf.Min(lowMin,v[side]);lowMax=Mathf.Max(lowMax,v[side]);}
    if(v[forward]>bounds.max[forward]-length*.04f){highMin=Mathf.Min(highMin,v[side]);highMax=Mathf.Max(highMax,v[side]);}
   }
   bool highTip=highMax-highMin<lowMax-lowMin;
   for(int i=0;i<vertices.Count;i++){
    Vector3 v=vertices[i];float y=highTip?v[forward]-bounds.max[forward]:bounds.min[forward]-v[forward];
    vertices[i]=new Vector3((v[side]-bounds.center[side])/length,y/length,(v[normal]-bounds.center[normal])/length);
   }
   return new Model{provenance="guided-reality-478d9d7-downArrow-local",parts=new[]{new Part{vertices=vertices.ToArray(),triangles=triangles.ToArray(),color=new Color(.1f,.92f,1,.94f)}}};
  }
 }
}
