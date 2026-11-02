using System;
using UnityEngine;
using UnityEngine.UI;
namespace Manual2AR.Spatial {
 public sealed class SpatialPlaybackBar {
  public RectTransform Root {get;private set;}
  Button play,pause,replay,mark;
  public SpatialPlaybackBar(Transform parent,Action playAction,Action pauseAction,Action replayAction,Action markAction,Action settingsAction){
   Root=AppTheme.Rect(parent,"Action Playback",new Vector2(.025f,.022f),new Vector2(.975f,.08f));
   play=AppTheme.Button(Root,"播放示意",new Vector2(0,0),new Vector2(.19f,1),playAction,AppIcon.Play,true);
   pause=AppTheme.Button(Root,"暂停",new Vector2(.203f,0),new Vector2(.393f,1),pauseAction,AppIcon.Pause);
   replay=AppTheme.Button(Root,"重新播放",new Vector2(.406f,0),new Vector2(.596f,1),replayAction,AppIcon.SwitchCamera);
   mark=AppTheme.Button(Root,"我已操作",new Vector2(.609f,0),new Vector2(.799f,1),markAction,AppIcon.Check);
   AppTheme.Button(Root,"位置设置",new Vector2(.812f,0),new Vector2(1,1),settingsAction,AppIcon.Info);
  }
  public void Refresh(SpatialPlayback state,bool busy,bool canMark){
   play.interactable=!busy&&state.Available&&state.State!="playing";
   pause.interactable=!busy&&state.State=="playing";
   replay.interactable=!busy&&state.Available;mark.interactable=!busy&&canMark;
   play.GetComponentInChildren<Text>().text=state.State=="paused"?"继续播放":"播放示意";
  }
 }
}
