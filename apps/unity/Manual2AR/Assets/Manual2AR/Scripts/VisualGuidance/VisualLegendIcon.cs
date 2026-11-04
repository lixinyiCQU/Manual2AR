using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UI;
namespace Manual2AR.VisualGuidance {
 /// <summary>Fixed isometric thumbnail of the same verified 3D mesh used in the scene.</summary>
 [RequireComponent(typeof(CanvasRenderer))]
 public sealed class VisualLegendIcon:MaskableGraphic {
  public LegendItem Item;public int VisibleTriangles {get;private set;}
  struct Face {public Vector3 a,b,c;public Color shade;public float depth;}
  protected override void OnPopulateMesh(VertexHelper v){
   v.Clear();VisibleTriangles=0;if(Item==null)return;var rect=rectTransform.rect;
   if(Item.kind=="highlight"){
    var color=Item.color!=null&&Item.color.Length==3?new Color(Item.color[0],Item.color[1],Item.color[2],.8f):AppTheme.TargetCyan;
    var r=new Rect(rect.xMin+10,rect.yMin+10,rect.width-20,rect.height-20);v.AddVert(new Vector2(r.xMin,r.yMin),color,Vector2.zero);v.AddVert(new Vector2(r.xMin,r.yMax),color,Vector2.zero);v.AddVert(new Vector2(r.xMax,r.yMax),color,Vector2.zero);v.AddVert(new Vector2(r.xMax,r.yMin),color,Vector2.zero);v.AddTriangle(0,1,2);v.AddTriangle(0,2,3);return;
   }
   var model=VisualAssetLibrary.Get(Item.asset_id);if(model==null)return;
   var rotation=Quaternion.Euler(22,-32,12);var faces=new List<Face>();var lo=new Vector2(float.MaxValue,float.MaxValue);var hi=-lo;
   for(int p=0;p<model.Vertices.Length;p++){
    var mesh=model.Mesh.parts[p];var vertices=model.Vertices[p];
    for(int i=0;i<mesh.triangles.Length;i+=3){var a=rotation*vertices[mesh.triangles[i]];var b=rotation*vertices[mesh.triangles[i+1]];var c=rotation*vertices[mesh.triangles[i+2]];
     foreach(var point in new[]{a,b,c}){lo=Vector2.Min(lo,point);hi=Vector2.Max(hi,point);}
     float light=.65f+.35f*Mathf.Abs(Vector3.Cross(b-a,c-a).normalized.z);
     faces.Add(new Face{a=a,b=b,c=c,shade=new Color(mesh.color[0]*light,mesh.color[1]*light,mesh.color[2]*light,1),depth=(a.z+b.z+c.z)/3});
    }
   }
   faces.Sort((a,b)=>a.depth.CompareTo(b.depth));float scale=Mathf.Min((rect.width-8)/Mathf.Max(.00001f,hi.x-lo.x),(rect.height-8)/Mathf.Max(.00001f,hi.y-lo.y));var centre=(lo+hi)*.5f;
   foreach(var f in faces){int start=v.currentVertCount;foreach(var point in new[]{f.a,f.b,f.c})v.AddVert(rect.center+((Vector2)point-centre)*scale,f.shade,Vector2.zero);v.AddTriangle(start,start+1,start+2);VisibleTriangles++;}
  }
 }
}
