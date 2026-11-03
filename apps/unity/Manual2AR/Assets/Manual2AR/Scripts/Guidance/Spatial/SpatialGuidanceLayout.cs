using UnityEngine;
using UnityEngine.UI;

namespace Manual2AR.Spatial {
 /// <summary>Teaching layout, independent of camera pose, inference and animation.</summary>
 public sealed partial class SpatialGuidanceController {
  void Build(){
   var canvas=new GameObject("Unboxing Spatial View",typeof(RectTransform),typeof(Canvas),typeof(CanvasScaler),typeof(GraphicRaycaster));canvas.transform.SetParent(transform,false);
   canvas.GetComponent<Canvas>().renderMode=RenderMode.ScreenSpaceOverlay;canvas.GetComponent<Canvas>().sortingOrder=200;
   var scaler=canvas.GetComponent<CanvasScaler>();scaler.uiScaleMode=CanvasScaler.ScaleMode.ScaleWithScreenSize;scaler.referenceResolution=new Vector2(1920,1080);scaler.matchWidthOrHeight=.5f;
   root=canvas.GetComponent<RectTransform>();root.gameObject.AddComponent<AppRoundedImage>().color=AppTheme.Background;
   title=AppTheme.Label(root,"开箱 · 空间指导",new Vector2(.025f,.94f),new Vector2(.76f,.995f),32);
   modeLabel=AppTheme.Label(root,"连接摄像头后开始指导",new Vector2(.025f,.90f),new Vector2(.76f,.94f),20,AppTheme.Muted);
   var controls=AppTheme.Panel(root,"Step and camera controls",new Vector2(.025f,.815f),new Vector2(.975f,.885f));
   AppTheme.Label(controls,"步骤",new Vector2(.015f,.10f),new Vector2(.075f,.90f),22,AppTheme.Muted);
   actionsDropdown=AppDropdown.Create(controls,"Action selector",new Vector2(.08f,.12f),new Vector2(.44f,.88f),index=>{if(index<tabActions.Count)Select(tabActions[index]);});
   targetSelector=AppTheme.Rect(controls,"Target selector",new Vector2(.46f,.12f),new Vector2(.71f,.88f));
   targetsDropdown=AppDropdown.Create(targetSelector,"Operation point",Vector2.zero,Vector2.one,SelectTarget);
   AppTheme.Button(controls,"启动摄像头",new Vector2(.73f,.12f),new Vector2(.86f,.88f),()=>StartCoroutine(BeginSession("camera",false)),AppIcon.Camera,true);
   AppTheme.Button(controls,"切换镜头",new Vector2(.875f,.12f),new Vector2(.99f,.88f),()=>{cameraIndex++;StartCoroutine(BeginSession("camera",false));},AppIcon.SwitchCamera);
   var cameraPanel=AppTheme.Panel(root,"Spatial Camera",new Vector2(.025f,.15f),new Vector2(.64f,.79f));cameraPanel.gameObject.AddComponent<RectMask2D>();
   viewport=AppTheme.Rect(cameraPanel,"Matched frame viewport",Vector2.zero,Vector2.one);var fitter=viewport.gameObject.AddComponent<AspectRatioFitter>();fitter.aspectMode=AspectRatioFitter.AspectMode.FitInParent;fitter.aspectRatio=4f/3;
   image=viewport.gameObject.AddComponent<RawImage>();image.raycastTarget=false;image.color=AppTheme.PanelBackground;
   assetGraphic=AppTheme.Rect(viewport,"Projected guidance assets",Vector2.zero,Vector2.one).gameObject.AddComponent<SpatialAssetGraphic>();assetGraphic.raycastTarget=false;
   overlay=AppTheme.Rect(viewport,"Metric guidance",Vector2.zero,Vector2.one).gameObject.AddComponent<SpatialOverlay>();overlay.Selected+=OnPoint;
   callout=new SpatialCallout(overlay);pickLabels=new SpatialPickLabels(overlay.transform);
   var card=AppTheme.Panel(root,"Step instructions and feedback",new Vector2(.66f,.15f),new Vector2(.975f,.79f));
   instruction=ScrollText(card,"Operation instructions",new Vector2(.04f,.815f),new Vector2(.96f,.97f),24);instruction.text="正在读取步骤…";
   authorHelp=AppTheme.Label(card,"",new Vector2(.04f,.68f),new Vector2(.96f,.80f),21,AppTheme.TargetCyan);LessonReadableText.Attach(authorHelp);
   referenceArea=AppTheme.Rect(card,"Reference viewport",new Vector2(.04f,.39f),new Vector2(.96f,.79f));referenceArea.gameObject.AddComponent<RectMask2D>();
   var referenceImage=AppTheme.Rect(referenceArea,"Official image",Vector2.zero,Vector2.one);reference=referenceImage.gameObject.AddComponent<RawImage>();reference.raycastTarget=true;reference.color=Color.clear;
   var enlarge=referenceImage.gameObject.AddComponent<Button>();enlarge.targetGraphic=reference;enlarge.transition=Selectable.Transition.None;enlarge.onClick.AddListener(EnlargeReference);
   referenceImage.gameObject.AddComponent<AspectRatioFitter>().aspectMode=AspectRatioFitter.AspectMode.FitInParent;
   ReferenceNavigation(card,"上一张",new Vector2(.04f,.30f),new Vector2(.25f,.37f),-1);
   referenceDropdown=AppDropdown.Create(card,"Reference selector",new Vector2(.28f,.30f),new Vector2(.72f,.37f),index=>{referenceIndex=index;StartCoroutine(LoadReference());});
   referenceCaption=referenceDropdown.captionText;
   ReferenceNavigation(card,"下一张",new Vector2(.75f,.30f),new Vector2(.96f,.37f),1);
   AppTheme.Label(card,"拍照反馈",new Vector2(.04f,.25f),new Vector2(.96f,.29f),21,AppTheme.TargetCyan);
   checkResult=Feedback(card);checkResult.text="可选拍照，查看位置或安装建议。";
   locateButton=AppTheme.Button(card,"拍照找位置",new Vector2(.04f,.015f),new Vector2(.48f,.078f),()=>StartCoroutine(Locate()),AppIcon.Inspect);
   verify=AppTheme.Button(card,"拍照参考",new Vector2(.52f,.015f),new Vector2(.96f,.078f),()=>StartCoroutine(Verify()),AppIcon.Camera);
   status=AppTheme.Label(root,"启动摄像头后开始指导",new Vector2(.025f,.095f),new Vector2(.64f,.145f),22,AppTheme.TargetCyan);
   setupBar=AppTheme.Rect(root,"Spatial Setup",new Vector2(.025f,.025f),new Vector2(.975f,.085f));
   AppTheme.Button(setupBar,"打印标定纸",new Vector2(0,0),new Vector2(.18f,1),()=>Application.OpenURL(origin+Api+"/print.pdf"),AppIcon.Save);
   sample=AppTheme.Button(setupBar,"采集棋盘",new Vector2(.20f,0),new Vector2(.38f,1),()=>{sampleNext=true;Message("采集当前棋盘视角");},AppIcon.Camera);
   solve=AppTheme.Button(setupBar,"计算标定",new Vector2(.40f,0),new Vector2(.58f,1),()=>StartCoroutine(Calibrate()),AppIcon.Check);
   setup=AppTheme.Button(setupBar,"设置起终点",new Vector2(.60f,0),new Vector2(.82f,1),()=>StartCoroutine(AuthorStep()),AppIcon.Inspect,true);
   cancel=AppTheme.Button(setupBar,"取消设置",new Vector2(.84f,0),new Vector2(1,1),ExitSetup,AppIcon.Close);
   actionBar=new SpatialActionBar(root,MarkOperation,()=>{setupExplicit=true;SetSetupVisible(true);});
   SetSetupVisible(true);cameraOwner=gameObject.AddComponent<SpatialCamera>();frameSource=cameraOwner;
   Canvas.willRenderCanvases+=RefreshCallout;AppShell.BindBack("返回图文指导",()=>StartCoroutine(Close()),()=>!changing);
  }
  void ReferenceNavigation(Transform parent,string title,Vector2 min,Vector2 max,int direction){
   var panel=AppTheme.Panel(parent,title,min,max);panel.GetComponent<Image>().color=AppTheme.ButtonBackground;
   var button=panel.gameObject.AddComponent<Button>();button.targetGraphic=panel.GetComponent<Image>();button.onClick.AddListener(()=>{referenceIndex+=direction;StartCoroutine(LoadReference());});
   var label=AppTheme.Label(panel,title,new Vector2(.02f,0),new Vector2(.98f,1),23);label.alignment=TextAnchor.MiddleCenter;AppTheme.Skin(button);
  }
  static Text Feedback(Transform parent){return ScrollText(parent,"AI feedback scroll",new Vector2(.04f,.095f),new Vector2(.96f,.245f),21);}
  static Text ScrollText(Transform parent,string name,Vector2 min,Vector2 max,int size){
   var area=AppTheme.Rect(parent,name,min,max);area.gameObject.AddComponent<Image>().color=Color.clear;
   var scroll=area.gameObject.AddComponent<ScrollRect>();scroll.horizontal=false;scroll.scrollSensitivity=35;scroll.movementType=ScrollRect.MovementType.Clamped;
   var viewport=AppTheme.Rect(area,"Viewport",Vector2.zero,Vector2.one);viewport.gameObject.AddComponent<RectMask2D>();
   var content=AppTheme.Rect(viewport,"Content",new Vector2(0,1),new Vector2(1,1));content.pivot=new Vector2(.5f,1);
   var layout=content.gameObject.AddComponent<VerticalLayoutGroup>();layout.childControlHeight=layout.childControlWidth=true;layout.childForceExpandHeight=false;
   content.gameObject.AddComponent<ContentSizeFitter>().verticalFit=ContentSizeFitter.FitMode.PreferredSize;
   var text=AppTheme.Label(content,"",Vector2.zero,Vector2.one,size);text.gameObject.AddComponent<LayoutElement>();text.verticalOverflow=VerticalWrapMode.Overflow;text.alignment=TextAnchor.UpperLeft;
   LessonReadableText.Attach(text);scroll.content=content;scroll.viewport=viewport;return text;
  }
 }
}
