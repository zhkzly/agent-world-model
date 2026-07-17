"""Tool-first expansion intents, semantic deltas, and candidate outcomes."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, JsonValue, model_validator

from .base import ArtifactRef, ContentHash, Identifier, KeyValue, NonEmptyStr, V2Contract
from .design import DifficultyDimension, TaskRequirement
from .evidence import CoverageLevel
from .jobs import Budget, BudgetUsage, PermissionScope, ReleaseProfile
from .judging import Finding, GateResult
from .lineage import IdentityDecision, ImplementationLineage, SemanticLineage
from .world import Rule, StateSchema, ToolSemantics, ToolSurface, WorldBoundary


class MutationIntent(V2Contract):
    intent_id: Identifier
    parent_refs: Annotated[tuple[ArtifactRef, ...], Field(min_length=1)]
    primary_parent_ref: ArtifactRef
    clue_refs: tuple[ArtifactRef, ...] = ()
    operator: Literal[
        "tool_surface",
        "tool_semantics",
        "transition_constraint",
        "task_scope",
        "composite",
    ]
    operator_version: NonEmptyStr
    parameters: tuple[KeyValue, ...] = ()
    seed: Annotated[int, Field(ge=0)]
    target_coverage_dimensions: Annotated[tuple[Identifier, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def validate_parent_identity(self) -> MutationIntent:
        revisions = [item.revision_id for item in self.parent_refs]
        if len(set(revisions)) != len(revisions):
            raise ValueError("MutationIntent parent_refs must be unique")
        if self.primary_parent_ref not in self.parent_refs:
            raise ValueError("primary_parent_ref must be one of parent_refs")
        if len(self.parent_refs) > 1 and self.operator != "composite":
            raise ValueError("multiple parents require a composite operator")
        return self


class ExpansionCampaign(V2Contract):
    """Frozen, resumable search scope consumed by one replaceable policy."""

    campaign_id: Identifier
    created_at: AwareDatetime
    anchor_package_refs: Annotated[tuple[ArtifactRef, ...], Field(min_length=1)]
    pool_snapshot_ref: ArtifactRef
    inbox_snapshot_ref: ArtifactRef | None = None
    source_catalog_ref: ArtifactRef
    feedback_refs: tuple[ArtifactRef, ...] = ()
    target_coverage_dimensions: Annotated[tuple[Identifier, ...], Field(min_length=1)]
    policy_id: Identifier
    policy_version: NonEmptyStr
    policy_parameters: tuple[KeyValue, ...] = ()
    operator_catalog_ref: ArtifactRef
    budget: Budget
    candidate_budget: Budget
    permissions: PermissionScope
    allowed_source_kinds: Annotated[tuple[Identifier, ...], Field(min_length=1)] = ("web",)
    risk_level: Literal["low", "medium", "high", "critical"] = "medium"
    fidelity_requirements: tuple[NonEmptyStr, ...] = ()
    release_profile: ReleaseProfile
    campaign_seed: Annotated[int, Field(ge=0)]
    maximum_intents_per_iteration: Annotated[int, Field(ge=1, le=128)] = 1
    maximum_in_flight: Annotated[int, Field(ge=1, le=32)] = 1
    maximum_iterations: Annotated[int, Field(ge=1)] = 20
    maximum_no_release_iterations: Annotated[int, Field(ge=1)] = 8
    maximum_infrastructure_error_iterations: Annotated[int, Field(ge=1)] = 3
    version_reservation_ttl_seconds: Annotated[float, Field(ge=60, le=604_800)] = 86_400

    @model_validator(mode="after")
    def validate_anchor_set(self) -> ExpansionCampaign:
        if self.allowed_source_kinds != ("web",):
            raise ValueError(
                "Expansion currently supports exactly Web evidence transport; MCP/CLI/API/SDK "
                "remain semantic mutation targets discovered from Web evidence"
            )
        revisions = [item.revision_id for item in self.anchor_package_refs]
        if len(set(revisions)) != len(revisions):
            raise ValueError("anchor_package_refs must be unique")
        feedback_revisions = [item.revision_id for item in self.feedback_refs]
        if len(set(feedback_revisions)) != len(feedback_revisions):
            raise ValueError("feedback_refs must be unique")
        parameter_keys = [item.key for item in self.policy_parameters]
        if len(set(parameter_keys)) != len(parameter_keys):
            raise ValueError("policy_parameters must have unique keys")
        if self.maximum_in_flight > self.maximum_intents_per_iteration:
            raise ValueError("maximum_in_flight cannot exceed intents per iteration")
        for field_name in Budget.model_fields:
            if field_name in {"schema_version", "wall_seconds"}:
                continue
            if getattr(self.candidate_budget, field_name) > getattr(self.budget, field_name):
                raise ValueError(f"candidate_budget.{field_name} exceeds the campaign reservation")
        if self.candidate_budget.wall_seconds > self.budget.wall_seconds:
            raise ValueError("candidate wall timeout exceeds the campaign deadline")
        return self


class ExpansionCampaignReport(V2Contract):
    """Framework-owned terminal projection; outcomes remain separate artifacts."""

    report_id: Identifier
    campaign_ref: ArtifactRef
    pool_snapshot_ref: ArtifactRef
    source_catalog_ref: ArtifactRef
    source_request_refs: Annotated[tuple[ArtifactRef, ...], Field(min_length=1)]
    source_result_refs: Annotated[tuple[ArtifactRef, ...], Field(min_length=1)]
    clue_snapshot_ref: ArtifactRef
    context_ref: ArtifactRef
    final_policy_checkpoint_ref: ArtifactRef
    final_framework_checkpoint_ref: ArtifactRef
    iteration_refs: tuple[ArtifactRef, ...] = ()
    outcome_refs: tuple[ArtifactRef, ...] = ()
    released_package_refs: tuple[ArtifactRef, ...] = ()
    stop_reason: Literal[
        "iteration_limit",
        "no_release_progress",
        "budget_exhausted",
        "no_admissible_operator",
        "completed_requested_iterations",
        "needs_human",
        "infrastructure_error",
    ]
    budget_usage: BudgetUsage = Field(default_factory=BudgetUsage)

    @model_validator(mode="after")
    def validate_source_bindings(self) -> ExpansionCampaignReport:
        if len(self.source_request_refs) != len(self.source_result_refs):
            raise ValueError("Campaign report requires one Source result per request")
        for label, refs in (
            ("source_request_refs", self.source_request_refs),
            ("source_result_refs", self.source_result_refs),
        ):
            if len({item.revision_id for item in refs}) != len(refs):
                raise ValueError(f"{label} must contain unique revisions")
        return self


class ToolSurfaceDelta(V2Contract):
    operation: Literal["add", "remove", "modify"]
    tool_id: Identifier
    before_hash: ContentHash | None = None
    after: ToolSurface | None = None
    changed_aspects: Annotated[
        tuple[
            Literal[
                "surface",
                "schema",
                "observation_schema",
            ],
            ...,
        ],
        Field(min_length=1),
    ]

    @model_validator(mode="after")
    def validate_operation(self) -> ToolSurfaceDelta:
        if self.operation == "add" and (self.before_hash is not None or self.after is None):
            raise ValueError("add requires after and forbids before_hash")
        if self.operation == "remove" and (self.before_hash is None or self.after is not None):
            raise ValueError("remove requires before_hash and forbids after")
        if self.operation == "modify" and (self.before_hash is None or self.after is None):
            raise ValueError("modify requires before_hash and after")
        return self


class ToolSemanticsDelta(V2Contract):
    operation: Literal["add", "remove", "modify"]
    tool_id: Identifier
    before_hash: ContentHash | None = None
    after: ToolSemantics | None = None
    changed_aspects: Annotated[
        tuple[
            Literal[
                "precondition",
                "transition",
                "postcondition",
                "error",
                "permission",
                "observation",
                "idempotency",
                "retry",
                "timeout",
                "transaction",
                "rollback",
                "concurrency",
            ],
            ...,
        ],
        Field(min_length=1),
    ]

    @model_validator(mode="after")
    def validate_operation(self) -> ToolSemanticsDelta:
        if self.operation == "add" and (self.before_hash is not None or self.after is None):
            raise ValueError("add requires after and forbids before_hash")
        if self.operation == "remove" and (self.before_hash is None or self.after is not None):
            raise ValueError("remove requires before_hash and forbids after")
        if self.operation == "modify" and (self.before_hash is None or self.after is None):
            raise ValueError("modify requires before_hash and after")
        return self


class StateSchemaDelta(V2Contract):
    before_hash: ContentHash
    after: StateSchema
    changed_entities: Annotated[tuple[Identifier, ...], Field(min_length=1)]
    rationale: NonEmptyStr


class TransitionConstraintDelta(V2Contract):
    operation: Literal["add", "remove", "modify"]
    rule_id: Identifier
    before_hash: ContentHash | None = None
    after: Rule | None = None
    affected_tool_ids: Annotated[tuple[Identifier, ...], Field(min_length=1)]
    rationale: NonEmptyStr

    @model_validator(mode="after")
    def validate_operation(self) -> TransitionConstraintDelta:
        if self.operation == "add" and (self.before_hash is not None or self.after is None):
            raise ValueError("add requires after and forbids before_hash")
        if self.operation == "remove" and (self.before_hash is None or self.after is not None):
            raise ValueError("remove requires before_hash and forbids after")
        if self.operation == "modify" and (self.before_hash is None or self.after is None):
            raise ValueError("modify requires before_hash and after")
        return self


class TaskScopeDelta(V2Contract):
    operation: Literal["add", "remove", "modify"]
    task_type: Identifier
    before_hash: ContentHash | None = None
    after: TaskRequirement | None = None
    rationale: NonEmptyStr

    @model_validator(mode="after")
    def validate_operation(self) -> TaskScopeDelta:
        if self.operation == "add" and (self.before_hash is not None or self.after is None):
            raise ValueError("add requires after and forbids before_hash")
        if self.operation == "remove" and (self.before_hash is None or self.after is not None):
            raise ValueError("remove requires before_hash and forbids after")
        if self.operation == "modify" and (self.before_hash is None or self.after is None):
            raise ValueError("modify requires before_hash and after")
        return self


class TaskDistribution(V2Contract):
    """Framework-owned snapshot of curriculum sampling semantics.

    Per-task objectives and executable rules live in :class:`TaskScopeDelta`.
    This projection records how those task types are organised and sampled,
    without including compiler-derived task protocol schemas.
    """

    task_type_order: Annotated[tuple[Identifier, ...], Field(min_length=1)]
    task_dimensions: Annotated[tuple[Identifier, ...], Field(min_length=1)]
    difficulty_dimensions: Annotated[tuple[DifficultyDimension, ...], Field(min_length=1)]
    generation_seed_space: NonEmptyStr
    minimum_distinct_initial_states: Annotated[int, Field(ge=2)]
    minimum_distinct_tasks_per_type: Annotated[int, Field(ge=2)]
    sampling_constraints: Annotated[tuple[Rule, ...], Field(max_length=128)] = ()

    @model_validator(mode="after")
    def validate_distribution(self) -> TaskDistribution:
        for label, values in (
            ("task_type_order", self.task_type_order),
            ("task_dimensions", self.task_dimensions),
        ):
            if len(set(values)) != len(values):
                raise ValueError(f"{label} must contain unique values")
        dimensions = [item.dimension for item in self.difficulty_dimensions]
        if len(set(dimensions)) != len(dimensions):
            raise ValueError("difficulty_dimensions must contain unique dimensions")
        return self


class TaskDistributionDelta(V2Contract):
    before_hash: ContentHash
    after: TaskDistribution
    changed_aspects: Annotated[
        tuple[
            Literal[
                "task_type_order",
                "task_dimensions",
                "difficulty_dimensions",
                "generation_seed_space",
                "minimum_distinct_initial_states",
                "minimum_distinct_tasks_per_type",
                "sampling_constraints",
            ],
            ...,
        ],
        Field(min_length=1),
    ]
    rationale: NonEmptyStr


class WorldBoundaryDelta(V2Contract):
    before_hash: ContentHash
    after: WorldBoundary
    changed_dimensions: Annotated[tuple[Identifier, ...], Field(min_length=1)]
    rationale: NonEmptyStr


class SemanticDelta(V2Contract):
    delta_id: Identifier
    intent_ref: ArtifactRef
    tool_surface_deltas: tuple[ToolSurfaceDelta, ...] = ()
    tool_semantics_deltas: tuple[ToolSemanticsDelta, ...] = ()
    state_schema_deltas: tuple[StateSchemaDelta, ...] = ()
    transition_constraint_deltas: tuple[TransitionConstraintDelta, ...] = ()
    task_scope_deltas: tuple[TaskScopeDelta, ...] = ()
    task_distribution_deltas: Annotated[
        tuple[TaskDistributionDelta, ...], Field(max_length=1)
    ] = ()
    world_boundary_delta: WorldBoundaryDelta | None = None
    evidence_refs: Annotated[tuple[ArtifactRef, ...], Field(min_length=1)]
    unresolved_questions: tuple[NonEmptyStr, ...] = ()

    @model_validator(mode="after")
    def require_semantic_change(self) -> SemanticDelta:
        if not any(
            (
                self.tool_surface_deltas,
                self.tool_semantics_deltas,
                self.state_schema_deltas,
                self.transition_constraint_deltas,
                self.task_scope_deltas,
                self.task_distribution_deltas,
                self.world_boundary_delta is not None,
            )
        ):
            raise ValueError("SemanticDelta cannot be empty")
        surface_by_tool = {item.tool_id: item.operation for item in self.tool_surface_deltas}
        semantics_by_tool = {item.tool_id: item.operation for item in self.tool_semantics_deltas}
        if len(surface_by_tool) != len(self.tool_surface_deltas):
            raise ValueError("tool_surface_deltas must contain at most one delta per tool")
        if len(semantics_by_tool) != len(self.tool_semantics_deltas):
            raise ValueError("tool_semantics_deltas must contain at most one delta per tool")
        for tool_id, operation in surface_by_tool.items():
            if operation in {"add", "remove"} and semantics_by_tool.get(tool_id) != operation:
                raise ValueError(
                    f"tool surface {operation} for {tool_id} requires "
                    f"matching semantics {operation}"
                )
        return self


class CoverageGain(V2Contract):
    dimension: Identifier
    before: CoverageLevel
    after: CoverageLevel
    evidence_refs: tuple[ArtifactRef, ...] = ()


class BehaviorDescriptor(V2Contract):
    descriptor: Identifier
    value: JsonValue
    evidence_refs: Annotated[tuple[ArtifactRef, ...], Field(min_length=1)]


class CandidateOutcome(V2Contract):
    outcome_id: Identifier
    campaign_ref: ArtifactRef
    iteration_ref: ArtifactRef
    intent_ref: ArtifactRef
    attempt_ref: ArtifactRef
    job_ref: ArtifactRef | None = None
    terminal_reason_code: Identifier
    candidate_ref: ArtifactRef | None = None
    released_package_ref: ArtifactRef | None = None
    terminal_status: Literal[
        "admission_rejected",
        "research_failed",
        "design_failed",
        "build_failed",
        "integration_failed",
        "verifier_failed",
        "judge_failed",
        "release_failed",
        "released",
        "needs_human",
        "budget_exhausted",
        "superseded",
        "quarantined",
        "infrastructure_error",
    ]
    hard_gate_results: tuple[GateResult, ...] = ()
    coverage_gain: tuple[CoverageGain, ...] = ()
    behavior_descriptors: tuple[BehaviorDescriptor, ...] = ()
    findings: tuple[Finding, ...] = ()
    budget_usage: BudgetUsage = Field(default_factory=BudgetUsage)
    repair_depth: Annotated[int, Field(ge=0)] = 0
    semantic_lineage_ref: ArtifactRef | None = None
    implementation_lineage_ref: ArtifactRef | None = None
    optional_consumer_metrics: dict[Identifier, float] = Field(default_factory=dict)

    @model_validator(mode="after")
    def released_requires_hard_pass(self) -> CandidateOutcome:
        if self.terminal_status == "admission_rejected" and self.job_ref is not None:
            raise ValueError("admission-rejected outcomes cannot claim an EnvironmentJob")
        if (
            self.terminal_status
            not in {
                "admission_rejected",
                "infrastructure_error",
            }
            and self.job_ref is None
        ):
            raise ValueError("admitted outcomes require job_ref")
        if self.terminal_status == "released":
            if self.candidate_ref is None:
                raise ValueError("released outcome requires candidate_ref")
            if self.released_package_ref is None:
                raise ValueError("released outcome requires released_package_ref")
            if self.semantic_lineage_ref is None or self.implementation_lineage_ref is None:
                raise ValueError("released outcome requires semantic and implementation lineage")
            if not self.hard_gate_results:
                raise ValueError("released outcome requires hard gate results")
            if any(result.hard and result.status != "pass" for result in self.hard_gate_results):
                raise ValueError("released outcome cannot contain a non-passing hard gate")
            if any(finding.blocks_release for finding in self.findings):
                raise ValueError("released outcome cannot contain blocking findings")
        candidate_terminal = {
            "judge_failed",
            "release_failed",
            "quarantined",
            "superseded",
        }
        if self.terminal_status in candidate_terminal and self.candidate_ref is None:
            raise ValueError(f"{self.terminal_status} outcome requires candidate_ref")
        if self.terminal_status != "released" and self.released_package_ref is not None:
            raise ValueError("released_package_ref is only valid for released outcomes")
        return self


__all__ = [
    "BehaviorDescriptor",
    "CandidateOutcome",
    "CoverageGain",
    "ExpansionCampaign",
    "ExpansionCampaignReport",
    "IdentityDecision",
    "ImplementationLineage",
    "MutationIntent",
    "SemanticDelta",
    "SemanticLineage",
    "StateSchemaDelta",
    "TaskDistribution",
    "TaskDistributionDelta",
    "TaskScopeDelta",
    "ToolSemanticsDelta",
    "ToolSurfaceDelta",
    "TransitionConstraintDelta",
    "WorldBoundaryDelta",
]
