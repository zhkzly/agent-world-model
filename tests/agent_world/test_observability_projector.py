from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from agent_world.artifact_store import ArtifactStore
from agent_world.builder.models import BuildRecord
from agent_world.contracts import (
    Budget,
    BudgetUsage,
    EnvironmentCandidate,
    PackageFile,
    PublicSelfCheckDescriptor,
    RuntimeLaunch,
    TaskMaterializerDescriptor,
    sha256_digest,
)
from agent_world.control.budget import LeaseBudgetLedger
from agent_world.control.telemetry import TelemetryStore
from agent_world.control.work import (
    OperationRun,
    ProposalExecution,
    ValidationIssue,
    ValidationReport,
    WorkAttempt,
    WorkCoordinate,
    WorkDefinition,
)
from agent_world.control.work_graph import tool_semantics_batch_definition
from agent_world.control.work_runtime import WorkControlRuntime
from agent_world.control.work_store import WorkControlStore
from agent_world.observability import (
    CoordinateScene,
    ObservabilityReader,
    ObservabilityRoot,
    RunSceneIndex,
    SceneHead,
    SceneIssue,
    SceneProjector,
    fold,
    safe_dynamic_text,
)
from agent_world.observability.scene import (
    MAX_COORDINATE_POINTERS,
    MAX_TOP_ISSUES,
    MAX_UNRESOLVED_ISSUES,
)


def _candidate_input(artifacts):
    """Persist the real candidate/build relation used for gate-to-file lookup."""

    design_ref = artifacts.put_json(
        artifact_id="design:scene",
        artifact_type="design.world_skeleton",
        value={"name": "scene fixture"},
    )
    implementation_ref = artifacts.put_json(
        artifact_id="implementation:scene",
        artifact_type="build.implementation_contract",
        value={"contract": "scene fixture"},
        dependencies=(design_ref,),
    )
    source_snapshot_ref = artifacts.put_json(
        artifact_id="source-snapshot:scene",
        artifact_type="build.source_workspace_snapshot",
        value={"source": "scene fixture"},
        dependencies=(implementation_ref,),
    )
    task_schema_ref = artifacts.put_json(
        artifact_id="task-schema:scene",
        artifact_type="build.task_materialization_schema",
        value={"schema": "scene fixture"},
        dependencies=(implementation_ref,),
    )
    curriculum_ref = artifacts.put_json(
        artifact_id="curriculum:scene",
        artifact_type="build.curriculum",
        value={"curriculum": "scene fixture"},
        dependencies=(design_ref,),
    )
    public_verifier_ref = artifacts.put_json(
        artifact_id="public-verifier:scene",
        artifact_type="build.public_verifier",
        value={"verifier": "scene fixture"},
        dependencies=(implementation_ref,),
    )
    lineage_ref = artifacts.put_json(
        artifact_id="implementation-lineage:scene",
        artifact_type="build.implementation_lineage",
        value={"lineage": "scene fixture"},
        dependencies=(source_snapshot_ref, implementation_ref),
    )
    build_ref = artifacts.put_json(
        artifact_id="build:scene",
        artifact_type="build.record",
        value=BuildRecord(
            build_id="build:scene",
            candidate_id="candidate:scene",
            candidate_revision=1,
            implementation_contract_ref=implementation_ref,
            source_snapshot_ref=source_snapshot_ref,
            completion_hash=sha256_digest(b"scene completion"),
            files=(
                PackageFile(
                    path="candidate/runtime.py",
                    content_hash=sha256_digest(b"runtime"),
                    size_bytes=7,
                    role="runtime",
                ),
                PackageFile(
                    path="candidate/materializer.py",
                    content_hash=sha256_digest(b"materializer"),
                    size_bytes=12,
                    role="task_materializer",
                ),
                PackageFile(
                    path="candidate/verifier.py",
                    content_hash=sha256_digest(b"verifier"),
                    size_bytes=8,
                    role="public_verifier",
                ),
            ),
            validations=("declared_file_closure",),
            agent_turn_number=1,
            public_self_check_argv=(".venv/bin/python", "-m", "candidate.verifier"),
        ),
        dependencies=(source_snapshot_ref, lineage_ref),
    )
    manifest_ref = artifacts.put_json(
        artifact_id="candidate-manifest:scene",
        artifact_type="build.candidate_manifest",
        value={"manifest": "scene fixture"},
        dependencies=(build_ref,),
    )
    candidate = EnvironmentCandidate(
        candidate_id="candidate:scene",
        revision=1,
        design_ref=design_ref,
        implementation_contract_ref=implementation_ref,
        source_workspace_snapshot_ref=source_snapshot_ref,
        build_artifact_ref=build_ref,
        runtime=RuntimeLaunch(argv=(".venv/bin/python", "-m", "candidate.runtime")),
        task_materializer=TaskMaterializerDescriptor(
            entrypoint="candidate.materializer:materialize",
            entry_path="candidate/materializer.py",
            output_schema_ref=task_schema_ref,
            curriculum_ref=curriculum_ref,
        ),
        public_self_check=PublicSelfCheckDescriptor(
            argv=(".venv/bin/python", "-m", "candidate.verifier"),
            entry_path="candidate/verifier.py",
        ),
        public_verifier_ref=public_verifier_ref,
        candidate_manifest_ref=manifest_ref,
        implementation_lineage_ref=lineage_ref,
    )
    return artifacts.put_json(
        artifact_id="candidate:scene",
        artifact_type="build.environment_candidate",
        value=candidate,
        dependencies=(
            design_ref,
            implementation_ref,
            source_snapshot_ref,
            build_ref,
            manifest_ref,
            lineage_ref,
        ),
    )


