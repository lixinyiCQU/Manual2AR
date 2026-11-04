using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UI;
namespace Manual2AR.VisualGuidance {
 /// <summary>Native/world text adapter. Caller must supply a registered world reference and viewing camera.</summary>
 public sealed class VisualWorldTextRenderer:MonoBehaviour {
  readonly List<Canvas> labels=new List<Canvas>();public int VisibleCount {get;private set;}
  public void PresentDisplay(GuidanceDisplay display,VisualRenderFrame frame,Camera viewer){var item=VisualTextContent.Directive(display);Present(item==null?new VisualTextLabel[0]:new[]{item},frame,viewer);}
  public void Present(VisualTextLabel[] annotations,VisualRenderFrame frame,Camera viewer){
   Clear();if(frame==null||!frame.HasWorldPlacement||viewer==null)return;
   foreach(var item in annotations??new VisualTextLabel[0]){
    if(item==null||item.reference_space_id!=frame.ReferenceSpaceId||item.position_m==null||item.position_m.Length!=3||VisibleCount>=4)continue;
    if(VisibleCount==labels.Count){var go=new GameObject("World teaching text",typeof(RectTransform),typeof(Canvas));go.transform.SetParent(transform,false);var canvas=go.GetComponent<Canvas>();canvas.renderMode=RenderMode.WorldSpace;var rect=go.GetComponent<RectTransform>();rect.sizeDelta=new Vector2(420,180);rect.localScale=Vector3.one*.0002f;var caption=AppTheme.Label(rect,"",new Vector2(.04f,.04f),new Vector2(.96f,.96f),28);var outline=caption.gameObject.AddComponent<UnityEngine.UI.Outline>();outline.effectColor=Color.black;outline.effectDistance=new Vector2(1.5f,-1.5f);labels.Add(canvas);}
    var label=labels[VisibleCount++];var p=VisualAssetLibrary.Vector(item.position_m);label.transform.position=frame.UnityWorldFromReference.MultiplyPoint3x4(new Vector3(p.x,p.y,-p.z));label.transform.rotation=viewer.transform.rotation;var text=label.GetComponentInChildren<Text>();text.supportRichText=item.kind=="directive";text.text=VisualTextContent.Format(item);text.color=VisualTextContent.ColorFor(item);label.gameObject.SetActive(true);
   }
  }
  public void Clear(){foreach(var label in labels)label.gameObject.SetActive(false);VisibleCount=0;}
 }
}
