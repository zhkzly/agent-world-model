from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from pydantic import HttpUrl
from v3_fixture import (
    build_judge_candidate_graph,
    build_release_graph,
    portable_counter_contracts,
)

from agent_world.agent_profiles import IsolatedAgentProfileProvider
from agent_world.artifact_store import ArtifactStore, ArtifactWriter
from agent_world.builder import (
    BuildBundle,
    BuilderSessionState,
    BuildInvocationSummary,
    BuildRecord,
    EnvironmentBuilder,
    ImplementationContract,
)
from agent_world.config import AgentBackendConfig, FoundryConfig, ResearchConfig
from agent_world.contracts import (
    ArtifactRef,
    Budget,
    BudgetUsage,
    CandidateManifest,
    CandidateOutcome,
    Claim,
    CoverageDimension,
    CoverageMap,
    DesignBaselineCheckpoint,
    DiscoveryAdmissionDecision,
    DiscoveryQuarantineRecommendation,
    DiscoveryRunSpec,
    EnvironmentCandidate,
    EnvironmentJob,
    EnvironmentRequest,
    Evidence,
    EvidenceGraph,
    ExpansionClue,
    ExpansionInboxSnapshot,
    ExpansionSourceCatalog,
    ExpansionSourceDescriptor,
    Finding,
    GateResult,
    ImplementationLineage,
    IntegrationReport,
    JudgeReport,
    KeyValue,
    MutationIntent,
    PermissionScope,
    sha256_digest,
)
from agent_world.control import (
    BudgetExceeded,
    BudgetLease,
    BudgetLedger,
    CampaignAlreadyRunningError,
    CampaignHeadConflictError,
    CampaignIterationRecord,
    CampaignRunCheckpoint,
    CampaignStore,
    ControlEventKind,
    ErrorAuditPolicy,
    JobRunSnapshot,
    LeaseBudgetLedger,
    NodeAttempt,
    RepairLedger,
    RepairRouter,
    StructuredRepairMode,
    TelemetryStore,
    invalidated_nodes,
    new_direct_job_head,
)
from agent_world.controller import (
    DiscoveryLaneState,
    FoundryController,
    _DesignReworkRequired,
    _DiscoveryLane,
    _GenerationHalt,
    _RunState,
)
from agent_world.designer import (
    AdmissionBundle,
    DesignBundle,
    DesignerError,
    DiscoveryBundle,
    DiscoveryService,
    EnvironmentDesigner,
    EvidenceBackedExpansionSource,
    ExpansionDesigner,
    ExpansionSourceRouter,
    PolicyCheckpoint,
)
from agent_world.designer.expansion import (
    AskBudget,
    EvolutionaryArchivePolicy,
    ExpansionContext,
    ParentDescriptor,
    RandomSearchPolicy,
    WideSearchPolicy,
)
from agent_world.expansion_runner import ExpansionCampaignRunner
from agent_world.invocation import CodexSdkBackend, InvocationLimits, InvocationStatus
from agent_world.judge import (
    CompiledVerifier,
    EnvironmentJudge,
    IntegrationBundle,
    JudgeBundle,
    VerifierCompiler,
)
from agent_world.registry import EnvironmentRegistry
from agent_world.research import build_research_toolchain


def _ref(artifact_id: str, artifact_type: str = "test_artifact") -> ArtifactRef:
    digest = sha256_digest(artifact_id.encode())
    return ArtifactRef(
        artifact_id=artifact_id,
        revision_id=digest,
        artifact_type=artifact_type,
        content_hash=digest,
        media_type="application/json",
        size_bytes=0,
    )


def _repair_router_harness(
    tmp_path: Path,
    maximum_attempts: int,
) -> tuple[RepairRouter, ArtifactWriter]:
    store = ArtifactStore(tmp_path / "repair-router-artifacts")
    writer = store.issue_writer(
        producer="framework",
        allowed_artifact_types=("control.finding",),
    )
    return (
        RepairRouter(maximum_attempts=maximum_attempts, artifact_store=writer),
        writer,
    )


def _persist_router_finding(
    writer: ArtifactWriter,
    finding: Finding,
    *,
    suffix: str = "1",
) -> ArtifactRef:
    return writer.put_json(
        artifact_id=f"{finding.finding_id}:router:{suffix}",
        artifact_type="control.finding",
        value=finding,
    )


