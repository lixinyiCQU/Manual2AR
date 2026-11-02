using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Security.Cryptography;
using System.Text;
using UnityEngine;
using UnityEngine.UI;
using UnityEngine.EventSystems;
using UnityEngine.Networking;
namespace Manual2AR {
 public sealed class PrinterInspectionController:MonoBehaviour,IAppModule {
  static readonly Color Background=new Color(.018f,.04f,.08f),Card=AppTheme.PanelBackground,Accent=AppTheme.TargetCyan,Muted=new Color(.65f,.75f,.83f);
  CameraFraming framing;AppAspectSelector aspectSelector;AppTaskMenu taskMenu;
  Font font;RectTransform root,viewport,content;GameObject menu,page;RawImage picture,mask;Material maskMaterial;Text connection,notice;
  PrinterInspectionPresentation presentation;
  int cameraIndex=-1;Button inspect,start,switchCamera,records,clear;
  readonly List<Button> taskButtons=new List<Button>();readonly List<bool> taskAvailability=new List<bool>();readonly List<GameObject> boxes=new List<GameObject>(),objectLabels=new List<GameObject>();
  readonly Stack<GameObject> boxPool=new Stack<GameObject>(),labelPool=new Stack<GameObject>();
  readonly List<int[]> tagBoxes=new List<int[]>();
  Texture2D captureTexture;
  RawImage livePreview;GameObject liveInset,occlusionDialog;Text displayMode;Button occlusionReview;
  int renderFrames,cameraFrames,resultFrames,appliedFrames,gcBefore;float metricsSince,lastCaptureMs;bool performancePending;
  readonly List<float> frameTimes=new List<float>(512);
  string offeredOcclusionCheck="",modalCheck="",modalSha="";
  InspectionSettings settings;InspectionCatalog catalog;InspectionRun run;InspectionReply latest;
  new WebCamTexture camera;Texture2D pairedTexture,labelTexture;
  bool busy,connected,tracking,monitoring,paired,opening,trackingRequest,inspectionInProgress;int sequence,trackingFailures,inspectionRevision;
  UnityWebRequest activeProgressRequest;string currentJobId="",currentJobRun="";
  enum UserAction {None,Inspect,Save,Clear,Back,StartCamera,SwitchCamera,ReviewOcclusion,ApproveOcclusion}
  UserAction pendingAction;float lastTrack,lastInspect,lastFrameCapture,lastOverlayApplyMs,noticeUntil;
  string runSource="",runProvider="";
  const string Api="/api/inspection/runs/";
  string Source {get{return "camera";}}
  string Provider {get{return settings.default_provider;}}
  void Start(){
   font=AppTheme.Font;framing=gameObject.AddComponent<CameraFraming>();BuildUI();AppShell.BindTeachingBack();
   try{settings=JsonUtility.FromJson<InspectionSettings>(File.ReadAllText(Path.Combine(Application.streamingAssetsPath,"Inspection.json")));}
   catch(Exception){connection.text="检查服务尚未就绪，请稍后重新连接。";return;}
   settings.backend_url=AppShell.BackendUrl(settings.backend_url);
   Application.targetFrameRate=settings.target_render_fps;metricsSince=Time.realtimeSinceStartup;gcBefore=GC.CollectionCount(0);
   RefreshCameras();StartCoroutine(Connect());
  }
  void Update(){
            if(AppShell.Changing)return;
   for(int i=0;i<taskButtons.Count;i++)taskButtons[i].interactable=taskAvailability[i]&&connected&&!busy&&!opening;
   if(settings==null)return;
   renderFrames++;if(frameTimes.Count<1024)frameTimes.Add(Time.unscaledDeltaTime*1000);if(camera!=null&&camera.isPlaying&&camera.didUpdateThisFrame)cameraFrames++;
   if(Time.realtimeSinceStartup-metricsSince>=settings.telemetry_seconds)PublishPerformance();
   if(liveInset!=null){bool show=settings.live_preview_inset&&page.activeSelf&&Source=="camera"&&paired&&camera!=null&&camera.isPlaying;liveInset.SetActive(show);if(show){livePreview.texture=framing.Live(camera,settings.capture_max_side);livePreview.uvRect=new Rect(0,0,1,1);livePreview.rectTransform.localEulerAngles=Vector3.zero;var bounds=((RectTransform)livePreview.transform.parent).rect;float scale=Mathf.Min(bounds.width/livePreview.texture.width,bounds.height/livePreview.texture.height);livePreview.rectTransform.sizeDelta=new Vector2(livePreview.texture.width*scale,livePreview.texture.height*scale);}}
   if(displayMode!=null)displayMode.text=paired?"同步标注画面":"实时相机";
   occlusionReview.gameObject.SetActive(latest!=null&&latest.public_result!=null&&latest.public_result.requires_occlusion_confirmation&&!inspectionInProgress);
   bool controlsBusy=busy&&!trackingRequest&&!inspectionInProgress;
   start.interactable=!controlsBusy&&!opening&&Source=="camera";
   switchCamera.interactable=!controlsBusy&&!opening&&Source=="camera"&&WebCamTexture.devices.Length>1;
   clear.interactable=!controlsBusy&&!opening;aspectSelector.SetInteractable(!busy&&!opening&&!inspectionInProgress);
   inspect.interactable=!controlsBusy&&!opening&&(camera!=null&&camera.isPlaying&&camera.width>16);
   records.interactable=run!=null&&latest!=null&&!controlsBusy&&!opening&&!inspectionInProgress;
   if(notice!=null)notice.gameObject.SetActive(page.activeSelf&&Time.realtimeSinceStartup<noticeUntil);
   if(!page.activeSelf)return;
   LayoutImage();
   if(!paired&&Source=="camera"&&camera!=null&&camera.isPlaying){picture.texture=framing.Live(camera,settings.capture_max_side);LayoutImage();}
   if(paired&&latest!=null&&latest.stage=="tracking"&&(Time.realtimeSinceStartup-lastFrameCapture)*1000>settings.max_overlay_age_ms){ClearOverlay();returnToLiveIfCamera();presentation.ShowPositionUnavailable();}
   if(busy||opening)return;
   if(pendingAction!=UserAction.None){var action=pendingAction;pendingAction=UserAction.None;Execute(action);return;}
   if(monitoring&&Time.realtimeSinceStartup-lastInspect>=settings.rescan_seconds){StartCoroutine(Inspect());return;}
   if(tracking&&Source=="camera"&&camera!=null&&camera.isPlaying&&camera.didUpdateThisFrame&&Time.realtimeSinceStartup-lastTrack>=settings.tracking_interval_seconds){lastTrack=Time.realtimeSinceStartup;StartCoroutine(Track());}
  }
  IEnumerator Request(string path,string method,string json,Action<string,string> done,bool fast=false){
   using(var r=new UnityWebRequest(settings.backend_url.TrimEnd('/')+path,method)){
    r.downloadHandler=new DownloadHandlerBuffer();r.timeout=fast?settings.tracking_request_timeout_seconds:settings.request_timeout_seconds;
    if(json!=null){r.uploadHandler=new UploadHandlerRaw(Encoding.UTF8.GetBytes(json));r.SetRequestHeader("Content-Type","application/json");}
    UnityWebRequestAsyncOperation op=null;string failure=null;try{op=r.SendWebRequest();}catch(Exception){failure="连接未建立";}
    if(op==null){done(null,failure);yield break;}yield return op;
    if(r.result!=UnityWebRequest.Result.Success){var error=Parse<InspectionError>(r.downloadHandler.text);failure=error!=null&&!string.IsNullOrEmpty(error.detail)?error.detail:"后端连接未完成，请检查服务并重试。";}
    done(r.downloadHandler.text,failure);
   }
  }
  static T Parse<T>(string raw)where T:class{try{return JsonUtility.FromJson<T>(raw);}catch{return null;}}
  IEnumerator TrackingRequest(string path,byte[] bytes,Action<string,string> done){
   using(var request=new UnityWebRequest(settings.backend_url.TrimEnd('/')+path,"POST")){
    request.uploadHandler=new UploadHandlerRaw(bytes);request.downloadHandler=new DownloadHandlerBuffer();request.SetRequestHeader("Content-Type","image/jpeg");request.timeout=settings.tracking_request_timeout_seconds;
    yield return request.SendWebRequest();done(request.downloadHandler.text,request.result==UnityWebRequest.Result.Success?null:"tracking_request_failed");
   }
  }
  static string Hash(byte[] data){using(var hash=SHA256.Create())return BitConverter.ToString(hash.ComputeHash(data)).Replace("-","").ToLowerInvariant();}

