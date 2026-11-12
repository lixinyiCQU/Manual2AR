"""Task-to-presentation bindings; rendering never changes evidence or progress."""
from pathlib import Path

from pydantic import Field

from .gt import Digest, Identity, Strict, digest, encoded


class Presentation(Strict):
    node_id: Identity
    action_id: Identity
    presentation_id: Identity


class Bindings(Strict):
    task_sha256: Digest
    resources: dict[str, Digest] = Field(min_length=1)
    presentations: list[Presentation] = Field(min_length=1)

    def check(self, task, root: Path, actions, library):
        if self.task_sha256 != digest(encoded(task.model_dump())):
            raise ValueError("AR bindings belong to another task revision")
        if len(self.presentations) != len(task.nodes) or {p.node_id for p in self.presentations} != {n.id for n in task.nodes}:
            raise ValueError("AR bindings must cover exactly the task nodes")
        if len({p.action_id for p in self.presentations}) != len(self.presentations):
            raise ValueError("Duplicate AR action binding")
        for name, sha in self.resources.items():
            path = (root / name).resolve()
            path.relative_to(root.resolve())
            if digest(path.read_bytes()) != sha:
                raise ValueError("AR reference resource changed")
        for p in self.presentations:
            if p.action_id not in actions or p.presentation_id not in library.presentations:
                raise ValueError("Unknown AR action or presentation")
            if actions[p.action_id].get("visual_guidance", {}).get("presentation_id") != p.presentation_id:
                raise ValueError("AR action/presentation mismatch")

    def execution(self, session):
        plan = session.plan()
        by_node = {p.node_id: p for p in self.presentations}
        needed = plan["needed_node_ids"]
        current = by_node.get(plan["node_id"], by_node[needed[-1]] if needed else self.presentations[-1])
        # The existing renderer uses operate/check/observe/complete; retain the exact baseline mode too.
        mode = {"operate": "operate", "request_view": "observe", "ask_manual": "check", "complete": "complete"}.get(plan["mode"], "observe")
        pending = [dict(id=cid, statement=session.conditions[cid].statement) for cid in plan["condition_ids"]
                   if session.conditions[cid].channel == "manual"]
        return dict(contract="baseline-ar-v1", **session.stamp(), baseline_mode=plan["mode"],
                    state_id=current.node_id, action_id=current.action_id, mode=mode, reason=plan["reason"],
                    complete=plan["mode"] == "complete", needs_assessment=session.last_frame == 0,
                    prerequisite_only=session.target_node_ids is not None and current.node_id not in session.target_node_ids,
                    completed_state_ids=[n for n in needed if n in plan["completed_node_ids"]],
                    remaining_state_ids=[n for n in needed if n not in plan["completed_node_ids"]],
                    target_node_ids=plan["target_node_ids"], needed_node_ids=needed,
                    guidance_allowed=plan["mode"] == "operate", guidance_policy=session.guidance_policy,
                    steps=[dict(node_id=n, action_id=by_node[n].action_id, instruction=session.nodes[n].instruction,
                                status=plan["node_states"][n], is_target=session.target_node_ids is None or n in session.target_node_ids,
                                prerequisite_only=session.target_node_ids is not None and n not in session.target_node_ids,
                                current=n == plan["node_id"], index=i + 1, total=len(needed)) for i,n in enumerate(needed)],
                    manual_conditions=pending, condition_ids=plan["condition_ids"], scope=session.evidence_mode)
