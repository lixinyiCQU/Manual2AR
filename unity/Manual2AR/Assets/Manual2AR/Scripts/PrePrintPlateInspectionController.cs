using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Text;
using UnityEngine;
using UnityEngine.EventSystems;
using UnityEngine.UI;

namespace Manual2AR
{
    [RequireComponent(typeof(Manual2ARBackendClient))]
    public sealed class PrePrintPlateInspectionController : MonoBehaviour
    {
        [SerializeField] int m_RequestedCameraWidth = 1280;
        [SerializeField] int m_RequestedCameraHeight = 720;
        [SerializeField] int m_RequestedCameraFps = 30;
        [SerializeField] string m_BackendBaseUrl = "http://127.0.0.1:8010";
        [SerializeField] float m_TrackingIntervalSeconds = 0.5f;

        Manual2ARBackendClient m_BackendClient;
        PrePrintPlateInspectionOverlay m_Overlay;
        readonly Dictionary<string, InspectionState> m_States = new Dictionary<string, InspectionState>();
        RectTransform m_CameraImagePlane;
        RectTransform m_CameraContent;
        RawImage m_CameraPreview;
        Text m_StatusText;
        Button m_StartCameraButton;
        Button m_SwitchCameraButton;
        Button m_InspectButton;
        Button m_ReInspectButton;
        Button m_CaptureEvidenceButton;
        Button m_ClearOverlayButton;
        GameObject m_ControlsRoot;
        WebCamTexture m_WebCamTexture;
        Texture2D m_CaptureTexture;
        Color32[] m_WebCamPixels;
        byte[] m_LastCameraJpg;
        string m_LastInspectionResponse;
        readonly StringBuilder m_TrackingResponses = new StringBuilder();
        BuildPlateInspectionResponse m_CurrentInspection;
        int m_CurrentCameraIndex = -1;
        int m_LastLayoutWidth;
        int m_LastLayoutHeight;
        int m_LastVideoRotation = -1;
        bool m_LastVideoMirrored;
        bool m_IsRequestInFlight;
        float m_LastTrackingTime;
        Coroutine m_CameraStartRoutine;

        bool HasLiveCamera => m_WebCamTexture != null && m_WebCamTexture.isPlaying &&
            m_WebCamTexture.width > 16 && m_WebCamTexture.height > 16;

        public void Configure(string backendBaseUrl)
        {
            if (!string.IsNullOrWhiteSpace(backendBaseUrl))
                m_BackendBaseUrl = backendBaseUrl.TrimEnd('/');
            if (m_BackendClient != null)
                m_BackendClient.backendBaseUrl = m_BackendBaseUrl;
        }

        void Awake()
        {
            m_BackendClient = GetComponent<Manual2ARBackendClient>();
            m_BackendClient.backendBaseUrl = m_BackendBaseUrl;
            var uiRoot = EnsureRuntimeUi();
            m_Overlay = gameObject.AddComponent<PrePrintPlateInspectionOverlay>();
            m_Overlay.Initialize(m_CameraContent, uiRoot);
            SetButtonsInteractable(true);
            Debug.Log(
                $"[Manual2AR] pre-print inspection backend={m_BackendBaseUrl} · " +
                "profile=preprint_plate_inspection_v1 · expected model=qwen3-vl-flash · " +
                "method=task-conditioned-profile+constraint-guided-SAM · guidance=image-space");
        }

        void OnEnable()
        {
            m_InspectButton.onClick.AddListener(InspectBuildPlate);
            m_CaptureEvidenceButton.onClick.AddListener(CaptureEvidence);
            m_ClearOverlayButton.onClick.AddListener(ClearOverlay);
        }

        void Start()
        {
            StartCamera();
        }

        void OnDisable()
        {
            m_InspectButton.onClick.RemoveListener(InspectBuildPlate);
            m_CaptureEvidenceButton.onClick.RemoveListener(CaptureEvidence);
            m_ClearOverlayButton.onClick.RemoveListener(ClearOverlay);
            CloseAndClearAll();
            StopWebCam();
        }

