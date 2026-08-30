using System.IO;
using Manual2AR;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;
using Unity.XR.CoreUtils;
using UnityEngine.XR.ARFoundation;

namespace Manual2AR.Editor
{
    public static class Manual2AREmptySpindleSceneBuilder
    {
        const string ScenePath = "Assets/Manual2AR/Scenes/EmptySpindleTracking.unity";
        const string DefaultBackendUrl = "http://127.0.0.1:8010";

        [MenuItem("Manual2AR/Open Empty Spindle Tracking")]
        public static void OpenScene()
        {
            if (!File.Exists(ScenePath))
            {
                Debug.LogError($"Manual2AR scene is missing: {ScenePath}");
                return;
            }

            EditorSceneManager.OpenScene(ScenePath, OpenSceneMode.Single);
        }

        [MenuItem("Manual2AR/Create Empty Spindle Tracking Scene")]
        public static void CreateScene()
        {
            var scene = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);
            scene.name = "EmptySpindleTracking";

            var arSessionObject = new GameObject("AR Session");
            arSessionObject.AddComponent<ARSession>();

            var originObject = new GameObject("XR Origin");
            var origin = originObject.AddComponent<XROrigin>();
            var raycastManager = originObject.AddComponent<ARRaycastManager>();
            var anchorManager = originObject.AddComponent<ARAnchorManager>();

            var cameraOffsetObject = new GameObject("Camera Offset");
            cameraOffsetObject.transform.SetParent(originObject.transform, false);

            var cameraObject = new GameObject("Main Camera");
            cameraObject.tag = "MainCamera";
            cameraObject.transform.SetParent(cameraOffsetObject.transform, false);
            cameraObject.transform.localPosition = Vector3.zero;
            cameraObject.transform.localRotation = Quaternion.identity;

            var arCamera = cameraObject.AddComponent<Camera>();
            arCamera.clearFlags = CameraClearFlags.SolidColor;
            arCamera.backgroundColor = Color.black;
            cameraObject.AddComponent<AudioListener>();
            var cameraManager = cameraObject.AddComponent<ARCameraManager>();
            cameraObject.AddComponent<ARCameraBackground>();

            origin.CameraFloorOffsetObject = cameraOffsetObject;
            origin.Camera = arCamera;

            var controllerObject = new GameObject("Manual2AR Empty Spindle Tracking Controller");
            controllerObject.AddComponent<Manual2ARBackendClient>();
            var controller = controllerObject.AddComponent<EmptySpindleTrackingController>();
            controller.Configure(cameraManager, raycastManager, anchorManager, arCamera, DefaultBackendUrl);

            Directory.CreateDirectory("Assets/Manual2AR/Scenes");
            EditorSceneManager.MarkSceneDirty(scene);
            EditorSceneManager.SaveScene(scene, ScenePath);

            Selection.activeObject = controllerObject;
            EditorGUIUtility.PingObject(controllerObject);
            Debug.Log($"Manual2AR Empty Spindle Tracking scene created: {ScenePath}");
        }
    }
}
