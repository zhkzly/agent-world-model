from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent_world.artifact_store import ArtifactStore
from agent_world.contracts import Budget, BudgetUsage
from agent_world.control.budget import LeaseBudgetLedger
from agent_world.control.models import BudgetLease
from agent_world.control.work import (
    FeedbackEvaluation,
    OperationBudget,
    OperationRun,
    ProposalExecution,
    ProposalPolicy,
    RepairPolicy,
    ValidationPolicy,
    ValidationReport,
    WorkAttempt,
    WorkCommit,
    WorkCoordinate,
    WorkDefinition,
)
from agent_world.control.work_runtime import (
    WorkControlRuntime,
    WorkRuntimeError,
    restore_work_budget_ledger,
)
from agent_world.control.work_store import (
    WorkControlHead,
    WorkControlLock,
    WorkControlStore,
    WorkControlStoreError,
    WorkHeadConflictError,
    WorkResumeError,
)


def _definition() -> WorkDefinition:
    coordinate = WorkCoordinate(
        scope_id="job:hotel",
        component="design",
        stage="world_behavior",
        artifact_slot="tool_semantics_batch",
        group_id="coupling:booking",
        shard_id="batch:1",
    )
    return WorkDefinition(
        work_id="work:hotel:tool-semantics:1",
        coordinate=coordinate,
        claim="The tool batch compiles against the frozen hotel world schema.",
        timing_reason="World rules consume exact executable tool semantics.",
        proposal_policy=ProposalPolicy(
            policy_id="proposal:tool-semantics",
            executor="agent",
            operation="design.tool_semantics_batch",
            budget=OperationBudget(
                wall_seconds=300,
                llm_tokens=20_000,
                agent_turns=1,
            ),
            agent_role="environment_engineer",
            capability_profile_id="profile:environment-engineer",
            output_contract_id="contract:tool-semantics-batch",
        ),
        validation_policy=ValidationPolicy(
            policy_id="validation:tool-semantics",
            validator_id="validator:tool-semantics",
            validator_revision_id="framework.validator.tool-semantics.v1",
            validation_phase="tool_semantics",
            frontier_ordinal=20,
            claim_id="design.tool_semantics.compiles",
            effect="block_compile",
            budget=OperationBudget(wall_seconds=5),
        ),
        repair_policy=RepairPolicy(policy_id="repair:tool-semantics"),
        required_claim_id="design.tool_semantics.compiles",
        allowed_mutation_roots=("/tools",),
        success_maturity="semantic_compiled",
    )


def _writer(root: Path):
    store = ArtifactStore(root / "artifacts")
    return store.issue_writer(
        producer="work-controller",
        allowed_artifact_type_prefixes=("control.", "design."),
    )


