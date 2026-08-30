from __future__ import annotations

import base64
import json
import os
import threading
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from typing import Protocol

from .models import GuidanceTarget, TrackedComponent, TrackingSessionResponse
from .tracking import OpenCvMaskTracker


class TrackingProviderError(RuntimeError):
    pass


class MaskTracker(Protocol):
    provider_name: str

    def start(
        self,
        image_bytes: bytes,
        component_id: str,
        bbox_0_1000: list[int],
        guidance_target: GuidanceTarget | None = None,
    ) -> tuple[str, TrackedComponent]: ...

    def update(self, session_id: str, image_bytes: bytes) -> TrackedComponent: ...

    def close(self, session_id: str) -> bool: ...


class RemoteSam2Tracker:
    """Client for a GPU service that implements the Manual2AR mask contract."""

    provider_name = "remote-sam2"

    def __init__(self, base_url: str, timeout_seconds: float = 15.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def start(
        self,
        image_bytes: bytes,
        component_id: str,
        bbox_0_1000: list[int],
        guidance_target: GuidanceTarget | None = None,
    ) -> tuple[str, TrackedComponent]:
        payload = self._post(
            "/api/tracking/sessions",
            {
                "image_base64": base64.b64encode(image_bytes).decode("ascii"),
                "component_id": component_id,
                "bbox_0_1000": bbox_0_1000,
                "guidance_target": (
                    guidance_target.model_dump(mode="json")
                    if guidance_target is not None
                    else None
                ),
            },
        )
        response = TrackingSessionResponse.model_validate(payload)
        return response.session_id, response.tracked

    def update(self, session_id: str, image_bytes: bytes) -> TrackedComponent:
        payload = self._post(
            f"/api/tracking/sessions/{session_id}/frames",
            {"image_base64": base64.b64encode(image_bytes).decode("ascii")},
        )
        return TrackedComponent.model_validate(payload)

    def close(self, session_id: str) -> bool:
        request = urllib.request.Request(
            f"{self.base_url}/api/tracking/sessions/{session_id}",
            method="DELETE",
        )
        try:
            with urllib.request.urlopen(
                request,
                timeout=self.timeout_seconds,
            ) as response:
                return response.status == 204
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return False
            raise TrackingProviderError(
                f"SAM2 service returned HTTP {exc.code} while closing a session"
            ) from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise TrackingProviderError(f"SAM2 service is unavailable: {exc}") from exc

    def health(self) -> dict[str, object]:
        request = urllib.request.Request(f"{self.base_url}/health", method="GET")
        try:
            with urllib.request.urlopen(request, timeout=1.5) as response:
                payload = json.loads(response.read().decode("utf-8"))
            return {
                "available": response.status == 200,
                "provider": str(payload.get("tracking_provider", self.provider_name)),
                "detail": str(payload.get("status", "ok")),
            }
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            return {
                "available": False,
                "provider": self.provider_name,
                "detail": str(exc),
            }

    def _post(self, path: str, payload: dict[str, object]) -> dict[str, object]:
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(
                request,
                timeout=self.timeout_seconds,
            ) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise TrackingProviderError(
                f"SAM2 service returned HTTP {exc.code}: {detail}"
            ) from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise TrackingProviderError(f"SAM2 service is unavailable: {exc}") from exc


@dataclass(frozen=True)
class _Route:
    tracker: MaskTracker
    internal_session_id: str


class HybridMaskTracker:
    """Route sessions to GPU SAM2 or the honest CPU fallback.

    `auto` tries the configured GPU service and falls back only when session
    creation fails. An existing GPU session never silently changes provider,
    because doing so would lose temporal state and make experiment logs false.
    """

    provider_name = "hybrid-sam2-opencv"

    def __init__(
        self,
        mode: str | None = None,
        remote: MaskTracker | None = None,
        local: MaskTracker | None = None,
    ) -> None:
        configured = (mode or os.getenv("MANUAL2AR_TRACKING_PROVIDER", "auto")).lower()
        if configured not in {"auto", "opencv", "sam2"}:
            raise ValueError(
                "MANUAL2AR_TRACKING_PROVIDER must be auto, opencv, or sam2"
            )
        remote_url = os.getenv("MANUAL2AR_SAM2_URL", "").strip()
        timeout = float(os.getenv("MANUAL2AR_SAM2_TIMEOUT_SECONDS", "15"))
        self.mode = configured
        self.local = local or OpenCvMaskTracker()
        self.remote = remote or (
            RemoteSam2Tracker(remote_url, timeout) if remote_url else None
        )
        self.remote_url = remote_url or None
        self._routes: dict[str, _Route] = {}
        self._lock = threading.Lock()
        self.last_remote_error: str | None = None

    def start(
        self,
        image_bytes: bytes,
        component_id: str,
        bbox_0_1000: list[int],
        guidance_target: GuidanceTarget | None = None,
    ) -> tuple[str, TrackedComponent]:
        tracker: MaskTracker = self.local
        internal_id: str
        tracked: TrackedComponent

        if self.mode in {"auto", "sam2"}:
            if self.remote is None:
                if self.mode == "sam2":
                    raise TrackingProviderError(
                        "SAM2 mode requires MANUAL2AR_SAM2_URL"
                    )
            else:
                try:
                    if guidance_target is None:
                        # Keep third-party/test providers that implement the
                        # pre-1.0 protocol usable. New clients always send the
                        # explicit target contract when one is available.
                        internal_id, tracked = self.remote.start(
                            image_bytes,
                            component_id,
                            bbox_0_1000,
                        )
                    else:
                        internal_id, tracked = self.remote.start(
                            image_bytes,
                            component_id,
                            bbox_0_1000,
                            guidance_target,
                        )
                    tracker = self.remote
                    self.last_remote_error = None
                    return self._register(tracker, internal_id, tracked)
                except TrackingProviderError as exc:
                    self.last_remote_error = str(exc)
                    if self.mode == "sam2":
                        raise

        if guidance_target is None:
            internal_id, tracked = self.local.start(
                image_bytes,
                component_id,
                bbox_0_1000,
            )
        else:
            internal_id, tracked = self.local.start(
                image_bytes,
                component_id,
                bbox_0_1000,
                guidance_target,
            )
        return self._register(tracker, internal_id, tracked)

    def update(self, session_id: str, image_bytes: bytes) -> TrackedComponent:
        with self._lock:
            route = self._routes.get(session_id)
        if route is None:
            raise KeyError(session_id)
        try:
            return route.tracker.update(route.internal_session_id, image_bytes)
        except TrackingProviderError:
            with self._lock:
                self._routes.pop(session_id, None)
            raise

    def close(self, session_id: str) -> bool:
        with self._lock:
            route = self._routes.pop(session_id, None)
        if route is None:
            return False
        return route.tracker.close(route.internal_session_id)

    def health(self) -> dict[str, object]:
        remote_health = (
            self.remote.health()
            if isinstance(self.remote, RemoteSam2Tracker)
            else {
                "available": self.remote is not None,
                "provider": getattr(self.remote, "provider_name", "none"),
                "detail": "in-process test provider" if self.remote else "not configured",
            }
        )
        return {
            "mode": self.mode,
            "active_default": (
                str(remote_health["provider"])
                if self.mode == "sam2"
                or (self.mode == "auto" and bool(remote_health["available"]))
                else self.local.provider_name
            ),
            "remote_url": self.remote_url,
            "remote_available": bool(remote_health["available"]),
            "remote_provider": str(remote_health["provider"]),
            "last_remote_error": self.last_remote_error,
        }

    def _register(
        self,
        tracker: MaskTracker,
        internal_id: str,
        tracked: TrackedComponent,
    ) -> tuple[str, TrackedComponent]:
        public_id = uuid.uuid4().hex
        with self._lock:
            self._routes[public_id] = _Route(tracker, internal_id)
        return public_id, tracked
