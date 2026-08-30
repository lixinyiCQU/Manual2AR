using System.Collections.Generic;
using TMPro;
using UnityEngine;
using UnityEngine.EventSystems;
using UnityEngine.UI;

namespace Manual2AR
{
    /// <summary>A single launcher for the Manual2AR recording demos.</summary>
    public sealed class Manual2ARDemoHubController : MonoBehaviour
    {
        readonly Dictionary<Manual2ARCameraMode, Button> m_CameraButtons =
            new Dictionary<Manual2ARCameraMode, Button>();
        TextMeshProUGUI m_CameraStatus;

        void Awake()
        {
            if (EventSystem.current == null)
            {
                var eventSystem = new GameObject("EventSystem");
                eventSystem.AddComponent<EventSystem>();
                eventSystem.AddComponent<StandaloneInputModule>();
            }

            var canvasObject = new GameObject("Manual2AR Demo Hub UI");
            var canvas = canvasObject.AddComponent<Canvas>();
            canvas.renderMode = RenderMode.ScreenSpaceOverlay;
            canvas.pixelPerfect = true;
            var scaler = canvasObject.AddComponent<CanvasScaler>();
            scaler.uiScaleMode = CanvasScaler.ScaleMode.ScaleWithScreenSize;
            scaler.referenceResolution = new Vector2(1920.0f, 1080.0f);
            scaler.matchWidthOrHeight = 0.5f;
            canvasObject.AddComponent<GraphicRaycaster>();

            var backgroundObject = new GameObject("Background");
            backgroundObject.transform.SetParent(canvasObject.transform, false);
            var backgroundRect = backgroundObject.AddComponent<RectTransform>();
            backgroundRect.anchorMin = Vector2.zero;
            backgroundRect.anchorMax = Vector2.one;
            backgroundRect.offsetMin = Vector2.zero;
            backgroundRect.offsetMax = Vector2.zero;
            var background = backgroundObject.AddComponent<Image>();
            background.color = new Color(0.006f, 0.025f, 0.04f, 1.0f);

            CreateText(canvasObject.transform, "Title", new Vector2(0.5f, 1.0f),
                new Vector2(0.0f, -92.0f), new Vector2(1500.0f, 70.0f),
                "LOADING & PRINTING", 42,
                Manual2ARVisualTheme.TargetLabel);
            CreateText(canvasObject.transform, "Subtitle", new Vector2(0.5f, 1.0f),
                new Vector2(0.0f, -148.0f), new Vector2(1500.0f, 46.0f),
                "4 VISUAL GUIDANCE MODULES · 6 DEMONSTRATION RESULTS", 25,
                new Color(0.55f, 0.78f, 0.84f, 1.0f));

            CreateWorkflowBackButton(canvasObject.transform);

            CreateCameraSelector(canvasObject.transform);

            CreateFeatureCard(canvasObject.transform, new Vector2(-430.0f, 95.0f),
                "FIGURE 1", "COMPONENT RECOGNITION",
                "IDENTIFY THE BUILD PLATE, FILAMENT SPOOL AND EMPTY SPOOL HOLDER",
                "ComponentOverviewTracking", true);
            CreateFeatureCard(canvasObject.transform, new Vector2(430.0f, 95.0f),
                "FIGURE 2", "GUIDED SPOOL PLACEMENT",
                "LOCATE THE EMPTY HOLDER AND GUIDE SPOOL PLACEMENT",
                "EmptySpindleTracking", true);
            CreateFeatureCard(canvasObject.transform, new Vector2(-430.0f, -215.0f),
                "FIGURES 3–4", "FILAMENT GUIDANCE & VERIFICATION",
                "GUIDE FILAMENT INSERTION AND VERIFY SUCCESSFUL LOADING",
                "FilamentLoadingGuidance", true);
            CreateFeatureCard(canvasObject.transform, new Vector2(430.0f, -215.0f),
                "FIGURES 5–6", "PRE-PRINT INSPECTION & CORRECTION",
                "INSPECT THE BUILD PLATE AND PROVIDE CORRECTIVE GUIDANCE",
                "PrePrintPlateInspection", true);

            CreateText(canvasObject.transform, "Footer", new Vector2(0.5f, 0.0f),
                new Vector2(0.0f, 54.0f), new Vector2(1600.0f, 48.0f),
                "SELECT A MODULE TO OPEN ITS LIVE FEATURE SCENE",
                20, new Color(0.55f, 0.78f, 0.84f, 1.0f));
        }

