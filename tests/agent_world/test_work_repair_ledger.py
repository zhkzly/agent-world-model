from __future__ import annotations

from datetime import UTC, datetime

import pytest

from agent_world.contracts import ArtifactRef, sha256_digest
from agent_world.control.work import (
    RepairAction,
    ValidationIssue,
    ValidationReport,
)
from agent_world.control.work_graph import tool_semantics_batch_definition
from agent_world.control.work_repair import WorkRepairDenied, WorkRepairLedger


def _ref(label: str, artifact_type: str) -> ArtifactRef:
    return ArtifactRef(
        artifact_id=f"artifact:{label}",
        revision_id=sha256_digest(f"revision:{label}".encode()),
        artifact_type=artifact_type,
        content_hash=sha256_digest(f"content:{label}".encode()),
        media_type="application/json",
        size_bytes=1,
    )


def _definition():
    return tool_semantics_batch_definition(
        job_id="job:hotel",
        group_id="coupling:booking",
        batch_id="batch:1",
        dependency_coordinates=(),
        agent_wall_seconds=120,
        agent_token_limit=10_000,
    )


def _issue(code: str, index: int = 0) -> ValidationIssue:
    return ValidationIssue(
        code=code,
        path=("tools", index, "reliability"),
        violated_condition=f"{code} violates the executable contract",
        expected_category="a reference to a declared mutable field",
    )


def _report(
    label: str,
    issues: tuple[ValidationIssue, ...],
    *,
    frontier: int = 20,
    status: str = "failed",
    quality: str = "actionable",
) -> ValidationReport:
    definition = _definition()
    subject_ref = (
        _ref(f"subject:{label}", "design.tool_semantics_batch_source")
        if status == "passed"
        else None
    )
    return ValidationReport(
        report_id=f"report:{label}",
        attempt_id=f"attempt:{label}",
        coordinate=definition.coordinate,
        policy_id=definition.validation_policy.policy_id,
        policy_digest=definition.validation_policy.content_digest(),
        subject_ref=subject_ref,
        status=status,
        validation_phase="tool_semantics" if frontier else "invocation_backend",
        frontier_ordinal=frontier,
        issues=issues,
        evidence_refs=(_ref(f"evidence:{label}", "control.proposal_execution"),),
        diagnostic_quality="not_applicable" if status == "passed" else quality,
        evaluated_at=datetime.now(UTC),
    )


def _authorization(
    *,
    ordinal: int,
    report: ValidationReport,
    decision: str = "local_correction",
) -> tuple[RepairAction, ArtifactRef, ArtifactRef, ArtifactRef, ArtifactRef]:
    definition = _definition()
    evaluation_ref = _ref(f"evaluation:{ordinal}", "control.feedback_evaluation")
    action = RepairAction(
        action_id=f"repair-action:{ordinal}",
        repair_policy_id=definition.repair_policy.policy_id,
        source_evaluation_ref=evaluation_ref,
        current_coordinate=definition.coordinate,
        target_coordinate=definition.coordinate,
        decision=decision,
        jump_distance=0,
        repair_attempt_ordinal=ordinal,
        immutable_input_refs=(
            _ref("world-skeleton", "design.world_skeleton"),
        ),
        allowed_mutation_roots=("/tools",) if decision == "local_correction" else (),
        reason_code="actionable_validation_failure",
        repair_attempt_charge=1,
        authorized_at=datetime.now(UTC),
    )
    return (
        action,
        _ref(f"action:{ordinal}", "control.repair_action"),
        evaluation_ref,
        _ref(report.report_id, "control.validation_report"),
        _ref(f"budget:{ordinal}", "control.budget_lease"),
    )