        void Update()
        {
            if (HasLiveCamera &&
                (Screen.width != m_LastLayoutWidth || Screen.height != m_LastLayoutHeight ||
                 m_LastVideoRotation != m_WebCamTexture.videoRotationAngle ||
                 m_LastVideoMirrored != m_WebCamTexture.videoVerticallyMirrored))
                UpdateCameraLayout();

            if (m_IsRequestInFlight || m_States.Count == 0 || !HasLiveCamera)
                return;
            if (Time.unscaledTime - m_LastTrackingTime < m_TrackingIntervalSeconds)
                return;
            m_LastTrackingTime = Time.unscaledTime;
            StartCoroutine(SendTrackingFrames());
        }

        public void StartCamera()
        {
            if (m_CameraStartRoutine != null)
                StopCoroutine(m_CameraStartRoutine);
            m_CameraStartRoutine = StartCoroutine(StartWebCamRoutine(false));
        }

        public void SwitchCamera()
        {
            if (m_CameraStartRoutine != null)
                StopCoroutine(m_CameraStartRoutine);
            m_CameraStartRoutine = StartCoroutine(StartWebCamRoutine(true));
        }

        IEnumerator StartWebCamRoutine(bool advance)
        {
            SetStatus($"STARTING {Manual2ARCameraSelection.ModeLabel(Manual2ARCameraSelection.mode)}…");
            if (!Application.HasUserAuthorization(UserAuthorization.WebCam))
                yield return Application.RequestUserAuthorization(UserAuthorization.WebCam);
            if (!Application.HasUserAuthorization(UserAuthorization.WebCam))
            {
                SetStatus("CAMERA PERMISSION REQUIRED");
                m_CameraStartRoutine = null;
                yield break;
            }
            var devices = WebCamTexture.devices;
            if (devices == null || devices.Length == 0)
            {
                SetStatus("NO CAMERA DEVICE DETECTED");
                m_CameraStartRoutine = null;
                yield break;
            }
            if (advance && m_CurrentCameraIndex >= 0)
                m_CurrentCameraIndex = (m_CurrentCameraIndex + 1) % devices.Length;
            else if (m_CurrentCameraIndex < 0 || m_CurrentCameraIndex >= devices.Length)
            {
                if (!Manual2ARCameraSelection.TryResolve(devices, out m_CurrentCameraIndex, out var selectionMessage))
                {
                    SetStatus(selectionMessage);
                    Debug.LogWarning($"[Manual2AR] available cameras: {Manual2ARCameraSelection.DeviceSummary(devices)}");
                    m_CameraStartRoutine = null;
                    yield break;
                }
            }

            CloseAndClearAll();
            StopWebCam();
            var selected = devices[m_CurrentCameraIndex];
            m_WebCamTexture = new WebCamTexture(
                selected.name,
                m_RequestedCameraWidth,
                m_RequestedCameraHeight,
                m_RequestedCameraFps);
            m_CameraPreview.texture = m_WebCamTexture;
            m_CameraPreview.color = Color.white;
            m_WebCamTexture.Play();
            var timeoutAt = Time.realtimeSinceStartup + 8.0f;
            while ((!m_WebCamTexture.didUpdateThisFrame || m_WebCamTexture.width <= 16) &&
                   Time.realtimeSinceStartup < timeoutAt)
                yield return null;
            if (!HasLiveCamera)
            {
                StopWebCam();
                SetStatus($"CAMERA START FAILED · {selected.name}");
                m_CameraStartRoutine = null;
                yield break;
            }
            UpdateCameraLayout();
            SetStatus($"CAMERA READY · {selected.name}");
            SetButtonsInteractable(true);
            Debug.Log(
                $"[Manual2AR] camera={selected.name} · frame={m_WebCamTexture.width}x{m_WebCamTexture.height} · " +
                $"rotation={m_WebCamTexture.videoRotationAngle} · mirrored={m_WebCamTexture.videoVerticallyMirrored}");
            m_CameraStartRoutine = null;
        }

        void StopWebCam()
        {
            if (m_WebCamTexture != null)
            {
                if (m_WebCamTexture.isPlaying)
                    m_WebCamTexture.Stop();
                Destroy(m_WebCamTexture);
                m_WebCamTexture = null;
            }
            if (m_CameraPreview != null)
                m_CameraPreview.texture = null;
        }

