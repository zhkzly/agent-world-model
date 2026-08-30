from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

import agent_env_foundry.task_foundry as task_foundry_module
from agent_env_foundry.environment import ToolSpec
from agent_env_foundry.provenance import ArgumentProvenance
from agent_env_foundry.public_agent import PublicEpisodeRun
from agent_env_foundry.release import canonical_bytes
from agent_env_foundry.semantics import AtomCheckRequest, AtomCheckResult, StartCase, TraceEvent
from agent_env_foundry.task_foundry import (
    AgentChoicePerturbation,
    AgentChoiceProof,
    AtomAdmissionPlan,
    AtomChallengeReport,
    AtomChallengeResult,
    AtomCheckerMutationSpec,
    AtomPlannedChallenge,
    AtomTask,
    AtomWitness,
    SolvedAtomTask,
    TaskFoundryError,
    run_atom_checker_mutations,
    seal_atom_task_pack,
    solve_atom_task_twice,
)


def _task() -> AtomTask:
    answer_schema = {
        "type": "object",
        "properties": {},
        "required": [],
        "additionalProperties": False,
    }
    preimage = {
        "release_id": "a" * 64,
        "start_case_id": "default",
        "capability_id": "cap-1",
        "semantic_key": "item:1",
        "answer_schema": answer_schema,
    }
    instruction = "Complete the public task."
    return AtomTask(
        "a" * 64,
        StartCase("default", None, ("base",)),
        "cap-1",
        "item:1",
        {"item": "one"},
        hashlib.sha256(canonical_bytes(preimage)).hexdigest(),
        instruction,
        hashlib.sha256(instruction.encode()).hexdigest(),
        answer_schema,
    )


def _witness(task: AtomTask, materialization_id: str, *, satisfied: bool = True) -> AtomWitness:
    result = AtomCheckResult(
        initially_satisfied=False,
        satisfied=satisfied,
        required_effects_ok=satisfied,
        collateral_ok=True,
        answer_ok=None,
        process_ok=satisfied,
        report_values={},
        failure_codes=() if satisfied else ("FAILED",),
    )
    return AtomWitness(
        task.task_id,
        materialization_id,
        {},
        (),
        {},
        (),
        result,
        1,
        (None,),
    )


def _plan(task: AtomTask) -> AtomAdmissionPlan:
    no_op_result = _witness(task, "0" * 64, satisfied=False).result
    return AtomAdmissionPlan(
        task.task_id,
        "perturb_each_occurrence",
        no_op_result,
        (
            AtomCheckerMutationSpec("force_satisfied", "no_op", "satisfied"),
            AtomCheckerMutationSpec(
                "force_required_effects_ok",
                "no_op",
                "required_effects_ok",
            ),
            AtomCheckerMutationSpec(
                "force_process_ok",
                "missing_process",
                "process_ok",
            ),
        ),
        (
            AtomPlannedChallenge("no_op", True, None, None, None),
            AtomPlannedChallenge("wrong_target", True, "d" * 64, None, None),
            AtomPlannedChallenge(
                "wrong_answer",
                False,
                None,
                None,
                "answer schema has no schema-valid alternative value",
            ),
            AtomPlannedChallenge("missing_process", True, None, None, None),
            AtomPlannedChallenge(
                "collateral",
                False,
                None,
                None,
                "no disjoint-workflow state-change Task is available",
            ),
        ),
    )


def test_atom_task_and_witness_identities_bind_frozen_content() -> None:
    task = _task()
    assert task.task_id
    assert task.task_id != replace(task, instruction="Different instruction").task_id
    witness = _witness(task, "b" * 64)
    assert witness.witness_id
    plan = _plan(task)
    solved = SolvedAtomTask(task, plan, (witness, _witness(task, "c" * 64)))
    assert solved.to_document()["format"] == "solved-atom-task/1"
    assert solved.to_document()["admission_plan"]["plan_id"] == plan.plan_id


