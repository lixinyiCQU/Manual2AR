from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import TrackedComponent, TrackingSessionRequest


class TrackingEventLogger:
    """Append image-free tracking telemetry for reproducible evaluation."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self._lock = threading.Lock()
        self._metadata: dict[str, dict[str, Any]] = {}

    def started(
        self,
        session_id: str,
        request: TrackingSessionRequest,
        tracked: TrackedComponent,
    ) -> None:
        metadata = {
            "run_id": request.run_id,
            "procedure_id": request.procedure_id,
            "step_id": request.step_id,
            "component_id": request.component_id,
            "initial_prompt_bbox_0_1000": request.bbox_0_1000,
            "guidance_target": (
                request.guidance_target.model_dump(mode="json")
                if request.guidance_target is not None
                else None
            ),
        }
        with self._lock:
            self._metadata[session_id] = metadata
        self._append(session_id, "started", tracked, metadata)

    def updated(self, session_id: str, tracked: TrackedComponent) -> None:
        with self._lock:
            metadata = dict(self._metadata.get(session_id, {}))
        self._append(session_id, "updated", tracked, metadata)

    def closed(self, session_id: str) -> None:
        with self._lock:
            metadata = self._metadata.pop(session_id, {})
        self._append(session_id, "closed", None, metadata)

    def _append(
        self,
        session_id: str,
        event: str,
        tracked: TrackedComponent | None,
        metadata: dict[str, Any],
    ) -> None:
        try:
            now = datetime.now(timezone.utc)
            payload: dict[str, Any] = {
                "created_at": now.isoformat(),
                "event": event,
                "session_id": session_id,
                **metadata,
            }
            if tracked is not None:
                payload.update(
                    {
                        "provider": tracked.provider,
                        "status": tracked.status,
                        "quality": tracked.quality,
                        "bbox_0_1000": tracked.bbox_0_1000,
                        "polygon_0_1000": tracked.polygon_0_1000,
                        "centroid_0_1000": tracked.centroid_0_1000,
                        "mask_area_ratio": tracked.mask_area_ratio,
                        "mask_quality_passed": tracked.mask_quality_passed,
                        "mask_quality_reasons": tracked.mask_quality_reasons,
                        "prompt_containment": tracked.prompt_containment,
                        "frame_index": tracked.frame_index,
                        "world_anchor_status": tracked.world_anchor_status,
                        "drift_ratio": tracked.drift_ratio,
                        "relocalization_count": tracked.relocalization_count,
                        "requires_redetection": tracked.requires_redetection,
                    }
                )
            self.root.mkdir(parents=True, exist_ok=True)
            path = self.root / f"{now.strftime('%Y%m%d')}.jsonl"
            line = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            with self._lock:
                with path.open("a", encoding="utf-8") as handle:
                    handle.write(line + "\n")
        except OSError:
            # Telemetry must never change the runtime guidance decision.
            return
