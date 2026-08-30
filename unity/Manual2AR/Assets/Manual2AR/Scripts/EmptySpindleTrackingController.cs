using System;
using System.Collections;
using System.IO;
using System.Text;
using Unity.Collections.LowLevel.Unsafe;
using UnityEngine;
using UnityEngine.EventSystems;
using UnityEngine.UI;
using UnityEngine.XR.ARFoundation;
using UnityEngine.XR.ARSubsystems;

namespace Manual2AR
{
    [RequireComponent(typeof(Manual2ARBackendClient))]
    public sealed class EmptySpindleTrackingController : MonoBehaviour
    {
        const int TargetSlotId = 4;
        const string PrimaryInstruction = "MOUNT SPOOL ← RIGHT TO LEFT";
        const string SecondaryInstruction = "SLOT 4 · EMPTY HOLDER LOCKED";
        const string LostInstruction = "TARGET LOST · RE-GROUND REQUIRED";

        [Header("AR fallback (iPhone later)")]
        [SerializeField] ARCameraManager m_CameraManager;
        [SerializeField] ARRaycastManager m_RaycastManager;
        [SerializeField] ARAnchorManager m_AnchorManager;
        [SerializeField] Camera m_ArCamera;

        [Header("Mac camera")]
        [SerializeField] int m_RequestedCameraWidth = 1280;
        [SerializeField] int m_RequestedCameraHeight = 720;
        [SerializeField] int m_RequestedCameraFps = 30;

        [Header("Backend")]
        [SerializeField] string m_BackendBaseUrl = "http://127.0.0.1:8010";

        [Header("Tracking")]
        [SerializeField] bool m_EnableBackendTrackingUpdates = true;
        [SerializeField] float m_BackendTrackingUpdateIntervalSeconds = 0.5f;
        [SerializeField] bool m_AutoRegroundAfterTrackingLoss = true;
        [SerializeField] float m_AutoRegroundDelaySeconds = 0.9f;

        [Header("UI")]
        [SerializeField] Text m_StatusText;
        [SerializeField] RawImage m_CameraPreview;
        [SerializeField] Button m_StartCameraButton;
        [SerializeField] Button m_SwitchCameraButton;
        [SerializeField] Button m_AutoGroundButton;
        [SerializeField] Button m_ReGroundButton;
        [SerializeField] Button m_CaptureEvidenceButton;
        [SerializeField] Button m_ClearOverlayButton;

        Manual2ARBackendClient m_BackendClient;
        ImageSpaceGuidanceOverlay m_Overlay;
        RectTransform m_CameraImagePlane;
        RectTransform m_CameraContent;
        GameObject m_ControlsRoot;
        WebCamTexture m_WebCamTexture;
        Texture2D m_WebCamCaptureTexture;
        Texture2D m_LastArCameraTexture;
        Color32[] m_WebCamPixels;
        byte[] m_LastCameraJpg;
        string m_LastRawResponse;
        EmptySpindleLocateResponse m_LastLocateResponse;
        string m_ActiveSessionId;
        string m_ActiveProvider;
        string m_ActiveModel;
        int m_CurrentCameraIndex = -1;
        int m_LastLayoutWidth;
        int m_LastLayoutHeight;
        int m_LastVideoRotation = -1;
        bool m_LastVideoMirrored;
        float m_LastTrackingUpdateTime;
        bool m_IsRequestInFlight;
        Coroutine m_CameraStartRoutine;
        Coroutine m_AutoRegroundRoutine;

        bool HasLiveWebCam => m_WebCamTexture != null && m_WebCamTexture.isPlaying &&
            m_WebCamTexture.width > 16 && m_WebCamTexture.height > 16;

        void Awake()
        {
            m_BackendClient = GetComponent<Manual2ARBackendClient>();
            m_BackendClient.backendBaseUrl = m_BackendBaseUrl;
            if (m_ArCamera == null)
                m_ArCamera = Camera.main;

            EnsureRuntimeUi();
            m_Overlay = gameObject.AddComponent<ImageSpaceGuidanceOverlay>();
            m_Overlay.Initialize(m_CameraContent, m_StatusText.transform.parent);
            SetButtonsInteractable(true);
            Debug.Log($"[Manual2AR] backend={m_BackendBaseUrl} · expected model=qwen3-vl-flash · guidance=image-space");
        }

