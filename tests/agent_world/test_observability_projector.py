from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from agent_world.artifact_store import ArtifactStore
from agent_world.builder.models import BuilderWorkspaceProgress, BuildRecord
from agent_world.builder.service import EnvironmentBuilder
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
from agent_world.control.work_graph import (
    structured_agent_work_definition,
    tool_semantics_batch_definition,
)
from agent_world.control.work_runtime import WorkControlRuntime
from agent_world.control.work_store import WorkControlStore
from agent_world.invocation.contracts import InvocationError
from agent_world.invocation.structured_diagnostics import (
    safe_terminal_condition,
    safe_terminal_expected_category,
    safe_terminal_remediation,
)
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


def test_contract_falls_back_to_the_exact_work_definition_for_a_design_node(
    tmp_path: Path,
) -> None:
    """A design scene's contract pointer must not falsely require a Candidate."""

    artifacts, heads, runtime, _definition, _input_ref, _candidate_ref, root, canary = _harness(
        tmp_path
    )
    definition = structured_agent_work_definition(
        scope_id=f"job:{canary}:design-contract",
        component="design",
        stage="contract_probe",
        artifact_slot="contract_probe",
        dependency_coordinates=(),
        claim_id="design.contract_probe.compiles",
        claim=f"The private claim {canary} is not projected into the Agent view.",
        timing_reason=f"The private timing rationale {canary} stays durable only.",
        output_contract_id="contract:design-contract-probe.v1",
        allowed_mutation_roots=("/proposal",),
        agent_wall_seconds=30,
        agent_token_limit=100,
    )
    with heads.exclusive(definition.coordinate) as lock:
        head = runtime.begin(
            lock,
            definition=definition,
            input_refs=(),
            elapsed_wall_seconds=0,
        )
    assert head.status == "running"

    reader = ObservabilityReader(
        root=root,
        artifacts=artifacts,
        heads=heads,
        telemetry=TelemetryStore(tmp_path / "telemetry"),
        known_secret_canaries=(canary,),
    )
    contract = reader.contract(definition.coordinate.scope_id, definition.coordinate.coordinate_key)

    assert contract["contract_kind"] == "work_definition"
    assert contract["read_only_reference"] is True
    assert contract["do_not_modify"] == ["framework_work_definition", "control_plane"]
    assert contract["proposal"] == {
        "executor": "agent",
        "operation": "design.contract_probe",
        "replay_mode": "non_replayable",
        "agent_role": "environment_engineer",
        "capability_profile_id": "profile:environment-engineer",
        "output_contract_id": "contract:design-contract-probe.v1",
        "implementation_revision_id": "framework.impl.unversioned.v0",
    }
    assert contract["validation"]["validation_phase"] == "contract_probe"
    assert contract["work"]["allowed_mutation_roots"] == ["/proposal"]
    assert contract["input_slots"] == []
    assert contract["output_slots"] == []
    assert canary not in str(contract)


