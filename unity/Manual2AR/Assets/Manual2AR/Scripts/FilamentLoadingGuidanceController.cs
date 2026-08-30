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
    public sealed class FilamentLoadingGuidanceController : MonoBehaviour
    {
        [SerializeField] int m_RequestedCameraWidth = 1280;
        [SerializeField] int m_RequestedCameraHeight = 720;
        [SerializeField] int m_RequestedCameraFps = 30;
        [SerializeField] string m_BackendBaseUrl = "http://127.0.0.1:8010";
        [SerializeField] float m_TrackingIntervalSeconds = 0.5f;

        Manual2ARBackendClient m_BackendClient;
        FilamentLoadingGuidanceOverlay m_Overlay;
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
        FilamentLoadingInspectionResponse m_CurrentInspection;
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
            m_Overlay = gameObject.AddComponent<FilamentLoadingGuidanceOverlay>();
            m_Overlay.Initialize(m_CameraContent, uiRoot);
            SetButtonsInteractable(true);
            Debug.Log(
                $"[Manual2AR] filament loading backend={m_BackendBaseUrl} · " +
                "profile=ams_lite_filament_loading_v1 · expected model=qwen3-vl-flash · " +
                "method=task-conditioned-profile+constraint-guided-SAM · guidance=image-space");
        }

        void OnEnable()
        {
            m_InspectButton.onClick.AddListener(InspectFilamentLoading);
            m_CaptureEvidenceButton.onClick.AddListener(CaptureEvidence);
            m_ClearOverlayButton.onClick.AddListener(ClearOverlay);
        }

        void Start()
        {
            StartCamera();
        }

        void OnDisable()
        {
            m_InspectButton.onClick.RemoveListener(InspectFilamentLoading);
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

        public void InspectFilamentLoading()
        {
            if (m_IsRequestInFlight || !HasLiveCamera)
            {
                if (!HasLiveCamera)
                    SetStatus("START CAMERA BEFORE FILAMENT CHECK");
                return;
            }
            StartCoroutine(InspectRoutine());
        }

        public void ReInspect()
        {
            CloseAndClearAll();
            InspectFilamentLoading();
        }

        public void ClearOverlay()
        {
            CloseAndClearAll();
            SetStatus("FILAMENT OVERLAY CLEARED");
        }

        IEnumerator InspectRoutine()
        {
            m_IsRequestInFlight = true;
            SetButtonsInteractable(false);
            CloseAndClearAll();
            m_LastInspectionResponse = null;
            m_TrackingResponses.Length = 0;
            m_Overlay.ShowProcessing();
            SetStatus("CHECKING FILAMENT PATH · QWEN3-VL-FLASH + SAM2");
            if (!TryCaptureCameraJpg(out var jpg, out var captureError))
            {
                m_IsRequestInFlight = false;
                SetButtonsInteractable(true);
                SetStatus($"CAMERA FRAME FAILED · {captureError}");
                yield break;
            }
            m_LastCameraJpg = jpg;
            FilamentLoadingInspectionResponse response = null;
            string rawResponse = null;
            yield return m_BackendClient.InspectFilamentLoading(
                Convert.ToBase64String(jpg),
                m_WebCamTexture.videoRotationAngle,
                (inspection, raw) =>
                {
                    response = inspection;
                    rawResponse = raw;
                });
            m_LastInspectionResponse = rawResponse;
            m_CurrentInspection = response;
            SaveLatestDiagnostics();
            m_IsRequestInFlight = false;
            SetButtonsInteractable(true);

            if (response == null || !string.IsNullOrEmpty(response.error) ||
                response.status == "uncertain" || response.masks == null ||
                response.masks.Length == 0)
            {
                foreach (var state in m_States.Values)
                    if (!string.IsNullOrEmpty(state.sessionId))
                        StartCoroutine(m_BackendClient.CloseTrackingSession(state.sessionId));
                m_States.Clear();
                m_CurrentInspection = response;
                m_Overlay.ShowUncertain();
                SetButtonsInteractable(true);
                SetStatus("LOADING STATE UNCERTAIN · REFRAME FEEDER + FILAMENT PATH");
                yield break;
            }

            foreach (var mask in response.masks)
            {
                if (mask == null || !AcceptMask(mask))
                {
                    HandleTrackingLost("initial filament mask failed");
                    yield break;
                }
            }
            if (!CurrentGeometryConsistent())
            {
                HandleTrackingLost("initial feeder/filament relation failed");
                yield break;
            }
            m_Overlay.SetInspectionState(response);
            m_LastTrackingTime = Time.unscaledTime;
            SetStatus(response.status == "loaded"
                ? "FILAMENT LOADED · FEEDER + PTFE PATH VERIFIED"
                : "INSERT FILAMENT UPWARD · ALIGN TIP WITH INLET");
            Debug.Log(
                $"[Manual2AR] filament_loading={response.status} · " +
                $"provider={response.provider} · model={response.model} · " +
                $"profile={response.profile_id}@{response.profile_version} · sessions={string.Join(",", ActiveSessionIds())}");
        }

        bool AcceptMask(FilamentLoadingMaskResult result)
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
                    m_CurrentInspection != null ? m_CurrentInspection.status : "uncertain",
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
            InspectionState feeder = null;
            foreach (var state in m_States.Values)
                if (state.objectType == "feeder_module")
                {
                    feeder = state;
                    break;
                }
            if (feeder == null || feeder.lastBox == null || feeder.lastBox.Length < 4)
                return false;
            foreach (var state in m_States.Values)
            {
                if (state.objectType == "feeder_module")
                    continue;
                var box = state.lastBox;
                if (box == null || box.Length < 4)
                    return false;
                var centerX = (box[0] + box[2]) * 0.5f;
                var centerY = (box[1] + box[3]) * 0.5f;
                var feederCenterX = (feeder.lastBox[0] + feeder.lastBox[2]) * 0.5f;
                var feederCenterY = (feeder.lastBox[1] + feeder.lastBox[3]) * 0.5f;
                if (Vector2.Distance(
                        new Vector2(centerX, centerY),
                        new Vector2(feederCenterX, feederCenterY)) > 610.0f)
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
                string overlayError = null;
                if (response == null || !string.IsNullOrEmpty(response.error) ||
                    response.tracked == null || response.tracked.status != "tracking" ||
                    response.tracked.requires_redetection || !response.tracked.mask_quality_passed ||
                    response.tracked.quality < 0.45f ||
                    string.IsNullOrEmpty(response.tracked.overlay_png_base64) ||
                    !m_Overlay.ShowMask(
                        state.objectId,
                        state.objectType,
                        response.tracked,
                        m_CurrentInspection != null ? m_CurrentInspection.status : "uncertain",
                        out overlayError))
                {
                    m_IsRequestInFlight = false;
                    HandleTrackingLost(response?.error ?? overlayError ?? "tracking quality gate failed");
                    yield break;
                }
                if (!string.IsNullOrEmpty(rawResponse))
                    m_TrackingResponses.AppendLine(rawResponse);
                current.lastBox = response.tracked.bbox_0_1000;
            }
            m_LastCameraJpg = jpg;
            m_IsRequestInFlight = false;
            if (!CurrentGeometryConsistent())
            {
                HandleTrackingLost("tracked filament evidence separated from feeder");
                yield break;
            }
            m_Overlay.SetInspectionState(m_CurrentInspection);
            SetStatus(m_CurrentInspection != null && m_CurrentInspection.status == "loaded"
                ? "FILAMENT LOADED · LIVE TRACKING"
                : "INSERT FILAMENT UPWARD · LIVE TRACKING");
        }

        void HandleTrackingLost(string reason)
        {
            Debug.LogWarning($"[Manual2AR] filament tracking lost: {reason}");
            CloseAndClearAll();
            SetStatus("FILAMENT TARGET LOST · RE-INSPECT REQUIRED");
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
                    name = "Manual2AR Filament Loading Capture Frame"
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
                SetStatus("RUN A SUCCESSFUL FILAMENT CHECK BEFORE SAVING");
                return;
            }
            StartCoroutine(CaptureEvidenceRoutine());
        }

        void SaveLatestDiagnostics()
        {
            try
            {
                var diagnosticsRoot = Path.Combine(
                    Application.persistentDataPath,
                    "Manual2AR",
                    "Diagnostics");
                Directory.CreateDirectory(diagnosticsRoot);
                if (m_LastCameraJpg != null && m_LastCameraJpg.Length > 0)
                    File.WriteAllBytes(
                        Path.Combine(diagnosticsRoot, "latest_filament_loading_camera.jpg"),
                        m_LastCameraJpg);
                if (!string.IsNullOrEmpty(m_LastInspectionResponse))
                    File.WriteAllText(
                        Path.Combine(diagnosticsRoot, "latest_filament_loading_response.json"),
                        m_LastInspectionResponse,
                        Encoding.UTF8);
            }
            catch (Exception exception)
            {
                Debug.LogWarning($"[Manual2AR] filament diagnostics unavailable: {exception.Message}");
            }
        }

        IEnumerator CaptureEvidenceRoutine()
        {
            var root = Path.Combine(
                Application.persistentDataPath,
                "Manual2AR",
                "Evidence",
                DateTime.Now.ToString("yyyyMMdd_HHmmss") + "_filament_loading_guidance");
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
                JsonUtility.ToJson(new FilamentLoadingEvidenceLog
                {
                    figure_id = "filament_insertion_guidance_and_loading_verification",
                    backend_base_url = m_BackendClient.backendBaseUrl,
                    profile_id = inspection?.profile_id ?? "ams_lite_filament_loading_v1",
                    profile_version = inspection?.profile_version ?? "unknown",
                    prompt_version = inspection?.prompt_version ?? "unknown",
                    method_label = inspection?.method_label ?? "unknown",
                    exemplar_guided = inspection != null && inspection.exemplar_guided,
                    provider = inspection?.provider ?? "unknown",
                    model = inspection?.model ?? "unknown",
                    loading_status = inspection?.status ?? "none",
                    session_ids = ActiveSessionIds(),
                    loaded_reference_sha256 = inspection?.reference_hashes?.loaded_sha256 ?? "unknown",
                    not_inserted_reference_sha256 = inspection?.reference_hashes?.not_inserted_sha256 ?? "unknown",
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
            var canvasObject = new GameObject("Manual2AR Filament Loading UI");
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

            m_ControlsRoot = new GameObject("Filament Loading Controls");
            m_ControlsRoot.transform.SetParent(canvasObject.transform, false);
            var controlsRect = m_ControlsRoot.AddComponent<RectTransform>();
            controlsRect.anchorMin = new Vector2(0.5f, 1.0f);
            controlsRect.anchorMax = new Vector2(0.5f, 1.0f);
            controlsRect.pivot = new Vector2(0.5f, 1.0f);
            controlsRect.anchoredPosition = new Vector2(0.0f, -24.0f);
            controlsRect.sizeDelta = new Vector2(920.0f, 64.0f);
            m_InspectButton = CreateButton(controlsRect, "Inspect Filament Loading", -280.0f, "CHECK / RE-CHECK", 300.0f);
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
            {
                m_StatusText.text = message;
                var overlayOwnsStatus = m_CurrentInspection != null &&
                    m_CurrentInspection.status != "uncertain" && m_States.Count > 0;
                m_StatusText.gameObject.SetActive(!overlayOwnsStatus);
            }
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
    }
}
