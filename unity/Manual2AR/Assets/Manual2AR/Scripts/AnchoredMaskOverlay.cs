using System.Collections.Generic;
using TMPro;
using UnityEngine;

namespace Manual2AR
{
    public sealed class AnchoredMaskOverlay : MonoBehaviour
    {
        static readonly Color CyanFill = new Color(0.0f, 0.88f, 1.0f, 0.36f);
        static readonly Color CyanLine = new Color(0.0f, 0.88f, 1.0f, 1.0f);
        static readonly Color LabelBackground = new Color(0.02f, 0.08f, 0.11f, 0.82f);

        [SerializeField]
        Camera m_ArCamera;

        [SerializeField]
        float m_OverlayDepthOffsetMeters = 0.012f;

        [SerializeField]
        float m_ArrowWidthMeters = 0.026f;

        GameObject m_Root;
        MeshFilter m_MeshFilter;
        MeshRenderer m_MeshRenderer;
        LineRenderer m_ArrowLine;
        LineRenderer m_ArrowHeadA;
        LineRenderer m_ArrowHeadB;
        TextMeshPro m_PrimaryText;
        TextMeshPro m_SecondaryText;
        Material m_MaskMaterial;
        Material m_LineMaterial;
        Material m_LabelMaterial;
        readonly List<Vector3> m_LocalMaskVertices = new();
        Vector3 m_ArrowStart;
        Vector3 m_ArrowEnd;
        float m_RevealStartedAt;
        bool m_Revealing;

        public bool isShowing => m_Root != null && m_Root.activeSelf;

        public void Initialize(Camera arCamera)
        {
            m_ArCamera = arCamera;
            EnsureMaterials();
        }

        public void Clear()
        {
            if (m_Root != null)
                Destroy(m_Root);
            m_Root = null;
            m_MeshFilter = null;
            m_MeshRenderer = null;
            m_ArrowLine = null;
            m_ArrowHeadA = null;
            m_ArrowHeadB = null;
            m_PrimaryText = null;
            m_SecondaryText = null;
            m_LocalMaskVertices.Clear();
        }

        public void Show(
            Transform anchor,
            int[] polygon_0_1000,
            int[] centroid_0_1000,
            string primaryLabel,
            string secondaryLabel)
        {
            if (anchor == null || m_ArCamera == null || polygon_0_1000 == null || polygon_0_1000.Length < 6)
                return;

            EnsureRoot(anchor);
            EnsureMaterials();
            BuildMask(anchor, polygon_0_1000, centroid_0_1000);
            BuildArrowAndLabels(primaryLabel, secondaryLabel);
        }

        void LateUpdate()
        {
            if (m_Root == null || m_ArCamera == null)
                return;

            var direction = m_Root.transform.position - m_ArCamera.transform.position;
            if (direction.sqrMagnitude > 0.0001f)
                m_Root.transform.rotation = Quaternion.LookRotation(direction.normalized, Vector3.up);
            if (m_Revealing)
            {
                var linear = Mathf.Clamp01((Time.unscaledTime - m_RevealStartedAt) / 0.28f);
                var eased = linear * linear * (3.0f - 2.0f * linear);
                m_Root.transform.localScale = Vector3.one * Mathf.Lerp(0.965f, 1.0f, eased);
                m_Revealing = linear < 1.0f;
            }
            if (m_ArrowLine != null)
            {
                var pulse = (Mathf.Sin(Time.unscaledTime * Mathf.PI * 2.0f * 1.05f) + 1.0f) * 0.5f;
                SetLine(
                    m_ArrowLine,
                    m_ArrowStart + Vector3.right * pulse * 0.014f,
                    m_ArrowEnd,
                    m_ArrowWidthMeters);
            }
        }

        void EnsureRoot(Transform anchor)
        {
            if (m_Root != null)
            {
                m_Root.transform.SetParent(anchor, false);
                m_Root.transform.localPosition = Vector3.forward * m_OverlayDepthOffsetMeters;
                return;
            }

            m_Root = new GameObject("Manual2AR Anchored Empty Spindle Overlay");
            m_Root.transform.SetParent(anchor, false);
            m_Root.transform.localPosition = Vector3.forward * m_OverlayDepthOffsetMeters;
            m_Root.transform.localScale = Vector3.one * 0.965f;
            m_RevealStartedAt = Time.unscaledTime;
            m_Revealing = true;

            var mask = new GameObject("SAM Visible Surface Mask");
            mask.transform.SetParent(m_Root.transform, false);
            m_MeshFilter = mask.AddComponent<MeshFilter>();
            m_MeshRenderer = mask.AddComponent<MeshRenderer>();
            m_MeshRenderer.sharedMaterial = m_MaskMaterial;

            m_ArrowLine = CreateLine("Mount Direction Arrow");
            m_ArrowHeadA = CreateLine("Arrow Head A");
            m_ArrowHeadB = CreateLine("Arrow Head B");

            m_PrimaryText = CreateWorldLabel("Primary Instruction", 0.0f, -0.18f, 0.03f);
            m_SecondaryText = CreateWorldLabel("Secondary Status", 0.0f, -0.235f, 0.022f);
        }

