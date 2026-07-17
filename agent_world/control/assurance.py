"""Framework-owned claim readiness, maturity and atomic node commitments."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, JsonValue, model_validator

from agent_world.contracts import (
    ArtifactRef,
    BudgetUsage,
    Identifier,
    NonEmptyStr,
    V2Contract,
    canonical_json_bytes,
    sha256_digest,
)

type ClaimStatus = Literal[
    "unknown",
    "passed",
    "failed",
    "inconclusive",
    "error",
    "not_run",
    "invalidated",
]
type GateEffect = Literal[
    "observe",
    "reject_revision",
    "block_integration",
    "block_release",
    "quarantine",
]
type ArtifactMaturity = Literal[
    "unvalidated",
    "design_valid",
    "build_valid",
    "executable",
    "integration_ready",
    "release_candidate",
    "released",
]

_MATURITY_ORDER: tuple[ArtifactMaturity, ...] = (
    "design_valid",
    "build_valid",
    "executable",
    "integration_ready",
    "release_candidate",
    "released",
)
_MATURITY_CLAIMS: dict[ArtifactMaturity, tuple[str, ...]] = {
    "design_valid": ("design.valid",),
    "build_valid": ("design.valid", "build.valid"),
    "executable": ("design.valid", "build.valid", "runtime.executable"),
    "integration_ready": (
        "design.valid",
        "build.valid",
        "runtime.executable",
        "integration.ready",
    ),
    "release_candidate": (
        "design.valid",
        "build.valid",
        "runtime.executable",
        "integration.ready",
        "verifier.valid",
        "release_judge.valid",
        "observability.release_ready",
    ),
    "released": (
        "design.valid",
        "build.valid",
        "runtime.executable",
        "integration.ready",
        "verifier.valid",
        "release_judge.valid",
        "observability.release_ready",
        "registry.released",
    ),
}


class AssuranceClaim(V2Contract):
    """One framework-evaluated claim over an exact immutable subject."""

    claim_id: Identifier
    subject_ref: ArtifactRef
    producer: Identifier
    status: ClaimStatus
    effect: GateEffect
    evidence_refs: tuple[ArtifactRef, ...] = ()
    dependency_refs: tuple[ArtifactRef, ...] = ()
    summary: NonEmptyStr
    evaluated_at: AwareDatetime
    invalidated_by_refs: tuple[ArtifactRef, ...] = ()

    @model_validator(mode="after")
    def validate_evidence_shape(self) -> AssuranceClaim:
        if self.status in {"passed", "failed", "inconclusive", "error"} and not (
            self.evidence_refs
        ):
            raise ValueError("evaluated AssuranceClaim requires evidence")
        if self.status == "invalidated" and not self.invalidated_by_refs:
            raise ValueError("invalidated AssuranceClaim requires invalidating refs")
        if self.status != "invalidated" and self.invalidated_by_refs:
            raise ValueError("only invalidated AssuranceClaim may bind invalidating refs")
        return self


class ClaimVector(V2Contract):
    """Exact readiness projection; maturity is recomputed and cannot be self-reported."""

    vector_id: Identifier
    revision: Annotated[int, Field(ge=1)]
    design_ref: ArtifactRef
    candidate_ref: ArtifactRef | None = None
    integration_ref: ArtifactRef | None = None
    verifier_ref: ArtifactRef | None = None
    release_judge_ref: ArtifactRef | None = None
    telemetry_ref: ArtifactRef | None = None
    claims: Annotated[tuple[AssuranceClaim, ...], Field(min_length=1)]
    maturity: ArtifactMaturity
    blocking_claim_ids: tuple[Identifier, ...] = ()

    @model_validator(mode="after")
    def validate_framework_projection(self) -> ClaimVector:
        if len({item.claim_id for item in self.claims}) != len(self.claims):
            raise ValueError("ClaimVector claim ids must be unique")
        expected_maturity, expected_blocking = reduce_maturity(self.claims)
        if self.maturity != expected_maturity:
            raise ValueError("ClaimVector maturity is not the framework-derived value")
        if self.blocking_claim_ids != expected_blocking:
            raise ValueError("ClaimVector blocking ids are not the framework-derived value")
        if (
            self.maturity
            in {
                "build_valid",
                "executable",
                "integration_ready",
                "release_candidate",
                "released",
            }
            and self.candidate_ref is None
        ):
            raise ValueError("post-design maturity requires candidate_ref")
        if (
            self.maturity
            in {
                "integration_ready",
                "release_candidate",
                "released",
            }
            and self.integration_ref is None
        ):
            raise ValueError("integration maturity requires integration_ref")
        if self.maturity in {"release_candidate", "released"} and (
            self.verifier_ref is None
            or self.release_judge_ref is None
            or self.telemetry_ref is None
        ):
            raise ValueError("release maturity requires Verifier, Release Judge and telemetry refs")
        return self


class TelemetryReleaseSummary(V2Contract):
    """Sanitized pre-release trace commitment; never contains prompts or sealed cases."""

    trace_id: Identifier
    run_id: Identifier
    collected_at: AwareDatetime
    cut_stage: Literal["pre_publish", "post_publish"]
    as_of_ns: Annotated[int, Field(ge=1)]
    open_span_count: Annotated[int, Field(ge=0)]
    provisional: bool
    health: Literal["healthy"] = "healthy"
    journal_mode: Literal["wal"] = "wal"
    span_count: Annotated[int, Field(ge=1)]
    metric_count: Annotated[int, Field(ge=0)]
    event_count: Annotated[int, Field(ge=0)]
    invocation_count: Annotated[int, Field(ge=1)]
    required_node_attempts: dict[Identifier, Annotated[int, Field(ge=1)]]
    required_operation_attempts: dict[Identifier, Annotated[int, Field(ge=1)]]
    required_metric_observations: dict[Identifier, Annotated[int, Field(ge=1)]]
    research_provenance_refs: tuple[ArtifactRef, ...] = ()
    unknown_measurement_count: Annotated[int, Field(ge=0)]
    summary: dict[str, JsonValue]
    summary_digest: str

    @model_validator(mode="after")
    def validate_trace_cut(self) -> TelemetryReleaseSummary:
        if self.cut_stage == "pre_publish":
            if not self.provisional or self.open_span_count != 1:
                raise ValueError("pre-publish telemetry requires exactly one open root span")
        elif self.provisional or self.open_span_count:
            raise ValueError("post-publish telemetry must be terminal")
        if self.summary.get("as_of_ns") != self.as_of_ns:
            raise ValueError("telemetry as_of_ns differs from its summary")
        if self.summary.get("open_span_count") != self.open_span_count:
            raise ValueError("telemetry open span count differs from its summary")
        if self.summary.get("provisional") is not self.provisional:
            raise ValueError("telemetry provisional flag differs from its summary")
        expected_digest = sha256_digest(canonical_json_bytes(self.summary))
        if self.summary_digest != expected_digest:
            raise ValueError("telemetry summary digest mismatch")
        reuse_mode = set(self.required_operation_attempts) == {"research.checkpoint_reuse"}
        if reuse_mode:
            if (
                len(self.research_provenance_refs) != 1
                or self.research_provenance_refs[0].artifact_type
                != "control.research_checkpoint_reuse_evidence"
            ):
                raise ValueError(
                    "checkpoint reuse telemetry requires one typed provenance artifact"
                )
        elif self.research_provenance_refs:
            raise ValueError("executed research telemetry cannot cite checkpoint reuse")
        return self


class ResearchCheckpointReuseEvidence(V2Contract):
    """Framework proof that a validated prior evidence graph replaced new search."""

    adoption_id: Identifier
    run_id: Identifier
    job_ref: ArtifactRef
    request_ref: ArtifactRef
    checkpoint_ref: ArtifactRef
    evidence_graph_ref: ArtifactRef
    final_design_ref: ArtifactRef
    modeling_gate_ref: ArtifactRef
    adopted_at: AwareDatetime

    @model_validator(mode="after")
    def validate_bindings(self) -> ResearchCheckpointReuseEvidence:
        if self.job_ref.artifact_type != "control.environment_job":
            raise ValueError("research reuse job_ref has the wrong artifact type")
        if self.request_ref.artifact_type != "control.environment_request":
            raise ValueError("research reuse request_ref has the wrong artifact type")
        if self.checkpoint_ref.artifact_type not in {
            "design.phase_checkpoint",
            "control.job_run_snapshot",
        }:
            raise ValueError("research reuse requires a typed resumable checkpoint")
        if self.evidence_graph_ref.artifact_type != "design.evidence_graph":
            raise ValueError("research reuse must bind an EvidenceGraph")
        if self.final_design_ref.artifact_type != "design.environment_design":
            raise ValueError("research reuse must bind the final EnvironmentDesign")
        if self.modeling_gate_ref.artifact_type != "control.modeling_gate":
            raise ValueError("research reuse must bind the final Modeling Gate")
        return self


class NodeCommit(V2Contract):
    """Atomic durable completion record written before downstream work starts."""

    commit_id: Identifier
    run_id: Identifier
    node: Identifier
    attempt_id: Identifier
    status: Literal["passed", "failed", "error", "cancelled"]
    input_refs: tuple[ArtifactRef, ...]
    output_refs: tuple[ArtifactRef, ...]
    settled_lease_ref: ArtifactRef | None = None
    usage: BudgetUsage = Field(default_factory=BudgetUsage)
    committed_at: AwareDatetime

    @model_validator(mode="after")
    def validate_terminal_shape(self) -> NodeCommit:
        if self.status == "passed" and not self.output_refs:
            raise ValueError("passed NodeCommit requires output refs")
        return self


def reduce_maturity(
    claims: tuple[AssuranceClaim, ...] | list[AssuranceClaim],
) -> tuple[ArtifactMaturity, tuple[Identifier, ...]]:
    """Derive the highest proven maturity and all currently blocking claims."""

    by_id = {claim.claim_id: claim for claim in claims}
    maturity: ArtifactMaturity = "unvalidated"
    for candidate in _MATURITY_ORDER:
        required = _MATURITY_CLAIMS[candidate]
        if all(
            by_id.get(claim_id) is not None and by_id[claim_id].status == "passed"
            for claim_id in required
        ):
            maturity = candidate
        else:
            break
    blocking = tuple(
        sorted(
            claim.claim_id
            for claim in claims
            if claim.effect in {"block_integration", "block_release", "quarantine"}
            and claim.status != "passed"
        )
    )
    return maturity, blocking


def claim(
    *,
    claim_id: str,
    subject_ref: ArtifactRef,
    producer: str,
    status: ClaimStatus,
    effect: GateEffect,
    summary: str,
    evidence_refs: tuple[ArtifactRef, ...] = (),
    dependency_refs: tuple[ArtifactRef, ...] = (),
    evaluated_at: datetime,
) -> AssuranceClaim:
    return AssuranceClaim(
        claim_id=claim_id,
        subject_ref=subject_ref,
        producer=producer,
        status=status,
        effect=effect,
        evidence_refs=evidence_refs,
        dependency_refs=dependency_refs,
        summary=summary,
        evaluated_at=evaluated_at,
    )


__all__ = [
    "ArtifactMaturity",
    "AssuranceClaim",
    "ClaimStatus",
    "ClaimVector",
    "GateEffect",
    "NodeCommit",
    "TelemetryReleaseSummary",
    "ResearchCheckpointReuseEvidence",
    "claim",
    "reduce_maturity",
]
