"""One Host-owned public policy loop and its one-turn Responses adapter."""

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
    JSONValue,
    ToolSpec,
    validate_observation,
)
from agent_env_foundry.episodes import (
    EpisodeDefect,
    EpisodeToolCall,
    PolicyCompletion,
    PolicySpec,
    PolicyTurn,
    PublicEpisodeCapture,
    PublicEpisodeInput,
)
from agent_env_foundry.jsonvalue import is_json_object, is_json_value
from agent_env_foundry.schema import SchemaError, validate_instance

PublicAgentFailureKind = Literal[
    "EnvironmentDefect",
    "FrameworkDefect",
    "InfrastructureFailure",
    "NoPublicWitness",
]
type _DriverCall = tuple[JSONValue, JSONValue, JSONValue]
type _DriverTerminal = Literal["none", "final_answer", "refusal"]

PUBLIC_AGENT_SYSTEM_PROMPT = (
    "Complete only the public task using the instruction, reset observation, and public "
    "function-tool observations. Treat tool observations as authoritative. Do not invent "
    "hidden state or claim completion before the requested outcome and evidence are observed."
)
PUBLIC_AGENT_PROMPT_DIGEST = hashlib.sha256(PUBLIC_AGENT_SYSTEM_PROMPT.encode()).hexdigest()
_OBSERVATION_GUIDANCE = (
    "The function result is a public observation object: ok=true returns data; ok=false "
    "returns error.code, error.message, and optional error.details. Inspect the observation "
    "before deciding the next action."
)
_BASE_URL = "http://127.0.0.1:8317/v1"
_ROUTE_ID = "responses:local-8317"


class _ResponsesResource(Protocol):
    def create(self, **kwargs: Any) -> Any: ...


class _ResponsesClient(Protocol):
    responses: _ResponsesResource


class ClientFactory(Protocol):
    def __call__(self, *, api_key: str, base_url: str, max_retries: int) -> _ResponsesClient: ...


class PublicAgentFailure(RuntimeError):
    def __init__(
        self, kind: PublicAgentFailureKind, code: str, message: str, **details: Any
    ) -> None:
        super().__init__(message)
        self.kind, self.code, self.details = kind, code, details


class UnattributedPolicyDriverFailure(RuntimeError):
    def __init__(self, code: str, phase: str, **details: JSONValue) -> None:
        super().__init__(code)
        self.code, self.phase = code, phase
        self.details = _object(details, "unattributed details")


class _DriverFailure(RuntimeError):
    def __init__(
        self,
        owner: Literal["provider", "infrastructure", "evidence"],
        code: str,
        phase: str,
        **details: JSONValue,
    ) -> None:
        super().__init__(code)
        self.defect = EpisodeDefect(owner, code, phase)
        self.details = _object(details, "driver details")


@dataclass(frozen=True, slots=True)
class DriverDecision:
    """Public material from exactly one decision; never tool authority."""

    calls: tuple[_DriverCall, ...] = ()
    terminal_kind: _DriverTerminal = "none"
    raw_public_terminal: JSONValue = None
    usage: JSONObject | None = None
    defect: EpisodeDefect | None = None


@dataclass(frozen=True, slots=True)
class PublicTraceEvent:
    seq: int
    tool_name: str
    arguments: JSONObject
    observation: JSONObject

    def to_document(self) -> JSONObject:
        return {
            "seq": self.seq,
            "tool_name": self.tool_name,
            "arguments": _object(self.arguments, "trace arguments"),
            "observation": _object(self.observation, "trace observation"),
        }


class PolicyDriver(Protocol):
    @property
    def policy_spec(self) -> PolicySpec: ...

    def start(self, public_input: PublicEpisodeInput) -> None: ...

    def next_decision(
        self, prior_public_results: tuple[tuple[str, JSONObject], ...]
    ) -> DriverDecision: ...

    def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class PublicEpisodeRun:
    trace: tuple[PublicTraceEvent, ...]
    final_answer: JSONObject
    provider_turns: int
    usage: tuple[JSONObject | None, ...]


