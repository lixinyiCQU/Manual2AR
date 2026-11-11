using System;
using UnityEngine;
namespace Manual2AR.Spatial {
 public sealed partial class SpatialGuidanceController {
  [Serializable] class CompiledCheck {public string[] manual_pending;}
  [Serializable] class ManualConditions {public string action_id;public string[] inspection_ids;public bool confirmed=true;}
  void ShowCompiledManual(string[] ids){
   var dialog=AppDialog.Open(root,"Compiled manual conditions","候选包含人工确认条件",AppDialogSize.Standard,null);
   var text=AppTheme.Label(dialog.Panel,"请阅读右侧核验反馈。照片无法确认以下条件：\n"+string.Join("、",ids)+"\n\n只有你已按候选要求实际核实时才确认；传感器条件仍须补充证据。",new Vector2(.06f,.30f),new Vector2(.94f,.82f),AppTheme.BodySize);AppReadableText.Attach(text);
   AppTheme.Button(dialog.Panel,"已逐项人工核实",new Vector2(.06f,.06f),new Vector2(.61f,.21f),()=>{dialog.Close();StartCoroutine(ConfirmCompiled(ids));},AppIcon.Check,true);
   AppTheme.Button(dialog.Panel,"暂不确认",new Vector2(.65f,.06f),new Vector2(.94f,.21f),dialog.Close,AppIcon.Close);
  }
  System.Collections.IEnumerator ConfirmCompiled(string[] ids){
   if(session==null)yield break;int version=epoch;
   yield return Request(Api+"/sessions/"+session.session_id+"/manual-conditions","POST",JsonUtility.ToJson(new ManualConditions{action_id=Current.action_id,inspection_ids=ids}),(raw,error)=>{
    if(version!=epoch)return;if(error!=null){checkResult.text=error;return;}
    var result=JsonUtility.FromJson<Check>(raw);ApplyExecution(result.execution);u7Sequence=result.u7_sequence;checkResult.text=result.evidence;
    if(result.status=="completed"&&Stateful&&result.prerequisite_only){checkResult.text="前置条件已核实，请继续当前操作或检查。";return;}
    if(result.status=="completed")ShowCompiledCompleted(Current.action_id=="holder.base");
   });
  }
  void ShowCompiledCompleted(bool baseStep){
   if(Stateful){ShowExecutionCompleted();return;}
   var panel=PhotoPanel("当前核验条件已满足",true);feedbackPinned=true;
   AppTheme.Label(panel,"请确认已按官方要求实际操作。\n照片仅检查可见状态，不能确认真正紧固。",new Vector2(.06f,.34f),new Vector2(.94f,.80f),29,AppTheme.SuccessGreen);
   AppTheme.Button(panel,baseStep?"已按要求操作，继续下一步":"确认并返回生成任务",new Vector2(.08f,.08f),new Vector2(.92f,.24f),()=>{ClosePhotoPrompt();if(baseStep)Select(Array.FindIndex(plan.actions,a=>a.action_id=="holder.slide"));else StartCoroutine(Close());},AppIcon.Check,true);
  }
 }
}