        public void Configure(
            ARCameraManager cameraManager,
            ARRaycastManager raycastManager,
            ARAnchorManager anchorManager,
            Camera arCamera,
            string backendBaseUrl)
        {
            m_CameraManager = cameraManager;
            m_RaycastManager = raycastManager;
            m_AnchorManager = anchorManager;
            m_ArCamera = arCamera;
            if (!string.IsNullOrWhiteSpace(backendBaseUrl))
                m_BackendBaseUrl = backendBaseUrl.TrimEnd('/');
            if (m_BackendClient != null)
                m_BackendClient.backendBaseUrl = m_BackendBaseUrl;
        }

        void OnEnable()
        {
            m_AutoGroundButton.onClick.AddListener(AutoGroundSlot4);
            m_CaptureEvidenceButton.onClick.AddListener(CaptureEvidence);
            m_ClearOverlayButton.onClick.AddListener(ClearOverlay);
        }

        void Start()
        {
            StartCamera();
        }

        void OnDisable()
        {
            m_AutoGroundButton.onClick.RemoveListener(AutoGroundSlot4);
            m_CaptureEvidenceButton.onClick.RemoveListener(CaptureEvidence);
            m_ClearOverlayButton.onClick.RemoveListener(ClearOverlay);
            StopWebCam();
        }

