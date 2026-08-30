from __future__ import annotations

import io
import json
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from app.main import app


client = TestClient(app)


def _jpeg() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (96, 72), color=(230, 120, 30)).save(buffer, "JPEG")
    return buffer.getvalue()


def _form(phase: str, consent: str = "true") -> dict[str, str]:
    return {
        "case_id": "AMS_TEST_001",
        "phase": phase,
        "operation": "winding_check",
        "viewpoint": "slot_closeup",
        "slot": "3",
        "expected_color": "orange",
        "actual_color": "orange",
        "winding_direction": "counterclockwise",
        "filament_state": "inserted",
        "expected_status": "completed",
        "notes": "test only",
        "consent": consent,
    }


def test_collector_page_is_mobile_capture_ui() -> None:
    response = client.get("/collector")
    assert response.status_code == 200
    assert "Manual2AR 现场采集" in response.text
    assert 'capture="environment"' in response.text


def test_live_empty_spindle_page_exposes_narrow_tracking_entry() -> None:
    response = client.get("/live-empty-spindle")
    assert response.status_code == 200
    assert "Empty Spool Holder · Automatic Grounding" in response.text
    assert "/api/ams-lite/empty-spool-axle/locate" in response.text
    assert "/api/tracking/sessions/${sessionId}/frames" in response.text
    assert "Start camera and auto-ground" in response.text
    assert "MOUNT SPOOL" in response.text
    assert "RIGHT TO LEFT" in response.text
    assert "LAST VERIFIED MASK HELD" not in response.text
    assert "Draw holder" not in response.text


def test_unity_mac_demo_uses_webcam_and_direct_tracking_updates() -> None:
    project_root = Path(__file__).resolve().parents[2]
    scripts = project_root / "unity" / "Manual2AR" / "Assets" / "Manual2AR" / "Scripts"
    controller = (scripts / "EmptySpindleTrackingController.cs").read_text(encoding="utf-8")
    client_source = (scripts / "Manual2ARBackendClient.cs").read_text(encoding="utf-8")
    overlay = (scripts / "ImageSpaceGuidanceOverlay.cs").read_text(encoding="utf-8")

    assert "WebCamTexture.devices" in controller
    assert "m_BackendTrackingUpdateIntervalSeconds = 0.5f" in controller
    assert '"http://127.0.0.1:8010"' in controller
    assert '"client_pending"' in controller
    assert "HandleTrackingLost" in controller
    assert "ClearCurrentOverlay(true)" in controller
    assert "FromJson<TrackedComponent>" in client_source
    assert '"http://127.0.0.1:8020"' not in controller + client_source
    assert "overlay_png_base64" in overlay
    assert "Manual2ARArrowGraphic" in overlay
    assert "Quaternion.Euler(0.0f, 0.0f, 90.0f)" in overlay
    assert "arrowOutline.effectDistance = new Vector2(5.0f, -5.0f)" in overlay
    assert "m_ArrowRoot.SetAsLastSibling()" in overlay
    assert "PositionArrow(centroid, tracked.bbox_0_1000)" in overlay
    assert "arrowObject.transform.SetParent(screenUiRoot, false)" in overlay
    assert "cameraContent.TransformPoint(new Vector3(x, y, 0.0f))" in overlay
    assert "m_ArrowRoot.position = worldTarget" in overlay


