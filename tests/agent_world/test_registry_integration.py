from __future__ import annotations

import asyncio
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import HttpUrl
from v3_fixture import ReleaseGraph, build_release_graph

from agent_world.agent_profiles import AgentProfileProvider
from agent_world.artifact_store import ArtifactStore, ArtifactWriter
from agent_world.builder import EnvironmentBuilder
from agent_world.config import AgentBackendConfig, FoundryConfig, ResearchConfig
from agent_world.contracts import (
    ArtifactRef,
    Budget,
    BudgetUsage,
    CurriculumSamplingPolicy,
    EnvironmentJob,
    EnvironmentPackageManifest,
    EnvironmentRequest,
    ExpansionSourceCatalog,
    ExpansionSourceDescriptor,
    FrameworkPackagePayload,
    GenerationContext,
    IntegrationReport,
    JudgeReport,
    MutationIntent,
    PermissionScope,
    ReleaseProfile,
    SuiteSelectionRequest,
    sha256_digest,
)
from agent_world.control import (
    DirectJobResumeRequiredError,
    DirectRequestConflictError,
    GenerationWorkGraph,
    JobRunSnapshot,
    LeaseBudgetLedger,
    MetricPoint,
    ReleaseDossier,
    TelemetryReleaseSummary,
    TelemetryStore,
    WorkAttempt,
    WorkControlRuntime,
    WorkGraphEpoch,
    deterministic_boundary_work_definition,
    new_direct_job_head,
)
from agent_world.controller import FoundryController, GenerateResult
from agent_world.designer import (
    DiscoveryService,
    EnvironmentDesigner,
    EvidenceBackedExpansionSource,
    ExpansionDesigner,
    ExpansionSourceRouter,
)
from agent_world.invocation import CodexSdkBackend
from agent_world.judge import EnvironmentJudge, VerifierCompiler
from agent_world.registry import (
    EnvironmentRegistry,
    PackageVersionReservation,
    ParentNotEligibleError,
    RegistryIntegrityError,
    ReleaseRejectedError,
    ReservationConflictError,
    ReservationExpiredError,
    UnsafePackageError,
)
from agent_world.research import build_research_toolchain

_release_graph = build_release_graph


def _framework_writer(store: ArtifactStore) -> ArtifactWriter:
    return store.issue_writer(
        producer="framework",
        allowed_artifact_types=(
            "curriculum",
            "environment_candidate",
            "environment_design",
            "environment_package_manifest",
            "evaluation_evidence",
            "evidence_summary",
            "implementation_contract",
            "public_verifier",
            "task_materializer_protocol",
            "test.semantic_source",
        ),
        allowed_artifact_type_prefixes=("control.", "discovery.", "expansion.", "release."),
        allowed_event_type_prefixes=(
            "design_",
            "discovery_",
            "expansion_",
            "generation_",
            "judge_",
        ),
    )


def _judge_writer(store: ArtifactStore) -> ArtifactWriter:
    return store.issue_writer(
        producer="environment-judge",
        allowed_artifact_types=("judge_report",),
        allowed_artifact_type_prefixes=("judge.",),
    )


def _commit(
    store: ArtifactStore,
    artifact_id: str,
    artifact_type: str,
    value: dict[str, object],
    *,
    dependencies: tuple[ArtifactRef, ...] = (),
) -> ArtifactRef:
    return _framework_writer(store).put_json(
        artifact_id=artifact_id,
        artifact_type=artifact_type,
        value=value,
        dependencies=dependencies,
    )


def _reserve(
    registry: EnvironmentRegistry,
    graph: ReleaseGraph,
    *,
    package_id: str | None = None,
    version: str | None = None,
) -> PackageVersionReservation:
    return registry.reserve_package_version(
        package_id or graph.package_id,
        version or graph.version,
        graph.owner_ref,
    )


def _direct_controller(
    root: Path,
    store: ArtifactStore,
    registry: EnvironmentRegistry,
    release_profile: ReleaseProfile,
) -> FoundryController:
    agent = AgentBackendConfig(
        model="gpt-5",
        api_key_environment="AGENT_WORLD_TEST_MODEL_KEY",
    )
    research_config = ResearchConfig(
        provider="searxng",
        searxng_base_url=HttpUrl("http://127.0.0.1:9"),
        searxng_allow_private_endpoint=True,
        use_jina_reader_fallback=False,
    )
    config = FoundryConfig(
        state_root=root,
        agent=agent,
        research=research_config,
        release_profile=release_profile,
    )
    profiles = AgentProfileProvider(agent, source_environment={})
    backend = CodexSdkBackend()
    research = build_research_toolchain(research_config, source_environment={})
    controller_artifacts = _framework_writer(store)
    designer_artifacts = store.issue_writer(
        producer="environment-designer",
        allowed_artifact_type_prefixes=("design.", "discovery."),
    )
    research_artifacts = store.issue_writer(
        producer="research-toolchain",
        allowed_artifact_type_prefixes=("evidence.",),
    )
    builder_artifacts = store.issue_writer(
        producer="environment-builder",
        allowed_artifact_type_prefixes=("build.",),
    )
    judge_artifacts = _judge_writer(store)
    expansion_runner_artifacts = store.issue_writer(
        producer="expansion-runner",
        allowed_artifact_type_prefixes=("control.", "expansion."),
    )
    expansion_designer_artifacts = store.issue_writer(
        producer="expansion-designer",
        allowed_artifact_type_prefixes=("expansion.",),
    )
    expansion_source_artifacts = store.issue_writer(
        producer="expansion-source",
        allowed_artifact_types=(
            "expansion.source_hypothesis",
            "expansion.source_clue",
            "expansion.source_result",
        ),
    )
    designer = EnvironmentDesigner(
        artifact_store=designer_artifacts,
        research_artifact_store=research_artifacts,
        invocation_backend=backend,
        profile_provider=profiles,
        research_toolchain=research,
    )
    return FoundryController(
        config=config,
        artifact_store=controller_artifacts,
        expansion_artifact_store=expansion_runner_artifacts,
        profile_provider=profiles,
        designer=designer,
        discovery=DiscoveryService(
            designer=designer,
            artifact_store=designer_artifacts,
            research_toolchain=research,
        ),
        expansion_designer=ExpansionDesigner(
            designer=designer,
            artifact_store=expansion_designer_artifacts,
            research_toolchain=research,
        ),
        expansion_source=ExpansionSourceRouter(
            (
                EvidenceBackedExpansionSource(
                    designer=designer,
                    artifact_store=expansion_source_artifacts,
                    research_toolchain=research,
                ),
            )
        ),
        builder=EnvironmentBuilder(
            artifact_store=builder_artifacts,
            invocation_backend=backend,
            profile_provider=profiles,
        ),
        verifier_compiler=VerifierCompiler(
            artifact_store=judge_artifacts,
            invocation_backend=backend,
            profile_provider=profiles,
        ),
        judge=EnvironmentJudge(artifact_store=judge_artifacts),
        registry=registry,
    )


def test_frozen_node_resume_discovers_epoch_from_context_not_snapshot_projection(
    tmp_path: Path,
) -> None:
    """A crash may omit an already-frozen epoch from the compact run summary.

    Recovery must still use the exact Context -> Epoch -> WorkDefinition ->
    stopped WorkHead closure.  This is intentionally a control-plane proof;
    it does not simulate an Agent or a Provider response.
    """

    state_root = tmp_path / "foundry"
    store = ArtifactStore(state_root / "artifacts")
    registry = EnvironmentRegistry(state_root / "registry", store)
    release_profile = ReleaseProfile(profile_id="frozen-resume-projection-gap")
    controller = _direct_controller(state_root, store, registry, release_profile)
    artifacts = controller.artifacts
    budget = Budget(wall_seconds=600)
    request = EnvironmentRequest(
        request_id="request:frozen-resume-projection-gap",
        need="Resume exactly one frozen node without replaying its prefix.",
        budget=budget,
        release_profile=release_profile,
    )
    request_ref = artifacts.put_json(
        artifact_id=request.request_id,
        artifact_type="control.environment_request",
        value=request,
    )
    job = EnvironmentJob(
        job_id="generate-job:frozen-resume-projection-gap",
        kind="generate",
        request_ref=request_ref,
        budget=budget,
        release_profile=release_profile,
    )
    job_ref = artifacts.put_json(
        artifact_id=f"{job.job_id}:job",
        artifact_type="control.environment_job",
        value=job,
        dependencies=(request_ref,),
    )
    context = GenerationContext(
        context_id="generation-context:frozen-resume-projection-gap",
        job_ref=job_ref,
        kind="generate",
        request_ref=request_ref,
        permissions=PermissionScope(),
        budget=budget,
        release_profile=release_profile,
    )
    context_ref = artifacts.put_json(
        artifact_id=context.context_id,
        artifact_type="control.generation_context",
        value=context,
        dependencies=context.root_refs,
    )
    definition = deterministic_boundary_work_definition(
        scope_id=job.job_id,
        component="design",
        stage="resume_boundary",
        artifact_slot="resume_boundary",
        dependency_coordinates=(),
        claim_id="resume_boundary.passed",
        claim="The frozen resume boundary has a durable stopped attempt.",
        timing_reason="The controller must recover the exact stopped node.",
        effect="block_release",
        success_maturity="resume_boundary_closed",
    )
    graph = GenerationWorkGraph.compile((definition,), mode="diagnostic")
    definition_ref = artifacts.put_json(
        artifact_id=f"work-definition:{definition.work_id}",
        artifact_type="control.work_definition",
        value=definition,
        dependencies=(context_ref,),
    )
    manifest = graph.manifest(
        topology_id="topology:frozen-resume-projection-gap",
        external_root_refs=(context_ref,),
    )
    manifest_ref = artifacts.put_json(
        artifact_id=f"work-graph-manifest:{manifest.graph_id}",
        artifact_type="control.work_graph_manifest",
        value=manifest,
        dependencies=(context_ref, definition_ref),
    )
    epoch = WorkGraphEpoch(
        epoch_id="epoch:bootstrap:frozen-resume-projection-gap",
        scope_id=job.job_id,
        epoch_kind="bootstrap",
        context_ref=context_ref,
        manifest_ref=manifest_ref,
    )
    epoch_ref = artifacts.put_json(
        artifact_id=epoch.epoch_id,
        artifact_type="control.work_graph_epoch",
        value=epoch,
        dependencies=(context_ref, manifest_ref, definition_ref),
    )

    runtime = WorkControlRuntime(
        artifacts=artifacts,
        heads=controller.work_control,
        budget=LeaseBudgetLedger(budget),
    )
    with controller.work_control.exclusive(definition.coordinate) as lock:
        started = runtime.begin(
            lock,
            definition=definition,
            input_refs=(context_ref,),
            elapsed_wall_seconds=0,
        )
    started_attempt = store.get_json(started.attempt_ref, WorkAttempt)
    interrupted_attempt = started_attempt.model_copy(
        update={
            "status": "interrupted",
            "finished_at": datetime.now(UTC),
            "failure_code": "process_interrupted_cancelled",
        }
    )
    interrupted_attempt_ref = artifacts.put_json(
        artifact_id=interrupted_attempt.attempt_id,
        artifact_type="control.work_attempt",
        value=interrupted_attempt,
        dependencies=(started.attempt_ref,),
    )
    with controller.work_control.exclusive(definition.coordinate) as lock:
        controller.work_control.compare_and_swap(
            lock,
            expected_head=started,
            next_head=started.model_copy(
                update={
                    "revision": started.revision + 1,
                    "status": "interrupted",
                    "attempt_ref": interrupted_attempt_ref,
                    "updated_at": datetime.now(UTC),
                }
            ),
        )

    # This deliberately omits both context_ref and epoch_ref: it reproduces a
    # controller crash between epoch persistence and compact-snapshot update.
    snapshot = JobRunSnapshot(
        run_id="run:frozen-resume-projection-gap",
        job_ref=job_ref,
        revision=1,
        status="failed",
        reserved_budget=budget,
        observed_actual_budget=BudgetUsage(),
        unknown_upper_bound_budget=BudgetUsage(),
        conservative_committed_budget=BudgetUsage(),
        latest_artifact_refs=(job_ref, request_ref),
        failure_code="controller_interrupted",
        failure_summary="The compact run projection did not record the frozen epoch.",
    )
    snapshot_ref = artifacts.put_json(
        artifact_id=f"{snapshot.run_id}:state",
        artifact_type="control.job_run_snapshot",
        value=snapshot,
        dependencies=(job_ref, request_ref),
    )
    direct_head = new_direct_job_head(
        request_id=request.request_id,
        request_fingerprint=sha256_digest(b"frozen-resume-projection-gap"),
        request_ref=request_ref,
        job_ref=job_ref,
        scope_id=job.job_id,
        run_id=snapshot.run_id,
        snapshot_ref=snapshot_ref,
        snapshot_revision=snapshot.revision,
        status="failed",
    )

    selected = controller._select_frozen_resume_target(  # noqa: SLF001 - control-plane regression
        head=direct_head,
        from_frozen_epoch=None,
        from_coordinate="design.resume_boundary.resume_boundary",
    )

    assert selected == (
        snapshot_ref,
        snapshot,
        context_ref,
        epoch_ref,
        definition.coordinate,
        definition,
    )