def test_work_head_cas_is_single_writer_and_terminal_commit_is_immutable(
    tmp_path: Path,
) -> None:
    definition = _definition()
    writer = _writer(tmp_path)
    work_store = WorkControlStore(tmp_path / "work-control")
    input_ref = writer.put_json(
        artifact_id="hotel:world-skeleton",
        artifact_type="design.world_skeleton",
        value={"kind": "hotel"},
    )
    attempt_ref = writer.put_json(
        artifact_id="hotel:attempt:1",
        artifact_type="control.work_attempt",
        value={"attempt_id": "attempt:1"},
        dependencies=(input_ref,),
    )
    initial = WorkControlStore.new_head(
        definition=definition,
        input_refs=(input_ref,),
        attempt_ref=attempt_ref,
    )
    with work_store.exclusive(definition.coordinate) as lock:
        work_store.compare_and_swap(lock, expected_head=None, next_head=initial)
        with pytest.raises(WorkHeadConflictError, match="changed"):
            work_store.compare_and_swap(lock, expected_head=None, next_head=initial)

        interrupted = initial.model_copy(
            update={
                "revision": 2,
                "status": "interrupted",
                "updated_at": datetime.now(UTC),
            }
        )
        work_store.compare_and_swap(
            lock,
            expected_head=initial,
            next_head=interrupted,
        )
        with pytest.raises(WorkHeadConflictError, match="new WorkAttempt"):
            work_store.compare_and_swap(
                lock,
                expected_head=interrupted,
                next_head=interrupted.model_copy(
                    update={
                        "revision": 3,
                        "status": "running",
                        "updated_at": datetime.now(UTC),
                    }
                ),
            )

    with pytest.raises(WorkControlStoreError, match="invalid WorkGraph lock"):
        work_store.compare_and_swap(
            WorkControlLock(
                scope_id=definition.coordinate.scope_id,
                coordinate_key=definition.coordinate.coordinate_key,
                nonce="forged",
            ),
            expected_head=work_store.read_head(definition.coordinate),
            next_head=interrupted.model_copy(update={"revision": 3, "status": "failed"}),
        )

    revised_input = writer.put_json(
        artifact_id="hotel:world-skeleton:v2",
        artifact_type="design.world_skeleton",
        value={"kind": "hotel", "revision": 2},
    )
    next_attempt_ref = writer.put_json(
        artifact_id="hotel:attempt:2",
        artifact_type="control.work_attempt",
        value={"attempt_id": "attempt:2"},
        dependencies=(revised_input,),
    )
    reopened = interrupted.model_copy(
        update={
            "revision": 3,
            "status": "running",
            "attempt_ref": next_attempt_ref,
            "input_fingerprint": WorkControlStore.input_fingerprint((revised_input,)),
            "invalidated_by_refs": (revised_input,),
            "updated_at": datetime.now(UTC),
        }
    )
    with work_store.exclusive(definition.coordinate) as lock:
        work_store.supersede(
            lock,
            expected_head=interrupted,
            next_head=reopened,
        )
    assert work_store.read_head(definition.coordinate) == reopened

    forged_definition = definition.model_copy(update={"work_id": "work:hotel:forged-v2"})
    forged_attempt_ref = writer.put_json(
        artifact_id="hotel:attempt:forged",
        artifact_type="control.work_attempt",
        value={"attempt_id": "attempt:forged"},
        dependencies=(revised_input,),
    )
    forged = reopened.model_copy(
        update={
            "revision": reopened.revision + 1,
            "work_id": forged_definition.work_id,
            "definition_digest": forged_definition.definition_digest,
            "acceptance_digest": forged_definition.acceptance_digest,
            "attempt_ref": forged_attempt_ref,
            "invalidated_by_refs": (reopened.attempt_ref,),
            "updated_at": datetime.now(UTC),
        }
    )
    with work_store.exclusive(definition.coordinate) as lock:
        with pytest.raises(WorkHeadConflictError, match="stale"):
            work_store.supersede_stale(
                lock,
                expected_head=reopened,
                next_head=forged,
            )


def test_model_fallback_authorizes_one_failed_terminal_head(
    tmp_path: Path,
) -> None:
    """A classified fallback has the same narrow terminal transition as retry."""

    definition = _definition()
    writer = _writer(tmp_path)
    work_store = WorkControlStore(tmp_path / "work-control")
    input_ref = writer.put_json(
        artifact_id="hotel:model-fallback-input",
        artifact_type="design.world_skeleton",
        value={"kind": "hotel"},
    )
    attempt_ref = writer.put_json(
        artifact_id="hotel:model-fallback-attempt",
        artifact_type="control.work_attempt",
        value={"attempt_id": "attempt:model-fallback"},
        dependencies=(input_ref,),
    )
    evaluation_ref = writer.put_json(
        artifact_id="hotel:model-fallback-evaluation",
        artifact_type="control.feedback_evaluation",
        value={"kind": "closed-transient-terminal"},
        dependencies=(attempt_ref,),
    )
    action_ref = writer.put_json(
        artifact_id="hotel:model-fallback-action",
        artifact_type="control.repair_action",
        value={"decision": "model_fallback"},
        dependencies=(attempt_ref, evaluation_ref),
    )
    initial = WorkControlStore.new_head(
        definition=definition,
        input_refs=(input_ref,),
        attempt_ref=attempt_ref,
    )
    failed = initial.model_copy(
        update={
            "revision": 2,
            "status": "failed",
            "evaluation_ref": evaluation_ref,
            "updated_at": datetime.now(UTC),
        }
    )
    fallback = failed.model_copy(
        update={
            "revision": 3,
            "status": "repair_authorized",
            "evaluation_ref": evaluation_ref,
            "repair_action_ref": action_ref,
            "invalidated_by_refs": (attempt_ref, action_ref),
            "updated_at": datetime.now(UTC),
        }
    )

    with work_store.exclusive(definition.coordinate) as lock:
        work_store.compare_and_swap(lock, expected_head=None, next_head=initial)
        work_store.compare_and_swap(lock, expected_head=initial, next_head=failed)
        authorized = work_store.authorize_model_fallback(
            lock,
            expected_head=failed,
            next_head=fallback,
        )

    assert authorized == fallback
    assert work_store.read_head(definition.coordinate) == fallback


