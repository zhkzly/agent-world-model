from __future__ import annotations

import hashlib
from dataclasses import replace

import pytest

from agent_env_foundry.release import canonical_bytes
from agent_env_foundry.semantics import AtomCheckResult, StartCase
from agent_env_foundry.task_foundry import (
    AtomTask,
    AtomWitness,
    SolvedAtomTask,
    TaskFoundryError,
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
        (),
        {},
        result,
        1,
        (None,),
    )


def test_atom_task_and_witness_identities_bind_frozen_content() -> None:
    task = _task()
    assert task.task_id
    assert task.task_id != replace(task, instruction="Different instruction").task_id
    witness = _witness(task, "b" * 64)
    assert witness.witness_id
    solved = SolvedAtomTask(task, (witness, _witness(task, "c" * 64)))
    assert solved.to_document()["format"] == "solved-atom-task/1"


def test_solved_atom_requires_two_fresh_successful_witnesses() -> None:
    task = _task()
    first = _witness(task, "b" * 64)
    with pytest.raises(TaskFoundryError) as caught:
        SolvedAtomTask(task, (first, _witness(task, "b" * 64)))
    assert caught.value.code == "witness_materialization_reused"

    with pytest.raises(TaskFoundryError) as caught:
        SolvedAtomTask(task, (first, _witness(task, "c" * 64, satisfied=False)))
    assert caught.value.code == "witness_not_satisfied"
