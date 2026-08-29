from __future__ import annotations

from dataclasses import replace
from typing import get_args

import pytest

from agent_env_foundry.semantics import PublicValueSource, StartCase
from agent_task_foundry.models import (
    AdmissionPlan,
    AdmissionReport,
    AllGoal,
    ArgumentOrigin,
    AssessmentRun,
    AtomGoal,
    AtomReportRef,
    ChallengePlan,
    ChallengeResult,
    CheckerArtifact,
    CheckerMutationPlan,
    CheckerMutationResult,
    ConditionReportRef,
    CorpusManifest,
    EpisodeIdentity,
    FacetPredicate,
    ForEachGoal,
    FoundryFailure,
    GoalProgram,
    IfGoal,
    LogicalBindingRef,
    LogicalSelection,
    OrderingEvent,
    OrderingJournal,
    ProvenanceReport,
    PublicTraceEvent,
    PublicValueOccurrence,
    RankSpec,
    ReportSpec,
    ResolvedBinding,
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


def _logical(blueprint: TaskBlueprint) -> tuple[LogicalBindingRef, ...]:
    return (
        LogicalBindingRef(
            "target",
            "finish",
            "item-alpha",
            blueprint.selectors[0].selector_id,
            {"name": "alpha"},
        ),
    )


def _selections() -> tuple[LogicalSelection, ...]:
    return (LogicalSelection(_blueprint().selectors[0], ("item-alpha",)),)


def _checker(blueprint: TaskBlueprint) -> CheckerArtifact:
    return CheckerArtifact(
        task_preimage_digest=digest_document(
            {"start_case_id": "case-1", "blueprint": blueprint.to_document()}
        ),
        goal_program=blueprint.goal,
        logical_bindings=_logical(blueprint),
        logical_selections=_selections(),
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
        logical_bindings=_logical(blueprint),
        logical_selections=_selections(),
        public_instruction_frame={
            "name": "alpha",
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
    assert "protected_bindings" not in protected
    assert protected["logical_bindings"][0]["semantic_key"] == "item-alpha"
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


def _trace(materialization_id: str) -> tuple[PublicTraceEvent, ...]:
    occurrence = PublicValueOccurrence(
        PublicValueSource("task_literal", None, None, "alpha"),
        materialization_id,
        "/name",
        None,
        None,
    )
    provenance = ProvenanceReport((ArgumentOrigin("/name", occurrence, True),))
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
        episode=EpisodeIdentity(
            materialization_id,
            DIGEST_A,
            DIGEST_B,
            DIGEST_C,
            f"conversation-{materialization_id[0]}",
        ),
        task_definition_id=definition.task_id,
        start_case_id=definition.start_case.case_id,
        reset_observation={"name": "alpha"},
        resolved_bindings=(
            ResolvedBinding(
                definition.logical_bindings[0].logical_ref_digest,
                materialization_id,
                {"native_id": 1},
                {"name": "alpha"},
                DIGEST_D,
            ),
        ),
        trace=_trace(materialization_id),
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
    plan = _plan(definition)
    challenge = ChallengeResult("no_op", "passed", None, DIGEST_E)
    mutation = CheckerMutationResult(
        "drop-goal",
        True,
        True,
        DIGEST_F,
        DIGEST_E,
        None,
    )
    report = AdmissionReport(
        task_definition_id=definition.task_id,
        checker_digest=definition.checker.checker_digest,
        plan_digest=plan.plan_digest,
        witness_digests=(first.run_id, second.run_id),
        challenges=(challenge,),
        checker_mutations=(mutation,),
    )
    report.validate_plan(plan)
    return report


def _plan(definition: TaskDefinition) -> AdmissionPlan:
    return AdmissionPlan(
        definition.task_id,
        definition.checker.checker_digest,
        (ChallengePlan("no_op", True, None),),
        (CheckerMutationPlan("drop-goal", True, None),),
    )


def _ordering(definition: TaskDefinition, plan: AdmissionPlan) -> OrderingJournal:
    return OrderingJournal(
        (
            OrderingEvent(1, "checker_frozen", definition.checker.checker_digest),
            OrderingEvent(
                2,
                "instruction_frozen",
                digest_document(definition.canonical_instruction),
            ),
            OrderingEvent(3, "task_persisted", definition.task_id),
            OrderingEvent(4, "model_call_allowed", plan.plan_digest),
        )
    )


def _pack(
    definition: TaskDefinition,
    first: WitnessRun,
    second: WitnessRun,
    report: AdmissionReport | None = None,
) -> TaskPack:
    plan = _plan(definition)
    return TaskPack(
        definition,
        (first, second),
        plan,
        _ordering(definition, plan),
        report or _admission(first, second, definition),
    )


def test_taskpack_requires_two_bound_fresh_witnesses_and_real_evidence_digests() -> None:
    definition = _definition()
    first = _witness(definition, DIGEST_E)
    second = _witness(definition, DIGEST_F)
    pack = _pack(definition, first, second)
    assert pack.taskpack_id
    assert pack.public_document() == {
        "taskpack_id": pack.taskpack_id,
        "task": definition.public_document(),
    }

    with pytest.raises(TaskModelError, match="fresh materializations"):
        TaskPack(
            definition,
            (first, _witness(definition, DIGEST_E)),
            _plan(definition),
            _ordering(definition, _plan(definition)),
            _admission(first, second, definition),
        )
    bad_admission = replace(
        _admission(first, second, definition),
        witness_digests=(DIGEST_A, DIGEST_B),
    )
    with pytest.raises(TaskModelError, match="witness evidence"):
        _pack(definition, first, second, bad_admission)


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
        ArgumentOrigin("/message", "ambient", True)  # type: ignore[arg-type]
    report = ProvenanceReport((ArgumentOrigin("/message", "agent_choice", True),))
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
    pack = _pack(definition, first, second)
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
