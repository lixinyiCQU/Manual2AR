using UnityEngine;
using UnityEngine.UI;
using Manual2AR.VisualGuidance;
namespace Manual2AR.Spatial {
 public sealed class SpatialLegend {
  public RectTransform Root {get;private set;}readonly RectTransform viewport;string action;
  public Rect Bounds {get{return new Rect(Root.anchoredPosition.x,viewport.rect.height+Root.anchoredPosition.y-Root.sizeDelta.y,Root.sizeDelta.x,Root.sizeDelta.y);}}
  public SpatialLegend(RectTransform parent){viewport=parent;Root=AppTheme.Panel(parent,"Fixed visual legend",new Vector2(0,1),new Vector2(0,1));Root.pivot=new Vector2(0,1);Root.anchoredPosition=new Vector2(12,-12);Root.GetComponent<Image>().color=new Color(.015f,.035f,.055f,.82f);Root.gameObject.SetActive(false);}
  public void Present(GuidanceDisplay profile){
   bool valid=profile?.schema_version=="manual2ar-guidance-display-v1"&&profile.legend!=null;
   Root.gameObject.SetActive(valid);if(!valid||action==profile.action_id)return;action=profile.action_id;
   foreach(Transform child in Root){child.gameObject.SetActive(false);Object.Destroy(child.gameObject);}
   Root.sizeDelta=new Vector2(310,profile.legend.Length*58+12);
   for(int i=0;i<profile.legend.Length;i++){
    var item=profile.legend[i];var row=AppTheme.Rect(Root,"Legend "+item.id,new Vector2(0,1),new Vector2(1,1));row.pivot=new Vector2(0,1);row.anchoredPosition=new Vector2(0,-6-i*58);row.sizeDelta=new Vector2(0,58);
    var icon=AppTheme.Rect(row,"Model thumbnail",new Vector2(.025f,.05f),new Vector2(.23f,.95f)).gameObject.AddComponent<VisualLegendIcon>();icon.Item=item;icon.raycastTarget=false;
    AppTheme.Label(row,item.label,new Vector2(.28f,.05f),new Vector2(.98f,.95f),25,VisualTextContent.LegendColor(item));
   }
   foreach(var g in Root.GetComponentsInChildren<Graphic>())g.raycastTarget=false;
  }
 }
}