def test_unity_component_overview_has_three_independent_masks_labels_and_sessions() -> None:
    project_root = Path(__file__).resolve().parents[2]
    scripts = project_root / "unity" / "Manual2AR" / "Assets" / "Manual2AR" / "Scripts"
    controller = (scripts / "ComponentOverviewTrackingController.cs").read_text(encoding="utf-8")
    client_source = (scripts / "Manual2ARBackendClient.cs").read_text(encoding="utf-8")
    overlay = (scripts / "MultiComponentGuidanceOverlay.cs").read_text(encoding="utf-8")

    assert '"build_plate"' in controller
    assert '"filament_spool"' in controller
    assert '"empty_spool_holder"' in controller
    assert "WebCamTexture.devices" in controller
    assert "m_TrackingIntervalSeconds = 0.35f" in controller
    assert "SendTrackingFrames" in controller
    assert "StartCoroutine(RequestTrackingUpdate" in controller
    assert "pendingUpdates.Exists" in controller
    assert "CloseAndClearAll" in controller
    assert "COMPONENT TRACKING LOST · RE-GROUND REQUIRED" in controller
    assert "m_AutoRegroundAfterTrackingLoss = true" in controller
    assert '"/api/components/locate"' in client_source
    assert '"/api/tracking/sessions/{sessionId}/frames"' in client_source
    assert "overlay_png_base64" in overlay
    assert "PositionLabel" in overlay
    assert "TransformPoint" in overlay
    assert "Screen.height" in overlay
    assert "SetAsLastSibling" in overlay
    assert '"http://127.0.0.1:8020"' not in controller + client_source


def test_capture_requires_explicit_consent(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MANUAL2AR_FIELD_CAPTURE_ROOT", str(tmp_path))
    response = client.post(
        "/api/evaluation/captures",
        data=_form("before", consent="false"),
        files={"image": ("before.jpg", _jpeg(), "image/jpeg")},
    )
    assert response.status_code == 400
    assert not list(tmp_path.rglob("*.jpg"))


def test_capture_saves_pair_labels_hashes_and_revisions(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MANUAL2AR_FIELD_CAPTURE_ROOT", str(tmp_path))
    before = client.post(
        "/api/evaluation/captures",
        data=_form("before"),
        files={"image": ("before.jpg", _jpeg(), "image/jpeg")},
    )
    assert before.status_code == 201
    assert before.json()["pair_complete"] is False

    after = client.post(
        "/api/evaluation/captures",
        data=_form("after"),
        files={"image": ("after.jpg", _jpeg(), "image/jpeg")},
    )
    assert after.status_code == 201
    assert after.json()["pair_complete"] is True

    retake = client.post(
        "/api/evaluation/captures",
        data=_form("after"),
        files={"image": ("after.jpg", _jpeg(), "image/jpeg")},
    )
    assert retake.status_code == 201
    assert retake.json()["revision"] == 2

    metadata = json.loads(
        (tmp_path / "AMS_TEST_001" / "after_001.json").read_text()
    )
    assert metadata["labels"]["direction_group"] == "counterclockwise"
    assert metadata["labels"]["viewpoint"] == "slot_closeup"
    assert metadata["labels"]["expected_status"] == "completed"
    assert len(metadata["sha256"]) == 64


def test_capture_records_traceable_paper_evidence_metadata(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MANUAL2AR_FIELD_CAPTURE_ROOT", str(tmp_path))
    form = _form("overlay")
    form.update(
        {
            "figure_id": "b",
            "run_id": "B_RUN_001",
            "device_id": "bambu_a1_mini_ams_lite",
            "task_id": "load_spool",
            "model_version": "qwen3-vl-flash",
            "prompt_version": "paper-v1",
            "manual_version": "ams-lite-official",
            "compile_version": "bundle-1.0",
            "paper_claim": "world-anchored spool placement guidance",
            "paper_use_allowed": "true",
        }
    )
    response = client.post(
        "/api/evaluation/captures",
        data=form,
        files={"image": ("overlay.jpg", _jpeg(), "image/jpeg")},
    )
    assert response.status_code == 201
    metadata = json.loads(
        (tmp_path / "AMS_TEST_001" / "overlay_001.json").read_text()
    )
    assert metadata["paper_evidence"]["figure_id"] == "b"
    assert metadata["paper_evidence"]["run_id"] == "B_RUN_001"
    assert metadata["paper_evidence"]["paper_use_allowed"] is True
