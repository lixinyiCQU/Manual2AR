using System;
using UnityEngine;
using UnityEngine.UI;
namespace Manual2AR.Spatial {
 public static class SpatialOrientationPanel {
  public static GameObject Open(Transform parent,Orientation settings,Action<Orientation> save){
   var shade=AppTheme.Rect(parent,"XYZ orientation modal",Vector2.zero,Vector2.one);var canvas=shade.gameObject.AddComponent<Canvas>();canvas.overrideSorting=true;canvas.sortingOrder=610;shade.gameObject.AddComponent<GraphicRaycaster>();shade.gameObject.AddComponent<Image>().color=new Color(0,0,0,.8f);AppModalBackdrop.Attach(shade.gameObject);
   var panel=AppTheme.Panel(shade,"XYZ orientation",new Vector2(.20f,.23f),new Vector2(.80f,.80f));
   var current=new Orientation{rotation_degrees=(float[])settings.rotation_degrees.Clone(),rotation_sign=settings.rotation_sign};
   AppTheme.Label(panel,"XYZ 操作坐标与模型朝向",new Vector2(.04f,.88f),new Vector2(.96f,.98f),28,AppTheme.TargetCyan);
   AppTheme.Label(panel,"原点沿用已确认的作用点；角度只调整示意模型，不移动实物坐标。",new Vector2(.04f,.75f),new Vector2(.96f,.87f),22);
   var labels=new Text[3];for(int i=0;i<3;i++){int axis=i;float y=.60f-i*.145f;labels[i]=AppTheme.Label(panel,"",new Vector2(.06f,y),new Vector2(.44f,y+.11f),25);Action refresh=()=>labels[axis].text="XYZ"[axis]+"  "+current.rotation_degrees[axis].ToString("0")+"°";refresh();AppTheme.Button(panel,"−15°",new Vector2(.49f,y),new Vector2(.69f,y+.11f),()=>{current.rotation_degrees[axis]=Mathf.Clamp(current.rotation_degrees[axis]-15,-180,180);refresh();});AppTheme.Button(panel,"+15°",new Vector2(.73f,y),new Vector2(.93f,y+.11f),()=>{current.rotation_degrees[axis]=Mathf.Clamp(current.rotation_degrees[axis]+15,-180,180);refresh();});}
   Button direction=null;Action caption=()=>direction.GetComponentInChildren<Text>().text=current.rotation_sign==1?"旋转：顺时针（从工具朝向作用端看）":"旋转：反向示意";
   direction=AppTheme.Button(panel,"",new Vector2(.05f,.17f),new Vector2(.95f,.27f),()=>{current.rotation_sign*=-1;caption();},AppIcon.SwitchCamera);caption();
   AppTheme.Button(panel,"取消",new Vector2(.05f,.025f),new Vector2(.30f,.13f),()=>UnityEngine.Object.Destroy(shade.gameObject),AppIcon.Close);
   AppTheme.Button(panel,"重置",new Vector2(.35f,.025f),new Vector2(.60f,.13f),()=>{current.rotation_degrees=new float[3];current.rotation_sign=1;for(int i=0;i<3;i++)labels[i].text="XYZ"[i]+"  0°";caption();});
   AppTheme.Button(panel,"应用并保存",new Vector2(.65f,.025f),new Vector2(.95f,.13f),()=>{save(current);UnityEngine.Object.Destroy(shade.gameObject);},AppIcon.Check,true);return shade.gameObject;
  }
 }
}
