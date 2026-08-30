using System;
using System.Reflection;
using UnityEditor;
using UnityEngine;

namespace Manual2AR.Editor
{
    /// <summary>Configures a full-resolution 16:9 Game view for clean screen recording.</summary>
    public static class Manual2ARRecordingViewSetup
    {
        const BindingFlags InstanceFlags =
            BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;

        [MenuItem("Manual2AR/Set Recording View 1920x1080")]
        public static void ConfigureRecordingView()
        {
            var gameViewType = typeof(EditorWindow).Assembly.GetType("UnityEditor.GameView");
            if (gameViewType == null)
                throw new InvalidOperationException("Unity GameView type was not found.");

            var gameView = EditorWindow.GetWindow(gameViewType);
            var setResolution = gameViewType.GetMethod("SetCustomResolution", InstanceFlags);
            if (setResolution == null)
                throw new MissingMethodException("Unity GameView.SetCustomResolution was not found.");

            setResolution.Invoke(gameView, new object[]
            {
                new Vector2(1920.0f, 1080.0f),
                "Manual2AR 1920x1080"
            });

            var lowResolution = gameViewType.GetProperty("lowResolutionForAspectRatios", InstanceFlags);
            lowResolution?.SetValue(gameView, false);

            gameView.Focus();
            gameView.Repaint();
            EditorApplication.delayCall += () => FitToWindow(gameViewType, gameView);
            Debug.Log("[Manual2AR] Recording view set to 1920x1080 with full-resolution rendering.");
        }

        static void FitToWindow(Type gameViewType, EditorWindow gameView)
        {
            if (gameView == null)
                return;

            var scaleToFit = gameViewType.GetMethod("ScaleThatFitsTargetInView", InstanceFlags);
            var snapZoom = gameViewType.GetMethod("SnapZoom", InstanceFlags);
            if (scaleToFit == null || snapZoom == null)
                return;

            var viewSize = new Vector2(
                Mathf.Max(1.0f, gameView.position.width),
                Mathf.Max(1.0f, gameView.position.height - 24.0f));
            var scale = (float)scaleToFit.Invoke(gameView, new object[]
            {
                new Vector2(1920.0f, 1080.0f),
                viewSize
            });
            snapZoom.Invoke(gameView, new object[] { scale });
            gameView.Repaint();
        }
    }
}