def test_resume_rejects_commit_with_fake_attempt_even_when_evaluation_looks_passed(
    tmp_path: Path,
) -> None:
    definition = _definition()
    writer = _writer(tmp_path)
    work_store = WorkControlStore(tmp_path / "work-control")
    input_ref = writer.put_json(
        artifact_id="hotel:skeleton",
        artifact_type="design.world_skeleton",
        value={"kind": "hotel"},
    )
    output_ref = writer.put_json(
        artifact_id="hotel:tool-semantics",
        artifact_type="design.tool_semantics_batch_source",
        value={"tools": ["reserve_hotel"]},
        dependencies=(input_ref,),
    )
    attempt_ref = writer.put_json(
        artifact_id="hotel:attempt:1",
        artifact_type="control.work_attempt",
        value={"attempt_id": "attempt:1"},
        dependencies=(input_ref,),
    )
    writer.put_json(
        artifact_id="hotel:work-definition:1",
        artifact_type="control.work_definition",
        value=definition,
        dependencies=(input_ref,),
    )
    fake_report_ref = writer.put_json(
        artifact_id="hotel:fake-validation-report",
        artifact_type="control.validation_report",
        value={"not": "a ValidationReport"},
        dependencies=(output_ref,),
    )
    evaluation = FeedbackEvaluation(
        evaluation_id="evaluation:hotel:tool-semantics:1",
        attempt_id="attempt:1",
        work_id=definition.work_id,
        coordinate=definition.coordinate,
        claim_id=definition.required_claim_id,
        acceptance_digest=definition.acceptance_digest,
        policy_digest=definition.validation_policy.content_digest(),
        status="passed",
        effect=definition.validation_policy.effect,
        readiness_effect="satisfies",
        subject_refs=(output_ref,),
        validation_report_ref=fake_report_ref,
        assurance_evidence_refs=(output_ref,),
        evaluated_at=datetime.now(UTC),
    )
    evaluation_ref = writer.put_json(
        artifact_id=evaluation.evaluation_id,
        artifact_type="control.feedback_evaluation",
        value=evaluation,
        dependencies=(input_ref, output_ref, fake_report_ref),
    )
    operation_refs = tuple(
        writer.put_json(
            artifact_id=f"hotel:fake-operation:{kind}",
            artifact_type="control.operation_run",
            value={"kind": kind},
        )
        for kind in ("proposal", "validation")
    )
    commit = WorkCommit(
        commit_id="commit:hotel:tool-semantics:1",
        work_id=definition.work_id,
        coordinate=definition.coordinate,
        attempt_id="attempt:1",
        definition_digest=definition.definition_digest,
        acceptance_digest=definition.acceptance_digest,
        validation_policy_digest=definition.validation_policy.content_digest(),
        input_refs=(input_ref,),
        validated_subject_refs=(output_ref,),
        output_refs=(output_ref,),
        feedback_evaluation_ref=evaluation_ref,
        operation_run_refs=operation_refs,
        committed_at=datetime.now(UTC),
    )
    commit_ref = writer.put_json(
        artifact_id=commit.commit_id,
        artifact_type="control.work_commit",
        value=commit,
        dependencies=(input_ref, output_ref, evaluation_ref, *operation_refs),
    )
    initial = WorkControlStore.new_head(
        definition=definition,
        input_refs=(input_ref,),
        attempt_ref=attempt_ref,
    )
    committed_head = WorkControlHead.model_validate(
        {
            **initial.model_dump(mode="python"),
            "revision": 2,
            "status": "committed",
            "evaluation_ref": evaluation_ref,
            "commit_ref": commit_ref,
            "updated_at": datetime.now(UTC),
        }
    )
    with work_store.exclusive(definition.coordinate) as lock:
        work_store.compare_and_swap(lock, expected_head=None, next_head=initial)
        work_store.compare_and_swap(
            lock,
            expected_head=initial,
            next_head=committed_head,
        )

    with pytest.raises(WorkResumeError, match="successful WorkAttempt"):
        work_store.require_active_commit(
            definition=definition,
            input_refs=(input_ref,),
            artifacts=writer,
        )
    changed_definition = definition.model_copy(
        update={"timing_reason": "A changed policy must invalidate the old commit."}
    )
    assert (
        work_store.require_active_commit(
            definition=changed_definition,
            input_refs=(input_ref,),
            artifacts=writer,
        )
        is None
    )


