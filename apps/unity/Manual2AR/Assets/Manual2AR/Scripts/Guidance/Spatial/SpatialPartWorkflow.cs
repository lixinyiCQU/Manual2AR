using System;
using System.Collections;
using UnityEngine;
using UnityEngine.UI;
namespace Manual2AR.Spatial {
 public sealed partial class SpatialGuidanceController {
  SpatialPartsView partsView;SpatialAxesGraphic axesGraphic;AppAspectSelector aspectSelector;int aspectIndex=4,lastRenderProof=-1,partsGeneration;
  byte[] latestBytes;Reply latestReply;string partsJob;bool partsDisplayActive;GameObject photoPrompt;
  void ChooseAspect(int value){if(changing||value==aspectIndex)return;bool restart=session!=null;aspectIndex=value;aspectSelector?.Select(value);StopParts();CancelAuthor();ClearGraphics();last=null;latestReply=null;latestBytes=null;cameraOwner.SetAspect(value);if(restart)StartCoroutine(BeginSession("camera",false));Message("画幅已切换 · 请使用当前画幅的标定");}
  void ShowOrientation(){if(last!=null&&last.machine_frame!=null&&last.motion_parameters!=null&&last.motion_parameters.enabled){Message("打印机坐标模式请调整动作轴；切换两点模式后可调高级朝向");return;}if(authorStage!=0||changing||locating){Message("请先完成或取消当前设点");return;}if(session==null||last==null||!last.target_ready){Message("请先设置并确认当前作用点");return;}SpatialOrientationPanel.Open(root,last.orientation??new Orientation(),value=>{value.action_id=Current.action_id;value.target_id=TargetId;StartCoroutine(SaveOrientation(value));});}
  IEnumerator SaveOrientation(Orientation value){StopParts();epoch++;last=null;ClearGraphics();yield return Request(Api+"/sessions/"+session.session_id+"/orientation","POST",JsonUtility.ToJson(value),(raw,error)=>Message(error??"XYZ 姿态已保存"));}
  void ClosePhotoPrompt(){feedbackPinned=false;if(photoPrompt!=null){photoPrompt.SetActive(false);Destroy(photoPrompt);}photoPrompt=null;}
  RectTransform PhotoPanel(string title,bool compact=false){ClosePhotoPrompt();var dialog=AppDialog.Open(root,"Photo preparation",title,compact?AppDialogSize.Compact:AppDialogSize.Standard,ClosePhotoPrompt);photoPrompt=dialog.gameObject;dialog.Panel.name="Photo guidance";return dialog.Panel;}

