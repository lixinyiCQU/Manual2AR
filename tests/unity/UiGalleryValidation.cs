using System;
using System.Collections;
using System.IO;
using Manual2AR;
using UnityEngine;
using UnityEngine.UI;

// Editor-only component preview. It never opens a physical camera or calls a model.
public static class UiGalleryValidation {
 static void Check(bool condition,string reason){if(!condition)throw new Exception("UI contract: "+reason);}
 static Rect Bounds(RectTransform rect){var corners=new Vector3[4];rect.GetWorldCorners(corners);return Rect.MinMaxRect(corners[0].x,corners[0].y,corners[2].x,corners[2].y);}
 public static IEnumerator Run(string folder){
  foreach(var size in new[]{new Vector2Int(1280,720),new Vector2Int(1920,1080),new Vector2Int(1600,1000)})foreach(AppWorkspaceKind kind in Enum.GetValues(typeof(AppWorkspaceKind))){
   var root=AppWorkspace.Canvas(null,"Internal component preview");root.GetComponent<Canvas>().renderMode=RenderMode.WorldSpace;root.sizeDelta=size;root.localScale=Vector3.one;root.position=Vector3.zero;root.rotation=Quaternion.identity;
   var view=new AppWorkspace(root,"模块二 · 教学工作区",kind);
   var camera=new GameObject("Preview rendering camera").AddComponent<Camera>();camera.orthographic=true;camera.orthographicSize=size.y*.5f;camera.transform.position=new Vector3(0,0,-1000);camera.cullingMask=1<<31;camera.clearFlags=CameraClearFlags.SolidColor;camera.backgroundColor=AppTheme.Background;
   root.GetComponent<Canvas>().worldCamera=camera;
   var back=AppTheme.Button(root,"返回任务列表",AppWorkspace.BackMin,AppWorkspace.BackMax,()=>{},AppIcon.Back);
   var overview=AppTheme.Button(view.HeaderActions,"步骤总览",Vector2.zero,Vector2.one,()=>{},AppIcon.Info);AppActionBar.Add(view.HeaderActions,overview);
   var start=AppTheme.Button(view.Tools,"启动摄像头",new Vector2(0,.08f),new Vector2(.23f,.92f),()=>{},AppIcon.Camera);
   var capture=AppTheme.Button(view.Tools,"切换摄像头",new Vector2(.25f,.08f),new Vector2(.48f,.92f),()=>{},AppIcon.SwitchCamera);
   AppTheme.Label(view.Tools,"画幅  1:1   16:9   9:16   3:4   4:3",new Vector2(.51f,0),Vector2.one,AppTheme.CaptionSize,AppTheme.Muted);
   var content=AppContent.Scroll(view.Main,"Guidance content",new Vector2(.025f,.025f),new Vector2(.975f,.97f));
   AppContent.Paragraph(content,kind==AppWorkspaceKind.Reading?"操作指导":"当前相机画面",AppTheme.TitleSize,AppTheme.TargetCyan);
   AppContent.Paragraph(content,"将 A1 mini 的料盘支架对准底座导槽，从上向下滑入，直至滑到底部。\n\n请使用两颗 M3-8 螺丝固定底座；工具与动作示意仅供教学。");
   AppContent.Paragraph(content,new string('长',160)+"。",AppTheme.BodySize);
   AppTheme.Label(view.Aside,"辅助信息",new Vector2(.06f,.86f),new Vector2(.94f,.97f),AppTheme.BodySize,AppTheme.TargetCyan);
   var feedback=AppContent.Scroll(view.Aside,"Feedback",new Vector2(.04f,.04f),new Vector2(.96f,.84f));
   AppContent.Paragraph(feedback,"需要调整后重新检查",AppTheme.BodySize,AppTheme.ErrorRed);
   AppContent.Paragraph(feedback,"支架仍单独放在桌面。\n\n让安装位置清晰入镜，然后重新检查。\n\n识别完成与安装核验通过是不同状态。",AppTheme.BodySize);
   var left=AppTheme.Button(view.FooterLeft,"进入AR指导",Vector2.zero,Vector2.one,()=>{},AppIcon.Inspect);AppActionBar.Add(view.FooterLeft,left);
   var previous=AppTheme.Button(view.FooterRight,"上一步",Vector2.zero,Vector2.one,()=>{},AppIcon.Back);AppActionBar.Add(view.FooterRight,previous);
   var done=AppTheme.Button(view.FooterRight,"已完成本章",Vector2.zero,Vector2.one,()=>{},AppIcon.Check);AppActionBar.Add(view.FooterRight,done);
   var next=AppTheme.Button(view.FooterRight,"下一步",Vector2.zero,Vector2.one,()=>{},null,true);AppActionBar.Add(view.FooterRight,next);
   foreach(Transform child in root.GetComponentsInChildren<Transform>(true))child.gameObject.layer=31;
   yield return null;Canvas.ForceUpdateCanvases();
   foreach(var text in root.GetComponentsInChildren<AppReadableText>())text.Reflow(true);
   Canvas.ForceUpdateCanvases();
   Check(view.Title.preferredHeight<=view.Title.rectTransform.rect.height+1,"page title clipped");
   Check(!Bounds(view.Main).Overlaps(Bounds(view.Aside)),"main overlaps context");
   Check(!Bounds(view.Tools).Overlaps(Bounds(view.Main)),"toolbar overlays media");
   Check(Mathf.Abs(previous.GetComponent<RectTransform>().rect.width-done.GetComponent<RectTransform>().rect.width)<1,"unequal footer buttons");
   foreach(var button in root.GetComponentsInChildren<Button>()){
    var bounds=Bounds((RectTransform)button.transform);
    Check(bounds.xMin>=-size.x*.5f-1&&bounds.xMax<=size.x*.5f+1&&bounds.yMin>=-size.y*.5f-1&&bounds.yMax<=size.y*.5f+1,"action outside the window: "+button.name+" "+bounds+" at "+size);
    Check(bounds.height>=40,"button is too short");
   }
   var label=next.GetComponentInChildren<Text>();label.fontStyle=FontStyle.Bold;AppTheme.Skin(next);Check(label.fontStyle==FontStyle.Bold&&next.GetComponentInChildren<AppIconGraphic>()==null,"styling guesses an icon or changes emphasis");
   Capture(camera,Path.Combine(folder,"ui-"+size.x+"x"+size.y+"-"+kind+".png"),size);
   float originalWidth=next.GetComponent<RectTransform>().rect.width;done.gameObject.SetActive(false);Canvas.ForceUpdateCanvases();Check(next.GetComponent<RectTransform>().rect.width>originalWidth+1,"hidden action left a fixed slot");
   UnityEngine.Object.Destroy(root.gameObject);UnityEngine.Object.Destroy(camera.gameObject);yield return null;
  }
 }
 static void Capture(Camera camera,string path,Vector2Int size){
  var rt=RenderTexture.GetTemporary(size.x,size.y,24);var previous=RenderTexture.active;
  try{camera.targetTexture=rt;camera.Render();RenderTexture.active=rt;var texture=new Texture2D(size.x,size.y,TextureFormat.RGB24,false);texture.ReadPixels(new Rect(0,0,size.x,size.y),0,0);texture.Apply();File.WriteAllBytes(path,texture.EncodeToPNG());UnityEngine.Object.Destroy(texture);}
  finally{camera.targetTexture=null;RenderTexture.active=previous;RenderTexture.ReleaseTemporary(rt);}
 }
}
