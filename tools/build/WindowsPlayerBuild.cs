// Copied into an isolated Unity validation project's Assets/Editor by the build runner.
using System;
using System.Linq;
using UnityEditor;
using UnityEditor.Build.Reporting;
public static class WindowsPlayerBuild {
 public static void Build(){
  var args=Environment.GetCommandLineArgs();int index=Array.IndexOf(args,"--manual2ar-output");
  if(index<0||index+1>=args.Length)throw new Exception("Missing --manual2ar-output");
  var result=BuildPipeline.BuildPlayer(EditorBuildSettings.scenes.Where(s=>s.enabled).Select(s=>s.path).ToArray(),args[index+1],BuildTarget.StandaloneWindows64,BuildOptions.None);
  if(result.summary.result!=BuildResult.Succeeded)throw new Exception("Windows build failed: "+result.summary.result);
 }
}
