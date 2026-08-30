using System.Collections;
using TMPro;
using UnityEngine;
using UnityEngine.EventSystems;
using UnityEngine.SceneManagement;
using UnityEngine.UI;

namespace Manual2AR
{
    /// <summary>
    /// Deterministic, backend-independent recording frontend for the prepared
    /// A1 mini + AMS Lite demonstration package.
    /// </summary>
    public sealed class Manual2ARWorkflowController : MonoBehaviour
    {
        enum Page
        {
            Welcome,
            Source,
            Library,
            Scan,
            Analysis,
            Tasks,
            TaskDetail
        }

        static readonly Color Background = new Color(0.004f, 0.018f, 0.032f, 1.0f);
        static readonly Color Surface = new Color(0.012f, 0.055f, 0.080f, 0.97f);
        static readonly Color SurfaceRaised = new Color(0.018f, 0.095f, 0.125f, 0.98f);
        static readonly Color Muted = new Color(0.55f, 0.76f, 0.81f, 1.0f);
        static readonly Color Dimmed = new Color(0.26f, 0.40f, 0.44f, 1.0f);
        static readonly Color Warning = new Color(1.0f, 0.70f, 0.25f, 1.0f);

        Canvas m_Canvas;
        RectTransform m_PageRoot;
        Coroutine m_AnalysisRoutine;
        WebCamTexture m_ScanCamera;
        RawImage m_ScanPreview;
        TextMeshProUGUI m_ScanCounter;
        TextMeshProUGUI m_ScanStatus;
        TextMeshProUGUI m_AnalysisStage;
        TextMeshProUGUI m_AnalysisDetail;
        Image m_AnalysisProgressFill;
        GameObject m_AnalysisCompletePanel;
        Button m_AnalysisContinueButton;

        bool m_A1Selected;
        bool m_AmsSelected;
        string m_UnknownPdfName;
        int m_CapturedPages;

        void Awake()
        {
            EnsureEventSystem();
            BuildCanvas();
            if (Manual2ARSceneNavigation.ConsumeWorkflowTaskDetailRequest())
                Show(Page.TaskDetail);
            else
                Show(Page.Welcome);
        }

        void OnDestroy()
        {
            StopScanner();
            if (m_AnalysisRoutine != null)
                StopCoroutine(m_AnalysisRoutine);
        }

        static void EnsureEventSystem()
        {
            if (EventSystem.current != null)
                return;
            var eventSystem = new GameObject("EventSystem");
            eventSystem.AddComponent<EventSystem>();
            eventSystem.AddComponent<StandaloneInputModule>();
        }

        void BuildCanvas()
        {
            var canvasObject = new GameObject("Manual2AR Workflow UI");
            canvasObject.transform.SetParent(transform, false);
            m_Canvas = canvasObject.AddComponent<Canvas>();
            m_Canvas.renderMode = RenderMode.ScreenSpaceOverlay;
            m_Canvas.pixelPerfect = true;
            var scaler = canvasObject.AddComponent<CanvasScaler>();
            scaler.uiScaleMode = CanvasScaler.ScaleMode.ScaleWithScreenSize;
            scaler.referenceResolution = new Vector2(1920.0f, 1080.0f);
            scaler.matchWidthOrHeight = 0.5f;
            canvasObject.AddComponent<GraphicRaycaster>();

            var background = CreatePanel(canvasObject.transform, "Background", Background,
                Vector2.zero, Vector2.one, Vector2.zero, Vector2.zero);
            background.GetComponent<Image>().raycastTarget = false;

            CreateAccentLine(canvasObject.transform, 0.0f, Manual2ARVisualTheme.TargetCyan);
            CreateAccentLine(canvasObject.transform, 1.0f, new Color(0.02f, 0.24f, 0.30f, 1.0f));
        }

        void CreateAccentLine(Transform parent, float normalizedY, Color color)
        {
            var line = CreatePanel(parent, "Accent Line", color,
                new Vector2(0.0f, normalizedY), new Vector2(1.0f, normalizedY),
                Vector2.zero, new Vector2(0.0f, normalizedY < 0.5f ? 4.0f : -4.0f));
            line.GetComponent<Image>().raycastTarget = false;
        }

        void Show(Page page)
        {
            StopScanner();
            if (m_AnalysisRoutine != null)
            {
                StopCoroutine(m_AnalysisRoutine);
                m_AnalysisRoutine = null;
            }
            if (m_PageRoot != null)
                Destroy(m_PageRoot.gameObject);

            var pageObject = new GameObject(page + " Page");
            pageObject.transform.SetParent(m_Canvas.transform, false);
            m_PageRoot = pageObject.AddComponent<RectTransform>();
            Stretch(m_PageRoot);

            switch (page)
            {
                case Page.Welcome: BuildWelcome(); break;
                case Page.Source: BuildSource(); break;
                case Page.Library: BuildLibrary(); break;
                case Page.Scan: BuildScan(); break;
                case Page.Analysis: BuildAnalysis(); break;
                case Page.Tasks: BuildTasks(); break;
                case Page.TaskDetail: BuildTaskDetail(); break;
            }
        }

