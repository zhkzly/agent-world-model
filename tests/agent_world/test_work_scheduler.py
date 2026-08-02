from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent_world.artifact_store import ArtifactStore
from agent_world.contracts import Budget
from agent_world.control import (
    ArtifactSlotContract,
    GenerationWorkGraph,
    JoinPolicy,
    LeaseBudgetLedger,
    WorkAttempt,
    WorkControlRuntime,
    WorkControlStore,
    WorkCoordinate,
    WorkExecutionContext,
    WorkExecutorMissingError,
    WorkGroupDefinition,
    WorkScheduler,
    deterministic_boundary_work_definition,
)
from agent_world.control.telemetry import TelemetryStore
from agent_world.control.work_runtime import WorkRuntimeError
from agent_world.control.work_store import WorkResumeError


def _definition(
    *,
    scope_id: str,
    component: str,
    stage: str,
    coordinate: WorkCoordinate,
    dependencies: tuple[WorkCoordinate, ...],
):
    return deterministic_boundary_work_definition(
        scope_id=scope_id,
        component=component,  # type: ignore[arg-type]
        stage=stage,
        artifact_slot=coordinate.artifact_slot,
        dependency_coordinates=dependencies,
        claim_id=f"{stage}.passed",
        claim=f"{stage} passes its deterministic boundary.",
        timing_reason=f"Consumers require committed {stage} evidence.",
        effect="block_release",
        success_maturity=f"{stage}_passed",
    ).model_copy(update={"coordinate": coordinate})


def _commit(
    runtime: WorkControlRuntime,
    definition,
    *,
    input_refs,
    output_ref,
    child_commit_refs=(),
) -> None:
    runtime.execute_deterministic_boundary(
        definition=definition,
        input_refs=input_refs,
        subject_ref=output_ref,
        output_refs=(output_ref,),
        child_commit_refs=child_commit_refs,
    )


def test_scheduler_discloses_only_declared_parent_artifacts(tmp_path: Path) -> None:
    """A causal dependency does not leak unrelated or sealed parent outputs."""

    scope_id = "job:least-privilege"
    producer_coordinate = WorkCoordinate(
        scope_id=scope_id,
        component="design",
        stage="producer",
        artifact_slot="producer",
    )
    consumer_coordinate = WorkCoordinate(
        scope_id=scope_id,
        component="release",
        stage="consumer",
        artifact_slot="consumer",
    )
    producer = _definition(
        scope_id=scope_id,
        component="design",
        stage="producer",
        coordinate=producer_coordinate,
        dependencies=(),
    ).model_copy(
        update={
            "output_slots": (
                ArtifactSlotContract(
                    slot_id="output:allowed",
                    direction="output",
                    artifact_types=("design.allowed",),
                    minimum_count=1,
                    maximum_count=1,
                    producer_component="design",
                ),
                ArtifactSlotContract(
                    slot_id="output:sealed",
                    direction="output",
                    artifact_types=("design.sealed",),
                    minimum_count=1,
                    maximum_count=1,
                    producer_component="design",
                    confidentiality="sealed",
                ),
            )
        }
    )
    consumer = _definition(
        scope_id=scope_id,
        component="release",
        stage="consumer",
        coordinate=consumer_coordinate,
        dependencies=(producer_coordinate,),
    ).model_copy(
        update={
            "input_slots": (
                ArtifactSlotContract(
                    slot_id="input:allowed",
                    direction="input",
                    artifact_types=("design.allowed",),
                    minimum_count=1,
                    maximum_count=1,
                    producer_component="design",
                ),
            )
        }
    )
    graph = GenerationWorkGraph.compile(
        (producer, consumer),
        mode="diagnostic",
        strict_input_contracts=True,
    )
    artifacts = ArtifactStore(tmp_path / "artifacts").issue_writer(
        producer="work-controller",
        allowed_artifact_type_prefixes=("control.", "design."),
    )
    heads = WorkControlStore(tmp_path / "heads")
    runtime = WorkControlRuntime(
        artifacts=artifacts,
        heads=heads,
        budget=LeaseBudgetLedger(Budget(wall_seconds=1_000)),
    )
    root_ref = artifacts.put_json(
        artifact_id="context",
        artifact_type="control.generation_context",
        value={"request": "hotel"},
    )
    allowed_ref = artifacts.put_json(
        artifact_id="allowed",
        artifact_type="design.allowed",
        value={"public": True},
        dependencies=(root_ref,),
    )
    sealed_ref = artifacts.put_json(
        artifact_id="sealed",
        artifact_type="design.sealed",
        value={"private": True},
        dependencies=(root_ref,),
    )
    runtime.execute_deterministic_boundary(
        definition=producer,
        input_refs=(root_ref,),
        subject_ref=allowed_ref,
        output_refs=(allowed_ref, sealed_ref),
    )
    manifest = graph.manifest(
        topology_id="topology:least-privilege",
        external_root_refs=(root_ref,),
    )
    manifest_ref = artifacts.put_json(
        artifact_id=manifest.graph_id,
        artifact_type="control.work_graph_manifest",
        value=manifest,
        dependencies=(root_ref,),
    )
    scheduler = WorkScheduler(
        graph=graph,
        manifest=manifest,
        manifest_ref=manifest_ref,
        heads=heads,
        artifacts=artifacts,
    )

    resolved = scheduler.resolve_inputs(consumer_coordinate)

    assert resolved.parent_commit_refs
    assert resolved.parent_output_refs == (allowed_ref,)
    assert resolved.all_input_refs == (root_ref, allowed_ref)
    assert (
        next(
            item for item in scheduler.snapshot().work if item.coordinate == consumer_coordinate
        ).state
        == "ready"
    )


