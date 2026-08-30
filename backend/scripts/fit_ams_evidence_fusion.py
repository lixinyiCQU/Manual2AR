from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.evidence_fusion import (
    FEATURE_NAMES,
    EvidenceFusionSample,
    fit_evidence_fusion,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fit the interpretable AMS Lite soft-evidence logistic model."
    )
    parser.add_argument("input_jsonl", type=Path)
    parser.add_argument("output_json", type=Path)
    args = parser.parse_args()

    samples: list[EvidenceFusionSample] = []
    for line_number, line in enumerate(
        args.input_jsonl.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        if not line.strip():
            continue
        payload = json.loads(line)
        try:
            features = tuple(float(payload[name]) for name in FEATURE_NAMES)
            samples.append(
                EvidenceFusionSample(
                    features=features,
                    label=int(payload["human_label"]),
                    necessary_observation_missing=bool(
                        payload.get("necessary_observation_missing", False)
                    ),
                    explicit_safety_conflict=bool(
                        payload.get("explicit_safety_conflict", False)
                    ),
                )
            )
        except (KeyError, TypeError, ValueError) as exception:
            raise ValueError(
                f"invalid labelled sample on line {line_number}: {exception}"
            ) from exception

    model = fit_evidence_fusion(samples)
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(
            {
                "model_type": "logistic_regression",
                "feature_names": FEATURE_NAMES,
                "weights": model.weights,
                "intercept": model.intercept,
                "threshold": model.threshold,
                "training_samples": len(samples),
                "hard_gate_precedence": [
                    "necessary_observation_missing",
                    "explicit_safety_conflict",
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"saved {args.output_json} from {len(samples)} real labelled samples")


if __name__ == "__main__":
    main()

