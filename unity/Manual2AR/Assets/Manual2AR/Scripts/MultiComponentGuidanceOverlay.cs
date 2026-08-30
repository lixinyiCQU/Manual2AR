using System;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UI;

namespace Manual2AR
{
    /// <summary>
    /// Renders independent current-frame SAM masks in camera-pixel space and
    /// keeps each English label upright in screen space above its tracked mask.
    /// This is image-space tracking for the Mac demo, not a world-space anchor.
    /// </summary>
    public sealed class MultiComponentGuidanceOverlay : MonoBehaviour
    {
        sealed class Layer
        {
            public RawImage mask;
            public Texture2D texture;
            public Text label;
            public int[] box;
        }

        readonly Dictionary<string, Layer> m_Layers = new Dictionary<string, Layer>();
        RectTransform m_CameraContent;
        Transform m_ScreenUiRoot;

        public int visibleCount
        {
            get
            {
                var count = 0;
                foreach (var layer in m_Layers.Values)
                    if (layer.mask != null && layer.mask.gameObject.activeSelf)
                        count++;
                return count;
            }
        }

        public void Initialize(RectTransform cameraContent, Transform screenUiRoot)
        {
            m_CameraContent = cameraContent;
            m_ScreenUiRoot = screenUiRoot;
        }

        public bool Show(
            string componentId,
            string englishLabel,
            TrackedComponent tracked,
            out string error)
        {
            error = null;
            if (tracked == null || tracked.status != "tracking" || tracked.requires_redetection ||
                !tracked.mask_quality_passed || tracked.quality < 0.45f)
            {
                error = "tracking quality gate rejected the current mask";
                Hide(componentId);
                return false;
            }
            if (string.IsNullOrWhiteSpace(tracked.overlay_png_base64))
            {
                error = "tracking response did not include a current mask";
                Hide(componentId);
                return false;
            }

            try
            {
                var layer = EnsureLayer(componentId);
                var png = Convert.FromBase64String(tracked.overlay_png_base64);
                if (!ImageConversion.LoadImage(layer.texture, png, false))
                    throw new InvalidOperationException("Unity could not decode the mask PNG");
                Manual2ARVisualTheme.RecolorMask(
                    layer.texture,
                    new Color32(10, 225, 245, 142));

                layer.mask.texture = layer.texture;
                layer.box = tracked.bbox_0_1000;
                layer.label.text = string.IsNullOrWhiteSpace(englishLabel)
                    ? componentId.Replace('_', ' ').ToUpperInvariant()
                    : englishLabel.ToUpperInvariant();
                layer.mask.gameObject.SetActive(true);
                layer.label.gameObject.SetActive(true);
                PositionLabel(layer);
                return true;
            }
            catch (Exception exception)
            {
                error = exception.Message;
                Hide(componentId);
                return false;
            }
        }

        public void Hide(string componentId)
        {
            if (!m_Layers.TryGetValue(componentId, out var layer))
                return;
            layer.mask.gameObject.SetActive(false);
            layer.label.gameObject.SetActive(false);
            layer.box = null;
        }

        public void Clear()
        {
            foreach (var componentId in m_Layers.Keys)
                Hide(componentId);
        }

        void LateUpdate()
        {
            foreach (var layer in m_Layers.Values)
                if (layer.mask.gameObject.activeSelf)
                    PositionLabel(layer);
        }

        Layer EnsureLayer(string componentId)
        {
            if (m_Layers.TryGetValue(componentId, out var existing))
                return existing;

            var maskObject = new GameObject($"{componentId} Current SAM Mask");
            maskObject.transform.SetParent(m_CameraContent, false);
            var maskRect = maskObject.AddComponent<RectTransform>();
            Stretch(maskRect);
            var mask = maskObject.AddComponent<RawImage>();
            mask.raycastTarget = false;
            mask.color = Color.white;
            maskObject.AddComponent<Manual2ARRevealMotion>().Configure(false);

            var labelObject = new GameObject($"{componentId} English Label");
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

            var layer = new Layer
            {
                mask = mask,
                texture = new Texture2D(2, 2, TextureFormat.RGBA32, false)
                {
                    name = $"Manual2AR {componentId} Tracking Mask"
                },
                label = label
            };
            m_Layers.Add(componentId, layer);
            Hide(componentId);
            return layer;
        }

        void PositionLabel(Layer layer)
        {
            if (m_CameraContent == null || layer.box == null || layer.box.Length < 4)
                return;

            var rect = m_CameraContent.rect;
            var x1 = rect.xMin + rect.width * layer.box[0] / 1000.0f;
            var x2 = rect.xMin + rect.width * layer.box[2] / 1000.0f;
            var y1 = rect.yMax - rect.height * layer.box[1] / 1000.0f;
            var y2 = rect.yMax - rect.height * layer.box[3] / 1000.0f;
            var corners = new[]
            {
                m_CameraContent.TransformPoint(new Vector3(x1, y1, 0.0f)),
                m_CameraContent.TransformPoint(new Vector3(x2, y1, 0.0f)),
                m_CameraContent.TransformPoint(new Vector3(x1, y2, 0.0f)),
                m_CameraContent.TransformPoint(new Vector3(x2, y2, 0.0f))
            };
            var minX = corners[0].x;
            var maxX = corners[0].x;
            var minY = corners[0].y;
            var maxY = corners[0].y;
            for (var index = 1; index < corners.Length; index++)
            {
                minX = Mathf.Min(minX, corners[index].x);
                maxX = Mathf.Max(maxX, corners[index].x);
                minY = Mathf.Min(minY, corners[index].y);
                maxY = Mathf.Max(maxY, corners[index].y);
            }
            const float halfLabelWidth = 215.0f;
            const float halfLabelHeight = 26.0f;
            const float safeMargin = 18.0f;
            var labelX = (minX + maxX) * 0.5f;
            var labelY = maxY + 32.0f;
            if (labelY + halfLabelHeight > Screen.height - safeMargin)
                labelY = minY - 32.0f;
            labelX = Mathf.Clamp(
                labelX,
                halfLabelWidth + safeMargin,
                Screen.width - halfLabelWidth - safeMargin);
            labelY = Mathf.Clamp(
                labelY,
                halfLabelHeight + safeMargin,
                Screen.height - halfLabelHeight - safeMargin);
            layer.label.rectTransform.position = new Vector3(labelX, labelY, 0.0f);
            layer.label.rectTransform.rotation = Quaternion.identity;
            layer.label.rectTransform.localScale = Vector3.one;
            layer.label.transform.SetAsLastSibling();
        }

        void OnDestroy()
        {
            foreach (var layer in m_Layers.Values)
                if (layer.texture != null)
                    Destroy(layer.texture);
        }

        static void Stretch(RectTransform rect)
        {
            rect.anchorMin = Vector2.zero;
            rect.anchorMax = Vector2.one;
            rect.offsetMin = Vector2.zero;
            rect.offsetMax = Vector2.zero;
        }
    }
}
