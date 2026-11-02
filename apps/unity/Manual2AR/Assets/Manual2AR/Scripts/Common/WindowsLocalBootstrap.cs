using System;
using System.IO;
using UnityEngine;

namespace Manual2AR {
 /// <summary>Windows camera drivers can enumerate but fail capture from a WSL/UNC Player.</summary>
 public static class WindowsLocalBootstrap {
  public static bool IsNetworkPath(string path){return !string.IsNullOrEmpty(path)&&path.Replace('\\','/').StartsWith("//",StringComparison.Ordinal);}
  [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.BeforeSceneLoad)]
  static void Redirect(){
   if(Application.isEditor||Application.platform!=RuntimePlatform.WindowsPlayer||!IsNetworkPath(Application.dataPath))return;
   string script=Path.GetFullPath(Path.Combine(Application.dataPath,"../Start-Desktop.ps1"));
   if(!File.Exists(script)){Debug.LogWarning("Run the complete Manual2AR folder from a local Windows disk to use the camera.");return;}
   bool spatial=Array.IndexOf(Environment.GetCommandLineArgs(),"--spatial-demo")>=0;
   try{
    var start=new System.Diagnostics.ProcessStartInfo("powershell.exe","-NoProfile -ExecutionPolicy Bypass -File \""+script+"\""+(spatial?" -SpatialDemo":""));
    start.UseShellExecute=true;System.Diagnostics.Process.Start(start);Application.Quit(0);
   }catch(Exception error){Debug.LogWarning("Could not launch local Windows frontend: "+error.GetType().Name+". Use the supplied startup script or copy the folder to a local disk.");}
  }
 }
}
