"""Public-only execution runner and load-bearing argument provenance checks."""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol, cast

from openai import OpenAI
from openai.types.responses import (
    EasyInputMessageParam,
    FunctionToolParam,
    ResponseFunctionToolCall,
    ResponseInputItemParam,
    ResponseInputParam,
    ResponseOutputItem,
)
from openai.types.responses.response_input_param import FunctionCallOutput

from agent_env_foundry.jsonvalue import is_json_object
from agent_env_foundry.semantics import JSONObject, JSONValue, TraceEvent
from agent_task_foundry.compiler import CompiledTaskChecker
from agent_task_foundry.models import (
    ArgumentOrigin,
    ProvenanceReport,
    PublicTraceEvent,
    TaskDefinition,
    WitnessRun,
)


class RunnerError(RuntimeError):
    """The public policy or provider violated the acting contract."""


class PublicActor(Protocol):
    def reset(self, start: JSONObject | None = None) -> JSONValue: ...
    def tools(self) -> tuple[Mapping[str, Any], ...]: ...
    def invoke(self, tool_name: str, arguments: JSONObject) -> Mapping[str, Any]: ...
    def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class PolicyAction:
    tool_name: str
    arguments: JSONObject


@dataclass(frozen=True, slots=True)
class PolicyFinish:
    answer: JSONValue


PolicyDecision = PolicyAction | PolicyFinish
Policy = Callable[[TaskDefinition, JSONValue, tuple[PublicTraceEvent, ...]], PolicyDecision]


@dataclass(frozen=True, slots=True)
class _ResponseTurn:
    output: tuple[ResponseOutputItem, ...]
    output_text: str


ResponseTurnCreator = Callable[[ResponseInputParam, list[FunctionToolParam]], _ResponseTurn]


def run_public_policy(
    *,
    actor: PublicActor,
    definition: TaskDefinition,
    checker: CompiledTaskChecker,
    before_facts: JSONValue,
    after_facts: Callable[[], JSONValue],
    policy: Policy,
    materialization_id: str,
    max_steps: int = 20,
) -> WitnessRun:
    """Run an injected public policy; no protected value enters its arguments."""

    reset_context = actor.reset(definition.blueprint.start_recipe.reset_input)
    if not _contains(reset_context, definition.public_reset_context):
        raise RunnerError("fresh reset context omits a TaskDefinition public fact")
    tools = tuple(actor.tools())
    trace: list[PublicTraceEvent] = []
    final_answer: JSONValue = None
    for _ in range(max_steps + 1):
        decision = policy(definition, reset_context, tuple(trace))
        if isinstance(decision, PolicyFinish):
            final_answer = decision.answer
            break
        if len(trace) >= max_steps:
            raise RunnerError("public policy exceeded max_steps")
        spec = _tool_spec(tools, decision.tool_name)
        provenance = trace_argument_provenance(
            arguments=decision.arguments,
            instruction_literals=_task_literals(definition),
            reset_context=reset_context,
            tool_spec=spec,
            prior_trace=tuple(trace),
        )
        observation = dict(actor.invoke(decision.tool_name, decision.arguments))
        if set(observation) != {"ok", "data", "error"}:
            raise RunnerError("actor returned a malformed ToolObservation")
        trace.append(
            PublicTraceEvent(
                len(trace) + 1,
                decision.tool_name,
                decision.arguments,
                cast(JSONObject, observation),
                provenance,
            )
        )
    else:
        raise RunnerError("public policy did not finish")
    semantic_trace = tuple(
        TraceEvent(item.seq, item.tool_name, item.arguments, item.observation) for item in trace
    )
    result = checker.evaluate(before_facts, after_facts(), semantic_trace, final_answer)
    return WitnessRun(
        run_id=uuid.uuid4().hex,
        materialization_id=materialization_id,
        task_definition_id=definition.task_definition_id,
        trace=tuple(trace),
        final_answer=final_answer,
        checker_status=result.status,
        checker_failures=result.failures,
    )


