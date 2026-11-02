using System;
using UnityEngine;
using UnityEngine.UI;

namespace Manual2AR {
 /// <summary>One upright, centered crop is shared by live preview and uploaded pixels.</summary>
 public sealed class CameraFraming:MonoBehaviour {
  public static readonly string[] Ratios={"1:1","16:9","9:16","3:4","4:3"};
  static readonly Vector2Int[] Parts={new Vector2Int(1,1),new Vector2Int(16,9),new Vector2Int(9,16),new Vector2Int(3,4),new Vector2Int(4,3)};
  public int AspectIndex {get;private set;}
  public RenderTexture Preview {get;private set;}
  Material material;AppAspectSelector selector;
  public static Rect CenterCrop(int width,int height,int rotation,int index){
   if(width<=0||height<=0||index<0||index>=Parts.Length)throw new ArgumentOutOfRangeException();
   bool quarter=((rotation%180)+180)%180==90;float w=quarter?height:width,h=quarter?width:height;
   float source=w/h,target=Parts[index].x/(float)Parts[index].y;
   float cw=source>target?target/source:1,ch=source>target?1:source/target;
   return new Rect((1-cw)*.5f,(1-ch)*.5f,cw,ch);
  }
  public static Vector2Int OutputSize(int width,int height,int rotation,int index,int maxSide){
   var crop=CenterCrop(width,height,rotation,index);bool quarter=((rotation%180)+180)%180==90;
   float w=(quarter?height:width)*crop.width,h=(quarter?width:height)*crop.height;var units=Parts[index];
   int count=Mathf.Max(1,Mathf.FloorToInt(Mathf.Min(Mathf.Min(w/units.x,h/units.y),Mathf.Clamp(maxSide,32,1280)/(float)Mathf.Max(units.x,units.y))+.0001f));
   return new Vector2Int(count*units.x,count*units.y);
  }
  public AppAspectSelector AddSelector(Transform parent,Vector2 min,Vector2 max,Action<int> choose){selector=AppAspectSelector.Create(parent,min,max,choose);selector.Select(AspectIndex);return selector;}
  public void SetAspect(int index){if(index<0||index>=Ratios.Length)throw new ArgumentOutOfRangeException();AspectIndex=index;selector?.Select(index);}
  public RenderTexture Render(Texture source,int rotation,bool mirrored,int maxSide){
   if(source==null)throw new ArgumentNullException(nameof(source));
   var size=OutputSize(source.width,source.height,rotation,AspectIndex,maxSide);
   if(Preview==null||Preview.width!=size.x||Preview.height!=size.y){
    if(Preview!=null){if(RenderTexture.active==Preview)RenderTexture.active=null;Preview.Release();Destroy(Preview);}Preview=new RenderTexture(size.x,size.y,0,RenderTextureFormat.ARGB32);Preview.name="Upright Centered Camera Crop";Preview.filterMode=FilterMode.Bilinear;Preview.Create();
   }
   if(material==null)material=new Material(Resources.Load<Shader>("CameraFrameCapture"));
   var crop=CenterCrop(source.width,source.height,rotation,AspectIndex);
   material.SetVector("_CropRect",new Vector4(crop.x,crop.y,crop.width,crop.height));material.SetFloat("_Rotation",((rotation%360)+360)%360);material.SetFloat("_MirrorY",mirrored?1:0);
   var previous=RenderTexture.active;try{Graphics.Blit(source,Preview,material);}finally{RenderTexture.active=previous;}return Preview;
  }
  public RenderTexture Live(WebCamTexture camera,int maxSide){
   if(camera==null||!camera.isPlaying||camera.width<=16)return null;
   return Render(camera,camera.videoRotationAngle,camera.videoVerticallyMirrored,maxSide);
  }
  public Texture2D Capture(Texture source,int rotation,bool mirrored,int maxSide,Texture2D reuse=null){
   var output=Render(source,rotation,mirrored,maxSide);
   if(reuse==null||reuse.width!=output.width||reuse.height!=output.height){if(reuse!=null)Destroy(reuse);reuse=new Texture2D(output.width,output.height,TextureFormat.RGB24,false);}
   var previous=RenderTexture.active;
   try{RenderTexture.active=output;reuse.ReadPixels(new Rect(0,0,output.width,output.height),0,0,false);reuse.Apply(false);return reuse;}
   finally{RenderTexture.active=previous;}
  }
  void OnDestroy(){if(Preview!=null){if(RenderTexture.active==Preview)RenderTexture.active=null;Preview.Release();Destroy(Preview);}if(material!=null)Destroy(material);}
 }
 public sealed class AppAspectSelector {
  readonly Button[] buttons=new Button[5];
  public RectTransform Root {get;private set;}
  public static AppAspectSelector Create(Transform parent,Vector2 min,Vector2 max,Action<int> choose){
   var selector=new AppAspectSelector();selector.Root=AppTheme.Panel(parent,"画幅比例",min,max);
   AppTheme.Label(selector.Root,"画幅",new Vector2(.015f,.05f),new Vector2(.13f,.95f),23,AppTheme.Muted);
   for(int i=0;i<5;i++){int index=i;float left=.14f+i*.17f;var card=AppTheme.Panel(selector.Root,CameraFraming.Ratios[i],new Vector2(left,.1f),new Vector2(left+.16f,.9f));var b=card.gameObject.AddComponent<Button>();b.targetGraphic=card.GetComponent<Image>();b.onClick.AddListener(()=>choose(index));var text=AppTheme.Label(card,CameraFraming.Ratios[i],Vector2.zero,Vector2.one,23);text.alignment=TextAnchor.MiddleCenter;AppTheme.Skin(b);selector.buttons[i]=b;}
   return selector;
  }
  public void Select(int selected){for(int i=0;i<buttons.Length;i++)buttons[i].GetComponent<Image>().color=i==selected?new Color(.045f,.43f,.56f):AppTheme.ButtonBackground;}
  public void SetInteractable(bool allowed){foreach(var button in buttons)button.interactable=allowed;}
 }
}
