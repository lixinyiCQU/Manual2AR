using UnityEngine;
using UnityEngine.UI;
using Manual2AR.VisualGuidance;
namespace Manual2AR.Spatial {
 public sealed class SpatialPartsView {
  public readonly System.Collections.Generic.List<Rect> LabelRects=new System.Collections.Generic.List<Rect>();
  readonly RawImage overlay;readonly VisualImageProxyGraphic proxy;readonly SpatialOverlay boxes;readonly RectTransform viewport;Texture2D texture;
  public SpatialPartsView(RectTransform parent){
   viewport=parent;overlay=AppTheme.Rect(parent,"Matched part masks",Vector2.zero,Vector2.one).gameObject.AddComponent<RawImage>();overlay.raycastTarget=false;overlay.color=Color.clear;
   proxy=AppTheme.Rect(parent,"Image-space holder proxy",Vector2.zero,Vector2.one).gameObject.AddComponent<VisualImageProxyGraphic>();proxy.raycastTarget=false;
   boxes=AppTheme.Rect(parent,"Semantic part boxes",Vector2.zero,Vector2.one).gameObject.AddComponent<SpatialOverlay>();boxes.raycastTarget=false;

  }
  public void Apply(PartStatus value,int width,int height){
   Clear();if(!string.IsNullOrEmpty(value.overlay_png_base64)){texture=new Texture2D(2,2,TextureFormat.RGBA32,false);if(ImageConversion.LoadImage(texture,System.Convert.FromBase64String(value.overlay_png_base64))){overlay.texture=texture;overlay.color=Color.white;}}
   var lines=new System.Collections.Generic.List<Segment>();boxes.width=width;boxes.height=height;
   int index=0;foreach(var part in value.parts??new LocatedPart[0]){
    if(part.status!="found"||part.bbox_0_1000==null||part.bbox_0_1000.Length!=4||index>=2)continue;index++;
    if(value.phase=="tracking"&&part.proxy!=null&&part.proxy.coordinate_space=="image_proxy"){proxy.AssetId=part.proxy.asset_id;proxy.Box=part.proxy.bbox_0_1000;proxy.Angle=part.proxy.angle_degrees;proxy.Width=width;proxy.Height=height;proxy.SetVerticesDirty();}
    if(string.IsNullOrEmpty(value.overlay_png_base64)){var b=part.bbox_0_1000;var p=new[]{new Pixel(b[0]*width/1000f,b[1]*height/1000f),new Pixel(b[2]*width/1000f,b[1]*height/1000f),new Pixel(b[2]*width/1000f,b[3]*height/1000f),new Pixel(b[0]*width/1000f,b[3]*height/1000f)};for(int i=0;i<4;i++)lines.Add(new Segment{a=p[i],b=p[(i+1)%4]});}
   }
   boxes.lines=lines.ToArray();boxes.SetVerticesDirty();
  }
  public void Clear(){LabelRects.Clear();overlay.texture=null;overlay.color=Color.clear;if(texture!=null)Object.Destroy(texture);texture=null;proxy.Clear();boxes.Clear();}
 }
}