def trace_argument_provenance(
    *,
    arguments: JSONObject,
    instruction_literals: tuple[JSONValue, ...],
    reset_context: JSONValue,
    tool_spec: Mapping[str, Any],
    prior_trace: tuple[PublicTraceEvent, ...],
) -> ProvenanceReport:
    leaves = _leaf_paths(arguments)
    if not leaves:
        return ProvenanceReport((ArgumentOrigin("/", "tool_schema", "no_arguments"),))
    origins: list[ArgumentOrigin] = []
    constants = _schema_constants(tool_spec.get("input_schema"))
    reset_values = _leaf_paths(reset_context)
    tool_values: list[tuple[JSONValue, str]] = []
    for event in prior_trace:
        if event.observation.get("ok") is True:
            tool_values.extend(
                (value, f"trace[{event.seq}].observation.data{path}")
                for path, value in _leaf_paths(event.observation.get("data"))
            )
    for path, value in leaves:
        source = ArgumentOrigin(path, "unresolved")
        if any(value == literal for literal in instruction_literals):
            source = ArgumentOrigin(path, "instruction")
        else:
            reset_match = next((pointer for pointer, item in reset_values if item == value), None)
            if reset_match is not None:
                source = ArgumentOrigin(path, "reset", reset_match)
            elif value in constants:
                source = ArgumentOrigin(path, "tool_schema")
            else:
                tool_match = next(
                    (pointer for item, pointer in tool_values if item == value),
                    None,
                )
                if tool_match is not None:
                    source = ArgumentOrigin(path, "tool_output", tool_match)
        origins.append(source)
    return ProvenanceReport(tuple(origins))


def run_responses_policy(
    *,
    actor: PublicActor,
    definition: TaskDefinition,
    checker: CompiledTaskChecker,
    before_facts: JSONValue,
    after_facts: Callable[[], JSONValue],
    model: str,
    base_url: str,
    materialization_id: str,
    max_steps: int = 20,
) -> WitnessRun:
    """Run the final instruction with an OpenAI Responses function-tool loop."""

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RunnerError("OPENAI_API_KEY is required for Responses execution")
    client = OpenAI(api_key=api_key, base_url=base_url, max_retries=0)

    def create_turn(
        input_items: ResponseInputParam,
        functions: list[FunctionToolParam],
    ) -> _ResponseTurn:
        response = client.responses.create(
            model=model,
            input=input_items,
            tools=functions,
            tool_choice="auto",
            parallel_tool_calls=False,
            store=False,
        )
        return _ResponseTurn(tuple(response.output), response.output_text or "")

    return _run_responses_policy_loop(
        actor=actor,
        definition=definition,
        checker=checker,
        before_facts=before_facts,
        after_facts=after_facts,
        create_turn=create_turn,
        materialization_id=materialization_id,
        max_steps=max_steps,
    )


def _run_responses_policy_loop(
    *,
    actor: PublicActor,
    definition: TaskDefinition,
    checker: CompiledTaskChecker,
    before_facts: JSONValue,
    after_facts: Callable[[], JSONValue],
    create_turn: ResponseTurnCreator,
    materialization_id: str,
    max_steps: int = 20,
) -> WitnessRun:
    """Execute typed Responses turns; injectable creator supports deterministic tests."""

    reset_context = actor.reset(definition.blueprint.start_recipe.reset_input)
    if not _contains(reset_context, definition.public_reset_context):
        raise RunnerError("fresh reset context omits a TaskDefinition public fact")
    tools = tuple(actor.tools())
    functions = [_responses_tool(spec) for spec in tools]
    initial_message: EasyInputMessageParam = {
        "role": "user",
        "content": json.dumps(
            {
                "instruction": definition.instruction,
                "reset_context": reset_context,
                "answer_schema": definition.answer_schema,
            },
            ensure_ascii=False,
        ),
    }
    history: ResponseInputParam = [initial_message]
    public_trace: list[PublicTraceEvent] = []
    final_answer: JSONValue = None
    for _ in range(max_steps + 1):
        turn = create_turn(history, functions)
        history.extend(_response_output_as_input(item) for item in turn.output)
        calls = [item for item in turn.output if isinstance(item, ResponseFunctionToolCall)]
        if not calls:
            if not turn.output_text.strip():
                raise RunnerError("Responses policy returned neither tool call nor answer")
            try:
                parsed_answer: object = json.loads(turn.output_text)
            except json.JSONDecodeError:
                final_answer = turn.output_text
            else:
                if not _is_json_value(parsed_answer):
                    raise RunnerError("Responses final answer is not a JSON value")
                final_answer = cast(JSONValue, parsed_answer)
            break
        for call in calls:
            try:
                parsed_arguments: object = json.loads(call.arguments)
            except json.JSONDecodeError as exc:
                raise RunnerError("tool arguments are not valid JSON") from exc
            if not is_json_object(parsed_arguments):
                raise RunnerError("tool arguments must be an object")
            arguments = cast(JSONObject, parsed_arguments)
            spec = _tool_spec(tools, call.name)
            provenance = trace_argument_provenance(
                arguments=arguments,
                instruction_literals=_task_literals(definition),
                reset_context=reset_context,
                tool_spec=spec,
                prior_trace=tuple(public_trace),
            )
            raw_observation = dict(actor.invoke(call.name, arguments))
            if set(raw_observation) != {"ok", "data", "error"} or not is_json_object(
                raw_observation
            ):
                raise RunnerError("actor returned a malformed ToolObservation")
            observation = cast(JSONObject, raw_observation)
            public_trace.append(
                PublicTraceEvent(
                    len(public_trace) + 1,
                    call.name,
                    arguments,
                    observation,
                    provenance,
                )
            )
            function_output: FunctionCallOutput = {
                "type": "function_call_output",
                "call_id": call.call_id,
                "output": json.dumps(observation, ensure_ascii=False, sort_keys=True),
            }
            history.append(function_output)
    else:
        raise RunnerError("Responses policy exceeded max_steps")
    semantic_trace = tuple(
        TraceEvent(item.seq, item.tool_name, item.arguments, item.observation)
        for item in public_trace
    )
    result = checker.evaluate(before_facts, after_facts(), semantic_trace, final_answer)
    return WitnessRun(
        uuid.uuid4().hex,
        materialization_id,
        definition.task_definition_id,
        tuple(public_trace),
        final_answer,
        result.status,
        result.failures,
    )