        void UpdateCameraLayout()
        {
            if (!HasLiveCamera || m_CameraImagePlane == null || m_CameraContent == null)
                return;
            var rotation = ((m_WebCamTexture.videoRotationAngle % 360) + 360) % 360;
            var quarterTurn = rotation == 90 || rotation == 270;
            var orientedWidth = quarterTurn ? m_WebCamTexture.height : m_WebCamTexture.width;
            var orientedHeight = quarterTurn ? m_WebCamTexture.width : m_WebCamTexture.height;
            var orientedAspect = (float)orientedWidth / Mathf.Max(1.0f, orientedHeight);
            var parentRect = ((RectTransform)m_CameraImagePlane.parent).rect;
            var parentAspect = parentRect.width / Mathf.Max(1.0f, parentRect.height);
            var planeSize = parentAspect > orientedAspect
                ? new Vector2(parentRect.width, parentRect.width / orientedAspect)
                : new Vector2(parentRect.height * orientedAspect, parentRect.height);
            m_CameraImagePlane.sizeDelta = planeSize;
            m_CameraContent.sizeDelta = quarterTurn
                ? new Vector2(planeSize.y, planeSize.x)
                : planeSize;
            m_CameraContent.localEulerAngles = new Vector3(0.0f, 0.0f, -rotation);
            m_CameraContent.localScale = new Vector3(
                1.0f,
                m_WebCamTexture.videoVerticallyMirrored ? -1.0f : 1.0f,
                1.0f);
            m_LastLayoutWidth = Screen.width;
            m_LastLayoutHeight = Screen.height;
            m_LastVideoRotation = m_WebCamTexture.videoRotationAngle;
            m_LastVideoMirrored = m_WebCamTexture.videoVerticallyMirrored;
        }

        public void InspectBuildPlate()
        {
            if (m_IsRequestInFlight || !HasLiveCamera)
            {
                if (!HasLiveCamera)
                    SetStatus("START CAMERA BEFORE INSPECTION");
                return;
            }
            StartCoroutine(InspectRoutine());
        }

        public void ReInspect()
        {
            CloseAndClearAll();
            InspectBuildPlate();
        }

        public void ClearOverlay()
        {
            CloseAndClearAll();
            SetStatus("INSPECTION OVERLAY CLEARED");
        }

        IEnumerator InspectRoutine()
        {
            m_IsRequestInFlight = true;
            SetButtonsInteractable(false);
            CloseAndClearAll();
            m_LastInspectionResponse = null;
            m_TrackingResponses.Length = 0;
            m_Overlay.ShowProcessing();
            SetStatus("INSPECTING · QWEN3-VL-FLASH + COMPILED SAM2 GATES");
            if (!TryCaptureCameraJpg(out var jpg, out var captureError))
            {
                m_IsRequestInFlight = false;
                SetButtonsInteractable(true);
                SetStatus($"CAMERA FRAME FAILED · {captureError}");
                yield break;
            }
            m_LastCameraJpg = jpg;
            BuildPlateInspectionResponse response = null;
            string rawResponse = null;
            yield return m_BackendClient.InspectBuildPlate(
                Convert.ToBase64String(jpg),
                m_WebCamTexture.videoRotationAngle,
                (inspection, raw) =>
                {
                    response = inspection;
                    rawResponse = raw;
                });
            m_LastInspectionResponse = rawResponse;
            m_CurrentInspection = response;
            SaveLatestInspectionDiagnostic(jpg, rawResponse);
            m_IsRequestInFlight = false;
            SetButtonsInteractable(true);

            if (response == null || !string.IsNullOrEmpty(response.error) ||
                response.status == "uncertain" || response.plate_mask == null ||
                !AcceptMask(response.plate_mask))
            {
                foreach (var state in m_States.Values)
                    if (!string.IsNullOrEmpty(state.sessionId))
                        StartCoroutine(m_BackendClient.CloseTrackingSession(state.sessionId));
                m_States.Clear();
                m_CurrentInspection = response;
                m_Overlay.ShowUncertain();
                SetButtonsInteractable(true);
                SetStatus("INSPECTION UNCERTAIN · REFRAME BUILD PLATE");
                yield break;
            }

            if (response.anomalies != null)
            {
                foreach (var anomaly in response.anomalies)
                {
                    if (anomaly == null || !AcceptMask(anomaly))
                    {
                        HandleTrackingLost("initial anomaly mask failed");
                        yield break;
                    }
                }
            }
            if (!CurrentGeometryConsistent())
            {
                HandleTrackingLost("initial anomaly/plate relation failed");
                yield break;
            }
            m_Overlay.SetInspectionState(response);
            m_LastTrackingTime = Time.unscaledTime;
            SetStatus(response.safe_to_print
                ? "READY TO PRINT"
                : "CORRECTIVE ACTION REQUIRED · REMOVE HIGHLIGHTED MATERIAL");
            Debug.Log(
                $"[Manual2AR] inspection={response.status} · safe_to_print={response.safe_to_print} · " +
                $"provider={response.provider} · model={response.model} · " +
                $"profile={response.profile_id}@{response.profile_version} · sessions={string.Join(",", ActiveSessionIds())}");
        }