def test_runtime_supersedes_only_a_stale_definition_under_the_coordinate_lock(
    tmp_path: Path,
) -> None:
    definition = _definition()
    writer = _writer(tmp_path)
    work_store = WorkControlStore(tmp_path / "work-control")
    runtime = WorkControlRuntime(
        artifacts=writer,
        heads=work_store,
        budget=LeaseBudgetLedger(Budget(wall_seconds=1_000, llm_tokens=100_000, agent_turns=10)),
    )
    input_ref = writer.put_json(
        artifact_id="hotel:skeleton:stale",
        artifact_type="design.world_skeleton",
        value={"kind": "hotel"},
    )
    with work_store.exclusive(definition.coordinate) as lock:
        initial = runtime.begin(
            lock,
            definition=definition,
            input_refs=(input_ref,),
            elapsed_wall_seconds=0,
        )
    orphan_lease_id = runtime._id("work-budget-lease", definition.work_id, "2")
    writer.put_json(
        artifact_id=orphan_lease_id,
        artifact_type="control.budget_lease",
        value=BudgetLease(
            lease_id=orphan_lease_id,
            owner_id=runtime._id("attempt", definition.work_id, "2"),
            reserved=Budget(
                wall_seconds=300,
                llm_tokens=20_000,
                agent_turns=1,
            ),
            status="released",
            created_at=datetime.now(UTC),
            finished_at=datetime.now(UTC),
        ),
    )
    changed = definition.model_copy(
        update={
            "proposal_policy": definition.proposal_policy.model_copy(
                update={"acceptance_transform_id": "framework.projection.v2"}
            )
        }
    )
    with work_store.exclusive(definition.coordinate) as lock:
        superseded = runtime.supersede_stale(
            lock,
            definition=changed,
            input_refs=(input_ref,),
            previous=initial,
            elapsed_wall_seconds=0,
        )
    assert superseded.status == "running"
    assert superseded.revision == initial.revision + 1
    assert superseded.definition_digest == changed.definition_digest
    assert superseded.attempt_ref != initial.attempt_ref
    assert initial.attempt_ref in superseded.invalidated_by_refs
    superseded_attempt = writer.get_json(superseded.attempt_ref, WorkAttempt)
    assert superseded_attempt.ordinal == 3
    assert superseded_attempt.operation_run_refs == ()
    initial_attempt_revisions = tuple(
        writer.get_json(ref, WorkAttempt)
        for ref in writer.list_revisions(initial.attempt_ref.artifact_id)
        if ref.artifact_type == "control.work_attempt"
    )
    assert any(
        attempt.status == "interrupted" and attempt.failure_code == "superseded_stale_execution"
        for attempt in initial_attempt_revisions
    )

    with work_store.exclusive(definition.coordinate) as lock:
        with pytest.raises(WorkRuntimeError, match="unchanged terminal work"):
            runtime.supersede_stale(
                lock,
                definition=changed,
                input_refs=(input_ref,),
                previous=superseded,
                elapsed_wall_seconds=0,
            )


