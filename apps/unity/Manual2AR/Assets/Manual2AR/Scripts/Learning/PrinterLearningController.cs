using System;
using System.Collections;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Security.Cryptography;
using System.Text;
using UnityEngine;
using UnityEngine.EventSystems;
using UnityEngine.Networking;
using UnityEngine.UI;
using Debug=UnityEngine.Debug;

namespace Manual2AR
{
    /// <summary>Camera-only learning workspace. Diagnostics remain in backend tools.</summary>
    public sealed class PrinterLearningController : MonoBehaviour, IAppModule
    {
        static readonly Color Navy=AppTheme.Background,Panel=AppTheme.PanelBackground,Cyan=AppTheme.TargetCyan;
        const string Prefix="/api/learning/runs/";
        LearningSettings settings;LearningKnowledge knowledge;
        readonly LearningInteractionState interaction=new LearningInteractionState();
        bool busy { get { return interaction.Busy; } set { interaction.Busy=value; } }
        UnityWebRequest inferenceRequest;Button clearButton;
        readonly Dictionary<string,LearningCard> cards=new Dictionary<string,LearningCard>(),byTarget=new Dictionary<string,LearningCard>();
        readonly Dictionary<string,LearningResult> results=new Dictionary<string,LearningResult>();
        readonly Dictionary<string,Text> rowLabels=new Dictionary<string,Text>();
        readonly Dictionary<string,Image> rowBackgrounds=new Dictionary<string,Image>();
        readonly List<Selectable> busyControls=new List<Selectable>();
        WebCamTexture webcam;Texture2D pairedFrame,spareFrame;CameraFraming framing;AppAspectSelector aspectSelector;
        readonly Dictionary<string,Texture2D> referencePhotos=new Dictionary<string,Texture2D>();
        RawImage preview;RectTransform root,imageArea,content,labelRoot,focusSheet;
        GameObject listPanel,focusPanel,modal;PrinterLearningOverlay overlay;Font font;
        int cameraIndex=-1;string activeProvider="sam31_cutie";
Text status,sourceLabel,focusTitle;
        bool trackingInFlight,userActionPending;int selectionGeneration;
        string runId,selected="",checkId="",detailId="";bool trackingActive,trackingPaused;float lastTrack;int sequence,detailGeneration,trackingFailures;