        bool AcceptMask(InspectionMaskResult result)
        {
            if (result == null || !result.tracking_ready || string.IsNullOrEmpty(result.session_id) ||
                result.tracked == null || result.tracked.status != "tracking" ||
                result.tracked.requires_redetection || !result.tracked.mask_quality_passed ||
                result.tracked.quality < 0.50f)
                return false;
            if (!m_Overlay.ShowMask(
                    result.object_id,
                    result.object_type,
                    result.tracked,
                    m_CurrentInspection != null && m_CurrentInspection.safe_to_print,
                    out var overlayError))
            {
                Debug.LogWarning($"[Manual2AR] mask render rejected: {overlayError}");
                StartCoroutine(m_BackendClient.CloseTrackingSession(result.session_id));
                return false;
            }
            m_States[result.object_id] = new InspectionState
            {
                objectId = result.object_id,
                objectType = result.object_type,
                sessionId = result.session_id,
                lastBox = result.tracked.bbox_0_1000
            };
            return true;
        }

        bool CurrentGeometryConsistent()
        {
            InspectionState plate = null;
            foreach (var state in m_States.Values)
                if (state.objectType == "build_plate")
                {
                    plate = state;
                    break;
                }
            if (plate == null || plate.lastBox == null || plate.lastBox.Length < 4)
                return false;
            foreach (var state in m_States.Values)
            {
                if (state.objectType == "build_plate")
                    continue;
                var box = state.lastBox;
                if (box == null || box.Length < 4)
                    return false;
                var centerX = (box[0] + box[2]) * 0.5f;
                var centerY = (box[1] + box[3]) * 0.5f;
                if (centerX < plate.lastBox[0] || centerX > plate.lastBox[2] ||
                    centerY < plate.lastBox[1] || centerY > plate.lastBox[3])
                    return false;
                var intersectionWidth = Mathf.Max(
                    0.0f,
                    Mathf.Min(box[2], plate.lastBox[2]) - Mathf.Max(box[0], plate.lastBox[0]));
                var intersectionHeight = Mathf.Max(
                    0.0f,
                    Mathf.Min(box[3], plate.lastBox[3]) - Mathf.Max(box[1], plate.lastBox[1]));
                var anomalyArea = Mathf.Max(1.0f, (box[2] - box[0]) * (box[3] - box[1]));
                if (intersectionWidth * intersectionHeight / anomalyArea < 0.55f)
                    return false;
            }
            return true;
        }