def test_work_attempt_span_inherits_the_direct_root_trace(tmp_path: Path) -> None:
    """A Scheduler leaf belongs to its Direct root, rather than an orphan trace."""

    scope_id = "job:trace-parent"
    coordinate = WorkCoordinate(
        scope_id=scope_id,
        component="design",
        stage="trace_boundary",
        artifact_slot="trace_boundary",
    )
    definition = _definition(
        scope_id=scope_id,
        component="design",
        stage="trace_boundary",
        coordinate=coordinate,
        dependencies=(),
    )
    artifacts = ArtifactStore(tmp_path / "artifacts").issue_writer(
        producer="work-controller",
        allowed_artifact_type_prefixes=("control.", "design."),
    )
    root_ref = artifacts.put_json(
        artifact_id="context:trace-parent",
        artifact_type="control.generation_context",
        value={"request": "hotel"},
    )
    output_ref = artifacts.put_json(
        artifact_id="output:trace-parent",
        artifact_type="design.trace_boundary",
        value={"passed": True},
        dependencies=(root_ref,),
    )
    with TelemetryStore(tmp_path / "telemetry") as telemetry:
        root = telemetry.start_span(
            trace_id="run:trace-parent",
            component="controller",
            operation="direct.generate",
            run_id="run:trace-parent",
        )
        telemetry.activate_trace(
            trace_id="run:trace-parent",
            run_id="run:trace-parent",
            parent_span_id=root.span_id,
        )
        runtime = WorkControlRuntime(
            artifacts=artifacts,
            heads=WorkControlStore(tmp_path / "heads"),
            budget=LeaseBudgetLedger(Budget(wall_seconds=1_000)),
            telemetry=telemetry,
            trace_id="run:trace-parent",
            run_id="run:trace-parent",
        )
        runtime.execute_deterministic_boundary(
            definition=definition,
            input_refs=(root_ref,),
            subject_ref=output_ref,
            output_refs=(output_ref,),
        )
        root.finish(status="passed")
        spans = telemetry.inspect_trace("run:trace-parent")["spans"]

    work_spans = [
        item for item in spans if item["operation"] == definition.proposal_policy.operation
    ]
    assert len(work_spans) == 1
    assert work_spans[0]["parent_span_id"] == root.span_id


def test_scheduler_retains_successful_sibling_and_opens_exact_join(tmp_path: Path) -> None:
    scope_id = "job:hotel"
    root_coordinate = WorkCoordinate(
        scope_id=scope_id,
        component="design",
        stage="modeling_boundary",
        artifact_slot="environment_design",
    )
    member_one_coordinate = WorkCoordinate(
        scope_id=scope_id,
        component="verifier",
        stage="verifier_intent",
        artifact_slot="verifier_intent",
        group_id="verifier-batches",
        shard_id="batch-1",
    )
    member_two_coordinate = member_one_coordinate.model_copy(update={"shard_id": "batch-2"})
    aggregate_coordinate = WorkCoordinate(
        scope_id=scope_id,
        component="verifier",
        stage="verifier_intent_aggregate",
        artifact_slot="verifier_intent_aggregate",
        group_id="verifier-batches",
    )
    root = _definition(
        scope_id=scope_id,
        component="design",
        stage="modeling_boundary",
        coordinate=root_coordinate,
        dependencies=(),
    )
    member_one = _definition(
        scope_id=scope_id,
        component="integration",
        stage="verifier_intent_1",
        coordinate=member_one_coordinate,
        dependencies=(root_coordinate,),
    )
    member_two = _definition(
        scope_id=scope_id,
        component="integration",
        stage="verifier_intent_2",
        coordinate=member_two_coordinate,
        dependencies=(root_coordinate,),
    )
    aggregate = _definition(
        scope_id=scope_id,
        component="integration",
        stage="verifier_intent_aggregate",
        coordinate=aggregate_coordinate,
        dependencies=(member_one_coordinate, member_two_coordinate),
    )
    group = WorkGroupDefinition(
        group_id="verifier-batches",
        scope_id=scope_id,
        member_coordinates=(member_one_coordinate, member_two_coordinate),
        aggregate_coordinate=aggregate_coordinate,
        join_policy=JoinPolicy(mode="all"),
    )
    graph = GenerationWorkGraph.compile(
        (root, member_one, member_two, aggregate),
        groups=(group,),
        mode="diagnostic",
    )
    artifacts = ArtifactStore(tmp_path / "artifacts").issue_writer(
        producer="work-controller",
        allowed_artifact_type_prefixes=("control.", "design.", "verifier."),
    )
    heads = WorkControlStore(tmp_path / "heads")
    runtime = WorkControlRuntime(
        artifacts=artifacts,
        heads=heads,
        budget=LeaseBudgetLedger(Budget(wall_seconds=1_000, tool_calls=100)),
    )
    external_ref = artifacts.put_json(
        artifact_id="request",
        artifact_type="control.environment_request",
        value={"need": "用户预订宾馆"},
    )
    root_ref = artifacts.put_json(
        artifact_id="design",
        artifact_type="design.environment_design",
        value={"world": "hotel"},
        dependencies=(external_ref,),
    )
    _commit(runtime, root, input_refs=(external_ref,), output_ref=root_ref)
    manifest = graph.manifest(
        topology_id="topology:scheduler-test",
        external_root_refs=(external_ref,),
    )
    manifest_ref = artifacts.put_json(
        artifact_id=manifest.graph_id,
        artifact_type="control.work_graph_manifest",
        value=manifest,
        dependencies=(external_ref,),
    )
    scheduler = WorkScheduler(
        graph=graph,
        manifest=manifest,
        manifest_ref=manifest_ref,
        heads=heads,
        artifacts=artifacts,
    )
    assert set(scheduler.snapshot().ready_coordinates) == {
        member_one_coordinate,
        member_two_coordinate,
    }

    first_ref = artifacts.put_json(
        artifact_id="verifier-1",
        artifact_type="verifier.intent",
        value={"batch": 1},
        dependencies=(root_ref,),
    )
    _commit(runtime, member_one, input_refs=(external_ref, root_ref), output_ref=first_ref)
    after_first = scheduler.snapshot()
    assert member_one_coordinate not in after_first.ready_coordinates
    assert member_two_coordinate in after_first.ready_coordinates
    assert aggregate_coordinate not in after_first.ready_coordinates

    second_ref = artifacts.put_json(
        artifact_id="verifier-2",
        artifact_type="verifier.intent",
        value={"batch": 2},
        dependencies=(root_ref,),
    )
    _commit(runtime, member_two, input_refs=(external_ref, root_ref), output_ref=second_ref)
    after_second = scheduler.snapshot()
    assert aggregate_coordinate in after_second.ready_coordinates
    assert after_second.groups[0].status == "ready"
    assert scheduler.invalidation_scope(member_one_coordinate) == (aggregate_coordinate,)

    first_commit_ref = heads.read_head(member_one_coordinate).commit_ref  # type: ignore[union-attr]
    second_commit_ref = heads.read_head(member_two_coordinate).commit_ref  # type: ignore[union-attr]
    assert first_commit_ref is not None and second_commit_ref is not None
    aggregate_ref = artifacts.put_json(
        artifact_id="verifier-aggregate",
        artifact_type="verifier.intent_aggregate",
        value={"members": 2},
        dependencies=(first_ref, second_ref),
    )
    _commit(
        runtime,
        aggregate,
        input_refs=(external_ref, first_ref, second_ref),
        output_ref=aggregate_ref,
        child_commit_refs=(first_commit_ref, second_commit_ref),
    )
    committed_join = scheduler.snapshot()
    aggregate_state = next(
        item for item in committed_join.work if item.coordinate == aggregate_coordinate
    )
    assert aggregate_state.state == "committed"

    # A new parent revision makes the parent stale, while every committed
    # descendant waits at its direct causal edge. Descendants become stale only
    # after the parent commits and their new exact input closure is knowable.
    root_head = heads.read_head(root_coordinate)
    assert root_head is not None
    changed_root = root.model_copy(update={"timing_reason": "A revised scheduling policy."})
    with heads.exclusive(root_coordinate) as lock:
        runtime.supersede_stale(
            lock,
            definition=changed_root,
            input_refs=(external_ref,),
            previous=root_head,
            elapsed_wall_seconds=0,
        )
    stale = scheduler.snapshot()
    stale_states = {item.coordinate.coordinate_key: item.state for item in stale.work}
    assert stale_states[member_one_coordinate.coordinate_key] == "waiting"
    assert stale_states[member_two_coordinate.coordinate_key] == "waiting"
    assert stale_states[aggregate_coordinate.coordinate_key] == "waiting"