        public void OpenTaskSelectionForRecording()
        {
            Show(Page.Tasks);
        }

        void BuildWelcome()
        {
            CreateText(m_PageRoot, "Kicker", new Vector2(0.085f, 0.79f), new Vector2(0.82f, 0.87f),
                "MANUAL  →  ACTION", 23, Manual2ARVisualTheme.TargetCyan, TextAnchor.MiddleLeft);
            CreateText(m_PageRoot, "Title", new Vector2(0.08f, 0.55f), new Vector2(0.78f, 0.79f),
                "MANUAL2AR", 88, Color.white, TextAnchor.MiddleLeft);
            CreateText(m_PageRoot, "Subtitle", new Vector2(0.085f, 0.43f), new Vector2(0.75f, 0.57f),
                "Turn equipment manuals into visual, task-based guidance", 32,
                Manual2ARVisualTheme.TargetLabel, TextAnchor.UpperLeft);

            var flow = CreatePanel(m_PageRoot, "Workflow Summary", Surface,
                new Vector2(0.085f, 0.20f), new Vector2(0.69f, 0.39f), Vector2.zero, Vector2.zero);
            AddOutline(flow, new Color(0.04f, 0.54f, 0.64f, 0.70f), 2.0f);
            CreateText(flow.transform, "Flow", new Vector2(0.04f, 0.18f), new Vector2(0.96f, 0.82f),
                "01  IMPORT OR SCAN\n02  ANALYZE MANUALS\n03  SELECT A TASK\n04  OPEN VISUAL GUIDANCE", 24,
                Muted, TextAnchor.MiddleLeft);

            CreateButton(m_PageRoot, "Start Guidance", "START GUIDANCE  →",
                new Vector2(0.72f, 0.20f), new Vector2(0.915f, 0.31f),
                Manual2ARVisualTheme.TargetCyan, Background, () => Show(Page.Source), 22);

            CreateText(m_PageRoot, "Mode", new Vector2(0.72f, 0.13f), new Vector2(0.915f, 0.19f),
                "RECORDING FRONTEND · 16:9", 15, Muted, TextAnchor.MiddleCenter);
        }

        void BuildSource()
        {
            BuildHeader("CHOOSE MANUAL SOURCE", "Start with a PDF or capture printed manual pages.",
                "01 / 04", () => Show(Page.Welcome));

            CreateChoiceCard(new Vector2(0.08f, 0.20f), new Vector2(0.48f, 0.72f),
                "01", "IMPORT PDF", "Select the prepared A1 mini and AMS Lite manuals.",
                "OPEN MANUAL LIBRARY", () => Show(Page.Library));
            CreateChoiceCard(new Vector2(0.52f, 0.20f), new Vector2(0.92f, 0.72f),
                "02", "SCAN MANUAL", "Capture printed pages with a live camera preview.",
                "OPEN CAMERA", () => Show(Page.Scan));

            CreateFooterStatus("NO BACKEND REQUIRED · PRE-REVIEWED DEMONSTRATION CATALOG");
        }

        void CreateChoiceCard(Vector2 min, Vector2 max, string index, string title,
            string detail, string action, UnityEngine.Events.UnityAction onClick)
        {
            var card = CreatePanel(m_PageRoot, title + " Card", Surface, min, max, Vector2.zero, Vector2.zero);
            AddOutline(card, new Color(0.03f, 0.62f, 0.72f, 0.70f), 3.0f);
            CreateBadge(card.transform, index, new Vector2(0.07f, 0.73f), new Vector2(0.22f, 0.88f),
                Manual2ARVisualTheme.TargetCyan, Background);
            CreateText(card.transform, "Title", new Vector2(0.07f, 0.49f), new Vector2(0.93f, 0.69f),
                title, 36, Color.white, TextAnchor.MiddleLeft);
            CreateText(card.transform, "Detail", new Vector2(0.07f, 0.31f), new Vector2(0.90f, 0.48f),
                detail, 22, Muted, TextAnchor.UpperLeft);
            CreateButton(card.transform, "Action", action + "  →",
                new Vector2(0.07f, 0.10f), new Vector2(0.60f, 0.24f),
                Manual2ARVisualTheme.ButtonBackground, Color.white, onClick, 17);
        }