        IEnumerator SendTrackingFrames()
        {
            if (!TryCaptureCameraJpg(out var jpg, out var captureError))
            {
                HandleTrackingLost($"camera frame failed: {captureError}");
                yield break;
            }
            m_IsRequestInFlight = true;
            var snapshot = new List<InspectionState>(m_States.Values);
            var pending = new List<PendingTrackingUpdate>();
            foreach (var state in snapshot)
            {
                TrackingFrameResponse response = null;
                string rawResponse = null;
                yield return m_BackendClient.SendTrackingFrame(
                    state.sessionId,
                    Convert.ToBase64String(jpg),
                    "client_pending",
                    0.0f,
                    0,
                    (updated, raw) =>
                    {
                        response = updated;
                        rawResponse = raw;
                    });
                if (!m_States.TryGetValue(state.objectId, out var current) ||
                    current.sessionId != state.sessionId)
                {
                    m_IsRequestInFlight = false;
                    yield break;
                }
                if (response == null || !string.IsNullOrEmpty(response.error) ||
                    response.tracked == null || response.tracked.status != "tracking" ||
                    response.tracked.requires_redetection || !response.tracked.mask_quality_passed ||
                    response.tracked.quality < 0.45f ||
                    string.IsNullOrEmpty(response.tracked.overlay_png_base64))
                {
                    m_IsRequestInFlight = false;
                    HandleTrackingLost(response?.error ?? "tracking quality gate failed");
                    yield break;
                }
                pending.Add(new PendingTrackingUpdate
                {
                    state = current,
                    response = response,
                    rawResponse = rawResponse
                });
            }

            // Render only after every independent session has produced a valid
            // result for this same camera frame. This prevents the plate,
            // foreign object and residue from visibly occupying different
            // frames while sequential HTTP requests are still completing.
            foreach (var update in pending)
            {
                if (!m_Overlay.ShowMask(
                        update.state.objectId,
                        update.state.objectType,
                        update.response.tracked,
                        m_CurrentInspection != null && m_CurrentInspection.safe_to_print,
                        out var overlayError))
                {
                    m_IsRequestInFlight = false;
                    HandleTrackingLost(overlayError ?? "tracked mask render rejected");
                    yield break;
                }
                update.state.lastBox = update.response.tracked.bbox_0_1000;
                if (!string.IsNullOrEmpty(update.rawResponse))
                    m_TrackingResponses.AppendLine(update.rawResponse);
            }
            m_LastCameraJpg = jpg;
            m_IsRequestInFlight = false;
            if (!CurrentGeometryConsistent())
            {
                HandleTrackingLost("tracked anomaly left the tracked build plate");
                yield break;
            }
            m_Overlay.SetInspectionState(m_CurrentInspection);
            SetStatus(m_CurrentInspection != null && m_CurrentInspection.safe_to_print
                ? "READY TO PRINT · LIVE TRACKING"
                : "CORRECTIVE ACTION REQUIRED · LIVE TRACKING");
        }

        void HandleTrackingLost(string reason)
        {
            Debug.LogWarning($"[Manual2AR] inspection tracking lost: {reason}");
            CloseAndClearAll();
            SetStatus("INSPECTION TRACKING LOST · RE-INSPECT REQUIRED");
        }

        void SaveLatestInspectionDiagnostic(byte[] jpg, string rawResponse)
        {
            try
            {
                var root = Path.Combine(
                    Application.persistentDataPath,
                    "Manual2AR",
                    "Diagnostics");
                Directory.CreateDirectory(root);
                if (jpg != null && jpg.Length > 0)
                    File.WriteAllBytes(
                        Path.Combine(root, "latest_preprint_camera.jpg"),
                        jpg);
                if (!string.IsNullOrEmpty(rawResponse))
                    File.WriteAllText(
                        Path.Combine(root, "latest_preprint_response.json"),
                        rawResponse,
                        Encoding.UTF8);
                Debug.Log($"[Manual2AR] latest inspection diagnostic: {root}");
            }
            catch (Exception exception)
            {
                Debug.LogWarning($"[Manual2AR] could not save inspection diagnostic: {exception.Message}");
            }
        }

        void CloseAndClearAll()
        {
            m_Overlay?.Clear();
            foreach (var state in m_States.Values)
                if (!string.IsNullOrEmpty(state.sessionId) && m_BackendClient != null)
                    StartCoroutine(m_BackendClient.CloseTrackingSession(state.sessionId));
            m_States.Clear();
            m_CurrentInspection = null;
        }

