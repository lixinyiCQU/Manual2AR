using System;
using System.Collections;
using UnityEngine;
using UnityEngine.UI;
namespace Manual2AR.Spatial {
 [Serializable] public class TaskExecution {public string contract,state_id,action_id,mode,reason,baseline_mode,session_id,task_sha256,task_summary,current_step,goal_title,user_summary,user_feedback;public int epoch,revision;public BaselineCondition[] manual_conditions;public BaselineVisualCondition[] visual_conditions,scene_conditions;public bool complete,needs_assessment,prerequisite_only,guidance_ready;public string[] completed_state_ids,remaining_state_ids,target_node_ids,needed_node_ids;public BaselineStep[] steps;}
 [Serializable] public class BaselineStep {public string node_id,action_id,instruction,status;public bool is_target,prerequisite_only,current;public int index,total;}
 public sealed partial class SpatialGuidanceController {
  [Serializable] class SceneEvaluation {public TaskExecution execution;public string action_id,source_sha256;public int client_frame_id;}
  TaskExecution execution;bool assessingScene;string attemptedScene="";
  bool Stateful {get{return plan!=null&&plan.stateful_runtime;}}
  bool NeedsSceneCheck {get{return Stateful&&(execution==null||execution.mode!="operate");}}
  void ApplyExecution(TaskExecution value){
   if(!Stateful||value==null)return;
   if(Baseline&&execution!=null&&value.revision<execution.revision)return;
   if(execution==null||execution.mode!=value.mode||execution.action_id!=value.action_id){guidedStarted=false;semanticReady=false;HideGuidance();}
   execution=value;
   RefreshBaselineSummary();
   verify.GetComponentInChildren<Text>().text=value.prerequisite_only?"核验前置条件":value.mode=="operate"?"检查安装":"核验现状";
   locateButton.GetComponentInChildren<Text>().text=NeedsSceneCheck?"重新评估现场":"识别部件";
   if(Baseline)verify.GetComponentInChildren<Text>().text=value.baseline_mode=="ask_manual"?"人工确认":"拍照核验";
  }
  void UpdateExecution(Reply reply){
   if(!Stateful)return;ApplyExecution(reply.execution);
   if(Baseline)return;
   string key=session==null?"":session.session_id+":"+Current.action_id;
   if(execution!=null&&execution.needs_assessment&&execution.action_id==Current.action_id&&!assessingScene&&attemptedScene!=key){attemptedScene=key;StartCoroutine(AssessCurrentScene());}
  }
  IEnumerator AssessCurrentScene(){
   if(!Stateful||session==null||last==null||assessingScene||checking)yield break;
   if(Baseline){yield return CheckBaseline(false);yield break;}
   assessingScene=true;int version=epoch;string identity=session.session_id;var sent=last;
   checkResult.text="正在对照官方参考评估部件与当前安装状态…";
   try{
    yield return Request(Api+"/sessions/"+identity+"/assess","POST",JsonUtility.ToJson(new Verify{action_id=Current.action_id,target_id=TargetId,client_frame_id=sent.client_frame_id}),(raw,error)=>{
     if(version!=epoch||session==null||session.session_id!=identity)return;
     if(error!=null){checkResult.text=error;return;}var result=JsonUtility.FromJson<SceneEvaluation>(raw);
     if(result.action_id!=Current.action_id||result.source_sha256!=sent.source_sha256||result.client_frame_id!=sent.client_frame_id)return;
     ApplyExecution(result.execution);checkResult.text=AppTheme.Readable(result.execution.reason+"\n评估仅选择操作或检查；完成状态仍需当前现场核验。");
    },150);
   }finally{assessingScene=false;}
  }
  bool RefreshExecutionPreparation(){
   if(!NeedsSceneCheck||execution==null||setupExplicit||authorStage>0)return false;
   startAtTarget.gameObject.SetActive(false);status.text=AppTheme.Readable(Baseline?execution.user_feedback:execution.reason);
   if(string.IsNullOrEmpty(verificationFeedback)&&!assessingScene&&!checking)checkResult.text=AppTheme.Readable(Baseline?execution.user_feedback:execution.reason+"\n请按当前阶段按钮提交照片。");
   return true;
  }
  void ShowExecutionCompleted(){
   var panel=PhotoPanel(execution!=null&&execution.complete?"当前任务核验完成":"当前步骤核验完成",true);feedbackPinned=true;
   AppTheme.Label(panel,Baseline?"照片检查和人工确认均已通过，任务完成。":"已满足本候选核验条件。\n请确认已按官方要求实际检查；照片不能确认机械紧固。",new Vector2(.06f,.34f),new Vector2(.94f,.80f),27,AppTheme.SuccessGreen);
   bool complete=execution!=null&&execution.complete;string next=execution?.action_id;
   AppTheme.Button(panel,complete?(Baseline?"返回任务列表":"确认并返回生成任务"):"继续下一项操作或检查",new Vector2(.08f,.08f),new Vector2(.92f,.24f),()=>{ClosePhotoPrompt();if(complete)StartCoroutine(Close());else {int index=Array.FindIndex(plan.actions,a=>a.action_id==next);if(index>=0)Select(index);}},AppIcon.Check,true);
  }
 }
}
