using UnityEngine;
using UnityEngine.UI;

namespace Manual2AR {
 /// <summary>Equal-height actions reflow when a module hides unavailable operations.</summary>
 public static class AppActionBar {
  public static void Attach(RectTransform parent,float relativeGap=0){
   if(parent.GetComponent<HorizontalLayoutGroup>()!=null)return;
   var row=parent.gameObject.AddComponent<HorizontalLayoutGroup>();row.spacing=16;row.childAlignment=TextAnchor.MiddleCenter;
   row.childControlWidth=row.childControlHeight=true;row.childForceExpandWidth=true;row.childForceExpandHeight=false;
   if(relativeGap>0){var spacing=parent.gameObject.AddComponent<AppActionBarGap>();spacing.Fraction=relativeGap;spacing.Refresh();}
  }
  public static void Add(RectTransform parent,Button button){
   button.transform.SetParent(parent,false);var size=button.GetComponent<LayoutElement>();if(size==null)size=button.gameObject.AddComponent<LayoutElement>();
   size.minWidth=0;size.preferredWidth=1;size.flexibleWidth=1;size.minHeight=size.preferredHeight=AppTheme.ButtonHeight;
  }
 }
 public sealed class AppActionBarGap:MonoBehaviour {
  public float Fraction;
  public void Refresh(){var row=GetComponent<HorizontalLayoutGroup>();if(row!=null)row.spacing=((RectTransform)transform).rect.width*Fraction;}
  void OnRectTransformDimensionsChange(){Refresh();}
 }
}
