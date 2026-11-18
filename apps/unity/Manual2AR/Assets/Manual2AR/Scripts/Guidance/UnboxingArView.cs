using System;
using System.Collections;
using System.Collections.Generic;
using System.Security.Cryptography;
using UnityEngine;
using UnityEngine.EventSystems;
using UnityEngine.UI;
using Manual2AR.Spatial;
using Manual2AR.VisualGuidance;

namespace Manual2AR
{
    [Serializable] public class UnboxingArGuide
    {
        public string schema_version,reason;
        public UnboxingArAction[] actions;
        public AssetLibraryDescriptor asset_library;
        public int verified_actions,total_actions;
    }

    [Serializable] public class UnboxingArAction
    {
        public string action_id,substep_id,title,instruction,target,visual_check,presentation_id,status,evidence,next_action,source_sha256;
        public bool optional;
        public string[] manual_checks,citation_ids;
        public UnboxingPhoto reference;
    }

    public sealed class UnboxingArView : MonoBehaviour
    {
        public const string Schema="manual2ar-unboxing-photo-ar-v1";
        [Serializable] class Stamp
        {
            public string state_id,variant_id,substep_id,action_id,source_sha256;
            public int revision;
        }
        [Serializable] class CaptureCommand : Stamp { public int client_frame_id; public string image_base64; }
        [Serializable] class ManualCommand : Stamp { public string[] confirmed_checks; }
        [Serializable] class PlayCommand : Stamp { public float anchor_x,anchor_y; public int width,height; }
        [Serializable] class Illustration
        {
            public string run_id,state_id,variant_id,substep_id,action_id,source_sha256;
            public int revision,width,height;
            public bool illustrative_only;
            public VisualPresentation presentation;
            public SpatialProjection projection;
        }

        GuidanceRun current;
        int actionIndex,mediaVersion,lastFrame;
        Func<string,string,string,Action<string,string>,IEnumerator> request;
        Func<string,Action<byte[]>,IEnumerator> loadBytes;
        Action<GuidanceRun> returnToLesson;
        RectTransform root,photoPlane;
        AppWorkspace workspace;
        Text stepTitle,copy,status,caption,emptyHint;
        RawImage image;
        SpatialAssetGraphic graphic;
        SpatialCamera cameraOwner;
        Dropdown devices;
        Button start,capture,reference,play,check,previous,next,skip;
        AppDialog dialog;
        Texture2D texture;
        byte[] captured;
        string displayedSha="",submittedSha="";
        bool busy,previewing,closed;
        float previewAt,animationAt;
        VisualPresentation activePresentation;
        VisualRenderFrame renderFrame;

        string Api { get { return "/api/guidance/runs/"+current.run_id; } }
        UnboxingArAction[] Actions { get { return current.photo_ar.actions??Array.Empty<UnboxingArAction>(); } }
        UnboxingArAction ActionItem { get { return actionIndex>=0 && actionIndex<Actions.Length?Actions[actionIndex]:null; } }
        bool HolderBlocked { get { return current.state_id=="U7"&&current.selected_substep_id=="U7-S2"&&Actions.Length==0; } }
        bool NextNeedsBase {
            get { return HolderBlocked||current.state_id=="U7"&&current.selected_substep_id=="U7-S1"
                &&(!Array.Exists(Actions,a=>a.action_id=="holder.base"&&a.status=="verified")||
                    Array.Exists(current.substeps??Array.Empty<UnboxingSubstep>(),s=>s.id=="U7-S2"&&s.locked)); }
        }
        bool LibraryReady { get { return VisualAssetLibrary.Matches(current.photo_ar.asset_library,VisualAssetLibrary.UnboxingId); } }
        bool LivePhoto { get { return captured!=null && !previewing; } }

