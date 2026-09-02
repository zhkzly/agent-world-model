"""Official OpenAI Responses adapters for Slice 2 Research and Evidence Review.

The Research producer owns an adaptive function-tool loop.  Every continuation
resends the exact prior Responses output-item objects plus matching
``function_call_output`` items because the configured endpoint does not retain
``previous_response_id`` state.  The independent Evidence Reviewer starts from a fresh
request and never receives producer history.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, cast

from jsonschema import Draft202012Validator
from openai import OpenAI

from agent_env_foundry.research import (
    RESEARCH_DRAFT_SCHEMA,
    DevelopmentBrief,
    DraftValidationError,
    EvidenceIntegrityError,
    EvidenceReview,
    NeedRecord,
    NotReleased,
    ResearchFailure,
    ResearchReady,
    ResearchTools,
    Unsupported,
    aggregate_evidence_review,
    derive_development_brief,
    finalize_research,
    validate_evidence_review,
)

_PROVIDER_TURN_TIMEOUT_SECONDS = 180.0

__all__ = [
    "AgentRoute",
    "BriefEvidenceReviewer",
    "ResponsesResearchAgent",
    "load_research_skill",
    "run_research",
]


class _ResearchToolSurface(Protocol):
    def search_sources(self, *, queries: Sequence[Mapping[str, Any]]) -> dict[str, Any]: ...

    def read_sources(self, *, entries: Sequence[Mapping[str, Any]]) -> dict[str, Any]: ...


class _ResponsesResource(Protocol):
    def create(self, **kwargs: Any) -> Any: ...


class _ResponsesClient(Protocol):
    responses: _ResponsesResource


class ClientFactory(Protocol):
    def __call__(self, *, api_key: str, base_url: str, max_retries: int) -> _ResponsesClient: ...


@dataclass(frozen=True)
class AgentRoute:
    """Non-secret, invocation-local route facts; the credential is never a field."""

    base_url: str = "http://127.0.0.1:8317/v1"
    model: str = "gpt-5.6-luna"
    max_provider_turns: int = 24

    def __post_init__(self) -> None:
        if self.base_url != "http://127.0.0.1:8317/v1":
            raise ValueError("Slice 2 Research route must use http://127.0.0.1:8317/v1")
        if self.model != "gpt-5.6-luna":
            raise ValueError("Slice 2 Research model must be exactly gpt-5.6-luna")
        if self.max_provider_turns <= 0:
            raise ValueError("max_provider_turns must be positive")


@dataclass
class _ProviderTurnBudget:
    limit: int
    used: int = 0

    def consume(
        self,
        *,
        phase: str,
        original_code: str = "budget_exhausted",
        original_message: str = "no provider turns remaining",
    ) -> None:
        if self.used >= self.limit:
            raise ResearchFailure(
                phase=phase,
                code="provider_turn_budget_exhausted",
                message="Provider turn budget exhausted before semantic closure",
                details={
                    "original_code": original_code,
                    "original_message": original_message,
                    "max_provider_turns": self.limit,
                },
            )
        self.used += 1


@dataclass(frozen=True)
class ResearchSkill:
    path: str
    text: str


def load_research_skill() -> ResearchSkill:
    path = Path(__file__).parent / "runtime_skills" / "research" / "SKILL.md"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ResearchFailure(
            phase="agent",
            code="research_skill_unreadable",
            message="the sole Research Skill could not be read",
            details={
                "original_code": type(exc).__name__,
                "original_message": str(exc),
                "path": str(path),
            },
        ) from exc
    return ResearchSkill(path=str(path), text=text)


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


_SEARCH_TOOL = {
    "type": "function",
    "name": "search_sources",
    "description": (
        "Discover SearXNG candidates for Agent-authored queries that target one unresolved "
        "Research Agenda question. Candidates and snippets are discovery-only and cannot be "
        "cited as evidence."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "queries": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "focus": {"type": "string"},
                    },
                    "required": ["query", "focus"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["queries"],
        "additionalProperties": False,
    },
    "strict": True,
}
_READ_TOOL = {
    "type": "function",
    "name": "read_sources",
    "description": (
        "Read Agent-selected sources in caller priority order. Each entry is an object "
        "{source, focus}: the source is a candidate handle, an absolute http(s) URL, or a "
        "retained S-number source handle; the focus is one narrow Agent-authored question "
        "whose exact passages should be projected. Only a small bounded set of exact passages "
        "per entry is returned. It never searches for substitutes or summarizes a source."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "entries": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "source": {"type": "string"},
                        "focus": {"type": "string"},
                    },
                    "required": ["source", "focus"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["entries"],
        "additionalProperties": False,
    },
    "strict": True,
}

_MODEL_PROTECTED_ID = re.compile(
    r"(?:source-revision|extraction|passage)-[0-9a-f]{64}|"
    r"(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f])"
)


def _model_safe_feedback_text(value: str) -> str:
    return _MODEL_PROTECTED_ID.sub("[PROTECTED_ID]", value)


class ResponsesResearchAgent:
    """One adaptive Research producer with exactly two visible function tools."""

    def __init__(
        self,
        *,
        tools: _ResearchToolSurface,
        route: AgentRoute | None = None,
        client_factory: ClientFactory | None = None,
        provider_budget: _ProviderTurnBudget | None = None,
    ) -> None:
        self.tools = tools
        self.route = route or AgentRoute()
        self._client_factory = client_factory or _default_client_factory
        self._provider_budget = provider_budget or _ProviderTurnBudget(
            self.route.max_provider_turns
        )

    def run(
        self,
        need: NeedRecord,
        *,
        final_validator: Callable[[dict[str, Any]], Mapping[str, Any] | None] | None = None,
    ) -> dict[str, Any]:
        skill = load_research_skill()
        input_text = (
            "Research this Need into the required structured Research Draft.\n\n"
            "Need and host-assigned coverage anchors (mechanical addressing aids, never "
            "semantic authority):\n"
            f"{json.dumps(need.to_document(), ensure_ascii=False, sort_keys=True)}\n\n"
            "Before your first `search_sources` call, form a run-local Research Agenda with "
            "unresolved questions across world, success, refusal, dynamics, initial, authority, "
            "scope, and substrate. Every search query and focus must target one unresolved "
            "Agenda question; every focused read must name the same question it is meant to "
            "close. Use the method Skill and adapt calls to remaining semantic gaps. A citation "
            "is valid only "
            "when it uses an exact E-number returned by a focused read_sources call. Mark each "
            "requirement basis as need or external_evidence. Every original Need clause must be "
            "accepted with mapped requirements or explicitly proposed unsupported; do not relabel "
            "a Need clause as contract, assumption, or exclusion. Fixed package mechanics reach "
            "Builder separately and require no web evidence. When the Need "
            "permits multiple coherent synthetic worlds, select and disclose one bounded variant "
            "instead of treating the missing stakeholder preference as a core gap. Stop only at "
            "semantic closure: every Need anchor is mapped or explicitly proposed unsupported; "
            "every accepted external fact is cited; every core success has an observable "
            "precondition and postcondition; every refusal names its prohibited mutation; the "
            "initial world exercises meaningful success and refusal relations; contradictions "
            "are resolved or disclosed; and no open gap can change core behavior."
        )
        return _run_tool_json_loop(
            route=self.route,
            client_factory=self._client_factory,
            instructions=skill.text,
            input_text=input_text,
            schema_name="research_draft",
            schema=RESEARCH_DRAFT_SCHEMA,
            tools=(_SEARCH_TOOL, _READ_TOOL),
            dispatch={
                "search_sources": self.tools.search_sources,
                "read_sources": self.tools.read_sources,
            },
            final_validator=final_validator,
            provider_budget=self._provider_budget,
        )


_EVIDENCE_REFERENCE_SCHEMA = {
    "type": "object",
    "properties": {"evidence_handle": {"type": "string"}},
    "required": ["evidence_handle"],
    "additionalProperties": False,
}

_EVIDENCE_REVIEW_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "clause_findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "clause_id": {"type": "string"},
                    "judgment": {
                        "type": "string",
                        "enum": [
                            "supported",
                            "omitted",
                            "contradicted",
                            "unjustified_narrowing",
                        ],
                    },
                    "rationale": {"type": "string"},
                    "evidence_refs": {
                        "type": "array",
                        "items": _EVIDENCE_REFERENCE_SCHEMA,
                    },
                },
                "required": [
                    "clause_id",
                    "judgment",
                    "rationale",
                    "evidence_refs",
                ],
                "additionalProperties": False,
            },
        },
        "requirement_findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "requirement_id": {"type": "string"},
                    "judgment": {
                        "type": "string",
                        "enum": [
                            "supported",
                            "not_entailed",
                            "contradicted",
                            "authority_mismatch",
                        ],
                    },
                    "rationale": {"type": "string"},
                    "evidence_refs": {
                        "type": "array",
                        "items": _EVIDENCE_REFERENCE_SCHEMA,
                    },
                },
                "required": [
                    "requirement_id",
                    "judgment",
                    "rationale",
                    "evidence_refs",
                ],
                "additionalProperties": False,
            },
        },
        "scope_assessment": {
            "type": "object",
            "properties": {
                "judgment": {
                    "type": "string",
                    "enum": ["supported", "acceptable_selection", "unjustified_narrowing"],
                },
                "rationale": {"type": "string"},
            },
            "required": ["judgment", "rationale"],
            "additionalProperties": False,
        },
        "residual_limitations": {"type": "array", "items": {"type": "string"}},
        "unsupported_findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "clause_id": {"type": "string"},
                    "evidence_refs": {
                        "type": "array",
                        "items": _EVIDENCE_REFERENCE_SCHEMA,
                    },
                    "rationale": {"type": "string"},
                },
                "required": ["clause_id", "evidence_refs", "rationale"],
                "additionalProperties": False,
            },
        },
    },
    "required": [
        "clause_findings",
        "requirement_findings",
        "scope_assessment",
        "residual_limitations",
        "unsupported_findings",
    ],
    "additionalProperties": False,
}


class BriefEvidenceReviewer:
    """Fresh semantic reviewer; Host code owns validation and action aggregation."""

    def __init__(
        self,
        *,
        route: AgentRoute | None = None,
        client_factory: ClientFactory | None = None,
        provider_budget: _ProviderTurnBudget | None = None,
    ) -> None:
        self.route = route or AgentRoute()
        self._client_factory = client_factory or _default_client_factory
        self._provider_budget = provider_budget or _ProviderTurnBudget(
            self.route.max_provider_turns
        )

    def review(self, *, need: NeedRecord, brief: DevelopmentBrief) -> EvidenceReview:
        input_text = (
            "Independently review the frozen Development Brief. Emit typed findings only; Host "
            "code owns accept, revise, unsupported, and not-released decisions. Check every Need "
            "clause and every Brief requirement, exact evidence entailment, contradictions, and "
            "unjustified narrowing. Keep disclosed non-blocking limits only in "
            "residual_limitations. Do not infer from a producer conversation; none is provided.\n\n"
            "# Need\n"
            f"{json.dumps(need.to_document(), ensure_ascii=False, sort_keys=True)}\n\n"
            f"{brief.review_evidence_index.to_model_markdown()}\n\n"
            "# Bounded Development Brief projection\n"
            f"{json.dumps(brief.to_model_document(), ensure_ascii=False, sort_keys=True)}"
        )

        def review_from_document(document: dict[str, Any]) -> EvidenceReview:
            return EvidenceReview(
                clause_findings=tuple(cast(list[dict[str, Any]], document["clause_findings"])),
                requirement_findings=tuple(
                    cast(list[dict[str, Any]], document["requirement_findings"])
                ),
                scope_assessment=cast(dict[str, Any], document["scope_assessment"]),
                residual_limitations=tuple(cast(list[str], document["residual_limitations"])),
                unsupported_findings=tuple(
                    cast(list[dict[str, Any]], document["unsupported_findings"])
                ),
            )

        def validate_review(document: dict[str, Any]) -> None:
            if _MODEL_PROTECTED_ID.search(json.dumps(document, ensure_ascii=False, sort_keys=True)):
                raise ResearchFailure(
                    phase="reviewer",
                    code="reviewer_raw_identifier_forbidden",
                    message="reviewer output must use short evidence handles, never raw 64-hex IDs",
                    details={
                        "original_code": "protected_identifier",
                        "original_message": "raw 64-hex identifier",
                    },
                )
            validate_evidence_review(brief=brief, review=review_from_document(document))
            return

        document = _run_fresh_json_turn(
            route=self.route,
            client_factory=self._client_factory,
            instructions=(
                "Return typed findings, never a global or terminal verdict. Every clause is "
                "authorized by the original Need; selected variants belong only in the scope "
                "assessment. Independently check whether each requirement's declared basis is "
                "valid and use authority_mismatch when it is not. Preserve event and "
                "predicate identity: invoice issuance evidence cannot support payment-due timing. "
                "A coherent disclosed jurisdiction or workflow choice is acceptable_selection in "
                "scope; the same hidden narrowing is unjustified_narrowing. Put non-blocking "
                "incompleteness only in residual_limitations; any real defect must be a typed "
                "blocking finding. Emit unsupported_findings=[] unless an explicit Need clause "
                "cannot form any coherent evidence-grounded world; never claim unsupported merely "
                "because sources were inaccessible or a taxonomy is not exhaustive."
            ),
            input_text=input_text,
            schema_name="evidence_review",
            schema=_EVIDENCE_REVIEW_SCHEMA,
            final_validator=validate_review,
            provider_budget=self._provider_budget,
        )
        return review_from_document(document)


def run_research(
    *,
    need: NeedRecord,
    tools: ResearchTools,
    route: AgentRoute | None = None,
    client_factory: ClientFactory | None = None,
) -> ResearchReady | NotReleased | Unsupported:
    """Direct Slice 2 coordinator: producer -> Host aggregation -> fresh reviewer."""
    selected_route = route or AgentRoute()
    provider_budget = _ProviderTurnBudget(selected_route.max_provider_turns)
    accepted_brief: DevelopmentBrief | None = None
    terminal_review: EvidenceReview | None = None

    def validate_and_review_draft(draft: dict[str, Any]) -> Mapping[str, Any] | None:
        nonlocal accepted_brief, terminal_review
        brief = derive_development_brief(need=need, draft=draft, store=tools.store)
        review = BriefEvidenceReviewer(
            route=selected_route,
            client_factory=client_factory,
            provider_budget=provider_budget,
        ).review(need=need, brief=brief)
        action = aggregate_evidence_review(brief=brief, review=review)
        if action == "REVISE":
            return {
                "review_action": action,
                "clause_findings": [_json_safe(item) for item in review.clause_findings],
                "requirement_findings": [_json_safe(item) for item in review.requirement_findings],
                "scope_assessment": _json_safe(review.scope_assessment),
                "residual_limitations": list(review.residual_limitations),
                "unsupported_findings": [_json_safe(item) for item in review.unsupported_findings],
                "declared_open_gaps": _json_safe(brief.draft.get("open_gaps", [])),
                "authority_reminder": (
                    "The original Need is authority for need-basis requirements. External facts "
                    "require exact evidence handles. Canonical reset/tools/invoke/close, "
                    "reconstruction, validation atomicity, and isolation are host contract "
                    "authority and must not be recast as externally evidenced Research claims."
                ),
            }
        accepted_brief = brief
        terminal_review = review
        return None

    try:
        ResponsesResearchAgent(
            tools=tools,
            route=selected_route,
            client_factory=client_factory,
            provider_budget=provider_budget,
        ).run(
            need,
            final_validator=validate_and_review_draft,
        )
        if accepted_brief is None or terminal_review is None:
            raise ResearchFailure(
                phase="research",
                code="terminal_review_missing",
                message="Research producer returned without a terminal fresh evidence review",
                details={
                    "original_code": "internal_state_error",
                    "original_message": "accepted_brief or terminal_review is missing",
                },
            )
        return finalize_research(
            brief=accepted_brief,
            review=terminal_review,
        )
    except EvidenceIntegrityError as exc:
        return NotReleased(
            code=exc.code,
            message=exc.message,
            details={
                "phase": exc.phase,
                **exc.details,
            },
        )
    except DraftValidationError as exc:
        return NotReleased(
            code="research_evidence_invalid",
            message=str(exc),
            details={
                "phase": "brief",
                "original_code": type(exc).__name__,
                "original_message": str(exc),
            },
        )
    except ResearchFailure as exc:
        return NotReleased(
            code=exc.code,
            message=exc.message,
            details={
                "phase": exc.phase,
                **exc.details,
            },
        )


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


def _credential() -> str:
    credential = os.environ.get("OPENAI_API_KEY")
    if not credential:
        raise ResearchFailure(
            phase="agent",
            code="missing_openai_api_key",
            message="OPENAI_API_KEY must be supplied at invocation time",
            details={
                "original_code": "missing_environment_variable",
                "original_message": "OPENAI_API_KEY is unset or empty",
            },
        )
    return credential


def _run_tool_json_loop(
    *,
    route: AgentRoute,
    client_factory: ClientFactory,
    instructions: str,
    input_text: str,
    schema_name: str,
    schema: Mapping[str, Any],
    tools: Sequence[Mapping[str, Any]],
    dispatch: Mapping[str, Callable[..., dict[str, Any]]],
    final_validator: Callable[[dict[str, Any]], Mapping[str, Any] | None] | None = None,
    provider_budget: _ProviderTurnBudget,
    output_code: str = "research_draft_invalid",
    strict_output: bool = True,
) -> dict[str, Any]:
    for tool in tools:
        parameters = tool.get("parameters")
        if not isinstance(parameters, Mapping):
            raise ResearchFailure(
                phase="provider_schema",
                code="function_parameters_schema_missing",
                message="function tool parameters must be a JSON Schema object",
                details={
                    "original_code": type(parameters).__name__,
                    "original_message": repr(parameters),
                    "function": str(tool.get("name")),
                },
            )
    credential = _credential()
    client = client_factory(api_key=credential, base_url=route.base_url, max_retries=0)
    history: list[Any] = [{"role": "user", "content": input_text}]
    next_phase = "agent"
    next_original_code = "budget_exhausted"
    next_original_message = "no provider turns remaining"
    try:
        while True:
            provider_budget.consume(
                phase=next_phase,
                original_code=next_original_code,
                original_message=next_original_message,
            )
            request = {
                "model": route.model,
                "instructions": instructions,
                "input": history,
                "tools": [dict(item) for item in tools],
                "tool_choice": "auto",
                "parallel_tool_calls": False,
                "text": {
                    "format": {
                        "type": "json_schema",
                        "name": schema_name,
                        "schema": dict(schema),
                        "strict": strict_output,
                    }
                },
                "store": False,
            }
            try:
                response = client.responses.create(**request)
            except Exception as exc:
                if _retryable_provider_failure(exc):
                    next_phase = "infrastructure"
                    next_original_code = type(exc).__name__
                    next_original_message = str(exc).replace(credential, "[REDACTED]")
                    continue
                raise
            next_phase = "agent"
            next_original_code = "budget_exhausted"
            next_original_message = "no provider turns remaining"
            output_items = list(cast(Sequence[Any], _item_value(response, "output") or ()))
            # Preserve every provider item object exactly as returned.  Do not dump,
            # summarize, reorder, or replace it before the next request.
            history.extend(output_items)
            function_calls = [
                item for item in output_items if _item_value(item, "type") == "function_call"
            ]
            if function_calls:
                for call in function_calls:
                    name = _item_value(call, "name")
                    arguments_text = _item_value(call, "arguments")
                    call_id = _item_value(call, "call_id")
                    if not isinstance(name, str) or name not in dispatch:
                        raise ResearchFailure(
                            phase="agent",
                            code="unknown_function_call",
                            message=(
                                "provider requested a function outside the allowed tool surface"
                            ),
                            details={
                                "original_code": "unknown_function",
                                "original_message": str(name),
                            },
                        )
                    if not isinstance(arguments_text, str) or not isinstance(call_id, str):
                        raise ResearchFailure(
                            phase="agent",
                            code="malformed_function_call",
                            message="provider function call omitted arguments or call_id",
                            details={
                                "original_code": "malformed_function_call",
                                "original_message": repr(call),
                            },
                        )
                    try:
                        arguments = json.loads(arguments_text)
                    except json.JSONDecodeError as exc:
                        raise ResearchFailure(
                            phase="agent",
                            code="invalid_function_arguments_json",
                            message="provider emitted invalid JSON function arguments",
                            details={
                                "original_code": type(exc).__name__,
                                "original_message": str(exc),
                                "function": name,
                            },
                        ) from exc
                    if not isinstance(arguments, dict):
                        raise ResearchFailure(
                            phase="agent",
                            code="invalid_function_arguments_shape",
                            message="provider function arguments must decode to an object",
                            details={
                                "original_code": type(arguments).__name__,
                                "original_message": repr(arguments),
                                "function": name,
                            },
                        )
                    tool_result = dispatch[name](**arguments)
                    history.append(
                        {
                            "type": "function_call_output",
                            "call_id": call_id,
                            "output": json.dumps(
                                tool_result,
                                ensure_ascii=False,
                                sort_keys=True,
                                separators=(",", ":"),
                            ),
                        }
                    )
                continue
            output_text = _item_value(response, "output_text")
            if not isinstance(output_text, str) or not output_text.strip():
                raise ResearchFailure(
                    phase="agent",
                    code="missing_structured_output",
                    message="provider returned neither a function call nor structured final text",
                    details={
                        "original_code": "empty_output_text",
                        "original_message": str(output_text),
                    },
                )
            document = _parse_and_validate_json(
                output_text, schema=schema, phase="agent", code=output_code
            )
            if final_validator is not None:
                try:
                    revision_feedback = final_validator(document)
                except DraftValidationError as exc:
                    # Only a correctable Draft defect returns to the producer.
                    # Host-owned typed outcomes (EvidenceIntegrityError and
                    # provider failures) never become
                    # another provider turn.
                    next_phase = "brief"
                    next_original_code = type(exc).__name__
                    next_original_message = str(exc)
                    history.append(
                        {
                            "role": "user",
                            "content": (
                                "The deterministic host rejected the Research Draft. "
                                f"Rejected condition: {_model_safe_feedback_text(str(exc))}. "
                                "Return a complete corrected Draft; copy evidence handles exactly "
                                "from read_sources, "
                                "and call the tools again if evidence is still missing."
                            ),
                        }
                    )
                    continue
                if revision_feedback is not None:
                    next_phase = "research_review"
                    next_original_code = "review_requires_revision"
                    next_original_message = json.dumps(
                        dict(revision_feedback),
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                    history.append(
                        {
                            "role": "user",
                            "content": (
                                "A new independent Evidence Reviewer returned blocking typed "
                                "findings. Revise the complete Draft in this same Research "
                                "history; "
                                "search or perform "
                                "another focused read when the feedback identifies an evidence "
                                "gap. Structured feedback:\n"
                                + json.dumps(
                                    dict(revision_feedback),
                                    ensure_ascii=False,
                                    sort_keys=True,
                                    separators=(",", ":"),
                                )
                            ),
                        }
                    )
                    continue
            return document
    except ResearchFailure:
        raise
    except Exception as exc:
        safe_message = str(exc).replace(credential, "[REDACTED]")
        raise ResearchFailure(
            phase="agent",
            code="responses_request_failed",
            message="OpenAI Responses tool turn failed with no provider fallback",
            details={
                "original_code": type(exc).__name__,
                "original_message": safe_message,
            },
        ) from exc


def _run_fresh_json_turn(
    *,
    route: AgentRoute,
    client_factory: ClientFactory,
    instructions: str,
    input_text: str,
    schema_name: str,
    schema: Mapping[str, Any],
    final_validator: Callable[[dict[str, Any]], None] | None = None,
    provider_budget: _ProviderTurnBudget,
    failure_phase: str = "reviewer",
    feedback_subject: str = "Evidence Review",
    feedback_instruction: str = (
        "Return a complete corrected review; copy evidence handles exactly "
        "from the bounded Evidence Index."
    ),
) -> dict[str, Any]:
    credential = _credential()
    client = client_factory(api_key=credential, base_url=route.base_url, max_retries=0)
    history: list[Any] = [{"role": "user", "content": input_text}]
    next_original_code = "budget_exhausted"
    next_original_message = "no provider turns remaining"
    try:
        while True:
            provider_budget.consume(
                phase=failure_phase,
                original_code=next_original_code,
                original_message=next_original_message,
            )
            request = {
                "model": route.model,
                "instructions": instructions,
                "input": history,
                "tools": [],
                "text": {
                    "format": {
                        "type": "json_schema",
                        "name": schema_name,
                        "schema": dict(schema),
                        "strict": True,
                    }
                },
                "store": False,
            }
            response = client.responses.create(**request)
            history.extend(list(cast(Sequence[Any], _item_value(response, "output") or ())))
            output_text = _item_value(response, "output_text")
            if not isinstance(output_text, str) or not output_text.strip():
                raise ResearchFailure(
                    phase=failure_phase,
                    code="missing_structured_output",
                    message="reviewer returned no structured final text",
                    details={
                        "original_code": "empty_output_text",
                        "original_message": str(output_text),
                    },
                )
            document = _parse_and_validate_json(
                output_text,
                schema=schema,
                phase=failure_phase,
                code=f"{failure_phase}_output_invalid",
            )
            if final_validator is not None:
                try:
                    final_validator(document)
                except ResearchFailure as exc:
                    next_original_code = exc.code
                    next_original_message = str(exc)
                    safe_details = _model_safe_feedback_text(
                        json.dumps(exc.details, ensure_ascii=False, sort_keys=True)
                    )
                    history.append(
                        {
                            "role": "user",
                            "content": (
                                f"The deterministic host rejected the {feedback_subject}. "
                                f"Rejected condition: {_model_safe_feedback_text(str(exc))}. "
                                "Machine details: "
                                f"{safe_details}. "
                                f"{feedback_instruction}"
                            ),
                        }
                    )
                    continue
            return document
    except ResearchFailure:
        raise
    except Exception as exc:
        raise ResearchFailure(
            phase=failure_phase,
            code="responses_request_failed",
            message=f"fresh {feedback_subject} turn failed with no provider fallback",
            details={
                "original_code": type(exc).__name__,
                "original_message": str(exc).replace(credential, "[REDACTED]"),
            },
        ) from exc


def _retryable_provider_failure(exc: Exception) -> bool:
    status = getattr(exc, "status_code", None)
    if isinstance(status, int) and status in {408, 409, 429, 500, 502, 503, 504}:
        return True
    return type(exc).__name__ in {
        "APIConnectionError",
        "APITimeoutError",
        "ConnectError",
        "ReadTimeout",
    }


def _parse_and_validate_json(
    text: str, *, schema: Mapping[str, Any], phase: str, code: str
) -> dict[str, Any]:
    try:
        document = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ResearchFailure(
            phase=phase,
            code=code,
            message="structured response is not valid JSON",
            details={
                "original_code": type(exc).__name__,
                "original_message": str(exc),
            },
        ) from exc
    if not isinstance(document, dict):
        raise ResearchFailure(
            phase=phase,
            code=code,
            message="structured response root must be an object",
            details={
                "original_code": type(document).__name__,
                "original_message": repr(document),
            },
        )
    errors = sorted(Draft202012Validator(schema).iter_errors(document), key=str)
    if errors:
        error = errors[0]
        location = "$" + "".join(f"[{part!r}]" for part in error.absolute_path)
        raise ResearchFailure(
            phase=phase,
            code=code,
            message=f"structured response violates its schema at {location}",
            details={
                "original_code": error.validator,
                "original_message": error.message,
                "field_path": location,
            },
        )
    return cast(dict[str, Any], document)


def _item_value(item: Any, name: str) -> Any:
    if isinstance(item, Mapping):
        return item.get(name)
    return getattr(item, name, None)
