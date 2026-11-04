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
   title.gameObject.SetActive(false);modeLabel.gameObject.SetActive(false);
   var controls=AppTheme.Panel(root,"Camera and action management",new Vector2(.015f,.90f),new Vector2(.985f,.985f));
   AppTheme.Button(root,"摄像头管理",new Vector2(.025f,.91f),new Vector2(.203f,.975f),ShowCameraSettings,AppIcon.Camera);
   AppTheme.Button(root,"动画管理",new Vector2(.218f,.91f),new Vector2(.396f,.975f),ShowMotionSettings,AppIcon.Inspect);
   var cameraPanel=AppTheme.Panel(root,"Spatial Camera",new Vector2(.025f,.105f),new Vector2(.72f,.88f));cameraPanel.gameObject.AddComponent<RectMask2D>();
   viewport=AppTheme.Rect(cameraPanel,"Matched frame viewport",Vector2.zero,Vector2.one);var fitter=viewport.gameObject.AddComponent<AspectRatioFitter>();fitter.aspectMode=AspectRatioFitter.AspectMode.FitInParent;fitter.aspectRatio=4f/3;
   image=viewport.gameObject.AddComponent<RawImage>();image.raycastTarget=false;image.color=AppTheme.PanelBackground;
   partsView=new SpatialPartsView(viewport);
   assetGraphic=AppTheme.Rect(viewport,"Projected guidance assets",Vector2.zero,Vector2.one).gameObject.AddComponent<SpatialAssetGraphic>();assetGraphic.raycastTarget=false;
   companionGraphic=AppTheme.Rect(viewport,"Second screw guidance",Vector2.zero,Vector2.one).gameObject.AddComponent<SpatialAssetGraphic>();companionGraphic.raycastTarget=false;
   axesGraphic=AppTheme.Rect(viewport,"Operation XYZ axes",Vector2.zero,Vector2.one).gameObject.AddComponent<SpatialAxesGraphic>();axesGraphic.raycastTarget=false;
   overlay=AppTheme.Rect(viewport,"Metric guidance",Vector2.zero,Vector2.one).gameObject.AddComponent<SpatialOverlay>();overlay.Selected+=OnPoint;
   visionFeedback=new SpatialFeedbackView(viewport);stepHeader=visionFeedback.StepLabel;
   legend=new SpatialLegend(viewport);
   textRenderer=new SpatialTextRenderer(viewport);callout=new SpatialCallout(overlay);pickLabels=new SpatialPickLabels(overlay.transform);
   var card=AppTheme.Panel(root,"Step instructions and feedback",new Vector2(.74f,.105f),new Vector2(.975f,.88f));
   infoCard=card;var official=AppTheme.Rect(card,"Collapsed official guidance",Vector2.zero,Vector2.one);
   AppTheme.Button(root,"官方图文指导",new Vector2(.604f,.91f),new Vector2(.782f,.975f),()=>ShowStepIntroduction(false),AppIcon.Info);
   instruction=ScrollText(official,"Operation instructions",new Vector2(.04f,.815f),new Vector2(.96f,.97f),24);instruction.text="正在读取步骤…";
   authorHelp=AppTheme.Label(official,"",new Vector2(.04f,.68f),new Vector2(.96f,.80f),21,AppTheme.TargetCyan);LessonReadableText.Attach(authorHelp);
   referenceArea=AppTheme.Rect(official,"Reference viewport",new Vector2(.04f,.39f),new Vector2(.96f,.79f));referenceArea.gameObject.AddComponent<RectMask2D>();
   var referenceImage=AppTheme.Rect(referenceArea,"Official image",Vector2.zero,Vector2.one);reference=referenceImage.gameObject.AddComponent<RawImage>();reference.raycastTarget=true;reference.color=Color.clear;
   var enlarge=referenceImage.gameObject.AddComponent<Button>();enlarge.targetGraphic=reference;enlarge.transition=Selectable.Transition.None;enlarge.onClick.AddListener(EnlargeReference);
   referenceImage.gameObject.AddComponent<AspectRatioFitter>().aspectMode=AspectRatioFitter.AspectMode.FitInParent;
   ReferenceNavigation(official,"上一张",new Vector2(.04f,.30f),new Vector2(.25f,.37f),-1);
   referenceDropdown=AppDropdown.Create(official,"Reference selector",new Vector2(.28f,.30f),new Vector2(.72f,.37f),index=>{referenceIndex=index;StartCoroutine(LoadReference());});
   referenceCaption=referenceDropdown.captionText;
   ReferenceNavigation(official,"下一张",new Vector2(.75f,.30f),new Vector2(.96f,.37f),1);
   official.gameObject.SetActive(false);
   AppTheme.Label(card,"识别位置与安装建议",new Vector2(.04f,.91f),new Vector2(.96f,.975f),22,AppTheme.TargetCyan);
   checkResult=Feedback(card);checkResult.text="可选拍照，查看位置或安装建议。";
   locateButton=AppTheme.Button(card,"识别部件",new Vector2(.04f,.015f),new Vector2(.48f,.078f),ShowLocateCapture,AppIcon.Inspect);
   verify=AppTheme.Button(card,"检查安装",new Vector2(.52f,.015f),new Vector2(.96f,.078f),ShowVerifyCapture,AppIcon.Camera);
   status=AppTheme.Label(card,"",Vector2.zero,Vector2.zero,22,AppTheme.TargetCyan);status.gameObject.SetActive(false);
   setupBar=AppTheme.Rect(root,"Spatial Setup",new Vector2(.025f,.025f),new Vector2(.975f,.085f));
   AppTheme.Button(setupBar,"打印标定纸",new Vector2(0,0),new Vector2(.16f,1),()=>Application.OpenURL(origin+Api+"/print.pdf"),AppIcon.Save);
   sample=AppTheme.Button(setupBar,"采集棋盘",new Vector2(.17f,0),new Vector2(.33f,1),()=>{sampleNext=true;Message("采集当前棋盘视角");},AppIcon.Camera);
   solve=AppTheme.Button(setupBar,"计算标定",new Vector2(.34f,0),new Vector2(.50f,1),()=>StartCoroutine(Calibrate()),AppIcon.Check);
   setup=AppTheme.Button(setupBar,"设置起终点",new Vector2(.51f,0),new Vector2(.69f,1),()=>StartCoroutine(AuthorStep()),AppIcon.Inspect,true);
   AppTheme.Button(setupBar,"打印机坐标",new Vector2(.70f,0),new Vector2(.85f,1),ShowMachineSetup,AppIcon.Inspect);
   cancel=AppTheme.Button(setupBar,"取消设置",new Vector2(.86f,0),new Vector2(1,1),ExitSetup,AppIcon.Close);
   actionBar=new SpatialActionBar(root,MarkOperation,ShowAnchorSetup);
   SetSetupVisible(true);cameraOwner=gameObject.AddComponent<SpatialCamera>();frameSource=cameraOwner;
   BuildPreflightButton();
   Canvas.willRenderCanvases+=RefreshCallout;AppShell.BindBack("返回图文指导",()=>StartCoroutine(Close()),()=>!changing&&!checking);AppShell.PlaceBack(new Vector2(.797f,.91f),new Vector2(.975f,.975f));
  }
  void ReferenceNavigation(Transform parent,string title,Vector2 min,Vector2 max,int direction){
   var panel=AppTheme.Panel(parent,title,min,max);panel.GetComponent<Image>().color=AppTheme.ButtonBackground;
   var button=panel.gameObject.AddComponent<Button>();button.targetGraphic=panel.GetComponent<Image>();button.onClick.AddListener(()=>{referenceIndex+=direction;StartCoroutine(LoadReference());});
   var label=AppTheme.Label(panel,title,new Vector2(.02f,0),new Vector2(.98f,1),23);label.alignment=TextAnchor.MiddleCenter;AppTheme.Skin(button);
  }
  static Text Feedback(Transform parent){return ScrollText(parent,"AI feedback scroll",new Vector2(.04f,.12f),new Vector2(.96f,.88f),23);}
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