class ResponsesPolicyDriver:
    """Single-use Responses mapper; the Host owns the loop and every invoke."""

    def __init__(
        self,
        *,
        policy_spec: PolicySpec,
        base_url: str = _BASE_URL,
        client_factory: ClientFactory | None = None,
    ) -> None:
        if (
            policy_spec.driver_id != "openai-responses"
            or policy_spec.driver_version != "1"
            or policy_spec.route_id != _route_id(base_url)
        ):
            raise ValueError("PolicySpec does not match ResponsesPolicyDriver")
        self._spec, self._base_url = policy_spec, base_url
        self._factory = client_factory or cast(ClientFactory, OpenAI)
        self._started = self._closed = False
        self._client: _ResponsesClient | None = None
        self._credential = ""
        self._input: PublicEpisodeInput | None = None
        self._history: list[Any] = []
        self._has_result = False

    @classmethod
    def from_route(
        cls,
        route: AgentRoute,
        *,
        max_provider_turns: int | None = None,
        client_factory: ClientFactory | None = None,
    ) -> ResponsesPolicyDriver:
        turns = route.max_provider_turns if max_provider_turns is None else max_provider_turns
        spec = PolicySpec(
            route.model,
            "openai-responses",
            "1",
            _route_id(route.base_url),
            PUBLIC_AGENT_PROMPT_DIGEST,
            turns,
        )
        return cls(policy_spec=spec, base_url=route.base_url, client_factory=client_factory)

    @property
    def policy_spec(self) -> PolicySpec:
        return self._spec

    def start(self, public_input: PublicEpisodeInput) -> None:
        if self._started or self._closed:
            raise _DriverFailure("evidence", "policy_driver_reused", "policy_driver_start")
        self._started = True
        digest = hashlib.sha256(public_input.system_prompt.encode()).hexdigest()
        if digest != self._spec.system_prompt_digest:
            raise _DriverFailure("evidence", "policy_prompt_digest_mismatch", "policy_driver_start")
        credential = os.environ.get("OPENAI_API_KEY")
        if not credential:
            raise _DriverFailure(
                "infrastructure", "provider_credential_missing", "policy_driver_start"
            )
        try:
            client = self._factory(api_key=credential, base_url=self._base_url, max_retries=2)
        except Exception as exc:
            raise _DriverFailure(
                "infrastructure",
                "responses_client_init_failed",
                "policy_driver_start",
                original_code=type(exc).__name__,
                original_message=str(exc).replace(credential, "[REDACTED]"),
            ) from exc
        self._credential, self._client, self._input = credential, client, public_input
        self._history = [{"role": "user", "content": _initial_user_content(public_input)}]

    def next_decision(
        self, prior_public_results: tuple[tuple[str, JSONObject], ...]
    ) -> DriverDecision:
        if self._client is None or self._input is None or self._closed:
            raise _DriverFailure("evidence", "policy_driver_not_active", "policy_driver_decision")
        for call_id, observation in prior_public_results:
            self._history.append(_response_result(call_id, observation))
        self._has_result |= bool(prior_public_results)
        try:
            response = self._client.responses.create(**self._request())
        except Exception as exc:
            raise _request_failure(exc, self._credential) from exc
        decision, output = _map_response(response)
        self._history.extend(output)  # opaque continuation, never persisted
        return decision

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        client, self._client = self._client, None
        self._credential, self._input = "", None
        self._history.clear()
        close = getattr(client, "close", None)
        if callable(close):
            close()

    def _request(self) -> dict[str, Any]:
        if self._input is None:
            raise AssertionError("Responses request before driver start")
        public = self._input.to_document()
        tools = cast(list[JSONObject], public["tool_specs"])
        return {
            "model": self._spec.model_id,
            "instructions": self._input.system_prompt,
            "input": list(self._history),
            "tools": [
                {
                    "type": "function",
                    "name": tool["name"],
                    "description": tool["description"],
                    "parameters": _responses_parameters(cast(JSONObject, tool["input_schema"])),
                    "strict": True,
                }
                for tool in tools
            ],
            "tool_choice": "auto" if self._has_result else "required",
            "parallel_tool_calls": False,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "public_episode_answer",
                    "schema": _responses_text_schema(cast(JSONObject, public["answer_schema"])),
                    "strict": True,
                }
            },
            "store": False,
        }


