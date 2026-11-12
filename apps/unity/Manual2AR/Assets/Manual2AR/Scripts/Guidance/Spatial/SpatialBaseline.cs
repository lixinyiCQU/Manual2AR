using System;
using System.Collections;
using System.Text;
using UnityEngine;
using UnityEngine.UI;
namespace Manual2AR.Spatial {
 [Serializable] public class BaselineCondition {public string id,statement;}
 [Serializable] public class BaselineVisualCondition {public string id,statement,value,evidence;public bool retained;public int step_index;}
 public sealed partial class SpatialGuidanceController {
  bool baselineEntry;
  bool baselineVerificationStage;
  bool baselineRetryOnly;
  string baselineResultTitle="现场评估结果";
  bool Baseline {get{return baselineEntry||Api=="/api/guidance/baseline/spatial";}}
  [Serializable] class BaselineCheck {public TaskExecution execution;public string action_id,source_sha256,feedback;public int client_frame_id;}
  [Serializable] class BaselineManual {public string action_id,statement,session_id,task_sha256;public string[] condition_ids;public int epoch,revision;}
  public static SpatialGuidanceController OpenBaseline(string backend,Action onClose){
   var controller=new GameObject("U7 Baseline Closed Loop").AddComponent<SpatialGuidanceController>();
   controller.origin=backend.TrimEnd('/');controller.Api="/api/guidance/baseline/spatial";
   controller.done=onClose;controller.Build();controller.StartCoroutine(controller.Initialize("U7"));return controller;
  }
  public static SpatialGuidanceController OpenCompiledBaseline(string backend,string job,Action onClose,string intent=""){
   Guid identity;if(!Guid.TryParseExact(job,"N",out identity))throw new ArgumentException("Invalid compiled job identity");
   var controller=new GameObject("Official Compiled Baseline").AddComponent<SpatialGuidanceController>();
   controller.origin=backend.TrimEnd('/');controller.Api="/api/guidance/compiled/jobs/"+job+"/spatial";controller.baselineEntry=true;controller.goalIntent=intent??"";
   controller.done=onClose;controller.Build();controller.StartCoroutine(controller.Initialize("U7"));return controller;
  }
  void ApplyBaseline(TaskExecution value){
   ApplyExecution(value);
   if(value!=null&&!value.complete&&Current.action_id!=value.action_id){
    int index=Array.FindIndex(plan.actions,a=>a.action_id==value.action_id);
    if(index>=0)Select(index);
   }
  }
  IEnumerator CheckBaseline(bool allowManual){return CheckBaselinePhoto(allowManual,false);}
  IEnumerator CheckBaselinePhoto(bool allowManual,bool retake){
   if(session==null||last==null||changing||checking||assessingScene)yield break;
   if(allowManual&&!retake&&execution!=null&&execution.baseline_mode=="ask_manual"){
    ShowBaselineManual(execution);yield break;
   }
   checking=true;ClosePhotoPrompt();ResetCheckFeedback();HideGuidance();int version=epoch;string identity=session.session_id;var sent=last;
   baselineResultTitle=allowManual?"操作核验结果":"现场评估结果";
   verificationFeedback=AppTheme.Readable(allowManual?"正在核验，请稍候…":"正在评估现场，请稍候…");checkResult.text=verificationFeedback;
   try{
    yield return Request(Api+"/sessions/"+identity+(allowManual?"/verify":"/assess"),"POST",JsonUtility.ToJson(new Verify{action_id=Current.action_id,target_id=TargetId,client_frame_id=sent.client_frame_id}),(raw,error)=>{
     if(version!=epoch||session==null||session.session_id!=identity)return;
     if(error!=null){verificationFeedback="本次未能完成核验，请重试。进度未更新。";ShowCheckFailure();return;}
     var result=JsonUtility.FromJson<BaselineCheck>(raw);
     if(result.action_id!=sent.action_id||result.client_frame_id!=sent.client_frame_id||result.source_sha256!=sent.source_sha256){verificationFeedback="核验结果与本次照片不匹配，请重新拍照；未采用该结果。";ShowCheckFailure();return;}
     ApplyBaseline(result.execution);verificationFeedback=AppTheme.Readable(result.execution.user_feedback);checkResult.text=verificationFeedback;
     baselineVerificationStage=allowManual||result.execution.mode=="operate"||result.execution.complete;
     baselineRetryOnly=allowManual&&result.execution.action_id==sent.action_id&&!result.execution.complete&&result.execution.baseline_mode!="ask_manual";
     if(result.execution.baseline_mode=="request_view")ShowCheckFailure();
     ShowBaselineManual(result.execution);
    },300);
   }finally{checking=false;}
  }
  void ShowBaselineManual(TaskExecution value){
   if(session==null||value==null)return;
   if(value.completed_state_ids!=null&&value.completed_state_ids.Length>0)baselineVerificationStage=true;
   var conditions=value.baseline_mode=="ask_manual"?value.manual_conditions:null;
   bool manual=conditions!=null&&conditions.Length>0;
   string identity=session.session_id;int version=epoch;
   var panel=PhotoPanel(baselineResultTitle+(manual?" · 人工确认":""));
   var body=new StringBuilder(value.user_summary);body.Append("\n\n").Append(value.user_feedback);
   foreach(var row in value.visual_conditions??new BaselineVisualCondition[0])
    if(row.value!="true")body.Append("\n\n待核实：").Append(row.statement);
   AppTheme.Button(panel,"查看识别详情",new Vector2(.65f,.87f),new Vector2(.87f,.96f),()=>ShowBaselineDetails(value),AppIcon.Info);
   if(manual){
    var currentText=AppTheme.Label(panel,"当前操作："+value.current_step,new Vector2(.06f,.74f),new Vector2(.94f,.85f),24);currentText.verticalOverflow=VerticalWrapMode.Overflow;AppReadableText.Attach(currentText);
    var pending=new StringBuilder("请核实（共 ");pending.Append(conditions.Length).Append(" 项）：");
    for(int i=0;i<conditions.Length;i++)pending.Append("\n\n").Append(i+1).Append("．").Append(conditions[i].statement);
    pending.Append("\n\n核实后勾选下方确认框。");
    var manualText=ScrollText(panel,"Baseline manual conditions",new Vector2(.54f,.36f),new Vector2(.94f,.73f),24);manualText.lineSpacing=1.1f;manualText.text=AppTheme.Readable(pending.ToString());
   }
   var text=ScrollText(panel,"Baseline visual results",new Vector2(.06f,manual?.36f:.27f),new Vector2(manual?.50f:.94f,manual?.73f:.85f),24);text.text=AppTheme.Readable(body.ToString());
   if(manual){
    var accept=AppTheme.Button(panel,"确认全部并继续",new Vector2(.06f,.06f),new Vector2(.49f,.20f),()=>{
     ClosePhotoPrompt();StartCoroutine(ConfirmBaseline(value,conditions,identity,version));
    },AppIcon.Check,true);accept.interactable=false;
    var area=AppTheme.Panel(panel,"All manual conditions acknowledged",new Vector2(.06f,.24f),new Vector2(.94f,.35f));
    var toggle=area.gameObject.AddComponent<Toggle>();toggle.targetGraphic=area.GetComponent<Image>();
    var box=AppTheme.Panel(area,"Checkbox",new Vector2(.015f,.14f),new Vector2(.08f,.86f));box.GetComponent<Image>().color=AppTheme.ButtonBackground;
    var mark=AppTheme.Label(box,"✓",Vector2.zero,Vector2.one,28,AppTheme.TargetCyan);mark.alignment=TextAnchor.MiddleCenter;toggle.graphic=mark;
    AppTheme.Label(area,"以上项目均已核实",new Vector2(.11f,0),new Vector2(.97f,1),24);
    toggle.isOn=false;toggle.onValueChanged.AddListener(on=>accept.interactable=on);
    AppTheme.Button(panel,baselineVerificationStage?"重新拍照核验":"重新评估现场",new Vector2(.52f,.06f),new Vector2(.76f,.20f),()=>{
     ClosePhotoPrompt();if(version==epoch&&session!=null&&session.session_id==identity)StartCoroutine(CheckBaselinePhoto(baselineVerificationStage,true));
    },AppIcon.Camera);
    AppTheme.Button(panel,"暂不确认",new Vector2(.79f,.06f),new Vector2(.94f,.20f),ClosePhotoPrompt,AppIcon.Close);
   }else{
    AppTheme.Button(panel,value.complete?"返回任务列表":!baselineRetryOnly&&value.guidance_ready?"查看 AR 操作指导":"返回调整画面",new Vector2(.08f,.06f),new Vector2(.92f,.20f),()=>{
     ClosePhotoPrompt();if(version!=epoch||session==null||session.session_id!=identity)return;
     if(value.complete)StartCoroutine(Close());else if(!baselineRetryOnly&&value.guidance_ready)StartCoroutine(EnterBaselineGuidance(value.action_id));
    },AppIcon.Check,true);
   }
  }
  void ShowBaselineDetails(TaskExecution value){
   var panel=PhotoPanel("识别详情");var body=new StringBuilder("以下为模型观察，可能存在误认。");
   foreach(var row in value.scene_conditions??value.visual_conditions??new BaselineVisualCondition[0]){
    body.Append("\n\n第").Append(row.step_index).Append("步 · ").Append(row.statement);
    body.Append("\n判断：").Append(row.value=="true"?"可见检查通过":row.value=="false"?"未通过":"未确认");
    if(!string.IsNullOrEmpty(row.evidence))body.Append("\n模型观察：").Append(row.evidence);
    if(row.retained)body.Append("\n使用此前照片的有效记录。");
   }
   ScrollText(panel,"Baseline observation details",new Vector2(.06f,.25f),new Vector2(.94f,.85f),24).text=AppTheme.Readable(body.ToString());
   AppTheme.Button(panel,"返回检查结果",new Vector2(.08f,.06f),new Vector2(.92f,.20f),()=>ShowBaselineManual(value),AppIcon.Back);
  }
  IEnumerator ConfirmBaseline(TaskExecution token,BaselineCondition[] conditions,string identity,int version){
   if(session==null||session.session_id!=identity||version!=epoch||checking)yield break;
   checking=true;
   try{
    var ids=Array.ConvertAll(conditions,c=>c.id);var statements=Array.ConvertAll(conditions,c=>c.statement);
    var command=new BaselineManual{action_id=token.action_id,condition_ids=ids,epoch=token.epoch,revision=token.revision,session_id=token.session_id,task_sha256=token.task_sha256,statement="操作者明确逐项确认全部条件："+string.Join("；",statements)};
    yield return Request(Api+"/sessions/"+identity+"/manual-conditions","POST",JsonUtility.ToJson(command),(raw,error)=>{
     if(session==null||session.session_id!=identity||version!=epoch)return;
     if(error!=null){verificationFeedback="确认未保存，请重新打开确认窗口后重试。";ShowCheckFailure();return;}
     var result=JsonUtility.FromJson<BaselineCheck>(raw);ApplyBaseline(result.execution);verificationFeedback=AppTheme.Readable(result.execution.user_feedback);checkResult.text=verificationFeedback;
     if(result.execution.mode=="operate")baselineVerificationStage=true;
     if(result.execution.complete)ShowExecutionCompleted();
     else if(result.execution.baseline_mode=="ask_manual")ShowBaselineManual(result.execution);
     else if(result.execution.mode=="operate"&&result.execution.guidance_ready)StartCoroutine(EnterBaselineGuidance(result.execution.action_id));
    });
   }finally{checking=false;}
  }
  void RefreshBaselineControls(){
   if(!Baseline||locateButton==null||verify==null)return;
   bool manual=execution!=null&&execution.baseline_mode=="ask_manual",complete=execution!=null&&execution.complete;
   bool assess=!manual&&!complete&&!baselineVerificationStage&&(execution==null||execution.mode!="operate");
   locateButton.gameObject.SetActive(assess);verify.gameObject.SetActive(!assess);
   var button=assess?locateButton:verify;var rect=(RectTransform)button.transform;rect.anchorMin=new Vector2(.04f,.015f);rect.anchorMax=new Vector2(.96f,.078f);
   bool busy=checking||assessingScene||changing||locating||automaticBusy||authorStage>0;
   button.interactable=session!=null&&last!=null&&!busy;
   string label=assess?(execution==null||execution.needs_assessment?"评估现场":"重新评估现场"):manual?"查看结果与人工确认":complete?"查看完成结果":"拍照核验";
   if(checking)label=manual?"正在保存人工确认…":baselineVerificationStage?"正在拍照核验…":"正在评估现场…";
   button.GetComponentInChildren<Text>().text=AppTheme.Readable(label);
  }
 }
}
