using UnityEngine;
using UnityEngine.UI;

namespace Manual2AR
{
    /// <summary>
    /// Resolution-independent broad arrow used by the paper-figure overlays.
    /// It is built from UI mesh geometry so it can remain crisp, translucent,
    /// recolored, and anchored to a tracked image-space target.
    /// </summary>
    public sealed class Manual2ARArrowGraphic : MaskableGraphic
    {
        [SerializeField, Range(0.18f, 0.72f)]
        float m_ShaftWidthRatio = 0.42f;

        [SerializeField, Range(0.18f, 0.58f)]
        float m_HeadHeightRatio = 0.38f;

        void Update()
        {
            if (isActiveAndEnabled)
                SetVerticesDirty();
        }

        protected override void OnPopulateMesh(VertexHelper vertexHelper)
        {
            vertexHelper.Clear();
            var bounds = GetPixelAdjustedRect();
            var centerX = bounds.center.x;
            // Keep the arrow tip locked to the tracked inlet while the tail
            // breathes vertically. This reads as motion without target drift.
            var tailPulse = (Mathf.Sin(Time.unscaledTime * Mathf.PI * 2.0f * 1.05f) + 1.0f) * 0.5f;
            var bottom = bounds.yMin + tailPulse * Mathf.Min(14.0f, bounds.height * 0.07f);
            var top = bounds.yMax;
            var headBase = Mathf.Lerp(top, bottom, m_HeadHeightRatio);
            var halfShaft = bounds.width * m_ShaftWidthRatio * 0.5f;

            AddVertex(vertexHelper, new Vector2(centerX - halfShaft, bottom));
            AddVertex(vertexHelper, new Vector2(centerX + halfShaft, bottom));
            AddVertex(vertexHelper, new Vector2(centerX + halfShaft, headBase));
            AddVertex(vertexHelper, new Vector2(centerX - halfShaft, headBase));
            vertexHelper.AddTriangle(0, 1, 2);
            vertexHelper.AddTriangle(0, 2, 3);

            AddVertex(vertexHelper, new Vector2(bounds.xMin, headBase));
            AddVertex(vertexHelper, new Vector2(bounds.xMax, headBase));
            AddVertex(vertexHelper, new Vector2(centerX, top));
            vertexHelper.AddTriangle(4, 5, 6);
        }

        void AddVertex(VertexHelper helper, Vector2 position)
        {
            var vertex = UIVertex.simpleVert;
            vertex.color = color;
            vertex.position = position;
            helper.AddVert(vertex);
        }
    }
}
