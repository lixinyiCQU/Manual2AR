using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Security.Cryptography;
using System.Text;
using UnityEngine;
using UnityEngine.Networking;
using UnityEngine.UI;

namespace Manual2AR.Spatial {
 /// <summary>Optional view, owns its camera/session and never mutates tutorial progress.</summary>
 public sealed partial class SpatialGuidanceController:MonoBehaviour,IAppModule {
  string Api="/api/guidance/spatial";
  AppWorkspace workspace;RectTransform root,viewport,referenceArea,infoCard;RawImage image,reference;SpatialOverlay overlay;SpatialAssetGraphic assetGraphic,companionGraphic;SpatialFeedbackView visionFeedback;Text stepHeader;SpatialCamera cameraOwner;SpatialReferenceViewer referenceViewer;
  ISpatialFrameSource frameSource;string tutorialRunId="",initialAction="";int pendingInteractions;
  Text title,instruction,status,authorHelp,checkResult,referenceCaption,modeLabel;Button setup,sample,solve,verify,cancel,locateButton;bool locating,locationPreview;UnityWebRequest localizationRequest;
  Dropdown referenceDropdown;bool backendReady;readonly HashSet<UnityWebRequest> requests=new HashSet<UnityWebRequest>();
  readonly SpatialPlayback playback=new SpatialPlayback();
  SpatialLegend legend;SpatialTextRenderer textRenderer;string vlmBrief="";SpatialActionBar actionBar;SpatialCallout callout;SpatialPickLabels pickLabels;RectTransform setupBar;
  bool setupVisible,setupExplicit,trackingInterrupted,authorBusy;int targetIndex,authorGeneration;float lastPresentedAt,lastRequestMs,presentationFps;
  Plan plan;Session session;Reply last;Texture2D displayed,referenceTexture;Action done;string origin,cameraSignature,mode="camera",candidate;
  U7Sequence u7Sequence=new U7Sequence();
  int actionIndex,referenceIndex,referenceGeneration,epoch,sequence,replayIndex,cameraIndex,authorStage,firstFrame,secondFrame;
  Pixel[] firstPoints,secondPoints;bool frozen,changing,sampleNext,checking,closed;
  string sticky="";float stickyUntil,frameStarted;bool requesting;
  ActionUnit Current {get{return plan.actions[actionIndex];}}
  string TargetId {get{return Current.target_instances==null||Current.target_instances.Length==0?"main":Current.target_instances[targetIndex].id;}}
  public static SpatialGuidanceController Open(string backend,string chapter,Action onClose){
   var controller=new GameObject("Desktop Spatial Guidance").AddComponent<SpatialGuidanceController>();
   controller.origin=backend.TrimEnd('/');controller.done=onClose;controller.Build();controller.StartCoroutine(controller.Initialize(chapter));return controller;
  }
  public static SpatialGuidanceController OpenForTutorial(string backend,string chapter,string actionId,string runId,Action<ActionUnit> onClose){
   var controller=Open(backend,chapter,null);controller.tutorialRunId=runId;controller.initialAction=actionId;
   controller.done=()=>onClose(controller.plan==null?null:controller.Current);return controller;
  }
  public static SpatialGuidanceController OpenCompiled(string backend,string candidate,Action onClose){
   var controller=new GameObject("Compiled U7 Spatial Experiment").AddComponent<SpatialGuidanceController>();
   controller.origin=backend.TrimEnd('/');controller.Api="/api/guidance/pipeline/candidates/"+candidate+"/spatial";
   controller.done=onClose;controller.Build();controller.StartCoroutine(controller.Initialize("U7"));return controller;
  }
  IEnumerator Initialize(string chapter){
   Plan incoming=null;
   yield return Request(Api+"/config","GET",null,(raw,error)=>{if(error!=null){Message(error);return;}incoming=JsonUtility.FromJson<Plan>(raw);});
   if(incoming==null)yield break;
   backendReady=incoming.automatic_configuration&&incoming.visual_revision=="mesh-loop-v2"&&incoming.required_client_revision=="machine-workframe-v1";
   if(Baseline&&(!incoming.explicit_scene_assessment||!incoming.batch_manual_confirmation))backendReady=false;
   if(Api!="/api/guidance/spatial"&&incoming.runtime_contract!=(Baseline?"baseline-ar-v1":incoming.stateful_runtime?"compiled-spatial-v3":"compiled-spatial-v2"))backendReady=false;
   if(!backendReady){Message("后端版本未更新，请重启后端");checkResult.text="请先关闭旧后端，再运行启动后端.cmd，返回图文后重新进入。";yield break;}
   backendReady=Manual2AR.VisualGuidance.VisualAssetLibrary.Matches(incoming.asset_library);
   if(!backendReady){Message("教学资产与后端版本不一致");checkResult.text="请启动资产库工作树的后端，并使用同一版本的前端。";yield break;}
   yield return RefreshU7Sequence();plan=incoming;
   int selected=string.IsNullOrEmpty(initialAction)?Array.FindIndex(plan.actions,a=>a.chapter_id==chapter):Array.FindIndex(plan.actions,a=>a.action_id==initialAction);if(selected>=0&&plan.actions[selected].action_id=="holder.slide"&&U7Locked)selected=Array.FindIndex(plan.actions,a=>a.action_id=="holder.base");Select(Mathf.Max(0,selected));RefreshBaselineSummary();StartCoroutine(Stream());
   if(CompiledBaseline){goalConfirmed=false;ShowBaselineGoalChoice();}
  }
  void Select(int index){
   bool continuing=guidedStarted&&GuidedFlow;
   if(plan==null||changing||index<0||index>=plan.actions.Length)return;if(Stateful&&execution!=null&&plan.actions[index].action_id!=execution.action_id){Message("请先完成当前计划的操作或核验");return;}if(plan.actions[index].action_id=="holder.slide"&&U7Locked){Message(u7Sequence.message??"请先拍照检查底座");BuildActionTabs();return;}actionIndex=index;targetIndex=0;epoch++;last=null;CancelAuthor();playback.Reset();trackingInterrupted=false;stickyUntil=0;callout.Hide();ClearGraphics();referenceIndex=Current.primary_reference_index;candidate=null;BuildTargets();
   title.text=AppTheme.Readable((string.IsNullOrEmpty(plan.experiment_title)?"开箱空间指导":plan.experiment_title)+" · "+Current.chapter_id+" · "+Current.title);
   instruction.text=AppTheme.Readable(Current.instruction);RefreshHelp();checkResult.text=Current.verification_mode=="manual"?"本章按官方说明人工确认，视觉不能判断螺丝是否锁紧。":"可选拍照，查看位置或安装建议。";
   verify.GetComponentInChildren<Text>().text=Current.verification_mode=="manual"?"确认完成":"检查安装";
   BuildActionTabs();
   StartCoroutine(LoadReference());
   ResetCheckFeedback();vlmBrief="";semanticReady=false;if(continuing)StartCoroutine(EnterSelectedStep(epoch));
  }
  void SelectChapter(string chapter){int index=Array.FindIndex(plan.actions,a=>a.chapter_id==chapter);if(index>=0)Select(index);}
  void BuildActionTabs(){
   if(plan==null||stepHeader==null)return;
   var display=Array.Find(plan.display_profiles??new Manual2AR.VisualGuidance.GuidanceDisplay[0],p=>p.action_id==Current.action_id);
   stepHeader.gameObject.SetActive(display==null);stepHeader.text=AppTheme.Readable(Current.title);
  }
  void BuildTargets(){BuildActionTabs();}
  void SelectTarget(int index){
   if(changing||plan==null||index==targetIndex)return;targetIndex=index;epoch++;last=null;CancelAuthor();playback.Reset();trackingInterrupted=false;stickyUntil=0;callout.Hide();ClearGraphics();BuildTargets();RefreshHelp();SendInteraction("target_selected");
  }
  void SetSetupVisible(bool value){setupVisible=value;setupBar.gameObject.SetActive(value);actionBar.Root.gameObject.SetActive(true);workspace.SetFooterVisible(value);workspace.FooterLeft.gameObject.SetActive(false);workspace.FooterRight.gameObject.SetActive(false);}
  void ExitSetup(){CancelAuthor();setupExplicit=false;SetSetupVisible(false);Message("已返回空间指导");}
  IEnumerator LoadReference(){
   CloseReference();reference.texture=null;reference.color=Color.clear;
   if(referenceTexture!=null){Destroy(referenceTexture);referenceTexture=null;}
   if(plan==null)yield break;int version=++referenceGeneration;var refs=Current.reference_images;if(refs==null||refs.Length==0)yield break;referenceIndex=(referenceIndex+refs.Length)%refs.Length;
   string file=Path.GetFileName(refs[referenceIndex]);referenceDropdown.ClearOptions();var names=new List<string>();for(int i=0;i<refs.Length;i++)names.Add("官方图 "+(i+1)+" / "+refs.Length);referenceDropdown.AddOptions(names);referenceDropdown.SetValueWithoutNotify(referenceIndex);referenceDropdown.RefreshShownValue();int photo=referenceIndex;
   string url=refs[referenceIndex].StartsWith("/")?refs[referenceIndex]:"/api/guidance/tasks/"+plan.task_id+"/variants/"+plan.variant_id+"/references/"+file;
   using(var request=UnityWebRequestTexture.GetTexture(origin+url)){
    request.timeout=15;requests.Add(request);yield return request.SendWebRequest();requests.Remove(request);
    if(closed||request.result!=UnityWebRequest.Result.Success||version!=referenceGeneration||photo!=referenceIndex)yield break;
    var texture=DownloadHandlerTexture.GetContent(request);if(referenceTexture!=null)Destroy(referenceTexture);referenceTexture=texture;reference.texture=texture;
    reference.uvRect=new Rect(0,0,1,1);reference.color=Color.white;reference.GetComponent<AspectRatioFitter>().aspectRatio=texture.width/(float)texture.height;
   }
  }
  IEnumerator BeginSession(string selectedMode,bool reuse){
   if(CompiledBaseline&&!goalConfirmed){ShowBaselineGoalChoice();yield break;}
   if(changing||checking||assessingScene||plan==null)yield break;if(!backendReady){Message("后端版本未更新，请重启后端");yield break;}changing=true;
   try{
   StopParts();CancelAutomatic();ClosePhotoPrompt();ResetCheckFeedback();guidedStarted=false;semanticReady=false;startAtTarget.gameObject.SetActive(false);epoch++;CancelAuthor();last=null;latestReply=null;latestBytes=null;baselineVerificationStage=false;baselineRetryOnly=false;baselineResultTitle="现场评估结果";playback.Reset();trackingInterrupted=false;callout.Hide();ClearGraphics();setupExplicit=false;SetSetupVisible(false);
   yield return DropSession();execution=null;attemptedScene="";mode=selectedMode;frameSource.Close();string failure=null;
   yield return null;
   if(mode=="camera"){
    yield return frameSource.Open(cameraIndex,e=>failure=e);
    if(failure!=null){Message(failure);changing=false;yield break;}cameraSignature=frameSource.Signature;
   }
   var command=new Begin{camera_id=mode=="replay"?"synthetic-replay":Hash(Encoding.UTF8.GetBytes(cameraSignature)).Substring(0,24),mode=mode,reuse_targets=reuse,tutorial_run_id=tutorialRunId,goal_intent=Baseline?goalIntent:""};
   yield return Request(Api+"/sessions","POST",JsonUtility.ToJson(command),(raw,error)=>{failure=error;if(error==null)session=JsonUtility.FromJson<Session>(raw);});
   changing=false;sequence=0;replayIndex=0;
   modeLabel.text=mode=="replay"?"合成定位回放 · 非实机检测 · 不写入实机位置":"Windows 摄像头 · "+CameraFraming.Ratios[aspectIndex]+" 标定画幅 · "+(WebCamTexture.devices.Length>0?WebCamTexture.devices[cameraIndex%WebCamTexture.devices.Length].name:"");
   if(failure!=null||session==null){Message(failure??"相机会话未建立，请重试。");yield break;}
   if(Baseline)ApplyBaseline(session.execution);else ApplyExecution(session.execution);
   if(session.u7_sequence!=null){u7Sequence=session.u7_sequence;BuildActionTabs();}
   if(mode=="camera"&&session.has_saved_targets&&!reuse&&!GuidedFlow)ShowReuse();
   if(GuidedFlow&&session.has_saved_targets)SetSetupVisible(false);
   else Message(mode=="replay"?"模拟回放已启动。":session.calibrated?"将已打印的定位标记固定到打印机刚性部位，让标记与操作区域同时入镜。":"首次使用：打印标定纸，在不同位置与倾角采集至少 12 张棋盘，再计算标定。");
   }finally{changing=false;RefreshBaselineControls();}
  }
  void ShowReuse(){
   var dialog=AppDialog.Open(root,"Reuse saved target confirmation","核对已保存位置",AppDialogSize.Standard,null);var panel=dialog.Panel;
   var text=AppTheme.Label(panel,"已有作用点设置。\n\n只有定位标记、打印机及相关安装区域均未发生相对移动时才可沿用。移动过标记或 X 轴等可动部件，请重新设置。",new Vector2(.05f,.32f),new Vector2(.95f,.81f),AppTheme.BodySize);AppReadableText.Attach(text);
   AppTheme.Button(panel,"沿用位置 · 标记未移动",new Vector2(.04f,.08f),new Vector2(.59f,.23f),()=>{dialog.Close();StartCoroutine(BeginSession("camera",true));},AppIcon.Check,true);
   AppTheme.Button(panel,"重新设置",new Vector2(.62f,.08f),new Vector2(.96f,.23f),dialog.Close,AppIcon.Inspect);
  }

