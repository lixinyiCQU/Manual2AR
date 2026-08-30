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
    public sealed class ComponentOverviewTrackingController : MonoBehaviour
    {
        static readonly string[] TargetComponentIds =
        {
            "build_plate",
            "filament_spool",
            "empty_spool_holder"
        };

        [SerializeField] int m_RequestedCameraWidth = 1280;
        [SerializeField] int m_RequestedCameraHeight = 720;
        [SerializeField] int m_RequestedCameraFps = 30;
        [SerializeField] string m_BackendBaseUrl = "http://127.0.0.1:8010";
        [SerializeField] float m_TrackingIntervalSeconds = 0.35f;
        [SerializeField] bool m_AutoRegroundAfterTrackingLoss = true;
        [SerializeField] float m_AutoRegroundDelaySeconds = 0.35f;

        Manual2ARBackendClient m_BackendClient;
        MultiComponentGuidanceOverlay m_Overlay;
        readonly Dictionary<string, ComponentState> m_States = new Dictionary<string, ComponentState>();
        RectTransform m_CameraImagePlane;
        RectTransform m_CameraContent;
        RawImage m_CameraPreview;
        Text m_StatusText;
        Button m_StartCameraButton;
        Button m_SwitchCameraButton;
        Button m_AutoLabelButton;
        Button m_ReGroundButton;
        Button m_CaptureEvidenceButton;
        Button m_ClearOverlayButton;
        GameObject m_ControlsRoot;
        WebCamTexture m_WebCamTexture;
        Texture2D m_CaptureTexture;
        Color32[] m_WebCamPixels;
        byte[] m_LastCameraJpg;
        readonly StringBuilder m_LastRawResponses = new StringBuilder();
        string m_Provider;
        string m_Model;
        int m_CurrentCameraIndex = -1;
        int m_LastLayoutWidth;
        int m_LastLayoutHeight;
        int m_LastVideoRotation = -1;
        bool m_LastVideoMirrored;
        bool m_IsRequestInFlight;
        float m_LastTrackingTime;
        Coroutine m_CameraStartRoutine;
        Coroutine m_AutoRegroundRoutine;

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
            EnsureRuntimeUi();
            m_Overlay = gameObject.AddComponent<MultiComponentGuidanceOverlay>();
            m_Overlay.Initialize(m_CameraContent, m_StatusText.transform.parent);
            SetButtonsInteractable(true);
            Debug.Log(
                $"[Manual2AR] component-overview backend={m_BackendBaseUrl} · " +
                "expected model=qwen3-vl-flash · guidance=image-space");
        }

        void OnEnable()
        {
            m_AutoLabelButton.onClick.AddListener(AutoLabelComponents);
            m_CaptureEvidenceButton.onClick.AddListener(CaptureEvidence);
            m_ClearOverlayButton.onClick.AddListener(ClearOverlay);
        }

        void Start()
        {
            StartCamera();
        }

        void OnDisable()
        {
            m_AutoLabelButton.onClick.RemoveListener(AutoLabelComponents);
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

            CancelScheduledReground();
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

        public void AutoLabelComponents()
        {
            if (m_IsRequestInFlight || !HasLiveCamera)
            {
                if (!HasLiveCamera)
                    SetStatus("START CAMERA BEFORE AUTO LABELING");
                return;
            }
            CancelScheduledReground();
            StartCoroutine(AutoLabelRoutine());
        }

        public void ReGround()
        {
            CancelScheduledReground();
            CloseAndClearAll();
            AutoLabelComponents();
        }

        public void ClearOverlay()
        {
            CancelScheduledReground();
            CloseAndClearAll();
            SetStatus("OVERLAY CLEARED");
        }

        IEnumerator AutoLabelRoutine()
        {
            m_IsRequestInFlight = true;
            SetButtonsInteractable(false);
            CloseAndClearAll();
            m_LastRawResponses.Length = 0;
            var remaining = new List<string>(TargetComponentIds);

            for (var attempt = 1; attempt <= 2 && remaining.Count > 0; attempt++)
            {
                SetStatus(attempt == 1
                    ? "LOCATING COMPONENTS · QWEN FLASH + SAM2"
                    : $"RETRYING {remaining.Count} MISSING COMPONENT(S)");
                if (!TryCaptureCameraJpg(out var jpg, out var captureError))
                {
                    SetStatus($"CAMERA FRAME FAILED · {captureError}");
                    break;
                }
                m_LastCameraJpg = jpg;
                MultiComponentLocateResponse response = null;
                string rawResponse = null;
                yield return m_BackendClient.LocateComponents(
                    Convert.ToBase64String(jpg),
                    remaining.ToArray(),
                    (located, raw) =>
                    {
                        response = located;
                        rawResponse = raw;
                    });
                if (!string.IsNullOrEmpty(rawResponse))
                    m_LastRawResponses.AppendLine(rawResponse);
                if (response != null)
                {
                    m_Provider = response.provider;
                    m_Model = response.model;
                }
                AcceptLocateResponse(response);
                remaining.RemoveAll(componentId => m_States.ContainsKey(componentId));
                if (remaining.Count > 0 && attempt == 1)
                    yield return null;
            }

            m_IsRequestInFlight = false;
            SetButtonsInteractable(true);
            m_LastTrackingTime = Time.unscaledTime;
            SaveLatestDiagnostics();
            if (m_States.Count == 0)
            {
                CloseAndClearAll();
                SetStatus("NO COMPONENT MASK PASSED · RE-GROUND REQUIRED");
                yield break;
            }
            if (m_States.Count == TargetComponentIds.Length)
                SetStatus("3/3 COMPONENTS LOCKED · LIVE TRACKING");
            else
                SetStatus($"{m_States.Count}/3 COMPONENTS LOCKED · RE-GROUND FOR MISSING TARGET");
            Debug.Log(
                $"[Manual2AR] overview locked={m_States.Count}/3 · provider={m_Provider} · " +
                $"model={m_Model} · sessions={string.Join(",", ActiveSessionIds())}");
        }

        void AcceptLocateResponse(MultiComponentLocateResponse response)
        {
            if (response == null || !string.IsNullOrEmpty(response.error) || response.results == null)
                return;
            foreach (var result in response.results)
            {
                if (result == null || string.IsNullOrEmpty(result.component_id) ||
                    m_States.ContainsKey(result.component_id))
                {
                    if (result != null && !string.IsNullOrEmpty(result.session_id))
                        StartCoroutine(m_BackendClient.CloseTrackingSession(result.session_id));
                    continue;
                }
                if (!result.found || !result.tracking_ready || string.IsNullOrEmpty(result.session_id) ||
                    result.tracked == null || result.tracked.status != "tracking" ||
                    result.tracked.requires_redetection || !result.tracked.mask_quality_passed ||
                    result.tracked.quality < 0.50f)
                    continue;
                if (!m_Overlay.Show(
                        result.component_id,
                        result.english_label,
                        result.tracked,
                        out _))
                {
                    StartCoroutine(m_BackendClient.CloseTrackingSession(result.session_id));
                    continue;
                }
                m_States.Add(result.component_id, new ComponentState
                {
                    componentId = result.component_id,
                    englishLabel = result.english_label,
                    sessionId = result.session_id
                });
            }
        }

        IEnumerator SendTrackingFrames()
        {
            if (!TryCaptureCameraJpg(out var jpg, out var captureError))
            {
                HandleTrackingLost($"CAMERA FRAME FAILED · {captureError}");
                yield break;
            }
            m_IsRequestInFlight = true;
            var snapshot = new List<ComponentState>(m_States.Values);
            var imageBase64 = Convert.ToBase64String(jpg);
            var pendingUpdates = new List<PendingTrackingUpdate>(snapshot.Count);
            foreach (var state in snapshot)
            {
                var pending = new PendingTrackingUpdate { state = state };
                pendingUpdates.Add(pending);
                StartCoroutine(RequestTrackingUpdate(pending, imageBase64));
            }

            // The three masks are independent sessions. Send their current-frame
            // updates together instead of waiting for three serial round trips.
            // We still validate the entire batch before displaying any result, so
            // a failed target can never leave a stale mask on screen.
            while (pendingUpdates.Exists(update => !update.completed))
                yield return null;

            foreach (var pending in pendingUpdates)
            {
                var state = pending.state;
                var response = pending.response;
                if (!m_States.TryGetValue(state.componentId, out var current) ||
                    current.sessionId != state.sessionId)
                {
                    m_IsRequestInFlight = false;
                    yield break;
                }
                if (response == null || !string.IsNullOrEmpty(response.error) || response.tracked == null ||
                    response.tracked.status != "tracking" || response.tracked.requires_redetection ||
                    !response.tracked.mask_quality_passed || response.tracked.quality < 0.45f ||
                    string.IsNullOrEmpty(response.tracked.overlay_png_base64))
                {
                    m_IsRequestInFlight = false;
                    HandleTrackingLost(response?.error ?? $"{state.componentId} quality gate failed");
                    yield break;
                }
            }

            m_LastRawResponses.Length = 0;
            foreach (var pending in pendingUpdates)
            {
                var state = pending.state;
                var response = pending.response;
                if (!m_Overlay.Show(
                        state.componentId,
                        state.englishLabel,
                        response.tracked,
                        out var overlayError))
                {
                    m_IsRequestInFlight = false;
                    HandleTrackingLost(overlayError);
                    yield break;
                }
                if (!string.IsNullOrEmpty(pending.rawResponse))
                    m_LastRawResponses.AppendLine(pending.rawResponse);
            }
            m_LastCameraJpg = jpg;
            m_IsRequestInFlight = false;
            SetStatus(m_States.Count == 3
                ? "3/3 COMPONENTS LOCKED · LIVE TRACKING"
                : $"{m_States.Count}/3 COMPONENTS LOCKED · LIVE TRACKING");
        }

        IEnumerator RequestTrackingUpdate(PendingTrackingUpdate pending, string imageBase64)
        {
            yield return m_BackendClient.SendTrackingFrame(
                pending.state.sessionId,
                imageBase64,
                "client_pending",
                0.0f,
                0,
                (updated, raw) =>
                {
                    pending.response = updated;
                    pending.rawResponse = raw;
                });
            pending.completed = true;
        }

        void HandleTrackingLost(string reason)
        {
            Debug.LogWarning($"[Manual2AR] component tracking lost: {reason}");
            CloseAndClearAll();
            SetStatus("COMPONENT TRACKING LOST · RE-GROUND REQUIRED");
            if (m_AutoRegroundAfterTrackingLoss && m_AutoRegroundRoutine == null && HasLiveCamera)
                m_AutoRegroundRoutine = StartCoroutine(AutoRegroundAfterDelay());
        }

        IEnumerator AutoRegroundAfterDelay()
        {
            yield return new WaitForSecondsRealtime(m_AutoRegroundDelaySeconds);
            m_AutoRegroundRoutine = null;
            if (!m_IsRequestInFlight && HasLiveCamera)
                AutoLabelComponents();
        }

        void CancelScheduledReground()
        {
            if (m_AutoRegroundRoutine == null)
                return;
            StopCoroutine(m_AutoRegroundRoutine);
            m_AutoRegroundRoutine = null;
        }

        void CloseAndClearAll()
        {
            m_Overlay?.Clear();
            foreach (var state in m_States.Values)
                if (!string.IsNullOrEmpty(state.sessionId) && m_BackendClient != null)
                    StartCoroutine(m_BackendClient.CloseTrackingSession(state.sessionId));
            m_States.Clear();
        }

        string[] ActiveSessionIds()
        {
            var ids = new List<string>();
            foreach (var state in m_States.Values)
                ids.Add(state.sessionId);
            return ids.ToArray();
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
                        Path.Combine(diagnosticsRoot, "latest_component_overview_camera.jpg"),
                        m_LastCameraJpg);
                if (m_LastRawResponses.Length > 0)
                    File.WriteAllText(
                        Path.Combine(diagnosticsRoot, "latest_component_overview_response.jsonl"),
                        m_LastRawResponses.ToString(),
                        Encoding.UTF8);
            }
            catch (Exception exception)
            {
                Debug.LogWarning($"[Manual2AR] overview diagnostics unavailable: {exception.Message}");
            }
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
                    name = "Manual2AR Component Overview Capture Frame"
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
            StartCoroutine(CaptureEvidenceRoutine());
        }

        IEnumerator CaptureEvidenceRoutine()
        {
            var root = Path.Combine(
                Application.persistentDataPath,
                "Manual2AR",
                "Evidence",
                DateTime.Now.ToString("yyyyMMdd_HHmmss") + "_component_overview");
            Directory.CreateDirectory(root);
            if (TryCaptureCameraJpg(out var currentJpg, out _))
            {
                m_LastCameraJpg = currentJpg;
                File.WriteAllBytes(Path.Combine(root, "camera_frame.jpg"), currentJpg);
            }
            if (m_LastRawResponses.Length > 0)
                File.WriteAllText(
                    Path.Combine(root, "qwen_sam_or_tracking_response.json"),
                    m_LastRawResponses.ToString(),
                    Encoding.UTF8);
            File.WriteAllText(
                Path.Combine(root, "tracking_log.json"),
                JsonUtility.ToJson(new EvidenceLog
                {
                    figure_id = "component_recognition_and_labeling",
                    backend_base_url = m_BackendClient.backendBaseUrl,
                    session_ids = ActiveSessionIds(),
                    provider = m_Provider,
                    model = m_Model,
                    camera_device = m_WebCamTexture != null ? m_WebCamTexture.deviceName : "none",
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
            SetStatus($"EVIDENCE SAVED · {root}");
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
            if (m_AutoLabelButton) m_AutoLabelButton.interactable = canUseFrame;
            if (m_ReGroundButton) m_ReGroundButton.interactable = canUseFrame;
            if (m_CaptureEvidenceButton)
                m_CaptureEvidenceButton.interactable = canUseFrame && m_States.Count > 0;
            if (m_ClearOverlayButton) m_ClearOverlayButton.interactable = interactable;
        }

        void EnsureRuntimeUi()
        {
            if (EventSystem.current == null)
            {
                var eventSystem = new GameObject("EventSystem");
                eventSystem.AddComponent<EventSystem>();
                eventSystem.AddComponent<StandaloneInputModule>();
            }

            var canvasObject = new GameObject("Manual2AR Component Recognition UI");
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

            var content = new GameObject("Camera Pixels And Component Masks");
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
                new Vector2(0.5f, 1.0f),
                new Vector2(0.0f, -108.0f),
                new Vector2(1500.0f, 46.0f),
                "START CAMERA TO BEGIN",
                Manual2ARVisualTheme.StatusFontSize,
                Manual2ARVisualTheme.TargetCyan);

            m_ControlsRoot = new GameObject("Demo Controls");
            m_ControlsRoot.transform.SetParent(canvasObject.transform, false);
            var controlsRect = m_ControlsRoot.AddComponent<RectTransform>();
            controlsRect.anchorMin = new Vector2(0.5f, 1.0f);
            controlsRect.anchorMax = new Vector2(0.5f, 1.0f);
            controlsRect.pivot = new Vector2(0.5f, 1.0f);
            controlsRect.anchoredPosition = new Vector2(0.0f, -24.0f);
            controlsRect.sizeDelta = new Vector2(920.0f, 64.0f);

            m_AutoLabelButton = CreateButton(controlsRect, "Label Components", -280.0f, "LABEL / RE-LABEL", 300.0f);
            m_CaptureEvidenceButton = CreateButton(controlsRect, "Save Evidence", 55.0f, "SAVE EVIDENCE", 260.0f);
            m_ClearOverlayButton = CreateButton(controlsRect, "Clear Overlay", 335.0f, "CLEAR", 220.0f);
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
            Manual2ARVisualTheme.AddTextDepth(go, 2.0f);
            return label;
        }

        static Button CreateButton(
            RectTransform parent,
            string name,
            float x,
            string labelText,
            float width = 204.0f)
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
                labelText.Length > 18 ? 15 : Manual2ARVisualTheme.ButtonFontSize,
                Color.white,
                TextAnchor.MiddleCenter);
            return button;
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

        sealed class ComponentState
        {
            public string componentId;
            public string englishLabel;
            public string sessionId;
        }

        sealed class PendingTrackingUpdate
        {
            public ComponentState state;
            public TrackingFrameResponse response;
            public string rawResponse;
            public bool completed;
        }

        [Serializable]
        sealed class EvidenceLog
        {
            public string figure_id;
            public string backend_base_url;
            public string[] session_ids;
            public string provider;
            public string model;
            public string camera_device;
            public string guidance_space;
            public string captured_at;
        }
    }
}
