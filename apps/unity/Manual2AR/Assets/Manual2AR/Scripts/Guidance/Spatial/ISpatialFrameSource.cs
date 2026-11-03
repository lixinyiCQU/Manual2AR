using System;
using System.Collections;
namespace Manual2AR.Spatial {
 /// <summary>Capture boundary for desktop and future native AR adapters.
 /// Capture returns upright, unmirrored JPEG pixels. A native adapter must freeze
 /// intrinsics/pose with that RGB frame and use a separate placement provider.
 /// No native AR implementation or SDK dependency is implied by this interface.</summary>
 public interface ISpatialFrameSource {
  bool Ready {get;}
  string Signature {get;}
  string ProviderId {get;}
  int CaptureWidth {get;}
  int CaptureHeight {get;}
  IEnumerator Open(int selected,Action<string> error);
  byte[] Capture();
  void Close();
 }
}
