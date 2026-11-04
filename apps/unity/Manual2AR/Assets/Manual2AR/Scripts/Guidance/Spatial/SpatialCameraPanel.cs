using UnityEngine;
using UnityEngine.UI;
namespace Manual2AR.Spatial {
 public sealed partial class SpatialGuidanceController {
  void ShowCameraSettings(){
   if(changing||checking||authorStage>0){Message("请先完成当前操作");return;}
   var panel=PhotoPanel("摄像头管理");
   AppTheme.Label(panel,"画幅改变后会重新建立相机会话，请使用对应标定。",new Vector2(.06f,.67f),new Vector2(.94f,.82f),25);
   aspectSelector=AppAspectSelector.Create(panel,new Vector2(.06f,.45f),new Vector2(.94f,.62f),ChooseAspect);aspectSelector.Select(aspectIndex);
   AppTheme.Button(panel,"启动摄像头",new Vector2(.06f,.24f),new Vector2(.48f,.39f),()=>{ClosePhotoPrompt();StartCoroutine(BeginSession("camera",false));},AppIcon.Camera,true);
   AppTheme.Button(panel,"切换镜头",new Vector2(.52f,.24f),new Vector2(.94f,.39f),()=>{cameraIndex++;ClosePhotoPrompt();StartCoroutine(BeginSession("camera",false));},AppIcon.SwitchCamera);
   AppTheme.Button(panel,"完成",new Vector2(.30f,.04f),new Vector2(.70f,.18f),ClosePhotoPrompt,AppIcon.Check);
  }
  void ShowAnchorSetup(){
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
  void ShowCheckFeedback(Check result){
   bool passed=result.status=="completed";var panel=PhotoPanel(passed?"本步检查通过":"需要调整后重新检查");
   feedbackPinned=true;
   panel.GetComponent<Image>().color=Color.Lerp(AppTheme.PanelBackground,passed?AppTheme.SuccessGreen:AppTheme.ErrorRed,.12f);
   var border=panel.gameObject.AddComponent<UnityEngine.UI.Outline>();border.effectColor=passed?AppTheme.SuccessGreen:AppTheme.ErrorRed;border.effectDistance=new Vector2(3,-3);
   var text=ScrollText(panel,"Visible installation feedback",new Vector2(.05f,.25f),new Vector2(.95f,.80f),28);
   text.text=AppTheme.Readable(result.evidence+"\n\n"+result.next_action);
   AppTheme.Button(panel,"继续调整",new Vector2(.3f,.06f),new Vector2(.7f,.20f),ClosePhotoPrompt,AppIcon.Back,true);
  }
 }
}
