using System;
using UnityEngine;
using UnityEngine.UI;

namespace Manual2AR {
 /// <summary>Shared controls, not a shared camera session. Each module handles invalidation.</summary>
 public sealed class AppCameraBar {
  public Button Start {get;private set;}
  public Button Switch {get;private set;}
  public AppAspectSelector Aspect {get;private set;}
  public AppCameraBar(RectTransform parent,CameraFraming framing,Action start,Action change,Action<int> aspect){
   Start=AppTheme.Button(parent,"启动摄像头",new Vector2(0,.08f),new Vector2(.18f,.92f),start,AppIcon.Camera);
   Switch=AppTheme.Button(parent,"切换摄像头",new Vector2(.19f,.08f),new Vector2(.37f,.92f),change,AppIcon.SwitchCamera);
   var area=AppTheme.Rect(parent,"Capture aspect",new Vector2(.40f,.08f),new Vector2(1,.92f));
   Aspect=framing.AddSelector(area,Vector2.zero,Vector2.one,aspect);
  }
 }
}
