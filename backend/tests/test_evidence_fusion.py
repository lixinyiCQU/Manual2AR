from __future__ import annotations

import pytest

from app.evidence_fusion import (
    EvidenceFusionModel,
    EvidenceFusionSample,
    fit_evidence_fusion,
)


def test_fusion_refuses_less_than_100_real_labels() -> None:
    samples = [
        EvidenceFusionSample(features=(0.8,) * 7, label=index % 2)
        for index in range(48)
    ]
    with pytest.raises(ValueError, match="at least 100"):
        fit_evidence_fusion(samples)


def test_hard_safety_gate_overrides_high_probability() -> None:
    model = EvidenceFusionModel(weights=(2.0,) * 7, intercept=0.0)
    allowed, probability, reason = model.safe_decision(
        (1.0,) * 7,
        necessary_observation_missing=True,
        explicit_safety_conflict=False,
    )
    assert probability > 0.99
    assert allowed is False
    assert reason == "necessary_observation_missing"


def test_fusion_can_fit_balanced_real_label_shape() -> None:
    samples = []
    for index in range(100):
        positive = index >= 50
        value = 0.85 if positive else 0.15
        samples.append(
            EvidenceFusionSample(features=(value,) * 7, label=int(positive))
        )
    model = fit_evidence_fusion(samples, iterations=500)
    assert model.probability((0.9,) * 7) > model.probability((0.1,) * 7)

