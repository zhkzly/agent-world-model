from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from typing import Literal

import pytest

from agent_env_foundry.agents import AgentRoute
from agent_env_foundry.assessment import (
    AssessmentPolicy,
    AssessmentRun,
    CorpusPolicy,
    CorpusSelectionCandidate,
    TaskAssessment,
    TaskFoundryProductReport,
    assess_task,
    select_corpus,
)
from agent_env_foundry.batch_foundry import AdmittedTaskRecord, TaskBatchReport
from agent_env_foundry.public_agent import PublicAgentFailure
from agent_env_foundry.semantics import AtomCheckResult, StartCase
from agent_env_foundry.task_foundry import AtomTask, AtomWitness

DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
DIGEST_C = "c" * 64
DIGEST_D = "d" * 64


def _run(index: int, *, satisfied: bool) -> AssessmentRun:
    return AssessmentRun(
        trial_index=index,
        status="satisfied" if satisfied else "failed",
        materialization_id=("1" if satisfied else "2") * 64,
        evidence={"format": "atom-witness/1", "trial": index},
        provider_turns=index,
        input_tokens=10 * index,
        output_tokens=5 * index,
        latency_ms=20 * index,
        failure_codes=() if satisfied else ("ANSWER_MISMATCH",),
    )


def test_task_assessment_is_model_relative_and_does_not_rewrite_taskpack() -> None:
    policy = AssessmentPolicy(
        model_id="gpt-5.6-luna",
        route_digest=DIGEST_B,
        public_agent_prompt_digest=DIGEST_C,
        max_provider_turns=12,
        trial_count=2,
    )
    assessment = TaskAssessment(
        task_pack_id=DIGEST_A,
        release_id=DIGEST_D,
        goal_kind="atom",
        policy=policy,
        runs=(_run(1, satisfied=True), _run(2, satisfied=False)),
    )

    assert assessment.reliability == 0.5
    assert assessment.provider_turns == 3
    assert assessment.input_tokens == 30
    assert assessment.output_tokens == 15
    assert assessment.failure_codes == ("ANSWER_MISMATCH",)
    assert assessment.difficulty == {
        "failure_rate": 0.5,
        "mean_provider_turns": 1.5,
        "mean_tokens": 22.5,
    }
    assert assessment.to_document()["task_pack_id"] == DIGEST_A
    assert len(assessment.assessment_id) == 64


def test_task_assessment_requires_exact_trial_set() -> None:
    policy = AssessmentPolicy(
        "gpt-5.6-luna",
        DIGEST_B,
        DIGEST_C,
        12,
        2,
    )
    with pytest.raises(ValueError, match="trial"):
        TaskAssessment(DIGEST_A, DIGEST_D, "atom", policy, (_run(1, satisfied=True),))


def test_corpus_selection_deduplicates_structure_and_binds_assessments() -> None:
    policy = CorpusPolicy("rl", minimum_reliability=0.5, max_tasks=3)
    candidates = (
        CorpusSelectionCandidate(DIGEST_A, "1" * 64, DIGEST_D, "atom", "4" * 64, 0.7),
        CorpusSelectionCandidate(DIGEST_B, "2" * 64, DIGEST_D, "atom", "4" * 64, 0.9),
        CorpusSelectionCandidate(DIGEST_C, "3" * 64, DIGEST_D, "foreach", "5" * 64, 0.8),
        CorpusSelectionCandidate("6" * 64, "7" * 64, "8" * 64, "if", "9" * 64, 0.4),
    )

    manifest = select_corpus(candidates, policy=policy, seed=7)

    assert len(manifest.entries) == 2
    assert {item.task_pack_id for item in manifest.entries} == {DIGEST_B, DIGEST_C}
    assert len({(item.release_id, item.structure_id) for item in manifest.entries}) == 2
    assert manifest.policy == policy
    assert len(manifest.selection_evidence_digest) == 64
    assert len(manifest.corpus_id) == 64


