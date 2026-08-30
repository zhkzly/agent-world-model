from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

import agent_env_foundry.foreach_foundry as foreach_module
from agent_env_foundry.foreach_foundry import (
    ForEachAdmissionPlan,
    ForEachAgentChoicePerturbation,
    ForEachAgentChoiceProof,
    ForEachAlternativeOrderProof,
    ForEachCheckerMutationResult,
    ForEachCollateralChallenge,
    ForEachNoOpChallenge,
    ForEachPartialChallenge,
    ForEachPartialChallengeReport,
    ForEachTask,
    ForEachWitness,
    ForEachWrongAnswerChallenge,
    SolvedForEachTask,
    run_foreach_checker_mutations,
    seal_foreach_task_pack,
)
from agent_env_foundry.provenance import ArgumentProvenance
from agent_env_foundry.release import canonical_bytes
from agent_env_foundry.semantics import (
    AtomCheckResult,
    BindingCandidate,
    PublicFieldSource,
    PublicValueSource,
    StartCase,
    TraceEvent,
)
from agent_env_foundry.task_foundry import TaskFoundryError


def _result(*, satisfied: bool = True) -> AtomCheckResult:
    return AtomCheckResult(
        initially_satisfied=False,
        satisfied=satisfied,
        required_effects_ok=satisfied,
        collateral_ok=True,
        answer_ok=None,
        process_ok=satisfied,
        report_values={},
        failure_codes=() if satisfied else ("FAILED",),
    )


def _task() -> ForEachTask:
    member_schema = {
        "type": "object",
        "properties": {},
        "required": [],
        "additionalProperties": False,
    }
    answer_schema = {
        "type": "object",
        "properties": {
            "results": {
                "type": "array",
                "items": member_schema,
                "minItems": 2,
                "maxItems": 2,
            }
        },
        "required": ["results"],
        "additionalProperties": False,
    }
    instruction = "Complete the task for every selected target."
    preimage = {
        "release_id": "a" * 64,
        "start_case_id": "default",
        "capability_id": "cap-1",
        "semantic_keys": ["item:1", "item:2"],
        "selector_id": "b" * 64,
        "member_answer_schema": member_schema,
    }
    return ForEachTask(
        "a" * 64,
        StartCase("default", None, ("base",)),
        "cap-1",
        ("item:1", "item:2"),
        ({"item": "one"}, {"item": "two"}),
        "b" * 64,
        hashlib.sha256(canonical_bytes(preimage)).hexdigest(),
        instruction,
        hashlib.sha256(instruction.encode()).hexdigest(),
        member_schema,
        answer_schema,
    )


def _witness(task: ForEachTask, materialization_id: str) -> ForEachWitness:
    return ForEachWitness(
        task.task_id,
        materialization_id,
        {},
        (),
        {"results": [{}, {}]},
        (),
        (_result(), _result()),
        1,
        (None,),
    )


def _plan(task: ForEachTask) -> ForEachAdmissionPlan:
    return ForEachAdmissionPlan(task.task_id, (0, 1), None, "e" * 64)


def _binding(key: str, item: str) -> BindingCandidate:
    return BindingCandidate(
        key,
        True,
        (),
        {"item": item},
        {"item": item},
        {},
        (
            PublicFieldSource(
                "/public_descriptor/item",
                PublicValueSource("task_literal", None, None, item),
            ),
        ),
    )


def test_foreach_task_binds_complete_ordered_selection_and_two_fresh_witnesses() -> None:
    task = _task()
    assert task.task_id
    assert task.to_document()["semantic_keys"] == ["item:1", "item:2"]
    plan = _plan(task)
    assert plan.to_document()["agent_choice_policy"] == "perturb_each_occurrence"
    assert plan.to_document()["collateral_task_id"] == "e" * 64
    assert plan.to_document()["format"] == "foreach-admission-plan/3"
    assert plan.to_document()["alternative_order_policy"] == (
        "deterministic_dependency_safe_reverse_replay"
    )
    assert [item["mutation_id"] for item in plan.to_document()["checker_mutations"]] == [
        "ignore_member_0",
        "ignore_member_1",
    ]
    answer_plan = ForEachAdmissionPlan(task.task_id, (0, 1), 0, "e" * 64)
    assert answer_plan.to_document()["format"] == "foreach-admission-plan/3"
    assert answer_plan.to_document()["wrong_answer_member_index"] == 0
    with pytest.raises(TaskFoundryError, match="wrong-answer member"):
        ForEachAdmissionPlan(task.task_id, (0, 1), 2, "e" * 64)
    solved = SolvedForEachTask(
        task,
        plan,
        (_witness(task, "c" * 64), _witness(task, "d" * 64)),
    )
    assert solved.to_document()["format"] == "solved-foreach-task/1"
    assert solved.to_document()["admission_plan"]["plan_id"] == plan.plan_id

    with pytest.raises(TaskFoundryError, match="ordered"):
        replace(task, semantic_keys=("item:2", "item:1"))
    with pytest.raises(TaskFoundryError, match="instruction"):
        foreach_module._verify_task_preimage(replace(task, instruction="tampered"))
    with pytest.raises(TaskFoundryError, match="every member"):
        SolvedForEachTask(
            task,
            ForEachAdmissionPlan(task.task_id, (0,), None, "e" * 64),
            (_witness(task, "c" * 64), _witness(task, "d" * 64)),
        )
    with pytest.raises(TaskFoundryError, match="fresh"):
        SolvedForEachTask(
            task,
            plan,
            (_witness(task, "c" * 64), _witness(task, "c" * 64)),
        )
    failed = replace(
        _witness(task, "d" * 64),
        member_results=(_result(), _result(satisfied=False)),
    )
    with pytest.raises(TaskFoundryError, match="Every selected"):
        SolvedForEachTask(task, plan, (_witness(task, "c" * 64), failed))