def _response_output_as_input(item: ResponseOutputItem) -> ResponseInputItemParam:
    """Convert one validated SDK output model to its official input-item shape."""

    document = item.model_dump(mode="json", exclude_none=True)
    item_type = document.get("type") if isinstance(document, dict) else None
    if not isinstance(item_type, str):
        raise RunnerError("Responses output item lacks a typed input representation")
    return cast(ResponseInputItemParam, document)


def _is_json_value(value: object) -> bool:
    if value is None or isinstance(value, (bool, int, float, str)):
        return True
    if isinstance(value, list):
        return all(_is_json_value(item) for item in value)
    if isinstance(value, dict):
        return all(isinstance(key, str) and _is_json_value(item) for key, item in value.items())
    return False


def _task_literals(definition: TaskDefinition) -> tuple[JSONValue, ...]:
    return tuple(
        predicate.value
        for selector in definition.blueprint.selectors
        for predicate in selector.filters
    )


def _contains(actual: JSONValue, required: JSONValue) -> bool:
    if isinstance(required, dict):
        return isinstance(actual, dict) and all(
            key in actual and _contains(actual[key], value) for key, value in required.items()
        )
    if isinstance(required, list):
        return (
            isinstance(actual, list)
            and len(actual) == len(required)
            and all(_contains(left, right) for left, right in zip(actual, required, strict=True))
        )
    return actual == required


def _tool_spec(tools: tuple[Mapping[str, Any], ...], name: str) -> Mapping[str, Any]:
    for spec in tools:
        if spec.get("name") == name:
            return spec
    raise RunnerError(f"unknown public tool {name!r}")


def _responses_tool(spec: Mapping[str, Any]) -> FunctionToolParam:
    name = spec.get("name")
    description = spec.get("description", "")
    parameters_value = spec.get("input_schema")
    if not isinstance(name, str) or not name:
        raise RunnerError("ToolSpec name must be a non-empty string")
    if not isinstance(description, str):
        raise RunnerError(f"ToolSpec {name!r} description must be a string")
    if not isinstance(parameters_value, dict):
        raise RunnerError(f"ToolSpec {name!r} input_schema must be an object")
    parameters: dict[str, object] = {str(key): value for key, value in parameters_value.items()}
    return {
        "type": "function",
        "name": name,
        "description": description,
        "parameters": parameters,
        "strict": True,
    }


def _schema_constants(schema: Any) -> set[JSONValue]:
    values: set[JSONValue] = set()
    if isinstance(schema, dict):
        constant = schema.get("const")
        if isinstance(constant, (type(None), bool, int, float, str)):
            values.add(constant)
        enum = schema.get("enum")
        if isinstance(enum, list):
            values.update(
                value for value in enum if isinstance(value, (type(None), bool, int, float, str))
            )
        for child in schema.values():
            values |= _schema_constants(child)
    elif isinstance(schema, list):
        for child in schema:
            values |= _schema_constants(child)
    return values


def _leaf_paths(value: JSONValue, pointer: str = "") -> list[tuple[str, JSONValue]]:
    if isinstance(value, dict):
        return [
            pair
            for key, child in value.items()
            for pair in _leaf_paths(
                child, pointer + "/" + key.replace("~", "~0").replace("/", "~1")
            )
        ]
    if isinstance(value, list):
        return [
            pair
            for index, child in enumerate(value)
            for pair in _leaf_paths(child, f"{pointer}/{index}")
        ]
    return [(pointer or "/", value)]