@pytest.mark.asyncio
async def test_scheduler_dispatches_real_leaf_executors_until_terminal(
    tmp_path: Path,
) -> None:
    scope_id = "job:dispatch"
    first_coordinate = WorkCoordinate(
        scope_id=scope_id,
        component="release",
        stage="package",
        artifact_slot="package",
    )
    second_coordinate = WorkCoordinate(
        scope_id=scope_id,
        component="registry",
        stage="publication",
        artifact_slot="publication",
    )
    first = _definition(
        scope_id=scope_id,
        component="release",
        stage="package",
        coordinate=first_coordinate,
        dependencies=(),
    )
    second = _definition(
        scope_id=scope_id,
        component="registry",
        stage="publication",
        coordinate=second_coordinate,
        dependencies=(first_coordinate,),
    )
    graph = GenerationWorkGraph.compile((first, second), mode="diagnostic")
    artifacts = ArtifactStore(tmp_path / "artifacts").issue_writer(
        producer="work-controller",
        allowed_artifact_type_prefixes=("control.", "release."),
    )
    heads = WorkControlStore(tmp_path / "heads")
    runtime = WorkControlRuntime(
        artifacts=artifacts,
        heads=heads,
        budget=LeaseBudgetLedger(Budget(wall_seconds=1_000, process_calls=20)),
    )
    request_ref = artifacts.put_json(
        artifact_id="request",
        artifact_type="control.environment_request",
        value={"need": "用户预订宾馆"},
    )
    manifest = graph.manifest(
        topology_id="topology:dispatch-test",
        external_root_refs=(request_ref,),
    )
    manifest_ref = artifacts.put_json(
        artifact_id=manifest.graph_id,
        artifact_type="control.work_graph_manifest",
        value=manifest,
        dependencies=(request_ref,),
    )
    scheduler = WorkScheduler(
        graph=graph,
        manifest=manifest,
        manifest_ref=manifest_ref,
        heads=heads,
        artifacts=artifacts,
        runtime=runtime,
    )
    definitions = {item.work_id: item for item in graph.definitions}

    async def execute(context: WorkExecutionContext) -> None:
        definition = definitions[graph.require(context.coordinate).work_id]
        input_refs = tuple(
            dict.fromkeys((*context.external_input_refs, *context.parent_output_refs))
        )
        opened_head = heads.read_head(context.coordinate)
        assert opened_head is not None
        assert opened_head.status == "running"
        assert opened_head.active_operation_ref is None
        opened_attempt = artifacts.get_json(opened_head.attempt_ref, WorkAttempt)
        assert opened_attempt.input_refs == input_refs
        output_ref = artifacts.put_json(
            artifact_id=f"output:{context.coordinate.stage}",
            artifact_type=f"release.{context.coordinate.stage}",
            value={"stage": context.coordinate.stage},
            dependencies=input_refs,
        )
        runtime.execute_deterministic_boundary(
            definition=definition,
            input_refs=input_refs,
            subject_ref=output_ref,
            output_refs=(output_ref,),
        )

    results = await scheduler.run_until_stalled(
        executors={first.work_id: execute, second.work_id: execute},
        maximum_concurrency=2,
    )

    assert tuple(item.coordinate.stage for item in results) == ("package", "publication")
    assert all(item.after_state == "committed" for item in results)
    assert scheduler.snapshot().work[-1].state == "committed"