        string[] ActiveSessionIds()
        {
            var ids = new List<string>();
            foreach (var state in m_States.Values)
                ids.Add(state.sessionId);
            return ids.ToArray();
        }

        bool TryCaptureCameraJpg(out byte[] jpg, out string error)
        {
            jpg = null;
            error = null;
            if (!HasLiveCamera)
            {
                error = "Mac WebCamTexture is not ready";
                return false;
            }
            var width = m_WebCamTexture.width;
            var height = m_WebCamTexture.height;
            var pixelCount = width * height;
            if (m_WebCamPixels == null || m_WebCamPixels.Length != pixelCount)
                m_WebCamPixels = new Color32[pixelCount];
            if (m_CaptureTexture == null || m_CaptureTexture.width != width || m_CaptureTexture.height != height)
            {
                if (m_CaptureTexture != null)
                    Destroy(m_CaptureTexture);
                m_CaptureTexture = new Texture2D(width, height, TextureFormat.RGBA32, false)
                {
                    name = "Manual2AR Pre-print Inspection Capture Frame"
                };
            }
            m_WebCamTexture.GetPixels32(m_WebCamPixels);
            m_CaptureTexture.SetPixels32(m_WebCamPixels);
            m_CaptureTexture.Apply(false, false);
            jpg = m_CaptureTexture.EncodeToJPG(88);
            return jpg != null && jpg.Length > 0;
        }

        public void CaptureEvidence()
        {
            if (m_CurrentInspection == null || m_CurrentInspection.status == "uncertain" || m_States.Count == 0)
            {
                SetStatus("RUN A SUCCESSFUL INSPECTION BEFORE SAVING");
                return;
            }
            StartCoroutine(CaptureEvidenceRoutine());
        }

        IEnumerator CaptureEvidenceRoutine()
        {
            var root = Path.Combine(
                Application.persistentDataPath,
                "Manual2AR",
                "Evidence",
                DateTime.Now.ToString("yyyyMMdd_HHmmss") + "_preprint_plate_inspection");
            Directory.CreateDirectory(root);
            if (TryCaptureCameraJpg(out var currentJpg, out _))
            {
                m_LastCameraJpg = currentJpg;
                File.WriteAllBytes(Path.Combine(root, "camera_frame.jpg"), currentJpg);
            }
            if (!string.IsNullOrEmpty(m_LastInspectionResponse))
                File.WriteAllText(
                    Path.Combine(root, "qwen_compiler_sam_response.json"),
                    m_LastInspectionResponse,
                    Encoding.UTF8);
            if (m_TrackingResponses.Length > 0)
                File.WriteAllText(
                    Path.Combine(root, "tracking_responses.jsonl"),
                    m_TrackingResponses.ToString(),
                    Encoding.UTF8);
            var inspection = m_CurrentInspection;
            File.WriteAllText(
                Path.Combine(root, "evidence_manifest.json"),
                JsonUtility.ToJson(new PlateInspectionEvidenceLog
                {
                    figure_id = "preprint_build_plate_inspection_and_corrective_guidance",
                    backend_base_url = m_BackendClient.backendBaseUrl,
                    profile_id = inspection?.profile_id ?? "preprint_plate_inspection_v1",
                    profile_version = inspection?.profile_version ?? "unknown",
                    prompt_version = inspection?.prompt_version ?? "unknown",
                    method_label = inspection?.method_label ?? "unknown",
                    exemplar_guided = inspection != null && inspection.exemplar_guided,
                    provider = inspection?.provider ?? "unknown",
                    model = inspection?.model ?? "unknown",
                    safe_to_print = inspection != null && inspection.safe_to_print,
                    inspection_status = inspection?.status ?? "none",
                    session_ids = ActiveSessionIds(),
                    clean_reference_sha256 = inspection?.reference_hashes?.clean_p2_sha256 ?? "unknown",
                    dirty_reference_sha256 = inspection?.reference_hashes?.dirty_p1_sha256 ?? "unknown",
                    camera_device = m_WebCamTexture != null ? m_WebCamTexture.deviceName : "none",
                    image_rotation_degrees = m_WebCamTexture != null ? m_WebCamTexture.videoRotationAngle : 0,
                    image_vertically_mirrored = m_WebCamTexture != null && m_WebCamTexture.videoVerticallyMirrored,
                    guidance_space = "image_space",
                    captured_at = DateTime.Now.ToString("O")
                }, true),
                Encoding.UTF8);

            var controlsWereActive = m_ControlsRoot.activeSelf;
            var statusWasActive = m_StatusText.gameObject.activeSelf;
            m_ControlsRoot.SetActive(false);
            m_StatusText.gameObject.SetActive(false);
            yield return new WaitForEndOfFrame();
            ScreenCapture.CaptureScreenshot(Path.Combine(root, "overlay_screenshot.png"));
            yield return new WaitForEndOfFrame();
            m_ControlsRoot.SetActive(controlsWereActive);
            m_StatusText.gameObject.SetActive(statusWasActive);
            Debug.Log($"[Manual2AR] evidence saved: {root}");
            SetStatus("EVIDENCE SAVED · CURRENT VERIFIED OVERLAY");
        }

