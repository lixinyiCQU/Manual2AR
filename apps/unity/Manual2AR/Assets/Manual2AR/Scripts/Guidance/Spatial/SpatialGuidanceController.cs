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
 public sealed class SpatialGuidanceController:MonoBehaviour,IAppModule {
  const string Api="/api/guidance/spatial";
  RectTransform root,viewport;RawImage image,reference;SpatialOverlay overlay;SpatialCamera cameraOwner;
  ISpatialFrameSource frameSource;string tutorialRunId="",initialAction="";int pendingInteractions;
  Text title,instruction,status,authorHelp,checkResult,referenceCaption,modeLabel;Button setup,sample,solve,verify,cancel,locateButton;bool locating,locationPreview;UnityWebRequest localizationRequest;
  readonly List<Button> tabs=new List<Button>();readonly HashSet<UnityWebRequest> requests=new HashSet<UnityWebRequest>();
  readonly List<Button> chapterButtons=new List<Button>();readonly List<int> tabActions=new List<int>();
  readonly SpatialPlayback playback=new SpatialPlayback();readonly List<Button> targetButtons=new List<Button>();
  SpatialPlaybackBar playbackBar;SpatialCallout callout;RectTransform setupBar,targetTabs;Button setupDone;
  bool setupVisible=true,setupExplicit,trackingInterrupted,authorBusy;int targetIndex,authorGeneration;float lastPresentedAt,lastRequestMs,presentationFps;
  Plan plan;Session session;Reply last;Texture2D displayed,referenceTexture;Action done;string origin,cameraSignature,mode="camera",candidate;
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
  void Build(){
   var canvas=new GameObject("Unboxing Spatial View",typeof(RectTransform),typeof(Canvas),typeof(CanvasScaler),typeof(GraphicRaycaster));canvas.transform.SetParent(transform,false);
   canvas.GetComponent<Canvas>().renderMode=RenderMode.ScreenSpaceOverlay;canvas.GetComponent<Canvas>().sortingOrder=200;
   var scaler=canvas.GetComponent<CanvasScaler>();scaler.uiScaleMode=CanvasScaler.ScaleMode.ScaleWithScreenSize;scaler.referenceResolution=new Vector2(1920,1080);scaler.matchWidthOrHeight=.5f;
   root=canvas.GetComponent<RectTransform>();root.gameObject.AddComponent<AppRoundedImage>().color=AppTheme.Background;
   title=AppTheme.Label(root,"开箱 · 空间指导",new Vector2(.025f,.94f),new Vector2(.65f,.995f),32);
   modeLabel=AppTheme.Label(root,"Windows 摄像头 · 开箱空间指导",new Vector2(.025f,.90f),new Vector2(.76f,.943f),20,AppTheme.Muted);
   var controls=AppTheme.Panel(root,"Camera Controls",new Vector2(.66f,.795f),new Vector2(.975f,.845f));
   AppTheme.Button(controls,"启动摄像头",new Vector2(.01f,.08f),new Vector2(.32f,.92f),()=>StartCoroutine(BeginSession("camera",false)),AppIcon.Camera,true);
   AppTheme.Button(controls,"模拟回放",new Vector2(.34f,.08f),new Vector2(.65f,.92f),()=>StartCoroutine(BeginSession("replay",false)),AppIcon.Inspect);
   AppTheme.Button(controls,"切换镜头",new Vector2(.67f,.08f),new Vector2(.99f,.92f),()=>{cameraIndex++;StartCoroutine(BeginSession("camera",false));},AppIcon.SwitchCamera);
   var cameraPanel=AppTheme.Panel(root,"Spatial Camera",new Vector2(.025f,.22f),new Vector2(.64f,.77f));cameraPanel.gameObject.AddComponent<RectMask2D>();
   viewport=AppTheme.Rect(cameraPanel,"Matched frame viewport",Vector2.zero,Vector2.one);var fitter=viewport.gameObject.AddComponent<AspectRatioFitter>();fitter.aspectMode=AspectRatioFitter.AspectMode.FitInParent;fitter.aspectRatio=4f/3;
   image=viewport.gameObject.AddComponent<RawImage>();image.raycastTarget=false;image.color=AppTheme.PanelBackground;
   overlay=AppTheme.Rect(viewport,"Metric guidance",Vector2.zero,Vector2.one).gameObject.AddComponent<SpatialOverlay>();overlay.Selected+=OnPoint;
   callout=new SpatialCallout(overlay);
   var card=AppTheme.Panel(root,"Official Action",new Vector2(.66f,.22f),new Vector2(.975f,.785f));
   instruction=AppTheme.Label(card,"正在读取官方步骤…",new Vector2(.045f,.68f),new Vector2(.955f,.975f),25);
   authorHelp=AppTheme.Label(card,"",new Vector2(.045f,.52f),new Vector2(.955f,.68f),21,AppTheme.TargetCyan);
   targetTabs=AppTheme.Rect(card,"Operation Point Selection",new Vector2(.045f,.60f),new Vector2(.955f,.68f));
   var referenceArea=AppTheme.Rect(card,"Reference viewport",new Vector2(.045f,.21f),new Vector2(.955f,.51f));referenceArea.gameObject.AddComponent<RectMask2D>();
   var referenceImage=AppTheme.Rect(referenceArea,"Official image",Vector2.zero,Vector2.one);reference=referenceImage.gameObject.AddComponent<RawImage>();reference.raycastTarget=false;reference.color=Color.clear;
   var refFit=referenceImage.gameObject.AddComponent<AspectRatioFitter>();refFit.aspectMode=AspectRatioFitter.AspectMode.FitInParent;
   referenceCaption=AppTheme.Label(card,"",new Vector2(.24f,.12f),new Vector2(.76f,.19f),18,AppTheme.Muted);
   AppTheme.Button(card,"上一图",new Vector2(.03f,.12f),new Vector2(.23f,.19f),()=>{referenceIndex--;StartCoroutine(LoadReference());},AppIcon.Back);
   AppTheme.Button(card,"下一图",new Vector2(.77f,.12f),new Vector2(.97f,.19f),()=>{referenceIndex++;StartCoroutine(LoadReference());},AppIcon.Info);
   AppTheme.Button(card,"官方来源",new Vector2(.67f,.02f),new Vector2(.97f,.10f),()=>{if(plan!=null)Application.OpenURL(Current.source_url);},AppIcon.Info);
   verify=AppTheme.Button(card,"拍照参考",new Vector2(.35f,.02f),new Vector2(.65f,.10f),()=>StartCoroutine(Verify()),AppIcon.Camera);
   locateButton=AppTheme.Button(card,"拍照找位置",new Vector2(.03f,.02f),new Vector2(.33f,.10f),()=>StartCoroutine(Locate()),AppIcon.Inspect);
   status=AppTheme.Label(root,"选择摄像头，或先运行模拟回放。首次实机使用请打印标定纸。",new Vector2(.025f,.155f),new Vector2(.975f,.215f),24,AppTheme.TargetCyan);
   checkResult=AppTheme.Label(root,"动作示意、我已操作和拍照参考分别记录，不限制切换步骤。",new Vector2(.025f,.09f),new Vector2(.80f,.153f),21,AppTheme.Muted);
   setupBar=AppTheme.Rect(root,"Spatial Setup",new Vector2(.025f,.022f),new Vector2(.975f,.08f));
   AppTheme.Button(setupBar,"打印标定纸",new Vector2(0,0),new Vector2(.18f,1),()=>Application.OpenURL(origin+Api+"/print.pdf"),AppIcon.Save);
   sample=AppTheme.Button(setupBar,"采集棋盘",new Vector2(.20f,0),new Vector2(.38f,1),()=>{sampleNext=true;Message("请让完整棋盘入镜，正在采集一个标定视角。");},AppIcon.Camera);
   solve=AppTheme.Button(setupBar,"计算标定",new Vector2(.40f,0),new Vector2(.58f,1),()=>StartCoroutine(Calibrate()),AppIcon.Check);
   setup=AppTheme.Button(setupBar,"设置起终点",new Vector2(.60f,0),new Vector2(.82f,1),()=>StartCoroutine(AuthorStep()),AppIcon.Inspect,true);
   cancel=AppTheme.Button(setupBar,"取消设置",new Vector2(.84f,0),new Vector2(1,1),CancelAuthor,AppIcon.Close);
   playbackBar=new SpatialPlaybackBar(root,()=>PlaybackCommand("play"),()=>PlaybackCommand("pause"),()=>PlaybackCommand("replay"),MarkOperation,()=>{setupExplicit=true;SetSetupVisible(true);});
   setupDone=AppTheme.Button(root,"返回指导",new Vector2(.83f,.095f),new Vector2(.975f,.145f),()=>{CancelAuthor();setupExplicit=false;SetSetupVisible(false);},AppIcon.Back);
   SetSetupVisible(true);
   cameraOwner=gameObject.AddComponent<SpatialCamera>();frameSource=cameraOwner;Canvas.willRenderCanvases+=RefreshCallout;AppShell.BindBack("返回图文指导",()=>StartCoroutine(Close()),()=>!changing);
  }
  IEnumerator Initialize(string chapter){
   yield return Request(Api+"/config","GET",null,(raw,error)=>{if(error!=null){Message(error);return;}plan=JsonUtility.FromJson<Plan>(raw);});
   if(plan==null)yield break;
   for(int i=0;i<plan.chapters.Length;i++){string selectedChapter=plan.chapters[i].id;float x=.025f+i*.95f/plan.chapters.Length;chapterButtons.Add(AppTheme.Button(root,selectedChapter+" · "+plan.chapters[i].title,new Vector2(x,.855f),new Vector2(x+.95f/plan.chapters.Length-.01f,.9f),()=>SelectChapter(selectedChapter),AppIcon.Info));}
   int selected=string.IsNullOrEmpty(initialAction)?Array.FindIndex(plan.actions,a=>a.chapter_id==chapter):Array.FindIndex(plan.actions,a=>a.action_id==initialAction);Select(Mathf.Max(0,selected));StartCoroutine(Stream());
  }
  void Select(int index){
   if(plan==null||changing)return;actionIndex=index;targetIndex=0;epoch++;last=null;CancelAuthor();playback.Reset();trackingInterrupted=false;stickyUntil=0;callout.Hide();overlay.Clear();referenceIndex=Current.primary_reference_index;candidate=null;BuildTargets();
   title.text=AppTheme.Readable("开箱空间指导 · "+Current.chapter_id+" · "+Current.title);
   instruction.text=AppTheme.Readable(Current.instruction);RefreshHelp();checkResult.text=Current.verification_mode=="manual"?"本章按官方说明人工确认，视觉不能判断螺丝是否锁紧。":"本动作尚未拍照；AI 仅检查该章节最后的可见安装状态。";
   verify.GetComponentInChildren<Text>().text=Current.verification_mode=="manual"?"人工确认":"拍照参考";
   BuildActionTabs();
   StartCoroutine(LoadReference());
  }
  void SelectChapter(string chapter){int index=Array.FindIndex(plan.actions,a=>a.chapter_id==chapter);if(index>=0)Select(index);}
  void BuildActionTabs(){
   foreach(var button in tabs)Destroy(button.gameObject);tabs.Clear();tabActions.Clear();
   for(int i=0;i<plan.actions.Length;i++)if(plan.actions[i].chapter_id==Current.chapter_id)tabActions.Add(i);
   for(int i=0;i<tabActions.Count;i++){int index=tabActions[i];float x=.025f+i*.615f/tabActions.Count;tabs.Add(AppTheme.Button(root,plan.actions[index].title,new Vector2(x,.795f),new Vector2(x+.615f/tabActions.Count-.008f,.845f),()=>Select(index),AppIcon.Info,index==actionIndex));}
   for(int i=0;i<chapterButtons.Count;i++)chapterButtons[i].GetComponent<Image>().color=plan.chapters[i].id==Current.chapter_id?new Color(.045f,.43f,.56f):AppTheme.ButtonBackground;
  }
  void BuildTargets(){
   foreach(var b in targetButtons)Destroy(b.gameObject);targetButtons.Clear();
   bool multiple=Current.target_instances!=null&&Current.target_instances.Length>1;targetTabs.gameObject.SetActive(multiple);
   authorHelp.rectTransform.anchorMax=new Vector2(.955f,multiple?.60f:.68f);
   if(!multiple)return;
   for(int i=0;i<Current.target_instances.Length;i++){int index=i;float x=i/(float)Current.target_instances.Length;var instance=Current.target_instances[i];var button=AppTheme.Button(targetTabs,string.IsNullOrEmpty(instance.short_label)?instance.label:instance.short_label,new Vector2(x,0),new Vector2(x+1f/Current.target_instances.Length-.02f,1),()=>SelectTarget(index),AppIcon.Inspect,i==targetIndex);targetButtons.Add(button);}
  }
  void SelectTarget(int index){
   if(changing||plan==null||index==targetIndex)return;targetIndex=index;epoch++;last=null;CancelAuthor();playback.Reset();trackingInterrupted=false;stickyUntil=0;callout.Hide();overlay.Clear();BuildTargets();RefreshHelp();SendInteraction("target_selected");
  }
  void SetSetupVisible(bool value){setupVisible=value;setupBar.gameObject.SetActive(value);setupDone.gameObject.SetActive(value);playbackBar.Root.gameObject.SetActive(!value);}
  IEnumerator LoadReference(){
   if(plan==null)yield break;int version=++referenceGeneration;var refs=Current.reference_images;referenceIndex=(referenceIndex+refs.Length)%refs.Length;
   string file=Path.GetFileName(refs[referenceIndex]);referenceCaption.text="官方图 "+(referenceIndex+1)+" / "+refs.Length;int photo=referenceIndex;
   using(var request=UnityWebRequestTexture.GetTexture(origin+"/api/guidance/tasks/"+plan.task_id+"/variants/"+plan.variant_id+"/references/"+file)){
    request.timeout=15;requests.Add(request);yield return request.SendWebRequest();requests.Remove(request);
    if(closed||request.result!=UnityWebRequest.Result.Success||version!=referenceGeneration||photo!=referenceIndex)yield break;
    var texture=DownloadHandlerTexture.GetContent(request);if(referenceTexture!=null)Destroy(referenceTexture);referenceTexture=texture;reference.texture=texture;
    reference.uvRect=new Rect(0,0,1,1);reference.color=Color.white;reference.GetComponent<AspectRatioFitter>().aspectRatio=texture.width/(float)texture.height;
   }
  }
  IEnumerator BeginSession(string selectedMode,bool reuse){
   if(changing||plan==null)yield break;changing=true;epoch++;CancelAuthor();last=null;playback.Reset();callout.Hide();overlay.Clear();setupExplicit=false;SetSetupVisible(true);
   yield return DropSession();mode=selectedMode;frameSource.Close();string failure=null;
   if(mode=="camera"){
    yield return frameSource.Open(cameraIndex,e=>failure=e);
    if(failure!=null){Message(failure);changing=false;yield break;}cameraSignature=frameSource.Signature;
   }
   var command=new Begin{camera_id=mode=="replay"?"synthetic-replay":Hash(Encoding.UTF8.GetBytes(cameraSignature)).Substring(0,24),mode=mode,reuse_targets=reuse,tutorial_run_id=tutorialRunId};
   yield return Request(Api+"/sessions","POST",JsonUtility.ToJson(command),(raw,error)=>{failure=error;if(error==null)session=JsonUtility.FromJson<Session>(raw);});
   changing=false;sequence=0;replayIndex=0;
   modeLabel.text=mode=="replay"?"合成定位回放 · 非实机检测 · 不写入实机位置":"Windows 摄像头 · 固定 4:3 标定画幅 · "+(WebCamTexture.devices.Length>0?WebCamTexture.devices[cameraIndex%WebCamTexture.devices.Length].name:"");
   if(failure!=null){Message(failure);yield break;}
   if(mode=="camera"&&session.has_saved_targets&&!reuse)ShowReuse();
   else Message(mode=="replay"?"模拟回放已启动。":session.calibrated?"将已打印的定位标记固定到打印机刚性部位，让标记与操作区域同时入镜。":"首次使用：打印标定纸，在不同位置与倾角采集至少 12 张棋盘，再计算标定。");
  }
  void ShowReuse(){
   var panel=AppTheme.Panel(root,"Reuse saved target confirmation",new Vector2(.16f,.35f),new Vector2(.84f,.72f));
   AppTheme.Label(panel,"已有作用点设置。\n只有定位标记、打印机及相关安装区域均未发生相对移动时才可沿用。移动过标记或 X 轴等可动部件，请重新设置。",new Vector2(.04f,.35f),new Vector2(.96f,.94f),27);
   AppTheme.Button(panel,"沿用位置 · 标记未移动",new Vector2(.04f,.08f),new Vector2(.59f,.28f),()=>{Destroy(panel.gameObject);StartCoroutine(BeginSession("camera",true));},AppIcon.Check,true);
   AppTheme.Button(panel,"重新设置",new Vector2(.62f,.08f),new Vector2(.96f,.28f),()=>Destroy(panel.gameObject),AppIcon.Inspect);
   panel.SetAsLastSibling();
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
    if(failure!=null){HideGuidance();Message(failure);yield return new WaitForSecondsRealtime(.5f);continue;}
    if(reply==null||reply.source_sha256!=sha||reply.client_frame_id!=id||reply.action_id!=Current.action_id||reply.session_id!=sentSession||(reply.target_id??"main")!=TargetId){HideGuidance();Message("画面身份不匹配，已隐藏空间提示。");continue;}
    lastRequestMs=(Time.realtimeSinceStartup-frameStarted)*1000;
    RenderFrame(bytes,reply);
    float delay=.10f-(Time.realtimeSinceStartup-frameStarted);if(delay>0)yield return new WaitForSecondsRealtime(delay);
   }
  }
  public void RenderFrame(byte[] bytes,Reply reply){
   var texture=new Texture2D(2,2,TextureFormat.RGB24,false);if(!ImageConversion.LoadImage(texture,bytes)){Destroy(texture);return;}
   if(displayed!=null)Destroy(displayed);displayed=texture;image.texture=texture;image.color=Color.white;viewport.GetComponent<AspectRatioFitter>().aspectRatio=texture.width/(float)texture.height;
   float now=Time.realtimeSinceStartup;if(lastPresentedAt>0)presentationFps=Mathf.Lerp(presentationFps,1/Mathf.Max(.001f,now-lastPresentedAt),.2f);lastPresentedAt=now;
   last=reply;RefreshHelp();overlay.width=reply.width;overlay.height=reply.height;overlay.lines=reply.lines??new Segment[0];overlay.corners=reply.pose==null?null:reply.pose.corners;
   if(authorStage==0){
    bool ready=reply.target_ready&&reply.visual!=null;
    if(playback.SetAvailable(ready)){trackingInterrupted=true;SendInteraction("tracking_hidden");}
    overlay.visual=ready?reply.visual:null;
    if(ready){playback.Configure(reply.visual.duration_seconds);callout.Show(reply.visual);if(!setupExplicit)SetSetupVisible(false);}else callout.Hide();
   }
   overlay.SetVerticesDirty();
   string text=StateLabel(reply.state);if(authorStage==2)text="移动镜头换一个角度，同时保持标记不动，再固定第二视角。";
   if(reply.target_ready&&playback.State=="paused")text=trackingInterrupted?"定位已恢复，可点击继续播放；动作示意不代表操作完成。":"示意已暂停，可点击继续播放。";
   if(stickyUntil>Time.realtimeSinceStartup)text=sticky+"  ·  "+text;
   status.text=AppTheme.Readable(text);sample.GetComponentInChildren<Text>().text="采集棋盘 "+reply.sample_count+" / 12";
  }
  static string StateLabel(string state){switch(state){
   case "tracking":return "已找到操作位置。点击播放示意，对照官方图文自行操作。";
   case "camera_calibration_required":return "请先采集棋盘并计算相机标定。";
   case "calibration_resolution_mismatch":return "当前画幅与标定不一致，请重新采集棋盘标定。";
   case "target_setup_required":return "已找到定位标记。请设置当前动作的起点与终点。";
   case "relocation_required":return "此操作涉及部件移动，相关位置提示已暂停；请重新设置当前作用点。";
   case "marker_too_small":return "定位标记太小，请靠近一些；同时保持操作区域入镜。";
   case "target_outside_view":return "操作位置在画面外，请调整镜头。";
   default:return "暂未稳定定位，已隐藏空间提示。请保持标记完整清晰入镜。";
  }}
  void Update(){
   if(root==null)return;
   bool active=session!=null&&!changing;
   sample.interactable=solve.interactable=active&&mode=="camera"&&authorStage==0&&!locating&&!locationPreview;
   setup.interactable=active&&!authorBusy&&!locating&&!locationPreview&&mode=="camera"&&last!=null&&last.calibrated;
   verify.interactable=active&&!checking&&!locating&&!locationPreview&&authorStage==0&&(Current.verification_mode=="manual"||(mode=="camera"&&last!=null));
   locateButton.interactable=active&&mode=="camera"&&!locating&&!checking&&authorStage==0&&last!=null;
   cancel.interactable=authorStage>0;
   playbackBar.Refresh(playback,changing||authorStage>0||locating||locationPreview,active);
   if(playback.Tick(Time.unscaledDeltaTime)){SendInteraction("animation_finished");Message("示意播放结束，可重新播放或自行操作；不表示安装已经完成。");}
   overlay.progress=playback.Progress;if(playback.State=="playing")overlay.SetVerticesDirty();
   if(requesting&&Time.realtimeSinceStartup-frameStarted>.8f){HideGuidance();status.text="定位更新中 · 显示的是上一张取景，空间提示已暂时隐藏。";}
  }
  void RefreshCallout(){if(overlay!=null&&overlay.visual!=null&&playback.Available&&!frozen)callout.Show(overlay.visual);}
  void HideGuidance(){if(playback.SetAvailable(false)){trackingInterrupted=true;SendInteraction("tracking_hidden");}overlay.Clear();callout.Hide();}
  void PlaybackCommand(string name){
   bool changed=name=="pause"?playback.Pause():name=="replay"?playback.Replay():playback.Play();
   if(!changed)return;if(name!="pause")trackingInterrupted=false;SendInteraction(name);Message(name=="pause"?"示意已暂停。":(Current.playback_caption??Current.instruction)+"（位置／方向示意，请对照官方图操作）");
  }
  void MarkOperation(){SendInteraction("user_marked");Message("已记录你的操作标记，可自由查看其他动作；这不是 AI 验收结果。");}
  void SendInteraction(string name){
   if(session==null||plan==null||closed)return;
   var command=new Interaction{event_id=Guid.NewGuid().ToString("N"),action_id=Current.action_id,target_id=TargetId,name=name,progress=playback.Progress,request_ms=Mathf.Clamp(lastRequestMs,0,300000),presentation_fps=Mathf.Clamp(presentationFps,0,240)};
   if(last!=null&&last.action_id==Current.action_id&&(last.target_id??"main")==TargetId){command.client_frame_id=last.client_frame_id;command.source_sha256=last.source_sha256;}
   int sentEpoch=epoch;string identity=session.session_id;pendingInteractions++;
   StartCoroutine(Request(Api+"/sessions/"+identity+"/events","POST",JsonUtility.ToJson(command),(raw,error)=>{
    pendingInteractions--;if(error!=null||sentEpoch!=epoch||session==null||session.session_id!=identity||name!="user_marked")return;
    var result=JsonUtility.FromJson<InteractionResult>(raw);
    if(result.relocation_required){epoch++;last=null;playback.Reset();HideGuidance();Message("已记录你的操作标记；此操作涉及部件移动，相关作用点需要重新设置。");}
   }));
  }
  void Message(string text){sticky=text;stickyUntil=Time.realtimeSinceStartup+6;if(status!=null)status.text=AppTheme.Readable(text);}
  void RefreshHelp(){
   if(plan==null||authorHelp==null)return;
   string text;
   if(authorStage>0)text=Current.authoring_instruction;
   else if(last!=null&&last.requires_relocation)text="部件位置可能已变化，请重新设置作用点；相机标定保留。";
   else if(last!=null&&last.target_ready)text=Current.kind=="fasten"?"工具仅作位置示意；拧下或拧紧请按上方文字与官方图判断。":Current.kind=="cut"?"这里只示意扎带位置，请先对照官方图辨认扎带。":Current.kind=="highlight"?"这里只高亮泡棉位置，没有编造移除方向。":"指示点只示意方向，请同时阅读上方文字和官方图。";
   else if(last!=null&&last.target_configured)text="位置设置仍保留。露出标记可继续；移动部件后需重新设置。";
   else text=!string.IsNullOrEmpty(Current.applicability_note)?Current.applicability_note:last!=null&&last.calibrated?"相机已标定。需要空间示意时再设置当前作用点。":"首次空间使用先标定，再设置作用点；也可直接阅读官方图文。";
   authorHelp.text=AppTheme.Readable(text);
   bool multiple=Current.target_instances!=null&&Current.target_instances.Length>1;
   targetTabs.gameObject.SetActive(multiple&&authorStage==0);
   authorHelp.rectTransform.anchorMax=new Vector2(.955f,multiple&&authorStage==0?.60f:.68f);
  }
  IEnumerator Calibrate(){
   if(session==null)yield break;string id=session.session_id;Message("正在计算相机参数…");
   yield return Request(Api+"/sessions/"+id+"/calibration","POST","{}",(raw,error)=>{if(session!=null&&session.session_id==id){overlay.Clear();Message(error??"标定已保存。请换上定位标记，固定后开始设置起终点。");}},20);
  }
  void OnPoint(Pixel point){status.text=AppTheme.Readable("已选择 "+overlay.picks.Count+" / 2 点。"+Current.authoring_instruction);}
  IEnumerator AuthorStep(){
   if(session==null||last==null||changing||authorBusy)yield break;
   int operation=authorGeneration;string sentSession=session.session_id;
   if(authorStage==0||authorStage==2){
    if(last.pose==null){Message("请先让定位标记清晰入镜。");yield break;}
    playback.SetAvailable(false);callout.Hide();frozen=true;overlay.Clear();overlay.accepting=true;overlay.SetVerticesDirty();
    if(authorStage==0){firstFrame=last.client_frame_id;authorStage=1;}
    else{secondFrame=last.client_frame_id;authorStage=3;}
    authorBusy=true;
    yield return Request(Api+"/sessions/"+sentSession+"/frames/"+last.client_frame_id+"/pin","POST","{}",(raw,error)=>{if(AuthorReplyCurrent(operation,sentSession)&&error!=null){CancelAuthor();Message(error);}});
    if(!AuthorReplyCurrent(operation,sentSession))yield break;authorBusy=false;
    RefreshHelp();setup.GetComponentInChildren<Text>().text=authorStage==1?"换角度再取景":"重建作用点";Message("画面已固定。按说明依次点击起点、终点；两次视角必须选择同一对真实位置。");yield break;
   }
   if(authorStage==1||authorStage==3){
    if(overlay.picks.Count!=2){Message("请在固定画面上依次选择两个点。");yield break;}
    if(authorStage==1){firstPoints=overlay.picks.ToArray();authorStage=2;frozen=false;overlay.accepting=false;overlay.picks.Clear();setup.GetComponentInChildren<Text>().text="固定第二视角";Message("保持打印机与标记不动，将摄像头横移约 15–25 厘米后再固定取景。");yield break;}
    secondPoints=overlay.picks.ToArray();overlay.accepting=false;authorBusy=true;
    yield return Request(Api+"/sessions/"+sentSession+"/targets","POST",JsonUtility.ToJson(new Author{action_id=Current.action_id,target_id=TargetId,first_frame=firstFrame,second_frame=secondFrame,first_points=firstPoints,second_points=secondPoints}),
     (raw,error)=>{if(!AuthorReplyCurrent(operation,sentSession))return;if(error!=null){Message(error);overlay.accepting=true;}else{var value=JsonUtility.FromJson<Candidate>(raw);candidate=value.candidate_id;authorStage=4;setup.GetComponentInChildren<Text>().text="确认保存位置";Message(value.message);}});
    if(AuthorReplyCurrent(operation,sentSession))authorBusy=false;yield break;
   }
   if(authorStage==4){
    authorBusy=true;yield return Request(Api+"/sessions/"+sentSession+"/targets/confirm","POST",JsonUtility.ToJson(new Save{candidate_id=candidate}),
     (raw,error)=>{if(!AuthorReplyCurrent(operation,sentSession))return;if(error==null){CancelAuthor();Message("作用点已保存。移动标记或相关可动部件后，请重新设置。");}else Message(error);});if(AuthorReplyCurrent(operation,sentSession))authorBusy=false;
   }
  }
  bool AuthorReplyCurrent(int version,string identity){return !closed&&version==authorGeneration&&session!=null&&session.session_id==identity;}
  void CancelAuthor(){if(localizationRequest!=null)try{localizationRequest.Abort();}catch(ObjectDisposedException){}localizationRequest=null;locating=false;authorGeneration++;authorBusy=false;authorStage=0;candidate=null;frozen=false;locationPreview=false;if(locateButton!=null)locateButton.GetComponentInChildren<Text>().text="拍照找位置";if(overlay!=null){overlay.accepting=false;overlay.Clear();}if(setup!=null)setup.GetComponentInChildren<Text>().text="设置起终点";RefreshHelp();}
  IEnumerator Locate(){
   if(locationPreview){locationPreview=false;frozen=false;modeLabel.text="Windows 摄像头 · 有标记空间指导";overlay.Clear();locateButton.GetComponentInChildren<Text>().text="拍照找位置";Message("已恢复实时空间指导。");yield break;}
   if(session==null||last==null||locating||mode!="camera")yield break;
   frozen=true;locating=true;HideGuidance();int version=epoch;string identity=session.session_id;var sent=last;
   modeLabel.text="本次照片 · 找位置参考 · 不是三维定位或安装核验";status.text="正在照片中寻找当前部件，可随时切换动作或返回图文。";
   yield return Request(Api+"/sessions/"+identity+"/locate","POST",JsonUtility.ToJson(new Verify{action_id=Current.action_id,target_id=TargetId,client_frame_id=sent.client_frame_id}),(raw,error)=>{
    if(version!=epoch||session==null||session.session_id!=identity)return;
    if(error!=null){frozen=false;Message(error);return;}
    var value=JsonUtility.FromJson<LocationPreview>(raw);
    if(!PresentLocation(value,sent,identity)){frozen=false;Message("照片身份已变化，旧定位已丢弃。");}
   },150);locating=false;
  }
  bool PresentLocation(LocationPreview value,Reply sent,string identity){
   if(value==null||session==null||session.session_id!=identity||value.session_id!=identity||value.source_sha256!=sent.source_sha256||value.client_frame_id!=sent.client_frame_id||value.action_id!=Current.action_id||value.target_id!=TargetId||value.width!=sent.width||value.height!=sent.height)return false;
   HideGuidance();frozen=true;locationPreview=true;overlay.lines=value.box_lines;overlay.outlines=value.outlines;overlay.SetVerticesDirty();
   modeLabel.text="本次照片 · 找位置参考 · 不是三维定位或安装核验";
   locateButton.GetComponentInChildren<Text>().text="返回实时";
   status.text=AppTheme.Readable(value.status=="found"?"已标出本次照片中的候选位置；请对照官方图辨认，点击返回实时继续。":"这张照片未能明确找到目标；可查看官方图，或返回实时换角度再拍。");return true;
  }
  IEnumerator Verify(){
   if(plan!=null&&Current.verification_mode=="manual"){if(session==null){Message("可返回原教程进行人工确认，或先启动演示会话。");yield break;}MarkOperation();checkResult.text="已记录人工确认；没有调用 AI 判断螺丝松紧。";yield break;}
   if(session==null||last==null||checking)yield break;checking=true;int version=epoch;var command=new Verify{action_id=Current.action_id,target_id=TargetId,client_frame_id=last.client_frame_id};string sha=last.source_sha256;
   checkResult.text="正在询问 AI · 仅检查本章最后的可见安装结果，不影响空间指导。";
   yield return Request(Api+"/sessions/"+session.session_id+"/verify","POST",JsonUtility.ToJson(command),(raw,error)=>{
    if(version!=epoch)return;if(error!=null){checkResult.text=AppTheme.Readable(error);return;}
    var result=JsonUtility.FromJson<Check>(raw);if(result.action_id!=command.action_id||result.source_sha256!=sha||result.client_frame_id!=command.client_frame_id)return;
    checkResult.text=AppTheme.Readable("最近一次拍照参考 · "+(result.status=="completed"?"可见状态符合":result.status=="wrong_operation"?"建议调整":"需要补充画面")+" · "+result.evidence+" "+result.next_action);
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
  void OnDestroy(){closed=true;Canvas.willRenderCanvases-=RefreshCallout;AbortRequests();if(displayed!=null)Destroy(displayed);if(referenceTexture!=null)Destroy(referenceTexture);}
 }
}