  IEnumerator Connect(){if(busy)yield break;busy=true;connected=false;
   yield return Request("/api/inspection/tasks","GET",null,(raw,error)=>{if(error==null){catalog=Parse<InspectionCatalog>(raw);connected=catalog!=null&&catalog.tasks!=null;if(connected)RenderTasks();}});
   busy=false;connection.text=connected?"选择检查项目，完成后查看结果。":"暂时无法连接检查服务，请稍后重试。";
  }
  void RenderTasks(){
   taskMenu.Clear();taskButtons.Clear();taskAvailability.Clear();
   foreach(var task in catalog.tasks){var item=task;var card=taskMenu.Add(item.id,item.title,item.description,item.available,()=>Choose(item));taskButtons.Add(card.Button);taskAvailability.Add(item.available);}
  }
  void BindTaskBack(){AppShell.BindBack("返回检查列表",()=>Schedule(UserAction.Back),()=>!opening&&(!busy||trackingRequest||inspectionInProgress));}
  void Choose(InspectionTask task){
   if(busy||opening||!task.available)return;
   menu.SetActive(false);page.SetActive(true);BindTaskBack();latest=null;ClearOverlay();presentation.Clear();
   presentation.SetCaptureHint("让整块打印板及四周边缘入镜，避免遮挡和强反光。");
   StartCoroutine(StartCamera());
  }
  void RefreshCameras(){
   var all=WebCamTexture.devices;if(cameraIndex<0){cameraIndex=0;for(int i=0;i<all.Length;i++)if(settings!=null&&all[i].name==settings.camera_name)cameraIndex=i;}
   cameraIndex=Mathf.Clamp(cameraIndex,0,Mathf.Max(0,all.Length-1));
  }
  IEnumerator EnsureRun(int expectedRevision=-1){
   int owner=expectedRevision>=0?expectedRevision:inspectionRevision;string expectedSource=Source,expectedProvider=Provider;
   if(run!=null&&runSource==expectedSource&&runProvider==expectedProvider)yield break;
   if(run!=null){var old=run.run_id;run=null;yield return Request(Api+old,"DELETE",null,(raw,error)=>{});if(owner!=inspectionRevision)yield break;}
   InspectionRun created=null;
   yield return Request("/api/inspection/runs","POST",JsonUtility.ToJson(new InspectionBegin{provider=expectedProvider,source=expectedSource}),(raw,error)=>{if(error==null)created=Parse<InspectionRun>(raw);});
   if(owner!=inspectionRevision||!page.activeSelf){if(created!=null)yield return Request(Api+created.run_id,"DELETE",null,(raw,error)=>{});yield break;}
   if(created==null){ShowNotice("检查暂不可用，请稍后重试。");yield break;}
   run=created;runSource=expectedSource;runProvider=expectedProvider;sequence=0;latest=null;
  }
  IEnumerator StartCamera(){
   if(busy||opening)yield break;opening=true;ClearOverlay();presentation.Clear();RefreshCameras();presentation.SetCaptureHint("正在启动摄像头……");
   if(!Application.HasUserAuthorization(UserAuthorization.WebCam))yield return Application.RequestUserAuthorization(UserAuthorization.WebCam);
   if(!Application.HasUserAuthorization(UserAuthorization.WebCam)){presentation.SetCaptureHint("请允许使用摄像头，然后重新启动。");opening=false;yield break;}
   StopCamera();ClearOverlay();presentation.Clear();var all=WebCamTexture.devices;
   if(all.Length==0){presentation.SetCaptureHint("未找到摄像头，请连接后重试。");opening=false;yield break;}
   camera=new WebCamTexture(all[Mathf.Clamp(cameraIndex,0,all.Length-1)].name,settings.camera_width,settings.camera_height,settings.camera_fps);camera.Play();float until=Time.realtimeSinceStartup+12;
   while(camera!=null&&camera.width<=16&&Time.realtimeSinceStartup<until)yield return null;
   opening=false;if(camera==null||camera.width<=16){StopCamera();presentation.SetCaptureHint("摄像头未能启动，请检查权限或关闭其他占用程序。");yield break;}
   busy=true;yield return EnsureRun();busy=false;paired=false;picture.texture=framing.Live(camera,settings.capture_max_side);picture.color=Color.white;
   presentation.SetCaptureHint("让整块打印板及四周边缘入镜，点击检查按钮开始。");
   if(run!=null)yield return SendEvent("camera.started",null);
  }
  void StopCamera(){if(camera!=null){camera.Stop();Destroy(camera);camera=null;}tracking=false;}
  byte[] Capture(){
   if(camera==null||!camera.isPlaying||camera.width<=16)return null;float began=Time.realtimeSinceStartup;
   captureTexture=framing.Capture(camera,camera.videoRotationAngle,camera.videoVerticallyMirrored,settings.capture_max_side,captureTexture);
   var bytes=captureTexture.EncodeToJPG(settings.jpeg_quality);lastCaptureMs=(Time.realtimeSinceStartup-began)*1000;return bytes;
  }
  IEnumerator ChangeFraming(int index){
   if(busy||opening)yield break;inspectionRevision++;tracking=monitoring=false;CloseOcclusionDialog();ClearOverlay();presentation.Clear();latest=null;busy=true;
   var old=run;run=null;if(old!=null)yield return Request(Api+old.run_id,"DELETE",null,(raw,error)=>{});
   framing.SetAspect(index);paired=false;if(camera!=null&&camera.isPlaying)picture.texture=framing.Live(camera,settings.capture_max_side);LayoutImage();
   presentation.SetCaptureHint("画幅已调整，让打印板及边缘入镜后重新检查。");busy=false;
  }

