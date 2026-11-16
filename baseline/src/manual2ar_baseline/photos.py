"""Photo experiment records and resumable sessions; no UI, camera or AR coupling."""
import json
from copy import deepcopy
from pathlib import Path
import uuid

from .gt import digest, encoded, load_bundle
from .state import Session
from .vision import Protocol, collect, evaluate, photo, prompt_for, reference_images, refine, scoped_protocol


def seal(folder: Path, status):
    files = {str(p.relative_to(folder)): digest(p.read_bytes()) for p in sorted(folder.rglob("*")) if p.is_file() and p.name != "manifest.json"}
    (folder / "manifest.json").write_bytes(encoded(dict(schema_version="baseline-photo-run-v1", status=status, files=files)))


def check_run(folder: Path):
    manifest = json.loads((folder / "manifest.json").read_bytes())
    if not isinstance(manifest, dict) or manifest.get("schema_version") != "baseline-photo-run-v1" or manifest.get("status") != "success" or not isinstance(manifest.get("files"), dict):
        raise ValueError("Photo run is incomplete or failed")
    actual = {str(p.relative_to(folder)) for p in folder.rglob("*") if p.is_file() and p.name != "manifest.json"}
    if actual != manifest["files"].keys() or not {"session.json", "protocol.json", "plan.json", "request.json"} <= actual:
        raise ValueError("Photo run artifact coverage changed")
    for name, sha in manifest["files"].items():
        path = (folder / name).resolve()
        path.relative_to(folder.resolve())
        if digest(path.read_bytes()) != sha:
            raise ValueError("Photo run artifact changed")


def prepare_session(bundle: Path, protocol_path: Path, *, resume=None, intent=None, same_context=False, context_id=None):
    sources, task = load_bundle(bundle)
    protocol = Protocol.model_validate_json(protocol_path.read_bytes())
    protocol.check(sources, task)
    if resume:
        check_run(resume)
        if not same_context and context_id is None:
            raise ValueError("Resuming requires explicit --same-context or a new --context-id")
        if same_context and context_id is not None:
            raise ValueError("Choose either the same context or a new context")
        if json.loads((resume / "protocol.json").read_bytes()) != protocol.model_dump():
            raise ValueError("Photo session uses another observation protocol")
        previous = json.loads((resume / "session.json").read_bytes())
        if previous.get("evidence_mode") != "experimental_photo_analysis" or (intent and intent != previous["intent"]):
            raise ValueError("Cannot resume another evidence mode or change the task intent")
        session = Session.from_bundle(bundle, previous["session_id"], previous["intent"], evidence_mode="experimental_photo_analysis",
            target_node_ids=previous.get("target_node_ids"), guidance_policy=previous.get("guidance_policy", "strict"))
        if previous.get("task_sha256") != session.task_sha:
            raise ValueError("Photo session task revision changed")
        for event in previous["events"]:
            session.apply(event)
    else:
        session = Session.from_bundle(bundle, "photo." + uuid.uuid4().hex, intent or task.title, evidence_mode="experimental_photo_analysis")
    if context_id:
        session.apply(dict(id="context." + uuid.uuid4().hex, **session.stamp(), kind="context_change", context_id=context_id, reason="操作者明确指定新的现场上下文"))
    return sources, protocol, session


def write_session(folder, protocol, session, request):
    (folder / "protocol.json").write_bytes(encoded(protocol.model_dump()))
    (folder / "request.json").write_bytes(encoded(request))
    (folder / "session.json").write_bytes(encoded(dict(session_id=session.id, task_sha256=session.task_sha,
        evidence_mode=session.evidence_mode, intent=session.intent, events=session.events,
        target_node_ids=getattr(session, "target_node_ids", None), guidance_policy=getattr(session, "guidance_policy", "strict"))))
    plan = session.plan()
    (folder / "plan.json").write_bytes(encoded(plan))
    return plan