  IEnumerator Stream(){
   while(!closed){
    if(changing||session==null||frozen){yield return null;continue;}
    var sentSession=session.session_id;int version=epoch;byte[] bytes=null;
    if(mode=="replay"){
     using(var get=UnityWebRequest.Get(origin+Api+"/replay/"+(replayIndex++%240)+".jpg")){get.timeout=5;requests.Add(get);yield return get.SendWebRequest();requests.Remove(get);if(get.result==UnityWebRequest.Result.Success)bytes=get.downloadHandler.data;}
    }else if(frameSource.Ready){
     if(frameSource.Signature!=cameraSignature){Message("相机分辨率或方向改变，请重新启动并标定。");frameSource.Close();yield return DropSession();continue;}
     bytes=frameSource.Capture();
    }
    if(bytes==null){HideGuidance();status.text="等待新的取景 · 空间提示已隐藏。";yield return new WaitForSecondsRealtime(.15f);continue;}
    double capturedAt=Time.realtimeSinceStartupAsDouble*1000;
    int id=++sequence;string sha=Hash(bytes),failure=null;Reply reply=null;bool takeSample=sampleNext;sampleNext=false;
    frameStarted=Time.realtimeSinceStartup;requesting=true;
    yield return Request(Api+"/sessions/"+sentSession+"/frames","POST",JsonUtility.ToJson(new Frame{client_frame_id=id,image_base64=Convert.ToBase64String(bytes),source_sha256=sha,action_id=Current.action_id,target_id=TargetId,calibration_sample=takeSample,snapshot=new CaptureSnapshot{provider_id=mode=="replay"?"synthetic":frameSource.ProviderId,client_frame_id=id,source_sha256=sha,width=mode=="replay"?960:frameSource.CaptureWidth,height=mode=="replay"?720:frameSource.CaptureHeight,capture_monotonic_ms=capturedAt}}),
     (raw,error)=>{failure=error;if(error==null)reply=JsonUtility.FromJson<Reply>(raw);},5);
    requesting=false;
    if(version!=epoch||session==null||session.session_id!=sentSession||frozen)continue;
    if(failure!=null){HideGuidance();Message(failure);if(Current.action_id=="holder.slide"){yield return RefreshU7Sequence();if(U7Locked)Select(Array.FindIndex(plan.actions,a=>a.action_id=="holder.base"));}yield return new WaitForSecondsRealtime(.5f);continue;}
    if(reply==null||reply.source_sha256!=sha||reply.client_frame_id!=id||reply.action_id!=Current.action_id||reply.session_id!=sentSession||(reply.target_id??"main")!=TargetId){HideGuidance();Message("画面身份不匹配，已隐藏空间提示。");continue;}
    lastRequestMs=(Time.realtimeSinceStartup-frameStarted)*1000;
    latestBytes=bytes;latestReply=reply;if(!partsDisplayActive)RenderFrame(bytes,reply);
    float delay=.10f-(Time.realtimeSinceStartup-frameStarted);if(delay>0)yield return new WaitForSecondsRealtime(delay);
   }
  }
  public void RenderFrame(byte[] bytes,Reply reply){
   var texture=new Texture2D(2,2,TextureFormat.RGB24,false);if(!ImageConversion.LoadImage(texture,bytes)){Destroy(texture);return;}
   if(displayed!=null)Destroy(displayed);displayed=texture;image.texture=texture;image.color=Color.white;viewport.GetComponent<AspectRatioFitter>().aspectRatio=texture.width/(float)texture.height;
   float now=Time.realtimeSinceStartup;if(lastPresentedAt>0)presentationFps=Mathf.Lerp(presentationFps,1/Mathf.Max(.001f,now-lastPresentedAt),.2f);lastPresentedAt=now;
   last=reply;UpdateExecution(reply);if(reply.u7_sequence!=null)u7Sequence=reply.u7_sequence;RefreshHelp();overlay.width=reply.width;overlay.height=reply.height;overlay.lines=reply.lines??new Segment[0];overlay.corners=reply.pose==null?null:reply.pose.corners;
   axesGraphic.width=reply.width;axesGraphic.height=reply.height;axesGraphic.axes=reply.machine_axes!=null&&reply.machine_axes.Length>0?reply.machine_axes:reply.visual!=null&&reply.visual.axes!=null&&reply.visual.axes.Length>0?reply.visual.axes:reply.reference_axes;if((GuidedFlow&&!semanticReady||Current.chapter_id=="U7")&&authorStage==0&&!setupExplicit)axesGraphic.axes=null;axesGraphic.SetVerticesDirty();
   if(GuidedFlow&&!semanticReady)overlay.lines=new Segment[0];
   if(authorStage==0){
    bool ready=reply.target_ready&&reply.visual!=null&&(!GuidedFlow||(guidedStarted&&semanticReady));bool resumed=!playback.Available&&trackingInterrupted;bool started=!playback.Available;
    if(playback.SetAvailable(ready)){trackingInterrupted=true;SendInteraction("tracking_hidden");}
    overlay.visual=ready?reply.visual:null;
    if(ready){playback.Configure(reply.visual.duration_seconds);if(reply.visual.display?.schema_version!="manual2ar-guidance-display-v1"&&(reply.visual.text_labels==null||reply.visual.text_labels.Length==0))callout.Show(reply.visual);else callout.Hide();if(started)SendInteraction(resumed?"auto_resumed":"auto_started");if(!setupExplicit)SetSetupVisible(false);}else callout.Hide();
   }
   RefreshAsset();overlay.SetVerticesDirty();
   string text=GuidedFlow&&guidedStarted&&!semanticReady?(locating?"正在识别与分割本步部件":"请识别部件后开始指导"):StateLabel(reply.state);if(authorStage==2)text="移动镜头换一个角度，同时保持标记不动，再固定第二视角。";
   if(stickyUntil>Time.realtimeSinceStartup)text=sticky;
   status.text=AppTheme.Readable(text);RefreshPreparation(reply);visionFeedback?.Place(reply);sample.GetComponentInChildren<Text>().text="采集棋盘 "+reply.sample_count+" / 12";
  }
  static string StateLabel(string state){switch(state){
   case "tracking":return "位置已就绪 · 自动示意中";
   case "camera_calibration_required":return "请先完成相机标定";
   case "calibration_resolution_mismatch":return "画幅已改变，请重新标定";
   case "target_setup_required":return "请设置当前操作位置";
   case "relocation_required":return "部件已移动，请重新设点";
   case "marker_too_small":return "请让定位标记更清晰入镜";
   case "target_outside_view":return "操作位置在画面外";
   default:return "请露出完整定位标记";
  }}
  void Update(){
   if(root==null)return;
   RefreshCheckHighlight();RefreshPlacementRepair();
   if(GuidedFlow&&!guidedStarted&&last!=null&&!automaticActive)RefreshPreparation(last);
   bool active=session!=null&&!changing;
   sample.interactable=solve.interactable=active&&mode=="camera"&&authorStage==0&&!locating&&!locationPreview;
   setup.interactable=active&&!authorBusy&&!locating&&!locationPreview&&mode=="camera"&&last!=null&&last.calibrated;
   verify.interactable=!automaticActive&&(Stateful||!GuidedFlow||guidedStarted)&&!assessingScene&&active&&!checking&&!locating&&!locationPreview&&authorStage==0&&(Current.verification_mode=="manual"||(mode=="camera"&&last!=null));
   locateButton.interactable=!automaticActive&&(Stateful||!GuidedFlow||guidedStarted)&&!assessingScene&&active&&mode=="camera"&&!checking&&authorStage==0&&last!=null&&!locating;
   cancel.interactable=!changing;
   actionBar.Refresh(changing||authorStage>0||locating||automaticBusy||locationPreview,active);
   RefreshBaselineControls();
   playback.Tick(Time.unscaledDeltaTime);
   overlay.progress=playback.Progress;if(playback.State=="playing")overlay.SetVerticesDirty();
   RefreshAsset();
   if(lastRenderProof!=epoch&&assetGraphic.VisibleTriangles>0){lastRenderProof=epoch;SendInteraction("render_ready");}
   if(requesting&&!partsDisplayActive&&Time.realtimeSinceStartup-frameStarted>.8f){HideGuidance();status.text="定位更新中";}
  }
  void RefreshAsset(){
   var currentAsset=(!frozen||partsDisplayActive)&&!overlay.accepting?overlay.visual:null;
   legend?.Present(currentAsset?.display);
   if(textRenderer!=null){if(currentAsset!=null)textRenderer.Present(currentAsset,overlay.width,overlay.height,"",last?.companion_visuals,legend!=null&&legend.Root.gameObject.activeSelf?new List<Rect>{legend.Bounds}:partsView.LabelRects);else textRenderer.Clear();}
   if(companionGraphic!=null){
    var other=currentAsset!=null&&last?.companion_visuals!=null&&last.companion_visuals.Length>0?last.companion_visuals[0]:null;
    if(other?.presentation!=null&&other.projection!=null){var q=other.projection;companionGraphic.Present(other.presentation,new Manual2AR.VisualGuidance.VisualRenderFrame{ReferenceSpaceId=other.presentation.reference_space_id,FrameId=last.client_frame_id,SourceSha256=last.source_sha256,Width=overlay.width,Height=overlay.height,CameraFromReference=q.camera_from_marker,Intrinsics=q.intrinsics,Distortion=q.distortion},playback.CyclePosition);}else companionGraphic.Clear();
   }
   if(SpatialAssetGraphic.HasPlacement(currentAsset)){
    if(currentAsset.presentation?.instances!=null){
     var p=currentAsset.projection;
     assetGraphic.Present(currentAsset.presentation,new Manual2AR.VisualGuidance.VisualRenderFrame{ReferenceSpaceId=currentAsset.presentation.reference_space_id,FrameId=last.client_frame_id,SourceSha256=last.source_sha256,Width=overlay.width,Height=overlay.height,CameraFromReference=p.camera_from_marker,Intrinsics=p.intrinsics,Distortion=p.distortion},playback.CyclePosition);return;
    }
    bool changed=assetGraphic.visual!=currentAsset||assetGraphic.progress!=playback.Progress;
    assetGraphic.Legacy(currentAsset);assetGraphic.width=overlay.width;assetGraphic.height=overlay.height;assetGraphic.progress=playback.Progress;
    if(changed)assetGraphic.SetVerticesDirty();
   }else assetGraphic.Clear();
  }
  void RefreshCallout(){if(overlay!=null&&overlay.visual!=null&&playback.Available&&(!frozen||partsDisplayActive)&&(overlay.visual.display?.schema_version!="manual2ar-guidance-display-v1"&&(overlay.visual.text_labels==null||overlay.visual.text_labels.Length==0)))callout.Show(overlay.visual);if(overlay!=null&&plan!=null)pickLabels.Refresh(overlay,authorMachine?new[]{"坐标原点 O","沿机架 +X 的点","沿立柱向上 +Z 的点"}:Current.authoring_points);}
  void ClearGraphics(){legend?.Present(null);textRenderer?.Clear();overlay.Clear();assetGraphic.Clear();companionGraphic?.Clear();axesGraphic?.Clear();}
  void HideGuidance(){visionFeedback?.Place(null);if(playback.SetAvailable(false)){trackingInterrupted=true;SendInteraction("tracking_hidden");}ClearGraphics();axesGraphic.Clear();callout.Hide();}
  void MarkOperation(){SendInteraction("user_marked");Message("已记录你的操作标记，可自由查看其他动作；这不是 AI 验收结果。");}
  void SendInteraction(string name){
   if(session==null||plan==null||closed)return;
   var command=new Interaction{event_id=Guid.NewGuid().ToString("N"),action_id=Current.action_id,target_id=TargetId,name=name,progress=playback.Progress,request_ms=Mathf.Clamp(lastRequestMs,0,300000),presentation_fps=Mathf.Clamp(presentationFps,0,240),visible_triangles=assetGraphic.VisibleTriangles,renderer_id=assetGraphic.AssetProvenance};
   if(last!=null&&last.action_id==Current.action_id&&(last.target_id??"main")==TargetId){command.client_frame_id=last.client_frame_id;command.source_sha256=last.source_sha256;}
   int sentEpoch=epoch;string identity=session.session_id;pendingInteractions++;
   StartCoroutine(Request(Api+"/sessions/"+identity+"/events","POST",JsonUtility.ToJson(command),(raw,error)=>{
    pendingInteractions--;if(error!=null||sentEpoch!=epoch||session==null||session.session_id!=identity||name!="user_marked")return;
    var result=JsonUtility.FromJson<InteractionResult>(raw);
    if(result.relocation_required){StopParts();epoch++;last=null;playback.Reset();HideGuidance();Message("已记录你的操作标记；此操作涉及部件移动，相关作用点需要重新设置。");}
   }));
  }
  void Message(string text){sticky=ShortStatus(text);stickyUntil=Time.realtimeSinceStartup+6;if(status!=null)status.text=AppTheme.Readable(ShortStatus(text));if(!feedbackPinned&&checkResult!=null)checkResult.text=AppTheme.Readable(ShortStatus(text));}
  static string ShortStatus(string text){if(string.IsNullOrEmpty(text))return "";int stop=text.IndexOf('。');if(stop>0)text=text.Substring(0,stop);return text.Length>46?text.Substring(0,44)+"…":text;}
  void RefreshHelp(){
   if(plan==null||authorHelp==null)return;
   string text;
   if(authorStage>0)text=authorMachine?"工作坐标系：依次选择 O、沿横梁的 +X 点、沿立柱向上的 +Z 点。两次视角使用相同的三个固定点。":Current.authoring_instruction;
   else if(last!=null&&last.requires_relocation)text="部件位置可能已变化，请重新设置作用点；相机标定保留。";
   else if(last!=null&&last.target_ready)text=!string.IsNullOrEmpty(Current.ready_hint)?Current.ready_hint:Current.kind=="fasten"?"工具仅作位置示意；拧下或拧紧请按上方文字与官方图判断。":Current.kind=="cut"?"这里只示意扎带位置，请先对照官方图辨认扎带。":Current.kind=="highlight"?"这里只高亮泡棉位置，没有编造移除方向。":"";
   else if(last!=null&&last.target_configured)text="位置设置仍保留。露出标记可继续；移动部件后需重新设置。";
   else if(!string.IsNullOrEmpty(Current.capture_guidance)&&last!=null&&last.calibrated)text=Current.capture_guidance;
   else text=!string.IsNullOrEmpty(Current.applicability_note)?Current.applicability_note:"";
   authorHelp.text=AppTheme.Readable(text);if(authorStage>0)checkResult.text=AppTheme.Readable(text);
   bool hasHelp=!string.IsNullOrEmpty(text);authorHelp.gameObject.SetActive(hasHelp);referenceArea.anchorMax=new Vector2(.96f,hasHelp?.67f:.79f);
  }
  IEnumerator Calibrate(){
   if(session==null)yield break;string id=session.session_id;Message("正在计算相机参数…");
   yield return Request(Api+"/sessions/"+id+"/calibration","POST","{}",(raw,error)=>{if(session!=null&&session.session_id==id){ClearGraphics();Message(error??"标定已保存。请换上定位标记，固定后开始设置起终点。");}},20);
  }
  void OnPoint(Pixel point){Message("已选择 "+overlay.picks.Count+" / "+overlay.MaximumPicks+" 点");}
  IEnumerator AuthorStep(){
   if(session==null||last==null||changing||authorBusy)yield break;
   int operation=authorGeneration;string sentSession=session.session_id;
   if(authorStage==0||authorStage==2){
    if(last.pose==null){Message("请先让定位标记清晰入镜。");yield break;}
    playback.SetAvailable(false);callout.Hide();frozen=true;ClearGraphics();overlay.MaximumPicks=authorMachine?3:2;overlay.accepting=true;overlay.SetVerticesDirty();
    if(authorStage==0){firstFrame=last.client_frame_id;authorStage=1;}
    else{secondFrame=last.client_frame_id;authorStage=3;}
    authorBusy=true;
    yield return Request(Api+"/sessions/"+sentSession+"/frames/"+last.client_frame_id+"/pin","POST","{}",(raw,error)=>{if(AuthorReplyCurrent(operation,sentSession)&&error!=null){CancelAuthor();Message(error);}});
    if(!AuthorReplyCurrent(operation,sentSession))yield break;authorBusy=false;
    RefreshHelp();setup.GetComponentInChildren<Text>().text=authorStage==1?"换角度再取景":"重建作用点";Message(authorMachine?"依次点击 O、+X、+Z 三个固定点，再换角度":"画面已固定。按说明依次点击起点、终点；两次视角必须选择同一对真实位置。");yield break;
   }
   if(authorStage==1||authorStage==3){
    if(overlay.picks.Count!=overlay.MaximumPicks){Message(authorMachine?"请依次选择 O、+X、+Z 三个固定点":"请在固定画面上依次选择两个点。");yield break;}
    if(authorStage==1){firstPoints=overlay.picks.ToArray();authorStage=2;frozen=false;overlay.accepting=false;overlay.picks.Clear();setup.GetComponentInChildren<Text>().text="固定第二视角";Message("保持打印机与标记不动，将摄像头横移约 15–25 厘米后再固定取景。");yield break;}
    secondPoints=overlay.picks.ToArray();overlay.accepting=false;authorBusy=true;
    string body=authorMachine?JsonUtility.ToJson(new MachineAuthor{first_frame=firstFrame,second_frame=secondFrame,first_points=firstPoints,second_points=secondPoints}):JsonUtility.ToJson(new Author{action_id=Current.action_id,target_id=TargetId,first_frame=firstFrame,second_frame=secondFrame,first_points=firstPoints,second_points=secondPoints});
    yield return Request(Api+"/sessions/"+sentSession+(authorMachine?"/machine/candidates":"/targets"),"POST",body,
     (raw,error)=>{if(!AuthorReplyCurrent(operation,sentSession))return;if(error!=null){Message(error);overlay.accepting=true;}else{var value=JsonUtility.FromJson<Candidate>(raw);candidate=value.candidate_id;authorStage=4;setup.GetComponentInChildren<Text>().text=authorMachine?"确认 O / XYZ":"确认保存位置";if(authorMachine){overlay.picks.Clear();axesGraphic.axes=value.preview_axes;axesGraphic.SetVerticesDirty();}Message(value.message);}});
    if(AuthorReplyCurrent(operation,sentSession))authorBusy=false;yield break;
   }
   if(authorStage==4){
    authorBusy=true;yield return Request(Api+"/sessions/"+sentSession+(authorMachine?"/machine/confirm":"/targets/confirm"),"POST",JsonUtility.ToJson(new Save{candidate_id=candidate}),
     (raw,error)=>{if(!AuthorReplyCurrent(operation,sentSession))return;if(error==null){bool machine=authorMachine;CancelAuthor();Message(machine?"打印机 O / XYZ 已保存 · U7 动作使用工作坐标":"作用点已保存。移动标记或相关可动部件后，请重新设置。");}else Message(error);});if(AuthorReplyCurrent(operation,sentSession))authorBusy=false;
   }
  }
  bool AuthorReplyCurrent(int version,string identity){return !closed&&version==authorGeneration&&session!=null&&session.session_id==identity;}
  void CancelAuthor(){CancelAutomatic();StopParts();if(localizationRequest!=null)try{localizationRequest.Abort();}catch(ObjectDisposedException){}localizationRequest=null;locating=false;authorGeneration++;authorBusy=false;authorStage=0;authorMachine=false;if(overlay!=null)overlay.MaximumPicks=2;candidate=null;frozen=false;locationPreview=false;if(locateButton!=null)locateButton.GetComponentInChildren<Text>().text="识别部件";if(overlay!=null){overlay.accepting=false;ClearGraphics();}if(setup!=null)setup.GetComponentInChildren<Text>().text="设置起终点";RefreshHelp();}
  IEnumerator Locate(){
   if(locationPreview){locationPreview=false;frozen=false;modeLabel.text="Windows 摄像头 · 有标记空间指导";ClearGraphics();locateButton.GetComponentInChildren<Text>().text="识别部件";Message("已恢复实时空间指导。");yield break;}
   if(session==null||last==null||locating||mode!="camera")yield break;
   if(Current.chapter_id=="U7"){yield return LocateParts();yield break;}
   frozen=true;locating=true;HideGuidance();int version=epoch;string identity=session.session_id;var sent=last;
   modeLabel.text="本次定位照片 · 返回实时后继续示意";checkResult.text="正在寻找当前部件…";Message("正在识别部件");
   yield return Request(Api+"/sessions/"+identity+"/locate","POST",JsonUtility.ToJson(new Verify{action_id=Current.action_id,target_id=TargetId,client_frame_id=sent.client_frame_id}),(raw,error)=>{
    if(version!=epoch||session==null||session.session_id!=identity)return;
    if(error!=null){frozen=false;checkResult.text=AppTheme.Readable(error);Message("拍照定位暂不可用");return;}
    var value=JsonUtility.FromJson<LocationPreview>(raw);
    if(!PresentLocation(value,sent,identity)){frozen=false;Message("照片身份已变化，旧定位已丢弃。");}
   },150);locating=false;
  }
  bool PresentLocation(LocationPreview value,Reply sent,string identity){
   if(value==null||session==null||session.session_id!=identity||value.session_id!=identity||value.source_sha256!=sent.source_sha256||value.client_frame_id!=sent.client_frame_id||value.action_id!=Current.action_id||value.target_id!=TargetId||value.width!=sent.width||value.height!=sent.height)return false;
   HideGuidance();frozen=true;locationPreview=true;overlay.lines=value.box_lines;overlay.outlines=value.outlines;overlay.SetVerticesDirty();
   modeLabel.text="本次定位照片 · 返回实时后继续示意";
   locateButton.GetComponentInChildren<Text>().text="返回实时";
   checkResult.text=AppTheme.Readable((value.status=="found"?"已标出候选位置":"未能确定位置")+"\n"+value.evidence+"\n"+value.next_action);Message("定位照片已返回");return true;
  }
  IEnumerator Verify(){
   if(Baseline){yield return CheckBaseline(true);yield break;}
   if(plan!=null&&Current.verification_mode=="manual"){if(session==null){Message("可返回原教程进行人工确认，或先启动演示会话。");yield break;}MarkOperation();checkResult.text="已记录人工确认；没有调用 AI 判断螺丝松紧。";yield break;}
   if(session==null||last==null||checking)yield break;checking=true;int version=epoch;var command=new Verify{action_id=Current.action_id,target_id=TargetId,client_frame_id=last.client_frame_id};string sha=last.source_sha256;
   ResetCheckFeedback();checkResult.text="正在查看安装区域…";
   yield return Request(Api+"/sessions/"+session.session_id+"/verify","POST",JsonUtility.ToJson(command),(raw,error)=>{
    if(version!=epoch)return;if(error!=null){verificationFeedback=AppTheme.Readable(error);ShowCheckFailure();return;}
    var result=JsonUtility.FromJson<Check>(raw);if(result.action_id!=command.action_id||result.source_sha256!=sha||result.client_frame_id!=command.client_frame_id)return;
    ApplyExecution(result.execution);if(result.u7_sequence!=null){u7Sequence=result.u7_sequence;BuildActionTabs();}
    verificationFeedback=AppTheme.Readable("安装核验 · "+(result.status=="completed"?"可见状态符合":(result.status=="wrong_operation"||result.status=="not_completed")?"尚未完成":"需要补充画面")+"\n\n"+result.evidence+"\n\n"+result.next_action);checkResult.text=verificationFeedback;
    if(Api!="/api/guidance/spatial"){
     var extra=JsonUtility.FromJson<CompiledCheck>(raw);
     if(extra.manual_pending!=null&&extra.manual_pending.Length>0){ShowCompiledManual(extra.manual_pending);return;}
     if(result.status=="completed"&&Stateful&&result.prerequisite_only){checkResult.text="前置条件核验已完成，请继续当前操作或结果检查。";return;}
     if(result.status=="completed"){ShowCompiledCompleted(Current.action_id=="holder.base");return;}
    }
    if(Current.chapter_id=="U7"&&result.status=="completed"){if(Current.action_id=="holder.base")ShowBaseCompleted();else ShowCompleted();}else ShowCheckFeedback(result);
   },150);checking=false;
  }
  IEnumerator Request(string path,string method,string body,Action<string,string> result,int timeout=10){
   using(var request=new UnityWebRequest(origin+path,method)){
    request.downloadHandler=new DownloadHandlerBuffer();request.timeout=timeout;if(body!=null){request.uploadHandler=new UploadHandlerRaw(Encoding.UTF8.GetBytes(body));request.SetRequestHeader("Content-Type","application/json");}
    if(path.EndsWith("/locate"))localizationRequest=request;
    requests.Add(request);yield return request.SendWebRequest();requests.Remove(request);if(localizationRequest==request)localizationRequest=null;
    string raw=request.downloadHandler.text,error=null;
    if(request.result!=UnityWebRequest.Result.Success){error="后端连接暂不可用，请确认服务已启动。";try{var value=JsonUtility.FromJson<Failure>(raw);if(!string.IsNullOrEmpty(value.detail))error=value.detail;}catch(Exception){}}
    if(!closed)result(raw,error);
   }
  }
  static string Hash(byte[] bytes){using(var sha=SHA256.Create())return BitConverter.ToString(sha.ComputeHash(bytes)).Replace("-","").ToLowerInvariant();}
  IEnumerator DropSession(){var old=session;session=null;if(old!=null)yield return Request(Api+"/sessions/"+old.session_id,"DELETE",null,(raw,error)=>{},5);}
  IEnumerator Close(){changing=true;float deadline=Time.realtimeSinceStartup+6;while(pendingInteractions>0&&Time.realtimeSinceStartup<deadline)yield return null;yield return DropSession();closed=true;frameSource.Close();done?.Invoke();Destroy(gameObject);}
  void AbortRequests(){foreach(var request in new List<UnityWebRequest>(requests))try{request.Abort();}catch(ObjectDisposedException){}requests.Clear();}
  public IEnumerator ReleaseModule(){closed=true;AbortRequests();StopAllCoroutines();frameSource.Close();var old=session;session=null;if(old!=null)using(var delete=UnityWebRequest.Delete(origin+Api+"/sessions/"+old.session_id)){delete.timeout=5;yield return delete.SendWebRequest();}}
  bool U7Locked {get{return u7Sequence!=null&&u7Sequence.enforced&&!u7Sequence.base_approved;}}
  IEnumerator RefreshU7Sequence(){yield return Request(Api+"/sequence"+(string.IsNullOrEmpty(tutorialRunId)?"":"?tutorial_run_id="+tutorialRunId),"GET",null,(raw,error)=>{if(error==null)u7Sequence=JsonUtility.FromJson<U7Sequence>(raw);});}
  void OnDestroy(){CancelAutomatic();closed=true;Canvas.willRenderCanvases-=RefreshCallout;AbortRequests();if(displayed!=null)Destroy(displayed);if(referenceTexture!=null)Destroy(referenceTexture);partsView?.Clear();}
 }
}
