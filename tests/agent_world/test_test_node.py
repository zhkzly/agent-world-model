"""T0 evidence for isolated, real single-node WorkGraph execution."""

from __future__ import annotations

import asyncio
import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

import agent_world.control.test_node as test_node_module
from agent_world.app import build_application
from agent_world.artifact_store import ArtifactStore
from agent_world.cli import build_parser
from agent_world.config import AgentBackendConfig, FoundryConfig, ResearchConfig
from agent_world.contracts import (
    ArtifactRef,
    Budget,
    EnvironmentJob,
    EnvironmentRequest,
    GenerationContext,
    PermissionScope,
    ReleaseProfile,
)
from agent_world.control import (
    ArtifactSlotContract,
    GenerationWorkGraph,
    LeaseBudgetLedger,
    RepairAction,
    WorkControlRuntime,
    WorkControlStore,
    WorkControlStoreError,
    WorkCoordinate,
    WorkDefinition,
    WorkGraphEpochRuntime,
    WorkGraphManifest,
    deterministic_boundary_work_definition,
    research_acquisition_work_definition,
    research_plan_work_definition,
    research_synthesis_work_definition,
    world_architecture_work_definition,
)
from agent_world.control.leaf_executor import (
    LeafExecutionFailure,
    LeafProposal,
    SchedulerLeafExecutor,
)
from agent_world.control.release_leaf import RegistryPublicationLeaf
from agent_world.control.test_node import (
    DiagnosticDescendantNodeRunner as DescendantRunner,
)
from agent_world.control.test_node import (
    DiagnosticFinalNodeRunner as FinalNodeRunner,
)
from agent_world.control.test_node import (
    DiagnosticRuntimeImplementationOverride,
    DiagnosticRuntimeProfileOverride,
)
from agent_world.control.test_node import (
    TestNodeError as NodeError,
)
from agent_world.control.test_node import (
    TestNodeExecution as NodeExecution,
)
from agent_world.control.test_node import (
    TestNodeRunner as NodeRunner,
)
from agent_world.control.work import OperationRun, WorkAttempt, WorkCommit
from agent_world.control.work_scheduler import WorkScheduler
from agent_world.observability import ObservabilityError, ObservabilityRoot


@dataclass(frozen=True, slots=True)
class _CapturedScope:
    config: FoundryConfig
    scope_id: str
    state_root: Path
    parent_coordinate: WorkCoordinate
    target_definition: WorkDefinition
    successor_definition: WorkDefinition
    source_target_attempt_ref: ArtifactRef
    source_target_output_ref: ArtifactRef


def _config(tmp_path: Path) -> FoundryConfig:
    return FoundryConfig(
        state_root=tmp_path / "captured-state",
        agent=AgentBackendConfig(
            model="test-node-structured-model",
            api_key_environment="AGENT_WORLD_TEST_NODE_KEY",
        ),
        # No research operation is dispatched in this T0 harness test.  The
        # built-in Bing route avoids adding a private endpoint/config value.
        research=ResearchConfig(provider="bing_rss", use_jina_reader_fallback=False),
    )


def _definition(
    *,
    scope_id: str,
    stage: str,
    dependencies: tuple[WorkCoordinate, ...],
) -> WorkDefinition:
    return deterministic_boundary_work_definition(
        scope_id=scope_id,
        component="design",
        stage=stage,
        artifact_slot=stage,
        dependency_coordinates=dependencies,
        claim_id=f"{stage}.passed",
        claim=f"{stage} must pass its real deterministic boundary.",
        timing_reason="The target must consume committed parent output.",
        effect="block_release",
        success_maturity=f"{stage}_passed",
    )


def _capture_scope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> _CapturedScope:
    # The only credential material is process-local and random.  Its variable
    # name is the only credential reference that reaches configuration/artifacts.
    monkeypatch.setenv("AGENT_WORLD_TEST_NODE_KEY", os.urandom(16).hex())
    config = _config(tmp_path)
    app = build_application(config)
    artifacts = app.controller.artifacts
    scope_id = "generate-job:test-node"
    budget = Budget(wall_seconds=1_000)
    permissions = PermissionScope()
    release = ReleaseProfile(profile_id="release:test-node")
    request = EnvironmentRequest(
        request_id="request:test-node",
        need="用户预订宾馆",
        permissions=permissions,
        budget=budget,
        release_profile=release,
    )
    request_ref = artifacts.put_json(
        artifact_id=request.request_id,
        artifact_type="control.environment_request",
        value=request,
    )
    job = EnvironmentJob(
        job_id=scope_id,
        kind="generate",
        request_ref=request_ref,
        permissions=permissions,
        budget=budget,
        release_profile=release,
    )
    job_ref = artifacts.put_json(
        artifact_id=job.job_id,
        artifact_type="control.environment_job",
        value=job,
        dependencies=(request_ref,),
    )
    context = GenerationContext(
        context_id="context:test-node",
        job_ref=job_ref,
        kind="generate",
        request_ref=request_ref,
        permissions=permissions,
        budget=budget,
        release_profile=release,
    )
    context_ref = artifacts.put_json(
        artifact_id=context.context_id,
        artifact_type="control.generation_context",
        value=context,
        dependencies=context.root_refs,
    )
    parent = _definition(scope_id=scope_id, stage="captured_parent", dependencies=()).model_copy(
        update={
            "output_slots": (
                ArtifactSlotContract(
                    slot_id="output:parent",
                    direction="output",
                    artifact_types=("design.test_node_parent",),
                    minimum_count=1,
                    maximum_count=1,
                    producer_component="design",
                ),
            )
        }
    )
    target = _definition(
        scope_id=scope_id,
        stage="captured_target",
        dependencies=(parent.coordinate,),
    ).model_copy(
        update={
            "input_slots": (
                ArtifactSlotContract(
                    slot_id="input:parent",
                    direction="input",
                    artifact_types=("design.test_node_parent",),
                    minimum_count=1,
                    maximum_count=1,
                    producer_component="design",
                ),
            ),
            "output_slots": (
                ArtifactSlotContract(
                    slot_id="output:target",
                    direction="output",
                    artifact_types=("design.test_node_target",),
                    minimum_count=1,
                    maximum_count=1,
                    producer_component="design",
                ),
            ),
        }
    )
    successor = _definition(
        scope_id=scope_id,
        stage="unheaded_successor",
        dependencies=(target.coordinate,),
    ).model_copy(
        update={
            "input_slots": (
                ArtifactSlotContract(
                    slot_id="input:target",
                    direction="input",
                    artifact_types=("design.test_node_target",),
                    minimum_count=1,
                    maximum_count=1,
                    producer_component="design",
                ),
            ),
            "output_slots": (
                ArtifactSlotContract(
                    slot_id="output:successor",
                    direction="output",
                    artifact_types=("design.test_node_successor",),
                    minimum_count=1,
                    maximum_count=1,
                    producer_component="design",
                ),
            ),
        }
    )
    # The target below is intentionally a small constructed boundary, but the
    # frozen graph itself must have a genuine bootstrap epoch.  Provenance
    # overlays are frozen through ``WorkGraphEpochRuntime`` in production; an
    # epoch-less hand-built manifest would exercise a different harness path.
    bootstrap_plan = research_plan_work_definition(
        scope_id=scope_id,
        agent_wall_seconds=60,
        agent_token_limit=1_000,
    )
    bootstrap_acquisition = research_acquisition_work_definition(
        scope_id=scope_id,
        dependency_coordinate=bootstrap_plan.coordinate,
        wall_seconds=60,
        maximum_search_calls=1,
        maximum_tool_calls=3,
    )
    bootstrap_synthesis = research_synthesis_work_definition(
        scope_id=scope_id,
        dependency_coordinate=bootstrap_acquisition.coordinate,
        agent_wall_seconds=60,
        agent_token_limit=1_000,
    )
    bootstrap_architecture = world_architecture_work_definition(
        scope_id=scope_id,
        dependency_coordinate=bootstrap_synthesis.coordinate,
        agent_wall_seconds=60,
        agent_token_limit=1_000,
    )
    graph = GenerationWorkGraph.compile(
        (
            bootstrap_plan,
            bootstrap_acquisition,
            bootstrap_synthesis,
            bootstrap_architecture,
            parent,
            target,
            successor,
        ),
        mode="diagnostic",
        strict_input_contracts=True,
    )
    # A frozen graph retains every executable WorkDefinition, including a
    # successor which has intentionally never been dispatched.  Runtime
    # execution would persist only parent/target definitions below; mirror the
    # production WorkGraphEpoch closure here so the test proves reconstruction
    # rather than depending on an incomplete hand-built manifest.
    WorkGraphEpochRuntime(
        artifacts=artifacts,
        heads=app.controller.work_control,
    ).freeze_bootstrap(
        context_ref=context_ref,
        graph=graph,
        topology_id="topology:test-node",
    )
    runtime = WorkControlRuntime(
        artifacts=artifacts,
        heads=app.controller.work_control,
        budget=LeaseBudgetLedger(budget),
    )
    parent_output_ref = artifacts.put_json(
        artifact_id="output:captured-parent",
        artifact_type="design.test_node_parent",
        value={"source": "captured-parent"},
        dependencies=(context_ref,),
    )
    runtime.execute_deterministic_boundary(
        definition=parent,
        input_refs=(context_ref,),
        subject_ref=parent_output_ref,
        output_refs=(parent_output_ref,),
    )
    target_output_ref = artifacts.put_json(
        artifact_id="output:captured-target",
        artifact_type="design.test_node_target",
        value={"source": "captured-target"},
        dependencies=(context_ref, parent_output_ref),
    )
    target_head = runtime.execute_deterministic_boundary(
        definition=target,
        input_refs=(context_ref, parent_output_ref),
        subject_ref=target_output_ref,
        output_refs=(target_output_ref,),
    )
    assert target_head.status == "committed"
    app.telemetry.close()
    return _CapturedScope(
        config=config,
        scope_id=scope_id,
        state_root=config.state_root,
        parent_coordinate=parent.coordinate,
        target_definition=target,
        successor_definition=successor,
        source_target_attempt_ref=target_head.attempt_ref,
        source_target_output_ref=target_output_ref,
    )


