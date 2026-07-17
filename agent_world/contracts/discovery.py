"""Non-blocking Discovery Lane and Expansion Inbox artifacts."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, model_validator

from .base import ArtifactRef, ContentHash, Identifier, NonEmptyStr, V2Contract
from .jobs import Budget, PermissionScope


class DiscoveryRunSpec(V2Contract):
    discovery_run_id: Identifier
    origin_job_ref: ArtifactRef
    request_ref: ArtifactRef
    source_kinds: Annotated[tuple[Identifier, ...], Field(min_length=1)]
    agent_profile_ref: ArtifactRef
    budget: Budget
    permissions: PermissionScope
    priority: Literal["low", "normal"] = "low"
    seed: Annotated[int, Field(ge=0)]


class ExpansionClue(V2Contract):
    clue_id: Identifier
    origin_run_ref: ArtifactRef
    evidence_refs: Annotated[tuple[ArtifactRef, ...], Field(min_length=1)]
    hypothesis: NonEmptyStr
    tool_or_workflow_surface: tuple[NonEmptyStr, ...] = ()
    coverage_dimensions: Annotated[tuple[Identifier, ...], Field(min_length=1)]
    scope_relation: Literal["in_scope", "adjacent", "new_domain", "uncertain"]
    feasibility: Literal["supported", "plausible", "uncertain", "blocked"]
    risk: Literal["low", "medium", "high", "critical"]
    unresolved_questions: tuple[NonEmptyStr, ...] = ()
    dedup_fingerprint: ContentHash


class DiscoveryAdmissionDecision(V2Contract):
    decision_id: Identifier
    clue_ref: ArtifactRef
    classification: Literal["hard_correction", "in_scope_extension", "expansion", "reject"]
    destination: Literal[
        "quarantine_recommendation",
        "current_research",
        "expansion_inbox",
        "drop",
    ]
    rationale: NonEmptyStr
    decided_against_baseline_ref: ArtifactRef | None = None
    challenged_claim_ids: tuple[Identifier, ...] = ()

    @model_validator(mode="after")
    def validate_destination(self) -> DiscoveryAdmissionDecision:
        required = {
            "hard_correction": "quarantine_recommendation",
            "in_scope_extension": "current_research",
            "expansion": "expansion_inbox",
            "reject": "drop",
        }
        if self.destination != required[self.classification]:
            raise ValueError("destination must match discovery classification")
        if self.classification == "hard_correction" and not self.challenged_claim_ids:
            raise ValueError("hard_correction requires at least one challenged claim")
        if self.classification != "hard_correction" and self.challenged_claim_ids:
            raise ValueError("challenged_claim_ids are only valid for hard_correction")
        return self


class DiscoveryQuarantineRecommendation(V2Contract):
    """Non-routable semantic advice about evidence that deserves quarantine review.

    This is intentionally not a ``Finding``: it has no workflow owner, release
    block, repair action, invalidation target, budget, or jump authority.  A
    framework policy must independently validate and promote it before any
    control-plane consequence is possible.
    """

    recommendation_id: Identifier
    clue_ref: ArtifactRef
    world_spec_ref: ArtifactRef
    challenged_claim_ids: Annotated[tuple[Identifier, ...], Field(min_length=1)]
    evidence_refs: Annotated[tuple[ArtifactRef, ...], Field(min_length=1)]
    risk: Literal["low", "medium", "high", "critical"]
    rationale: NonEmptyStr


class QuarantineReviewDecision(V2Contract):
    """Framework decision compiled from a non-routable Discovery recommendation.

    The decision is deliberately separate from the Agent-authored semantic
    recommendation.  Only the ``framework`` producer may persist this contract;
    a confirmed decision can then be compiled into a normal ``Finding`` by the
    Controller-owned quarantine policy.
    """

    review_id: Identifier
    recommendation_ref: ArtifactRef
    baseline_ref: ArtifactRef
    outcome: Literal["confirmed", "dismissed"]
    reason_code: Literal[
        "verified_hard_correction",
        "admission_binding_mismatch",
        "baseline_binding_mismatch",
        "claim_not_hard_supported",
        "evidence_binding_mismatch",
        "evidence_not_independently_retrieved",
        "no_new_evidence",
    ]
    challenged_claim_ids: tuple[Identifier, ...] = ()
    validated_evidence_refs: tuple[ArtifactRef, ...] = ()

    @model_validator(mode="after")
    def validate_outcome(self) -> QuarantineReviewDecision:
        confirmed = self.outcome == "confirmed"
        if confirmed != (self.reason_code == "verified_hard_correction"):
            raise ValueError("only verified_hard_correction can confirm quarantine")
        if confirmed and not self.challenged_claim_ids:
            raise ValueError("confirmed quarantine requires challenged claims")
        if confirmed and not self.validated_evidence_refs:
            raise ValueError("confirmed quarantine requires validated evidence")
        return self


class DesignBaselineCheckpoint(V2Contract):
    checkpoint_id: Identifier
    origin_job_ref: ArtifactRef
    created_at: AwareDatetime
    request_ref: ArtifactRef
    evidence_graph_ref: ArtifactRef
    coverage_map_ref: ArtifactRef
    world_spec_ref: ArtifactRef
    scope_fingerprint: ContentHash


class ExpansionInboxSnapshot(V2Contract):
    snapshot_id: Identifier
    created_at: AwareDatetime
    clue_refs: tuple[ArtifactRef, ...] = ()
    coverage_gap_refs: tuple[ArtifactRef, ...] = ()
    admission_decision_refs: tuple[ArtifactRef, ...] = ()
    source_baseline_refs: tuple[ArtifactRef, ...] = ()


__all__ = [
    "DesignBaselineCheckpoint",
    "DiscoveryAdmissionDecision",
    "DiscoveryQuarantineRecommendation",
    "DiscoveryRunSpec",
    "ExpansionClue",
    "ExpansionInboxSnapshot",
    "QuarantineReviewDecision",
]
