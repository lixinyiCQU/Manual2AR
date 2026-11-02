using UnityEngine;
using UnityEngine.UI;
namespace Manual2AR {
 // Resolution-independent rounded panels/buttons. No raster/icon-font dependency.
 [RequireComponent(typeof(CanvasRenderer))]
 public sealed class AppRoundedImage:Image {
  public float radius=18;
  protected override void OnPopulateMesh(VertexHelper vh){
   vh.Clear();var r=rectTransform.rect;float rad=Mathf.Min(radius,Mathf.Min(r.width,r.height)*.5f);
   vh.AddVert(r.center,color,Vector2.zero);int count=0;
   var centers=new[]{new Vector2(r.xMax-rad,r.yMax-rad),new Vector2(r.xMin+rad,r.yMax-rad),new Vector2(r.xMin+rad,r.yMin+rad),new Vector2(r.xMax-rad,r.yMin+rad)};
   for(int corner=0;corner<4;corner++)for(int j=0;j<=8;j++){
    float a=(corner*90+j*90f/8)*Mathf.Deg2Rad;var p=centers[corner]+new Vector2(Mathf.Cos(a),Mathf.Sin(a))*rad;
    vh.AddVert(p,color,Vector2.zero);count++;
   }
   for(int i=1;i<=count;i++)vh.AddTriangle(0,i,i==count?1:i+1);
  }
 }
}
