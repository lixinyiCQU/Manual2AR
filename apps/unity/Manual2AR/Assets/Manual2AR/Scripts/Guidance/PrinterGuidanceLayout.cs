using System;
using UnityEngine;
using UnityEngine.UI;

namespace Manual2AR {
    /// <summary>Reading and optional capture surfaces; task logic lives in the controller.</summary>
    public sealed partial class PrinterGuidanceController {
        GameObject captureDialog,cameraSettings,cameraEmpty;AppWorkspace workspace,captureWorkspace;
        Button photoEntry,textCompletion,overviewButton;Text chapterHeading;

        protected override void BuildUI(){
            root=AppWorkspace.Canvas(transform,"Operation guidance");workspace=new AppWorkspace(root,"模块二 · 操作指导",AppWorkspaceKind.Reading);title=workspace.Title;
            count=TextAt(root,"",new Vector2(.64f,.94f),new Vector2(.79f,.995f),21);count.gameObject.SetActive(false);BuildProgress(12);
            overviewButton=AppTheme.Button(workspace.HeaderActions,"步骤总览",Vector2.zero,Vector2.one,()=>ShowOverview(false),AppIcon.Info);AppActionBar.Add(workspace.HeaderActions,overviewButton);
            spatialEntry=AppTheme.Button(root,"进入AR指导",new Vector2(.025f,.025f),new Vector2(.195f,.085f),OpenSpatial,AppIcon.Inspect,true);spatialEntry.gameObject.SetActive(false);
            cancelChild=ButtonAt(root,"结束子任务并返回",new Vector2(.385f,.025f),new Vector2(.555f,.085f),()=>StartCoroutine(CancelChild()));cancelChild.gameObject.SetActive(false);
            photoEntry=AppTheme.Button(root,"拍照核验",new Vector2(.205f,.025f),new Vector2(.375f,.085f),OpenPhotoReference,AppIcon.Camera);photoEntry.gameObject.SetActive(false);
            restart=ButtonAt(root,"重新开始",new Vector2(.83f,.845f),new Vector2(.975f,.89f),ResetDialog);restart.gameObject.SetActive(false);

            instructionCard=workspace.Main;
            TextAt(instructionCard,"本章指导",new Vector2(.035f,.93f),new Vector2(.965f,.99f),21).color=Cyan;
            chapterHeading=TextAt(instructionCard,"",new Vector2(.035f,.79f),new Vector2(.965f,.92f),32);chapterHeading.fontStyle=FontStyle.Bold;chapterHeading.resizeTextForBestFit=true;chapterHeading.resizeTextMinSize=25;chapterHeading.resizeTextMaxSize=32;
            body=Scroll(instructionCard,new Vector2(.025f,.025f),new Vector2(.975f,.87f));
            body.parent.parent.GetComponent<Image>().color=Color.clear;
            substepTabs=Rect("分步骤切换",instructionCard,new Vector2(.035f,.68f),new Vector2(.965f,.77f));substepTabs.gameObject.SetActive(false);
            referencePanel=workspace.Aside;
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
            primary=ButtonAt(root,"确认完成",new Vector2(.625f,.025f),new Vector2(.795f,.085f),Primary);
            notice=TextAt(root,"正在读取配置……",new Vector2(.025f,.085f),new Vector2(.975f,.13f),18);notice.color=AppTheme.Muted;
            back=ButtonAt(root,"← 上一步",new Vector2(.445f,.025f),new Vector2(.615f,.085f),()=>StartCoroutine(Command("back")));
            recheck=ButtonAt(root,"重新检查本章",new Vector2(.175f,.025f),new Vector2(.34f,.075f),()=>StartCoroutine(Command("recheck")));recheck.gameObject.SetActive(false);
            next=ButtonAt(root,"下一步 →",new Vector2(.805f,.025f),new Vector2(.975f,.085f),()=>StartCoroutine(Command("advance")));
            textCompletion=ButtonAt(root,"已完成本章",new Vector2(.625f,.025f),new Vector2(.795f,.085f),()=>{if(!busy&&run!=null)StartCoroutine(Confirm());});textCompletion.gameObject.SetActive(false);
            AppActionBar.Add(workspace.FooterLeft,spatialEntry);AppActionBar.Add(workspace.FooterLeft,photoEntry);AppActionBar.Add(workspace.FooterLeft,cancelChild);
            AppActionBar.Add(workspace.FooterRight,back);AppActionBar.Add(workspace.FooterRight,primary);AppActionBar.Add(workspace.FooterRight,textCompletion);AppActionBar.Add(workspace.FooterRight,next);
            primary.interactable=next.interactable=back.interactable=recheck.interactable=false;
            BuildCaptureDialog();
            taskMenu=AppTaskMenu.Create(root,"Operation Task Catalog","操作指导","Bambu Lab A1 mini · 选择操作任务");catalogPanel=taskMenu.Root.gameObject;catalogStatus=taskMenu.Status;
            resume=AppTheme.Button(catalogPanel.transform,"继续当前指导",new Vector2(.70f,.83f),new Vector2(.95f,.89f),()=>{if(run!=null){catalogPanel.SetActive(false);BindTaskBack();StartCoroutine(Connect(false));}},AppIcon.Check);resume.gameObject.SetActive(false);
            AppShell.BindTeachingBack();EnhanceScrolls();Canvas.willRenderCanvases+=RefreshForDisplayScale;
        }

