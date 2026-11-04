using System;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.EventSystems;
using UnityEngine.UI;
namespace Manual2AR.Spatial {
 /// <summary>Render projected metric geometry on its exact submitted frame, with no pose extrapolation.</summary>
 [RequireComponent(typeof(CanvasRenderer))]
 public sealed class SpatialOverlay:MaskableGraphic,IPointerClickHandler {
  public event Action<Pixel> Selected;
  public int width=960,height=720;public Segment[] lines=new Segment[0];public Pixel[] corners;
  public GuidanceVisual visual;public Pixel leaderEnd;public float progress;
  public Outline[] outlines;
  public readonly List<Pixel> picks=new List<Pixel>();
  public bool accepting;
  public int MaximumPicks=2;
  public void Clear(){lines=new Segment[0];corners=null;visual=null;leaderEnd=null;outlines=null;picks.Clear();SetVerticesDirty();}
  Vector2 Point(Pixel p){var r=rectTransform.rect;return new Vector2(r.xMin+p.x/width*r.width,r.yMax-p.y/height*r.height);}
  void Line(VertexHelper v,Vector2 a,Vector2 b,Color shade,float thickness){
   if((a-b).sqrMagnitude<.01f)return;Vector2 n=b-a;n=new Vector2(-n.y,n.x).normalized*thickness*.5f;int i=v.currentVertCount;
   v.AddVert(a-n,shade,Vector2.zero);v.AddVert(a+n,shade,Vector2.zero);v.AddVert(b+n,shade,Vector2.zero);v.AddVert(b-n,shade,Vector2.zero);v.AddTriangle(i,i+1,i+2);v.AddTriangle(i,i+2,i+3);
  }
  protected override void OnPopulateMesh(VertexHelper v){
   v.Clear();bool hasAsset=SpatialAssetGraphic.HasPlacement(visual);
   if(!hasAsset&&(visual==null||visual.kind!="highlight"))foreach(var line in lines??new Segment[0]){Line(v,Point(line.a),Point(line.b),new Color(0,.12f,.16f,.9f),9);Line(v,Point(line.a),Point(line.b),AppTheme.TargetCyan,4);}
   foreach(var outline in outlines??new Outline[0])if(outline.points!=null&&outline.points.Length>2)for(int i=0;i<outline.points.Length;i++)Line(v,Point(outline.points[i]),Point(outline.points[(i+1)%outline.points.Length]),AppTheme.SuccessGreen,3);
   if(corners!=null&&corners.Length==4)for(int i=0;i<4;i++)Line(v,Point(corners[i]),Point(corners[(i+1)%4]),AppTheme.SuccessGreen,2);
   if(visual!=null&&!accepting){
    Vector2 anchor=Point(visual.anchor);Circle(v,anchor,16,AppTheme.TargetCyan,2);
    if(leaderEnd!=null)Line(v,anchor,Point(leaderEnd),AppTheme.TargetCyan,2);
    bool model=hasAsset;
    if(!model&&visual.kind=="slide"&&visual.trajectory!=null&&visual.trajectory.Length>1){
     float index=Mathf.Clamp01(progress)*(visual.trajectory.Length-1);int i=Mathf.Min((int)index,visual.trajectory.Length-2);
     Vector2 moving=Vector2.Lerp(Point(visual.trajectory[i]),Point(visual.trajectory[i+1]),index-i);
     Vector2 direction=(Point(visual.trajectory[i+1])-Point(visual.trajectory[i])).normalized;
     if(direction.sqrMagnitude>.5f){
      Vector2 side=new Vector2(-direction.y,direction.x);
      // A directional glyph, not a fabricated component model or swept volume.
      Line(v,moving-direction*32,moving,Color.white,5);
      Line(v,moving,moving-direction*17+side*12,AppTheme.TargetCyan,6);
      Line(v,moving,moving-direction*17-side*12,AppTheme.TargetCyan,6);
      Circle(v,Point(visual.trajectory[0]),10,new Color(1,1,1,.8f),2);
      Circle(v,Point(visual.trajectory[visual.trajectory.Length-1]),18,AppTheme.TargetCyan,3);
     }
    }else if(visual.kind=="fasten"||visual.kind=="cut"){
     if(!model)foreach(var segment in visual.tool_lines??new Segment[0])Line(v,Point(segment.a),Point(segment.b),new Color(1,.78f,.35f,.9f),6);
     Circle(v,anchor,21+Mathf.Sin(progress*Mathf.PI*2)*4,new Color(1,.78f,.35f,.85f),2);
    }else if(visual.kind=="highlight"){
     // A position spotlight, never a fabricated segmented outline of the foam.
     float radius=24+Mathf.Sin(progress*Mathf.PI*2)*5;
     Disk(v,anchor,radius,new Color(0,.88f,1,.16f));Circle(v,anchor,radius,AppTheme.TargetCyan,3);
     Circle(v,anchor,radius+8,new Color(0,.88f,1,.35f),2);
    }
   }
   foreach(var p in picks){Vector2 x=Point(p);Line(v,x-Vector2.right*9,x+Vector2.right*9,Color.yellow,3);Line(v,x-Vector2.up*9,x+Vector2.up*9,Color.yellow,3);}
  }
  void Circle(VertexHelper v,Vector2 centre,float radius,Color shade,float thickness){for(int i=0;i<28;i++){float a=i*Mathf.PI*2/28,b=(i+1)*Mathf.PI*2/28;Line(v,centre+new Vector2(Mathf.Cos(a),Mathf.Sin(a))*radius,centre+new Vector2(Mathf.Cos(b),Mathf.Sin(b))*radius,shade,thickness);}}
  void Disk(VertexHelper v,Vector2 centre,float radius,Color shade){for(int i=0;i<28;i++){float a=i*Mathf.PI*2/28,b=(i+1)*Mathf.PI*2/28;int n=v.currentVertCount;v.AddVert(centre,shade,Vector2.zero);v.AddVert(centre+new Vector2(Mathf.Cos(a),Mathf.Sin(a))*radius,shade,Vector2.zero);v.AddVert(centre+new Vector2(Mathf.Cos(b),Mathf.Sin(b))*radius,shade,Vector2.zero);v.AddTriangle(n,n+1,n+2);}}
  public void OnPointerClick(PointerEventData data){
   if(!accepting||picks.Count>=MaximumPicks)return;Vector2 local;if(!RectTransformUtility.ScreenPointToLocalPointInRectangle(rectTransform,data.position,data.pressEventCamera,out local))return;
   var r=rectTransform.rect;if(!r.Contains(local))return;
   var p=new Pixel((local.x-r.xMin)/r.width*width,(r.yMax-local.y)/r.height*height);picks.Add(p);SetVerticesDirty();Selected?.Invoke(p);
  }
 }
}