def _harness(tmp_path: Path):
    artifacts = ArtifactStore(tmp_path / "artifacts").issue_writer(
        producer="work-controller",
        allowed_artifact_type_prefixes=("build.", "control.", "design."),
    )
    heads = WorkControlStore(tmp_path / "work-control")
    budget = LeaseBudgetLedger(
        Budget(
            llm_tokens=10_000,
            agent_turns=5,
            repair_attempts=3,
            tool_calls=10,
            process_calls=10,
            evaluation_episodes=10,
            wall_seconds=1_000,
            monetary_cost=5,
        )
    )
    canary = "canary-observability-secret"
    root = ObservabilityRoot(tmp_path / "state")
    projector = SceneProjector(
        root=root,
        artifacts=artifacts,
        heads=heads,
        known_secret_canaries=(canary,),
    )
    runtime = WorkControlRuntime(
        artifacts=artifacts,
        heads=heads,
        budget=budget,
        projector=projector,
    )
    scope_id = f"job:{canary}"
    base = tool_semantics_batch_definition(
        job_id=scope_id,
        group_id="coupling:scene",
        batch_id="batch:scene",
        dependency_coordinates=(),
        agent_wall_seconds=120,
        agent_token_limit=1_000,
        agent_monetary_limit=1,
    )
    coordinate = WorkCoordinate(
        scope_id=scope_id,
        component="integration",
        stage="runtime_integration",
        artifact_slot="candidate_runtime",
    )
    definition = WorkDefinition.model_validate(
        base.model_copy(update={"coordinate": coordinate}).model_dump(mode="python")
    )
    input_ref = artifacts.put_json(
        artifact_id="design-input:scene",
        artifact_type="design.world_skeleton",
        value={"entities": ["scene"]},
    )
    return (
        artifacts,
        heads,
        runtime,
        definition,
        input_ref,
        _candidate_input(artifacts),
        root,
        canary,
    )


def _attempt(artifacts, head) -> WorkAttempt:
    return artifacts.get_json(head.attempt_ref, WorkAttempt)


def _execution(attempt: WorkAttempt, definition: WorkDefinition, ordinal: int) -> ProposalExecution:
    now = datetime.now(UTC)
    actual = BudgetUsage(llm_tokens=100, agent_turns=1, monetary_cost=0.1)
    return ProposalExecution(
        execution_id=f"execution:scene:{ordinal}",
        attempt_id=attempt.attempt_id,
        executor="agent",
        operation=definition.proposal_policy.operation,
        status="completed",
        invocation_id=f"invocation:scene:{ordinal}",
        provider="openai",
        model="gpt-5.4-mini",
        profile_digest=sha256_digest(b"environment-engineer-profile"),
        output_schema_digest=sha256_digest(b"scene-output-schema"),
        output_commitment=sha256_digest(f"candidate:scene:{ordinal}".encode()),
        continuation_commitment=sha256_digest(b"scene-continuation"),
        observed_actual=actual,
        conservative_committed=actual,
        started_at=now,
        finished_at=now + timedelta(milliseconds=10),
        duration_ms=10,
    )