def test_partial_challenge_requires_only_the_omitted_member_to_fail() -> None:
    task = _task()
    result = ForEachPartialChallenge(
        task.task_id,
        _plan(task).plan_id,
        1,
        task.semantic_keys[1],
        "e" * 64,
        (),
        {"results": [{}]},
        (),
        (_result(), _result(satisfied=False)),
    )
    assert result.to_document()["omitted_semantic_key"] == "item:2"
    first = replace(
        result,
        omitted_member_index=0,
        omitted_semantic_key="item:1",
        materialization_id="f" * 64,
        member_results=(_result(satisfied=False), _result()),
    )
    report = ForEachPartialChallengeReport(task.task_id, _plan(task), (first, result))
    assert report.report_id
    solved = SolvedForEachTask(
        task,
        _plan(task),
        (_witness(task, "1" * 64), _witness(task, "2" * 64)),
    )
    mutations = run_foreach_checker_mutations(solved, report)
    assert all(item.killed for item in mutations.mutations)

    with pytest.raises(TaskFoundryError, match="omitted"):
        replace(result, member_results=(_result(), _result()))
    with pytest.raises(TaskFoundryError, match="every frozen omission"):
        replace(report, partials=(result,))


def test_foreach_plan_freezes_before_any_witness_opens(
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
            raise AssertionError("witness opened before ForEach plan froze")

    def stop_after_plan(*_args: object) -> ForEachAdmissionPlan:
        events.append("plan")
        raise StopAfterPlan

    monkeypatch.setattr(foreach_module, "_derive_admission_plan", stop_after_plan)
    with pytest.raises(StopAfterPlan):
        foreach_module.solve_foreach_task_twice(  # type: ignore[arg-type]
            Prepared(), task, (), tmp_path
        )
    assert events == ["plan"]


def test_foreach_agent_choice_perturbation_requires_every_member_to_stay_satisfied() -> None:
    with pytest.raises(TaskFoundryError, match="AgentChoice"):
        ForEachAgentChoicePerturbation(
            "a" * 64,
            "b" * 64,
            1,
            "/reason",
            "original",
            "alternative",
            (),
            (_result(), _result(satisfied=False)),
        )


def test_foreach_noop_and_alternative_order_are_discriminating() -> None:
    task = _task()
    plan = _plan(task)
    with pytest.raises(TaskFoundryError, match="no-op"):
        ForEachNoOpChallenge(
            task.task_id,
            plan.plan_id,
            "a" * 64,
            (_result(), _result(satisfied=False)),
        )

    proof = ForEachAlternativeOrderProof(
        task.task_id,
        plan.plan_id,
        "b" * 64,
        "c" * 64,
        "d" * 64,
        (1, 0),
        (),
        {"results": [{}, {}]},
        (),
        (_result(), _result()),
    )
    assert proof.proof_id
    with pytest.raises(TaskFoundryError, match="reverse"):
        replace(proof, member_action_order=(0, 1))

    with pytest.raises(TaskFoundryError, match="mutant"):
        ForEachCheckerMutationResult("ignore_member_0", 0, False, False, False)


def test_reverse_replay_order_preserves_dependencies_and_reverses_members() -> None:
    task = replace(
        _task(),
        public_descriptors=(
            {"item": "one", "shared": "same"},
            {"item": "two", "shared": "same"},
        ),
    )
    witness = replace(
        _witness(task, "a" * 64),
        trace=(
            TraceEvent(1, "discover", {}, {"ok": True}),
            TraceEvent(2, "act", {"item": "one", "shared": "same"}, {"ok": True}),
            TraceEvent(3, "act", {"item": "two", "shared": "same"}, {"id": "two-id"}),
            TraceEvent(4, "confirm", {"item": "two", "id": "two-id"}, {"ok": True}),
        ),
        argument_provenance=(
            ArgumentProvenance(
                2,
                "/item",
                "one",
                "task_literal",
                None,
                None,
                "/public_descriptor/selected_targets/0/item",
            ),
            ArgumentProvenance(
                3,
                "/item",
                "two",
                "task_literal",
                None,
                None,
                "/public_descriptor/selected_targets/1/item",
            ),
            ArgumentProvenance(
                2,
                "/shared",
                "same",
                "task_literal",
                None,
                None,
                "/public_descriptor/selected_targets/1/shared",
            ),
            ArgumentProvenance(
                3,
                "/shared",
                "same",
                "task_literal",
                None,
                None,
                "/public_descriptor/selected_targets/0/shared",
            ),
            ArgumentProvenance(
                4,
                "/item",
                "two",
                "task_literal",
                None,
                None,
                "/public_descriptor/selected_targets/1/item",
            ),
            ArgumentProvenance(
                4,
                "/id",
                "two-id",
                "tool_observation",
                3,
                "act",
                "/id",
            ),
        ),
    )

    ordered = foreach_module._reverse_replay_order(witness, task.public_descriptors)

    assert [item.seq for item in ordered] == [1, 3, 4, 2]


def test_foreach_wrong_answer_fails_only_the_planned_member() -> None:
    task = _task()
    plan = _plan(task)
    wrong = replace(
        _result(satisfied=False),
        required_effects_ok=True,
        collateral_ok=True,
        answer_ok=False,
        process_ok=True,
    )
    challenge = ForEachWrongAnswerChallenge(
        task.task_id,
        plan.plan_id,
        0,
        "a" * 64,
        (),
        {"results": [{}, {}]},
        {"results": [{"wrong": True}, {}]},
        (_result(), _result()),
        (wrong, _result()),
    )
    assert challenge.member_index == 0
    with pytest.raises(TaskFoundryError, match="planned member"):
        replace(challenge, member_results=(_result(), wrong))


def test_foreach_collateral_requires_successful_control_and_isolated_axis() -> None:
    task = _task()
    plan = _plan(task)
    collateral = replace(
        _result(satisfied=False),
        required_effects_ok=True,
        collateral_ok=False,
        process_ok=True,
    )
    challenge = ForEachCollateralChallenge(
        task.task_id,
        plan.plan_id,
        plan.collateral_task_id,
        "a" * 64,
        (),
        (),
        {"results": [{}, {}]},
        (_result(), _result()),
        _result(),
        (collateral, collateral),
    )
    assert challenge.to_document()["control_result"]["satisfied"] is True

    with pytest.raises(TaskFoundryError, match="successful baseline and control"):
        replace(challenge, control_result=_result(satisfied=False))
    non_collateral = replace(collateral, collateral_ok=True)
    with pytest.raises(TaskFoundryError, match="isolate"):
        replace(challenge, collateral_member_results=(non_collateral, collateral))


def test_foreach_task_pack_requires_one_complete_same_plan_admission() -> None:
    task = _task()
    plan = _plan(task)
    witnesses = (_witness(task, "1" * 64), _witness(task, "2" * 64))
    solved = SolvedForEachTask(task, plan, witnesses)
    failed = _result(satisfied=False)
    first = ForEachPartialChallenge(
        task.task_id,
        plan.plan_id,
        0,
        task.semantic_keys[0],
        "3" * 64,
        (),
        {"results": [{}]},
        (),
        (failed, _result()),
    )
    second = replace(
        first,
        omitted_member_index=1,
        omitted_semantic_key=task.semantic_keys[1],
        materialization_id="4" * 64,
        member_results=(_result(), failed),
    )
    partials = ForEachPartialChallengeReport(task.task_id, plan, (first, second))
    mutations = run_foreach_checker_mutations(solved, partials)
    noop = ForEachNoOpChallenge(task.task_id, plan.plan_id, "5" * 64, (failed, failed))
    alternative = ForEachAlternativeOrderProof(
        task.task_id,
        plan.plan_id,
        witnesses[0].witness_id,
        "6" * 64,
        "7" * 64,
        (1, 0),
        (),
        {"results": [{}, {}]},
        (),
        (_result(), _result()),
    )
    collateral_result = replace(
        failed,
        required_effects_ok=True,
        collateral_ok=False,
        process_ok=True,
    )
    collateral = ForEachCollateralChallenge(
        task.task_id,
        plan.plan_id,
        plan.collateral_task_id,
        "8" * 64,
        (),
        (),
        {"results": [{}, {}]},
        (_result(), _result()),
        _result(),
        (collateral_result, collateral_result),
    )
    pack = seal_foreach_task_pack(
        solved,
        noop,
        None,
        partials,
        ForEachAgentChoiceProof(task.task_id, plan.plan_id, ()),
        alternative,
        collateral,
        mutations,
    )
    assert pack.task_pack_id
    assert pack.to_document()["format"] == "foreach-task-pack/1"

    with pytest.raises(TaskFoundryError, match="reused a materialization"):
        seal_foreach_task_pack(
            solved,
            noop,
            None,
            partials,
            ForEachAgentChoiceProof(task.task_id, plan.plan_id, ()),
            replace(alternative, materialization_id=witnesses[0].materialization_id),
            collateral,
            mutations,
        )

    with pytest.raises(TaskFoundryError, match="does not share one Task and plan"):
        seal_foreach_task_pack(
            solved,
            noop,
            None,
            partials,
            ForEachAgentChoiceProof(task.task_id, "9" * 64, ()),
            alternative,
            collateral,
            mutations,
        )

    choice_witness = replace(
        witnesses[0],
        trace=(
            TraceEvent(
                1,
                "submit",
                {"reason": "original"},
                {"ok": True, "data": {}, "error": None},
            ),
        ),
        argument_provenance=(
            ArgumentProvenance(1, "/reason", "original", "agent_choice", None, None, None),
        ),
    )
    choice_solved = SolvedForEachTask(task, plan, (choice_witness, witnesses[1]))
    with pytest.raises(TaskFoundryError, match="does not perturb every AgentChoice"):
        seal_foreach_task_pack(
            choice_solved,
            noop,
            None,
            partials,
            ForEachAgentChoiceProof(task.task_id, plan.plan_id, ()),
            alternative,
            collateral,
            mutations,
        )


def test_foreach_fresh_selection_must_match_the_complete_frozen_set() -> None:
    task = _task()

    class Trusted:
        bindings = (_binding("item:1", "one"), _binding("item:2", "two"))

        def enumerate_bindings(
            self, _capability: str, _facts: object
        ) -> tuple[BindingCandidate, ...]:
            return self.bindings

    trusted = Trusted()
    session = SimpleNamespace(trusted=trusted)
    assert foreach_module._resolve_complete_selection(session, task, {}) == trusted.bindings

    trusted.bindings = (*trusted.bindings, _binding("item:3", "three"))
    with pytest.raises(TaskFoundryError, match="missing, extra, or reordered"):
        foreach_module._resolve_complete_selection(session, task, {})


def test_foreach_collateral_target_is_out_of_selection_state_change() -> None:
    task = _task()

    def candidate(capability: str, key: str, identity: str) -> SimpleNamespace:
        return SimpleNamespace(
            capability_id=capability,
            semantic_key=key,
            task_id=identity * 64,
            start_case=task.start_case,
        )

    same_capability = candidate(task.capability_id, "item:3", "1")
    selected_key = candidate("cap-2", "item:1", "2")
    query = candidate("cap-0", "item:3", "3")
    expected = candidate("cap-2", "item:3", "4")
    catalog = {
        task.capability_id: SimpleNamespace(task_kind="state_change"),
        "cap-2": SimpleNamespace(task_kind="state_change"),
        "cap-0": SimpleNamespace(task_kind="query"),
    }
    actual = foreach_module._select_collateral_task(
        task,
        (same_capability, selected_key, query, expected),  # type: ignore[arg-type]
        catalog,
    )
    assert actual is expected


def test_foreach_compiler_keeps_report_profiles_in_separate_groups(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    start = StartCase("default", None, ("base",))
    full = {
        "type": "object",
        "properties": {"first": {"type": "string"}, "second": {"type": "string"}},
        "required": ["first", "second"],
        "additionalProperties": False,
    }
    single = {
        "type": "object",
        "properties": {"first": {"type": "string"}},
        "required": ["first"],
        "additionalProperties": False,
    }
    atoms = tuple(
        SimpleNamespace(
            release_id="a" * 64,
            start_case=start,
            capability_id="cap-1",
            semantic_key=f"item:{item}",
            public_descriptor={"item": item},
            answer_schema=schema,
        )
        for schema in (full, single)
        for item in ("one", "two")
    )
    prepared = SimpleNamespace(
        identity=SimpleNamespace(release_id="a" * 64),
        task_goals={"cap-1": "Complete every selected target."},
    )
    monkeypatch.setattr(foreach_module, "_prove_initially_false", lambda *_args: None)

    compiled = foreach_module.compile_foreach_tasks(  # type: ignore[arg-type]
        prepared,
        atoms,
        tmp_path,
    )

    assert len(compiled) == 2
    assert {tuple(item.member_answer_schema["required"]) for item in compiled} == {
        ("first", "second"),
        ("first",),
    }
