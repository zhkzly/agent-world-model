"""Direct S2 Task proposal through one real public environment exploration."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol, cast

from openai import OpenAI

from agent_env_foundry.agents import AgentRoute
from agent_env_foundry.environment import (
    Environment,
    JSONObject,
    JSONValue,
    ToolSpec,
    invalid_arguments_observation,
    unknown_tool_observation,
    validate_observation,
    validate_tool_catalog,
)
from agent_env_foundry.jsonvalue import is_json_object, is_json_value
from agent_env_foundry.release import canonical_bytes, sha256_hex
from agent_env_foundry.schema import (
    SchemaError,
    project_responses_strict_schema,
    validate_instance,
)
from agent_env_foundry.task_draft import (
    TASK_DRAFT_FORMAT,
    AnswerProjection,
    PublicValueRef,
    SamplingTarget,
    TaskDraft,
    draft_atom_steps,
    draft_goal_shape,
    materialize_answer,
    task_draft_from_document,
)
from agent_env_foundry.task_goal import TraceEvent

_PROVIDER_TURN_TIMEOUT_SECONDS = 180.0
TASK_SAMPLING_EVIDENCE_FORMAT = "task-sampling-evidence/1"
_SAMPLING_SCHEMA: JSONObject = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["draft", "unsupported"]},
        "reason": {"type": ["string", "null"]},
        "instruction": {"type": ["string", "null"]},
        "goal_json": {"type": ["string", "null"]},
        "answer_json": {"type": ["string", "null"]},
    },
    "required": ["status", "reason", "instruction", "goal_json", "answer_json"],
    "additionalProperties": False,
}
_SAMPLING_PROMPT = """Sample one real training Task from the supplied released environment.

SamplingTarget is mandatory. The final DraftGoal must have exactly its required Goal shape and
outcome, and every required focus tool must be an objective step rather than exploratory.
If that target is not natural and executable, inspect enough public state to justify it and
return status=unsupported; never substitute an easier Task.

Use only reset context, ToolSpecs, and returned ToolObservations. Follow inspect, choose one
Need-relevant coherent objective, resolve every operand publicly, execute it, and verify the
result through public tools. Read-only exploratory calls may be omitted from the Goal. Any free
ID, version, quantity, message, or target affecting truth must be uniquely selected by public
evidence or written exactly in the instruction. Do not expose tool names, a solution path,
hidden state, or answer values in the instruction.

For task-owned text that is not copied from reset or an observation, quote every free string
literal in the instruction and state that its spelling and case are exact. Avoid decorative
free-text arguments, especially in refusal Tasks: every literal must be part of the user intent
and reproducible by a fresh Agent. Do not rely on a solver paraphrasing back to the sampled bytes.

For an If target, the condition must be the public business scalar that the instruction
actually depends on and must occur before the branch objective. Never use ToolObservation
/ok, generic request success, tool availability, or the whole data collection as the condition.

After real execution, return status=draft with the natural instruction, goal_json, and
answer_json. Goal step numbers are one-based public call positions. answer_json is an
AnswerProjection that only copies or assembles Task/reset/ToolObservation JSON; it cannot
compute, relabel, or assert new facts. For every direct source field, use an output key that
matches the final semantic token of its public JSON pointer: for example, source
/data/assignee_id must be named assignee_id, never a generic result or value key. Do not
author an answer schema, Checker, reward,
protected-state expectation, Python code, or admission verdict.

