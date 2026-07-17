"""Evidence-backed inputs and outputs for optional Evolve source discovery.

Expansion sources discover mutation clues.  They do not select parents, create
``MutationIntent`` values, execute candidates, or participate in release gates.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, model_validator

from .base import ArtifactRef, ContentHash, Identifier, KeyValue, NonEmptyStr, V2Contract
from .jobs import Budget, BudgetUsage, PermissionScope

ExpansionSourceKind = Literal[
    "requirement_gap",
    "web_workflow",
    "tool_ecosystem",
    "repository",
    "pool_neighborhood",
    "random_theme",
    "capability_gap",
]

CAPABILITY_FEEDBACK_ARTIFACT_TYPE = "consumer.capability_feedback"
CAPABILITY_FEEDBACK_ARTIFACT_ID_PREFIX = "feedback:"
CAPABILITY_FEEDBACK_PRODUCER = "consumer-feedback-recorder"


class ExpansionSourceDescriptor(V2Contract):
    """One replaceable source implementation frozen into a Campaign catalog."""

    source_id: Identifier
    engine: Identifier = "evidence-backed-web"
    kind: ExpansionSourceKind
    version: NonEmptyStr = "1"
    parameters: tuple[KeyValue, ...] = ()
    budget: Budget
    maximum_hypotheses: Annotated[int, Field(ge=1, le=32)] = 4
    maximum_clues: Annotated[int, Field(ge=1, le=32)] = 4
    maximum_parents: Annotated[int, Field(ge=1, le=64)] = 8
    maximum_context_bytes: Annotated[
        int,
        Field(ge=16_384, le=4 * 1024 * 1024),
    ] = 524_288

    @model_validator(mode="after")
    def validate_source_budget(self) -> ExpansionSourceDescriptor:
        keys = [item.key for item in self.parameters]
        if len(set(keys)) != len(keys):
            raise ValueError("ExpansionSource parameters must have unique keys")
        if self.budget.agent_turns < 2 or self.budget.llm_tokens < 2:
            raise ValueError("evidence-backed ExpansionSource requires two real Agent turns")
        if self.budget.search_calls < 1:
            raise ValueError("evidence-backed ExpansionSource requires a real search call")
        if self.budget.tool_calls <= self.budget.search_calls:
            raise ValueError("ExpansionSource must reserve at least one fetch beyond search calls")
        prohibited = {
            "build_seconds": self.budget.build_seconds,
            "evaluation_episodes": self.budget.evaluation_episodes,
            "container_seconds": self.budget.container_seconds,
            "live_probe_cost": self.budget.live_probe_cost,
        }
        nonzero = sorted(name for name, value in prohibited.items() if value)
        if nonzero:
            raise ValueError(f"ExpansionSource cannot reserve candidate work: {nonzero}")
        return self


class ExpansionSourceCatalog(V2Contract):
    catalog_id: Identifier
    sources: Annotated[tuple[ExpansionSourceDescriptor, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def unique_sources(self) -> ExpansionSourceCatalog:
        ids = [item.source_id for item in self.sources]
        if len(set(ids)) != len(ids):
            raise ValueError("ExpansionSourceCatalog source ids must be unique")
        return self


class _CapabilitySignal(V2Contract):
    """Shared closed metadata for one aggregate, never one task or trajectory."""

    capability_dimension: Identifier
    sample_count: Annotated[int, Field(ge=0)]
    confidence: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]

    @model_validator(mode="after")
    def zero_samples_have_zero_confidence(self) -> _CapabilitySignal:
        if self.sample_count == 0 and self.confidence != 0:
            raise ValueError("zero-sample capability signals must have zero confidence")
        return self


class CapabilitySuccessSignal(_CapabilitySignal):
    signal_type: Literal["success_count"] = "success_count"
    count: Annotated[int, Field(ge=0)]

    @model_validator(mode="after")
    def count_is_bounded_by_samples(self) -> CapabilitySuccessSignal:
        if self.count > self.sample_count:
            raise ValueError("success count cannot exceed sample_count")
        return self


class CapabilityFailureSignal(_CapabilitySignal):
    signal_type: Literal["failure_count"] = "failure_count"
    count: Annotated[int, Field(ge=0)]

    @model_validator(mode="after")
    def count_is_bounded_by_samples(self) -> CapabilityFailureSignal:
        if self.count > self.sample_count:
            raise ValueError("failure count cannot exceed sample_count")
        return self


class CapabilityRateSignal(_CapabilitySignal):
    signal_type: Literal["rate"] = "rate"
    metric: Literal["success", "failure", "truncation", "runtime_error"]
    value: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]

    @model_validator(mode="after")
    def rate_requires_samples(self) -> CapabilityRateSignal:
        if self.sample_count == 0:
            raise ValueError("rate signals require at least one sample")
        return self


class CapabilityRewardSignal(_CapabilitySignal):
    signal_type: Literal["reward"] = "reward"
    statistic: Literal["mean", "minimum", "maximum", "p50", "p90", "p95", "p99"]
    value: Annotated[float, Field(allow_inf_nan=False)]

    @model_validator(mode="after")
    def reward_requires_samples(self) -> CapabilityRewardSignal:
        if self.sample_count == 0:
            raise ValueError("reward signals require at least one sample")
        return self


class CapabilityStepsSignal(_CapabilitySignal):
    signal_type: Literal["steps"] = "steps"
    statistic: Literal["mean", "minimum", "maximum", "p50", "p90", "p95", "p99"]
    value: Annotated[float, Field(ge=0, allow_inf_nan=False)]

    @model_validator(mode="after")
    def steps_require_samples(self) -> CapabilityStepsSignal:
        if self.sample_count == 0:
            raise ValueError("steps signals require at least one sample")
        return self


class CapabilityCountSignal(_CapabilitySignal):
    signal_type: Literal["count"] = "count"
    metric: Literal[
        "episodes",
        "packages",
        "tool_calls",
        "runtime_errors",
        "timeouts",
        "permission_denials",
    ]
    count: Annotated[int, Field(ge=0)]


class CapabilityCoverageGapSignal(_CapabilitySignal):
    signal_type: Literal["coverage_gap"] = "coverage_gap"
    gap: Literal[
        "unattempted",
        "low_success",
        "high_failure",
        "low_reward",
        "excess_steps",
        "runtime_instability",
        "insufficient_samples",
    ]
    severity: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]


type CapabilityAggregateSignal = Annotated[
    CapabilitySuccessSignal
    | CapabilityFailureSignal
    | CapabilityRateSignal
    | CapabilityRewardSignal
    | CapabilityStepsSignal
    | CapabilityCountSignal
    | CapabilityCoverageGapSignal,
    Field(discriminator="signal_type"),
]


class _CapabilityFeedbackBody(V2Contract):
    format: Literal["agent-world.capability-feedback.v1"] = "agent-world.capability-feedback.v1"
    created_at: AwareDatetime
    suite_snapshot_id: Identifier
    suite_snapshot_digest: ContentHash
    signals: Annotated[tuple[CapabilityAggregateSignal, ...], Field(min_length=1)]
    evidence_refs: tuple[ArtifactRef, ...] = ()

    @model_validator(mode="after")
    def validate_feedback_body(self) -> _CapabilityFeedbackBody:
        identities = [
            (
                signal.capability_dimension,
                signal.signal_type,
                getattr(signal, "metric", None),
                getattr(signal, "statistic", None),
                getattr(signal, "gap", None),
            )
            for signal in self.signals
        ]
        if len(set(identities)) != len(identities):
            raise ValueError("CapabilityFeedback aggregate signal identities must be unique")
        evidence = [item.revision_id for item in self.evidence_refs]
        if len(set(evidence)) != len(evidence):
            raise ValueError("CapabilityFeedback evidence_refs must be unique")
        return self


class CapabilityFeedback(_CapabilityFeedbackBody):
    """Frozen aggregate priority signal, never world evidence or release evidence."""

    feedback_id: Identifier

    @classmethod
    def create(
        cls,
        *,
        created_at: datetime,
        suite_snapshot_id: str,
        suite_snapshot_digest: str,
        signals: tuple[CapabilityAggregateSignal, ...],
        evidence_refs: tuple[ArtifactRef, ...] = (),
    ) -> CapabilityFeedback:
        body = _CapabilityFeedbackBody(
            created_at=created_at,
            suite_snapshot_id=suite_snapshot_id,
            suite_snapshot_digest=suite_snapshot_digest,
            signals=signals,
            evidence_refs=evidence_refs,
        )
        digest = body.content_digest()
        return cls(
            **body.model_dump(mode="python"),
            feedback_id=f"feedback:{digest.removeprefix('sha256:')}",
        )

    @model_validator(mode="after")
    def validate_identity(self) -> CapabilityFeedback:
        body = _CapabilityFeedbackBody(
            created_at=self.created_at,
            suite_snapshot_id=self.suite_snapshot_id,
            suite_snapshot_digest=self.suite_snapshot_digest,
            signals=self.signals,
            evidence_refs=self.evidence_refs,
        )
        expected_id = f"feedback:{body.content_digest().removeprefix('sha256:')}"
        if self.feedback_id != expected_id:
            raise ValueError("CapabilityFeedback id does not match canonical aggregate content")
        return self


class ExpansionSourceParent(V2Contract):
    """Exact released-parent design projection visible to a Source."""

    package_manifest_ref: ArtifactRef
    design_ref: ArtifactRef
    coverage_map_ref: ArtifactRef


class ExpansionSourceRequest(V2Contract):
    """One immutable, budgeted Source invocation over frozen parent inputs."""

    request_id: Identifier
    created_at: AwareDatetime
    descriptor: ExpansionSourceDescriptor
    parents: Annotated[tuple[ExpansionSourceParent, ...], Field(min_length=1)]
    target_coverage_dimensions: Annotated[tuple[Identifier, ...], Field(min_length=1)]
    feedback_refs: tuple[ArtifactRef, ...] = ()
    permissions: PermissionScope
    allowed_source_kinds: tuple[Identifier, ...] = ("web",)
    maximum_risk: Literal["low", "medium", "high", "critical"] = "medium"
    seed: Annotated[int, Field(ge=0)]

    @model_validator(mode="after")
    def validate_frozen_inputs(self) -> ExpansionSourceRequest:
        if self.allowed_source_kinds != ("web",):
            raise ValueError("ExpansionSource currently supports exactly real Web transport")
        parent_revisions = [item.package_manifest_ref.revision_id for item in self.parents]
        if len(set(parent_revisions)) != len(parent_revisions):
            raise ValueError("ExpansionSource parents must be unique exact manifests")
        targets = self.target_coverage_dimensions
        if len(set(targets)) != len(targets):
            raise ValueError("target_coverage_dimensions must be unique")
        feedback = [item.revision_id for item in self.feedback_refs]
        if len(set(feedback)) != len(feedback):
            raise ValueError("feedback_refs must be unique")
        if self.descriptor.kind == "capability_gap" and not self.feedback_refs:
            raise ValueError("CapabilityGap requires an explicit frozen feedback snapshot")
        return self


class ExpansionSourceHypothesis(V2Contract):
    """An unproven idea.  Policy and candidate execution must never consume it."""

    hypothesis_id: Identifier
    source_request_ref: ArtifactRef
    statement: NonEmptyStr
    tool_or_workflow_surface: tuple[NonEmptyStr, ...] = ()
    coverage_dimensions: Annotated[tuple[Identifier, ...], Field(min_length=1)]
    research_queries: Annotated[tuple[NonEmptyStr, ...], Field(min_length=1)]
    dedup_fingerprint: ContentHash


class ExpansionSourceResult(V2Contract):
    """Terminal Source outcome, deliberately separate from CandidateOutcome/fitness."""

    result_id: Identifier
    source_request_ref: ArtifactRef
    status: Literal[
        "completed",
        "insufficient_evidence",
        "needs_human",
        "budget_exhausted",
        "input_rejected",
        "infrastructure_error",
    ]
    hypothesis_refs: tuple[ArtifactRef, ...] = ()
    clue_refs: tuple[ArtifactRef, ...] = ()
    evidence_refs: tuple[ArtifactRef, ...] = ()
    budget_usage: BudgetUsage = Field(default_factory=BudgetUsage)
    failure_code: Identifier | None = None

    @model_validator(mode="after")
    def validate_terminal_shape(self) -> ExpansionSourceResult:
        if self.status == "completed" and not self.clue_refs:
            raise ValueError("completed ExpansionSource requires at least one clue")
        if self.status != "completed" and self.clue_refs:
            raise ValueError("non-completed ExpansionSource cannot publish clues")
        if self.status in {"completed", "insufficient_evidence"}:
            if self.failure_code is not None:
                raise ValueError("successful/evidence-empty Source result cannot claim failure")
        elif self.failure_code is None:
            raise ValueError("failed ExpansionSource result requires failure_code")
        return self


class ExpansionClueSnapshot(V2Contract):
    """Frozen clue universe prepared before the Campaign's first Policy.ask."""

    snapshot_id: Identifier
    created_at: AwareDatetime
    source_catalog_ref: ArtifactRef
    inbox_snapshot_ref: ArtifactRef | None = None
    source_request_refs: Annotated[tuple[ArtifactRef, ...], Field(min_length=1)]
    source_result_refs: Annotated[tuple[ArtifactRef, ...], Field(min_length=1)]
    clue_refs: tuple[ArtifactRef, ...] = ()
    feedback_refs: tuple[ArtifactRef, ...] = ()

    @model_validator(mode="after")
    def validate_snapshot(self) -> ExpansionClueSnapshot:
        if len(self.source_request_refs) != len(self.source_result_refs):
            raise ValueError("ClueSnapshot requires one Source result per request")
        for name in ("source_request_refs", "source_result_refs", "clue_refs", "feedback_refs"):
            refs = getattr(self, name)
            if len({item.revision_id for item in refs}) != len(refs):
                raise ValueError(f"{name} must contain unique revisions")
        return self


__all__ = [
    "CAPABILITY_FEEDBACK_ARTIFACT_ID_PREFIX",
    "CAPABILITY_FEEDBACK_ARTIFACT_TYPE",
    "CAPABILITY_FEEDBACK_PRODUCER",
    "CapabilityAggregateSignal",
    "CapabilityCountSignal",
    "CapabilityCoverageGapSignal",
    "CapabilityFailureSignal",
    "CapabilityFeedback",
    "CapabilityRateSignal",
    "CapabilityRewardSignal",
    "CapabilityStepsSignal",
    "CapabilitySuccessSignal",
    "ExpansionClueSnapshot",
    "ExpansionSourceCatalog",
    "ExpansionSourceDescriptor",
    "ExpansionSourceHypothesis",
    "ExpansionSourceKind",
    "ExpansionSourceParent",
    "ExpansionSourceRequest",
    "ExpansionSourceResult",
]