        void BuildLibrary()
        {
            BuildHeader("MANUAL LIBRARY", "Select both prepared manuals to unlock the demonstration task.",
                "01 / 04", () => Show(Page.Source));

            CreateManualCard(new Vector2(0.08f, 0.49f), new Vector2(0.92f, 0.72f),
                "A1", "Bambu Lab A1 mini Quick Start Guide", "A1 MINI · QUICK START",
                m_A1Selected, () => { m_A1Selected = !m_A1Selected; Show(Page.Library); });
            CreateManualCard(new Vector2(0.08f, 0.23f), new Vector2(0.92f, 0.46f),
                "AMS", "Bambu Lab AMS Lite Quick Start Guide", "AMS LITE · LOADING PAGES",
                m_AmsSelected, () => { m_AmsSelected = !m_AmsSelected; Show(Page.Library); });

            var addLabel = string.IsNullOrWhiteSpace(m_UnknownPdfName)
                ? "ADD PDF"
                : "IMPORTED · NOT MATCHED";
            CreateButton(m_PageRoot, "Add PDF", addLabel,
                new Vector2(0.08f, 0.105f), new Vector2(0.29f, 0.175f),
                SurfaceRaised, Color.white, AddPdf, 17);
            if (!string.IsNullOrWhiteSpace(m_UnknownPdfName))
            {
                CreateText(m_PageRoot, "Unknown PDF", new Vector2(0.31f, 0.105f), new Vector2(0.58f, 0.175f),
                    ShortName(m_UnknownPdfName) + " · does not unlock this demo", 15,
                    Warning, TextAnchor.MiddleLeft);
            }

            var selectedCount = (m_A1Selected ? 1 : 0) + (m_AmsSelected ? 1 : 0);
            var analyze = CreateButton(m_PageRoot, "Analyze Manuals", $"ANALYZE {selectedCount} MANUALS  →",
                new Vector2(0.67f, 0.09f), new Vector2(0.92f, 0.18f),
                selectedCount == 2 ? Manual2ARVisualTheme.TargetCyan : SurfaceRaised,
                selectedCount == 2 ? Background : Dimmed,
                () => Show(Page.Analysis), 19);
            analyze.interactable = selectedCount == 2;
            CreateFooterStatus(selectedCount == 2
                ? "BOTH PREPARED MANUALS SELECTED · READY TO ANALYZE"
                : "SELECT BOTH PREPARED MANUALS");
        }

        void CreateManualCard(Vector2 min, Vector2 max, string code, string title, string meta,
            bool selected, UnityEngine.Events.UnityAction onClick)
        {
            var color = selected ? new Color(0.015f, 0.13f, 0.16f, 0.98f) : Surface;
            var card = CreatePanel(m_PageRoot, title + " Card", color, min, max, Vector2.zero, Vector2.zero);
            AddOutline(card, selected ? Manual2ARVisualTheme.SuccessGreen : new Color(0.08f, 0.30f, 0.35f, 1.0f),
                selected ? 3.0f : 2.0f);
            CreateBadge(card.transform, code, new Vector2(0.035f, 0.24f), new Vector2(0.14f, 0.76f),
                selected ? Manual2ARVisualTheme.SuccessGreen : Manual2ARVisualTheme.TargetCyan, Background);
            CreateText(card.transform, "Title", new Vector2(0.18f, 0.48f), new Vector2(0.72f, 0.82f),
                title, 28, Color.white, TextAnchor.MiddleLeft);
            CreateText(card.transform, "Meta", new Vector2(0.18f, 0.18f), new Vector2(0.72f, 0.48f),
                meta, 16, Muted, TextAnchor.MiddleLeft);
            CreateBadge(card.transform, selected ? "SELECTED" : "READY",
                new Vector2(0.76f, 0.34f), new Vector2(0.94f, 0.66f),
                selected ? Manual2ARVisualTheme.SuccessGreen : SurfaceRaised,
                selected ? Background : Manual2ARVisualTheme.TargetLabel);

            var button = card.AddComponent<Button>();
            button.transition = Selectable.Transition.ColorTint;
            button.onClick.AddListener(onClick);
        }

        void AddPdf()
        {
#if UNITY_EDITOR
            var path = UnityEditor.EditorUtility.OpenFilePanel("Add equipment manual", string.Empty, "pdf");
            if (string.IsNullOrWhiteSpace(path))
                return;
            var fileName = System.IO.Path.GetFileName(path);
            var normalized = fileName.ToLowerInvariant();
            if (normalized.Contains("a1") && normalized.Contains("mini"))
                m_A1Selected = true;
            else if (normalized.Contains("ams"))
                m_AmsSelected = true;
            else
                m_UnknownPdfName = fileName;
            Show(Page.Library);
#else
            m_UnknownPdfName = "External PDF";
            Show(Page.Library);
#endif
        }

