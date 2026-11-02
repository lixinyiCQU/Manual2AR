using UnityEngine;
using UnityEngine.UI;
namespace Manual2AR
{
    // Custom Graphic subclasses must declare their renderer dependency explicitly.
    [RequireComponent(typeof(CanvasRenderer))]
    public sealed class PrinterLearningLine : MaskableGraphic
    {
        Vector2 start,end;
        public void SetPoints(Vector2 a,Vector2 b) { if((start-a).sqrMagnitude<.01f&&(end-b).sqrMagnitude<.01f)return;start=a;end=b;SetVerticesDirty(); }
        protected override void OnPopulateMesh(VertexHelper vh)
        {
            vh.Clear();Vector2 delta=end-start;
            if(delta.sqrMagnitude<1) return;
            Vector2 n=new Vector2(-delta.y,delta.x).normalized*1.2f;
            var v=UIVertex.simpleVert;v.color=color;
            v.position=start-n;vh.AddVert(v);v.position=start+n;vh.AddVert(v);
            v.position=end+n;vh.AddVert(v);v.position=end-n;vh.AddVert(v);
            vh.AddTriangle(0,1,2);vh.AddTriangle(0,2,3);
        }
    }
}