def _responses_parameters(value: JSONObject) -> JSONObject:
    """Add only the mechanical empty-object members required by strict tools."""

    schema = cast(JSONObject, json.loads(json.dumps(value, ensure_ascii=False)))
    if schema.get("type") == "object" and "properties" not in schema and "required" not in schema:
        schema["properties"] = {}
        schema["required"] = []
    return schema


def _responses_text_schema(value: JSONObject) -> JSONObject:
    """Project exact JSON Schema into the local provider's supported wire subset."""

    schema = cast(JSONObject, json.loads(json.dumps(value, ensure_ascii=False)))

    def visit(node: JSONValue) -> None:
        if isinstance(node, dict):
            if "const" in node:
                constant = node["const"]
                if isinstance(constant, (dict, list)):
                    node.pop("const")
                    for key, child in _json_shape(constant).items():
                        node.setdefault(key, child)
                elif "type" not in node:
                    node["type"] = _json_type(constant)
            node_type = node.get("type")
            if (
                node_type == "object"
                or isinstance(node_type, list)
                and "object" in node_type
                or "properties" in node
            ):
                node["additionalProperties"] = False
            for child in node.values():
                visit(child)
        elif isinstance(node, list):
            for child in node:
                visit(child)

    visit(schema)
    return schema


def _json_shape(value: JSONValue) -> JSONObject:
    kind = _json_type(value)
    if isinstance(value, dict):
        return {
            "type": "object",
            "properties": {key: _json_shape(child) for key, child in value.items()},
            "required": list(value),
            "additionalProperties": False,
        }
    if isinstance(value, list):
        item_types = sorted({_json_type(item) for item in value}) or ["string"]
        items: JSONObject = (
            {"type": item_types[0]}
            if len(item_types) == 1
            else {"anyOf": [{"type": item} for item in item_types]}
        )
        return {"type": "array", "items": items}
    return {"type": kind}


def _json_type(value: JSONValue) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    return "object"


def capture_public_episode(
    *,
    actor: Environment,
    instruction: str,
    reset_observation: JSONValue,
    answer_schema: JSONObject,
    policy_driver: PolicyDriver,
) -> PublicEpisodeCapture:
    capture, _details = _capture(
        actor, instruction, reset_observation, answer_schema, policy_driver, None
    )
    return capture


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
    """Existing S2 success projection over the shared Host capture."""

    driver = ResponsesPolicyDriver.from_route(
        route or AgentRoute(),
        max_provider_turns=max_provider_turns,
        client_factory=client_factory,
    )
    capture, details = _capture(
        actor, instruction, reset_observation, answer_schema, driver, tool_specs
    )
    if capture.defect is not None:
        kind: PublicAgentFailureKind
        if capture.defect.owner == "environment":
            kind = "EnvironmentDefect"
        elif capture.defect.owner == "evidence":
            kind = "FrameworkDefect"
        else:
            kind = "InfrastructureFailure"
        raise PublicAgentFailure(
            kind,
            capture.defect.code,
            "public episode defect",
            **details,
            capture=capture.to_document(),
        )
    completion = capture.completion
    if completion is None or completion.terminal_kind != "completed":
        code = completion.terminal_code if completion is not None else None
        raise PublicAgentFailure(
            "NoPublicWitness",
            code or "public_policy_failed",
            "public policy failure",
            **details,
            capture=capture.to_document(),
        )
    return PublicEpisodeRun(
        _trace_from_capture(capture),
        cast(JSONObject, completion.to_document()["final_answer"]),
        len(capture.turns),
        tuple(cast(JSONObject | None, turn.to_document()["usage"]) for turn in capture.turns),
    )