def _real_controller(root: Path) -> FoundryController:
    """Assemble production classes without invoking any external capability."""

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
    )
    artifacts = ArtifactStore(root / "artifacts")
    controller_artifacts = artifacts.issue_writer(
        producer="framework",
        allowed_artifact_types=("environment_package_manifest",),
        allowed_artifact_type_prefixes=(
            "control.",
            "discovery.",
            "expansion.",
            "release.",
            "test.",
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
        allowed_artifact_type_prefixes=("design.", "discovery."),
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
        allowed_artifact_type_prefixes=("control.", "expansion.", "test."),
    )
    expansion_designer_artifacts = artifacts.issue_writer(
        producer="expansion-designer",
        allowed_artifact_type_prefixes=("expansion.",),
    )
    expansion_source_artifacts = artifacts.issue_writer(
        producer="expansion-source",
        allowed_artifact_types=(
            "expansion.source_hypothesis",
            "expansion.source_clue",
            "expansion.source_result",
        ),
    )
    registry = EnvironmentRegistry(root / "registry", artifacts)
    profiles = IsolatedAgentProfileProvider(agent, source_environment={})
    backend = CodexSdkBackend()
    research = build_research_toolchain(research_config, source_environment={})
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


def test_run_workspace_uses_portable_physical_directory(tmp_path: Path) -> None:
    controller = _real_controller(tmp_path / "foundry")

    builder = controller._workspace_for("run:abc123", "builder")
    repeated = controller._workspace_for("run:abc123", "builder")
    other = controller._workspace_for("run:def456", "builder")
    run_directory = builder.relative_to(controller.workspace_root).parts[0]

    assert builder == repeated
    assert builder != other
    assert ":" not in run_directory
    assert builder.parent.parent == controller.workspace_root


def test_discovery_budget_preflight_fails_terminally_without_touching_direct(
    tmp_path: Path,
) -> None:
    async def exercise() -> None:
        controller = _real_controller(tmp_path / "discovery-preflight")
        request = EnvironmentRequest(
            request_id="request:discovery-preflight",
            need="Generate a real hotel booking environment.",
            permissions=PermissionScope(),
            budget=controller.config.generation_budget,
            release_profile=controller.config.release_profile,
        )
        request_ref = controller.artifacts.put_json(
            artifact_id=request.request_id,
            artifact_type="control.environment_request",
            value=request,
        )
        job = EnvironmentJob(
            job_id="job:discovery-preflight",
            kind="generate",
            request_ref=request_ref,
            permissions=request.permissions,
            budget=request.budget,
            release_profile=request.release_profile,
        )
        job_ref = controller.artifacts.put_json(
            artifact_id=job.job_id,
            artifact_type="control.environment_job",
            value=job,
            dependencies=(request_ref,),
        )
        run = _RunState(
            run_id="run:discovery-preflight",
            job_ref=job_ref,
            ledger=BudgetLedger(request.budget),
        )
        run.remember(request_ref, job_ref)
        direct_before = run.ledger.used

        lane = await controller._start_discovery(  # noqa: SLF001
            run=run,
            job=job,
            job_ref=job_ref,
            request=request,
            request_ref=request_ref,
            budget=Budget(
                llm_tokens=80_000,
                agent_turns=4,
                search_calls=3,
                tool_calls=12,
                wall_seconds=900,
            ),
        )

        assert lane is None
        assert run.ledger.used == direct_before
        state_ref = next(
            ref
            for ref in run.latest.values()
            if ref.artifact_type == "control.discovery_lane_state"
        )
        state = controller.artifacts.get_json(state_ref, DiscoveryLaneState)
        assert state.status == "failed"
        assert state.used_budget == BudgetUsage()
        assert state.failure_code == "discovery_budget_llm_tokens_insufficient"
        attempt = next(item for item in run.attempts if item.node == "discovery")
        assert attempt.status == "failed"
        failure_ref = next(
            ref for ref in run.latest.values() if ref.artifact_type == "control.failure_evidence"
        )
        failure = controller.artifacts.get_json(failure_ref)
        assert failure["dimension"] == "llm_tokens"
        assert failure["reserved"] == 80_000
        assert failure["required"] == 131_072
        assert set(controller.artifacts.dependencies(failure_ref)) == {
            job_ref,
            next(ref for ref in run.latest.values() if ref.artifact_type == "discovery.run_spec"),
            state_ref,
        }
        event_types = [event.event_type for event in controller.artifacts.list_events()]
        assert "discovery_not_started" in event_types
        assert "discovery_started" not in event_types

    asyncio.run(exercise())


def test_compile_branch_repair_leases_do_not_double_reserve_budget(
    tmp_path: Path,
) -> None:
    controller = _real_controller(tmp_path / "foundry")
    remaining = controller.config.generation_budget

    verifier, builder = controller._compile_branch_budgets(  # noqa: SLF001
        remaining,
        verifier_base_turns=controller.verifier_compiler.minimum_invocation_turns(8),
    )

    assert builder.repair_attempts == controller.builder.maximum_precommit_reworks
    assert verifier.agent_turns == 12
    assert verifier.repair_attempts == 8
    assert verifier.repair_attempts + builder.repair_attempts <= remaining.repair_attempts
    assert verifier.agent_turns + builder.agent_turns <= remaining.agent_turns
    assert verifier.llm_tokens + builder.llm_tokens <= remaining.llm_tokens

    ledger = LeaseBudgetLedger(remaining)
    ledger.reserve(
        lease_id="lease:verifier",
        owner_id="attempt:verifier",
        requested=verifier,
        elapsed_wall_seconds=0,
    )
    ledger.reserve(
        lease_id="lease:builder",
        owner_id="attempt:builder",
        requested=builder,
        elapsed_wall_seconds=0,
    )

    recovered_verifier = controller._verifier_only_budget(  # noqa: SLF001
        remaining,
        verifier_base_turns=controller.verifier_compiler.minimum_invocation_turns(8),
    )
    assert recovered_verifier.agent_turns == 12
    assert recovered_verifier.repair_attempts == 8
    assert recovered_verifier.llm_tokens == verifier.llm_tokens
    assert recovered_verifier.build_seconds == 0


def test_direct_terminal_failure_is_recovered_without_replaying_generation(
    tmp_path: Path,
) -> None:
    """The post-checkpoint/pre-result crash window must be pure bookkeeping."""

    controller = _real_controller(tmp_path / "foundry")
    request_id = "request:recover-terminal-failure"
    request = EnvironmentRequest(
        request_id=request_id,
        need="Generate a real local inventory workflow environment.",
        permissions=PermissionScope(),
        budget=controller.config.generation_budget,
        release_profile=controller.config.release_profile,
    )
    request_fingerprint = controller._direct_request_fingerprint(  # noqa: SLF001
        request,
        enable_discovery=False,
        discovery_budget=controller.config.discovery_budget,
    )
    request_ref = controller.artifacts.put_json(
        artifact_id="request-artifact:recover-terminal-failure",
        artifact_type="control.environment_request",
        value=request,
    )
    job = EnvironmentJob(
        job_id="generate-job:recover-terminal-failure",
        kind="generate",
        request_ref=request_ref,
        permissions=request.permissions,
        budget=request.budget,
        release_profile=request.release_profile,
    )
    job_ref = controller.artifacts.put_json(
        artifact_id="generate-job:recover-terminal-failure:job",
        artifact_type="control.environment_job",
        value=job,
        dependencies=(request_ref,),
    )
    running_snapshot = JobRunSnapshot(
        run_id="run:recover-terminal-failure",
        job_ref=job_ref,
        revision=1,
        status="running",
        reserved_budget=request.budget,
        observed_actual_budget=BudgetUsage(),
        unknown_upper_bound_budget=BudgetUsage(),
        conservative_committed_budget=BudgetUsage(),
    )
    running_ref = controller.artifacts.put_json(
        artifact_id="run:recover-terminal-failure:state",
        artifact_type="control.job_run_snapshot",
        value=running_snapshot,
        dependencies=(job_ref,),
    )
    terminal_snapshot = running_snapshot.model_copy(
        update={
            "revision": 2,
            "status": "failed",
            "failure_code": "independent_verification_failed",
            "failure_summary": "Independent verification rejected the candidate.",
        }
    )
    terminal_ref = controller.artifacts.put_json(
        artifact_id="run:recover-terminal-failure:state",
        artifact_type="control.job_run_snapshot",
        value=terminal_snapshot,
        dependencies=(job_ref, running_ref),
    )
    with controller.direct_jobs.exclusive(request_id) as lock:
        running_head = new_direct_job_head(
            request_id=request_id,
            request_fingerprint=request_fingerprint,
            request_ref=request_ref,
            job_ref=job_ref,
            run_id=terminal_snapshot.run_id,
            snapshot_ref=running_ref,
            snapshot_revision=1,
            status="running",
        )
        controller.direct_jobs.compare_and_swap(
            lock,
            expected_head=None,
            next_head=running_head,
        )
        terminal_head = new_direct_job_head(
            request_id=request_id,
            request_fingerprint=request_fingerprint,
            request_ref=request_ref,
            job_ref=job_ref,
            run_id=terminal_snapshot.run_id,
            snapshot_ref=terminal_ref,
            snapshot_revision=2,
            status="failed",
        )
        controller.direct_jobs.compare_and_swap(
            lock,
            expected_head=running_head,
            next_head=terminal_head,
        )

    first = asyncio.run(
        controller.generate(
            request.need,
            request_id=request_id,
            permissions=request.permissions,
            budget=request.budget,
            release_profile=request.release_profile,
            discovery_budget=controller.config.discovery_budget,
            enable_discovery=False,
        )
    )
    second = asyncio.run(
        controller.generate(
            request.need,
            request_id=request_id,
            permissions=request.permissions,
            budget=request.budget,
            release_profile=request.release_profile,
            discovery_budget=controller.config.discovery_budget,
            enable_discovery=False,
        )
    )

    assert first == second
    assert first.status == "failed"
    assert first.final_snapshot_ref == terminal_ref
    assert first.failure_code == "independent_verification_failed"
    assert first.failure_summary == "Independent verification rejected the candidate."
    completed_head = controller.direct_jobs.read_head(request_id)
    assert completed_head is not None
    assert completed_head.result_ref is not None


def test_abandoned_direct_generation_is_cancelled_with_a_new_terminal_revision(
    tmp_path: Path,
) -> None:
    controller = _real_controller(tmp_path / "foundry")
    request_id = "request:cancel-abandoned"
    request = EnvironmentRequest(
        request_id=request_id,
        need="Generate a real local inventory workflow environment.",
        permissions=PermissionScope(),
        budget=controller.config.generation_budget.model_copy(update={"monetary_cost": 5.0}),
        release_profile=controller.config.release_profile,
    )
    fingerprint = controller._direct_request_fingerprint(  # noqa: SLF001
        request,
        enable_discovery=False,
        discovery_budget=controller.config.discovery_budget,
    )
    request_ref = controller.artifacts.put_json(
        artifact_id="request-artifact:cancel-abandoned",
        artifact_type="control.environment_request",
        value=request,
    )
    job = EnvironmentJob(
        job_id="generate-job:cancel-abandoned",
        kind="generate",
        request_ref=request_ref,
        permissions=request.permissions,
        budget=request.budget,
        release_profile=request.release_profile,
    )
    job_ref = controller.artifacts.put_json(
        artifact_id="generate-job:cancel-abandoned:job",
        artifact_type="control.environment_job",
        value=job,
        dependencies=(request_ref,),
    )
    lease = LeaseBudgetLedger(request.budget).reserve(
        lease_id="lease:abandoned-builder",
        owner_id="attempt:abandoned-builder",
        requested=Budget(
            llm_tokens=100,
            agent_turns=1,
            build_seconds=10,
            wall_seconds=30,
            monetary_cost=1,
        ),
        elapsed_wall_seconds=0,
    )
    lease_ref = controller.artifacts.put_json(
        artifact_id=f"run:cancel-abandoned:budget-lease:{lease.lease_id}",
        artifact_type="control.budget_lease",
        value=lease,
        dependencies=(job_ref,),
    )
    running = JobRunSnapshot(
        run_id="run:cancel-abandoned",
        job_ref=job_ref,
        revision=1,
        status="running",
        reserved_budget=request.budget,
        observed_actual_budget=BudgetUsage(),
        unknown_upper_bound_budget=BudgetUsage(),
        conservative_committed_budget=BudgetUsage(),
        attempts=(
            NodeAttempt(
                attempt_id=lease.owner_id,
                node="build",
                ordinal=1,
                status="running",
                started_at=datetime.now(UTC),
                input_refs=(job_ref, lease_ref),
            ),
        ),
        latest_artifact_refs=(lease_ref,),
    )
    running_ref = controller.artifacts.put_json(
        artifact_id="run:cancel-abandoned:state",
        artifact_type="control.job_run_snapshot",
        value=running,
        dependencies=(job_ref,),
    )
    with controller.direct_jobs.exclusive(request_id) as lock:
        controller.direct_jobs.compare_and_swap(
            lock,
            expected_head=None,
            next_head=new_direct_job_head(
                request_id=request_id,
                request_fingerprint=fingerprint,
                request_ref=request_ref,
                job_ref=job_ref,
                run_id=running.run_id,
                snapshot_ref=running_ref,
                snapshot_revision=1,
                status="running",
            ),
        )

    result = asyncio.run(controller.cancel_abandoned_generation(request_id))

    assert result.status == "failed"
    assert result.failure_code == "operator_cancelled"
    assert result.final_snapshot_ref != running_ref
    terminal = controller.artifacts.get_json(result.final_snapshot_ref, JobRunSnapshot)
    assert terminal.revision == 2
    assert terminal.status == "failed"
    assert terminal.failure_code == "operator_cancelled"
    assert terminal.observed_actual_budget == BudgetUsage()
    assert terminal.unknown_upper_bound_budget == BudgetUsage(
        llm_tokens=100,
        agent_turns=1,
        build_seconds=10,
        monetary_cost=1,
    )
    assert terminal.attempts[0].status == "failed"
    assert terminal.attempts[0].budget_usage == terminal.unknown_upper_bound_budget
    terminal_lease = next(
        controller.artifacts.get_json(ref, type(lease))
        for ref in controller.artifacts.list_revisions(lease_ref.artifact_id)
        if controller.artifacts.get_json(ref, type(lease)).status == "settled"
    )
    assert terminal_lease.status == "settled"
    assert terminal_lease.unknown_upper_bound == terminal.unknown_upper_bound_budget
    completed_head = controller.direct_jobs.read_head(request_id)
    assert completed_head is not None
    assert completed_head.status == "failed"
    assert completed_head.result_ref is not None


def test_expansion_identity_gate_rejection_is_typed_design_rework(tmp_path: Path) -> None:
    controller = _real_controller(tmp_path / "foundry")
    subject_ref = controller.artifacts.put_json(
        artifact_id="identity-gate-subject",
        artifact_type="expansion.environment_design",
        value=KeyValue(key="kind", value="expansion-design"),
    )
    run = _RunState(
        run_id="candidate-run:identity-rework",
        job_ref=subject_ref,
        ledger=BudgetLedger(Budget(repair_attempts=1, wall_seconds=30)),
    )

    correction = controller._expansion_identity_correction(
        run=run,
        design_ref=subject_ref,
        error_type="IdentityMismatch",
    )

    assert len(correction.findings) == len(correction.finding_refs) == 1
    finding = controller.artifacts.get_json(correction.finding_refs[0], Finding)
    assert finding.owner == "design"
    assert finding.category == "expansion_identity_gate_failed"
    directive = RepairRouter(
        maximum_attempts=1,
        artifact_store=controller.artifacts,
    ).route(finding, correction.finding_refs[0])
    assert directive.action == "new_revision"
    assert directive.invalidates == (
        "verifier",
        "build",
        "integration",
        "judge",
        "release",
    )


@pytest.mark.asyncio
async def test_direct_design_rework_reuses_judge_route_and_closes_authorization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario = _discovery_scenario(tmp_path, "direct-design-route")
    controller = scenario.controller
    run = scenario.run
    previous = scenario.design
    request = controller.artifacts.get_json(previous.design.request_ref, EnvironmentRequest)
    job = controller.artifacts.get_json(run.job_ref, EnvironmentJob)
    revised_design = previous.design.model_copy(update={"revision": previous.design.revision + 1})
    revised_design_ref = controller.designer.artifacts.put_json(
        artifact_id=previous.design_ref.artifact_id,
        artifact_type="design.environment_design",
        value=revised_design,
        dependencies=controller.artifacts.dependencies(previous.design_ref),
    )
    revised = replace(
        previous,
        design=revised_design,
        design_ref=revised_design_ref,
        invocation_usage=BudgetUsage(),
        invocation_results=(),
    )

    async def revise(**_kwargs: object) -> DesignBundle:
        return revised

    monkeypatch.setattr(controller.designer, "revise", revise)
    fingerprint = sha256_digest(b"judge-found-design-semantic-defect")
    finding = Finding(
        finding_id="finding:judge-design-rework",
        category="design_transition_semantics",
        severity="high",
        owner="design",
        subject_ref=previous.design_ref,
        summary="Judge found a design-owned transition defect.",
        evidence_refs=(previous.design_ref,),
        fingerprint=fingerprint,
        disclosure="public",
        suggested_repair="Revise the owning WorldSpec transition.",
    )
    finding_ref = controller.artifacts.put_json(
        artifact_id="finding:judge-design-rework",
        artifact_type="control.finding",
        value=finding,
        dependencies=(previous.design_ref,),
    )
    directive = RepairRouter(
        maximum_attempts=job.budget.repair_attempts,
        artifact_store=controller.artifacts,
    ).route(
        finding,
        finding_ref,
        current_node="judge",
        ledger=run.repair_ledger,
        blocking_claim_ids_before=(fingerprint,),
    )
    ledger_ref = controller._persist_repair_ledger_entries(  # noqa: SLF001
        run,
        (directive,),
    )[0]
    directive_ref = controller.artifacts.put_json(
        artifact_id="directive:judge-design-rework",
        artifact_type="control.repair_directive",
        value=directive,
        dependencies=(finding_ref, previous.design_ref, ledger_ref),
    )

    result = await controller._run_direct_design_revision(  # noqa: SLF001
        run=run,
        job=job,
        job_ref=run.job_ref,
        request=request,
        request_ref=previous.design.request_ref,
        previous=previous,
        correction=_DesignReworkRequired(
            findings=(finding,),
            finding_refs=(finding_ref,),
            directive_refs=(directive_ref,),
        ),
    )

    assert result.design_ref == revised_design_ref
    assert len(run.repair_ledger.entries) == 1
    entry = run.repair_ledger.entries[0]
    assert entry.current_node == "judge"
    assert entry.target_node == "design"
    assert entry.outcome == "resolved"
    assert entry.finished_at is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("verifier_first", [False, True])
async def test_parallel_verifier_cannot_delay_build_commit_or_integration_start(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    verifier_first: bool,
) -> None:
    scenario = _discovery_scenario(tmp_path, "parallel-build-integration")
    controller = scenario.controller
    controller.config = controller.config.model_copy(
        update={
            "agent": controller.config.agent.model_copy(update={"max_concurrent_invocations": 2})
        }
    )
    store = controller.artifacts._store  # noqa: SLF001 - shared real ArtifactStore
    candidate_root = tmp_path / "candidate"
    candidate_root.mkdir()
    graph = build_judge_candidate_graph(candidate_root, store)

    def latest(artifact_id: str) -> ArtifactRef:
        return store.list_revisions(artifact_id)[-1]

    implementation_contract_ref = graph.candidate.implementation_contract_ref
    source_snapshot_ref = graph.candidate.source_workspace_snapshot_ref
    implementation_lineage_ref = graph.candidate.implementation_lineage_ref
    build_artifact_ref = graph.candidate.build_artifact_ref
    candidate_manifest_ref = graph.candidate.candidate_manifest_ref
    build_bundle = BuildBundle(
        implementation_contract=store.get_json(
            implementation_contract_ref,
            ImplementationContract,
        ),
        implementation_contract_ref=implementation_contract_ref,
        source_snapshot_ref=source_snapshot_ref,
        implementation_lineage=store.get_json(
            implementation_lineage_ref,
            ImplementationLineage,
        ),
        implementation_lineage_ref=implementation_lineage_ref,
        candidate_manifest=store.get_json(candidate_manifest_ref, CandidateManifest),
        candidate_manifest_ref=candidate_manifest_ref,
        build_record=store.get_json(build_artifact_ref, BuildRecord),
        build_artifact_ref=build_artifact_ref,
        candidate=store.get_json(graph.candidate_ref, EnvironmentCandidate),
        candidate_ref=graph.candidate_ref,
        project_root=graph.workspace,
        session=None,
        state=None,
        invocation=BuildInvocationSummary(
            invocation_id="invocation:parallel-build",
            status=InvocationStatus.COMPLETED,
            duration_ms=1,
            usage=None,
            backend_version="test-contract",
        ),
    )
    compiled = CompiledVerifier(
        verifier=graph.verifier,
        verifier_ref=graph.verifier_ref,
        invocation_results=(),
    )
    verifier_started = asyncio.Event()
    allow_verifier_finish = asyncio.Event()
    order: list[str] = []

    async def compile_verifier(**_kwargs: object) -> CompiledVerifier:
        verifier_started.set()
        if not verifier_first:
            await allow_verifier_finish.wait()
        order.append("verifier_finished")
        return compiled

    async def build_candidate(**_kwargs: object) -> BuildBundle:
        await verifier_started.wait()
        if verifier_first:
            verifier_attempt = next(
                item for item in scenario.run.attempts if item.node == "verifier"
            )
            while verifier_attempt.status == "running":
                await asyncio.sleep(0)
                verifier_attempt = next(
                    item for item in scenario.run.attempts if item.node == "verifier"
                )
            assert verifier_attempt.status == "passed"
            order.append("builder_observed_verifier_passed")
        order.append("builder_finished")
        return build_bundle

    async def integrate_candidate(**kwargs: object) -> tuple[None, BuildBundle]:
        order.append("integration_started")
        build = kwargs["build"]
        assert isinstance(build, BuildBundle)
        sibling_reservation = kwargs["sibling_reservation"]
        assert callable(sibling_reservation)
        build_attempt = next(item for item in scenario.run.attempts if item.node == "build")
        assert build_attempt.status == "passed"
        assert build_attempt.attempt_id in scenario.run.node_commit_refs
        if not verifier_first:
            assert sibling_reservation() is not None
            assert not allow_verifier_finish.is_set()
            allow_verifier_finish.set()
            verifier_attempt = next(
                item for item in scenario.run.attempts if item.node == "verifier"
            )
            while verifier_attempt.status == "running":
                await asyncio.sleep(0)
                verifier_attempt = next(
                    item for item in scenario.run.attempts if item.node == "verifier"
                )
            assert verifier_attempt.status == "passed"
        assert sibling_reservation() is None
        return None, build

    monkeypatch.setattr(controller.builder, "build", build_candidate)
    monkeypatch.setattr(controller.verifier_compiler, "compile", compile_verifier)
    monkeypatch.setattr(controller, "_integrate_and_repair", integrate_candidate)

    result_compiled, result_build = await controller._compile_and_build(  # noqa: SLF001
        scenario.run,
        controller.artifacts.get_json(scenario.run.job_ref, EnvironmentJob),
        scenario.design,
    )

    assert result_compiled == compiled
    assert result_build == build_bundle
    assert order == (
        [
            "verifier_finished",
            "builder_observed_verifier_passed",
            "builder_finished",
            "integration_started",
        ]
        if verifier_first
        else ["builder_finished", "integration_started", "verifier_finished"]
    )
    assert latest(graph.candidate_ref.artifact_id) == graph.candidate_ref


@pytest.mark.asyncio
@pytest.mark.parametrize("fault_stage", ["terminal_persist", "global_consume"])
async def test_compile_cleanup_completes_partial_branch_terminalization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fault_stage: str,
) -> None:
    scenario = _discovery_scenario(tmp_path, f"compile-terminal-{fault_stage}")
    controller = scenario.controller
    controller.config = controller.config.model_copy(
        update={
            "agent": controller.config.agent.model_copy(update={"max_concurrent_invocations": 2})
        }
    )
    store = controller.artifacts._store  # noqa: SLF001
    candidate_root = tmp_path / f"candidate-{fault_stage}"
    candidate_root.mkdir()
    graph = build_judge_candidate_graph(candidate_root, store)
    build_bundle = BuildBundle(
        implementation_contract=store.get_json(
            graph.candidate.implementation_contract_ref,
            ImplementationContract,
        ),
        implementation_contract_ref=graph.candidate.implementation_contract_ref,
        source_snapshot_ref=graph.candidate.source_workspace_snapshot_ref,
        implementation_lineage=store.get_json(
            graph.candidate.implementation_lineage_ref,
            ImplementationLineage,
        ),
        implementation_lineage_ref=graph.candidate.implementation_lineage_ref,
        candidate_manifest=store.get_json(
            graph.candidate.candidate_manifest_ref,
            CandidateManifest,
        ),
        candidate_manifest_ref=graph.candidate.candidate_manifest_ref,
        build_record=store.get_json(graph.candidate.build_artifact_ref, BuildRecord),
        build_artifact_ref=graph.candidate.build_artifact_ref,
        candidate=store.get_json(graph.candidate_ref, EnvironmentCandidate),
        candidate_ref=graph.candidate_ref,
        project_root=graph.workspace,
        session=None,
        state=None,
        invocation=BuildInvocationSummary(
            invocation_id=f"invocation:{fault_stage}",
            status=InvocationStatus.COMPLETED,
            duration_ms=1,
            usage=None,
            backend_version="test-contract",
            unknown_token_upper_bounds=(100,),
        ),
    )
    compiled = CompiledVerifier(
        verifier=graph.verifier,
        verifier_ref=graph.verifier_ref,
        invocation_results=(),
    )

    async def compile_verifier(**_kwargs: object) -> CompiledVerifier:
        return compiled

    async def build_candidate(**_kwargs: object) -> BuildBundle:
        return build_bundle

    async def integrate_candidate(**kwargs: object) -> tuple[None, BuildBundle]:
        build = kwargs["build"]
        assert isinstance(build, BuildBundle)
        return None, build

    monkeypatch.setattr(controller.builder, "build", build_candidate)
    monkeypatch.setattr(controller.verifier_compiler, "compile", compile_verifier)
    monkeypatch.setattr(controller, "_integrate_and_repair", integrate_candidate)
    injected = False
    if fault_stage == "terminal_persist":
        original_persist = controller._persist_budget_lease  # noqa: SLF001

        def fail_terminal_persist_once(*args: object, **kwargs: object) -> ArtifactRef:
            nonlocal injected
            lease = args[1]
            if not injected and getattr(lease, "status", None) == "settled":
                injected = True
                raise RuntimeError("injected terminal lease persistence failure")
            return original_persist(*args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(controller, "_persist_budget_lease", fail_terminal_persist_once)
    else:
        original_consume = BudgetLedger.consume_uncertain

        def fail_global_consume_once(
            ledger: BudgetLedger,
            *,
            observed_actual: BudgetUsage,
            unknown_upper_bound: BudgetUsage,
        ) -> BudgetUsage:
            nonlocal injected
            if ledger is scenario.run.ledger and not injected:
                injected = True
                raise RuntimeError("injected global budget consumption failure")
            return original_consume(
                ledger,
                observed_actual=observed_actual,
                unknown_upper_bound=unknown_upper_bound,
            )

        monkeypatch.setattr(BudgetLedger, "consume_uncertain", fail_global_consume_once)

    with pytest.raises(RuntimeError, match="injected"):
        await controller._compile_and_build(  # noqa: SLF001
            scenario.run,
            controller.artifacts.get_json(scenario.run.job_ref, EnvironmentJob),
            scenario.design,
        )

    assert injected
    compile_attempts = tuple(
        item for item in scenario.run.attempts if item.node in {"build", "verifier"}
    )
    assert compile_attempts
    assert all(item.status not in {"pending", "running"} for item in compile_attempts)
    terminal_leases = tuple(
        controller.artifacts.get_json(ref, BudgetLease)
        for ref in scenario.run.latest.values()
        if ref.artifact_type == "control.budget_lease"
    )
    assert terminal_leases
    assert all(item.status != "active" for item in terminal_leases)
    assert scenario.run.ledger.used != BudgetUsage()


def test_budget_ledger_never_exchanges_dimensions() -> None:
    ledger = BudgetLedger(
        Budget(
            llm_tokens=1_000,
            agent_turns=3,
            search_calls=2,
            wall_seconds=60.0,
        )
    )

    used = ledger.consume(
        BudgetUsage(llm_tokens=400, agent_turns=1, search_calls=2, wall_seconds=15.5)
    )
    assert used.search_calls == 2
    assert ledger.remaining == Budget(
        llm_tokens=600,
        agent_turns=2,
        search_calls=0,
        wall_seconds=44.5,
    )
    assert not ledger.can_consume(BudgetUsage(search_calls=1))
    assert ledger.can_consume(BudgetUsage(llm_tokens=600, agent_turns=2))

    with pytest.raises(BudgetExceeded) as error:
        ledger.consume(BudgetUsage(search_calls=1, llm_tokens=1))
    assert error.value.dimensions == ("search_calls",)
    assert ledger.used == used


def test_budget_ledger_separates_actual_unknown_and_conservative_commitment() -> None:
    ledger = BudgetLedger(Budget(llm_tokens=1_000, agent_turns=4))

    committed = ledger.consume_uncertain(
        observed_actual=BudgetUsage(llm_tokens=300, agent_turns=1),
        unknown_upper_bound=BudgetUsage(llm_tokens=200, agent_turns=1),
    )

    assert ledger.observed_actual == BudgetUsage(llm_tokens=300, agent_turns=1)
    assert ledger.unknown_upper_bound == BudgetUsage(llm_tokens=200, agent_turns=1)
    assert committed == BudgetUsage(llm_tokens=500, agent_turns=2)
    assert ledger.remaining.llm_tokens == 500
    assert ledger.remaining.agent_turns == 2


def test_campaign_budget_leases_reserve_non_wall_dimensions_and_share_one_deadline() -> None:
    ledger = LeaseBudgetLedger(
        Budget(
            llm_tokens=1_000,
            agent_turns=10,
            search_calls=4,
            evaluation_episodes=8,
            wall_seconds=100,
        )
    )
    first_budget = Budget(
        llm_tokens=400,
        agent_turns=4,
        search_calls=2,
        evaluation_episodes=4,
        wall_seconds=80,
    )
    second_budget = Budget(
        llm_tokens=500,
        agent_turns=5,
        search_calls=2,
        evaluation_episodes=4,
        wall_seconds=80,
    )
    first = ledger.reserve(
        lease_id="lease:first",
        owner_id="candidate:first",
        requested=first_budget,
        elapsed_wall_seconds=10,
    )
    second = ledger.reserve(
        lease_id="lease:second",
        owner_id="candidate:second",
        requested=second_budget,
        elapsed_wall_seconds=10,
    )

    assert first.status == second.status == "active"
    assert ledger.remaining(elapsed_wall_seconds=10) == Budget(
        llm_tokens=100,
        agent_turns=1,
        wall_seconds=90,
    )
    with pytest.raises(BudgetExceeded) as error:
        ledger.reserve(
            lease_id="lease:third",
            owner_id="candidate:third",
            requested=Budget(agent_turns=2, wall_seconds=10),
            elapsed_wall_seconds=10,
        )
    assert error.value.dimensions == ("agent_turns",)

    settled = ledger.settle(
        first.lease_id,
        BudgetUsage(
            llm_tokens=300,
            agent_turns=3,
            search_calls=1,
            evaluation_episodes=2,
            wall_seconds=70,
        ),
    )
    ledger.release(second.lease_id)
    assert settled.status == "settled"
    assert ledger.usage(elapsed_wall_seconds=75) == BudgetUsage(
        llm_tokens=300,
        agent_turns=3,
        search_calls=1,
        evaluation_episodes=2,
        wall_seconds=75,
    )
    assert ledger.remaining(elapsed_wall_seconds=75) == Budget(
        llm_tokens=700,
        agent_turns=7,
        search_calls=3,
        evaluation_episodes=6,
        wall_seconds=25,
    )


def test_campaign_budget_lease_restore_and_idempotent_active_reservation() -> None:
    reserved = Budget(agent_turns=4, wall_seconds=60)
    initial = LeaseBudgetLedger(reserved)
    lease = initial.reserve(
        lease_id="lease:resume",
        owner_id="candidate:resume",
        requested=Budget(agent_turns=2, wall_seconds=40),
        elapsed_wall_seconds=5,
    )
    restored = LeaseBudgetLedger(reserved, leases=initial.leases)

    assert (
        restored.reserve(
            lease_id="lease:resume",
            owner_id="candidate:resume",
            requested=lease.reserved,
            elapsed_wall_seconds=5,
        )
        == lease
    )
    with pytest.raises(ValueError, match="different or terminal"):
        restored.reserve(
            lease_id="lease:resume",
            owner_id="candidate:other",
            requested=lease.reserved,
            elapsed_wall_seconds=5,
        )


def test_campaign_budget_lease_rejects_child_overuse() -> None:
    ledger = LeaseBudgetLedger(Budget(agent_turns=2, wall_seconds=30))
    lease = ledger.reserve(
        lease_id="lease:bounded",
        owner_id="candidate:bounded",
        requested=Budget(agent_turns=1, wall_seconds=20),
        elapsed_wall_seconds=0,
    )

    with pytest.raises(BudgetExceeded, match="agent_turns"):
        ledger.settle(
            lease.lease_id,
            BudgetUsage(agent_turns=2, wall_seconds=5),
        )


def test_campaign_store_enforces_single_writer_and_checkpoint_cas(tmp_path: Path) -> None:
    store = CampaignStore(tmp_path / "campaigns")
    campaign_id = "campaign:single-writer"
    first_ref = _ref("checkpoint:first", "control.campaign_checkpoint")
    second_ref = _ref("checkpoint:second", "control.campaign_checkpoint")

    with store.exclusive(campaign_id) as lock:
        first = store.compare_and_swap(
            lock,
            expected_checkpoint_ref=None,
            checkpoint_ref=first_ref,
            checkpoint_revision=1,
        )
        assert first.checkpoint_ref == first_ref
        with pytest.raises(CampaignAlreadyRunningError):
            with CampaignStore(tmp_path / "campaigns").exclusive(campaign_id):
                pass
        with pytest.raises(CampaignHeadConflictError):
            store.compare_and_swap(
                lock,
                expected_checkpoint_ref=None,
                checkpoint_ref=second_ref,
                checkpoint_revision=2,
            )
        second = store.compare_and_swap(
            lock,
            expected_checkpoint_ref=first_ref,
            checkpoint_ref=second_ref,
            checkpoint_revision=2,
        )
        assert second.checkpoint_ref == second_ref

    reopened = CampaignStore(tmp_path / "campaigns")
    assert reopened.read_head(campaign_id) == second


def test_campaign_framework_checkpoint_is_separate_from_policy_state() -> None:
    campaign_ref = _ref("campaign:one", "expansion.campaign")
    before_ref = _ref("policy:before", "expansion.policy_checkpoint")
    after_ref = _ref("policy:after", "expansion.policy_checkpoint")
    intent_ref = _ref("intent:one", "expansion.mutation_intent")
    outcome_ref = _ref("outcome:one", "expansion.candidate_outcome")
    lease_ref = _ref("lease:one", "control.budget_lease")
    source_catalog_ref = _ref("source-catalog:one", "expansion.source_catalog")
    source_intake_ref = _ref("source-intake:one", "control.source_intake")
    source_request_ref = _ref("source-request:one", "expansion.source_request")
    source_lease_ref = _ref("source-lease:one", "control.budget_lease")
    source_result_ref = _ref("source-result:one", "expansion.source_result")
    clue_snapshot_ref = _ref("clue-snapshot:one", "expansion.clue_snapshot")
    context_ref = _ref("expansion-context:one", "expansion.context")
    planned = CampaignIterationRecord(
        iteration_id="iteration:one",
        campaign_ref=campaign_ref,
        number=0,
        status="planned",
        policy_before_ref=before_ref,
        intent_refs=(intent_ref,),
    )
    leased = planned.model_copy(update={"status": "leased", "lease_refs": (lease_ref,)})
    told_ref = _ref("iteration:one:told", "control.campaign_iteration")
    evaluated = leased.model_copy(
        update={
            "status": "evaluated",
            "outcome_refs": (outcome_ref,),
        }
    )
    told = CampaignIterationRecord(
        **evaluated.model_dump(exclude={"status", "policy_after_ref"}),
        status="told",
        policy_after_ref=after_ref,
    )
    now = datetime.now(UTC)
    checkpoint = CampaignRunCheckpoint(
        checkpoint_id="campaign-checkpoint:one",
        campaign_ref=campaign_ref,
        revision=2,
        status="running",
        started_at=now,
        deadline_at=now + timedelta(minutes=5),
        next_iteration=1,
        updated_at=now,
        policy_checkpoint_ref=after_ref,
        phase="candidate_loop",
        source_catalog_ref=source_catalog_ref,
        source_intake_ref=source_intake_ref,
        source_request_refs=(source_request_ref,),
        source_lease_refs=(source_lease_ref,),
        source_result_refs=(source_result_ref,),
        clue_snapshot_ref=clue_snapshot_ref,
        context_ref=context_ref,
        completed_iteration_refs=(told_ref,),
        lease_refs=(source_lease_ref, lease_ref),
        outcome_refs=(outcome_ref,),
    )

    assert planned.status == "planned"
    assert leased.status == "leased"
    assert told.status == "told"
    assert checkpoint.policy_checkpoint_ref == after_ref
    assert checkpoint.outcome_refs == (outcome_ref,)


def test_campaign_resume_settles_unknown_leased_candidate_and_tells_policy(
    tmp_path: Path,
) -> None:
    state_root = tmp_path / "foundry"
    controller = _real_controller(state_root)
    store = controller.registry._artifact_store  # noqa: SLF001 - real shared trust root
    (tmp_path / "parent-release").mkdir()
    graph = build_release_graph(
        tmp_path / "parent-release",
        store,
        variant="candidate-recovery",
    )
    reservation = controller.registry.reserve_package_version(
        graph.package_id,
        graph.version,
        graph.owner_ref,
    )
    prepared = controller.registry.prepare(
        candidate_workspace=graph.workspace,
        manifest_ref=graph.manifest_ref,
        judge_report_ref=graph.report_ref,
        release_profile=graph.release_profile,
        reservation=reservation,
        framework_payloads=graph.framework_payloads,
    )
    release = controller.registry.publish(prepared)

    class SourceBoundaryFailure:
        async def discover(self, **_kwargs: object) -> object:
            raise RuntimeError("deliberate Source infrastructure interruption")

    runner = ExpansionCampaignRunner(
        artifact_store=controller.expansion_artifacts,
        registry=controller.registry,
        campaign_store=controller.campaign_store,
        candidate_executor=controller,
        expansion_source=SourceBoundaryFailure(),  # type: ignore[arg-type]
        source_workspace_root=state_root / "source-recovery-workspaces",
    )
    artifacts = controller.expansion_artifacts
    candidate_budget = Budget(
        llm_tokens=1_000,
        agent_turns=4,
        search_calls=2,
        tool_calls=8,
        build_seconds=20,
        evaluation_episodes=6,
        container_seconds=30,
        live_probe_cost=1.5,
        repair_attempts=2,
        wall_seconds=120,
        monetary_cost=3.25,
    )
    source_budget = Budget(
        llm_tokens=100,
        agent_turns=2,
        search_calls=1,
        tool_calls=2,
        wall_seconds=30,
    )
    campaign_budget = Budget(
        llm_tokens=2_000,
        agent_turns=8,
        search_calls=4,
        tool_calls=16,
        build_seconds=40,
        evaluation_episodes=12,
        container_seconds=60,
        live_probe_cost=3,
        repair_attempts=4,
        wall_seconds=300,
        monetary_cost=6.5,
    )
    source_catalog = ExpansionSourceCatalog(
        catalog_id="source-catalog:candidate-recovery",
        sources=(
            ExpansionSourceDescriptor(
                source_id="source:candidate-recovery",
                kind="random_theme",
                budget=source_budget,
            ),
        ),
    )

    campaign_id = "campaign:candidate-recovery"
    with controller.campaign_store.exclusive(campaign_id) as lock:
        state = runner._create_state(  # noqa: SLF001
            lock=lock,
            campaign_id=campaign_id,
            anchor_package_refs=(release.manifest_ref,),
            target_coverage_dimensions=("tool_semantics",),
            inbox_snapshot_ref=None,
            source_catalog=source_catalog,
            feedback_refs=(),
            policy_id="random-search",
            policy_parameters=(),
            permissions=PermissionScope(),
            campaign_budget=campaign_budget,
            candidate_budget=candidate_budget,
            release_profile=graph.release_profile,
            campaign_seed=41,
            maximum_intents_per_iteration=1,
            maximum_in_flight=1,
            maximum_iterations=3,
            maximum_no_release_iterations=2,
            maximum_infrastructure_error_iterations=3,
            version_reservation_ttl_seconds=60,
            allowed_source_kinds=("web",),
            risk_level="medium",
            fidelity_requirements=(),
        )
        state = asyncio.run(runner._execute_source_intake(lock, state))  # noqa: SLF001
        assert state.checkpoint.phase == "candidate_loop"
        assert state.context is not None

        intent = MutationIntent(
            intent_id="intent:candidate-recovery",
            parent_refs=(release.manifest_ref,),
            primary_parent_ref=release.manifest_ref,
            operator="tool_semantics",
            operator_version="1",
            parameters=(KeyValue(key="focus", value="errors"),),
            seed=17,
            target_coverage_dimensions=("tool_semantics",),
        )
        intent_ref = controller.expansion_artifacts.put_json(
            artifact_id="mutation-intent:candidate-recovery",
            artifact_type="expansion.mutation_intent",
            value=intent,
            dependencies=(
                state.campaign_ref,
                state.policy_checkpoint_ref,
                release.manifest_ref,
            ),
        )
        lease = state.ledger.reserve(
            lease_id="budget-lease:candidate-recovery",
            owner_id=intent.intent_id,
            requested=candidate_budget,
            elapsed_wall_seconds=0,
        )
        lease_ref = runner._persist_lease(  # noqa: SLF001
            state.campaign_ref,
            intent_ref,
            lease,
            previous_ref=None,
        )
        leased = CampaignIterationRecord(
            iteration_id="campaign-iteration:candidate-recovery",
            campaign_ref=state.campaign_ref,
            number=0,
            status="leased",
            policy_before_ref=state.policy_checkpoint_ref,
            intent_refs=(intent_ref,),
            lease_refs=(lease_ref,),
        )
        leased_ref = runner._persist_iteration(leased, previous_ref=None)  # noqa: SLF001
        state = runner._advance_checkpoint(  # noqa: SLF001
            lock,
            state,
            active_iteration_ref=leased_ref,
            lease_refs=(*state.checkpoint.lease_refs, lease_ref),
        )

    with controller.campaign_store.exclusive(campaign_id) as lock:
        interrupted_head = controller.campaign_store.read_head(campaign_id)
        assert interrupted_head is not None
        interrupted = runner._load_state(interrupted_head.checkpoint_ref)  # noqa: SLF001
        recovered = asyncio.run(  # noqa: SLF001
            runner._recover_active_iteration(lock, interrupted)
        )

    assert recovered.checkpoint.active_iteration_ref is None
    assert recovered.checkpoint.next_iteration == 1
    assert recovered.checkpoint.consecutive_infrastructure_failures == 1
    assert len(recovered.checkpoint.completed_iteration_refs) == 1
    assert len(recovered.checkpoint.outcome_refs) == 1
    head = controller.campaign_store.read_head(campaign_id)
    assert head is not None
    assert head.checkpoint_ref == recovered.checkpoint_ref
    assert head.checkpoint_revision == recovered.checkpoint.revision

    outcome_ref = recovered.checkpoint.outcome_refs[0]
    outcome = controller.expansion_artifacts.get_json(outcome_ref, CandidateOutcome)
    expected_usage = BudgetUsage.model_validate(
        candidate_budget.model_dump(exclude={"schema_version"})
    )
    assert outcome.terminal_status == "infrastructure_error"
    assert outcome.terminal_reason_code == "campaign_resume_unknown_leased_execution"
    assert outcome.budget_usage == expected_usage
    assert outcome.campaign_ref == state.campaign_ref
    assert outcome.iteration_ref == leased_ref
    assert outcome.intent_ref == intent_ref

    lease_history = tuple(
        artifacts.get_json(ref, type(lease))
        for ref in recovered.checkpoint.lease_refs
        if ref.artifact_id == lease_ref.artifact_id
    )
    assert {item.status for item in lease_history} == {"active", "settled"}
    settled = next(item for item in lease_history if item.status == "settled")
    assert settled.observed_actual == expected_usage
    assert settled.unknown_upper_bound == BudgetUsage()
    assert settled.conservative_committed == expected_usage
    assert recovered.ledger.active_leases == ()

    told_ref = recovered.checkpoint.completed_iteration_refs[0]
    told = artifacts.get_json(told_ref, CampaignIterationRecord)
    assert told.status == "told"
    assert told.outcome_refs == (outcome_ref,)
    evaluated = tuple(
        artifacts.get_json(ref, CampaignIterationRecord)
        for ref in artifacts.dependencies(told_ref)
        if ref.artifact_type == "control.campaign_iteration"
    )
    assert any(item.status == "evaluated" for item in evaluated)
    policy_after = artifacts.get_json(
        recovered.checkpoint.policy_checkpoint_ref,
        PolicyCheckpoint,
    )
    assert policy_after.seen_outcome_ids == (outcome.outcome_id,)
    assert policy_after.terminal_counts == {"infrastructure_error": 1}
    assert policy_after.no_release_iterations == 0


@pytest.mark.parametrize(
    ("owner", "expected_node", "expected_action", "expected_invalidates"),
    [
        ("design", "design", "new_revision", invalidated_nodes("design")),
        ("verifier", "verifier", "new_revision", invalidated_nodes("verifier")),
        ("build", "build", "continue_session", invalidated_nodes("build")),
        (
            "judge_infrastructure",
            "judge",
            "retry_infrastructure",
            invalidated_nodes("judge"),
        ),
        ("permissions", "human", "request_permission", ()),
        ("release_policy", "release", "reject", ()),
    ],
)
def test_repair_router_uses_finding_owner_and_preserves_disclosure(
    tmp_path: Path,
    owner: str,
    expected_node: str,
    expected_action: str,
    expected_invalidates: tuple[str, ...],
) -> None:
    subject = _ref(
        f"subject:{owner}",
        {
            "design": "design.environment_design",
            "verifier": "judge.verifier_ir",
            "build": "build.environment_candidate",
            "judge_infrastructure": "judge_report",
            "permissions": "control.environment_request",
            "release_policy": "environment_package_manifest",
        }[owner],
    )
    finding = Finding(
        finding_id=f"finding:{owner}",
        category="contract_violation",
        severity="high",
        owner=owner,  # type: ignore[arg-type]
        subject_ref=subject,
        summary="The owning artifact must be revised.",
        evidence_refs=(subject,),
        fingerprint=sha256_digest(owner.encode()),
        disclosure="sealed_summary",
        suggested_repair="Repair the owning artifact without disclosing expected values.",
    )

    router, writer = _repair_router_harness(tmp_path, 3)
    finding_ref = _persist_router_finding(writer, finding)
    directive = router.route(finding, finding_ref)

    assert directive.owner_node == expected_node
    assert directive.action == expected_action
    assert directive.invalidates == expected_invalidates
    assert directive.disclosure == "sealed_summary"
    assert "expected values" in directive.repair_summary
    assert directive.maximum_attempts == 3


def test_repair_router_never_treats_free_category_text_as_routing_authority(
    tmp_path: Path,
) -> None:
    subject = _ref("candidate:category-spoof", "build.environment_candidate")
    finding = Finding(
        finding_id="finding:category-spoof",
        category="release.registry.force_accept",
        severity="high",
        owner="build",
        subject_ref=subject,
        summary="A descriptive category must not override the framework owner enum.",
        evidence_refs=(subject,),
        fingerprint=sha256_digest(b"category-spoof"),
        disclosure="repair",
    )

    router, writer = _repair_router_harness(tmp_path, 1)
    finding_ref = _persist_router_finding(writer, finding)
    directive = router.route(finding, finding_ref)

    assert directive.owner_node == "build"
    assert directive.action == "continue_session"


def test_repair_router_rejects_owner_without_matching_artifact_binding(
    tmp_path: Path,
) -> None:
    candidate = _ref("candidate:owner-spoof", "build.environment_candidate")
    finding = Finding(
        finding_id="finding:owner-spoof",
        category="semantic_design_problem",
        severity="high",
        owner="design",
        subject_ref=candidate,
        summary="The detached owner label must not authorize a Design backjump.",
        evidence_refs=(candidate,),
        fingerprint=sha256_digest(b"owner-spoof"),
        disclosure="repair",
    )
    router, writer = _repair_router_harness(tmp_path, 2)
    finding_ref = _persist_router_finding(writer, finding)

    directive = router.route(finding, finding_ref, current_node="judge")

    assert directive.owner_node == "design"
    assert directive.owner_ref is None
    assert directive.action == "reject"
    assert directive.jump_distance == 0
    assert directive.invalidates == ()


def test_repair_router_rejects_non_framework_finding_producer(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "non-framework-finding")
    framework = store.issue_writer(
        producer="framework",
        allowed_artifact_types=("control.finding", "design.environment_design"),
    )
    challenger = store.issue_writer(
        producer="environment-judge",
        allowed_artifact_types=("control.finding",),
    )
    subject = framework.put_json(
        artifact_id="design:non-framework-finding",
        artifact_type="design.environment_design",
        value={"placeholder": "framework-owned subject"},
    )
    finding = Finding(
        finding_id="finding:non-framework-producer",
        category="semantic_design_problem",
        severity="high",
        owner="design",
        subject_ref=subject,
        summary="An Agent producer must not gain Router authority.",
        evidence_refs=(subject,),
        fingerprint=sha256_digest(b"non-framework-producer"),
        disclosure="repair",
    )
    finding_ref = challenger.put_json(
        artifact_id=finding.finding_id,
        artifact_type="control.finding",
        value=finding,
    )

    with pytest.raises(ValueError, match="framework-authored"):
        RepairRouter(maximum_attempts=2, artifact_store=framework).route(
            finding,
            finding_ref,
            current_node="judge",
        )


def test_modeling_failure_binds_design_subject_and_gate_as_causal_evidence(
    tmp_path: Path,
) -> None:
    scenario = _discovery_scenario(tmp_path, "modeling-finding-binding")
    gate_ref = scenario.controller.artifacts.put_json(
        artifact_id="modeling-gate:finding-binding",
        artifact_type="control.modeling_gate",
        value=KeyValue(key="status", value="fail"),
        dependencies=(scenario.design.design_ref,),
    )

    finding_ref = scenario.controller._control_failure_finding(  # noqa: SLF001
        scenario.run,
        node="design",
        event_kind=ControlEventKind.CONTRACT_FAILURE,
        code="modeling_gate_failed",
        error_type="ModelingGateRejected",
        subject_ref=scenario.design.design_ref,
        causal_refs=(gate_ref,),
        repair_context=("unresolved_assumptions_forbidden",),
    )

    finding = scenario.controller.artifacts.get_json(finding_ref, Finding)
    assert finding.subject_ref == scenario.design.design_ref
    assert gate_ref in finding.evidence_refs
    directive = RepairRouter(
        maximum_attempts=2,
        artifact_store=scenario.controller.artifacts,
    ).route(finding, finding_ref, current_node="design")
    assert directive.owner_ref == scenario.design.design_ref
    assert directive.action == "new_revision"
    assert directive.jump_distance == 0


def test_repair_router_groups_many_findings_into_one_executable_action(
    tmp_path: Path,
) -> None:
    candidate = _ref("candidate:grouped", "build.environment_candidate")
    evidence = _ref("evaluation:grouped", "judge.property_evidence")
    findings = tuple(
        Finding(
            finding_id=f"finding:grouped:{index}",
            category=f"runtime_contract_{index}",
            severity="high",
            owner="build",
            subject_ref=candidate,
            summary=f"Runtime defect {index} must be repaired.",
            evidence_refs=(evidence,),
            fingerprint=sha256_digest(f"runtime-defect-{index}".encode()),
            disclosure="repair",
            suggested_repair=f"Repair runtime defect {index}.",
        )
        for index in range(2)
    )
    router, writer = _repair_router_harness(tmp_path, 3)
    finding_refs = tuple(
        _persist_router_finding(writer, finding, suffix=str(index))
        for index, finding in enumerate(findings)
    )
    ledger = RepairLedger()

    routes = router.route_many(
        tuple(zip(findings, finding_refs, strict=True)),
        current_node="judge",
        ledger=ledger,
        blocking_claim_ids_before=tuple(item.fingerprint for item in findings),
    )

    assert len(routes) == 1
    assert len(ledger.entries) == 1
    assert routes[0].finding_ref == finding_refs[0]
    assert routes[0].related_finding_refs == (finding_refs[1],)
    assert ledger.entries[0].related_finding_refs == (finding_refs[1],)
    assert "defect 0" in routes[0].repair_summary
    assert "defect 1" in routes[0].repair_summary


def test_framework_task_reset_invariant_does_not_trigger_semantic_rework(
    tmp_path: Path,
) -> None:
    state_shape_ref = _ref(
        "world-state-shape:payment",
        "design.world_state_shape",
    )
    finding = Finding(
        finding_id="finding:framework-task-reset-invariant",
        category="framework_invariant_violation",
        severity="critical",
        owner="judge_infrastructure",
        subject_ref=state_shape_ref,
        summary="Typed state IR violated a deterministic framework projection invariant.",
        evidence_refs=(state_shape_ref,),
        fingerprint=sha256_digest(b"framework-task-reset-invariant"),
        disclosure="repair",
        suggested_repair="Inspect the framework compiler without revising Agent semantics.",
    )

    router, writer = _repair_router_harness(tmp_path, 2)
    finding_ref = _persist_router_finding(writer, finding)
    directive = router.route(
        finding,
        finding_ref,
        current_node="design",
    )

    assert directive.owner_node == "judge"
    assert directive.owner_ref is None
    assert directive.action == "reject"
    assert directive.jump_distance == 0
    assert directive.invalidates == ()
    assert directive.causal_evidence_refs == (state_shape_ref,)


def test_repair_ledger_restore_stops_immediately_after_identical_no_progress(
    tmp_path: Path,
) -> None:
    subject = _ref("judge-report:1", "judge_report")
    evidence = _ref("sandbox-evidence:1", "judge.sandbox_evidence")
    finding = Finding(
        finding_id="finding:stable-infrastructure-root-cause",
        category="judge_infrastructure_timeout",
        severity="high",
        owner="judge_infrastructure",
        subject_ref=subject,
        summary="The sandbox supervisor timed out before the runtime became ready.",
        evidence_refs=(evidence,),
        fingerprint=sha256_digest(b"stable-infrastructure-root-cause"),
        disclosure="repair",
        suggested_repair="Retry only the independent judge infrastructure.",
    )
    router, writer = _repair_router_harness(tmp_path, 3)
    first_ref = _persist_router_finding(writer, finding, suffix="1")
    original = RepairLedger()
    first = router.route(
        finding,
        first_ref,
        current_node="judge",
        ledger=original,
        blocking_claim_ids_before=("runtime.executable",),
    )
    assert first.action == "retry_infrastructure"
    original.complete(
        first.ledger_entry_id or "",
        blocking_claim_ids_after=("runtime.executable",),
    )

    restored = RepairLedger(entries=original.entries)
    second_ref = _persist_router_finding(writer, finding, suffix="2")
    second = router.route(
        finding,
        second_ref,
        current_node="judge",
        ledger=restored,
        blocking_claim_ids_before=("runtime.executable",),
    )
    assert second.action == "reject"
    assert second.ledger_entry_id is not None
    assert [entry.attempt_ordinal for entry in restored.entries] == [1, 2]
    assert restored.entries[-1].outcome == "exhausted"


def test_repair_ledger_requires_explicit_validator_stage_progress() -> None:
    subject = _ref("design:state", "design.state_entity_inventory")
    evidence = _ref("validation:state", "control.structured_repair_evidence")
    finding_ref = _ref("finding:state", "control.finding")
    finding = Finding(
        finding_id="finding:state-layer-transition",
        category="structured_semantic_correction",
        severity="high",
        owner="design",
        subject_ref=subject,
        summary="The state inventory must advance through typed validation.",
        evidence_refs=(evidence,),
        fingerprint=sha256_digest(b"state-layer-transition"),
        disclosure="repair",
        suggested_repair="Correct the current typed state artifact.",
    )
    ledger = RepairLedger()
    authorized = ledger.authorize(
        finding=finding,
        finding_ref=finding_ref,
        current_node="design",
        target_node="design",
        owner_ref=subject,
        action="continue_session",
        jump_distance=0,
        causal_evidence_refs=(evidence,),
        blocking_claim_ids_before=("state_inventory_resource_coverage",),
        validation_phase_before="inventory_resources",
        validation_frontier_before=20,
    )

    completed = ledger.complete(
        authorized.entry_id,
        blocking_claim_ids_after=("state_inventory_visibility_coverage",),
        progress_evidence="validation_stage_advanced",
        validation_phase_after="inventory_visibility",
        validation_frontier_after=30,
    )

    assert completed.outcome == "progressed"
    assert completed.blocking_claim_ids_after == ("state_inventory_visibility_coverage",)
    assert completed.progress_evidence == "validation_stage_advanced"
    assert completed.validation_frontier_before == 20
    assert completed.validation_frontier_after == 30


def test_error_audit_policy_triggers_for_interval_and_hash_only_diagnostics() -> None:
    subject = _ref("build:candidate", "build.environment_candidate")
    evidence = _ref("build:diagnostic", "control.structured_repair_evidence")
    ledger = RepairLedger()
    for index in range(3):
        finding = Finding(
            finding_id=f"finding:audit:{index}",
            category="builder_structured_correction",
            severity="high",
            owner="build",
            subject_ref=subject,
            summary="Builder output requires a bounded correction.",
            evidence_refs=(evidence,),
            fingerprint=sha256_digest(f"audit:{index}".encode()),
            disclosure="repair",
        )
        issue_code = (
            "builder_agent.output:0123456789abcdef" if index == 0 else f"completion_schema_{index}"
        )
        ledger.authorize(
            finding=finding,
            finding_ref=_ref(f"finding-ref:audit:{index}", "control.finding"),
            current_node="build",
            target_node="build",
            owner_ref=subject,
            action="continue_session",
            jump_distance=0,
            causal_evidence_refs=(evidence,),
            blocking_claim_ids_before=(issue_code,),
        )

    decision = ErrorAuditPolicy(error_interval=3).evaluate(
        ledger.entries,
        last_audited_entry_count=0,
        seconds_since_last_audit=1,
    )

    assert decision.triggered
    assert set(decision.trigger_codes) == {"error_interval", "generic_diagnostic"}
    assert "replace_generic_diagnostic_with_typed_issue" in decision.recommended_actions
    assert decision.open_authorization_count == 3


def test_repair_ledger_rejects_unproven_disjoint_blocker_churn() -> None:
    subject = _ref("design:state", "design.state_entity_inventory")
    evidence = _ref("validation:state", "control.structured_repair_evidence")
    finding_ref = _ref("finding:state", "control.finding")
    finding = Finding(
        finding_id="finding:state-unproven-transition",
        category="structured_semantic_correction",
        severity="high",
        owner="design",
        subject_ref=subject,
        summary="The state inventory changed blockers without stage evidence.",
        evidence_refs=(evidence,),
        fingerprint=sha256_digest(b"state-unproven-transition"),
        disclosure="repair",
    )
    ledger = RepairLedger()
    authorized = ledger.authorize(
        finding=finding,
        finding_ref=finding_ref,
        current_node="design",
        target_node="design",
        owner_ref=subject,
        action="continue_session",
        jump_distance=0,
        causal_evidence_refs=(evidence,),
        blocking_claim_ids_before=("blocker:a",),
    )

    completed = ledger.complete(
        authorized.entry_id,
        blocking_claim_ids_after=("blocker:b",),
    )

    assert completed.outcome == "no_progress"
    assert completed.progress_evidence == "none"
    restored = RepairLedger(
        entries=(type(completed).model_validate(completed.model_dump(mode="python")),)
    )
    assert restored.entries == (completed,)


def test_repair_ledger_detects_a_b_a_oscillation_within_one_repair_family() -> None:
    subject = _ref("design:oscillation", "design.environment_design")
    evidence = _ref("validation:oscillation", "control.structured_repair_evidence")
    finding_ref = _ref("finding:oscillation", "control.finding")
    finding = Finding(
        finding_id="finding:oscillation",
        category="structured_semantic_correction",
        severity="high",
        owner="design",
        subject_ref=subject,
        summary="The same transaction alternated between two blocker sets.",
        evidence_refs=(evidence,),
        fingerprint=sha256_digest(b"oscillation"),
        disclosure="repair",
    )
    ledger = RepairLedger()
    first = ledger.authorize(
        finding=finding,
        finding_ref=finding_ref,
        repair_fingerprint="repair-family:stable",
        current_node="design",
        target_node="design",
        owner_ref=subject,
        action="continue_session",
        jump_distance=0,
        causal_evidence_refs=(evidence,),
        blocking_claim_ids_before=("blocker:a",),
    )
    first_done = ledger.complete(
        first.entry_id,
        blocking_claim_ids_after=("blocker:b",),
        progress_evidence="issue_set_changed",
    )
    second = ledger.authorize(
        finding=finding,
        finding_ref=finding_ref,
        repair_fingerprint="repair-family:stable",
        current_node="design",
        target_node="design",
        owner_ref=subject,
        action="continue_session",
        jump_distance=0,
        causal_evidence_refs=(evidence,),
        blocking_claim_ids_before=("blocker:b",),
    )
    second_done = ledger.complete(
        second.entry_id,
        blocking_claim_ids_after=("blocker:a",),
        progress_evidence="issue_set_changed",
    )

    assert first_done.outcome == "progressed"
    assert second_done.outcome == "no_progress"


def test_repair_router_zero_attempt_policy_never_authorizes_work(tmp_path: Path) -> None:
    subject = _ref("candidate:no-retry", "build.environment_candidate")
    evidence = _ref("evaluation:no-retry", "judge.property_evidence")
    finding = Finding(
        finding_id="finding:no-retry",
        category="runtime_contract_no_retry",
        severity="high",
        owner="build",
        subject_ref=subject,
        summary="The runtime contract failed under a zero-retry policy.",
        evidence_refs=(evidence,),
        fingerprint=sha256_digest(b"runtime-contract-no-retry"),
        disclosure="repair",
    )
    ledger = RepairLedger()

    router, writer = _repair_router_harness(tmp_path, 0)
    finding_ref = _persist_router_finding(writer, finding)
    directive = router.route(
        finding,
        finding_ref,
        current_node="judge",
        ledger=ledger,
        blocking_claim_ids_before=(finding.fingerprint,),
    )

    assert directive.action == "reject"
    assert ledger.entries[0].outcome == "exhausted"
    assert ledger.entries[0].finished_at is not None


def test_repair_ledger_terminally_escalates_unexecuted_authorization(tmp_path: Path) -> None:
    subject = _ref("candidate:escalated", "build.environment_candidate")
    evidence = _ref("evaluation:escalated", "judge.property_evidence")
    finding = Finding(
        finding_id="finding:escalated",
        category="runtime_contract_escalated",
        severity="high",
        owner="build",
        subject_ref=subject,
        summary="A conflicting upstream action prevents this repair from executing.",
        evidence_refs=(evidence,),
        fingerprint=sha256_digest(b"runtime-contract-escalated"),
        disclosure="repair",
    )
    ledger = RepairLedger()
    router, writer = _repair_router_harness(tmp_path, 2)
    finding_ref = _persist_router_finding(writer, finding)
    directive = router.route(
        finding,
        finding_ref,
        current_node="judge",
        ledger=ledger,
        blocking_claim_ids_before=(finding.fingerprint,),
    )

    terminal = ledger.terminate(
        directive.ledger_entry_id or "",
        outcome="escalated",
        retained_refs=(subject,),
    )

    assert terminal.outcome == "escalated"
    assert terminal.retained_refs == (subject,)
    assert terminal.finished_at is not None


def test_expansion_policies_are_deterministic_replaceable_and_idempotent() -> None:
    context = ExpansionContext(
        context_id="campaign:determinism",
        snapshot_ref=_ref("pool:snapshot", "environment_pool_snapshot"),
        parents=(
            ParentDescriptor(package_ref=_ref("package:alpha", "environment_package")),
            ParentDescriptor(package_ref=_ref("package:beta", "environment_package")),
        ),
        anchor_parent_refs=(_ref("package:alpha", "environment_package"),),
        clue_refs=(
            _ref("clue:tool-errors", "expansion_clue"),
            _ref("clue:workflow", "expansion_clue"),
        ),
        target_coverage_dimensions=("tool_semantics", "transition_constraints"),
        campaign_seed=918273,
        maximum_iterations=5,
        maximum_no_release_iterations=2,
    )
    ask_budget = AskBudget(
        maximum_intents=5,
        remaining=Budget(agent_turns=5, wall_seconds=120),
    )

    random_policy = RandomSearchPolicy()
    first = asyncio.run(random_policy.ask(context, None, ask_budget))
    second = asyncio.run(random_policy.ask(context, None, ask_budget))
    assert first == second
    assert len(first) == 5
    assert all(intent.parent_refs for intent in first)
    assert all(intent.primary_parent_ref in intent.parent_refs for intent in first)
    assert all(intent.operator != "workspace" for intent in first)
    assert {intent.operator for intent in first} <= {
        "tool_surface",
        "tool_semantics",
        "transition_constraint",
        "task_scope",
        "composite",
    }

    wide = asyncio.run(WideSearchPolicy().ask(context, None, ask_budget))
    assert [intent.operator for intent in wide] == [
        "tool_surface",
        "tool_semantics",
        "transition_constraint",
        "task_scope",
        "composite",
    ]

    outcome = CandidateOutcome(
        outcome_id="outcome:build-failed",
        campaign_ref=_ref("campaign:outcome", "expansion.campaign"),
        iteration_ref=_ref("iteration:outcome", "control.campaign_iteration"),
        intent_ref=_ref("intent:outcome", "expansion.mutation_intent"),
        attempt_ref=_ref("attempt:1", "node_attempt"),
        job_ref=_ref("job:outcome", "control.environment_job"),
        terminal_reason_code="build_failed",
        terminal_status="build_failed",
        budget_usage=BudgetUsage(agent_turns=1, build_seconds=3.0),
    )
    policy = EvolutionaryArchivePolicy(external_injection_rate=1.0)
    checkpoint = asyncio.run(policy.tell(None, (outcome,)))
    same_checkpoint = asyncio.run(policy.tell(checkpoint, (outcome,)))
    assert checkpoint == same_checkpoint
    assert checkpoint.iteration == 1
    assert checkpoint.no_release_iterations == 1
    assert checkpoint.terminal_counts == {"build_failed": 1}
    assert (
        policy.should_stop(
            context,
            checkpoint,
            Budget(agent_turns=1, wall_seconds=30),
        ).reason
        == "continue"
    )

    released = CandidateOutcome(
        outcome_id="outcome:released",
        campaign_ref=_ref("campaign:outcome", "expansion.campaign"),
        iteration_ref=_ref("iteration:outcome", "control.campaign_iteration"),
        intent_ref=_ref("intent:released", "expansion.mutation_intent"),
        attempt_ref=_ref("attempt:released", "node_attempt"),
        job_ref=_ref("job:released", "control.environment_job"),
        terminal_reason_code="released",
        candidate_ref=_ref("candidate:released", "environment_candidate"),
        released_package_ref=_ref("package:released", "environment_package_manifest"),
        terminal_status="released",
        hard_gate_results=(
            GateResult(
                gate_id="behavior",
                status="pass",
                hard=True,
                subject_ref=_ref("candidate:released", "environment_candidate"),
                evidence_refs=(_ref("evidence:released", "evaluation_evidence"),),
                duration_seconds=1.0,
                summary="Real isolated behavior gate passed.",
            ),
        ),
        semantic_lineage_ref=_ref("lineage:semantic", "semantic_lineage"),
        implementation_lineage_ref=_ref("lineage:implementation", "implementation_lineage"),
    )
    archive_checkpoint = asyncio.run(policy.tell(checkpoint, (released,)))
    assert archive_checkpoint.archive_parent_refs == (released.released_package_ref,)

    second_outcome = CandidateOutcome(
        outcome_id="outcome:research-failed",
        campaign_ref=_ref("campaign:outcome", "expansion.campaign"),
        iteration_ref=_ref("iteration:outcome", "control.campaign_iteration"),
        intent_ref=_ref("intent:research", "expansion.mutation_intent"),
        attempt_ref=_ref("attempt:2", "node_attempt"),
        job_ref=_ref("job:research", "control.environment_job"),
        terminal_reason_code="research_failed",
        terminal_status="research_failed",
    )
    exhausted = asyncio.run(policy.tell(checkpoint, (second_outcome,)))
    assert (
        policy.should_stop(
            context,
            exhausted,
            Budget(agent_turns=1, wall_seconds=30),
        ).reason
        == "no_release_progress"
    )


def test_composite_policy_recombines_pool_parents_without_requiring_a_clue() -> None:
    alpha = _ref("package:alpha", "environment_package_manifest")
    beta = _ref("package:beta", "environment_package_manifest")
    gamma = _ref("package:gamma", "environment_package_manifest")
    context = ExpansionContext(
        context_id="campaign:clueless-recombination",
        snapshot_ref=_ref("pool:clueless", "environment_pool_snapshot"),
        parents=tuple(ParentDescriptor(package_ref=parent) for parent in (alpha, beta, gamma)),
        anchor_parent_refs=(alpha,),
        target_coverage_dimensions=("tool_semantics",),
        campaign_seed=993,
    )
    ask_budget = AskBudget(
        maximum_intents=5,
        remaining=Budget(agent_turns=5, wall_seconds=120),
    )

    intents = asyncio.run(WideSearchPolicy().ask(context, None, ask_budget))
    composite = next(intent for intent in intents if intent.operator == "composite")
    assert composite.clue_refs == ()
    assert 2 <= len(composite.parent_refs) <= 3
    assert set(composite.parent_refs) <= {alpha, beta, gamma}

    single_parent_context = context.model_copy(
        update={
            "context_id": "campaign:single-parent-without-clue",
            "parents": (ParentDescriptor(package_ref=alpha),),
        }
    )
    single_parent_intents = asyncio.run(
        WideSearchPolicy().ask(single_parent_context, None, ask_budget)
    )
    assert all(intent.operator != "composite" for intent in single_parent_intents)


def test_expansion_policy_stops_when_a_required_budget_dimension_is_empty() -> None:
    context = ExpansionContext(
        context_id="campaign:budget",
        snapshot_ref=_ref("pool:budget", "environment_pool_snapshot"),
        parents=(ParentDescriptor(package_ref=_ref("package:one", "environment_package")),),
        anchor_parent_refs=(_ref("package:one", "environment_package"),),
        target_coverage_dimensions=("tools",),
        campaign_seed=7,
    )
    policy = RandomSearchPolicy()
    checkpoint = asyncio.run(policy.tell(None, ()))

    decision = policy.should_stop(
        context,
        checkpoint,
        Budget(agent_turns=1, wall_seconds=0),
    )
    assert decision.stop
    assert decision.reason == "budget_exhausted"


def test_expansion_policy_records_infrastructure_without_treating_it_as_fitness() -> None:
    context = ExpansionContext(
        context_id="campaign:infrastructure",
        snapshot_ref=_ref("pool:infrastructure", "environment_pool_snapshot"),
        parents=(ParentDescriptor(package_ref=_ref("package:one", "environment_package")),),
        anchor_parent_refs=(_ref("package:one", "environment_package"),),
        target_coverage_dimensions=("tools",),
        campaign_seed=11,
        maximum_no_release_iterations=1,
    )
    policy = EvolutionaryArchivePolicy()
    outcome = CandidateOutcome(
        outcome_id="outcome:infrastructure",
        campaign_ref=_ref("campaign:infrastructure", "expansion.campaign"),
        iteration_ref=_ref("iteration:infrastructure", "control.campaign_iteration"),
        intent_ref=_ref("intent:infrastructure", "expansion.mutation_intent"),
        attempt_ref=_ref("attempt:infrastructure", "node_attempt"),
        job_ref=_ref("job:infrastructure", "control.environment_job"),
        terminal_reason_code="infrastructure_error",
        terminal_status="infrastructure_error",
    )

    checkpoint = asyncio.run(policy.tell(None, (outcome,)))

    assert checkpoint.iteration == 1
    assert checkpoint.no_release_iterations == 0
    assert checkpoint.terminal_counts == {"infrastructure_error": 1}
    assert not policy.should_stop(
        context,
        checkpoint,
        Budget(agent_turns=1, wall_seconds=30),
    ).stop


@dataclass(frozen=True, slots=True)
class _DiscoveryScenario:
    controller: FoundryController
    run: _RunState
    design: DesignBundle
    bundle: DiscoveryBundle
    spec: DiscoveryRunSpec
    spec_ref: ArtifactRef
    state_ref: ArtifactRef
    discovery_budget: Budget
    invocation_budget: Budget


def _discovery_scenario(tmp_path: Path, name: str) -> _DiscoveryScenario:
    controller = _real_controller(tmp_path / name)
    store = controller.artifacts._store  # noqa: SLF001 - shared real test store
    executable = portable_counter_contracts(store).design
    request = EnvironmentRequest(
        request_id=f"request:{name}",
        need="Discover additional real counter tool and workflow semantics.",
        permissions=PermissionScope(),
        budget=controller.config.generation_budget,
        release_profile=controller.config.release_profile,
    )
    request_ref = controller.artifacts.put_json(
        artifact_id=f"request:{name}",
        artifact_type="control.environment_request",
        value=request,
    )
    job = EnvironmentJob(
        job_id=f"job:{name}",
        kind="generate",
        request_ref=request_ref,
        permissions=request.permissions,
        budget=request.budget,
        release_profile=request.release_profile,
    )
    job_ref = controller.artifacts.put_json(
        artifact_id=f"job:{name}",
        artifact_type="control.environment_job",
        value=job,
        dependencies=(request_ref,),
    )
    source_ref = controller.artifacts.put_json(
        artifact_id=f"source:{name}",
        artifact_type="test.discovery_source",
        value={"observed": "counter workflows expose additional tool semantics"},
    )
    source_hash = sha256_digest(b"counter workflows expose additional tool semantics")
    evidence = Evidence(
        evidence_id=f"evidence:{name}",
        source_kind="web",
        source_uri="https://example.invalid/counter-workflow",
        retrieved_at=datetime.now(UTC),
        retrieval_status="success",
        raw_content_hash=source_hash,
        content_hash=source_hash,
        fetcher="test-fetcher",
        fetcher_version="1",
        extractor="test-extractor",
        extractor_version="1",
        observed_summary="A fetched source describes additional counter workflow semantics.",
        content_ref=source_ref,
    )
    evidence_ref = controller.discovery.artifacts.put_json(
        artifact_id=f"evidence:{name}",
        artifact_type="discovery.evidence",
        value=evidence,
        dependencies=(source_ref,),
    )
    evidence_graph = EvidenceGraph(
        graph_id=f"graph:{name}",
        revision=1,
        evidence=(evidence,),
        claims=(
            Claim(
                claim_id=f"claim:{name}",
                kind="observed",
                statement="The workflow has evidence-backed adjacent tool semantics.",
                confidence=0.9,
                evidence_ids=(evidence.evidence_id,),
                status="supported",
            ),
        ),
    )
    evidence_graph_ref = controller.discovery.artifacts.put_json(
        artifact_id=f"evidence-graph:{name}",
        artifact_type="design.evidence_graph",
        value=evidence_graph,
        dependencies=(evidence_ref,),
    )
    coverage = CoverageMap(
        coverage_id=f"coverage:{name}",
        revision=1,
        dimensions=(
            CoverageDimension(
                dimension="tool_semantics",
                evidence_discovered="complete",
                world_modelled="complete",
                claim_ids=(f"claim:{name}",),
            ),
        ),
        evidence_graph_ref=evidence_graph_ref,
    )
    coverage_ref = controller.discovery.artifacts.put_json(
        artifact_id=f"coverage:{name}",
        artifact_type="design.coverage_map",
        value=coverage,
        dependencies=(evidence_graph_ref,),
    )
    world_ref = controller.discovery.artifacts.put_json(
        artifact_id=f"world:{name}",
        artifact_type="design.world_spec",
        value=executable.world_spec,
        dependencies=(evidence_graph_ref,),
    )
    design = executable.model_copy(
        update={
            "job_ref": job_ref,
            "request_ref": request_ref,
            "evidence_graph_ref": evidence_graph_ref,
            "coverage_map_ref": coverage_ref,
        }
    )
    design_ref = controller.discovery.artifacts.put_json(
        artifact_id=f"design:{name}",
        artifact_type="design.environment_design",
        value=design,
        dependencies=(job_ref, request_ref, evidence_graph_ref, coverage_ref, world_ref),
    )
    baseline = DesignBaselineCheckpoint(
        checkpoint_id=f"baseline:{name}",
        origin_job_ref=job_ref,
        created_at=datetime.now(UTC),
        request_ref=request_ref,
        evidence_graph_ref=evidence_graph_ref,
        coverage_map_ref=coverage_ref,
        world_spec_ref=world_ref,
        scope_fingerprint=sha256_digest(name.encode()),
    )
    baseline_ref = controller.discovery.artifacts.put_json(
        artifact_id=f"baseline:{name}",
        artifact_type="design.baseline_checkpoint",
        value=baseline,
        dependencies=(job_ref, request_ref, evidence_graph_ref, coverage_ref, world_ref),
    )
    design_bundle = DesignBundle(
        evidence_graph=evidence_graph,
        evidence_graph_ref=evidence_graph_ref,
        coverage_map=coverage,
        coverage_map_ref=coverage_ref,
        world_spec=executable.world_spec,
        world_spec_ref=world_ref,
        design=design,
        design_ref=design_ref,
        baseline=baseline,
        baseline_ref=baseline_ref,
        research_usage=BudgetUsage(),
        invocation_usage=BudgetUsage(),
        invocation_results=(),
    )
    discovery_budget = Budget(
        llm_tokens=200_000,
        agent_turns=12,
        search_calls=2,
        tool_calls=8,
        wall_seconds=30,
    )
    invocation_budget = Budget(llm_tokens=1_000, agent_turns=2, wall_seconds=10)
    run_id = f"discovery:{name}"
    spec = DiscoveryRunSpec(
        discovery_run_id=run_id,
        origin_job_ref=job_ref,
        request_ref=request_ref,
        source_kinds=("web",),
        agent_profile_ref=source_ref,
        budget=discovery_budget,
        permissions=PermissionScope(),
        seed=7,
    )
    spec_ref = controller.artifacts.put_json(
        artifact_id=f"{run_id}:spec",
        artifact_type="discovery.run_spec",
        value=spec,
        dependencies=(job_ref, request_ref, source_ref),
    )
    state_ref = controller._persist_discovery_state(  # noqa: SLF001
        spec_ref=spec_ref,
        state=DiscoveryLaneState(
            discovery_run_ref=spec_ref,
            status="running",
            reserved_budget=discovery_budget,
            used_budget=BudgetUsage(),
        ),
    )
    run = _RunState(
        run_id=f"run:{name}",
        job_ref=job_ref,
        ledger=BudgetLedger(controller.config.generation_budget),
    )
    run.remember(request_ref, job_ref, spec_ref, state_ref)
    controller._start_attempt(run, "discovery", (spec_ref,))  # noqa: SLF001
    clue = ExpansionClue(
        clue_id=f"clue:{name}",
        origin_run_ref=spec_ref,
        evidence_refs=(evidence_ref,),
        hypothesis="A critical-risk workflow variant may exercise additional tool semantics.",
        tool_or_workflow_surface=("counter.adjust",),
        coverage_dimensions=("tool_semantics",),
        scope_relation="adjacent",
        feasibility="supported",
        risk="critical",
        dedup_fingerprint=sha256_digest(f"clue:{name}".encode()),
    )
    clue_ref = controller.discovery.artifacts.put_json(
        artifact_id=f"clue:{name}",
        artifact_type="discovery.expansion_clue",
        value=clue,
        dependencies=(spec_ref, evidence_ref),
    )
    bundle = DiscoveryBundle(
        clues=(clue,),
        clue_refs=(clue_ref,),
        evidence=(evidence,),
        research_usage=BudgetUsage(search_calls=1, tool_calls=1),
        invocation_usage=BudgetUsage(llm_tokens=100, agent_turns=1),
        invocation_results=(),
    )
    return _DiscoveryScenario(
        controller=controller,
        run=run,
        design=design_bundle,
        bundle=bundle,
        spec=spec,
        spec_ref=spec_ref,
        state_ref=state_ref,
        discovery_budget=discovery_budget,
        invocation_budget=invocation_budget,
    )


@dataclass(frozen=True, slots=True)
class _BuilderRepairScenario:
    controller: FoundryController
    run: _RunState
    job: EnvironmentJob
    design: DesignBundle
    build: BuildBundle
    integration: IntegrationBundle
    compiled: CompiledVerifier


def _builder_repair_scenario(tmp_path: Path, name: str) -> _BuilderRepairScenario:
    """Create a real control-plane graph with only external execution replaced."""

    discovery = _discovery_scenario(tmp_path, name)
    controller = discovery.controller
    store = controller.artifacts._store  # noqa: SLF001 - shared real ArtifactStore
    candidate_root = tmp_path / f"candidate-{name}"
    candidate_root.mkdir()
    graph = build_judge_candidate_graph(candidate_root, store)
    graph_design = replace(
        discovery.design,
        world_spec=graph.design.world_spec,
        world_spec_ref=graph.world_spec_ref,
        design=graph.design,
        design_ref=graph.design_ref,
    )
    profile_hash = sha256_digest(f"{name}:repair-profile".encode()).removeprefix("sha256:")
    config_hash = sha256_digest(f"{name}:repair-config".encode()).removeprefix("sha256:")
    repair_workspace = graph.workspace.resolve()
    repair_profile = SimpleNamespace(
        rollout_token_limit=256,
        limits=InvocationLimits(
            timeout_seconds=5,
            interrupt_grace_seconds=0.1,
            kill_grace_seconds=0.1,
        ),
        lineage_id=f"repair-lineage-{name}",
        workspace=repair_workspace,
        profile_hash=profile_hash,
        codex_config_sha256=config_hash,
    )
    repair_session = SimpleNamespace(
        lineage_id=repair_profile.lineage_id,
        workspace=repair_workspace,
        profile_hash=profile_hash,
        codex_config_sha256=config_hash,
    )
    repair_state = SimpleNamespace(
        profile=repair_profile,
        invocation_session=repair_session,
    )
    build = BuildBundle(
        implementation_contract=store.get_json(
            graph.candidate.implementation_contract_ref,
            ImplementationContract,
        ),
        implementation_contract_ref=graph.candidate.implementation_contract_ref,
        source_snapshot_ref=graph.candidate.source_workspace_snapshot_ref,
        implementation_lineage=store.get_json(
            graph.candidate.implementation_lineage_ref,
            ImplementationLineage,
        ),
        implementation_lineage_ref=graph.candidate.implementation_lineage_ref,
        candidate_manifest=store.get_json(
            graph.candidate.candidate_manifest_ref,
            CandidateManifest,
        ),
        candidate_manifest_ref=graph.candidate.candidate_manifest_ref,
        build_record=store.get_json(graph.candidate.build_artifact_ref, BuildRecord),
        build_artifact_ref=graph.candidate.build_artifact_ref,
        candidate=graph.candidate,
        candidate_ref=graph.candidate_ref,
        project_root=graph.workspace,
        session=None,
        state=cast(BuilderSessionState, repair_state),
        invocation=BuildInvocationSummary(
            invocation_id=f"invocation:{name}:initial-build",
            status=InvocationStatus.COMPLETED,
            duration_ms=1,
            usage=None,
            backend_version="controller-repair-contract-test",
        ),
    )
    evidence_ref = controller.judge.artifacts.put_json(
        artifact_id=f"integration-evidence:{name}",
        artifact_type="judge.integration_contract_evidence",
        value={"status": "failed", "failure": "runtime_protocol"},
        dependencies=(build.candidate_ref,),
    )
    finding = Finding(
        finding_id=f"finding:{name}:build-repair",
        category="runtime_protocol",
        severity="high",
        owner="build",
        subject_ref=build.candidate_ref,
        summary="The runtime protocol requires a same-session Builder repair.",
        evidence_refs=(evidence_ref,),
        fingerprint=sha256_digest(f"{name}:runtime-protocol".encode()),
        disclosure="repair",
        suggested_repair="Repair the runtime protocol implementation.",
    )
    gate = GateResult(
        gate_id="runtime_protocol",
        status="fail",
        hard=True,
        subject_ref=build.candidate_ref,
        evidence_refs=(evidence_ref,),
        duration_seconds=0.01,
        summary="Runtime protocol execution failed.",
    )
    report = IntegrationReport(
        report_id=f"integration-report:{name}",
        revision=1,
        candidate_ref=build.candidate_ref,
        status="failed",
        gate_results=(gate,),
        findings=(finding,),
        evidence_refs=(evidence_ref,),
        budget_usage=BudgetUsage(
            tool_calls=1,
            evaluation_episodes=1,
            container_seconds=1,
        ),
    )
    report_ref = controller.judge.artifacts.put_json(
        artifact_id=report.report_id,
        artifact_type="judge.integration_report",
        value=report,
        dependencies=(build.candidate_ref, graph_design.world_spec_ref, evidence_ref),
    )
    integration = IntegrationBundle(
        report=report,
        report_ref=report_ref,
        evidence_refs=(evidence_ref,),
    )
    job = controller.artifacts.get_json(discovery.run.job_ref, EnvironmentJob)
    control_budget = Budget(
        llm_tokens=1_000,
        agent_turns=3,
        tool_calls=3,
        build_seconds=20,
        evaluation_episodes=3,
        container_seconds=5,
        repair_attempts=2,
        wall_seconds=60,
        monetary_cost=2,
    )
    run = _RunState(
        run_id=f"run:{name}:builder-repair",
        job_ref=discovery.run.job_ref,
        ledger=BudgetLedger(control_budget),
    )
    run.remember(
        discovery.run.job_ref,
        graph_design.design_ref,
        graph_design.world_spec_ref,
        build.candidate_ref,
        build.candidate_manifest_ref,
    )
    return _BuilderRepairScenario(
        controller=controller,
        run=run,
        job=job,
        design=graph_design,
        build=build,
        integration=integration,
        compiled=CompiledVerifier(
            verifier=graph.verifier,
            verifier_ref=graph.verifier_ref,
            invocation_results=(),
        ),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_kind", ["cancelled", "unknown_exception"])
async def test_builder_repair_failure_terminalizes_lease_attempt_and_route(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_kind: str,
) -> None:
    scenario = _builder_repair_scenario(tmp_path, f"repair-terminal-{failure_kind}")
    controller = scenario.controller
    repair_called = False

    def required_integration_budget(**_kwargs: object) -> Budget:
        return Budget(
            tool_calls=1,
            evaluation_episodes=1,
            container_seconds=1,
            wall_seconds=10,
        )

    async def evaluate_integration(**_kwargs: object) -> IntegrationBundle:
        return scenario.integration

    async def fail_repair(**_kwargs: object) -> BuildBundle:
        nonlocal repair_called
        repair_called = True
        if failure_kind == "cancelled":
            raise asyncio.CancelledError
        raise RuntimeError("unknown Builder repair infrastructure failure")

    monkeypatch.setattr(
        controller.judge,
        "required_integration_budget",
        required_integration_budget,
    )
    monkeypatch.setattr(controller.judge, "evaluate_integration", evaluate_integration)
    monkeypatch.setattr(controller.builder, "repair", fail_repair)

    if failure_kind == "cancelled":
        with pytest.raises(asyncio.CancelledError):
            await controller._integrate_and_repair(  # noqa: SLF001
                run=scenario.run,
                job=scenario.job,
                design=scenario.design,
                build=scenario.build,
            )
    else:
        with pytest.raises(
            _GenerationHalt,
            match="Integration-directed Builder repair did not complete",
        ) as captured:
            await controller._integrate_and_repair(  # noqa: SLF001
                run=scenario.run,
                job=scenario.job,
                design=scenario.design,
                build=scenario.build,
            )
        assert captured.value.code == "integration_builder_repair_infrastructure_error"

    assert repair_called
    repair_attempt = next(attempt for attempt in scenario.run.attempts if attempt.node == "build")
    assert repair_attempt.status == "failed"
    assert repair_attempt.finished_at is not None
    terminal_lease_refs = tuple(
        ref for ref in scenario.run.latest.values() if ref.artifact_type == "control.budget_lease"
    )
    repair_lease_ref, repair_lease = next(
        (ref, controller.artifacts.get_json(ref, BudgetLease))
        for ref in terminal_lease_refs
        if controller.artifacts.get_json(ref, BudgetLease).owner_id == repair_attempt.attempt_id
    )
    expected_unknown = BudgetUsage(
        llm_tokens=repair_lease.reserved.llm_tokens,
        agent_turns=repair_lease.reserved.agent_turns,
        build_seconds=repair_lease.reserved.build_seconds,
        monetary_cost=repair_lease.reserved.monetary_cost,
    )
    assert repair_lease.reserved.llm_tokens == 256
    assert repair_lease.reserved.agent_turns == 1
    assert repair_lease.reserved.build_seconds == pytest.approx(5.8)
    assert repair_lease.reserved.wall_seconds == pytest.approx(5.8)
    assert repair_lease.reserved.monetary_cost == pytest.approx(2 * 256 / 1_000)
    assert repair_attempt.budget_usage == expected_unknown.model_copy(update={"repair_attempts": 1})
    assert repair_lease.status == "settled"
    assert repair_lease.observed_actual == BudgetUsage()
    assert repair_lease.unknown_upper_bound == expected_unknown
    assert repair_lease.conservative_committed == expected_unknown
    lease_history_refs = controller.artifacts.list_revisions(repair_lease_ref.artifact_id)
    lease_history = tuple(
        controller.artifacts.get_json(ref, BudgetLease) for ref in lease_history_refs
    )
    assert {lease.status for lease in lease_history} == {"active", "settled"}
    active_ref = next(
        ref
        for ref, lease in zip(lease_history_refs, lease_history, strict=True)
        if lease.status == "active"
    )
    assert active_ref in controller.artifacts.dependencies(repair_lease_ref)
    assert scenario.run.ledger.unknown_upper_bound == expected_unknown
    assert all(attempt.status != "running" for attempt in scenario.run.attempts)
    assert scenario.run.repair_ledger.entries
    assert all(entry.outcome != "authorized" for entry in scenario.run.repair_ledger.entries)
    assert scenario.run.repair_ledger.entries[-1].outcome == "escalated"


@pytest.mark.asyncio
async def test_integration_repair_requirement_failure_terminalizes_route_without_work(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario = _builder_repair_scenario(tmp_path, "repair-requirement-failure")
    controller = scenario.controller

    def required_integration_budget(**_kwargs: object) -> Budget:
        return Budget(
            tool_calls=1,
            evaluation_episodes=1,
            container_seconds=1,
            wall_seconds=10,
        )

    async def evaluate_integration(**_kwargs: object) -> IntegrationBundle:
        return scenario.integration

    def fail_repair_requirements(_state: BuilderSessionState) -> tuple[int, float]:
        raise OSError("repair workspace identity cannot be resolved")

    async def forbidden_repair(**_kwargs: object) -> BuildBundle:
        raise AssertionError("planning failure must not enter Builder repair")

    monkeypatch.setattr(
        controller.judge,
        "required_integration_budget",
        required_integration_budget,
    )
    monkeypatch.setattr(controller.judge, "evaluate_integration", evaluate_integration)
    monkeypatch.setattr(
        controller.builder,
        "repair_turn_requirements",
        fail_repair_requirements,
    )
    monkeypatch.setattr(controller.builder, "repair", forbidden_repair)

    with pytest.raises(_GenerationHalt) as captured:
        await controller._integrate_and_repair(  # noqa: SLF001
            run=scenario.run,
            job=scenario.job,
            design=scenario.design,
            build=scenario.build,
        )

    assert captured.value.code == "integration_builder_repair_profile_invalid"
    assert all(attempt.node != "build" for attempt in scenario.run.attempts)
    assert scenario.run.ledger.observed_actual.repair_attempts == 0
    assert scenario.run.ledger.unknown_upper_bound.repair_attempts == 0
    assert not any(
        ref.artifact_type == "control.budget_lease"
        and controller.artifacts.get_json(ref, BudgetLease).owner_id.startswith("attempt:build")
        for ref in scenario.run.latest.values()
    )
    assert scenario.run.repair_ledger.entries
    assert all(entry.outcome != "authorized" for entry in scenario.run.repair_ledger.entries)
    assert scenario.run.repair_ledger.entries[-1].outcome == "escalated"


@pytest.mark.asyncio
async def test_integration_repair_attempt_telemetry_failure_is_atomic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario = _builder_repair_scenario(tmp_path, "repair-attempt-telemetry-failure")
    controller = scenario.controller
    telemetry = TelemetryStore(tmp_path / "repair-attempt-telemetry")

    def required_integration_budget(**_kwargs: object) -> Budget:
        return Budget(
            tool_calls=1,
            evaluation_episodes=1,
            container_seconds=1,
            wall_seconds=10,
        )

    def fail_start_span(**kwargs: object) -> None:
        assert kwargs["node"] == "build"
        raise RuntimeError("telemetry storage unavailable")

    async def evaluate_integration(**_kwargs: object) -> IntegrationBundle:
        controller.telemetry = telemetry
        return scenario.integration

    async def forbidden_repair(**_kwargs: object) -> BuildBundle:
        raise AssertionError("attempt registration failure must not enter Builder repair")

    monkeypatch.setattr(
        controller.judge,
        "required_integration_budget",
        required_integration_budget,
    )
    monkeypatch.setattr(controller.judge, "evaluate_integration", evaluate_integration)
    monkeypatch.setattr(controller.builder, "repair", forbidden_repair)
    monkeypatch.setattr(telemetry, "start_span", fail_start_span)

    try:
        with pytest.raises(_GenerationHalt) as captured:
            await controller._integrate_and_repair(  # noqa: SLF001
                run=scenario.run,
                job=scenario.job,
                design=scenario.design,
                build=scenario.build,
            )
    finally:
        telemetry.close()

    assert captured.value.code == "integration_builder_repair_attempt_start_failed"
    assert all(attempt.node != "build" for attempt in scenario.run.attempts)
    assert all(attempt.status != "running" for attempt in scenario.run.attempts)
    assert scenario.run.ledger.observed_actual.repair_attempts == 0
    assert scenario.run.ledger.unknown_upper_bound.repair_attempts == 0
    assert not any(
        ref.artifact_type == "control.budget_lease"
        and controller.artifacts.get_json(ref, BudgetLease).owner_id.startswith("attempt:build")
        for ref in scenario.run.latest.values()
    )
    assert scenario.run.repair_ledger.entries
    assert all(entry.outcome != "authorized" for entry in scenario.run.repair_ledger.entries)
    assert scenario.run.repair_ledger.entries[-1].outcome == "escalated"


@pytest.mark.asyncio
async def test_judge_builder_repair_unknown_failure_terminalizes_control_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario = _builder_repair_scenario(tmp_path, "judge-repair-terminal")
    controller = scenario.controller
    evidence_ref = controller.judge.artifacts.put_json(
        artifact_id="judge-repair-terminal:evidence",
        artifact_type="judge.evaluation_evidence",
        value={"status": "failed", "failure": "runtime_protocol"},
        dependencies=(scenario.build.candidate_ref,),
    )
    finding = scenario.integration.report.findings[0].model_copy(
        update={
            "finding_id": "finding:judge-repair-terminal",
            "evidence_refs": (evidence_ref,),
            "fingerprint": sha256_digest(b"judge-repair-terminal"),
        }
    )
    gate = scenario.integration.report.gate_results[0].model_copy(
        update={"evidence_refs": (evidence_ref,)}
    )
    report = JudgeReport(
        report_id="judge-report:repair-terminal",
        revision=1,
        candidate_ref=scenario.build.candidate_ref,
        verdict="fail",
        gate_results=(gate,),
        findings=(finding,),
        evaluation_evidence_refs=(evidence_ref,),
        budget_usage=BudgetUsage(
            tool_calls=1,
            evaluation_episodes=1,
            container_seconds=1,
        ),
    )
    report_ref = controller.judge.artifacts.put_json(
        artifact_id=report.report_id,
        artifact_type="judge_report",
        value=report,
        dependencies=(
            scenario.build.candidate_ref,
            scenario.design.world_spec_ref,
            scenario.compiled.verifier_ref,
            evidence_ref,
        ),
    )
    judge_bundle = JudgeBundle(
        report=report,
        report_ref=report_ref,
        evidence_refs=(evidence_ref,),
    )
    repair_called = False

    def required_evaluation_budget(**_kwargs: object) -> Budget:
        return Budget(
            tool_calls=1,
            evaluation_episodes=1,
            container_seconds=1,
            wall_seconds=10,
        )

    async def evaluate(**_kwargs: object) -> JudgeBundle:
        return judge_bundle

    async def fail_repair(**_kwargs: object) -> BuildBundle:
        nonlocal repair_called
        repair_called = True
        raise RuntimeError("unknown Builder repair infrastructure failure")

    monkeypatch.setattr(
        controller.judge,
        "required_evaluation_budget",
        required_evaluation_budget,
    )
    monkeypatch.setattr(controller.judge, "evaluate", evaluate)
    monkeypatch.setattr(controller.builder, "repair", fail_repair)

    with pytest.raises(_GenerationHalt) as captured:
        await controller._judge_and_repair(  # noqa: SLF001
            run=scenario.run,
            job=scenario.job,
            design=scenario.design,
            compiled=scenario.compiled,
            build=scenario.build,
        )

    assert captured.value.code == "builder_repair_infrastructure_error"
    assert repair_called
    repair_attempt = next(attempt for attempt in scenario.run.attempts if attempt.node == "build")
    assert repair_attempt.status == "failed"
    assert repair_attempt.finished_at is not None
    repair_lease_ref, repair_lease = next(
        (ref, controller.artifacts.get_json(ref, BudgetLease))
        for ref in scenario.run.latest.values()
        if ref.artifact_type == "control.budget_lease"
        and controller.artifacts.get_json(ref, BudgetLease).owner_id == repair_attempt.attempt_id
    )
    expected_unknown = BudgetUsage(
        llm_tokens=repair_lease.reserved.llm_tokens,
        agent_turns=repair_lease.reserved.agent_turns,
        build_seconds=repair_lease.reserved.build_seconds,
        monetary_cost=repair_lease.reserved.monetary_cost,
    )
    assert repair_attempt.budget_usage == expected_unknown.model_copy(update={"repair_attempts": 1})
    assert repair_lease.status == "settled"
    assert repair_lease.observed_actual == BudgetUsage()
    assert repair_lease.unknown_upper_bound == expected_unknown
    assert repair_lease.conservative_committed == expected_unknown
    assert {
        controller.artifacts.get_json(ref, BudgetLease).status
        for ref in controller.artifacts.list_revisions(repair_lease_ref.artifact_id)
    } == {"active", "settled"}
    assert scenario.run.ledger.unknown_upper_bound == expected_unknown
    assert scenario.run.ledger.observed_actual.repair_attempts == 1
    assert all(attempt.status != "running" for attempt in scenario.run.attempts)
    assert scenario.run.repair_ledger.entries
    assert all(entry.outcome != "authorized" for entry in scenario.run.repair_ledger.entries)
    assert scenario.run.repair_ledger.entries[-1].outcome == "escalated"


@pytest.mark.asyncio
async def test_recovered_build_without_state_never_starts_or_consumes_repair(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario = _builder_repair_scenario(tmp_path, "repair-no-state")
    controller = scenario.controller
    recovered_build = replace(scenario.build, state=None)

    def required_integration_budget(**_kwargs: object) -> Budget:
        return Budget(
            tool_calls=1,
            evaluation_episodes=1,
            container_seconds=1,
            wall_seconds=10,
        )

    async def evaluate_integration(**_kwargs: object) -> IntegrationBundle:
        return scenario.integration

    async def forbidden_repair(**_kwargs: object) -> BuildBundle:
        raise AssertionError("build.state=None must fail before Builder repair")

    monkeypatch.setattr(
        controller.judge,
        "required_integration_budget",
        required_integration_budget,
    )
    monkeypatch.setattr(controller.judge, "evaluate_integration", evaluate_integration)
    monkeypatch.setattr(controller.builder, "repair", forbidden_repair)

    with pytest.raises(_GenerationHalt) as captured:
        await controller._integrate_and_repair(  # noqa: SLF001
            run=scenario.run,
            job=scenario.job,
            design=scenario.design,
            build=recovered_build,
        )

    assert captured.value.code == "recovered_build_requires_fresh_codegen"
    assert all(attempt.node != "build" for attempt in scenario.run.attempts)
    assert scenario.run.ledger.observed_actual.repair_attempts == 0
    assert scenario.run.ledger.unknown_upper_bound.repair_attempts == 0
    repair_leases = tuple(
        controller.artifacts.get_json(ref, BudgetLease)
        for ref in scenario.run.latest.values()
        if ref.artifact_type == "control.budget_lease"
        and controller.artifacts.get_json(ref, BudgetLease).owner_id.startswith("attempt:build")
    )
    assert repair_leases == ()
    assert scenario.run.repair_ledger.entries
    assert all(entry.outcome != "authorized" for entry in scenario.run.repair_ledger.entries)
    assert scenario.run.repair_ledger.entries[-1].outcome == "escalated"


def _discovery_lane(
    scenario: _DiscoveryScenario,
    task: asyncio.Task[DiscoveryBundle],
) -> _DiscoveryLane:
    return _DiscoveryLane(
        spec=scenario.spec,
        spec_ref=scenario.spec_ref,
        ledger=BudgetLedger(scenario.discovery_budget),
        task=task,
        state_ref=scenario.state_ref,
        invocation_budget=scenario.invocation_budget,
        started_monotonic=time.monotonic(),
    )


def test_structured_repair_keeps_stable_family_while_issue_set_shrinks(
    tmp_path: Path,
) -> None:
    async def exercise() -> None:
        scenario = _discovery_scenario(tmp_path, "structured-repair-family")
        controller = scenario.controller
        run = scenario.run
        initial_issues = tuple(
            f"evidence_reference_unknown@claims.claim:{index}.evidence_ids.0" for index in range(16)
        )
        remaining_issues = initial_issues[-2:]

        first_id = await controller._authorize_structured_repair(  # noqa: SLF001
            run,
            owner_node="design",
            lineage_id="job:hotel.evidence-synthesis",
            role="researcher",
            repair_mode=StructuredRepairMode.CONTRACT_CORRECTION,
            issue_codes=initial_issues,
            continued_session=True,
        )
        await controller._complete_structured_repair(  # noqa: SLF001
            run,
            first_id,
            remaining_issue_codes=remaining_issues,
            continued_session=True,
        )
        second_id = await controller._authorize_structured_repair(  # noqa: SLF001
            run,
            owner_node="design",
            lineage_id="job:hotel.evidence-synthesis",
            role="researcher",
            repair_mode=StructuredRepairMode.CONTRACT_CORRECTION,
            issue_codes=remaining_issues,
            continued_session=True,
        )

        entries = tuple(
            entry for entry in run.repair_ledger.entries if entry.entry_id in {first_id, second_id}
        )
        assert [entry.attempt_ordinal for entry in entries] == [1, 2]
        assert entries[0].finding_fingerprint == entries[1].finding_fingerprint
        assert entries[0].outcome == "progressed"
        assert entries[1].outcome == "authorized"

    asyncio.run(exercise())


def test_controller_treats_exact_issue_change_as_bounded_progress(tmp_path: Path) -> None:
    async def exercise() -> None:
        scenario = _discovery_scenario(tmp_path, "structured-repair-issue-change")
        controller = scenario.controller
        run = scenario.run
        first_id = await controller._authorize_structured_repair(  # noqa: SLF001
            run,
            owner_node="design",
            lineage_id="job:hotel.assumption-closure",
            role="researcher",
            repair_mode=StructuredRepairMode.CONTRACT_CORRECTION,
            issue_codes=("schema_assumption_fidelity_claim_missing@resolutions.0",),
            continued_session=True,
        )

        await controller._complete_structured_repair(  # noqa: SLF001
            run,
            first_id,
            remaining_issue_codes=(
                "assumption_fidelity_unknown_claim@resolutions.0.fidelity.evidence_claim_ids",
            ),
            continued_session=True,
        )
        first = next(item for item in run.repair_ledger.entries if item.entry_id == first_id)
        assert first.outcome == "progressed"
        assert first.progress_evidence == "issue_set_changed"

        second_id = await controller._authorize_structured_repair(  # noqa: SLF001
            run,
            owner_node="design",
            lineage_id="job:hotel.assumption-closure",
            role="researcher",
            repair_mode=StructuredRepairMode.CONTRACT_CORRECTION,
            issue_codes=(
                "assumption_fidelity_unknown_claim@resolutions.0.fidelity.evidence_claim_ids",
            ),
            continued_session=True,
        )
        second = next(item for item in run.repair_ledger.entries if item.entry_id == second_id)
        assert second.outcome == "authorized"
        assert second.attempt_ordinal == 2

    asyncio.run(exercise())


def test_authority_backed_designer_repair_is_globally_charged_once(tmp_path: Path) -> None:
    scenario = _discovery_scenario(tmp_path, "designer-repair-single-charge")
    controller = scenario.controller
    run = scenario.run
    work = controller._reserve_designer_work(  # noqa: SLF001
        run,
        purpose="authority-backed-designer-test",
        base_turns=1,
        maximum_corrections=1,
        controller_owns_structured_repairs=True,
    )
    # This is the single global charge owned by Controller/RepairLedger.
    run.ledger.consume(BudgetUsage(repair_attempts=1))
    error = DesignerError(
        "agent.environment-engineer.output",
        "typed validation did not converge",
        budget_usage=BudgetUsage(llm_tokens=25, agent_turns=2, repair_attempts=1),
        budget_observed_actual=BudgetUsage(
            llm_tokens=25,
            agent_turns=2,
            repair_attempts=1,
        ),
        budget_unknown_upper_bound=BudgetUsage(),
    )

    attempt_usage = controller._settle_designer_error(  # noqa: SLF001
        run,
        work,
        error,
    )

    assert attempt_usage == error.budget_usage
    assert attempt_usage.repair_attempts == 1
    assert run.ledger.observed_actual.repair_attempts == 1
    assert work.terminal_lease is not None
    assert work.terminal_lease.observed_actual == BudgetUsage(
        llm_tokens=25,
        agent_turns=2,
    )
    assert work.terminal_lease.unknown_upper_bound == BudgetUsage()


def test_unmanaged_designer_meter_retains_its_repair_charge(tmp_path: Path) -> None:
    scenario = _discovery_scenario(tmp_path, "designer-repair-meter-owned")
    controller = scenario.controller
    run = scenario.run
    work = controller._reserve_designer_work(  # noqa: SLF001
        run,
        purpose="meter-owned-designer-test",
        base_turns=1,
        maximum_corrections=1,
    )

    controller._settle_designer_work(  # noqa: SLF001
        run,
        work,
        BudgetUsage(llm_tokens=25, agent_turns=2, repair_attempts=1),
    )

    assert run.ledger.observed_actual.repair_attempts == 1
    assert work.terminal_lease is not None
    assert work.terminal_lease.observed_actual.repair_attempts == 1


def test_discovery_cutoff_never_waits_for_cancel_resistant_research(tmp_path: Path) -> None:
    async def exercise() -> None:
        scenario = _discovery_scenario(tmp_path, "slow-discover")

        async def slow_discover() -> DiscoveryBundle:
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                await asyncio.sleep(0.3)
            return scenario.bundle

        task = asyncio.create_task(slow_discover())
        await asyncio.sleep(0)
        lane = _discovery_lane(scenario, task)
        started = time.monotonic()
        scenario.controller._freeze_discovery_for_release(  # noqa: SLF001
            scenario.run,
            lane,
            scenario.design,
        )
        assert time.monotonic() - started < 0.2
        state = scenario.controller.artifacts.get_json(lane.state_ref, DiscoveryLaneState)
        assert state.status == "deferred"
        await task

    asyncio.run(exercise())


def test_discovery_cutoff_never_waits_for_cancel_resistant_admission(tmp_path: Path) -> None:
    async def exercise() -> None:
        scenario = _discovery_scenario(tmp_path, "slow-admit")
        staged = scenario.controller.discovery.stage_late_inbox(
            run_spec=scenario.spec,
            discovery=scenario.bundle,
            baseline_ref=scenario.design.baseline_ref,
        )

        async def slow_admission() -> AdmissionBundle:
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                await asyncio.sleep(0.3)
            return staged

        discovery_task = asyncio.create_task(asyncio.sleep(0, result=scenario.bundle))
        admission_task = asyncio.create_task(slow_admission())
        await asyncio.sleep(0)
        lane = _discovery_lane(scenario, discovery_task)
        lane.bundle = scenario.bundle
        lane.admission = staged
        lane.discovery_accounted = True
        lane.admission_task = admission_task
        lane.admission_budget = Budget(llm_tokens=1_000, agent_turns=1, wall_seconds=10)
        started = time.monotonic()
        scenario.controller._freeze_discovery_for_release(  # noqa: SLF001
            scenario.run,
            lane,
            scenario.design,
        )
        assert time.monotonic() - started < 0.2
        state = scenario.controller.artifacts.get_json(lane.state_ref, DiscoveryLaneState)
        assert state.status == "deferred"
        assert state.inbox_ref == staged.inbox_ref
        await admission_task

    asyncio.run(exercise())


def test_completed_late_critical_risk_clue_is_persisted_in_inbox(tmp_path: Path) -> None:
    async def exercise() -> None:
        scenario = _discovery_scenario(tmp_path, "late-critical")
        task = asyncio.create_task(asyncio.sleep(0, result=scenario.bundle))
        await task
        lane = _discovery_lane(scenario, task)
        scenario.controller._freeze_discovery_for_release(  # noqa: SLF001
            scenario.run,
            lane,
            scenario.design,
        )
        state = scenario.controller.artifacts.get_json(lane.state_ref, DiscoveryLaneState)
        assert state.status == "deferred"
        assert state.inbox_ref is not None
        inbox = scenario.controller.artifacts.get_json(
            state.inbox_ref,
            ExpansionInboxSnapshot,
        )
        assert inbox.clue_refs == scenario.bundle.clue_refs

    asyncio.run(exercise())


def test_discovery_exception_is_terminal_lane_data_not_direct_exception(tmp_path: Path) -> None:
    async def exercise() -> None:
        scenario = _discovery_scenario(tmp_path, "discover-error")

        async def broken_discover() -> DiscoveryBundle:
            raise RuntimeError("isolated discovery failure")

        task = asyncio.create_task(broken_discover())
        await asyncio.sleep(0)
        lane = _discovery_lane(scenario, task)
        scenario.controller._freeze_discovery_for_release(  # noqa: SLF001
            scenario.run,
            lane,
            scenario.design,
        )
        state = scenario.controller.artifacts.get_json(lane.state_ref, DiscoveryLaneState)
        assert state.status == "failed"
        assert state.failure_code == "discovery_runtimeerror"

    asyncio.run(exercise())


def test_discovery_research_failure_accounts_observed_work_and_preserves_code(
    tmp_path: Path,
) -> None:
    async def exercise() -> None:
        scenario = _discovery_scenario(tmp_path, "discover-research-error")
        error = DesignerError(
            "discovery.research.fetch",
            "safe aggregate",
            budget_usage=BudgetUsage(llm_tokens=40, agent_turns=1),
            budget_observed_actual=BudgetUsage(llm_tokens=10, agent_turns=1),
            budget_unknown_upper_bound=BudgetUsage(llm_tokens=30),
            research_usage=BudgetUsage(search_calls=1, tool_calls=3),
            failure_code="research_infrastructure_upstream_unavailable",
            infrastructure_error=True,
        )

        async def broken_discover() -> DiscoveryBundle:
            raise error

        task = asyncio.create_task(broken_discover())
        await asyncio.sleep(0)
        lane = _discovery_lane(scenario, task)
        scenario.controller._freeze_discovery_for_release(  # noqa: SLF001
            scenario.run,
            lane,
            scenario.design,
        )
        state = scenario.controller.artifacts.get_json(lane.state_ref, DiscoveryLaneState)
        assert state.status == "failed"
        assert state.failure_code == (
            "discovery_research_infrastructure_upstream_unavailable"
        )
        assert state.used_budget == BudgetUsage(
            llm_tokens=40,
            agent_turns=1,
            search_calls=1,
            tool_calls=3,
        )
        assert lane.ledger.observed_actual == BudgetUsage(
            llm_tokens=10,
            agent_turns=1,
            search_calls=1,
            tool_calls=3,
        )
        assert lane.ledger.unknown_upper_bound == BudgetUsage(llm_tokens=30)

        scenario.controller._fail_discovery_lane(  # noqa: SLF001
            scenario.run,
            lane,
            error,
        )
        assert lane.ledger.observed_actual == BudgetUsage(
            llm_tokens=10,
            agent_turns=1,
            search_calls=1,
            tool_calls=3,
        )
        assert lane.ledger.unknown_upper_bound == BudgetUsage(llm_tokens=30)

    asyncio.run(exercise())


def test_research_budget_failure_keeps_budget_terminal_status() -> None:
    status, code = FoundryController._designer_failure_status(  # noqa: SLF001
        DesignerError(
            "research.fetch",
            "safe aggregate",
            budget_exhausted=True,
            failure_code="research_budget_exhausted",
        ),
        default_code="design_research_fetch",
    )

    assert status == "budget_exhausted"
    assert code == "research_budget_exhausted"


def test_unverified_discovery_recommendation_is_dismissed_without_control_authority(
    tmp_path: Path,
) -> None:
    async def exercise() -> None:
        scenario = _discovery_scenario(tmp_path, "hard-correction")
        staged = scenario.controller.discovery.stage_late_inbox(
            run_spec=scenario.spec,
            discovery=scenario.bundle,
            baseline_ref=scenario.design.baseline_ref,
        )
        decision = DiscoveryAdmissionDecision(
            decision_id="decision:hard-correction",
            clue_ref=scenario.bundle.clue_refs[0],
            classification="hard_correction",
            destination="quarantine_recommendation",
            rationale="New evidence challenges a supported hard claim.",
            decided_against_baseline_ref=scenario.design.baseline_ref,
            challenged_claim_ids=("claim:hard-correction",),
        )
        decision_ref = scenario.controller.discovery.artifacts.put_json(
            artifact_id="decision:hard-correction",
            artifact_type="discovery.admission_decision",
            value=decision,
            dependencies=(scenario.bundle.clue_refs[0], scenario.design.baseline_ref),
        )
        recommendation = DiscoveryQuarantineRecommendation(
            recommendation_id="recommendation:hard-correction",
            clue_ref=scenario.bundle.clue_refs[0],
            world_spec_ref=scenario.design.world_spec_ref,
            challenged_claim_ids=("claim:hard-correction",),
            evidence_refs=scenario.bundle.clues[0].evidence_refs,
            risk="high",
            rationale="New evidence challenges a supported hard claim.",
        )
        recommendation_ref = scenario.controller.discovery.artifacts.put_json(
            artifact_id="recommendation:hard-correction",
            artifact_type="discovery.quarantine_recommendation",
            value=recommendation,
            dependencies=(decision_ref, *recommendation.evidence_refs),
        )
        admission = AdmissionBundle(
            decisions=(decision,),
            decision_refs=(decision_ref,),
            recommendation_refs=(recommendation_ref,),
            inbox=staged.inbox,
            inbox_ref=staged.inbox_ref,
            invocation_usage=BudgetUsage(),
            invocation_results=(),
        )
        discovery_task = asyncio.create_task(asyncio.sleep(0, result=scenario.bundle))
        admission_task = asyncio.create_task(asyncio.sleep(0, result=admission))
        await asyncio.gather(discovery_task, admission_task)
        lane = _discovery_lane(scenario, discovery_task)
        lane.bundle = scenario.bundle
        lane.admission = staged
        lane.discovery_accounted = True
        lane.admission_task = admission_task
        scenario.controller._freeze_discovery_for_release(  # noqa: SLF001
            scenario.run,
            lane,
            scenario.design,
        )
        state = scenario.controller.artifacts.get_json(lane.state_ref, DiscoveryLaneState)
        assert state.status == "quarantine_dismissed"
        assert state.recommendation_refs == (recommendation_ref,)
        assert len(state.quarantine_review_refs) == 1
        review = scenario.controller.artifacts.get_json(state.quarantine_review_refs[0])
        assert review["outcome"] == "dismissed"
        assert review["reason_code"] == "evidence_not_independently_retrieved"
        assert state.finding_refs == ()
        assert scenario.run.findings == {}
        assert scenario.controller.registry.list() == ()

    asyncio.run(exercise())


def test_provenance_checked_discovery_recommendation_becomes_framework_finding(
    tmp_path: Path,
) -> None:
    async def exercise() -> None:
        scenario = _discovery_scenario(tmp_path, "confirmed-hard-correction")
        body = b"The retrieved workflow contradicts the supported baseline claim."
        content_ref = scenario.controller.designer.research_artifacts.put_blob(
            artifact_id="evidence:confirmed-hard-correction:content",
            artifact_type="evidence.extracted_content",
            content=body,
            media_type="text/plain",
        )
        content_hash = sha256_digest(body)
        new_evidence = Evidence(
            evidence_id="evidence:confirmed-hard-correction:new",
            source_kind="web",
            source_uri="https://example.invalid/new-workflow-evidence",
            retrieved_at=datetime.now(UTC),
            retrieval_status="success",
            raw_content_hash=content_hash,
            content_hash=content_hash,
            fetcher="test-fetcher",
            fetcher_version="1",
            extractor="test-extractor",
            extractor_version="1",
            observed_summary="New retrieved evidence contradicts a supported baseline claim.",
            content_ref=content_ref,
        )
        clue = scenario.bundle.clues[0].model_copy(
            update={"evidence_refs": (content_ref,)}
        )
        clue_ref = scenario.controller.discovery.artifacts.put_json(
            artifact_id="clue:confirmed-hard-correction:retrieved",
            artifact_type="discovery.expansion_clue",
            value=clue,
            dependencies=(scenario.spec_ref, content_ref),
        )
        bundle = replace(
            scenario.bundle,
            clues=(clue,),
            clue_refs=(clue_ref,),
            evidence=(new_evidence,),
        )
        staged = scenario.controller.discovery.stage_late_inbox(
            run_spec=scenario.spec,
            discovery=bundle,
            baseline_ref=scenario.design.baseline_ref,
        )
        decision = DiscoveryAdmissionDecision(
            decision_id="decision:confirmed-hard-correction",
            clue_ref=clue_ref,
            classification="hard_correction",
            destination="quarantine_recommendation",
            rationale="New evidence challenges a supported hard claim.",
            decided_against_baseline_ref=scenario.design.baseline_ref,
            challenged_claim_ids=("claim:confirmed-hard-correction",),
        )
        decision_ref = scenario.controller.discovery.artifacts.put_json(
            artifact_id="decision:confirmed-hard-correction",
            artifact_type="discovery.admission_decision",
            value=decision,
            dependencies=(clue_ref, scenario.design.baseline_ref),
        )
        recommendation = DiscoveryQuarantineRecommendation(
            recommendation_id="recommendation:confirmed-hard-correction",
            clue_ref=clue_ref,
            world_spec_ref=scenario.design.world_spec_ref,
            challenged_claim_ids=("claim:confirmed-hard-correction",),
            evidence_refs=(content_ref,),
            risk="high",
            rationale="New evidence challenges a supported hard claim.",
        )
        recommendation_ref = scenario.controller.discovery.artifacts.put_json(
            artifact_id="recommendation:confirmed-hard-correction",
            artifact_type="discovery.quarantine_recommendation",
            value=recommendation,
            dependencies=(decision_ref, content_ref),
        )
        admission = AdmissionBundle(
            decisions=(decision,),
            decision_refs=(decision_ref,),
            recommendation_refs=(recommendation_ref,),
            inbox=staged.inbox,
            inbox_ref=staged.inbox_ref,
            invocation_usage=BudgetUsage(),
            invocation_results=(),
        )
        discovery_task = asyncio.create_task(asyncio.sleep(0, result=bundle))
        admission_task = asyncio.create_task(asyncio.sleep(0, result=admission))
        await asyncio.gather(discovery_task, admission_task)
        lane = _discovery_lane(scenario, discovery_task)
        lane.bundle = bundle
        lane.admission = staged
        lane.discovery_accounted = True
        lane.admission_task = admission_task

        with pytest.raises(_DesignReworkRequired) as captured:
            scenario.controller._freeze_discovery_for_release(  # noqa: SLF001
                scenario.run,
                lane,
                scenario.design,
            )

        state = scenario.controller.artifacts.get_json(lane.state_ref, DiscoveryLaneState)
        assert state.status == "quarantine_confirmed"
        assert len(state.quarantine_review_refs) == 1
        assert len(state.finding_refs) == 1
        review = scenario.controller.artifacts.get_json(state.quarantine_review_refs[0])
        assert review["outcome"] == "confirmed"
        assert review["reason_code"] == "verified_hard_correction"
        assert (
            scenario.controller.artifacts.get_revision(state.quarantine_review_refs[0]).producer
            == "framework"
        )
        finding_ref = state.finding_refs[0]
        finding = scenario.controller.artifacts.get_json(finding_ref, Finding)
        assert finding.owner == "design"
        assert finding.subject_ref == scenario.design.world_spec_ref
        assert scenario.controller.artifacts.get_revision(finding_ref).producer == "framework"
        correction = captured.value
        assert correction.finding_refs == (finding_ref,)
        assert correction.additional_evidence == (new_evidence,)

        router = RepairRouter(
            maximum_attempts=3,
            artifact_store=scenario.controller.artifacts,
        )
        routes = router.route_many(
            tuple(zip(correction.findings, correction.finding_refs, strict=True)),
            current_node="discovery",
            ledger=scenario.run.repair_ledger,
        )
        assert len(routes) == 1
        assert routes[0].owner_node == "design"
        assert routes[0].action == "new_revision"
        assert routes[0].jump_distance == 1

    asyncio.run(exercise())


def test_discovery_resume_reuses_persisted_clues_without_research(tmp_path: Path) -> None:
    async def exercise() -> None:
        scenario = _discovery_scenario(tmp_path, "resume-staged")
        staged = scenario.controller.discovery.stage_late_inbox(
            run_spec=scenario.spec,
            discovery=scenario.bundle,
            baseline_ref=None,
        )
        state_ref = scenario.controller._persist_discovery_state(  # noqa: SLF001
            spec_ref=scenario.spec_ref,
            state=DiscoveryLaneState(
                discovery_run_ref=scenario.spec_ref,
                status="deferred",
                reserved_budget=scenario.discovery_budget,
                used_budget=BudgetUsage(llm_tokens=100, agent_turns=1),
                clue_refs=scenario.bundle.clue_refs,
                admission_decision_refs=staged.decision_refs,
                inbox_ref=staged.inbox_ref,
            ),
            previous_ref=scenario.state_ref,
            extra_dependencies=(
                *scenario.bundle.clue_refs,
                *staged.decision_refs,
                staged.inbox_ref,
            ),
        )
        assert state_ref != scenario.state_ref
        result = await scenario.controller.resume_discovery(
            scenario.spec.discovery_run_id,
            budget=scenario.discovery_budget,
        )
        assert result.status == "admitted"
        assert result.inbox_ref is not None
        resumed = scenario.controller.artifacts.get_json(
            result.state_ref,
            DiscoveryLaneState,
        )
        assert resumed.clue_refs == scenario.bundle.clue_refs
        assert resumed.used_budget.search_calls == 0

    asyncio.run(exercise())


def test_discovery_resume_settles_unknown_active_work_before_new_revision(
    tmp_path: Path,
) -> None:
    scenario = _discovery_scenario(tmp_path, "resume-unknown")
    running = scenario.controller.artifacts.get_json(
        scenario.state_ref,
        DiscoveryLaneState,
    )

    deferred_ref, deferred = scenario.controller._settle_unknown_discovery_state(  # noqa: SLF001
        spec_ref=scenario.spec_ref,
        state_ref=scenario.state_ref,
        state=running,
    )

    assert deferred.status == "deferred"
    assert deferred.used_budget.llm_tokens == scenario.discovery_budget.llm_tokens
    assert deferred.used_budget.agent_turns == scenario.discovery_budget.agent_turns
    assert deferred.used_budget.search_calls == scenario.discovery_budget.search_calls
    assert deferred.used_budget.tool_calls == scenario.discovery_budget.tool_calls
    assert scenario.state_ref in scenario.controller.artifacts.dependencies(deferred_ref)
