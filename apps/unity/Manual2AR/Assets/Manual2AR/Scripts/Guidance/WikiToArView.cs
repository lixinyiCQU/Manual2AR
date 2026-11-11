using System;
using System.Collections;
using System.Collections.Generic;
using System.Security.Cryptography;
using System.Text;
using UnityEngine;
using UnityEngine.Networking;
using UnityEngine.UI;

namespace Manual2AR {
 /// <summary>A fresh question and upright photo generate an evidence-bound, isolated AR task.</summary>
 public sealed partial class WikiToArView:MonoBehaviour {
  [Serializable] class Question {public string intent,image_base64,source_sha256,capture_id,camera_signature,geometry_reference;public int client_frame_id;public ExperimentOptions experiment;}
  [Serializable] class Job {public string id,status,message,source_sha256,capture_id,created_at,intent,camera_signature;public int client_frame_id;public float elapsed_seconds;public Scene scene;public Candidate candidate;public ExperimentOptions experiment;public string method,geometry_reference;public Alignment alignment;}
  [Serializable] class Alignment {public string state,current_capability;public AlignedPart[] parts;}
  [Serializable] class AlignedPart {public string component_id,status,evidence;}
  [Serializable] class Scene {public string summary;public string[] visible_parts,uncertainties;}
  [Serializable] class ExecutionStep {public string state_id,action_id,mode,reason,instruction;public bool claim_conflict;}
  [Serializable] class ExecutionPlan {public ExecutionStep[] steps;}
  [Serializable] class Candidate {public ExecutionPlan execution_plan;public string id,procedure_sha256;public bool spatial_ready;public VisualContract observation_contract;public Step[] states;}
  [Serializable] class VisualContract {public ContractFeature[] features;public ContractSpec[] specs;public ContractRule[] rules;}
  [Serializable] class ContractFeature {public string id,component_id,description;}
  [Serializable] class ContractSpec {public string id,inspection_id,predicate,region_definition,limitation;public string[] feature_ids;}
  [Serializable] class ContractRule {public string spec_id,expected,origin,rationale;}
  [Serializable] class Step {public string state_id,instruction;public string[] preconditions,postconditions,warnings;public Source[] sources;public Observation[] observations;public Photo[] images;}
  [Serializable] class Source {public string text,url;}
  [Serializable] class Observation {public string condition,verification_channel;}
  [Serializable] class Photo {public string url,sha256;}
  [Serializable] class Approval {public string procedure_sha256;public bool confirmed=true;}
  [Serializable] class Failure {public string detail;}
  const string Api="/api/guidance/pipeline";
  string origin,captureId="",cameraSignature="";Action done;RectTransform root,feedback;
  InputField intent;Dropdown lenses;Button submit,preview,shoot,start,resume;Text status,phaseText,waitHint;RawImage image;RectTransform progressFill;
  Spatial.SpatialCamera cameraOwner;Texture2D texture,reference;byte[] captured;int frame,generation;bool busy,closed,frozen;float nextPreview;Job job;string renderedStatus="";
  readonly HashSet<UnityWebRequest> requests=new HashSet<UnityWebRequest>();
  public static void Open(string backend,Action onClose){var view=new GameObject("Wiki to AR").AddComponent<WikiToArView>();view.origin=backend.TrimEnd('/');view.done=onClose;view.Build();}
  void Build(){
   root=AppWorkspace.Canvas(transform,"Wiki to AR workspace",30);var w=new AppWorkspace(root,"资料 → AR 指导 · A1 mini");
   AppWorkspace.Place(w.HeaderActions,.44f,.925f,.795f,.985f);
   experimentButton=AppTheme.Button(w.HeaderActions,"实验：基线",Vector2.zero,Vector2.one,()=>StartCoroutine(ShowExperiments()),AppIcon.Inspect);AppActionBar.Add(w.HeaderActions,experimentButton);
   resume=AppTheme.Button(w.HeaderActions,"继续上次任务",Vector2.zero,Vector2.one,()=>StartCoroutine(Resume()),AppIcon.Back);AppActionBar.Add(w.HeaderActions,resume);
   AppTheme.Button(root,"返回任务列表",AppWorkspace.BackMin,AppWorkspace.BackMax,Close,AppIcon.Back);
   start=AppTheme.Button(w.Tools,"启动摄像头",new Vector2(0,0),new Vector2(.25f,1),()=>StartCoroutine(StartCamera()),AppIcon.Camera);
   lenses=AppDropdown.Create(w.Tools,"摄像头",new Vector2(.27f,0),new Vector2(.66f,1),i=>{cameraOwner.Close();ClearCapture();});
   var names=new List<string>();foreach(var device in WebCamTexture.devices)names.Add(device.name);if(names.Count==0)names.Add("未发现摄像头");lenses.AddOptions(names);
   shoot=AppTheme.Button(w.Tools,"拍摄现场",new Vector2(.69f,0),Vector2.one,Capture,AppIcon.Camera,true);
   var media=AppTheme.Rect(w.Main,"Upright scene",Vector2.zero,Vector2.one);media.gameObject.AddComponent<RectMask2D>();
   image=AppTheme.Rect(media,"Scene photo",Vector2.zero,Vector2.one).gameObject.AddComponent<RawImage>();image.color=Color.clear;
   image.gameObject.AddComponent<AspectRatioFitter>().aspectMode=AspectRatioFitter.AspectMode.FitInParent;AppMediaEmptyState.Attach(w.Main,image,"启动摄像头，拍摄打印机及待安装部件");
   AppTheme.Label(w.Aside,"你希望完成什么？",new Vector2(.05f,.89f),new Vector2(.95f,.97f),26,AppTheme.TargetCyan);
   intent=Input(w.Aside,"描述设备操作目标，例如你要安装的部件",new Vector2(.05f,.67f),new Vector2(.95f,.88f));intent.characterLimit=1200;
   phaseText=AppTheme.Label(w.Aside,"拍照后生成任务",new Vector2(.05f,.57f),new Vector2(.95f,.66f),25,AppTheme.TargetCyan);
   var track=AppTheme.Rect(w.Aside,"Generation progress",new Vector2(.05f,.545f),new Vector2(.95f,.555f));track.gameObject.AddComponent<Image>().color=AppTheme.ButtonBackground;
   progressFill=AppTheme.Rect(track,"Completed stages",Vector2.zero,Vector2.zero);progressFill.gameObject.AddComponent<Image>().color=AppTheme.TargetCyan;
   waitHint=AppTheme.Label(w.Aside,"已生成的任务可直接继续，无需重新调用模型。",new Vector2(.05f,.465f),new Vector2(.95f,.535f),19,AppTheme.Muted);
   feedback=AppContent.Scroll(w.Aside,"Generation feedback",new Vector2(.04f,.04f),new Vector2(.96f,.455f));
   AppContent.Paragraph(feedback,"系统将从离线设备资料查找依据并生成任务。本阶段仅支持现有U7的底座固定与支架滑入能力。",25);
   submit=AppTheme.Button(w.FooterLeft,"根据问题与照片生成",Vector2.zero,Vector2.one,()=>StartCoroutine(Generate()),AppIcon.Inspect,true);AppActionBar.Add(w.FooterLeft,submit);
   preview=AppTheme.Button(w.FooterRight,"预览并进入 AR",Vector2.zero,Vector2.one,Preview,AppIcon.Check,true);AppActionBar.Add(w.FooterRight,preview);preview.interactable=false;
   status=AppTheme.Label(root,"尚未拍摄现场照片",new Vector2(.03f,.105f),new Vector2(.97f,.13f),19,AppTheme.Muted);
   cameraOwner=gameObject.AddComponent<Spatial.SpatialCamera>();
   intent.onValueChanged.AddListener(_=>{if(busy||job==null)return;job=null;preview.interactable=false;phaseText.text="目标已更改，请重新生成任务";});BindBack();
  }
  void BindBack(){AppShell.BindBack("返回任务列表",Close);AppShell.PlaceBack(AppWorkspace.BackMin,AppWorkspace.BackMax);}
  InputField Input(Transform parent,string hint,Vector2 min,Vector2 max){
   var area=AppTheme.Panel(parent,"Installation intent",min,max);var input=area.gameObject.AddComponent<InputField>();input.targetGraphic=area.GetComponent<Image>();input.lineType=InputField.LineType.MultiLineNewline;
   input.textComponent=AppTheme.Label(area,"",new Vector2(.03f,.06f),new Vector2(.97f,.94f),26);input.textComponent.supportRichText=false;
   input.placeholder=AppTheme.Label(area,hint,new Vector2(.03f,.06f),new Vector2(.97f,.94f),24,AppTheme.Muted);return input;
  }
  IEnumerator StartCamera(){if(busy)yield break;ClearCapture();string error=null;yield return cameraOwner.Open(lenses.value,e=>error=e);status.text=error??"让打印机与待安装部件入镜，然后拍摄现场。";}
  void ClearCapture(){captured=null;captureId="";job=null;frozen=false;generation++;preview.interactable=false;image.texture=null;image.color=Color.clear;renderedStatus="";phaseText.text="拍照后生成任务";progressFill.anchorMax=Vector2.zero;}
  void Update(){UpdateProgress();if(busy||frozen||cameraOwner==null||!cameraOwner.Ready||Time.unscaledTime<nextPreview)return;nextPreview=Time.unscaledTime+.15f;var raw=cameraOwner.Capture();if(raw!=null)ShowImage(raw);}
  void ShowImage(byte[] raw){if(texture==null)texture=new Texture2D(2,2,TextureFormat.RGB24,false);if(!ImageConversion.LoadImage(texture,raw))return;image.texture=texture;image.color=Color.white;image.GetComponent<AspectRatioFitter>().aspectRatio=texture.width/(float)texture.height;}
  void Capture(){if(busy||!cameraOwner.Ready)return;var raw=cameraOwner.Capture();if(raw==null){status.text="画面尚未就绪，请稍后再拍。";return;}captured=raw;cameraSignature=cameraOwner.Signature;captureId=Guid.NewGuid().ToString("N");frame++;frozen=true;job=null;preview.interactable=false;ShowImage(raw);status.text="现场照片已保留；填写目标后点击生成。";}
  static string Hash(byte[] raw){using(var sha=SHA256.Create())return BitConverter.ToString(sha.ComputeHash(raw)).Replace("-","").ToLowerInvariant();}
  void Busy(bool value){busy=value;if(submit==null)return;experimentButton.interactable=resume.interactable=submit.interactable=shoot.interactable=start.interactable=lenses.interactable=intent.interactable=!value;}
  static Job Decode(string raw,out string error){error=null;try{var value=JsonUtility.FromJson<Job>(raw);if(value==null)throw new Exception();return value;}catch(Exception){error="任务状态读取失败，可点击继续上次任务重试。";return null;}}
  IEnumerator Generate(){
   if(busy)yield break;if(captured==null||string.IsNullOrWhiteSpace(intent.text)){status.text="请填写安装目标并拍摄现场。";yield break;}
   Busy(true);preview.interactable=false;job=null;int version=++generation;var command=new Question{intent=intent.text.Trim(),image_base64=Convert.ToBase64String(captured),source_sha256=Hash(captured),capture_id=captureId,client_frame_id=frame,camera_signature=cameraSignature,experiment=options,geometry_reference=geometryReference};
   try{
    string error=null;yield return Request(Api+"/jobs","POST",JsonUtility.ToJson(command),(raw,e)=>{error=e;if(e==null)job=Decode(raw,out error);});
    if(error!=null){status.text=error;yield break;}
    renderedStatus="";yield return Follow(version,command.capture_id,command.source_sha256,command.client_frame_id);
   }finally{Busy(false);}
   if(!closed&&preview.interactable)Preview();
  }
  IEnumerator Resume(){
   if(busy)yield break;Busy(true);preview.interactable=false;int version=++generation;
   try{
    string error=null;Job latest=null;yield return Request(Api+"/jobs/latest","GET",null,(raw,e)=>{error=e;if(e==null)latest=Decode(raw,out error);});
    if(error!=null){status.text=error;yield break;}if(string.IsNullOrEmpty(latest.id)){status.text=latest.message;yield break;}
    byte[] photo=null;using(var r=UnityWebRequest.Get(origin+Api+"/jobs/"+latest.id+"/scene")){requests.Add(r);r.timeout=20;yield return r.SendWebRequest();requests.Remove(r);if(r.result==UnityWebRequest.Result.Success)photo=r.downloadHandler.data;}
    if(photo==null||Hash(photo)!=latest.source_sha256){status.text="上次照片不可用或已改变，请重新拍摄。";yield break;}
    cameraOwner.Close();captured=photo;captureId=latest.capture_id;frame=latest.client_frame_id;cameraSignature=latest.camera_signature;intent.text=latest.intent;frozen=true;job=latest;options=latest.experiment??new ExperimentOptions();geometryReference=latest.geometry_reference??"";RefreshExperimentLabel();ShowImage(photo);renderedStatus="";
    yield return Follow(version,captureId,latest.source_sha256,frame);
   }finally{Busy(false);}
   if(!closed&&preview.interactable)Preview();
  }
  IEnumerator Follow(int version,string expectedCapture,string expectedSha,int expectedFrame){
   string identity=job.id;int failures=0;
   while(!closed&&version==generation){
    if(job.id!=identity||job.capture_id!=expectedCapture||job.source_sha256!=expectedSha||job.client_frame_id!=expectedFrame){status.text="生成结果与当前照片不匹配，请重拍。";job=null;yield break;}
    if(renderedStatus!=job.status){Debug.Log("WikiToAR job="+identity+" stage="+job.status);Render();renderedStatus=job.status;}
    if(job.status=="ready"||job.status=="approved"||job.status=="unsupported"||job.status=="failed")yield break;
    yield return new WaitForSecondsRealtime(failures>0?3:1);string error=null;Job incoming=null;
    yield return Request(Api+"/jobs/"+identity,"GET",null,(raw,e)=>{error=e;if(e==null)incoming=Decode(raw,out error);});
    if(error!=null){status.text="连接暂时中断，正在重试；无需重新生成。";if(++failures>=3){status.text="连接中断，可点击继续上次任务；后台生成结果会保留。";yield break;}continue;}
    failures=0;job=incoming;
   }
  }
  void UpdateProgress(){
   if(job==null||phaseText==null)return;int step=job.status=="observing"?1:job.status=="retrieving"?2:(job.status=="compiling"||job.status=="reviewing")?3:(job.status=="binding"||job.status=="aligning")?4:0;
   bool ready=job.status=="ready"||job.status=="approved";double seconds=job.elapsed_seconds;
   if(!ready&&DateTimeOffset.TryParse(job.created_at,out var at))seconds=Math.Max(0,(DateTimeOffset.UtcNow-at).TotalSeconds);
   string elapsed=((int)seconds/60)+"分"+((int)seconds%60).ToString("00")+"秒";
   string name=step==1?"分析现场":step==2?"检索官方资料":step==3?"编译步骤与核验条件":step==4?(job.status=="aligning"?"对齐现场并选择执行计划":"绑定 AR 能力"):"准备生成";
   phaseText.text=ready?"生成完成 · "+elapsed:job.status=="failed"?"生成未完成":job.status=="unsupported"?"当前任务暂不支持 AR":step+"/4 · "+name+"\n已等待 "+elapsed;
   progressFill.anchorMax=new Vector2(ready?1:Mathf.Max(0,step-1)/4f,1);
   waitHint.text=ready?"请确认弹窗中的任务与依据，再进入 AR。":job.status=="failed"||job.status=="unsupported"?"可修改目标后重试；当前任务未被放行。":(Enabled(options)>0?"已启用优化，会增加模型调用；可能等待数分钟，离开后可继续。":"生成可能需要1–2分钟；离开后可继续上次任务。");
  }
  void Clear(RectTransform target){foreach(Transform child in target){child.gameObject.SetActive(false);Destroy(child.gameObject);}}
  void Render(){
   Clear(feedback);status.text=AppTheme.Readable(job.message);
   AppContent.Paragraph(feedback,"本轮配置："+(Enabled(job.experiment??new ExperimentOptions())==0?"基线":"已选 "+Enabled(job.experiment)+" 项实验开关")+(string.IsNullOrEmpty(job.geometry_reference)?"":" · 人工几何对照"),21,AppTheme.Muted);
   if(job.candidate!=null&&job.candidate.states!=null){foreach(var s in job.candidate.states)AppContent.Paragraph(feedback,s.instruction,26);AppContent.Paragraph(feedback,"生成内容需预览确认；照片不能确认真正紧固。",23,AppTheme.WarningAmber);}
   if(job.alignment!=null){AppContent.Paragraph(feedback,"现场部件对应（待核验）",23,AppTheme.TargetCyan);foreach(var part in job.alignment.parts??new AlignedPart[0])AppContent.Paragraph(feedback,(part.component_id=="spool_holder_base"?"料盘支架底座":part.component_id=="external_spool_holder"?"料盘支架":part.component_id)+" · "+part.status+"："+part.evidence,22,AppTheme.Muted);}
   if(!(job.experiment?.stateful_planning??false)&&job.scene!=null&&!string.IsNullOrEmpty(job.scene.summary)){string brief=job.scene.summary;AppContent.Paragraph(feedback,"现场观察："+(brief.Length>80?brief.Substring(0,80)+"…":brief),23,AppTheme.Muted);}
   preview.interactable=job.candidate!=null&&(job.status=="ready"||job.status=="approved"||job.status=="unsupported");
  }
  void Preview(){
   if(busy||job==null||job.candidate==null)return;var candidate=job.candidate;var dialog=AppDialog.Open(root,"Generated task preview","生成任务与官方依据",AppDialogSize.Large,null);
   Debug.Log("WikiToAR preview job="+job.id);
   var content=AppContent.Scroll(dialog.Panel,"Generated task",new Vector2(.03f,.17f),new Vector2(.60f,.85f));
   AppContent.Paragraph(content,"以下为自动生成的任务；空间示意复用 U7 资产，首次进入需配置当前位置。核验只依据现场照。",23,AppTheme.Muted);
   if(candidate.execution_plan?.steps!=null)foreach(var step in candidate.execution_plan.steps)AppContent.Paragraph(content,step.instruction+"\n本次建议："+(step.mode=="check"?"先核验现状":step.mode=="observe"?"补充取景":"指导操作")+" · "+step.reason,24,step.claim_conflict?AppTheme.WarningAmber:AppTheme.TargetCyan);
   foreach(var s in candidate.states){AppContent.Paragraph(content,s.instruction,29,AppTheme.TargetCyan);foreach(var warning in s.warnings??new string[0])AppContent.Paragraph(content,warning,25,AppTheme.WarningAmber);
    foreach(var o in s.observations??new Observation[0])AppContent.Paragraph(content,(o.verification_channel=="manual"?"人工确认：":"核验：")+o.condition,25);
    foreach(var source in s.sources??new Source[0])AppContent.Paragraph(content,"原文："+source.text,23,AppTheme.Muted);
   }
   if(candidate.observation_contract!=null){
    AppContent.Paragraph(content,"严格观察规范（请审核特征及验收期望）",25,AppTheme.TargetCyan);
    foreach(var f in candidate.observation_contract.features??new ContractFeature[0])AppContent.Paragraph(content,f.id+" · "+f.component_id+"："+f.description,23);
    foreach(var q in candidate.observation_contract.specs??new ContractSpec[0])AppContent.Paragraph(content,q.inspection_id+" / "+q.predicate+"："+q.region_definition+(string.IsNullOrEmpty(q.limitation)?"":"；"+q.limitation),23);
    foreach(var r in candidate.observation_contract.rules??new ContractRule[0])AppContent.Paragraph(content,r.spec_id+" → "+r.expected+" ["+r.origin+"]："+r.rationale,23,AppTheme.Muted);
   }
   var media=AppTheme.Rect(dialog.Panel,"Retrieved official image",new Vector2(.63f,.22f),new Vector2(.97f,.82f));media.gameObject.AddComponent<RectMask2D>();
   var picture=AppTheme.Rect(media,"Official image",Vector2.zero,Vector2.one).gameObject.AddComponent<RawImage>();picture.color=Color.clear;picture.gameObject.AddComponent<AspectRatioFitter>().aspectMode=AspectRatioFitter.AspectMode.FitInParent;
   var photos=new List<Photo>();foreach(var s in candidate.states)if(s.images!=null)photos.AddRange(s.images);int index=0;
   Action show=()=>{if(photos.Count>0)StartCoroutine(LoadPhoto(photos[index],picture));};show();
   AppTheme.Button(dialog.Panel,"上一图",new Vector2(.63f,.13f),new Vector2(.79f,.21f),()=>{if(photos.Count==0)return;index=(index+photos.Count-1)%photos.Count;show();},AppIcon.Back);
   AppTheme.Button(dialog.Panel,"下一图",new Vector2(.81f,.13f),new Vector2(.97f,.21f),()=>{if(photos.Count==0)return;index=(index+1)%photos.Count;show();},AppIcon.SwitchCamera);
   AppTheme.Button(dialog.Panel,"返回修改",new Vector2(.03f,.025f),new Vector2(.28f,.115f),dialog.Close,AppIcon.Back);
   AppTheme.Button(dialog.Panel,"确认任务，进入 AR",new Vector2(.55f,.025f),new Vector2(.97f,.115f),()=>{dialog.Close();StartCoroutine(Approve(candidate));},AppIcon.Check,true).interactable=candidate.spatial_ready;
  }
  IEnumerator LoadPhoto(Photo item,RawImage target){
   using(var r=UnityWebRequest.Get(origin+item.url)){requests.Add(r);r.timeout=20;yield return r.SendWebRequest();requests.Remove(r);if(target==null||r.result!=UnityWebRequest.Result.Success||Hash(r.downloadHandler.data)!=item.sha256)yield break;
    var next=new Texture2D(2,2);if(!ImageConversion.LoadImage(next,r.downloadHandler.data)){Destroy(next);yield break;}if(reference!=null)Destroy(reference);reference=next;target.texture=reference;target.color=Color.white;target.GetComponent<AspectRatioFitter>().aspectRatio=reference.width/(float)reference.height;}
  }
  IEnumerator Approve(Candidate candidate){
   if(busy)yield break;Busy(true);string error=null;yield return Request(Api+"/jobs/"+candidate.id+"/approve","POST",JsonUtility.ToJson(new Approval{procedure_sha256=candidate.procedure_sha256}),(raw,e)=>error=e);Busy(false);
   if(error!=null){status.text=error;yield break;}cameraOwner.Close();root.gameObject.SetActive(false);
   Spatial.SpatialGuidanceController.OpenCompiled(origin,candidate.id,()=>{root.gameObject.SetActive(true);BindBack();});
  }
  IEnumerator Request(string path,string method,string body,Action<string,string> callback){
   using(var r=new UnityWebRequest(origin+path,method)){r.downloadHandler=new DownloadHandlerBuffer();r.timeout=30;if(body!=null){r.uploadHandler=new UploadHandlerRaw(Encoding.UTF8.GetBytes(body));r.SetRequestHeader("Content-Type","application/json");}requests.Add(r);yield return r.SendWebRequest();requests.Remove(r);if(closed)yield break;
    string error=null;if(r.result!=UnityWebRequest.Result.Success){try{error=JsonUtility.FromJson<Failure>(r.downloadHandler.text).detail;}catch(Exception){}if(string.IsNullOrEmpty(error))error="生成服务连接失败，请启动本工作树的后端后重试。";}callback(r.downloadHandler.text,error);}
  }
  void Close(){closed=true;done?.Invoke();Destroy(gameObject);}
  void OnDestroy(){closed=true;foreach(var r in requests)r.Abort();if(cameraOwner!=null)cameraOwner.Close();if(texture!=null)Destroy(texture);if(reference!=null)Destroy(reference);}
 }
}
