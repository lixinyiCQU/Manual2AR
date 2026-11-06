using System;
using UnityEngine;
using UnityEngine.UI;
namespace Manual2AR.Spatial {
 public sealed partial class SpatialGuidanceController {
  bool authorMachine;
  void ShowMachineSetup(){
   if(session==null||last==null||!last.calibrated||mode!="camera"){Message("请先启动摄像头并完成当前画幅标定");return;}
   if(authorStage!=0||changing||checking){Message("请先完成或取消当前设置");return;}
   OpenMachineIntro();
  }
  void OpenMachineIntro(){
   StopParts();var panel=PhotoPanel("打印机工作坐标系 · 一次设置，多动作复用");
   AppTheme.Label(panel,"每个视角依次点击同样的三个固定实物点：\n\nO  原点：选择固定机架上 X、Z 方向相交的角点。\nX  沿横梁方向选固定点：从设备正面看向右为 +X。\nZ  从原点沿立柱向上 +Z 方向选择一点。\n\nX、Z 应互相垂直，距原点 25–400 mm。\n系统按右手规则计算 Y；不要选择可移动的热床或工具头。",new Vector2(.05f,.24f),new Vector2(.95f,.85f),25);
   AppTheme.Label(panel,"这是教学工作坐标，不是设备固件的机械零点；定位标记与机架必须固定。",new Vector2(.05f,.14f),new Vector2(.95f,.25f),21,AppTheme.Muted);
   AppTheme.Button(panel,"取消",new Vector2(.05f,.025f),new Vector2(.34f,.12f),ClosePhotoPrompt,AppIcon.Close);
   AppTheme.Button(panel,"固定第一视角并选三点",new Vector2(.40f,.025f),new Vector2(.95f,.12f),()=>{ClosePhotoPrompt();CancelAuthor();authorMachine=true;setupExplicit=true;SetSetupVisible(true);StartCoroutine(AuthorStep());},AppIcon.Inspect,true);
  }
  void ShowMotionSettings(){
   if(plan==null||Current.chapter_id!="U7"){Message("当前仅 U7 支持工作坐标系动作参数");return;}
   if(session==null||last==null||authorStage!=0||changing||checking||locating){Message("请先完成当前操作并启动摄像头");return;}
   var current=last.motion_parameters??Current.machine_motion??new MotionParameters();
   if(last.visual?.presentation?.instances==null||last.visual.presentation.instances.Length==0){Message("请让定位标记和操作位置入镜，等待动画就绪");return;}
   SpatialActionPanel.Open(root,current,last.visual.presentation,Current.kind=="fasten",HasMachineReference(last.machine_frame),value=>StartCoroutine(SaveMotion(value)),ShowMachineSetup);
  }
  System.Collections.IEnumerator SaveMotion(MotionParameters value){
   StopParts();epoch++;last=null;ClearGraphics();yield return Request(Api+"/sessions/"+session.session_id+"/motion","POST",JsonUtility.ToJson(new MotionCommand{action_id=Current.action_id,parameters=value}),(raw,error)=>Message(error??"动作参数已保存 · 空间动画已更新"));
  }
 }
}