        bool LivePreview { get {return settings.preview_mode=="live";} }
        float lastResultCapture=-1,metricsSince,expiredSeconds;int renderFrames,cameraFrames,resultFrames,appliedFrames,slowFrames,gcBefore,skippedFrames;
        bool overlayExpired,performancePending;readonly List<float> frameTimes=new List<float>(256);
        int responseBytes,uploadBytes;
        void Start()
        {
            font=AppTheme.Font;
            try {
                settings=JsonUtility.FromJson<LearningSettings>(File.ReadAllText(Path.Combine(Application.streamingAssetsPath,"Learning.json")));
                knowledge=JsonUtility.FromJson<LearningKnowledge>(File.ReadAllText(Path.Combine(Application.streamingAssetsPath,settings.knowledge_file)));
                IndexKnowledge();
            } catch(Exception e) { Debug.LogError("[Learning] 请先运行 run.sh sync 同步公共配置与知识卡："+e.Message);enabled=false;return; }
            Application.targetFrameRate=settings.target_render_fps;metricsSince=Time.realtimeSinceStartup;gcBefore=GC.CollectionCount(0);
            QualitySettings.resolutionScalingFixedDPIFactor=1;
            #if !UNITY_EDITOR
            Screen.SetResolution(settings.ui_width,settings.ui_height,FullScreenMode.Windowed);
            #endif
            settings.backend_url=AppShell.BackendUrl(settings.backend_url);
            framing=gameObject.AddComponent<CameraFraming>();
            BuildUI();AppShell.BindTeachingBack();RefreshCameras();StartCoroutine(Connect());
        }
        void IndexKnowledge()
        {
            if(knowledge==null||knowledge.schema_version!="learning-knowledge-v3"||knowledge.cards==null||knowledge.cards.Length!=8) throw new InvalidDataException("需要V3版的八部件资料，请重新sync/package并使用对应后端。");
            cards.Clear();byTarget.Clear();
            foreach(var c in knowledge.cards) {cards[c.id]=c;if(!string.IsNullOrEmpty(c.target_id))byTarget[c.target_id]=c;}
        }
        void Update()
        {
            if(AppShell.Changing)return;
            if(settings==null||preview==null)return;
            renderFrames++;float frameMs=Time.unscaledDeltaTime*1000f;frameTimes.Add(frameMs);if(frameMs>33.333f)slowFrames++;
            if(webcam!=null&&webcam.isPlaying&&webcam.didUpdateThisFrame){cameraFrames++;if(busy&&trackingActive)skippedFrames++;}
            if(LivePreview&&webcam!=null&&webcam.isPlaying&&webcam.width>16)preview.texture=framing.Live(webcam,settings.capture_max_side);
            if(LivePreview&&lastResultCapture>=0){
                bool expired=(Time.realtimeSinceStartup-lastResultCapture)*1000f>settings.max_overlay_age_ms;
                if(expired!=overlayExpired){overlay.SetAgeVisibility(!expired);overlayExpired=expired;}
            }
            if(overlayExpired)expiredSeconds+=Time.unscaledDeltaTime;
            if(Time.realtimeSinceStartup-metricsSince>=settings.telemetry_seconds)PublishPerformance();
            LayoutImage();
            bool controlsEnabled=interaction.CanUseControls(trackingInFlight,userActionPending);
            foreach(var control in busyControls) if(control!=null&&control.interactable!=controlsEnabled)control.interactable=controlsEnabled;
            if(clearButton!=null)clearButton.interactable=!interaction.Clearing;
            aspectSelector.SetInteractable(controlsEnabled);
            if(!userActionPending&&interaction.CanStartInference&&webcam!=null&&webcam.isPlaying&&webcam.didUpdateThisFrame&&trackingActive&&!trackingPaused&&Time.unscaledTime-lastTrack>=TrackingInterval) {
                StartCoroutine(Recognize(true));
            }
        }
        bool HasMasks() { foreach(var r in results.Values)if(r.tracking_ready)return true;return false; }
        string ImageHash(byte[] bytes){using(var sha=SHA256.Create())return BitConverter.ToString(sha.ComputeHash(bytes)).Replace("-","").ToLowerInvariant();}
        string Label(string target) {return byTarget.TryGetValue(target,out var c)?c.name:target;}
        string Provider {get{return activeProvider;}}
        float TrackingInterval { get {return Provider=="sam31_cutie"?settings.cutie_tracking_interval_seconds:settings.tracking_interval_seconds;} }
        int TrackingTimeout { get {return Provider=="sam31_cutie"?settings.cutie_tracking_request_timeout_seconds:settings.tracking_request_timeout_seconds;} }
        T Parse<T>(string raw) where T:class {try{return JsonUtility.FromJson<T>(raw);}catch(Exception e){Debug.LogWarning("[Learning] 响应解析："+e.Message);return null;}}
        IEnumerator Request(string path,string method,string body,Action<string,string> done,int timeout=0,bool inference=false)
        {
            using(var request=new UnityWebRequest(settings.backend_url.TrimEnd('/')+path,method)) {
                request.downloadHandler=new DownloadHandlerBuffer();
                if(body!=null)request.uploadHandler=new UploadHandlerRaw(Encoding.UTF8.GetBytes(body));
                request.SetRequestHeader("Content-Type","application/json");request.timeout=timeout>0?timeout:settings.request_timeout_seconds;
                if(inference){inferenceRequest=request;uploadBytes=body==null?0:Encoding.UTF8.GetByteCount(body);}
                try {
                    UnityWebRequestAsyncOperation operation=null;string launchError=null;
                    try{operation=request.SendWebRequest();}catch(Exception e){launchError=e.Message;}
                    if(operation==null){done?.Invoke(null,"连接无法发起："+launchError+"。请通过 Manual2AR/Learning 菜单打开场景以配置本地开发 HTTP。");yield break;}
                    yield return operation;
                    if(inference)responseBytes=(request.downloadHandler.data==null?0:request.downloadHandler.data.Length);
                    string error=null;
                    if(request.result!=UnityWebRequest.Result.Success) {
                        var typed=Parse<LearningError>(request.downloadHandler.text);
                        error="HTTP "+request.responseCode+" "+(typed!=null&&!string.IsNullOrEmpty(typed.detail)?typed.detail:request.error);
                    }
                    done?.Invoke(request.downloadHandler.text,error);
                } finally {
                    if(ReferenceEquals(inferenceRequest,request))inferenceRequest=null;
                }
            }
        }
        IEnumerator TrackingRequest(string path,byte[] jpeg,Action<string,string> done)
        {
            using(var request=new UnityWebRequest(settings.backend_url.TrimEnd('/')+path,"POST")){
                request.uploadHandler=new UploadHandlerRaw(jpeg);request.downloadHandler=new DownloadHandlerBuffer();
                request.SetRequestHeader("Content-Type","image/jpeg");request.timeout=TrackingTimeout;inferenceRequest=request;uploadBytes=jpeg.Length;
                try{
                    UnityWebRequestAsyncOperation operation=null;string launchError=null;
                    try{operation=request.SendWebRequest();}catch(Exception e){launchError=e.Message;}
                    if(operation==null){done(null,"请求无法发起："+launchError);yield break;}
                    yield return operation;responseBytes=(request.downloadHandler.data==null?0:request.downloadHandler.data.Length);
                    done(request.downloadHandler.text,request.result==UnityWebRequest.Result.Success?null:"HTTP "+request.responseCode+" "+request.error);
                }finally{if(ReferenceEquals(inferenceRequest,request))inferenceRequest=null;}
            }
        }
        void PublishPerformance()
        {
            float elapsed=Time.realtimeSinceStartup-metricsSince;frameTimes.Sort();
            float p50=frameTimes.Count>0?frameTimes[(frameTimes.Count-1)/2]:0,p95=frameTimes.Count>0?frameTimes[Mathf.FloorToInt((frameTimes.Count-1)*.95f)]:0;
            var data=new LearningReceipt{render_fps=renderFrames/elapsed,camera_fps=cameraFrames/elapsed,result_fps=resultFrames/elapsed,applied_fps=appliedFrames/elapsed,
                unity_frame_p50_ms=p50,unity_frame_p95_ms=p95,gc_collections=GC.CollectionCount(0)-gcBefore,managed_heap_bytes=GC.GetTotalMemory(false),overlay_expired=overlayExpired,expired_seconds=expiredSeconds,
                tracking_active=trackingActive,tracking_paused=trackingPaused,inference_inflight=busy,
                frames_over_33_ms=slowFrames,skipped_camera_frames=skippedFrames,preview_mode=settings.preview_mode,
                frame_age_ms=lastResultCapture<0?0:(Time.realtimeSinceStartup-lastResultCapture)*1000f};
            if(!performancePending&&!string.IsNullOrEmpty(runId))StartCoroutine(PerformanceReceipt(data));
            metricsSince=Time.realtimeSinceStartup;gcBefore=GC.CollectionCount(0);renderFrames=cameraFrames=resultFrames=appliedFrames=slowFrames=skippedFrames=0;frameTimes.Clear();expiredSeconds=0;
        }
        IEnumerator PerformanceReceipt(LearningReceipt data)
        {
            performancePending=true;
            try{yield return Request(Prefix+runId+"/events","POST",JsonUtility.ToJson(new LearningEvent{@event="frontend.performance",data=data}),null,5);}
            finally{performancePending=false;}
        }
        IEnumerator GetBytes(string path,Action<byte[],string> done,Action<string> sourceHash=null)
        {
            using(var request=UnityWebRequest.Get(settings.backend_url.TrimEnd('/')+path)) {
                request.timeout=settings.request_timeout_seconds;UnityWebRequestAsyncOperation operation=null;string launchError=null;
                try{operation=request.SendWebRequest();}catch(Exception e){launchError=e.Message;}
                if(operation==null){done(null,"图片连接无法发起："+launchError);yield break;}
                yield return operation;
                sourceHash?.Invoke(request.GetResponseHeader("X-Source-SHA256"));
                done(request.result==UnityWebRequest.Result.Success?request.downloadHandler.data:null,
                    request.result==UnityWebRequest.Result.Success?null:request.responseCode+" "+request.error);
            }
        }
        void Log(string name,LearningReceipt data)
        {
            if(string.IsNullOrEmpty(runId))return;
            data.knowledge_revision=knowledge.revision;
            StartCoroutine(Request(Prefix+runId+"/events","POST",JsonUtility.ToJson(new LearningEvent{@event=name,data=data}),
                (raw,error)=>{if(error!=null)Debug.LogWarning("[Learning] 日志回执失败："+error);}));
        }
        IEnumerator Connect()
        {
            if(!interaction.CanStartInference)yield break;busy=true;status.text="正在更新资料……";
            LearningKnowledge incoming=null;string failure=null;
            yield return Request("/api/learning/knowledge","GET",null,(raw,error)=>{failure=error;if(error==null)incoming=Parse<LearningKnowledge>(raw);});
            if(incoming!=null&&incoming.schema_version=="learning-knowledge-v3"&&incoming.cards!=null&&incoming.cards.Length==8) {
                if(incoming.revision!=knowledge.revision){yield return CloseRun();ResetVisual();if(webcam!=null)preview.texture=framing.Live(webcam,settings.capture_max_side);}
                knowledge=incoming;IndexKnowledge();BuildPartList();
                status.text="准备就绪。启动摄像头识别打印机，或直接浏览部件介绍。";
            } else {status.text="服务暂时未连接，可以先浏览部件介绍。";Debug.LogWarning("[Learning] Connection: "+failure);}
            busy=false;
        }
        void RefreshCameras(){
            var all=WebCamTexture.devices;
            if(cameraIndex<0){cameraIndex=0;for(int i=0;i<all.Length;i++)if(all[i].name==settings.camera_name)cameraIndex=i;}
            cameraIndex=Mathf.Clamp(cameraIndex,0,Mathf.Max(0,all.Length-1));
        }
        IEnumerator SwitchCamera(){
            var all=WebCamTexture.devices;if(all.Length<2){status.text="当前只有一个可用摄像头。";yield break;}
            cameraIndex=(cameraIndex+1)%all.Length;yield return OpenCamera();
        }
        IEnumerator CloseRun()
        {
            var old=runId;runId=null;
            if(!string.IsNullOrEmpty(old))yield return Request(Prefix+old,"DELETE",null,null,10);
        }
        IEnumerator EnsureRun()
        {
            if(!string.IsNullOrEmpty(runId))yield break;
            yield return Request("/api/learning/runs","POST",JsonUtility.ToJson(new LearningBegin{provider="auto",source="camera"}),
                (raw,error)=>{
                    var response=error==null?Parse<LearningRun>(raw):null;
                    if(response==null){status.text="识别服务暂时不可用，请稍后重试。";Debug.LogWarning("[Learning] Begin: "+error);}
                    else if(response.knowledge_revision!=knowledge.revision){
                        status.text="资料已更新，请返回教学首页后重新进入。";
                        if(!string.IsNullOrEmpty(response.run_id))StartCoroutine(Request(Prefix+response.run_id,"DELETE",null,null));
                    }
                    else {runId=response.run_id;activeProvider=string.IsNullOrEmpty(response.provider)?"opencv":response.provider;}
                });
        }
        void StopCamera()
        {
            if(webcam!=null){webcam.Stop();Destroy(webcam);webcam=null;}
        }
        void ResetVisual()
        {
            lastResultCapture=-1;overlayExpired=false;overlay.SetAgeVisibility(true);results.Clear();trackingActive=false;trackingPaused=false;trackingFailures=0;checkId="";selected="";overlay.Clear();listPanel.SetActive(true);focusPanel.SetActive(false);
            foreach(var p in rowLabels)p.Value.text=Label(p.Key)+"\n<color=#8CA8BD>点击了解</color>";
            foreach(var p in rowBackgrounds)p.Value.color=Panel;
        }
        IEnumerator OpenCamera()
        {
            if(!interaction.CanStartInference)yield break;busy=true;CloseModal();yield return CloseRun();ResetVisual();StopCamera();
            yield return Application.RequestUserAuthorization(UserAuthorization.WebCam);
            if(!Application.HasUserAuthorization(UserAuthorization.WebCam)){status.text="未取得摄像头权限，请在 Windows 隐私设置中允许桌面应用访问。";busy=false;yield break;}
            RefreshCameras();var devices=WebCamTexture.devices;
            if(devices.Length==0||cameraIndex>=devices.Length){status.text="没有可用摄像头，请连接后重新启动。";busy=false;yield break;}
            webcam=new WebCamTexture(devices[cameraIndex].name,settings.camera_width,settings.camera_height,settings.camera_fps);webcam.Play();
            float deadline=Time.realtimeSinceStartup+12;
            while(webcam.width<=16&&Time.realtimeSinceStartup<deadline)yield return null;
            if(webcam.width<=16){StopCamera();status.text="摄像头没有返回画面，请关闭占用它的其他应用。";busy=false;yield break;}
            preview.texture=framing.Live(webcam,settings.capture_max_side);sourceLabel.text="让整台设备进入画面，点击识别查看部件位置。";LayoutImage();
            yield return EnsureRun();
            if(runId!=null){Log("camera.ready",new LearningReceipt{source="camera",device=devices[cameraIndex].name,image_width=webcam.width,image_height=webcam.height,rotation=webcam.videoRotationAngle,vertically_mirrored=webcam.videoVerticallyMirrored});status.text="完整拍到打印机，保持清晰稳定，再点击识别。识别将上传所拍摄的当前帧。";}
            busy=false;
        }