def _assert_diagnostic_result_artifacts(
    *,
    result,
    target_coordinate: WorkCoordinate,
) -> None:
    diagnostic_root = Path(result.diagnostic_state_root)
    diagnostic_heads = WorkControlStore(diagnostic_root / "work-control")
    diagnostic_head = diagnostic_heads.read_head(target_coordinate)
    assert diagnostic_head is not None and diagnostic_head.commit_ref is not None
    assert os.path.isfile(result.archived_source_head_path)
    assert (diagnostic_root / "work-control" / ".test-node-diagnostic").read_text(
        encoding="utf-8"
    ) == "diagnostic_only=true\nreleasable=false\n"
    diagnostic_artifacts = ArtifactStore(diagnostic_root / "artifacts")
    attempt = diagnostic_artifacts.get_json(result.target_attempt_ref, WorkAttempt)
    commit = diagnostic_artifacts.get_json(diagnostic_head.commit_ref, WorkCommit)
    evaluation = diagnostic_artifacts.get_json(result.target_evaluation_ref)
    assert attempt.diagnostic_only is True and attempt.releasable is False
    assert commit.diagnostic_only is True and commit.releasable is False
    assert evaluation["diagnostic_only"] is True
    assert evaluation["releasable"] is False
    assert evaluation["readiness_effect"] == "observes"


@pytest.mark.asyncio
async def test_test_node_reruns_only_target_with_real_scheduler_dispatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _capture_scope(tmp_path, monkeypatch)
    calls: list[WorkCoordinate] = []
    fresh_outputs: list[ArtifactRef] = []

    def executor_factory(execution: NodeExecution):
        async def execute(context) -> None:
            calls.append(context.coordinate)
            input_refs = tuple(
                dict.fromkeys((*context.external_input_refs, *context.parent_output_refs))
            )
            output_ref = execution.app.controller.artifacts.put_json(
                artifact_id=f"rerun-target:{execution.run_id}",
                artifact_type="design.test_node_target",
                value={"source": "fresh-target-rerun"},
                dependencies=input_refs,
            )
            fresh_outputs.append(output_ref)
            execution.runtime.execute_deterministic_boundary(
                definition=execution.definition,
                input_refs=input_refs,
                subject_ref=output_ref,
                output_refs=(output_ref,),
            )

        return execute

    result = await NodeRunner(
        config=captured.config,
        source_state_root=captured.state_root,
        diagnostic_parent=tmp_path / "diagnostics",
        executor_factory=executor_factory,
    ).run(
        scope_id=captured.scope_id,
        target_coordinate="design.captured_target.captured_target",
    )

    assert calls == [captured.target_definition.coordinate]
    assert result.status == "committed"
    assert result.diagnostic_only is True
    assert result.releasable is False
    assert result.source_attempt_ref == captured.source_target_attempt_ref
    assert result.target_attempt_ref != captured.source_target_attempt_ref
    assert result.validation_report.diagnostic_only is True
    assert result.validation_report.releasable is False
    assert result.validation_report.subject_refs == tuple(fresh_outputs)
    assert captured.source_target_output_ref not in result.validation_report.subject_refs
    assert len(result.proposal_executions) == 1
    assert result.proposal_executions[0].output_commitment == fresh_outputs[0].content_hash
    assert result.reserved_budget.repair_attempts == 0

    source_heads = WorkControlStore(captured.state_root / "work-control")
    source_head = source_heads.read_head(captured.target_definition.coordinate)
    assert source_head is not None
    assert source_head.attempt_ref == captured.source_target_attempt_ref

    _assert_diagnostic_result_artifacts(
        result=result,
        target_coordinate=captured.target_definition.coordinate,
    )


@pytest.mark.asyncio
async def test_test_node_refreshes_a_current_implementation_as_one_new_scheduler_definition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A code/Prompt/Skill revision is durable evidence, not a budget disguise."""

    captured = _capture_scope(tmp_path, monkeypatch)
    updated_implementation = "framework.test-node-current-implementation.v1"
    updated_validator = "framework.test-node-current-validator.v1"
    monkeypatch.setattr(
        test_node_module,
        "current_runtime_revisions_for_definition",
        lambda definition: (
            (updated_implementation, updated_validator)
            if definition.coordinate == captured.target_definition.coordinate
            else None
        ),
    )
    dispatched_definitions: list[WorkDefinition] = []

    def executor_factory(execution: NodeExecution):
        async def execute(context) -> None:
            dispatched_definitions.append(execution.definition)
            input_refs = tuple(
                dict.fromkeys((*context.external_input_refs, *context.parent_output_refs))
            )
            output_ref = execution.app.controller.artifacts.put_json(
                artifact_id=f"current-runtime-target:{execution.run_id}",
                artifact_type="design.test_node_target",
                value={"source": "current-runtime-definition"},
                dependencies=input_refs,
            )
            execution.runtime.execute_deterministic_boundary(
                definition=execution.definition,
                input_refs=input_refs,
                subject_ref=output_ref,
                output_refs=(output_ref,),
            )

        return execute

    result = await NodeRunner(
        config=captured.config,
        source_state_root=captured.state_root,
        diagnostic_parent=tmp_path / "diagnostics",
        executor_factory=executor_factory,
    ).run(
        scope_id=captured.scope_id,
        target_coordinate="design.captured_target.captured_target",
        refresh_current_implementation=True,
    )

    assert result.status == "committed"
    assert result.runtime_implementation_override_ref is not None
    assert result.proposal_llm_tokens == result.source_proposal_llm_tokens
    assert result.proposal_wall_seconds == result.source_proposal_wall_seconds
    assert len(dispatched_definitions) == 1
    assert (
        dispatched_definitions[0].proposal_policy.implementation_revision_id
        == updated_implementation
    )
    assert dispatched_definitions[0].validation_policy.validator_revision_id == updated_validator

    diagnostic_artifacts = ArtifactStore(Path(result.diagnostic_state_root) / "artifacts")
    override = diagnostic_artifacts.get_json(
        result.runtime_implementation_override_ref,
        DiagnosticRuntimeImplementationOverride,
    )
    assert override.source_definition_digest == captured.target_definition.definition_digest
    assert override.implementation_revision_id == updated_implementation
    assert override.validator_revision_id == updated_validator
    assert override.diagnostic_only is True
    assert override.releasable is False

    source_head = WorkControlStore(captured.state_root / "work-control").read_head(
        captured.target_definition.coordinate
    )
    assert source_head is not None
    assert source_head.attempt_ref == captured.source_target_attempt_ref


def test_runtime_profile_overlay_freezes_one_changed_agent_provenance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A transport experiment becomes a new epoch, not a hidden config retry."""

    captured = _capture_scope(tmp_path, monkeypatch)
    WorkControlStore(captured.state_root / "work-control").mark_test_node_diagnostic_clone()
    app = build_application(captured.config)
    artifacts = app.controller.artifacts
    manifest_ref = next(
        ref
        for ref in artifacts.list_revisions()
        if ref.artifact_type == "control.work_graph_manifest"
    )
    manifest = artifacts.get_json(manifest_ref, WorkGraphManifest)
    graph = NodeRunner._reconstruct_graph(artifacts, manifest)  # noqa: SLF001 - frozen test input
    definition = next(
        item for item in graph.definitions if item.coordinate.stage == "evidence_synthesis"
    )
    assert definition.proposal_policy.executor == "agent"

    overlay = test_node_module._apply_diagnostic_runtime_profile_overlay(  # noqa: SLF001
        app=app,
        source=test_node_module._ProposalEnvelopeOverlaySource(  # noqa: SLF001
            graph=graph,
            manifest=manifest,
            manifest_ref=manifest_ref,
            definition=definition,
            context_ref=manifest.external_root_refs[0],
        ),
        source_model=captured.config.agent.model,
        model=captured.config.agent.model,
        source_transport="provider_schema",
        transport="json_object",
    )

    assert overlay.definition.coordinate == definition.coordinate
    assert overlay.definition.definition_digest != definition.definition_digest
    assert (
        overlay.definition.proposal_policy.implementation_revision_id
        != definition.proposal_policy.implementation_revision_id
    )
    override = artifacts.get_json(overlay.override_ref, DiagnosticRuntimeProfileOverride)
    assert override.source_manifest_ref == manifest_ref
    assert override.source_definition_digest == definition.definition_digest
    assert override.source_model == captured.config.agent.model
    assert override.model == captured.config.agent.model
    assert override.source_structured_output_transport == "provider_schema"
    assert override.structured_output_transport == "json_object"
    assert override.implementation_revision_id == (
        overlay.definition.proposal_policy.implementation_revision_id
    )
    assert override.diagnostic_only is True
    assert override.releasable is False


