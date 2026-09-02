from __future__ import annotations

from dataclasses import replace

from agent_env_foundry.task_assessment import (
    CorpusManifest,
    TaskAssessment,
    TaskAssessmentRun,
    select_corpus,
)


def _run(index: int, status: str) -> TaskAssessmentRun:
    return TaskAssessmentRun(
        "task-assessment-run/1",
        index,
        status,
        f"{index}" * 64,
        2,
        100,
        20,
        500,
        None if status == "satisfied" else "NoPublicWitness",
        None if status == "satisfied" else "policy_failed",
    )


def _assessment(
    pack_digit: str,
    *,
    structure_digit: str,
    runs: tuple[TaskAssessmentRun, ...],
) -> TaskAssessment:
    return TaskAssessment(
        "task-assessment/1",
        pack_digit * 64,
        "a" * 64,
        "b" * 64,
        "c" * 64,
        structure_digit * 64,
        runs,
    )


def test_assessment_identity_is_separate_and_abstention_is_not_model_failure() -> None:
    assessment = _assessment(
        "1",
        structure_digit="d",
        runs=(
            _run(1, "satisfied"),
            _run(2, "failed"),
            replace(
                _run(3, "failed"),
                status="abstained",
                failure_kind="InfrastructureFailure",
                failure_code="provider_unavailable",
            ),
        ),
    )

    assert assessment.valid_trials == 2
    assert assessment.reliability == 0.5
    changed = replace(
        assessment,
        runs=(replace(assessment.runs[0], elapsed_ms=900), *assessment.runs[1:]),
    )
    assert changed.assessment_id != assessment.assessment_id
    assert changed.task_pack_id == assessment.task_pack_id


def test_corpus_considers_every_pair_and_selects_one_per_structure() -> None:
    lower = _assessment(
        "1",
        structure_digit="d",
        runs=(_run(1, "satisfied"), _run(2, "failed")),
    )
    higher = _assessment(
        "2",
        structure_digit="d",
        runs=(_run(1, "satisfied"), _run(2, "satisfied")),
    )
    other = _assessment(
        "3",
        structure_digit="e",
        runs=(_run(1, "satisfied"), _run(2, "satisfied")),
    )

    corpus = select_corpus((lower, higher, other), minimum_reliability=0.5)

    assert isinstance(corpus, CorpusManifest)
    assert set(corpus.candidates) == {
        (item.task_pack_id, item.assessment_id) for item in (lower, higher, other)
    }
    assert {item.task_pack_id for item in corpus.entries} == {
        higher.task_pack_id,
        other.task_pack_id,
    }
    assert len({item.structure_id for item in corpus.entries}) == len(corpus.entries)
