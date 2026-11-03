using System;
using UnityEngine;
using UnityEngine.UI;

namespace Manual2AR {
    /// <summary>Reading and optional capture surfaces; task logic lives in the controller.</summary>
    public sealed partial class PrinterGuidanceController {
        GameObject captureDialog,cameraSettings,cameraEmpty;
        Button photoEntry;

        protected override void BuildUI(){
            var canvas=new GameObject("Operation guidance",typeof(RectTransform),typeof(Canvas),typeof(CanvasScaler),typeof(GraphicRaycaster));
            canvas.GetComponent<Canvas>().renderMode=RenderMode.ScreenSpaceOverlay;canvas.GetComponent<Canvas>().pixelPerfect=true;
            var scaler=canvas.GetComponent<CanvasScaler>();scaler.uiScaleMode=CanvasScaler.ScaleMode.ScaleWithScreenSize;scaler.referenceResolution=new Vector2(1920,1080);scaler.matchWidthOrHeight=.5f;
            root=canvas.GetComponent<RectTransform>();AppTheme.Attach(root);canvas.AddComponent<AppRoundedImage>().color=Navy;
            if(UnityEngine.EventSystems.EventSystem.current==null)new GameObject("EventSystem",typeof(UnityEngine.EventSystems.EventSystem),typeof(UnityEngine.EventSystems.StandaloneInputModule));
            title=TextAt(root,"模块二 · 操作指导",new Vector2(.025f,.94f),new Vector2(.62f,.995f),30);title.color=Color.white;
            count=TextAt(root,"",new Vector2(.64f,.94f),new Vector2(.79f,.995f),21);BuildProgress(12);
            ButtonAt(root,"步骤总览",new Vector2(.025f,.845f),new Vector2(.18f,.89f),()=>ShowOverview(false));
            spatialEntry=AppTheme.Button(root,"进入空间指导",new Vector2(.19f,.845f),new Vector2(.40f,.89f),OpenSpatial,AppIcon.Inspect,true);spatialEntry.gameObject.SetActive(false);
            spatialActions=AppTheme.Button(root,"指导单元",new Vector2(.41f,.845f),new Vector2(.55f,.89f),ShowSpatialActions,AppIcon.Info);spatialActions.gameObject.SetActive(false);
            cancelChild=ButtonAt(root,"结束子任务并返回",new Vector2(.19f,.845f),new Vector2(.55f,.89f),()=>StartCoroutine(CancelChild()));cancelChild.gameObject.SetActive(false);
            photoEntry=AppTheme.Button(root,"拍照参考（可选）",new Vector2(.60f,.845f),new Vector2(.815f,.89f),OpenPhotoReference,AppIcon.Camera);photoEntry.gameObject.SetActive(false);
            restart=ButtonAt(root,"重新开始",new Vector2(.83f,.845f),new Vector2(.975f,.89f),ResetDialog);

            instructionCard=Frame("操作说明与参考",root,new Vector2(.025f,.14f),new Vector2(.425f,.83f));
            TextAt(instructionCard,"本章指导",new Vector2(.035f,.90f),new Vector2(.965f,.98f),21).color=Cyan;
            body=Scroll(instructionCard,new Vector2(.025f,.025f),new Vector2(.975f,.87f));
            body.parent.parent.GetComponent<Image>().color=Color.clear;
            substepTabs=Rect("分步骤切换",instructionCard,new Vector2(.035f,.77f),new Vector2(.965f,.87f));substepTabs.gameObject.SetActive(false);
            referencePanel=Frame("官方参考图",root,new Vector2(.445f,.14f),new Vector2(.975f,.83f));
            TextAt(referencePanel,"官方参考图",new Vector2(.03f,.92f),new Vector2(.97f,.985f),21).color=Cyan;
            referenceArea=Rect("Reference viewport",referencePanel,new Vector2(.025f,.12f),new Vector2(.975f,.91f));referenceArea.gameObject.AddComponent<RectMask2D>();
            referenceRect=Rect("Reference image",referenceArea,new Vector2(.5f,.5f),new Vector2(.5f,.5f));referenceImage=referenceRect.gameObject.AddComponent<RawImage>();
            referenceRect.gameObject.AddComponent<Button>().onClick.AddListener(EnlargeReference);
            referenceCaption=TextAt(referencePanel,"",new Vector2(.20f,.02f),new Vector2(.80f,.10f),21);referenceCaption.alignment=TextAnchor.MiddleCenter;referenceCaption.color=AppTheme.Muted;
            previousPhoto=ButtonAt(referencePanel,"上一图",new Vector2(.025f,.02f),new Vector2(.185f,.10f),()=>{photoIndex--;StartCoroutine(LoadReference());});
            nextPhoto=ButtonAt(referencePanel,"下一图",new Vector2(.815f,.02f),new Vector2(.975f,.10f),()=>{photoIndex++;StartCoroutine(LoadReference());});
            // Retained base-view references, never used as filler in a lesson.
            placeholder=Rect("Unused lesson placeholder",root,Vector2.zero,Vector2.zero).gameObject;placeholder.SetActive(false);
            manualPanel=Rect("Manual context",root,Vector2.zero,Vector2.zero).gameObject;manualHelp=TextAt(manualPanel.transform,"",Vector2.zero,Vector2.one,24);manualPanel.SetActive(false);
            actionsPanel=Frame("后续操作",root,new Vector2(.025f,.14f),new Vector2(.425f,.35f)).gameObject;actionsPanel.SetActive(false);
            primary=ButtonAt(root,"确认完成",new Vector2(.355f,.025f),new Vector2(.685f,.075f),Primary);
            notice=TextAt(root,"正在读取配置……",new Vector2(.025f,.085f),new Vector2(.975f,.13f),18);notice.color=AppTheme.Muted;
            back=ButtonAt(root,"← 上一步",new Vector2(.025f,.025f),new Vector2(.16f,.075f),()=>StartCoroutine(Command("back")));
            recheck=ButtonAt(root,"重新检查本章",new Vector2(.175f,.025f),new Vector2(.34f,.075f),()=>StartCoroutine(Command("recheck")));recheck.gameObject.SetActive(false);
            next=ButtonAt(root,"下一步 →",new Vector2(.775f,.025f),new Vector2(.975f,.075f),()=>StartCoroutine(Command("advance")));
            primary.interactable=next.interactable=back.interactable=recheck.interactable=false;
            BuildCaptureDialog();
            taskMenu=AppTaskMenu.Create(root,"Operation Task Catalog","操作指导","Bambu Lab A1 mini · 选择操作任务");catalogPanel=taskMenu.Root.gameObject;catalogStatus=taskMenu.Status;
            resume=AppTheme.Button(catalogPanel.transform,"继续当前指导",new Vector2(.70f,.83f),new Vector2(.95f,.89f),()=>{if(run!=null){catalogPanel.SetActive(false);BindTaskBack();StartCoroutine(Connect(false));}},AppIcon.Check);resume.gameObject.SetActive(false);
            AppShell.BindTeachingBack();EnhanceScrolls();Canvas.willRenderCanvases+=RefreshForDisplayScale;
        }