def test_runtime_profile_overlay_freezes_one_model_only_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A model route experiment cannot masquerade as an ordinary retry."""

    captured = _capture_scope(tmp_path, monkeypatch)
    WorkControlStore(captured.state_root / "work-control").mark_test_node_diagnostic_clone()
    app = build_application(captured.config)
    artifacts = app.controller.artifacts
    manifest_ref = next(
        ref
        for ref in artifacts.list_revisions()
        if ref.artifact_type == "control.work_graph_manifest"
    )
    manifest = artifacts.get_json(manifest_ref, WorkGraphManifest)
    graph = NodeRunner._reconstruct_graph(artifacts, manifest)  # noqa: SLF001 - frozen test input
    definition = next(
        item for item in graph.definitions if item.coordinate.stage == "evidence_synthesis"
    )

    overlay = test_node_module._apply_diagnostic_runtime_profile_overlay(  # noqa: SLF001
        app=app,
        source=test_node_module._ProposalEnvelopeOverlaySource(  # noqa: SLF001
            graph=graph,
            manifest=manifest,
            manifest_ref=manifest_ref,
            definition=definition,
            context_ref=manifest.external_root_refs[0],
        ),
        source_model="gpt-5.4-mini",
        model="gpt-5.3-codex-spark",
        source_transport="json_envelope",
        transport="json_envelope",
    )

    override = artifacts.get_json(overlay.override_ref, DiagnosticRuntimeProfileOverride)
    assert override.source_model == "gpt-5.4-mini"
    assert override.model == "gpt-5.3-codex-spark"
    assert override.source_structured_output_transport == "json_envelope"
    assert override.structured_output_transport == "json_envelope"
    assert (
        overlay.definition.proposal_policy.implementation_revision_id
        != definition.proposal_policy.implementation_revision_id
    )


@pytest.mark.asyncio
async def test_test_node_nonterminal_scheduler_error_rebuilds_fresh_running_scene(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A harness failure cannot inherit a stale successful scene from its parent."""

    captured = _capture_scope(tmp_path, monkeypatch)
    diagnostic_parent = tmp_path / "diagnostics"

    def executor_factory(_execution: NodeExecution):
        async def execute(_context) -> None:
            # Deliberately return without closing the Scheduler-opened attempt.
            # The true Scheduler boundary must report this as nonterminal
            # framework evidence, not preserve the source scene.
            return None

        return execute

    with pytest.raises(NodeError) as raised:
        await NodeRunner(
            config=captured.config,
            source_state_root=captured.state_root,
            diagnostic_parent=diagnostic_parent,
            executor_factory=executor_factory,
        ).run(
            scope_id=captured.scope_id,
            target_coordinate=captured.target_definition.coordinate.coordinate_key,
        )

    assert raised.value.code == "test_node_nonterminal_dispatch_failure"
    diagnostic_roots = tuple(diagnostic_parent.iterdir())
    assert len(diagnostic_roots) == 1
    diagnostic_root = diagnostic_roots[0]
    head = WorkControlStore(diagnostic_root / "work-control").read_head(
        captured.target_definition.coordinate
    )
    assert head is not None and head.status == "running"
    scene = (diagnostic_root / "observability" / captured.scope_id / "scene.md").read_text(
        encoding="utf-8"
    )
    assert scene.startswith("Status: running\n")


