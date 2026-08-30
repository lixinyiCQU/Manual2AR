from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import ProcedureDocument


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROFILE_ROOTS = {
    "bambu_a1_mini": PROJECT_ROOT / "examples" / "bambu_a1_mini_v1",
    "bambu_a1_mini_ams_lite": (
        PROJECT_ROOT / "examples" / "bambu_a1_mini_ams_lite_v1"
    ),
}


class DeviceProfileError(ValueError):
    pass


@dataclass(frozen=True)
class DeviceProfile:
    profile_id: str
    device_id: str
    display_name: str
    supported_variant: str
    task_scope: str
    root: Path
    manual_path: Path
    procedure_path: Path
    component_lexicon: dict[str, dict[str, Any]]
    state_reference_images: dict[str, list[str]]
    instruction_translations: dict[str, dict[str, str]]

    def load_procedure(self, guidance_language: str = "zh") -> ProcedureDocument:
        try:
            payload = json.loads(self.procedure_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise DeviceProfileError(
                f"Unable to read procedure for device profile {self.profile_id}: {exc}"
            ) from exc
        procedure = ProcedureDocument.model_validate(payload)
        translations = self.instruction_translations.get(
            guidance_language,
            {},
        )
        if translations:
            procedure = procedure.model_copy(deep=True)
            for state in procedure.states:
                translated = str(translations.get(state.state_id, "")).strip()
                if translated:
                    state.instruction = translated
        return procedure

    def reference_paths(self, state_ids: list[str] | None = None) -> list[Path]:
        names: list[str] = []
        selected = state_ids or list(self.state_reference_images)
        for state_id in selected:
            for name in self.state_reference_images.get(state_id, []):
                if name not in names:
                    names.append(name)
        paths = [self.root / name for name in names]
        return [path for path in paths if path.is_file()]

    def grounding_context(self, component_ids: list[str]) -> str:
        lines = [
            f"设备：{self.display_name}",
            f"适用版本：{self.supported_variant}",
            f"任务范围：{self.task_scope}",
        ]
        for component_id in component_ids:
            base_name = component_id.split(":", 1)[-1].strip()
            item = self.component_lexicon.get(base_name)
            if not isinstance(item, dict):
                continue
            aliases = "、".join(str(value) for value in item.get("aliases", []))
            visual = str(item.get("visual_description", "")).strip()
            lines.append(
                f"- {component_id}：别名={aliases or base_name}；视觉特征={visual}"
            )
        return "\n".join(lines)


def load_device_profile(profile_id: str | None) -> DeviceProfile | None:
    normalized = str(profile_id or "").strip().lower()
    if not normalized:
        return None
    if normalized not in PROFILE_ROOTS:
        raise DeviceProfileError(f"Unknown device profile: {profile_id}")

    profile_root = PROFILE_ROOTS[normalized]
    profile_path = profile_root / "profile.json"
    try:
        payload = json.loads(profile_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DeviceProfileError(f"Unable to read {profile_path}: {exc}") from exc

    return DeviceProfile(
        profile_id=str(payload["profile_id"]),
        device_id=str(payload["device_id"]),
        display_name=str(payload["display_name"]),
        supported_variant=str(payload["supported_variant"]),
        task_scope=str(payload["task_scope"]),
        root=profile_root,
        manual_path=profile_root / str(payload["manual_path"]),
        procedure_path=profile_root / str(payload["procedure_path"]),
        component_lexicon=dict(payload.get("component_lexicon", {})),
        state_reference_images={
            str(key): [str(value) for value in values]
            for key, values in payload.get("state_reference_images", {}).items()
        },
        instruction_translations={
            str(language): {
                str(state_id): str(instruction)
                for state_id, instruction in translations.items()
            }
            for language, translations in payload.get(
                "instruction_translations",
                {},
            ).items()
        },
    )


def profile_for_procedure(procedure: ProcedureDocument) -> DeviceProfile | None:
    if procedure.device.device_id == "bambu_a1_mini":
        return load_device_profile("bambu_a1_mini")
    if procedure.device.device_id == "bambu_a1_mini_ams_lite":
        return load_device_profile("bambu_a1_mini_ams_lite")
    return None
