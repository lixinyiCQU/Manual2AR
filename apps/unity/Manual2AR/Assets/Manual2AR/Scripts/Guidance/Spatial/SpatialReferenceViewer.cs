using UnityEngine;
using UnityEngine.UI;

namespace Manual2AR.Spatial {
 /// <summary>Read-only enlarged view. The controller retains ownership of the source texture.</summary>
 public sealed class SpatialReferenceViewer:MonoBehaviour {
  public static SpatialReferenceViewer Open(Transform parent,Texture texture,string caption){
   var shade=AppTheme.Rect(parent,"Enlarged spatial reference",Vector2.zero,Vector2.one);
   var canvas=shade.gameObject.AddComponent<Canvas>();canvas.overrideSorting=true;canvas.sortingOrder=620;shade.gameObject.AddComponent<GraphicRaycaster>();
   var viewer=shade.gameObject.AddComponent<SpatialReferenceViewer>();
   var background=shade.gameObject.AddComponent<Image>();background.color=new Color(0,0,0,.85f);AppModalBackdrop.Attach(shade.gameObject);
   var dismiss=shade.gameObject.AddComponent<Button>();dismiss.targetGraphic=background;dismiss.transition=Selectable.Transition.None;dismiss.onClick.AddListener(viewer.Close);
   var panel=AppTheme.Panel(shade,"Reference photo dialog",new Vector2(.04f,.04f),new Vector2(.96f,.96f));
   AppTheme.Label(panel,caption,new Vector2(.025f,.925f),new Vector2(.72f,.985f),26,AppTheme.TargetCyan);
   var area=AppTheme.Rect(panel,"Photo area",new Vector2(.025f,.04f),new Vector2(.975f,.90f));area.gameObject.AddComponent<RectMask2D>();
   var photo=AppTheme.Rect(area,"Full reference photo",Vector2.zero,Vector2.one).gameObject.AddComponent<RawImage>();photo.texture=texture;photo.raycastTarget=false;
   var fit=photo.gameObject.AddComponent<AspectRatioFitter>();fit.aspectMode=AspectRatioFitter.AspectMode.FitInParent;fit.aspectRatio=texture.width/(float)texture.height;
   AppTheme.Button(panel,"关闭图片",new Vector2(.78f,.925f),new Vector2(.975f,.985f),viewer.Close,AppIcon.Close);
   shade.SetAsLastSibling();return viewer;
  }
  public void Close(){gameObject.SetActive(false);Destroy(gameObject);}
 }
 public sealed partial class SpatialGuidanceController {
  void EnlargeReference(){if(referenceTexture==null)return;CloseReference();referenceViewer=SpatialReferenceViewer.Open(root,referenceTexture,"官方参考图 · "+(referenceIndex+1)+" / "+Current.reference_images.Length);}
  void CloseReference(){if(referenceViewer!=null)referenceViewer.Close();referenceViewer=null;}
 }
}