        void BuildScan()
        {
            BuildHeader("SCAN MANUAL", "Capture clear, flat pages inside the frame.",
                "01 / 04", () => Show(Page.Source));

            var previewPanel = CreatePanel(m_PageRoot, "Camera Preview Panel", new Color(0.01f, 0.02f, 0.025f, 1.0f),
                new Vector2(0.08f, 0.19f), new Vector2(0.69f, 0.73f), Vector2.zero, Vector2.zero);
            AddOutline(previewPanel, new Color(0.03f, 0.58f, 0.68f, 0.85f), 3.0f);
            var previewObject = new GameObject("Live Camera Preview");
            previewObject.transform.SetParent(previewPanel.transform, false);
            var previewRect = previewObject.AddComponent<RectTransform>();
            previewRect.anchorMin = new Vector2(0.02f, 0.035f);
            previewRect.anchorMax = new Vector2(0.98f, 0.965f);
            previewRect.offsetMin = Vector2.zero;
            previewRect.offsetMax = Vector2.zero;
            m_ScanPreview = previewObject.AddComponent<RawImage>();
            m_ScanPreview.color = new Color(0.16f, 0.22f, 0.24f, 1.0f);
            var fitter = previewObject.AddComponent<AspectRatioFitter>();
            fitter.aspectMode = AspectRatioFitter.AspectMode.EnvelopeParent;
            fitter.aspectRatio = 16.0f / 9.0f;

            var guide = CreatePanel(previewPanel.transform, "Page Frame", Color.clear,
                new Vector2(0.20f, 0.10f), new Vector2(0.80f, 0.90f), Vector2.zero, Vector2.zero);
            AddOutline(guide, Manual2ARVisualTheme.TargetCyan, 3.0f);
            guide.GetComponent<Image>().raycastTarget = false;

            var actionPanel = CreatePanel(m_PageRoot, "Scan Actions", Surface,
                new Vector2(0.72f, 0.19f), new Vector2(0.92f, 0.73f), Vector2.zero, Vector2.zero);
            CreateText(actionPanel.transform, "Title", new Vector2(0.10f, 0.79f), new Vector2(0.90f, 0.92f),
                "PAGE CAPTURE", 23, Color.white, TextAnchor.MiddleLeft);
            m_ScanCounter = CreateText(actionPanel.transform, "Counter", new Vector2(0.10f, 0.64f), new Vector2(0.90f, 0.78f),
                CapturedPageLabel(), 21, Manual2ARVisualTheme.TargetCyan, TextAnchor.MiddleLeft);
            m_ScanStatus = CreateText(actionPanel.transform, "Status", new Vector2(0.10f, 0.46f), new Vector2(0.90f, 0.63f),
                "Starting camera…", 16, Muted, TextAnchor.UpperLeft);
            CreateButton(actionPanel.transform, "Capture", "CAPTURE PAGE",
                new Vector2(0.10f, 0.31f), new Vector2(0.90f, 0.43f),
                Manual2ARVisualTheme.TargetCyan, Background, CapturePage, 17);
            CreateButton(actionPanel.transform, "Remove", "REMOVE LAST",
                new Vector2(0.10f, 0.18f), new Vector2(0.90f, 0.29f),
                SurfaceRaised, Color.white, RemoveLastPage, 16);
            var finish = CreateButton(actionPanel.transform, "Finish", "FINISH SCANNING  →",
                new Vector2(0.10f, 0.045f), new Vector2(0.90f, 0.155f),
                m_CapturedPages >= 2 ? Manual2ARVisualTheme.SuccessGreen : SurfaceRaised,
                m_CapturedPages >= 2 ? Background : Dimmed, FinishScanning, 16);
            finish.interactable = m_CapturedPages >= 2;

            CreateFooterStatus("CAPTURE AT LEAST TWO CLEAR PAGES TO CONTINUE");
            StartScanner();
        }

        void StartScanner()
        {
            var devices = WebCamTexture.devices;
            if (!Manual2ARCameraSelection.TryResolve(devices, out var cameraIndex, out var message))
            {
                if (m_ScanStatus != null)
                {
                    m_ScanStatus.text = message;
                    m_ScanStatus.color = Warning;
                }
                return;
            }
            m_ScanCamera = new WebCamTexture(devices[cameraIndex].name, 1280, 720, 30);
            m_ScanPreview.texture = m_ScanCamera;
            m_ScanCamera.Play();
            if (m_ScanStatus != null)
            {
                m_ScanStatus.text = "CAMERA READY\n" +
                    Manual2ARCameraSelection.ModeLabel(Manual2ARCameraSelection.mode);
                m_ScanStatus.color = Manual2ARVisualTheme.SuccessGreen;
            }
        }

