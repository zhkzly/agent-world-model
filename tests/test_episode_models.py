from __future__ import annotations

import hashlib
from dataclasses import fields, replace

import pytest

from agent_env_foundry.environment import ToolSpec
from agent_env_foundry.episodes import (
    EpisodeDefect,
    EpisodeRequest,
    EpisodeToolCall,
    PolicyCompletion,
    PolicySpec,
    PolicyTurn,
    PublicEpisodeCapture,
    PublicEpisodeInput,
    RewardOutcome,
)
from agent_env_foundry.jsonvalue import is_json_object, is_json_value
from agent_env_foundry.release import canonical_bytes

DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
DIGEST_C = "c" * 64
DIGEST_D = "d" * 64


def _policy() -> PolicySpec:
    return PolicySpec(
        model_id="gpt-5.6-luna",
        driver_id="responses",
        driver_version="1",
        route_id="openai:primary",
        system_prompt_digest=DIGEST_A,
        max_provider_turns=12,
    )


def _tool_spec() -> ToolSpec:
    return {
        "name": "inspect_item",
        "description": "Inspect one public item.",
        "input_schema": {
            "type": "object",
            "properties": {
                "selector": {
                    "type": "object",
                    "properties": {"tags": {"type": "array", "items": {"type": "string"}}},
                    "required": ["tags"],
                    "additionalProperties": False,
                }
            },
            "required": ["selector"],
            "additionalProperties": False,
        },
        "output_schema": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
            "additionalProperties": False,
        },
    }


def _public_input() -> PublicEpisodeInput:
    return PublicEpisodeInput(
        system_prompt="Use only the public tools.",
        instruction="Inspect the selected item.",
        reset_observation={"items": [{"name": "alpha", "tags": ["hot", "new"]}]},
        tool_specs=(_tool_spec(),),
        answer_schema={
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
            "additionalProperties": False,
        },
    )


def _completion() -> PolicyCompletion:
    return PolicyCompletion(
        terminal_kind="completed",
        final_answer={"name": "alpha"},
        terminal_code=None,
    )


def test_policy_spec_is_a_closed_non_secret_canonical_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy = _policy()

    assert {field.name for field in fields(PolicySpec)} == {
        "model_id",
        "driver_id",
        "driver_version",
        "route_id",
        "system_prompt_digest",
        "max_provider_turns",
    }
    assert policy.to_document() == {
        "format": "policy-spec/1",
        "model_id": "gpt-5.6-luna",
        "driver_id": "responses",
        "driver_version": "1",
        "route_id": "openai:primary",
        "system_prompt_digest": DIGEST_A,
        "max_provider_turns": 12,
    }
    assert policy.policy_id == hashlib.sha256(canonical_bytes(policy.to_document())).hexdigest()
    assert replace(policy, route_id="openai:secondary").policy_id != policy.policy_id
    monkeypatch.setenv("OPENAI_API_KEY", "old-secret")
    before_rotation = _policy().policy_id
    monkeypatch.setenv("OPENAI_API_KEY", "rotated-secret")
    assert _policy().policy_id == before_rotation

    policy_fields = {field.name: getattr(policy, field.name) for field in fields(PolicySpec)}
    for forbidden in (
        {"api_key": "secret"},
        {"auth_headers": {"Authorization": "Bearer secret"}},
        {"base_url": "https://secret@example.test/v1"},
        {"output_path": "/tmp/episode"},
        {"generation_config": {"temperature": 1}},
    ):
        with pytest.raises(TypeError):
            PolicySpec(**{**policy_fields, **forbidden})


def test_policy_spec_has_no_producerless_checkpoint_slot() -> None:
    assert "checkpoint_id" not in {field.name for field in fields(PolicySpec)}


@pytest.mark.parametrize(
    "route_id",
    (
        "https://user:secret@example.test/v1?api_key=secret",
        "/tmp/provider-route",
        "OpenAI Primary",
        DIGEST_B,
    ),
)
def test_policy_route_id_rejects_secret_path_and_opaque_digest_shapes(route_id: str) -> None:
    with pytest.raises(ValueError, match="route_id"):
        replace(_policy(), route_id=route_id)


def test_episode_request_is_one_logical_rollout_without_attempt_or_upstream_evidence() -> None:
    request = EpisodeRequest(
        release_id=DIGEST_A,
        task_pack_id=DIGEST_B,
        task_id=DIGEST_C,
        policy_id=DIGEST_D,
        rollout_index=1,
    )

    assert {field.name for field in fields(EpisodeRequest)} == {
        "release_id",
        "task_pack_id",
        "task_id",
        "policy_id",
        "rollout_index",
    }
    assert request.to_document() == {
        "format": "episode-request/1",
        "release_id": DIGEST_A,
        "task_pack_id": DIGEST_B,
        "task_id": DIGEST_C,
        "policy_id": DIGEST_D,
        "rollout_index": 1,
    }
    assert request.request_id == hashlib.sha256(canonical_bytes(request.to_document())).hexdigest()

    forbidden_fields = {
        "attempt_index",
        "retry_index",
        "output_path",
        "credential",
        "witness_id",
        "assessment_id",
        "corpus_id",
    }
    assert forbidden_fields.isdisjoint(field.name for field in fields(EpisodeRequest))
    for bad_index in (0, -1, 1.0, True):
        with pytest.raises(ValueError, match="rollout_index"):
            replace(request, rollout_index=bad_index)  # type: ignore[arg-type]


