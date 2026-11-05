using System;
using UnityEngine;
using UnityEngine.UI;

namespace Manual2AR {
 /// <summary>Shared task catalog layout for teaching and inspection.</summary>
 public sealed class AppTaskMenu {
  public sealed class Card {public Button Button;public RawImage Image;}
  public RectTransform Root {get;private set;}
  public Text Status {get;private set;}
  RectTransform list,row;int count;
  public static AppTaskMenu Create(Transform parent,string name,string title,string subtitle){
   var view=new AppTaskMenu();view.Root=AppTheme.Rect(parent,name,Vector2.zero,Vector2.one);view.Root.gameObject.AddComponent<Image>().color=AppTheme.Background;
   AppTheme.Label(view.Root,title,new Vector2(.05f,.90f),new Vector2(.76f,.98f),AppTheme.TitleSize);
   AppTheme.Label(view.Root,subtitle,new Vector2(.05f,.82f),new Vector2(.67f,.90f),AppTheme.BodySize,AppTheme.Muted);
   var area=AppTheme.Rect(view.Root,"Task List",new Vector2(.05f,.15f),new Vector2(.95f,.80f));var scroll=area.gameObject.AddComponent<ScrollRect>();scroll.horizontal=false;scroll.movementType=ScrollRect.MovementType.Clamped;scroll.scrollSensitivity=40;
   var viewport=AppTheme.Rect(area,"Viewport",Vector2.zero,new Vector2(.975f,1));viewport.gameObject.AddComponent<RectMask2D>();
   view.list=AppTheme.Rect(viewport,"Cards",new Vector2(0,1),Vector2.one);view.list.pivot=new Vector2(.5f,1);
   var layout=view.list.gameObject.AddComponent<VerticalLayoutGroup>();layout.spacing=24;layout.padding=new RectOffset(3,3,3,12);layout.childForceExpandHeight=false;layout.childControlHeight=true;
   var track=AppTheme.Rect(area,"Vertical Scrollbar",new Vector2(.986f,0),Vector2.one);track.gameObject.AddComponent<AppRoundedImage>().color=AppTheme.ButtonBackground;var bar=track.gameObject.AddComponent<Scrollbar>();bar.direction=Scrollbar.Direction.BottomToTop;
   var handle=AppTheme.Rect(track,"Handle",Vector2.zero,Vector2.one);var handleImage=handle.gameObject.AddComponent<AppRoundedImage>();handleImage.color=AppTheme.TargetCyan;bar.handleRect=handle;bar.targetGraphic=handleImage;scroll.verticalScrollbar=bar;scroll.verticalScrollbarVisibility=ScrollRect.ScrollbarVisibility.AutoHide;
   view.list.gameObject.AddComponent<ContentSizeFitter>().verticalFit=ContentSizeFitter.FitMode.PreferredSize;scroll.viewport=viewport;scroll.content=view.list;
   view.Status=AppTheme.Label(view.Root,"正在读取任务…",new Vector2(.05f,.045f),new Vector2(.95f,.115f),23,AppTheme.Muted);return view;
  }
  public void Clear(){foreach(Transform child in list){child.gameObject.SetActive(false);UnityEngine.Object.Destroy(child.gameObject);}count=0;row=null;}
  public Card Add(string id,string title,string description,bool available,Action action){
   if(count%2==0){row=AppTheme.Rect(list,"Task Row "+count/2,Vector2.zero,Vector2.one);row.gameObject.AddComponent<LayoutElement>().preferredHeight=228;}
   float left=count%2==0?0:.515f;count++;
   var card=AppTheme.Panel(row,id,new Vector2(left,0),new Vector2(left+.485f,1));
   var button=card.gameObject.AddComponent<Button>();button.targetGraphic=card.GetComponent<Image>();button.interactable=available;button.onClick.AddListener(()=>action());AppTheme.Skin(button);
   var media=AppTheme.Panel(card,"Task Image",new Vector2(.03f,.14f),new Vector2(.30f,.86f));media.GetComponent<Image>().color=AppTheme.ButtonBackground;
   var icon=AppTheme.Rect(media,"Task Symbol",new Vector2(.28f,.24f),new Vector2(.72f,.76f)).gameObject.AddComponent<AppIconGraphic>();icon.symbol=AppIcon.Inspect;icon.raycastTarget=false;icon.color=available?AppTheme.TargetCyan:AppTheme.Muted;
   var image=AppTheme.Rect(media,"Official Thumbnail",Vector2.zero,Vector2.one).gameObject.AddComponent<RawImage>();image.raycastTarget=false;image.color=Color.clear;
   image.gameObject.AddComponent<AspectRatioFitter>().aspectMode=AspectRatioFitter.AspectMode.FitInParent;
   AppTheme.Label(card,title,new Vector2(.34f,.60f),new Vector2(.96f,.90f),29,available?AppTheme.TargetCyan:AppTheme.Muted);
   AppTheme.Label(card,description,new Vector2(.34f,.19f),new Vector2(.96f,.60f),23,available?Color.white:AppTheme.Muted);
   if(!available)AppTheme.Label(card,"即将开放",new Vector2(.34f,.035f),new Vector2(.96f,.18f),20,AppTheme.Muted);
   return new Card{Button=button,Image=image};
  }
 }
}