        void StopScanner()
        {
            if (m_ScanCamera == null)
                return;
            if (m_ScanCamera.isPlaying)
                m_ScanCamera.Stop();
            Destroy(m_ScanCamera);
            m_ScanCamera = null;
        }

        void CapturePage()
        {
            m_CapturedPages++;
            Show(Page.Scan);
        }

        void RemoveLastPage()
        {
            m_CapturedPages = Mathf.Max(0, m_CapturedPages - 1);
            Show(Page.Scan);
        }

        void FinishScanning()
        {
            if (m_CapturedPages < 2)
                return;
            m_A1Selected = true;
            m_AmsSelected = true;
            Show(Page.Analysis);
        }

        string CapturedPageLabel()
        {
            return m_CapturedPages == 1 ? "1 page captured" : $"{m_CapturedPages} pages captured";
        }

        void BuildAnalysis()
        {
            BuildHeader("ANALYZE MANUALS", "Building a stable task catalog from the prepared manuals.",
                "02 / 04", () => Show(Page.Library));

            var card = CreatePanel(m_PageRoot, "Analysis Card", Surface,
                new Vector2(0.16f, 0.23f), new Vector2(0.84f, 0.69f), Vector2.zero, Vector2.zero);
            AddOutline(card, new Color(0.03f, 0.58f, 0.68f, 0.72f), 3.0f);
            CreateBadge(card.transform, "ANALYZING", new Vector2(0.06f, 0.76f), new Vector2(0.23f, 0.88f),
                Manual2ARVisualTheme.TargetCyan, Background);
            m_AnalysisStage = CreateText(card.transform, "Stage", new Vector2(0.06f, 0.51f), new Vector2(0.94f, 0.74f),
                "Reading manual pages", 34, Color.white, TextAnchor.MiddleLeft);
            m_AnalysisDetail = CreateText(card.transform, "Detail", new Vector2(0.06f, 0.39f), new Vector2(0.94f, 0.52f),
                "Preparing 2 source documents", 18, Muted, TextAnchor.MiddleLeft);

            var progressTrack = CreatePanel(card.transform, "Progress Track", new Color(0.03f, 0.16f, 0.20f, 1.0f),
                new Vector2(0.06f, 0.29f), new Vector2(0.94f, 0.35f), Vector2.zero, Vector2.zero);
            var fill = CreatePanel(progressTrack.transform, "Progress Fill", Manual2ARVisualTheme.TargetCyan,
                Vector2.zero, new Vector2(0.10f, 1.0f), Vector2.zero, Vector2.zero);
            m_AnalysisProgressFill = fill.GetComponent<Image>();
            m_AnalysisProgressFill.rectTransform.pivot = new Vector2(0.0f, 0.5f);

            m_AnalysisCompletePanel = CreatePanel(card.transform, "Complete Summary", new Color(0.02f, 0.18f, 0.15f, 0.95f),
                new Vector2(0.06f, 0.08f), new Vector2(0.61f, 0.23f), Vector2.zero, Vector2.zero);
            CreateText(m_AnalysisCompletePanel.transform, "Summary", new Vector2(0.05f, 0.0f), new Vector2(0.95f, 1.0f),
                "2 manuals analyzed  ·  4 tasks generated", 18,
                Manual2ARVisualTheme.SuccessGreen, TextAnchor.MiddleCenter);
            m_AnalysisCompletePanel.SetActive(false);

            m_AnalysisContinueButton = CreateButton(card.transform, "Continue", "VIEW GENERATED TASKS  →",
                new Vector2(0.65f, 0.08f), new Vector2(0.94f, 0.23f),
                Manual2ARVisualTheme.SuccessGreen, Background, () => Show(Page.Tasks), 16);
            m_AnalysisContinueButton.gameObject.SetActive(false);
            CreateFooterStatus("PRE-REVIEWED DEMONSTRATION CATALOG · RESULTS REMAIN STABLE BETWEEN RECORDINGS");
            m_AnalysisRoutine = StartCoroutine(RunAnalysis());
        }