@pytest.mark.asyncio
async def test_diagnostic_descendant_dispatches_one_unheaded_successor_from_diagnostic_parent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A real diagnostic parent can drive one frozen unheaded successor only."""

    captured = _capture_scope(tmp_path, monkeypatch)
    diagnostic_parent = tmp_path / ".agent-world-live"
    rerun_calls: list[WorkCoordinate] = []

    def target_executor_factory(execution: NodeExecution):
        async def execute(context) -> None:
            rerun_calls.append(context.coordinate)
            input_refs = tuple(
                dict.fromkeys((*context.external_input_refs, *context.parent_output_refs))
            )
            output_ref = execution.app.controller.artifacts.put_json(
                artifact_id=f"rerun-target:{execution.run_id}",
                artifact_type="design.test_node_target",
                value={"source": "fresh-diagnostic-parent"},
                dependencies=input_refs,
            )
            execution.runtime.execute_deterministic_boundary(
                definition=execution.definition,
                input_refs=input_refs,
                subject_ref=output_ref,
                output_refs=(output_ref,),
            )

        return execute

    parent_result = await NodeRunner(
        config=captured.config,
        source_state_root=captured.state_root,
        diagnostic_parent=diagnostic_parent,
        executor_factory=target_executor_factory,
    ).run(
        scope_id=captured.scope_id,
        target_coordinate=captured.target_definition.coordinate.coordinate_key,
    )
    assert rerun_calls == [captured.target_definition.coordinate]
    parent_root = Path(parent_result.diagnostic_state_root)
    assert (
        WorkControlStore(parent_root / "work-control").read_head(
            captured.successor_definition.coordinate
        )
        is None
    )

    successor_calls: list[WorkCoordinate] = []
    successor_outputs: list[ArtifactRef] = []
    manifest_refs = tuple(
        ref
        for ref in ArtifactStore(parent_root / "artifacts").list_revisions()
        if ref.artifact_type == "control.work_graph_manifest"
    )
    assert len(manifest_refs) == 1

    def successor_executor_factory(execution: NodeExecution):
        async def execute(context) -> None:
            successor_calls.append(context.coordinate)
            input_refs = tuple(
                dict.fromkeys((*context.external_input_refs, *context.parent_output_refs))
            )
            output_ref = execution.app.controller.artifacts.put_json(
                artifact_id=f"successor:{execution.run_id}",
                artifact_type="design.test_node_successor",
                value={"source": "fresh-diagnostic-successor"},
                dependencies=input_refs,
            )
            successor_outputs.append(output_ref)
            execution.runtime.execute_deterministic_boundary(
                definition=execution.definition,
                input_refs=input_refs,
                subject_ref=output_ref,
                output_refs=(output_ref,),
            )

        return execute

    result = await DescendantRunner(
        config=captured.config,
        diagnostic_state_root=parent_root,
        diagnostic_parent=diagnostic_parent,
        executor_factory=successor_executor_factory,
    ).run(
        scope_id=captured.scope_id,
        target_coordinate="design.unheaded_successor.unheaded_successor",
        required_manifest_revision=manifest_refs[0].revision_id,
    )

    assert successor_calls == [captured.successor_definition.coordinate]
    assert result.status == "committed"
    assert result.diagnostic_only is True
    assert result.releasable is False
    assert result.execution_envelope.physical_turn_llm_tokens == result.proposal_llm_tokens
    assert result.execution_envelope.logical_session_token_limit is None
    assert result.predecessor_commit_refs == (parent_result.target_commit_ref,)
    assert result.validation_report.subject_refs == tuple(successor_outputs)
    assert (
        WorkControlStore(parent_root / "work-control").read_head(
            captured.successor_definition.coordinate
        )
        is None
    )

    result_root = Path(result.diagnostic_state_root)
    result_heads = WorkControlStore(result_root / "work-control")
    successor_head = result_heads.read_head(captured.successor_definition.coordinate)
    assert successor_head is not None and successor_head.commit_ref is not None
    result_artifacts = ArtifactStore(result_root / "artifacts")
    successor_attempt = result_artifacts.get_json(result.target_attempt_ref, WorkAttempt)
    successor_commit = result_artifacts.get_json(successor_head.commit_ref, WorkCommit)
    successor_evaluation = result_artifacts.get_json(result.target_evaluation_ref)
    assert successor_attempt.diagnostic_only and not successor_attempt.releasable
    assert successor_commit.diagnostic_only and not successor_commit.releasable
    assert successor_evaluation["diagnostic_only"] is True
    assert successor_evaluation["releasable"] is False


@pytest.mark.asyncio
async def test_diagnostic_descendant_allows_one_explicit_retryable_infrastructure_attempt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A recovered provider route can consume one exact failed diagnostic attempt.

    This is deliberately a real Scheduler/Proposal/Validation/Feedback/RepairAction
    boundary test, rather than a direct WorkHead mutation.  The first physical
    leaf records typed retryable transport evidence; the second is only possible
    through the explicit ``infrastructure_retry`` route and retains the same
    frozen graph definition and envelope.
    """

    captured = _capture_scope(tmp_path, monkeypatch)
    diagnostic_parent = tmp_path / ".agent-world-live"

    def parent_executor_factory(execution: NodeExecution):
        async def execute(context) -> None:
            input_refs = tuple(
                dict.fromkeys((*context.external_input_refs, *context.parent_output_refs))
            )
            output_ref = execution.app.controller.artifacts.put_json(
                artifact_id=f"retry-parent:{execution.run_id}",
                artifact_type="design.test_node_target",
                value={"source": "diagnostic-parent-for-retry"},
                dependencies=input_refs,
            )
            execution.runtime.execute_deterministic_boundary(
                definition=execution.definition,
                input_refs=input_refs,
                subject_ref=output_ref,
                output_refs=(output_ref,),
            )

        return execute

    parent = await NodeRunner(
        config=captured.config,
        source_state_root=captured.state_root,
        diagnostic_parent=diagnostic_parent,
        executor_factory=parent_executor_factory,
    ).run(
        scope_id=captured.scope_id,
        target_coordinate=captured.target_definition.coordinate.coordinate_key,
    )
    parent_root = Path(parent.diagnostic_state_root)
    parent_app = build_application(captured.config.model_copy(update={"state_root": parent_root}))
    parent_artifacts = parent_app.controller.artifacts
    source_manifest_ref = next(
        ref
        for ref in parent_artifacts.list_revisions()
        if ref.artifact_type == "control.work_graph_manifest"
    )
    source_manifest = parent_artifacts.get_json(source_manifest_ref, WorkGraphManifest)

    # The captured helper intentionally uses code-owned boundaries.  Grant
    # only this successor one infrastructure retry policy so the test can
    # prove control-plane recovery without fabricating an Agent response.
    source_graph = NodeRunner._reconstruct_graph(  # noqa: SLF001 - frozen test closure setup
        parent_artifacts,
        source_manifest,
    )
    retry_successor = source_graph.require(captured.successor_definition.coordinate).model_copy(
        update={
            "repair_policy": captured.successor_definition.repair_policy.model_copy(
                update={
                    "maximum_infrastructure_retries": 1,
                    "maximum_total_repair_attempts": 1,
                }
            )
        }
    )
    retry_graph = GenerationWorkGraph.compile(
        (
            source_graph.require(captured.parent_coordinate),
            source_graph.require(captured.target_definition.coordinate),
            retry_successor,
        ),
        mode="diagnostic",
        strict_input_contracts=True,
    )
    for definition in retry_graph.definitions:
        parent_artifacts.put_json(
            artifact_id=f"work-definition:{definition.work_id}",
            artifact_type="control.work_definition",
            value=definition,
            dependencies=source_manifest.external_root_refs,
        )
    retry_manifest = retry_graph.manifest(
        topology_id="topology:test-node-infrastructure-retry",
        external_root_refs=source_manifest.external_root_refs,
    )
    retry_manifest_ref = parent_artifacts.put_json(
        artifact_id=retry_manifest.graph_id,
        artifact_type="control.work_graph_manifest",
        value=retry_manifest,
        dependencies=source_manifest.external_root_refs,
    )

    first_calls: list[str] = []

    def failing_executor_factory(execution: NodeExecution):
        kernel = SchedulerLeafExecutor(runtime=execution.runtime)

        async def proposal(_context, _attempt, _dispatch_id) -> LeafProposal:
            first_calls.append("provider-route")
            raise LeafExecutionFailure(
                code="test_retryable_provider_unavailable",
                category="one typed transient provider-route failure",
                retryable=True,
                expected_category="one fresh physical attempt after same-route liveness succeeds",
            )

        async def execute(context) -> None:
            await kernel.execute(
                context,
                definition=execution.definition,
                proposal_runner=proposal,
            )

        return execute

    first = await DescendantRunner(
        config=captured.config,
        diagnostic_state_root=parent_root,
        diagnostic_parent=diagnostic_parent,
        executor_factory=failing_executor_factory,
    ).run(
        scope_id=captured.scope_id,
        target_coordinate=retry_successor.coordinate.coordinate_key,
        required_manifest_ref=retry_manifest_ref,
    )

    assert first_calls == ["provider-route"]
    assert first.status == "failed"
    assert first.validation_report.status == "error"
    assert first.validation_report.infrastructure_retryable is True
    assert first.proposal_budget_override_ref is None

    # A changed envelope is a new diagnostic experiment, never a retry of the
    # transport failure.  Reject it before the RepairAction or leaf executes.
    with pytest.raises(NodeError) as mismatched_retry:
        await DescendantRunner(
            config=captured.config,
            diagnostic_state_root=Path(first.diagnostic_state_root),
            diagnostic_parent=diagnostic_parent,
            executor_factory=failing_executor_factory,
        ).run(
            scope_id=captured.scope_id,
            target_coordinate=retry_successor.coordinate.coordinate_key,
            required_manifest_ref=retry_manifest_ref,
            proposal_llm_tokens=1,
            infrastructure_retry=True,
        )
    assert mismatched_retry.value.code == "test_descendant_infrastructure_retry_envelope_mismatch"

    retry_calls: list[WorkCoordinate] = []

    def recovered_executor_factory(execution: NodeExecution):
        kernel = SchedulerLeafExecutor(runtime=execution.runtime)

        async def proposal(context, _attempt, _dispatch_id) -> LeafProposal:
            retry_calls.append(context.coordinate)
            input_refs = tuple(
                dict.fromkeys((*context.external_input_refs, *context.parent_output_refs))
            )
            output_ref = execution.app.controller.artifacts.put_json(
                artifact_id=f"retry-recovered-output:{execution.run_id}",
                artifact_type="design.test_node_successor",
                value={"source": "same-definition-recovered-provider-route"},
                dependencies=input_refs,
            )
            return LeafProposal(output_refs=(output_ref,), subject_refs=(output_ref,))

        async def execute(context) -> None:
            await kernel.execute(
                context,
                definition=execution.definition,
                proposal_runner=proposal,
            )

        return execute

    retried = await DescendantRunner(
        config=captured.config,
        diagnostic_state_root=Path(first.diagnostic_state_root),
        diagnostic_parent=diagnostic_parent,
        executor_factory=recovered_executor_factory,
    ).run(
        scope_id=captured.scope_id,
        target_coordinate=retry_successor.coordinate.coordinate_key,
        required_manifest_ref=retry_manifest_ref,
        infrastructure_retry=True,
    )

    assert retry_calls == [retry_successor.coordinate]
    assert retried.status == "committed"
    assert retried.proposal_budget_override_ref is None
    assert retried.reserved_budget.repair_attempts == 1
    assert retried.infrastructure_retry_action_ref is not None
    retried_artifacts = ArtifactStore(Path(retried.diagnostic_state_root) / "artifacts")
    action = retried_artifacts.get_json(
        retried.infrastructure_retry_action_ref,
        RepairAction,
    )
    previous_attempt = ArtifactStore(Path(first.diagnostic_state_root) / "artifacts").get_json(
        first.target_attempt_ref,
        WorkAttempt,
    )
    retry_attempt = retried_artifacts.get_json(retried.target_attempt_ref, WorkAttempt)
    assert action.decision == "infrastructure_retry"
    assert action.source_evaluation_ref == first.target_evaluation_ref
    assert retry_attempt.parent_attempt_id == previous_attempt.attempt_id
    assert retry_attempt.repair_action_ref == retried.infrastructure_retry_action_ref
    assert retry_attempt.repair_attempt_charge == 1

    with pytest.raises(NodeError) as repeated_retry:
        await DescendantRunner(
            config=captured.config,
            diagnostic_state_root=Path(retried.diagnostic_state_root),
            diagnostic_parent=diagnostic_parent,
            executor_factory=recovered_executor_factory,
        ).run(
            scope_id=captured.scope_id,
            target_coordinate=retry_successor.coordinate.coordinate_key,
            required_manifest_ref=retry_manifest_ref,
            infrastructure_retry=True,
        )
    assert repeated_retry.value.code == "test_descendant_infrastructure_retry_not_failed"
    assert retry_calls == [retry_successor.coordinate]


