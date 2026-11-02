using System;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UI;

namespace Manual2AR
{
    public sealed class PrinterLearningOverlay : MonoBehaviour
    {
        sealed class Layer { public RawImage mask;public Texture2D texture;public RectTransform tag;public Text text;public PrinterLearningLine line;public Material material;public int[] box,center; }
        readonly Dictionary<string,Layer> layers=new Dictionary<string,Layer>();
        RectTransform content,labelRoot;Font font;Action<string> selected;string focus="";Material maskMaterial;Texture2D sharedLabels;RawImage labelImage;Material labelMaterial;bool useLabels,labelsVisible=true;
        bool layoutDirty=true;Rect lastContentRect,lastLabelRect;Matrix4x4 lastTransform;
        readonly Dictionary<string,int> labelIds=new Dictionary<string,int>();
        public int VisibleCount { get { int count=0;foreach(var l in layers.Values) if(l.tag.gameObject.activeSelf) count++;return count; } }
        public void Initialize(RectTransform cameraContent,RectTransform labels,Font f,Action<string> onSelect)
        {
            content=cameraContent;labelRoot=labels;font=f;selected=onSelect;
            var shader=Resources.Load<Shader>("PrinterLearningMask");
            if(shader==null)throw new InvalidOperationException("缺少PrinterLearningMask.shader，请使用完整的新版Unity工程包。");
            maskMaterial=new Material(shader);
        }
        public static Color ComponentColor(string id)
        {
            switch(id) {
                case "build_plate":return new Color32(57,198,244,255);
                case "heated_bed":return new Color32(255,169,77,255);
                case "toolhead":return new Color32(91,224,155,255);
                case "x_axis":return new Color32(242,211,79,255);
                case "z_axis":return new Color32(179,153,255,255);
                case "filament_spool":return new Color32(255,122,168,255);
                case "control_screen":return new Color32(88,220,202,255);
                case "power_switch":return new Color32(247,141,97,255);
                default:return Color.white;
            }
        }
        public void SetLabelMap(LearningLabelMap value)
        {
            if(value==null||string.IsNullOrEmpty(value.png_base64)){useLabels=false;if(labelImage!=null)labelImage.gameObject.SetActive(false);return;}
            if(sharedLabels==null)sharedLabels=new Texture2D(2,2,TextureFormat.RGBA32,false,true);
            if(!ImageConversion.LoadImage(sharedLabels,Convert.FromBase64String(value.png_base64),false)||sharedLabels.width!=value.width||sharedLabels.height!=value.height)throw new InvalidOperationException("Label map decode/dimensions failed");
            sharedLabels.filterMode=FilterMode.Point;sharedLabels.wrapMode=TextureWrapMode.Clamp;
            if(value.labels==null||value.labels.Length<1||value.labels.Length>8)throw new InvalidOperationException("Invalid label mapping");
            if(labelImage==null){
                var go=new GameObject("Shared ID mask",typeof(RectTransform),typeof(RawImage));go.transform.SetParent(content,false);
                var rect=go.GetComponent<RectTransform>();rect.anchorMin=Vector2.zero;rect.anchorMax=Vector2.one;rect.offsetMin=rect.offsetMax=Vector2.zero;
                labelImage=go.GetComponent<RawImage>();labelImage.raycastTarget=false;labelMaterial=new Material(maskMaterial);labelImage.material=labelMaterial;
                labelMaterial.SetFloat("_UseLabels",1);
            }
            useLabels=true;labelsVisible=true;labelIds.Clear();labelImage.texture=sharedLabels;labelImage.gameObject.SetActive(true);
            foreach(var item in value.labels){
                if(item.label_id<1||item.label_id>8||labelIds.ContainsKey(item.component_id))throw new InvalidOperationException("Invalid label ID");
                labelIds[item.component_id]=item.label_id;
                labelMaterial.SetColor("_Palette"+item.label_id,ComponentColor(item.component_id));
                var layer=Ensure(item.component_id);layer.mask.texture=sharedLabels;layer.mask.gameObject.SetActive(false);
                // One uploaded ID texture shared by all layers; ID tested in the shader.
                layer.material.SetFloat("_UseLabels",1);layer.material.SetFloat("_LabelId",item.label_id);
            }
        }
        public void SetAgeVisibility(bool visible)
        {
            layoutDirty=true;labelsVisible=visible;if(labelImage!=null)labelImage.gameObject.SetActive(visible&&useLabels);foreach(var item in layers)SetVisible(item.Value,visible&&item.Value.box!=null&&(focus==""||focus==item.Key));
        }
        public bool Show(string id,string label,LearningTracked tracked,int width,int height,out string error)
        {
            layoutDirty=true;error=null;
            if(tracked==null||tracked.status!="tracking"||!tracked.mask_quality_passed||tracked.requires_redetection||tracked.quality<.45f) {
                error="mask quality rejected";Hide(id);return false;
            }
            try {
                if(useLabels&&(!labelIds.ContainsKey(id)||sharedLabels.width!=width||sharedLabels.height!=height))throw new Exception("Label/frame identity differs");
                Layer l=Ensure(id);
                if(!useLabels&&!ImageConversion.LoadImage(l.texture,Convert.FromBase64String(tracked.overlay_png_base64),false)) throw new Exception("PNG decode failed");
                bool cropped=!useLabels&&tracked.mask_roi_xywh!=null&&tracked.mask_roi_xywh.Length==4;
                var rect=l.mask.rectTransform;
                if(cropped){
                    var roi=tracked.mask_roi_xywh;int x=roi[0],y=roi[1],w=roi[2],h=roi[3];
                    if(tracked.mask_frame_width!=width||tracked.mask_frame_height!=height||x<0||y<0||w<=0||h<=0||x+w>width||y+h>height||l.texture.width!=w||l.texture.height!=h)
                        throw new Exception("mask ROI/frame dimensions differ");
                    rect.anchorMin=new Vector2((float)x/width,1f-(float)(y+h)/height);
                    rect.anchorMax=new Vector2((float)(x+w)/width,1f-(float)y/height);
                } else {
                    if(!useLabels&&(l.texture.width!=width||l.texture.height!=height)) throw new Exception("mask/frame dimensions differ");
                    rect.anchorMin=Vector2.zero;rect.anchorMax=Vector2.one;
                }
                rect.offsetMin=rect.offsetMax=Vector2.zero;
                if(tracked.bbox_0_1000==null||tracked.bbox_0_1000.Length!=4) throw new Exception("missing mask bounds");
                // The shader reads only mask alpha; component colors are set on
                // the GPU, without a per-frame CPU texture recoloring pass.
                l.mask.texture=useLabels?sharedLabels:l.texture;l.material.SetFloat("_UseLabels",useLabels?1:0);l.box=tracked.bbox_0_1000;l.center=tracked.centroid_0_1000;l.text.text=label;
                SetVisible(l,string.IsNullOrEmpty(focus)||focus==id);return true;
            } catch(Exception e) {error=e.Message;Hide(id);return false;}
        }
        public void Select(string id) { layoutDirty=true;focus=id??"";if(labelMaterial!=null)labelMaterial.SetFloat("_LabelId",focus==""?0:(labelIds.TryGetValue(focus,out var index)?index:-99));foreach(var p in layers) SetVisible(p.Value,p.Value.box!=null&&(focus==""||p.Key==focus)); }
        public void Hide(string id) {layoutDirty=true;if(labelMaterial!=null&&labelIds.TryGetValue(id,out var index))labelMaterial.SetColor("_Palette"+index,Color.clear); if(layers.TryGetValue(id,out var l)) { l.box=null;SetVisible(l,false); } }
        public void Clear() {foreach(var p in layers) Hide(p.Key);focus="";if(labelImage!=null)labelImage.gameObject.SetActive(false);}
        void SetVisible(Layer l,bool show) {show=show&&labelsVisible;l.mask.gameObject.SetActive(show&&!useLabels);l.tag.gameObject.SetActive(show);l.line.gameObject.SetActive(show);}
        Layer Ensure(string id)
        {
            if(layers.TryGetValue(id,out var old)) return old;
            var m=new GameObject(id+" mask",typeof(RectTransform),typeof(RawImage));m.transform.SetParent(content,false);
            var r=m.GetComponent<RectTransform>();r.anchorMin=Vector2.zero;r.anchorMax=Vector2.one;r.offsetMin=r.offsetMax=Vector2.zero;
            var color=ComponentColor(id);var mask=m.GetComponent<RawImage>();mask.raycastTarget=false;mask.color=color;mask.material=new Material(maskMaterial);
            // Add the renderer before the Graphic can enter RectMask2D's clipping registry.
            var line=new GameObject(id+" leader",typeof(RectTransform),typeof(CanvasRenderer),typeof(PrinterLearningLine));line.transform.SetParent(labelRoot,false);
            var lr=line.GetComponent<RectTransform>();lr.anchorMin=lr.anchorMax=new Vector2(.5f,.5f);lr.sizeDelta=Vector2.zero;
            var graphic=line.GetComponent<PrinterLearningLine>();graphic.color=color;graphic.raycastTarget=false;
            var tag=new GameObject(id+" label",typeof(RectTransform),typeof(AppRoundedImage),typeof(Button),typeof(Outline));tag.transform.SetParent(labelRoot,false);
            var tr=tag.GetComponent<RectTransform>();tr.anchorMin=tr.anchorMax=new Vector2(.5f,.5f);tr.sizeDelta=new Vector2(205,43);
            tag.GetComponent<Image>().color=new Color(.015f,.09f,.16f,.96f);tag.GetComponent<Outline>().effectColor=color;
            tag.GetComponent<Button>().onClick.AddListener(()=>selected?.Invoke(id));
            var text=new GameObject("Caption",typeof(RectTransform),typeof(Text));text.transform.SetParent(tr,false);
            var rt=text.GetComponent<RectTransform>();rt.anchorMin=Vector2.zero;rt.anchorMax=Vector2.one;rt.offsetMin=new Vector2(7,3);rt.offsetMax=new Vector2(-7,-3);
            var tx=text.GetComponent<Text>();tx.font=font;tx.fontSize=21;tx.color=color;tx.alignment=TextAnchor.MiddleCenter;tx.raycastTarget=false;
            tx.resizeTextForBestFit=true;tx.resizeTextMinSize=14;tx.resizeTextMaxSize=21;
            var l=new Layer{mask=mask,material=mask.material,texture=new Texture2D(2,2,TextureFormat.RGBA32,false),tag=tr,text=tx,line=graphic};
            layers[id]=l;SetVisible(l,false);return l;
        }
        Vector2 Project(float x,float y)
        {
            Rect r=content.rect;
            return labelRoot.InverseTransformPoint(content.TransformPoint(new Vector3(r.xMin+r.width*x/1000f,r.yMax-r.height*y/1000f,0)));
        }
        readonly List<Vector2> placed=new List<Vector2>(8);
        void LateUpdate()
        {
            if(content==null||labelRoot==null)return;
            var transformNow=content.localToWorldMatrix;
            if(!layoutDirty&&content.rect==lastContentRect&&labelRoot.rect==lastLabelRect&&transformNow==lastTransform)return;
            layoutDirty=false;lastContentRect=content.rect;lastLabelRect=labelRoot.rect;lastTransform=transformNow;
            placed.Clear();Rect bounds=labelRoot.rect;
            foreach(var p in layers) {
                Layer l=p.Value;if(l.box==null||!l.tag.gameObject.activeSelf) continue;
                float x=l.center!=null&&l.center.Length==2?l.center[0]:(l.box[0]+l.box[2])*.5f;
                float y=l.center!=null&&l.center.Length==2?l.center[1]:(l.box[1]+l.box[3])*.5f;
                Vector2 center=Project(x,y),top=Project((l.box[0]+l.box[2])*.5f,l.box[1]);
                Vector2 pos=new Vector2(center.x,Mathf.Max(center.y,top.y)+45);
                float half=Mathf.Min(102.5f,Mathf.Max(20,bounds.width*.45f));
                pos.x=Mathf.Clamp(pos.x,bounds.xMin+half+8,bounds.xMax-half-8);
                pos.y=Mathf.Clamp(pos.y,bounds.yMin+29,bounds.yMax-29);
                for(int attempt=0;attempt<8;attempt++) {
                    bool hit=false;foreach(var previous in placed) if(Mathf.Abs(previous.x-pos.x)<205&&Mathf.Abs(previous.y-pos.y)<47) {hit=true;break;}
                    if(!hit)break;
                    pos.y-=49;if(pos.y<bounds.yMin+29) {pos.y=bounds.yMax-29;pos.x=Mathf.Clamp(pos.x+105,bounds.xMin+half+8,bounds.xMax-half-8);}
                }
                placed.Add(pos);l.tag.anchoredPosition=pos;
                l.line.SetPoints(center,pos+new Vector2(0,pos.y>center.y?-21:21));
            }
        }
        void OnDestroy() { foreach(var l in layers.Values) {if(l.texture!=null) Destroy(l.texture);if(l.material!=null)Destroy(l.material);}if(sharedLabels!=null)Destroy(sharedLabels);if(labelMaterial!=null)Destroy(labelMaterial);if(maskMaterial!=null)Destroy(maskMaterial); }
    }
}
