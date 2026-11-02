// Explicit local hardware check: reads frames in memory, never uploads or saves camera images.
using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using Manual2AR;
using Manual2AR.Spatial;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

public static class SpatialCameraValidation {
 const string Key="Manual2AR.Spatial.CameraValidation";static bool started;static double since;
 [Serializable] class Device {public string name,error,signature;public bool ready;public int jpeg_frames;}
 [Serializable] class Report {public bool local_capture_only=true;public int successful_devices;public List<Device> devices=new List<Device>();}
 [InitializeOnLoadMethod] static void Attach(){if(SessionState.GetBool(Key,false)){since=EditorApplication.timeSinceStartup;EditorApplication.update+=Tick;}}
 public static void Run(){SessionState.SetBool(Key,true);EditorSceneManager.OpenScene("Assets/Manual2AR/Scenes/Welcome.unity");EditorApplication.isPlaying=true;}
 static void Tick(){
  if(EditorApplication.timeSinceStartup-since>100){SessionState.SetBool(Key,false);EditorApplication.Exit(2);return;}
  if(started||!EditorApplication.isPlaying)return;var shell=UnityEngine.Object.FindObjectOfType<AppShell>();if(shell==null)return;started=true;shell.StartCoroutine(Check());
 }
 static IEnumerator Check(){
  var report=new Report();var names=WebCamTexture.devices;var go=new GameObject("Local camera validation");var input=go.AddComponent<SpatialCamera>();
  for(int i=0;i<names.Length;i++){
   var record=new Device{name=names[i].name};report.devices.Add(record);yield return input.Open(i,error=>record.error=error);
   record.ready=input.Ready;record.signature=input.Signature;float until=Time.realtimeSinceStartup+3;
   while(record.ready&&record.jpeg_frames<3&&Time.realtimeSinceStartup<until){yield return null;var bytes=input.Capture();if(bytes!=null&&bytes.Length>1000)record.jpeg_frames++;}
   if(record.jpeg_frames>=3)report.successful_devices++;input.Close();yield return null;
  }
  string folder=Path.Combine(Application.dataPath,"../CameraValidation");Directory.CreateDirectory(folder);File.WriteAllText(Path.Combine(folder,"result.json"),JsonUtility.ToJson(report,true));
  UnityEngine.Object.Destroy(go);SessionState.SetBool(Key,false);EditorApplication.Exit(report.successful_devices>0?0:1);
 }
}