        void BuildMask(Transform anchor, int[] polygon_0_1000, int[] centroid_0_1000)
        {
            m_LocalMaskVertices.Clear();

            var anchorDistance = Mathf.Max(0.25f, Vector3.Distance(m_ArCamera.transform.position, anchor.position));
            var worldHeight = 2.0f * anchorDistance * Mathf.Tan(m_ArCamera.fieldOfView * 0.5f * Mathf.Deg2Rad);
            var worldWidth = worldHeight * m_ArCamera.aspect;

            var centroid = ReadPoint(centroid_0_1000, 500, 500);
            for (var i = 0; i + 1 < polygon_0_1000.Length; i += 2)
            {
                var p = new Vector2(polygon_0_1000[i], polygon_0_1000[i + 1]);
                var local = new Vector3(
                    ((p.x - centroid.x) / 1000.0f) * worldWidth,
                    -((p.y - centroid.y) / 1000.0f) * worldHeight,
                    0.0f);
                m_LocalMaskVertices.Add(local);
            }

            if (m_LocalMaskVertices.Count < 3)
                return;

            var vertices = new List<Vector3> { Vector3.zero };
            vertices.AddRange(m_LocalMaskVertices);

            var triangles = new List<int>();
            for (var i = 1; i < vertices.Count; i++)
            {
                var next = i == vertices.Count - 1 ? 1 : i + 1;
                triangles.Add(0);
                triangles.Add(i);
                triangles.Add(next);
            }

            var mesh = new Mesh { name = "Manual2AR SAM Mask Mesh" };
            mesh.SetVertices(vertices);
            mesh.SetTriangles(triangles, 0);
            mesh.RecalculateBounds();
            mesh.RecalculateNormals();
            m_MeshFilter.sharedMesh = mesh;
        }

        void BuildArrowAndLabels(string primaryLabel, string secondaryLabel)
        {
            var bounds = ComputeLocalBounds();
            var width = Mathf.Max(0.18f, bounds.size.x);
            var arrowY = bounds.max.y + 0.07f;
            var start = new Vector3(bounds.max.x + width * 0.30f, arrowY, -0.002f);
            var end = new Vector3(bounds.center.x, arrowY, -0.002f);
            m_ArrowStart = start;
            m_ArrowEnd = end;

            SetLine(m_ArrowLine, start, end, m_ArrowWidthMeters);
            SetLine(m_ArrowHeadA, end + new Vector3(0.055f, 0.035f, 0), end, m_ArrowWidthMeters * 0.8f);
            SetLine(m_ArrowHeadB, end + new Vector3(0.055f, -0.035f, 0), end, m_ArrowWidthMeters * 0.8f);

            m_PrimaryText.text = primaryLabel;
            m_PrimaryText.transform.localPosition = new Vector3(bounds.center.x, bounds.min.y - 0.13f, -0.003f);
            m_SecondaryText.text = secondaryLabel;
            m_SecondaryText.transform.localPosition = new Vector3(bounds.center.x, bounds.min.y - 0.19f, -0.003f);
        }

        Bounds ComputeLocalBounds()
        {
            if (m_LocalMaskVertices.Count == 0)
                return new Bounds(Vector3.zero, new Vector3(0.22f, 0.16f, 0.01f));

            var bounds = new Bounds(m_LocalMaskVertices[0], Vector3.zero);
            for (var i = 1; i < m_LocalMaskVertices.Count; i++)
                bounds.Encapsulate(m_LocalMaskVertices[i]);
            return bounds;
        }

        static Vector2 ReadPoint(int[] values, int fallbackX, int fallbackY)
        {
            if (values == null || values.Length < 2)
                return new Vector2(fallbackX, fallbackY);
            return new Vector2(values[0], values[1]);
        }

        LineRenderer CreateLine(string lineName)
        {
            var go = new GameObject(lineName);
            go.transform.SetParent(m_Root.transform, false);
            var line = go.AddComponent<LineRenderer>();
            line.sharedMaterial = m_LineMaterial;
            line.positionCount = 2;
            line.useWorldSpace = false;
            line.numCapVertices = 8;
            line.numCornerVertices = 8;
            line.startColor = CyanLine;
            line.endColor = CyanLine;
            return line;
        }

        void SetLine(LineRenderer line, Vector3 start, Vector3 end, float width)
        {
            line.startWidth = width;
            line.endWidth = width;
            line.SetPosition(0, start);
            line.SetPosition(1, end);
        }

        TextMeshPro CreateWorldLabel(string labelName, float x, float y, float fontSize)
        {
            var go = new GameObject(labelName);
            go.transform.SetParent(m_Root.transform, false);
            go.transform.localPosition = new Vector3(x, y, -0.004f);

            var text = go.AddComponent<TextMeshPro>();
            text.alignment = TextAlignmentOptions.Center;
            text.fontSize = fontSize;
            text.enableWordWrapping = false;
            text.color = Color.white;
            text.text = "";
            return text;
        }

        void EnsureMaterials()
        {
            if (m_MaskMaterial == null)
            {
                m_MaskMaterial = new Material(Shader.Find("Sprites/Default"));
                m_MaskMaterial.color = CyanFill;
                m_MaskMaterial.renderQueue = 3000;
            }

            if (m_LineMaterial == null)
            {
                m_LineMaterial = new Material(Shader.Find("Sprites/Default"));
                m_LineMaterial.color = CyanLine;
                m_LineMaterial.renderQueue = 3001;
            }

            if (m_LabelMaterial == null)
            {
                m_LabelMaterial = new Material(Shader.Find("Sprites/Default"));
                m_LabelMaterial.color = LabelBackground;
            }
        }
    }
}