def test_frozen_resume_selects_committed_but_stale_consumer_after_parent_revision(
    tmp_path: Path,
) -> None:
    """A repaired parent must resume its stale consumer, not an old downstream gate.

    This reproduces the Candidate r9 control-plane shape with deterministic
    boundaries: the consumer has a physical ``committed`` head, but its input
    closure names the parent's r1 Artifact.  After the parent commits r9, the
    frozen Scheduler must expose the consumer as the only resumable frontier.
    """

    state_root = tmp_path / "foundry"
    store = ArtifactStore(state_root / "artifacts")
    registry = EnvironmentRegistry(state_root / "registry", store)
    release_profile = ReleaseProfile(profile_id="stale-consumer-resume")
    controller = _direct_controller(state_root, store, registry, release_profile)
    artifacts = controller.artifacts
    budget = Budget(wall_seconds=600)
    request = EnvironmentRequest(
        request_id="request:stale-consumer-resume",
        need="Refresh only the consumer after its parent source revision changes.",
        budget=budget,
        release_profile=release_profile,
    )
    request_ref = artifacts.put_json(
        artifact_id=request.request_id,
        artifact_type="control.environment_request",
        value=request,
    )
    job = EnvironmentJob(
        job_id="generate-job:stale-consumer-resume",
        kind="generate",
        request_ref=request_ref,
        budget=budget,
        release_profile=release_profile,
    )
    job_ref = artifacts.put_json(
        artifact_id=f"{job.job_id}:job",
        artifact_type="control.environment_job",
        value=job,
        dependencies=(request_ref,),
    )
    context = GenerationContext(
        context_id="generation-context:stale-consumer-resume",
        job_ref=job_ref,
        kind="generate",
        request_ref=request_ref,
        permissions=PermissionScope(),
        budget=budget,
        release_profile=release_profile,
    )
    context_ref = artifacts.put_json(
        artifact_id=context.context_id,
        artifact_type="control.generation_context",
        value=context,
        dependencies=context.root_refs,
    )
    parent_r1 = deterministic_boundary_work_definition(
        scope_id=job.job_id,
        component="design",
        stage="candidate_source",
        artifact_slot="candidate_source",
        dependency_coordinates=(),
        claim_id="candidate.source.ready",
        claim="The Candidate source closure is ready for its consumer.",
        timing_reason="Integration requires one exact Candidate source revision.",
        effect="block_integration",
        success_maturity="candidate_ready",
    )
    integration = deterministic_boundary_work_definition(
        scope_id=job.job_id,
        component="integration",
        stage="candidate_integration",
        artifact_slot="integration_report",
        dependency_coordinates=(parent_r1.coordinate,),
        claim_id="candidate.integration.ready",
        claim="Integration validates the exact Candidate source closure.",
        timing_reason="A later gate may consume only current Integration evidence.",
        effect="block_release",
        success_maturity="integration_ready",
    )
    for definition in (parent_r1, integration):
        artifacts.put_json(
            artifact_id=f"work-definition:{definition.work_id}",
            artifact_type="control.work_definition",
            value=definition,
            dependencies=(context_ref,),
        )

    runtime = WorkControlRuntime(
        artifacts=artifacts,
        heads=controller.work_control,
        budget=LeaseBudgetLedger(budget),
    )
    source_r1 = artifacts.put_json(
        artifact_id="candidate:r1",
        artifact_type="control.candidate_source",
        value={"revision": "r1"},
        dependencies=(context_ref,),
    )
    runtime.execute_deterministic_boundary(
        definition=parent_r1,
        input_refs=(context_ref,),
        subject_ref=source_r1,
        output_refs=(source_r1,),
    )
    integration_r1 = artifacts.put_json(
        artifact_id="integration:r1",
        artifact_type="control.integration_report",
        value={"candidate_revision": "r1"},
        dependencies=(source_r1,),
    )
    runtime.execute_deterministic_boundary(
        definition=integration,
        input_refs=(context_ref, source_r1),
        subject_ref=integration_r1,
        output_refs=(integration_r1,),
    )

    # Change an acceptance-bearing definition field as well as the output.
    # Changing timing prose alone deliberately permits historical-commit reuse,
    # which is correct for a non-semantic scheduling adjustment but does not
    # model Candidate r9's new source closure.
    parent_r2 = parent_r1.model_copy(
        update={
            "claim": "The refreshed Candidate source closure is ready for its consumer.",
            "timing_reason": "The Candidate source revision was refreshed.",
        }
    )
    artifacts.put_json(
        artifact_id=f"work-definition:{parent_r2.work_id}",
        artifact_type="control.work_definition",
        value=parent_r2,
        dependencies=(context_ref,),
    )
    old_parent_head = controller.work_control.read_head(parent_r1.coordinate)
    assert old_parent_head is not None and old_parent_head.status == "committed"
    revision_runtime = WorkControlRuntime(
        artifacts=artifacts,
        heads=controller.work_control,
        budget=LeaseBudgetLedger(budget),
    )
    with controller.work_control.exclusive(parent_r1.coordinate) as lock:
        revision_runtime.supersede_stale(
            lock,
            definition=parent_r2,
            input_refs=(context_ref,),
            previous=old_parent_head,
            elapsed_wall_seconds=0,
        )
    source_r2 = artifacts.put_json(
        artifact_id="candidate:r2",
        artifact_type="control.candidate_source",
        value={"revision": "r2"},
        dependencies=(context_ref,),
    )
    revision_runtime.execute_deterministic_boundary(
        definition=parent_r2,
        input_refs=(context_ref,),
        subject_ref=source_r2,
        output_refs=(source_r2,),
    )

    graph = GenerationWorkGraph.compile((parent_r2, integration), mode="diagnostic")
    manifest = graph.manifest(
        topology_id="topology:stale-consumer-resume",
        external_root_refs=(context_ref,),
    )
    manifest_ref = artifacts.put_json(
        artifact_id=f"work-graph-manifest:{manifest.graph_id}",
        artifact_type="control.work_graph_manifest",
        value=manifest,
        dependencies=(context_ref,),
    )
    epoch = WorkGraphEpoch(
        epoch_id="epoch:bootstrap:stale-consumer-resume",
        scope_id=job.job_id,
        epoch_kind="bootstrap",
        context_ref=context_ref,
        manifest_ref=manifest_ref,
    )
    epoch_ref = artifacts.put_json(
        artifact_id=epoch.epoch_id,
        artifact_type="control.work_graph_epoch",
        value=epoch,
        dependencies=(context_ref, manifest_ref),
    )
    snapshot = JobRunSnapshot(
        run_id="run:stale-consumer-resume",
        job_ref=job_ref,
        revision=1,
        status="failed",
        reserved_budget=budget,
        observed_actual_budget=BudgetUsage(),
        unknown_upper_bound_budget=BudgetUsage(),
        conservative_committed_budget=BudgetUsage(),
        latest_artifact_refs=(job_ref, request_ref, context_ref, epoch_ref),
        failure_code="owner_lost",
        failure_summary="The original owner stopped after the parent revision committed.",
    )
    snapshot_ref = artifacts.put_json(
        artifact_id=f"{snapshot.run_id}:state",
        artifact_type="control.job_run_snapshot",
        value=snapshot,
        dependencies=(job_ref, context_ref, epoch_ref),
    )
    direct_head = new_direct_job_head(
        request_id=request.request_id,
        request_fingerprint=sha256_digest(b"stale-consumer-resume"),
        request_ref=request_ref,
        job_ref=job_ref,
        scope_id=job.job_id,
        run_id=snapshot.run_id,
        snapshot_ref=snapshot_ref,
        snapshot_revision=snapshot.revision,
        status="failed",
    )

    states = controller._frozen_epoch_schedule_states(  # noqa: SLF001 - control-plane proof
        context_ref=context_ref,
        epoch_ref=epoch_ref,
    )
    assert states[integration.coordinate.coordinate_key] == "stale"
    selected = controller._select_frozen_resume_target(  # noqa: SLF001 - control-plane proof
        head=direct_head,
        from_frozen_epoch=None,
        from_coordinate=None,
    )

    assert selected == (
        snapshot_ref,
        snapshot,
        context_ref,
        epoch_ref,
        integration.coordinate,
        integration,
    )


