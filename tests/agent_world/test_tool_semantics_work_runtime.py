from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agent_world.artifact_store import ArtifactStore
from agent_world.contracts import Budget, BudgetUsage, sha256_digest
from agent_world.control.budget import LeaseBudgetLedger
from agent_world.control.telemetry import TelemetryStore
from agent_world.control.work import (
    AssurancePolicy,
    AssuranceProbeResult,
    AssuranceReport,
    OperationBudget,
    OperationRun,
    ProposalExecution,
    RepairAction,
    ValidationIssue,
    ValidationReport,
    WorkAttempt,
)
from agent_world.control.work_graph import tool_semantics_batch_definition
from agent_world.control.work_runtime import (
    WorkControlRuntime,
    WorkRuntimeError,
    restore_work_budget_ledger,
)
from agent_world.control.work_store import WorkControlStore


def _harness(tmp_path: Path):
    artifacts = ArtifactStore(tmp_path / "artifacts").issue_writer(
        producer="work-controller",
        allowed_artifact_type_prefixes=("control.", "design."),
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
            wall_seconds=1000,
            monetary_cost=5,
        )
    )
    runtime = WorkControlRuntime(artifacts=artifacts, heads=heads, budget=budget)
    definition = tool_semantics_batch_definition(
        job_id="job:hotel",
        group_id="coupling:booking",
        batch_id="batch:1",
        dependency_coordinates=(),
        agent_wall_seconds=120,
        agent_token_limit=1_000,
        agent_monetary_limit=1,
    )
    input_ref = artifacts.put_json(
        artifact_id="hotel:world-skeleton",
        artifact_type="design.world_skeleton",
        value={"entities": ["hotel", "reservation"]},
    )
    return artifacts, heads, budget, runtime, definition, input_ref


def test_real_assurance_execution_and_work_span_are_bound_to_commit(tmp_path: Path) -> None:
    artifacts, heads, budget, _runtime, base, input_ref = _harness(tmp_path)
    definition = base.model_copy(
        update={
            "assurance_policy": AssurancePolicy(
                policy_id="assurance:tool-semantics",
                runtime_profile_id="runtime:isolated-v2",
                probe_ids=("probe:reset-step", "probe:materializer"),
                claim_id=base.required_claim_id,
                effect="block_compile",
                budget=OperationBudget(
                    wall_seconds=10,
                    process_calls=1,
                    evaluation_episodes=1,
                ),
                evidence_freshness="same_candidate",
            )
        }
    )
    telemetry = TelemetryStore(tmp_path / "telemetry", commit_batch_size=1)
    runtime = WorkControlRuntime(
        artifacts=artifacts,
        heads=heads,
        budget=budget,
        telemetry=telemetry,
        trace_id="run:hotel-assurance",
    )
    output_ref = artifacts.put_json(
        artifact_id="hotel:assured-tool-semantics",
        artifact_type="design.tool_semantics_batch_source",
        value={"tools": [{"tool_id": "reserve_hotel"}]},
        dependencies=(input_ref,),
    )
    evidence_ref = artifacts.put_json(
        artifact_id="hotel:runtime-probe",
        artifact_type="control.assurance_evidence",
        value={"reset": "passed", "materializer": "passed"},
        dependencies=(output_ref,),
    )
    with heads.exclusive(definition.coordinate) as lock:
        head = runtime.begin(
            lock,
            definition=definition,
            input_refs=(input_ref,),
            elapsed_wall_seconds=0,
        )
        proposal_execution = _execution(
            _attempt(artifacts, head),
            1,
            output_commitment=output_ref.content_hash,
        )
        head = _checkpoint_proposal(
            runtime,
            artifacts,
            lock,
            definition,
            head,
            proposal_execution,
            output_refs=(output_ref,),
        )
        assurance_report = AssuranceReport(
            report_id="assurance-report:passed",
            attempt_id=_attempt(artifacts, head).attempt_id,
            coordinate=definition.coordinate,
            policy_id=definition.assurance_policy.policy_id,  # type: ignore[union-attr]
            policy_digest=definition.assurance_policy.content_digest(),  # type: ignore[union-attr]
            runtime_profile_id="runtime:isolated-v2",
            runtime_commitment=sha256_digest(b"runtime-image-v2"),
            evidence_freshness="same_candidate",
            probe_results=tuple(
                AssuranceProbeResult(
                    probe_id=probe_id,
                    status="passed",
                    evidence_refs=(evidence_ref,),
                )
                for probe_id in ("probe:reset-step", "probe:materializer")
            ),
            status="passed",
            evaluated_at=datetime.now(UTC),
        )
        head = _checkpoint_assurance(
            runtime,
            lock,
            definition,
            assurance_report,
            observed_actual=BudgetUsage(
                process_calls=1,
                evaluation_episodes=1,
            ),
        )
        attempt = _attempt(artifacts, head)
        report = ValidationReport(
            report_id="report:assured-pass",
            attempt_id=attempt.attempt_id,
            coordinate=definition.coordinate,
            policy_id=definition.validation_policy.policy_id,
            policy_digest=definition.validation_policy.content_digest(),
            subject_refs=(output_ref,),
            status="passed",
            validation_phase="tool_semantics",
            frontier_ordinal=30,
            passed_check_ids=(definition.required_claim_id,),
            evidence_refs=(evidence_ref,),
            diagnostic_quality="not_applicable",
            evaluated_at=datetime.now(UTC),
        )
        head = _checkpoint_validation_and_evaluate(
            runtime,
            artifacts,
            lock,
            definition,
            head,
            report,
            output_refs=(output_ref,),
        )
    assert head.status == "committed"
    committed_attempt = _attempt(artifacts, head)
    assert len(committed_attempt.operation_run_refs) == 3
    assert committed_attempt.telemetry_span_id is not None
    trace = telemetry.inspect_trace("run:hotel-assurance")
    operations = {item["operation"] for item in trace["spans"]}
    assert {
        "design.tool_semantics_batch",
        "work.assurance",
        "work.validation",
    } <= operations
    assert all(item["status"] != "running" for item in trace["spans"])
    telemetry.close()


