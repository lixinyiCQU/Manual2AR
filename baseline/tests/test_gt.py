from copy import deepcopy
import json
from pathlib import Path

import pytest

from manual2ar_baseline.gt import (
    Sources, TaskDefinition, digest, encoded, extract_text, load_bundle,
    normalize, snapshot, validate_mapping, verify_sources,
)


BASELINE = Path(__file__).resolve().parents[1]
REFERENCE = BASELINE.parent
GT = BASELINE / "ground_truth/u7/v1"


@pytest.fixture
def mapping():
    return json.loads((GT / "mapping.json").read_bytes())


@pytest.fixture
def sources():
    return Sources.model_validate_json((GT / "sources.json").read_bytes())


def test_u7_source_selection_and_candidate_are_distinct(sources):
    captured, task = load_bundle(GT / "candidate")
    verify_sources(captured, REFERENCE)
    assert captured == sources
    assert len(task.nodes) == 2 and len(task.conditions) == 10
    assert len(task.requirements) == 19
    review = json.loads((GT / "candidate/review.json").read_bytes())
    assert review["source_selection"] == "confirmed_by_user"
    assert review["status"] == "pending_human_review"
    assert review["scene_labels"] == review["spatial_labels"] == "not_provided"
    assert review["automatic_compiler_input"] is False
    records = {s.id: s for s in captured.records}
    assert records["official.base"].kind == "official"
    assert records["reference.base"].kind == "reference_verification"


def test_official_images_are_verified_against_original_evidence(sources):
    evidence = json.loads((REFERENCE / "resources/tasks/bambu_a1_mini/unboxing/v2/evidence.json").read_bytes())
    artifacts = {a.id: a for a in sources.artifacts}
    for image in sources.images:
        artifact = artifacts[image.artifact_id]
        relative = "references/" + Path(artifact.path).name
        assert artifact.sha256 == evidence["images"][relative]["sha256"]
        assert image.role == "official_reference_not_scene"


def test_user_decisions_are_applied_without_rewriting_first_candidate():
    _, task = load_bundle(GT / "candidate-v2")
    assert len(task.conditions) == 8
    conditions = {c.id: c for c in task.conditions}
    assert "c.base.screws" in conditions
    assert conditions["c.base.screws"].object_ids == ["base", "upper_screw", "lower_screw"]
    assert "c.base.upper_screw" not in conditions and "c.base.screw_specification" not in conditions
    requirement = next(r for r in task.requirements if r.id == "r.base.specification")
    assert requirement.kind == "material_selection"
    assert requirement.id in task.nodes[0].requirement_ids
    assert not any(requirement.id in c.requirement_ids for c in task.conditions)
    assert conditions["c.base.secure"].channel == "manual"
    assert conditions["c.base.direction"].channel == conditions["c.holder.direction"].channel == "unresolved"
    review = json.loads((GT / "candidate-v2/review.json").read_bytes())
    assert review["resolved_items"] == ["review.decomposition", "review.specification"]
    assert review["status"] == "pending_human_review" and len(review["items"]) == 2
    assert review["reviewed_task_sha256"] == digest((GT / "candidate/task.json").read_bytes())


def test_review_decisions_are_bound_to_the_exact_new_task(tmp_path, mapping):
    path = tmp_path / "mapping.json"
    mapping["nodes"][0]["instruction"] += " changed"
    path.write_bytes(encoded(mapping))
    with pytest.raises(ValueError, match="does not match"):
        normalize(GT / "sources.json", path, tmp_path / "bundle", GT / "human-review.json")
    assert not (tmp_path / "bundle").exists()


def test_reviewed_candidate_rebuild_matches_every_frozen_file(tmp_path):
    normalize(GT / "sources.json", GT / "mapping.json", tmp_path / "bundle", GT / "human-review.json")
    for path in (GT / "candidate-v2").iterdir():
        assert path.read_bytes() == (tmp_path / "bundle" / path.name).read_bytes()


def test_normalization_is_deterministic_and_never_overwrites(tmp_path):
    for name in ("first", "second"):
        normalize(GT / "sources.json", GT / "mapping.json", tmp_path / name)
    for path in (tmp_path / "first").iterdir():
        assert path.read_bytes() == (tmp_path / "second" / path.name).read_bytes()
    with pytest.raises(FileExistsError):
        normalize(GT / "sources.json", GT / "mapping.json", tmp_path / "first")


@pytest.mark.parametrize("mutation", ["cycle", "unknown_object", "unknown_condition", "unknown_goal", "empty_check", "duplicate", "channel", "extra_state"])
def test_invalid_task_contracts_are_rejected(mapping, mutation):
    if mutation == "cycle":
        mapping["nodes"][0]["depends_on"] = ["install_holder"]
    elif mutation == "unknown_object":
        mapping["conditions"][0]["object_ids"] = ["invented_part"]
    elif mutation == "unknown_condition":
        mapping["nodes"][0]["precondition_ids"] = ["invented_condition"]
    elif mutation == "unknown_goal":
        mapping["goal_condition_ids"] = ["invented_condition"]
    elif mutation == "empty_check":
        mapping["nodes"][0]["completion_ids"] = []
    elif mutation == "duplicate":
        mapping["conditions"].append(deepcopy(mapping["conditions"][0]))
    elif mutation == "channel":
        manual = next(c for c in mapping["conditions"] if c["id"] == "c.base.secure")
        manual["channel"] = "vision"
    else:
        mapping["completed"] = True
    with pytest.raises(ValueError):
        TaskDefinition.model_validate(mapping)


def test_requirement_coverage_is_not_replaced_by_valid_citations(mapping):
    for row in [*mapping["nodes"], *mapping["conditions"]]:
        row["requirement_ids"] = [r for r in row["requirement_ids"] if r != "r.base.quantity"]
    with pytest.raises(ValueError, match="Unmapped requirements"):
        TaskDefinition.model_validate(mapping)


