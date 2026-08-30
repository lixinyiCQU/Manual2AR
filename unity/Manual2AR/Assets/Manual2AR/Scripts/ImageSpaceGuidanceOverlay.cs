using System;
using UnityEngine;
using UnityEngine.UI;

namespace Manual2AR
{
    /// <summary>
    /// Renders the server's current-frame SAM mask in the exact same image
    /// plane as the WebCamTexture.  This is intentionally image-space guidance:
    /// the Mac demo does not claim an ARKit world anchor.
    /// </summary>
    public sealed class ImageSpaceGuidanceOverlay : MonoBehaviour
    {
        RawImage m_MaskImage;
        RectTransform m_ArrowRoot;
        Text m_PrimaryText;
        Text m_SecondaryText;
        RectTransform m_StateBadge;
        Text m_StateBadgeText;
        RectTransform m_GuidancePanel;
        Texture2D m_MaskTexture;

        public bool isShowing => m_MaskImage != null && m_MaskImage.gameObject.activeSelf;

        public void Initialize(RectTransform cameraContent, Transform screenUiRoot)
        {
            if (m_MaskImage != null)
                return;

            var maskObject = new GameObject("Current SAM Visible-Surface Mask");
            maskObject.transform.SetParent(cameraContent, false);
            var maskRect = maskObject.AddComponent<RectTransform>();
            Stretch(maskRect);
            m_MaskImage = maskObject.AddComponent<RawImage>();
            m_MaskImage.raycastTarget = false;
            m_MaskImage.color = Color.white;
            maskObject.AddComponent<Manual2ARRevealMotion>().Configure(false);

            var arrowObject = new GameObject("Tracked Mount Direction Arrow");
            // Function 3 already proves this arrangement in the live Mac view:
            // draw the arrow in the upright screen UI, then map its endpoint
            // from the rotated/aspect-filled camera plane into world/screen
            // coordinates.  Keeping the arrow itself under cameraContent made
            // its local 90-degree direction combine with the webcam rotation,
            // which could move the complete mesh outside the visible Game View.
            arrowObject.transform.SetParent(screenUiRoot, false);
            m_ArrowRoot = arrowObject.AddComponent<RectTransform>();
            m_ArrowRoot.anchorMin = new Vector2(0.5f, 0.5f);
            m_ArrowRoot.anchorMax = new Vector2(0.5f, 0.5f);
            // Manual2ARArrowGraphic points from bottom to top. Keeping its
            // pivot at the tip and rotating the root 90 degrees makes the same
            // Function 3 arrow point right-to-left without changing its visual
            // proportions or target-lock animation.
            m_ArrowRoot.pivot = new Vector2(0.5f, 1.0f);
            // Match Function 3's paper-figure arrow proportions exactly.
            m_ArrowRoot.sizeDelta = new Vector2(176.0f, 224.0f);
            var arrow = arrowObject.AddComponent<Manual2ARArrowGraphic>();
            arrow.color = new Color(
                Manual2ARVisualTheme.TargetCyan.r,
                Manual2ARVisualTheme.TargetCyan.g,
                Manual2ARVisualTheme.TargetCyan.b,
                0.64f);
            arrow.raycastTarget = false;
            var arrowOutline = arrowObject.AddComponent<Outline>();
            arrowOutline.effectColor = new Color(0.0f, 0.06f, 0.08f, 0.72f);
            arrowOutline.effectDistance = new Vector2(5.0f, -5.0f);
            arrowObject.AddComponent<Manual2ARRevealMotion>().Configure(false);

            CreateStateBadge(screenUiRoot);
            CreateGuidancePanel(screenUiRoot);
            m_PrimaryText = CreateInstructionText(
                m_GuidancePanel,
                "Primary Guidance",
                new Vector2(0.5f, 0.5f),
                new Vector2(0.0f, 22.0f),
                Manual2ARVisualTheme.PrimaryInstructionFontSize,
                Manual2ARVisualTheme.TargetLabel);
            m_SecondaryText = CreateInstructionText(
                m_GuidancePanel,
                "Secondary Guidance",
                new Vector2(0.5f, 0.5f),
                new Vector2(0.0f, -25.0f),
                Manual2ARVisualTheme.SecondaryInstructionFontSize,
                Color.white);
            m_PrimaryText.gameObject.AddComponent<Manual2ARRevealMotion>();
            m_SecondaryText.gameObject.AddComponent<Manual2ARRevealMotion>();

            Clear();
        }

