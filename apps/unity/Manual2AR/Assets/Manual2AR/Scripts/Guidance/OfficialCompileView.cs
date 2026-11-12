using System;
using System.Collections;
using System.Collections.Generic;
using System.Text;
using UnityEngine;
using UnityEngine.Networking;
using UnityEngine.UI;
namespace Manual2AR {
 public sealed class OfficialCompileView:MonoBehaviour {
  [Serializable] class Question {public string intent;}
  [Serializable] class Job {public string id,status,message,preview,manifest_sha256;}
  [Serializable] class PreviewUse {public string manifest_sha256;public bool acknowledge_experimental=true;}
  [Serializable] class Failure {public string detail;}
  const string Api="/api/guidance/compiled/jobs";
  string origin;Action done;RectTransform root,content;InputField intent;Text status;Button compile,use;
  Job job;bool busy,closed;readonly HashSet<UnityWebRequest> requests=new HashSet<UnityWebRequest>();
  public static OfficialCompileView Open(string backend,Action onClose){
   var view=new GameObject("Official Source Compilation").AddComponent<OfficialCompileView>();view.origin=backend.TrimEnd('/');view.done=onClose;view.Build();return view;
  }
  void Build(){
   root=AppWorkspace.Canvas(transform,"Official compilation workspace",30);
   var workspace=new AppWorkspace(root,"官方资料 → 安装任务",AppWorkspaceKind.Reading);workspace.SetToolsVisible(false);
   AppTheme.Button(root,"返回任务列表",AppWorkspace.BackMin,AppWorkspace.BackMax,Close,AppIcon.Back);
   AppTheme.Label(workspace.Main,"你希望完成什么操作？",new Vector2(.05f,.86f),new Vector2(.95f,.96f),28,AppTheme.TargetCyan);
   var area=AppTheme.Panel(workspace.Main,"Task intent",new Vector2(.05f,.53f),new Vector2(.95f,.84f));
   intent=area.gameObject.AddComponent<InputField>();intent.targetGraphic=area.GetComponent<Image>();intent.lineType=InputField.LineType.MultiLineNewline;intent.characterLimit=1000;
   intent.textComponent=AppTheme.Label(area,"",new Vector2(.04f,.06f),new Vector2(.96f,.94f),27);intent.textComponent.supportRichText=false;
   intent.placeholder=AppTheme.Label(area,"例如：安装料盘支架／安装支架底座／将支架滑入底座",new Vector2(.04f,.06f),new Vector2(.96f,.94f),25,AppTheme.Muted);
   AppTheme.Label(workspace.Main,"先从官方离线资料生成完整任务，再进入相机核验和 AR 指导。\n\n请阅读右侧的操作、确认条件和出处。当前生成结果属于实验候选，需要核对后试用。",new Vector2(.05f,.13f),new Vector2(.95f,.48f),25);
   content=AppContent.Scroll(workspace.Aside,"Compiled task review",new Vector2(.02f,.02f),new Vector2(.98f,.98f));
   AppContent.Paragraph(content,"生成后将在这里显示任务、核验条件和官方出处。",26);
   compile=AppTheme.Button(workspace.FooterLeft,"从官方资料编译",Vector2.zero,Vector2.one,()=>StartCoroutine(Generate()),AppIcon.Inspect,true);AppActionBar.Add(workspace.FooterLeft,compile);
   use=AppTheme.Button(workspace.FooterRight,"已阅读候选，进入 AR 试用",Vector2.zero,Vector2.one,()=>StartCoroutine(Enter()),AppIcon.Check,true);AppActionBar.Add(workspace.FooterRight,use);use.interactable=false;
   status=AppTheme.Label(root,"请输入安装或其他明确操作目标",new Vector2(.03f,.105f),new Vector2(.97f,.13f),19,AppTheme.Muted);
   intent.onValueChanged.AddListener(_=>{if(!busy){job=null;use.interactable=false;}});BindBack();
  }
  void BindBack(){AppShell.BindBack("返回任务列表",Close);AppShell.PlaceBack(AppWorkspace.BackMin,AppWorkspace.BackMax);}
  void Busy(bool value){busy=value;compile.interactable=!value;intent.interactable=!value;use.interactable=!value&&job!=null&&(job.status=="ready"||job.status=="active");}
  void Show(Job value){
   job=value;status.text=AppTheme.Readable(value.message);
   if(!string.IsNullOrEmpty(value.preview)){
    foreach(Transform child in content){child.gameObject.SetActive(false);Destroy(child.gameObject);}
    var text=AppContent.Paragraph(content,value.preview,24);text.supportRichText=false;
   }
  }
  IEnumerator Generate(){
   if(busy||string.IsNullOrWhiteSpace(intent.text))yield break;Busy(true);job=null;
   try{
    string failure=null,raw=null;yield return Request(Api,"POST",JsonUtility.ToJson(new Question{intent=intent.text.Trim()}),(s,e)=>{raw=s;failure=e;});
    if(failure!=null){status.text=failure;yield break;}Show(JsonUtility.FromJson<Job>(raw));
    while(!closed&&(job.status=="queued"||job.status=="compiling")){
     yield return new WaitForSecondsRealtime(.5f);yield return Request(Api+"/"+job.id,"GET",null,(s,e)=>{raw=s;failure=e;});
     if(failure!=null){status.text=failure;yield break;}Show(JsonUtility.FromJson<Job>(raw));
    }
   }finally{Busy(false);}
  }
  IEnumerator Enter(){
   if(busy||job==null||(job.status!="ready"&&job.status!="active"))yield break;Busy(true);
   try{
    string failure=null,raw=null;yield return Request(Api+"/"+job.id+"/use","POST",JsonUtility.ToJson(new PreviewUse{manifest_sha256=job.manifest_sha256}),(s,e)=>{raw=s;failure=e;});
    if(failure!=null){status.text=failure;yield break;}Show(JsonUtility.FromJson<Job>(raw));root.gameObject.SetActive(false);
    Spatial.SpatialGuidanceController.OpenCompiledBaseline(origin,job.id,()=>{if(!closed){root.gameObject.SetActive(true);BindBack();}},intent.text.Trim());
   }finally{Busy(false);}
  }
  IEnumerator Request(string path,string method,string body,Action<string,string> result){
   using(var request=new UnityWebRequest(origin+path,method)){
    request.downloadHandler=new DownloadHandlerBuffer();request.timeout=30;
    if(body!=null){request.uploadHandler=new UploadHandlerRaw(Encoding.UTF8.GetBytes(body));request.SetRequestHeader("Content-Type","application/json");}
    requests.Add(request);yield return request.SendWebRequest();requests.Remove(request);
    string raw=request.downloadHandler.text,error=null;
    if(request.result!=UnityWebRequest.Result.Success){error="任务编译服务暂不可用。";try{var value=JsonUtility.FromJson<Failure>(raw);if(!string.IsNullOrEmpty(value.detail))error=value.detail;}catch(Exception){}}
    if(!closed)result(raw,error);
   }
  }
  void Close(){closed=true;foreach(var request in requests)try{request.Abort();}catch(ObjectDisposedException){}requests.Clear();done?.Invoke();Destroy(gameObject);}
  void OnDestroy(){closed=true;foreach(var request in requests)try{request.Abort();}catch(ObjectDisposedException){}requests.Clear();}
 }
}
