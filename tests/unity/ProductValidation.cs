using System;
using System.Collections;
using System.IO;
using System.Reflection;
using Manual2AR;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;
using UnityEngine.Networking;
using System.Text;
using System.Security.Cryptography;
using UnityEngine.UI;

public static class ProductValidation {
 const string Key="Manual2AR.Integration.Validation";static bool started;static int errors;static double since;
 static string Folder {get{return Path.Combine(Application.dataPath,"../Validation");}}
 [InitializeOnLoadMethod] static void Attach(){if(SessionState.GetBool(Key,false)){since=EditorApplication.timeSinceStartup;Application.logMessageReceived+=Log;EditorApplication.update+=Tick;}}
 public static void Run(){Directory.CreateDirectory(Folder);SessionState.SetBool(Key,true);EditorSceneManager.OpenScene("Assets/Manual2AR/Scenes/Welcome.unity");EditorApplication.isPlaying=true;}
 static void Log(string text,string stack,LogType type){if(type==LogType.Error||type==LogType.Exception||type==LogType.Assert){errors++;File.AppendAllText(Path.Combine(Folder,"errors.txt"),text+"\n"+stack+"\n");}}
 static object Field(object o,string name){var flags=BindingFlags.Instance|BindingFlags.NonPublic|BindingFlags.Public;var field=o.GetType().GetField(name,flags);if(field!=null)return field.GetValue(o);return o.GetType().GetProperty(name,flags).GetValue(o);}
 static object Invoke(object o,string name,params object[] args){return o.GetType().GetMethod(name,BindingFlags.Instance|BindingFlags.NonPublic|BindingFlags.Public).Invoke(o,args);}
 static void Check(bool ok,string message){if(!ok)throw new Exception(message);}
 static void Tick(){if(errors>0||EditorApplication.timeSinceStartup-since>180){SessionState.SetBool(Key,false);EditorApplication.Exit(2);return;}if(started||!EditorApplication.isPlaying)return;var welcome=UnityEngine.Object.FindObjectOfType<WelcomeController>();if(welcome==null||Field(welcome,"catalog")==null||(bool)Field(welcome,"connecting"))return;started=true;UnityEngine.Object.FindObjectOfType<AppShell>().StartCoroutine(Scenario());}
 static IEnumerator Wait(Func<bool> condition,string reason){float until=Time.realtimeSinceStartup+20;while(!condition()&&Time.realtimeSinceStartup<until)yield return null;Check(condition(),reason);}
 static IEnumerator Shot(string name){yield return null;yield return new WaitForSecondsRealtime(.5f);Capture(name);}
 static void Capture(string name){
  Check(UnityEngine.EventSystems.EventSystem.current!=null,"Scene has no clickable UI EventSystem");
  var camera=Camera.main;Check(camera!=null,"Missing scene camera");var canvases=UnityEngine.Object.FindObjectsOfType<Canvas>();var modes=new RenderMode[canvases.Length];var cameras=new Camera[canvases.Length];
  var target=camera.targetTexture;var previous=RenderTexture.active;var rt=RenderTexture.GetTemporary(1920,1080,24);
  try{camera.targetTexture=rt;for(int i=0;i<canvases.Length;i++){modes[i]=canvases[i].renderMode;cameras[i]=canvases[i].worldCamera;canvases[i].renderMode=RenderMode.ScreenSpaceCamera;canvases[i].worldCamera=camera;canvases[i].planeDistance=1;}
   Canvas.ForceUpdateCanvases();camera.Render();RenderTexture.active=rt;var image=new Texture2D(1920,1080,TextureFormat.RGB24,false);image.ReadPixels(new Rect(0,0,1920,1080),0,0);image.Apply();File.WriteAllBytes(Path.Combine(Folder,name),image.EncodeToPNG());UnityEngine.Object.Destroy(image);
  }finally{for(int i=0;i<canvases.Length;i++){canvases[i].renderMode=modes[i];canvases[i].worldCamera=cameras[i];}camera.targetTexture=target;RenderTexture.active=previous;RenderTexture.ReleaseTemporary(rt);}
 }
 [Serializable] class DebugImage {public string preview_url,url;}
 [Serializable] class DebugImages {public DebugImage[] images;}
 static string Hash(byte[] data){using(var sha=SHA256.Create())return BitConverter.ToString(sha.ComputeHash(data)).Replace("-","").ToLowerInvariant();}
 static IEnumerator Call(string url,string method,string json,Action<string> done){
  using(var request=new UnityWebRequest(url,method)){request.downloadHandler=new DownloadHandlerBuffer();request.timeout=30;if(json!=null){request.uploadHandler=new UploadHandlerRaw(Encoding.UTF8.GetBytes(json));request.SetRequestHeader("Content-Type","application/json");}yield return request.SendWebRequest();Check(request.result==UnityWebRequest.Result.Success,"Test API failed: "+request.responseCode+" "+request.downloadHandler.text);done(request.downloadHandler.text);}
 }
 static IEnumerator Frame(string origin,Action<byte[]> done){
  DebugImages images=null;yield return Call(origin+"/api/learning/images","GET",null,raw=>images=JsonUtility.FromJson<DebugImages>(raw));
  using(var request=UnityWebRequest.Get(origin+images.images[0].preview_url)){yield return request.SendWebRequest();Check(request.result==UnityWebRequest.Result.Success,"Controlled backend frame missing");done(request.downloadHandler.data);}
 }
 static void NoDiagnostics(){
  foreach(var button in UnityEngine.Object.FindObjectsOfType<Button>()){
   if(!button.gameObject.activeInHierarchy)continue;var text=button.GetComponentInChildren<Text>();if(text==null)continue;
   foreach(var word in new[]{"保存画面","使用图片","静态图片","云端识别","本地识别","刷新连接","刷新设备","查看本次记录"})Check(!text.text.Contains(word),"Diagnostic control is visible: "+text.text);
  }
 }
 static void CheckBack(string label){
  var shell=UnityEngine.Object.FindObjectOfType<AppShell>();var button=(Button)Field(shell,"back");
  Check(button!=null&&button.gameObject.activeInHierarchy,"Missing contextual back button");Check(button.GetComponentInChildren<Text>().text==label,"Wrong parent navigation: "+button.GetComponentInChildren<Text>().text);
 }
 static int CheckFraming(){
  var go=new GameObject("Framing Pixel Validation");var framing=go.AddComponent<CameraFraming>();var source=new Texture2D(160,120,TextureFormat.RGB24,false);source.filterMode=FilterMode.Point;source.wrapMode=TextureWrapMode.Clamp;
  var pixels=new Color32[160*120];for(int y=0;y<120;y++)for(int x=0;x<160;x++)pixels[y*160+x]=new Color32((byte)x,(byte)(y*2),(byte)((x/20+y/20)%2==0?40:210),255);source.SetPixels32(pixels);source.Apply(false);
  int passed=0;var ratios=new[]{1f,16f/9,9f/16,3f/4,4f/3};
  for(int aspect=0;aspect<5;aspect++)foreach(int angle in new[]{0,90,180,270})foreach(bool mirror in new[]{false,true}){
   framing.SetAspect(aspect);var prior=RenderTexture.active;var frame=framing.Capture(source,angle,mirror,1280);Check(RenderTexture.active==prior,"Capture changed the global render target");
   Check(Mathf.Abs(frame.width/(float)frame.height-ratios[aspect])<.0001f,"Wrong capture ratio");
   float upW=angle%180==0?160:120,upH=angle%180==0?120:160;float cutW=Mathf.Min(upW,upH*ratios[aspect]),cutH=Mathf.Min(upH,upW/ratios[aspect]);
   foreach(float px in new[]{.15f,.5f,.85f})foreach(float py in new[]{.15f,.5f,.85f}){
    int x=Mathf.FloorToInt(frame.width*px),y=Mathf.FloorToInt(frame.height*py);
    float u=((upW-cutW)*.5f+(x+.5f)*cutW/frame.width)/upW,v=((upH-cutH)*.5f+(y+.5f)*cutH/frame.height)/upH;
    float rawU=u,rawV=v;if(angle==90){rawU=1-v;rawV=u;}else if(angle==180){rawU=1-u;rawV=1-v;}else if(angle==270){rawU=v;rawV=1-u;}if(mirror)rawV=1-rawV;
    int sx=Mathf.Clamp(Mathf.FloorToInt(rawU*160),0,159),sy=Mathf.Clamp(Mathf.FloorToInt(rawV*120),0,119);var expected=pixels[sy*160+sx];Color32 actual=frame.GetPixel(x,y);
    Check(Mathf.Abs(actual.r-expected.r)<=2&&Mathf.Abs(actual.g-expected.g)<=3,"Preview/capture geometry mismatch: "+CameraFraming.Ratios[aspect]+" "+angle+" mirror="+mirror+" sample="+x+","+y+" got="+actual+" expected="+expected);
   }
   var decoded=new Texture2D(2,2);Check(ImageConversion.LoadImage(decoded,frame.EncodeToJPG(90)),"Cropped JPEG did not decode");Check(decoded.width==frame.width&&decoded.height==frame.height,"Uploaded JPEG differs from preview dimensions");
   UnityEngine.Object.Destroy(decoded);UnityEngine.Object.Destroy(frame);passed++;
  }
  var crop=CameraFraming.CenterCrop(1920,1080,0,0);Check(Mathf.Abs(crop.x-.21875f)<.00001f&&crop.y==0,"Square crop is not centered");
  UnityEngine.Object.Destroy(source);UnityEngine.Object.Destroy(go);return passed;
 }
 static IEnumerator Scenario(){
  Check(AppTheme.Readable("打印状态检查").IndexOf((char)0x200b)>=0,"Chinese wrapping missing");
  Check(AppTheme.Font!=null&&AppTheme.Font.HasCharacter('学'),"Embedded Chinese font not available");
  Check(WindowsLocalBootstrap.IsNetworkPath(@"\\wsl.localhost\Ubuntu\demo\Manual2AR_Data"),"WSL UNC path was not identified");
  Check(WindowsLocalBootstrap.IsNetworkPath("//wsl$/Ubuntu/demo/Manual2AR_Data"),"Forward-slash UNC path was not identified");
  Check(!WindowsLocalBootstrap.IsNetworkPath(@"C:\Users\demo\Manual2AR_Data"),"Local Windows path was classified as a network share");
  var clock=new Manual2AR.Spatial.SpatialPlayback();clock.Configure(3);clock.SetAvailable(true);Check(clock.Play(),"Playback did not start");clock.Tick(1);
  Check(Mathf.Abs(clock.Progress-1f/3)<.001f,"Playback depends on camera update count");clock.SetAvailable(false);float stopped=clock.Progress;clock.Tick(10);
  Check(clock.State=="paused"&&clock.Progress==stopped,"Tracking loss did not pause animation");clock.SetAvailable(true);Check(clock.State=="paused","Tracking recovery auto-executed an action");
  Check(clock.Replay()&&clock.Progress==0,"Replay kept old progress");Check(clock.Tick(3)&&clock.State=="finished"&&!clock.Tick(1),"Animation finish was emitted more than once");
  Check(SceneManager.sceneCountInBuildSettings==4,"Build must contain exactly four product scenes");
  int cropCases=CheckFraming();
  var welcome=UnityEngine.Object.FindObjectOfType<WelcomeController>();
  Check(AppShell.SelectedService==null,"Initial entry skipped the service library");NoDiagnostics();yield return Shot("01-service-library.png");
  welcome.OpenService("bambu-a1-mini");Check(AppShell.SelectedService!=null,"Service selection did not persist");
  yield return Shot("02-teaching-home.png");string origin=AppShell.SelectedService.backend_url;
  AppShell.Open("PrinterLearning");yield return Wait(()=>!AppShell.Changing&&UnityEngine.Object.FindObjectOfType<PrinterLearningController>()!=null,"Learning did not open");
  var learning=UnityEngine.Object.FindObjectOfType<PrinterLearningController>();yield return Wait(()=>!(bool)Field(learning,"busy"),"Learning not ready");
  CheckBack("返回教学首页");
  UnityEngine.Object.Destroy(((Canvas)Field(UnityEngine.Object.FindObjectOfType<AppShell>(),"shell")).gameObject);yield return null;yield return null;CheckBack("返回教学首页");
  Check(((CameraFraming)Field(learning,"framing")).AspectIndex==0,"Default framing must be 1:1");
  Check(((LearningKnowledge)Field(learning,"knowledge")).cards.Length==8,"Missing knowledge cards");
  Check(learning.GetComponentsInChildren<Dropdown>(true).Length==0,"Learning still has diagnostic selectors");NoDiagnostics();yield return Shot("03-learning.png");
  byte[] bytes=null;yield return Frame(origin,data=>bytes=data);
  var fullFrame=new Texture2D(2,2,TextureFormat.RGB24,false);ImageConversion.LoadImage(fullFrame,bytes);var cropped=((CameraFraming)Field(learning,"framing")).Capture(fullFrame,0,false,640);bytes=cropped.EncodeToJPG(90);UnityEngine.Object.Destroy(cropped);UnityEngine.Object.Destroy(fullFrame);
  string sha=Hash(bytes);LearningRun run=null;
  yield return Call(origin+"/api/learning/runs","POST",JsonUtility.ToJson(new LearningBegin{provider="auto",source="camera"}),raw=>run=JsonUtility.FromJson<LearningRun>(raw));
  Check(run.provider=="opencv"&&run.fallback_used,"Controlled missing-GPU fallback was not exercised");
  LearningReply result=null;yield return Call(origin+"/api/learning/runs/"+run.run_id+"/locate","POST",JsonUtility.ToJson(new LearningFrame{client_frame_id=1,image_base64=Convert.ToBase64String(bytes),expected_source_sha256=sha}),raw=>result=JsonUtility.FromJson<LearningReply>(raw));
  Check(result.source_sha256==sha&&result.client_frame_id==1,"Learning frame identity mismatch");
  learning.GetType().GetField("runId",BindingFlags.Instance|BindingFlags.NonPublic).SetValue(learning,run.run_id);
  var texture=new Texture2D(2,2,TextureFormat.RGB24,false);ImageConversion.LoadImage(texture,bytes);
  Invoke(learning,"RenderReply",result,texture,bytes,Time.realtimeSinceStartup,0f,0f,1,sha,false);
  Check(((PrinterLearningOverlay)Field(learning,"overlay")).VisibleCount>0,"Learning masks were not rendered");yield return Shot("04-learning-recognition.png");
  learning.StartCoroutine((IEnumerator)Invoke(learning,"ChangeFraming",2));yield return Wait(()=>Field(learning,"runId")==null&&((CameraFraming)Field(learning,"framing")).AspectIndex==2,"Changing ratio did not close the old session");
  Check(!(bool)Field(learning,"trackingActive")&&((PrinterLearningOverlay)Field(learning,"overlay")).VisibleCount==0,"Changing ratio kept old masks");
  AppShell.SelectService(null);AppShell.BindTeachingBack();Check(AppShell.SelectedService!=null,"Direct scene entry could not resolve its teaching service");
  AppShell.GoBack();yield return Wait(()=>!AppShell.Changing&&SceneManager.GetActiveScene().name=="Welcome","Learning did not release");
  Check(AppShell.SelectedService!=null,"Home lost selected service");yield return Shot("05-return-teaching-home.png");
  AppShell.Open("PrinterGuidance");yield return Wait(()=>!AppShell.Changing&&UnityEngine.Object.FindObjectOfType<PrinterGuidanceController>()!=null,"Guidance did not open");
  var guidance=UnityEngine.Object.FindObjectOfType<PrinterGuidanceController>();yield return Wait(()=>(bool)Field(guidance,"connected"),"Guidance not connected");NoDiagnostics();CheckBack("返回教学首页");yield return Shot("06-guidance-catalog.png");
  guidance.StartCoroutine((IEnumerator)Invoke(guidance,"BeginSelected","a1_mini_standalone_unboxing_v1","standalone_unboxing",false));yield return Wait(()=>Field(guidance,"run")!=null,"Unboxing did not start");NoDiagnostics();yield return Shot("07-guidance-overview.png");Invoke(guidance,"CloseModal");yield return Shot("08-guidance-step.png");
  var tutorial=(GuidanceRun)Field(guidance,"run");GuidanceRun spatialChapter=null;
  foreach(string chapter in new[]{"U4","U5"}){
   yield return Call(origin+"/api/guidance/runs/"+tutorial.run_id+"/browse","POST",JsonUtility.ToJson(new GuidanceBrowse{state_id=tutorial.state_id,revision=tutorial.revision,target_state_id=chapter}),raw=>tutorial=JsonUtility.FromJson<GuidanceRun>(raw));
   Invoke(guidance,"Apply",tutorial);Invoke(guidance,"CloseModal");Check(((Button)Field(guidance,"spatialEntry")).gameObject.activeSelf,chapter+" lacks spatial entry");
  }
  yield return Call(origin+"/api/guidance/runs/"+tutorial.run_id+"/browse","POST",JsonUtility.ToJson(new GuidanceBrowse{state_id=tutorial.state_id,revision=tutorial.revision,target_state_id="U6"}),raw=>spatialChapter=JsonUtility.FromJson<GuidanceRun>(raw));
  Invoke(guidance,"Apply",spatialChapter);Invoke(guidance,"CloseModal");
  Check(((Button)Field(guidance,"spatialEntry")).gameObject.activeSelf,"U6 has no spatial entry");Invoke(guidance,"OpenSpatial");
  var spatial=UnityEngine.Object.FindObjectOfType<Manual2AR.Spatial.SpatialGuidanceController>();
  yield return Wait(()=>Field(spatial,"plan")!=null,"Spatial plan missing");
  var spatialPlan=(Manual2AR.Spatial.Plan)Field(spatial,"plan");Check(spatialPlan.actions.Length==10&&spatialPlan.chapters.Length==4,"Unboxing extension catalog missing");
  spatial.StartCoroutine((IEnumerator)Invoke(spatial,"BeginSession","replay",false));
  yield return Wait(()=>Field(spatial,"last")!=null&&((Manual2AR.Spatial.Reply)Field(spatial,"last")).target_ready,"Spatial replay missing");
  CheckBack("返回图文指导");var firstSpatial=(Manual2AR.Spatial.Reply)Field(spatial,"last");
  yield return Wait(()=>Field(spatial,"referenceTexture")!=null,"Official reference disappeared during session start");
  Check(((RawImage)Field(spatial,"reference")).transform.parent.name=="Reference viewport","Reference is not confined to its own viewport");
  Check(firstSpatial.lines.Length==3&&firstSpatial.pose.matrix.Length==16,"Metric arrow/pose missing");
  Check(firstSpatial.visual!=null&&firstSpatial.visual.trajectory.Length==33,"Metric motion path missing");
  Check(!(bool)Field(spatial,"setupVisible"),"Setup controls are mixed into normal guidance");
  int authorScope=(int)Field(spatial,"authorGeneration");string spatialSession=((Manual2AR.Spatial.Session)Field(spatial,"session")).session_id;
  Check((bool)Invoke(spatial,"AuthorReplyCurrent",authorScope,spatialSession),"Current authoring scope was rejected");Invoke(spatial,"CancelAuthor");
  Check(!(bool)Invoke(spatial,"AuthorReplyCurrent",authorScope,spatialSession),"Cancelled authoring accepted a late reply");
  var metricOverlay=(Manual2AR.Spatial.SpatialOverlay)Field(spatial,"overlay");metricOverlay.accepting=true;
  Canvas.ForceUpdateCanvases();var metricRect=metricOverlay.rectTransform;var bounds=metricRect.rect;
  Vector2 quarter=RectTransformUtility.WorldToScreenPoint(null,metricRect.TransformPoint(new Vector3(bounds.xMin+bounds.width*.25f,bounds.yMax-bounds.height*.25f,0)));
  metricOverlay.OnPointerClick(new UnityEngine.EventSystems.PointerEventData(UnityEngine.EventSystems.EventSystem.current){position=quarter});
  Check(metricOverlay.picks.Count==1&&Mathf.Abs(metricOverlay.picks[0].x-firstSpatial.width*.25f)<1&&Mathf.Abs(metricOverlay.picks[0].y-firstSpatial.height*.25f)<1,"UI click does not map to submitted image pixels");
  metricOverlay.accepting=false;metricOverlay.picks.Clear();metricOverlay.SetVerticesDirty();
  Canvas.ForceUpdateCanvases();Invoke(spatial,"RefreshCallout");
  var calloutRect=(RectTransform)Field(Field(spatial,"callout"),"root");var imageCorners=new Vector3[4];var labelCorners=new Vector3[4];metricRect.GetWorldCorners(imageCorners);calloutRect.GetWorldCorners(labelCorners);
  Check(labelCorners[0].x>=imageCorners[0].x-1&&labelCorners[2].x<=imageCorners[2].x+1,"Operation label extends outside camera image");
  Invoke(spatial,"PlaybackCommand","play");yield return new WaitForSecondsRealtime(.6f);Check(((Manual2AR.Spatial.SpatialPlayback)Field(spatial,"playback")).Progress>0,"Playback did not advance");
  Invoke(spatial,"PlaybackCommand","pause");float held=((Manual2AR.Spatial.SpatialPlayback)Field(spatial,"playback")).Progress;yield return new WaitForSecondsRealtime(.3f);
  Check(Mathf.Abs(((Manual2AR.Spatial.SpatialPlayback)Field(spatial,"playback")).Progress-held)<.001f,"Pause did not hold the animation");
  yield return Shot("spatial-01-slide.png");Invoke(spatial,"Select",1);
  yield return Wait(()=>Field(spatial,"last")!=null&&((Manual2AR.Spatial.Reply)Field(spatial,"last")).lines.Length>20,"Fastening ring missing");
  yield return Shot("spatial-02-fasten.png");Invoke(spatial,"Select",4);
  yield return Wait(()=>Field(spatial,"last")!=null&&((Manual2AR.Spatial.Reply)Field(spatial,"last")).action_id=="holder.slide","U7 did not open");
  yield return Shot("spatial-03-holder.png");
  Invoke(spatial,"Select",3);yield return Wait(()=>Field(spatial,"last")!=null&&((Manual2AR.Spatial.Reply)Field(spatial,"last")).action_id=="holder.base","Base screws did not open");
  Check(((System.Collections.ICollection)Field(spatial,"targetButtons")).Count==2,"Two screw selectors missing");Invoke(spatial,"SelectTarget",1);
  yield return Wait(()=>Field(spatial,"last")!=null&&((Manual2AR.Spatial.Reply)Field(spatial,"last")).target_id=="second","Second screw kept first screw geometry");
  Check(((Manual2AR.Spatial.Reply)Field(spatial,"last")).visual.label=="底座螺丝 2","Second screw label mismatch");Invoke(spatial,"MarkOperation");yield return Shot("spatial-04-second-screw.png");
  Invoke(spatial,"SelectChapter","U4");yield return Wait(()=>Field(spatial,"last")!=null&&((Manual2AR.Spatial.Reply)Field(spatial,"last")).action_id=="zlock.remove","U4 chapter navigation failed");
  Check(((System.Collections.ICollection)Field(spatial,"targetButtons")).Count==4,"Z lock needs four screw selectors");Check(((System.Collections.ICollection)Field(spatial,"tabs")).Count==4,"U4 action tabs missing");
  Invoke(spatial,"SelectTarget",3);yield return Wait(()=>Field(spatial,"last")!=null&&((Manual2AR.Spatial.Reply)Field(spatial,"last")).target_id=="fourth","Fourth transport screw missing");yield return Shot("extension-01-zlock.png");
  Invoke(spatial,"Select",Array.FindIndex(spatialPlan.actions,a=>a.action_id=="toolhead.tie"));yield return Wait(()=>Field(spatial,"last")!=null&&((Manual2AR.Spatial.Reply)Field(spatial,"last")).visual!=null&&((Manual2AR.Spatial.Reply)Field(spatial,"last")).visual.kind=="cut","Tie reference missing");
  Check(((Manual2AR.Spatial.Reply)Field(spatial,"last")).visual.tool_lines.Length==2,"Cut reference geometry missing");yield return Shot("extension-02-tie.png");
  Invoke(spatial,"Select",Array.FindIndex(spatialPlan.actions,a=>a.action_id=="packing.foam"));yield return Wait(()=>Field(spatial,"last")!=null&&((Manual2AR.Spatial.Reply)Field(spatial,"last")).visual!=null&&((Manual2AR.Spatial.Reply)Field(spatial,"last")).visual.kind=="highlight","Foam highlight missing");
  Check(((System.Collections.ICollection)Field(spatial,"targetButtons")).Count==3,"Optional foam positions missing");
  Invoke(spatial,"SelectChapter","U5");yield return Wait(()=>Field(spatial,"last")!=null&&((Manual2AR.Spatial.Reply)Field(spatial,"last")).action_id=="bed.tighten","U5 chapter navigation failed");
  Check(((System.Collections.ICollection)Field(spatial,"targetButtons")).Count==3,"Bed needs three screw selectors");Check(((Button)Field(spatial,"verify")).GetComponentInChildren<Text>().text=="人工确认","Bed tightening should not be a VLM check");
  spatial.StartCoroutine((IEnumerator)Invoke(spatial,"Verify"));yield return null;Check(((Text)Field(spatial,"checkResult")).text.Contains("人工确认"),"Manual confirmation not shown");yield return Shot("extension-03-bed.png");
  AppShell.GoBack();yield return Wait(()=>UnityEngine.Object.FindObjectOfType<Manual2AR.Spatial.SpatialGuidanceController>()==null,"Spatial view did not release");
  Check(((RectTransform)Field(guidance,"root")).gameObject.activeSelf,"Tutorial did not resume");
  Check(((GuidanceRun)Field(guidance,"run")).revision==spatialChapter.revision,"Spatial view changed tutorial progress");
  CheckBack("返回任务列表");AppShell.GoBack();yield return null;Check(SceneManager.GetActiveScene().name=="PrinterGuidance"&&((GameObject)Field(guidance,"catalogPanel")).activeSelf,"Guidance skipped its task catalog");CheckBack("返回教学首页");
  AppShell.GoBack();yield return Wait(()=>!AppShell.Changing&&SceneManager.GetActiveScene().name=="Welcome","Guidance did not release");
  AppShell.Open("PrinterInspection");yield return Wait(()=>!AppShell.Changing&&UnityEngine.Object.FindObjectOfType<PrinterInspectionController>()!=null,"Inspection did not open");
  var inspection=UnityEngine.Object.FindObjectOfType<PrinterInspectionController>();yield return Wait(()=>(bool)Field(inspection,"connected"),"Inspection not connected");
  Check(inspection.GetComponentsInChildren<Dropdown>(true).Length==0,"Inspection still has diagnostic selectors");NoDiagnostics();yield return Shot("09-inspection-catalog.png");
  CheckBack("返回教学首页");
  ((GameObject)Field(inspection,"menu")).SetActive(false);((GameObject)Field(inspection,"page")).SetActive(true);Invoke(inspection,"BindTaskBack");CheckBack("返回检查列表");
  InspectionRun checkRun=null;yield return Call(origin+"/api/inspection/runs","POST",JsonUtility.ToJson(new InspectionBegin{provider="opencv",source="camera"}),raw=>checkRun=JsonUtility.FromJson<InspectionRun>(raw));
  inspection.GetType().GetField("run",BindingFlags.Instance|BindingFlags.NonPublic).SetValue(inspection,checkRun);
  string job=Guid.NewGuid().ToString("N"),api=origin+"/api/inspection/runs/"+checkRun.run_id;InspectionProgress progress=null;
  yield return Call(api+"/checks","POST",JsonUtility.ToJson(new InspectionCheckStart{request_id=job,image_base64=Convert.ToBase64String(bytes),source_sha256=sha,client_frame_id=1}),raw=>progress=JsonUtility.FromJson<InspectionProgress>(raw));
  bool localized=false;float deadline=Time.realtimeSinceStartup+25;
  while(Time.realtimeSinceStartup<deadline){
   yield return Call(api+"/checks/"+job+"?after_revision="+progress.revision,"GET",null,raw=>progress=JsonUtility.FromJson<InspectionProgress>(raw));
   if(progress.result!=null&&!string.IsNullOrEmpty(progress.result.run_id)){
    Invoke(inspection,"ApplyReply",progress.result,bytes,Time.realtimeSinceStartup);
    if(progress.result.stage=="localization"&&!localized){localized=true;yield return Shot("10-inspection-localization.png");}
   }
   if(progress.phase=="completed"||progress.phase=="failed")break;
   yield return new WaitForSecondsRealtime(.1f);
  }
  Check(localized&&progress.phase=="completed","Staged inspection was not rendered; phase="+progress.phase);
  Check(progress.result.public_result.status=="anomaly_detected","Anomaly status missing");NoDiagnostics();yield return Shot("11-inspection-result.png");
  AppShell.GoBack();yield return Wait(()=>((GameObject)Field(inspection,"menu")).activeSelf&&!(bool)Field(inspection,"busy"),"Inspection skipped its task catalog");Check(SceneManager.GetActiveScene().name=="PrinterInspection","Inspection jumped directly to teaching home");CheckBack("返回教学首页");
  AppShell.GoBack();yield return Wait(()=>!AppShell.Changing&&SceneManager.GetActiveScene().name=="Welcome","Inspection did not release");
  welcome=UnityEngine.Object.FindObjectOfType<WelcomeController>();yield return Wait(()=>welcome!=null&&Field(welcome,"catalog")!=null,"Welcome missing");Invoke(welcome,"Library");
  Check(AppShell.SelectedService==null,"Cannot return to service library");yield return Shot("12-return-library.png");
  Check(UnityEngine.Object.FindObjectsOfType<AppShell>().Length==1,"Duplicate application shell");Check(errors==0,"Runtime errors");
  File.WriteAllText(Path.Combine(Folder,"success.json"),"{\"runtime_errors\":0,\"scenes\":4,\"service_library\":true,\"service_context\":true,\"diagnostic_controls_hidden\":true,\"controlled_learning_render\":true,\"automatic_cpu_fallback\":true,\"staged_inspection\":true,\"real_model_calls\":0,\"camera_hardware_tested\":false,\"center_crop_cases\":40,\"hierarchical_navigation\":true,\"navigation_canvas_repaired\":true,\"ratio_change_closes_session\":true,\"event_system_present\":true,\"spatial_replay\":true,\"spatial_metric_geometry\":true,\"spatial_pixel_picking\":true,\"spatial_reference_loaded\":true,\"spatial_preserves_tutorial_progress\":true}");
  SessionState.SetBool(Key,false);EditorApplication.Exit(0);
 }
}