  void ShowLocateCapture(){
   if(GuidedFlow){StartCoroutine(LocateParts());return;}
   if(partsDisplayActive){StopParts();Message("已恢复空间指导");return;}
   if(Current.chapter_id!="U7"){StartCoroutine(Locate());return;}
   var panel=PhotoPanel("拍清底座和料盘支架");AppTheme.Label(panel,"让灰色双螺丝底座与白色料盘支架同时入镜。\n支架可放在打印机旁；若已安装遮住底座，会分别报告可见情况。",new Vector2(.04f,.65f),new Vector2(.96f,.85f),25);
   ReferenceExample(panel,"base_reference",new Vector2(.05f,.23f),new Vector2(.42f,.63f));ReferenceExample(panel,"holder_reference",new Vector2(.47f,.23f),new Vector2(.95f,.63f));
   AppTheme.Label(panel,"底座",new Vector2(.05f,.16f),new Vector2(.42f,.23f),23);AppTheme.Label(panel,"料盘支架",new Vector2(.47f,.16f),new Vector2(.95f,.23f),23);
   AppTheme.Button(panel,"取消",new Vector2(.04f,.025f),new Vector2(.35f,.13f),ClosePhotoPrompt,AppIcon.Close);AppTheme.Button(panel,"识别部件",new Vector2(.43f,.025f),new Vector2(.96f,.13f),()=>{ClosePhotoPrompt();StartCoroutine(Locate());},AppIcon.Camera,true);
  }
  static void ReferenceExample(Transform parent,string name,Vector2 min,Vector2 max){var slot=AppTheme.Rect(parent,name+" slot",min,max);var img=AppTheme.Rect(slot,name,Vector2.zero,Vector2.one).gameObject.AddComponent<RawImage>();img.texture=Resources.Load<Texture2D>("VisualGuidance/references/"+name);img.raycastTarget=false;if(img.texture!=null){var fit=img.gameObject.AddComponent<AspectRatioFitter>();fit.aspectMode=AspectRatioFitter.AspectMode.FitInParent;fit.aspectRatio=img.texture.width/(float)img.texture.height;}}
  void ShowVerifyCapture(){
   if(GuidedFlow){StartCoroutine(ReinspectStep());return;}
   if(Current.chapter_id!="U7"){StartCoroutine(Verify());return;}
   if(Current.action_id=="holder.base"){
    var basePanel=PhotoPanel("检查底座安装 · 第 1 步");AppTheme.Label(basePanel,"请拍清立柱背面的灰色底座及上下两颗螺丝。\n通过后开放第 2 步：安装料盘支架。\n本次只检查可见安装状态，螺丝紧固仍需人工确认。",new Vector2(.05f,.48f),new Vector2(.95f,.84f),26);
    ReferenceExample(basePanel,"base_reference",new Vector2(.25f,.17f),new Vector2(.75f,.46f));AppTheme.Button(basePanel,"取消",new Vector2(.04f,.025f),new Vector2(.35f,.13f),ClosePhotoPrompt,AppIcon.Close);AppTheme.Button(basePanel,"检查安装",new Vector2(.43f,.025f),new Vector2(.96f,.13f),()=>{ClosePhotoPrompt();StartCoroutine(Verify());},AppIcon.Camera,true);return;
   }
   var panel=PhotoPanel("查看最终安装状态");AppTheme.Label(panel,"请拍清白色料盘支架与打印机立柱的连接。\n只判断可见安装状态，不检查螺丝扭矩。\n支架仍单独放在桌上时，不会判定完成。",new Vector2(.05f,.48f),new Vector2(.95f,.84f),27);
   ReferenceExample(panel,"installation_reference",new Vector2(.25f,.18f),new Vector2(.75f,.46f));
   AppTheme.Button(panel,"取消",new Vector2(.04f,.025f),new Vector2(.35f,.13f),ClosePhotoPrompt,AppIcon.Close);AppTheme.Button(panel,"检查安装",new Vector2(.43f,.025f),new Vector2(.96f,.13f),()=>{ClosePhotoPrompt();StartCoroutine(Verify());},AppIcon.Camera,true);
  }
  void ShowBaseCompleted(){var panel=PhotoPanel("底座安装检查通过",true);feedbackPinned=true;AppTheme.Label(panel,"可以继续第 2 步：安装料盘支架。\n请先人工确认螺丝已按官方说明固定。",new Vector2(.06f,.34f),new Vector2(.94f,.80f),31,AppTheme.SuccessGreen);AppTheme.Button(panel,"确认完成，进入子步骤 2",new Vector2(.08f,.08f),new Vector2(.92f,.24f),()=>{ClosePhotoPrompt();Select(Array.FindIndex(plan.actions,a=>a.action_id=="holder.slide"));},AppIcon.Check,true);}
  void ShowCompleted(){var panel=PhotoPanel("✓ 料盘支架安装检查完成",true);feedbackPinned=true;AppTheme.Label(panel,"料盘支架已安装到打印机上，\n可见连接符合本步要求。",new Vector2(.06f,.44f),new Vector2(.94f,.78f),31,AppTheme.SuccessGreen);AppTheme.Label(panel,"本次结果仅针对拍摄画面的可见安装状态。",new Vector2(.06f,.28f),new Vector2(.94f,.42f),23,AppTheme.Muted);AppTheme.Button(panel,"留在空间指导",new Vector2(.05f,.06f),new Vector2(.47f,.21f),ClosePhotoPrompt,AppIcon.Check);AppTheme.Button(panel,"返回图文指导",new Vector2(.53f,.06f),new Vector2(.95f,.21f),()=>{ClosePhotoPrompt();StartCoroutine(Close());},AppIcon.Back,true);}
  IEnumerator LocateParts(){
   if(session==null||last==null||mode!="camera"||locating){Message("请先启动摄像头或等待本次识别");yield break;}
   string previousJob=partsDisplayActive?partsJob:null;bool preserving=!string.IsNullOrEmpty(previousJob);
   if(!preserving)StopParts();vlmBrief="";int generation=partsGeneration;partsDisplayActive=true;frozen=!preserving;locating=true;int version=epoch;string identity=session.session_id;var sent=latestReply??last;var raw=latestBytes;int frame=sent.client_frame_id;
   if(!preserving&&raw!=null)RenderFrame(raw,sent);PartStatus response=null;checkResult.text=preserving?"正在重新识别，原有跟踪继续…":"正在识别底座和料盘支架…";
   yield return Request(Api+"/sessions/"+identity+"/locate","POST",JsonUtility.ToJson(new Verify{action_id=Current.action_id,target_id=TargetId,client_frame_id=frame}),(text,error)=>{if(error!=null)checkResult.text=AppTheme.Readable(error);else response=JsonUtility.FromJson<PartStatus>(text);},20);
   string candidateJob=response?.job_id;bool accepted=false;
   float deadline=Time.realtimeSinceStartup+140;
   while(response!=null&&generation==partsGeneration&&partsDisplayActive&&version==epoch&&session!=null&&session.session_id==identity&&Time.realtimeSinceStartup<deadline){
    if(response.session_id!=identity||response.job_id!=candidateJob||response.source_sha256!=sent.source_sha256||response.client_frame_id!=frame){checkResult.text="照片身份已变化，请重新识别。";break;}
    if(response.phase=="tracking"){
     if(!PartsReady(response)){checkResult.text="本次未获得可用的目标高亮，请重新识别。";break;}
     partsJob=candidateJob;accepted=true;semanticReady=true;Message("部件高亮与动画指导中");if(raw!=null)RenderFrame(raw,sent);partsView.Apply(response,sent.width,sent.height);RefreshAsset();checkResult.text=PartFeedback(response);frozen=false;locating=false;
     if(preserving)StartCoroutine(Request(Api+"/sessions/"+identity+"/parts?job_id="+previousJob,"DELETE",null,(r,e)=>{},5));
     StartCoroutine(TrackParts(identity,partsJob,version));break;
    }
    if(response.parts!=null&&!preserving){if(response.phase=="located")Message("已找到位置，正在准备分割");semanticReady=false;if(raw!=null)RenderFrame(raw,sent);PresentPartBoxes(response,sent);checkResult.text=response.phase=="located"?"已找到部件，正在分割，GPU 不可用时自动使用本机 CPU…":AppTheme.Readable(response.next_action);}
    if(response.phase=="failed"||response.phase=="not_found"||response.phase=="segmentation_unavailable"){checkResult.text="本次识别未完成，请调整画面后重试。";break;}
    yield return new WaitForSecondsRealtime(.25f);yield return Request(Api+"/sessions/"+identity+"/parts/"+candidateJob,"GET",null,(text,error)=>{if(error!=null){response.phase="failed";response.next_action=error;}else response=JsonUtility.FromJson<PartStatus>(text);},10);
   }
   if(!accepted&&!string.IsNullOrEmpty(candidateJob))StartCoroutine(Request(Api+"/sessions/"+identity+"/parts?job_id="+candidateJob,"DELETE",null,(r,e)=>{},5));
   if(generation!=partsGeneration||version!=epoch)yield break;
   locating=false;frozen=false;
   if(!accepted){if(!preserving)StopParts();checkResult.text=preserving?"本次识别未完成，原有跟踪继续；请调整画面后重试。":"本次识别未完成，请调整画面后重试。";}
   locateButton.GetComponentInChildren<Text>().text="识别部件";
  }
  void PresentPartBoxes(PartStatus value,Reply frame){
   SetBriefAdvice(value.guidance);
   partsView.Apply(value,frame.width,frame.height);RefreshAsset();
  }
  IEnumerator TrackParts(string identity,string job,int version){
   int processed=last.client_frame_id;
   while(partsDisplayActive&&partsJob==job&&session!=null&&session.session_id==identity&&version==epoch){
    if(latestReply==null||latestReply.client_frame_id<=processed){yield return null;continue;}
    var reply=latestReply;var bytes=latestBytes;PartStatus result=null;string failure=null;processed=reply.client_frame_id;
    yield return Request(Api+"/sessions/"+identity+"/parts/"+job+"/frames","POST",JsonUtility.ToJson(new Verify{action_id=reply.action_id,target_id=reply.target_id,client_frame_id=reply.client_frame_id}),(text,error)=>{failure=error;if(error==null)result=JsonUtility.FromJson<PartStatus>(text);},12);
    if(!partsDisplayActive||partsJob!=job||version!=epoch)yield break;
    if(failure!=null||result==null||result.phase!="tracking"){StopParts();checkResult.text="跟踪中断，请重新识别。";yield break;}
    if(!PresentTrackedParts(bytes,reply,result,identity,job)){partsView.Clear();continue;}
    if(!locating&&!checking)checkResult.text=PartFeedback(result);yield return new WaitForSecondsRealtime(.15f);
   }
  }
  bool PresentTrackedParts(byte[] bytes,Reply reply,PartStatus result,string identity,string job){
   if(bytes==null||reply==null||result==null||!partsDisplayActive||session==null||session.session_id!=identity||result.session_id!=identity||result.job_id!=job||result.source_sha256!=reply.source_sha256||result.client_frame_id!=reply.client_frame_id||Hash(bytes)!=reply.source_sha256)return false;
   semanticReady=PartsReady(result);SetBriefAdvice(result.guidance);RenderFrame(bytes,reply);partsView.Apply(result,reply.width,reply.height);RefreshAsset();return true;
  }
  bool PartsReady(PartStatus value){return value!=null&&value.phase=="tracking"&&!string.IsNullOrEmpty(value.overlay_png_base64)&&Array.Exists(value.parts??new LocatedPart[0],p=>p.status=="found"&&p.component_id==(Current.action_id=="holder.base"?"spool_holder_base":"external_spool_holder"));}
  string PartFeedback(PartStatus value){return AppTheme.Readable((string.IsNullOrEmpty(verificationFeedback)?"":verificationFeedback+"\n\n")+(semanticReady?"部件已高亮，请按画面示意操作。":"正在准备位置高亮，请保持画面稳定。"));}
  void SetBriefAdvice(string advice){if(string.IsNullOrEmpty(advice))return;int end=advice.IndexOf('。');if(end>0)advice=advice.Substring(0,end);vlmBrief=advice.Length>18?advice.Substring(0,18)+"…":advice;}
  void StopParts(){
   semanticReady=false;if(GuidedFlow&&overlay!=null)HideGuidance();partsGeneration++;bool active=partsDisplayActive;string stoppedJob=partsJob;partsDisplayActive=false;partsJob=null;partsView?.Clear();frozen=false;locating=false;
   if(active&&session!=null&&!closed)StartCoroutine(Request(Api+"/sessions/"+session.session_id+"/parts"+(string.IsNullOrEmpty(stoppedJob)?"":"?job_id="+stoppedJob),"DELETE",null,(raw,error)=>{},5));
   if(locateButton!=null)locateButton.GetComponentInChildren<Text>().text="识别部件";
  }
 }
}
