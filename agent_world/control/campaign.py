"""Framework-owned durable state for resumable Expansion campaigns."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, model_validator

from agent_world.contracts import ArtifactRef, Identifier, V2Contract


class CampaignIterationRecord(V2Contract):
    """One ask batch committed before work and completed before policy.tell."""

    iteration_id: Identifier
    campaign_ref: ArtifactRef
    number: Annotated[int, Field(ge=0)]
    status: Literal["planned", "leased", "evaluated", "told"]
    policy_before_ref: ArtifactRef
    intent_refs: Annotated[tuple[ArtifactRef, ...], Field(min_length=1)]
    lease_refs: tuple[ArtifactRef, ...] = ()
    outcome_refs: tuple[ArtifactRef, ...] = ()
    policy_after_ref: ArtifactRef | None = None

    @model_validator(mode="after")
    def validate_phase(self) -> CampaignIterationRecord:
        for label, refs in (
            ("intent_refs", self.intent_refs),
            ("lease_refs", self.lease_refs),
            ("outcome_refs", self.outcome_refs),
        ):
            revisions = [item.revision_id for item in refs]
            if len(set(revisions)) != len(revisions):
                raise ValueError(f"{label} must not contain duplicate revisions")
        if self.status == "planned":
            if self.lease_refs or self.outcome_refs or self.policy_after_ref is not None:
                raise ValueError("planned iteration contains only the committed intent batch")
        elif self.status == "leased":
            if self.outcome_refs or self.policy_after_ref is not None:
                raise ValueError("leased iteration cannot contain outcomes or policy_after_ref")
        else:
            if len(self.outcome_refs) != len(self.intent_refs):
                raise ValueError("evaluated iteration requires exactly one outcome per intent")
            if self.status == "evaluated" and self.policy_after_ref is not None:
                raise ValueError("evaluated iteration cannot contain policy_after_ref")
            if self.status == "told" and self.policy_after_ref is None:
                raise ValueError("told iteration requires policy_after_ref")
        return self


class ExpansionCandidateAttempt(V2Contract):
    """Framework binding for one campaign intent and its real candidate execution."""

    attempt_id: Identifier
    campaign_ref: ArtifactRef
    iteration_number: Annotated[int, Field(ge=0)]
    intent_ref: ArtifactRef
    lease_ref: ArtifactRef | None = None
    job_ref: ArtifactRef | None = None
    reservation_ref: ArtifactRef | None = None
    latest_run_snapshot_ref: ArtifactRef | None = None
    status: Literal[
        "admission_pending",
        "admission_rejected",
        "leased",
        "running",
        "released",
        "failed",
        "needs_human",
        "budget_exhausted",
        "infrastructure_error",
    ]
    outcome_ref: ArtifactRef | None = None

    @model_validator(mode="after")
    def validate_attempt(self) -> ExpansionCandidateAttempt:
        if self.status in {"admission_pending", "admission_rejected"}:
            if self.lease_ref is not None or self.job_ref is not None:
                raise ValueError("pre-admission/rejected attempts cannot reserve work")
        elif self.lease_ref is None:
            raise ValueError("admitted candidate attempts require a budget lease")
        terminal = self.status in {
            "admission_rejected",
            "released",
            "failed",
            "needs_human",
            "budget_exhausted",
            "infrastructure_error",
        }
        if terminal != (self.outcome_ref is not None):
            raise ValueError("terminal candidate attempts require exactly one outcome_ref")
        return self


class SourceIntakeRecord(V2Contract):
    """Durable pre-Policy Source phase for one Expansion Campaign."""

    intake_id: Identifier
    campaign_ref: ArtifactRef
    revision: Annotated[int, Field(ge=1)]
    status: Literal["planned", "leased", "completed"]
    source_catalog_ref: ArtifactRef
    source_request_refs: Annotated[tuple[ArtifactRef, ...], Field(min_length=1)]
    source_lease_refs: tuple[ArtifactRef, ...] = ()
    source_result_refs: tuple[ArtifactRef, ...] = ()
    clue_snapshot_ref: ArtifactRef | None = None
    context_ref: ArtifactRef | None = None

    @model_validator(mode="after")
    def validate_phase(self) -> SourceIntakeRecord:
        for label, refs in (
            ("source_request_refs", self.source_request_refs),
            ("source_lease_refs", self.source_lease_refs),
            ("source_result_refs", self.source_result_refs),
        ):
            if len({item.revision_id for item in refs}) != len(refs):
                raise ValueError(f"{label} must not contain duplicate revisions")
        count = len(self.source_request_refs)
        if self.status == "planned":
            if (
                self.source_lease_refs
                or self.source_result_refs
                or self.clue_snapshot_ref is not None
                or self.context_ref is not None
            ):
                raise ValueError("planned Source intake contains only frozen requests")
        elif self.status == "leased":
            if len(self.source_lease_refs) != count:
                raise ValueError("leased Source intake requires one lease per request")
            if (
                self.source_result_refs
                or self.clue_snapshot_ref is not None
                or self.context_ref is not None
            ):
                raise ValueError("leased Source intake cannot contain terminal artifacts")
        else:
            if len(self.source_lease_refs) != count or len(self.source_result_refs) != count:
                raise ValueError(
                    "completed Source intake requires one lease and result per request"
                )
            if self.clue_snapshot_ref is None or self.context_ref is None:
                raise ValueError("completed Source intake requires frozen clue/context artifacts")
        return self


class CampaignRunCheckpoint(V2Contract):
    """Framework state kept separate from replaceable policy-private state."""

    checkpoint_id: Identifier
    campaign_ref: ArtifactRef
    revision: Annotated[int, Field(ge=1)]
    started_at: AwareDatetime
    deadline_at: AwareDatetime
    next_iteration: Annotated[int, Field(ge=0)] = 0
    status: Literal[
        "running",
        "completed",
        "needs_human",
        "budget_exhausted",
        "infrastructure_error",
    ]
    updated_at: AwareDatetime
    policy_checkpoint_ref: ArtifactRef
    phase: Literal["source_intake", "candidate_loop"]
    source_catalog_ref: ArtifactRef
    source_intake_ref: ArtifactRef
    source_request_refs: Annotated[tuple[ArtifactRef, ...], Field(min_length=1)]
    source_lease_refs: tuple[ArtifactRef, ...] = ()
    source_result_refs: tuple[ArtifactRef, ...] = ()
    clue_snapshot_ref: ArtifactRef | None = None
    context_ref: ArtifactRef | None = None
    completed_iteration_refs: tuple[ArtifactRef, ...] = ()
    active_iteration_ref: ArtifactRef | None = None
    lease_refs: tuple[ArtifactRef, ...] = ()
    outcome_refs: tuple[ArtifactRef, ...] = ()
    released_package_refs: tuple[ArtifactRef, ...] = ()
    consecutive_infrastructure_failures: Annotated[int, Field(ge=0)] = 0
    stop_reason: Literal[
        "iteration_limit",
        "no_release_progress",
        "budget_exhausted",
        "no_admissible_operator",
        "completed_requested_iterations",
        "needs_human",
        "infrastructure_error",
    ] | None = None

    @model_validator(mode="after")
    def validate_state(self) -> CampaignRunCheckpoint:
        if self.status != "running" and self.active_iteration_ref is not None:
            raise ValueError("terminal campaign checkpoint cannot retain an active iteration")
        if self.deadline_at <= self.started_at:
            raise ValueError("campaign deadline must be after its start")
        if self.updated_at < self.started_at:
            raise ValueError("checkpoint update cannot precede campaign start")
        if (self.status == "running") != (self.stop_reason is None):
            raise ValueError("only terminal campaign checkpoints require stop_reason")
        if self.phase == "source_intake":
            if self.active_iteration_ref is not None or self.completed_iteration_refs:
                raise ValueError("Source intake cannot contain candidate iterations")
            if self.outcome_refs or self.released_package_refs:
                raise ValueError("Source intake cannot contain candidate outcomes/releases")
            if (
                self.source_result_refs
                or self.clue_snapshot_ref is not None
                or self.context_ref is not None
            ):
                raise ValueError(
                    "Source-intake checkpoint cannot expose an unfrozen Policy context"
                )
            if self.source_lease_refs and len(self.source_lease_refs) != len(
                self.source_request_refs
            ):
                raise ValueError("Source-intake leases must be empty or complete")
        else:
            if len(self.source_lease_refs) != len(self.source_request_refs):
                raise ValueError("candidate_loop requires one terminal Source lease per request")
            if len(self.source_result_refs) != len(self.source_request_refs):
                raise ValueError("candidate_loop requires one Source result per request")
            if self.clue_snapshot_ref is None or self.context_ref is None:
                raise ValueError("candidate_loop requires a frozen Source snapshot and context")
        if not set(self.source_lease_refs) <= set(self.lease_refs):
            raise ValueError("source_lease_refs must be included in Campaign lease_refs")
        for label, refs in (
            ("source_request_refs", self.source_request_refs),
            ("source_lease_refs", self.source_lease_refs),
            ("source_result_refs", self.source_result_refs),
            ("completed_iteration_refs", self.completed_iteration_refs),
            ("lease_refs", self.lease_refs),
            ("outcome_refs", self.outcome_refs),
            ("released_package_refs", self.released_package_refs),
        ):
            revisions = [item.revision_id for item in refs]
            if len(set(revisions)) != len(revisions):
                raise ValueError(f"{label} must not contain duplicate revisions")
        return self


__all__ = [
    "CampaignIterationRecord",
    "CampaignRunCheckpoint",
    "ExpansionCandidateAttempt",
    "SourceIntakeRecord",
]
