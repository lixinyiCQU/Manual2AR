using System;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UI;

namespace Manual2AR
{
    /// <summary>
    /// Renders current-frame plate/anomaly masks and a screen-space inspection
    /// panel. All masks remain children of the oriented camera-pixel transform,
    /// so aspect-fill crop, webcam rotation, and mirroring are shared exactly.
    /// </summary>
    public sealed class PrePrintPlateInspectionOverlay : MonoBehaviour
    {
        sealed class MaskLayer
        {
            public RawImage image;
            public Texture2D texture;
            public Text label;
            public string objectType;
            public int[] trackedBox;
        }

        readonly Dictionary<string, MaskLayer> m_Layers = new Dictionary<string, MaskLayer>();
        RectTransform m_CameraContent;
        Transform m_ScreenUiRoot;
        RectTransform m_Panel;
        Outline m_PanelOutline;
        Text m_AlignedRow;
        Text m_ClearRow;
        Text m_ResidueRow;
        Text m_ActionText;
        Text m_HeadlineText;
        RectTransform m_StateBadge;
        Text m_StateBadgeText;
        Outline m_StateBadgeOutline;
        RectTransform m_BottomBanner;
        Text m_BottomBannerText;
        Outline m_BottomBannerOutline;
        int[] m_PlateBox;
        bool m_SafeToPrint;

        public void Initialize(RectTransform cameraContent, Transform screenUiRoot)
        {
            m_CameraContent = cameraContent;
            m_ScreenUiRoot = screenUiRoot;
            CreatePanel(screenUiRoot);
            CreateStateBadge(screenUiRoot);
            CreateBottomBanner(screenUiRoot);
            Clear();
        }

        public bool ShowMask(
            string objectId,
            string objectType,
            TrackedComponent tracked,
            bool safeToPrint,
            out string error)
        {
            error = null;
            if (tracked == null || tracked.status != "tracking" || tracked.requires_redetection ||
                !tracked.mask_quality_passed || tracked.quality < 0.45f ||
                string.IsNullOrWhiteSpace(tracked.overlay_png_base64))
            {
                error = "current mask failed the Unity inspection gate";
                return false;
            }

            try
            {
                var layer = EnsureLayer(objectId, objectType);
                var png = Convert.FromBase64String(tracked.overlay_png_base64);
                if (!ImageConversion.LoadImage(layer.texture, png, false))
                    throw new InvalidOperationException("Unity could not decode the current SAM mask");
                RecolorMask(layer.texture, objectType, safeToPrint);
                layer.image.texture = layer.texture;
                layer.image.gameObject.SetActive(true);
                layer.label.text = LabelForObjectType(objectType);
                layer.label.color = IsAnomaly(objectType)
                    ? Manual2ARVisualTheme.ErrorRed
                    : Manual2ARVisualTheme.TargetLabel;
                layer.label.gameObject.SetActive(true);
                layer.trackedBox = tracked.bbox_0_1000;
                layer.objectType = objectType;
                if (objectType == "build_plate")
                    m_PlateBox = tracked.bbox_0_1000;
                m_SafeToPrint = safeToPrint;
                PositionMaskLabel(layer);
                PositionPanel();
                return true;
            }
            catch (Exception exception)
            {
                error = exception.Message;
                return false;
            }
        }

        public void SetInspectionState(BuildPlateInspectionResponse response)
        {
            if (response == null)
            {
                Clear();
                return;
            }
            if (response.status == "uncertain")
            {
                ShowUncertain();
                return;
            }
            m_SafeToPrint = response.safe_to_print;
            var aligned = PredicatePassed(response, "plate_aligned");
            var clear = PredicatePassed(response, "surface_clear");
            var noResidue = PredicatePassed(response, "no_residue");
            SetRow(m_AlignedRow, aligned, "PLATE ALIGNED");
            SetRow(m_ClearRow, clear, "SURFACE CLEAR");
            SetRow(m_ResidueRow, noResidue, "NO RESIDUE");
            m_HeadlineText.text = response.safe_to_print
                ? "READY TO PRINT"
                : "CORRECTIVE ACTION REQUIRED";
            m_HeadlineText.color = response.safe_to_print
                ? Manual2ARVisualTheme.SuccessGreen
                : Manual2ARVisualTheme.ErrorRed;
            m_ActionText.text = response.safe_to_print
                ? "BUILD PLATE VERIFIED"
                : JoinActions(response.correction_instructions);
            m_ActionText.color = response.safe_to_print
                ? Manual2ARVisualTheme.TargetCyan
                : new Color(1.0f, 0.82f, 0.74f, 1.0f);
            SetFrameStyle(
                response.safe_to_print ? "VERIFIED STATE" : "CORRECTIVE STATE",
                response.safe_to_print
                    ? "READY TO PRINT · LIVE TRACKING"
                    : "CORRECTIVE ACTION REQUIRED · LIVE TRACKING",
                response.safe_to_print
                    ? Manual2ARVisualTheme.TargetCyan
                    : Manual2ARVisualTheme.ErrorRed,
                response.safe_to_print
                    ? Manual2ARVisualTheme.SuccessGreen
                    : Manual2ARVisualTheme.ErrorRed);
            m_Panel.gameObject.SetActive(true);
            m_StateBadge.gameObject.SetActive(true);
            m_BottomBanner.gameObject.SetActive(true);
            PositionPanel();
        }

