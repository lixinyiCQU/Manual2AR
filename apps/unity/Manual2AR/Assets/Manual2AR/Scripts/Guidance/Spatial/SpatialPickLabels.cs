using UnityEngine;
using UnityEngine.UI;

namespace Manual2AR.Spatial {
 /// <summary>Names authored image points; no coordinate inference or task logic.</summary>
 public sealed class SpatialPickLabels {
  readonly RectTransform[] boxes=new RectTransform[3];readonly Text[] texts=new Text[3];
  public SpatialPickLabels(Transform parent){
   for(int i=0;i<3;i++){
    boxes[i]=AppTheme.Panel(parent,"Setup point "+(i+1),Vector2.zero,Vector2.zero);boxes[i].pivot=new Vector2(0,.5f);
    texts[i]=AppTheme.Label(boxes[i],"",new Vector2(.04f,.04f),new Vector2(.96f,.96f),19);
    texts[i].alignment=TextAnchor.MiddleCenter;
    foreach(var graphic in boxes[i].GetComponentsInChildren<Graphic>())graphic.raycastTarget=false;
    boxes[i].gameObject.SetActive(false);
   }
  }
  public void Refresh(SpatialOverlay overlay,string[] names){
   var size=overlay.rectTransform.rect.size;
   for(int i=0;i<3;i++){
    bool visible=overlay.accepting&&i<overlay.picks.Count&&size.x>1&&size.y>1;
    boxes[i].gameObject.SetActive(visible);if(!visible)continue;
    string name=names!=null&&names.Length>i?names[i]:(i==0?"第一点":"第二点");
    string value=(i+1)+" · "+name;texts[i].text=AppTheme.Readable(value);texts[i].color=i==0?Color.yellow:AppTheme.SuccessGreen;
    float width=Mathf.Clamp(35+value.Length*19,125,290);boxes[i].sizeDelta=new Vector2(width,34);
    var p=overlay.picks[i];float x=p.x/overlay.width*size.x,y=(1-p.y/overlay.height)*size.y;
    boxes[i].anchoredPosition=new Vector2(Mathf.Clamp(x+15,4,Mathf.Max(4,size.x-width-4)),Mathf.Clamp(y+(i==0?30:-30),20,Mathf.Max(20,size.y-20)));
   }
  }
 }
}
