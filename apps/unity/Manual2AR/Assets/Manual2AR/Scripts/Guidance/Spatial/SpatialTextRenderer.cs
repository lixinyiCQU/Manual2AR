using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UI;
using Manual2AR.VisualGuidance;
namespace Manual2AR.Spatial {
 /// <summary>Metric anchor labels share collision avoidance with same-frame part names.</summary>
 public sealed class SpatialTextRenderer {
  readonly RectTransform viewport;readonly List<Text> labels=new List<Text>();
  public int VisibleCount {get;private set;}
  public int ContextCount {get;private set;}
  public SpatialTextRenderer(RectTransform parent){viewport=parent;}
  public void Present(GuidanceVisual visual,int width,int height,string advice,GuidanceVisual[] companions=null,IList<Rect> reserved=null){
   Clear();if(visual?.projection==null||width<=0||height<=0)return;
   var occupied=reserved==null?new List<Rect>():new List<Rect>(reserved);
   var identities=new HashSet<string>();
   bool controlled=visual.display?.schema_version=="manual2ar-guidance-display-v1";
   var visuals=new List<GuidanceVisual>{visual};if(companions!=null)visuals.AddRange(companions);
   foreach(var source in visuals)foreach(var item in controlled?(source==visual?new[]{VisualTextContent.Directive(visual.display)}:new VisualTextLabel[0]):source?.text_labels??new VisualTextLabel[0]){
    if(item==null||identities.Contains(item.id)||item.position_m==null||item.position_m.Length!=3||item.reference_space_id!="calibrated-marker"||VisibleCount>=4)continue;
    Vector2 pixel;float depth;if(!SpatialAssetGraphic.Project(source.projection,VisualAssetLibrary.Vector(item.position_m),out pixel,out depth)||pixel.x<0||pixel.y<0||pixel.x>width||pixel.y>height)continue;
    if(VisibleCount==labels.Count){var panel=AppTheme.Rect(viewport,"Metric text annotation",Vector2.zero,Vector2.zero);panel.pivot=Vector2.zero;panel.sizeDelta=new Vector2(240,45);var text=AppTheme.Label(panel,"",Vector2.zero,Vector2.one,22);var outline=text.gameObject.AddComponent<UnityEngine.UI.Outline>();outline.effectColor=Color.black;outline.effectDistance=new Vector2(1.5f,-1.5f);foreach(var g in panel.GetComponentsInChildren<Graphic>())g.raycastTarget=false;labels.Add(text);}
    identities.Add(item.id);bool contextual=item.kind=="context"||item.kind=="directive";if(contextual)ContextCount++;
    var label=labels[VisibleCount++];label.supportRichText=item.kind=="directive";label.text=VisualTextContent.Format(item);label.color=VisualTextContent.ColorFor(item);label.fontSize=26;
    var rect=(RectTransform)label.transform.parent;rect.sizeDelta=contextual?new Vector2(560,150):new Vector2(280,60);var size=viewport.rect.size;float scale=Mathf.Clamp(.6f/depth,1f,1.1f);rect.localScale=Vector3.one*scale;
    rect.anchoredPosition=SpatialLabelLayout.Place(new Vector2(pixel.x/width*size.x+35,(1-pixel.y/height)*size.y+30),rect.sizeDelta*scale,size,occupied);rect.gameObject.SetActive(true);
   }
  }
  public void Clear(){foreach(var label in labels)label.transform.parent.gameObject.SetActive(false);VisibleCount=0;ContextCount=0;}
 }
}
