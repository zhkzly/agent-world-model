"""Closed authority boundary between framework events and executable decisions.

The Foundry deliberately separates two questions:

* what happened and whether it is mechanically decidable; and
* what workflow effect, if any, is authorized.

Agents never construct these records.  They may produce registered semantic
advisories, but only framework code can compile an advisory or a deterministic
failure into a :class:`ControlEvent`.  ``CodeRouter`` is then the only place
that derives a Finding owner, local repair capability, or Design revision mode.
Free text, Finding categories, and suggested repairs are never routing inputs.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import model_validator

from agent_world.contracts import ArtifactRef, Identifier, V2Contract

from .models import NodeKind


class ControlEventKind(StrEnum):
    """Closed framework classification for a failed or pending decision."""

    CONTRACT_FAILURE = "contract_failure"
    COMPONENT_FAILURE = "component_failure"
    BACKEND_RETRYABLE = "backend_retryable"
    PERMISSION_REQUIRED = "permission_required"
    BUDGET_EXHAUSTED = "budget_exhausted"
    INFRASTRUCTURE_FAILURE = "infrastructure_failure"
    RELEASE_POLICY_FAILURE = "release_policy_failure"
    SEMANTIC_DECISION_REQUIRED = "semantic_decision_required"


class SemanticQuestionKind(StrEnum):
    """The semantic questions that code cannot answer from closed contracts."""

    BUSINESS_MEANING = "business_meaning"
    REASONABLENESS = "reasonableness"
    EVIDENCE_CONFLICT = "evidence_conflict"
    TASK_DIFFICULTY = "task_difficulty"
    SCOPE_IDENTITY = "scope_identity"


class StructuredRepairMode(StrEnum):
    """Closed local correction modes; none grants backjump or release authority."""

    CONTRACT_CORRECTION = "contract_correction"
    BUILDER_PRECOMMIT_CORRECTION = "builder_precommit_correction"
    BACKEND_RETRY = "backend_retry"


class DesignRevisionMode(StrEnum):
    """Framework-selected Design repair scope consumed by EnvironmentDesigner."""

    ASSUMPTION_CLOSURE = "assumption_closure"
    EVIDENCE_RECONCILIATION = "evidence_reconciliation"
    FULL_SEMANTIC_REVISION = "full_semantic_revision"


class ControlEvent(V2Contract):
    """One framework-authored event before it acquires workflow effects."""

    event_id: Identifier
    kind: ControlEventKind
    node: NodeKind
    reason_code: Identifier
    subject_ref: ArtifactRef
    evidence_refs: tuple[ArtifactRef, ...] = ()
    issue_codes: tuple[Identifier, ...] = ()
    semantic_question: SemanticQuestionKind | None = None

    @model_validator(mode="after")
    def validate_event_shape(self) -> ControlEvent:
        semantic = self.kind is ControlEventKind.SEMANTIC_DECISION_REQUIRED
        if semantic != (self.semantic_question is not None):
            raise ValueError(
                "semantic decision events alone require one closed semantic question"
            )
        if len(set(self.evidence_refs)) != len(self.evidence_refs):
            raise ValueError("ControlEvent evidence refs must be unique")
        if len(set(self.issue_codes)) != len(self.issue_codes):
            raise ValueError("ControlEvent issue codes must be unique")
        return self


class DeterministicDisposition(V2Contract):
    """Code-owned result for an event that needs no semantic arbitration."""

    classification: Literal["deterministic"] = "deterministic"
    event_id: Identifier
    owner: Literal[
        "design",
        "verifier",
        "build",
        "judge_infrastructure",
        "permissions",
        "release_policy",
    ]
    repair_mode: StructuredRepairMode
    design_revision_mode: DesignRevisionMode | None = None
    local_only: bool = False


class AdvisoryWorkOrder(V2Contract):
    """A semantic question with no jump, budget, Gate, or release fields."""

    classification: Literal["semantic_advisory"] = "semantic_advisory"
    event_id: Identifier
    role: Literal["researcher", "environment-engineer", "challenger"]
    question: SemanticQuestionKind
    subject_ref: ArtifactRef
    evidence_refs: tuple[ArtifactRef, ...]


class CodeRouter:
    """Classify framework events without consulting free text or an LLM."""

    _NODE_OWNER = {
        "design": "design",
        "verifier": "verifier",
        "build": "build",
        "integration": "judge_infrastructure",
        "judge": "judge_infrastructure",
        "release": "release_policy",
        "request": "permissions",
        "discovery": "design",
    }
    _SEMANTIC_ROLE = {
        SemanticQuestionKind.BUSINESS_MEANING: "environment-engineer",
        SemanticQuestionKind.REASONABLENESS: "environment-engineer",
        SemanticQuestionKind.EVIDENCE_CONFLICT: "researcher",
        SemanticQuestionKind.TASK_DIFFICULTY: "challenger",
        SemanticQuestionKind.SCOPE_IDENTITY: "environment-engineer",
    }

    def classify(self, event: ControlEvent) -> DeterministicDisposition | AdvisoryWorkOrder:
        if event.kind is ControlEventKind.SEMANTIC_DECISION_REQUIRED:
            assert event.semantic_question is not None
            return AdvisoryWorkOrder(
                event_id=event.event_id,
                role=self._SEMANTIC_ROLE[event.semantic_question],
                question=event.semantic_question,
                subject_ref=event.subject_ref,
                evidence_refs=event.evidence_refs,
            )

        owner = self._owner(event)
        revision_mode: DesignRevisionMode | None = None
        if owner == "design":
            revision_mode = (
                DesignRevisionMode.ASSUMPTION_CLOSURE
                if event.issue_codes
                and set(event.issue_codes) <= {"unresolved_assumptions_forbidden"}
                else DesignRevisionMode.FULL_SEMANTIC_REVISION
            )
        repair_mode = (
            StructuredRepairMode.BACKEND_RETRY
            if event.kind is ControlEventKind.BACKEND_RETRYABLE
            else StructuredRepairMode.CONTRACT_CORRECTION
        )
        return DeterministicDisposition(
            event_id=event.event_id,
            owner=owner,
            repair_mode=repair_mode,
            design_revision_mode=revision_mode,
            local_only=False,
        )

    def classify_local_repair(
        self,
        event: ControlEvent,
        *,
        mode: StructuredRepairMode,
    ) -> DeterministicDisposition:
        """Authorize only a same-node correction; never a global route."""

        if event.kind is ControlEventKind.SEMANTIC_DECISION_REQUIRED:
            raise ValueError("semantic advisory work cannot become a local repair directly")
        expected_kind = (
            ControlEventKind.BACKEND_RETRYABLE
            if mode is StructuredRepairMode.BACKEND_RETRY
            else ControlEventKind.CONTRACT_FAILURE
        )
        if event.kind is not expected_kind:
            raise ValueError("structured repair mode is incompatible with ControlEvent kind")
        disposition = self.classify(event)
        if not isinstance(disposition, DeterministicDisposition):
            raise AssertionError("deterministic local event produced an advisory work order")
        if disposition.owner not in {"design", "verifier", "build", "judge_infrastructure"}:
            raise ValueError("local structured repair requires a component owner")
        return disposition.model_copy(update={"repair_mode": mode, "local_only": True})

    @classmethod
    def _owner(
        cls,
        event: ControlEvent,
    ) -> Literal[
        "design",
        "verifier",
        "build",
        "judge_infrastructure",
        "permissions",
        "release_policy",
    ]:
        if event.kind is ControlEventKind.PERMISSION_REQUIRED:
            return "permissions"
        if event.kind is ControlEventKind.INFRASTRUCTURE_FAILURE:
            return "judge_infrastructure"
        if event.kind is ControlEventKind.RELEASE_POLICY_FAILURE:
            return "release_policy"
        return cls._NODE_OWNER[event.node]  # type: ignore[return-value]


__all__ = [
    "AdvisoryWorkOrder",
    "CodeRouter",
    "ControlEvent",
    "ControlEventKind",
    "DesignRevisionMode",
    "DeterministicDisposition",
    "SemanticQuestionKind",
    "StructuredRepairMode",
]