@pytest.mark.asyncio
async def test_scheduler_dispatches_independent_tool_shards_in_one_capacity_bounded_wave(
    tmp_path: Path,
) -> None:
    """Two ready tool shards really enter the Scheduler together at capacity two.

    This is deliberately a Scheduler/WorkControl boundary rather than a mock
    Provider assertion.  The barrier proves that the second shard has opened
    before the first is allowed to commit; with capacity one it times out.
    """

    scope_id = "job:singleton-tool-wave"
    coordinates = tuple(
        WorkCoordinate(
            scope_id=scope_id,
            component="design",
            stage="world_behavior",
            artifact_slot="tool_semantics_batch",
            group_id="tool-semantics-batches",
            shard_id=f"tool-batch-{index}",
        )
        for index in (1, 2)
    )
    definitions = tuple(
        _definition(
            scope_id=scope_id,
            component="design",
            stage="world_behavior",
            coordinate=coordinate,
            dependencies=(),
        ).model_copy(
            update={
                "work_id": f"work:{coordinate.shard_id}",
                "output_slots": (
                    ArtifactSlotContract(
                        slot_id="output:tool-semantics",
                        direction="output",
                        artifact_types=("design.tool_semantics",),
                        minimum_count=1,
                        maximum_count=1,
                        producer_component="design",
                    ),
                ),
            }
        )
        for coordinate in coordinates
    )
    graph = GenerationWorkGraph.compile(definitions, mode="diagnostic", strict_input_contracts=True)
    artifacts = ArtifactStore(tmp_path / "artifacts").issue_writer(
        producer="work-controller",
        allowed_artifact_type_prefixes=("control.", "design."),
    )
    heads = WorkControlStore(tmp_path / "heads")
    runtime = WorkControlRuntime(
        artifacts=artifacts,
        heads=heads,
        budget=LeaseBudgetLedger(Budget(wall_seconds=1_000, process_calls=20)),
    )
    root_ref = artifacts.put_json(
        artifact_id="context",
        artifact_type="control.generation_context",
        value={"need": "book a room"},
    )
    manifest = graph.manifest(
        topology_id="topology:singleton-tool-wave",
        external_root_refs=(root_ref,),
    )
    manifest_ref = artifacts.put_json(
        artifact_id=manifest.graph_id,
        artifact_type="control.work_graph_manifest",
        value=manifest,
        dependencies=(root_ref,),
    )
    scheduler = WorkScheduler(
        graph=graph,
        manifest=manifest,
        manifest_ref=manifest_ref,
        heads=heads,
        artifacts=artifacts,
        runtime=runtime,
    )
    by_work_id = {definition.work_id: definition for definition in definitions}
    started: set[str] = set()
    both_started = asyncio.Event()

    async def execute(context: WorkExecutionContext) -> None:
        shard_id = context.coordinate.shard_id
        assert shard_id is not None
        started.add(shard_id)
        if len(started) == len(definitions):
            both_started.set()
        await asyncio.wait_for(both_started.wait(), timeout=0.5)
        definition = by_work_id[graph.require(context.coordinate).work_id]
        input_refs = context.external_input_refs
        output_ref = artifacts.put_json(
            artifact_id=f"tool-semantics:{shard_id}",
            artifact_type="design.tool_semantics",
            value={"tool_shard": shard_id},
            dependencies=input_refs,
        )
        runtime.execute_deterministic_boundary(
            definition=definition,
            input_refs=input_refs,
            subject_ref=output_ref,
            output_refs=(output_ref,),
        )

    results = await scheduler.run_until_stalled(
        executors={definition.work_id: execute for definition in definitions},
        maximum_concurrency=2,
    )

    assert started == {"tool-batch-1", "tool-batch-2"}
    assert len(results) == 2
    assert all(result.after_state == "committed" for result in results)


@pytest.mark.asyncio
async def test_scheduler_reexecutes_terminal_failure_for_new_definition_same_inputs(
    tmp_path: Path,
) -> None:
    """A frozen feedback variant must supersede, not inherit, an old failure.

    This is the real Scheduler-to-leaf boundary used by a feedback-only
    descendant node: the input closure is intentionally unchanged, while the
    immutable WorkDefinition changes.  The old terminal verdict must become
    ``stale`` before any executor/model can be invoked.
    """

    scope_id = "job:definition-feedback"
    coordinate = WorkCoordinate(
        scope_id=scope_id,
        component="design",
        stage="world_rules",
        artifact_slot="world_rules",
    )
    original = _definition(
        scope_id=scope_id,
        component="design",
        stage="world_rules",
        coordinate=coordinate,
        dependencies=(),
    )
    updated = original.model_copy(
        update={"timing_reason": "Diagnostic feedback changed this exact definition."}
    )
    assert original.definition_digest != updated.definition_digest
    artifacts = ArtifactStore(tmp_path / "artifacts").issue_writer(
        producer="work-controller",
        allowed_artifact_type_prefixes=("control.", "design."),
    )
    heads = WorkControlStore(tmp_path / "heads")
    runtime = WorkControlRuntime(
        artifacts=artifacts,
        heads=heads,
        budget=LeaseBudgetLedger(Budget(wall_seconds=1_000, process_calls=20)),
    )
    request_ref = artifacts.put_json(
        artifact_id="request:definition-feedback",
        artifact_type="control.environment_request",
        value={"need": "用户预订宾馆"},
    )
    failed_ref = artifacts.put_json(
        artifact_id="failed:world-rules",
        artifact_type="design.world_rules",
        value={"invalid": True},
        dependencies=(request_ref,),
    )
    runtime.execute_deterministic_boundary(
        definition=original,
        input_refs=(request_ref,),
        subject_ref=failed_ref,
        output_refs=(failed_ref,),
        issues=(
            (
                "invalid_world_rule",
                ("rules",),
                "world rules are invalid",
                "valid world rules",
            ),
        ),
    )
    original_head = heads.read_head(coordinate)
    assert original_head is not None
    assert original_head.status == "failed"

    graph = GenerationWorkGraph.compile((updated,), mode="diagnostic")
    manifest = graph.manifest(
        topology_id="topology:definition-feedback",
        external_root_refs=(request_ref,),
    )
    manifest_ref = artifacts.put_json(
        artifact_id=manifest.graph_id,
        artifact_type="control.work_graph_manifest",
        value=manifest,
        dependencies=(request_ref,),
    )
    # The descendant runner creates a fresh diagnostic runtime over the copied
    # durable heads.  Its in-memory definition registry must therefore contain
    # only the feedback variant, not the source definition that made the old
    # failure.
    execution_runtime = WorkControlRuntime(
        artifacts=artifacts,
        heads=heads,
        budget=LeaseBudgetLedger(Budget(wall_seconds=1_000, process_calls=20)),
        diagnostic_only=True,
    )
    scheduler = WorkScheduler(
        graph=graph,
        manifest=manifest,
        manifest_ref=manifest_ref,
        heads=heads,
        artifacts=artifacts,
        runtime=execution_runtime,
    )

    scheduled = next(item for item in scheduler.snapshot().work if item.coordinate == coordinate)
    assert scheduled.state == "stale"

    async def execute(context: WorkExecutionContext) -> None:
        opened_head = heads.read_head(context.coordinate)
        assert opened_head is not None
        assert opened_head.status == "running"
        assert opened_head.definition_digest == updated.definition_digest
        output_ref = artifacts.put_json(
            artifact_id="output:world-rules",
            artifact_type="design.world_rules",
            value={"valid": True},
            dependencies=(request_ref,),
        )
        execution_runtime.execute_deterministic_boundary(
            definition=updated,
            input_refs=(request_ref,),
            subject_ref=output_ref,
            output_refs=(output_ref,),
        )

    result = await scheduler.dispatch_one(
        coordinate,
        executors={updated.work_id: execute},
    )

    assert result.before_state == "stale"
    assert result.after_state == "committed"
    final_head = heads.read_head(coordinate)
    assert final_head is not None
    assert final_head.status == "committed"
    assert final_head.definition_digest == updated.definition_digest
    assert final_head.revision > original_head.revision
    original_attempt = artifacts.get_json(original_head.attempt_ref, WorkAttempt)
    final_attempt = artifacts.get_json(final_head.attempt_ref, WorkAttempt)
    assert final_attempt.parent_attempt_id == original_attempt.attempt_id


