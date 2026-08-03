"""Bounded, agent-facing Tier A scene contracts and their pure reducer.

The scene is deliberately a projection of already durable WorkGraph facts.  It
does not own scheduling, repair, or release authority, and ``fold`` only sees
cold inputs that a later read-side command can reconstruct.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, model_validator

from agent_world.contracts import (
    ContentHash,
    NonEmptyStr,
    V2Contract,
    canonical_json_bytes,
    sha256_digest,
)

MAX_TOP_ISSUES = 8
MAX_UNRESOLVED_ISSUES = 32
MAX_COORDINATE_POINTERS = 16
MAX_MISSING_COORDINATES = 32
MAX_WATERMARK_COORDINATES = 64
MAX_FRONTIER_SAMPLES = 4
MAX_ROOT_INDEX_ENTRIES = 64
MAX_ACTIVE_WORK_POINTERS = 16
_EMPTY_ACTIVE_WORK_DIGEST = sha256_digest(canonical_json_bytes(()))

type HeadStatus = Literal[
    "running",
    "repair_authorized",
    "committed",
    "failed",
    "needs_human",
    "interrupted",
]
# Mirrors ``agent_world.control.work.ValidationStatus``.  ``error`` is the
# authoritative marker of an infrastructure/transport terminal (a leaf that
# could not produce a valid proposal, e.g. a compatible-gateway response that
# was not JSON) as opposed to ``failed`` (a real proposal whose semantics were
# deterministically rejected).  The scene must route these two lanes apart so a
# transport failure never presents the frozen WorldSpec as the repair subject.
type ValidationStatus = Literal["passed", "failed", "inconclusive", "error"]
type PipelineStage = Literal[
    "Research",
    "Designer",
    "Builder",
    "Integration",
    "Judge",
    "Registry",
]
type FrontierProgress = Literal["strict_progress", "resolved", "no_progress", "unknown"]
type RepairAuthority = Literal[
    "authorized",
    "in_progress",
    "eligible",
    "none",
    "needs_human",
]
type RepairTarget = Literal[
    "generated_candidate_code",
    "design_worldspec",
    "proposal_semantics",
    "infrastructure_transport",
    "needs_human",
]
type StuckReason = Literal[
    "authorized_repair",
    "thrashing",
    "no_repair_authority",
    "subprocess_crash",
    "budget_exhausted",
    "blocked_by_parent",
    "needs_human",
]
type SceneStatus = Literal[
    "running",
    "repair_authorized",
    "committed",
    "failed",
    "needs_human",
    "interrupted",
]
type NextActionHint = Literal[
    "inspect_subprocess",
    "inspect_infrastructure",
    "adjust_budget",
    "repair_candidate_code",
    "revise_proposal",
    "review_design_worldspec",
    "request_human_review",
    "wait_for_running_work",
]
type OperationPhase = Literal["proposal", "validation", "assurance"]
type WorkspaceHeartbeatStatus = Literal[
    "turn_started",
    "changed",
    "steady",
    "turn_terminal",
    "unavailable",
]
type InvocationLivenessPhase = Literal[
    "queued",
    "admitted",
    "profile_verifying",
    "profile_verified",
    "worker_spawned",
    "payload_dispatched",
    "sdk_session_open",
    "thread_start",
    "thread_resume",
    "turn_start",
    "turn_stream",
    "parent_waiting",
    "worker_exited",
    "direct_request_dispatched",
    "direct_dispatched",
    "direct_awaiting_response",
    "direct_stream_opened",
    "direct_awaiting_stream_event",
    "cancel_requested",
    "declared_wall_expired",
    "cleanup_running",
    "cleanup_finished",
    "terminal_received",
    "owner_lost",
]
type CodexTerminalErrorShape = Literal["missing", "non_object", "object"]
type CodexTerminalErrorInfo = Literal[
    "absent",
    "non_object",
    "object:other",
    "active_turn_not_steerable",
    "enum:contextwindowexceeded",
    "enum:sessionbudgetexceeded",
    "enum:usagelimitexceeded",
    "enum:serveroverloaded",
    "enum:internalservererror",
    "enum:unauthorized",
    "enum:badrequest",
    "enum:cyberpolicy",
    "enum:sandboxerror",
    "enum:threadrollbackfailed",
    "enum:other",
    "transport:http_connection_failed",
    "transport:response_stream_connection_failed",
    "transport:response_stream_disconnected",
    "transport:response_too_many_failed_attempts",
]
type ProviderAdvisoryTextSignal = Literal[
    "authentication_or_authorization",
    "model_or_route_availability",
    "context_or_token_limit",
    "request_or_schema_compatibility",
    "capacity_or_rate_limit",
    "transport_or_connection",
    "timeout_or_deadline",
    "policy_or_content_filter",
    "provider_internal_error",
]


class TopIssue(V2Contract):
    """One bounded, secret-screened diagnostic suitable for an agent read."""

    code: Annotated[NonEmptyStr, Field(max_length=160)]
    path: Annotated[tuple[str | int, ...], Field(min_length=1, max_length=16)]
    violated_condition: Annotated[NonEmptyStr, Field(max_length=512)]
    expected_category: Annotated[NonEmptyStr, Field(max_length=512)]
    remediation: Annotated[NonEmptyStr, Field(max_length=512)] | None = None
    severity: Literal["warning", "blocker"]

    @model_validator(mode="after")
    def validate_path(self) -> TopIssue:
        for part in self.path:
            if isinstance(part, str) and (not part or len(part) > 160):
                raise ValueError("scene issue path strings must contain 1..160 characters")
            if isinstance(part, int) and part < 0:
                raise ValueError("scene issue path indices cannot be negative")
        return self


class RuntimeAgentActivityCounts(V2Contract):
    """Content-free counts of compact SDK item-type notifications.

    Each count is a notification observation, not a claim that a command,
    write, tool call, or message completed successfully.  ``None`` on the
    enclosing liveness record means a historical trace predates this safe
    classification, rather than that every activity count was zero.
    """

    reasoning_event_count: Annotated[int, Field(ge=0)] = 0
    agent_message_event_count: Annotated[int, Field(ge=0)] = 0
    command_event_count: Annotated[int, Field(ge=0)] = 0
    file_change_event_count: Annotated[int, Field(ge=0)] = 0
    tool_event_count: Annotated[int, Field(ge=0)] = 0
    other_event_count: Annotated[int, Field(ge=0)] = 0
    unclassified_event_count: Annotated[int, Field(ge=0)] = 0

    @property
    def total_event_count(self) -> int:
        return sum(
            (
                self.reasoning_event_count,
                self.agent_message_event_count,
                self.command_event_count,
                self.file_change_event_count,
                self.tool_event_count,
                self.other_event_count,
                self.unclassified_event_count,
            )
        )


class RuntimeAgentLiveness(V2Contract):
    """Safe child-invocation timing bound to this exact Scheduler proposal.

    Times are measured from the durable WorkAttempt start rather than from a
    provider clock.  The projection deliberately contains no model output,
    prompt, endpoint, transcript, tool arguments, or workspace path.
    """

    started_elapsed_ms: Annotated[int, Field(ge=0)]
    first_progress_elapsed_ms: Annotated[int, Field(ge=0)] | None = None
    last_progress_elapsed_ms: Annotated[int, Field(ge=0)] | None = None
    last_local_heartbeat_elapsed_ms: Annotated[int, Field(ge=0)] | None = None
    last_local_heartbeat_phase: InvocationLivenessPhase | None = None
    terminal_elapsed_ms: Annotated[int, Field(ge=0)] | None = None
    observed_event_count: Annotated[int, Field(ge=0)] = 0
    activity: RuntimeAgentActivityCounts | None = None

    @model_validator(mode="after")
    def validate_order(self) -> RuntimeAgentLiveness:
        for value in (
            self.first_progress_elapsed_ms,
            self.last_progress_elapsed_ms,
            self.last_local_heartbeat_elapsed_ms,
            self.terminal_elapsed_ms,
        ):
            if value is not None and value < self.started_elapsed_ms:
                raise ValueError("Runtime Agent liveness cannot precede invocation start")
        if (
            self.first_progress_elapsed_ms is not None
            and self.last_progress_elapsed_ms is not None
            and self.last_progress_elapsed_ms < self.first_progress_elapsed_ms
        ):
            raise ValueError("Runtime Agent last progress cannot precede first progress")
        if (
            self.last_local_heartbeat_phase is not None
            and self.last_local_heartbeat_elapsed_ms is None
        ):
            raise ValueError("Runtime Agent heartbeat phase requires a heartbeat time")
        if (
            self.activity is not None
            and self.activity.total_event_count > self.observed_event_count
        ):
            raise ValueError("Runtime Agent activity cannot exceed all observed events")
        return self


class CodexTerminalEnvelope(V2Contract):
    """Closed, content-free facts from one failed Codex terminal envelope.

    This is a project-execution Agent observation, not feedback for the
    runtime Code Agent.  The projector reads it only from the already-redacted
    leaf-failure evidence whose attempt, coordinate, and failure code match
    the current validation report.  It intentionally excludes provider text,
    endpoint, workspace, request, and session material.
    """

    terminal_error_shape: CodexTerminalErrorShape | None = None
    codex_error_info: CodexTerminalErrorInfo | None = None
    http_status: Annotated[int, Field(ge=100, le=599)] | None = None
    advisory_text_signals: Annotated[
        tuple[ProviderAdvisoryTextSignal, ...], Field(max_length=9)
    ] = ()

    @model_validator(mode="after")
    def validate_nonempty(self) -> CodexTerminalEnvelope:
        if (
            self.terminal_error_shape is None
            and self.codex_error_info is None
            and self.http_status is None
            and not self.advisory_text_signals
        ):
            raise ValueError("Codex terminal envelope requires at least one closed fact")
        if len(set(self.advisory_text_signals)) != len(self.advisory_text_signals):
            raise ValueError("Codex terminal envelope advisory signals must be unique")
        return self


class RuntimeAgentRequestShape(V2Contract):
    """Content-free dimensions of the exact request that reached an adapter.

    This exists so the project-execution Agent can compare a zero-event node
    with a passing control without loading Prompt text, Runtime Skill text,
    output schemas, endpoints, sessions, or workspace paths.  It is evidence
    for attribution, never a request-size policy or an acceptance contract.
    """

    prompt_bytes: Annotated[int, Field(ge=0)]
    runtime_skill_count: Annotated[int, Field(ge=0)]
    output_schema_bytes: Annotated[int, Field(ge=0)] | None = None
    allowed_builtin_tool_count: Annotated[int, Field(ge=0)]
    execution_mode: Literal["agentic", "single_shot_structured"]
    continued_session: bool


class CandidateWorkspaceLiveness(V2Contract):
    """Content-free Builder workspace heartbeat for this exact attempt."""

    status: WorkspaceHeartbeatStatus
    observed_elapsed_ms: Annotated[int, Field(ge=0)]
    last_changed_elapsed_ms: Annotated[int, Field(ge=0)] | None = None
    file_count: Annotated[int, Field(ge=0)]
    total_bytes: Annotated[int, Field(ge=0)]
    error_code: Annotated[NonEmptyStr, Field(max_length=160)] | None = None

    @model_validator(mode="after")
    def validate_heartbeat_shape(self) -> CandidateWorkspaceLiveness:
        if self.status == "unavailable" and self.error_code is None:
            raise ValueError("unavailable workspace heartbeat requires an error code")
        if self.status != "unavailable" and self.error_code is not None:
            raise ValueError("available workspace heartbeat cannot expose an error code")
        if (
            self.last_changed_elapsed_ms is not None
            and self.last_changed_elapsed_ms > self.observed_elapsed_ms
        ):
            raise ValueError("workspace change cannot follow its latest heartbeat")
        return self


class BudgetAdmissionDimension(V2Contract):
    """One exact reserve comparison, safe to expose in a project Agent view."""

    dimension: NonEmptyStr
    requested: Annotated[int | float, Field(ge=0)]
    available: Annotated[int | float, Field(ge=0)]

    @model_validator(mode="after")
    def validate_rejection(self) -> BudgetAdmissionDimension:
        if self.requested <= self.available:
            raise ValueError("budget admission dimension must show a positive deficit")
        return self


class BudgetExhaustion(V2Contract):
    """Safe budget facts for a terminal Scheduler attempt.

    This is a read-side projection of the framework-owned
    ``control.budget_exhaustion_evidence`` artifact.  Exact requested and
    available values are included only when a reserve admission rejected an
    operation before it began; settlement overshoots carry no invented
    admission comparison because their ``OperationRun`` is authoritative.
    """

    exhausted_dimensions: Annotated[tuple[NonEmptyStr, ...], Field(min_length=1, max_length=16)]
    admission: tuple[BudgetAdmissionDimension, ...] = ()
    during_authorized_repair: bool
    operation_not_started: bool

    @model_validator(mode="after")
    def validate_dimensions(self) -> BudgetExhaustion:
        if len(set(self.exhausted_dimensions)) != len(self.exhausted_dimensions):
            raise ValueError("budget exhaustion dimensions must be unique")
        admission_dimensions = tuple(item.dimension for item in self.admission)
        if admission_dimensions and admission_dimensions != self.exhausted_dimensions:
            raise ValueError(
                "budget admission facts must cover exactly the exhausted dimensions"
            )
        return self


class FrontierDiff(V2Contract):
    """Set-size projection of the current and preceding unresolved frontier."""

    previous_size: Annotated[int, Field(ge=0)]
    current_size: Annotated[int, Field(ge=0)]
    delta: int

    @model_validator(mode="after")
    def validate_delta(self) -> FrontierDiff:
        if self.delta != self.current_size - self.previous_size:
            raise ValueError("frontier delta must equal current_size minus previous_size")
        return self


class CoordinatePointer(V2Contract):
    """A bounded map-layer pointer to one on-disk coordinate scene."""

    coordinate_key: ContentHash
    coordinate_label: Annotated[NonEmptyStr, Field(max_length=512)]
    head_status: HeadStatus
    json_path: Annotated[NonEmptyStr, Field(max_length=512)]
    markdown_path: Annotated[NonEmptyStr, Field(max_length=512)]


class ActiveWorkPointer(V2Contract):
    """A compact, redacted live-operation overlay for one coordinate.

    This is navigation evidence for the project-execution Agent, not a
    Scheduler state transition or a Provider transcript.  Multiple physical
    turns may be active beneath one coordinate, so the pointer intentionally
    aggregates counts and never exposes an invocation id, workspace, prompt,
    response, or model identifier.
    """

    coordinate_key: ContentHash
    coordinate_label: Annotated[NonEmptyStr, Field(max_length=512)]
    route: Literal["codex_sdk", "direct_llm", "mixed"]
    active_turn_count: Annotated[int, Field(ge=1)]
    provider_progress_count: Annotated[int, Field(ge=0)]
    started_at: AwareDatetime
    last_activity_at: AwareDatetime
    first_provider_progress_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def validate_timing(self) -> ActiveWorkPointer:
        if self.last_activity_at < self.started_at:
            raise ValueError("active work cannot have activity before it starts")
        if (
            self.first_provider_progress_at is not None
            and self.first_provider_progress_at < self.started_at
        ):
            raise ValueError("first Provider progress cannot precede active work")
        return self


class CoordinateWatermark(V2Contract):
    """One durable-head version included in a materialized scene."""

    coordinate_key: ContentHash
    revision: Annotated[int, Field(ge=1)]
    status: HeadStatus
    attempt_ref_revision: ContentHash


class SceneWatermark(V2Contract):
    """Bounded per-coordinate freshness proof plus an all-head aggregate hash."""

    coordinates: Annotated[
        tuple[CoordinateWatermark, ...], Field(max_length=MAX_WATERMARK_COORDINATES)
    ]
    coordinate_overflow_count: Annotated[int, Field(ge=0)] = 0
    aggregate_digest: ContentHash
    graph_digest: ContentHash
    # Live invocation-control records are replaceable observations, but they
    # must participate in cache freshness or a newly active retry remains
    # hidden behind an older failed/repair head.
    active_work_digest: ContentHash = _EMPTY_ACTIVE_WORK_DIGEST
    projected_from_run_id: Annotated[NonEmptyStr, Field(max_length=512)] | None = None
    projected_at: AwareDatetime

    @model_validator(mode="after")
    def validate_unique_coordinates(self) -> SceneWatermark:
        keys = tuple(item.coordinate_key for item in self.coordinates)
        if len(set(keys)) != len(keys):
            raise ValueError("scene watermark coordinates must be unique")
        return self


class CoordinateScene(V2Contract):
    """The bounded current scene for one physical WorkCoordinate."""

    scope_id: Annotated[NonEmptyStr, Field(max_length=512)]
    coordinate_key: ContentHash
    coordinate_label: Annotated[NonEmptyStr, Field(max_length=512)]
    head_status: HeadStatus
    attempt_ordinal: Annotated[int, Field(ge=1)]
    failure_code: Annotated[NonEmptyStr, Field(max_length=512)] | None = None
    validation_status: ValidationStatus | None = None
    frontier_ordinal: Annotated[int, Field(ge=0)]
    pipeline_stage: PipelineStage
    unresolved_issue_ids: Annotated[
        tuple[ContentHash, ...], Field(max_length=MAX_UNRESOLVED_ISSUES)
    ] = ()
    unresolved_issue_overflow_count: Annotated[int, Field(ge=0)] = 0
    unresolved_issue_digest: ContentHash
    previous_issue_digest: ContentHash | None = None
    frontier_diff: FrontierDiff
    frontier_progress: FrontierProgress
    repair_authority: RepairAuthority
    candidate_file: Annotated[NonEmptyStr, Field(max_length=512)] | None = None
    contract_pointer: Annotated[NonEmptyStr, Field(max_length=512)] | None = None
    repair_target: RepairTarget | None = None
    top_issues: Annotated[tuple[TopIssue, ...], Field(max_length=MAX_TOP_ISSUES)] = ()
    subprocess_pointer: Annotated[NonEmptyStr, Field(max_length=512)] | None = None
    input_fingerprint: ContentHash
    attempt_ref_id: Annotated[NonEmptyStr, Field(max_length=512)]
    # Terminal timing is derived from durable WorkAttempt / OperationRun
    # timestamps.  A still-running attempt additionally exposes one current
    # wall-clock checkpoint, explicitly marked as an estimate, so an Agent does
    # not mistake minutes of active waiting for missing telemetry.
    attempt_elapsed_ms: Annotated[int, Field(ge=0)] | None = None
    attempt_elapsed_estimated: bool = False
    first_progress_elapsed_ms: Annotated[int, Field(ge=0)] | None = None
    last_completed_phase: OperationPhase | None = None
    terminal_failure_phase: OperationPhase | None = None
    terminal_failure_elapsed_ms: Annotated[int, Field(ge=0)] | None = None
    runtime_agent_liveness: RuntimeAgentLiveness | None = None
    codex_terminal_envelope: CodexTerminalEnvelope | None = None
    runtime_agent_request_shape: RuntimeAgentRequestShape | None = None
    candidate_workspace_liveness: CandidateWorkspaceLiveness | None = None
    budget_exhaustion: BudgetExhaustion | None = None

    @model_validator(mode="after")
    def validate_scene_bounds(self) -> CoordinateScene:
        if len(set(self.unresolved_issue_ids)) != len(self.unresolved_issue_ids):
            raise ValueError("scene unresolved issue identities must be unique")
        if self.head_status == "committed" and self.repair_target is not None:
            raise ValueError("committed coordinate scenes cannot advertise a repair target")
        if (
            self.repair_target == "generated_candidate_code"
            and self.candidate_file is None
            and self.repair_authority != "authorized"
        ):
            raise ValueError(
                "candidate-code repair target without a concrete file requires Scheduler authority"
            )
        if self.budget_exhaustion is not None and self.failure_code != "budget_exhausted":
            raise ValueError("budget exhaustion scene facts require budget_exhausted failure")
        if self.attempt_elapsed_estimated and (
            self.head_status != "running" or self.attempt_elapsed_ms is None
        ):
            raise ValueError("only a running scene may carry an elapsed-time estimate")
        return self


class FrontierRecord(V2Contract):
    """One compact, append-only per-attempt frontier sample."""

    coordinate_key: ContentHash
    attempt_ref_revision: ContentHash
    attempt_ref_id: Annotated[NonEmptyStr, Field(max_length=512)]
    attempt_ordinal: Annotated[int, Field(ge=1)]
    frontier_ordinal: Annotated[int, Field(ge=0)]
    unresolved_issue_digest: ContentHash
    unresolved_issue_count: Annotated[int, Field(ge=0)]
    issue_samples: Annotated[tuple[TopIssue, ...], Field(max_length=MAX_FRONTIER_SAMPLES)] = ()


class RunSceneIndex(V2Contract):
    """The map-layer index that agents read before expanding one coordinate."""

    scope_id: Annotated[NonEmptyStr, Field(max_length=512)]
    overall_status: SceneStatus
    stuck_coordinate: CoordinatePointer | None = None
    stuck_reason: StuckReason | None = None
    missing_coordinates: Annotated[
        tuple[CoordinatePointer, ...], Field(max_length=MAX_MISSING_COORDINATES)
    ] = ()
    missing_coordinates_overflow_count: Annotated[int, Field(ge=0)] = 0
    frontier_size: Annotated[int, Field(ge=0)]
    frontier_delta: int
    next_action_hint: NextActionHint | None = None
    active_work: Annotated[
        tuple[ActiveWorkPointer, ...], Field(max_length=MAX_ACTIVE_WORK_POINTERS)
    ] = ()
    active_work_overflow_count: Annotated[int, Field(ge=0)] = 0
    coordinate_pointers: Annotated[
        tuple[CoordinatePointer, ...], Field(max_length=MAX_COORDINATE_POINTERS)
    ] = ()
    additional_stuck_count: Annotated[int, Field(ge=0)] = 0
    watermark: SceneWatermark

    @model_validator(mode="after")
    def validate_stuck_shape(self) -> RunSceneIndex:
        if self.stuck_reason is not None and self.stuck_coordinate is None:
            raise ValueError("a stuck reason requires a stuck coordinate")
        if len({item.coordinate_key for item in self.coordinate_pointers}) != len(
            self.coordinate_pointers
        ):
            raise ValueError("scene coordinate pointers must be unique")
        if len({item.coordinate_key for item in self.active_work}) != len(self.active_work):
            raise ValueError("scene active-work coordinates must be unique")
        return self


class ScopeIndexEntry(V2Contract):
    """One bounded root-index entry for a stable scope partition."""

    scope_id: Annotated[NonEmptyStr, Field(max_length=512)]
    overall_status: SceneStatus
    updated_at: AwareDatetime
    stuck_coordinate_key: ContentHash | None = None


class ObservabilityIndex(V2Contract):
    """Cross-scope pointer index; it is a cache just like each scene file."""

    entries: Annotated[tuple[ScopeIndexEntry, ...], Field(max_length=MAX_ROOT_INDEX_ENTRIES)] = ()
    overflow_count: Annotated[int, Field(ge=0)] = 0

    @model_validator(mode="after")
    def validate_unique_scopes(self) -> ObservabilityIndex:
        scopes = tuple(item.scope_id for item in self.entries)
        if len(set(scopes)) != len(scopes):
            raise ValueError("observability root index scopes must be unique")
        return self


@dataclass(frozen=True, slots=True)
class SceneIssue:
    """Cold, already secret-screened issue input to the shared reducer."""

    normalized_identity: str
    code: str
    path: tuple[str | int, ...]
    violated_condition: str
    expected_category: str
    severity: Literal["warning", "blocker"]
    actionable: bool
    gate_id: str | None = None
    candidate_file: str | None = None
    multi_file_gate: bool = False
    remediation: str | None = None


@dataclass(frozen=True, slots=True)
class SceneHead:
    """Durable coordinate facts plus an explicitly provisional running-time projection."""

    scope_id: str
    coordinate_key: str
    coordinate_label: str
    head_status: HeadStatus
    revision: int
    attempt_ref_revision: str
    attempt_ref_id: str
    attempt_ordinal: int
    failure_code: str | None
    frontier_ordinal: int
    pipeline_stage: PipelineStage
    repair_authority: RepairAuthority
    input_fingerprint: str
    issues: tuple[SceneIssue, ...]
    previous_issue_ids: tuple[str, ...]
    run_id: str | None
    graph_digest: str
    updated_at: datetime
    # The projector may obtain the full immediate repair lineage from durable
    # validation reports.  Keeping that derived classification on the
    # read-model input prevents this compact view from reimplementing a weaker
    # issue-set-only approximation of the control-plane progress lattice.
    # Hand-built view fixtures deliberately leave it absent and exercise the
    # conservative local fallback below.
    frontier_progress: FrontierProgress | None = None
    subprocess_available: bool = False
    # The terminal ValidationReport.status for this head, when one exists.
    # ``error`` denotes an infrastructure/transport terminal; ``failed`` denotes
    # a deterministically rejected real proposal.  ``None`` when the head has no
    # settled validation report yet (running / freshly scheduled).
    validation_status: ValidationStatus | None = None
    # True when this head's terminal report routes its repair to an ancestor
    # coordinate (a ``control.parent_repair_route`` was committed).  A rejected
    # proposal WITHOUT such a route is repairable where it was produced, so it
    # must not be presented as a frozen-design defect.
    routes_repair_to_parent: bool = False
    attempt_elapsed_ms: int | None = None
    attempt_elapsed_estimated: bool = False
    first_progress_elapsed_ms: int | None = None
    last_completed_phase: OperationPhase | None = None
    terminal_failure_phase: OperationPhase | None = None
    terminal_failure_elapsed_ms: int | None = None
    runtime_agent_liveness: RuntimeAgentLiveness | None = None
    codex_terminal_envelope: CodexTerminalEnvelope | None = None
    runtime_agent_request_shape: RuntimeAgentRequestShape | None = None
    candidate_workspace_liveness: CandidateWorkspaceLiveness | None = None
    budget_exhaustion: BudgetExhaustion | None = None


@dataclass(frozen=True, slots=True)
class SceneTierBEvent:
    """The small cold subset of a Tier B event relevant to scene folding."""

    event_type: str
    coordinate_key: str | None = None


@dataclass(frozen=True, slots=True)
class Scene:
    """All deterministic Tier A outputs of one shared fold."""

    index: RunSceneIndex
    coordinates: tuple[CoordinateScene, ...]
    frontier_records: tuple[FrontierRecord, ...]


def fold(
    heads: Sequence[SceneHead],
    tier_b_events: Sequence[SceneTierBEvent],
    *,
    active_work: Sequence[ActiveWorkPointer] = (),
) -> Scene:
    """Fold only cold durable heads and Tier B facts into one bounded scene.

    This signature is intentionally shared by the eager runtime projection and
    the future cold-start read-side rebuild.  Do not add WorkScheduler or
    WorkReadiness snapshots here: those objects do not survive process restart.
    """

    if not heads:
        raise ValueError("scene fold requires at least one durable WorkControlHead")
    scope_ids = {item.scope_id for item in heads}
    if len(scope_ids) != 1:
        raise ValueError("one scene fold cannot mix scope partitions")
    graph_digests = {item.graph_digest for item in heads}
    if len(graph_digests) != 1:
        raise ValueError("one scene fold requires one graph digest")

    event_coordinates = {
        item.coordinate_key
        for item in tier_b_events
        if item.event_type == "runtime_subprocess_scene" and item.coordinate_key is not None
    }
    ordered_heads = tuple(sorted(heads, key=lambda item: item.coordinate_key))
    ordered_active_work = tuple(
        sorted(active_work, key=lambda item: (item.started_at, item.coordinate_key))
    )
    coordinates = tuple(
        _coordinate_scene(
            head,
            subprocess_available=(
                head.subprocess_available or head.coordinate_key in event_coordinates
            ),
        )
        for head in ordered_heads
    )
    updated_at_by_coordinate = {head.coordinate_key: head.updated_at for head in ordered_heads}
    records = tuple(
        FrontierRecord(
            coordinate_key=coordinate.coordinate_key,
            attempt_ref_revision=head.attempt_ref_revision,
            attempt_ref_id=coordinate.attempt_ref_id,
            attempt_ordinal=coordinate.attempt_ordinal,
            frontier_ordinal=coordinate.frontier_ordinal,
            unresolved_issue_digest=coordinate.unresolved_issue_digest,
            unresolved_issue_count=(
                len(head.issues)
                if coordinate.unresolved_issue_overflow_count
                else len(coordinate.unresolved_issue_ids)
            ),
            issue_samples=coordinate.top_issues[:MAX_FRONTIER_SAMPLES],
        )
        for head, coordinate in zip(ordered_heads, coordinates, strict=True)
    )
    stuck_scenes = tuple(
        sorted(
            (item for item in coordinates if item.head_status != "committed"),
            key=lambda item: _stuck_sort_key(
                item,
                updated_at=updated_at_by_coordinate[item.coordinate_key],
            ),
        )
    )
    stuck = stuck_scenes[0] if stuck_scenes else None
    # The bounded map must retain the most actionable coordinate first.  A
    # coordinate-key sort is deterministic but can otherwise hide the actual
    # thrashing/crashed coordinate behind unrelated running work in a wide graph.
    pointer_scenes = (
        *stuck_scenes,
        *(item for item in coordinates if item.head_status == "committed"),
    )
    pointers = tuple(_pointer(item) for item in pointer_scenes)
    missing = stuck_scenes
    watermark_items = tuple(
        CoordinateWatermark(
            coordinate_key=head.coordinate_key,
            revision=head.revision,
            status=head.head_status,
            attempt_ref_revision=head.attempt_ref_revision,
        )
        for head in ordered_heads[:MAX_WATERMARK_COORDINATES]
    )
    aggregate_digest = sha256_digest(
        canonical_json_bytes(
            tuple(
                {
                    "coordinate_key": head.coordinate_key,
                    "revision": head.revision,
                    "status": head.head_status,
                    "attempt_ref_revision": head.attempt_ref_revision,
                }
                for head in ordered_heads
            )
        )
    )
    latest = max(ordered_heads, key=lambda item: (item.updated_at, item.coordinate_key))
    index = RunSceneIndex(
        scope_id=ordered_heads[0].scope_id,
        overall_status=_overall_status(coordinates, active_work=ordered_active_work),
        stuck_coordinate=(_pointer(stuck) if stuck is not None else None),
        stuck_reason=(_stuck_reason(stuck) if stuck is not None else None),
        missing_coordinates=tuple(_pointer(item) for item in missing[:MAX_MISSING_COORDINATES]),
        missing_coordinates_overflow_count=max(0, len(missing) - MAX_MISSING_COORDINATES),
        frontier_size=sum(len(head.issues) for head in ordered_heads),
        frontier_delta=sum(item.frontier_diff.delta for item in coordinates),
        next_action_hint=(
            "wait_for_running_work"
            if ordered_active_work
            else (_next_action(stuck) if stuck is not None else None)
        ),
        active_work=ordered_active_work[:MAX_ACTIVE_WORK_POINTERS],
        active_work_overflow_count=max(0, len(ordered_active_work) - MAX_ACTIVE_WORK_POINTERS),
        coordinate_pointers=tuple(pointers[:MAX_COORDINATE_POINTERS]),
        additional_stuck_count=max(0, len(stuck_scenes) - MAX_COORDINATE_POINTERS),
        watermark=SceneWatermark(
            coordinates=watermark_items,
            coordinate_overflow_count=max(0, len(ordered_heads) - MAX_WATERMARK_COORDINATES),
            aggregate_digest=aggregate_digest,
            graph_digest=ordered_heads[0].graph_digest,
            active_work_digest=active_work_digest(ordered_active_work),
            projected_from_run_id=latest.run_id,
            projected_at=latest.updated_at,
        ),
    )
    return Scene(index=index, coordinates=coordinates, frontier_records=records)


def _coordinate_scene(head: SceneHead, *, subprocess_available: bool) -> CoordinateScene:
    issue_ids = tuple(sorted(item.normalized_identity for item in head.issues))
    prior_ids = tuple(sorted(set(head.previous_issue_ids)))
    shown_issue_ids = issue_ids[:MAX_UNRESOLVED_ISSUES]
    ordered_issues = tuple(
        sorted(
            head.issues,
            key=lambda item: (
                not item.actionable,
                item.severity != "blocker",
                item.code,
                item.normalized_identity,
            ),
        )
    )
    visible_issues = ordered_issues[:MAX_TOP_ISSUES]
    top_issues = tuple(
        TopIssue(
            code=item.code,
            path=item.path,
            violated_condition=item.violated_condition,
            expected_category=item.expected_category,
            remediation=item.remediation,
            severity=item.severity,
        )
        for item in visible_issues
    )
    multi_file_gate = any(item.multi_file_gate for item in ordered_issues)
    blocker_candidate_files = {
        item.candidate_file
        for item in ordered_issues
        if item.severity == "blocker" and item.candidate_file is not None
    }
    candidate_issue = None
    if not multi_file_gate and len(blocker_candidate_files) == 1:
        sole_candidate_file = next(iter(blocker_candidate_files))
        candidate_issue = next(
            (
                item
                for item in visible_issues
                if item.severity == "blocker" and item.candidate_file == sole_candidate_file
            ),
            None,
        )
    candidate_file = candidate_issue.candidate_file if candidate_issue is not None else None
    repair_target = _repair_target(
        head,
        candidate_issue,
        multi_file_gate=multi_file_gate,
    )
    issue_digest = _issue_digest(issue_ids)
    previous_digest = _issue_digest(prior_ids) if prior_ids else None
    frontier_diff = FrontierDiff(
        previous_size=len(prior_ids),
        current_size=len(issue_ids),
        delta=len(issue_ids) - len(prior_ids),
    )
    contract_pointer = (
        f"observe contract {head.scope_id} {head.coordinate_key}"
        if repair_target is not None
        else None
    )
    return CoordinateScene(
        scope_id=head.scope_id,
        coordinate_key=head.coordinate_key,
        coordinate_label=head.coordinate_label,
        head_status=head.head_status,
        attempt_ordinal=head.attempt_ordinal,
        failure_code=head.failure_code,
        validation_status=head.validation_status,
        frontier_ordinal=head.frontier_ordinal,
        pipeline_stage=head.pipeline_stage,
        unresolved_issue_ids=shown_issue_ids,
        unresolved_issue_overflow_count=max(0, len(issue_ids) - MAX_UNRESOLVED_ISSUES),
        unresolved_issue_digest=issue_digest,
        previous_issue_digest=previous_digest,
        frontier_diff=frontier_diff,
        frontier_progress=(
            head.frontier_progress or _frontier_progress(issue_ids, prior_ids, head.head_status)
        ),
        repair_authority=head.repair_authority,
        candidate_file=candidate_file,
        contract_pointer=contract_pointer,
        repair_target=repair_target,
        top_issues=top_issues,
        subprocess_pointer=(
            f"subprocess/{_coordinate_file_name(head.coordinate_key)}.json"
            if subprocess_available
            else None
        ),
        input_fingerprint=head.input_fingerprint,
        attempt_ref_id=head.attempt_ref_id,
        attempt_elapsed_ms=head.attempt_elapsed_ms,
        attempt_elapsed_estimated=head.attempt_elapsed_estimated,
        first_progress_elapsed_ms=head.first_progress_elapsed_ms,
        last_completed_phase=head.last_completed_phase,
        terminal_failure_phase=head.terminal_failure_phase,
        terminal_failure_elapsed_ms=head.terminal_failure_elapsed_ms,
        runtime_agent_liveness=head.runtime_agent_liveness,
        codex_terminal_envelope=head.codex_terminal_envelope,
        runtime_agent_request_shape=head.runtime_agent_request_shape,
        candidate_workspace_liveness=head.candidate_workspace_liveness,
        budget_exhaustion=head.budget_exhaustion,
    )


def _repair_target(
    head: SceneHead,
    issue: SceneIssue | None,
    *,
    multi_file_gate: bool,
) -> RepairTarget | None:
    if head.head_status == "committed":
        return None
    # An infrastructure/transport terminal (ValidationReport.status == "error")
    # is not evidence of a design defect: the leaf never produced a proposal to
    # judge.  It must never route to Candidate code or the frozen WorldSpec,
    # even if the Scheduler has authorized an infrastructure retry on a Builder
    # coordinate.  Otherwise a transient Provider terminal tells the project
    # Agent to edit unrelated generated code and creates a repair loop.  This
    # must precede every semantic repair-authority branch.
    if head.validation_status == "error" and head.issues:
        return "infrastructure_transport"
    # A causal Integration failure can authorize a Builder repair whose source
    # closure spans several files.  ``multi_file_gate`` normally prevents the
    # view from guessing one editable file, but an already-authorized
    # CandidateBuild repair is stronger evidence: surface the exact permitted
    # lane without inventing a single-file target.
    if head.repair_authority == "authorized" and head.coordinate_label.startswith(
        "build.candidate_build."
    ):
        return "generated_candidate_code"
    if multi_file_gate:
        return "needs_human"
    if head.pipeline_stage == "Designer" and head.issues:
        # A rejected proposal is only a frozen-design defect when the leaf
        # actually routed its repair upstream.  Without that route the failure
        # lives in the output this coordinate just produced -- e.g. a
        # ToolSemantics batch referencing an error code it never declared -- and
        # the honest instruction is to revise that proposal, not to edit the
        # frozen WorldSpec.  Conflating the two is what turned a self-repairable
        # semantic defect into repeated frozen-design edits.
        if head.routes_repair_to_parent:
            return "design_worldspec"
        return "proposal_semantics"
    if issue is not None and issue.candidate_file is not None:
        return "generated_candidate_code"
    if head.issues or head.head_status == "needs_human":
        return "needs_human"
    return None


def _frontier_progress(
    issue_ids: tuple[str, ...],
    previous_issue_ids: tuple[str, ...],
    status: HeadStatus,
) -> FrontierProgress:
    if status == "committed":
        return "resolved"
    if not issue_ids:
        return "unknown"
    if not previous_issue_ids:
        return "unknown"
    if set(issue_ids) < set(previous_issue_ids):
        return "strict_progress"
    return "no_progress"


def _issue_digest(issue_ids: tuple[str, ...]) -> str:
    return sha256_digest(canonical_json_bytes(issue_ids))


def _coordinate_file_name(coordinate_key: str) -> str:
    return coordinate_key.removeprefix("sha256:")


def _pointer(scene: CoordinateScene) -> CoordinatePointer:
    filename = _coordinate_file_name(scene.coordinate_key)
    return CoordinatePointer(
        coordinate_key=scene.coordinate_key,
        coordinate_label=scene.coordinate_label,
        head_status=scene.head_status,
        json_path=f"coordinates/{filename}.json",
        markdown_path=f"coordinates/{filename}.md",
    )


def active_work_digest(items: Sequence[ActiveWorkPointer]) -> str:
    """Hash safe live facts so cache reads cannot hide a new retry."""

    return sha256_digest(
        canonical_json_bytes(tuple(item.model_dump(mode="json") for item in items))
    )


def _overall_status(
    coordinates: tuple[CoordinateScene, ...],
    *,
    active_work: Sequence[ActiveWorkPointer] = (),
) -> SceneStatus:
    if active_work:
        return "running"
    priorities: tuple[SceneStatus, ...] = (
        "needs_human",
        "failed",
        "interrupted",
        "repair_authorized",
        "running",
        "committed",
    )
    statuses = {item.head_status for item in coordinates}
    return next(item for item in priorities if item in statuses)


def _stuck_sort_key(
    scene: CoordinateScene,
    *,
    updated_at: datetime,
) -> tuple[int, int, float, str]:
    reason = _stuck_reason(scene)
    # Prefer one already-authorized correction over a downstream failed
    # coordinate with no local authority.  More urgent anomalies (crash,
    # budget exhaustion, thrashing, explicit human decision) still win.
    reason_priority = (
        3
        if scene.repair_authority == "authorized"
        else {
            "thrashing": 0,
            "subprocess_crash": 1,
            "budget_exhausted": 2,
            "needs_human": 3,
            "no_repair_authority": 4,
            "blocked_by_parent": 5,
            None: 6,
        }[reason]
    )
    status_priority = {
        "failed": 0,
        "needs_human": 1,
        "interrupted": 2,
        "repair_authorized": 3,
        "running": 4,
        "committed": 5,
    }[scene.head_status]
    # A compact top-level scene is a *current* project-Agent orientation, not
    # a durable error archive.  Once urgency and terminal status tie, surface
    # the most recently changed unresolved coordinate.  Without this tie
    # breaker, a stale downstream Integration failure can win merely because
    # its opaque coordinate hash sorts before the just-failed Builder attempt
    # that the Code Agent actually needs to investigate.  The per-coordinate
    # files retain the full history; equal timestamps deliberately keep the
    # coordinate key as a deterministic final tie breaker.
    return (reason_priority, status_priority, -updated_at.timestamp(), scene.coordinate_key)


def _stuck_reason(scene: CoordinateScene) -> StuckReason | None:
    if scene.head_status == "needs_human":
        return "needs_human"
    if scene.failure_code == "budget_exhausted":
        return "budget_exhausted"
    if scene.subprocess_pointer is not None:
        return "subprocess_crash"
    # A new Scheduler-authorized correction may follow earlier unsuccessful
    # attempts.  Its historical ordinal is not evidence that this newly
    # authorized, recipient-specific repair has itself thrashed.
    if scene.repair_authority == "authorized":
        return "authorized_repair"
    if scene.frontier_progress == "no_progress" and scene.attempt_ordinal > 1:
        return "thrashing"
    if scene.failure_code is not None and scene.failure_code.startswith("causal_"):
        return "blocked_by_parent"
    if scene.head_status in {"failed", "interrupted"} and scene.repair_authority == "none":
        return "no_repair_authority"
    return None


def _next_action(scene: CoordinateScene) -> NextActionHint | None:
    reason = _stuck_reason(scene)
    if reason == "subprocess_crash":
        return "inspect_subprocess"
    if scene.budget_exhaustion is not None:
        return "adjust_budget"
    # A transport/infra terminal must be inspected as infrastructure even when
    # the attempt count would otherwise read as thrashing: the loop is caused by
    # mis-routing, not by an unrepairable design.  This precedes the thrashing
    # branch so it is not swallowed into request_human_review.
    if scene.repair_target == "infrastructure_transport":
        return "inspect_infrastructure"
    if scene.repair_target == "generated_candidate_code":
        return "repair_candidate_code"
    if scene.repair_target == "proposal_semantics":
        return "revise_proposal"
    if scene.repair_target == "design_worldspec":
        return "review_design_worldspec"
    if scene.repair_target == "needs_human" or reason in {
        "thrashing",
        "needs_human",
        "no_repair_authority",
    }:
        return "request_human_review"
    if scene.head_status in {"running", "repair_authorized"}:
        return "wait_for_running_work"
    return None


__all__ = [
    "ActiveWorkPointer",
    "CandidateWorkspaceLiveness",
    "BudgetExhaustion",
    "CoordinatePointer",
    "CoordinateScene",
    "CoordinateWatermark",
    "CodexTerminalEnvelope",
    "FrontierDiff",
    "FrontierRecord",
    "MAX_COORDINATE_POINTERS",
    "MAX_ACTIVE_WORK_POINTERS",
    "MAX_FRONTIER_SAMPLES",
    "MAX_MISSING_COORDINATES",
    "MAX_ROOT_INDEX_ENTRIES",
    "MAX_TOP_ISSUES",
    "MAX_UNRESOLVED_ISSUES",
    "MAX_WATERMARK_COORDINATES",
    "ObservabilityIndex",
    "PipelineStage",
    "RunSceneIndex",
    "RuntimeAgentActivityCounts",
    "RuntimeAgentLiveness",
    "RuntimeAgentRequestShape",
    "Scene",
    "SceneHead",
    "SceneIssue",
    "SceneTierBEvent",
    "SceneWatermark",
    "ScopeIndexEntry",
    "TopIssue",
    "active_work_digest",
    "fold",
]
