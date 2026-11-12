using System;
using System.Collections;
using System.Collections.Generic;
using System.Security.Cryptography;
using System.Text;
using UnityEngine;
using UnityEngine.EventSystems;
using UnityEngine.Networking;
using UnityEngine.UI;
using Manual2AR.Spatial;
using Manual2AR.VisualGuidance;

namespace Manual2AR {
 public sealed class U7DemoView:MonoBehaviour {
  [Serializable] class Scene {public string id,title,sha256,url;}
  [Serializable] class Catalog {public string task_sha256,scope,mode_notice;public string[] questions;public Scene[] scenes;public GoalStep[] official_steps;public AssetLibraryDescriptor asset_library;}
  [Serializable] class GoalStep {public string node_id,instruction;public bool prerequisite_only;}
  [Serializable] class Reply {public string mode,source_sha256,observation_notice,placement_notice;public TaskExecution execution;public GoalStep[] official_steps;}
  [Serializable] class StartCommand {public string intent,mode;}
  [Serializable] class Command {public string session_id,task_sha256,source_sha256,scene_id="",image_base64="";public int epoch,revision;}
  [Serializable] class ManualCommand {public string session_id,task_sha256,source_sha256;public int epoch,revision;public string[] condition_ids;public bool confirmed=true;}
  [Serializable] class ArCommand {public string session_id,task_sha256,source_sha256;public int epoch,revision;public float anchor_x=.45f,anchor_y=.34f;}
  [Serializable] class Illustration {public string session_id,task_sha256,source_sha256,action_id;public int epoch,revision,width,height;public bool illustrative_only;public VisualPresentation presentation;public SpatialProjection projection;}
  [Serializable] class Failure {public string detail;}
  const string Api="/api/guidance/u7-demo";
  string origin,sceneId="",photoSha="",guidedAction="";Action done;
  RectTransform root,photoRect;Text feedback,notice,phase;InputField question;Dropdown modes,photos,examples;
  Button action,cameraButton,captureButton,reset;RawImage image;Texture2D texture;SpatialCamera cameraOwner;
  SpatialAssetGraphic graphic;Catalog catalog;Reply reply;Illustration illustration;AppDialog dialog;
  byte[] captured;int generation,captureVersion,submittedVersion=-1;bool busy,closed;float previewAt,animationAt;
  readonly HashSet<UnityWebRequest> requests=new HashSet<UnityWebRequest>();
  bool Scripted {get{return modes.value==0;}}