def _capture(
    actor: Environment,
    instruction: Any,
    reset_observation: Any,
    answer_schema: Any,
    driver: PolicyDriver,
    tool_specs: Sequence[ToolSpec | Mapping[str, Any]] | None,
) -> tuple[PublicEpisodeCapture, JSONObject]:
    try:
        actor_tool_specs = tool_specs is None
        try:
            resolved_tool_specs = actor.tools() if tool_specs is None else tool_specs
            public_input, catalog = _public_input(
                instruction, reset_observation, answer_schema, resolved_tool_specs
            )
        except Exception as exc:
            if not actor_tool_specs:
                raise
            kind: PublicAgentFailureKind = (
                "InfrastructureFailure"
                if getattr(exc, "kind", None) == "InfrastructureFailure"
                else "EnvironmentDefect"
            )
            raise PublicAgentFailure(kind, "actor_tool_catalog_invalid", str(exc)) from exc
        frozen_answer_schema = cast(JSONObject, public_input.to_document()["answer_schema"])
        spec = driver.policy_spec
    except Exception:
        driver.close()
        raise
    turns: list[PolicyTurn] = []
    completion: PolicyCompletion | None = None
    defect: EpisodeDefect | None = None
    details: JSONObject = {}
    results: tuple[tuple[str, JSONObject], ...] = ()
    seen_ids: set[str] = set()
    unattributed: UnattributedPolicyDriverFailure | None = None
    try:
        if not isinstance(spec, PolicySpec):
            raise ValueError("PolicyDriver policy_spec must be a PolicySpec")
        if spec.system_prompt_digest != PUBLIC_AGENT_PROMPT_DIGEST:
            raise ValueError("PolicySpec prompt digest does not match the Host prompt")
        try:
            driver.start(public_input)
        except _DriverFailure as exc:
            defect, details = exc.defect, exc.details
        except Exception as exc:
            raise _unattributed(exc, "policy_driver_start") from exc
        while completion is None and defect is None and len(turns) < spec.max_provider_turns:
            if driver.policy_spec.policy_id != spec.policy_id:
                defect = EpisodeDefect("evidence", "policy_spec_changed", "policy_driver_decision")
                break
            try:
                decision = driver.next_decision(results)
            except _DriverFailure as exc:
                defect, details = exc.defect, exc.details
                break
            except Exception as exc:
                raise _unattributed(exc, "policy_driver_decision") from exc
            if not isinstance(decision, DriverDecision):
                raise UnattributedPolicyDriverFailure(
                    "policy_driver_decision_invalid", "policy_driver_decision"
                )
            calls, results, policy_code, call_defect, call_details = _apply_calls(
                decision.calls, actor, catalog, seen_ids, decision.defect is None
            )
            turns.append(
                PolicyTurn(
                    len(turns) + 1,
                    calls,
                    _json(decision.raw_public_terminal, "public terminal"),
                    _optional_object(decision.usage, "usage"),
                )
            )
            if call_defect is not None:
                defect, details = call_defect, call_details
            elif policy_code is not None:
                completion = _failed(policy_code)
            else:
                completion = _decision_completion(decision, frozen_answer_schema, turns)
            if decision.defect is not None and defect is None:
                defect = decision.defect
        if completion is None and defect is None:
            completion = _failed("provider_turn_budget_exhausted")
            details = {"max_provider_turns": spec.max_provider_turns}
    except UnattributedPolicyDriverFailure as exc:
        unattributed = exc
    finally:
        try:
            driver.close()
        except OSError as exc:
            if defect is None:
                defect = EpisodeDefect(
                    "infrastructure", "policy_driver_close_failed", "policy_driver_close"
                )
                details = _exception_details(exc)
        except Exception as exc:
            unattributed = _unattributed(exc, "policy_driver_close")
    if unattributed is not None:
        raise unattributed
    return (
        PublicEpisodeCapture(public_input, tuple(turns), completion, defect),
        details,
    )


def _trace_from_capture(capture: PublicEpisodeCapture) -> tuple[PublicTraceEvent, ...]:
    dispatched = (
        call
        for turn in capture.turns
        for call in turn.calls
        if call.dispatch_status == "dispatched"
    )
    return tuple(
        PublicTraceEvent(
            seq,
            cast(str, call.tool_name),
            _object(call.parsed_arguments, "trace arguments"),
            _object(call.observation, "trace observation"),
        )
        for seq, call in enumerate(dispatched, 1)
    )


def _public_input(
    instruction: Any,
    reset_observation: Any,
    answer_schema: Any,
    tool_specs: Sequence[ToolSpec | Mapping[str, Any]],
) -> tuple[PublicEpisodeInput, dict[str, ToolSpec]]:
    public_tools: list[ToolSpec] = []
    for tool in tool_specs:
        copied = dict(tool)
        description = copied.get("description")
        if isinstance(description, str):
            copied["description"] = f"{description.rstrip()} {_OBSERVATION_GUIDANCE}"
        public_tools.append(cast(ToolSpec, copied))
    public_input = PublicEpisodeInput(
        PUBLIC_AGENT_SYSTEM_PROMPT,
        instruction,
        cast(JSONValue, reset_observation),
        tuple(public_tools),
        cast(JSONObject, answer_schema),
    )
    public_tool_documents = cast(list[JSONObject], public_input.to_document()["tool_specs"])
    return public_input, {
        cast(str, tool["name"]): cast(ToolSpec, tool) for tool in public_tool_documents
    }