def test_runtime_reactivates_exact_history_without_inventing_attempt_lease(
    tmp_path: Path,
) -> None:
    base = _definition()
    definition = base.model_copy(
        update={
            "proposal_policy": ProposalPolicy(
                policy_id="proposal:tool-semantics:code",
                executor="code",
                operation="design.tool_semantics_projection",
                budget=OperationBudget(wall_seconds=5),
            )
        }
    )
    writer = _writer(tmp_path)
    store = WorkControlStore(tmp_path / "work-control")
    runtime = WorkControlRuntime(
        artifacts=writer,
        heads=store,
        budget=LeaseBudgetLedger(Budget(wall_seconds=1_000, llm_tokens=100_000, agent_turns=10)),
    )
    input_ref = writer.put_json(
        artifact_id="hotel:historical-input",
        artifact_type="design.world_skeleton",
        value={"kind": "hotel"},
    )
    output_ref = writer.put_json(
        artifact_id="hotel:historical-output",
        artifact_type="design.tool_semantics_batch_source",
        value={"tools": ["reserve_hotel"]},
        dependencies=(input_ref,),
    )
    committed = runtime.execute_deterministic_boundary(
        definition=definition,
        input_refs=(input_ref,),
        subject_ref=output_ref,
        output_refs=(output_ref,),
    )
    assert committed.status == "committed"
    historical_commit_ref = committed.commit_ref
    assert historical_commit_ref is not None

    changed = definition.model_copy(
        update={
            "timing_reason": "A temporary framework revision changed this node.",
            "proposal_policy": definition.proposal_policy.model_copy(
                update={
                    "budget": definition.proposal_policy.budget.model_copy(
                        update={"wall_seconds": 6.0}
                    )
                }
            ),
            "validation_policy": definition.validation_policy.model_copy(
                update={
                    "budget": definition.validation_policy.budget.model_copy(
                        update={"wall_seconds": 6.0}
                    )
                }
            ),
            "repair_policy": definition.repair_policy.model_copy(
                update={"maximum_process_recoveries": 1}
            ),
        }
    )
    assert changed.definition_digest != definition.definition_digest
    assert changed.acceptance_digest == definition.acceptance_digest
    with store.exclusive(definition.coordinate) as lock:
        stale = runtime.supersede_stale(
            lock,
            definition=changed,
            input_refs=(input_ref,),
            previous=committed,
            elapsed_wall_seconds=0,
        )
    stale_attempt = writer.get_json(stale.attempt_ref, WorkAttempt)
    assert stale_attempt.operation_run_refs == ()

    with store.exclusive(definition.coordinate) as lock:
        restored = runtime.reactivate_historical_commit(
            lock,
            definition=changed,
            input_refs=(input_ref,),
        )
    assert restored is not None
    assert restored[1] == historical_commit_ref
    final_head = store.read_head(definition.coordinate)
    assert final_head is not None
    assert final_head.status == "committed"
    assert final_head.definition_digest == changed.definition_digest
    assert final_head.commit_ref == historical_commit_ref
    assert (
        store.require_active_commit(
            definition=changed,
            input_refs=(input_ref,),
            artifacts=writer,
        )
        is not None
    )
    interrupted_attempts = tuple(
        writer.get_json(ref, WorkAttempt)
        for ref in writer.list_revisions(stale.attempt_ref.artifact_id)
        if ref.artifact_type == "control.work_attempt"
    )
    assert any(
        attempt.status == "interrupted" and attempt.failure_code == "historical_commit_reactivated"
        for attempt in interrupted_attempts
    )
    changed_validator = changed.model_copy(
        update={
            "validation_policy": definition.validation_policy.model_copy(
                update={"validator_revision_id": "framework.validator.tool-semantics.v2"}
            )
        }
    )
    assert changed_validator.acceptance_digest != changed.acceptance_digest
    assert (
        store.find_historical_commit(
            definition=changed_validator,
            input_refs=(input_ref,),
            artifacts=writer,
        )
        is None
    )