def _failed_runtime_report(
    attempt: WorkAttempt,
    definition: WorkDefinition,
    *,
    label: str,
    violated_condition: str,
    remediation: str | None = None,
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
                remediation=remediation,
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
                remediation="Return the exact Runtime v2 protocol declaration.",
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
    assert (
        coordinate.top_issues[0].remediation == "Return the exact Runtime v2 protocol declaration."
    )
    scene_markdown = root.scene_markdown_path(scene_scope_id).read_text()
    assert "candidate/runtime.py" in scene_markdown
    assert "WorldSpec and the gate are frozen" in scene_markdown
    coordinate_markdown = root.coordinate_markdown_path(
        scene_scope_id,
        coordinate.coordinate_key,
    ).read_text()
    assert "frozen WorldSpec and gate are not editable (DRIFT)" in coordinate_markdown
    assert "Fix: Return the exact Runtime v2 protocol declaration." in coordinate_markdown
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


def test_projector_does_not_fabricate_progress_for_a_timeout(tmp_path: Path) -> None:
    """A timed-out Agent operation must be debuggable from the safe scene.

    This constructs the real WorkAttempt -> proposal OperationRun -> validation
    OperationRun -> FeedbackEvaluation boundary.  It deliberately supplies no
    proposal artifact or progress event: the scene must expose timing and the
    failed proposal phase without treating a terminal timestamp as progress or
    the frozen design as the repair subject.
    """

    artifacts, heads, runtime, definition, input_ref, candidate_ref, root, canary = _harness(
        tmp_path
    )
    with heads.exclusive(definition.coordinate) as lock:
        head = runtime.begin(
            lock,
            definition=definition,
            input_refs=(input_ref, candidate_ref),
            elapsed_wall_seconds=0,
        )
        runtime.schedule_operation(
            lock,
            definition=definition,
            kind="proposal",
            replay_mode="non_replayable",
            elapsed_wall_seconds=0,
        )
        head = runtime.start_operation(
            lock,
            definition=definition,
            dispatch_id="dispatch:scene:timeout",
        )
        operation = artifacts.get_json(head.active_operation_ref, OperationRun)
        assert operation.started_at is not None
        observed = BudgetUsage(agent_turns=1)
        unknown = BudgetUsage(llm_tokens=definition.proposal_policy.budget.llm_tokens)
        timeout_execution = ProposalExecution(
            execution_id="execution:scene:timeout",
            attempt_id=_attempt(artifacts, head).attempt_id,
            executor="agent",
            operation=definition.proposal_policy.operation,
            status="failed",
            invocation_id="dispatch:scene:timeout",
            provider="openai",
            model="grok-4.5",
            profile_digest=sha256_digest(b"timeout-profile"),
            output_schema_digest=sha256_digest(b"timeout-schema"),
            error_code="agent_backend_direct_timeout",
            observed_actual=observed,
            unknown_upper_bound=unknown,
            conservative_committed=BudgetUsage(
                agent_turns=1,
                llm_tokens=definition.proposal_policy.budget.llm_tokens,
            ),
            started_at=operation.started_at,
            finished_at=operation.started_at + timedelta(milliseconds=1),
            duration_ms=1,
        )
        head = runtime.checkpoint_proposal(
            lock,
            definition=definition,
            execution=timeout_execution,
        )
        report = ValidationReport(
            report_id="report:scene:timeout",
            attempt_id=_attempt(artifacts, head).attempt_id,
            coordinate=definition.coordinate,
            policy_id=definition.validation_policy.policy_id,
            policy_digest=definition.validation_policy.content_digest(),
            status="error",
            validation_phase=definition.validation_policy.validation_phase,
            frontier_ordinal=definition.validation_policy.frontier_ordinal,
            issues=(
                ValidationIssue(
                    code="agent_backend_direct_timeout",
                    path=("operation",),
                    violated_condition="the Agent backend returned a non-success terminal result",
                    expected_category="one fresh execution under the declared replay policy",
                ),
            ),
            diagnostic_quality="actionable",
            evaluated_at=datetime.now(UTC),
        )
        _checkpoint_failed_evaluation(runtime, artifacts, lock, definition, head, report)

    scene_scope_id = safe_dynamic_text(
        definition.coordinate.scope_id,
        known_secret_canaries=(canary,),
    )
    index = RunSceneIndex.model_validate_json(root.scene_json_path(scene_scope_id).read_bytes())
    coordinate = CoordinateScene.model_validate_json(
        root.coordinate_json_path(
            scene_scope_id,
            index.coordinate_pointers[0].coordinate_key,
        ).read_bytes()
    )
    assert coordinate.repair_target == "infrastructure_transport"
    assert coordinate.attempt_elapsed_ms is not None
    assert coordinate.first_progress_elapsed_ms is None
    assert coordinate.last_completed_phase == "validation"
    assert coordinate.terminal_failure_phase == "proposal"
    assert coordinate.terminal_failure_elapsed_ms == 1
    coordinate_markdown = root.coordinate_markdown_path(
        scene_scope_id,
        coordinate.coordinate_key,
    ).read_text()
    assert "Elapsed:" in coordinate_markdown
    assert "First progress:" not in coordinate_markdown
    assert "Terminal failure phase: proposal (1 ms)" in coordinate_markdown
    assert "Last completed phase: validation" in coordinate_markdown


def test_projector_routes_codex_physical_output_ceiling_to_continuation(
    tmp_path: Path,
) -> None:
    """Project a real failure boundary without mislabeling it as transport.

    The live Builder invocation reached the Provider's physical output ceiling,
    while its old scene said ``transport_or_connection``.  This reproduces the
    durable WorkAttempt -> ProposalExecution -> ValidationReport ->
    FeedbackEvaluation -> SceneProjector route with the closed terminal facts
    that the worker now emits.  It proves feedback tells the project Agent to
    make an explicit continuation/split decision, not to blindly retry.
    """

    artifacts, heads, runtime, definition, input_ref, candidate_ref, root, canary = _harness(
        tmp_path
    )
    terminal = InvocationError(
        code="turn_failed_output_limit",
        message="turn_failed_output_limit",
        retryable=True,
        details={
            "terminal_error_shape": "object",
            "codex_error_info": "enum:other",
            "terminal_status": "incomplete",
            "terminal_reason": "max_output_tokens",
        },
    )

    with heads.exclusive(definition.coordinate) as lock:
        head = runtime.begin(
            lock,
            definition=definition,
            input_refs=(input_ref, candidate_ref),
            elapsed_wall_seconds=0,
        )
        runtime.schedule_operation(
            lock,
            definition=definition,
            kind="proposal",
            replay_mode="non_replayable",
            elapsed_wall_seconds=0,
        )
        head = runtime.start_operation(
            lock,
            definition=definition,
            dispatch_id="dispatch:scene:output-limit",
        )
        operation = artifacts.get_json(head.active_operation_ref, OperationRun)
        assert operation.started_at is not None
        execution = ProposalExecution(
            execution_id="execution:scene:output-limit",
            attempt_id=_attempt(artifacts, head).attempt_id,
            executor="agent",
            operation=definition.proposal_policy.operation,
            status="failed",
            invocation_id="dispatch:scene:output-limit",
            provider="openai",
            model="gpt-5.3-codex-spark",
            profile_digest=sha256_digest(b"output-limit-profile"),
            output_schema_digest=sha256_digest(b"output-limit-schema"),
            error_code="agent_backend_turn_failed_output_limit",
            observed_actual=BudgetUsage(agent_turns=1),
            unknown_upper_bound=BudgetUsage(
                llm_tokens=definition.proposal_policy.budget.llm_tokens
            ),
            conservative_committed=BudgetUsage(
                agent_turns=1,
                llm_tokens=definition.proposal_policy.budget.llm_tokens,
            ),
            started_at=operation.started_at,
            finished_at=operation.started_at + timedelta(milliseconds=126_104),
            duration_ms=126_104,
        )
        head = runtime.checkpoint_proposal(
            lock,
            definition=definition,
            execution=execution,
        )
        report = ValidationReport(
            report_id="report:scene:output-limit",
            attempt_id=_attempt(artifacts, head).attempt_id,
            coordinate=definition.coordinate,
            policy_id=definition.validation_policy.policy_id,
            policy_digest=definition.validation_policy.content_digest(),
            status="error",
            validation_phase=definition.validation_policy.validation_phase,
            frontier_ordinal=definition.validation_policy.frontier_ordinal,
            issues=(
                ValidationIssue(
                    code="agent_backend_turn_failed_output_limit",
                    path=("operation", "proposal"),
                    violated_condition=safe_terminal_condition(terminal),
                    expected_category=safe_terminal_expected_category(terminal) or "",
                    remediation=safe_terminal_remediation(terminal),
                    retryable=False,
                ),
            ),
            diagnostic_quality="informative",
            evaluated_at=datetime.now(UTC),
        )
        head = _checkpoint_failed_evaluation(
            runtime,
            artifacts,
            lock,
            definition,
            head,
            report,
        )

    assert head.status == "failed"
    scene_scope_id = safe_dynamic_text(
        definition.coordinate.scope_id,
        known_secret_canaries=(canary,),
    )
    index = RunSceneIndex.model_validate_json(root.scene_json_path(scene_scope_id).read_bytes())
    coordinate = CoordinateScene.model_validate_json(
        root.coordinate_json_path(
            scene_scope_id,
            index.coordinate_pointers[0].coordinate_key,
        ).read_bytes()
    )
    issue = coordinate.top_issues[0]
    assert issue.code == "agent_backend_turn_failed_output_limit"
    assert "physical turn" in issue.violated_condition
    assert "session-bound continuation" in issue.expected_category
    assert issue.remediation is not None
    assert "continuation checkpoint" in issue.remediation
    markdown = root.coordinate_markdown_path(
        scene_scope_id,
        coordinate.coordinate_key,
    ).read_text()
    assert "physical turn" in markdown
    assert "continuation checkpoint" in markdown
    assert "not an ordinary transport retry" in markdown
    assert "Verify the Provider liveness route" not in markdown


def test_projector_binds_safe_runtime_activity_and_workspace_heartbeat(
    tmp_path: Path,
) -> None:
    """Project one real WorkAttempt/telemetry/heartbeat boundary without a transcript.

    The pre-change scene could show neither child-Invocation liveness nor the
    Builder's content-free workspace heartbeat.  This exercise uses the normal
    proposal and validation state transitions, rather than hand-writing a
    scene, and proves activity classes cannot leak a compact item id.
    """

    artifacts, heads, runtime, definition, input_ref, candidate_ref, root, canary = _harness(
        tmp_path
    )
    telemetry = TelemetryStore(tmp_path / "telemetry")
    runtime.trace_id = "trace:scene-runtime-activity"
    runtime.run_id = "run:scene-runtime-activity"
    runtime.telemetry = telemetry
    assert runtime.projector is not None
    runtime.projector.telemetry = telemetry
    activity_canary = "activity-item-id-must-not-persist"

    try:
        with heads.exclusive(definition.coordinate) as lock:
            head = runtime.begin(
                lock,
                definition=definition,
                input_refs=(input_ref, candidate_ref),
                elapsed_wall_seconds=0,
            )
            runtime.schedule_operation(
                lock,
                definition=definition,
                kind="proposal",
                replay_mode="non_replayable",
                elapsed_wall_seconds=0,
            )
            head = runtime.start_operation(
                lock,
                definition=definition,
                dispatch_id="dispatch:scene:runtime-activity",
            )
            operation = artifacts.get_json(head.active_operation_ref, OperationRun)
            assert operation.started_at is not None
            attempt = _attempt(artifacts, head)
            invocation_id = "dispatch:scene:runtime-activity"
            span = telemetry.start_span(
                trace_id=runtime.trace_id,
                component="invocation",
                operation="agent.invoke",
                run_id=runtime.run_id,
                node="environment-engineer",
                attributes={"invocation_id_hash": sha256_digest(invocation_id.encode())},
            )
            span.progress(
                "item/started",
                {"item": {"id": activity_canary, "type": "reasoning"}},
            )
            span.progress(
                "item/updated",
                {"item": {"id": activity_canary, "type": "commandExecution"}},
            )
            span.progress(
                "item/updated",
                {"item": {"id": activity_canary, "type": "fileChange"}},
            )
            span.finish(status="failed", error_code="turn_failed_unclassified_codex_error")
            artifacts.put_json(
                artifact_id=EnvironmentBuilder.workspace_progress_artifact_id(
                    runtime.run_id,
                    attempt.attempt_id,
                ),
                artifact_type="build.workspace_progress",
                value=BuilderWorkspaceProgress(
                    run_id=runtime.run_id,
                    attempt_id=attempt.attempt_id,
                    lineage_id="lineage:scene-runtime-activity",
                    observed_at=datetime.now(UTC),
                    status="turn_terminal",
                    file_count=0,
                    total_bytes=0,
                    metadata_digest=sha256_digest(b"scene workspace heartbeat"),
                ),
                dependencies=(input_ref,),
            )
            execution = ProposalExecution(
                execution_id="execution:scene:runtime-activity",
                attempt_id=attempt.attempt_id,
                executor="agent",
                operation=definition.proposal_policy.operation,
                status="failed",
                invocation_id=invocation_id,
                provider="openai",
                model="gpt-5.4-mini",
                profile_digest=sha256_digest(b"runtime-activity-profile"),
                output_schema_digest=sha256_digest(b"runtime-activity-schema"),
                error_code="agent_backend_turn_failed_unclassified_codex_error",
                observed_actual=BudgetUsage(agent_turns=1),
                conservative_committed=BudgetUsage(agent_turns=1),
                started_at=operation.started_at,
                finished_at=operation.started_at + timedelta(milliseconds=15),
                duration_ms=15,
            )
            head = runtime.checkpoint_proposal(
                lock,
                definition=definition,
                execution=execution,
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
                    label="runtime-activity",
                    violated_condition="the Agent terminated before committing a candidate",
                ),
            )
    finally:
        telemetry.close()

    scene_scope_id = safe_dynamic_text(
        definition.coordinate.scope_id,
        known_secret_canaries=(canary,),
    )
    index = RunSceneIndex.model_validate_json(root.scene_json_path(scene_scope_id).read_bytes())
    coordinate = CoordinateScene.model_validate_json(
        root.coordinate_json_path(
            scene_scope_id,
            index.coordinate_pointers[0].coordinate_key,
        ).read_bytes()
    )
    assert coordinate.runtime_agent_liveness is not None
    assert coordinate.runtime_agent_liveness.observed_event_count == 3
    assert coordinate.runtime_agent_liveness.activity is not None
    assert coordinate.runtime_agent_liveness.activity.reasoning_event_count == 1
    assert coordinate.runtime_agent_liveness.activity.command_event_count == 1
    assert coordinate.runtime_agent_liveness.activity.file_change_event_count == 1
    assert coordinate.candidate_workspace_liveness is not None
    assert coordinate.candidate_workspace_liveness.status == "turn_terminal"
    assert coordinate.candidate_workspace_liveness.file_count == 0
    markdown = root.coordinate_markdown_path(
        scene_scope_id,
        coordinate.coordinate_key,
    ).read_text()
    assert "Runtime Agent liveness:" in markdown
    assert "reasoning-events=1" in markdown
    assert "command-events=1" in markdown
    assert "file-change-events=1" in markdown
    assert "Candidate workspace heartbeat: turn_terminal" in markdown
    assert activity_canary not in markdown
    assert (
        activity_canary
        not in root.coordinate_json_path(
            scene_scope_id,
            coordinate.coordinate_key,
        ).read_text()
    )


