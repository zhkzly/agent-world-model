from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from agent_world.contracts import ArtifactRef, sha256_digest
from agent_world.control.work import (
    AssurancePolicy,
    FeedbackEvaluation,
    OperationBudget,
    ProposalPolicy,
    RepairAction,
    RepairPolicy,
    ValidationIssue,
    ValidationPolicy,
    ValidationReport,
    WorkAttempt,
    WorkCommit,
    WorkCoordinate,
    WorkDefinition,
    classify_progress,
)


def _hash(label: str) -> str:
    return sha256_digest(label.encode())


def _ref(label: str, artifact_type: str = "control.test") -> ArtifactRef:
    return ArtifactRef(
        artifact_id=f"artifact:{label}",
        revision_id=_hash(f"revision:{label}"),
        artifact_type=artifact_type,
        content_hash=_hash(f"content:{label}"),
        media_type="application/json",
        size_bytes=1,
    )


def _coordinate(slot: str = "world_behavior", *, stage: str = "world_behavior") -> WorkCoordinate:
    return WorkCoordinate(
        scope_id="job:hotel",
        component="design",
        stage=stage,
        artifact_slot=slot,
    )


def _issue(
    code: str,
    path: tuple[str | int, ...],
    *,
    condition: str | None = None,
) -> ValidationIssue:
    return ValidationIssue(
        code=code,
        path=path,
        violated_condition=condition or f"{code} violated its closed contract",
        expected_category="closed_contract_value",
    )


def _report(
    report_id: str,
    issues: tuple[ValidationIssue, ...],
    *,
    frontier: int = 20,
    phase: str = "tool_semantics",
    quality: str = "actionable",
) -> ValidationReport:
    return ValidationReport(
        report_id=report_id,
        attempt_id=f"attempt:{report_id}",
        coordinate=_coordinate(),
        policy_id="validation:world-behavior",
        policy_digest=_hash("validation:world-behavior:v1"),
        status="failed",
        validation_phase=phase,
        frontier_ordinal=frontier,
        issues=issues,
        diagnostic_quality=quality,
        evaluated_at=datetime.now(UTC),
    )


def _passed_report() -> ValidationReport:
    return ValidationReport(
        report_id="report:passed",
        attempt_id="attempt:passed",
        coordinate=_coordinate(),
        policy_id="validation:world-behavior",
        policy_digest=_hash("validation:world-behavior:v1"),
        subject_ref=_ref("behavior", "design.world_behavior"),
        status="passed",
        validation_phase="tool_semantics",
        frontier_ordinal=30,
        passed_check_ids=("tool.reliability",),
        diagnostic_quality="not_applicable",
        evaluated_at=datetime.now(UTC),
    )


def test_work_policies_separate_agent_validation_and_real_execution() -> None:
    proposal = ProposalPolicy(
        policy_id="proposal:world-behavior",
        executor="agent",
        operation="design.world_behavior",
        agent_role="environment_engineer",
        capability_profile_id="profile:design",
        output_contract_id="contract:world-behavior-source",
        budget=OperationBudget(
            wall_seconds=300.0,
            first_progress_seconds=60.0,
            llm_tokens=40_000,
            agent_turns=1,
        ),
    )
    validation = ValidationPolicy(
        policy_id="validation:world-behavior",
        validator_id="validator:world-behavior",
        validation_phase="tool_semantics",
        frontier_ordinal=20,
        claim_id="design.behavior.valid",
        effect="block_compile",
        budget=OperationBudget(wall_seconds=3.0),
    )
    assurance = AssurancePolicy(
        policy_id="assurance:world-behavior",
        runtime_profile_id="runtime:isolated",
        probe_ids=("probe:reset-step",),
        claim_id="design.behavior.valid",
        effect="block_compile",
        budget=OperationBudget(
            wall_seconds=30.0,
            process_calls=2,
            evaluation_episodes=1,
        ),
        evidence_freshness="same_attempt",
    )
    definition = WorkDefinition(
        work_id="work:world-behavior",
        coordinate=_coordinate(),
        dependency_coordinates=(_coordinate("architecture", stage="world_architecture"),),
        proposal_policy=proposal,
        validation_policy=validation,
        assurance_policy=assurance,
        repair_policy=RepairPolicy(policy_id="repair:world-behavior"),
        required_claim_id="design.behavior.valid",
        success_maturity="design_behavior_valid",
    )

    assert definition.definition_digest.startswith("sha256:")
    assert definition.proposal_policy.budget.agent_turns == 1
    assert definition.validation_policy.budget.agent_turns == 0
    assert definition.assurance_policy is not None
    assert definition.assurance_policy.budget.process_calls == 2

    with pytest.raises(ValidationError, match="Agent proposal requires"):
        ProposalPolicy(
            policy_id="proposal:invalid-agent",
            executor="agent",
            operation="design.invalid",
            budget=OperationBudget(wall_seconds=10.0, llm_tokens=1, agent_turns=1),
        )
    with pytest.raises(ValidationError, match="deterministic validation"):
        ValidationPolicy(
            policy_id="validation:invalid",
            validator_id="validator:invalid",
            validation_phase="schema",
            frontier_ordinal=1,
            claim_id="design.invalid",
            effect="block_compile",
            budget=OperationBudget(wall_seconds=3.0, agent_turns=1),
        )


