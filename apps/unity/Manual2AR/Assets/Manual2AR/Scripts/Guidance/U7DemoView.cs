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
  [Serializable] class FlowStep {public string node_id,title,status;public bool prerequisite_only;}
  [Serializable] class DemoFlow {public string phase,goal,scene_summary,next_action;public FlowStep[] steps;}
  [Serializable] class ObservationHint {public string condition_id,statement,reason,instruction;}
  [Serializable] class PlanAction {public string mode,node_id;public ObservationHint[] observation_hints;}
  [Serializable] class RemainingPlan {public string schema_version,session_id,task_sha256;public int epoch,revision;public PlanAction current_action;}
  [Serializable] class Reply {public string mode,source_sha256,observation_notice,placement_notice;public TaskExecution execution;public GoalStep[] official_steps;public DemoFlow demo_flow;public RemainingPlan remaining_plan;}
  [Serializable] class GoalChoice {public string title;public string[] selected_node_ids;}
  [Serializable] class GoalPreview {public string status,task_sha256;public GoalChoice[] candidates;}
  [Serializable] class StartCommand {public string intent,mode;}
  [Serializable] class Command {public string session_id,task_sha256,source_sha256,scene_id="",image_base64="";public int epoch,revision;}
  [Serializable] class ManualCommand {public string session_id,task_sha256,source_sha256;public int epoch,revision;public string[] condition_ids;public bool confirmed=true;}
  [Serializable] class ArCommand {public string session_id,task_sha256,source_sha256;public int epoch,revision;public float anchor_x=.45f,anchor_y=.34f;}
  [Serializable] class Illustration {public string session_id,task_sha256,source_sha256,action_id;public int epoch,revision,width,height;public bool illustrative_only;public VisualPresentation presentation;public SpatialProjection projection;}
  [Serializable] class Failure {public string detail;}
  const string Api="/api/guidance/u7-demo";
  string origin,sceneId="",photoSha="",guidedAction="";Action done;
  RectTransform root,photoRect,feedbackArea;Text feedback,notice,phase,goalHeading;InputField question;Dropdown modes,photos,examples;
  Button action,cameraButton,captureButton,reset,replayButton,sourcesButton;RawImage image;Texture2D texture;SpatialCamera cameraOwner;
  SpatialAssetGraphic graphic;Catalog catalog;Reply reply;Illustration illustration;AppDialog dialog;
  byte[] captured;int generation,captureVersion,submittedVersion=-1;bool busy,closed,previewing;float previewAt,animationAt;
  readonly HashSet<UnityWebRequest> requests=new HashSet<UnityWebRequest>();
  bool Scripted {get{return modes.value==0;}}

  public static U7DemoView Open(string backend,Action onClose){
   var view=new GameObject("U7 Demonstration").AddComponent<U7DemoView>();view.origin=backend.TrimEnd('/');view.done=onClose;view.Build();view.StartCoroutine(view.Load());return view;
  }
  void Build(){
   root=AppWorkspace.Canvas(transform,"U7 Demo workspace",30);var w=new AppWorkspace(root,"提问及拍摄现场生成AR指导 · U7");
   AppWorkspace.Place(w.Main,.025f,.13f,.64f,.815f);AppWorkspace.Place(w.Aside,.66f,.13f,.975f,.815f);
   AppTheme.Button(root,"返回任务列表",AppWorkspace.BackMin,AppWorkspace.BackMax,Close,AppIcon.Back);
   modes=AppDropdown.Create(w.Tools,"Demo evidence mode",new Vector2(0,0),new Vector2(.27f,1),_=>ChangeMode());
   modes.AddOptions(new List<string>{"历史照片演示（预设）","实时拍摄（真实模型）"});
   photos=AppDropdown.Create(w.Tools,"Demo photo selection",new Vector2(.29f,0),new Vector2(.66f,1),_=>{
    if(Scripted&&catalog!=null)StartCoroutine(LoadScene());else {ResetSession();cameraOwner.Close();previewing=false;ClearPhoto();phase.text="目标与现场";SetFeedback("摄像头已更换。请启动相机并拍摄现场。");}
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
   goalHeading=AppTheme.Label(w.Aside,"本次目标",new Vector2(.05f,.92f),new Vector2(.95f,.98f),26,AppTheme.TargetCyan);
   var field=AppTheme.Panel(w.Aside,"Demo question",new Vector2(.05f,.77f),new Vector2(.95f,.91f));
   question=field.gameObject.AddComponent<InputField>();question.targetGraphic=field.GetComponent<Image>();question.characterLimit=1000;question.lineType=InputField.LineType.MultiLineNewline;
   question.textComponent=AppTheme.Label(field,"",new Vector2(.03f,.04f),new Vector2(.97f,.96f),25);question.textComponent.supportRichText=false;
   question.placeholder=AppTheme.Label(field,"例如：安装料盘支架",new Vector2(.03f,.04f),new Vector2(.97f,.96f),23,AppTheme.Muted);
   examples=AppDropdown.Create(w.Aside,"Demo question examples",new Vector2(.05f,.67f),new Vector2(.95f,.75f),i=>{if(catalog!=null&&i<catalog.questions.Length)question.text=catalog.questions[i];});
   phase=AppTheme.Label(w.Aside,"正在读取演示资料…",new Vector2(.05f,.57f),new Vector2(.95f,.65f),24,AppTheme.TargetCyan);
   var body=AppContent.Scroll(w.Aside,"Demo plan and progress",new Vector2(.05f,.17f),new Vector2(.95f,.56f));
   feedbackArea=(RectTransform)body.parent.parent;
   feedback=AppContent.Paragraph(body,"",25);AppReadableText.Attach(feedback);
   sourcesButton=AppTheme.Button(w.Aside,"官方步骤",new Vector2(.05f,.035f),new Vector2(.49f,.14f),ShowSources,AppIcon.Info);
   replayButton=AppTheme.Button(w.Aside,"重播本步",new Vector2(.52f,.035f),new Vector2(.95f,.14f),()=>StartCoroutine(ShowAR(.45f,.34f)),AppIcon.Play);
   reset=AppTheme.Button(w.FooterLeft,"重新选择目标",Vector2.zero,Vector2.one,ResetSession,AppIcon.Back);
   action=AppTheme.Button(w.FooterRight,"评估现场并生成计划",Vector2.zero,Vector2.one,MainAction,AppIcon.Check,true);
   AppActionBar.Add(w.FooterLeft,reset);AppActionBar.Add(w.FooterRight,action);
   notice=AppTheme.Label(root,"已审核U7任务 · 历史照片预设观察（演示）",new Vector2(.025f,.105f),new Vector2(.975f,.13f),19,AppTheme.Muted);
   cameraOwner=gameObject.AddComponent<SpatialCamera>();
   question.onValueChanged.AddListener(_=>{if(reply!=null)ResetSession();});
   question.text="安装料盘支架";AppShell.BindBack("返回任务列表",Close,()=>!closed);Refresh();
  }
  IEnumerator Load(){
   int version=generation;busy=true;yield return Request(Api+"/catalog","GET",null,(raw,error)=>{
    if(error!=null){SetFeedback(error);return;}catalog=JsonUtility.FromJson<Catalog>(raw);
    if(catalog==null||catalog.questions==null||catalog.scenes==null||!VisualAssetLibrary.Matches(catalog.asset_library)){catalog=null;phase.text="演示资料未能载入";SetFeedback("资产或资料格式不一致，请更新客户端和后端。");return;}
    examples.ClearOptions();examples.AddOptions(new List<string>(Array.ConvertAll(catalog.questions,q=>"示例："+q)));SetPhotoOptions();
   });if(closed||version!=generation)yield break;busy=false;
   if(catalog!=null&&Scripted)yield return LoadScene();Refresh();
  }
  void SetPhotoOptions(){
   photos.ClearOptions();var names=new List<string>();
   if(Scripted){foreach(var scene in catalog.scenes)names.Add(scene.title);}else{foreach(var device in WebCamTexture.devices)names.Add(device.name);}
   if(names.Count==0)names.Add(Scripted?"演示素材未准备":"未发现摄像头");photos.AddOptions(names);photos.SetValueWithoutNotify(0);photos.RefreshShownValue();
  }
  void ChangeMode(){if(cameraOwner==null)return;ResetSession();cameraOwner.Close();previewing=false;ClearPhoto();phase.text="目标与现场";if(catalog!=null){SetPhotoOptions();if(Scripted)StartCoroutine(LoadScene());else SetFeedback("请选择摄像头，启动后手动拍摄现场。");}Refresh();}
  void ClearPhoto(){captured=null;photoSha=sceneId="";illustration=null;graphic.Clear();image.texture=null;image.color=Color.clear;if(texture!=null){Destroy(texture);texture=null;}}
  void ShowPhoto(byte[] raw){
   illustration=null;graphic.Clear();if(texture!=null)Destroy(texture);texture=new Texture2D(2,2);
   if(!texture.LoadImage(raw)){ClearPhoto();SetFeedback("照片无法显示，请重新载入或拍摄。");return;}
   image.texture=texture;image.color=Color.white;photoRect.GetComponent<AspectRatioFitter>().aspectRatio=texture.width/(float)texture.height;
  }
  IEnumerator LoadScene(){
   if(busy||catalog==null||catalog.scenes.Length==0)yield break;
   int version=++generation;var scene=catalog.scenes[photos.value];busy=true;CloseDialog();ClearPhoto();phase.text="正在载入照片…";
   using(var get=UnityWebRequest.Get(origin+scene.url)){
    get.timeout=30;requests.Add(get);yield return get.SendWebRequest();requests.Remove(get);
    if(closed||version!=generation)yield break;
    if(get.result!=UnityWebRequest.Result.Success){phase.text="照片未载入，可重试";SetFeedback("历史照片未能载入，请点击“重新载入照片”。");}
    else if(Hash(get.downloadHandler.data)!=scene.sha256){phase.text="照片校验失败";SetFeedback("演示照片与记录不一致，请重新准备素材。");}
    else{captured=get.downloadHandler.data;photoSha=scene.sha256;sceneId=scene.id;captureVersion++;ShowPhoto(captured);phase.text=reply==null?"目标与现场":"新照片待核验";SetFeedback(reply==null?"照片已准备。填写目标后，评估现场并生成计划。":"照片已更换。请核验当前照片，更新现场结果和进度。");}
   }
   busy=false;Refresh();
  }
  IEnumerator StartCamera(){
   if(Scripted||busy)yield break;int version=generation;busy=true;previewing=false;ClearPhoto();string failure=null;yield return cameraOwner.Open(photos.value,e=>failure=e);
   if(closed||version!=generation)yield break;previewing=failure==null;
   phase.text=previewing?"正在取景 · 尚未拍摄":"相机未启动";SetFeedback(failure??"对准打印机及安装位置，点击“拍摄现场”。取景不会自动核验。");busy=false;Refresh();
  }
  void Capture(){if(busy||Scripted||!previewing)return;var raw=cameraOwner.Capture();if(raw==null){SetFeedback("尚未取得新画面，请稍候再拍。");return;}
   captured=raw;photoSha=Hash(raw);sceneId="";captureVersion++;previewing=false;cameraOwner.Close();ShowPhoto(raw);phase.text=reply==null?"目标与现场":"新照片待核验";SetFeedback(reply==null?"照片已拍摄。点击评估现场，生成本次计划。":"照片已拍摄。点击核验，检查操作后的结果。");Refresh();
  }
  void MainAction(){
   if(busy||previewing)return;
   if(catalog==null){StartCoroutine(Load());return;}
   if(captured==null){if(Scripted)StartCoroutine(catalog.scenes.Length==0?Load():LoadScene());return;}
   if(reply==null){StartCoroutine(Generate());return;}
   var state=reply.execution;
   if(state.complete){ResetSession();return;}
   if(NeedsFreshPhoto())return;
   if(reply.source_sha256!=photoSha){StartCoroutine(Observe());return;}
   if(state.baseline_mode=="ask_manual"){ShowManual();return;}
   if(state.guidance_ready&&guidedAction!=state.action_id){StartCoroutine(ShowAR(.45f,.34f));return;}
   StartCoroutine(Observe());
  }
  IEnumerator Generate(){
   if(previewing||captured==null||string.IsNullOrWhiteSpace(question.text))yield break;int version=generation;busy=true;phase.text="正在匹配已审核的官方任务…";
   string intent=question.text.Trim();var command=JsonUtility.ToJson(new StartCommand{intent=intent,mode=Scripted?"scripted":"live"});GoalPreview preview=null;
   yield return Request(Api+"/goal-preview","POST",command,(raw,error)=>{if(error!=null)SetFeedback(error);else preview=JsonUtility.FromJson<GoalPreview>(raw);});
   if(closed||version!=generation)yield break;
   if(preview==null){busy=false;Refresh();yield break;}
   if(preview.task_sha256!=catalog.task_sha256){busy=false;phase.text="任务版本不一致";SetFeedback("请重新打开演示，载入当前任务资料。");Refresh();yield break;}
   if(preview.status!="matched"){
    busy=false;phase.text="请明确本次目标";
    SetFeedback("尚未确定任务范围。请选择官方任务，或改写目标后重试。");
    if(preview.candidates!=null&&preview.candidates.Length>0)ShowGoalChoices(preview.candidates,intent);
    else SetFeedback("当前演示支持：安装料盘支架、安装支架底座、滑入料盘支架。请明确要完成的操作。");
    Refresh();yield break;
   }
   yield return Request(Api+"/sessions","POST",command,(raw,error)=>{if(error!=null)SetFeedback(error);else Apply(JsonUtility.FromJson<Reply>(raw));});
   if(closed||version!=generation)yield break;busy=false;if(reply!=null)yield return Observe();Refresh();
  }
  void ShowGoalChoices(GoalChoice[] choices,string intent){
   CloseDialog();int version=generation;dialog=AppDialog.Open(root,"U7 goal choices","你希望完成哪项任务？",AppDialogSize.Large,CloseDialog);
   var body=AppContent.Scroll(dialog.Panel,"Demo goal candidates",new Vector2(.06f,.22f),new Vector2(.94f,.85f));
   AppContent.Paragraph(body,"尚未评估现场。选择目标后，再点击评估现场。",24,AppTheme.Muted);
   foreach(var choice in choices){
    var selected=choice;AppContent.Paragraph(body,choice.title,24);
    var button=AppTheme.Button(body,"选择："+GoalLabel(choice),Vector2.zero,Vector2.one,()=>{
     if(closed||generation!=version||reply!=null||question.text.Trim()!=intent)return;
     CloseDialog();question.text=selected.title;phase.text="目标已选定";SetFeedback("本次目标："+GoalLabel(selected)+"。\n点击评估现场，判断当前进度。");Refresh();
    },AppIcon.Check);button.gameObject.AddComponent<LayoutElement>().minHeight=64;
   }
   AppTheme.Button(dialog.Panel,"返回修改目标",new Vector2(.1f,.05f),new Vector2(.9f,.18f),CloseDialog,AppIcon.Back);
  }
  static string GoalLabel(GoalChoice choice){
   if(choice.selected_node_ids==null)return choice.title;
   if(choice.selected_node_ids.Length==2)return "安装料盘支架（两步）";
   return choice.selected_node_ids.Length==1&&choice.selected_node_ids[0]=="install_base"?"仅安装底座":"滑入支架（需核实底座）";
  }
  Command Stamp(){var e=reply.execution;return new Command{session_id=e.session_id,task_sha256=e.task_sha256,epoch=e.epoch,revision=e.revision,source_sha256=photoSha};}
  IEnumerator Observe(){
   if(reply==null||captured==null||busy||previewing)yield break;
   if(!Scripted&&captureVersion<=submittedVersion){SetFeedback("请重新拍摄操作后的现场，再点击核验。");yield break;}
   int version=generation;busy=true;phase.text=Scripted?"正在载入预设观察并规划…":"正在核验照片，请稍候…";
   var command=Stamp();command.scene_id=Scripted?sceneId:"";command.image_base64=Scripted?"":Convert.ToBase64String(captured);int sentVersion=captureVersion;
   yield return Request(Api+"/sessions/"+reply.execution.session_id+"/photo","POST",JsonUtility.ToJson(command),(raw,error)=>{
    if(error!=null){SetFeedback(error);return;}var result=JsonUtility.FromJson<Reply>(raw);
    if(result==null||result.execution==null||result.source_sha256!=photoSha){SetFeedback("照片已改变，请重拍后核验。");return;}Apply(result);if(reply==result)submittedVersion=sentVersion;
   },300);if(closed||version!=generation)yield break;busy=false;Refresh();
  }
  void Apply(Reply value){
   if(value==null||value.execution==null||catalog==null||value.mode!=(Scripted?"scripted":"live")||value.execution.task_sha256!=catalog.task_sha256||(reply!=null&&(value.execution.session_id!=reply.execution.session_id||value.execution.revision<reply.execution.revision))){SetFeedback("任务版本不一致，请重新打开演示。");return;}
   var plan=value.remaining_plan;var state=value.execution;
   if(plan!=null&&(plan.schema_version!="baseline-remaining-plan-v1"||plan.session_id!=state.session_id||plan.task_sha256!=state.task_sha256||plan.epoch!=state.epoch||plan.revision!=state.revision||plan.current_action==null||plan.current_action.mode!=state.baseline_mode||(!state.complete&&plan.current_action.node_id!=state.state_id))){
    SetFeedback("计划与当前进度不一致，请重新评估现场。");return;
   }
   if(reply==null||reply.execution.action_id!=value.execution.action_id)guidedAction="";
   reply=value;illustration=null;graphic.Clear();phase.color=value.execution.complete?AppTheme.SuccessGreen:AppTheme.TargetCyan;
   phase.text=value.execution.complete?"本次目标已完成":value.execution.baseline_mode=="ask_manual"?"现场结果 · 待人工核实":value.execution.baseline_mode=="request_view"?"现场结果 · 需要补拍":guidedAction==value.execution.action_id?"结果核验":"操作指导";
   RenderFeedback();Refresh();
  }
  void RenderFeedback(){
   if(reply==null)return;
   var flow=reply.demo_flow;var e=reply.execution;var text=new StringBuilder();
   if(flow==null){text.Append(e.user_summary).Append("\n\n").Append(e.user_feedback);}
   else {
    text.Append("目标：").Append(flow.goal).Append("\n现场：").Append(flow.scene_summary);
    if(!e.complete){
     var hints=reply.remaining_plan?.current_action?.observation_hints;
     if(e.baseline_mode=="request_view"&&hints!=null&&hints.Length>0){
      var supported=new List<string>();foreach(var condition in e.visual_conditions??new BaselineVisualCondition[0])if(condition.value=="true"&&!condition.retained)supported.Add(CaptureTarget(condition.id,condition.statement));
      if(supported.Count>0)text.Append("\n照片已支持：").Append(string.Join("、",supported)).Append("。");
      text.Append("\n\n补拍重点");
      foreach(var hint in hints)text.Append("\n• ").Append(CaptureTarget(hint.condition_id,hint.statement)).Append("：").Append(CaptureAdvice(hint));
      text.Append("\n请同时保留周边安装位置，补拍后重新评估。");
     }else text.Append("\n\n下一步：").Append(flow.next_action);
    }
    if(flow.steps!=null&&flow.steps.Length>0){
     text.Append("\n\n官方流程");
     for(int i=0;i<flow.steps.Length;i++){
      var step=flow.steps[i];string status=step.status=="verified"?"已核实":step.status=="failed"?"待调整":step.status=="pending"?(e.baseline_mode=="ask_manual"&&step.node_id==e.state_id?"待人工核实":"待完成"):step.status=="blocked"?"前置待核实":"待核实";
      text.Append("\n").Append(i+1).Append(". ").Append(step.title).Append(" · ").Append(status);
      if(!e.complete&&step.node_id==e.state_id)text.Append("（当前）");
      if(step.prerequisite_only)text.Append("（必要前置）");
     }
     if(!e.complete)text.Append("\n未核实的步骤，核实后再决定是否需要操作。");
    }
   }
   if(illustration!=null)text.Append("\n\n动画为照片示意，可点击画面调整位置。");
   SetFeedback(text.ToString());
  }
  static string CaptureTarget(string id,string statement){
   switch(id){case "c.base.mount":return "底座位置";case "c.base.screws":return "两颗固定螺丝";case "c.base.appearance":return "底座外观";case "c.holder.connection":return "支架连接处";case "c.holder.appearance":return "支架外观";default:return statement;}
  }
  static string CaptureAdvice(ObservationHint hint){
   switch(hint.reason){case "occluded":return "被遮挡，请换角度拍清。";case "out_of_frame":return "未入镜，请拍入画面。";case "unresolved_identity":return "部件身份不明，请拍清特征和安装位置。";case "insufficient_detail":return "细节不清，请靠近拍清。";default:return hint.instruction;}
  }
  void ShowManual(){
   CloseDialog();var token=reply;dialog=AppDialog.Open(root,"U7 demo manual confirmation","请核实当前操作",AppDialogSize.Large,CloseDialog);
   var panel=dialog.Panel;var text=new StringBuilder(token.demo_flow?.scene_summary??"当前操作的照片检查已通过。");text.Append("\n\n请实际检查以下项目：");
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
   if(busy||reply!=token||token.source_sha256!=photoSha)yield break;int version=generation;busy=true;
   var e=token.execution;var command=new ManualCommand{session_id=e.session_id,task_sha256=e.task_sha256,epoch=e.epoch,revision=e.revision,source_sha256=token.source_sha256,condition_ids=Array.ConvertAll(e.manual_conditions,c=>c.id)};
   yield return Request(Api+"/sessions/"+e.session_id+"/manual","POST",JsonUtility.ToJson(command),(raw,error)=>{if(error!=null)SetFeedback(error);else Apply(JsonUtility.FromJson<Reply>(raw));});if(closed||version!=generation)yield break;busy=false;
   if(reply!=token&&reply!=null&&reply.execution.guidance_ready&&!reply.execution.complete)yield return ShowAR(.45f,.34f);
   Refresh();
  }
  IEnumerator ShowAR(float x,float y){
   if(busy||previewing||reply==null||!reply.execution.guidance_ready||reply.execution.complete)yield break;int version=generation;busy=true;var e=reply.execution;
   if(reply.source_sha256!=photoSha){SetFeedback("请先核验当前照片，再显示本步示意。");busy=false;yield break;}
   var command=new ArCommand{session_id=e.session_id,task_sha256=e.task_sha256,epoch=e.epoch,revision=e.revision,source_sha256=photoSha,anchor_x=x,anchor_y=y};
   yield return Request(Api+"/sessions/"+e.session_id+"/ar","POST",JsonUtility.ToJson(command),(raw,error)=>{
    if(error!=null){SetFeedback(error);return;}var value=JsonUtility.FromJson<Illustration>(raw);
    if(value==null||value.projection==null||value.width<=0||value.height<=0||value.projection.camera_from_marker==null||value.projection.camera_from_marker.Length!=16||value.projection.intrinsics==null||value.projection.intrinsics.Length!=9||value.source_sha256!=photoSha||value.session_id!=e.session_id||value.task_sha256!=e.task_sha256||value.epoch!=e.epoch||value.action_id!=e.action_id||value.revision!=e.revision||!value.illustrative_only||value.presentation?.catalog_sha256!=catalog.asset_library.catalog_sha256||!VisualAssetLibrary.Validate(value.presentation)){SetFeedback("动画与当前照片或任务不一致。");return;}
    illustration=value;guidedAction=e.action_id;animationAt=Time.realtimeSinceStartup;phase.text="操作指导 · 完成后拍照核验";RenderFeedback();
   });if(closed||version!=generation)yield break;busy=false;Refresh();
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
   if(!Scripted&&previewing&&cameraOwner.Ready&&Time.realtimeSinceStartup>=previewAt){previewAt=Time.realtimeSinceStartup+.12f;var raw=cameraOwner.Capture();if(raw!=null)ShowPhoto(raw);}
   if(illustration!=null){var p=illustration.projection;var frame=new VisualRenderFrame{ReferenceSpaceId=illustration.presentation.reference_space_id,SourceSha256=illustration.source_sha256,Width=illustration.width,Height=illustration.height,CameraFromReference=p.camera_from_marker,Intrinsics=p.intrinsics,Distortion=p.distortion,HasWorldPlacement=false};
    graphic.Present(illustration.presentation,frame,Mathf.Repeat((Time.realtimeSinceStartup-animationAt)/illustration.presentation.duration_seconds,1));}
   Refresh();
  }
  void Refresh(){
   if(action==null)return;bool idle=!busy&&!closed,ready=catalog!=null&&idle;
   bool hasPlan=reply!=null;goalHeading.gameObject.SetActive(!hasPlan);question.gameObject.SetActive(!hasPlan);examples.gameObject.SetActive(!hasPlan);
   float top=hasPlan?.86f:.56f;
   if(feedbackArea.anchorMax.y!=top){feedbackArea.anchorMax=new Vector2(.95f,top);phase.rectTransform.anchorMin=new Vector2(.05f,hasPlan?.89f:.57f);phase.rectTransform.anchorMax=new Vector2(.95f,hasPlan?.98f:.65f);}
   modes.interactable=photos.interactable=examples.interactable=question.interactable=reset.interactable=ready;
   cameraButton.gameObject.SetActive(!Scripted);captureButton.gameObject.SetActive(!Scripted);
   var selector=(RectTransform)photos.transform;float end=Scripted?1:.66f;if(selector.anchorMax.x!=end)selector.anchorMax=new Vector2(end,1);
   cameraButton.interactable=ready&&!Scripted&&!previewing;captureButton.interactable=ready&&!Scripted&&previewing&&cameraOwner!=null&&cameraOwner.Ready;
   cameraButton.GetComponentInChildren<Text>().text=AppTheme.Readable(captured==null?"启动相机":"重新拍摄");
   bool complete=reply!=null&&reply.execution.complete;
   action.interactable=idle&&!previewing&&(catalog==null||complete||(Scripted&&captured==null)||(captured!=null&&!string.IsNullOrWhiteSpace(question.text)));
   string label=catalog==null?"重新载入演示资料":captured==null?(Scripted?"重新载入照片":"请先拍摄现场"):reply==null?"评估现场并生成计划":complete?"开始下一次演示":reply.source_sha256!=photoSha?(reply.execution.baseline_mode=="request_view"?"评估补拍照片":"核验当前照片"):reply.execution.baseline_mode=="ask_manual"?"核实人工项目":reply.execution.guidance_ready&&guidedAction!=reply.execution.action_id?"开始本步AR指导":reply.execution.baseline_mode=="request_view"?"重新评估现场":"完成操作，拍照核验";
   if(NeedsFreshPhoto()){label=reply.execution.baseline_mode=="request_view"?"请先补拍，再评估":"请先重新拍摄，再核验";action.interactable=false;}
   action.GetComponentInChildren<Text>().text=AppTheme.Readable(busy?"处理中…":previewing?"请先拍摄现场":label);
   bool canReplay=!previewing&&reply!=null&&reply.execution.guidance_ready&&!complete&&guidedAction==reply.execution.action_id&&reply.source_sha256==photoSha;
   replayButton.gameObject.SetActive(canReplay);replayButton.interactable=ready&&canReplay;
   sourcesButton.GetComponent<RectTransform>().anchorMax=new Vector2(canReplay?.49f:.95f,.14f);
   notice.text=AppTheme.Readable("已审核U7任务 · "+(Scripted?"历史照片预设观察":"真实模型观察")+" · 演示，不计入实验 · 照片示意定位");
  }
  bool NeedsFreshPhoto(){return !Scripted&&reply!=null&&!reply.execution.complete&&captureVersion<=submittedVersion&&reply.execution.baseline_mode!="ask_manual"&&!(reply.execution.guidance_ready&&guidedAction!=reply.execution.action_id);}
  void SetFeedback(string value){
   feedback.text=AppTheme.Readable(value);AppReadableText.Attach(feedback);
   LayoutRebuilder.ForceRebuildLayoutImmediate((RectTransform)feedback.transform.parent);
   feedbackArea.GetComponent<ScrollRect>().verticalNormalizedPosition=1;
  }
  void CloseDialog(){if(dialog!=null){var old=dialog;dialog=null;old.Close();}}
  void ResetSession(){
   CloseDialog();generation++;foreach(var pending in new List<UnityWebRequest>(requests))if(pending.method!="DELETE")pending.Abort();busy=false;illustration=null;graphic.Clear();guidedAction="";submittedVersion=-1;phase.color=AppTheme.TargetCyan;phase.text="目标与现场";
   var previous=reply;reply=null;if(previous!=null)StartCoroutine(Request(Api+"/sessions/"+previous.execution.session_id,"DELETE",null,(raw,error)=>{}));SetFeedback("填写目标并提供照片。系统会显示现场结果和剩余步骤。");Refresh();
  }
  static string Hash(byte[] raw){using(var digest=SHA256.Create())return BitConverter.ToString(digest.ComputeHash(raw)).Replace("-","").ToLowerInvariant();}
  IEnumerator Request(string path,string method,string body,Action<string,string> receive,int timeout=30){
   int version=generation;using(var request=new UnityWebRequest(origin+path,method)){
    request.downloadHandler=new DownloadHandlerBuffer();if(body!=null){request.uploadHandler=new UploadHandlerRaw(Encoding.UTF8.GetBytes(body));request.SetRequestHeader("Content-Type","application/json");}
    request.timeout=timeout;requests.Add(request);yield return request.SendWebRequest();requests.Remove(request);
    if(closed||version!=generation)yield break;
    if(request.result==UnityWebRequest.Result.Success){try{receive(request.downloadHandler.text,null);}catch(ArgumentException){phase.text="返回结果无效，请重试。";SetFeedback("服务返回格式异常，原进度保留。");}}
    else {string error="请求未完成，请重试。";try{var value=JsonUtility.FromJson<Failure>(request.downloadHandler.text);if(!string.IsNullOrEmpty(value.detail))error=value.detail;}catch(ArgumentException){}if(method!="DELETE"){phase.text="请求未完成，可调整后重试。";phase.color=AppTheme.TargetCyan;}receive(null,error);}
   }
  }
  void Close(){if(closed)return;StartCoroutine(Finish());}
  IEnumerator Finish(){
   busy=true;closed=true;generation++;foreach(var pending in new List<UnityWebRequest>(requests))pending.Abort();cameraOwner.Close();CloseDialog();root.gameObject.SetActive(false);
   var onClose=done;done=null;onClose?.Invoke();
   if(reply!=null)yield return Request(Api+"/sessions/"+reply.execution.session_id,"DELETE",null,(raw,error)=>{},5);
   Destroy(gameObject);
  }
  void OnDestroy(){closed=true;cameraOwner?.Close();foreach(var request in requests)request.Abort();requests.Clear();if(texture!=null)Destroy(texture);}
 }
}
