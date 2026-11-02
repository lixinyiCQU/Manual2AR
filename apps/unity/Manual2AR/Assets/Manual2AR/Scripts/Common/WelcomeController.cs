using System;
using System.Collections;
using System.IO;
using UnityEngine;
using UnityEngine.Networking;
using UnityEngine.UI;

namespace Manual2AR {
 [Serializable] public class AppSettings {public string backend_url;}
 [Serializable] public class AppModuleCard {public string id,title,description,scene,api_prefix,status_message;public bool available;}
 [Serializable] public class AppModuleCatalog {public string schema_version;public AppModuleCard[] modules;}
 [Serializable] public class AppService {public string id,title,description,teaching_title,headline,introduction,content_version,source_title,snapshot_version,backend_url;public AppModuleCard[] modules;}
 [Serializable] public class AppServiceCatalog {public string schema_version;public bool import_available;public AppService[] services;}

 /// <summary>One library and one reusable service workspace; neither owns module state.</summary>
 public sealed class WelcomeController:MonoBehaviour {
  Text status;RectTransform root,body;AppSettings settings;AppServiceCatalog catalog;bool connecting;float nextRefresh;
  void Start(){
   Application.targetFrameRate=60;
   var go=new GameObject("Manual2AR Welcome UI",typeof(RectTransform),typeof(Canvas),typeof(CanvasScaler),typeof(GraphicRaycaster));root=(RectTransform)go.transform;
   go.GetComponent<Canvas>().renderMode=RenderMode.ScreenSpaceOverlay;
   var scale=go.GetComponent<CanvasScaler>();scale.uiScaleMode=CanvasScaler.ScaleMode.ScaleWithScreenSize;scale.referenceResolution=new Vector2(1920,1080);scale.matchWidthOrHeight=.5f;
   go.AddComponent<Image>().color=AppTheme.Background;
   try{settings=JsonUtility.FromJson<AppSettings>(File.ReadAllText(Path.Combine(Application.streamingAssetsPath,"App.json")));}catch(Exception){}
   try{catalog=JsonUtility.FromJson<AppServiceCatalog>(File.ReadAllText(Path.Combine(Application.streamingAssetsPath,"Services.json")));}catch(Exception){}
   Render();StartCoroutine(Connect());
  }
  void Update(){if(!connecting&&Time.unscaledTime>=nextRefresh)StartCoroutine(Connect());}
  void OnDestroy(){if(root!=null)Destroy(root.gameObject);}
  public void OpenService(string id){
   if(catalog==null||catalog.services==null)return;
   foreach(var item in catalog.services)if(item.id==id){AppShell.SelectService(item);Render();return;}
  }
  void Library(){AppShell.SelectService(null);Render();}
  void Render(){
   if(body!=null){body.gameObject.SetActive(false);Destroy(body.gameObject);}
   body=AppTheme.Rect(root,"Welcome Content",Vector2.zero,Vector2.one);
   var service=AppShell.SelectedService;
   AppTheme.Label(body,"Manual2AR",new Vector2(.055f,.89f),new Vector2(.60f,.97f),44);
   status=AppTheme.Label(body,"",new Vector2(.70f,.90f),new Vector2(.945f,.96f),22,AppTheme.Muted);status.alignment=TextAnchor.MiddleRight;
   if(service==null)BuildLibrary();else BuildWorkspace(service);
  }
  RectTransform Scroll(Transform parent,string name,Vector2 min,Vector2 max){
   var area=AppTheme.Rect(parent,name,min,max);var view=area.gameObject.AddComponent<ScrollRect>();view.horizontal=false;view.movementType=ScrollRect.MovementType.Clamped;view.scrollSensitivity=35;
   var viewport=AppTheme.Rect(area,"Viewport",Vector2.zero,Vector2.one);viewport.gameObject.AddComponent<RectMask2D>();
   var content=AppTheme.Rect(viewport,"Content",new Vector2(0,1),Vector2.one);content.pivot=new Vector2(.5f,1);
   var layout=content.gameObject.AddComponent<VerticalLayoutGroup>();layout.spacing=20;layout.padding=new RectOffset(4,4,4,10);layout.childControlHeight=true;layout.childForceExpandHeight=false;
   content.gameObject.AddComponent<ContentSizeFitter>().verticalFit=ContentSizeFitter.FitMode.PreferredSize;view.viewport=viewport;view.content=content;return content;
  }
  void BuildLibrary(){
   AppTheme.Label(body,"您的设备教学资料库",new Vector2(.055f,.80f),new Vector2(.93f,.88f),39);
   AppTheme.Label(body,"选择已导入的资料，进入对应设备的教学服务。",new Vector2(.055f,.72f),new Vector2(.945f,.80f),26,AppTheme.Muted);
   var list=Scroll(body,"Service List",new Vector2(.055f,.20f),new Vector2(.945f,.69f));
   if(catalog==null||catalog.services==null||catalog.services.Length==0){AppTheme.Label(list,"暂未加载教学资料，请稍后再试。",Vector2.zero,Vector2.one,27);return;}
   foreach(var service in catalog.services){
    var item=service;var card=AppTheme.Panel(list,"Service "+item.id,Vector2.zero,Vector2.one);card.gameObject.AddComponent<LayoutElement>().preferredHeight=230;
    AppTheme.Label(card,item.title,new Vector2(.035f,.64f),new Vector2(.73f,.90f),35);
    AppTheme.Label(card,item.description,new Vector2(.035f,.36f),new Vector2(.73f,.62f),25,AppTheme.Muted);
    AppTheme.Label(card,"快照版本："+item.snapshot_version,new Vector2(.035f,.10f),new Vector2(.73f,.35f),22,AppTheme.TargetCyan);
    AppTheme.Button(card,"进入教学",new Vector2(.77f,.25f),new Vector2(.965f,.72f),()=>OpenService(item.id),AppIcon.Check,true);
   }
   AppTheme.Label(body,"说明书与 Wiki 资料导入",new Vector2(.055f,.105f),new Vector2(.64f,.165f),25,AppTheme.Muted);
   var import=AppTheme.Button(body,"导入资料 · 即将开放",new Vector2(.70f,.09f),new Vector2(.945f,.16f),()=>{},AppIcon.Info);import.interactable=false;
  }
  void BuildWorkspace(AppService service){
   AppTheme.Label(body,service.teaching_title,new Vector2(.055f,.82f),new Vector2(.94f,.89f),26,AppTheme.Muted);
   AppTheme.Label(body,service.headline,new Vector2(.055f,.69f),new Vector2(.94f,.79f),43);
   AppTheme.Label(body,service.introduction,new Vector2(.055f,.61f),new Vector2(.94f,.69f),27,AppTheme.Muted);
   var list=Scroll(body,"Module Cards",new Vector2(.055f,.21f),new Vector2(.945f,.59f));
   var items=service.modules??new AppModuleCard[0];
   for(int row=0;row<(items.Length+2)/3;row++){
    var line=AppTheme.Rect(list,"Modules Row "+row,Vector2.zero,Vector2.one);line.gameObject.AddComponent<LayoutElement>().preferredHeight=330;
    int columns=Math.Min(3,items.Length-row*3);
    for(int col=0;col<columns;col++){
     int index=row*3+col;var item=items[index];float left=col/(float)columns,right=(col+1)/(float)columns;
     var card=AppTheme.Panel(line,item.id,new Vector2(left+.008f,.02f),new Vector2(right-.008f,.98f));
     AppTheme.Label(card,(index+1).ToString("00"),new Vector2(.075f,.74f),new Vector2(.92f,.92f),34,AppTheme.TargetCyan);
     AppTheme.Label(card,item.title,new Vector2(.075f,.51f),new Vector2(.94f,.74f),34);
     AppTheme.Label(card,item.available?item.description:item.status_message,new Vector2(.075f,.265f),new Vector2(.92f,.51f),24,AppTheme.Muted);
     var button=AppTheme.Button(card,"进入模块",new Vector2(.075f,.07f),new Vector2(.925f,.23f),()=>AppShell.Open(item.scene),AppIcon.Check,true);button.interactable=item.available;
    }
   }
   AppTheme.Label(body,service.source_title+" · 资料版本 "+service.content_version,new Vector2(.055f,.10f),new Vector2(.70f,.17f),23,AppTheme.Muted);
   AppTheme.Button(body,"返回资料库",new Vector2(.77f,.095f),new Vector2(.945f,.16f),Library,AppIcon.Home);
  }
  IEnumerator Connect(){
   nextRefresh=Time.unscaledTime+20;if(settings==null||connecting)yield break;connecting=true;status.text="正在连接…";
   try{using(var request=UnityWebRequest.Get(settings.backend_url.TrimEnd('/')+"/api/app/services")){
    request.timeout=8;yield return request.SendWebRequest();
    if(request.result!=UnityWebRequest.Result.Success){status.text="可浏览已导入资料";yield break;}
    AppServiceCatalog incoming=null;try{incoming=JsonUtility.FromJson<AppServiceCatalog>(request.downloadHandler.text);}catch(Exception){}
    if(incoming==null||incoming.schema_version!="manual2ar-services-v1"||incoming.services==null){status.text="资料服务暂不可用";yield break;}
    catalog=incoming;var selected=AppShell.SelectedService;
    if(selected!=null){AppService match=null;foreach(var item in incoming.services)if(item.id==selected.id)match=item;AppShell.SelectService(match);}
    Render();status.text="教学服务已连接";status.color=AppTheme.SuccessGreen;
   }}finally{connecting=false;}
  }
 }
}
