from __future__ import annotations

from dataclasses import fields, replace

import pytest

from agent_env_foundry.semantics import PublicValueSource, StartCase
from agent_task_foundry.models import (
    AdmissionPlan,
    AdmissionReport,
    AllGoal,
    ArgumentOrigin,
    AtomGoal,
    ChallengePlan,
    ChallengeResult,
    CheckerArtifact,
    CheckerMutationPlan,
    CheckerMutationResult,
    EpisodeIdentity,
    FacetPredicate,
    ForEachGoal,
    LogicalBindingRef,
    LogicalSelection,
    OrderingEvent,
    OrderingJournal,
    ProvenanceReport,
    PublicTraceEvent,
    PublicValueOccurrence,
    ResolvedBinding,
    SelectorSpec,
    TaskBlueprint,
    TaskDefinition,
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


def _selector() -> SelectorSpec:
    return SelectorSpec(
        "target",
        "finish",
        (FacetPredicate("name", "eq", "alpha"),),
        None,
        "exactly_one",
    )


def _logical() -> LogicalBindingRef:
    return LogicalBindingRef(
        slot="target",
        capability_id="finish",
        semantic_key="item-alpha",
        selector_id=_selector().selector_id,
        instruction_values={"name": "alpha"},
    )


def _selection() -> LogicalSelection:
    return LogicalSelection(
        selector=_selector(),
        semantic_keys=("item-alpha",),
    )


def _definition() -> TaskDefinition:
    blueprint = TaskBlueprint((_selector(),), AtomGoal("finish", "target"), None)
    checker = CheckerArtifact(
        task_preimage_digest=digest_document(
            {"start_case_id": "case-1", "blueprint": blueprint.to_document()}
        ),
        goal_program=blueprint.goal,
        logical_bindings=(_logical(),),
        logical_selections=(_selection(),),
        answer_schema=None,
        semantics_digest=DIGEST_B,
    )
    return TaskDefinition(
        release_id=DIGEST_A,
        semantics_digest=DIGEST_B,
        start_case=StartCase("case-1", {"seed": 1}, ("baseline",)),
        blueprint=blueprint,
        logical_bindings=(_logical(),),
        logical_selections=(_selection(),),
        public_instruction_frame={"name": "alpha"},
        canonical_instruction="Finish the item named alpha.",
        answer_schema=None,
        checker=checker,
    )


def test_definition_and_checker_bind_only_logical_not_protected_materialization_data() -> None:
    definition = _definition()
    protected = definition.protected_document()
    assert "protected_bindings" not in protected
    assert protected["logical_bindings"][0]["semantic_key"] == "item-alpha"
    assert "native_id" not in repr(protected)
    assert "protected_bindings" not in {field.name for field in fields(TaskDefinition)}
    different_binding = replace(_logical(), semantic_key="item-beta")
    different_membership = replace(_selection(), semantic_keys=("item-beta",))
    with pytest.raises(TaskModelError, match="different logical bindings"):
        replace(
            definition,
            logical_bindings=(different_binding,),
            logical_selections=(different_membership,),
        )
    with pytest.raises(TaskModelError, match="different logical selections"):
        checker_selection = LogicalSelection(
            replace(_selector(), cardinality="any_one"),
            ("item-alpha",),
        )
        replace(
            definition,
            checker=replace(
                definition.checker,
                logical_selections=(checker_selection,),
            ),
        )
    with pytest.raises(TaskModelError, match="checker goal"):
        replace(
            definition,
            checker=replace(
                definition.checker,
                goal_program=AtomGoal("finish", "missing-slot"),
            ),
        )
    with pytest.raises(TaskModelError, match="answer schema"):
        replace(definition, answer_schema={"type": "object"})
    with pytest.raises(TaskModelError, match="task preimage"):
        replace(
            definition,
            checker=replace(definition.checker, task_preimage_digest=DIGEST_F),
        )
    bad_goal = replace(
        definition.blueprint,
        goal=AtomGoal("finish", "missing-slot"),
    )
    with pytest.raises(TaskModelError, match="missing logical binding slot"):
        replace(
            definition,
            blueprint=bad_goal,
            checker=replace(
                definition.checker,
                goal_program=bad_goal.goal,
                task_preimage_digest=digest_document(
                    {
                        "start_case_id": definition.start_case.case_id,
                        "blueprint": bad_goal.to_document(),
                    }
                ),
            ),
        )
    extra_selector = SelectorSpec("unused", "finish", (), None, "exactly_one")
    extra_binding = LogicalBindingRef(
        "unused-member", "finish", "unused-key", "unused", {"name": "unused"}
    )
    extra_selection = LogicalSelection(extra_selector, ("unused-key",))
    extra_blueprint = replace(
        definition.blueprint,
        selectors=(*definition.blueprint.selectors, extra_selector),
    )
    extra_checker = CheckerArtifact(
        digest_document(
            {
                "start_case_id": definition.start_case.case_id,
                "blueprint": extra_blueprint.to_document(),
            }
        ),
        definition.checker.goal_program,
        (*definition.logical_bindings, extra_binding),
        (*definition.logical_selections, extra_selection),
        definition.answer_schema,
        definition.semantics_digest,
    )
    with pytest.raises(TaskModelError, match="unused logical"):
        TaskDefinition(
            definition.release_id,
            definition.semantics_digest,
            definition.start_case,
            extra_blueprint,
            (*definition.logical_bindings, extra_binding),
            (*definition.logical_selections, extra_selection),
            definition.public_instruction_frame,
            definition.canonical_instruction,
            definition.answer_schema,
            extra_checker,
        )
    duplicate_goal = AllGoal(
        "duplicate-composition",
        (AtomGoal("finish", "target"), AtomGoal("finish", "target")),
    )
    duplicate_blueprint = replace(definition.blueprint, goal=duplicate_goal)
    duplicate_checker = replace(
        definition.checker,
        goal_program=duplicate_goal,
        task_preimage_digest=digest_document(
            {
                "start_case_id": definition.start_case.case_id,
                "blueprint": duplicate_blueprint.to_document(),
            }
        ),
    )
    with pytest.raises(TaskModelError, match="consumes logical slot.*more than once"):
        replace(
            definition,
            blueprint=duplicate_blueprint,
            checker=duplicate_checker,
        )


def test_logical_selection_and_resolution_close_fresh_set_drift() -> None:
    selection = LogicalSelection(
        selector=SelectorSpec("all-items", "finish", (), None, "all"),
        semantic_keys=("item-alpha", "item-beta"),
    )
    assert selection.selection_digest
    single_exact = LogicalSelection(
        replace(selection.selector, cardinality="exactly_one"),
        ("item-alpha",),
    )
    single_any = replace(
        single_exact,
        selector=replace(single_exact.selector, cardinality="any_one"),
    )
    assert single_any.selection_digest != single_exact.selection_digest
    with pytest.raises(TaskModelError, match="cardinality.*one member"):
        LogicalSelection(
            replace(selection.selector, cardinality="exactly_one"),
            selection.semantic_keys,
        )
    with pytest.raises(TaskModelError, match="cardinality.*one member"):
        LogicalSelection(
            replace(selection.selector, cardinality="any_one"),
            selection.semantic_keys,
        )
    with pytest.raises(TaskModelError, match="semantic_keys"):
        replace(selection, semantic_keys=("item-alpha", "item-alpha"))
    resolved = ResolvedBinding(
        logical_ref_digest=_logical().logical_ref_digest,
        materialization_id=DIGEST_C,
        protected_binding={"native_id": 42},
        public_descriptor={"name": "alpha"},
        source_evidence_digest=DIGEST_D,
    )
    assert resolved.materialization_id == DIGEST_C


def test_public_value_occurrence_is_bound_to_one_episode_event() -> None:
    source = PublicValueSource("tool_output", "lookup", "/items/0/id", None)
    occurrence = PublicValueOccurrence(
        source=source,
        materialization_id=DIGEST_C,
        instruction_slot=None,
        trace_event_seq=2,
        json_pointer="/items/0/id",
    )
    report = ProvenanceReport((ArgumentOrigin("/target_id", occurrence, True),))
    assert report.complete
    with pytest.raises(TaskModelError, match="trace_event_seq"):
        replace(occurrence, trace_event_seq=None)
    with pytest.raises(TaskModelError, match="instruction_slot"):
        PublicValueOccurrence(
            PublicValueSource("task_literal", None, None, None),
            DIGEST_C,
            None,
            None,
            None,
        )


def test_episode_identity_is_fresh_and_admission_report_covers_frozen_plan() -> None:
    first = EpisodeIdentity(DIGEST_C, DIGEST_A, DIGEST_B, DIGEST_D, "conversation-1")
    second = EpisodeIdentity(DIGEST_C, DIGEST_A, DIGEST_B, DIGEST_D, "conversation-2")
    assert first.episode_id != second.episode_id
    plan = AdmissionPlan(
        task_definition_id=DIGEST_A,
        checker_digest=DIGEST_B,
        challenges=(
            ChallengePlan("no_op", True, None),
            ChallengePlan("process", False, "no_process_rule"),
        ),
        checker_mutations=(CheckerMutationPlan("drop-goal", True, None),),
    )
    report = AdmissionReport(
        task_definition_id=DIGEST_A,
        checker_digest=DIGEST_B,
        plan_digest=plan.plan_digest,
        witness_digests=(DIGEST_C, DIGEST_D),
        challenges=(
            ChallengeResult("no_op", "passed", None, DIGEST_E),
            ChallengeResult("process", "not_applicable", "no_process_rule", None),
        ),
        checker_mutations=(
            CheckerMutationResult("drop-goal", True, True, DIGEST_F, DIGEST_E, None),
        ),
    )
    report.validate_plan(plan)
    assert report.accepted
    with pytest.raises(TaskModelError, match="plan"):
        replace(report, challenges=report.challenges[:1]).validate_plan(plan)
    unreachable = replace(
        report,
        checker_mutations=(
            CheckerMutationResult(
                "drop-goal",
                False,
                False,
                DIGEST_F,
                None,
                "mutant_unreachable",
            ),
        ),
    )
    with pytest.raises(TaskModelError, match="applicable.*unreachable"):
        unreachable.validate_plan(plan)


def _episode(materialization_id: str, conversation: str) -> EpisodeIdentity:
    return EpisodeIdentity(materialization_id, DIGEST_A, DIGEST_B, DIGEST_D, conversation)


def _resolved(definition: TaskDefinition, materialization_id: str) -> ResolvedBinding:
    return ResolvedBinding(
        definition.logical_bindings[0].logical_ref_digest,
        materialization_id,
        {"native_id": 7},
        {"name": "alpha"},
        DIGEST_E,
    )


def _witness(
    definition: TaskDefinition,
    materialization_id: str,
    conversation: str,
) -> WitnessRun:
    occurrence = PublicValueOccurrence(
        PublicValueSource("task_literal", None, None, "alpha"),
        materialization_id,
        "/name",
        None,
        None,
    )
    trace = (
        PublicTraceEvent(
            1,
            "finish_item",
            {"name": "alpha"},
            {"ok": True, "data": {"done": True}, "error": None},
            ProvenanceReport((ArgumentOrigin("/name", occurrence, True),)),
        ),
    )
    return WitnessRun(
        episode=_episode(materialization_id, conversation),
        task_definition_id=definition.task_id,
        start_case_id=definition.start_case.case_id,
        reset_observation={"items": [{"name": "alpha"}]},
        resolved_bindings=(_resolved(definition, materialization_id),),
        trace=trace,
        final_answer=None,
        checker_digest=definition.checker.checker_digest,
        before_facts_digest=DIGEST_C,
        after_facts_digest=DIGEST_D,
        checker_status="satisfied",
        checker_failures=(),
    )


def _plan(definition: TaskDefinition) -> AdmissionPlan:
    return AdmissionPlan(
        definition.task_id,
        definition.checker.checker_digest,
        (ChallengePlan("no_op", True, None),),
        (CheckerMutationPlan("drop-goal", True, None),),
    )


def _report(
    definition: TaskDefinition,
    plan: AdmissionPlan,
    first: WitnessRun,
    second: WitnessRun,
) -> AdmissionReport:
    return AdmissionReport(
        definition.task_id,
        definition.checker.checker_digest,
        plan.plan_digest,
        (first.run_id, second.run_id),
        (ChallengeResult("no_op", "passed", None, DIGEST_E),),
        (CheckerMutationResult("drop-goal", True, True, DIGEST_F, DIGEST_E, None),),
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


def test_taskpack_consumes_resolution_occurrence_ordering_and_admission_plan() -> None:
    definition = _definition()
    plan = _plan(definition)
    first = _witness(definition, DIGEST_C, "conversation-1")
    second = _witness(definition, DIGEST_D, "conversation-2")
    report = _report(definition, plan, first, second)
    ordering = _ordering(definition, plan)
    pack = TaskPack(definition, (first, second), plan, ordering, report)
    assert pack.taskpack_id

    wrong_start_first = replace(first, start_case_id="other-case")
    wrong_start_second = replace(second, start_case_id="other-case")
    wrong_start_report = _report(
        definition,
        plan,
        wrong_start_first,
        wrong_start_second,
    )
    with pytest.raises(TaskModelError, match="TaskDefinition start case"):
        TaskPack(
            definition,
            (wrong_start_first, wrong_start_second),
            plan,
            ordering,
            wrong_start_report,
        )

    unknown = replace(
        second,
        resolved_bindings=(replace(second.resolved_bindings[0], logical_ref_digest=DIGEST_F),),
    )
    with pytest.raises(TaskModelError, match="logical binding resolutions"):
        TaskPack(definition, (first, unknown), plan, ordering, report)

    with pytest.raises(TaskModelError, match="admission plan"):
        TaskPack(
            definition,
            (first, second),
            plan,
            ordering,
            replace(report, plan_digest=DIGEST_F),
        )

    origin = first.trace[0].provenance.origins[0]
    assert isinstance(origin.source, PublicValueOccurrence)
    bad_literal_witness = replace(
        first,
        trace=(
            replace(
                first.trace[0],
                provenance=ProvenanceReport(
                    (
                        replace(
                            origin,
                            source=replace(origin.source, instruction_slot="/missing"),
                        ),
                    )
                ),
            ),
        ),
    )
    with pytest.raises(TaskModelError, match="instruction frame"):
        TaskPack(definition, (bad_literal_witness, second), plan, ordering, report)

    mismatched_origin = replace(
        origin,
        source=replace(origin.source, source=replace(origin.source.source, value="beta")),
    )
    mismatched_literal_witness = replace(
        first,
        trace=(
            replace(
                first.trace[0],
                arguments={"name": "beta"},
                provenance=ProvenanceReport((mismatched_origin,)),
            ),
        ),
    )
    with pytest.raises(TaskModelError, match="differs from frozen instruction frame"):
        TaskPack(
            definition,
            (mismatched_literal_witness, second),
            plan,
            ordering,
            report,
        )

    bad_ordering = replace(
        ordering,
        events=(*ordering.events[:3], OrderingEvent(4, "model_call_allowed", DIGEST_F)),
    )
    with pytest.raises(TaskModelError, match="ordering evidence"):
        TaskPack(definition, (first, second), plan, bad_ordering, report)


def test_witness_rejects_occurrence_not_found_in_actual_prior_trace() -> None:
    definition = _definition()
    materialization_id = DIGEST_C
    bad_occurrence = PublicValueOccurrence(
        PublicValueSource("tool_output", "lookup", "/id", None),
        materialization_id,
        None,
        99,
        "/id",
    )
    event = PublicTraceEvent(
        1,
        "finish_item",
        {"target_id": "hidden"},
        {"ok": True, "data": {"done": True}, "error": None},
        ProvenanceReport((ArgumentOrigin("/target_id", bad_occurrence, True),)),
    )
    with pytest.raises(TaskModelError, match="prior trace event"):
        WitnessRun(
            episode=_episode(materialization_id, "conversation-bad"),
            task_definition_id=definition.task_id,
            start_case_id=definition.start_case.case_id,
            reset_observation={},
            resolved_bindings=(_resolved(definition, materialization_id),),
            trace=(event,),
            final_answer=None,
            checker_digest=definition.checker.checker_digest,
            before_facts_digest=DIGEST_C,
            after_facts_digest=DIGEST_D,
            checker_status="satisfied",
            checker_failures=(),
        )

    source_event = PublicTraceEvent(
        1,
        "search",
        {},
        {"ok": True, "data": {"id": "public-id"}, "error": None},
        ProvenanceReport(()),
    )
    wrong_tool_occurrence = replace(bad_occurrence, trace_event_seq=1)
    use_event = PublicTraceEvent(
        2,
        "finish_item",
        {"target_id": "public-id"},
        {"ok": True, "data": {"done": True}, "error": None},
        ProvenanceReport((ArgumentOrigin("/target_id", wrong_tool_occurrence, True),)),
    )
    with pytest.raises(TaskModelError, match="wrong tool"):
        WitnessRun(
            episode=_episode(materialization_id, "conversation-wrong-tool"),
            task_definition_id=definition.task_id,
            start_case_id=definition.start_case.case_id,
            reset_observation={},
            resolved_bindings=(_resolved(definition, materialization_id),),
            trace=(source_event, use_event),
            final_answer=None,
            checker_digest=definition.checker.checker_digest,
            before_facts_digest=DIGEST_C,
            after_facts_digest=DIGEST_D,
            checker_status="satisfied",
            checker_failures=(),
        )


def _foreach_definition() -> TaskDefinition:
    selector = SelectorSpec("all-items", "finish", (), None, "all")
    bindings = (
        LogicalBindingRef(
            "member-alpha",
            "finish",
            "item-alpha",
            "all-items",
            {"name": "alpha"},
        ),
        LogicalBindingRef(
            "member-beta",
            "finish",
            "item-beta",
            "all-items",
            {"name": "beta"},
        ),
    )
    selections = (LogicalSelection(selector, ("item-alpha", "item-beta")),)
    blueprint = TaskBlueprint(
        (selector,),
        ForEachGoal("all-items", "finish"),
        None,
    )
    checker = CheckerArtifact(
        digest_document({"start_case_id": "case-many", "blueprint": blueprint.to_document()}),
        blueprint.goal,
        bindings,
        selections,
        None,
        DIGEST_B,
    )
    return TaskDefinition(
        DIGEST_A,
        DIGEST_B,
        StartCase("case-many", {"seed": 2}, ("multiple",)),
        blueprint,
        bindings,
        selections,
        {},
        "Finish every selected item.",
        None,
        checker,
    )


def _foreach_witness(
    definition: TaskDefinition,
    materialization_id: str,
    conversation: str,
) -> WitnessRun:
    resolutions = tuple(
        ResolvedBinding(
            item.logical_ref_digest,
            materialization_id,
            {"native_id": position},
            {"name": item.instruction_values["name"]},
            DIGEST_E,
        )
        for position, item in enumerate(definition.logical_bindings, 1)
    )
    return WitnessRun(
        _episode(materialization_id, conversation),
        definition.task_id,
        definition.start_case.case_id,
        {},
        resolutions,
        (
            PublicTraceEvent(
                1,
                "finish_all",
                {},
                {"ok": True, "data": {"finished": 2}, "error": None},
                ProvenanceReport(()),
            ),
        ),
        None,
        definition.checker.checker_digest,
        DIGEST_C,
        DIGEST_D,
        "satisfied",
        (),
    )


def test_multimember_foreach_taskpack_accepts_exact_set_and_rejects_drift() -> None:
    definition = _foreach_definition()
    assert "composition_rule_id" not in {field.name for field in fields(LogicalSelection)}
    assert "foreach_selector_id" not in {field.name for field in fields(LogicalSelection)}
    selector = definition.blueprint.selectors[0]
    with pytest.raises(TaskModelError, match="ForEach.*selector"):
        TaskBlueprint((), ForEachGoal("missing", "finish"), None)
    with pytest.raises(TaskModelError, match="ForEach.*cardinality"):
        TaskBlueprint(
            (replace(selector, cardinality="exactly_one"),),
            ForEachGoal(selector.selector_id, "finish"),
            None,
        )
    with pytest.raises(TaskModelError, match="selection membership"):
        CheckerArtifact(
            definition.checker.task_preimage_digest,
            definition.blueprint.goal,
            definition.logical_bindings[:1],
            definition.logical_selections,
            None,
            DIGEST_B,
        )
    duplicate_binding = replace(
        definition.logical_bindings[0],
        slot="member-alpha-duplicate",
    )
    with pytest.raises(TaskModelError, match="selection membership"):
        CheckerArtifact(
            definition.checker.task_preimage_digest,
            definition.blueprint.goal,
            (*definition.logical_bindings, duplicate_binding),
            definition.logical_selections,
            None,
            DIGEST_B,
        )
    with pytest.raises(TaskModelError, match="stable member order"):
        CheckerArtifact(
            definition.checker.task_preimage_digest,
            definition.blueprint.goal,
            tuple(reversed(definition.logical_bindings)),
            definition.logical_selections,
            None,
            DIGEST_B,
        )
    plan = _plan(definition)
    first = _foreach_witness(definition, DIGEST_C, "foreach-1")
    second = _foreach_witness(definition, DIGEST_D, "foreach-2")
    ordering = _ordering(definition, plan)
    report = _report(definition, plan, first, second)
    assert TaskPack(definition, (first, second), plan, ordering, report).taskpack_id

    missing = replace(second, resolved_bindings=second.resolved_bindings[:1])
    with pytest.raises(TaskModelError, match="logical binding resolutions"):
        TaskPack(definition, (first, missing), plan, ordering, report)

    reordered = replace(
        second,
        resolved_bindings=tuple(reversed(second.resolved_bindings)),
    )
    reordered_report = _report(definition, plan, first, reordered)
    with pytest.raises(TaskModelError, match="stable resolution order"):
        TaskPack(definition, (first, reordered), plan, ordering, reordered_report)

    extra = replace(
        second,
        resolved_bindings=(
            *second.resolved_bindings,
            ResolvedBinding(DIGEST_F, DIGEST_D, {"native_id": 3}, {"name": "gamma"}, DIGEST_E),
        ),
    )
    with pytest.raises(TaskModelError, match="logical binding resolutions"):
        TaskPack(definition, (first, extra), plan, ordering, report)