@pytest.mark.asyncio
async def test_diagnostic_descendant_external_cancellation_settles_started_operation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The actual descendant runner turns an external cancel into terminal evidence."""

    captured = _capture_scope(tmp_path, monkeypatch)
    diagnostic_parent = tmp_path / ".agent-world-live"

    def target_executor_factory(execution: NodeExecution):
        async def execute(context) -> None:
            input_refs = tuple(
                dict.fromkeys((*context.external_input_refs, *context.parent_output_refs))
            )
            output_ref = execution.app.controller.artifacts.put_json(
                artifact_id=f"descendant-cancel-parent:{execution.run_id}",
                artifact_type="design.test_node_target",
                value={"source": "fresh-diagnostic-parent"},
                dependencies=input_refs,
            )
            execution.runtime.execute_deterministic_boundary(
                definition=execution.definition,
                input_refs=input_refs,
                subject_ref=output_ref,
                output_refs=(output_ref,),
            )

        return execute

    parent_result = await NodeRunner(
        config=captured.config,
        source_state_root=captured.state_root,
        diagnostic_parent=diagnostic_parent,
        executor_factory=target_executor_factory,
    ).run(
        scope_id=captured.scope_id,
        target_coordinate=captured.target_definition.coordinate.coordinate_key,
    )
    started = asyncio.Event()

    def executor_factory(execution: NodeExecution):
        async def execute(context) -> None:
            input_refs = tuple(
                dict.fromkeys((*context.external_input_refs, *context.parent_output_refs))
            )
            with execution.runtime.heads.exclusive(execution.definition.coordinate) as lock:
                execution.runtime.schedule_operation(
                    lock,
                    definition=execution.definition,
                    kind="proposal",
                    replay_mode="non_replayable",
                    elapsed_wall_seconds=0,
                    input_refs=input_refs,
                )
                execution.runtime.start_operation(
                    lock,
                    definition=execution.definition,
                    dispatch_id="dispatch:descendant-external-cancellation",
                )
            started.set()
            await asyncio.Event().wait()

        return execute

    task = asyncio.create_task(
        DescendantRunner(
            config=captured.config,
            diagnostic_state_root=Path(parent_result.diagnostic_state_root),
            diagnostic_parent=diagnostic_parent,
            executor_factory=executor_factory,
        ).run(
            scope_id=captured.scope_id,
            target_coordinate=captured.successor_definition.coordinate.coordinate_key,
        )
    )
    await asyncio.wait_for(started.wait(), timeout=1)
    task.cancel()
    result = await task

    assert result.status == "failed"
    assert result.validation_report.status == "error"
    assert result.validation_report.issues[0].code == "process_interrupted_cancelled"
    result_head = WorkControlStore(Path(result.diagnostic_state_root) / "work-control").read_head(
        captured.successor_definition.coordinate
    )
    assert result_head is not None and result_head.status == "failed"


@pytest.mark.asyncio
async def test_diagnostic_commit_is_never_normal_scheduler_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only an explicitly marked diagnostic successor may consume this commit."""

    captured = _capture_scope(tmp_path, monkeypatch)

    def executor_factory(execution: NodeExecution):
        async def execute(context) -> None:
            input_refs = tuple(
                dict.fromkeys((*context.external_input_refs, *context.parent_output_refs))
            )
            output_ref = execution.app.controller.artifacts.put_json(
                artifact_id=f"diagnostic-authority-target:{execution.run_id}",
                artifact_type="design.test_node_target",
                value={"source": "fresh-diagnostic-target"},
                dependencies=input_refs,
            )
            execution.runtime.execute_deterministic_boundary(
                definition=execution.definition,
                input_refs=input_refs,
                subject_ref=output_ref,
                output_refs=(output_ref,),
            )

        return execute

    result = await NodeRunner(
        config=captured.config,
        source_state_root=captured.state_root,
        diagnostic_parent=tmp_path / "diagnostics",
        executor_factory=executor_factory,
    ).run(
        scope_id=captured.scope_id,
        target_coordinate=captured.target_definition.coordinate.coordinate_key,
    )
    diagnostic_config = captured.config.model_copy(
        update={"state_root": Path(result.diagnostic_state_root)}
    )
    app = build_application(diagnostic_config)
    frozen = NodeRunner(config=diagnostic_config)._load_frozen_target(  # noqa: SLF001
        app=app,
        scope_id=captured.scope_id,
        target=captured.target_definition.coordinate,
    )
    attempt = app.controller.artifacts.get_json(result.target_attempt_ref, WorkAttempt)

    assert (
        app.controller.work_control.require_active_commit(
            definition=frozen.definition,
            input_refs=attempt.input_refs,
            artifacts=app.controller.artifacts,
        )
        is None
    )
    diagnostic_commit = app.controller.work_control.require_diagnostic_commit(
        definition=frozen.definition,
        input_refs=attempt.input_refs,
        artifacts=app.controller.artifacts,
    )
    assert diagnostic_commit is not None

    with pytest.raises(NodeError, match="diagnostic-only commit"):
        NodeRunner._assert_complete_ancestor_closure(  # noqa: SLF001 - authority guard
            app=app,
            graph=frozen.graph,
            target=captured.successor_definition.coordinate,
        )
    NodeRunner._assert_complete_ancestor_closure(  # noqa: SLF001 - authority guard
        app=app,
        graph=frozen.graph,
        target=captured.successor_definition.coordinate,
        allow_diagnostic_ancestor_closure=True,
    )

    ordinary_snapshot = WorkScheduler(
        graph=frozen.graph,
        manifest=frozen.manifest,
        manifest_ref=frozen.manifest_ref,
        heads=app.controller.work_control,
        artifacts=app.controller.artifacts,
    ).snapshot()
    assert (
        next(
            item
            for item in ordinary_snapshot.work
            if item.coordinate == captured.target_definition.coordinate
        ).state
        == "stale"
    )

    diagnostic_runtime = WorkControlRuntime(
        artifacts=app.controller.artifacts,
        heads=app.controller.work_control,
        budget=LeaseBudgetLedger(Budget(wall_seconds=1_000)),
        diagnostic_only=True,
    )
    diagnostic_scheduler = WorkScheduler(
        graph=frozen.graph,
        manifest=frozen.manifest,
        manifest_ref=frozen.manifest_ref,
        heads=app.controller.work_control,
        artifacts=app.controller.artifacts,
        runtime=diagnostic_runtime,
        allow_diagnostic_ancestors=True,
    )
    diagnostic_snapshot = diagnostic_scheduler.snapshot()
    assert (
        next(
            item
            for item in diagnostic_snapshot.work
            if item.coordinate == captured.target_definition.coordinate
        ).state
        == "committed"
    )
    resolved = diagnostic_scheduler.resolve_inputs(captured.successor_definition.coordinate)
    assert resolved.parent_commit_refs == (diagnostic_commit[1],)


@pytest.mark.asyncio
async def test_test_node_failed_target_is_terminal_evidence_not_a_repair_loop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _capture_scope(tmp_path, monkeypatch)
    calls: list[WorkCoordinate] = []

    def executor_factory(execution: NodeExecution):
        async def execute(context) -> None:
            calls.append(context.coordinate)
            input_refs = tuple(
                dict.fromkeys((*context.external_input_refs, *context.parent_output_refs))
            )
            output_ref = execution.app.controller.artifacts.put_json(
                artifact_id=f"rerun-failed-target:{execution.run_id}",
                artifact_type="design.test_node_target",
                value={"source": "fresh-target-failure"},
                dependencies=input_refs,
            )
            execution.runtime.execute_deterministic_boundary(
                definition=execution.definition,
                input_refs=input_refs,
                subject_ref=output_ref,
                output_refs=(output_ref,),
                issues=(
                    (
                        "test_node_real_failure",
                        ("target",),
                        "The actual target boundary rejected this fresh output.",
                        "the frozen target acceptance condition",
                    ),
                ),
            )

        return execute

    result = await NodeRunner(
        config=captured.config,
        source_state_root=captured.state_root,
        diagnostic_parent=tmp_path / "diagnostics",
        executor_factory=executor_factory,
    ).run(
        scope_id=captured.scope_id,
        target_coordinate=captured.target_definition.coordinate.coordinate_key,
    )

    assert calls == [captured.target_definition.coordinate]
    assert result.status == "failed"
    assert result.target_commit_ref is None
    assert result.validation_report.status == "failed"
    assert result.validation_report.diagnostic_only is True
    diagnostic_head = WorkControlStore(
        Path(result.diagnostic_state_root) / "work-control"
    ).read_head(captured.target_definition.coordinate)
    assert diagnostic_head is not None
    assert diagnostic_head.status == "failed"
    assert diagnostic_head.repair_action_ref is None
    assert diagnostic_head.commit_ref is None


