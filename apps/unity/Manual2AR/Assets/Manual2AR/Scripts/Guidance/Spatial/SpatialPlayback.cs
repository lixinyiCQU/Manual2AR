using System;
namespace Manual2AR.Spatial {
 /// <summary>Explanatory animation clock. Independent of camera updates and task completion.</summary>
 public sealed class SpatialPlayback {
  public string State {get;private set;}="idle";
  public bool Available {get;private set;}
  public float Progress {get;private set;}
  public float Duration {get;private set;}=3;
  public void Reset(){State="idle";Progress=0;Available=false;}
  public void Configure(float duration){Duration=Math.Max(1,Math.Min(10,duration));}
  public bool SetAvailable(bool value){bool paused=!value&&State=="playing";Available=value;if(paused)State="paused";return paused;}
  public bool Play(){if(!Available||State=="playing")return false;if(State=="finished")Progress=0;State="playing";return true;}
  public bool Pause(){if(State!="playing")return false;State="paused";return true;}
  public bool Replay(){if(!Available)return false;Progress=0;State="playing";return true;}
  public bool Tick(float seconds){
   if(State!="playing"||!Available)return false;
   Progress=Math.Min(1,Progress+Math.Max(0,seconds)/Duration);
   if(Progress<1)return false;State="finished";return true;
  }
 }
}