def test_work_contracts_are_closed_and_definition_rejects_self_dependency() -> None:
    with pytest.raises(ValidationError):
        WorkCoordinate.model_validate(
            {
                "scope_id": "job:hotel",
                "component": "design",
                "stage": "world_behavior",
                "artifact_slot": "world_behavior",
                "undeclared": True,
            }
        )
    with pytest.raises(ValidationError, match="physical shard requires"):
        WorkCoordinate(
            scope_id="job:hotel",
            component="design",
            stage="world_behavior",
            artifact_slot="world_behavior",
            shard_id="shard:1",
        )
    with pytest.raises(ValidationError, match="deadline cannot exceed"):
        OperationBudget(wall_seconds=2.0, first_progress_seconds=3.0)

    proposal = ProposalPolicy(
        policy_id="proposal:code",
        executor="code",
        operation="compile",
        budget=OperationBudget(wall_seconds=1.0),
    )
    validation = ValidationPolicy(
        policy_id="validation:code",
        validator_id="validator:code",
        validation_phase="compile",
        frontier_ordinal=1,
        claim_id="design.compiles",
        effect="block_compile",
        budget=OperationBudget(wall_seconds=1.0),
    )
    with pytest.raises(ValidationError, match="own output coordinate"):
        WorkDefinition(
            work_id="work:self-cycle",
            coordinate=_coordinate(),
            dependency_coordinates=(_coordinate(),),
            proposal_policy=proposal,
            validation_policy=validation,
            repair_policy=RepairPolicy(policy_id="repair:none"),
            required_claim_id="design.compiles",
            success_maturity="design_valid",
        )


def test_generic_root_diagnostic_is_exactly_non_actionable() -> None:
    generic = _issue(
        "semantic_contract_violation",
        ("root",),
        condition="The compiled component violates a closed semantic contract.",
    )
    report = _report(
        "report:generic-root",
        (generic,),
        quality="insufficient",
    )

    assert generic.actionable is False
    assert report.repair_actionable is False
    with pytest.raises(ValidationError, match="diagnostic quality"):
        ValidationReport.model_validate(
            {**report.model_dump(mode="python"), "diagnostic_quality": "actionable"}
        )


def test_exact_field_diagnostic_is_actionable_and_does_not_store_rejected_value() -> None:
    issue = _issue(
        "tool_reliability_reference_missing",
        ("tools", 3, "reliability", "idempotency_state_path"),
        condition="Reference must resolve to a declared mutable state field.",
    )
    report = _report("report:exact", (issue,))

    assert issue.actionable is True
    assert report.repair_actionable is True
    assert "rejected_value" not in issue.model_dump(mode="json")
    assert report.model_validate_json(report.model_dump_json()) == report

    nonretryable = issue.model_copy(update={"retryable": False})
    assert not nonretryable.actionable
    reworded = _issue(
        issue.code,
        issue.path,
        condition="The same deterministic condition, phrased differently.",
    )
    assert reworded.normalized_identity == issue.normalized_identity