  IEnumerator ProgressRequest(int owner,string path,string method,string json,Action<string,string> done){
   if(owner!=inspectionRevision)yield break;
   using(var request=new UnityWebRequest(settings.backend_url.TrimEnd('/')+path,method)){
    request.downloadHandler=new DownloadHandlerBuffer();request.timeout=15;
    if(json!=null){request.uploadHandler=new UploadHandlerRaw(Encoding.UTF8.GetBytes(json));request.SetRequestHeader("Content-Type","application/json");}
    activeProgressRequest=request;UnityWebRequestAsyncOperation operation=null;try{operation=request.SendWebRequest();}catch(Exception){}
    if(operation!=null)yield return operation;
    if(activeProgressRequest==request)activeProgressRequest=null;
    if(owner==inspectionRevision)done(request.downloadHandler.text,operation!=null&&request.result==UnityWebRequest.Result.Success?null:"progress_request_failed");
   }
  }
  bool AcceptProgress(InspectionProgress value,int owner,string job,int frameId,string sha){return owner==inspectionRevision&&page.activeSelf&&value!=null&&run!=null&&value.run_id==run.run_id&&value.job_id==job&&value.client_frame_id==frameId&&value.source_sha256==sha&&!string.IsNullOrEmpty(value.check_id);}
  void CancelInspection(){
   inspectionRevision++;inspectionInProgress=false;busy=false;tracking=monitoring=false;
   if(activeProgressRequest!=null)activeProgressRequest.Abort();
   string job=currentJobId,owner=currentJobRun;currentJobId=currentJobRun="";
   if(!string.IsNullOrEmpty(job)&&!string.IsNullOrEmpty(owner))StartCoroutine(Request(Api+owner+"/checks/"+job,"DELETE",null,(raw,error)=>{},true));
  }
  void FinishInspection(){inspectionInProgress=false;busy=false;currentJobId=currentJobRun="";lastInspect=Time.realtimeSinceStartup;}
  IEnumerator Inspect(){
   if(busy||opening)yield break;float captureTime=Time.realtimeSinceStartup;byte[] bytes=Capture();if(bytes==null)yield break;
   CloseOcclusionDialog();int owner=++inspectionRevision;busy=inspectionInProgress=true;tracking=false;latest=null;ClearOverlay();ShowPair(bytes);presentation.ShowProcessing();if(Source=="camera")returnToLiveIfCamera();yield return EnsureRun(owner);
   if(owner!=inspectionRevision)yield break;
   if(run==null){FinishInspection();presentation.ShowResult(null,null);yield break;}
   int id=++sequence;string sha=Hash(bytes),job=Guid.NewGuid().ToString("N");currentJobId=job;currentJobRun=run.run_id;
   InspectionProgress update=null;
   yield return ProgressRequest(owner,Api+run.run_id+"/checks","POST",JsonUtility.ToJson(new InspectionCheckStart{request_id=job,image_base64=Convert.ToBase64String(bytes),source_sha256=sha,client_frame_id=id}),(raw,error)=>{if(error==null)update=Parse<InspectionProgress>(raw);});
   if(owner!=inspectionRevision)yield break;
   if(!AcceptProgress(update,owner,job,id,sha)){CancelInspection();presentation.ShowResult(null,null);yield break;}
   int revision=0,failures=0;float deadline=Time.realtimeSinceStartup+settings.request_timeout_seconds;
   while(owner==inspectionRevision){
    if(!AcceptProgress(update,owner,job,id,sha))break;
    if(update.revision>revision){
     revision=update.revision;var reply=update.result;
     if(reply!=null&&!string.IsNullOrEmpty(reply.run_id)){
      if(!Accept(reply,id,sha,update.check_id))break;
      ApplyReply(reply,bytes,captureTime);
      StartCoroutine(SendEvent("frontend.render",new InspectionRender{run_id=run.run_id,check_id=reply.check_id,job_id=job,progress_phase=update.phase,progress_revision=revision,client_frame_id=id,source_sha256=sha,identity_matched=true,request_ms=(Time.realtimeSinceStartup-captureTime)*1000,frame_age_ms=(Time.realtimeSinceStartup-captureTime)*1000,overlay_apply_ms=lastOverlayApplyMs}));
      // Give the localization frame a render opportunity before replacing it.
      yield return null;if(owner!=inspectionRevision)yield break;
     }
    }
    if(update.finished){
     bool completed=update.phase=="completed"&&latest!=null&&latest.stage=="inspection";
     if(!completed){if(latest!=null&&latest.stage=="localization")presentation.ShowLocalizationUnavailable(latest.public_result);else presentation.ShowResult(null,null);}
     FinishInspection();if(completed)MaybeOfferOcclusion();trackingFailures=0;tracking=completed&&Source=="camera"&&latest.active_tracks>0;
     if(completed&&Source=="camera"&&settings.continuous_monitoring&&!monitoring){monitoring=true;StartCoroutine(SendEvent("monitor.started",null));}
     yield break;
    }
    if(Time.realtimeSinceStartup>deadline)break;
    yield return new WaitForSecondsRealtime(settings.progress_poll_seconds);if(owner!=inspectionRevision)yield break;
    InspectionProgress next=null;
    yield return ProgressRequest(owner,Api+run.run_id+"/checks/"+job+"?after_revision="+revision,"GET",null,(raw,error)=>{if(error==null)next=Parse<InspectionProgress>(raw);});
    if(owner!=inspectionRevision)yield break;
    if(next==null){if(++failures>2)break;continue;}failures=0;update=next;
   }
   if(owner!=inspectionRevision)yield break;
   CancelInspection();if(latest!=null&&latest.stage=="localization")presentation.ShowLocalizationUnavailable(latest.public_result);else presentation.ShowResult(null,null);
  }
  bool Accept(InspectionReply reply,int id,string sha,string check){return reply!=null&&run!=null&&reply.run_id==run.run_id&&reply.client_frame_id==id&&reply.source_sha256==sha&&(check==null||reply.check_id==check);}
  IEnumerator Track(){
   if(busy||run==null||latest==null)yield break;byte[] bytes=Capture();if(bytes==null)yield break;busy=trackingRequest=true;float time=Time.realtimeSinceStartup;int id=++sequence;string sha=Hash(bytes),check=latest.check_id;InspectionReply reply=null;
   yield return TrackingRequest(Api+run.run_id+"/frames/jpeg?client_frame_id="+id+"&check_id="+check+"&source_sha256="+sha,bytes,(raw,error)=>{if(error==null)reply=Parse<InspectionReply>(raw);});busy=trackingRequest=false;
   if(!Accept(reply,id,sha,check)){
    ClearOverlay();returnToLiveIfCamera();tracking=reply==null&&++trackingFailures<=2;
    if(tracking)presentation.ShowTrackingState("recovering");else presentation.ShowPositionUnavailable();yield break;
   }
   trackingFailures=0;resultFrames++;
   float requestMs=(Time.realtimeSinceStartup-time)*1000;bool stale=DisplayTrackingReply(reply,bytes,time);
   yield return SendEvent("frontend.render",new InspectionRender{client_frame_id=id,source_sha256=sha,check_id=check,run_id=run.run_id,identity_matched=true,stale_hidden=stale,frame_age_ms=(Time.realtimeSinceStartup-time)*1000,request_ms=requestMs,overlay_apply_ms=stale?0:lastOverlayApplyMs,capture_encode_ms=lastCaptureMs,request_upload_bytes=bytes.Length});
  }
  bool DisplayTrackingReply(InspectionReply reply,byte[] bytes,float captureTime){
   bool stale=(Time.realtimeSinceStartup-captureTime)*1000>settings.max_overlay_age_ms;
   if(stale){ClearOverlay();returnToLiveIfCamera();presentation.ShowPositionUnavailable();}else{ApplyReply(reply,bytes,captureTime);appliedFrames++;}
   tracking=reply.active_tracks>0;presentation.ShowTrackingState(reply.tracking_state);return stale;
  }
  void ApplyReply(InspectionReply reply,byte[] bytes,float captureTime){
   var timer=System.Diagnostics.Stopwatch.StartNew();latest=reply;lastFrameCapture=captureTime;ShowPair(bytes);ClearOverlay();int[] plateBox=null;
   foreach(var obj in reply.objects??new InspectionObject[0]){
    if(obj.kind=="plate")plateBox=obj.bbox_0_1000;
    bool initial=reply.stage=="localization"||reply.stage=="inspection";
    if(initial&&obj.found&&!obj.tracking_ready&&obj.bbox_0_1000!=null)DrawBox(obj.bbox_0_1000,reply.stage=="localization");
    if(obj.bbox_0_1000!=null&&(obj.tracking_ready||initial&&obj.found))DrawObjectLabel(obj);
   }
   foreach(var candidate in reply.scene_candidates??new InspectionSceneCandidate[0]){
    if(candidate.bbox_0_1000==null)continue;DrawBox(candidate.bbox_0_1000);
    DrawObjectLabel(new InspectionObject{id=candidate.id,kind="unclassified",semantic_status="candidate",bbox_0_1000=candidate.bbox_0_1000});
   }
   if(occlusionDialog!=null&&(reply.check_id!=modalCheck||reply.public_result==null||!reply.public_result.requires_occlusion_confirmation))CloseOcclusionDialog();
   if(reply.stage=="localization")presentation.ShowLocalization(reply.public_result);else presentation.ShowResult(reply.public_result,plateBox);
   if(reply.stage!="localization"&&reply.label_map!=null)ApplyLabels(reply.label_map,reply.objects);
   timer.Stop();lastOverlayApplyMs=(float)timer.Elapsed.TotalMilliseconds;
  }
  void ApplyLabels(InspectionLabels labels,InspectionObject[] objects){
   if(labels==null||string.IsNullOrEmpty(labels.png_base64)||labels.labels==null||objects==null)return;
   byte[] png;try{png=Convert.FromBase64String(labels.png_base64);}catch(FormatException){return;}
   if(labelTexture==null)labelTexture=new Texture2D(2,2,TextureFormat.RGBA32,false,true);
   if(!ImageConversion.LoadImage(labelTexture,png,false)||labelTexture.width!=labels.width||labelTexture.height!=labels.height)return;
   if(picture.texture==null||picture.texture.width!=labels.width||picture.texture.height!=labels.height)return;
   labelTexture.filterMode=FilterMode.Point;mask.texture=labelTexture;mask.gameObject.SetActive(true);
   for(int i=1;i<=8;i++)maskMaterial.SetColor("_Palette"+i,Color.clear);
   foreach(var label in labels.labels){string kind="",semantic="";foreach(var obj in objects)if(obj.id==label.component_id){kind=obj.kind;semantic=obj.semantic_status;}maskMaterial.SetColor("_Palette"+label.label_id,kind=="plate"?new Color(.04f,.88f,.96f,latest.public_result!=null&&latest.public_result.status=="no_visible_anomaly"?118f/255:66f/255):semantic=="candidate"?new Color(1,.64f,.32f,.65f):new Color(1,28f/255,18f/255,190f/255));}
  }

