using UnityEngine;
using UnityEngine.UI;

namespace Manual2AR.Spatial {
 [RequireComponent(typeof(CanvasRenderer))]
 public sealed class SpatialAxesGraphic:MaskableGraphic {
  public Axis[] axes;public int width=960,height=720;readonly Text[] labels=new Text[4];
  protected override void Awake(){base.Awake();for(int i=0;i<4;i++){labels[i]=AppTheme.Label(transform,"XYZO"[i].ToString(),Vector2.zero,Vector2.zero,19);labels[i].raycastTarget=false;labels[i].rectTransform.sizeDelta=new Vector2(26,26);labels[i].alignment=TextAnchor.MiddleCenter;labels[i].color=i==3?Color.white:ColorFor(i);labels[i].gameObject.SetActive(false);}}
  static Color ColorFor(int n){return n==0?new Color(1,.28f,.24f):n==1?new Color(.3f,1,.4f):new Color(.3f,.6f,1);}
  Vector2 Point(Pixel p){var r=rectTransform.rect;return new Vector2(r.xMin+p.x/width*r.width,r.yMax-p.y/height*r.height);}
  public void Clear(){axes=null;SetVerticesDirty();foreach(var label in labels)if(label!=null)label.gameObject.SetActive(false);}
  void LateUpdate(){for(int i=0;i<4;i++){bool show=axes!=null&&axes.Length>0&&(i==3||i<axes.Length);labels[i].gameObject.SetActive(show);if(show)labels[i].rectTransform.anchoredPosition=Point(i==3?axes[0].a:axes[i].b)+(i==3?new Vector2(-12,-12):new Vector2(10,10));}}
  void Line(VertexHelper helper,Vector2 a,Vector2 b,Color color,float thickness){Vector2 normal=new Vector2(-(b-a).y,(b-a).x).normalized*thickness/2;int n=helper.currentVertCount;helper.AddVert(a-normal,color,Vector2.zero);helper.AddVert(a+normal,color,Vector2.zero);helper.AddVert(b+normal,color,Vector2.zero);helper.AddVert(b-normal,color,Vector2.zero);helper.AddTriangle(n,n+1,n+2);helper.AddTriangle(n,n+2,n+3);}
  protected override void OnPopulateMesh(VertexHelper helper){helper.Clear();if(axes==null)return;for(int i=0;i<axes.Length;i++){var a=Point(axes[i].a);var b=Point(axes[i].b);var direction=(b-a).normalized;var side=new Vector2(-direction.y,direction.x);Line(helper,a,b,ColorFor(i),3);Line(helper,b,b-direction*9+side*5,ColorFor(i),3);Line(helper,b,b-direction*9-side*5,ColorFor(i),3);}}
 }
}
