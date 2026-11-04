using UnityEngine;
using UnityEngine.UI;
namespace Manual2AR.VisualGuidance {
 /// <summary>Image-space teaching proxy fitted to a matched mask. Never creates a metric or AR anchor.</summary>
 [RequireComponent(typeof(CanvasRenderer))]
 public sealed class VisualImageProxyGraphic:MaskableGraphic {
  public string AssetId;public int[] Box;public float Angle;public int Width,Height;
  public int VisibleTriangles {get;private set;}
  public void Clear(){AssetId=null;Box=null;SetVerticesDirty();}
  protected override void OnPopulateMesh(VertexHelper helper){
   helper.Clear();VisibleTriangles=0;var model=VisualAssetLibrary.Get(AssetId);if(model==null||Box==null||Box.Length!=4||Width<=0||Height<=0)return;
   float angle=Angle*Mathf.Deg2Rad,c=Mathf.Cos(angle),s=Mathf.Sin(angle);Vector2 lo=new Vector2(float.MaxValue,float.MaxValue),hi=-lo;
   foreach(var part in model.Vertices)foreach(var v in part){var p=new Vector2(c*v.x-s*v.y,s*v.x+c*v.y);lo=Vector2.Min(lo,p);hi=Vector2.Max(hi,p);}
   var rect=rectTransform.rect;var centre=(lo+hi)/2;float bw=(Box[2]-Box[0])/1000f*Width,bh=(Box[3]-Box[1])/1000f*Height;float scale=Mathf.Min(bw/Mathf.Max(.0001f,hi.x-lo.x),bh/Mathf.Max(.0001f,hi.y-lo.y));
   for(int part=0;part<model.Vertices.Length;part++){
    var mesh=model.Mesh.parts[part];var shade=new Color(mesh.color[0],mesh.color[1],mesh.color[2],.34f);int start=helper.currentVertCount;
    foreach(var v in model.Vertices[part]){var p=new Vector2(c*v.x-s*v.y,s*v.x+c*v.y)-centre;float x=(Box[0]+Box[2])/2000f*Width+p.x*scale,y=(Box[1]+Box[3])/2000f*Height+p.y*scale;helper.AddVert(new Vector2(rect.xMin+x/Width*rect.width,rect.yMax-y/Height*rect.height),shade,Vector2.zero);}
    for(int i=0;i<mesh.triangles.Length;i+=3){helper.AddTriangle(start+mesh.triangles[i],start+mesh.triangles[i+1],start+mesh.triangles[i+2]);VisibleTriangles++;}
   }
  }
 }
}
