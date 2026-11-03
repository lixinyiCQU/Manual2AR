using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Security.Cryptography;
using System.Text;
using UnityEngine;
using UnityEngine.EventSystems;
using UnityEngine.Networking;
using UnityEngine.UI;

namespace Manual2AR
{
    /// <summary>A single audited task. Human and visual checks use different server commands.</summary>
    public abstract class GuidanceStepView : MonoBehaviour, IAppModule
    {
        protected static readonly Color Navy=new Color(.018f,.04f,.085f),Panel=new Color(.025f,.085f,.15f),Cyan=new Color(0,.85f,.94f),Purple=new Color(.75f,.24f,.85f);
        protected abstract string Api {get;}
        protected abstract string ConfigFile {get;}
        protected abstract string SetupHint {get;}
        protected abstract string TaskTitle {get;}
        protected abstract string CompletionMessage {get;}
        protected abstract string FinishLabel {get;}
        protected UnboxingSettings settings;protected UnboxingTask task;protected UnboxingRun run;protected Font font;
        protected RectTransform root,cameraArea,cameraRect,referencePanel,referenceArea,referenceRect,body;
        protected RawImage cameraImage,referenceImage;protected GameObject cameraPanel,placeholder,modal;
        protected Text title,count,notice,result,referenceCaption,cameraCaption;protected Text[] progress;
        protected Button primary,next,back,recheck,startCamera,live,previousPhoto,nextPhoto,restart;
        protected CameraFraming framing;protected AppAspectSelector aspectSelector;
        protected Dropdown devices;protected WebCamTexture webcam;protected Texture2D snapshot,referenceTexture;
        protected bool busy,starting,frozen;protected int sequence,photoIndex,photoGeneration;protected string shownState="",lastError="";