def _checkpoint_proposal(runtime, artifacts, lock, definition, execution: ProposalExecution):
    runtime.schedule_operation(
        lock,
        definition=definition,
        kind="proposal",
        replay_mode="queryable",
        elapsed_wall_seconds=0,
    )
    head = runtime.start_operation(
        lock,
        definition=definition,
        dispatch_id=execution.invocation_id or execution.execution_id,
    )
    operation = artifacts.get_json(head.active_operation_ref, OperationRun)
    assert operation.started_at is not None
    finished = operation.started_at + timedelta(milliseconds=execution.duration_ms)
    settled = ProposalExecution.model_validate(
        execution.model_copy(
            update={"started_at": operation.started_at, "finished_at": finished}
        ).model_dump(mode="python")
    )
    return runtime.checkpoint_proposal(
        lock,
        definition=definition,
        execution=settled,
    )


def _checkpoint_failed_evaluation(runtime, artifacts, lock, definition, head, report):
    runtime.schedule_operation(
        lock,
        definition=definition,
        kind="validation",
        replay_mode="deterministic",
        elapsed_wall_seconds=0,
    )
    runtime.start_operation(
        lock,
        definition=definition,
        dispatch_id=f"validation:{report.attempt_id}",
    )
    head = runtime.checkpoint_validation(
        lock,
        definition=definition,
        report=report,
        observed_actual=BudgetUsage(),
    )
    assert _attempt(artifacts, head).validation_report_ref is not None
    return runtime.evaluate(
        lock,
        definition=definition,
        report=report,
        elapsed_wall_seconds=0,
    )


def _failed_runtime_report(
    attempt: WorkAttempt,
    definition: WorkDefinition,
    *,
    label: str,
    violated_condition: str,
    issue_code: str = "integration_gate_runtime_protocol_fail",
    frontier_ordinal: int = 20,
) -> ValidationReport:
    return ValidationReport(
        report_id=f"report:scene:{label}",
        attempt_id=attempt.attempt_id,
        coordinate=definition.coordinate,
        policy_id=definition.validation_policy.policy_id,
        policy_digest=definition.validation_policy.content_digest(),
        status="failed",
        validation_phase=definition.validation_policy.validation_phase,
        frontier_ordinal=frontier_ordinal,
        issues=(
            ValidationIssue(
                code=issue_code,
                path=("integration", "gate", 0),
                violated_condition=violated_condition,
                expected_category="a Runtime v2 handshake response",
            ),
        ),
        diagnostic_quality="actionable",
        evaluated_at=datetime.now(UTC),
    )


def test_projector_materializes_secret_safe_thrashing_candidate_scene(tmp_path: Path) -> None:
    artifacts, heads, runtime, definition, input_ref, candidate_ref, root, canary = _harness(
        tmp_path
    )
    violated_condition = f"Runtime handshake omitted its protocol declaration ({canary})."

    with heads.exclusive(definition.coordinate) as lock:
        head = runtime.begin(
            lock,
            definition=definition,
            input_refs=(input_ref, candidate_ref),
            elapsed_wall_seconds=0,
        )
        head = _checkpoint_proposal(
            runtime,
            artifacts,
            lock,
            definition,
            _execution(_attempt(artifacts, head), definition, 1),
        )
        head = _checkpoint_failed_evaluation(
            runtime,
            artifacts,
            lock,
            definition,
            head,
            _failed_runtime_report(
                _attempt(artifacts, head),
                definition,
                label="first",
                violated_condition=violated_condition,
            ),
        )
        assert head.status == "repair_authorized"

        head = runtime.begin_authorized_repair(lock, definition=definition)
        head = _checkpoint_proposal(
            runtime,
            artifacts,
            lock,
            definition,
            _execution(_attempt(artifacts, head), definition, 2),
        )
        head = _checkpoint_failed_evaluation(
            runtime,
            artifacts,
            lock,
            definition,
            head,
            _failed_runtime_report(
                _attempt(artifacts, head),
                definition,
                label="again",
                violated_condition=violated_condition,
            ),
        )

    assert head.status == "failed"
    scene_scope_id = safe_dynamic_text(
        definition.coordinate.scope_id,
        known_secret_canaries=(canary,),
    )
    assert scene_scope_id.startswith("sha256:")
    assert not (root.root / definition.coordinate.scope_id).exists()
    index = RunSceneIndex.model_validate_json(root.scene_json_path(scene_scope_id).read_bytes())
    assert index.stuck_coordinate is not None
    assert index.stuck_reason == "thrashing"
    assert index.frontier_delta == 0
    coordinate = CoordinateScene.model_validate_json(
        root.coordinate_json_path(
            scene_scope_id,
            index.stuck_coordinate.coordinate_key,
        ).read_bytes()
    )
    assert coordinate.frontier_progress == "no_progress"
    assert coordinate.candidate_file == "candidate/runtime.py"
    assert coordinate.repair_target == "generated_candidate_code"
    assert coordinate.top_issues[0].violated_condition.startswith("sha256:")
    scene_markdown = root.scene_markdown_path(scene_scope_id).read_text()
    assert "candidate/runtime.py" in scene_markdown
    assert "WorldSpec and the gate are frozen" in scene_markdown
    coordinate_markdown = root.coordinate_markdown_path(
        scene_scope_id,
        coordinate.coordinate_key,
    ).read_text()
    assert "frozen WorldSpec and gate are not editable (DRIFT)" in coordinate_markdown
    tier_a_text = "\n".join(
        (
            root.index_path.read_text(),
            root.scene_json_path(scene_scope_id).read_text(),
            scene_markdown,
            root.coordinate_json_path(
                scene_scope_id,
                coordinate.coordinate_key,
            ).read_text(),
            coordinate_markdown,
        )
    )
    assert canary not in tier_a_text
    frontier_lines = (
        root.frontier_path(
            scene_scope_id,
            coordinate.coordinate_key,
        )
        .read_text()
        .splitlines()
    )
    assert len(frontier_lines) == 2
    assert len(heads.read_scope_heads(definition.coordinate.scope_id)) == 1


