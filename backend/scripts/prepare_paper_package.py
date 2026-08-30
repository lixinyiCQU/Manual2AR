#!/usr/bin/env python3
"""Build an audited Manual2AR paper package from recorded evidence.

For panels with ``evidence_json`` this command first renders a clean overlay
from the recorded geometry.  It then runs panel-specific gates and exports the
300 dpi figures only when every panel passes.  A failing run always leaves an
audit report explaining what must be recaptured.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

try:
    from scripts.audit_paper_evidence import audit
    from scripts.export_paper_evidence import export
    from scripts.render_recorded_overlay import render
except ModuleNotFoundError:  # Direct execution: python scripts/prepare_paper_package.py
    from audit_paper_evidence import audit
    from export_paper_evidence import export
    from render_recorded_overlay import render


def _resolve(base: Path, value: str, label: str) -> Path:
    if value.startswith("REPLACE_"):
        raise ValueError(f"{label} is still a template placeholder: {value}")
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = (base / path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"{label} does not exist: {path}")
    return path


def prepare(spec_path: Path, output_root: Path) -> dict[str, Any]:
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    output_root.mkdir(parents=True, exist_ok=True)
    overlay_root = output_root / "generated_overlays"
    working = json.loads(json.dumps(spec))

    for panel in working.get("panels") or []:
        figure_id = str(panel["figure_id"]).lower()
        run_id = str(panel.get("run_id") or f"figure-{figure_id}")
        raw_path = _resolve(spec_path.parent, str(panel["raw_image"]), "raw_image")
        panel["raw_image"] = str(raw_path.resolve())
        for key in ("result_json", "tracking_log"):
            if panel.get(key):
                panel[key] = str(
                    _resolve(spec_path.parent, str(panel[key]), key).resolve()
                )
        evidence_value = panel.get("evidence_json")
        if evidence_value:
            evidence_path = _resolve(spec_path.parent, str(evidence_value), "evidence_json")
            panel["evidence_json"] = str(evidence_path.resolve())
            overlay_path = overlay_root / f"figure_{figure_id}_{run_id}.png"
            provenance_path = overlay_root / f"figure_{figure_id}_{run_id}.provenance.json"
            render(
                raw_path=raw_path,
                evidence_path=evidence_path,
                output_path=overlay_path,
                provenance_path=provenance_path,
            )
            panel["overlay_image"] = str(overlay_path.resolve())
            panel["overlay_provenance"] = str(provenance_path.resolve())
        else:
            panel["overlay_image"] = str(
                _resolve(
                    spec_path.parent,
                    str(panel["overlay_image"]),
                    "overlay_image",
                ).resolve()
            )

    working_spec = output_root / "resolved_paper_evidence_spec.json"
    working_spec.write_text(
        json.dumps(working, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    report = audit(working_spec)
    audit_path = output_root / "paper_evidence_audit.json"
    audit_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if not report["passed"]:
        failures = sum(len(panel["failures"]) for panel in report["panels"])
        raise ValueError(
            f"paper evidence audit failed with {failures} issue(s); see {audit_path}"
        )
    manifest = export(working_spec, output_root)
    manifest["audit_report"] = str(audit_path.resolve())
    manifest_path = output_root / "figure_evidence_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("spec", type=Path)
    parser.add_argument("output_root", type=Path)
    args = parser.parse_args()
    manifest = prepare(args.spec.resolve(), args.output_root.resolve())
    print(f"prepared {len(manifest['panels'])} audited paper panels")
    print(args.output_root.resolve() / "figure_evidence_manifest.json")


if __name__ == "__main__":
    main()