@pytest.mark.asyncio
async def test_scheduler_waits_on_uncommitted_parent_before_dispatching_authorized_repair(
    tmp_path: Path,
) -> None:
    """Old repair authority cannot outrun a parent whose active commit is unknown."""

    scope_id = "job:repair-waits-for-parent"
    parent_coordinate = WorkCoordinate(
        scope_id=scope_id,
        component="design",
        stage="world_architecture",
        artifact_slot="environment_design",
    )
    child_coordinate = WorkCoordinate(
        scope_id=scope_id,
        component="design",
        stage="world_rules",
        artifact_slot="world_rules",
    )
    parent = _definition(
        scope_id=scope_id,
        component="design",
        stage="world_architecture",
        coordinate=parent_coordinate,
        dependencies=(),
    )
    child = _definition(
        scope_id=scope_id,
        component="design",
        stage="world_rules",
        coordinate=child_coordinate,
        dependencies=(parent_coordinate,),
    )
    artifacts = ArtifactStore(tmp_path / "artifacts").issue_writer(
        producer="work-controller",
        allowed_artifact_type_prefixes=("control.", "design."),
    )
    heads = WorkControlStore(tmp_path / "heads")
    runtime = WorkControlRuntime(
        artifacts=artifacts,
        heads=heads,
        budget=LeaseBudgetLedger(Budget(wall_seconds=1_000, process_calls=20)),
    )
    request_ref = artifacts.put_json(
        artifact_id="request:repair-waits-for-parent",
        artifact_type="control.environment_request",
        value={"need": "用户预订宾馆"},
    )
    parent_ref = artifacts.put_json(
        artifact_id="design:repair-waits-for-parent",
        artifact_type="design.environment_design",
        value={"world": "hotel"},
        dependencies=(request_ref,),
    )
    _commit(runtime, parent, input_refs=(request_ref,), output_ref=parent_ref)
    child_ref = artifacts.put_json(
        artifact_id="world-rules:repair-waits-for-parent",
        artifact_type="design.world_rules",
        value={"invalid": True},
        dependencies=(parent_ref,),
    )
    runtime.execute_deterministic_boundary(
        definition=child,
        input_refs=(request_ref, parent_ref),
        subject_ref=child_ref,
        output_refs=(child_ref,),
        issues=(
            (
                "invalid_world_rule",
                ("rules",),
                "world rules are invalid",
                "valid world rules",
            ),
        ),
    )
    failed_child = heads.read_head(child_coordinate)
    assert failed_child is not None
    assert failed_child.status == "failed"
    assert failed_child.evaluation_ref is not None
    repair_ref = artifacts.put_json(
        artifact_id="repair:world-rules",
        artifact_type="control.repair_action",
        value={"fixture": "scheduler-projection-only"},
        dependencies=(failed_child.evaluation_ref,),
    )
    with heads.exclusive(child_coordinate) as lock:
        heads.authorize_infrastructure_retry(
            lock,
            expected_head=failed_child,
            next_head=failed_child.model_copy(
                update={
                    "revision": failed_child.revision + 1,
                    "status": "repair_authorized",
                    "repair_action_ref": repair_ref,
                    "invalidated_by_refs": (repair_ref,),
                    "updated_at": datetime.now(UTC),
                }
            ),
        )

    changed_parent = parent.model_copy(
        update={"timing_reason": "A revised architecture boundary invalidates its old commit."}
    )
    graph = GenerationWorkGraph.compile((changed_parent, child), mode="diagnostic")
    manifest = graph.manifest(
        topology_id="topology:repair-waits-for-parent",
        external_root_refs=(request_ref,),
    )
    manifest_ref = artifacts.put_json(
        artifact_id=manifest.graph_id,
        artifact_type="control.work_graph_manifest",
        value=manifest,
        dependencies=(request_ref,),
    )
    scheduler = WorkScheduler(
        graph=graph,
        manifest=manifest,
        manifest_ref=manifest_ref,
        heads=heads,
        artifacts=artifacts,
        runtime=runtime,
    )

    snapshot = scheduler.snapshot()
    states = {item.coordinate.coordinate_key: item for item in snapshot.work}
    assert states[parent_coordinate.coordinate_key].state == "stale"
    child_state = states[child_coordinate.coordinate_key]
    assert child_state.state == "waiting"
    assert child_state.waiting_on == (parent_coordinate,)

    async def must_not_dispatch(_context: WorkExecutionContext) -> None:
        raise AssertionError("child repair dispatched before its parent committed")

    results = await scheduler.run_until_stalled(
        executors={child.work_id: must_not_dispatch},
    )

    assert results == ()
    assert heads.read_head(child_coordinate).status == "repair_authorized"  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_scheduler_holds_committed_descendant_while_parent_is_stale(
    tmp_path: Path,
) -> None:
    """A stale committed chain is reopened one causal boundary at a time."""

    scope_id = "job:committed-child-waits-for-parent"
    parent_coordinate = WorkCoordinate(
        scope_id=scope_id,
        component="research",
        stage="research_plan",
        artifact_slot="research_plan",
    )
    child_coordinate = WorkCoordinate(
        scope_id=scope_id,
        component="research",
        stage="evidence_acquisition",
        artifact_slot="research_acquisition",
    )
    parent = _definition(
        scope_id=scope_id,
        component="research",
        stage="research_plan",
        coordinate=parent_coordinate,
        dependencies=(),
    )
    child = _definition(
        scope_id=scope_id,
        component="research",
        stage="evidence_acquisition",
        coordinate=child_coordinate,
        dependencies=(parent_coordinate,),
    )
    artifacts = ArtifactStore(tmp_path / "artifacts").issue_writer(
        producer="work-controller",
        allowed_artifact_type_prefixes=("control.", "design."),
    )
    heads = WorkControlStore(tmp_path / "heads")
    runtime = WorkControlRuntime(
        artifacts=artifacts,
        heads=heads,
        budget=LeaseBudgetLedger(Budget(wall_seconds=1_000, process_calls=20)),
    )
    request_ref = artifacts.put_json(
        artifact_id="request:committed-child-waits",
        artifact_type="control.environment_request",
        value={"need": "用户预订宾馆"},
    )
    plan_ref = artifacts.put_json(
        artifact_id="research-plan:committed-child-waits",
        artifact_type="design.research_plan",
        value={"queries": ["hotel booking"]},
        dependencies=(request_ref,),
    )
    _commit(runtime, parent, input_refs=(request_ref,), output_ref=plan_ref)
    acquisition_ref = artifacts.put_json(
        artifact_id="research-acquisition:committed-child-waits",
        artifact_type="design.research_acquisition",
        value={"evidence": ["source"]},
        dependencies=(plan_ref,),
    )
    _commit(
        runtime,
        child,
        input_refs=(request_ref, plan_ref),
        output_ref=acquisition_ref,
    )

    changed_parent = parent.model_copy(
        update={"timing_reason": "The control policy changed without changing acceptance."}
    )
    graph = GenerationWorkGraph.compile((changed_parent, child), mode="diagnostic")
    manifest = graph.manifest(
        topology_id="topology:committed-child-waits",
        external_root_refs=(request_ref,),
    )
    manifest_ref = artifacts.put_json(
        artifact_id=manifest.graph_id,
        artifact_type="control.work_graph_manifest",
        value=manifest,
        dependencies=(request_ref,),
    )
    scheduler = WorkScheduler(
        graph=graph,
        manifest=manifest,
        manifest_ref=manifest_ref,
        heads=heads,
        artifacts=artifacts,
        runtime=runtime,
    )

    states = {
        item.coordinate.coordinate_key: item
        for item in scheduler.snapshot().work
    }
    assert states[parent_coordinate.coordinate_key].state == "stale"
    child_state = states[child_coordinate.coordinate_key]
    assert child_state.state == "waiting"
    assert child_state.waiting_on == (parent_coordinate,)