def test_observe_phase_four_queries_and_tier_a_retention(tmp_path: Path) -> None:
    """Exercise queries from real terminal attempts, not replay fixtures."""

    artifacts, heads, runtime, definition, input_ref, candidate_ref, root, canary = _harness(
        tmp_path
    )
    telemetry = TelemetryStore(tmp_path / "telemetry")
    runtime.telemetry = telemetry
    runtime.trace_id = "trace:observability-query"
    runtime.run_id = "run:observability-query"
    assert runtime.projector is not None
    runtime.projector.telemetry = telemetry

    with heads.exclusive(definition.coordinate) as lock:
        head = runtime.begin(
            lock,
            definition=definition,
            input_refs=(input_ref, candidate_ref),
            elapsed_wall_seconds=0,
        )
        head = _checkpoint_proposal(
            runtime,
            artifacts,
            lock,
            definition,
            _execution(_attempt(artifacts, head), definition, 1),
        )
        first_report = _failed_runtime_report(
            _attempt(artifacts, head),
            definition,
            label="frontier-first",
            violated_condition="The Runtime response is missing its protocol version.",
            frontier_ordinal=20,
        )
        head = _checkpoint_failed_evaluation(
            runtime,
            artifacts,
            lock,
            definition,
            head,
            first_report,
        )
        assert head.status == "repair_authorized"

        head = runtime.begin_authorized_repair(lock, definition=definition)
        head = _checkpoint_proposal(
            runtime,
            artifacts,
            lock,
            definition,
            _execution(_attempt(artifacts, head), definition, 2),
        )
        second_report = _failed_runtime_report(
            _attempt(artifacts, head),
            definition,
            label="frontier-second",
            violated_condition="The reachable Runtime endpoint still violates the frozen contract.",
            issue_code="integration_gate_task_reachability_fail",
            frontier_ordinal=21,
        )
        head = _checkpoint_failed_evaluation(
            runtime,
            artifacts,
            lock,
            definition,
            head,
            second_report,
        )
    assert head.status == "repair_authorized"

    comparison_scope_id = "job:observability-comparison"
    comparison_base = tool_semantics_batch_definition(
        job_id=comparison_scope_id,
        group_id="coupling:scene",
        batch_id="batch:scene",
        dependency_coordinates=(),
        agent_wall_seconds=120,
        agent_token_limit=1_000,
        agent_monetary_limit=1,
    )
    comparison_coordinate = WorkCoordinate(
        scope_id=comparison_scope_id,
        component="integration",
        stage="runtime_integration",
        artifact_slot="candidate_runtime",
    )
    comparison_definition = WorkDefinition.model_validate(
        comparison_base.model_copy(
            update={"coordinate": comparison_coordinate}
        ).model_dump(mode="python")
    )
    with heads.exclusive(comparison_coordinate) as lock:
        comparison_head = runtime.begin(
            lock,
            definition=comparison_definition,
            input_refs=(input_ref, candidate_ref),
            elapsed_wall_seconds=0,
        )
    assert comparison_head.status == "running"

    reader = ObservabilityReader(
        root=root,
        artifacts=artifacts,
        heads=heads,
        telemetry=telemetry,
        known_secret_canaries=(canary,),
        tier_a_keep_last_scopes=64,
    )
    frontier_diff = reader.frontier_diff(
        definition.coordinate.scope_id,
        definition.coordinate.coordinate_key,
    )
    issues = frontier_diff["issues"]
    assert issues["added"]["issue_ids"] == list(second_report.blocking_issue_ids)
    assert issues["removed"]["issue_ids"] == list(first_report.blocking_issue_ids)
    assert issues["retained"]["issue_ids"] == []
    assert frontier_diff["frontier_ordinal_delta"] == 1

    replay = reader.replay(
        definition.coordinate.scope_id,
        definition.coordinate.coordinate_key,
    )
    assert replay["source"] == "tier_b_telemetry"
    assert [attempt["status"] for attempt in replay["attempts"]] == ["failed", "failed"]
    assert [attempt["frontier_ordinal"] for attempt in replay["attempts"]] == [20, 21]

    comparison = reader.compare(
        baseline_scope_id=definition.coordinate.scope_id,
        candidate_scope_id=comparison_scope_id,
    )
    first_divergence = comparison["first_diverging_coordinate"]
    assert first_divergence is not None
    assert first_divergence["baseline"]["status"] == "repair_authorized"
    assert first_divergence["candidate"]["status"] == "running"
    assert canary not in str((frontier_diff, replay, comparison))

    retaining_reader = ObservabilityReader(
        root=root,
        artifacts=artifacts,
        heads=heads,
        telemetry=telemetry,
        known_secret_canaries=(canary,),
        tier_a_keep_last_scopes=1,
    )
    safe_primary_scope = safe_dynamic_text(
        definition.coordinate.scope_id,
        known_secret_canaries=(canary,),
    )
    retaining_reader.scene(definition.coordinate.scope_id, force_rebuild=True)
    primary_directory = root.root / safe_primary_scope
    os.utime(primary_directory, ns=(1, 1))
    retaining_reader.scene(comparison_scope_id, force_rebuild=True)
    assert not (primary_directory / "scene.json").exists()

    terminal_events = telemetry.inspect_trace("trace:observability-query")["events"]
    assert any(item["event_type"] == "work.attempt_terminal" for item in terminal_events)
    assert canary not in str(terminal_events)
    rebuilt = retaining_reader.scene(definition.coordinate.scope_id, force_rebuild=True)
    assert rebuilt.cache_status == "rebuilt"
    assert (primary_directory / "scene.json").exists()