def test_product_witness_builder_attaches_argument_provenance() -> None:
    task = _task()
    tool: ToolSpec = {
        "name": "inspect",
        "description": "Inspect one item.",
        "input_schema": {
            "type": "object",
            "properties": {"item": {"type": "string"}},
            "required": ["item"],
            "additionalProperties": False,
        },
        "output_schema": {"type": "object"},
    }
    trace = (
        TraceEvent(
            1,
            "inspect",
            {"item": "one"},
            {"ok": True, "data": {"item": "one"}, "error": None},
        ),
    )
    episode = PublicEpisodeRun(trace, {}, 1, (None,))
    witness = task_foundry_module._witness(
        task,
        "b" * 64,
        {},
        (tool,),
        episode,
        _witness(task, "c" * 64).result,
    )
    assert len(witness.argument_provenance) == 1
    assert witness.argument_provenance[0].source_kind == "task_literal"


def test_solved_atom_requires_two_fresh_successful_witnesses() -> None:
    task = _task()
    first = _witness(task, "b" * 64)
    with pytest.raises(TaskFoundryError) as caught:
        SolvedAtomTask(task, _plan(task), (first, _witness(task, "b" * 64)))
    assert caught.value.code == "witness_materialization_reused"

    with pytest.raises(TaskFoundryError) as caught:
        SolvedAtomTask(task, _plan(task), (first, _witness(task, "c" * 64, satisfied=False)))
    assert caught.value.code == "witness_not_satisfied"


def test_atom_admission_plan_is_complete_and_bound_before_witnesses() -> None:
    task = _task()
    plan = _plan(task)
    assert plan.plan_id
    assert plan.agent_choice_policy == "perturb_each_occurrence"
    assert tuple(item.category for item in plan.challenges) == (
        "no_op",
        "wrong_target",
        "wrong_answer",
        "missing_process",
        "collateral",
    )
    assert plan.challenges[1].target_task_id == "d" * 64

    with pytest.raises(TaskFoundryError) as caught:
        AtomAdmissionPlan(
            task.task_id,
            "perturb_each_occurrence",
            plan.no_op_result,
            plan.checker_mutations,
            plan.challenges[:-1],
        )
    assert caught.value.code == "admission_plan_incomplete"

    with pytest.raises(TaskFoundryError) as caught:
        AtomPlannedChallenge("wrong_target", True, None, None, None)
    assert caught.value.code == "admission_plan_wrong_target_missing"

    with pytest.raises(TaskFoundryError) as caught:
        AtomAdmissionPlan(
            task.task_id,
            "ignore_choices",
            plan.no_op_result,
            plan.checker_mutations,
            plan.challenges,
        )
    assert caught.value.code == "admission_agent_choice_policy_invalid"

    assert tuple(item.mutation_id for item in plan.checker_mutations) == (
        "force_satisfied",
        "force_required_effects_ok",
        "force_process_ok",
    )


def test_replay_rebinds_dynamic_outputs_and_changes_only_the_targeted_choice() -> None:
    first = TraceEvent(
        1,
        "submit",
        {"charge_reference": "CHG-1", "reason": "original"},
        {"ok": True, "data": {"dispute_reference": "DSP-OLD"}, "error": None},
    )
    first_provenance = (
        ArgumentProvenance(
            1,
            "/charge_reference",
            "CHG-1",
            "task_literal",
            None,
            None,
            "/public_descriptor/charge_reference",
        ),
        ArgumentProvenance(1, "/reason", "original", "agent_choice", None, None, None),
    )
    first_arguments = task_foundry_module._replay_arguments(
        first,
        first_provenance,
        {},
        {},
        (1, "/reason"),
        "alternative",
    )
    assert first_arguments == {"charge_reference": "CHG-1", "reason": "alternative"}

    second = TraceEvent(
        2,
        "inspect",
        {"dispute_reference": "DSP-OLD"},
        {"ok": True, "data": {}, "error": None},
    )
    second_provenance = (
        ArgumentProvenance(
            2,
            "/dispute_reference",
            "DSP-OLD",
            "tool_observation",
            1,
            "submit",
            "/data/dispute_reference",
        ),
    )
    second_arguments = task_foundry_module._replay_arguments(
        second,
        second_provenance,
        {},
        {1: {"ok": True, "data": {"dispute_reference": "DSP-NEW"}, "error": None}},
        (1, "/reason"),
        "alternative",
    )
    assert second_arguments == {"dispute_reference": "DSP-NEW"}