        void Update()
        {
            if (HasLiveWebCam &&
                (Screen.width != m_LastLayoutWidth || Screen.height != m_LastLayoutHeight ||
                 m_LastVideoRotation != m_WebCamTexture.videoRotationAngle ||
                 m_LastVideoMirrored != m_WebCamTexture.videoVerticallyMirrored))
                UpdateCameraLayout();

            if (!m_EnableBackendTrackingUpdates || string.IsNullOrEmpty(m_ActiveSessionId) ||
                m_IsRequestInFlight || !CanCaptureCurrentFrame())
                return;

            if (Time.unscaledTime - m_LastTrackingUpdateTime >= m_BackendTrackingUpdateIntervalSeconds)
            {
                m_LastTrackingUpdateTime = Time.unscaledTime;
                StartCoroutine(SendTrackingFrame());
            }
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

        IEnumerator StartWebCamRoutine(bool advanceToNextDevice)
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

            if (advanceToNextDevice && m_CurrentCameraIndex >= 0)
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

            ClearCurrentOverlay(true);
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

            if (!HasLiveWebCam)
            {
                StopWebCam();
                SetStatus($"CAMERA START FAILED · {selected.name}");
                m_CameraStartRoutine = null;
                yield break;
            }

            UpdateCameraLayout();
            SetButtonsInteractable(true);
            SetStatus($"CAMERA READY · {selected.name}");
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
            if (!HasLiveWebCam || m_CameraImagePlane == null || m_CameraContent == null)
                return;

            var sourceWidth = (float)m_WebCamTexture.width;
            var sourceHeight = (float)m_WebCamTexture.height;
            var rotation = ((m_WebCamTexture.videoRotationAngle % 360) + 360) % 360;
            var quarterTurn = rotation == 90 || rotation == 270;
            var orientedWidth = quarterTurn ? sourceHeight : sourceWidth;
            var orientedHeight = quarterTurn ? sourceWidth : sourceHeight;
            var orientedAspect = orientedWidth / Mathf.Max(1.0f, orientedHeight);
            var parentRect = ((RectTransform)m_CameraImagePlane.parent).rect;
            var parentAspect = parentRect.width / Mathf.Max(1.0f, parentRect.height);
            Vector2 planeSize;
            if (parentAspect > orientedAspect)
                planeSize = new Vector2(parentRect.width, parentRect.width / orientedAspect);
            else
                planeSize = new Vector2(parentRect.height * orientedAspect, parentRect.height);

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

        public void AutoGroundSlot4()
        {
            if (m_IsRequestInFlight || !CanCaptureCurrentFrame())
            {
                if (!CanCaptureCurrentFrame())
                    SetStatus("START CAMERA BEFORE AUTO GROUNDING");
                return;
            }
            CancelScheduledReground();
            StartCoroutine(AutoGroundSlot4Routine());
        }

        public void ReGround()
        {
            CancelScheduledReground();
            ClearCurrentOverlay(true);
            AutoGroundSlot4();
        }

        public void ClearOverlay()
        {
            CancelScheduledReground();
            ClearCurrentOverlay(true);
            SetStatus("OVERLAY CLEARED");
        }

        IEnumerator AutoGroundSlot4Routine()
        {
            m_IsRequestInFlight = true;
            SetButtonsInteractable(false);
            ClearCurrentOverlay(true);
            EmptySpindleLocateResponse response = null;
            string validationReason = null;

            for (var attempt = 1; attempt <= 2; attempt++)
            {
                SetStatus(attempt == 1
                    ? "GROUNDING SLOT 4 · QWEN FLASH + SAM2"
                    : "RETRYING QWEN FLASH + SAM2");
                if (!TryCaptureCameraJpg(out var jpg, out var captureError))
                {
                    validationReason = $"CAMERA FRAME FAILED · {captureError}";
                    break;
                }

                m_LastCameraJpg = jpg;
                m_LastLocateResponse = null;
                yield return m_BackendClient.LocateEmptySpindle(
                    Convert.ToBase64String(jpg),
                    TargetSlotId,
                    (located, raw) =>
                    {
                        m_LastLocateResponse = located;
                        m_LastRawResponse = raw;
                    });
                response = m_LastLocateResponse;
                SaveLatestDiagnostics();
                if (IsValidSlot4Response(response, out validationReason))
                    break;
                if (attempt == 2 || !IsTransientLocateFailure(response))
                    break;
                yield return new WaitForSecondsRealtime(0.65f);
            }

            m_IsRequestInFlight = false;
            SetButtonsInteractable(true);
            if (!IsValidSlot4Response(response, out validationReason))
            {
                ClearCurrentOverlay(true);
                SetStatus(validationReason);
                yield break;
            }

            m_ActiveSessionId = response.session_id;
            m_ActiveProvider = response.provider;
            m_ActiveModel = response.model;
            m_LastTrackingUpdateTime = Time.unscaledTime;
            if (!m_Overlay.Show(
                    response.tracked,
                    PrimaryInstruction,
                    SecondaryInstruction,
                    out var overlayError))
            {
                ClearCurrentOverlay(true);
                SetStatus($"MASK DISPLAY FAILED · {overlayError}");
                yield break;
            }

            SetStatus(SecondaryInstruction);
            Debug.Log(
                $"[Manual2AR] locked slot=4 · provider={m_ActiveProvider} · model={m_ActiveModel} · " +
                $"tracking={response.tracked.provider} · session={m_ActiveSessionId}");
        }

        IEnumerator SendTrackingFrame()
        {
            if (!TryCaptureCameraJpg(out var jpg, out var captureError))
            {
                HandleTrackingLost($"CAMERA FRAME FAILED · {captureError}");
                yield break;
            }

            var sessionAtRequest = m_ActiveSessionId;
            if (string.IsNullOrEmpty(sessionAtRequest))
                yield break;

            m_IsRequestInFlight = true;
            TrackingFrameResponse response = null;
            string rawResponse = null;
            yield return m_BackendClient.SendTrackingFrame(
                sessionAtRequest,
                Convert.ToBase64String(jpg),
                "client_pending",
                0.0f,
                0,
                (updated, raw) =>
                {
                    response = updated;
                    rawResponse = raw;
                });
            m_IsRequestInFlight = false;

            if (sessionAtRequest != m_ActiveSessionId)
                yield break;
            if (response == null || !string.IsNullOrEmpty(response.error) || response.tracked == null ||
                response.tracked.status != "tracking" || response.tracked.requires_redetection ||
                !response.tracked.mask_quality_passed || response.tracked.quality < 0.45f)
            {
                HandleTrackingLost(response?.error ?? "tracking quality gate failed");
                yield break;
            }

            if (!m_Overlay.Show(
                    response.tracked,
                    PrimaryInstruction,
                    SecondaryInstruction,
                    out var overlayError))
            {
                HandleTrackingLost(overlayError);
                yield break;
            }

            m_LastCameraJpg = jpg;
            m_LastRawResponse = rawResponse;
            SetStatus(SecondaryInstruction);
        }

        void HandleTrackingLost(string reason)
        {
            ClearCurrentOverlay(true);
            SetStatus(LostInstruction);
            Debug.LogWarning($"[Manual2AR] {LostInstruction} · {reason}");
            if (m_AutoRegroundAfterTrackingLoss && CanCaptureCurrentFrame() && m_AutoRegroundRoutine == null)
                m_AutoRegroundRoutine = StartCoroutine(AutoRegroundAfterDelay());
        }

        IEnumerator AutoRegroundAfterDelay()
        {
            yield return new WaitForSecondsRealtime(m_AutoRegroundDelaySeconds);
            m_AutoRegroundRoutine = null;
            if (!m_IsRequestInFlight && CanCaptureCurrentFrame())
                AutoGroundSlot4();
        }

        void CancelScheduledReground()
        {
            if (m_AutoRegroundRoutine == null)
                return;
            StopCoroutine(m_AutoRegroundRoutine);
            m_AutoRegroundRoutine = null;
        }

        void ClearCurrentOverlay(bool closeSession)
        {
            m_Overlay?.Clear();
            var sessionToClose = m_ActiveSessionId;
            m_ActiveSessionId = null;
            if (closeSession && !string.IsNullOrEmpty(sessionToClose) && m_BackendClient != null)
                StartCoroutine(m_BackendClient.CloseTrackingSession(sessionToClose));
        }

        bool IsValidSlot4Response(EmptySpindleLocateResponse response, out string reason)
        {
            if (response == null)
            {
                reason = "NO MODEL RESPONSE · RE-GROUND REQUIRED";
                return false;
            }

            var error = response.error ?? response.candidate?.failure_reason;
            if (ContainsOccupied(error))
            {
                reason = "SLOT 4 OCCUPIED · SELECT AN EMPTY SLOT";
                return false;
            }
            if (ContainsTargetNotVisible(error))
            {
                var cameraName = HasLiveWebCam && !string.IsNullOrWhiteSpace(m_WebCamTexture.deviceName)
                    ? m_WebCamTexture.deviceName
                    : "SELECTED CAMERA";
                reason = $"SLOT 4 NOT VISIBLE · CAMERA: {cameraName} · AIM AT AMS LITE";
                return false;
            }
            if (!string.IsNullOrEmpty(response.error))
            {
                reason = $"VISION SERVICE ERROR · {response.error}";
                return false;
            }
            if (!response.found || !response.tracking_ready || string.IsNullOrEmpty(response.session_id))
            {
                reason = "SLOT 4 NOT CONFIRMED · RE-GROUND REQUIRED";
                return false;
            }
            if (response.candidate == null || response.candidate.slot_id != TargetSlotId)
            {
                reason = "WRONG SLOT DETECTED · SLOT 4 REQUIRED";
                return false;
            }
            if (response.tracked == null || response.tracked.status != "tracking")
            {
                reason = "SAM MASK NOT TRACKABLE · RE-GROUND REQUIRED";
                return false;
            }
            if (response.tracked.requires_redetection || !response.tracked.mask_quality_passed ||
                response.tracked.quality < 0.58f)
            {
                reason = "MASK QUALITY GATE FAILED · RE-GROUND REQUIRED";
                return false;
            }
            if (string.IsNullOrEmpty(response.tracked.overlay_png_base64))
            {
                reason = "NO VALID CURRENT MASK · RE-GROUND REQUIRED";
                return false;
            }
            reason = null;
            return true;
        }

        static bool ContainsOccupied(string value)
        {
            return !string.IsNullOrEmpty(value) &&
                value.IndexOf("occupied", StringComparison.OrdinalIgnoreCase) >= 0;
        }

        static bool ContainsTargetNotVisible(string value)
        {
            if (string.IsNullOrEmpty(value))
                return false;
            var lower = value.ToLowerInvariant();
            return lower.Contains("no empty spool") || lower.Contains("not clearly visible") ||
                lower.Contains("not visible") || lower.Contains("outside the frame") ||
                lower.Contains("foreground is dominated");
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
                        Path.Combine(diagnosticsRoot, "latest_empty_spindle_camera.jpg"),
                        m_LastCameraJpg);
                if (!string.IsNullOrEmpty(m_LastRawResponse))
                    File.WriteAllText(
                        Path.Combine(diagnosticsRoot, "latest_empty_spindle_response.json"),
                        m_LastRawResponse,
                        Encoding.UTF8);
            }
            catch (Exception exception)
            {
                Debug.LogWarning($"[Manual2AR] spindle diagnostics unavailable: {exception.Message}");
            }
        }