        public static UnboxingArView Open(GuidanceRun run,Func<string,string,string,Action<string,string>,IEnumerator> send,
            Func<string,Action<byte[]>,IEnumerator> getBytes,string cameraName,Action<GuidanceRun> onClose)
        {
            var view=new GameObject("Unboxing AR").AddComponent<UnboxingArView>();
            view.current=run;view.request=send;view.loadBytes=getBytes;view.returnToLesson=onClose;
            view.Build(cameraName);
            view.SelectAction(0);
            return view;
        }

        void Build(string preferredCamera)
        {
            root=AppWorkspace.Canvas(transform,"Unboxing AR workspace",30);
            workspace=new AppWorkspace(root,"开箱 AR 指引");
            AppWorkspace.Place(workspace.Main,.025f,.14f,.64f,.815f);
            AppWorkspace.Place(workspace.Aside,.655f,.14f,.975f,.815f);
            AppShell.BindBack("返回开箱图文",Close,()=>!closed&&!busy&&dialog==null);
            devices=AppDropdown.Create(workspace.Tools,"开箱相机",Vector2.zero,new Vector2(.30f,1),_=>SwitchCamera());
            var names=new List<string>();int preferred=0;
            foreach(var device in WebCamTexture.devices){if(device.name==preferredCamera)preferred=names.Count;names.Add(device.name);}
            if(names.Count==0)names.Add("未发现摄像头");
            devices.AddOptions(names);devices.SetValueWithoutNotify(preferred);
            start=AppTheme.Button(workspace.Tools,"启动相机",new Vector2(.32f,0),new Vector2(.53f,1),()=>StartCoroutine(StartCamera()),AppIcon.Camera);
            capture=AppTheme.Button(workspace.Tools,"拍摄现场",new Vector2(.55f,0),new Vector2(.76f,1),Capture,AppIcon.Camera,true);
            reference=AppTheme.Button(workspace.Tools,"查看官方图",new Vector2(.78f,0),Vector2.one,()=>StartCoroutine(ShowReference()),AppIcon.Info);
            cameraOwner=gameObject.AddComponent<SpatialCamera>();

            photoPlane=AppTheme.Rect(workspace.Main,"Unboxing photo plane",Vector2.zero,Vector2.one);
            photoPlane.gameObject.AddComponent<AspectRatioFitter>().aspectMode=AspectRatioFitter.AspectMode.FitInParent;
            photoPlane.gameObject.AddComponent<RectMask2D>();
            image=AppTheme.Rect(photoPlane,"Unboxing image",Vector2.zero,Vector2.one).gameObject.AddComponent<RawImage>();
            graphic=AppTheme.Rect(photoPlane,"Unboxing motion",Vector2.zero,Vector2.one).gameObject.AddComponent<SpatialAssetGraphic>();
            graphic.raycastTarget=false;
            var trigger=photoPlane.gameObject.AddComponent<EventTrigger>();
            var click=new EventTrigger.Entry{eventID=EventTriggerType.PointerClick};
            click.callback.AddListener(e=>Place((PointerEventData)e));trigger.triggers.Add(click);
            emptyHint=AppTheme.Label(workspace.Main,"启动相机拍摄现场，或先播放动作示意",new Vector2(.1f,.4f),new Vector2(.9f,.6f),22,AppTheme.Muted);
            emptyHint.alignment=TextAnchor.MiddleCenter;
            stepTitle=AppTheme.Label(workspace.Aside,"",new Vector2(.05f,.84f),new Vector2(.95f,.98f),28,AppTheme.TargetCyan);
            var body=AppContent.Scroll(workspace.Aside,"开箱动作和核验结果",new Vector2(.04f,.18f),new Vector2(.96f,.82f));
            copy=AppContent.Paragraph(body,"",23);
            status=AppContent.Paragraph(body,"",22,AppTheme.TargetCyan);
            play=AppTheme.Button(workspace.Aside,"播放动作示意",new Vector2(.05f,.035f),new Vector2(.95f,.15f),()=>StartCoroutine(Play(.5f,.5f)),AppIcon.Play);
            caption=AppTheme.Label(root,"",new Vector2(.025f,.105f),new Vector2(.975f,.137f),18,AppTheme.Muted);
            previous=AppTheme.Button(workspace.FooterLeft,"上一步",Vector2.zero,Vector2.one,()=>Navigate(-1),AppIcon.Back);
            next=AppTheme.Button(workspace.FooterLeft,"下一步",Vector2.zero,Vector2.one,()=>Navigate(1),AppIcon.Play);
            skip=AppTheme.Button(workspace.FooterLeft,"跳过选配章节",Vector2.zero,Vector2.one,SkipOptional,AppIcon.Play);
            AppActionBar.Add(workspace.FooterLeft,skip);
            check=AppTheme.Button(workspace.FooterRight,"评估现场",Vector2.zero,Vector2.one,CheckCurrent,AppIcon.Check,true);
            AppActionBar.Add(workspace.FooterLeft,previous);AppActionBar.Add(workspace.FooterLeft,next);AppActionBar.Add(workspace.FooterRight,check);
        }

