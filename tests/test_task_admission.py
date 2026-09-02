from __future__ import annotations

import json
from contextlib import nullcontext
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from agent_env_foundry.agents import AgentRoute
from agent_env_foundry.environment import success_observation
from agent_env_foundry.task_admission import (
    TaskWitness,
    challenge_collateral_from_witness,
    challenge_no_op,
    challenge_partial_from_witness,
    challenge_wrong_answer,
    challenge_wrong_target,
    run_task_witness,
)
from agent_env_foundry.task_contract import (
    CandidateTaskContract,
    TaskCheckResult,
    TaskProposalEvidence,
    seal_task_contract,
)
from agent_env_foundry.task_pack import TaskPack, TaskPackError


class FunctionCall:
    type = "function_call"

    def __init__(self, name: str, arguments: dict[str, Any], call_id: str) -> None:
        self.name = name
        self.arguments = json.dumps(arguments)
        self.call_id = call_id


class Response:
    def __init__(self, output: list[Any], output_text: str = "") -> None:
        self.output = output
        self.output_text = output_text
        self.usage = {"input_tokens": 10, "output_tokens": 5}


class Responses:
    def __init__(self, values: list[Response]) -> None:
        self.values = iter(values)
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Response:
        self.calls.append(kwargs)
        return next(self.values)


class Client:
    def __init__(self, values: list[Response]) -> None:
        self.responses = Responses(values)

    def close(self) -> None:
        return


class Actor:
    def __init__(self) -> None:
        self.count = 0

    def reset(self, start=None):
        self.count = int((start or {}).get("count", 0))
        return {"count": self.count, "counter_id": "counter-main"}

    def tools(self):
        return (
            {
                "name": "increment",
                "description": "Increment the selected counter.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "counter_id": {"type": "string"},
                        "amount": {"type": "integer", "minimum": 1},
                    },
                    "required": ["counter_id", "amount"],
                    "additionalProperties": False,
                },
                "output_schema": {
                    "type": "object",
                    "properties": {
                        "counter_id": {"type": "string"},
                        "count": {"type": "integer"},
                    },
                    "required": ["counter_id", "count"],
                    "additionalProperties": False,
                },
            },
        )

    def invoke(self, tool_name, arguments):
        assert tool_name == "increment"
        self.count += arguments["amount"]
        return success_observation({"counter_id": arguments["counter_id"], "count": self.count})

    def close(self):
        return


class Prepared:
    def __init__(self) -> None:
        self.actor = Actor()
        self.identity = SimpleNamespace(release_id="1" * 64)
        self.state_reads = 0

    def open(self, instance):
        Path(instance).mkdir(parents=True, exist_ok=True)
        return nullcontext(SimpleNamespace(actor=self.actor))

    def read_state(self, instance):
        self.state_reads += 1
        return {"counters": [{"id": "counter-main", "count": self.actor.count}]}


def _task_inputs(challenge_categories=("no_op", "wrong_answer")):
    evidence = TaskProposalEvidence(
        "task-proposal-evidence/1",
        "1" * 64,
        None,
        {"count": 0, "counter_id": "counter-main"},
        {"counters": [{"id": "counter-main", "count": 0}]},
        {"counters": [{"id": "counter-main", "count": 2}]},
        (
            {
                "tool": "increment",
                "arguments": {"counter_id": "counter-main", "amount": 2},
                "observation": success_observation({"counter_id": "counter-main", "count": 2}),
            },
        ),
        {"counter_id": "counter-main", "count": 2},
    )
    candidate = CandidateTaskContract(
        "candidate-task-contract/1",
        evidence.release_id,
        "2" * 64,
        None,
        "Increase counter-main by two and report its resulting count.",
        {
            "type": "object",
            "properties": {
                "counter_id": {"type": "string"},
                "count": {"type": "integer"},
            },
            "required": ["counter_id", "count"],
            "additionalProperties": False,
        },
        "Require counter-main alone to increase by exactly two.",
        evidence.evidence_id,
        challenge_categories,
    )
    task = seal_task_contract(candidate, checker_project_digest="a" * 64)
    return evidence, candidate, task


def _task(challenge_categories=("no_op", "wrong_answer")):
    return _task_inputs(challenge_categories)[2]


