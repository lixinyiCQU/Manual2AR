using System;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UI;

namespace Manual2AR
{
    /// <summary>
    /// Unified filament guidance and verification overlay. Masks share the oriented camera transform;
    /// labels, panel and arrow stay upright in screen space. The arrow endpoint
    /// is derived from the inlet relative to the tracked feeder, never fixed.
    /// </summary>
    public sealed class FilamentLoadingGuidanceOverlay : MonoBehaviour
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
        Text m_Headline;
        Text m_RowOne;
        Text m_RowTwo;
        Text m_RowThree;
        Text m_Action;
        RectTransform m_StateBadge;
        Text m_StateBadgeText;
        Outline m_StateBadgeOutline;
        RectTransform m_BottomBanner;
        Text m_BottomBannerText;
        Outline m_BottomBannerOutline;
        RectTransform m_ArrowRoot;
        int[] m_InitialFeederBox;
        int[] m_CurrentFeederBox;
        int[] m_InletPoint;
        string m_State = "uncertain";

        public void Initialize(RectTransform cameraContent, Transform screenUiRoot)
        {
            m_CameraContent = cameraContent;
            m_ScreenUiRoot = screenUiRoot;
            CreatePanel(screenUiRoot);
            CreateStateBadge(screenUiRoot);
            CreateBottomBanner(screenUiRoot);
            CreateArrow(screenUiRoot);
            Clear();
        }

        public bool ShowMask(
            string objectId,
            string objectType,
            TrackedComponent tracked,
            string loadingState,
            out string error)
        {
            error = null;
            if (tracked == null || tracked.status != "tracking" || tracked.requires_redetection ||
                !tracked.mask_quality_passed || tracked.quality < 0.45f ||
                string.IsNullOrWhiteSpace(tracked.overlay_png_base64))
            {
                error = "current mask failed the Unity filament quality gate";
                return false;
            }

            try
            {
                var layer = EnsureLayer(objectId, objectType);
                var png = Convert.FromBase64String(tracked.overlay_png_base64);
                if (!ImageConversion.LoadImage(layer.texture, png, false))
                    throw new InvalidOperationException("Unity could not decode the current SAM mask");
                RecolorMask(layer.texture, objectType, loadingState);
                layer.image.texture = layer.texture;
                layer.image.gameObject.SetActive(true);
                layer.label.text = LabelForObjectType(objectType);
                layer.label.color = LabelColor(objectType, loadingState);
                layer.label.gameObject.SetActive(true);
                layer.trackedBox = tracked.bbox_0_1000;
                layer.objectType = objectType;
                if (objectType == "feeder_module")
                    m_CurrentFeederBox = tracked.bbox_0_1000;
                m_State = loadingState;
                PositionMaskLabel(layer);
                PositionPanel();
                PositionArrow();
                return true;
            }
            catch (Exception exception)
            {
                error = exception.Message;
                return false;
            }
        }

        public void SetInspectionState(FilamentLoadingInspectionResponse response)
        {
            if (response == null || response.status == "uncertain")
            {
                ShowUncertain();
                return;
            }
            m_State = response.status;
            m_InitialFeederBox = response.feeder_module?.bbox_0_1000;
            m_InletPoint = response.filament_inlet?.target_point_0_1000;
            if (m_CurrentFeederBox == null)
                m_CurrentFeederBox = m_InitialFeederBox;

            if (response.status == "loaded")
            {
                SetRow(m_RowOne, true, "FILAMENT ENTERED FEEDER UNIT");
                SetRow(m_RowTwo, true, "FILAMENT VISIBLE IN PTFE");
                SetRow(m_RowThree, true, "LOADING VERIFIED");
                m_Headline.text = "FILAMENT LOADED";
                m_Headline.color = Manual2ARVisualTheme.SuccessGreen;
                m_Action.text = "FEEDER + PTFE PATH VERIFIED";
                m_Action.color = Manual2ARVisualTheme.TargetLabel;
                SetFrameStyle(
                    "VERIFIED STATE",
                    "FILAMENT LOADED · LIVE TRACKING",
                    Manual2ARVisualTheme.TargetCyan,
                    Manual2ARVisualTheme.SuccessGreen);
                m_ArrowRoot.gameObject.SetActive(false);
            }
            else
            {
                SetRow(m_RowOne, false, "FILAMENT NOT IN INLET");
                SetDirectionalRow(m_RowTwo, "↑  ALIGN FILAMENT END WITH INLET");
                SetDirectionalRow(m_RowThree, "↑  FEED FILAMENT INTO INLET");
                m_Headline.text = "FILAMENT NOT INSERTED";
                m_Headline.color = Manual2ARVisualTheme.ErrorRed;
                m_Action.text = "FEED FILAMENT UPWARD";
                m_Action.color = Manual2ARVisualTheme.TargetCyan;
                SetFrameStyle(
                    "GUIDANCE STATE",
                    "FEED FILAMENT UPWARD · LIVE TRACKING",
                    Manual2ARVisualTheme.ErrorRed,
                    Manual2ARVisualTheme.ErrorRed);
                m_ArrowRoot.gameObject.SetActive(true);
            }
            m_Panel.gameObject.SetActive(true);
            m_StateBadge.gameObject.SetActive(true);
            m_BottomBanner.gameObject.SetActive(true);
            PositionPanel();
            PositionArrow();
        }