        protected virtual void Start()
        {
            font=AppTheme.Font;
            framing=gameObject.AddComponent<CameraFraming>();
            BuildUI();
            try{settings=JsonUtility.FromJson<UnboxingSettings>(File.ReadAllText(Path.Combine(Application.streamingAssetsPath,ConfigFile)));}
            catch(Exception){notice.text="教学资料尚未就绪，请稍后重试。";return;}
            settings.backend_url=AppShell.BackendUrl(settings.backend_url);
            RefreshDevices();StartCoroutine(Connect(false));
        }
        protected virtual void Update()
        {
            if(AppShell.Changing)return;
            if(run==null||settings==null)return;
            bool visual=run.channel=="vision"&&!run.completed;
            primary.gameObject.SetActive(!run.completed&&!run.can_advance);
            primary.interactable=!busy&&(run.channel=="manual"||(visual&&webcam!=null&&webcam.isPlaying&&webcam.width>16));
            next.interactable=!busy&&run.can_advance;back.interactable=!busy&&run.can_back&&!run.completed;
            recheck.interactable=!busy&&!run.completed;startCamera.interactable=!busy&&!starting;
            aspectSelector.SetInteractable(!busy&&!starting);devices.interactable=!busy&&!starting;live.interactable=!busy&&webcam!=null&&webcam.isPlaying;
            restart.interactable=!busy;
            previousPhoto.interactable=!busy&&photoIndex>0;
            nextPhoto.interactable=!busy&&run.presentation.images!=null&&photoIndex+1<run.presentation.images.Length;
            if(visual&&webcam!=null&&webcam.isPlaying&&!frozen){cameraImage.texture=framing.Live(webcam,1280);LayoutCamera();}
            LayoutReference();
        }
        protected string Hash(byte[] data){using(var sha=SHA256.Create())return BitConverter.ToString(sha.ComputeHash(data)).Replace("-","").ToLowerInvariant();}
        protected T Parse<T>(string value) where T:class {try{return JsonUtility.FromJson<T>(value);}catch{return null;}}
        protected virtual UnboxingRun ParseRun(string raw) { return Parse<UnboxingRun>(raw); }
        protected IEnumerator Request(string path,string method,string json,Action<string,string> done)
        {
            using(var request=new UnityWebRequest(settings.backend_url.TrimEnd('/')+path,method)){
                request.downloadHandler=new DownloadHandlerBuffer();request.timeout=settings.request_timeout_seconds;
                if(json!=null)request.uploadHandler=new UploadHandlerRaw(Encoding.UTF8.GetBytes(json));
                request.SetRequestHeader("Content-Type","application/json");
                UnityWebRequestAsyncOperation operation=null;string failure=null;
                try{operation=request.SendWebRequest();}catch(Exception e){failure=e.Message;}
                if(operation==null){done(null,failure);yield break;}
                yield return operation;
                if(request.result!=UnityWebRequest.Result.Success){
                    var error=Parse<UnboxingError>(request.downloadHandler.text);
                    failure="HTTP "+request.responseCode+" "+(error!=null&&!string.IsNullOrEmpty(error.detail)?error.detail:request.error);
                }
                done(request.downloadHandler.text,failure);
            }
        }
        protected IEnumerator Bytes(string path,Action<byte[]> done)
        {
            using(var r=UnityWebRequest.Get(settings.backend_url.TrimEnd('/')+path)){
                r.timeout=settings.request_timeout_seconds;yield return r.SendWebRequest();
                done(r.result==UnityWebRequest.Result.Success?r.downloadHandler.data:null);
            }
        }
        protected abstract IEnumerator Connect(bool reset);
        protected virtual void Apply(UnboxingRun value)
        {
            if(task==null||value.task_revision!=task.task_revision){notice.text="任务版本不匹配，请重新连接。";return;}
            bool changed=shownState!=value.state_id;run=value;shownState=value.state_id;lastError="";
            title.text=TaskTitle;
            if(progress.Length!=value.step_count)BuildProgress(value.step_count);
            count.text=value.completed?"本任务已完成":"步骤 "+(value.step_index+1)+" / "+value.step_count+"";
            for(int i=0;i<progress.Length;i++){
                progress[i].text=(i<value.step_index||value.completed?"✓ ":"")+(i+1).ToString();
                progress[i].color=i==value.step_index?Cyan:(i<value.step_index?new Color(.3f,.9f,.65f):new Color(.5f,.6f,.7f));
            }
            bool visual=Array.Exists(value.observations??new UnboxingObservation[0],n=>n.channel=="vision")&&!value.completed;
            cameraPanel.SetActive(visual);
            if(!visual)StopCamera();
            referencePanel.anchorMin=visual?new Vector2(.025f,.145f):new Vector2(.025f,.20f);
            referencePanel.anchorMax=visual?new Vector2(.37f,.355f):new Vector2(.61f,.84f);
            primary.GetComponentInChildren<Text>().text=value.channel=="manual"?"我已完成，确认本项":"拍摄并检查当前项";
            next.GetComponentInChildren<Text>().text=value.step_index==value.step_count-1?FinishLabel:"下一步 →";
            result.text=value.completed?CompletionMessage:
                value.can_advance?"✓ 本步全部检查项已完成，可以进入下一步。":value.channel=="manual"?"按说明完成操作后，点击确认。":"按拍摄指导移动手机或摄像头，再拍摄检查。";
            result.color=value.can_advance||value.completed?new Color(.2f,1,.65f):Cyan;
            notice.text=value.can_advance?"本步所有检查项已完成，点击下一步。":visual?value.capture_instruction:(value.completed?"完成记录已保存在后端，可打开任务记录查看。":"请阅读本步说明与参考图。");
            RebuildBody();
            if(changed){photoIndex=0;ShowLive();}
            referencePanel.gameObject.SetActive(value.presentation.images!=null&&value.presentation.images.Length>0);
            placeholder.SetActive(!visual&&(value.presentation.images==null||value.presentation.images.Length==0));
            StartCoroutine(LoadReference());
        }
        protected virtual void RebuildBody()
        {
            foreach(Transform t in body){t.gameObject.SetActive(false);Destroy(t.gameObject);}
            Paragraph(run.presentation.title,29,Cyan);
            Paragraph(run.presentation.instruction,24,Color.white);
            if(run.presentation.tools!=null&&run.presentation.tools.Length>0)Paragraph("工具："+string.Join("、",run.presentation.tools),20,Color.white);
            if(run.presentation.materials!=null&&run.presentation.materials.Length>0)Paragraph("物料："+string.Join("、",run.presentation.materials),20,Color.white);
            int passed=0;foreach(var n in run.observations??new UnboxingObservation[0])if(n.status=="completed")passed++;
            Paragraph("本步检查：已完成 "+passed+" / "+run.observations.Length+" 项",21,Cyan);
            if(!string.IsNullOrEmpty(run.current_condition))Paragraph((run.channel=="manual"?"请确认：":"当前检查：")+"\n"+ConditionLabel(run.pending_id,run.current_condition),23,Cyan);
            foreach(var n in run.observations??new UnboxingObservation[0]){
                if(n.status=="not_started")continue;
                string symbol=n.status=="completed"?"✓ ":n.status=="wrong_operation"?"✕ ":"○ ";
                Paragraph(symbol+ConditionLabel(n.id,n.condition),20,n.status=="completed"?new Color(.3f,1,.7f):Color.white);
                if(!string.IsNullOrEmpty(n.evidence)&&!(n.channel=="manual"&&ConditionLabel(n.id,n.condition)!=n.condition))Paragraph((n.channel=="manual"?"用户确认：":"可见证据：")+n.evidence,19,new Color(.75f,.85f,.91f));
                if(!string.IsNullOrEmpty(n.correction))Paragraph("处理建议："+n.correction,21,new Color(1,.65f,.4f));
            }
            foreach(var warning in run.presentation.warnings??new string[0])Paragraph("提醒："+warning,19,new Color(1,.77f,.4f));
            LayoutRebuilder.ForceRebuildLayoutImmediate(body);
        }
        protected string ConditionLabel(string id,string fallback)
        {
            foreach(var label in run.presentation.display_conditions??new UnboxingDisplayCondition[0])if(label.id==id)return label.text;
            return fallback;
        }
        protected IEnumerator Command(string action)
        {
            if(busy||run==null)yield break;busy=true;
            var sent=run;string error=null;
            yield return Request(Api+sent.run_id+"/"+action,"POST",JsonUtility.ToJson(new UnboxingCommand{state_id=sent.state_id,revision=sent.revision}),
                (raw,e)=>{error=e;var incoming=e==null?ParseRun(raw):null;if(incoming!=null){if(action=="recheck")ShowLive();Apply(incoming);}});
            busy=false;if(error!=null)notice.text="操作未完成，请稍后重试。";
        }
        protected IEnumerator Confirm()
        {
            if(busy||run==null||run.channel!="manual")yield break;busy=true;var sent=run;string error=null;
            yield return Request(Api+sent.run_id+"/confirm","POST",JsonUtility.ToJson(new UnboxingConfirmation{
                state_id=sent.state_id,revision=sent.revision,inspection_id=sent.pending_id,confirmed=true}),
                (raw,e)=>{error=e;var incoming=e==null?ParseRun(raw):null;if(incoming!=null)Apply(incoming);});
            busy=false;if(error!=null)notice.text="操作未完成，请稍后重试。";
        }
        protected virtual void Primary(){if(run==null||busy)return;if(run.channel=="manual")StartCoroutine(Confirm());else StartCoroutine(Verify());}
        protected void RefreshDevices()
        {
            devices.ClearOptions();var list=new List<string>();int preferred=0;
            for(int i=0;i<WebCamTexture.devices.Length;i++){var d=WebCamTexture.devices[i];list.Add(d.name);if(d.name==settings.camera_name)preferred=i;}
            if(list.Count==0)list.Add("未发现摄像头");devices.AddOptions(list);devices.value=preferred;
        }
        protected IEnumerator StartCamera()
        {
            if(starting||busy||run==null||run.channel!="vision")yield break;starting=true;
            if(!Application.HasUserAuthorization(UserAuthorization.WebCam))yield return Application.RequestUserAuthorization(UserAuthorization.WebCam);
            if(run==null||run.channel!="vision"){starting=false;yield break;}
            if(!Application.HasUserAuthorization(UserAuthorization.WebCam)){notice.text="请允许应用使用摄像头。";starting=false;yield break;}
            StopCamera();var available=WebCamTexture.devices;
            if(available.Length==0){notice.text="未发现摄像头，请连接后点击同步。";starting=false;yield break;}
            int selected=Mathf.Clamp(devices.value,0,available.Length-1);
            webcam=new WebCamTexture(available[selected].name,settings.camera_width,settings.camera_height,settings.camera_fps);webcam.Play();
            float limit=Time.realtimeSinceStartup+15;
            while(webcam!=null&&webcam.width<=16&&Time.realtimeSinceStartup<limit)yield return null;
            starting=false;
            if(run==null||run.channel!="vision"){StopCamera();yield break;}
            if(webcam==null||webcam.width<=16){StopCamera();notice.text="摄像头未就绪，请检查占用和权限后重试。";}
            else{ShowLive();notice.text=run.capture_instruction;}
        }
        protected void StopCamera(){if(webcam!=null){webcam.Stop();Destroy(webcam);webcam=null;}cameraImage.texture=null;}
        protected void ShowLive(){frozen=false;if(snapshot!=null){Destroy(snapshot);snapshot=null;}if(webcam!=null)cameraImage.texture=framing.Live(webcam,1280);cameraCaption.text="实时取景 · 拍摄时提交一张当前图像";}
        protected Texture2D CaptureCamera(){return framing.Capture(webcam,webcam.videoRotationAngle,webcam.videoVerticallyMirrored,1280);}
        protected void ChangeFraming(int index){
            if(busy||starting)return;framing.SetAspect(index);ShowLive();LayoutCamera();result.text="画幅已调整，请重新拍照查看结果。";
        }
        protected virtual IEnumerator Verify()
        {
            if(busy||run==null||run.channel!="vision"||webcam==null||webcam.width<=16)yield break;
            Texture2D frame=null;string captureError=null;
            try{frame=CaptureCamera();}catch(Exception e){captureError=e.Message;}
            if(frame==null){notice.text="拍摄失败："+captureError;yield break;}
            busy=true;frozen=true;if(snapshot!=null)Destroy(snapshot);snapshot=frame;cameraImage.texture=frame;LayoutCamera();
            byte[] bytes=frame.EncodeToJPG(92);string sha=Hash(bytes),error=null;int sentFrame=++sequence;var sent=run;
            cameraCaption.text="正在检查本次拍摄的照片";notice.text="正在核验当前项，请等待结果……";
            UnboxingRun incoming=null;
            yield return Request(Api+sent.run_id+"/verify","POST",JsonUtility.ToJson(new UnboxingCapture{
                state_id=sent.state_id,revision=sent.revision,inspection_id=sent.pending_id,client_frame_id=sentFrame,
                image_base64=Convert.ToBase64String(bytes),source_sha256=sha}),
                (raw,e)=>{error=e;if(e==null)incoming=ParseRun(raw);});
            UnboxingObservation checkedItem=null;
            if(incoming!=null&&incoming.run_id==sent.run_id&&incoming.state_id==sent.state_id&&incoming.revision==sent.revision+1)
                foreach(var n in incoming.observations??new UnboxingObservation[0])if(n.id==sent.pending_id&&n.frame_id==sentFrame&&n.source_sha256==sha)checkedItem=n;
            if(checkedItem==null){busy=false;notice.text="本次检查未完成，请重新拍摄。";yield break;}
            Apply(incoming);frozen=true;
            cameraCaption.text="本次拍摄的照片";
            if(!string.IsNullOrEmpty(checkedItem.image_url)){
                byte[] annotated=null;yield return Bytes(checkedItem.image_url,data=>annotated=data);
                if(annotated!=null){var texture=new Texture2D(2,2,TextureFormat.RGB24,false);if(ImageConversion.LoadImage(texture,annotated)){Destroy(snapshot);snapshot=texture;cameraImage.texture=snapshot;LayoutCamera();}else Destroy(texture);}
            }
            result.text=checkedItem.status=="completed"?"✓ 当前项通过\n"+checkedItem.evidence:
                (checkedItem.status=="wrong_operation"?"检测到未完成或错误状态":"暂时无法判断")+"\n"+checkedItem.evidence+"\n"+checkedItem.correction;
            result.color=checkedItem.status=="completed"?new Color(.2f,1,.65f):checkedItem.status=="wrong_operation"?new Color(1,.35f,.4f):new Color(1,.78f,.35f);
            notice.text=run.can_advance?"本步所有观察点通过。点击下一步。":"点击实时预览重新取景，再检查当前待办项。";
            busy=false;
        }
        protected void LayoutCamera(){
            var texture=cameraImage.texture;if(texture==null)return;float scale=Mathf.Min(cameraArea.rect.width/texture.width,cameraArea.rect.height/texture.height);
            cameraRect.sizeDelta=new Vector2(texture.width*scale,texture.height*scale);cameraRect.localEulerAngles=Vector3.zero;cameraImage.uvRect=new Rect(0,0,1,1);
        }
        protected virtual void LayoutReference(){if(referenceTexture==null)return;float s=Mathf.Min(referenceArea.rect.width/referenceTexture.width,referenceArea.rect.height/referenceTexture.height);referenceRect.sizeDelta=new Vector2(referenceTexture.width*s,referenceTexture.height*s);}
        protected virtual IEnumerator LoadReference()
        {
            int generation=++photoGeneration;var photos=run.presentation.images;
            if(photos==null||photos.Length==0)yield break;
            photoIndex=Mathf.Clamp(photoIndex,0,photos.Length-1);var photo=photos[photoIndex];byte[] bytes=null;
            referenceCaption.text="官方参考图 "+(photoIndex+1)+" / "+photos.Length+" · "+photo.caption;
            try{string path=Path.Combine(Application.streamingAssetsPath,photo.local_file);if(File.Exists(path))bytes=File.ReadAllBytes(path);}catch(Exception){}
            if(bytes!=null&&Hash(bytes)!=photo.sha256)bytes=null;
            if(bytes==null)yield return Bytes(photo.url,data=>bytes=data);
            if(generation!=photoGeneration)yield break;
            if(bytes==null||Hash(bytes)!=photo.sha256){referenceCaption.text="参考图读取失败，请同步后重试。";yield break;}
            var texture=new Texture2D(2,2,TextureFormat.RGBA32,false);
            if(!ImageConversion.LoadImage(texture,bytes)){Destroy(texture);yield break;}
            if(referenceTexture!=null)Destroy(referenceTexture);referenceTexture=texture;referenceImage.texture=texture;LayoutReference();
        }
        protected void Sources()
        {
            if(run==null)return;CloseModal();modal=Frame("官方来源",root,new Vector2(.10f,.10f),new Vector2(.90f,.90f)).gameObject;
            var sheet=Scroll(modal.transform,new Vector2(.03f,.17f),new Vector2(.97f,.95f));
            Paragraph(sheet,"本步官方原文证据",29,Cyan);
            foreach(var source in run.presentation.sources??new UnboxingSource[0])Paragraph(sheet,source.text+"\n来源："+source.url+"\n采集："+source.captured_at+"\n引用："+source.id,20,Color.white);
            ButtonAt(modal.transform,"打开官方页面",new Vector2(.04f,.035f),new Vector2(.58f,.12f),()=>{if(run.presentation.sources.Length>0)Application.OpenURL(run.presentation.sources[0].url);});
            ButtonAt(modal.transform,"关闭",new Vector2(.65f,.035f),new Vector2(.96f,.12f),CloseModal);
        }
        protected virtual void CloseModal(){if(modal!=null){Destroy(modal);modal=null;}}
        protected virtual void EnlargeReference()
        {
            if(referenceTexture==null)return;CloseModal();modal=Frame("查看参考图",root,new Vector2(.04f,.08f),new Vector2(.96f,.91f)).gameObject;
            var image=Rect("Official photo",modal.transform,new Vector2(.03f,.14f),new Vector2(.97f,.97f)).gameObject.AddComponent<RawImage>();
            image.texture=referenceTexture;image.raycastTarget=false;var fit=image.gameObject.AddComponent<AspectRatioFitter>();fit.aspectMode=AspectRatioFitter.AspectMode.FitInParent;fit.aspectRatio=(float)referenceTexture.width/referenceTexture.height;
            ButtonAt(modal.transform,"关闭参考图",new Vector2(.70f,.02f),new Vector2(.97f,.10f),CloseModal);
        }
        protected void ResetDialog()
        {
            if(busy)return;CloseModal();modal=Frame("重新开始",root,new Vector2(.23f,.28f),new Vector2(.77f,.72f)).gameObject;
            TextAt(modal.transform,"重新开始将建立新的指导记录。已有日志保留；当前进度不再继续。",new Vector2(.07f,.35f),new Vector2(.93f,.9f),25);
            ButtonAt(modal.transform,"重新开始",new Vector2(.06f,.08f),new Vector2(.55f,.26f),()=>{CloseModal();StartCoroutine(Connect(true));});
            ButtonAt(modal.transform,"取消",new Vector2(.62f,.08f),new Vector2(.94f,.26f),CloseModal);
        }
        protected RectTransform Rect(string name,Transform parent,Vector2 min,Vector2 max){var o=new GameObject(name,typeof(RectTransform));o.transform.SetParent(parent,false);var r=o.GetComponent<RectTransform>();r.anchorMin=min;r.anchorMax=max;r.offsetMin=r.offsetMax=Vector2.zero;return r;}
        protected RectTransform Frame(string name,Transform parent,Vector2 min,Vector2 max){var r=Rect(name,parent,min,max);r.gameObject.AddComponent<AppRoundedImage>().color=Panel;var border=r.gameObject.AddComponent<Outline>();border.effectColor=Cyan*.7f;return r;}
        protected Text TextAt(Transform parent,string value,Vector2 min,Vector2 max,int size=23){var r=Rect("Text",parent,min,max);var t=r.gameObject.AddComponent<Text>();t.font=font;t.fontSize=size;t.text=value;t.color=Color.white;t.alignment=TextAnchor.MiddleLeft;t.raycastTarget=false;t.horizontalOverflow=HorizontalWrapMode.Wrap;t.verticalOverflow=VerticalWrapMode.Truncate;return t;}
        protected Button ButtonAt(Transform parent,string label,Vector2 min,Vector2 max,Action action){var r=Frame(label,parent,min,max);var b=r.gameObject.AddComponent<Button>();b.targetGraphic=r.GetComponent<Image>();b.onClick.AddListener(()=>action());var t=TextAt(r,label,new Vector2(.03f,.03f),new Vector2(.97f,.97f));t.alignment=TextAnchor.MiddleCenter;t.resizeTextForBestFit=true;t.resizeTextMinSize=12;t.resizeTextMaxSize=23;return b;}
        protected void Paragraph(string value,int size,Color color){Paragraph(body,value,size,color);}
        protected virtual void Paragraph(RectTransform parent,string value,int size,Color color){var o=new GameObject("Paragraph",typeof(RectTransform),typeof(Text),typeof(LayoutElement));o.transform.SetParent(parent,false);var t=o.GetComponent<Text>();t.font=font;t.fontSize=size;t.color=color;t.text=value;t.raycastTarget=false;t.horizontalOverflow=HorizontalWrapMode.Wrap;t.verticalOverflow=VerticalWrapMode.Overflow;}
        protected RectTransform Scroll(Transform parent,Vector2 min,Vector2 max){var area=Rect("Scroll",parent,min,max);area.gameObject.AddComponent<AppRoundedImage>().color=Panel;var scroll=area.gameObject.AddComponent<ScrollRect>();scroll.horizontal=false;var viewport=Rect("Viewport",area,Vector2.zero,Vector2.one);viewport.gameObject.AddComponent<RectMask2D>();var content=Rect("Content",viewport,new Vector2(0,1),new Vector2(1,1));content.pivot=new Vector2(.5f,1);var layout=content.gameObject.AddComponent<VerticalLayoutGroup>();layout.padding=new RectOffset(12,12,8,16);layout.spacing=16;layout.childControlHeight=true;layout.childControlWidth=true;layout.childForceExpandHeight=false;content.gameObject.AddComponent<ContentSizeFitter>().verticalFit=ContentSizeFitter.FitMode.PreferredSize;scroll.viewport=viewport;scroll.content=content;return content;}
        protected Dropdown DropdownAt(Transform parent,Vector2 min,Vector2 max)
        {
            var r=Frame("Camera selector",parent,min,max);var d=r.gameObject.AddComponent<Dropdown>();d.targetGraphic=r.GetComponent<Image>();d.captionText=TextAt(r,"",new Vector2(.03f,.02f),new Vector2(.97f,.98f),19);
            var template=Frame("Template",r,new Vector2(0,0),new Vector2(1,0));template.pivot=new Vector2(.5f,1);template.sizeDelta=new Vector2(0,180);
            var scroll=template.gameObject.AddComponent<ScrollRect>();scroll.horizontal=false;var viewport=Rect("Viewport",template,Vector2.zero,Vector2.one);viewport.gameObject.AddComponent<RectMask2D>();
            var sheet=Rect("Content",viewport,new Vector2(0,1),new Vector2(1,1));sheet.pivot=new Vector2(.5f,1);sheet.sizeDelta=new Vector2(0,40);
            var item=Rect("Item",sheet,new Vector2(0,.5f),new Vector2(1,.5f));item.sizeDelta=new Vector2(0,40);var bg=item.gameObject.AddComponent<AppRoundedImage>();bg.color=Panel;var toggle=item.gameObject.AddComponent<Toggle>();toggle.targetGraphic=bg;
            var check=Rect("Check",item,new Vector2(.01f,.1f),new Vector2(.02f,.9f));toggle.graphic=check.gameObject.AddComponent<AppRoundedImage>();toggle.graphic.color=Cyan;
            d.itemText=TextAt(item,"",new Vector2(.04f,0),Vector2.one,19);d.template=template;scroll.viewport=viewport;scroll.content=sheet;template.gameObject.SetActive(false);return d;
        }
        protected void BuildProgress(int total)
        {
            if(progress!=null)foreach(var text in progress){text.gameObject.SetActive(false);Destroy(text.gameObject);}
            progress=new Text[total];float width=.94f/Mathf.Max(1,total);
            for(int i=0;i<total;i++){progress[i]=TextAt(root,""+(i+1),new Vector2(.03f+i*width,.895f),new Vector2(.03f+(i+1)*width,.928f),22);progress[i].alignment=TextAnchor.MiddleCenter;}
        }
        protected abstract void BuildUI();
        public IEnumerator ReleaseModule(){
            StopAllCoroutines();StopCamera();var identity=run==null?null:run.run_id;run=null;
            if(settings!=null&&!string.IsNullOrEmpty(identity))using(var request=UnityWebRequest.Delete(settings.backend_url.TrimEnd('/')+Api+identity)){request.timeout=8;yield return request.SendWebRequest();}
        }
        protected virtual void OnDisable(){StopAllCoroutines();StopCamera();if(snapshot!=null)Destroy(snapshot);if(referenceTexture!=null)Destroy(referenceTexture);CloseModal();busy=false;}
    }
}
