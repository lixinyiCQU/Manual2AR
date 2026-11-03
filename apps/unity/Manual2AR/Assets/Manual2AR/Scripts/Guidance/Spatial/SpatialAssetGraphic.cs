using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UI;

namespace Manual2AR.Spatial {
 /// <summary>Project illustration meshes using the exact RGB snapshot's K/distortion/pose.
 /// No estimated depth, extra camera, hidden GPU dependency, or task-state mutation.</summary>
 [RequireComponent(typeof(CanvasRenderer))]
 public sealed class SpatialAssetGraphic:MaskableGraphic {
  public GuidanceVisual visual;public int width=960,height=720;public float progress;
  public int VisibleTriangles {get;private set;}
  public string AssetProvenance {get;private set;}="";
  struct Face {public Vector2 a,b,c;public float depth;public Color color;}
  readonly List<Face> faces=new List<Face>();
  // JsonUtility may create empty nested objects for JSON null; check the payload.
  public static bool HasPlacement(GuidanceVisual value){
   return value!=null&&value.asset!=null&&!string.IsNullOrEmpty(value.asset.asset_id)
    &&value.asset.marker_from_asset!=null&&value.asset.marker_from_asset.Length==16
    &&value.projection!=null&&value.projection.camera_from_marker!=null&&value.projection.camera_from_marker.Length==16
    &&value.projection.intrinsics!=null&&value.projection.intrinsics.Length==9;
  }
  public void Clear(){visual=null;VisibleTriangles=0;AssetProvenance="";SetVerticesDirty();}
  public static Vector3 Transform(float[] matrix,Vector3 p){
   return new Vector3(matrix[0]*p.x+matrix[1]*p.y+matrix[2]*p.z+matrix[3],matrix[4]*p.x+matrix[5]*p.y+matrix[6]*p.z+matrix[7],matrix[8]*p.x+matrix[9]*p.y+matrix[10]*p.z+matrix[11]);
  }
  public static bool Project(SpatialProjection projection,Vector3 marker,out Vector2 pixel,out float depth){
   pixel=Vector2.zero;depth=0;
   if(projection==null||projection.camera_from_marker==null||projection.camera_from_marker.Length!=16||projection.intrinsics==null||projection.intrinsics.Length!=9)return false;
   Vector3 p=Transform(projection.camera_from_marker,marker);depth=p.z;if(depth<=.03f)return false;
   float x=p.x/p.z,y=p.y/p.z,r2=x*x+y*y,r4=r2*r2,r6=r4*r2;var d=projection.distortion;
   float k1=Coefficient(d,0),k2=Coefficient(d,1),p1=Coefficient(d,2),p2=Coefficient(d,3),k3=Coefficient(d,4);
   float denominator=1+Coefficient(d,5)*r2+Coefficient(d,6)*r4+Coefficient(d,7)*r6;
   if(Mathf.Abs(denominator)<.0001f)return false;
   float radial=(1+k1*r2+k2*r4+k3*r6)/denominator;
   float xd=x*radial+2*p1*x*y+p2*(r2+2*x*x),yd=y*radial+p1*(r2+2*y*y)+2*p2*x*y;
   var k=projection.intrinsics;pixel=new Vector2(k[0]*xd+k[2],k[4]*yd+k[5]);
   return !float.IsNaN(pixel.x)&&!float.IsNaN(pixel.y)&&!float.IsInfinity(pixel.x)&&!float.IsInfinity(pixel.y);
  }
  static float Coefficient(float[] d,int index){return d!=null&&index<d.Length?d[index]:0;}
  Vector2 Local(Vector2 p){var r=rectTransform.rect;return new Vector2(r.xMin+p.x/width*r.width,r.yMax-p.y/height*r.height);}
  protected override void OnPopulateMesh(VertexHelper helper){
   helper.Clear();faces.Clear();VisibleTriangles=0;AssetProvenance="";
   if(!HasPlacement(visual))return;
   var asset=visual.asset;if(asset.marker_from_asset==null||asset.marker_from_asset.Length!=16)return;
   var model=SpatialAssetGeometry.Get(asset.asset_id);if(model==null)return;AssetProvenance=model.provenance;
   Vector3 shift=asset.motion=="translate"&&asset.translation_m!=null&&asset.translation_m.Length==3?new Vector3(asset.translation_m[0],asset.translation_m[1],asset.translation_m[2])*Mathf.Clamp01(progress):Vector3.zero;
   foreach(var part in model.parts){
    int count=part.vertices.Length;var pixels=new Vector2[count];var camera=new Vector3[count];var valid=new bool[count];
    for(int i=0;i<count;i++){
     Vector3 local=SpatialAssetGeometry.Animate(part.vertices[i],part,asset.motion,progress);
     Vector3 marker=Transform(asset.marker_from_asset,local)+shift;float depth;
     valid[i]=Project(visual.projection,marker,out pixels[i],out depth);camera[i]=Transform(visual.projection.camera_from_marker,marker);
    }
    for(int i=0;i<part.triangles.Length;i+=3){
     int a=part.triangles[i],b=part.triangles[i+1],c=part.triangles[i+2];if(!valid[a]||!valid[b]||!valid[c])continue;
     Vector3 normal=Vector3.Cross(camera[b]-camera[a],camera[c]-camera[a]).normalized;
     float light=.6f+.4f*Mathf.Abs(Vector3.Dot(normal,new Vector3(-.3f,-.4f,-1).normalized));Color color=part.color;
     color.r*=light;color.g*=light;color.b*=light;
     faces.Add(new Face{a=Local(pixels[a]),b=Local(pixels[b]),c=Local(pixels[c]),depth=(camera[a].z+camera[b].z+camera[c].z)/3,color=color});
    }
   }
   faces.Sort((a,b)=>b.depth.CompareTo(a.depth));
   foreach(var face in faces){
    // UI shader culls neither face; painter sorting supplies readable tool surfaces.
    int i=helper.currentVertCount;helper.AddVert(face.a,face.color,Vector2.zero);helper.AddVert(face.b,face.color,Vector2.zero);helper.AddVert(face.c,face.color,Vector2.zero);helper.AddTriangle(i,i+1,i+2);
   }
   VisibleTriangles=faces.Count;
  }
 }
}