def test_specification_must_have_a_check_even_when_linked_to_instruction(mapping):
    for row in mapping["conditions"]:
        row["requirement_ids"] = [r for r in row["requirement_ids"] if r != "r.base.quantity"]
    mapping["nodes"][0]["requirement_ids"].append("r.base.quantity")
    with pytest.raises(ValueError, match="lacks a check"):
        TaskDefinition.model_validate(mapping)


def test_invented_quote_is_not_ground_truth(mapping, sources):
    mapping["requirements"][0]["quote"] = "按 9 Nm 扭矩拧紧"
    task = TaskDefinition.model_validate(mapping)
    with pytest.raises(ValueError, match="quote"):
        validate_mapping(sources, task)


def test_source_text_hash_and_source_coverage_are_checked(mapping, sources):
    value = sources.model_dump()
    value["records"][0]["text"] += " altered"
    with pytest.raises(ValueError, match="hash mismatch"):
        Sources.model_validate(value)
    value = sources.model_dump()
    value["records"].append({**value["records"][0], "id": "unmapped.source"})
    with pytest.raises(ValueError, match="no requirement"):
        validate_mapping(Sources.model_validate(value), TaskDefinition.model_validate(mapping))


@pytest.mark.parametrize("name", ["task.json", "sources.json", "review.json", "REVIEW.md"])
def test_bundle_tampering_is_rejected(tmp_path, name):
    normalize(GT / "sources.json", GT / "mapping.json", tmp_path / "bundle")
    path = tmp_path / "bundle" / name
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="changed"):
        load_bundle(path.parent)


def test_normalizer_cannot_manufacture_human_approval(tmp_path):
    folder = tmp_path / "bundle"
    normalize(GT / "sources.json", GT / "mapping.json", folder)
    path = folder / "review.json"
    review = json.loads(path.read_bytes())
    review["status"] = "approved"
    path.write_bytes(encoded(review))
    manifest = json.loads((folder / "manifest.json").read_bytes())
    manifest["files"]["review.json"] = digest(path.read_bytes())
    (folder / "manifest.json").write_bytes(encoded(manifest))
    with pytest.raises(ValueError, match="Review identity/status"):
        load_bundle(folder)


def test_invalid_manifest_type_is_rejected(tmp_path):
    (tmp_path / "manifest.json").write_text("null")
    with pytest.raises(ValueError, match="Invalid bundle"):
        load_bundle(tmp_path)


def test_source_extraction_never_imports_reference_code(tmp_path):
    source = tmp_path / "definitions.py"
    source.write_text("raise RuntimeError('must never run')\nRULE = 'original definition'\n")
    assert extract_text(source, "python:RULE") == "original definition"
    source.write_text("RULE = make_definition()\n")
    with pytest.raises(ValueError, match="constant"):
        extract_text(source, "python:RULE")


def test_snapshot_checks_expected_hash_and_path_boundaries(tmp_path):
    reference = tmp_path / "reference"
    reference.mkdir()
    (reference / "source.json").write_text('{"text":"original"}')
    selection = dict(schema_version="baseline-sources-v1", source_selection="unconfirmed",
                     artifacts=[dict(id="source", path="source.json")],
                     records=[dict(id="quote", artifact_id="source", locator="json:/text", kind="official")])
    path = tmp_path / "selection.json"
    path.write_bytes(encoded(selection))
    snapshot(path, reference, tmp_path / "sources.json")
    captured = Sources.model_validate_json((tmp_path / "sources.json").read_bytes())
    verify_sources(captured, reference)
    (reference / "source.json").write_text('{"text":"modified"}')
    with pytest.raises(ValueError, match="artifact changed"):
        verify_sources(captured, reference)
    selection["artifacts"][0]["sha256"] = "0" * 64
    path.write_bytes(encoded(selection))
    with pytest.raises(ValueError, match="hash mismatch"):
        snapshot(path, reference, tmp_path / "bad.json")
    selection["artifacts"][0]["path"] = "../selection.json"
    path.write_bytes(encoded(selection))
    with pytest.raises(ValueError):
        snapshot(path, reference, tmp_path / "escaped.json")
    assert not (tmp_path / "bad.json").exists() and not (tmp_path / "escaped.json").exists()


def test_contract_accepts_other_devices_and_more_than_two_nodes():
    # A consumable precondition need not remain true as a final goal.
    value = dict(schema_version="baseline-task-v1", id="cable_assembly", version="1", device_id="other_device",
                 title="Connect three cables", scope="Another task with three independent node identities",
                 objects=[dict(id="cable", name="cable", source_ids=["official"])],
                 requirements=[], conditions=[], nodes=[], goal_condition_ids=["connected3"],
                 review_items=[dict(id="review", targets=["cable_assembly"], question="Review mapping", proposal="pending")])
    for i in range(1, 4):
        rid, cid, nid = f"r{i}", f"connected{i}", f"connect{i}"
        value["requirements"].append(dict(id=rid, kind="operation", source_id="official", quote="Connect cable"))
        value["conditions"].append(dict(id=cid, statement="Cable connected", object_ids=["cable"], requirement_ids=[rid],
                                        channel="vision", scope="visible_state", basis="direct_reference",
                                        standard_status="needs_visual_standard", definition="Interface standard pending"))
        value["nodes"].append(dict(id=nid, instruction="Connect cable", object_ids=["cable"], requirement_ids=[rid],
                                   depends_on=[f"connect{i-1}"] if i > 1 else [], completion_ids=[cid]))
    task = TaskDefinition.model_validate(value)
    assert len(task.nodes) == 3 and len({n.instruction for n in task.nodes}) == 1
