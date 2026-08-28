from __future__ import annotations

from dataclasses import replace
from typing import get_args

import pytest

from agent_env_foundry.semantics import StartCase
from agent_task_foundry.models import (
    AdmissionReport,
    AllGoal,
    ArgumentOrigin,
    AssessmentRun,
    AtomGoal,
    AtomReportRef,
    ChallengeResult,
    CheckerArtifact,
    CheckerMutationResult,
    ConditionReportRef,
    CorpusManifest,
    FacetPredicate,
    ForEachGoal,
    FoundryFailure,
    GoalProgram,
    IfGoal,
    OrderingEvent,
    OrderingJournal,
    ProvenanceReport,
    PublicTraceEvent,
    RankSpec,
    ReportSpec,
    SelectorSpec,
    TaskAssessment,
    TaskBlueprint,
    TaskDefinition,
    TaskFingerprint,
    TaskModelError,
    TaskPack,
    WitnessRun,
    digest_document,
)

DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
DIGEST_C = "c" * 64
DIGEST_D = "d" * 64
DIGEST_E = "e" * 64
DIGEST_F = "f" * 64
OBJECT = {"type": "object", "additionalProperties": False}


def test_goal_program_has_exactly_four_nodes_and_full_cardinality_contract() -> None:
    assert set(get_args(GoalProgram.__value__)) == {AtomGoal, AllGoal, IfGoal, ForEachGoal}
    selector = SelectorSpec(
        "target",
        "finish",
        (FacetPredicate("name", "eq", "alpha"),),
        RankSpec("priority", "max"),
        "any_one",
    )
    assert selector.cardinality == "any_one"
    with pytest.raises(TaskModelError, match="cardinality"):
        replace(selector, cardinality="one")  # type: ignore[arg-type]


def _blueprint() -> TaskBlueprint:
    selector = SelectorSpec(
        "target",
        "finish",
        (FacetPredicate("name", "eq", "alpha"),),
        None,
        "exactly_one",
    )
    return TaskBlueprint(
        (selector,),
        AtomGoal("finish", "target"),
        ReportSpec((AtomReportRef("finish", "target", "confirmation"),)),
    )


def _checker(blueprint: TaskBlueprint) -> CheckerArtifact:
    return CheckerArtifact(
        task_preimage_digest=digest_document(
            {"start_case_id": "case-1", "blueprint": blueprint.to_document()}
        ),
        goal_program=blueprint.goal,
        selector_resolutions={"target": ["item-alpha"]},
        protected_bindings={"item-alpha": {"native_id": 1}},
        answer_schema={
            "type": "object",
            "properties": {"confirmation": {"type": "string"}},
            "required": ["confirmation"],
            "additionalProperties": False,
        },
        semantics_digest=DIGEST_B,
    )


def _definition(*, instruction: str = "Finish the item named alpha.") -> TaskDefinition:
    blueprint = _blueprint()
    return TaskDefinition(
        release_id=DIGEST_A,
        semantics_digest=DIGEST_B,
        start_case=StartCase("case-1", {"seed": 1}, ("baseline",)),
        blueprint=blueprint,
        protected_bindings={"item-alpha": {"native_id": 1}},
        public_instruction_frame={
            "reset_context": {"user": "operator"},
            "answer_schema": _checker(blueprint).answer_schema,
            "limitations": [],
        },
        canonical_instruction=instruction,
        answer_schema=_checker(blueprint).answer_schema,
        checker=_checker(blueprint),
    )


def test_task_definition_identity_is_non_circular_and_public_projection_is_blind() -> None:
    first = _definition()
    second = _definition(instruction="Finish the item named beta.")
    assert first.task_id != second.task_id
    assert "task_id" not in first.identity_preimage_document()
    public = first.public_document()
    assert public["task_id"] == first.task_id
    assert "protected_bindings" not in public
    assert "checker" not in public
    assert "semantics_digest" not in public
    protected = first.protected_document()
    assert protected["semantics_digest"] == DIGEST_B
    assert protected["checker"]["semantics_digest"] == DIGEST_B


def test_report_sources_are_typed_and_condition_goal_requires_a_branch() -> None:
    report = ReportSpec(
        (
            AtomReportRef("finish", "target", "confirmation"),
            ConditionReportRef("can_finish", "target", "reason"),
        )
    )
    assert report.to_document()["fields"][1]["kind"] == "condition"
    with pytest.raises(TaskModelError, match="at least one"):
        IfGoal("can_finish", "target", None, None)
    with pytest.raises(TaskModelError, match="at least two"):
        AllGoal("workflow-all", (AtomGoal("finish", "target"),))
    selector = SelectorSpec("target", "finish", (), None, "exactly_one")
    with pytest.raises(TaskModelError, match="goal-less.*report"):
        TaskBlueprint(
            (selector,),
            IfGoal("can_finish", "target", AtomGoal("finish", "target"), None),
            None,
        )


def test_ordering_journal_mechanically_gates_model_calls() -> None:
    with pytest.raises(TaskModelError, match="kind"):
        OrderingEvent(1, "persisted", DIGEST_A)  # type: ignore[arg-type]
    prefix = OrderingJournal((OrderingEvent(1, "checker_frozen", DIGEST_A),))
    assert not prefix.model_call_allowed
    journal = OrderingJournal(
        (
            OrderingEvent(1, "checker_frozen", DIGEST_A),
            OrderingEvent(2, "instruction_frozen", DIGEST_B),
            OrderingEvent(3, "task_persisted", DIGEST_C),
            OrderingEvent(4, "model_call_allowed", DIGEST_D),
        )
    )
    assert journal.model_call_allowed
    with pytest.raises(TaskModelError, match="ordering"):
        OrderingJournal(
            (
                OrderingEvent(1, "instruction_frozen", DIGEST_B),
                OrderingEvent(2, "checker_frozen", DIGEST_A),
                OrderingEvent(3, "task_persisted", DIGEST_C),
                OrderingEvent(4, "model_call_allowed", DIGEST_D),
            )
        )