        static string Digest(byte[] bytes)
        {
            using(var sha=SHA256.Create())return BitConverter.ToString(sha.ComputeHash(bytes)).Replace("-","").ToLowerInvariant();
        }

        void SetImage(byte[] bytes)
        {
            if(texture==null)texture=new Texture2D(2,2,TextureFormat.RGB24,false);
            if(!texture.LoadImage(bytes)){ClearMedia();Feedback("图片读取失败，请重新拍摄。");return;}
            image.texture=texture;image.color=Color.white;emptyHint.gameObject.SetActive(false);
            photoPlane.GetComponent<AspectRatioFitter>().aspectRatio=(float)texture.width/texture.height;
        }

        void ClearMedia()
        {
            mediaVersion++;
            cameraOwner.Close();previewing=false;captured=null;displayedSha="";activePresentation=null;renderFrame=null;
            graphic.Clear();image.texture=null;image.color=Color.clear;image.uvRect=new Rect(0,0,1,1);
            photoPlane.GetComponent<AspectRatioFitter>().aspectRatio=4f/3;
            RenderStatus();
        }

        void SelectAction(int index)
        {
            actionIndex=index;ClearMedia();submittedSha=ActionItem?.source_sha256??"";
            lastFrame=Math.Max(lastFrame,current.last_client_frame_id);
            workspace.Title.text=AppTheme.Readable(current.task_info.title+" · 第 "+(current.step_index+1)+" / "+current.step_count+" 章");
            stepTitle.text=AppTheme.Readable(ActionItem==null?"官方步骤":(ActionItem.optional?"可选 · ":"")+ActionItem.title);
            copy.text=AppTheme.Readable(HolderBlocked?"请点“上一步”，拍摄并核实底座。":ActionItem==null?current.presentation.instruction:ActionItem.instruction);
            if(ActionItem!=null&&!string.IsNullOrEmpty(ActionItem.target))copy.text+=AppTheme.Readable("\n\n操作位置　"+ActionItem.target);
            if(ActionItem!=null&&!string.IsNullOrEmpty(current.photo_ar.reason))copy.text+=AppTheme.Readable("\n\n"+current.photo_ar.reason);
            if(ActionItem!=null&&!string.IsNullOrEmpty(ActionItem.visual_check))copy.text+=AppTheme.Readable("\n\n拍摄时请看　"+ActionItem.visual_check);
            caption.text=ActionItem==null?"请阅读官方步骤。":string.IsNullOrEmpty(ActionItem.visual_check)?
                "动作可单独播放，实际操作后请人工核实。":"可先播放动作，或拍摄现场后核验。";
            RenderStatus();Refresh();
            if(CurrentReference()!=null)StartCoroutine(ShowReference());
        }

