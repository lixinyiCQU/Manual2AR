using System;
using System.Collections;
using UnityEngine;
using UnityEngine.UI;
namespace Manual2AR.Spatial {
 /// <summary>U7 preparation, explicit start and verification-led step entry. Recognition is never a pass.</summary>
 public sealed partial class SpatialGuidanceController {
  bool guidedStarted,semanticReady,stepRequestBusy,introRefBusy,feedbackPinned;string verificationFeedback="";Button startAtTarget;
  bool GuidedFlow {get{return plan!=null&&Current.chapter_id=="U7"&&mode=="camera";}}
  void BuildPreflightButton(){
   startAtTarget=AppTheme.Button(viewport,"开始本步",Vector2.zero,Vector2.zero,()=>StartCoroutine(StartPrepared()),AppIcon.Check,true);
   var rect=(RectTransform)startAtTarget.transform;rect.pivot=new Vector2(.5f,.5f);rect.sizeDelta=new Vector2(220,58);startAtTarget.gameObject.SetActive(false);
  }
  void RefreshPreparation(Reply reply){
   bool preparing=GuidedFlow&&!guidedStarted&&authorStage==0&&!setupExplicit;var state=reply.preflight;
   bool ready=preparing&&state!=null&&state.can_start;
   startAtTarget.gameObject.SetActive(ready);
   if(ready){var rect=(RectTransform)startAtTarget.transform;var size=viewport.rect.size;rect.anchoredPosition=new Vector2(Mathf.Clamp(state.anchor.x/reply.width*size.x,110,size.x-110),Mathf.Clamp((1-state.anchor.y/reply.height)*size.y+60,30,size.y-30));}
   if(!preparing||state==null)return;
   if(!reply.calibrated)status.text="请先完成当前画幅的相机标定";
   else if(!state.marker_visible)status.text="请放置固定定位标记，并让完整标记入镜";
   else if(!state.has_cached_target)status.text="已找到标记，请配置当前步骤的空间锚点";
   else if(!ready)status.text="请让操作位置入镜";
   else status.text="准备就绪，请在操作位置点击开始";
   checkResult.text=ready?"已找到缓存的操作位置。确认标记与打印机未发生相对移动，再点击画面上的开始按钮。":!reply.calibrated?"打开空间锚点配置，完成相机标定。":"保持打印机和标记固定，调整相机让标记及操作区域同时入镜。";
  }
  IEnumerator StartPrepared(){
   if(session==null||last?.preflight==null||!last.preflight.can_start||changing)yield break;
   changing=true;string failure=null;string id=session.session_id;
   yield return Request(Api+"/sessions/"+id+"/reuse","POST","{\"confirmed\":true}",(raw,error)=>failure=error);
   changing=false;if(failure!=null){Message(failure);yield break;}
   guidedStarted=true;semanticReady=false;startAtTarget.gameObject.SetActive(false);setupExplicit=false;SetSetupVisible(false);ShowStepIntroduction(true);
  }
  void ShowStepIntroduction(bool startAfterClose){
   if(plan==null)return;int version=epoch;
   var panel=PhotoPanel(Current.title);
   var text=ScrollText(panel,"Official step instruction",new Vector2(.05f,.53f),new Vector2(.95f,.85f),26);text.text=AppTheme.Readable(Current.instruction);
   var slot=AppTheme.Rect(panel,"Official reference",new Vector2(.15f,.20f),new Vector2(.85f,.52f));var img=AppTheme.Rect(slot,"Step reference image",Vector2.zero,Vector2.one).gameObject.AddComponent<RawImage>();img.color=Color.white;
   if(referenceTexture!=null){img.texture=referenceTexture;var fit=img.gameObject.AddComponent<AspectRatioFitter>();fit.aspectMode=AspectRatioFitter.AspectMode.FitInParent;fit.aspectRatio=referenceTexture.width/(float)referenceTexture.height;}else ReferenceExample(slot,Current.action_id=="holder.base"?"base_reference":"installation_reference",Vector2.zero,Vector2.one);
   var caption=AppTheme.Label(panel,"官方图 "+(referenceIndex+1)+" / "+Current.reference_images.Length,new Vector2(.20f,.135f),new Vector2(.80f,.19f),21,AppTheme.Muted);caption.alignment=TextAnchor.MiddleCenter;
   AppTheme.Button(panel,"上一图",new Vector2(.025f,.28f),new Vector2(.145f,.39f),()=>StartCoroutine(ChangeIntroReference(-1,img,caption,version)),AppIcon.Back);
   AppTheme.Button(panel,"下一图",new Vector2(.855f,.28f),new Vector2(.975f,.39f),()=>StartCoroutine(ChangeIntroReference(1,img,caption,version)),AppIcon.SwitchCamera);
   AppTheme.Button(panel,"放大参考图",new Vector2(.05f,.025f),new Vector2(.38f,.13f),()=>EnlargeReference(),AppIcon.Inspect);
   AppTheme.Button(panel,startAfterClose?(Current.action_id=="holder.slide"?"准备拍照识别":"开始指导"):"收起图文",new Vector2(.44f,.025f),new Vector2(.95f,.13f),()=>{ClosePhotoPrompt();if(startAfterClose&&version==epoch){if(Current.action_id=="holder.slide")PromptManualRecognition();else StartCoroutine(AutoLocateStep(version));}},AppIcon.Check,true);
  }
  IEnumerator ChangeIntroReference(int direction,RawImage image,Text caption,int version){
   if(introRefBusy)yield break;introRefBusy=true;
   try{referenceIndex+=direction;image.texture=null;image.color=Color.clear;yield return LoadReference();if(image==null||version!=epoch||referenceTexture==null)yield break;image.texture=referenceTexture;image.color=Color.white;var fit=image.GetComponent<AspectRatioFitter>();if(fit==null)fit=image.gameObject.AddComponent<AspectRatioFitter>();fit.aspectMode=AspectRatioFitter.AspectMode.FitInParent;fit.aspectRatio=referenceTexture.width/(float)referenceTexture.height;caption.text="官方图 "+(referenceIndex+1)+" / "+Current.reference_images.Length;}finally{introRefBusy=false;}
  }
  IEnumerator EnterSelectedStep(int version){
   float deadline=Time.realtimeSinceStartup+8;
   while(version==epoch&&session!=null&&(last==null||last.action_id!=Current.action_id)&&Time.realtimeSinceStartup<deadline)yield return null;
   if(version==epoch&&session!=null)ShowStepIntroduction(true);
  }
  void PromptManualRecognition(){
   semanticReady=false;checkResult.text="请让灰色底座和白色料盘支架同时入镜，摆好后点击“识别部件”。";
  }
  IEnumerator AutoLocateStep(int version){
   if(!GuidedFlow||!guidedStarted||version!=epoch||session==null)yield break;
   if(Current.action_id=="holder.slide"){PromptManualRecognition();yield break;}
   checkResult.text="正在准备当前步骤的定位画面…";
   float deadline=Time.realtimeSinceStartup+8;
   while(version==epoch&&session!=null&&(last==null||!last.target_ready||last.action_id!=Current.action_id||latestReply==null||latestReply.client_frame_id!=last.client_frame_id)&&Time.realtimeSinceStartup<deadline)yield return null;
   if(version!=epoch||session==null)yield break;
   if(last==null||!last.target_ready||last.action_id!=Current.action_id){checkResult.text="请让标记和操作位置清晰入镜；位置仍未就绪时，请检查空间锚点配置。";yield break;}
   checkResult.text="正在拍照识别本步部件，随后显示位置与安装建议…";
   yield return LocateParts();
  }
  IEnumerator ReinspectStep(){
   if(session==null||!guidedStarted||checking||changing||stepRequestBusy||authorStage>0)yield break;
   stepRequestBusy=true;try{
   int version=epoch,previous=last==null?0:last.client_frame_id;float deadline=Time.realtimeSinceStartup+5;
   while(version==epoch&&session!=null&&(last==null||last.client_frame_id<=previous)&&Time.realtimeSinceStartup<deadline)yield return null;
   if(version!=epoch||session==null||last==null||last.client_frame_id<=previous){Message("请重新取景后再检查");yield break;}
   yield return Verify();

   }finally{stepRequestBusy=false;}
  }
 }
}