def test_projector_failure_never_changes_the_work_attempt_result(tmp_path: Path) -> None:
    artifacts, heads, runtime, definition, input_ref, _candidate_ref, root, canary = _harness(
        tmp_path
    )
    malformed_candidate_ref = artifacts.put_json(
        artifact_id="candidate:malformed-scene",
        artifact_type="build.environment_candidate",
        value={"not": "an EnvironmentCandidate"},
    )

    with heads.exclusive(definition.coordinate) as lock:
        head = runtime.begin(
            lock,
            definition=definition,
            input_refs=(input_ref, malformed_candidate_ref),
            elapsed_wall_seconds=0,
        )
        head = _checkpoint_proposal(
            runtime,
            artifacts,
            lock,
            definition,
            _execution(_attempt(artifacts, head), definition, 1),
        )
        head = _checkpoint_failed_evaluation(
            runtime,
            artifacts,
            lock,
            definition,
            head,
            _failed_runtime_report(
                _attempt(artifacts, head),
                definition,
                label="projection-isolated",
                violated_condition="Runtime protocol evidence is incomplete.",
            ),
        )

    assert head.status == "repair_authorized"
    scene_scope_id = safe_dynamic_text(
        definition.coordinate.scope_id,
        known_secret_canaries=(canary,),
    )
    assert not (root.root / scene_scope_id).exists()


