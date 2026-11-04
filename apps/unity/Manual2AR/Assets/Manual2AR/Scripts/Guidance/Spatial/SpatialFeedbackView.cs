using UnityEngine;
using UnityEngine.UI;
namespace Manual2AR.Spatial {
 /// <summary>Frameless labels follow the current marker projection; loss uses an in-frame caption.</summary>
 public sealed class SpatialFeedbackView {
  readonly RectTransform viewport,root;
  public Text StepLabel {get;private set;}
  public bool MarkerAttached {get;private set;}
  public SpatialFeedbackView(RectTransform camera){
   viewport=camera;root=AppTheme.Rect(camera,"Marker teaching captions",Vector2.zero,Vector2.zero);root.pivot=new Vector2(0,1);root.sizeDelta=new Vector2(500,52);
   StepLabel=Caption("正在读取步骤",Vector2.zero,Vector2.one,28);
   StepLabel.resizeTextForBestFit=true;StepLabel.resizeTextMinSize=24;StepLabel.resizeTextMaxSize=28;
   Place(null);
  }
  Text Caption(string text,Vector2 min,Vector2 max,int size){
   var label=AppTheme.Label(root,text,min,max,size);label.horizontalOverflow=HorizontalWrapMode.Wrap;
   var outline=label.gameObject.AddComponent<UnityEngine.UI.Outline>();outline.effectColor=Color.black;outline.effectDistance=new Vector2(1.5f,-1.5f);
   return label;
  }
  public void Place(Reply reply){
   var size=viewport.rect.size;var corners=reply?.pose?.corners;
   root.sizeDelta=new Vector2(Mathf.Min(500,Mathf.Max(1,size.x-24)),52);
   MarkerAttached=corners!=null&&corners.Length==4&&reply.width>0&&reply.height>0;
   Vector2 position=new Vector2(16,size.y-16);
   if(MarkerAttached){
    float y=0,left=float.MaxValue,top=float.MaxValue;
    foreach(var p in corners){if(p==null){MarkerAttached=false;break;}y+=p.y*.25f;left=Mathf.Min(left,p.x);top=Mathf.Min(top,p.y);}
    if(MarkerAttached){
     float x=left/reply.width*size.x-root.sizeDelta.x-18;
     // Leave the action area on the marker's right clear for tools and part labels.
     position=x>=12?new Vector2(x,(1-y/reply.height)*size.y+31):new Vector2(left/reply.width*size.x,(1-top/reply.height)*size.y+80);
    }
   }
   root.anchoredPosition=new Vector2(Mathf.Clamp(position.x,12,Mathf.Max(12,size.x-root.sizeDelta.x-12)),Mathf.Clamp(position.y,74,Mathf.Max(74,size.y-12)));
  }

 }
}
