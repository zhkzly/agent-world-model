from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import fields, replace
from typing import Any

import pytest

from agent_env_foundry.agents import AgentRoute
from agent_env_foundry.episodes import EpisodeDefect, PolicySpec, PublicEpisodeInput
from agent_env_foundry.public_agent import (
    PUBLIC_AGENT_PROMPT_DIGEST,
    PUBLIC_AGENT_SYSTEM_PROMPT,
    DriverDecision,
    PublicAgentFailure,
    PublicEpisodeRun,
    ResponsesPolicyDriver,
    UnattributedPolicyDriverFailure,
    capture_public_episode,
    run_public_episode,
)


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


def _spec(turns: int = 4) -> PolicySpec:
    return PolicySpec(
        model_id="scripted-policy",
        driver_id="scripted",
        driver_version="1",
        route_id="test:scripted",
        system_prompt_digest=PUBLIC_AGENT_PROMPT_DIGEST,
        max_provider_turns=turns,
    )


VALID_CALL = ("call-1", "inspect_item", '{"item":"public-1"}')
VALID_OBSERVATION = {"ok": True, "data": {"value": "public-1"}, "error": None}


class Actor:
    def __init__(self) -> None:
        self.tools_count = 0
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def tools(self) -> tuple[dict[str, Any], ...]:
        self.tools_count += 1
        return (_tool(),)

    def invoke(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((tool_name, arguments))
        return {
            "ok": True,
            "data": {"value": arguments["item"]},
            "error": None,
        }


class ScriptedDriver:
    def __init__(
        self,
        decisions: list[DriverDecision],
        *,
        spec: PolicySpec | None = None,
        close_error: Exception | None = None,
        start_hook: Callable[[], None] | None = None,
    ) -> None:
        self._spec = spec or _spec()
        self.decisions = decisions
        self.close_error = close_error
        self.start_hook = start_hook
        self.started: list[PublicEpisodeInput] = []
        self.results: list[tuple[tuple[str, dict[str, Any]], ...]] = []
        self.close_count = 0

    @property
    def policy_spec(self) -> PolicySpec:
        return self._spec

    def start(self, public_input: PublicEpisodeInput) -> None:
        self.started.append(public_input)
        if self.start_hook is not None:
            self.start_hook()

    def next_decision(
        self,
        prior_public_results: tuple[tuple[str, dict[str, Any]], ...],
    ) -> DriverDecision:
        self.results.append(prior_public_results)
        return self.decisions.pop(0)

    def close(self) -> None:
        self.close_count += 1
        if self.close_error is not None:
            raise self.close_error


class Responses:
    def __init__(self, outcomes: list[Any]) -> None:
        self.outcomes = outcomes
        self.requests: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> dict[str, Any]:
        self.requests.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class Client:
    def __init__(self, responses: Responses, *, close_error: Exception | None = None) -> None:
        self.responses = responses
        self.close_error = close_error
        self.close_count = 0

    def close(self) -> None:
        self.close_count += 1
        if self.close_error is not None:
            raise self.close_error


class StatusFailure(RuntimeError):
    def __init__(self, status_code: int) -> None:
        super().__init__(f"remote status {status_code}")
        self.status_code = status_code


class ServiceUnavailableError(RuntimeError):
    pass


def _capture(driver: ScriptedDriver, actor: Actor | None = None):
    return capture_public_episode(
        actor=actor or Actor(),
        instruction="Inspect public-1 and report its value.",
        reset_observation={"items": ["public-1"]},
        answer_schema=_answer_schema(),
        policy_driver=driver,
    )


@pytest.mark.parametrize(
    ("raw_call", "raw_field", "raw_value"),
    [
        ((None, "inspect_item", "{}"), "raw_call_id", None),
        ((7, "inspect_item", "{}"), "raw_call_id", 7),
        (("call-1", None, "{}"), "raw_tool_name", None),
        (("call-1", ["inspect_item"], "{}"), "raw_tool_name", ["inspect_item"]),
    ],
)
def test_host_retains_malformed_call_metadata_exactly(
    raw_call: tuple[Any, Any, Any], raw_field: str, raw_value: Any
) -> None:
    actor = Actor()
    capture = _capture(ScriptedDriver([DriverDecision(calls=(raw_call,))]), actor)

    assert capture.completion is not None
    assert capture.completion.terminal_code == "malformed_tool_call"
    call = capture.to_document()["turns"][0]["calls"][0]
    assert call[raw_field] == raw_value
    assert call["dispatch_status"] == "malformed_call"
    assert actor.calls == []


@pytest.mark.parametrize(
    ("arguments", "code", "parse_status", "schema_status"),
    [
        ({"item": "public-1"}, "tool_arguments_invalid", "invalid_type", "not_checked"),
        ("{", "tool_arguments_invalid", "invalid_json", "not_checked"),
        ("[]", "tool_arguments_invalid", "non_object", "not_checked"),
        ("{}", "tool_arguments_schema_invalid", "valid", "invalid"),
    ],
)
def test_host_retains_invalid_arguments_without_dispatch(
    arguments: Any, code: str, parse_status: str, schema_status: str
) -> None:
    actor = Actor()
    call = ("call-1", "inspect_item", arguments)
    capture = _capture(ScriptedDriver([DriverDecision(calls=(call,))]), actor)
    retained = capture.to_document()["turns"][0]["calls"][0]

    assert capture.completion is not None and capture.completion.terminal_code == code
    assert retained["raw_arguments"] == arguments
    assert retained["parse_status"] == parse_status
    assert retained["schema_status"] == schema_status
    assert actor.calls == []


def test_multiple_calls_retain_success_before_later_policy_failure() -> None:
    actor = Actor()
    decision = DriverDecision(
        calls=(VALID_CALL, ("call-2", "hidden_tool", "{}")),
        usage={"input_tokens": 5},
    )
    capture = _capture(ScriptedDriver([decision]), actor)
    turn = capture.to_document()["turns"][0]

    assert capture.completion is not None
    assert capture.completion.terminal_code == "unknown_tool_call"
    assert [call["dispatch_status"] for call in turn["calls"]] == [
        "dispatched",
        "unknown_tool",
    ]
    assert turn["calls"][0]["observation"] == VALID_OBSERVATION
    assert turn["usage"] == {"input_tokens": 5}
    assert actor.calls == [("inspect_item", {"item": "public-1"})]


@pytest.mark.parametrize(
    ("decision", "code"),
    [
        (DriverDecision(), "final_answer_missing"),
        (
            DriverDecision(terminal_kind="final_answer", raw_public_terminal="{"),
            "final_answer_invalid",
        ),
        (
            DriverDecision(terminal_kind="final_answer", raw_public_terminal='{"wrong":true}'),
            "final_answer_invalid",
        ),
    ],
)
def test_final_answer_failures_after_mutation_keep_the_prior_turn(
    decision: DriverDecision, code: str
) -> None:
    driver = ScriptedDriver([DriverDecision(calls=(VALID_CALL,)), decision])
    capture = _capture(driver)

    assert capture.completion is not None and capture.completion.terminal_code == code
    assert len(capture.turns) == 2
    assert capture.turns[0].calls[0].dispatch_status == "dispatched"
    assert capture.turns[1].raw_public_terminal == decision.raw_public_terminal
    assert driver.close_count == 1


def test_refusal_and_turn_budget_are_healthy_policy_failures() -> None:
    refusal = _capture(
        ScriptedDriver(
            [
                DriverDecision(calls=(VALID_CALL,)),
                DriverDecision(terminal_kind="refusal", raw_public_terminal="cannot comply"),
            ]
        )
    )
    budget = _capture(ScriptedDriver([DriverDecision(calls=(VALID_CALL,))], spec=_spec(turns=1)))

    assert refusal.defect is None
    assert refusal.completion is not None and refusal.completion.terminal_code == "policy_refusal"
    assert refusal.turns[1].raw_public_terminal == "cannot comply"
    assert budget.defect is None
    assert budget.completion is not None
    assert budget.completion.terminal_code == "provider_turn_budget_exhausted"
    assert len(budget.turns) == 1


def test_responses_maps_raw_malformed_call_and_refusal_terminal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    malformed = Responses(
        [
            {
                "output": [
                    {
                        "type": "function_call",
                        "call_id": 7,
                        "name": ["inspect_item"],
                        "arguments": {"item": "public-1"},
                    }
                ],
                "output_text": None,
            }
        ]
    )
    malformed_capture = capture_public_episode(
        actor=Actor(),
        instruction="Inspect public-1.",
        reset_observation={},
        answer_schema=_answer_schema(),
        policy_driver=ResponsesPolicyDriver.from_route(
            AgentRoute(max_provider_turns=1),
            client_factory=lambda **_kwargs: Client(malformed),
        ),
    )
    retained = malformed_capture.to_document()["turns"][0]["calls"][0]
    assert retained["raw_call_id"] == 7
    assert retained["raw_tool_name"] == ["inspect_item"]
    assert retained["raw_arguments"] == {"item": "public-1"}

    refusal_responses = Responses(
        [
            _call_response(),
            {
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "refusal", "refusal": "cannot comply"}],
                    }
                ],
                "output_text": None,
            },
        ]
    )
    refusal_capture = capture_public_episode(
        actor=Actor(),
        instruction="Inspect public-1.",
        reset_observation={},
        answer_schema=_answer_schema(),
        policy_driver=ResponsesPolicyDriver.from_route(
            AgentRoute(max_provider_turns=2),
            client_factory=lambda **_kwargs: Client(refusal_responses),
        ),
    )
    assert refusal_capture.completion is not None
    assert refusal_capture.completion.terminal_code == "policy_refusal"
    assert refusal_capture.turns[1].raw_public_terminal == "cannot comply"


