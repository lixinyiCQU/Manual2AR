using System;
using UnityEngine;
using UnityEngine.UI;
namespace Manual2AR.Spatial {
 public sealed class SpatialActionBar {
  public RectTransform Root {get;private set;}
  readonly Button settings;
  public SpatialActionBar(Transform parent,Action markAction,Action settingsAction){
   Root=(RectTransform)parent;
   settings=AppTheme.Button(Root,"空间锚点配置",Vector2.zero,Vector2.one,settingsAction,AppIcon.Inspect);AppActionBar.Add(Root,settings);
  }
  public void Refresh(bool busy,bool canMark){settings.interactable=!busy;}
 }
}
