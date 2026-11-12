"""Task GT normalization and provenance checks, without model or runtime state."""
import ast
import hashlib
import json
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


Text = Annotated[str, Field(min_length=1, pattern=r"\S")]
Identity = Annotated[str, Field(pattern=r"^[A-Za-z][A-Za-z0-9_.-]{0,99}$")]
Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def encoded(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Artifact(Strict):
    id: Identity
    path: Text
    sha256: Digest


class Source(Strict):
    id: Identity
    artifact_id: Identity
    locator: Text
    kind: Literal["official", "reference_instruction", "reference_verification", "reference_context"]
    text: Text
    text_sha256: Digest
    citation_id: str = ""
    source_url: str = ""


class ReferenceImage(Strict):
    id: Identity
    artifact_id: Identity
    source_ids: list[Identity] = Field(min_length=1)
    source_url: Text
    role: Literal["official_reference_not_scene"] = "official_reference_not_scene"


class Sources(Strict):
    schema_version: Literal["baseline-sources-v1"]
    source_selection: Literal["unconfirmed", "confirmed_by_user"]
    confirmation_statement: str = ""
    artifacts: list[Artifact] = Field(min_length=1)
    records: list[Source] = Field(min_length=1)
    images: list[ReferenceImage] = Field(default_factory=list)

    @model_validator(mode="after")
    def integrity(self):
        artifacts = unique(self.artifacts)
        sources = unique(self.records)
        unique(self.images)
        if self.source_selection == "confirmed_by_user" and not self.confirmation_statement.strip():
            raise ValueError("Source confirmation needs the user's statement")
        for source in self.records:
            if source.artifact_id not in artifacts:
                raise ValueError("Unknown source artifact: " + source.id)
            if digest(source.text.encode()) != source.text_sha256:
                raise ValueError("Source text hash mismatch: " + source.id)
        for image in self.images:
            if image.artifact_id not in artifacts or not set(image.source_ids) <= sources.keys():
                raise ValueError("Unknown image provenance: " + image.id)
        return self


class Object(Strict):
    id: Identity
    name: Text
    aliases: list[Text] = Field(default_factory=list)
    source_ids: list[Identity] = Field(min_length=1)


class Requirement(Strict):
    id: Identity
    kind: Literal["operation", "outcome", "specification", "material_selection", "applicability", "observation_boundary"]
    source_id: Identity
    quote: Text


class Condition(Strict):
    id: Identity
    statement: Text
    object_ids: list[Identity] = Field(min_length=1)
    requirement_ids: list[Identity] = Field(min_length=1)
    channel: Literal["vision", "manual", "unresolved"]
    scope: Literal["visible_state", "nonvisual_confirmation", "undetermined"]
    basis: Literal["direct_reference", "normalization_proposal"]
    standard_status: Literal["needs_visual_standard", "manual_definition", "unresolved"]
    definition: Text

    @model_validator(mode="after")
    def channels(self):
        expected = {"vision": ("visible_state", "needs_visual_standard"),
                    "manual": ("nonvisual_confirmation", "manual_definition"),
                    "unresolved": ("undetermined", "unresolved")}
        if (self.scope, self.standard_status) != expected[self.channel]:
            raise ValueError("Condition channel/scope/standard mismatch: " + self.id)
        return self


class Node(Strict):
    id: Identity
    instruction: Text
    object_ids: list[Identity] = Field(min_length=1)
    requirement_ids: list[Identity] = Field(min_length=1)
    depends_on: list[Identity] = Field(default_factory=list)
    precondition_ids: list[Identity] = Field(default_factory=list)
    completion_ids: list[Identity] = Field(min_length=1)


class ReviewItem(Strict):
    id: Identity
    targets: list[Identity] = Field(min_length=1)
    question: Text
    proposal: Text


class TaskDefinition(Strict):
    schema_version: Literal["baseline-task-v1"]
    id: Identity
    version: Text
    device_id: Identity
    title: Text
    scope: Text
    objects: list[Object] = Field(min_length=1)
    requirements: list[Requirement] = Field(min_length=1)
    conditions: list[Condition] = Field(min_length=1)
    nodes: list[Node] = Field(min_length=1)
    goal_condition_ids: list[Identity] = Field(min_length=1)
    policy_requirement_ids: list[Identity] = Field(default_factory=list)
    review_items: list[ReviewItem] = Field(default_factory=list)

    @model_validator(mode="after")
    def graph(self):
        objects, requirements, conditions, nodes = map(unique, (self.objects, self.requirements, self.conditions, self.nodes))
        unique(self.review_items)
        used_requirements = set(self.policy_requirement_ids)
        used_conditions = set()
        for row in self.conditions:
            require_refs(row.object_ids, objects, row.id)
            require_refs(row.requirement_ids, requirements, row.id)
            used_requirements.update(row.requirement_ids)
        for row in self.nodes:
            require_refs(row.object_ids, objects, row.id)
            require_refs(row.requirement_ids, requirements, row.id)
            require_refs(row.depends_on, nodes, row.id)
            require_refs(row.precondition_ids + row.completion_ids, conditions, row.id)
            used_requirements.update(row.requirement_ids)
            used_conditions.update(row.precondition_ids + row.completion_ids)
        require_refs(self.policy_requirement_ids, requirements, self.id)
        require_refs(self.goal_condition_ids, conditions, self.id)
        if used_requirements != requirements.keys():
            raise ValueError("Unmapped requirements: " + str(sorted(requirements.keys() - used_requirements)))
        if used_conditions != conditions.keys():
            raise ValueError("Every condition must belong to a node")
        for requirement in self.requirements:
            if requirement.kind in ("outcome", "specification") and not any(requirement.id in c.requirement_ids for c in self.conditions):
                raise ValueError("Requirement lacks a check: " + requirement.id)
            if requirement.kind == "operation" and not any(requirement.id in n.requirement_ids for n in self.nodes):
                raise ValueError("Operation lacks a node: " + requirement.id)
            if requirement.kind == "material_selection" and not any(requirement.id in n.requirement_ids for n in self.nodes):
                raise ValueError("Material selection lacks an instruction: " + requirement.id)
        pending = set(nodes)
        while pending:
            ready = {n for n in pending if not set(nodes[n].depends_on) & pending}
            if not ready:
                raise ValueError("Task dependency cycle")
            pending -= ready
        for row in self.review_items:
            require_refs(row.targets, objects.keys() | requirements.keys() | conditions.keys() | nodes.keys() | {self.id}, row.id)
        return self


def unique(rows):
    result = {row.id: row for row in rows}
    if len(result) != len(rows):
        raise ValueError("Duplicate identities")
    return result


def require_refs(values, available, owner):
    if len(values) != len(set(values)) or not set(values) <= set(available):
        raise ValueError("Duplicate/unknown references at " + owner)


def validate_mapping(sources: Sources, task: TaskDefinition):
    records = unique(sources.records)
    for obj in task.objects:
        require_refs(obj.source_ids, records, obj.id)
    for req in task.requirements:
        if req.source_id not in records or req.quote not in records[req.source_id].text:
            raise ValueError("Requirement quote is not in its source: " + req.id)
    for source in sources.records:
        if not any(req.source_id == source.id for req in task.requirements):
            raise ValueError("Source has no requirement mapping: " + source.id)


def extract_text(path: Path, locator: str) -> str:
    if locator.startswith("json:"):
        value = json.loads(path.read_bytes())
        for token in locator[5:].split("/")[1:]:
            token = token.replace("~1", "/").replace("~0", "~")
            value = value[int(token)] if isinstance(value, list) else value[token]
    elif locator.startswith("python:"):
        name = locator[7:]
        matches = [node.value.value for node in ast.parse(path.read_text()).body
                   if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets)
                   and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)]
        if len(matches) != 1:
            raise ValueError("Missing/ambiguous source constant: " + name)
        value = matches[0]
    else:
        raise ValueError("Unsupported source locator: " + locator)
    if not isinstance(value, str):
        raise ValueError("Source locator must select text")
    return value


