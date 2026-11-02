using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Text;
using System.Text.RegularExpressions;
using UnityEngine;
using UnityEngine.UI;

namespace Manual2AR
{
    /// <summary>Task selection and child-task navigation reuse the audited step UI.</summary>
    public sealed class PrinterGuidanceController : GuidanceStepView
    {
        GuidanceCatalog catalog;bool connected;
        AppTaskMenu taskMenu;
        GameObject catalogPanel,actionsPanel;Text catalogStatus;Button resume,cancelChild;
        readonly List<Button> taskButtons=new List<Button>();readonly List<Texture2D> thumbnails=new List<Texture2D>();
        int catalogGeneration;
        RectTransform responseArea;bool? previewLayout;int textLayoutGeneration;Vector2 lastDisplaySize;float lastDisplayScale=-1;bool fittingText;
        Text captureHelp,checkTarget,manualHelp;RectTransform instructionCard,substepTabs;GameObject manualPanel;
        Texture2D modalTexture;string presentationKey="";readonly List<Texture2D> animationTextures=new List<Texture2D>();
        bool Free {get{return Current!=null&&Current.navigation_policy=="free";}}
        readonly HashSet<string> overviewRuns=new HashSet<string>();
        GuidanceRun Current {get{return run as GuidanceRun;}}
        protected override string Api {get{return "/api/guidance/runs/";}}
        protected override string ConfigFile {get{return "Guidance.json";}}
        protected override string SetupHint {get{return "bash run.sh sync";}}
        protected override string TaskTitle {get{return "模块二 · "+(Current!=null?Current.flow_label:"操作指导");}}
        protected override string FinishLabel {get{return "完成本任务";}}
        protected override string CompletionMessage {get{return "✓ 本任务指导已完成\n"+(Current!=null?Current.completion_scope:"");}}
        protected override UnboxingRun ParseRun(string raw){return Parse<GuidanceRun>(raw);}

