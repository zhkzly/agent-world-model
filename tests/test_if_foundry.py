from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from tests.fixtures.fx_task_execution import reload_evidence

import agent_env_foundry.if_foundry as if_module
from agent_env_foundry.if_foundry import (
    IfAdmissionPlan,
    IfTask,
    IfWitness,
    SolvedIfTask,
    compile_if_tasks,
    seal_if_task_pack,
)
from agent_env_foundry.release import canonical_bytes
from agent_env_foundry.semantics import AtomCheckResult, ConditionCheckResult, StartCase
from agent_env_foundry.task_foundry import AtomTask, TaskFoundryError


def _task() -> IfTask:
    answer_schema = {
        "type": "object",
        "properties": {},
        "required": [],
        "additionalProperties": False,
    }
    instruction = "If the selected target qualifies, take the true branch; otherwise false."
    preimage = {
        "release_id": "a" * 64,
        "start_case_id": "default",
        "condition_id": "condition-1",
        "semantic_key": "item:1",
        "true_capability_id": "cap-true",
        "false_capability_id": "cap-false",
        "expected_branch": "true",
        "branch_task_id": "b" * 64,
        "answer_schema": answer_schema,
    }
    return IfTask(
        "a" * 64,
        StartCase("default", None, ("base",)),
        "condition-1",
        "item:1",
        {"item": "one"},
        "cap-true",
        "cap-false",
        "true",
        "b" * 64,
        hashlib.sha256(canonical_bytes(preimage)).hexdigest(),
        instruction,
        hashlib.sha256(instruction.encode()).hexdigest(),
        answer_schema,
    )


def _atom_result(*, satisfied: bool = True) -> AtomCheckResult:
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


def _witness(task: IfTask, materialization_id: str) -> IfWitness:
    return IfWitness(
        task.task_id,
        materialization_id,
        reload_evidence(task.task_id, materialization_id),
        {},
        (),
        {},
        (),
        ConditionCheckResult("true", {}, ()),
        _atom_result(),
        1,
        (None,),
    )


def _atom(start: StartCase) -> AtomTask:
    answer_schema = {
        "type": "object",
        "properties": {},
        "required": [],
        "additionalProperties": False,
    }
    checker = {
        "release_id": "a" * 64,
        "start_case_id": start.case_id,
        "capability_id": "cap-true",
        "semantic_key": "item:1",
        "answer_schema": answer_schema,
    }
    instruction = "Complete the selected public task."
    return AtomTask(
        "a" * 64,
        start,
        "cap-true",
        "item:1",
        {"item": "one"},
        hashlib.sha256(canonical_bytes(checker)).hexdigest(),
        instruction,
        hashlib.sha256(instruction.encode()).hexdigest(),
        answer_schema,
    )


def test_if_task_binds_condition_branch_and_two_fresh_witnesses() -> None:
    task = _task()
    assert task.task_id
    with pytest.raises(TaskFoundryError, match="instruction"):
        if_module._verify_task_preimage(replace(task, instruction="tampered"))
    plan = IfAdmissionPlan(task.task_id)
    solved = SolvedIfTask(
        task,
        plan,
        (_witness(task, "c" * 64), _witness(task, "d" * 64)),
    )
    assert solved.witnesses[0].to_document()["format"] == "if-witness/2"
    with pytest.raises(TaskFoundryError, match="reload evidence"):
        replace(
            solved.witnesses[0],
            reload_evidence=reload_evidence(
                "f" * 64,
                solved.witnesses[0].materialization_id,
            ),
        )
    assert solved.to_document()["format"] == "solved-if-task/1"
    assert solved.to_document()["admission_plan"]["plan_id"] == plan.plan_id

    wrong_condition = replace(
        _witness(task, "e" * 64),
        condition_result=ConditionCheckResult("false", {}, ()),
    )
    with pytest.raises(TaskFoundryError, match="condition branch"):
        SolvedIfTask(task, plan, (_witness(task, "c" * 64), wrong_condition))
    failed_branch = replace(
        _witness(task, "f" * 64),
        branch_result=_atom_result(satisfied=False),
    )
    with pytest.raises(TaskFoundryError, match="selected Atom branch"):
        SolvedIfTask(task, plan, (_witness(task, "c" * 64), failed_branch))
    with pytest.raises(TaskFoundryError, match="fresh"):
        SolvedIfTask(task, plan, (_witness(task, "c" * 64), _witness(task, "c" * 64)))


