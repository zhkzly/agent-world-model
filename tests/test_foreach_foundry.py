from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from tests.fixtures.fx_task_execution import reload_evidence

import agent_env_foundry.foreach_foundry as foreach_module
from agent_env_foundry.foreach_foundry import (
    ForEachAdmissionPlan,
    ForEachNoOpChallenge,
    ForEachPartialChallenge,
    ForEachPartialChallengeReport,
    ForEachTask,
    ForEachWitness,
    SolvedForEachTask,
    seal_foreach_task_pack,
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
        reload_evidence(task.task_id, materialization_id),
        {},
        (),
        {"results": [{}, {}]},
        (),
        (_result(), _result()),
        1,
        (None,),
    )


def _plan(task: ForEachTask) -> ForEachAdmissionPlan:
    return ForEachAdmissionPlan(task.task_id, (0,))


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
    assert plan.to_document()["format"] == "foreach-admission-plan/4"
    solved = SolvedForEachTask(
        task,
        plan,
        (_witness(task, "c" * 64), _witness(task, "d" * 64)),
    )
    assert solved.witnesses[0].to_document()["format"] == "foreach-witness/2"
    with pytest.raises(TaskFoundryError, match="reload evidence"):
        replace(
            solved.witnesses[0],
            reload_evidence=reload_evidence(
                "f" * 64,
                solved.witnesses[0].materialization_id,
            ),
        )
    assert solved.to_document()["format"] == "solved-foreach-task/1"
    assert solved.to_document()["admission_plan"]["plan_id"] == plan.plan_id

    with pytest.raises(TaskFoundryError, match="ordered"):
        replace(task, semantic_keys=("item:2", "item:1"))
    with pytest.raises(TaskFoundryError, match="instruction"):
        foreach_module._verify_task_preimage(replace(task, instruction="tampered"))
    with pytest.raises(TaskFoundryError, match="representative"):
        SolvedForEachTask(
            task,
            ForEachAdmissionPlan(task.task_id, (1,)),
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
        0,
        task.semantic_keys[0],
        "e" * 64,
        (),
        {"results": [{}]},
        (),
        (_result(satisfied=False), _result()),
    )
    assert result.to_document()["omitted_semantic_key"] == "item:1"
    report = ForEachPartialChallengeReport(task.task_id, _plan(task), (result,))
    assert report.report_id

    with pytest.raises(TaskFoundryError, match="omitted"):
        replace(result, member_results=(_result(), _result()))
    with pytest.raises(TaskFoundryError, match="representative"):
        replace(report, partials=())


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


def test_foreach_noop_rejects_every_selected_member() -> None:
    task = _task()
    plan = _plan(task)
    with pytest.raises(TaskFoundryError, match="no-op"):
        ForEachNoOpChallenge(
            task.task_id,
            plan.plan_id,
            "a" * 64,
            (_result(), _result(satisfied=False)),
        )


def test_foreach_task_pack_seals_witnesses_noop_and_one_partial() -> None:
    task = _task()
    plan = _plan(task)
    witnesses = (_witness(task, "1" * 64), _witness(task, "2" * 64))
    solved = SolvedForEachTask(task, plan, witnesses)
    failed = _result(satisfied=False)
    partial = ForEachPartialChallenge(
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
    partials = ForEachPartialChallengeReport(task.task_id, plan, (partial,))
    noop = ForEachNoOpChallenge(task.task_id, plan.plan_id, "4" * 64, (failed, failed))

    pack = seal_foreach_task_pack(solved, noop, partials)
    assert pack.task_pack_id
    assert pack.to_document()["admission"]["format"] == "foreach-admission-report/2"

    with pytest.raises(TaskFoundryError, match="reused a materialization"):
        seal_foreach_task_pack(
            solved,
            replace(noop, materialization_id=witnesses[0].materialization_id),
            partials,
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
