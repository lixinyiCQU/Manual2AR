from __future__ import annotations

import base64
import io
import json

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.device_profiles import load_device_profile
from app.main import app
from app.manual_service import ManualService
from app.models import (
    ComponentBox,
    StateLocalizationRequest,
    StateLocalizationResult,
    VerificationRequest,
    VerificationResult,
)
from app.ollama_client import OllamaClient, OllamaError


client = TestClient(app)


def test_blank_comparison_mode_uses_single_frame_default() -> None:
    request = VerificationRequest(
        procedure_id="procedure-test",
        current_step_id="S0",
        image_base64="jpeg-base64",
        comparison_mode="",
        mock_status="",
    )
    assert request.comparison_mode == "single_frame"
    assert request.mock_status == "completed"


def test_verification_model_outage_returns_safe_uncertainty(monkeypatch) -> None:
    service = ManualService()
    procedure = service._load_mock_procedure(
        [("TWO_OBJECT_BOOK_PEN_manual.pdf", "application/pdf", b"mock")]
    )
    procedure_id = "qwen-empty-content-safe-fallback"
    service.jobs.restore_completed(procedure_id, procedure)
    monkeypatch.setattr(
        service,
        "_verify_with_ollama",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            OllamaError("Qwen Chat Completions returned no message content")
        ),
    )

    result = service.verify(
        VerificationRequest(
            procedure_id=procedure_id,
            current_step_id="S0",
            image_base64=_image_base64(),
            mode="ollama",
        )
    )

    assert result.status == "uncertain"
    assert result.safe_to_advance is False
    assert result.confidence == 0.0
    assert result.component_boxes_0_1000 == []
    assert result.overlay_semantic == "insufficient"
    assert result.safety_gate_reasons


def test_vlm_box_is_mapped_back_to_raw_portrait_camera_coordinates() -> None:
    converted = ManualService._boxes_to_raw_coordinates(
        [
            ComponentBox(
                component_id="source:pen",
                bbox_0_1000=[100, 200, 300, 400],
                observation="upright VLM box",
            )
        ],
        90,
    )
    assert converted[0].bbox_0_1000 == [200, 700, 400, 900]
    assert "原始坐标" in converted[0].observation


def _image_base64() -> str:
    image = Image.new("RGB", (80, 60), color=(40, 90, 130))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _pen_image_base64(x: int) -> str:
    image = Image.new("RGB", (180, 120), color=(225, 220, 210))
    for px in range(x, x + 70):
        for py in range(50, 60):
            image.putpixel((px, py), (0, 200, 180))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=95)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _book_image_base64() -> str:
    image = Image.new("RGB", (200, 140), color=(38, 45, 52))
    for px in range(45, 160):
        for py in range(30, 115):
            image.putpixel((px, py), (232, 224, 205))
    # Add a dark binding so that the object contains trackable internal detail.
    for px in range(98, 104):
        for py in range(30, 115):
            image.putpixel((px, py), (90, 72, 58))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=95)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _mock_procedure_id() -> str:
    response = client.post(
        "/api/manuals?mode=mock",
        files=[("files", ("manual.pdf", b"%PDF-mock", "application/pdf"))],
    )
    assert response.status_code == 202
    job_id = response.json()["job_id"]
    job = client.get(f"/api/manuals/{job_id}")
    assert job.status_code == 200
    payload = job.json()
    assert payload["status"] == "completed"
    assert payload["procedure"]["states"][0]["state_id"] == "S0"
    return payload["procedure_id"]


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["vision_provider"] == "qwen"
    assert payload["model"] == "qwen3-vl-flash"
    assert payload["tracking_mode"] in {"auto", "opencv", "sam2"}
    assert payload["tracking_provider"] == "opencv-grabcut-lk-baseline"
    assert isinstance(payload["tracking_remote_available"], bool)


