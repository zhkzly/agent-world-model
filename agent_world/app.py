"""Production composition root for the Agent World Foundry.

The pipeline core owns workflow and release decisions; this module is the only
place that chooses concrete production adapters.  It deliberately contains no
template backend, replay path, fixture registry, or alternate success path.
"""

from __future__ import annotations

import json
import os
import stat
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
    EnvironmentSuiteSnapshot,
    ExpansionCampaign,
    SuiteSelectionRequest,
)
from agent_world.control import (
    BudgetLease,
    CampaignRunCheckpoint,
    CampaignStore,
    DirectJobStore,
    JobRunSnapshot,
    TelemetryStore,
)
from agent_world.controller import FoundryController
from agent_world.designer import (
    DiscoveryService,
    EnvironmentDesigner,
    EvidenceBackedExpansionSource,
    ExpansionDesigner,
    ExpansionSourceRouter,
)
from agent_world.expansion_runner import validate_campaign_report_graph
from agent_world.invocation import CodexSdkBackend
from agent_world.judge import (
    CleanCandidateBuilder,
    EnvironmentJudge,
    InteractiveChallengerStrategy,
    IsolationPolicy,
    VerifierCompiler,
)
from agent_world.registry import (
    EnvironmentRegistry,
    ReleaseRecord,
    ReleaseStatus,
)
from agent_world.research import ResearchToolchain, build_research_toolchain

_MAX_AUTH_FILE_BYTES = 4 * 1024 * 1024
_MAX_CANARY_BYTES = 8192
_SENSITIVE_AUTH_KEYS = (
    "api_key",
    "apikey",
    "authorization",
    "bearer",
    "cookie",
    "credential",
    "password",
    "refresh",
    "secret",
    "session",
    "token",
)


class ApplicationConfigurationError(RuntimeError):
    """A fail-closed assembly error whose message is safe for CLI output."""


