using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Rendering;

namespace Manual2AR.VisualGuidance {
 /// <summary>SDK-independent native/world renderer. Caller supplies an explicitly registered reference transform.
 /// It does not initialize ARKit, estimate depth, or register a marker to an AR world.</summary>
 public sealed class VisualWorldRenderer:MonoBehaviour,IVisualGuidanceRenderer {
  readonly VisualSceneSampler sampler=new VisualSceneSampler();readonly List<GameObject> objects=new List<GameObject>();readonly List<Mesh> meshes=new List<Mesh>();readonly List<Material> materials=new List<Material>();
  string sceneId;
  public int ActiveParts {get;private set;}
  public void Present(VisualPresentation p,VisualRenderFrame frame,float phase){
   if(frame==null||!frame.HasWorldPlacement||frame.ReferenceSpaceId!=p?.reference_space_id||!VisualAssetLibrary.Validate(p)){Clear();return;}
   var parts=sampler.Sample(p,phase);
   if(sceneId!=p.presentation_id){Clear();sceneId=p.presentation_id;}
   while(objects.Count<parts.Count){
    var go=new GameObject("Teaching asset part");go.transform.SetParent(transform,false);var mesh=new Mesh();go.AddComponent<MeshFilter>().sharedMesh=mesh;
    var shader=Shader.Find("Sprites/Default");var material=new Material(shader);go.AddComponent<MeshRenderer>().sharedMaterial=material;
    objects.Add(go);meshes.Add(mesh);materials.Add(material);
   }
   for(int n=0;n<parts.Count;n++){
    var part=parts[n];var vertices=new Vector3[part.Vertices.Length];for(int i=0;i<vertices.Length;i++)vertices[i]=transform.InverseTransformPoint(frame.UnityWorldFromReference.MultiplyPoint3x4(new Vector3(part.Vertices[i].x,part.Vertices[i].y,-part.Vertices[i].z)));
    // Reflecting one axis reverses winding. Both adapters sample the same RH animation.
    var indices=(int[])part.Triangles.Clone();for(int i=0;i<indices.Length;i+=3){int swap=indices[i];indices[i]=indices[i+2];indices[i+2]=swap;}
    meshes[n].Clear();meshes[n].vertices=vertices;meshes[n].triangles=indices;meshes[n].RecalculateNormals();meshes[n].RecalculateBounds();materials[n].color=part.Color;objects[n].SetActive(true);
   }
   ActiveParts=parts.Count;
  }
  public void Clear(){foreach(var o in objects)if(o!=null)Destroy(o);foreach(var m in meshes)if(m!=null)Destroy(m);foreach(var m in materials)if(m!=null)Destroy(m);objects.Clear();meshes.Clear();materials.Clear();sceneId=null;ActiveParts=0;}
  void OnDisable(){Clear();}
 }
}