def verify_sources(sources: Sources, root: Path):
    root = root.resolve()
    paths = {}
    for artifact in sources.artifacts:
        path = (root / artifact.path).resolve()
        path.relative_to(root)
        if digest(path.read_bytes()) != artifact.sha256:
            raise ValueError("Reference artifact changed: " + artifact.id)
        paths[artifact.id] = path
    for source in sources.records:
        if extract_text(paths[source.artifact_id], source.locator) != source.text:
            raise ValueError("Source excerpt differs from reference: " + source.id)


def snapshot(selection_path: Path, root: Path, output: Path):
    selection = json.loads(selection_path.read_bytes())
    root = root.resolve()
    paths = {}
    for artifact in selection["artifacts"]:
        path = (root / artifact["path"]).resolve()
        path.relative_to(root)
        sha = digest(path.read_bytes())
        if artifact.get("sha256", sha) != sha:
            raise ValueError("Selected artifact hash mismatch: " + artifact["id"])
        artifact["sha256"] = sha
        paths[artifact["id"]] = path
    for source in selection["records"]:
        source["text"] = extract_text(paths[source["artifact_id"]], source["locator"])
        source["text_sha256"] = digest(source["text"].encode())
    value = Sources.model_validate(selection)
    verify_sources(value, root)
    with output.open("xb") as stream:
        stream.write(encoded(value.model_dump()))