def test_failed_assurance_cannot_be_overridden_by_passing_validation(tmp_path: Path) -> None:
    artifacts, heads, budget, _runtime, base, input_ref = _harness(tmp_path)
    definition = base.model_copy(
        update={
            "assurance_policy": AssurancePolicy(
                policy_id="assurance:tool-semantics",
                runtime_profile_id="runtime:isolated-v2",
                probe_ids=("probe:reset-step",),
                claim_id=base.required_claim_id,
                effect="block_compile",
                budget=OperationBudget(wall_seconds=10, process_calls=1),
                evidence_freshness="same_candidate",
            )
        }
    )
    runtime = WorkControlRuntime(artifacts=artifacts, heads=heads, budget=budget)
    output_ref = artifacts.put_json(
        artifact_id="hotel:invalid-assured-output",
        artifact_type="design.tool_semantics_batch_source",
        value={"tools": []},
        dependencies=(input_ref,),
    )
    evidence_ref = artifacts.put_json(
        artifact_id="hotel:failed-runtime-probe",
        artifact_type="control.assurance_evidence",
        value={"reset": "failed"},
        dependencies=(output_ref,),
    )
    with heads.exclusive(definition.coordinate) as lock:
        head = runtime.begin(
            lock,
            definition=definition,
            input_refs=(input_ref,),
            elapsed_wall_seconds=0,
        )
        proposal_execution = _execution(
            _attempt(artifacts, head),
            1,
            output_commitment=output_ref.content_hash,
        )
        head = _checkpoint_proposal(
            runtime,
            artifacts,
            lock,
            definition,
            head,
            proposal_execution,
            output_refs=(output_ref,),
        )
        assurance_report = AssuranceReport(
            report_id="assurance-report:failed",
            attempt_id=_attempt(artifacts, head).attempt_id,
            coordinate=definition.coordinate,
            policy_id=definition.assurance_policy.policy_id,  # type: ignore[union-attr]
            policy_digest=definition.assurance_policy.content_digest(),  # type: ignore[union-attr]
            runtime_profile_id="runtime:isolated-v2",
            runtime_commitment=sha256_digest(b"runtime-image-v2"),
            evidence_freshness="same_candidate",
            probe_results=(
                AssuranceProbeResult(
                    probe_id="probe:reset-step",
                    status="failed",
                    evidence_refs=(evidence_ref,),
                    issue_codes=("runtime_reset_failed",),
                ),
            ),
            status="failed",
            evaluated_at=datetime.now(UTC),
        )
        head = _checkpoint_assurance(
            runtime,
            lock,
            definition,
            assurance_report,
            observed_actual=BudgetUsage(process_calls=1),
        )
        attempt = _attempt(artifacts, head)
        passing_report = ValidationReport(
            report_id="report:false-pass",
            attempt_id=attempt.attempt_id,
            coordinate=definition.coordinate,
            policy_id=definition.validation_policy.policy_id,
            policy_digest=definition.validation_policy.content_digest(),
            subject_refs=(output_ref,),
            status="passed",
            validation_phase="tool_semantics",
            frontier_ordinal=30,
            passed_check_ids=(definition.required_claim_id,),
            evidence_refs=(evidence_ref,),
            diagnostic_quality="not_applicable",
            evaluated_at=datetime.now(UTC),
        )
        with pytest.raises(WorkRuntimeError, match="non-passing assurance"):
            _checkpoint_validation_and_evaluate(
                runtime,
                artifacts,
                lock,
                definition,
                head,
                passing_report,
                output_refs=(output_ref,),
            )
    assert heads.read_head(definition.coordinate).status == "running"  # type: ignore[union-attr]