def observe(session, sources, protocol, image_path: Path, reference_root: Path, output: Path, client, *, condition_ids=None):
    protocol.check(sources, session.task)
    if session.evidence_mode not in ("experimental_photo_analysis", "experimental_compiled_photo_analysis"):
        raise ValueError("Photo observations need an experimental photo session")
    raw = image_path.read_bytes()
    current, size = photo(raw)
    active = protocol if condition_ids is None else scoped_protocol(protocol, sources, session.task, condition_ids)
    references = reference_images(sources, active, reference_root)
    sha = digest(current)
    owner_ids = {n.id for n in session.task.nodes if any(r.condition_id in n.completion_ids for r in active.rules)}
    requirement_ids = {rid for n in session.task.nodes if n.id in owner_ids for rid in n.requirement_ids}
    requirement_ids.update(session.task.policy_requirement_ids)
    context = dict(user_question=session.intent, user_claims_are_not_evidence=True, task_title=session.task.title,
        official_operations=[dict(node_id=n.id, instruction=n.instruction) for n in session.task.nodes if n.id in owner_ids],
        official_fragments=[dict(source_id=r.source_id, quote=r.quote) for r in session.task.requirements if r.id in requirement_ids])
    prompt, query = prompt_for(session.task, active, sha, references, context=context)
    request = dict(kind="photo_observation", **session.stamp(), frame_id=session.last_frame + 1,
                   capture_sha256=digest(raw), source_sha256=sha, submitted_size=list(size),
                   protocol_sha256=digest(encoded(protocol.model_dump())), provider_kind=client.kind,
                   observation_protocol_sha256=digest(encoded(active.model_dump())),
                   observation_condition_ids=[r.condition_id for r in active.rules],
                   guidance_policy=getattr(session, 'guidance_policy', 'strict'),
                   source_identity_recheck=bool(active.refinement and getattr(session, 'guidance_policy', 'strict') in ('scene_guided', 'evidence_guided')),
                   implementation_sha256=digest(encoded({p.name: digest(p.read_bytes()) for p in Path(__file__).parent.glob("*.py")})),
                   independent_labels="not_provided", semantic_standard="experimental_model_observations_with_rules")
    output.mkdir(parents=True, exist_ok=False)
    (output / "capture.original").write_bytes(raw)
    (output / "scene.jpg").write_bytes(current)
    (output / "query.json").write_bytes(encoded(query))
    (output / "acceptance-rules.json").write_bytes(encoded([r.model_dump() for r in active.rules]))
    (output / "request.json").write_bytes(encoded(request))
    (output / "protocol.json").write_bytes(encoded(protocol.model_dump()))
    (output / "observation-protocol.json").write_bytes(encoded(active.model_dump()))
    for i, ref in enumerate(references):
        (output / f"reference-{i}.jpg").write_bytes(ref["raw"])
    stage = "model_observation"
    try:
        findings = collect(client, prompt, active, sha, [current] + [r["raw"] for r in references], output)
        if active.refinement:
            (output / "coarse-findings.json").write_bytes(encoded(findings.model_dump()))
            stage = "detail_observation"
            findings = refine(session.task, active, findings, current, references, output, client, context=context,
                              verify_source=getattr(session, 'guidance_policy', 'strict') in ('scene_guided', 'evidence_guided'))
        readings, detail = evaluate(active, findings, sha)
        (output / "findings.json").write_bytes(encoded(findings.model_dump()))
        (output / "evaluated.json").write_bytes(encoded(dict(readings=readings, details=detail)))
        stage = "state_update"
        event = dict(id="vision." + uuid.uuid4().hex, **{k: request[k] for k in ("session_id", "task_sha256", "epoch", "revision")},
                     kind="observation", origin="vlm_findings", frame_id=request["frame_id"], source_sha256=sha, values=readings)
        prepared = deepcopy(session)
        prepared.apply(event)
        plan = write_session(output, protocol, prepared, request)
        stage = "review_generation"
        from .photo_review import render
        render(output)
        stage = "state_commit"
        session.apply(event)
    except Exception as failure:
        (output / "failure.json").write_bytes(encoded(dict(stage=stage, error_type=type(failure).__name__, state_not_authorized_by_failure=True)))
        seal(output, "failed")
        raise
    seal(output, "success")
    return plan


def confirm(session, protocol, condition_ids, statement, output: Path):
    if session.evidence_mode not in ("experimental_photo_analysis", "experimental_compiled_photo_analysis") or not condition_ids or len(condition_ids) != len(set(condition_ids)):
        raise ValueError("Explicit distinct manual conditions are required")
    if output.exists():
        raise FileExistsError(output)
    request = dict(kind="operator_confirmation", **session.stamp(), condition_ids=condition_ids, statement=statement)
    event = dict(id="manual." + uuid.uuid4().hex, **session.stamp(), kind="manual", origin="operator", statement=statement,
                 values={cid: "true" for cid in condition_ids})
    prepared = deepcopy(session)
    prepared.apply(event)
    output.mkdir(parents=True, exist_ok=False)
    plan = write_session(output, protocol, prepared, request)
    session.apply(event)
    seal(output, "success")
    return plan