        UnboxingPhoto CurrentReference()
        {
            if(ActionItem!=null)return string.IsNullOrEmpty(ActionItem.reference?.sha256)?null:ActionItem.reference;
            return Array.Find(current.presentation.images??Array.Empty<UnboxingPhoto>(),p=>p!=null&&!string.IsNullOrEmpty(p.sha256));
        }

        IEnumerator ShowReference()
        {
            var photo=CurrentReference();
            if(closed||busy||photo==null)yield break;
            ClearMedia();int version=mediaVersion;Refresh();
            caption.text="正在读取官方参考图…";
            byte[] bytes=null;yield return loadBytes(photo.url,data=>bytes=data);
            if(closed||version!=mediaVersion)yield break;
            if(bytes==null||Digest(bytes)!=photo.sha256){caption.text="参考图读取失败，可以重新载入或拍摄现场。";Refresh();yield break;}
            // Unity cannot decode GIF. The tutorial packages a hash-checked still atlas for its first frame.
            if(photo.animation_frames!=null&&photo.animation_frames.Length>0){
                var frame=photo.animation_frames[0];
                yield return loadBytes(frame.url,data=>bytes=data);
                if(closed||version!=mediaVersion)yield break;
                if(bytes==null||Digest(bytes)!=frame.sha256||frame.uv==null||frame.uv.Length!=4){caption.text="动图预览读取失败，请拍摄现场。";yield break;}
                SetImage(bytes);
                if(image.texture!=null){
                    var uv=new Rect(frame.uv[0],frame.uv[1],frame.uv[2],frame.uv[3]);
                    image.uvRect=uv;photoPlane.GetComponent<AspectRatioFitter>().aspectRatio=texture.width*uv.width/(texture.height*uv.height);
                }
            } else SetImage(bytes);
            if(image.texture!=null){displayedSha=photo.sha256;caption.text="官方参考图 · 仅供演示。点击操作位置放置动画。";}
            Refresh();
        }

        void SwitchCamera()
        {
            if(cameraOwner==null||busy)return;
            ClearMedia();caption.text="镜头已切换，请启动相机。";Refresh();
        }

        IEnumerator StartCamera()
        {
            if(closed||busy)yield break;
            ClearMedia();busy=true;caption.text="正在启动相机…";Refresh();
            string error=null;yield return cameraOwner.Open(devices.value,e=>error=e);
            if(closed)yield break;
            busy=false;previewing=error==null&&cameraOwner.Ready;
            caption.text=previewing?"实时取景 · 对准当前操作位置，点击拍摄现场。":error??"摄像头未就绪。";Refresh();
        }

        void Capture()
        {
            if(closed||busy||!previewing)return;
            var bytes=cameraOwner.Capture();
            if(bytes==null){caption.text="尚未收到新画面，请稍后再拍。";return;}
            ClearMedia();SetImage(bytes);
            if(image.texture!=null){captured=bytes;displayedSha=Digest(bytes);caption.text="现场照片 · 点击操作位置放置动画，或提交核验。";}
            Refresh();
        }

        void Place(PointerEventData pointer)
        {
            if(closed||busy||previewing||ActionItem==null||!LibraryReady)return;
            if(!RectTransformUtility.ScreenPointToLocalPointInRectangle(photoPlane,pointer.position,pointer.pressEventCamera,out var local))return;
            var r=photoPlane.rect;
            StartCoroutine(Play(Mathf.Clamp((local.x-r.xMin)/r.width,.05f,.95f),Mathf.Clamp((r.yMax-local.y)/r.height,.05f,.95f)));
        }

        void RenderStatus()
        {
            var item=ActionItem;
            if(item==null){Feedback(current.photo_ar.reason);return;}
            string label;
            switch(item.status){
                case "verified":label="本动作已核实";break;
                case "needs_manual":label="待人工核实";break;
                case "not_met":label="现场条件未满足";break;
                case "needs_photo":label="画面不足，请补拍";break;
                default:label="待核验";break;
            }
            string provenance=!string.IsNullOrEmpty(item.source_sha256)&&(!LivePhoto||displayedSha!=item.source_sha256)?"本会话上次现场照片":null;
            Feedback(string.Join("\n",Array.FindAll(new[]{label,provenance,item.evidence,item.next_action!=item.evidence?item.next_action:null},s=>!string.IsNullOrWhiteSpace(s))));
        }