        protected override void BuildUI()
        {
            var canvas=new GameObject("Operation guidance",typeof(RectTransform),typeof(Canvas),typeof(CanvasScaler),typeof(UnityEngine.UI.GraphicRaycaster));
            canvas.GetComponent<Canvas>().renderMode=RenderMode.ScreenSpaceOverlay;canvas.GetComponent<Canvas>().pixelPerfect=true;
            var scaler=canvas.GetComponent<CanvasScaler>();scaler.uiScaleMode=CanvasScaler.ScaleMode.ScaleWithScreenSize;scaler.referenceResolution=new Vector2(1920,1080);scaler.matchWidthOrHeight=.5f;
            root=canvas.GetComponent<RectTransform>();AppTheme.Attach(root);canvas.AddComponent<AppRoundedImage>().color=Navy;
            if(UnityEngine.EventSystems.EventSystem.current==null)new GameObject("EventSystem",typeof(UnityEngine.EventSystems.EventSystem),typeof(UnityEngine.EventSystems.StandaloneInputModule));
            title=TextAt(root,"模块二 · 操作指导",new Vector2(.025f,.94f),new Vector2(.62f,.995f),30);title.color=Color.white;
            count=TextAt(root,"",new Vector2(.64f,.94f),new Vector2(.79f,.995f),21);BuildProgress(12);

            ButtonAt(root,"步骤总览",new Vector2(.025f,.845f),new Vector2(.18f,.89f),()=>ShowOverview(false));
            cancelChild=ButtonAt(root,"结束子任务并返回",new Vector2(.31f,.845f),new Vector2(.58f,.89f),()=>StartCoroutine(CancelChild()));cancelChild.gameObject.SetActive(false);
            restart=ButtonAt(root,"重新开始",new Vector2(.83f,.845f),new Vector2(.975f,.89f),ResetDialog);
            instructionCard=Frame("操作说明与参考",root,new Vector2(.025f,.505f),new Vector2(.625f,.83f));
            TextAt(instructionCard,"01  操作说明",new Vector2(.03f,.84f),new Vector2(.97f,.98f),20).color=Cyan;
            body=Scroll(instructionCard,new Vector2(.015f,.025f),new Vector2(.985f,.82f));
            substepTabs=Rect("分步骤切换",instructionCard,new Vector2(.02f,.68f),new Vector2(.98f,.83f));substepTabs.gameObject.SetActive(false);
            referencePanel=Frame("官方参考图",root,new Vector2(.025f,.15f),new Vector2(.625f,.49f));
            referenceArea=Rect("Reference viewport",referencePanel,new Vector2(.015f,.19f),new Vector2(.985f,.98f));referenceArea.gameObject.AddComponent<RectMask2D>();
            referenceRect=Rect("Reference image",referenceArea,new Vector2(.5f,.5f),new Vector2(.5f,.5f));referenceImage=referenceRect.gameObject.AddComponent<RawImage>();
            referenceRect.gameObject.AddComponent<Button>().onClick.AddListener(EnlargeReference);
            referenceCaption=TextAt(referencePanel,"",new Vector2(.17f,.01f),new Vector2(.83f,.18f),16);
            previousPhoto=ButtonAt(referencePanel,"上一图",new Vector2(.01f,.025f),new Vector2(.16f,.15f),()=>{photoIndex--;StartCoroutine(LoadReference());});
            nextPhoto=ButtonAt(referencePanel,"下一图",new Vector2(.84f,.025f),new Vector2(.99f,.15f),()=>{photoIndex++;StartCoroutine(LoadReference());});
            placeholder=Frame("本任务步骤",root,new Vector2(.025f,.15f),new Vector2(.625f,.49f)).gameObject;
            cameraPanel=Frame("拍摄与核验",root,new Vector2(.645f,.51f),new Vector2(.975f,.83f)).gameObject;
            TextAt(cameraPanel.transform,"02  拍照参考",new Vector2(.025f,.90f),new Vector2(.975f,.995f),22).color=Cyan;
            captureHelp=TextAt(cameraPanel.transform,"",new Vector2(.025f,.79f),new Vector2(.975f,.94f),20);
            checkTarget=TextAt(cameraPanel.transform,"",new Vector2(.025f,.73f),new Vector2(.975f,.815f),18);checkTarget.color=Cyan;checkTarget.gameObject.SetActive(false);
            devices=DropdownAt(cameraPanel.transform,new Vector2(.025f,.67f),new Vector2(.49f,.725f));
            startCamera=ButtonAt(cameraPanel.transform,"启动摄像头",new Vector2(.51f,.67f),new Vector2(.745f,.725f),()=>StartCoroutine(StartCamera()));
            aspectSelector=framing.AddSelector(cameraPanel.transform,new Vector2(.025f,.59f),new Vector2(.975f,.65f),ChangeFraming);
            live=ButtonAt(cameraPanel.transform,"重新拍摄",new Vector2(.765f,.67f),new Vector2(.975f,.725f),ShowLive);
            cameraArea=Frame("当前图像",cameraPanel.transform,new Vector2(.025f,.27f),new Vector2(.975f,.655f));cameraArea.gameObject.AddComponent<RectMask2D>();
            cameraRect=Rect("Current frame",cameraArea,new Vector2(.5f,.5f),new Vector2(.5f,.5f));cameraImage=cameraRect.gameObject.AddComponent<RawImage>();cameraImage.raycastTarget=false;
            cameraCaption=TextAt(cameraPanel.transform,"",new Vector2(.025f,.23f),new Vector2(.975f,.27f),15);
            var response=Scroll(cameraPanel.transform,new Vector2(.025f,.015f),new Vector2(.975f,.225f));responseArea=response.parent.parent.GetComponent<RectTransform>();
            var responseObject=new GameObject("本次检查结果",typeof(RectTransform),typeof(Text),typeof(LayoutElement));responseObject.transform.SetParent(response,false);
            result=responseObject.GetComponent<Text>();result.font=font;result.fontSize=22;result.supportRichText=false;result.lineSpacing=1.12f;result.color=Cyan;result.verticalOverflow=VerticalWrapMode.Overflow;result.raycastTarget=false;
            manualPanel=Frame("完成操作",root,new Vector2(.645f,.64f),new Vector2(.975f,.83f)).gameObject;
            TextAt(manualPanel.transform,"02  操作提示",new Vector2(.045f,.77f),new Vector2(.955f,.96f),23).color=Cyan;
            var manualBody=Scroll(manualPanel.transform,new Vector2(.025f,.04f),new Vector2(.975f,.70f));
            var manualText=new GameObject("操作提示正文",typeof(RectTransform),typeof(Text),typeof(LayoutElement));manualText.transform.SetParent(manualBody,false);
            manualHelp=manualText.GetComponent<Text>();manualHelp.font=font;manualHelp.fontSize=24;manualHelp.supportRichText=false;manualHelp.lineSpacing=1.12f;manualHelp.color=Color.white;manualHelp.raycastTarget=false;manualHelp.verticalOverflow=VerticalWrapMode.Overflow;
            actionsPanel=Frame("后续操作",root,new Vector2(.645f,.17f),new Vector2(.975f,.54f)).gameObject;
            primary=ButtonAt(root,"确认完成",new Vector2(.645f,.43f),new Vector2(.975f,.485f),Primary);
            notice=TextAt(root,"正在读取配置……",new Vector2(.025f,.095f),new Vector2(.50f,.16f),18);
            back=ButtonAt(root,"← 上一步",new Vector2(.025f,.025f),new Vector2(.16f,.075f),()=>StartCoroutine(Command("back")));
            recheck=ButtonAt(root,"重新检查本章",new Vector2(.175f,.025f),new Vector2(.34f,.075f),()=>StartCoroutine(Command("recheck")));recheck.gameObject.SetActive(false);


            next=ButtonAt(root,"下一步 →",new Vector2(.775f,.025f),new Vector2(.975f,.075f),()=>StartCoroutine(Command("advance")));
            primary.interactable=next.interactable=back.interactable=recheck.interactable=false;
            cameraPanel.SetActive(false);manualPanel.SetActive(false);actionsPanel.SetActive(false);
            taskMenu=AppTaskMenu.Create(root,"Operation Task Catalog","操作指导","Bambu Lab A1 mini · 选择操作任务");catalogPanel=taskMenu.Root.gameObject;catalogStatus=taskMenu.Status;
            resume=AppTheme.Button(catalogPanel.transform,"继续当前指导",new Vector2(.70f,.83f),new Vector2(.95f,.89f),()=>{if(run!=null){catalogPanel.SetActive(false);BindTaskBack();StartCoroutine(Connect(false));}},AppIcon.Check);resume.gameObject.SetActive(false);
            AppShell.BindTeachingBack();EnhanceScrolls();Canvas.willRenderCanvases+=RefreshForDisplayScale;
        }
        protected override void Start()
        {
            base.Start();if(settings!=null)Screen.SetResolution(settings.ui_width,settings.ui_height,FullScreenMode.Windowed);
        }
        // Same Chinese break opportunities and line spacing as module one.
        // These changes affect presentation only; source evidence remains verbatim.
        static string ReadableText(string value)
        {
            if(string.IsNullOrEmpty(value))return value;
            value=value.Replace("\u200b","").Replace("\u2060","").Replace("\r\n","\n").Replace('\r','\n');
            value=Regex.Replace(value,@"[ \t]+"," ");
            value=Regex.Replace(value,@"\n\s*([，。！？；：、）》】])","$1");
            value=value.Replace("AMS lite","AMS\u00a0lite").Replace("A1 mini","A1\u00a0mini");
            var output=new StringBuilder(value.Length*2);
            for(int i=0;i<value.Length;i++){
                output.Append(value[i]);
                if(i+1<value.Length&&value[i]>=0x3400&&value[i]<=0x9fff&&value[i+1]>=0x3400&&value[i+1]<=0x9fff)output.Append('\u200b');
            }
            return output.ToString();
        }
        static void PreventOrphanPunctuation(Text label)
        {
            if(label==null||!label.gameObject.activeInHierarchy||label.rectTransform.rect.width<=0)return;
            string value=label.text;
            for(int pass=0;pass<32;pass++){
                var generator=label.cachedTextGenerator;generator.Populate(value,label.GetGenerationSettings(label.rectTransform.rect.size));
                int insert=-1;
                foreach(var line in generator.lines){
                    int start=line.startCharIdx;
                    while(start<value.Length&&(char.IsWhiteSpace(value[start])||value[start]=='\u200b'))start++;
                    if(start<=0||start>=value.Length||"，。！？；：、）》】".IndexOf(value[start])<0)continue;
                    int previous=start-1;
                    while(previous>=0&&(char.IsWhiteSpace(value[previous])||value[previous]=='\u200b'||"，。！？；：、）》】".IndexOf(value[previous])>=0))previous--;
                    if(previous<0)continue;
                    insert=previous;
                    if(value[previous]<128&&char.IsLetterOrDigit(value[previous])){
                        while(insert>0&&((value[insert-1]<128&&(char.IsLetterOrDigit(value[insert-1])||value[insert-1]=='-'))||value[insert-1]=='\u00a0'))insert--;
                    }
                    break;
                }
                if(insert<0)break;
                value=value.Insert(insert,"\n");label.text=value;
            }
        }
        void RefreshForDisplayScale()
        {
            if(root==null||body==null||fittingText)return;
            float scale=root.GetComponent<Canvas>().scaleFactor;var size=root.rect.size;
            if(lastDisplaySize==size&&Mathf.Abs(lastDisplayScale-scale)<.0001f)return;
            lastDisplaySize=size;lastDisplayScale=scale;fittingText=true;
            try{
                foreach(var text in body.GetComponentsInChildren<Text>())PreventOrphanPunctuation(text);
                PreventOrphanPunctuation(manualHelp);PreventOrphanPunctuation(captureHelp);PreventOrphanPunctuation(result);
                LayoutRebuilder.ForceRebuildLayoutImmediate(body);
                if(manualHelp!=null)LayoutRebuilder.ForceRebuildLayoutImmediate(manualHelp.transform.parent as RectTransform);
                if(result!=null)LayoutRebuilder.ForceRebuildLayoutImmediate(result.transform.parent as RectTransform);
            }finally{fittingText=false;}
        }
        IEnumerator FinishTextLayout(int generation)
        {
            yield return null;if(generation!=textLayoutGeneration)yield break;
            Canvas.ForceUpdateCanvases();
            foreach(var text in body.GetComponentsInChildren<Text>())PreventOrphanPunctuation(text);
            PreventOrphanPunctuation(manualHelp);PreventOrphanPunctuation(captureHelp);PreventOrphanPunctuation(result);
            LayoutRebuilder.ForceRebuildLayoutImmediate(body);Canvas.ForceUpdateCanvases();
        }
        protected override void Paragraph(RectTransform parent,string value,int size,Color color)
        {
            var o=new GameObject("Paragraph",typeof(RectTransform),typeof(Text),typeof(LayoutElement));o.transform.SetParent(parent,false);
            var t=o.GetComponent<Text>();t.font=font;t.fontSize=size;t.text=ReadableText(value);t.color=color;t.supportRichText=false;t.raycastTarget=false;
            t.lineSpacing=1.12f;t.horizontalOverflow=HorizontalWrapMode.Wrap;t.verticalOverflow=VerticalWrapMode.Overflow;
            o.GetComponent<LayoutElement>().minHeight=size*1.3f;
        }
        void BodyParagraphs(string value)
        {
            if(string.IsNullOrWhiteSpace(value))return;
            foreach(var paragraph in Regex.Split(value.Trim(),@"\n\s*\n"))Paragraph(paragraph,24,Color.white);
        }
        protected override void RebuildBody()
        {
            foreach(Transform t in body){t.gameObject.SetActive(false);Destroy(t.gameObject);}
            Paragraph(run.presentation.title.Trim().TrimEnd('。')+(run.presentation.optional?"（可选）":""),28,Color.white);
            string instruction=run.presentation.instruction;
            if(!string.IsNullOrEmpty(run.presentation.substep_title))instruction=Regex.Replace(instruction,@"^\s*\d+[.、．]\s*","");
            BodyParagraphs(instruction);
            BodyParagraphs(run.presentation.chapter_context);
            bool repeatsOptional=run.presentation.optional&&instruction.Contains("选择性地安装料盘支架");
            if(!repeatsOptional)BodyParagraphs(run.presentation.applicability_note);
            if(run.presentation.tools!=null&&run.presentation.tools.Length>0)Paragraph("准备工具："+string.Join("、",run.presentation.tools),22,Color.white);
            if(run.presentation.materials!=null&&run.presentation.materials.Length>0)Paragraph("准备物料："+string.Join("、",run.presentation.materials),22,Color.white);
            var layout=body.GetComponent<VerticalLayoutGroup>();layout.spacing=12;layout.padding=new RectOffset(18,18,10,18);
            LayoutRebuilder.ForceRebuildLayoutImmediate(body);
            var scroll=body.parent.parent.GetComponent<ScrollRect>();scroll.movementType=ScrollRect.MovementType.Clamped;scroll.scrollSensitivity=38;scroll.verticalNormalizedPosition=1;
        }
        void LayoutTeachingPanels()
        {
            bool preview=cameraImage.texture!=null;
            if(previewLayout==preview)return;previewLayout=preview;
            var panel=cameraPanel.GetComponent<RectTransform>();panel.anchorMin=new Vector2(.645f,preview?.30f:.51f);panel.anchorMax=new Vector2(.975f,.83f);
            cameraArea.gameObject.SetActive(preview);cameraCaption.gameObject.SetActive(preview);
            captureHelp.alignment=TextAnchor.UpperLeft;captureHelp.fontSize=22;
            captureHelp.GetComponent<RectTransform>().anchorMin=new Vector2(.025f,preview?.78f:.58f);captureHelp.GetComponent<RectTransform>().anchorMax=new Vector2(.975f,preview?.91f:.88f);
            SetAnchors(devices.GetComponent<RectTransform>(),.025f,preview?.66f:.43f,.49f,preview?.75f:.55f);
            SetAnchors(startCamera.GetComponent<RectTransform>(),.51f,preview?.66f:.43f,.745f,preview?.75f:.55f);
            SetAnchors(live.GetComponent<RectTransform>(),.765f,preview?.66f:.43f,.975f,preview?.75f:.55f);
            SetAnchors(aspectSelector.Root,.025f,preview?.575f:.29f,.975f,preview?.645f:.41f);
            SetAnchors(cameraArea,.025f,.225f,.975f,.56f);SetAnchors(cameraCaption.GetComponent<RectTransform>(),.025f,.18f,.975f,.215f);
            SetAnchors(responseArea,.025f,.02f,.975f,preview?.17f:.26f);
            LayoutCamera();
        }
        static void SetAnchors(RectTransform rect,float left,float bottom,float right,float top){rect.anchorMin=new Vector2(left,bottom);rect.anchorMax=new Vector2(right,top);}
        void ShowOverview(bool entering)
        {
            if(task==null)return;StopCamera();CloseModal();
            modal=Frame("步骤总览",root,new Vector2(.035f,.09f),new Vector2(.965f,.93f)).gameObject;
            TextAt(modal.transform,task.title,new Vector2(.035f,.89f),new Vector2(.965f,.98f),31).color=Color.white;
            var outline=Scroll(modal.transform,new Vector2(.025f,.14f),new Vector2(.61f,.87f));
            Paragraph(outline,"教程章节 · "+task.steps.Length+" 章",24,Cyan);
            foreach(var step in task.steps){
                var selected=step;string state=step.id;
                bool visited=Current!=null&&Array.IndexOf(Current.visited_step_ids??new string[0],state)>=0;
                string label=(state==run.state_id?"正在查看 · ":visited?"已浏览 · ":"")+step.title+(step.optional?"（可选）":"");
                if(Free)RowButton(outline,label,()=>{CloseModal();StartCoroutine(BrowseStep(selected.id,null));});
                else Paragraph(outline,step.title,21,Color.white);
            }
            var official=Scroll(modal.transform,new Vector2(.63f,.34f),new Vector2(.975f,.87f));
            Paragraph(official,"关于本教程",24,Cyan);Paragraph(official,task.scope,21,Color.white);
            foreach(var requirement in task.entry_requirements??new string[0])Paragraph(official,requirement,20,new Color(1,.82f,.5f));
            if(Free)Paragraph(official,"点击左侧章节可自由跳转。拍照回答仅供参考，不影响浏览；浏览记录与操作标记分别保存。",20,Color.white);
            var source=task.official_source;
            string sourceUrl=source!=null?source.url:(task.official_sections!=null&&task.official_sections.Length>0?task.official_sections[0].url:"");
            Paragraph(official,source!=null?source.title:"Bambu Lab 官方指南",21,Cyan);
            if(!string.IsNullOrEmpty(sourceUrl)){
                ButtonAt(modal.transform,"打开官方指南 ↗",new Vector2(.65f,.24f),new Vector2(.95f,.31f),()=>Application.OpenURL(sourceUrl));
            }

            ButtonAt(modal.transform,entering?"开始浏览教程":"返回当前章节",new Vector2(.65f,.025f),new Vector2(.95f,.10f),CloseModal);
            EnhanceScrolls();
        }
        void EnhanceScrolls()
        {
            foreach(var scroll in root.GetComponentsInChildren<ScrollRect>(true)){
                if(scroll.verticalScrollbar!=null||!scroll.vertical)continue;
                var track=Rect("内容滚动条",scroll.transform,new Vector2(.985f,.015f),new Vector2(1,.985f));track.gameObject.AddComponent<AppRoundedImage>().color=new Color(.08f,.17f,.23f);
                var handle=Rect("滚动滑块",track,Vector2.zero,Vector2.one);var graphic=handle.gameObject.AddComponent<AppRoundedImage>();graphic.color=new Color(.15f,.58f,.65f);
                var bar=track.gameObject.AddComponent<Scrollbar>();bar.direction=Scrollbar.Direction.BottomToTop;bar.handleRect=handle;bar.targetGraphic=graphic;
                scroll.verticalScrollbar=bar;scroll.verticalScrollbarVisibility=ScrollRect.ScrollbarVisibility.AutoHide;
                scroll.viewport.offsetMax=new Vector2(-12,0);
            }
        }
        void RowButton(RectTransform parent,string label,Action action)
        {
            var row=Frame("章节入口",parent,Vector2.zero,Vector2.one);row.gameObject.AddComponent<LayoutElement>().preferredHeight=68;
            var button=row.gameObject.AddComponent<Button>();button.targetGraphic=row.GetComponent<Image>();button.onClick.AddListener(()=>{if(!busy)action();});
            TextAt(row,label,new Vector2(.025f,.02f),new Vector2(.975f,.98f),21);
        }
        void BuildSubsteps()
        {
            foreach(Transform child in substepTabs){child.gameObject.SetActive(false);Destroy(child.gameObject);}
            var steps=Current.substeps??new UnboxingSubstep[0];substepTabs.gameObject.SetActive(steps.Length>0);
            var scroll=body.parent.parent.GetComponent<RectTransform>();scroll.anchorMax=new Vector2(.985f,steps.Length>0?.65f:.82f);
            for(int i=0;i<steps.Length;i++){
                var sub=steps[i];float width=1f/steps.Length;
                var button=ButtonAt(substepTabs,"分步骤 "+(i+1),new Vector2(i*width,.08f),new Vector2((i+1)*width-.015f,.92f),()=>StartCoroutine(BrowseStep(run.state_id,sub.id)));
                if(sub.id==Current.selected_substep_id)button.GetComponent<Image>().color=new Color(.02f,.26f,.32f);
            }
        }
        IEnumerator BrowseStep(string state,string substep)
        {
            if(busy||run==null)yield break;busy=true;string error=null;var sent=run;
            yield return Request(Api+sent.run_id+"/browse","POST",JsonUtility.ToJson(new GuidanceBrowse{state_id=sent.state_id,revision=sent.revision,target_state_id=state,substep_id=substep}),
                (raw,e)=>{error=e;var incoming=e==null?ParseRun(raw):null;if(incoming!=null)Apply(incoming);});
            busy=false;if(error!=null)notice.text="切换未成功，请返回任务列表后重试。";
        }
        void RenderPlaceholder()
        {
            foreach(Transform t in placeholder.transform){t.gameObject.SetActive(false);Destroy(t.gameObject);}
            var outline=Scroll(placeholder.transform,new Vector2(.02f,.02f),new Vector2(.98f,.98f));
            Paragraph(outline,task.title+" · 步骤大纲",23,Cyan);
            for(int i=0;i<task.steps.Length;i++)Paragraph(outline,(i==run.step_index?"→ ":"")+(i+1)+". "+task.steps[i].title,19,i==run.step_index?Color.white:new Color(.6f,.72f,.82f));
            EnhanceScrolls();
        }
        protected override void Update()
        {
            if(AppShell.Changing)return;
            base.Update();
            if(cameraPanel.activeSelf){LayoutTeachingPanels();LayoutCamera();}
            primary.GetComponent<RectTransform>().anchorMin=new Vector2(.645f,cameraPanel.activeSelf?(cameraImage.texture!=null?.22f:.43f):.56f);
            primary.GetComponent<RectTransform>().anchorMax=new Vector2(.975f,cameraPanel.activeSelf?(cameraImage.texture!=null?.275f:.485f):.615f);
            foreach(var b in taskButtons)if(b!=null)b.interactable=connected&&!busy;
            resume.gameObject.SetActive(run!=null&&Current!=null&&Current.status!="cancelled");resume.interactable=!busy;
            aspectSelector.SetInteractable(!busy&&!starting);
            if(Current==null)return;
            bool active=Current.status=="running";
            primary.gameObject.SetActive(active&&!run.can_advance&&!run.completed);
            next.interactable=active&&!busy&&run.can_advance;back.interactable=active&&!busy&&run.can_back&&!run.completed;
            recheck.interactable=active&&!busy&&!run.completed;
            restart.gameObject.SetActive(string.IsNullOrEmpty(Current.parent_run_id));
            cancelChild.gameObject.SetActive(!string.IsNullOrEmpty(Current.parent_run_id)&&Current.can_cancel);
            cancelChild.interactable=!busy;
            if(Free){
                primary.gameObject.SetActive(active&&!run.completed&&(run.channel=="vision"||Array.IndexOf(Current.user_marked_step_ids??new string[0],run.state_id)<0));
                primary.GetComponentInChildren<Text>().text=run.channel=="vision"?"拍照，获取参考意见":"标记本章已操作（可选）";
                next.interactable=active&&!busy&&!run.completed;back.interactable=active&&!busy&&run.can_back;
                if(notice.text.Contains("HTTP ")||notice.text.Contains("同步进度"))notice.text="请求未完成，请重试；仍有问题可返回任务列表后重试。";
            }
            if(!Free&&active&&run.state_id=="P3"&&!run.can_advance)primary.GetComponentInChildren<Text>().text="我已完成耗材准备，确认";
        }
        protected override IEnumerator Connect(bool reset)
        {
            if(busy||settings==null)yield break;busy=true;lastError="";string error=null;
            if(catalog==null){try{catalog=JsonUtility.FromJson<GuidanceCatalog>(File.ReadAllText(Path.Combine(Application.streamingAssetsPath,"GuidanceCatalog.json")));RenderCatalog();}catch(Exception){}}
            yield return Request("/api/guidance/tasks","GET",null,(raw,e)=>{error=e;if(e==null){var incoming=Parse<GuidanceCatalog>(raw);if(incoming!=null&&incoming.tasks!=null){catalog=incoming;connected=true;RenderCatalog();}}});
            if(error==null&&reset&&Current!=null){
                string taskId=Current.task_id,variant=Current.variant_id;
                if(!run.completed||!string.IsNullOrEmpty(Current.parent_run_id))yield return CancelFlow();
                if(string.IsNullOrEmpty(lastError)){run=null;yield return CreateRun(taskId,variant);}
            }else if(error==null&&run!=null){
                yield return Request(Api+run.run_id,"GET",null,(raw,e)=>{error=e;var incoming=e==null?ParseRun(raw):null;if(incoming!=null)Apply(incoming);else if(e!=null&&e.StartsWith("HTTP 404")){run=null;ShowCatalog();}});
            }
            busy=false;
            if(error!=null){connected=false;catalogStatus.text="教学服务暂时未连接，请稍后重试。";notice.text=catalogStatus.text;}
            else catalogStatus.text="选择任务开始指导。设备已准备好的用户可直接进入首次打印。";
        }
        protected override void Apply(UnboxingRun value)
        {
            var incoming=value as GuidanceRun;
            if(incoming==null||incoming.task_info==null){notice.text="任务资料暂不可用，请返回任务列表后重试。";return;}
            if(run==null||run.run_id!=incoming.run_id){shownState="";CloseModal();}
            task=incoming.task_info;sequence=Mathf.Max(sequence,incoming.last_client_frame_id);
            string key=incoming.run_id+"/"+incoming.state_id+"/"+incoming.selected_substep_id;
            if(presentationKey!=key){shownState="";photoIndex=0;referenceImage.uvRect=new Rect(0,0,1,1);presentationKey=key;}
            base.Apply(incoming);catalogPanel.SetActive(false);BindTaskBack();BuildActions(incoming);BuildSubsteps();
            count.text=run.completed?"本任务已完成":"第 "+(run.step_index+1)+" / "+run.step_count+" 步";
            referencePanel.anchorMin=new Vector2(.025f,.15f);referencePanel.anchorMax=new Vector2(.625f,.49f);
            bool visual=Array.Exists(run.observations??new UnboxingObservation[0],n=>n.channel=="vision")&&!run.completed;
            cameraPanel.SetActive(visual);manualPanel.SetActive(!visual);
            captureHelp.text=run.can_advance?"本步核验已完成。现场发生变化时，请重新核验。":run.capture_instruction;checkTarget.text=string.IsNullOrEmpty(run.pending_id)?"本步所需图像已核验":"本次核验："+ConditionLabel(run.pending_id,run.current_condition);
            cameraCaption.text=frozen?"本次拍摄快照 · 标注仅对应此帧":"相机预览 · 点击拍摄后才上传";
            manualHelp.text=run.completed?CompletionMessage:run.can_advance?"✓ 本步已确认。点击右下角进入下一步。":ConditionLabel(run.pending_id,run.current_condition)+"\n\n完成上述操作后，点击下方确认。";
            if(incoming.status=="waiting_child")manualHelp.text=incoming.flow_notice+"\n请选择下面的后续操作。";
            else if(!string.IsNullOrEmpty(incoming.flow_notice))manualHelp.text=incoming.flow_notice;
            if(incoming.child_receipts!=null)foreach(var receipt in incoming.child_receipts)manualHelp.text+="\n"+receipt.title+" · "+(receipt.status=="completed"?"已完成":"已取消");
            result.text="等待拍摄检查。";
            foreach(var observation in run.observations??new UnboxingObservation[0]){
                if(observation.channel!="vision"||observation.status=="not_started")continue;
                string label=observation.status=="completed"?"✓ 检查通过":observation.failure_kind=="provider_error"?"服务连接失败":observation.failure_kind=="invalid_contract"?"回复格式异常":observation.status=="wrong_operation"?"需要调整":"需要补充画面";
                result.text=label+"\n"+observation.evidence+(string.IsNullOrEmpty(observation.correction)?"":"\n"+observation.correction);
                result.color=observation.status=="completed"?new Color(.3f,1,.7f):new Color(1,.79f,.48f);
            }
            notice.text=run.completed?"指导记录已保存。":run.can_advance?"本步已完成。":visual?"左侧对照官方示例，右侧拍摄并查看检查结果。":"先阅读左侧操作说明，完成后确认。";
            if(Free){
                for(int i=0;i<progress.Length;i++){progress[i].text=(i+1).ToString();progress[i].color=i==run.step_index?Cyan:new Color(.5f,.6f,.7f);}
                count.text=run.completed?"本次浏览已结束":"第 "+(run.step_index+1)+" / "+run.step_count+" 章";
                captureHelp.text=run.capture_instruction;cameraCaption.text=frozen?"最近一次拍摄的照片":"相机预览";
                result.text="尚未拍照。完成本章操作后可询问 AI，也可直接查看其他章节。";result.color=new Color(.74f,.82f,.9f);
                foreach(var observation in run.observations??new UnboxingObservation[0]){
                    if(observation.channel!="vision"||observation.status=="not_started")continue;
                    string status=observation.failure_kind=="provider_error"?"AI 服务暂不可用":observation.failure_kind=="invalid_contract"?"AI 回复异常，请重试":observation.status=="completed"?"最近一次拍照参考 · 可见状态符合":observation.status=="wrong_operation"?"最近一次拍照参考 · 建议调整":"最近一次拍照参考 · 暂不能确认";
                    result.color=observation.status=="completed"?Cyan:new Color(1,.79f,.48f);
                    result.text=status+"\n"+observation.evidence+(string.IsNullOrEmpty(observation.correction)?"":"\n"+observation.correction);
                }
                manualHelp.text=run.completed?"已结束本次教程浏览。你可以从步骤总览重新查看任意章节。":"本章无需拍照。\n请按左侧说明操作，可自由切换章节。";
                if(Array.IndexOf(incoming.user_marked_step_ids??new string[0],run.state_id)>=0)manualHelp.text+="\n\n你已将本章标记为已操作。";
                next.GetComponentInChildren<Text>().text=run.step_index==run.step_count-1?"结束本次浏览":"下一章 →";
                notice.text=run.completed?"本次浏览记录已保存。":"可随时从步骤总览跳转；拍照建议不影响浏览。";
            }
            captureHelp.text=ReadableText(captureHelp.text).Replace("；","；\n");manualHelp.text=ReadableText(manualHelp.text);result.text=ReadableText(result.text);
            previewLayout=null;LayoutTeachingPanels();StartCoroutine(FinishTextLayout(++textLayoutGeneration));
            if(placeholder.activeSelf)RenderPlaceholder();
            if(overviewRuns.Add(incoming.run_id))ShowOverview(true);
        }
        protected override IEnumerator Verify()
        {
            int before=run!=null?run.revision:-1;
            yield return base.Verify();
            // Base capture verifies frame identity and downloads its annotation; retain one result area.
            if(Current!=null&&run.revision!=before){var saved=run;Apply(saved);frozen=true;cameraCaption.text=Free?"本次拍摄的照片":"本次检查快照 · 标注仅对应此帧";}
        }
        void ShowCatalog()
        {
            if(busy)return;StopCamera();ShowLive();CloseModal();catalogPanel.SetActive(true);catalogPanel.transform.SetAsLastSibling();
            AppShell.BindTeachingBack();
            catalogStatus.text=connected?"请选择任务；也可继续当前指导。":"教学服务暂时未连接，请稍后重试。";
        }
        void BindTaskBack(){AppShell.BindBack("返回任务列表",ShowCatalog,()=>!busy&&!starting);}
        void RenderCatalog(){
            taskButtons.Clear();taskMenu.Clear();foreach(var texture in thumbnails)if(texture!=null)Destroy(texture);thumbnails.Clear();int generation=++catalogGeneration;
            if(catalog==null||catalog.tasks==null)return;
            foreach(var entry in catalog.tasks){
                var item=entry;var card=taskMenu.Add(item.id,item.title,item.description,true,()=>SelectTask(item));taskButtons.Add(card.Button);StartCoroutine(LoadThumbnail(item.thumbnail,card.Image,generation));
            }
            if(catalogPanel.activeSelf)catalogPanel.transform.SetAsLastSibling();
        }
        IEnumerator LoadThumbnail(GuidanceThumbnail photo,RawImage target,int generation)
        {
            byte[] data=null;try{string path=Path.Combine(Application.streamingAssetsPath,photo.local_file);if(File.Exists(path))data=File.ReadAllBytes(path);}catch(Exception){}
            if(data!=null&&Hash(data)!=photo.sha256)data=null;
            if(data==null)yield return Bytes(photo.url,bytes=>data=bytes);
            if(generation!=catalogGeneration||target==null||data==null||Hash(data)!=photo.sha256)yield break;
            var texture=new Texture2D(2,2,TextureFormat.RGBA32,false);
            if(ImageConversion.LoadImage(texture,data)){target.texture=texture;target.color=Color.white;target.GetComponent<AspectRatioFitter>().aspectRatio=(float)texture.width/texture.height;thumbnails.Add(texture);}else Destroy(texture);
        }
        void SelectTask(GuidanceTaskEntry entry)
        {
            if(busy||!connected)return;
            if(entry.variants.Length==1){StartSelected(entry.id,entry.default_variant);return;}
            CloseModal();modal=Frame("选择打印入口",root,new Vector2(.20f,.22f),new Vector2(.80f,.76f)).gameObject;
            TextAt(modal.transform,entry.id=="a1_mini_standalone_unboxing_v1"?"选择开箱版本":"选择打印方式",new Vector2(.06f,.76f),new Vector2(.94f,.95f),28).color=Cyan;
            for(int i=0;i<entry.variants.Length;i++){
                var variant=entry.variants[i];float y=.48f-i*.22f;
                ButtonAt(modal.transform,variant.title,new Vector2(.06f,y),new Vector2(.94f,y+.16f),()=>{CloseModal();StartSelected(entry.id,variant.id);});
            }
            ButtonAt(modal.transform,"取消",new Vector2(.60f,.025f),new Vector2(.94f,.17f),CloseModal);
        }
        void StartSelected(string taskId,string variant)
        {
            if(Current!=null&&(Current.status=="running"||Current.status=="waiting_child"||!string.IsNullOrEmpty(Current.parent_run_id))){
                CloseModal();modal=Frame("切换指导",root,new Vector2(.20f,.27f),new Vector2(.80f,.73f)).gameObject;
                TextAt(modal.transform,"开始新任务将结束当前指导，已有记录保留。是否继续？",new Vector2(.07f,.35f),new Vector2(.93f,.90f),26);
                ButtonAt(modal.transform,"结束当前指导并开始",new Vector2(.05f,.07f),new Vector2(.62f,.24f),()=>{CloseModal();StartCoroutine(BeginSelected(taskId,variant,true));});
                ButtonAt(modal.transform,"取消",new Vector2(.68f,.07f),new Vector2(.95f,.24f),CloseModal);
            }else StartCoroutine(BeginSelected(taskId,variant,false));
        }
        IEnumerator BeginSelected(string taskId,string variant,bool endOld)
        {
            if(busy)yield break;busy=true;lastError="";
            if(endOld)yield return CancelFlow();
            if(string.IsNullOrEmpty(lastError))yield return CreateRun(taskId,variant);
            busy=false;
        }
        IEnumerator CreateRun(string taskId,string variant)
        {
            yield return Request("/api/guidance/runs","POST",JsonUtility.ToJson(new GuidanceStart{task_id=taskId,variant_id=variant}),
                (raw,error)=>{if(error!=null){notice.text="操作未完成，请稍后重试。";catalogStatus.text=notice.text;lastError=error;}else{var incoming=ParseRun(raw);if(incoming!=null)Apply(incoming);else catalogStatus.text="任务响应无效。";}});
        }
        IEnumerator CancelFlow()
        {
            lastError="";if(run==null)yield break;
            yield return Request(Api+run.run_id+"/cancel-flow","POST",JsonUtility.ToJson(new UnboxingCommand{state_id=run.state_id,revision=run.revision}),
                (raw,error)=>{if(error!=null&&!error.StartsWith("HTTP 404")){lastError=error;notice.text="操作未完成，请稍后重试。";catalogStatus.text=notice.text;}else run=null;});
        }
        void BuildActions(GuidanceRun value)
        {
            foreach(Transform t in actionsPanel.transform){t.gameObject.SetActive(false);Destroy(t.gameObject);}
            var actions=value.available_actions??new GuidanceAction[0];actionsPanel.SetActive(actions.Length>0);
            if(actions.Length==0)return;

            for(int i=0;i<actions.Length;i++){
                var action=actions[i];float h=.84f/actions.Length,y=.95f-(i+1)*h;
                ButtonAt(actionsPanel.transform,action.label,new Vector2(.025f,y),new Vector2(.975f,y+h-.04f),()=>{
                    if(action.id=="retry")RetryDialog();else StartCoroutine(TaskAction(action.id,false));});
            }
        }
        IEnumerator TaskAction(string id,bool confirmed)
        {
            if(busy||run==null)yield break;busy=true;var sent=run;string failure=null;
            yield return Request(Api+sent.run_id+"/actions/"+id,"POST",JsonUtility.ToJson(new GuidanceActionCommand{state_id=sent.state_id,revision=sent.revision,confirmed=confirmed}),
                (raw,error)=>{failure=error;var incoming=error==null?ParseRun(raw):null;if(incoming!=null)Apply(incoming);});
            busy=false;if(failure!=null)notice.text="操作未成功，请返回任务列表后重试。";
        }
        void RetryDialog()
        {
            CloseModal();modal=Frame("设备重试",root,new Vector2(.20f,.27f),new Vector2(.80f,.73f)).gameObject;
            TextAt(modal.transform,"请先按打印机提示选择重试。确认后，本应用返回对应操作步骤，并清除受影响的核验记录。",new Vector2(.06f,.35f),new Vector2(.94f,.91f),25);
            ButtonAt(modal.transform,"已在设备选择重试",new Vector2(.04f,.06f),new Vector2(.64f,.23f),()=>{CloseModal();StartCoroutine(TaskAction("retry",true));});
            ButtonAt(modal.transform,"取消",new Vector2(.70f,.06f),new Vector2(.96f,.23f),CloseModal);
        }
        IEnumerator CancelChild()
        {
            if(busy||run==null)yield break;busy=true;string failure=null;
            yield return Request(Api+run.run_id+"/cancel","POST",JsonUtility.ToJson(new UnboxingCommand{state_id=run.state_id,revision=run.revision}),
                (raw,error)=>{failure=error;var incoming=error==null?ParseRun(raw):null;if(incoming!=null)Apply(incoming);});
            busy=false;if(failure!=null)notice.text="操作未成功，请返回任务列表后重试。";
        }
        protected override void CloseModal()
        {
            base.CloseModal();if(modalTexture!=null){Destroy(modalTexture);modalTexture=null;}
        }
        protected override void EnlargeReference()
        {
            if(referenceTexture==null)return;
            var uv=referenceImage.uvRect;if(uv==new Rect(0,0,1,1)){base.EnlargeReference();return;}
            CloseModal();int w=Mathf.RoundToInt(referenceTexture.width*uv.width),h=Mathf.RoundToInt(referenceTexture.height*uv.height);
            modalTexture=new Texture2D(w,h,TextureFormat.RGB24,false);modalTexture.SetPixels(referenceTexture.GetPixels(Mathf.RoundToInt(referenceTexture.width*uv.x),Mathf.RoundToInt(referenceTexture.height*uv.y),w,h));modalTexture.Apply();
            modal=Frame("查看官方动图当前帧",root,new Vector2(.04f,.08f),new Vector2(.96f,.91f)).gameObject;
            var picture=Rect("官方当前帧",modal.transform,new Vector2(.03f,.14f),new Vector2(.97f,.97f)).gameObject.AddComponent<RawImage>();picture.texture=modalTexture;
            var fit=picture.gameObject.AddComponent<AspectRatioFitter>();fit.aspectMode=AspectRatioFitter.AspectMode.FitInParent;fit.aspectRatio=(float)w/h;
            ButtonAt(modal.transform,"返回动图",new Vector2(.70f,.02f),new Vector2(.97f,.10f),CloseModal);
        }
        protected override IEnumerator LoadReference()
        {
            referenceImage.uvRect=new Rect(0,0,1,1);
            foreach(var texture in animationTextures)if(texture!=null){if(referenceTexture==texture)referenceTexture=null;Destroy(texture);}animationTextures.Clear();
            if(run==null)yield break;var photos=run.presentation.images;
            if(photos==null||photos.Length==0){photoGeneration++;yield break;}
            photoIndex=Mathf.Clamp(photoIndex,0,photos.Length-1);var photo=photos[photoIndex];
            if(photo.animation_frames==null||photo.animation_frames.Length==0){yield return base.LoadReference();yield break;}
            int generation=++photoGeneration;if(referenceTexture!=null){Destroy(referenceTexture);referenceTexture=null;}referenceCaption.text="官方参考图 "+(photoIndex+1)+" / "+photos.Length+" · 动图";
            string atlasFile="";Texture2D atlas=null;
            while(generation==photoGeneration&&referencePanel.gameObject.activeSelf){
                foreach(var frame in photo.animation_frames){
                    if(generation!=photoGeneration)yield break;
                    if(atlasFile!=frame.local_file){
                        byte[] bytes=null;try{var path=Path.Combine(Application.streamingAssetsPath,frame.local_file);if(File.Exists(path))bytes=File.ReadAllBytes(path);}catch(Exception){}
                        if(bytes!=null&&Hash(bytes)!=frame.sha256)bytes=null;if(bytes==null)yield return Bytes(frame.url,data=>bytes=data);
                        if(generation!=photoGeneration)yield break;
                        if(bytes==null||Hash(bytes)!=frame.sha256){referenceCaption.text="动图读取失败，可切换其他官方参考图。";yield break;}
                        var nextAtlas=new Texture2D(2,2,TextureFormat.RGB24,false);
                        if(!ImageConversion.LoadImage(nextAtlas,bytes)){Destroy(nextAtlas);yield break;}
                        if(atlas!=null){animationTextures.Remove(atlas);Destroy(atlas);}atlas=nextAtlas;animationTextures.Add(atlas);atlasFile=frame.local_file;
                        referenceTexture=atlas;referenceImage.texture=atlas;LayoutReference();
                    }
                    referenceImage.uvRect=new Rect(frame.uv[0],frame.uv[1],frame.uv[2],frame.uv[3]);
                    yield return new WaitForSecondsRealtime(frame.duration_ms/1000f);
                }
            }
        }
        protected override void OnDisable()
        {
            Canvas.willRenderCanvases-=RefreshForDisplayScale;base.OnDisable();foreach(var texture in animationTextures)if(texture!=null)Destroy(texture);animationTextures.Clear();foreach(var texture in thumbnails)if(texture!=null)Destroy(texture);thumbnails.Clear();
        }
    }
}
