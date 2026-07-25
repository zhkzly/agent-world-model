"""T0 evidence for isolated, real single-node WorkGraph execution."""

from __future__ import annotations

import asyncio
import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

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
    WorkControlRuntime,
    WorkControlStore,
    WorkControlStoreError,
    WorkCoordinate,
    WorkDefinition,
    deterministic_boundary_work_definition,
)
from agent_world.control.leaf_executor import LeafExecutionFailure, SchedulerLeafExecutor
from agent_world.control.release_leaf import RegistryPublicationLeaf
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
    graph = GenerationWorkGraph.compile(
        (parent, target),
        mode="diagnostic",
        strict_input_contracts=True,
    )
    manifest = graph.manifest(
        topology_id="topology:test-node",
        external_root_refs=(context_ref,),
    )
    artifacts.put_json(
        artifact_id=manifest.graph_id,
        artifact_type="control.work_graph_manifest",
        value=manifest,
        dependencies=(context_ref,),
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
    assert (
        (diagnostic_root / "work-control" / ".test-node-diagnostic").read_text(
            encoding="utf-8"
        )
        == "diagnostic_only=true\nreleasable=false\n"
    )
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
        target_coordinate=captured.target_definition.coordinate.coordinate_key,
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

    ordinary_snapshot = WorkScheduler(
        graph=frozen.graph,
        manifest=frozen.manifest,
        manifest_ref=frozen.manifest_ref,
        heads=app.controller.work_control,
        artifacts=app.controller.artifacts,
    ).snapshot()
    assert next(
        item
        for item in ordinary_snapshot.work
        if item.coordinate == captured.target_definition.coordinate
    ).state == "stale"

    diagnostic_runtime = WorkControlRuntime(
        artifacts=app.controller.artifacts,
        heads=app.controller.work_control,
        budget=LeaseBudgetLedger(Budget(wall_seconds=1_000)),
        diagnostic_only=True,
    )
    diagnostic_snapshot = WorkScheduler(
        graph=frozen.graph,
        manifest=frozen.manifest,
        manifest_ref=frozen.manifest_ref,
        heads=app.controller.work_control,
        artifacts=app.controller.artifacts,
        runtime=diagnostic_runtime,
        allow_diagnostic_ancestors=True,
    ).snapshot()
    assert next(
        item
        for item in diagnostic_snapshot.work
        if item.coordinate == captured.target_definition.coordinate
    ).state == "committed"


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
    attempt = artifacts.get_json(result.target_attempt_ref, WorkAttempt)
    operation = artifacts.get_json(attempt.operation_run_refs[0], OperationRun)
    assert operation.status == "terminal"
    assert operation.error_code == "process_interrupted_cancelled"
    execution = artifacts.get_json(operation.execution_ref)
    assert execution["status"] == "interrupted"
    assert execution["invocation_id"] is None
    assert execution["unknown_upper_bound"]["agent_turns"] == 0


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
    assert WorkControlStore(captured.state_root / "work-control").read_head(
        captured.target_definition.coordinate
    ) is not None


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
    for directory in ("campaigns", "direct-jobs", "registry", "telemetry"):
        (source_root / directory).mkdir()

    diagnostic_root = tmp_path / "diagnostic-state"
    NodeRunner._copy_state_root(source_root, diagnostic_root)

    assert (diagnostic_root / "artifacts" / "durable.json").is_file()
    assert not (diagnostic_root / "runs").exists()
    assert not (diagnostic_root / "expansion-source-runs").exists()
    for directory in ("campaigns", "direct-jobs", "registry", "telemetry"):
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