def test_deterministic_boundary_supersedes_a_terminal_stale_input(
    tmp_path: Path,
) -> None:
    base = _definition()
    definition = base.model_copy(
        update={
            "proposal_policy": ProposalPolicy(
                policy_id="proposal:modeling-boundary:code",
                executor="code",
                operation="design.modeling_boundary",
                budget=OperationBudget(wall_seconds=5),
            )
        }
    )
    writer = _writer(tmp_path)
    store = WorkControlStore(tmp_path / "work-control")
    runtime = WorkControlRuntime(
        artifacts=writer,
        heads=store,
        budget=LeaseBudgetLedger(Budget(wall_seconds=1_000, llm_tokens=100_000, agent_turns=10)),
    )
    first_input = writer.put_json(
        artifact_id="hotel:design",
        artifact_type="design.environment_design",
        value={"revision": 1},
    )
    first_gate = writer.put_json(
        artifact_id="hotel:modeling-gate",
        artifact_type="control.modeling_gate",
        value={"status": "fail"},
        dependencies=(first_input,),
    )
    first = runtime.execute_deterministic_boundary(
        definition=definition,
        input_refs=(first_input,),
        subject_ref=first_gate,
        output_refs=(first_gate,),
        issues=(
            (
                "unresolved_assumptions_forbidden",
                ("modeling_boundary", 0),
                "the design still declares an open model-owned issue",
                "one typed assumption disposition",
            ),
        ),
    )
    assert first.status == "failed"

    second_input = writer.put_json(
        artifact_id="hotel:design",
        artifact_type="design.environment_design",
        value={"revision": 2},
        dependencies=(first_input,),
    )
    second_gate = writer.put_json(
        artifact_id="hotel:modeling-gate",
        artifact_type="control.modeling_gate",
        value={"status": "pass"},
        dependencies=(second_input,),
    )
    second = runtime.execute_deterministic_boundary(
        definition=definition,
        input_refs=(second_input,),
        subject_ref=second_gate,
        output_refs=(second_gate,),
    )

    assert second.status == "committed"
    assert second.revision > first.revision
    assert first.attempt_ref in second.invalidated_by_refs
    second_attempt = writer.get_json(second.attempt_ref, WorkAttempt)
    assert second_attempt.ordinal == 2
    assert second_attempt.observed_actual.agent_turns == 0