        public void ShowUncertain()
        {
            Clear();
            m_HeadlineText.text = "INSPECTION UNCERTAIN";
            m_HeadlineText.color = new Color(1.0f, 0.64f, 0.32f, 1.0f);
            m_AlignedRow.text = "!  SHOW THE ENTIRE BUILD PLATE";
            m_AlignedRow.color = Color.white;
            m_ClearRow.text = "!  KEEP ALL FOUR EDGES IN FRAME";
            m_ClearRow.color = Color.white;
            m_ResidueRow.text = "!  THEN PRESS INSPECT AGAIN";
            m_ResidueRow.color = Manual2ARVisualTheme.TargetLabel;
            m_ActionText.text = "REFRAME BUILD PLATE";
            m_ActionText.color = new Color(1.0f, 0.76f, 0.46f, 1.0f);
            SetFrameStyle(
                "STATE UNCERTAIN",
                "REFRAME · RE-INSPECT REQUIRED",
                new Color(1.0f, 0.64f, 0.32f, 1.0f),
                new Color(1.0f, 0.64f, 0.32f, 1.0f));
            m_Panel.anchorMin = new Vector2(1.0f, 0.5f);
            m_Panel.anchorMax = m_Panel.anchorMin;
            m_Panel.pivot = new Vector2(1.0f, 0.5f);
            m_Panel.anchoredPosition = new Vector2(-42.0f, -18.0f);
            m_Panel.gameObject.SetActive(true);
            m_StateBadge.gameObject.SetActive(true);
            m_BottomBanner.gameObject.SetActive(true);
        }

        public void ShowProcessing()
        {
            Clear();
            m_HeadlineText.text = "ANALYZING CURRENT FRAME";
            m_HeadlineText.color = Manual2ARVisualTheme.TargetCyan;
            m_AlignedRow.text = "1  QWEN SEMANTIC GROUNDING";
            m_AlignedRow.color = Color.white;
            m_ClearRow.text = "2  SAM2 VISIBLE-SURFACE MASKS";
            m_ClearRow.color = Color.white;
            m_ResidueRow.text = "3  SAFETY AND QUALITY GATES";
            m_ResidueRow.color = Color.white;
            m_ActionText.text = "PLEASE WAIT";
            m_ActionText.color = Manual2ARVisualTheme.TargetLabel;
            SetFrameStyle(
                "ANALYZING",
                "QWEN3-VL-FLASH + SAM2 · PLEASE WAIT",
                Manual2ARVisualTheme.TargetCyan,
                Manual2ARVisualTheme.TargetCyan);
            m_Panel.anchorMin = new Vector2(1.0f, 0.5f);
            m_Panel.anchorMax = m_Panel.anchorMin;
            m_Panel.pivot = new Vector2(1.0f, 0.5f);
            m_Panel.anchoredPosition = new Vector2(-42.0f, -18.0f);
            m_Panel.gameObject.SetActive(true);
            m_StateBadge.gameObject.SetActive(true);
            m_BottomBanner.gameObject.SetActive(true);
        }

        public void Clear()
        {
            foreach (var layer in m_Layers.Values)
            {
                if (layer.image != null)
                    layer.image.gameObject.SetActive(false);
                if (layer.label != null)
                    layer.label.gameObject.SetActive(false);
                layer.trackedBox = null;
            }
            m_PlateBox = null;
            if (m_Panel != null)
                m_Panel.gameObject.SetActive(false);
            if (m_StateBadge != null)
                m_StateBadge.gameObject.SetActive(false);
            if (m_BottomBanner != null)
                m_BottomBanner.gameObject.SetActive(false);
        }

        void LateUpdate()
        {
            foreach (var layer in m_Layers.Values)
                if (layer.image != null && layer.image.gameObject.activeSelf)
                    PositionMaskLabel(layer);
            if (m_Panel != null && m_Panel.gameObject.activeSelf)
                PositionPanel();
        }

