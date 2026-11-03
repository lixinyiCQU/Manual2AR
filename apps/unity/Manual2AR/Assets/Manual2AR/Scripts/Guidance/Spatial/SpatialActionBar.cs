using System;
using UnityEngine;
using UnityEngine.UI;
namespace Manual2AR.Spatial {
 public sealed class SpatialActionBar {
  public RectTransform Root {get;private set;}
  readonly Button mark,settings;
  public SpatialActionBar(Transform parent,Action markAction,Action settingsAction){
   Root=AppTheme.Rect(parent,"Spatial actions",new Vector2(.025f,.025f),new Vector2(.975f,.085f));
   mark=AppTheme.Button(Root,"我已操作",new Vector2(.53f,0),new Vector2(.75f,1),markAction,AppIcon.Check);
   settings=AppTheme.Button(Root,"空间锚点配置",new Vector2(.77f,0),new Vector2(1,1),settingsAction,AppIcon.Inspect);
  }
  public void Refresh(bool busy,bool canMark){mark.interactable=!busy&&canMark;settings.interactable=!busy;}
 }
}
