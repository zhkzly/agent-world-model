"""Closed contracts for the generation WorkGraph control plane.

These records separate expensive proposal execution, deterministic validation,
real-execution assurance, boundary evaluation, repair authority, and resumable
commit state.  They are the clean-break target for every generation component;
the old FeedbackContract and component-local retry limits are not inputs.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, model_validator

from agent_world.contracts import (
    ArtifactRef,
    BudgetUsage,
    ContentHash,
    Identifier,
    NonEmptyStr,
    V2Contract,
    canonical_json_bytes,
    sha256_digest,
)

type WorkComponent = Literal[
    "controller",
    "research",
    "design",
    "verifier",
    "build",
    "integration",
    "judge",
    "release",
    "registry",
]
type AgentRole = Literal["researcher", "environment_engineer", "challenger"]
type ProposalExecutor = Literal["code", "agent", "real_tools"]
type ValidationEffect = Literal[
    "observe",
    "reject_revision",
    "block_compile",
    "block_integration",
    "block_release",
    "quarantine",
]
type ValidationStatus = Literal["passed", "failed", "inconclusive", "error"]
type DiagnosticQuality = Literal["not_applicable", "actionable", "informative", "insufficient"]
type EvaluationStatus = Literal[
    "passed",
    "failed",
    "inconclusive",
    "error",
    "not_run",
    "invalidated",
]
type ReadinessEffect = Literal["satisfies", "blocks", "observes", "invalidates"]
type ProgressClassification = Literal[
    "resolved",
    "strict_progress",
    "unchanged",
    "regressed",
    "oscillating",
    "unknown",
]
type RepairDecision = Literal[
    "local_correction",
    "parent_correction",
    "infrastructure_retry",
    "session_continuation",
    "request_human",
    "reject",
]
type ProposalExecutionStatus = Literal[
    "completed",
    "failed",
    "interrupted",
    "cancelled",
    "budget_exhausted",
]
type BoundaryExecutionStatus = Literal[
    "completed",
    "failed",
    "interrupted",
    "cancelled",
    "budget_exhausted",
]
type OperationKind = Literal["proposal", "validation", "assurance"]
type OperationRunStatus = Literal["scheduled", "running", "terminal"]
type ReplayMode = Literal[
    "deterministic",
    "idempotent_with_key",
    "queryable",
    "non_replayable",
]
type RepairOutcome = Literal[
    "authorized",
    "resolved",
    "progressed",
    "no_progress",
    "rejected",
    "exhausted",
]

_GENERIC_ISSUE_CODES = {
    "invalid",
    "schema_validation_error",
    "semantic_contract_violation",
    "value_error",
}
_GENERIC_ROOT_PARTS = {"root", "__root__", "$"}


def _duplicates(values: tuple[object, ...]) -> bool:
    return len(set(values)) != len(values)


def work_input_fingerprint(refs: tuple[ArtifactRef, ...]) -> ContentHash:
    """Return the stable identity of one immutable Work input closure."""

    if _duplicates(refs):
        raise ValueError("WorkGraph input refs must be unique")
    return sha256_digest(canonical_json_bytes(sorted(ref.revision_id for ref in refs)))


class OperationBudget(V2Contract):
    """Numeric hard limits for one operation; reporting labels are not policy."""

    wall_seconds: Annotated[float, Field(gt=0)]
    first_progress_seconds: Annotated[float, Field(gt=0)] | None = None
    first_write_seconds: Annotated[float, Field(gt=0)] | None = None
    llm_tokens: Annotated[int, Field(ge=0)] = 0
    agent_turns: Annotated[int, Field(ge=0)] = 0
    search_calls: Annotated[int, Field(ge=0)] = 0
    tool_calls: Annotated[int, Field(ge=0)] = 0
    process_calls: Annotated[int, Field(ge=0)] = 0
    build_seconds: Annotated[float, Field(ge=0)] = 0
    evaluation_episodes: Annotated[int, Field(ge=0)] = 0
    container_seconds: Annotated[float, Field(ge=0)] = 0
    live_probe_cost: Annotated[float, Field(ge=0)] = 0
    monetary_cost: Annotated[float, Field(ge=0)] = 0

    @model_validator(mode="after")
    def validate_deadlines(self) -> OperationBudget:
        for value in (self.first_progress_seconds, self.first_write_seconds):
            if value is not None and value > self.wall_seconds:
                raise ValueError("progress/write deadline cannot exceed the operation deadline")
        if (
            self.first_progress_seconds is not None
            and self.first_write_seconds is not None
            and self.first_write_seconds < self.first_progress_seconds
        ):
            raise ValueError("first-write deadline cannot precede first-progress deadline")
        return self


class ArtifactSlotContract(V2Contract):
    """Exact Artifact boundary accepted or produced by one Work item."""

    slot_id: Identifier
    direction: Literal["input", "output"]
    artifact_types: Annotated[tuple[Identifier, ...], Field(min_length=1)]
    minimum_count: Annotated[int, Field(ge=0)]
    maximum_count: Annotated[int, Field(ge=1)]
    producer_component: WorkComponent | Literal["external"]
    confidentiality: Literal["public", "framework_private", "sealed"] = "public"

    @model_validator(mode="after")
    def validate_slot(self) -> ArtifactSlotContract:
        if _duplicates(self.artifact_types):
            raise ValueError("Artifact slot types must be unique")
        if self.minimum_count > self.maximum_count:
            raise ValueError("Artifact slot minimum cannot exceed its maximum")
        if self.direction == "output" and self.producer_component == "external":
            raise ValueError("Work output cannot be owned by an external producer")
        return self

    def matching_refs(self, refs: tuple[ArtifactRef, ...]) -> tuple[ArtifactRef, ...]:
        return tuple(ref for ref in refs if ref.artifact_type in self.artifact_types)

    def validate_refs(self, refs: tuple[ArtifactRef, ...]) -> None:
        count = len(self.matching_refs(refs))
        if not self.minimum_count <= count <= self.maximum_count:
            raise ValueError(
                f"Artifact slot {self.slot_id} expected {self.minimum_count}.."
                f"{self.maximum_count} matching refs, received {count}"
            )


class WorkCoordinate(V2Contract):
    """Stable logical/physical work identity, independent of Artifact revision."""

    scope_id: Identifier
    component: WorkComponent
    stage: Identifier
    artifact_slot: Identifier
    group_id: Identifier | None = None
    shard_id: Identifier | None = None

    @model_validator(mode="after")
    def validate_hierarchy(self) -> WorkCoordinate:
        if self.shard_id is not None and self.group_id is None:
            raise ValueError("a physical shard requires a containing group")
        return self

    @property
    def coordinate_key(self) -> ContentHash:
        return sha256_digest(self.stable_json_bytes())


class OperationRun(V2Contract):
    """Durable execution authority for one real bounded operation.

    A component may perform external work only after the Work head points at a
    ``running`` revision. Terminal revisions bind the exact execution record
    and settled lease, so recovery adopts evidence instead of replaying work.
    """

    operation_run_id: Identifier
    attempt_id: Identifier
    coordinate: WorkCoordinate
    kind: OperationKind
    ordinal: Annotated[int, Field(ge=1)]
    revision: Annotated[int, Field(ge=1)]
    policy_id: Identifier
    policy_digest: ContentHash
    operation: Identifier
    replay_mode: ReplayMode
    status: OperationRunStatus
    input_refs: tuple[ArtifactRef, ...] = ()
    budget_lease_ref: ArtifactRef
    dispatch_id: Identifier | None = None
    backend_handle_commitment: ContentHash | None = None
    execution_ref: ArtifactRef | None = None
    output_refs: tuple[ArtifactRef, ...] = ()
    observed_actual: BudgetUsage = Field(default_factory=BudgetUsage)
    unknown_upper_bound: BudgetUsage = Field(default_factory=BudgetUsage)
    conservative_committed: BudgetUsage = Field(default_factory=BudgetUsage)
    error_code: Identifier | None = None
    scheduled_at: AwareDatetime
    started_at: AwareDatetime | None = None
    finished_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def validate_lifecycle(self) -> OperationRun:
        if _duplicates(self.input_refs) or _duplicates(self.output_refs):
            raise ValueError("OperationRun input/output refs must be unique")
        if set(self.input_refs) & set(self.output_refs):
            raise ValueError("OperationRun output cannot also be an immutable input")
        if self.budget_lease_ref.artifact_type != "control.budget_lease":
            raise ValueError("OperationRun requires an exact BudgetLease")
        expected_execution_type = {
            "proposal": "control.proposal_execution",
            "validation": "control.validation_execution",
            "assurance": "control.assurance_execution",
        }[self.kind]
        if self.status == "scheduled":
            if any(
                value is not None
                for value in (
                    self.dispatch_id,
                    self.backend_handle_commitment,
                    self.execution_ref,
                    self.started_at,
                    self.finished_at,
                )
            ):
                raise ValueError("scheduled OperationRun has not started")
            if self.output_refs or self.error_code is not None:
                raise ValueError("scheduled OperationRun cannot claim a result")
        elif self.status == "running":
            if (
                self.dispatch_id is None
                or self.started_at is None
                or self.execution_ref is not None
                or self.finished_at is not None
            ):
                raise ValueError("running OperationRun requires dispatch identity and start time")
            if self.output_refs or self.error_code is not None:
                raise ValueError("running OperationRun cannot claim a terminal result")
        else:
            if (
                self.dispatch_id is None
                or self.started_at is None
                or self.execution_ref is None
                or self.finished_at is None
            ):
                raise ValueError(
                    "terminal OperationRun requires dispatch, execution, and timestamps"
                )
            if self.execution_ref.artifact_type != expected_execution_type:
                raise ValueError("OperationRun execution ref does not match its kind")
        expected_usage = BudgetUsage.model_validate(
            {
                field_name: getattr(self.observed_actual, field_name)
                + getattr(self.unknown_upper_bound, field_name)
                for field_name in BudgetUsage.model_fields
                if field_name != "schema_version"
            }
        )
        if self.conservative_committed != expected_usage:
            raise ValueError("OperationRun usage must equal actual plus unknown")
        if self.status != "terminal" and self.conservative_committed != BudgetUsage():
            raise ValueError("non-terminal OperationRun cannot claim usage")
        if self.started_at is not None and self.started_at < self.scheduled_at:
            raise ValueError("OperationRun cannot start before scheduling")
        if self.finished_at is not None and (
            self.started_at is None or self.finished_at < self.started_at
        ):
            raise ValueError("OperationRun cannot finish before starting")
        return self


class ProposalPolicy(V2Contract):
    """Who may produce a proposal and the exact capability/budget envelope."""

    policy_id: Identifier
    executor: ProposalExecutor
    # ``executor_revision_id`` is the backend CAPABILITY contract: the backend
    # must prove it speaks this structured-protocol version.  It is NOT the
    # version of the leaf implementation code, and must not be overloaded for
    # cache invalidation.  ``implementation_revision_id`` is that separate
    # acceptance-critical fact: the version of the in-tree leaf code (and, for
    # Agent proposals, the model identity) that produced an output.  Editing a
    # leaf's code bumps this id, which flows into ``acceptance_digest`` so a
    # historical commit produced by stale code is never silently reused.
    executor_revision_id: Identifier = "framework.executor.v1"
    implementation_revision_id: Identifier = "framework.impl.unversioned.v0"
    operation: Identifier
    budget: OperationBudget
    # Replay authority is a property of the real operation, not a property of
    # the generic leaf kernel.  Scheduler recovery uses this immutable policy
    # to distinguish a query that may be repeated from an Agent/codegen turn
    # whose interrupted outcome must remain terminal.
    replay_mode: ReplayMode = "non_replayable"
    # A long-running Agent session may span several Provider-owned physical
    # turns.  The normal OperationBudget still reserves exactly one physical
    # turn; these two fields declare the immutable logical session envelope
    # used to materialize and resume the same Provider session.
    session_token_limit: Annotated[int, Field(ge=1)] | None = None
    session_wall_seconds: Annotated[float, Field(gt=0)] | None = None
    agent_role: AgentRole | None = None
    capability_profile_id: Identifier | None = None
    output_contract_id: Identifier | None = None
    acceptance_transform_id: Identifier | None = None
    tool_ids: tuple[Identifier, ...] = ()

    @model_validator(mode="after")
    def validate_executor_authority(self) -> ProposalPolicy:
        if _duplicates(self.tool_ids):
            raise ValueError("proposal tool ids must be unique")
        if self.executor == "agent":
            if (
                self.agent_role is None
                or self.capability_profile_id is None
                or self.output_contract_id is None
            ):
                raise ValueError(
                    "Agent proposal requires role, capability profile, and output contract"
                )
            if self.budget.agent_turns < 1 or self.budget.llm_tokens < 1:
                raise ValueError("Agent proposal requires numeric turn and token limits")
            if (self.session_token_limit is None) != (self.session_wall_seconds is None):
                raise ValueError("Agent logical session token and wall limits must be declared together")
            if self.session_token_limit is not None and (
                self.session_token_limit < self.budget.llm_tokens
                or self.session_wall_seconds is None
                or self.session_wall_seconds < self.budget.wall_seconds
            ):
                raise ValueError(
                    "Agent logical session envelope cannot be smaller than one physical turn"
                )
        elif self.agent_role is not None or self.output_contract_id is not None:
            raise ValueError("non-Agent proposal cannot declare Agent role/output contract")
        elif self.session_token_limit is not None or self.session_wall_seconds is not None:
            raise ValueError("non-Agent proposal cannot declare a logical Agent session envelope")
        if self.executor != "agent" and self.acceptance_transform_id is not None:
            raise ValueError("only an Agent proposal may declare an acceptance transform")
        if self.executor == "real_tools" and (
            not self.tool_ids or self.capability_profile_id is None
        ):
            raise ValueError(
                "real-tools proposal requires registered tools and a capability profile"
            )
        if self.executor != "real_tools" and self.tool_ids:
            raise ValueError("only a real-tools proposal may declare tool ids")
        if self.executor == "code" and self.capability_profile_id is not None:
            raise ValueError("in-process code proposal cannot declare a capability profile")
        if self.executor == "code" and (
            self.budget.agent_turns or self.budget.llm_tokens or self.budget.search_calls
        ):
            raise ValueError("code proposal cannot reserve Agent or search capacity")
        return self


class ValidationPolicy(V2Contract):
    """Framework-owned deterministic validation and its boundary effect."""

    policy_id: Identifier
    validator_id: Identifier
    validator_revision_id: Identifier
    validation_phase: Identifier
    frontier_ordinal: Annotated[int, Field(ge=0)]
    claim_id: Identifier
    effect: ValidationEffect
    budget: OperationBudget
    require_actionable_diagnostics: bool = True

    @model_validator(mode="after")
    def deterministic_budget_only(self) -> ValidationPolicy:
        if (
            self.budget.llm_tokens
            or self.budget.agent_turns
            or self.budget.search_calls
            or self.budget.evaluation_episodes
        ):
            raise ValueError(
                "deterministic validation cannot reserve Agent, search, or episode capacity"
            )
        return self


class AssurancePolicy(V2Contract):
    """Real-execution probes kept separate from deterministic validation."""

    policy_id: Identifier
    runtime_profile_id: Identifier
    probe_ids: Annotated[tuple[Identifier, ...], Field(min_length=1)]
    claim_id: Identifier
    effect: ValidationEffect
    budget: OperationBudget
    evidence_freshness: Literal["same_attempt", "same_candidate", "fresh_deployment"]

    @model_validator(mode="after")
    def real_execution_budget(self) -> AssurancePolicy:
        if _duplicates(self.probe_ids):
            raise ValueError("assurance probe ids must be unique")
        if self.budget.process_calls < 1:
            raise ValueError("real-execution assurance requires a process-call limit")
        if self.budget.llm_tokens or self.budget.agent_turns or self.budget.search_calls:
            raise ValueError("real-execution assurance cannot hide Agent/search work")
        return self


class RepairPolicy(V2Contract):
    """The single executable semantic/infrastructure retry policy for one work item."""

    policy_id: Identifier
    policy_revision_id: Identifier = "framework.repair-authority.v1"
    maximum_local_corrections: Annotated[int, Field(ge=0, le=1)] = 1
    strict_progress_bonus_corrections: Annotated[int, Field(ge=0, le=1)] = 1
    maximum_infrastructure_retries: Annotated[int, Field(ge=0)] = 1
    # Provider output ceilings are neither semantic corrections nor transient
    # infrastructure retries.  This count is derived from the declared logical
    # session envelope and the physical-turn reservation; it is separately
    # metered by Agent/token/wall budgets rather than repair_attempts.
    maximum_session_continuations: Annotated[int, Field(ge=0)] = 0
    maximum_process_recoveries: Annotated[int, Field(ge=0, le=2)] = 2
    maximum_automatic_backjump: Annotated[int, Field(ge=0, le=1)] = 0
    maximum_total_repair_attempts: Annotated[int, Field(ge=0)] = 3
    require_causal_evidence_for_parent: Literal[True] = True
    insufficient_diagnostic_action: Literal["terminal"] = "terminal"
    no_progress_action: Literal["terminal"] = "terminal"
    oscillation_action: Literal["terminal"] = "terminal"

    @model_validator(mode="after")
    def validate_single_limit(self) -> RepairPolicy:
        semantic_limit = self.maximum_local_corrections + self.strict_progress_bonus_corrections
        if semantic_limit > self.maximum_total_repair_attempts:
            raise ValueError("semantic correction allowance exceeds total repair attempts")
        if self.maximum_infrastructure_retries > self.maximum_total_repair_attempts:
            raise ValueError("infrastructure retry allowance exceeds total repair attempts")
        if (
            semantic_limit + self.maximum_infrastructure_retries
            > self.maximum_total_repair_attempts
        ):
            raise ValueError("semantic and infrastructure allowances exceed total repair attempts")
        if self.maximum_infrastructure_retries > self.maximum_total_repair_attempts:
            raise ValueError("infrastructure retry allowance exceeds total repair attempts")
        if self.maximum_local_corrections == 0 and self.strict_progress_bonus_corrections:
            raise ValueError("a progress bonus requires an initial local correction")
        if self.maximum_automatic_backjump and self.maximum_total_repair_attempts == 0:
            raise ValueError("a backjump requires a non-zero repair allowance")
        return self


class WorkDefinition(V2Contract):
    """Static executable policy for one logical or physical WorkGraph item."""

    work_id: Identifier
    coordinate: WorkCoordinate
    claim: Annotated[NonEmptyStr, Field(max_length=512)]
    timing_reason: Annotated[NonEmptyStr, Field(max_length=512)]
    dependency_coordinates: tuple[WorkCoordinate, ...] = ()
    repair_target_coordinates: tuple[WorkCoordinate, ...] = ()
    input_slots: tuple[ArtifactSlotContract, ...] = ()
    output_slots: tuple[ArtifactSlotContract, ...] = ()
    proposal_policy: ProposalPolicy
    validation_policy: ValidationPolicy
    assurance_policy: AssurancePolicy | None = None
    repair_policy: RepairPolicy
    required_claim_id: Identifier
    allowed_mutation_roots: tuple[NonEmptyStr, ...] = ()
    invalidation_rule: Literal["descendants"] = "descendants"
    success_maturity: Identifier

    @model_validator(mode="after")
    def validate_definition(self) -> WorkDefinition:
        dependency_keys = tuple(item.coordinate_key for item in self.dependency_coordinates)
        if _duplicates(dependency_keys):
            raise ValueError("work dependencies must be unique")
        repair_target_keys = tuple(item.coordinate_key for item in self.repair_target_coordinates)
        if _duplicates(repair_target_keys):
            raise ValueError("work repair targets must be unique")
        if self.coordinate.coordinate_key in dependency_keys:
            raise ValueError("work cannot depend on its own output coordinate")
        if self.coordinate.coordinate_key in repair_target_keys:
            raise ValueError("local repair is implicit and cannot be a repair target edge")
        if _duplicates(self.allowed_mutation_roots):
            raise ValueError("work mutation roots must be unique")
        slots = (*self.input_slots, *self.output_slots)
        if _duplicates(tuple(item.slot_id for item in slots)):
            raise ValueError("WorkDefinition Artifact slot ids must be unique")
        if any(item.direction != "input" for item in self.input_slots):
            raise ValueError("WorkDefinition input_slots must have input direction")
        if any(item.direction != "output" for item in self.output_slots):
            raise ValueError("WorkDefinition output_slots must have output direction")
        for direction_slots in (self.input_slots, self.output_slots):
            declared_types = tuple(
                artifact_type for item in direction_slots for artifact_type in item.artifact_types
            )
            if _duplicates(declared_types):
                raise ValueError("Artifact types cannot be ambiguously assigned to multiple slots")
        dependency_components = {dependency.component for dependency in self.dependency_coordinates}
        if any(
            item.producer_component != "external"
            and item.producer_component not in dependency_components
            for item in self.input_slots
        ):
            raise ValueError(
                "input Artifact producer must be represented by a dependency component"
            )
        if any(item.producer_component != self.coordinate.component for item in self.output_slots):
            raise ValueError("output Artifact slot owner must match Work coordinate component")
        mutation_repair = (
            self.repair_policy.maximum_local_corrections
            or self.repair_policy.strict_progress_bonus_corrections
            or self.repair_policy.maximum_automatic_backjump
            or self.repair_policy.maximum_session_continuations
        )
        if bool(mutation_repair) != bool(self.allowed_mutation_roots):
            raise ValueError(
                "mutable repair/continuation policy and allowed mutation roots must be declared together"
            )
        if bool(self.repair_target_coordinates) != bool(
            self.repair_policy.maximum_automatic_backjump
        ):
            raise ValueError(
                "parent repair targets and automatic backjump authority must be declared together"
            )
        if self.validation_policy.claim_id != self.required_claim_id:
            raise ValueError("validation policy must evaluate the WorkDefinition claim")
        if (
            self.assurance_policy is not None
            and self.assurance_policy.claim_id != self.required_claim_id
        ):
            raise ValueError("assurance policy must evaluate the WorkDefinition claim")
        return self

    @property
    def definition_digest(self) -> ContentHash:
        return self.content_digest()

    @property
    def acceptance_digest(self) -> ContentHash:
        """Identity of the contract an already-passing output must still satisfy.

        Execution budgets, repair routing, timing prose, and mutation authority
        affect future attempts but cannot retroactively invalidate a successful
        immutable output.  Validator, output transformation, topology, Claim,
        assurance, and maturity remain acceptance-critical.
        """

        validation = self.validation_policy
        assurance = self.assurance_policy
        return sha256_digest(
            canonical_json_bytes(
                {
                    "protocol": "framework.work-acceptance.v1",
                    "work_id": self.work_id,
                    "coordinate": self.coordinate.model_dump(mode="json"),
                    "claim": self.claim,
                    "dependency_coordinates": tuple(
                        item.model_dump(mode="json") for item in self.dependency_coordinates
                    ),
                    "input_slots": tuple(item.model_dump(mode="json") for item in self.input_slots),
                    "output_slots": tuple(
                        item.model_dump(mode="json") for item in self.output_slots
                    ),
                    "output_contract_id": self.proposal_policy.output_contract_id,
                    "acceptance_transform_id": (self.proposal_policy.acceptance_transform_id),
                    "implementation_revision_id": (self.proposal_policy.implementation_revision_id),
                    "tool_ids": self.proposal_policy.tool_ids,
                    "validation": {
                        "validator_id": validation.validator_id,
                        "validator_revision_id": validation.validator_revision_id,
                        "validation_phase": validation.validation_phase,
                        "frontier_ordinal": validation.frontier_ordinal,
                        "claim_id": validation.claim_id,
                        "effect": validation.effect,
                        "require_actionable_diagnostics": (
                            validation.require_actionable_diagnostics
                        ),
                    },
                    "assurance": (
                        None
                        if assurance is None
                        else {
                            "runtime_profile_id": assurance.runtime_profile_id,
                            "probe_ids": assurance.probe_ids,
                            "claim_id": assurance.claim_id,
                            "effect": assurance.effect,
                            "evidence_freshness": assurance.evidence_freshness,
                        }
                    ),
                    "required_claim_id": self.required_claim_id,
                    "invalidation_rule": self.invalidation_rule,
                    "success_maturity": self.success_maturity,
                }
            )
        )


def repair_epoch_digest(
    definition: WorkDefinition,
    input_refs: tuple[ArtifactRef, ...],
) -> ContentHash:
    """Scope every repair decision to one exact definition/input epoch."""

    return sha256_digest(
        canonical_json_bytes(
            {
                "work_id": definition.work_id,
                "coordinate": definition.coordinate.model_dump(mode="json"),
                "definition_digest": definition.definition_digest,
                "input_fingerprint": work_input_fingerprint(input_refs),
                "validation_policy_digest": (definition.validation_policy.content_digest()),
                "repair_policy_digest": definition.repair_policy.content_digest(),
            }
        )
    )


class ProposalExecution(V2Contract):
    """Public commitment to one real proposal execution, never its raw transcript."""

    execution_id: Identifier
    attempt_id: Identifier
    executor: ProposalExecutor
    executor_revision_id: Identifier = "framework.executor.v1"
    operation: Identifier
    status: ProposalExecutionStatus
    invocation_id: Identifier | None = None
    provider: Identifier | None = None
    model: NonEmptyStr | None = None
    profile_digest: ContentHash | None = None
    output_schema_digest: ContentHash | None = None
    output_commitment: ContentHash | None = None
    continuation_commitment: ContentHash | None = None
    error_code: Identifier | None = None
    observed_actual: BudgetUsage = Field(default_factory=BudgetUsage)
    unknown_upper_bound: BudgetUsage = Field(default_factory=BudgetUsage)
    conservative_committed: BudgetUsage = Field(default_factory=BudgetUsage)
    started_at: AwareDatetime
    finished_at: AwareDatetime
    duration_ms: Annotated[int, Field(ge=0)]

    @model_validator(mode="after")
    def validate_execution_evidence(self) -> ProposalExecution:
        if self.finished_at < self.started_at:
            raise ValueError("proposal execution cannot finish before it starts")
        if self.status == "completed":
            if self.output_commitment is None or self.error_code is not None:
                raise ValueError("completed proposal requires output commitment and no error")
        elif self.error_code is None:
            raise ValueError("non-completed proposal requires a stable error code")
        agent_fields = (
            self.invocation_id,
            self.provider,
            self.model,
            self.profile_digest,
            self.output_schema_digest,
        )
        agent_preflight_failure = (
            self.executor == "agent"
            and self.status != "completed"
            and self.error_code is not None
            and self.error_code.startswith("preflight_")
        )
        # A process can disappear after the dispatch fence but before the SDK
        # returns invocation/profile provenance.  Preserve it as an explicit
        # interrupted unknown rather than fabricating a provider/session id.
        agent_interrupted_before_provenance = (
            self.executor == "agent"
            and self.status == "interrupted"
            and self.error_code is not None
            and self.error_code.startswith("process_interrupted")
        )
        if self.executor == "agent" and any(value is None for value in agent_fields):
            if not (agent_preflight_failure or agent_interrupted_before_provenance) or any(
                value is not None for value in agent_fields
            ):
                raise ValueError(
                    "Agent execution requires invocation/profile/model/schema evidence "
                    "unless framework preflight stopped before dispatch"
                )
        if self.executor != "agent" and any(value is not None for value in agent_fields):
            raise ValueError("non-Agent execution cannot claim Agent invocation evidence")
        expected = {
            field_name: getattr(self.observed_actual, field_name)
            + getattr(self.unknown_upper_bound, field_name)
            for field_name in BudgetUsage.model_fields
            if field_name != "schema_version"
        }
        if self.conservative_committed != BudgetUsage.model_validate(expected):
            raise ValueError("proposal conservative usage must equal actual plus unknown")
        return self


class ValidationExecution(V2Contract):
    """Measured deterministic validator execution, separate from its report."""

    execution_id: Identifier
    attempt_id: Identifier
    policy_id: Identifier
    validator_id: Identifier
    validator_revision_id: Identifier
    status: BoundaryExecutionStatus
    evidence_refs: tuple[ArtifactRef, ...] = ()
    error_code: Identifier | None = None
    observed_actual: BudgetUsage = Field(default_factory=BudgetUsage)
    unknown_upper_bound: BudgetUsage = Field(default_factory=BudgetUsage)
    conservative_committed: BudgetUsage = Field(default_factory=BudgetUsage)
    started_at: AwareDatetime
    finished_at: AwareDatetime
    duration_ms: Annotated[int, Field(ge=0)]

    @model_validator(mode="after")
    def validate_execution(self) -> ValidationExecution:
        if self.finished_at < self.started_at:
            raise ValueError("validation execution cannot finish before it starts")
        if _duplicates(self.evidence_refs):
            raise ValueError("validation execution evidence refs must be unique")
        if self.status == "completed":
            if self.error_code is not None:
                raise ValueError("completed validation cannot carry an error code")
        elif self.error_code is None:
            raise ValueError("non-completed validation requires an error code")
        expected = BudgetUsage.model_validate(
            {
                field_name: getattr(self.observed_actual, field_name)
                + getattr(self.unknown_upper_bound, field_name)
                for field_name in BudgetUsage.model_fields
                if field_name != "schema_version"
            }
        )
        if self.conservative_committed != expected:
            raise ValueError("validation usage must equal actual plus unknown")
        return self


class AssuranceExecution(V2Contract):
    """Measured real probe execution with freshness and runtime identity."""

    execution_id: Identifier
    attempt_id: Identifier
    policy_id: Identifier
    runtime_profile_id: Identifier
    probe_ids: Annotated[tuple[Identifier, ...], Field(min_length=1)]
    evidence_freshness: Literal["same_attempt", "same_candidate", "fresh_deployment"]
    status: BoundaryExecutionStatus
    evidence_refs: tuple[ArtifactRef, ...] = ()
    runtime_commitment: ContentHash
    error_code: Identifier | None = None
    observed_actual: BudgetUsage = Field(default_factory=BudgetUsage)
    unknown_upper_bound: BudgetUsage = Field(default_factory=BudgetUsage)
    conservative_committed: BudgetUsage = Field(default_factory=BudgetUsage)
    started_at: AwareDatetime
    finished_at: AwareDatetime
    duration_ms: Annotated[int, Field(ge=0)]

    @model_validator(mode="after")
    def validate_execution(self) -> AssuranceExecution:
        if self.finished_at < self.started_at:
            raise ValueError("assurance execution cannot finish before it starts")
        if _duplicates(self.probe_ids) or _duplicates(self.evidence_refs):
            raise ValueError("assurance probes and evidence refs must be unique")
        if self.status == "completed":
            if not self.evidence_refs or self.error_code is not None:
                raise ValueError("completed assurance requires real evidence and no error code")
        elif self.error_code is None:
            raise ValueError("non-completed assurance requires an error code")
        expected = BudgetUsage.model_validate(
            {
                field_name: getattr(self.observed_actual, field_name)
                + getattr(self.unknown_upper_bound, field_name)
                for field_name in BudgetUsage.model_fields
                if field_name != "schema_version"
            }
        )
        if self.conservative_committed != expected:
            raise ValueError("assurance usage must equal actual plus unknown")
        return self


class AssuranceProbeResult(V2Contract):
    """Framework-derived verdict for one exact real-execution probe."""

    probe_id: Identifier
    status: Literal["passed", "failed", "inconclusive", "error"]
    evidence_refs: Annotated[tuple[ArtifactRef, ...], Field(min_length=1)]
    issue_codes: tuple[Identifier, ...] = ()
    duration_ms: Annotated[int, Field(ge=0)] = 0

    @model_validator(mode="after")
    def validate_probe_verdict(self) -> AssuranceProbeResult:
        if _duplicates(self.evidence_refs) or _duplicates(self.issue_codes):
            raise ValueError("assurance probe evidence and issue codes must be unique")
        if self.status == "passed" and self.issue_codes:
            raise ValueError("passing assurance probe cannot carry issue codes")
        if self.status != "passed" and not self.issue_codes:
            raise ValueError("non-passing assurance probe requires stable issue codes")
        return self


class AssuranceReport(V2Contract):
    """Exact per-probe verdict; execution completion alone never proves a Claim."""

    report_id: Identifier
    attempt_id: Identifier
    coordinate: WorkCoordinate
    policy_id: Identifier
    policy_digest: ContentHash
    runtime_profile_id: Identifier
    runtime_commitment: ContentHash
    evidence_freshness: Literal["same_attempt", "same_candidate", "fresh_deployment"]
    probe_results: Annotated[tuple[AssuranceProbeResult, ...], Field(min_length=1)]
    status: Literal["passed", "failed", "inconclusive", "error"]
    evaluated_at: AwareDatetime

    @model_validator(mode="after")
    def derive_assurance_status(self) -> AssuranceReport:
        probe_ids = tuple(item.probe_id for item in self.probe_results)
        if _duplicates(probe_ids):
            raise ValueError("assurance report probe ids must be unique")
        statuses = {item.status for item in self.probe_results}
        expected: Literal["passed", "failed", "inconclusive", "error"] = (
            "error"
            if "error" in statuses
            else "failed"
            if "failed" in statuses
            else "inconclusive"
            if "inconclusive" in statuses
            else "passed"
        )
        if self.status != expected:
            raise ValueError("assurance report status is not derived from probe verdicts")
        return self

    @property
    def evidence_refs(self) -> tuple[ArtifactRef, ...]:
        return tuple(
            dict.fromkeys(ref for result in self.probe_results for ref in result.evidence_refs)
        )


class ValidationIssue(V2Contract):
    """Safe field-addressable deterministic diagnostic with no rejected value."""

    code: Identifier
    path: Annotated[tuple[str | int, ...], Field(min_length=1)]
    violated_condition: Annotated[NonEmptyStr, Field(max_length=512)]
    expected_category: Annotated[NonEmptyStr, Field(max_length=512)]
    # ``remediation`` is framework-authored safe guidance, never a rejected
    # model value.  It lets a later authorized correction distinguish the
    # concrete next edit from the durable condition/expectation identity.
    remediation: Annotated[NonEmptyStr, Field(max_length=512)] | None = None
    severity: Literal["warning", "blocker"] = "blocker"
    retryable: bool = True

    @model_validator(mode="after")
    def validate_safe_path(self) -> ValidationIssue:
        for part in self.path:
            if isinstance(part, str) and (not part or len(part) > 80):
                raise ValueError("validation issue path parts must contain 1-80 characters")
            if isinstance(part, int) and part < 0:
                raise ValueError("validation issue array indices cannot be negative")
        return self

    @property
    def actionable(self) -> bool:
        root_only = len(self.path) == 1 and str(self.path[0]).lower() in _GENERIC_ROOT_PARTS
        return self.retryable and self.code not in _GENERIC_ISSUE_CODES and not root_only

    @property
    def informative(self) -> bool:
        """Whether feedback names one safe next debugging route without authorizing repair.

        A non-retryable external terminal can still be enough for a Code Agent
        to act on: it may direct an adapter, profile, Provider, or observability
        change while explicitly forbidding an in-attempt Agent correction.  Do
        not label that case ``insufficient`` merely because Scheduler cannot
        spend another turn.  Framework-authored remediation is the deliberate
        proof that the feedback identifies a bounded next action.
        """

        return self.actionable or (
            self.code not in _GENERIC_ISSUE_CODES and self.remediation is not None
        )

    @property
    def normalized_identity(self) -> ContentHash:
        return sha256_digest(
            canonical_json_bytes(
                {
                    "code": self.code,
                    "path": self.path,
                    "expected_category": self.expected_category,
                    "severity": self.severity,
                }
            )
        )


def diagnostic_quality_for_issues(
    *,
    status: ValidationStatus,
    issues: tuple[ValidationIssue, ...],
) -> DiagnosticQuality:
    """Derive diagnostic quality independently from repair authority."""

    if status == "passed":
        return "not_applicable"
    blockers = tuple(issue for issue in issues if issue.severity == "blocker")
    if blockers and all(issue.actionable for issue in blockers):
        return "actionable"
    if blockers and all(issue.informative for issue in blockers):
        return "informative"
    return "insufficient"


class ValidationReport(V2Contract):
    """All leaf diagnostics for one attempt and validation-policy revision."""

    report_id: Identifier
    attempt_id: Identifier
    coordinate: WorkCoordinate
    policy_id: Identifier
    policy_digest: ContentHash
    subject_refs: tuple[ArtifactRef, ...] = ()
    status: ValidationStatus
    validation_phase: Identifier
    frontier_ordinal: Annotated[int, Field(ge=0)]
    passed_check_ids: tuple[Identifier, ...] = ()
    issues: tuple[ValidationIssue, ...] = ()
    evidence_refs: tuple[ArtifactRef, ...] = ()
    diagnostic_quality: DiagnosticQuality
    # A diagnostic run may execute the same validator against real inputs, but
    # its report is never release evidence.  Keep that fact on the report
    # itself rather than relying on a CLI-only label that can be lost when the
    # report is consumed by a later control-plane reader.
    diagnostic_only: bool = False
    releasable: bool = True
    evaluated_at: AwareDatetime

    @model_validator(mode="after")
    def validate_report(self) -> ValidationReport:
        if _duplicates(self.subject_refs):
            raise ValueError("validated subject refs must be unique")
        if _duplicates(self.passed_check_ids):
            raise ValueError("passed validation check ids must be unique")
        if _duplicates(tuple(item.normalized_identity for item in self.issues)):
            raise ValueError("validation issues must be unique")
        if _duplicates(self.evidence_refs):
            raise ValueError("validation evidence refs must be unique")
        blockers = tuple(item for item in self.issues if item.severity == "blocker")
        if self.status == "passed":
            if blockers:
                raise ValueError("passed validation report cannot contain blockers")
            if not self.subject_refs:
                raise ValueError("passed validation report must bind validated subjects")
        else:
            if self.status == "failed" and not blockers:
                raise ValueError("failed validation report requires at least one blocker")
            if not self.issues and not self.evidence_refs:
                raise ValueError("non-passing validation requires diagnostics or evidence")
        expected_quality = diagnostic_quality_for_issues(
            status=self.status,
            issues=self.issues,
        )
        if self.diagnostic_quality != expected_quality:
            raise ValueError("diagnostic quality is not the framework-derived value")
        if self.diagnostic_only and self.releasable:
            raise ValueError("diagnostic validation reports are never releasable")
        return self

    @property
    def blocking_issue_ids(self) -> tuple[ContentHash, ...]:
        return tuple(
            sorted(
                issue.normalized_identity for issue in self.issues if issue.severity == "blocker"
            )
        )

    @property
    def repair_actionable(self) -> bool:
        return self.status == "failed" and self.diagnostic_quality == "actionable"

    @property
    def infrastructure_retryable(self) -> bool:
        """Whether this typed execution error permits one Scheduler retry.

        An opaque error report is deliberately not retryable.  Otherwise a
        generic provider failure could consume another complete tool or Agent
        envelope merely because its status happened to be ``error``.
        """

        blockers = tuple(issue for issue in self.issues if issue.severity == "blocker")
        return (
            self.status == "error" and bool(blockers) and all(issue.retryable for issue in blockers)
        )

    @property
    def progress_state_digest(self) -> ContentHash:
        return sha256_digest(
            canonical_json_bytes(
                {
                    "coordinate": self.coordinate,
                    "policy_digest": self.policy_digest,
                    "phase": self.validation_phase,
                    "frontier": self.frontier_ordinal,
                    "blockers": self.blocking_issue_ids,
                }
            )
        )


class FeedbackEvaluation(V2Contract):
    """Unique boundary terminal; reports themselves never authorize readiness or repair."""

    evaluation_id: Identifier
    attempt_id: Identifier
    work_id: Identifier
    coordinate: WorkCoordinate
    claim_id: Identifier
    acceptance_digest: ContentHash
    policy_digest: ContentHash
    status: EvaluationStatus
    effect: ValidationEffect
    readiness_effect: ReadinessEffect
    subject_refs: tuple[ArtifactRef, ...] = ()
    validation_report_ref: ArtifactRef | None = None
    assurance_report_ref: ArtifactRef | None = None
    assurance_evidence_refs: tuple[ArtifactRef, ...] = ()
    supersedes_ref: ArtifactRef | None = None
    invalidated_by_refs: tuple[ArtifactRef, ...] = ()
    diagnostic_only: bool = False
    releasable: bool = True
    evaluated_at: AwareDatetime

    @model_validator(mode="after")
    def validate_boundary_authority(self) -> FeedbackEvaluation:
        if _duplicates(self.subject_refs):
            raise ValueError("boundary subject refs must be unique")
        if _duplicates(self.assurance_evidence_refs):
            raise ValueError("assurance evidence refs must be unique")
        if _duplicates(self.invalidated_by_refs):
            raise ValueError("invalidating Artifact refs must be unique")
        if (
            self.validation_report_ref is not None
            and self.validation_report_ref.artifact_type != "control.validation_report"
        ):
            raise ValueError("boundary validation_report_ref has the wrong Artifact type")
        if (
            self.assurance_report_ref is not None
            and self.assurance_report_ref.artifact_type != "control.assurance_report"
        ):
            raise ValueError("boundary assurance_report_ref has the wrong Artifact type")
        if (
            self.supersedes_ref is not None
            and self.supersedes_ref.artifact_type != "control.feedback_evaluation"
        ):
            raise ValueError("boundary supersedes_ref has the wrong Artifact type")
        if self.diagnostic_only and self.releasable:
            raise ValueError("diagnostic evaluations are never releasable")
        if self.status in {"passed", "failed", "inconclusive", "error"} and not (
            self.validation_report_ref or self.assurance_report_ref
        ):
            raise ValueError("evaluated boundary requires a report or assurance evidence")
        if self.status == "passed" and not self.subject_refs:
            raise ValueError("passed boundary must bind the exact subject closure")
        if self.status == "invalidated":
            if not self.invalidated_by_refs:
                raise ValueError("invalidated boundary requires invalidating Artifacts")
        elif self.invalidated_by_refs:
            raise ValueError("only invalidated boundary can bind invalidating Artifacts")

        if self.status == "invalidated":
            expected_readiness: ReadinessEffect = "invalidates"
        elif self.diagnostic_only or self.effect == "observe":
            expected_readiness = "observes"
        elif self.status == "passed":
            expected_readiness = "satisfies"
        else:
            expected_readiness = "blocks"
        if self.readiness_effect != expected_readiness:
            raise ValueError("readiness effect is not derived from status and boundary policy")
        return self


class WorkAttempt(V2Contract):
    """One scheduled execution with exact policy digests and terminal evidence."""

    attempt_id: Identifier
    work_id: Identifier
    coordinate: WorkCoordinate
    ordinal: Annotated[int, Field(ge=1)]
    parent_attempt_id: Identifier | None = None
    status: Literal[
        "scheduled",
        "running",
        "succeeded",
        "failed",
        "interrupted",
        "cancelled",
        "budget_exhausted",
        "needs_human",
    ]
    definition_digest: ContentHash
    proposal_policy_digest: ContentHash
    validation_policy_digest: ContentHash
    assurance_policy_digest: ContentHash | None = None
    repair_policy_digest: ContentHash
    telemetry_trace_id: Identifier | None = None
    telemetry_span_id: Identifier | None = None
    operation_run_refs: tuple[ArtifactRef, ...] = ()
    input_refs: tuple[ArtifactRef, ...] = ()
    output_refs: tuple[ArtifactRef, ...] = ()
    child_commit_refs: tuple[ArtifactRef, ...] = ()
    assurance_report_ref: ArtifactRef | None = None
    validation_report_ref: ArtifactRef | None = None
    feedback_evaluation_ref: ArtifactRef | None = None
    repair_action_ref: ArtifactRef | None = None
    repair_attempt_charge: Annotated[int, Field(ge=0, le=1)] = 0
    recovery_ordinal: Annotated[int, Field(ge=0, le=2)] = 0
    recovery_reason_code: Identifier | None = None
    continuation_commitment: ContentHash | None = None
    observed_actual: BudgetUsage = Field(default_factory=BudgetUsage)
    unknown_upper_bound: BudgetUsage = Field(default_factory=BudgetUsage)
    conservative_committed: BudgetUsage = Field(default_factory=BudgetUsage)
    scheduled_at: AwareDatetime
    started_at: AwareDatetime | None = None
    first_progress_at: AwareDatetime | None = None
    first_write_at: AwareDatetime | None = None
    finished_at: AwareDatetime | None = None
    failure_code: Identifier | None = None
    diagnostic_only: bool = False
    releasable: bool = True

    @model_validator(mode="after")
    def validate_lifecycle(self) -> WorkAttempt:
        if (self.telemetry_trace_id is None) != (self.telemetry_span_id is None):
            raise ValueError("WorkAttempt telemetry trace and span must be declared together")
        if (
            _duplicates(self.input_refs)
            or _duplicates(self.output_refs)
            or _duplicates(self.child_commit_refs)
            or _duplicates(self.operation_run_refs)
        ):
            raise ValueError("work attempt input/output refs must be unique")
        if any(item.artifact_type != "control.work_commit" for item in self.child_commit_refs):
            raise ValueError("work attempt child refs must be WorkCommit Artifacts")
        if set(self.input_refs) & set(self.output_refs):
            raise ValueError("work attempt output cannot also be an immutable input")
        if (
            self.validation_report_ref is not None
            and self.validation_report_ref.artifact_type != "control.validation_report"
        ):
            raise ValueError("work attempt validation_report_ref has the wrong Artifact type")
        if (
            self.feedback_evaluation_ref is not None
            and self.feedback_evaluation_ref.artifact_type != "control.feedback_evaluation"
        ):
            raise ValueError("work attempt evaluation ref has the wrong Artifact type")
        if any(item.artifact_type != "control.operation_run" for item in self.operation_run_refs):
            raise ValueError("work attempt operation refs have the wrong Artifact type")
        if (
            self.assurance_report_ref is not None
            and self.assurance_report_ref.artifact_type != "control.assurance_report"
        ):
            raise ValueError("work attempt assurance report ref has the wrong type")
        if (
            self.repair_action_ref is not None
            and self.repair_action_ref.artifact_type != "control.repair_action"
        ):
            raise ValueError("work attempt repair action ref has the wrong Artifact type")
        if self.repair_attempt_charge and self.repair_action_ref is None:
            raise ValueError("repair charge requires an exact RepairAction")
        recovering = self.recovery_ordinal > 0
        if recovering != (self.recovery_reason_code is not None):
            raise ValueError("physical recovery requires ordinal and reason together")
        if recovering and (self.repair_action_ref is None or self.repair_attempt_charge != 0):
            raise ValueError("physical recovery reuses one RepairAction without charging it twice")
        expected_usage = {
            field_name: getattr(self.observed_actual, field_name)
            + getattr(self.unknown_upper_bound, field_name)
            for field_name in BudgetUsage.model_fields
            if field_name != "schema_version"
        }
        if self.conservative_committed != BudgetUsage.model_validate(expected_usage):
            raise ValueError("work attempt conservative usage must equal actual plus unknown")
        if self.diagnostic_only and self.releasable:
            raise ValueError("diagnostic work attempts are never releasable")
        terminal = self.status not in {"scheduled", "running"}
        if terminal != (self.finished_at is not None):
            raise ValueError("terminal work attempt requires finished_at")
        if self.status == "scheduled":
            if any(
                value is not None
                for value in (
                    self.started_at,
                    self.first_progress_at,
                    self.first_write_at,
                    self.finished_at,
                )
            ):
                raise ValueError("scheduled work has not started or produced progress")
        elif self.started_at is None:
            raise ValueError("running and terminal work attempts require started_at")
        if self.started_at is not None and self.started_at < self.scheduled_at:
            raise ValueError("work cannot start before it is scheduled")
        for progress_at in (self.first_progress_at, self.first_write_at):
            if progress_at is not None and (
                self.started_at is None
                or progress_at < self.started_at
                or (self.finished_at is not None and progress_at > self.finished_at)
            ):
                raise ValueError("progress/write timestamp is outside the active attempt")
        if (
            self.first_progress_at is not None
            and self.first_write_at is not None
            and self.first_write_at < self.first_progress_at
        ):
            raise ValueError("first write cannot precede first progress")
        if self.finished_at is not None and (
            self.started_at is None or self.finished_at < self.started_at
        ):
            raise ValueError("work cannot finish before it starts")
        if self.status == "succeeded":
            if (
                not self.output_refs
                or not self.operation_run_refs
                or self.feedback_evaluation_ref is None
            ):
                raise ValueError(
                    "successful work requires output, proposal, and boundary evaluation refs"
                )
            if self.failure_code is not None:
                raise ValueError("successful work cannot carry failure_code")
        elif self.status in {"failed", "budget_exhausted", "needs_human"} and (
            self.feedback_evaluation_ref is None
        ):
            raise ValueError("evaluated terminal failure requires a boundary evaluation")
        elif terminal and self.failure_code is None:
            raise ValueError("non-success terminal work requires a stable failure_code")
        return self


class WorkCommit(V2Contract):
    """The sole successful active-output marker for one exact WorkAttempt."""

    commit_id: Identifier
    work_id: Identifier
    coordinate: WorkCoordinate
    attempt_id: Identifier
    definition_digest: ContentHash
    acceptance_digest: ContentHash
    validation_policy_digest: ContentHash
    input_refs: tuple[ArtifactRef, ...] = ()
    validated_subject_refs: Annotated[tuple[ArtifactRef, ...], Field(min_length=1)]
    output_refs: Annotated[tuple[ArtifactRef, ...], Field(min_length=1)]
    feedback_evaluation_ref: ArtifactRef
    operation_run_refs: Annotated[tuple[ArtifactRef, ...], Field(min_length=2)]
    assurance_report_ref: ArtifactRef | None = None
    child_commit_refs: tuple[ArtifactRef, ...] = ()
    aggregate: bool = False
    diagnostic_only: bool = False
    releasable: bool = True
    committed_at: AwareDatetime

    @model_validator(mode="after")
    def validate_commit(self) -> WorkCommit:
        for values in (
            self.input_refs,
            self.validated_subject_refs,
            self.output_refs,
            self.child_commit_refs,
            self.operation_run_refs,
        ):
            if _duplicates(values):
                raise ValueError("work commit refs must be unique within each role")
        if set(self.input_refs) & set(self.output_refs):
            raise ValueError("work commit output cannot also be an immutable input")
        if self.feedback_evaluation_ref.artifact_type != "control.feedback_evaluation":
            raise ValueError("work commit evaluation ref has the wrong Artifact type")
        if any(item.artifact_type != "control.operation_run" for item in self.operation_run_refs):
            raise ValueError("work commit operation refs have the wrong Artifact type")
        if (
            self.assurance_report_ref is not None
            and self.assurance_report_ref.artifact_type != "control.assurance_report"
        ):
            raise ValueError("work commit assurance report ref has the wrong type")
        if any(item.artifact_type != "control.work_commit" for item in self.child_commit_refs):
            raise ValueError("aggregate child refs must be WorkCommit Artifacts")
        if self.aggregate != bool(self.child_commit_refs):
            raise ValueError("aggregate commits must bind child commits and leaves must not")
        if self.diagnostic_only and self.releasable:
            raise ValueError("diagnostic work commits are never releasable")
        return self

    @property
    def consumer_refs(self) -> tuple[ArtifactRef, ...]:
        """Refs made ready for consumers: validated subjects plus new evidence."""

        return tuple(dict.fromkeys((*self.validated_subject_refs, *self.output_refs)))


class WorkRepairLedgerEntry(V2Contract):
    """Repair history owned only by RepairAction and exact ValidationReports."""

    entry_id: Identifier
    work_id: Identifier
    coordinate: WorkCoordinate
    # Entries from an older unscoped live store remain readable audit evidence,
    # but entries_for() never gives them repair authority.
    repair_epoch_digest: ContentHash | None = None
    definition_digest: ContentHash | None = None
    input_fingerprint: ContentHash | None = None
    repair_policy_digest: ContentHash
    repair_action_ref: ArtifactRef
    decision: Literal[
        "local_correction",
        "parent_correction",
        "infrastructure_retry",
        "session_continuation",
    ]
    reason_code: Identifier = "legacy_unspecified"
    source_evaluation_ref: ArtifactRef
    report_before_ref: ArtifactRef
    report_after_ref: ArtifactRef | None = None
    progress: ProgressClassification | None = None
    outcome: RepairOutcome = "authorized"
    repair_attempt_ordinal: Annotated[int, Field(ge=1)]
    process_recovery_count: Annotated[int, Field(ge=0, le=2)] = 0
    recovery_attempt_refs: tuple[ArtifactRef, ...] = ()
    observed_actual: BudgetUsage = Field(default_factory=BudgetUsage)
    unknown_upper_bound: BudgetUsage = Field(default_factory=BudgetUsage)
    conservative_committed: BudgetUsage = Field(default_factory=BudgetUsage)
    authorized_at: AwareDatetime
    finished_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def validate_ledger_entry(self) -> WorkRepairLedgerEntry:
        epoch_fields = (
            self.repair_epoch_digest,
            self.definition_digest,
            self.input_fingerprint,
        )
        if any(value is None for value in epoch_fields) and not all(
            value is None for value in epoch_fields
        ):
            raise ValueError("repair epoch identity must be complete or read-only legacy")
        expected_types = {
            "repair_action_ref": (self.repair_action_ref, "control.repair_action"),
            "source_evaluation_ref": (
                self.source_evaluation_ref,
                "control.feedback_evaluation",
            ),
            "report_before_ref": (self.report_before_ref, "control.validation_report"),
        }
        if self.report_after_ref is not None:
            expected_types["report_after_ref"] = (
                self.report_after_ref,
                "control.validation_report",
            )
        if any(ref.artifact_type != "control.work_attempt" for ref in self.recovery_attempt_refs):
            raise ValueError("recovery attempt refs have the wrong Artifact type")
        if _duplicates(self.recovery_attempt_refs) or self.process_recovery_count != len(
            self.recovery_attempt_refs
        ):
            raise ValueError("process recovery count must bind unique attempts")
        for field_name, (ref, artifact_type) in expected_types.items():
            if ref.artifact_type != artifact_type:
                raise ValueError(f"{field_name} has the wrong Artifact type")
        terminal = self.outcome != "authorized"
        executed_terminal = self.outcome in {"resolved", "progressed", "no_progress"}
        if terminal != (self.finished_at is not None):
            raise ValueError("terminal repair ledger entry requires finished_at")
        if executed_terminal != (self.progress is not None):
            raise ValueError("executed terminal repair requires progress classification")
        if executed_terminal != (self.report_after_ref is not None):
            raise ValueError("executed terminal repair requires the after report")
        expected_outcome: RepairOutcome | None = None
        if self.progress == "resolved":
            expected_outcome = "resolved"
        elif self.progress == "strict_progress":
            expected_outcome = "progressed"
        elif self.progress is not None:
            expected_outcome = "no_progress"
        if expected_outcome is not None and self.outcome != expected_outcome:
            raise ValueError("repair outcome is not derived from progress classification")
        expected_usage = {
            field_name: getattr(self.observed_actual, field_name)
            + getattr(self.unknown_upper_bound, field_name)
            for field_name in BudgetUsage.model_fields
            if field_name != "schema_version"
        }
        if self.conservative_committed != BudgetUsage.model_validate(expected_usage):
            raise ValueError("repair conservative usage must equal actual plus unknown")
        return self


class RepairAction(V2Contract):
    """One framework-authorized correction against the minimal causal coordinate."""

    action_id: Identifier
    repair_policy_id: Identifier
    repair_epoch_digest: ContentHash
    definition_digest: ContentHash
    input_fingerprint: ContentHash
    source_evaluation_ref: ArtifactRef
    current_coordinate: WorkCoordinate
    target_coordinate: WorkCoordinate
    decision: RepairDecision
    jump_distance: Annotated[int, Field(ge=0, le=2)]
    repair_attempt_ordinal: Annotated[int, Field(ge=0)]
    immutable_input_refs: tuple[ArtifactRef, ...] = ()
    allowed_mutation_roots: tuple[NonEmptyStr, ...] = ()
    causal_evidence_refs: tuple[ArtifactRef, ...] = ()
    reason_code: Identifier
    repair_attempt_charge: Annotated[int, Field(ge=0, le=1)]
    authorized_at: AwareDatetime

    @model_validator(mode="after")
    def validate_repair_authority(self) -> RepairAction:
        if self.source_evaluation_ref.artifact_type != "control.feedback_evaluation":
            raise ValueError("repair source must be a FeedbackEvaluation Artifact")
        for values in (
            self.immutable_input_refs,
            self.allowed_mutation_roots,
            self.causal_evidence_refs,
        ):
            if _duplicates(values):
                raise ValueError("repair inputs, mutation roots, and evidence must be unique")
        physical_attempt = self.decision in {
            "local_correction",
            "parent_correction",
            "infrastructure_retry",
            "session_continuation",
        }
        charged_repair = self.decision in {
            "local_correction",
            "parent_correction",
            "infrastructure_retry",
        }
        if charged_repair != (self.repair_attempt_charge == 1):
            raise ValueError("only an executing repair action consumes one repair attempt")
        if physical_attempt != (self.repair_attempt_ordinal >= 1):
            raise ValueError("only a physical continuation or repair has a positive attempt ordinal")
        if self.jump_distance >= 2 and self.decision != "request_human":
            raise ValueError("distance-two repair requires human authority")
        if self.decision == "local_correction":
            if self.jump_distance != 0 or self.target_coordinate != self.current_coordinate:
                raise ValueError("local correction must target the current coordinate")
        if self.decision == "parent_correction":
            if self.jump_distance != 1 or not self.causal_evidence_refs:
                raise ValueError("parent correction requires exact one-hop causal evidence")
            if self.target_coordinate == self.current_coordinate:
                raise ValueError("parent correction must target a distinct coordinate")
        if self.decision == "infrastructure_retry" and self.jump_distance != 0:
            raise ValueError("infrastructure retry cannot backjump")
        if self.decision == "session_continuation":
            if self.jump_distance != 0 or self.target_coordinate != self.current_coordinate:
                raise ValueError("session continuation must target the current coordinate")
            if not (self.immutable_input_refs and self.allowed_mutation_roots):
                raise ValueError(
                    "session continuation requires exact immutable inputs and mutation roots"
                )
        if self.decision in {"local_correction", "parent_correction"} and not (
            self.immutable_input_refs and self.allowed_mutation_roots
        ):
            raise ValueError("semantic correction requires immutable inputs and mutation roots")
        if not physical_attempt and self.allowed_mutation_roots:
            raise ValueError("non-executing decision cannot grant mutation authority")
        return self


class ParentRepairRoute(V2Contract):
    """Safe, code-routed request to repair one declared causal parent.

    A failed downstream leaf has no authority to reopen another coordinate.  It
    may only emit this immutable request alongside its normal ValidationReport.
    ``WorkScheduler`` validates the declared one-hop graph edge and turns it
    into a *target-local* RepairAction under the target's own mutation budget.
    That separation is intentional: the source owns the finding, while the
    owner of the mutable Artifact owns the actual repair attempt.
    """

    route_id: Identifier
    source_coordinate: WorkCoordinate
    source_attempt_id: Identifier
    source_definition_digest: ContentHash
    target_coordinate: WorkCoordinate
    issue_identities: Annotated[tuple[ContentHash, ...], Field(min_length=1)]
    routed_at: AwareDatetime

    @model_validator(mode="after")
    def validate_route(self) -> ParentRepairRoute:
        if self.source_coordinate == self.target_coordinate:
            raise ValueError("parent repair route must target a distinct coordinate")
        if _duplicates(self.issue_identities):
            raise ValueError("parent repair route issue identities must be unique")
        return self


def classify_progress(
    previous: ValidationReport,
    current: ValidationReport,
    *,
    history: tuple[ValidationReport, ...] = (),
) -> ProgressClassification:
    """Conservatively classify repair progress from exact normalized diagnostics.

    ``history`` contains reports older than ``previous``.  Returning ``unknown``
    never authorizes another Agent turn; callers may grant a progress bonus only
    for ``strict_progress``.
    """

    if previous.coordinate != current.coordinate:
        raise ValueError("progress comparison requires one WorkCoordinate")
    if previous.policy_digest != current.policy_digest:
        raise ValueError("progress comparison requires one validation policy revision")
    if any(
        item.coordinate != current.coordinate or item.policy_digest != current.policy_digest
        for item in history
    ):
        raise ValueError("progress history must share coordinate and policy revision")

    current_blockers = set(current.blocking_issue_ids)
    previous_blockers = set(previous.blocking_issue_ids)
    if current.status == "passed":
        return "resolved"
    if not current_blockers:
        return "unknown"
    if previous.diagnostic_quality != "actionable" or current.diagnostic_quality != "actionable":
        return "unknown"
    if (
        current_blockers == previous_blockers
        and current.frontier_ordinal == previous.frontier_ordinal
        and current.validation_phase == previous.validation_phase
    ):
        return "unchanged"

    current_state = (
        current.validation_phase,
        current.frontier_ordinal,
        frozenset(current_blockers),
    )
    historical_states = {
        (item.validation_phase, item.frontier_ordinal, frozenset(item.blocking_issue_ids))
        for item in history
    }
    if current_state in historical_states:
        return "oscillating"
    if current.frontier_ordinal < previous.frontier_ordinal:
        return "regressed"

    historical_blockers = {blocker for item in history for blocker in item.blocking_issue_ids}
    reintroduced = current_blockers & (historical_blockers - previous_blockers)
    if reintroduced:
        return "regressed"
    if current_blockers < previous_blockers:
        return "strict_progress"
    if (
        current.frontier_ordinal == previous.frontier_ordinal
        and current.validation_phase == previous.validation_phase
        and current_blockers.isdisjoint(previous_blockers)
    ):
        # One bounded correction may expose the next sibling obligations at
        # the same compiler frontier. Exact disjointness proves every prior
        # blocker was removed; history above still rejects A -> B -> A.
        return "strict_progress"
    if current.frontier_ordinal > previous.frontier_ordinal and not (
        current_blockers & previous_blockers
    ):
        return "strict_progress"
    return "unknown"


__all__ = [
    "AgentRole",
    "ArtifactSlotContract",
    "AssuranceExecution",
    "AssuranceProbeResult",
    "AssurancePolicy",
    "AssuranceReport",
    "BoundaryExecutionStatus",
    "DiagnosticQuality",
    "EvaluationStatus",
    "FeedbackEvaluation",
    "OperationBudget",
    "OperationKind",
    "OperationRun",
    "OperationRunStatus",
    "ParentRepairRoute",
    "ReplayMode",
    "ProgressClassification",
    "ProposalExecution",
    "ProposalExecutionStatus",
    "ProposalExecutor",
    "ProposalPolicy",
    "ReadinessEffect",
    "RepairAction",
    "RepairDecision",
    "RepairPolicy",
    "RepairOutcome",
    "ValidationEffect",
    "ValidationExecution",
    "ValidationIssue",
    "ValidationPolicy",
    "ValidationReport",
    "ValidationStatus",
    "WorkAttempt",
    "WorkCommit",
    "WorkComponent",
    "WorkCoordinate",
    "WorkDefinition",
    "WorkRepairLedgerEntry",
    "classify_progress",
    "diagnostic_quality_for_issues",
    "repair_epoch_digest",
    "work_input_fingerprint",
]