        void Feedback(string message){status.text=AppTheme.Readable(message??"");}

        static bool ManualReady(UnboxingArAction item)
        {
            return item?.status=="needs_manual"&&item.manual_checks?.Length>0
                &&(string.IsNullOrEmpty(item.visual_check)||item.source_sha256?.Length==64);
        }

        void Refresh()
        {
            var item=ActionItem;
            bool idle=!busy&&!closed&&dialog==null;
            start.gameObject.SetActive(item!=null);devices.gameObject.SetActive(item!=null);capture.gameObject.SetActive(item!=null);
            start.interactable=idle&&!previewing;devices.interactable=idle;
            capture.interactable=idle&&previewing&&cameraOwner.Ready;
            reference.interactable=idle&&CurrentReference()!=null;
            play.gameObject.SetActive(item!=null);
            play.interactable=idle&&!previewing&&LibraryReady;
            emptyHint.gameObject.SetActive(image.texture==null&&activePresentation==null);
            if(item!=null&&!LibraryReady)caption.text="动画资产版本不匹配，请同步开箱资产并更新客户端。";
            previous.interactable=idle&&(actionIndex>0||current.step_index>0||SubstepIndex()>0);
            next.interactable=idle&&!NextNeedsBase;
            next.GetComponentInChildren<Text>().text=AppTheme.Readable(NextNeedsBase?"核实底座后继续":AtEnd()?"结束本次指引":item!=null&&item.status!="verified"?"浏览下一步":"下一步");
            skip.gameObject.SetActive(current.task_info.steps[current.step_index].optional);skip.interactable=idle;
            bool newPhoto=item!=null&&!string.IsNullOrEmpty(item.visual_check)&&LivePhoto&&displayedSha!=submittedSha;
            bool manual=ManualReady(item)&&!newPhoto&&!previewing;
            check.gameObject.SetActive(item!=null&&(manual||!string.IsNullOrEmpty(item.visual_check)));
            check.interactable=idle&&(manual||newPhoto);
            string label=manual?"核实人工项目":item?.status=="needs_photo"?"评估补拍照片":item?.status=="unassessed"?"评估现场":"拍照核验";
            check.GetComponentInChildren<Text>().text=AppTheme.Readable(busy?"处理中…":label);
        }

        int SubstepIndex()
        {
            return Array.FindIndex(current.substeps??Array.Empty<UnboxingSubstep>(),s=>s.id==current.selected_substep_id);
        }

        bool AtEnd()
        {
            return actionIndex+1>=Actions.Length&&SubstepIndex()+1>=(current.substeps?.Length??0)&&current.step_index+1>=current.step_count;
        }

        void Navigate(int delta)
        {
            if(closed||busy||delta>0&&NextNeedsBase)return;
            int index=actionIndex+delta;
            if(index>=0&&index<Actions.Length){SelectAction(index);return;}
            int sub=SubstepIndex()+delta;
            if(sub>=0&&sub<(current.substeps?.Length??0)){
                if(current.substeps[sub].locked){Feedback(current.u7_sequence?.message??"请先核实前一步。");return;}
                StartCoroutine(Browse(current.state_id,current.substeps[sub].id,delta));return;
            }
            int chapter=current.step_index+delta;
            if(chapter>=current.step_count){ShowFinish();return;}
            if(chapter<0)return;
            var step=current.task_info.steps[chapter];var subs=step.substeps;
            string targetSub=subs==null||subs.Length==0?null:subs[delta>0?0:subs.Length-1].id;
            if(delta<0&&step.id=="U7"&&current.u7_sequence?.base_approved==false&&targetSub=="U7-S2")targetSub="U7-S1";
            StartCoroutine(Browse(step.id,targetSub,delta));
        }

