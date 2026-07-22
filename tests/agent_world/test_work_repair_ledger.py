from __future__ import annotations

from datetime import UTC, datetime

import pytest

from agent_world.contracts import ArtifactRef, sha256_digest
from agent_world.control.work import (
    RepairAction,
    ValidationIssue,
    ValidationReport,
    repair_epoch_digest,
    work_input_fingerprint,
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
        subject_refs=((subject_ref,) if subject_ref is not None else ()),
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
    reason_code: str = "actionable_validation_failure",
    definition=None,
    input_refs: tuple[ArtifactRef, ...] | None = None,
) -> tuple[RepairAction, ArtifactRef, ArtifactRef, ArtifactRef, ArtifactRef]:
    definition = definition or _definition()
    evaluation_ref = _ref(f"evaluation:{ordinal}", "control.feedback_evaluation")
    input_refs = input_refs or (_ref("world-skeleton", "design.world_skeleton"),)
    action = RepairAction(
        action_id=f"repair-action:{ordinal}",
        repair_policy_id=definition.repair_policy.policy_id,
        repair_epoch_digest=repair_epoch_digest(definition, input_refs),
        definition_digest=definition.definition_digest,
        input_fingerprint=work_input_fingerprint(input_refs),
        source_evaluation_ref=evaluation_ref,
        current_coordinate=definition.coordinate,
        target_coordinate=definition.coordinate,
        decision=decision,
        jump_distance=0,
        repair_attempt_ordinal=ordinal,
        immutable_input_refs=input_refs,
        allowed_mutation_roots=("/tools",) if decision == "local_correction" else (),
        reason_code=reason_code,
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


def _authorize(
    ledger: WorkRepairLedger,
    report: ValidationReport,
    ordinal: int,
    *,
    definition=None,
    input_refs: tuple[ArtifactRef, ...] | None = None,
):
    definition = definition or _definition()
    input_refs = input_refs or (_ref("world-skeleton", "design.world_skeleton"),)
    action, action_ref, evaluation_ref, report_ref, budget_ref = _authorization(
        ordinal=ordinal,
        report=report,
        definition=definition,
        input_refs=input_refs,
    )
    return ledger.authorize(
        definition=definition,
        action=action,
        action_ref=action_ref,
        evaluation_ref=evaluation_ref,
        report=report,
        report_ref=report_ref,
    )


def test_repair_epoch_isolates_definition_and_input_revisions() -> None:
    ledger = WorkRepairLedger()
    definition = _definition()
    input_refs = (_ref("world-skeleton", "design.world_skeleton"),)
    report = _report("old-definition", (_issue("reference_missing"),))
    old = _authorize(
        ledger,
        report,
        1,
        definition=definition,
        input_refs=input_refs,
    )
    ledger.complete(
        old.entry_id,
        report_before=report,
        report_after=_report("same-old-definition", (_issue("reference_missing"),)),
        report_after_ref=_ref(
            "report:same-old-definition",
            "control.validation_report",
        ),
    )

    revised_definition = definition.model_copy(
        update={
            "proposal_policy": definition.proposal_policy.model_copy(
                update={"acceptance_transform_id": "framework.revision.v2"}
            )
        }
    )
    assert ledger.entries_for(revised_definition, input_refs=input_refs) == ()
    revised = _authorize(
        ledger,
        report,
        1,
        definition=revised_definition,
        input_refs=input_refs,
    )
    assert revised.repair_attempt_ordinal == 1

    changed_inputs = (_ref("world-skeleton-v2", "design.world_skeleton"),)
    assert ledger.entries_for(revised_definition, input_refs=changed_inputs) == ()


def test_local_repair_accepts_minimal_authorized_subtree_and_rejects_escape() -> None:
    ledger = WorkRepairLedger()
    definition = _definition().model_copy(
        update={
            "allowed_mutation_roots": (
                "/boundary",
                "/state_entities",
                "/tool_inventory",
            )
        }
    )
    report = _report("unknown-actor", (_issue("architecture_visibility_actor_unknown"),))
    action, action_ref, evaluation_ref, report_ref, budget_ref = _authorization(
        ordinal=1,
        report=report,
        definition=definition,
    )
    action = action.model_copy(update={"allowed_mutation_roots": ("/state_entities",)})

    entry = ledger.authorize(
        definition=definition,
        action=action,
        action_ref=action_ref,
        evaluation_ref=evaluation_ref,
        report=report,
        report_ref=report_ref,
    )
    assert entry.decision == "local_correction"

    escaped = action.model_copy(
        update={
            "action_id": "repair-action:escape",
            "allowed_mutation_roots": ("/curriculum",),
        }
    )
    with pytest.raises(WorkRepairDenied, match="repair_mutation_authority_mismatch"):
        WorkRepairLedger().authorize(
            definition=definition,
            action=escaped,
            action_ref=_ref("action:escape", "control.repair_action"),
            evaluation_ref=evaluation_ref,
            report=report,
            report_ref=report_ref,
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


def test_process_recovery_does_not_consume_provider_retry_allowance() -> None:
    ledger = WorkRepairLedger()
    error_report = _report(
        "provider-error",
        (_issue("provider_timeout"),),
        frontier=0,
        status="error",
        quality="actionable",
    )
    action, action_ref, evaluation_ref, report_ref, budget_ref = _authorization(
        ordinal=1,
        report=error_report,
        decision="infrastructure_retry",
        reason_code="retryable_infrastructure_failure",
    )
    ledger.authorize(
        definition=_definition(),
        action=action,
        action_ref=action_ref,
        evaluation_ref=evaluation_ref,
        report=error_report,
        report_ref=report_ref,
    )

    interrupted = _report(
        "process-interrupted",
        (_issue("process_interrupted_before_checkpoint"),),
        frontier=0,
        status="error",
        quality="actionable",
    )
    action, action_ref, evaluation_ref, report_ref, budget_ref = _authorization(
        ordinal=2,
        report=interrupted,
        decision="infrastructure_retry",
        reason_code="process_interrupted",
    )
    recovered = ledger.authorize(
        definition=_definition(),
        action=action,
        action_ref=action_ref,
        evaluation_ref=evaluation_ref,
        report=interrupted,
        report_ref=report_ref,
    )
    assert recovered.reason_code == "process_interrupted"