def _execution(
    attempt: WorkAttempt,
    ordinal: int,
    *,
    output_commitment: str | None = None,
) -> ProposalExecution:
    now = datetime.now(UTC)
    actual = BudgetUsage(llm_tokens=100, agent_turns=1, monetary_cost=0.1)
    return ProposalExecution(
        execution_id=f"execution:hotel:{ordinal}",
        attempt_id=attempt.attempt_id,
        executor="agent",
        operation="design.tool_semantics_batch",
        status="completed",
        invocation_id=f"invocation:hotel:{ordinal}",
        provider="openai",
        model="gpt-5.4-mini",
        profile_digest=sha256_digest(b"environment-engineer-profile"),
        output_schema_digest=sha256_digest(b"tool-semantics-schema"),
        output_commitment=output_commitment or sha256_digest(f"candidate:{ordinal}".encode()),
        continuation_commitment=sha256_digest(b"private-codex-session"),
        observed_actual=actual,
        conservative_committed=actual,
        started_at=now,
        finished_at=now + timedelta(milliseconds=10),
        duration_ms=10,
    )


def _interrupted_execution(attempt: WorkAttempt) -> ProposalExecution:
    now = datetime.now(UTC)
    actual = BudgetUsage(llm_tokens=50, agent_turns=1)
    return ProposalExecution(
        execution_id=f"execution:interrupted:{attempt.ordinal}",
        attempt_id=attempt.attempt_id,
        executor="agent",
        operation="design.tool_semantics_batch",
        status="interrupted",
        invocation_id=f"invocation:interrupted:{attempt.ordinal}",
        provider="openai",
        model="gpt-5.4-mini",
        profile_digest=sha256_digest(b"environment-engineer-profile"),
        output_schema_digest=sha256_digest(b"tool-semantics-schema"),
        error_code="process_interrupted_after_proposal",
        observed_actual=actual,
        conservative_committed=actual,
        started_at=now,
        finished_at=now + timedelta(milliseconds=10),
        duration_ms=10,
    )


def _failed_report(
    attempt: WorkAttempt,
    definition,
    label: str,
    issues: tuple[ValidationIssue, ...],
    *,
    frontier: int = 20,
) -> ValidationReport:
    return ValidationReport(
        report_id=f"report:{label}",
        attempt_id=attempt.attempt_id,
        coordinate=definition.coordinate,
        policy_id=definition.validation_policy.policy_id,
        policy_digest=definition.validation_policy.content_digest(),
        status="failed",
        validation_phase="tool_semantics",
        frontier_ordinal=frontier,
        issues=issues,
        diagnostic_quality="actionable",
        evaluated_at=datetime.now(UTC),
    )


def _attempt(artifacts, head) -> WorkAttempt:
    return artifacts.get_json(head.attempt_ref, WorkAttempt)