@pytest.mark.asyncio
async def test_scheduler_names_ready_coordinate_when_framework_omits_its_executor(
    tmp_path: Path,
) -> None:
    """A missing leaf binding is framework failure, never an empty semantic stall."""

    scope_id = "job:missing-executor"
    coordinate = WorkCoordinate(
        scope_id=scope_id,
        component="design",
        stage="world_behavior",
        artifact_slot="tool_semantics_batch",
        group_id="tool-semantics-batches",
        shard_id="tool-batch-1",
    )
    definition = _definition(
        scope_id=scope_id,
        component="design",
        stage="world_behavior",
        coordinate=coordinate,
        dependencies=(),
    )
    graph = GenerationWorkGraph.compile((definition,), mode="diagnostic")
    artifacts = ArtifactStore(tmp_path / "artifacts").issue_writer(
        producer="work-controller",
        allowed_artifact_type_prefixes=("control.",),
    )
    root_ref = artifacts.put_json(
        artifact_id="request",
        artifact_type="control.environment_request",
        value={"need": "用户预订宾馆"},
    )
    manifest = graph.manifest(
        topology_id="topology:missing-executor",
        external_root_refs=(root_ref,),
    )
    manifest_ref = artifacts.put_json(
        artifact_id=manifest.graph_id,
        artifact_type="control.work_graph_manifest",
        value=manifest,
        dependencies=(root_ref,),
    )
    heads = WorkControlStore(tmp_path / "heads")
    scheduler = WorkScheduler(
        graph=graph,
        manifest=manifest,
        manifest_ref=manifest_ref,
        heads=heads,
        artifacts=artifacts,
        runtime=WorkControlRuntime(
            artifacts=artifacts,
            heads=heads,
            budget=LeaseBudgetLedger(Budget(wall_seconds=1_000)),
        ),
    )

    with pytest.raises(WorkExecutorMissingError) as captured:
        await scheduler.run_until_stalled(executors={})

    assert captured.value.coordinates == (coordinate,)
    assert "design.world_behavior.tool_semantics_batch" in str(captured.value)


def test_blocked_group_blocks_aggregate_with_exact_evaluation(tmp_path: Path) -> None:
    scope_id = "job:blocked-group"
    first_coordinate = WorkCoordinate(
        scope_id=scope_id,
        component="verifier",
        stage="verifier_intent",
        artifact_slot="verifier_intent",
        group_id="verifier-batches",
        shard_id="batch-1",
    )
    second_coordinate = first_coordinate.model_copy(update={"shard_id": "batch-2"})
    aggregate_coordinate = WorkCoordinate(
        scope_id=scope_id,
        component="verifier",
        stage="verifier_aggregate",
        artifact_slot="verifier_aggregate",
        group_id="verifier-batches",
    )
    first = _definition(
        scope_id=scope_id,
        component="integration",
        stage="first",
        coordinate=first_coordinate,
        dependencies=(),
    )
    second = _definition(
        scope_id=scope_id,
        component="integration",
        stage="second",
        coordinate=second_coordinate,
        dependencies=(),
    )
    aggregate = _definition(
        scope_id=scope_id,
        component="integration",
        stage="aggregate",
        coordinate=aggregate_coordinate,
        dependencies=(first_coordinate, second_coordinate),
    )
    group = WorkGroupDefinition(
        group_id="verifier-batches",
        scope_id=scope_id,
        member_coordinates=(first_coordinate, second_coordinate),
        aggregate_coordinate=aggregate_coordinate,
    )
    graph = GenerationWorkGraph.compile(
        (first, second, aggregate), groups=(group,), mode="diagnostic"
    )
    artifacts = ArtifactStore(tmp_path / "artifacts").issue_writer(
        producer="work-controller",
        allowed_artifact_type_prefixes=("control.", "verifier."),
    )
    heads = WorkControlStore(tmp_path / "heads")
    runtime = WorkControlRuntime(
        artifacts=artifacts,
        heads=heads,
        budget=LeaseBudgetLedger(Budget(wall_seconds=1_000, tool_calls=100)),
    )
    root_ref = artifacts.put_json(
        artifact_id="request",
        artifact_type="control.environment_request",
        value={"need": "hotel"},
    )
    failed_ref = artifacts.put_json(
        artifact_id="failed-intent",
        artifact_type="verifier.intent",
        value={"invalid": True},
        dependencies=(root_ref,),
    )
    runtime.execute_deterministic_boundary(
        definition=first,
        input_refs=(root_ref,),
        subject_ref=failed_ref,
        output_refs=(failed_ref,),
        issues=(("invalid_intent", ("intent",), "intent is invalid", "valid intent"),),
    )
    manifest = graph.manifest(topology_id="topology:blocked-group", external_root_refs=(root_ref,))
    manifest_ref = artifacts.put_json(
        artifact_id=manifest.graph_id,
        artifact_type="control.work_graph_manifest",
        value=manifest,
        dependencies=(root_ref,),
    )
    snapshot = WorkScheduler(
        graph=graph,
        manifest=manifest,
        manifest_ref=manifest_ref,
        heads=heads,
        artifacts=artifacts,
    ).snapshot()
    aggregate_state = next(
        item for item in snapshot.work if item.coordinate == aggregate_coordinate
    )
    assert aggregate_state.state == "blocked"
    assert len(aggregate_state.blocking_evaluation_refs) == 1


