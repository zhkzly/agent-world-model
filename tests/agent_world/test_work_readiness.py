from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent_world.artifact_store import ArtifactStore
from agent_world.control.work import FeedbackEvaluation, WorkCommit
from agent_world.control.work_graph import GenerationWorkGraph, tool_semantics_batch_definition
from agent_world.control.work_readiness import WorkReadinessProjection
from agent_world.control.work_store import WorkControlStore, WorkResumeError


def test_readiness_requires_active_exact_commit_not_a_report_or_output_alone(
    tmp_path: Path,
) -> None:
    artifacts = ArtifactStore(tmp_path / "artifacts").issue_writer(
        producer="work-controller",
        allowed_artifact_type_prefixes=("control.", "design."),
    )
    store = WorkControlStore(tmp_path / "work-control")
    definition = tool_semantics_batch_definition(
        job_id="job:hotel",
        group_id="coupling:booking",
        batch_id="batch:1",
        dependency_coordinates=(),
        agent_wall_seconds=120,
        agent_token_limit=10_000,
    )
    graph = GenerationWorkGraph.compile((definition,))
    input_ref = artifacts.put_json(
        artifact_id="hotel:input",
        artifact_type="design.world_skeleton",
        value={"kind": "hotel"},
    )
    output_ref = artifacts.put_json(
        artifact_id="hotel:output",
        artifact_type="design.tool_semantics_batch_source",
        value={"tools": ["reserve_hotel"]},
        dependencies=(input_ref,),
    )
    attempt_ref = artifacts.put_json(
        artifact_id="hotel:attempt",
        artifact_type="control.work_attempt",
        value={"attempt_id": "attempt:1"},
        dependencies=(input_ref,),
    )
    inputs = {definition.coordinate.coordinate_key: (input_ref,)}
    initial = WorkControlStore.new_head(
        definition=definition,
        input_refs=(input_ref,),
        attempt_ref=attempt_ref,
    )
    with store.exclusive(definition.coordinate) as lock:
        store.compare_and_swap(lock, expected_head=None, next_head=initial)

    incomplete = WorkReadinessProjection.project(
        graph=graph,
        work_store=store,
        artifacts=artifacts,
        input_refs_by_coordinate=inputs,
    )
    assert incomplete.status == "incomplete"
    assert incomplete.satisfied_commit_refs == ()

    evaluation = FeedbackEvaluation(
        evaluation_id="evaluation:hotel:1",
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
    evaluation_ref = artifacts.put_json(
        artifact_id=evaluation.evaluation_id,
        artifact_type="control.feedback_evaluation",
        value=evaluation,
        dependencies=(input_ref, output_ref),
    )
    commit = WorkCommit(
        commit_id="commit:hotel:1",
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
    commit_ref = artifacts.put_json(
        artifact_id=commit.commit_id,
        artifact_type="control.work_commit",
        value=commit,
        dependencies=(input_ref, output_ref, evaluation_ref),
    )
    committed = initial.model_copy(
        update={
            "revision": 2,
            "status": "committed",
            "evaluation_ref": evaluation_ref,
            "commit_ref": commit_ref,
            "updated_at": datetime.now(UTC),
        }
    )
    with store.exclusive(definition.coordinate) as lock:
        store.compare_and_swap(lock, expected_head=initial, next_head=committed)

    with pytest.raises(WorkResumeError, match="successful WorkAttempt"):
        WorkReadinessProjection.project(
            graph=graph,
            work_store=store,
            artifacts=artifacts,
            input_refs_by_coordinate=inputs,
        )
