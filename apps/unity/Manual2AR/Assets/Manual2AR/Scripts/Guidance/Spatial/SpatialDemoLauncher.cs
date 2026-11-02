using System;
using System.Collections;
using System.IO;
using UnityEngine;
namespace Manual2AR.Spatial {
 /// <summary>Direct editor demo entry. Production tutorials open the same view in place.</summary>
 public sealed class SpatialDemoLauncher:MonoBehaviour {
  [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
  static void CommandLine(){if(!Application.isEditor&&Array.IndexOf(Environment.GetCommandLineArgs(),"--spatial-demo")>=0)new GameObject("Spatial Demo Entry").AddComponent<SpatialDemoLauncher>();}
  IEnumerator Start(){
   yield return null;
   string origin="http://127.0.0.1:8010";
   try{origin=JsonUtility.FromJson<UnboxingSettings>(File.ReadAllText(Path.Combine(Application.streamingAssetsPath,"Guidance.json"))).backend_url;}catch(Exception){}
   SpatialGuidanceController.Open(AppShell.BackendUrl(origin),"U6",()=>AppShell.Open("Welcome"));
  }
 }
}
