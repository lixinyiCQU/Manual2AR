using System;
using System.Collections;
using System.Text;
using UnityEngine;
using UnityEngine.UI;

namespace Manual2AR.Spatial {
 public sealed partial class SpatialGuidanceController {
  [Serializable] class GoalQuestion {public string intent;}
  [Serializable] class GoalStep {public string node_id,instruction;public bool is_target,prerequisite_only;}
  [Serializable] class GoalPreview {public string status,goal_title,requested_intent,interpretation,message,task_sha256;public string[] selected_node_ids;public GoalStep[] official_steps;}
  string goalIntent="";
  bool goalConfirmed;
  Text taskSummary;
  string lastTaskSummary="";
  bool CompiledBaseline {get{return Baseline&&Api.StartsWith("/api/guidance/compiled/jobs/",StringComparison.Ordinal);}}

  void RefreshBaselineSummary(){
   if(!Baseline||taskSummary==null)return;
   string summary=execution!=null&&!string.IsNullOrEmpty(execution.user_summary)?execution.user_summary:
    !string.IsNullOrEmpty(plan?.goal_overview)?plan.goal_overview:"请先确定本次目标，再拍摄现场。系统会展示当前进度与剩余操作。";
   if(execution!=null&&!string.IsNullOrEmpty(execution.current_step))summary="当前操作："+execution.current_step+"\n\n"+summary;
   SetBaselineSummary(summary);
  }

  void SetBaselineSummary(string summary){
   if(taskSummary==null||summary==lastTaskSummary)return;
   lastTaskSummary=summary;taskSummary.text=AppTheme.Readable(summary);
  }

  void ShowBaselineGoalChoice(){
   if(!Baseline||plan==null)return;
   if(!CompiledBaseline){
    var info=PhotoPanel("当前任务范围");
    var body=ScrollText(info,"Current task goal",new Vector2(.06f,.25f),new Vector2(.94f,.84f),25);
    body.text=taskSummary.text;
    AppTheme.Button(info,"返回指导",new Vector2(.25f,.06f),new Vector2(.75f,.20f),ClosePhotoPrompt,AppIcon.Back);
    return;
   }
   if(changing||checking||locating||automaticBusy||authorStage>0){Message("请先完成当前操作，再选择任务目标。");return;}
   var panel=PhotoPanel(session==null?"选择本次任务目标":"切换目标并重新评估");
   AppTheme.Label(panel,session==null?"输入本次希望完成的任务，系统将对应到官方操作。":"切换目标将建立新会话，重新评估现场；原会话记录保留。",new Vector2(.05f,.77f),new Vector2(.95f,.86f),23,AppTheme.TargetCyan);
   var field=AppTheme.Panel(panel,"Goal intent",new Vector2(.05f,.61f),new Vector2(.95f,.75f));
   var input=field.gameObject.AddComponent<InputField>();input.targetGraphic=field.GetComponent<Image>();input.characterLimit=1000;input.lineType=InputField.LineType.MultiLineNewline;
   input.textComponent=AppTheme.Label(field,"",new Vector2(.03f,.05f),new Vector2(.97f,.95f),25);input.textComponent.supportRichText=false;
   input.placeholder=AppTheme.Label(field,"安装料盘支架／安装支架底座／将支架滑入底座",new Vector2(.03f,.05f),new Vector2(.97f,.95f),23,AppTheme.Muted);
   input.text=string.IsNullOrWhiteSpace(goalIntent)?plan.default_goal_intent??"":goalIntent;
   var result=ScrollText(panel,"Official goal match",new Vector2(.05f,.23f),new Vector2(.95f,.59f),23);
   result.text="匹配后会列出本次目标、必要前置操作及官方最细步骤。照片用于判断进度，不会自动改变目标范围。";
   GoalPreview preview=null;bool pending=false;
   var accept=AppTheme.Button(panel,session==null?"使用此目标":"切换目标并重新评估",new Vector2(.51f,.04f),new Vector2(.95f,.19f),()=>{
    if(preview==null||preview.status!="matched"||pending)return;
    goalIntent=input.text.Trim();goalConfirmed=true;
    SetBaselineSummary(GoalDescription(preview));
    ClosePhotoPrompt();
    if(session!=null)StartCoroutine(BeginSession(mode,false));
    else {verificationFeedback="目标已确定。请在摄像头管理中启动镜头，拍摄安装现场。";checkResult.text=AppTheme.Readable(verificationFeedback);}
   },AppIcon.Check,true);accept.interactable=false;
   Button match=null;
   match=AppTheme.Button(panel,"对应官方步骤",new Vector2(.05f,.04f),new Vector2(.48f,.19f),()=>{
    if(pending||string.IsNullOrWhiteSpace(input.text))return;
    pending=true;accept.interactable=false;match.interactable=false;input.interactable=false;result.text="正在核对官方任务和目标范围…";
    string requested=input.text.Trim();int version=epoch;
    StartCoroutine(PreviewBaselineGoal(requested,(value,error)=>{
     if(panel==null||version!=epoch)return;
     pending=false;input.interactable=true;match.interactable=true;
     preview=value;result.text=AppTheme.Readable(error??GoalDescription(value));
     accept.interactable=error==null&&value!=null&&value.status=="matched";
    }));
   },AppIcon.Inspect);
   input.onValueChanged.AddListener(_=>{preview=null;accept.interactable=false;});
  }