def _authorize(ledger: WorkRepairLedger, report: ValidationReport, ordinal: int):
    action, action_ref, evaluation_ref, report_ref, budget_ref = _authorization(
        ordinal=ordinal,
        report=report,
    )
    return ledger.authorize(
        definition=_definition(),
        action=action,
        action_ref=action_ref,
        evaluation_ref=evaluation_ref,
        report=report,
        report_ref=report_ref,
        budget_lease_ref=budget_ref,
    )


def test_strict_progress_grants_one_bonus_then_unchanged_is_terminal() -> None:
    ledger = WorkRepairLedger()
    issue_a = _issue("reference_missing", 0)
    issue_b = _issue("lifecycle_field_missing", 1)
    first_report = _report("a-and-b", (issue_a, issue_b))
    first = _authorize(ledger, first_report, 1)
    second_report = _report("b", (issue_b,))
    first_done = ledger.complete(
        first.entry_id,
        report_before=first_report,
        report_after=second_report,
        report_after_ref=_ref("report:b", "control.validation_report"),
    )
    assert first_done.progress == "strict_progress"

    second = _authorize(ledger, second_report, 2)
    second_done = ledger.complete(
        second.entry_id,
        report_before=second_report,
        report_after=_report("b-again", (issue_b,)),
        report_after_ref=_ref("report:b-again", "control.validation_report"),
        history=(first_report,),
    )
    assert second_done.outcome == "no_progress"
    with pytest.raises(WorkRepairDenied, match="no_progress_terminal"):
        _authorize(ledger, second_report, 3)


def test_a_to_b_to_a_is_oscillation_and_never_authorizes_a_third_turn() -> None:
    ledger = WorkRepairLedger()
    issue_a = _issue("reference_missing")
    issue_b = _issue("lifecycle_field_missing")
    report_a = _report("a", (issue_a,))
    first = _authorize(ledger, report_a, 1)
    report_b = _report("b", (issue_b,), frontier=30)
    ledger.complete(
        first.entry_id,
        report_before=report_a,
        report_after=report_b,
        report_after_ref=_ref("report:b", "control.validation_report"),
    )
    second = _authorize(ledger, report_b, 2)
    done = ledger.complete(
        second.entry_id,
        report_before=report_b,
        report_after=_report("again-a", (issue_a,), frontier=30),
        report_after_ref=_ref("report:again-a", "control.validation_report"),
        history=(report_a,),
    )
    # Reintroducing A after a frontier advance is a regression; the same
    # frontier would classify as oscillation. Both are terminal no-progress.
    assert done.progress == "regressed"
    assert done.outcome == "no_progress"


def test_generic_diagnostic_denied_and_infrastructure_budget_is_separate() -> None:
    ledger = WorkRepairLedger()
    generic = ValidationIssue(
        code="value_error",
        path=("root",),
        violated_condition="An untyped validator failed.",
        expected_category="a typed field-addressable diagnostic",
    )
    generic_report = _report(
        "generic",
        (generic,),
        quality="insufficient",
    )
    with pytest.raises(WorkRepairDenied, match="not_actionable"):
        _authorize(ledger, generic_report, 1)

    error_report = _report(
        "backend-error",
        (generic.model_copy(update={"retryable": False}),),
        frontier=0,
        status="error",
        quality="insufficient",
    )
    action, action_ref, evaluation_ref, report_ref, budget_ref = _authorization(
        ordinal=1,
        report=error_report,
        decision="infrastructure_retry",
    )
    entry = ledger.authorize(
        definition=_definition(),
        action=action,
        action_ref=action_ref,
        evaluation_ref=evaluation_ref,
        report=error_report,
        report_ref=report_ref,
        budget_lease_ref=budget_ref,
    )
    semantic_report = _report("semantic", (_issue("reference_missing"),), frontier=20)
    completed = ledger.complete(
        entry.entry_id,
        report_before=error_report,
        report_after=semantic_report,
        report_after_ref=_ref("report:semantic", "control.validation_report"),
    )
    assert completed.progress == "strict_progress"
    assert completed.decision == "infrastructure_retry"