        public void ShowUncertain()
        {
            Clear();
            m_Headline.text = "LOADING STATE UNCERTAIN";
            m_Headline.color = new Color(1.0f, 0.64f, 0.32f, 1.0f);
            SetDirectionalRow(m_RowOne, "!  SHOW FEEDER + LOWER INLET");
            SetDirectionalRow(m_RowTwo, "!  SHOW FILAMENT TIP");
            SetDirectionalRow(m_RowThree, "!  SHOW UPPER PTFE TUBE");
            m_Action.text = "REFRAME AND CHECK AGAIN";
            m_Action.color = new Color(1.0f, 0.76f, 0.46f, 1.0f);
            SetFrameStyle(
                "STATE UNCERTAIN",
                "REFRAME · RE-CHECK REQUIRED",
                new Color(1.0f, 0.64f, 0.32f, 1.0f),
                new Color(1.0f, 0.64f, 0.32f, 1.0f));
            PlacePanelAtRight();
            m_Panel.gameObject.SetActive(true);
            m_StateBadge.gameObject.SetActive(true);
            m_BottomBanner.gameObject.SetActive(true);
        }

        public void ShowProcessing()
        {
            Clear();
            m_Headline.text = "ANALYZING CURRENT FRAME";
            m_Headline.color = Manual2ARVisualTheme.TargetCyan;
            SetDirectionalRow(m_RowOne, "1  QWEN LOADING-STATE GROUNDING");
            SetDirectionalRow(m_RowTwo, "2  SAM2 FEEDER + FILAMENT MASKS");
            SetDirectionalRow(m_RowThree, "3  STATE AND TRACKING GATES");
            m_Action.text = "PLEASE WAIT";
            m_Action.color = Manual2ARVisualTheme.TargetLabel;
            SetFrameStyle(
                "ANALYZING",
                "QWEN3-VL-FLASH + SAM2 · PLEASE WAIT",
                Manual2ARVisualTheme.TargetCyan,
                Manual2ARVisualTheme.TargetCyan);
            PlacePanelAtRight();
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
            m_InitialFeederBox = null;
            m_CurrentFeederBox = null;
            m_InletPoint = null;
            m_State = "uncertain";
            if (m_Panel != null)
                m_Panel.gameObject.SetActive(false);
            if (m_ArrowRoot != null)
                m_ArrowRoot.gameObject.SetActive(false);
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
            if (m_ArrowRoot != null && m_ArrowRoot.gameObject.activeSelf)
                PositionArrow();
        }