def test_deterministic_boundary_recovers_a_report_written_before_head_commit(
    tmp_path: Path,
) -> None:
    base = _definition()
    definition = base.model_copy(
        update={
            "proposal_policy": ProposalPolicy(
                policy_id="proposal:modeling-boundary:recovery",
                executor="code",
                operation="design.modeling_boundary",
                budget=OperationBudget(wall_seconds=5),
            )
        }
    )
    writer = _writer(tmp_path)
    store = WorkControlStore(tmp_path / "work-control")
    runtime = WorkControlRuntime(
        artifacts=writer,
        heads=store,
        budget=LeaseBudgetLedger(Budget(wall_seconds=1_000, llm_tokens=100_000, agent_turns=10)),
    )
    input_ref = writer.put_json(
        artifact_id="hotel:closed-design",
        artifact_type="design.environment_design",
        value={"revision": 2},
    )
    gate_ref = writer.put_json(
        artifact_id="hotel:passed-modeling-gate",
        artifact_type="control.modeling_gate",
        value={"status": "pass"},
        dependencies=(input_ref,),
    )
    with store.exclusive(definition.coordinate) as lock:
        head = runtime.begin(
            lock,
            definition=definition,
            input_refs=(input_ref,),
            elapsed_wall_seconds=0,
        )
        head = runtime.schedule_operation(
            lock,
            definition=definition,
            kind="proposal",
            replay_mode="deterministic",
            elapsed_wall_seconds=0,
        )
        head = runtime.start_operation(
            lock,
            definition=definition,
            dispatch_id="dispatch:modeling-boundary:recovery",
        )
        attempt = writer.get_json(head.attempt_ref, WorkAttempt)
        operation = writer.get_json(head.active_operation_ref, OperationRun)
        assert operation.started_at is not None
        now = operation.started_at
        head = runtime.checkpoint_proposal(
            lock,
            definition=definition,
            execution=ProposalExecution(
                execution_id="execution:modeling-boundary:recovery",
                attempt_id=attempt.attempt_id,
                executor="code",
                executor_revision_id=definition.proposal_policy.executor_revision_id,
                operation=definition.proposal_policy.operation,
                status="completed",
                output_commitment=gate_ref.content_hash,
                observed_actual=BudgetUsage(),
                conservative_committed=BudgetUsage(),
                started_at=now,
                finished_at=now,
                duration_ms=0,
            ),
            output_refs=(gate_ref,),
        )
        attempt = writer.get_json(head.attempt_ref, WorkAttempt)
        report = ValidationReport(
            report_id="report:modeling-boundary:recovery",
            attempt_id=attempt.attempt_id,
            coordinate=definition.coordinate,
            policy_id=definition.validation_policy.policy_id,
            policy_digest=definition.validation_policy.content_digest(),
            subject_refs=(gate_ref,),
            status="passed",
            validation_phase=definition.validation_policy.validation_phase,
            frontier_ordinal=definition.validation_policy.frontier_ordinal,
            passed_check_ids=(definition.required_claim_id,),
            evidence_refs=(gate_ref,),
            diagnostic_quality="not_applicable",
            evaluated_at=now,
        )
        writer.put_json(
            artifact_id=report.report_id,
            artifact_type="control.validation_report",
            value=report,
            dependencies=(head.attempt_ref, gate_ref),
        )

    recovered = runtime.execute_deterministic_boundary(
        definition=definition,
        input_refs=(input_ref,),
        subject_ref=gate_ref,
        output_refs=(gate_ref,),
    )

    assert recovered.status == "committed"
    recovered_attempt = writer.get_json(recovered.attempt_ref, WorkAttempt)
    assert len(recovered_attempt.operation_run_refs) == 2
    assert recovered_attempt.output_refs == (gate_ref,)


def test_restored_work_budget_is_isolated_by_scope(tmp_path: Path) -> None:
    writer = _writer(tmp_path)
    store = WorkControlStore(tmp_path / "work-control")
    reserved = Budget(wall_seconds=1_000, llm_tokens=100_000, agent_turns=10)
    definition_a = _definition()
    definition_b = definition_a.model_copy(
        update={
            "work_id": "work:hotel-b:tool-semantics:1",
            "coordinate": definition_a.coordinate.model_copy(update={"scope_id": "job:hotel-b"}),
        }
    )
    for definition in (definition_a, definition_b):
        runtime = WorkControlRuntime(
            artifacts=writer,
            heads=store,
            budget=LeaseBudgetLedger(reserved),
        )
        input_ref = writer.put_json(
            artifact_id=f"{definition.coordinate.scope_id}:input",
            artifact_type="design.world_skeleton",
            value={"scope": definition.coordinate.scope_id},
        )
        with store.exclusive(definition.coordinate) as lock:
            runtime.begin(
                lock,
                definition=definition,
                input_refs=(input_ref,),
                elapsed_wall_seconds=0,
            )
            runtime.schedule_operation(
                lock,
                definition=definition,
                kind="proposal",
                replay_mode="queryable",
                elapsed_wall_seconds=0,
            )

    restored_a = restore_work_budget_ledger(
        writer,
        reserved=reserved,
        scope_id=definition_a.coordinate.scope_id,
    )
    restored_b = restore_work_budget_ledger(
        writer,
        reserved=reserved,
        scope_id=definition_b.coordinate.scope_id,
    )

    assert len(restored_a.active_leases) == 1
    assert len(restored_b.active_leases) == 1
    assert restored_a.active_leases[0].owner_id != restored_b.active_leases[0].owner_id
    assert restored_a.remaining(elapsed_wall_seconds=0).agent_turns == 9
    assert restored_b.remaining(elapsed_wall_seconds=0).agent_turns == 9