  public static U7DemoView Open(string backend,Action onClose){
   var view=new GameObject("U7 Demonstration").AddComponent<U7DemoView>();view.origin=backend.TrimEnd('/');view.done=onClose;view.Build();view.StartCoroutine(view.Load());return view;
  }
  void Build(){
   root=AppWorkspace.Canvas(transform,"U7 Demo workspace",30);var w=new AppWorkspace(root,"提问及拍摄现场生成AR指导 · U7");
   AppTheme.Button(root,"返回任务列表",AppWorkspace.BackMin,AppWorkspace.BackMax,Close,AppIcon.Back);
   modes=AppDropdown.Create(w.Tools,"Demo evidence mode",new Vector2(0,0),new Vector2(.27f,1),_=>ChangeMode());
   modes.AddOptions(new List<string>{"历史照片演示（预设）","实时拍摄（真实模型）"});
   photos=AppDropdown.Create(w.Tools,"Demo photo selection",new Vector2(.29f,0),new Vector2(.66f,1),_=>{
    if(Scripted&&catalog!=null)StartCoroutine(LoadScene());else {ResetSession();cameraOwner.Close();ClearPhoto();phase.text="摄像头已更换，请重新拍摄并生成计划。";}
   });
   cameraButton=AppTheme.Button(w.Tools,"启动相机",new Vector2(.68f,0),new Vector2(.84f,1),()=>StartCoroutine(StartCamera()),AppIcon.Camera);
   captureButton=AppTheme.Button(w.Tools,"拍摄现场",new Vector2(.86f,0),Vector2.one,Capture,AppIcon.Camera,true);
   photoRect=AppTheme.Rect(w.Main,"Demo photo plane",Vector2.zero,Vector2.one);photoRect.gameObject.AddComponent<AspectRatioFitter>().aspectMode=AspectRatioFitter.AspectMode.FitInParent;
   photoRect.gameObject.AddComponent<RectMask2D>();
   image=AppTheme.Rect(photoRect,"Demo photo",Vector2.zero,Vector2.one).gameObject.AddComponent<RawImage>();image.color=Color.clear;
   graphic=AppTheme.Rect(photoRect,"Existing U7 animation",Vector2.zero,Vector2.one).gameObject.AddComponent<SpatialAssetGraphic>();graphic.raycastTarget=false;
   var trigger=photoRect.gameObject.AddComponent<EventTrigger>();var click=new EventTrigger.Entry{eventID=EventTriggerType.PointerClick};
   click.callback.AddListener(data=>{
    if(busy||illustration==null||reply==null)return;Vector2 local;var pointer=(PointerEventData)data;
    if(RectTransformUtility.ScreenPointToLocalPointInRectangle(photoRect,pointer.position,pointer.pressEventCamera,out local)){
     var rect=photoRect.rect;StartCoroutine(ShowAR(Mathf.Clamp((local.x-rect.xMin)/rect.width,.05f,.95f),Mathf.Clamp(1-(local.y-rect.yMin)/rect.height,.05f,.95f)));
    }
   });trigger.triggers.Add(click);
   AppMediaEmptyState.Attach(w.Main,image,"选择历史照片，或启动摄像头拍摄现场");
   AppTheme.Label(w.Aside,"你希望完成什么？",new Vector2(.05f,.92f),new Vector2(.95f,.98f),26,AppTheme.TargetCyan);
   var field=AppTheme.Panel(w.Aside,"Demo question",new Vector2(.05f,.77f),new Vector2(.95f,.91f));
   question=field.gameObject.AddComponent<InputField>();question.targetGraphic=field.GetComponent<Image>();question.characterLimit=1000;question.lineType=InputField.LineType.MultiLineNewline;
   question.textComponent=AppTheme.Label(field,"",new Vector2(.03f,.04f),new Vector2(.97f,.96f),25);question.textComponent.supportRichText=false;
   question.placeholder=AppTheme.Label(field,"例如：安装料盘支架",new Vector2(.03f,.04f),new Vector2(.97f,.96f),23,AppTheme.Muted);
   examples=AppDropdown.Create(w.Aside,"Demo question examples",new Vector2(.05f,.67f),new Vector2(.95f,.75f),i=>{if(catalog!=null&&i<catalog.questions.Length)question.text=catalog.questions[i];});
   phase=AppTheme.Label(w.Aside,"正在读取演示资料…",new Vector2(.05f,.57f),new Vector2(.95f,.65f),24,AppTheme.TargetCyan);
   var body=AppContent.Scroll(w.Aside,"Demo plan and progress",new Vector2(.05f,.17f),new Vector2(.95f,.56f));
   feedback=AppContent.Paragraph(body,"",25);AppReadableText.Attach(feedback);
   AppTheme.Button(w.Aside,"查看官方步骤",new Vector2(.05f,.035f),new Vector2(.95f,.14f),ShowSources,AppIcon.Info);
   reset=AppTheme.Button(w.FooterLeft,"重新选择目标",Vector2.zero,Vector2.one,()=>{ResetSession();phase.text="请输入目标，提供照片后生成计划。";},AppIcon.Back);
   action=AppTheme.Button(w.FooterRight,"生成AR指导",Vector2.zero,Vector2.one,MainAction,AppIcon.Check,true);
   AppActionBar.Add(w.FooterLeft,reset);AppActionBar.Add(w.FooterRight,action);
   notice=AppTheme.Label(root,"已审核U7任务 · 历史照片预设观察（演示）",new Vector2(.025f,.105f),new Vector2(.975f,.13f),19,AppTheme.Muted);
   cameraOwner=gameObject.AddComponent<SpatialCamera>();
   question.onValueChanged.AddListener(_=>{if(reply!=null)ResetSession();});
   question.text="安装料盘支架";AppShell.BindBack("返回任务列表",Close,()=>!busy);Refresh();
  }
  IEnumerator Load(){
   busy=true;yield return Request(Api+"/catalog","GET",null,(raw,error)=>{
    if(error!=null){SetFeedback(error);return;}catalog=JsonUtility.FromJson<Catalog>(raw);
    if(!VisualAssetLibrary.Matches(catalog.asset_library)){catalog=null;SetFeedback("资产版本不一致，请更新客户端和后端。");return;}
    examples.ClearOptions();examples.AddOptions(new List<string>(Array.ConvertAll(catalog.questions,q=>"示例："+q)));SetPhotoOptions();
   });busy=false;
   if(catalog!=null)yield return LoadScene();Refresh();
  }
  void SetPhotoOptions(){
   photos.ClearOptions();var names=new List<string>();
   if(Scripted){foreach(var scene in catalog.scenes)names.Add(scene.title);}else{foreach(var device in WebCamTexture.devices)names.Add(device.name);}
   if(names.Count==0)names.Add(Scripted?"演示素材未准备":"未发现摄像头");photos.AddOptions(names);photos.SetValueWithoutNotify(0);photos.RefreshShownValue();
  }
  void ChangeMode(){if(cameraOwner==null)return;ResetSession();cameraOwner.Close();ClearPhoto();if(catalog!=null){SetPhotoOptions();if(Scripted)StartCoroutine(LoadScene());}Refresh();}
  void ClearPhoto(){captured=null;photoSha=sceneId="";illustration=null;graphic.Clear();image.texture=null;image.color=Color.clear;if(texture!=null){Destroy(texture);texture=null;}}
  void ShowPhoto(byte[] raw){
   illustration=null;graphic.Clear();if(texture!=null)Destroy(texture);texture=new Texture2D(2,2);
   if(!texture.LoadImage(raw)){Destroy(texture);texture=null;SetFeedback("照片无法显示。");return;}
   image.texture=texture;image.color=Color.white;photoRect.GetComponent<AspectRatioFitter>().aspectRatio=texture.width/(float)texture.height;
  }
  IEnumerator LoadScene(){
   if(busy||catalog==null||catalog.scenes.Length==0)yield break;
   int version=++generation;var scene=catalog.scenes[photos.value];busy=true;
   using(var get=UnityWebRequest.Get(origin+scene.url)){
    requests.Add(get);yield return get.SendWebRequest();requests.Remove(get);
    if(closed||version!=generation)yield break;
    if(get.result!=UnityWebRequest.Result.Success){SetFeedback("历史照片未能载入，请重新选择。");}
    else if(Hash(get.downloadHandler.data)!=scene.sha256){SetFeedback("演示照片校验失败。");}
    else{captured=get.downloadHandler.data;photoSha=scene.sha256;sceneId=scene.id;captureVersion++;ShowPhoto(captured);phase.text=reply==null?"照片已准备，可生成计划。":"照片已更换，请核验当前步骤。";}
   }
   busy=false;Refresh();
  }
  IEnumerator StartCamera(){
   if(Scripted||busy)yield break;busy=true;ClearPhoto();string failure=null;yield return cameraOwner.Open(photos.value,e=>failure=e);
   if(failure!=null)SetFeedback(failure);else phase.text="请拍摄打印机及待安装部件。";busy=false;Refresh();
  }
  void Capture(){if(busy||Scripted)return;var raw=cameraOwner.Capture();if(raw==null){SetFeedback("尚未取得新画面，请稍候再拍。");return;}
   captured=raw;photoSha=Hash(raw);sceneId="";captureVersion++;cameraOwner.Close();ShowPhoto(raw);phase.text="照片已拍摄，请生成计划或核验。";Refresh();
  }
  void MainAction(){
   if(busy||catalog==null)return;
   if(reply==null){StartCoroutine(Generate());return;}
   var state=reply.execution;
   if(state.complete){ResetSession();phase.text="可以更换目标或照片，开始下一次演示。";return;}
   if(reply.source_sha256!=photoSha){StartCoroutine(Observe());return;}
   if(state.baseline_mode=="ask_manual"){ShowManual();return;}
   if(state.guidance_ready&&guidedAction!=state.action_id){StartCoroutine(ShowAR(.45f,.34f));return;}
   StartCoroutine(Observe());
  }
  IEnumerator Generate(){
   if(captured==null||string.IsNullOrWhiteSpace(question.text))yield break;busy=true;phase.text="正在匹配已审核的官方任务…";
   yield return Request(Api+"/sessions","POST",JsonUtility.ToJson(new StartCommand{intent=question.text.Trim(),mode=Scripted?"scripted":"live"}),(raw,error)=>{if(error!=null)SetFeedback(error);else Apply(JsonUtility.FromJson<Reply>(raw));});
   busy=false;if(reply!=null)yield return Observe();Refresh();
  }
  Command Stamp(){var e=reply.execution;return new Command{session_id=e.session_id,task_sha256=e.task_sha256,epoch=e.epoch,revision=e.revision,source_sha256=photoSha};}
  IEnumerator Observe(){
   if(reply==null||captured==null||busy)yield break;
   if(!Scripted&&captureVersion<=submittedVersion){SetFeedback("请重新拍摄操作后的现场，再点击核验。");yield break;}
   busy=true;phase.text=Scripted?"正在载入预设观察并规划…":"正在核验照片，请稍候…";
   var command=Stamp();command.scene_id=Scripted?sceneId:"";command.image_base64=Scripted?"":Convert.ToBase64String(captured);int sentVersion=captureVersion;
   yield return Request(Api+"/sessions/"+reply.execution.session_id+"/photo","POST",JsonUtility.ToJson(command),(raw,error)=>{
    if(error!=null){SetFeedback(error);return;}var result=JsonUtility.FromJson<Reply>(raw);
    if(result.source_sha256!=photoSha){SetFeedback("照片已改变，请重拍后核验。");return;}submittedVersion=sentVersion;Apply(result);
   },300);busy=false;Refresh();
  }
  void Apply(Reply value){
   if(value==null||catalog==null||value.mode!=(Scripted?"scripted":"live")||value.execution.task_sha256!=catalog.task_sha256){SetFeedback("任务版本不一致，请重新打开演示。");return;}
   if(reply==null||reply.execution.action_id!=value.execution.action_id)guidedAction="";
   phase.color=value.execution.complete?AppTheme.SuccessGreen:AppTheme.TargetCyan;
   reply=value;illustration=null;graphic.Clear();phase.text=value.execution.complete?"本次目标已完成":value.execution.baseline_mode=="ask_manual"?"请核实人工项目":value.execution.baseline_mode=="request_view"?"需要补充照片":"接下来完成当前操作";
   var text=new StringBuilder(value.execution.user_summary);text.Append("\n\n").Append(value.execution.user_feedback);
   if(!value.execution.complete)text.Append("\n\n当前操作：").Append(value.execution.current_step);
   SetFeedback(text.ToString());Refresh();
  }
  void ShowManual(){
   CloseDialog();var token=reply;dialog=AppDialog.Open(root,"U7 demo manual confirmation","请核实当前操作",AppDialogSize.Large,CloseDialog);
   var panel=dialog.Panel;var text=new StringBuilder("照片检查已通过。请核实：");
   for(int i=0;i<token.execution.manual_conditions.Length;i++)text.Append("\n\n").Append(i+1).Append("．").Append(token.execution.manual_conditions[i].statement);
   var body=AppContent.Scroll(panel,"Demo manual items",new Vector2(.06f,.36f),new Vector2(.94f,.85f));AppContent.Paragraph(body,text.ToString(),26);
   Button accept=null;var area=AppTheme.Panel(panel,"Demo manual acknowledgment",new Vector2(.06f,.23f),new Vector2(.94f,.33f));var toggle=area.gameObject.AddComponent<Toggle>();toggle.targetGraphic=area.GetComponent<Image>();
   var box=AppTheme.Panel(area,"Checkbox",new Vector2(.01f,.05f),new Vector2(.07f,.95f));box.GetComponent<Image>().color=AppTheme.ButtonBackground;
   var mark=AppTheme.Label(box,"✓",Vector2.zero,Vector2.one,28,AppTheme.TargetCyan);mark.alignment=TextAnchor.MiddleCenter;toggle.graphic=mark;
   AppTheme.Label(area,Scripted?"以上项目已核实（演示确认）":"以上项目已实际核实",new Vector2(.1f,0),Vector2.one,25);
   accept=AppTheme.Button(panel,"确认并继续",new Vector2(.06f,.05f),new Vector2(.62f,.18f),()=>{CloseDialog();StartCoroutine(Confirm(token));},AppIcon.Check,true);accept.interactable=false;
   toggle.isOn=false;toggle.onValueChanged.AddListener(value=>accept.interactable=value);
   AppTheme.Button(panel,"暂不确认",new Vector2(.65f,.05f),new Vector2(.94f,.18f),CloseDialog,AppIcon.Close);
  }
  IEnumerator Confirm(Reply token){
   if(busy||reply!=token)yield break;busy=true;
   var e=token.execution;var command=new ManualCommand{session_id=e.session_id,task_sha256=e.task_sha256,epoch=e.epoch,revision=e.revision,source_sha256=token.source_sha256,condition_ids=Array.ConvertAll(e.manual_conditions,c=>c.id)};
   yield return Request(Api+"/sessions/"+e.session_id+"/manual","POST",JsonUtility.ToJson(command),(raw,error)=>{if(error!=null)SetFeedback(error);else Apply(JsonUtility.FromJson<Reply>(raw));});busy=false;Refresh();
  }
  IEnumerator ShowAR(float x,float y){
   if(busy||reply==null)yield break;busy=true;var e=reply.execution;
   if(reply.source_sha256!=photoSha){SetFeedback("请先核验当前照片，再显示本步示意。");busy=false;yield break;}
   var command=new ArCommand{session_id=e.session_id,task_sha256=e.task_sha256,epoch=e.epoch,revision=e.revision,source_sha256=photoSha,anchor_x=x,anchor_y=y};
   yield return Request(Api+"/sessions/"+e.session_id+"/ar","POST",JsonUtility.ToJson(command),(raw,error)=>{
    if(error!=null){SetFeedback(error);return;}var value=JsonUtility.FromJson<Illustration>(raw);
    if(value.source_sha256!=photoSha||value.session_id!=e.session_id||value.task_sha256!=e.task_sha256||value.epoch!=e.epoch||value.action_id!=e.action_id||value.revision!=e.revision||!value.illustrative_only||!VisualAssetLibrary.Validate(value.presentation)){SetFeedback("动画与当前照片或任务不一致。");return;}
    illustration=value;guidedAction=e.action_id;animationAt=Time.realtimeSinceStartup;phase.text="请按示意操作，完成后拍照核验。";
    SetFeedback(e.current_step+"\n\n照片上的动画示意，可点击画面调整位置。\n完成后提供新照片，再点击“拍照核验”。");
   });busy=false;Refresh();
  }
  void ShowSources(){
   var steps=reply?.official_steps??catalog?.official_steps;
   if(steps==null||steps.Length==0){SetFeedback("官方步骤尚未载入，请稍后重试。");return;}
   CloseDialog();dialog=AppDialog.Open(root,"U7 official steps","已审核 U7 教材与官方步骤",AppDialogSize.Large,CloseDialog);
   var body=AppContent.Scroll(dialog.Panel,"Demo official steps",new Vector2(.06f,.22f),new Vector2(.94f,.85f));
   if(reply==null)AppContent.Paragraph(body,"U7 完整操作流程，可先浏览再生成计划。",23,AppTheme.Muted);
   foreach(var step in steps)AppContent.Paragraph(body,(step.prerequisite_only?"必要前置：":"操作：")+step.instruction,26);
   AppContent.Paragraph(body,"本演示读取预编译、已审核的U7任务，不现场重新编译资料。",22,AppTheme.Muted);
   AppTheme.Button(dialog.Panel,"返回当前任务",new Vector2(.1f,.05f),new Vector2(.9f,.18f),CloseDialog,AppIcon.Back);
  }
  void Update(){
   if(closed)return;
   if(!Scripted&&cameraOwner.Ready&&Time.realtimeSinceStartup>=previewAt){previewAt=Time.realtimeSinceStartup+.12f;var raw=cameraOwner.Capture();if(raw!=null)ShowPhoto(raw);}
   if(illustration!=null){var p=illustration.projection;var frame=new VisualRenderFrame{ReferenceSpaceId=illustration.presentation.reference_space_id,SourceSha256=illustration.source_sha256,Width=illustration.width,Height=illustration.height,CameraFromReference=p.camera_from_marker,Intrinsics=p.intrinsics,Distortion=p.distortion,HasWorldPlacement=false};
    graphic.Present(illustration.presentation,frame,Mathf.Repeat((Time.realtimeSinceStartup-animationAt)/illustration.presentation.duration_seconds,1));}
   Refresh();
  }
  void Refresh(){
   if(action==null)return;bool ready=catalog!=null&&!busy;
   modes.interactable=photos.interactable=examples.interactable=question.interactable=reset.interactable=ready;
   cameraButton.gameObject.SetActive(!Scripted);captureButton.gameObject.SetActive(!Scripted);
   var selector=(RectTransform)photos.transform;float end=Scripted?1:.66f;if(selector.anchorMax.x!=end)selector.anchorMax=new Vector2(end,1);
   cameraButton.interactable=ready&&!Scripted;captureButton.interactable=ready&&!Scripted&&cameraOwner!=null&&cameraOwner.Ready;
   action.interactable=ready&&captured!=null&&!string.IsNullOrWhiteSpace(question.text);
   string label=reply==null?"生成AR指导":reply.execution.complete?"开始下一次演示":reply.source_sha256!=photoSha?"核验当前照片":reply.execution.baseline_mode=="ask_manual"?"核实并确认":reply.execution.guidance_ready&&guidedAction!=reply.execution.action_id?"播放本步AR示意":reply.execution.baseline_mode=="request_view"?"重新评估现场":"拍照核验";
   action.GetComponentInChildren<Text>().text=AppTheme.Readable(busy?"处理中…":label);
   notice.text=AppTheme.Readable("已审核U7任务 · "+(Scripted?"历史照片预设观察（演示，不计入实验）":"真实模型观察")+" · 照片示意定位");
  }
  void SetFeedback(string value){feedback.text=AppTheme.Readable(value);}
  void CloseDialog(){if(dialog!=null){var old=dialog;dialog=null;old.Close();}}
  void ResetSession(){
   CloseDialog();generation++;illustration=null;graphic.Clear();guidedAction="";submittedVersion=-1;
   var previous=reply;reply=null;if(previous!=null)StartCoroutine(Request(Api+"/sessions/"+previous.execution.session_id,"DELETE",null,(raw,error)=>{}));SetFeedback("目标改变后将建立新会话，重新判断进度。");Refresh();
  }
  static string Hash(byte[] raw){using(var digest=SHA256.Create())return BitConverter.ToString(digest.ComputeHash(raw)).Replace("-","").ToLowerInvariant();}
  IEnumerator Request(string path,string method,string body,Action<string,string> receive,int timeout=30){
   int version=generation;using(var request=new UnityWebRequest(origin+path,method)){
    request.downloadHandler=new DownloadHandlerBuffer();if(body!=null){request.uploadHandler=new UploadHandlerRaw(Encoding.UTF8.GetBytes(body));request.SetRequestHeader("Content-Type","application/json");}
    request.timeout=timeout;requests.Add(request);yield return request.SendWebRequest();requests.Remove(request);
    if(closed||version!=generation)yield break;
    if(request.result==UnityWebRequest.Result.Success)receive(request.downloadHandler.text,null);
    else {string error="请求未完成，请重试。";try{var value=JsonUtility.FromJson<Failure>(request.downloadHandler.text);if(!string.IsNullOrEmpty(value.detail))error=value.detail;}catch(ArgumentException){}if(method!="DELETE"){phase.text="请求未完成，可调整后重试。";phase.color=AppTheme.TargetCyan;}receive(null,error);}
   }
  }
  void Close(){if(closed)return;StartCoroutine(Finish());}
  IEnumerator Finish(){
   busy=true;closed=true;generation++;foreach(var pending in new List<UnityWebRequest>(requests))pending.Abort();cameraOwner.Close();CloseDialog();if(reply!=null)yield return Request(Api+"/sessions/"+reply.execution.session_id,"DELETE",null,(raw,error)=>{});
   closed=true;foreach(var request in requests)request.Abort();requests.Clear();if(texture!=null)Destroy(texture);Destroy(gameObject);done?.Invoke();
  }
  void OnDestroy(){closed=true;cameraOwner?.Close();foreach(var request in requests)request.Abort();requests.Clear();if(texture!=null)Destroy(texture);}
 }
}