def test_public_input_snapshots_deep_json_and_returns_fresh_documents() -> None:
    reset = {"items": [{"name": "alpha", "tags": ["hot", "new"]}]}
    tool = _tool_spec()
    answer_schema = {
        "type": "object",
        "properties": {"answer": {"type": "object", "properties": {}}},
        "required": ["answer"],
        "additionalProperties": False,
    }
    public_input = PublicEpisodeInput(
        "Use only public facts.",
        "Inspect the item.",
        reset,
        (tool,),
        answer_schema,
    )
    expected = public_input.to_document()

    reset["items"][0]["name"] = "caller-mutated"
    tool["input_schema"]["properties"]["selector"]["required"].append("hidden")
    answer_schema["properties"]["answer"]["description"] = "caller-mutated"
    assert public_input.to_document() == expected

    emitted = public_input.to_document()
    emitted["reset_observation"]["items"][0]["tags"].append("emitted-mutation")
    emitted["tool_specs"][0]["input_schema"]["required"].append("emitted-mutation")
    assert public_input.to_document() == expected


def test_contract_json_fields_remain_structural_json_values() -> None:
    public_input = _public_input()
    call = EpisodeToolCall(
        "call-1",
        "inspect_item",
        "call-1",
        "inspect_item",
        '{"selector":{"tags":["hot"]}}',
        {"selector": {"tags": ["hot"]}},
        "valid",
        "valid",
        "dispatched",
        {"ok": True, "data": {"name": "alpha"}},
    )
    turn = PolicyTurn(1, (call,), None, {"input_tokens": 3})

    assert is_json_value(public_input.reset_observation)
    assert is_json_object(public_input.answer_schema)
    assert all(is_json_object(tool) for tool in public_input.tool_specs)
    assert is_json_value(call.raw_call_id)
    assert is_json_value(call.raw_tool_name)
    assert is_json_object(call.parsed_arguments)
    assert is_json_object(call.observation)
    assert is_json_object(turn.usage)


def test_public_input_rejects_non_json_and_non_tool_contract_content() -> None:
    with pytest.raises(ValueError, match="reset_observation"):
        replace(_public_input(), reset_observation={"bad": object()})
    with pytest.raises(ValueError, match="answer_schema"):
        replace(_public_input(), answer_schema={"type": "array"})
    with pytest.raises(ValueError, match="ToolSpec"):
        PublicEpisodeInput(
            "Prompt.",
            "Instruction.",
            {},
            ({**_tool_spec(), "unexpected": True},),
            _public_input().to_document()["answer_schema"],
        )


def test_tool_call_preserves_raw_malformed_material_and_deep_snapshots() -> None:
    raw_call_id = {"unexpected": [1, 2]}
    raw_tool_name = ["inspect_item", {"bad": True}]
    parsed_arguments = {"selector": {"tags": ["hot"]}}
    observation = {
        "ok": True,
        "data": {"items": [{"name": "alpha"}]},
        "error": None,
    }
    call = EpisodeToolCall(
        raw_call_id=raw_call_id,
        raw_tool_name=raw_tool_name,
        call_id=None,
        tool_name=None,
        raw_arguments='{"selector":',
        parsed_arguments=parsed_arguments,
        parse_status="invalid_json",
        schema_status="not_checked",
        dispatch_status="not_dispatched",
        observation=observation,
    )
    expected = call.to_document()

    raw_call_id["unexpected"].append(3)
    raw_tool_name[1]["bad"] = False
    parsed_arguments["selector"]["tags"].append("caller-mutated")
    observation["data"]["items"][0]["name"] = "caller-mutated"

    assert call.to_document() == expected
    assert call.to_document()["raw_call_id"] == {"unexpected": [1, 2]}
    assert call.to_document()["raw_tool_name"] == ["inspect_item", {"bad": True}]
    assert call.to_document()["raw_arguments"] == '{"selector":'
    emitted = call.to_document()
    emitted["raw_call_id"]["unexpected"].append("emitted-mutation")
    emitted["observation"]["data"]["items"][0]["name"] = "emitted-mutation"
    assert call.to_document() == expected