  IEnumerator PreviewBaselineGoal(string intent,Action<GoalPreview,string> receive){
   yield return Request(Api+"/goal-preview","POST",JsonUtility.ToJson(new GoalQuestion{intent=intent}),(raw,error)=>{
    if(error!=null){receive(null,error);return;}
    GoalPreview value;
    try{value=JsonUtility.FromJson<GoalPreview>(raw);}catch(ArgumentException){receive(null,"任务匹配结果格式无效，请重新核对。");return;}
    if(value==null||value.task_sha256!=plan.task_sha256||value.requested_intent!=intent){receive(null,"任务版本或目标已改变，请返回后重新打开。");return;}
    receive(value,null);
   });
  }

  static string GoalDescription(GoalPreview value){
   if(value==null)return "尚未取得任务匹配结果。";
   var text=new StringBuilder();
   if(!string.IsNullOrEmpty(value.goal_title))text.Append("本次目标：").Append(value.goal_title).Append('\n');
   text.Append(value.message);
   if(!string.IsNullOrEmpty(value.interpretation))text.Append("\n目标解释：").Append(value.interpretation);
   if(value.official_steps!=null){
    text.Append("\n\n官方操作路径：");
    for(int i=0;i<value.official_steps.Length;i++){
     var step=value.official_steps[i];text.Append('\n').Append(i+1).Append("．").Append(step.instruction);
     if(step.prerequisite_only)text.Append("（必要前置）");
    }
   }
   return text.ToString();
  }

  IEnumerator EnterBaselineGuidance(string action){
   int version=epoch;string identity=session?.session_id;
   float deadline=Time.realtimeSinceStartup+8;
   while(version==epoch&&session!=null&&session.session_id==identity&&(checking||last==null||last.action_id!=action)&&Time.realtimeSinceStartup<deadline)yield return null;
   if(version!=epoch||session==null||session.session_id!=identity||execution==null||execution.action_id!=action||execution.mode!="operate")yield break;
   var panel=PhotoPanel("进入下一操作的 AR 指导");
   var text=ScrollText(panel,"Next official operation",new Vector2(.06f,.34f),new Vector2(.94f,.84f),26);
   bool positioned=last?.preflight!=null&&last.preflight.can_start;
   string placement=positioned?"请实际确认定位标记与打印机、安装区域未发生相对移动，再沿用已保存位置进入指导。":"AR 显示位置尚未准备好，请先完成相机标定或空间锚点配置。";
   text.text=AppTheme.Readable("当前操作："+(execution.current_step??Current.title)+"\n\n完成本步后，点击“拍照核验”。\n\n"+placement);
   AppTheme.Button(panel,positioned?"确认位置未移动，进入指导":"配置 AR 显示位置",new Vector2(.08f,.07f),new Vector2(.92f,.25f),()=>{
    ClosePhotoPrompt();if(version!=epoch)return;
    if(positioned&&last?.preflight!=null&&last.preflight.can_start)StartCoroutine(StartPrepared());
    else if(last!=null&&last.calibrated)ShowAnchorSetup();
    else ShowCameraSettings();
   },AppIcon.Check,true);
  }
 }
}