        void BuildCaptureDialog(){
            var shade=Rect("Photo reference dialog",root,Vector2.zero,Vector2.one);shade.gameObject.AddComponent<Image>().color=new Color(.005f,.015f,.025f,.97f);captureDialog=shade.gameObject;
            var panel=Frame("拍摄与核验",shade,new Vector2(.025f,.06f),new Vector2(.975f,.925f));cameraPanel=panel.gameObject;
            TextAt(panel,"拍照参考",new Vector2(.025f,.91f),new Vector2(.60f,.985f),30).color=Color.white;
            startCamera=AppTheme.Button(panel,"启动摄像头",new Vector2(.025f,.825f),new Vector2(.29f,.895f),()=>StartCoroutine(StartCamera()),AppIcon.Camera,true);
            live=AppTheme.Button(panel,"重新取景",new Vector2(.31f,.825f),new Vector2(.53f,.895f),ShowLive,AppIcon.SwitchCamera);
            AppTheme.Button(panel,"镜头设置",new Vector2(.76f,.915f),new Vector2(.975f,.98f),OpenCameraSettings,AppIcon.Camera);
            cameraArea=Frame("当前图像",panel,new Vector2(.025f,.12f),new Vector2(.625f,.805f));cameraArea.gameObject.AddComponent<RectMask2D>();
            cameraRect=Rect("Current frame",cameraArea,new Vector2(.5f,.5f),new Vector2(.5f,.5f));cameraImage=cameraRect.gameObject.AddComponent<RawImage>();cameraImage.raycastTarget=false;
            cameraEmpty=Rect("Camera start guidance",cameraArea,new Vector2(.10f,.15f),new Vector2(.90f,.85f)).gameObject;
            var icon=AppTheme.Rect(cameraEmpty.transform,"Camera icon",new Vector2(.43f,.53f),new Vector2(.57f,.78f)).gameObject.AddComponent<AppIconGraphic>();icon.symbol=AppIcon.Camera;icon.color=AppTheme.Muted;icon.raycastTarget=false;
            var empty=TextAt(cameraEmpty.transform,"启动摄像头后，这里显示实时取景\n点击拍照时才提交当前图像",new Vector2(.05f,.20f),new Vector2(.95f,.48f),26);empty.alignment=TextAnchor.MiddleCenter;empty.color=AppTheme.Muted;
            cameraCaption=TextAt(panel,"",new Vector2(.025f,.035f),new Vector2(.625f,.105f),21);cameraCaption.color=AppTheme.Muted;
            TextAt(panel,"拍摄指导",new Vector2(.66f,.825f),new Vector2(.97f,.89f),23).color=Cyan;
            var guide=Scroll(panel,new Vector2(.65f,.595f),new Vector2(.975f,.815f));guide.parent.parent.GetComponent<Image>().color=Color.clear;
            captureHelp=FlowText(guide,"拍摄指导正文",24,Color.white);
            checkTarget=TextAt(panel,"",Vector2.zero,Vector2.zero,18);checkTarget.gameObject.SetActive(false);
            TextAt(panel,"本次拍照反馈",new Vector2(.66f,.50f),new Vector2(.97f,.565f),23).color=Cyan;
            var response=Scroll(panel,new Vector2(.65f,.20f),new Vector2(.975f,.49f));responseArea=response.parent.parent.GetComponent<RectTransform>();responseArea.GetComponent<Image>().color=Color.clear;
            result=FlowText(response,"本次检查结果",24,AppTheme.Muted);
            TextAt(panel,"拍照建议仅供参考，不影响章节浏览",new Vector2(.66f,.025f),new Vector2(.97f,.075f),18).color=AppTheme.Muted;
            var options=Frame("镜头设置",shade,new Vector2(.20f,.25f),new Vector2(.80f,.78f));cameraSettings=options.gameObject;
            TextAt(options,"镜头设置",new Vector2(.05f,.80f),new Vector2(.95f,.96f),30);
            TextAt(options,"选择摄像头",new Vector2(.05f,.67f),new Vector2(.95f,.78f),23).color=Cyan;
            devices=DropdownAt(options,new Vector2(.05f,.53f),new Vector2(.95f,.66f));
            TextAt(options,"拍摄画幅",new Vector2(.05f,.36f),new Vector2(.95f,.49f),23).color=Cyan;
            aspectSelector=framing.AddSelector(options,new Vector2(.05f,.22f),new Vector2(.95f,.35f),ChangeFraming);
            AppTheme.Button(options,"完成设置",new Vector2(.60f,.04f),new Vector2(.95f,.16f),CloseCameraSettings,AppIcon.Check,true);
            cameraSettings.SetActive(false);captureDialog.SetActive(false);
        }

