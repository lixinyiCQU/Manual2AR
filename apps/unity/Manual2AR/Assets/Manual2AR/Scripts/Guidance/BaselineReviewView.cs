using System;
using System.Collections;
using System.Collections.Generic;
using System.Text;
using UnityEngine;
using UnityEngine.Networking;
using UnityEngine.UI;

namespace Manual2AR {
 public sealed class BaselineReviewView:MonoBehaviour {
  [Serializable] class PlanInfo {public string id,title,human_rate;public bool available;public int revision,scheduled,contract_pass,reviewed,approved;}
  [Serializable] class Catalog {public string contract;public PlanInfo[] plans;}
  [Serializable] class Trial {public string trial_id,intent,device,status,decision;public int repeat;public bool contract_pass,can_experiment;}
  [Serializable] class Trials {public string id,title,human_rate;public int revision,scheduled,contract_pass,reviewed,approved;public Trial[] trials;}
  [Serializable] class Label {public string trial_id,compilation_manifest_sha256,task_sha256,decision="pending",reviewer="",note="",task_scope="pending",requirements="pending",dependencies="pending",verification="pending";}
  [Serializable] class Photo {public string url,sha256;}
  [Serializable] class Candidate {public string plan_sha256,trial_id,intent,scope,status,text,official_text,task_sha256,compilation_manifest_sha256;public bool contract_pass,can_experiment;public int revision;public Label label;public Photo[] images;}
  [Serializable] class SaveReview {public string plan_sha256;public int revision;public Label label;}
  [Serializable] class Use {public string plan_sha256,manifest_sha256;public bool acknowledge_experimental=true;}
  [Serializable] class Job {public string id;}
  [Serializable] class Export {public string path,message;}
  [Serializable] class Failure {public string detail;}
  const string Api="/api/guidance/reviews";
  readonly string[] fields={"task_scope","requirements","dependencies","verification"};
  readonly string[] captions={"任务范围","要求完整与忠实","操作顺序与依赖","核验方法与边界"};
  string origin,planId;Action done;RectTransform root,official,generated;Dropdown plans,attempts,filter;
  InputField reviewer,note;Text status,statistics,photoCaption;Button save,use,next,export,discard,back,previousPhoto,nextPhoto;
  RawImage image;Texture2D texture;PlanInfo[] available;Trials listing;Candidate candidate;readonly List<Trial> visible=new List<Trial>();
  Spatial.SpatialReferenceViewer referenceViewer;
  readonly List<Button> ratings=new List<Button>();readonly HashSet<UnityWebRequest> requests=new HashSet<UnityWebRequest>();
  bool busy,closed,dirty,rendering;int generation,photoIndex;
  public static BaselineReviewView Open(string backend,Action onClose){
   var view=new GameObject("Baseline Human Review").AddComponent<BaselineReviewView>();view.origin=backend.TrimEnd('/');view.done=onClose;view.Build();view.StartCoroutine(view.Initialize());return view;
  }
  void Build(){
   root=AppWorkspace.Canvas(transform,"Baseline review workspace",30);var w=new AppWorkspace(root,"候选人工审核与 U7 实测",AppWorkspaceKind.Reading);
   back=AppTheme.Button(root,"返回任务列表",AppWorkspace.BackMin,AppWorkspace.BackMax,Close,AppIcon.Back);
   plans=AppDropdown.Create(w.Tools,"评价集",Vector2.zero,new Vector2(.25f,1),i=>{if(!rendering)StartCoroutine(LoadPlan(available[i].id));});
   attempts=AppDropdown.Create(w.Tools,"生成尝试",new Vector2(.27f,0),new Vector2(.77f,1),i=>{if(!rendering&&i<visible.Count)StartCoroutine(LoadCandidate(visible[i].trial_id));});
   filter=AppDropdown.Create(w.Tools,"筛选",new Vector2(.79f,0),Vector2.one,i=>{if(!rendering)RenderTrials(null);});
   filter.AddOptions(new List<string>{"可审核候选","U7 现场试验","全部生成尝试"});
   statistics=AppTheme.Label(root,"正在连接审核服务…",new Vector2(.03f,.905f),new Vector2(.59f,.935f),20,AppTheme.Muted);
   AppTheme.Label(w.Main,"官方原文与参考图",new Vector2(.04f,.935f),new Vector2(.96f,.99f),27,AppTheme.TargetCyan);
   var media=AppTheme.Panel(w.Main,"Official reference",new Vector2(.04f,.565f),new Vector2(.96f,.925f));
   image=AppTheme.Rect(media,"Reference image",Vector2.zero,Vector2.one).gameObject.AddComponent<RawImage>();image.color=Color.clear;
   var enlarge=image.gameObject.AddComponent<Button>();enlarge.targetGraphic=image;enlarge.transition=Selectable.Transition.None;enlarge.onClick.AddListener(EnlargeReference);
   image.gameObject.AddComponent<AspectRatioFitter>().aspectMode=AspectRatioFitter.AspectMode.FitInParent;
   previousPhoto=AppTheme.Button(w.Main,"上一张",new Vector2(.04f,.50f),new Vector2(.25f,.56f),()=>ChangePhoto(-1));
   nextPhoto=AppTheme.Button(w.Main,"下一张",new Vector2(.75f,.50f),new Vector2(.96f,.56f),()=>ChangePhoto(1));
   photoCaption=AppTheme.Label(w.Main,"尚未选择候选",new Vector2(.27f,.50f),new Vector2(.73f,.56f),22,AppTheme.Muted);photoCaption.alignment=TextAnchor.MiddleCenter;
   official=AppContent.Scroll(w.Main,"Official source text",new Vector2(.02f,.02f),new Vector2(.98f,.48f));
   AppTheme.Label(w.Aside,"生成任务与逐项审核",new Vector2(.03f,.935f),new Vector2(.97f,.99f),27,AppTheme.TargetCyan);
   generated=AppContent.Scroll(w.Aside,"Candidate instructions and checks",new Vector2(.02f,.46f),new Vector2(.98f,.925f));
   for(int i=0;i<fields.Length;i++){
    int index=i;float x=i%2==0?.03f:.515f;float y=i<2?.36f:.265f;
    var button=AppTheme.Button(w.Aside,captions[i]+"：未评价",new Vector2(x,y),new Vector2(x+.455f,y+.083f),()=>Rate(index),AppIcon.Inspect);ratings.Add(button);
   }
   AppTheme.Label(w.Aside,"审核人",new Vector2(.03f,.195f),new Vector2(.14f,.25f),22,AppTheme.Muted);
   reviewer=Input(w.Aside,"请填写审核人",new Vector2(.15f,.19f),new Vector2(.97f,.25f),100,false);
   note=Input(w.Aside,"审核理由或草稿；未填完四项时保存为待审核",new Vector2(.03f,.02f),new Vector2(.97f,.175f),4000,true);
   reviewer.onValueChanged.AddListener(_=>Changed());note.onValueChanged.AddListener(_=>Changed());
   save=AppTheme.Button(w.FooterRight,"保存审核",Vector2.zero,Vector2.one,()=>StartCoroutine(Save()),AppIcon.Save,true);AppActionBar.Add(w.FooterRight,save);
   next=AppTheme.Button(w.FooterRight,"下一份待审",Vector2.zero,Vector2.one,Next,AppIcon.Play);AppActionBar.Add(w.FooterRight,next);
   use=AppTheme.Button(w.FooterLeft,"U7 现场试验",Vector2.zero,Vector2.one,()=>StartCoroutine(Enter()),AppIcon.Camera,true);AppActionBar.Add(w.FooterLeft,use);
   export=AppTheme.Button(w.FooterLeft,"导出审核",Vector2.zero,Vector2.one,()=>StartCoroutine(ExportReview()),AppIcon.Save);AppActionBar.Add(w.FooterLeft,export);
   discard=AppTheme.Button(w.HeaderActions,"刷新",Vector2.zero,Vector2.one,()=>{dirty=false;if(listing!=null)StartCoroutine(LoadPlan(planId));else StartCoroutine(Initialize());},AppIcon.Inspect);AppActionBar.Add(w.HeaderActions,discard);
   status=AppTheme.Label(root,"请逐项核对官方资料；现场试验不会自动改变审核意见。",new Vector2(.03f,.105f),new Vector2(.97f,.13f),19,AppTheme.Muted);BindBack();Controls();
  }
  InputField Input(Transform parent,string hint,Vector2 min,Vector2 max,int limit,bool multiline){
   var area=AppTheme.Panel(parent,hint,min,max);area.GetComponent<Image>().color=AppTheme.ButtonBackground;
   var input=area.gameObject.AddComponent<InputField>();input.targetGraphic=area.GetComponent<Image>();input.characterLimit=limit;
   input.lineType=multiline?InputField.LineType.MultiLineNewline:InputField.LineType.SingleLine;
   input.textComponent=AppTheme.Label(area,"",new Vector2(.025f,.04f),new Vector2(.975f,.96f),23);input.textComponent.alignment=TextAnchor.UpperLeft;
   input.placeholder=AppTheme.Label(area,hint,new Vector2(.025f,.04f),new Vector2(.975f,.96f),22,AppTheme.Muted);return input;
  }
  void BindBack(){AppShell.BindBack("返回任务列表",Close,()=>!busy&&!dirty);AppShell.PlaceBack(AppWorkspace.BackMin,AppWorkspace.BackMax);}
  string Verdict(string value){return value=="approved"?"通过":value=="rejected"?"未通过":"待审核";}
  string TrialCaption(Trial t){return t.device+" · "+t.intent.Replace("我希望","")+" · 第"+t.repeat+"次 · "+(t.contract_pass?Verdict(t.decision):"生成未通过");}
  string Rating(string value){return value=="pass"?"通过":value=="fail"?"不通过":"未评价";}
  void Changed(){if(rendering||candidate==null||!candidate.contract_pass)return;dirty=true;Controls();}
  void Controls(){
   bool editable=!busy&&candidate!=null&&candidate.contract_pass;
   foreach(var b in ratings)b.interactable=editable;reviewer.interactable=note.interactable=editable;save.interactable=editable;
   use.interactable=!busy&&!dirty&&candidate!=null&&candidate.can_experiment;
   next.interactable=!busy&&!dirty&&listing!=null;export.interactable=!busy&&!dirty&&listing!=null;
   plans.interactable=attempts.interactable=filter.interactable=!busy&&!dirty&&listing!=null;back.interactable=!busy&&!dirty;
   discard.interactable=!busy;discard.GetComponentInChildren<Text>().text=dirty?"放弃修改":"刷新";
   previousPhoto.interactable=nextPhoto.interactable=!busy&&candidate!=null&&candidate.images!=null&&candidate.images.Length>1;
  }
  void Clear(RectTransform content){foreach(Transform child in content){child.gameObject.SetActive(false);Destroy(child.gameObject);}var scroll=content.GetComponentInParent<ScrollRect>();if(scroll!=null)scroll.verticalNormalizedPosition=1;}
  IEnumerator Initialize(){
   if(busy)yield break;busy=true;Controls();string raw=null,error=null;
   try{
    yield return Request(Api,"GET",null,(s,e)=>{raw=s;error=e;});if(error!=null){status.text=error;yield break;}
    var catalog=JsonUtility.FromJson<Catalog>(raw);if(catalog.contract!="baseline-review-v1"){status.text="请更新后端以使用人工审核。";yield break;}
    var list=new List<PlanInfo>();foreach(var p in catalog.plans)if(p.available)list.Add(p);available=list.ToArray();
    rendering=true;plans.ClearOptions();plans.AddOptions(list.ConvertAll(p=>p.title));rendering=false;
    if(available.Length==0){status.text="本机尚未安装可审核的固定评价资料，请检查后端资料路径。";yield break;}
   }finally{busy=false;Controls();}
   if(available!=null&&available.Length>0)yield return LoadPlan(available[0].id);
  }
  IEnumerator LoadPlan(string identity){
   if(busy||dirty)yield break;string preferred=identity==planId&&candidate!=null?candidate.trial_id:null;busy=true;Controls();string raw=null,error=null;
   try{yield return Request(Api+"/"+identity,"GET",null,(s,e)=>{raw=s;error=e;});if(error!=null){status.text=error;yield break;}
    listing=JsonUtility.FromJson<Trials>(raw);planId=identity;Stats();
   }finally{busy=false;Controls();}
   RenderTrials(preferred);
  }
  void Stats(){if(listing!=null)statistics.text=AppTheme.Readable("全部 "+listing.scheduled+" 次 · 契约 "+listing.contract_pass+" · 已审 "+listing.reviewed+"/"+listing.contract_pass+" · 人工通过 "+listing.approved+" · 通过率 "+listing.human_rate);}
  void RenderTrials(string preferred){
   if(listing==null)return;visible.Clear();foreach(var t in listing.trials)if(filter.value==2||(filter.value==1?t.can_experiment:t.contract_pass))visible.Add(t);
   rendering=true;attempts.ClearOptions();attempts.AddOptions(visible.ConvertAll(TrialCaption));
   int index=visible.FindIndex(t=>t.trial_id==preferred);if(index<0)index=visible.FindIndex(t=>t.can_experiment);if(index<0)index=0;attempts.SetValueWithoutNotify(index);rendering=false;
   if(visible.Count>0)StartCoroutine(LoadCandidate(visible[index].trial_id));else{candidate=null;Controls();status.text="当前筛选下没有候选。";}
  }
  IEnumerator LoadCandidate(string trial){
   if(busy||dirty)yield break;busy=true;Controls();int stamp=++generation;string raw=null,error=null;
   try{
    yield return Request(Api+"/"+planId+"/trials/"+trial,"GET",null,(s,e)=>{raw=s;error=e;});if(error!=null){status.text=error;yield break;}
    candidate=JsonUtility.FromJson<Candidate>(raw);rendering=true;CloseReference();
    Clear(official);Clear(generated);AppContent.Paragraph(official,string.IsNullOrEmpty(candidate.official_text)?"本次没有形成可审核候选。请查看右侧的检索或编译失败记录。":candidate.official_text,24);
    AppContent.Paragraph(generated,candidate.intent+"\n"+candidate.scope,23,AppTheme.Muted);AppContent.Paragraph(generated,candidate.text,24);
    reviewer.text=candidate.label==null?"":candidate.label.reviewer;note.text=candidate.label==null?"":candidate.label.note;
    RefreshRatings();rendering=false;dirty=false;photoIndex=0;image.color=Color.clear;
    status.text=candidate.contract_pass?"四项均明确评价后计入人工审核；可保存未完成的草稿。":"本次失败已保留，不纳入人工审核通过率分母。";
    if(candidate.images!=null&&candidate.images.Length>0)StartCoroutine(LoadPhoto(stamp,0));else photoCaption.text="无参考图";
   }finally{rendering=false;busy=false;Controls();}
  }
  void RefreshRatings(){for(int i=0;i<fields.Length;i++){string value=candidate.label==null?"pending":(string)typeof(Label).GetField(fields[i]).GetValue(candidate.label);ratings[i].GetComponentInChildren<Text>().text=captions[i]+"："+Rating(value);ratings[i].targetGraphic.color=value=="pass"?new Color(.04f,.30f,.23f):value=="fail"?new Color(.33f,.10f,.12f):AppTheme.ButtonBackground;}}
  void Rate(int index){if(candidate==null||candidate.label==null)return;var field=typeof(Label).GetField(fields[index]);string current=(string)field.GetValue(candidate.label);field.SetValue(candidate.label,current=="pending"?"pass":current=="pass"?"fail":"pending");RefreshRatings();Changed();}
  void ChangePhoto(int offset){if(candidate==null||candidate.images==null||candidate.images.Length==0)return;photoIndex=(photoIndex+offset+candidate.images.Length)%candidate.images.Length;StartCoroutine(LoadPhoto(generation,photoIndex));}
  void EnlargeReference(){if(texture==null||image.color.a<.1f)return;CloseReference();referenceViewer=Spatial.SpatialReferenceViewer.Open(root,texture,"官方参考图 · "+(photoIndex+1)+" / "+candidate.images.Length);}
  void CloseReference(){if(referenceViewer!=null)referenceViewer.Close();referenceViewer=null;}
  IEnumerator LoadPhoto(int stamp,int index){
   var item=candidate.images[index];photoCaption.text="参考图加载中…";
   using(var request=UnityWebRequest.Get(origin+item.url)){
    request.timeout=20;requests.Add(request);yield return request.SendWebRequest();requests.Remove(request);
    if(closed||stamp!=generation||index!=photoIndex)yield break;
    if(request.result!=UnityWebRequest.Result.Success||Hash(request.downloadHandler.data)!=item.sha256){photoCaption.text="参考图未通过校验，请重试";yield break;}
    var nextTexture=new Texture2D(2,2);if(!ImageConversion.LoadImage(nextTexture,request.downloadHandler.data)){Destroy(nextTexture);yield break;}
    CloseReference();if(texture!=null)Destroy(texture);texture=nextTexture;image.texture=texture;image.color=Color.white;image.GetComponent<AspectRatioFitter>().aspectRatio=texture.width/(float)texture.height;
    photoCaption.text="参考图 "+(index+1)+" / "+candidate.images.Length+" · 点击放大";
   }
  }
  string Hash(byte[] data){using(var sha=System.Security.Cryptography.SHA256.Create())return BitConverter.ToString(sha.ComputeHash(data)).Replace("-","").ToLowerInvariant();}
  IEnumerator Save(){
   if(busy||candidate==null||candidate.label==null)yield break;var label=candidate.label;label.reviewer=reviewer.text.Trim();label.note=note.text.Trim();bool pending=false,failed=false;
   foreach(string field in fields){string value=(string)typeof(Label).GetField(field).GetValue(label);pending|=value=="pending";failed|=value=="fail";}
   label.decision=pending?"pending":failed?"rejected":"approved";
   if(!pending&&(string.IsNullOrWhiteSpace(label.reviewer)||string.IsNullOrWhiteSpace(label.note))){status.text="请填写审核人和理由后保存正式审核；也可保留未评价项目保存草稿。";yield break;}
   busy=true;Controls();string raw=null,error=null;
   try{yield return Request(Api+"/"+planId+"/trials/"+candidate.trial_id+"/review","POST",JsonUtility.ToJson(new SaveReview{plan_sha256=candidate.plan_sha256,revision=candidate.revision,label=label}),(s,e)=>{raw=s;error=e;});
    if(error!=null){status.text=error+"；请先保留当前意见，刷新后重试。";yield break;}
    var summary=JsonUtility.FromJson<PlanInfo>(raw);candidate.revision=listing.revision=summary.revision;listing.reviewed=summary.reviewed;listing.approved=summary.approved;listing.human_rate=summary.human_rate;
    foreach(var t in listing.trials)if(t.trial_id==candidate.trial_id)t.decision=label.decision;
    for(int i=0;i<visible.Count;i++)attempts.options[i].text=TrialCaption(visible[i]);attempts.RefreshShownValue();
    dirty=false;Stats();status.text="已保存："+Verdict(label.decision)+"。现场试验与人工审核结果分别记录。";
   }finally{busy=false;Controls();}
  }
  void Next(){if(busy||dirty||listing==null||candidate==null)return;int start=visible.FindIndex(t=>t.trial_id==candidate.trial_id);for(int i=1;i<=visible.Count;i++){int index=(start+i)%visible.Count;if(visible[index].contract_pass&&visible[index].decision=="pending"){rendering=true;attempts.SetValueWithoutNotify(index);rendering=false;StartCoroutine(LoadCandidate(visible[index].trial_id));return;}}status.text="当前列表的候选已全部审核。";}
  IEnumerator ExportReview(){
   if(busy||dirty)yield break;busy=true;Controls();string raw=null,error=null;
   try{yield return Request(Api+"/"+planId+"/export","POST","{}",(s,e)=>{raw=s;error=e;});status.text=error??("审核已导出到后端目录："+JsonUtility.FromJson<Export>(raw).path);}
   finally{busy=false;Controls();}
  }
  IEnumerator Enter(){
   if(busy||dirty||candidate==null||!candidate.can_experiment)yield break;busy=true;Controls();string raw=null,error=null;
   try{yield return Request(Api+"/"+planId+"/trials/"+candidate.trial_id+"/use","POST",JsonUtility.ToJson(new Use{plan_sha256=candidate.plan_sha256,manifest_sha256=candidate.compilation_manifest_sha256}),(s,e)=>{raw=s;error=e;});
    if(error!=null){status.text=error;yield break;}var job=JsonUtility.FromJson<Job>(raw);root.gameObject.SetActive(false);
    Spatial.SpatialGuidanceController.OpenCompiledBaseline(origin,job.id,()=>{if(!closed){root.gameObject.SetActive(true);BindBack();StartCoroutine(LoadCandidate(candidate.trial_id));}});
   }finally{busy=false;Controls();}
  }
  IEnumerator Request(string path,string method,string body,Action<string,string> result){
   using(var request=new UnityWebRequest(origin+path,method)){
    request.downloadHandler=new DownloadHandlerBuffer();request.timeout=30;
    if(body!=null){request.uploadHandler=new UploadHandlerRaw(Encoding.UTF8.GetBytes(body));request.SetRequestHeader("Content-Type","application/json");}
    requests.Add(request);yield return request.SendWebRequest();requests.Remove(request);string raw=request.downloadHandler.text,error=null;
    if(request.result!=UnityWebRequest.Result.Success){error="审核服务暂不可用。";try{var value=JsonUtility.FromJson<Failure>(raw);if(!string.IsNullOrEmpty(value.detail))error=value.detail;}catch(Exception){}}
    if(!closed)result(raw,error);
   }
  }
  void Close(){if(busy||dirty){status.text="请先保存审核草稿，或点击“放弃修改”后返回。";return;}closed=true;done?.Invoke();Destroy(gameObject);}
  void OnDestroy(){closed=true;CloseReference();foreach(var request in requests)try{request.Abort();}catch(ObjectDisposedException){}requests.Clear();if(texture!=null)Destroy(texture);}
 }
}
