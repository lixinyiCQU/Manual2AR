using UnityEngine;
using UnityEngine.UI;

namespace Manual2AR {
 public sealed class AppMediaEmptyState:MonoBehaviour {
  RawImage media;GameObject hint;bool? visible;
  public static GameObject Attach(RectTransform parent,RawImage source,string message){
   var state=parent.gameObject.AddComponent<AppMediaEmptyState>();state.media=source;
   var root=AppTheme.Rect(parent,"Media empty state",new Vector2(.12f,.25f),new Vector2(.88f,.75f));state.hint=root.gameObject;
   var icon=AppTheme.Rect(root,"Camera",new Vector2(.44f,.55f),new Vector2(.56f,.83f)).gameObject.AddComponent<AppIconGraphic>();icon.symbol=AppIcon.Camera;icon.color=AppTheme.Muted;icon.raycastTarget=false;
   var text=AppTheme.Label(root,message,new Vector2(0,.12f),new Vector2(1,.5f),AppTheme.BodySize,AppTheme.Muted);text.alignment=TextAnchor.MiddleCenter;
   state.Refresh();return state.hint;
  }
  void LateUpdate(){Refresh();}
  void Refresh(){bool empty=media!=null&&media.texture==null;if(empty==visible)return;visible=empty;if(hint!=null)hint.SetActive(empty);}
 }
}
