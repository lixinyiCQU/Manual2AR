using System.IO;
using Manual2AR;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace Manual2AR.Editor
{
    public static class Manual2ARFilamentLoadingSceneBuilder
    {
        const string ScenePath = "Assets/Manual2AR/Scenes/FilamentLoadingGuidance.unity";
        const string DefaultBackendUrl = "http://127.0.0.1:8010";

        [MenuItem("Manual2AR/Create Filament Loading Guidance Scene")]
        public static void CreateScene()
        {
            var scene = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);
            scene.name = "FilamentLoadingGuidance";

            var cameraObject = new GameObject("Main Camera");
            cameraObject.tag = "MainCamera";
            var camera = cameraObject.AddComponent<Camera>();
            camera.clearFlags = CameraClearFlags.SolidColor;
            camera.backgroundColor = Color.black;
            cameraObject.AddComponent<AudioListener>();

            var controllerObject = new GameObject("Manual2AR Filament Loading Guidance Controller");
            controllerObject.AddComponent<Manual2ARBackendClient>();
            var controller = controllerObject.AddComponent<FilamentLoadingGuidanceController>();
            controller.Configure(DefaultBackendUrl);

            Directory.CreateDirectory("Assets/Manual2AR/Scenes");
            EditorSceneManager.MarkSceneDirty(scene);
            EditorSceneManager.SaveScene(scene, ScenePath);
            Selection.activeObject = controllerObject;
            EditorGUIUtility.PingObject(controllerObject);
            Debug.Log($"Manual2AR filament loading guidance scene created: {ScenePath}");
        }

        public static void CreateSceneBatch()
        {
            CreateScene();
            AssetDatabase.SaveAssets();
            UnityEditor.EditorApplication.Exit(0);
        }
    }
}