def _checkpoint_proposal(
    runtime: WorkControlRuntime,
    artifacts,
    lock,
    definition,
    head,
    execution: ProposalExecution,
    *,
    output_refs=(),
):
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
        dispatch_id=execution.invocation_id or f"dispatch:{execution.execution_id}",
    )
    assert _attempt(artifacts, head).attempt_id == execution.attempt_id
    operation = artifacts.get_json(head.active_operation_ref, OperationRun)
    assert operation.started_at is not None
    finished_at = operation.started_at + timedelta(milliseconds=execution.duration_ms)
    execution = ProposalExecution.model_validate(
        execution.model_copy(
            update={"started_at": operation.started_at, "finished_at": finished_at}
        ).model_dump(mode="python")
    )
    return runtime.checkpoint_proposal(
        lock,
        definition=definition,
        execution=execution,
        output_refs=output_refs,
    )


def _checkpoint_validation_and_evaluate(
    runtime: WorkControlRuntime,
    artifacts,
    lock,
    definition,
    head,
    report: ValidationReport,
    *,
    output_refs=(),
    child_commit_refs=(),
    repair_mutation_roots=None,
):
    head = runtime.schedule_operation(
        lock,
        definition=definition,
        kind="validation",
        replay_mode="deterministic",
        elapsed_wall_seconds=0,
    )
    head = runtime.start_operation(
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
        output_refs=output_refs,
        child_commit_refs=child_commit_refs,
        elapsed_wall_seconds=0,
        repair_mutation_roots=repair_mutation_roots,
    )


def _checkpoint_assurance(
    runtime: WorkControlRuntime,
    lock,
    definition,
    report: AssuranceReport,
    *,
    observed_actual: BudgetUsage,
):
    runtime.schedule_operation(
        lock,
        definition=definition,
        kind="assurance",
        replay_mode="non_replayable",
        elapsed_wall_seconds=0,
    )
    runtime.start_operation(
        lock,
        definition=definition,
        dispatch_id=f"assurance:{report.attempt_id}",
    )
    return runtime.checkpoint_assurance(
        lock,
        definition=definition,
        report=report,
        observed_actual=observed_actual,
    )


def test_bad_case_strict_progress_then_unchanged_stops_without_old_control_artifacts(
    tmp_path: Path,
) -> None:
    artifacts, heads, budget, runtime, definition, input_ref = _harness(tmp_path)
    issue_a = ValidationIssue(
        code="rule_reference_missing",
        path=("tools", 0, "rules", 0, "when", "left"),
        violated_condition="Rule path must resolve against RuleContextCatalog.",
        expected_category="a declared tool argument or mutable state field",
    )
    issue_b = ValidationIssue(
        code="lifecycle_field_missing",
        path=("tools", 0, "reliability", "lifecycle_field"),
        violated_condition="Lifecycle field must be mutable on the reservation entity.",
        expected_category="a declared mutable lifecycle field",
    )
    with heads.exclusive(definition.coordinate) as lock:
        head = runtime.begin(
            lock,
            definition=definition,
            input_refs=(input_ref,),
            elapsed_wall_seconds=0,
        )
        head = _checkpoint_proposal(
            runtime,
            artifacts,
            lock,
            definition,
            head,
            _execution(_attempt(artifacts, head), 1),
        )
        report = _failed_report(_attempt(artifacts, head), definition, "a-b", (issue_a, issue_b))
        head = _checkpoint_validation_and_evaluate(
            runtime, artifacts, lock, definition, head, report
        )
        assert head.status == "repair_authorized"

        head = runtime.begin_authorized_repair(lock, definition=definition)
        head = _checkpoint_proposal(
            runtime,
            artifacts,
            lock,
            definition,
            head,
            _execution(_attempt(artifacts, head), 2),
        )
        report = _failed_report(_attempt(artifacts, head), definition, "b", (issue_b,))
        head = _checkpoint_validation_and_evaluate(
            runtime, artifacts, lock, definition, head, report
        )
        assert runtime.repairs.entries[0].outcome == "progressed"
        assert head.status == "repair_authorized"

        head = runtime.begin_authorized_repair(lock, definition=definition)
        head = _checkpoint_proposal(
            runtime,
            artifacts,
            lock,
            definition,
            head,
            _execution(_attempt(artifacts, head), 3),
        )
        report = _failed_report(_attempt(artifacts, head), definition, "b-again", (issue_b,))
        head = _checkpoint_validation_and_evaluate(
            runtime, artifacts, lock, definition, head, report
        )
        assert head.status == "failed"
        assert runtime.repairs.entries[-1].outcome == "no_progress"

    snapshot = runtime.budget_coordinator.snapshot(scope_id=definition.coordinate.scope_id)
    assert sum(item.conservative_committed.repair_attempts for item in snapshot.leases) == 2
    artifact_types = {ref.artifact_type for ref in artifacts.list_revisions()}
    assert "control.feedback_result" not in artifact_types
    assert "control.repair_target" not in artifact_types
    assert "design.semantic_node_commit" not in artifact_types
    assert "control.finding" not in artifact_types


