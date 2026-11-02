using UnityEngine;
using UnityEngine.UI;
namespace Manual2AR {
 public enum AppIcon {Camera,SwitchCamera,Inspect,Save,Clear,Home,Warning,Check,Close,Info,Back}
 [RequireComponent(typeof(CanvasRenderer))]
 public sealed class AppIconGraphic:MaskableGraphic {
  public AppIcon symbol;
  void Line(VertexHelper v,float x,float y,float a,float b){
   var r=rectTransform.rect;float size=Mathf.Min(r.width,r.height);Vector2 origin=r.center-new Vector2(size,size)*.5f;Vector2 p=origin+new Vector2(x,y)*size,q=origin+new Vector2(a,b)*size;
   Vector2 n=(q-p).normalized;n=new Vector2(-n.y,n.x)*size*.014f;
   int i=v.currentVertCount;v.AddVert(p-n,color,Vector2.zero);v.AddVert(p+n,color,Vector2.zero);v.AddVert(q+n,color,Vector2.zero);v.AddVert(q-n,color,Vector2.zero);v.AddTriangle(i,i+1,i+2);v.AddTriangle(i,i+2,i+3);
  }
  void Circle(VertexHelper v,float x,float y,float radius,float start=0,float end=360){for(int i=0;i<24;i++){float a=(start+(end-start)*i/24)*Mathf.Deg2Rad,b=(start+(end-start)*(i+1)/24)*Mathf.Deg2Rad;Line(v,x+Mathf.Cos(a)*radius,y+Mathf.Sin(a)*radius,x+Mathf.Cos(b)*radius,y+Mathf.Sin(b)*radius);}}
  void Box(VertexHelper v,float x,float y,float w,float h){Line(v,x,y,x+w,y);Line(v,x+w,y,x+w,y+h);Line(v,x+w,y+h,x,y+h);Line(v,x,y+h,x,y);}
  protected override void OnPopulateMesh(VertexHelper v){
   v.Clear();switch(symbol){
    case AppIcon.Camera:case AppIcon.Save:Box(v,.12f,.2f,.76f,.56f);Line(v,.3f,.76f,.37f,.88f);Line(v,.37f,.88f,.63f,.88f);Line(v,.63f,.88f,.7f,.76f);Circle(v,.5f,.48f,.17f);break;
    case AppIcon.SwitchCamera:Circle(v,.5f,.5f,.32f,25,165);Circle(v,.5f,.5f,.32f,205,345);Line(v,.19f,.58f,.15f,.76f);Line(v,.19f,.58f,.37f,.59f);Line(v,.81f,.42f,.85f,.24f);Line(v,.81f,.42f,.63f,.41f);break;
    case AppIcon.Inspect:Circle(v,.43f,.57f,.25f);Line(v,.61f,.39f,.86f,.14f);Line(v,.29f,.55f,.4f,.45f);Line(v,.4f,.45f,.58f,.66f);break;
    case AppIcon.Home:Line(v,.1f,.52f,.5f,.88f);Line(v,.5f,.88f,.9f,.52f);Line(v,.23f,.58f,.23f,.14f);Line(v,.23f,.14f,.77f,.14f);Line(v,.77f,.14f,.77f,.58f);Box(v,.42f,.14f,.16f,.27f);break;
    case AppIcon.Clear:Line(v,.2f,.73f,.8f,.73f);Line(v,.37f,.86f,.63f,.86f);Line(v,.27f,.67f,.32f,.15f);Line(v,.32f,.15f,.68f,.15f);Line(v,.68f,.15f,.73f,.67f);Line(v,.43f,.6f,.43f,.26f);Line(v,.57f,.6f,.57f,.26f);break;
    case AppIcon.Back:Line(v,.82f,.5f,.18f,.5f);Line(v,.18f,.5f,.46f,.78f);Line(v,.18f,.5f,.46f,.22f);break;
    case AppIcon.Check:Line(v,.17f,.48f,.4f,.25f);Line(v,.4f,.25f,.84f,.78f);break;
    case AppIcon.Close:Line(v,.23f,.23f,.77f,.77f);Line(v,.23f,.77f,.77f,.23f);break;
    case AppIcon.Warning:Line(v,.12f,.16f,.5f,.86f);Line(v,.5f,.86f,.88f,.16f);Line(v,.88f,.16f,.12f,.16f);Line(v,.5f,.38f,.5f,.64f);Line(v,.5f,.26f,.5f,.28f);break;
    default:Circle(v,.5f,.5f,.36f);Line(v,.5f,.34f,.5f,.56f);Line(v,.5f,.69f,.5f,.7f);break;
   }
  }
 }
}
