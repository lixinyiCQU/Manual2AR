using System;
using System.Collections;
using UnityEngine;
using UnityEngine.UI;
namespace Manual2AR {
 public sealed partial class WikiToArView {
  [Serializable] class ExperimentOptions {
   public bool visual_observation_contract,stateful_planning,text_only,hierarchical_evidence,image_enrichment,visual_reranking,scene_alignment,staged_compilation,semantic_review,region_alignment,mask_refinement,temporal_verification,contextual_display;
  }
  [Serializable] class OptionDescriptor {public string id,label,description;}
  [Serializable] class OptionCatalog {public string contract;public OptionDescriptor[] features,controls;}
  ExperimentOptions options=new ExperimentOptions();Button experimentButton;string geometryReference="";
  int Enabled(ExperimentOptions value){int count=0;foreach(var f in typeof(ExperimentOptions).GetFields())if((bool)f.GetValue(value))count++;return count;}
  void RefreshExperimentLabel(){int count=Enabled(options);experimentButton.GetComponentInChildren<Text>().text=count==0?(string.IsNullOrEmpty(geometryReference)?"实验：基线":"实验：几何对照"):"实验："+count+" 项";}
  IEnumerator ShowExperiments(){
   if(busy)yield break;OptionCatalog catalog=null;string failure=null;
   yield return Request(Api+"/experiments","GET",null,(raw,error)=>{failure=error;if(error==null)catalog=JsonUtility.FromJson<OptionCatalog>(raw);});
   if(catalog==null||catalog.contract!="manual2ar-ablation-v1"){status.text=failure??"后端不支持实验开关，请更新后端。";yield break;}
   var dialog=AppDialog.Open(root,"Pipeline experiment options","基线与消融实验设置",AppDialogSize.Large,null);
   var draft=JsonUtility.FromJson<ExperimentOptions>(JsonUtility.ToJson(options));string geometryDraft=geometryReference;
   var content=AppContent.Scroll(dialog.Panel,"Optimization switches",new Vector2(.04f,.19f),new Vector2(.96f,.77f));
   Action render=null;render=()=>{
    Clear(content);AppContent.Paragraph(content,"全部关闭即本次测试基线。身份校验、现场证据隔离和空间配置确认始终启用。开关改变后需生成新任务，旧记录不会被改写。",23,AppTheme.Muted);
    if(job!=null)AppContent.Paragraph(content,"本轮ID："+job.id,21,AppTheme.Muted);
    AppContent.Paragraph(content,"可选几何对照：填写同图任务ID；确认复用人工配置，仅隔离几何误差，不计自动定位成功。保持打印机与定位板相对固定。留空则独立配置。",22,AppTheme.Muted);
    var geometry=Input(content,"几何对照任务ID（可选）",Vector2.zero,Vector2.one);geometry.gameObject.AddComponent<LayoutElement>().preferredHeight=80;geometry.characterLimit=32;geometry.text=geometryDraft;geometry.onValueChanged.AddListener(value=>geometryDraft=value.Trim());
    var oracle=AppTheme.Button(content,"打开人工 U7 对照（不计自动规划成功）",Vector2.zero,Vector2.one,()=>{dialog.Close();StartCoroutine(OpenOracle());},AppIcon.Inspect);oracle.gameObject.AddComponent<LayoutElement>().preferredHeight=66;
    var rows=new System.Collections.Generic.List<OptionDescriptor>();rows.AddRange(catalog.controls);rows.AddRange(catalog.features);
    foreach(var descriptor in rows){var row=descriptor;var field=typeof(ExperimentOptions).GetField(row.id);if(field==null)continue;bool enabled=(bool)field.GetValue(draft);
     var button=AppTheme.Button(content,(enabled?"✓ ":"○ ")+row.label,Vector2.zero,Vector2.one,()=>{
      bool next=!(bool)field.GetValue(draft);field.SetValue(draft,next);
      if(row.id=="text_only"&&next){draft.visual_reranking=false;draft.scene_alignment=false;draft.stateful_planning=false;}
      if((row.id=="visual_reranking"||row.id=="scene_alignment"||row.id=="stateful_planning")&&next)draft.text_only=false;
      render();},enabled?AppIcon.Check:AppIcon.Inspect,enabled);
     button.gameObject.AddComponent<LayoutElement>().preferredHeight=64;AppContent.Paragraph(content,row.description,21,AppTheme.Muted);
    }
   };
   Action<bool> preset=all=>{draft=new ExperimentOptions();geometryDraft="";if(all)foreach(var field in typeof(ExperimentOptions).GetFields())if(field.Name!="text_only")field.SetValue(draft,true);render();};
   AppTheme.Button(dialog.Panel,"基线：全部关闭",new Vector2(.04f,.79f),new Vector2(.33f,.88f),()=>preset(false),AppIcon.Clear);
   AppTheme.Button(dialog.Panel,"启用全部优化",new Vector2(.36f,.79f),new Vector2(.65f,.88f),()=>preset(true),AppIcon.Check);
   AppTheme.Button(dialog.Panel,"评价本轮结果",new Vector2(.68f,.79f),new Vector2(.96f,.88f),()=>{dialog.Close();ShowHumanReview();},AppIcon.Inspect);
   Action<bool> apply=rerun=>{options=draft;geometryReference=geometryDraft;RefreshExperimentLabel();job=null;preview.interactable=false;phaseText.text="实验配置已更改，请生成新任务";dialog.Close();if(rerun)StartCoroutine(Generate());};
   AppTheme.Button(dialog.Panel,"取消",new Vector2(.04f,.045f),new Vector2(.25f,.145f),dialog.Close,AppIcon.Back);
   AppTheme.Button(dialog.Panel,"应用开关",new Vector2(.29f,.045f),new Vector2(.58f,.145f),()=>apply(false),AppIcon.Check);
   AppTheme.Button(dialog.Panel,"应用并同图重跑",new Vector2(.62f,.045f),new Vector2(.96f,.145f),()=>apply(true),AppIcon.Camera,true);render();
  }
  IEnumerator OpenOracle(){
   if(captured==null||string.IsNullOrWhiteSpace(intent.text)){status.text="请先输入目标并拍摄现场，用于配对人工 U7 对照。";yield break;}
   string failure=null;var command=new Question{intent=intent.text.Trim(),image_base64=Convert.ToBase64String(captured),source_sha256=Hash(captured),capture_id=captureId,client_frame_id=frame,camera_signature=cameraSignature,experiment=new ExperimentOptions()};
   yield return Request(Api+"/experiments/oracle","POST",JsonUtility.ToJson(command),(raw,error)=>failure=error);
   if(failure!=null){status.text=failure;yield break;}
   job=null;preview.interactable=false;status.text="正在查看人工 U7 对照；不计自动规划成绩。返回后请重新生成或恢复自动任务，再评价。";
   cameraOwner.Close();root.gameObject.SetActive(false);Spatial.SpatialGuidanceController.Open(origin,"U7",()=>{root.gameObject.SetActive(true);BindBack();});
  }
  [Serializable] class HumanRating {public string task_planning="unrated",component_binding="unrated",guidance="unrated",verification="unrated",notes="";public float review_seconds;}
  void ShowHumanReview(){
   if(job==null){status.text="请先生成一个任务再评价。";return;}string identity=job.id;
   var dialog=AppDialog.Open(root,"Human experiment review","人工评价 · "+identity.Substring(0,8),AppDialogSize.Standard,null);
   var form=new HumanRating();float opened=Time.realtimeSinceStartup;var content=AppContent.Scroll(dialog.Panel,"Review dimensions",new Vector2(.05f,.26f),new Vector2(.95f,.86f));
   var fields=new[]{"task_planning","component_binding","guidance","verification"};var labels=new[]{"任务规划","部件与资产绑定","现场指导","完成核验"};
   for(int i=0;i<fields.Length;i++){var field=typeof(HumanRating).GetField(fields[i]);string label=labels[i];Button button=null;
    button=AppTheme.Button(content,label+"：未评价",Vector2.zero,Vector2.one,()=>{string current=(string)field.GetValue(form);string next=current=="unrated"?"pass":current=="pass"?"fail":"unrated";field.SetValue(form,next);button.GetComponentInChildren<Text>().text=label+"："+(next=="pass"?"通过":next=="fail"?"失败":"未评价");},AppIcon.Inspect);button.gameObject.AddComponent<LayoutElement>().preferredHeight=66;
   }
   AppContent.Paragraph(content,"点击每项切换 未评价／通过／失败。未评价不计入成功率；此记录不会改变安装进度。",22,AppTheme.Muted);
   AppTheme.Button(dialog.Panel,"取消",new Vector2(.05f,.07f),new Vector2(.43f,.18f),dialog.Close,AppIcon.Back);
   AppTheme.Button(dialog.Panel,"保存人工评价",new Vector2(.49f,.07f),new Vector2(.95f,.18f),()=>{form.review_seconds=Time.realtimeSinceStartup-opened;dialog.Close();StartCoroutine(Request(Api+"/jobs/"+identity+"/review","POST",JsonUtility.ToJson(form),(raw,error)=>status.text=error??"人工评价已保存，可导出实验结果。"));},AppIcon.Save,true);
  }
 }
}
