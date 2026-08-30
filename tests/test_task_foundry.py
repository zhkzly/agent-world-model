from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from tests.fixtures.fx_task_execution import reload_evidence

import agent_env_foundry.task_foundry as task_foundry_module
from agent_env_foundry.environment import ToolSpec
from agent_env_foundry.public_agent import PublicEpisodeRun
from agent_env_foundry.release import canonical_bytes
from agent_env_foundry.semantics import AtomCheckRequest, AtomCheckResult, StartCase, TraceEvent
from agent_env_foundry.task_foundry import (
    AtomAdmissionPlan,
    AtomChallengeReport,
    AtomChallengeResult,
    AtomPlannedChallenge,
    AtomTask,
    AtomWitness,
    SolvedAtomTask,
    TaskFoundryError,
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
        reload_evidence(task.task_id, materialization_id),
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
        no_op_result,
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
        ),
    )


def test_atom_task_and_witness_identities_bind_frozen_content() -> None:
    task = _task()
    assert task.task_id
    assert task.task_id != replace(task, instruction="Different instruction").task_id
    witness = _witness(task, "b" * 64)
    assert witness.witness_id
    assert witness.to_document()["format"] == "atom-witness/2"
    with pytest.raises(TaskFoundryError, match="reload evidence"):
        replace(
            witness,
            reload_evidence=replace(witness.reload_evidence, task_id="f" * 64),
        )
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
        reload_evidence(task.task_id, "b" * 64),
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
    assert tuple(item.category for item in plan.challenges) == (
        "no_op",
        "wrong_target",
        "wrong_answer",
    )
    assert plan.challenges[1].target_task_id == "d" * 64

    with pytest.raises(TaskFoundryError) as caught:
        AtomAdmissionPlan(
            task.task_id,
            plan.no_op_result,
            plan.challenges[:-1],
        )
    assert caught.value.code == "admission_plan_incomplete"

    with pytest.raises(TaskFoundryError) as caught:
        AtomPlannedChallenge("wrong_target", True, None, None, None)
    assert caught.value.code == "admission_plan_wrong_target_missing"


def test_atom_challenge_report_requires_each_applicable_core_negative_to_fail() -> None:
    task = _task()
    plan = _plan(task)
    rejected = plan.no_op_result
    no_op = AtomChallengeResult("no_op", True, "b" * 64, (), {}, rejected, None, None)
    wrong_target = AtomChallengeResult(
        "wrong_target",
        True,
        "c" * 64,
        (),
        {},
        rejected,
        _witness(task, "d" * 64).result,
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

    report = AtomChallengeReport(task.task_id, plan, (no_op, wrong_target, wrong_answer))
    assert report.to_document()["format"] == "atom-challenge-report/1"
    assert plan.to_document()["format"] == "atom-admission-plan/4"

    with pytest.raises(TaskFoundryError) as caught:
        AtomChallengeReport(
            task.task_id,
            plan,
            (replace(no_op, result=_witness(task, "e" * 64).result), wrong_target, wrong_answer),
        )
    assert caught.value.code == "challenge_false_acceptance"


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
    challenges = AtomChallengeReport(
        task.task_id,
        plan,
        (no_op, wrong_target, wrong_answer),
    )

    task_pack = seal_atom_task_pack(solved, challenges)
    assert task_pack.task_pack_id
    assert task_pack.to_document()["format"] == "atom-task-pack/2"


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
        "seal",
    ]
    assert events[0][1] == {"route": route, "max_provider_turns": 5}
    assert events[1][1] == {"route": route, "max_provider_turns": 5}
    assert events[2][1] == (solved, challenges)


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