        Text FlowText(RectTransform parent,string name,int size,Color color){
            var o=new GameObject(name,typeof(RectTransform),typeof(Text),typeof(LayoutElement));o.transform.SetParent(parent,false);
            var text=o.GetComponent<Text>();text.font=font;text.fontSize=size;text.color=color;text.lineSpacing=1.3f;text.supportRichText=false;text.raycastTarget=false;text.verticalOverflow=VerticalWrapMode.Overflow;LessonReadableText.Attach(text);return text;
        }

        void LayoutLesson(){
            bool pictures=run.presentation.images!=null&&run.presentation.images.Length>0;
            bool actions=Current.available_actions!=null&&Current.available_actions.Length>0;
            SetAnchors(instructionCard,(pictures||actions) ? .025f : .16f,actions&&pictures?.37f:.14f,(pictures||actions) ? .425f : .84f,.83f);
            SetAnchors(referencePanel,.445f,.14f,.975f,.83f);
            SetAnchors(actionsPanel.GetComponent<RectTransform>(),pictures?.025f:.445f,.14f,pictures?.425f:.975f,pictures?.35f:.83f);
            primary.transform.SetParent(cameraPanel.activeSelf?cameraPanel.transform:root,false);
            SetAnchors(primary.GetComponent<RectTransform>(),cameraPanel.activeSelf?.66f:.355f,cameraPanel.activeSelf?.10f:.025f,cameraPanel.activeSelf?.97f:.685f,cameraPanel.activeSelf?.18f:.075f);
            manualPanel.SetActive(false);placeholder.SetActive(false);
            if(!cameraPanel.activeSelf)ClosePhotoReference();
            if(captureDialog.activeSelf){if(cameraSettings.activeSelf)AppShell.BindBack("返回拍照参考",CloseCameraSettings,()=>!starting);else BindCaptureBack();}
            RefreshReferenceCaption();
        }