The user input contains task_draft_contract with the exact Goal and AnswerProjection syntax
for this target. Follow those tagged JSON examples exactly; replace example steps, pointers,
branches, fields, and literals only with values supported by your real public trace.
prior_accepted_tasks contains public summaries only. Use them to avoid repeating the same
semantic objective; they are not solution evidence for the new Task.
"""

SamplingFailureKind = Literal[
    "EnvironmentDefect",
    "FrameworkDefect",
    "InfrastructureFailure",
    "SamplingUnsupported",
    "DraftRejected",
]


class _ResponsesResource(Protocol):
    def create(self, **kwargs: Any) -> Any: ...


class _ResponsesClient(Protocol):
    responses: _ResponsesResource


class ClientFactory(Protocol):
    def __call__(self, *, api_key: str, base_url: str, max_retries: int) -> _ResponsesClient: ...


class _PreparedIdentity(Protocol):
    release_id: str


class _PreparedSession(Protocol):
    actor: Environment

    def __enter__(self) -> _PreparedSession: ...
    def __exit__(self, *args: Any) -> None: ...


class PreparedTaskEnvironment(Protocol):
    identity: _PreparedIdentity

    @property
    def reset_observation_schema(self) -> JSONObject: ...

    def open(self, instance_directory: Path) -> _PreparedSession: ...
    def read_state(self, instance_directory: Path) -> JSONValue: ...


class SamplingFailure(RuntimeError):
    def __init__(
        self,
        kind: SamplingFailureKind,
        code: str,
        message: str,
        **details: Any,
    ) -> None:
        super().__init__(message)
        self.kind, self.code, self.details = kind, code, details


@dataclass(frozen=True, slots=True)
class TaskSamplingEvidence:
    release_id: str
    sampling_target_id: str
    reset_start: JSONObject | None
    reset_observation: JSONValue
    before_state: JSONValue
    after_state: JSONValue
    public_trace: tuple[TraceEvent, ...]
    expected_answer: JSONObject
    final_answer_schema: JSONObject

    def __post_init__(self) -> None:
        for digest_value, role in (
            (self.release_id, "release_id"),
            (self.sampling_target_id, "sampling_target_id"),
        ):
            if len(digest_value) != 64 or any(
                char not in "0123456789abcdef" for char in digest_value
            ):
                raise ValueError(f"{role} must be a sha256 digest")
        if self.reset_start is not None and not is_json_object(self.reset_start):
            raise ValueError("reset_start must be a JSON object or null")
        for json_value, role in (
            (self.reset_observation, "reset_observation"),
            (self.before_state, "before_state"),
            (self.after_state, "after_state"),
        ):
            if not is_json_value(json_value):
                raise ValueError(f"{role} must be a JSON value")
        if not self.public_trace or any(
            not isinstance(event, TraceEvent) for event in self.public_trace
        ):
            raise ValueError("public_trace must contain real TraceEvents")
        if not is_json_object(self.expected_answer) or not is_json_object(self.final_answer_schema):
            raise ValueError("sampling answer and schema must be JSON objects")

    @property
    def evidence_id(self) -> str:
        return sha256_hex(canonical_bytes(self.to_document()))

    def to_document(self) -> JSONObject:
        return {
            "format": TASK_SAMPLING_EVIDENCE_FORMAT,
            "release_id": self.release_id,
            "sampling_target_id": self.sampling_target_id,
            "reset_start": _json_copy(self.reset_start),
            "reset_observation": _json_copy(self.reset_observation),
            "before_state": _json_copy(self.before_state),
            "after_state": _json_copy(self.after_state),
            "public_trace": [event.to_document() for event in self.public_trace],
            "expected_answer": _object_copy(self.expected_answer),
            "final_answer_schema": _object_copy(self.final_answer_schema),
        }


@dataclass(frozen=True, slots=True)
class SampledTaskDraft:
    draft: TaskDraft
    evidence: TaskSamplingEvidence
    provider_turns: int
    usage: tuple[JSONObject | None, ...]


@dataclass(frozen=True, slots=True)
class _SamplingTerminal:
    status: Literal["draft", "unsupported"]
    draft: TaskDraft | None
    reason: str | None


def sample_task_draft(
    prepared: PreparedTaskEnvironment,
    *,
    development_brief: JSONObject,
    target: SamplingTarget,
    instance_directory: Path,
    route: AgentRoute | None = None,
    reset_start: JSONObject | None = None,
    prior_accepted_summaries: Sequence[Mapping[str, Any]] = (),
    client_factory: ClientFactory | None = None,
) -> SampledTaskDraft:
    """Let one generic Agent execute, then return a Host-checked TaskDraft."""

    if not is_json_object(development_brief):
        raise SamplingFailure(
            "DraftRejected", "development_brief_invalid", "development_brief must be an object"
        )
    if not isinstance(target, SamplingTarget):
        raise SamplingFailure(
            "FrameworkDefect", "sampling_target_invalid", "target must be a SamplingTarget"
        )
    if reset_start is not None and not is_json_object(reset_start):
        raise SamplingFailure(
            "DraftRejected", "reset_start_invalid", "reset_start must be an object or null"
        )
    summaries = _sampling_summaries(prior_accepted_summaries)
    instance = _fresh_instance_path(instance_directory)
    selected_route = route or AgentRoute()
    factory = client_factory or _default_client_factory
    credential = os.environ.get("OPENAI_API_KEY")
    if not credential and client_factory is None:
        raise SamplingFailure(
            "InfrastructureFailure",
            "provider_credential_missing",
            "OPENAI_API_KEY must be supplied at invocation time",
        )
    try:
        client = factory(
            api_key=credential or "injected-test-client",
            base_url=selected_route.base_url,
            max_retries=0,
        )
    except Exception as exc:
        raise SamplingFailure(
            "InfrastructureFailure",
            "responses_client_init_failed",
            "cannot initialize the sampling Responses client",
            original_code=type(exc).__name__,
            original_message=_safe_message(exc, credential),
        ) from exc

    public_trace: list[JSONObject] = []
    usage: list[JSONObject | None] = []
    history: list[Any] = []
    provider_turns = 0
    terminal: _SamplingTerminal | None = None
    terminal_errors: list[str] = []
    try:
        with prepared.open(instance) as session:
            actor = session.actor
            try:
                reset_observation = actor.reset(reset_start)
                catalog = validate_tool_catalog(actor.tools(), role="sampling tools()")
                before_state = prepared.read_state(instance)
            except Exception as exc:
                raise _environment_failure("sampling_reset_failed", exc) from exc
            history.append(
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "development_brief": _sampling_brief(development_brief),
                            "sampling_target": target.to_document(),
                            "task_draft_contract": _task_draft_contract(target),
                            "prior_accepted_tasks": summaries,
                            "reset_observation": reset_observation,
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                }
            )
            while provider_turns < selected_route.max_provider_turns:
                provider_turns += 1
                response = _provider_turn(
                    client,
                    route=selected_route,
                    history=history,
                    catalog=catalog,
                    credential=credential,
                    has_public_action=bool(public_trace),
                )
                usage.append(_usage(response))
                output_items = _output_items(response)
                history.extend(output_items)
                calls = [item for item in output_items if _item(item, "type") == "function_call"]
                if calls:
                    for call in calls:
                        trace_item, call_output = _dispatch_call(actor, catalog, call)
                        if trace_item is not None:
                            public_trace.append(trace_item)
                        history.append(call_output)
                    continue
                output_text = _item(response, "output_text")
                if not isinstance(output_text, str) or not output_text.strip():
                    raise SamplingFailure(
                        "DraftRejected",
                        "sampling_terminal_missing",
                        "Sampling Agent returned neither a tool call nor a terminal",
                    )
                if not public_trace:
                    raise SamplingFailure(
                        "DraftRejected",
                        "sampling_public_action_missing",
                        "Sampling Agent must inspect or execute the real public environment",
                    )
                try:
                    terminal = _sampling_terminal(output_text, target)
                except ValueError as exc:
                    error = str(exc)
                    terminal_errors.append(error)
                    if terminal_errors.count(error) >= 2 or len(terminal_errors) >= 3:
                        raise SamplingFailure(
                            "DraftRejected",
                            "sampling_terminal_stalled",
                            "Sampling Agent could not satisfy the disclosed terminal contract",
                            errors=list(terminal_errors),
                        ) from exc
                    contract = json.dumps(
                        _task_draft_contract(target),
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                    history.append(
                        {
                            "role": "user",
                            "content": (
                                f"Rejected condition: {error}. Exact TaskDraft and "
                                f"AnswerProjection contract: {contract}. Your rejected "
                                f"terminal was: {output_text}. Return the complete corrected "
                                "terminal without repeating completed tool calls."
                            ),
                        }
                    )
                    continue
                break
            if terminal is None:
                raise SamplingFailure(
                    "DraftRejected",
                    "sampling_turn_budget_exhausted",
                    "Sampling Agent exhausted its provider-turn budget",
                    max_provider_turns=selected_route.max_provider_turns,
                )
        try:
            after_state = prepared.read_state(instance)
        except Exception as exc:
            raise _environment_failure("sampling_state_read_failed", exc) from exc
    except SamplingFailure as exc:
        _retain_sampling_metrics(exc, provider_turns, usage, public_trace)
        raise
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()

    if terminal.status == "unsupported":
        failure = SamplingFailure(
            "SamplingUnsupported",
            "sampling_target_unsupported",
            cast(str, terminal.reason),
            sampling_target_id=target.target_id,
        )
        _retain_sampling_metrics(failure, provider_turns, usage, public_trace)
        raise failure
    draft = cast(TaskDraft, terminal.draft)
    trace = tuple(
        TraceEvent(
            index,
            cast(str, item["tool"]),
            cast(JSONObject, item["arguments"]),
            cast(JSONObject, item["observation"]),
        )
        for index, item in enumerate(public_trace, 1)
    )
    try:
        _validate_sampled_draft(draft, target, trace, before_state, after_state)
    except SamplingFailure as exc:
        exc.details.setdefault("rejected_draft", draft.to_document())
        _retain_sampling_metrics(exc, provider_turns, usage, public_trace)
        raise
    try:
        answer = materialize_answer(
            draft.answer,
            reset_observation=reset_observation,
            reset_schema=prepared.reset_observation_schema,
            trace=trace,
            tool_specs=tuple(catalog.values()),
        )
    except ValueError as exc:
        failure = SamplingFailure(
            "DraftRejected",
            "draft_answer_projection_invalid",
            str(exc),
        )
        failure.details.setdefault("rejected_draft", draft.to_document())
        _retain_sampling_metrics(failure, provider_turns, usage, public_trace)
        raise failure from exc
    evidence = TaskSamplingEvidence(
        prepared.identity.release_id,
        target.target_id,
        reset_start,
        reset_observation,
        before_state,
        after_state,
        trace,
        answer.value,
        answer.schema,
    )
    return SampledTaskDraft(draft, evidence, provider_turns, tuple(usage))


def _default_client_factory(*, api_key: str, base_url: str, max_retries: int) -> _ResponsesClient:
    return cast(
        _ResponsesClient,
        OpenAI(
            api_key=api_key,
            base_url=base_url,
            max_retries=max_retries,
            timeout=_PROVIDER_TURN_TIMEOUT_SECONDS,
        ),
    )


def _provider_turn(
    client: _ResponsesClient,
    *,
    route: AgentRoute,
    history: list[Any],
    catalog: Mapping[str, ToolSpec],
    credential: str | None,
    has_public_action: bool,
) -> Any:
    request = {
        "model": route.model,
        "instructions": _SAMPLING_PROMPT,
        "input": list(history),
        "tools": [_response_tool(spec) for spec in catalog.values()],
        "tool_choice": "auto" if has_public_action else "required",
        "parallel_tool_calls": False,
        "text": {
            "format": {
                "type": "json_schema",
                "name": "task_draft_sampling",
                "schema": _SAMPLING_SCHEMA,
                "strict": True,
            }
        },
        "store": False,
    }
    try:
        return client.responses.create(**request)
    except Exception as exc:
        raise SamplingFailure(
            _provider_failure_kind(exc),
            "sampling_provider_turn_failed",
            "sampling Responses turn failed",
            original_code=type(exc).__name__,
            original_message=_safe_message(exc, credential),
        ) from exc


def _response_tool(spec: ToolSpec) -> JSONObject:
    parameters = cast(JSONObject, project_responses_strict_schema(spec["input_schema"]))
    return {
        "type": "function",
        "name": spec["name"],
        "description": spec["description"],
        "parameters": parameters,
        "strict": True,
    }


def _dispatch_call(
    actor: Environment,
    catalog: Mapping[str, ToolSpec],
    call: Any,
) -> tuple[JSONObject | None, JSONObject]:
    call_id, name, arguments_text = (
        _item(call, "call_id"),
        _item(call, "name"),
        _item(call, "arguments"),
    )
    if not isinstance(call_id, str) or not call_id:
        raise SamplingFailure(
            "DraftRejected",
            "sampling_tool_call_id_invalid",
            "sampling tool call omitted its call_id",
        )
    if not isinstance(name, str) or not name:
        observation = unknown_tool_observation(str(name))
        return None, _call_output(call_id, observation)
    if not isinstance(arguments_text, str):
        observation = invalid_arguments_observation(
            "function arguments must be a JSON object", tool_name=name
        )
        return None, _call_output(call_id, observation)
    try:
        arguments = json.loads(arguments_text)
    except json.JSONDecodeError as exc:
        observation = invalid_arguments_observation(str(exc), tool_name=name)
        return None, _call_output(call_id, observation)
    if not is_json_object(arguments):
        observation = invalid_arguments_observation(
            "function arguments must decode to an object", tool_name=name
        )
        return None, _call_output(call_id, observation)
    spec = catalog.get(name)
    if spec is None:
        observation = unknown_tool_observation(name)
        return None, _call_output(call_id, observation)
    try:
        validate_instance(arguments, spec["input_schema"], role=f"proposal tool {name!r}")
    except SchemaError as exc:
        observation = invalid_arguments_observation(str(exc), tool_name=name)
        return None, _call_output(call_id, observation)
    try:
        raw_observation = actor.invoke(name, arguments)
        validate_observation(raw_observation, spec, role=f"proposal tool {name!r}")
    except Exception as exc:
        raise _environment_failure("proposal_tool_execution_failed", exc) from exc
    observation_document = cast(
        JSONObject, json.loads(json.dumps(raw_observation, ensure_ascii=False))
    )
    trace_item: JSONObject = {
        "tool": name,
        "arguments": cast(JSONObject, json.loads(json.dumps(arguments, ensure_ascii=False))),
        "observation": observation_document,
    }
    return trace_item, _call_output(call_id, observation_document)


def _call_output(call_id: str, observation: Mapping[str, Any]) -> JSONObject:
    return {
        "type": "function_call_output",
        "call_id": call_id,
        "output": json.dumps(
            observation,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
    }


def _sampling_terminal(output_text: str, target: SamplingTarget) -> _SamplingTerminal:
    try:
        document = json.loads(output_text)
        validate_instance(document, _SAMPLING_SCHEMA, role="Task sampling terminal")
    except (json.JSONDecodeError, SchemaError) as exc:
        raise ValueError(f"sampling terminal is invalid: {exc}") from exc
    assert isinstance(document, dict)
    status = document["status"]
    if status == "unsupported":
        if (
            not isinstance(document["reason"], str)
            or not document["reason"].strip()
            or any(
                document[name] is not None for name in ("instruction", "goal_json", "answer_json")
            )
        ):
            raise ValueError("unsupported terminal requires only a non-empty reason")
        return _SamplingTerminal("unsupported", None, document["reason"])
    if (
        document["reason"] is not None
        or not isinstance(document["instruction"], str)
        or not document["instruction"].strip()
    ):
        raise ValueError("draft terminal requires instruction and no unsupported reason")
    goal = _nested_object(document["goal_json"], "DraftGoal")
    answer = _nested_object(document["answer_json"], "AnswerProjection")
    draft = task_draft_from_document(
        {
            "format": TASK_DRAFT_FORMAT,
            "sampling_target_id": target.target_id,
            "instruction": document["instruction"],
            "goal": goal,
            "answer": answer,
        }
    )
    return _SamplingTerminal("draft", draft, None)


def _sampling_brief(development_brief: JSONObject) -> JSONObject:
    requirements = development_brief.get("requirements")
    frozen_need = development_brief.get("frozen_need")
    selected_world = development_brief.get("selected_world")
    if (
        not isinstance(requirements, list)
        or not is_json_object(frozen_need)
        or not is_json_object(selected_world)
    ):
        return _object_copy(development_brief)
    need_document = cast(JSONObject, frozen_need)
    world_document = cast(JSONObject, selected_world)
    public_fields = (
        "id",
        "kind",
        "state_relation",
        "observable_relation",
        "precondition",
        "postcondition",
    )
    compact: list[JSONValue] = []
    for item in requirements:
        if not is_json_object(item):
            raise SamplingFailure(
                "FrameworkDefect",
                "development_brief_requirement_invalid",
                "development_brief requirements must be objects",
            )
        requirement = cast(JSONObject, item)
        compact.append(
            {name: _json_copy(requirement[name]) for name in public_fields if name in requirement}
        )
    return {
        "frozen_need": _object_copy(need_document),
        "selected_world": _object_copy(world_document),
        "requirements": compact,
    }


def _sampling_summaries(
    summaries: Sequence[Mapping[str, Any]],
) -> list[JSONObject]:
    if isinstance(summaries, (str, bytes)):
        raise SamplingFailure(
            "FrameworkDefect",
            "prior_task_summaries_invalid",
            "prior accepted Task summaries must be a sequence of objects",
        )
    result: list[JSONObject] = []
    keys = {
        "structure_id",
        "goal_shape",
        "objective_tools",
        "outcome_classes",
        "instruction",
    }
    for summary in summaries:
        document = dict(summary)
        if set(document) != keys or not is_json_object(document):
            raise SamplingFailure(
                "FrameworkDefect",
                "prior_task_summary_invalid",
                "a prior accepted Task summary has invalid fields",
            )
        structure_id = document["structure_id"]
        text_fields = (document["goal_shape"], document["instruction"])
        arrays = (document["objective_tools"], document["outcome_classes"])
        if (
            not isinstance(structure_id, str)
            or len(structure_id) != 64
            or any(character not in "0123456789abcdef" for character in structure_id)
            or any(not isinstance(value, str) or not value.strip() for value in text_fields)
            or any(
                not isinstance(values, list)
                or not values
                or any(not isinstance(value, str) or not value.strip() for value in values)
                for values in arrays
            )
        ):
            raise SamplingFailure(
                "FrameworkDefect",
                "prior_task_summary_invalid",
                "a prior accepted Task summary has invalid values",
            )
        result.append(_object_copy(cast(JSONObject, document)))
    return result


def _task_draft_contract(target: SamplingTarget) -> JSONObject:
    atom_one: JSONObject = {"kind": "atom", "step": 1}
    atom_two: JSONObject = {"kind": "atom", "step": 2}
    if target.required_goal_shape == "atom":
        goal: JSONObject = atom_one
    elif target.required_goal_shape == "all":
        goal = {"kind": "all", "children": [atom_one, atom_two]}
    elif target.required_goal_shape == "if":
        goal = {
            "kind": "if",
            "condition": {
                "kind": "observation",
                "step": 1,
                "pointer": "/data/public_scalar",
            },
            "operator": "eq",
            "value": None,
            "then_goal": atom_two,
            "else_goal": None,
        }
    else:
        goal = {
            "kind": "foreach",
            "members": {
                "kind": "observation",
                "step": 1,
                "pointer": "/data/public_members",
            },
            "member_key_pointer": "/public_id",
            "member_argument_pointer": "/public_id",
            "children": [atom_one, atom_two],
        }
    return {
        "goal_example": goal,
        "answer_projection_example": {
            "kind": "object",
            "fields": {
                "entity_id": {
                    "kind": "source",
                    "source": {
                        "kind": "observation",
                        "step": 1,
                        "pointer": "/data/entity_id",
                    },
                }
            },
        },
        "source_forms": {
            "task_literal": {"kind": "task_literal", "value": "exact disclosed value"},
            "reset": {"kind": "reset", "pointer": "/public/reset/pointer"},
            "observation": {
                "kind": "observation",
                "step": 1,
                "pointer": "/data/public/pointer",
            },
        },
    }


def _validate_sampled_draft(
    draft: TaskDraft,
    target: SamplingTarget,
    trace: tuple[TraceEvent, ...],
    before_state: JSONValue,
    after_state: JSONValue,
) -> None:
    if draft.sampling_target_id != target.target_id:
        raise SamplingFailure(
            "DraftRejected",
            "draft_target_identity_mismatch",
            "TaskDraft belongs to another SamplingTarget",
        )
    if draft_goal_shape(draft.goal) != target.required_goal_shape:
        raise SamplingFailure(
            "DraftRejected",
            "draft_goal_shape_mismatch",
            "TaskDraft Goal shape does not satisfy SamplingTarget",
            expected=target.required_goal_shape,
            actual=draft_goal_shape(draft.goal),
        )
    steps = draft_atom_steps(draft.goal)
    if not steps or len(steps) != len(set(steps)):
        raise SamplingFailure(
            "DraftRejected",
            "draft_objective_steps_invalid",
            "TaskDraft objective steps must be non-empty and unique",
        )
    events = {event.seq: event for event in trace}
    missing = [step for step in steps if step not in events]
    if missing:
        raise SamplingFailure(
            "DraftRejected",
            "draft_objective_step_missing",
            "TaskDraft references a tool call that did not occur",
            missing_steps=missing,
        )
    objectives = [events[step] for step in steps]
    tools = {event.tool_name for event in objectives}
    changed = canonical_bytes(before_state) != canonical_bytes(after_state)
    actual_outcome = _observed_outcome(objectives, changed=changed)
    if target.required_outcome == "transition" and not changed:
        raise SamplingFailure(
            "DraftRejected",
            "draft_transition_noop",
            "transition target made no state change",
            actual_outcome=actual_outcome,
            actual_tools=sorted(tools),
        )
    if target.required_outcome != "transition" and changed:
        raise SamplingFailure(
            "DraftRejected",
            "draft_nontransition_changed_state",
            "query/refusal target changed protected state",
            actual_outcome=actual_outcome,
            actual_tools=sorted(tools),
        )
    for event in objectives:
        ok = event.observation["ok"]
        error = event.observation["error"]
        if target.required_outcome == "refusal":
            code = error.get("code") if isinstance(error, dict) else None
            valid = ok is False and isinstance(code, str) and not code.startswith("contract.")
        else:
            valid = ok is True
        if not valid:
            raise SamplingFailure(
                "DraftRejected",
                "draft_objective_outcome_mismatch",
                "objective observation does not satisfy the required outcome",
                step=event.seq,
                actual_outcome=actual_outcome,
                actual_tools=sorted(tools),
            )
    if not set(target.required_focus_tools).issubset(tools):
        raise SamplingFailure(
            "DraftRejected",
            "draft_focus_tool_missing",
            "required focus tools must participate in the objective",
            required=list(target.required_focus_tools),
            actual=sorted(tools),
            actual_outcome=actual_outcome,
        )
    mismatch = _answer_field_source_mismatch(draft.answer)
    if mismatch is not None:
        field, pointer = mismatch
        raise SamplingFailure(
            "DraftRejected",
            "draft_answer_field_source_mismatch",
            "a direct answer field must name the semantic leaf of its public source",
            field=field,
            source_pointer=pointer,
        )


def _answer_field_source_mismatch(
    projection: AnswerProjection,
) -> tuple[str, str] | None:
    if projection.kind == "object":
        for field, child in projection.fields:
            if child.kind == "source":
                source = cast(PublicValueRef, child.source)
                pointer = source.pointer
                leaf = _semantic_pointer_leaf(pointer) if source.kind != "task_literal" else None
                if leaf is not None and _semantic_name(field) != _semantic_name(leaf):
                    return field, cast(str, pointer)
            nested = _answer_field_source_mismatch(child)
            if nested is not None:
                return nested
    elif projection.kind == "array":
        for child in projection.items:
            nested = _answer_field_source_mismatch(child)
            if nested is not None:
                return nested
    return None


def _observed_outcome(objectives: list[TraceEvent], *, changed: bool) -> str:
    successes = [event.observation["ok"] is True for event in objectives]
    if successes and not any(successes):
        return "refusal"
    if all(successes):
        return "transition" if changed else "query"
    return "mixed"


def _semantic_pointer_leaf(pointer: str | None) -> str | None:
    if not pointer:
        return None
    token = pointer.rsplit("/", 1)[-1].replace("~1", "/").replace("~0", "~")
    return None if token.isdecimal() or token in {"data", "error"} else token


def _semantic_name(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum())


def _nested_object(value: Any, role: str) -> JSONObject:
    if not isinstance(value, str):
        raise ValueError(f"{role} must be encoded as a JSON string")
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{role} JSON is invalid: {exc}") from exc
    if not is_json_object(decoded):
        raise ValueError(f"{role} must decode to a JSON object")
    return cast(JSONObject, decoded)


def _output_items(response: Any) -> list[Any]:
    output = _item(response, "output")
    if not isinstance(output, Sequence) or isinstance(output, (str, bytes)):
        raise SamplingFailure(
            "InfrastructureFailure",
            "sampling_response_output_invalid",
            "sampling Responses output must be an item sequence",
        )
    return list(output)


def _usage(response: Any) -> JSONObject | None:
    value = _item(response, "usage")
    if value is None:
        return None
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        value = dump()
    if not is_json_object(value):
        raise SamplingFailure(
            "InfrastructureFailure",
            "sampling_usage_invalid",
            "sampling Responses usage must be a JSON object",
        )
    return cast(JSONObject, json.loads(json.dumps(value, ensure_ascii=False)))


def _item(value: Any, name: str) -> Any:
    return value.get(name) if isinstance(value, Mapping) else getattr(value, name, None)


def _fresh_instance_path(path: Path) -> Path:
    selected = Path(path)
    if selected.is_symlink() or (
        selected.exists() and (not selected.is_dir() or any(selected.iterdir()))
    ):
        raise SamplingFailure(
            "DraftRejected",
            "sampling_instance_not_fresh",
            "sampling instance_directory must be absent or empty",
        )
    return selected.resolve()


def _environment_failure(code: str, exc: Exception) -> SamplingFailure:
    kind: SamplingFailureKind = (
        "InfrastructureFailure"
        if getattr(exc, "kind", None) == "InfrastructureFailure"
        else "EnvironmentDefect"
    )
    return SamplingFailure(
        kind,
        code,
        str(exc),
        original_code=type(exc).__name__,
        original_message=str(exc),
    )


def _safe_message(exc: Exception, credential: str | None) -> str:
    message = str(exc)
    return message.replace(credential, "[REDACTED]") if credential else message


def _provider_failure_kind(exc: Exception) -> SamplingFailureKind:
    return (
        "FrameworkDefect"
        if getattr(exc, "status_code", None) in {400, 422}
        else "InfrastructureFailure"
    )


def _retain_sampling_metrics(
    failure: SamplingFailure,
    provider_turns: int,
    usage: list[JSONObject | None],
    public_trace: list[JSONObject],
) -> None:
    failure.details.setdefault("provider_turns", provider_turns)
    failure.details.setdefault(
        "usage", [_object_copy(item) if item is not None else None for item in usage]
    )
    failure.details.setdefault("public_tool_calls", len(public_trace))
    failure.details.setdefault("public_trace", [_object_copy(item) for item in public_trace])


def _json_copy(value: JSONValue) -> JSONValue:
    return cast(JSONValue, json.loads(json.dumps(value, ensure_ascii=False)))


def _object_copy(value: JSONObject) -> JSONObject:
    return cast(JSONObject, _json_copy(value))


__all__ = [
    "ClientFactory",
    "PreparedTaskEnvironment",
    "SampledTaskDraft",
    "SamplingFailure",
    "SamplingFailureKind",
    "TASK_SAMPLING_EVIDENCE_FORMAT",
    "TaskSamplingEvidence",
    "sample_task_draft",
]
