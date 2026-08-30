using UnityEngine;
using UnityEngine.SceneManagement;
using UnityEngine.UI;

namespace Manual2AR
{
    public static class Manual2ARSceneNavigation
    {
        public const string HubSceneName = "Manual2ARDemoHub";
        public const string WorkflowSceneName = "Manual2ARWorkflow";

        static bool s_OpenWorkflowTaskDetail;

        public static void CreateHomeButton(Transform canvasRoot)
        {
            if (canvasRoot == null || canvasRoot.Find("Demo Hub Button") != null)
                return;

            var go = new GameObject("Demo Hub Button");
            go.transform.SetParent(canvasRoot, false);
            var rect = go.AddComponent<RectTransform>();
            rect.anchorMin = new Vector2(0.0f, 1.0f);
            rect.anchorMax = new Vector2(0.0f, 1.0f);
            rect.pivot = new Vector2(0.0f, 1.0f);
            rect.anchoredPosition = new Vector2(24.0f, -24.0f);
            rect.sizeDelta = new Vector2(186.0f, 54.0f);
            var image = go.AddComponent<Image>();
            image.color = Manual2ARVisualTheme.ButtonBackground;
            var button = go.AddComponent<Button>();
            var colors = button.colors;
            colors.highlightedColor = new Color(0.03f, 0.48f, 0.62f, 1.0f);
            colors.pressedColor = Manual2ARVisualTheme.TargetCyan;
            button.colors = colors;
            button.onClick.AddListener(LoadHub);

            var labelObject = new GameObject("Text");
            labelObject.transform.SetParent(go.transform, false);
            var labelRect = labelObject.AddComponent<RectTransform>();
            Stretch(labelRect);
            var label = labelObject.AddComponent<Text>();
            label.text = "←  BACK TO MODULES";
            Manual2ARVisualTheme.StyleText(
                label,
                Manual2ARVisualTheme.ButtonFontSize,
                Color.white,
                TextAnchor.MiddleCenter);
        }

        public static void LoadHub()
        {
            SceneManager.LoadScene(HubSceneName);
        }

        public static void LoadWorkflowTask()
        {
            s_OpenWorkflowTaskDetail = true;
            SceneManager.LoadScene(WorkflowSceneName);
        }

        public static bool ConsumeWorkflowTaskDetailRequest()
        {
            var requested = s_OpenWorkflowTaskDetail;
            s_OpenWorkflowTaskDetail = false;
            return requested;
        }

        public static void Load(string sceneName)
        {
            SceneManager.LoadScene(sceneName);
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