class Decision(Strict):
    id: Identity
    user_statement: Text
    resolution: Text


class Delegation(Strict):
    reviewer: Literal["assistant_under_user_delegation"]
    authorization_quote: Text
    decision_ids: list[Identity] = Field(min_length=1)
    scope: Literal["state_validation"]


class HumanReview(Strict):
    schema_version: Literal["baseline-human-review-v1"]
    reviewed_task_sha256: Digest
    task_sha256: Digest
    sources_sha256: Digest
    decisions: list[Decision] = Field(min_length=1)
    delegation: Delegation | None = None

    def check(self, sources, task):
        unique(self.decisions)
        if self.task_sha256 != digest(encoded(task.model_dump())) or self.sources_sha256 != digest(encoded(sources.model_dump())):
            raise ValueError("Human review does not match current task/sources")
        if {d.id for d in self.decisions} & {r.id for r in task.review_items}:
            raise ValueError("Review item cannot be both resolved and pending")
        if self.delegation:
            require_refs(self.delegation.decision_ids, {d.id for d in self.decisions}, "delegation")
            for row in self.decisions:
                if row.id in self.delegation.decision_ids and row.user_statement != self.delegation.authorization_quote:
                    raise ValueError("Delegated decision must retain the authorization, not invent a user choice")


def review_report(sources: Sources, task: TaskDefinition, human=None):
    result = dict(schema_version="baseline-gt-review-v1", status="pending_human_review",
                source_selection=sources.source_selection,
                task_sha256=digest(encoded(task.model_dump())),
                sources_sha256=digest(encoded(sources.model_dump())),
                items=[row.model_dump() for row in task.review_items],
                observation_standards="not_implemented_in_normalization",
                scene_labels="not_provided", spatial_labels="not_provided",
                automatic_compiler_input=False)
    if human:
        human.check(sources, task)
        result.update(resolved_items=[d.id for d in human.decisions], reviewed_task_sha256=human.reviewed_task_sha256)
        if human.delegation and not task.review_items and sources.source_selection == "confirmed_by_user":
            if any(c.channel == "unresolved" for c in task.conditions):
                raise ValueError("Unresolved channels cannot enter state validation")
            result.update(status="approved_for_state_validation", reviewer=human.delegation.reviewer,
                          validation_scope="controlled_facts_only")
    return result