def test_process_recovery_keeps_semantic_baseline_and_charges_repair_once(
    tmp_path: Path,
) -> None:
    artifacts, heads, budget, runtime, definition, input_ref = _harness(tmp_path)
    issue_a = ValidationIssue(
        code="rule_reference_missing",
        path=("tools", 0, "rules", 0, "when", "left"),
        violated_condition="Rule path must resolve against RuleContextCatalog.",
        expected_category="a declared tool argument or mutable state field",
    )
    issue_b = ValidationIssue(
        code="lifecycle_field_missing",
        path=("tools", 0, "reliability", "lifecycle_field"),
        violated_condition="Lifecycle field must be mutable.",
        expected_category="a declared mutable lifecycle field",
    )
    with heads.exclusive(definition.coordinate) as lock:
        head = runtime.begin(
            lock,
            definition=definition,
            input_refs=(input_ref,),
            elapsed_wall_seconds=0,
        )
        head = _checkpoint_proposal(
            runtime,
            artifacts,
            lock,
            definition,
            head,
            _execution(_attempt(artifacts, head), 1),
        )
        baseline = _failed_report(
            _attempt(artifacts, head),
            definition,
            "semantic-baseline",
            (issue_a, issue_b),
        )
        head = _checkpoint_validation_and_evaluate(
            runtime, artifacts, lock, definition, head, baseline
        )
        semantic_action_ref = head.repair_action_ref
        assert semantic_action_ref is not None
        head = runtime.begin_authorized_repair(lock, definition=definition)
        head = _checkpoint_proposal(
            runtime,
            artifacts,
            lock,
            definition,
            head,
            _interrupted_execution(_attempt(artifacts, head)),
        )
        head = runtime.restart_interrupted_repair(
            lock,
            definition=definition,
            reason_code="process_interrupted_after_proposal",
            elapsed_wall_seconds=0,
        )
        recovered = _attempt(artifacts, head)
        assert recovered.repair_action_ref == semantic_action_ref
        assert recovered.repair_attempt_charge == 0
        assert recovered.recovery_ordinal == 1
        assert (
            runtime.repairs.entries_for(
                definition,
                input_refs=(input_ref,),
            )[0].outcome
            == "authorized"
        )

        head = _checkpoint_proposal(
            runtime,
            artifacts,
            lock,
            definition,
            head,
            _execution(recovered, 3),
        )
        repaired_report = _failed_report(
            _attempt(artifacts, head),
            definition,
            "semantic-progress-after-recovery",
            (issue_b,),
        )
        head = _checkpoint_validation_and_evaluate(
            runtime, artifacts, lock, definition, head, repaired_report
        )
        assert head.status == "repair_authorized"
        first_entry = runtime.repairs.entries_for(
            definition,
            input_refs=(input_ref,),
        )[0]
        assert first_entry.outcome == "progressed"
        assert first_entry.progress == "strict_progress"
        assert first_entry.process_recovery_count == 1
        snapshot = runtime.budget_coordinator.snapshot(scope_id=definition.coordinate.scope_id)
        assert sum(item.conservative_committed.repair_attempts for item in snapshot.leases) == 1


