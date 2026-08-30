using System.Collections.Generic;
using System.IO;
using Manual2AR;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace Manual2AR.Editor
{
    public static class Manual2ARWorkflowSceneBuilder
    {
        public const string WorkflowScenePath = "Assets/Manual2AR/Scenes/Manual2ARWorkflow.unity";

        static readonly string[] RecordingScenePaths =
        {
            WorkflowScenePath,
            "Assets/Manual2AR/Scenes/Manual2ARDemoHub.unity",
            "Assets/Manual2AR/Scenes/ComponentOverviewTracking.unity",
            "Assets/Manual2AR/Scenes/EmptySpindleTracking.unity",
            "Assets/Manual2AR/Scenes/FilamentLoadingGuidance.unity",
            "Assets/Manual2AR/Scenes/PrePrintPlateInspection.unity"
        };

        [InitializeOnLoadMethod]
        static void EnsureWorkflowSceneAfterCompile()
        {
            EditorApplication.delayCall += () =>
            {
                if (EditorApplication.isPlayingOrWillChangePlaymode || File.Exists(WorkflowScenePath))
                    return;
                CreateScene(false);
            };
        }

        [MenuItem("Manual2AR/Open Recording Workflow")]
        public static void OpenWorkflow()
        {
            if (EditorApplication.isPlaying)
            {
                Manual2ARSceneNavigation.LoadWorkflowTask();
                return;
            }
            if (!File.Exists(WorkflowScenePath))
                CreateScene(false);
            EditorSceneManager.OpenScene(WorkflowScenePath, OpenSceneMode.Single);
        }

        [MenuItem("Manual2AR/Open Task Selection")]
        public static void OpenTaskSelection()
        {
            if (!EditorApplication.isPlaying)
            {
                OpenWorkflow();
                return;
            }

            var controller = Object.FindObjectOfType<Manual2ARWorkflowController>();
            if (controller != null)
                controller.OpenTaskSelectionForRecording();
        }

        [MenuItem("Manual2AR/Create Recording Workflow and Configure Build Settings")]
        public static void CreateSceneFromMenu()
        {
            CreateScene(true);
        }

        public static void CreateSceneBatch()
        {
            CreateScene(false);
            EditorApplication.Exit(0);
        }

        static void CreateScene(bool openAfterCreation)
        {
            var previous = SceneManager.GetActiveScene();
            var scene = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Additive);
            scene.name = "Manual2ARWorkflow";

            var cameraObject = new GameObject("Main Camera");
            SceneManager.MoveGameObjectToScene(cameraObject, scene);
            cameraObject.tag = "MainCamera";
            var camera = cameraObject.AddComponent<Camera>();
            camera.clearFlags = CameraClearFlags.SolidColor;
            camera.backgroundColor = new Color(0.004f, 0.018f, 0.032f, 1.0f);
            cameraObject.AddComponent<AudioListener>();

            var controllerObject = new GameObject("Manual2AR Recording Workflow Controller");
            SceneManager.MoveGameObjectToScene(controllerObject, scene);
            controllerObject.AddComponent<Manual2ARWorkflowController>();

            Directory.CreateDirectory("Assets/Manual2AR/Scenes");
            EditorSceneManager.MarkSceneDirty(scene);
            EditorSceneManager.SaveScene(scene, WorkflowScenePath);
            ConfigureBuildSettings();
            AssetDatabase.SaveAssets();

            if (openAfterCreation)
            {
                EditorSceneManager.CloseScene(scene, true);
                EditorSceneManager.OpenScene(WorkflowScenePath, OpenSceneMode.Single);
                Selection.activeObject = Object.FindObjectOfType<Manual2ARWorkflowController>();
            }
            else
            {
                EditorSceneManager.CloseScene(scene, true);
                if (previous.IsValid() && previous.isLoaded)
                    SceneManager.SetActiveScene(previous);
            }

            Debug.Log($"Manual2AR recording workflow created: {WorkflowScenePath}");
        }

        public static void ConfigureBuildSettings()
        {
            var configured = new List<EditorBuildSettingsScene>();
            foreach (var path in RecordingScenePaths)
                configured.Add(new EditorBuildSettingsScene(path, true));

            var seen = new HashSet<string>(RecordingScenePaths);
            foreach (var existing in EditorBuildSettings.scenes)
            {
                if (!seen.Contains(existing.path))
                    configured.Add(existing);
            }
            EditorBuildSettings.scenes = configured.ToArray();
        }
    }
}
