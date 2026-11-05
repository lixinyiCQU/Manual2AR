using UnityEngine;
using UnityEngine.UI;

namespace Manual2AR.Spatial {
 /// <summary>Read-only enlarged view. The controller retains ownership of the source texture.</summary>
 public sealed class SpatialReferenceViewer:MonoBehaviour {
  public static SpatialReferenceViewer Open(Transform parent,Texture texture,string caption){
   SpatialReferenceViewer viewer=null;
   var dialog=AppDialog.Open(parent,"Enlarged spatial reference",caption,AppDialogSize.Large,()=>viewer.Close());var shade=(RectTransform)dialog.transform;
   viewer=shade.gameObject.AddComponent<SpatialReferenceViewer>();var panel=dialog.Panel;
   var area=AppTheme.Rect(panel,"Photo area",new Vector2(.025f,.04f),new Vector2(.975f,.90f));area.gameObject.AddComponent<RectMask2D>();
   var photo=AppTheme.Rect(area,"Full reference photo",Vector2.zero,Vector2.one).gameObject.AddComponent<RawImage>();photo.texture=texture;photo.raycastTarget=false;
   var fit=photo.gameObject.AddComponent<AspectRatioFitter>();fit.aspectMode=AspectRatioFitter.AspectMode.FitInParent;fit.aspectRatio=texture.width/(float)texture.height;
   shade.SetAsLastSibling();return viewer;
  }
  public void Close(){gameObject.SetActive(false);Destroy(gameObject);}
 }
 public sealed partial class SpatialGuidanceController {
  void EnlargeReference(){if(referenceTexture==null)return;CloseReference();referenceViewer=SpatialReferenceViewer.Open(root,referenceTexture,"官方参考图 · "+(referenceIndex+1)+" / "+Current.reference_images.Length);}
  void CloseReference(){if(referenceViewer!=null)referenceViewer.Close();referenceViewer=null;}
 }
}