def normalize(sources_path: Path, mapping_path: Path, output: Path, review_decisions_path: Path | None = None):
    sources = Sources.model_validate_json(sources_path.read_bytes())
    task = TaskDefinition.model_validate_json(mapping_path.read_bytes())
    validate_mapping(sources, task)
    human = HumanReview.model_validate_json(review_decisions_path.read_bytes()) if review_decisions_path else None
    report = review_report(sources, task, human)
    # Exclusive directory creation prevents a new run from rewriting reviewed evidence.
    output.mkdir(parents=True, exist_ok=False)
    files = {"sources.json": encoded(sources.model_dump()), "task.json": encoded(task.model_dump()),
             "review.json": encoded(report),
             "REVIEW.md": render_review(sources, task).encode()}
    if human:
        files["human-review.json"] = encoded(human.model_dump(exclude_none=True))
    for name, raw in files.items():
        (output / name).write_bytes(raw)
    (output / "manifest.json").write_bytes(encoded(dict(schema_version="baseline-gt-bundle-v1",
        files={name: digest(raw) for name, raw in files.items()})))


def load_bundle(folder: Path):
    manifest = json.loads((folder / "manifest.json").read_bytes())
    expected = {"sources.json", "task.json", "review.json", "REVIEW.md"}
    if not isinstance(manifest, dict) or manifest.get("schema_version") != "baseline-gt-bundle-v1" or set(manifest.get("files", {})) not in (expected, expected | {"human-review.json"}):
        raise ValueError("Invalid bundle manifest")
    for name, sha in manifest["files"].items():
        if digest((folder / name).read_bytes()) != sha:
            raise ValueError("Bundle file changed: " + name)
    sources = Sources.model_validate_json((folder / "sources.json").read_bytes())
    task = TaskDefinition.model_validate_json((folder / "task.json").read_bytes())
    validate_mapping(sources, task)
    human = HumanReview.model_validate_json((folder / "human-review.json").read_bytes()) if "human-review.json" in manifest["files"] else None
    if json.loads((folder / "review.json").read_bytes()) != review_report(sources, task, human):
        raise ValueError("Review identity/status mismatch")
    if (folder / "REVIEW.md").read_text() != render_review(sources, task):
        raise ValueError("Review document differs from task")
    return sources, task


def render_review(sources, task):
    records = unique(sources.records)
    notice = ("来源已确认不等于本次细分和证据渠道已审核。当前包仅为待审核任务 GT，不是可执行视觉标准或现场标签。" if task.review_items else
              "本任务已无待处理方案审核项；批准范围以 review.json 为准。任务定义不等于可执行视觉标准、现场标签或实物验证结果。")
    lines = ["# " + task.title + "：GT 规范化审核", "", notice, "",
             "## 操作节点", ""]
    for node in task.nodes:
        lines += [f"- **{node.id}**：{node.instruction}", f"  - 依赖：{', '.join(node.depends_on) or '无'}；完成条件：{', '.join(node.completion_ids)}"]
    lines += ["", "## 条件及来源", ""]
    requirements = unique(task.requirements)
    for condition in task.conditions:
        lines += [f"### {condition.id}：{condition.statement}", "",
                  f"渠道：`{condition.channel}`；定义状态：`{condition.standard_status}`；依据：`{condition.basis}`。", "", condition.definition, ""]
        for identity in condition.requirement_ids:
            req = requirements[identity]
            lines += [f"- [{req.id}] {req.quote}（{records[req.source_id].kind} / {req.source_id}）"]
        lines.append("")
    lines += ["## 逐项来源覆盖", ""]
    for req in task.requirements:
        mapped = [r.id for r in [*task.nodes, *task.conditions] if req.id in r.requirement_ids]
        if req.id in task.policy_requirement_ids:
            mapped.append("任务适用范围/观察边界")
        lines.append(f"- {req.id}：{req.quote} → {', '.join(mapped)}")
    lines += ["", "## 请审核" if task.review_items else "## 审核范围", ""]
    if not task.review_items:
        lines += ["方案结论见关联审核记录；批准范围以 review.json 为准。当前仅用于给定事实后的状态与调度验证，不证明真实感知或实物结果。", ""]
    for item in task.review_items:
        lines += [f"### {item.id}", "", item.question, "", "当前提案：" + item.proposal, ""]
    return "\n".join(lines)