@dataclass(frozen=True, slots=True)
class FoundryApplication:
    """Fully assembled production graph for generation and future campaigns."""

    config: FoundryConfig
    artifacts: ArtifactStore
    registry: EnvironmentRegistry
    profiles: IsolatedAgentProfileProvider
    backend: CodexSdkBackend
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
        leases = tuple(
            self._artifacts.get_json(ref, BudgetLease)
            for ref in snapshot.latest_artifact_refs
            if ref.artifact_type == "control.budget_lease"
        )
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
        return {
            "spans": list(spans),
            "orphaned_spans": list(orphaned_spans),
            "builder_workspace": self._latest_builder_workspace(snapshot),
            "usage": {
                "observed_actual": snapshot.observed_actual_budget.model_dump(mode="json"),
                "unknown_upper_bound": snapshot.unknown_upper_bound_budget.model_dump(
                    mode="json"
                ),
                "conservative_committed": (
                    snapshot.conservative_committed_budget.model_dump(mode="json")
                ),
                "inflight_observed": {
                    "llm_tokens": None,
                    "event_count": sum(
                        int(item["observed_event_count"]) for item in spans
                    ),
                    "protocol_tool_event_count": sum(
                        int(item["observed_protocol_tool_event_count"])
                        for item in spans
                    ),
                },
                "active_reserved_exposure": reserved_exposure,
                "active_lease_count": len(active_leases),
                "orphaned_lease_count": (
                    len(observed_active_leases) if snapshot.status != "running" else 0
                ),
            },
        }

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
        allowed_artifact_type_prefixes=("control.", "discovery.", "expansion.", "release."),
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
    backend = CodexSdkBackend(
        max_concurrent_invocations=config.agent.max_concurrent_invocations,
        telemetry=telemetry,
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
        turn_token_limit=config.agent.environment_codegen_turn_token_limit,
        turn_timeout_seconds=config.agent.environment_codegen_invocation_timeout_seconds,
    )
    verifier_compiler = VerifierCompiler(
        artifact_store=judge_artifacts,
        invocation_backend=backend,
        profile_provider=profiles,
        maximum_structured_reworks=config.judge.maximum_structured_reworks,
        maximum_tasks_per_batch=config.judge.maximum_tasks_per_verifier_batch,
    )
    clean_builder = CleanCandidateBuilder(
        build_isolation=IsolationPolicy(purpose="build"),
        uv_cache_dir=config.judge.uv_cache_dir,
        timeout_seconds=config.judge.clean_build_timeout_seconds,
    )
    judge = EnvironmentJudge(
        artifact_store=judge_artifacts,
        interactive_challenger=InteractiveChallengerStrategy(
            invocation_backend=backend,
            profile_provider=profiles,
        ),
        clean_builder=clean_builder,
        runtime_isolation=IsolationPolicy(purpose="runtime"),
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
    clean_builder = CleanCandidateBuilder(
        build_isolation=IsolationPolicy(purpose="build"),
        uv_cache_dir=config.judge.uv_cache_dir,
        timeout_seconds=config.judge.clean_build_timeout_seconds,
    )
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
    if config.agent.api_key_environment is not None:
        names.add(config.agent.api_key_environment)
    if config.research.jina_api_key_environment is not None:
        names.add(config.research.jina_api_key_environment)
    return {name: source[name] for name in sorted(names) if name in source}


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
    if agent.api_key_environment is not None:
        canaries.add(
            _required_environment_secret(
                environment,
                agent.api_key_environment,
                purpose="model credential",
                minimum=8,
            )
        )
    else:
        assert agent.chatgpt_auth_file is not None
        auth = _read_authorized_auth_json(agent.chatgpt_auth_file)
        canaries.update(_auth_secret_canaries(auth))

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


def _read_authorized_auth_json(path: Path) -> dict[str, object]:
    """Read one explicitly authorized file without following a symlink race."""

    descriptor: int | None = None
    try:
        if not path.is_absolute():
            raise ApplicationConfigurationError(
                "authorized Codex login file must use an absolute path"
            )
        before = os.lstat(path)
        if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
            raise ApplicationConfigurationError("authorized Codex login file is unavailable")
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or (
            opened.st_dev,
            opened.st_ino,
        ) != (before.st_dev, before.st_ino):
            raise ApplicationConfigurationError("authorized Codex login file changed while read")
        if opened.st_size <= 0 or opened.st_size > _MAX_AUTH_FILE_BYTES:
            raise ApplicationConfigurationError("authorized Codex login file has an invalid size")
        if os.name != "nt" and stat.S_IMODE(opened.st_mode) & 0o077:
            raise ApplicationConfigurationError(
                "authorized Codex login file permissions are too broad"
            )
        chunks: list[bytes] = []
        remaining = opened.st_size + 1
        while remaining > 0:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        if len(raw) != opened.st_size or len(raw) > _MAX_AUTH_FILE_BYTES:
            raise ApplicationConfigurationError("authorized Codex login file changed while read")
        parsed = json.loads(raw, parse_constant=_reject_nonfinite_json)
        if not isinstance(parsed, dict) or not parsed:
            raise ApplicationConfigurationError("authorized Codex login file is invalid")
        return parsed
    except ApplicationConfigurationError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, TypeError):
        # Never chain parser/OS details: either can contain source paths or raw values.
        raise ApplicationConfigurationError("authorized Codex login file is invalid") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _auth_secret_canaries(value: Mapping[str, object]) -> tuple[bytes, ...]:
    canaries: set[bytes] = set()

    def visit(node: object, *, sensitive_parent: bool = False) -> None:
        if isinstance(node, Mapping):
            for raw_key, child in node.items():
                key = str(raw_key).casefold().replace("-", "_")
                sensitive = sensitive_parent or any(part in key for part in _SENSITIVE_AUTH_KEYS)
                visit(child, sensitive_parent=sensitive)
            return
        if isinstance(node, list):
            for child in node:
                visit(child, sensitive_parent=sensitive_parent)
            return
        if sensitive_parent and isinstance(node, str) and node:
            canaries.add(
                _validate_canary(
                    node,
                    purpose="authorized Codex login credential",
                    minimum=4,
                )
            )

    visit(value)
    if not canaries:
        raise ApplicationConfigurationError(
            "authorized Codex login file contains no recognizable credential material"
        )
    return tuple(sorted(canaries))


def _reject_nonfinite_json(value: str) -> None:
    raise ValueError(f"non-finite JSON value is forbidden: {value}")


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
    "open_registry",
]