  void ShowPair(byte[] bytes){
   if(pairedTexture==null)pairedTexture=new Texture2D(2,2,TextureFormat.RGB24,false);
   if(ImageConversion.LoadImage(pairedTexture,bytes)){picture.texture=pairedTexture;picture.color=Color.white;paired=true;LayoutImage();}
  }
  void returnToLiveIfCamera(){if(Source=="camera"){paired=false;picture.texture=framing.Live(camera,settings.capture_max_side);LayoutImage();}}
  void ClearOverlay(){
   mask.gameObject.SetActive(false);foreach(var box in boxes)if(box!=null){box.SetActive(false);boxPool.Push(box);}boxes.Clear();
   foreach(var label in objectLabels)if(label!=null){label.SetActive(false);labelPool.Push(label);}objectLabels.Clear();tagBoxes.Clear();
  }
  void DrawBox(int[] box,bool dashed=false){
   if(box.Length!=4)return;GameObject go;
   if(boxPool.Count>0)go=boxPool.Pop();else{
    var created=Rect("候选位置",content,Vector2.zero,Vector2.one);go=created.gameObject;
    var plain=Rect("实线",created,Vector2.zero,Vector2.one);foreach(var edge in new[]{new[]{0f,0f,1f,.018f},new[]{0f,.982f,1f,1f},new[]{0f,0f,.012f,1f},new[]{.988f,0f,1f,1f}}){var line=Rect("边框",plain,new Vector2(edge[0],edge[1]),new Vector2(edge[2],edge[3]));line.gameObject.AddComponent<Image>().color=new Color(1,.68f,.2f);}
    var dashes=Rect("虚线",created,Vector2.zero,Vector2.one);
    for(int i=0;i<12;i++){float x=i/12f,y=(i+.6f)/12f;foreach(float edge in new[]{0f,1f}){var line=Rect("定位虚线",dashes,new Vector2(x,edge),new Vector2(y,edge));line.sizeDelta=new Vector2(0,2);line.gameObject.AddComponent<Image>().color=new Color(1,.74f,.3f,.95f);var vertical=Rect("定位虚线",dashes,new Vector2(edge,x),new Vector2(edge,y));vertical.sizeDelta=new Vector2(2,0);vertical.gameObject.AddComponent<Image>().color=new Color(1,.74f,.3f,.95f);}}
   }
   var r=go.GetComponent<RectTransform>();r.anchorMin=new Vector2(box[0]/1000f,1-box[3]/1000f);r.anchorMax=new Vector2(box[2]/1000f,1-box[1]/1000f);r.offsetMin=r.offsetMax=Vector2.zero;r.Find("实线").gameObject.SetActive(!dashed);r.Find("虚线").gameObject.SetActive(dashed);go.SetActive(true);boxes.Add(go);
  }
  void DrawObjectLabel(InspectionObject obj){
   var b=obj.bbox_0_1000;if(b.Length!=4)return;string label=obj.kind=="plate"?"打印板":obj.kind=="unclassified"?"未识别物体":obj.semantic_status=="candidate"?"待确认区域":obj.kind=="residue"?"残料":"异物";GameObject go;
   if(labelPool.Count>0)go=labelPool.Pop();else{var created=Rect("目标标签",viewport,new Vector2(.5f,.5f),new Vector2(.5f,.5f));created.gameObject.AddComponent<AppRoundedImage>().radius=12;var text=TextAt(created,"",new Vector2(.04f,.04f),new Vector2(.96f,.96f),26,Color.white);text.alignment=TextAnchor.MiddleCenter;text.fontStyle=FontStyle.Bold;go=created.gameObject;}
   var r=go.GetComponent<RectTransform>();r.pivot=new Vector2(.5f,.5f);r.sizeDelta=new Vector2(label.Length>3?180:label=="打印板"?132:108,44);
   go.GetComponent<AppRoundedImage>().color=obj.kind=="plate"?new Color(.02f,.22f,.28f,.94f):obj.kind=="unclassified"?new Color(.45f,.28f,.06f,.94f):new Color(.43f,.1f,.09f,.94f);go.GetComponentInChildren<Text>(true).text=label;go.SetActive(true);r.SetAsLastSibling();objectLabels.Add(go);tagBoxes.Add(b);
  }
  void LateUpdate(){
   if(viewport==null||content==null)return;
   for(int i=0;i<objectLabels.Count;i++){var r=objectLabels[i].GetComponent<RectTransform>();var box=tagBoxes[i];var rect=content.rect;
    Vector3 anchor=content.TransformPoint(new Vector3(rect.xMin+rect.width*(box[0]+box[2])/2000f,rect.yMax-rect.height*box[1]/1000f,0));Vector2 p=viewport.InverseTransformPoint(anchor);p.y+=28;var bounds=viewport.rect;
    p.x=Mathf.Clamp(p.x,bounds.xMin+r.sizeDelta.x/2+6,bounds.xMax-r.sizeDelta.x/2-6);p.y=Mathf.Clamp(p.y,bounds.yMin+28,bounds.yMax-28);
    for(int j=0;j<i;j++){var earlier=objectLabels[j].GetComponent<RectTransform>();if(Mathf.Abs(earlier.anchoredPosition.x-p.x)<(r.sizeDelta.x+earlier.sizeDelta.x)/2&&Mathf.Abs(earlier.anchoredPosition.y-p.y)<48)p.y=Mathf.Max(bounds.yMin+28,p.y-49);}
    r.anchoredPosition=p;
   }
   if(liveInset!=null)liveInset.transform.SetAsLastSibling();
  }
  void LayoutImage(){
   var texture=picture.texture;if(texture==null)return;float scale=Mathf.Min(viewport.rect.width/texture.width,viewport.rect.height/texture.height);
   content.sizeDelta=new Vector2(texture.width*scale,texture.height*scale);content.localEulerAngles=Vector3.zero;picture.uvRect=new Rect(0,0,1,1);
  }
  IEnumerator SendEvent(string name,InspectionRender receipt){if(run==null)yield break;yield return Request(Api+run.run_id+"/events","POST",JsonUtility.ToJson(new InspectionEvent{@event=name,data=receipt??new InspectionRender()}),(raw,error)=>{},true);}
  void ClearAnnotations(){
   CloseOcclusionDialog();
   if(busy||opening)return;tracking=monitoring=false;ClearOverlay();presentation.Clear();returnToLiveIfCamera();presentation.SetCaptureHint("标注已清除，可重新检查打印板。");
  }
  IEnumerator SaveEvidence(){
   if(busy||run==null||latest==null)yield break;busy=true;bool saved=false;
   yield return Request(Api+run.run_id+"/evidence","POST",JsonUtility.ToJson(new InspectionSave{check_id=latest.check_id}),(raw,error)=>{var result=error==null?Parse<InspectionSaved>(raw):null;saved=result!=null&&result.saved;});
   busy=false;ShowNotice(saved?"检查记录已保存":"暂未保存，请稍后重试。");
  }
  void ShowNotice(string value){notice.text=value;noticeUntil=Time.realtimeSinceStartup+3;notice.gameObject.SetActive(true);}
  IEnumerator Back(){CloseOcclusionDialog();
   if(busy||opening)yield break;busy=true;tracking=monitoring=false;StopCamera();ClearOverlay();presentation.Clear();
   if(run!=null)yield return Request(Api+run.run_id,"DELETE",null,(raw,error)=>{});
   run=null;latest=null;page.SetActive(false);menu.SetActive(true);AppShell.BindTeachingBack();busy=false;
  }
  void Schedule(UserAction action){if(opening)return;if(inspectionInProgress){CancelInspection();}else if(busy&&!trackingRequest)return;pendingAction=action;}
  void Execute(UserAction action){
   switch(action){case UserAction.Inspect:StartCoroutine(Inspect());break;case UserAction.Save:StartCoroutine(SaveEvidence());break;case UserAction.Clear:ClearAnnotations();break;case UserAction.Back:StartCoroutine(Back());break;case UserAction.StartCamera:StartCoroutine(StartCamera());break;case UserAction.SwitchCamera:StartCoroutine(SwitchCamera());break;case UserAction.ReviewOcclusion:ShowOcclusionDialog();break;case UserAction.ApproveOcclusion:StartCoroutine(ApproveOcclusion());break;}
  }
  IEnumerator SwitchCamera(){
   if(busy||opening)yield break;RefreshCameras();var devices=WebCamTexture.devices;if(devices.Length<2)yield break;
   cameraIndex=(cameraIndex+1)%devices.Length;latest=null;monitoring=tracking=false;yield return StartCamera();
  }
  void PublishPerformance(){
   float elapsed=Time.realtimeSinceStartup-metricsSince;frameTimes.Sort();
   var data=new InspectionRender{render_fps=renderFrames/elapsed,camera_fps=cameraFrames/elapsed,result_fps=resultFrames/elapsed,applied_fps=appliedFrames/elapsed,unity_frame_p95_ms=frameTimes.Count==0?0:frameTimes[Mathf.FloorToInt((frameTimes.Count-1)*.95f)],gc_collections=GC.CollectionCount(0)-gcBefore,managed_heap_bytes=GC.GetTotalMemory(false),pooled_labels=labelPool.Count+objectLabels.Count,pooled_boxes=boxPool.Count+boxes.Count};
   if(run!=null&&!performancePending)StartCoroutine(PerformanceReceipt(data));metricsSince=Time.realtimeSinceStartup;gcBefore=GC.CollectionCount(0);renderFrames=cameraFrames=resultFrames=appliedFrames=0;frameTimes.Clear();
  }
  IEnumerator PerformanceReceipt(InspectionRender data){performancePending=true;try{yield return SendEvent("frontend.performance",data);}finally{performancePending=false;}}
  void MaybeOfferOcclusion(){if(latest!=null&&latest.public_result!=null&&latest.public_result.requires_occlusion_confirmation&&offeredOcclusionCheck!=latest.check_id){offeredOcclusionCheck=latest.check_id;ShowOcclusionDialog();}}
  void CloseOcclusionDialog(){if(occlusionDialog!=null){Destroy(occlusionDialog);occlusionDialog=null;}modalCheck=modalSha="";}
  void ShowOcclusionDialog(){
   if(latest==null||latest.public_result==null||!latest.public_result.requires_occlusion_confirmation||inspectionInProgress)return;CloseOcclusionDialog();modalCheck=latest.check_id;modalSha=latest.public_result.inspection_source_sha256;
   var dim=Rect("Occlusion Confirmation",root,Vector2.zero,Vector2.one);occlusionDialog=dim.gameObject;dim.gameObject.AddComponent<Image>().color=new Color(0,0,0,.72f);
   var card=Panel(dim,"人工确认",new Vector2(.23f,.25f),new Vector2(.77f,.75f));
   var title=TextAt(card,"打印头遮挡左上角",new Vector2(.055f,.77f),new Vector2(.945f,.94f),36,Color.white);title.fontStyle=FontStyle.Bold;
   TextAt(card,"可见板面未见明显异物或残料。\n\n打印头挡住的区域无法由摄像头确认。请确认这是打印头的正常遮挡，且您已人工确认板面无异物或残料。",new Vector2(.055f,.25f),new Vector2(.945f,.75f),29,Color.white);
   ButtonAt(card,"稍后确认",new Vector2(.055f,.07f),new Vector2(.35f,.21f),()=>CloseOcclusionDialog());
   ButtonAt(card,"已人工检查，确认通过",new Vector2(.39f,.07f),new Vector2(.945f,.21f),()=>{Schedule(UserAction.ApproveOcclusion);});
  }
  IEnumerator ApproveOcclusion(){
   if(busy||run==null||latest==null||modalCheck!=latest.check_id||string.IsNullOrEmpty(modalSha))yield break;
   busy=true;int owner=inspectionRevision;string identity=run.run_id,check=modalCheck,sha=modalSha;InspectionConfirmationReply reply=null;
   yield return Request(Api+identity+"/confirm-occlusion","POST",JsonUtility.ToJson(new InspectionConfirmation{check_id=check,inspection_source_sha256=sha}),(raw,error)=>{if(error==null)reply=Parse<InspectionConfirmationReply>(raw);},true);
   busy=false;if(owner!=inspectionRevision||run==null||run.run_id!=identity||latest==null||latest.check_id!=check)yield break;
   CloseOcclusionDialog();
   if(reply==null||reply.check_id!=check||reply.inspection_source_sha256!=sha){ShowNotice("当前画面已变化，请重新检查后确认。");yield break;}
   latest.decision=reply.decision;latest.public_result=reply.public_result;presentation.ShowResult(reply.public_result,null);ShowNotice("人工确认已记录，本次检查通过。");
  }
  void BuildUI(){
   var canvas=new GameObject("Manual2AR Inspection UI",typeof(RectTransform),typeof(Canvas),typeof(CanvasScaler),typeof(GraphicRaycaster));var renderer=canvas.GetComponent<Canvas>();renderer.renderMode=RenderMode.ScreenSpaceOverlay;renderer.pixelPerfect=true;renderer.sortingOrder=100;
   var scaler=canvas.GetComponent<CanvasScaler>();scaler.uiScaleMode=CanvasScaler.ScaleMode.ScaleWithScreenSize;scaler.referenceResolution=new Vector2(1920,1080);scaler.matchWidthOrHeight=.5f;root=canvas.GetComponent<RectTransform>();AppTheme.Attach(root);canvas.AddComponent<Image>().color=Background;
   if(EventSystem.current==null)new GameObject("EventSystem",typeof(EventSystem),typeof(StandaloneInputModule));
   page=Rect("打印板检查",root,Vector2.zero,Vector2.one).gameObject;
   var heading=TextAt(page.transform,"打印板检查",new Vector2(.025f,.925f),new Vector2(.50f,.982f),38,Color.white);heading.fontStyle=FontStyle.Bold;
   var caption=TextAt(page.transform,"模块三 · 打印状态检查",new Vector2(.025f,.89f),new Vector2(.50f,.927f),22,Muted);
   var controls=Panel(page.transform,"Inspection Controls",new Vector2(.025f,.795f),new Vector2(.715f,.88f));
   start=ActionButton(controls,"启动摄像头",new Vector2(.015f,.13f),new Vector2(.295f,.87f),AppIcon.Camera,()=>Schedule(UserAction.StartCamera));
   switchCamera=ActionButton(controls,"切换摄像头",new Vector2(.315f,.13f),new Vector2(.595f,.87f),AppIcon.SwitchCamera,()=>Schedule(UserAction.SwitchCamera));
   inspect=ActionButton(controls,"检查 / 重新检查",new Vector2(.615f,.13f),new Vector2(.985f,.87f),AppIcon.Inspect,()=>Schedule(UserAction.Inspect),true);
   aspectSelector=framing.AddSelector(page.transform,new Vector2(.025f,.73f),new Vector2(.715f,.782f),index=>StartCoroutine(ChangeFraming(index)));
   var cameraCard=Panel(page.transform,"Camera Card",new Vector2(.025f,.15f),new Vector2(.715f,.715f));
   viewport=Rect("Camera Stage",cameraCard,new Vector2(.006f,.012f),new Vector2(.994f,.988f));viewport.gameObject.AddComponent<RectMask2D>();
   content=Rect("Camera Pixels And Inspection Masks",viewport,new Vector2(.5f,.5f),new Vector2(.5f,.5f));
   picture=Rect("原图",content,Vector2.zero,Vector2.one).gameObject.AddComponent<RawImage>();picture.raycastTarget=false;picture.color=Color.black;
   mask=Rect("分割高亮",content,Vector2.zero,Vector2.one).gameObject.AddComponent<RawImage>();mask.raycastTarget=false;var shader=Resources.Load<Shader>("PrinterInspectionMask");if(shader==null)throw new Exception("Missing inspection shader");maskMaterial=new Material(shader);maskMaterial.SetFloat("_UseLabels",1);maskMaterial.SetFloat("_LabelOpacity",1);mask.material=maskMaterial;mask.gameObject.SetActive(false);
   presentation=gameObject.AddComponent<PrinterInspectionPresentation>();presentation.Initialize(content,page.transform,font);
   displayMode=TextAt(cameraCard,"实时相机",new Vector2(.02f,.91f),new Vector2(.35f,.98f),22,Color.white);
   liveInset=Panel(viewport,"Live Camera Inset",new Vector2(.73f,.02f),new Vector2(.99f,.29f)).gameObject;liveInset.GetComponent<AppRoundedImage>().color=new Color(.015f,.055f,.08f,.98f);
   var insetPixels=Rect("实时小预览",liveInset.transform,new Vector2(.02f,.14f),new Vector2(.98f,.98f));var liveRect=Rect("Camera",insetPixels,new Vector2(.5f,.5f),new Vector2(.5f,.5f));livePreview=liveRect.gameObject.AddComponent<RawImage>();livePreview.raycastTarget=false;TextAt(liveInset.transform,"实时相机",new Vector2(.04f,.01f),new Vector2(.98f,.15f),20,Color.white);liveInset.SetActive(false);
   occlusionReview=ButtonAt(page.transform,"确认遮挡区域",new Vector2(.75f,.16f),new Vector2(.96f,.215f),()=>Schedule(UserAction.ReviewOcclusion));occlusionReview.gameObject.SetActive(false);

   records=ActionButton(page.transform,"保存记录",new Vector2(.735f,.045f),new Vector2(.85f,.11f),AppIcon.Save,()=>Schedule(UserAction.Save));
   clear=ActionButton(page.transform,"清除标注",new Vector2(.86f,.045f),new Vector2(.975f,.11f),AppIcon.Clear,()=>Schedule(UserAction.Clear));
   notice=ScreenText(page.transform,"操作提示",new Vector2(.85f,.14f),Vector2.zero,new Vector2(450,45),"",25,Accent);notice.gameObject.SetActive(false);
   taskMenu=AppTaskMenu.Create(root,"Inspection Task Catalog","打印状态检查","Bambu Lab A1 mini · 选择检查项目");menu=taskMenu.Root.gameObject;connection=taskMenu.Status;page.SetActive(false);

  }
  Button ActionButton(Transform parent,string label,Vector2 min,Vector2 max,AppIcon symbol,Action action,bool primary=false){
   var r=Panel(parent,label,min,max);var graphic=r.GetComponent<AppRoundedImage>();graphic.color=primary?new Color(.045f,.43f,.56f):new Color(.045f,.16f,.24f);
   var button=r.gameObject.AddComponent<Button>();button.targetGraphic=graphic;var colors=button.colors;colors.highlightedColor=new Color(.6f,.9f,1);colors.pressedColor=new Color(.35f,.75f,.85f);colors.disabledColor=new Color(.42f,.5f,.56f,.85f);button.colors=colors;button.onClick.AddListener(()=>action());
   var iconRect=Rect("操作图标",r,new Vector2(.06f,.2f),new Vector2(.21f,.8f));var icon=iconRect.gameObject.AddComponent<AppIconGraphic>();icon.symbol=symbol;icon.color=Color.white;icon.raycastTarget=false;
   var text=TextAt(r,label,new Vector2(.26f,.03f),new Vector2(.97f,.97f),label.Length>6?28:30,Color.white);text.alignment=TextAnchor.MiddleCenter;text.fontStyle=FontStyle.Bold;
   return button;
  }
  Text ScreenText(Transform parent,string name,Vector2 anchor,Vector2 position,Vector2 size,string value,int fontSize,Color color){
   var r=Rect(name,parent,anchor,anchor);r.pivot=anchor;r.anchoredPosition=position;r.sizeDelta=size;var text=r.gameObject.AddComponent<Text>();text.text=value;text.font=font;text.fontSize=fontSize;text.alignment=TextAnchor.MiddleCenter;text.color=color;text.raycastTarget=false;text.supportRichText=false;return text;
  }
  RectTransform Rect(string name,Transform parent,Vector2 min,Vector2 max){var go=new GameObject(name,typeof(RectTransform));go.transform.SetParent(parent,false);var r=go.GetComponent<RectTransform>();r.anchorMin=min;r.anchorMax=max;r.offsetMin=r.offsetMax=Vector2.zero;return r;}
  RectTransform Panel(Transform parent,string name,Vector2 min,Vector2 max){var r=Rect(name,parent,min,max);r.gameObject.AddComponent<AppRoundedImage>().color=Card;var line=r.gameObject.AddComponent<Outline>();line.effectDistance=new Vector2(1,-1);line.effectColor=new Color(.07f,.23f,.32f);return r;}
  Text TextAt(Transform parent,string value,Vector2 min,Vector2 max,int size,Color color){var r=Rect("Text",parent,min,max);var text=r.gameObject.AddComponent<Text>();text.font=font;text.fontSize=size;text.color=color;text.text=value;text.supportRichText=false;text.raycastTarget=false;text.verticalOverflow=VerticalWrapMode.Truncate;return text;}
  Button ButtonAt(Transform parent,string label,Vector2 min,Vector2 max,Action action){var r=Panel(parent,label,min,max);var b=r.gameObject.AddComponent<Button>();b.targetGraphic=r.GetComponent<Graphic>();b.onClick.AddListener(()=>action());var t=TextAt(r,label,new Vector2(.025f,.025f),new Vector2(.975f,.975f),27,Color.white);t.alignment=TextAnchor.MiddleCenter;return b;}


  public IEnumerator ReleaseModule(){
   inspectionRevision++;monitoring=tracking=false;if(activeProgressRequest!=null)activeProgressRequest.Abort();StopAllCoroutines();StopCamera();
   var identity=run==null?null:run.run_id;run=null;
   if(settings!=null&&!string.IsNullOrEmpty(identity))using(var request=UnityWebRequest.Delete(settings.backend_url.TrimEnd('/')+Api+identity)){request.timeout=8;yield return request.SendWebRequest();}
  }
  void OnDisable(){
   CloseOcclusionDialog();inspectionRevision++;if(captureTexture!=null)Destroy(captureTexture);if(activeProgressRequest!=null)activeProgressRequest.Abort();StopAllCoroutines();StopCamera();if(pairedTexture!=null)Destroy(pairedTexture);if(labelTexture!=null)Destroy(labelTexture);if(maskMaterial!=null)Destroy(maskMaterial);
   if(run!=null&&settings!=null){var request=UnityWebRequest.Delete(settings.backend_url.TrimEnd('/')+Api+run.run_id);request.SendWebRequest().completed+=op=>request.Dispose();}busy=false;
  }
 }
}