def test_fold_caps_wide_coordinate_and_issue_collections() -> None:
    now = datetime.now(UTC)
    graph_digest = sha256_digest(b"wide graph")
    heads = tuple(
        SceneHead(
            scope_id="job:wide-observability",
            coordinate_key=sha256_digest(f"coordinate:{coordinate}".encode()),
            coordinate_label=f"integration.runtime_integration.slot:{coordinate}",
            head_status="failed",
            revision=1,
            attempt_ref_revision=sha256_digest(f"attempt-ref:{coordinate}".encode()),
            attempt_ref_id=f"attempt:wide:{coordinate}",
            attempt_ordinal=2,
            failure_code="validation_failed",
            frontier_ordinal=20,
            pipeline_stage="Integration",
            repair_authority="none",
            input_fingerprint=sha256_digest(f"input:{coordinate}".encode()),
            issues=tuple(
                SceneIssue(
                    normalized_identity=sha256_digest(f"issue:{coordinate}:{issue}".encode()),
                    code="integration_gate_runtime_protocol_fail",
                    path=("integration", "gate", issue),
                    violated_condition=f"Runtime protocol finding {issue}.",
                    expected_category="a Runtime v2 handshake response",
                    severity="blocker",
                    actionable=True,
                    gate_id="runtime_protocol",
                    candidate_file="candidate/runtime.py",
                )
                for issue in range(40 if coordinate == 0 else 1)
            ),
            previous_issue_ids=(
                (sha256_digest(f"issue:{coordinate}:0".encode()),)
                if coordinate == MAX_COORDINATE_POINTERS
                else ()
            ),
            run_id=None,
            graph_digest=graph_digest,
            updated_at=now + timedelta(microseconds=coordinate),
        )
        for coordinate in range(MAX_COORDINATE_POINTERS + 4)
    )

    scene = fold(heads, ())

    assert len(scene.index.coordinate_pointers) == MAX_COORDINATE_POINTERS
    assert scene.index.additional_stuck_count == 4
    assert scene.index.stuck_coordinate is not None
    thrashing_key = heads[MAX_COORDINATE_POINTERS].coordinate_key
    assert scene.index.stuck_reason == "thrashing"
    assert scene.index.stuck_coordinate.coordinate_key == thrashing_key
    assert scene.index.coordinate_pointers[0].coordinate_key == thrashing_key
    wide_coordinate = next(
        item for item in scene.coordinates if item.unresolved_issue_overflow_count
    )
    assert len(wide_coordinate.unresolved_issue_ids) == MAX_UNRESOLVED_ISSUES
    assert wide_coordinate.unresolved_issue_overflow_count == 8
    assert len(wide_coordinate.top_issues) == MAX_TOP_ISSUES


def test_fold_never_guesses_a_candidate_file_for_a_multi_file_gate() -> None:
    issue = SceneIssue(
        normalized_identity=sha256_digest(b"supply-chain-issue"),
        code="release_gate_supply_chain_fail",
        path=("release", "gate", 0),
        violated_condition="The Candidate closure has an unresolved supply-chain finding.",
        expected_category="a complete verified Candidate source closure",
        severity="blocker",
        actionable=True,
        gate_id="supply_chain",
        candidate_file=None,
        multi_file_gate=True,
    )
    head = SceneHead(
        scope_id="job:multi-file-gate",
        coordinate_key=sha256_digest(b"multi-file-coordinate"),
        coordinate_label="judge.release_assurance.candidate",
        head_status="failed",
        revision=2,
        attempt_ref_revision=sha256_digest(b"multi-file-attempt"),
        attempt_ref_id="attempt:multi-file",
        attempt_ordinal=2,
        failure_code="validation_failed",
        frontier_ordinal=20,
        pipeline_stage="Judge",
        repair_authority="none",
        input_fingerprint=sha256_digest(b"multi-file-input"),
        issues=(issue,),
        previous_issue_ids=(),
        run_id=None,
        graph_digest=sha256_digest(b"multi-file-graph"),
        updated_at=datetime.now(UTC),
    )

    coordinate = fold((head,), ()).coordinates[0]

    assert coordinate.candidate_file is None
    assert coordinate.repair_target == "needs_human"


