using System;
using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Networking;
using UnityEngine.UI;

namespace Manual2AR
{
    /// <summary>Virtualized, in-Unity reader for Chromium-rendered offline articles.</summary>
    public sealed class PrinterLearningWikiView : MonoBehaviour
    {
        Font font;string backend;Text status;RectTransform viewport,sheet,outline;
        ScrollRect scroll;LearningWikiDocument document;UnityWebRequest activeRequest;
        readonly List<RawImage> tileViews=new List<RawImage>();
        readonly Dictionary<int,Texture2D> textures=new Dictionary<int,Texture2D>();
        readonly Stack<LearningSource> history=new Stack<LearningSource>();
        string pageId="",requestedAnchor="";bool loadingTile;float scale=1,lastWidth=-1;

        RectTransform Rect(string name,Transform parent,Vector2 min,Vector2 max)
        {
            var obj=new GameObject(name,typeof(RectTransform));obj.transform.SetParent(parent,false);
            var rect=obj.GetComponent<RectTransform>();rect.anchorMin=min;rect.anchorMax=max;rect.offsetMin=rect.offsetMax=Vector2.zero;return rect;
        }
        Text TextAt(Transform parent,string text,Vector2 min,Vector2 max,int size=19)
        {
            var r=Rect("Text",parent,min,max);var t=r.gameObject.AddComponent<Text>();t.font=font;t.text=text;
            t.fontSize=size;t.color=Color.white;t.supportRichText=false;t.raycastTarget=false;t.verticalOverflow=VerticalWrapMode.Truncate;return t;
        }
        Button ButtonAt(Transform parent,string label,Vector2 min,Vector2 max,Action action)
        {
            var r=Rect(label,parent,min,max);var img=r.gameObject.AddComponent<Image>();img.color=new Color(.02f,.22f,.30f,1);
            var button=r.gameObject.AddComponent<Button>();button.targetGraphic=img;button.onClick.AddListener(()=>action());
            TextAt(r,label,new Vector2(.04f,.04f),new Vector2(.96f,.96f)).alignment=TextAnchor.MiddleCenter;return button;
        }
        public void Initialize(RectTransform panel,Font usedFont,string backendUrl,LearningSource source,Action exit)
        {
            font=usedFont;backend=backendUrl.TrimEnd('/');
            status=TextAt(panel,"正在准备离线 Wiki……",new Vector2(.025f,.865f),new Vector2(.97f,.915f),18);
            ButtonAt(panel,"返回更多信息",new Vector2(.025f,.025f),new Vector2(.24f,.09f),exit);
            ButtonAt(panel,"上一篇",new Vector2(.265f,.025f),new Vector2(.40f,.09f),()=>{
                if(history.Count>0){var previous=history.Pop();Open(previous.page_id,previous.anchor,false);}
            });
            ButtonAt(panel,"回到页首",new Vector2(.425f,.025f),new Vector2(.56f,.09f),()=>Jump(""));
            var tocArea=Rect("Article outline",panel,new Vector2(.025f,.12f),new Vector2(.23f,.85f));
            tocArea.gameObject.AddComponent<Image>().color=new Color(.025f,.09f,.16f,1);
            var tocScroll=tocArea.gameObject.AddComponent<ScrollRect>();tocScroll.horizontal=false;
            var tocView=Rect("Viewport",tocArea,Vector2.zero,Vector2.one);tocView.gameObject.AddComponent<RectMask2D>();
            outline=Rect("Outline",tocView,new Vector2(0,1),new Vector2(1,1));outline.pivot=new Vector2(.5f,1);
            tocScroll.viewport=tocView;tocScroll.content=outline;tocScroll.movementType=ScrollRect.MovementType.Clamped;
            var area=Rect("Offline article",panel,new Vector2(.245f,.12f),new Vector2(.975f,.85f));
            area.gameObject.AddComponent<Image>().color=Color.white;scroll=area.gameObject.AddComponent<ScrollRect>();scroll.horizontal=false;
            viewport=Rect("Viewport",area,Vector2.zero,Vector2.one);viewport.gameObject.AddComponent<RectMask2D>();
            sheet=Rect("Document",viewport,new Vector2(0,1),new Vector2(1,1));sheet.pivot=new Vector2(.5f,1);
            scroll.viewport=viewport;scroll.content=sheet;scroll.movementType=ScrollRect.MovementType.Clamped;scroll.scrollSensitivity=45;
            Open(source.page_id,source.anchor,false);
        }
        void ReleaseTiles()
        {
            foreach(var item in textures.Values)if(item!=null)Destroy(item);textures.Clear();tileViews.Clear();
            if(sheet!=null)foreach(Transform child in sheet)Destroy(child.gameObject);
            if(outline!=null)foreach(Transform child in outline)Destroy(child.gameObject);
        }
        void Open(string identity,string anchor,bool remember=true)
        {
            if(string.IsNullOrEmpty(identity)){status.text="此链接未包含在当前离线快照中。";return;}
            if(identity==pageId&&document!=null){Jump(anchor);return;}
            if(remember&&!string.IsNullOrEmpty(pageId))history.Push(new LearningSource{page_id=pageId,anchor=""});
            if(activeRequest!=null)activeRequest.Abort();StopAllCoroutines();activeRequest=null;
            ReleaseTiles();document=null;loadingTile=false;pageId=identity;requestedAnchor=anchor??"";lastWidth=-1;
            sheet.anchoredPosition=Vector2.zero;sheet.sizeDelta=Vector2.zero;StartCoroutine(LoadDocument());
        }
        IEnumerator LoadDocument()
        {
            float deadline=Time.realtimeSinceStartup+180;
            while(Time.realtimeSinceStartup<deadline){
                using(var request=UnityWebRequest.Get(backend+"/api/learning/wiki/pages/"+pageId+"/render")){
                    request.timeout=30;activeRequest=request;yield return request.SendWebRequest();activeRequest=null;
                    if(request.result!=UnityWebRequest.Result.Success){status.text="文章暂时无法打开，请稍后重试。";yield break;}
                    LearningWikiDocument value=null;
                    try{value=JsonUtility.FromJson<LearningWikiDocument>(request.downloadHandler.text);}catch(Exception){ }
                    if(value==null){status.text="文章暂时无法打开。";yield break;}
                    if(value.state=="failed"){status.text="文章暂时无法打开，请稍后重试。";yield break;}
                    if(value.state=="ready"){
                        if(value.width<=0||value.height<=0||value.tiles==null||value.tiles.Length==0){status.text="文章暂时无法打开。";yield break;}
                        document=value;BuildDocument();status.text=value.title;Canvas.ForceUpdateCanvases();LayoutDocument();Jump(requestedAnchor);yield break;
                    }
                    status.text=value.state=="queued"?"正在打开文章……":"正在打开文章……";
                }
                yield return new WaitForSecondsRealtime(.5f);
            }
            status.text="离线文章准备超时，请关闭后重试。";
        }
        void BuildDocument()
        {
            foreach(var tile in document.tiles){
                var rect=Rect("Article tile "+tile.index,sheet,new Vector2(0,1),new Vector2(1,1));rect.pivot=new Vector2(.5f,1);
                var view=rect.gameObject.AddComponent<RawImage>();view.color=Color.white;tileViews.Add(view);
            }
            int row=0;
            foreach(var anchor in document.anchors??new LearningWikiAnchor[0]){
                if(!anchor.is_heading)continue;var captured=anchor.id;
                var b=ButtonAt(outline,anchor.title,new Vector2(0,1),new Vector2(1,1),()=>Jump(captured));
                var r=b.GetComponent<RectTransform>();r.pivot=new Vector2(.5f,1);r.anchoredPosition=new Vector2(0,-row*64);r.sizeDelta=new Vector2(0,60);row++;
            }
            outline.sizeDelta=new Vector2(0,row*64);
            foreach(var link in document.links??new LearningWikiLink[0]){
                var captured=link;var r=Rect("Wiki link",sheet,new Vector2(0,1),new Vector2(0,1));r.pivot=new Vector2(0,1);
                var image=r.gameObject.AddComponent<Image>();image.color=Color.clear;
                var button=r.gameObject.AddComponent<Button>();button.transition=Selectable.Transition.None;button.targetGraphic=image;
                button.onClick.AddListener(()=>Open(captured.page_id,captured.anchor));
            }
        }
        void LayoutDocument()
        {
            if(document==null||viewport.rect.width<=1)return;
            float oldScale=scale;scale=viewport.rect.width/document.width;
            if(lastWidth>0&&oldScale>0)sheet.anchoredPosition=new Vector2(0,sheet.anchoredPosition.y*scale/oldScale);
            sheet.sizeDelta=new Vector2(0,document.height*scale);
            for(int i=0;i<document.tiles.Length;i++){
                var tile=document.tiles[i];var r=tileViews[i].rectTransform;
                r.anchoredPosition=new Vector2(0,-tile.y*scale);r.sizeDelta=new Vector2(0,tile.height*scale);
            }
            int child=document.tiles.Length;
            foreach(var link in document.links??new LearningWikiLink[0]){
                var r=(RectTransform)sheet.GetChild(child++);r.anchoredPosition=new Vector2(link.x*scale,-link.y*scale);r.sizeDelta=new Vector2(link.width*scale,link.height*scale);
            }
            lastWidth=viewport.rect.width;
        }
        void Jump(string anchor)
        {
            if(document==null)return;float y=0;bool found=string.IsNullOrEmpty(anchor);
            foreach(var a in document.anchors??new LearningWikiAnchor[0])if(a.id==anchor){y=a.y;found=true;break;}
            scroll.StopMovement();sheet.anchoredPosition=new Vector2(0,Mathf.Clamp(y*scale,0,Mathf.Max(0,sheet.rect.height-viewport.rect.height)));
            status.text=found?document.title:document.title+" · 已打开文章，请从目录选择章节。";
        }
        void Update()
        {
            if(AppShell.Changing)return;
            if(document==null)return;
            if(Mathf.Abs(viewport.rect.width-lastWidth)>.5f)LayoutDocument();
            float first=sheet.anchoredPosition.y/scale,last=(sheet.anchoredPosition.y+viewport.rect.height)/scale;
            var evict=new List<int>();
            foreach(var pair in textures){var tile=document.tiles[pair.Key];if(tile.y+tile.height<first-2048||tile.y>last+2048)evict.Add(pair.Key);}
            foreach(var index in evict){tileViews[index].texture=null;Destroy(textures[index]);textures.Remove(index);}
            if(loadingTile)return;
            for(int i=0;i<document.tiles.Length;i++){
                var tile=document.tiles[i];
                if(tile.y+tile.height>=first-512&&tile.y<=last+512&&!textures.ContainsKey(i)){StartCoroutine(LoadTile(i));break;}
            }
        }
        IEnumerator LoadTile(int index)
        {
            loadingTile=true;
            using(var request=UnityWebRequestTexture.GetTexture(backend+document.tiles[index].url)){
                request.timeout=30;activeRequest=request;yield return request.SendWebRequest();activeRequest=null;
                if(request.result==UnityWebRequest.Result.Success){
                    var texture=DownloadHandlerTexture.GetContent(request);textures[index]=texture;tileViews[index].texture=texture;
                }else{status.text="图片暂时无法加载，请稍后重试。";yield return new WaitForSecondsRealtime(2);}
            }
            loadingTile=false;
        }
        void OnDisable()
        {
            if(activeRequest!=null)activeRequest.Abort();StopAllCoroutines();activeRequest=null;ReleaseTiles();document=null;
        }
    }
}