        MaskLayer EnsureLayer(string objectId, string objectType)
        {
            if (m_Layers.TryGetValue(objectId, out var existing))
                return existing;
            var go = new GameObject($"{objectId} Current Filament Mask");
            go.transform.SetParent(m_CameraContent, false);
            var rect = go.AddComponent<RectTransform>();
            Stretch(rect);
            var rawImage = go.AddComponent<RawImage>();
            rawImage.raycastTarget = false;
            rawImage.color = Color.white;
            go.AddComponent<Manual2ARRevealMotion>().Configure(false);

            var labelObject = new GameObject($"{objectId} Filament Label");
            labelObject.transform.SetParent(m_ScreenUiRoot, false);
            var labelRect = labelObject.AddComponent<RectTransform>();
            labelRect.anchorMin = new Vector2(0.5f, 0.5f);
            labelRect.anchorMax = new Vector2(0.5f, 0.5f);
            labelRect.pivot = new Vector2(0.5f, 0.5f);
            labelRect.sizeDelta = new Vector2(500.0f, 58.0f);
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
                    name = $"Manual2AR {objectId} Filament Mask"
                },
                label = label,
                objectType = objectType
            };
            m_Layers.Add(objectId, layer);
            layer.image.gameObject.SetActive(false);
            layer.label.gameObject.SetActive(false);
            return layer;
        }

        static void RecolorMask(Texture2D texture, string objectType, string loadingState)
        {
            Color32 target;
            if (objectType == "feeder_module")
                target = new Color32(10, 225, 245, 94);
            else if (loadingState == "loaded")
                target = new Color32(44, 255, 148, 205);
            else
                target = new Color32(255, 40, 24, 220);
            Manual2ARVisualTheme.RecolorMask(texture, target);
        }

        static Color LabelColor(string objectType, string loadingState)
        {
            if (objectType == "feeder_module")
                return Manual2ARVisualTheme.TargetLabel;
            return loadingState == "loaded"
                ? Manual2ARVisualTheme.SuccessGreen
                : Manual2ARVisualTheme.ErrorRed;
        }

        void CreatePanel(Transform root)
        {
            var panelObject = new GameObject("Filament Loading State Panel");
            panelObject.transform.SetParent(root, false);
            m_Panel = panelObject.AddComponent<RectTransform>();
            m_Panel.anchorMin = new Vector2(0.0f, 0.5f);
            m_Panel.anchorMax = new Vector2(0.0f, 0.5f);
            m_Panel.pivot = new Vector2(0.0f, 0.5f);
            m_Panel.sizeDelta = new Vector2(590.0f, 410.0f);
            var background = panelObject.AddComponent<Image>();
            background.color = Manual2ARVisualTheme.PanelBackground;
            m_PanelOutline = panelObject.AddComponent<Outline>();
            m_PanelOutline.effectColor = new Color(0.04f, 0.82f, 0.92f, 0.9f);
            m_PanelOutline.effectDistance = new Vector2(4.0f, -4.0f);
            panelObject.AddComponent<Manual2ARRevealMotion>();

            m_Headline = CreateText(m_Panel, "Headline", 128.0f, Manual2ARVisualTheme.HeadlineFontSize, TextAnchor.MiddleCenter);
            m_RowOne = CreateText(m_Panel, "Feeder State", 55.0f, 25, TextAnchor.MiddleLeft);
            m_RowTwo = CreateText(m_Panel, "Insertion State", -3.0f, 25, TextAnchor.MiddleLeft);
            m_RowThree = CreateText(m_Panel, "PTFE State", -61.0f, 25, TextAnchor.MiddleLeft);
            m_Action = CreateText(m_Panel, "Primary Action", -140.0f, Manual2ARVisualTheme.PrimaryInstructionFontSize, TextAnchor.MiddleCenter);
            m_Action.rectTransform.sizeDelta = new Vector2(540.0f, 82.0f);
            m_Action.horizontalOverflow = HorizontalWrapMode.Wrap;
        }

        void CreateStateBadge(Transform root)
        {
            var badgeObject = new GameObject("Filament State Badge");
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
            var bannerObject = new GameObject("Filament Live Tracking Banner");
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

        void CreateArrow(Transform root)
        {
            var arrowObject = new GameObject("Tracked Upward Filament Arrow");
            arrowObject.transform.SetParent(root, false);
            m_ArrowRoot = arrowObject.AddComponent<RectTransform>();
            m_ArrowRoot.anchorMin = new Vector2(0.5f, 0.5f);
            m_ArrowRoot.anchorMax = new Vector2(0.5f, 0.5f);
            m_ArrowRoot.pivot = new Vector2(0.5f, 1.0f);
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
            m_ArrowRoot.gameObject.SetActive(false);
        }

        static Text CreateText(
            RectTransform parent,
            string name,
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
            rect.anchoredPosition = new Vector2(0.0f, y);
            rect.sizeDelta = new Vector2(530.0f, 58.0f);
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
            var topCenter = CameraPointToWorld(new[]
            {
                (layer.trackedBox[0] + layer.trackedBox[2]) / 2,
                layer.trackedBox[1]
            });
            layer.label.rectTransform.position = new Vector3(topCenter.x, topCenter.y + 34.0f, 0.0f);
            layer.label.rectTransform.rotation = Quaternion.identity;
            layer.label.rectTransform.localScale = Vector3.one;
        }

        void PositionArrow()
        {
            if (m_ArrowRoot == null || m_State != "not_inserted" ||
                m_InitialFeederBox == null || m_CurrentFeederBox == null ||
                m_InletPoint == null || m_InitialFeederBox.Length < 4 ||
                m_CurrentFeederBox.Length < 4 || m_InletPoint.Length < 2)
            {
                if (m_ArrowRoot != null)
                    m_ArrowRoot.gameObject.SetActive(false);
                return;
            }
            var initialWidth = Mathf.Max(1.0f, m_InitialFeederBox[2] - m_InitialFeederBox[0]);
            var initialHeight = Mathf.Max(1.0f, m_InitialFeederBox[3] - m_InitialFeederBox[1]);
            var relativeX = (m_InletPoint[0] - m_InitialFeederBox[0]) / initialWidth;
            var relativeY = (m_InletPoint[1] - m_InitialFeederBox[1]) / initialHeight;
            // The backend compiles this point onto the actual lower insertion
            // boundary. Preserve that semantic anchor instead of borrowing the
            // loose tip position, which can be far away from the inlet.
            relativeX = Mathf.Clamp(relativeX, 0.02f, 0.98f);
            relativeY = Mathf.Clamp(relativeY, 0.72f, 1.02f);
            var trackedPoint = new[]
            {
                Mathf.RoundToInt(Mathf.Lerp(m_CurrentFeederBox[0], m_CurrentFeederBox[2], relativeX)),
                Mathf.RoundToInt(Mathf.Lerp(m_CurrentFeederBox[1], m_CurrentFeederBox[3], relativeY))
            };
            var worldPoint = CameraPointToWorld(trackedPoint);
            m_ArrowRoot.position = new Vector3(worldPoint.x, worldPoint.y + 20.0f, 0.0f);
            m_ArrowRoot.rotation = Quaternion.identity;
            m_ArrowRoot.localScale = Vector3.one;
            m_ArrowRoot.gameObject.SetActive(true);
        }

        Vector3 CameraPointToWorld(int[] point)
        {
            var rect = m_CameraContent.rect;
            var x = rect.xMin + rect.width * point[0] / 1000.0f;
            var y = rect.yMax - rect.height * point[1] / 1000.0f;
            return m_CameraContent.TransformPoint(new Vector3(x, y, 0.0f));
        }

        void PositionPanel()
        {
            if (m_Panel == null || !m_Panel.gameObject.activeSelf)
                return;
            var feederCenterX = m_CurrentFeederBox != null && m_CurrentFeederBox.Length >= 4
                ? (m_CurrentFeederBox[0] + m_CurrentFeederBox[2]) * 0.5f
                : 350.0f;
            var useRightSide = feederCenterX < 500.0f;
            m_Panel.anchorMin = new Vector2(useRightSide ? 1.0f : 0.0f, 0.5f);
            m_Panel.anchorMax = m_Panel.anchorMin;
            m_Panel.pivot = new Vector2(useRightSide ? 1.0f : 0.0f, 0.5f);
            m_Panel.anchoredPosition = new Vector2(useRightSide ? -42.0f : 42.0f, -18.0f);
        }

        void PlacePanelAtRight()
        {
            m_Panel.anchorMin = new Vector2(1.0f, 0.5f);
            m_Panel.anchorMax = m_Panel.anchorMin;
            m_Panel.pivot = new Vector2(1.0f, 0.5f);
            m_Panel.anchoredPosition = new Vector2(-42.0f, -18.0f);
        }

        static void SetRow(Text row, bool passed, string label)
        {
            row.text = passed ? $"✓  {label}" : $"✕  {label}";
            row.color = passed
                ? Manual2ARVisualTheme.SuccessGreen
                : Manual2ARVisualTheme.ErrorRed;
        }

        static void SetDirectionalRow(Text row, string label)
        {
            row.text = label;
            row.color = Manual2ARVisualTheme.TargetLabel;
        }

        static string LabelForObjectType(string objectType)
        {
            switch (objectType)
            {
                case "feeder_module": return "AMS LITE FEEDER UNIT";
                case "filament_tip": return "FREE FILAMENT END";
                case "inserted_filament": return "FILAMENT ENTRY";
                case "ptfe_filament": return "FILAMENT IN PTFE TUBE";
                default: return objectType.Replace('_', ' ').ToUpperInvariant();
            }
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
