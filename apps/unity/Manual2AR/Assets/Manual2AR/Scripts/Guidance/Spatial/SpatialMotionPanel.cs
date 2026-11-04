using System;
using UnityEngine;
using UnityEngine.UI;
namespace Manual2AR.Spatial {
 /// <summary>Explicit motion parameters in a registered printer frame, no automatic pose estimation.</summary>
 public static class SpatialMotionPanel {
  public static GameObject Open(Transform parent,MotionParameters source,bool rotary,bool hasFrame,Action<MotionParameters> save,Action setup){
   var shade=AppTheme.Rect(parent,"Teaching motion modal",Vector2.zero,Vector2.one);var canvas=shade.gameObject.AddComponent<Canvas>();canvas.overrideSorting=true;canvas.sortingOrder=610;shade.gameObject.AddComponent<GraphicRaycaster>();shade.gameObject.AddComponent<Image>().color=new Color(0,0,0,.8f);AppModalBackdrop.Attach(shade.gameObject);
   var panel=AppTheme.Panel(shade,"Teaching motion",new Vector2(.18f,.16f),new Vector2(.82f,.86f));
   var value=JsonUtility.FromJson<MotionParameters>(JsonUtility.ToJson(source));
   AppTheme.Label(panel,"动作参数 · 打印机工作坐标",new Vector2(.04f,.90f),new Vector2(.96f,.99f),29,AppTheme.TargetCyan);
   AppTheme.Label(panel,hasFrame?"机架 O / XYZ 已固定；同一动作共用参数。":"尚未建立打印机坐标；两点模式沿用原设置。",new Vector2(.05f,.82f),new Vector2(.95f,.90f),23,AppTheme.Muted);
   Button enable=null;Action refresh=()=>enable.GetComponentInChildren<Text>().text=value.enabled?"坐标模式：打印机 XYZ":"坐标模式：原有两点方向";
   enable=AppTheme.Button(panel,"",new Vector2(.05f,.73f),new Vector2(.64f,.81f),()=>{value.enabled=!value.enabled;refresh();},AppIcon.Inspect);refresh();
   AppTheme.Button(panel,"建立坐标系",new Vector2(.68f,.73f),new Vector2(.95f,.81f),()=>{UnityEngine.Object.Destroy(shade.gameObject);setup();},AppIcon.Inspect);
   AppTheme.Label(panel,rotary?"工具作用轴":"移动轴",new Vector2(.05f,.61f),new Vector2(.30f,.70f),25);
   var axis=AppDropdown.Create(panel,"Motion axis",new Vector2(.32f,.61f),new Vector2(.58f,.70f),i=>value.axis="XYZ"[i].ToString());axis.AddOptions(new System.Collections.Generic.List<string>{"X","Y","Z"});axis.SetValueWithoutNotify(Mathf.Max(0,"XYZ".IndexOf(value.axis)));axis.RefreshShownValue();
   var sign=AppDropdown.Create(panel,"Axis direction",new Vector2(.64f,.61f),new Vector2(.95f,.70f),i=>value.direction=i==0?1:-1);sign.AddOptions(new System.Collections.Generic.List<string>{"正向 +","反向 −"});sign.SetValueWithoutNotify(value.direction==1?0:1);sign.RefreshShownValue();
   Row(panel,rotary?"工具示意轴长":"移动距离",.49f,8,200,value.distance_mm," mm",v=>value.distance_mm=Mathf.Round(v));
   Row(panel,"循环周期",.37f,.5f,5,value.duration_seconds," s",v=>value.duration_seconds=Mathf.Round(v*10)/10);
   if(rotary){Row(panel,"每轮旋转角度",.25f,0,360,value.rotation_degrees,"°",v=>value.rotation_degrees=Mathf.Round(v));Button direction=null;direction=AppTheme.Button(panel,value.rotation_sign==1?"拧紧方向：顺时针（沿工具朝作用端看）":"反向旋转示意",new Vector2(.05f,.15f),new Vector2(.95f,.23f),()=>{value.rotation_sign*=-1;direction.GetComponentInChildren<Text>().text=value.rotation_sign==1?"拧紧方向：顺时针（沿工具朝作用端看）":"反向旋转示意";},AppIcon.SwitchCamera);}
   else AppTheme.Label(panel,"按选定轴靠近已有终点；距离只表示教学动作，不用于测量或控制打印机。",new Vector2(.05f,.16f),new Vector2(.95f,.31f),23,AppTheme.Muted);
   AppTheme.Button(panel,"取消",new Vector2(.05f,.025f),new Vector2(.30f,.11f),()=>UnityEngine.Object.Destroy(shade.gameObject),AppIcon.Close);
   var apply=AppTheme.Button(panel,"应用并保存",new Vector2(.40f,.025f),new Vector2(.95f,.11f),()=>{if(value.enabled&&!hasFrame)return;save(value);UnityEngine.Object.Destroy(shade.gameObject);},AppIcon.Check,true);
   // Recheck mode each frame without coupling the panel to camera or inference state.
   var guard=shade.gameObject.AddComponent<MotionApplyGuard>();guard.button=apply;guard.Allowed=()=>!value.enabled||hasFrame;
   return shade.gameObject;
  }
  public static void Row(Transform panel,string title,float y,float min,float max,float current,string unit,Action<float> change){
   var label=AppTheme.Label(panel,"",new Vector2(.05f,y),new Vector2(.46f,y+.09f),24);Action<float> update=v=>{change(v);label.text=title+"  "+v.ToString(unit==" s"||unit=="×"?"0.0":"0")+unit;};
   var area=AppTheme.Rect(panel,title,new Vector2(.49f,y+.015f),new Vector2(.94f,y+.075f));var slider=area.gameObject.AddComponent<Slider>();
   var bg=AppTheme.Panel(area,"Track",new Vector2(0,.4f),new Vector2(1,.6f));bg.GetComponent<Image>().color=AppTheme.ButtonBackground;
   var thumb=AppTheme.Panel(area,"Handle",new Vector2(0,.12f),new Vector2(0,.88f));thumb.sizeDelta=new Vector2(20,0);thumb.GetComponent<Image>().color=AppTheme.TargetCyan;slider.handleRect=thumb;slider.targetGraphic=thumb.GetComponent<Image>();slider.minValue=min;slider.maxValue=max;slider.wholeNumbers=unit!=" s"&&unit!="×";slider.SetValueWithoutNotify(current);slider.onValueChanged.AddListener(v=>update(v));update(current);
  }
 }
 public sealed class MotionApplyGuard:MonoBehaviour {public Button button;public Func<bool> Allowed;void Update(){if(button!=null)button.interactable=Allowed!=null&&Allowed();}}
}
