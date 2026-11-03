using UnityEngine;
using UnityEngine.UI;
namespace Manual2AR.Spatial {
 /// <summary>Readable screen-space label connected to a metric, frame-bound point.</summary>
 public sealed class SpatialCallout {
  RectTransform root;Text label;SpatialOverlay overlay;
  public SpatialCallout(SpatialOverlay parent){
   overlay=parent;root=AppTheme.Panel(parent.transform,"Operation Point",Vector2.zero,Vector2.zero);root.pivot=new Vector2(0,.5f);
   label=AppTheme.Label(root,"",new Vector2(.05f,.05f),new Vector2(.95f,.95f),23);label.alignment=TextAnchor.MiddleCenter;
   foreach(var g in root.GetComponentsInChildren<Graphic>())g.raycastTarget=false;Hide();
  }
  public void Show(GuidanceVisual visual){
   var size=overlay.rectTransform.rect.size;if(size.x<1||size.y<1){Hide();return;}
   float width=Mathf.Clamp(35+visual.label.Length*23,150,300),height=42;
   root.sizeDelta=new Vector2(width,height);label.text=AppTheme.Readable(visual.label);
   float x=visual.anchor.x/overlay.width*size.x,y=(1-visual.anchor.y/overlay.height)*size.y;
   float left=Mathf.Clamp(x+28,5,Mathf.Max(5,size.x-width-5));float centre=Mathf.Clamp(y+45,height*.5f+5,size.y-height*.5f-5);
   if(SpatialAssetGraphic.HasPlacement(visual)){
    Vector3 tail=SpatialAssetGraphic.Transform(visual.asset.marker_from_asset,new Vector3(0,-1,0));Vector2 tailPixel;float depth;
    if(SpatialAssetGraphic.Project(visual.projection,tail,out tailPixel,out depth)){
     // Put the label on the other side of the tool, never over the handle/shaft.
     float offset=tailPixel.y<visual.anchor.y?-55:55;
     centre=Mathf.Clamp(y+offset,height*.5f+5,size.y-height*.5f-5);
     left=Mathf.Clamp(x+55,5,Mathf.Max(5,size.x-width-5));
    }
   }
   root.anchoredPosition=new Vector2(left,centre);root.gameObject.SetActive(true);
   overlay.leaderEnd=new Pixel(left/size.x*overlay.width,(1-centre/size.y)*overlay.height);
  }
  public void Hide(){root.gameObject.SetActive(false);overlay.leaderEnd=null;}
 }
}
