using UnityEngine;
using UnityEngine.UI;
namespace Manual2AR.Spatial {
 public sealed partial class SpatialGuidanceController {
  void ShowCameraSettings(){
   if(changing||checking||authorStage>0||automaticBusy){Message("请先完成当前操作");return;}
   var panel=PhotoPanel("摄像头管理");
   AppTheme.Label(panel,"画幅改变后会重新建立相机会话，请使用对应标定。",new Vector2(.06f,.67f),new Vector2(.94f,.82f),25);
   aspectSelector=AppAspectSelector.Create(panel,new Vector2(.06f,.45f),new Vector2(.94f,.62f),ChooseAspect);aspectSelector.Select(aspectIndex);
   AppTheme.Button(panel,"启动摄像头",new Vector2(.06f,.24f),new Vector2(.48f,.39f),()=>{ClosePhotoPrompt();StartCoroutine(BeginSession("camera",false));},AppIcon.Camera,true);
   AppTheme.Button(panel,"切换镜头",new Vector2(.52f,.24f),new Vector2(.94f,.39f),()=>{cameraIndex++;ClosePhotoPrompt();StartCoroutine(BeginSession("camera",false));},AppIcon.SwitchCamera);
   AppTheme.Button(panel,"完成",new Vector2(.30f,.04f),new Vector2(.70f,.18f),ClosePhotoPrompt,AppIcon.Check);
  }
  void ShowManualAnchorSetup(){
   if(plan==null||session==null||changing||checking||locating){Message("请先启动相机并完成当前操作");return;}
   var panel=PhotoPanel("空间锚点配置");
   var targets=Current.target_instances??new TargetInstance[0];
   AppTheme.Label(panel,"仅在安装或标记位置改变时调整。两颗螺丝分别保存标定点，教学时同时显示。",new Vector2(.05f,.68f),new Vector2(.95f,.83f),25);
   for(int i=0;i<targets.Length;i++){int selected=i;float top=.64f-i*.11f;
    AppTheme.Button(panel,targets[i].label+" · 配置作用点",new Vector2(.08f,top-.09f),new Vector2(.92f,top),()=>{ClosePhotoPrompt();SelectTarget(selected);setupExplicit=true;SetSetupVisible(true);StartCoroutine(AuthorStep());},AppIcon.Inspect);
   }
   AppTheme.Button(panel,"相机及工作坐标设置",new Vector2(.08f,.12f),new Vector2(.66f,.23f),()=>{ClosePhotoPrompt();setupExplicit=true;SetSetupVisible(true);},AppIcon.Inspect);
   AppTheme.Button(panel,"返回",new Vector2(.70f,.12f),new Vector2(.92f,.23f),ClosePhotoPrompt,AppIcon.Back);
  }
  Image feedbackBackground;bool verificationFailed;float feedbackStarted;
  void ResetCheckFeedback(){
   verificationFeedback="";verificationFailed=false;
   if(feedbackBackground!=null)feedbackBackground.color=Color.clear;
   if(checkResult!=null)checkResult.color=Color.white;
  }
  void ShowCheckFailure(){
   verificationFailed=true;feedbackStarted=Time.unscaledTime;
   checkResult.text=verificationFeedback;checkResult.color=new Color(1,.88f,.85f);
   var scroll=feedbackBackground.GetComponent<ScrollRect>();Canvas.ForceUpdateCanvases();scroll.verticalNormalizedPosition=1;
   RefreshCheckHighlight();
  }
  void RefreshCheckHighlight(){
   if(!verificationFailed||feedbackBackground==null)return;
   float elapsed=Time.unscaledTime-feedbackStarted;
   // Three gentle pulses, then retain a steady error surface until the next check.
   float strength=elapsed<4.5f?.17f+.09f*(1-Mathf.Cos(elapsed*Mathf.PI*2/1.5f)):.17f;
   feedbackBackground.color=Color.Lerp(AppTheme.PanelBackground,AppTheme.ErrorRed,strength);
  }
  void ShowCheckFeedback(Check result){
   if(result.status!="completed"){ShowCheckFailure();return;}
   var panel=PhotoPanel("本步检查通过",true);feedbackPinned=true;
   var text=ScrollText(panel,"Visible installation feedback",new Vector2(.06f,.28f),new Vector2(.94f,.80f),30);
   text.text=AppTheme.Readable(result.evidence+"\n\n"+result.next_action);
   AppTheme.Button(panel,"继续指导",new Vector2(.25f,.07f),new Vector2(.75f,.23f),ClosePhotoPrompt,AppIcon.Check,true);
  }
 }
}
