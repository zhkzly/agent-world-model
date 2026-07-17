"""Closed records for resumable Foundry jobs and repair decisions."""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, model_validator

from agent_world.contracts import (
    ArtifactRef,
    Budget,
    BudgetUsage,
    Identifier,
    NonEmptyStr,
    V2Contract,
)

NodeKind = Literal[
    "request",
    "discovery",
    "design",
    "verifier",
    "build",
    "integration",
    "judge",
    "release",
]
NodeStatus = Literal[
    "pending",
    "running",
    "passed",
    "failed",
    "invalidated",
    "needs_human",
    "budget_exhausted",
]


class NodeAttempt(V2Contract):
    attempt_id: Identifier
    node: NodeKind
    ordinal: Annotated[int, Field(ge=1)]
    status: NodeStatus
    started_at: AwareDatetime
    finished_at: AwareDatetime | None = None
    input_refs: tuple[ArtifactRef, ...] = ()
    output_refs: tuple[ArtifactRef, ...] = ()
    finding_refs: tuple[ArtifactRef, ...] = ()
    invalidated_by_refs: tuple[ArtifactRef, ...] = ()
    agent_profile_hash: str | None = None
    agent_session_id: str | None = None
    failure_code: Identifier | None = None
    failure_summary: str | None = None
    budget_usage: BudgetUsage = Field(default_factory=BudgetUsage)

    @model_validator(mode="after")
    def terminal_shape(self) -> NodeAttempt:
        terminal = self.status not in {"pending", "running"}
        if terminal != (self.finished_at is not None):
            raise ValueError("terminal node attempts require finished_at and active ones forbid it")
        if self.status == "passed" and not self.output_refs:
            raise ValueError("passed node attempts require output artifacts")
        if self.status == "invalidated" and not self.invalidated_by_refs:
            raise ValueError("invalidated attempts require invalidating artifacts")
        if self.failure_code is not None and self.status not in {
            "failed",
            "needs_human",
            "budget_exhausted",
        }:
            raise ValueError("failure_code is only valid for terminal failure states")
        return self


class RepairDirective(V2Contract):
    directive_id: Identifier
    finding_ref: ArtifactRef
    related_finding_refs: tuple[ArtifactRef, ...] = ()
    owner_node: Literal["design", "verifier", "build", "judge", "release", "human"]
    action: Literal[
        "continue_session",
        "new_revision",
        "retry_infrastructure",
        "request_permission",
        "reject",
    ]
    invalidates: tuple[NodeKind, ...]
    disclosure: Literal["public", "repair", "sealed_summary"]
    repair_summary: NonEmptyStr
    maximum_attempts: Annotated[int, Field(ge=0)]
    current_node: NodeKind | None = None
    owner_ref: ArtifactRef | None = None
    jump_distance: Annotated[int, Field(ge=0, le=2)] = 0
    causal_evidence_refs: tuple[ArtifactRef, ...] = ()
    blocking_claim_ids_before: tuple[Identifier, ...] = ()
    ledger_entry_id: Identifier | None = None
    decision_reason: NonEmptyStr = "framework failure taxonomy and Artifact ownership"

    @model_validator(mode="after")
    def validate_backjump(self) -> RepairDirective:
        if self.finding_ref in self.related_finding_refs:
            raise ValueError("primary Finding cannot be repeated as a related Finding")
        if len(set(self.related_finding_refs)) != len(self.related_finding_refs):
            raise ValueError("RepairDirective related Findings must be unique")
        if self.jump_distance == 1 and not self.causal_evidence_refs:
            raise ValueError("distance-1 RepairDirective requires causal evidence")
        if self.jump_distance >= 2 and self.action != "request_permission":
            raise ValueError("automatic distance-2 backjump is forbidden")
        return self


