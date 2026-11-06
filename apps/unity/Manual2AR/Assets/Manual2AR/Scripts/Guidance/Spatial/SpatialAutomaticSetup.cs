using System;
using System.Collections;
using UnityEngine;
using UnityEngine.UI;

namespace Manual2AR.Spatial {
 /// <summary>Printed reference, two RGB captures and explicit preview. Never changes installation verdicts.</summary>
 public sealed partial class SpatialGuidanceController {
  string automaticFirstView;int automaticGeneration;Button automaticCapture,automaticSave;Text automaticHint;
  bool automaticBusy,automaticActive;
  void ShowAnchorSetup(){if(plan!=null&&Current.chapter_id=="U7"&&mode=="camera")ShowAutomaticSetup();else ShowManualAnchorSetup();}
  void ShowAutomaticSetup(){
   if(session==null||last==null||changing||checking||locating||automaticBusy){Message("请先启动摄像头并等待当前操作结束");return;}
   CancelAutomatic();var panel=PhotoPanel("空间锚点配置 · 自动配置优先");
   var text=ScrollText(panel,"Automatic setup instructions",new Vector2(.06f,.38f),new Vector2(.94f,.84f),26);
   text.text="1. 首次使用先完成相机标定；已标定的同一镜头和画幅无需重做。\n\n2. 将工作坐标板平放、固定。+X 与打印机横梁正向一致，+Y 指向打印机背面，+Z 向上。\n\n3. 拍清灰色底座和两颗螺丝；按提示换视角拍第二张，系统自动设置作用点和动画。";
   AppTheme.Button(panel,"打印工作坐标板",new Vector2(.06f,.24f),new Vector2(.48f,.35f),()=>Application.OpenURL(origin+Api+"/workboard.pdf"),AppIcon.Save);
   AppTheme.Button(panel,"备份并重新配置",new Vector2(.52f,.24f),new Vector2(.94f,.35f),ConfirmAutomaticReset,AppIcon.Clear);
   AppTheme.Button(panel,"手动配置 / 相机标定",new Vector2(.06f,.07f),new Vector2(.48f,.20f),()=>{ClosePhotoPrompt();ShowManualAnchorSetup();},AppIcon.Inspect);
   AppTheme.Button(panel,"开始自动配置",new Vector2(.52f,.07f),new Vector2(.94f,.20f),()=>{ClosePhotoPrompt();StartAutomatic();},AppIcon.Check,true);
  }
  void ConfirmAutomaticReset(){
   var panel=PhotoPanel("备份旧配置并重新开始",true);
   AppTheme.Label(panel,"将备份并清除这台打印机的作用点、XYZ 和动画微调。\n\n保留相机标定及教学进度。",new Vector2(.07f,.34f),new Vector2(.93f,.80f),27);
   AppTheme.Button(panel,"取消",new Vector2(.06f,.07f),new Vector2(.44f,.25f),ShowAutomaticSetup,AppIcon.Back);
   AppTheme.Button(panel,"备份并清除",new Vector2(.50f,.07f),new Vector2(.94f,.25f),()=>{ClosePhotoPrompt();StartCoroutine(ResetAutomatic());},AppIcon.Check,true);
  }
  IEnumerator ResetAutomatic(){
   if(automaticBusy||session==null)yield break;StopParts();CancelAuthor();CancelAutomatic();int version=epoch;string identity=session.session_id;
   automaticBusy=true;string failure=null;
   yield return Request(Api+"/sessions/"+identity+"/automatic/reset","POST","{\"confirmed\":true}",(raw,error)=>failure=error);
   automaticBusy=false;if(session==null||session.session_id!=identity||version!=epoch)yield break;
   if(failure!=null){Message(failure);yield break;}
   epoch++;last=null;latestReply=null;latestBytes=null;guidedStarted=false;semanticReady=false;ClearGraphics();
   Message("旧配置已备份，相机标定已保留");
  }
  static bool HasMachineReference(MachineFrame value){return value!=null&&!string.IsNullOrEmpty(value.frame_id)&&value.frame_id.Length==32&&value.marker_from_machine!=null&&value.marker_from_machine.Length==16;}
  static bool HasMarkerPose(Pose value){return value!=null&&value.matrix!=null&&value.matrix.Length==16&&value.corners!=null&&value.corners.Length==4;}
  void StartAutomatic(){
   if(last==null||!last.calibrated){Message("请先在手动配置中完成当前画幅的相机标定");return;}
   if(!HasMarkerPose(last.pose)){Message("请让完整坐标板和灰色底座同时入镜");return;}
   if(HasMachineReference(last.machine_frame)){OpenAutomaticCapture();return;}
   var panel=PhotoPanel("确认坐标板摆放方向");
   AppTheme.Label(panel,"坐标板必须平放并固定：\n\n红色 +X：沿打印机横梁，从设备正面看向右。\n绿色 +Y：指向打印机背面。\n蓝色 +Z：垂直桌面向上。\n\n原点采用方形标记中心。请按 100% 打印并量准尺寸；扫描不会自动判断纸张是否与机器对齐。",new Vector2(.06f,.23f),new Vector2(.94f,.83f),27);
   AppTheme.Button(panel,"确认方向，扫描坐标板",new Vector2(.10f,.05f),new Vector2(.90f,.18f),()=>{ClosePhotoPrompt();StartCoroutine(RegisterPrintedReference());},AppIcon.Check,true);
  }
  IEnumerator RegisterPrintedReference(){
   if(session==null||!HasMarkerPose(latestReply?.pose))yield break;
   int version=epoch;string identity=session.session_id;automaticBusy=true;string failure=null;
   yield return Request(Api+"/sessions/"+identity+"/automatic/reference","POST",JsonUtility.ToJson(new PrintedReference{client_frame_id=latestReply.client_frame_id}),(raw,error)=>failure=error);
   automaticBusy=false;if(session==null||session.session_id!=identity||version!=epoch)yield break;
   if(failure!=null){Message(failure);yield break;}
   checkResult.text="坐标板已确认。现在拍摄第一视角，随后横移相机拍第二视角。";OpenAutomaticCapture();
  }
  void OpenAutomaticCapture(){
   StopParts();CancelAuthor();CancelAutomatic();automaticActive=true;setupExplicit=true;SetSetupVisible(false);
   checkResult.text="自动配置：让定位板、灰色底座及两颗螺丝清晰入镜。无需逐点点击。";
   ClosePhotoPrompt();BuildAutomaticSidebar();
  }
  GameObject automaticSidebar;
  void BuildAutomaticSidebar(){
   automaticSidebar=AppTheme.Panel(infoCard,"Automatic capture controls",new Vector2(.02f,.09f),new Vector2(.98f,.99f)).gameObject;
   automaticHint=ScrollText(automaticSidebar.transform,"Automatic capture status",new Vector2(.06f,.30f),new Vector2(.94f,.94f),26);
   automaticHint.text="拍清灰色底座与两颗螺丝，定位板同时入镜。\n\n第一张定位后，保持打印机和板不动，横移镜头约 15–25 厘米再拍第二张。\n\n无需点击螺丝或路径端点。";
   automaticCapture=AppTheme.Button(automaticSidebar.transform,"拍第一视角",new Vector2(.06f,.15f),new Vector2(.94f,.27f),()=>StartCoroutine(CaptureAutomatic()),AppIcon.Camera,true);
   AppTheme.Button(automaticSidebar.transform,"退出自动配置",new Vector2(.06f,.015f),new Vector2(.94f,.12f),CancelAutomatic,AppIcon.Close);
  }
  bool AutomaticCurrent(int generation,string identity,int version){return automaticActive&&!closed&&automaticGeneration==generation&&epoch==version&&session!=null&&session.session_id==identity;}
  IEnumerator CaptureAutomatic(){
   if(automaticBusy||!automaticActive||!HasMarkerPose(latestReply?.pose)||session==null){if(automaticHint!=null)automaticHint.text="请让坐标板完整入镜后再拍摄。";yield break;}
   int generation=automaticGeneration,version=epoch;string identity=session.session_id;var sent=latestReply;var raw=latestBytes;
   automaticBusy=true;locating=true;automaticCapture.interactable=false;frozen=true;HideGuidance();RenderFrame(raw,sent);
   automaticHint.text="正在定位底座并放大识别螺丝；本步骤不调用 GPU。";
   AutomaticView result=null;string failure=null;
   yield return Request(Api+"/sessions/"+identity+"/automatic/views","POST",JsonUtility.ToJson(new Verify{action_id=Current.action_id,target_id=TargetId,client_frame_id=sent.client_frame_id}),(text,error)=>{failure=error;if(error==null)result=JsonUtility.FromJson<AutomaticView>(text);},150);
   if(!AutomaticCurrent(generation,identity,version))yield break;
   locating=false;automaticBusy=false;automaticCapture.interactable=true;
   if(failure!=null||result==null||result.session_id!=identity||result.client_frame_id!=sent.client_frame_id||result.source_sha256!=sent.source_sha256||result.action_id!=Current.action_id){frozen=false;automaticHint.text=failure??"照片身份不匹配，请重新拍摄。";yield break;}
   if(string.IsNullOrEmpty(automaticFirstView)){
    automaticFirstView=result.view_id;frozen=false;automaticCapture.GetComponentInChildren<Text>().text="拍第二视角";
    automaticHint.text=result.message+"\n\n保持同一灰色底座清晰可见，不移动机器或定位板。";yield break;
   }
   automaticBusy=true;automaticCapture.interactable=false;
   AutomaticCandidate value=null;
   yield return Request(Api+"/sessions/"+identity+"/automatic/candidates","POST",JsonUtility.ToJson(new AutomaticPair{action_id=Current.action_id,first_view=automaticFirstView,second_view=result.view_id,second_frame=sent.client_frame_id}),(text,error)=>{failure=error;if(error==null)value=JsonUtility.FromJson<AutomaticCandidate>(text);},20);
   if(!AutomaticCurrent(generation,identity,version))yield break;
   automaticBusy=false;automaticCapture.interactable=true;
   if(failure!=null||value==null||value.session_id!=identity||value.client_frame_id!=sent.client_frame_id||value.source_sha256!=sent.source_sha256){frozen=false;automaticFirstView=null;automaticCapture.GetComponentInChildren<Text>().text="重新拍第一视角";automaticHint.text=(failure??"候选与照片不匹配")+"\n请重新拍摄两个视角；旧配置保持不变。";yield break;}
   RenderFrame(raw,sent);overlay.Clear();foreach(var point in value.points??new AutomaticPoint[0])overlay.picks.Add(point.point);overlay.SetVerticesDirty();
   automaticHint.text="已生成 "+value.target_count+" 处作用点。\n\n核对黄色十字是否对准螺丝或可见边缘。\n\n"+(value.slide_illustrative?"滑入动画将使用两颗螺丝之间的底座参考点，仅示意上下方向，不代表插槽位置和实际行程。":value.slide_ready?"滑入动画位置也已准备。":"滑入动画尚未定位，可另行补充配置。")+"\n\n保存不会判定安装完成。";
   automaticCapture.GetComponentInChildren<Text>().text="换角度重新拍摄";automaticCapture.onClick.RemoveAllListeners();automaticCapture.onClick.AddListener(()=>{automaticFirstView=null;if(automaticSave!=null){automaticSave.gameObject.SetActive(false);Destroy(automaticSave.gameObject);}AppWorkspace.Place((RectTransform)automaticHint.transform.parent.parent.parent,.06f,.30f,.94f,.94f);automaticCapture.onClick.RemoveAllListeners();automaticCapture.onClick.AddListener(()=>StartCoroutine(CaptureAutomatic()));automaticCapture.GetComponentInChildren<Text>().text="拍第一视角";frozen=false;overlay.Clear();});
   if(automaticSave!=null)Destroy(automaticSave.gameObject);automaticSave=AppTheme.Button(automaticSidebar.transform,"核对无误，保存",new Vector2(.06f,.29f),new Vector2(.94f,.41f),()=>StartCoroutine(SaveAutomatic(value)),AppIcon.Check,true);
   AppWorkspace.Place((RectTransform)automaticHint.transform.parent.parent.parent,.06f,.44f,.94f,.94f);
  }
  IEnumerator SaveAutomatic(AutomaticCandidate value){
   if(automaticBusy||session==null)yield break;automaticBusy=true;int generation=automaticGeneration,version=epoch;string identity=session.session_id;string failure=null;
   yield return Request(Api+"/sessions/"+identity+"/automatic/confirm","POST",JsonUtility.ToJson(new Save{candidate_id=value.candidate_id}),(text,error)=>failure=error);
   if(!AutomaticCurrent(generation,identity,version))yield break;automaticBusy=false;
   if(failure!=null){automaticHint.text=failure;yield break;}
   CancelAutomatic();setupExplicit=false;SetSetupVisible(false);guidedStarted=false;semanticReady=false;Message("作用点已保存，请在操作位置点击开始");
  }
  void CancelAutomatic(){if(automaticActive){setupExplicit=false;SetSetupVisible(false);}automaticGeneration++;automaticBusy=false;automaticActive=false;automaticFirstView=null;if(automaticSidebar!=null){automaticSidebar.SetActive(false);Destroy(automaticSidebar);}automaticSidebar=null;automaticSave=null;frozen=false;locating=false;if(overlay!=null)overlay.Clear();}
 }
}
