from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from agent_world.artifact_store import ArtifactStore
from agent_world.contracts import Budget, BudgetUsage, sha256_digest
from agent_world.control.budget import LeaseBudgetLedger
from agent_world.control.work import (
    ProposalExecution,
    ValidationIssue,
    ValidationReport,
    WorkAttempt,
)
from agent_world.control.work_graph import tool_semantics_batch_definition
from agent_world.control.work_runtime import WorkControlRuntime, restore_work_budget_ledger
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
    )
    input_ref = artifacts.put_json(
        artifact_id="hotel:world-skeleton",
        artifact_type="design.world_skeleton",
        value={"entities": ["hotel", "reservation"]},
    )
    return artifacts, heads, budget, runtime, definition, input_ref


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
        output_commitment=output_commitment
        or sha256_digest(f"candidate:{ordinal}".encode()),
        continuation_commitment=sha256_digest(b"private-codex-session"),
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
        head = runtime.checkpoint_proposal(
            lock,
            definition=definition,
            execution=_execution(_attempt(artifacts, head), 1),
        )
        head = runtime.evaluate(
            lock,
            definition=definition,
            report=_failed_report(
                _attempt(artifacts, head), definition, "a-b", (issue_a, issue_b)
            ),
            elapsed_wall_seconds=0,
        )
        assert head.status == "repair_authorized"

        head = runtime.begin_authorized_repair(lock, definition=definition)
        head = runtime.checkpoint_proposal(
            lock,
            definition=definition,
            execution=_execution(_attempt(artifacts, head), 2),
        )
        head = runtime.evaluate(
            lock,
            definition=definition,
            report=_failed_report(_attempt(artifacts, head), definition, "b", (issue_b,)),
            elapsed_wall_seconds=0,
        )
        assert runtime.repairs.entries[0].outcome == "progressed"
        assert head.status == "repair_authorized"

        head = runtime.begin_authorized_repair(lock, definition=definition)
        head = runtime.checkpoint_proposal(
            lock,
            definition=definition,
            execution=_execution(_attempt(artifacts, head), 3),
        )
        head = runtime.evaluate(
            lock,
            definition=definition,
            report=_failed_report(
                _attempt(artifacts, head), definition, "b-again", (issue_b,)
            ),
            elapsed_wall_seconds=0,
        )
        assert head.status == "failed"
        assert runtime.repairs.entries[-1].outcome == "no_progress"

    assert budget.usage(elapsed_wall_seconds=0).repair_attempts == 2
    artifact_types = {ref.artifact_type for ref in artifacts.list_revisions()}
    assert "control.feedback_result" not in artifact_types
    assert "control.repair_target" not in artifact_types
    assert "design.semantic_node_commit" not in artifact_types
    assert "control.finding" not in artifact_types


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
        head = runtime.checkpoint_proposal(
            lock,
            definition=definition,
            execution=_execution(_attempt(artifacts, head), 1),
        )
        head = runtime.evaluate(
            lock,
            definition=definition,
            report=_failed_report(_attempt(artifacts, head), definition, "invalid", (issue,)),
            elapsed_wall_seconds=0,
        )
        # Simulate a process crash immediately after RepairAction + lease +
        # ledger + head were durable. No in-memory repair state is reused.
        runtime = WorkControlRuntime(
            artifacts=artifacts,
            heads=heads,
            budget=restore_work_budget_ledger(artifacts, reserved=budget.reserved),
        )
        head = runtime.begin_authorized_repair(lock, definition=definition)
        output_ref = artifacts.put_json(
            artifact_id="hotel:tool-semantics:valid",
            artifact_type="design.tool_semantics_batch_source",
            value={"tools": [{"tool_id": "reserve_hotel"}]},
            dependencies=(input_ref,),
        )
        head = runtime.checkpoint_proposal(
            lock,
            definition=definition,
            execution=_execution(
                _attempt(artifacts, head),
                2,
                output_commitment=output_ref.content_hash,
            ),
        )
        attempt = _attempt(artifacts, head)
        passed = ValidationReport(
            report_id="report:passed",
            attempt_id=attempt.attempt_id,
            coordinate=definition.coordinate,
            policy_id=definition.validation_policy.policy_id,
            policy_digest=definition.validation_policy.content_digest(),
            subject_ref=output_ref,
            status="passed",
            validation_phase="tool_semantics",
            frontier_ordinal=30,
            passed_check_ids=("tool_semantics.closed",),
            diagnostic_quality="not_applicable",
            evaluated_at=datetime.now(UTC),
        )
        head = runtime.evaluate(
            lock,
            definition=definition,
            report=passed,
            output_refs=(output_ref,),
            elapsed_wall_seconds=0,
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
