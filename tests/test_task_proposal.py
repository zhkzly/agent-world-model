from __future__ import annotations

import json
from contextlib import nullcontext
from types import SimpleNamespace
from typing import Any

import pytest

from agent_env_foundry.agents import AgentRoute
from agent_env_foundry.environment import success_observation
from agent_env_foundry.task_proposal import ProposalFailure, propose_task_direct


class FunctionCall:
    type = "function_call"

    def __init__(self, name: str, arguments: dict, call_id: str) -> None:
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


class BadRequestResponses:
    def create(self, **kwargs: Any) -> Response:
        error = RuntimeError("invalid framework request")
        error.status_code = 400  # type: ignore[attr-defined]
        raise error


class BadRequestClient:
    responses = BadRequestResponses()

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

    def open(self, instance):
        return nullcontext(SimpleNamespace(actor=self.actor))

    def read_state(self, instance):
        return {"counters": [{"id": "counter-main", "count": self.actor.count}]}


def _final(*, schema: dict | None = None) -> dict:
    answer_schema = schema or {
        "type": "object",
        "properties": {
            "counter_id": {"type": "string"},
            "count": {"type": "integer"},
        },
        "required": ["counter_id", "count"],
        "additionalProperties": False,
    }
    return {
        "instruction": "Increase counter-main by two and report its ID and resulting count.",
        "checker_brief": (
            "Require counter-main to increase by exactly two, preserve every other counter, "
            "and require the answer to report counter-main and count 2."
        ),
        "final_answer_schema_json": json.dumps(answer_schema),
        "proposed_final_answer_json": json.dumps({"counter_id": "counter-main", "count": 2}),
    }


def test_direct_proposal_uses_public_tools_and_host_captures_protected_evidence(
    tmp_path,
) -> None:
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
            Response([], json.dumps(_final())),
        ]
    )
    prepared = Prepared()
    result = propose_task_direct(
        prepared,
        development_brief={"need": "Maintain a persistent counter."},
        research_digest="2" * 64,
        instance_directory=tmp_path / "instance",
        route=AgentRoute(),
        client_factory=lambda **kwargs: client,
    )

    assert result.candidate.instruction.startswith("Increase counter-main")
    assert "challenge_categories" not in result.candidate.to_document()
    assert result.evidence.before_state == {"counters": [{"id": "counter-main", "count": 0}]}
    assert result.evidence.after_state == {"counters": [{"id": "counter-main", "count": 2}]}
    assert result.evidence.evidence_id == result.candidate.proposal_evidence_digest
    assert result.evidence.public_trace[0]["tool"] == "increment"
    first_input = repr(client.responses.calls[0]["input"])
    proposal_schema = client.responses.calls[0]["text"]["format"]["schema"]
    assert "before_state" not in first_input
    assert "after_state" not in first_input
    assert "checker_brief" not in first_input
    assert "challenge_categories" not in proposal_schema["properties"]


def test_direct_proposal_returns_nested_contract_error_for_same_history_repair(
    tmp_path,
) -> None:
    bad = _final(schema={"type": "string"})
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
            Response([], json.dumps(bad)),
            Response([], json.dumps(_final())),
        ]
    )

    result = propose_task_direct(
        Prepared(),
        development_brief={"need": "Maintain a persistent counter."},
        research_digest="2" * 64,
        instance_directory=tmp_path / "instance",
        route=AgentRoute(),
        client_factory=lambda **kwargs: client,
    )

    assert result.provider_turns == 3
    assert "final_answer_schema" in repr(client.responses.calls[2]["input"])


def test_direct_proposal_rejects_terminal_without_real_public_action(tmp_path) -> None:
    client = Client([Response([], json.dumps(_final()))])

    with pytest.raises(ProposalFailure, match="public tool"):
        propose_task_direct(
            Prepared(),
            development_brief={"need": "Maintain a persistent counter."},
            research_digest="2" * 64,
            instance_directory=tmp_path / "instance",
            route=AgentRoute(),
            client_factory=lambda **kwargs: client,
        )


def test_provider_request_contract_failure_is_attributed_to_framework(tmp_path) -> None:
    with pytest.raises(ProposalFailure) as caught:
        propose_task_direct(
            Prepared(),
            development_brief={"need": "Maintain a persistent counter."},
            research_digest="2" * 64,
            instance_directory=tmp_path / "instance",
            route=AgentRoute(),
            client_factory=lambda **kwargs: BadRequestClient(),
        )

    assert caught.value.kind == "FrameworkDefect"
    assert caught.value.code == "proposal_provider_turn_failed"
