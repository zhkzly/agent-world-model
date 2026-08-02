"""Physical Scheduler leaf tests; these execute an isolated Candidate process."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest
from v3_fixture import build_judge_candidate_graph, builder_writer, judge_writer

from agent_world.artifact_store import ArtifactStore
from agent_world.builder import EnvironmentBuilder
from agent_world.contracts import Budget
from agent_world.control import (
    GenerationWorkGraph,
    LeaseBudgetLedger,
    OperationBudget,
    SchedulerLeafExecutor,
    WorkControlRuntime,
    WorkControlStore,
    WorkScheduler,
    deterministic_boundary_work_definition,
)
from agent_world.control.work import ValidationReport, WorkAttempt
from agent_world.judge import CleanCandidateBuilder, EnvironmentJudge, IntegrationLeaf


async def _real_host_execution(purpose: str):
    from agent_world.judge import HostExecutionPolicy, HostExecutionUnavailable

    isolation = HostExecutionPolicy(purpose=cast("object", purpose))  # type: ignore[arg-type]
    try:
        await isolation.ensure_available()
    except HostExecutionUnavailable as exc:
        pytest.skip(f"real host execution unavailable: {exc.code}: {exc}")
    return isolation


@pytest.mark.asyncio
async def test_scheduler_integration_leaf_runs_real_clean_install_reset_and_step(
    tmp_path: Path,
) -> None:
    """A Scheduler WorkCommit is earned by a real local Candidate execution.

    The candidate is a prebuilt v3 fixture only so this test can isolate the
    Integration leaf.  No Judge result is faked: the leaf restores its immutable
    tar, performs the offline clean install, launches the runtime and exercises
    the materializer/reset/invoke protocol as direct host processes.
    """

    store = ArtifactStore(tmp_path / "artifacts")
    fixture = build_judge_candidate_graph(tmp_path, store)
    control_artifacts = store.issue_writer(
        producer="work-controller",
        allowed_artifact_type_prefixes=("control.",),
    )
    build = deterministic_boundary_work_definition(
        scope_id="job:physical-integration",
        component="build",
        stage="candidate_build",
        artifact_slot="environment_candidate",
        dependency_coordinates=(),
        claim_id="build.candidate.valid",
        claim="The exact prebuilt Candidate is available to the Integration leaf.",
        timing_reason="This test starts at the first physical Judge boundary.",
        effect="block_integration",
        success_maturity="candidate_built",
    )
    integration_base = deterministic_boundary_work_definition(
        scope_id="job:physical-integration",
        component="integration",
        stage="runtime_integration",
        artifact_slot="integration_report",
        dependency_coordinates=(build.coordinate,),
        claim_id="integration.runtime.executable",
        claim="Candidate clean-install and Runtime ABI execute in isolation.",
        timing_reason="Only physical execution can establish runtime readiness.",
        effect="block_release",
        success_maturity="integration_passed",
        wall_seconds=180,
    )
    integration = integration_base.model_copy(
        update={
            "proposal_policy": integration_base.proposal_policy.model_copy(
                update={
                    "operation": "integration.runtime_integration.execute",
                    "budget": OperationBudget(
                        wall_seconds=180,
                        tool_calls=64,
                        process_calls=16,
                        build_seconds=60,
                        evaluation_episodes=128,
                        container_seconds=180,
                    ),
                }
            )
        }
    )
    graph = GenerationWorkGraph.compile((build, integration), mode="diagnostic")
    context_ref = control_artifacts.put_json(
        artifact_id="physical-integration-context",
        artifact_type="control.generation_context",
        value={"kind": "physical-integration"},
    )
    manifest = graph.manifest(
        topology_id="topology:physical-integration",
        external_root_refs=(context_ref,),
    )
    manifest_ref = control_artifacts.put_json(
        artifact_id=manifest.graph_id,
        artifact_type="control.work_graph_manifest",
        value=manifest,
        dependencies=(context_ref,),
    )
    heads = WorkControlStore(tmp_path / "work-control")
    runtime = WorkControlRuntime(
        artifacts=control_artifacts,
        heads=heads,
        budget=LeaseBudgetLedger(
            Budget(
                tool_calls=128,
                process_calls=32,
                build_seconds=120,
                evaluation_episodes=256,
                container_seconds=360,
                wall_seconds=360,
            )
        ),
    )
    runtime.execute_deterministic_boundary(
        definition=build,
        input_refs=(context_ref,),
        subject_ref=fixture.candidate_ref,
        output_refs=(fixture.candidate_ref,),
    )
    scheduler = WorkScheduler(
        graph=graph,
        manifest=manifest,
        manifest_ref=manifest_ref,
        heads=heads,
        artifacts=control_artifacts,
        runtime=runtime,
    )
    # materialize_exact_candidate uses only the Artifact writer; no Agent
    # invocation/profile is touched in this physical Judge test.
    builder = EnvironmentBuilder(
        artifact_store=builder_writer(store),
        invocation_backend=cast("object", object()),  # type: ignore[arg-type]
        profile_provider=cast("object", object()),  # type: ignore[arg-type]
    )
    judge = EnvironmentJudge(
        artifact_store=judge_writer(store),
        clean_builder=CleanCandidateBuilder(
            build_execution=await _real_host_execution("build"),
            uv_path=fixture.uv_path,
            uv_cache_dir=fixture.uv_cache_dir,
            timeout_seconds=60,
        ),
        runtime_execution=await _real_host_execution("runtime"),
    )
    leaf = IntegrationLeaf(
        builder=builder,
        judge=judge,
        release_profile=fixture.release_profile,
        workspace_root=tmp_path / "judge-workspaces",
        run_id="physical-integration",
        kernel=SchedulerLeafExecutor(runtime=runtime),
    )

    async def execute(context) -> None:
        await leaf.execute(context, definition=integration)

    results = await scheduler.run_until_stalled(executors={integration.work_id: execute})

    assert len(results) == 1
    assert results[0].before_state == "ready"
    assert results[0].after_state == "committed"
    final = heads.read_head(integration.coordinate)
    assert final is not None and final.status == "committed"


@pytest.mark.asyncio
async def test_scheduler_integration_budget_preflight_gives_actionable_framework_feedback(
    tmp_path: Path,
) -> None:
    """One frozen Candidate reaches the real leaf, not a generic ValueError path."""

    store = ArtifactStore(tmp_path / "artifacts")
    fixture = build_judge_candidate_graph(tmp_path, store)
    control_artifacts = store.issue_writer(
        producer="work-controller",
        allowed_artifact_type_prefixes=("control.",),
    )
    build = deterministic_boundary_work_definition(
        scope_id="job:integration-budget-feedback",
        component="build",
        stage="candidate_build",
        artifact_slot="environment_candidate",
        dependency_coordinates=(),
        claim_id="build.candidate.valid",
        claim="The exact prebuilt Candidate is available to the Integration leaf.",
        timing_reason="This test starts at the actual Integration preflight boundary.",
        effect="block_integration",
        success_maturity="candidate_built",
    )
    integration_base = deterministic_boundary_work_definition(
        scope_id="job:integration-budget-feedback",
        component="integration",
        stage="runtime_integration",
        artifact_slot="integration_report",
        dependency_coordinates=(build.coordinate,),
        claim_id="integration.runtime.executable",
        claim="Candidate Integration must have an admissible frozen budget.",
        timing_reason="The graph must size actual materialization work before execution.",
        effect="block_release",
        success_maturity="integration_passed",
        wall_seconds=180,
    )
    integration = integration_base.model_copy(
        update={
            "proposal_policy": integration_base.proposal_policy.model_copy(
                update={
                    "operation": "integration.runtime_integration.execute",
                    "budget": OperationBudget(
                        wall_seconds=180,
                        tool_calls=64,
                        process_calls=16,
                        build_seconds=60,
                        evaluation_episodes=0,
                        container_seconds=180,
                    ),
                }
            )
        }
    )
    graph = GenerationWorkGraph.compile((build, integration), mode="diagnostic")
    context_ref = control_artifacts.put_json(
        artifact_id="integration-budget-feedback-context",
        artifact_type="control.generation_context",
        value={"kind": "integration-budget-feedback"},
    )
    manifest = graph.manifest(
        topology_id="topology:integration-budget-feedback",
        external_root_refs=(context_ref,),
    )
    manifest_ref = control_artifacts.put_json(
        artifact_id=manifest.graph_id,
        artifact_type="control.work_graph_manifest",
        value=manifest,
        dependencies=(context_ref,),
    )
    heads = WorkControlStore(tmp_path / "work-control")
    runtime = WorkControlRuntime(
        artifacts=control_artifacts,
        heads=heads,
        budget=LeaseBudgetLedger(
            Budget(
                tool_calls=128,
                process_calls=32,
                build_seconds=120,
                evaluation_episodes=256,
                container_seconds=360,
                wall_seconds=360,
            )
        ),
    )
    runtime.execute_deterministic_boundary(
        definition=build,
        input_refs=(context_ref,),
        subject_ref=fixture.candidate_ref,
        output_refs=(fixture.candidate_ref,),
    )
    scheduler = WorkScheduler(
        graph=graph,
        manifest=manifest,
        manifest_ref=manifest_ref,
        heads=heads,
        artifacts=control_artifacts,
        runtime=runtime,
    )
    builder = EnvironmentBuilder(
        artifact_store=builder_writer(store),
        invocation_backend=cast("object", object()),  # type: ignore[arg-type]
        profile_provider=cast("object", object()),  # type: ignore[arg-type]
    )
    leaf = IntegrationLeaf(
        builder=builder,
        judge=EnvironmentJudge(artifact_store=judge_writer(store)),
        release_profile=fixture.release_profile,
        workspace_root=tmp_path / "budget-feedback-workspaces",
        run_id="integration-budget-feedback",
        kernel=SchedulerLeafExecutor(runtime=runtime),
    )

    async def execute(context) -> None:
        await leaf.execute(context, definition=integration)

    results = await scheduler.run_until_stalled(executors={integration.work_id: execute})

    assert len(results) == 1
    assert results[0].after_state == "blocked"
    head = heads.read_head(integration.coordinate)
    assert head is not None and head.status == "failed"
    attempt = control_artifacts.get_json(head.attempt_ref, WorkAttempt)
    report = control_artifacts.get_json(attempt.validation_report_ref, ValidationReport)
    assert report.status == "error"
    issue = report.issues[0]
    assert issue.code == "preflight_runtime_integration_budget_insufficient"
    assert issue.retryable is False
    assert issue.expected_category == (
        "a final Integration WorkDefinition sized from its committed EnvironmentDesign"
    )
    assert issue.remediation is not None
    assert "do not regenerate or repair the Candidate" in issue.remediation