def _apply_calls(
    calls: tuple[_DriverCall, ...],
    actor: Environment,
    catalog: Mapping[str, ToolSpec],
    seen_ids: set[str],
    dispatch: bool,
) -> tuple[
    tuple[EpisodeToolCall, ...],
    tuple[tuple[str, JSONObject], ...],
    str | None,
    EpisodeDefect | None,
    JSONObject,
]:
    records: list[EpisodeToolCall] = []
    results: list[tuple[str, JSONObject]] = []
    policy_code: str | None = None
    defect: EpisodeDefect | None = None
    details: JSONObject = {}
    if not isinstance(calls, tuple):
        raise UnattributedPolicyDriverFailure(
            "policy_driver_calls_invalid", "policy_driver_decision"
        )
    for raw in calls:
        if not isinstance(raw, tuple) or len(raw) != 3:
            raise UnattributedPolicyDriverFailure(
                "policy_driver_call_invalid", "policy_driver_decision"
            )
        raw_id, raw_name, raw_arguments = (
            _json(raw[0], "call id"),
            _json(raw[1], "tool name"),
            _json(raw[2], "arguments"),
        )
        call_id = raw_id if isinstance(raw_id, str) and raw_id.strip() else None
        tool_name = raw_name if isinstance(raw_name, str) and raw_name.strip() else None
        parsed: JSONObject | None = None
        parse_status = schema_status = "not_checked"
        dispatch_status, observation = "not_dispatched", None
        duplicate_id = call_id is not None and call_id in seen_ids
        if call_id is not None and not duplicate_id:
            seen_ids.add(call_id)
        if policy_code is not None or defect is not None or not dispatch:
            dispatch_status = "not_dispatched_after_terminal"
        elif duplicate_id:
            dispatch_status, policy_code = "duplicate_call_id", "duplicate_tool_call_id"
        elif call_id is None or tool_name is None:
            dispatch_status, policy_code = "malformed_call", "malformed_tool_call"
        elif not isinstance(raw_arguments, str):
            parse_status, dispatch_status, policy_code = (
                "invalid_type",
                "invalid_arguments",
                "tool_arguments_invalid",
            )
        else:
            try:
                decoded = json.loads(raw_arguments)
            except json.JSONDecodeError:
                parse_status, dispatch_status, policy_code = (
                    "invalid_json",
                    "invalid_arguments",
                    "tool_arguments_invalid",
                )
            else:
                if not is_json_object(decoded):
                    parse_status, dispatch_status, policy_code = (
                        "non_object",
                        "invalid_arguments",
                        "tool_arguments_invalid",
                    )
                else:
                    parsed, parse_status = cast(JSONObject, decoded), "valid"
                    if tool_name not in catalog:
                        dispatch_status, policy_code = "unknown_tool", "unknown_tool_call"
                    else:
                        try:
                            validate_instance(
                                parsed,
                                catalog[tool_name]["input_schema"],
                                role=f"public tool {tool_name!r} arguments",
                            )
                        except SchemaError:
                            schema_status, dispatch_status, policy_code = (
                                "invalid",
                                "schema_invalid",
                                "tool_arguments_schema_invalid",
                            )
                        else:
                            schema_status = "valid"
                            try:
                                value = actor.invoke(
                                    tool_name, _object(parsed, "tool dispatch arguments")
                                )
                            except Exception as exc:
                                owner: Literal["environment", "infrastructure"] = (
                                    "infrastructure"
                                    if getattr(exc, "kind", None) == "InfrastructureFailure"
                                    else "environment"
                                )
                                defect = EpisodeDefect(
                                    owner, "actor_dispatch_failed", "tool_dispatch"
                                )
                                dispatch_status = "dispatch_failed"
                                details = _exception_details(exc)
                            else:
                                try:
                                    validate_observation(value, catalog[tool_name], role=tool_name)
                                    observation = _object(value, "tool observation")
                                except Exception as exc:
                                    defect = EpisodeDefect(
                                        "environment",
                                        "tool_observation_invalid",
                                        "tool_observation",
                                    )
                                    dispatch_status = "observation_invalid"
                                    details = _exception_details(exc)
                                else:
                                    dispatch_status = "dispatched"
                                    results.append((call_id, _object(observation, "public result")))
        records.append(
            EpisodeToolCall(
                raw_id,
                raw_name,
                call_id,
                tool_name,
                raw_arguments,
                parsed,
                parse_status,
                schema_status,
                dispatch_status,
                observation,
            )
        )
    return tuple(records), tuple(results), policy_code, defect, details


