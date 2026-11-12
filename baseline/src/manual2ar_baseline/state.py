"""Deterministic assembly-task scheduling over controlled facts, not model verdicts."""
from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, TypeAdapter, model_validator

from .gt import Digest, Identity, Strict, TaskDefinition, Text, digest, encoded, load_bundle


Truth = Literal["true", "false", "unknown"]


class Envelope(Strict):
    id: Identity
    session_id: Identity
    task_sha256: Digest
    epoch: int = Field(ge=0)
    revision: int = Field(ge=0)


class Reading(Strict):
    value: Truth
    reason: Literal["observed", "occluded", "out_of_frame", "insufficient_detail", "unresolved_identity"]

    @model_validator(mode="after")
    def observability(self):
        if (self.value == "unknown") == (self.reason == "observed"):
            raise ValueError("Unknown requires an observation limit; true/false require observed evidence")
        return self


class Observation(Envelope):
    kind: Literal["observation"]
    origin: Literal["controlled_annotation", "vlm_findings"]
    frame_id: int = Field(ge=1)
    source_sha256: Digest
    values: dict[Identity, Reading] = Field(min_length=1)


class ManualConfirmation(Envelope):
    kind: Literal["manual"]
    origin: Literal["controlled_operator", "operator"]
    statement: Text
    values: dict[Identity, Literal["true", "false"]] = Field(min_length=1)


class Claim(Envelope):
    kind: Literal["claim"]
    node_id: Identity
    quote: Text
    completed: bool


class ContextChange(Envelope):
    kind: Literal["context_change"]
    context_id: Identity
    reason: Text


class Invalidation(Envelope):
    kind: Literal["invalidate"]
    condition_ids: list[Identity] = Field(min_length=1)
    reason: Text


Event = TypeAdapter(Annotated[Observation | ManualConfirmation | Claim | ContextChange | Invalidation,
                              Field(discriminator="kind")])


@dataclass(frozen=True)
class Fact:
    value: Truth = "unknown"
    evidence_id: str | None = None
    retained_on: str | None = None