def test_projector_projects_running_invocation_liveness_as_an_estimate(
    tmp_path: Path,
) -> None:
    """A live proposal must not look idle merely because it has no terminal record.

    This exercises the real durable WorkAttempt -> running OperationRun ->
    invocation telemetry -> SceneProjector path.  Before the fix, the exact
    same state rendered neither elapsed time nor child-Agent first progress,
    because only a terminal ProposalExecution supplied an invocation id.
    """

    artifacts, heads, runtime, definition, input_ref, candidate_ref, root, canary = _harness(
        tmp_path
    )
    telemetry = TelemetryStore(tmp_path / "telemetry")
    runtime.trace_id = "trace:scene-running-invocation"
    runtime.run_id = "run:scene-running-invocation"
    runtime.telemetry = telemetry
    assert runtime.projector is not None
    runtime.projector.telemetry = telemetry
    invocation_id = "dispatch:scene:running-invocation"

    try:
        with heads.exclusive(definition.coordinate) as lock:
            head = runtime.begin(
                lock,
                definition=definition,
                input_refs=(input_ref, candidate_ref),
                elapsed_wall_seconds=0,
            )
            runtime.schedule_operation(
                lock,
                definition=definition,
                kind="proposal",
                replay_mode="non_replayable",
                elapsed_wall_seconds=0,
            )
            head = runtime.start_operation(
                lock,
                definition=definition,
                dispatch_id=invocation_id,
            )
            assert head.status == "running"
            span = telemetry.start_span(
                trace_id=runtime.trace_id,
                component="invocation",
                operation="agent.invoke",
                run_id=runtime.run_id,
                node="environment-engineer",
                attributes={"invocation_id_hash": sha256_digest(invocation_id.encode())},
            )
            span.progress("item/started", {"item": {"type": "reasoning"}})
            span.heartbeat("direct_awaiting_stream_event")
            runtime.projector.rebuild(definition.coordinate.scope_id, run_id=runtime.run_id)
            span.finish(status="passed")
    finally:
        telemetry.close()

    scene_scope_id = safe_dynamic_text(
        definition.coordinate.scope_id,
        known_secret_canaries=(canary,),
    )
    index = RunSceneIndex.model_validate_json(root.scene_json_path(scene_scope_id).read_bytes())
    coordinate = CoordinateScene.model_validate_json(
        root.coordinate_json_path(
            scene_scope_id,
            index.coordinate_pointers[0].coordinate_key,
        ).read_bytes()
    )
    assert coordinate.head_status == "running"
    assert coordinate.attempt_elapsed_ms is not None
    assert coordinate.attempt_elapsed_estimated is True
    assert coordinate.first_progress_elapsed_ms is not None
    assert coordinate.runtime_agent_liveness is not None
    assert coordinate.runtime_agent_liveness.first_progress_elapsed_ms is not None
    assert coordinate.runtime_agent_liveness.last_local_heartbeat_elapsed_ms is not None
    assert coordinate.runtime_agent_liveness.last_local_heartbeat_phase == (
        "direct_awaiting_stream_event"
    )
    assert coordinate.runtime_agent_liveness.terminal_elapsed_ms is None
    markdown = root.coordinate_markdown_path(
        scene_scope_id,
        coordinate.coordinate_key,
    ).read_text()
    assert "Elapsed (running estimate):" in markdown
    assert "First progress:" in markdown
    assert "Runtime Agent liveness:" in markdown
    assert "local heartbeat" in markdown
    assert "not Provider progress" in markdown


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
        comparison_base.model_copy(update={"coordinate": comparison_coordinate}).model_dump(
            mode="python"
        )
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