def test_turn_capture_keeps_completion_and_one_primary_defect() -> None:
    usage = {"input_tokens": 10, "details": {"cached": [2]}}
    terminal = {"kind": "message", "parts": [{"text": "done"}]}
    turn = PolicyTurn(
        turn_index=1,
        calls=(),
        raw_public_terminal=terminal,
        usage=usage,
    )
    completion = _completion()
    defect = EpisodeDefect(owner="infrastructure", code="driver_close_failed", phase="capture")
    capture = PublicEpisodeCapture(
        public_input=_public_input(),
        turns=(turn,),
        completion=completion,
        defect=defect,
    )
    expected = capture.to_document()

    terminal["parts"][0]["text"] = "caller-mutated"
    usage["details"]["cached"].append(99)
    assert capture.completion is completion
    assert capture.defect is defect
    assert capture.to_document() == expected
    assert capture.to_document()["completion"]["terminal_kind"] == "completed"
    assert capture.to_document()["defect"] == {
        "owner": "infrastructure",
        "code": "driver_close_failed",
        "phase": "capture",
    }
    emitted = capture.to_document()
    emitted["turns"][0]["usage"]["details"]["cached"].append("emitted-mutation")
    emitted["completion"]["final_answer"]["name"] = "emitted-mutation"
    assert capture.to_document() == expected

    with pytest.raises(ValueError, match="completion or defect"):
        replace(capture, completion=None, defect=None)
    with pytest.raises(ValueError, match="turn_index"):
        replace(turn, turn_index=0)
    with pytest.raises(ValueError, match="contiguous"):
        replace(capture, turns=(replace(turn, turn_index=2),))


def test_policy_completion_is_only_completed_or_policy_failure() -> None:
    answer = {"answer": {"parts": ["ok"]}}
    completed = PolicyCompletion("completed", answer, None)
    expected = {
        "terminal_kind": "completed",
        "final_answer": {"answer": {"parts": ["ok"]}},
        "terminal_code": None,
    }
    answer["answer"]["parts"].append("caller-mutated")
    assert completed.to_document() == expected
    emitted = completed.to_document()
    emitted["final_answer"]["answer"]["parts"].append("emitted-mutation")
    assert completed.to_document() == expected
    assert PolicyCompletion("policy_failure", None, "final_answer_invalid").to_document() == {
        "terminal_kind": "policy_failure",
        "final_answer": None,
        "terminal_code": "final_answer_invalid",
    }

    with pytest.raises(ValueError, match="terminal_kind"):
        PolicyCompletion("infrastructure_failure", None, "route_failed")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="completed"):
        PolicyCompletion("completed", None, None)
    with pytest.raises(ValueError, match="policy_failure"):
        PolicyCompletion("policy_failure", {"answer": "invalid"}, "invalid")


def test_defect_owner_set_is_closed_and_provider_is_not_infrastructure() -> None:
    owners = {
        "provider",
        "infrastructure",
        "environment",
        "task_artifact",
        "checker",
        "evidence",
    }

    defects = {
        owner: EpisodeDefect(owner=owner, code=f"{owner}_failed", phase="capture")
        for owner in owners
    }
    assert set(defects) == owners
    assert defects["provider"].owner != defects["infrastructure"].owner
    with pytest.raises(ValueError, match="owner"):
        EpisodeDefect("policy", "bad_answer", "capture")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("disposition", "reward", "owner", "code"),
    (
        ("verified_success", 1.0, None, None),
        ("verified_failure", 0.0, None, None),
        ("abstain", None, "provider", "remote_429"),
        ("abstain", None, "infrastructure", "credential_missing"),
    ),
)
def test_reward_outcome_accepts_only_the_exact_truth_table(
    disposition: str,
    reward: float | None,
    owner: str | None,
    code: str | None,
) -> None:
    outcome = RewardOutcome(disposition, reward, owner, code)  # type: ignore[arg-type]
    assert outcome.to_document() == {
        "disposition": disposition,
        "reward": reward,
        "abstain_owner": owner,
        "abstain_code": code,
    }


@pytest.mark.parametrize(
    ("disposition", "reward", "owner", "code"),
    (
        ("verified_success", 0.0, None, None),
        ("verified_success", 1, None, None),
        ("verified_success", 1.0, "provider", "remote_429"),
        ("verified_failure", 1.0, None, None),
        ("verified_failure", None, None, None),
        ("abstain", 0.0, "provider", "remote_429"),
        ("abstain", None, None, "remote_429"),
        ("abstain", None, "provider", None),
        ("abstain", None, "policy", "bad_answer"),
    ),
)
def test_reward_outcome_rejects_every_crossed_combination(
    disposition: str,
    reward: float | int | None,
    owner: str | None,
    code: str | None,
) -> None:
    with pytest.raises(ValueError):
        RewardOutcome(disposition, reward, owner, code)  # type: ignore[arg-type]
