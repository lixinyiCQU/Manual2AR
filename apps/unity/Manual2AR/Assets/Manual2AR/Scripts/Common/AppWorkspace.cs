using UnityEngine;
using UnityEngine.UI;

namespace Manual2AR {
 public enum AppWorkspaceKind {Visual,Reading}
 /// <summary>Owns screen regions only. Modules retain camera, inference and task state.</summary>
 public sealed class AppWorkspace {
  public static readonly Vector2 BackMin=new Vector2(.805f,.925f),BackMax=new Vector2(.975f,.985f);
  public RectTransform Main {get;private set;}
  public RectTransform Aside {get;private set;}
  public RectTransform Tools {get;private set;}
  public RectTransform HeaderActions {get;private set;}
  public RectTransform FooterLeft {get;private set;}
  public RectTransform FooterRight {get;private set;}
  public Text Title {get;private set;}
  public AppWorkspace(Transform root,string title,AppWorkspaceKind kind=AppWorkspaceKind.Visual){
   Title=AppTheme.Label(root,title,new Vector2(.025f,.915f),new Vector2(.57f,.995f),AppTheme.TitleSize);
   HeaderActions=AppTheme.Rect(root,"Header actions",new Vector2(.625f,.925f),new Vector2(.795f,.985f));
   Tools=AppTheme.Rect(root,"Workspace tools",new Vector2(.025f,.835f),new Vector2(.975f,.905f));
   Main=AppTheme.Panel(root,"Main content",Vector2.zero,Vector2.one);
   Aside=AppTheme.Panel(root,"Context and feedback",Vector2.zero,Vector2.one);
   FooterLeft=AppTheme.Rect(root,"Related actions",new Vector2(.025f,.025f),new Vector2(.415f,.105f));
   FooterRight=AppTheme.Rect(root,"Task actions",new Vector2(.445f,.025f),new Vector2(.975f,.105f));
   SetKind(kind);AppActionBar.Attach(HeaderActions);AppActionBar.Attach(FooterLeft);AppActionBar.Attach(FooterRight);
  }
  public void SetKind(AppWorkspaceKind kind){
   Place(Main,.025f,.13f,kind==AppWorkspaceKind.Reading?.425f:.715f,.815f);
   Place(Aside,kind==AppWorkspaceKind.Reading?.445f:.735f,.13f,.975f,.815f);
  }
  public void SetReadingContent(bool hasAside){
   Place(Main,hasAside?.025f:.16f,.13f,hasAside?.425f:.84f,.815f);Place(Aside,.445f,.13f,.975f,.815f);Aside.gameObject.SetActive(hasAside);
  }
  public void SetToolsVisible(bool visible){Tools.gameObject.SetActive(visible);Main.anchorMax=new Vector2(Main.anchorMax.x,visible?.815f:.905f);Aside.anchorMax=new Vector2(Aside.anchorMax.x,visible?.815f:.905f);}
  public void SetFooterVisible(bool visible){
   FooterLeft.gameObject.SetActive(visible);FooterRight.gameObject.SetActive(visible);
   Main.anchorMin=new Vector2(Main.anchorMin.x,visible?.13f:.025f);Aside.anchorMin=new Vector2(Aside.anchorMin.x,visible?.13f:.025f);
  }
  public static void Place(RectTransform r,float left,float bottom,float right,float top){r.anchorMin=new Vector2(left,bottom);r.anchorMax=new Vector2(right,top);r.offsetMin=r.offsetMax=Vector2.zero;}
  public static RectTransform Canvas(Transform parent,string name,int order=0){
   var go=new GameObject(name,typeof(RectTransform),typeof(Canvas),typeof(CanvasScaler),typeof(GraphicRaycaster));go.transform.SetParent(parent,false);
   var canvas=go.GetComponent<Canvas>();canvas.renderMode=RenderMode.ScreenSpaceOverlay;canvas.pixelPerfect=true;canvas.sortingOrder=order;
   var scale=go.GetComponent<CanvasScaler>();scale.uiScaleMode=CanvasScaler.ScaleMode.ScaleWithScreenSize;scale.referenceResolution=new Vector2(1920,1080);scale.matchWidthOrHeight=.5f;
   go.AddComponent<Image>().color=AppTheme.Background;return go.GetComponent<RectTransform>();
  }
 }
}
