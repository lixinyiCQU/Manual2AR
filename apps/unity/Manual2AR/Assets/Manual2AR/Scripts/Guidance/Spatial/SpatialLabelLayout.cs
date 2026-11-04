using System.Collections.Generic;
using UnityEngine;
namespace Manual2AR.Spatial {
 public static class SpatialLabelLayout {
  public static Vector2 Place(Vector2 desired,Vector2 extent,Vector2 view,IList<Rect> occupied){
   var offsets=new[]{Vector2.zero,new Vector2(0,extent.y+14),new Vector2(0,-extent.y-14),new Vector2(extent.x+14,0),new Vector2(-extent.x-14,0),new Vector2(0,2*(extent.y+14)),new Vector2(0,-2*(extent.y+14))};
   var best=Vector2.zero;float score=float.MaxValue;
   foreach(var offset in offsets){
    var position=new Vector2(Mathf.Clamp(desired.x+offset.x,6,Mathf.Max(6,view.x-extent.x-6)),Mathf.Clamp(desired.y+offset.y,view.y*.15f,Mathf.Max(view.y*.15f,view.y*.85f-extent.y)));
    var rect=new Rect(position,extent);float overlap=0;
    foreach(var other in occupied){float w=Mathf.Max(0,Mathf.Min(rect.xMax,other.xMax+8)-Mathf.Max(rect.xMin,other.xMin-8));float h=Mathf.Max(0,Mathf.Min(rect.yMax,other.yMax+8)-Mathf.Max(rect.yMin,other.yMin-8));overlap+=w*h;}
    if(overlap<score){score=overlap;best=position;}if(overlap==0)break;
   }
   occupied.Add(new Rect(best,extent));return best;
  }
 }
}