        void SkipOptional()
        {
            if(busy||closed||!current.task_info.steps[current.step_index].optional)return;
            if(current.step_index+1>=current.step_count){ShowFinish();return;}
            var step=current.task_info.steps[current.step_index+1];
            StartCoroutine(Browse(step.id,step.substeps!=null&&step.substeps.Length>0?step.substeps[0].id:null,1));
        }

        void ShowFinish()
        {
            dialog=AppDialog.Open(root,"Unboxing guide summary","已浏览到开箱指引末尾",AppDialogSize.Standard,CloseDialog);
            var sheet=AppContent.Scroll(dialog.Panel,"开箱浏览结果",new Vector2(.06f,.25f),new Vector2(.94f,.82f));
            int marked=Array.FindAll(current.chapter_completion??Array.Empty<ChapterCompletion>(),chapter=>chapter.completed).Length;
            AppContent.Paragraph(sheet,current.flow_label+" · 已浏览 "+(current.visited_step_ids?.Length??0)+" / "+current.step_count+" 章",25);
            if(current.photo_ar.total_actions>0)
                AppContent.Paragraph(sheet,"已核实动作　"+current.photo_ar.verified_actions+" / "+current.photo_ar.total_actions+"（含选配项）",24,AppTheme.TargetCyan);
            AppContent.Paragraph(sheet,"已有完成记录的章节　"+marked+" / "+current.step_count+"。可返回相应章节查看实际核实结果。",23);
            AppTheme.Button(dialog.Panel,"返回开箱图文",new Vector2(.06f,.05f),new Vector2(.94f,.18f),()=>{CloseDialog();Close();},AppIcon.Back,true);
            Refresh();
        }

        IEnumerator Browse(string chapter,string substep,int direction)
        {
            var sent=current;busy=true;Refresh();
            var command=new GuidanceBrowse{state_id=sent.state_id,revision=sent.revision,target_state_id=chapter,substep_id=substep};
            string error=null;GuidanceRun incoming=null;
            yield return request(Api+"/browse","POST",JsonUtility.ToJson(command),(raw,e)=>{error=e;if(e==null)incoming=ParseRun(raw);});
            busy=false;
            if(ValidRun(incoming,sent)&&incoming.state_id==chapter&&(string.IsNullOrEmpty(substep)||incoming.selected_substep_id==substep)){
                current=incoming;SelectAction(direction>0?0:Math.Max(0,Actions.Length-1));
            } else {yield return Recover(sent,error??"返回的步骤与本次选择不一致。");}
        }

        // A lost acknowledgement can follow a committed photo or navigation. Read back before retrying.
        IEnumerator Recover(GuidanceRun sent,string reason)
        {
            busy=true;Refresh();GuidanceRun saved=null;
            yield return request(Api,"GET",null,(raw,error)=>{if(error==null)saved=ParseRun(raw);});
            busy=false;
            if(SameRun(saved,sent)&&saved.revision>sent.revision){
                string id=ActionItem?.action_id;current=saved;
                SelectAction(Math.Max(0,Array.FindIndex(Actions,item=>item.action_id==id)));
                Feedback("已从服务端恢复本次进度。\n"+status.text);
            }else{Feedback(reason+" 请重试。");Refresh();}
        }

        static GuidanceRun ParseRun(string raw)
        {
            try{return JsonUtility.FromJson<GuidanceRun>(raw);}catch(ArgumentException){return null;}
        }

        static bool SameRun(GuidanceRun value,GuidanceRun sent)
        {
            return value!=null&&value.photo_ar?.schema_version==Schema&&value.run_id==sent.run_id&&value.variant_id==sent.variant_id
                &&value.task_id==sent.task_id&&value.task_revision==sent.task_revision&&value.status=="running"
                &&value.presentation!=null&&value.task_info?.steps?.Length==value.step_count
                &&value.step_index>=0&&value.step_index<value.step_count&&value.task_info.steps[value.step_index]?.id==value.state_id;
        }