def test_agent_choice_perturbation_requires_the_checker_to_stay_satisfied() -> None:
    task = _task()
    failed = _witness(task, "b" * 64, satisfied=False).result
    with pytest.raises(TaskFoundryError) as caught:
        AgentChoicePerturbation(
            "c" * 64,
            "d" * 64,
            1,
            "/reason",
            "original",
            "alternative",
            (),
            failed,
        )
    assert caught.value.code == "agent_choice_is_load_bearing"


def test_agent_choice_rebinds_dynamic_final_answer_from_checker_report() -> None:
    result = AtomCheckResult(
        initially_satisfied=False,
        satisfied=False,
        required_effects_ok=True,
        collateral_ok=True,
        answer_ok=False,
        process_ok=True,
        report_values={"commit_reference": "new-commit"},
        failure_codes=("ANSWER_MISMATCH",),
    )
    schema = {
        "type": "object",
        "properties": {"commit_reference": {"type": "string"}},
        "required": ["commit_reference"],
        "additionalProperties": False,
    }
    assert task_foundry_module._rebound_final_answer(result, schema) == {
        "commit_reference": "new-commit"
    }


def test_instruction_preserves_temporal_answer_qualifiers() -> None:
    instruction = task_foundry_module._instruction(
        "Complete the task.",
        {"target": "one"},
        (SimpleNamespace(field_id="status", public_label="Status after reopening"),),
    )
    assert "observation before that event cannot fill an after-event field" in instruction


def test_atom_task_pack_seals_only_one_complete_same_plan_admission() -> None:
    task = _task()
    plan = _plan(task)

    def trace(*names: str) -> tuple[TraceEvent, ...]:
        return tuple(
            TraceEvent(index, name, {}, {"ok": True, "data": {}, "error": None})
            for index, name in enumerate(names, start=1)
        )

    first = replace(_witness(task, "1" * 64), trace=trace("inspect", "submit", "result"))
    second = replace(_witness(task, "2" * 64), trace=trace("inspect", "submit", "result"))
    solved = SolvedAtomTask(task, plan, (first, second))
    rejected = _witness(task, "3" * 64, satisfied=False).result
    control = _witness(task, "4" * 64).result
    no_op = AtomChallengeResult("no_op", True, "3" * 64, (), {}, rejected, None, None)
    wrong_target = AtomChallengeResult(
        "wrong_target",
        True,
        "4" * 64,
        (),
        {},
        rejected,
        control,
        None,
    )
    wrong_answer = AtomChallengeResult(
        "wrong_answer",
        False,
        None,
        (),
        {},
        None,
        None,
        "answer schema has no schema-valid alternative value",
    )
    missing_process = AtomChallengeResult(
        "missing_process",
        True,
        "5" * 64,
        (),
        {},
        rejected,
        None,
        None,
    )
    collateral = AtomChallengeResult(
        "collateral",
        False,
        None,
        (),
        {},
        None,
        None,
        "no disjoint-workflow state-change Task is available",
    )
    challenges = AtomChallengeReport(
        task.task_id,
        plan,
        (no_op, wrong_target, wrong_answer, missing_process, collateral),
    )
    mutations = run_atom_checker_mutations(plan, challenges)
    choices = AgentChoiceProof(task.task_id, plan.plan_id, ())

    task_pack = seal_atom_task_pack(solved, challenges, choices, mutations)
    assert task_pack.task_pack_id
    assert task_pack.to_document()["format"] == "atom-task-pack/2"

    with pytest.raises(TaskFoundryError) as caught:
        seal_atom_task_pack(
            solved,
            challenges,
            replace(choices, admission_plan_id="8" * 64),
            mutations,
        )
    assert caught.value.code == "atom_admission_identity_mismatch"

    choice_trace = (
        TraceEvent(
            1,
            "submit",
            {"reason": "original"},
            {"ok": True, "data": {}, "error": None},
        ),
    )
    choice_witness = replace(
        first,
        trace=choice_trace,
        argument_provenance=(
            ArgumentProvenance(1, "/reason", "original", "agent_choice", None, None, None),
        ),
    )
    choice_solved = SolvedAtomTask(task, plan, (choice_witness, second))
    with pytest.raises(TaskFoundryError) as caught:
        seal_atom_task_pack(choice_solved, challenges, choices, mutations)
    assert caught.value.code == "atom_admission_agent_choice_incomplete"


