from __future__ import annotations

import io

import pytest
from PIL import Image

from app.models import TrackedComponent
from app.tracking import OpenCvMaskTracker
from app.tracking_provider import HybridMaskTracker, TrackingProviderError


class _FailingRemote:
    provider_name = "fake-sam2"

    def start(self, *_args, **_kwargs):
        raise TrackingProviderError("intentional remote outage")

    def update(self, *_args, **_kwargs):
        raise TrackingProviderError("intentional remote outage")

    def close(self, _session_id: str) -> bool:
        return True


class _WorkingRemote:
    provider_name = "fake-sam2"

    def __init__(self) -> None:
        self.closed = False

    def start(self, _image, component_id, bbox):
        return "remote-internal", TrackedComponent(
            component_id=component_id,
            status="tracking",
            quality=0.97,
            bbox_0_1000=bbox,
            polygon_0_1000=[
                [bbox[0], bbox[1]],
                [bbox[2], bbox[1]],
                [bbox[2], bbox[3]],
            ],
            centroid_0_1000=[
                (bbox[0] + bbox[2]) // 2,
                (bbox[1] + bbox[3]) // 2,
            ],
            provider="facebook/sam2.1-hiera-tiny+box-mask+lk",
        )

    def update(self, session_id, _image):
        assert session_id == "remote-internal"
        return TrackedComponent(
            component_id="source:pen",
            status="tracking",
            quality=0.95,
            bbox_0_1000=[100, 100, 300, 300],
            polygon_0_1000=[[100, 100], [300, 100], [300, 300]],
            centroid_0_1000=[200, 200],
            provider="facebook/sam2.1-hiera-tiny+box-mask+lk",
        )

    def close(self, session_id: str) -> bool:
        assert session_id == "remote-internal"
        self.closed = True
        return True


def _pen_bytes() -> bytes:
    image = Image.new("RGB", (180, 120), color=(225, 220, 210))
    for px in range(25, 95):
        for py in range(50, 60):
            image.putpixel((px, py), (0, 200, 180))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=95)
    return buffer.getvalue()


def test_auto_mode_falls_back_to_explicit_opencv_provider() -> None:
    hybrid = HybridMaskTracker(
        mode="auto",
        remote=_FailingRemote(),
        local=OpenCvMaskTracker(),
    )
    session_id, tracked = hybrid.start(
        _pen_bytes(),
        "source:蓝色笔",
        [130, 380, 560, 590],
    )
    assert tracked.provider == "opencv-grabcut-lk-baseline"
    assert hybrid.last_remote_error == "intentional remote outage"
    assert hybrid.close(session_id) is True


def test_strict_sam2_mode_never_silently_falls_back() -> None:
    hybrid = HybridMaskTracker(
        mode="sam2",
        remote=_FailingRemote(),
        local=OpenCvMaskTracker(),
    )
    with pytest.raises(TrackingProviderError, match="intentional remote outage"):
        hybrid.start(
            _pen_bytes(),
            "source:蓝色笔",
            [130, 380, 560, 590],
        )


def test_remote_session_keeps_the_same_provider_and_internal_state() -> None:
    remote = _WorkingRemote()
    hybrid = HybridMaskTracker(
        mode="sam2",
        remote=remote,
        local=OpenCvMaskTracker(),
    )
    session_id, tracked = hybrid.start(
        _pen_bytes(),
        "source:pen",
        [100, 100, 300, 300],
    )
    assert tracked.provider.startswith("facebook/sam2.1")
    updated = hybrid.update(session_id, _pen_bytes())
    assert updated.provider == tracked.provider
    assert hybrid.close(session_id) is True
    assert remote.closed is True