def test_infrastructure_error_during_semantic_repair_terminalizes_without_retry(
    tmp_path: Path,
) -> None:
    """BC-45: a failed repair transport cannot strand a running WorkHead."""

    artifacts, heads, _budget, runtime, definition, input_ref = _harness(tmp_path)
    issue = ValidationIssue(
        code="tool_rule_binding_required",
        path=("tools", 0, "conditions"),
        violated_condition="Tool rules must use frozen binding ids.",
        expected_category="one frozen bound reference or lookup id",
    )
    with heads.exclusive(definition.coordinate) as lock:
        head = runtime.begin(
            lock,
            definition=definition,
            input_refs=(input_ref,),
            elapsed_wall_seconds=0,
        )
        head = _checkpoint_proposal(
            runtime,
            artifacts,
            lock,
            definition,
            head,
            _execution(_attempt(artifacts, head), 1),
        )
        baseline = _failed_report(
            _attempt(artifacts, head), definition, "semantic-baseline", (issue,)
        )
        head = _checkpoint_validation_and_evaluate(
            runtime, artifacts, lock, definition, head, baseline
        )
        assert head.status == "repair_authorized"

        head = runtime.begin_authorized_repair(lock, definition=definition)
        head = _checkpoint_proposal(
            runtime,
            artifacts,
            lock,
            definition,
            head,
            _execution(_attempt(artifacts, head), 2),
        )
        malformed_output_error = ValidationReport(
            report_id="report:repair-malformed-output",
            attempt_id=_attempt(artifacts, head).attempt_id,
            coordinate=definition.coordinate,
            policy_id=definition.validation_policy.policy_id,
            policy_digest=definition.validation_policy.content_digest(),
            status="error",
            validation_phase="tool_semantics",
            frontier_ordinal=20,
            issues=(
                ValidationIssue(
                    code="agent_backend_structured_output_invalid_json",
                    path=("operation",),
                    violated_condition="The provider returned malformed native structured output.",
                    expected_category="a configuration change outside this repair",
                    retryable=True,
                ),
            ),
            diagnostic_quality="actionable",
            evaluated_at=datetime.now(UTC),
        )
        head = _checkpoint_validation_and_evaluate(
            runtime, artifacts, lock, definition, head, malformed_output_error
        )

    assert head.status == "failed"
    assert head.repair_action_ref is None
    entry = runtime.repairs.entries_for(definition, input_refs=(input_ref,))[0]
    assert entry.progress == "unknown"
    assert entry.outcome == "no_progress"


def test_work_attempt_telemetry_projects_authorized_repair_and_recovery(
    tmp_path: Path,
) -> None:
    """Telemetry mirrors durable repair lineage but cannot create repair authority."""

    artifacts, heads, budget, _runtime, definition, input_ref = _harness(tmp_path)
    telemetry = TelemetryStore(tmp_path / "telemetry", commit_batch_size=1)
    runtime = WorkControlRuntime(
        artifacts=artifacts,
        heads=heads,
        budget=budget,
        telemetry=telemetry,
        trace_id="run:repair-telemetry",
    )
    issue = ValidationIssue(
        code="rule_reference_missing",
        path=("tools", 0, "rules", 0, "when", "left"),
        violated_condition="Rule path must resolve against RuleContextCatalog.",
        expected_category="a declared tool argument or mutable state field",
    )
    with heads.exclusive(definition.coordinate) as lock:
        head = runtime.begin(
            lock,
            definition=definition,
            input_refs=(input_ref,),
            elapsed_wall_seconds=0,
        )
        head = _checkpoint_proposal(
            runtime,
            artifacts,
            lock,
            definition,
            head,
            _execution(_attempt(artifacts, head), 1),
        )
        head = _checkpoint_validation_and_evaluate(
            runtime,
            artifacts,
            lock,
            definition,
            head,
            _failed_report(_attempt(artifacts, head), definition, "telemetry", (issue,)),
        )
        action_ref = head.repair_action_ref
        assert action_ref is not None
        action = artifacts.get_json(action_ref, RepairAction)
        head = runtime.begin_authorized_repair(lock, definition=definition)
        head = _checkpoint_proposal(
            runtime,
            artifacts,
            lock,
            definition,
            head,
            _interrupted_execution(_attempt(artifacts, head)),
        )
        runtime.restart_interrupted_repair(
            lock,
            definition=definition,
            reason_code="process_interrupted_after_proposal",
            elapsed_wall_seconds=0,
        )

    spans = [
        item
        for item in telemetry.inspect_trace("run:repair-telemetry")["spans"]
        if item["operation"] == definition.proposal_policy.operation
    ]
    by_attempt = {item["attempt"]: item for item in spans}
    assert set(by_attempt) == {1, 2, 3}
    initial = json.loads(by_attempt[1]["attributes_json"])
    authorized = json.loads(by_attempt[2]["attributes_json"])
    recovered = json.loads(by_attempt[3]["attributes_json"])
    assert by_attempt[1]["repair_depth"] == 0
    assert initial["repair_mode"] == "initial"
    assert by_attempt[2]["repair_depth"] == action.repair_attempt_ordinal
    assert authorized["repair_mode"] == action.decision
    assert authorized["repair_action_revision"] == action_ref.revision_id
    assert by_attempt[3]["repair_depth"] == action.repair_attempt_ordinal
    assert recovered["repair_mode"] == "process_recovery"
    assert recovered["process_recovery_ordinal"] == 1
    telemetry.close()