class RepairLedgerEntry(V2Contract):
    entry_id: Identifier
    finding_ref: ArtifactRef
    related_finding_refs: tuple[ArtifactRef, ...] = ()
    finding_fingerprint: str
    observed_subject_ref: ArtifactRef
    resolved_owner_ref: ArtifactRef | None = None
    current_node: NodeKind
    target_node: Literal["design", "verifier", "build", "judge", "release", "human"]
    action: Literal[
        "continue_session",
        "new_revision",
        "retry_infrastructure",
        "request_permission",
        "reject",
    ]
    jump_distance: Annotated[int, Field(ge=0, le=2)]
    causal_evidence_refs: tuple[ArtifactRef, ...] = ()
    blocking_claim_ids_before: tuple[Identifier, ...] = ()
    blocking_claim_ids_after: tuple[Identifier, ...] = ()
    validation_phase_before: Identifier | None = None
    validation_frontier_before: Annotated[int, Field(ge=0)] | None = None
    validation_phase_after: Identifier | None = None
    validation_frontier_after: Annotated[int, Field(ge=0)] | None = None
    invalidated_refs: tuple[ArtifactRef, ...] = ()
    retained_refs: tuple[ArtifactRef, ...] = ()
    session_strategy: Literal["continued", "fresh", "none"] = "none"
    progress_evidence: Literal[
        "none", "issue_set_changed", "validation_stage_advanced"
    ] = "none"
    outcome: Literal[
        "authorized",
        "progressed",
        "resolved",
        "no_progress",
        "escalated",
        "exhausted",
        "rejected",
    ] = "authorized"
    attempt_ordinal: Annotated[int, Field(ge=1)]
    started_at: AwareDatetime
    finished_at: AwareDatetime | None = None
    usage: BudgetUsage = Field(default_factory=BudgetUsage)

    @model_validator(mode="after")
    def validate_repair_entry(self) -> RepairLedgerEntry:
        if self.finding_ref in self.related_finding_refs:
            raise ValueError("primary Finding cannot be repeated as a related Finding")
        if len(set(self.related_finding_refs)) != len(self.related_finding_refs):
            raise ValueError("RepairLedger related Findings must be unique")
        if self.jump_distance == 1 and not self.causal_evidence_refs:
            raise ValueError("distance-1 repair requires causal evidence")
        terminal = self.outcome != "authorized"
        if terminal != (self.finished_at is not None):
            raise ValueError("terminal RepairLedgerEntry requires finished_at")
        before = set(self.blocking_claim_ids_before)
        after = set(self.blocking_claim_ids_after)
        if (self.validation_phase_before is None) != (
            self.validation_frontier_before is None
        ):
            raise ValueError("repair validation phase/frontier before must be provided together")
        if (self.validation_phase_after is None) != (self.validation_frontier_after is None):
            raise ValueError("repair validation phase/frontier after must be provided together")
        if self.progress_evidence == "validation_stage_advanced":
            # Legacy Designer validators still use the temporary framework
            # rank table.  Once either side opts into the shared frontier,
            # both sides must provide a strictly monotonic witness.
            frontier_present = (
                self.validation_frontier_before is not None
                or self.validation_frontier_after is not None
            )
            if frontier_present and (
                self.validation_frontier_before is None
                or self.validation_frontier_after is None
                or self.validation_frontier_after <= self.validation_frontier_before
            ):
                raise ValueError("stage-advanced repair requires a monotonic validation frontier")
        if self.progress_evidence == "issue_set_changed" and (
            not before or not after or before == after
        ):
            raise ValueError(
                "issue-set-changed repair requires two distinct non-empty blocker sets"
            )
        if self.outcome == "no_progress" and (not after or after < before):
            raise ValueError(
                "no-progress repair requires unresolved blockers without a strict reduction"
            )
        return self


