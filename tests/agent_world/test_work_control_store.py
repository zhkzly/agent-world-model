from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent_world.artifact_store import ArtifactStore
from agent_world.control.work import (
    FeedbackEvaluation,
    OperationBudget,
    ProposalPolicy,
    RepairPolicy,
    ValidationPolicy,
    WorkCommit,
    WorkCoordinate,
    WorkDefinition,
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
            next_head=interrupted.model_copy(
                update={"revision": 3, "status": "failed"}
            ),
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
    evaluation = FeedbackEvaluation(
        evaluation_id="evaluation:hotel:tool-semantics:1",
        attempt_id="attempt:1",
        work_id=definition.work_id,
        coordinate=definition.coordinate,
        claim_id=definition.required_claim_id,
        policy_digest=definition.validation_policy.content_digest(),
        status="passed",
        effect=definition.validation_policy.effect,
        readiness_effect="satisfies",
        subject_ref=output_ref,
        assurance_evidence_refs=(output_ref,),
        evaluated_at=datetime.now(UTC),
    )
    evaluation_ref = writer.put_json(
        artifact_id=evaluation.evaluation_id,
        artifact_type="control.feedback_evaluation",
        value=evaluation,
        dependencies=(input_ref, output_ref),
    )
    commit = WorkCommit(
        commit_id="commit:hotel:tool-semantics:1",
        work_id=definition.work_id,
        coordinate=definition.coordinate,
        attempt_id="attempt:1",
        definition_digest=definition.definition_digest,
        validation_policy_digest=definition.validation_policy.content_digest(),
        input_refs=(input_ref,),
        output_refs=(output_ref,),
        feedback_evaluation_ref=evaluation_ref,
        committed_at=datetime.now(UTC),
    )
    commit_ref = writer.put_json(
        artifact_id=commit.commit_id,
        artifact_type="control.work_commit",
        value=commit,
        dependencies=(input_ref, output_ref, evaluation_ref),
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
