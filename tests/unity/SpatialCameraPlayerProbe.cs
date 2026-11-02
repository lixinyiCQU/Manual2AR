// Compile into an isolated diagnostic Player only, never into the delivery project.
using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using Manual2AR.Spatial;
using UnityEngine;

public sealed class SpatialCameraPlayerProbe:MonoBehaviour {
 [Serializable] class Device {public string name,error,signature;public bool ready;public int jpeg_frames;}
 [Serializable] class Report {public bool local_capture_only=true;public string application_path;public int successful_devices;public List<Device> devices=new List<Device>();}
 [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
 static void Install(){if(Array.IndexOf(Environment.GetCommandLineArgs(),"--camera-hardware-probe")>=0)new GameObject("Local camera probe").AddComponent<SpatialCameraPlayerProbe>();}
 IEnumerator Start(){
  yield return null;var report=new Report{application_path=Application.dataPath};var names=WebCamTexture.devices;var input=gameObject.AddComponent<SpatialCamera>();
  for(int i=0;i<names.Length;i++){
   var record=new Device{name=names[i].name};report.devices.Add(record);yield return input.Open(i,error=>record.error=error);
   record.ready=input.Ready;record.signature=input.Signature;float until=Time.realtimeSinceStartup+3;
   while(record.ready&&record.jpeg_frames<3&&Time.realtimeSinceStartup<until){yield return null;var bytes=input.Capture();if(bytes!=null&&bytes.Length>1000)record.jpeg_frames++;}
   if(record.jpeg_frames>=3)report.successful_devices++;input.Close();yield return null;
  }
  var args=Environment.GetCommandLineArgs();int at=Array.IndexOf(args,"--camera-probe-result");
  if(at>=0&&at+1<args.Length)File.WriteAllText(args[at+1],JsonUtility.ToJson(report,true));
  Application.Quit(report.successful_devices>0?0:1);
 }
}
