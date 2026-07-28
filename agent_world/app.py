"""Production composition root for the Agent World Foundry.

The pipeline core owns workflow and release decisions; this module is the only
place that chooses concrete production adapters.  It deliberately contains no
template backend, replay path, fixture registry, or alternate success path.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from agent_world.agent_profiles import IsolatedAgentProfileProvider
from agent_world.artifact_store import ArtifactStore
from agent_world.builder import BuilderWorkspaceProgress, EnvironmentBuilder
from agent_world.config import FoundryConfig, load_foundry_config
from agent_world.consumer import (
    CAPABILITY_FEEDBACK_ARTIFACT_ID_PREFIX,
    CAPABILITY_FEEDBACK_ARTIFACT_TYPE,
    CAPABILITY_FEEDBACK_PRODUCER,
    FeedbackRecorder,
    LocalRolloutConsumer,
)
from agent_world.contracts import (
    ArtifactRef,
    BudgetUsage,
    EnvironmentJob,
    EnvironmentSuiteSnapshot,
    ExpansionCampaign,
    SuiteSelectionRequest,
)
from agent_world.control import (
    BudgetLease,
    CampaignRunCheckpoint,
    CampaignStore,
    DirectJobStore,
    DurableLeaseBudgetCoordinator,
    JobRunSnapshot,
    TelemetryStore,
    WorkControlStore,
)
from agent_world.control.telemetry import INVOCATION_ACTIVITY_CLASSES
from agent_world.controller import FoundryController
from agent_world.designer import (
    DiscoveryService,
    EnvironmentDesigner,
    EvidenceBackedExpansionSource,
    ExpansionDesigner,
    ExpansionSourceRouter,
)
from agent_world.diagnostic_state import is_marked_test_node_diagnostic_state_root
from agent_world.expansion_runner import validate_campaign_report_graph
from agent_world.invocation import (
    CodexSdkBackend,
    DirectLlmBackend,
    InvocationBackend,
    RoutedInvocationBackend,
)
from agent_world.judge import (
    CleanCandidateBuilder,
    EnvironmentJudge,
    InteractiveChallengerStrategy,
    IsolationPolicy,
    VerifierCompiler,
)
from agent_world.observability import DebugTranscriptWriter, ObservabilityReader, ObservabilityRoot
from agent_world.registry import (
    EnvironmentRegistry,
    ReleaseRecord,
    ReleaseStatus,
)
from agent_world.research import ResearchToolchain, build_research_toolchain

_MAX_CANARY_BYTES = 8192


class ApplicationConfigurationError(RuntimeError):
    """A fail-closed assembly error whose message is safe for CLI output."""


@dataclass(frozen=True, slots=True)
class FoundryApplication:
    """Fully assembled production graph for generation and future campaigns."""

    config: FoundryConfig
    artifacts: ArtifactStore
    registry: EnvironmentRegistry
    profiles: IsolatedAgentProfileProvider
    backend: InvocationBackend
    telemetry: TelemetryStore
    research: ResearchToolchain
    designer: EnvironmentDesigner
    discovery: DiscoveryService
    expansion_source: ExpansionSourceRouter
    expansion_designer: ExpansionDesigner
    builder: EnvironmentBuilder
    verifier_compiler: VerifierCompiler
    judge: EnvironmentJudge
    controller: FoundryController


@dataclass(frozen=True, slots=True)
class ConsumptionApplication:
    """Credential-free optional consumer graph downstream of Registry release."""

    registry: RegistryReader
    rollout: LocalRolloutConsumer
    feedback: FeedbackRecorder


@dataclass(frozen=True, slots=True)
class RegistryReader:
    """Capability-limited offline Registry view; it cannot publish packages."""

    _registry: EnvironmentRegistry = field(repr=False)

    def list(
        self,
        *,
        package_id: str | None = None,
        statuses: Iterable[ReleaseStatus] | None = None,
    ) -> tuple[ReleaseRecord, ...]:
        return self._registry.list(package_id=package_id, statuses=statuses)

    def inspect(
        self,
        package_id: str,
        version: str,
        *,
        package_digest: str | None = None,
    ) -> ReleaseRecord:
        return self._registry.inspect(
            package_id,
            version,
            package_digest=package_digest,
        )

    def create_suite_snapshot(
        self,
        selections: Iterable[SuiteSelectionRequest],
    ) -> EnvironmentSuiteSnapshot:
        return self._registry.create_suite_snapshot(tuple(selections))

    def load_suite_snapshot(self, snapshot_id: str) -> EnvironmentSuiteSnapshot:
        return self._registry.load_suite_snapshot(snapshot_id)


@dataclass(frozen=True, slots=True)
class CampaignReader:
    """Credential-free read view over Campaign head and immutable artifacts."""

    _store: CampaignStore = field(repr=False)
    _artifacts: ArtifactStore = field(repr=False)

    def inspect(self, campaign_id: str) -> dict[str, object]:
        head = self._store.read_head(campaign_id)
        if head is None:
            raise ApplicationConfigurationError("campaign does not exist")
        if head.report_ref is not None:
            campaign, checkpoint, report = validate_campaign_report_graph(
                self._artifacts,
                head,
            )
        else:
            checkpoint = self._artifacts.get_json(
                head.checkpoint_ref,
                CampaignRunCheckpoint,
            )
            campaign = self._artifacts.get_json(
                checkpoint.campaign_ref,
                ExpansionCampaign,
            )
            report = None
        return {
            "head": head.model_dump(mode="json"),
            "campaign": campaign.model_dump(mode="json"),
            "checkpoint": checkpoint.model_dump(mode="json"),
            "report": report.model_dump(mode="json") if report is not None else None,
        }


@dataclass(frozen=True, slots=True)
class DirectRunReader:
    """Credential-free projection of one durable Direct Generation run."""

    _store: DirectJobStore = field(repr=False)
    _artifacts: ArtifactStore = field(repr=False)
    _telemetry: TelemetryStore = field(repr=False)
    _work_heads: WorkControlStore | None = field(default=None, repr=False)

    def inspect(self, request_id: str, *, include_metrics: bool = False) -> dict[str, object]:
        head = self._store.read_head(request_id)
        if head is None:
            raise ApplicationConfigurationError("Direct Generation request does not exist")
        snapshot = self._artifacts.get_json(head.snapshot_ref, JobRunSnapshot)
        if snapshot.run_id != head.run_id or snapshot.job_ref != head.job_ref:
            raise ApplicationConfigurationError("Direct Generation head is internally inconsistent")
        events: list[dict[str, object]] = []
        for event in self._artifacts.list_events_for_run(
            head.run_id,
            anchor_artifact_ids=(head.job_ref.artifact_id, head.request_ref.artifact_id),
        ):
            if event.event_type == "artifact_revision_committed":
                continue
            refs = (event.subject_ref, *event.related_refs)
            belongs_to_run = any(
                ref == head.job_ref
                or ref == head.request_ref
                or ref.artifact_id.startswith(f"{head.run_id}:")
                for ref in refs
            )
            if not belongs_to_run:
                continue
            events.append(
                {
                    "event_type": event.event_type,
                    "occurred_at": event.occurred_at.isoformat(),
                    "reason_code": event.reason_code,
                    "subject_ref": event.subject_ref.model_dump(mode="json"),
                    "details": [item.model_dump(mode="json") for item in event.details],
                }
            )
        output: dict[str, object] = {
            "head": head.model_dump(mode="json"),
            "snapshot": snapshot.model_dump(mode="json"),
            "events": events,
            "active_work": self._active_work(head.run_id, snapshot),
        }
        if include_metrics:
            output["metrics"] = self._telemetry.inspect_trace(head.run_id)
        return output

    def _active_work(
        self,
        run_id: str,
        snapshot: JobRunSnapshot,
    ) -> dict[str, object]:
        observed_spans = self._telemetry.active_work(run_id)
        spans = observed_spans if snapshot.status == "running" else ()
        orphaned_spans = observed_spans if snapshot.status != "running" else ()
        # A DirectJob snapshot is a terminal summary, not a mutable duplicate
        # of Scheduler state.  For a live run the Scheduler scope ledger is
        # updated before dispatch and after every operation, so it is the
        # authority for in-flight budget observation.  Old runs without a
        # scope ledger retain the snapshot-only compatibility projection.
        scheduler_budget = self._scheduler_budget(snapshot)
        if scheduler_budget is None:
            leases = tuple(
                self._artifacts.get_json(ref, BudgetLease)
                for ref in snapshot.latest_artifact_refs
                if ref.artifact_type == "control.budget_lease"
            )
            observed_actual = snapshot.observed_actual_budget
            unknown_upper_bound = snapshot.unknown_upper_bound_budget
            conservative_committed = snapshot.conservative_committed_budget
            budget_source = "direct_job_terminal_snapshot"
        else:
            leases, observed_actual, unknown_upper_bound, conservative_committed = scheduler_budget
            budget_source = "scheduler_scope_lease_ledger"
        observed_active_leases = tuple(lease for lease in leases if lease.status == "active")
        active_leases = observed_active_leases if snapshot.status == "running" else ()
        reserved_exposure: dict[str, int | float] = {}
        for lease in active_leases:
            for name, value in lease.reserved.model_dump(
                mode="python", exclude={"schema_version"}
            ).items():
                if name == "wall_seconds":
                    reserved_exposure[name] = max(
                        reserved_exposure.get(name, 0),
                        value,
                    )
                else:
                    reserved_exposure[name] = reserved_exposure.get(name, 0) + value
        activity_counts = {activity: 0 for activity in INVOCATION_ACTIVITY_CLASSES}
        activity_classification_available = False
        for span in spans:
            if not bool(span.get("activity_classification_available", False)):
                continue
            activity_classification_available = True
            observed_activity = span.get("observed_activity_event_counts")
            if not isinstance(observed_activity, Mapping):
                continue
            for activity in INVOCATION_ACTIVITY_CLASSES:
                observed = observed_activity.get(activity)
                if (
                    isinstance(observed, (int, float))
                    and not isinstance(observed, bool)
                    and observed >= 0
                ):
                    activity_counts[activity] += int(observed)
        return {
            "spans": list(spans),
            "orphaned_spans": list(orphaned_spans),
            "builder_workspace": self._latest_builder_workspace(snapshot),
            "usage": {
                "projection_source": budget_source,
                "observed_actual": observed_actual.model_dump(mode="json"),
                "unknown_upper_bound": unknown_upper_bound.model_dump(mode="json"),
                "conservative_committed": conservative_committed.model_dump(mode="json"),
                "inflight_observed": {
                    "llm_tokens": None,
                    "event_count": sum(int(item["observed_event_count"]) for item in spans),
                    "activity_classification_available": activity_classification_available,
                    "activity_event_counts": (
                        activity_counts if activity_classification_available else None
                    ),
                },
                "active_reserved_exposure": reserved_exposure,
                "active_lease_count": len(active_leases),
                "orphaned_lease_count": (
                    len(observed_active_leases) if snapshot.status != "running" else 0
                ),
            },
        }

    def _scheduler_budget(
        self,
        snapshot: JobRunSnapshot,
    ) -> tuple[tuple[BudgetLease, ...], BudgetUsage, BudgetUsage, BudgetUsage] | None:
        """Read the Scheduler ledger for one Direct job without mutating it.

        A missing ledger is expected only for an older terminal run.  A
        malformed existing ledger must surface as an inspection failure rather
        than being hidden behind a misleading zero budget.
        """

        if self._work_heads is None:
            return None
        job = self._artifacts.get_json(snapshot.job_ref, EnvironmentJob)
        coordinator = DurableLeaseBudgetCoordinator(self._work_heads.root / "scope-budgets")
        try:
            ledger = coordinator.snapshot(scope_id=job.job_id)
        except ValueError:
            return None
        settled = tuple(lease for lease in ledger.leases if lease.status == "settled")
        return (
            ledger.leases,
            self._sum_lease_usage(settled, "observed_actual"),
            self._sum_lease_usage(settled, "unknown_upper_bound"),
            self._sum_lease_usage(settled, "conservative_committed"),
        )

    @staticmethod
    def _sum_lease_usage(
        leases: tuple[BudgetLease, ...],
        attribute: str,
    ) -> BudgetUsage:
        fields = tuple(name for name in BudgetUsage.model_fields if name != "schema_version")
        return BudgetUsage.model_validate(
            {
                name: sum(getattr(getattr(lease, attribute), name) for lease in leases)
                for name in fields
            }
        )

    def _latest_builder_workspace(
        self,
        snapshot: JobRunSnapshot,
    ) -> dict[str, object] | None:
        active_builds = tuple(
            attempt
            for attempt in snapshot.attempts
            if attempt.node == "build" and attempt.status == "running"
        )
        if not active_builds:
            return None
        active_build = max(active_builds, key=lambda item: item.started_at)
        candidates: list[tuple[BuilderWorkspaceProgress, ArtifactRef]] = []
        artifact_id = EnvironmentBuilder.workspace_progress_artifact_id(
            snapshot.run_id,
            active_build.attempt_id,
        )
        for ref in self._artifacts.list_revisions(artifact_id):
            if ref.artifact_type != "build.workspace_progress":
                continue
            progress = self._artifacts.get_json(ref, BuilderWorkspaceProgress)
            if (
                progress.run_id != snapshot.run_id
                or progress.attempt_id != active_build.attempt_id
                or progress.observed_at < active_build.started_at
            ):
                continue
            candidates.append((progress, ref))
        if not candidates:
            return None
        progress, ref = max(candidates, key=lambda item: item[0].observed_at)
        return {
            "ref": ref.model_dump(mode="json"),
            "progress": progress.model_dump(mode="json"),
        }


def load_application(path: str | os.PathLike[str] | None = None) -> FoundryApplication:
    """Load explicit configuration and assemble only real production adapters."""

    return build_application(load_foundry_config(path))


def build_application(config: FoundryConfig) -> FoundryApplication:
    """Build the one production object graph used by ``generate``.

    Credentials are resolved from the explicitly configured handles once.  Raw
    values remain process-private and are registered only as in-memory canaries
    on stores that must reject accidental persistence.
    """

    environment = _authorized_environment(config, os.environ)
    canaries = _collect_secret_canaries(config, environment)
    _prepare_state_root(config.state_root)

    artifacts = ArtifactStore(
        config.state_root / "artifacts",
        known_secret_canaries=canaries,
    )
    controller_artifacts = artifacts.issue_writer(
        producer="framework",
        allowed_artifact_types=("environment_package_manifest",),
        allowed_artifact_type_prefixes=(
            "control.",
            "design.",
            "discovery.",
            "expansion.",
            "release.",
        ),
        allowed_event_type_prefixes=(
            "design_",
            "discovery_",
            "expansion_",
            "generation_",
            "judge_",
        ),
    )
    designer_artifacts = artifacts.issue_writer(
        producer="environment-designer",
        allowed_artifact_types=(
            "control.feedback_diagnostic",
            "control.feedback_result",
        ),
        allowed_artifact_type_prefixes=("design.", "discovery."),
        allowed_event_type_prefixes=("design_",),
    )
    research_artifacts = artifacts.issue_writer(
        producer="research-toolchain",
        allowed_artifact_type_prefixes=("evidence.",),
    )
    builder_artifacts = artifacts.issue_writer(
        producer="environment-builder",
        allowed_artifact_type_prefixes=("build.",),
    )
    judge_artifacts = artifacts.issue_writer(
        producer="environment-judge",
        allowed_artifact_types=("judge_report",),
        allowed_artifact_type_prefixes=("judge.",),
    )
    expansion_runner_artifacts = artifacts.issue_writer(
        producer="expansion-runner",
        allowed_artifact_types=(
            "expansion.pool_snapshot",
            "expansion.operator_catalog",
            "expansion.source_catalog",
            "expansion.campaign",
            "expansion.source_request",
            "expansion.source_result",
            "expansion.clue_snapshot",
            "expansion.context",
            "expansion.mutation_intent",
            "expansion.campaign_report",
            "expansion.policy_checkpoint",
            "expansion.candidate_outcome",
        ),
        allowed_artifact_type_prefixes=("control.",),
    )
    expansion_designer_artifacts = artifacts.issue_writer(
        producer="expansion-designer",
        allowed_artifact_types=(
            "expansion.evidence_graph",
            "expansion.coverage_map",
            "expansion.world_spec",
            "expansion.identity_decision",
            "expansion.semantic_delta",
            "expansion.semantic_lineage",
            "expansion.environment_design",
        ),
    )
    expansion_source_artifacts = artifacts.issue_writer(
        producer="expansion-source",
        allowed_artifact_types=(
            "expansion.source_hypothesis",
            "expansion.source_clue",
            "expansion.source_result",
        ),
    )
    artifacts.seal_capability_issuance()
    registry = EnvironmentRegistry(
        config.state_root / "registry",
        artifacts,
        known_secret_canaries=canaries,
        reservation_ttl_seconds=config.expansion.version_reservation_ttl_seconds,
    )
    profiles = IsolatedAgentProfileProvider(
        config.agent,
        source_environment=environment,
    )
    telemetry = TelemetryStore(
        config.state_root / "telemetry",
        commit_batch_size=config.observability.commit_batch_size,
    )
    codex_backend = CodexSdkBackend(
        max_concurrent_invocations=config.agent.max_concurrent_invocations,
        telemetry=telemetry,
    )
    direct_backend = DirectLlmBackend(
        max_concurrent_invocations=config.agent.max_concurrent_invocations,
        telemetry=telemetry,
    )
    backend: InvocationBackend = RoutedInvocationBackend(
        codex_backend=codex_backend,
        direct_backend=direct_backend,
        max_concurrent_invocations=config.agent.max_concurrent_invocations,
    )
    research = build_research_toolchain(
        config.research,
        source_environment=environment,
        telemetry=telemetry,
    )
    designer = EnvironmentDesigner(
        artifact_store=designer_artifacts,
        research_artifact_store=research_artifacts,
        invocation_backend=backend,
        profile_provider=profiles,
        research_toolchain=research,
    )
    discovery = DiscoveryService(
        designer=designer,
        artifact_store=designer_artifacts,
        research_toolchain=research,
    )
    expansion_designer = ExpansionDesigner(
        designer=designer,
        artifact_store=expansion_designer_artifacts,
        research_toolchain=research,
    )
    expansion_source_engine = EvidenceBackedExpansionSource(
        designer=designer,
        artifact_store=expansion_source_artifacts,
        research_toolchain=research,
    )
    expansion_source = ExpansionSourceRouter((expansion_source_engine,))
    for configured_source in config.expansion.sources:
        expansion_source.validate_descriptor(configured_source.descriptor())
    builder = EnvironmentBuilder(
        artifact_store=builder_artifacts,
        invocation_backend=backend,
        profile_provider=profiles,
        dependency_network_domains=config.agent.engineer_dependency_network_domains,
        maximum_repair_attempts=max(
            config.generation_budget.repair_attempts,
            config.expansion.candidate_budget.repair_attempts,
        ),
        # Keep the user-configured multi-turn Builder budget logical.  The
        # Builder reserves this observed Provider ceiling for one physical
        # turn and the Scheduler owns any durable continuation.
        turn_token_limit=config.agent.environment_codegen_physical_turn_token_limit,
        turn_timeout_seconds=config.agent.environment_codegen_invocation_timeout_seconds,
    )
    verifier_compiler = VerifierCompiler(
        artifact_store=judge_artifacts,
        invocation_backend=backend,
        profile_provider=profiles,
        maximum_structured_reworks=config.judge.maximum_structured_reworks,
        maximum_tasks_per_batch=config.judge.maximum_tasks_per_verifier_batch,
    )
    clean_builder = _clean_candidate_builder(config)
    judge = EnvironmentJudge(
        artifact_store=judge_artifacts,
        interactive_challenger=InteractiveChallengerStrategy(
            invocation_backend=backend,
            profile_provider=profiles,
        ),
        clean_builder=clean_builder,
        runtime_isolation=IsolationPolicy(purpose="runtime"),
        telemetry=telemetry,
        known_secret_canaries=canaries,
    )
    controller = FoundryController(
        config=config,
        artifact_store=controller_artifacts,
        expansion_artifact_store=expansion_runner_artifacts,
        profile_provider=profiles,
        designer=designer,
        discovery=discovery,
        expansion_designer=expansion_designer,
        expansion_source=expansion_source,
        builder=builder,
        verifier_compiler=verifier_compiler,
        judge=judge,
        registry=registry,
        telemetry=telemetry,
        known_secret_canaries=canaries,
    )
    return FoundryApplication(
        config=config,
        artifacts=artifacts,
        registry=registry,
        profiles=profiles,
        backend=backend,
        telemetry=telemetry,
        research=research,
        designer=designer,
        discovery=discovery,
        expansion_source=expansion_source,
        expansion_designer=expansion_designer,
        builder=builder,
        verifier_compiler=verifier_compiler,
        judge=judge,
        controller=controller,
    )


def open_registry(config: FoundryConfig) -> RegistryReader:
    """Open the durable Registry for offline read commands.

    Listing and inspection do not need model or research credentials.  This is
    intentionally not a second generation composition path.
    """

    _prepare_state_root(config.state_root)
    artifacts = ArtifactStore(config.state_root / "artifacts")
    artifacts.seal_capability_issuance()
    return RegistryReader(
        EnvironmentRegistry(
            config.state_root / "registry",
            artifacts,
            reservation_ttl_seconds=config.expansion.version_reservation_ttl_seconds,
        )
    )


def open_consumption(config: FoundryConfig) -> ConsumptionApplication:
    """Open real local Suite consumption without resolving LLM/search credentials."""

    _prepare_state_root(config.state_root)
    artifacts = ArtifactStore(config.state_root / "artifacts")
    feedback_artifacts = artifacts.issue_writer(
        producer=CAPABILITY_FEEDBACK_PRODUCER,
        allowed_artifact_types=(CAPABILITY_FEEDBACK_ARTIFACT_TYPE,),
        allowed_artifact_id_prefixes=(CAPABILITY_FEEDBACK_ARTIFACT_ID_PREFIX,),
    )
    artifacts.seal_capability_issuance()
    registry = EnvironmentRegistry(
        config.state_root / "registry",
        artifacts,
        reservation_ttl_seconds=config.expansion.version_reservation_ttl_seconds,
    )
    clean_builder = _clean_candidate_builder(config)
    return ConsumptionApplication(
        registry=RegistryReader(registry),
        rollout=LocalRolloutConsumer(
            registry=registry,
            clean_builder=clean_builder,
            runtime_isolation=IsolationPolicy(purpose="runtime"),
        ),
        feedback=FeedbackRecorder(
            registry=registry,
            artifact_store=feedback_artifacts,
        ),
    )


def open_campaigns(config: FoundryConfig) -> CampaignReader:
    """Open Campaign state for inspection without resolving model credentials."""

    _prepare_state_root(config.state_root)
    artifacts = ArtifactStore(config.state_root / "artifacts")
    artifacts.seal_capability_issuance()
    return CampaignReader(CampaignStore(config.state_root / "campaigns"), artifacts)


def open_direct_runs(config: FoundryConfig) -> DirectRunReader:
    """Open durable Direct run projections without model or research credentials."""

    _prepare_state_root(config.state_root)
    artifacts = ArtifactStore(config.state_root / "artifacts")
    artifacts.seal_capability_issuance()
    return DirectRunReader(
        DirectJobStore(config.state_root / "direct-jobs"),
        artifacts,
        TelemetryStore(
            config.state_root / "telemetry",
            commit_batch_size=config.observability.commit_batch_size,
        ),
        WorkControlStore(config.state_root / "work-control"),
    )


def open_observability(config: FoundryConfig) -> ObservabilityReader:
    """Open the secret-screened, read-side Agent observability plane.

    The reader needs in-memory canaries to re-screen source and Tier B text
    before displaying it.  It does not construct an InvocationBackend or make
    an external model call.
    """

    is_reserved_live = ".agent-world-live" in config.state_root.parts
    if is_reserved_live and not is_marked_test_node_diagnostic_state_root(config.state_root):
        # This is a lexical guard deliberately placed before any filesystem
        # access.  Live auth state is never an observability input.
        raise ApplicationConfigurationError(
            "observability cannot access the reserved live state directory"
        )
    environment = _authorized_environment(config, os.environ)
    canaries = _collect_secret_canaries(config, environment)
    _prepare_state_root(config.state_root)
    artifacts = ArtifactStore(
        config.state_root / "artifacts",
        known_secret_canaries=canaries,
    )
    artifacts.seal_capability_issuance()
    return ObservabilityReader(
        root=ObservabilityRoot(config.state_root),
        artifacts=artifacts,
        heads=WorkControlStore(config.state_root / "work-control"),
        telemetry=TelemetryStore(
            config.state_root / "telemetry",
            commit_batch_size=config.observability.commit_batch_size,
        ),
        known_secret_canaries=canaries,
        tier_a_keep_last_scopes=config.observability.tier_a_keep_last_scopes,
    )


def open_debug_transcripts(
    config: FoundryConfig,
    *,
    enabled: bool | None = None,
) -> DebugTranscriptWriter:
    """Open the explicitly opt-in local transcript sink without workflow authority."""

    is_reserved_live = ".agent-world-live" in config.state_root.parts
    if is_reserved_live and not is_marked_test_node_diagnostic_state_root(config.state_root):
        raise ApplicationConfigurationError(
            "observability cannot access the reserved live state directory"
        )
    environment = _authorized_environment(config, os.environ)
    canaries = _collect_secret_canaries(config, environment)
    _prepare_state_root(config.state_root)
    return DebugTranscriptWriter(
        root=ObservabilityRoot(config.state_root),
        known_secret_canaries=canaries,
        enabled=enabled,
    )


def open_telemetry(config: FoundryConfig) -> TelemetryStore:
    """Open the credential-free operational evidence plane."""

    _prepare_state_root(config.state_root)
    return TelemetryStore(
        config.state_root / "telemetry",
        commit_batch_size=config.observability.commit_batch_size,
    )


def _authorized_environment(
    config: FoundryConfig,
    source: Mapping[str, str],
) -> dict[str, str]:
    names = {
        "PATH",
        "LANG",
        "LC_ALL",
        "TZ",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
    }
    names.add(config.agent.api_key_environment)
    if config.agent.openai_base_url_environment is not None:
        names.add(config.agent.openai_base_url_environment)
    if config.research.jina_api_key_environment is not None:
        names.add(config.research.jina_api_key_environment)
    return {name: source[name] for name in sorted(names) if name in source}


def _clean_candidate_builder(config: FoundryConfig) -> CleanCandidateBuilder:
    """Assemble the clean-build boundary with a safe configuration diagnosis."""

    try:
        return CleanCandidateBuilder(
            build_isolation=IsolationPolicy(purpose="build"),
            uv_cache_dir=config.judge.uv_cache_dir,
            timeout_seconds=config.judge.clean_build_timeout_seconds,
        )
    except ValueError as exc:
        raise ApplicationConfigurationError(
            "judge clean-build configuration is invalid; "
            "verify judge.uv_cache_dir is a real directory when configured"
        ) from exc


def _prepare_state_root(path: Path) -> None:
    requested = path.expanduser()
    try:
        if requested.exists() and requested.is_symlink():
            raise ApplicationConfigurationError("state_root cannot be a symbolic link")
        requested.mkdir(parents=True, exist_ok=True, mode=0o700)
        if requested.is_symlink() or not requested.is_dir():
            raise ApplicationConfigurationError("state_root must be a real directory")
        if os.name != "nt":
            requested.chmod(0o700)
    except ApplicationConfigurationError:
        raise
    except OSError:
        raise ApplicationConfigurationError("state_root is not securely accessible") from None


def _collect_secret_canaries(
    config: FoundryConfig,
    environment: Mapping[str, str],
) -> tuple[bytes, ...]:
    canaries: set[bytes] = set()
    agent = config.agent
    canaries.add(
        _required_environment_secret(
            environment,
            agent.api_key_environment,
            purpose="model credential",
            # API-compatible gateways legitimately issue compact opaque
            # credentials.  The redactor's exact-value protection starts
            # at four bytes, so requiring a longer token here would make
            # a real configured backend unusable without adding safety.
            minimum=4,
        )
    )
    if agent.openai_base_url_environment is not None:
        canaries.add(
            _required_environment_secret(
                environment,
                agent.openai_base_url_environment,
                purpose="model routing value",
                minimum=4,
            )
        )

    research_name = config.research.jina_api_key_environment
    if research_name is not None:
        value = environment.get(research_name)
        if value:
            canaries.add(
                _validate_canary(
                    value,
                    purpose="research credential",
                    minimum=4,
                )
            )
        elif config.research.provider == "jina":
            raise ApplicationConfigurationError(
                f"research credential environment {research_name!r} is unavailable"
            )
    return tuple(sorted(canaries))


def _required_environment_secret(
    environment: Mapping[str, str],
    name: str,
    *,
    purpose: str,
    minimum: int,
) -> bytes:
    value = environment.get(name)
    if not value:
        raise ApplicationConfigurationError(f"{purpose} environment {name!r} is unavailable")
    return _validate_canary(value, purpose=purpose, minimum=minimum)


def _validate_canary(value: str, *, purpose: str, minimum: int) -> bytes:
    encoded = value.encode("utf-8")
    if not minimum <= len(encoded) <= _MAX_CANARY_BYTES:
        raise ApplicationConfigurationError(
            f"{purpose} has an invalid size for safe in-memory redaction"
        )
    return encoded


__all__ = [
    "ApplicationConfigurationError",
    "CampaignReader",
    "ConsumptionApplication",
    "DirectRunReader",
    "FoundryApplication",
    "RegistryReader",
    "build_application",
    "load_application",
    "open_campaigns",
    "open_consumption",
    "open_direct_runs",
    "open_debug_transcripts",
    "open_observability",
    "open_registry",
]