        static bool ValidRun(GuidanceRun value,GuidanceRun sent){return SameRun(value,sent)&&value.revision==sent.revision+1;}

        T StampFor<T>(string source) where T:Stamp,new()
        {
            return new T{state_id=current.state_id,revision=current.revision,variant_id=current.variant_id,
                substep_id=ActionItem.substep_id??"",action_id=ActionItem.action_id,source_sha256=source??""};
        }

        void CheckCurrent()
        {
            if(closed||busy||previewing||ActionItem==null)return;
            if(LivePhoto&&displayedSha!=submittedSha&&!string.IsNullOrEmpty(ActionItem.visual_check)){
                var cmd=StampFor<CaptureCommand>(displayedSha);cmd.client_frame_id=++lastFrame;cmd.image_base64=Convert.ToBase64String(captured);
                StartCoroutine(Submit("ar-photo",cmd,cmd.client_frame_id));return;
            }
            if(!ManualReady(ActionItem))return;
            dialog=AppDialog.Open(root,"Unboxing manual checks","请逐项实际核实",AppDialogSize.Standard,CloseDialog);
            var list=AppContent.Scroll(dialog.Panel,"本动作人工项目",new Vector2(.06f,.25f),new Vector2(.94f,.85f));
            if(!string.IsNullOrEmpty(ActionItem.visual_check))
                AppContent.Paragraph(list,(LivePhoto&&displayedSha==ActionItem.source_sha256?"本次现场照片":"本会话上次现场照片")+"　"+ActionItem.evidence,23,AppTheme.TargetCyan);
            foreach(var condition in ActionItem.manual_checks)AppContent.Paragraph(list,"• "+condition,24);
            var command=StampFor<ManualCommand>(ActionItem.source_sha256);command.confirmed_checks=ActionItem.manual_checks;
            AppTheme.Button(dialog.Panel,"以上项目均已核实",new Vector2(.05f,.05f),new Vector2(.62f,.18f),
                ()=>{CloseDialog();StartCoroutine(Submit("ar-manual",command,0));},AppIcon.Check,true);
            AppTheme.Button(dialog.Panel,"暂不确认",new Vector2(.65f,.05f),new Vector2(.95f,.18f),CloseDialog,AppIcon.Close);Refresh();
        }

        IEnumerator Submit(string route,Stamp command,int frameId)
        {
            if(busy||closed)yield break;
            // Remove the previous revision's illustration before presenting any new evidence.
            activePresentation=null;renderFrame=null;graphic.Clear();
            var sent=current;busy=true;Feedback(frameId==0?"正在保存人工核实…":"正在检查本次现场照片…");Refresh();
            GuidanceRun incoming=null;string error=null;
            yield return request(Api+"/"+route,"POST",JsonUtility.ToJson(command),(raw,e)=>{error=e;if(e==null)incoming=ParseRun(raw);});
            busy=false;
            bool valid=ValidRun(incoming,sent)&&incoming.state_id==sent.state_id&&(frameId==0||incoming.last_client_frame_id==frameId);
            var returned=incoming?.photo_ar?.actions??Array.Empty<UnboxingArAction>();
            // A new holder photo can contradict a prerequisite. Only follow that redirect on the accepted frame.
            if(valid&&frameId>0&&command.action_id=="holder.slide"&&sent.state_id=="U7"&&sent.selected_substep_id=="U7-S2"&&
                incoming.selected_substep_id=="U7-S1"&&incoming.u7_sequence?.base_approved==false){
                int baseIndex=Array.FindIndex(returned,item=>item.action_id=="holder.base"&&item.source_sha256==command.source_sha256);
                if(baseIndex>=0){
                    current=incoming;SelectAction(baseIndex);
                    Feedback("本次照片需要重新核实底座。\n"+status.text);
                    yield break;
                }
            }
            var updated=Array.Find(returned,item=>item.action_id==command.action_id);
            if(!valid||incoming.selected_substep_id!=sent.selected_substep_id||updated==null||(updated.source_sha256??"")!=command.source_sha256){
                yield return Recover(sent,error??"回复与当前动作或照片不一致。");yield break;
            }
            current=incoming;actionIndex=Array.IndexOf(Actions,updated);
            if(frameId>0)submittedSha=command.source_sha256;
            RenderStatus();Refresh();
        }