class Session:
    """Single offline session. An invalid event changes neither facts nor revision."""

    def __init__(self, task: TaskDefinition, session_id: str, intent: str, *, evidence_mode="controlled_facts_only",
                 target_node_ids=None, guidance_policy="strict"):
        self.task = TaskDefinition.model_validate(task.model_dump())
        if self.task.review_items or any(c.channel == "unresolved" for c in self.task.conditions):
            raise ValueError("Task still has unresolved review items/channels")
        self.task_sha = digest(encoded(self.task.model_dump()))
        self.id = TypeAdapter(Identity).validate_python(session_id)
        self.intent = TypeAdapter(Text).validate_python(intent)
        self.evidence_mode = TypeAdapter(Literal["controlled_facts_only", "experimental_photo_analysis", "experimental_compiled_photo_analysis"]).validate_python(evidence_mode)
        self.conditions = {c.id: c for c in self.task.conditions}
        self.nodes = {n.id: n for n in self.task.nodes}
        self.guidance_policy = TypeAdapter(Literal["strict", "scene_guided"]).validate_python(guidance_policy)
        if target_node_ids is not None:
            if (not target_node_ids or len(target_node_ids) != len(set(target_node_ids))
                    or not set(target_node_ids) <= self.nodes.keys()):
                raise ValueError("Target scope must contain unique known task nodes")
            self.target_node_ids = tuple(target_node_ids)
            self.goal_condition_ids = tuple(dict.fromkeys(c for identity in self.target_node_ids
                                                          for c in self.nodes[identity].completion_ids))
        else:
            self.target_node_ids = None
            self.goal_condition_ids = tuple(self.task.goal_condition_ids)
        self.owners = {c: {n.id for n in self.task.nodes if c in n.completion_ids} for c in self.conditions}
        self.dependencies = {n.id: set(n.depends_on) | set().union(*(self.owners[c] for c in n.precondition_ids))
                             for n in self.task.nodes}
        self.order = []
        pending = set(self.nodes)
        while pending:
            ready = [n.id for n in self.task.nodes if n.id in pending and not self.dependencies[n.id] & pending]
            if not ready:
                raise ValueError("Condition producers introduce a dependency cycle")
            self.order.extend(ready)
            pending -= set(ready)
        self.needed = set().union(*(self.owners[c] for c in self.goal_condition_ids))
        for node in reversed(self.order):
            if node in self.needed:
                self.needed.update(self.dependencies[node])
        self.facts = {c: Fact() for c in self.conditions}
        self.epoch = self.revision = self.last_frame = 0
        self.context_id = "initial"
        self.events = []
        self.claims = []
        self.event_ids = set()

    @classmethod
    def from_bundle(cls, folder: Path, session_id: str, intent: str, *, evidence_mode="controlled_facts_only",
                    target_node_ids=None, guidance_policy="strict"):
        _, task = load_bundle(folder)
        review = json.loads((folder / "review.json").read_bytes())
        if review["status"] != "approved_for_state_validation":
            raise ValueError("Bundle is not approved for state validation")
        return cls(task, session_id, intent, evidence_mode=evidence_mode, target_node_ids=target_node_ids,
                   guidance_policy=guidance_policy)

    def stamp(self):
        return dict(session_id=self.id, task_sha256=self.task_sha, epoch=self.epoch, revision=self.revision)

    def completed(self):
        result = {}
        for identity in self.order:
            node = self.nodes[identity]
            result[identity] = (all(result[d] for d in self.dependencies[identity]) and
                                all(self.facts[c].value == "true" for c in node.completion_ids))
        return result

    def affected(self, condition_ids):
        owners = set().union(*(self.owners[c] for c in condition_ids))
        downstream = set()
        for node in self.order:
            if self.dependencies[node] & (owners | downstream):
                downstream.add(node)
        return owners, downstream

    def expire(self, facts, condition_ids, *, own_manual=True):
        owners, downstream = self.affected(condition_ids)
        for cid in condition_ids:
            facts[cid] = Fact()
        for node in owners | downstream:
            for cid in self.nodes[node].completion_ids:
                if node in downstream or (own_manual and self.conditions[cid].channel == "manual"):
                    facts[cid] = Fact()

    def apply(self, raw):
        event = Event.validate_python(raw)
        if digest(encoded(self.task.model_dump())) != self.task_sha:
            raise ValueError("Session task definition changed")
        if (event.session_id, event.task_sha256, event.epoch, event.revision) != (self.id, self.task_sha, self.epoch, self.revision):
            raise ValueError("Stale or mismatched session/task/epoch/revision")
        if event.id in self.event_ids:
            raise ValueError("Event already consumed")
        if isinstance(event, (Observation, ManualConfirmation)):
            allowed = ("controlled_annotation", "controlled_operator") if self.evidence_mode == "controlled_facts_only" else ("vlm_findings", "operator")
            if event.origin not in allowed:
                raise ValueError("Cannot mix controlled evidence and photo-analysis evidence")
        facts = dict(self.facts)
        if isinstance(event, Observation):
            if event.frame_id <= self.last_frame:
                raise ValueError("Stale observation frame")
            if any(cid not in self.conditions or self.conditions[cid].channel != "vision" for cid in event.values):
                raise ValueError("Observation can only update declared visual conditions")
            completed = self.completed()
            invalidating = {cid for cid, row in event.values.items()
                            if row.value == "false" or self.facts[cid].value == "false" and row.value == "true"
                            or row.value == "unknown" and row.reason != "occluded"}
            invalid_owners, _ = self.affected(invalidating)
            updates = {}
            for cid, row in event.values.items():
                previous = self.facts[cid]
                retain = (row.value == "unknown" and row.reason == "occluded" and previous.value == "true"
                          and not self.owners[cid] & invalid_owners and any(completed[n] for n in self.owners[cid]))
                updates[cid] = Fact(previous.value, previous.evidence_id, event.id) if retain else Fact(row.value, event.id)
                if row.value == "unknown" and not retain and previous.value == "true":
                    invalidating.add(cid)
            self.expire(facts, invalidating)
            facts.update(updates)
        elif isinstance(event, ManualConfirmation):
            if any(cid not in self.conditions or self.conditions[cid].channel != "manual" for cid in event.values):
                raise ValueError("Manual confirmation cannot override visual conditions")
            completed = self.completed()
            for cid, value in event.values.items():
                for node_id in self.owners[cid] if value == "true" else []:
                    node = self.nodes[node_id]
                    required = node.precondition_ids + [c for c in node.completion_ids if self.conditions[c].channel == "vision"]
                    if not all(completed[d] for d in self.dependencies[node_id]) or any(self.facts[c].value != "true" for c in required):
                        raise ValueError("Required visual/prerequisite evidence must pass before positive manual confirmation")
            changed = {cid for cid, value in event.values.items()
                       if value == "false" or self.facts[cid].value == "false" and value == "true"}
            self.expire(facts, changed, own_manual=False)
            facts.update({cid: Fact(value, event.id) for cid, value in event.values.items()})
        elif isinstance(event, Claim):
            if event.node_id not in self.nodes or event.quote not in self.intent:
                raise ValueError("Claim must match a node and the actual user input")
        elif isinstance(event, ContextChange):
            if event.context_id == self.context_id:
                raise ValueError("Context change needs a new identity")
            facts = {c: Fact() for c in self.conditions}
        else:
            if len(event.condition_ids) != len(set(event.condition_ids)) or not set(event.condition_ids) <= self.conditions.keys():
                raise ValueError("Unknown/duplicate invalidation condition")
            self.expire(facts, event.condition_ids)
        # Commit only after the complete event has passed all gates.
        self.facts = facts
        if isinstance(event, Observation):
            self.last_frame = event.frame_id
        elif isinstance(event, Claim):
            self.claims.append(event.model_dump())
        elif isinstance(event, ContextChange):
            self.epoch += 1
            self.context_id = event.context_id
            self.last_frame = 0
        self.events.append(event.model_dump())
        self.event_ids.add(event.id)
        self.revision += 1
        return self.plan()

    def plan(self):
        completed = self.completed()
        conflicts = []
        for claim in self.claims:
            if claim["epoch"] != self.epoch:
                continue
            values = [self.facts[c].value for c in self.nodes[claim["node_id"]].completion_ids]
            if (claim["completed"] and "false" in values) or (not claim["completed"] and all(v == "true" for v in values)):
                conflicts.append(dict(node_id=claim["node_id"], quote=claim["quote"], claim_id=claim["id"]))
        statuses = {}
        for identity in self.order:
            node = self.nodes[identity]
            values = [self.facts[c].value for c in node.completion_ids]
            visual = [self.facts[c].value for c in node.completion_ids if self.conditions[c].channel == "vision"]
            statuses[identity] = ("verified" if completed[identity] else "blocked" if any(not completed[d] for d in self.dependencies[identity])
                                  else "not_completed" if "false" in values else "suspected_installed" if visual and all(v == "true" for v in visual)
                                  else "unknown")
        result = dict(scope=self.evidence_mode, **self.stamp(), context_id=self.context_id,
                      completed_node_ids=[n for n in self.order if completed[n]], node_states=statuses,
                      conditions={cid: asdict(fact) for cid, fact in self.facts.items()}, claim_conflicts=conflicts,
                      target_node_ids=list(self.target_node_ids) if self.target_node_ids is not None else None,
                      needed_node_ids=[n for n in self.order if n in self.needed], guidance_policy=self.guidance_policy)
        if all(self.facts[c].value == "true" for c in self.goal_condition_ids) and all(completed[n] for n in self.needed):
            return {**result, "mode": "complete", "node_id": None, "condition_ids": [], "reason": "本任务所定义的条件已满足；结论范围为本会话所采用的证据方法，不证明隐藏机械状态。"}
        for identity in self.order:
            if identity not in self.needed or completed[identity] or any(not completed[d] for d in self.dependencies[identity]):
                continue
            node = self.nodes[identity]
            if self.guidance_policy == "scene_guided":
                decision = self.scene_guidance(node)
                if decision:
                    return {**result, **decision, "node_id": identity}
            checks = node.precondition_ids + sorted(node.completion_ids, key=lambda c: self.conditions[c].channel == "manual")
            for cid in checks:
                value = self.facts[cid].value
                if value == "true":
                    continue
                mode = "operate" if value == "false" else "ask_manual" if self.conditions[cid].channel == "manual" else "request_view"
                reason = {"operate": "请完成或纠正这一项：", "ask_manual": "请对照官方要求逐项确认：", "request_view": "请拍摄或补充核验这一项，证据不足不代表未安装："}[mode]
                return {**result, "mode": mode, "node_id": identity, "condition_ids": [cid], "reason": reason + self.conditions[cid].statement}
        # Goal facts can also be external guards rather than a node's result.
        missing = [c for c in self.goal_condition_ids if self.facts[c].value != "true"]
        if missing:
            cid = missing[0]
            mode = "operate" if self.facts[cid].value == "false" else "ask_manual" if self.conditions[cid].channel == "manual" else "request_view"
            return {**result, "mode": mode, "node_id": None, "condition_ids": [cid], "reason": "任务目标条件尚未满足：" + self.conditions[cid].statement}
        return {**result, "mode": "unsupported", "node_id": None, "condition_ids": [], "reason": "任务依赖无法继续，请检查任务定义。"}

    def scene_guidance(self, node):
        """An unknown result can receive instructions, but cannot authorize completion."""
        for cid in node.precondition_ids:
            if self.facts[cid].value != "true":
                return dict(mode="request_view", condition_ids=[cid],
                            reason="开始此操作前，需要先核实前置条件：" + self.conditions[cid].statement)
        visual = [c for c in node.completion_ids if self.conditions[c].channel == "vision"]
        negative = [c for c in visual if self.facts[c].value == "false"]
        if negative:
            return dict(mode="operate", condition_ids=negative,
                        reason="当前操作尚有未满足的可见条件。请按官方指导执行：" + node.instruction)
        unknown = [c for c in visual if self.facts[c].value == "unknown"]
        if not unknown:
            return None
        # A verified prerequisite permits teaching the next action, not accepting its unknown result.
        if self.last_frame == 0 or not self.dependencies[node.id]:
            cid = unknown[0]
            return dict(mode="request_view", condition_ids=[cid],
                        reason="当前操作的现场证据尚不足，请补拍或核实：" + self.conditions[cid].statement)
        return dict(mode="operate", condition_ids=unknown,
                    reason="此操作的完成状态尚未确认，前置条件已满足。可按官方指导执行；若已安装，可直接核验：" + node.instruction)
