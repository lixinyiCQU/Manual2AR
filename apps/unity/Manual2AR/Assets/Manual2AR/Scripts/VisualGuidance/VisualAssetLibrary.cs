using System;
using System.Collections.Generic;
using System.Security.Cryptography;
using UnityEngine;

namespace Manual2AR.VisualGuidance {
 /// <summary>Immutable, hash-checked assets packaged by the backend sync command. No network or AR SDK.</summary>
 public static class VisualAssetLibrary {
  public sealed class Model {public AssetDefinition Definition;public AssetMesh Mesh;public Vector3[][] Vertices;}
  public const string TeachingId="manual2ar.teaching",UnboxingId="manual2ar.unboxing";
  sealed class Pack {
   public string Id,Folder,Digest,Error;public bool Attempted;
   public VisualCatalog Catalog;
   public readonly Dictionary<string,Model> Models=new Dictionary<string,Model>();
   public readonly Dictionary<string,PresentationDefinition> Scenes=new Dictionary<string,PresentationDefinition>();
   public Pack(string id,string folder){Id=id;Folder=folder;}
  }
  static Pack teaching=new Pack(TeachingId,"VisualGuidance"),unboxing=new Pack(UnboxingId,"UnboxingVisualGuidance");
  static Pack Select(string id){return id==TeachingId?teaching:id==UnboxingId?unboxing:null;}
  public static string CatalogSha256 {get{Ensure(teaching);return teaching.Digest;}}
  public static string Error {get{Ensure(teaching);return teaching.Error;}}
  [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.SubsystemRegistration)] static void Reset(){
   teaching=new Pack(TeachingId,"VisualGuidance");unboxing=new Pack(UnboxingId,"UnboxingVisualGuidance");
  }
  static string Hash(byte[] bytes){using(var sha=SHA256.Create())return BitConverter.ToString(sha.ComputeHash(bytes)).Replace("-","").ToLowerInvariant();}
  static bool Finite(float value){return !float.IsNaN(value)&&!float.IsInfinity(value);}
  static void Ensure(Pack pack){
   if(pack.Attempted)return;pack.Attempted=true;
   var models=pack.Models;var scenes=pack.Scenes;
   try{
    var raw=Resources.Load<TextAsset>(pack.Folder+"/catalog");if(raw==null)throw new InvalidOperationException("未安装教学资产，请重新同步前端");
    pack.Digest=Hash(raw.bytes);var catalog=JsonUtility.FromJson<VisualCatalog>(raw.text);
    if(catalog.library_id!=pack.Id||catalog.schema_version!="manual2ar-visual-library-v1"||catalog.coordinate_convention!="right_handed_xyz_metres_functional_origin_positive_y"||catalog.assets==null||catalog.presentations==null)throw new InvalidOperationException("教学资产版本不兼容");
    foreach(var a in catalog.assets){
     if(a.mesh==null||a.units!="metres"||a.nominal_axis_m<=0||!a.mesh.path.StartsWith("meshes/")||a.mesh.path.Contains("..")||!a.mesh.path.EndsWith(".json"))throw new InvalidOperationException("教学资产路径或单位无效");
     var text=Resources.Load<TextAsset>(pack.Folder+"/"+a.mesh.path.Substring(0,a.mesh.path.Length-5));
     if(text==null||Hash(text.bytes)!=a.mesh.sha256)throw new InvalidOperationException("教学模型缺失或校验失败");
     var mesh=JsonUtility.FromJson<AssetMesh>(text.text);if(mesh.asset_id!=a.id||mesh.schema_version!="manual2ar-asset-mesh-v1"||mesh.parts==null)throw new InvalidOperationException("教学模型身份不匹配");
     var vectors=new Vector3[mesh.parts.Length][];int vertexCount=0,triangleCount=0;
     for(int part=0;part<mesh.parts.Length;part++){
      var p=mesh.parts[part];if(p.vertices==null||p.vertices.Length%3!=0||p.triangles==null||p.triangles.Length%3!=0||p.color==null||p.color.Length!=4)throw new InvalidOperationException("教学网格无效");
      vectors[part]=new Vector3[p.vertices.Length/3];
      for(int i=0;i<p.vertices.Length;i++)if(!Finite(p.vertices[i])||Math.Abs(p.vertices[i])>1)throw new InvalidOperationException("教学模型尺度无效");
      for(int i=0;i<vectors[part].Length;i++)vectors[part][i]=new Vector3(p.vertices[i*3],p.vertices[i*3+1],p.vertices[i*3+2]);
      foreach(int index in p.triangles)if(index<0||index>=vectors[part].Length)throw new InvalidOperationException("教学网格索引无效");
      vertexCount+=vectors[part].Length;triangleCount+=p.triangles.Length/3;
     }
     if(vertexCount!=a.mesh.vertices||triangleCount!=a.mesh.triangles||triangleCount>2400)throw new InvalidOperationException("教学模型超出显示预算");
     models.Add(a.id,new Model{Definition=a,Mesh=mesh,Vertices=vectors});
    }
    foreach(var scene in catalog.presentations){foreach(var layer in scene.layers)if(!models.ContainsKey(layer.asset_id)||Array.Find(models[layer.asset_id].Definition.clips,c=>c.id==layer.clip_id)==null)throw new InvalidOperationException("教学动作引用无效");scenes.Add(scene.id,scene);}
    pack.Catalog=catalog;
   }catch(Exception e){models.Clear();scenes.Clear();pack.Catalog=null;pack.Error=e is InvalidOperationException?e.Message:"教学资产读取失败，请更新前端";}
  }
  public static bool Matches(AssetLibraryDescriptor expected,string libraryId=TeachingId){
   var pack=Select(libraryId);if(expected==null||pack==null||expected.library_id!=libraryId)return false;Ensure(pack);
   return pack.Catalog!=null&&expected.catalog_sha256==pack.Digest&&expected.version==pack.Catalog.version;
  }
  public static Model Get(string id,string libraryId=TeachingId){
   var pack=Select(libraryId);if(id==null||pack==null)return null;Ensure(pack);
   return pack.Models.TryGetValue(id,out var model)?model:null;
  }
  public static bool Validate(VisualPresentation p){
   var pack=Select(p?.library_id);if(pack==null)return false;Ensure(pack);
   if(pack.Catalog==null||p.schema_version!="manual2ar-visual-presentation-v1"||!p.illustrative_only||string.IsNullOrEmpty(p.reference_space_id)||p.reference_space_id.Length>100||p.catalog_sha256!=pack.Digest||p.library_version!=pack.Catalog.version||p.instances==null||!pack.Scenes.TryGetValue(p.presentation_id??"",out var spec)||p.instances.Length!=spec.layers.Length)return false;
   var ids=new HashSet<string>();
   for(int n=0;n<p.instances.Length;n++){
    var i=p.instances[n];
    if(i==null||!ids.Add(i.id))return false;var model=Get(i.asset_id,p.library_id);var layer=Array.Find(spec.layers,l=>l.id==i.id);
    if(!Finite(i.speed)||i.speed<.25f||i.speed>4)return false;
    if(!Finite(i.rotation_scale)||i.rotation_scale<0||i.rotation_scale>1||(i.rotation_sign!=1&&i.rotation_sign!=-1))return false;
    if(model==null||layer==null||i.reverse_with_rotation!=layer.reverse_with_rotation||spec.layers[n].id!=i.id||layer.asset_id!=i.asset_id||layer.clip_id!=i.clip_id||i.asset_version!=model.Definition.version||i.mesh_sha256!=model.Definition.mesh.sha256||i.reference_from_asset==null||i.reference_from_asset.Length!=16||i.path_m==null||i.path_m.Length!=3||!Finite(i.opacity)||i.opacity<=0||i.opacity>1)return false;
    foreach(float f in i.reference_from_asset)if(!Finite(f))return false;foreach(float f in i.path_m)if(!Finite(f))return false;
    var m=Matrix(i.reference_from_asset);var x=m.GetColumn(0);var y=m.GetColumn(1);var z=m.GetColumn(2);float scale=new Vector3(x.x,x.y,x.z).magnitude;
    if(scale<1e-5f||scale>100||Math.Abs(y.magnitude-scale)>1e-4||Math.Abs(z.magnitude-scale)>1e-4||Math.Abs(Vector3.Dot(x,y))+Math.Abs(Vector3.Dot(x,z))+Math.Abs(Vector3.Dot(y,z))>1e-4||VisualAssetLibrary.Vector(i.path_m).magnitude>.4f||m.determinant<=0||Math.Abs(m.m30)+Math.Abs(m.m31)+Math.Abs(m.m32)+Math.Abs(m.m33-1)>1e-5)return false;
   }
   return true;
  }
  public static Matrix4x4 Matrix(float[] values){var m=new Matrix4x4();for(int i=0;i<16;i++)m[i/4,i%4]=values[i];return m;}
  public static Vector3 Vector(float[] v){return new Vector3(v[0],v[1],v[2]);}
 }
}
