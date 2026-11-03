using System;
using System.Collections;
using UnityEngine;
namespace Manual2AR.Spatial {
 /// <summary>One camera owner; fixed upright 4:3 capture is also the calibrated image domain.</summary>
 public sealed class SpatialCamera:MonoBehaviour,ISpatialFrameSource {
  WebCamTexture webcam;CameraFraming framing;Texture2D capture;float lastFrameAt;
  public bool Ready {get{return webcam!=null&&webcam.isPlaying&&webcam.width>16;}}
  public string ProviderId {get{return "desktop_rgb";}}
  public int CaptureWidth {get{return capture==null?0:capture.width;}}
  public int CaptureHeight {get{return capture==null?0:capture.height;}}
  public string Signature {get{return !Ready?"":webcam.deviceName+"|"+webcam.width+"x"+webcam.height+"|"+webcam.videoRotationAngle+"|"+webcam.videoVerticallyMirrored+"|upright-4:3-960-v1";}}
  public IEnumerator Open(int selected,Action<string> error){
   Close();if(!Application.HasUserAuthorization(UserAuthorization.WebCam))yield return Application.RequestUserAuthorization(UserAuthorization.WebCam);
   var devices=WebCamTexture.devices;
   if(devices.Length==0||!Application.HasUserAuthorization(UserAuthorization.WebCam)){error("摄像头不可用，请检查 Windows 相机权限和占用。");yield break;}
   webcam=new WebCamTexture(devices[Mathf.Max(0,selected)%devices.Length].name,960,720,15);webcam.Play();
   float deadline=Time.realtimeSinceStartup+10;while(!Ready&&Time.realtimeSinceStartup<deadline)yield return null;
   if(!Ready){Close();error("未收到摄像头画面，请关闭占用相机的其他软件。");yield break;}
   framing=gameObject.AddComponent<CameraFraming>();framing.SetAspect(4);
  }
  void Update(){if(Ready&&webcam.didUpdateThisFrame)lastFrameAt=Time.realtimeSinceStartup;}
  public byte[] Capture(){if(!Ready||Time.realtimeSinceStartup-lastFrameAt>.5f)return null;capture=framing.Capture(webcam,webcam.videoRotationAngle,webcam.videoVerticallyMirrored,960,capture);return capture.EncodeToJPG(92);}
  public void Close(){if(webcam!=null){webcam.Stop();Destroy(webcam);webcam=null;}if(framing!=null){Destroy(framing);framing=null;}if(capture!=null){Destroy(capture);capture=null;}}
  void OnDestroy(){Close();}
 }
}