        static bool IsTransientLocateFailure(EmptySpindleLocateResponse response)
        {
            var message = response?.error ?? response?.candidate?.failure_reason;
            if (string.IsNullOrEmpty(message))
                return response == null;
            var lower = message.ToLowerInvariant();
            return lower.Contains("no message content") || lower.Contains("truncated json") ||
                lower.Contains("unavailable") || lower.Contains("timeout") ||
                lower.Contains("temporar") || lower.Contains("connection");
        }

        bool CanCaptureCurrentFrame()
        {
            if (HasLiveWebCam)
                return true;
            if (Application.isEditor || Application.platform == RuntimePlatform.OSXPlayer)
                return false;
            return m_CameraManager != null;
        }

        unsafe bool TryCaptureCameraJpg(out byte[] jpg, out string error)
        {
            jpg = null;
            error = null;
            if (HasLiveWebCam)
            {
                var width = m_WebCamTexture.width;
                var height = m_WebCamTexture.height;
                var pixelCount = width * height;
                if (m_WebCamPixels == null || m_WebCamPixels.Length != pixelCount)
                    m_WebCamPixels = new Color32[pixelCount];
                if (m_WebCamCaptureTexture == null || m_WebCamCaptureTexture.width != width ||
                    m_WebCamCaptureTexture.height != height)
                {
                    if (m_WebCamCaptureTexture != null)
                        Destroy(m_WebCamCaptureTexture);
                    m_WebCamCaptureTexture = new Texture2D(width, height, TextureFormat.RGBA32, false)
                    {
                        name = "Manual2AR WebCam Capture Frame"
                    };
                }

                m_WebCamTexture.GetPixels32(m_WebCamPixels);
                m_WebCamCaptureTexture.SetPixels32(m_WebCamPixels);
                m_WebCamCaptureTexture.Apply(false, false);
                jpg = m_WebCamCaptureTexture.EncodeToJPG(88);
                return jpg != null && jpg.Length > 0;
            }

            if (m_CameraManager == null)
            {
                error = "no WebCamTexture or ARCameraManager";
                return false;
            }
            if (!m_CameraManager.TryAcquireLatestCpuImage(out var image))
            {
                error = "no CPU camera image";
                return false;
            }

            try
            {
                const TextureFormat format = TextureFormat.RGBA32;
                if (m_LastArCameraTexture == null || m_LastArCameraTexture.width != image.width ||
                    m_LastArCameraTexture.height != image.height)
                    m_LastArCameraTexture = new Texture2D(image.width, image.height, format, false);

                var conversionParams = new XRCpuImage.ConversionParams(
                    image,
                    format,
                    XRCpuImage.Transformation.MirrorY);
                var rawTextureData = m_LastArCameraTexture.GetRawTextureData<byte>();
                image.Convert(
                    conversionParams,
                    new IntPtr(rawTextureData.GetUnsafePtr()),
                    rawTextureData.Length);
                m_LastArCameraTexture.Apply();
                jpg = m_LastArCameraTexture.EncodeToJPG(88);
                return true;
            }
            finally
            {
                image.Dispose();
            }
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
                DateTime.Now.ToString("yyyyMMdd_HHmmss"));
            Directory.CreateDirectory(root);
            if (TryCaptureCameraJpg(out var currentJpg, out _))
            {
                m_LastCameraJpg = currentJpg;
                File.WriteAllBytes(Path.Combine(root, "camera_frame.jpg"), currentJpg);
            }
            if (!string.IsNullOrEmpty(m_LastRawResponse))
                File.WriteAllText(
                    Path.Combine(root, "qwen_sam_or_tracking_response.json"),
                    m_LastRawResponse,
                    Encoding.UTF8);

