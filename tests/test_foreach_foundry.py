from __future__ import annotations

import hashlib
from dataclasses import replace
from types import SimpleNamespace

import pytest

import agent_env_foundry.foreach_foundry as foreach_module
from agent_env_foundry.foreach_foundry import (
    ForEachTask,
    ForEachWitness,
    SolvedForEachTask,
)
from agent_env_foundry.release import canonical_bytes
from agent_env_foundry.semantics import (
    AtomCheckResult,
    BindingCandidate,
    PublicFieldSource,
    PublicValueSource,
    StartCase,
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
    solved = SolvedForEachTask(task, (_witness(task, "c" * 64), _witness(task, "d" * 64)))
    assert solved.to_document()["format"] == "solved-foreach-task/1"

    with pytest.raises(TaskFoundryError, match="ordered"):
        replace(task, semantic_keys=("item:2", "item:1"))
    with pytest.raises(TaskFoundryError, match="fresh"):
        SolvedForEachTask(task, (_witness(task, "c" * 64), _witness(task, "c" * 64)))
    failed = replace(
        _witness(task, "d" * 64),
        member_results=(_result(), _result(satisfied=False)),
    )
    with pytest.raises(TaskFoundryError, match="Every selected"):
        SolvedForEachTask(task, (_witness(task, "c" * 64), failed))


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
