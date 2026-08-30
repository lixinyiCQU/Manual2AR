from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np


FEATURE_NAMES = (
    "qwen_predicate_confidence",
    "slot_topology_consistency",
    "mask_quality",
    "tracking_stability",
    "before_after_change",
    "path_color_consistency",
    "visibility",
)
MINIMUM_TRAINING_SAMPLES = 100


@dataclass(frozen=True)
class EvidenceFusionSample:
    features: tuple[float, ...]
    label: int
    necessary_observation_missing: bool = False
    explicit_safety_conflict: bool = False

    def __post_init__(self) -> None:
        if len(self.features) != len(FEATURE_NAMES):
            raise ValueError(
                f"expected {len(FEATURE_NAMES)} features, got {len(self.features)}"
            )
        if self.label not in (0, 1):
            raise ValueError("label must be 0 or 1")
        if not all(0.0 <= value <= 1.0 for value in self.features):
            raise ValueError("fusion features must be normalized to [0, 1]")


@dataclass(frozen=True)
class EvidenceFusionModel:
    weights: tuple[float, ...]
    intercept: float
    threshold: float = 0.5

    def probability(self, features: Iterable[float]) -> float:
        values = np.asarray(tuple(features), dtype=np.float64)
        if values.shape != (len(FEATURE_NAMES),):
            raise ValueError("feature vector does not match FEATURE_NAMES")
        logit = float(np.dot(values, np.asarray(self.weights)) + self.intercept)
        logit = float(np.clip(logit, -40.0, 40.0))
        return float(1.0 / (1.0 + np.exp(-logit)))

    def safe_decision(
        self,
        features: Iterable[float],
        *,
        necessary_observation_missing: bool,
        explicit_safety_conflict: bool,
    ) -> tuple[bool, float, str]:
        probability = self.probability(features)
        if necessary_observation_missing:
            return False, probability, "necessary_observation_missing"
        if explicit_safety_conflict:
            return False, probability, "explicit_safety_conflict"
        return probability >= self.threshold, probability, "soft_evidence_fusion"


def fit_evidence_fusion(
    samples: Iterable[EvidenceFusionSample],
    *,
    learning_rate: float = 0.12,
    iterations: int = 2500,
    l2: float = 0.01,
) -> EvidenceFusionModel:
    rows = list(samples)
    if len(rows) < MINIMUM_TRAINING_SAMPLES:
        raise ValueError(
            f"need at least {MINIMUM_TRAINING_SAMPLES} real labelled transitions; "
            f"received {len(rows)}"
        )
    labels = np.asarray([row.label for row in rows], dtype=np.float64)
    if len(np.unique(labels)) < 2:
        raise ValueError("training data must contain both completed and failed labels")
    matrix = np.asarray([row.features for row in rows], dtype=np.float64)
    weights = np.zeros(matrix.shape[1], dtype=np.float64)
    intercept = 0.0
    for _ in range(iterations):
        logits = np.clip(matrix @ weights + intercept, -40.0, 40.0)
        predictions = 1.0 / (1.0 + np.exp(-logits))
        error = predictions - labels
        weights -= learning_rate * (
            matrix.T @ error / len(rows) + l2 * weights
        )
        intercept -= learning_rate * float(np.mean(error))
    return EvidenceFusionModel(
        weights=tuple(float(value) for value in weights),
        intercept=float(intercept),
    )