        IEnumerator RunAnalysis()
        {
            var stages = new[]
            {
                "Reading manual pages",
                "Identifying equipment",
                "Extracting executable tasks",
                "Building visual guidance modules"
            };
            var details = new[]
            {
                "Preparing 2 source documents",
                "A1 mini and AMS Lite matched",
                "Separating assembly, setup, loading and maintenance",
                "Mapping 4 modules to 6 demonstration results"
            };

            for (var index = 0; index < stages.Length; index++)
            {
                m_AnalysisStage.text = stages[index];
                m_AnalysisDetail.text = details[index];
                var progress = (index + 1.0f) / stages.Length;
                m_AnalysisProgressFill.rectTransform.anchorMax = new Vector2(progress, 1.0f);
                yield return new WaitForSecondsRealtime(0.72f);
            }

            m_AnalysisStage.text = "Manual analysis complete";
            m_AnalysisStage.color = Manual2ARVisualTheme.SuccessGreen;
            m_AnalysisDetail.text = "The prepared task catalog is ready.";
            m_AnalysisCompletePanel.SetActive(true);
            m_AnalysisContinueButton.gameObject.SetActive(true);
            m_AnalysisRoutine = null;
        }

        void BuildTasks()
        {
            BuildHeader("SELECT A TASK", "Choose what you want to complete with the imported manuals.",
                "03 / 04", () => Show(Page.Library));

            CreateTaskCard(new Vector2(0.08f, 0.49f), new Vector2(0.48f, 0.72f),
                "01", "INITIAL ASSEMBLY", "Mechanical setup and first installation checks",
                false, null);
            CreateTaskCard(new Vector2(0.52f, 0.49f), new Vector2(0.92f, 0.72f),
                "02", "CONNECTION & CALIBRATION", "Connect the system and prepare the printer",
                false, null);
            CreateTaskCard(new Vector2(0.08f, 0.20f), new Vector2(0.48f, 0.45f),
                "03", "LOADING & PRINTING", "Load filament and verify the printer before starting",
                true, () => Show(Page.TaskDetail));
            CreateTaskCard(new Vector2(0.52f, 0.20f), new Vector2(0.92f, 0.45f),
                "04", "MAINTENANCE & RECOVERY", "Inspect, maintain and recover the printer system",
                false, null);

            CreateFooterStatus("2 MANUALS ANALYZED · 4 TASKS READY · SELECT ONE TO CONTINUE");
        }

        void CreateTaskCard(Vector2 min, Vector2 max, string number, string title,
            string detail, bool opensDemo, UnityEngine.Events.UnityAction onClick)
        {
            var card = CreatePanel(m_PageRoot, title + " Task", SurfaceRaised,
                min, max, Vector2.zero, Vector2.zero);
            AddOutline(card, Manual2ARVisualTheme.TargetCyan, 2.0f);
            CreateBadge(card.transform, number, new Vector2(0.045f, 0.60f), new Vector2(0.16f, 0.83f),
                Manual2ARVisualTheme.TargetCyan, Background);
            CreateBadge(card.transform, "TASK READY",
                new Vector2(0.58f, 0.68f), new Vector2(0.94f, 0.84f),
                new Color(0.02f, 0.20f, 0.23f, 1.0f), Manual2ARVisualTheme.TargetCyan);
            CreateText(card.transform, "Title", new Vector2(0.045f, 0.34f), new Vector2(0.94f, 0.62f),
                title, 26, Color.white, TextAnchor.MiddleLeft);
            CreateText(card.transform, "Detail", new Vector2(0.045f, 0.08f), new Vector2(0.84f, 0.34f),
                detail, 17, Muted, TextAnchor.UpperLeft);
            var button = card.AddComponent<Button>();
            if (opensDemo && onClick != null)
                button.onClick.AddListener(onClick);
        }

