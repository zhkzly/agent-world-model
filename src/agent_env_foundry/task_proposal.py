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
from agent_env_foundry.jsonvalue import is_json_object
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

_PROVIDER_TURN_TIMEOUT_SECONDS = 180.0
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

ProposalFailureKind = Literal[
    "EnvironmentDefect",
    "FrameworkDefect",
    "InfrastructureFailure",
    "CandidateRejected",
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


@dataclass(frozen=True, slots=True)
class ProposedTask:
    candidate: CandidateTaskContract
    evidence: TaskProposalEvidence
    provider_turns: int
    usage: tuple[JSONObject | None, ...]


@dataclass(frozen=True, slots=True)
class _ProposalFields:
    instruction: str
    checker_brief: str
    final_answer_schema: JSONObject
    proposed_final_answer: JSONObject


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
) -> Any:
    request = {
        "model": route.model,
        "instructions": _SYSTEM_PROMPT,
        "input": list(history),
        "tools": [_response_tool(spec) for spec in catalog.values()],
        "tool_choice": "auto" if has_public_action else "required",
        "parallel_tool_calls": False,
        "text": {
            "format": {
                "type": "json_schema",
                "name": "candidate_task_proposal",
                "schema": _PROPOSAL_SCHEMA,
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


__all__ = [
    "ClientFactory",
    "PreparedTaskEnvironment",
    "ProposalFailure",
    "ProposalFailureKind",
    "ProposedTask",
    "propose_task_direct",
]