def test_executor_revision_invalidates_failed_execution_but_not_acceptance() -> None:
    definition = _definition()
    changed = definition.model_copy(
        update={
            "proposal_policy": definition.proposal_policy.model_copy(
                update={"executor_revision_id": "framework.codex-structured-protocol.v2"}
            )
        }
    )

    assert changed.definition_digest != definition.definition_digest
    assert changed.acceptance_digest == definition.acceptance_digest


def test_repair_policy_revision_invalidates_attempt_but_not_accepted_output() -> None:
    definition = _definition()
    changed = definition.model_copy(
        update={
            "repair_policy": definition.repair_policy.model_copy(
                update={"policy_revision_id": "framework.repair-authority.v2"}
            )
        }
    )

    assert changed.definition_digest != definition.definition_digest
    assert changed.repair_policy.content_digest() != definition.repair_policy.content_digest()
    assert changed.acceptance_digest == definition.acceptance_digest


def test_repair_authorized_head_accepts_only_exact_continuation_binding(
    tmp_path: Path,
) -> None:
    definition = _definition()
    writer = _writer(tmp_path)
    store = WorkControlStore(tmp_path / "work-control")
    input_ref = writer.put_json(
        artifact_id="hotel:repair-input",
        artifact_type="design.world_skeleton",
        value={"kind": "hotel"},
    )
    attempt_ref = writer.put_json(
        artifact_id="hotel:repair-attempt",
        artifact_type="control.work_attempt",
        value={"attempt_id": "attempt:repair"},
    )
    bound_attempt_ref = writer.put_json(
        artifact_id="hotel:repair-attempt",
        artifact_type="control.work_attempt",
        value={"attempt_id": "attempt:repair", "continuation": "bound"},
        dependencies=(attempt_ref,),
    )
    evaluation_ref = writer.put_json(
        artifact_id="hotel:repair-evaluation",
        artifact_type="control.feedback_evaluation",
        value={"status": "failed"},
    )
    action_ref = writer.put_json(
        artifact_id="hotel:repair-action",
        artifact_type="control.repair_action",
        value={"decision": "local_correction"},
    )
    initial = WorkControlStore.new_head(
        definition=definition,
        input_refs=(input_ref,),
        attempt_ref=attempt_ref,
    )
    authorized = initial.model_copy(
        update={
            "revision": 2,
            "status": "repair_authorized",
            "evaluation_ref": evaluation_ref,
            "repair_action_ref": action_ref,
            "updated_at": datetime.now(UTC),
        }
    )
    bound = authorized.model_copy(
        update={
            "revision": 3,
            "attempt_ref": bound_attempt_ref,
            "updated_at": datetime.now(UTC),
        }
    )
    with store.exclusive(definition.coordinate) as lock:
        store.compare_and_swap(lock, expected_head=None, next_head=initial)
        store.compare_and_swap(lock, expected_head=initial, next_head=authorized)
        store.compare_and_swap(lock, expected_head=authorized, next_head=bound)

    tampered = bound.model_copy(
        update={
            "revision": 4,
            "attempt_ref": attempt_ref,
            "repair_action_ref": writer.put_json(
                artifact_id="hotel:other-repair-action",
                artifact_type="control.repair_action",
                value={"decision": "local_correction"},
            ),
            "updated_at": datetime.now(UTC),
        }
    )
    with store.exclusive(definition.coordinate) as lock:
        with pytest.raises(WorkHeadConflictError, match="preserve exact repair authority"):
            store.compare_and_swap(lock, expected_head=bound, next_head=tampered)
