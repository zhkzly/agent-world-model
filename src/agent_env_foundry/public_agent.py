"""Fresh public-only Responses function-tool episode runner."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol, cast

from jsonschema import Draft202012Validator
from openai import OpenAI

from agent_env_foundry.agents import AgentRoute
from agent_env_foundry.environment import (
    Environment,
    JSONObject,
    ToolSpec,
    validate_observation,
    validate_tool_catalog,
)
from agent_env_foundry.jsonvalue import is_json_object, is_json_value
from agent_env_foundry.schema import SchemaError, require_object_root, validate_instance
from agent_env_foundry.semantics import TraceEvent

PublicAgentFailureKind = Literal[
    "EnvironmentDefect",
    "InfrastructureFailure",
    "NoPublicWitness",
]
PUBLIC_AGENT_SYSTEM_PROMPT = (
    "Solve only the public task. Use the provided function tools when needed. "
    "Treat every tool observation as authoritative. Never invent hidden state. "
    "Return only the final JSON object matching the required schema."
)
PUBLIC_AGENT_PROMPT_DIGEST = hashlib.sha256(PUBLIC_AGENT_SYSTEM_PROMPT.encode("utf-8")).hexdigest()


class _ResponsesResource(Protocol):
    def create(self, **kwargs: Any) -> Any: ...


class _ResponsesClient(Protocol):
    responses: _ResponsesResource


class ClientFactory(Protocol):
    def __call__(self, *, api_key: str, base_url: str, max_retries: int) -> _ResponsesClient: ...


class PublicAgentFailure(RuntimeError):
    def __init__(
        self,
        kind: PublicAgentFailureKind,
        code: str,
        message: str,
        **details: Any,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.code = code
        self.details = details


@dataclass(frozen=True, slots=True)
class PublicEpisodeRun:
    trace: tuple[TraceEvent, ...]
    final_answer: JSONObject
    provider_turns: int
    usage: tuple[JSONObject | None, ...]


def run_public_episode(
    *,
    actor: Environment,
    instruction: str,
    reset_observation: Any,
    tool_specs: Sequence[ToolSpec | Mapping[str, Any]],
    answer_schema: JSONObject,
    route: AgentRoute | None = None,
    client_factory: ClientFactory | None = None,
    max_provider_turns: int | None = None,
) -> PublicEpisodeRun:
    selected_route = route or AgentRoute()
    turn_limit = (
        selected_route.max_provider_turns if max_provider_turns is None else max_provider_turns
    )
    if turn_limit <= 0:
        raise ValueError("max_provider_turns must be positive")
    if not isinstance(instruction, str) or not instruction.strip():
        raise ValueError("public instruction must be non-empty")
    if not is_json_value(reset_observation):
        raise ValueError("reset observation must be JSON")
    try:
        require_object_root(answer_schema, role="public final answer")
        catalog = validate_tool_catalog(tuple(tool_specs), role="public episode tools")
    except Exception as exc:
        raise ValueError(str(exc)) from exc
    credential = os.environ.get("OPENAI_API_KEY")
    if not credential:
        raise PublicAgentFailure(
            "InfrastructureFailure",
            "provider_credential_missing",
            "OPENAI_API_KEY is required for a public episode",
        )
    factory = client_factory or cast(ClientFactory, OpenAI)
    try:
        client = factory(
            api_key=credential,
            base_url=selected_route.base_url,
            max_retries=0,
        )
    except Exception as exc:
        raise PublicAgentFailure(
            "InfrastructureFailure",
            "responses_client_init_failed",
            "public episode provider client initialization failed",
            original_code=type(exc).__name__,
            original_message=str(exc).replace(credential, "[REDACTED]"),
        ) from exc
    history: list[Any] = [
        {
            "role": "user",
            "content": json.dumps(
                {
                    "instruction": instruction,
                    "reset_observation": reset_observation,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
        }
    ]
    trace: list[TraceEvent] = []
    usage_records: list[JSONObject | None] = []
    tools = [
        {
            "type": "function",
            "name": spec["name"],
            "description": spec["description"],
            "parameters": spec["input_schema"],
            "strict": True,
        }
        for spec in catalog.values()
    ]
    for turn in range(1, turn_limit + 1):
        request = {
            "model": selected_route.model,
            "instructions": PUBLIC_AGENT_SYSTEM_PROMPT,
            "input": history,
            "tools": tools,
            "tool_choice": "auto",
            "parallel_tool_calls": False,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "public_episode_answer",
                    "schema": answer_schema,
                    "strict": True,
                }
            },
            "store": False,
        }
        try:
            response = client.responses.create(**request)
        except Exception as exc:
            raise PublicAgentFailure(
                "InfrastructureFailure",
                "responses_request_failed",
                "public episode provider request failed",
                original_code=type(exc).__name__,
                original_message=str(exc).replace(credential, "[REDACTED]"),
            ) from exc
        usage_records.append(_usage(response))
        output_items = list(cast(Sequence[Any], _item(response, "output") or ()))
        history.extend(output_items)
        calls = [item for item in output_items if _item(item, "type") == "function_call"]
        if calls:
            for call in calls:
                name = _item(call, "name")
                arguments_text = _item(call, "arguments")
                call_id = _item(call, "call_id")
                if not isinstance(name, str) or name not in catalog:
                    raise PublicAgentFailure(
                        "NoPublicWitness",
                        "unknown_tool_call",
                        "public Agent requested a tool outside the public catalog",
                        tool_name=name,
                    )
                if not isinstance(arguments_text, str) or not isinstance(call_id, str):
                    raise PublicAgentFailure(
                        "NoPublicWitness",
                        "malformed_tool_call",
                        "public Agent emitted a malformed function call",
                    )
                try:
                    arguments = json.loads(arguments_text)
                except json.JSONDecodeError as exc:
                    raise PublicAgentFailure(
                        "NoPublicWitness",
                        "tool_arguments_invalid",
                        "public Agent tool arguments are not JSON",
                    ) from exc
                if not is_json_object(arguments):
                    raise PublicAgentFailure(
                        "NoPublicWitness",
                        "tool_arguments_invalid",
                        "public Agent tool arguments must be an object",
                    )
                spec = catalog[name]
                try:
                    validate_instance(
                        arguments,
                        spec["input_schema"],
                        role=f"public tool {name!r} arguments",
                    )
                except SchemaError as exc:
                    raise PublicAgentFailure(
                        "NoPublicWitness",
                        "tool_arguments_schema_invalid",
                        str(exc),
                    ) from exc
                try:
                    observation = actor.invoke(name, arguments)
                except Exception as exc:
                    inherited_kind = getattr(exc, "kind", None)
                    kind: PublicAgentFailureKind = (
                        "InfrastructureFailure"
                        if inherited_kind == "InfrastructureFailure"
                        else "EnvironmentDefect"
                    )
                    raise PublicAgentFailure(
                        kind,
                        "actor_dispatch_failed",
                        "public actor tool dispatch failed",
                        original_code=type(exc).__name__,
                        original_message=str(exc),
                    ) from exc
                try:
                    validate_observation(observation, spec, role=f"public tool {name!r}")
                except Exception as exc:
                    raise PublicAgentFailure(
                        "EnvironmentDefect",
                        "tool_observation_invalid",
                        str(exc),
                    ) from exc
                trace.append(
                    TraceEvent(
                        len(trace) + 1,
                        name,
                        arguments,
                        cast(JSONObject, dict(observation)),
                    )
                )
                history.append(
                    {
                        "type": "function_call_output",
                        "call_id": call_id,
                        "output": json.dumps(
                            observation,
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                    }
                )
            continue
        output_text = _item(response, "output_text")
        if not isinstance(output_text, str) or not output_text.strip():
            raise PublicAgentFailure(
                "NoPublicWitness",
                "final_answer_missing",
                "public Agent returned neither a tool call nor a final answer",
            )
        try:
            answer = json.loads(output_text)
        except json.JSONDecodeError as exc:
            raise PublicAgentFailure(
                "NoPublicWitness",
                "final_answer_invalid",
                "public Agent final answer is not JSON",
            ) from exc
        errors = sorted(Draft202012Validator(answer_schema).iter_errors(answer), key=str)
        if errors or not is_json_object(answer):
            error = errors[0] if errors else None
            raise PublicAgentFailure(
                "NoPublicWitness",
                "final_answer_invalid",
                "public Agent final answer violates its schema",
                original_message=error.message if error else "answer root is not an object",
            )
        return PublicEpisodeRun(tuple(trace), answer, turn, tuple(usage_records))
    raise PublicAgentFailure(
        "NoPublicWitness",
        "provider_turn_budget_exhausted",
        "public Agent exhausted its provider-turn budget",
        max_provider_turns=turn_limit,
    )


def _item(value: Any, name: str) -> Any:
    if isinstance(value, Mapping):
        return value.get(name)
    return getattr(value, name, None)


def _usage(response: Any) -> JSONObject | None:
    value = _item(response, "usage")
    if value is None:
        return None
    if not isinstance(value, Mapping) and callable(getattr(value, "model_dump", None)):
        value = value.model_dump()
    try:
        normalized = json.loads(json.dumps(value, ensure_ascii=False))
    except (TypeError, ValueError) as exc:
        raise PublicAgentFailure(
            "InfrastructureFailure",
            "provider_usage_invalid",
            "provider usage is not JSON-serializable",
        ) from exc
    if not is_json_object(normalized):
        raise PublicAgentFailure(
            "InfrastructureFailure",
            "provider_usage_invalid",
            "provider usage must be an object when present",
        )
    return cast(JSONObject, normalized)


__all__ = [
    "ClientFactory",
    "PUBLIC_AGENT_PROMPT_DIGEST",
    "PUBLIC_AGENT_SYSTEM_PROMPT",
    "PublicAgentFailure",
    "PublicEpisodeRun",
    "run_public_episode",
]