        IEnumerator Play(float x,float y)
        {
            if(closed||busy||previewing||ActionItem==null||!LibraryReady)yield break;
            mediaVersion++;
            var cmd=StampFor<PlayCommand>(displayedSha);cmd.anchor_x=x;cmd.anchor_y=y;
            cmd.width=image.texture==null?960:Mathf.RoundToInt(texture.width*image.uvRect.width);
            cmd.height=image.texture==null?720:Mathf.RoundToInt(texture.height*image.uvRect.height);
            busy=true;Refresh();Illustration value=null;string error=null;
            yield return request(Api+"/ar-illustration","POST",JsonUtility.ToJson(cmd),(raw,e)=>{
                error=e;if(e==null)try{value=JsonUtility.FromJson<Illustration>(raw);}catch(ArgumentException){}
            });
            busy=false;
            if(value==null||value.run_id!=current.run_id||value.revision!=cmd.revision||value.state_id!=cmd.state_id||
                value.variant_id!=cmd.variant_id||(value.substep_id??"")!=cmd.substep_id||value.action_id!=cmd.action_id||
                (value.source_sha256??"")!=displayedSha||!value.illustrative_only||value.width!=cmd.width||value.height!=cmd.height||
                value.projection?.intrinsics?.Length!=9||value.projection.camera_from_marker?.Length!=16||
                value.presentation?.catalog_sha256!=current.photo_ar.asset_library.catalog_sha256||
                !VisualAssetLibrary.Validate(value.presentation)||value.presentation.presentation_id!=ActionItem.presentation_id||
                !(value.presentation.duration_seconds>0)){
                Feedback(error??"动画与本步或照片不匹配，请重新进入开箱指引。");Refresh();yield break;
            }
            activePresentation=value.presentation;animationAt=Time.realtimeSinceStartup;
            renderFrame=new VisualRenderFrame{ReferenceSpaceId=activePresentation.reference_space_id,SourceSha256=displayedSha,
                Width=value.width,Height=value.height,CameraFromReference=value.projection.camera_from_marker,
                Intrinsics=value.projection.intrinsics,Distortion=value.projection.distortion,HasWorldPlacement=false};
            caption.text=(LivePhoto?"现场照片":image.texture==null?"独立动作示意":"官方参考图")+" · 点击操作位置可调整动画。";Refresh();
        }

        void Update()
        {
            if(previewing&&cameraOwner.Ready&&Time.realtimeSinceStartup>=previewAt){
                previewAt=Time.realtimeSinceStartup+.12f;
                var bytes=cameraOwner.Capture();if(bytes!=null)SetImage(bytes);
            }
            if(activePresentation!=null&&renderFrame!=null)
                graphic.Present(activePresentation,renderFrame,Mathf.Repeat((Time.realtimeSinceStartup-animationAt)/activePresentation.duration_seconds,1));
        }

        void CloseDialog(){if(dialog!=null){dialog.Close();dialog=null;}Refresh();}

        void Close()
        {
            if(busy||closed)return;
            closed=true;mediaVersion++;cameraOwner.Close();
            root.gameObject.SetActive(false);returnToLesson(current);Destroy(gameObject);
        }

        void OnDestroy(){closed=true;cameraOwner?.Close();if(texture!=null)Destroy(texture);}
    }
}