        public bool Show(
            TrackedComponent tracked,
            string primaryLabel,
            string secondaryLabel,
            out string error)
        {
            error = null;
            if (tracked == null || tracked.status != "tracking" || tracked.requires_redetection ||
                !tracked.mask_quality_passed || tracked.quality < 0.45f)
            {
                error = "tracking quality gate rejected the current mask";
                Clear();
                return false;
            }

            if (string.IsNullOrWhiteSpace(tracked.overlay_png_base64))
            {
                error = "tracking response did not include a current mask";
                Clear();
                return false;
            }

            try
            {
                var png = Convert.FromBase64String(tracked.overlay_png_base64);
                if (m_MaskTexture == null)
                {
                    m_MaskTexture = new Texture2D(2, 2, TextureFormat.RGBA32, false)
                    {
                        name = "Manual2AR Current Tracking Mask"
                    };
                }

                if (!ImageConversion.LoadImage(m_MaskTexture, png, false))
                    throw new InvalidOperationException("Unity could not decode the mask PNG");
                Manual2ARVisualTheme.RecolorMask(
                    m_MaskTexture,
                    new Color32(10, 225, 245, 142));

                m_MaskImage.texture = m_MaskTexture;
                m_MaskImage.gameObject.SetActive(true);

                var centroid = ReadPoint(tracked.centroid_0_1000, 500, 500);
                PositionArrow(centroid, tracked.bbox_0_1000);
                // Keep the animated direction arrow above the screen panels
                // after each tracking refresh.
                m_ArrowRoot.SetAsLastSibling();
                m_ArrowRoot.gameObject.SetActive(true);

                m_PrimaryText.text = primaryLabel;
                m_SecondaryText.text = secondaryLabel;
                m_PrimaryText.gameObject.SetActive(true);
                m_SecondaryText.gameObject.SetActive(true);
                m_StateBadgeText.text = "GUIDANCE STATE";
                m_StateBadge.gameObject.SetActive(true);
                m_GuidancePanel.gameObject.SetActive(true);
                return true;
            }
            catch (Exception exception)
            {
                error = exception.Message;
                Clear();
                return false;
            }
        }

        public void Clear()
        {
            if (m_MaskImage != null)
                m_MaskImage.gameObject.SetActive(false);
            if (m_ArrowRoot != null)
                m_ArrowRoot.gameObject.SetActive(false);
            if (m_PrimaryText != null)
                m_PrimaryText.gameObject.SetActive(false);
            if (m_SecondaryText != null)
                m_SecondaryText.gameObject.SetActive(false);
            if (m_StateBadge != null)
                m_StateBadge.gameObject.SetActive(false);
            if (m_GuidancePanel != null)
                m_GuidancePanel.gameObject.SetActive(false);
        }

        void OnDestroy()
        {
            if (m_MaskTexture != null)
                Destroy(m_MaskTexture);
        }

        static Vector2 ReadPoint(int[] values, int fallbackX, int fallbackY)
        {
            if (values == null || values.Length < 2)
                return new Vector2(fallbackX, fallbackY);
            return new Vector2(values[0], values[1]);
        }

        void PositionArrow(Vector2 targetPoint, int[] trackedBox)
        {
            if (m_ArrowRoot == null || m_MaskImage == null)
                return;
            var cameraContent = m_MaskImage.rectTransform.parent as RectTransform;
            if (cameraContent == null)
                return;
            // Put the tip on the right-hand portion of the tracked holder so
            // the shaft remains outside the cyan mask and cannot visually
            // disappear into it. The normalized clamps reserve room for the
            // arrow tail and for the top/bottom recording UI.
            if (trackedBox != null && trackedBox.Length >= 4)
            {
                var boxWidth = Mathf.Max(1.0f, trackedBox[2] - trackedBox[0]);
                var boxHeight = Mathf.Max(1.0f, trackedBox[3] - trackedBox[1]);
                targetPoint.x = trackedBox[0] + boxWidth * 0.72f;
                targetPoint.y = trackedBox[1] + boxHeight * 0.50f;
            }
            targetPoint.x = Mathf.Clamp(targetPoint.x, 90.0f, 900.0f);
            targetPoint.y = Mathf.Clamp(targetPoint.y, 145.0f, 835.0f);

            var rect = cameraContent.rect;
            var x = rect.xMin + rect.width * targetPoint.x / 1000.0f;
            var y = rect.yMax - rect.height * targetPoint.y / 1000.0f;
            // Convert through the camera transform instead of assigning its
            // local coordinates directly to a screen-space RectTransform.
            // This preserves the tracked endpoint under rotation, mirroring
            // and Aspect Fill while the arrow stays upright and visible.
            var worldTarget = cameraContent.TransformPoint(new Vector3(x, y, 0.0f));
            m_ArrowRoot.position = worldTarget;
            m_ArrowRoot.rotation = Quaternion.Euler(0.0f, 0.0f, 90.0f);
            m_ArrowRoot.localScale = Vector3.one;
        }