@pytest.mark.parametrize("output_text", ["", " \n"])
def test_responses_blank_output_text_with_calls_is_not_a_terminal(
    monkeypatch: pytest.MonkeyPatch, output_text: str
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    first = _call_response()
    first["output_text"] = output_text
    responses = Responses([first, _final_response()])

    capture = capture_public_episode(
        actor=Actor(),
        instruction="Inspect public-1.",
        reset_observation={},
        answer_schema=_answer_schema(),
        policy_driver=ResponsesPolicyDriver.from_route(
            AgentRoute(max_provider_turns=2),
            client_factory=lambda **_kwargs: Client(responses),
        ),
    )

    assert capture.defect is None
    assert capture.completion is not None
    assert capture.completion.terminal_kind == "completed"
    assert [turn.raw_public_terminal for turn in capture.turns] == [None, '{"value":"public-1"}']
    assert capture.turns[0].calls[0].dispatch_status == "dispatched"
    assert len(responses.requests) == 2


@pytest.mark.parametrize(
    ("failure", "owner"),
    [
        (StatusFailure(429), "provider"),
        (StatusFailure(503), "provider"),
        (ServiceUnavailableError("declared outage"), "provider"),
        (StatusFailure(400), "evidence"),
        (StatusFailure(422), "evidence"),
        (StatusFailure(401), "infrastructure"),
        (OSError("local transport failed"), "infrastructure"),
    ],
)
def test_responses_request_defects_keep_prefix_and_have_exact_owner(
    monkeypatch: pytest.MonkeyPatch, failure: Exception, owner: str
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    responses = Responses([_call_response(), failure])
    driver = ResponsesPolicyDriver.from_route(
        AgentRoute(max_provider_turns=2),
        client_factory=lambda **_kwargs: Client(responses),
    )
    actor = Actor()
    capture = capture_public_episode(
        actor=actor,
        instruction="Inspect public-1.",
        reset_observation={},
        answer_schema=_answer_schema(),
        policy_driver=driver,
    )

    assert capture.defect is not None and capture.defect.owner == owner
    assert capture.defect.code == "responses_request_failed"
    assert capture.completion is None
    assert capture.turns[0].calls[0].observation == VALID_OBSERVATION
    assert actor.calls == [("inspect_item", {"item": "public-1"})]


def test_unattributed_request_or_envelope_blocks_instead_of_guessing_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    for outcome in (
        RuntimeError("unknown"),
        {},
        {"output": {"wrong": True}},
    ):
        driver = ResponsesPolicyDriver.from_route(
            AgentRoute(max_provider_turns=1),
            client_factory=lambda current=outcome, **_kwargs: Client(Responses([current])),
        )
        with pytest.raises(UnattributedPolicyDriverFailure):
            capture_public_episode(
                actor=Actor(),
                instruction="Inspect public-1.",
                reset_observation={},
                answer_schema=_answer_schema(),
                policy_driver=driver,
            )


def test_completion_survives_usage_and_close_sealing_defects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    usage_driver = ResponsesPolicyDriver.from_route(
        AgentRoute(max_provider_turns=2),
        client_factory=lambda **_kwargs: Client(
            Responses([_call_response(), _final_response(usage=object())])
        ),
    )
    usage_capture = capture_public_episode(
        actor=Actor(),
        instruction="Inspect public-1.",
        reset_observation={},
        answer_schema=_answer_schema(),
        policy_driver=usage_driver,
    )
    close_capture = _capture(
        ScriptedDriver(
            [
                DriverDecision(calls=(VALID_CALL,)),
                DriverDecision(
                    terminal_kind="final_answer",
                    raw_public_terminal='{"value":"public-1"}',
                ),
            ],
            close_error=OSError("close failed"),
        )
    )

    assert usage_capture.completion is not None
    assert usage_capture.completion.terminal_kind == "completed"
    assert usage_capture.defect == EpisodeDefect(
        "evidence", "provider_usage_invalid", "policy_driver_usage"
    )
    assert close_capture.completion is not None
    assert close_capture.completion.terminal_kind == "completed"
    assert close_capture.defect == EpisodeDefect(
        "infrastructure", "policy_driver_close_failed", "policy_driver_close"
    )


def test_responses_request_matches_policy_and_private_reasoning_is_not_captured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    responses = Responses(
        [
            _call_response(include_reasoning=True),
            _final_response(as_message=True, include_reasoning=True),
        ]
    )
    client = Client(responses)
    factory_calls: list[dict[str, Any]] = []

    def factory(**kwargs: Any) -> Client:
        factory_calls.append(kwargs)
        return client

    driver = ResponsesPolicyDriver.from_route(
        AgentRoute(max_provider_turns=2), client_factory=factory
    )
    actor = Actor()
    capture = capture_public_episode(
        actor=actor,
        instruction="Inspect public-1.",
        reset_observation={"items": ["public-1"]},
        answer_schema=_answer_schema(),
        policy_driver=driver,
    )

    assert capture.completion is not None and capture.completion.terminal_kind == "completed"
    assert factory_calls == [
        {"api_key": "test-key", "base_url": "http://127.0.0.1:8317/v1", "max_retries": 2}
    ]
    assert responses.requests[0]["model"] == driver.policy_spec.model_id
    assert responses.requests[0]["instructions"] == capture.public_input.system_prompt
    assert (
        responses.requests[0]["tools"][0]["description"]
        == (capture.public_input.to_document()["tool_specs"][0]["description"])
    )
    assert responses.requests[0]["tool_choice"] == "required"
    assert responses.requests[1]["tool_choice"] == "auto"
    assert responses.requests[1]["input"][-1]["call_id"] == "call-1"
    assert "reasoning" not in json.dumps(capture.to_document())
    assert actor.tools_count == 1
    assert client.close_count == 1

    reused = capture_public_episode(
        actor=Actor(),
        instruction="Inspect public-1.",
        reset_observation={},
        answer_schema=_answer_schema(),
        policy_driver=driver,
    )
    assert reused.defect == EpisodeDefect("evidence", "policy_driver_reused", "policy_driver_start")
    assert len(responses.requests) == 2
    assert client.close_count == 1


def test_responses_request_normalizes_mechanical_zero_argument_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    tool = _tool()
    tool["input_schema"] = {"type": "object", "additionalProperties": False}
    responses = Responses([_call_response()])
    driver = ResponsesPolicyDriver.from_route(
        AgentRoute(),
        client_factory=lambda **_kwargs: Client(responses),
    )
    public_input = PublicEpisodeInput(
        PUBLIC_AGENT_SYSTEM_PROMPT,
        "List public items.",
        {},
        (tool,),
        _answer_schema(),
    )

    driver.start(public_input)
    driver.next_decision(())
    parameters = responses.requests[0]["tools"][0]["parameters"]

    assert parameters == {
        "type": "object",
        "additionalProperties": False,
        "properties": {},
        "required": [],
    }


def test_responses_wire_projects_collection_consts_without_changing_host_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    responses = Responses([_call_response()])
    driver = ResponsesPolicyDriver.from_route(
        AgentRoute(), client_factory=lambda **_kwargs: Client(responses)
    )
    answer_schema = {
        "type": "object",
        "properties": {"paths": {"const": ["README.md"]}, "clean": {"const": True}},
        "required": ["paths", "clean"],
        "additionalProperties": False,
    }
    public_input = PublicEpisodeInput(
        PUBLIC_AGENT_SYSTEM_PROMPT,
        "Inspect state.",
        {},
        (_tool(),),
        answer_schema,
    )

    driver.start(public_input)
    driver.next_decision(())

    wire = responses.requests[0]["text"]["format"]["schema"]["properties"]
    assert wire["paths"] == {"type": "array", "items": {"type": "string"}}
    assert wire["clean"] == {"const": True, "type": "boolean"}
    assert answer_schema["properties"]["paths"] == {"const": ["README.md"]}


def test_responses_wire_closes_nested_object_without_changing_host_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    responses = Responses([_call_response()])
    driver = ResponsesPolicyDriver.from_route(
        AgentRoute(), client_factory=lambda **_kwargs: Client(responses)
    )
    answer_schema = {
        "type": "object",
        "properties": {
            "record": {
                "type": "object",
                "properties": {"id": {"type": "string"}},
                "required": ["id"],
                "additionalProperties": True,
            }
        },
        "required": ["record"],
        "additionalProperties": False,
    }
    public_input = PublicEpisodeInput(
        PUBLIC_AGENT_SYSTEM_PROMPT,
        "Inspect state.",
        {},
        (_tool(),),
        answer_schema,
    )

    driver.start(public_input)
    driver.next_decision(())

    wire_record = responses.requests[0]["text"]["format"]["schema"]["properties"]["record"]
    assert wire_record["additionalProperties"] is False
    assert answer_schema["properties"]["record"]["additionalProperties"] is True


def test_run_public_episode_attributes_bad_request_to_framework(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    responses = Responses([StatusFailure(400)])

    with pytest.raises(PublicAgentFailure) as caught:
        run_public_episode(
            actor=Actor(),
            instruction="Inspect public-1.",
            reset_observation={},
            tool_specs=(_tool(),),
            answer_schema=_answer_schema(),
            client_factory=lambda **_kwargs: Client(responses),
            max_provider_turns=1,
        )

    assert caught.value.kind == "FrameworkDefect"
    assert caught.value.code == "responses_request_failed"


def test_host_rejects_duplicate_call_ids() -> None:
    duplicate = _capture(
        ScriptedDriver(
            [DriverDecision(calls=(VALID_CALL, ("call-1", "inspect_item", '{"item":"x"}')))]
        )
    )
    assert duplicate.completion is not None
    assert duplicate.completion.terminal_code == "duplicate_tool_call_id"
    assert [call.dispatch_status for call in duplicate.turns[0].calls] == [
        "dispatched",
        "duplicate_call_id",
    ]


def test_prompt_authority_fails_before_first_provider_call() -> None:
    bad_spec_driver = ScriptedDriver([], spec=replace(_spec(), system_prompt_digest="0" * 64))
    with pytest.raises(ValueError, match="prompt digest"):
        _capture(bad_spec_driver)
    assert bad_spec_driver.started == []
    assert bad_spec_driver.close_count == 1


def test_capture_preserves_actor_tools_infrastructure_owner() -> None:
    class ToolsTransportFailure(RuntimeError):
        kind = "InfrastructureFailure"

    class BrokenToolsActor(Actor):
        def tools(self) -> tuple[dict[str, Any], ...]:
            raise ToolsTransportFailure("actor transport unavailable")

    driver = ScriptedDriver([])
    with pytest.raises(PublicAgentFailure) as caught:
        capture_public_episode(
            actor=BrokenToolsActor(),
            instruction="Inspect one item.",
            reset_observation={},
            answer_schema=_answer_schema(),
            policy_driver=driver,
        )

    assert caught.value.kind == "InfrastructureFailure"
    assert caught.value.code == "actor_tool_catalog_invalid"
    assert driver.close_count == 1


def test_capture_attributes_an_invalid_actor_tool_catalog_to_environment() -> None:
    class BrokenCatalogActor(Actor):
        def tools(self) -> tuple[dict[str, Any], ...]:
            return ({"name": "incomplete"},)

    driver = ScriptedDriver([])
    with pytest.raises(PublicAgentFailure) as caught:
        capture_public_episode(
            actor=BrokenCatalogActor(),
            instruction="Inspect one item.",
            reset_observation={},
            answer_schema=_answer_schema(),
            policy_driver=driver,
        )

    assert caught.value.kind == "EnvironmentDefect"
    assert caught.value.code == "actor_tool_catalog_invalid"
    assert driver.close_count == 1


def test_host_uses_frozen_tool_and_answer_schema_snapshots() -> None:
    class AliasedActor(Actor):
        def __init__(self) -> None:
            super().__init__()
            self.tool = _tool()

        def tools(self) -> tuple[dict[str, Any], ...]:
            self.tools_count += 1
            return (self.tool,)

    actor = AliasedActor()
    answer_schema = _answer_schema()

    def mutate_caller_aliases() -> None:
        actor.tool["input_schema"]["required"] = ["different"]
        answer_schema["required"] = ["different"]

    driver = ScriptedDriver(
        [
            DriverDecision(calls=(VALID_CALL,)),
            DriverDecision(
                terminal_kind="final_answer",
                raw_public_terminal='{"value":"public-1"}',
            ),
        ],
        start_hook=mutate_caller_aliases,
    )
    capture = capture_public_episode(
        actor=actor,
        instruction="Inspect public-1.",
        reset_observation={},
        answer_schema=answer_schema,
        policy_driver=driver,
    )

    assert capture.completion is not None
    assert capture.completion.terminal_kind == "completed"
    assert capture.turns[0].calls[0].dispatch_status == "dispatched"
    assert actor.tools_count == 1


def test_success_wrapper_preserves_exact_s2_projection_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    responses = Responses([_call_response(), _final_response()])
    episode = run_public_episode(
        actor=Actor(),
        instruction="Inspect public-1.",
        reset_observation={},
        tool_specs=(_tool(),),
        answer_schema=_answer_schema(),
        client_factory=lambda **_kwargs: Client(responses),
        max_provider_turns=2,
    )

    assert isinstance(episode, PublicEpisodeRun)
    assert {field.name for field in fields(episode)} == {
        "trace",
        "final_answer",
        "provider_turns",
        "usage",
    }
    assert episode.final_answer == {"value": "public-1"}
    assert [event.to_document() for event in episode.trace] == [
        {
            "seq": 1,
            "tool_name": "inspect_item",
            "arguments": {"item": "public-1"},
            "observation": VALID_OBSERVATION,
        }
    ]
    json.dumps(
        {
            "trace": [event.to_document() for event in episode.trace],
            "final_answer": episode.final_answer,
            "provider_turns": episode.provider_turns,
            "usage": episode.usage,
        },
        allow_nan=False,
    )


def _call_response(*, include_reasoning: bool = False) -> dict[str, Any]:
    output: list[dict[str, Any]] = []
    if include_reasoning:
        output.append({"type": "reasoning", "summary": [{"text": "private"}]})
    output.append(
        {
            "type": "function_call",
            "call_id": "call-1",
            "name": "inspect_item",
            "arguments": '{"item":"public-1"}',
        }
    )
    return {"output": output, "output_text": None, "usage": {"input_tokens": 3}}


def _final_response(
    *,
    usage: Any = None,
    as_message: bool = False,
    include_reasoning: bool = False,
) -> dict[str, Any]:
    answer = '{"value":"public-1"}'
    output: list[dict[str, Any]] = []
    if include_reasoning:
        output.append({"type": "reasoning", "summary": [{"text": "private"}]})
    if as_message:
        output.append(
            {
                "type": "message",
                "content": [{"type": "output_text", "text": answer}],
            }
        )
    return {
        "output": output,
        "output_text": answer,
        "usage": {"output_tokens": 2} if usage is None else usage,
    }