def test_fresh_witness_uses_only_public_input_then_checks_reopened_state(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    client = Client(
        [
            Response(
                [
                    FunctionCall(
                        "increment",
                        {"counter_id": "counter-main", "amount": 2},
                        "call-1",
                    )
                ]
            ),
            Response([], '{"counter_id":"counter-main","count":2}'),
        ]
    )
    prepared = Prepared()
    observed = {}

    def check(project_root, *, task, request, runtime_root, settings):
        observed["request"] = request
        return TaskCheckResult(
            "task-check-result/1",
            True,
            True,
            True,
            True,
            True,
            True,
            (),
        )

    monkeypatch.setattr("agent_env_foundry.task_admission.execute_task_checker", check)
    witness = run_task_witness(
        prepared,
        task=_task(),
        checker_project_root=tmp_path / "checker",
        instance_directory=tmp_path / "instance",
        checker_runtime_root=tmp_path / "checker-runtime",
        witness_index=1,
        route=AgentRoute(),
        client_factory=lambda **kwargs: client,
    )

    assert witness.before_state == {"counters": [{"id": "counter-main", "count": 0}]}
    assert witness.after_state == {"counters": [{"id": "counter-main", "count": 2}]}
    assert witness.public_trace[0]["tool"] == "increment"
    assert witness.checker_result.passed
    assert prepared.state_reads == 3
    assert observed["request"].task_id == witness.task_id
    model_input = repr(client.responses.calls[0]["input"])
    assert "before_state" not in model_input
    assert "after_state" not in model_input
    assert "checker" not in model_input


def test_noop_and_schema_valid_wrong_answer_are_independently_rejected(
    tmp_path, monkeypatch
) -> None:
    evidence, candidate, task = _task_inputs()
    passed = TaskCheckResult("task-check-result/1", True, True, True, True, True, True, ())
    witness = TaskWitness(
        "task-witness/1",
        task.task_id,
        task.release_id,
        1,
        {"count": 0, "counter_id": "counter-main"},
        {"counters": [{"id": "counter-main", "count": 0}]},
        {"counters": [{"id": "counter-main", "count": 2}]},
        (
            {
                "tool": "increment",
                "arguments": {"counter_id": "counter-main", "amount": 2},
                "observation": success_observation({"counter_id": "counter-main", "count": 2}),
            },
        ),
        {"counter_id": "counter-main", "count": 2},
        passed,
        1,
        ({"input_tokens": 10, "output_tokens": 5},),
    )

    def check(project_root, *, task, request, runtime_root, settings):
        no_op = request.before_state == request.after_state
        answer = request.final_answer == {"counter_id": "counter-main", "count": 2}
        axes = (not no_op, answer, not no_op, True, bool(request.public_trace))
        reasons = tuple(
            name
            for name, ok in zip(
                ("goal", "answer", "required", "forbidden", "process"),
                axes,
                strict=True,
            )
            if not ok
        )
        return TaskCheckResult("task-check-result/1", all(axes), *axes, tuple(sorted(reasons)))

    monkeypatch.setattr("agent_env_foundry.task_admission.execute_task_checker", check)
    no_op = challenge_no_op(
        Prepared(),
        task=task,
        reference_final_answer=witness.final_answer,
        checker_project_root=tmp_path / "checker",
        instance_directory=tmp_path / "noop-instance",
        checker_runtime_root=tmp_path / "noop-checker-runtime",
    )
    wrong_answer = challenge_wrong_answer(
        task=task,
        witness=witness,
        checker_project_root=tmp_path / "checker",
        checker_runtime_root=tmp_path / "wrong-answer-checker-runtime",
    )

    assert no_op.category == "no_op"
    assert no_op.before_state == no_op.after_state
    assert not no_op.checker_result.passed
    assert wrong_answer.category == "wrong_answer"
    assert wrong_answer.final_answer != witness.final_answer
    assert not wrong_answer.checker_result.answer

    pack = TaskPack(
        "task-pack/1",
        candidate,
        evidence,
        task,
        (witness, replace(witness, witness_index=2)),
        (no_op, wrong_answer),
    )
    assert pack.public_document() == {
        "format": "public-task-pack/1",
        "task_pack_id": pack.task_pack_id,
        "task_id": task.task_id,
        "release_id": task.release_id,
        "instruction": task.instruction,
        "final_answer_schema": task.final_answer_schema,
    }
    with pytest.raises(TaskPackError, match="exact declared order"):
        replace(pack, challenges=(wrong_answer, no_op))


def test_wrong_target_challenge_is_a_fresh_public_physical_attempt(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    client = Client(
        [
            Response(
                [
                    FunctionCall(
                        "increment",
                        {"counter_id": "counter-main", "amount": 1},
                        "call-1",
                    )
                ]
            ),
            Response([], '{"summary":"Incremented the counter by one."}'),
        ]
    )

    class CoarsePrepared(Prepared):
        def read_state(self, instance):
            self.state_reads += 1
            return {"counter_exists": True}

    def check(project_root, *, task, request, runtime_root, settings):
        amount = request.public_trace[0]["arguments"]["amount"]
        complete = amount == 2
        axes = (complete, complete, complete, True, bool(request.public_trace))
        reasons = tuple(
            name
            for name, ok in zip(
                ("goal", "answer", "required", "forbidden", "process"),
                axes,
                strict=True,
            )
            if not ok
        )
        return TaskCheckResult("task-check-result/1", all(axes), *axes, tuple(sorted(reasons)))

    monkeypatch.setattr("agent_env_foundry.task_admission.execute_task_checker", check)
    challenge = challenge_wrong_target(
        CoarsePrepared(),
        task=_task(("no_op", "wrong_answer", "wrong_target")),
        reference_final_answer={"counter_id": "counter-main", "count": 2},
        checker_project_root=tmp_path / "checker",
        instance_directory=tmp_path / "partial-instance",
        checker_runtime_root=tmp_path / "partial-checker-runtime",
        route=AgentRoute(),
        client_factory=lambda **kwargs: client,
    )

    assert challenge.category == "wrong_target"
    assert challenge.before_state == challenge.after_state
    assert challenge.provider_turns == 2
    assert challenge.policy_final_answer == {"summary": "Incremented the counter by one."}
    model_input = repr(client.responses.calls[0]["input"])
    assert "VERIFIER WRONG-TARGET CHALLENGE" in model_input
    assert "overrides conflicting" in model_input
    assert "before_state" not in model_input
    assert "checker" not in model_input


def test_wrong_answer_mutation_can_preserve_a_patterned_identifier(tmp_path, monkeypatch) -> None:
    evidence, candidate, _ = _task_inputs()
    candidate = replace(
        candidate,
        final_answer_schema={
            "type": "object",
            "properties": {"commit_id": {"type": "string", "pattern": "^[0-9a-f]{40}$"}},
            "required": ["commit_id"],
            "additionalProperties": False,
        },
    )
    task = seal_task_contract(candidate, checker_project_digest="a" * 64)
    passing = TaskCheckResult("task-check-result/1", True, True, True, True, True, True, ())
    witness = TaskWitness(
        "task-witness/1",
        task.task_id,
        task.release_id,
        1,
        evidence.reset_observation,
        evidence.before_state,
        evidence.after_state,
        evidence.public_trace,
        {"commit_id": "a" * 40},
        passing,
        1,
        ({"input_tokens": 1},),
    )

    def check(project_root, *, task, request, runtime_root, settings):
        answer = request.final_answer == {"commit_id": "a" * 40}
        reasons = () if answer else ("answer",)
        return TaskCheckResult(
            "task-check-result/1", answer, True, answer, True, True, True, reasons
        )

    monkeypatch.setattr("agent_env_foundry.task_admission.execute_task_checker", check)
    challenge = challenge_wrong_answer(
        task=task,
        witness=witness,
        checker_project_root=tmp_path / "checker",
        checker_runtime_root=tmp_path / "runtime",
    )

    mutated = challenge.final_answer["commit_id"]
    assert isinstance(mutated, str) and len(mutated) == 40
    assert set(mutated) <= set("0123456789abcdef")
    assert mutated != "a" * 40


def test_partial_can_replay_a_strict_successful_witness_prefix(tmp_path, monkeypatch) -> None:
    evidence, _, task = _task_inputs(("no_op", "wrong_answer", "partial"))
    passed = TaskCheckResult("task-check-result/1", True, True, True, True, True, True, ())
    trace = tuple(
        {
            "tool": "increment",
            "arguments": {"counter_id": "counter-main", "amount": 1},
            "observation": success_observation({"counter_id": "counter-main", "count": index}),
        }
        for index in (1, 2)
    )
    witness = TaskWitness(
        "task-witness/1",
        task.task_id,
        task.release_id,
        1,
        evidence.reset_observation,
        evidence.before_state,
        evidence.after_state,
        trace,
        {"counter_id": "counter-main", "count": 2},
        passed,
        1,
        ({"input_tokens": 1},),
    )

    def check(project_root, *, task, request, runtime_root, settings):
        count = request.after_state["counters"][0]["count"]
        complete = count == 2
        axes = (complete, True, complete, True, bool(request.public_trace))
        reasons = () if complete else ("goal", "required")
        return TaskCheckResult("task-check-result/1", all(axes), *axes, tuple(sorted(reasons)))

    monkeypatch.setattr("agent_env_foundry.task_admission.execute_task_checker", check)
    challenge = challenge_partial_from_witness(
        Prepared(),
        task=task,
        witness=witness,
        checker_project_root=tmp_path / "checker",
        attempt_root=tmp_path / "partial-attempts",
        checker_runtime_root=tmp_path / "checker-runtime",
    )

    assert challenge.category == "partial"
    assert len(challenge.public_trace) == 1
    assert challenge.provider_turns == 0
    assert challenge.source_witness_id == witness.witness_id
    assert not challenge.checker_result.required_effects


def test_collateral_starts_from_a_replayed_passing_witness(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    evidence, candidate, task = _task_inputs(("no_op", "wrong_answer", "collateral"))
    passed = TaskCheckResult("task-check-result/1", True, True, True, True, True, True, ())
    witness = TaskWitness(
        "task-witness/1",
        task.task_id,
        task.release_id,
        1,
        evidence.reset_observation,
        evidence.before_state,
        evidence.after_state,
        evidence.public_trace,
        evidence.proposed_final_answer,
        passed,
        1,
        ({"input_tokens": 1},),
    )
    client = Client(
        [
            Response(
                [
                    FunctionCall(
                        "increment",
                        {"counter_id": "counter-main", "amount": 1},
                        "call-extra",
                    )
                ]
            ),
            Response([], '{"summary":"Incremented once beyond the requested result."}'),
        ]
    )

    def check(project_root, *, task, request, runtime_root, settings):
        count = request.after_state["counters"][0]["count"]
        answer = request.final_answer == evidence.proposed_final_answer
        axes = (count >= 2, answer, count >= 2, count == 2, bool(request.public_trace))
        reasons = tuple(
            name
            for name, ok in zip(
                ("goal", "answer", "required", "forbidden", "process"),
                axes,
                strict=True,
            )
            if not ok
        )
        return TaskCheckResult("task-check-result/1", all(axes), *axes, tuple(sorted(reasons)))

    monkeypatch.setattr("agent_env_foundry.task_admission.execute_task_checker", check)
    challenge = challenge_collateral_from_witness(
        Prepared(),
        task=task,
        witness=witness,
        checker_project_root=tmp_path / "checker",
        instance_directory=tmp_path / "collateral-instance",
        checker_runtime_root=tmp_path / "runtime",
        route=AgentRoute(),
        client_factory=lambda **kwargs: client,
    )

    assert len(challenge.public_trace) == 2
    assert challenge.source_witness_id == witness.witness_id
    assert challenge.checker_result.required_effects
    assert not challenge.checker_result.forbidden_effects

    no_op = challenge_no_op(
        Prepared(),
        task=task,
        reference_final_answer=witness.final_answer,
        checker_project_root=tmp_path / "checker",
        instance_directory=tmp_path / "noop-instance",
        checker_runtime_root=tmp_path / "noop-runtime",
    )
    wrong_answer = challenge_wrong_answer(
        task=task,
        witness=witness,
        checker_project_root=tmp_path / "checker",
        checker_runtime_root=tmp_path / "wrong-answer-runtime",
    )
    pack = TaskPack(
        "task-pack/1",
        candidate,
        evidence,
        task,
        (witness, replace(witness, witness_index=2)),
        (no_op, wrong_answer, challenge),
    )
    assert pack.task_pack_id
