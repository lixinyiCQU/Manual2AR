using System;
using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UI;
namespace Manual2AR {
 /// <summary>One blurred in-app snapshot per popup. Owns its blocker and releases it with the dialog.</summary>
 public sealed class AppModalBackdrop:MonoBehaviour {
  GameObject shade;Canvas shadeCanvas;RawImage preview;Texture2D snapshot;int order;
  public bool Ready {get{return snapshot!=null;}}
  public static AppModalBackdrop Attach(GameObject dialog){
   var existing=dialog.GetComponent<AppModalBackdrop>();if(existing!=null)return existing;
   int level=610;foreach(var other in FindObjectsOfType<AppModalBackdrop>())if(other.gameObject.activeInHierarchy)level=Mathf.Max(level,other.order+10);
   var result=dialog.AddComponent<AppModalBackdrop>();result.order=level;
   var canvas=dialog.GetComponent<Canvas>();if(canvas==null)canvas=dialog.AddComponent<Canvas>();canvas.overrideSorting=true;canvas.sortingOrder=level;
   if(dialog.GetComponent<GraphicRaycaster>()==null)dialog.AddComponent<GraphicRaycaster>();
   var rect=(RectTransform)dialog.transform;var image=dialog.GetComponent<Image>();
   if(image!=null&&rect.anchorMin==Vector2.zero&&rect.anchorMax==Vector2.one)image.color=Color.clear;
   var shade=AppTheme.Rect(dialog.transform.parent,"Modal focus backdrop",Vector2.zero,Vector2.one);result.shade=shade.gameObject;
   shade.SetSiblingIndex(dialog.transform.GetSiblingIndex());result.shadeCanvas=shade.gameObject.AddComponent<Canvas>();result.shadeCanvas.overrideSorting=true;result.shadeCanvas.sortingOrder=level-1;shade.gameObject.AddComponent<GraphicRaycaster>();
   result.preview=shade.gameObject.AddComponent<RawImage>();result.preview.color=Color.clear;result.preview.raycastTarget=true;
   var dim=AppTheme.Rect(shade,"Dim background",Vector2.zero,Vector2.one).gameObject.AddComponent<Image>();dim.color=new Color(0,.015f,.025f,.62f);dim.raycastTarget=true;
   if(dialog.activeInHierarchy)result.StartCoroutine(result.Recapture());return result;
  }
  IEnumerator Recapture(){yield return null;Capture();}
  void Capture(){
   if(shade==null||!gameObject.activeInHierarchy)return;var camera=Camera.main;if(camera==null)return;
   var own=GetComponentsInChildren<Canvas>();var enabled=new bool[own.Length];for(int i=0;i<own.Length;i++){enabled[i]=own[i].enabled;own[i].enabled=false;}shadeCanvas.enabled=false;
   var overlays=new List<Canvas>();var cameras=new List<Camera>();var distances=new List<float>();
   foreach(var canvas in FindObjectsOfType<Canvas>())if(canvas.renderMode==RenderMode.ScreenSpaceOverlay){overlays.Add(canvas);cameras.Add(canvas.worldCamera);distances.Add(canvas.planeDistance);canvas.renderMode=RenderMode.ScreenSpaceCamera;canvas.worldCamera=camera;canvas.planeDistance=1;}
   var previous=RenderTexture.active;var target=camera.targetTexture;var full=RenderTexture.GetTemporary(Mathf.Max(320,Screen.width),Mathf.Max(180,Screen.height),24);var small=RenderTexture.GetTemporary(320,180,0);
   try{
    camera.targetTexture=full;Canvas.ForceUpdateCanvases();camera.Render();Graphics.Blit(full,small);RenderTexture.active=small;
    if(snapshot!=null)Destroy(snapshot);snapshot=new Texture2D(320,180,TextureFormat.RGB24,false);snapshot.ReadPixels(new Rect(0,0,320,180),0,0);snapshot.Apply();
    var pixels=snapshot.GetPixels32();pixels=Blur(Blur(pixels,320,180,true),320,180,false);snapshot.SetPixels32(pixels);snapshot.Apply();snapshot.filterMode=FilterMode.Bilinear;preview.texture=snapshot;preview.color=Color.white;
   }finally{
    camera.targetTexture=target;RenderTexture.active=previous;RenderTexture.ReleaseTemporary(full);RenderTexture.ReleaseTemporary(small);
    for(int i=0;i<overlays.Count;i++)if(overlays[i]!=null){overlays[i].renderMode=RenderMode.ScreenSpaceOverlay;overlays[i].worldCamera=cameras[i];overlays[i].planeDistance=distances[i];}
    for(int i=0;i<own.Length;i++)if(own[i]!=null)own[i].enabled=enabled[i];if(shadeCanvas!=null)shadeCanvas.enabled=true;Canvas.ForceUpdateCanvases();
   }
  }
  static Color32[] Blur(Color32[] source,int width,int height,bool horizontal){
   var output=new Color32[source.Length];
   for(int y=0;y<height;y++)for(int x=0;x<width;x++){int r=0,g=0,b=0;for(int k=-4;k<=4;k++){var p=source[Mathf.Clamp(y+(horizontal?0:k),0,height-1)*width+Mathf.Clamp(x+(horizontal?k:0),0,width-1)];r+=p.r;g+=p.g;b+=p.b;}output[y*width+x]=new Color32((byte)(r/9),(byte)(g/9),(byte)(b/9),255);}
   return output;
  }
  void OnEnable(){if(shade!=null){shade.SetActive(true);StartCoroutine(Recapture());}}
  void OnDisable(){if(shade!=null)shade.SetActive(false);}
  void OnDestroy(){if(shade!=null)Destroy(shade);if(snapshot!=null)Destroy(snapshot);}
 }
}
