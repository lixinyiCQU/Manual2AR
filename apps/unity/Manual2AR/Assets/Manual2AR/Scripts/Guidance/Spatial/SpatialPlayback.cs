using System;
namespace Manual2AR.Spatial {
 /// <summary>Automatic illustration loop; pauses on missing geometry, never executes a task.</summary>
 public sealed class SpatialPlayback {
  public string State {get;private set;}="idle";
  public bool Available {get;private set;}
  public float CyclePosition {get;private set;}
  public float Progress {get;private set;}
  public float Duration {get;private set;}=1.2f;
  public void Reset(){State="idle";Progress=0;CyclePosition=0;Available=false;}
  public void Configure(float duration){Duration=Math.Max(.5f,Math.Min(10,duration));}
  public bool SetAvailable(bool value){bool paused=!value&&State=="playing";Available=value;State=value?"playing":State=="idle"?"idle":"paused";return paused;}
  public bool Tick(float seconds){
   if(State!="playing"||!Available)return false;
   float advance=Math.Max(0,seconds)/Duration;CyclePosition+=advance;float value=Progress+advance;bool looped=value>=1-.000001f;
   Progress=value%1;if(Progress>1-.000001f)Progress=0;return looped;
  }
 }
}