        MaskLayer EnsureLayer(string objectId, string objectType)
        {
            if (m_Layers.TryGetValue(objectId, out var existing))
                return existing;
            var go = new GameObject($"{objectId} Current Inspection Mask");
            go.transform.SetParent(m_CameraContent, false);
            var rect = go.AddComponent<RectTransform>();
            Stretch(rect);
            var rawImage = go.AddComponent<RawImage>();
            rawImage.raycastTarget = false;
            rawImage.color = Color.white;
            go.AddComponent<Manual2ARRevealMotion>().Configure(false);

            var labelObject = new GameObject($"{objectId} Inspection Label");
            labelObject.transform.SetParent(m_ScreenUiRoot, false);
            var labelRect = labelObject.AddComponent<RectTransform>();
            labelRect.anchorMin = new Vector2(0.5f, 0.5f);
            labelRect.anchorMax = new Vector2(0.5f, 0.5f);
            labelRect.pivot = new Vector2(0.5f, 0.5f);
            labelRect.sizeDelta = new Vector2(430.0f, 52.0f);
            var label = labelObject.AddComponent<Text>();
            Manual2ARVisualTheme.StyleText(
                label,
                Manual2ARVisualTheme.ObjectLabelFontSize,
                Manual2ARVisualTheme.TargetLabel,
                TextAnchor.MiddleCenter);
            label.horizontalOverflow = HorizontalWrapMode.Overflow;
            label.verticalOverflow = VerticalWrapMode.Overflow;
            Manual2ARVisualTheme.AddTextDepth(labelObject, 4.0f);
            labelObject.AddComponent<Manual2ARRevealMotion>();
            var layer = new MaskLayer
            {
                image = rawImage,
                texture = new Texture2D(2, 2, TextureFormat.RGBA32, false)
                {
                    name = $"Manual2AR {objectId} Inspection Mask"
                },
                label = label,
                objectType = objectType
            };
            m_Layers.Add(objectId, layer);
            layer.image.gameObject.SetActive(false);
            layer.label.gameObject.SetActive(false);
            return layer;
        }

        static void RecolorMask(Texture2D texture, string objectType, bool safeToPrint)
        {
            var anomaly = IsAnomaly(objectType);
            var target = anomaly
                ? new Color32(255, 28, 18, 190)
                : new Color32(10, 225, 245, safeToPrint ? (byte)118 : (byte)66);
            Manual2ARVisualTheme.RecolorMask(texture, target);
        }

        void CreatePanel(Transform root)
        {
            var panelObject = new GameObject("Pre-print Inspection Checklist");
            panelObject.transform.SetParent(root, false);
            m_Panel = panelObject.AddComponent<RectTransform>();
            m_Panel.anchorMin = new Vector2(0.0f, 0.5f);
            m_Panel.anchorMax = new Vector2(0.0f, 0.5f);
            m_Panel.pivot = new Vector2(0.0f, 0.5f);
            m_Panel.sizeDelta = new Vector2(520.0f, 390.0f);
            var background = panelObject.AddComponent<Image>();
            background.color = Manual2ARVisualTheme.PanelBackground;
            m_PanelOutline = panelObject.AddComponent<Outline>();
            m_PanelOutline.effectColor = new Color(0.04f, 0.82f, 0.92f, 0.9f);
            m_PanelOutline.effectDistance = new Vector2(4.0f, -4.0f);
            panelObject.AddComponent<Manual2ARRevealMotion>();

            m_HeadlineText = CreateText(m_Panel, "Headline", 0.0f, 122.0f, Manual2ARVisualTheme.HeadlineFontSize, TextAnchor.MiddleCenter);
            m_AlignedRow = CreateText(m_Panel, "Plate Aligned", 0.0f, 53.0f, Manual2ARVisualTheme.ObjectLabelFontSize, TextAnchor.MiddleLeft);
            m_ClearRow = CreateText(m_Panel, "Surface Clear", 0.0f, -4.0f, Manual2ARVisualTheme.ObjectLabelFontSize, TextAnchor.MiddleLeft);
            m_ResidueRow = CreateText(m_Panel, "No Residue", 0.0f, -61.0f, Manual2ARVisualTheme.ObjectLabelFontSize, TextAnchor.MiddleLeft);
            m_ActionText = CreateText(m_Panel, "Corrective Actions", 0.0f, -132.0f, 22, TextAnchor.MiddleCenter);
            m_ActionText.rectTransform.sizeDelta = new Vector2(470.0f, 92.0f);
            m_ActionText.horizontalOverflow = HorizontalWrapMode.Wrap;
            m_ActionText.verticalOverflow = VerticalWrapMode.Truncate;
        }

