"""Checkpoint B: one generic execution-first Sampling Agent."""

from __future__ import annotations

import json
from contextlib import nullcontext
from types import SimpleNamespace
from typing import Any

import pytest

from agent_env_foundry.agents import AgentRoute
from agent_env_foundry.environment import success_observation
from agent_env_foundry.task_draft import SamplingTarget
from agent_env_foundry.task_proposal import SamplingFailure, sample_task_draft


class FunctionCall:
    type = "function_call"

    def __init__(self, name: str, arguments: dict[str, object], call_id: str) -> None:
        self.name, self.arguments, self.call_id = name, json.dumps(arguments), call_id


class Response:
    def __init__(self, output: list[Any], output_text: str = "") -> None:
        self.output, self.output_text = output, output_text
        self.usage = {"input_tokens": 10, "output_tokens": 5}


class Client:
    def __init__(self, responses: list[Response]) -> None:
        self.responses = SimpleNamespace()
        iterator = iter(responses)
        self.calls: list[dict[str, Any]] = []

        def create(**kwargs: Any) -> Response:
            self.calls.append(kwargs)
            return next(iterator)

        self.responses.create = create

    def close(self) -> None:
        return


class Actor:
    def __init__(self) -> None:
        self.count = 0

    def reset(self, start=None):
        self.count = int((start or {}).get("count", 0))
        return {"count": self.count, "counter_id": "counter-main", "labels": []}

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
                        "count": {"type": "integer", "minimum": 0},
                    },
                    "required": ["counter_id", "count"],
                    "additionalProperties": False,
                },
            },
            {
                "name": "inspect",
                "description": "Inspect the selected counter.",
                "input_schema": {
                    "type": "object",
                    "properties": {"counter_id": {"type": "string"}},
                    "required": ["counter_id"],
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
        if tool_name == "increment":
            self.count += arguments["amount"]
        return success_observation({"counter_id": arguments["counter_id"], "count": self.count})

    def close(self):
        return


class Prepared:
    def __init__(self) -> None:
        self.actor = Actor()
        self.identity = SimpleNamespace(release_id="1" * 64)
        self.reset_observation_schema = {
            "type": "object",
            "properties": {
                "count": {"type": "integer"},
                "counter_id": {"type": "string"},
                "labels": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["count", "counter_id", "labels"],
            "additionalProperties": False,
        }

    def open(self, instance):
        return nullcontext(SimpleNamespace(actor=self.actor))

    def read_state(self, instance):
        return {"counters": [{"id": "counter-main", "count": self.actor.count}]}


def _target(shape: str = "atom") -> SamplingTarget:
    return SamplingTarget(shape, ("increment",), "transition")


def _terminal(*, goal: dict[str, object] | None = None) -> dict[str, object]:
    return {
        "status": "draft",
        "reason": None,
        "instruction": "Increase counter-main by exactly 2 and report its ID and count.",
        "goal_json": json.dumps(goal or {"kind": "atom", "step": 1}),
        "answer_json": json.dumps(
            {
                "kind": "object",
                "fields": {
                    "counter_id": {
                        "kind": "source",
                        "source": {
                            "kind": "observation",
                            "step": 1,
                            "pointer": "/data/counter_id",
                        },
                    },
                    "count": {
                        "kind": "source",
                        "source": {
                            "kind": "observation",
                            "step": 1,
                            "pointer": "/data/count",
                        },
                    },
                },
            }
        ),
    }


def _call() -> FunctionCall:
    return FunctionCall(
        "increment",
        {"counter_id": "counter-main", "amount": 2},
        "call-1",
    )


def test_sampling_agent_must_execute_then_emit_a_grounded_task_draft(tmp_path) -> None:
    client = Client([Response([_call()]), Response([], json.dumps(_terminal()))])

    result = sample_task_draft(
        Prepared(),
        development_brief={"need": "Maintain a persistent counter."},
        target=_target(),
        instance_directory=tmp_path / "instance",
        route=AgentRoute(),
        client_factory=lambda **kwargs: client,
    )

    assert result.draft.goal.step == 1
    assert result.evidence.before_state == {"counters": [{"id": "counter-main", "count": 0}]}
    assert result.evidence.after_state == {"counters": [{"id": "counter-main", "count": 2}]}
    assert result.evidence.expected_answer == {"counter_id": "counter-main", "count": 2}
    assert result.evidence.final_answer_schema == {
        "type": "object",
        "properties": {
            "count": {"type": "integer"},
            "counter_id": {"type": "string"},
        },
        "required": ["count", "counter_id"],
        "additionalProperties": False,
    }
    request = client.calls[0]
    assert request["tool_choice"] == "required"
    assert "SamplingTarget is mandatory" in request["instructions"]
    normalized_instructions = " ".join(request["instructions"].split())
    assert "quote every free string literal" in normalized_instructions
    assert "decorative free-text" in normalized_instructions
    assert "checker" not in str(request["text"]["format"]["schema"]).lower()
    assert "answer_schema" not in str(request["text"]["format"]["schema"])
    model_input = json.loads(request["input"][0]["content"])
    contract = model_input["task_draft_contract"]
    assert contract["goal_example"] == {"kind": "atom", "step": 1}
    assert contract["answer_projection_example"]["kind"] == "object"


def test_direct_answer_field_must_name_its_public_source_leaf(tmp_path) -> None:
    terminal = _terminal()
    terminal["answer_json"] = json.dumps(
        {
            "kind": "object",
            "fields": {
                "result": {
                    "kind": "source",
                    "source": {
                        "kind": "observation",
                        "step": 1,
                        "pointer": "/data/count",
                    },
                }
            },
        }
    )
    client = Client([Response([_call()]), Response([], json.dumps(terminal))])

    with pytest.raises(SamplingFailure) as caught:
        sample_task_draft(
            Prepared(),
            development_brief={"need": "Maintain a persistent counter."},
            target=_target(),
            instance_directory=tmp_path / "instance",
            route=AgentRoute(),
            client_factory=lambda **kwargs: client,
        )

    assert caught.value.kind == "DraftRejected"
    assert caught.value.code == "draft_answer_field_source_mismatch"


def test_sampling_agent_receives_business_context_without_research_audit_metadata(
    tmp_path,
) -> None:
    client = Client([Response([_call()]), Response([], json.dumps(_terminal()))])
    brief = {
        "frozen_need": {"original_need": "Maintain counters.", "clauses": []},
        "selected_world": {"scope": "Persistent counters.", "exclusions": []},
        "requirements": [
            {
                "id": "REQ-001",
                "kind": "workflows",
                "state_relation": "Incrementing changes the selected counter.",
                "observable_relation": "The new count is returned publicly.",
                "authority": "need",
                "evidence_refs": ["E-1"],
                "falsifiable_consequence": "Audit-only text.",
                "need_origins": ["NEED-1"],
            }
        ],
        "initial_world_relations": [],
        "cited_evidence": [],
    }

    sample_task_draft(
        Prepared(),
        development_brief=brief,
        target=_target(),
        instance_directory=tmp_path / "instance",
        route=AgentRoute(),
        client_factory=lambda **kwargs: client,
    )

    model_input = json.loads(client.calls[0]["input"][0]["content"])["development_brief"]
    assert model_input["requirements"] == [
        {
            "id": "REQ-001",
            "kind": "workflows",
            "state_relation": "Incrementing changes the selected counter.",
            "observable_relation": "The new count is returned publicly.",
        }
    ]
    assert "falsifiable_consequence" not in str(model_input)
    assert "evidence_refs" not in str(model_input)


def test_sampling_agent_receives_only_public_prior_task_summaries(tmp_path) -> None:
    client = Client([Response([_call()]), Response([], json.dumps(_terminal()))])
    summary = {
        "structure_id": "a" * 64,
        "goal_shape": "atom",
        "objective_tools": ["increment"],
        "outcome_classes": ["transition"],
        "instruction": "Increase a different counter and report its ID and count.",
    }

    sample_task_draft(
        Prepared(),
        development_brief={"need": "Maintain a persistent counter."},
        target=_target(),
        instance_directory=tmp_path / "instance",
        route=AgentRoute(),
        prior_accepted_summaries=(summary,),
        client_factory=lambda **kwargs: client,
    )

    model_input = json.loads(client.calls[0]["input"][0]["content"])
    assert model_input["prior_accepted_tasks"] == [summary]
    assert all(
        word not in str(model_input["prior_accepted_tasks"]).lower()
        for word in ("goal_truth", "expected_answer", "trace", "state")
    )


def test_nonempty_trace_with_missing_objective_step_is_rejected(tmp_path) -> None:
    client = Client(
        [
            Response([_call()]),
            Response([], json.dumps(_terminal(goal={"kind": "atom", "step": 2}))),
        ]
    )

    with pytest.raises(SamplingFailure) as caught:
        sample_task_draft(
            Prepared(),
            development_brief={"need": "Maintain a persistent counter."},
            target=_target(),
            instance_directory=tmp_path / "instance",
            route=AgentRoute(),
            client_factory=lambda **kwargs: client,
        )

    assert caught.value.kind == "DraftRejected"
    assert caught.value.code == "draft_objective_step_missing"


def test_sampling_uses_sealed_reset_schema_for_empty_public_answer_arrays(tmp_path) -> None:
    terminal = _terminal()
    terminal["answer_json"] = json.dumps(
        {
            "kind": "object",
            "fields": {
                "labels": {
                    "kind": "source",
                    "source": {"kind": "reset", "pointer": "/labels"},
                }
            },
        }
    )
    client = Client([Response([_call()]), Response([], json.dumps(terminal))])

    result = sample_task_draft(
        Prepared(),
        development_brief={"need": "Maintain a persistent counter."},
        target=_target(),
        instance_directory=tmp_path / "instance",
        route=AgentRoute(),
        client_factory=lambda **kwargs: client,
    )

    assert result.evidence.expected_answer == {"labels": []}
    assert result.evidence.final_answer_schema["properties"]["labels"] == {
        "type": "array",
        "items": {"type": "string"},
    }


def test_off_target_goal_shape_is_rejected_not_counted_as_sampling_success(tmp_path) -> None:
    client = Client([Response([_call()]), Response([], json.dumps(_terminal()))])

    with pytest.raises(SamplingFailure) as caught:
        sample_task_draft(
            Prepared(),
            development_brief={"need": "Maintain a persistent counter."},
            target=_target("foreach"),
            instance_directory=tmp_path / "instance",
            route=AgentRoute(),
            client_factory=lambda **kwargs: client,
        )

    assert caught.value.kind == "DraftRejected"
    assert caught.value.code == "draft_goal_shape_mismatch"
    assert caught.value.details["provider_turns"] == 2
    assert caught.value.details["public_tool_calls"] == 1
    assert caught.value.details["usage"] == [
        {"input_tokens": 10, "output_tokens": 5},
        {"input_tokens": 10, "output_tokens": 5},
    ]


def test_required_focus_tool_must_be_an_objective_not_exploration(tmp_path) -> None:
    client = Client([Response([_call()]), Response([], json.dumps(_terminal()))])
    target = SamplingTarget("atom", ("inspect",), "transition")

    with pytest.raises(SamplingFailure) as caught:
        sample_task_draft(
            Prepared(),
            development_brief={"need": "Maintain a persistent counter."},
            target=target,
            instance_directory=tmp_path / "instance",
            route=AgentRoute(),
            client_factory=lambda **kwargs: client,
        )

    assert caught.value.kind == "DraftRejected"
    assert caught.value.code == "draft_focus_tool_missing"


def test_transition_target_requires_a_real_protected_state_change(tmp_path) -> None:
    inspect = FunctionCall("inspect", {"counter_id": "counter-main"}, "call-1")
    client = Client([Response([inspect]), Response([], json.dumps(_terminal()))])
    target = SamplingTarget("atom", ("inspect",), "transition")

    with pytest.raises(SamplingFailure) as caught:
        sample_task_draft(
            Prepared(),
            development_brief={"need": "Maintain a persistent counter."},
            target=target,
            instance_directory=tmp_path / "instance",
            route=AgentRoute(),
            client_factory=lambda **kwargs: client,
        )

    assert caught.value.kind == "DraftRejected"
    assert caught.value.code == "draft_transition_noop"
    assert caught.value.details["actual_outcome"] == "query"


def test_outcome_mismatch_precedes_focus_redirect_and_retains_actual_tool(tmp_path) -> None:
    client = Client([Response([_call()]), Response([], json.dumps(_terminal()))])
    target = SamplingTarget("atom", ("inspect",), "refusal")

    with pytest.raises(SamplingFailure) as caught:
        sample_task_draft(
            Prepared(),
            development_brief={"need": "Maintain a persistent counter."},
            target=target,
            instance_directory=tmp_path / "instance",
            route=AgentRoute(),
            client_factory=lambda **kwargs: client,
        )

    assert caught.value.code == "draft_nontransition_changed_state"
    assert caught.value.details["actual_outcome"] == "transition"
    assert caught.value.details["actual_tools"] == ["increment"]


def test_agent_can_return_typed_unsupported_after_public_inspection(tmp_path) -> None:
    unsupported = {
        "status": "unsupported",
        "reason": "No natural transition uses the required focus tool.",
        "instruction": None,
        "goal_json": None,
        "answer_json": None,
    }
    inspect = FunctionCall("inspect", {"counter_id": "counter-main"}, "call-1")
    client = Client([Response([inspect]), Response([], json.dumps(unsupported))])

    with pytest.raises(SamplingFailure) as caught:
        sample_task_draft(
            Prepared(),
            development_brief={"need": "Maintain a persistent counter."},
            target=_target("if"),
            instance_directory=tmp_path / "instance",
            route=AgentRoute(),
            client_factory=lambda **kwargs: client,
        )

    assert caught.value.kind == "SamplingUnsupported"
    assert caught.value.code == "sampling_target_unsupported"


def test_repeated_terminal_encoding_error_stops_with_executable_feedback(tmp_path) -> None:
    invalid = _terminal(goal={"shape": "atom", "steps": [1]})
    client = Client(
        [
            Response([_call()]),
            Response([], json.dumps(invalid)),
            Response([], json.dumps(invalid)),
        ]
    )

    with pytest.raises(SamplingFailure) as caught:
        sample_task_draft(
            Prepared(),
            development_brief={"need": "Maintain a persistent counter."},
            target=_target(),
            instance_directory=tmp_path / "instance",
            route=AgentRoute(),
            client_factory=lambda **kwargs: client,
        )

    assert caught.value.kind == "DraftRejected"
    assert caught.value.code == "sampling_terminal_stalled"
    assert len(client.calls) == 3
    feedback = client.calls[2]["input"][-1]["content"]
    assert "DraftGoal has unsupported kind" in feedback
    assert '"kind":"atom","step":1' in feedback
    assert "AnswerProjection" in feedback
