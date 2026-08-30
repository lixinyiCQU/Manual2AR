using UnityEngine;
using UnityEngine.UI;

namespace Manual2AR
{
    /// <summary>
    /// Shared visual language for all paper-figure demos.  Keeping the values
    /// here prevents each feature scene from slowly drifting into a different
    /// mask hue, type scale, or outline depth.
    /// </summary>
    public static class Manual2ARVisualTheme
    {
        public static readonly Color TargetCyan = new Color(0.04f, 0.88f, 0.96f, 1.0f);
        public static readonly Color TargetLabel = new Color(0.88f, 1.0f, 1.0f, 1.0f);
        public static readonly Color SuccessGreen = new Color(0.17f, 1.0f, 0.58f, 1.0f);
        public static readonly Color ErrorRed = new Color(1.0f, 0.16f, 0.10f, 1.0f);
        public static readonly Color PanelBackground = new Color(0.01f, 0.05f, 0.075f, 0.90f);
        public static readonly Color ButtonBackground = new Color(0.02f, 0.22f, 0.32f, 0.92f);
        public static readonly Color OutlineColor = new Color(0.0f, 0.035f, 0.05f, 0.82f);

        public const int ObjectLabelFontSize = 28;
        public const int HeadlineFontSize = 31;
        public const int PrimaryInstructionFontSize = 32;
        public const int SecondaryInstructionFontSize = 24;
        public const int StatusFontSize = 24;
        public const int ButtonFontSize = 17;

        static Font s_Font;

        public static Font Font
        {
            get
            {
                if (s_Font == null)
                {
                    s_Font = UnityEngine.Font.CreateDynamicFontFromOSFont(
                        new[] { "Avenir Next", "Helvetica Neue", "Helvetica", "Arial" },
                        40);
                    if (s_Font == null)
                        s_Font = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
                }
                return s_Font;
            }
        }

        public static void StyleText(Text text, int fontSize, Color color, TextAnchor alignment)
        {
            text.font = Font;
            text.fontSize = fontSize;
            text.fontStyle = FontStyle.Bold;
            text.alignment = alignment;
            text.color = color;
            text.raycastTarget = false;
        }

        public static void AddTextDepth(GameObject target, float distance = 3.0f)
        {
            var outline = target.GetComponent<Outline>() ?? target.AddComponent<Outline>();
            outline.effectColor = OutlineColor;
            var crispDistance = Mathf.Min(1.5f, Mathf.Max(1.0f, distance));
            outline.effectDistance = new Vector2(crispDistance, -crispDistance);
        }

        public static void RecolorMask(Texture2D texture, Color32 color)
        {
            var pixels = texture.GetPixels32();
            for (var index = 0; index < pixels.Length; index++)
            {
                if (pixels[index].a < 8)
                    pixels[index] = new Color32(0, 0, 0, 0);
                else
                    pixels[index] = color;
            }
            texture.SetPixels32(pixels);
            texture.Apply(false, false);
        }
    }
}