        void CreateStateBadge(Transform root)
        {
            var badgeObject = new GameObject("Plate Inspection State Badge");
            badgeObject.transform.SetParent(root, false);
            m_StateBadge = badgeObject.AddComponent<RectTransform>();
            m_StateBadge.anchorMin = new Vector2(0.0f, 1.0f);
            m_StateBadge.anchorMax = new Vector2(0.0f, 1.0f);
            m_StateBadge.pivot = new Vector2(0.0f, 1.0f);
            m_StateBadge.anchoredPosition = new Vector2(28.0f, -28.0f);
            m_StateBadge.sizeDelta = new Vector2(420.0f, 68.0f);
            var background = badgeObject.AddComponent<Image>();
            background.color = new Color(0.01f, 0.05f, 0.075f, 0.90f);
            m_StateBadgeOutline = badgeObject.AddComponent<Outline>();
            m_StateBadgeOutline.effectDistance = new Vector2(3.0f, -3.0f);
            badgeObject.AddComponent<Manual2ARRevealMotion>();

            var textObject = new GameObject("State Badge Text");
            textObject.transform.SetParent(m_StateBadge, false);
            var textRect = textObject.AddComponent<RectTransform>();
            Stretch(textRect);
            textRect.offsetMin = new Vector2(22.0f, 0.0f);
            textRect.offsetMax = new Vector2(-14.0f, 0.0f);
            m_StateBadgeText = textObject.AddComponent<Text>();
            Manual2ARVisualTheme.StyleText(
                m_StateBadgeText, 25, Manual2ARVisualTheme.TargetLabel, TextAnchor.MiddleLeft);
            Manual2ARVisualTheme.AddTextDepth(textObject, 2.0f);
        }

        void CreateBottomBanner(Transform root)
        {
            var bannerObject = new GameObject("Plate Inspection Live Tracking Banner");
            bannerObject.transform.SetParent(root, false);
            m_BottomBanner = bannerObject.AddComponent<RectTransform>();
            m_BottomBanner.anchorMin = new Vector2(0.5f, 0.0f);
            m_BottomBanner.anchorMax = new Vector2(0.5f, 0.0f);
            m_BottomBanner.pivot = new Vector2(0.5f, 0.0f);
            m_BottomBanner.anchoredPosition = new Vector2(0.0f, 34.0f);
            m_BottomBanner.sizeDelta = new Vector2(1040.0f, 74.0f);
            var background = bannerObject.AddComponent<Image>();
            background.color = new Color(0.01f, 0.05f, 0.075f, 0.90f);
            m_BottomBannerOutline = bannerObject.AddComponent<Outline>();
            m_BottomBannerOutline.effectDistance = new Vector2(3.0f, -3.0f);
            bannerObject.AddComponent<Manual2ARRevealMotion>();

            var textObject = new GameObject("Live Tracking Text");
            textObject.transform.SetParent(m_BottomBanner, false);
            var textRect = textObject.AddComponent<RectTransform>();
            Stretch(textRect);
            m_BottomBannerText = textObject.AddComponent<Text>();
            Manual2ARVisualTheme.StyleText(
                m_BottomBannerText, 28, Manual2ARVisualTheme.TargetLabel, TextAnchor.MiddleCenter);
            Manual2ARVisualTheme.AddTextDepth(textObject, 2.0f);
        }

        void SetFrameStyle(string badge, string banner, Color panelColor, Color bannerColor)
        {
            m_StateBadgeText.text = badge;
            m_StateBadgeText.color = Manual2ARVisualTheme.TargetLabel;
            m_StateBadgeOutline.effectColor = new Color(
                Manual2ARVisualTheme.TargetCyan.r,
                Manual2ARVisualTheme.TargetCyan.g,
                Manual2ARVisualTheme.TargetCyan.b,
                0.90f);
            m_PanelOutline.effectColor = new Color(panelColor.r, panelColor.g, panelColor.b, 0.92f);
            m_BottomBannerText.text = banner;
            m_BottomBannerText.color = bannerColor;
            m_BottomBannerOutline.effectColor = new Color(
                bannerColor.r, bannerColor.g, bannerColor.b, 0.92f);
        }

