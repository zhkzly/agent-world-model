"""Public-only execution runner and load-bearing argument provenance checks."""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol, cast

from agent_env_foundry.semantics import JSONValue, JSONObject, TraceEvent
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


def run_public_policy(
    *,
    actor: PublicActor,
    definition: TaskDefinition,
    checker: CompiledTaskChecker,
    before_facts: JSONValue,
    after_facts: Callable[[], JSONValue],
    policy: Policy,
    max_steps: int = 20,
) -> WitnessRun:
    """Run an injected public policy; no protected value enters its arguments."""

    reset_context = actor.reset(definition.blueprint.start_recipe.reset_input)
    if reset_context != definition.public_reset_context:
        raise RunnerError("fresh public reset context differs from TaskDefinition")
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
            instruction=definition.instruction,
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
        task_definition_id=definition.task_definition_id,
        trace=tuple(trace),
        final_answer=final_answer,
        checker_status=result.status,
        checker_failures=result.failures,
    )


def trace_argument_provenance(
    *,
    arguments: JSONObject,
    instruction: str,
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
        if isinstance(value, str) and value and value in instruction:
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
    max_steps: int = 20,
) -> WitnessRun:
    """Run the final instruction with an OpenAI Responses function-tool loop.

    This function intentionally requires invocation-time credentials. It is not
    used by deterministic unit tests and never receives checker/native data in
    the model input.
    """

    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RunnerError("openai package is required for Responses execution") from exc
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RunnerError("OPENAI_API_KEY is required for Responses execution")
    reset_context = actor.reset(definition.blueprint.start_recipe.reset_input)
    tools = tuple(actor.tools())
    functions = [_responses_tool(spec) for spec in tools]
    client = OpenAI(api_key=api_key, base_url=base_url, max_retries=0)
    history: list[Any] = [
        {
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
    ]
    public_trace: list[PublicTraceEvent] = []
    final_answer: JSONValue = None
    for _ in range(max_steps + 1):
        response = client.responses.create(
            model=model,
            input=history,
            tools=functions,
            tool_choice="auto",
            parallel_tool_calls=False,
            store=False,
        )
        output = list(cast(Sequence[Any], response.output or ()))
        history.extend(output)
        calls = [item for item in output if getattr(item, "type", None) == "function_call"]
        if not calls:
            text = response.output_text
            if not isinstance(text, str) or not text.strip():
                raise RunnerError("Responses policy returned neither tool call nor answer")
            try:
                final_answer = json.loads(text)
            except json.JSONDecodeError:
                final_answer = text
            break
        for call in calls:
            arguments = json.loads(call.arguments)
            if not isinstance(arguments, dict):
                raise RunnerError("tool arguments must be an object")
            spec = _tool_spec(tools, call.name)
            provenance = trace_argument_provenance(
                arguments=arguments,
                instruction=definition.instruction,
                reset_context=reset_context,
                tool_spec=spec,
                prior_trace=tuple(public_trace),
            )
            observation = dict(actor.invoke(call.name, arguments))
            public_trace.append(
                PublicTraceEvent(
                    len(public_trace) + 1,
                    call.name,
                    arguments,
                    cast(JSONObject, observation),
                    provenance,
                )
            )
            history.append(
                {
                    "type": "function_call_output",
                    "call_id": call.call_id,
                    "output": json.dumps(observation, ensure_ascii=False, sort_keys=True),
                }
            )
    semantic_trace = tuple(
        TraceEvent(item.seq, item.tool_name, item.arguments, item.observation)
        for item in public_trace
    )
    result = checker.evaluate(before_facts, after_facts(), semantic_trace, final_answer)
    return WitnessRun(
        uuid.uuid4().hex,
        definition.task_definition_id,
        tuple(public_trace),
        final_answer,
        result.status,
        result.failures,
    )


def _tool_spec(tools: tuple[Mapping[str, Any], ...], name: str) -> Mapping[str, Any]:
    for spec in tools:
        if spec.get("name") == name:
            return spec
    raise RunnerError(f"unknown public tool {name!r}")


def _responses_tool(spec: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "type": "function",
        "name": spec["name"],
        "description": spec.get("description", ""),
        "parameters": spec["input_schema"],
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
            for pair in _leaf_paths(child, pointer + "/" + key.replace("~", "~0").replace("/", "~1"))
        ]
    if isinstance(value, list):
        return [
            pair for index, child in enumerate(value) for pair in _leaf_paths(child, f"{pointer}/{index}")
        ]
    return [(pointer or "/", value)]
