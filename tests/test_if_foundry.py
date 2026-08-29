from __future__ import annotations

import hashlib
from dataclasses import replace
from types import SimpleNamespace

import pytest

import agent_env_foundry.if_foundry as if_module
from agent_env_foundry.if_foundry import (
    IfAdmissionPlan,
    IfTask,
    IfWitness,
    SolvedIfTask,
    seal_if_task_pack,
)
from agent_env_foundry.release import canonical_bytes
from agent_env_foundry.semantics import AtomCheckResult, ConditionCheckResult, StartCase
from agent_env_foundry.task_foundry import TaskFoundryError


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
        {},
        (),
        {},
        (),
        ConditionCheckResult("true", {}, ()),
        _atom_result(),
        _atom_result(satisfied=False),
        1,
        (None,),
    )


def test_if_task_binds_condition_branch_and_two_fresh_witnesses() -> None:
    task = _task()
    assert task.task_id
    with pytest.raises(TaskFoundryError, match="instruction"):
        if_module._verify_task_preimage(replace(task, instruction="tampered"))
    plan = IfAdmissionPlan(task.task_id, ("flip_condition_branch",))
    with pytest.raises(TaskFoundryError, match="flip-condition"):
        IfAdmissionPlan(task.task_id, ())
    solved = SolvedIfTask(
        task,
        plan,
        (_witness(task, "c" * 64), _witness(task, "d" * 64)),
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
    false_accept = replace(
        _witness(task, "f" * 64),
        opposite_branch_result=_atom_result(),
    )
    with pytest.raises(TaskFoundryError, match="opposite Atom branch"):
        SolvedIfTask(task, plan, (_witness(task, "c" * 64), false_accept))
    with pytest.raises(TaskFoundryError, match="fresh"):
        SolvedIfTask(task, plan, (_witness(task, "c" * 64), _witness(task, "c" * 64)))


def test_if_task_pack_reuses_the_exact_admitted_atom_branch() -> None:
    task = _task()
    plan = IfAdmissionPlan(task.task_id, ("flip_condition_branch",))
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
    assert pack.to_document()["format"] == "if-task-pack/1"

    wrong_branch = SimpleNamespace(**{**branch_task.__dict__, "semantic_key": "item:other"})

    class WrongBranchPack:
        task = wrong_branch

        def to_document(self) -> dict[str, object]:
            return {"format": "atom-task-pack/1", "task_pack_id": "f" * 64}

    with pytest.raises(TaskFoundryError, match="differs from its frozen Atom branch"):
        seal_if_task_pack(solved, WrongBranchPack())  # type: ignore[arg-type]
