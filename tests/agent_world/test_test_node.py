"""T0 evidence for isolated, real single-node WorkGraph execution."""

from __future__ import annotations

import asyncio
import hashlib
import os
from dataclasses import dataclass
from datetime import UTC, datetime
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
    BudgetUsage,
    EnvironmentJob,
    EnvironmentRequest,
    GenerationContext,
    PermissionScope,
    ReleaseProfile,
    canonical_json_bytes,
    sha256_digest,
)
from agent_world.control import (
    ArtifactSlotContract,
    ContinuationStoreError,
    FeedbackEvaluation,
    GenerationWorkGraph,
    LeaseBudgetLedger,
    ParentRepairRoute,
    RepairAction,
    ValidationIssue,
    ValidationReport,
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
    structured_agent_work_definition,
    world_architecture_work_definition,
)
from agent_world.control.leaf_executor import (
    AgentExecutionProvenance,
    LeafExecutionFailure,
    LeafProposal,
    LeafValidationFailure,
    LeafWorkspaceRecovery,
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
    _prepare_diagnostic_clone,
)
from agent_world.control.test_node import (
    DiagnosticSuccessorNodeRunner as SuccessorRunner,
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
from agent_world.control.work_store import WorkResumeError
from agent_world.invocation import InvocationStatus, InvocationTerminalFact
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
    graph: GenerationWorkGraph


def test_continuation_workspace_authority_is_one_marked_diagnostic_runs_root(
    tmp_path: Path,
) -> None:
    diagnostic_root = tmp_path / ".agent-world-live" / "test-node-source"
    work_control = WorkControlStore(diagnostic_root / "work-control")
    work_control.mark_test_node_diagnostic_clone()
    workspace = diagnostic_root / "runs" / "candidate" / ".agent-runtime" / "workspace"
    workspace.mkdir(parents=True)

    assert test_node_module._marked_diagnostic_runs_root(workspace) == (  # noqa: SLF001
        diagnostic_root / "runs"
    )

    unmarked_workspace = (
        tmp_path / ".agent-world-live" / "test-node-unmarked" / "runs" / "workspace"
    )
    unmarked_workspace.mkdir(parents=True)
    with pytest.raises(
        NodeError,
        match="does not belong to one exact marked diagnostic runs root",
    ):
        test_node_module._marked_diagnostic_runs_root(unmarked_workspace)  # noqa: SLF001


def test_snapshot_repair_uses_fresh_diagnostic_workspace_not_prior_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempt_ref = object()
    action_ref = object()
    coordinate = object()
    attempt = SimpleNamespace(
        # A successful Agent attempt retains this provenance commitment, but
        # the snapshot action below is the authority for a fresh-session repair.
        continuation_commitment="sha256:prior-agent-provenance",
    )
    action = SimpleNamespace(repair_seed_attempt_ref=object())

    class _Artifacts:
        @staticmethod
        def get_json(ref: object, model: object) -> object:
            if ref is action_ref and model is RepairAction:
                return action
            if ref is attempt_ref and model is WorkAttempt:
                return attempt
            raise AssertionError((ref, model))

    app = SimpleNamespace(
        controller=SimpleNamespace(
            work_control=SimpleNamespace(
                read_head=lambda requested: (
                    SimpleNamespace(
                        status="repair_authorized",
                        repair_action_ref=action_ref,
                        attempt_ref=attempt_ref,
                    )
                    if requested is coordinate
                    else None
                ),
            ),
            artifacts=_Artifacts(),
        ),
    )
    monkeypatch.setattr(
        test_node_module,
        "NodeContinuationStore",
        lambda *_args, **_kwargs: pytest.fail(
            "snapshot repair must not inspect the prior continuation store"
        ),
    )

    diagnostic_root = tmp_path / "fresh-diagnostic"
    assert (
        test_node_module._authorized_semantic_continuation_workspace_root(  # noqa: SLF001
            app=app,
            definition=SimpleNamespace(coordinate=coordinate),
            diagnostic_root=diagnostic_root,
        )
        == diagnostic_root / "runs"
    )


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
    *,
    repairable_target: bool = False,
    infrastructure_retryable_target: bool = False,
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
    if repairable_target:
        target = target.model_copy(
            update={
                "repair_policy": target.repair_policy.model_copy(
                    update={
                        "maximum_local_corrections": 1,
                        "strict_progress_bonus_corrections": 0,
                        "maximum_infrastructure_retries": 0,
                        "maximum_total_repair_attempts": 1,
                    }
                ),
                "allowed_mutation_roots": ("/candidate",),
            }
        )
    if infrastructure_retryable_target:
        target = target.model_copy(
            update={
                "repair_policy": target.repair_policy.model_copy(
                    update={
                        "maximum_infrastructure_retries": 1,
                        "maximum_total_repair_attempts": 1,
                    }
                )
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
        graph=graph,
    )


def test_final_graph_reconciliation_reuses_committed_definition_and_keeps_override_fresh(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R1.1/R1.2/R1.3: reconciliation reuses committed definitions but leaves an
    explicitly overridden target fresh.

    ``complete_generation_work_graph`` recompiles every final definition from
    live compiler functions, so a committed coordinate acquires a divergent
    ``definition_digest`` (fresh ``repair_policy`` / ``*_revision_id``) and the
    active-commit gate orphans the parent.  The diagnostic reconciliation must
    swap that fresh definition for the exact committed one, unless the caller
    intentionally overrides it (budget overlay), in which case it stays fresh.
    """

    captured = _capture_scope(tmp_path, monkeypatch)
    app = build_application(captured.config)
    committed_head = app.controller.work_control.read_head(captured.target_definition.coordinate)
    assert committed_head is not None and committed_head.status == "committed"

    # Mimic the live-compiler divergence: the same coordinate/work_id, but a
    # different repair_policy budget → a different definition_digest.
    divergent_target = captured.target_definition.model_copy(
        update={
            "repair_policy": captured.target_definition.repair_policy.model_copy(
                update={
                    "maximum_infrastructure_retries": 3,
                    "maximum_model_fallbacks": 2,
                    "maximum_total_repair_attempts": 13,
                }
            )
        }
    )
    assert divergent_target.definition_digest != committed_head.definition_digest

    fresh_definitions = tuple(
        divergent_target
        if definition.coordinate == captured.target_definition.coordinate
        else definition
        for definition in captured.graph.definitions
    )
    fresh_graph = GenerationWorkGraph.compile(
        fresh_definitions,
        mode=captured.graph.mode,
        strict_input_contracts=True,
        required_terminal_coordinates=captured.graph.required_terminal_coordinates,
        groups=captured.graph.groups,
        milestones=captured.graph.milestones,
    )

    runner = FinalNodeRunner(
        config=captured.config,
        diagnostic_state_root=captured.state_root,
    )

    # Passthrough: the committed coordinate reuses the committed definition.
    reconciled = runner._reconcile_final_graph_with_committed(  # noqa: SLF001
        app=app,
        scope_id=captured.scope_id,
        graph=fresh_graph,
    )
    reconciled_target = reconciled.require(captured.target_definition.coordinate)
    assert reconciled_target.definition_digest == committed_head.definition_digest
    assert reconciled_target.definition_digest != divergent_target.definition_digest

    # Overlay preservation (R1.3): an explicitly excluded target stays fresh.
    reconciled_override = runner._reconcile_final_graph_with_committed(  # noqa: SLF001
        app=app,
        scope_id=captured.scope_id,
        graph=fresh_graph,
        exclude_coordinates=(captured.target_definition.coordinate,),
    )
    assert (
        reconciled_override.require(captured.target_definition.coordinate).definition_digest
        == divergent_target.definition_digest
    )
    app.telemetry.close()


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


def test_diagnostic_successor_coordinate_feedback_lists_copyable_candidates() -> None:
    """A fresh derived graph must expose the coordinates a Code Agent can run."""

    scope_id = "generate-job:successor-coordinate-feedback"
    architecture = _definition(
        scope_id=scope_id,
        stage="world_architecture",
        dependencies=(),
    )
    shared = _definition(
        scope_id=scope_id,
        stage="shared_tool_semantics",
        dependencies=(architecture.coordinate,),
    )
    behavior = _definition(
        scope_id=scope_id,
        stage="world_behavior",
        dependencies=(shared.coordinate,),
    )
    graph = SimpleNamespace(definitions=(architecture, shared, behavior))

    with pytest.raises(NodeError) as raised:
        SuccessorRunner._resolve_fresh_semantic_coordinate(  # noqa: SLF001 - feedback seam
            graph,
            "design.world_behavior.tool_semantics_batch",
        )

    assert raised.value.code == "test_successor_coordinate_not_fresh_semantic"
    message = str(raised.value)
    assert "design|shared_tool_semantics|shared_tool_semantics||" in message
    assert "design|world_behavior|world_behavior||" in message


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
    """A code/Prompt/Skill refresh preserves its frozen Agent model lineage."""

    captured = _capture_scope(tmp_path, monkeypatch)
    updated_implementation = "framework.test-node-current-implementation.v1"
    updated_validator = "framework.test-node-current-validator.v1"
    inherited_model = "gpt-5.4-mini"
    monkeypatch.setattr(
        test_node_module,
        "current_runtime_revisions_for_definition",
        lambda definition: (
            (updated_implementation, updated_validator)
            if definition.coordinate == captured.target_definition.coordinate
            else None
        ),
    )
    monkeypatch.setattr(
        test_node_module,
        "_inherited_diagnostic_runtime_profile_config",
        lambda *, app, manifest_ref, definition, config: (
            config.model_copy(
                update={
                    "agent": config.agent.model_copy(
                        update={"model": inherited_model, "fallback_models": ()}
                    )
                }
            ),
            (SimpleNamespace(model=inherited_model),),
        ),
    )
    dispatched_definitions: list[WorkDefinition] = []

    def executor_factory(execution: NodeExecution):
        async def execute(context) -> None:
            assert execution.app.config.agent.model == inherited_model
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
    assert override.source_proposal_budget == captured.target_definition.proposal_policy.budget
    assert override.proposal_budget == captured.target_definition.proposal_policy.budget
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
    """A model experiment becomes a new epoch, not a hidden config retry."""

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
        model="gpt-5.4-mini",
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
    assert override.model == "gpt-5.4-mini"
    assert override.implementation_revision_id == (
        overlay.definition.proposal_policy.implementation_revision_id
    )
    assert override.diagnostic_only is True
    assert override.releasable is False
    inherited_config, inherited_overrides = (
        test_node_module._inherited_diagnostic_runtime_profile_config(  # noqa: SLF001
            app=app,
            manifest_ref=overlay.manifest_ref,
            definition=overlay.definition,
            config=captured.config,
        )
    )
    assert inherited_overrides == (override,)
    assert inherited_config.agent.model == "gpt-5.4-mini"
    assert inherited_config.agent.model_routes == (
        "gpt-5.4-mini",
        captured.config.agent.model,
    )


def test_test_node_reconstructs_legacy_definition_without_implicit_model_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A newly added retry field must not invalidate frozen historical graphs."""

    captured = _capture_scope(tmp_path, monkeypatch)
    app = build_application(captured.config)
    artifacts = app.controller.artifacts
    manifest_ref = next(
        ref
        for ref in artifacts.list_revisions()
        if ref.artifact_type == "control.work_graph_manifest"
    )
    source_manifest = artifacts.get_json(manifest_ref, WorkGraphManifest)

    # Model the exact historic wire shape: the field did not exist, rather
    # than representing an explicit zero in a current graph.
    legacy_raw = captured.target_definition.model_dump(mode="python")
    legacy_raw["repair_policy"].pop("maximum_model_fallbacks", None)
    legacy_definition = WorkDefinition.model_validate(legacy_raw)
    assert legacy_definition.repair_policy.maximum_model_fallbacks == 0
    assert (
        "maximum_model_fallbacks" not in legacy_definition.model_dump(mode="json")["repair_policy"]
    )

    legacy_ref = artifacts.put_json(
        artifact_id="work-definition:legacy-no-model-fallback",
        artifact_type="control.work_definition",
        value=legacy_definition,
    )
    assert legacy_ref.content_hash == legacy_definition.definition_digest
    manifest = source_manifest.model_copy(
        update={
            "node_bindings": tuple(
                binding.model_copy(update={"definition_digest": legacy_ref.content_hash})
                if binding.coordinate == captured.target_definition.coordinate
                else binding
                for binding in source_manifest.node_bindings
            )
        }
    )

    reconstructed = NodeRunner._reconstruct_graph(  # noqa: SLF001 - frozen closure proof
        artifacts,
        manifest,
    )
    recovered = reconstructed.require(captured.target_definition.coordinate)
    assert recovered.definition_digest == legacy_ref.content_hash
    assert recovered.repair_policy.maximum_model_fallbacks == 0


def test_frozen_definition_catalog_preserves_exact_manifest_reconstruction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One cached catalog is equivalent to per-binding immutable lookup."""

    captured = _capture_scope(tmp_path, monkeypatch)
    app = build_application(captured.config)
    artifacts = app.controller.artifacts
    manifest_ref = next(
        ref
        for ref in artifacts.list_revisions()
        if ref.artifact_type == "control.work_graph_manifest"
    )
    manifest = artifacts.get_json(manifest_ref, WorkGraphManifest)

    catalog = NodeRunner._definition_catalog(artifacts)  # noqa: SLF001 - exact lookup cache
    reconstructed = NodeRunner._reconstruct_graph(  # noqa: SLF001 - frozen closure proof
        artifacts,
        manifest,
        definition_catalog=catalog,
    )

    recovered = reconstructed.require(captured.target_definition.coordinate)
    assert recovered == captured.target_definition
    assert catalog[
        (
            recovered.coordinate.coordinate_key,
            recovered.work_id,
            recovered.definition_digest,
        )
    ] == (captured.target_definition,)


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
        source_model=captured.config.agent.model,
        model="gpt-5.3-codex-spark",
    )

    override = artifacts.get_json(overlay.override_ref, DiagnosticRuntimeProfileOverride)
    assert override.source_model == captured.config.agent.model
    assert override.model == "gpt-5.3-codex-spark"
    assert (
        overlay.definition.proposal_policy.implementation_revision_id
        != definition.proposal_policy.implementation_revision_id
    )
    inherited_config, inherited_overrides = (
        test_node_module._inherited_diagnostic_runtime_profile_config(  # noqa: SLF001
            app=app,
            manifest_ref=overlay.manifest_ref,
            definition=overlay.definition,
            config=captured.config,
        )
    )
    assert inherited_overrides == (override,)
    assert inherited_config.agent.model == "gpt-5.3-codex-spark"
    assert inherited_config.agent.model_routes == (
        "gpt-5.3-codex-spark",
        captured.config.agent.model,
    )


def test_inherited_profile_ignores_one_provable_duplicate_overlay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A repeated historic model wrapper must not block its frozen repair turn."""

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
    source = test_node_module._ProposalEnvelopeOverlaySource(  # noqa: SLF001
        graph=graph,
        manifest=manifest,
        manifest_ref=manifest_ref,
        definition=definition,
        context_ref=manifest.external_root_refs[0],
    )
    first = test_node_module._apply_diagnostic_runtime_profile_overlay(  # noqa: SLF001
        app=app,
        source=source,
        source_model=captured.config.agent.model,
        model="grok-4.5",
    )
    second = test_node_module._apply_diagnostic_runtime_profile_overlay(  # noqa: SLF001
        app=app,
        source=test_node_module._ProposalEnvelopeOverlaySource(  # noqa: SLF001
            graph=first.graph,
            manifest=first.manifest,
            manifest_ref=first.manifest_ref,
            definition=first.definition,
            context_ref=source.context_ref,
        ),
        source_model=captured.config.agent.model,
        model="grok-4.5",
    )

    inherited_config, inherited_overrides = (
        test_node_module._inherited_diagnostic_runtime_profile_config(  # noqa: SLF001
            app=app,
            manifest_ref=second.manifest_ref,
            definition=second.definition,
            config=captured.config,
        )
    )

    assert len(inherited_overrides) == 2
    assert inherited_config.agent.model == "grok-4.5"


def test_model_diagnostic_promotes_a_configured_fallback_without_duplicate_route(
    tmp_path: Path,
) -> None:
    """A model-only node diagnostic must remain executable after promotion."""

    config = _config(tmp_path)
    source_model = config.agent.model
    promoted_model = "gpt-5.3-codex-spark"
    configured = config.model_copy(
        update={
            "agent": config.agent.model_copy(
                update={"fallback_models": (promoted_model, "gpt-5.4-mini")}
            )
        }
    )

    change = test_node_module._diagnostic_runtime_profile_change(  # noqa: SLF001
        configured,
        diagnostic_model=promoted_model,
        diagnostic_source_model=source_model,
    )

    assert change.config.agent.model == promoted_model
    assert change.config.agent.fallback_models == (source_model, "gpt-5.4-mini")
    assert change.config.agent.model_routes == (
        promoted_model,
        source_model,
        "gpt-5.4-mini",
    )
    # The captured/live configuration itself stays untouched; only the
    # isolated diagnostic application receives the normalized route list.
    assert configured.agent.model == source_model
    assert configured.agent.fallback_models == (promoted_model, "gpt-5.4-mini")


def test_terminal_retry_preserves_only_later_configured_model_routes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A proved retry route keeps its declared successors for later fallback."""

    base = _config(tmp_path)
    config = base.model_copy(
        update={
            "agent": base.agent.model_copy(
                update={
                    "model": "gpt-5.4-mini",
                    "fallback_models": ("gpt-5.3-codex-spark", "grok-4.5"),
                }
            )
        }
    )
    app = SimpleNamespace(
        controller=SimpleNamespace(artifacts=SimpleNamespace(get_json=lambda _ref, _type: object()))
    )
    monkeypatch.setattr(
        test_node_module.TestNodeRunner,
        "_proposal_executions",
        lambda _artifacts, _attempt: (SimpleNamespace(model="gpt-5.3-codex-spark"),),
    )

    retried = test_node_module._diagnostic_terminal_profile_config(  # noqa: SLF001
        app=app,
        retry_head=SimpleNamespace(attempt_ref=object()),
        config=config,
    )

    assert retried.agent.model == "gpt-5.3-codex-spark"
    assert retried.agent.fallback_models == ("grok-4.5",)
    assert config.agent.model_routes == ("gpt-5.4-mini", "gpt-5.3-codex-spark", "grok-4.5")


@pytest.mark.asyncio
async def test_test_node_nonterminal_scheduler_error_rebuilds_fresh_running_scene(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A harness failure cannot inherit a stale successful scene from its parent."""

    captured = _capture_scope(tmp_path, monkeypatch)
    diagnostic_parent = tmp_path / ".agent-world-live"

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
async def test_diagnostic_descendant_runtime_refresh_reauthorizes_settled_causal_repair(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A Prompt/Skill revision derives new repair authority from settled evidence.

    This is the true Scheduler boundary for a real bad-case shape: a candidate
    first completed one precise semantic correction, but a causal runtime
    implementation revision needs another turn. The refreshed attempt retains
    its immutable parent closure, source snapshot, and exact downstream
    feedback while receiving neither the old RepairAction nor its private
    continuation binding.
    """

    captured = _capture_scope(tmp_path, monkeypatch)
    diagnostic_parent = tmp_path / ".agent-world-live"

    def parent_executor_factory(execution: NodeExecution):
        async def execute(context) -> None:
            input_refs = tuple(
                dict.fromkeys((*context.external_input_refs, *context.parent_output_refs))
            )
            output_ref = execution.app.controller.artifacts.put_json(
                artifact_id=f"repair-refresh-parent:{execution.run_id}",
                artifact_type="design.test_node_target",
                value={"source": "diagnostic-parent-for-runtime-refresh"},
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
    source_graph = NodeRunner._reconstruct_graph(  # noqa: SLF001 - frozen test closure setup
        parent_artifacts,
        source_manifest,
    )
    repair_successor = source_graph.require(captured.successor_definition.coordinate).model_copy(
        update={
            "repair_policy": captured.successor_definition.repair_policy.model_copy(
                update={
                    "maximum_local_corrections": 1,
                    "strict_progress_bonus_corrections": 0,
                    "maximum_infrastructure_retries": 0,
                    "maximum_total_repair_attempts": 1,
                }
            ),
            "allowed_mutation_roots": ("/candidate",),
        }
    )
    repair_graph = GenerationWorkGraph.compile(
        tuple(
            repair_successor if definition.coordinate == repair_successor.coordinate else definition
            for definition in source_graph.definitions
        ),
        mode="diagnostic",
        strict_input_contracts=True,
    )
    context_ref = next(
        ref
        for ref in source_manifest.external_root_refs
        if ref.artifact_type == "control.generation_context"
    )
    repair_manifest, repair_manifest_ref, _repair_epoch, _repair_epoch_ref = WorkGraphEpochRuntime(
        artifacts=parent_artifacts,
        heads=parent_app.controller.work_control,
    ).freeze_bootstrap(
        context_ref=context_ref,
        graph=repair_graph,
        topology_id="topology:test-node-runtime-refresh-from-repair",
    )

    def committed_executor_factory(execution: NodeExecution):
        async def execute(context) -> None:
            input_refs = tuple(
                dict.fromkeys((*context.external_input_refs, *context.parent_output_refs))
            )
            output_ref = execution.app.controller.artifacts.put_json(
                artifact_id=f"repair-refresh-committed:{execution.run_id}",
                artifact_type="design.test_node_successor",
                value={"source": "candidate-before-causal-repair"},
                dependencies=input_refs,
            )
            execution.runtime.execute_deterministic_boundary(
                definition=execution.definition,
                input_refs=input_refs,
                subject_ref=output_ref,
                output_refs=(output_ref,),
            )

        return execute

    committed = await DescendantRunner(
        config=captured.config,
        diagnostic_state_root=parent_root,
        diagnostic_parent=diagnostic_parent,
        executor_factory=committed_executor_factory,
    ).run(
        scope_id=captured.scope_id,
        target_coordinate=repair_successor.coordinate.coordinate_key,
        required_manifest_ref=repair_manifest_ref,
    )
    assert committed.status == "committed"
    committed_root = Path(committed.diagnostic_state_root)
    committed_app = build_application(
        captured.config.model_copy(update={"state_root": committed_root})
    )
    committed_artifacts = committed_app.controller.artifacts
    committed_head = committed_app.controller.work_control.read_head(repair_successor.coordinate)
    assert committed_head is not None and committed_head.status == "committed"
    committed_attempt = committed_artifacts.get_json(committed_head.attempt_ref, WorkAttempt)

    source_coordinate = WorkCoordinate(
        scope_id=captured.scope_id,
        component="integration",
        stage="runtime_integration",
        artifact_slot="integration_report",
    )
    source_issue = ValidationIssue(
        code="test_runtime_refresh_role_visibility",
        path=("candidate", "role_visibility"),
        violated_condition="the source candidate violated one visible-role rule",
        expected_category="one candidate satisfying the declared visible-role rule",
        remediation="Regenerate after the recorded runtime guidance revision.",
    )
    source_report = ValidationReport(
        report_id="validation-report:test-descendant-runtime-refresh-source",
        attempt_id="attempt:test-descendant-runtime-refresh-source",
        coordinate=source_coordinate,
        policy_id="validation:test-descendant-runtime-refresh-source",
        policy_digest=sha256_digest(b"test-descendant-runtime-refresh-source-policy"),
        status="failed",
        validation_phase="runtime_integration",
        frontier_ordinal=100,
        issues=(source_issue,),
        diagnostic_quality="actionable",
        diagnostic_only=True,
        releasable=False,
        evaluated_at=datetime.now(UTC),
    )
    source_report_ref = committed_artifacts.put_json(
        artifact_id=source_report.report_id,
        artifact_type="control.validation_report",
        value=source_report,
        dependencies=committed_attempt.input_refs,
    )
    source_evaluation = FeedbackEvaluation(
        evaluation_id="evaluation:test-descendant-runtime-refresh-source",
        attempt_id=source_report.attempt_id,
        work_id="work:test-descendant-runtime-refresh-source",
        coordinate=source_coordinate,
        claim_id="test-descendant-runtime-refresh-source.claim",
        acceptance_digest=sha256_digest(b"test-descendant-runtime-refresh-source-acceptance"),
        policy_digest=source_report.policy_digest,
        status="failed",
        effect="block_release",
        readiness_effect="observes",
        validation_report_ref=source_report_ref,
        diagnostic_only=True,
        releasable=False,
        evaluated_at=datetime.now(UTC),
    )
    source_evaluation_ref = committed_artifacts.put_json(
        artifact_id=source_evaluation.evaluation_id,
        artifact_type="control.feedback_evaluation",
        value=source_evaluation,
        dependencies=(source_report_ref,),
    )
    route = ParentRepairRoute(
        route_id="parent-repair-route:test-descendant-runtime-refresh",
        source_coordinate=source_coordinate,
        source_attempt_id=source_report.attempt_id,
        source_definition_digest=sha256_digest(
            b"test-descendant-runtime-refresh-source-definition"
        ),
        target_coordinate=repair_successor.coordinate,
        issue_identities=(source_issue.normalized_identity,),
        routed_at=datetime.now(UTC),
    )
    route_ref = committed_artifacts.put_json(
        artifact_id=route.route_id,
        artifact_type="control.parent_repair_route",
        value=route,
        dependencies=(source_report_ref, source_evaluation_ref),
    )
    causal_runtime = WorkControlRuntime(
        artifacts=committed_artifacts,
        heads=committed_app.controller.work_control,
        budget=LeaseBudgetLedger(committed.reserved_budget),
        telemetry=committed_app.telemetry,
        projector=committed_app.controller.scene_projector,
        trace_id="test-descendant-runtime-refresh-causal-authority",
        run_id="test-descendant-runtime-refresh-causal-authority",
        diagnostic_only=True,
        repair_scope_id=captured.scope_id,
    )
    with committed_app.controller.work_control.exclusive(repair_successor.coordinate) as lock:
        authorized_head = causal_runtime.authorize_causal_repair(
            lock,
            definition=repair_successor,
            input_refs=committed_attempt.input_refs,
            source_evaluation_ref=source_evaluation_ref,
            source_report_ref=source_report_ref,
            route_ref=route_ref,
        )
    assert authorized_head.status == "repair_authorized"
    assert authorized_head.repair_action_ref is not None
    old_repair_action_ref = authorized_head.repair_action_ref

    assert (
        WorkControlStore(committed_root / "work-control").read_head(repair_successor.coordinate)
        == authorized_head
    )

    with pytest.raises(NodeError) as exact_repair:
        await DescendantRunner(
            config=captured.config,
            diagnostic_state_root=committed_root,
            diagnostic_parent=diagnostic_parent,
        ).run(
            scope_id=captured.scope_id,
            target_coordinate=repair_successor.coordinate.coordinate_key,
            required_manifest_ref=repair_manifest_ref,
        )
    assert exact_repair.value.code == "test_descendant_authorized_repair_requires_runtime_refresh"

    repair_actions_seen: list[ArtifactRef | None] = []

    def authorized_repair_executor_factory(execution: NodeExecution):
        async def execute(context) -> None:
            repair_actions_seen.append(context.repair_action_ref)
            input_refs = tuple(
                dict.fromkeys((*context.external_input_refs, *context.parent_output_refs))
            )
            output_ref = execution.app.controller.artifacts.put_json(
                artifact_id=f"repair-executed:{execution.run_id}",
                artifact_type="design.test_node_successor",
                value={"source": "one-authorized-scheduler-repair"},
                dependencies=input_refs,
            )
            execution.runtime.execute_deterministic_boundary(
                definition=execution.definition,
                input_refs=input_refs,
                subject_ref=output_ref,
                output_refs=(output_ref,),
            )

        return execute

    executed_repair = await DescendantRunner(
        config=captured.config,
        diagnostic_state_root=committed_root,
        diagnostic_parent=diagnostic_parent,
        executor_factory=authorized_repair_executor_factory,
    ).run(
        scope_id=captured.scope_id,
        target_coordinate=repair_successor.coordinate.coordinate_key,
        required_manifest_ref=repair_manifest_ref,
        execute_authorized_repair=True,
    )

    assert executed_repair.status == "committed"
    assert executed_repair.authorized_repair_action_ref == old_repair_action_ref
    assert repair_actions_seen == [old_repair_action_ref]
    executed_artifacts = ArtifactStore(Path(executed_repair.diagnostic_state_root) / "artifacts")
    executed_attempt = executed_artifacts.get_json(executed_repair.target_attempt_ref, WorkAttempt)
    assert executed_attempt.parent_attempt_id == committed_attempt.attempt_id
    assert executed_attempt.repair_action_ref == old_repair_action_ref
    # The original diagnostic copy remains evidence with its own untouched
    # authority, so a separate runtime-refresh experiment can still start from
    # the same bad case rather than a mutated test fixture.
    assert (
        WorkControlStore(committed_root / "work-control").read_head(repair_successor.coordinate)
        == authorized_head
    )

    updated_implementation = "framework.test-descendant-runtime-refresh.v1"
    updated_validator = "framework.test-descendant-validator-refresh.v1"
    monkeypatch.setattr(
        test_node_module,
        "current_runtime_revisions_for_definition",
        lambda definition: (
            (updated_implementation, updated_validator)
            if definition.coordinate == repair_successor.coordinate
            else None
        ),
    )
    seen_repair_actions: list[ArtifactRef | None] = []

    def regeneration_executor_factory(execution: NodeExecution):
        async def execute(context) -> None:
            seen_repair_actions.append(context.repair_action_ref)
            input_refs = tuple(
                dict.fromkeys((*context.external_input_refs, *context.parent_output_refs))
            )
            output_ref = execution.app.controller.artifacts.put_json(
                artifact_id=f"repair-refresh-regenerated:{execution.run_id}",
                artifact_type="design.test_node_successor",
                value={"source": "fresh-runtime-revision-regeneration"},
                dependencies=input_refs,
            )
            execution.runtime.execute_deterministic_boundary(
                definition=execution.definition,
                input_refs=input_refs,
                subject_ref=output_ref,
                output_refs=(output_ref,),
            )

        return execute

    regenerated = await DescendantRunner(
        config=captured.config,
        diagnostic_state_root=Path(executed_repair.diagnostic_state_root),
        diagnostic_parent=diagnostic_parent,
        executor_factory=regeneration_executor_factory,
    ).run(
        scope_id=captured.scope_id,
        target_coordinate=repair_successor.coordinate.coordinate_key,
        required_manifest_ref=repair_manifest_ref,
        refresh_current_implementation=True,
    )

    assert regenerated.status == "committed"
    assert regenerated.runtime_implementation_override_ref is not None
    assert regenerated.superseded_stale_attempt_ref == executed_repair.target_attempt_ref
    assert regenerated.superseded_stale_definition_digest == repair_successor.definition_digest
    assert regenerated.superseded_authorized_repair_action_ref is None
    assert regenerated.authorized_repair_action_ref is not None
    assert regenerated.authorized_repair_action_ref != old_repair_action_ref
    assert seen_repair_actions == [regenerated.authorized_repair_action_ref]
    regenerated_artifacts = ArtifactStore(Path(regenerated.diagnostic_state_root) / "artifacts")
    regenerated_attempt = regenerated_artifacts.get_json(
        regenerated.target_attempt_ref,
        WorkAttempt,
    )
    refreshed_action = regenerated_artifacts.get_json(
        regenerated.authorized_repair_action_ref,
        RepairAction,
    )
    regenerated_head = WorkControlStore(
        Path(regenerated.diagnostic_state_root) / "work-control"
    ).read_head(repair_successor.coordinate)
    old_action = committed_artifacts.get_json(old_repair_action_ref, RepairAction)
    assert regenerated_attempt.parent_attempt_id == executed_attempt.attempt_id
    assert regenerated_attempt.repair_action_ref == regenerated.authorized_repair_action_ref
    assert regenerated_attempt.definition_digest == refreshed_action.definition_digest
    assert regenerated_head is not None
    assert regenerated_head.definition_digest == refreshed_action.definition_digest
    assert refreshed_action.definition_digest != old_action.definition_digest
    assert refreshed_action.causal_evidence_refs == (
        source_evaluation_ref,
        source_report_ref,
        route_ref,
    )


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
async def test_diagnostic_descendant_recovers_nested_private_candidate_drafts_in_fresh_sessions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each copied diagnostic child may inspect, but never adopt, its parent's draft.

    The first descendant executes a real Scheduler boundary and creates normal
    files under its private ``runs/`` workspace before a classified Provider
    terminal.  The next descendant receives neither that directory nor an old
    Provider thread; its sole authority is the action-bound private recovery
    record copied with the durable diagnostic control state.  If that fresh
    child itself receives a transport terminal after writing more files, its
    new draft belongs to the child rather than to its source root.
    """

    captured = _capture_scope(tmp_path, monkeypatch)
    diagnostic_parent = tmp_path / ".agent-world-live"

    def parent_executor_factory(execution: NodeExecution):
        async def execute(context) -> None:
            input_refs = tuple(
                dict.fromkeys((*context.external_input_refs, *context.parent_output_refs))
            )
            output_ref = execution.app.controller.artifacts.put_json(
                artifact_id=f"workspace-recovery-parent:{execution.run_id}",
                artifact_type="design.test_node_target",
                value={"source": "diagnostic-parent-for-workspace-recovery"},
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
    artifacts = parent_app.controller.artifacts
    source_manifest_ref = next(
        ref
        for ref in artifacts.list_revisions()
        if ref.artifact_type == "control.work_graph_manifest"
    )
    source_manifest = artifacts.get_json(source_manifest_ref, WorkGraphManifest)
    source_graph = NodeRunner._reconstruct_graph(  # noqa: SLF001 - frozen setup
        artifacts,
        source_manifest,
    )
    candidate = structured_agent_work_definition(
        scope_id=captured.scope_id,
        component="build",
        stage="candidate_build",
        artifact_slot="candidate_build",
        dependency_coordinates=(captured.target_definition.coordinate,),
        claim_id="builder.candidate.completes",
        claim="A fresh Engineer session may inspect one untrusted private draft.",
        timing_reason="A Provider capacity terminal cannot adopt an incomplete Candidate.",
        output_contract_id="contract:diagnostic-candidate-build.v1",
        allowed_mutation_roots=("/candidate",),
        agent_wall_seconds=60,
        agent_token_limit=1_000,
        maximum_local_corrections=1,
        strict_progress_bonus_corrections=0,
        maximum_infrastructure_retries=2,
        maximum_model_fallbacks=0,
        maximum_total_repair_attempts=3,
        input_slots=(
            ArtifactSlotContract(
                slot_id="input:diagnostic-target",
                direction="input",
                artifact_types=("design.test_node_target",),
                minimum_count=1,
                maximum_count=1,
                producer_component="design",
            ),
        ),
        output_slots=(
            ArtifactSlotContract(
                slot_id="output:candidate-build",
                direction="output",
                artifact_types=("design.candidate_build",),
                minimum_count=1,
                maximum_count=1,
                producer_component="build",
            ),
        ),
    )
    graph = GenerationWorkGraph.compile(
        (
            source_graph.require(captured.parent_coordinate),
            source_graph.require(captured.target_definition.coordinate),
            candidate,
        ),
        mode="diagnostic",
        strict_input_contracts=True,
    )
    for definition in graph.definitions:
        artifacts.put_json(
            artifact_id=f"work-definition:{definition.work_id}",
            artifact_type="control.work_definition",
            value=definition,
            dependencies=source_manifest.external_root_refs,
        )
    manifest = graph.manifest(
        topology_id="topology:test-node-private-candidate-workspace-recovery",
        external_root_refs=source_manifest.external_root_refs,
    )
    manifest_ref = artifacts.put_json(
        artifact_id=manifest.graph_id,
        artifact_type="control.work_graph_manifest",
        value=manifest,
        dependencies=source_manifest.external_root_refs,
    )

    model = captured.config.agent.model
    profile_digest = sha256_digest(canonical_json_bytes({"profile": "diagnostic-engineer"}))
    config_digest = sha256_digest(canonical_json_bytes({"config": "diagnostic-engineer"}))
    schema_digest = sha256_digest(canonical_json_bytes({"schema": "candidate-completion"}))
    written_workspace: Path | None = None
    retried_workspace: Path | None = None

    def provenance(dispatch_id: str) -> AgentExecutionProvenance:
        return AgentExecutionProvenance(
            invocation_id=dispatch_id,
            provider="test-provider",
            model=model,
            profile_digest=profile_digest,
            output_schema_digest=schema_digest,
        )

    def failing_executor_factory(execution: NodeExecution):
        kernel = SchedulerLeafExecutor(runtime=execution.runtime)

        async def proposal(_context, attempt: WorkAttempt, dispatch_id: str) -> LeafProposal:
            nonlocal written_workspace
            workspace = execution.workspace_root
            (workspace / "candidate").mkdir(parents=True)
            (workspace / "candidate" / "runtime.py").write_text(
                "def draft_runtime(): return 'untrusted'\n",
                encoding="utf-8",
            )
            written_workspace = workspace.resolve()
            # The real InvocationControlPlane always leaves one redacted
            # terminal record for a dispatched Agent turn.  This realistic
            # leaf boundary deliberately bypasses the adapter to poison the
            # Scheduler failure path, so it must record that same settled
            # physical fact; otherwise the descendant's liveness gate rightly
            # rejects an unprovable retry before workspace recovery is reached.
            ownership = kernel.invocation_ownership(
                definition=execution.definition,
                attempt=attempt,
                dispatch_id=dispatch_id,
            )
            execution.app.invocation_control.begin(
                invocation_id=dispatch_id,
                owner=ownership,
                route="codex_sdk",
                model=model,
                profile_digest=profile_digest,
                envelope_digest="d" * 64,
                declared_wall_seconds=60,
            )
            execution.app.invocation_control.settle(
                dispatch_id,
                terminal=InvocationTerminalFact(
                    status=InvocationStatus.FAILED,
                    code="turn_failed_provider_unavailable",
                    retryable=True,
                ),
            )
            raise LeafExecutionFailure(
                code="agent_backend_turn_failed_provider_unavailable",
                category="the Provider closed after regular private Candidate files were written",
                retryable=True,
                observed_actual=BudgetUsage(llm_tokens=1_000, agent_turns=1),
                agent=provenance(dispatch_id),
                workspace_recovery=LeafWorkspaceRecovery(
                    workspace=workspace.resolve(),
                    lineage_id="implementation:diagnostic-private-draft",
                    profile_digest=profile_digest,
                    codex_config_digest=config_digest,
                    model=model,
                    output_schema_digest=schema_digest,
                ),
            )

        async def execute(context) -> None:
            await kernel.execute(context, definition=execution.definition, proposal_runner=proposal)

        return execute

    first = await DescendantRunner(
        config=captured.config,
        diagnostic_state_root=parent_root,
        diagnostic_parent=diagnostic_parent,
        executor_factory=failing_executor_factory,
    ).run(
        scope_id=captured.scope_id,
        target_coordinate=candidate.coordinate.coordinate_key,
        required_manifest_ref=manifest_ref,
    )
    assert first.status == "failed"
    assert written_workspace is not None
    first_root = Path(first.diagnostic_state_root)
    assert written_workspace.is_relative_to(first_root / "runs")

    def retried_failure_executor_factory(execution: NodeExecution):
        kernel = SchedulerLeafExecutor(runtime=execution.runtime)

        async def proposal(_context, attempt: WorkAttempt, dispatch_id: str) -> LeafProposal:
            nonlocal retried_workspace
            assert execution.app.config.agent.model == model
            assert attempt.continuation_commitment is not None
            assert execution.runtime.continuations is not None
            assert execution.runtime.continuation_workspace_root == first_root / "runs"
            record = execution.runtime.continuations.load_commitment(
                attempt.continuation_commitment,
                workspace_root=execution.runtime.continuation_workspace_root,
            )
            assert record is not None
            assert record.continuation_kind == "workspace_recovery"
            assert record.thread_id is None
            assert record.workspace_for_recovery() == written_workspace
            with pytest.raises(ContinuationStoreError, match="cannot resume a Provider thread"):
                record.restore_session()
            assert (
                (written_workspace / "candidate" / "runtime.py")
                .read_text(encoding="utf-8")
                .startswith("def draft_runtime")
            )
            workspace = execution.workspace_root
            (workspace / "candidate").mkdir(parents=True)
            (workspace / "candidate" / "runtime.py").write_text(
                "def recovered_draft_runtime(): return 'still-untrusted'\n",
                encoding="utf-8",
            )
            retried_workspace = workspace.resolve()
            ownership = kernel.invocation_ownership(
                definition=execution.definition,
                attempt=attempt,
                dispatch_id=dispatch_id,
            )
            execution.app.invocation_control.begin(
                invocation_id=dispatch_id,
                owner=ownership,
                route="codex_sdk",
                model=model,
                profile_digest=profile_digest,
                envelope_digest="e" * 64,
                declared_wall_seconds=60,
            )
            execution.app.invocation_control.settle(
                dispatch_id,
                terminal=InvocationTerminalFact(
                    status=InvocationStatus.FAILED,
                    code="turn_failed_provider_unavailable",
                    retryable=True,
                ),
            )
            raise LeafExecutionFailure(
                code="agent_backend_turn_failed_provider_unavailable",
                category="the Provider closed after a fresh recovery workspace was written",
                retryable=True,
                observed_actual=BudgetUsage(llm_tokens=1_000, agent_turns=1),
                agent=provenance(dispatch_id),
                workspace_recovery=LeafWorkspaceRecovery(
                    workspace=workspace.resolve(),
                    lineage_id="implementation:diagnostic-private-retry-draft",
                    profile_digest=profile_digest,
                    codex_config_digest=config_digest,
                    model=model,
                    output_schema_digest=schema_digest,
                ),
            )

        async def execute(context) -> None:
            await kernel.execute(context, definition=execution.definition, proposal_runner=proposal)

        return execute

    drifted_config = captured.config.model_copy(
        update={
            "agent": captured.config.agent.model_copy(
                update={"model": "different-current-default", "fallback_models": ()}
            )
        }
    )
    retried_failure = await DescendantRunner(
        config=drifted_config,
        diagnostic_state_root=first_root,
        diagnostic_parent=diagnostic_parent,
        executor_factory=retried_failure_executor_factory,
    ).run(
        scope_id=captured.scope_id,
        target_coordinate=candidate.coordinate.coordinate_key,
        required_manifest_ref=manifest_ref,
        infrastructure_retry=True,
    )
    assert retried_failure.status == "failed"
    assert retried_failure.infrastructure_retry_action_ref is not None
    assert retried_workspace is not None
    retry_root = Path(retried_failure.diagnostic_state_root)
    assert retried_workspace.is_relative_to(retry_root / "runs")
    assert not retried_workspace.is_relative_to(first_root / "runs")

    def recovered_executor_factory(execution: NodeExecution):
        kernel = SchedulerLeafExecutor(runtime=execution.runtime)

        async def proposal(context, attempt: WorkAttempt, dispatch_id: str) -> LeafProposal:
            assert execution.app.config.agent.model == model
            assert attempt.continuation_commitment is not None
            assert execution.runtime.continuations is not None
            assert execution.runtime.continuation_workspace_root == retry_root / "runs"
            record = execution.runtime.continuations.load_commitment(
                attempt.continuation_commitment,
                workspace_root=execution.runtime.continuation_workspace_root,
            )
            assert record is not None
            assert record.continuation_kind == "workspace_recovery"
            assert record.thread_id is None
            assert record.workspace_for_recovery() == retried_workspace
            with pytest.raises(ContinuationStoreError, match="cannot resume a Provider thread"):
                record.restore_session()
            assert (
                (retried_workspace / "candidate" / "runtime.py")
                .read_text(encoding="utf-8")
                .startswith("def recovered_draft_runtime")
            )
            output_ref = execution.app.controller.artifacts.put_json(
                artifact_id=f"candidate-workspace-recovered:{execution.run_id}",
                artifact_type="design.candidate_build",
                value={"complete_replacement_after_fresh_workspace_inspection": True},
                dependencies=context.external_input_refs,
            )
            return LeafProposal(
                output_refs=(output_ref,),
                subject_refs=(output_ref,),
                observed_actual=BudgetUsage(llm_tokens=1_000, agent_turns=1),
                agent=provenance(dispatch_id),
            )

        async def execute(context) -> None:
            await kernel.execute(context, definition=execution.definition, proposal_runner=proposal)

        return execute

    recovered = await DescendantRunner(
        config=drifted_config,
        diagnostic_state_root=retry_root,
        diagnostic_parent=diagnostic_parent,
        executor_factory=recovered_executor_factory,
    ).run(
        scope_id=captured.scope_id,
        target_coordinate=candidate.coordinate.coordinate_key,
        required_manifest_ref=manifest_ref,
        infrastructure_retry=True,
    )
    assert recovered.status == "committed"
    assert recovered.infrastructure_retry_action_ref is not None
    recovery_artifacts = ArtifactStore(Path(recovered.diagnostic_state_root) / "artifacts")
    action = recovery_artifacts.get_json(recovered.infrastructure_retry_action_ref, RepairAction)
    recovery_attempt = recovery_artifacts.get_json(recovered.target_attempt_ref, WorkAttempt)
    assert action.workspace_recovery is True
    # The recovery commitment existed only while the fresh Agent was inspecting
    # the private draft (asserted inside ``recovered_executor_factory``).  A
    # successful commit must clear it so no future attempt can reuse the draft.
    assert recovery_attempt.continuation_commitment is None
    assert str(retried_workspace) not in recovery_attempt.model_dump_json()


@pytest.mark.asyncio
async def test_diagnostic_descendant_authorizes_then_executes_one_actionable_semantic_repair(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed diagnostic candidate gets one explicit feedback-bound repair.

    The first constructed boundary is a real Scheduler/Validation/Feedback
    failure, not a hand-mutated Work head.  The authorization command may only
    record the existing normal RepairAction; it must not dispatch an executor.
    A separate descendant run then consumes that exact action through the
    ordinary Scheduler repair path.
    """

    captured = _capture_scope(tmp_path, monkeypatch)
    diagnostic_parent = tmp_path / ".agent-world-live"

    def parent_executor_factory(execution: NodeExecution):
        async def execute(context) -> None:
            input_refs = tuple(
                dict.fromkeys((*context.external_input_refs, *context.parent_output_refs))
            )
            output_ref = execution.app.controller.artifacts.put_json(
                artifact_id=f"semantic-repair-parent:{execution.run_id}",
                artifact_type="design.test_node_target",
                value={"source": "diagnostic-parent-for-semantic-repair"},
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
    source_graph = NodeRunner._reconstruct_graph(  # noqa: SLF001 - frozen test closure setup
        parent_artifacts,
        source_manifest,
    )
    repair_successor = source_graph.require(captured.successor_definition.coordinate).model_copy(
        update={
            "repair_policy": captured.successor_definition.repair_policy.model_copy(
                update={
                    "maximum_local_corrections": 1,
                    "strict_progress_bonus_corrections": 0,
                    "maximum_infrastructure_retries": 0,
                    "maximum_total_repair_attempts": 1,
                }
            ),
            "allowed_mutation_roots": ("/candidate",),
        }
    )
    repair_graph = GenerationWorkGraph.compile(
        (
            source_graph.require(captured.parent_coordinate),
            source_graph.require(captured.target_definition.coordinate),
            repair_successor,
        ),
        mode="diagnostic",
        strict_input_contracts=True,
    )
    for definition in repair_graph.definitions:
        parent_artifacts.put_json(
            artifact_id=f"work-definition:{definition.work_id}",
            artifact_type="control.work_definition",
            value=definition,
            dependencies=source_manifest.external_root_refs,
        )
    repair_manifest = repair_graph.manifest(
        topology_id="topology:test-node-semantic-repair",
        external_root_refs=source_manifest.external_root_refs,
    )
    repair_manifest_ref = parent_artifacts.put_json(
        artifact_id=repair_manifest.graph_id,
        artifact_type="control.work_graph_manifest",
        value=repair_manifest,
        dependencies=source_manifest.external_root_refs,
    )

    first_calls: list[str] = []

    def failing_executor_factory(execution: NodeExecution):
        kernel = SchedulerLeafExecutor(runtime=execution.runtime)

        async def proposal(_context, _attempt, _dispatch_id) -> LeafProposal:
            first_calls.append("rejected-candidate")
            raise LeafValidationFailure(
                issues=(
                    ValidationIssue(
                        code="test_semantic_coverage_missing_negative_case",
                        path=("candidate", "coverage", 0),
                        violated_condition=(
                            "the candidate omits the negative semantic coverage row"
                        ),
                        expected_category=(
                            "one candidate including the declared negative semantic coverage row"
                        ),
                        remediation=(
                            "Preserve valid coverage and add the missing negative semantic row."
                        ),
                    ),
                ),
                output_commitment=sha256_digest(b"test-semantic-repair-rejected-candidate"),
                category="deterministic_semantic_coverage",
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
        target_coordinate=repair_successor.coordinate.coordinate_key,
        required_manifest_ref=repair_manifest_ref,
    )

    assert first_calls == ["rejected-candidate"]
    assert first.status == "failed"
    assert first.validation_report.status == "failed"
    assert first.validation_report.repair_actionable is True
    first_head = WorkControlStore(Path(first.diagnostic_state_root) / "work-control").read_head(
        repair_successor.coordinate
    )
    assert first_head is not None
    assert first_head.repair_action_ref is None

    authorization_executor_calls: list[NodeExecution] = []

    def forbidden_authorization_executor(execution: NodeExecution):
        authorization_executor_calls.append(execution)
        raise AssertionError("semantic repair authorization must not create an executor")

    authorized = await DescendantRunner(
        config=captured.config,
        diagnostic_state_root=Path(first.diagnostic_state_root),
        diagnostic_parent=diagnostic_parent,
        executor_factory=forbidden_authorization_executor,
    ).run(
        scope_id=captured.scope_id,
        target_coordinate=repair_successor.coordinate.coordinate_key,
        required_manifest_ref=repair_manifest_ref,
        authorize_semantic_repair=True,
    )

    assert authorization_executor_calls == []
    assert authorized.status == "repair_authorized"
    assert authorized.authorized_repair_action_ref is not None
    assert authorized.target_evaluation_ref == first.target_evaluation_ref
    assert authorized.reserved_budget.repair_attempts == 0
    authorized_artifacts = ArtifactStore(Path(authorized.diagnostic_state_root) / "artifacts")
    action = authorized_artifacts.get_json(
        authorized.authorized_repair_action_ref,
        RepairAction,
    )
    first_attempt = ArtifactStore(Path(first.diagnostic_state_root) / "artifacts").get_json(
        first.target_attempt_ref,
        WorkAttempt,
    )
    assert action.decision == "local_correction"
    assert action.source_evaluation_ref == first.target_evaluation_ref
    assert action.immutable_input_refs == first_attempt.input_refs
    assert action.allowed_mutation_roots == ("/candidate",)

    repair_actions_seen: list[ArtifactRef | None] = []
    repair_briefs: list[tuple[ValidationIssue, ...]] = []

    def repaired_executor_factory(execution: NodeExecution):
        kernel = SchedulerLeafExecutor(runtime=execution.runtime)

        async def execute(context) -> None:
            repair_actions_seen.append(context.repair_action_ref)
            brief = kernel.agent_correction_brief(context, definition=execution.definition)
            assert brief is not None
            repair_briefs.append(brief.issues)
            input_refs = tuple(
                dict.fromkeys((*context.external_input_refs, *context.parent_output_refs))
            )
            output_ref = execution.app.controller.artifacts.put_json(
                artifact_id=f"semantic-repair-completed:{execution.run_id}",
                artifact_type="design.test_node_successor",
                value={"source": "one-authorized-semantic-repair"},
                dependencies=input_refs,
            )
            execution.runtime.execute_deterministic_boundary(
                definition=execution.definition,
                input_refs=input_refs,
                subject_ref=output_ref,
                output_refs=(output_ref,),
            )

        return execute

    repaired = await DescendantRunner(
        config=captured.config,
        diagnostic_state_root=Path(authorized.diagnostic_state_root),
        diagnostic_parent=diagnostic_parent,
        executor_factory=repaired_executor_factory,
    ).run(
        scope_id=captured.scope_id,
        target_coordinate=repair_successor.coordinate.coordinate_key,
        required_manifest_ref=repair_manifest_ref,
        execute_authorized_repair=True,
    )

    assert repaired.status == "committed"
    assert repaired.reserved_budget.repair_attempts == 1
    assert repair_actions_seen == [authorized.authorized_repair_action_ref]
    assert len(repair_briefs) == 1
    assert repair_briefs[0][0].code == "test_semantic_coverage_missing_negative_case"
    repaired_artifacts = ArtifactStore(Path(repaired.diagnostic_state_root) / "artifacts")
    repaired_attempt = repaired_artifacts.get_json(repaired.target_attempt_ref, WorkAttempt)
    assert repaired_attempt.parent_attempt_id == first_attempt.attempt_id
    assert repaired_attempt.repair_action_ref == authorized.authorized_repair_action_ref
    assert repaired_attempt.repair_attempt_charge == 1


@pytest.mark.asyncio
async def test_initial_test_node_failure_can_authorize_and_execute_one_semantic_repair(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An isolated first-node failure can use the explicit repair bridge.

    The target's only parent is a normal captured commit, which is exactly the
    shape produced by ``test-node``.  A plain descendant remains forbidden;
    only the two explicit semantic-repair phases may cross the bridge after
    the initial failure is proved diagnostic-only.
    """

    captured = _capture_scope(tmp_path, monkeypatch, repairable_target=True)
    diagnostic_parent = tmp_path / ".agent-world-live"
    first_calls: list[str] = []

    def failing_executor_factory(execution: NodeExecution):
        kernel = SchedulerLeafExecutor(runtime=execution.runtime)

        async def proposal(_context, _attempt, _dispatch_id) -> LeafProposal:
            first_calls.append("rejected-initial-target")
            raise LeafValidationFailure(
                issues=(
                    ValidationIssue(
                        code="test_initial_target_binding_alias_invalid",
                        path=("candidate", "binding_id"),
                        violated_condition=(
                            "the initial candidate selected a binding outside the frozen alias set"
                        ),
                        expected_category="one alias from the frozen target catalog",
                        remediation="Preserve valid content and replace only the invalid alias.",
                    ),
                ),
                output_commitment=sha256_digest(b"test-initial-target-invalid-alias"),
                category="deterministic_binding_alias",
            )

        async def execute(context) -> None:
            await kernel.execute(
                context,
                definition=execution.definition,
                proposal_runner=proposal,
            )

        return execute

    first = await NodeRunner(
        config=captured.config,
        source_state_root=captured.state_root,
        diagnostic_parent=diagnostic_parent,
        executor_factory=failing_executor_factory,
    ).run(
        scope_id=captured.scope_id,
        target_coordinate=captured.target_definition.coordinate.coordinate_key,
    )

    assert first_calls == ["rejected-initial-target"]
    assert first.status == "failed"
    assert first.validation_report.repair_actionable is True
    first_root = Path(first.diagnostic_state_root)
    first_app = build_application(captured.config.model_copy(update={"state_root": first_root}))
    first_artifacts = first_app.controller.artifacts
    manifest_ref = next(
        ref
        for ref in first_artifacts.list_revisions()
        if ref.artifact_type == "control.work_graph_manifest"
    )
    parent_head = first_app.controller.work_control.read_head(captured.parent_coordinate)
    assert parent_head is not None and parent_head.commit_ref is not None
    parent_commit = first_artifacts.get_json(parent_head.commit_ref, WorkCommit)
    assert not parent_commit.diagnostic_only

    with pytest.raises(NodeError) as ordinary_descendant:
        await DescendantRunner(
            config=captured.config,
            diagnostic_state_root=first_root,
            diagnostic_parent=diagnostic_parent,
        ).run(
            scope_id=captured.scope_id,
            target_coordinate=captured.target_definition.coordinate.coordinate_key,
            required_manifest_ref=manifest_ref,
        )
    assert ordinary_descendant.value.code == "test_descendant_no_diagnostic_parent"

    authorization_executor_calls: list[NodeExecution] = []

    def forbidden_authorization_executor(execution: NodeExecution):
        authorization_executor_calls.append(execution)
        raise AssertionError("semantic repair authorization must not create an executor")

    authorized = await DescendantRunner(
        config=captured.config,
        diagnostic_state_root=first_root,
        diagnostic_parent=diagnostic_parent,
        executor_factory=forbidden_authorization_executor,
    ).run(
        scope_id=captured.scope_id,
        target_coordinate=captured.target_definition.coordinate.coordinate_key,
        required_manifest_ref=manifest_ref,
        authorize_semantic_repair=True,
    )

    assert authorization_executor_calls == []
    assert authorized.status == "repair_authorized"
    assert authorized.authorized_repair_action_ref is not None
    first_attempt = first_artifacts.get_json(first.target_attempt_ref, WorkAttempt)
    authorized_artifacts = ArtifactStore(Path(authorized.diagnostic_state_root) / "artifacts")
    action = authorized_artifacts.get_json(
        authorized.authorized_repair_action_ref,
        RepairAction,
    )
    assert action.decision == "local_correction"
    assert action.immutable_input_refs == first_attempt.input_refs
    assert action.allowed_mutation_roots == ("/candidate",)

    repair_briefs: list[tuple[ValidationIssue, ...]] = []

    def repaired_executor_factory(execution: NodeExecution):
        kernel = SchedulerLeafExecutor(runtime=execution.runtime)

        async def execute(context) -> None:
            brief = kernel.agent_correction_brief(context, definition=execution.definition)
            assert brief is not None
            repair_briefs.append(brief.issues)
            input_refs = tuple(
                dict.fromkeys((*context.external_input_refs, *context.parent_output_refs))
            )
            output_ref = execution.app.controller.artifacts.put_json(
                artifact_id=f"initial-target-repaired:{execution.run_id}",
                artifact_type="design.test_node_target",
                value={"source": "one-authorized-initial-target-repair"},
                dependencies=input_refs,
            )
            execution.runtime.execute_deterministic_boundary(
                definition=execution.definition,
                input_refs=input_refs,
                subject_ref=output_ref,
                output_refs=(output_ref,),
            )

        return execute

    repaired = await DescendantRunner(
        config=captured.config,
        diagnostic_state_root=Path(authorized.diagnostic_state_root),
        diagnostic_parent=diagnostic_parent,
        executor_factory=repaired_executor_factory,
    ).run(
        scope_id=captured.scope_id,
        target_coordinate=captured.target_definition.coordinate.coordinate_key,
        required_manifest_ref=manifest_ref,
        execute_authorized_repair=True,
    )

    assert repaired.status == "committed"
    assert repaired.reserved_budget.repair_attempts == 1
    assert len(repair_briefs) == 1
    assert repair_briefs[0][0].code == "test_initial_target_binding_alias_invalid"
    repaired_artifacts = ArtifactStore(Path(repaired.diagnostic_state_root) / "artifacts")
    repaired_attempt = repaired_artifacts.get_json(repaired.target_attempt_ref, WorkAttempt)
    assert repaired_attempt.parent_attempt_id == first_attempt.attempt_id
    assert repaired_attempt.repair_action_ref == authorized.authorized_repair_action_ref
    assert repaired_attempt.repair_attempt_charge == 1


@pytest.mark.asyncio
async def test_initial_test_node_failure_can_retry_one_infrastructure_terminal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The initial test-node bridge applies to a classified route retry too.

    Its only parent is an ordinary captured commit. The retry remains safe
    because the failed target itself is a marked diagnostic terminal and the
    runtime rechecks its exact retryable report before creating the attempt.
    """

    captured = _capture_scope(
        tmp_path,
        monkeypatch,
        infrastructure_retryable_target=True,
    )
    diagnostic_parent = tmp_path / ".agent-world-live"
    first_calls: list[str] = []

    def failing_executor_factory(execution: NodeExecution):
        kernel = SchedulerLeafExecutor(runtime=execution.runtime)

        async def proposal(_context, _attempt, _dispatch_id) -> LeafProposal:
            first_calls.append("retryable-initial-target")
            raise LeafExecutionFailure(
                code="test_initial_target_provider_unavailable",
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

    first = await NodeRunner(
        config=captured.config,
        source_state_root=captured.state_root,
        diagnostic_parent=diagnostic_parent,
        executor_factory=failing_executor_factory,
    ).run(
        scope_id=captured.scope_id,
        target_coordinate=captured.target_definition.coordinate.coordinate_key,
    )

    assert first_calls == ["retryable-initial-target"]
    assert first.status == "failed"
    assert first.validation_report.infrastructure_retryable is True
    first_root = Path(first.diagnostic_state_root)
    first_app = build_application(captured.config.model_copy(update={"state_root": first_root}))
    first_artifacts = first_app.controller.artifacts
    manifest_ref = next(
        ref
        for ref in first_artifacts.list_revisions()
        if ref.artifact_type == "control.work_graph_manifest"
    )
    parent_head = first_app.controller.work_control.read_head(captured.parent_coordinate)
    assert parent_head is not None and parent_head.commit_ref is not None
    parent_commit = first_artifacts.get_json(parent_head.commit_ref, WorkCommit)
    assert not parent_commit.diagnostic_only

    retry_calls: list[WorkCoordinate] = []

    def recovered_executor_factory(execution: NodeExecution):
        kernel = SchedulerLeafExecutor(runtime=execution.runtime)

        async def proposal(context, _attempt, _dispatch_id) -> LeafProposal:
            retry_calls.append(context.coordinate)
            input_refs = tuple(
                dict.fromkeys((*context.external_input_refs, *context.parent_output_refs))
            )
            output_ref = execution.app.controller.artifacts.put_json(
                artifact_id=f"initial-target-retry-recovered:{execution.run_id}",
                artifact_type="design.test_node_target",
                value={"source": "one-initial-target-infrastructure-retry"},
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
        diagnostic_state_root=first_root,
        diagnostic_parent=diagnostic_parent,
        executor_factory=recovered_executor_factory,
    ).run(
        scope_id=captured.scope_id,
        target_coordinate=captured.target_definition.coordinate.coordinate_key,
        required_manifest_ref=manifest_ref,
        infrastructure_retry=True,
    )

    assert retry_calls == [captured.target_definition.coordinate]
    assert retried.status == "committed"
    assert retried.infrastructure_retry_action_ref is not None
    retried_artifacts = ArtifactStore(Path(retried.diagnostic_state_root) / "artifacts")
    action = retried_artifacts.get_json(
        retried.infrastructure_retry_action_ref,
        RepairAction,
    )
    previous_attempt = first_artifacts.get_json(first.target_attempt_ref, WorkAttempt)
    retry_attempt = retried_artifacts.get_json(retried.target_attempt_ref, WorkAttempt)
    assert action.decision == "infrastructure_retry"
    assert retry_attempt.parent_attempt_id == previous_attempt.attempt_id
    assert retry_attempt.repair_action_ref == retried.infrastructure_retry_action_ref
    assert retry_attempt.repair_attempt_charge == 1


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
async def test_descendant_refresh_restarts_one_locally_failed_node_after_authoring_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A changed Code-Agent development loop may start a fresh first attempt.

    This is not an unbounded retry and it does not borrow a Scheduler repair
    action.  The source is one fully observed local validation failure; the
    overlay changes its authoring revision, then the ordinary Scheduler opens
    a new attempt with the same frozen parent closure.
    """

    captured = _capture_scope(tmp_path, monkeypatch)
    diagnostic_parent = tmp_path / ".agent-world-live"

    def failing_executor_factory(execution: NodeExecution):
        async def execute(context) -> None:
            input_refs = tuple(
                dict.fromkeys((*context.external_input_refs, *context.parent_output_refs))
            )
            output_ref = execution.app.controller.artifacts.put_json(
                artifact_id=f"local-refresh-failed:{execution.run_id}",
                artifact_type="design.test_node_target",
                value={"source": "local-validation-failure"},
                dependencies=input_refs,
            )
            execution.runtime.execute_deterministic_boundary(
                definition=execution.definition,
                input_refs=input_refs,
                subject_ref=output_ref,
                output_refs=(output_ref,),
                issues=(
                    (
                        "test_node_local_authoring_failure",
                        ("candidate",),
                        "The first local authoring revision failed its real validation boundary.",
                        "the frozen target acceptance condition",
                    ),
                ),
            )

        return execute

    failed = await NodeRunner(
        config=captured.config,
        source_state_root=captured.state_root,
        diagnostic_parent=diagnostic_parent,
        executor_factory=failing_executor_factory,
    ).run(
        scope_id=captured.scope_id,
        target_coordinate=captured.target_definition.coordinate.coordinate_key,
    )
    assert failed.status == "failed"
    assert failed.validation_report.status == "failed"
    failed_artifacts = ArtifactStore(Path(failed.diagnostic_state_root) / "artifacts")
    manifest_ref = next(
        reference
        for reference in failed_artifacts.list_revisions()
        if reference.artifact_type == "control.work_graph_manifest"
    )

    updated_implementation = "framework.test-descendant-local-refresh.v1"
    updated_validator = "framework.test-descendant-local-validator.v1"
    monkeypatch.setattr(
        test_node_module,
        "current_runtime_revisions_for_definition",
        lambda definition: (
            (updated_implementation, updated_validator)
            if definition.coordinate == captured.target_definition.coordinate
            else None
        ),
    )
    dispatched: list[WorkDefinition] = []

    def refreshed_executor_factory(execution: NodeExecution):
        async def execute(context) -> None:
            dispatched.append(execution.definition)
            input_refs = tuple(
                dict.fromkeys((*context.external_input_refs, *context.parent_output_refs))
            )
            output_ref = execution.app.controller.artifacts.put_json(
                artifact_id=f"local-refresh-passed:{execution.run_id}",
                artifact_type="design.test_node_target",
                value={"source": "fresh-current-authoring-revision"},
                dependencies=input_refs,
            )
            execution.runtime.execute_deterministic_boundary(
                definition=execution.definition,
                input_refs=input_refs,
                subject_ref=output_ref,
                output_refs=(output_ref,),
            )

        return execute

    refreshed = await DescendantRunner(
        config=captured.config,
        diagnostic_state_root=Path(failed.diagnostic_state_root),
        diagnostic_parent=diagnostic_parent,
        executor_factory=refreshed_executor_factory,
    ).run(
        scope_id=captured.scope_id,
        target_coordinate=captured.target_definition.coordinate.coordinate_key,
        required_manifest_ref=manifest_ref,
        refresh_current_implementation=True,
    )

    assert refreshed.status == "committed"
    assert refreshed.runtime_implementation_override_ref is not None
    assert refreshed.authorized_repair_action_ref is None
    assert refreshed.reserved_budget.repair_attempts == 0
    assert refreshed.superseded_stale_attempt_ref == failed.target_attempt_ref
    assert len(dispatched) == 1
    assert dispatched[0].proposal_policy.implementation_revision_id == updated_implementation
    assert dispatched[0].validation_policy.validator_revision_id == updated_validator


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
    # This diagnostic fixture executes a framework leaf rather than a real
    # Agent-backed proposal, so its Scheduler dispatch must not be presented
    # as an Agent invocation identity.
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
async def test_test_node_keyboard_interrupt_settles_started_operation_before_reraise(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A real SIGINT shape must settle WorkControl before CLI exit 130."""

    captured = _capture_scope(tmp_path, monkeypatch)
    diagnostic_parent = tmp_path / "diagnostics"

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
                    dispatch_id="dispatch:test-node-keyboard-interrupt",
                )
            raise KeyboardInterrupt

        return execute

    with pytest.raises(KeyboardInterrupt):
        await NodeRunner(
            config=captured.config,
            source_state_root=captured.state_root,
            diagnostic_parent=diagnostic_parent,
            executor_factory=executor_factory,
        ).run(
            scope_id=captured.scope_id,
            target_coordinate=captured.target_definition.coordinate.coordinate_key,
        )

    diagnostic_roots = tuple(diagnostic_parent.iterdir())
    assert len(diagnostic_roots) == 1
    artifacts = ArtifactStore(diagnostic_roots[0] / "artifacts")
    head = WorkControlStore(diagnostic_roots[0] / "work-control").read_head(
        captured.target_definition.coordinate
    )
    assert head is not None and head.status == "failed" and head.active_operation_ref is None
    attempt = artifacts.get_json(head.attempt_ref, WorkAttempt)
    assert attempt.finished_at is not None
    assert attempt.validation_report_ref is not None
    report = artifacts.get_json(attempt.validation_report_ref)
    assert report["issues"][0]["code"] == "process_interrupted_cancelled"


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


@pytest.mark.asyncio
async def test_descendant_preflight_names_the_noncommitted_parent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A diagnostic descendant tells the project Agent exactly what blocks it."""

    captured = _capture_scope(tmp_path, monkeypatch)
    diagnostic_parent = tmp_path / ".agent-world-live"

    def target_executor_factory(execution: NodeExecution):
        async def execute(context) -> None:
            input_refs = tuple(
                dict.fromkeys((*context.external_input_refs, *context.parent_output_refs))
            )
            output_ref = execution.app.controller.artifacts.put_json(
                artifact_id=f"diagnostic-parent:{execution.run_id}",
                artifact_type="design.test_node_target",
                value={"source": "diagnostic-parent"},
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
    parent_root = Path(parent_result.diagnostic_state_root)
    parent_head_key = hashlib.sha256(
        f"{captured.scope_id}\0{captured.target_definition.coordinate.coordinate_key}".encode()
    ).hexdigest()
    (parent_root / "work-control" / "heads" / f"{parent_head_key}.json").replace(
        parent_root / "withheld-descendant-parent-head.json"
    )

    with pytest.raises(NodeError) as raised:
        await DescendantRunner(
            config=captured.config,
            diagnostic_state_root=parent_root,
            diagnostic_parent=diagnostic_parent,
        ).run(
            scope_id=captured.scope_id,
            target_coordinate=captured.successor_definition.coordinate.coordinate_key,
        )

    assert raised.value.code == "test_descendant_ancestor_closure_missing"
    assert "design.captured_target.captured_target=missing" in str(raised.value)


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
    invocation_record = source_root / "invocation-control" / "attempts" / "settled.json"
    invocation_record.parent.mkdir(parents=True)
    invocation_record.write_text('{"status":"settled"}', encoding="utf-8")
    for directory in (
        "campaigns",
        "direct-jobs",
        "observability",
        "registry",
        "telemetry",
    ):
        (source_root / directory).mkdir()
    (source_root / "work-control").mkdir()

    diagnostic_root = _prepare_diagnostic_clone(
        source_root=source_root,
        diagnostic_parent=tmp_path,
        marker_error_code="test_node_diagnostic_marker_failed",
        marker_message="x",
    )

    assert (diagnostic_root / "artifacts" / "durable.json").is_file()
    assert not (diagnostic_root / "runs").exists()
    assert not (diagnostic_root / "expansion-source-runs").exists()
    for directory in (
        "campaigns",
        "direct-jobs",
        "invocation-control",
        "observability",
        "registry",
        "telemetry",
    ):
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
    assert not hasattr(parsed, "diagnostic_structured_output_transport")
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


def test_test_node_cli_rejects_legacy_profile_transport_overlay(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(
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
    assert not hasattr(parsed, "diagnostic_structured_output_transport")


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
    assert not hasattr(parsed, "diagnostic_structured_output_transport")
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


def test_descendant_node_cli_accepts_one_authorized_semantic_repair(
    tmp_path: Path,
) -> None:
    parsed = build_parser().parse_args(
        [
            "test-descendant-node",
            "generate-job:test-node",
            "build.candidate_build.environment_candidate",
            "--diagnostic-state-root",
            str(tmp_path / ".agent-world-live" / "test-node-source"),
            "--execute-authorized-repair",
        ]
    )

    assert parsed.execute_authorized_repair is True
    assert parsed.infrastructure_retry is False
    assert parsed.refresh_current_implementation is False


def test_descendant_node_cli_accepts_one_semantic_repair_authorization(
    tmp_path: Path,
) -> None:
    parsed = build_parser().parse_args(
        [
            "test-descendant-node",
            "generate-job:test-node",
            "build.candidate_build.environment_candidate",
            "--diagnostic-state-root",
            str(tmp_path / ".agent-world-live" / "test-node-source"),
            "--authorize-semantic-repair",
        ]
    )

    assert parsed.authorize_semantic_repair is True
    assert parsed.execute_authorized_repair is False
    assert parsed.infrastructure_retry is False
    assert parsed.refresh_current_implementation is False


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


def test_descendant_node_cli_rejects_legacy_profile_transport_overlay(
    tmp_path: Path,
) -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(
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
    assert not hasattr(parsed, "diagnostic_structured_output_transport")


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


def test_final_node_cli_selects_runtime_integration_without_a_model_envelope(
    tmp_path: Path,
) -> None:
    diagnostic_state = str(tmp_path / ".agent-world-live" / "test-node-plan-derived-design")
    parsed = build_parser().parse_args(
        [
            "test-final-node",
            "generate-job:test-node",
            "runtime_integration",
            "--diagnostic-state-root",
            diagnostic_state,
        ]
    )

    assert parsed.target_stage == "runtime_integration"
    assert parsed.batch_index is None
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
    runtime_integration = WorkCoordinate(
        scope_id=scope_id,
        component="integration",
        stage="runtime_integration",
        artifact_slot="integration_report",
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
            for coordinate in (
                implementation_plan,
                first_batch,
                second_batch,
                runtime_integration,
            )
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
    assert (
        FinalNodeRunner._initial_target(
            final_graph=graph,  # type: ignore[arg-type]
            verifier_plan=plan,  # type: ignore[arg-type]
            target_stage="runtime_integration",
            batch_index=None,
        )
        == runtime_integration
    )
    with pytest.raises(NodeError, match="1-based index"):
        FinalNodeRunner._initial_target(
            final_graph=graph,  # type: ignore[arg-type]
            verifier_plan=plan,  # type: ignore[arg-type]
            target_stage="verifier_intent_batch",
            batch_index=3,
        )


def test_final_node_reports_inactive_candidate_before_integration_dispatch() -> None:
    with pytest.raises(
        NodeError,
        match="CandidateBuild predecessor is not active",
    ):
        FinalNodeRunner._require_dispatchable_final_target(  # noqa: SLF001
            target_stage="runtime_integration",
            scheduled_state="waiting",
        )

    FinalNodeRunner._require_dispatchable_final_target(  # noqa: SLF001
        target_stage="runtime_integration",
        scheduled_state="stale",
    )

    with pytest.raises(NodeError, match="implementation_plan is blocked"):
        FinalNodeRunner._require_dispatchable_final_target(  # noqa: SLF001
            target_stage="implementation_plan",
            scheduled_state="blocked",
        )


@pytest.mark.parametrize(
    ("diagnostic_only", "releasable", "expected"),
    (
        (False, True, True),
        (True, False, True),
        (False, False, False),
        (True, True, False),
    ),
)
def test_final_epoch_verifier_plan_anchor_accepts_only_normal_or_diagnostic_modes(
    diagnostic_only: bool,
    releasable: bool,
    expected: bool,
) -> None:
    commit = SimpleNamespace(
        diagnostic_only=diagnostic_only,
        releasable=releasable,
    )

    assert (
        DescendantRunner._is_eligible_final_epoch_verifier_plan_anchor(  # type: ignore[arg-type]  # noqa: SLF001
            commit
        )
        is expected
    )


def test_final_epoch_overlay_feedback_routes_stale_design_predecessor_to_final_harness() -> None:
    error = test_node_module._final_epoch_rederivation_required(  # noqa: SLF001
        source_epoch_kind="final",
        error=WorkResumeError(
            "predecessor WorkCommit is not active for the next graph: "
            "verifier.verifier_plan.verifier_batch_plan"
        ),
        label="current runtime implementation refresh",
    )

    assert error is not None
    assert error.code == "test_node_final_epoch_rederivation_required"
    assert "verifier.verifier_plan.verifier_batch_plan" in str(error)
    assert "No model invocation was started" in str(error)
    assert "test-final-node" in str(error)
    assert (
        test_node_module._final_epoch_rederivation_required(  # noqa: SLF001
            source_epoch_kind="design",
            error=WorkResumeError(
                "predecessor WorkCommit is not active for the next graph: "
                "verifier.verifier_plan.verifier_batch_plan"
            ),
            label="current runtime implementation refresh",
        )
        is None
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