        bool TryCapture(out byte[] bytes,out Texture2D snapshot,out string error){
            bytes=null;snapshot=null;error=null;
            if(webcam==null||!webcam.isPlaying||webcam.width<=16){error="请先启动摄像头";return false;}
            try{snapshot=framing.Capture(webcam,webcam.videoRotationAngle,webcam.videoVerticallyMirrored,settings.capture_max_side,spareFrame);spareFrame=null;bytes=snapshot.EncodeToJPG(Mathf.Clamp(settings.jpeg_quality,40,95));return true;}
            catch(Exception e){error=e.Message;if(snapshot!=null)Destroy(snapshot);snapshot=null;return false;}
        }
        IEnumerator ChangeFraming(int index){
            interaction.InvalidateReplies();yield return CloseRun();ResetVisual();framing.SetAspect(index);
            if(webcam!=null&&webcam.isPlaying)preview.texture=framing.Live(webcam,settings.capture_max_side);
            status.text="画幅已调整，请重新识别部件。";LayoutImage();
        }
        void DisplayFrame(Texture2D snapshot)
        {
            if(pairedFrame!=null&&pairedFrame!=snapshot){if(spareFrame!=null)Destroy(spareFrame);spareFrame=pairedFrame;}
            snapshot.Apply(false);pairedFrame=snapshot;preview.texture=LivePreview&&webcam!=null?(Texture)framing.Live(webcam,settings.capture_max_side):snapshot;LayoutImage();
        }
        IEnumerator Recognize(bool tracking)
        {
            if(!interaction.CanStartInference)yield break;
            if(tracking)trackingInFlight=true;
            // Release the UI even if this coroutine is interrupted. The request
            // starts, rather than finishes, the rate-limit interval.
            try {yield return RecognizeFrame(tracking);}
            finally {busy=false;if(tracking)trackingInFlight=false;}
        }
        IEnumerator UserAction(IEnumerator action,bool resumeTracking=false)
        {
            if(userActionPending||interaction.Clearing)yield break;
            if(busy&&!trackingInFlight)yield break;
            userActionPending=true;bool wasPaused=trackingPaused;trackingPaused=true;
            try{
                if(trackingInFlight){interaction.InvalidateReplies();if(inferenceRequest!=null)inferenceRequest.Abort();}
                while(busy)yield return null;
                if(!interaction.Clearing)yield return action;
            }finally{if(resumeTracking)trackingPaused=wasPaused;userActionPending=false;}
        }
        IEnumerator RecognizeFrame(bool tracking)
        {
            if(!interaction.CanStartInference)yield break;
            int revision=interaction.Revision;
            lastTrack=Time.unscaledTime;
            float captureStarted=Time.realtimeSinceStartup;
            if(!TryCapture(out var bytes,out var snapshot,out var reason)){
                if(tracking){overlay.Clear();results.Clear();foreach(var p in rowLabels)p.Value.text=Label(p.Key)+"\n画面不可用，请重新启动摄像头";}
                status.text=reason;yield break;
            }
            float captureMs=(Time.realtimeSinceStartup-captureStarted)*1000f;
            busy=true;yield return EnsureRun();
            if(runId==null||!interaction.AcceptsReply(revision)){Destroy(snapshot);busy=false;yield break;}
            int sent=++sequence;string expectedRun=runId;
            if(!tracking){ResetVisual();DisplayFrame(snapshot);status.text="正在识别打印机部件，请保持画面清晰稳定……";}
            string expectedHash=ImageHash(bytes);
            var request=tracking?null:new LearningFrame{client_frame_id=sent,expected_source_sha256=expectedHash,image_base64=Convert.ToBase64String(bytes),capture_time_ms=captureStarted*1000f};
            LearningReply reply=null;string failure=null;
            float requestStarted=Time.realtimeSinceStartup;
            if(tracking)yield return TrackingRequest(Prefix+runId+"/frames/jpeg?client_frame_id="+sent+"&expected_source_sha256="+expectedHash+"&capture_time_ms="+(captureStarted*1000f).ToString("R",System.Globalization.CultureInfo.InvariantCulture),bytes,
                (raw,error)=>{failure=error;if(error==null)reply=Parse<LearningReply>(raw);});
            else yield return Request(Prefix+runId+"/locate","POST",JsonUtility.ToJson(request),(raw,error)=>{failure=error;if(error==null)reply=Parse<LearningReply>(raw);},0,true);
            if(!interaction.AcceptsReply(revision)){
                if(pairedFrame==snapshot)pairedFrame=null;
                Destroy(snapshot);yield break;
            }
            float roundtripMs=(Time.realtimeSinceStartup-requestStarted)*1000f;
            if(reply==null||reply.results==null||reply.run_id!=expectedRun||reply.client_frame_id!=sent||(!string.IsNullOrEmpty(expectedHash)&&reply.source_sha256!=expectedHash)){
                if(tracking)Destroy(snapshot);
                if(tracking&&++trackingFailures<=2&&(failure==null||!failure.Contains("HTTP 404"))){
                    overlay.Clear();foreach(var r in results.Values)r.tracking_ready=false;
                    status.text="正在重新获取部件位置，请保持画面稳定。";Debug.LogWarning("[Learning] Tracking retry: "+failure);
                    foreach(var p in rowLabels)p.Value.text=Label(p.Key)+"\n请求重试中";
                    busy=false;yield break;
                }
                trackingActive=false;
                overlay.Clear();results.Clear();
                foreach(var p in rowLabels)p.Value.text=Label(p.Key)+"\n<color=#D9B16A>请求失败，请重新识别</color>";
                if(webcam!=null)preview.texture=framing.Live(webcam,settings.capture_max_side);
                if(failure!=null&&failure.Contains("HTTP 404"))runId=null;
                status.text="暂时无法识别，请调整视角后重试。";Debug.LogWarning("[Learning] Inference: "+failure);busy=false;yield break;
            }
            RenderReply(reply,snapshot,bytes,captureStarted,captureMs,roundtripMs,sent,expectedHash,tracking);
        }
        void RenderReply(LearningReply reply,Texture2D snapshot,byte[] bytes,float captureStarted,float captureMs,float roundtripMs,int sent,string expectedHash,bool tracking){
            if(!string.IsNullOrEmpty(reply.first_mask_provider))activeProvider=reply.first_mask_provider;
            trackingFailures=0;
            trackingActive=tracking?reply.active_sessions>0:false;
            resultFrames++;float receivedAge=(Time.realtimeSinceStartup-captureStarted)*1000f;
            bool stale=LivePreview&&receivedAge>settings.max_overlay_age_ms;
            DisplayFrame(snapshot);checkId=reply.check_id;
            var applyTimer=Stopwatch.StartNew();
            bool labelsOk=true;
            try{overlay.SetLabelMap(reply.label_map);}catch(Exception e){labelsOk=false;overlay.Clear();Debug.LogWarning("[Learning] 标签图拒绝："+e.Message);}
            lastResultCapture=captureStarted;overlayExpired=stale;overlay.SetAgeVisibility(!stale);
            var receipts=new List<LearningRenderItem>();
            foreach(var r in reply.results){
                // JsonUtility may instantiate a default object for JSON null. Only a
                // backend-approved mask is a rendering attempt; this is not GPU proof.
                bool attempted=r.tracking_ready,rendered=false;string error=r.error;var timer=Stopwatch.StartNew();
                if(r.tracking_ready&&!stale&&!trackingPaused&&labelsOk)rendered=overlay.Show(r.component_id,Label(r.component_id),r.tracked,snapshot.width,snapshot.height,out error);
                if(!rendered){overlay.Hide(r.component_id);if(!stale&&!trackingPaused)r.tracking_ready=false;}results[r.component_id]=r;timer.Stop();
                if(!tracking&&r.tracking_ready)trackingActive=true;
                if(rowLabels.TryGetValue(r.component_id,out var row))row.text=Label(r.component_id)+"\n<color="+(rendered?"#3EEBC0":"#D9B16A")+">"+(stale?"正在更新":Stage(r,tracking))+"</color>";
                var corners=new Vector3[4];content.GetWorldCorners(corners);
                receipts.Add(new LearningRenderItem{component_id=r.component_id,attempted=attempted,passed=rendered,reason=error??r.stage,
                    decode_ms=(float)timer.Elapsed.TotalMilliseconds,bbox_0_1000=r.tracked!=null?r.tracked.bbox_0_1000:null,
                    image_rect=new[]{corners[0].x,corners[0].y,corners[2].x,corners[2].y}});
            }
            overlay.Select(selected);applyTimer.Stop();if(!stale&&!trackingPaused&&labelsOk&&overlay.VisibleCount>0)appliedFrames++;
            Log("frontend.render",new LearningReceipt{check_id=checkId,client_frame_id=sent,frame_id=reply.frame_id,
                source_sha256=expectedHash,request_ms=roundtripMs,stale_rejected=stale,overlay_apply_ms=(float)applyTimer.Elapsed.TotalMilliseconds,
                request_upload_bytes=uploadBytes,request_download_bytes=responseBytes,preview_mode=settings.preview_mode,
                capture_time_ms=captureStarted*1000f,capture_encode_ms=captureMs,frame_age_ms=(Time.realtimeSinceStartup-captureStarted)*1000f,
                source="camera",image_width=snapshot.width,image_height=snapshot.height,
                rotation=webcam!=null?webcam.videoRotationAngle:0,vertically_mirrored=webcam!=null&&webcam.videoVerticallyMirrored,
                results=receipts.ToArray()});
            int count=0;bool serviceFailed=false;foreach(var r in results.Values){if(r.tracking_ready)count++;if(r.stage=="segmentation_error")serviceFailed=true;}
            int recovering=0;foreach(var r in results.Values)if(r.retained_for_recovery)recovering++;
            status.text=count>0?$"已识别 {count} 个部件，点击名称或画面标签查看介绍。":recovering>0?"正在重新寻找部件，请保持画面稳定。":serviceFailed?"识别服务暂时不可用，请稍后重试。":"请完整拍到打印机后重新识别。";
            if(trackingPaused)status.text="标注已暂停，您可以继续浏览部件介绍。";
            if(stale)status.text="正在更新标注，请保持画面稳定。";
            else if(reply.fallback_used)status.text="已切换本地标注。"+status.text;
            busy=false;
        }

