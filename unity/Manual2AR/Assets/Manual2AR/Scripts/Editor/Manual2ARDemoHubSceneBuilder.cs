using System.Collections.Generic;
using System.IO;
using Manual2AR;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace Manual2AR.Editor
{
    public static class Manual2ARDemoHubSceneBuilder
    {
        const string HubScenePath = "Assets/Manual2AR/Scenes/Manual2ARDemoHub.unity";

        static readonly string[] Manual2ARScenePaths =
        {
            Manual2ARWorkflowSceneBuilder.WorkflowScenePath,
            HubScenePath,
            "Assets/Manual2AR/Scenes/ComponentOverviewTracking.unity",
            "Assets/Manual2AR/Scenes/EmptySpindleTracking.unity",
            "Assets/Manual2AR/Scenes/FilamentLoadingGuidance.unity",
            "Assets/Manual2AR/Scenes/PrePrintPlateInspection.unity"
        };

        [MenuItem("Manual2AR/Open Demo Hub")]
        public static void OpenHub()
        {
            if (EditorApplication.isPlaying)
            {
                Manual2ARSceneNavigation.LoadHub();
                return;
            }
            if (!File.Exists(HubScenePath))
                CreateScene();
            EditorSceneManager.OpenScene(HubScenePath, OpenSceneMode.Single);
        }

        [MenuItem("Manual2AR/Create Demo Hub and Configure Build Settings")]
        public static void CreateScene()
        {
            var scene = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);
            scene.name = "Manual2ARDemoHub";

            var cameraObject = new GameObject("Main Camera");
            cameraObject.tag = "MainCamera";
            var camera = cameraObject.AddComponent<Camera>();
            camera.clearFlags = CameraClearFlags.SolidColor;
            camera.backgroundColor = new Color(0.006f, 0.025f, 0.04f, 1.0f);
            cameraObject.AddComponent<AudioListener>();

            var hubObject = new GameObject("Manual2AR Demo Hub Controller");
            hubObject.AddComponent<Manual2ARDemoHubController>();

            Directory.CreateDirectory("Assets/Manual2AR/Scenes");
            EditorSceneManager.MarkSceneDirty(scene);
            EditorSceneManager.SaveScene(scene, HubScenePath);
            ConfigureBuildSettings();
            AssetDatabase.SaveAssets();
            Selection.activeObject = hubObject;
            EditorGUIUtility.PingObject(hubObject);
            Debug.Log($"Manual2AR demo hub created: {HubScenePath}");
        }

        public static void CreateSceneBatch()
        {
            CreateScene();
            EditorApplication.Exit(0);
        }

        static void ConfigureBuildSettings()
        {
            Manual2ARWorkflowSceneBuilder.ConfigureBuildSettings();
        }
    }
}