        void BuildTaskDetail()
        {
            BuildHeader("LOADING & PRINTING", "A manual-derived task composed of four visual guidance modules.",
                "04 / 04", () => Show(Page.Tasks));

            var modules = CreatePanel(m_PageRoot, "Modules", Surface,
                new Vector2(0.055f, 0.145f), new Vector2(0.71f, 0.75f), Vector2.zero, Vector2.zero);
            AddOutline(modules, new Color(0.03f, 0.44f, 0.52f, 0.75f), 2.0f);
            CreateText(modules.transform, "Section", new Vector2(0.035f, 0.89f), new Vector2(0.55f, 0.97f),
                "4 VISUAL GUIDANCE MODULES", 17, Manual2ARVisualTheme.TargetCyan, TextAnchor.MiddleLeft);

            CreateModuleRow(modules.transform, 1, "COMPONENT RECOGNITION", "FIGURE 1",
                "Identify the build plate, filament spool and empty spool holder", 0.69f);
            CreateModuleRow(modules.transform, 2, "GUIDED SPOOL PLACEMENT", "FIGURE 2",
                "Locate the empty holder and guide spool placement", 0.47f);
            CreateModuleRow(modules.transform, 3, "FILAMENT GUIDANCE & VERIFICATION", "FIGURES 3–4",
                "Guide filament insertion and verify successful loading", 0.25f);
            CreateModuleRow(modules.transform, 4, "PRE-PRINT INSPECTION & CORRECTION", "FIGURES 5–6",
                "Inspect the build plate and provide corrective guidance", 0.03f);

            var info = CreatePanel(m_PageRoot, "Task Information", SurfaceRaised,
                new Vector2(0.735f, 0.145f), new Vector2(0.945f, 0.75f), Vector2.zero, Vector2.zero);
            CreateText(info.transform, "Sources Header", new Vector2(0.09f, 0.84f), new Vector2(0.91f, 0.93f),
                "SOURCE MANUALS", 15, Manual2ARVisualTheme.TargetCyan, TextAnchor.MiddleLeft);
            CreateText(info.transform, "Sources", new Vector2(0.09f, 0.66f), new Vector2(0.91f, 0.84f),
                "A1 mini Quick Start Guide\nAMS Lite Quick Start Guide", 18, Color.white, TextAnchor.UpperLeft);
            CreateText(info.transform, "Safety Header", new Vector2(0.09f, 0.53f), new Vector2(0.91f, 0.61f),
                "KEY SAFETY CONDITIONS", 15, Manual2ARVisualTheme.TargetCyan, TextAnchor.MiddleLeft);
            CreateText(info.transform, "Safety", new Vector2(0.09f, 0.24f), new Vector2(0.91f, 0.52f),
                "• Printer remains idle\n• Do not press the release button during normal loading\n• Re-inspect the build plate after correction",
                16, Manual2ARVisualTheme.TargetLabel, TextAnchor.UpperLeft);
            CreateBadge(info.transform, "6 DEMONSTRATION RESULTS", new Vector2(0.09f, 0.11f), new Vector2(0.91f, 0.20f),
                new Color(0.02f, 0.20f, 0.23f, 1.0f), Manual2ARVisualTheme.TargetCyan);

            CreateButton(m_PageRoot, "Start Task", "START TASK  →",
                new Vector2(0.735f, 0.055f), new Vector2(0.945f, 0.125f),
                Manual2ARVisualTheme.SuccessGreen, Background,
                () => SceneManager.LoadScene(Manual2ARSceneNavigation.HubSceneName), 20);
            CreateFooterStatus("TASK READY · SELECT START TASK TO OPEN THE FOUR LIVE MODULES");
        }

        void CreateModuleRow(Transform parent, int number, string title, string figure, string detail, float y)
        {
            var row = CreatePanel(parent, "Module " + number, new Color(0.015f, 0.085f, 0.11f, 1.0f),
                new Vector2(0.025f, y), new Vector2(0.975f, y + 0.19f), Vector2.zero, Vector2.zero);
            CreateBadge(row.transform, number.ToString("00"), new Vector2(0.025f, 0.22f), new Vector2(0.105f, 0.78f),
                Manual2ARVisualTheme.TargetCyan, Background);
            CreateText(row.transform, "Title", new Vector2(0.13f, 0.47f), new Vector2(0.68f, 0.82f),
                title, 20, Color.white, TextAnchor.MiddleLeft);
            CreateText(row.transform, "Detail", new Vector2(0.13f, 0.12f), new Vector2(0.78f, 0.47f),
                detail, 15, Muted, TextAnchor.MiddleLeft);
            CreateBadge(row.transform, figure, new Vector2(0.80f, 0.28f), new Vector2(0.965f, 0.72f),
                SurfaceRaised, Manual2ARVisualTheme.TargetCyan);
        }

        void BuildHeader(string title, string subtitle, string progress, UnityEngine.Events.UnityAction back)
        {
            CreateButton(m_PageRoot, "Back", "←  BACK",
                new Vector2(0.055f, 0.875f), new Vector2(0.16f, 0.94f),
                SurfaceRaised, Color.white, back, 15);
            CreateText(m_PageRoot, "Header Title", new Vector2(0.055f, 0.80f), new Vector2(0.72f, 0.87f),
                title, 42, Color.white, TextAnchor.MiddleLeft);
            CreateText(m_PageRoot, "Header Subtitle", new Vector2(0.055f, 0.755f), new Vector2(0.74f, 0.80f),
                subtitle, 20, Muted, TextAnchor.MiddleLeft);
            CreateBadge(m_PageRoot, progress, new Vector2(0.82f, 0.79f), new Vector2(0.945f, 0.85f),
                SurfaceRaised, Manual2ARVisualTheme.TargetCyan);
        }

        void CreateFooterStatus(string value)
        {
            CreateText(m_PageRoot, "Footer Status", new Vector2(0.055f, 0.015f), new Vector2(0.945f, 0.05f),
                value, 14, Muted, TextAnchor.MiddleCenter);
        }