        static void CreateWorkflowBackButton(Transform parent)
        {
            var go = new GameObject("Back To Task Button");
            go.transform.SetParent(parent, false);
            var rect = go.AddComponent<RectTransform>();
            rect.anchorMin = new Vector2(0.0f, 1.0f);
            rect.anchorMax = new Vector2(0.0f, 1.0f);
            rect.pivot = new Vector2(0.0f, 1.0f);
            rect.anchoredPosition = new Vector2(30.0f, -30.0f);
            rect.sizeDelta = new Vector2(218.0f, 52.0f);
            var image = go.AddComponent<Image>();
            image.color = Manual2ARVisualTheme.ButtonBackground;
            var button = go.AddComponent<Button>();
            button.onClick.AddListener(Manual2ARSceneNavigation.LoadWorkflowTask);
            CreateText(go.transform, "Text", new Vector2(0.5f, 0.5f), Vector2.zero,
                new Vector2(204.0f, 44.0f), "←  BACK TO TASK", 16, Color.white);
        }

        void CreateCameraSelector(Transform parent)
        {
            var panelObject = new GameObject("Camera Source Selector");
            panelObject.transform.SetParent(parent, false);
            var panelRect = panelObject.AddComponent<RectTransform>();
            panelRect.anchorMin = new Vector2(0.5f, 0.5f);
            panelRect.anchorMax = new Vector2(0.5f, 0.5f);
            panelRect.anchoredPosition = new Vector2(0.0f, 307.0f);
            panelRect.sizeDelta = new Vector2(1660.0f, 92.0f);
            var panelImage = panelObject.AddComponent<Image>();
            panelImage.color = new Color(0.015f, 0.075f, 0.095f, 0.92f);

            CreateText(panelObject.transform, "Camera Source Label", new Vector2(0.0f, 0.5f),
                new Vector2(112.0f, 12.0f), new Vector2(205.0f, 38.0f),
                "CAMERA SOURCE", 19, Manual2ARVisualTheme.TargetLabel);

            CreateCameraButton(panelRect, Manual2ARCameraMode.Auto, -480.0f, "AUTO");
            CreateCameraButton(panelRect, Manual2ARCameraMode.MacBuiltIn, -205.0f, "MAC BUILT-IN");
            CreateCameraButton(panelRect, Manual2ARCameraMode.External, 70.0f, "EXTERNAL CAMERA");
            CreateCameraButton(panelRect, Manual2ARCameraMode.IPhoneContinuity, 345.0f, "IPHONE CONTINUITY");

            m_CameraStatus = CreateText(
                panelObject.transform,
                "Camera Selection Status",
                new Vector2(0.5f, 0.0f),
                new Vector2(110.0f, 6.0f),
                new Vector2(1380.0f, 32.0f),
                string.Empty,
                15,
                new Color(0.64f, 0.84f, 0.88f, 1.0f));
            UpdateCameraSelection();
        }

        void CreateCameraButton(
            RectTransform parent,
            Manual2ARCameraMode cameraMode,
            float x,
            string labelText)
        {
            var go = new GameObject($"{labelText} Camera Button");
            go.transform.SetParent(parent, false);
            var rect = go.AddComponent<RectTransform>();
            rect.anchorMin = new Vector2(0.5f, 0.5f);
            rect.anchorMax = new Vector2(0.5f, 0.5f);
            rect.anchoredPosition = new Vector2(x, 12.0f);
            rect.sizeDelta = new Vector2(252.0f, 42.0f);
            var image = go.AddComponent<Image>();
            image.color = Manual2ARVisualTheme.ButtonBackground;
            var button = go.AddComponent<Button>();
            var capturedMode = cameraMode;
            button.onClick.AddListener(() =>
            {
                Manual2ARCameraSelection.SetMode(capturedMode);
                UpdateCameraSelection();
            });
            m_CameraButtons[cameraMode] = button;
            CreateText(go.transform, "Text", new Vector2(0.5f, 0.5f), Vector2.zero,
                new Vector2(238.0f, 42.0f), labelText, 16, Color.white);
        }

