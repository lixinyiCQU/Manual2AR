using System;
using System.Collections;
using System.IO;
using System.Reflection;
using Manual2AR;
using UnityEngine;
using UnityEngine.UI;

public static class WikiPipelineValidation {
 static BindingFlags Flags=BindingFlags.Instance|BindingFlags.NonPublic|BindingFlags.Public;
 static object Get(object o,string key){return o.GetType().GetField(key,Flags).GetValue(o);}
 static void Set(object o,string key,object value){o.GetType().GetField(key,Flags).SetValue(o,value);}
 static object Invoke(object o,string key,params object[] args){return o.GetType().GetMethod(key,Flags).Invoke(o,args);}
 static void Check(bool ok,string why){if(!ok)throw new Exception(why);}
 static string CanonicalText(Text label){var reader=label.GetComponent<AppReadableText>();return reader==null?label.text.Replace("\u200b",""):reader.Source;}
 static Button ButtonNamed(string text){foreach(var button in UnityEngine.Object.FindObjectsOfType<Button>()){var label=button.GetComponentInChildren<Text>();if(label!=null&&label.text.Replace(((char)0x200b).ToString(),"")==text)return button;}throw new Exception("Missing button "+text);}
 public static IEnumerator Run(string origin,byte[] photo,Action<string> shot){
  WikiToArView.Open(origin,()=>{});var view=UnityEngine.Object.FindObjectOfType<WikiToArView>();Check(view!=null,"Missing question-to-AR view");
  Set(view,"captured",photo);Set(view,"cameraSignature","controlled-camera");Set(view,"captureId",Guid.NewGuid().ToString("N"));Set(view,"frame",1);Set(view,"frozen",true);
  Invoke(view,"ShowImage",photo);((InputField)Get(view,"intent")).text="安装料盘支架";
  yield return view.StartCoroutine((IEnumerator)Invoke(view,"ShowExperiments"));
  Check(GameObject.Find("Pipeline experiment options")!=null,"Missing ablation options modal");
  ButtonNamed("启用全部优化").onClick.Invoke();yield return null;yield return null;shot("pipeline-00-ablation-options.png");
  ButtonNamed("应用开关").onClick.Invoke();yield return null;
  Check((bool)Get(Get(view,"options"),"scene_alignment")&&(bool)Get(Get(view,"options"),"contextual_display"),"Full preset did not persist selections");
  yield return view.StartCoroutine((IEnumerator)Invoke(view,"Generate"));
  var job=Get(view,"job");Check(job!=null&&(string)Get(job,"status")=="ready","Question/photo did not produce a runnable candidate");
  Check(((Button)Get(view,"preview")).interactable,"Generated AR entry disabled");
  yield return null;
  var automatic=GameObject.Find("Generated task preview");Check(automatic!=null,"Completed job did not automatically show preview");automatic.GetComponent<AppDialog>().Close();
  shot("pipeline-01-question-and-generated-task.png");
  yield return view.StartCoroutine((IEnumerator)Invoke(view,"Resume"));
  Check((string)Get(Get(view,"job"),"id")== (string)Get(job,"id"),"Resume generated a different task");
  Check((bool)Get(view,"busy")==false,"Controls stayed locked after resume");
  Check((bool)Get(Get(view,"options"),"staged_compilation"),"Resuming lost method switches");
  yield return null;shot("pipeline-02-evidence-preview.png");
  var dialog=GameObject.Find("Generated task preview");Check(dialog!=null,"Missing generated task preview");dialog.GetComponent<AppDialog>().Close();
  yield return view.StartCoroutine((IEnumerator)Invoke(view,"Approve",Get(job,"candidate")));
  var spatial=UnityEngine.Object.FindObjectOfType<Manual2AR.Spatial.SpatialGuidanceController>();
  float end=Time.realtimeSinceStartup+15;while(spatial!=null&&Get(spatial,"plan")==null&&Time.realtimeSinceStartup<end)yield return null;
  Check(spatial!=null&&Get(spatial,"plan")!=null,"Generated candidate did not load isolated spatial runtime");
  var plan=(Manual2AR.Spatial.Plan)Get(spatial,"plan");Check(plan.actions.Length==2&&plan.actions[0].instruction.Contains("M3-8"),"Authored plan substituted for generated instructions");
  Check(plan.display_profiles!=null&&plan.display_profiles.Length==2,"Generated contextual display profiles missing");
  Check(plan.runtime_contract=="compiled-spatial-v3"&&plan.stateful_runtime,"Generated AR did not load isolated geometry / scene-only verification contract");
  Check(((Manual2AR.Spatial.SpatialCamera)Get(spatial,"cameraOwner")).Ready==false,"Validation unexpectedly opened physical camera");
  yield return null;shot("pipeline-03-generated-ar-workspace.png");
  string api=(string)Get(spatial,"Api");string response=null,failure=null;
  yield return spatial.StartCoroutine((IEnumerator)Invoke(spatial,"Request",api+"/sessions","POST","{\"camera_id\":\"controlled-no-camera\",\"mode\":\"camera\",\"visual_client_revision\":\"machine-workframe-v1\"}",new Action<string,string>((raw,error)=>{response=raw;failure=error;}),10));
  Check(failure==null,"Cannot create controlled execution session");var session=JsonUtility.FromJson<Manual2AR.Spatial.Session>(response);Set(spatial,"session",session);
  string sha;using(var digest=System.Security.Cryptography.SHA256.Create())sha=BitConverter.ToString(digest.ComputeHash(photo)).Replace("-","").ToLowerInvariant();
  var probe=new Texture2D(2,2);ImageConversion.LoadImage(probe,photo);
  var snapshot=new Manual2AR.Spatial.CaptureSnapshot{provider_id="desktop_rgb",client_frame_id=1,source_sha256=sha,width=probe.width,height=probe.height,capture_monotonic_ms=1};UnityEngine.Object.Destroy(probe);
  var frame=new Manual2AR.Spatial.Frame{snapshot=snapshot,action_id="holder.base",client_frame_id=1,source_sha256=sha,image_base64=Convert.ToBase64String(photo)};
  yield return spatial.StartCoroutine((IEnumerator)Invoke(spatial,"Request",api+"/sessions/"+session.session_id+"/frames","POST",JsonUtility.ToJson(frame),new Action<string,string>((raw,error)=>{response=raw;failure=error;}),10));Check(failure==null,"Cannot deliver controlled scene frame: "+failure+" "+response);
  byte[] runtimePhoto=photo;
  for(int sample=2;sample<=3;sample++){
   var image=new Texture2D(2,2);ImageConversion.LoadImage(image,photo);for(int x=0;x<12;x++)for(int y=0;y<12;y++)image.SetPixel(x,y,sample==2?Color.red:Color.green);image.Apply();runtimePhoto=image.EncodeToJPG(90);UnityEngine.Object.Destroy(image);
   using(var digest=System.Security.Cryptography.SHA256.Create())sha=BitConverter.ToString(digest.ComputeHash(runtimePhoto)).Replace("-","").ToLowerInvariant();
   frame.client_frame_id=sample;frame.snapshot.client_frame_id=sample;frame.snapshot.source_sha256=frame.source_sha256=sha;frame.image_base64=Convert.ToBase64String(runtimePhoto);frame.snapshot.capture_monotonic_ms=sample*300;
   yield return new WaitForSecondsRealtime(.3f);
   yield return spatial.StartCoroutine((IEnumerator)Invoke(spatial,"Request",api+"/sessions/"+session.session_id+"/frames","POST",JsonUtility.ToJson(frame),new Action<string,string>((raw,error)=>{response=raw;failure=error;}),10));Check(failure==null,"Cannot provide distinct temporal frames");
  }
  var reply=JsonUtility.FromJson<Manual2AR.Spatial.Reply>(response);Invoke(spatial,"RenderFrame",runtimePhoto,reply);
  end=Time.realtimeSinceStartup+15;while(((bool)Get(spatial,"assessingScene")||Get(spatial,"execution")==null)&&Time.realtimeSinceStartup<end)yield return null;
  var execution=(Manual2AR.Spatial.TaskExecution)Get(spatial,"execution");Check(execution!=null&&execution.mode=="check","Installed base did not enter verification-only mode");
  yield return null;Check(((Button)Get(spatial,"verify")).interactable,"Verification incorrectly requires a marker or animation setup");shot("pipeline-05-existing-base-check.png");
  yield return spatial.StartCoroutine((IEnumerator)Invoke(spatial,"Verify"));yield return null;
  Check(GameObject.Find("Compiled manual conditions")!=null,"Mechanical condition was auto-approved from image");ButtonNamed("已逐项人工核实").onClick.Invoke();
  end=Time.realtimeSinceStartup+10;while(GameObject.Find("Photo preparation")==null&&Time.realtimeSinceStartup<end)yield return null;
  ButtonNamed("继续下一项操作或检查").onClick.Invoke();yield return null;
  yield return spatial.StartCoroutine((IEnumerator)Invoke(spatial,"Request","/test/pipeline/scene-state","POST","{\"S1\":\"satisfied\",\"S2\":\"satisfied\"}",new Action<string,string>((raw,error)=>failure=error),10));
  frame.action_id="holder.slide";frame.client_frame_id=4;frame.snapshot.client_frame_id=4;
  yield return spatial.StartCoroutine((IEnumerator)Invoke(spatial,"Request",api+"/sessions/"+session.session_id+"/frames","POST",JsonUtility.ToJson(frame),new Action<string,string>((raw,error)=>{response=raw;failure=error;}),10));Check(failure==null,"Remaining step could not execute without authored base gate");
  reply=JsonUtility.FromJson<Manual2AR.Spatial.Reply>(response);Invoke(spatial,"RenderFrame",runtimePhoto,reply);
  end=Time.realtimeSinceStartup+15;while((bool)Get(spatial,"assessingScene")&&Time.realtimeSinceStartup<end)yield return null;
  execution=(Manual2AR.Spatial.TaskExecution)Get(spatial,"execution");Check(execution.mode=="check"&&execution.action_id=="holder.slide","Already installed holder repeated installation");shot("pipeline-06-installed-holder-check.png");
  yield return spatial.StartCoroutine((IEnumerator)Invoke(spatial,"Close"));
  Check(((RectTransform)Get(view,"root")).gameObject.activeSelf,"Cannot return from generated AR");Invoke(view,"ShowHumanReview");yield return null;shot("pipeline-04-human-review.png");
  ButtonNamed("任务规划：未评价").onClick.Invoke();ButtonNamed("保存人工评价").onClick.Invoke();yield return new WaitForSecondsRealtime(.5f);Invoke(view,"Close");
  File.WriteAllText(Path.Combine(Application.dataPath,"../Validation/wiki-pipeline.json"),"{\"question_photo_to_candidate\":true,\"approval_and_generated_ar\":true,\"return_navigation\":true,\"real_model_calls\":0,\"camera_hardware_tested\":false}");
 }
 public static IEnumerator Official(string origin,Action<string> shot){
  var view=OfficialCompileView.Open(origin,()=>{});
  ((InputField)Get(view,"intent")).text="我已完成底座，现在希望安装夹具手柄";
  yield return view.StartCoroutine((IEnumerator)Invoke(view,"Generate"));
  var job=Get(view,"job");Check(job!=null&&(string)Get(job,"status")=="ready","Official fixture did not compile");
  Check(((Button)Get(view,"use")).interactable,"Compiled task is not selectable");
  Check(((string)Get(job,"preview")).Contains("fasten_fixture"),"Generated preview was substituted with GT");
  yield return null;shot("official-01-generated-review.png");
  yield return view.StartCoroutine((IEnumerator)Invoke(view,"Enter"));
  var spatial=UnityEngine.Object.FindObjectOfType<Manual2AR.Spatial.SpatialGuidanceController>();
  yield return BaselineWait(()=>spatial!=null&&Get(spatial,"plan")!=null,"Compiled official task did not open AR");
  var plan=(Manual2AR.Spatial.Plan)Get(spatial,"plan");
  Check(plan.runtime_contract=="baseline-ar-v1"&&((string)Get(spatial,"Api")).StartsWith("/api/guidance/compiled/jobs/"),"Wrong compiled baseline runtime");
  Check(plan.actions[0].instruction.Contains("3")||plan.actions[0].instruction.Contains("2"),"Generated instruction missing official count");
  Check(!((Manual2AR.Spatial.SpatialCamera)Get(spatial,"cameraOwner")).Ready,"Official UI probe opened camera");
  yield return null;shot("official-02-generated-ar-entry.png");
  string[] intents={"安装控制夹具","将底座固定到立柱","将夹具手柄从上向下滑入底座"};
  int[] selectedCounts={2,1,1},neededCounts={2,1,2};
  Set(spatial,"frozen",true);
  for(int i=0;i<intents.Length;i++){
   if(i>0)Invoke(spatial,"ShowBaselineGoalChoice");
   var input=GameObject.Find("Goal intent").GetComponent<InputField>();input.text=intents[i];
   ButtonNamed("对应官方步骤").onClick.Invoke();
   yield return BaselineWait(()=>ButtonNamed("使用此目标").interactable,"Goal did not align with its official parent or leaf operation: "+intents[i]);
   yield return null;shot("official-goal-0"+(i+1)+"-match.png");
   ButtonNamed("使用此目标").onClick.Invoke();
   Check((bool)Get(spatial,"goalConfirmed")&&(string)Get(spatial,"goalIntent")==intents[i],"Goal choice lost explicit user intent");
   var command=new Manual2AR.Spatial.Begin{camera_id="controlled-goal-ui",goal_intent=(string)Get(spatial,"goalIntent")};string raw=null;
   yield return BaselineSend(spatial,(string)Get(spatial,"Api")+"/sessions",JsonUtility.ToJson(command),s=>raw=s);
   var session=JsonUtility.FromJson<Manual2AR.Spatial.Session>(raw);Set(spatial,"session",session);Set(spatial,"execution",null);Invoke(spatial,"ApplyBaseline",session.execution);
   Check(session.execution.target_node_ids.Length==selectedCounts[i]&&session.execution.needed_node_ids.Length==neededCounts[i],"Selected goal scope differs from its official dependency closure");
   yield return null;
   Check(!string.IsNullOrEmpty(session.execution.task_summary)&&CanonicalText((Text)Get(spatial,"taskSummary")).Contains(AppReadableText.Prepare(session.execution.current_step)),"Current task progress is not visible");
   yield return null;shot("official-goal-0"+(i+1)+"-progress.png");
   yield return spatial.StartCoroutine((IEnumerator)Invoke(spatial,"DropSession"));Set(spatial,"execution",null);
  }
  yield return spatial.StartCoroutine((IEnumerator)Invoke(spatial,"Close"));
  Check(((RectTransform)Get(view,"root")).gameObject.activeSelf,"Cannot return to official compilation review");
  Invoke(view,"Close");
  File.WriteAllText(Path.Combine(Application.dataPath,"../Validation/official-compiler.json"),"{\"controlled_fixture_compilation\":true,\"gt_input\":false,\"generated_preview_and_ar_entry\":true,\"parent_and_two_leaf_goals_selected\":true,\"persistent_scope_and_progress\":true,\"real_model_calls\":0,\"camera_hardware_tested\":false}");
 }
 public static IEnumerator Review(string origin,Action<string> shot){
  var view=BaselineReviewView.Open(origin,()=>{});
  yield return BaselineWait(()=>Get(view,"candidate")!=null&&!(bool)Get(view,"busy"),"Review candidate did not load");
  var candidate=Get(view,"candidate");Check((bool)Get(candidate,"contract_pass"),"Missing reviewable fixture");
  yield return BaselineWait(()=>((UnityEngine.UI.RawImage)Get(view,"image")).texture!=null,"Official review image not loaded");
  Invoke(view,"EnlargeReference");yield return null;Check(GameObject.Find("Enlarged spatial reference")!=null,"Review reference does not enlarge");
  ((Manual2AR.Spatial.SpatialReferenceViewer)Get(view,"referenceViewer")).Close();yield return null;
  yield return null;shot("review-01-official-and-generated.png");
  ((InputField)Get(view,"reviewer")).text="受控UI验证，不是实际人工审核";
  ((InputField)Get(view,"note")).text="自动化回归标签只保存在测试服务临时目录，不进入真实评价。";
  for(int i=0;i<4;i++)Invoke(view,"Rate",i);
  yield return view.StartCoroutine((IEnumerator)Invoke(view,"Save"));
  Check(!(bool)Get(view,"dirty")&&(int)Get(Get(view,"listing"),"reviewed")==1,"Review save did not persist formal fixture label");
  var attempts=(Dropdown)Get(view,"attempts");Check(attempts.options[attempts.value].text.EndsWith("通过"),"Candidate caption stayed unrated after save");
  var officialImage=(RawImage)Get(view,"image");Check(officialImage.texture!=null&&officialImage.color.a>.9f,"Saving review discarded official image");
  yield return null;shot("review-02-saved-rubric.png");
  yield return view.StartCoroutine((IEnumerator)Invoke(view,"ExportReview"));
  Check(((Text)Get(view,"status")).text.Contains("导出"),"Review export missing");
  Invoke(view,"Close");yield return null;
  view=BaselineReviewView.Open(origin,()=>{});
  yield return BaselineWait(()=>Get(view,"candidate")!=null&&!(bool)Get(view,"busy"),"Saved review did not reopen");
  Check((string)Get(Get(Get(view,"candidate"),"label"),"decision")=="approved","Review reset on reopening");
  for(int i=0;i<2;i++){
   string trial="fixture.r0"+(i+1);
   yield return view.StartCoroutine((IEnumerator)Invoke(view,"LoadCandidate",trial));
   yield return view.StartCoroutine((IEnumerator)Invoke(view,"Enter"));
   var spatial=UnityEngine.Object.FindObjectOfType<Manual2AR.Spatial.SpatialGuidanceController>();
   yield return BaselineWait(()=>spatial!=null&&Get(spatial,"plan")!=null,"Archived candidate did not open AR");
   var plan=(Manual2AR.Spatial.Plan)Get(spatial,"plan");
   Check(plan.task_origin=="automatic_official_compilation"&&plan.actions[0].instruction.Contains("2"),"Archived candidate replaced with GT");
   Check(!((Manual2AR.Spatial.SpatialCamera)Get(spatial,"cameraOwner")).Ready,"Review probe opened camera");
   yield return null;shot("review-0"+(i+3)+"-candidate-ar.png");
   yield return spatial.StartCoroutine((IEnumerator)Invoke(spatial,"Close"));
   yield return BaselineWait(()=>!(bool)Get(view,"busy"),"Review did not reload after AR");
   Check(((RectTransform)Get(view,"root")).gameObject.activeSelf,"Cannot return to human review from AR");
  }
  Invoke(view,"Close");
  File.WriteAllText(Path.Combine(Application.dataPath,"../Validation/baseline-review.json"),"{\"official_images\":true,\"four_rubric_save_reload_export\":true,\"two_archived_candidates_enter_ar\":true,\"labels_scope\":\"controlled_test_only\",\"real_model_calls\":0,\"camera_hardware_tested\":false}");
 }
 static IEnumerator BaselineSend(Manual2AR.Spatial.SpatialGuidanceController view,string path,string body,Action<string> receive){
  string failure=null;
  yield return view.StartCoroutine((IEnumerator)Invoke(view,"Request",path,"POST",body,new Action<string,string>((raw,error)=>{failure=error;if(error==null)receive(raw);}),20));
  Check(failure==null,"Baseline API: "+failure);
 }
 static IEnumerator BaselineWait(Func<bool> ready,string message){
  float end=Time.realtimeSinceStartup+15;while(!ready()&&Time.realtimeSinceStartup<end)yield return null;
  Check(ready(),message);
 }
 [Serializable] class BaselineCounter {public int count;}
 static IEnumerator BaselineCalls(Manual2AR.Spatial.SpatialGuidanceController view,Action<int> receive){
  string failure=null;
  yield return view.StartCoroutine((IEnumerator)Invoke(view,"Request","/test/baseline/call-count","GET",null,new Action<string,string>((raw,error)=>{failure=error;if(error==null)receive(JsonUtility.FromJson<BaselineCounter>(raw).count);}),10));
  Check(failure==null,"Cannot read controlled baseline call count");
 }
 sealed class BaselineFrames:Manual2AR.Spatial.ISpatialFrameSource {
  byte[] bytes;bool ready;public bool failNext;public int opened;
  public BaselineFrames(byte[] value){bytes=value;}public bool Ready=>ready;public string Signature=>"controlled-baseline-camera-switch";public string ProviderId=>"desktop_rgb";public int CaptureWidth=>960;public int CaptureHeight=>720;
  public IEnumerator Open(int selected,Action<string> error){opened++;if(failNext){failNext=false;ready=false;error("受控相机启动失败");yield break;}ready=true;yield break;}
  public byte[] Capture(){return bytes;}public void Close(){ready=false;}
 }
 public static IEnumerator Baseline(string origin,Action<string> shot){
  var view=Manual2AR.Spatial.SpatialGuidanceController.OpenBaseline(origin,()=>{});
  yield return BaselineWait(()=>Get(view,"plan")!=null,"Baseline did not load");
  Check(((Manual2AR.Spatial.Plan)Get(view,"plan")).runtime_contract=="baseline-ar-v1","Wrong baseline runtime");
  string api=(string)Get(view,"Api"),raw=null;
  yield return BaselineSend(view,"/test/baseline/state","{\"base\":true,\"holder\":false,\"hidden\":false}",s=>{});
  yield return BaselineSend(view,"/test/baseline/grounding","{\"missing\":true}",s=>{});
  yield return BaselineSend(view,api+"/sessions","{\"camera_id\":\"baseline-probe\",\"mode\":\"camera\",\"reuse_targets\":true,\"visual_client_revision\":\"machine-workframe-v1\"}",s=>raw=s);
  var session=JsonUtility.FromJson<Manual2AR.Spatial.Session>(raw);Set(view,"session",session);Set(view,"frozen",true);
  byte[] photo;
  using(var get=UnityEngine.Networking.UnityWebRequest.Get(origin+api+"/replay/30.jpg")){
   yield return get.SendWebRequest();Check(get.result==UnityEngine.Networking.UnityWebRequest.Result.Success,"Missing synthetic baseline photo");photo=get.downloadHandler.data;
  }
  string sha;using(var digest=System.Security.Cryptography.SHA256.Create())sha=BitConverter.ToString(digest.ComputeHash(photo)).Replace("-","").ToLowerInvariant();
  var frame=new Manual2AR.Spatial.Frame{action_id="holder.base",client_frame_id=1,source_sha256=sha,image_base64=Convert.ToBase64String(photo),snapshot=new Manual2AR.Spatial.CaptureSnapshot{provider_id="desktop_rgb",client_frame_id=1,source_sha256=sha,width=960,height=720,capture_monotonic_ms=1}};
  yield return BaselineSend(view,api+"/sessions/"+session.session_id+"/frames",JsonUtility.ToJson(frame),s=>raw=s);
  var reply=JsonUtility.FromJson<Manual2AR.Spatial.Reply>(raw);Check(!Manual2AR.Spatial.SpatialAssetGraphic.HasPlacement(reply.visual),"Unknown baseline showed operation assets");Invoke(view,"RenderFrame",photo,reply);
  int beforeCalls=0,afterCalls=0;yield return BaselineCalls(view,n=>beforeCalls=n);
  yield return new WaitForSecondsRealtime(.25f);yield return BaselineCalls(view,n=>afterCalls=n);
  Check(!(bool)Get(view,"checking")&&beforeCalls==afterCalls,"Camera startup automatically invoked vision");
  Check(((Button)Get(view,"locateButton")).gameObject.activeSelf&&!((Button)Get(view,"verify")).gameObject.activeSelf,"Initial stage shows both assessment and verification");
  shot("baseline-00-idle-manual-assessment.png");Invoke(view,"ShowLocateCapture");
  yield return new WaitForSecondsRealtime(.1f);
  Check((bool)Get(view,"checking")&&((Text)Get(view,"checkResult")).text.Replace("\u200b","").Contains("正在评估"),"Live updates erased pending baseline feedback");
  yield return BaselineWait(()=>!(bool)Get(view,"checking"),"Ungrounded baseline check did not finish");
  yield return new WaitForSecondsRealtime(.15f);
  var feedbackLabel=(Text)Get(view,"checkResult");string canonicalFeedback=CanonicalText(feedbackLabel),savedFeedback=((string)Get(view,"verificationFeedback")).Replace("\u200b","");
  Debug.Log("Baseline diagnostic feedback: rendered="+feedbackLabel.text+" | canonical="+canonicalFeedback+" | saved="+savedFeedback);
  shot("baseline-00-missing-grounding-feedback.png");
  Check(canonicalFeedback.Contains("未确认")&&!savedFeedback.Contains("证据框"),"Default feedback must be concise and preserve uncertainty");
  Check(((Manual2AR.Spatial.TaskExecution)Get(view,"execution")).baseline_mode=="request_view","Ungrounded claim advanced baseline");
  Check(((Button)Get(view,"locateButton")).interactable&&!((Button)Get(view,"verify")).gameObject.activeSelf,"Assessment stage did not recover one clear action");
  ButtonNamed("返回调整画面").onClick.Invoke();
  yield return BaselineSend(view,"/test/baseline/grounding","{\"missing\":false}",s=>{});
  yield return BaselineSend(view,"/test/baseline/state","{\"base\":false}",s=>{});
  Invoke(view,"ShowLocateCapture");
  yield return BaselineWait(()=>Get(view,"execution")!=null&&((Manual2AR.Spatial.TaskExecution)Get(view,"execution")).baseline_mode=="operate"&&!(bool)Get(view,"checking"),"Initial baseline observation did not request installation");
  Check(!((Button)Get(view,"locateButton")).gameObject.activeSelf&&((Button)Get(view,"verify")).gameObject.activeSelf,"Operation stage still shows assessment action");Invoke(view,"ClosePhotoPrompt");
  frame.client_frame_id=2;frame.snapshot.client_frame_id=2;
  yield return BaselineSend(view,api+"/sessions/"+session.session_id+"/frames",JsonUtility.ToJson(frame),s=>raw=s);
  reply=JsonUtility.FromJson<Manual2AR.Spatial.Reply>(raw);Set(view,"guidedStarted",true);Set(view,"semanticReady",true);Set(view,"partsDisplayActive",true);Invoke(view,"RenderFrame",photo,reply);yield return null;Canvas.ForceUpdateCanvases();
  var graphic=(Manual2AR.Spatial.SpatialAssetGraphic)Get(view,"assetGraphic");
  Check(graphic.VisibleTriangles>0&&graphic.AssetProvenance=="manual2ar-library-v1/u7.holder_base","Baseline screw assets not rendered");shot("baseline-01-base-operation.png");
  yield return BaselineSend(view,"/test/baseline/state","{\"base\":true}",s=>{});
  yield return view.StartCoroutine((IEnumerator)Invoke(view,"CheckBaseline",true));yield return null;
  var token=(Manual2AR.Spatial.TaskExecution)Get(view,"execution");
  Check(token.baseline_mode=="ask_manual"&&token.manual_conditions.Length==2,"Current manual conditions are not grouped");
  Check(GameObject.Find("Baseline visual results")!=null&&CanonicalText(GameObject.Find("Baseline visual results").GetComponentInChildren<Text>()).Contains("可见检查通过"),"Visual evidence was not shown before manual confirmation");
  Check(!CanonicalText(GameObject.Find("Baseline visual results").GetComponentInChildren<Text>()).Contains("受控事实"),"Raw model narration leaked into concise feedback");
  ButtonNamed("查看识别详情").onClick.Invoke();yield return null;
  Check(CanonicalText(GameObject.Find("Baseline observation details").GetComponentInChildren<Text>()).Contains("模型观察"),"Accepted observations are unavailable in details");
  ButtonNamed("返回检查结果").onClick.Invoke();yield return null;
  var manualBody=CanonicalText(GameObject.Find("Baseline manual conditions").GetComponentInChildren<Text>());
  Check(Array.TrueForAll(token.manual_conditions,c=>manualBody.Contains(AppReadableText.Prepare(c.statement))),"Manual result window omits a pending condition");
  Check(!ButtonNamed("确认全部并继续").interactable,"Manual confirmation was preselected");
  yield return null;shot("baseline-02-prime-results.png");yield return new WaitForSecondsRealtime(.05f);shot("baseline-02-visual-results-and-all-manual.png");
  ButtonNamed("暂不确认").onClick.Invoke();yield return null;
  Check(((Manual2AR.Spatial.TaskExecution)Get(view,"execution")).revision==token.revision,"Closing manual results changed progress");
  yield return BaselineCalls(view,n=>beforeCalls=n);Invoke(view,"ShowVerifyCapture");yield return null;yield return BaselineCalls(view,n=>afterCalls=n);
  Check(beforeCalls==afterCalls,"Opening pending manual results took another photo");
  frame.client_frame_id=3;frame.snapshot.client_frame_id=3;
  yield return BaselineSend(view,api+"/sessions/"+session.session_id+"/frames",JsonUtility.ToJson(frame),s=>raw=s);
  Invoke(view,"RenderFrame",photo,JsonUtility.FromJson<Manual2AR.Spatial.Reply>(raw));int retryRevision=token.revision;
  ButtonNamed("重新拍照核验").onClick.Invoke();
  yield return BaselineWait(()=>((Manual2AR.Spatial.TaskExecution)Get(view,"execution")).revision>retryRevision&&!(bool)Get(view,"checking"),"Manual result cannot be challenged with a new photo");
  token=(Manual2AR.Spatial.TaskExecution)Get(view,"execution");Check(token.completed_state_ids.Length==0&&token.manual_conditions.Length==2,"Retaking a photo silently confirmed manual conditions");
  GameObject.Find("All manual conditions acknowledged").GetComponent<Toggle>().isOn=true;
  Check(ButtonNamed("确认全部并继续").interactable,"Explicit checkbox did not enable confirmation");
  ButtonNamed("确认全部并继续").onClick.Invoke();
  yield return BaselineWait(()=>((Manual2AR.Spatial.TaskExecution)Get(view,"execution")).revision>token.revision&&!(bool)Get(view,"checking"),"Grouped manual confirmation did not advance");yield return null;
  var nextOperation=(Manual2AR.Spatial.TaskExecution)Get(view,"execution");
  Check(nextOperation.action_id=="holder.slide"&&nextOperation.guidance_ready&&nextOperation.mode=="operate","Base did not enter holder guidance after manual confirmation");
  Check(CanonicalText((Text)Get(view,"taskSummary")).Contains(AppReadableText.Prepare(nextOperation.current_step)),"Next operation is hidden from task progress");Set(view,"frozen",true);
  frame.action_id="holder.slide";frame.client_frame_id=4;frame.snapshot.client_frame_id=4;
  yield return BaselineSend(view,api+"/sessions/"+session.session_id+"/frames",JsonUtility.ToJson(frame),s=>raw=s);
  reply=JsonUtility.FromJson<Manual2AR.Spatial.Reply>(raw);Set(view,"guidedStarted",true);Set(view,"semanticReady",true);Set(view,"partsDisplayActive",true);Invoke(view,"RenderFrame",photo,reply);yield return null;Canvas.ForceUpdateCanvases();
  yield return BaselineWait(()=>GameObject.Find("Next official operation")!=null,"Manual confirmation did not open next AR operation");shot("baseline-03-next-operation-entry.png");Invoke(view,"ClosePhotoPrompt");yield return null;
  Check(graphic.VisibleTriangles>0&&graphic.AssetProvenance=="manual2ar-library-v1/u7.holder_slide","Baseline slide assets not rendered");shot("baseline-03-holder-operation.png");
  var modern=JsonUtility.FromJson<Manual2AR.Spatial.GuidanceVisual>(JsonUtility.ToJson(reply.visual));modern.asset=null;modern.label="受控定位说明";modern.anchor=new Manual2AR.Spatial.Pixel(300,200);
  var callout=(Manual2AR.Spatial.SpatialCallout)Get(view,"callout");callout.Show(modern);callout.Show(new Manual2AR.Spatial.GuidanceVisual());
  Check(!((RectTransform)Get(callout,"root")).gameObject.activeSelf,"Incomplete callout was not safely hidden");
  yield return view.StartCoroutine((IEnumerator)Invoke(view,"CheckBaseline",true));yield return null;
  var failedCheck=(Manual2AR.Spatial.TaskExecution)Get(view,"execution");
  Check(failedCheck.mode=="operate"&&failedCheck.action_id=="holder.slide"&&failedCheck.completed_state_ids.Length==1,"Failed photo changed official step");
  Check((bool)Get(view,"guidedStarted"),"Same-step failed check reset the guidance lifecycle");
  Check(GameObject.Find("Next official operation")==null,"Failed check replayed next-operation entry");
  Check(ButtonNamed("返回调整画面")!=null,"Failed check must offer adjustment instead of AR replay");
  shot("baseline-03-failed-check-retry.png");ButtonNamed("返回调整画面").onClick.Invoke();yield return null;
  Check(GameObject.Find("Next official operation")==null,"Dismissing failed check restarted AR entry");
  frame.client_frame_id=5;frame.snapshot.client_frame_id=5;
  yield return BaselineSend(view,api+"/sessions/"+session.session_id+"/frames",JsonUtility.ToJson(frame),s=>raw=s);
  Invoke(view,"RenderFrame",photo,JsonUtility.FromJson<Manual2AR.Spatial.Reply>(raw));
  yield return BaselineSend(view,"/test/baseline/state","{\"holder\":true,\"hidden\":true}",s=>{});
  yield return view.StartCoroutine((IEnumerator)Invoke(view,"CheckBaseline",true));yield return null;
  var holder=(Manual2AR.Spatial.TaskExecution)Get(view,"execution");Check(holder.baseline_mode=="ask_manual"&&holder.manual_conditions[0].id=="c.holder.direction","Verified base history did not survive normal occlusion");
  Set(view,"baselineVerificationStage",false);Invoke(view,"ShowBaselineManual",holder);yield return null;
  Check(ButtonNamed("重新拍照核验")!=null,"Completed prerequisite did not restore operation verification stage");
  GameObject.Find("All manual conditions acknowledged").GetComponent<Toggle>().isOn=true;ButtonNamed("确认全部并继续").onClick.Invoke();
  yield return BaselineWait(()=>((Manual2AR.Spatial.TaskExecution)Get(view,"execution")).complete&&!(bool)Get(view,"checking"),"Baseline loop did not complete");yield return null;shot("baseline-04-complete.png");
  Check(!((Manual2AR.Spatial.SpatialCamera)Get(view,"cameraOwner")).Ready,"Baseline probe opened physical camera");
  Invoke(view,"ClosePhotoPrompt");var camera=new BaselineFrames(photo);Set(view,"frameSource",camera);
  camera.failNext=true;yield return view.StartCoroutine((IEnumerator)Invoke(view,"BeginSession","camera",false));
  Check(!(bool)Get(view,"changing")&&Get(view,"session")==null,"Camera startup failure locked the controller");
  yield return BaselineCalls(view,n=>beforeCalls=n);
  yield return view.StartCoroutine((IEnumerator)Invoke(view,"BeginSession","camera",false));
  yield return BaselineWait(()=>Get(view,"last")!=null,"Controlled camera did not recover after startup failure");
  string oldSession=((Manual2AR.Spatial.Session)Get(view,"session")).session_id;
  Set(view,"partsDisplayActive",true);Set(view,"partsJob","stale-controlled-tracker");Set(view,"frozen",true);
  yield return view.StartCoroutine((IEnumerator)Invoke(view,"BeginSession","camera",false));
  yield return BaselineWait(()=>Get(view,"last")!=null&&((Manual2AR.Spatial.Reply)Get(view,"last")).client_frame_id>=2,"Camera restart stopped displaying live frames");
  Check(!(bool)Get(view,"partsDisplayActive")&&!(bool)Get(view,"frozen")&&((Manual2AR.Spatial.Session)Get(view,"session")).session_id!=oldSession,"Camera switch retained stale tracking state");
  yield return BaselineCalls(view,n=>afterCalls=n);Check(beforeCalls==afterCalls,"Camera restart triggered automatic evaluation");
  shot("baseline-05-camera-restart-awaits-user.png");
  File.WriteAllText(Path.Combine(Application.dataPath,"../Validation/baseline-ar.json"),"{\"controlled_closed_loop\":true,\"both_u7_assets_rendered\":true,\"manual_conditions\":3,\"manual_windows\":2,\"no_automatic_assessment\":true,\"phase_specific_buttons\":true,\"visual_results_before_manual\":true,\"batch_manual_confirmation\":true,\"camera_restart_releases_tracking\":true,\"camera_failure_recoverable\":true,\"partial_callout_safe\":true,\"failed_check_does_not_restart_guidance\":true,\"concise_feedback_with_optional_details\":true,\"real_model_calls\":0,\"camera_hardware_tested\":false}");
  yield return view.StartCoroutine((IEnumerator)Invoke(view,"Close"));
 }
 [Serializable] class DemoReply {public string mode,source_sha256;public Manual2AR.Spatial.TaskExecution execution;}
 static DemoReply DemoState(U7DemoView view){var value=Get(view,"reply");return value==null?null:JsonUtility.FromJson<DemoReply>(JsonUtility.ToJson(value));}
 public static IEnumerator Demo(string origin,Action<string> shot){
  bool closed=false;var view=U7DemoView.Open(origin,()=>closed=true);
  yield return BaselineWait(()=>Get(view,"catalog")!=null&&Get(view,"captured")!=null&&!(bool)Get(view,"busy"),"U7 demo did not load historical photographs");
  Check(((Dropdown)Get(view,"modes")).value==0,"Demo does not default to explicitly scripted observations");
  Check(CanonicalText((Text)Get(view,"notice")).Contains("预设观察"),"Demo evidence source is hidden");
  yield return null;Canvas.ForceUpdateCanvases();
  var mainAction=(Button)Get(view,"action");var resetAction=(Button)Get(view,"reset");
  Check(mainAction.gameObject.activeInHierarchy&&((RectTransform)mainAction.transform).rect.width>100&&((RectTransform)mainAction.transform).rect.height>30,"Demo main action is not visibly laid out");
  Check(((RectTransform)resetAction.transform).rect.width>100,"Demo reset action is collapsed");
  shot("demo-00-question-and-photo.png");
  Invoke(view,"ShowSources");yield return null;
  var official=GameObject.Find("Demo official steps");Check(official!=null,"Official steps require a generated plan");
  string officialText="";foreach(var text in official.GetComponentsInChildren<Text>())officialText+=CanonicalText(text);
  Check(officialText.Contains("M3-8")&&officialText.Contains("滑入"),"Before-plan official view omits U7 steps");
  Check(DemoState(view)==null,"Browsing official instructions created a session");
  shot("demo-00-official-steps-before-plan.png");ButtonNamed("返回当前任务").onClick.Invoke();yield return null;
  ((InputField)Get(view,"question")).text="安装料盘底座及滑入料盘支架";
  ((Button)Get(view,"action")).onClick.Invoke();
  yield return BaselineWait(()=>DemoState(view)!=null&&DemoState(view).execution.baseline_mode=="ask_manual"&&!(bool)Get(view,"busy"),"Demo did not match composite goal and assess base");
  Check(DemoState(view).execution.target_node_ids.Length==2,"Demo lost part of composite goal");
  ((Button)Get(view,"action")).onClick.Invoke();yield return null;
  Check(!ButtonNamed("确认并继续").interactable,"Demo preselected manual acknowledgment");
  shot("demo-01-grouped-base-confirmation.png");ButtonNamed("暂不确认").onClick.Invoke();yield return null;
  Check(DemoState(view).execution.completed_state_ids.Length==0,"Dismissing demo manual dialog advanced state");
  ((Button)Get(view,"action")).onClick.Invoke();yield return null;
  GameObject.Find("Demo manual acknowledgment").GetComponent<Toggle>().isOn=true;ButtonNamed("确认并继续").onClick.Invoke();
  yield return BaselineWait(()=>DemoState(view).execution.mode=="operate"&&!(bool)Get(view,"busy"),"Demo did not schedule holder operation");
  ((Button)Get(view,"action")).onClick.Invoke();
  yield return BaselineWait(()=>Get(view,"illustration")!=null&&!(bool)Get(view,"busy"),"Demo did not bind existing AR asset");
  yield return new WaitForSecondsRealtime(.15f);Canvas.ForceUpdateCanvases();
  var graphic=(Manual2AR.Spatial.SpatialAssetGraphic)Get(view,"graphic");
  Check(graphic.VisibleTriangles>0&&graphic.AssetProvenance=="manual2ar-library-v1/u7.holder_slide","Demo AR model was not rendered");
  shot("demo-02-existing-u7-ar.png");
  ((Button)Get(view,"action")).onClick.Invoke();
  yield return BaselineWait(()=>!(bool)Get(view,"busy")&&DemoState(view).execution.mode=="operate","Failed demo check did not keep current operation");
  Check(DemoState(view).execution.completed_state_ids.Length==1&&(string)Get(view,"guidedAction")=="holder.slide","Failed demo check reset progress");
  Check(CanonicalText(((Button)Get(view,"action")).GetComponentInChildren<Text>()).Contains("拍照核验"),"Failed demo check requested AR replay");
  shot("demo-02-failed-check-keeps-step.png");
  ((Dropdown)Get(view,"photos")).value=1;
  yield return BaselineWait(()=>!(bool)Get(view,"busy")&&(string)Get(view,"sceneId")=="holder_ready","Demo photo switch did not complete");
  Check(Get(view,"illustration")==null,"Old animation stayed on a different photograph");
  Check(((string)Get(view,"guidedAction"))=="holder.slide","Photo switch reset the current operation");
  ((Button)Get(view,"action")).onClick.Invoke();
  yield return BaselineWait(()=>DemoState(view).execution.baseline_mode=="ask_manual"&&!(bool)Get(view,"busy"),"Demo did not verify holder result");
  Check(DemoState(view).execution.completed_state_ids.Length==1,"Normal occlusion discarded verified base");
  ((Button)Get(view,"action")).onClick.Invoke();yield return null;
  GameObject.Find("Demo manual acknowledgment").GetComponent<Toggle>().isOn=true;ButtonNamed("确认并继续").onClick.Invoke();
  yield return BaselineWait(()=>DemoState(view).execution.complete&&!(bool)Get(view,"busy"),"Demo failed to complete");
  shot("demo-03-prime-completed.png");yield return new WaitForSecondsRealtime(.1f);shot("demo-03-completed.png");
  Invoke(view,"ResetSession");((InputField)Get(view,"question")).text="安装支架底座";((Dropdown)Get(view,"photos")).value=0;
  yield return BaselineWait(()=>!(bool)Get(view,"busy")&&(string)Get(view,"sceneId")=="base_ready","Demo did not restore base photo");
  ((Button)Get(view,"action")).onClick.Invoke();
  yield return BaselineWait(()=>DemoState(view)!=null&&DemoState(view).execution.baseline_mode=="ask_manual"&&!(bool)Get(view,"busy"),"Base-only demo did not assess");
  ((Button)Get(view,"action")).onClick.Invoke();yield return null;GameObject.Find("Demo manual acknowledgment").GetComponent<Toggle>().isOn=true;ButtonNamed("确认并继续").onClick.Invoke();
  yield return BaselineWait(()=>DemoState(view).execution.complete&&!(bool)Get(view,"busy"),"Base-only demo exceeded requested endpoint");
  Check(DemoState(view).execution.target_node_ids.Length==1,"Base-only target expanded");
  Invoke(view,"ResetSession");((InputField)Get(view,"question")).text="安装料盘支架";((Dropdown)Get(view,"photos")).value=1;
  yield return BaselineWait(()=>!(bool)Get(view,"busy")&&(string)Get(view,"sceneId")=="holder_ready","Installed photo did not load");
  ((Button)Get(view,"action")).onClick.Invoke();
  yield return BaselineWait(()=>DemoState(view)!=null&&DemoState(view).execution.baseline_mode=="request_view"&&!(bool)Get(view,"busy"),"Fresh installed-holder scenario skipped prerequisite uncertainty");
  Check(DemoState(view).execution.completed_state_ids.Length==0,"New demo inherited past manual confirmation");
  shot("demo-04-installed-but-needs-base-evidence.png");
  byte[] historical=(byte[])Get(view,"captured");((Dropdown)Get(view,"modes")).value=1;
  Set(view,"captured",historical);Set(view,"photoSha",new string('0',64));Set(view,"captureVersion",100);Invoke(view,"ShowPhoto",historical);
  ((Button)Get(view,"action")).onClick.Invoke();
  yield return BaselineWait(()=>DemoState(view)!=null&&!(bool)Get(view,"busy"),"Live demo failed request left the interface busy");
  Check(DemoState(view).mode=="live"&&DemoState(view).execution.completed_state_ids.Length==0,"Live failure fell back to scripted progress");
  Check(CanonicalText((Text)Get(view,"phase")).Contains("请求未完成"),"Failed request left a misleading waiting message");
  Invoke(view,"ShowSources");yield return null;
  Check(GameObject.Find("Demo official steps")!=null,"Failed photo check blocked official instructions");
  ButtonNamed("返回当前任务").onClick.Invoke();yield return null;
  Check(CanonicalText((Text)Get(view,"phase")).Contains("请求未完成")&&DemoState(view).execution.completed_state_ids.Length==0,"Browsing instructions changed failed-check progress");
  Check(!((Manual2AR.Spatial.SpatialCamera)Get(view,"cameraOwner")).Ready,"Demo validation opened a physical camera");
  shot("demo-05-real-mode-failure-preserves-progress.png");Invoke(view,"Close");
  yield return BaselineWait(()=>closed,"U7 demo did not return to task list");
  File.WriteAllText(Path.Combine(Application.dataPath,"../Validation/u7-demo.json"),"{\"scripted_mode_explicit\":true,\"composite_goal\":true,\"base_only_endpoint\":true,\"existing_asset_rendered\":true,\"photo_switch_clears_old_overlay\":true,\"manual_acknowledgment_required\":true,\"fresh_session_keeps_occlusion_unknown\":true,\"completed_closed_loop\":true,\"real_model_calls\":0,\"camera_hardware_tested\":false}");
 }

}
