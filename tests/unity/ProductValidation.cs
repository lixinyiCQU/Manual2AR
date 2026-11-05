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
 static void Tick(){if(errors>0||EditorApplication.timeSinceStartup-since>240){SessionState.SetBool(Key,false);EditorApplication.Exit(2);return;}if(started||!EditorApplication.isPlaying)return;var welcome=UnityEngine.Object.FindObjectOfType<WelcomeController>();if(welcome==null||Field(welcome,"catalog")==null||(bool)Field(welcome,"connecting"))return;started=true;UnityEngine.Object.FindObjectOfType<AppShell>().StartCoroutine(Scenario());}
 static IEnumerator Wait(Func<bool> condition,string reason,float timeout=20){float until=Time.realtimeSinceStartup+timeout;while(!condition()&&Time.realtimeSinceStartup<until)yield return null;Check(condition(),reason);}
 static IEnumerator Shot(string name){yield return null;yield return new WaitForSecondsRealtime(.5f);Capture(name);}
 static void Capture(string name){
  Check(UnityEngine.EventSystems.EventSystem.current!=null,"Scene has no clickable UI EventSystem");
  var camera=Camera.main;Check(camera!=null,"Missing scene camera");var canvases=UnityEngine.Object.FindObjectsOfType<Canvas>();var modes=new RenderMode[canvases.Length];var cameras=new Camera[canvases.Length];
  var target=camera.targetTexture;var previous=RenderTexture.active;var rt=RenderTexture.GetTemporary(1920,1080,24);
  try{camera.targetTexture=rt;for(int i=0;i<canvases.Length;i++){modes[i]=canvases[i].renderMode;cameras[i]=canvases[i].worldCamera;canvases[i].renderMode=RenderMode.ScreenSpaceCamera;canvases[i].worldCamera=camera;canvases[i].planeDistance=1;}
   Canvas.ForceUpdateCanvases();camera.Render();RenderTexture.active=rt;var image=new Texture2D(1920,1080,TextureFormat.RGB24,false);image.ReadPixels(new Rect(0,0,1920,1080),0,0);image.Apply();File.WriteAllBytes(Path.Combine(Folder,name),image.EncodeToPNG());UnityEngine.Object.Destroy(image);
  }finally{for(int i=0;i<canvases.Length;i++){canvases[i].renderMode=modes[i];canvases[i].worldCamera=cameras[i];}camera.targetTexture=target;RenderTexture.active=previous;RenderTexture.ReleaseTemporary(rt);}
 }
 sealed class ControlledFrameSource:Manual2AR.Spatial.ISpatialFrameSource {
  readonly byte[] bytes;bool opened;public ControlledFrameSource(byte[] value){bytes=value;}public bool Ready=>opened;public string Signature=>"controlled-u7-rgb";public string ProviderId=>"desktop_rgb";public int CaptureWidth=>960;public int CaptureHeight=>720;
  public IEnumerator Open(int selected,Action<string> error){opened=true;yield break;}public byte[] Capture(){return bytes;}public void Close(){opened=false;}
 }
 static string Plain(string value){return System.Text.RegularExpressions.Regex.Replace(value??"","<[^>]*>","").Replace(((char)0x200b).ToString(),"");}
 static void ClickText(GameObject panel,string wanted){foreach(var button in panel.GetComponentsInChildren<Button>()){string text=button.GetComponentInChildren<Text>()?.text??"";if(text.Replace(((char)0x200b).ToString(),"").Contains(wanted)){button.onClick.Invoke();return;}}throw new Exception("Button not found: "+wanted);}
 [Serializable] class RecognitionCounter {public int count;}
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
  yield return UiGalleryValidation.Run(Folder);
  Check(AppTheme.Readable("打印状态检查").IndexOf((char)0x200b)>=0,"Chinese wrapping missing");
  Check(AppTheme.Font!=null&&AppTheme.Font.HasCharacter('学'),"Embedded Chinese font not available");
  string dense=AppReadableText.Wrap(new string('中',40),8,t=>t.Length);var wrappedLines=dense.Split('\n');Check(wrappedLines.Length==5,"Chinese text has premature word-run breaks");foreach(string line in wrappedLines)Check(line.Length==8,"Chinese row leaves unexplained short lines");
  string protectedWords=AppReadableText.Wrap(AppReadableText.Prepare("安装 M3-12 螺丝，料管为 520 mm。"),12,t=>t.Length);Check(protectedWords.Contains("M3-12")&&protectedWords.Contains("520\u00a0mm"),"Model names or units were split");
  foreach(string line in protectedWords.Split('\n'))Check(!line.StartsWith("，")&&!line.StartsWith("。"),"Punctuation starts a rendered line");

  Check(WindowsLocalBootstrap.IsNetworkPath(@"\\wsl.localhost\Ubuntu\demo\Manual2AR_Data"),"WSL UNC path was not identified");
  Check(WindowsLocalBootstrap.IsNetworkPath("//wsl$/Ubuntu/demo/Manual2AR_Data"),"Forward-slash UNC path was not identified");
  Check(!WindowsLocalBootstrap.IsNetworkPath(@"C:\Users\demo\Manual2AR_Data"),"Local Windows path was classified as a network share");
  var clock=new Manual2AR.Spatial.SpatialPlayback();clock.Configure(1.2f);clock.SetAvailable(true);clock.Tick(.3f);
  Check(clock.State=="playing"&&Mathf.Abs(clock.Progress-.25f)<.001f,"Automatic animation did not start");clock.SetAvailable(false);float stopped=clock.Progress;clock.Tick(10);
  Check(clock.State=="paused"&&clock.Progress==stopped,"Tracking loss did not pause animation");clock.SetAvailable(true);Check(clock.State=="playing","Tracking recovery did not resume the illustration");
  Check(clock.Tick(.9f)&&clock.State=="playing"&&clock.Progress<.001f,"Animation did not loop");Check(clock.Tick(1.2f),"Second cycle did not run");
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
  guidance.StartCoroutine((IEnumerator)Invoke(guidance,"BeginSelected","a1_mini_standalone_unboxing_v1","standalone_unboxing",false));yield return Wait(()=>Field(guidance,"run")!=null,"Unboxing did not start");NoDiagnostics();yield return Shot("07-guidance-overview.png");Check(((GameObject)Field(guidance,"modal")).GetComponent<AppModalBackdrop>().Ready,"Overview has no blurred backdrop");
  var overview=(GameObject)Field(guidance,"modal");ClickText(overview,"查看官方指南");
  yield return Wait(()=>Field(guidance,"wikiDialog")!=null&&((GameObject)Field(guidance,"wikiDialog")).GetComponentInChildren<PrinterLearningWikiView>()!=null,"Guidance did not open embedded Wiki");
  var wiki=((GameObject)Field(guidance,"wikiDialog")).GetComponentInChildren<PrinterLearningWikiView>();yield return Wait(()=>Field(wiki,"document")!=null,"Embedded unboxing Wiki did not render",90);yield return Shot("ui-01-embedded-wiki.png");
  Check(((GameObject)Field(guidance,"wikiDialog")).GetComponent<AppModalBackdrop>().Ready,"Nested Wiki has no focus backdrop");Invoke(guidance,"CloseWiki");Check(overview.activeSelf,"Closing Wiki lost the step overview");
  Invoke(guidance,"CloseModal");yield return Shot("08-guidance-step.png");
  var manualCompletion=(Button)Field(guidance,"textCompletion");yield return Wait(()=>manualCompletion.gameObject.activeSelf&&manualCompletion.interactable,"Text chapter has no manual completion action");manualCompletion.onClick.Invoke();
  yield return Wait(()=>Array.Exists(((GuidanceRun)Field(guidance,"run")).chapter_completion,c=>c.state_id=="U1"&&c.completed),"Manual chapter completion was not saved");
  Invoke(guidance,"ShowOverview",false);yield return Shot("completion-01-manual-chapter.png");Invoke(guidance,"CloseModal");
  Check(!((GameObject)Field(guidance,"placeholder")).activeSelf,"Reading chapter repeats the task outline");
  var readingCard=(RectTransform)Field(guidance,"instructionCard");Check(readingCard.anchorMax.y-readingCard.anchorMin.y>.65f,"Text-only chapter did not reclaim outline space");
  var tutorial=(GuidanceRun)Field(guidance,"run");GuidanceRun spatialChapter=null;
  yield return Call(origin+"/api/guidance/runs/"+tutorial.run_id+"/browse","POST",JsonUtility.ToJson(new GuidanceBrowse{state_id=tutorial.state_id,revision=tutorial.revision,target_state_id="U3"}),raw=>tutorial=JsonUtility.FromJson<GuidanceRun>(raw));
  Invoke(guidance,"Apply",tutorial);Invoke(guidance,"CloseModal");yield return Wait(()=>Field(guidance,"referenceTexture")!=null,"Lesson reference missing");
  Check(!((Text)Field(guidance,"count")).gameObject.activeSelf&&!((Button)Field(guidance,"restart")).gameObject.activeSelf,"Obsolete chapter count/restart visible");
  Check(!((Text)Field(guidance,"notice")).gameObject.activeSelf,"Redundant chapter switching hint visible");
  var overviewButton=(Button)Field(guidance,"overviewButton");var shellBack=(Button)Field(UnityEngine.Object.FindObjectOfType<AppShell>(),"back");
  var headerActions=((AppWorkspace)Field(guidance,"workspace")).HeaderActions;
  Check(headerActions.anchorMin.y==AppWorkspace.BackMin.y&&Mathf.Abs(((RectTransform)shellBack.transform).rect.height-AppTheme.ButtonHeight)<1,"Overview is not in the shared header slot");
  var footerBack=(RectTransform)((Button)Field(guidance,"back")).transform;var footerDone=(RectTransform)((Button)Field(guidance,"textCompletion")).transform;var footerNext=(RectTransform)((Button)Field(guidance,"next")).transform;
  Check(footerBack.parent==((AppWorkspace)Field(guidance,"workspace")).FooterRight&&Mathf.Abs(footerNext.rect.height-AppTheme.ButtonHeight)<1,"Footer does not use the common task action bar");
  var lessonPicture=(RectTransform)Field(guidance,"referencePanel");Check(readingCard.anchorMax.x<lessonPicture.anchorMin.x,"Instructions overlap official figure");
  Check(!((GameObject)Field(guidance,"captureDialog")).activeSelf,"Optional camera controls clutter the reading page");
  Check(!((Button)Field(guidance,"previousPhoto")).gameObject.activeSelf&&!((Button)Field(guidance,"nextPhoto")).gameObject.activeSelf,"Single image has redundant arrows");
  yield return Shot("lesson-01-reading-and-figure.png");Invoke(guidance,"OpenPhotoReference");CheckBack("返回教学");yield return Shot("lesson-02-photo-idle.png");
  var referenceView=(RectTransform)Field(guidance,"referenceArea");Canvas.ForceUpdateCanvases();Check(referenceView.rect.width>800,"Official figure remains too narrow");
  var referenceGraphic=(RawImage)Field(guidance,"referenceImage");var originalUV=referenceGraphic.uvRect;referenceGraphic.uvRect=new Rect(0,0,.5f,.25f);Invoke(guidance,"LayoutReference");
  var fittedReference=(RectTransform)Field(guidance,"referenceRect");var atlas=(Texture2D)Field(guidance,"referenceTexture");Check(Mathf.Abs(fittedReference.rect.width/fittedReference.rect.height-atlas.width*.5f/(atlas.height*.25f))<.01f,"GIF frame uses atlas aspect rather than its own aspect");referenceGraphic.uvRect=originalUV;Invoke(guidance,"LayoutReference");
  var cameraPicture=(RawImage)Field(guidance,"cameraImage");var photoPreviewTexture=new Texture2D(2,2,TextureFormat.RGB24,false);ImageConversion.LoadImage(photoPreviewTexture,bytes);cameraPicture.texture=photoPreviewTexture;Invoke(guidance,"LayoutTeachingPanels");
  Check(!((GameObject)Field(guidance,"cameraEmpty")).activeSelf,"Empty-camera hint covers the preview");
  var photoArea=(RectTransform)Field(guidance,"cameraArea");Check(photoArea.rect.width>900&&photoArea.rect.height>500,"Photo preview is still squeezed");
  Check(((Button)Field(guidance,"primary")).transform.parent==((AppWorkspace)Field(guidance,"captureWorkspace")).FooterRight,"Capture action is outside its dialog");
  ((Text)Field(guidance,"result")).text="本次拍照参考 · 建议调整\n请将配件分组摆放，并补拍尚未清楚入镜的部分。\n可对照官方参考图继续操作。";yield return Shot("lesson-03-photo-preview.png");Invoke(guidance,"Apply",tutorial);CheckBack("返回教学");
  Invoke(guidance,"OpenCameraSettings");CheckBack("返回拍照参考");yield return Shot("lesson-04-camera-settings.png");AppShell.GoBack();CheckBack("返回教学");AppShell.GoBack();CheckBack("返回任务列表");
  Check(!((GameObject)Field(guidance,"captureDialog")).activeSelf,"Photo dialog did not close");UnityEngine.Object.Destroy(photoPreviewTexture);

  foreach(string chapter in new[]{"U2","U6","U10"}){
   string substep=chapter=="U2"?"U2-S2":null;
   yield return Call(origin+"/api/guidance/runs/"+tutorial.run_id+"/browse","POST",JsonUtility.ToJson(new GuidanceBrowse{state_id=tutorial.state_id,revision=tutorial.revision,target_state_id=chapter,substep_id=substep}),raw=>tutorial=JsonUtility.FromJson<GuidanceRun>(raw));
   Invoke(guidance,"Apply",tutorial);Invoke(guidance,"CloseModal");yield return Shot("reader-"+chapter+"-sections.png");
   Check(tutorial.presentation.lesson!=null&&tutorial.presentation.lesson.reviewed,"Reviewed lesson data missing");
   var content=(RectTransform)Field(guidance,"body");bool actionSection=false,cautionSection=false;
   foreach(Transform child in content){if(child.name=="操作指导")actionSection=true;if(child.name=="注意事项"||child.name=="操作前注意")cautionSection=true;}
   Check(actionSection&&cautionSection,"Operation and caution sections were not separated");
   foreach(Transform child in content){if(child.name=="操作指导"){Check(child.GetComponent<AppRoundedImage>()!=null,"Action instructions have no distinct card");Check(Array.Exists(child.GetComponentsInChildren<AppIconGraphic>(),icon=>icon.symbol==AppIcon.Tool),"Action instructions lack tool icon");}foreach(var label in child.GetComponentsInChildren<Text>())Check(!label.text.Contains("当前分步骤"),"Redundant substep count remains in content");}
   var chapterTitle=(Text)Field(guidance,"chapterHeading");Check(chapterTitle.transform.parent==(Transform)Field(guidance,"instructionCard"),"Chapter title is not at top of the teaching card");
   foreach(var reader in content.GetComponentsInChildren<AppReadableText>()){
    var label=reader.GetComponent<Text>();Check(label.horizontalOverflow==HorizontalWrapMode.Overflow,"Unity word wrapping still overrides reviewed reading flow");
    Check(reader.Source.Replace("\u00a0"," ").IndexOf("\u200b")<0,"Canonical reading source contains invisible break runs");
   }
  }
  foreach(string chapter in new[]{"U4","U5"}){
   yield return Call(origin+"/api/guidance/runs/"+tutorial.run_id+"/browse","POST",JsonUtility.ToJson(new GuidanceBrowse{state_id=tutorial.state_id,revision=tutorial.revision,target_state_id=chapter}),raw=>tutorial=JsonUtility.FromJson<GuidanceRun>(raw));
   Invoke(guidance,"Apply",tutorial);Invoke(guidance,"CloseModal");Check(((Button)Field(guidance,"spatialEntry")).gameObject.activeSelf,chapter+" lacks spatial entry");
  }
  yield return Call(origin+"/api/guidance/runs/"+tutorial.run_id+"/browse","POST",JsonUtility.ToJson(new GuidanceBrowse{state_id=tutorial.state_id,revision=tutorial.revision,target_state_id="U6"}),raw=>spatialChapter=JsonUtility.FromJson<GuidanceRun>(raw));
  Invoke(guidance,"Apply",spatialChapter);Invoke(guidance,"CloseModal");
  Check(((Button)Field(guidance,"spatialEntry")).gameObject.activeSelf,"U6 has no spatial entry");Invoke(guidance,"OpenSpatial");
  var spatial=UnityEngine.Object.FindObjectOfType<Manual2AR.Spatial.SpatialGuidanceController>();
  yield return Wait(()=>Field(spatial,"plan")!=null,"Spatial plan missing");
  Check(!((RectTransform)Field(spatial,"setupBar")).gameObject.activeSelf,"Setup controls visible before explicit configuration");
  var spatialPlan=(Manual2AR.Spatial.Plan)Field(spatial,"plan");Check(spatialPlan.actions.Length==10&&spatialPlan.chapters.Length==4,"Unboxing extension catalog missing");
  spatial.StartCoroutine((IEnumerator)Invoke(spatial,"BeginSession","replay",false));
  yield return Wait(()=>Field(spatial,"last")!=null&&((Manual2AR.Spatial.Reply)Field(spatial,"last")).target_ready,"Spatial replay missing");
  CheckBack("返回图文指导");var navigation=(Button)Field(UnityEngine.Object.FindObjectOfType<AppShell>(),"back");Check(((RectTransform)navigation.transform).anchorMin.y>.9f,"Spatial return is not in the top toolbar");
  Canvas.ForceUpdateCanvases();var topNavigationBounds=new Vector3[4];((RectTransform)navigation.transform).GetWorldCorners(topNavigationBounds);
  foreach(var toolbarName in new[]{"摄像头管理","动画管理","空间锚点配置","官方图文指导"}){
   Button toolbarButton=null;foreach(var candidateButton in spatial.GetComponentsInChildren<Button>())if(candidateButton.gameObject.name==toolbarName)toolbarButton=candidateButton;
   Check(toolbarButton!=null,"Toolbar action missing: "+toolbarName);var toolbarBounds=new Vector3[4];((RectTransform)toolbarButton.transform).GetWorldCorners(toolbarBounds);
   Check(Mathf.Abs(toolbarBounds[0].y-topNavigationBounds[0].y)<1&&Mathf.Abs((toolbarBounds[2]-toolbarBounds[0]).x-(topNavigationBounds[2]-topNavigationBounds[0]).x)<1&&Mathf.Abs((toolbarBounds[2]-toolbarBounds[0]).y-(topNavigationBounds[2]-topNavigationBounds[0]).y)<1,"Top toolbar actions have different sizes or rows: "+toolbarName+" "+toolbarBounds[0]+" "+toolbarBounds[2]+" vs "+topNavigationBounds[0]+" "+topNavigationBounds[2]);
  }
  Check(!((Text)Field(spatial,"status")).gameObject.activeInHierarchy,"Redundant right-side status is still visible");var firstSpatial=(Manual2AR.Spatial.Reply)Field(spatial,"last");
  yield return Wait(()=>Field(spatial,"referenceTexture")!=null,"Official reference disappeared during session start");
  Check(((RawImage)Field(spatial,"reference")).transform.parent.name=="Reference viewport","Reference is not confined to its own viewport");
  var referencePhoto=(RawImage)Field(spatial,"reference");var photoTexture=referencePhoto.texture;
  Check(referencePhoto.raycastTarget&&referencePhoto.GetComponent<Button>()!=null,"Spatial reference photo cannot be clicked");
  referencePhoto.GetComponent<Button>().onClick.Invoke();yield return null;
  var photoViewer=UnityEngine.Object.FindObjectOfType<Manual2AR.Spatial.SpatialReferenceViewer>();Check(photoViewer!=null,"Enlarged reference did not open");
  var fullPhoto=photoViewer.GetComponentInChildren<RawImage>();Check(fullPhoto.texture==photoTexture,"Enlarged photo differs from displayed official reference");
  yield return Shot("spatial-reference-enlarged.png");
  Check(fullPhoto.rectTransform.rect.width>referencePhoto.rectTransform.rect.width,"Photo dialog did not enlarge the image");photoViewer.Close();yield return null;
  Check(referencePhoto.texture==photoTexture&&photoTexture!=null,"Closing reference dialog destroyed the lesson image");
  Check(!((Text)Field(spatial,"authorHelp")).text.Contains("首次空间使用"),"Removed calibration introduction is still visible");
  Check(firstSpatial.lines.Length==3&&firstSpatial.pose.matrix.Length==16,"Metric arrow/pose missing");
  Check(firstSpatial.visual!=null&&firstSpatial.visual.trajectory.Length==33,"Metric motion path missing");
  Check(!(bool)Field(spatial,"setupVisible"),"Setup controls are mixed into normal guidance");
  Check(((RectTransform)((RectTransform)Field(spatial,"viewport")).parent).anchorMin.y<.03f,"Camera did not expand into the removed footer area");
  var anchorControls=(Manual2AR.Spatial.SpatialActionBar)Field(spatial,"actionBar");
  anchorControls.Root.Find("空间锚点配置").GetComponent<Button>().onClick.Invoke();yield return null;
  Check(Field(spatial,"photoPrompt")!=null,"Anchor settings did not open");ClickText((GameObject)Field(spatial,"photoPrompt"),"相机及工作坐标设置");yield return null;
  var cancelSetup=(Button)Field(spatial,"cancel");Check(cancelSetup.interactable&&cancelSetup.gameObject.activeInHierarchy,"Cannot leave anchor configuration before choosing points");
  cancelSetup.onClick.Invoke();yield return null;
  Check(!(bool)Field(spatial,"setupVisible")&&anchorControls.Root.gameObject.activeSelf&&!(bool)Field(spatial,"setupExplicit"),"Cancel did not restore guidance controls");
  Check(!((bool)Field(spatial,"frozen")),"Cancel left camera frozen");
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
  var autoClock=(Manual2AR.Spatial.SpatialPlayback)Field(spatial,"playback");Check(autoClock.State=="playing","Spatial guide waits for a manual play button");
  float beforeAuto=autoClock.Progress;yield return new WaitForSecondsRealtime(.2f);Check(Mathf.Abs(autoClock.Progress-beforeAuto)>.02f,"Automatic animation is static");
  foreach(var button in spatial.GetComponentsInChildren<Button>()){string text=button.GetComponentInChildren<Text>()?.text.Replace(((char)0x200b).ToString(),"")??"";Check(text!="播放示意"&&text!="暂停"&&text!="重新播放"&&text!="模拟回放"&&text!="官方来源","Removed spatial control remains visible: "+text);}
  // Frozen-photo preview remains distinct from calibrated spatial guidance.
  var photoFrame=(Manual2AR.Spatial.Reply)Field(spatial,"last");
  var preview=new Manual2AR.Spatial.LocationPreview{status="found",session_id=photoFrame.session_id,action_id=photoFrame.action_id,target_id=photoFrame.target_id,source_sha256=photoFrame.source_sha256,client_frame_id=photoFrame.client_frame_id,width=photoFrame.width,height=photoFrame.height,box_lines=photoFrame.lines,outlines=new[]{new Manual2AR.Spatial.Outline{points=new[]{new Manual2AR.Spatial.Pixel(400,300),new Manual2AR.Spatial.Pixel(500,300),new Manual2AR.Spatial.Pixel(500,400)}}}};
  Check((bool)Invoke(spatial,"PresentLocation",preview,photoFrame,photoFrame.session_id),"Bound photo preview was rejected");
  Check((bool)Field(spatial,"frozen")&&(bool)Field(spatial,"locationPreview")&&!((Manual2AR.Spatial.SpatialPlayback)Field(spatial,"playback")).Available,"Photo preview leaked into metric playback");
  Check(((Text)Field(spatial,"modeLabel")).text.Contains("本次定位照片"),"Photo preview has no scope label");yield return Shot("integrated-04-photo-preview.png");
  preview.source_sha256="wrong-frame";Check(!(bool)Invoke(spatial,"PresentLocation",preview,photoFrame,photoFrame.session_id),"Wrong photo identity was accepted");
  spatial.StartCoroutine((IEnumerator)Invoke(spatial,"Locate"));yield return Wait(()=>!(bool)Field(spatial,"frozen"),"Returning to live view failed");
  yield return Shot("spatial-01-slide.png");Invoke(spatial,"Select",1);
  yield return Wait(()=>Field(spatial,"last")!=null&&((Manual2AR.Spatial.Reply)Field(spatial,"last")).lines.Length>20,"Fastening ring missing");
  yield return Shot("spatial-02-fasten.png");Invoke(spatial,"Select",4);
  yield return Wait(()=>Field(spatial,"last")!=null&&((Manual2AR.Spatial.Reply)Field(spatial,"last")).action_id=="holder.slide","U7 did not open");
  yield return Shot("spatial-03-holder.png");
  var holderGraphic=(Manual2AR.Spatial.SpatialAssetGraphic)Field(spatial,"assetGraphic");
  Check(holderGraphic.VisibleTriangles>0&&holderGraphic.AssetProvenance=="manual2ar-library-v1/u7.holder_slide","U7 library presentation missing");
  yield return Shot("u7-01-slide-animation.png");
  var librarySlide=((Manual2AR.Spatial.Reply)Field(spatial,"last")).visual.presentation;
  Check(Manual2AR.VisualGuidance.VisualAssetLibrary.Validate(librarySlide)&&librarySlide.instances.Length==3,"U7 compositional scene invalid");
  var librarySampler=new Manual2AR.VisualGuidance.VisualSceneSampler();
  var atStart=librarySampler.Sample(librarySlide,.08f);var initialVertex=atStart[0].Vertices[0];
  var atEnd=librarySampler.Sample(librarySlide,.82f);
  var declaredPath=Manual2AR.VisualGuidance.VisualAssetLibrary.Vector(librarySlide.instances[0].path_m);
  Check(Vector3.Distance(atEnd[0].Vertices[0]-initialVertex,declaredPath)<.00001f,"U7 holder animation does not follow authored metric path");
  var worldObject=new GameObject("Native visual adapter validation");worldObject.transform.position=new Vector3(.7f,.2f,.1f);
  var worldRenderer=worldObject.AddComponent<Manual2AR.VisualGuidance.VisualWorldRenderer>();
  var worldFrame=new Manual2AR.VisualGuidance.VisualRenderFrame{HasWorldPlacement=true,ReferenceSpaceId="calibrated-marker",UnityWorldFromReference=Matrix4x4.Translate(new Vector3(.1f,.2f,.3f))};
  worldRenderer.Present(librarySlide,worldFrame,.82f);Check(worldRenderer.ActiveParts==atEnd.Count,"Native adapter does not share sampled parts");
  var firstMesh=worldObject.GetComponentInChildren<MeshFilter>();var point=atEnd[0].Vertices[0];var expectedWorld=worldFrame.UnityWorldFromReference.MultiplyPoint3x4(new Vector3(point.x,point.y,-point.z));
  Check(Vector3.Distance(firstMesh.transform.TransformPoint(firstMesh.sharedMesh.vertices[0]),expectedWorld)<.00001f,"Native reference-space handedness differs from desktop sampler");
  worldFrame.ReferenceSpaceId="unregistered-ar-world";worldRenderer.Present(librarySlide,worldFrame,.82f);Check(worldRenderer.ActiveParts==0,"Native adapter accepted an unregistered reference space");UnityEngine.Object.Destroy(worldObject);
  var badLibrary=JsonUtility.FromJson<Manual2AR.VisualGuidance.VisualPresentation>(JsonUtility.ToJson(librarySlide));badLibrary.catalog_sha256=new string('0',64);
  Check(!Manual2AR.VisualGuidance.VisualAssetLibrary.Validate(badLibrary),"Mismatched asset pack was accepted");

  Invoke(spatial,"Select",3);yield return Wait(()=>Field(spatial,"last")!=null&&((Manual2AR.Spatial.Reply)Field(spatial,"last")).action_id=="holder.base","Base screws did not open");
  Check(spatial.GetComponentsInChildren<Dropdown>().Length==0,"Teaching view still contains step/target selectors");
  var bothScrews=(Manual2AR.Spatial.Reply)Field(spatial,"last");Check(bothScrews.companion_visuals.Length==1,"Second screw overlay missing");Invoke(spatial,"SelectTarget",1);
  yield return Wait(()=>Field(spatial,"last")!=null&&((Manual2AR.Spatial.Reply)Field(spatial,"last")).target_id=="second","Second screw kept first screw geometry");
  Check(((Manual2AR.Spatial.Reply)Field(spatial,"last")).visual.label=="底座螺丝 2","Second screw label mismatch");Invoke(spatial,"MarkOperation");yield return Shot("spatial-04-second-screw.png");
  Check(holderGraphic.VisibleTriangles>30&&holderGraphic.AssetProvenance=="manual2ar-library-v1/u7.holder_base","U7 library tool missing");
  Check(((Manual2AR.Spatial.Reply)Field(spatial,"last")).visual.asset.motion=="tighten","U7 uses removal direction");
  Check(((Manual2AR.Spatial.SpatialTextRenderer)Field(spatial,"textRenderer")).ContextCount==1,"U7 context missing or duplicated for two screws");
  var sceneLegend=(Manual2AR.Spatial.SpatialLegend)Field(spatial,"legend");var legendBefore=sceneLegend.Root.anchoredPosition;
  Canvas.ForceUpdateCanvases();int legendMeshes=0;foreach(var thumbnail in sceneLegend.Root.GetComponentsInChildren<Manual2AR.VisualGuidance.VisualLegendIcon>())if(thumbnail.Item.kind=="model"){Check(thumbnail.VisibleTriangles>0,"Legend has no actual 3D model thumbnail");legendMeshes++;}
  bool coloredLegend=false;foreach(var legendLabel in sceneLegend.Root.GetComponentsInChildren<Text>())coloredLegend|=legendLabel.color!=Color.white;Check(coloredLegend,"Legend component colors missing");
  Check(legendMeshes>=2&&sceneLegend.Root.anchorMin==new Vector2(0,1),"Legend is not fixed at the top left");
  yield return null;Check(sceneLegend.Root.anchoredPosition==legendBefore,"Legend moved with a scene target");
  Check(((Manual2AR.Spatial.SpatialTextRenderer)Field(spatial,"textRenderer")).VisibleCount==1,"Scene still repeats component names or check verdicts");

  bool showsContext=false;foreach(var sceneText in spatial.GetComponentsInChildren<Text>())showsContext|=Plain(sceneText.text).Contains("用内六角扳手拧紧");
  bool coloredDirective=false;foreach(var directive in spatial.GetComponentsInChildren<Text>())coloredDirective|=directive.supportRichText&&directive.text.Contains("<color=#");Check(coloredDirective,"Anchored instruction does not share component colors");
  Check(showsContext,"Scene imperative did not show tool, action and object");
  Canvas.ForceUpdateCanvases();foreach(var sceneContext in spatial.GetComponentsInChildren<Text>())if(Plain(sceneContext.text).Contains("用内六角扳手拧紧"))Check(sceneContext.preferredHeight<=sceneContext.rectTransform.rect.height+1,"Context state line is clipped by CJK line height");
  yield return Shot("u7-context-information.png");
  string readySource=((Text)Field(spatial,"authorHelp")).GetComponent<AppReadableText>().Source;
  Check(!((Text)Field(spatial,"title")).gameObject.activeSelf&&!((Text)Field(spatial,"modeLabel")).gameObject.activeSelf,"Spatial debug header remains visible");
  Check(((Manual2AR.Spatial.SpatialTextRenderer)Field(spatial,"textRenderer")).VisibleCount>0,"Metric text annotations missing");
  foreach(var text in spatial.GetComponentsInChildren<Text>())Check(!text.text.Contains("我已操作"),"Manual completion remains in spatial guidance");
  Invoke(spatial,"ShowStepIntroduction",false);yield return Shot("flow-01-official-introduction.png");Invoke(spatial,"ClosePhotoPrompt");
  yield return Shot("u7-02-base-tighten.png");
  var axisReply=(Manual2AR.Spatial.Reply)Field(spatial,"last");Check(axisReply.visual.axes.Length==3,"Operation XYZ axes missing");
  Invoke(spatial,"ShowCameraSettings");Check(Field(spatial,"aspectSelector")!=null&&(int)Field(spatial,"aspectIndex")==4,"Camera management/framing missing");yield return Shot("u7-camera-management.png");Invoke(spatial,"ClosePhotoPrompt");
  Invoke(spatial,"ShowLocateCapture");yield return Shot("u7-04-two-part-photo-guidance.png");Check(Field(spatial,"photoPrompt")!=null,"Two-part photo guidance did not open");Invoke(spatial,"ClosePhotoPrompt");
  Invoke(spatial,"ShowCompleted");yield return Shot("u7-05-installation-complete.png");Invoke(spatial,"ClosePhotoPrompt");
  var orientPanel=Manual2AR.Spatial.SpatialOrientationPanel.Open((RectTransform)Field(spatial,"root"),new Manual2AR.Spatial.Orientation(),value=>{});yield return Shot("u7-06-xyz-orientation.png");UnityEngine.Object.Destroy(orientPanel);yield return null;
  // Positive rotation about the tool's +Y working axis must look clockwise from the handle.
  var rotating=JsonUtility.FromJson<Manual2AR.VisualGuidance.VisualPresentation>(JsonUtility.ToJson(axisReply.visual.presentation));
  foreach(var item in rotating.instances)item.reference_from_asset=new float[]{1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1};
  var rotationSampler=new Manual2AR.VisualGuidance.VisualSceneSampler();var ringStart=rotationSampler.Sample(rotating,0);Vector3 ring0=Vector3.zero;int ringIndex=-1;
  for(int i=0;i<ringStart.Count;i++)if(ringStart[i].AssetId=="motion.turn_arrow"){ringIndex=i;ring0=ringStart[i].Vertices[0];break;}
  Check(ringIndex>=0,"Rotation arrow geometry missing");var ring1=rotationSampler.Sample(rotating,.65f)[ringIndex].Vertices[0];
  Check(ring0.x*(-ring1.z)-(-ring0.z)*ring1.x>0,"Tightening animation is counterclockwise from the handle");
  foreach(var item in rotating.instances)item.rotation_scale=.5f;
  var half=rotationSampler.Sample(rotating,.65f)[ringIndex].Vertices[0];
  var from=new Vector2(ring0.x,-ring0.z);var to=new Vector2(half.x,-half.z);Check(Mathf.Abs(Vector2.Angle(from,to)-180)<.01f,"Parameterized rotation angle was ignored");
  // Arrowhead must indicate the same direction as the actual angular velocity for either sign.
  foreach(int sign in new[]{1,-1}){
   foreach(var item in rotating.instances){item.rotation_sign=sign;item.rotation_scale=1;}
   var sample=rotationSampler.Sample(rotating,0);var head=sample[ringIndex+1];
   var tip=head.Vertices[0];var tail=(head.Vertices[1]+head.Vertices[2])*.5f;
   Check(Vector3.Dot(tip-tail,Vector3.Cross(Vector3.up,(tip+tail)*.5f)*sign)>0,"Arrowhead contradicts rotation direction "+sign);
  }
  foreach(var item in rotating.instances){item.rotation_sign=1;item.speed=.5f;}
  var slow=rotationSampler.Sample(rotating,1.1f)[ringIndex].Vertices[0];
  Check((slow-Quaternion.AngleAxis(360*.55f/.65f,Vector3.up)*ring0).magnitude<1e-5f,"Slow component reset at the global cycle boundary");
  foreach(var item in rotating.instances){item.visible=true;item.playing=false;}
  var static0=rotationSampler.Sample(rotating,0)[ringIndex].Vertices[0];var static1=rotationSampler.Sample(rotating,.3f)[ringIndex].Vertices[0];
  Check((static1-static0).magnitude<1e-6f,"Static component continued animating");
  foreach(var item in rotating.instances){item.playing=true;item.speed=1;}
  Check(rotationSampler.Sample(rotating,.90f)[ringIndex].Color.a<.01f,"Screw stroke did not disappear before restarting");
  Check(rotationSampler.Sample(rotating,1.01f)[ringIndex].Color.a>.9f,"Screw stroke did not reappear after reset");
  var occupiedLabels=new System.Collections.Generic.List<Rect>();var viewSize=new Vector2(1000,700);var labelSize=new Vector2(240,45);
  var labelA=Manual2AR.Spatial.SpatialLabelLayout.Place(new Vector2(400,300),labelSize,viewSize,occupiedLabels);
  var labelB=Manual2AR.Spatial.SpatialLabelLayout.Place(new Vector2(400,300),labelSize,viewSize,occupiedLabels);
  Check(!new Rect(labelA,labelSize).Overlaps(new Rect(labelB,labelSize)),"Nearby labels overlap");
  rotating.instances[1].visible=false;Check(rotationSampler.Sample(rotating,0)[ringIndex].Color.a==0,"Hidden component remained visible");
  var actionPanel=Manual2AR.Spatial.SpatialActionPanel.Open((RectTransform)Field(spatial,"root"),new Manual2AR.Spatial.MotionParameters(),axisReply.visual.presentation,true,true,value=>{},()=>{});
  Check(actionPanel.GetComponentsInChildren<Dropdown>().Length==2,"Component action selectors missing");yield return Shot("actions-01-components.png");UnityEngine.Object.Destroy(actionPanel);yield return null;
  // Unity maps JSON null nested objects to empty instances: this caused the camera-only blank modal.
  var emptyReply=JsonUtility.FromJson<Manual2AR.Spatial.Reply>("{\"visual\":null,\"motion_parameters\":null}");
  var lastBefore=Field(spatial,"last");spatial.GetType().GetField("last",BindingFlags.NonPublic|BindingFlags.Instance).SetValue(spatial,emptyReply);
  Invoke(spatial,"ShowMotionSettings");Check(GameObject.Find("Action management")==null,"Unready camera opened an action blocker");
  spatial.GetType().GetField("last",BindingFlags.NonPublic|BindingFlags.Instance).SetValue(spatial,lastBefore);
  var emptyPanel=Manual2AR.Spatial.SpatialActionPanel.Open((RectTransform)Field(spatial,"root"),null,new Manual2AR.VisualGuidance.VisualPresentation(),true,false,value=>{},()=>{});
  Button closeEmpty=null;foreach(var button in emptyPanel.GetComponentsInChildren<Button>())if(button.gameObject.name=="关闭")closeEmpty=button;
  Check(closeEmpty!=null,"Empty action panel has no exit");yield return Shot("actions-02-not-ready.png");closeEmpty.onClick.Invoke();yield return null;Check(emptyPanel==null,"Empty panel did not close");
  var firstInstance=axisReply.visual.presentation.instances[0];
  var oldMotion=new Manual2AR.Spatial.MotionParameters{components=new[]{null,new Manual2AR.Spatial.ComponentMotion{id=firstInstance.id,rotation_degrees=null,offset_mm=null}}};
  var repairedPanel=Manual2AR.Spatial.SpatialActionPanel.Open((RectTransform)Field(spatial,"root"),oldMotion,axisReply.visual.presentation,true,true,value=>{},()=>{});
  Check(repairedPanel.GetComponentsInChildren<Slider>().Length==3,"Legacy component axes did not get valid defaults");
  repairedPanel.GetComponent<AppDialog>().Close();yield return null;Check(repairedPanel==null,"Action escape did not release the blocker");
  var captions=(Manual2AR.Spatial.SpatialFeedbackView)Field(spatial,"visionFeedback");
  var textRoot=((Text)Field(spatial,"stepHeader")).transform.parent.GetComponent<RectTransform>();
  Check(textRoot.GetComponentsInChildren<Image>().Length==0&&textRoot.sizeDelta.y<=70,"Teaching hints still use large panels");
  Check(!((Text)Field(spatial,"stepHeader")).gameObject.activeInHierarchy,"Step name is still drawn in the camera scene");
  Check(!((Text)Field(spatial,"stepHeader")).text.Contains("/"),"Step title still repeats fraction progress");
  Check(((Text)Field(spatial,"stepHeader")).fontSize>=24&&((Text)Field(spatial,"stepHeader")).GetComponent<UnityEngine.UI.Outline>()!=null,"Step text lacks legible size and dark outline");
  var markerCaptionFrame=new Manual2AR.Spatial.Reply{width=960,height=720,pose=new Manual2AR.Spatial.Pose{corners=new[]{new Manual2AR.Spatial.Pixel(100,100),new Manual2AR.Spatial.Pixel(140,100),new Manual2AR.Spatial.Pixel(140,140),new Manual2AR.Spatial.Pixel(100,140)}}};
  captions.Place(markerCaptionFrame);var captionPosition=textRoot.anchoredPosition;Check(captions.MarkerAttached,"Hint did not attach to marker");
  foreach(var markerCorner in markerCaptionFrame.pose.corners)markerCorner.x+=60;
  captions.Place(markerCaptionFrame);Check((captionPosition-textRoot.anchoredPosition).magnitude>10,"Hint failed to follow marker motion");
  captions.Place(new Manual2AR.Spatial.Reply{width=960,height=720});Check(!captions.MarkerAttached,"Lost marker retained a stale caption anchor");
  yield return Shot("u7-frameless-marker-hints.png");
  var worldTextObject=new GameObject("World text adapter test");var worldText=worldTextObject.AddComponent<Manual2AR.VisualGuidance.VisualWorldTextRenderer>();
  var worldTextFrame=new Manual2AR.VisualGuidance.VisualRenderFrame{ReferenceSpaceId="calibrated-marker",HasWorldPlacement=true,UnityWorldFromReference=Matrix4x4.identity};worldText.PresentDisplay(axisReply.visual.display,worldTextFrame,Camera.main);Check(worldText.VisibleCount>0,"Registered world text did not render");bool imperativeWorld=false;foreach(var anchoredText in worldText.GetComponentsInChildren<Text>())imperativeWorld|=Plain(anchoredText.text).Contains("用内六角扳手拧紧")&&!Plain(anchoredText.text).Contains("检查通过");
  Check(imperativeWorld,"AR adapter did not preserve the imperative-only display contract");
  worldTextFrame.HasWorldPlacement=false;worldText.PresentDisplay(axisReply.visual.display,worldTextFrame,Camera.main);Check(worldText.VisibleCount==0,"Unregistered world text remained visible");UnityEngine.Object.Destroy(worldTextObject);yield return null;
  var motionPanel=Manual2AR.Spatial.SpatialMotionPanel.Open((RectTransform)Field(spatial,"root"),new Manual2AR.Spatial.MotionParameters{axis="Z",direction=-1,distance_mm=60},false,true,value=>{},()=>{});yield return Shot("machine-01-motion-parameters.png");UnityEngine.Object.Destroy(motionPanel);yield return null;

  // Exercise the same three-point wizard against a synthetic session; never open physical hardware.
  Invoke(spatial,"OpenMachineIntro");yield return Shot("machine-02-coordinate-intro.png");
  var coordinatePrompt=(GameObject)Field(spatial,"photoPrompt");Check(coordinatePrompt!=null,"Coordinate introduction missing");Button startCoordinate=null;
  foreach(var button in coordinatePrompt.GetComponentsInChildren<Button>())if((button.GetComponentInChildren<Text>()?.text??"").Replace(((char)0x200b).ToString(),"").Contains("固定第一视角"))startCoordinate=button;
  Check(startCoordinate!=null,"Coordinate wizard start button missing");startCoordinate.onClick.Invoke();yield return Wait(()=>(int)Field(spatial,"authorStage")==1&&!(bool)Field(spatial,"authorBusy"),"First coordinate photo was not pinned");
  var coordinateOverlay=(Manual2AR.Spatial.SpatialOverlay)Field(spatial,"overlay");Check(coordinateOverlay.MaximumPicks==3,"Coordinate wizard still accepts only two points");Canvas.ForceUpdateCanvases();
  var coordinateRect=coordinateOverlay.rectTransform;var coordinateBounds=coordinateRect.rect;
  foreach(float u in new[]{.3f,.5f,.7f}){var screen=RectTransformUtility.WorldToScreenPoint(null,coordinateRect.TransformPoint(new Vector3(coordinateBounds.xMin+coordinateBounds.width*u,coordinateBounds.yMin+coordinateBounds.height*u,0)));coordinateOverlay.OnPointerClick(new UnityEngine.EventSystems.PointerEventData(UnityEngine.EventSystems.EventSystem.current){position=screen});}
  Check(coordinateOverlay.picks.Count==3,"Third coordinate point could not be selected");yield return Shot("machine-03-three-point-authoring.png");
  Invoke(spatial,"CancelAuthor");Check(coordinateOverlay.MaximumPicks==2&&!(bool)Field(spatial,"authorMachine"),"Cancelling coordinate setup leaked into target authoring");
  yield return Wait(()=>((Manual2AR.Spatial.SpatialPlayback)Field(spatial,"playback")).Available,"Animation did not resume after coordinate cancellation");
  spatial.GetType().GetField("frozen",BindingFlags.Instance|BindingFlags.NonPublic).SetValue(spatial,true);yield return null;
  var partsReply=(Manual2AR.Spatial.Reply)Field(spatial,"latestReply");var partsBytes=(byte[])Field(spatial,"latestBytes");
  var matchedParts=new Manual2AR.Spatial.PartStatus{session_id=partsReply.session_id,job_id="controlled-parts",phase="tracking",source_sha256=partsReply.source_sha256,client_frame_id=partsReply.client_frame_id,
   parts=new[]{new Manual2AR.Spatial.LocatedPart{component_id="spool_holder_base",status="found",bbox_0_1000=new[]{200,220,290,400}},new Manual2AR.Spatial.LocatedPart{component_id="external_spool_holder",status="found",bbox_0_1000=new[]{450,400,800,720},proxy=new Manual2AR.Spatial.ImageProxy{asset_id="part.spool_holder_proxy",coordinate_space="image_proxy",bbox_0_1000=new[]{450,400,800,720},angle_degrees=25,illustrative_only=true}}}};
  var maskTexture=new Texture2D(partsReply.width,partsReply.height,TextureFormat.RGBA32,false);var maskPixels=new Color32[partsReply.width*partsReply.height];
  for(int py=0;py<partsReply.height;py++)for(int px=0;px<partsReply.width;px++)if(px>partsReply.width*.45f&&px<partsReply.width*.8f&&py>partsReply.height*.28f&&py<partsReply.height*.6f)maskPixels[py*partsReply.width+px]=new Color32(20,210,240,75);
  maskTexture.SetPixels32(maskPixels);maskTexture.Apply();matchedParts.overlay_png_base64=Convert.ToBase64String(maskTexture.EncodeToPNG());UnityEngine.Object.Destroy(maskTexture);
  spatial.GetType().GetField("partsDisplayActive",BindingFlags.Instance|BindingFlags.NonPublic).SetValue(spatial,true);
  Check((bool)Invoke(spatial,"PresentTrackedParts",partsBytes,partsReply,matchedParts,partsReply.session_id,"controlled-parts"),"Matching tracked frame rejected");yield return Shot("u7-07-image-holder-proxy.png");
  Check(holderGraphic.VisibleTriangles>30&&((Manual2AR.Spatial.SpatialOverlay)Field(spatial,"overlay")).visual!=null&&((Manual2AR.Spatial.SpatialPlayback)Field(spatial,"playback")).Available,"Part view hid the 3D animation");
  var guideViewport=(RectTransform)Field(spatial,"viewport");Check(guideViewport.Find("Part label 0")==null,"Tracked part names remain outside the fixed legend");
  var imageProxy=UnityEngine.Object.FindObjectOfType<Manual2AR.VisualGuidance.VisualImageProxyGraphic>();Check(imageProxy!=null&&imageProxy.VisibleTriangles>0,"Tracked holder proxy did not render");
  matchedParts.source_sha256="wrong-frame";Check(!(bool)Invoke(spatial,"PresentTrackedParts",partsBytes,partsReply,matchedParts,partsReply.session_id,"controlled-parts"),"Delayed masks accepted over a different camera frame");
  Invoke(spatial,"StopParts");yield return Wait(()=>Field(spatial,"last")!=null&&((Manual2AR.Spatial.Reply)Field(spatial,"last")).visual!=null,"Returning from part tracking failed");
  var pickingOverlay=(Manual2AR.Spatial.SpatialOverlay)Field(spatial,"overlay");
  pickingOverlay.accepting=true;pickingOverlay.picks.Clear();pickingOverlay.picks.Add(new Manual2AR.Spatial.Pixel(320,250));pickingOverlay.picks.Add(new Manual2AR.Spatial.Pixel(360,330));
  Invoke(spatial,"RefreshCallout");yield return Shot("u7-03-setup-point-names.png");
  bool outer=false,centre=false;foreach(var label in pickingOverlay.GetComponentsInChildren<Text>()){string plain=label.text.Replace(((char)0x200b).ToString(),"");outer|=plain.Contains("扳手长杆外端");centre|=plain.Contains("当前螺丝中心");}
  Check(outer&&centre,"U7 setup point labels are missing");pickingOverlay.accepting=false;pickingOverlay.picks.Clear();Invoke(spatial,"RefreshCallout");
  Invoke(spatial,"SelectChapter","U4");yield return Wait(()=>Field(spatial,"last")!=null&&((Manual2AR.Spatial.Reply)Field(spatial,"last")).action_id=="zlock.remove","U4 chapter navigation failed");
  Check(Array.Find(spatialPlan.actions,a=>a.action_id=="zlock.remove").target_instances.Length==4,"Z lock target definitions missing");
  Invoke(spatial,"SelectTarget",3);yield return Wait(()=>Field(spatial,"last")!=null&&((Manual2AR.Spatial.Reply)Field(spatial,"last")).target_id=="fourth","Fourth transport screw missing");yield return Shot("extension-01-zlock.png");
  var assetGraphic=(Manual2AR.Spatial.SpatialAssetGraphic)Field(spatial,"assetGraphic");
  var legacyVisual=JsonUtility.FromJson<Manual2AR.Spatial.GuidanceVisual>("{\"kind\":\"slide\",\"asset\":null,\"projection\":null}");
  Check(!Manual2AR.Spatial.SpatialAssetGraphic.HasPlacement(legacyVisual),"Legacy JSON null became an active mesh placement");
  Check(assetGraphic.VisibleTriangles>30,"Hex key model did not render");Check(assetGraphic.AssetProvenance=="manual2ar-procedural-hex-v1","Wrong screw tool model");
  var screwVisual=((Manual2AR.Spatial.Reply)Field(spatial,"last")).visual;Check(screwVisual.asset.motion=="loosen","Transport screws use tightening motion");
  var modelTip=Manual2AR.Spatial.SpatialAssetGraphic.Transform(screwVisual.asset.marker_from_asset,Vector3.zero);Vector2 tipPixel;float tipDepth;
  Check(Manual2AR.Spatial.SpatialAssetGraphic.Project(screwVisual.projection,modelTip,out tipPixel,out tipDepth)&&Vector2.Distance(tipPixel,new Vector2(screwVisual.anchor.x,screwVisual.anchor.y))<.1f,"Tool tip is detached from selected screw");
  yield return Shot("u4-01-hex-animation.png");
  Invoke(spatial,"Select",Array.FindIndex(spatialPlan.actions,a=>a.action_id=="toolhead.tie"));yield return Wait(()=>Field(spatial,"last")!=null&&((Manual2AR.Spatial.Reply)Field(spatial,"last")).visual!=null&&((Manual2AR.Spatial.Reply)Field(spatial,"last")).visual.kind=="cut","Tie reference missing");
  Check(((Manual2AR.Spatial.Reply)Field(spatial,"last")).visual.tool_lines.Length==2,"Cut reference geometry missing");yield return Shot("extension-02-tie.png");
  Check(assetGraphic.VisibleTriangles>50&&assetGraphic.AssetProvenance=="manual2ar-procedural-scissors-v1","Scissors did not render");
  yield return Shot("u4-02-scissors-animation.png");
  Invoke(spatial,"Select",Array.FindIndex(spatialPlan.actions,a=>a.action_id=="toolhead.slide"));yield return Wait(()=>Field(spatial,"last")!=null&&((Manual2AR.Spatial.Reply)Field(spatial,"last")).action_id=="toolhead.slide","Toolhead slide missing");
  yield return Shot("u4-03-arrow-start.png");Check(assetGraphic.VisibleTriangles>0&&assetGraphic.AssetProvenance=="guided-reality-478d9d7-downArrow-local","Reviewed local arrow model was not used");
  yield return Shot("u4-04-arrow-moving.png");
  var projection=new Manual2AR.Spatial.SpatialProjection{camera_from_marker=new float[]{1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1},intrinsics=new float[]{900,0,480,0,900,360,0,0,1},distortion=new float[]{.1f,-.02f,.003f,.004f,0}};
  Vector2 distorted;float depth;Check(Manual2AR.Spatial.SpatialAssetGraphic.Project(projection,new Vector3(.1f,.05f,.5f),out distorted,out depth)&&Vector2.Distance(distorted,new Vector2(661.467f,450.7785f))<.001f,"Mesh projection differs from OpenCV lens distortion");
  Check(!Manual2AR.Spatial.SpatialAssetGraphic.Project(projection,new Vector3(0,0,-1),out distorted,out depth),"Behind-camera model was projected");
  Invoke(spatial,"Select",Array.FindIndex(spatialPlan.actions,a=>a.action_id=="packing.foam"));yield return Wait(()=>Field(spatial,"last")!=null&&((Manual2AR.Spatial.Reply)Field(spatial,"last")).visual!=null&&((Manual2AR.Spatial.Reply)Field(spatial,"last")).visual.kind=="highlight","Foam highlight missing");
  Check(Array.Find(spatialPlan.actions,a=>a.action_id=="packing.foam").target_instances.Length==3,"Optional foam positions missing");
  yield return Shot("u4-05-foam-highlight.png");Check(assetGraphic.VisibleTriangles==0,"Previous tool leaked into foam action");
  Invoke(spatial,"SelectChapter","U5");yield return Wait(()=>Field(spatial,"last")!=null&&((Manual2AR.Spatial.Reply)Field(spatial,"last")).action_id=="bed.tighten","U5 chapter navigation failed");
  Check(Array.Find(spatialPlan.actions,a=>a.action_id=="bed.tighten").target_instances.Length==3,"Bed needs three screw definitions");Check(((Button)Field(spatial,"verify")).GetComponentInChildren<Text>().text=="确认完成","Bed tightening should not be a VLM check");
  spatial.StartCoroutine((IEnumerator)Invoke(spatial,"Verify"));yield return null;Check(((Text)Field(spatial,"checkResult")).text.Contains("人工确认"),"Manual confirmation not shown");yield return Shot("extension-03-bed.png");
  AppShell.GoBack();yield return Wait(()=>UnityEngine.Object.FindObjectOfType<Manual2AR.Spatial.SpatialGuidanceController>()==null,"Spatial view did not release");
  Check(((RectTransform)Field(guidance,"root")).gameObject.activeSelf,"Tutorial did not resume");
  yield return Wait(()=>((GuidanceRun)Field(guidance,"run")).state_id=="U5","Spatial return did not follow official chapter");
  var resumed=(GuidanceRun)Field(guidance,"run");
  Check(resumed.user_marked_step_ids.Length==1&&Array.IndexOf(resumed.user_marked_step_ids,"U1")>=0,"Spatial replay changed tutorial operation marks");
  Check(resumed.spatial_guidance.learning_records.Length>0,"Spatial learning records were not attached to tutorial");
  foreach(var record in resumed.spatial_guidance.learning_records)Check(!record.operation_verified,"Replay was reported as verified");
  Invoke(guidance,"ShowOverview",false);yield return Shot("integrated-01-coverage.png");Invoke(guidance,"CloseModal");
  guidance.StartCoroutine((IEnumerator)Invoke(guidance,"BrowseStep","U7","U7-S1"));
  yield return Wait(()=>((GuidanceRun)Field(guidance,"run")).state_id=="U7"&&!(bool)Field(guidance,"busy"),"U7 base page missing");
  var gatedU7=(GuidanceRun)Field(guidance,"run");Check(gatedU7.u7_sequence!=null&&!gatedU7.u7_sequence.base_approved&&gatedU7.substeps[1].locked,"U7 second step is not locked before base verification");yield return Shot("u7-sequence-01-locked.png");
  GuidanceRun approvedU7=null;yield return Call(origin+"/api/guidance/runs/"+gatedU7.run_id+"/verify","POST",JsonUtility.ToJson(new UnboxingCapture{state_id="U7",revision=gatedU7.revision,inspection_id=gatedU7.pending_id,client_frame_id=Mathf.Max(0,gatedU7.last_client_frame_id)+1,image_base64=Convert.ToBase64String(bytes),source_sha256=Hash(bytes)}),raw=>approvedU7=JsonUtility.FromJson<GuidanceRun>(raw));
  Check(approvedU7.u7_sequence.base_approved&&!approvedU7.substeps[1].locked,"A valid base check did not unlock the second step");Invoke(guidance,"Apply",approvedU7);yield return Shot("u7-sequence-02-unlocked.png");
  guidance.StartCoroutine((IEnumerator)Invoke(guidance,"BrowseStep","U7","U7-S2"));
  yield return Wait(()=>((GuidanceRun)Field(guidance,"run")).selected_substep_id=="U7-S2"&&!(bool)Field(guidance,"busy"),"Substep selection failed");
  var substepSelect=((RectTransform)Field(guidance,"substepTabs")).GetComponentInChildren<Dropdown>();Check(substepSelect!=null&&substepSelect.options.Count==2,"Official substeps are not an adaptive dropdown");
  Check(substepSelect.options[1].text.Contains("从上向下"),"Substep selector shows an empty numbered heading");
  substepSelect.Show();yield return Shot("integrated-02-substep-menu.png");substepSelect.Hide();Invoke(guidance,"OpenSpatial");
  spatial=UnityEngine.Object.FindObjectOfType<Manual2AR.Spatial.SpatialGuidanceController>();yield return Wait(()=>Field(spatial,"plan")!=null,"Contextual spatial view missing");
  Check(((Manual2AR.Spatial.Plan)Field(spatial,"plan")).actions[(int)Field(spatial,"actionIndex")].action_id=="holder.slide","Substep opened the wrong spatial action");
  spatial.StartCoroutine((IEnumerator)Invoke(spatial,"BeginSession","replay",false));yield return Wait(()=>Field(spatial,"last")!=null&&((Manual2AR.Spatial.Reply)Field(spatial,"last")).target_ready,"Reopened spatial replay missing");
  yield return Shot("integrated-03-guidance.png");AppShell.GoBack();
  yield return Wait(()=>UnityEngine.Object.FindObjectOfType<Manual2AR.Spatial.SpatialGuidanceController>()==null,"Contextual spatial view did not close");
  yield return Wait(()=>((RectTransform)Field(guidance,"root")).gameObject.activeSelf&&!(bool)Field(guidance,"busy"),"Official tutorial did not resume");
  // Full real-provider protocol, synthetic camera bytes and local fake VLM/GPU only.
  guidance.StartCoroutine((IEnumerator)Invoke(guidance,"BrowseStep","U7","U7-S1"));yield return Wait(()=>!(bool)Field(guidance,"busy")&&((GuidanceRun)Field(guidance,"run")).selected_substep_id=="U7-S1","Base reset page missing");
  var resetRun=(GuidanceRun)Field(guidance,"run");GuidanceRun resetResult=null;yield return Call(origin+"/api/guidance/runs/"+resetRun.run_id+"/recheck","POST",JsonUtility.ToJson(new UnboxingCommand{state_id="U7",revision=resetRun.revision}),raw=>resetResult=JsonUtility.FromJson<GuidanceRun>(raw));Invoke(guidance,"Apply",resetResult);Invoke(guidance,"CloseModal");Invoke(guidance,"OpenSpatial");
  spatial=UnityEngine.Object.FindObjectOfType<Manual2AR.Spatial.SpatialGuidanceController>();yield return Wait(()=>Field(spatial,"plan")!=null,"Automatic U7 view missing");
  byte[] controlledBytes=null;using(var get=UnityWebRequest.Get(origin+"/api/guidance/spatial/replay/30.jpg")){yield return get.SendWebRequest();controlledBytes=get.downloadHandler.data;}
  var controlledSource=new ControlledFrameSource(controlledBytes);spatial.GetType().GetField("frameSource",BindingFlags.Instance|BindingFlags.NonPublic).SetValue(spatial,controlledSource);
  yield return Call(origin+"/test/spatial/seed","POST","{\"camera_id\":\""+Hash(Encoding.UTF8.GetBytes(controlledSource.Signature)).Substring(0,24)+"\"}",raw=>{});
  spatial.StartCoroutine((IEnumerator)Invoke(spatial,"BeginSession","camera",false));yield return Wait(()=>Field(spatial,"last")!=null&&((Manual2AR.Spatial.Reply)Field(spatial,"last")).preflight.can_start,"Preflight did not locate cached anchor");
  Check(!((Manual2AR.Spatial.SpatialLegend)Field(spatial,"legend")).Root.gameObject.activeSelf,"Legend appears before teaching content is ready");
  Check(!((Manual2AR.Spatial.SpatialPlayback)Field(spatial,"playback")).Available,"Animation started before user preparation confirmation");yield return Shot("flow-02-positioned-start.png");
  ((Button)Field(spatial,"startAtTarget")).onClick.Invoke();yield return Wait(()=>Field(spatial,"photoPrompt")!=null,"Step introduction did not open");ClickText((GameObject)Field(spatial,"photoPrompt"),"开始指导");
  yield return Wait(()=>(bool)Field(spatial,"partsDisplayActive")&&!(bool)Field(spatial,"locating"),"Automatic base recognition did not finish");
  Check(((Manual2AR.Spatial.SpatialPlayback)Field(spatial,"playback")).Available,"Recognized base did not start animation");
  var readyFlag=spatial.GetType().GetField("semanticReady",BindingFlags.Instance|BindingFlags.NonPublic);readyFlag.SetValue(spatial,false);Invoke(spatial,"RenderFrame",Field(spatial,"latestBytes"),Field(spatial,"latestReply"));
  Check(!((Manual2AR.Spatial.SpatialPlayback)Field(spatial,"playback")).Available,"VLM-only boxes enabled animation before segmentation");
  readyFlag.SetValue(spatial,true);Invoke(spatial,"RenderFrame",Field(spatial,"latestBytes"),Field(spatial,"latestReply"));yield return Shot("flow-03-base-guidance.png");
  ((Button)Field(spatial,"verify")).onClick.Invoke();yield return Wait(()=>!(bool)Field(spatial,"checking")&&Field(spatial,"photoPrompt")!=null,"Base verification did not show confirmation");
  Check(((Manual2AR.Spatial.Plan)Field(spatial,"plan")).actions[(int)Field(spatial,"actionIndex")].action_id=="holder.base","Base verification advanced without user confirmation");var successPanel=((GameObject)Field(spatial,"photoPrompt")).transform.Find("Photo guidance") as RectTransform;
  Check(successPanel!=null&&successPanel.anchorMax.y-successPanel.anchorMin.y<=.41f,"Success dialog remains oversized");
  Check(Array.Exists(successPanel.GetComponentsInChildren<Text>(),t=>t.fontSize>=31),"Success dialog text is too small");yield return Shot("flow-base-confirmation.png");
  ClickText((GameObject)Field(spatial,"photoPrompt"),"确认完成");yield return Wait(()=>((Manual2AR.Spatial.Plan)Field(spatial,"plan")).actions[(int)Field(spatial,"actionIndex")].action_id=="holder.slide"&&Field(spatial,"photoPrompt")!=null,"Confirmed base did not advance to holder step");
  int requestsBeforeManual=0,requestsAfterManual=0;
  yield return Call(origin+"/test/spatial/recognition-count","GET",null,raw=>requestsBeforeManual=JsonUtility.FromJson<RecognitionCounter>(raw).count);
  ClickText((GameObject)Field(spatial,"photoPrompt"),"准备拍照识别");
  int manualWaitFrame=((Manual2AR.Spatial.Reply)Field(spatial,"last")).client_frame_id;
  yield return Wait(()=>((Manual2AR.Spatial.Reply)Field(spatial,"last")).client_frame_id>=manualWaitFrame+3,"Manual recognition waiting stopped camera preview");
  yield return Call(origin+"/test/spatial/recognition-count","GET",null,raw=>requestsAfterManual=JsonUtility.FromJson<RecognitionCounter>(raw).count);
  Check(requestsBeforeManual==requestsAfterManual&&!(bool)Field(spatial,"locating")&&!(bool)Field(spatial,"partsDisplayActive")&&!(bool)Field(spatial,"semanticReady"),"Holder entry took a photo without user action");
  Check(((Text)Field(spatial,"checkResult")).GetComponent<AppReadableText>().Source.Contains("同时入镜"),"Holder entry did not explain manual framing: "+((Text)Field(spatial,"checkResult")).GetComponent<AppReadableText>().Source);yield return Shot("flow-04-manual-photo-ready.png");
  ((Button)Field(spatial,"locateButton")).onClick.Invoke();yield return Wait(()=>(bool)Field(spatial,"partsDisplayActive")&&!(bool)Field(spatial,"locating"),"Manual two-part recognition did not finish");
  yield return Call(origin+"/test/spatial/recognition-count","GET",null,raw=>requestsAfterManual=JsonUtility.FromJson<RecognitionCounter>(raw).count);
  Check(requestsAfterManual==requestsBeforeManual+1,"Manual capture did not make exactly one VLM recognition request");yield return Shot("flow-04-holder-guidance.png");
  string stableJob=(string)Field(spatial,"partsJob");
  yield return Call(origin+"/test/spatial/next-failure","POST","{\"kind\":\"recognition\"}",raw=>{});
  ((Button)Field(spatial,"locateButton")).onClick.Invoke();yield return Wait(()=>!(bool)Field(spatial,"locating"),"Failed replacement did not finish");
  Check((string)Field(spatial,"partsJob")==stableJob&&(bool)Field(spatial,"partsDisplayActive"),"Failed recognition erased the active tracker");
  yield return Call(origin+"/test/spatial/next-failure","POST","{\"kind\":\"verification\"}",raw=>{});
  ((Button)Field(spatial,"verify")).onClick.Invoke();yield return Wait(()=>!(bool)Field(spatial,"checking")&&(bool)Field(spatial,"verificationFailed"),"Negative installation check did not reach sidebar");
  Check(Field(spatial,"photoPrompt")==null,"Negative installation check opened a blocking dialog");
  Check(((Image)Field(spatial,"feedbackBackground")).color!=Color.clear,"Negative feedback has no red surface");
  int preservedFrame=((Manual2AR.Spatial.Reply)Field(spatial,"last")).client_frame_id;
  yield return Wait(()=>((Manual2AR.Spatial.Reply)Field(spatial,"last")).client_frame_id>preservedFrame+2,"Tracking froze after negative verification");
  Check((string)Field(spatial,"partsJob")==stableJob&&(bool)Field(spatial,"partsDisplayActive"),"Installation verdict cleared tracking");
  Check(((Text)Field(spatial,"checkResult")).GetComponent<AppReadableText>().Source.Contains("安装核验"),"Tracking overwrote the negative feedback");yield return Shot("flow-tracking-survives-vlm-failure.png");
  ((Button)Field(spatial,"verify")).onClick.Invoke();yield return Wait(()=>!(bool)Field(spatial,"checking")&&Field(spatial,"photoPrompt")!=null,"Final holder verification did not finish");Check(!(bool)Field(spatial,"verificationFailed")&&((Image)Field(spatial,"feedbackBackground")).color==Color.clear,"Successful recheck retained error highlighting");Invoke(spatial,"ClosePhotoPrompt");AppShell.GoBack();
  yield return Wait(()=>UnityEngine.Object.FindObjectOfType<Manual2AR.Spatial.SpatialGuidanceController>()==null&&!(bool)Field(guidance,"busy"),"Automatic flow did not return to tutorial");
  var completedTutorial=(GuidanceRun)Field(guidance,"run");Check(Array.Exists(completedTutorial.chapter_completion,c=>c.state_id=="U7"&&c.completed),"Verified spatial chapter was not marked complete");
  Invoke(guidance,"ShowOverview",false);yield return Shot("flow-05-completed-overview.png");foreach(var label in ((GameObject)Field(guidance,"modal")).GetComponentsInChildren<Text>())Check(!label.text.Contains("已浏览")&&!label.text.Contains("查看学习记录"),"Debug learning record remains in overview");Invoke(guidance,"CloseModal");
  guidance.StartCoroutine((IEnumerator)Invoke(guidance,"BeginSelected","a1_mini_first_print_external_v1","first_print_sd",true));
  yield return Wait(()=>Field(guidance,"run") is GuidanceRun firstPrint&&firstPrint.task_id=="a1_mini_first_print_external_v1"&&!(bool)Field(guidance,"busy"),"First-print task did not survive the UI change");Invoke(guidance,"CloseModal");
  bool hasManualRequirement=false;foreach(var paragraph in ((RectTransform)Field(guidance,"body")).GetComponentsInChildren<Text>())if(paragraph.text.Replace(((char)0x200b).ToString(),"").Contains("完成后请确认"))hasManualRequirement=true;
  Check(hasManualRequirement,"Gated manual task lost its confirmation requirement");Check(((Button)Field(guidance,"primary")).transform.parent==((AppWorkspace)Field(guidance,"workspace")).FooterRight,"Manual confirmation is hidden in photo dialog");yield return Shot("lesson-05-first-print.png");
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
  File.WriteAllText(Path.Combine(Folder,"success.json"),"{\"runtime_errors\":0,\"scenes\":4,\"service_library\":true,\"service_context\":true,\"diagnostic_controls_hidden\":true,\"controlled_learning_render\":true,\"automatic_cpu_fallback\":true,\"staged_inspection\":true,\"real_model_calls\":0,\"camera_hardware_tested\":false,\"center_crop_cases\":40,\"hierarchical_navigation\":true,\"navigation_canvas_repaired\":true,\"ratio_change_closes_session\":true,\"event_system_present\":true,\"spatial_replay\":true,\"spatial_metric_geometry\":true,\"spatial_pixel_picking\":true,\"spatial_reference_loaded\":true,\"spatial_preserves_tutorial_progress\":true,\"u7_composite_assets\":true,\"clockwise_from_tool_handle\":true,\"xyz_orientation_modal\":true,\"two_part_photo_guidance\":true,\"tracked_image_proxy\":true,\"wrong_frame_mask_rejected\":true,\"concurrent_masks_proxy_animation\":true,\"parameterized_rotation\":true,\"motion_parameter_panel\":true,\"three_point_coordinate_wizard\":true,\"u7_sequence_verified_unlock\":true,\"component_action_management\":true,\"empty_action_modal_recovery\":true,\"frameless_marker_captions\":true,\"unified_spatial_toolbar\":true,\"manual_holder_capture\":true,\"legible_spatial_text\":true,\"fixed_model_legend\":true,\"legend_lifecycle_and_colors\":true,\"tracking_survives_vlm_failure\":true,\"imperative_display_contract\":true,\"bidirectional_arrowhead\":true,\"u7_preflight_auto_guidance\":true,\"metric_text_annotations\":true,\"u7_contextual_information\":true,\"visual_completion_overview\":true,\"modal_blur_backdrop\":true,\"embedded_guidance_wiki\":true,\"chapter_card_layout\":true,\"guidance_footer_layout\":true,\"nonmodal_verification_failure\":true,\"compact_step_dialogs\":true,\"shared_workspace_contract\":true,\"ui_gallery_sizes\":3}");
  SessionState.SetBool(Key,false);EditorApplication.Exit(0);
 }
}