@pytest.mark.asyncio
async def test_test_node_cancellation_is_terminal_unknown_agent_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _capture_scope(tmp_path, monkeypatch)

    def executor_factory(execution: NodeExecution):
        kernel = SchedulerLeafExecutor(runtime=execution.runtime)

        async def cancelled_proposal(_context, _attempt, _dispatch_id):
            raise asyncio.CancelledError

        async def execute(context) -> None:
            await kernel.execute(
                context,
                definition=execution.definition,
                proposal_runner=cancelled_proposal,
            )

        return execute

    result = await NodeRunner(
        config=captured.config,
        source_state_root=captured.state_root,
        diagnostic_parent=tmp_path / "diagnostics",
        executor_factory=executor_factory,
    ).run(
        scope_id=captured.scope_id,
        target_coordinate=captured.target_definition.coordinate.coordinate_key,
    )

    assert result.status == "failed"
    assert result.target_commit_ref is None
    assert result.validation_report.status == "error"
    assert result.validation_report.issues[0].code == "process_interrupted_cancelled"
    assert result.unknown_usage.agent_turns == 0

    artifacts = ArtifactStore(Path(result.diagnostic_state_root) / "artifacts")
    assert result.target_attempt_ref is not None
    attempt = artifacts.get_json(result.target_attempt_ref, WorkAttempt)
    operation = artifacts.get_json(attempt.operation_run_refs[0], OperationRun)
    assert operation.status == "terminal"
    assert operation.error_code == "process_interrupted_cancelled"
    assert operation.execution_ref is not None
    execution = artifacts.get_json(operation.execution_ref)
    assert execution["status"] == "interrupted"
    assert execution["invocation_id"] is None
    assert execution["unknown_upper_bound"]["agent_turns"] == 0