        string Stage(LearningResult r,bool tracking=false)
        {
            if(r.tracking_ready)return "已识别";
            if(r.retained_for_recovery)return "正在寻找";
            return "当前不可见";
        }
        void SelectPart(string target)
        {
            if(!byTarget.TryGetValue(target,out var card))return;
            bool changed=selected!=target||!focusPanel.activeSelf;
            selected=target;detailId=card.id;overlay.Select(target);listPanel.SetActive(false);focusPanel.SetActive(true);
            if(changed)BuildSidebar(card);
            foreach(var pair in rowBackgrounds)pair.Value.color=pair.Key==target?new Color(.03f,.23f,.31f,1):Panel;
            Log("frontend.select",new LearningReceipt{component_id=target,check_id=checkId});
        }
        void ShowAll()
        {
            selectionGeneration++;selected="";overlay.Select("");listPanel.SetActive(true);focusPanel.SetActive(false);
        }
        void BuildSidebar(LearningCard card)
        {
            selectionGeneration++;focusTitle.text=card.name;
            foreach(Transform child in focusSheet)Destroy(child.gameObject);
            if(card.images!=null&&card.images.Length>0){
                var area=Rect("Official reference image",focusSheet,Vector2.zero,Vector2.one);
                area.gameObject.AddComponent<LayoutElement>().preferredHeight=235;
                var picture=Rect("Reference photo",area,Vector2.zero,Vector2.one).gameObject.AddComponent<RawImage>();picture.raycastTarget=false;
                picture.gameObject.AddComponent<AspectRatioFitter>().aspectMode=AspectRatioFitter.AspectMode.FitInParent;
                StartCoroutine(LoadPhoto(card.images[0],picture,selectionGeneration));
                Paragraph(focusSheet,"官方参考图",18,new Color(.62f,.77f,.84f));
            }
            Paragraph(focusSheet,"功能说明",25,Cyan);
            foreach(var text in card.description??new string[0])Paragraph(focusSheet,text,23);
            Canvas.ForceUpdateCanvases();focusSheet.parent.parent.GetComponent<ScrollRect>().verticalNormalizedPosition=1;
            Log("learning.detail",new LearningReceipt{card_id=card.id,component_id=card.target_id,check_id=checkId});
        }
        IEnumerator Clear()
        {
            if(!interaction.TryBeginClear())yield break;
            ResetVisual();CloseModal();
            if(webcam!=null)preview.texture=framing.Live(webcam,settings.capture_max_side);
            status.text="标注已清除，正在停止跟踪……";
            if(inferenceRequest!=null)inferenceRequest.Abort();
            try {
                // Let the cancelled coroutine release its busy state before
                // sending clear. Its obsolete reply is guarded by Revision.
                while(busy)yield return null;
                busy=true;string failure=null;
                if(!string.IsNullOrEmpty(runId))yield return Request(Prefix+runId+"/clear","POST","{}",(raw,error)=>failure=error,TrackingTimeout+10);
                if(failure!=null){
                    // A failed remote clear must not reuse old object memory.
                    yield return CloseRun();
                    status.text="标注已清除，可以重新识别。";
                    Debug.LogWarning("[Learning] 后端清理未确认："+failure);
                } else status.text="标注已清除，可以重新识别。";
            } finally { interaction.FinishClear(); }
        }