def test_if_task_pack_reuses_the_exact_admitted_atom_branch() -> None:
    task = _task()
    plan = IfAdmissionPlan(task.task_id)
    solved = SolvedIfTask(
        task,
        plan,
        (_witness(task, "c" * 64), _witness(task, "d" * 64)),
    )
    branch_task = SimpleNamespace(
        task_id=task.branch_task_id,
        release_id=task.release_id,
        start_case=task.start_case,
        capability_id=task.branch_capability_id,
        semantic_key=task.semantic_key,
    )

    class BranchPack:
        task = branch_task

        def to_document(self) -> dict[str, object]:
            return {"format": "atom-task-pack/1", "task_pack_id": "e" * 64}

    pack = seal_if_task_pack(solved, BranchPack())  # type: ignore[arg-type]
    assert pack.task_pack_id
    assert pack.to_document()["format"] == "if-task-pack/2"

    wrong_branch = SimpleNamespace(**{**branch_task.__dict__, "semantic_key": "item:other"})

    class WrongBranchPack:
        task = wrong_branch

        def to_document(self) -> dict[str, object]:
            return {"format": "atom-task-pack/1", "task_pack_id": "f" * 64}

    with pytest.raises(TaskFoundryError, match="differs from its frozen Atom branch"):
        seal_if_task_pack(solved, WrongBranchPack())  # type: ignore[arg-type]


def test_if_atom_uniqueness_is_scoped_by_start_case(tmp_path: Path) -> None:
    first = _atom(StartCase("first", {"mode": "first"}, ("first",)))
    second = _atom(StartCase("second", {"mode": "second"}, ("second",)))

    class ReachedOpen(RuntimeError):
        pass

    class Prepared:
        identity = SimpleNamespace(release_id="a" * 64)

        def open(self, _root: Path) -> object:
            raise ReachedOpen

    with pytest.raises(ReachedOpen):
        compile_if_tasks(Prepared(), (first, second), tmp_path)  # type: ignore[arg-type]

    profile = replace(
        first,
        answer_schema={
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
            "additionalProperties": False,
        },
    )
    with pytest.raises(ReachedOpen):
        compile_if_tasks(Prepared(), (first, profile), tmp_path)  # type: ignore[arg-type]

    with pytest.raises(TaskFoundryError) as caught:
        compile_if_tasks(Prepared(), (first, first), tmp_path)  # type: ignore[arg-type]
    assert caught.value.code == "if_atom_universe_invalid"


def test_abstaining_condition_rejects_only_that_if_blueprint() -> None:
    condition = SimpleNamespace(
        true_capability_ids=("cap-true",),
        false_capability_ids=("cap-false",),
    )
    assert (
        if_module._condition_capability(
            condition,  # type: ignore[arg-type]
            ConditionCheckResult("abstain", {}, ()),
        )
        is None
    )
    assert (
        if_module._condition_capability(
            condition,  # type: ignore[arg-type]
            ConditionCheckResult("true", {}, ()),
        )
        == "cap-true"
    )


def test_if_instruction_discloses_report_fields_and_requires_branch_execution() -> None:
    instruction = if_module._instruction(
        "The public condition holds.",
        "Complete the true outcome.",
        "Complete the false outcome.",
        {"item": "one"},
    )

    assert "Return a JSON object with these fields" not in instruction
    assert "condition evaluation alone does not complete the Task" in instruction