def test_solve_freezes_admission_plan_before_opening_a_witness(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    task = _task()
    events: list[str] = []

    class StopAfterPlan(RuntimeError):
        pass

    class Prepared:
        identity = SimpleNamespace(release_id=task.release_id)

        def open(self, _path: object) -> object:
            events.append("witness")
            raise AssertionError("witness opened before admission plan froze")

    def stop_after_plan(*_args: object) -> AtomAdmissionPlan:
        events.append("plan")
        raise StopAfterPlan

    monkeypatch.setattr(task_foundry_module, "_derive_atom_admission_plan", stop_after_plan)
    with pytest.raises(StopAfterPlan):
        solve_atom_task_twice(Prepared(), task, (task,), tmp_path)  # type: ignore[arg-type]
    assert events == ["plan"]


def test_wrong_target_selection_prefers_same_capability_then_shared_workflow() -> None:
    current = _task()
    same_target_profile = replace(
        current,
        answer_schema={
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
            "additionalProperties": False,
        },
    )
    same_capability = replace(
        current,
        semantic_key="item:2",
        public_descriptor={"item": "two"},
    )
    shared_workflow = replace(
        current,
        capability_id="cap-2",
        semantic_key="item:3",
        public_descriptor={"item": "three"},
    )
    unrelated = replace(
        current,
        capability_id="cap-3",
        semantic_key="item:4",
        public_descriptor={"item": "four"},
    )
    capabilities = {
        "cap-1": SimpleNamespace(workflow_ids=("workflow-1",), task_kind="state_change"),
        "cap-2": SimpleNamespace(workflow_ids=("workflow-1",), task_kind="state_change"),
        "cap-3": SimpleNamespace(workflow_ids=("workflow-2",), task_kind="query"),
    }

    selected = task_foundry_module._select_wrong_target_task(
        current,
        (current, same_target_profile, unrelated, shared_workflow, same_capability),
        capabilities,  # type: ignore[arg-type]
    )
    assert selected == same_capability
    selected = task_foundry_module._select_wrong_target_task(
        current,
        (current, unrelated, shared_workflow),
        capabilities,  # type: ignore[arg-type]
    )
    assert selected == shared_workflow


def test_wrong_target_selection_prefers_closest_public_descriptor() -> None:
    current = replace(
        _task(),
        public_descriptor={"operation": "update", "path": "one", "content": "value"},
    )
    distant = replace(
        current,
        semantic_key="create:one",
        public_descriptor={"operation": "create", "path": "one", "content": None},
    )
    close = replace(
        current,
        semantic_key="update:two",
        public_descriptor={"operation": "update", "path": "two", "content": "value"},
    )
    capabilities = {
        current.capability_id: SimpleNamespace(
            workflow_ids=("workflow-1",),
            task_kind="process",
        )
    }
    selected = task_foundry_module._select_wrong_target_task(
        current,
        (current, distant, close),
        capabilities,  # type: ignore[arg-type]
    )
    assert selected == close


def test_collateral_selection_requires_a_disjoint_state_change_workflow() -> None:
    current = _task()
    shared_state_change = replace(
        current,
        capability_id="cap-2",
        semantic_key="item:2",
        public_descriptor={"item": "two"},
    )
    disjoint_query = replace(
        current,
        capability_id="cap-3",
        semantic_key="item:3",
        public_descriptor={"item": "three"},
    )
    disjoint_state_change = replace(
        current,
        capability_id="cap-4",
        semantic_key="item:4",
        public_descriptor={"item": "four"},
    )
    capabilities = {
        "cap-1": SimpleNamespace(workflow_ids=("workflow-1",), task_kind="query"),
        "cap-2": SimpleNamespace(workflow_ids=("workflow-1",), task_kind="state_change"),
        "cap-3": SimpleNamespace(workflow_ids=("workflow-2",), task_kind="query"),
        "cap-4": SimpleNamespace(workflow_ids=("workflow-2",), task_kind="state_change"),
    }
    selected = task_foundry_module._select_collateral_task(
        current,
        (current, shared_state_change, disjoint_query, disjoint_state_change),
        capabilities,  # type: ignore[arg-type]
    )
    assert selected == disjoint_state_change

    with pytest.raises(TaskFoundryError) as caught:
        task_foundry_module._assert_collateral_discriminated(
            _witness(current, "b" * 64, satisfied=False).result
        )
    assert caught.value.code == "collateral_not_discriminated"
    task_foundry_module._assert_collateral_discriminated(
        replace(
            _witness(current, "b" * 64, satisfied=False).result,
            collateral_ok=False,
        )
    )


def test_atom_challenge_report_requires_rejected_noop() -> None:
    task = _task()
    plan = _plan(task)
    rejected = plan.no_op_result
    no_op = AtomChallengeResult(
        "no_op",
        True,
        "b" * 64,
        (),
        {},
        rejected,
        None,
        None,
    )
    with pytest.raises(TaskFoundryError) as caught:
        replace(no_op, category="wrong_target")
    assert caught.value.code == "challenge_control_result_missing"
    wrong_target = replace(
        no_op,
        category="wrong_target",
        control_result=_witness(task, "c" * 64).result,
    )
    not_applicable = AtomChallengeResult(
        "wrong_answer",
        False,
        None,
        (),
        {},
        None,
        None,
        "answer schema has no schema-valid alternative value",
    )
    missing_process = replace(no_op, category="missing_process")
    collateral = AtomChallengeResult(
        "collateral",
        False,
        None,
        (),
        {},
        None,
        None,
        "no disjoint-workflow state-change Task is available",
    )
    report = AtomChallengeReport(
        task.task_id,
        plan,
        (no_op, wrong_target, not_applicable, missing_process, collateral),
    )
    assert report.to_document()["format"] == "atom-challenge-report/1"
    assert plan.to_document()["format"] == "atom-admission-plan/3"
    mutation_report = run_atom_checker_mutations(plan, report)
    assert all(item.killed for item in mutation_report.mutations)

    with pytest.raises(TaskFoundryError) as caught:
        AtomChallengeReport(
            task.task_id,
            plan,
            (
                replace(no_op, result=replace(no_op.result, collateral_ok=False)),
                wrong_target,
                not_applicable,
                missing_process,
                collateral,
            ),
        )
    assert caught.value.code == "challenge_noop_result_drift"

    surviving_process = replace(
        missing_process,
        result=replace(missing_process.result, process_ok=True),
    )
    surviving_report = AtomChallengeReport(
        task.task_id,
        plan,
        (no_op, wrong_target, not_applicable, surviving_process, collateral),
    )
    with pytest.raises(TaskFoundryError) as caught:
        run_atom_checker_mutations(plan, surviving_report)
    assert caught.value.code == "checker_mutant_survived"

    with pytest.raises(TaskFoundryError) as caught:
        AtomChallengeReport(
            task.task_id,
            plan,
            (no_op, wrong_target, not_applicable, missing_process),
        )
    assert caught.value.code == "challenge_plan_incomplete"

    accepted = replace(no_op, result=_witness(task, "c" * 64).result)
    with pytest.raises(TaskFoundryError) as caught:
        AtomChallengeReport(
            task.task_id,
            plan,
            (accepted, wrong_target, not_applicable, missing_process, collateral),
        )
    assert caught.value.code == "challenge_false_acceptance"
    accepted_wrong_target = replace(wrong_target, result=_witness(task, "c" * 64).result)
    with pytest.raises(TaskFoundryError) as caught:
        AtomChallengeReport(
            task.task_id,
            plan,
            (no_op, accepted_wrong_target, not_applicable, missing_process, collateral),
        )
    assert caught.value.code == "challenge_false_acceptance"

    applicable_collateral_challenges = (
        *plan.challenges[:-1],
        AtomPlannedChallenge("collateral", True, "e" * 64, None, None),
    )
    applicable_collateral_plan = replace(
        plan,
        checker_mutations=task_foundry_module._derive_checker_mutation_specs(
            applicable_collateral_challenges,
            plan.no_op_result,
        ),
        challenges=applicable_collateral_challenges,
    )
    accepted_collateral = replace(
        wrong_target,
        category="collateral",
        result=_witness(task, "c" * 64).result,
    )
    with pytest.raises(TaskFoundryError) as caught:
        AtomChallengeReport(
            task.task_id,
            applicable_collateral_plan,
            (no_op, wrong_target, not_applicable, missing_process, accepted_collateral),
        )
    assert caught.value.code == "challenge_false_acceptance"


def test_checker_mutation_plan_uses_the_actual_pre_witness_noop_axes() -> None:
    challenges = (
        AtomPlannedChallenge("no_op", True, None, None, None),
        AtomPlannedChallenge("wrong_target", False, None, None, "no sibling Task"),
        AtomPlannedChallenge("wrong_answer", False, None, None, "no alternate answer"),
        AtomPlannedChallenge("missing_process", True, None, None, None),
        AtomPlannedChallenge("collateral", False, None, None, "no collateral Task"),
    )
    query_noop = AtomCheckResult(
        initially_satisfied=False,
        satisfied=False,
        required_effects_ok=True,
        collateral_ok=True,
        answer_ok=False,
        process_ok=False,
        report_values={"value": "public"},
        failure_codes=("PUBLIC_READ_MISSING", "ANSWER_MISMATCH"),
    )
    query_specs = task_foundry_module._derive_checker_mutation_specs(
        challenges,
        query_noop,
    )
    assert tuple(item.mutation_id for item in query_specs) == (
        "force_satisfied",
        "force_process_ok",
    )

    state_change_noop = replace(
        query_noop,
        required_effects_ok=False,
        answer_ok=None,
        report_values={},
        failure_codes=("REQUIRED_EFFECT_MISSING", "PUBLIC_PROCESS_MISSING"),
    )
    state_change_specs = task_foundry_module._derive_checker_mutation_specs(
        challenges,
        state_change_noop,
    )
    assert tuple(item.mutation_id for item in state_change_specs) == (
        "force_satisfied",
        "force_required_effects_ok",
        "force_process_ok",
    )


def test_admit_atom_task_runs_one_complete_existing_pipeline(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    task = _task()
    prepared = object()
    route = object()
    events: list[tuple[str, object]] = []
    plan = SimpleNamespace(plan_id="plan")
    solved = SimpleNamespace(admission_plan=plan)
    challenges = object()
    choices = object()
    mutations = object()
    task_pack = object()

    monkeypatch.setattr(
        task_foundry_module,
        "solve_atom_task_twice",
        lambda *_args, **kwargs: events.append(("solve", kwargs)) or solved,
    )
    monkeypatch.setattr(
        task_foundry_module,
        "challenge_atom_task",
        lambda *_args, **kwargs: events.append(("challenge", kwargs)) or challenges,
    )
    monkeypatch.setattr(
        task_foundry_module,
        "prove_agent_choices_non_load_bearing",
        lambda *_args: events.append(("choices", _args[-1])) or choices,
    )
    monkeypatch.setattr(
        task_foundry_module,
        "run_atom_checker_mutations",
        lambda actual_plan, actual_challenges: (
            events.append(("mutations", (actual_plan, actual_challenges))) or mutations
        ),
    )
    monkeypatch.setattr(
        task_foundry_module,
        "seal_atom_task_pack",
        lambda *args: events.append(("seal", args)) or task_pack,
    )

    result = task_foundry_module.admit_atom_task(
        prepared,  # type: ignore[arg-type]
        task,
        (task,),
        tmp_path,
        route=route,  # type: ignore[arg-type]
        max_provider_turns=5,
    )

    assert result is task_pack
    assert [item[0] for item in events] == [
        "solve",
        "challenge",
        "choices",
        "mutations",
        "seal",
    ]
    assert events[0][1] == {"route": route, "max_provider_turns": 5}
    assert events[1][1] == {"route": route, "max_provider_turns": 5}
    assert events[2][1] == tmp_path / "agent-choices"
    assert events[3][1] == (plan, challenges)
    assert events[4][1] == (solved, challenges, choices, mutations)


def test_report_profiles_are_bounded_to_full_plus_each_single_field() -> None:
    fields = (
        SimpleNamespace(field_id="first"),
        SimpleNamespace(field_id="second"),
        SimpleNamespace(field_id="third"),
    )

    profiles = task_foundry_module._answer_field_profiles(fields)

    assert tuple(tuple(item.field_id for item in profile) for profile in profiles) == (
        ("first", "second", "third"),
        ("first",),
        ("second",),
        ("third",),
    )
    assert task_foundry_module._answer_field_profiles((fields[0],)) == ((fields[0],),)
    assert task_foundry_module._answer_field_profiles(()) == ((),)


def test_report_projection_reuses_release_truth_and_only_scores_selected_fields() -> None:
    expected = {"first": "expected", "second": "other"}

    class Trusted:
        def __init__(self) -> None:
            self.answers: list[object] = []

        def evaluate_atom(self, request: AtomCheckRequest) -> AtomCheckResult:
            self.answers.append(request.final_answer)
            answer_ok = request.final_answer == expected
            return AtomCheckResult(
                initially_satisfied=False,
                satisfied=answer_ok,
                required_effects_ok=True,
                collateral_ok=True,
                answer_ok=answer_ok,
                process_ok=True,
                report_values=expected,
                failure_codes=() if answer_ok else ("ANSWER_MISMATCH",),
            )

    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {"first": {"type": "string"}},
        "required": ["first"],
    }
    context = task_foundry_module._context("cap-1", "item:1", {"item": "one"})
    trusted = Trusted()
    session = SimpleNamespace(trusted=trusted)
    correct_request = AtomCheckRequest(
        "cap-1",
        {},
        {},
        {"item": "one"},
        (),
        {"first": "expected"},
        context,
    )

    correct = task_foundry_module._evaluate_report_atom(  # type: ignore[arg-type]
        session,
        correct_request,
        schema,
    )
    wrong = task_foundry_module._evaluate_report_atom(  # type: ignore[arg-type]
        session,
        AtomCheckRequest(
            "cap-1",
            {},
            {},
            {"item": "one"},
            (),
            {"first": "wrong"},
            context,
        ),
        schema,
    )

    assert correct.satisfied is True
    assert wrong.satisfied is False and wrong.answer_ok is False
    assert trusted.answers == [
        {"first": "expected"},
        expected,
        {"first": "wrong"},
        {"first": "wrong", "second": "other"},
    ]


def test_nullable_union_has_a_schema_valid_non_null_wrong_answer() -> None:
    assert (
        task_foundry_module._alternative_value(
            {"type": ["string", "null"]},
            None,
        )
        == "wrong"
    )
    assert (
        task_foundry_module._alternative_value(
            {"type": ["boolean", "null"]},
            None,
        )
        is False
    )


def test_atom_instruction_does_not_duplicate_structured_output_schema() -> None:
    instruction = task_foundry_module._instruction(
        "Complete the requested outcome.",
        {"item": "one"},
        (),
    )
    assert "Return a JSON object with these fields" not in instruction