def _decision_completion(
    decision: DriverDecision, schema: JSONObject, turns: Sequence[PolicyTurn]
) -> PolicyCompletion | None:
    has_dispatched_call = any(
        call.dispatch_status == "dispatched" for turn in turns for call in turn.calls
    )
    if decision.calls and decision.terminal_kind != "none":
        return _failed("ambiguous_policy_decision")
    if decision.calls:
        return None
    if decision.terminal_kind == "refusal":
        return _failed("policy_refusal")
    if decision.terminal_kind == "none":
        return _failed(
            "final_answer_missing" if has_dispatched_call else "required_tool_call_missing"
        )
    if decision.terminal_kind != "final_answer":
        raise UnattributedPolicyDriverFailure(
            "policy_driver_terminal_invalid", "policy_driver_decision"
        )
    raw = decision.raw_public_terminal
    if not has_dispatched_call:
        return _failed("required_tool_call_missing")
    if not isinstance(raw, str) or not raw.strip():
        return _failed("final_answer_missing")
    try:
        answer = json.loads(raw)
    except json.JSONDecodeError:
        return _failed("final_answer_invalid")
    if not is_json_object(answer) or next(Draft202012Validator(schema).iter_errors(answer), None):
        return _failed("final_answer_invalid")
    return PolicyCompletion("completed", cast(JSONObject, answer), None)


def _failed(code: str) -> PolicyCompletion:
    return PolicyCompletion("policy_failure", None, code)


def _map_response(response: Any) -> tuple[DriverDecision, list[Any]]:
    output = _item(response, "output")
    if isinstance(output, Sequence) and not isinstance(output, (str, bytes)):
        items = list(output)
    else:
        raise UnattributedPolicyDriverFailure("responses_output_invalid", "policy_driver_response")
    calls: list[_DriverCall] = []
    texts: list[str] = []
    refusal: JSONValue = None
    for item in items:
        kind = _item(item, "type")
        if kind == "function_call":
            calls.append(
                (
                    _json(_item(item, "call_id"), "call id"),
                    _json(_item(item, "name"), "tool name"),
                    _json(_item(item, "arguments"), "arguments"),
                )
            )
        elif kind == "reasoning":
            continue
        elif kind == "message":
            content = _item(item, "content")
            if not isinstance(content, Sequence) or isinstance(content, (str, bytes)):
                raise UnattributedPolicyDriverFailure(
                    "responses_message_invalid", "policy_driver_response"
                )
            for part in content:
                if _item(part, "type") == "output_text" and isinstance(_item(part, "text"), str):
                    texts.append(_item(part, "text"))
                elif _item(part, "type") == "refusal" and refusal is None:
                    refusal = _json(_item(part, "refusal"), "refusal")
                else:
                    raise UnattributedPolicyDriverFailure(
                        "responses_message_part_unexpected", "policy_driver_response"
                    )
        else:
            raise UnattributedPolicyDriverFailure(
                "responses_output_item_unexpected",
                "policy_driver_response",
                item_type=_json(kind, "output item type"),
            )
    raw_terminal = _item(response, "output_text")
    if (
        raw_terminal is None or isinstance(raw_terminal, str) and not raw_terminal.strip()
    ) and texts:
        raw_terminal = "".join(texts)
    if calls and isinstance(raw_terminal, str) and not raw_terminal.strip():
        raw_terminal = None
    terminal = _json(raw_terminal, "public terminal")
    terminal_kind: _DriverTerminal = (
        "final_answer" if terminal is not None else "refusal" if refusal is not None else "none"
    )
    terminal = refusal if terminal_kind == "refusal" else terminal
    usage = _item(response, "usage")
    if usage is not None and callable(getattr(usage, "model_dump", None)):
        usage = usage.model_dump()
    try:
        normalized_usage = _optional_object(usage, "usage")
    except ValueError:
        return (
            DriverDecision(
                tuple(calls),
                terminal_kind,
                terminal,
                None,
                EpisodeDefect("evidence", "provider_usage_invalid", "policy_driver_usage"),
            ),
            items,
        )
    return DriverDecision(tuple(calls), terminal_kind, terminal, normalized_usage), items