        static Text CreateInstructionText(
            Transform parent,
            string name,
            Vector2 anchor,
            Vector2 position,
            int fontSize,
            Color color)
        {
            var objectWithText = new GameObject(name);
            objectWithText.transform.SetParent(parent, false);
            var rect = objectWithText.AddComponent<RectTransform>();
            rect.anchorMin = anchor;
            rect.anchorMax = anchor;
            rect.pivot = new Vector2(0.5f, 0.5f);
            rect.anchoredPosition = position;
            rect.sizeDelta = new Vector2(980.0f, 44.0f);

            var text = objectWithText.AddComponent<Text>();
            Manual2ARVisualTheme.StyleText(text, fontSize, color, TextAnchor.MiddleCenter);
            text.horizontalOverflow = HorizontalWrapMode.Overflow;
            text.verticalOverflow = VerticalWrapMode.Overflow;
            Manual2ARVisualTheme.AddTextDepth(objectWithText, 3.0f);
            return text;
        }

        void CreateStateBadge(Transform root)
        {
            var badgeObject = new GameObject("Spool Guidance State Badge");
            badgeObject.transform.SetParent(root, false);
            m_StateBadge = badgeObject.AddComponent<RectTransform>();
            m_StateBadge.anchorMin = new Vector2(0.0f, 1.0f);
            m_StateBadge.anchorMax = new Vector2(0.0f, 1.0f);
            m_StateBadge.pivot = new Vector2(0.0f, 1.0f);
            m_StateBadge.anchoredPosition = new Vector2(28.0f, -28.0f);
            m_StateBadge.sizeDelta = new Vector2(380.0f, 68.0f);
            var background = badgeObject.AddComponent<Image>();
            background.color = Manual2ARVisualTheme.PanelBackground;
            var outline = badgeObject.AddComponent<Outline>();
            outline.effectColor = new Color(
                Manual2ARVisualTheme.TargetCyan.r,
                Manual2ARVisualTheme.TargetCyan.g,
                Manual2ARVisualTheme.TargetCyan.b,
                0.92f);
            outline.effectDistance = new Vector2(3.0f, -3.0f);
            badgeObject.AddComponent<Manual2ARRevealMotion>();
            m_StateBadgeText = CreateInstructionText(
                m_StateBadge,
                "State Badge Text",
                new Vector2(0.5f, 0.5f),
                Vector2.zero,
                25,
                Manual2ARVisualTheme.TargetLabel);
            m_StateBadgeText.alignment = TextAnchor.MiddleCenter;
        }

        void CreateGuidancePanel(Transform root)
        {
            var panelObject = new GameObject("Spool Guidance Live Tracking Panel");
            panelObject.transform.SetParent(root, false);
            m_GuidancePanel = panelObject.AddComponent<RectTransform>();
            m_GuidancePanel.anchorMin = new Vector2(0.5f, 0.0f);
            m_GuidancePanel.anchorMax = new Vector2(0.5f, 0.0f);
            m_GuidancePanel.pivot = new Vector2(0.5f, 0.0f);
            m_GuidancePanel.anchoredPosition = new Vector2(0.0f, 32.0f);
            m_GuidancePanel.sizeDelta = new Vector2(1120.0f, 116.0f);
            var background = panelObject.AddComponent<Image>();
            background.color = Manual2ARVisualTheme.PanelBackground;
            var outline = panelObject.AddComponent<Outline>();
            outline.effectColor = new Color(
                Manual2ARVisualTheme.TargetCyan.r,
                Manual2ARVisualTheme.TargetCyan.g,
                Manual2ARVisualTheme.TargetCyan.b,
                0.92f);
            outline.effectDistance = new Vector2(3.0f, -3.0f);
            panelObject.AddComponent<Manual2ARRevealMotion>();
        }