def test_one_repair_policy_is_the_total_semantic_and_infrastructure_ceiling() -> None:
    policy = RepairPolicy(policy_id="repair:default")

    assert policy.maximum_total_repair_attempts == 3
    with pytest.raises(ValidationError, match="allowances exceed total"):
        RepairPolicy(
            policy_id="repair:incoherent",
            maximum_local_corrections=1,
            strict_progress_bonus_corrections=1,
            maximum_infrastructure_retries=1,
            maximum_total_repair_attempts=2,
        )
def test_progress_classifier_covers_real_no_progress_and_frontier_bad_cases() -> None:
    issue_a = _issue("reference_missing", ("tools", 0, "state_path"))
    issue_b = _issue("lifecycle_field_missing", ("entities", 0, "lifecycle_field"))
    previous = _report("report:a", (issue_a, issue_b), frontier=20)

    assert classify_progress(previous, _passed_report()) == "resolved"
    assert classify_progress(previous, _report("report:same", (issue_a, issue_b))) == "unchanged"
    assert (
        classify_progress(previous, _report("report:shrunk", (issue_b,)))
        == "strict_progress"
    )
    assert (
        classify_progress(
            previous,
            _report("report:advanced", (_issue("new_error", ("tools", 1)),), frontier=30),
        )
        == "strict_progress"
    )
    assert (
        classify_progress(previous, _report("report:backward", (issue_b,), frontier=10))
        == "regressed"
    )

    generic = _report(
        "report:generic",
        (_issue("value_error", ("root",)),),
        quality="insufficient",
    )
    assert classify_progress(previous, generic) == "unknown"


def test_progress_classifier_detects_a_to_b_to_a_oscillation_and_reintroduction() -> None:
    issue_a = _issue("reference_missing", ("tools", 0, "state_path"))
    issue_b = _issue("lifecycle_field_missing", ("entities", 0, "lifecycle_field"))
    first_a = _report("report:first-a", (issue_a,))
    then_b = _report("report:then-b", (issue_b,))
    again_a = _report("report:again-a", (issue_a,))

    assert classify_progress(then_b, again_a, history=(first_a,)) == "oscillating"

    current_with_old_a = _report(
        "report:old-a-plus-new",
        (issue_a, _issue("permission_missing", ("tools", 1, "permission"))),
        frontier=30,
    )
    assert (
        classify_progress(then_b, current_with_old_a, history=(first_a,))
        == "regressed"
    )


def test_feedback_evaluation_derives_readiness_and_diagnostic_is_non_releasable() -> None:
    report_ref = _ref("validation-report", "control.validation_report")
    subject_ref = _ref("behavior", "design.world_behavior")
    passed = FeedbackEvaluation(
        evaluation_id="evaluation:behavior",
        attempt_id="attempt:behavior",
        work_id="work:behavior",
        coordinate=_coordinate(),
        claim_id="design.behavior.valid",
        policy_digest=_hash("validation:world-behavior:v1"),
        status="passed",
        effect="block_compile",
        readiness_effect="satisfies",
        subject_ref=subject_ref,
        validation_report_ref=report_ref,
        evaluated_at=datetime.now(UTC),
    )
    assert passed.readiness_effect == "satisfies"

    diagnostic = FeedbackEvaluation.model_validate(
        {
            **passed.model_dump(mode="python"),
            "evaluation_id": "evaluation:diagnostic",
            "diagnostic_only": True,
            "releasable": False,
            "readiness_effect": "observes",
        }
    )
    assert diagnostic.releasable is False
    with pytest.raises(ValidationError, match="readiness effect"):
        FeedbackEvaluation.model_validate(
            {**passed.model_dump(mode="python"), "readiness_effect": "blocks"}
        )
    with pytest.raises(ValidationError, match="never releasable"):
        FeedbackEvaluation.model_validate(
            {**diagnostic.model_dump(mode="python"), "releasable": True}
        )