def _request_failure(
    exc: Exception, credential: str
) -> _DriverFailure | UnattributedPolicyDriverFailure:
    status, name = getattr(exc, "status_code", None), type(exc).__name__
    details: dict[str, JSONValue] = _exception_details(exc, credential)
    if isinstance(status, int):
        details["status_code"] = status
    if (
        status == 429
        or (isinstance(status, int) and status >= 500)
        or name
        in {
            "RateLimitError",
            "InternalServerError",
            "ServiceUnavailableError",
        }
    ):
        owner: Literal["provider", "infrastructure", "evidence"] = "provider"
    elif status in {400, 422} or name in {"BadRequestError", "UnprocessableEntityError"}:
        owner = "evidence"
    elif status in {401, 403, 404} or name in {
        "AuthenticationError",
        "PermissionDeniedError",
        "NotFoundError",
    }:
        owner = "infrastructure"
    elif status == 408:
        owner = "provider"
    elif isinstance(exc, (OSError, ImportError)) or name in {
        "APIConnectionError",
        "APITimeoutError",
        "ConnectError",
        "ReadTimeout",
    }:
        owner = "infrastructure"
    else:
        return UnattributedPolicyDriverFailure(
            "responses_request_unattributed", "policy_driver_request", **details
        )
    return _DriverFailure(owner, "responses_request_failed", "policy_driver_request", **details)


def _unattributed(exc: Exception, phase: str) -> UnattributedPolicyDriverFailure:
    if isinstance(exc, UnattributedPolicyDriverFailure):
        return exc
    return UnattributedPolicyDriverFailure(
        "policy_driver_exception_unattributed", phase, **_exception_details(exc)
    )


def _initial_user_content(public_input: PublicEpisodeInput) -> str:
    return json.dumps(
        {
            "instruction": public_input.instruction,
            "reset_observation": public_input.to_document()["reset_observation"],
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _response_result(call_id: str, observation: JSONObject) -> JSONObject:
    return {
        "type": "function_call_output",
        "call_id": call_id,
        "output": json.dumps(
            observation, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ),
    }


def _exception_details(exc: Exception, secret: str = "") -> JSONObject:
    message = str(exc).replace(secret, "[REDACTED]") if secret else str(exc)
    return {"original_code": type(exc).__name__, "original_message": message}


def _route_id(base_url: str) -> str:
    if base_url != _BASE_URL:
        raise ValueError("unsupported Responses route")
    return _ROUTE_ID


def _item(value: Any, name: str) -> Any:
    return value.get(name) if isinstance(value, Mapping) else getattr(value, name, None)


def _json(value: Any, role: str) -> JSONValue:
    if not is_json_value(value):
        raise ValueError(f"{role} must be JSON")
    return cast(JSONValue, json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False)))


def _object(value: Any, role: str) -> JSONObject:
    copied = _json(value, role)
    if not is_json_object(copied):
        raise ValueError(f"{role} must be a JSON object")
    return cast(JSONObject, copied)


def _optional_object(value: Any, role: str) -> JSONObject | None:
    return None if value is None else _object(value, role)


__all__ = [
    "ClientFactory",
    "DriverDecision",
    "PUBLIC_AGENT_PROMPT_DIGEST",
    "PUBLIC_AGENT_SYSTEM_PROMPT",
    "PolicyDriver",
    "PublicAgentFailure",
    "PublicEpisodeRun",
    "PublicTraceEvent",
    "ResponsesPolicyDriver",
    "UnattributedPolicyDriverFailure",
    "capture_public_episode",
    "run_public_episode",
]