        Transform EnsureRuntimeUi()
        {
            if (EventSystem.current == null)
            {
                var eventSystem = new GameObject("EventSystem");
                eventSystem.AddComponent<EventSystem>();
                eventSystem.AddComponent<StandaloneInputModule>();
            }
            var canvasObject = new GameObject("Manual2AR Pre-print Inspection UI");
            var canvas = canvasObject.AddComponent<Canvas>();
            canvas.renderMode = RenderMode.ScreenSpaceOverlay;
            canvas.pixelPerfect = true;
            canvas.sortingOrder = 100;
            var scaler = canvasObject.AddComponent<CanvasScaler>();
            scaler.uiScaleMode = CanvasScaler.ScaleMode.ScaleWithScreenSize;
            scaler.referenceResolution = new Vector2(1920.0f, 1080.0f);
            scaler.matchWidthOrHeight = 0.5f;
            canvasObject.AddComponent<GraphicRaycaster>();
            Manual2ARSceneNavigation.CreateHomeButton(canvasObject.transform);

            var stage = new GameObject("Camera Stage");
            stage.transform.SetParent(canvasObject.transform, false);
            var stageRect = stage.AddComponent<RectTransform>();
            Stretch(stageRect);
            var plane = new GameObject("Aspect Fill Camera Image Plane");
            plane.transform.SetParent(stage.transform, false);
            m_CameraImagePlane = plane.AddComponent<RectTransform>();
            m_CameraImagePlane.anchorMin = new Vector2(0.5f, 0.5f);
            m_CameraImagePlane.anchorMax = new Vector2(0.5f, 0.5f);
            m_CameraImagePlane.pivot = new Vector2(0.5f, 0.5f);
            var content = new GameObject("Camera Pixels And Inspection Masks");
            content.transform.SetParent(plane.transform, false);
            m_CameraContent = content.AddComponent<RectTransform>();
            m_CameraContent.anchorMin = new Vector2(0.5f, 0.5f);
            m_CameraContent.anchorMax = new Vector2(0.5f, 0.5f);
            m_CameraContent.pivot = new Vector2(0.5f, 0.5f);
            m_CameraPreview = content.AddComponent<RawImage>();
            m_CameraPreview.raycastTarget = false;
            m_CameraPreview.color = Color.black;

            m_StatusText = CreateUiText(
                canvasObject.transform,
                "Status",
                new Vector2(0.5f, 0.0f),
                new Vector2(0.0f, 62.0f),
                new Vector2(1500.0f, 54.0f),
                "START CAMERA TO BEGIN",
                Manual2ARVisualTheme.StatusFontSize,
                Manual2ARVisualTheme.TargetCyan);

            m_ControlsRoot = new GameObject("Inspection Controls");
            m_ControlsRoot.transform.SetParent(canvasObject.transform, false);
            var controlsRect = m_ControlsRoot.AddComponent<RectTransform>();
            controlsRect.anchorMin = new Vector2(0.5f, 1.0f);
            controlsRect.anchorMax = new Vector2(0.5f, 1.0f);
            controlsRect.pivot = new Vector2(0.5f, 1.0f);
            controlsRect.anchoredPosition = new Vector2(0.0f, -24.0f);
            controlsRect.sizeDelta = new Vector2(920.0f, 64.0f);
            m_InspectButton = CreateButton(controlsRect, "Inspect Build Plate", -280.0f, "INSPECT / RE-INSPECT", 300.0f);
            m_CaptureEvidenceButton = CreateButton(controlsRect, "Save Evidence", 55.0f, "SAVE EVIDENCE", 260.0f);
            m_ClearOverlayButton = CreateButton(controlsRect, "Clear Overlay", 335.0f, "CLEAR", 220.0f);
            return canvasObject.transform;
        }