        static GameObject CreatePanel(Transform parent, string name, Color color,
            Vector2 anchorMin, Vector2 anchorMax, Vector2 offsetMin, Vector2 offsetMax)
        {
            var go = new GameObject(name);
            go.transform.SetParent(parent, false);
            var rect = go.AddComponent<RectTransform>();
            rect.anchorMin = anchorMin;
            rect.anchorMax = anchorMax;
            rect.offsetMin = offsetMin;
            rect.offsetMax = offsetMax;
            var image = go.AddComponent<Image>();
            image.color = color;
            return go;
        }

        static TextMeshProUGUI CreateText(Transform parent, string name, Vector2 anchorMin, Vector2 anchorMax,
            string value, int fontSize, Color color, TextAnchor alignment)
        {
            var go = new GameObject(name);
            go.transform.SetParent(parent, false);
            var rect = go.AddComponent<RectTransform>();
            rect.anchorMin = anchorMin;
            rect.anchorMax = anchorMax;
            rect.offsetMin = Vector2.zero;
            rect.offsetMax = Vector2.zero;
            var text = go.AddComponent<TextMeshProUGUI>();
            text.text = value;
            text.fontSize = Mathf.Max(20, fontSize);
            text.fontStyle = fontSize >= 22 ? FontStyles.Bold : FontStyles.Normal;
            text.alignment = ToTmpAlignment(alignment);
            text.color = color;
            text.enableWordWrapping = true;
            text.overflowMode = TextOverflowModes.Truncate;
            text.lineSpacing = 3.0f;
            text.raycastTarget = false;
            if (TMP_Settings.defaultFontAsset != null)
                text.font = TMP_Settings.defaultFontAsset;
            return text;
        }

        static TextAlignmentOptions ToTmpAlignment(TextAnchor alignment)
        {
            switch (alignment)
            {
                case TextAnchor.UpperLeft: return TextAlignmentOptions.TopLeft;
                case TextAnchor.UpperCenter: return TextAlignmentOptions.Top;
                case TextAnchor.UpperRight: return TextAlignmentOptions.TopRight;
                case TextAnchor.MiddleLeft: return TextAlignmentOptions.MidlineLeft;
                case TextAnchor.MiddleRight: return TextAlignmentOptions.MidlineRight;
                case TextAnchor.LowerLeft: return TextAlignmentOptions.BottomLeft;
                case TextAnchor.LowerCenter: return TextAlignmentOptions.Bottom;
                case TextAnchor.LowerRight: return TextAlignmentOptions.BottomRight;
                default: return TextAlignmentOptions.Center;
            }
        }

        static Button CreateButton(Transform parent, string name, string label,
            Vector2 anchorMin, Vector2 anchorMax, Color background, Color foreground,
            UnityEngine.Events.UnityAction onClick, int fontSize)
        {
            var go = CreatePanel(parent, name, background, anchorMin, anchorMax, Vector2.zero, Vector2.zero);
            var button = go.AddComponent<Button>();
            var colors = button.colors;
            colors.normalColor = Color.white;
            colors.highlightedColor = new Color(0.74f, 1.0f, 1.0f, 1.0f);
            colors.pressedColor = new Color(0.50f, 0.94f, 1.0f, 1.0f);
            colors.disabledColor = new Color(0.42f, 0.48f, 0.50f, 0.65f);
            button.colors = colors;
            if (onClick != null)
                button.onClick.AddListener(onClick);
            CreateText(go.transform, "Text", Vector2.zero, Vector2.one, label, fontSize,
                foreground, TextAnchor.MiddleCenter);
            return button;
        }

        static void CreateBadge(Transform parent, string value, Vector2 min, Vector2 max,
            Color background, Color foreground)
        {
            var badge = CreatePanel(parent, value + " Badge", background, min, max, Vector2.zero, Vector2.zero);
            CreateText(badge.transform, "Text", Vector2.zero, Vector2.one, value, 18, foreground, TextAnchor.MiddleCenter);
        }

        static void AddOutline(GameObject target, Color color, float distance)
        {
            var outline = target.GetComponent<Outline>() ?? target.AddComponent<Outline>();
            outline.effectColor = color;
            outline.effectDistance = new Vector2(distance, -distance);
        }

        static void Stretch(RectTransform rect)
        {
            rect.anchorMin = Vector2.zero;
            rect.anchorMax = Vector2.one;
            rect.offsetMin = Vector2.zero;
            rect.offsetMax = Vector2.zero;
        }

        static string ShortName(string value)
        {
            if (string.IsNullOrWhiteSpace(value) || value.Length <= 30)
                return value;
            return value.Substring(0, 27) + "…";
        }
    }
}
