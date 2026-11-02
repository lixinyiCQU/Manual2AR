using System.IO;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
namespace Manual2AR.Editor {
 public static class AppEditorSetup {
  [InitializeOnLoadMethod] static void Initialize(){
   EditorApplication.delayCall+=()=>{
    if(Application.isBatchMode||EditorApplication.isPlayingOrWillChangePlaymode)return;
    if(!SessionState.GetBool("Manual2AR.Welcome.Opened",false)){
     SessionState.SetBool("Manual2AR.Welcome.Opened",true);
     if(File.Exists("Assets/Manual2AR/Scenes/Welcome.unity"))EditorSceneManager.OpenScene("Assets/Manual2AR/Scenes/Welcome.unity");
    }
   };
  }
  [MenuItem("Manual2AR/打开欢迎界面")]
  public static void Open(){if(EditorSceneManager.SaveCurrentModifiedScenesIfUserWantsTo())EditorSceneManager.OpenScene("Assets/Manual2AR/Scenes/Welcome.unity");}
 }
}
