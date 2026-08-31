"""Leaf contracts for S3 public policy Episodes and base reward."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Literal, cast

from agent_env_foundry.environment import (
    JSONObject,
    JSONValue,
    ToolSpec,
    validate_tool_catalog,
)
from agent_env_foundry.jsonvalue import is_json_object, is_json_value
from agent_env_foundry.release import canonical_bytes
from agent_env_foundry.schema import require_object_root

type DefectOwner = Literal[
    "provider",
    "infrastructure",
    "environment",
    "task_artifact",
    "semantics",
    "verifier",
    "evidence",
]
type _CompletionKind = Literal["completed", "policy_failure"]
type _RewardDisposition = Literal["verified_success", "verified_failure", "abstain"]

_DEFECT_OWNERS = frozenset(
    {
        "provider",
        "infrastructure",
        "environment",
        "task_artifact",
        "semantics",
        "verifier",
        "evidence",
    }
)
_COMPLETION_KINDS = frozenset({"completed", "policy_failure"})
_REWARD_DISPOSITIONS = frozenset({"verified_success", "verified_failure", "abstain"})
_HEX = frozenset("0123456789abcdef")
_ROUTE_ID = re.compile(r"[a-z0-9](?:[a-z0-9._:-]*[a-z0-9])?")


@dataclass(frozen=True, slots=True)
class PolicySpec:
    model_id: str
    driver_id: str
    driver_version: str
    route_id: str
    system_prompt_digest: str
    max_provider_turns: int

    def __post_init__(self) -> None:
        _text(self.model_id, "model_id")
        _text(self.driver_id, "driver_id")
        _text(self.driver_version, "driver_version")
        _route_id(self.route_id)
        _digest(self.system_prompt_digest, "system_prompt_digest")
        _positive(self.max_provider_turns, "max_provider_turns")

    @property
    def policy_id(self) -> str:
        return _document_digest(self.to_document())

    def to_document(self) -> JSONObject:
        return {
            "format": "policy-spec/1",
            "model_id": self.model_id,
            "driver_id": self.driver_id,
            "driver_version": self.driver_version,
            "route_id": self.route_id,
            "system_prompt_digest": self.system_prompt_digest,
            "max_provider_turns": self.max_provider_turns,
        }


@dataclass(frozen=True, slots=True)
class EpisodeRequest:
    release_id: str
    task_pack_id: str
    task_id: str
    policy_id: str
    rollout_index: int

    def __post_init__(self) -> None:
        for value, role in (
            (self.release_id, "release_id"),
            (self.task_pack_id, "task_pack_id"),
            (self.task_id, "task_id"),
            (self.policy_id, "policy_id"),
        ):
            _digest(value, role)
        _positive(self.rollout_index, "rollout_index")

    @property
    def request_id(self) -> str:
        return _document_digest(self.to_document())

    def to_document(self) -> JSONObject:
        return {
            "format": "episode-request/1",
            "release_id": self.release_id,
            "task_pack_id": self.task_pack_id,
            "task_id": self.task_id,
            "policy_id": self.policy_id,
            "rollout_index": self.rollout_index,
        }


@dataclass(frozen=True, slots=True)
class PublicEpisodeInput:
    system_prompt: str
    instruction: str
    reset_observation: JSONValue
    tool_specs: tuple[ToolSpec, ...]
    answer_schema: JSONObject

    def __post_init__(self) -> None:
        _text(self.system_prompt, "system_prompt")
        _text(self.instruction, "instruction")
        reset_observation = _snapshot_json(self.reset_observation, "reset_observation")
        tool_specs = _snapshot_tool_specs(self.tool_specs)
        answer_schema = _normal_object(self.answer_schema, "answer_schema")
        try:
            require_object_root(answer_schema, role="public answer_schema")
        except Exception as exc:
            raise ValueError(str(exc)) from exc
        object.__setattr__(self, "reset_observation", reset_observation)
        object.__setattr__(self, "tool_specs", tool_specs)
        object.__setattr__(self, "answer_schema", answer_schema)

    def to_document(self) -> JSONObject:
        return {
            "system_prompt": self.system_prompt,
            "instruction": self.instruction,
            "reset_observation": _copy_json(self.reset_observation),
            "tool_specs": [_copy_object(cast(JSONObject, spec)) for spec in self.tool_specs],
            "answer_schema": _copy_object(self.answer_schema),
        }


@dataclass(frozen=True, slots=True)
class EpisodeToolCall:
    raw_call_id: JSONValue | None
    raw_tool_name: JSONValue | None
    call_id: str | None
    tool_name: str | None
    raw_arguments: JSONValue | str | None
    parsed_arguments: JSONObject | None
    parse_status: str
    schema_status: str
    dispatch_status: str
    observation: JSONObject | None

    def __post_init__(self) -> None:
        if self.call_id is not None:
            _text(self.call_id, "call_id")
        if self.tool_name is not None:
            _text(self.tool_name, "tool_name")
        for value, role in (
            (self.parse_status, "parse_status"),
            (self.schema_status, "schema_status"),
            (self.dispatch_status, "dispatch_status"),
        ):
            _text(value, role)
        object.__setattr__(self, "raw_call_id", _snapshot_json(self.raw_call_id, "raw_call_id"))
        object.__setattr__(
            self,
            "raw_tool_name",
            _snapshot_json(self.raw_tool_name, "raw_tool_name"),
        )
        object.__setattr__(
            self,
            "raw_arguments",
            _snapshot_json(self.raw_arguments, "raw_arguments"),
        )
        object.__setattr__(
            self,
            "parsed_arguments",
            _snapshot_optional_object(self.parsed_arguments, "parsed_arguments"),
        )
        object.__setattr__(
            self,
            "observation",
            _snapshot_optional_object(self.observation, "observation"),
        )

    def to_document(self) -> JSONObject:
        return {
            "raw_call_id": _copy_json(self.raw_call_id),
            "raw_tool_name": _copy_json(self.raw_tool_name),
            "call_id": self.call_id,
            "tool_name": self.tool_name,
            "raw_arguments": _copy_json(self.raw_arguments),
            "parsed_arguments": _copy_optional_object(self.parsed_arguments),
            "parse_status": self.parse_status,
            "schema_status": self.schema_status,
            "dispatch_status": self.dispatch_status,
            "observation": _copy_optional_object(self.observation),
        }


@dataclass(frozen=True, slots=True)
class PolicyTurn:
    turn_index: int
    calls: tuple[EpisodeToolCall, ...]
    raw_public_terminal: JSONValue | str | None
    usage: JSONObject | None

    def __post_init__(self) -> None:
        _positive(self.turn_index, "turn_index")
        if not isinstance(self.calls, tuple) or any(
            not isinstance(item, EpisodeToolCall) for item in self.calls
        ):
            raise ValueError("calls must be a tuple of EpisodeToolCall values")
        object.__setattr__(
            self,
            "raw_public_terminal",
            _snapshot_json(self.raw_public_terminal, "raw_public_terminal"),
        )
        object.__setattr__(
            self,
            "usage",
            _snapshot_optional_object(self.usage, "usage"),
        )

    def to_document(self) -> JSONObject:
        return {
            "turn_index": self.turn_index,
            "calls": [item.to_document() for item in self.calls],
            "raw_public_terminal": _copy_json(self.raw_public_terminal),
            "usage": _copy_optional_object(self.usage),
        }


@dataclass(frozen=True, slots=True)
class PolicyCompletion:
    terminal_kind: _CompletionKind
    final_answer: JSONObject | None
    terminal_code: str | None

    def __post_init__(self) -> None:
        if self.terminal_kind not in _COMPLETION_KINDS:
            raise ValueError("terminal_kind must be completed or policy_failure")
        if self.terminal_kind == "completed":
            if self.final_answer is None or self.terminal_code is not None:
                raise ValueError("completed requires a final_answer and no terminal_code")
        elif self.final_answer is not None or self.terminal_code is None:
            raise ValueError("policy_failure requires only a terminal_code")
        if self.terminal_code is not None:
            _text(self.terminal_code, "terminal_code")
        object.__setattr__(
            self,
            "final_answer",
            _snapshot_optional_object(self.final_answer, "final_answer"),
        )

    def to_document(self) -> JSONObject:
        return {
            "terminal_kind": self.terminal_kind,
            "final_answer": _copy_optional_object(self.final_answer),
            "terminal_code": self.terminal_code,
        }


@dataclass(frozen=True, slots=True)
class EpisodeDefect:
    owner: DefectOwner
    code: str
    phase: str

    def __post_init__(self) -> None:
        if self.owner not in _DEFECT_OWNERS:
            raise ValueError("defect owner is invalid")
        _text(self.code, "defect code")
        _text(self.phase, "defect phase")

    def to_document(self) -> JSONObject:
        return {"owner": self.owner, "code": self.code, "phase": self.phase}


@dataclass(frozen=True, slots=True)
class PublicEpisodeCapture:
    public_input: PublicEpisodeInput
    turns: tuple[PolicyTurn, ...]
    completion: PolicyCompletion | None
    defect: EpisodeDefect | None

    def __post_init__(self) -> None:
        if not isinstance(self.public_input, PublicEpisodeInput):
            raise ValueError("public_input must be a PublicEpisodeInput")
        if not isinstance(self.turns, tuple) or any(
            not isinstance(item, PolicyTurn) for item in self.turns
        ):
            raise ValueError("turns must be a tuple of PolicyTurn values")
        expected_indices = tuple(range(1, len(self.turns) + 1))
        if tuple(item.turn_index for item in self.turns) != expected_indices:
            raise ValueError("turn_index values must be contiguous and 1-based")
        if self.completion is not None and not isinstance(self.completion, PolicyCompletion):
            raise ValueError("completion must be a PolicyCompletion")
        if self.defect is not None and not isinstance(self.defect, EpisodeDefect):
            raise ValueError("defect must be an EpisodeDefect")
        if self.completion is None and self.defect is None:
            raise ValueError("capture requires a completion or defect")

    def to_document(self) -> JSONObject:
        return {
            "public_input": self.public_input.to_document(),
            "turns": [item.to_document() for item in self.turns],
            "completion": self.completion.to_document() if self.completion is not None else None,
            "defect": self.defect.to_document() if self.defect is not None else None,
        }


@dataclass(frozen=True, slots=True)
class RewardOutcome:
    disposition: _RewardDisposition
    reward: float | None
    abstain_owner: DefectOwner | None
    abstain_code: str | None

    def __post_init__(self) -> None:
        if self.disposition not in _REWARD_DISPOSITIONS:
            raise ValueError("reward disposition is invalid")
        if self.disposition == "verified_success":
            if (
                type(self.reward) is not float
                or self.reward != 1.0
                or self.abstain_owner is not None
                or self.abstain_code is not None
            ):
                raise ValueError("verified_success requires exactly reward 1.0")
            return
        if self.disposition == "verified_failure":
            if (
                type(self.reward) is not float
                or self.reward != 0.0
                or self.abstain_owner is not None
                or self.abstain_code is not None
            ):
                raise ValueError("verified_failure requires exactly reward 0.0")
            return
        if self.reward is not None:
            raise ValueError("abstain requires reward null")
        if self.abstain_owner not in _DEFECT_OWNERS:
            raise ValueError("abstain requires a valid owner")
        if self.abstain_code is None:
            raise ValueError("abstain requires a code")
        _text(self.abstain_code, "abstain code")

    def to_document(self) -> JSONObject:
        return {
            "disposition": self.disposition,
            "reward": self.reward,
            "abstain_owner": self.abstain_owner,
            "abstain_code": self.abstain_code,
        }


def _snapshot_tool_specs(value: Any) -> tuple[ToolSpec, ...]:
    if not isinstance(value, tuple):
        raise ValueError("tool_specs must be a tuple of ToolSpec values")
    normalized = tuple(
        cast(ToolSpec, _normal_object(item, f"ToolSpec {index}"))
        for index, item in enumerate(value)
    )
    try:
        validate_tool_catalog(normalized, role="public episode ToolSpecs")
    except Exception as exc:
        raise ValueError(str(exc)) from exc
    return normalized


def _snapshot_optional_object(value: Any, role: str) -> JSONObject | None:
    if value is None:
        return None
    return _normal_object(value, role)


def _snapshot_json(value: Any, role: str) -> JSONValue:
    return _normal_json(value, role)


def _normal_object(value: Any, role: str) -> JSONObject:
    normalized = _normal_json(value, role)
    if not is_json_object(normalized):
        raise ValueError(f"{role} must be a JSON object")
    return cast(JSONObject, normalized)


def _normal_json(value: Any, role: str) -> JSONValue:
    if not is_json_value(value):
        raise ValueError(f"{role} must be JSON")
    try:
        canonical_bytes(value)
        normalized = json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))
    except Exception as exc:
        raise ValueError(f"{role} must be canonical JSON: {exc}") from exc
    if not is_json_value(normalized):
        raise ValueError(f"{role} must be JSON")
    return cast(JSONValue, normalized)


def _copy_json(value: JSONValue) -> JSONValue:
    return cast(
        JSONValue,
        json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False)),
    )


def _copy_object(value: JSONObject) -> JSONObject:
    return cast(JSONObject, _copy_json(value))


def _copy_optional_object(value: JSONObject | None) -> JSONObject | None:
    return _copy_object(value) if value is not None else None


def _document_digest(document: JSONObject) -> str:
    return hashlib.sha256(canonical_bytes(document)).hexdigest()


def _route_id(value: Any) -> None:
    if (
        not isinstance(value, str)
        or _ROUTE_ID.fullmatch(value) is None
        or (len(value) == 64 and all(character in _HEX for character in value))
    ):
        raise ValueError("route_id must be a normalized non-secret identifier, not a URL or digest")


def _digest(value: Any, role: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in _HEX for character in value)
    ):
        raise ValueError(f"{role} must be a sha256 digest")


def _text(value: Any, role: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{role} must be non-empty text")


def _positive(value: Any, role: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{role} must be a positive integer")


__all__ = [
    "DefectOwner",
    "EpisodeDefect",
    "EpisodeRequest",
    "EpisodeToolCall",
    "PolicyCompletion",
    "PolicySpec",
    "PolicyTurn",
    "PublicEpisodeCapture",
    "PublicEpisodeInput",
    "RewardOutcome",
]
