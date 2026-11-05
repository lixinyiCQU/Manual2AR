using System;
using System.Text;
using UnityEngine;
using UnityEngine.UI;

namespace Manual2AR {
 public static class AppTheme {
  public static readonly Color Background=new Color(.018f,.04f,.08f),PanelBackground=new Color(.025f,.075f,.12f),TargetCyan=new Color(.13f,.83f,.92f),Muted=new Color(.63f,.74f,.83f);
  public static readonly Color SuccessGreen=new Color(.22f,.9f,.66f),ErrorRed=new Color(1,.34f,.3f),ButtonBackground=new Color(.045f,.16f,.24f);
  public const int TitleSize=32,BodySize=26,CaptionSize=22;
  public const float ButtonHeight=64;
  public static readonly Color WarningAmber=new Color(1,.75f,.35f);
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
  public static Button Button(Transform parent,string value,Vector2 min,Vector2 max,Action click,AppIcon? symbol=null,bool primary=false){
   var r=Panel(parent,value,min,max);r.GetComponent<Image>().color=primary?new Color(.045f,.43f,.56f):ButtonBackground;
   var b=r.gameObject.AddComponent<Button>();b.targetGraphic=r.GetComponent<Image>();b.onClick.AddListener(()=>click());
   if(symbol.HasValue){var icon=Rect(r,"Icon",new Vector2(.045f,.24f),new Vector2(.18f,.76f)).gameObject.AddComponent<AppIconGraphic>();icon.symbol=symbol.Value;icon.raycastTarget=false;icon.color=Color.white;}
   var text=Label(r,value,new Vector2(symbol.HasValue?.21f:.04f,.04f),new Vector2(.96f,.96f),BodySize);text.alignment=TextAnchor.MiddleCenter;Skin(b);return b;
  }
  public static void Skin(Button button){
   var colors=button.colors;colors.highlightedColor=new Color(.83f,.96f,1);colors.pressedColor=new Color(.64f,.83f,.9f);colors.disabledColor=new Color(.55f,.62f,.68f,.55f);colors.fadeDuration=.12f;button.colors=colors;
   foreach(var text in button.GetComponentsInChildren<Text>(true)){text.font=Font;text.fontSize=Mathf.Max(CaptionSize,text.fontSize);text.resizeTextForBestFit=true;text.resizeTextMinSize=CaptionSize;text.resizeTextMaxSize=text.fontSize;text.lineSpacing=1.18f;}
  }
 }

 public interface IAppModule {System.Collections.IEnumerator ReleaseModule();}
}