        void UpdateCameraSelection()
        {
            var devices = WebCamTexture.devices;
            var selectedMode = Manual2ARCameraSelection.mode;
            foreach (var pair in m_CameraButtons)
            {
                var selected = pair.Key == selectedMode;
                var available = Manual2ARCameraSelection.IsAvailable(pair.Key, devices);
                var image = pair.Value.GetComponent<Image>();
                image.color = selected
                    ? new Color(0.02f, 0.46f, 0.56f, 1.0f)
                    : available
                        ? Manual2ARVisualTheme.ButtonBackground
                        : new Color(0.08f, 0.11f, 0.12f, 0.92f);
                var outline = pair.Value.GetComponent<Outline>();
                if (outline == null)
                    outline = pair.Value.gameObject.AddComponent<Outline>();
                outline.effectColor = selected
                    ? Manual2ARVisualTheme.SuccessGreen
                    : new Color(0.12f, 0.32f, 0.35f, 0.8f);
                outline.effectDistance = new Vector2(2.0f, -2.0f);
            }

            if (Manual2ARCameraSelection.TryResolve(devices, out _, out _))
            {
                m_CameraStatus.text = $"SELECTED: {Manual2ARCameraSelection.ModeLabel(selectedMode)}";
                m_CameraStatus.color = Manual2ARVisualTheme.SuccessGreen;
            }
            else
            {
                m_CameraStatus.text = $"{Manual2ARCameraSelection.ModeLabel(selectedMode)} NOT CONNECTED · " +
                    "SELECT AUTO OR CONNECT THE REQUESTED SOURCE";
                m_CameraStatus.color = new Color(1.0f, 0.64f, 0.42f, 1.0f);
            }
        }

        static void CreateFeatureCard(
            Transform parent,
            Vector2 position,
            string category,
            string title,
            string detail,
            string sceneName,
            bool enabled)
        {
            var go = new GameObject($"{category} {title}");
            go.transform.SetParent(parent, false);
            var rect = go.AddComponent<RectTransform>();
            rect.anchorMin = new Vector2(0.5f, 0.5f);
            rect.anchorMax = new Vector2(0.5f, 0.5f);
            rect.anchoredPosition = position;
            rect.sizeDelta = new Vector2(760.0f, 270.0f);
            var image = go.AddComponent<Image>();
            image.color = enabled
                ? Manual2ARVisualTheme.PanelBackground
                : new Color(0.035f, 0.055f, 0.065f, 0.92f);
            var outline = go.AddComponent<Outline>();
            outline.effectColor = enabled
                ? new Color(0.04f, 0.82f, 0.92f, 0.95f)
                : new Color(0.25f, 0.32f, 0.34f, 0.8f);
            outline.effectDistance = new Vector2(4.0f, -4.0f);
            var button = go.AddComponent<Button>();
            button.interactable = enabled;
            if (enabled)
            {
                var capturedScene = sceneName;
                button.onClick.AddListener(() => Manual2ARSceneNavigation.Load(capturedScene));
            }

            CreateText(go.transform, "Mode", new Vector2(0.5f, 0.5f),
                new Vector2(0.0f, 78.0f), new Vector2(650.0f, 42.0f),
                category, 24, enabled ? Manual2ARVisualTheme.TargetCyan : Color.gray);
            var featureTitle = CreateText(go.transform, "Feature", new Vector2(0.5f, 0.5f),
                new Vector2(0.0f, 16.0f), new Vector2(730.0f, 58.0f),
                title, 33, Color.white);
            featureTitle.enableAutoSizing = true;
            featureTitle.fontSizeMin = 20.0f;
            featureTitle.fontSizeMax = 33.0f;
            CreateText(go.transform, "Detail", new Vector2(0.5f, 0.5f),
                new Vector2(0.0f, -60.0f), new Vector2(690.0f, 70.0f),
                detail, 21, enabled ? new Color(0.66f, 0.87f, 0.91f, 1.0f) : Color.gray);
        }

        static TextMeshProUGUI CreateText(
            Transform parent,
            string name,
            Vector2 anchor,
            Vector2 position,
            Vector2 size,
            string value,
            int fontSize,
            Color color)
        {
            var go = new GameObject(name);
            go.transform.SetParent(parent, false);
            var rect = go.AddComponent<RectTransform>();
            rect.anchorMin = anchor;
            rect.anchorMax = anchor;
            rect.pivot = new Vector2(0.5f, 0.5f);
            rect.anchoredPosition = position;
            rect.sizeDelta = size;
            var text = go.AddComponent<TextMeshProUGUI>();
            text.text = value;
            text.fontSize = Mathf.Max(20, fontSize);
            text.fontStyle = fontSize >= 22 ? FontStyles.Bold : FontStyles.Normal;
            text.alignment = TextAlignmentOptions.Center;
            text.color = color;
            text.enableWordWrapping = true;
            text.overflowMode = TextOverflowModes.Truncate;
            text.raycastTarget = false;
            if (TMP_Settings.defaultFontAsset != null)
                text.font = TMP_Settings.defaultFontAsset;
            return text;
        }
    }
}