        void LayoutImage(){
            if(preview.texture==null)return;float w=preview.texture.width,h=preview.texture.height;
            float scale=Mathf.Min(imageArea.rect.width/w,imageArea.rect.height/h);content.sizeDelta=new Vector2(w*scale,h*scale);content.localEulerAngles=Vector3.zero;content.localScale=Vector3.one;
        }

        void CloseModal(){detailGeneration++;if(modal!=null){modal.SetActive(false);Destroy(modal);}modal=null;}
        RectTransform Modal(string title,bool article=false)
        {
            CloseModal();modal=Rect("Modal shade",root,Vector2.zero,Vector2.one).gameObject;
            modal.AddComponent<AppRoundedImage>().color=new Color(0,.015f,.04f,.90f);AppModalBackdrop.Attach(modal);
            var panel=Frame("Detail panel",modal.transform,article?new Vector2(.09f,.06f):new Vector2(.25f,.18f),article?new Vector2(.91f,.94f):new Vector2(.75f,.82f));
            TextAt(panel,title,new Vector2(.025f,.915f),new Vector2(.91f,.99f),article?30:26);
            ButtonAt(panel,"×",new Vector2(.94f,.92f),new Vector2(.985f,.985f),CloseModal);
            return panel;
        }
        RectTransform Scroll(Transform parent,Vector2 min,Vector2 max)
        {
            var area=Rect("Scroll",parent,min,max);var scroll=area.gameObject.AddComponent<ScrollRect>();scroll.horizontal=false;
            var viewport=Rect("Viewport",area,Vector2.zero,new Vector2(.97f,1));viewport.gameObject.AddComponent<RectMask2D>();viewport.gameObject.AddComponent<AppRoundedImage>().color=Color.clear;
            var sheet=Rect("Content",viewport,new Vector2(0,1),new Vector2(1,1));sheet.pivot=new Vector2(.5f,1);
            var layout=sheet.gameObject.AddComponent<VerticalLayoutGroup>();layout.spacing=12;layout.padding=new RectOffset(10,18,12,20);layout.childControlHeight=true;layout.childControlWidth=true;layout.childForceExpandHeight=false;
            var fitter=sheet.gameObject.AddComponent<ContentSizeFitter>();fitter.verticalFit=ContentSizeFitter.FitMode.PreferredSize;
            scroll.viewport=viewport;scroll.content=sheet;scroll.movementType=ScrollRect.MovementType.Clamped;scroll.scrollSensitivity=38;
            var bar=Rect("Scrollbar",area,new Vector2(.98f,0),Vector2.one);var track=bar.gameObject.AddComponent<AppRoundedImage>();track.color=new Color(.05f,.16f,.23f,1);
            var scrollbar=bar.gameObject.AddComponent<Scrollbar>();scrollbar.direction=Scrollbar.Direction.BottomToTop;
            var handle=Rect("Handle",bar,Vector2.zero,Vector2.one);var graphic=handle.gameObject.AddComponent<AppRoundedImage>();graphic.color=new Color(.15f,.65f,.75f,.85f);
            scrollbar.handleRect=handle;scrollbar.targetGraphic=graphic;scroll.verticalScrollbar=scrollbar;scroll.verticalScrollbarVisibility=ScrollRect.ScrollbarVisibility.AutoHide;return sheet;
        }
        void Paragraph(Transform parent,string text,int size=21,Color? color=null)
        {
            var o=new GameObject("Paragraph",typeof(RectTransform),typeof(Text),typeof(LayoutElement));o.transform.SetParent(parent,false);
            var t=o.GetComponent<Text>();t.font=font;t.text=CjkText(text);t.fontSize=size;t.supportRichText=false;t.raycastTarget=false;t.lineSpacing=1.12f;t.color=color??Color.white;t.horizontalOverflow=HorizontalWrapMode.Wrap;t.verticalOverflow=VerticalWrapMode.Overflow;
            var le=o.GetComponent<LayoutElement>();le.minHeight=32;le.preferredHeight=-1;
        }
        // Legacy uGUI can treat a long unspaced Chinese run as one word. Add
        // invisible break opportunities in presentation only; source data stays verbatim.
        static string CjkText(string text)
        {
            if(string.IsNullOrEmpty(text))return text;
            var output=new StringBuilder(text.Length*2);
            for(int i=0;i<text.Length;i++){
                output.Append(text[i]);
                if(i+1<text.Length&&text[i]>=0x3400&&text[i]<=0x9fff&&text[i+1]>=0x3400&&text[i+1]<=0x9fff)output.Append('\u200b');
            }
            return output.ToString();
        }
        void RowButton(Transform parent,string text,Action action)
        {
            var r=Rect("Action",parent,Vector2.zero,Vector2.one);r.gameObject.AddComponent<LayoutElement>().preferredHeight=64;
            var b=MakeButton(r,text,action,19);b.GetComponent<Image>().color=new Color(.025f,.20f,.28f,1);
        }
        void ShowLibrary()
        {
            CloseModal();ShowAll();listPanel.SetActive(false);focusPanel.SetActive(true);focusTitle.text="认识 A1 mini";
            foreach(Transform child in focusSheet)Destroy(child.gameObject);
            Paragraph(focusSheet,"整机介绍",25,Cyan);
            foreach(var text in knowledge.device_description??new string[0])Paragraph(focusSheet,text,23);
            Log("learning.library",new LearningReceipt());
        }
        void ShowDetail(string id)
        {
            if(!cards.TryGetValue(id,out var card))return;
            CloseModal();SelectPart(card.target_id);
        }
        void ShowDeviceMore()
        {
            ShowMore("整机",knowledge.device_more_information,ShowLibrary);
        }
        void ShowRelated(LearningCard card)
        {
            ShowMore(card.name,card.more_information,()=>CloseModal());
        }
        void ShowMore(string name,LearningSource[] sources,Action back)
        {
            var panel=Modal("更多信息 · "+name);var sheet=Scroll(panel,new Vector2(.03f,.15f),new Vector2(.97f,.89f));
            var groups=new List<string>();
            foreach(var source in sources??new LearningSource[0]){
                var category=string.IsNullOrEmpty(source.category)?"官方 Wiki":source.category;
                if(!groups.Contains(category))groups.Add(category);
            }
            float height=Mathf.Clamp(170+groups.Count*44+(sources==null?0:sources.Length)*70,420,root.rect.height*.66f);
            float fraction=height/root.rect.height;panel.anchorMin=new Vector2(.25f,.5f-fraction*.5f);panel.anchorMax=new Vector2(.75f,.5f+fraction*.5f);
            foreach(var group in groups){
                Paragraph(sheet,group,24,Cyan);
                foreach(var source in sources??new LearningSource[0]){
                    var category=string.IsNullOrEmpty(source.category)?"官方 Wiki":source.category;
                    if(category!=group)continue;var captured=source;
                    RowButton(sheet,source.title,()=>ShowArticle(captured,()=>ShowMore(name,sources,back)));
                }
            }
            ButtonAt(panel,"返回",new Vector2(.03f,.035f),new Vector2(.32f,.115f),back);
        }
        void ShowArticle(LearningSource source,Action back)
        {
            var panel=Modal("离线 Wiki",true);
            var reader=panel.gameObject.AddComponent<PrinterLearningWikiView>();
            reader.Initialize(panel,font,settings.backend_url,source,back);
            Log("learning.source",new LearningReceipt{card_id=detailId,citation_id=source.page_id});
        }
        IEnumerator LoadPhoto(LearningPhoto source,RawImage target,int generation)
        {
            if(referencePhotos.TryGetValue(source.id,out var cached)){
                if(generation==selectionGeneration&&target!=null){target.texture=cached;target.GetComponent<AspectRatioFitter>().aspectRatio=cached.width/(float)cached.height;}yield break;
            }
            byte[] body=null;string error=null;string path=Path.Combine(Application.streamingAssetsPath,source.local_file);
            try{if(File.Exists(path))body=File.ReadAllBytes(path);}catch(Exception e){error=e.Message;}
            if(body==null)yield return GetBytes(source.url,(bytes,failure)=>{body=bytes;error=failure;});
            if(generation!=selectionGeneration||target==null)yield break;
            if(body==null){Debug.LogWarning("[Learning] 参考图加载失败："+error);target.gameObject.SetActive(false);yield break;}
            var texture=new Texture2D(2,2,TextureFormat.RGB24,false);
            if(!ImageConversion.LoadImage(texture,body)){Destroy(texture);target.gameObject.SetActive(false);yield break;}
            texture.filterMode=FilterMode.Bilinear;texture.wrapMode=TextureWrapMode.Clamp;referencePhotos[source.id]=texture;target.texture=texture;target.GetComponent<AspectRatioFitter>().aspectRatio=texture.width/(float)texture.height;
        }