def _designer_head(
    *,
    validation_status,
    code: str,
    violated_condition: str,
    routes_repair_to_parent: bool = False,
) -> SceneHead:
    """A Designer-stage failed head, parameterised by its terminal lane.

    This mirrors the production ``design.world_behavior.tool_semantics_batch``
    coordinate on attempt 2: the only variable that must decide the repair lane
    is the terminal ``ValidationReport.status`` (error = infrastructure,
    failed = a real rejected proposal), never the pipeline stage.
    """

    issue = SceneIssue(
        normalized_identity=sha256_digest(f"designer-issue:{code}".encode()),
        code=code,
        path=("operation",),
        violated_condition=violated_condition,
        expected_category="one fresh execution under the declared replay policy",
        severity="blocker",
        actionable=True,
        gate_id=None,
        candidate_file=None,
    )
    return SceneHead(
        scope_id="job:designer-lane",
        coordinate_key=sha256_digest(f"designer-coordinate:{code}".encode()),
        coordinate_label="design.world_behavior.tool_semantics_batch",
        head_status="failed",
        revision=2,
        attempt_ref_revision=sha256_digest(f"designer-attempt:{code}".encode()),
        attempt_ref_id=f"attempt:designer:{code}",
        attempt_ordinal=2,
        failure_code=code,
        frontier_ordinal=1,
        pipeline_stage="Designer",
        repair_authority="none",
        input_fingerprint=sha256_digest(b"designer-input"),
        issues=(issue,),
        previous_issue_ids=(),
        run_id=None,
        graph_digest=sha256_digest(b"designer-graph"),
        updated_at=datetime.now(UTC),
        validation_status=validation_status,
        routes_repair_to_parent=routes_repair_to_parent,
    )


def test_fold_routes_designer_transport_terminal_to_infrastructure_not_design() -> None:
    """A backend/transport terminal on a Designer coordinate must not tell the
    agent to edit the frozen WorldSpec.

    This is the deterministic reproduction of the observed thrashing loop: the
    DirectLlmBackend intermittently returns a completed-but-not-JSON response
    (``ValidationReport.status == "error"``), and the scene previously routed
    any Designer-stage issue to ``design_worldspec`` -> ``review_design_worldspec``,
    driving edits to the frozen design that could never fix a transport fault.
    """

    head = _designer_head(
        validation_status="error",
        code="agent_backend_direct_structured_output_invalid_json",
        violated_condition="the Agent backend returned a non-success terminal result",
    )

    scene = fold((head,), ())
    coordinate = scene.coordinates[0]

    assert coordinate.validation_status == "error"
    assert coordinate.repair_target == "infrastructure_transport"
    assert coordinate.repair_target != "design_worldspec"
    assert scene.index.next_action_hint == "inspect_infrastructure"
    assert scene.index.next_action_hint != "review_design_worldspec"


def test_fold_keeps_genuine_designer_semantic_failure_on_design_lane() -> None:
    """A rejected proposal that routed its repair upstream stays on the design lane.

    The parent repair route is the leaf's own statement that the defect is not
    owned here, so the transport and proposal lanes must not blind the scene to a
    true frozen-design defect.
    """

    head = _designer_head(
        validation_status="failed",
        code="design_world_behavior_semantic_incoherence",
        violated_condition="The proposed tool semantics contradict the frozen requirements.",
        routes_repair_to_parent=True,
    )

    scene = fold((head,), ())
    coordinate = scene.coordinates[0]

    assert coordinate.validation_status == "failed"
    assert coordinate.repair_target == "design_worldspec"
    assert scene.index.next_action_hint == "review_design_worldspec"


def test_fold_routes_self_inconsistent_proposal_to_the_proposal_lane() -> None:
    """A proposal that violates its own contract must be revised, not the design.

    Observed live on ``design.world_behavior.tool_semantics_batch``: the batch
    referenced a ``timeout_error_code`` it never declared in its own errors
    section.  That defect lives in the output this coordinate just produced, and
    no parent repair route was committed, so directing the agent at the frozen
    WorldSpec would repeat the original thrashing loop with a new failure class.
    """

    head = _designer_head(
        validation_status="failed",
        code="reliability_timeout_error_unknown",
        violated_condition="semantic contract reliability_timeout_error_unknown",
        routes_repair_to_parent=False,
    )

    scene = fold((head,), ())
    coordinate = scene.coordinates[0]

    assert coordinate.validation_status == "failed"
    assert coordinate.repair_target == "proposal_semantics"
    assert coordinate.repair_target != "design_worldspec"
    assert scene.index.next_action_hint == "revise_proposal"
    assert scene.index.next_action_hint != "review_design_worldspec"
