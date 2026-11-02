using System;
using System.Collections.Generic;
using System.Text;
using UnityEngine;
using UnityEngine.UI;

namespace Manual2AR {
 public static class AppTheme {
  public static readonly Color Background=new Color(.018f,.04f,.08f),PanelBackground=new Color(.025f,.075f,.12f),TargetCyan=new Color(.13f,.83f,.92f),Muted=new Color(.63f,.74f,.83f);
  public static readonly Color SuccessGreen=new Color(.22f,.9f,.66f),ErrorRed=new Color(1,.34f,.3f),ButtonBackground=new Color(.045f,.16f,.24f);
  static Font font;
  public static Font Font {get {if(font==null)font=Resources.Load<Font>("Fonts/NotoSansCJKsc-Regular");if(font==null)font=Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");return font;}}
  public static RectTransform Rect(Transform parent,string name,Vector2 min,Vector2 max){var o=new GameObject(name,typeof(RectTransform));o.transform.SetParent(parent,false);var r=(RectTransform)o.transform;r.anchorMin=min;r.anchorMax=max;r.offsetMin=r.offsetMax=Vector2.zero;return r;}
  public static string Readable(string value){
   if(string.IsNullOrEmpty(value))return value;
   value=value.Replace("A1 mini","A1"+(char)0xa0+"mini").Replace("AMS lite","AMS"+(char)0xa0+"lite");
   var output=new StringBuilder(value.Length*2);
   for(int i=0;i<value.Length;i++){output.Append(value[i]);if(i+1<value.Length&&value[i]>=0x3400&&value[i]<=0x9fff&&value[i+1]>=0x3400&&value[i+1]<=0x9fff)output.Append((char)0x200b);}
   return output.ToString();
  }
  public static Text Label(Transform parent,string value,Vector2 min,Vector2 max,int size=26,Color? color=null){var r=Rect(parent,"Text",min,max);var t=r.gameObject.AddComponent<Text>();t.font=Font;t.fontSize=size;t.text=Readable(value);t.color=color??Color.white;t.supportRichText=false;t.raycastTarget=false;t.alignment=TextAnchor.MiddleLeft;t.horizontalOverflow=HorizontalWrapMode.Wrap;t.verticalOverflow=VerticalWrapMode.Truncate;t.lineSpacing=1.12f;return t;}
  public static RectTransform Panel(Transform parent,string name,Vector2 min,Vector2 max){var r=Rect(parent,name,min,max);var g=r.gameObject.AddComponent<AppRoundedImage>();g.color=PanelBackground;g.radius=20;return r;}
  public static Button Button(Transform parent,string value,Vector2 min,Vector2 max,Action click,AppIcon symbol=AppIcon.Info,bool primary=false){
   var r=Panel(parent,value,min,max);r.GetComponent<Image>().color=primary?new Color(.045f,.43f,.56f):ButtonBackground;
   var b=r.gameObject.AddComponent<Button>();b.targetGraphic=r.GetComponent<Image>();b.onClick.AddListener(()=>click());
   var icon=Rect(r,"Icon",new Vector2(.045f,.22f),new Vector2(.20f,.78f)).gameObject.AddComponent<AppIconGraphic>();icon.symbol=symbol;icon.raycastTarget=false;icon.color=Color.white;
   var text=Label(r,value,new Vector2(.23f,.04f),new Vector2(.96f,.96f),27);text.alignment=TextAnchor.MiddleCenter;Skin(b);return b;
  }
  public static void Skin(Button button){
   var colors=button.colors;colors.highlightedColor=new Color(.83f,.96f,1);colors.pressedColor=new Color(.64f,.83f,.9f);colors.disabledColor=new Color(.55f,.62f,.68f,.55f);colors.fadeDuration=.12f;button.colors=colors;
   foreach(var text in button.GetComponentsInChildren<Text>(true)){text.font=Font;text.fontStyle=FontStyle.Normal;text.fontSize=Mathf.Max(21,text.fontSize);text.resizeTextForBestFit=true;text.resizeTextMinSize=20;text.resizeTextMaxSize=text.fontSize;text.lineSpacing=1.12f;}
   var label=button.GetComponentInChildren<Text>(true);
   if(label==null||label.transform.parent!=button.transform||button.GetComponentInChildren<AppIconGraphic>(true)!=null)return;
   string value=label.text;AppIcon? icon=null;
   if(value.Contains("保存"))icon=AppIcon.Save;else if(value.Contains("清除"))icon=AppIcon.Clear;else if(value.Contains("识别")||value.Contains("检查"))icon=AppIcon.Inspect;
   else if(value.Contains("刷新")||value.Contains("重新连接")||value.Contains("切换摄像头"))icon=AppIcon.SwitchCamera;else if(value.Contains("打开输入")||value.Contains("启动摄像"))icon=AppIcon.Camera;
   else if(value.Contains("返回任务"))icon=AppIcon.Home;else if(value.Contains("总览")||value.Contains("整机介绍"))icon=AppIcon.Info;
   if(!icon.HasValue)return;
   var rect=(RectTransform)button.transform;var graphic=Rect(rect,"Action Icon",new Vector2(.055f,.24f),new Vector2(.18f,.76f)).gameObject.AddComponent<AppIconGraphic>();graphic.symbol=icon.Value;graphic.color=Color.white;graphic.raycastTarget=false;
   label.rectTransform.anchorMin=new Vector2(.23f,label.rectTransform.anchorMin.y);
  }
  public static void Attach(RectTransform root){if(root.GetComponent<AppThemeRefresh>()==null)root.gameObject.AddComponent<AppThemeRefresh>();}
 }
 public sealed class AppThemeRefresh:MonoBehaviour {
  readonly HashSet<int> styled=new HashSet<int>();float next;
  void LateUpdate(){if(Time.unscaledTime<next)return;next=Time.unscaledTime+.5f;
   foreach(var b in GetComponentsInChildren<Button>(true))if(styled.Add(b.GetInstanceID()))AppTheme.Skin(b);
  }
 }
 public interface IAppModule {System.Collections.IEnumerator ReleaseModule();}
}