        RectTransform Rect(string name,Transform parent,Vector2 min,Vector2 max)
        {
            var o=new GameObject(name,typeof(RectTransform));o.transform.SetParent(parent,false);var r=o.GetComponent<RectTransform>();r.anchorMin=min;r.anchorMax=max;r.offsetMin=r.offsetMax=Vector2.zero;return r;
        }
        RectTransform Frame(string name,Transform parent,Vector2 min,Vector2 max)
        {
            var r=Rect(name,parent,min,max);r.gameObject.AddComponent<AppRoundedImage>().color=Panel;var outline=r.gameObject.AddComponent<Outline>();outline.effectColor=new Color(0,.72f,.9f,.8f);outline.effectDistance=new Vector2(1.5f,-1.5f);return r;
        }
        Text TextAt(Transform parent,string value,Vector2 min,Vector2 max,int size=23)
        {
            var r=Rect("Text",parent,min,max);var t=r.gameObject.AddComponent<Text>();t.font=font;t.fontSize=size;t.text=value;t.color=Color.white;t.alignment=TextAnchor.MiddleLeft;
            t.raycastTarget=false;t.horizontalOverflow=HorizontalWrapMode.Wrap;t.verticalOverflow=VerticalWrapMode.Truncate;return t;
        }
        Button MakeButton(RectTransform r,string label,Action action,int size=23)
        {
            var image=r.gameObject.AddComponent<AppRoundedImage>();image.color=Panel;var border=r.gameObject.AddComponent<Outline>();border.effectColor=new Color(0,.6f,.8f,.8f);
            var button=r.gameObject.AddComponent<Button>();button.targetGraphic=image;button.onClick.AddListener(()=>action());
            var text=TextAt(r,label,new Vector2(.04f,.06f),new Vector2(.96f,.94f),size);text.alignment=TextAnchor.MiddleCenter;return button;
        }
        Button ButtonAt(Transform parent,string label,Vector2 min,Vector2 max,Action action,bool gated=false)
        {var b=MakeButton(Rect(label,parent,min,max),label,action);if(gated)busyControls.Add(b);return b;}

