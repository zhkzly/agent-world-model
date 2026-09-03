from __future__ import annotations

import json
from typing import Any

import pytest

from agent_env_foundry.public_agent import (
    PUBLIC_AGENT_SYSTEM_PROMPT,
    PublicAgentFailure,
    run_public_episode,
)


class Actor:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.tool_snapshots = 0

    def tools(self) -> tuple[dict[str, Any], ...]:
        self.tool_snapshots += 1
        return (_tool(),)

    def invoke(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((tool_name, arguments))
        return {"ok": True, "data": {"value": arguments["item"]}, "error": None}


class Responses:
    def __init__(self, outputs: list[dict[str, Any]]) -> None:
        self.outputs = outputs
        self.requests: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> dict[str, Any]:
        self.requests.append(kwargs)
        return self.outputs.pop(0)


class Client:
    def __init__(self, responses: Responses) -> None:
        self.responses = responses


def _tool() -> dict[str, Any]:
    return {
        "name": "inspect_item",
        "description": "Inspect one public item.",
        "input_schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {"item": {"type": "string"}},
            "required": ["item"],
        },
        "output_schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
        },
    }


def _answer_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {"value": {"type": "string"}},
        "required": ["value"],
    }


def test_public_episode_preserves_exact_tool_loop_and_returns_trace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = Responses(
        [
            {
                "output": [
                    {
                        "type": "function_call",
                        "name": "inspect_item",
                        "arguments": '{"item":"public-1"}',
                        "call_id": "call-1",
                    }
                ],
                "output_text": None,
                "usage": {"input_tokens": 10, "output_tokens": 4},
            },
            {
                "output": [],
                "output_text": '{"value":"public-1"}',
                "usage": {"input_tokens": 20, "output_tokens": 3},
            },
        ]
    )
    actor = Actor()
    tool_specs = actor.tools()
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    episode = run_public_episode(
        actor=actor,
        instruction="Inspect public-1 and report its value.",
        reset_observation={"items": [{"item": "public-1"}]},
        tool_specs=tool_specs,
        answer_schema=_answer_schema(),
        client_factory=lambda **_kwargs: Client(responses),
        max_provider_turns=2,
    )

    assert episode.final_answer == {"value": "public-1"}
    assert episode.provider_turns == 2
    assert episode.usage == (
        {"input_tokens": 10, "output_tokens": 4},
        {"input_tokens": 20, "output_tokens": 3},
    )
    assert episode.trace[0].tool_name == "inspect_item"
    assert episode.trace[0].arguments == {"item": "public-1"}
    assert actor.tool_snapshots == 1
    assert actor.calls == [("inspect_item", {"item": "public-1"})]
    assert responses.requests[0]["tool_choice"] == "required"
    assert responses.requests[1]["tool_choice"] == "auto"
    assert "ok=true" in responses.requests[0]["tools"][0]["description"]
    assert "error.code" in responses.requests[0]["tools"][0]["description"]
    assert "when needed" not in PUBLIC_AGENT_SYSTEM_PROMPT
    assert "final JSON" not in PUBLIC_AGENT_SYSTEM_PROMPT
    assert "exact spelling and case" in PUBLIC_AGENT_SYSTEM_PROMPT
    assert "Do not paraphrase" in PUBLIC_AGENT_SYSTEM_PROMPT
    continuation = responses.requests[1]["input"]
    assert continuation[1]["type"] == "function_call"
    assert continuation[2] == {
        "type": "function_call_output",
        "call_id": "call-1",
        "output": json.dumps(
            {"ok": True, "data": {"value": "public-1"}, "error": None},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
    }


def test_public_episode_rejects_unknown_tool_and_invalid_final_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    unknown = Responses(
        [
            {
                "output": [
                    {
                        "type": "function_call",
                        "name": "hidden_tool",
                        "arguments": "{}",
                        "call_id": "call-1",
                    }
                ],
                "output_text": None,
            }
        ]
    )
    with pytest.raises(PublicAgentFailure) as caught:
        run_public_episode(
            actor=Actor(),
            instruction="Inspect one item.",
            reset_observation={},
            tool_specs=(_tool(),),
            answer_schema=_answer_schema(),
            client_factory=lambda **_kwargs: Client(unknown),
            max_provider_turns=1,
        )
    assert caught.value.code == "unknown_tool_call"

    invalid = Responses(
        [
            {
                "output": [
                    {
                        "type": "function_call",
                        "name": "inspect_item",
                        "arguments": '{"item":"public-1"}',
                        "call_id": "call-1",
                    }
                ],
                "output_text": None,
            },
            {"output": [], "output_text": '{"wrong":true}'},
        ]
    )
    with pytest.raises(PublicAgentFailure) as caught:
        run_public_episode(
            actor=Actor(),
            instruction="Inspect one item.",
            reset_observation={},
            tool_specs=(_tool(),),
            answer_schema=_answer_schema(),
            client_factory=lambda **_kwargs: Client(invalid),
            max_provider_turns=2,
        )
    assert caught.value.code == "final_answer_invalid"

    premature = Responses([{"output": [], "output_text": '{"value":"guessed"}'}])
    with pytest.raises(PublicAgentFailure) as caught:
        run_public_episode(
            actor=Actor(),
            instruction="Inspect one item.",
            reset_observation={},
            tool_specs=(_tool(),),
            answer_schema=_answer_schema(),
            client_factory=lambda **_kwargs: Client(premature),
            max_provider_turns=1,
        )
    assert caught.value.code == "required_tool_call_missing"


def test_public_episode_failure_retains_prior_public_capture(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    responses = Responses(
        [
            {
                "output": [
                    {
                        "type": "function_call",
                        "name": "inspect_item",
                        "arguments": '{"item":"public-1"}',
                        "call_id": "call-1",
                    }
                ],
                "output_text": None,
                "usage": {"input_tokens": 10, "output_tokens": 4},
            },
            {
                "output": [
                    {
                        "type": "function_call",
                        "name": "hidden_tool",
                        "arguments": "{}",
                        "call_id": "call-2",
                    }
                ],
                "output_text": None,
                "usage": {"input_tokens": 20, "output_tokens": 3},
            },
        ]
    )

    with pytest.raises(PublicAgentFailure) as caught:
        run_public_episode(
            actor=Actor(),
            instruction="Inspect public-1 and report its value.",
            reset_observation={"items": [{"item": "public-1"}]},
            tool_specs=(_tool(),),
            answer_schema=_answer_schema(),
            client_factory=lambda **_kwargs: Client(responses),
            max_provider_turns=2,
        )

    assert caught.value.kind == "NoPublicWitness"
    assert caught.value.code == "unknown_tool_call"
    assert "capture" in caught.value.details
    capture = caught.value.details["capture"]
    json.dumps(capture, allow_nan=False)
    assert capture["turns"] == [
        {
            "turn_index": 1,
            "calls": [
                {
                    "raw_call_id": "call-1",
                    "raw_tool_name": "inspect_item",
                    "call_id": "call-1",
                    "tool_name": "inspect_item",
                    "raw_arguments": '{"item":"public-1"}',
                    "parsed_arguments": {"item": "public-1"},
                    "parse_status": "valid",
                    "schema_status": "valid",
                    "dispatch_status": "dispatched",
                    "observation": {
                        "ok": True,
                        "data": {"value": "public-1"},
                        "error": None,
                    },
                }
            ],
            "raw_public_terminal": None,
            "usage": {"input_tokens": 10, "output_tokens": 4},
        },
        {
            "turn_index": 2,
            "calls": [
                {
                    "raw_call_id": "call-2",
                    "raw_tool_name": "hidden_tool",
                    "call_id": "call-2",
                    "tool_name": "hidden_tool",
                    "raw_arguments": "{}",
                    "parsed_arguments": {},
                    "parse_status": "valid",
                    "schema_status": "not_checked",
                    "dispatch_status": "unknown_tool",
                    "observation": None,
                }
            ],
            "raw_public_terminal": None,
            "usage": {"input_tokens": 20, "output_tokens": 3},
        },
    ]
    assert capture["completion"] == {
        "terminal_kind": "policy_failure",
        "final_answer": None,
        "terminal_code": "unknown_tool_call",
    }


def test_public_episode_rejects_zero_budget_and_attributes_actor_defects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    with pytest.raises(ValueError, match="positive"):
        run_public_episode(
            actor=Actor(),
            instruction="Inspect one item.",
            reset_observation={},
            tool_specs=(_tool(),),
            answer_schema=_answer_schema(),
            client_factory=lambda **_kwargs: Client(Responses([])),
            max_provider_turns=0,
        )

    response = Responses(
        [
            {
                "output": [
                    {
                        "type": "function_call",
                        "name": "inspect_item",
                        "arguments": '{"item":"public-1"}',
                        "call_id": "call-1",
                    }
                ],
                "output_text": None,
            }
        ]
    )

    class BrokenActor(Actor):
        def invoke(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
            del tool_name, arguments
            return {"ok": True, "data": {"wrong": True}, "error": None}

    with pytest.raises(PublicAgentFailure) as caught:
        run_public_episode(
            actor=BrokenActor(),
            instruction="Inspect one item.",
            reset_observation={},
            tool_specs=(_tool(),),
            answer_schema=_answer_schema(),
            client_factory=lambda **_kwargs: Client(response),
            max_provider_turns=1,
        )
    assert caught.value.kind == "EnvironmentDefect"
    assert caught.value.code == "tool_observation_invalid"


def test_public_episode_attributes_client_initialization_to_infrastructure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "secret-test-key")

    def broken_factory(**_kwargs: Any) -> Client:
        raise RuntimeError("cannot configure secret-test-key")

    with pytest.raises(PublicAgentFailure) as caught:
        run_public_episode(
            actor=Actor(),
            instruction="Inspect one item.",
            reset_observation={},
            tool_specs=(_tool(),),
            answer_schema=_answer_schema(),
            client_factory=broken_factory,
            max_provider_turns=1,
        )

    assert caught.value.kind == "InfrastructureFailure"
    assert caught.value.code == "responses_client_init_failed"
    assert "secret-test-key" not in caught.value.details["original_message"]
