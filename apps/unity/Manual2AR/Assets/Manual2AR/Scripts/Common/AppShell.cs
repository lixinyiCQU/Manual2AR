using System;
using System.Collections;
using System.IO;
using UnityEngine;
using UnityEngine.EventSystems;
using UnityEngine.SceneManagement;
using UnityEngine.UI;

namespace Manual2AR {
 /// <summary>One persistent, contextual back action. Task pages never skip their parent.</summary>
 public sealed class AppShell:MonoBehaviour {
  static AppShell instance;Canvas shell;Button back;Text state;Action backAction;Func<bool> canBack;bool changing;string backLabel="返回教学首页";
  public static AppService SelectedService {get;private set;}
  public static bool Changing {get{return instance!=null&&instance.changing;}}
  public static void SelectService(AppService service){SelectedService=service;}
  public static string BackendUrl(string fallback){return SelectedService==null||string.IsNullOrEmpty(SelectedService.backend_url)?fallback:SelectedService.backend_url;}
  [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.SubsystemRegistration)]
  static void ResetStatics(){instance=null;SelectedService=null;}
  [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.BeforeSceneLoad)]
  static void Install(){Ensure();}
  [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
  static void RepairDirectSceneEntry(){Ensure();instance.EnsureUI();}
  static void Ensure(){
   if(instance!=null)return;instance=FindObjectOfType<AppShell>();
   if(instance==null)instance=new GameObject("Manual2AR Application").AddComponent<AppShell>();
   DontDestroyOnLoad(instance.gameObject);
  }
  void Awake(){SceneManager.sceneLoaded+=Loaded;}
  void OnDestroy(){SceneManager.sceneLoaded-=Loaded;}
  void Loaded(Scene scene,LoadSceneMode mode){
   EnsureUI();if(scene.name=="Welcome")HideBack();else BindTeachingBack();
  }
  void EnsureUI(){
   if(EventSystem.current==null){var events=new GameObject("Application EventSystem",typeof(EventSystem),typeof(StandaloneInputModule));events.transform.SetParent(transform,false);}
   if(shell!=null)return;
   var go=new GameObject("Application Navigation",typeof(RectTransform),typeof(Canvas),typeof(CanvasScaler),typeof(GraphicRaycaster));go.transform.SetParent(transform,false);
   shell=go.GetComponent<Canvas>();shell.renderMode=RenderMode.ScreenSpaceOverlay;shell.sortingOrder=500;
   var scaler=go.GetComponent<CanvasScaler>();scaler.uiScaleMode=CanvasScaler.ScaleMode.ScaleWithScreenSize;scaler.referenceResolution=new Vector2(1920,1080);scaler.matchWidthOrHeight=.5f;
   back=AppTheme.Button(go.transform,"返回教学首页",new Vector2(.805f,.939f),new Vector2(.975f,.988f),GoBack,AppIcon.Back);
   state=AppTheme.Label(go.transform,"",new Vector2(.63f,.939f),new Vector2(.79f,.988f),21,AppTheme.Muted);
   back.gameObject.name=backLabel;back.GetComponentInChildren<Text>().text=backLabel;back.gameObject.SetActive(backAction!=null);
  }
  static void ResolveDirectEntry(){
   if(SelectedService!=null)return;
   try{var catalog=JsonUtility.FromJson<AppServiceCatalog>(File.ReadAllText(Path.Combine(Application.streamingAssetsPath,"Services.json")));if(catalog!=null&&catalog.services!=null&&catalog.services.Length==1)SelectedService=catalog.services[0];}catch(Exception){}
  }
  public static void BindTeachingBack(){ResolveDirectEntry();BindBack("返回教学首页",()=>Open("Welcome"));}
  public static void BindBack(string label,Action action,Func<bool> allowed=null){
   Ensure();instance.EnsureUI();instance.backAction=action;instance.canBack=allowed;instance.backLabel=label;
   var rect=(RectTransform)instance.back.transform;rect.anchorMin=new Vector2(.805f,.939f);rect.anchorMax=new Vector2(.975f,.988f);
   instance.back.gameObject.SetActive(true);instance.back.gameObject.name=label;instance.back.GetComponentInChildren<Text>().text=label;
  }
  public static void PlaceBack(Vector2 min,Vector2 max){Ensure();instance.EnsureUI();var rect=(RectTransform)instance.back.transform;rect.anchorMin=min;rect.anchorMax=max;}
  public static void HideBack(){Ensure();instance.EnsureUI();instance.backAction=null;instance.canBack=null;instance.back.gameObject.SetActive(false);}
  public static void GoBack(){if(instance!=null&&!instance.changing&&(instance.canBack==null||instance.canBack()))instance.backAction?.Invoke();}
  void Update(){EnsureUI();if(back!=null)back.interactable=!changing&&(canBack==null||canBack());}
  public static void Open(string scene){Ensure();if(!instance.changing)instance.StartCoroutine(instance.Navigate(scene));}
  IEnumerator Navigate(string scene){
   changing=true;EnsureUI();back.interactable=false;state.text="正在返回…";
   try{
    foreach(var canvas in FindObjectsOfType<Canvas>())if(canvas!=shell){var group=canvas.GetComponent<CanvasGroup>();if(group==null)group=canvas.gameObject.AddComponent<CanvasGroup>();group.interactable=false;}
    foreach(var behavior in FindObjectsOfType<MonoBehaviour>())if(behavior is IAppModule module)yield return module.ReleaseModule();
    var operation=SceneManager.LoadSceneAsync(scene,LoadSceneMode.Single);if(operation!=null)while(!operation.isDone)yield return null;
   }finally{changing=false;if(state!=null)state.text="";foreach(var group in FindObjectsOfType<CanvasGroup>())group.interactable=true;}
  }
 }
}