def test_resume_advances_an_explicit_committed_frontier_in_the_same_job(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A completed epoch can advance without reopening any of its own nodes.

    This is the control-plane half of recovery: the Runner independently proves
    active Commit closure immediately before it derives the suffix.  Here the
    Controller must preserve the original job/context/epoch and must not invent
    a stopped-coordinate retry authority.
    """

    state_root = tmp_path / "foundry"
    store = ArtifactStore(state_root / "artifacts")
    registry = EnvironmentRegistry(state_root / "registry", store)
    release_profile = ReleaseProfile(profile_id="committed-frontier")
    controller = _direct_controller(state_root, store, registry, release_profile)
    artifacts = controller.artifacts
    budget = Budget(wall_seconds=600)
    request = EnvironmentRequest(
        request_id="request:committed-frontier",
        need="Advance only the causal suffix of one fully committed epoch.",
        budget=budget,
        release_profile=release_profile,
    )
    request_ref = artifacts.put_json(
        artifact_id=request.request_id,
        artifact_type="control.environment_request",
        value=request,
    )
    job = EnvironmentJob(
        job_id="generate-job:committed-frontier",
        kind="generate",
        request_ref=request_ref,
        budget=budget,
        release_profile=release_profile,
    )
    job_ref = artifacts.put_json(
        artifact_id=f"{job.job_id}:job",
        artifact_type="control.environment_job",
        value=job,
        dependencies=(request_ref,),
    )
    context = GenerationContext(
        context_id="generation-context:committed-frontier",
        job_ref=job_ref,
        kind="generate",
        request_ref=request_ref,
        permissions=PermissionScope(),
        budget=budget,
        release_profile=release_profile,
    )
    context_ref = artifacts.put_json(
        artifact_id=context.context_id,
        artifact_type="control.generation_context",
        value=context,
        dependencies=context.root_refs,
    )
    definition = deterministic_boundary_work_definition(
        scope_id=job.job_id,
        component="design",
        stage="committed_frontier",
        artifact_slot="committed_frontier",
        dependency_coordinates=(),
        claim_id="committed_frontier.passed",
        claim="This frozen epoch is fully committed before its successor is derived.",
        timing_reason="A framework repair must not replay already committed work.",
        effect="block_release",
        success_maturity="committed_frontier_closed",
    )
    graph = GenerationWorkGraph.compile((definition,), mode="diagnostic")
    definition_ref = artifacts.put_json(
        artifact_id=f"work-definition:{definition.work_id}",
        artifact_type="control.work_definition",
        value=definition,
        dependencies=(context_ref,),
    )
    manifest = graph.manifest(
        topology_id="topology:committed-frontier",
        external_root_refs=(context_ref,),
    )
    manifest_ref = artifacts.put_json(
        artifact_id=f"work-graph-manifest:{manifest.graph_id}",
        artifact_type="control.work_graph_manifest",
        value=manifest,
        dependencies=(context_ref, definition_ref),
    )
    epoch = WorkGraphEpoch(
        epoch_id="epoch:bootstrap:committed-frontier",
        scope_id=job.job_id,
        epoch_kind="bootstrap",
        context_ref=context_ref,
        manifest_ref=manifest_ref,
    )
    epoch_ref = artifacts.put_json(
        artifact_id=epoch.epoch_id,
        artifact_type="control.work_graph_epoch",
        value=epoch,
        dependencies=(context_ref, manifest_ref, definition_ref),
    )
    output_ref = artifacts.put_json(
        artifact_id="committed-frontier:output",
        artifact_type="test.semantic_source",
        value={"status": "committed"},
        dependencies=(context_ref,),
    )
    runtime = WorkControlRuntime(
        artifacts=artifacts,
        heads=controller.work_control,
        budget=LeaseBudgetLedger(budget),
    )
    committed_head = runtime.execute_deterministic_boundary(
        definition=definition,
        input_refs=(context_ref,),
        subject_ref=output_ref,
        output_refs=(output_ref,),
    )
    assert committed_head.status == "committed"

    run_id = "run:committed-frontier"
    running_snapshot = JobRunSnapshot(
        run_id=run_id,
        job_ref=job_ref,
        revision=1,
        status="running",
        reserved_budget=budget,
        observed_actual_budget=BudgetUsage(),
        unknown_upper_bound_budget=BudgetUsage(),
        conservative_committed_budget=BudgetUsage(),
        latest_artifact_refs=(request_ref, job_ref, context_ref, epoch_ref),
    )
    running_snapshot_ref = artifacts.put_json(
        artifact_id=f"{run_id}:state",
        artifact_type="control.job_run_snapshot",
        value=running_snapshot,
        dependencies=(request_ref, job_ref, context_ref, epoch_ref),
    )
    snapshot = running_snapshot.model_copy(
        update={
            "revision": 2,
            "status": "failed",
            "failure_code": "framework_fix_pending",
            "failure_summary": (
                "A later control-plane boundary stopped after this frontier committed."
            ),
        }
    )
    snapshot_ref = artifacts.put_json(
        artifact_id=f"{run_id}:state",
        artifact_type="control.job_run_snapshot",
        value=snapshot,
        dependencies=(running_snapshot_ref, request_ref, job_ref, context_ref, epoch_ref),
    )
    failed_result = GenerateResult(
        run_id=run_id,
        status="failed",
        request_ref=request_ref,
        job_ref=job_ref,
        final_snapshot_ref=snapshot_ref,
        failure_code="framework_fix_pending",
        failure_summary="A later control-plane boundary stopped after this frontier committed.",
    )
    failed_result_ref = artifacts.put_json(
        artifact_id=f"{run_id}:generate-result",
        artifact_type="control.generate_result",
        value=failed_result,
        dependencies=(request_ref, job_ref, snapshot_ref),
    )
    fingerprint = controller._direct_request_fingerprint(  # noqa: SLF001
        request,
        enable_discovery=False,
        discovery_budget=controller.config.discovery_budget,
    )
    with controller.direct_jobs.exclusive(request.request_id) as lock:
        running_direct_head = new_direct_job_head(
            request_id=request.request_id,
            request_fingerprint=fingerprint,
            request_ref=request_ref,
            job_ref=job_ref,
            scope_id=job.job_id,
            run_id=run_id,
            snapshot_ref=running_snapshot_ref,
            snapshot_revision=running_snapshot.revision,
            status="running",
        )
        controller.direct_jobs.compare_and_swap(
            lock,
            expected_head=None,
            next_head=running_direct_head,
        )
        failed_direct_head = new_direct_job_head(
            request_id=request.request_id,
            request_fingerprint=fingerprint,
            request_ref=request_ref,
            job_ref=job_ref,
            scope_id=job.job_id,
            run_id=run_id,
            snapshot_ref=snapshot_ref,
            snapshot_revision=snapshot.revision,
            status="failed",
        )
        controller.direct_jobs.compare_and_swap(
            lock,
            expected_head=running_direct_head,
            next_head=failed_direct_head,
        )
        completed_direct_head = new_direct_job_head(
            request_id=request.request_id,
            request_fingerprint=fingerprint,
            request_ref=request_ref,
            job_ref=job_ref,
            scope_id=job.job_id,
            run_id=run_id,
            snapshot_ref=snapshot_ref,
            snapshot_revision=snapshot.revision,
            status="failed",
            result_ref=failed_result_ref,
        )
        controller.direct_jobs.compare_and_swap(
            lock,
            expected_head=failed_direct_head,
            next_head=completed_direct_head,
        )

    captured: dict[str, object] = {}

    async def intercept_execute_direct_locked(**kwargs: object) -> GenerateResult:
        captured.update(kwargs)
        return failed_result

    monkeypatch.setattr(controller, "_execute_direct_locked", intercept_execute_direct_locked)

    resumed = asyncio.run(
        controller.resume_generation(
            request.request_id,
            from_frozen_epoch=epoch_ref.artifact_id,
        )
    )

    assert resumed == failed_result
    assert captured["recovery_context_ref"] == context_ref
    assert captured["recovery_epoch_ref"] == epoch_ref
    assert captured["recovery_frontier"] is True
    assert captured.get("recovery_coordinate") is None
    assert captured.get("resume_authority_ref") is None
    assert controller.work_control.read_head(definition.coordinate) == committed_head


def test_resume_keeps_a_running_crash_boundary_in_the_same_job(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A dead owner resumes its exact running node, never the graph prefix.

    This exercises the controller handoff between a recovered Direct head and
    the frozen WorkGraph.  The actual Work-level reconciliation is covered by
    the DirectWorkRunner recovery boundary tests; this regression proves the
    controller does not reject the running head or misclassify it as a
    terminal operator retry before that reconciliation can happen.
    """

    state_root = tmp_path / "foundry"
    store = ArtifactStore(state_root / "artifacts")
    registry = EnvironmentRegistry(state_root / "registry", store)
    release_profile = ReleaseProfile(profile_id="running-crash-boundary")
    controller = _direct_controller(state_root, store, registry, release_profile)
    artifacts = controller.artifacts
    budget = Budget(wall_seconds=600)
    request = EnvironmentRequest(
        request_id="request:running-crash-boundary",
        need="Resume the exact node whose owner crashed after dispatch.",
        budget=budget,
        release_profile=release_profile,
    )
    request_ref = artifacts.put_json(
        artifact_id=request.request_id,
        artifact_type="control.environment_request",
        value=request,
    )
    job = EnvironmentJob(
        job_id="generate-job:running-crash-boundary",
        kind="generate",
        request_ref=request_ref,
        budget=budget,
        release_profile=release_profile,
    )
    job_ref = artifacts.put_json(
        artifact_id=f"{job.job_id}:job",
        artifact_type="control.environment_job",
        value=job,
        dependencies=(request_ref,),
    )
    context = GenerationContext(
        context_id="generation-context:running-crash-boundary",
        job_ref=job_ref,
        kind="generate",
        request_ref=request_ref,
        permissions=PermissionScope(),
        budget=budget,
        release_profile=release_profile,
    )
    context_ref = artifacts.put_json(
        artifact_id=context.context_id,
        artifact_type="control.generation_context",
        value=context,
        dependencies=context.root_refs,
    )
    definition = deterministic_boundary_work_definition(
        scope_id=job.job_id,
        component="design",
        stage="crash_boundary",
        artifact_slot="crash_boundary",
        dependency_coordinates=(),
        claim_id="crash_boundary.passed",
        claim="A crashed node is reconciled before the run advances.",
        timing_reason="The Direct owner can die after dispatch.",
        effect="block_release",
        success_maturity="crash_boundary_closed",
    )
    graph = GenerationWorkGraph.compile((definition,), mode="diagnostic")
    definition_ref = artifacts.put_json(
        artifact_id=f"work-definition:{definition.work_id}",
        artifact_type="control.work_definition",
        value=definition,
        dependencies=(context_ref,),
    )
    manifest = graph.manifest(
        topology_id="topology:running-crash-boundary",
        external_root_refs=(context_ref,),
    )
    manifest_ref = artifacts.put_json(
        artifact_id=f"work-graph-manifest:{manifest.graph_id}",
        artifact_type="control.work_graph_manifest",
        value=manifest,
        dependencies=(context_ref, definition_ref),
    )
    epoch = WorkGraphEpoch(
        epoch_id="epoch:bootstrap:running-crash-boundary",
        scope_id=job.job_id,
        epoch_kind="bootstrap",
        context_ref=context_ref,
        manifest_ref=manifest_ref,
    )
    epoch_ref = artifacts.put_json(
        artifact_id=epoch.epoch_id,
        artifact_type="control.work_graph_epoch",
        value=epoch,
        dependencies=(context_ref, manifest_ref, definition_ref),
    )
    runtime = WorkControlRuntime(
        artifacts=artifacts,
        heads=controller.work_control,
        budget=LeaseBudgetLedger(budget),
    )
    with controller.work_control.exclusive(definition.coordinate) as lock:
        running_work_head = runtime.begin(
            lock,
            definition=definition,
            input_refs=(context_ref,),
            elapsed_wall_seconds=0,
        )

    run_id = "run:running-crash-boundary"
    running_snapshot = JobRunSnapshot(
        run_id=run_id,
        job_ref=job_ref,
        revision=1,
        status="running",
        reserved_budget=budget,
        observed_actual_budget=BudgetUsage(),
        unknown_upper_bound_budget=BudgetUsage(),
        conservative_committed_budget=BudgetUsage(),
        latest_artifact_refs=(job_ref, request_ref),
    )
    running_snapshot_ref = artifacts.put_json(
        artifact_id=f"{run_id}:state",
        artifact_type="control.job_run_snapshot",
        value=running_snapshot,
        dependencies=(job_ref, request_ref),
    )
    failed_snapshot = running_snapshot.model_copy(
        update={
            "revision": 2,
            "status": "failed",
            "failure_code": "scheduler_direct_owner_lost",
            "failure_summary": "The Direct owner process exited after dispatch.",
        }
    )
    failed_snapshot_ref = artifacts.put_json(
        artifact_id=f"{run_id}:state",
        artifact_type="control.job_run_snapshot",
        value=failed_snapshot,
        dependencies=(running_snapshot_ref, job_ref, request_ref),
    )
    failed_result = GenerateResult(
        run_id=run_id,
        status="failed",
        request_ref=request_ref,
        job_ref=job_ref,
        final_snapshot_ref=failed_snapshot_ref,
        failure_code="scheduler_direct_owner_lost",
        failure_summary="The Direct owner process exited after dispatch.",
    )
    failed_result_ref = artifacts.put_json(
        artifact_id=f"{run_id}:generate-result",
        artifact_type="control.generate_result",
        value=failed_result,
        dependencies=(request_ref, job_ref, failed_snapshot_ref),
    )
    fingerprint = controller._direct_request_fingerprint(  # noqa: SLF001
        request,
        enable_discovery=False,
        discovery_budget=controller.config.discovery_budget,
    )
    with controller.direct_jobs.exclusive(request.request_id) as lock:
        running_direct_head = new_direct_job_head(
            request_id=request.request_id,
            request_fingerprint=fingerprint,
            request_ref=request_ref,
            job_ref=job_ref,
            scope_id=job.job_id,
            run_id=run_id,
            snapshot_ref=running_snapshot_ref,
            snapshot_revision=1,
            status="running",
        )
        controller.direct_jobs.compare_and_swap(
            lock,
            expected_head=None,
            next_head=running_direct_head,
        )
        failed_direct_head = new_direct_job_head(
            request_id=request.request_id,
            request_fingerprint=fingerprint,
            request_ref=request_ref,
            job_ref=job_ref,
            scope_id=job.job_id,
            run_id=run_id,
            snapshot_ref=failed_snapshot_ref,
            snapshot_revision=2,
            status="failed",
        )
        controller.direct_jobs.compare_and_swap(
            lock,
            expected_head=running_direct_head,
            next_head=failed_direct_head,
        )
        completed_direct_head = new_direct_job_head(
            request_id=request.request_id,
            request_fingerprint=fingerprint,
            request_ref=request_ref,
            job_ref=job_ref,
            scope_id=job.job_id,
            run_id=run_id,
            snapshot_ref=failed_snapshot_ref,
            snapshot_revision=2,
            status="failed",
            result_ref=failed_result_ref,
        )
        controller.direct_jobs.compare_and_swap(
            lock,
            expected_head=failed_direct_head,
            next_head=completed_direct_head,
        )

    captured: dict[str, object] = {}

    async def intercept_execute_direct_locked(**kwargs: object) -> GenerateResult:
        captured.update(kwargs)
        return failed_result

    monkeypatch.setattr(controller, "_execute_direct_locked", intercept_execute_direct_locked)

    resumed = asyncio.run(
        controller.resume_generation(
            request.request_id,
            from_coordinate="design.crash_boundary.crash_boundary",
        )
    )

    assert resumed == failed_result
    assert captured["recovery_context_ref"] == context_ref
    assert captured["recovery_epoch_ref"] == epoch_ref
    assert captured["recovery_coordinate"] == definition.coordinate
    # A running attempt has not reached the terminal-retry boundary.  The
    # frozen runner must reconcile it before any new leaf dispatch.
    assert captured["resume_authority_ref"] is None
    assert controller.work_control.read_head(definition.coordinate) == running_work_head


def test_controller_reconciles_registry_event_failure_after_atomic_publish(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_root = tmp_path / "foundry"
    store = ArtifactStore(state_root / "artifacts")
    registry = EnvironmentRegistry(state_root / "registry", store)
    release_profile = ReleaseProfile(
        profile_id="registry-post-commit-fault",
        required_hard_gates=("runtime_protocol", "task_reachability", "clean_deployment"),
    )
    controller = _direct_controller(state_root, store, registry, release_profile)
    graph = _release_graph(tmp_path, store, release_profile=release_profile)
    reservation = _reserve(registry, graph)
    prepared = registry.prepare(
        candidate_workspace=graph.workspace,
        manifest_ref=graph.manifest_ref,
        judge_report_ref=graph.report_ref,
        release_profile=release_profile,
        reservation=reservation,
        framework_payloads=graph.framework_payloads,
    )

    def fail_after_index_commit(**_kwargs: object) -> None:
        raise OSError("injected Registry event fsync failure")

    monkeypatch.setattr(registry, "_append_event", fail_after_index_commit)

    published = controller._publish_registry_release(  # noqa: SLF001
        prepared=prepared,
        job_ref=graph.owner_ref,
        manifest_ref=graph.manifest_ref,
    )

    inspected = registry.inspect(
        graph.package_id,
        graph.version,
        package_digest=published.coordinate.package_digest,
    )
    assert published == inspected
    assert published.reservation_owner_ref == graph.owner_ref
    assert registry.inspect_reservation(reservation.reservation_id).status == "consumed"


@pytest.mark.parametrize("completed_failure_head", (False, True))
def test_direct_generate_recovers_published_job_and_retries_without_agent_replay(
    tmp_path: Path,
    completed_failure_head: bool,
) -> None:
    state_root = tmp_path / "foundry"
    store = ArtifactStore(state_root / "artifacts")
    registry = EnvironmentRegistry(state_root / "registry", store)
    release_profile = ReleaseProfile(
        profile_id="registry-integration",
        required_hard_gates=("runtime_protocol", "task_reachability", "clean_deployment"),
    )
    controller = _direct_controller(
        state_root,
        store,
        registry,
        release_profile,
    )
    request_id = "request:published-crash-window"
    need = "Build a real inventory environment with executable state transitions."
    request = EnvironmentRequest(
        request_id=request_id,
        need=need,
        budget=controller.config.generation_budget,
        release_profile=release_profile,
    )
    request_ref = _framework_writer(store).put_json(
        artifact_id=controller._stable_id("request-artifact", request_id),  # noqa: SLF001
        artifact_type="control.environment_request",
        value=request,
    )
    job_id = controller._stable_id(  # noqa: SLF001
        "generate-job",
        request_id,
        request_ref.revision_id,
    )
    job = EnvironmentJob(
        job_id=job_id,
        kind="generate",
        request_ref=request_ref,
        budget=request.budget,
        release_profile=release_profile,
    )
    job_ref = _framework_writer(store).put_json(
        artifact_id=f"{job_id}:job",
        artifact_type="control.environment_job",
        value=job,
        dependencies=(request_ref,),
    )

    graph = _release_graph(
        tmp_path,
        store,
        owner_ref=job_ref,
        release_profile=release_profile,
    )
    reservation = _reserve(registry, graph)
    prepared = registry.prepare(
        candidate_workspace=graph.workspace,
        manifest_ref=graph.manifest_ref,
        judge_report_ref=graph.report_ref,
        release_profile=release_profile,
        reservation=reservation,
        framework_payloads=graph.framework_payloads,
    )
    published = registry.publish(prepared)

    run_id = "run:published-crash-window"
    telemetry = TelemetryStore(state_root / "telemetry")
    controller.telemetry = telemetry
    root_span = telemetry.start_span(
        trace_id=run_id,
        component="controller",
        operation="direct.generate",
        run_id=run_id,
    )
    for node in ("request", "design", "verifier", "build", "integration", "judge", "release"):
        span = telemetry.start_span(
            trace_id=run_id,
            component="controller",
            operation=f"node.{node}",
            parent_span_id=root_span.span_id,
            run_id=run_id,
            node=node,
        )
        span.finish(status="passed")
    invocation_span = telemetry.start_span(
        trace_id=run_id,
        component="invocation",
        operation="agent.invoke",
        parent_span_id=root_span.span_id,
        run_id=run_id,
    )
    invocation_span.finish(status="passed")
    for operation in ("research.search", "research.fetch", "research.extract"):
        span = telemetry.start_span(
            trace_id=run_id,
            component="research",
            operation=operation,
            parent_span_id=root_span.span_id,
            run_id=run_id,
        )
        span.finish(status="passed")
    telemetry.record_metrics(
        run_id,
        root_span.span_id,
        (
            MetricPoint("invocation.tokens.total", 1, "tokens", "provider"),
            MetricPoint("research.search.calls", 1, "calls", "framework"),
            MetricPoint("research.fetch.calls", 1, "calls", "framework"),
            MetricPoint("research.documents.extracted", 1, "documents", "framework"),
        ),
    )
    telemetry.flush()
    running_snapshot = JobRunSnapshot(
        run_id=run_id,
        job_ref=job_ref,
        revision=1,
        status="running",
        reserved_budget=request.budget,
        observed_actual_budget=BudgetUsage(),
        unknown_upper_bound_budget=BudgetUsage(),
        conservative_committed_budget=BudgetUsage(),
        latest_artifact_refs=(job_ref, request_ref),
    )
    running_snapshot_ref = _framework_writer(store).put_json(
        artifact_id=f"{run_id}:state",
        artifact_type="control.job_run_snapshot",
        value=running_snapshot,
        dependencies=(job_ref, request_ref),
    )
    fingerprint = controller._direct_request_fingerprint(  # noqa: SLF001
        request,
        enable_discovery=False,
        discovery_budget=controller.config.discovery_budget,
    )
    with controller.direct_jobs.exclusive(request_id) as lock:
        initial_head = new_direct_job_head(
            request_id=request_id,
            request_fingerprint=fingerprint,
            request_ref=request_ref,
            job_ref=job_ref,
            run_id=run_id,
            snapshot_ref=running_snapshot_ref,
            snapshot_revision=1,
            status="running",
        )
        controller.direct_jobs.compare_and_swap(
            lock,
            expected_head=None,
            next_head=initial_head,
        )
        if completed_failure_head:
            failed_snapshot = running_snapshot.model_copy(
                update={
                    "revision": 2,
                    "status": "failed",
                    "failure_code": "post_publish_bookkeeping_failed",
                    "failure_summary": "Controller bookkeeping failed after Registry publish.",
                }
            )
            failed_snapshot_ref = _framework_writer(store).put_json(
                artifact_id=f"{run_id}:state",
                artifact_type="control.job_run_snapshot",
                value=failed_snapshot,
                dependencies=(running_snapshot_ref, job_ref, request_ref),
            )
            failed_head = new_direct_job_head(
                request_id=request_id,
                request_fingerprint=fingerprint,
                request_ref=request_ref,
                job_ref=job_ref,
                run_id=run_id,
                snapshot_ref=failed_snapshot_ref,
                snapshot_revision=2,
                status="failed",
            )
            controller.direct_jobs.compare_and_swap(
                lock,
                expected_head=initial_head,
                next_head=failed_head,
            )
            failed_result = GenerateResult(
                run_id=run_id,
                status="failed",
                request_ref=request_ref,
                job_ref=job_ref,
                final_snapshot_ref=failed_snapshot_ref,
                failure_code="post_publish_bookkeeping_failed",
                failure_summary="Controller bookkeeping failed after Registry publish.",
            )
            failed_result_ref = _framework_writer(store).put_json(
                artifact_id=f"{run_id}:generate-result",
                artifact_type="control.generate_result",
                value=failed_result,
                dependencies=(request_ref, job_ref, failed_snapshot_ref),
            )
            completed_head = new_direct_job_head(
                request_id=request_id,
                request_fingerprint=fingerprint,
                request_ref=request_ref,
                job_ref=job_ref,
                run_id=run_id,
                snapshot_ref=failed_snapshot_ref,
                snapshot_revision=2,
                status="failed",
                result_ref=failed_result_ref,
            )
            controller.direct_jobs.compare_and_swap(
                lock,
                expected_head=failed_head,
                next_head=completed_head,
            )

    recovered = asyncio.run(
        controller.generate(
            need,
            request_id=request_id,
            enable_discovery=False,
        )
    )
    retried = asyncio.run(
        controller.generate(
            need,
            request_id=request_id,
            enable_discovery=False,
        )
    )

    assert recovered.status == "released"
    assert recovered.release is not None
    assert recovered.release.release_id == published.release_id
    assert retried == recovered
    assert retried.release_ref == recovered.release_ref
    recovered_snapshot = store.get_json(recovered.final_snapshot_ref, JobRunSnapshot)
    final_telemetry_refs = tuple(
        ref
        for ref in recovered_snapshot.latest_artifact_refs
        if ref.artifact_type == "release.final_telemetry_summary"
    )
    assert len(final_telemetry_refs) == 1
    final_telemetry = store.get_json(final_telemetry_refs[0], TelemetryReleaseSummary)
    assert final_telemetry.cut_stage == "post_publish"
    assert final_telemetry.open_span_count == 0

    with pytest.raises(DirectRequestConflictError, match="different canonical"):
        asyncio.run(
            controller.generate(
                "A different environment need must not reuse this request id.",
                request_id=request_id,
                enable_discovery=False,
            )
        )

    unfinished_id = "request:unfinished-agent-work"
    unfinished_request = EnvironmentRequest(
        request_id=unfinished_id,
        need="An interrupted environment whose unknown Agent work cannot be replayed.",
        budget=controller.config.generation_budget,
        release_profile=release_profile,
    )
    unfinished_request_ref = _framework_writer(store).put_json(
        artifact_id=controller._stable_id(  # noqa: SLF001
            "request-artifact",
            unfinished_id,
        ),
        artifact_type="control.environment_request",
        value=unfinished_request,
    )
    unfinished_job_id = controller._stable_id(  # noqa: SLF001
        "generate-job",
        unfinished_id,
        unfinished_request_ref.revision_id,
    )
    unfinished_job = EnvironmentJob(
        job_id=unfinished_job_id,
        kind="generate",
        request_ref=unfinished_request_ref,
        budget=unfinished_request.budget,
        release_profile=release_profile,
    )
    unfinished_job_ref = _framework_writer(store).put_json(
        artifact_id=f"{unfinished_job_id}:job",
        artifact_type="control.environment_job",
        value=unfinished_job,
        dependencies=(unfinished_request_ref,),
    )
    unfinished_run_id = "run:unfinished-agent-work"
    unfinished_snapshot = JobRunSnapshot(
        run_id=unfinished_run_id,
        job_ref=unfinished_job_ref,
        revision=1,
        status="running",
        reserved_budget=unfinished_request.budget,
        observed_actual_budget=BudgetUsage(agent_turns=1),
        unknown_upper_bound_budget=BudgetUsage(),
        conservative_committed_budget=BudgetUsage(agent_turns=1),
        latest_artifact_refs=(unfinished_job_ref, unfinished_request_ref),
    )
    unfinished_snapshot_ref = _framework_writer(store).put_json(
        artifact_id=f"{unfinished_run_id}:state",
        artifact_type="control.job_run_snapshot",
        value=unfinished_snapshot,
        dependencies=(unfinished_job_ref, unfinished_request_ref),
    )
    unfinished_fingerprint = controller._direct_request_fingerprint(  # noqa: SLF001
        unfinished_request,
        enable_discovery=False,
        discovery_budget=controller.config.discovery_budget,
    )
    with controller.direct_jobs.exclusive(unfinished_id) as lock:
        controller.direct_jobs.compare_and_swap(
            lock,
            expected_head=None,
            next_head=new_direct_job_head(
                request_id=unfinished_id,
                request_fingerprint=unfinished_fingerprint,
                request_ref=unfinished_request_ref,
                job_ref=unfinished_job_ref,
                run_id=unfinished_run_id,
                snapshot_ref=unfinished_snapshot_ref,
                snapshot_revision=1,
                status="running",
            ),
        )
    with pytest.raises(DirectJobResumeRequiredError, match="will not replay"):
        asyncio.run(
            controller.generate(
                unfinished_request.need,
                request_id=unfinished_id,
                enable_discovery=False,
            )
        )

    terminal_id = "request:terminal-budget-result"
    zero_wall_budget = controller.config.generation_budget.model_copy(update={"wall_seconds": 0.0})
    terminal = asyncio.run(
        controller.generate(
            "A zero-wall budget must produce one durable honest terminal result.",
            request_id=terminal_id,
            budget=zero_wall_budget,
            enable_discovery=False,
        )
    )
    terminal_retry = asyncio.run(
        controller.generate(
            "A zero-wall budget must produce one durable honest terminal result.",
            request_id=terminal_id,
            budget=zero_wall_budget,
            enable_discovery=False,
        )
    )
    assert terminal.status == "budget_exhausted"
    assert terminal.failure_code == "wall_budget_missing"
    assert terminal_retry == terminal


def test_registry_prepares_and_atomically_publishes_immutable_package(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifact-store")
    graph = _release_graph(tmp_path, store)
    registry = EnvironmentRegistry(tmp_path / "registry", store)
    reservation = _reserve(registry, graph)

    prepared = registry.prepare(
        candidate_workspace=graph.workspace,
        manifest_ref=graph.manifest_ref,
        judge_report_ref=graph.report_ref,
        release_profile=graph.release_profile,
        reservation=reservation,
        framework_payloads=graph.framework_payloads,
    )
    staging = registry.root / prepared.staging_relpath
    assert staging.is_dir()
    assert (staging / "runtime.py").read_bytes() == (graph.workspace / "runtime.py").read_bytes()

    record = registry.publish(prepared)
    package_path = registry.root / record.package_relpath
    assert record.status == "released"
    assert record.reservation_id == reservation.reservation_id
    consumed = registry.inspect_reservation(reservation.reservation_id)
    assert consumed.status == "consumed"
    assert _reserve(registry, graph) == consumed
    competing_owner = _commit(
        store,
        "job:competing-publisher",
        "control.environment_job",
        {"job_id": "job:competing-publisher", "kind": "expand"},
    )
    with pytest.raises(ReservationConflictError, match="already published"):
        registry.reserve_package_version(
            graph.package_id,
            graph.version,
            competing_owner,
        )
    with pytest.raises(ReservationConflictError, match="cannot be released"):
        registry.release_reservation(reservation.reservation_id, graph.owner_ref)
    assert record.candidate_ref == graph.candidate_ref
    assert package_path.is_dir()
    assert not staging.exists()
    assert not (registry.root / "prepared" / f"{prepared.staging_token}.json").exists()
    assert (package_path / "manifest.json").is_file()
    assert (package_path / "release-dossier.json").is_file()
    manifest = store.get_json(graph.manifest_ref, EnvironmentPackageManifest)
    declared_roles = {item.path: item.role for item in manifest.files}
    assert manifest.format == "envpkg-v3"
    assert manifest.task_materializer.protocol == "python-callable-v3"
    assert manifest.task_materializer.output_schema_path == "tasks/materializer_protocol.json"
    assert manifest.trusted_evaluator.rule_ir_path == "world/rule_ir.json"
    assert declared_roles["tasks/materializer_protocol.json"] == "materializer_protocol"
    assert declared_roles["tasks/curriculum.json"] == "curriculum"
    assert declared_roles["world/rule_ir.json"] == "rule_ir"
    assert declared_roles["world/world_spec.json"] == "world_spec"
    assert declared_roles["envpkg.toml"] == "package_metadata"
    assert declared_roles["evidence/provenance.json"] == "provenance"
    assert declared_roles["evidence/assurance.json"] == "assurance"
    assert declared_roles["evidence/fidelity.json"] == "fidelity"
    assert declared_roles["sbom/sbom.json"] == "sbom"
    for payload in graph.framework_payloads:
        assert (package_path / payload.path).read_bytes() == payload.content
    assert registry.inspect(graph.package_id, graph.version) == record
    assert registry.list() == (record,)

    assert registry.publish(prepared) == record
    assert registry.list() == (record,)

    snapshot = registry.pool_snapshot()
    assert snapshot.releases == (record,)
    assert registry.load_pool_snapshot(snapshot.snapshot_id) == snapshot
    suite = registry.create_suite_snapshot(
        (
            SuiteSelectionRequest(
                package_id=record.coordinate.package_id,
                version=record.coordinate.version,
                weight=Decimal("2.5"),
                curriculum_policy=CurriculumSamplingPolicy(maximum_steps=37),
            ),
        )
    )
    suite_member = suite.packages[0]
    assert suite.consumer_protocol == "agent-world.local-consumer.v3"
    assert suite_member.package_digest == record.coordinate.package_digest
    assert suite_member.manifest_hash == manifest.content_digest()
    assert suite_member.weight == Decimal("2.5")
    assert suite_member.curriculum_policy.maximum_steps == 37
    assert registry.load_suite_snapshot(suite.snapshot_id) == suite
    resolved = registry.resolve_suite_package(
        suite.snapshot_id,
        record.coordinate.package_id,
        record.coordinate.version,
    )
    assert resolved.record == record
    assert resolved.package_root == package_path
    assert registry.require_released_manifest(graph.manifest_ref) == record
    assert registry.require_snapshot_parent(snapshot.snapshot_id, graph.manifest_ref) == record
    with pytest.raises(ParentNotEligibleError, match="artifact_type"):
        registry.require_released_manifest(graph.candidate_ref)
    with pytest.raises(ParentNotEligibleError, match="not a member"):
        registry.require_snapshot_parent(snapshot.snapshot_id, graph.candidate_ref)

    released_runtime = package_path / "runtime.py"
    released_bytes = released_runtime.read_bytes()
    released_mode = released_runtime.stat().st_mode & 0o777
    released_runtime.chmod(0o600)
    released_runtime.write_bytes(b"tampered released runtime\n")
    with pytest.raises(RegistryIntegrityError, match="changed|digest|hash|size"):
        registry.load_suite_snapshot(suite.snapshot_id)
    released_runtime.write_bytes(released_bytes)
    released_runtime.chmod(released_mode)
    assert registry.load_suite_snapshot(suite.snapshot_id) == suite

    for protected_path in (payload.path for payload in graph.framework_payloads):
        released_contract = package_path / protected_path
        original_bytes = released_contract.read_bytes()
        original_mode = released_contract.stat().st_mode & 0o777
        released_contract.chmod(0o600)
        released_contract.write_bytes(b'{"tampered":true}')
        with pytest.raises(RegistryIntegrityError, match="changed|digest|hash|size"):
            registry.load_suite_snapshot(suite.snapshot_id)
        released_contract.write_bytes(original_bytes)
        released_contract.chmod(original_mode)
        assert registry.load_suite_snapshot(suite.snapshot_id) == suite

    report = store.get_json(graph.report_ref, JudgeReport)
    reachability_ref = next(
        ref
        for ref in report.evaluation_evidence_refs
        if ref.artifact_type == "judge.reachability_public_evidence"
    )
    evidence_digest = reachability_ref.content_hash.removeprefix("sha256:")
    evidence_blob = store.root / "blobs" / "sha256" / evidence_digest[:2] / evidence_digest
    evidence_bytes = evidence_blob.read_bytes()
    evidence_mode = evidence_blob.stat().st_mode & 0o777
    evidence_blob.chmod(0o600)
    evidence_blob.write_bytes(b'{"tampered":true}')
    with pytest.raises(
        RegistryIntegrityError,
        match="Judge evidence closure is invalid",
    ):
        registry.load_suite_snapshot(suite.snapshot_id)
    evidence_blob.write_bytes(evidence_bytes)
    evidence_blob.chmod(evidence_mode)
    assert registry.load_suite_snapshot(suite.snapshot_id) == suite

    (graph.workspace / "runtime.py").write_bytes(b"changed candidate bytes\n")
    assert (package_path / "runtime.py").read_bytes() == released_bytes

    quarantined = registry.quarantine(
        graph.package_id,
        graph.version,
        reason_code="new_hard_evidence",
    )
    assert quarantined.status == "quarantined"
    assert (package_path / "runtime.py").read_bytes() == released_bytes
    assert registry.list(statuses=("released",)) == ()
    assert registry.list(statuses=("quarantined",)) == (quarantined,)
    with pytest.raises(ParentNotEligibleError, match="not currently released"):
        registry.require_released_manifest(graph.manifest_ref)
    with pytest.raises(ParentNotEligibleError, match="not currently released"):
        registry.require_snapshot_parent(snapshot.snapshot_id, graph.manifest_ref)
    assert registry.load_suite_snapshot(suite.snapshot_id) == suite
    with pytest.raises(ParentNotEligibleError, match="only currently released"):
        registry.create_suite_snapshot(
            (
                SuiteSelectionRequest(
                    package_id=record.coordinate.package_id,
                    version=record.coordinate.version,
                ),
            )
        )
    with pytest.raises(ParentNotEligibleError, match="not currently released"):
        registry.resolve_suite_package(
            suite.snapshot_id,
            record.coordinate.package_id,
            record.coordinate.version,
        )


def test_prepare_rejects_tampering_of_every_framework_metadata_payload(
    tmp_path: Path,
) -> None:
    store = ArtifactStore(tmp_path / "artifact-store")
    graph = _release_graph(tmp_path, store)
    registry = EnvironmentRegistry(tmp_path / "registry", store)
    reservation = _reserve(registry, graph)

    for target in graph.framework_payloads:
        tampered = tuple(
            FrameworkPackagePayload(
                path=payload.path,
                role=payload.role,
                content=payload.content + b"\n",
            )
            if payload.path == target.path
            else payload
            for payload in graph.framework_payloads
        )
        with pytest.raises(
            UnsafePackageError,
            match="framework package payload differs",
        ):
            registry.prepare(
                candidate_workspace=graph.workspace,
                manifest_ref=graph.manifest_ref,
                judge_report_ref=graph.report_ref,
                release_profile=graph.release_profile,
                reservation=reservation,
                framework_payloads=tampered,
            )

    assert registry.inspect_reservation(reservation.reservation_id).status == "active"


def test_expansion_uses_all_frozen_pool_parents_and_revokes_quarantine(
    tmp_path: Path,
) -> None:
    store = ArtifactStore(tmp_path / "artifact-store")
    registry = EnvironmentRegistry(tmp_path / "registry", store)
    anchor_root = tmp_path / "anchor-package"
    pool_root = tmp_path / "pool-package"
    anchor_root.mkdir()
    pool_root.mkdir()
    anchor_graph = _release_graph(anchor_root, store, variant="anchor")
    pool_graph = _release_graph(pool_root, store, variant="pool")

    for graph in (anchor_graph, pool_graph):
        prepared = registry.prepare(
            candidate_workspace=graph.workspace,
            manifest_ref=graph.manifest_ref,
            judge_report_ref=graph.report_ref,
            release_profile=graph.release_profile,
            reservation=_reserve(registry, graph),
            framework_payloads=graph.framework_payloads,
        )
        assert registry.publish(prepared).status == "released"

    controller = _direct_controller(
        tmp_path / "foundry",
        store,
        registry,
        anchor_graph.release_profile,
    )
    runner = controller.expansion_runner
    campaign_id = "campaign:complete-frozen-parent-universe"
    source_budget = Budget(
        llm_tokens=2,
        agent_turns=2,
        search_calls=1,
        tool_calls=3,
        wall_seconds=10,
    )
    source_catalog = ExpansionSourceCatalog(
        catalog_id="source-catalog:pool-parent-test",
        sources=(
            ExpansionSourceDescriptor(
                source_id="source:unavailable-fault-injection",
                kind="pool_neighborhood",
                budget=source_budget,
            ),
        ),
    )
    campaign_budget = Budget(
        llm_tokens=2,
        agent_turns=8,
        search_calls=1,
        tool_calls=3,
        wall_seconds=300,
    )
    candidate_budget = Budget(agent_turns=2, wall_seconds=60)

    class UnavailableSourceFault:
        async def discover(self, **_kwargs: object) -> object:
            raise ConnectionError("intentional Source outage for recovery coverage")

    runner.source = UnavailableSourceFault()  # type: ignore[assignment]
    with controller.campaign_store.exclusive(campaign_id) as lock:
        state = runner._create_state(  # noqa: SLF001
            lock=lock,
            campaign_id=campaign_id,
            anchor_package_refs=(anchor_graph.manifest_ref,),
            target_coverage_dimensions=("tool_semantics",),
            inbox_snapshot_ref=None,
            source_catalog=source_catalog,
            feedback_refs=(),
            policy_id="wide-search",
            policy_parameters=(),
            permissions=PermissionScope(),
            campaign_budget=campaign_budget,
            candidate_budget=candidate_budget,
            release_profile=anchor_graph.release_profile,
            campaign_seed=73,
            maximum_intents_per_iteration=5,
            maximum_in_flight=1,
            maximum_iterations=2,
            maximum_no_release_iterations=2,
            maximum_infrastructure_error_iterations=2,
            version_reservation_ttl_seconds=3600,
            allowed_source_kinds=("web",),
            risk_level="medium",
            fidelity_requirements=(),
        )
        assert state.context is None
        state = asyncio.run(runner._execute_source_intake(lock, state))  # noqa: SLF001

    frozen_refs = tuple(item.manifest_ref for item in state.snapshot.releases)
    assert state.context is not None
    assert {item.package_ref for item in state.context.parents} == set(frozen_refs)
    assert state.context.anchor_parent_refs == (anchor_graph.manifest_ref,)
    assert pool_graph.manifest_ref in frozen_refs

    pool_intent = MutationIntent(
        intent_id="intent:frozen-non-anchor-parent",
        parent_refs=(pool_graph.manifest_ref,),
        primary_parent_ref=pool_graph.manifest_ref,
        operator="tool_semantics",
        operator_version="1",
        seed=11,
        target_coverage_dimensions=("tool_semantics",),
    )
    assert runner._admission_error(state, pool_intent) is None  # noqa: SLF001

    recombination = MutationIntent(
        intent_id="intent:pool-recombination",
        parent_refs=(anchor_graph.manifest_ref, pool_graph.manifest_ref),
        primary_parent_ref=anchor_graph.manifest_ref,
        operator="composite",
        operator_version="1",
        seed=12,
        target_coverage_dimensions=("tool_semantics",),
    )
    assert runner._admission_error(state, recombination) is None  # noqa: SLF001

    single_parent_composite = MutationIntent(
        intent_id="intent:invalid-single-parent-composite",
        parent_refs=(anchor_graph.manifest_ref,),
        primary_parent_ref=anchor_graph.manifest_ref,
        operator="composite",
        operator_version="1",
        seed=13,
        target_coverage_dimensions=("tool_semantics",),
    )
    assert (  # noqa: SLF001
        runner._admission_error(state, single_parent_composite)
        == "composite_single_parent_requires_clue"
    )

    registry.quarantine(
        pool_graph.package_id,
        pool_graph.version,
        reason_code="parent_semantics_invalidated",
    )
    assert (  # noqa: SLF001
        runner._admission_error(state, pool_intent) == "parent_no_longer_eligible"
    )


def test_version_reservation_is_exclusive_idempotent_and_restart_safe(
    tmp_path: Path,
) -> None:
    store = ArtifactStore(tmp_path / "artifact-store")
    first_owner = _commit(
        store,
        "job:first-owner",
        "control.environment_job",
        {"job_id": "job:first-owner", "kind": "expand"},
    )
    second_owner = _commit(
        store,
        "job:second-owner",
        "control.environment_job",
        {"job_id": "job:second-owner", "kind": "expand"},
    )
    registry_root = tmp_path / "registry"
    registry = EnvironmentRegistry(registry_root, store)

    def attempt(owner_ref: ArtifactRef) -> PackageVersionReservation | str:
        try:
            return registry.reserve_package_version("shared-environment", "1.1.0", owner_ref)
        except ReservationConflictError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(executor.map(attempt, (first_owner, second_owner)))

    winners = tuple(item for item in results if isinstance(item, PackageVersionReservation))
    assert len(winners) == 1
    assert results.count("conflict") == 1
    winner = winners[0]
    assert winner.status == "active"
    assert (
        registry.reserve_package_version(
            winner.package_id,
            winner.version,
            winner.owner_ref,
        )
        == winner
    )

    restarted = EnvironmentRegistry(registry_root, store)
    assert restarted.inspect_reservation(winner.reservation_id) == winner
    assert (
        restarted.reserve_package_version(
            winner.package_id,
            winner.version,
            winner.owner_ref,
        )
        == winner
    )


def test_expired_and_cancelled_reservations_release_the_coordinate(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifact-store")
    first_owner = _commit(
        store,
        "job:expiring-owner",
        "control.environment_job",
        {"job_id": "job:expiring-owner", "kind": "expand"},
    )
    second_owner = _commit(
        store,
        "job:replacement-owner",
        "control.environment_job",
        {"job_id": "job:replacement-owner", "kind": "expand"},
    )
    registry = EnvironmentRegistry(
        tmp_path / "registry",
        store,
        reservation_ttl_seconds=0.03,
    )
    expiring = registry.reserve_package_version("expiry-environment", "1.0.0", first_owner)
    time.sleep(0.05)
    assert registry.inspect_reservation(expiring.reservation_id).status == "expired"

    replacement = registry.reserve_package_version(
        "expiry-environment",
        "1.0.0",
        second_owner,
        ttl_seconds=60,
    )
    cancelled = registry.release_reservation(replacement.reservation_id, second_owner)
    assert cancelled.status == "cancelled"
    assert registry.release_reservation(replacement.reservation_id, second_owner) == cancelled

    reacquired = registry.reserve_package_version(
        "expiry-environment",
        "1.0.0",
        first_owner,
        ttl_seconds=60,
    )
    assert reacquired.status == "active"
    assert reacquired.reservation_id not in {
        expiring.reservation_id,
        replacement.reservation_id,
    }


def test_prepare_rejects_manifest_outside_reserved_coordinate(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifact-store")
    graph = _release_graph(tmp_path, store)
    registry = EnvironmentRegistry(tmp_path / "registry", store)
    wrong_coordinate = _reserve(
        registry,
        graph,
        package_id="different-environment",
        version="9.0.0",
    )

    with pytest.raises(ReservationConflictError, match="manifest coordinate"):
        registry.prepare(
            candidate_workspace=graph.workspace,
            manifest_ref=graph.manifest_ref,
            judge_report_ref=graph.report_ref,
            release_profile=graph.release_profile,
            reservation=wrong_coordinate,
            framework_payloads=graph.framework_payloads,
        )
    assert registry.list() == ()
    assert registry.inspect_reservation(wrong_coordinate.reservation_id).status == "active"


def test_prepare_rejects_unparsable_physical_world_spec(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifact-store")
    graph = _release_graph(
        tmp_path,
        store,
        world_spec_bytes_override=b'{"world":"inventory"}',
    )
    registry = EnvironmentRegistry(tmp_path / "registry", store)
    reservation = _reserve(registry, graph)

    with pytest.raises(
        ReleaseRejectedError,
        match="physical WorldSpec is not a valid closed contract",
    ):
        registry.prepare(
            candidate_workspace=graph.workspace,
            manifest_ref=graph.manifest_ref,
            judge_report_ref=graph.report_ref,
            release_profile=graph.release_profile,
            reservation=reservation,
            framework_payloads=graph.framework_payloads,
        )

    assert registry.list() == ()
    assert registry.inspect_reservation(reservation.reservation_id).status == "active"


def test_expired_prepared_release_cannot_publish_or_claim_success(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifact-store")
    graph = _release_graph(tmp_path, store)
    registry = EnvironmentRegistry(tmp_path / "registry", store)
    reservation = registry.reserve_package_version(
        graph.package_id,
        graph.version,
        graph.owner_ref,
        ttl_seconds=5.0,
    )
    prepared = registry.prepare(
        candidate_workspace=graph.workspace,
        manifest_ref=graph.manifest_ref,
        judge_report_ref=graph.report_ref,
        release_profile=graph.release_profile,
        reservation=reservation,
        framework_payloads=graph.framework_payloads,
    )
    remaining = (reservation.expires_at - datetime.now(UTC)).total_seconds()
    time.sleep(max(remaining + 0.05, 0.05))

    with pytest.raises(ReservationExpiredError, match="reservation expired"):
        registry.publish(prepared)
    assert registry.list() == ()
    assert registry.inspect_reservation(reservation.reservation_id).status == "expired"


def test_nonpassing_judge_evidence_cannot_assemble_a_package(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifact-store")
    # Package is the first release-candidate artifact.  A failed Judge must
    # not get that far and rely on a later Registry rejection: its evidence is
    # not an admissible package closure.
    with pytest.raises(ValueError, match="source-bound passing JudgeReport"):
        _release_graph(tmp_path, store, judge_passes=False)


def test_registry_rejects_source_tree_not_verified_by_judge(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    graph = _release_graph(tmp_path, store)
    report = store.get_json(graph.report_ref, JudgeReport)
    wrong_report = report.model_copy(
        update={"candidate_source_tree_digest": sha256_digest(b"different-source-tree")}
    )
    wrong_report_ref = _judge_writer(store).put_json(
        artifact_id="judge-report:wrong-source-tree",
        artifact_type="judge_report",
        value=wrong_report,
        dependencies=(graph.candidate_ref, *wrong_report.evaluation_evidence_refs),
    )
    manifest = store.get_json(graph.manifest_ref, EnvironmentPackageManifest)
    wrong_manifest = manifest.model_copy(update={"judge_report_ref": wrong_report_ref})
    original_dependencies = store.dependencies(graph.manifest_ref)
    wrong_manifest_ref = _framework_writer(store).put_json(
        artifact_id="manifest:wrong-source-tree",
        artifact_type="environment_package_manifest",
        value=wrong_manifest,
        dependencies=(
            *(item for item in original_dependencies if item != graph.report_ref),
            wrong_report_ref,
        ),
    )
    registry = EnvironmentRegistry(tmp_path / "registry", store)
    reservation = _reserve(registry, graph)

    with pytest.raises(ReleaseRejectedError, match="bind different revisions"):
        registry.prepare(
            candidate_workspace=graph.workspace,
            manifest_ref=wrong_manifest_ref,
            judge_report_ref=wrong_report_ref,
            release_profile=graph.release_profile,
            reservation=reservation,
            framework_payloads=graph.framework_payloads,
        )
    assert registry.list() == ()


def test_registry_rejects_generic_reachability_evidence(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    graph = _release_graph(tmp_path, store)
    generic_ref = _judge_writer(store).put_json(
        artifact_id="reachability:generic-summary",
        artifact_type="judge.evaluation_evidence",
        value={"status": "pass", "claim": "all generated tasks are reachable"},
        dependencies=(graph.candidate_ref,),
    )
    report = store.get_json(graph.report_ref, JudgeReport)
    gate_results = tuple(
        gate.model_copy(update={"evidence_refs": (generic_ref,)})
        if gate.gate_id == "task_reachability"
        else gate
        for gate in report.gate_results
    )
    evidence_refs = tuple(
        ref
        for ref in report.evaluation_evidence_refs
        if ref.artifact_type != "judge.reachability_public_evidence"
    ) + (generic_ref,)
    generic_report = report.model_copy(
        update={
            "gate_results": gate_results,
            "evaluation_evidence_refs": evidence_refs,
        }
    )
    registry = EnvironmentRegistry(tmp_path / "registry", store)

    with pytest.raises(
        ReleaseRejectedError,
        match="typed public reachability evidence",
    ):
        registry._validate_reachability_release_evidence(  # noqa: SLF001
            generic_report,
            {item.gate_id: item for item in generic_report.gate_results},
        )


def test_registry_rejects_incomplete_integration_gate_closure(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    graph = _release_graph(tmp_path, store)
    manifest = store.get_json(graph.manifest_ref, EnvironmentPackageManifest)
    integration = store.get_json(manifest.integration_report_ref, IntegrationReport)
    incomplete = integration.model_copy(update={"gate_results": integration.gate_results[:-1]})
    incomplete_ref = _judge_writer(store).put_json(
        artifact_id="integration-report:missing-gate",
        artifact_type="judge.integration_report",
        value=incomplete,
        dependencies=store.dependencies(manifest.integration_report_ref),
    )
    revised_manifest = manifest.model_copy(update={"integration_report_ref": incomplete_ref})
    revised_manifest_ref = _framework_writer(store).put_json(
        artifact_id="manifest:missing-integration-gate",
        artifact_type="environment_package_manifest",
        value=revised_manifest,
        dependencies=tuple(
            incomplete_ref if ref == manifest.integration_report_ref else ref
            for ref in store.dependencies(graph.manifest_ref)
        ),
    )
    registry = EnvironmentRegistry(tmp_path / "registry", store)
    with pytest.raises(ReleaseRejectedError, match="bind different revisions"):
        registry.prepare(
            candidate_workspace=graph.workspace,
            manifest_ref=revised_manifest_ref,
            judge_report_ref=graph.report_ref,
            release_profile=graph.release_profile,
            reservation=_reserve(registry, graph),
            framework_payloads=graph.framework_payloads,
        )


def test_registry_rejects_dossier_without_the_exact_prepackage_closure(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    graph = _release_graph(tmp_path, store)
    manifest = store.get_json(graph.manifest_ref, EnvironmentPackageManifest)
    dossier = store.get_json(manifest.release_dossier_ref, ReleaseDossier)
    missing_commit = dossier.prepackage_commit_refs[-1]
    truncated_dossier = dossier.model_copy(
        update={"prepackage_commit_refs": dossier.prepackage_commit_refs[:-1]}
    )
    truncated_dossier_ref = _framework_writer(store).put_json(
        artifact_id="release-dossier:missing-observability-commit",
        artifact_type="release.dossier",
        value=truncated_dossier,
        dependencies=tuple(
            ref for ref in store.dependencies(manifest.release_dossier_ref) if ref != missing_commit
        ),
    )
    revised_manifest = manifest.model_copy(update={"release_dossier_ref": truncated_dossier_ref})
    revised_manifest_ref = _framework_writer(store).put_json(
        artifact_id="manifest:missing-prepackage-commit",
        artifact_type="environment_package_manifest",
        value=revised_manifest,
        dependencies=tuple(
            truncated_dossier_ref if ref == manifest.release_dossier_ref else ref
            for ref in store.dependencies(graph.manifest_ref)
        ),
    )
    registry = EnvironmentRegistry(tmp_path / "registry", store)
    with pytest.raises(ReleaseRejectedError, match="WorkCommit coordinates are not canonical"):
        registry.prepare(
            candidate_workspace=graph.workspace,
            manifest_ref=revised_manifest_ref,
            judge_report_ref=graph.report_ref,
            release_profile=graph.release_profile,
            reservation=_reserve(registry, graph),
            framework_payloads=graph.framework_payloads,
        )


def test_registry_rejects_incomplete_release_telemetry(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    graph = _release_graph(tmp_path, store)
    manifest = store.get_json(graph.manifest_ref, EnvironmentPackageManifest)
    telemetry = store.get_json(manifest.telemetry_summary_ref, TelemetryReleaseSummary)
    incomplete_telemetry = telemetry.model_copy(
        update={
            "required_node_attempts": {
                key: value
                for key, value in telemetry.required_node_attempts.items()
                if key != "judge"
            }
        }
    )
    incomplete_telemetry_ref = _framework_writer(store).put_json(
        artifact_id="telemetry-summary:missing-judge",
        artifact_type="release.telemetry_summary",
        value=incomplete_telemetry,
        dependencies=store.dependencies(manifest.telemetry_summary_ref),
    )
    dossier = store.get_json(manifest.release_dossier_ref, ReleaseDossier)
    revised_dossier = dossier.model_copy(update={"telemetry_summary_ref": incomplete_telemetry_ref})
    revised_dossier_ref = _framework_writer(store).put_json(
        artifact_id="release-dossier:missing-telemetry-node",
        artifact_type="release.dossier",
        value=revised_dossier,
        dependencies=tuple(
            incomplete_telemetry_ref if ref == manifest.telemetry_summary_ref else ref
            for ref in store.dependencies(manifest.release_dossier_ref)
        ),
    )
    revised_manifest = manifest.model_copy(
        update={
            "telemetry_summary_ref": incomplete_telemetry_ref,
            "release_dossier_ref": revised_dossier_ref,
        }
    )
    revised_manifest_ref = _framework_writer(store).put_json(
        artifact_id="manifest:missing-telemetry-node",
        artifact_type="environment_package_manifest",
        value=revised_manifest,
        dependencies=tuple(
            incomplete_telemetry_ref
            if ref == manifest.telemetry_summary_ref
            else revised_dossier_ref
            if ref == manifest.release_dossier_ref
            else ref
            for ref in store.dependencies(graph.manifest_ref)
        ),
    )
    registry = EnvironmentRegistry(tmp_path / "registry", store)
    with pytest.raises(ReleaseRejectedError, match="does not prove its frozen final-graph output"):
        registry.prepare(
            candidate_workspace=graph.workspace,
            manifest_ref=revised_manifest_ref,
            judge_report_ref=graph.report_ref,
            release_profile=graph.release_profile,
            reservation=_reserve(registry, graph),
            framework_payloads=graph.framework_payloads,
        )


def test_registry_rejects_manifest_from_non_framework_signed_producer(
    tmp_path: Path,
) -> None:
    store = ArtifactStore(tmp_path / "artifact-store")
    graph = _release_graph(tmp_path, store)
    manifest = store.get_json(graph.manifest_ref, EnvironmentPackageManifest)
    untrusted_writer = store.issue_writer(
        producer="environment-builder",
        allowed_artifact_types=("environment_package_manifest",),
    )
    forged_ref = untrusted_writer.put_json(
        artifact_id="manifest:forged-producer",
        artifact_type="environment_package_manifest",
        value=manifest,
        dependencies=store.dependencies(graph.manifest_ref),
    )
    registry = EnvironmentRegistry(tmp_path / "registry", store)
    reservation = _reserve(registry, graph)

    with pytest.raises(ReleaseRejectedError, match="signed framework producer"):
        registry.prepare(
            candidate_workspace=graph.workspace,
            manifest_ref=forged_ref,
            judge_report_ref=graph.report_ref,
            release_profile=graph.release_profile,
            reservation=reservation,
            framework_payloads=graph.framework_payloads,
        )


def test_registry_rejects_judge_report_from_non_judge_signed_producer(
    tmp_path: Path,
) -> None:
    store = ArtifactStore(tmp_path / "artifact-store")
    graph = _release_graph(tmp_path, store)
    report = store.get_json(graph.report_ref, JudgeReport)
    untrusted_writer = store.issue_writer(
        producer="environment-builder",
        allowed_artifact_types=("judge_report",),
    )
    forged_report_ref = untrusted_writer.put_json(
        artifact_id="judge-report:forged-producer",
        artifact_type="judge_report",
        value=report,
        dependencies=store.dependencies(graph.report_ref),
    )
    registry = EnvironmentRegistry(tmp_path / "registry", store)
    reservation = _reserve(registry, graph)

    with pytest.raises(ReleaseRejectedError, match="signed Judge producer"):
        registry.prepare(
            candidate_workspace=graph.workspace,
            manifest_ref=graph.manifest_ref,
            judge_report_ref=forged_report_ref,
            release_profile=graph.release_profile,
            reservation=reservation,
            framework_payloads=graph.framework_payloads,
        )


def test_registry_rejects_undeclared_files(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifact-store")
    graph = _release_graph(tmp_path, store)
    (graph.workspace / "undeclared.txt").write_text("not declared by the package manifest")
    registry = EnvironmentRegistry(tmp_path / "registry", store)
    reservation = _reserve(registry, graph)

    with pytest.raises(UnsafePackageError, match="declaration mismatch"):
        registry.prepare(
            candidate_workspace=graph.workspace,
            manifest_ref=graph.manifest_ref,
            judge_report_ref=graph.report_ref,
            release_profile=graph.release_profile,
            reservation=reservation,
            framework_payloads=graph.framework_payloads,
        )


def test_registry_rejects_known_credential_canary(tmp_path: Path) -> None:
    canary = b"release-boundary-canary-2c75e19e"
    store = ArtifactStore(tmp_path / "artifact-store")
    graph = _release_graph(tmp_path, store, runtime_bytes=b"payload=" + canary + b"\n")
    registry = EnvironmentRegistry(
        tmp_path / "registry",
        store,
        known_secret_canaries=(canary,),
    )
    reservation = _reserve(registry, graph)

    with pytest.raises(UnsafePackageError, match="known secret canary"):
        registry.prepare(
            candidate_workspace=graph.workspace,
            manifest_ref=graph.manifest_ref,
            judge_report_ref=graph.report_ref,
            release_profile=graph.release_profile,
            reservation=reservation,
            framework_payloads=graph.framework_payloads,
        )


def test_registry_rejects_symlinked_payload(tmp_path: Path) -> None:
    if os.name == "nt":
        pytest.skip("symlink creation may require elevated Windows privileges")
    store = ArtifactStore(tmp_path / "artifact-store")
    graph = _release_graph(tmp_path, store)
    outside = tmp_path / "outside-runtime.py"
    outside.write_bytes((graph.workspace / "runtime.py").read_bytes())
    (graph.workspace / "runtime.py").unlink()
    (graph.workspace / "runtime.py").symlink_to(outside)
    registry = EnvironmentRegistry(tmp_path / "registry", store)
    reservation = _reserve(registry, graph)

    with pytest.raises(UnsafePackageError, match="symlink is prohibited"):
        registry.prepare(
            candidate_workspace=graph.workspace,
            manifest_ref=graph.manifest_ref,
            judge_report_ref=graph.report_ref,
            release_profile=graph.release_profile,
            reservation=reservation,
            framework_payloads=graph.framework_payloads,
        )
