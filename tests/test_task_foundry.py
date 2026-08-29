from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

import agent_env_foundry.task_foundry as task_foundry_module
from agent_env_foundry.environment import ToolSpec
from agent_env_foundry.public_agent import PublicEpisodeRun
from agent_env_foundry.release import canonical_bytes
from agent_env_foundry.semantics import AtomCheckResult, StartCase, TraceEvent
from agent_env_foundry.task_foundry import (
    AtomAdmissionPlan,
    AtomChallengeReport,
    AtomChallengeResult,
    AtomPlannedChallenge,
    AtomTask,
    AtomWitness,
    SolvedAtomTask,
    TaskFoundryError,
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
    return AtomAdmissionPlan(
        task.task_id,
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
    assert tuple(item.category for item in plan.challenges) == (
        "no_op",
        "wrong_target",
        "wrong_answer",
        "missing_process",
    )
    assert plan.challenges[1].target_task_id == "d" * 64

    with pytest.raises(TaskFoundryError) as caught:
        AtomAdmissionPlan(task.task_id, plan.challenges[:-1])
    assert caught.value.code == "admission_plan_incomplete"

    with pytest.raises(TaskFoundryError) as caught:
        AtomPlannedChallenge("wrong_target", True, None, None, None)
    assert caught.value.code == "admission_plan_wrong_target_missing"


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
        (current, unrelated, shared_workflow, same_capability),
        capabilities,  # type: ignore[arg-type]
    )
    assert selected == same_capability
    selected = task_foundry_module._select_wrong_target_task(
        current,
        (current, unrelated, shared_workflow),
        capabilities,  # type: ignore[arg-type]
    )
    assert selected == shared_workflow


def test_atom_challenge_report_requires_rejected_noop() -> None:
    task = _task()
    plan = _plan(task)
    rejected = AtomCheckResult(
        initially_satisfied=False,
        satisfied=False,
        required_effects_ok=False,
        collateral_ok=True,
        answer_ok=None,
        process_ok=False,
        report_values={},
        failure_codes=("NO_OP",),
    )
    no_op = AtomChallengeResult(
        "no_op",
        True,
        "b" * 64,
        (),
        {},
        rejected,
        None,
    )
    wrong_target = replace(no_op, category="wrong_target")
    not_applicable = AtomChallengeResult(
        "wrong_answer",
        False,
        None,
        (),
        {},
        None,
        "answer schema has no schema-valid alternative value",
    )
    missing_process = replace(no_op, category="missing_process")
    report = AtomChallengeReport(
        task.task_id,
        plan,
        (no_op, wrong_target, not_applicable, missing_process),
    )
    assert report.to_document()["format"] == "atom-challenge-report/1"

    with pytest.raises(TaskFoundryError) as caught:
        AtomChallengeReport(task.task_id, plan, (no_op, wrong_target, not_applicable))
    assert caught.value.code == "challenge_plan_incomplete"

    accepted = replace(no_op, result=_witness(task, "c" * 64).result)
    with pytest.raises(TaskFoundryError) as caught:
        AtomChallengeReport(
            task.task_id,
            plan,
            (accepted, wrong_target, not_applicable, missing_process),
        )
    assert caught.value.code == "challenge_false_acceptance"

    accepted_wrong_target = replace(wrong_target, result=_witness(task, "c" * 64).result)
    with pytest.raises(TaskFoundryError) as caught:
        AtomChallengeReport(
            task.task_id,
            plan,
            (no_op, accepted_wrong_target, not_applicable, missing_process),
        )
    assert caught.value.code == "challenge_false_acceptance"