def _trace() -> tuple[PublicTraceEvent, ...]:
    provenance = ProvenanceReport(
        (ArgumentOrigin("/name", "instruction", "/selectors/target", True),)
    )
    return (
        PublicTraceEvent(
            1,
            "finish_item",
            {"name": "alpha"},
            {"ok": True, "data": {"confirmation": "ok-alpha"}, "error": None},
            provenance,
        ),
    )


def _witness(definition: TaskDefinition, materialization_id: str) -> WitnessRun:
    return WitnessRun(
        materialization_id=materialization_id,
        task_definition_id=definition.task_id,
        start_case_id=definition.start_case.case_id,
        trace=_trace(),
        final_answer={"confirmation": "ok-alpha"},
        checker_digest=definition.checker.checker_digest,
        before_facts_digest=DIGEST_C,
        after_facts_digest=DIGEST_D,
        checker_status="satisfied",
        checker_failures=(),
    )


def _admission(
    first: WitnessRun,
    second: WitnessRun,
    definition: TaskDefinition,
) -> AdmissionReport:
    challenge = ChallengeResult("no_op", "passed", None, DIGEST_E)
    mutation = CheckerMutationResult(
        "drop-goal",
        True,
        True,
        DIGEST_F,
        DIGEST_E,
        None,
    )
    return AdmissionReport(
        definition.task_id,
        definition.checker.checker_digest,
        (first.run_id, second.run_id),
        (challenge,),
        (mutation,),
    )


def test_taskpack_requires_two_bound_fresh_witnesses_and_real_evidence_digests() -> None:
    definition = _definition()
    first = _witness(definition, DIGEST_E)
    second = _witness(definition, DIGEST_F)
    pack = TaskPack(definition, (first, second), _admission(first, second, definition))
    assert pack.taskpack_id
    assert pack.public_document() == {
        "taskpack_id": pack.taskpack_id,
        "task": definition.public_document(),
    }

    with pytest.raises(TaskModelError, match="fresh materializations"):
        TaskPack(
            definition,
            (first, replace(second, materialization_id=DIGEST_E)),
            _admission(first, second, definition),
        )
    bad_admission = replace(
        _admission(first, second, definition),
        witness_digests=(DIGEST_A, DIGEST_B),
    )
    with pytest.raises(TaskModelError, match="witness evidence"):
        TaskPack(definition, (first, second), bad_admission)


def test_challenge_and_mutation_records_cannot_assert_success_without_evidence() -> None:
    with pytest.raises(TaskModelError, match="evidence_digest"):
        ChallengeResult("wrong_target", "passed", None, None)
    not_applicable = ChallengeResult("process", "not_applicable", "no_process_rule", None)
    assert not_applicable.reason_code == "no_process_rule"
    with pytest.raises(TaskModelError, match="reachable mutation"):
        CheckerMutationResult("drop-goal", True, True, DIGEST_F, None, None)
    with pytest.raises(TaskModelError, match="verdict"):
        ChallengeResult("wrong_target", "accepted", None, DIGEST_E)  # type: ignore[arg-type]


def test_load_bearing_agent_choice_is_not_complete_provenance() -> None:
    with pytest.raises(TaskModelError, match="source"):
        ArgumentOrigin("/message", "ambient", None, True)  # type: ignore[arg-type]
    report = ProvenanceReport((ArgumentOrigin("/message", "agent_choice", None, True),))
    assert not report.complete


def test_runtime_checker_status_is_closed() -> None:
    definition = _definition()
    with pytest.raises(TaskModelError, match="checker_status"):
        replace(
            _witness(definition, DIGEST_E),
            checker_status="done",  # type: ignore[arg-type]
        )
    with pytest.raises(TaskModelError, match="status"):
        AssessmentRun(DIGEST_C, "done", 1, 1, 1, 1, None)  # type: ignore[arg-type]


def test_assessment_and_corpus_identity_stay_outside_taskpack() -> None:
    definition = _definition()
    first = _witness(definition, DIGEST_E)
    second = _witness(definition, DIGEST_F)
    pack = TaskPack(definition, (first, second), _admission(first, second, definition))
    run = AssessmentRun(DIGEST_C, "satisfied", 1, 100, 50, 120, None)
    assessment = TaskAssessment(
        pack.taskpack_id,
        "gpt-5.6-luna",
        DIGEST_A,
        DIGEST_B,
        (run,),
        1.0,
        1,
        150,
        120,
        (),
    )
    fingerprint = TaskFingerprint(
        ("finish",),
        ("workflow",),
        (),
        "atom",
        ("eq",),
        1,
        1,
        ("baseline",),
        True,
        False,
    )
    manifest = CorpusManifest(
        DIGEST_A,
        7,
        (pack.taskpack_id,),
        (assessment.assessment_id,),
        DIGEST_B,
    )
    assert assessment.assessment_id not in pack.to_document()
    assert fingerprint.fingerprint_id
    assert manifest.corpus_id


def test_non_success_outcomes_are_closed_and_evidence_bound() -> None:
    failure = FoundryFailure("NoPublicWitness", "budget_exhausted", "No witness found", (DIGEST_A,))
    assert failure.to_document()["kind"] == "NoPublicWitness"
    with pytest.raises(TaskModelError, match="failure kind"):
        FoundryFailure("Anything", "bad", "bad", ())  # type: ignore[arg-type]