def test_product_report_keeps_taskpack_assessment_and_corpus_identities_separate() -> None:
    policy = AssessmentPolicy("gpt-5.6-luna", DIGEST_B, DIGEST_C, 12, 1)
    assessment = TaskAssessment(
        DIGEST_A,
        DIGEST_D,
        "atom",
        policy,
        (_run(1, satisfied=True),),
    )
    corpus = select_corpus(
        (
            CorpusSelectionCandidate(
                DIGEST_A,
                assessment.assessment_id,
                DIGEST_D,
                "atom",
                "4" * 64,
                1.0,
            ),
        ),
        policy=CorpusPolicy("rl", 0.5, None),
        seed=0,
    )
    batch = TaskBatchReport(
        DIGEST_D,
        1,
        1,
        1,
        1,
        (AdmittedTaskRecord("atom", "5" * 64, "4" * 64, DIGEST_A, "pack.json"),),
        (),
        (),
    )

    report = TaskFoundryProductReport(batch, (assessment,), corpus)

    assert report.batch.admitted[0].task_pack_id == DIGEST_A
    assert report.assessments[0].assessment_id != DIGEST_A
    assert report.corpus.corpus_id not in {DIGEST_A, assessment.assessment_id}
    assert len(report.product_run_id) == 64

    with pytest.raises(ValueError, match="assess every admitted"):
        TaskFoundryProductReport(batch, (), corpus)
    wrong_entry = replace(corpus.entries[0], assessment_id="9" * 64)
    wrong_corpus = replace(corpus, entries=(wrong_entry,))
    with pytest.raises(ValueError, match="facts differ"):
        TaskFoundryProductReport(batch, (assessment,), wrong_corpus)
    wrong_reliability = replace(corpus.entries[0], reliability=0.5)
    with pytest.raises(ValueError, match="facts differ"):
        TaskFoundryProductReport(
            batch,
            (assessment,),
            replace(corpus, entries=(wrong_reliability,)),
        )
    with pytest.raises(ValueError, match="duplicate TaskAssessments"):
        TaskFoundryProductReport(batch, (assessment, assessment), corpus)


def test_assessment_records_checker_failure_without_weakening_task(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    task = AtomTask(
        DIGEST_D,
        StartCase("default", None, ("default",)),
        "CAP-1",
        "item:1",
        {"item_id": "1"},
        DIGEST_A,
        "Inspect item 1.",
        DIGEST_B,
        {
            "type": "object",
            "additionalProperties": False,
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
        },
    )
    outcomes = iter(
        (
            AtomWitness(
                task.task_id,
                "1" * 64,
                {},
                (),
                {},
                (),
                AtomCheckResult(False, True, True, True, True, True, {}, ()),
                1,
                ({"input_tokens": 10, "output_tokens": 2},),
            ),
            AtomWitness(
                task.task_id,
                "2" * 64,
                {},
                (),
                {},
                (),
                AtomCheckResult(
                    False,
                    False,
                    True,
                    True,
                    False,
                    True,
                    {},
                    ("ANSWER_MISMATCH",),
                ),
                2,
                ({"input_tokens": 12, "output_tokens": 3},),
            ),
        )
    )
    monkeypatch.setattr(
        "agent_env_foundry.assessment.run_atom_task_once",
        lambda *args, **kwargs: next(outcomes),
    )
    route = AgentRoute(max_provider_turns=12)
    policy = AssessmentPolicy.from_route(route, trial_count=2)
    prepared = SimpleNamespace(identity=SimpleNamespace(release_id=DIGEST_D))

    assessment = assess_task(
        prepared,
        "atom",
        task,
        task_pack_id=DIGEST_A,
        atom_task_universe=(task,),
        instance_root=tmp_path,
        policy=policy,
        route=route,
    )

    assert assessment.reliability == 0.5
    assert assessment.runs[1].failure_codes == ("ANSWER_MISMATCH",)
    assert assessment.task_pack_id == DIGEST_A


@pytest.mark.parametrize(
    ("kind", "recorded"),
    (("NoPublicWitness", True), ("InfrastructureFailure", False)),
)
def test_assessment_records_only_model_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    kind: Literal["NoPublicWitness", "InfrastructureFailure"],
    recorded: bool,
) -> None:
    task = AtomTask(
        DIGEST_D,
        StartCase("default", None, ("default",)),
        "CAP-1",
        "item:1",
        {"item_id": "1"},
        DIGEST_A,
        "Inspect item 1.",
        DIGEST_B,
        {
            "type": "object",
            "additionalProperties": False,
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
        },
    )

    def fail(*args, **kwargs):
        raise PublicAgentFailure(kind, "provider_failed", "provider failed")

    monkeypatch.setattr("agent_env_foundry.assessment.run_atom_task_once", fail)
    route = AgentRoute(max_provider_turns=12)
    policy = AssessmentPolicy.from_route(route, trial_count=1)
    prepared = SimpleNamespace(identity=SimpleNamespace(release_id=DIGEST_D))

    def call():
        return assess_task(
            prepared,
            "atom",
            task,
            task_pack_id=DIGEST_A,
            atom_task_universe=(task,),
            instance_root=tmp_path,
            policy=policy,
            route=route,
        )

    if recorded:
        assessment = call()
        assert assessment.reliability == 0.0
        assert assessment.failure_codes == ("provider_failed",)
    else:
        with pytest.raises(PublicAgentFailure) as raised:
            call()
        assert raised.value.kind == "InfrastructureFailure"