def _diagnostic_terminal_scope(tmp_path: Path, *, mark_clone: bool):
    """Build one scope whose only terminal head is a diagnostic ``observes`` verdict.

    ``FeedbackEvaluation`` requires ``readiness_effect == "observes"`` whenever
    ``diagnostic_only`` is set, so this is the exact shape every ``test-node``
    copy acquires once one node terminates inside the clone.
    """

    scope_id = "job:diagnostic-terminal"
    coordinate = WorkCoordinate(
        scope_id=scope_id,
        component="verifier",
        stage="verifier_intent",
        artifact_slot="verifier_intent",
    )
    definition = _definition(
        scope_id=scope_id,
        component="integration",
        stage="first",
        coordinate=coordinate,
        dependencies=(),
    )
    graph = GenerationWorkGraph.compile((definition,), groups=(), mode="diagnostic")
    artifacts = ArtifactStore(tmp_path / "artifacts").issue_writer(
        producer="work-controller",
        allowed_artifact_type_prefixes=("control.", "verifier."),
    )
    heads = WorkControlStore(tmp_path / "heads")
    if mark_clone:
        heads.mark_test_node_diagnostic_clone()
    runtime = WorkControlRuntime(
        artifacts=artifacts,
        heads=heads,
        budget=LeaseBudgetLedger(Budget(wall_seconds=1_000, tool_calls=100)),
        diagnostic_only=True,
    )
    root_ref = artifacts.put_json(
        artifact_id="request",
        artifact_type="control.environment_request",
        value={"need": "hotel"},
    )
    failed_ref = artifacts.put_json(
        artifact_id="failed-intent",
        artifact_type="verifier.intent",
        value={"invalid": True},
        dependencies=(root_ref,),
    )
    runtime.execute_deterministic_boundary(
        definition=definition,
        input_refs=(root_ref,),
        subject_ref=failed_ref,
        output_refs=(failed_ref,),
        issues=(("invalid_intent", ("intent",), "intent is invalid", "valid intent"),),
    )
    manifest = graph.manifest(
        topology_id="topology:diagnostic-terminal",
        external_root_refs=(root_ref,),
    )
    manifest_ref = artifacts.put_json(
        artifact_id=manifest.graph_id,
        artifact_type="control.work_graph_manifest",
        value=manifest,
        dependencies=(root_ref,),
    )
    return coordinate, graph, manifest, manifest_ref, heads, artifacts, runtime


def test_diagnostic_observes_terminal_does_not_poison_its_own_clone(tmp_path: Path) -> None:
    """A diagnostic terminal must not make its whole clone undispatchable.

    ``snapshot()`` used to require every terminal evaluation to block readiness.
    But a diagnostic verdict is contractually forbidden from blocking (it must
    be ``observes``), so a single terminated node inside a ``test-node`` copy
    raised ``terminal Work evaluation does not block readiness`` and made every
    other coordinate in that scope permanently undispatchable -- the clone
    poisoned itself, which is why repeated single-node debugging runs could never
    reach their target.
    """

    (
        coordinate,
        graph,
        manifest,
        manifest_ref,
        heads,
        artifacts,
        runtime,
    ) = _diagnostic_terminal_scope(tmp_path, mark_clone=True)

    snapshot = WorkScheduler(
        graph=graph,
        manifest=manifest,
        manifest_ref=manifest_ref,
        heads=heads,
        artifacts=artifacts,
        runtime=runtime,
    ).snapshot()

    state = next(item for item in snapshot.work if item.coordinate == coordinate)
    assert state.state == "blocked"
    assert len(state.blocking_evaluation_refs) == 1


def test_unmarked_state_root_keeps_the_strict_terminal_readiness_invariant(
    tmp_path: Path,
) -> None:
    """The allowance is scoped to a marked diagnostic clone, nothing wider.

    Without the ``test-node`` marker the original strict invariant still holds,
    so a normal release scope can never quietly accept a non-blocking terminal.
    """

    (
        _coordinate,
        graph,
        manifest,
        manifest_ref,
        heads,
        artifacts,
        runtime,
    ) = _diagnostic_terminal_scope(tmp_path, mark_clone=False)

    with pytest.raises(WorkResumeError):
        WorkScheduler(
            graph=graph,
            manifest=manifest,
            manifest_ref=manifest_ref,
            heads=heads,
            artifacts=artifacts,
            runtime=runtime,
        ).snapshot()


def _orphan_scope(tmp_path: Path):
    """Build a single-node graph and leave its head at running & no active op."""

    scope_id = "job:orphan-uncommenced"
    coordinate = WorkCoordinate(
        scope_id=scope_id,
        component="release",
        stage="package",
        artifact_slot="package",
    )
    definition = _definition(
        scope_id=scope_id,
        component="release",
        stage="package",
        coordinate=coordinate,
        dependencies=(),
    )
    graph = GenerationWorkGraph.compile((definition,), mode="diagnostic")
    artifacts = ArtifactStore(tmp_path / "artifacts").issue_writer(
        producer="work-controller",
        allowed_artifact_type_prefixes=("control.", "release."),
    )
    heads = WorkControlStore(tmp_path / "heads")
    runtime = WorkControlRuntime(
        artifacts=artifacts,
        heads=heads,
        budget=LeaseBudgetLedger(Budget(wall_seconds=1_000, process_calls=20)),
    )
    root_ref = artifacts.put_json(
        artifact_id="context:orphan",
        artifact_type="control.generation_context",
        value={"request": "hotel"},
    )
    manifest = graph.manifest(
        topology_id="topology:orphan-test",
        external_root_refs=(root_ref,),
    )
    manifest_ref = artifacts.put_json(
        artifact_id=manifest.graph_id,
        artifact_type="control.work_graph_manifest",
        value=manifest,
        dependencies=(root_ref,),
    )
    # Reproduce the SIGKILL-between-begin-and-start_operation window: the
    # Scheduler durably wrote a running head with no active operation.
    with heads.exclusive(coordinate) as lock:
        runtime.begin(
            lock,
            definition=definition,
            input_refs=(root_ref,),
            elapsed_wall_seconds=0,
        )
    return (
        scope_id,
        coordinate,
        definition,
        graph,
        manifest,
        manifest_ref,
        heads,
        artifacts,
        runtime,
        root_ref,
    )