def test_mock_manual_and_safe_completion() -> None:
    procedure_id = _mock_procedure_id()
    response = client.post(
        "/api/guidance/verify",
        json={
            "procedure_id": procedure_id,
            "current_step_id": "S0",
            "history": [],
            "image_base64": _image_base64(),
            "mode": "mock",
            "mock_status": "completed",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "completed"
    assert payload["safe_to_advance"] is True
    assert payload["matched_step_id"] == "S0"


def test_wrong_and_uncertain_never_advance() -> None:
    procedure_id = _mock_procedure_id()
    for status in ("wrong_operation", "uncertain"):
        response = client.post(
            "/api/guidance/verify",
            json={
                "procedure_id": procedure_id,
                "current_step_id": "S1",
                "history": ["S0"],
                "image_base64": _image_base64(),
                "mode": "mock",
                "mock_status": status,
            },
        )
        assert response.status_code == 200
        assert response.json()["safe_to_advance"] is False


def test_before_after_checkpoint_requires_before_image() -> None:
    procedure_id = _mock_procedure_id()
    response = client.post(
        "/api/guidance/verify",
        json={
            "procedure_id": procedure_id,
            "current_step_id": "S1",
            "image_base64": _image_base64(),
            "comparison_mode": "before_after",
            "mode": "mock",
        },
    )
    assert response.status_code == 422


def test_mock_before_after_checkpoint_uses_same_safety_gate() -> None:
    procedure_id = _mock_procedure_id()
    for status, expected_advance in (
        ("completed", True),
        ("wrong_operation", False),
        ("uncertain", False),
    ):
        response = client.post(
            "/api/guidance/verify",
            json={
                "procedure_id": procedure_id,
                "current_step_id": "S1",
                "history": ["S0"],
                "before_image_base64": _image_base64(),
                "image_base64": _image_base64(),
                "comparison_mode": "before_after",
                "mode": "mock",
                "mock_status": status,
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == status
        assert payload["safe_to_advance"] is expected_advance


def test_multiview_inspections_retain_nodes_before_step_advance() -> None:
    procedure_id = _mock_procedure_id()
    first = client.post(
        "/api/guidance/verify",
        json={
            "procedure_id": procedure_id,
            "current_step_id": "S0",
            "history": [],
            "image_base64": _image_base64(),
            "mode": "mock",
            "mock_status": "completed",
            "inspection_id": "S0-C1",
            "focus_component_ids": ["source:设备顶部"],
            "focus_condition": "顶部连接清晰可见",
            "completed_inspection_ids": [],
            "expected_inspection_ids": ["S0-C1", "S0-C2"],
            "is_final_inspection": False,
        },
    )
    assert first.status_code == 200
    assert first.json()["status"] == "completed"
    assert first.json()["safe_to_advance"] is False

    final = client.post(
        "/api/guidance/verify",
        json={
            "procedure_id": procedure_id,
            "current_step_id": "S0",
            "history": [],
            "image_base64": _image_base64(),
            "mode": "mock",
            "mock_status": "completed",
            "inspection_id": "S0-C2",
            "focus_component_ids": ["source:设备底部"],
            "focus_condition": "底部固定位置清晰可见",
            "completed_inspection_ids": ["S0-C1"],
            "expected_inspection_ids": ["S0-C1", "S0-C2"],
            "is_final_inspection": True,
        },
    )
    assert final.status_code == 200
    assert final.json()["safe_to_advance"] is True


def test_client_cannot_spoof_a_missing_predicate_as_completed() -> None:
    procedure_id = _mock_procedure_id()
    response = client.post(
        "/api/guidance/verify",
        json={
            "run_id": "spoof-attempt-new-run",
            "procedure_id": procedure_id,
            "current_step_id": "S0",
            "history": [],
            "image_base64": _image_base64(),
            "mode": "mock",
            "mock_status": "completed",
            "inspection_id": "S0-C2",
            "focus_component_ids": ["source:设备底部"],
            "focus_condition": "底部固定位置清晰可见",
            # The phone claims C1 was already completed, but this run never
            # submitted evidence for C1. The server-owned predicate cache must
            # ignore this field as an unlock signal.
            "completed_inspection_ids": ["S0-C1"],
            "expected_inspection_ids": ["S0-C1", "S0-C2"],
            "is_final_inspection": True,
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["safe_to_advance"] is False
    assert "S0-C1" not in payload["retained_inspection_ids"]
    assert any(
        item["predicate_id"] == "S0-C1" and item["status"] == "not_started"
        for item in payload["predicates"]
    )


def test_unknown_procedure_is_rejected() -> None:
    response = client.post(
        "/api/guidance/verify",
        json={
            "procedure_id": "missing",
            "current_step_id": "S0",
            "image_base64": _image_base64(),
            "mode": "mock",
        },
    )
    assert response.status_code == 400


def test_mock_state_localization_returns_contiguous_prefix() -> None:
    procedure_id = _mock_procedure_id()
    response = client.post(
        "/api/guidance/locate",
        json={
            "procedure_id": procedure_id,
            "image_base64": _image_base64(),
            "mode": "mock",
            "mock_recommended_step_id": "S3",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["recommended_step_id"] == "S3"
    assert payload["completed_step_ids"] == ["S0", "S1", "S2"]
    assert payload["requires_human_confirmation"] is True
    assert payload["unavailable_checks"]


def test_home_demo_selects_home_procedure() -> None:
    response = client.post(
        "/api/manuals?mode=mock",
        files=[
            (
                "files",
                (
                    "HOME_DESK_KIT_01_manual_v1.pdf",
                    b"%PDF-mock",
                    "application/pdf",
                ),
            )
        ],
    )
    assert response.status_code == 202
    job_id = response.json()["job_id"]
    job = client.get(f"/api/manuals/{job_id}").json()
    assert job["procedure"]["device"]["device_id"] == "HOME-DESK-KIT-01"
    assert len(job["procedure"]["states"]) == 5


def test_relocation_demo_contains_source_and_target_grounding() -> None:
    response = client.post(
        "/api/manuals?mode=mock",
        files=[
            (
                "files",
                (
                    "HOME_OBJECT_RELOCATION_01_manual_v1.pdf",
                    b"%PDF-mock",
                    "application/pdf",
                ),
            )
        ],
    )
    assert response.status_code == 202
    job_id = response.json()["job_id"]
    job = client.get(f"/api/manuals/{job_id}").json()
    assert job["procedure"]["device"]["device_id"] == "HOME-OBJECT-RELOCATION-01"
    step = job["procedure"]["states"][2]
    assert step["target_components"] == [
        "source:蓝色笔",
        "target:中间主书下半部",
    ]

    verify = client.post(
        "/api/guidance/verify",
        json={
            "procedure_id": job["procedure_id"],
            "current_step_id": "S2",
            "history": ["S0", "S1"],
            "image_base64": _image_base64(),
            "mode": "mock",
            "mock_status": "not_started",
        },
    )
    assert verify.status_code == 200
    box_ids = [item["component_id"] for item in verify.json()["component_boxes_0_1000"]]
    assert box_ids == ["source:蓝色笔", "target:中间主书下半部"]


def test_two_object_demo_is_the_minimal_grounding_flow() -> None:
    response = client.post(
        "/api/manuals?mode=mock",
        files=[
            (
                "files",
                (
                    "TWO_OBJECT_BOOK_PEN_01_manual_v1.pdf",
                    b"%PDF-mock",
                    "application/pdf",
                ),
            )
        ],
    )
    assert response.status_code == 202
    job_id = response.json()["job_id"]
    job = client.get(f"/api/manuals/{job_id}").json()
    procedure = job["procedure"]
    assert procedure["device"]["device_id"] == "TWO-OBJECT-BOOK-PEN-01"
    assert len(procedure["states"]) == 4
    assert procedure["states"][2]["target_components"] == [
        "source:蓝色笔",
        "target:书的下半部",
    ]


def test_a1_mini_profile_loads_audited_manual_state_graph_without_training() -> None:
    response = client.post(
        "/api/manuals?mode=ollama&device_profile=bambu_a1_mini",
        files=[
            (
                "files",
                (
                    "A1_mini_quick_start_zh.pdf",
                    b"%PDF-profile-selection",
                    "application/pdf",
                ),
            )
        ],
    )
    assert response.status_code == 202
    job_id = response.json()["job_id"]
    job = client.get(f"/api/manuals/{job_id}").json()
    procedure = job["procedure"]

    assert job["status"] == "completed"
    assert procedure["device"]["device_id"] == "bambu_a1_mini"
    assert procedure["task"]["task_id"] == "a1_mini_external_spool_path_v1"
    assert len(procedure["states"]) == 7
    assert procedure["states"][3]["target_components"] == [
        "source:最短PTFE管",
        "target:工具头进料口",
    ]
    assert procedure["states"][5]["manual_provenance"]["page"] == 12


def test_a1_mini_ams_lite_profile_is_separate_and_checkpoint_ready() -> None:
    response = client.post(
        "/api/manuals?mode=ollama&device_profile=bambu_a1_mini_ams_lite",
        files=[
            (
                "files",
                (
                    "A1_mini_quick_start_zh.pdf",
                    b"%PDF-profile-selection",
                    "application/pdf",
                ),
            )
        ],
    )
    assert response.status_code == 202
    job_id = response.json()["job_id"]
    job = client.get(f"/api/manuals/{job_id}").json()
    procedure = job["procedure"]

    assert job["status"] == "completed"
    assert procedure["device"]["device_id"] == "bambu_a1_mini_ams_lite"
    assert procedure["task"]["task_id"] == "ams_lite_load_spool_slot1_v1"
    assert procedure["task"]["task_type"] == "load_spool"
    assert procedure["task"]["parameters"]["required_material"] is None
    assert job["bundle"]["schema_version"] == "1.0"
    assert [item["screen_position"] for item in job["bundle"]["component_topology"]] == [
        "left_upper",
        "left_lower",
        "right_lower",
        "right_upper",
    ]
    assert [task["task_template_id"] for task in job["bundle"]["tasks"]] == [
        "load_spool",
        "unload_spool",
        "swap_spool",
        "recover_visible_jam",
    ]
    assert len(procedure["states"]) == 4
    assert len(procedure["states"][0]["observation_nodes"]) == 1
    assert procedure["states"][0]["observation_nodes"][0][
        "verification_channel"
    ] == "vision"
    assert "实验室尚未授权操作" in procedure["states"][0]["wrong_states"]
    assert procedure["states"][2]["target_components"] == [
        "target:AMS Lite 1号送料器模块",
        "source:1号槽耗材头",
        "forbidden:AMS Lite 1号黄色释放按钮",
    ]
    assert "不必钻到机器底下" in procedure["states"][2][
        "observation_nodes"
    ][0]["capture_instruction"]
    assert "不要再推料或按按钮" in procedure["states"][3]["instruction"]
    assert len(procedure["states"][3]["observation_nodes"]) == 1

    selected = client.post(
        f"/api/manuals/{job_id}/tasks/select",
        json={
            "task_template_id": "load_spool",
            "selected_slot_id": 4,
            "required_material": None,
            "user_confirmed_slot": True,
        },
    )
    assert selected.status_code == 200
    selected_payload = selected.json()
    assert selected_payload["selected_slot_id"] == 4
    assert selected_payload["procedure"]["task"]["task_id"].startswith(
        "ams_lite_load_spool_slot4"
    )
    serialized = json.dumps(selected_payload["procedure"], ensure_ascii=False)
    assert "4号送料口" in serialized
    assert "灰色料盘" not in serialized
    assert "橙色PLA料盘" not in serialized

    blocked = client.post(
        f"/api/manuals/{job_id}/tasks/select",
        json={
            "task_template_id": "unload_spool",
            "selected_slot_id": 1,
            "user_confirmed_slot": True,
        },
    )
    assert blocked.status_code == 400
    assert "官方维护来源" in blocked.json()["detail"]


def test_ams_loading_final_gate_requires_five_server_retained_predicates() -> None:
    created = client.post(
        "/api/manuals?mode=ollama&device_profile=bambu_a1_mini_ams_lite",
        files=[
            (
                "files",
                ("A1_mini_quick_start_zh.pdf", b"%PDF-final-gate", "application/pdf"),
            )
        ],
    )
    assert created.status_code == 202
    job_id = created.json()["job_id"]
    selected = client.post(
        f"/api/manuals/{job_id}/tasks/select",
        json={
            "task_template_id": "load_spool",
            "selected_slot_id": 3,
            "user_confirmed_slot": True,
        },
    )
    assert selected.status_code == 200
    procedure_id = selected.json()["procedure_id"]

    common = {
        "procedure_id": procedure_id,
        "history": [],
        "image_base64": _image_base64(),
        "before_image_base64": _image_base64(),
        "mode": "mock",
        "mock_status": "completed",
        "run_id": "paper-final-gate",
        "request_purpose": "state_verification",
        "is_final_inspection": True,
    }

    # A good-looking final PTFE frame cannot bypass missing earlier checkpoints.
    premature = client.post(
        "/api/guidance/verify",
        json={
            **common,
            "current_step_id": "S3",
            "inspection_id": "S3-C1",
            "expected_inspection_ids": ["S3-C1"],
            "comparison_mode": "before_after",
        },
    )
    assert premature.status_code == 200
    assert premature.json()["safe_to_advance"] is False
    expected_ids = {
        "selected_slot_identity_consistent",
        "spool_stably_installed",
        "filament_entered_selected_slot_feeder",
        "filament_visible_in_selected_slot_ptfe",
        "no_cross_slot_bend_or_tangle",
    }
    assert {item["predicate_id"] for item in premature.json()["predicates"]} == expected_ids

    for state_id, inspection_id, comparison_mode in [
        ("S0", "S0-C1", "single_frame"),
        ("S1", "S1-C1", "before_after"),
        ("S2", "S2-C1", "before_after"),
        ("S3", "S3-C1", "before_after"),
    ]:
        response = client.post(
            "/api/guidance/verify",
            json={
                **common,
                "current_step_id": state_id,
                "inspection_id": inspection_id,
                "expected_inspection_ids": [inspection_id],
                "comparison_mode": comparison_mode,
            },
        )
        assert response.status_code == 200

    final_payload = response.json()
    assert final_payload["safe_to_advance"] is True
    assert {item["predicate_id"] for item in final_payload["predicates"]} == expected_ids
    assert all(item["status"] == "completed" for item in final_payload["predicates"])


def test_a1_filename_does_not_silently_enable_audited_profile(monkeypatch) -> None:
    service = ManualService()
    expected = load_device_profile("bambu_a1_mini").load_procedure().model_copy(
        deep=True
    )
    expected.device.device_id = "auto-generated-from-pdf"
    monkeypatch.setattr(
        service,
        "_prepare_manual_inputs",
        lambda _uploads: (["automatic PDF text"], []),
    )
    monkeypatch.setattr(
        service,
        "_analyze_with_ollama",
        lambda _text, _images, guidance_language, on_constraint_repair: expected,
    )

    job = service.create_job()
    service.process_job(
        job.job_id,
        [("A1_mini_quick_start_zh.pdf", "application/pdf", b"%PDF")],
        "ollama",
        None,
    )

    completed = service.jobs.get(job.job_id)
    assert completed is not None
    assert completed.status == "completed"
    assert completed.procedure.device.device_id == "auto-generated-from-pdf"


def test_a1_profile_can_return_english_guidance_without_changing_state_ids() -> None:
    profile = load_device_profile("bambu_a1_mini")
    chinese = profile.load_procedure("zh")
    english = profile.load_procedure("en")

    assert [state.state_id for state in chinese.states] == [
        state.state_id for state in english.states
    ]
    assert chinese.states[3].instruction.startswith("将最短PTFE管")
    assert english.states[3].instruction.startswith("Insert one end")
    assert english.states[3].target_components == chinese.states[3].target_components


def test_a1_mini_profile_rejects_unknown_profile() -> None:
    response = client.post(
        "/api/manuals?mode=ollama&device_profile=not_a_printer",
        files=[("files", ("manual.pdf", b"%PDF", "application/pdf"))],
    )
    assert response.status_code == 422


def test_a1_mini_visible_facts_map_to_first_incomplete_step(monkeypatch) -> None:
    service = ManualService()
    profile = load_device_profile("bambu_a1_mini")
    assert profile is not None
    procedure = profile.load_procedure()
    monkeypatch.setattr(
        service.ollama,
        "chat_structured",
        lambda **_kwargs: {
            "device_identity": "a1_mini",
            "spool_holder_base": "installed",
            "spool_holder": "installed",
            "ptfe_to_toolhead": "disconnected",
            "external_spool": "not_mounted",
            "filament_into_ptfe": "not_inserted",
            "route_condition": "incomplete",
            "evidence": "整机、底座和料盘支架可见，尚未连接PTFE管。",
        },
    )
    localized = service._locate_a1_mini_facts(
        StateLocalizationRequest(
            procedure_id="test",
            image_base64=_image_base64(),
            mode="ollama",
        ),
        procedure,
        profile,
    )
    assert localized is not None
    assert localized.completed_step_ids == ["S0", "S1", "S2"]
    assert localized.recommended_step_id == "S3"

    current = service._verification_from_a1_mini_localization(
        procedure.states[3],
        procedure,
        localized,
    )
    assert current.status == "not_started"
    assert current.safe_to_advance is False


def test_low_confidence_or_whole_device_results_do_not_create_masks() -> None:
    service = ManualService()
    profile = load_device_profile("bambu_a1_mini")
    assert profile is not None
    procedure = profile.load_procedure()
    low_confidence = StateLocalizationResult(
        observed_summary="A1_FACTS device=not_a1_mini",
        completed_step_ids=[],
        recommended_step_id="S0",
        evidence="identity mismatch",
        confidence=0.35,
    )
    assert not service._allow_localization_grounding(
        low_confidence,
        procedure.states[0],
    )

    identified_whole_device = low_confidence.model_copy(
        update={
            "observed_summary": "A1_FACTS device=a1_mini",
            "confidence": 0.82,
        }
    )
    assert not service._allow_localization_grounding(
        identified_whole_device,
        procedure.states[0],
    )
    assert not service._allow_localization_grounding(
        identified_whole_device,
        procedure.states[1],
    )

    uncertain = VerificationResult(
        status="uncertain",
        matched_step_id="S1",
        evidence="small part is occluded",
        component_boxes_0_1000=[],
        manual_page=8,
        manual_section="spool holder",
        confidence=0.35,
        safe_to_advance=False,
        next_action="adjust view",
    )
    assert not service._allow_verification_grounding(
        uncertain,
        procedure.states[1],
    )


def test_unknown_procedure_state_localization_is_rejected() -> None:
    response = client.post(
        "/api/guidance/locate",
        json={
            "procedure_id": "missing",
            "image_base64": _image_base64(),
            "mode": "mock",
        },
    )
    assert response.status_code == 400


def test_fenced_structured_output_is_recovered() -> None:
    payload = OllamaClient._extract_json_content(
        "```json\n{\"status\": \"uncertain\"}\n```"
    )
    assert payload == {"status": "uncertain"}


def test_natural_language_step_references_are_normalized() -> None:
    state_ids = ["S0", "S1", "S2", "S3"]
    assert ManualService._normalize_step_reference("步骤 3", state_ids) == "S3"
    assert ManualService._normalize_step_reference("step-2", state_ids) == "S2"
    assert ManualService._normalize_step_reference("S 1", state_ids) == "S1"
    assert ManualService._normalize_step_reference("unknown", state_ids) is None


def test_model_state_links_are_sanitized_before_validation() -> None:
    raw = {
        "task": {
            "task_id": "t",
            "manual_id": "m",
            "initial_state": "bad",
            "terminal_states": ["bad"],
        },
        "states": [
            {"state_id": "free text", "step_index": 9, "next_on_success": "unknown", "instruction": "open", "preconditions": ["cover closed"], "postconditions": [], "verification": "cover open"},
            {"state_id": "duplicate", "step_index": 9, "next_on_success": "done", "instruction": "close", "preconditions": ["book open"], "postconditions": ["book open"], "verification": "book is fully closed"},
        ],
    }
    sanitized = ManualService._sanitize_procedure_payload(raw)
    assert [state["state_id"] for state in sanitized["states"]] == ["S0", "S1"]
    assert sanitized["states"][0]["next_on_success"] == "S1"
    assert sanitized["states"][1]["next_on_success"] is None
    assert sanitized["task"]["initial_state"] == "S0"
    assert sanitized["task"]["terminal_states"] == ["S1"]
    assert sanitized["states"][0]["postconditions"] == ["cover open"]
    assert sanitized["states"][1]["postconditions"] == ["book is fully closed"]


def test_manual_parser_rejects_an_action_without_observable_state_change() -> None:
    raw = {
        "task": {"task_id": "t", "manual_id": "m"},
        "states": [
            {
                "instruction": "press the button",
                "preconditions": ["button visible"],
                "postconditions": ["button visible"],
                "verification": "button visible",
            }
        ],
    }
    with pytest.raises(ValueError, match="identical preconditions"):
        ManualService._sanitize_procedure_payload(raw)


def test_manual_compiler_keeps_richer_boundary_and_normalizes_visual_roles() -> None:
    raw = {
        "device": {
            "device_id": "book-pen",
            "name": "Book and pen",
            "role": "parse manual into auditable procedure state graph",
        },
        "task": {
            "task_id": "parse manual into auditable procedure state graph",
            "manual_id": "book_pen_01",
        },
        "states": [
            {
                "instruction": "开始前状态 S0",
                "preconditions": ["书和笔入镜"],
                "postconditions": ["书打开", "蓝色笔"],
                "target_components": ["book", "blue pen"],
                "verification": "说明书自动拆步骤、当前进度判断、方向箭头",
            },
            {
                "instruction": "合上摊开的书",
                "preconditions": ["书完全打开", "蓝色笔水平放在书左边且不接触书"],
                "postconditions": ["书完全合上"],
                "wrong_states": ["书仍打开"],
                "target_components": ["book"],
                "verification": "书完全合上",
            },
        ],
    }

    sanitized = ManualService._sanitize_procedure_payload(raw)

    expected_boundary = ["书完全打开", "蓝色笔水平放在书左边且不接触书"]
    assert sanitized["states"][0]["postconditions"] == expected_boundary
    assert sanitized["states"][1]["preconditions"] == expected_boundary
    assert sanitized["states"][0]["target_components"] == [
        "source:book",
        "source:blue pen",
    ]
    assert sanitized["states"][1]["target_components"] == ["source:书"]
    assert sanitized["states"][0]["verification"] == "书打开；蓝色笔"
    assert sanitized["device"]["role"] == "manual_defined_equipment"
    assert sanitized["task"]["task_id"] == "book_pen_01_procedure"
    assert ManualService._constraints_need_repair(sanitized) is True


def test_constraint_repair_changes_predicates_but_keeps_locked_steps(monkeypatch) -> None:
    service = ManualService()
    raw = {
        "device": {"device_id": "d", "name": "demo"},
        "task": {"task_id": "t", "manual_id": "m"},
        "states": [
            {
                "instruction": "开始前状态 S0",
                "preconditions": ["物体入镜"],
                "postconditions": ["书", "笔"],
                "target_components": ["book", "pen"],
                "verification": "书和笔可见",
                "manual_provenance": {"page": 1, "section": "开始前"},
            },
            {
                "instruction": "合上书",
                "preconditions": ["书", "笔"],
                "postconditions": ["书合上"],
                "wrong_states": ["书仍打开"],
                "target_components": ["book"],
                "verification": "书合上",
                "manual_provenance": {"page": 2, "section": "步骤 1"},
            },
        ],
    }
    sanitized = ManualService._sanitize_procedure_payload(raw)
    locked_instructions = [state["instruction"] for state in sanitized["states"]]

    monkeypatch.setattr(
        service.ollama,
        "chat_structured",
        lambda **_: {
            "states": [
                {
                    "state_id": "S0",
                    "preconditions": ["书和笔完整入镜"],
                    "postconditions": ["书完全打开", "笔水平位于书左边且不接触书"],
                    "wrong_states": ["书已合上", "笔不在书左边"],
                    "target_components": ["source:书", "source:笔"],
                    "verification": "书打开且笔水平位于左边",
                    "source_text": "把书摊开，笔水平放在书的左边。",
                },
                {
                    "state_id": "S1",
                    "preconditions": ["书完全打开", "笔水平位于书左边且不接触书"],
                    "postconditions": ["书完全合上", "笔仍在书左边"],
                    "wrong_states": ["书仍打开"],
                    "target_components": ["source:书"],
                    "verification": "书完全合上",
                    "source_text": "合上摊开的书。",
                },
            ]
        },
    )

    repaired = service._repair_observable_constraints(sanitized, "manual text")

    assert [state["instruction"] for state in repaired["states"]] == locked_instructions
    assert repaired["states"][0]["postconditions"] == [
        "书完全打开",
        "笔水平位于书左边且不接触书",
    ]
    assert repaired["states"][0]["wrong_states"] == [
        "书已合上",
        "笔不在书左边",
    ]
    assert repaired["states"][0]["manual_provenance"]["source_text"] == (
        "把书摊开，笔水平放在书的左边。"
    )
    assert ManualService._constraints_need_repair(repaired) is False


def test_manual_parser_deduplicates_text_and_rendered_page_steps() -> None:
    base_task = {"task_id": "t", "manual_id": "m"}
    initial = {
        "instruction": "开始前状态 S0",
        "preconditions": ["书和笔入镜"],
        "postconditions": ["书打开", "笔在左边"],
        "wrong_states": ["书合上"],
        "target_components": ["source:书", "source:笔"],
        "verification": "书打开且笔在左边",
        "manual_provenance": {"page": 1, "section": "开始前"},
    }
    close = {
        "instruction": "步骤 1 合上摊开的书。",
        "preconditions": ["书打开", "笔在左边"],
        "postconditions": ["书合上", "笔仍在左边"],
        "wrong_states": ["书仍打开"],
        "target_components": ["source:书"],
        "verification": "书合上且笔仍在左边",
        "manual_provenance": {"page": 2, "section": "步骤 1"},
    }
    move = {
        "instruction": "步骤 2 把笔移动到书上。",
        "preconditions": ["书合上", "笔在左边"],
        "postconditions": ["笔在书上"],
        "wrong_states": ["笔仍在左边"],
        "target_components": ["source:笔", "target:书"],
        "verification": "笔在书上",
        "manual_provenance": {"page": 2, "section": "步骤 2"},
    }
    duplicate_initial = dict(initial)
    duplicate_initial["manual_provenance"] = {
        "page": 1,
        "section": "重复的开始前状态",
    }
    raw = {
        "task": base_task,
        "states": [initial, close, move, duplicate_initial, dict(close), dict(move)],
    }

    sanitized = ManualService._sanitize_procedure_payload(raw)

    assert [state["instruction"] for state in sanitized["states"]] == [
        "开始前状态 S0",
        "步骤 1 合上摊开的书。",
        "步骤 2 把笔移动到书上。",
    ]
    assert [state["state_id"] for state in sanitized["states"]] == [
        "S0",
        "S1",
        "S2",
    ]


def test_manual_parser_drops_guidance_system_meta_steps() -> None:
    raw = {
        "task": {"task_id": "t", "manual_id": "m"},
        "states": [
            {
                "instruction": "开始前状态 S0",
                "preconditions": ["书和笔入镜"],
                "postconditions": ["书打开，笔在左边"],
            },
            {
                "instruction": "合上摊开的书",
                "preconditions": ["书打开"],
                "postconditions": ["书合上"],
            },
            {
                "instruction": "当前进度定位",
                "postconditions": ["界面显示下一步"],
            },
            {
                "instruction": "Next_on_success",
                "postconditions": ["自动推进"],
            },
        ],
    }
    sanitized = ManualService._sanitize_procedure_payload(raw)
    assert [item["instruction"] for item in sanitized["states"]] == [
        "开始前状态 S0",
        "合上摊开的书",
    ]
    assert sanitized["states"][0]["state_type"] == "initial_state"
    assert sanitized["states"][1]["state_type"] == "action"
    assert sanitized["states"][1]["next_on_success"] is None
    assert sanitized["states"][0]["preconditions"] != sanitized["states"][0]["postconditions"]
    assert sanitized["states"][0]["wrong_states"] != sanitized["states"][0]["postconditions"]
    assert sanitized["states"][1]["preconditions"] == sanitized["states"][0]["postconditions"]


def test_manual_compiler_persists_one_observation_node_per_condition() -> None:
    raw = {
        "device": {"device_id": "demo", "name": "Demo"},
        "task": {"task_id": "demo", "manual_id": "manual"},
        "states": [
            {
                "instruction": "确认初始状态",
                "preconditions": ["设备入镜"],
                "postconditions": ["底座安装在设备右侧", "PTFE管已连接工具头进料口"],
                "wrong_states": ["底座缺失", "PTFE管未连接"],
                "target_components": ["source:底座", "source:PTFE管", "target:工具头进料口"],
                "verification": "确认两个可见条件",
                "manual_provenance": {
                    "page": 3,
                    "section": "安装检查",
                    "source_text": "检查底座与PTFE连接。",
                },
            }
        ],
    }
    sanitized = ManualService._sanitize_procedure_payload(raw)
    state = sanitized["states"][0]
    assert [node["condition"] for node in state["observation_nodes"]] == state["postconditions"]
    assert [node["inspection_id"] for node in state["observation_nodes"]] == ["S0-C1", "S0-C2"]
    assert state["observation_nodes"][0]["viewpoint"] == "right"
    assert state["observation_nodes"][1]["visualization"] == "polyline"
    assert all(node["manual_provenance"]["page"] == 3 for node in state["observation_nodes"])


def test_manual_compiler_rejects_explicit_multi_action_state() -> None:
    raw = {
        "task": {"task_id": "demo", "manual_id": "manual"},
        "states": [
            {
                "instruction": "安装支架，然后插入PTFE管",
                "preconditions": ["支架与PTFE管可见"],
                "postconditions": ["支架已安装", "PTFE管已插入"],
                "verification": "两个动作完成",
            }
        ],
    }
    with pytest.raises(ValueError, match="multiple independently ordered actions"):
        ManualService._sanitize_procedure_payload(raw)


def test_low_confidence_start_requires_audited_human_override() -> None:
    response = client.post(
        "/api/manuals?mode=ollama&device_profile=bambu_a1_mini",
        files=[("files", ("A1_mini.pdf", b"%PDF", "application/pdf"))],
    )
    assert response.status_code == 202
    procedure_id = response.json()["job_id"]
    rejected = client.post(
        "/api/guidance/start-confirmations",
        json={
            "procedure_id": procedure_id,
            "recommended_step_id": "S6",
            "confidence": 0.62,
            "human_override": False,
            "device_identity": "a1_mini",
            "procedure_compatible": "true",
        },
    )
    assert rejected.status_code == 409
    accepted = client.post(
        "/api/guidance/start-confirmations",
        json={
            "procedure_id": procedure_id,
            "recommended_step_id": "S6",
            "confidence": 0.62,
            "human_override": True,
            "override_reason": "all boundary observation nodes reviewed",
            "device_identity": "a1_mini",
            "procedure_compatible": "true",
        },
    )
    assert accepted.status_code == 200
    assert accepted.json()["accepted"] is True
    assert accepted.json()["audit_id"]


@pytest.mark.parametrize(
    ("raw_confidence", "expected"),
    [(85, 0.85), ("62%", 0.62), (0.45, 0.45)],
)
def test_state_localization_normalizes_percentage_confidence(
    raw_confidence, expected
) -> None:
    payload = {
        "observed_summary": "visible equipment",
        "completed_step_ids": [],
        "recommended_step_id": "S0",
        "evidence": "visible equipment",
        "confidence": raw_confidence,
        "requires_human_confirmation": True,
        "unavailable_checks": [],
    }
    normalized = ManualService._normalize_state_localization_payload(payload)
    assert normalized["confidence"] == pytest.approx(expected)
    StateLocalizationResult.model_validate(normalized)


def test_state_localization_rejects_impossible_confidence_conservatively() -> None:
    payload = {
        "observed_summary": "visible equipment",
        "completed_step_ids": [],
        "recommended_step_id": "S0",
        "evidence": "visible equipment",
        "confidence": 150,
        "requires_human_confirmation": False,
        "unavailable_checks": [],
    }
    normalized = ManualService._normalize_state_localization_payload(payload)
    assert normalized["confidence"] == 0.0
    assert normalized["requires_human_confirmation"] is True
    assert normalized["unavailable_checks"]


def test_book_pen_scene_facts_map_to_manual_state(monkeypatch) -> None:
    service = ManualService()
    procedure = service._load_mock_procedure(
        [("TWO_OBJECT_BOOK_PEN_manual.pdf", "application/pdf", b"mock")]
    )
    request = StateLocalizationRequest(
        procedure_id="test",
        image_base64=_image_base64(),
        mode="ollama",
    )

    scenes = [
        (
            {
                "book_state": "open",
                "pen_relation": "left_of_book",
                "pen_orientation": "horizontal",
                "evidence": "open book and pen on the left",
            },
            "S1",
            ["S0"],
        ),
        (
            {
                "book_state": "closed",
                "pen_relation": "left_of_book",
                "pen_orientation": "horizontal",
                "evidence": "closed book and pen on the left",
            },
            "S2",
            ["S0", "S1"],
        ),
        (
            {
                "book_state": "closed",
                "pen_relation": "on_book_right_half",
                "pen_orientation": "horizontal",
                "evidence": "closed book; pen is off-script on the right",
            },
            "S2",
            ["S0", "S1"],
        ),
    ]
    for facts, expected_step, expected_completed in scenes:
        monkeypatch.setattr(
            service.ollama,
            "chat_structured",
            lambda **_kwargs: facts,
        )
        result = service._locate_book_pen_facts(request, procedure)
        assert result is not None
        assert result.recommended_step_id == expected_step
        assert result.completed_step_ids == expected_completed


def test_book_pen_verification_uses_state_graph_not_free_step_guess() -> None:
    service = ManualService()
    procedure = service._load_mock_procedure(
        [("TWO_OBJECT_BOOK_PEN_manual.pdf", "application/pdf", b"mock")]
    )
    localized = StateLocalizationResult(
        observed_summary=(
            "可见场景事实：书=closed；笔相对位置=left_of_book；"
            "笔方向=horizontal。"
        ),
        completed_step_ids=["S0", "S1"],
        recommended_step_id="S2",
        evidence="书已合上，笔仍在书左侧。",
        confidence=0.88,
        requires_human_confirmation=True,
    )

    completed = service._verification_from_book_pen_localization(
        procedure.states[1],
        procedure,
        localized,
    )
    assert completed.status == "completed"
    assert completed.matched_step_id == "S1"

    next_step = service._verification_from_book_pen_localization(
        procedure.states[2],
        procedure,
        localized,
    )
    assert next_step.status == "in_progress"
    assert next_step.matched_step_id == "S2"


def test_mask_tracking_session_returns_shape_and_follows_pen() -> None:
    created = client.post(
        "/api/tracking/sessions",
        json={
            "image_base64": _pen_image_base64(25),
            "component_id": "source:蓝色笔",
            "bbox_0_1000": [130, 380, 560, 590],
        },
    )
    assert created.status_code == 201
    payload = created.json()
    assert payload["tracked"]["status"] == "tracking"
    assert payload["tracked"]["polygon_0_1000"]
    assert payload["tracked"]["overlay_png_base64"]
    first_x = payload["tracked"]["centroid_0_1000"][0]

    updated = client.post(
        f"/api/tracking/sessions/{payload['session_id']}/frames",
        json={
            "image_base64": _pen_image_base64(55),
            "world_anchor_status": "anchored",
            "client_drift_ratio": 0.021,
            "client_relocalization_count": 2,
        },
    )
    assert updated.status_code == 200
    assert updated.json()["status"] == "tracking"
    assert updated.json()["centroid_0_1000"][0] > first_x + 80
    assert updated.json()["world_anchor_status"] == "anchored"
    assert updated.json()["drift_ratio"] == 0.021
    assert updated.json()["relocalization_count"] == 2

    deleted = client.delete(
        f"/api/tracking/sessions/{payload['session_id']}"
    )
    assert deleted.status_code == 204


def test_book_tracking_uses_pixel_mask_not_full_prompt_box() -> None:
    prompt = [150, 100, 900, 950]
    created = client.post(
        "/api/tracking/sessions",
        json={
            "image_base64": _book_image_base64(),
            "component_id": "source:书",
            "bbox_0_1000": prompt,
        },
    )
    assert created.status_code == 201
    payload = created.json()
    tracked = payload["tracked"]
    assert tracked["status"] == "tracking"
    assert tracked["provider"] == "opencv-grabcut-lk-baseline"
    assert tracked["polygon_0_1000"]
    assert tracked["overlay_png_base64"]

    tracked_box = tracked["bbox_0_1000"]
    tracked_area = (tracked_box[2] - tracked_box[0]) * (
        tracked_box[3] - tracked_box[1]
    )
    prompt_area = (prompt[2] - prompt[0]) * (prompt[3] - prompt[1])
    assert tracked_area < prompt_area * 0.75

    deleted = client.delete(
        f"/api/tracking/sessions/{payload['session_id']}"
    )
    assert deleted.status_code == 204


def test_unknown_tracking_session_is_rejected() -> None:
    response = client.post(
        "/api/tracking/sessions/missing/frames",
        json={"image_base64": _image_base64()},
    )
    assert response.status_code == 404


def test_small_ams_control_rejects_failed_full_box_mask() -> None:
    created = client.post(
        "/api/tracking/sessions",
        json={
            "image_base64": _image_base64(),
            "component_id": "target:AMS Lite 1号送料口",
            "bbox_0_1000": [100, 100, 900, 900],
        },
    )
    assert created.status_code == 201
    tracked = created.json()["tracked"]
    assert tracked["status"] == "lost"
    assert tracked["requires_redetection"] is True
    assert tracked["mask_quality_passed"] is False
    assert tracked["overlay_png_base64"] == ""