        static void Stretch(RectTransform rect)
        {
            rect.anchorMin = Vector2.zero;
            rect.anchorMax = Vector2.one;
            rect.offsetMin = Vector2.zero;
            rect.offsetMax = Vector2.zero;
        }
    }

    /// <summary>One clean UI mesh: a thick shaft and a large left arrowhead.</summary>
    public sealed class GuidanceArrowGraphic : MaskableGraphic
    {
        float m_TargetX = 500.0f;
        float m_TargetY = 500.0f;
        float m_TargetBoxWidth = 180.0f;

        void Update()
        {
            if (isActiveAndEnabled)
                SetVerticesDirty();
        }

        public void SetTarget(float x_0_1000, float y_0_1000, float boxWidth_0_1000)
        {
            m_TargetX = Mathf.Clamp(x_0_1000, 0.0f, 1000.0f);
            m_TargetY = Mathf.Clamp(y_0_1000, 0.0f, 1000.0f);
            m_TargetBoxWidth = Mathf.Clamp(boxWidth_0_1000, 20.0f, 700.0f);
            SetVerticesDirty();
        }

        protected override void OnPopulateMesh(VertexHelper vertexHelper)
        {
            vertexHelper.Clear();
            var rect = rectTransform.rect;
            if (rect.width <= 1.0f || rect.height <= 1.0f)
                return;

            var target = new Vector2(
                rect.xMin + rect.width * m_TargetX / 1000.0f,
                rect.yMax - rect.height * m_TargetY / 1000.0f);
            var minRun = rect.width * 0.105f;
            var boxRun = rect.width * m_TargetBoxWidth / 1000.0f;
            var baseRun = Mathf.Clamp(boxRun * 0.72f, minRun, rect.width * 0.18f);
            var tailPulse = (Mathf.Sin(Time.unscaledTime * Mathf.PI * 2.0f * 1.05f) + 1.0f) * 0.5f;
            var animatedRun = baseRun + tailPulse * rect.width * 0.012f;
            var start = new Vector2(
                Mathf.Min(rect.xMax - rect.width * 0.035f, target.x + animatedRun),
                target.y);
            var thickness = Mathf.Max(22.0f, rect.width * 0.028f);
            var headLength = Mathf.Max(52.0f, rect.width * 0.065f);
            var headHalfHeight = headLength * 0.78f;

            // Leave the triangular arrowhead visually separate from the
            // holder's center so the target surface remains readable.
            var shaftEndX = Mathf.Min(start.x, target.x + headLength * 0.72f);
            AddQuad(
                vertexHelper,
                new Vector2(shaftEndX, target.y - thickness * 0.5f),
                new Vector2(start.x, target.y - thickness * 0.5f),
                new Vector2(start.x, target.y + thickness * 0.5f),
                new Vector2(shaftEndX, target.y + thickness * 0.5f));
            AddTriangle(
                vertexHelper,
                target,
                new Vector2(target.x + headLength, target.y - headHalfHeight),
                new Vector2(target.x + headLength, target.y + headHalfHeight));
        }

        void AddQuad(VertexHelper helper, Vector2 a, Vector2 b, Vector2 c, Vector2 d)
        {
            var startIndex = helper.currentVertCount;
            helper.AddVert(a, color, Vector2.zero);
            helper.AddVert(b, color, Vector2.zero);
            helper.AddVert(c, color, Vector2.zero);
            helper.AddVert(d, color, Vector2.zero);
            helper.AddTriangle(startIndex, startIndex + 1, startIndex + 2);
            helper.AddTriangle(startIndex, startIndex + 2, startIndex + 3);
        }

        void AddTriangle(VertexHelper helper, Vector2 a, Vector2 b, Vector2 c)
        {
            var startIndex = helper.currentVertCount;
            helper.AddVert(a, color, Vector2.zero);
            helper.AddVert(b, color, Vector2.zero);
            helper.AddVert(c, color, Vector2.zero);
            helper.AddTriangle(startIndex, startIndex + 1, startIndex + 2);
        }
    }
}
