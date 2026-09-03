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
from agent_env_foundry.task_contract import (
    CANDIDATE_TASK_FORMAT,
    TASK_PROPOSAL_EVIDENCE_FORMAT,
    CandidateTaskContract,
    TaskProposalEvidence,
)
from agent_env_foundry.task_draft import (
    TASK_DRAFT_FORMAT,
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
_PROPOSAL_SCHEMA: JSONObject = {
    "type": "object",
    "properties": {
        "instruction": {"type": "string", "minLength": 1},
        "checker_brief": {"type": "string", "minLength": 1},
        "final_answer_schema_json": {"type": "string", "minLength": 1},
        "proposed_final_answer_json": {"type": "string", "minLength": 1},
    },
    "required": [
        "instruction",
        "checker_brief",
        "final_answer_schema_json",
        "proposed_final_answer_json",
    ],
    "additionalProperties": False,
}
_SYSTEM_PROMPT = """You propose one purposeful training Task for the supplied Need and
real environment.

Use the public tools to explore and physically complete one concrete, Need-relevant objective.
Base the proposal only on the Development Brief, reset observation, ToolSpecs, and returned
ToolObservations. Never assume hidden state. The public instruction must contain every
load-bearing constraint, but must not reveal a solution path, hidden state, or answer key.

The Host may supply previously accepted public instructions from this same Release. Propose a
different semantic and execution objective. A change only in wording, selected entity or
parameter, exploratory inspection order, or final-answer field labels is not a different Task.
Reusing a public tool is fine when the required goal, condition, state transition, refusal
outcome, or answer relation is materially different.

After at least one real public tool call, return the required structured proposal. Encode the
object-root Draft 2020-12 final-answer schema and your observed final answer as JSON strings.
The checker brief is private input for a later independent code author: state the intended goal,
required and forbidden effects, answer relation, and any genuinely required process evidence. If
the public instruction lets the acting Agent select a qualifying entity, identify that selection
as a variable to bind from the future trace/answer; never turn the proposal's chosen ID into a
fixed checker target. A proposal-specific ID is fixed only when the public instruction names it.
The Host applies one universal admission procedure and independently captures protected
before/after state; you cannot see or define that state and you do not decide admission.
"""
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

For an If target, the condition must be the public business scalar that the instruction
actually depends on and must occur before the branch objective. Never use ToolObservation
/ok, generic request success, tool availability, or the whole data collection as the condition.

After real execution, return status=draft with the natural instruction, goal_json, and
answer_json. Goal step numbers are one-based public call positions. answer_json is an
AnswerProjection that only copies or assembles Task/reset/ToolObservation JSON; it cannot
compute, relabel, or assert new facts. Do not author an answer schema, Checker, reward,
protected-state expectation, Python code, or admission verdict.

The user input contains task_draft_contract with the exact Goal and AnswerProjection syntax
for this target. Follow those tagged JSON examples exactly; replace example steps, pointers,
branches, fields, and literals only with values supported by your real public trace.
"""

ProposalFailureKind = Literal[
    "EnvironmentDefect",
    "FrameworkDefect",
    "InfrastructureFailure",
    "CandidateRejected",
]
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


class ProposalFailure(RuntimeError):
    def __init__(
        self,
        kind: ProposalFailureKind,
        code: str,
        message: str,
        **details: Any,
    ) -> None:
        super().__init__(message)
        self.kind, self.code, self.details = kind, code, details


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
class ProposedTask:
    candidate: CandidateTaskContract
    evidence: TaskProposalEvidence
    provider_turns: int
    usage: tuple[JSONObject | None, ...]


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
class _ProposalFields:
    instruction: str
    checker_brief: str
    final_answer_schema: JSONObject
    proposed_final_answer: JSONObject


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
    try:
        instance = _fresh_instance_path(instance_directory)
    except ProposalFailure as exc:
        raise _as_sampling_failure(exc) from exc
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
                raise _as_sampling_failure(
                    _environment_failure("sampling_reset_failed", exc)
                ) from exc
            history.append(
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "development_brief": _sampling_brief(development_brief),
                            "sampling_target": target.to_document(),
                            "task_draft_contract": _task_draft_contract(target),
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
                try:
                    response = _provider_turn(
                        client,
                        route=selected_route,
                        history=history,
                        catalog=catalog,
                        credential=credential,
                        has_public_action=bool(public_trace),
                        instructions=_SAMPLING_PROMPT,
                        response_schema=_SAMPLING_SCHEMA,
                        response_name="task_draft_sampling",
                    )
                except ProposalFailure as exc:
                    raise _as_sampling_failure(exc) from exc
                try:
                    usage.append(_usage(response))
                    output_items = _output_items(response)
                except ProposalFailure as exc:
                    raise _as_sampling_failure(exc) from exc
                history.extend(output_items)
                calls = [item for item in output_items if _item(item, "type") == "function_call"]
                if calls:
                    for call in calls:
                        try:
                            trace_item, call_output = _dispatch_call(actor, catalog, call)
                        except ProposalFailure as exc:
                            raise _as_sampling_failure(exc) from exc
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
            raise _as_sampling_failure(
                _environment_failure("sampling_state_read_failed", exc)
            ) from exc
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()

    if terminal.status == "unsupported":
        raise SamplingFailure(
            "SamplingUnsupported",
            "sampling_target_unsupported",
            cast(str, terminal.reason),
            sampling_target_id=target.target_id,
        )
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
    _validate_sampled_draft(draft, target, trace, before_state, after_state)
    try:
        answer = materialize_answer(
            draft.answer,
            reset_observation=reset_observation,
            reset_schema=prepared.reset_observation_schema,
            trace=trace,
            tool_specs=tuple(catalog.values()),
        )
    except ValueError as exc:
        raise SamplingFailure(
            "DraftRejected",
            "draft_answer_projection_invalid",
            str(exc),
        ) from exc
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


def propose_task_direct(
    prepared: PreparedTaskEnvironment,
    *,
    development_brief: JSONObject,
    builder_projection_digest: str,
    instance_directory: Path,
    route: AgentRoute | None = None,
    reset_start: JSONObject | None = None,
    prior_accepted_instructions: Sequence[str] = (),
    client_factory: ClientFactory | None = None,
) -> ProposedTask:
    """Explore one fresh public instance and return a proposal, never a verdict."""

    if not is_json_object(development_brief):
        raise ProposalFailure(
            "CandidateRejected",
            "development_brief_invalid",
            "development_brief must be a JSON object",
        )
    if reset_start is not None and not is_json_object(reset_start):
        raise ProposalFailure(
            "CandidateRejected",
            "reset_start_invalid",
            "reset_start must be a JSON object or null",
        )
    prior_instructions = tuple(prior_accepted_instructions)
    if (
        isinstance(prior_accepted_instructions, (str, bytes))
        or any(not isinstance(item, str) or not item.strip() for item in prior_instructions)
        or len(prior_instructions) != len(set(prior_instructions))
    ):
        raise ProposalFailure(
            "FrameworkDefect",
            "prior_task_context_invalid",
            "prior accepted instructions must be unique non-empty strings",
        )
    instance = _fresh_instance_path(instance_directory)
    selected_route = route or AgentRoute()
    factory = client_factory or _default_client_factory
    credential = os.environ.get("OPENAI_API_KEY")
    if not credential and client_factory is None:
        raise ProposalFailure(
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
        raise ProposalFailure(
            "InfrastructureFailure",
            "responses_client_init_failed",
            "cannot initialize the proposal Responses client",
            original_code=type(exc).__name__,
            original_message=_safe_message(exc, credential),
        ) from exc

    public_trace: list[JSONObject] = []
    usage: list[JSONObject | None] = []
    history: list[Any] = []
    provider_turns = 0
    try:
        with prepared.open(instance) as session:
            actor = session.actor
            try:
                reset_observation = actor.reset(reset_start)
                catalog = validate_tool_catalog(actor.tools(), role="proposal tools()")
                before_state = prepared.read_state(instance)
            except Exception as exc:
                raise _environment_failure("proposal_reset_failed", exc) from exc
            history.append(
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "development_brief": development_brief,
                            "reset_observation": reset_observation,
                            "prior_accepted_instructions": list(prior_instructions),
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                }
            )
            fields: _ProposalFields | None = None
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
                    raise ProposalFailure(
                        "CandidateRejected",
                        "proposal_terminal_missing",
                        "proposal Agent returned neither a public tool call nor a proposal",
                    )
                if not public_trace:
                    raise ProposalFailure(
                        "CandidateRejected",
                        "proposal_public_action_missing",
                        "proposal requires at least one real public tool action",
                    )
                try:
                    fields = _proposal_fields(output_text)
                except ValueError as exc:
                    history.append(
                        {
                            "role": "user",
                            "content": (
                                "The deterministic Host rejected the proposal. Rejected "
                                f"condition: {exc}. Return the complete corrected proposal in "
                                "the required output shape; do not repeat completed tool calls."
                            ),
                        }
                    )
                    continue
                break
            if fields is None:
                raise ProposalFailure(
                    "CandidateRejected",
                    "proposal_turn_budget_exhausted",
                    "proposal Agent exhausted its provider-turn budget",
                    max_provider_turns=selected_route.max_provider_turns,
                )
        try:
            after_state = prepared.read_state(instance)
        except Exception as exc:
            raise _environment_failure("proposal_state_read_failed", exc) from exc
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()

    evidence = TaskProposalEvidence(
        TASK_PROPOSAL_EVIDENCE_FORMAT,
        prepared.identity.release_id,
        reset_start,
        reset_observation,
        before_state,
        after_state,
        tuple(public_trace),
        fields.proposed_final_answer,
    )
    candidate = CandidateTaskContract(
        CANDIDATE_TASK_FORMAT,
        prepared.identity.release_id,
        builder_projection_digest,
        reset_start,
        fields.instruction,
        fields.final_answer_schema,
        fields.checker_brief,
        evidence.evidence_id,
    )
    return ProposedTask(candidate, evidence, provider_turns, tuple(usage))


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
    instructions: str = _SYSTEM_PROMPT,
    response_schema: JSONObject = _PROPOSAL_SCHEMA,
    response_name: str = "candidate_task_proposal",
) -> Any:
    request = {
        "model": route.model,
        "instructions": instructions,
        "input": list(history),
        "tools": [_response_tool(spec) for spec in catalog.values()],
        "tool_choice": "auto" if has_public_action else "required",
        "parallel_tool_calls": False,
        "text": {
            "format": {
                "type": "json_schema",
                "name": response_name,
                "schema": response_schema,
                "strict": True,
            }
        },
        "store": False,
    }
    try:
        return client.responses.create(**request)
    except Exception as exc:
        raise ProposalFailure(
            _provider_failure_kind(exc),
            "proposal_provider_turn_failed",
            "proposal Responses turn failed",
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
        raise ProposalFailure(
            "CandidateRejected",
            "proposal_tool_call_id_invalid",
            "proposal tool call omitted its call_id",
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
                "result": {
                    "kind": "source",
                    "source": {
                        "kind": "observation",
                        "step": 1,
                        "pointer": "/data/public_result",
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
    if not set(target.required_focus_tools).issubset(tools):
        raise SamplingFailure(
            "DraftRejected",
            "draft_focus_tool_missing",
            "required focus tools must participate in the objective",
            required=list(target.required_focus_tools),
            actual=sorted(tools),
        )
    changed = canonical_bytes(before_state) != canonical_bytes(after_state)
    if target.required_outcome == "transition" and not changed:
        raise SamplingFailure(
            "DraftRejected", "draft_transition_noop", "transition target made no state change"
        )
    if target.required_outcome != "transition" and changed:
        raise SamplingFailure(
            "DraftRejected",
            "draft_nontransition_changed_state",
            "query/refusal target changed protected state",
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
            )


def _as_sampling_failure(exc: ProposalFailure) -> SamplingFailure:
    kind: SamplingFailureKind = (
        "DraftRejected" if exc.kind == "CandidateRejected" else cast(SamplingFailureKind, exc.kind)
    )
    return SamplingFailure(kind, exc.code, str(exc), **exc.details)


def _proposal_fields(output_text: str) -> _ProposalFields:
    try:
        document = json.loads(output_text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"proposal is not JSON: {exc}") from exc
    try:
        validate_instance(document, _PROPOSAL_SCHEMA, role="candidate Task proposal")
    except SchemaError as exc:
        raise ValueError(str(exc)) from exc
    assert isinstance(document, dict)
    answer_schema = _nested_object(document["final_answer_schema_json"], "final_answer_schema")
    answer = _nested_object(document["proposed_final_answer_json"], "proposed_final_answer")
    try:
        CandidateTaskContract(
            CANDIDATE_TASK_FORMAT,
            "0" * 64,
            "0" * 64,
            None,
            cast(str, document["instruction"]),
            answer_schema,
            cast(str, document["checker_brief"]),
            "0" * 64,
        )
        validate_instance(answer, answer_schema, role="proposed_final_answer")
        wire_answer_schema = project_responses_strict_schema(answer_schema)
        validate_instance(
            answer,
            wire_answer_schema,
            role="Responses-compatible proposed_final_answer",
        )
    except (SchemaError, ValueError) as exc:
        raise ValueError(str(exc)) from exc
    return _ProposalFields(
        cast(str, document["instruction"]),
        cast(str, document["checker_brief"]),
        answer_schema,
        answer,
    )


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
        raise ProposalFailure(
            "InfrastructureFailure",
            "proposal_response_output_invalid",
            "proposal Responses output must be an item sequence",
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
        raise ProposalFailure(
            "InfrastructureFailure",
            "proposal_usage_invalid",
            "proposal Responses usage must be a JSON object",
        )
    return cast(JSONObject, json.loads(json.dumps(value, ensure_ascii=False)))


def _item(value: Any, name: str) -> Any:
    return value.get(name) if isinstance(value, Mapping) else getattr(value, name, None)


def _fresh_instance_path(path: Path) -> Path:
    selected = Path(path)
    if selected.is_symlink() or (
        selected.exists() and (not selected.is_dir() or any(selected.iterdir()))
    ):
        raise ProposalFailure(
            "CandidateRejected",
            "proposal_instance_not_fresh",
            "proposal instance_directory must be absent or empty",
        )
    return selected.resolve()


def _environment_failure(code: str, exc: Exception) -> ProposalFailure:
    kind: ProposalFailureKind = (
        "InfrastructureFailure"
        if getattr(exc, "kind", None) == "InfrastructureFailure"
        else "EnvironmentDefect"
    )
    return ProposalFailure(
        kind,
        code,
        str(exc),
        original_code=type(exc).__name__,
        original_message=str(exc),
    )


def _safe_message(exc: Exception, credential: str | None) -> str:
    message = str(exc)
    return message.replace(credential, "[REDACTED]") if credential else message


def _provider_failure_kind(exc: Exception) -> ProposalFailureKind:
    return (
        "FrameworkDefect"
        if getattr(exc, "status_code", None) in {400, 422}
        else "InfrastructureFailure"
    )


def _json_copy(value: JSONValue) -> JSONValue:
    return cast(JSONValue, json.loads(json.dumps(value, ensure_ascii=False)))


def _object_copy(value: JSONObject) -> JSONObject:
    return cast(JSONObject, _json_copy(value))


__all__ = [
    "ClientFactory",
    "PreparedTaskEnvironment",
    "ProposalFailure",
    "ProposalFailureKind",
    "ProposedTask",
    "SampledTaskDraft",
    "SamplingFailure",
    "SamplingFailureKind",
    "TASK_SAMPLING_EVIDENCE_FORMAT",
    "TaskSamplingEvidence",
    "propose_task_direct",
    "sample_task_draft",
]