        static Text CreateUiText(
            Transform parent,
            string name,
            Vector2 anchor,
            Vector2 anchoredPosition,
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
            rect.pivot = anchor;
            rect.anchoredPosition = anchoredPosition;
            rect.sizeDelta = size;
            var label = go.AddComponent<Text>();
            label.text = value;
            Manual2ARVisualTheme.StyleText(label, fontSize, color, TextAnchor.MiddleCenter);
            Manual2ARVisualTheme.AddTextDepth(go, 3.0f);
            return label;
        }

        static Button CreateButton(
            RectTransform parent,
            string name,
            float x,
            string labelText,
            float width = 216.0f)
        {
            var go = new GameObject(name);
            go.transform.SetParent(parent, false);
            var rect = go.AddComponent<RectTransform>();
            rect.anchorMin = new Vector2(0.5f, 0.5f);
            rect.anchorMax = new Vector2(0.5f, 0.5f);
            rect.anchoredPosition = new Vector2(x, 0.0f);
            rect.sizeDelta = new Vector2(width, 58.0f);
            var image = go.AddComponent<Image>();
            image.color = Manual2ARVisualTheme.ButtonBackground;
            var button = go.AddComponent<Button>();
            var colors = button.colors;
            colors.highlightedColor = new Color(0.03f, 0.48f, 0.62f, 1.0f);
            colors.pressedColor = new Color(0.02f, 0.66f, 0.76f, 1.0f);
            button.colors = colors;
            var labelObject = new GameObject("Text");
            labelObject.transform.SetParent(go.transform, false);
            var labelRect = labelObject.AddComponent<RectTransform>();
            Stretch(labelRect);
            var label = labelObject.AddComponent<Text>();
            label.text = labelText;
            Manual2ARVisualTheme.StyleText(
                label,
                labelText.Length > 17 ? 15 : Manual2ARVisualTheme.ButtonFontSize,
                Color.white,
                TextAnchor.MiddleCenter);
            return button;
        }

        void SetStatus(string message)
        {
            if (m_StatusText != null)
                m_StatusText.text = message;
            Debug.Log($"[Manual2AR] {message}");
        }

        void SetButtonsInteractable(bool interactable)
        {
            if (m_StartCameraButton) m_StartCameraButton.interactable = !m_IsRequestInFlight;
            if (m_SwitchCameraButton)
                m_SwitchCameraButton.interactable = !m_IsRequestInFlight && WebCamTexture.devices.Length > 1;
            var canUseFrame = interactable && HasLiveCamera && !m_IsRequestInFlight;
            if (m_InspectButton) m_InspectButton.interactable = canUseFrame;
            if (m_ReInspectButton) m_ReInspectButton.interactable = canUseFrame;
            if (m_CaptureEvidenceButton)
                m_CaptureEvidenceButton.interactable = canUseFrame &&
                    m_CurrentInspection != null && m_CurrentInspection.status != "uncertain" &&
                    m_States.Count > 0;
            if (m_ClearOverlayButton) m_ClearOverlayButton.interactable = interactable;
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
            if (m_CaptureTexture != null)
                Destroy(m_CaptureTexture);
        }

        sealed class InspectionState
        {
            public string objectId;
            public string objectType;
            public string sessionId;
            public int[] lastBox;
        }

        sealed class PendingTrackingUpdate
        {
            public InspectionState state;
            public TrackingFrameResponse response;
            public string rawResponse;
        }
    }
}
