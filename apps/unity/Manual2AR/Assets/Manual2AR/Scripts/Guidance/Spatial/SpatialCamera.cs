using System;
using System.Collections;
using UnityEngine;
namespace Manual2AR.Spatial {
 /// <summary>One camera owner; fixed upright 4:3 capture is also the calibrated image domain.</summary>
 public sealed class SpatialCamera:MonoBehaviour,ISpatialFrameSource {
  WebCamTexture webcam;CameraFraming framing;Texture2D capture;float lastFrameAt=float.NegativeInfinity;int generation;public int AspectIndex {get;private set;}=4;
  public void SetAspect(int value){if(value<0||value>=CameraFraming.Ratios.Length)throw new ArgumentOutOfRangeException();AspectIndex=value;if(framing!=null)framing.SetAspect(value);}
  bool HardwareReady {get{return webcam!=null&&webcam.isPlaying&&webcam.width>16&&webcam.height>16;}}
  public bool Ready {get{return HardwareReady&&framing!=null;}}
  public string ProviderId {get{return "desktop_rgb";}}
  public int CaptureWidth {get{return capture==null?0:capture.width;}}
  public int CaptureHeight {get{return capture==null?0:capture.height;}}
  public string Signature {get{return !Ready?"":webcam.deviceName+"|"+webcam.width+"x"+webcam.height+"|"+webcam.videoRotationAngle+"|"+webcam.videoVerticallyMirrored+"|upright-"+CameraFraming.Ratios[AspectIndex]+"-960-v1";}}
  public IEnumerator Open(int selected,Action<string> error){
   Close();int opening=generation;if(!Application.HasUserAuthorization(UserAuthorization.WebCam))yield return Application.RequestUserAuthorization(UserAuthorization.WebCam);
   if(opening!=generation)yield break;
   var devices=WebCamTexture.devices;
   if(devices.Length==0||!Application.HasUserAuthorization(UserAuthorization.WebCam)){error("摄像头不可用，请检查 Windows 相机权限和占用。");yield break;}
   bool started=false;try{webcam=new WebCamTexture(devices[Mathf.Max(0,selected)%devices.Length].name,960,720,15);webcam.Play();started=true;}
   catch(Exception){Close();}
   if(!started){error("摄像头启动失败，请检查连接和相机占用。");yield break;}
   float deadline=Time.realtimeSinceStartup+10;while(opening==generation&&!HardwareReady&&Time.realtimeSinceStartup<deadline)yield return null;
   if(opening!=generation)yield break;
   if(!HardwareReady){Close();error("未收到摄像头画面，请关闭占用相机的其他软件。");yield break;}
   framing=gameObject.AddComponent<CameraFraming>();framing.SetAspect(AspectIndex);
  }
  void Update(){if(HardwareReady&&webcam.didUpdateThisFrame)lastFrameAt=Time.realtimeSinceStartup;}
  public byte[] Capture(){if(!Ready||Time.realtimeSinceStartup-lastFrameAt>.5f)return null;capture=framing.Capture(webcam,webcam.videoRotationAngle,webcam.videoVerticallyMirrored,960,capture);return capture.EncodeToJPG(92);}
  public void Close(){generation++;lastFrameAt=float.NegativeInfinity;if(webcam!=null){webcam.Stop();Destroy(webcam);webcam=null;}if(framing!=null){Destroy(framing);framing=null;}if(capture!=null){Destroy(capture);capture=null;}}
  void OnDestroy(){Close();}
 }
}