def test_resume_uncommenced_running_resets_orphaned_head_to_fresh_attempt(
    tmp_path: Path,
) -> None:
    """AC-B1: a never-commenced running head is re-opened as a fresh attempt."""

    (
        _scope_id,
        coordinate,
        definition,
        _graph,
        _manifest,
        _manifest_ref,
        heads,
        artifacts,
        runtime,
        root_ref,
    ) = _orphan_scope(tmp_path)

    orphan_head = heads.read_head(coordinate)
    assert orphan_head is not None
    assert orphan_head.status == "running"
    assert orphan_head.active_operation_ref is None
    prior_attempt = artifacts.get_json(orphan_head.attempt_ref, WorkAttempt)
    assert prior_attempt.ordinal == 1

    with heads.exclusive(coordinate) as lock:
        reset = runtime.resume_uncommenced_running(
            lock,
            definition=definition,
            input_refs=(root_ref,),
        )

    assert reset.status == "running"
    assert reset.active_operation_ref is None
    assert reset.attempt_ref != orphan_head.attempt_ref
    fresh_attempt = artifacts.get_json(reset.attempt_ref, WorkAttempt)
    assert fresh_attempt.ordinal == prior_attempt.ordinal + 1
    assert fresh_attempt.parent_attempt_id == prior_attempt.attempt_id
    # The prior attempt is durably archived as interrupted with the distinct
    # never-commenced failure code (a new revision of the same attempt id).
    archived = next(
        candidate
        for ref in artifacts.list_revisions(prior_attempt.attempt_id)
        if (candidate := artifacts.get_json(ref, WorkAttempt)).status == "interrupted"
    )
    assert archived.failure_code == "orphaned_uncommenced_execution"


def test_resume_uncommenced_running_rejects_active_operation_and_changed_definition(
    tmp_path: Path,
) -> None:
    """AC-B1: the primitive is strictly for same-definition, never-commenced heads."""

    (
        _scope_id,
        coordinate,
        definition,
        _graph,
        _manifest,
        _manifest_ref,
        heads,
        artifacts,
        runtime,
        root_ref,
    ) = _orphan_scope(tmp_path)

    # A CHANGED definition (different inputs) is supersede authority's job, not
    # this same-definition reset.
    other_ref = artifacts.put_json(
        artifact_id="context:orphan-other",
        artifact_type="control.generation_context",
        value={"request": "airport"},
    )
    with heads.exclusive(coordinate) as lock:
        with pytest.raises(WorkRuntimeError):
            runtime.resume_uncommenced_running(
                lock,
                definition=definition,
                input_refs=(other_ref,),
            )

    # Cross the dispatch fence: a head WITH an active operation must never be
    # reset by this primitive (real-work settlement is reconcile's job).
    with heads.exclusive(coordinate) as lock:
        runtime.schedule_operation(
            lock,
            definition=definition,
            kind="proposal",
            replay_mode="queryable",
            elapsed_wall_seconds=0,
        )
    active_head = heads.read_head(coordinate)
    assert active_head is not None
    assert active_head.active_operation_ref is not None
    with heads.exclusive(coordinate) as lock:
        with pytest.raises(WorkRuntimeError):
            runtime.resume_uncommenced_running(
                lock,
                definition=definition,
                input_refs=(root_ref,),
            )


@pytest.mark.asyncio
async def test_orphaned_running_head_recovers_and_reaches_committed(
    tmp_path: Path,
) -> None:
    """AC-B2: reconciliation re-dispatches the orphan; it is not stuck forever."""

    (
        _scope_id,
        coordinate,
        definition,
        graph,
        manifest,
        manifest_ref,
        heads,
        artifacts,
        runtime,
        _root_ref,
    ) = _orphan_scope(tmp_path)

    scheduler = WorkScheduler(
        graph=graph,
        manifest=manifest,
        manifest_ref=manifest_ref,
        heads=heads,
        artifacts=artifacts,
        runtime=runtime,
    )

    orphan_head = heads.read_head(coordinate)
    assert orphan_head is not None
    orphan_attempt_ref = orphan_head.attempt_ref

    from agent_world.control.direct_runner import DirectWorkRunner

    DirectWorkRunner._reconcile_abandoned_operations(
        graph=graph,
        runtime=runtime,
        scheduler=scheduler,
    )

    # Reconciliation archives the never-commenced attempt and opens a fresh one
    # that the scheduler classifies as re-dispatchable rather than a permanently
    # pinned ``running`` head.
    reset_head = heads.read_head(coordinate)
    assert reset_head is not None
    assert reset_head.attempt_ref != orphan_attempt_ref
    after = next(item for item in scheduler.snapshot().work if item.coordinate == coordinate)
    assert after.state == "ready"

    async def execute(context: WorkExecutionContext) -> None:
        input_refs = tuple(
            dict.fromkeys((*context.external_input_refs, *context.parent_output_refs))
        )
        output_ref = artifacts.put_json(
            artifact_id=f"output:{context.coordinate.stage}",
            artifact_type=f"release.{context.coordinate.stage}",
            value={"stage": context.coordinate.stage},
            dependencies=input_refs,
        )
        runtime.execute_deterministic_boundary(
            definition=definition,
            input_refs=input_refs,
            subject_ref=output_ref,
            output_refs=(output_ref,),
        )

    results = await scheduler.run_until_stalled(
        executors={definition.work_id: execute},
        maximum_concurrency=1,
    )

    assert tuple(item.after_state for item in results) == ("committed",)
    assert scheduler.snapshot().work[-1].state == "committed"