def test_work_attempt_commit_and_diagnostic_lifecycle_are_fail_closed() -> None:
    now = datetime.now(UTC)
    output = _ref("behavior", "design.world_behavior")
    evaluation = _ref("evaluation", "control.feedback_evaluation")
    attempt = WorkAttempt(
        attempt_id="attempt:behavior:1",
        work_id="work:behavior",
        coordinate=_coordinate(),
        ordinal=1,
        status="succeeded",
        definition_digest=_hash("definition"),
        proposal_policy_digest=_hash("proposal"),
        validation_policy_digest=_hash("validation"),
        repair_policy_digest=_hash("repair"),
        output_refs=(output,),
        feedback_evaluation_ref=evaluation,
        scheduled_at=now,
        started_at=now + timedelta(seconds=1),
        first_progress_at=now + timedelta(seconds=2),
        finished_at=now + timedelta(seconds=3),
    )
    commit = WorkCommit(
        commit_id="commit:behavior:1",
        work_id=attempt.work_id,
        coordinate=attempt.coordinate,
        attempt_id=attempt.attempt_id,
        definition_digest=attempt.definition_digest,
        output_refs=attempt.output_refs,
        feedback_evaluation_ref=evaluation,
        committed_at=now + timedelta(seconds=4),
    )
    assert commit.aggregate is False

    with pytest.raises(ValidationError, match="successful work requires"):
        WorkAttempt.model_validate(
            {**attempt.model_dump(mode="python"), "output_refs": ()}
        )
    with pytest.raises(ValidationError, match="never releasable"):
        WorkAttempt.model_validate(
            {**attempt.model_dump(mode="python"), "diagnostic_only": True}
        )
    with pytest.raises(ValidationError, match="aggregate commits"):
        WorkCommit.model_validate(
            {**commit.model_dump(mode="python"), "aggregate": True}
        )


def test_repair_action_enforces_local_one_hop_and_human_boundaries() -> None:
    now = datetime.now(UTC)
    evaluation_ref = _ref("evaluation", "control.feedback_evaluation")
    input_ref = _ref("architecture", "design.world_architecture")
    current = _coordinate()
    parent = _coordinate("architecture", stage="world_architecture")
    local = RepairAction(
        action_id="repair:local:1",
        repair_policy_id="repair:world-behavior",
        source_evaluation_ref=evaluation_ref,
        current_coordinate=current,
        target_coordinate=current,
        decision="local_correction",
        jump_distance=0,
        repair_attempt_ordinal=1,
        immutable_input_refs=(input_ref,),
        allowed_mutation_roots=("/tools/3/reliability",),
        reason_code="actionable_local_diagnostic",
        repair_attempt_charge=1,
        authorized_at=now,
    )
    assert local.repair_attempt_charge == 1

    parent_action = RepairAction.model_validate(
        {
            **local.model_dump(mode="python"),
            "action_id": "repair:parent:1",
            "target_coordinate": parent,
            "decision": "parent_correction",
            "jump_distance": 1,
            "causal_evidence_refs": (evaluation_ref,),
        }
    )
    assert parent_action.jump_distance == 1
    with pytest.raises(ValidationError, match="one-hop causal evidence"):
        RepairAction.model_validate(
            {**parent_action.model_dump(mode="python"), "causal_evidence_refs": ()}
        )
    with pytest.raises(ValidationError, match="distance-two"):
        RepairAction.model_validate(
            {**parent_action.model_dump(mode="python"), "jump_distance": 2}
        )
    with pytest.raises(ValidationError, match="only an executing"):
        RepairAction.model_validate(
            {**local.model_dump(mode="python"), "repair_attempt_charge": 0}
        )


def test_repair_policy_has_one_total_attempt_ceiling() -> None:
    with pytest.raises(ValidationError, match="semantic correction allowance"):
        RepairPolicy(
            policy_id="repair:split-truth",
            maximum_local_corrections=1,
            strict_progress_bonus_corrections=1,
            maximum_infrastructure_retries=0,
            maximum_total_repair_attempts=1,
        )
    with pytest.raises(ValidationError, match="infrastructure retry allowance"):
        RepairPolicy(
            policy_id="repair:infra-split-truth",
            maximum_local_corrections=0,
            strict_progress_bonus_corrections=0,
            maximum_infrastructure_retries=2,
            maximum_total_repair_attempts=1,
        )