def test_repaired_tool_batch_creates_only_exact_resumable_work_commit(tmp_path: Path) -> None:
    artifacts, heads, budget, runtime, definition, input_ref = _harness(tmp_path)
    issue = ValidationIssue(
        code="rule_reference_missing",
        path=("tools", 0, "rules", 0, "when", "left"),
        violated_condition="Rule path must resolve against RuleContextCatalog.",
        expected_category="a declared state field",
    )
    with heads.exclusive(definition.coordinate) as lock:
        head = runtime.begin(
            lock,
            definition=definition,
            input_refs=(input_ref,),
            elapsed_wall_seconds=0,
        )
        head = _checkpoint_proposal(
            runtime,
            artifacts,
            lock,
            definition,
            head,
            _execution(_attempt(artifacts, head), 1),
        )
        failed = _failed_report(_attempt(artifacts, head), definition, "invalid", (issue,))
        head = _checkpoint_validation_and_evaluate(
            runtime, artifacts, lock, definition, head, failed
        )
        # Simulate a process crash immediately after RepairAction + lease +
        # ledger + head were durable. No in-memory repair state is reused.
        runtime = WorkControlRuntime(
            artifacts=artifacts,
            heads=heads,
            budget=restore_work_budget_ledger(
                artifacts,
                reserved=budget.reserved,
                scope_id=definition.coordinate.scope_id,
            ),
            repair_scope_id=definition.coordinate.scope_id,
        )
        head = runtime.begin_authorized_repair(lock, definition=definition)
        output_ref = artifacts.put_json(
            artifact_id="hotel:tool-semantics:valid",
            artifact_type="design.tool_semantics_batch_source",
            value={"tools": [{"tool_id": "reserve_hotel"}]},
            dependencies=(input_ref,),
        )
        proposal = _execution(
            _attempt(artifacts, head),
            2,
            output_commitment=output_ref.content_hash,
        )
        head = _checkpoint_proposal(
            runtime,
            artifacts,
            lock,
            definition,
            head,
            proposal,
            output_refs=(output_ref,),
        )
        attempt = _attempt(artifacts, head)
        passed = ValidationReport(
            report_id="report:passed",
            attempt_id=attempt.attempt_id,
            coordinate=definition.coordinate,
            policy_id=definition.validation_policy.policy_id,
            policy_digest=definition.validation_policy.content_digest(),
            subject_refs=(output_ref,),
            status="passed",
            validation_phase="tool_semantics",
            frontier_ordinal=30,
            passed_check_ids=(definition.required_claim_id,),
            diagnostic_quality="not_applicable",
            evaluated_at=datetime.now(UTC),
        )
        head = _checkpoint_validation_and_evaluate(
            runtime,
            artifacts,
            lock,
            definition,
            head,
            passed,
            output_refs=(output_ref,),
        )
        assert head.status == "committed"

    active = heads.require_active_commit(
        definition=definition,
        input_refs=(input_ref,),
        artifacts=artifacts,
    )
    assert active is not None
    commit, commit_ref = active
    assert output_ref in commit.output_refs
    assert commit_ref == head.commit_ref