class BudgetLease(V2Contract):
    """One child reservation within a parent vector budget.

    Wall time is a shared deadline rather than an additive resource. The
    reserved wall dimension limits the child itself, while the campaign ledger
    reports one framework-observed elapsed duration.
    """

    lease_id: Identifier
    owner_id: Identifier
    reserved: Budget
    status: Literal["active", "settled", "released"] = "active"
    observed_actual: BudgetUsage = Field(default_factory=BudgetUsage)
    unknown_upper_bound: BudgetUsage = Field(default_factory=BudgetUsage)
    conservative_committed: BudgetUsage = Field(default_factory=BudgetUsage)
    created_at: AwareDatetime
    finished_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def validate_terminal_shape(self) -> BudgetLease:
        terminal = self.status != "active"
        if terminal != (self.finished_at is not None):
            raise ValueError("terminal leases require finished_at and active leases forbid it")
        if self.status == "active" and any(
            value != BudgetUsage()
            for value in (
                self.observed_actual,
                self.unknown_upper_bound,
                self.conservative_committed,
            )
        ):
            raise ValueError("active leases cannot claim actual, unknown, or committed usage")
        for field_name in Budget.model_fields:
            if field_name == "schema_version":
                continue
            if getattr(self.conservative_committed, field_name) > getattr(
                self.reserved, field_name
            ):
                raise ValueError(f"lease usage exceeds reserved {field_name}")
        expected_committed = _canonical_usage_sum(
            self.observed_actual,
            self.unknown_upper_bound,
        )
        if self.conservative_committed != expected_committed:
            raise ValueError(
                "lease conservative commitment must equal actual plus unknown upper bound"
            )
        if self.status == "released" and self.conservative_committed != BudgetUsage():
            raise ValueError("released leases cannot claim child usage")
        return self


class JobRunSnapshot(V2Contract):
    run_id: Identifier
    job_ref: ArtifactRef
    revision: Annotated[int, Field(ge=1)]
    status: Literal[
        "running",
        "released",
        "failed",
        "needs_human",
        "budget_exhausted",
    ]
    reserved_budget: Budget
    observed_actual_budget: BudgetUsage
    unknown_upper_bound_budget: BudgetUsage
    conservative_committed_budget: BudgetUsage
    attempts: tuple[NodeAttempt, ...] = ()
    latest_artifact_refs: tuple[ArtifactRef, ...] = ()
    release_ref: ArtifactRef | None = None
    failure_code: Identifier | None = None
    failure_summary: NonEmptyStr | None = None

    @model_validator(mode="after")
    def release_shape(self) -> JobRunSnapshot:
        expected_committed = _canonical_usage_sum(
            self.observed_actual_budget,
            self.unknown_upper_bound_budget,
        )
        if self.conservative_committed_budget != expected_committed:
            raise ValueError(
                "snapshot conservative commitment must equal actual plus unknown upper bound"
            )
        exceeded = tuple(
            field_name
            for field_name in Budget.model_fields
            if field_name != "schema_version"
            and Decimal(str(getattr(self.conservative_committed_budget, field_name)))
            > Decimal(str(getattr(self.reserved_budget, field_name)))
        )
        if exceeded:
            raise ValueError(
                "snapshot conservative commitment exceeds reserved dimensions: "
                + ", ".join(exceeded)
            )
        if self.status == "released" and self.release_ref is None:
            raise ValueError("released run requires release_ref")
        if self.status != "released" and self.release_ref is not None:
            raise ValueError("release_ref is only valid for released runs")
        failure_values = (self.failure_code, self.failure_summary)
        if self.status in {"running", "released"} and any(
            value is not None for value in failure_values
        ):
            raise ValueError("running/released snapshots cannot contain failure metadata")
        if self.status not in {"running", "released"} and any(
            value is None for value in failure_values
        ):
            raise ValueError("terminal failure snapshots require failure metadata")
        return self


def _canonical_usage_sum(left: BudgetUsage, right: BudgetUsage) -> BudgetUsage:
    """Match ledger Decimal arithmetic at persisted model boundaries."""

    values: dict[str, int | float] = {}
    for field_name in Budget.model_fields:
        if field_name == "schema_version":
            continue
        left_value = getattr(left, field_name)
        right_value = getattr(right, field_name)
        total = Decimal(str(left_value)) + Decimal(str(right_value))
        values[field_name] = (
            int(total)
            if isinstance(left_value, int) and isinstance(right_value, int)
            else float(total)
        )
    return BudgetUsage.model_validate(values)


__all__ = [
    "BudgetLease",
    "JobRunSnapshot",
    "NodeAttempt",
    "NodeKind",
    "NodeStatus",
    "RepairDirective",
    "RepairLedgerEntry",
]
