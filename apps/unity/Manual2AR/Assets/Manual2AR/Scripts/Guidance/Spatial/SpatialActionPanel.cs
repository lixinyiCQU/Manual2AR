using System;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UI;
using Manual2AR.VisualGuidance;
namespace Manual2AR.Spatial {
 /// <summary>Edits presentation instances independently of capture, tracking and anchor ownership.</summary>
 public static class SpatialActionPanel {
  public static GameObject Open(Transform parent,MotionParameters source,VisualPresentation presentation,bool rotary,bool hasFrame,Action<MotionParameters> save,Action setup){
   var dialog=AppDialog.Open(parent,"Action management","动画管理",AppDialogSize.Large,null);var shade=(RectTransform)dialog.transform;var panel=dialog.Panel;
   Action close=dialog.Close;AppTheme.Button(panel,"关闭",new Vector2(.05f,.025f),new Vector2(.30f,.10f),close,AppIcon.Close);
   var instances=Array.FindAll(presentation?.instances??new VisualInstance[0],i=>i!=null&&!string.IsNullOrEmpty(i.id));
   if(instances.Length==0){AppTheme.Label(panel,"动画组件尚未就绪。请让定位标记和操作位置入镜后再打开动画管理。",new Vector2(.08f,.35f),new Vector2(.92f,.70f),27);return shade.gameObject;}
   var value=source==null?new MotionParameters():JsonUtility.FromJson<MotionParameters>(JsonUtility.ToJson(source));if(!hasFrame)value.enabled=false;
   var components=new List<ComponentMotion>(Array.FindAll(value.components??new ComponentMotion[0],c=>c!=null&&!string.IsNullOrEmpty(c.id)));
   foreach(var c in components){if(c.rotation_degrees==null||c.rotation_degrees.Length!=3)c.rotation_degrees=new float[3];if(c.offset_mm==null||c.offset_mm.Length!=3)c.offset_mm=new float[3];}
   foreach(var instance in instances)if(!components.Exists(c=>c.id==instance.id))components.Add(new ComponentMotion{id=instance.id});
   value.components=components.ToArray();int selected=0,tab=0;RectTransform content=null;
   AppTheme.Button(panel,"整体移动与旋转",new Vector2(.05f,.74f),new Vector2(.48f,.82f),()=>{close();SpatialMotionPanel.Open(parent,value,rotary,hasFrame,save,setup);},AppIcon.SwitchCamera);
   Action rebuild=null;rebuild=()=>{
    if(content!=null)UnityEngine.Object.Destroy(content.gameObject);
    content=AppTheme.Rect(panel,"Component controls",new Vector2(0,.12f),new Vector2(1,.72f));
    var instance=instances[selected];var component=components.Find(c=>c.id==instance.id);
    var visibility=AppTheme.Button(content,component.visible?"显示组件":"隐藏组件",new Vector2(.05f,.86f),new Vector2(.47f,.98f),()=>{component.visible=!component.visible;rebuild();},AppIcon.Inspect);
    AppTheme.Button(content,component.playing?"自动循环":"静态起始姿态",new Vector2(.53f,.86f),new Vector2(.95f,.98f),()=>{component.playing=!component.playing;rebuild();},AppIcon.SwitchCamera);
    var tabs=AppDropdown.Create(content,"Component properties",new Vector2(.05f,.70f),new Vector2(.95f,.82f),i=>{tab=i;rebuild();});tabs.AddOptions(new List<string>{"模型朝向 · 局部 XYZ","位置与大小 · 工作坐标","播放速度与旋转方向"});tabs.SetValueWithoutNotify(tab);tabs.RefreshShownValue();
    if(tab==0){for(int i=0;i<3;i++){int axis=i;SpatialMotionPanel.Row(content,"绕局部 "+"XYZ"[i],.52f-i*.17f,-180,180,component.rotation_degrees[i],"°",v=>component.rotation_degrees[axis]=Mathf.Round(v));}}
    else if(tab==1){for(int i=0;i<3;i++){int axis=i;SpatialMotionPanel.Row(content,"偏移 "+"XYZ"[i],.54f-i*.14f,-100,100,component.offset_mm[i]," mm",v=>component.offset_mm[axis]=Mathf.Round(v));}SpatialMotionPanel.Row(content,"模型大小",.11f,.25f,3,component.scale,"×",v=>component.scale=v);}
    else{SpatialMotionPanel.Row(content,"播放倍率",.51f,.25f,4,component.speed,"×",v=>component.speed=v);AppTheme.Button(content,component.rotation_sign==0?"旋转方向：跟随整体":component.rotation_sign==1?"旋转方向：顺时针":"旋转方向：逆时针",new Vector2(.05f,.31f),new Vector2(.95f,.44f),()=>{component.rotation_sign=component.rotation_sign==0?1:component.rotation_sign==1?-1:0;rebuild();},AppIcon.SwitchCamera);AppTheme.Label(content,"旋转从工具柄朝作用端看；静态模式停在起始姿态。",new Vector2(.05f,.10f),new Vector2(.95f,.28f),23,AppTheme.Muted);}
   };
   var selector=AppDropdown.Create(panel,"Animation component",new Vector2(.52f,.74f),new Vector2(.95f,.82f),i=>{selected=i;rebuild();});var names=new List<string>();foreach(var instance in instances)names.Add(VisualAssetLibrary.Get(instance.asset_id)?.Definition.label??instance.id);selector.AddOptions(names);selector.RefreshShownValue();rebuild();
   AppTheme.Button(panel,"应用并保存",new Vector2(.40f,.025f),new Vector2(.95f,.10f),()=>{save(value);close();},AppIcon.Check,true);
   return shade.gameObject;
  }
 }
}