        static Text CreateText(
            RectTransform parent,
            string name,
            float x,
            float y,
            int fontSize,
            TextAnchor alignment)
        {
            var go = new GameObject(name);
            go.transform.SetParent(parent, false);
            var rect = go.AddComponent<RectTransform>();
            rect.anchorMin = new Vector2(0.5f, 0.5f);
            rect.anchorMax = new Vector2(0.5f, 0.5f);
            rect.pivot = new Vector2(0.5f, 0.5f);
            rect.anchoredPosition = new Vector2(x, y);
            rect.sizeDelta = new Vector2(450.0f, 55.0f);
            var text = go.AddComponent<Text>();
            Manual2ARVisualTheme.StyleText(text, fontSize, Color.white, alignment);
            Manual2ARVisualTheme.AddTextDepth(go, 3.0f);
            return text;
        }

        void PositionMaskLabel(MaskLayer layer)
        {
            if (m_CameraContent == null || layer.label == null ||
                layer.trackedBox == null || layer.trackedBox.Length < 4)
                return;
            var rect = m_CameraContent.rect;
            var x1 = rect.xMin + rect.width * layer.trackedBox[0] / 1000.0f;
            var x2 = rect.xMin + rect.width * layer.trackedBox[2] / 1000.0f;
            var y1 = rect.yMax - rect.height * layer.trackedBox[1] / 1000.0f;
            var y2 = rect.yMax - rect.height * layer.trackedBox[3] / 1000.0f;
            var topLeft = m_CameraContent.TransformPoint(new Vector3(x1, y1, 0.0f));
            var topRight = m_CameraContent.TransformPoint(new Vector3(x2, y1, 0.0f));
            var bottomLeft = m_CameraContent.TransformPoint(new Vector3(x1, y2, 0.0f));
            var bottomRight = m_CameraContent.TransformPoint(new Vector3(x2, y2, 0.0f));
            var minX = Mathf.Min(topLeft.x, topRight.x, bottomLeft.x, bottomRight.x);
            var maxX = Mathf.Max(topLeft.x, topRight.x, bottomLeft.x, bottomRight.x);
            var maxY = Mathf.Max(topLeft.y, topRight.y, bottomLeft.y, bottomRight.y);
            layer.label.rectTransform.position = new Vector3((minX + maxX) * 0.5f, maxY + 32.0f, 0.0f);
            layer.label.rectTransform.rotation = Quaternion.identity;
            layer.label.rectTransform.localScale = Vector3.one;
        }

        static bool IsAnomaly(string objectType)
        {
            return objectType == "foreign_object" || objectType == "residue";
        }

        static string LabelForObjectType(string objectType)
        {
            switch (objectType)
            {
                case "build_plate": return "BUILD PLATE";
                case "foreign_object": return "FOREIGN OBJECT";
                case "residue": return "RESIDUE";
                default: return objectType.Replace('_', ' ').ToUpperInvariant();
            }
        }

        void PositionPanel()
        {
            if (m_Panel == null || m_CameraContent == null || m_PlateBox == null || m_PlateBox.Length < 4)
                return;
            var plateCenterX = (m_PlateBox[0] + m_PlateBox[2]) * 0.5f;
            var useRightSide = plateCenterX < 500.0f;
            m_Panel.anchorMin = new Vector2(useRightSide ? 1.0f : 0.0f, 0.5f);
            m_Panel.anchorMax = m_Panel.anchorMin;
            m_Panel.pivot = new Vector2(useRightSide ? 1.0f : 0.0f, 0.5f);
            m_Panel.anchoredPosition = new Vector2(useRightSide ? -42.0f : 42.0f, -18.0f);
        }

        static bool PredicatePassed(BuildPlateInspectionResponse response, string predicateId)
        {
            if (response.predicates == null)
                return false;
            foreach (var predicate in response.predicates)
                if (predicate != null && predicate.predicate_id == predicateId)
                    return predicate.passed;
            return false;
        }

        static void SetRow(Text row, bool passed, string label)
        {
            row.text = passed ? $"✓  {label}" : $"✕  {label}";
            row.color = passed
                ? Manual2ARVisualTheme.SuccessGreen
                : Manual2ARVisualTheme.ErrorRed;
        }

        static string JoinActions(string[] actions)
        {
            if (actions == null || actions.Length == 0)
                return "RE-INSPECT BEFORE PRINTING";
            return string.Join("\n", actions);
        }

        static void Stretch(RectTransform rect)
        {
            rect.anchorMin = Vector2.zero;
            rect.anchorMax = Vector2.one;
            rect.offsetMin = Vector2.zero;
            rect.offsetMax = Vector2.zero;
        }

        void OnDestroy()
        {
            foreach (var layer in m_Layers.Values)
                if (layer.texture != null)
                    Destroy(layer.texture);
        }
    }
}
