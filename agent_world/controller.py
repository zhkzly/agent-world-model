"""Durable Direct Generation orchestration for the Agent World Foundry.

The controller is deliberately the only place that joins the five product
components.  It owns job state, independent budget ledgers, repair routing and
release authority; it does not synthesize world semantics, candidate code or
private verifier expectations itself.
"""

from __future__ import annotations

import asyncio
import hashlib
import time
import traceback
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Protocol, cast

from pydantic import JsonValue, model_validator

from agent_world.artifact_store import ArtifactWriter
from agent_world.builder import (
    BuildBundle,
    BuilderError,
    BuilderSessionState,
    BuildInvocationSummary,
    EnvironmentBuilder,
)
from agent_world.config import FoundryConfig
from agent_world.contracts import (
    ArtifactRef,
    BehaviorDescriptor,
    Budget,
    BudgetUsage,
    CandidateOutcome,
    CoverageDimension,
    CoverageGain,
    CoverageLevel,
    CoverageMap,
    DesignBaselineCheckpoint,
    DiscoveryRunSpec,
    EnvironmentDesign,
    EnvironmentJob,
    EnvironmentPackageManifest,
    EnvironmentRequest,
    Evidence,
    EvidenceGraph,
    ExpansionCampaign,
    ExpansionClue,
    ExpansionSourceCatalog,
    Finding,
    GateResult,
    GenerationContext,
    IdentityDecision,
    IntegrationReport,
    JudgeReport,
    KeyValue,
    MutationIntent,
    PackageLineage,
    PermissionScope,
    ReleaseProfile,
    SemanticLineage,
    TrustedEvaluatorDescriptor,
    V2Contract,
    canonical_json_bytes,
    compile_framework_package_payloads,
    sha256_digest,
)
from agent_world.control import (
    PRODUCTION_FEEDBACK,
    BudgetExceeded,
    BudgetLease,
    BudgetLedger,
    CampaignIterationRecord,
    CampaignStore,
    ClaimVector,
    CodeRouter,
    ControlEvent,
    ControlEventKind,
    DesignRevisionMode,
    DeterministicDisposition,
    DirectJobHead,
    DirectJobLock,
    DirectJobResumeRequiredError,
    DirectJobStore,
    DirectJobStoreError,
    DirectRequestConflictError,
    DurableLeaseBudgetCoordinator,
    ErrorAuditPolicy,
    ExpansionCandidateAttempt,
    FeedbackResult,
    JobRunSnapshot,
    LeaseBudgetLedger,
    MetricPoint,
    NodeAttempt,
    NodeCommit,
    NodeKind,
    NodeResumeAuthority,
    QuarantineReviewBundle,
    QuarantineReviewPolicy,
    RepairDirective,
    RepairLedger,
    RepairLedgerEntry,
    RepairRouter,
    RepairTargetRef,
    ResearchCheckpointReuseEvidence,
    ScopeBudgetAmendment,
    StructuredRepairAuthority,
    StructuredRepairDenied,
    StructuredRepairMode,
    TelemetryReleaseSummary,
    TelemetryStore,
    ValidationDiagnostic,
    WorkAttempt,
    WorkControlStore,
    WorkCoordinate,
    WorkDefinition,
    WorkDependencyUnavailableError,
    WorkExecutorMissingError,
    WorkGraphEpoch,
    WorkGraphManifest,
    WorkReadinessSnapshot,
    WorkRepairDenied,
    WorkRuntimeError,
    WorkSpan,
    claim,
    new_direct_job_head,
    reduce_maturity,
)
from agent_world.control.direct_runner import (
    DirectWorkRun,
    DirectWorkRunner,
    DirectWorkRunnerError,
    SemanticPrefixRun,
)
from agent_world.control.work_graph import (
    GenerationWorkGraph,
    WorkGraphMilestone,
    WorkGroupDefinition,
)
from agent_world.control.work_scheduler import WorkScheduler
from agent_world.designer import (
    AdmissionBundle,
    DesignBundle,
    DesignerBudgetPlanError,
    DesignerError,
    DiscoveryBundle,
    DiscoveryService,
    EnvironmentDesigner,
    ExpansionDesignBundle,
    ExpansionDesigner,
    ExpansionSource,
    ResolvedExpansionClue,
    ResolvedExpansionParent,
    derive_designer_invocation_budget,
)
from agent_world.expansion_runner import (
    CampaignCandidateResult,
    ExpandResult,
    ExpansionCampaignRunner,
)
from agent_world.invocation import (
    InvocationControlRouteLivenessChecker,
    InvocationControlStore,
    InvocationResult,
    InvocationStatus,
    InvocationUsage,
    NodeCapabilityRequirement,
)
from agent_world.judge import (
    CompiledVerifier,
    EnvironmentJudge,
    IntegrationBundle,
    JudgeBundle,
    VerifierCompilationError,
    VerifierCompiler,
)
from agent_world.observability import ObservabilityRoot, SceneProjector
from agent_world.registry import (
    EnvironmentRegistry,
    PackageVersionReservation,
    PreparedRelease,
    ReleaseRecord,
)

type GenerateStatus = Literal[
    "released",
    "failed",
    "needs_human",
    "budget_exhausted",
]
type FrozenResumeState = Literal["stale", "repair_ready", "running", "blocked"]
type ExecutableDesignBundle = DesignBundle | ExpansionDesignBundle
type CandidateTerminalStatus = Literal[
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
    "infrastructure_error",
]

_FRAMEWORK_ACTOR = "framework"
_INITIAL_PACKAGE_VERSION = "1.0.0"
_RISK_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}


class ProfileDescriptorProvider(Protocol):
    """Expose a public, non-secret description of one resolved Agent profile."""

    def profile_descriptor(
        self,
        role: str,
        *,
        permissions: PermissionScope,
        requirement: NodeCapabilityRequirement,
    ) -> dict[str, object]: ...


class DiscoveryLaneState(V2Contract):
    """Recoverable state for the separately budgeted, non-blocking lane."""

    discovery_run_ref: ArtifactRef
    status: Literal[
        "pending",
        "running",
        "inbox_staged",
        "admitting",
        "admitted",
        "quarantine_recommended",
        "quarantine_dismissed",
        "quarantine_confirmed",
        "failed",
        "deferred",
    ]
    reserved_budget: Budget
    used_budget: BudgetUsage
    baseline_ref: ArtifactRef | None = None
    clue_refs: tuple[ArtifactRef, ...] = ()
    admission_decision_refs: tuple[ArtifactRef, ...] = ()
    recommendation_refs: tuple[ArtifactRef, ...] = ()
    quarantine_review_refs: tuple[ArtifactRef, ...] = ()
    finding_refs: tuple[ArtifactRef, ...] = ()
    inbox_ref: ArtifactRef | None = None
    failure_code: str | None = None

    @model_validator(mode="after")
    def validate_terminal_details(self) -> DiscoveryLaneState:
        if self.status == "failed" and self.failure_code is None:
            raise ValueError("failed Discovery state requires failure_code")
        if self.status != "failed" and self.failure_code is not None:
            raise ValueError("failure_code is only valid for failed Discovery")
        if (
            self.status
            in {
                "inbox_staged",
                "admitting",
                "admitted",
                "quarantine_recommended",
                "quarantine_dismissed",
                "quarantine_confirmed",
            }
            and self.inbox_ref is None
        ):
            raise ValueError(f"{self.status} Discovery state requires an Inbox snapshot")
        if self.status == "quarantine_recommended" and not self.recommendation_refs:
            raise ValueError("quarantine status requires at least one recommendation")
        if self.status == "quarantine_dismissed" and (
            not self.recommendation_refs or not self.quarantine_review_refs
        ):
            raise ValueError("dismissed quarantine requires recommendation and review refs")
        if self.status == "quarantine_confirmed" and (
            not self.recommendation_refs or not self.quarantine_review_refs or not self.finding_refs
        ):
            raise ValueError(
                "confirmed quarantine requires recommendation, review, and Finding refs"
            )
        if self.finding_refs and self.status != "quarantine_confirmed":
            raise ValueError("Discovery Finding refs require confirmed quarantine")
        return self


class GenerateResult(V2Contract):
    """Typed terminal result; failure is data and never a fallback package."""

    run_id: str
    status: GenerateStatus
    request_ref: ArtifactRef
    job_ref: ArtifactRef
    final_snapshot_ref: ArtifactRef
    discovery_run_ref: ArtifactRef | None = None
    discovery_state_ref: ArtifactRef | None = None
    expansion_inbox_ref: ArtifactRef | None = None
    finding_refs: tuple[ArtifactRef, ...] = ()
    package_manifest_ref: ArtifactRef | None = None
    release_ref: ArtifactRef | None = None
    release: ReleaseRecord | None = None
    failure_code: str | None = None
    failure_summary: str | None = None

    @model_validator(mode="after")
    def validate_terminal_shape(self) -> GenerateResult:
        released = self.status == "released"
        release_values = (
            self.package_manifest_ref,
            self.release_ref,
            self.release,
        )
        if released and any(value is None for value in release_values):
            raise ValueError("released result requires manifest and release evidence")
        if not released and any(value is not None for value in release_values):
            raise ValueError("non-released result cannot claim release evidence")
        failure_values = (self.failure_code, self.failure_summary)
        if released and any(value is not None for value in failure_values):
            raise ValueError("released result cannot contain failure metadata")
        if not released and any(value is None for value in failure_values):
            raise ValueError("non-released result requires failure metadata")
        return self


class DiscoveryResumeResult(V2Contract):
    """Terminal outcome of an explicitly resumed, separately budgeted lane."""

    discovery_run_id: str
    status: Literal[
        "admitted",
        "quarantine_recommended",
        "quarantine_dismissed",
        "quarantine_confirmed",
        "failed",
    ]
    spec_ref: ArtifactRef
    state_ref: ArtifactRef
    used_budget: BudgetUsage
    inbox_ref: ArtifactRef | None = None
    recommendation_refs: tuple[ArtifactRef, ...] = ()
    quarantine_review_refs: tuple[ArtifactRef, ...] = ()
    finding_refs: tuple[ArtifactRef, ...] = ()
    failure_code: str | None = None

    @model_validator(mode="after")
    def validate_terminal_details(self) -> DiscoveryResumeResult:
        if self.status == "failed" and self.failure_code is None:
            raise ValueError("failed Discovery resume requires failure_code")
        if self.status != "failed" and self.failure_code is not None:
            raise ValueError("successful Discovery resume cannot carry failure_code")
        if self.status == "quarantine_recommended" and not self.recommendation_refs:
            raise ValueError("quarantine status requires recommendations")
        if self.status == "quarantine_dismissed" and (
            not self.recommendation_refs or not self.quarantine_review_refs
        ):
            raise ValueError("dismissed quarantine requires recommendation and review refs")
        if self.status == "quarantine_confirmed" and (
            not self.recommendation_refs or not self.quarantine_review_refs or not self.finding_refs
        ):
            raise ValueError(
                "confirmed quarantine requires recommendation, review, and Finding refs"
            )
        if self.status != "failed" and self.inbox_ref is None:
            raise ValueError("successful Discovery resume requires an Inbox")
        return self


@dataclass(slots=True)
class _RunState:
    run_id: str
    job_ref: ArtifactRef
    scope_id: str
    ledger: BudgetLedger
    attempts: list[NodeAttempt] = field(default_factory=list)
    latest: dict[str, ArtifactRef] = field(default_factory=dict)
    findings: dict[str, ArtifactRef] = field(default_factory=dict)
    snapshot_revision: int = 0
    last_snapshot_ref: ArtifactRef | None = None
    wall_charged: bool = False
    direct_request_id: str | None = None
    direct_request_fingerprint: str | None = None
    direct_request_ref: ArtifactRef | None = None
    direct_lock: DirectJobLock | None = None
    direct_head: DirectJobHead | None = None
    allow_direct_restart: bool = False
    allow_registry_reconciliation: bool = False
    telemetry_root_span: WorkSpan | None = None
    telemetry_node_spans: dict[str, WorkSpan] = field(default_factory=dict)
    repair_ledger: RepairLedger = field(default_factory=RepairLedger)
    repair_snapshot_lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)
    node_commit_refs: dict[str, ArtifactRef] = field(default_factory=dict)
    research_checkpoint_reuse: tuple[ArtifactRef, ArtifactRef] | None = None
    compile_cleanup: Callable[[], Awaitable[None]] | None = field(
        default=None,
        repr=False,
    )
    last_error_audit_entry_count: int = 0
    last_error_audit_monotonic: float = field(default_factory=time.monotonic)
    error_audit_sequence: int = 0

    def remember(self, *refs: ArtifactRef) -> None:
        for ref in refs:
            self.latest[ref.artifact_id] = ref

    def remember_findings(self, *refs: ArtifactRef) -> None:
        for ref in refs:
            self.findings[ref.revision_id] = ref
            self.remember(ref)


@dataclass(frozen=True, slots=True)
class _ControllerStructuredRepairAuthority(StructuredRepairAuthority):
    controller: FoundryController
    run: _RunState

    async def authorize(
        self,
        *,
        owner_node: Literal["design", "verifier", "build", "judge"],
        lineage_id: str,
        role: str,
        repair_mode: StructuredRepairMode,
        issue_codes: tuple[str, ...],
        continued_session: bool,
        diagnostic: ValidationDiagnostic | None = None,
        feedback_contract_id: str | None = None,
        repair_target: RepairTargetRef | None = None,
    ) -> str:
        async with self.run.repair_snapshot_lock:
            return await self.controller._authorize_structured_repair(
                self.run,
                owner_node=owner_node,
                lineage_id=lineage_id,
                role=role,
                repair_mode=repair_mode,
                issue_codes=issue_codes,
                continued_session=continued_session,
                diagnostic=diagnostic,
                feedback_contract_id=feedback_contract_id,
                repair_target=repair_target,
            )

    async def complete(
        self,
        entry_id: str,
        *,
        remaining_issue_codes: tuple[str, ...],
        continued_session: bool,
        remaining_diagnostic: ValidationDiagnostic | None = None,
    ) -> None:
        async with self.run.repair_snapshot_lock:
            await self.controller._complete_structured_repair(
                self.run,
                entry_id,
                remaining_issue_codes=remaining_issue_codes,
                continued_session=continued_session,
                remaining_diagnostic=remaining_diagnostic,
            )


@dataclass(slots=True)
class _DiscoveryLane:
    spec: DiscoveryRunSpec
    spec_ref: ArtifactRef
    ledger: BudgetLedger
    task: asyncio.Task[DiscoveryBundle]
    state_ref: ArtifactRef
    invocation_budget: Budget
    started_monotonic: float
    admission_task: asyncio.Task[AdmissionBundle] | None = None
    admission_budget: Budget = field(default_factory=Budget)
    discovery_accounted: bool = False
    admission_accounted: bool = False
    admitted: bool = False
    closed: bool = False
    bundle: DiscoveryBundle | None = None
    admission: AdmissionBundle | None = None
    quarantine_reviews: tuple[QuarantineReviewBundle, ...] = ()


@dataclass(frozen=True, slots=True)
class _ReleasePlan:
    """Framework-owned identity/version decision prepared before expensive codegen."""

    package_id: str
    version: str
    identity_ref: ArtifactRef
    semantic_lineage: SemanticLineage
    semantic_lineage_ref: ArtifactRef
    evidence_summary_ref: ArtifactRef


@dataclass(slots=True)
class _DesignerWorkLease:
    """One durable, pre-authorized Designer semantic work order."""

    ledger: LeaseBudgetLedger
    lease: BudgetLease
    lease_ref: ArtifactRef
    controller_owns_structured_repairs: bool = False
    terminal_lease: BudgetLease | None = None
    global_charged: bool = False
    terminal_ref: ArtifactRef | None = None


@dataclass(slots=True)
class _JudgeWorkLease:
    """One durable, pre-authorized independent evaluation work order."""

    ledger: LeaseBudgetLedger
    lease: BudgetLease
    lease_ref: ArtifactRef
    terminal_lease: BudgetLease | None = None
    global_charged: bool = False
    terminal_ref: ArtifactRef | None = None


@dataclass(slots=True)
class _AgentInvocationWorkLease:
    """Durable reservation for one repair-time real Agent invocation."""

    ledger: LeaseBudgetLedger
    lease: BudgetLease
    lease_ref: ArtifactRef
    terminal_lease: BudgetLease | None = None
    global_charged: bool = False
    terminal_ref: ArtifactRef | None = None


@dataclass(frozen=True, slots=True)
class _PendingRepairActions:
    """Executed repair awaiting an independent next-report outcome."""

    directives: tuple[RepairDirective, ...]
    session_strategy: Literal["continued", "fresh", "none"]
    action_usage: BudgetUsage
    invalidated_refs: tuple[ArtifactRef, ...] = ()


class _GenerationHalt(RuntimeError):
    def __init__(
        self,
        *,
        status: GenerateStatus,
        code: str,
        summary: str,
        finding_refs: tuple[ArtifactRef, ...] = (),
    ) -> None:
        super().__init__(summary)
        self.status = status
        self.code = code
        self.summary = summary
        self.finding_refs = finding_refs


class _DesignReworkRequired(RuntimeError):
    """Typed upstream loop edge; it is handled only by the Controller."""

    def __init__(
        self,
        *,
        findings: Sequence[Finding],
        finding_refs: Sequence[ArtifactRef],
        additional_evidence: Sequence[Evidence] = (),
        challenged_claim_ids: Sequence[str] = (),
        directive_refs: Sequence[ArtifactRef] = (),
        revision_mode: DesignRevisionMode = DesignRevisionMode.FULL_SEMANTIC_REVISION,
    ) -> None:
        if not findings or len(findings) != len(finding_refs):
            raise ValueError("design rework requires aligned findings and refs")
        if any(finding.owner != "design" for finding in findings):
            raise ValueError("design rework accepts only design-owned findings")
        if directive_refs and len(set(directive_refs)) != len(directive_refs):
            raise ValueError("design rework directive refs must be unique RepairActions")
        super().__init__("an upstream EnvironmentDesign revision is required")
        self.findings = tuple(findings)
        self.finding_refs = tuple(finding_refs)
        self.additional_evidence = tuple(additional_evidence)
        self.challenged_claim_ids = tuple(dict.fromkeys(challenged_claim_ids))
        self.directive_refs = tuple(directive_refs)
        self.revision_mode = revision_mode


class FoundryController:
    """Run Direct Generation to a real Registry release or an honest terminal state."""

    def __init__(
        self,
        *,
        config: FoundryConfig,
        artifact_store: ArtifactWriter,
        expansion_artifact_store: ArtifactWriter,
        profile_provider: ProfileDescriptorProvider,
        designer: EnvironmentDesigner,
        discovery: DiscoveryService,
        expansion_designer: ExpansionDesigner,
        expansion_source: ExpansionSource,
        builder: EnvironmentBuilder,
        verifier_compiler: VerifierCompiler,
        judge: EnvironmentJudge,
        registry: EnvironmentRegistry,
        telemetry: TelemetryStore | None = None,
        invocation_control: InvocationControlStore | None = None,
        error_audit_policy: ErrorAuditPolicy | None = None,
        known_secret_canaries: Sequence[str | bytes] = (),
    ) -> None:
        self.config = config
        self.artifacts = artifact_store
        self.expansion_artifacts = expansion_artifact_store
        self.profiles = profile_provider
        self.designer = designer
        self.discovery = discovery
        self.expansion_designer = expansion_designer
        self.expansion_source = expansion_source
        self.builder = builder
        self.verifier_compiler = verifier_compiler
        self.judge = judge
        self.registry = registry
        self.telemetry = telemetry
        self.invocation_control = invocation_control
        self.route_liveness_checker = (
            InvocationControlRouteLivenessChecker(invocation_control)
            if invocation_control is not None
            else None
        )
        self.error_audit_policy = error_audit_policy or ErrorAuditPolicy()
        self.code_router = CodeRouter()
        self.quarantine_review_policy = QuarantineReviewPolicy(artifact_store=self.artifacts)
        self.workspace_root = (config.state_root / "runs").expanduser().resolve()
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        self.direct_jobs = DirectJobStore(config.state_root / "direct-jobs")
        self.work_control = WorkControlStore(config.state_root / "work-control")
        self.scene_projector = SceneProjector(
            root=ObservabilityRoot(config.state_root),
            artifacts=self.artifacts,
            heads=self.work_control,
            telemetry=self.telemetry,
            invocation_control=self.invocation_control,
            known_secret_canaries=known_secret_canaries,
        )
        self.direct_work_runner = (
            DirectWorkRunner(
                artifacts=self.artifacts,
                heads=self.work_control,
                designer=self.designer,
                builder=self.builder,
                verifier_compiler=self.verifier_compiler,
                judge=self.judge,
                registry=self.registry,
                telemetry=self.telemetry,
                workspace_root=self.workspace_root / "scheduler-direct",
                structured_turn_token_limit=config.agent.structured_turn_token_limit,
                structured_turn_wall_seconds=config.agent.structured_invocation_timeout_seconds,
                environment_codegen_session_token_limit=(
                    config.agent.environment_codegen_turn_token_limit
                ),
                environment_codegen_session_wall_seconds=(
                    config.agent.environment_codegen_invocation_timeout_seconds
                ),
                environment_codegen_physical_turn_token_limit=(
                    config.agent.environment_codegen_physical_turn_token_limit
                ),
                model_routes=config.agent.model_routes,
                route_liveness_checker=self.route_liveness_checker,
                require_route_liveness_gate=self.route_liveness_checker is not None,
                infrastructure_retry_backoff_seconds=(
                    config.agent.infrastructure_retry_backoff_seconds
                ),
                maximum_same_model_infrastructure_retries=(
                    config.agent.maximum_same_model_infrastructure_retries
                ),
                # A Scheduler wave must use the same admission capacity as the
                # routed InvocationBackend.  Otherwise it can mark many Work
                # heads running while their calls are merely queued outside
                # the Provider boundary, which makes liveness/scene evidence
                # ambiguous and defeats configured ToolSemantics parallelism.
                maximum_concurrency=config.agent.max_concurrent_invocations,
                projector=self.scene_projector,
            )
            if self.telemetry is not None
            else None
        )
        self.campaign_store = CampaignStore(config.state_root / "campaigns")
        self.expansion_runner = ExpansionCampaignRunner(
            artifact_store=self.expansion_artifacts,
            registry=self.registry,
            campaign_store=self.campaign_store,
            candidate_executor=self,
            expansion_source=self.expansion_source,
            source_workspace_root=config.state_root / "expansion-source-runs",
        )

    def _workspace_for(self, logical_id: str, *parts: str) -> Path:
        """Map a logical artifact/run id to a portable physical directory."""

        readable = "".join(
            character
            if character.isascii() and (character.isalnum() or character in "._-")
            else "-"
            for character in logical_id
        ).strip("-._")
        digest = hashlib.sha256(logical_id.encode("utf-8")).hexdigest()[:16]
        directory = f"{(readable or 'workspace')[:64]}-{digest}"
        return self.workspace_root.joinpath(directory, *parts)

    async def generate(
        self,
        need: str,
        *,
        request_id: str | None = None,
        permissions: PermissionScope | None = None,
        budget: Budget | None = None,
        release_profile: ReleaseProfile | None = None,
        discovery_budget: Budget | None = None,
        enable_discovery: bool = True,
    ) -> GenerateResult:
        """Generate once per request id, or return its exact durable terminal result.

        The request id is an idempotency key over the canonical request and Direct
        execution policy.  Reusing it for different semantics is a hard conflict.
        Unknown in-flight Agent work is never replayed as though it were free.
        """

        selected_budget = budget or self.config.generation_budget
        selected_release = release_profile or self.config.release_profile
        selected_permissions = permissions or PermissionScope()
        selected_request_id = request_id or f"request:{uuid.uuid4().hex}"
        selected_discovery_budget = discovery_budget or self.config.discovery_budget
        request = EnvironmentRequest(
            request_id=selected_request_id,
            need=need,
            permissions=selected_permissions,
            budget=selected_budget,
            release_profile=selected_release,
        )
        request_fingerprint = self._direct_request_fingerprint(
            request,
            enable_discovery=enable_discovery,
            discovery_budget=selected_discovery_budget,
        )
        with self.direct_jobs.exclusive(selected_request_id) as direct_lock:
            existing = self.direct_jobs.read_head(selected_request_id)
            if existing is not None:
                if existing.request_fingerprint != request_fingerprint:
                    raise DirectRequestConflictError(
                        "request-id is already bound to different canonical request semantics"
                    )
                return await self._load_or_recover_direct_result(
                    head=existing,
                    request=request,
                    direct_lock=direct_lock,
                )
            return await self._generate_new_locked(
                request=request,
                request_fingerprint=request_fingerprint,
                selected_discovery_budget=selected_discovery_budget,
                enable_discovery=enable_discovery,
                direct_lock=direct_lock,
            )

    async def run_semantic_prefix(
        self,
        need: str,
        *,
        request_id: str | None = None,
        permissions: PermissionScope | None = None,
        budget: Budget | None = None,
        release_profile: ReleaseProfile | None = None,
    ) -> SemanticPrefixRun:
        """Run a fresh normal semantic prefix without creating release state.

        This staged debugging boundary deliberately does not enter
        ``DirectJobStore`` and cannot return ``GenerateResult``.  The caller
        supplies a fresh physical state root, while this Controller still owns
        the canonical Request, Job, GenerationContext, and framework event
        lineage consumed by the unchanged Scheduler runner.
        """

        if self.direct_work_runner is None:
            raise DirectJobStoreError("Direct WorkGraph requires configured telemetry")
        selected_budget = budget or self.config.generation_budget
        selected_release = release_profile or self.config.release_profile
        selected_permissions = permissions or PermissionScope()
        selected_request_id = request_id or f"semantic-prefix-request:{uuid.uuid4().hex}"
        request = EnvironmentRequest(
            request_id=selected_request_id,
            need=need,
            permissions=selected_permissions,
            budget=selected_budget,
            release_profile=selected_release,
        )
        request_ref = self.artifacts.put_json(
            artifact_id=self._stable_id("request-artifact", selected_request_id),
            artifact_type="control.environment_request",
            value=request,
        )
        job_id = self._stable_id(
            "generate-job",
            selected_request_id,
            request_ref.revision_id,
        )
        job = EnvironmentJob(
            job_id=job_id,
            kind="generate",
            request_ref=request_ref,
            permissions=selected_permissions,
            budget=selected_budget,
            release_profile=selected_release,
        )
        job_ref = self.artifacts.put_json(
            artifact_id=f"{job_id}:job",
            artifact_type="control.environment_job",
            value=job,
            dependencies=(request_ref,),
        )
        context = GenerationContext(
            context_id=f"generation-context:{job_id}",
            job_ref=job_ref,
            kind="generate",
            request_ref=request_ref,
            permissions=selected_permissions,
            budget=selected_budget,
            release_profile=selected_release,
        )
        context_ref = self.artifacts.put_json(
            artifact_id=context.context_id,
            artifact_type="control.generation_context",
            value=context,
            dependencies=context.root_refs,
        )
        run_id = f"semantic-prefix:{uuid.uuid4().hex}"
        self.artifacts.record_event(
            event_type="generation_semantic_prefix_started",
            subject_ref=job_ref,
            related_refs=(request_ref, context_ref),
            details=(
                KeyValue(key="engine", value="scheduler-workgraph"),
                KeyValue(key="release_attempted", value="false"),
            ),
        )
        outcome = await self.direct_work_runner.run_semantic_prefix(
            context_ref=context_ref,
            run_id=run_id,
        )
        self.artifacts.record_event(
            event_type="generation_semantic_prefix_finished",
            subject_ref=job_ref,
            related_refs=tuple(
                ref
                for ref in (
                    context_ref,
                    outcome.bootstrap_epoch_ref,
                    outcome.world_epoch_ref,
                    outcome.design_epoch_ref,
                    outcome.modeling_commit_ref,
                    outcome.verifier_plan_commit_ref,
                )
                if ref is not None
            ),
            details=(KeyValue(key="status", value=outcome.status),),
        )
        return outcome

    async def resume_generation(
        self,
        request_id: str,
        *,
        adopt_config_budget: bool = False,
        from_frozen_epoch: str | None = None,
        from_coordinate: str | None = None,
    ) -> GenerateResult:
        """Resume one selected stopped node from an immutable graph epoch.

        The selected node consumes the exact committed output closure of its
        frozen ancestors. It receives a fresh physical attempt only when an
        explicit control authority binds the old terminal attempt; downstream
        work is then scheduled normally. This is deliberately not an entry
        point for rerunning a whole pipeline.
        """

        return await self._resume_generation_from_frozen_node(
            request_id,
            adopt_config_budget=adopt_config_budget,
            from_frozen_epoch=from_frozen_epoch,
            from_coordinate=from_coordinate,
        )

    async def _resume_generation_from_frozen_node(
        self,
        request_id: str,
        *,
        adopt_config_budget: bool,
        from_frozen_epoch: str | None,
        from_coordinate: str | None,
    ) -> GenerateResult:
        """Resume one exact stopped coordinate without replaying its prefix."""

        with self.direct_jobs.exclusive(request_id) as direct_lock:
            head = self.direct_jobs.read_head(request_id)
            if head is None:
                raise DirectJobStoreError("Direct Generation request does not exist")
            request = self.artifacts.get_json(head.request_ref, EnvironmentRequest)
            job = self.artifacts.get_json(head.job_ref, EnvironmentJob)
            self.artifacts.require_exact_json(
                head.request_ref,
                request,
                artifact_types=("control.environment_request",),
            )
            self.artifacts.require_exact_json(
                head.job_ref,
                job,
                artifact_types=("control.environment_job",),
            )
            if request.request_id != request_id or job.request_ref != head.request_ref:
                raise DirectJobStoreError("Direct head does not bind its resumable request/job")
            if head.status == "released":
                return await self._load_or_recover_direct_result(
                    head=head,
                    request=request,
                    direct_lock=direct_lock,
                )

            if head.status == "running":
                # Holding the writer lock proves the previous Controller is no
                # longer live. Make the interruption durable before selecting
                # a recovery source so later recovery never guesses from an
                # orphaned mutable head.
                await self._terminalize_abandoned_direct_head(
                    head=head,
                    request=request,
                    direct_lock=direct_lock,
                )
                head = self.direct_jobs.read_head(request_id)
                if head is None:
                    raise DirectJobStoreError("abandoned Direct head disappeared during recovery")
            if head.status not in {"failed", "needs_human", "budget_exhausted"}:
                raise DirectJobResumeRequiredError(
                    "Direct Generation must be terminal before node-level recovery"
                )
            if head.result_ref is None:
                await self._load_or_recover_direct_result(
                    head=head,
                    request=request,
                    direct_lock=direct_lock,
                )
                head = self.direct_jobs.read_head(request_id)
                if head is None or head.result_ref is None:
                    raise DirectJobStoreError("terminal Direct head lacks a persisted result")

            # An explicit epoch without a stopped coordinate means something
            # materially different from retry: the caller is selecting a
            # fully committed checkpoint and asks us to derive *only* its next
            # causal epoch.  This is the durable escape hatch after fixing a
            # framework bug which made a later historical epoch incoherent.
            # It never guesses a chronological frontier and never replays the
            # selected epoch's own nodes.
            if from_frozen_epoch is not None and from_coordinate is None:
                if adopt_config_budget:
                    raise DirectJobResumeRequiredError(
                        "a committed-frontier continuation cannot amend a budget; "
                        "budget amendments bind one unstarted stopped node"
                    )
                (
                    snapshot_ref,
                    snapshot,
                    context_ref,
                    epoch_ref,
                ) = self._select_frozen_resume_frontier(
                    head=head,
                    from_frozen_epoch=from_frozen_epoch,
                )
                self.artifacts.record_event(
                    event_type="generation_resume_requested",
                    subject_ref=head.job_ref,
                    related_refs=(
                        head.job_ref,
                        head.result_ref,
                        snapshot_ref,
                        context_ref,
                        epoch_ref,
                    ),
                    details=(
                        KeyValue(key="previous_run_id", value=snapshot.run_id),
                        KeyValue(key="recovery_epoch", value=epoch_ref.artifact_id),
                        KeyValue(key="recovery_mode", value="committed_frontier_successor"),
                        KeyValue(key="budget_amended", value="false"),
                    ),
                )
                return await self._execute_direct_locked(
                    request=request,
                    request_fingerprint=head.request_fingerprint,
                    selected_discovery_budget=self.config.discovery_budget,
                    enable_discovery=False,
                    direct_lock=direct_lock,
                    job=job,
                    job_ref=head.job_ref,
                    request_ref=head.request_ref,
                    prior_head=head,
                    recovery_snapshot=snapshot,
                    recovery_snapshot_ref=snapshot_ref,
                    recovery_context_ref=context_ref,
                    recovery_epoch_ref=epoch_ref,
                    recovery_frontier=True,
                    effective_budget=snapshot.reserved_budget,
                )

            (
                snapshot_ref,
                snapshot,
                context_ref,
                epoch_ref,
                coordinate,
                definition,
            ) = self._select_frozen_resume_target(
                head=head,
                from_frozen_epoch=from_frozen_epoch,
                from_coordinate=from_coordinate,
            )
            work_head = self.work_control.read_head(coordinate)
            if (
                work_head is None
                or work_head.work_id != definition.work_id
                or work_head.definition_digest != definition.definition_digest
                or work_head.acceptance_digest != definition.acceptance_digest
            ):
                raise DirectJobResumeRequiredError(
                    "selected node no longer has the exact frozen definition closure"
                )
            resume_state = self._frozen_resume_state(
                context_ref=context_ref,
                epoch_ref=epoch_ref,
                coordinate=coordinate,
            )
            if resume_state is None:
                raise DirectJobResumeRequiredError(
                    "selected node is no longer a resumable frozen frontier"
                )

            amendment_ref: ArtifactRef | None = None
            effective_budget = snapshot.reserved_budget
            if adopt_config_budget:
                if resume_state == "stale":
                    raise DirectJobResumeRequiredError(
                        "a stale descendant already has a valid parent revision; "
                        "it must be re-derived, not treated as a budget-admission retry"
                    )
                amendment_ref = self._authorize_scope_budget_amendment_for_target(
                    job=job,
                    source_snapshot_ref=snapshot_ref,
                    source_snapshot=snapshot,
                    source_epoch_ref=epoch_ref,
                    definition=definition,
                    amended_budget=self.config.generation_budget,
                )
                amendment = self.artifacts.get_json(amendment_ref, ScopeBudgetAmendment)
                effective_budget = amendment.amended_reserved

            authority_ref: ArtifactRef | None = None
            recovery_mode: str
            if resume_state == "stale":
                # The node has a durable terminal head, but its exact
                # parent-output closure has changed.  This is not an operator
                # retry of the old attempt: Scheduler owns the supersession
                # and opens a new attempt with the current parent Artifact.
                recovery_mode = "causal_descendant_refresh"
            elif work_head.status == "repair_authorized":
                if amendment_ref is not None:
                    raise DirectJobResumeRequiredError(
                        "a semantic repair already has its own authority; "
                        "budget amendment is not a retry"
                    )
                recovery_mode = "scheduler_owned_repair"
            elif work_head.status == "running":
                # The Direct writer lock is held and the Direct head has
                # already been terminalized above, so this is not a second
                # live Scheduler.  The Work head is the exact crash boundary:
                # let DirectWorkRunner reconcile its unfinished OperationRun
                # under the frozen definition before it schedules anything.
                # In particular, do not manufacture a terminal-retry
                # authority for an attempt that never reached a terminal
                # decision.
                recovery_mode = "abandoned_operation_reconciliation"
            else:
                authority_ref = self._authorize_node_resume(
                    snapshot_ref=snapshot_ref,
                    context_ref=context_ref,
                    epoch_ref=epoch_ref,
                    definition=definition,
                    source_attempt_ref=work_head.attempt_ref,
                    source_input_fingerprint=work_head.input_fingerprint,
                    budget_amendment_ref=amendment_ref,
                )
                recovery_mode = "terminal_node_retry"

            self.artifacts.record_event(
                event_type="generation_resume_requested",
                subject_ref=head.job_ref,
                related_refs=tuple(
                    ref
                    for ref in (
                        head.job_ref,
                        head.result_ref,
                        snapshot_ref,
                        context_ref,
                        epoch_ref,
                        amendment_ref,
                        authority_ref,
                    )
                    if ref is not None
                ),
                details=(
                    KeyValue(key="previous_run_id", value=snapshot.run_id),
                    KeyValue(key="recovery_coordinate", value=coordinate.coordinate_key),
                    KeyValue(key="recovery_epoch", value=epoch_ref.artifact_id),
                    KeyValue(key="recovery_mode", value=recovery_mode),
                    KeyValue(key="budget_amended", value=str(amendment_ref is not None).lower()),
                ),
            )
            return await self._execute_direct_locked(
                request=request,
                request_fingerprint=head.request_fingerprint,
                selected_discovery_budget=self.config.discovery_budget,
                enable_discovery=False,
                direct_lock=direct_lock,
                job=job,
                job_ref=head.job_ref,
                request_ref=head.request_ref,
                prior_head=head,
                recovery_snapshot=snapshot,
                recovery_snapshot_ref=snapshot_ref,
                recovery_context_ref=context_ref,
                recovery_epoch_ref=epoch_ref,
                recovery_coordinate=coordinate,
                resume_authority_ref=authority_ref,
                effective_budget=effective_budget,
            )

    def _select_frozen_resume_frontier(
        self,
        *,
        head: DirectJobHead,
        from_frozen_epoch: str,
    ) -> tuple[ArtifactRef, JobRunSnapshot, ArtifactRef, ArtifactRef]:
        """Resolve one caller-pinned completed epoch without chronology guesses.

        The Controller proves the selected epoch belongs to the current Direct
        job and retains an immutable definition closure.  The Runner then
        proves that every one of those definitions still has an active commit
        immediately before it advances the causal suffix.  Keeping that second
        proof at the execution boundary closes the race between selection and
        scheduling without treating a stale epoch as a new root run.
        """

        snapshot_ref = head.snapshot_ref
        snapshot = self.artifacts.get_json(snapshot_ref, JobRunSnapshot)
        self.artifacts.require_exact_json(
            snapshot_ref,
            snapshot,
            artifact_types=("control.job_run_snapshot",),
        )
        if (
            snapshot.job_ref != head.job_ref
            or snapshot.run_id != head.run_id
            or snapshot.revision != head.snapshot_revision
        ):
            raise DirectJobResumeRequiredError(
                "current Direct head does not bind its exact recovery snapshot"
            )

        context_refs = tuple(
            dict.fromkeys(
                ref
                for ref in snapshot.latest_artifact_refs
                if ref.artifact_type == "control.generation_context"
            )
        )
        if len(context_refs) > 1:
            raise DirectJobResumeRequiredError(
                "current Direct snapshot has multiple GenerationContext roots"
            )
        if not context_refs:
            # Old compact snapshots can omit the context/epoch projection. A
            # same-job lookup is still exact because the immutable context
            # binds the DirectJob Artifact, rather than wall time or a latest
            # state entry.
            context_refs = tuple(
                ref
                for ref in self.artifacts.list_revisions()
                if ref.artifact_type == "control.generation_context"
                and self.artifacts.get_json(ref, GenerationContext).job_ref == head.job_ref
            )
        if not context_refs:
            raise DirectJobResumeRequiredError(
                "no exact GenerationContext is available for committed-frontier recovery"
            )

        candidates: list[tuple[ArtifactRef, ArtifactRef]] = []
        for context_ref in context_refs:
            context = self.artifacts.get_json(context_ref, GenerationContext)
            self.artifacts.require_exact_json(
                context_ref,
                context,
                artifact_types=("control.generation_context",),
            )
            if context.job_ref != head.job_ref:
                continue
            for epoch_ref in self.artifacts.list_revisions():
                matches_epoch = from_frozen_epoch in {
                    epoch_ref.artifact_id,
                    epoch_ref.revision_id,
                }
                if epoch_ref.artifact_type != "control.work_graph_epoch" or not matches_epoch:
                    continue
                epoch = self.artifacts.get_json(epoch_ref, WorkGraphEpoch)
                self.artifacts.require_exact_json(
                    epoch_ref,
                    epoch,
                    artifact_types=("control.work_graph_epoch",),
                )
                if epoch.context_ref != context_ref:
                    continue
                manifest = self.artifacts.get_json(epoch.manifest_ref, WorkGraphManifest)
                # This is a selection-time topology proof only.  Current
                # WorkHead/Commit activeness is intentionally rechecked in the
                # Runner just before suffix dispatch.
                for binding in manifest.node_bindings:
                    self._frozen_work_definition(
                        coordinate=binding.coordinate,
                        work_id=binding.work_id,
                        definition_digest=binding.definition_digest,
                    )
                candidates.append((context_ref, epoch_ref))

        unique = tuple(dict.fromkeys(candidates))
        if len(unique) == 1:
            context_ref, epoch_ref = unique[0]
            return snapshot_ref, snapshot, context_ref, epoch_ref
        if not unique:
            raise DirectJobResumeRequiredError(
                "no exact frozen epoch belongs to this Direct job; "
                "inspect the same run before selecting a committed frontier"
            )
        raise DirectJobResumeRequiredError(
            "frozen epoch artifact id has multiple revisions; "
            "select its exact revision id for committed-frontier recovery"
        )

    def _select_frozen_resume_target(
        self,
        *,
        head: DirectJobHead,
        from_frozen_epoch: str | None,
        from_coordinate: str | None,
    ) -> tuple[
        ArtifactRef,
        JobRunSnapshot,
        ArtifactRef,
        ArtifactRef,
        WorkCoordinate,
        WorkDefinition,
    ]:
        """Select one exact Context/Epoch/WorkHead recovery closure.

        A ``JobRunSnapshot`` is a terminal/run summary.  It is useful to bind
        the Direct restart to its current job, but it must not become the
        authority that decides whether a durable ``WorkGraphEpoch`` exists:
        a controller crash between epoch persistence and snapshot projection
        used to make a perfectly intact node unrecoverable.  The immutable
        GenerationContext, epoch, manifest, active WorkCommit closure and
        stopped WorkHead are the recovery proof; no candidate is adopted by
        timestamp or artifact iteration order.
        """

        snapshot_ref = head.snapshot_ref
        snapshot = self.artifacts.get_json(snapshot_ref, JobRunSnapshot)
        self.artifacts.require_exact_json(
            snapshot_ref,
            snapshot,
            artifact_types=("control.job_run_snapshot",),
        )
        if (
            snapshot.job_ref != head.job_ref
            or snapshot.run_id != head.run_id
            or snapshot.revision != head.snapshot_revision
        ):
            raise DirectJobResumeRequiredError(
                "current Direct head does not bind its exact recovery snapshot"
            )

        context_refs: list[ArtifactRef] = []
        snapshot_contexts = tuple(
            ref
            for ref in snapshot.latest_artifact_refs
            if ref.artifact_type == "control.generation_context"
        )
        if len(snapshot_contexts) > 1:
            raise DirectJobResumeRequiredError(
                "current Direct snapshot has multiple GenerationContext roots"
            )
        if snapshot_contexts:
            context_refs.extend(snapshot_contexts)
        else:
            # Older terminal wrappers may have lost their compact snapshot
            # projection.  Discover a root only by exact immutable job
            # binding, never by the latest Artifact or by wall-clock order.
            for candidate_ref in self.artifacts.list_revisions():
                if candidate_ref.artifact_type != "control.generation_context":
                    continue
                candidate_context = self.artifacts.get_json(candidate_ref, GenerationContext)
                if candidate_context.job_ref == head.job_ref:
                    context_refs.append(candidate_ref)
        context_refs = list(dict.fromkeys(context_refs))
        if not context_refs:
            raise DirectJobResumeRequiredError(
                "no exact GenerationContext is available for frozen-node recovery"
            )

        candidates: list[
            tuple[
                ArtifactRef,
                JobRunSnapshot,
                ArtifactRef,
                ArtifactRef,
                WorkCoordinate,
                WorkDefinition,
                FrozenResumeState,
            ]
        ] = []
        evidence_counts = {
            "contexts": 0,
            "epochs": 0,
            "selector_matches": 0,
            "definition_matches": 0,
            "resumable_frontiers": 0,
        }
        epoch_refs = tuple(
            ref
            for ref in self.artifacts.list_revisions()
            if ref.artifact_type == "control.work_graph_epoch"
        )
        for context_ref in context_refs:
            context = self.artifacts.get_json(context_ref, GenerationContext)
            self.artifacts.require_exact_json(
                context_ref,
                context,
                artifact_types=("control.generation_context",),
            )
            if context.job_ref != head.job_ref:
                continue
            evidence_counts["contexts"] += 1
            for epoch_ref in epoch_refs:
                epoch = self.artifacts.get_json(epoch_ref, WorkGraphEpoch)
                if epoch.context_ref != context_ref:
                    continue
                self.artifacts.require_exact_json(
                    epoch_ref,
                    epoch,
                    artifact_types=("control.work_graph_epoch",),
                )
                if from_frozen_epoch is not None and from_frozen_epoch not in {
                    epoch_ref.artifact_id,
                    epoch_ref.revision_id,
                }:
                    continue
                evidence_counts["epochs"] += 1
                manifest = self.artifacts.get_json(epoch.manifest_ref, WorkGraphManifest)
                states = self._frozen_epoch_schedule_states(
                    context_ref=context_ref,
                    epoch_ref=epoch_ref,
                    epoch=epoch,
                    manifest=manifest,
                )
                for binding in manifest.node_bindings:
                    if from_coordinate is not None and not self._coordinate_selector_matches(
                        binding.coordinate,
                        from_coordinate,
                    ):
                        continue
                    evidence_counts["selector_matches"] += 1
                    definition = self._frozen_work_definition(
                        coordinate=binding.coordinate,
                        work_id=binding.work_id,
                        definition_digest=binding.definition_digest,
                    )
                    work_head = self.work_control.read_head(binding.coordinate)
                    if (
                        work_head is None
                        or work_head.work_id != definition.work_id
                        or work_head.definition_digest != definition.definition_digest
                        or work_head.acceptance_digest != definition.acceptance_digest
                    ):
                        continue
                    evidence_counts["definition_matches"] += 1
                    scheduled_state = states.get(binding.coordinate.coordinate_key)
                    if scheduled_state not in {
                        "stale",
                        "repair_ready",
                        "running",
                        "blocked",
                    }:
                        continue
                    # A committed child whose parent has a newer accepted
                    # revision is logically ``stale``.  Its physical head is
                    # still committed by design, so status-only recovery used
                    # to skip it and leave later gates consuming historic
                    # Candidate evidence.  The frozen Scheduler snapshot is
                    # the authority for this causal-frontier classification.
                    resume_state = cast(FrozenResumeState, scheduled_state)
                    evidence_counts["resumable_frontiers"] += 1
                    candidates.append(
                        (
                            snapshot_ref,
                            snapshot,
                            context_ref,
                            epoch_ref,
                            binding.coordinate,
                            definition,
                            resume_state,
                        )
                    )

        # A coordinate retained by a later epoch is one logical candidate. If
        # the user did not explicitly pin an epoch, use its first topology
        # boundary so recovery starts from the smallest valid graph. Different
        # epoch revisions at that same boundary are semantic alternatives, so
        # fail closed rather than selecting by file/list order.
        ResumeCandidate = tuple[
            ArtifactRef,
            JobRunSnapshot,
            ArtifactRef,
            ArtifactRef,
            WorkCoordinate,
            WorkDefinition,
            FrozenResumeState,
        ]
        by_binding: dict[tuple[str, str], ResumeCandidate] = {}
        for resume_candidate in candidates:
            binding_key = (
                resume_candidate[4].coordinate_key,
                resume_candidate[3].revision_id,
            )
            prior = by_binding.get(binding_key)
            if prior is not None and prior != resume_candidate:
                raise DirectJobResumeRequiredError(
                    "one frozen epoch has conflicting recovery bindings"
                )
            by_binding[binding_key] = resume_candidate
        by_coordinate: dict[str, tuple[ResumeCandidate, ...]] = {}
        for resume_candidate in by_binding.values():
            coordinate_key = resume_candidate[4].coordinate_key
            by_coordinate[coordinate_key] = (
                *by_coordinate.get(coordinate_key, ()),
                resume_candidate,
            )

        selected: list[ResumeCandidate] = []
        ambiguous_epoch_keys: list[str] = []
        for coordinate_key, bindings in by_coordinate.items():
            earliest_rank = min(self._epoch_rank(item[3]) for item in bindings)
            earliest = tuple(
                item for item in bindings if self._epoch_rank(item[3]) == earliest_rank
            )
            if len(earliest) != 1:
                ambiguous_epoch_keys.append(coordinate_key)
                continue
            selected.append(earliest[0])
        if ambiguous_epoch_keys:
            raise DirectJobResumeRequiredError(
                "multiple frozen revisions contain the selected stopped coordinate; "
                "resume requires --from-frozen-epoch. Coordinates: "
                + ", ".join(sorted(ambiguous_epoch_keys))
            )
        # A stale/repair/running coordinate is a closer causal frontier than
        # an old blocked descendant.  Prefer it so a resume never asks the
        # operator to retry a Release result that was produced from a
        # superseded Candidate.  Independent frontiers at the same priority
        # still require an explicit coordinate rather than guessing.
        state_priority = {
            "stale": 0,
            "repair_ready": 1,
            "running": 2,
            "blocked": 3,
        }
        if selected:
            best_priority = min(state_priority[item[6]] for item in selected)
            selected = [
                item for item in selected if state_priority[item[6]] == best_priority
            ]
        selected.sort(key=lambda item: (item[4].coordinate_key, item[3].revision_id))
        if len(selected) == 1:
            (
                selected_snapshot_ref,
                selected_snapshot,
                selected_context_ref,
                selected_epoch_ref,
                selected_coordinate,
                selected_definition,
                _selected_state,
            ) = selected[0]
            return (
                selected_snapshot_ref,
                selected_snapshot,
                selected_context_ref,
                selected_epoch_ref,
                selected_coordinate,
                selected_definition,
            )
        if not selected:
            selector = from_coordinate or from_frozen_epoch or "current causal frontier"
            raise DirectJobResumeRequiredError(
                f"no exact resumable frozen frontier matches {selector!r}; "
                "recovery evidence="
                + ", ".join(f"{key}={value}" for key, value in sorted(evidence_counts.items()))
                + "; inspect observe scene first"
            )
        options = ", ".join(item[4].coordinate_key for item in selected)
        raise DirectJobResumeRequiredError(
            "multiple causal frontiers are eligible; resume requires --from-coordinate. "
            f"Canonical coordinates: {options}"
        )

    def _frozen_resume_state(
        self,
        *,
        context_ref: ArtifactRef,
        epoch_ref: ArtifactRef,
        coordinate: WorkCoordinate,
    ) -> FrozenResumeState | None:
        """Return the Scheduler-owned state for one selected recovery coordinate."""

        states = self._frozen_epoch_schedule_states(
            context_ref=context_ref,
            epoch_ref=epoch_ref,
        )
        state = states.get(coordinate.coordinate_key)
        if state in {"stale", "repair_ready", "running", "blocked"}:
            return cast(FrozenResumeState, state)
        return None

    def _frozen_epoch_schedule_states(
        self,
        *,
        context_ref: ArtifactRef,
        epoch_ref: ArtifactRef,
        epoch: WorkGraphEpoch | None = None,
        manifest: WorkGraphManifest | None = None,
    ) -> dict[str, str]:
        """Reconstruct one frozen graph and classify its current causal frontier.

        Work heads persist physical status only.  The Scheduler additionally
        proves whether each head still binds the current parent-output closure;
        that is the sole safe way to discover a committed-but-stale consumer
        after an upstream Candidate revision.
        """

        loaded_epoch = epoch or self.artifacts.get_json(epoch_ref, WorkGraphEpoch)
        self.artifacts.require_exact_json(
            epoch_ref,
            loaded_epoch,
            artifact_types=("control.work_graph_epoch",),
        )
        if loaded_epoch.context_ref != context_ref:
            raise DirectJobResumeRequiredError(
                "frozen epoch does not bind the selected GenerationContext"
            )
        loaded_manifest = manifest or self.artifacts.get_json(
            loaded_epoch.manifest_ref,
            WorkGraphManifest,
        )
        self.artifacts.require_exact_json(
            loaded_epoch.manifest_ref,
            loaded_manifest,
            artifact_types=("control.work_graph_manifest",),
        )
        definitions = tuple(
            self._frozen_work_definition(
                coordinate=binding.coordinate,
                work_id=binding.work_id,
                definition_digest=binding.definition_digest,
            )
            for binding in loaded_manifest.node_bindings
        )
        groups = tuple(
            WorkGroupDefinition(
                group_id=binding.group_id,
                scope_id=loaded_manifest.scope_id,
                member_coordinates=binding.member_coordinates,
                aggregate_coordinate=binding.aggregate_coordinate,
            )
            for binding in loaded_manifest.group_bindings
        )
        if any(
            group.content_digest() != binding.group_digest
            for group, binding in zip(groups, loaded_manifest.group_bindings, strict=True)
        ):
            raise DirectJobResumeRequiredError("frozen WorkGraph group binding is inconsistent")
        milestones = tuple(
            WorkGraphMilestone(
                milestone_id=binding.milestone_id,
                kind=binding.kind,
                required_coordinates=binding.required_coordinates,
                establishes=binding.establishes,
            )
            for binding in loaded_manifest.milestone_bindings
        )
        if any(
            milestone.content_digest() != binding.milestone_digest
            for milestone, binding in zip(
                milestones,
                loaded_manifest.milestone_bindings,
                strict=True,
            )
        ):
            raise DirectJobResumeRequiredError("frozen WorkGraph milestone binding is inconsistent")
        graph = GenerationWorkGraph.compile(
            definitions,
            mode=loaded_manifest.mode,
            required_terminal_coordinates=loaded_manifest.required_terminal_coordinates,
            groups=groups,
            milestones=milestones,
        )
        # A process can die after ``begin`` but before it writes the terminal
        # FeedbackEvaluation.  That historical crash boundary must remain
        # resumable, but it cannot participate in normal stale analysis: the
        # Scheduler rightly rejects a terminal head without its boundary
        # evaluation.  Prefer that raw interruption first; once it is
        # reconciled, the next recovery obtains the full causal snapshot.
        missing_boundary = any(
            (work_head := self.work_control.read_head(definition.coordinate)) is not None
            and work_head.status in {"failed", "needs_human", "interrupted"}
            and work_head.evaluation_ref is None
            for definition in definitions
        )
        if missing_boundary:
            physical_states: dict[str, str] = {}
            for definition in definitions:
                work_head = self.work_control.read_head(definition.coordinate)
                if work_head is None:
                    continue
                if work_head.status == "repair_authorized":
                    physical_states[definition.coordinate.coordinate_key] = "repair_ready"
                elif work_head.status == "running":
                    physical_states[definition.coordinate.coordinate_key] = "running"
                elif work_head.status in {"failed", "needs_human", "interrupted"}:
                    physical_states[definition.coordinate.coordinate_key] = "blocked"
                elif work_head.status == "committed":
                    physical_states[definition.coordinate.coordinate_key] = "committed"
            return physical_states
        scheduler = WorkScheduler(
            graph=graph,
            manifest=loaded_manifest,
            manifest_ref=loaded_epoch.manifest_ref,
            heads=self.work_control,
            artifacts=self.artifacts,
        )
        states: dict[str, str] = {}
        for item in scheduler.snapshot().work:
            state = item.state
            work_head = self.work_control.read_head(item.coordinate)
            if (
                state == "ready"
                and work_head is not None
                and work_head.status == "running"
            ):
                # Scheduler uses ``ready`` for the narrow begin-before-first-
                # operation crash window so it can dispatch the node again.
                # Frozen recovery must retain its physical running identity:
                # DirectWorkRunner first reconciles that abandoned attempt;
                # treating it as an arbitrary fresh node would bypass that
                # durable crash boundary.
                state = "running"
            states[item.coordinate.coordinate_key] = state
        return states

    def _epoch_rank(self, epoch_ref: ArtifactRef) -> tuple[int, str]:
        epoch = self.artifacts.get_json(epoch_ref, WorkGraphEpoch)
        rank = {"bootstrap": 0, "world": 1, "design": 2, "final": 3}.get(epoch.epoch_kind)
        if rank is None:
            raise DirectJobResumeRequiredError("unknown frozen WorkGraph epoch kind")
        return rank, epoch_ref.revision_id

    @staticmethod
    def _coordinate_selector_matches(coordinate: WorkCoordinate, selector: str) -> bool:
        parts = (coordinate.component, coordinate.stage, coordinate.artifact_slot)
        base = ".".join(parts)
        extended = ".".join(
            item for item in (*parts, coordinate.group_id, coordinate.shard_id) if item is not None
        )
        return selector in {coordinate.coordinate_key, base, extended}

    def _authorize_node_resume(
        self,
        *,
        snapshot_ref: ArtifactRef,
        context_ref: ArtifactRef,
        epoch_ref: ArtifactRef,
        definition: WorkDefinition,
        source_attempt_ref: ArtifactRef,
        source_input_fingerprint: str,
        budget_amendment_ref: ArtifactRef | None,
    ) -> ArtifactRef:
        source_attempt = self.artifacts.get_json(source_attempt_ref, WorkAttempt)
        if (
            source_attempt.coordinate != definition.coordinate
            or source_attempt.definition_digest != definition.definition_digest
            or source_attempt.status
            not in {"failed", "budget_exhausted", "needs_human", "interrupted"}
        ):
            raise DirectJobResumeRequiredError(
                "selected node does not expose an exact terminal execution attempt"
            )
        authority = NodeResumeAuthority(
            authority_id=self._stable_id(
                "node-resume-authority",
                snapshot_ref.revision_id,
                context_ref.revision_id,
                epoch_ref.revision_id,
                source_attempt_ref.revision_id,
                definition.coordinate.coordinate_key,
                budget_amendment_ref.revision_id if budget_amendment_ref is not None else "retry",
            ),
            source_snapshot_ref=snapshot_ref,
            source_context_ref=context_ref,
            source_epoch_ref=epoch_ref,
            source_attempt_ref=source_attempt_ref,
            coordinate=definition.coordinate,
            source_definition_digest=definition.definition_digest,
            source_input_fingerprint=source_input_fingerprint,
            reason="budget_amendment" if budget_amendment_ref is not None else "operator_retry",
            budget_amendment_ref=budget_amendment_ref,
        )
        return self.artifacts.put_json(
            artifact_id=authority.authority_id,
            artifact_type="control.node_resume_authority",
            value=authority,
            dependencies=tuple(
                ref
                for ref in (
                    snapshot_ref,
                    context_ref,
                    epoch_ref,
                    source_attempt_ref,
                    budget_amendment_ref,
                )
                if ref is not None
            ),
        )

    def _authorize_scope_budget_amendment_for_target(
        self,
        *,
        job: EnvironmentJob,
        source_snapshot_ref: ArtifactRef,
        source_snapshot: JobRunSnapshot,
        source_epoch_ref: ArtifactRef,
        definition: WorkDefinition,
        amended_budget: Budget,
    ) -> ArtifactRef:
        """Amend one unstarted admission failure at any frozen coordinate."""

        work_head = self.work_control.read_head(definition.coordinate)
        if work_head is None or work_head.attempt_ref is None:
            raise DirectJobResumeRequiredError("budget amendment target has no durable WorkAttempt")
        attempt = self.artifacts.get_json(work_head.attempt_ref, WorkAttempt)
        if (
            work_head.status != "failed"
            or attempt.coordinate != definition.coordinate
            or attempt.definition_digest != definition.definition_digest
            or attempt.status != "budget_exhausted"
            or attempt.failure_code != "budget_exhausted"
            or attempt.operation_run_refs
        ):
            raise DirectJobResumeRequiredError(
                "scope budget may be amended only for an unstarted budget-admission rejection"
            )
        coordinator = DurableLeaseBudgetCoordinator(self.work_control.root / "scope-budgets")
        try:
            current = coordinator.snapshot(scope_id=job.job_id)
        except ValueError:
            current = coordinator.initialize(
                scope_id=job.job_id,
                reserved=source_snapshot.reserved_budget,
            )
        if current.reserved == amended_budget:
            raise DirectJobResumeRequiredError(
                "configured budget already matches the active scope budget; "
                "no amendment is available"
            )
        amendment = ScopeBudgetAmendment(
            amendment_id=self._stable_id(
                "scope-budget-amendment",
                job.job_id,
                source_snapshot_ref.revision_id,
                source_epoch_ref.revision_id,
                work_head.attempt_ref.revision_id,
                amended_budget.content_digest(),
            ),
            scope_id=job.job_id,
            source_snapshot_ref=source_snapshot_ref,
            source_epoch_ref=source_epoch_ref,
            source_attempt_ref=work_head.attempt_ref,
            target_coordinate_key=definition.coordinate.coordinate_key,
            source_definition_digest=definition.definition_digest,
            prior_reserved=current.reserved,
            amended_reserved=amended_budget,
        )
        amendment_ref = self.artifacts.put_json(
            artifact_id=amendment.amendment_id,
            artifact_type="control.scope_budget_amendment",
            value=amendment,
            dependencies=tuple(
                ref
                for ref in (
                    source_snapshot_ref,
                    source_epoch_ref,
                    work_head.attempt_ref,
                    attempt.validation_report_ref,
                )
                if ref is not None
            ),
        )
        coordinator.amend(
            scope_id=job.job_id,
            amendment_id=amendment.amendment_id,
            reserved=amendment.amended_reserved,
        )
        return amendment_ref

    async def _terminalize_abandoned_direct_head(
        self,
        *,
        head: DirectJobHead,
        request: EnvironmentRequest,
        direct_lock: DirectJobLock,
    ) -> None:
        snapshot = self.artifacts.get_json(head.snapshot_ref, JobRunSnapshot)
        if snapshot.status != "running" or snapshot.run_id != head.run_id:
            raise DirectJobStoreError("running Direct head does not bind its running snapshot")
        run = self._restore_direct_run(head, snapshot, direct_lock)
        final_snapshot_ref = await self._persist_snapshot(
            run,
            status="failed",
            failure_code="scheduler_direct_owner_lost",
            failure_summary=(
                "The Direct owner lock was recovered without a live Controller owner; "
                "the stopped run requires explicit frozen-node recovery."
            ),
        )
        result = GenerateResult(
            run_id=run.run_id,
            status="failed",
            request_ref=head.request_ref,
            job_ref=head.job_ref,
            final_snapshot_ref=final_snapshot_ref,
            failure_code="scheduler_direct_owner_lost",
            failure_summary=(
                "The Direct owner lock was recovered without a live Controller owner; "
                "the stopped run requires explicit frozen-node recovery."
            ),
        )
        self._complete_direct_result(run, result)

    def _frozen_work_definition(
        self,
        *,
        coordinate: WorkCoordinate,
        work_id: str,
        definition_digest: str,
    ) -> WorkDefinition:
        candidates: list[WorkDefinition] = []
        for ref in self.artifacts.list_revisions():
            if (
                ref.artifact_type != "control.work_definition"
                or ref.content_hash != definition_digest
            ):
                continue
            try:
                definition = self.artifacts.get_json(ref, WorkDefinition)
            except ValueError:
                continue
            if (
                definition.work_id == work_id
                and definition.coordinate == coordinate
                and definition.definition_digest == definition_digest
            ):
                candidates.append(definition)
        if not candidates or any(item != candidates[0] for item in candidates[1:]):
            raise DirectJobStoreError("frozen final graph lacks one exact WorkDefinition")
        return candidates[0]

    async def _generate_new_locked(
        self,
        *,
        request: EnvironmentRequest,
        request_fingerprint: str,
        selected_discovery_budget: Budget,
        enable_discovery: bool,
        direct_lock: DirectJobLock,
    ) -> GenerateResult:
        """Execute a brand-new Direct job while holding its durable writer lock."""

        selected_budget = request.budget
        selected_release = request.release_profile
        selected_permissions = request.permissions
        selected_request_id = request.request_id
        request_ref = self.artifacts.put_json(
            artifact_id=self._stable_id("request-artifact", selected_request_id),
            artifact_type="control.environment_request",
            value=request,
        )
        job_id = self._stable_id(
            "generate-job",
            selected_request_id,
            request_ref.revision_id,
        )
        job = EnvironmentJob(
            job_id=job_id,
            kind="generate",
            request_ref=request_ref,
            permissions=selected_permissions,
            budget=selected_budget,
            release_profile=selected_release,
        )
        job_ref = self.artifacts.put_json(
            artifact_id=f"{job_id}:job",
            artifact_type="control.environment_job",
            value=job,
            dependencies=(request_ref,),
        )
        return await self._execute_direct_locked(
            request=request,
            request_fingerprint=request_fingerprint,
            selected_discovery_budget=selected_discovery_budget,
            enable_discovery=enable_discovery,
            direct_lock=direct_lock,
            job=job,
            job_ref=job_ref,
            request_ref=request_ref,
            prior_head=None,
        )

    async def _execute_direct_locked(
        self,
        *,
        request: EnvironmentRequest,
        request_fingerprint: str,
        selected_discovery_budget: Budget,
        enable_discovery: bool,
        direct_lock: DirectJobLock,
        job: EnvironmentJob,
        job_ref: ArtifactRef,
        request_ref: ArtifactRef,
        prior_head: DirectJobHead | None,
        recovery_snapshot: JobRunSnapshot | None = None,
        recovery_snapshot_ref: ArtifactRef | None = None,
        recovery_context_ref: ArtifactRef | None = None,
        recovery_epoch_ref: ArtifactRef | None = None,
        recovery_coordinate: WorkCoordinate | None = None,
        resume_authority_ref: ArtifactRef | None = None,
        recovery_frontier: bool = False,
        effective_budget: Budget | None = None,
    ) -> GenerateResult:
        # Direct Generation has one executable success path: the durable
        # four-epoch WorkGraph runner.  DirectJobStore is only its idempotent
        # result index; it no longer owns component-local orchestration.
        return await self._execute_scheduler_direct_locked(
            request=request,
            request_fingerprint=request_fingerprint,
            direct_lock=direct_lock,
            job=job,
            job_ref=job_ref,
            request_ref=request_ref,
            prior_head=prior_head,
            recovery_snapshot=recovery_snapshot,
            recovery_snapshot_ref=recovery_snapshot_ref,
            recovery_context_ref=recovery_context_ref,
            recovery_epoch_ref=recovery_epoch_ref,
            recovery_coordinate=recovery_coordinate,
            resume_authority_ref=resume_authority_ref,
            recovery_frontier=recovery_frontier,
            effective_budget=effective_budget,
        )

    async def _execute_scheduler_direct_locked(
        self,
        *,
        request: EnvironmentRequest,
        request_fingerprint: str,
        direct_lock: DirectJobLock,
        job: EnvironmentJob,
        job_ref: ArtifactRef,
        request_ref: ArtifactRef,
        prior_head: DirectJobHead | None,
        recovery_snapshot: JobRunSnapshot | None = None,
        recovery_snapshot_ref: ArtifactRef | None = None,
        recovery_context_ref: ArtifactRef | None = None,
        recovery_epoch_ref: ArtifactRef | None = None,
        recovery_coordinate: WorkCoordinate | None = None,
        resume_authority_ref: ArtifactRef | None = None,
        recovery_frontier: bool = False,
        effective_budget: Budget | None = None,
    ) -> GenerateResult:
        """Project the Scheduler terminal state into the durable public result.

        ``DirectJobStore`` remains an idempotency/result index, not a second
        workflow engine: research, design, build, verifier, repair and release
        all occur exclusively under :class:`DirectWorkRunner`.
        """

        # This is a deterministic admission decision, not a shortened Direct
        # path: with no wall capacity the framework must create one durable
        # terminal result before requiring telemetry, a Runner, or any Agent
        # capability.  It prevents a misconfigured executor from obscuring
        # the more fundamental guarantee that no model/tool work was started.
        selected_budget = effective_budget or request.budget
        if selected_budget.wall_seconds <= 0:
            run = _RunState(
                run_id=f"run:{uuid.uuid4().hex}",
                job_ref=job_ref,
                scope_id=job.job_id,
                ledger=BudgetLedger(selected_budget),
                direct_request_id=request.request_id,
                direct_request_fingerprint=request_fingerprint,
                direct_request_ref=request_ref,
                direct_lock=direct_lock,
                direct_head=prior_head,
                allow_direct_restart=prior_head is not None,
            )
            run.remember(request_ref, job_ref)
            # DirectJobStore deliberately requires an initial running revision
            # before any terminal projection, even when deterministic admission
            # prevents the first executable operation.
            await self._persist_snapshot(run, status="running")
            snapshot_ref = await self._persist_snapshot(
                run,
                status="budget_exhausted",
                failure_code="wall_budget_missing",
                failure_summary=(
                    "Direct Generation has no positive wall-time budget; no Agent, tool, "
                    "build, or Judge operation was dispatched."
                ),
            )
            result = GenerateResult(
                run_id=run.run_id,
                status="budget_exhausted",
                request_ref=request_ref,
                job_ref=job_ref,
                final_snapshot_ref=snapshot_ref,
                failure_code="wall_budget_missing",
                failure_summary=(
                    "Direct Generation has no positive wall-time budget; no Agent, tool, "
                    "build, or Judge operation was dispatched."
                ),
            )
            self._complete_direct_result(run, result)
            return result
        if self.direct_work_runner is None:
            raise DirectJobStoreError("Direct WorkGraph requires configured telemetry")
        run = _RunState(
            run_id=f"run:{uuid.uuid4().hex}",
            job_ref=job_ref,
            scope_id=job.job_id,
            ledger=BudgetLedger(selected_budget),
            direct_request_id=request.request_id,
            direct_request_fingerprint=request_fingerprint,
            direct_request_ref=request_ref,
            direct_lock=direct_lock,
            direct_head=prior_head,
            allow_direct_restart=prior_head is not None,
        )
        run.remember(request_ref, job_ref)
        if recovery_snapshot is not None:
            run.remember(*recovery_snapshot.latest_artifact_refs)
        if recovery_snapshot_ref is not None:
            run.remember(recovery_snapshot_ref)
        if recovery_context_ref is not None:
            run.remember(recovery_context_ref)
        if recovery_epoch_ref is not None:
            run.remember(recovery_epoch_ref)
        if resume_authority_ref is not None:
            run.remember(resume_authority_ref)
        context_ref = self._scheduler_context_for(
            job=job,
            job_ref=job_ref,
            request=request,
            request_ref=request_ref,
            prior_head=prior_head,
            recovery_snapshot=recovery_snapshot,
            recovery_context_ref=recovery_context_ref,
        )
        run.remember(context_ref)
        await self._persist_snapshot(run, status="running")
        self.artifacts.record_event(
            event_type="generation_started",
            subject_ref=job_ref,
            related_refs=(request_ref, context_ref),
            details=(KeyValue(key="engine", value="scheduler-workgraph"),),
        )
        try:
            outcome = await self.direct_work_runner.run(
                context_ref=context_ref,
                run_id=run.run_id,
                recovery_snapshot=recovery_snapshot,
                recovery_snapshot_ref=recovery_snapshot_ref,
                recovery_epoch_ref=recovery_epoch_ref,
                recovery_coordinate=recovery_coordinate,
                resume_authority_ref=resume_authority_ref,
                recovery_frontier=recovery_frontier,
            )
        except Exception as exc:
            return await self._project_scheduler_execution_error(
                run=run,
                request_ref=request_ref,
                job_ref=job_ref,
                error=exc,
            )
        return await self._project_scheduler_outcome(
            run=run,
            request_ref=request_ref,
            job_ref=job_ref,
            outcome=outcome,
        )

    async def _recover_abandoned_scheduler_direct_locked(
        self,
        *,
        head: DirectJobHead,
        request: EnvironmentRequest,
        job: EnvironmentJob,
        snapshot: JobRunSnapshot,
        direct_lock: DirectJobLock,
    ) -> GenerateResult:
        """Resume one durable Scheduler graph after the Direct owner lock is reacquired.

        The caller's lock establishes that no Controller still owns the Direct
        run.  Scheduler reconciliation then settles any persisted OperationRun
        before normal wave scheduling.  This is intentionally not the old
        snapshot-only cancellation path: the WorkGraph owns operation cost,
        replay authority, and the resulting terminal coordinate.
        """

        # A generic ``generate`` idempotency lookup must never turn owner loss
        # into a fresh bootstrap. Earlier code called ``DirectWorkRunner.run``
        # here, whose normal entry re-derived Research through final topology.
        # Keep the checkpoint immutable and require the explicit recovery API.
        raise DirectJobResumeRequiredError(
            "abandoned Direct runs require explicit `run resume` frozen-epoch recovery; "
            "the framework will not replay upstream work through automatic generate retry"
        )

        if self.direct_work_runner is None:
            # A historical snapshot can prove that an Agent already ran but
            # cannot prove a Scheduler graph/OperationRun closure.  Such work
            # is non-replayable: treating the missing control plane as an
            # invitation to reissue the prompt would double-spend real model
            # work and falsify idempotency.  This guard is deliberately before
            # the telemetry configuration error so old stores fail closed with
            # their actual safety reason.
            consumed = snapshot.observed_actual_budget.model_dump()
            unknown = snapshot.unknown_upper_bound_budget.model_dump()
            if any(value != 0 for value in (*consumed.values(), *unknown.values())):
                raise DirectJobResumeRequiredError(
                    "durable Direct Generation checkpoint contains possibly consumed "
                    "Agent/tool work; the framework will not replay it without a "
                    "recoverable Scheduler operation closure"
                )
            raise DirectJobStoreError("Direct WorkGraph requires configured telemetry")
        run = self._restore_direct_run(head, snapshot, direct_lock)
        context_ref = self._scheduler_context_for(
            job=job,
            job_ref=head.job_ref,
            request=request,
            request_ref=head.request_ref,
            prior_head=head,
        )
        run.remember(context_ref)
        self.artifacts.record_event(
            event_type="generation_scheduler_recovery_started",
            subject_ref=head.snapshot_ref,
            related_refs=(head.request_ref, head.job_ref, context_ref),
            details=(KeyValue(key="run_id", value=head.run_id),),
        )
        try:
            outcome = await self.direct_work_runner.run(
                context_ref=context_ref,
                run_id=run.run_id,
                recovering=True,
            )
        except Exception as exc:
            return await self._project_scheduler_execution_error(
                run=run,
                request_ref=head.request_ref,
                job_ref=head.job_ref,
                error=exc,
            )
        return await self._project_scheduler_outcome(
            run=run,
            request_ref=head.request_ref,
            job_ref=head.job_ref,
            outcome=outcome,
        )

    async def _project_scheduler_execution_error(
        self,
        *,
        run: _RunState,
        request_ref: ArtifactRef,
        job_ref: ArtifactRef,
        error: Exception,
    ) -> GenerateResult:
        """Persist a Scheduler infrastructure failure without inventing semantic repair."""

        if isinstance(error, WorkExecutorMissingError):
            failure_code = "scheduler_executor_missing"
            summary = str(error)
        else:
            failure_code = "scheduler_direct_execution_error"
            diagnostic_ref = self._record_scheduler_execution_diagnostic(
                run=run,
                error=error,
            )
            safe_type = self._safe_identifier(type(error).__name__)
            summary = f"Scheduler Direct execution stopped ({safe_type})."
            if diagnostic_ref is not None:
                summary += f" Read safe diagnostic: {diagnostic_ref.artifact_id}."
        final_snapshot_ref = await self._persist_snapshot(
            run,
            status="failed",
            failure_code=failure_code,
            failure_summary=summary,
        )
        result = GenerateResult(
            run_id=run.run_id,
            status="failed",
            request_ref=request_ref,
            job_ref=job_ref,
            final_snapshot_ref=final_snapshot_ref,
            failure_code=failure_code,
            failure_summary=summary,
        )
        self._complete_direct_result(run, result)
        return result

    def _record_scheduler_execution_diagnostic(
        self,
        *,
        run: _RunState,
        error: Exception,
    ) -> ArtifactRef | None:
        """Persist one text-free failure location for project-execution debugging.

        The outer Direct runner is the last framework boundary before a
        ``GenerateResult``.  Flattening an exception to its class made a real
        failed run impossible to attribute: the project Agent could not tell
        whether to inspect a Scheduler invariant, an adapter, or the model
        prompt.  This compact Artifact deliberately keeps only framework
        source locations, exception classes, and a one-way message fingerprint.
        It is observation only: it grants no retry, repair, or semantic
        authority, and never retains an exception message, provider payload,
        workspace path, or session data.
        """

        try:
            frames: list[dict[str, JsonValue]] = []
            frame_sites: list[str] = []
            for frame in traceback.extract_tb(error.__traceback__):
                normalized = frame.filename.replace("\\", "/")
                marker = "/agent_world/"
                if marker not in normalized:
                    continue
                source_path = "agent_world/" + normalized.split(marker, 1)[1]
                frame_sites.append(f"{source_path}:{frame.lineno}")
                frames.append(
                    {
                        "source_path": source_path,
                        "function": self._safe_identifier(frame.name),
                        "line": frame.lineno,
                    }
                )
            # Four frames are enough to distinguish the caller, Scheduler,
            # adapter, and root invariant without turning this local view into
            # an accumulating traceback transcript.
            frames = frames[-4:]
            cause_types: list[str] = []
            cause: BaseException | None = error.__cause__ or error.__context__
            while cause is not None and len(cause_types) < 4:
                cause_types.append(self._safe_identifier(type(cause).__name__))
                cause = cause.__cause__ or cause.__context__
            safe_type = self._safe_identifier(type(error).__name__)
            evidence: dict[str, JsonValue] = {
                "diagnostic_kind": "scheduler_direct_execution_exception",
                "error_type": safe_type,
                "error_site": (frame_sites[-1] if frame_sites else "external_boundary"),
                "frames": cast(JsonValue, frames),
                "cause_types": cast(JsonValue, cause_types),
                "message_fingerprint": sha256_digest(str(error).encode("utf-8", errors="replace")),
            }
            if isinstance(error, WorkDependencyUnavailableError):
                evidence["work_dependency"] = cast(
                    JsonValue,
                    {
                        "child_coordinate_key": error.child.coordinate_key,
                        "parent_coordinate_key": error.parent.coordinate_key,
                        "parent_status": self._safe_identifier(error.parent_status),
                        "reason_code": self._safe_identifier(error.reason_code),
                    },
                )
            if isinstance(error, DirectWorkRunnerError) and error.safe_code is not None:
                evidence["direct_runner_invariant"] = cast(
                    JsonValue,
                    {
                        "code": self._safe_identifier(error.safe_code),
                        "coordinate_keys": tuple(
                            self._safe_identifier(item) for item in error.safe_coordinate_keys[:32]
                        ),
                    },
                )
            if isinstance(error, WorkRuntimeError) and isinstance(
                error.__cause__, WorkRepairDenied
            ):
                # WorkRepairDenied accepts only a framework-declared stable
                # code. Exposing that code fixes the project-execution Agent
                # view without leaking the wrapped exception text, model
                # output, workspace details, or a Provider payload.
                evidence["work_repair_denial"] = cast(
                    JsonValue,
                    {"code": self._safe_identifier(error.__cause__.code)},
                )
            ref = self.artifacts.put_json(
                artifact_id=self._stable_id(
                    "scheduler-direct-diagnostic",
                    run.run_id,
                    safe_type,
                    str(run.snapshot_revision),
                ),
                artifact_type="control.scheduler_execution_diagnostic",
                value=evidence,
                dependencies=(run.job_ref,),
            )
        except Exception:
            # A diagnostic write may not mask the already-closed control-plane
            # error or prevent the DirectJob from receiving a terminal result.
            return None
        run.remember(ref)
        return ref

    async def _project_scheduler_outcome(
        self,
        *,
        run: _RunState,
        request_ref: ArtifactRef,
        job_ref: ArtifactRef,
        outcome: DirectWorkRun,
    ) -> GenerateResult:
        """Project one already-terminal Scheduler outcome into DirectJob state."""

        try:
            run.ledger.consume_uncertain(
                observed_actual=outcome.observed_actual,
                unknown_upper_bound=outcome.unknown_upper_bound,
            )
        except BudgetExceeded as exc:
            raise DirectJobStoreError(
                "Scheduler outcome exceeds the DirectJob budget authority"
            ) from exc

        if outcome.status == "released":
            if outcome.package_manifest_ref is None or outcome.release_ref is None:
                raise DirectJobStoreError("released Scheduler outcome lacks Registry closure")
            release = self.artifacts.get_json(outcome.release_ref, ReleaseRecord)
            run.remember(
                outcome.bootstrap_epoch_ref,
                *((outcome.world_epoch_ref,) if outcome.world_epoch_ref is not None else ()),
                *((outcome.design_epoch_ref,) if outcome.design_epoch_ref is not None else ()),
                *((outcome.final_epoch_ref,) if outcome.final_epoch_ref is not None else ()),
                outcome.package_manifest_ref,
                outcome.release_ref,
            )
            final_snapshot_ref = await self._persist_snapshot(
                run,
                status="released",
                release_ref=outcome.release_ref,
            )
            result = GenerateResult(
                run_id=run.run_id,
                status="released",
                request_ref=request_ref,
                job_ref=job_ref,
                final_snapshot_ref=final_snapshot_ref,
                package_manifest_ref=outcome.package_manifest_ref,
                release_ref=outcome.release_ref,
                release=release,
            )
            self._complete_direct_result(run, result)
            return result
        blocked = ", ".join(outcome.blocked_coordinates) or "unknown scheduler coordinate"
        run.remember(
            outcome.bootstrap_epoch_ref,
            *((outcome.world_epoch_ref,) if outcome.world_epoch_ref is not None else ()),
            *((outcome.design_epoch_ref,) if outcome.design_epoch_ref is not None else ()),
            *((outcome.final_epoch_ref,) if outcome.final_epoch_ref is not None else ()),
        )
        final_snapshot_ref = await self._persist_snapshot(
            run,
            status="failed",
            failure_code="scheduler_direct_blocked",
            failure_summary=f"Scheduler Direct stopped at: {blocked}",
        )
        result = GenerateResult(
            run_id=run.run_id,
            status="failed",
            request_ref=request_ref,
            job_ref=job_ref,
            final_snapshot_ref=final_snapshot_ref,
            failure_code="scheduler_direct_blocked",
            failure_summary=f"Scheduler Direct stopped at: {blocked}",
        )
        self._complete_direct_result(run, result)
        return result

    def _scheduler_context_for(
        self,
        *,
        job: EnvironmentJob,
        job_ref: ArtifactRef,
        request: EnvironmentRequest,
        request_ref: ArtifactRef,
        prior_head: DirectJobHead | None,
        recovery_snapshot: JobRunSnapshot | None = None,
        recovery_context_ref: ArtifactRef | None = None,
    ) -> ArtifactRef:
        """Reuse the exact Scheduler root on resume; never fork a shadow graph."""

        if recovery_context_ref is not None:
            context = self.artifacts.get_json(recovery_context_ref, GenerationContext)
            self.artifacts.require_exact_json(
                recovery_context_ref,
                context,
                artifact_types=("control.generation_context",),
            )
            if (
                context.job_ref != job_ref
                or context.request_ref != request_ref
                or context.permissions != request.permissions
                or context.budget != request.budget
                or context.release_profile != request.release_profile
            ):
                raise DirectJobStoreError("frozen recovery has an incompatible Scheduler root")
            return recovery_context_ref

        if recovery_snapshot is not None or prior_head is not None:
            snapshot = recovery_snapshot
            if snapshot is None:
                assert prior_head is not None
                snapshot = self.artifacts.get_json(prior_head.snapshot_ref, JobRunSnapshot)
            contexts = tuple(
                ref
                for ref in snapshot.latest_artifact_refs
                if ref.artifact_type == "control.generation_context"
            )
            if len(contexts) == 1:
                context = self.artifacts.get_json(contexts[0], GenerationContext)
                if (
                    context.job_ref == job_ref
                    and context.request_ref == request_ref
                    and context.permissions == request.permissions
                    and context.budget == request.budget
                    and context.release_profile == request.release_profile
                ):
                    return contexts[0]
            if contexts:
                raise DirectJobStoreError("resumed Direct job has an incompatible Scheduler root")
        context = GenerationContext(
            context_id=f"generation-context:{job.job_id}",
            job_ref=job_ref,
            kind="generate",
            request_ref=request_ref,
            permissions=request.permissions,
            budget=request.budget,
            release_profile=request.release_profile,
        )
        return self.artifacts.put_json(
            artifact_id=context.context_id,
            artifact_type="control.generation_context",
            value=context,
            dependencies=context.root_refs,
        )

    async def resume_discovery(
        self,
        discovery_run_id: str,
        *,
        budget: Budget | None = None,
    ) -> DiscoveryResumeResult:
        """Resume one durable optional lane under a fresh independent budget.

        This command is intentionally outside Direct Generation.  It may wait
        for real research/admission work, but it cannot revise or alter the
        terminal verdict of the origin Generate job.
        """

        selected_budget = budget or self.config.discovery_budget
        lock_id = f"discovery-resume:{discovery_run_id}"
        with self.direct_jobs.exclusive(lock_id):
            return await self._resume_discovery_locked(
                discovery_run_id=discovery_run_id,
                budget=selected_budget,
            )

    async def expand(
        self,
        *,
        anchor_package_refs: Sequence[ArtifactRef],
        target_coverage_dimensions: Sequence[str],
        campaign_id: str,
        inbox_snapshot_ref: ArtifactRef | None = None,
        source_ids: Sequence[str] | None = None,
        feedback_refs: Sequence[ArtifactRef] = (),
        policy_id: str | None = None,
        policy_parameters: Sequence[KeyValue] | None = None,
        permissions: PermissionScope | None = None,
        campaign_budget: Budget | None = None,
        candidate_budget: Budget | None = None,
        release_profile: ReleaseProfile | None = None,
        campaign_seed: int | None = None,
        allowed_source_kinds: Sequence[str] = ("web",),
        risk_level: Literal["low", "medium", "high", "critical"] = "medium",
        fidelity_requirements: Sequence[str] = (),
    ) -> ExpandResult:
        """Start optional tool-first expansion from exact released package manifests."""

        selected_id = campaign_id
        source_catalog = self._expansion_source_catalog(
            source_ids=source_ids,
            feedback_refs=feedback_refs,
        )
        selected_policy = policy_id or self.config.expansion.policy
        selected_parameters = tuple(policy_parameters or ())
        if selected_policy == "evolutionary-archive" and not selected_parameters:
            selected_parameters = (
                KeyValue(
                    key="external_injection_rate",
                    value=self.config.expansion.external_injection_rate,
                ),
            )
        seed = campaign_seed
        if seed is None:
            seed = int(hashlib.sha256(selected_id.encode()).hexdigest()[:16], 16)
        return await self.expansion_runner.start(
            anchor_package_refs=anchor_package_refs,
            target_coverage_dimensions=target_coverage_dimensions,
            inbox_snapshot_ref=inbox_snapshot_ref,
            source_catalog=source_catalog,
            feedback_refs=tuple(feedback_refs),
            campaign_id=selected_id,
            policy_id=selected_policy,
            policy_parameters=selected_parameters,
            permissions=permissions or PermissionScope(),
            campaign_budget=campaign_budget or self.config.expansion.campaign_budget,
            candidate_budget=candidate_budget or self.config.expansion.candidate_budget,
            release_profile=release_profile or self.config.release_profile,
            campaign_seed=seed,
            maximum_intents_per_iteration=(self.config.expansion.maximum_intents_per_iteration),
            maximum_in_flight=self.config.expansion.max_in_flight,
            maximum_iterations=self.config.expansion.maximum_iterations,
            maximum_no_release_iterations=(self.config.expansion.maximum_no_release_iterations),
            maximum_infrastructure_error_iterations=(
                self.config.expansion.maximum_infrastructure_error_iterations
            ),
            version_reservation_ttl_seconds=(self.config.expansion.version_reservation_ttl_seconds),
            allowed_source_kinds=allowed_source_kinds,
            risk_level=risk_level,
            fidelity_requirements=fidelity_requirements,
        )

    def _expansion_source_catalog(
        self,
        *,
        source_ids: Sequence[str] | None,
        feedback_refs: Sequence[ArtifactRef],
    ) -> ExpansionSourceCatalog:
        """Freeze one configured Source subset into a content-named Campaign catalog."""

        configured = {item.source_id: item for item in self.config.expansion.sources}
        if source_ids is None:
            requested = self.config.expansion.default_source_ids
        else:
            requested = tuple(source_ids)
            if not requested:
                raise ValueError("Expansion requires at least one selected Source")
            if len(set(requested)) != len(requested):
                raise ValueError("Expansion Source selection contains duplicate ids")
            unknown = sorted(set(requested) - set(configured))
            if unknown:
                raise ValueError(f"Expansion Source selection is not configured: {unknown}")
        requested_set = set(requested)
        descriptors = tuple(
            item.descriptor()
            for item in self.config.expansion.sources
            if item.source_id in requested_set
        )
        if not descriptors:
            raise ValueError("Expansion requires at least one configured Source")
        if any(item.kind == "capability_gap" for item in descriptors) and not feedback_refs:
            raise ValueError("capability_gap Source requires frozen capability feedback refs")
        digest = sha256_digest(
            canonical_json_bytes(
                [item.model_dump(mode="json", by_alias=True) for item in descriptors]
            )
        )
        return ExpansionSourceCatalog(
            catalog_id=f"source-catalog:{digest.removeprefix('sha256:')[:24]}",
            sources=descriptors,
        )

    async def resume_expansion(self, campaign_id: str) -> ExpandResult:
        """Resume one durable Campaign under its single-writer lock."""

        return await self.expansion_runner.resume(campaign_id)

    async def execute_expansion_candidate(
        self,
        *,
        campaign: ExpansionCampaign,
        campaign_ref: ArtifactRef,
        iteration_ref: ArtifactRef,
        intent: MutationIntent,
        intent_ref: ArtifactRef,
        lease: BudgetLease,
        lease_ref: ArtifactRef,
        registry_snapshot_id: str,
        authorized_archive_parent_refs: Sequence[ArtifactRef],
    ) -> CampaignCandidateResult:
        """Execute one admitted intent through the ordinary candidate/release path."""

        self.artifacts.require_exact_json(
            campaign_ref,
            campaign,
            artifact_types=("expansion.campaign",),
        )
        self.artifacts.require_exact_json(
            intent_ref,
            intent,
            artifact_types=("expansion.mutation_intent",),
        )
        self.artifacts.require_exact_json(
            lease_ref,
            lease,
            artifact_types=("control.budget_lease",),
        )
        if lease.owner_id != intent.intent_id or lease.reserved != campaign.candidate_budget:
            raise ValueError("candidate lease does not bind the exact intent/budget")
        if lease.status != "active":
            raise ValueError("candidate execution requires an active budget lease")

        job_id = self._stable_id("expand-job", campaign.campaign_id, intent.intent_id)
        job = EnvironmentJob(
            job_id=job_id,
            kind="expand",
            anchor_package_refs=intent.parent_refs,
            expansion_campaign_ref=campaign_ref,
            permissions=campaign.permissions,
            budget=campaign.candidate_budget,
            release_profile=campaign.release_profile,
        )
        job_ref = self.artifacts.put_json(
            artifact_id=f"{job_id}:job",
            artifact_type="control.environment_job",
            value=job,
            dependencies=(campaign_ref, iteration_ref, intent_ref, lease_ref, *intent.parent_refs),
        )
        attempt_id = self._stable_id(
            "candidate-attempt",
            campaign_ref.revision_id,
            iteration_ref.revision_id,
            intent_ref.revision_id,
        )
        leased_attempt = ExpansionCandidateAttempt(
            attempt_id=attempt_id,
            campaign_ref=campaign_ref,
            iteration_number=self._iteration_number(iteration_ref),
            intent_ref=intent_ref,
            lease_ref=lease_ref,
            job_ref=job_ref,
            status="leased",
        )
        leased_attempt_ref = self.artifacts.put_json(
            artifact_id=f"{attempt_id}:state",
            artifact_type="control.expansion_candidate_attempt",
            value=leased_attempt,
            dependencies=(campaign_ref, iteration_ref, intent_ref, lease_ref, job_ref),
        )
        running_attempt = leased_attempt.model_copy(update={"status": "running"})
        running_attempt_ref = self.artifacts.put_json(
            artifact_id=f"{attempt_id}:state",
            artifact_type="control.expansion_candidate_attempt",
            value=running_attempt,
            dependencies=(leased_attempt_ref, job_ref),
        )

        run_id = self._stable_id("candidate-run", campaign.campaign_id, intent.intent_id)
        run = _RunState(
            run_id=run_id,
            job_ref=job_ref,
            scope_id=job.job_id,
            ledger=BudgetLedger(campaign.candidate_budget),
        )
        if self.telemetry is not None:
            run.telemetry_root_span = self.telemetry.start_span(
                trace_id=run_id,
                component="controller",
                operation="expansion.candidate",
                run_id=run_id,
                campaign_id=campaign.campaign_id,
                node="request",
                input_refs=(campaign_ref, iteration_ref, intent_ref, job_ref),
                attributes={
                    "campaign_id_hash": self._hashed_session(campaign.campaign_id),
                    "intent_id_hash": self._hashed_session(intent.intent_id),
                    "release_profile": campaign.release_profile.profile_id,
                },
            )
            self.telemetry.activate_trace(
                trace_id=run_id,
                run_id=run_id,
                campaign_id=campaign.campaign_id,
                parent_span_id=run.telemetry_root_span.span_id,
            )
        run.remember(
            campaign_ref,
            iteration_ref,
            intent_ref,
            lease_ref,
            job_ref,
            running_attempt_ref,
        )
        request_attempt = self._start_attempt(run, "request", (intent_ref, job_ref))
        self._finish_attempt(run, request_attempt, status="passed", output_refs=(job_ref,))
        await self._persist_snapshot(run, status="running")

        design: ExpansionDesignBundle | None = None
        build: BuildBundle | None = None
        judge_bundle: JudgeBundle | None = None
        reservation: PackageVersionReservation | None = None
        manifest_ref: ArtifactRef | None = None
        release_ref: ArtifactRef | None = None
        started = time.monotonic()
        halt: _GenerationHalt | None = None
        try:
            async with asyncio.timeout(campaign.candidate_budget.wall_seconds):
                parents, parent_manifests = self._resolve_expansion_parents(
                    intent=intent,
                    registry_snapshot_id=registry_snapshot_id,
                    authorized_archive_parent_refs=authorized_archive_parent_refs,
                )
                clues = self._resolve_expansion_clues(intent.clue_refs)
                design = await self._run_expansion_design(
                    run=run,
                    job=job,
                    job_ref=job_ref,
                    campaign=campaign,
                    intent=intent,
                    intent_ref=intent_ref,
                    parents=parents,
                    clues=clues,
                )
                primary_index = intent.parent_refs.index(intent.primary_parent_ref)
                primary_manifest = parent_manifests[primary_index]
                parent_workspace_refs = self._unique_refs(
                    tuple(
                        ref
                        for manifest in parent_manifests
                        for ref in manifest.lineage.implementation.source_snapshot_refs
                    )
                )
                while True:
                    try:
                        try:
                            release_plan = self._prepare_expansion_release_plan(
                                run=run,
                                campaign=campaign,
                                intent=intent,
                                primary_manifest=primary_manifest,
                                design=design,
                            )
                        except Exception as exc:
                            raise self._expansion_identity_correction(
                                run=run,
                                design_ref=design.design_ref,
                                error_type=type(exc).__name__,
                            ) from exc
                        run.remember(
                            release_plan.identity_ref,
                            release_plan.semantic_lineage_ref,
                            release_plan.evidence_summary_ref,
                        )
                        reservation = self._reserve_release_coordinate(
                            run=run,
                            package_id=release_plan.package_id,
                            version=release_plan.version,
                            ttl_seconds=campaign.version_reservation_ttl_seconds,
                        )
                        compiled, build = await self._compile_and_build(
                            run,
                            job,
                            design,
                            parent_workspace_refs=parent_workspace_refs,
                        )
                        judge_bundle, build = await self._judge_and_repair(
                            run=run,
                            job=job,
                            design=design,
                            compiled=compiled,
                            build=build,
                        )
                        break
                    except _DesignReworkRequired as correction:
                        if reservation is not None:
                            self._release_reservation_if_active(reservation, job_ref)
                            reservation = None
                        build = None
                        judge_bundle = None
                        design = await self._run_expansion_design_revision(
                            run=run,
                            job=job,
                            job_ref=job_ref,
                            campaign=campaign,
                            intent=intent,
                            intent_ref=intent_ref,
                            parents=parents,
                            clues=clues,
                            previous=design,
                            correction=correction,
                        )

                assert reservation is not None and build is not None and judge_bundle is not None
                self._charge_wall(run, started)
                manifest_ref, release_ref, _ = self._release(
                    run=run,
                    job=job,
                    design=design,
                    build=build,
                    judge_bundle=judge_bundle,
                    plan=release_plan,
                    reservation=reservation,
                )
                final_snapshot_ref = await self._persist_snapshot(
                    run,
                    status="released",
                    release_ref=release_ref,
                )
        except TimeoutError:
            halt = _GenerationHalt(
                status="budget_exhausted",
                code="expansion_candidate_wall_timeout",
                summary="Expansion candidate reached its wall-time reservation.",
            )
        except BudgetExceeded as exc:
            halt = _GenerationHalt(
                status="budget_exhausted",
                code="expansion_candidate_budget_exhausted",
                summary=f"Expansion candidate exhausted: {', '.join(exc.dimensions)}.",
            )
        except _GenerationHalt as exc:
            halt = exc
        except Exception as exc:
            finding_ref = self._control_failure_finding(
                run,
                node="release",
                event_kind=ControlEventKind.RELEASE_POLICY_FAILURE,
                code="expansion_candidate_infrastructure_error",
                error_type=type(exc).__name__,
                exception=exc,
            )
            halt = _GenerationHalt(
                status="failed",
                code="expansion_candidate_infrastructure_error",
                summary="Expansion candidate stopped on an infrastructure/programming error.",
                finding_refs=(finding_ref,),
            )

        if manifest_ref is None:
            if reservation is not None:
                self._release_reservation_if_active(reservation, job_ref)
            assert halt is not None
            run.remember_findings(*halt.finding_refs)
            self._charge_wall(run, started, clamp=True)
            final_snapshot_ref = await self._persist_snapshot(run, status=halt.status)

        findings = (
            judge_bundle.report.findings
            if manifest_ref is not None and judge_bundle is not None
            else self._load_run_findings(run)
        )
        latest_report = (
            judge_bundle.report if judge_bundle is not None else self._latest_judge_report(run)
        )
        gates = latest_report.gate_results if latest_report is not None else ()
        terminal_status = (
            "released" if manifest_ref is not None else self._candidate_terminal_status(run, halt)
        )
        outcome = CandidateOutcome(
            outcome_id=self._stable_id("candidate-outcome", campaign.campaign_id, intent.intent_id),
            campaign_ref=campaign_ref,
            iteration_ref=iteration_ref,
            intent_ref=intent_ref,
            attempt_ref=running_attempt_ref,
            job_ref=job_ref,
            terminal_reason_code=("released" if halt is None else self._safe_identifier(halt.code)),
            candidate_ref=build.candidate_ref if build is not None else None,
            released_package_ref=manifest_ref,
            terminal_status=terminal_status,
            hard_gate_results=tuple(gate for gate in gates if gate.hard),
            coverage_gain=(
                self._coverage_gains(
                    parents[intent.parent_refs.index(intent.primary_parent_ref)],
                    design,
                    judge_bundle.report_ref,
                )
                if manifest_ref is not None and design is not None and judge_bundle is not None
                else ()
            ),
            behavior_descriptors=(
                self._behavior_descriptors(design, judge_bundle.report_ref)
                if manifest_ref is not None and design is not None and judge_bundle is not None
                else ()
            ),
            findings=findings,
            budget_usage=run.ledger.used,
            repair_depth=run.ledger.used.repair_attempts,
            semantic_lineage_ref=(design.semantic_lineage_ref if design is not None else None),
            implementation_lineage_ref=(
                build.implementation_lineage_ref if build is not None else None
            ),
        )
        outcome_dependencies = self._unique_refs(
            (
                campaign_ref,
                iteration_ref,
                intent_ref,
                running_attempt_ref,
                job_ref,
                final_snapshot_ref,
                *((manifest_ref,) if manifest_ref is not None else ()),
                *((release_ref,) if release_ref is not None else ()),
                *tuple(run.findings.values()),
            )
        )
        outcome_ref = self.artifacts.put_json(
            artifact_id=f"{outcome.outcome_id}:record",
            artifact_type="expansion.candidate_outcome",
            value=outcome,
            dependencies=outcome_dependencies,
        )
        terminal_attempt = running_attempt.model_copy(
            update={
                "reservation_ref": self._latest_ref(run, "release.package_version_reservation"),
                "latest_run_snapshot_ref": final_snapshot_ref,
                "status": self._candidate_attempt_status(terminal_status),
                "outcome_ref": outcome_ref,
            }
        )
        terminal_attempt_ref = self.artifacts.put_json(
            artifact_id=f"{attempt_id}:state",
            artifact_type="control.expansion_candidate_attempt",
            value=terminal_attempt,
            dependencies=(running_attempt_ref, outcome_ref, final_snapshot_ref),
        )
        if run.telemetry_root_span is not None and self.telemetry is not None:
            self._close_open_telemetry_spans(
                run,
                error_code="controller_terminal" if manifest_ref is not None else terminal_status,
            )
            run.telemetry_root_span.finish(
                status="passed" if manifest_ref is not None else "failed",
                error_code=None if manifest_ref is not None else terminal_status,
                output_refs=(outcome_ref, terminal_attempt_ref),
            )
            self.telemetry.flush()
        return CampaignCandidateResult(
            outcome=outcome,
            outcome_ref=outcome_ref,
            attempt_ref=terminal_attempt_ref,
        )

    def _iteration_number(self, iteration_ref: ArtifactRef) -> int:
        iteration = self.artifacts.get_json(iteration_ref, CampaignIterationRecord)
        if iteration.status != "leased":
            raise ValueError("candidate execution requires a leased iteration revision")
        return iteration.number

    def _resolve_expansion_parents(
        self,
        *,
        intent: MutationIntent,
        registry_snapshot_id: str,
        authorized_archive_parent_refs: Sequence[ArtifactRef],
    ) -> tuple[
        tuple[ResolvedExpansionParent, ...],
        tuple[EnvironmentPackageManifest, ...],
    ]:
        archive_revisions = {item.revision_id for item in authorized_archive_parent_refs}
        parents: list[ResolvedExpansionParent] = []
        manifests: list[EnvironmentPackageManifest] = []
        for package_ref in intent.parent_refs:
            if package_ref.revision_id in archive_revisions:
                record = self.registry.require_released_manifest(package_ref)
            else:
                record = self.registry.require_snapshot_parent(
                    registry_snapshot_id,
                    package_ref,
                )
            if record.manifest_ref != package_ref:
                raise ValueError("Registry parent resolution changed the exact manifest ref")
            manifest = self.artifacts.get_json(package_ref, EnvironmentPackageManifest)
            self.artifacts.require_exact_json(
                package_ref,
                manifest,
                artifact_types=("environment_package_manifest",),
            )
            design = self.artifacts.get_json(manifest.design_ref, EnvironmentDesign)
            self.artifacts.require_exact_json(
                manifest.design_ref,
                design,
                artifact_types=("design.environment_design", "expansion.environment_design"),
            )
            parents.append(
                ResolvedExpansionParent(
                    package_ref=package_ref,
                    design=design,
                    design_ref=manifest.design_ref,
                )
            )
            manifests.append(manifest)
        return tuple(parents), tuple(manifests)

    def _resolve_expansion_clues(
        self,
        clue_refs: Sequence[ArtifactRef],
    ) -> tuple[ResolvedExpansionClue, ...]:
        resolved: list[ResolvedExpansionClue] = []
        for clue_ref in clue_refs:
            allowed_types = (
                "discovery.expansion_clue",
                "expansion.source_clue",
            )
            if clue_ref.artifact_type not in allowed_types:
                raise ValueError("Expansion intent references an unsupported clue artifact")
            clue = self.artifacts.get_json(clue_ref, ExpansionClue)
            self.artifacts.require_exact_json(
                clue_ref,
                clue,
                artifact_types=allowed_types,
            )
            resolved.append(ResolvedExpansionClue(clue=clue, clue_ref=clue_ref))
        return tuple(resolved)

    async def _run_expansion_design(
        self,
        *,
        run: _RunState,
        job: EnvironmentJob,
        job_ref: ArtifactRef,
        campaign: ExpansionCampaign,
        intent: MutationIntent,
        intent_ref: ArtifactRef,
        parents: Sequence[ResolvedExpansionParent],
        clues: Sequence[ResolvedExpansionClue],
    ) -> ExpansionDesignBundle:
        work = self._reserve_designer_work(
            run,
            purpose=f"expansion-design-{intent.intent_id}",
            base_turns=3,
            maximum_corrections=3 * self.designer.maximum_structured_reworks,
        )
        attempt_id = self._start_attempt(
            run,
            "design",
            (job_ref, intent_ref, work.lease_ref),
        )
        await self._persist_snapshot(run, status="running")
        work_settled = False
        settled_invocation_usage = BudgetUsage()
        try:
            bundle = await self.expansion_designer.expand(
                job=job,
                job_ref=job_ref,
                intent=intent,
                intent_ref=intent_ref,
                parents=parents,
                clues=clues,
                workspace=self._workspace_for(run.run_id, "design"),
                invocation_budget=work.lease.reserved,
            )
            usage = self._add_usage(
                bundle.invocation_usage,
                bundle.research_usage,
            )
            invocation_actual, invocation_unknown = self._designer_bundle_settlement(bundle)
            self._settle_designer_work(
                run,
                work,
                invocation_actual,
                unknown_upper_bound=invocation_unknown,
            )
            work_settled = True
            settled_invocation_usage = bundle.invocation_usage
            run.ledger.consume(bundle.research_usage)
            modeling_request = EnvironmentRequest(
                request_id=self._stable_id(
                    "expansion-request",
                    campaign.campaign_id,
                    intent.intent_id,
                ),
                need=(
                    "Expand a released Agent environment through the admitted "
                    f"{intent.operator} semantic operator."
                ),
                allowed_source_kinds=campaign.allowed_source_kinds,
                fidelity_requirements=campaign.fidelity_requirements,
                permissions=campaign.permissions,
                risk_level=campaign.risk_level,
                budget=campaign.candidate_budget,
                release_profile=campaign.release_profile,
            )
            modeling_gate_ref, failures = self._modeling_gate(
                job=job,
                request=modeling_request,
                design=bundle,
            )
            run.remember(modeling_gate_ref)
            if failures:
                finding_ref = self._control_failure_finding(
                    run,
                    node="design",
                    event_kind=ControlEventKind.CONTRACT_FAILURE,
                    code="modeling_gate_failed",
                    error_type="ModelingGateRejected",
                    subject_ref=bundle.design_ref,
                    causal_refs=(modeling_gate_ref,),
                    repair_context=failures,
                )
                self._finish_attempt(
                    run,
                    attempt_id,
                    status="failed",
                    output_refs=(modeling_gate_ref,),
                    finding_refs=(finding_ref,),
                    failure_code="modeling_gate_failed",
                    failure_summary="Framework Modeling Gate rejected the expansion design.",
                    usage=usage,
                )
                finding = self.artifacts.get_json(finding_ref, Finding)
                await self._persist_snapshot(run, status="running")
                return await self._run_expansion_design_revision(
                    run=run,
                    job=job,
                    job_ref=job_ref,
                    campaign=campaign,
                    intent=intent,
                    intent_ref=intent_ref,
                    parents=parents,
                    clues=clues,
                    previous=bundle,
                    correction=_DesignReworkRequired(
                        findings=(finding,),
                        finding_refs=(finding_ref,),
                        revision_mode=self._design_revision_mode_for_finding(finding),
                    ),
                )
            outputs = (
                bundle.evidence_graph_ref,
                bundle.coverage_map_ref,
                bundle.world_spec_ref,
                bundle.semantic_delta_ref,
                bundle.identity_decision_ref,
                bundle.semantic_lineage_ref,
                bundle.design_ref,
                modeling_gate_ref,
            )
            run.remember(*outputs)
            self._finish_attempt(
                run,
                attempt_id,
                status="passed",
                output_refs=outputs,
                usage=usage,
                profile_hash=self._last_profile_hash(bundle.invocation_results),
                session_id=self._last_session_id(bundle.invocation_results),
            )
            await self._persist_snapshot(run, status="running")
            return bundle
        except _GenerationHalt:
            raise
        except BudgetExceeded as exc:
            failure_usage = (
                settled_invocation_usage
                if work_settled
                else self._settle_failed_designer_work(run, work, exc)
            )
            self._finish_running_attempt_if_needed(
                run,
                attempt_id,
                status="budget_exhausted",
                failure_code="expansion_design_budget_exhausted",
                failure_summary="Expansion design exceeded its vector reservation.",
                usage=failure_usage,
            )
            raise _GenerationHalt(
                status="budget_exhausted",
                code="expansion_design_budget_exhausted",
                summary=f"Expansion design exhausted: {', '.join(exc.dimensions)}.",
            ) from exc
        except DesignerError as exc:
            failure_usage = self._settle_designer_error(
                run,
                work,
                exc,
                settled_invocation_usage if work_settled else None,
            )
            status, code = self._designer_failure_status(
                exc,
                default_code=(
                    "framework_invariant_violation"
                    if exc.framework_invariant
                    else "expansion_designer_infrastructure_error"
                    if exc.infrastructure_error
                    else f"expansion_{self._safe_identifier(exc.stage)}"
                ),
            )
            finding_ref = self._control_failure_finding(
                run,
                node="design",
                event_kind=(
                    ControlEventKind.PERMISSION_REQUIRED
                    if status == "needs_human"
                    else ControlEventKind.INFRASTRUCTURE_FAILURE
                    if exc.framework_invariant or exc.infrastructure_error
                    else ControlEventKind.COMPONENT_FAILURE
                ),
                code=code,
                error_type=type(exc).__name__,
                subject_ref=exc.subject_ref,
                exception=exc,
            )
            self._finish_running_attempt_if_needed(
                run,
                attempt_id,
                status=status,
                finding_refs=(finding_ref,),
                failure_code=code,
                failure_summary="Expansion Designer did not produce a valid design revision.",
                usage=failure_usage,
                profile_hash=self._last_profile_hash(exc.results),
                session_id=self._last_session_id(exc.results),
            )
            raise _GenerationHalt(
                status=self._generate_status(status),
                code=code,
                summary="Expansion Designer stopped without a complete design.",
                finding_refs=(finding_ref,),
            ) from exc
        except Exception as exc:
            failure_usage = (
                settled_invocation_usage
                if work_settled
                else self._settle_failed_designer_work(run, work, exc)
            )
            finding_ref = self._control_failure_finding(
                run,
                node="design",
                event_kind=ControlEventKind.INFRASTRUCTURE_FAILURE,
                code="expansion_designer_infrastructure_error",
                error_type=type(exc).__name__,
                exception=exc,
            )
            self._finish_running_attempt_if_needed(
                run,
                attempt_id,
                status="failed",
                finding_refs=(finding_ref,),
                failure_code="expansion_designer_infrastructure_error",
                failure_summary="Expansion Designer failed outside its invocation protocol.",
                usage=failure_usage,
            )
            raise _GenerationHalt(
                status="failed",
                code="expansion_designer_infrastructure_error",
                summary="Expansion Designer infrastructure failed closed.",
                finding_refs=(finding_ref,),
            ) from exc

    async def _run_expansion_design_revision(
        self,
        *,
        run: _RunState,
        job: EnvironmentJob,
        job_ref: ArtifactRef,
        campaign: ExpansionCampaign,
        intent: MutationIntent,
        intent_ref: ArtifactRef,
        parents: Sequence[ResolvedExpansionParent],
        clues: Sequence[ResolvedExpansionClue],
        previous: ExpansionDesignBundle,
        correction: _DesignReworkRequired,
    ) -> ExpansionDesignBundle:
        """Repair expansion semantics and invalidate every compiled descendant."""

        router = RepairRouter(
            maximum_attempts=job.budget.repair_attempts,
            artifact_store=self.artifacts,
        )
        if correction.directive_refs:
            routes = tuple(
                self.artifacts.get_json(ref, RepairDirective) for ref in correction.directive_refs
            )
            for route, directive_ref in zip(routes, correction.directive_refs, strict=True):
                self.artifacts.require_exact_json(
                    directive_ref,
                    route,
                    artifact_types=("control.repair_directive",),
                )
            covered_refs = tuple(
                ref for route in routes for ref in (route.finding_ref, *route.related_finding_refs)
            )
            if len(set(covered_refs)) != len(covered_refs) or set(covered_refs) != set(
                correction.finding_refs
            ):
                raise ValueError(
                    "persisted expansion RepairActions do not cover the exact Finding set"
                )
            directive_refs = correction.directive_refs
        else:
            routes = router.route_many(
                tuple(
                    zip(
                        correction.findings,
                        correction.finding_refs,
                        strict=True,
                    )
                ),
                current_node="design",
                ledger=run.repair_ledger,
            )
            ledger_refs = self._persist_repair_ledger_entries(run, routes)
            directive_refs = tuple(
                self.artifacts.put_json(
                    artifact_id=(
                        f"{run.run_id}:expansion-design-repair-directive:"
                        f"{previous.design_ref.revision_id[-16:]}:{index}"
                    ),
                    artifact_type="control.repair_directive",
                    value=route,
                    dependencies=(
                        route.finding_ref,
                        *route.related_finding_refs,
                        previous.design_ref,
                        intent_ref,
                        ledger_refs[index],
                    ),
                )
                for index, route in enumerate(routes)
            )
        if any(route.owner_node != "design" or route.action != "new_revision" for route in routes):
            raise ValueError("expansion design revision received a non-design RepairDirective")
        if correction.additional_evidence or correction.challenged_claim_ids:
            raise ValueError(
                "expansion design rework cannot silently change its frozen Campaign evidence; "
                "a new admitted intent is required"
            )
        run.remember(*directive_refs)
        run.remember_findings(*correction.finding_refs)
        routes_completed = False

        def complete_design_routes(
            blocking_claim_ids_after: tuple[str, ...],
            *,
            retained_refs: tuple[ArtifactRef, ...],
            usage: BudgetUsage,
            invalidated_refs: tuple[ArtifactRef, ...] = (),
        ) -> None:
            nonlocal routes_completed
            if routes_completed:
                return
            for route in routes:
                if route.ledger_entry_id is None:
                    raise ValueError("design repair directive lacks ledger entry")
                run.repair_ledger.complete(
                    route.ledger_entry_id,
                    blocking_claim_ids_after=blocking_claim_ids_after,
                    invalidated_refs=invalidated_refs,
                    retained_refs=retained_refs,
                    session_strategy="continued",
                    usage=usage,
                )
            self._persist_repair_ledger_entries(run, routes)
            routes_completed = True

        required_design_turns = 1
        required_downstream_turns = 1 + self.verifier_compiler.maximum_invocation_turns(
            len(previous.design.curriculum.task_types)
        )
        remaining = run.ledger.remaining
        if (
            remaining.repair_attempts < 1
            or remaining.agent_turns < required_design_turns + required_downstream_turns
        ):
            self._terminate_repair_routes(
                run,
                routes,
                outcome="exhausted",
                retained_refs=(previous.design_ref,),
            )
            await self._persist_snapshot(run, status="running")
            raise _GenerationHalt(
                status="budget_exhausted",
                code="expansion_design_rework_budget_exhausted",
                summary=(
                    "An expansion design revision is required, but the remaining vector budget "
                    "cannot cover semantic repair and a fresh Verifier/Builder branch."
                ),
                finding_refs=correction.finding_refs,
            )

        revision_ordinal = 1 + sum(item.node == "design" for item in run.attempts)
        available_after_action = BudgetLedger(
            run.ledger.remaining,
            BudgetUsage(repair_attempts=1),
        ).remaining
        try:
            work = self._reserve_designer_work(
                run,
                purpose=f"expansion-design-revision-{revision_ordinal}",
                base_turns=required_design_turns,
                maximum_corrections=self.designer.maximum_structured_reworks,
                available=available_after_action,
            )
        except (_GenerationHalt, BudgetExceeded) as exc:
            self._terminate_repair_routes(
                run,
                routes,
                outcome="exhausted",
                retained_refs=(previous.design_ref,),
            )
            await self._persist_snapshot(run, status="running")
            if isinstance(exc, _GenerationHalt):
                raise
            raise _GenerationHalt(
                status="budget_exhausted",
                code="expansion_design_rework_reservation_exhausted",
                summary="Expansion design rework could not reserve its Agent budget.",
                finding_refs=correction.finding_refs,
            ) from exc
        run.ledger.consume(BudgetUsage(repair_attempts=1))
        attempt_id = self._start_attempt(
            run,
            "design",
            (
                previous.design_ref,
                intent_ref,
                *correction.finding_refs,
                *directive_refs,
                work.lease_ref,
            ),
        )
        self.artifacts.record_event(
            event_type="expansion_design_rework_started",
            subject_ref=previous.design_ref,
            related_refs=(intent_ref, *correction.finding_refs, *directive_refs),
            details=(KeyValue(key="repair_ordinal", value=revision_ordinal),),
        )
        await self._persist_snapshot(run, status="running")
        work_settled = False
        settled_invocation_usage = BudgetUsage()
        try:
            bundle = await self.expansion_designer.revise(
                job=job,
                job_ref=job_ref,
                intent=intent,
                intent_ref=intent_ref,
                parents=parents,
                clues=clues,
                previous=previous,
                findings=correction.findings,
                finding_refs=correction.finding_refs,
                workspace=self._workspace_for(
                    run.run_id,
                    f"expansion-design-revision-{revision_ordinal}",
                ),
                invocation_budget=work.lease.reserved,
            )
            invocation_usage = bundle.invocation_usage
            invocation_actual, invocation_unknown = self._designer_bundle_settlement(bundle)
            self._settle_designer_work(
                run,
                work,
                invocation_actual,
                unknown_upper_bound=invocation_unknown,
            )
            work_settled = True
            settled_invocation_usage = invocation_usage
            modeling_request = EnvironmentRequest(
                request_id=self._stable_id(
                    "expansion-request",
                    campaign.campaign_id,
                    intent.intent_id,
                ),
                need=(
                    "Expand a released Agent environment through the admitted "
                    f"{intent.operator} semantic operator."
                ),
                allowed_source_kinds=campaign.allowed_source_kinds,
                fidelity_requirements=campaign.fidelity_requirements,
                permissions=campaign.permissions,
                risk_level=campaign.risk_level,
                budget=campaign.candidate_budget,
                release_profile=campaign.release_profile,
            )
            modeling_gate_ref, policy_failures = self._modeling_gate(
                job=job,
                request=modeling_request,
                design=bundle,
            )
            run.remember(modeling_gate_ref)
            total_usage = self._add_usage(
                BudgetUsage(repair_attempts=1),
                invocation_usage,
            )
            if policy_failures:
                finding_ref = self._control_failure_finding(
                    run,
                    node="design",
                    event_kind=ControlEventKind.CONTRACT_FAILURE,
                    code="revised_expansion_modeling_gate_failed",
                    error_type="ModelingGateRejected",
                    subject_ref=bundle.design_ref,
                    causal_refs=(modeling_gate_ref,),
                    repair_context=policy_failures,
                )
                self._finish_attempt(
                    run,
                    attempt_id,
                    status="failed",
                    output_refs=(modeling_gate_ref,),
                    finding_refs=(finding_ref,),
                    failure_code="revised_expansion_modeling_gate_failed",
                    failure_summary=(
                        "Framework Modeling Gate rejected the expansion design revision: "
                        + ", ".join(policy_failures)
                    ),
                    usage=total_usage,
                )
                finding = self.artifacts.get_json(finding_ref, Finding)
                complete_design_routes(
                    (finding.fingerprint,),
                    retained_refs=(bundle.design_ref,),
                    usage=total_usage,
                )
                await self._persist_snapshot(run, status="running")
                return await self._run_expansion_design_revision(
                    run=run,
                    job=job,
                    job_ref=job_ref,
                    campaign=campaign,
                    intent=intent,
                    intent_ref=intent_ref,
                    parents=parents,
                    clues=clues,
                    previous=bundle,
                    correction=_DesignReworkRequired(
                        findings=(finding,),
                        finding_refs=(finding_ref,),
                        revision_mode=self._design_revision_mode_for_finding(finding),
                    ),
                )
            outputs = (
                bundle.evidence_graph_ref,
                bundle.coverage_map_ref,
                bundle.world_spec_ref,
                bundle.semantic_delta_ref,
                bundle.identity_decision_ref,
                bundle.semantic_lineage_ref,
                bundle.design_ref,
                modeling_gate_ref,
            )
            run.remember(*outputs)
            invalidated_refs = self._invalidate_artifact_descendants(
                run,
                superseded_refs=(previous.design_ref,),
                invalidating_refs=(*directive_refs, bundle.design_ref),
            )
            complete_design_routes(
                (),
                retained_refs=(bundle.design_ref,),
                usage=total_usage,
                invalidated_refs=invalidated_refs,
            )
            self._finish_attempt(
                run,
                attempt_id,
                status="passed",
                output_refs=outputs,
                usage=total_usage,
                profile_hash=self._last_profile_hash(bundle.invocation_results),
                session_id=self._last_session_id(bundle.invocation_results),
            )
            await self._persist_snapshot(run, status="running")
            return bundle
        except _GenerationHalt:
            raise
        except BudgetExceeded as exc:
            failure_usage = (
                settled_invocation_usage
                if work_settled
                else self._settle_failed_designer_work(run, work, exc)
            )
            self._finish_attempt(
                run,
                attempt_id,
                status="budget_exhausted",
                finding_refs=correction.finding_refs,
                failure_code="expansion_design_rework_budget_exhausted",
                failure_summary="Expansion design revision exceeded its vector budget.",
                usage=self._add_usage(BudgetUsage(repair_attempts=1), failure_usage),
            )
            self._terminate_repair_routes(
                run,
                routes,
                outcome="exhausted",
                retained_refs=(previous.design_ref,),
                usage=self._add_usage(BudgetUsage(repair_attempts=1), failure_usage),
            )
            raise _GenerationHalt(
                status="budget_exhausted",
                code="expansion_design_rework_budget_exhausted",
                summary=f"Expansion design rework exhausted: {', '.join(exc.dimensions)}.",
                finding_refs=correction.finding_refs,
            ) from exc
        except DesignerError as exc:
            failure_usage = self._settle_designer_error(
                run,
                work,
                exc,
                settled_invocation_usage if work_settled else None,
            )
            status, code = self._designer_failure_status(
                exc,
                default_code=f"expansion_design_rework_{self._safe_identifier(exc.stage)}",
            )
            self._finish_attempt(
                run,
                attempt_id,
                status=status,
                finding_refs=correction.finding_refs,
                failure_code=code,
                failure_summary="Expansion Designer did not commit a valid semantic revision.",
                usage=self._add_usage(BudgetUsage(repair_attempts=1), failure_usage),
                profile_hash=self._last_profile_hash(exc.results),
                session_id=self._last_session_id(exc.results),
            )
            self._terminate_repair_routes(
                run,
                routes,
                outcome=("exhausted" if status == "budget_exhausted" else "escalated"),
                retained_refs=(previous.design_ref,),
                usage=self._add_usage(BudgetUsage(repair_attempts=1), failure_usage),
            )
            raise _GenerationHalt(
                status=self._generate_status(status),
                code=code,
                summary="Expansion Designer failed during targeted upstream rework.",
                finding_refs=correction.finding_refs,
            ) from exc
        except Exception as exc:
            failure_usage = (
                settled_invocation_usage
                if work_settled
                else self._settle_failed_designer_work(run, work, exc)
            )
            self._finish_attempt(
                run,
                attempt_id,
                status="failed",
                finding_refs=correction.finding_refs,
                failure_code="expansion_designer_rework_infrastructure_error",
                failure_summary="Expansion design rework failed outside Agent protocol.",
                usage=self._add_usage(BudgetUsage(repair_attempts=1), failure_usage),
            )
            self._terminate_repair_routes(
                run,
                routes,
                outcome="escalated",
                retained_refs=(previous.design_ref,),
                usage=self._add_usage(BudgetUsage(repair_attempts=1), failure_usage),
            )
            raise _GenerationHalt(
                status="failed",
                code="expansion_designer_rework_infrastructure_error",
                summary="Expansion design rework infrastructure failed closed.",
                finding_refs=correction.finding_refs,
            ) from exc

    def _finish_running_attempt_if_needed(
        self,
        run: _RunState,
        attempt_id: str,
        *,
        status: Literal["failed", "needs_human", "budget_exhausted"],
        finding_refs: tuple[ArtifactRef, ...] = (),
        failure_code: str,
        failure_summary: str,
        usage: BudgetUsage | None = None,
        profile_hash: str | None = None,
        session_id: str | None = None,
    ) -> None:
        attempt = next(item for item in run.attempts if item.attempt_id == attempt_id)
        if attempt.status == "running":
            self._finish_attempt(
                run,
                attempt_id,
                status=status,
                finding_refs=finding_refs,
                failure_code=failure_code,
                failure_summary=failure_summary,
                usage=usage,
                profile_hash=profile_hash,
                session_id=session_id,
            )

    def _latest_judge_report(self, run: _RunState) -> JudgeReport | None:
        ref = self._latest_ref(run, "judge_report")
        return self.artifacts.get_json(ref, JudgeReport) if ref is not None else None

    def _expansion_identity_correction(
        self,
        *,
        run: _RunState,
        design_ref: ArtifactRef,
        error_type: str,
    ) -> _DesignReworkRequired:
        """Turn a framework Identity Gate rejection into a typed design loop edge."""

        finding_ref = self._control_failure_finding(
            run,
            node="design",
            event_kind=ControlEventKind.CONTRACT_FAILURE,
            code="expansion_identity_gate_failed",
            error_type=error_type,
            subject_ref=design_ref,
        )
        finding = self.artifacts.get_json(finding_ref, Finding)
        self.artifacts.require_exact_json(
            finding_ref,
            finding,
            artifact_types=("control.finding",),
        )
        return _DesignReworkRequired(
            findings=(finding,),
            finding_refs=(finding_ref,),
        )

    @staticmethod
    def _latest_ref(run: _RunState, artifact_type: str) -> ArtifactRef | None:
        matches = [ref for ref in run.latest.values() if ref.artifact_type == artifact_type]
        return matches[-1] if matches else None

    def _load_run_findings(self, run: _RunState) -> tuple[Finding, ...]:
        return tuple(self.artifacts.get_json(ref, Finding) for ref in run.findings.values())

    @staticmethod
    def _candidate_terminal_status(
        run: _RunState,
        halt: _GenerationHalt | None,
    ) -> CandidateTerminalStatus:
        if halt is None:
            return "infrastructure_error"
        if halt.status == "needs_human":
            return "needs_human"
        if halt.status == "budget_exhausted":
            return "budget_exhausted"
        if "infrastructure" in halt.code or halt.code == "judge_execution_error":
            return "infrastructure_error"
        failed_nodes = [
            item.node
            for item in run.attempts
            if item.status in {"failed", "needs_human", "budget_exhausted"}
        ]
        node = failed_nodes[-1] if failed_nodes else "design"
        if node == "design":
            return "research_failed" if "research" in halt.code else "design_failed"
        if node == "verifier":
            return "verifier_failed"
        if node == "build":
            return "build_failed"
        if node == "integration":
            return "integration_failed"
        if node == "judge":
            return "judge_failed"
        if node == "release":
            return "release_failed"
        return "infrastructure_error"

    @staticmethod
    def _candidate_attempt_status(
        terminal_status: CandidateTerminalStatus,
    ) -> Literal[
        "released",
        "failed",
        "needs_human",
        "budget_exhausted",
        "infrastructure_error",
    ]:
        if terminal_status == "released":
            return "released"
        if terminal_status == "needs_human":
            return "needs_human"
        if terminal_status == "budget_exhausted":
            return "budget_exhausted"
        if terminal_status == "infrastructure_error":
            return "infrastructure_error"
        return "failed"

    def _coverage_gains(
        self,
        primary_parent: ResolvedExpansionParent,
        design: ExpansionDesignBundle,
        judge_report_ref: ArtifactRef,
    ) -> tuple[CoverageGain, ...]:
        before_map = self.artifacts.get_json(
            primary_parent.design.coverage_map_ref,
            CoverageMap,
        )
        before = {item.dimension: item for item in before_map.dimensions}
        after = {item.dimension: item for item in design.coverage_map.dimensions}
        ranks = {"absent": 0, "partial": 1, "complete": 2, "not_applicable": -1}
        gains: list[CoverageGain] = []
        for dimension in sorted(set(before) | set(after)):
            before_level = self._semantic_coverage_level(before.get(dimension))
            after_level = self._semantic_coverage_level(after.get(dimension))
            if ranks[after_level] > ranks[before_level]:
                gains.append(
                    CoverageGain(
                        dimension=dimension,
                        before=before_level,
                        after=after_level,
                        evidence_refs=(design.coverage_map_ref, judge_report_ref),
                    )
                )
        return tuple(gains)

    @staticmethod
    def _semantic_coverage_level(value: CoverageDimension | None) -> CoverageLevel:
        if value is None:
            return "absent"
        evidence = value.evidence_discovered
        world = value.world_modelled
        if evidence == "not_applicable" and world == "not_applicable":
            return "not_applicable"
        if evidence == "complete" and world == "complete":
            return "complete"
        if evidence != "absent" or world != "absent":
            return "partial"
        return "absent"

    @staticmethod
    def _behavior_descriptors(
        design: ExpansionDesignBundle,
        judge_report_ref: ArtifactRef,
    ) -> tuple[BehaviorDescriptor, ...]:
        """Compute selection descriptors from the closed delta and Judge evidence."""

        delta = design.semantic_delta
        shared = {
            "semantic_delta_hash": delta.content_digest(),
            "world_spec_hash": design.world_spec.content_digest(),
        }
        values: list[tuple[str, dict[str, object]]] = []
        for operation in ("add", "remove", "modify"):
            surfaces = tuple(
                sorted(
                    item.tool_id
                    for item in delta.tool_surface_deltas
                    if item.operation == operation
                )
            )
            if surfaces:
                values.append((f"tool_surface:{operation}", {**shared, "tool_ids": list(surfaces)}))
            semantics = [
                {
                    "tool_id": item.tool_id,
                    "changed_aspects": sorted(item.changed_aspects),
                }
                for item in sorted(
                    delta.tool_semantics_deltas,
                    key=lambda candidate: candidate.tool_id,
                )
                if item.operation == operation
            ]
            if semantics:
                values.append((f"tool_semantics:{operation}", {**shared, "tools": semantics}))
            transitions = [
                {
                    "rule_id": item.rule_id,
                    "affected_tool_ids": sorted(item.affected_tool_ids),
                }
                for item in sorted(
                    delta.transition_constraint_deltas,
                    key=lambda candidate: candidate.rule_id,
                )
                if item.operation == operation
            ]
            if transitions:
                values.append(
                    (f"transition_constraint:{operation}", {**shared, "rules": transitions})
                )
            task_scopes = tuple(
                sorted(
                    item.task_type
                    for item in delta.task_scope_deltas
                    if item.operation == operation
                )
            )
            if task_scopes:
                values.append(
                    (f"task_scope:{operation}", {**shared, "task_types": list(task_scopes)})
                )
        if delta.state_schema_deltas:
            values.append(
                (
                    "state_schema",
                    {
                        **shared,
                        "changed_entities": sorted(
                            {
                                entity
                                for item in delta.state_schema_deltas
                                for entity in item.changed_entities
                            }
                        ),
                    },
                )
            )
        if delta.world_boundary_delta is not None:
            values.append(
                (
                    "world_boundary",
                    {
                        **shared,
                        "changed_dimensions": sorted(delta.world_boundary_delta.changed_dimensions),
                    },
                )
            )
        return tuple(
            BehaviorDescriptor(
                descriptor=descriptor,
                value=cast(JsonValue, value),
                evidence_refs=(design.semantic_delta_ref, judge_report_ref),
            )
            for descriptor, value in values
        )

    async def _resume_discovery_locked(
        self,
        *,
        discovery_run_id: str,
        budget: Budget,
    ) -> DiscoveryResumeResult:
        state_ref = self._discovery_state_head(discovery_run_id)
        state = self.artifacts.get_json(state_ref, DiscoveryLaneState)
        if state.discovery_run_ref.artifact_id != f"{discovery_run_id}:spec":
            raise ValueError("Discovery state is bound to a different run id")
        base_spec_ref = state.discovery_run_ref
        base_spec = self.artifacts.get_json(base_spec_ref, DiscoveryRunSpec)
        self.artifacts.require_exact_json(
            base_spec_ref,
            base_spec,
            artifact_types=("discovery.run_spec",),
        )
        if base_spec.discovery_run_id != discovery_run_id:
            raise ValueError("Discovery spec id does not match the requested run")
        if state.status in {
            "admitted",
            "quarantine_dismissed",
            "quarantine_confirmed",
        }:
            existing_status = cast(
                Literal[
                    "admitted",
                    "quarantine_dismissed",
                    "quarantine_confirmed",
                ],
                state.status,
            )
            return DiscoveryResumeResult(
                discovery_run_id=discovery_run_id,
                status=existing_status,
                spec_ref=base_spec_ref,
                state_ref=state_ref,
                used_budget=state.used_budget,
                inbox_ref=state.inbox_ref,
                recommendation_refs=state.recommendation_refs,
                quarantine_review_refs=state.quarantine_review_refs,
                finding_refs=state.finding_refs,
            )
        if state.status == "quarantine_recommended":
            if state.baseline_ref is None:
                raise ValueError("quarantine recommendation has no Design baseline")
            reviews = self._review_quarantine_refs(
                recommendation_refs=state.recommendation_refs,
                baseline_ref=state.baseline_ref,
            )
            review_refs = tuple(item.decision_ref for item in reviews)
            finding_refs = tuple(
                item.finding_ref for item in reviews if item.finding_ref is not None
            )
            reviewed_status: Literal["quarantine_dismissed", "quarantine_confirmed"] = (
                "quarantine_confirmed" if finding_refs else "quarantine_dismissed"
            )
            reviewed_state = state.model_copy(
                update={
                    "status": reviewed_status,
                    "quarantine_review_refs": review_refs,
                    "finding_refs": finding_refs,
                }
            )
            reviewed_ref = self._persist_discovery_state(
                spec_ref=base_spec_ref,
                state=reviewed_state,
                previous_ref=state_ref,
                extra_dependencies=(
                    state.baseline_ref,
                    *state.clue_refs,
                    *state.admission_decision_refs,
                    *state.recommendation_refs,
                    *review_refs,
                    *finding_refs,
                    *((state.inbox_ref,) if state.inbox_ref else ()),
                ),
            )
            if reviewed_status == "quarantine_confirmed":
                self._quarantine_released_baseline(state.baseline_ref)
            self.artifacts.record_event(
                event_type=(
                    "discovery_quarantine_confirmed"
                    if reviewed_status == "quarantine_confirmed"
                    else "discovery_quarantine_dismissed"
                ),
                subject_ref=reviewed_ref,
                related_refs=(*review_refs, *finding_refs),
                reason_code=(
                    "discovery_hard_correction_confirmed"
                    if reviewed_status == "quarantine_confirmed"
                    else "discovery_hard_correction_dismissed"
                ),
            )
            return DiscoveryResumeResult(
                discovery_run_id=discovery_run_id,
                status=reviewed_status,
                spec_ref=base_spec_ref,
                state_ref=reviewed_ref,
                used_budget=state.used_budget,
                inbox_ref=state.inbox_ref,
                recommendation_refs=state.recommendation_refs,
                quarantine_review_refs=review_refs,
                finding_refs=finding_refs,
            )

        if state.status in {"pending", "running", "inbox_staged", "admitting"}:
            state_ref, state = self._settle_unknown_discovery_state(
                spec_ref=base_spec_ref,
                state_ref=state_ref,
                state=state,
            )

        request = self.artifacts.get_json(base_spec.request_ref, EnvironmentRequest)
        self.artifacts.require_exact_json(
            base_spec.request_ref,
            request,
            artifact_types=("control.environment_request",),
        )
        spec_ordinal = len(self.artifacts.list_revisions(base_spec_ref.artifact_id)) + 1
        resumed_spec = base_spec.model_copy(
            update={"budget": budget, "seed": base_spec.seed + spec_ordinal}
        )
        resumed_spec_ref = self.artifacts.put_json(
            artifact_id=base_spec_ref.artifact_id,
            artifact_type="discovery.run_spec",
            value=resumed_spec,
            dependencies=(base_spec_ref, state_ref, base_spec.request_ref),
        )
        ledger = BudgetLedger(budget)
        pending_ref = self._persist_resumed_discovery_state(
            spec_ref=resumed_spec_ref,
            previous_ref=state_ref,
            source_state=state,
            status="pending",
            used_budget=ledger.used,
        )
        workspace = self._workspace_for(discovery_run_id, f"resume-{spec_ordinal}")
        resume_started = time.monotonic()
        bundle: DiscoveryBundle | None = None
        staged: AdmissionBundle | None = None
        active_budget = Budget()
        active_accounted = False
        progress_ref = pending_ref
        try:
            if state.inbox_ref is not None:
                bundle = self._rebuild_discovery_bundle(state.clue_refs)
            else:
                active_budget = self._plan_designer_budget(
                    budget,
                    base_turns=2,
                    maximum_corrections=2 * self.designer.maximum_structured_reworks,
                )
            running_ref = self._persist_resumed_discovery_state(
                spec_ref=resumed_spec_ref,
                previous_ref=pending_ref,
                source_state=state,
                status="running",
                used_budget=ledger.used,
            )
            progress_ref = running_ref
            self.artifacts.record_event(
                event_type="discovery_resume_started",
                subject_ref=resumed_spec_ref,
                related_refs=(state_ref, running_ref),
            )
            if bundle is None:
                bundle = await asyncio.wait_for(
                    self.discovery.discover(
                        run_spec=resumed_spec,
                        run_ref=resumed_spec_ref,
                        request=request,
                        workspace=workspace / "research",
                        invocation_budget=active_budget,
                    ),
                    timeout=active_budget.wall_seconds,
                )
                invocation_actual, invocation_unknown = self._designer_bundle_settlement(bundle)
                ledger.consume_uncertain(
                    observed_actual=invocation_actual,
                    unknown_upper_bound=invocation_unknown,
                )
                ledger.consume(bundle.research_usage)
                active_accounted = True

            staged = self.discovery.stage_late_inbox(
                run_spec=resumed_spec,
                discovery=bundle,
                baseline_ref=state.baseline_ref,
            )
            admission = staged
            if state.baseline_ref is not None and bundle.clues:
                baseline = self.artifacts.get_json(
                    state.baseline_ref,
                    DesignBaselineCheckpoint,
                )
                baseline_evidence = self.artifacts.get_json(
                    baseline.evidence_graph_ref,
                    EvidenceGraph,
                )
                elapsed = max(0.0, time.monotonic() - resume_started)
                remaining = ledger.remaining.model_copy(
                    update={"wall_seconds": max(0.0, budget.wall_seconds - elapsed)}
                )
                admission_turns = min(
                    len(bundle.clues),
                    remaining.agent_turns,
                    remaining.llm_tokens // self.config.agent.structured_turn_token_limit,
                )
                if admission_turns <= 0 or remaining.wall_seconds <= 0:
                    raise BudgetExceeded(("agent_turns", "llm_tokens", "wall_seconds"))
                active_budget = self._plan_designer_budget(
                    remaining,
                    base_turns=admission_turns,
                    maximum_corrections=(
                        admission_turns * self.designer.maximum_structured_reworks
                    ),
                )
                active_accounted = False
                admission = await asyncio.wait_for(
                    self.discovery.admit(
                        run_spec=resumed_spec,
                        discovery=bundle,
                        workspace=workspace / "admission",
                        baseline=baseline,
                        baseline_ref=state.baseline_ref,
                        baseline_evidence=baseline_evidence,
                        invocation_budget=active_budget,
                    ),
                    timeout=active_budget.wall_seconds,
                )
                invocation_actual, invocation_unknown = self._designer_bundle_settlement(admission)
                ledger.consume_uncertain(
                    observed_actual=invocation_actual,
                    unknown_upper_bound=invocation_unknown,
                )
                active_accounted = True

            self._charge_discovery_wall(ledger, budget, resume_started)
            terminal_reviews: tuple[QuarantineReviewBundle, ...] = ()
            if admission.recommendation_refs:
                if state.baseline_ref is None:
                    raise ValueError("quarantine recommendation has no Design baseline")
                terminal_reviews = self._review_quarantine_refs(
                    recommendation_refs=admission.recommendation_refs,
                    baseline_ref=state.baseline_ref,
                )
            review_refs = tuple(item.decision_ref for item in terminal_reviews)
            finding_refs = tuple(
                item.finding_ref for item in terminal_reviews if item.finding_ref is not None
            )
            terminal_status: Literal["admitted", "quarantine_dismissed", "quarantine_confirmed"] = (
                "quarantine_confirmed"
                if finding_refs
                else "quarantine_dismissed"
                if admission.recommendation_refs
                else "admitted"
            )
            terminal_state = DiscoveryLaneState(
                discovery_run_ref=resumed_spec_ref,
                status=terminal_status,
                reserved_budget=budget,
                used_budget=ledger.used,
                baseline_ref=state.baseline_ref,
                clue_refs=bundle.clue_refs,
                admission_decision_refs=admission.decision_refs,
                recommendation_refs=admission.recommendation_refs,
                quarantine_review_refs=review_refs,
                finding_refs=finding_refs,
                inbox_ref=admission.inbox_ref,
            )
            terminal_ref = self._persist_discovery_state(
                spec_ref=resumed_spec_ref,
                state=terminal_state,
                previous_ref=progress_ref,
                extra_dependencies=(
                    *((state.baseline_ref,) if state.baseline_ref else ()),
                    *bundle.clue_refs,
                    *admission.decision_refs,
                    *admission.recommendation_refs,
                    *review_refs,
                    *finding_refs,
                    admission.inbox_ref,
                ),
            )
            if terminal_status == "quarantine_confirmed" and state.baseline_ref is not None:
                self._quarantine_released_baseline(state.baseline_ref)
            self.artifacts.record_event(
                event_type="discovery_resume_completed",
                subject_ref=terminal_ref,
                related_refs=(
                    resumed_spec_ref,
                    admission.inbox_ref,
                    *admission.recommendation_refs,
                    *review_refs,
                    *finding_refs,
                ),
                reason_code=(
                    "discovery_hard_correction_confirmed"
                    if terminal_status == "quarantine_confirmed"
                    else "discovery_hard_correction_dismissed"
                    if terminal_status == "quarantine_dismissed"
                    else None
                ),
            )
            return DiscoveryResumeResult(
                discovery_run_id=discovery_run_id,
                status=terminal_status,
                spec_ref=resumed_spec_ref,
                state_ref=terminal_ref,
                used_budget=ledger.used,
                inbox_ref=admission.inbox_ref,
                recommendation_refs=admission.recommendation_refs,
                quarantine_review_refs=review_refs,
                finding_refs=finding_refs,
            )
        except Exception as exc:
            if not active_accounted and self._budget_has_capacity(active_budget):
                try:
                    usage = (
                        exc.budget_usage
                        if isinstance(exc, DesignerError) and exc.budget_usage is not None
                        else self._budget_as_usage(active_budget)
                    )
                    ledger.consume(usage)
                except BudgetExceeded:
                    pass
            self._charge_discovery_wall(ledger, budget, resume_started)
            failure_code = self._exception_code("discovery_resume", exc)
            if isinstance(exc, DesignerBudgetPlanError):
                failure_code = f"discovery_resume_budget_{exc.dimension}_insufficient"
            clue_refs = bundle.clue_refs if bundle else state.clue_refs
            decision_refs = staged.decision_refs if staged else state.admission_decision_refs
            inbox_ref = staged.inbox_ref if staged else state.inbox_ref
            failed_state = DiscoveryLaneState(
                discovery_run_ref=resumed_spec_ref,
                status="failed",
                reserved_budget=budget,
                used_budget=ledger.used,
                baseline_ref=state.baseline_ref,
                clue_refs=clue_refs,
                admission_decision_refs=decision_refs,
                inbox_ref=inbox_ref,
                failure_code=failure_code,
            )
            failed_ref = self._persist_discovery_state(
                spec_ref=resumed_spec_ref,
                state=failed_state,
                previous_ref=progress_ref,
                extra_dependencies=(
                    *((state.baseline_ref,) if state.baseline_ref else ()),
                    *clue_refs,
                    *decision_refs,
                    *((inbox_ref,) if inbox_ref else ()),
                ),
            )
            self.artifacts.record_event(
                event_type=(
                    "discovery_resume_not_started"
                    if progress_ref == pending_ref
                    else "discovery_resume_failed"
                ),
                subject_ref=failed_ref,
                related_refs=(resumed_spec_ref,),
                reason_code=failure_code,
            )
            return DiscoveryResumeResult(
                discovery_run_id=discovery_run_id,
                status="failed",
                spec_ref=resumed_spec_ref,
                state_ref=failed_ref,
                used_budget=ledger.used,
                inbox_ref=inbox_ref,
                failure_code=failure_code,
            )

    def _discovery_state_head(self, discovery_run_id: str) -> ArtifactRef:
        artifact_id = f"{discovery_run_id}:spec:state"
        revisions = tuple(
            ref
            for ref in self.artifacts.list_revisions(artifact_id)
            if ref.artifact_type == "control.discovery_lane_state"
        )
        if not revisions:
            raise ValueError("Discovery run does not have a durable lane state")
        predecessor_ids = {
            dependency.revision_id
            for ref in revisions
            for dependency in self.artifacts.dependencies(ref)
            if dependency.artifact_id == artifact_id
        }
        heads = tuple(ref for ref in revisions if ref.revision_id not in predecessor_ids)
        if len(heads) != 1:
            raise ValueError("Discovery lane state DAG is forked or has no unique head")
        return heads[0]

    def _settle_unknown_discovery_state(
        self,
        *,
        spec_ref: ArtifactRef,
        state_ref: ArtifactRef,
        state: DiscoveryLaneState,
    ) -> tuple[ArtifactRef, DiscoveryLaneState]:
        ledger = BudgetLedger(state.reserved_budget)
        ledger.consume(state.used_budget)
        try:
            ledger.consume(self._budget_as_usage(ledger.remaining))
        except BudgetExceeded:
            pass
        deferred = state.model_copy(
            update={"status": "deferred", "used_budget": ledger.used, "failure_code": None}
        )
        deferred_ref = self._persist_discovery_state(
            spec_ref=spec_ref,
            state=deferred,
            previous_ref=state_ref,
            extra_dependencies=(
                *((state.baseline_ref,) if state.baseline_ref else ()),
                *state.clue_refs,
                *state.admission_decision_refs,
                *state.recommendation_refs,
                *((state.inbox_ref,) if state.inbox_ref else ()),
            ),
        )
        self.artifacts.record_event(
            event_type="discovery_unknown_work_settled",
            subject_ref=deferred_ref,
            related_refs=(state_ref,),
            reason_code="resume_unknown_work_charged",
        )
        return deferred_ref, deferred

    def _persist_resumed_discovery_state(
        self,
        *,
        spec_ref: ArtifactRef,
        previous_ref: ArtifactRef,
        source_state: DiscoveryLaneState,
        status: Literal["pending", "running"],
        used_budget: BudgetUsage,
    ) -> ArtifactRef:
        state = DiscoveryLaneState(
            discovery_run_ref=spec_ref,
            status=status,
            reserved_budget=self.artifacts.get_json(spec_ref, DiscoveryRunSpec).budget,
            used_budget=used_budget,
            baseline_ref=source_state.baseline_ref,
            clue_refs=source_state.clue_refs,
            admission_decision_refs=source_state.admission_decision_refs,
            inbox_ref=source_state.inbox_ref,
        )
        return self._persist_discovery_state(
            spec_ref=spec_ref,
            state=state,
            previous_ref=previous_ref,
            extra_dependencies=(
                *((source_state.baseline_ref,) if source_state.baseline_ref else ()),
                *source_state.clue_refs,
                *source_state.admission_decision_refs,
                *((source_state.inbox_ref,) if source_state.inbox_ref else ()),
            ),
        )

    def _rebuild_discovery_bundle(
        self,
        clue_refs: tuple[ArtifactRef, ...],
    ) -> DiscoveryBundle:
        clues = tuple(self.artifacts.get_json(ref, ExpansionClue) for ref in clue_refs)
        return DiscoveryBundle(
            clues=clues,
            clue_refs=clue_refs,
            # Clues bind extracted-content refs, not serialized Evidence models.
            # Admission consumes the typed clues and preserves those refs in its
            # decisions/Findings; it does not require an in-memory Evidence catalog.
            evidence=(),
            research_usage=BudgetUsage(),
            invocation_usage=BudgetUsage(),
            invocation_results=(),
        )

    @staticmethod
    def _budget_has_capacity(budget: Budget) -> bool:
        return any(
            getattr(budget, field_name) > 0
            for field_name in Budget.model_fields
            if field_name != "schema_version"
        )

    @staticmethod
    def _charge_discovery_wall(
        ledger: BudgetLedger,
        budget: Budget,
        started: float,
    ) -> None:
        remaining = max(0.0, budget.wall_seconds - ledger.used.wall_seconds)
        ledger.consume(
            BudgetUsage(wall_seconds=min(remaining, max(0.0, time.monotonic() - started)))
        )

    async def _start_discovery(
        self,
        *,
        run: _RunState,
        job: EnvironmentJob,
        job_ref: ArtifactRef,
        request: EnvironmentRequest,
        request_ref: ArtifactRef,
        budget: Budget,
    ) -> _DiscoveryLane | None:
        if not request.allowed_source_kinds:
            self.artifacts.record_event(
                event_type="discovery_not_started",
                subject_ref=job_ref,
                reason_code="no_allowed_sources",
            )
            return None
        discovery_permissions = PermissionScope(
            filesystem_read_roots=request.permissions.filesystem_read_roots,
            network_domains=request.permissions.network_domains,
            tool_allowlist=request.permissions.tool_allowlist,
            credential_handles=request.permissions.credential_handles,
            allow_external_side_effects=False,
        )
        descriptor = self.profiles.profile_descriptor(
            "researcher",
            permissions=discovery_permissions,
            requirement=NodeCapabilityRequirement.structured_read(
                node_id="researcher.structured-output",
                role="researcher",
            ),
        )
        descriptor_ref = self.artifacts.put_json(
            artifact_id=f"{run.run_id}:discovery-profile",
            artifact_type="control.agent_profile_descriptor",
            value=descriptor,
            dependencies=(job_ref,),
        )
        discovery_run_id = self._stable_id(
            "discovery-run",
            run.run_id,
            request_ref.revision_id,
        )
        seed = int(
            hashlib.sha256(f"{job.job_id}\0{request_ref.revision_id}".encode()).hexdigest()[:16],
            16,
        )
        spec = DiscoveryRunSpec(
            discovery_run_id=discovery_run_id,
            origin_job_ref=job_ref,
            request_ref=request_ref,
            source_kinds=request.allowed_source_kinds,
            agent_profile_ref=descriptor_ref,
            budget=budget,
            permissions=discovery_permissions,
            priority="low",
            seed=seed,
        )
        spec_ref = self.artifacts.put_json(
            artifact_id=f"{discovery_run_id}:spec",
            artifact_type="discovery.run_spec",
            value=spec,
            dependencies=(job_ref, request_ref, descriptor_ref),
        )
        discovery_ledger = BudgetLedger(budget)
        pending_ref = self._persist_discovery_state(
            spec_ref=spec_ref,
            state=DiscoveryLaneState(
                discovery_run_ref=spec_ref,
                status="pending",
                reserved_budget=budget,
                used_budget=discovery_ledger.used,
            ),
        )
        run.remember(descriptor_ref, spec_ref, pending_ref)
        attempt_id = self._start_attempt(run, "discovery", (spec_ref,))
        workspace = self._workspace_for(run.run_id, "discovery")
        try:
            invocation_budget = self._plan_designer_budget(
                budget,
                base_turns=2,
                maximum_corrections=2 * self.designer.maximum_structured_reworks,
            )
        except DesignerBudgetPlanError as exc:
            await self._reject_discovery_budget_start(
                run=run,
                job_ref=job_ref,
                spec_ref=spec_ref,
                pending_ref=pending_ref,
                ledger=discovery_ledger,
                failure=exc,
            )
            return None
        started_monotonic = time.monotonic()
        task = asyncio.create_task(
            asyncio.wait_for(
                self.discovery.discover(
                    run_spec=spec,
                    run_ref=spec_ref,
                    request=request,
                    workspace=workspace,
                    invocation_budget=invocation_budget,
                ),
                timeout=budget.wall_seconds,
            ),
            name=f"agent-world-{discovery_run_id}",
        )
        running_ref = self._persist_discovery_state(
            spec_ref=spec_ref,
            state=DiscoveryLaneState(
                discovery_run_ref=spec_ref,
                status="running",
                reserved_budget=budget,
                used_budget=discovery_ledger.used,
            ),
            previous_ref=pending_ref,
        )
        run.remember(running_ref)
        # Discovery remains independent from Direct success.  A started event
        # is emitted only after budget admission and task creation both succeed.
        self.artifacts.record_event(
            event_type="discovery_started",
            subject_ref=spec_ref,
            related_refs=(running_ref,),
            details=(KeyValue(key="attempt_id", value=attempt_id),),
        )
        await self._persist_snapshot(run, status="running")
        lane = _DiscoveryLane(
            spec=spec,
            spec_ref=spec_ref,
            ledger=discovery_ledger,
            task=task,
            state_ref=running_ref,
            invocation_budget=invocation_budget,
            started_monotonic=started_monotonic,
        )
        return lane

    async def _reject_discovery_budget_start(
        self,
        *,
        run: _RunState,
        job_ref: ArtifactRef,
        spec_ref: ArtifactRef,
        pending_ref: ArtifactRef,
        ledger: BudgetLedger,
        failure: DesignerBudgetPlanError,
    ) -> None:
        """Close a non-admitted optional lane without touching Direct budget."""

        failure_code = f"discovery_budget_{failure.dimension}_insufficient"
        failed_ref = self._persist_discovery_state(
            spec_ref=spec_ref,
            state=DiscoveryLaneState(
                discovery_run_ref=spec_ref,
                status="failed",
                reserved_budget=ledger.reserved,
                used_budget=ledger.used,
                failure_code=failure_code,
            ),
            previous_ref=pending_ref,
        )
        failure_ref = self.artifacts.put_json(
            artifact_id=f"{run.run_id}:discovery-start-failure",
            artifact_type="control.failure_evidence",
            value={
                "run_id": run.run_id,
                "node": "discovery",
                "stage": "discovery_research",
                "failure_code": failure_code,
                "error_type": "designer_budget_plan_failure",
                "dimension": failure.dimension,
                "reserved": failure.reserved,
                "required": failure.required,
                "base_turns": failure.base_turns,
                "turn_token_limit": failure.rollout_token_limit,
            },
            dependencies=(job_ref, spec_ref, failed_ref),
        )
        run.remember(failed_ref, failure_ref)
        self._finish_discovery_attempt(
            run,
            status="failed",
            output_refs=(failed_ref, failure_ref),
            usage=ledger.used,
            failure_code=failure_code,
        )
        self.artifacts.record_event(
            event_type="discovery_not_started",
            subject_ref=failure_ref,
            related_refs=(spec_ref, failed_ref),
            reason_code=failure_code,
        )
        await self._persist_snapshot(run, status="running")

    async def _poll_discovery(
        self,
        run: _RunState,
        lane: _DiscoveryLane,
        design: DesignBundle,
    ) -> None:
        """Advance already-complete Discovery work without awaiting either task."""

        if lane.closed:
            return
        changed = False
        if lane.bundle is None:
            if not lane.task.done():
                return
            try:
                bundle = lane.task.result()
                invocation_actual, invocation_unknown = self._designer_bundle_settlement(bundle)
                lane.ledger.consume_uncertain(
                    observed_actual=invocation_actual,
                    unknown_upper_bound=invocation_unknown,
                )
                lane.ledger.consume(bundle.research_usage)
                lane.discovery_accounted = True
                lane.bundle = bundle
                lane.admission = self.discovery.stage_late_inbox(
                    run_spec=lane.spec,
                    discovery=bundle,
                    baseline_ref=design.baseline_ref,
                )
                lane.state_ref = self._persist_discovery_progress_state(
                    run=run,
                    lane=lane,
                    status="inbox_staged",
                    baseline_ref=design.baseline_ref,
                )
                changed = True
            except asyncio.CancelledError as exc:
                self._fail_discovery_lane(run, lane, exc)
                changed = True
            except Exception as exc:
                self._fail_discovery_lane(run, lane, exc)
                changed = True
            if lane.closed:
                await self._persist_snapshot(run, status="running")
                return

        assert lane.bundle is not None
        assert lane.admission is not None
        if lane.admission_task is None:
            if not lane.bundle.clues:
                lane.admitted = True
                lane.closed = True
                lane.state_ref = self._persist_discovery_progress_state(
                    run=run,
                    lane=lane,
                    status="admitted",
                    baseline_ref=design.baseline_ref,
                )
                self._finish_discovery_attempt(
                    run,
                    status="passed",
                    output_refs=(lane.state_ref, lane.admission.inbox_ref),
                    usage=lane.ledger.used,
                )
                await self._persist_snapshot(run, status="running")
                return
            remaining = self._discovery_remaining_budget(lane)
            if (
                remaining.agent_turns <= 0
                or remaining.llm_tokens < self.config.agent.structured_turn_token_limit
                or remaining.wall_seconds <= 0
            ):
                await self._defer_discovery(
                    run,
                    lane,
                    reason="discovery_admission_budget_unavailable",
                    baseline_ref=design.baseline_ref,
                )
                return
            admission_turns = min(
                len(lane.bundle.clues),
                remaining.agent_turns,
                remaining.llm_tokens // self.config.agent.structured_turn_token_limit,
            )
            try:
                lane.admission_budget = self._plan_designer_budget(
                    remaining,
                    base_turns=admission_turns,
                    maximum_corrections=(
                        admission_turns * self.designer.maximum_structured_reworks
                    ),
                )
                lane.admission_task = asyncio.create_task(
                    asyncio.wait_for(
                        self.discovery.admit(
                            run_spec=lane.spec,
                            discovery=lane.bundle,
                            workspace=self._workspace_for(run.run_id, "discovery-admission"),
                            baseline=design.baseline,
                            baseline_ref=design.baseline_ref,
                            baseline_evidence=design.evidence_graph,
                            invocation_budget=lane.admission_budget,
                        ),
                        timeout=lane.admission_budget.wall_seconds,
                    ),
                    name=f"agent-world-{lane.spec.discovery_run_id}-admission",
                )
                lane.state_ref = self._persist_discovery_progress_state(
                    run=run,
                    lane=lane,
                    status="admitting",
                    baseline_ref=design.baseline_ref,
                )
                await self._persist_snapshot(run, status="running")
            except asyncio.CancelledError as exc:
                self._fail_discovery_lane(run, lane, exc, stage="discovery_admission")
                await self._persist_snapshot(run, status="running")
            except Exception as exc:
                self._fail_discovery_lane(run, lane, exc, stage="discovery_admission")
                await self._persist_snapshot(run, status="running")
            return

        if not lane.admission_task.done():
            if changed:
                await self._persist_snapshot(run, status="running")
            return
        correction: _DesignReworkRequired | None = None
        try:
            admission = lane.admission_task.result()
            invocation_actual, invocation_unknown = self._designer_bundle_settlement(admission)
            lane.ledger.consume_uncertain(
                observed_actual=invocation_actual,
                unknown_upper_bound=invocation_unknown,
            )
            lane.admission_accounted = True
            lane.admission = admission
            lane.admitted = True
            lane.closed = True
            correction = self._review_discovery_recommendations(
                run=run,
                lane=lane,
                design=design,
            )
            status = self._discovery_terminal_status(lane)
            lane.state_ref = self._persist_discovery_progress_state(
                run=run,
                lane=lane,
                status=status,
                baseline_ref=design.baseline_ref,
            )
            self._finish_discovery_attempt(
                run,
                status="passed",
                output_refs=(
                    lane.state_ref,
                    admission.inbox_ref,
                    *admission.recommendation_refs,
                    *(item.decision_ref for item in lane.quarantine_reviews),
                    *(
                        item.finding_ref
                        for item in lane.quarantine_reviews
                        if item.finding_ref is not None
                    ),
                ),
                usage=lane.ledger.used,
            )
            self.artifacts.record_event(
                event_type=(
                    "discovery_quarantine_confirmed"
                    if status == "quarantine_confirmed"
                    else "discovery_quarantine_dismissed"
                    if status == "quarantine_dismissed"
                    else "discovery_quarantine_recommended"
                    if status == "quarantine_recommended"
                    else "discovery_admitted"
                ),
                subject_ref=lane.state_ref,
                related_refs=(
                    admission.inbox_ref,
                    *admission.recommendation_refs,
                    *(item.decision_ref for item in lane.quarantine_reviews),
                    *(
                        item.finding_ref
                        for item in lane.quarantine_reviews
                        if item.finding_ref is not None
                    ),
                ),
                reason_code=(
                    "discovery_hard_correction_confirmed"
                    if status == "quarantine_confirmed"
                    else "discovery_hard_correction_dismissed"
                    if status == "quarantine_dismissed"
                    else "discovery_hard_correction_recommended"
                    if status == "quarantine_recommended"
                    else None
                ),
            )
        except asyncio.CancelledError as exc:
            self._fail_discovery_lane(run, lane, exc, stage="discovery_admission")
        except Exception as exc:
            self._fail_discovery_lane(run, lane, exc, stage="discovery_admission")
        await self._persist_snapshot(run, status="running")
        if correction is not None:
            raise correction

    def _freeze_discovery_for_release(
        self,
        run: _RunState,
        lane: _DiscoveryLane,
        design: DesignBundle,
    ) -> None:
        """Synchronously freeze the optional lane before the atomic Direct commit.

        Only already-complete task results are observed.  No coroutine is run or
        awaited here; unfinished work becomes a durable deferred work order.
        """

        if lane.closed:
            return
        if lane.bundle is None and lane.task.done():
            try:
                bundle = lane.task.result()
                invocation_actual, invocation_unknown = self._designer_bundle_settlement(bundle)
                lane.ledger.consume_uncertain(
                    observed_actual=invocation_actual,
                    unknown_upper_bound=invocation_unknown,
                )
                lane.ledger.consume(bundle.research_usage)
                lane.discovery_accounted = True
                lane.bundle = bundle
                lane.admission = self.discovery.stage_late_inbox(
                    run_spec=lane.spec,
                    discovery=bundle,
                    baseline_ref=design.baseline_ref,
                )
                lane.state_ref = self._persist_discovery_progress_state(
                    run=run,
                    lane=lane,
                    status="inbox_staged",
                    baseline_ref=design.baseline_ref,
                )
            except asyncio.CancelledError as exc:
                self._fail_discovery_lane(run, lane, exc)
            except Exception as exc:
                self._fail_discovery_lane(run, lane, exc)
        if lane.closed:
            return
        correction: _DesignReworkRequired | None = None
        if lane.admission_task is not None and lane.admission_task.done():
            try:
                admission = lane.admission_task.result()
                invocation_actual, invocation_unknown = self._designer_bundle_settlement(admission)
                lane.ledger.consume_uncertain(
                    observed_actual=invocation_actual,
                    unknown_upper_bound=invocation_unknown,
                )
                lane.admission_accounted = True
                lane.admission = admission
                lane.admitted = True
                lane.closed = True
                correction = self._review_discovery_recommendations(
                    run=run,
                    lane=lane,
                    design=design,
                )
                status = self._discovery_terminal_status(lane)
                lane.state_ref = self._persist_discovery_progress_state(
                    run=run,
                    lane=lane,
                    status=status,
                    baseline_ref=design.baseline_ref,
                )
                self._finish_discovery_attempt(
                    run,
                    status="passed",
                    output_refs=(
                        lane.state_ref,
                        admission.inbox_ref,
                        *admission.recommendation_refs,
                        *(item.decision_ref for item in lane.quarantine_reviews),
                        *(
                            item.finding_ref
                            for item in lane.quarantine_reviews
                            if item.finding_ref is not None
                        ),
                    ),
                    usage=lane.ledger.used,
                )
            except asyncio.CancelledError as exc:
                self._fail_discovery_lane(run, lane, exc, stage="discovery_admission")
            except Exception as exc:
                self._fail_discovery_lane(run, lane, exc, stage="discovery_admission")
        if correction is not None:
            raise correction
        if not lane.closed:
            self._defer_discovery_now(
                run,
                lane,
                reason="foreground_release_ready",
                baseline_ref=design.baseline_ref,
            )

    async def _defer_discovery(
        self,
        run: _RunState,
        lane: _DiscoveryLane,
        *,
        reason: str,
        baseline_ref: ArtifactRef | None = None,
    ) -> None:
        if self._defer_discovery_now(
            run,
            lane,
            reason=reason,
            baseline_ref=baseline_ref,
        ):
            await self._persist_snapshot(run, status="running")

    def _defer_discovery_now(
        self,
        run: _RunState,
        lane: _DiscoveryLane,
        *,
        reason: str,
        baseline_ref: ArtifactRef | None = None,
    ) -> bool:
        if lane.closed:
            return False
        active_task: asyncio.Task[object]
        active_budget: Budget
        if lane.admission_task is not None:
            active_task = cast(asyncio.Task[object], lane.admission_task)
            active_budget = lane.admission_budget
        else:
            active_task = cast(asyncio.Task[object], lane.task)
            active_budget = lane.invocation_budget
        if not active_task.done():
            active_task.cancel()
            active_task.add_done_callback(self._consume_optional_task_result)
            try:
                if active_task is lane.task and not lane.discovery_accounted:
                    lane.ledger.consume(self._budget_as_usage(active_budget))
                    lane.discovery_accounted = True
                elif active_task is lane.admission_task and not lane.admission_accounted:
                    lane.ledger.consume(self._budget_as_usage(active_budget))
                    lane.admission_accounted = True
            except BudgetExceeded:
                pass
        else:
            self._consume_optional_task_result(active_task)
        lane.closed = True
        state = DiscoveryLaneState(
            discovery_run_ref=lane.spec_ref,
            status="deferred",
            reserved_budget=lane.ledger.reserved,
            used_budget=lane.ledger.used,
            baseline_ref=baseline_ref,
            clue_refs=lane.bundle.clue_refs if lane.bundle else (),
            admission_decision_refs=lane.admission.decision_refs if lane.admission else (),
            inbox_ref=lane.admission.inbox_ref if lane.admission else None,
        )
        lane.state_ref = self._persist_discovery_state(
            spec_ref=lane.spec_ref,
            state=state,
            previous_ref=lane.state_ref,
            extra_dependencies=(
                *((baseline_ref,) if baseline_ref else ()),
                *(lane.bundle.clue_refs if lane.bundle else ()),
                *(lane.admission.decision_refs if lane.admission else ()),
                *((lane.admission.inbox_ref,) if lane.admission else ()),
            ),
        )
        run.remember(lane.state_ref)
        self._finish_discovery_attempt(
            run,
            status="pending",
            output_refs=(),
            usage=lane.ledger.used,
        )
        self.artifacts.record_event(
            event_type="discovery_deferred",
            subject_ref=lane.state_ref,
            related_refs=(lane.spec_ref,),
            reason_code=self._safe_identifier(reason),
        )
        return True

    def _discovery_remaining_budget(self, lane: _DiscoveryLane) -> Budget:
        elapsed = max(0.0, time.monotonic() - lane.started_monotonic)
        return lane.ledger.remaining.model_copy(
            update={"wall_seconds": max(0.0, lane.ledger.reserved.wall_seconds - elapsed)}
        )

    def _review_discovery_recommendations(
        self,
        *,
        run: _RunState,
        lane: _DiscoveryLane,
        design: DesignBundle,
    ) -> _DesignReworkRequired | None:
        """Compile semantic recommendations through the framework authority wall."""

        if lane.admission is None or not lane.admission.recommendation_refs:
            return None
        reviews = self._review_quarantine_refs(
            recommendation_refs=lane.admission.recommendation_refs,
            baseline_ref=design.baseline_ref,
        )
        lane.quarantine_reviews = reviews
        review_refs = tuple(item.decision_ref for item in reviews)
        finding_pairs = tuple(
            (item.finding, item.finding_ref)
            for item in reviews
            if item.finding is not None and item.finding_ref is not None
        )
        run.remember(*review_refs)
        if not finding_pairs:
            return None
        findings = tuple(item[0] for item in finding_pairs)
        finding_refs = tuple(item[1] for item in finding_pairs)
        run.remember_findings(*finding_refs)
        validated_revisions = {
            ref.revision_id for item in reviews for ref in item.decision.validated_evidence_refs
        }
        additional_evidence = tuple(
            evidence
            for evidence in (lane.bundle.evidence if lane.bundle is not None else ())
            if evidence.content_ref is not None
            and evidence.content_ref.revision_id in validated_revisions
        )
        challenged_claim_ids = tuple(
            dict.fromkeys(
                claim_id
                for item in reviews
                if item.decision.outcome == "confirmed"
                for claim_id in item.decision.challenged_claim_ids
            )
        )
        return _DesignReworkRequired(
            findings=findings,
            finding_refs=finding_refs,
            additional_evidence=additional_evidence,
            challenged_claim_ids=challenged_claim_ids,
            revision_mode=DesignRevisionMode.EVIDENCE_RECONCILIATION,
        )

    def _review_quarantine_refs(
        self,
        *,
        recommendation_refs: tuple[ArtifactRef, ...],
        baseline_ref: ArtifactRef,
    ) -> tuple[QuarantineReviewBundle, ...]:
        return tuple(
            self.quarantine_review_policy.review(
                recommendation_ref=recommendation_ref,
                baseline_ref=baseline_ref,
            )
            for recommendation_ref in recommendation_refs
        )

    @staticmethod
    def _discovery_terminal_status(
        lane: _DiscoveryLane,
    ) -> Literal[
        "admitted",
        "quarantine_recommended",
        "quarantine_dismissed",
        "quarantine_confirmed",
    ]:
        if lane.admission is None or not lane.admission.recommendation_refs:
            return "admitted"
        if any(item.finding_ref is not None for item in lane.quarantine_reviews):
            return "quarantine_confirmed"
        if len(lane.quarantine_reviews) == len(lane.admission.recommendation_refs):
            return "quarantine_dismissed"
        return "quarantine_recommended"

    def _persist_discovery_progress_state(
        self,
        *,
        run: _RunState,
        lane: _DiscoveryLane,
        status: Literal[
            "inbox_staged",
            "admitting",
            "admitted",
            "quarantine_recommended",
            "quarantine_dismissed",
            "quarantine_confirmed",
        ],
        baseline_ref: ArtifactRef,
    ) -> ArtifactRef:
        if lane.bundle is None or lane.admission is None:
            raise ValueError("Discovery progress requires a staged bundle and Inbox")
        state = DiscoveryLaneState(
            discovery_run_ref=lane.spec_ref,
            status=status,
            reserved_budget=lane.ledger.reserved,
            used_budget=lane.ledger.used,
            baseline_ref=baseline_ref,
            clue_refs=lane.bundle.clue_refs,
            admission_decision_refs=lane.admission.decision_refs,
            recommendation_refs=lane.admission.recommendation_refs,
            quarantine_review_refs=tuple(item.decision_ref for item in lane.quarantine_reviews),
            finding_refs=tuple(
                item.finding_ref for item in lane.quarantine_reviews if item.finding_ref is not None
            ),
            inbox_ref=lane.admission.inbox_ref,
        )
        ref = self._persist_discovery_state(
            spec_ref=lane.spec_ref,
            state=state,
            previous_ref=lane.state_ref,
            extra_dependencies=(
                baseline_ref,
                *lane.bundle.clue_refs,
                *lane.admission.decision_refs,
                *lane.admission.recommendation_refs,
                *(item.decision_ref for item in lane.quarantine_reviews),
                *(
                    item.finding_ref
                    for item in lane.quarantine_reviews
                    if item.finding_ref is not None
                ),
                lane.admission.inbox_ref,
            ),
        )
        run.remember(
            ref,
            lane.admission.inbox_ref,
            *lane.admission.decision_refs,
            *(item.decision_ref for item in lane.quarantine_reviews),
        )
        return ref

    def _fail_discovery_lane(
        self,
        run: _RunState,
        lane: _DiscoveryLane,
        exc: BaseException,
        *,
        stage: str = "discovery",
    ) -> None:
        try:
            if lane.bundle is None and not lane.discovery_accounted:
                if isinstance(exc, DesignerError):
                    if (
                        exc.budget_observed_actual is not None
                        and exc.budget_unknown_upper_bound is not None
                    ):
                        lane.ledger.consume_uncertain(
                            observed_actual=self._add_usage(
                                exc.budget_observed_actual,
                                exc.research_usage,
                            ),
                            unknown_upper_bound=exc.budget_unknown_upper_bound,
                        )
                    else:
                        invocation_usage = (
                            exc.budget_usage
                            if exc.budget_usage is not None
                            else self._budget_as_usage(lane.invocation_budget)
                        )
                        lane.ledger.consume(self._add_usage(invocation_usage, exc.research_usage))
                else:
                    lane.ledger.consume(self._budget_as_usage(lane.invocation_budget))
                lane.discovery_accounted = True
            elif lane.admission_task is not None and not lane.admission_accounted:
                if (
                    isinstance(exc, DesignerError)
                    and exc.budget_observed_actual is not None
                    and exc.budget_unknown_upper_bound is not None
                ):
                    lane.ledger.consume_uncertain(
                        observed_actual=exc.budget_observed_actual,
                        unknown_upper_bound=exc.budget_unknown_upper_bound,
                    )
                else:
                    usage = (
                        exc.budget_usage
                        if isinstance(exc, DesignerError) and exc.budget_usage is not None
                        else self._budget_as_usage(lane.admission_budget)
                    )
                    lane.ledger.consume(usage)
                lane.admission_accounted = True
        except BudgetExceeded:
            pass
        lane.closed = True
        failure_code = self._exception_code(stage, exc)
        failed = DiscoveryLaneState(
            discovery_run_ref=lane.spec_ref,
            status="failed",
            reserved_budget=lane.ledger.reserved,
            used_budget=lane.ledger.used,
            clue_refs=lane.bundle.clue_refs if lane.bundle else (),
            admission_decision_refs=lane.admission.decision_refs if lane.admission else (),
            inbox_ref=lane.admission.inbox_ref if lane.admission else None,
            failure_code=failure_code,
        )
        lane.state_ref = self._persist_discovery_state(
            spec_ref=lane.spec_ref,
            state=failed,
            previous_ref=lane.state_ref,
            extra_dependencies=(
                *(lane.bundle.clue_refs if lane.bundle else ()),
                *(lane.admission.decision_refs if lane.admission else ()),
                *((lane.admission.inbox_ref,) if lane.admission else ()),
            ),
        )
        run.remember(lane.state_ref)
        self._finish_discovery_attempt(
            run,
            status="failed",
            output_refs=(lane.state_ref,),
            failure_code=failure_code,
            usage=lane.ledger.used,
        )
        self.artifacts.record_event(
            event_type="discovery_failed",
            subject_ref=lane.state_ref,
            related_refs=(lane.spec_ref,),
            reason_code=failure_code,
        )

    @staticmethod
    def _consume_optional_task_result(task: asyncio.Task[object]) -> None:
        """Consume a detached optional task exception without awaiting cancellation."""

        try:
            task.exception()
        except asyncio.CancelledError:
            return

    async def _run_direct_design_revision(
        self,
        *,
        run: _RunState,
        job: EnvironmentJob,
        job_ref: ArtifactRef,
        request: EnvironmentRequest,
        request_ref: ArtifactRef,
        previous: DesignBundle,
        correction: _DesignReworkRequired,
    ) -> DesignBundle:
        """Route a design Finding upstream and invalidate every dependent node."""

        router = RepairRouter(
            maximum_attempts=job.budget.repair_attempts,
            artifact_store=self.artifacts,
        )
        if correction.directive_refs:
            routes = tuple(
                self.artifacts.get_json(ref, RepairDirective) for ref in correction.directive_refs
            )
            for route, directive_ref in zip(routes, correction.directive_refs, strict=True):
                self.artifacts.require_exact_json(
                    directive_ref,
                    route,
                    artifact_types=("control.repair_directive",),
                )
            covered_refs = tuple(
                ref for route in routes for ref in (route.finding_ref, *route.related_finding_refs)
            )
            if len(set(covered_refs)) != len(covered_refs) or set(covered_refs) != set(
                correction.finding_refs
            ):
                raise ValueError(
                    "persisted design RepairActions do not cover the exact Finding set"
                )
            directive_refs = correction.directive_refs
        else:
            routes = router.route_many(
                tuple(
                    zip(
                        correction.findings,
                        correction.finding_refs,
                        strict=True,
                    )
                ),
                current_node="design",
                ledger=run.repair_ledger,
            )
            ledger_refs = self._persist_repair_ledger_entries(run, routes)
            directive_refs = tuple(
                self.artifacts.put_json(
                    artifact_id=(
                        f"{run.run_id}:design-repair-directive:"
                        f"{previous.design.revision + 1}:{index}"
                    ),
                    artifact_type="control.repair_directive",
                    value=route,
                    dependencies=(
                        route.finding_ref,
                        *route.related_finding_refs,
                        previous.design_ref,
                        ledger_refs[index],
                    ),
                )
                for index, route in enumerate(routes)
            )
        if any(route.owner_node != "design" or route.action != "new_revision" for route in routes):
            raise ValueError("design revision received a non-design RepairDirective")
        run.remember(*directive_refs)
        run.remember_findings(*correction.finding_refs)
        routes_completed = False

        def complete_design_routes(
            blocking_claim_ids_after: tuple[str, ...],
            *,
            retained_refs: tuple[ArtifactRef, ...],
            usage: BudgetUsage,
            invalidated_refs: tuple[ArtifactRef, ...] = (),
        ) -> None:
            nonlocal routes_completed
            if routes_completed:
                return
            for route in routes:
                if route.ledger_entry_id is None:
                    raise ValueError("design repair directive lacks ledger entry")
                run.repair_ledger.complete(
                    route.ledger_entry_id,
                    blocking_claim_ids_after=blocking_claim_ids_after,
                    invalidated_refs=invalidated_refs,
                    retained_refs=retained_refs,
                    session_strategy="continued",
                    usage=usage,
                )
            self._persist_repair_ledger_entries(run, routes)
            routes_completed = True

        required_design_turns = 2 if correction.additional_evidence else 1
        required_downstream_turns = 1 + self.verifier_compiler.maximum_invocation_turns(
            len(previous.design.curriculum.task_types)
        )
        remaining = run.ledger.remaining
        if (
            remaining.repair_attempts < 1
            or remaining.agent_turns < required_design_turns + required_downstream_turns
        ):
            self._terminate_repair_routes(
                run,
                routes,
                outcome="exhausted",
                retained_refs=(previous.design_ref,),
            )
            await self._persist_snapshot(run, status="running")
            raise _GenerationHalt(
                status="budget_exhausted",
                code="design_rework_budget_exhausted",
                summary=(
                    "A design revision is required, but the remaining vector budget cannot "
                    "cover evidence/design repair and a fresh Verifier/Builder branch."
                ),
                finding_refs=correction.finding_refs,
            )
        available_after_action = BudgetLedger(
            run.ledger.remaining,
            BudgetUsage(repair_attempts=1),
        ).remaining
        try:
            work = self._reserve_designer_work(
                run,
                purpose=f"direct-design-revision-{previous.design.revision + 1}",
                base_turns=required_design_turns,
                maximum_corrections=(
                    required_design_turns * self.designer.maximum_structured_reworks
                ),
                available=available_after_action,
                controller_owns_structured_repairs=True,
            )
        except (_GenerationHalt, BudgetExceeded) as exc:
            self._terminate_repair_routes(
                run,
                routes,
                outcome="exhausted",
                retained_refs=(previous.design_ref,),
            )
            await self._persist_snapshot(run, status="running")
            if isinstance(exc, _GenerationHalt):
                raise
            raise _GenerationHalt(
                status="budget_exhausted",
                code="design_rework_reservation_exhausted",
                summary="Design rework could not reserve its Agent budget.",
                finding_refs=correction.finding_refs,
            ) from exc
        run.ledger.consume(BudgetUsage(repair_attempts=1))
        attempt_id = self._start_attempt(
            run,
            "design",
            (
                previous.design_ref,
                *correction.finding_refs,
                *directive_refs,
                work.lease_ref,
            ),
        )
        self.artifacts.record_event(
            event_type="design_rework_started",
            subject_ref=previous.design_ref,
            related_refs=(*correction.finding_refs, *directive_refs),
            details=(KeyValue(key="next_revision", value=previous.design.revision + 1),),
        )
        await self._persist_snapshot(run, status="running")
        work_settled = False
        settled_invocation_usage = BudgetUsage()
        try:
            bundle = await self.designer.revise(
                job=job,
                job_ref=job_ref,
                request=request,
                request_ref=request_ref,
                previous=previous,
                findings=correction.findings,
                finding_refs=correction.finding_refs,
                workspace=self._workspace_for(
                    run.run_id,
                    f"design-revision-{previous.design.revision + 1}",
                ),
                additional_evidence=correction.additional_evidence,
                challenged_claim_ids=correction.challenged_claim_ids,
                revision_mode=correction.revision_mode,
                invocation_budget=work.lease.reserved,
                repair_authority=self._structured_repair_authority(run),
            )
            invocation_usage = bundle.invocation_usage
            invocation_actual, invocation_unknown = self._designer_bundle_settlement(bundle)
            self._settle_designer_work(
                run,
                work,
                invocation_actual,
                unknown_upper_bound=invocation_unknown,
            )
            work_settled = True
            settled_invocation_usage = invocation_usage
            modeling_gate_ref, policy_failures = self._modeling_gate(
                job=job,
                request=request,
                design=bundle,
            )
            run.remember(modeling_gate_ref)
            total_usage = self._add_usage(
                BudgetUsage(repair_attempts=1),
                invocation_usage,
            )
            if policy_failures:
                finding_ref = self._control_failure_finding(
                    run,
                    node="design",
                    event_kind=ControlEventKind.CONTRACT_FAILURE,
                    code="revised_modeling_gate_failed",
                    error_type="ModelingGateRejected",
                    subject_ref=bundle.design_ref,
                    causal_refs=(modeling_gate_ref,),
                    repair_context=policy_failures,
                )
                self._finish_attempt(
                    run,
                    attempt_id,
                    status="failed",
                    output_refs=(modeling_gate_ref,),
                    finding_refs=(finding_ref,),
                    failure_code="revised_modeling_gate_failed",
                    failure_summary=(
                        "Framework Modeling Gate rejected the design revision: "
                        + ", ".join(policy_failures)
                    ),
                    usage=total_usage,
                )
                finding = self.artifacts.get_json(finding_ref, Finding)
                complete_design_routes(
                    (finding.fingerprint,),
                    retained_refs=(bundle.design_ref,),
                    usage=total_usage,
                )
                await self._persist_snapshot(run, status="running")
                if tuple(policy_failures) == ("unresolved_assumptions_forbidden",) and frozenset(
                    self._modeling_unresolved(request, bundle)
                ) == frozenset(self._modeling_unresolved(request, previous)):
                    raise _GenerationHalt(
                        status="failed",
                        code="design_rework_no_progress",
                        summary=(
                            "The directed design revision did not reduce the release-blocking "
                            "uncertainty set; further automatic retries are forbidden."
                        ),
                        finding_refs=(finding_ref,),
                    )
                return await self._run_direct_design_revision(
                    run=run,
                    job=job,
                    job_ref=job_ref,
                    request=request,
                    request_ref=request_ref,
                    previous=bundle,
                    correction=_DesignReworkRequired(
                        findings=(finding,),
                        finding_refs=(finding_ref,),
                        revision_mode=self._design_revision_mode_for_finding(finding),
                    ),
                )
            outputs = (
                bundle.evidence_graph_ref,
                bundle.coverage_map_ref,
                bundle.world_spec_ref,
                bundle.design_ref,
                bundle.baseline_ref,
                modeling_gate_ref,
            )
            run.remember(*outputs)
            invalidated_refs = self._invalidate_artifact_descendants(
                run,
                superseded_refs=(previous.design_ref,),
                invalidating_refs=(*directive_refs, bundle.design_ref),
            )
            complete_design_routes(
                (),
                retained_refs=(bundle.design_ref,),
                usage=total_usage,
                invalidated_refs=invalidated_refs,
            )
            self._finish_attempt(
                run,
                attempt_id,
                status="passed",
                output_refs=outputs,
                usage=total_usage,
                profile_hash=self._last_profile_hash(bundle.invocation_results),
                session_id=self._last_session_id(bundle.invocation_results),
            )
            await self._persist_snapshot(run, status="running")
            return bundle
        except _GenerationHalt:
            raise
        except BudgetExceeded as exc:
            failure_usage = (
                settled_invocation_usage
                if work_settled
                else self._settle_failed_designer_work(run, work, exc)
            )
            self._terminate_repair_routes(
                run,
                routes,
                outcome="exhausted",
                retained_refs=(previous.design_ref,),
                usage=self._add_usage(BudgetUsage(repair_attempts=1), failure_usage),
            )
            self._finish_attempt(
                run,
                attempt_id,
                status="budget_exhausted",
                finding_refs=correction.finding_refs,
                failure_code="design_rework_budget_exhausted",
                failure_summary="Design revision completed outside its vector budget.",
                usage=self._add_usage(BudgetUsage(repair_attempts=1), failure_usage),
            )
            raise _GenerationHalt(
                status="budget_exhausted",
                code="design_rework_budget_exhausted",
                summary=f"Design rework exhausted: {', '.join(exc.dimensions)}.",
                finding_refs=correction.finding_refs,
            ) from exc
        except DesignerError as exc:
            failure_usage = self._settle_designer_error(
                run,
                work,
                exc,
                settled_invocation_usage if work_settled else None,
            )
            status, code = self._designer_failure_status(
                exc,
                default_code=f"design_rework_{self._safe_identifier(exc.stage)}",
            )
            self._finish_attempt(
                run,
                attempt_id,
                status=status,
                finding_refs=correction.finding_refs,
                failure_code=code,
                failure_summary="Environment Designer did not commit a valid new revision.",
                usage=self._add_usage(BudgetUsage(repair_attempts=1), failure_usage),
                profile_hash=self._last_profile_hash(exc.results),
                session_id=self._last_session_id(exc.results),
            )
            self._terminate_repair_routes(
                run,
                routes,
                outcome=("exhausted" if status == "budget_exhausted" else "escalated"),
                retained_refs=(previous.design_ref,),
                usage=self._add_usage(BudgetUsage(repair_attempts=1), failure_usage),
            )
            raise _GenerationHalt(
                status=self._generate_status(status),
                code=code,
                summary="Environment Designer failed during targeted upstream rework.",
                finding_refs=correction.finding_refs,
            ) from exc
        except Exception as exc:
            failure_usage = (
                settled_invocation_usage
                if work_settled
                else self._settle_failed_designer_work(run, work, exc)
            )
            self._finish_attempt(
                run,
                attempt_id,
                status="failed",
                finding_refs=correction.finding_refs,
                failure_code="designer_rework_infrastructure_error",
                failure_summary="Design rework failed outside the Agent invocation protocol.",
                usage=self._add_usage(BudgetUsage(repair_attempts=1), failure_usage),
            )
            self._terminate_repair_routes(
                run,
                routes,
                outcome="escalated",
                retained_refs=(previous.design_ref,),
                usage=self._add_usage(BudgetUsage(repair_attempts=1), failure_usage),
            )
            raise _GenerationHalt(
                status="failed",
                code="designer_rework_infrastructure_error",
                summary="Environment Designer rework infrastructure failed closed.",
                finding_refs=correction.finding_refs,
            ) from exc

    def _modeling_gate(
        self,
        *,
        job: EnvironmentJob,
        request: EnvironmentRequest,
        design: ExecutableDesignBundle,
    ) -> tuple[ArtifactRef, tuple[str, ...]]:
        """Apply framework-owned release policy to an Agent-authored design."""

        failures: list[str] = []
        profile = job.release_profile
        if _RISK_ORDER[request.risk_level] > _RISK_ORDER[profile.maximum_risk]:
            failures.append("request_risk_exceeds_release_profile")

        coverage = {item.dimension: item for item in design.coverage_map.dimensions}
        for dimension in profile.minimum_coverage_dimensions:
            item = coverage.get(dimension)
            if item is None:
                failures.append(f"missing_coverage:{dimension}")
            elif item.evidence_discovered == "absent" or item.world_modelled == "absent":
                failures.append(f"unmodelled_coverage:{dimension}")

        unresolved = self._modeling_unresolved(request, design)
        if unresolved and not profile.allow_unresolved_assumptions:
            failures.append("unresolved_assumptions_forbidden")
        if not any(
            claim.kind == "observed" and claim.status == "supported" and claim.evidence_ids
            for claim in design.evidence_graph.claims
        ):
            failures.append("no_supported_observed_claim")

        status: Literal["pass", "fail"] = "fail" if failures else "pass"
        gate = GateResult(
            gate_id="modeling",
            status=status,
            hard=True,
            subject_ref=design.design_ref,
            evidence_refs=(
                design.evidence_graph_ref,
                design.coverage_map_ref,
                design.world_spec_ref,
            ),
            observed_metrics={
                "coverage_dimensions": float(len(design.coverage_map.dimensions)),
                "supported_observed_claims": float(
                    sum(
                        claim.kind == "observed" and claim.status == "supported"
                        for claim in design.evidence_graph.claims
                    )
                ),
                "unresolved_items": float(len(unresolved)),
            },
            duration_seconds=0.0,
            summary=(
                "Framework Modeling Gate rejected policy conditions: " + ", ".join(failures)
                if failures
                else "Framework Modeling Gate validated evidence, coverage, risk and unknowns."
            ),
        )
        gate_ref = self.artifacts.put_json(
            artifact_id=self._stable_id(
                "modeling-gate",
                design.design_ref.revision_id,
                profile.content_digest(),
            ),
            artifact_type="control.modeling_gate",
            value=gate,
            dependencies=(
                design.design_ref,
                design.evidence_graph_ref,
                design.coverage_map_ref,
                design.world_spec_ref,
            ),
        )
        return gate_ref, tuple(failures)

    def _record_feedback_result(
        self,
        *,
        contract_id: str,
        status: Literal["passed", "failed", "inconclusive", "error", "not_run"],
        subject_ref: ArtifactRef | None,
        evidence_refs: tuple[ArtifactRef, ...],
        summary: str,
        target: RepairTargetRef | None = None,
        diagnostic_ref: ArtifactRef | None = None,
        usage: BudgetUsage | None = None,
    ) -> ArtifactRef:
        """Persist a dynamic feedback fact after catalog and target validation."""

        contract = PRODUCTION_FEEDBACK.require(contract_id)
        identity_ref = subject_ref or diagnostic_ref or evidence_refs[0]
        result = FeedbackResult(
            result_id=self._stable_id(
                "feedback-result",
                contract_id,
                identity_ref.revision_id,
                status,
            ),
            contract_id=contract.contract_id,
            claim_id=contract.claim_id,
            target=target,
            status=status,
            subject_ref=subject_ref,
            evidence_refs=self._unique_refs(evidence_refs),
            diagnostic_ref=diagnostic_ref,
            usage=usage or BudgetUsage(),
            evaluated_at=datetime.now(UTC),
            summary=summary,
        )
        PRODUCTION_FEEDBACK.validate_result(result)
        result_ref = self.artifacts.put_json(
            artifact_id=result.result_id,
            artifact_type="control.feedback_result",
            value=result,
            dependencies=self._unique_refs(
                (
                    *((subject_ref,) if subject_ref is not None else ()),
                    *evidence_refs,
                    *((diagnostic_ref,) if diagnostic_ref is not None else ()),
                    *(target.immutable_input_refs if target is not None else ()),
                )
            ),
        )
        return result_ref

    @staticmethod
    def _modeling_unresolved(
        request: EnvironmentRequest,
        design: ExecutableDesignBundle,
    ) -> tuple[str, ...]:
        """Return the exact deduplicated uncertainty set inspected by the gate."""

        return tuple(
            dict.fromkeys(
                (
                    *request.unknowns_requiring_human,
                    *design.evidence_graph.unresolved_questions,
                    *design.design.unresolved_questions,
                    *design.world_spec.unknowns,
                    *(
                        unknown
                        for dimension in design.coverage_map.dimensions
                        for unknown in dimension.unknowns
                    ),
                )
            )
        )

    async def _compile_and_build(
        self,
        run: _RunState,
        job: EnvironmentJob,
        design: ExecutableDesignBundle,
        *,
        parent_workspace_refs: Sequence[ArtifactRef] = (),
        recovered_build: BuildBundle | None = None,
    ) -> tuple[CompiledVerifier, BuildBundle]:
        """Execute the compile branch under a cancellation-safe task scope."""

        try:
            return await self._compile_and_build_inner(
                run,
                job,
                design,
                parent_workspace_refs=parent_workspace_refs,
                recovered_build=recovered_build,
            )
        finally:
            cleanup = run.compile_cleanup
            if cleanup is not None:
                await cleanup()
                run.compile_cleanup = None

    async def _compile_and_build_inner(
        self,
        run: _RunState,
        job: EnvironmentJob,
        design: ExecutableDesignBundle,
        *,
        parent_workspace_refs: Sequence[ArtifactRef] = (),
        recovered_build: BuildBundle | None = None,
    ) -> tuple[CompiledVerifier, BuildBundle]:
        if recovered_build is not None:
            _, recovered_build = await self._integrate_and_repair(
                run=run,
                job=job,
                design=design,
                build=recovered_build,
            )
            return await self._compile_with_recovered_build(
                run=run,
                job=job,
                design=design,
                build=recovered_build,
            )
        verifier_base_turns = self.verifier_compiler.minimum_invocation_turns(
            len(design.design.curriculum.task_types)
        )
        verifier_budget, builder_budget = self._compile_branch_budgets(
            run.ledger.remaining,
            verifier_base_turns=verifier_base_turns,
        )
        required_branch_turns = verifier_budget.agent_turns + builder_budget.agent_turns
        if run.ledger.remaining.agent_turns < required_branch_turns:
            raise _GenerationHalt(
                status="budget_exhausted",
                code="compile_branch_turn_budget_exhausted",
                summary=(
                    "Verifier corrections and Builder require "
                    f"{required_branch_turns} reserved Agent turns."
                ),
            )
        verifier_attempt = self._start_attempt(
            run,
            "verifier",
            (design.design_ref, design.world_spec_ref),
        )
        build_attempt = self._start_attempt(run, "build", (design.design_ref,))
        branch_ledger = LeaseBudgetLedger(run.ledger.remaining)
        verifier_lease = branch_ledger.reserve(
            lease_id=self._stable_id("budget-lease", verifier_attempt),
            owner_id=verifier_attempt,
            requested=verifier_budget,
            elapsed_wall_seconds=0.0,
        )
        builder_lease = branch_ledger.reserve(
            lease_id=self._stable_id("budget-lease", build_attempt),
            owner_id=build_attempt,
            requested=builder_budget,
            elapsed_wall_seconds=0.0,
        )
        verifier_lease_ref = self._persist_budget_lease(run, verifier_lease)
        builder_lease_ref = self._persist_budget_lease(run, builder_lease)
        run.remember(verifier_lease_ref, builder_lease_ref)
        await self._persist_snapshot(run, status="running")
        # A single local-auth SDK slot must stay with Builder until its bounded
        # pre-commit loop is closed.  Starting Verifier shards immediately would
        # put all of them ahead of a same-session Builder correction in the FIFO
        # backend queue.  Multi-slot providers retain the independent concurrency.
        builder_task = asyncio.create_task(
            self.builder.build(
                design=design.design,
                design_ref=design.design_ref,
                workspace=self._workspace_for(run.run_id, "builder"),
                budget=builder_budget,
                permissions=job.permissions,
                parent_workspace_refs=parent_workspace_refs,
                repair_authority=self._structured_repair_authority(run),
                run_id=run.run_id,
                attempt_id=build_attempt,
            ),
            name=f"{run.run_id}-builder",
        )
        verifier_task: asyncio.Task[CompiledVerifier] | None = None
        if self.config.agent.max_concurrent_invocations > 1:
            verifier_task = asyncio.create_task(
                self.verifier_compiler.compile(
                    design=design.design,
                    design_ref=design.design_ref,
                    world_spec_ref=design.world_spec_ref,
                    workspace=self._workspace_for(run.run_id, "verifier"),
                    lineage_id=f"{run.run_id}.verifier",
                    budget=verifier_budget,
                    permissions=job.permissions,
                    repair_authority=self._structured_repair_authority(run),
                ),
                name=f"{run.run_id}-verifier",
            )

        cleanup_done = False
        integration_task: asyncio.Task[tuple[IntegrationBundle, BuildBundle]] | None = None
        branch_global_charged = {
            builder_lease.lease_id: False,
            verifier_lease.lease_id: False,
        }
        branch_terminal_leases: dict[str, BudgetLease] = {}
        branch_terminal_refs: dict[str, ArtifactRef] = {}
        compiled: CompiledVerifier | None = None
        build: BuildBundle | None = None
        integration_error: BaseException | None = None
        halts: list[_GenerationHalt] = []

        async def settle_branch(
            *,
            lease: BudgetLease,
            lease_ref: ArtifactRef,
            actual: BudgetUsage,
            unknown: BudgetUsage,
        ) -> tuple[BudgetLease, BudgetUsage]:
            terminal = branch_terminal_leases.get(lease.lease_id)
            if terminal is None:
                current = next(
                    item for item in branch_ledger.leases if item.lease_id == lease.lease_id
                )
                terminal = (
                    branch_ledger.settle(
                        lease.lease_id,
                        actual,
                        unknown_upper_bound=unknown,
                    )
                    if current.status == "active"
                    else current
                )
                branch_terminal_leases[lease.lease_id] = terminal
            terminal_ref = branch_terminal_refs.get(lease.lease_id)
            if terminal_ref is None:
                terminal_ref = self._persist_budget_lease(
                    run,
                    terminal,
                    previous_ref=lease_ref,
                )
                branch_terminal_refs[lease.lease_id] = terminal_ref
            run.remember(terminal_ref)
            usage = terminal.conservative_committed
            if not branch_global_charged[lease.lease_id]:
                if terminal.status == "settled":
                    run.ledger.consume_uncertain(
                        observed_actual=terminal.observed_actual,
                        unknown_upper_bound=terminal.unknown_upper_bound,
                    )
                branch_global_charged[lease.lease_id] = True
            return terminal, usage

        async def release_branch(
            *,
            lease: BudgetLease,
            lease_ref: ArtifactRef,
        ) -> BudgetLease:
            terminal = branch_terminal_leases.get(lease.lease_id)
            if terminal is None:
                current = next(
                    item for item in branch_ledger.leases if item.lease_id == lease.lease_id
                )
                terminal = (
                    branch_ledger.release(lease.lease_id) if current.status == "active" else current
                )
                branch_terminal_leases[lease.lease_id] = terminal
            terminal_ref = branch_terminal_refs.get(lease.lease_id)
            if terminal_ref is None:
                terminal_ref = self._persist_budget_lease(
                    run,
                    terminal,
                    previous_ref=lease_ref,
                )
                branch_terminal_refs[lease.lease_id] = terminal_ref
            run.remember(terminal_ref)
            if terminal.status == "released":
                branch_global_charged[lease.lease_id] = True
            return terminal

        async def terminalize_verifier(result: CompiledVerifier | BaseException) -> None:
            nonlocal compiled
            attempt = next(item for item in run.attempts if item.attempt_id == verifier_attempt)
            if attempt.status not in {"pending", "running"}:
                return
            actual, unknown = self._verifier_result_settlement(
                result,
                budget=verifier_budget,
                base_turns=verifier_base_turns,
            )
            _terminal, usage = await settle_branch(
                lease=verifier_lease,
                lease_ref=verifier_lease_ref,
                actual=actual,
                unknown=unknown,
            )
            if isinstance(result, BaseException):
                code, status = self._verifier_error(result)
                finding_ref = self._control_failure_finding(
                    run,
                    node="verifier",
                    event_kind=(
                        ControlEventKind.PERMISSION_REQUIRED
                        if status == "needs_human"
                        else ControlEventKind.COMPONENT_FAILURE
                    ),
                    code=code,
                    error_type=type(result).__name__,
                )
                self._finish_attempt(
                    run,
                    verifier_attempt,
                    status=status,
                    finding_refs=(finding_ref,),
                    failure_code=code,
                    failure_summary="Independent verifier compilation failed.",
                    usage=usage,
                )
                halts.append(
                    _GenerationHalt(
                        status=self._generate_status(status),
                        code=code,
                        summary="Independent Challenger did not produce valid Verifier IR.",
                        finding_refs=(finding_ref,),
                    )
                )
            else:
                compiled = result
                run.remember(result.verifier_ref, *result.checkpoint_refs)
                feedback_ref = self._record_feedback_result(
                    contract_id="feedback.verifier.intent",
                    status="passed",
                    subject_ref=result.verifier_ref,
                    evidence_refs=tuple(result.checkpoint_refs) or (result.verifier_ref,),
                    target=RepairTargetRef(
                        target_id=self._stable_id(
                            "feedback-target",
                            "feedback.verifier.intent",
                            result.verifier_ref.revision_id,
                        ),
                        component="verifier",
                        artifact_slot="verifier_intent_batch",
                        lineage_id=f"{run.run_id}.verifier",
                        immutable_input_refs=(design.design_ref, design.world_spec_ref),
                        committed_subject_ref=result.verifier_ref,
                        allowed_mutation_paths=("/",),
                    ),
                    summary="Independent verifier intent compiled to closed framework IR.",
                    usage=usage,
                )
                run.remember(feedback_ref)
                self._finish_attempt(
                    run,
                    verifier_attempt,
                    status="passed",
                    output_refs=(*result.checkpoint_refs, result.verifier_ref),
                    usage=usage,
                    profile_hash=self._last_profile_hash(result.invocation_results),
                    session_id=self._last_session_id(result.invocation_results),
                )
            await self._persist_snapshot(run, status="running")

        async def terminalize_builder(result: BuildBundle | BaseException) -> None:
            nonlocal build
            attempt = next(item for item in run.attempts if item.attempt_id == build_attempt)
            if attempt.status not in {"pending", "running"}:
                return
            actual, unknown = self._builder_result_settlement(
                result,
                budget=builder_budget,
            )
            _terminal, usage = await settle_branch(
                lease=builder_lease,
                lease_ref=builder_lease_ref,
                actual=actual,
                unknown=unknown,
            )
            if isinstance(result, BaseException):
                code, status, state = self._builder_error(result)
                finding_ref = self._control_failure_finding(
                    run,
                    node="build",
                    event_kind=(
                        ControlEventKind.PERMISSION_REQUIRED
                        if status == "needs_human"
                        else ControlEventKind.COMPONENT_FAILURE
                    ),
                    code=code,
                    error_type=type(result).__name__,
                )
                self._finish_attempt(
                    run,
                    build_attempt,
                    status=status,
                    finding_refs=(finding_ref,),
                    failure_code=code,
                    failure_summary="Environment Builder did not produce a valid candidate.",
                    usage=usage,
                    profile_hash=(f"sha256:{state.profile.profile_hash}" if state else None),
                    session_id=(
                        self._hashed_session(state.invocation_session.thread_id)
                        if state and state.invocation_session
                        else None
                    ),
                )
                halts.append(
                    _GenerationHalt(
                        status=self._generate_status(status),
                        code=code,
                        summary="Environment Builder stopped without a valid candidate.",
                        finding_refs=(finding_ref,),
                    )
                )
            else:
                build = result
                outputs = (
                    result.implementation_contract_ref,
                    result.source_snapshot_ref,
                    result.implementation_lineage_ref,
                    result.candidate_manifest_ref,
                    result.build_artifact_ref,
                    result.candidate_ref,
                )
                run.remember(*outputs)
                feedback_ref = self._record_feedback_result(
                    contract_id="feedback.build.candidate",
                    status="passed",
                    subject_ref=result.candidate_ref,
                    evidence_refs=outputs[:-1],
                    target=RepairTargetRef(
                        target_id=self._stable_id(
                            "feedback-target",
                            "feedback.build.candidate",
                            result.candidate_ref.revision_id,
                        ),
                        component="build",
                        artifact_slot="candidate_workspace",
                        lineage_id=f"{run.run_id}.builder",
                        immutable_input_refs=(design.design_ref,),
                        committed_subject_ref=result.candidate_ref,
                        allowed_mutation_paths=("/candidate",),
                    ),
                    summary=(
                        "Builder committed one closed candidate and reproducible source snapshot."
                    ),
                    usage=usage,
                )
                run.remember(feedback_ref)
                self._finish_attempt(
                    run,
                    build_attempt,
                    status="passed",
                    output_refs=outputs,
                    usage=usage,
                    profile_hash=(
                        f"sha256:{result.state.profile.profile_hash}"
                        if result.state is not None
                        else None
                    ),
                    session_id=(
                        self._hashed_session(result.session.thread_id)
                        if result.session is not None
                        else None
                    ),
                )
            await self._persist_snapshot(run, status="running")
            if build is not None:
                self.artifacts.record_event(
                    event_type="generation_node_committed",
                    subject_ref=build.candidate_ref,
                    related_refs=(build.source_snapshot_ref, design.design_ref),
                    reason_code="build_passed_before_verifier",
                )

        async def cleanup_compile_children() -> None:
            """Cancel child Agent work and terminally settle every branch lease."""

            nonlocal cleanup_done
            if cleanup_done:
                return
            tasks: tuple[asyncio.Task[object], ...] = tuple(
                cast(asyncio.Task[object], task)
                for task in (builder_task, verifier_task, integration_task)
                if task is not None
            )
            for task in tasks:
                if not task.done():
                    task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

            lease_specs = (
                (
                    builder_lease,
                    builder_lease_ref,
                    builder_task,
                    build_attempt,
                    "build_cancelled",
                ),
                (
                    verifier_lease,
                    verifier_lease_ref,
                    verifier_task,
                    verifier_attempt,
                    "verifier_cancelled",
                ),
            )
            for original, previous_ref, child_task, attempt_id, failure_code in lease_specs:
                attempt = next(item for item in run.attempts if item.attempt_id == attempt_id)
                if child_task is None:
                    terminal_lease = await release_branch(
                        lease=original,
                        lease_ref=previous_ref,
                    )
                    if attempt.status in {"pending", "running"}:
                        self._finish_attempt(
                            run,
                            attempt_id,
                            status="failed",
                            failure_code=failure_code,
                            failure_summary="Compile child was never started.",
                            usage=terminal_lease.conservative_committed,
                        )
                    continue
                if child_task.done() and not child_task.cancelled():
                    try:
                        child_result: object = child_task.result()
                    except BaseException as exc:  # task result is terminal evidence
                        child_result = exc
                    if attempt_id == build_attempt:
                        await terminalize_builder(cast(BuildBundle | BaseException, child_result))
                    else:
                        await terminalize_verifier(
                            cast(CompiledVerifier | BaseException, child_result)
                        )
                    continue
                unknown = self._budget_as_usage(original.reserved).model_copy(
                    update={"wall_seconds": 0.0}
                )
                terminal_lease, usage = await settle_branch(
                    lease=original,
                    lease_ref=previous_ref,
                    actual=BudgetUsage(),
                    unknown=unknown,
                )
                if attempt.status in {"pending", "running"}:
                    self._finish_attempt(
                        run,
                        attempt_id,
                        status="failed",
                        failure_code=failure_code,
                        failure_summary="Compile child was cancelled before commit.",
                        usage=usage,
                    )
            cleanup_done = True

        run.compile_cleanup = cleanup_compile_children
        pending: dict[
            asyncio.Task[object],
            Literal["builder", "verifier", "integration"],
        ] = {cast(asyncio.Task[object], builder_task): "builder"}
        if verifier_task is not None:
            pending[cast(asyncio.Task[object], verifier_task)] = "verifier"

        while pending:
            done, _still_pending = await asyncio.wait(
                tuple(pending),
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in sorted(done, key=lambda item: pending[item]):
                kind = pending.pop(task)
                result = (await asyncio.gather(task, return_exceptions=True))[0]
                if kind == "builder":
                    await terminalize_builder(cast(BuildBundle | BaseException, result))
                    if verifier_task is None:
                        verifier_task = asyncio.create_task(
                            self.verifier_compiler.compile(
                                design=design.design,
                                design_ref=design.design_ref,
                                world_spec_ref=design.world_spec_ref,
                                workspace=self._workspace_for(run.run_id, "verifier"),
                                lineage_id=f"{run.run_id}.verifier",
                                budget=verifier_budget,
                                permissions=job.permissions,
                                repair_authority=self._structured_repair_authority(run),
                            ),
                            name=f"{run.run_id}-verifier",
                        )
                        pending[cast(asyncio.Task[object], verifier_task)] = "verifier"
                    if build is not None:

                        def active_verifier_reservation() -> Budget | None:
                            current = next(
                                item
                                for item in branch_ledger.leases
                                if item.lease_id == verifier_lease.lease_id
                            )
                            return current.reserved if current.status == "active" else None

                        integration_task = asyncio.create_task(
                            self._integrate_and_repair(
                                run=run,
                                job=job,
                                design=design,
                                build=build,
                                sibling_reservation=active_verifier_reservation,
                            ),
                            name=f"{run.run_id}-integration",
                        )
                        pending[cast(asyncio.Task[object], integration_task)] = "integration"
                elif kind == "verifier":
                    await terminalize_verifier(cast(CompiledVerifier | BaseException, result))
                elif isinstance(result, BaseException):
                    integration_error = result
                else:
                    _integration, build = cast(
                        tuple[IntegrationBundle, BuildBundle],
                        result,
                    )

        await self._persist_snapshot(run, status="running")
        if integration_error is not None:
            if isinstance(integration_error, _GenerationHalt):
                raise _GenerationHalt(
                    status=integration_error.status,
                    code=integration_error.code,
                    summary=" ".join(
                        (integration_error.summary, *(halt.summary for halt in halts))
                    ),
                    finding_refs=(
                        *integration_error.finding_refs,
                        *(ref for halt in halts for ref in halt.finding_refs),
                    ),
                ) from integration_error
            raise integration_error
        if halts:
            findings = tuple(ref for halt in halts for ref in halt.finding_refs)
            primary = next(
                (halt for halt in halts if halt.status == "needs_human"),
                halts[0],
            )
            raise _GenerationHalt(
                status=primary.status,
                code=primary.code,
                summary=" ".join(halt.summary for halt in halts),
                finding_refs=findings,
            )
        assert compiled is not None and build is not None
        return compiled, build

    async def _compile_with_recovered_build(
        self,
        *,
        run: _RunState,
        job: EnvironmentJob,
        design: ExecutableDesignBundle,
        build: BuildBundle,
    ) -> tuple[CompiledVerifier, BuildBundle]:
        """Compile only the invalidated Verifier branch around an exact Build."""

        build_outputs = (
            build.implementation_contract_ref,
            build.source_snapshot_ref,
            build.implementation_lineage_ref,
            build.candidate_manifest_ref,
            build.build_artifact_ref,
            build.candidate_ref,
        )
        build_attempt = self._start_attempt(
            run,
            "build",
            (design.design_ref, build.source_snapshot_ref),
        )
        run.remember(*build_outputs)
        self._finish_attempt(
            run,
            build_attempt,
            status="passed",
            output_refs=build_outputs,
            usage=BudgetUsage(),
        )
        await self._persist_snapshot(run, status="running")
        self.artifacts.record_event(
            event_type="generation_checkpoint_adopted",
            subject_ref=build.candidate_ref,
            related_refs=(design.design_ref, build.source_snapshot_ref),
            reason_code="exact_build_checkpoint",
        )

        base_turns = self.verifier_compiler.minimum_invocation_turns(
            len(design.design.curriculum.task_types)
        )
        verifier_budget = self._verifier_only_budget(
            run.ledger.remaining,
            verifier_base_turns=base_turns,
        )
        verifier_attempt = self._start_attempt(
            run,
            "verifier",
            (design.design_ref, design.world_spec_ref, build.candidate_ref),
        )
        ledger = LeaseBudgetLedger(run.ledger.remaining)
        lease = ledger.reserve(
            lease_id=self._stable_id("budget-lease", verifier_attempt),
            owner_id=verifier_attempt,
            requested=verifier_budget,
            elapsed_wall_seconds=0.0,
        )
        lease_ref = self._persist_budget_lease(run, lease)
        run.remember(lease_ref)
        await self._persist_snapshot(run, status="running")
        results = await asyncio.gather(
            self.verifier_compiler.compile(
                design=design.design,
                design_ref=design.design_ref,
                world_spec_ref=design.world_spec_ref,
                workspace=self._workspace_for(run.run_id, "verifier"),
                lineage_id=f"{run.run_id}.verifier",
                budget=verifier_budget,
                permissions=job.permissions,
                repair_authority=self._structured_repair_authority(run),
            ),
            return_exceptions=True,
        )
        result = results[0]
        verifier_actual, verifier_unknown = self._verifier_result_settlement(
            result,
            budget=verifier_budget,
            base_turns=base_turns,
        )
        usage = self._add_usage(verifier_actual, verifier_unknown)
        settled = ledger.settle(
            lease.lease_id,
            verifier_actual,
            unknown_upper_bound=verifier_unknown,
        )
        run.remember(self._persist_budget_lease(run, settled, previous_ref=lease_ref))
        try:
            run.ledger.consume_uncertain(
                observed_actual=verifier_actual,
                unknown_upper_bound=verifier_unknown,
            )
        except BudgetExceeded as exc:
            self._finish_attempt(
                run,
                verifier_attempt,
                status="budget_exhausted",
                failure_code="verifier_recovery_budget_exhausted",
                failure_summary="Recovered Build verifier compilation exceeded its lease.",
                usage=usage,
            )
            await self._persist_snapshot(run, status="running")
            raise _GenerationHalt(
                status="budget_exhausted",
                code="verifier_recovery_budget_exhausted",
                summary=(
                    "Verifier compilation exhausted budget dimensions: "
                    f"{', '.join(exc.dimensions)}."
                ),
            ) from exc
        if isinstance(result, BaseException):
            code, status = self._verifier_error(result)
            finding_ref = self._control_failure_finding(
                run,
                node="verifier",
                event_kind=(
                    ControlEventKind.PERMISSION_REQUIRED
                    if status == "needs_human"
                    else ControlEventKind.COMPONENT_FAILURE
                ),
                code=code,
                error_type=type(result).__name__,
            )
            self._finish_attempt(
                run,
                verifier_attempt,
                status=status,
                finding_refs=(finding_ref,),
                failure_code=code,
                failure_summary="Independent verifier compilation failed.",
                usage=usage,
            )
            await self._persist_snapshot(run, status="running")
            raise _GenerationHalt(
                status=self._generate_status(status),
                code=code,
                summary="Independent Challenger did not produce valid Verifier IR.",
                finding_refs=(finding_ref,),
            )
        compiled = result
        run.remember(compiled.verifier_ref, *compiled.checkpoint_refs)
        self._finish_attempt(
            run,
            verifier_attempt,
            status="passed",
            output_refs=(*compiled.checkpoint_refs, compiled.verifier_ref),
            usage=usage,
            profile_hash=self._last_profile_hash(compiled.invocation_results),
            session_id=self._last_session_id(compiled.invocation_results),
        )
        await self._persist_snapshot(run, status="running")
        return compiled, build

    async def _integrate_and_repair(
        self,
        *,
        run: _RunState,
        job: EnvironmentJob,
        design: ExecutableDesignBundle,
        build: BuildBundle,
        sibling_reservation: Callable[[], Budget | None] | None = None,
    ) -> tuple[IntegrationBundle, BuildBundle]:
        """Run early execution without spending an active sibling's reservation."""

        router = RepairRouter(
            maximum_attempts=job.budget.repair_attempts,
            artifact_store=self.artifacts,
        )
        integration_ordinal = 0
        pending: _PendingRepairActions | None = None
        while True:
            integration_ordinal += 1
            attempt_id = self._start_attempt(
                run,
                "integration",
                (build.candidate_ref, design.world_spec_ref),
            )
            try:
                available = self._budget_excluding_reservation(
                    run.ledger.remaining,
                    sibling_reservation() if sibling_reservation is not None else None,
                )
                requested_budget = self.judge.required_integration_budget(
                    design=design.design,
                    available=available,
                )
                work = self._reserve_judge_work(
                    run,
                    attempt_id=attempt_id,
                    requested=requested_budget,
                    available=available,
                )
            except BudgetExceeded as exc:
                if pending is not None:
                    self._terminate_repair_routes(
                        run,
                        pending.directives,
                        outcome="exhausted",
                        retained_refs=(design.design_ref, build.candidate_ref),
                        usage=pending.action_usage,
                    )
                self._finish_attempt(
                    run,
                    attempt_id,
                    status="budget_exhausted",
                    failure_code="integration_budget_reservation_exhausted",
                    failure_summary="Integration work could not reserve its vector budget.",
                )
                raise _GenerationHalt(
                    status="budget_exhausted",
                    code="integration_budget_reservation_exhausted",
                    summary=(
                        "Early real execution cannot reserve budget dimensions: "
                        f"{', '.join(exc.dimensions)}."
                    ),
                ) from exc
            except Exception as exc:
                if pending is not None:
                    self._terminate_repair_routes(
                        run,
                        pending.directives,
                        outcome="escalated",
                        retained_refs=(design.design_ref, build.candidate_ref),
                        usage=pending.action_usage,
                    )
                self._finish_attempt(
                    run,
                    attempt_id,
                    status="failed",
                    failure_code="integration_budget_preparation_error",
                    failure_summary="Integration budget preparation failed closed.",
                )
                raise _GenerationHalt(
                    status="failed",
                    code="integration_budget_preparation_error",
                    summary="Early execution could not prepare a durable work lease.",
                ) from exc
            try:
                await self._persist_snapshot(run, status="running")
                async with asyncio.timeout(work.lease.reserved.wall_seconds):
                    integrated = await self.judge.evaluate_integration(
                        candidate=build.candidate,
                        candidate_ref=build.candidate_ref,
                        source_dir=build.project_root,
                        world_spec=design.world_spec,
                        world_spec_ref=design.world_spec_ref,
                        release_profile=job.release_profile,
                        budget=work.lease.reserved,
                        run_id=f"{run.run_id}:integration:{integration_ordinal}",
                    )
                self._settle_judge_work(run, work, integrated.report.budget_usage)
            except BudgetExceeded as exc:
                if pending is not None:
                    self._terminate_repair_routes(
                        run,
                        pending.directives,
                        outcome="escalated",
                        retained_refs=(design.design_ref, build.candidate_ref),
                        usage=pending.action_usage,
                    )
                failure_usage = self._settle_failed_judge_work(run, work)
                self._finish_attempt(
                    run,
                    attempt_id,
                    status="budget_exhausted",
                    failure_code="integration_budget_exhausted",
                    failure_summary="Integration exceeded its reserved vector budget.",
                    usage=failure_usage,
                )
                raise _GenerationHalt(
                    status="budget_exhausted",
                    code="integration_budget_exhausted",
                    summary=f"Integration exhausted: {', '.join(exc.dimensions)}.",
                ) from exc
            except asyncio.CancelledError:
                if pending is not None:
                    self._terminate_repair_routes(
                        run,
                        pending.directives,
                        outcome="escalated",
                        retained_refs=(design.design_ref, build.candidate_ref),
                        usage=pending.action_usage,
                    )
                failure_usage = self._settle_failed_judge_work(run, work)
                self._finish_attempt(
                    run,
                    attempt_id,
                    status="failed",
                    failure_code="integration_cancelled",
                    failure_summary="Integration was cancelled with unknown final usage.",
                    usage=failure_usage,
                )
                raise
            except Exception as exc:
                if pending is not None:
                    self._terminate_repair_routes(
                        run,
                        pending.directives,
                        outcome="escalated",
                        retained_refs=(design.design_ref, build.candidate_ref),
                        usage=pending.action_usage,
                    )
                failure_usage = self._settle_failed_judge_work(run, work)
                finding_ref = self._control_failure_finding(
                    run,
                    node="integration",
                    event_kind=ControlEventKind.INFRASTRUCTURE_FAILURE,
                    code="integration_execution_error",
                    error_type=type(exc).__name__,
                )
                self._finish_attempt(
                    run,
                    attempt_id,
                    status="failed",
                    finding_refs=(finding_ref,),
                    failure_code="integration_execution_error",
                    failure_summary="Integration failed before committing a report.",
                    usage=failure_usage,
                )
                raise _GenerationHalt(
                    status="failed",
                    code="integration_execution_error",
                    summary="Integration infrastructure failed without usable evidence.",
                    finding_refs=(finding_ref,),
                ) from exc

            finding_refs = self._persist_integration_findings(
                run=run,
                integration_bundle=integrated,
                ordinal=integration_ordinal,
            )
            outputs = (integrated.report_ref, *integrated.evidence_refs)
            run.remember(*outputs)
            run.remember_findings(*finding_refs)
            status: Literal["passed", "failed"] = (
                "passed" if integrated.report.status == "ready" else "failed"
            )
            feedback_ref = self._record_feedback_result(
                contract_id="feedback.integration.runtime",
                status=status,
                subject_ref=integrated.report_ref,
                evidence_refs=tuple(integrated.evidence_refs) or (integrated.report_ref,),
                diagnostic_ref=(integrated.report_ref if status == "failed" else None),
                summary=(
                    "The candidate passed real install, reset and invocation execution."
                    if status == "passed"
                    else "Real integration execution produced release-blocking findings."
                ),
                usage=integrated.report.budget_usage,
            )
            run.remember(feedback_ref)
            self._finish_attempt(
                run,
                attempt_id,
                status=status,
                output_refs=outputs,
                finding_refs=finding_refs,
                failure_code=(None if status == "passed" else "integration_not_ready"),
                failure_summary=(
                    None
                    if status == "passed"
                    else "Candidate did not pass early real install/reset/invoke execution."
                ),
                usage=integrated.report.budget_usage,
            )

            blockers_after = tuple(
                sorted(
                    item.fingerprint for item in integrated.report.findings if item.blocks_release
                )
            )
            if pending is not None:
                for directive in pending.directives:
                    if directive.ledger_entry_id is None:
                        raise ValueError("pending repair directive lacks ledger entry")
                    ledger_entry = next(
                        item
                        for item in run.repair_ledger.entries
                        if item.entry_id == directive.ledger_entry_id
                    )
                    progress_evidence: Literal["none", "issue_set_changed"] = "none"
                    if (
                        ledger_entry.blocking_claim_ids_before
                        and blockers_after
                        and frozenset(ledger_entry.blocking_claim_ids_before)
                        != frozenset(blockers_after)
                    ):
                        progress_evidence = "issue_set_changed"
                    run.repair_ledger.complete(
                        directive.ledger_entry_id,
                        blocking_claim_ids_after=blockers_after,
                        invalidated_refs=pending.invalidated_refs,
                        retained_refs=(design.design_ref,),
                        session_strategy=pending.session_strategy,
                        progress_evidence=progress_evidence,
                        usage=pending.action_usage,
                    )
                self._persist_repair_ledger_entries(run, pending.directives)
                pending = None
            await self._persist_snapshot(run, status="running")
            if integrated.report.status == "ready":
                return integrated, build

            blockers_before = tuple(
                sorted(
                    item.fingerprint for item in integrated.report.findings if item.blocks_release
                )
            )
            finding_pairs = tuple(zip(integrated.report.findings, finding_refs, strict=True))
            finding_by_revision = {
                ref.revision_id: (finding, ref) for finding, ref in finding_pairs
            }
            routes = router.route_many(
                finding_pairs,
                current_node="integration",
                ledger=run.repair_ledger,
                blocking_claim_ids_before=blockers_before,
            )
            if not routes:
                raise _GenerationHalt(
                    status="failed",
                    code="integration_failed_without_routable_finding",
                    summary="Integration failed without a routable structured Finding.",
                    finding_refs=finding_refs,
                )
            ledger_refs = self._persist_repair_ledger_entries(run, routes)
            directive_refs = tuple(
                self.artifacts.put_json(
                    artifact_id=(
                        f"{run.run_id}:integration-repair-directive:{integration_ordinal}:{index}"
                    ),
                    artifact_type="control.repair_directive",
                    value=directive,
                    dependencies=(
                        directive.finding_ref,
                        *directive.related_finding_refs,
                        integrated.report_ref,
                        ledger_refs[index],
                    ),
                )
                for index, directive in enumerate(routes)
            )
            run.remember(*directive_refs)

            design_indices = tuple(
                index
                for index, route in enumerate(routes)
                if route.owner_node == "design" and route.action == "new_revision"
            )
            if design_indices:
                selected = tuple(routes[index] for index in design_indices)
                nonselected = tuple(
                    route for index, route in enumerate(routes) if index not in design_indices
                )
                self._terminate_repair_routes(
                    run,
                    nonselected,
                    outcome="escalated",
                    retained_refs=(integrated.report_ref, design.design_ref),
                )
                design_pairs = tuple(
                    finding_by_revision[ref.revision_id]
                    for route in selected
                    for ref in (route.finding_ref, *route.related_finding_refs)
                )
                raise _DesignReworkRequired(
                    findings=tuple(finding for finding, _ref in design_pairs),
                    finding_refs=tuple(ref for _finding, ref in design_pairs),
                    directive_refs=tuple(directive_refs[index] for index in design_indices),
                )

            if all(
                item.owner_node == "judge" and item.action == "retry_infrastructure"
                for item in routes
            ):
                if run.ledger.remaining.repair_attempts < 1:
                    self._terminate_repair_routes(
                        run,
                        routes,
                        outcome="exhausted",
                        retained_refs=(integrated.report_ref,),
                    )
                    raise _GenerationHalt(
                        status="budget_exhausted",
                        code="integration_infrastructure_retry_budget_exhausted",
                        summary="Integration infrastructure retry budget is exhausted.",
                        finding_refs=finding_refs,
                    )
                run.ledger.consume(BudgetUsage(repair_attempts=1))
                pending = _PendingRepairActions(
                    directives=routes,
                    session_strategy="none",
                    action_usage=BudgetUsage(repair_attempts=1),
                )
                await self._persist_snapshot(run, status="running")
                continue

            unsupported = tuple(
                route
                for route in routes
                if route.owner_node != "build" or route.action != "continue_session"
            )
            if unsupported:
                needs_human = any(item.action == "request_permission" for item in unsupported)
                self._terminate_repair_routes(
                    run,
                    routes,
                    outcome="escalated",
                    retained_refs=(integrated.report_ref, design.design_ref),
                )
                raise _GenerationHalt(
                    status="needs_human" if needs_human else "failed",
                    code=self._safe_identifier(
                        f"integration_repair_{unsupported[0].owner_node}_{unsupported[0].action}"
                    ),
                    summary=(
                        "Integration repair was rejected by the bounded router: "
                        f"{unsupported[0].decision_reason}."
                    ),
                    finding_refs=finding_refs,
                )
            remaining = self._budget_excluding_reservation(
                run.ledger.remaining,
                sibling_reservation() if sibling_reservation is not None else None,
            )
            if (
                remaining.repair_attempts < 1
                or remaining.agent_turns < 1
                or remaining.build_seconds <= 0
                or remaining.wall_seconds <= 0
            ):
                self._terminate_repair_routes(
                    run,
                    routes,
                    outcome="exhausted",
                    retained_refs=(integrated.report_ref, design.design_ref),
                )
                raise _GenerationHalt(
                    status="budget_exhausted",
                    code="integration_builder_repair_budget_exhausted",
                    summary="Integration authorized Builder repair but its budget is exhausted.",
                    finding_refs=finding_refs,
                )
            if build.state is None:
                self._terminate_repair_routes(
                    run,
                    routes,
                    outcome="escalated",
                    retained_refs=(integrated.report_ref, design.design_ref),
                )
                raise _GenerationHalt(
                    status="failed",
                    code="recovered_build_requires_fresh_codegen",
                    summary=(
                        "Recovered Build failed Integration without a resumable Agent session; "
                        "a fresh Builder revision is required."
                    ),
                    finding_refs=finding_refs,
                )
            try:
                repair_remaining = BudgetLedger(
                    remaining,
                    BudgetUsage(repair_attempts=1),
                ).remaining
                repair_reservation = self._builder_repair_budget(
                    repair_remaining,
                    build.state,
                )
            except BudgetExceeded as exc:
                self._terminate_repair_routes(
                    run,
                    routes,
                    outcome="exhausted",
                    retained_refs=(integrated.report_ref, design.design_ref),
                )
                raise _GenerationHalt(
                    status="budget_exhausted",
                    code="integration_builder_repair_budget_exhausted",
                    summary=(
                        "Integration-authorized Builder repair cannot reserve one complete "
                        f"session turn: {', '.join(exc.dimensions)}."
                    ),
                    finding_refs=finding_refs,
                ) from exc
            except Exception as exc:
                self._terminate_repair_routes(
                    run,
                    routes,
                    outcome="escalated",
                    retained_refs=(integrated.report_ref, design.design_ref),
                )
                raise _GenerationHalt(
                    status="failed",
                    code="integration_builder_repair_profile_invalid",
                    summary="The resumable Builder session lacks enforceable per-turn limits.",
                    finding_refs=finding_refs,
                ) from exc
            repair_budget = repair_reservation.model_copy(update={"repair_attempts": 1})
            try:
                repair_attempt_id = self._start_attempt(
                    run,
                    "build",
                    (build.candidate_ref, *finding_refs, *directive_refs),
                )
            except Exception as exc:
                self._terminate_repair_routes(
                    run,
                    routes,
                    outcome="escalated",
                    retained_refs=(integrated.report_ref, design.design_ref),
                )
                await self._persist_snapshot(run, status="running")
                raise _GenerationHalt(
                    status="failed",
                    code="integration_builder_repair_attempt_start_failed",
                    summary="Builder repair could not create an atomic NodeAttempt.",
                    finding_refs=finding_refs,
                ) from exc
            repair_work: _AgentInvocationWorkLease | None = None
            repair_action_consumed = False
            try:
                run.ledger.consume(BudgetUsage(repair_attempts=1))
                repair_action_consumed = True
                repair_work = self._reserve_agent_invocation_work(
                    run,
                    attempt_id=repair_attempt_id,
                    requested=repair_reservation,
                    available=repair_remaining,
                )
                await self._persist_snapshot(run, status="running")
                repaired = await self.builder.repair(
                    state=build.state,
                    findings=integrated.report.findings,
                    budget=repair_budget,
                )
                repair_actual, repair_unknown = self._builder_invocation_settlement(
                    repaired.invocation,
                    unknown_token_cap=repair_budget.llm_tokens,
                    monetary_upper_bound=repair_budget.monetary_cost,
                    reserved_turns=repair_budget.agent_turns,
                )
                repair_usage = self._settle_agent_invocation_work(
                    run,
                    repair_work,
                    observed_actual=repair_actual,
                    unknown_upper_bound=repair_unknown,
                )
            except BaseException as exc:
                failure_invocation_usage = BudgetUsage()
                if isinstance(exc, BuilderError) and exc.invocation is not None:
                    failure_actual, failure_unknown = self._builder_invocation_settlement(
                        exc.invocation,
                        unknown_token_cap=repair_budget.llm_tokens,
                        monetary_upper_bound=repair_budget.monetary_cost,
                        reserved_turns=repair_budget.agent_turns,
                    )
                    if repair_work is None:
                        raise RuntimeError(
                            "Builder invocation evidence exists without a persisted repair lease"
                        ) from exc
                    failure_invocation_usage = self._settle_agent_invocation_work(
                        run,
                        repair_work,
                        observed_actual=failure_actual,
                        unknown_upper_bound=failure_unknown,
                    )
                elif repair_work is not None:
                    failure_invocation_usage = self._settle_agent_invocation_work(
                        run,
                        repair_work,
                        observed_actual=BudgetUsage(),
                        unknown_upper_bound=self._agent_invocation_unknown(
                            repair_reservation,
                            include_build_time=True,
                        ),
                    )
                failure_usage = self._add_usage(
                    BudgetUsage(repair_attempts=1 if repair_action_consumed else 0),
                    failure_invocation_usage,
                )
                if isinstance(exc, asyncio.CancelledError):
                    repair_status: Literal["failed", "needs_human", "budget_exhausted"] = "failed"
                    code = "integration_builder_repair_cancelled"
                elif isinstance(exc, BudgetExceeded):
                    repair_status = "budget_exhausted"
                    code = "integration_builder_repair_budget_exhausted"
                elif isinstance(exc, BuilderError):
                    repair_status, code = self._invocation_failure_status(
                        exc.invocation.status if exc.invocation is not None else None,
                        default_code=(
                            f"integration_builder_repair_{self._safe_identifier(exc.stage)}"
                        ),
                    )
                else:
                    repair_status = "failed"
                    code = "integration_builder_repair_infrastructure_error"
                self._finish_attempt(
                    run,
                    repair_attempt_id,
                    status=repair_status,
                    finding_refs=finding_refs,
                    failure_code=code,
                    failure_summary="Builder did not produce a repaired Integration candidate.",
                    usage=failure_usage,
                )
                self._terminate_repair_routes(
                    run,
                    routes,
                    outcome=("exhausted" if repair_status == "budget_exhausted" else "escalated"),
                    retained_refs=(integrated.report_ref, design.design_ref),
                    usage=failure_usage,
                )
                await self._persist_snapshot(run, status="running")
                if isinstance(exc, asyncio.CancelledError):
                    raise
                raise _GenerationHalt(
                    status=self._generate_status(repair_status),
                    code=code,
                    summary="Integration-directed Builder repair did not complete.",
                    finding_refs=finding_refs,
                ) from exc
            repair_outputs = (
                repaired.source_snapshot_ref,
                repaired.implementation_lineage_ref,
                repaired.candidate_manifest_ref,
                repaired.build_artifact_ref,
                repaired.candidate_ref,
            )
            run.remember(*repair_outputs)
            invalidated_refs = self._invalidate_artifact_descendants(
                run,
                superseded_refs=(build.candidate_ref,),
                invalidating_refs=(repaired.candidate_ref,),
            )
            self._finish_attempt(
                run,
                repair_attempt_id,
                status="passed",
                output_refs=repair_outputs,
                usage=self._add_usage(BudgetUsage(repair_attempts=1), repair_usage),
                profile_hash=(
                    f"sha256:{repaired.state.profile.profile_hash}"
                    if repaired.state is not None
                    else None
                ),
                session_id=(
                    self._hashed_session(repaired.session.thread_id)
                    if repaired.session is not None
                    else None
                ),
            )
            pending = _PendingRepairActions(
                directives=routes,
                session_strategy="continued",
                action_usage=self._add_usage(
                    BudgetUsage(repair_attempts=1),
                    repair_usage,
                ),
                invalidated_refs=invalidated_refs,
            )
            await self._persist_snapshot(run, status="running")
            build = repaired

    async def _judge_and_repair(
        self,
        *,
        run: _RunState,
        job: EnvironmentJob,
        design: ExecutableDesignBundle,
        compiled: CompiledVerifier,
        build: BuildBundle,
    ) -> tuple[JudgeBundle, BuildBundle]:
        router = RepairRouter(
            maximum_attempts=job.budget.repair_attempts,
            artifact_store=self.artifacts,
        )
        judge_ordinal = 0
        pending: _PendingRepairActions | None = None
        while True:
            judge_ordinal += 1
            attempt_id = self._start_attempt(
                run,
                "judge",
                (build.candidate_ref, compiled.verifier_ref),
            )
            try:
                requested_budget = self.judge.required_evaluation_budget(
                    design=design.design,
                    verifier=compiled.verifier,
                    available=run.ledger.remaining,
                )
                judge_work = self._reserve_judge_work(
                    run,
                    attempt_id=attempt_id,
                    requested=requested_budget,
                )
            except BudgetExceeded as exc:
                if pending is not None:
                    self._terminate_repair_routes(
                        run,
                        pending.directives,
                        outcome="exhausted",
                        retained_refs=(design.design_ref, build.candidate_ref),
                        usage=pending.action_usage,
                    )
                self._finish_attempt(
                    run,
                    attempt_id,
                    status="budget_exhausted",
                    failure_code="judge_budget_reservation_exhausted",
                    failure_summary="Judge worst-case work could not be reserved before execution.",
                )
                raise _GenerationHalt(
                    status="budget_exhausted",
                    code="judge_budget_reservation_exhausted",
                    summary=(
                        "Full independent evaluation cannot reserve budget dimensions: "
                        f"{', '.join(exc.dimensions)}."
                    ),
                ) from exc
            except Exception as exc:
                if pending is not None:
                    self._terminate_repair_routes(
                        run,
                        pending.directives,
                        outcome="escalated",
                        retained_refs=(design.design_ref, build.candidate_ref),
                        usage=pending.action_usage,
                    )
                finding_ref = self._control_failure_finding(
                    run,
                    node="judge",
                    event_kind=ControlEventKind.INFRASTRUCTURE_FAILURE,
                    code="judge_budget_compilation_error",
                    error_type=type(exc).__name__,
                )
                self._finish_attempt(
                    run,
                    attempt_id,
                    status="failed",
                    finding_refs=(finding_ref,),
                    failure_code="judge_budget_compilation_error",
                    failure_summary=(
                        "Judge worst-case budget could not be compiled and persisted."
                    ),
                )
                raise _GenerationHalt(
                    status="failed",
                    code="judge_budget_compilation_error",
                    summary="Independent Judge budget preparation failed closed.",
                    finding_refs=(finding_ref,),
                ) from exc
            try:
                await self._persist_snapshot(run, status="running")
                async with asyncio.timeout(judge_work.lease.reserved.wall_seconds):
                    judge_bundle = await self.judge.evaluate(
                        candidate=build.candidate,
                        candidate_ref=build.candidate_ref,
                        source_dir=build.project_root,
                        world_spec=design.world_spec,
                        world_spec_ref=design.world_spec_ref,
                        verifier=compiled.verifier,
                        verifier_ref=compiled.verifier_ref,
                        release_profile=job.release_profile,
                        budget=judge_work.lease.reserved,
                        reachability_workspace=self._workspace_for(
                            run.run_id,
                            "judge",
                            f"attempt-{judge_ordinal}",
                            "reachability",
                        ),
                        run_id=f"{run.run_id}:judge:{judge_ordinal}",
                    )
                self._settle_judge_work(
                    run,
                    judge_work,
                    judge_bundle.report.budget_usage,
                )
            except BudgetExceeded as exc:
                if pending is not None:
                    self._terminate_repair_routes(
                        run,
                        pending.directives,
                        outcome="escalated",
                        retained_refs=(design.design_ref, build.candidate_ref),
                        usage=pending.action_usage,
                    )
                failure_usage = self._settle_failed_judge_work(run, judge_work)
                self._finish_attempt(
                    run,
                    attempt_id,
                    status="budget_exhausted",
                    failure_code="judge_budget_exhausted",
                    failure_summary="Judge completed outside the reserved vector budget.",
                    usage=failure_usage,
                )
                raise _GenerationHalt(
                    status="budget_exhausted",
                    code="judge_budget_exhausted",
                    summary=f"Judge exhausted budget dimensions: {', '.join(exc.dimensions)}.",
                ) from exc
            except asyncio.CancelledError:
                if pending is not None:
                    self._terminate_repair_routes(
                        run,
                        pending.directives,
                        outcome="escalated",
                        retained_refs=(design.design_ref, build.candidate_ref),
                        usage=pending.action_usage,
                    )
                failure_usage = self._settle_failed_judge_work(run, judge_work)
                self._finish_attempt(
                    run,
                    attempt_id,
                    status="failed",
                    failure_code="judge_cancelled",
                    failure_summary=(
                        "Judge was cancelled with unknown final usage; its full lease was charged."
                    ),
                    usage=failure_usage,
                )
                raise
            except Exception as exc:
                if pending is not None:
                    self._terminate_repair_routes(
                        run,
                        pending.directives,
                        outcome="escalated",
                        retained_refs=(design.design_ref, build.candidate_ref),
                        usage=pending.action_usage,
                    )
                failure_usage = self._settle_failed_judge_work(run, judge_work)
                finding_ref = self._control_failure_finding(
                    run,
                    node="judge",
                    event_kind=ControlEventKind.INFRASTRUCTURE_FAILURE,
                    code="judge_execution_error",
                    error_type=type(exc).__name__,
                )
                self._finish_attempt(
                    run,
                    attempt_id,
                    status="failed",
                    finding_refs=(finding_ref,),
                    failure_code="judge_execution_error",
                    failure_summary="Judge infrastructure failed before a report was committed.",
                    usage=failure_usage,
                )
                raise _GenerationHalt(
                    status="failed",
                    code="judge_execution_error",
                    summary="Independent Judge failed without release evidence.",
                    finding_refs=(finding_ref,),
                ) from exc

            finding_refs = self._persist_judge_findings(
                run=run,
                judge_bundle=judge_bundle,
                ordinal=judge_ordinal,
            )
            outputs = (judge_bundle.report_ref, *judge_bundle.evidence_refs)
            run.remember(*outputs)
            run.remember_findings(*finding_refs)
            blockers_after = tuple(
                sorted(
                    finding.fingerprint
                    for finding in judge_bundle.report.findings
                    if finding.blocks_release
                )
            )
            if pending is not None:
                for directive in pending.directives:
                    if directive.ledger_entry_id is None:
                        raise ValueError("pending Judge repair directive lacks ledger entry")
                    ledger_entry = next(
                        item
                        for item in run.repair_ledger.entries
                        if item.entry_id == directive.ledger_entry_id
                    )
                    progress_evidence: Literal["none", "issue_set_changed"] = "none"
                    if (
                        ledger_entry.blocking_claim_ids_before
                        and blockers_after
                        and frozenset(ledger_entry.blocking_claim_ids_before)
                        != frozenset(blockers_after)
                    ):
                        progress_evidence = "issue_set_changed"
                    run.repair_ledger.complete(
                        directive.ledger_entry_id,
                        blocking_claim_ids_after=blockers_after,
                        invalidated_refs=pending.invalidated_refs,
                        retained_refs=(design.design_ref, compiled.verifier_ref),
                        session_strategy=pending.session_strategy,
                        progress_evidence=progress_evidence,
                        usage=pending.action_usage,
                    )
                self._persist_repair_ledger_entries(run, pending.directives)
                pending = None
            judge_status: Literal["passed", "failed"] = (
                "passed" if judge_bundle.report.verdict == "pass" else "failed"
            )
            feedback_ref = self._record_feedback_result(
                contract_id="feedback.judge.release",
                status=judge_status,
                subject_ref=judge_bundle.report_ref,
                evidence_refs=tuple(judge_bundle.evidence_refs) or (judge_bundle.report_ref,),
                diagnostic_ref=(judge_bundle.report_ref if judge_status == "failed" else None),
                summary=(
                    "Independent executable release gates passed for the exact candidate bytes."
                    if judge_status == "passed"
                    else "Independent executable release gates produced blocking findings."
                ),
                usage=judge_bundle.report.budget_usage,
            )
            run.remember(feedback_ref)
            self._finish_attempt(
                run,
                attempt_id,
                status=judge_status,
                output_refs=outputs if judge_status == "passed" else (),
                finding_refs=finding_refs,
                failure_code=(
                    None if judge_status == "passed" else f"judge_{judge_bundle.report.verdict}"
                ),
                failure_summary=(
                    None
                    if judge_status == "passed"
                    else "One or more independent release gates did not pass."
                ),
                usage=judge_bundle.report.budget_usage,
            )
            await self._persist_snapshot(run, status="running")
            if judge_bundle.report.verdict == "pass":
                return judge_bundle, build

            blockers_before = tuple(
                sorted(
                    finding.fingerprint
                    for finding in judge_bundle.report.findings
                    if finding.blocks_release
                )
            )
            finding_pairs = tuple(zip(judge_bundle.report.findings, finding_refs, strict=True))
            finding_by_revision = {
                ref.revision_id: (finding, ref) for finding, ref in finding_pairs
            }
            routes = router.route_many(
                finding_pairs,
                current_node="judge",
                ledger=run.repair_ledger,
                blocking_claim_ids_before=blockers_before,
            )
            ledger_refs = self._persist_repair_ledger_entries(run, routes)
            directive_refs = tuple(
                self.artifacts.put_json(
                    artifact_id=(f"{run.run_id}:repair-directive:{judge_ordinal}:{index}"),
                    artifact_type="control.repair_directive",
                    value=directive,
                    dependencies=(
                        directive.finding_ref,
                        *directive.related_finding_refs,
                        judge_bundle.report_ref,
                        ledger_refs[index],
                    ),
                )
                for index, directive in enumerate(routes)
            )
            run.remember(*directive_refs)
            design_indices = tuple(
                index
                for index, directive in enumerate(routes)
                if directive.owner_node == "design" and directive.action == "new_revision"
            )
            if design_indices:
                nonselected = tuple(
                    route for index, route in enumerate(routes) if index not in design_indices
                )
                self._terminate_repair_routes(
                    run,
                    nonselected,
                    outcome="escalated",
                    retained_refs=(judge_bundle.report_ref, design.design_ref),
                )
                design_pairs = tuple(
                    finding_by_revision[ref.revision_id]
                    for index in design_indices
                    for ref in (
                        routes[index].finding_ref,
                        *routes[index].related_finding_refs,
                    )
                )
                raise _DesignReworkRequired(
                    findings=tuple(finding for finding, _ref in design_pairs),
                    finding_refs=tuple(ref for _finding, ref in design_pairs),
                    directive_refs=tuple(directive_refs[index] for index in design_indices),
                )
            if routes and all(
                directive.owner_node == "judge" and directive.action == "retry_infrastructure"
                for directive in routes
            ):
                if run.ledger.remaining.repair_attempts < 1:
                    self._terminate_repair_routes(
                        run,
                        routes,
                        outcome="exhausted",
                        retained_refs=(judge_bundle.report_ref,),
                    )
                    raise _GenerationHalt(
                        status="budget_exhausted",
                        code="judge_infrastructure_retry_budget_exhausted",
                        summary="Judge infrastructure retry budget is exhausted.",
                        finding_refs=finding_refs,
                    )
                run.ledger.consume(BudgetUsage(repair_attempts=1))
                self.artifacts.record_event(
                    event_type="judge_infrastructure_retry",
                    subject_ref=judge_bundle.report_ref,
                    related_refs=(*finding_refs, *directive_refs),
                    details=(KeyValue(key="next_attempt", value=judge_ordinal + 1),),
                )
                pending = _PendingRepairActions(
                    directives=routes,
                    session_strategy="none",
                    action_usage=BudgetUsage(repair_attempts=1),
                )
                await self._persist_snapshot(run, status="running")
                continue
            if routes and all(
                directive.owner_node == "verifier" and directive.action == "new_revision"
                for directive in routes
            ):
                remaining = run.ledger.remaining
                required_verifier_turns = self.verifier_compiler.maximum_invocation_turns(
                    len(design.design.curriculum.task_types)
                )
                if remaining.repair_attempts < 1 or remaining.agent_turns < required_verifier_turns:
                    self._terminate_repair_routes(
                        run,
                        routes,
                        outcome="exhausted",
                        retained_refs=(judge_bundle.report_ref, design.design_ref),
                    )
                    raise _GenerationHalt(
                        status="budget_exhausted",
                        code="verifier_rework_budget_exhausted",
                        summary="Verifier revision is required but its Agent budget is exhausted.",
                        finding_refs=finding_refs,
                    )
                verifier_base_turns = self.verifier_compiler.minimum_invocation_turns(
                    len(design.design.curriculum.task_types)
                )
                try:
                    available_after_action = BudgetLedger(
                        remaining,
                        BudgetUsage(repair_attempts=1),
                    ).remaining
                    verifier_rework_budget = self._verifier_only_budget(
                        available_after_action,
                        verifier_base_turns=verifier_base_turns,
                    )
                except (_GenerationHalt, BudgetExceeded):
                    self._terminate_repair_routes(
                        run,
                        routes,
                        outcome="exhausted",
                        retained_refs=(judge_bundle.report_ref, design.design_ref),
                    )
                    raise
                verifier_attempt_id = self._start_attempt(
                    run,
                    "verifier",
                    (compiled.verifier_ref, *finding_refs, *directive_refs),
                )
                run.ledger.consume(BudgetUsage(repair_attempts=1))
                verifier_work: _AgentInvocationWorkLease | None = None
                try:
                    verifier_work = self._reserve_agent_invocation_work(
                        run,
                        attempt_id=verifier_attempt_id,
                        requested=verifier_rework_budget,
                    )
                    await self._persist_snapshot(run, status="running")
                    revised = await self.verifier_compiler.compile(
                        design=design.design,
                        design_ref=design.design_ref,
                        world_spec_ref=design.world_spec_ref,
                        workspace=self._workspace_for(
                            run.run_id,
                            f"verifier-rework-{judge_ordinal}",
                        ),
                        lineage_id=f"{run.run_id}.verifier.rework.{judge_ordinal}",
                        budget=verifier_rework_budget,
                        permissions=job.permissions,
                        repair_findings=judge_bundle.report.findings,
                        repair_authority=self._structured_repair_authority(run),
                    )
                    verifier_actual, verifier_unknown = self._invocation_settlement(
                        revised.invocation_results,
                        unknown_token_cap=verifier_rework_budget.llm_tokens,
                        base_turns=verifier_base_turns,
                        monetary_upper_bound=verifier_rework_budget.monetary_cost,
                        reserved_turns=verifier_rework_budget.agent_turns,
                    )
                    verifier_usage = self._settle_agent_invocation_work(
                        run,
                        verifier_work,
                        observed_actual=verifier_actual,
                        unknown_upper_bound=verifier_unknown,
                    )
                except BaseException as exc:
                    failure_invocation_usage = BudgetUsage()
                    if verifier_work is not None:
                        if isinstance(exc, VerifierCompilationError):
                            failure_actual, failure_unknown = self._verifier_result_settlement(
                                exc,
                                budget=verifier_rework_budget,
                                base_turns=verifier_base_turns,
                            )
                        else:
                            failure_actual = BudgetUsage()
                            failure_unknown = self._agent_invocation_unknown(
                                verifier_rework_budget,
                                include_build_time=False,
                            )
                        failure_invocation_usage = self._settle_agent_invocation_work(
                            run,
                            verifier_work,
                            observed_actual=failure_actual,
                            unknown_upper_bound=failure_unknown,
                        )
                    failure_usage = self._add_usage(
                        BudgetUsage(repair_attempts=1),
                        failure_invocation_usage,
                    )
                    if isinstance(exc, asyncio.CancelledError):
                        verifier_code = "verifier_rework_cancelled"
                        verifier_status: Literal["failed", "needs_human", "budget_exhausted"] = (
                            "failed"
                        )
                    else:
                        verifier_code, verifier_status = self._verifier_error(exc)
                    self._finish_attempt(
                        run,
                        verifier_attempt_id,
                        status=verifier_status,
                        finding_refs=finding_refs,
                        failure_code=verifier_code,
                        failure_summary="Verifier rework did not produce a valid revision.",
                        usage=failure_usage,
                    )
                    self._terminate_repair_routes(
                        run,
                        routes,
                        outcome=("exhausted" if isinstance(exc, BudgetExceeded) else "escalated"),
                        retained_refs=(judge_bundle.report_ref, design.design_ref),
                        usage=failure_usage,
                    )
                    await self._persist_snapshot(run, status="running")
                    if isinstance(exc, asyncio.CancelledError):
                        raise
                    raise _GenerationHalt(
                        status=self._generate_status(verifier_status),
                        code=verifier_code,
                        summary="Independent Challenger failed to revise the Verifier IR.",
                        finding_refs=finding_refs,
                    ) from exc
                compiled = revised
                run.remember(revised.verifier_ref, *revised.checkpoint_refs)
                self._finish_attempt(
                    run,
                    verifier_attempt_id,
                    status="passed",
                    output_refs=(*revised.checkpoint_refs, revised.verifier_ref),
                    usage=self._add_usage(
                        BudgetUsage(repair_attempts=1),
                        verifier_usage,
                    ),
                    profile_hash=self._last_profile_hash(revised.invocation_results),
                    session_id=self._last_session_id(revised.invocation_results),
                )
                pending = _PendingRepairActions(
                    directives=routes,
                    session_strategy="fresh",
                    action_usage=self._add_usage(
                        BudgetUsage(repair_attempts=1),
                        verifier_usage,
                    ),
                )
                await self._persist_snapshot(run, status="running")
                continue
            non_build = tuple(
                directive
                for directive in routes
                if directive.owner_node != "build" or directive.action != "continue_session"
            )
            if non_build:
                status: GenerateStatus = (
                    "needs_human"
                    if any(directive.action == "request_permission" for directive in non_build)
                    else "failed"
                )
                code = self._safe_identifier(
                    f"repair_{non_build[0].owner_node}_{non_build[0].action}"
                )
                self._terminate_repair_routes(
                    run,
                    routes,
                    outcome="escalated",
                    retained_refs=(judge_bundle.report_ref, design.design_ref),
                )
                raise _GenerationHalt(
                    status=status,
                    code=code,
                    summary=(
                        "Judge Findings are not implementation-owned; Controller preserved the "
                        "RepairRouter decision and stopped instead of guessing an upstream fix."
                    ),
                    finding_refs=finding_refs,
                )
            if not routes:
                raise _GenerationHalt(
                    status="failed",
                    code="judge_failed_without_routable_finding",
                    summary="Judge failed without a routable structured Finding.",
                    finding_refs=finding_refs,
                )
            if build.state is None:
                self._terminate_repair_routes(
                    run,
                    routes,
                    outcome="escalated",
                    retained_refs=(judge_bundle.report_ref, design.design_ref),
                )
                raise _GenerationHalt(
                    status="failed",
                    code="recovered_build_requires_fresh_codegen",
                    summary=(
                        "The recovered candidate needs implementation repair, but its ephemeral "
                        "Agent session is intentionally absent; a fresh Builder run is required."
                    ),
                    finding_refs=finding_refs,
                )
            remaining = run.ledger.remaining
            if (
                remaining.repair_attempts < 1
                or remaining.agent_turns < 1
                or remaining.build_seconds <= 0
                or remaining.wall_seconds <= 0
            ):
                self._terminate_repair_routes(
                    run,
                    routes,
                    outcome="exhausted",
                    retained_refs=(judge_bundle.report_ref, design.design_ref),
                )
                raise _GenerationHalt(
                    status="budget_exhausted",
                    code="builder_repair_budget_exhausted",
                    summary=(
                        "Implementation repair is authorized but its vector budget is exhausted."
                    ),
                    finding_refs=finding_refs,
                )
            try:
                repair_remaining = BudgetLedger(
                    remaining,
                    BudgetUsage(repair_attempts=1),
                ).remaining
                repair_reservation = self._builder_repair_budget(
                    repair_remaining,
                    build.state,
                )
            except BudgetExceeded as exc:
                self._terminate_repair_routes(
                    run,
                    routes,
                    outcome="exhausted",
                    retained_refs=(judge_bundle.report_ref, design.design_ref),
                )
                raise _GenerationHalt(
                    status="budget_exhausted",
                    code="builder_repair_budget_exhausted",
                    summary=(
                        "Implementation repair cannot reserve one complete session turn: "
                        f"{', '.join(exc.dimensions)}."
                    ),
                    finding_refs=finding_refs,
                ) from exc
            except Exception as exc:
                self._terminate_repair_routes(
                    run,
                    routes,
                    outcome="escalated",
                    retained_refs=(judge_bundle.report_ref, design.design_ref),
                )
                raise _GenerationHalt(
                    status="failed",
                    code="builder_repair_profile_invalid",
                    summary="The resumable Builder session lacks enforceable per-turn limits.",
                    finding_refs=finding_refs,
                ) from exc
            build_findings = tuple(judge_bundle.report.findings)
            repair_budget = repair_reservation.model_copy(update={"repair_attempts": 1})
            try:
                repair_attempt_id = self._start_attempt(
                    run,
                    "build",
                    (build.candidate_ref, *finding_refs, *directive_refs),
                )
            except Exception as exc:
                self._terminate_repair_routes(
                    run,
                    routes,
                    outcome="escalated",
                    retained_refs=(judge_bundle.report_ref, design.design_ref),
                )
                await self._persist_snapshot(run, status="running")
                raise _GenerationHalt(
                    status="failed",
                    code="builder_repair_attempt_start_failed",
                    summary="Builder repair could not create an atomic NodeAttempt.",
                    finding_refs=finding_refs,
                ) from exc
            repair_work: _AgentInvocationWorkLease | None = None
            repair_action_consumed = False
            try:
                run.ledger.consume(BudgetUsage(repair_attempts=1))
                repair_action_consumed = True
                repair_work = self._reserve_agent_invocation_work(
                    run,
                    attempt_id=repair_attempt_id,
                    requested=repair_reservation,
                    available=repair_remaining,
                )
                await self._persist_snapshot(run, status="running")
                repaired = await self.builder.repair(
                    state=build.state,
                    findings=build_findings,
                    budget=repair_budget,
                )
                repair_actual, repair_unknown = self._builder_invocation_settlement(
                    repaired.invocation,
                    unknown_token_cap=repair_budget.llm_tokens,
                    monetary_upper_bound=repair_budget.monetary_cost,
                    reserved_turns=repair_budget.agent_turns,
                )
                repair_usage = self._settle_agent_invocation_work(
                    run,
                    repair_work,
                    observed_actual=repair_actual,
                    unknown_upper_bound=repair_unknown,
                )
            except BaseException as exc:
                failure_invocation_usage = BudgetUsage()
                if isinstance(exc, BuilderError) and exc.invocation is not None:
                    failure_actual, failure_unknown = self._builder_invocation_settlement(
                        exc.invocation,
                        unknown_token_cap=repair_budget.llm_tokens,
                        monetary_upper_bound=repair_budget.monetary_cost,
                        reserved_turns=repair_budget.agent_turns,
                    )
                    if repair_work is None:
                        raise RuntimeError(
                            "Builder invocation evidence exists without a persisted repair lease"
                        ) from exc
                    failure_invocation_usage = self._settle_agent_invocation_work(
                        run,
                        repair_work,
                        observed_actual=failure_actual,
                        unknown_upper_bound=failure_unknown,
                    )
                elif repair_work is not None:
                    failure_invocation_usage = self._settle_agent_invocation_work(
                        run,
                        repair_work,
                        observed_actual=BudgetUsage(),
                        unknown_upper_bound=self._agent_invocation_unknown(
                            repair_reservation,
                            include_build_time=True,
                        ),
                    )
                failure_usage = self._add_usage(
                    BudgetUsage(repair_attempts=1 if repair_action_consumed else 0),
                    failure_invocation_usage,
                )
                if isinstance(exc, asyncio.CancelledError):
                    repair_status: Literal["failed", "needs_human", "budget_exhausted"] = "failed"
                    code = "builder_repair_cancelled"
                elif isinstance(exc, BudgetExceeded):
                    repair_status = "budget_exhausted"
                    code = "builder_repair_budget_exhausted"
                elif isinstance(exc, BuilderError):
                    repair_status, code = self._invocation_failure_status(
                        (exc.invocation.status if exc.invocation is not None else None),
                        default_code=f"builder_repair_{self._safe_identifier(exc.stage)}",
                    )
                else:
                    repair_status = "failed"
                    code = "builder_repair_infrastructure_error"
                self._finish_attempt(
                    run,
                    repair_attempt_id,
                    status=repair_status,
                    finding_refs=finding_refs,
                    failure_code=code,
                    failure_summary="Same-session Environment Builder repair did not complete.",
                    usage=failure_usage,
                )
                self._terminate_repair_routes(
                    run,
                    routes,
                    outcome=("exhausted" if repair_status == "budget_exhausted" else "escalated"),
                    retained_refs=(judge_bundle.report_ref, design.design_ref),
                    usage=failure_usage,
                )
                await self._persist_snapshot(run, status="running")
                if isinstance(exc, asyncio.CancelledError):
                    raise
                raise _GenerationHalt(
                    status=self._generate_status(repair_status),
                    code=code,
                    summary="Same-session implementation repair stopped without a new candidate.",
                    finding_refs=finding_refs,
                ) from exc
            repair_outputs = (
                repaired.source_snapshot_ref,
                repaired.implementation_lineage_ref,
                repaired.candidate_manifest_ref,
                repaired.build_artifact_ref,
                repaired.candidate_ref,
            )
            run.remember(*repair_outputs)
            invalidated_refs = self._invalidate_artifact_descendants(
                run,
                superseded_refs=(build.candidate_ref,),
                invalidating_refs=(repaired.candidate_ref,),
            )
            self._finish_attempt(
                run,
                repair_attempt_id,
                status="passed",
                output_refs=repair_outputs,
                usage=self._add_usage(
                    BudgetUsage(repair_attempts=1),
                    repair_usage,
                ),
                profile_hash=(
                    f"sha256:{repaired.state.profile.profile_hash}"
                    if repaired.state is not None
                    else None
                ),
                session_id=(
                    self._hashed_session(repaired.session.thread_id)
                    if repaired.session is not None
                    else None
                ),
            )
            await self._persist_snapshot(run, status="running")
            pending = _PendingRepairActions(
                directives=routes,
                session_strategy="continued",
                action_usage=self._add_usage(
                    BudgetUsage(repair_attempts=1),
                    repair_usage,
                ),
                invalidated_refs=invalidated_refs,
            )
            try:
                _, build = await self._integrate_and_repair(
                    run=run,
                    job=job,
                    design=design,
                    build=repaired,
                )
            except BaseException:
                self._terminate_repair_routes(
                    run,
                    pending.directives,
                    outcome="escalated",
                    retained_refs=(repaired.candidate_ref, judge_bundle.report_ref),
                    usage=pending.action_usage,
                )
                pending = None
                await self._persist_snapshot(run, status="running")
                raise

    def _prepare_direct_release_plan(
        self,
        *,
        run: _RunState,
        job: EnvironmentJob,
        request: EnvironmentRequest,
        design: DesignBundle,
    ) -> _ReleasePlan:
        """Bind initial package identity and public provenance before code generation."""

        boundary_hash = design.world_spec.boundary.content_digest()
        world_spec_hash = design.world_spec.content_digest()
        tool_contract_set_hash = sha256_digest(
            canonical_json_bytes(
                [
                    tool.model_dump(mode="json", exclude_none=False)
                    for tool in design.world_spec.tools
                ]
            )
        )
        package_id = f"env:{boundary_hash.removeprefix('sha256:')[:32]}"
        identity = IdentityDecision(
            decision_id=self._stable_id("identity", boundary_hash),
            target_kind="new_package",
            boundary_after_hash=boundary_hash,
            rationale=(
                "Initial Direct Generation has no semantic parent; stable identity derives from "
                "the complete WorldBoundary rather than Runtime source code."
            ),
            confidence=1.0,
        )
        identity_ref = self.artifacts.put_json(
            artifact_id=f"{run.run_id}:identity-decision",
            artifact_type="release.identity_decision",
            value=identity,
            dependencies=(design.world_spec_ref, design.design_ref),
        )
        evidence_refs = self._unique_refs(
            tuple(
                evidence.content_ref
                for evidence in design.evidence_graph.evidence
                if evidence.content_ref is not None
            )
        )
        semantic_delta_hash = sha256_digest(
            canonical_json_bytes(
                {
                    "operator": "initial_generation",
                    "world_boundary_hash": boundary_hash,
                    "world_spec_hash": world_spec_hash,
                    "tool_contract_set_hash": tool_contract_set_hash,
                }
            )
        )
        seed = int(
            hashlib.sha256(f"{job.job_id}\0{design.design_ref.revision_id}".encode()).hexdigest()[
                :16
            ],
            16,
        )
        semantic = SemanticLineage(
            lineage_id=self._stable_id("semantic-lineage", design.design_ref.revision_id),
            evidence_refs=evidence_refs,
            operator_id="initial_generation",
            operator_version="1",
            operator_parameters={"origin": "direct_generate"},
            seed=seed,
            tool_contract_set_after_hash=tool_contract_set_hash,
            world_spec_after_hash=world_spec_hash,
            semantic_delta_hash=semantic_delta_hash,
            identity_decision=identity,
        )
        semantic_ref = self.artifacts.put_json(
            artifact_id=f"{run.run_id}:semantic-lineage",
            artifact_type="release.semantic_lineage",
            value=semantic,
            dependencies=self._unique_refs(
                (identity_ref, design.design_ref, design.world_spec_ref, *evidence_refs)
            ),
        )
        evidence_summary_ref = self._persist_public_evidence_summary(
            run=run,
            design=design,
            origin="direct_generate",
            request_id=request.request_id,
            extra_dependencies=(semantic_ref,),
        )
        return _ReleasePlan(
            package_id=package_id,
            version=_INITIAL_PACKAGE_VERSION,
            identity_ref=identity_ref,
            semantic_lineage=semantic,
            semantic_lineage_ref=semantic_ref,
            evidence_summary_ref=evidence_summary_ref,
        )

    def _prepare_expansion_release_plan(
        self,
        *,
        run: _RunState,
        campaign: ExpansionCampaign,
        intent: MutationIntent,
        primary_manifest: EnvironmentPackageManifest,
        design: ExpansionDesignBundle,
    ) -> _ReleasePlan:
        """Independently enforce semantic identity before Registry reservation."""

        identity = design.identity_decision
        semantic = design.semantic_lineage
        self.artifacts.require_exact_json(
            design.identity_decision_ref,
            identity,
            artifact_types=("expansion.identity_decision",),
        )
        self.artifacts.require_exact_json(
            design.semantic_lineage_ref,
            semantic,
            artifact_types=("expansion.semantic_lineage",),
        )
        if design.design.semantic_lineage_ref != design.semantic_lineage_ref:
            raise ValueError("Expansion design does not bind its exact SemanticLineage")
        if semantic.semantic_parent_refs != intent.parent_refs:
            raise ValueError("SemanticLineage parents differ from the admitted intent")
        if semantic.clue_refs != intent.clue_refs:
            raise ValueError("SemanticLineage clues differ from the admitted intent")
        if (
            semantic.operator_id != intent.operator
            or semantic.operator_version != intent.operator_version
            or semantic.seed != intent.seed
        ):
            raise ValueError("SemanticLineage operator/seed differs from the admitted intent")
        if semantic.world_spec_after_hash != design.world_spec.content_digest():
            raise ValueError("SemanticLineage does not bind the generated WorldSpec")
        if identity.boundary_after_hash != design.world_spec.boundary.content_digest():
            raise ValueError("IdentityDecision does not bind the generated WorldBoundary")
        if len(intent.parent_refs) > 1 and identity.target_kind != "new_package":
            raise ValueError("multi-parent composite candidates must create a new package")

        world_hash = design.world_spec.content_digest()
        boundary_hash = design.world_spec.boundary.content_digest()
        if identity.target_kind == "package_revision":
            if len(intent.parent_refs) != 1:
                raise ValueError("package revisions require exactly one semantic parent")
            if (
                boundary_hash != primary_manifest.world_boundary_hash
                or identity.boundary_before_hash != primary_manifest.world_boundary_hash
                or identity.changed_boundary_dimensions
            ):
                raise ValueError("package revisions must preserve the primary WorldBoundary")
            package_id = primary_manifest.package_id
            minor = max(1, design.world_spec.revision - 1)
            version = f"1.{minor}.0+{world_hash.removeprefix('sha256:')[:12]}"
        else:
            package_id = f"env:{boundary_hash.removeprefix('sha256:')[:32]}"
            version = _INITIAL_PACKAGE_VERSION

        evidence_summary_ref = self._persist_public_evidence_summary(
            run=run,
            design=design,
            origin="expansion_campaign",
            request_id=campaign.campaign_id,
            extra_dependencies=(
                design.semantic_delta_ref,
                design.identity_decision_ref,
                design.semantic_lineage_ref,
            ),
        )
        return _ReleasePlan(
            package_id=package_id,
            version=version,
            identity_ref=design.identity_decision_ref,
            semantic_lineage=semantic,
            semantic_lineage_ref=design.semantic_lineage_ref,
            evidence_summary_ref=evidence_summary_ref,
        )

    def _persist_public_evidence_summary(
        self,
        *,
        run: _RunState,
        design: ExecutableDesignBundle,
        origin: str,
        request_id: str,
        extra_dependencies: tuple[ArtifactRef, ...] = (),
    ) -> ArtifactRef:
        evidence_refs = self._unique_refs(
            tuple(
                evidence.content_ref
                for evidence in design.evidence_graph.evidence
                if evidence.content_ref is not None
            )
        )
        evidence_summary = {
            "format": "agent-world-public-evidence-v2",
            "origin": origin,
            "request_id": request_id,
            "evidence_graph_id": design.evidence_graph.graph_id,
            "evidence_graph_revision": design.evidence_graph.revision,
            "sources": [
                {
                    "evidence_id": item.evidence_id,
                    "source_kind": item.source_kind,
                    "source_uri": item.source_uri,
                    "retrieved_at": item.retrieved_at.isoformat(),
                    "content_hash": item.content_hash,
                    "fetcher": item.fetcher,
                    "fetcher_version": item.fetcher_version,
                    "extractor": item.extractor,
                    "extractor_version": item.extractor_version,
                    "license": item.license,
                    "source_risk": item.source_risk,
                    "observed_summary": item.observed_summary,
                }
                for item in design.evidence_graph.evidence
            ],
            "claims": [
                {
                    "claim_id": claim.claim_id,
                    "kind": claim.kind,
                    "statement": claim.statement,
                    "confidence": claim.confidence,
                    "evidence_ids": list(claim.evidence_ids),
                    "status": claim.status,
                    "risk": claim.risk,
                }
                for claim in design.evidence_graph.claims
            ],
            "unresolved_questions": list(design.evidence_graph.unresolved_questions),
        }
        return self.artifacts.put_json(
            artifact_id=f"{run.run_id}:public-evidence-summary",
            artifact_type="release.public_evidence_summary",
            value=evidence_summary,
            dependencies=self._unique_refs(
                (design.evidence_graph_ref, *evidence_refs, *extra_dependencies)
            ),
        )

    def _reserve_release_coordinate(
        self,
        *,
        run: _RunState,
        package_id: str,
        version: str,
        ttl_seconds: float | None = None,
    ) -> PackageVersionReservation:
        try:
            reservation = self.registry.reserve_package_version(
                package_id,
                version,
                run.job_ref,
                ttl_seconds=ttl_seconds,
                framework_actor=_FRAMEWORK_ACTOR,
            )
        except Exception as exc:
            finding_ref = self._control_failure_finding(
                run,
                node="release",
                event_kind=ControlEventKind.RELEASE_POLICY_FAILURE,
                code="package_version_reservation_rejected",
                error_type=type(exc).__name__,
            )
            raise _GenerationHalt(
                status="failed",
                code="package_version_reservation_rejected",
                summary="Registry could not reserve the framework-decided package coordinate.",
                finding_refs=(finding_ref,),
            ) from exc
        reservation_ref = self.artifacts.put_json(
            artifact_id=self._stable_id(
                "release-reservation",
                reservation.reservation_id,
                reservation.owner_ref.revision_id,
            ),
            artifact_type="release.package_version_reservation",
            value=reservation,
            dependencies=(run.job_ref,),
        )
        run.remember(reservation_ref)
        return reservation

    def _release_reservation_if_active(
        self,
        reservation: PackageVersionReservation,
        owner_ref: ArtifactRef,
    ) -> None:
        """Best-effort terminal cleanup; consumed/cancelled reservations stay auditable."""

        try:
            current = self.registry.inspect_reservation(reservation.reservation_id)
            if current.status == "active":
                self.registry.release_reservation(
                    current.reservation_id,
                    owner_ref,
                    framework_actor=_FRAMEWORK_ACTOR,
                )
        except Exception:
            # The durable TTL remains the final fail-safe.  Never hide the
            # original candidate or publication failure with cleanup noise.
            return

    def _prepare_release_claim_vector(
        self,
        *,
        run: _RunState,
        design: ExecutableDesignBundle,
        build: BuildBundle,
        judge_bundle: JudgeBundle,
    ) -> tuple[
        IntegrationReport,
        ArtifactRef,
        ArtifactRef,
        ArtifactRef,
        ArtifactRef,
    ]:
        """Bind exact final-candidate readiness before any package bytes are compiled."""

        integration_refs = tuple(
            ref
            for attempt in run.attempts
            if attempt.node == "integration"
            and attempt.status == "passed"
            and build.candidate_ref in attempt.input_refs
            for ref in attempt.output_refs
            if ref.artifact_type == "judge.integration_report"
        )
        judge_dependencies = set(self.artifacts.dependencies(judge_bundle.report_ref))
        verifier_refs = tuple(
            ref for ref in judge_dependencies if ref.artifact_type == "judge.verifier_ir_projection"
        )
        modeling_gate_refs = tuple(
            ref
            for attempt in run.attempts
            if attempt.node == "design" and attempt.status == "passed"
            for ref in attempt.output_refs
            if ref.artifact_type == "control.modeling_gate"
            and self.artifacts.get_json(ref, GateResult).subject_ref == design.design_ref
        )
        work_manifest_refs = tuple(
            ref
            for attempt in run.attempts
            if attempt.node == "design" and attempt.status == "passed"
            for ref in attempt.output_refs
            if ref.artifact_type == "control.work_graph_manifest"
        )
        readiness_refs = tuple(
            ref
            for attempt in run.attempts
            if attempt.node == "design" and attempt.status == "passed"
            for ref in attempt.output_refs
            if ref.artifact_type == "control.work_readiness"
        )
        if (
            not integration_refs
            or len(verifier_refs) != 1
            or len(modeling_gate_refs) != 1
            or len(work_manifest_refs) != 1
            or len(readiness_refs) != 1
        ):
            raise _GenerationHalt(
                status="failed",
                code="release_evidence_closure_incomplete",
                summary=(
                    "Release requires one causal Integration result and exactly one Verifier "
                    "revision bound by the final JudgeReport."
                ),
            )
        integration_ref = integration_refs[-1]
        verifier_ref = verifier_refs[0]
        modeling_gate_ref = modeling_gate_refs[0]
        work_manifest_ref = work_manifest_refs[0]
        readiness_ref = readiness_refs[0]
        readiness = self.artifacts.get_json(
            readiness_ref,
            WorkReadinessSnapshot,
        )
        modeling_gate = self.artifacts.get_json(modeling_gate_ref, GateResult)
        if (
            modeling_gate.status != "pass"
            or not modeling_gate.hard
            or readiness.manifest_ref != work_manifest_ref
            or readiness.status != "ready"
            or not readiness.release_candidate_ready
        ):
            raise _GenerationHalt(
                status="failed",
                code="release_modeling_gate_not_final_design",
                summary="The exact final EnvironmentDesign lacks one passing Modeling Gate.",
            )
        integration = self.artifacts.get_json(integration_ref, IntegrationReport)
        self.artifacts.require_exact_json(
            integration_ref,
            integration,
            artifact_types=("judge.integration_report",),
        )
        expected_digest = build.candidate_manifest.candidate_source_tree_digest
        if (
            integration.status != "ready"
            or integration.candidate_ref != build.candidate_ref
            or integration.candidate_source_tree_digest != expected_digest
        ):
            raise _GenerationHalt(
                status="failed",
                code="release_integration_not_final_candidate",
                summary=(
                    "The latest ready IntegrationReport does not bind the exact candidate "
                    "being released."
                ),
            )
        if (
            judge_bundle.report.candidate_ref != build.candidate_ref
            or judge_bundle.report.candidate_source_tree_digest != expected_digest
        ):
            raise _GenerationHalt(
                status="failed",
                code="release_judge_not_final_candidate",
                summary="The passing JudgeReport does not bind the exact final source tree.",
            )
        if self.telemetry is None:
            raise _GenerationHalt(
                status="failed",
                code="release_observability_unavailable",
                summary="Production telemetry is required before envpkg release.",
            )
        self.telemetry.flush()
        inspected = self.telemetry.inspect_trace(run.run_id)
        health = self.telemetry.health()
        spans = inspected["spans"]
        running_spans = tuple(span for span in spans if span["status"] == "running")
        required_nodes = ("request", "design", "verifier", "build", "integration", "judge")
        required_node_attempts = {
            node: sum(
                1
                for span in spans
                if span["operation"] == f"node.{node}" and span["status"] == "passed"
            )
            for node in required_nodes
        }
        invocation_count = sum(
            1
            for span in spans
            if span["operation"] == "agent.invoke" and span["status"] == "passed"
        )
        required_operations = ("research.search", "research.fetch", "research.extract")
        executed_research_attempts = {
            operation: sum(
                1 for span in spans if span["operation"] == operation and span["status"] == "passed"
            )
            for operation in required_operations
        }
        checkpoint_reuse_count = sum(
            1
            for span in spans
            if span["operation"] == "research.checkpoint_reuse" and span["status"] == "passed"
        )
        required_operation_attempts = (
            executed_research_attempts
            if all(executed_research_attempts.values())
            else {"research.checkpoint_reuse": checkpoint_reuse_count}
        )
        research_provenance_refs: tuple[ArtifactRef, ...] = ()
        if set(required_operation_attempts) == {"research.checkpoint_reuse"}:
            research_provenance_refs = (
                self._persist_research_checkpoint_reuse_evidence(
                    run=run,
                    design=design,
                    modeling_gate_ref=modeling_gate_ref,
                ),
            )
        required_metrics = (
            "invocation.tokens.total",
            "research.search.calls",
            "research.fetch.calls",
            "research.documents.extracted",
        )
        required_metric_observations = {
            name: sum(1 for metric in inspected["metrics"] if metric["name"] == name)
            for name in required_metrics
        }
        if (
            health.get("journal_mode") != "wal"
            or not spans
            or run.telemetry_root_span is None
            or len(running_spans) != 1
            or running_spans[0]["span_id"] != run.telemetry_root_span.span_id
            or any(count < 1 for count in required_node_attempts.values())
            or invocation_count < 1
            or not required_operation_attempts
            or any(count < 1 for count in required_operation_attempts.values())
            or any(count < 1 for count in required_metric_observations.values())
            or run.telemetry_node_spans
        ):
            raise _GenerationHalt(
                status="failed",
                code="release_observability_unhealthy",
                summary=(
                    "Release telemetry must have one open root, closed required nodes, at least "
                    "one real Agent invocation, complete research operations/metrics and no "
                    "leaked node span."
                ),
            )
        unknown_measurement_count = sum(
            int(count) for count in inspected["summary"]["unknown_measurements"].values()
        )
        telemetry_summary = TelemetryReleaseSummary(
            trace_id=run.run_id,
            run_id=run.run_id,
            collected_at=datetime.now(UTC),
            cut_stage="pre_publish",
            as_of_ns=int(inspected["summary"]["as_of_ns"]),
            open_span_count=int(inspected["summary"]["open_span_count"]),
            provisional=bool(inspected["summary"]["provisional"]),
            journal_mode="wal",
            span_count=len(spans),
            metric_count=len(inspected["metrics"]),
            event_count=len(inspected["events"]),
            invocation_count=invocation_count,
            required_node_attempts=required_node_attempts,
            required_operation_attempts=required_operation_attempts,
            required_metric_observations=required_metric_observations,
            research_provenance_refs=research_provenance_refs,
            unknown_measurement_count=unknown_measurement_count,
            summary=inspected["summary"],
            summary_digest=sha256_digest(canonical_json_bytes(inspected["summary"])),
        )
        telemetry_ref = self.artifacts.put_json(
            artifact_id=f"{run.run_id}:telemetry-release-summary",
            artifact_type="release.telemetry_summary",
            value=telemetry_summary,
            dependencies=(
                run.job_ref,
                build.candidate_ref,
                judge_bundle.report_ref,
                *research_provenance_refs,
            ),
        )
        observability_feedback_ref = self._record_feedback_result(
            contract_id="feedback.controller.observability",
            status="passed",
            subject_ref=telemetry_ref,
            evidence_refs=(telemetry_ref, *research_provenance_refs),
            summary="Sanitized telemetry covers every required pre-release operation.",
        )
        run.remember(observability_feedback_ref)
        evaluated_at = datetime.now(UTC)
        design_claim_id, design_effect = self._release_feedback_claim_policy(
            "feedback.design.modeling_gate"
        )
        build_claim_id, build_effect = self._release_feedback_claim_policy(
            "feedback.build.candidate"
        )
        verifier_claim_id, verifier_effect = self._release_feedback_claim_policy(
            "feedback.verifier.intent"
        )
        integration_claim_id, integration_effect = self._release_feedback_claim_policy(
            "feedback.integration.runtime"
        )
        judge_claim_id, judge_effect = self._release_feedback_claim_policy("feedback.judge.release")
        observability_claim_id, observability_effect = self._release_feedback_claim_policy(
            "feedback.controller.observability"
        )
        claims = (
            claim(
                claim_id=design_claim_id,
                subject_ref=design.design_ref,
                producer=_FRAMEWORK_ACTOR,
                status="passed",
                effect=design_effect,
                summary="The exact EnvironmentDesign passed framework modeling gates.",
                evidence_refs=(modeling_gate_ref, work_manifest_ref, readiness_ref),
                dependency_refs=(
                    design.design_ref,
                    design.world_spec_ref,
                    work_manifest_ref,
                    readiness_ref,
                ),
                evaluated_at=evaluated_at,
            ),
            claim(
                claim_id=build_claim_id,
                subject_ref=build.candidate_ref,
                producer=_FRAMEWORK_ACTOR,
                status="passed",
                effect=build_effect,
                summary="Builder committed a closed candidate source tree.",
                evidence_refs=(build.build_artifact_ref, build.candidate_manifest_ref),
                dependency_refs=(design.design_ref,),
                evaluated_at=evaluated_at,
            ),
            claim(
                claim_id="runtime.executable",
                subject_ref=build.candidate_ref,
                producer=_FRAMEWORK_ACTOR,
                status="passed",
                effect="block_integration",
                summary="Clean host install/start/reset/invoke execution passed.",
                evidence_refs=(integration_ref,),
                dependency_refs=(build.candidate_ref,),
                evaluated_at=evaluated_at,
            ),
            claim(
                claim_id=integration_claim_id,
                subject_ref=build.candidate_ref,
                producer=_FRAMEWORK_ACTOR,
                status="passed",
                effect=integration_effect,
                summary="All Integration gates passed for the exact final source tree.",
                evidence_refs=(integration_ref,),
                dependency_refs=(build.candidate_ref,),
                evaluated_at=evaluated_at,
            ),
            claim(
                claim_id=verifier_claim_id,
                subject_ref=build.candidate_ref,
                producer=_FRAMEWORK_ACTOR,
                status="passed",
                effect=verifier_effect,
                summary="Framework-expanded Verifier IR is bound to the release Judge.",
                evidence_refs=(verifier_ref,),
                dependency_refs=(design.design_ref, design.world_spec_ref),
                evaluated_at=evaluated_at,
            ),
            claim(
                claim_id=judge_claim_id,
                subject_ref=build.candidate_ref,
                producer=_FRAMEWORK_ACTOR,
                status="passed",
                effect=judge_effect,
                summary="Independent release Judge passed every required hard gate.",
                evidence_refs=(judge_bundle.report_ref,),
                dependency_refs=(integration_ref, verifier_ref),
                evaluated_at=evaluated_at,
            ),
            claim(
                claim_id=observability_claim_id,
                subject_ref=build.candidate_ref,
                producer=_FRAMEWORK_ACTOR,
                status="passed",
                effect=observability_effect,
                summary="Durable sanitized execution telemetry exists for the release path.",
                evidence_refs=(telemetry_ref,),
                dependency_refs=(run.job_ref,),
                evaluated_at=evaluated_at,
            ),
        )
        maturity, blockers = reduce_maturity(claims)
        if maturity != "release_candidate" or blockers:
            raise _GenerationHalt(
                status="failed",
                code="release_claim_vector_not_ready",
                summary="Framework-derived release claims did not reach RELEASE_CANDIDATE.",
            )
        vector = ClaimVector(
            vector_id=self._stable_id(
                "claim-vector",
                build.candidate_ref.revision_id,
                judge_bundle.report_ref.revision_id,
            ),
            revision=1,
            design_ref=design.design_ref,
            candidate_ref=build.candidate_ref,
            integration_ref=integration_ref,
            verifier_ref=verifier_ref,
            release_judge_ref=judge_bundle.report_ref,
            telemetry_ref=telemetry_ref,
            claims=claims,
            maturity=maturity,
            blocking_claim_ids=blockers,
        )
        claim_vector_ref = self.artifacts.put_json(
            artifact_id=f"{run.run_id}:release-claim-vector",
            artifact_type="release.claim_vector",
            value=vector,
            dependencies=self._unique_refs(
                (
                    design.design_ref,
                    design.world_spec_ref,
                    modeling_gate_ref,
                    run.job_ref,
                    build.candidate_ref,
                    build.candidate_manifest_ref,
                    build.build_artifact_ref,
                    integration_ref,
                    verifier_ref,
                    judge_bundle.report_ref,
                    telemetry_ref,
                )
            ),
        )
        run.remember(integration_ref, verifier_ref, telemetry_ref, claim_vector_ref)
        return integration, integration_ref, verifier_ref, telemetry_ref, claim_vector_ref

    @staticmethod
    def _release_feedback_claim_policy(
        contract_id: str,
    ) -> tuple[
        str,
        Literal[
            "observe",
            "reject_revision",
            "block_integration",
            "block_release",
            "quarantine",
        ],
    ]:
        """Compile release Claim policy from the executable feedback catalog."""

        contract = PRODUCTION_FEEDBACK.require(contract_id)
        effect = "observe" if contract.effect == "evidence_only" else contract.effect
        if effect not in {
            "observe",
            "reject_revision",
            "block_integration",
            "block_release",
            "quarantine",
        }:
            raise ValueError(
                f"feedback contract {contract_id} cannot produce a release Claim effect"
            )
        return contract.claim_id, cast(
            Literal[
                "observe",
                "reject_revision",
                "block_integration",
                "block_release",
                "quarantine",
            ],
            effect,
        )

    def _persist_research_checkpoint_reuse_evidence(
        self,
        *,
        run: _RunState,
        design: ExecutableDesignBundle,
        modeling_gate_ref: ArtifactRef,
    ) -> ArtifactRef:
        """Commit the exact checkpoint chain that replaced external research."""

        reused = run.research_checkpoint_reuse
        if reused is None:
            raise _GenerationHalt(
                status="failed",
                code="research_checkpoint_provenance_missing",
                summary="Research reuse telemetry has no validated checkpoint binding.",
            )
        checkpoint_ref, evidence_graph_ref = reused
        job = self.artifacts.get_json(run.job_ref, EnvironmentJob)
        self.artifacts.require_exact_json(
            run.job_ref,
            job,
            artifact_types=("control.environment_job",),
        )
        if job.kind != "generate" or job.request_ref is None:
            raise _GenerationHalt(
                status="failed",
                code="research_checkpoint_job_invalid",
                summary="Only a Direct Generation job can adopt a research checkpoint.",
            )
        if evidence_graph_ref != design.design.evidence_graph_ref:
            raise _GenerationHalt(
                status="failed",
                code="research_checkpoint_not_final_design",
                summary="Adopted research does not feed the final EnvironmentDesign.",
            )
        if checkpoint_ref.artifact_type == "control.job_run_snapshot":
            snapshot = self.artifacts.get_json(checkpoint_ref, JobRunSnapshot)
            self.artifacts.require_exact_json(
                checkpoint_ref,
                snapshot,
                artifact_types=("control.job_run_snapshot",),
            )
            checkpoint_valid = (
                snapshot.job_ref == run.job_ref
                and evidence_graph_ref in snapshot.latest_artifact_refs
            )
        else:
            checkpoint_valid = False
        gate = self.artifacts.get_json(modeling_gate_ref, GateResult)
        if (
            not checkpoint_valid
            or gate.status != "pass"
            or not gate.hard
            or gate.subject_ref != design.design_ref
        ):
            raise _GenerationHalt(
                status="failed",
                code="research_checkpoint_provenance_invalid",
                summary="Research checkpoint bindings do not close over the final design.",
            )
        evidence = ResearchCheckpointReuseEvidence(
            adoption_id=self._stable_id(
                "research-checkpoint-reuse",
                run.run_id,
                checkpoint_ref.revision_id,
            ),
            run_id=run.run_id,
            job_ref=run.job_ref,
            request_ref=job.request_ref,
            checkpoint_ref=checkpoint_ref,
            evidence_graph_ref=evidence_graph_ref,
            final_design_ref=design.design_ref,
            modeling_gate_ref=modeling_gate_ref,
            adopted_at=datetime.now(UTC),
        )
        ref = self.artifacts.put_json(
            artifact_id=f"{run.run_id}:research-checkpoint-reuse-evidence",
            artifact_type="control.research_checkpoint_reuse_evidence",
            value=evidence,
            dependencies=(
                run.job_ref,
                job.request_ref,
                checkpoint_ref,
                evidence_graph_ref,
                design.design_ref,
                modeling_gate_ref,
            ),
        )
        run.remember(ref)
        return ref

    def _persist_final_telemetry_summary(
        self,
        run: _RunState,
        *,
        dependencies: tuple[ArtifactRef, ...],
    ) -> ArtifactRef:
        """Commit the complete terminal trace after Registry publication succeeds."""

        if self.telemetry is None:
            raise ValueError("final telemetry summary requires TelemetryStore")
        self.telemetry.flush()
        inspected = self.telemetry.inspect_trace(run.run_id)
        health = self.telemetry.health()
        if health.get("journal_mode") != "wal":
            raise ValueError("final telemetry WAL is unhealthy")
        spans = inspected["spans"]
        if any(span["status"] == "running" for span in spans):
            raise ValueError("final telemetry contains a running span")
        required_nodes = (
            "request",
            "design",
            "verifier",
            "build",
            "integration",
            "judge",
            "release",
        )
        node_counts = {
            node: sum(
                1
                for span in spans
                if span["operation"] == f"node.{node}" and span["status"] == "passed"
            )
            for node in required_nodes
        }
        invocation_count = sum(
            1
            for span in spans
            if span["operation"] == "agent.invoke" and span["status"] == "passed"
        )
        required_operations = ("research.search", "research.fetch", "research.extract")
        executed_operation_counts = {
            operation: sum(
                1 for span in spans if span["operation"] == operation and span["status"] == "passed"
            )
            for operation in required_operations
        }
        checkpoint_reuse_count = sum(
            1
            for span in spans
            if span["operation"] == "research.checkpoint_reuse" and span["status"] == "passed"
        )
        operation_counts = (
            executed_operation_counts
            if all(executed_operation_counts.values())
            else {"research.checkpoint_reuse": checkpoint_reuse_count}
        )
        research_provenance_refs = tuple(
            ref
            for ref in run.latest.values()
            if ref.artifact_type == "control.research_checkpoint_reuse_evidence"
        )
        required_metrics = (
            "invocation.tokens.total",
            "research.search.calls",
            "research.fetch.calls",
            "research.documents.extracted",
        )
        metric_counts = {
            name: sum(1 for metric in inspected["metrics"] if metric["name"] == name)
            for name in required_metrics
        }
        if (
            any(count < 1 for count in node_counts.values())
            or invocation_count < 1
            or not operation_counts
            or any(count < 1 for count in operation_counts.values())
            or any(count < 1 for count in metric_counts.values())
        ):
            raise ValueError("final telemetry does not cover the complete released path")
        summary = TelemetryReleaseSummary(
            trace_id=run.run_id,
            run_id=run.run_id,
            collected_at=datetime.now(UTC),
            cut_stage="post_publish",
            as_of_ns=int(inspected["summary"]["as_of_ns"]),
            open_span_count=int(inspected["summary"]["open_span_count"]),
            provisional=bool(inspected["summary"]["provisional"]),
            span_count=len(spans),
            metric_count=len(inspected["metrics"]),
            event_count=len(inspected["events"]),
            invocation_count=invocation_count,
            required_node_attempts=node_counts,
            required_operation_attempts=operation_counts,
            required_metric_observations=metric_counts,
            research_provenance_refs=research_provenance_refs,
            unknown_measurement_count=sum(
                int(count) for count in inspected["summary"]["unknown_measurements"].values()
            ),
            summary=inspected["summary"],
            summary_digest=sha256_digest(canonical_json_bytes(inspected["summary"])),
        )
        return self.artifacts.put_json(
            artifact_id=f"{run.run_id}:final-telemetry-summary",
            artifact_type="release.final_telemetry_summary",
            value=summary,
            dependencies=self._unique_refs((run.job_ref, *dependencies, *research_provenance_refs)),
        )

    def _ensure_final_telemetry_summary(
        self,
        run: _RunState,
        *,
        dependencies: tuple[ArtifactRef, ...],
    ) -> ArtifactRef:
        """Recover or create the unique post-publish telemetry checkpoint."""

        artifact_id = f"{run.run_id}:final-telemetry-summary"
        for ref in self.artifacts.list_revisions(artifact_id):
            summary = self.artifacts.get_json(ref, TelemetryReleaseSummary)
            self.artifacts.require_exact_json(
                ref,
                summary,
                artifact_types=("release.final_telemetry_summary",),
            )
            expected_dependencies = set(
                self._unique_refs(
                    (
                        run.job_ref,
                        *dependencies,
                        *summary.research_provenance_refs,
                    )
                )
            )
            if (
                summary.run_id == run.run_id
                and summary.trace_id == run.run_id
                and summary.cut_stage == "post_publish"
                and not summary.provisional
                and summary.open_span_count == 0
                and set(self.artifacts.dependencies(ref)) == expected_dependencies
            ):
                run.remember(ref)
                return ref
        if self.telemetry is None:
            raise ValueError("post-publish telemetry recovery requires TelemetryStore")
        self.telemetry.reconcile_released_trace(
            run.run_id,
            output_refs=dependencies,
        )
        ref = self._persist_final_telemetry_summary(run, dependencies=dependencies)
        run.remember(ref)
        return ref

    def _release(
        self,
        *,
        run: _RunState,
        job: EnvironmentJob,
        design: ExecutableDesignBundle,
        build: BuildBundle,
        judge_bundle: JudgeBundle,
        plan: _ReleasePlan,
        reservation: PackageVersionReservation,
    ) -> tuple[ArtifactRef, ArtifactRef, ReleaseRecord]:
        open_repairs = tuple(
            entry.entry_id for entry in run.repair_ledger.entries if entry.outcome == "authorized"
        )
        if open_repairs:
            raise _GenerationHalt(
                status="failed",
                code="release_repair_ledger_open",
                summary="Release refused while RepairLedger contains unclosed authorizations.",
            )
        if judge_bundle.report.verdict != "pass":
            raise _GenerationHalt(
                status="failed",
                code="release_without_judge_pass",
                summary="Controller refused release without a passing JudgeReport.",
            )
        (
            integration_report,
            integration_report_ref,
            verifier_ref,
            telemetry_summary_ref,
            claim_vector_ref,
        ) = self._prepare_release_claim_vector(
            run=run,
            design=design,
            build=build,
            judge_bundle=judge_bundle,
        )
        attempt_id = self._start_attempt(
            run,
            "release",
            (
                build.candidate_ref,
                judge_bundle.report_ref,
                integration_report_ref,
                verifier_ref,
                telemetry_summary_ref,
                claim_vector_ref,
            ),
        )
        boundary_hash = design.world_spec.boundary.content_digest()
        world_spec_hash = design.world_spec.content_digest()
        lineage = PackageLineage(
            semantic=plan.semantic_lineage,
            implementation=build.implementation_lineage,
        )
        framework_payloads = compile_framework_package_payloads(
            design.design,
            package_id=plan.package_id,
            version=plan.version,
            candidate_manifest=build.candidate_manifest,
            judge_report=judge_bundle.report,
            integration_report=integration_report,
            lineage=lineage,
            design_ref=design.design_ref,
            world_spec_ref=design.world_spec_ref,
            candidate_ref=build.candidate_ref,
            candidate_manifest_ref=build.candidate_manifest_ref,
            build_record_ref=build.build_artifact_ref,
            implementation_lineage_ref=build.implementation_lineage_ref,
            judge_report_ref=judge_bundle.report_ref,
            integration_report_ref=integration_report_ref,
            release_dossier_ref=claim_vector_ref,
            telemetry_summary_ref=telemetry_summary_ref,
            pyproject_bytes=(build.project_root / "pyproject.toml").read_bytes(),
            uv_lock_bytes=(build.project_root / "uv.lock").read_bytes(),
        )
        manifest = EnvironmentPackageManifest(
            package_id=plan.package_id,
            version=plan.version,
            created_at=datetime.now(UTC),
            world_boundary_hash=boundary_hash,
            world_spec_hash=world_spec_hash,
            candidate_source_tree_digest=(build.candidate_manifest.candidate_source_tree_digest),
            design_ref=design.design_ref,
            world_spec_ref=design.world_spec_ref,
            candidate_ref=build.candidate_ref,
            candidate_manifest_ref=build.candidate_manifest_ref,
            build_record_ref=build.build_artifact_ref,
            implementation_lineage_ref=build.implementation_lineage_ref,
            judge_report_ref=judge_bundle.report_ref,
            integration_report_ref=integration_report_ref,
            release_dossier_ref=claim_vector_ref,
            telemetry_summary_ref=telemetry_summary_ref,
            runtime=build.candidate.runtime,
            task_materializer=build.candidate.task_materializer,
            trusted_evaluator=TrustedEvaluatorDescriptor(),
            public_self_check=build.candidate.public_self_check,
            public_verifier_ref=build.candidate.public_verifier_ref,
            files=(
                *build.candidate_manifest.files,
                *(payload.descriptor() for payload in framework_payloads),
            ),
            lineage=lineage,
            known_limits=build.candidate_manifest.known_limits,
        )
        manifest_dependencies = self._unique_refs(
            (
                design.design_ref,
                design.world_spec_ref,
                build.candidate_ref,
                build.candidate_manifest_ref,
                build.build_artifact_ref,
                build.candidate.public_verifier_ref,
                build.candidate.task_materializer.output_schema_ref,
                build.candidate.task_materializer.curriculum_ref,
                build.implementation_lineage_ref,
                build.source_snapshot_ref,
                judge_bundle.report_ref,
                integration_report_ref,
                claim_vector_ref,
                telemetry_summary_ref,
                verifier_ref,
                plan.identity_ref,
                plan.semantic_lineage_ref,
                plan.evidence_summary_ref,
            )
        )
        manifest_ref = self.artifacts.put_json(
            artifact_id=self._stable_id(
                "manifest",
                plan.package_id,
                plan.version,
            ),
            artifact_type="environment_package_manifest",
            value=manifest,
            dependencies=manifest_dependencies,
        )
        try:
            prepared = self.registry.prepare(
                candidate_workspace=build.project_root,
                manifest_ref=manifest_ref,
                judge_report_ref=judge_bundle.report_ref,
                release_profile=job.release_profile,
                reservation=reservation,
                framework_payloads=framework_payloads,
                framework_actor=_FRAMEWORK_ACTOR,
            )
            release = self._publish_registry_release(
                prepared=prepared,
                job_ref=run.job_ref,
                manifest_ref=manifest_ref,
            )
        except Exception as exc:
            cleanup_error_type: str | None = None
            if reservation.status == "active":
                try:
                    self.registry.release_reservation(
                        reservation.reservation_id,
                        run.job_ref,
                        framework_actor=_FRAMEWORK_ACTOR,
                    )
                except Exception as cleanup_exc:
                    # Preserve the publication failure. The durable reservation has a bounded
                    # expiry and remains inspectable when cleanup itself cannot complete.
                    cleanup_error_type = type(cleanup_exc).__name__
            error_type = type(exc).__name__
            if cleanup_error_type is not None:
                error_type = f"{error_type}_reservation_cleanup_{cleanup_error_type}"
            finding_ref = self._control_failure_finding(
                run,
                node="release",
                event_kind=ControlEventKind.RELEASE_POLICY_FAILURE,
                code="registry_release_rejected",
                error_type=error_type,
                subject_ref=manifest_ref,
            )
            self._finish_attempt(
                run,
                attempt_id,
                status="failed",
                finding_refs=(finding_ref,),
                failure_code="registry_release_rejected",
                failure_summary="Registry rejected or failed the prepared release.",
            )
            raise _GenerationHalt(
                status="failed",
                code="registry_release_rejected",
                summary="Registry did not publish the candidate.",
                finding_refs=(finding_ref,),
            ) from exc
        release_ref = self.artifacts.put_json(
            artifact_id=f"{run.run_id}:release-record",
            artifact_type="release.record",
            value=release,
            dependencies=(manifest_ref, judge_bundle.report_ref, build.candidate_ref),
        )
        registry_feedback_ref = self._record_feedback_result(
            contract_id="feedback.registry.publish",
            status="passed",
            subject_ref=release_ref,
            evidence_refs=(manifest_ref, release_ref),
            summary="Registry committed and re-read the exact verified environment package.",
        )
        run.remember(
            plan.identity_ref,
            plan.semantic_lineage_ref,
            plan.evidence_summary_ref,
            manifest_ref,
            release_ref,
            registry_feedback_ref,
        )
        self._finish_attempt(
            run,
            attempt_id,
            status="passed",
            output_refs=(manifest_ref, release_ref),
        )
        return manifest_ref, release_ref, release

    def _publish_registry_release(
        self,
        *,
        prepared: PreparedRelease,
        job_ref: ArtifactRef,
        manifest_ref: ArtifactRef,
    ) -> ReleaseRecord:
        """Converge on Registry truth across the publish commit-point window."""

        try:
            return self.registry.publish(prepared)
        except Exception as exc:
            committed = self._registry_release_for_direct_job(job_ref)
            if committed is None:
                raise
            if (
                committed.reservation_owner_ref != job_ref
                or committed.manifest_ref != manifest_ref
                or committed.coordinate != prepared.coordinate
            ):
                raise DirectJobStoreError(
                    "Registry committed a different release during publication recovery"
                ) from exc
            return committed

    def _persist_judge_findings(
        self,
        *,
        run: _RunState,
        judge_bundle: JudgeBundle,
        ordinal: int,
    ) -> tuple[ArtifactRef, ...]:
        return tuple(
            self.artifacts.put_json(
                artifact_id=f"{run.run_id}:finding:{ordinal}:{index}",
                artifact_type="control.finding",
                value=finding,
                dependencies=self._unique_refs((judge_bundle.report_ref, *finding.evidence_refs)),
            )
            for index, finding in enumerate(judge_bundle.report.findings)
        )

    def _persist_integration_findings(
        self,
        *,
        run: _RunState,
        integration_bundle: IntegrationBundle,
        ordinal: int,
    ) -> tuple[ArtifactRef, ...]:
        return tuple(
            self.artifacts.put_json(
                artifact_id=f"{run.run_id}:integration-finding:{ordinal}:{index}",
                artifact_type="control.finding",
                value=finding,
                dependencies=self._unique_refs(
                    (integration_bundle.report_ref, *finding.evidence_refs)
                ),
            )
            for index, finding in enumerate(integration_bundle.report.findings)
        )

    def _persist_repair_ledger_entries(
        self,
        run: _RunState,
        directives: Sequence[RepairDirective],
    ) -> tuple[ArtifactRef, ...]:
        """Persist every global repair authorization before its directive executes."""

        entries = {item.entry_id: item for item in run.repair_ledger.entries}
        refs: list[ArtifactRef] = []
        for directive in directives:
            if directive.ledger_entry_id is None:
                raise ValueError("RepairDirective is missing its global ledger entry")
            entry = entries.get(directive.ledger_entry_id)
            if entry is None:
                raise ValueError("RepairDirective references an unknown global ledger entry")
            refs.append(self._persist_repair_ledger_entry(run, entry))
        return tuple(refs)

    def _persist_repair_ledger_entry(
        self,
        run: _RunState,
        entry: RepairLedgerEntry,
    ) -> ArtifactRef:
        dependencies = self._unique_refs(
            (
                entry.finding_ref,
                *entry.related_finding_refs,
                *entry.causal_evidence_refs,
                *((entry.resolved_owner_ref,) if entry.resolved_owner_ref else ()),
            )
        )
        ref = self.artifacts.put_json(
            artifact_id=f"{run.run_id}:repair-ledger:{entry.entry_id}",
            artifact_type="control.repair_ledger_entry",
            value=entry,
            dependencies=dependencies,
        )
        run.remember(ref)
        if self.telemetry is not None:
            self.telemetry.record_event(
                trace_id=run.run_id,
                span_id=(
                    run.telemetry_root_span.span_id if run.telemetry_root_span is not None else None
                ),
                event_type=(
                    "repair.authorized" if entry.outcome == "authorized" else "repair.completed"
                ),
                payload={
                    "entry_id": entry.entry_id,
                    "current_node": entry.current_node,
                    "target_node": entry.target_node,
                    "jump_distance": entry.jump_distance,
                    "attempt_ordinal": entry.attempt_ordinal,
                    "outcome": entry.outcome,
                },
            )
        self._maybe_persist_error_audit(run)
        return ref

    def _maybe_persist_error_audit(self, run: _RunState) -> ArtifactRef | None:
        """Persist a global diagnosis after bounded error/time/no-progress triggers."""

        decision = self.error_audit_policy.evaluate(
            run.repair_ledger.entries,
            last_audited_entry_count=run.last_error_audit_entry_count,
            seconds_since_last_audit=max(
                0.0,
                time.monotonic() - run.last_error_audit_monotonic,
            ),
        )
        if not decision.triggered:
            return None
        run.error_audit_sequence += 1
        dependencies = self._unique_refs(
            (
                run.job_ref,
                *(
                    ref
                    for ref in run.latest.values()
                    if ref.artifact_type == "control.repair_ledger_entry"
                ),
            )
        )
        ref = self.artifacts.put_json(
            artifact_id=f"{run.run_id}:error-audit:{run.error_audit_sequence}",
            artifact_type="control.error_audit_snapshot",
            value={
                "schema_version": "agent-world.error-audit-snapshot.v1",
                "run_id": run.run_id,
                "created_at": datetime.now(UTC).isoformat(),
                **decision.persistence_projection(),
            },
            dependencies=dependencies,
        )
        run.remember(ref)
        run.last_error_audit_entry_count = len(run.repair_ledger.entries)
        run.last_error_audit_monotonic = time.monotonic()
        if self.telemetry is not None:
            self.telemetry.record_event(
                trace_id=run.run_id,
                span_id=(
                    run.telemetry_root_span.span_id if run.telemetry_root_span is not None else None
                ),
                event_type="error.audit_snapshot",
                payload={
                    "sequence": run.error_audit_sequence,
                    "trigger_codes": ",".join(decision.trigger_codes),
                    "repair_entry_count": decision.repair_entry_count,
                    "no_progress_count": decision.no_progress_count,
                },
            )
        return ref

    def _terminate_repair_routes(
        self,
        run: _RunState,
        routes: Sequence[RepairDirective],
        *,
        outcome: Literal["escalated", "exhausted", "rejected"],
        retained_refs: tuple[ArtifactRef, ...] = (),
        usage: BudgetUsage | None = None,
    ) -> None:
        """Make every unexecuted authorization terminal before leaving a node."""

        entries = {item.entry_id: item for item in run.repair_ledger.entries}
        for route in routes:
            if route.ledger_entry_id is None:
                raise ValueError("RepairDirective is missing its global ledger entry")
            current = entries.get(route.ledger_entry_id)
            if current is None:
                raise ValueError("RepairDirective references an unknown global ledger entry")
            if current.outcome == "authorized":
                run.repair_ledger.terminate(
                    route.ledger_entry_id,
                    outcome=outcome,
                    retained_refs=retained_refs,
                    usage=usage,
                )
        self._persist_repair_ledger_entries(run, routes)

    def _structured_repair_authority(
        self,
        run: _RunState,
    ) -> StructuredRepairAuthority:
        return _ControllerStructuredRepairAuthority(self, run)

    async def _authorize_structured_repair(
        self,
        run: _RunState,
        *,
        owner_node: Literal["design", "verifier", "build", "judge"],
        lineage_id: str,
        role: str,
        repair_mode: StructuredRepairMode,
        issue_codes: tuple[str, ...],
        continued_session: bool,
        diagnostic: ValidationDiagnostic | None = None,
        feedback_contract_id: str | None = None,
        repair_target: RepairTargetRef | None = None,
    ) -> str:
        if (feedback_contract_id is None) != (repair_target is None):
            raise StructuredRepairDenied("feedback_contract_target_binding_incomplete")
        feedback_contract = None
        if feedback_contract_id is not None and repair_target is not None:
            try:
                feedback_contract = PRODUCTION_FEEDBACK.require_for_target(
                    feedback_contract_id,
                    repair_target,
                )
            except ValueError as exc:
                raise StructuredRepairDenied("feedback_contract_target_mismatch") from exc
            if feedback_contract.repair_owner_component != owner_node:
                raise StructuredRepairDenied("feedback_contract_node_mismatch")
        active_structured_authorizations = sum(
            entry.outcome == "authorized" and entry.current_node == entry.target_node
            for entry in run.repair_ledger.entries
        )
        if run.ledger.remaining.repair_attempts <= active_structured_authorizations:
            raise StructuredRepairDenied("global_repair_budget_exhausted")
        safe_role = self._safe_identifier(role)
        safe_mode = repair_mode.value
        safe_issues = tuple(dict.fromkeys(self._safe_identifier(item) for item in issue_codes)) or (
            "structured_contract_violation",
        )
        if diagnostic is not None:
            if diagnostic.owner_component != owner_node:
                raise StructuredRepairDenied("diagnostic_owner_mismatch")
            diagnostic_issues = tuple(
                dict.fromkeys(self._safe_identifier(item) for item in diagnostic.issue_codes)
            )
            if diagnostic_issues != safe_issues:
                raise StructuredRepairDenied("diagnostic_issue_set_mismatch")
        issue_set_digest = sha256_digest(canonical_json_bytes(safe_issues))
        ordinal = len(run.repair_ledger.entries) + 1
        repair_target_ref: ArtifactRef | None = None
        if repair_target is not None:
            repair_target_ref = self.artifacts.put_json(
                artifact_id=f"{run.run_id}:repair-target:{ordinal}",
                artifact_type="control.repair_target",
                value=repair_target,
                dependencies=repair_target.immutable_input_refs or (run.job_ref,),
            )
        fingerprint = sha256_digest(
            canonical_json_bytes(
                {
                    "run_id": run.run_id,
                    "repair_target_key": (
                        repair_target.target_key if repair_target is not None else None
                    ),
                    "lineage_id": self._safe_identifier(lineage_id),
                    "role": safe_role,
                    "repair_mode": safe_mode,
                }
            )
        )
        evidence_ref = self.artifacts.put_json(
            artifact_id=f"{run.run_id}:structured-repair-evidence:{ordinal}",
            artifact_type="control.structured_repair_evidence",
            value={
                "run_id": run.run_id,
                "lineage_id": self._safe_identifier(lineage_id),
                "role": safe_role,
                "repair_mode": safe_mode,
                "issue_codes": safe_issues,
                "issue_set_digest": issue_set_digest,
                "continued_session": continued_session,
                "feedback_contract_id": feedback_contract_id,
                "repair_target_ref": (
                    repair_target_ref.model_dump(mode="json")
                    if repair_target_ref is not None
                    else None
                ),
                "diagnostic": (
                    diagnostic.persistence_projection() if diagnostic is not None else None
                ),
            },
            dependencies=self._unique_refs(
                (run.job_ref, *((repair_target_ref,) if repair_target_ref is not None else ()))
            ),
        )
        feedback_result_ref: ArtifactRef | None = None
        if feedback_contract is not None and repair_target is not None:
            feedback_result = FeedbackResult(
                result_id=self._stable_id(
                    "feedback-result",
                    run.run_id,
                    feedback_contract.contract_id,
                    str(ordinal),
                ),
                contract_id=feedback_contract.contract_id,
                claim_id=feedback_contract.claim_id,
                target=repair_target,
                status="failed",
                subject_ref=repair_target.committed_subject_ref,
                evidence_refs=(evidence_ref,),
                diagnostic_ref=evidence_ref,
                evaluated_at=datetime.now(UTC),
                summary="The exact semantic transaction failed its framework contract.",
            )
            PRODUCTION_FEEDBACK.validate_result(feedback_result)
            feedback_result_ref = self.artifacts.put_json(
                artifact_id=feedback_result.result_id,
                artifact_type="control.feedback_result",
                value=feedback_result,
                dependencies=self._unique_refs(
                    (
                        evidence_ref,
                        *((repair_target_ref,) if repair_target_ref is not None else ()),
                    )
                ),
            )
        event = ControlEvent(
            event_id=f"{run.run_id}:structured-repair-event:{ordinal}",
            kind=(
                ControlEventKind.BACKEND_RETRYABLE
                if repair_mode is StructuredRepairMode.BACKEND_RETRY
                else ControlEventKind.CONTRACT_FAILURE
            ),
            node=owner_node,
            reason_code=f"structured_{safe_mode}",
            subject_ref=repair_target_ref or evidence_ref,
            evidence_refs=self._unique_refs(
                (
                    evidence_ref,
                    *((feedback_result_ref,) if feedback_result_ref is not None else ()),
                )
            ),
            issue_codes=safe_issues,
        )
        disposition = self.code_router.classify_local_repair(event, mode=repair_mode)
        event_ref = self.artifacts.put_json(
            artifact_id=event.event_id,
            artifact_type="control.event",
            value=event,
            dependencies=(evidence_ref,),
        )
        disposition_ref = self.artifacts.put_json(
            artifact_id=f"{event.event_id}:disposition",
            artifact_type="control.event_disposition",
            value=disposition,
            dependencies=(event_ref,),
        )
        finding = Finding(
            finding_id=f"finding:{fingerprint.removeprefix('sha256:')[:24]}",
            category=f"{owner_node}_structured_{safe_mode}",
            severity="high",
            owner=disposition.owner,
            subject_ref=repair_target_ref or evidence_ref,
            summary=(f"{safe_role} output requires a framework-authorized {safe_mode} correction."),
            evidence_refs=self._unique_refs(
                (
                    event_ref,
                    disposition_ref,
                    evidence_ref,
                    *((feedback_result_ref,) if feedback_result_ref is not None else ()),
                )
            ),
            fingerprint=fingerprint,
            disclosure="repair",
            suggested_repair="Correct only the rejected typed artifact at the current node.",
        )
        finding_ref = self.artifacts.put_json(
            artifact_id=f"{run.run_id}:structured-repair-finding:{ordinal}",
            artifact_type="control.finding",
            value=finding,
            dependencies=(event_ref, disposition_ref, evidence_ref),
        )
        if repair_target_ref is not None:
            run.remember(repair_target_ref)
        run.remember(
            evidence_ref,
            event_ref,
            disposition_ref,
            *((feedback_result_ref,) if feedback_result_ref is not None else ()),
        )
        run.remember_findings(finding_ref)
        entry = run.repair_ledger.authorize(
            finding=finding,
            finding_ref=finding_ref,
            current_node=owner_node,
            target_node=owner_node,
            owner_ref=repair_target_ref or evidence_ref,
            action=(
                "retry_infrastructure"
                if repair_mode is StructuredRepairMode.BACKEND_RETRY
                else "continue_session"
            ),
            jump_distance=0,
            causal_evidence_refs=self._unique_refs(
                (evidence_ref, *((repair_target_ref,) if repair_target_ref is not None else ()))
            ),
            blocking_claim_ids_before=safe_issues,
            validation_phase_before=(
                diagnostic.validation_phase if diagnostic is not None else None
            ),
            validation_frontier_before=(
                diagnostic.frontier_ordinal if diagnostic is not None else None
            ),
            maximum_attempts=(
                feedback_contract.maximum_attempts if feedback_contract is not None else None
            ),
        )
        self._persist_repair_ledger_entry(run, entry)
        await self._persist_snapshot(run, status="running")
        if entry.outcome != "authorized":
            raise StructuredRepairDenied(entry.outcome)
        return entry.entry_id

    async def _complete_structured_repair(
        self,
        run: _RunState,
        entry_id: str,
        *,
        remaining_issue_codes: tuple[str, ...],
        continued_session: bool,
        remaining_diagnostic: ValidationDiagnostic | None = None,
    ) -> None:
        safe_remaining = tuple(
            dict.fromkeys(self._safe_identifier(item) for item in remaining_issue_codes)
        )
        current = next(
            (item for item in run.repair_ledger.entries if item.entry_id == entry_id),
            None,
        )
        if current is None:
            raise ValueError("unknown structured RepairLedger entry")
        progress_evidence: Literal["none", "issue_set_changed", "validation_stage_advanced"] = (
            "none"
        )
        if remaining_diagnostic is not None:
            if remaining_diagnostic.owner_component != current.target_node:
                raise ValueError("remaining diagnostic owner does not match RepairLedger target")
            diagnostic_issues = tuple(
                dict.fromkeys(
                    self._safe_identifier(item) for item in remaining_diagnostic.issue_codes
                )
            )
            if diagnostic_issues != safe_remaining:
                raise ValueError("remaining diagnostic issue set does not match completion")
        if (
            current.validation_frontier_before is not None
            and remaining_diagnostic is not None
            and remaining_diagnostic.frontier_ordinal > current.validation_frontier_before
        ):
            progress_evidence = "validation_stage_advanced"
        elif self._structured_validation_stage_advanced(
            current.blocking_claim_ids_before,
            safe_remaining,
        ):
            # Transitional support for Designer validators that have not yet
            # adopted the shared frontier contract.  Verifier and Builder do
            # not use this hard-coded compatibility path.
            progress_evidence = "validation_stage_advanced"
        elif (
            current.blocking_claim_ids_before
            and safe_remaining
            and frozenset(current.blocking_claim_ids_before) != frozenset(safe_remaining)
        ):
            # Exact issue identity changed even though a legacy validator did
            # not provide an ordinal frontier.  This is bounded evidence that
            # error A became error B, not proof of resolution; the local repair
            # limit still prevents A/B oscillation from becoming an open loop.
            progress_evidence = "issue_set_changed"
        entry = run.repair_ledger.complete(
            entry_id,
            blocking_claim_ids_after=safe_remaining,
            retained_refs=(
                (current.resolved_owner_ref,) if current.resolved_owner_ref is not None else ()
            ),
            session_strategy="continued" if continued_session else "fresh",
            progress_evidence=progress_evidence,
            validation_phase_after=(
                remaining_diagnostic.validation_phase if remaining_diagnostic is not None else None
            ),
            validation_frontier_after=(
                remaining_diagnostic.frontier_ordinal if remaining_diagnostic is not None else None
            ),
            usage=BudgetUsage(repair_attempts=1),
        )
        run.ledger.consume(BudgetUsage(repair_attempts=1))
        self._persist_repair_ledger_entry(run, entry)
        await self._persist_snapshot(run, status="running")

    @staticmethod
    def _structured_repair_owner_ref(
        run: _RunState,
        owner_node: Literal["design", "verifier", "build", "judge"],
    ) -> ArtifactRef:
        artifact_types = {
            "design": ("design.environment_design",),
            "verifier": ("judge.verifier_ir_projection",),
            "build": ("build.environment_candidate", "build.implementation_contract"),
            "judge": ("judge_report", "judge.integration_report"),
        }[owner_node]
        for artifact_type in artifact_types:
            if ref := FoundryController._latest_ref(run, artifact_type):
                return ref
        return run.job_ref

    @staticmethod
    def _structured_validation_stage_advanced(
        before: tuple[str, ...],
        after: tuple[str, ...],
    ) -> bool:
        """Accept only explicit monotonic validator-stage transitions."""

        if len(before) != 1 or len(after) != 1:
            return False
        ranks = {
            "boundary_visibility_capacity": 10,
            "state_inventory_resource_coverage": 20,
            "state_inventory_resource_ownership": 30,
            "state_inventory_visibility_coverage": 40,
            "schema_root_object": 50,
            "schema_object_properties": 60,
            "schema_object_not_closed": 70,
            "schema_external_ref": 80,
            "state_schema_field_drift": 90,
            "state_schema_lifecycle_drift": 100,
        }
        before_rank = ranks.get(before[0])
        after_rank = ranks.get(after[0])
        return before_rank is not None and after_rank is not None and after_rank > before_rank

    def _control_failure_finding(
        self,
        run: _RunState,
        *,
        node: NodeKind,
        event_kind: ControlEventKind,
        code: str,
        error_type: str,
        subject_ref: ArtifactRef | None = None,
        causal_refs: Sequence[ArtifactRef] = (),
        repair_context: Sequence[str] = (),
        exception: BaseException | None = None,
    ) -> ArtifactRef:
        safe_code = self._safe_identifier(code)
        safe_context = tuple(self._safe_identifier(item) for item in repair_context)
        subject = subject_ref or run.job_ref
        event_id = self._stable_id(
            "control-event",
            run.run_id,
            node,
            safe_code,
            subject.revision_id,
            str(len(run.findings)),
        )
        event = ControlEvent(
            event_id=event_id,
            kind=event_kind,
            node=node,
            reason_code=safe_code,
            subject_ref=subject,
            evidence_refs=self._unique_refs(tuple(causal_refs)),
            issue_codes=safe_context,
        )
        disposition = self.code_router.classify(event)
        if not isinstance(disposition, DeterministicDisposition):
            raise ValueError("a semantic advisory event cannot be compiled directly to Finding")
        event_ref = self.artifacts.put_json(
            artifact_id=event.event_id,
            artifact_type="control.event",
            value=event,
            dependencies=self._unique_refs((subject, *causal_refs)),
        )
        disposition_ref = self.artifacts.put_json(
            artifact_id=f"{event.event_id}:disposition",
            artifact_type="control.event_disposition",
            value=disposition,
            dependencies=(event_ref,),
        )
        diagnostic: dict[str, JsonValue] = {}
        if exception is not None:
            frames = traceback.extract_tb(exception.__traceback__)
            if frames:
                frame = frames[-1]
                path_parts = frame.filename.replace("\\", "/").split("/")
                safe_path = "/".join(path_parts[-3:])
                diagnostic["error_site"] = self._safe_identifier(
                    f"{safe_path}:{frame.name}:{frame.lineno}"
                )
            # Raw exception text can contain credentials, request content or
            # host paths.  Persist a correlation digest instead of the text;
            # the typed site and causal exception classes remain inspectable.
            diagnostic["message_fingerprint"] = sha256_digest(
                str(exception).encode("utf-8", errors="replace")
            )
            causes: list[str] = []
            current = exception.__cause__ or exception.__context__
            while current is not None and len(causes) < 4:
                causes.append(self._safe_identifier(type(current).__name__))
                current = current.__cause__ or current.__context__
            diagnostic["cause_types"] = cast(JsonValue, causes)
            if isinstance(exception, DesignerError):
                diagnostic["designer_stage"] = self._safe_identifier(exception.stage)
                diagnostic["framework_invariant"] = exception.framework_invariant
                diagnostic["infrastructure_error"] = exception.infrastructure_error
                if exception.failure_code is not None:
                    diagnostic["designer_failure_code"] = self._safe_identifier(
                        exception.failure_code
                    )
                if exception.lineage_id is not None:
                    diagnostic["designer_lineage"] = self._safe_identifier(exception.lineage_id)
                if exception.validation_issues:
                    diagnostic["validation_issues"] = cast(
                        JsonValue,
                        [self._safe_identifier(item) for item in exception.validation_issues],
                    )
                if exception.result is not None:
                    diagnostic["invocation_status"] = self._safe_identifier(
                        exception.result.status.value
                    )
                    diagnostic["invocation_attempt_count"] = len(exception.results)
                    if exception.result.error is not None:
                        diagnostic["backend_error_code"] = self._safe_identifier(
                            exception.result.error.code
                        )
                        diagnostic["backend_retryable"] = exception.result.error.retryable
                    if exception.result.worker_exit_code is not None:
                        diagnostic["backend_worker_exit_code"] = exception.result.worker_exit_code
        evidence_ref = self.artifacts.put_json(
            artifact_id=self._stable_id(
                "control-failure-evidence",
                run.run_id,
                node,
                safe_code,
                str(len(run.findings)),
            ),
            artifact_type="control.failure_evidence",
            value={
                "run_id": run.run_id,
                "node": self._safe_identifier(node),
                "failure_code": safe_code,
                "error_type": self._safe_identifier(error_type),
                "repair_context": list(safe_context),
                **diagnostic,
            },
            dependencies=self._unique_refs((subject, event_ref, disposition_ref, *causal_refs)),
        )
        fingerprint = sha256_digest(
            canonical_json_bytes(
                {
                    "run_id": run.run_id,
                    "node": node,
                    "code": safe_code,
                    "subject": subject.revision_id,
                }
            )
        )
        finding = Finding(
            finding_id=f"finding:{fingerprint.removeprefix('sha256:')[:24]}",
            category=safe_code,
            severity="high",
            owner=disposition.owner,
            subject_ref=subject,
            summary=(
                f"{node} stopped without a releasable output ({safe_code})."
                + (" Framework checks: " + ", ".join(safe_context) + "." if safe_context else "")
            ),
            evidence_refs=self._unique_refs(
                (event_ref, disposition_ref, evidence_ref, *causal_refs)
            ),
            fingerprint=fingerprint,
            disclosure="public" if disposition.owner == "permissions" else "repair",
            suggested_repair=(
                "Provide the explicitly requested permission and resume this job."
                if disposition.owner == "permissions"
                else (
                    "Correct the typed issues recorded in the framework ControlEvent."
                    if safe_context
                    else "Resume only through the framework-selected owning component."
                )
            ),
            blocks_release=True,
        )
        finding_ref = self.artifacts.put_json(
            artifact_id=self._stable_id(
                "control-finding",
                run.run_id,
                node,
                safe_code,
                evidence_ref.revision_id,
            ),
            artifact_type="control.finding",
            value=finding,
            dependencies=self._unique_refs(
                (
                    subject,
                    event_ref,
                    disposition_ref,
                    evidence_ref,
                    *causal_refs,
                )
            ),
        )
        run.remember(event_ref, disposition_ref, evidence_ref)
        run.remember_findings(finding_ref)
        return finding_ref

    def _design_revision_mode_for_finding(self, finding: Finding) -> DesignRevisionMode:
        """Read only the typed CodeRouter disposition, never Finding prose."""

        disposition_refs = tuple(
            ref for ref in finding.evidence_refs if ref.artifact_type == "control.event_disposition"
        )
        if not disposition_refs:
            return DesignRevisionMode.FULL_SEMANTIC_REVISION
        if len(disposition_refs) != 1:
            raise ValueError("design Finding must bind at most one CodeRouter disposition")
        disposition = self.artifacts.get_json(
            disposition_refs[0],
            DeterministicDisposition,
        )
        self.artifacts.require_exact_json(
            disposition_refs[0],
            disposition,
            artifact_types=("control.event_disposition",),
        )
        if disposition.owner != "design" or disposition.design_revision_mode is None:
            raise ValueError("design Finding disposition lacks a Design revision mode")
        return disposition.design_revision_mode

    async def _load_or_recover_direct_result(
        self,
        *,
        head: DirectJobHead,
        request: EnvironmentRequest,
        direct_lock: DirectJobLock,
    ) -> GenerateResult:
        """Return a completed result or recover the post-publish crash window.

        No other running checkpoint is automatically replayed: an Agent turn may
        have consumed tokens or caused permitted external effects after the last
        checkpoint.  Treating that work as absent would be false idempotency.
        """

        self.artifacts.require_exact_json(
            head.request_ref,
            request,
            artifact_types=("control.environment_request",),
        )
        job = self.artifacts.get_json(head.job_ref, EnvironmentJob)
        self.artifacts.require_exact_json(
            head.job_ref,
            job,
            artifact_types=("control.environment_job",),
        )
        if job.kind != "generate" or job.request_ref != head.request_ref:
            raise DirectJobStoreError("Direct job head does not bind its exact Generate job")
        snapshot = self.artifacts.get_json(head.snapshot_ref, JobRunSnapshot)
        self.artifacts.require_exact_json(
            head.snapshot_ref,
            snapshot,
            artifact_types=("control.job_run_snapshot",),
        )
        if (
            snapshot.run_id != head.run_id
            or snapshot.job_ref != head.job_ref
            or snapshot.revision != head.snapshot_revision
            or snapshot.status != head.status
        ):
            raise DirectJobStoreError("Direct job head differs from its immutable snapshot")

        if head.result_ref is not None and head.status == "released":
            result = self.artifacts.get_json(head.result_ref, GenerateResult)
            self.artifacts.require_exact_json(
                head.result_ref,
                result,
                artifact_types=("control.generate_result",),
            )
            self._validate_direct_result(head, snapshot, result)
            return result

        release = self._registry_release_for_direct_job(head.job_ref)
        if release is not None:
            return await self._recover_direct_release(
                head=head,
                snapshot=snapshot,
                release=release,
                direct_lock=direct_lock,
            )

        if head.result_ref is not None:
            result = self.artifacts.get_json(head.result_ref, GenerateResult)
            self.artifacts.require_exact_json(
                head.result_ref,
                result,
                artifact_types=("control.generate_result",),
            )
            self._validate_direct_result(head, snapshot, result)
            return result

        if head.status in {"failed", "needs_human", "budget_exhausted"}:
            result = self._direct_failure_result_from_snapshot(head=head, snapshot=snapshot)
            run = self._restore_direct_run(head, snapshot, direct_lock)
            self._complete_direct_result(run, result)
            return result
        if head.status == "running":
            return await self._recover_abandoned_scheduler_direct_locked(
                head=head,
                request=request,
                job=job,
                snapshot=snapshot,
                direct_lock=direct_lock,
            )
        raise DirectJobResumeRequiredError(
            "durable Direct Generation checkpoint exists but has no terminal result; "
            "the framework will not replay possibly consumed Agent/tool work"
        )

    def _validate_direct_result(
        self,
        head: DirectJobHead,
        snapshot: JobRunSnapshot,
        result: GenerateResult,
    ) -> None:
        if (
            result.run_id != head.run_id
            or result.request_ref != head.request_ref
            or result.job_ref != head.job_ref
            or result.final_snapshot_ref != head.snapshot_ref
            or result.status != head.status
        ):
            raise DirectJobStoreError("persisted GenerateResult differs from its Direct job head")
        if result.status != "released":
            return
        if (
            result.release is None
            or result.release_ref is None
            or result.package_manifest_ref is None
            or snapshot.release_ref != result.release_ref
        ):
            raise DirectJobStoreError("released Direct result is incomplete")
        self.artifacts.require_exact_json(
            result.release_ref,
            result.release,
            artifact_types=("release.record",),
        )
        if (
            result.release.manifest_ref != result.package_manifest_ref
            or result.release.reservation_owner_ref != head.job_ref
        ):
            raise DirectJobStoreError("released Direct result does not belong to its Generate job")
        current = self.registry.inspect(
            result.release.coordinate.package_id,
            result.release.coordinate.version,
            package_digest=result.release.coordinate.package_digest,
        )
        if (
            current.release_id != result.release.release_id
            or current.manifest_ref != result.release.manifest_ref
            or current.reservation_owner_ref != head.job_ref
        ):
            raise DirectJobStoreError("Registry release differs from persisted GenerateResult")

    def _registry_release_for_direct_job(self, job_ref: ArtifactRef) -> ReleaseRecord | None:
        candidates = tuple(
            record for record in self.registry.list() if record.reservation_owner_ref == job_ref
        )
        if len(candidates) > 1:
            raise DirectJobStoreError("one Direct Generate job owns multiple Registry releases")
        if not candidates:
            return None
        candidate = candidates[0]
        return self.registry.inspect(
            candidate.coordinate.package_id,
            candidate.coordinate.version,
            package_digest=candidate.coordinate.package_digest,
        )

    def _quarantine_released_baseline(self, baseline_ref: ArtifactRef) -> None:
        """Quarantine only a release that still binds the challenged WorldSpec."""

        baseline = self.artifacts.get_json(baseline_ref, DesignBaselineCheckpoint)
        self.artifacts.require_exact_json(
            baseline_ref,
            baseline,
            artifact_types=("design.baseline_checkpoint",),
        )
        release = self._registry_release_for_direct_job(baseline.origin_job_ref)
        if release is None or release.status != "released":
            return
        released_design = self.artifacts.get_json(release.design_ref, EnvironmentDesign)
        self.artifacts.require_exact_json(
            release.design_ref,
            released_design,
            artifact_types=("design.environment_design",),
        )
        if (
            sha256_digest(canonical_json_bytes(released_design.world_spec))
            != baseline.world_spec_ref.content_hash
        ):
            return
        self.registry.quarantine(
            release.coordinate.package_id,
            release.coordinate.version,
            reason_code="discovery_hard_correction_confirmed",
            actor="framework",
        )

    async def _recover_direct_release(
        self,
        *,
        head: DirectJobHead,
        snapshot: JobRunSnapshot,
        release: ReleaseRecord,
        direct_lock: DirectJobLock,
    ) -> GenerateResult:
        """Finish publication bookkeeping after Registry already committed release."""

        if release.reservation_owner_ref != head.job_ref:
            raise DirectJobStoreError("Registry release belongs to a different Direct job")
        job = self.artifacts.get_json(head.job_ref, EnvironmentJob)
        if release.release_profile != job.release_profile:
            raise DirectJobStoreError(
                "Registry release profile differs from its Direct Generate job"
            )
        if head.status == "running" and release.status != "released":
            raise DirectJobStoreError(
                "incomplete Direct job cannot recover a Registry release that is no longer released"
            )
        if head.status == "released":
            checkpoint_release_ref = snapshot.release_ref
            if checkpoint_release_ref is None:
                raise DirectJobStoreError("released checkpoint does not contain release_ref")
            stored_release = self.artifacts.get_json(checkpoint_release_ref, ReleaseRecord)
            self.artifacts.require_exact_json(
                checkpoint_release_ref,
                stored_release,
                artifact_types=("release.record",),
            )
            if stored_release.release_id != release.release_id:
                raise DirectJobStoreError("released checkpoint and Registry disagree")
            run = self._restore_direct_run(head, snapshot, direct_lock)
            final_telemetry_ref = self._ensure_final_telemetry_summary(
                run,
                dependencies=(release.manifest_ref, checkpoint_release_ref),
            )
            if final_telemetry_ref not in snapshot.latest_artifact_refs:
                final_snapshot_ref = await self._persist_snapshot(
                    run,
                    status="released",
                    release_ref=checkpoint_release_ref,
                )
                snapshot = self.artifacts.get_json(final_snapshot_ref, JobRunSnapshot)
                if run.direct_head is None:
                    raise DirectJobStoreError("telemetry recovery lost the Direct job head")
                head = run.direct_head
            result = self._direct_result_from_snapshot(
                head=head,
                snapshot=snapshot,
                release_ref=checkpoint_release_ref,
                release=stored_release,
            )
            self._complete_direct_result(run, result)
            return result

        run = self._restore_direct_run(head, snapshot, direct_lock)
        run.allow_registry_reconciliation = head.status in {
            "failed",
            "needs_human",
            "budget_exhausted",
        }
        release_ref = self.artifacts.put_json(
            artifact_id=f"{run.run_id}:release-record",
            artifact_type="release.record",
            value=release,
            dependencies=(release.manifest_ref, release.judge_report_ref, release.candidate_ref),
        )
        run.remember(release.manifest_ref, release_ref)
        recovery_attempt = self._start_attempt(
            run,
            "release",
            (release.manifest_ref, release.judge_report_ref),
        )
        self._finish_attempt(
            run,
            recovery_attempt,
            status="passed",
            output_refs=(release.manifest_ref, release_ref),
        )
        self._ensure_final_telemetry_summary(
            run,
            dependencies=(release.manifest_ref, release_ref),
        )
        final_snapshot_ref = await self._persist_snapshot(
            run,
            status="released",
            release_ref=release_ref,
        )
        final_snapshot = self.artifacts.get_json(final_snapshot_ref, JobRunSnapshot)
        result = self._direct_result_from_snapshot(
            head=run.direct_head,
            snapshot=final_snapshot,
            release_ref=release_ref,
            release=release,
        )
        self._complete_direct_result(run, result)
        self.artifacts.record_event(
            event_type="generation_recovered_after_publish",
            subject_ref=final_snapshot_ref,
            related_refs=(release.manifest_ref, release_ref),
        )
        return result

    def _restore_direct_run(
        self,
        head: DirectJobHead,
        snapshot: JobRunSnapshot,
        direct_lock: DirectJobLock,
    ) -> _RunState:
        ledger = BudgetLedger(snapshot.reserved_budget)
        ledger.consume_uncertain(
            observed_actual=snapshot.observed_actual_budget,
            unknown_upper_bound=snapshot.unknown_upper_bound_budget,
        )
        run = _RunState(
            run_id=head.run_id,
            job_ref=head.job_ref,
            scope_id=(
                head.scope_id or self.artifacts.get_json(head.job_ref, EnvironmentJob).job_id
            ),
            ledger=ledger,
            attempts=list(snapshot.attempts),
            latest={ref.artifact_id: ref for ref in snapshot.latest_artifact_refs},
            findings={
                ref.revision_id: ref
                for ref in snapshot.latest_artifact_refs
                if ref.artifact_type == "control.finding"
            },
            snapshot_revision=snapshot.revision,
            last_snapshot_ref=head.snapshot_ref,
            wall_charged=True,
            direct_request_id=head.request_id,
            direct_request_fingerprint=head.request_fingerprint,
            direct_request_ref=head.request_ref,
            direct_lock=direct_lock,
            direct_head=head,
            repair_ledger=RepairLedger(
                tuple(
                    self.artifacts.get_json(ref, RepairLedgerEntry)
                    for ref in snapshot.latest_artifact_refs
                    if ref.artifact_type == "control.repair_ledger_entry"
                )
            ),
        )
        run.remember(head.request_ref, head.job_ref)
        return run

    def _direct_result_from_snapshot(
        self,
        *,
        head: DirectJobHead | None,
        snapshot: JobRunSnapshot,
        release_ref: ArtifactRef,
        release: ReleaseRecord,
    ) -> GenerateResult:
        if head is None:
            raise DirectJobStoreError("Direct recovery lost its durable head")
        latest_by_type = {ref.artifact_type: ref for ref in snapshot.latest_artifact_refs}
        return GenerateResult(
            run_id=head.run_id,
            status="released",
            request_ref=head.request_ref,
            job_ref=head.job_ref,
            final_snapshot_ref=head.snapshot_ref,
            discovery_run_ref=latest_by_type.get("discovery.run_spec"),
            discovery_state_ref=latest_by_type.get("control.discovery_lane_state"),
            expansion_inbox_ref=latest_by_type.get("discovery.expansion_inbox_snapshot"),
            finding_refs=tuple(
                sorted(
                    (
                        ref
                        for ref in snapshot.latest_artifact_refs
                        if ref.artifact_type == "control.finding"
                    ),
                    key=lambda ref: (ref.artifact_id, ref.revision_id),
                )
            ),
            package_manifest_ref=release.manifest_ref,
            release_ref=release_ref,
            release=release,
        )

    @staticmethod
    def _direct_failure_result_from_snapshot(
        *,
        head: DirectJobHead,
        snapshot: JobRunSnapshot,
    ) -> GenerateResult:
        if head.status not in {"failed", "needs_human", "budget_exhausted"}:
            raise DirectJobStoreError("failure recovery requires a failed terminal checkpoint")
        if snapshot.failure_code is None or snapshot.failure_summary is None:
            raise DirectJobStoreError("terminal failure checkpoint lacks durable failure metadata")
        failure_status = cast(
            Literal["failed", "needs_human", "budget_exhausted"],
            head.status,
        )
        latest_by_type = {ref.artifact_type: ref for ref in snapshot.latest_artifact_refs}
        return GenerateResult(
            run_id=head.run_id,
            status=failure_status,
            request_ref=head.request_ref,
            job_ref=head.job_ref,
            final_snapshot_ref=head.snapshot_ref,
            discovery_run_ref=latest_by_type.get("discovery.run_spec"),
            discovery_state_ref=latest_by_type.get("control.discovery_lane_state"),
            expansion_inbox_ref=latest_by_type.get("discovery.expansion_inbox_snapshot"),
            finding_refs=tuple(
                sorted(
                    (
                        ref
                        for ref in snapshot.latest_artifact_refs
                        if ref.artifact_type == "control.finding"
                    ),
                    key=lambda ref: (ref.artifact_id, ref.revision_id),
                )
            ),
            failure_code=snapshot.failure_code,
            failure_summary=snapshot.failure_summary,
        )

    def _complete_direct_result(self, run: _RunState, result: GenerateResult) -> ArtifactRef:
        if (
            run.direct_head is None
            or run.direct_lock is None
            or run.direct_request_id is None
            or run.direct_request_fingerprint is None
            or run.direct_request_ref is None
        ):
            raise DirectJobStoreError("Direct result completion lacks durable run context")
        if (
            result.final_snapshot_ref != run.direct_head.snapshot_ref
            or result.status != run.direct_head.status
        ):
            raise DirectJobStoreError("Direct result does not match the latest checkpoint")
        result_dependencies = self._unique_refs(
            (
                result.request_ref,
                result.job_ref,
                result.final_snapshot_ref,
                *result.finding_refs,
                *((result.package_manifest_ref,) if result.package_manifest_ref else ()),
                *((result.release_ref,) if result.release_ref else ()),
                *((result.discovery_run_ref,) if result.discovery_run_ref else ()),
                *((result.discovery_state_ref,) if result.discovery_state_ref else ()),
                *((result.expansion_inbox_ref,) if result.expansion_inbox_ref else ()),
            )
        )
        try:
            result_ref = self.artifacts.put_json(
                artifact_id=f"{run.run_id}:generate-result",
                artifact_type="control.generate_result",
                value=result,
                dependencies=result_dependencies,
            )
        except Exception as exc:
            raise DirectJobStoreError("unable to persist terminal GenerateResult") from exc
        completed_head = new_direct_job_head(
            request_id=run.direct_request_id,
            request_fingerprint=run.direct_request_fingerprint,
            request_ref=run.direct_request_ref,
            job_ref=run.job_ref,
            scope_id=run.scope_id,
            run_id=run.run_id,
            snapshot_ref=run.direct_head.snapshot_ref,
            snapshot_revision=run.direct_head.snapshot_revision,
            status=run.direct_head.status,
            result_ref=result_ref,
            previous_result_ref=run.direct_head.previous_result_ref,
        )
        run.direct_head = self.direct_jobs.compare_and_swap(
            run.direct_lock,
            expected_head=run.direct_head,
            next_head=completed_head,
        )
        return result_ref

    def _checkpoint_direct_head(
        self,
        run: _RunState,
        snapshot_ref: ArtifactRef,
        status: Literal[
            "running",
            "released",
            "failed",
            "needs_human",
            "budget_exhausted",
        ],
    ) -> None:
        direct_values = (
            run.direct_request_id,
            run.direct_request_fingerprint,
            run.direct_request_ref,
            run.direct_lock,
        )
        if all(value is None for value in direct_values):
            return
        if any(value is None for value in direct_values):
            raise DirectJobStoreError("Direct run has incomplete durable head context")
        request_id = run.direct_request_id
        request_fingerprint = run.direct_request_fingerprint
        request_ref = run.direct_request_ref
        direct_lock = run.direct_lock
        if (
            request_id is None
            or request_fingerprint is None
            or request_ref is None
            or direct_lock is None
        ):
            raise DirectJobStoreError("Direct run durable context failed type narrowing")
        next_head = new_direct_job_head(
            request_id=request_id,
            request_fingerprint=request_fingerprint,
            request_ref=request_ref,
            job_ref=run.job_ref,
            scope_id=run.scope_id,
            run_id=run.run_id,
            snapshot_ref=snapshot_ref,
            snapshot_revision=run.snapshot_revision,
            status=status,
            previous_result_ref=(
                run.direct_head.previous_result_ref
                if run.direct_head is not None and run.direct_head.result_ref is None
                else run.direct_head.result_ref
                if run.direct_head is not None
                else None
            ),
        )
        run.direct_head = self.direct_jobs.compare_and_swap(
            direct_lock,
            expected_head=run.direct_head,
            next_head=next_head,
            allow_terminal_restart=run.allow_direct_restart,
            allow_registry_reconciliation=run.allow_registry_reconciliation,
        )
        run.allow_direct_restart = False
        run.allow_registry_reconciliation = False

    async def _persist_snapshot(
        self,
        run: _RunState,
        *,
        status: Literal[
            "running",
            "released",
            "failed",
            "needs_human",
            "budget_exhausted",
        ],
        release_ref: ArtifactRef | None = None,
        failure_code: str | None = None,
        failure_summary: str | None = None,
    ) -> ArtifactRef:
        self._commit_finished_attempts(run)
        run.snapshot_revision += 1
        latest = self._unique_refs(tuple(run.latest.values()))
        snapshot = JobRunSnapshot(
            run_id=run.run_id,
            job_ref=run.job_ref,
            revision=run.snapshot_revision,
            status=status,
            reserved_budget=run.ledger.reserved,
            observed_actual_budget=run.ledger.observed_actual,
            unknown_upper_bound_budget=run.ledger.unknown_upper_bound,
            conservative_committed_budget=run.ledger.used,
            attempts=tuple(run.attempts),
            latest_artifact_refs=latest,
            release_ref=release_ref,
            failure_code=failure_code,
            failure_summary=failure_summary,
        )
        dependencies = [run.job_ref, *latest]
        if run.last_snapshot_ref is not None:
            dependencies.append(run.last_snapshot_ref)
        snapshot_ref = self.artifacts.put_json(
            artifact_id=f"{run.run_id}:state",
            artifact_type="control.job_run_snapshot",
            value=snapshot,
            dependencies=self._unique_refs(tuple(dependencies)),
        )
        run.last_snapshot_ref = snapshot_ref
        self._checkpoint_direct_head(run, snapshot_ref, status)
        if self.telemetry is not None:
            self.telemetry.record_event(
                trace_id=run.run_id,
                span_id=(
                    run.telemetry_root_span.span_id if run.telemetry_root_span is not None else None
                ),
                event_type="control.snapshot.committed",
                payload={
                    "revision": run.snapshot_revision,
                    "status": status,
                    "attempt_count": len(run.attempts),
                    "latest_artifact_count": len(latest),
                },
            )
            self.telemetry.flush()
        return snapshot_ref

    def _commit_finished_attempts(self, run: _RunState) -> None:
        """Commit every newly terminal node before publishing a new run snapshot."""

        for attempt in run.attempts:
            if attempt.attempt_id in run.node_commit_refs:
                continue
            if attempt.status in {"pending", "running", "invalidated"}:
                continue
            if attempt.finished_at is None:
                raise ValueError("terminal NodeAttempt is missing finished_at")
            commit = NodeCommit(
                commit_id=f"commit:{attempt.attempt_id.removeprefix('attempt:')}",
                run_id=run.run_id,
                node=attempt.node,
                attempt_id=attempt.attempt_id,
                status="passed" if attempt.status == "passed" else "failed",
                input_refs=attempt.input_refs,
                output_refs=attempt.output_refs,
                usage=attempt.budget_usage,
                committed_at=attempt.finished_at,
            )
            dependencies = self._unique_refs(
                (
                    *attempt.input_refs,
                    *attempt.output_refs,
                    *attempt.finding_refs,
                )
            )
            ref = self.artifacts.put_json(
                artifact_id=f"{run.run_id}:node-commit:{attempt.attempt_id}",
                artifact_type="control.node_commit",
                value=commit,
                dependencies=dependencies,
            )
            run.node_commit_refs[attempt.attempt_id] = ref
            run.remember(ref)

    def _persist_discovery_state(
        self,
        *,
        spec_ref: ArtifactRef,
        state: DiscoveryLaneState,
        previous_ref: ArtifactRef | None = None,
        extra_dependencies: tuple[ArtifactRef, ...] = (),
    ) -> ArtifactRef:
        dependencies = [spec_ref, *extra_dependencies]
        if previous_ref is not None:
            dependencies.append(previous_ref)
        return self.artifacts.put_json(
            artifact_id=f"{state.discovery_run_ref.artifact_id}:state",
            artifact_type="control.discovery_lane_state",
            value=state,
            dependencies=self._unique_refs(tuple(dependencies)),
        )

    def _start_attempt(
        self,
        run: _RunState,
        node: Literal[
            "request",
            "discovery",
            "design",
            "verifier",
            "build",
            "integration",
            "judge",
            "release",
        ],
        inputs: tuple[ArtifactRef, ...],
    ) -> str:
        ordinal = 1 + sum(attempt.node == node for attempt in run.attempts)
        attempt_id = f"attempt:{node}:{ordinal}:{uuid.uuid4().hex[:16]}"
        attempt = NodeAttempt(
            attempt_id=attempt_id,
            node=node,
            ordinal=ordinal,
            status="running",
            started_at=datetime.now(UTC),
            input_refs=FoundryController._unique_refs(inputs),
        )
        telemetry_span: WorkSpan | None = None
        if self.telemetry is not None:
            component = cast(
                Literal["controller", "designer", "builder", "judge", "registry"],
                {
                    "request": "controller",
                    "discovery": "designer",
                    "design": "designer",
                    "verifier": "judge",
                    "build": "builder",
                    "integration": "judge",
                    "judge": "judge",
                    "release": "registry",
                }[node],
            )
            telemetry_span = self.telemetry.start_span(
                trace_id=run.run_id,
                component=component,
                operation=f"node.{node}",
                parent_span_id=(
                    run.telemetry_root_span.span_id if run.telemetry_root_span is not None else None
                ),
                run_id=run.run_id,
                node=node,
                attempt=ordinal,
                repair_depth=run.ledger.used.repair_attempts,
                input_refs=inputs,
            )
        try:
            run.attempts.append(attempt)
        except BaseException:
            if telemetry_span is not None:
                telemetry_span.finish(status="error", error_code="attempt_registration_failed")
            raise
        if telemetry_span is not None:
            run.telemetry_node_spans[attempt_id] = telemetry_span
        return attempt_id

    def _finish_attempt(
        self,
        run: _RunState,
        attempt_id: str,
        *,
        status: Literal[
            "passed",
            "failed",
            "needs_human",
            "budget_exhausted",
        ],
        output_refs: tuple[ArtifactRef, ...] = (),
        finding_refs: tuple[ArtifactRef, ...] = (),
        failure_code: str | None = None,
        failure_summary: str | None = None,
        usage: BudgetUsage | None = None,
        profile_hash: str | None = None,
        session_id: str | None = None,
    ) -> None:
        index = next(
            (
                index
                for index, attempt in enumerate(run.attempts)
                if attempt.attempt_id == attempt_id
            ),
            None,
        )
        if index is None:
            raise ValueError(f"unknown node attempt: {attempt_id}")
        current = run.attempts[index]
        run.attempts[index] = current.model_copy(
            update={
                "status": status,
                "finished_at": datetime.now(UTC),
                "output_refs": FoundryController._unique_refs(output_refs),
                "finding_refs": FoundryController._unique_refs(finding_refs),
                "agent_profile_hash": profile_hash,
                "agent_session_id": session_id,
                "failure_code": failure_code,
                "failure_summary": failure_summary,
                "budget_usage": usage or BudgetUsage(),
            }
        )
        span = run.telemetry_node_spans.pop(attempt_id, None)
        if span is not None:
            effective_usage = usage or BudgetUsage()
            units = {
                "llm_tokens": "tokens",
                "agent_turns": "turns",
                "search_calls": "calls",
                "tool_calls": "calls",
                "build_seconds": "seconds",
                "evaluation_episodes": "episodes",
                "container_seconds": "seconds",
                "live_probe_cost": "cost_units",
                "repair_attempts": "attempts",
                "wall_seconds": "seconds",
                "monetary_cost": "currency_units",
            }
            metrics = tuple(
                MetricPoint(
                    name=f"budget.accounted.{name}",
                    value=getattr(effective_usage, name),
                    unit=unit,
                    provenance="framework",
                    labels={"node": current.node},
                )
                for name, unit in units.items()
            )
            telemetry_status = cast(
                Literal["passed", "failed", "needs_human", "budget_exhausted"],
                status,
            )
            span.finish(
                status=telemetry_status,
                error_code=failure_code,
                output_refs=output_refs,
                metrics=metrics,
            )

    @staticmethod
    def _close_open_telemetry_spans(run: _RunState, *, error_code: str) -> None:
        """Close abandoned node spans so terminal traces never pretend work is running."""

        for span in tuple(run.telemetry_node_spans.values()):
            if not span.closed:
                span.finish(status="error", error_code=error_code)
        run.telemetry_node_spans.clear()

    def _invalidate_artifact_descendants(
        self,
        run: _RunState,
        *,
        superseded_refs: tuple[ArtifactRef, ...],
        invalidating_refs: tuple[ArtifactRef, ...],
    ) -> tuple[ArtifactRef, ...]:
        """Invalidate only attempts that consumed the superseded Artifact DAG.

        Rejected pre-commit output has no ArtifactRef and therefore invalidates
        nothing.  A successful new revision invalidates the transitive
        descendants of the precise superseded revisions; unrelated research,
        sibling batches and cached artifacts remain valid.
        """

        if not superseded_refs or not invalidating_refs:
            raise ValueError("artifact invalidation requires superseded and invalidating refs")
        descendants: dict[str, ArtifactRef] = {}
        frontier = list(self._unique_refs(superseded_refs))
        visited = {item.revision_id for item in frontier}
        while frontier:
            current = frontier.pop()
            for dependent in self.artifacts.dependents(current):
                if dependent.revision_id in visited:
                    continue
                visited.add(dependent.revision_id)
                descendants[dependent.revision_id] = dependent
                frontier.append(dependent)

        invalidated_output_refs: list[ArtifactRef] = []
        causal_revision_ids = set(descendants) | {item.revision_id for item in superseded_refs}
        for index, attempt in enumerate(run.attempts):
            if attempt.status in {"pending", "running", "invalidated"}:
                continue
            bound_refs = (*attempt.input_refs, *attempt.output_refs)
            if not any(ref.revision_id in causal_revision_ids for ref in bound_refs):
                continue
            invalidated_output_refs.extend(attempt.output_refs)
            run.attempts[index] = attempt.model_copy(
                update={
                    "status": "invalidated",
                    "invalidated_by_refs": self._unique_refs(invalidating_refs),
                    "failure_code": None,
                    "failure_summary": None,
                }
            )
        return self._unique_refs(tuple(invalidated_output_refs))

    def _finish_discovery_attempt(
        self,
        run: _RunState,
        *,
        status: Literal["pending", "passed", "failed"],
        output_refs: tuple[ArtifactRef, ...],
        finding_refs: tuple[ArtifactRef, ...] = (),
        usage: BudgetUsage | None = None,
        failure_code: str | None = None,
    ) -> None:
        indices = [
            index
            for index, attempt in enumerate(run.attempts)
            if attempt.node == "discovery" and attempt.status in {"pending", "running"}
        ]
        if not indices:
            return
        index = indices[-1]
        attempt = run.attempts[index]
        if status == "pending":
            run.attempts[index] = attempt.model_copy(
                update={
                    "status": "pending",
                    "finished_at": None,
                    "budget_usage": usage or BudgetUsage(),
                }
            )
            return
        self._finish_attempt(
            run,
            attempt.attempt_id,
            status=status,
            output_refs=output_refs,
            finding_refs=finding_refs,
            failure_code=failure_code,
            failure_summary=(
                "Discovery found a blocking hard correction."
                if failure_code == "discovery_hard_correction"
                else ("Discovery lane failed independently." if status == "failed" else None)
            ),
            usage=usage,
        )

    def _invocation_usage(
        self,
        results: tuple[InvocationResult, ...],
        *,
        unknown_token_cap: int,
        base_turns: int,
    ) -> BudgetUsage:
        actual, unknown = self._invocation_settlement(
            results,
            unknown_token_cap=unknown_token_cap,
            base_turns=base_turns,
        )
        return self._add_usage(actual, unknown)

    def _invocation_settlement(
        self,
        results: tuple[InvocationResult, ...],
        *,
        unknown_token_cap: int,
        base_turns: int,
        unknown_token_upper_bounds: tuple[int, ...] = (),
        monetary_upper_bound: float = 0.0,
        reserved_turns: int | None = None,
    ) -> tuple[BudgetUsage, BudgetUsage]:
        del base_turns  # Repair usage is owned exclusively by RepairLedger.
        known = tuple(self._token_total(item.usage) for item in results)
        known_total = sum(value for value in known if value is not None)
        inferred_unknown_bounds = tuple(
            self.config.agent.structured_turn_token_limit for value in known if value is None
        )
        all_unknown_bounds = (*inferred_unknown_bounds, *unknown_token_upper_bounds)
        started_turns = len(results) + len(unknown_token_upper_bounds)
        conservative_unknown = min(
            max(0, unknown_token_cap - known_total),
            sum(all_unknown_bounds),
        )
        return (
            BudgetUsage(
                llm_tokens=known_total,
                agent_turns=started_turns,
            ),
            BudgetUsage(
                llm_tokens=conservative_unknown,
                monetary_cost=self._monetary_unknown_for_started_turns(
                    monetary_upper_bound,
                    started_turns=started_turns,
                    reserved_turns=(reserved_turns or started_turns),
                ),
            ),
        )

    def _compile_branch_budgets(
        self,
        remaining: Budget,
        *,
        verifier_base_turns: int,
    ) -> tuple[Budget, Budget]:
        """Reserve explicit semantic envelopes for the parallel compile branch.

        ``agent_turns`` is a cardinality ceiling, not a token-allocation weight.
        Dividing all remaining tokens by all remaining possible turns makes a
        real Codex prefill larger than the resulting cap.  Conversely, handing
        every Verifier correction the complete branch lease violates the
        worst-case lease proof.  Reserve one configured cap per possible turn
        and reduce optional structured corrections when capacity is tighter.
        """

        if not 1 <= verifier_base_turns <= self.verifier_compiler.maximum_task_shards:
            raise _GenerationHalt(
                status="failed",
                code="compile_branch_verifier_shard_count_invalid",
                summary="Verifier task shard count is outside framework policy.",
            )
        builder_turns = self.builder.maximum_precommit_reworks + 1
        builder_repair_attempts = builder_turns - 1
        minimum_turns = builder_turns + verifier_base_turns
        if remaining.agent_turns < minimum_turns:
            raise _GenerationHalt(
                status="budget_exhausted",
                code="compile_branch_turn_budget_exhausted",
                summary=f"Verifier and Builder require {minimum_turns} reserved Agent turns.",
            )
        verifier_turn_cap = self.config.agent.structured_turn_token_limit
        builder_tokens = self.config.agent.environment_codegen_physical_turn_token_limit
        reserved_builder_tokens = builder_tokens * builder_turns
        minimum_tokens = verifier_turn_cap * verifier_base_turns + reserved_builder_tokens
        if remaining.llm_tokens < minimum_tokens:
            raise _GenerationHalt(
                status="budget_exhausted",
                code="compile_branch_token_budget_exhausted",
                summary=(
                    "Verifier and Builder cannot reserve their configured real-Agent "
                    "turn envelopes."
                ),
            )
        if remaining.repair_attempts < builder_repair_attempts:
            raise _GenerationHalt(
                status="budget_exhausted",
                code="compile_branch_repair_budget_exhausted",
                summary="Builder pre-commit correction budget cannot be reserved.",
            )
        possible_verifier_corrections = min(
            verifier_base_turns * self.verifier_compiler.maximum_structured_reworks,
            remaining.repair_attempts - builder_repair_attempts,
            max(0, remaining.agent_turns - minimum_turns),
            max(
                0,
                (remaining.llm_tokens - reserved_builder_tokens) // verifier_turn_cap
                - verifier_base_turns,
            ),
        )
        verifier_turns = verifier_base_turns + possible_verifier_corrections
        verifier_tokens = verifier_turn_cap * verifier_turns
        total_reserved_tokens = verifier_tokens + reserved_builder_tokens
        verifier_money = remaining.monetary_cost * verifier_tokens / total_reserved_tokens
        verifier = Budget(
            llm_tokens=verifier_tokens,
            agent_turns=verifier_turns,
            repair_attempts=possible_verifier_corrections,
            wall_seconds=remaining.wall_seconds,
            monetary_cost=verifier_money,
        )
        builder = Budget(
            llm_tokens=reserved_builder_tokens,
            agent_turns=builder_turns,
            build_seconds=remaining.build_seconds,
            repair_attempts=builder_repair_attempts,
            wall_seconds=remaining.wall_seconds,
            monetary_cost=max(0.0, remaining.monetary_cost - verifier_money),
        )
        return verifier, builder

    def _verifier_only_budget(
        self,
        remaining: Budget,
        *,
        verifier_base_turns: int,
    ) -> Budget:
        """Reserve Verifier capacity when an exact Build checkpoint was adopted."""

        if not 1 <= verifier_base_turns <= self.verifier_compiler.maximum_task_shards:
            raise _GenerationHalt(
                status="failed",
                code="verifier_checkpoint_shard_count_invalid",
                summary="Verifier task shard count is outside framework policy.",
            )
        token_cap = self.config.agent.structured_turn_token_limit
        if remaining.agent_turns < verifier_base_turns:
            raise _GenerationHalt(
                status="budget_exhausted",
                code="verifier_checkpoint_turn_budget_exhausted",
                summary="Recovered Build requires fresh Verifier Agent turns.",
            )
        if remaining.llm_tokens < token_cap * verifier_base_turns:
            raise _GenerationHalt(
                status="budget_exhausted",
                code="verifier_checkpoint_token_budget_exhausted",
                summary="Recovered Build cannot reserve the Verifier token envelope.",
            )
        corrections = min(
            verifier_base_turns * self.verifier_compiler.maximum_structured_reworks,
            remaining.repair_attempts,
            max(0, remaining.agent_turns - verifier_base_turns),
            max(0, remaining.llm_tokens // token_cap - verifier_base_turns),
        )
        turns = verifier_base_turns + corrections
        return Budget(
            llm_tokens=token_cap * turns,
            agent_turns=turns,
            repair_attempts=corrections,
            wall_seconds=remaining.wall_seconds,
            monetary_cost=remaining.monetary_cost,
        )

    def _persist_budget_lease(
        self,
        run: _RunState,
        lease: BudgetLease,
        *,
        previous_ref: ArtifactRef | None = None,
    ) -> ArtifactRef:
        dependencies = (run.job_ref,) if previous_ref is None else (run.job_ref, previous_ref)
        return self.artifacts.put_json(
            artifact_id=f"{run.run_id}:budget-lease:{lease.lease_id}",
            artifact_type="control.budget_lease",
            value=lease,
            dependencies=dependencies,
        )

    def _budget_excluding_reservation(
        self,
        remaining: Budget,
        reservation: Budget | None,
    ) -> Budget:
        """Return capacity available beside an already admitted sibling.

        Non-wall dimensions are exclusive vector resources.  Wall time is a
        shared deadline, so the LeaseBudgetLedger deliberately leaves it
        available to concurrent work while proving every other dimension fits.
        """

        if reservation is None:
            return remaining
        ledger = LeaseBudgetLedger(remaining)
        shared_deadline_reservation = reservation.model_copy(
            update={"wall_seconds": remaining.wall_seconds}
        )
        ledger.reserve(
            lease_id="budget-lease:sibling-reservation",
            owner_id="concurrent-sibling",
            requested=shared_deadline_reservation,
            elapsed_wall_seconds=0.0,
        )
        return ledger.remaining(elapsed_wall_seconds=0.0)

    def _reserve_agent_invocation_work(
        self,
        run: _RunState,
        *,
        attempt_id: str,
        requested: Budget,
        available: Budget | None = None,
    ) -> _AgentInvocationWorkLease:
        """Persist a repair-time Agent lease before crossing the backend boundary."""

        if requested.agent_turns <= 0 or requested.wall_seconds <= 0:
            raise BudgetExceeded(("agent_turns", "wall_seconds"))
        ledger = LeaseBudgetLedger(available or run.ledger.remaining)
        lease = ledger.reserve(
            lease_id=self._stable_id("agent-repair-budget-lease", run.run_id, attempt_id),
            owner_id=attempt_id,
            requested=requested,
            elapsed_wall_seconds=0.0,
        )
        lease_ref = self._persist_budget_lease(run, lease)
        run.remember(lease_ref)
        return _AgentInvocationWorkLease(ledger=ledger, lease=lease, lease_ref=lease_ref)

    def _settle_agent_invocation_work(
        self,
        run: _RunState,
        work: _AgentInvocationWorkLease,
        *,
        observed_actual: BudgetUsage,
        unknown_upper_bound: BudgetUsage,
    ) -> BudgetUsage:
        """Idempotently close a repair invocation and commit its three quantities."""

        if work.terminal_lease is None:
            work.terminal_lease = work.ledger.settle(
                work.lease.lease_id,
                observed_actual,
                unknown_upper_bound=unknown_upper_bound,
            )
        if work.terminal_ref is None:
            work.terminal_ref = self._persist_budget_lease(
                run,
                work.terminal_lease,
                previous_ref=work.lease_ref,
            )
        run.remember(work.terminal_ref)
        if not work.global_charged:
            run.ledger.consume_uncertain(
                observed_actual=work.terminal_lease.observed_actual,
                unknown_upper_bound=work.terminal_lease.unknown_upper_bound,
            )
            work.global_charged = True
        return work.terminal_lease.conservative_committed

    @staticmethod
    def _agent_invocation_unknown(
        budget: Budget,
        *,
        include_build_time: bool,
    ) -> BudgetUsage:
        """Fail closed only over dimensions a repair-time Agent can consume."""

        return BudgetUsage(
            llm_tokens=budget.llm_tokens,
            agent_turns=budget.agent_turns,
            build_seconds=(budget.build_seconds if include_build_time else 0),
            monetary_cost=budget.monetary_cost,
        )

    def _builder_repair_budget(
        self,
        remaining: Budget,
        state: BuilderSessionState,
    ) -> Budget:
        """Authorize exactly one continuation under the immutable session profile."""

        token_limit, timeout_limit = self.builder.repair_turn_requirements(state)
        missing = tuple(
            dimension
            for dimension, available, required in (
                ("llm_tokens", remaining.llm_tokens, token_limit),
                ("agent_turns", remaining.agent_turns, 1),
                ("build_seconds", remaining.build_seconds, timeout_limit),
                ("wall_seconds", remaining.wall_seconds, timeout_limit),
            )
            if available < required
        )
        if missing:
            raise BudgetExceeded(missing)
        monetary_cost = (
            0.0
            if remaining.llm_tokens <= 0
            else min(
                remaining.monetary_cost,
                remaining.monetary_cost * token_limit / remaining.llm_tokens,
            )
        )
        return Budget(
            llm_tokens=token_limit,
            agent_turns=1,
            build_seconds=timeout_limit,
            wall_seconds=timeout_limit,
            monetary_cost=monetary_cost,
        )

    def _reserve_judge_work(
        self,
        run: _RunState,
        *,
        attempt_id: str,
        requested: Budget,
        available: Budget | None = None,
    ) -> _JudgeWorkLease:
        """Persist a conservative worst-case Judge reservation before child work starts."""

        missing_time = tuple(
            dimension
            for dimension in ("container_seconds", "wall_seconds")
            if getattr(requested, dimension) <= 0
        )
        if missing_time:
            raise BudgetExceeded(missing_time)
        ledger = LeaseBudgetLedger(available or run.ledger.remaining)
        lease = ledger.reserve(
            lease_id=self._stable_id("judge-budget-lease", run.run_id, attempt_id),
            owner_id=attempt_id,
            requested=requested,
            elapsed_wall_seconds=0.0,
        )
        lease_ref = self._persist_budget_lease(run, lease)
        run.remember(lease_ref)
        return _JudgeWorkLease(ledger=ledger, lease=lease, lease_ref=lease_ref)

    def _settle_judge_work(
        self,
        run: _RunState,
        work: _JudgeWorkLease,
        usage: BudgetUsage,
        *,
        unknown_upper_bound: BudgetUsage | None = None,
    ) -> ArtifactRef:
        """Settle trusted Judge usage and commit it to the parent vector ledger."""

        if work.terminal_lease is None:
            work.terminal_lease = work.ledger.settle(
                work.lease.lease_id,
                usage,
                unknown_upper_bound=unknown_upper_bound,
            )
        if not work.global_charged:
            run.ledger.consume_uncertain(
                observed_actual=work.terminal_lease.observed_actual,
                unknown_upper_bound=work.terminal_lease.unknown_upper_bound,
            )
            work.global_charged = True
        if work.terminal_ref is None:
            work.terminal_ref = self._persist_budget_lease(
                run,
                work.terminal_lease,
                previous_ref=work.lease_ref,
            )
        run.remember(work.terminal_ref)
        return work.terminal_ref

    def _settle_failed_judge_work(
        self,
        run: _RunState,
        work: _JudgeWorkLease,
    ) -> BudgetUsage:
        """Fail closed when a Judge invocation has no trustworthy terminal usage."""

        requested_usage = self._budget_as_usage(work.lease.reserved)
        self._settle_judge_work(
            run,
            work,
            BudgetUsage(),
            unknown_upper_bound=requested_usage,
        )
        assert work.terminal_lease is not None
        return work.terminal_lease.conservative_committed

    def _reserve_designer_work(
        self,
        run: _RunState,
        *,
        purpose: str,
        base_turns: int,
        maximum_corrections: int,
        available: Budget | None = None,
        controller_owns_structured_repairs: bool = False,
    ) -> _DesignerWorkLease:
        """Reserve a hard semantic-node envelope before any Designer invocation."""

        if base_turns <= 0 or maximum_corrections < 0:
            raise ValueError("Designer work shape must contain positive base turns")
        remaining = available or run.ledger.remaining
        requested = self._designer_budget_slice(
            remaining,
            purpose=purpose,
            base_turns=base_turns,
            maximum_corrections=maximum_corrections,
        )
        ledger = LeaseBudgetLedger(remaining)
        lease = ledger.reserve(
            lease_id=self._stable_id(
                "designer-budget-lease",
                run.run_id,
                purpose,
                str(len(run.attempts)),
            ),
            owner_id=self._safe_identifier(f"{run.run_id}:{purpose}"),
            requested=requested,
            elapsed_wall_seconds=0.0,
        )
        lease_ref = self._persist_budget_lease(run, lease)
        run.remember(lease_ref)
        return _DesignerWorkLease(
            ledger=ledger,
            lease=lease,
            lease_ref=lease_ref,
            controller_owns_structured_repairs=controller_owns_structured_repairs,
        )

    def _designer_budget_slice(
        self,
        remaining: Budget,
        *,
        purpose: str,
        base_turns: int,
        maximum_corrections: int,
    ) -> Budget:
        """Derive one non-exchangeable invocation envelope from remaining capacity."""

        try:
            return self._plan_designer_budget(
                remaining,
                base_turns=base_turns,
                maximum_corrections=maximum_corrections,
            )
        except DesignerBudgetPlanError as exc:
            raise _GenerationHalt(
                status="budget_exhausted",
                code=f"designer_{exc.dimension}_budget_exhausted",
                summary=(
                    f"Designer work {purpose} requires {exc.required} {exc.dimension}; "
                    f"{exc.reserved} is reserved."
                ),
            ) from exc

    def _plan_designer_budget(
        self,
        remaining: Budget,
        *,
        base_turns: int,
        maximum_corrections: int,
    ) -> Budget:
        """Use the single typed planner without changing caller failure policy."""

        return derive_designer_invocation_budget(
            remaining,
            base_turns=base_turns,
            maximum_corrections=maximum_corrections,
            rollout_token_limit=self.config.agent.structured_turn_token_limit,
        )

    def _settle_designer_work(
        self,
        run: _RunState,
        work: _DesignerWorkLease,
        usage: BudgetUsage,
        *,
        unknown_upper_bound: BudgetUsage | None = None,
    ) -> ArtifactRef:
        if work.terminal_lease is None:
            lease_usage = usage
            lease_unknown = unknown_upper_bound
            if work.controller_owns_structured_repairs:
                lease_usage = usage.model_copy(update={"repair_attempts": 0})
                if lease_unknown is not None:
                    lease_unknown = lease_unknown.model_copy(update={"repair_attempts": 0})
            work.terminal_lease = work.ledger.settle(
                work.lease.lease_id,
                lease_usage,
                unknown_upper_bound=lease_unknown,
            )
        if not work.global_charged:
            run.ledger.consume_uncertain(
                observed_actual=work.terminal_lease.observed_actual,
                unknown_upper_bound=work.terminal_lease.unknown_upper_bound,
            )
            work.global_charged = True
        if work.terminal_ref is None:
            work.terminal_ref = self._persist_budget_lease(
                run,
                work.terminal_lease,
                previous_ref=work.lease_ref,
            )
        run.remember(work.terminal_ref)
        return work.terminal_ref

    def _settle_failed_designer_work(
        self,
        run: _RunState,
        work: _DesignerWorkLease,
        exc: BaseException,
    ) -> BudgetUsage:
        if (
            isinstance(exc, DesignerError)
            and exc.budget_observed_actual is not None
            and exc.budget_unknown_upper_bound is not None
        ):
            observed = exc.budget_observed_actual
            unknown = exc.budget_unknown_upper_bound
        elif isinstance(exc, DesignerError) and exc.budget_usage is not None:
            observed = exc.budget_usage
            unknown = BudgetUsage()
        else:
            observed = BudgetUsage()
            unknown = self._budget_as_usage(work.lease.reserved)
        self._settle_designer_work(
            run,
            work,
            observed,
            unknown_upper_bound=unknown,
        )
        assert work.terminal_lease is not None
        return work.terminal_lease.conservative_committed

    def _settle_designer_error(
        self,
        run: _RunState,
        work: _DesignerWorkLease,
        exc: DesignerError,
        settled_invocation_usage: BudgetUsage | None = None,
    ) -> BudgetUsage:
        """Account both invocation and already-spent research on node failure."""

        invocation_usage = (
            settled_invocation_usage
            if settled_invocation_usage is not None
            else self._settle_failed_designer_work(run, work, exc)
        )
        if (
            settled_invocation_usage is None
            and work.controller_owns_structured_repairs
            and exc.budget_usage is not None
        ):
            # The Controller/RepairLedger owns the global repair dimension,
            # while the node attempt still attributes the real correction.
            invocation_usage = exc.budget_usage
        research_usage = exc.research_usage
        if research_usage != BudgetUsage():
            run.ledger.consume(research_usage)
        return self._add_usage(invocation_usage, research_usage)

    @staticmethod
    def _designer_bundle_settlement(
        bundle: DesignBundle | ExpansionDesignBundle | DiscoveryBundle | AdmissionBundle,
    ) -> tuple[BudgetUsage, BudgetUsage]:
        """Preserve actual/unknown provenance across the Designer boundary."""

        actual = bundle.invocation_observed_actual
        unknown = bundle.invocation_unknown_upper_bound
        if actual is None and unknown is None:
            return bundle.invocation_usage, BudgetUsage()
        if actual is None or unknown is None:
            raise RuntimeError("Designer bundle contains an incomplete budget settlement")
        if FoundryController._add_usage(actual, unknown) != bundle.invocation_usage:
            raise RuntimeError("Designer bundle budget settlement is not conservative")
        return actual, unknown

    @staticmethod
    def _budget_as_usage(budget: Budget) -> BudgetUsage:
        """Charge a full reservation when a child exits without trustworthy usage."""

        return BudgetUsage.model_validate(
            {
                field_name: 0 if field_name == "wall_seconds" else getattr(budget, field_name)
                for field_name in Budget.model_fields
                if field_name != "schema_version"
            }
        )

    def _builder_invocation_usage(
        self,
        invocation: BuildInvocationSummary,
        *,
        unknown_token_cap: int,
    ) -> BudgetUsage:
        actual, unknown = self._builder_invocation_settlement(
            invocation,
            unknown_token_cap=unknown_token_cap,
        )
        return self._add_usage(actual, unknown)

    @staticmethod
    def _builder_invocation_settlement(
        invocation: BuildInvocationSummary,
        *,
        unknown_token_cap: int,
        monetary_upper_bound: float = 0.0,
        reserved_turns: int | None = None,
    ) -> tuple[BudgetUsage, BudgetUsage]:
        actual_tokens = max(0, invocation.total_tokens)
        unknown_tokens = min(
            max(0, unknown_token_cap - actual_tokens),
            sum(invocation.unknown_token_upper_bounds),
        )
        return (
            BudgetUsage(
                llm_tokens=actual_tokens,
                agent_turns=invocation.turns,
                build_seconds=max(0.0, invocation.duration_ms / 1000),
            ),
            BudgetUsage(
                llm_tokens=unknown_tokens,
                monetary_cost=FoundryController._monetary_unknown_for_started_turns(
                    monetary_upper_bound,
                    started_turns=invocation.turns,
                    reserved_turns=(reserved_turns or invocation.turns),
                ),
            ),
        )

    @staticmethod
    def _monetary_unknown_for_started_turns(
        reserved_monetary_cost: float,
        *,
        started_turns: int,
        reserved_turns: int,
    ) -> float:
        """Bound unpriced provider work without claiming it as observed spend."""

        if reserved_monetary_cost <= 0 or started_turns <= 0 or reserved_turns <= 0:
            return 0.0
        return min(
            reserved_monetary_cost,
            reserved_monetary_cost * started_turns / reserved_turns,
        )

    def _verifier_result_settlement(
        self,
        result: CompiledVerifier | BaseException,
        *,
        budget: Budget,
        base_turns: int,
    ) -> tuple[BudgetUsage, BudgetUsage]:
        if isinstance(result, CompiledVerifier):
            return self._invocation_settlement(
                result.invocation_results,
                unknown_token_cap=budget.llm_tokens,
                base_turns=base_turns,
                monetary_upper_bound=budget.monetary_cost,
                reserved_turns=budget.agent_turns,
            )
        if isinstance(result, VerifierCompilationError):
            return self._invocation_settlement(
                result.invocation_results,
                unknown_token_cap=budget.llm_tokens,
                base_turns=base_turns,
                unknown_token_upper_bounds=result.unknown_token_upper_bounds,
                monetary_upper_bound=budget.monetary_cost,
                reserved_turns=budget.agent_turns,
            )
        return BudgetUsage(), self._budget_as_usage(budget)

    def _builder_result_settlement(
        self,
        result: BuildBundle | BaseException,
        *,
        budget: Budget,
    ) -> tuple[BudgetUsage, BudgetUsage]:
        if isinstance(result, BuildBundle):
            return self._builder_invocation_settlement(
                result.invocation,
                unknown_token_cap=budget.llm_tokens,
                monetary_upper_bound=budget.monetary_cost,
                reserved_turns=budget.agent_turns,
            )
        if isinstance(result, BuilderError) and result.invocation is not None:
            return self._builder_invocation_settlement(
                result.invocation,
                unknown_token_cap=budget.llm_tokens,
                monetary_upper_bound=budget.monetary_cost,
                reserved_turns=budget.agent_turns,
            )
        if isinstance(result, BuilderError) and result.permission_denied:
            return BudgetUsage(), BudgetUsage()
        return BudgetUsage(), self._budget_as_usage(budget)

    @staticmethod
    def _token_total(usage: InvocationUsage | None) -> int | None:
        if usage is None or usage.turn is None:
            return None
        return max(0, usage.turn.total_tokens)

    @staticmethod
    def _add_usage(left: BudgetUsage, right: BudgetUsage) -> BudgetUsage:
        return BudgetUsage(
            llm_tokens=left.llm_tokens + right.llm_tokens,
            agent_turns=left.agent_turns + right.agent_turns,
            search_calls=left.search_calls + right.search_calls,
            tool_calls=left.tool_calls + right.tool_calls,
            build_seconds=left.build_seconds + right.build_seconds,
            evaluation_episodes=(left.evaluation_episodes + right.evaluation_episodes),
            container_seconds=left.container_seconds + right.container_seconds,
            live_probe_cost=left.live_probe_cost + right.live_probe_cost,
            repair_attempts=left.repair_attempts + right.repair_attempts,
            wall_seconds=left.wall_seconds + right.wall_seconds,
            monetary_cost=left.monetary_cost + right.monetary_cost,
        )

    @staticmethod
    def _last_profile_hash(results: tuple[InvocationResult, ...]) -> str | None:
        for result in reversed(results):
            if result.session is not None:
                return f"sha256:{result.session.profile_hash}"
        return None

    @staticmethod
    def _last_session_id(results: tuple[InvocationResult, ...]) -> str | None:
        for result in reversed(results):
            if result.session is not None:
                return FoundryController._hashed_session(result.session.thread_id)
        return None

    @staticmethod
    def _hashed_session(thread_id: str) -> str:
        digest = hashlib.sha256(thread_id.encode("utf-8")).hexdigest()[:24]
        return f"agent-session:{digest}"

    @staticmethod
    def _invocation_failure_status(
        status: InvocationStatus | None,
        *,
        default_code: str,
    ) -> tuple[
        Literal["failed", "needs_human", "budget_exhausted"],
        str,
    ]:
        if status is InvocationStatus.NEEDS_HUMAN:
            return "needs_human", "agent_needs_human"
        if status is InvocationStatus.BUDGET_EXHAUSTED:
            return "budget_exhausted", "agent_budget_exhausted"
        if status is InvocationStatus.TIMED_OUT:
            return "budget_exhausted", "agent_timed_out"
        if status is InvocationStatus.CANCELLED:
            return "failed", "agent_cancelled"
        return "failed", FoundryController._safe_identifier(default_code)

    @staticmethod
    def _designer_failure_status(
        exc: DesignerError,
        *,
        default_code: str,
    ) -> tuple[
        Literal["failed", "needs_human", "budget_exhausted"],
        str,
    ]:
        if exc.requires_permission:
            return "needs_human", "agent_permission_required"
        if exc.budget_exhausted:
            return (
                "budget_exhausted",
                FoundryController._safe_identifier(exc.failure_code or "agent_budget_exhausted"),
            )
        if exc.failure_code is not None:
            return "failed", FoundryController._safe_identifier(exc.failure_code)
        return FoundryController._invocation_failure_status(
            exc.result.status if exc.result is not None else None,
            default_code=default_code,
        )

    @staticmethod
    def _verifier_error(
        exc: BaseException,
    ) -> tuple[str, Literal["failed", "needs_human", "budget_exhausted"]]:
        if isinstance(exc, VerifierCompilationError) and exc.permission_denied:
            return "verifier_permission_required", "needs_human"
        if isinstance(exc, VerifierCompilationError) and exc.result is not None:
            status, code = FoundryController._invocation_failure_status(
                exc.result.status,
                default_code="verifier_compilation_failed",
            )
            return code, status
        return "verifier_compilation_failed", "failed"

    @staticmethod
    def _builder_error(
        exc: BaseException,
    ) -> tuple[
        str,
        Literal["failed", "needs_human", "budget_exhausted"],
        BuilderSessionState | None,
    ]:
        if isinstance(exc, BuilderError):
            if exc.permission_denied:
                return "builder_permission_required", "needs_human", exc.state
            status, code = FoundryController._invocation_failure_status(
                exc.invocation.status if exc.invocation is not None else None,
                default_code=f"builder_{FoundryController._safe_identifier(exc.stage)}",
            )
            return code, status, exc.state
        return "builder_execution_failed", "failed", None

    @staticmethod
    def _generate_status(
        status: Literal["failed", "needs_human", "budget_exhausted"],
    ) -> GenerateStatus:
        return status

    @staticmethod
    def _exception_code(prefix: str, exc: BaseException) -> str:
        closed_code = getattr(exc, "failure_code", None)
        if isinstance(closed_code, str) and closed_code:
            return FoundryController._safe_identifier(f"{prefix}_{closed_code}")
        return FoundryController._safe_identifier(f"{prefix}_{type(exc).__name__.lower()}")

    @staticmethod
    def _safe_identifier(value: str) -> str:
        safe = "".join(
            character if character.isalnum() or character in "._:-" else "_" for character in value
        ).strip("._:-")
        if not safe:
            return "unspecified"
        if len(safe) <= 160:
            return safe
        digest = hashlib.sha256(safe.encode("utf-8")).hexdigest()[:16]
        return f"{safe[:143]}:{digest}"

    @staticmethod
    def _stable_id(prefix: str, *parts: str) -> str:
        digest = hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()[:24]
        return f"{prefix}:{digest}"

    @staticmethod
    def _unique_refs(refs: tuple[ArtifactRef, ...]) -> tuple[ArtifactRef, ...]:
        by_revision = {ref.revision_id: ref for ref in refs}
        return tuple(
            sorted(
                by_revision.values(),
                key=lambda ref: (ref.artifact_id, ref.revision_id),
            )
        )

    @staticmethod
    def _direct_request_fingerprint(
        request: EnvironmentRequest,
        *,
        enable_discovery: bool,
        discovery_budget: Budget,
    ) -> str:
        return sha256_digest(
            canonical_json_bytes(
                {
                    "request": request.model_dump(mode="json", exclude_none=False),
                    "direct_policy": {
                        "enable_discovery": enable_discovery,
                        "discovery_budget": (
                            discovery_budget.model_dump(mode="json", exclude_none=False)
                            if enable_discovery
                            else None
                        ),
                    },
                }
            )
        )

    @staticmethod
    def _charge_wall(
        run: _RunState,
        started: float,
        *,
        clamp: bool = False,
    ) -> None:
        if run.wall_charged:
            return
        elapsed = max(0.0, time.monotonic() - started)
        if clamp:
            elapsed = min(elapsed, run.ledger.reserved.wall_seconds)
        run.ledger.consume(BudgetUsage(wall_seconds=elapsed))
        run.wall_charged = True


__all__ = [
    "DiscoveryLaneState",
    "DiscoveryResumeResult",
    "FoundryController",
    "GenerateResult",
    "GenerateStatus",
    "ProfileDescriptorProvider",
]
