using System;
using UnityEngine;
using UnityEngine.UI;
namespace Manual2AR.Spatial {
 public sealed class SpatialActionBar {
  public RectTransform Root {get;private set;}
  readonly Button settings;
  public SpatialActionBar(Transform parent,Action markAction,Action settingsAction){
   Root=AppTheme.Rect(parent,"Spatial actions",new Vector2(.411f,.91f),new Vector2(.589f,.975f));
   settings=AppTheme.Button(Root,"空间锚点配置",Vector2.zero,Vector2.one,settingsAction,AppIcon.Inspect);
  }
  public void Refresh(bool busy,bool canMark){settings.interactable=!busy;}
 }
}