@pytest.mark.asyncio
async def test_test_node_external_cancellation_settles_started_operation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A CLI-level cancellation cannot strand a dispatched diagnostic head."""

    captured = _capture_scope(tmp_path, monkeypatch)
    started = asyncio.Event()

    def executor_factory(execution: NodeExecution):
        async def execute(context) -> None:
            input_refs = tuple(
                dict.fromkeys((*context.external_input_refs, *context.parent_output_refs))
            )
            with execution.runtime.heads.exclusive(execution.definition.coordinate) as lock:
                execution.runtime.schedule_operation(
                    lock,
                    definition=execution.definition,
                    kind="proposal",
                    replay_mode="non_replayable",
                    elapsed_wall_seconds=0,
                    input_refs=input_refs,
                )
                execution.runtime.start_operation(
                    lock,
                    definition=execution.definition,
                    dispatch_id="dispatch:test-node-external-cancellation",
                )
            started.set()
            await asyncio.Event().wait()

        return execute

    task = asyncio.create_task(
        NodeRunner(
            config=captured.config,
            source_state_root=captured.state_root,
            diagnostic_parent=tmp_path / "diagnostics",
            executor_factory=executor_factory,
        ).run(
            scope_id=captured.scope_id,
            target_coordinate=captured.target_definition.coordinate.coordinate_key,
        )
    )
    await asyncio.wait_for(started.wait(), timeout=1)
    task.cancel()
    result = await task

    assert result.status == "failed"
    assert result.validation_report.status == "error"
    assert result.validation_report.issues[0].code == "process_interrupted_cancelled"
    artifacts = ArtifactStore(Path(result.diagnostic_state_root) / "artifacts")
    attempt = artifacts.get_json(result.target_attempt_ref, WorkAttempt)
    operation = artifacts.get_json(attempt.operation_run_refs[0], OperationRun)
    assert operation.status == "terminal"
    assert operation.error_code == "process_interrupted_cancelled"


@pytest.mark.asyncio
async def test_test_node_fails_closed_when_a_committed_ancestor_head_is_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _capture_scope(tmp_path, monkeypatch)
    parent_key = hashlib.sha256(
        f"{captured.scope_id}\0{captured.parent_coordinate.coordinate_key}".encode()
    ).hexdigest()
    parent_head = captured.state_root / "work-control" / "heads" / f"{parent_key}.json"
    withheld_parent_head = captured.state_root / "withheld-parent-head.json"
    parent_head.replace(withheld_parent_head)
    calls: list[WorkCoordinate] = []

    def executor_factory(_execution: NodeExecution):
        async def execute(context) -> None:
            calls.append(context.coordinate)

        return execute

    with pytest.raises(NodeError) as raised:
        await NodeRunner(
            config=captured.config,
            source_state_root=captured.state_root,
            diagnostic_parent=tmp_path / "diagnostics",
            executor_factory=executor_factory,
        ).run(
            scope_id=captured.scope_id,
            target_coordinate=captured.target_definition.coordinate.coordinate_key,
        )

    assert raised.value.code == "missing_ancestor_closure"
    assert calls == []
    assert withheld_parent_head.is_file()
    assert (
        WorkControlStore(captured.state_root / "work-control").read_head(
            captured.target_definition.coordinate
        )
        is not None
    )


def test_test_node_archive_requires_a_marked_diagnostic_copy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _capture_scope(tmp_path, monkeypatch)
    heads = WorkControlStore(captured.state_root / "work-control")
    source_head = heads.read_head(captured.target_definition.coordinate)
    assert source_head is not None

    with heads.exclusive(captured.target_definition.coordinate) as lock:
        with pytest.raises(WorkControlStoreError, match="isolated test-node state"):
            heads.archive_terminal_head_for_diagnostic(lock, expected_head=source_head)

    assert heads.read_head(captured.target_definition.coordinate) == source_head


def test_test_node_copy_excludes_non_durable_agent_workspaces(tmp_path: Path) -> None:
    source_root = tmp_path / "source-state"
    (source_root / "artifacts").mkdir(parents=True)
    (source_root / "artifacts" / "durable.json").write_text("{}", encoding="utf-8")
    runtime_home = source_root / "runs" / "prior-agent" / ".agent-runtime"
    runtime_home.mkdir(parents=True)
    (runtime_home / "tool-link").symlink_to(tmp_path / "outside-tool")
    source_runs = source_root / "expansion-source-runs" / "prior-agent"
    source_runs.mkdir(parents=True)
    for directory in ("campaigns", "direct-jobs", "observability", "registry", "telemetry"):
        (source_root / directory).mkdir()

    diagnostic_root = tmp_path / "diagnostic-state"
    NodeRunner._copy_state_root(source_root, diagnostic_root)

    assert (diagnostic_root / "artifacts" / "durable.json").is_file()
    assert not (diagnostic_root / "runs").exists()
    assert not (diagnostic_root / "expansion-source-runs").exists()
    for directory in ("campaigns", "direct-jobs", "observability", "registry", "telemetry"):
        assert not (diagnostic_root / directory).exists()


def test_observability_allows_only_marked_test_node_live_copy(tmp_path: Path) -> None:
    live_parent = tmp_path / ".agent-world-live"
    ordinary_state = live_parent / "ordinary-state"
    with pytest.raises(ObservabilityError, match="reserved live state"):
        ObservabilityRoot(ordinary_state)

    diagnostic_state = live_parent / "test-node-isolated"
    (diagnostic_state / "work-control").mkdir(parents=True)
    WorkControlStore(diagnostic_state / "work-control").mark_test_node_diagnostic_clone()

    root = ObservabilityRoot(diagnostic_state)
    assert root.state_root == diagnostic_state.resolve()


def test_test_node_cli_accepts_exact_scope_coordinate_and_source_override(tmp_path: Path) -> None:
    source_override = str(tmp_path / "captured-state")
    parsed = build_parser().parse_args(
        [
            "test-node",
            "generate-job:test-node",
            "sha256:" + "a" * 64,
            "--source-state-root",
            source_override,
        ]
    )

    assert parsed.command == "test-node"
    assert parsed.scope_id == "generate-job:test-node"
    assert parsed.target_coordinate == "sha256:" + "a" * 64
    assert parsed.source_state_root == source_override
    assert parsed.proposal_llm_tokens is None
    assert parsed.proposal_wall_seconds is None
    assert parsed.refresh_current_implementation is False
    assert parsed.diagnostic_structured_output_transport is None
    assert parsed.diagnostic_model is None
    assert parsed.diagnostic_source_model is None


def test_test_node_cli_accepts_one_explicit_long_diagnostic_envelope(tmp_path: Path) -> None:
    source_override = str(tmp_path / "captured-state")
    parsed = build_parser().parse_args(
        [
            "test-node",
            "generate-job:test-node",
            "build.candidate_build.environment_candidate",
            "--source-state-root",
            source_override,
            "--proposal-llm-tokens",
            "5000000",
            "--proposal-wall-seconds",
            "28800",
        ]
    )

    assert parsed.proposal_llm_tokens == 5_000_000
    assert parsed.proposal_wall_seconds == 28_800.0


def test_test_node_cli_accepts_one_current_runtime_implementation_refresh(tmp_path: Path) -> None:
    parsed = build_parser().parse_args(
        [
            "test-node",
            "generate-job:test-node",
            "research.evidence_synthesis.evidence_synthesis",
            "--source-state-root",
            str(tmp_path / "captured-state"),
            "--refresh-current-implementation",
        ]
    )

    assert parsed.refresh_current_implementation is True
    assert parsed.proposal_llm_tokens is None
    assert parsed.proposal_wall_seconds is None


def test_test_node_cli_accepts_one_profile_transport_overlay(tmp_path: Path) -> None:
    parsed = build_parser().parse_args(
        [
            "test-node",
            "generate-job:test-node",
            "research.evidence_synthesis.evidence_synthesis",
            "--source-state-root",
            str(tmp_path / "captured-state"),
            "--diagnostic-structured-output-transport",
            "json_object",
        ]
    )

    assert parsed.diagnostic_structured_output_transport == "json_object"
    assert parsed.refresh_current_implementation is False
    assert parsed.proposal_llm_tokens is None
    assert parsed.proposal_wall_seconds is None


def test_test_node_cli_accepts_one_model_only_profile_overlay(tmp_path: Path) -> None:
    parsed = build_parser().parse_args(
        [
            "test-node",
            "generate-job:test-node",
            "research.evidence_synthesis.evidence_synthesis",
            "--source-state-root",
            str(tmp_path / "captured-state"),
            "--diagnostic-source-model",
            "gpt-5.4-mini",
            "--diagnostic-model",
            "gpt-5.3-codex-spark",
        ]
    )

    assert parsed.diagnostic_source_model == "gpt-5.4-mini"
    assert parsed.diagnostic_model == "gpt-5.3-codex-spark"
    assert parsed.diagnostic_structured_output_transport is None


def test_descendant_node_cli_requires_marked_diagnostic_source(tmp_path: Path) -> None:
    diagnostic_state = str(tmp_path / ".agent-world-live" / "test-node-source")
    parsed = build_parser().parse_args(
        [
            "test-descendant-node",
            "generate-job:test-node",
            "design|task_curriculum|task_curriculum||",
            "--diagnostic-state-root",
            diagnostic_state,
        ]
    )

    assert parsed.command == "test-descendant-node"
    assert parsed.scope_id == "generate-job:test-node"
    assert parsed.target_coordinate == "design|task_curriculum|task_curriculum||"
    assert parsed.diagnostic_state_root == diagnostic_state
    assert parsed.proposal_llm_tokens is None
    assert parsed.proposal_wall_seconds is None
    assert parsed.infrastructure_retry is False
    assert parsed.diagnostic_structured_output_transport is None
    assert parsed.diagnostic_model is None
    assert parsed.diagnostic_source_model is None


def test_descendant_node_cli_accepts_one_explicit_long_diagnostic_envelope(
    tmp_path: Path,
) -> None:
    diagnostic_state = str(tmp_path / ".agent-world-live" / "test-node-source")
    parsed = build_parser().parse_args(
        [
            "test-descendant-node",
            "generate-job:test-node",
            "design|task_curriculum|task_curriculum||",
            "--diagnostic-state-root",
            diagnostic_state,
            "--proposal-llm-tokens",
            "5000000",
            "--proposal-wall-seconds",
            "28800",
        ]
    )

    assert parsed.proposal_llm_tokens == 5_000_000
    assert parsed.proposal_wall_seconds == 28_800.0


def test_descendant_node_cli_accepts_one_explicit_infrastructure_retry(
    tmp_path: Path,
) -> None:
    diagnostic_state = str(tmp_path / ".agent-world-live" / "test-node-source")
    parsed = build_parser().parse_args(
        [
            "test-descendant-node",
            "generate-job:test-node",
            "build.candidate_build.environment_candidate",
            "--diagnostic-state-root",
            diagnostic_state,
            "--proposal-llm-tokens",
            "5000000",
            "--proposal-wall-seconds",
            "28800",
            "--infrastructure-retry",
        ]
    )

    assert parsed.infrastructure_retry is True
    assert parsed.proposal_llm_tokens == 5_000_000
    assert parsed.proposal_wall_seconds == 28_800.0


def test_descendant_node_cli_accepts_one_feedback_only_diagnostic(
    tmp_path: Path,
) -> None:
    diagnostic_state = str(tmp_path / ".agent-world-live" / "test-node-source")
    parsed = build_parser().parse_args(
        [
            "test-descendant-node",
            "generate-job:test-node",
            "build.candidate_build.environment_candidate",
            "--diagnostic-state-root",
            diagnostic_state,
            "--manifest-revision",
            "sha256:" + "b" * 64,
            "--diagnostic-terminal-feedback",
        ]
    )

    assert parsed.diagnostic_terminal_feedback is True
    assert parsed.infrastructure_retry is False
    assert parsed.manifest_revision == "sha256:" + "b" * 64
    assert parsed.proposal_llm_tokens is None
    assert parsed.proposal_wall_seconds is None


def test_descendant_node_cli_accepts_one_profile_transport_overlay(
    tmp_path: Path,
) -> None:
    parsed = build_parser().parse_args(
        [
            "test-descendant-node",
            "generate-job:test-node",
            "build.candidate_build.environment_candidate",
            "--diagnostic-state-root",
            str(tmp_path / ".agent-world-live" / "test-node-source"),
            "--diagnostic-structured-output-transport",
            "json_object",
        ]
    )

    assert parsed.diagnostic_structured_output_transport == "json_object"
    assert parsed.infrastructure_retry is False
    assert parsed.diagnostic_terminal_feedback is False


def test_descendant_node_cli_accepts_one_model_only_profile_overlay(
    tmp_path: Path,
) -> None:
    parsed = build_parser().parse_args(
        [
            "test-descendant-node",
            "generate-job:test-node",
            "build.candidate_build.environment_candidate",
            "--diagnostic-state-root",
            str(tmp_path / ".agent-world-live" / "test-node-source"),
            "--diagnostic-source-model",
            "gpt-5.4-mini",
            "--diagnostic-model",
            "gpt-5.3-codex-spark",
        ]
    )

    assert parsed.diagnostic_source_model == "gpt-5.4-mini"
    assert parsed.diagnostic_model == "gpt-5.3-codex-spark"
    assert parsed.diagnostic_structured_output_transport is None


def test_world_plan_node_cli_requires_one_marked_legacy_diagnostic_root(
    tmp_path: Path,
) -> None:
    diagnostic_state = str(tmp_path / ".agent-world-live" / "test-node-legacy-world")
    parsed = build_parser().parse_args(
        [
            "test-world-plan-node",
            "generate-job:test-node",
            "--diagnostic-state-root",
            diagnostic_state,
        ]
    )

    assert parsed.command == "test-world-plan-node"
    assert parsed.scope_id == "generate-job:test-node"
    assert parsed.diagnostic_state_root == diagnostic_state


def test_world_plan_node_cli_accepts_one_exact_legacy_manifest_selector(
    tmp_path: Path,
) -> None:
    diagnostic_state = str(tmp_path / ".agent-world-live" / "test-node-legacy-world")
    revision = "sha256:" + "c" * 64
    parsed = build_parser().parse_args(
        [
            "test-world-plan-node",
            "generate-job:test-node",
            "--diagnostic-state-root",
            diagnostic_state,
            "--manifest-revision",
            revision,
        ]
    )

    assert parsed.manifest_revision == revision


def test_task_requirement_node_cli_requires_one_committed_plan_root(
    tmp_path: Path,
) -> None:
    diagnostic_state = str(tmp_path / ".agent-world-live" / "test-node-world-plan")
    parsed = build_parser().parse_args(
        [
            "test-task-requirement-node",
            "generate-job:test-node",
            "todo.add_task",
            "--diagnostic-state-root",
            diagnostic_state,
        ]
    )

    assert parsed.command == "test-task-requirement-node"
    assert parsed.scope_id == "generate-job:test-node"
    assert parsed.task_type == "todo.add_task"
    assert parsed.diagnostic_state_root == diagnostic_state


def test_task_curriculum_join_cli_requires_one_completed_plan_derived_root(
    tmp_path: Path,
) -> None:
    diagnostic_state = str(tmp_path / ".agent-world-live" / "test-node-plan-derived-design")
    parsed = build_parser().parse_args(
        [
            "test-task-curriculum-join",
            "generate-job:test-node",
            "--diagnostic-state-root",
            diagnostic_state,
        ]
    )

    assert parsed.command == "test-task-curriculum-join"
    assert parsed.scope_id == "generate-job:test-node"
    assert parsed.diagnostic_state_root == diagnostic_state


def test_plan_derived_design_node_cli_selects_only_one_closed_tail_stage(
    tmp_path: Path,
) -> None:
    diagnostic_state = str(tmp_path / ".agent-world-live" / "test-node-plan-derived-design")
    parsed = build_parser().parse_args(
        [
            "test-plan-derived-design-node",
            "generate-job:test-node",
            "modeling_boundary",
            "--diagnostic-state-root",
            diagnostic_state,
        ]
    )

    assert parsed.command == "test-plan-derived-design-node"
    assert parsed.scope_id == "generate-job:test-node"
    assert parsed.target_stage == "modeling_boundary"
    assert parsed.diagnostic_state_root == diagnostic_state


def test_final_node_cli_selects_one_frozen_initial_batch(
    tmp_path: Path,
) -> None:
    diagnostic_state = str(tmp_path / ".agent-world-live" / "test-node-plan-derived-design")
    parsed = build_parser().parse_args(
        [
            "test-final-node",
            "generate-job:test-node",
            "verifier_intent_batch",
            "--batch-index",
            "2",
            "--diagnostic-state-root",
            diagnostic_state,
        ]
    )

    assert parsed.command == "test-final-node"
    assert parsed.scope_id == "generate-job:test-node"
    assert parsed.target_stage == "verifier_intent_batch"
    assert parsed.batch_index == 2
    assert parsed.diagnostic_state_root == diagnostic_state
    assert parsed.proposal_llm_tokens is None
    assert parsed.proposal_wall_seconds is None


def test_final_node_cli_accepts_one_explicit_long_diagnostic_envelope(
    tmp_path: Path,
) -> None:
    diagnostic_state = str(tmp_path / ".agent-world-live" / "test-node-plan-derived-design")
    parsed = build_parser().parse_args(
        [
            "test-final-node",
            "generate-job:test-node",
            "implementation_plan",
            "--diagnostic-state-root",
            diagnostic_state,
            "--proposal-llm-tokens",
            "5000000",
            "--proposal-wall-seconds",
            "28800",
        ]
    )

    assert parsed.proposal_llm_tokens == 5_000_000
    assert parsed.proposal_wall_seconds == 28_800.0


def test_final_node_long_envelope_is_finite_and_bounded_by_generation_budget() -> None:
    source = SimpleNamespace(
        proposal_policy=SimpleNamespace(
            executor="agent",
            budget=Budget(llm_tokens=16_384, wall_seconds=300),
        )
    )
    generation_budget = Budget(llm_tokens=10_000_000, wall_seconds=28_800)

    assert FinalNodeRunner._proposal_envelope(
        source_definition=source,  # type: ignore[arg-type]
        requested_llm_tokens=5_000_000,
        requested_wall_seconds=28_800,
        diagnostic_budget=generation_budget,
    ) == (5_000_000, 28_800.0)
    with pytest.raises(NodeError, match="exceeds the configured generation budget"):
        FinalNodeRunner._proposal_envelope(
            source_definition=source,  # type: ignore[arg-type]
            requested_llm_tokens=10_000_001,
            requested_wall_seconds=None,
            diagnostic_budget=generation_budget,
        )


def test_descendant_node_long_envelope_is_finite_and_bounded_by_generation_budget() -> None:
    source = SimpleNamespace(
        proposal_policy=SimpleNamespace(
            executor="agent",
            budget=Budget(llm_tokens=64_000, wall_seconds=1_200),
        )
    )
    generation_budget = Budget(llm_tokens=10_000_000, wall_seconds=28_800)

    assert DescendantRunner._proposal_envelope(
        source_definition=source,  # type: ignore[arg-type]
        requested_llm_tokens=5_000_000,
        requested_wall_seconds=28_800,
        diagnostic_budget=generation_budget,
    ) == (5_000_000, 28_800.0)
    with pytest.raises(NodeError, match="may not decrease"):
        DescendantRunner._proposal_envelope(
            source_definition=source,  # type: ignore[arg-type]
            requested_llm_tokens=63_999,
            requested_wall_seconds=None,
            diagnostic_budget=generation_budget,
        )


def test_test_node_execution_envelope_distinguishes_turn_from_logical_session() -> None:
    definition = SimpleNamespace(
        proposal_policy=SimpleNamespace(
            budget=Budget(llm_tokens=125_000, wall_seconds=720),
            session_token_limit=5_000_000,
            session_wall_seconds=28_800,
        ),
        repair_policy=SimpleNamespace(maximum_session_continuations=39),
    )

    envelope = NodeRunner._proposal_execution_envelope(  # noqa: SLF001 - CLI view projection
        definition  # type: ignore[arg-type]
    )

    assert envelope.physical_turn_llm_tokens == 125_000
    assert envelope.physical_turn_wall_seconds == 720
    assert envelope.logical_session_token_limit == 5_000_000
    assert envelope.logical_session_wall_seconds == 28_800
    assert envelope.maximum_session_continuations == 39


def test_final_node_target_selection_binds_one_physical_batch() -> None:
    scope_id = "generate-job:test-node"
    implementation_plan = WorkCoordinate(
        scope_id=scope_id,
        component="build",
        stage="implementation_plan",
        artifact_slot="implementation_plan",
    )
    first_batch = WorkCoordinate(
        scope_id=scope_id,
        component="verifier",
        stage="verifier_intent_batch",
        artifact_slot="verifier_intent_checkpoint",
        group_id="verifier-intent-batches",
        shard_id="batch-1",
    )
    second_batch = first_batch.model_copy(update={"shard_id": "batch-2"})
    graph = SimpleNamespace(
        definitions=tuple(
            SimpleNamespace(coordinate=coordinate)
            for coordinate in (implementation_plan, first_batch, second_batch)
        )
    )
    plan = SimpleNamespace(batches=(object(), object()))

    assert (
        FinalNodeRunner._initial_target(
            final_graph=graph,  # type: ignore[arg-type]
            verifier_plan=plan,  # type: ignore[arg-type]
            target_stage="implementation_plan",
            batch_index=None,
        )
        == implementation_plan
    )
    assert (
        FinalNodeRunner._initial_target(
            final_graph=graph,  # type: ignore[arg-type]
            verifier_plan=plan,  # type: ignore[arg-type]
            target_stage="verifier_intent_batch",
            batch_index=2,
        )
        == second_batch
    )
    with pytest.raises(NodeError, match="1-based index"):
        FinalNodeRunner._initial_target(
            final_graph=graph,  # type: ignore[arg-type]
            verifier_plan=plan,  # type: ignore[arg-type]
            target_stage="verifier_intent_batch",
            batch_index=3,
        )


@pytest.mark.asyncio
async def test_registry_publication_leaf_fails_closed_in_diagnostic_runtime(tmp_path: Path) -> None:
    class NoRegistryWrite:
        def __init__(self) -> None:
            self.reserve_calls = 0

        def reserve_package_version(self, *args: object, **kwargs: object) -> object:
            self.reserve_calls += 1
            raise AssertionError("diagnostic execution must not reserve a Registry version")

    class DiagnosticKernel:
        runtime = SimpleNamespace(diagnostic_only=True)

        async def execute(self, context, *, definition, proposal_runner) -> None:
            await proposal_runner(context, object(), "diagnostic-dispatch")

    registry = NoRegistryWrite()
    leaf = RegistryPublicationLeaf(
        builder=object(),  # type: ignore[arg-type]
        registry=registry,  # type: ignore[arg-type]
        workspace_root=tmp_path,
        kernel=DiagnosticKernel(),  # type: ignore[arg-type]
    )

    with pytest.raises(LeafExecutionFailure) as raised:
        await leaf.execute(object(), definition=object())  # type: ignore[arg-type]

    assert raised.value.code == "diagnostic_registry_publication_forbidden"
    assert raised.value.retryable is False
    assert registry.reserve_calls == 0