        void BuildPartList()
        {
            if(listPanel==null)return;
            foreach(Transform t in listPanel.transform)Destroy(t.gameObject);rowLabels.Clear();rowBackgrounds.Clear();int i=0;
            foreach(var c in knowledge.cards){if(string.IsNullOrEmpty(c.target_id))continue;string target=c.target_id;
                float top=.91f-i*.105f;var r=Rect(c.name,listPanel.transform,new Vector2(.04f,top-.093f),new Vector2(.96f,top));
                var b=MakeButton(r,c.name+"\n<color=#8CA8BD>点击了解</color>",()=>SelectPart(target),21);
                var color=PrinterLearningOverlay.ComponentColor(target);r.GetComponent<Outline>().effectColor=color;
                var accent=Rect("Component color",r,new Vector2(0,0),new Vector2(.015f,1)).gameObject.AddComponent<AppRoundedImage>();accent.color=color;accent.raycastTarget=false;
                rowLabels[target]=b.GetComponentInChildren<Text>();rowBackgrounds[target]=r.GetComponent<Image>();i++;}
            TextAt(listPanel.transform,"部件列表 · 点击名称高亮",new Vector2(.04f,.93f),new Vector2(.96f,.99f),23);
        }
        void BuildUI()
        {
            if(FindObjectOfType<EventSystem>()==null)new GameObject("Learning EventSystem",typeof(EventSystem),typeof(StandaloneInputModule));
            var canvas=new GameObject("Learning UI",typeof(RectTransform),typeof(Canvas),typeof(CanvasScaler),typeof(GraphicRaycaster));canvas.transform.SetParent(transform,false);
            var surface=canvas.GetComponent<Canvas>();surface.renderMode=RenderMode.ScreenSpaceOverlay;surface.pixelPerfect=true;
            var scaler=canvas.GetComponent<CanvasScaler>();scaler.uiScaleMode=CanvasScaler.ScaleMode.ScaleWithScreenSize;scaler.referenceResolution=new Vector2(1920,1080);scaler.matchWidthOrHeight=.5f;AppTheme.Attach(canvas.GetComponent<RectTransform>());
            root=canvas.GetComponent<RectTransform>();Rect("Background",root,Vector2.zero,Vector2.one).gameObject.AddComponent<AppRoundedImage>().color=Navy;
            TextAt(root,"Manual2AR / 3D打印机教学系统",new Vector2(.025f,.936f),new Vector2(.67f,.992f),34);
            TextAt(root,"部件认知",new Vector2(.70f,.936f),new Vector2(.87f,.992f),26);
            ButtonAt(root,"启动摄像头",new Vector2(.025f,.845f),new Vector2(.205f,.91f),()=>StartCoroutine(UserAction(OpenCamera())),true);
            ButtonAt(root,"切换摄像头",new Vector2(.22f,.845f),new Vector2(.37f,.91f),()=>StartCoroutine(UserAction(SwitchCamera())),true);
            ButtonAt(root,"识别 / 重新识别",new Vector2(.385f,.845f),new Vector2(.605f,.91f),()=>StartCoroutine(UserAction(Recognize(false))),true);
            clearButton=ButtonAt(root,"清除标注",new Vector2(.62f,.845f),new Vector2(.78f,.91f),()=>StartCoroutine(Clear()));
            ButtonAt(root,"整机介绍",new Vector2(.795f,.845f),new Vector2(.975f,.91f),ShowLibrary);
            aspectSelector=framing.AddSelector(root,new Vector2(.025f,.775f),new Vector2(.66f,.83f),index=>StartCoroutine(UserAction(ChangeFraming(index))));
            imageArea=Frame("Image viewport",root,new Vector2(.025f,.15f),new Vector2(.66f,.76f));imageArea.gameObject.AddComponent<RectMask2D>();
            content=Rect("Paired frame and masks",imageArea,new Vector2(.5f,.5f),new Vector2(.5f,.5f));
            preview=Rect("Frame",content,Vector2.zero,Vector2.one).gameObject.AddComponent<RawImage>();preview.raycastTarget=false;preview.color=Color.white;
            labelRoot=Rect("Clickable labels",imageArea,Vector2.zero,Vector2.one);overlay=gameObject.AddComponent<PrinterLearningOverlay>();overlay.Initialize(content,labelRoot,font,SelectPart);
            var side=Frame("Part panel",root,new Vector2(.69f,.15f),new Vector2(.975f,.82f));
            listPanel=Rect("All parts",side,Vector2.zero,Vector2.one).gameObject;BuildPartList();
            focusPanel=Rect("Selected part",side,Vector2.zero,Vector2.one).gameObject;
            focusTitle=TextAt(focusPanel.transform,"",new Vector2(.055f,.90f),new Vector2(.95f,.985f),28);
            focusSheet=Scroll(focusPanel.transform,new Vector2(.03f,.15f),new Vector2(.97f,.89f));
            ButtonAt(focusPanel.transform,"返回列表",new Vector2(.045f,.035f),new Vector2(.39f,.115f),ShowAll);
            ButtonAt(focusPanel.transform,"更多信息",new Vector2(.43f,.035f),new Vector2(.955f,.115f),()=>{
                if(byTarget.TryGetValue(selected,out var c))ShowRelated(c);else ShowDeviceMore();
            });focusPanel.SetActive(false);
            sourceLabel=TextAt(root,"启动摄像头，或点击部件名称阅读介绍。",new Vector2(.025f,.105f),new Vector2(.72f,.145f),20);
            status=TextAt(root,"",new Vector2(.025f,.025f),new Vector2(.73f,.08f),22);
            var version=TextAt(root,"Manual2AR · 部件认知",new Vector2(.75f,.025f),new Vector2(.975f,.08f),18);version.alignment=TextAnchor.MiddleRight;version.color=new Color(.56f,.71f,.8f);
        }
        public IEnumerator ReleaseModule(){
            interaction.TryBeginClear();trackingActive=false;if(inferenceRequest!=null)inferenceRequest.Abort();StopAllCoroutines();StopCamera();
            var identity=runId;runId=null;
            if(settings!=null&&!string.IsNullOrEmpty(identity))using(var request=UnityWebRequest.Delete(settings.backend_url.TrimEnd('/')+Prefix+identity)){request.timeout=8;yield return request.SendWebRequest();}
        }
        void OnDisable()
        {
            interaction.TryBeginClear();
            if(inferenceRequest!=null)inferenceRequest.Abort();
            StopAllCoroutines();StopCamera();interaction.FinishClear();if(spareFrame!=null)Destroy(spareFrame);
            if(settings!=null&&!string.IsNullOrEmpty(runId)){
                var request=UnityWebRequest.Delete(settings.backend_url.TrimEnd('/')+Prefix+runId);request.timeout=10;
                try{request.SendWebRequest().completed+=_=>request.Dispose();}catch(Exception){request.Dispose();}runId=null;
            }
            CloseModal();foreach(var photo in referencePhotos.Values)if(photo!=null)Destroy(photo);referencePhotos.Clear();if(pairedFrame!=null)Destroy(pairedFrame);
        }
    }
}