            var trackingLog = JsonUtility.ToJson(new EvidenceTrackingLog
            {
                figure_id = "slot4_empty_spindle_tracking",
                device = "AMS Lite",
                slot_id = TargetSlotId,
                backend_base_url = m_BackendClient.backendBaseUrl,
                session_id = m_ActiveSessionId,
                guidance_space = "image_space",
                camera_device = m_WebCamTexture != null ? m_WebCamTexture.deviceName : "AR camera",
                provider = m_ActiveProvider,
                model = m_ActiveModel,
                captured_at = DateTime.Now.ToString("O")
            }, true);
            File.WriteAllText(Path.Combine(root, "tracking_log.json"), trackingLog, Encoding.UTF8);

            var controlsWereActive = m_ControlsRoot != null && m_ControlsRoot.activeSelf;
            var statusWasActive = m_StatusText != null && m_StatusText.gameObject.activeSelf;
            if (m_ControlsRoot != null)
                m_ControlsRoot.SetActive(false);
            if (m_StatusText != null)
                m_StatusText.gameObject.SetActive(false);
            yield return new WaitForEndOfFrame();
            ScreenCapture.CaptureScreenshot(Path.Combine(root, "overlay_screenshot.png"));
            yield return new WaitForEndOfFrame();
            if (m_ControlsRoot != null)
                m_ControlsRoot.SetActive(controlsWereActive);
            if (m_StatusText != null)
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
            var canUseFrame = interactable && CanCaptureCurrentFrame() && !m_IsRequestInFlight;
            if (m_AutoGroundButton) m_AutoGroundButton.interactable = canUseFrame;
            if (m_ReGroundButton) m_ReGroundButton.interactable = canUseFrame;
            if (m_CaptureEvidenceButton)
                m_CaptureEvidenceButton.interactable = canUseFrame &&
                    !string.IsNullOrEmpty(m_ActiveSessionId) && m_Overlay != null && m_Overlay.isShowing;
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

            var canvasObject = new GameObject("Manual2AR Empty Spindle Tracking UI");
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

            var content = new GameObject("Camera Pixels And Tracking Overlay");
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
                new Vector2(1280.0f, 46.0f),
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

            m_AutoGroundButton = CreateButton(controlsRect, "Ground Slot 4", -280.0f, "GROUND / RE-GROUND SLOT 4", 330.0f);
            m_CaptureEvidenceButton = CreateButton(controlsRect, "Save Evidence", 75.0f, "SAVE EVIDENCE", 250.0f);
            m_ClearOverlayButton = CreateButton(controlsRect, "Clear Overlay", 345.0f, "CLEAR", 220.0f);
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
                Manual2ARVisualTheme.ButtonFontSize,
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
            if (m_WebCamCaptureTexture != null)
                Destroy(m_WebCamCaptureTexture);
            if (m_LastArCameraTexture != null)
                Destroy(m_LastArCameraTexture);
        }

        [Serializable]
        sealed class EvidenceTrackingLog
        {
            public string figure_id;
            public string device;
            public int slot_id;
            public string backend_base_url;
            public string session_id;
            public string guidance_space;
            public string camera_device;
            public string provider;
            public string model;
            public string captured_at;
        }
    }
}
