using System;
using UnityEngine;

namespace Manual2AR.VisualGuidance {
 [Serializable] public class AssetLibraryDescriptor {public string library_id,version,catalog_sha256;}
 [Serializable] public class VisualCatalog {public string schema_version,library_id,version,style_id,coordinate_convention;public AssetDefinition[] assets;public PresentationDefinition[] presentations;}
 [Serializable] public class AssetDefinition {public string id,version,label,category,units,geometry_accuracy;public float nominal_axis_m;public MeshReference mesh;public AssetClip[] clips;}
 [Serializable] public class MeshReference {public string path,sha256;public int vertices,triangles;}
 [Serializable] public class AssetClip {public string id;public AssetTrack[] tracks;}
 [Serializable] public class AssetTrack {public string kind,target="*",easing="linear";public float[] axis=new float[]{0,1,0},pivot_m=new float[]{0,0,0};public float degrees,start,end=1,from_value=1,to_value=1;}
 [Serializable] public class PresentationDefinition {public string id,label;public float duration_seconds;public PresentationLayer[] layers;}
 [Serializable] public class PresentationLayer {public string id,asset_id,clip_id;public bool reverse_with_rotation;}
 [Serializable] public class AssetMesh {public string schema_version,asset_id;public MeshPart[] parts;}
 [Serializable] public class MeshPart {public string id;public float[] vertices,color;public int[] triangles;}
 [Serializable] public class LegendItem {public string id,label,kind,asset_id,component_id;public float[] color;public string[] terms;}
 [Serializable] public class ImperativeInstruction {public string adverbial,actor_mode,actor,action,@object,acceptance,anchor,sentence;public float[] position_m;}
 [Serializable] public class GuidanceDisplay {public string schema_version,action_id,source;public LegendItem[] legend;public ImperativeInstruction instruction;}
 [Serializable] public class VisualTextLabel {public string id,text,brief,source,reference_space_id,kind,state;public float[] position_m;public LegendItem[] color_legend;}
 [Serializable] public class VisualPresentation {public string schema_version,library_id,library_version,catalog_sha256,presentation_id,reference_space_id;public bool illustrative_only;public float duration_seconds;public VisualInstance[] instances;}
 [Serializable] public class VisualInstance {public string id,asset_id,asset_version,mesh_sha256,clip_id;public float[] reference_from_asset,path_m;public float opacity=1,rotation_scale=1,speed=1;public bool visible=true,playing=true,reverse_with_rotation;public int rotation_sign=1;}
 /// <summary>Renderer input is separate from task state and capture SDK. Metres, RH asset/reference space.</summary>
 public sealed class VisualRenderFrame {
  public string ReferenceSpaceId,SourceSha256;public int FrameId,Width,Height;
  public float[] CameraFromReference,Intrinsics,Distortion;
  // Native adapter supplies a Unity transform for the reflected (x,y,-z) reference space.
  public bool HasWorldPlacement;public Matrix4x4 UnityWorldFromReference=Matrix4x4.identity;
 }
 public interface IVisualGuidanceRenderer {
  void Present(VisualPresentation presentation,VisualRenderFrame frame,float cyclePosition);
  void Clear();
 }
}
