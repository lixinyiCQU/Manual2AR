using UnityEngine;
using UnityEngine.UI;

namespace Manual2AR {
 public static class AppContent {
  public static RectTransform Scroll(Transform parent,string name,Vector2 min,Vector2 max){
   var area=AppTheme.Rect(parent,name,min,max);area.gameObject.AddComponent<Image>().color=Color.clear;
   var scroll=area.gameObject.AddComponent<ScrollRect>();scroll.horizontal=false;scroll.scrollSensitivity=40;scroll.movementType=ScrollRect.MovementType.Clamped;
   var viewport=AppTheme.Rect(area,"Viewport",Vector2.zero,new Vector2(.975f,1));viewport.gameObject.AddComponent<RectMask2D>();
   var content=AppTheme.Rect(viewport,"Content",new Vector2(0,1),Vector2.one);content.pivot=new Vector2(.5f,1);
   var layout=content.gameObject.AddComponent<VerticalLayoutGroup>();layout.childControlHeight=layout.childControlWidth=true;layout.childForceExpandHeight=false;layout.spacing=24;layout.padding=new RectOffset(12,18,12,24);
   content.gameObject.AddComponent<ContentSizeFitter>().verticalFit=ContentSizeFitter.FitMode.PreferredSize;
   var track=AppTheme.Rect(area,"Scrollbar",new Vector2(.986f,.015f),new Vector2(1,.985f));track.gameObject.AddComponent<AppRoundedImage>().color=AppTheme.ButtonBackground;
   var handle=AppTheme.Rect(track,"Handle",Vector2.zero,Vector2.one);var graphic=handle.gameObject.AddComponent<AppRoundedImage>();graphic.color=AppTheme.TargetCyan;
   var bar=track.gameObject.AddComponent<Scrollbar>();bar.direction=Scrollbar.Direction.BottomToTop;bar.handleRect=handle;bar.targetGraphic=graphic;
   scroll.verticalScrollbar=bar;scroll.verticalScrollbarVisibility=ScrollRect.ScrollbarVisibility.AutoHide;scroll.viewport=viewport;scroll.content=content;return content;
  }
  public static Text Paragraph(Transform parent,string value,int size=AppTheme.BodySize,Color? color=null){
   var text=AppTheme.Label(parent,value,Vector2.zero,Vector2.one,size,color);text.name="Paragraph";text.verticalOverflow=VerticalWrapMode.Overflow;text.alignment=TextAnchor.UpperLeft;text.lineSpacing=1.3f;
   text.gameObject.AddComponent<LayoutElement>().minHeight=size*1.3f;AppReadableText.Attach(text);return text;
  }
 }
}
