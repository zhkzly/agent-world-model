"""Content-addressed run state for the self-owned StateGraph control plane.

One ``RunState`` carries the full closure of a single generation/expansion run:
the immutable ``GenerationContext`` root, one budget lease, and one ``NodeSlice``
per pipeline stage.  State evolves only by appending a new immutable version, so
resume collapses to a single rule: a slice that is not ``committed`` is re-run.

This module intentionally owns no execution logic.  It defines the typed values
that cross the executor/node/router boundary; behaviour lives in ``node.py``,
``edge.py``, ``router.py`` and ``executor.py``.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, JsonValue, model_validator

from ..contracts.base import ArtifactRef, Identifier, NonEmptyStr, V2Contract

NodeStatus = Literal["pending", "running", "committed", "failed", "honest_stop"]

# The three lanes every node outcome collapses into (see stategraph-rewrite §2.4).
# ``design_defect`` is the only lane that authorises a feedback re-run; the other
# two never rewrite a design and never touch a frozen WorldSpec.
FindingLane = Literal["infra_retryable", "design_defect", "framework_diagnosis"]


class Finding(V2Contract):
    """One actionable signal produced by a node, consumed by the router.

    ``lane`` is the single authority for how the executor reacts.  ``code`` and
    ``field_path`` carry framework-safe diagnostic identity only; Agent-authored
    input values must never enter either (diagnostic-fidelity redline).
    """

    finding_id: Identifier
    source_node: Identifier
    lane: FindingLane
    code: Identifier
    field_path: NonEmptyStr | None = None
    summary: NonEmptyStr
    # Causal evidence for a back-jump; empty means "local correction only".
    rerun_target: Identifier | None = None

    @model_validator(mode="after")
    def _rerun_only_for_design_defect(self) -> Finding:
        if self.rerun_target is not None and self.lane != "design_defect":
            raise ValueError("only design_defect findings may request a rerun target")
        return self


class NodeSlice(V2Contract):
    """The per-node state slice: status, outputs, and cache identity.

    ``definition_digest`` folds the leaf source digest and model version, so a
    code change to a node invalidates only that node's cache (RISK-2 fix).
    ``input_fingerprint`` is the digest of the upstream outputs this node
    consumed; together they key the resume/reuse decision.  ``continuation``
    holds live agent-session state that cannot be rebuilt from the commit graph
    (former NodeContinuationStore/SemanticRepairSeedStore), kept as a field
    rather than a separate store.
    """

    node_id: Identifier
    status: NodeStatus = "pending"
    outputs: dict[Identifier, ArtifactRef] = Field(default_factory=dict)
    input_fingerprint: NonEmptyStr | None = None
    definition_digest: NonEmptyStr | None = None
    attempts: Annotated[int, Field(ge=0)] = 0
    continuation: dict[Identifier, JsonValue] = Field(default_factory=dict)
    failure_code: Identifier | None = None
    failure_summary: NonEmptyStr | None = None

    @model_validator(mode="after")
    def _terminal_shape(self) -> NodeSlice:
        if self.status == "committed" and not self.outputs:
            raise ValueError("committed slices must carry at least one output ref")
        if self.status in ("failed", "honest_stop") and self.failure_code is None:
            raise ValueError(f"{self.status} slices require a failure_code")
        if self.status in ("pending", "running", "committed") and self.failure_code is not None:
            raise ValueError(f"{self.status} slices cannot carry a failure_code")
        return self

    @property
    def is_committed(self) -> bool:
        return self.status == "committed"

    @property
    def is_terminal(self) -> bool:
        """Whether this slice needs no further work (committed or honest stop)."""

        return self.status in ("committed", "honest_stop")


class RunState(V2Contract):
    """Immutable content-addressed snapshot of one run.

    generate and expand share this exact schema; expand differs only in
    ``scope_id`` and a seed node, then rejoins the same graph.
    """

    request_id: Identifier
    scope_id: Identifier
    context_ref: ArtifactRef
    lease_id: Identifier
    slices: dict[Identifier, NodeSlice] = Field(default_factory=dict)
    findings: tuple[Finding, ...] = ()

    @model_validator(mode="after")
    def _slice_keys_match(self) -> RunState:
        for key, sl in self.slices.items():
            if key != sl.node_id:
                raise ValueError(f"slice key {key!r} does not match node_id {sl.node_id!r}")
        if self.context_ref.artifact_type != "control.generation_context":
            raise ValueError("RunState.context_ref must be a GenerationContext artifact")
        return self

    def slice_for(self, node_id: str) -> NodeSlice:
        return self.slices.get(node_id, NodeSlice(node_id=node_id))

    def with_slice(self, updated: NodeSlice) -> RunState:
        """Return a new state with one slice replaced (append-only evolution)."""

        merged = dict(self.slices)
        merged[updated.node_id] = updated
        return self.model_copy(update={"slices": merged})

    def with_findings(self, new: tuple[Finding, ...]) -> RunState:
        return self.model_copy(update={"findings": self.findings + new})

    def open_findings_for(self, node_id: str) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.rerun_target == node_id)
