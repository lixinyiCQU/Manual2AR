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
}