        protected override void BuildProgress(int total){
            base.BuildProgress(total);if(workspace==null)return;
            float width=1f/Mathf.Max(1,total);
            for(int i=0;i<progress.Length;i++){var tab=progress[i].transform.parent as RectTransform;tab.SetParent(workspace.Tools,false);AppWorkspace.Place(tab,i*width,.12f,(i+1)*width-.004f,.88f);}
        }

        void BuildCaptureDialog(){
            var dialog=AppDialog.Open(root,"Photo reference dialog","拍照核验",AppDialogSize.Large,ClosePhotoReference);captureDialog=dialog.gameObject;var panel=dialog.Panel;cameraPanel=panel.gameObject;
            var content=Rect("Capture workspace",panel,new Vector2(.01f,.015f),new Vector2(.99f,.85f));captureWorkspace=new AppWorkspace(content,"拍照核验");captureWorkspace.Title.gameObject.SetActive(false);captureWorkspace.HeaderActions.gameObject.SetActive(false);
            var controls=new AppCameraBar(captureWorkspace.Tools,framing,()=>StartCoroutine(StartCamera()),OpenCameraSettings,ChangeFraming);startCamera=controls.Start;aspectSelector=controls.Aspect;
            controls.Switch.GetComponentInChildren<Text>().text="镜头设置";
            cameraArea=captureWorkspace.Main;cameraArea.gameObject.AddComponent<RectMask2D>();
            cameraRect=Rect("Current frame",cameraArea,new Vector2(.5f,.5f),new Vector2(.5f,.5f));cameraImage=cameraRect.gameObject.AddComponent<RawImage>();cameraImage.raycastTarget=false;
            cameraEmpty=AppMediaEmptyState.Attach(cameraArea,cameraImage,"启动摄像头；点击拍照后提交当前画面");
            cameraCaption=TextAt(captureWorkspace.FooterLeft,"",Vector2.zero,Vector2.one,AppTheme.CaptionSize);cameraCaption.color=AppTheme.Muted;
            live=AppTheme.Button(captureWorkspace.FooterRight,"重新取景",Vector2.zero,Vector2.one,ShowLive,AppIcon.SwitchCamera);AppActionBar.Add(captureWorkspace.FooterRight,live);
            var side=captureWorkspace.Aside;
            TextAt(side,"拍摄指导",new Vector2(.05f,.90f),new Vector2(.95f,.98f),AppTheme.BodySize).color=Cyan;
            var guide=Scroll(side,new Vector2(.03f,.58f),new Vector2(.97f,.89f));captureHelp=FlowText(guide,"拍摄指导正文",AppTheme.BodySize,Color.white);
            checkTarget=TextAt(side,"",Vector2.zero,Vector2.zero,AppTheme.CaptionSize);checkTarget.gameObject.SetActive(false);
            TextAt(side,"本次核验反馈",new Vector2(.05f,.48f),new Vector2(.95f,.56f),AppTheme.BodySize).color=Cyan;
            var response=Scroll(side,new Vector2(.03f,.04f),new Vector2(.97f,.47f));responseArea=response.parent.parent.GetComponent<RectTransform>();result=FlowText(response,"本次检查结果",AppTheme.BodySize,AppTheme.Muted);
            var lens=AppDialog.Open(dialog.transform,"Camera settings","镜头设置",AppDialogSize.Standard,CloseCameraSettings);var options=lens.Panel;cameraSettings=lens.gameObject;
            TextAt(options,"选择摄像头",new Vector2(.05f,.65f),new Vector2(.95f,.78f),AppTheme.BodySize).color=Cyan;
            devices=DropdownAt(options,new Vector2(.05f,.48f),new Vector2(.95f,.64f));
            TextAt(options,"画幅可在拍照页顶部调整；切换后需重新拍照。",new Vector2(.05f,.27f),new Vector2(.95f,.44f),AppTheme.BodySize).color=AppTheme.Muted;
            AppTheme.Button(options,"完成设置",new Vector2(.60f,.04f),new Vector2(.95f,.16f),CloseCameraSettings,AppIcon.Check,true);
            cameraSettings.SetActive(false);captureDialog.SetActive(false);
        }

        Text FlowText(RectTransform parent,string name,int size,Color color){
            var o=new GameObject(name,typeof(RectTransform),typeof(Text),typeof(LayoutElement));o.transform.SetParent(parent,false);
            var text=o.GetComponent<Text>();text.font=font;text.fontSize=size;text.color=color;text.lineSpacing=1.3f;text.supportRichText=false;text.raycastTarget=false;text.verticalOverflow=VerticalWrapMode.Overflow;AppReadableText.Attach(text);return text;
        }

        void LayoutLesson(){
            bool pictures=run.presentation.images!=null&&run.presentation.images.Length>0;
            bool actions=Current.available_actions!=null&&Current.available_actions.Length>0;
            workspace.SetReadingContent(pictures||actions);
            if(actions&&pictures)instructionCard.anchorMin=new Vector2(.025f,.37f);
            SetAnchors(actionsPanel.GetComponent<RectTransform>(),pictures?.025f:.445f,.13f,pictures?.425f:.975f,pictures?.35f:.815f);
            if(cameraPanel.activeSelf)AppActionBar.Add(captureWorkspace.FooterRight,primary);
            else{AppActionBar.Add(workspace.FooterRight,primary);primary.transform.SetSiblingIndex(1);}
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