        void LayoutTeachingPanels(){if(cameraEmpty!=null)cameraEmpty.SetActive(cameraImage.texture==null);cameraRect.gameObject.SetActive(cameraImage.texture!=null);LayoutCamera();}

        void RefreshReferenceCaption(){
            if(run==null)return;int total=run.presentation.images==null?0:run.presentation.images.Length;
            previousPhoto.gameObject.SetActive(total>1);nextPhoto.gameObject.SetActive(total>1);
            SetAnchors(referenceCaption.rectTransform,total>1?.20f:.025f,.02f,total>1?.80f:.975f,.10f);
            bool animated=total>0&&run.presentation.images[Mathf.Clamp(photoIndex,0,total-1)].animation_frames!=null&&run.presentation.images[Mathf.Clamp(photoIndex,0,total-1)].animation_frames.Length>0;
            referenceCaption.text=(photoIndex+1)+" / "+total+(animated?" · 动图":"")+" · 点击图片放大";
        }

        protected override void LayoutReference(){
            if(referenceTexture==null)return;
            var uv=referenceImage.uvRect;float width=referenceTexture.width*Mathf.Max(.0001f,uv.width),height=referenceTexture.height*Mathf.Max(.0001f,uv.height);
            float scale=Mathf.Min(referenceArea.rect.width/width,referenceArea.rect.height/height);
            referenceRect.sizeDelta=new Vector2(width*scale,height*scale);RefreshReferenceCaption();
        }

        void OpenPhotoReference(){
            if(run==null||run.channel!="vision"||busy)return;CloseModal();captureDialog.SetActive(true);captureDialog.transform.SetAsLastSibling();
            if(snapshot!=null&&cameraImage.texture==null){cameraImage.texture=snapshot;frozen=true;}
            LayoutTeachingPanels();BindCaptureBack();
        }
        void BindCaptureBack(){AppShell.BindBack("返回教学",ClosePhotoReference,()=>!starting);}
        void ClosePhotoReference(){
            if(captureDialog==null||!captureDialog.activeSelf)return;cameraSettings.SetActive(false);StopCamera();captureDialog.SetActive(false);BindTaskBack();
        }
        void OpenCameraSettings(){cameraSettings.SetActive(true);cameraSettings.transform.SetAsLastSibling();AppShell.BindBack("返回拍照参考",CloseCameraSettings,()=>!starting);}
        void CloseCameraSettings(){cameraSettings.SetActive(false);BindCaptureBack();}
    }
}
