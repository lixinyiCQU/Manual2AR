from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import (
    StateStartConfirmationRequest,
    StateLocalizationRequest,
    StateLocalizationResult,
    VerificationRequest,
    VerificationResult,
)


class GuidanceEventLogger:
    """Write image-free closed-loop decisions for baseline evaluation."""

    def __init__(
        self,
        root: Path,
        model_name: str,
        provider_name: str = "unknown",
    ) -> None:
        self.root = root
        self.model_name = model_name
        self.provider_name = provider_name
        self._lock = threading.Lock()

    def located(
        self,
        request: StateLocalizationRequest,
        result: StateLocalizationResult,
        latency_ms: float,
    ) -> None:
        self._append(
            {
                "event": "located",
                "run_id": request.run_id,
                "procedure_id": request.procedure_id,
                "mode": request.mode,
                "model": self.model_name if request.mode == "ollama" else "mock",
                "vision_provider": (
                    self.provider_name if request.mode == "ollama" else "mock"
                ),
                "recommended_step_id": result.recommended_step_id,
                "completed_step_ids": result.completed_step_ids,
                "confidence": result.confidence,
                "device_identity": result.device_identity,
                "device_configuration": result.device_configuration,
                "procedure_compatible": result.procedure_compatible,
                "capture_mode": result.capture_mode,
                "requires_human_confirmation": result.requires_human_confirmation,
                "unavailable_check_count": len(result.unavailable_checks),
                "grounded_component_count": len(result.component_boxes_0_1000),
                "latency_ms": round(latency_ms, 2),
            }
        )

    def verified(
        self,
        request: VerificationRequest,
        result: VerificationResult,
        latency_ms: float,
    ) -> None:
        invariant_violation = bool(
            result.safe_to_advance
            and (
                result.status != "completed"
                or result.matched_step_id != request.current_step_id
            )
        )
        self._append(
            {
                "event": "verified",
                "run_id": request.run_id,
                "procedure_id": request.procedure_id,
                "mode": request.mode,
                "model": self.model_name if request.mode == "ollama" else "mock",
                "vision_provider": (
                    self.provider_name if request.mode == "ollama" else "mock"
                ),
                "current_step_id": request.current_step_id,
                "inspection_id": request.inspection_id,
                "is_final_inspection": request.is_final_inspection,
                "retained_inspection_count": len(
                    request.completed_inspection_ids
                ),
                "history_length": len(request.history),
                "status": result.status,
                "matched_step_id": result.matched_step_id,
                "confidence": result.confidence,
                "safe_to_advance": result.safe_to_advance,
                "grounded_component_count": len(result.component_boxes_0_1000),
                "safety_invariant_violation": invariant_violation,
                "latency_ms": round(latency_ms, 2),
            }
        )

    def start_confirmed(
        self,
        request: StateStartConfirmationRequest,
    ) -> str:
        audit_id = uuid.uuid4().hex
        self._append(
            {
                "event": "start_confirmed",
                "audit_id": audit_id,
                "run_id": request.run_id,
                "procedure_id": request.procedure_id,
                "recommended_step_id": request.recommended_step_id,
                "confidence": request.confidence,
                "human_override": request.human_override,
                "override_reason": request.override_reason,
                "count_as_model_success": not request.human_override,
            }
        )
        return audit_id

    def failed(
        self,
        event: str,
        run_id: str | None,
        procedure_id: str,
        mode: str,
        latency_ms: float,
        error_type: str,
        error_message: str | None = None,
    ) -> None:
        self._append(
            {
                "event": event,
                "run_id": run_id,
                "procedure_id": procedure_id,
                "mode": mode,
                "model": self.model_name if mode == "ollama" else "mock",
                "vision_provider": (
                    self.provider_name if mode == "ollama" else "mock"
                ),
                "latency_ms": round(latency_ms, 2),
                "error_type": error_type,
                "error_message": error_message[:400] if error_message else None,
            }
        )

    def _append(self, payload: dict[str, Any]) -> None:
        try:
            now = datetime.now(timezone.utc)
            row = {
                "created_at": now.isoformat(),
                "decision_id": uuid.uuid4().hex,
                **payload,
            }
            self.root.mkdir(parents=True, exist_ok=True)
            path = self.root / f"{now.strftime('%Y%m%d')}.jsonl"
            line = json.dumps(row, ensure_ascii=False, separators=(",", ":"))
            with self._lock:
                with path.open("a", encoding="utf-8") as handle:
                    handle.write(line + "\n")
        except OSError:
            # Evidence logging must never alter a runtime safety decision.
            return
