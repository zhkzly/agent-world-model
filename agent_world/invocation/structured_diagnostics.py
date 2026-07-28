"""Secret-safe diagnostics for one-shot structured-response terminals.

The backend must never retain provider text merely to explain a malformed
response. These helpers derive a small closed vocabulary from the response
shape and JSON parser position, so Scheduler feedback can distinguish an
incompatible gateway from a semantic proposal without exposing the proposal.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import TypeGuard

from .contracts import InvocationError, JsonObject, JsonValue

_MAX_SAFE_RESPONSE_CHARACTERS = 2_000_000
_DIRECT_INVALID_JSON_CODE = "direct_structured_output_invalid_json"
_DIRECT_TRANSPORT_INVALID_CODE = "direct_structured_output_transport_invalid"
_DIRECT_OUTPUT_LIMIT_CODE = "direct_output_limit"
_DIRECT_INVALID_REQUEST_CODE = "direct_invalid_request"
_DIRECT_PROVIDER_STREAM_STALLED_CODE = "direct_provider_stream_stalled"
_DIRECT_PROVIDER_EXCEPTION_CODES = frozenset(
    {
        "direct_authentication_failed",
        "direct_model_unavailable",
        "direct_provider_rejected",
        "direct_provider_timeout",
        "direct_provider_unavailable",
        "direct_rate_limited",
    }
)
_PROVIDER_QUOTA_EXHAUSTED_CODE = "turn_failed_quota_exhausted"
_SESSION_BUDGET_EXHAUSTED_CODE = "turn_failed_session_budget_exhausted"
_USAGE_LIMIT_EXCEEDED_CODE = "turn_failed_usage_limit_exceeded"
_PROVIDER_REJECTED_CODE = "turn_failed_provider_rejected"
_PROVIDER_UNAVAILABLE_CODE = "turn_failed_provider_unavailable"
_PROVIDER_AUTHENTICATION_CODE = "turn_failed_authentication"
_PROVIDER_MODEL_UNAVAILABLE_CODE = "turn_failed_model_unavailable"
_PROVIDER_CONTEXT_WINDOW_CODE = "turn_failed_context_window"
_PROVIDER_OUTPUT_LIMIT_CODE = "turn_failed_output_limit"
_PROVIDER_OUTPUT_SCHEMA_CODE = "turn_failed_output_schema"
_PROVIDER_CONTENT_FILTERED_CODE = "turn_failed_content_filtered"
_PROVIDER_INVALID_REQUEST_CODE = "turn_failed_invalid_request"
_PROVIDER_SANDBOX_CODE = "turn_failed_sandbox_error"
_PROVIDER_THREAD_ROLLBACK_CODE = "turn_failed_thread_rollback"
_PROVIDER_UNCLASSIFIED_CODE = "turn_failed_unclassified_codex_error"
_SDK_EXECUTION_FAILED_CODE = "sdk_execution_failed"
# A configured output ceiling is a non-secret integer.  Diagnostic nodes may
# intentionally declare up to the same 10M ceiling as the generation budget,
# so feedback must not erase a legitimate 5M/10M value merely because older
# physical defaults were smaller.
_MAX_SAFE_OUTPUT_TOKEN_LIMIT = 10_000_000
_MAX_SAFE_DIRECT_STREAM_IDLE_SECONDS = 31_536_000
_MAX_SAFE_DIRECT_STREAM_EVENT_COUNT = 10_000_000
_NON_RETRYABLE_TERMINAL_CODES = frozenset(
    {
        _PROVIDER_REJECTED_CODE,
        _PROVIDER_QUOTA_EXHAUSTED_CODE,
        _SESSION_BUDGET_EXHAUSTED_CODE,
        _USAGE_LIMIT_EXCEEDED_CODE,
        _PROVIDER_AUTHENTICATION_CODE,
        _PROVIDER_MODEL_UNAVAILABLE_CODE,
        _PROVIDER_CONTEXT_WINDOW_CODE,
        _PROVIDER_OUTPUT_LIMIT_CODE,
        _PROVIDER_OUTPUT_SCHEMA_CODE,
        _PROVIDER_CONTENT_FILTERED_CODE,
        _PROVIDER_INVALID_REQUEST_CODE,
        _PROVIDER_SANDBOX_CODE,
        _PROVIDER_THREAD_ROLLBACK_CODE,
        _PROVIDER_UNCLASSIFIED_CODE,
        _DIRECT_INVALID_JSON_CODE,
        _DIRECT_TRANSPORT_INVALID_CODE,
        _DIRECT_OUTPUT_LIMIT_CODE,
        _DIRECT_INVALID_REQUEST_CODE,
    }
)
_RESPONSE_SHAPES = frozenset(
    {
        "empty",
        "markdown_fence",
        "object",
        "array",
        "string",
        "scalar",
        "literal",
        "non_json",
    }
)
_PARSE_FAILURES = frozenset({"syntax", "truncated", "extra_data", "nonfinite_number"})
_ENVELOPE_SHAPES = frozenset(
    {
        "artifact_json_string",
        "artifact_json_object",
        "artifact_json_array",
        "artifact_json_scalar",
        "non_envelope",
        "provider_ir",
    }
)
_CODEX_PROVIDER_ERROR_SHAPES = frozenset({"missing", "non_object", "object"})
_CODEX_PROVIDER_ERROR_INFO = frozenset(
    {
        "absent",
        "non_object",
        "object:other",
        "active_turn_not_steerable",
        "enum:contextwindowexceeded",
        "enum:sessionbudgetexceeded",
        "enum:usagelimitexceeded",
        "enum:serveroverloaded",
        "enum:internalservererror",
        "enum:unauthorized",
        "enum:badrequest",
        "enum:cyberpolicy",
        "enum:sandboxerror",
        "enum:threadrollbackfailed",
        "enum:other",
        "transport:http_connection_failed",
        "transport:response_stream_connection_failed",
        "transport:response_stream_disconnected",
        "transport:response_too_many_failed_attempts",
    }
)
_CODEX_ADVISORY_TEXT_SIGNALS = frozenset(
    {
        "authentication_or_authorization",
        "model_or_route_availability",
        "context_or_token_limit",
        "request_or_schema_compatibility",
        "capacity_or_rate_limit",
        "transport_or_connection",
        "timeout_or_deadline",
        "policy_or_content_filter",
        "provider_internal_error",
    }
)
_CODEX_OUTPUT_TERMINAL_STATUSES = frozenset({"incomplete"})
_CODEX_OUTPUT_TERMINAL_REASONS = frozenset({"max_output_tokens"})
_CODEX_WORKER_PHASES = frozenset(
    {
        "sdk_session_open",
        "thread_start",
        "thread_resume",
        "turn_start",
        "turn_stream",
        "unknown",
    }
)
_CODEX_TERMINAL_DETAIL_CODES = frozenset(
    {
        _PROVIDER_QUOTA_EXHAUSTED_CODE,
        _SESSION_BUDGET_EXHAUSTED_CODE,
        _USAGE_LIMIT_EXCEEDED_CODE,
        _PROVIDER_REJECTED_CODE,
        _PROVIDER_UNAVAILABLE_CODE,
        _PROVIDER_AUTHENTICATION_CODE,
        _PROVIDER_MODEL_UNAVAILABLE_CODE,
        _PROVIDER_CONTEXT_WINDOW_CODE,
        _PROVIDER_OUTPUT_LIMIT_CODE,
        _PROVIDER_OUTPUT_SCHEMA_CODE,
        _PROVIDER_CONTENT_FILTERED_CODE,
        _PROVIDER_INVALID_REQUEST_CODE,
        _PROVIDER_SANDBOX_CODE,
        _PROVIDER_THREAD_ROLLBACK_CODE,
        _PROVIDER_UNCLASSIFIED_CODE,
    }
)
_DIRECT_PROVIDER_ERROR_SHAPES = frozenset({"missing", "non_object", "object"})
_DIRECT_PROVIDER_ERROR_TYPES = frozenset(
    {
        "absent",
        "non_string",
        "invalid_request",
        "structured_output_schema",
        "request_parameter",
        "context_window",
        "other",
    }
)
_DIRECT_PROVIDER_ERROR_CODES = frozenset(
    {
        "absent",
        "non_string",
        "structured_output_schema",
        "request_parameter",
        "context_window",
        "model_route",
        "other",
    }
)
_DIRECT_PROVIDER_ERROR_PARAMS = frozenset(
    {
        "absent",
        "non_string",
        "structured_output_schema",
        "structured_output_format",
        "output_token_limit",
        "reasoning_effort",
        "model",
        "input",
        "instructions",
        "other",
    }
)


def direct_invalid_json_details(output_text: str, exc: Exception) -> JsonObject:
    """Classify malformed provider text without retaining a provider transcript."""

    return {
        "response_shape": _response_shape(output_text),
        "parse_failure": _parse_failure(output_text, exc),
        "parse_offset": _parse_offset(exc),
        "response_characters": min(len(output_text), _MAX_SAFE_RESPONSE_CHARACTERS),
    }


def direct_transport_decode_details(
    value: JsonValue,
    *,
    transport: str,
    exc: Exception,
) -> JsonObject:
    """Describe a decoded outer transport failure with no inner payload bytes."""

    if transport in {"provider_schema", "json_object"}:
        return {"transport": transport, "envelope_shape": "provider_ir"}
    if not isinstance(value, dict) or set(value) != {"artifact_json"}:
        return {"transport": "json_envelope", "envelope_shape": "non_envelope"}
    payload = value["artifact_json"]
    if isinstance(payload, str):
        return {
            "transport": "json_envelope",
            "envelope_shape": "artifact_json_string",
            **direct_invalid_json_details(payload, exc),
        }
    return {
        "transport": "json_envelope",
        "envelope_shape": _envelope_shape(payload),
    }


def direct_output_limit_details(*, configured_max_output_tokens: int) -> JsonObject:
    """Describe a provider output ceiling without retaining its response body.

    The value is the declared adapter request parameter, not an inference from
    provider prose.  Keeping it in a small bounded vocabulary lets the
    Scheduler distinguish a causal policy change from a semantic retry.
    """

    if (
        isinstance(configured_max_output_tokens, bool)
        or not isinstance(configured_max_output_tokens, int)
        or not 1 <= configured_max_output_tokens <= _MAX_SAFE_OUTPUT_TOKEN_LIMIT
    ):
        return {}
    return {
        "terminal_status": "incomplete",
        "terminal_reason": "max_output_tokens",
        "configured_max_output_tokens": configured_max_output_tokens,
    }


def direct_provider_stream_stalled_details(
    *,
    idle_timeout_seconds: float,
    observed_provider_event_count: int,
) -> JsonObject:
    """Describe a started Direct stream that went silent without retaining text.

    This terminal differs from a logical parent timeout: the request already
    crossed the Provider boundary and emitted at least one event, then its next
    stream event did not arrive before the resolved profile's explicit idle
    interval.
    """

    if (
        isinstance(idle_timeout_seconds, bool)
        or not isinstance(idle_timeout_seconds, (int, float))
        or not 0 < idle_timeout_seconds <= _MAX_SAFE_DIRECT_STREAM_IDLE_SECONDS
        or isinstance(observed_provider_event_count, bool)
        or not isinstance(observed_provider_event_count, int)
        or not 1 <= observed_provider_event_count <= _MAX_SAFE_DIRECT_STREAM_EVENT_COUNT
    ):
        return {}
    return {
        "waiting_phase": "direct_awaiting_stream_event",
        "idle_timeout_seconds": idle_timeout_seconds,
        "observed_provider_event_count": observed_provider_event_count,
    }


def direct_provider_exception_details(exc: Exception) -> JsonObject:
    """Project a Direct HTTP exception into a closed, secret-safe fingerprint.

    Provider ``message`` fields can contain request fragments, routes, or user
    content.  They are deliberately never retained.  The small vocabulary below
    is enough to distinguish a rejected structured-output schema from a profile
    parameter or context problem before deciding what kind of real execution to
    run next.
    """

    details: JsonObject = {}
    status_code: object = getattr(exc, "status_code", None)
    if _safe_http_status(status_code):
        details["http_status"] = status_code

    body: object = getattr(exc, "body", None)
    if body is None:
        details["provider_error_shape"] = "missing"
        return details
    if not isinstance(body, Mapping):
        details["provider_error_shape"] = "non_object"
        return details

    details["provider_error_shape"] = "object"
    error_body = _direct_provider_error_body(body)
    details["provider_error_type"] = _direct_provider_error_type(error_body.get("type"))
    details["provider_error_code"] = _direct_provider_error_code(error_body.get("code"))
    details["provider_error_param"] = _direct_provider_error_param(error_body.get("param"))
    return details


def _direct_provider_error_body(body: Mapping[object, object]) -> Mapping[object, object]:
    """Use a nested ``error`` object when the compatible gateway provides one."""

    nested = body.get("error")
    return nested if isinstance(nested, Mapping) else body


def _direct_provider_error_type(value: object) -> str:
    normalized = _normalized_provider_label(value)
    if normalized is None:
        return "absent" if value is None else "non_string"
    if normalized in {"invalid_request_error", "invalid_request"}:
        return "invalid_request"
    if normalized in {"invalid_json_schema", "json_schema_error"}:
        return "structured_output_schema"
    if normalized in {"unsupported_parameter", "invalid_parameter", "unknown_parameter"}:
        return "request_parameter"
    if normalized in {"context_length_exceeded", "context_window_exceeded"}:
        return "context_window"
    return "other"


def _direct_provider_error_code(value: object) -> str:
    normalized = _normalized_provider_label(value)
    if normalized is None:
        return "absent" if value is None else "non_string"
    if normalized in {
        "invalid_json_schema",
        "json_schema_error",
        "schema_validation_error",
        "invalid_response_format",
    }:
        return "structured_output_schema"
    if normalized in {"unsupported_parameter", "invalid_parameter", "unknown_parameter"}:
        return "request_parameter"
    if normalized in {"context_length_exceeded", "context_window_exceeded"}:
        return "context_window"
    if normalized in {"model_not_found", "model_not_available", "unsupported_model"}:
        return "model_route"
    return "other"


def _direct_provider_error_param(value: object) -> str:
    normalized = _normalized_provider_label(value)
    if normalized is None:
        return "absent" if value is None else "non_string"
    if normalized.startswith("text.format.schema") or normalized.startswith(
        "response_format.json_schema"
    ):
        return "structured_output_schema"
    if normalized in {"text.format", "response_format"}:
        return "structured_output_format"
    if normalized in {"max_output_tokens", "max_tokens"}:
        return "output_token_limit"
    if normalized in {"reasoning", "reasoning.effort"}:
        return "reasoning_effort"
    if normalized == "model":
        return "model"
    if normalized in {"input", "messages"}:
        return "input"
    if normalized == "instructions":
        return "instructions"
    return "other"


def _normalized_provider_label(value: object) -> str | None:
    return value.strip().casefold() if isinstance(value, str) else None


def safe_terminal_condition(error: InvocationError | None) -> str:
    """Return a bounded terminal condition without trusting provider text."""

    if error is None:
        return "the Agent backend returned a non-success terminal result"
    code = safe_terminal_code(error)
    if code == _DIRECT_INVALID_JSON_CODE:
        return _invalid_json_condition(safe_terminal_details(error))
    if code == _DIRECT_TRANSPORT_INVALID_CODE:
        return _transport_decode_condition(safe_terminal_details(error))
    if code == _DIRECT_OUTPUT_LIMIT_CODE:
        return _output_limit_condition(error.details)
    if code == _DIRECT_PROVIDER_STREAM_STALLED_CODE:
        return _direct_provider_stream_stalled_condition(safe_terminal_details(error))
    if code == _DIRECT_INVALID_REQUEST_CODE:
        return _direct_invalid_request_condition(safe_terminal_details(error))
    if code in _DIRECT_PROVIDER_EXCEPTION_CODES:
        return _direct_provider_exception_condition(code, safe_terminal_details(error))
    if code == _SDK_EXECUTION_FAILED_CODE:
        phase = safe_terminal_details(error).get("worker_phase")
        if phase == "thread_resume":
            return "the Codex SDK failed while restoring a prior thread before a new turn began"
        if phase == "thread_start":
            return "the Codex SDK failed while creating a new thread before a turn began"
        if phase == "turn_start":
            return "the Codex SDK failed while starting the requested turn"
        if phase == "turn_stream":
            return "the Codex SDK failed while streaming the requested turn"
        return "the Codex SDK failed before a terminal Agent result was available"
    if code == _PROVIDER_QUOTA_EXHAUSTED_CODE:
        return "the configured Provider reported that its quota is exhausted"
    if code == _SESSION_BUDGET_EXHAUSTED_CODE:
        return (
            "the Codex Agent session exhausted its declared rollout token budget "
            "before returning a result"
        )
    if code == _USAGE_LIMIT_EXCEEDED_CODE:
        return "the configured Provider reported that its usage limit is exhausted"
    if code == _PROVIDER_UNAVAILABLE_CODE:
        return _provider_unavailable_condition(safe_terminal_details(error))
    if code == _PROVIDER_REJECTED_CODE:
        return _provider_rejection_condition(safe_terminal_details(error))
    if code == _PROVIDER_AUTHENTICATION_CODE:
        return "the configured Provider rejected the Agent credential"
    if code == _PROVIDER_MODEL_UNAVAILABLE_CODE:
        return "the configured Provider does not offer the requested model route"
    if code == _PROVIDER_CONTEXT_WINDOW_CODE:
        return "the Provider rejected the turn because its context window was exceeded"
    if code == _PROVIDER_OUTPUT_LIMIT_CODE:
        return (
            "the Codex Provider ended this physical turn at its output-token ceiling before "
            "a completion was emitted"
        )
    if code == _PROVIDER_OUTPUT_SCHEMA_CODE:
        return "the Provider rejected the declared structured-output schema or transport"
    if code == _PROVIDER_CONTENT_FILTERED_CODE:
        return "the Provider blocked the turn under its content or safety policy"
    if code == _PROVIDER_INVALID_REQUEST_CODE:
        return "the Provider rejected the declared Agent request as invalid"
    if code == _PROVIDER_SANDBOX_CODE:
        return "the Codex runtime reported a sandbox error while executing the turn"
    if code == _PROVIDER_THREAD_ROLLBACK_CODE:
        return "the Codex runtime could not roll back the failed thread state"
    if code == _PROVIDER_UNCLASSIFIED_CODE:
        return _unclassified_terminal_condition(safe_terminal_details(error))
    return "the Agent backend returned a non-success terminal result"


def safe_terminal_expected_category(error: InvocationError | None) -> str | None:
    """Return a bounded next-result category when the terminal owns one.

    ``None`` deliberately preserves the framework's generic execution
    category.  Output exhaustion is different: the failed physical attempt
    cannot be replayed under the same immutable budget, but a Code Agent can
    choose between a newly declared larger budget and a smaller bounded output
    request after inspecting the node's real output shape.
    """

    code = safe_terminal_code(error)
    if code == _PROVIDER_QUOTA_EXHAUSTED_CODE:
        return (
            "restored Provider quota or an explicitly authorized model/provider route; "
            "do not issue a model correction or blind retry"
        )
    if code == _SDK_EXECUTION_FAILED_CODE and (
        safe_terminal_details(error).get("worker_phase") == "thread_resume"
    ):
        return (
            "a private Codex session-state/worker-lifecycle correction or an explicitly "
            "authorized fresh session; do not issue a model correction or blind retry"
        )
    if code == _SESSION_BUDGET_EXHAUSTED_CODE:
        return (
            "a new diagnostic definition with a larger declared rollout-token budget, a "
            "smaller or split effective runtime input, or a narrower Runtime Skill scope; "
            "do not issue a model correction or blind retry"
        )
    if code == _USAGE_LIMIT_EXCEEDED_CODE:
        return (
            "restored Provider usage capacity or an explicitly authorized model/provider route; "
            "do not issue a model correction or blind retry"
        )
    if code == _PROVIDER_UNAVAILABLE_CODE:
        return (
            "a recovered Codex Provider route followed by an authorized bounded infrastructure "
            "retry; do not issue a model correction"
        )
    if code == _PROVIDER_REJECTED_CODE:
        return (
            "a supported Codex SDK/Provider request contract or an explicitly authorized "
            "route/profile change; do not issue a model correction or blind retry"
        )
    if code == _PROVIDER_AUTHENTICATION_CODE:
        return (
            "a corrected credential or Provider authentication route outside this attempt; "
            "do not issue a model correction or blind retry"
        )
    if code == _PROVIDER_MODEL_UNAVAILABLE_CODE:
        return (
            "an explicitly authorized available model/provider route; do not issue a model "
            "correction or blind retry"
        )
    if code == _PROVIDER_CONTEXT_WINDOW_CODE:
        return (
            "a smaller or split effective runtime input, or an explicitly authorized "
            "larger-context route; do not blind retry"
        )
    if code == _PROVIDER_OUTPUT_LIMIT_CODE:
        return (
            "an explicitly authorized, session-bound continuation under the remaining logical "
            "budget, or a smaller/split Agent boundary; do not blind retry"
        )
    if code == _PROVIDER_OUTPUT_SCHEMA_CODE:
        return (
            "a corrected adapter/schema/transport definition after auditing the effective "
            "runtime instructions; do not blind retry"
        )
    if code == _PROVIDER_CONTENT_FILTERED_CODE:
        return (
            "a prompt and Runtime Skill policy audit, or an explicitly authorized alternate "
            "route; do not blind retry"
        )
    if code == _PROVIDER_INVALID_REQUEST_CODE:
        return (
            "a corrected adapter request, profile, or structured-output contract; do not issue "
            "a model correction or blind retry"
        )
    if code == _PROVIDER_SANDBOX_CODE:
        return (
            "a Builder sandbox/capability/workspace configuration that permits the declared "
            "operation; do not issue a model correction or blind retry"
        )
    if code == _PROVIDER_THREAD_ROLLBACK_CODE:
        return (
            "a fresh diagnostic thread/session policy after inspecting the Codex runtime route; "
            "do not blind retry the failed continuation"
        )
    if code == _PROVIDER_UNCLASSIFIED_CODE:
        return (
            "one safe InvocationBackend/SDK terminal-envelope investigation, followed by a "
            "new classified route or explicit causal change; do not issue a model correction "
            "or blind retry"
        )
    if code == _DIRECT_OUTPUT_LIMIT_CODE:
        configured = _configured_output_limit(error.details if error is not None else {})
        if configured is not None:
            return (
                "a new diagnostic definition with an explicitly changed structured "
                f"output-token budget (the failed attempt declared {configured}) or a "
                "smaller bounded structured response; never a blind retry of this attempt"
            )
        return (
            "a new diagnostic definition with an explicitly changed structured output-token "
            "budget or a smaller bounded structured response; never a blind retry of this attempt"
        )
    if code == _DIRECT_PROVIDER_STREAM_STALLED_CODE:
        return (
            "a profile-matched Direct Provider liveness control and either a corrected Direct "
            "stream/route boundary or one Scheduler-authorized fresh physical execution; do not "
            "change the Prompt or Runtime Skill without semantic output"
        )
    if code == _DIRECT_INVALID_JSON_CODE:
        return _direct_invalid_json_expected_category(safe_terminal_details(error))
    if code == _DIRECT_TRANSPORT_INVALID_CODE:
        return _direct_transport_expected_category(safe_terminal_details(error))
    if code == _DIRECT_INVALID_REQUEST_CODE:
        return _direct_invalid_request_expected_category(safe_terminal_details(error))
    if code == "direct_provider_unavailable":
        return (
            "a Direct Provider liveness/route check using the safe HTTP fingerprint, then at "
            "most one policy-authorized fresh physical execution; do not issue a model correction"
        )
    if code == "direct_rate_limited":
        return (
            "restored Direct Provider capacity followed by at most one policy-authorized fresh "
            "physical execution; do not issue a model correction"
        )
    if code in {"direct_authentication_failed", "direct_model_unavailable"}:
        return (
            "a corrected Direct credential/model route outside this attempt; do not issue a "
            "model correction or blind retry"
        )
    if code in {"direct_provider_timeout", "direct_provider_rejected"}:
        return (
            "a Direct adapter/provider route investigation using the safe HTTP fingerprint; "
            "make one explicit causal decision before another real execution"
        )
    return None


def terminal_failure_retryable(error: InvocationError | None) -> bool:
    """Use explicit backend retryability while rejecting known incompatibilities."""

    return bool(
        error is not None
        and error.retryable
        and safe_terminal_code(error) not in _NON_RETRYABLE_TERMINAL_CODES
    )


def safe_terminal_code(error: InvocationError | None) -> str | None:
    """Return the most specific closed terminal code available to feedback.

    Older workers classified a closed ``sandboxError`` and thread rollback as
    generic Provider rejection while already carrying a safe enum label.  Keep
    that historical evidence useful without trusting an arbitrary provider
    message or changing the original immutable error record.
    """

    if error is None:
        return None
    if error.code != _PROVIDER_REJECTED_CODE:
        return error.code
    info = safe_terminal_details(error).get("codex_error_info")
    legacy_codes = {
        "enum:sandboxerror": _PROVIDER_SANDBOX_CODE,
        "enum:threadrollbackfailed": _PROVIDER_THREAD_ROLLBACK_CODE,
        "enum:other": _PROVIDER_UNCLASSIFIED_CODE,
        "object:other": _PROVIDER_UNCLASSIFIED_CODE,
    }
    return legacy_codes.get(info, error.code) if isinstance(info, str) else error.code


def safe_terminal_remediation(error: InvocationError | None) -> str | None:
    """Return one safe Code-Agent debugging route for a terminal boundary."""

    code = safe_terminal_code(error)
    if code == _DIRECT_INVALID_JSON_CODE:
        return _direct_invalid_json_remediation(safe_terminal_details(error))
    if code == _DIRECT_TRANSPORT_INVALID_CODE:
        return _direct_transport_remediation(safe_terminal_details(error))
    if code == _DIRECT_INVALID_REQUEST_CODE:
        return _direct_invalid_request_remediation(safe_terminal_details(error))
    if code == _DIRECT_PROVIDER_STREAM_STALLED_CODE:
        return (
            "Inspect the safe Provider-event count, idle interval, and local waiting heartbeat; "
            "run one profile-matched Direct control. If that control passes, treat this as one "
            "stalled stream and repair the Direct route/proxy/adapter boundary or use only an "
            "existing Scheduler-authorized retry."
        )
    if code == _SDK_EXECUTION_FAILED_CODE and (
        safe_terminal_details(error).get("worker_phase") == "thread_resume"
    ):
        return (
            "Inspect Codex thread persistence, worker lifetime, and private continuation state "
            "before another continuation attempt."
        )
    if code == "direct_provider_unavailable":
        return (
            "Inspect the retained Direct safe HTTP status and provider shape, verify current "
            "route liveness, then spend at most the declared infrastructure retry."
        )
    if code == "direct_rate_limited":
        return (
            "Inspect the retained Direct HTTP status and safe provider shape, wait for restored "
            "capacity, then spend at most the declared infrastructure retry."
        )
    if code in {"direct_authentication_failed", "direct_model_unavailable"}:
        return "Inspect Direct credential/model routing outside the Agent Prompt and Runtime Skill."
    if code in {"direct_provider_timeout", "direct_provider_rejected"}:
        return (
            "Inspect the retained Direct HTTP status and safe provider shape before selecting a "
            "new route, budget, or one authorized retry."
        )
    routes = {
        _PROVIDER_REJECTED_CODE: (
            "Inspect the InvocationBackend terminal projection and Provider/profile request route; "
            "retain only a closed terminal kind before another real invocation."
        ),
        _PROVIDER_UNAVAILABLE_CODE: (
            "Verify the Provider liveness route, then spend at most the policy-authorized "
            "infrastructure retry."
        ),
        _PROVIDER_QUOTA_EXHAUSTED_CODE: (
            "Restore quota or select an explicitly authorized Provider/model route; do not replay "
            "this physical attempt."
        ),
        _SESSION_BUDGET_EXHAUSTED_CODE: (
            "Inspect the declared rollout envelope and effective planning scope, then create a "
            "new diagnostic definition with an explicitly larger budget or narrower scope."
        ),
        _USAGE_LIMIT_EXCEEDED_CODE: (
            "Restore Provider usage capacity or select an explicitly authorized model/provider "
            "route; do not replay this physical attempt."
        ),
        _PROVIDER_AUTHENTICATION_CODE: (
            "Inspect credential/profile routing outside the Agent prompt and Runtime Skill."
        ),
        _PROVIDER_MODEL_UNAVAILABLE_CODE: (
            "Select an explicitly authorized available model route; do not alter the proposal "
            "first."
        ),
        _PROVIDER_CONTEXT_WINDOW_CODE: (
            "Audit effective prompt, Runtime Skill, and input size; split or reduce the node "
            "before another real invocation."
        ),
        _PROVIDER_OUTPUT_LIMIT_CODE: (
            "Treat this as a Provider physical-turn ceiling, not an ordinary transport retry: "
            "preserve the workspace/session only through an explicit continuation checkpoint, "
            "or split the Agent work into observable physical nodes before another real call."
        ),
        _PROVIDER_OUTPUT_SCHEMA_CODE: (
            "Audit adapter transport, output schema, effective prompt, and Runtime Skill together."
        ),
        _PROVIDER_CONTENT_FILTERED_CODE: (
            "Audit effective prompt and Runtime Skill policy content before choosing an "
            "authorized route."
        ),
        _PROVIDER_INVALID_REQUEST_CODE: (
            "Audit adapter request construction, profile, and structured-output contract "
            "before retrying."
        ),
        _PROVIDER_SANDBOX_CODE: (
            "Audit Builder workspace, sandbox, and capability profile against the operation "
            "that ran."
        ),
        _PROVIDER_THREAD_ROLLBACK_CODE: (
            "Audit Codex session/continuation handling and use a fresh diagnostic thread if "
            "authorized."
        ),
        _PROVIDER_UNCLASSIFIED_CODE: (
            "Inspect the safe Codex terminal-envelope shape, any advisory redacted-text signals, "
            "and same-route controls; make an explicit causal change or improve feedback before "
            "another real invocation."
        ),
    }
    return routes.get(code) if code is not None else None


def safe_terminal_details(error: InvocationError | None) -> JsonObject:
    """Retain closed terminal facts plus content-free advisory text signals.

    This helper is also used when Builder translates an ``InvocationError``
    into its own exception and later reconstructs it for Scheduler.  It must
    not become a generic carrier for provider text, stderr, routes, or request
    material. Advisory signals are derived inside the worker from ambiguous
    terminal prose but preserve no provider words; they are for Code-Agent
    investigation only and never alter retry routing.
    """

    if error is None:
        return {}
    if error.code == _DIRECT_INVALID_JSON_CODE:
        return _safe_direct_invalid_json_details(error.details)
    if error.code == _DIRECT_TRANSPORT_INVALID_CODE:
        return _safe_direct_transport_details(error.details)
    if error.code == _DIRECT_OUTPUT_LIMIT_CODE:
        return _safe_direct_output_limit_details(error.details)
    if error.code == _DIRECT_PROVIDER_STREAM_STALLED_CODE:
        return _safe_direct_provider_stream_stalled_details(error.details)
    if error.code == _DIRECT_INVALID_REQUEST_CODE:
        return _safe_direct_invalid_request_details(error.details)
    if error.code in _DIRECT_PROVIDER_EXCEPTION_CODES:
        return _safe_direct_invalid_request_details(error.details)
    if error.code == _SDK_EXECUTION_FAILED_CODE:
        phase = error.details.get("worker_phase")
        if isinstance(phase, str) and phase in _CODEX_WORKER_PHASES:
            return {"worker_phase": phase}
        return {}
    if error.code not in _CODEX_TERMINAL_DETAIL_CODES:
        return {}
    details = error.details
    safe: JsonObject = {}
    shape = details.get("terminal_error_shape")
    if isinstance(shape, str) and shape in _CODEX_PROVIDER_ERROR_SHAPES:
        safe["terminal_error_shape"] = shape
    info = details.get("codex_error_info")
    if isinstance(info, str) and info in _CODEX_PROVIDER_ERROR_INFO:
        safe["codex_error_info"] = info
    signals = details.get("advisory_text_signals")
    if (
        error.code == _PROVIDER_UNCLASSIFIED_CODE
        and isinstance(signals, list)
        and 1 <= len(signals) <= len(_CODEX_ADVISORY_TEXT_SIGNALS)
        and all(
            isinstance(signal, str) and signal in _CODEX_ADVISORY_TEXT_SIGNALS for signal in signals
        )
        and len(set(signals)) == len(signals)
    ):
        safe["advisory_text_signals"] = signals
    if error.code == _PROVIDER_OUTPUT_LIMIT_CODE:
        terminal_status = details.get("terminal_status")
        terminal_reason = details.get("terminal_reason")
        if (
            isinstance(terminal_status, str)
            and terminal_status in _CODEX_OUTPUT_TERMINAL_STATUSES
            and isinstance(terminal_reason, str)
            and terminal_reason in _CODEX_OUTPUT_TERMINAL_REASONS
        ):
            safe["terminal_status"] = terminal_status
            safe["terminal_reason"] = terminal_reason
    http_status = details.get("http_status")
    if _safe_http_status(http_status):
        safe["http_status"] = http_status
    return safe


def _safe_direct_invalid_request_details(details: JsonObject) -> JsonObject:
    """Revalidate Direct exception facts before Scheduler persistence."""

    safe: JsonObject = {}
    http_status = details.get("http_status")
    if _safe_http_status(http_status):
        safe["http_status"] = http_status
    shape = details.get("provider_error_shape")
    if isinstance(shape, str) and shape in _DIRECT_PROVIDER_ERROR_SHAPES:
        safe["provider_error_shape"] = shape
    for key, allowed in (
        ("provider_error_type", _DIRECT_PROVIDER_ERROR_TYPES),
        ("provider_error_code", _DIRECT_PROVIDER_ERROR_CODES),
        ("provider_error_param", _DIRECT_PROVIDER_ERROR_PARAMS),
    ):
        value = details.get(key)
        if isinstance(value, str) and value in allowed:
            safe[key] = value
    return safe


def _safe_direct_invalid_json_details(details: JsonObject) -> JsonObject:
    parsed = _json_parse_details(details)
    if parsed is None:
        return {}
    shape, failure, offset, characters = parsed
    return {
        "response_shape": shape,
        "parse_failure": failure,
        "parse_offset": offset,
        "response_characters": characters,
    }


def _safe_direct_transport_details(details: JsonObject) -> JsonObject:
    transport = details.get("transport")
    envelope_shape = details.get("envelope_shape")
    if (
        transport not in {"json_envelope", "provider_schema", "json_object"}
        or envelope_shape not in _ENVELOPE_SHAPES
    ):
        return {}
    safe: JsonObject = {"transport": transport, "envelope_shape": envelope_shape}
    parsed = _json_parse_details(details)
    if parsed is not None:
        shape, failure, offset, characters = parsed
        safe.update(
            {
                "response_shape": shape,
                "parse_failure": failure,
                "parse_offset": offset,
                "response_characters": characters,
            }
        )
    return safe


def _safe_direct_output_limit_details(details: JsonObject) -> JsonObject:
    configured = _configured_output_limit(details)
    if configured is None:
        return {}
    return {
        "terminal_status": "incomplete",
        "terminal_reason": "max_output_tokens",
        "configured_max_output_tokens": configured,
    }


def _safe_direct_provider_stream_stalled_details(details: JsonObject) -> JsonObject:
    waiting_phase = details.get("waiting_phase")
    idle_timeout_seconds = details.get("idle_timeout_seconds")
    observed_provider_event_count = details.get("observed_provider_event_count")
    if (
        waiting_phase != "direct_awaiting_stream_event"
        or isinstance(idle_timeout_seconds, bool)
        or not isinstance(idle_timeout_seconds, (int, float))
        or not 0 < idle_timeout_seconds <= _MAX_SAFE_DIRECT_STREAM_IDLE_SECONDS
        or isinstance(observed_provider_event_count, bool)
        or not isinstance(observed_provider_event_count, int)
        or not 1 <= observed_provider_event_count <= _MAX_SAFE_DIRECT_STREAM_EVENT_COUNT
    ):
        return {}
    return {
        "waiting_phase": waiting_phase,
        "idle_timeout_seconds": idle_timeout_seconds,
        "observed_provider_event_count": observed_provider_event_count,
    }


def _direct_provider_stream_stalled_condition(details: JsonObject) -> str:
    idle_timeout_seconds = details.get("idle_timeout_seconds")
    observed_provider_event_count = details.get("observed_provider_event_count")
    if (
        isinstance(idle_timeout_seconds, (int, float))
        and not isinstance(idle_timeout_seconds, bool)
        and isinstance(observed_provider_event_count, int)
        and not isinstance(observed_provider_event_count, bool)
    ):
        return (
            "the Direct Provider stream emitted "
            f"{observed_provider_event_count} event(s) then yielded no next event for "
            f"{idle_timeout_seconds:g} seconds"
        )
    return "the Direct Provider stream stopped yielding events after it had started"


def _invalid_json_condition(details: JsonObject) -> str:
    parsed = _json_parse_details(details)
    if parsed is None:
        return "structured JSON response invalid (safe parser detail unavailable)"
    shape, failure, offset, characters = parsed
    return (
        "structured JSON response invalid "
        f"(shape={shape}; parse={failure}; offset={offset}; chars={characters})"
    )


def _transport_decode_condition(details: JsonObject) -> str:
    transport = details.get("transport")
    envelope_shape = details.get("envelope_shape")
    if (
        transport not in {"json_envelope", "provider_schema", "json_object"}
        or envelope_shape not in _ENVELOPE_SHAPES
    ):
        return "structured output transport invalid (safe encoding detail unavailable)"
    parsed = _json_parse_details(details)
    if parsed is None:
        return (
            "structured output transport invalid "
            f"(transport={transport}; envelope={envelope_shape})"
        )
    _shape, failure, offset, characters = parsed
    return (
        "structured output transport invalid "
        f"(transport={transport}; envelope={envelope_shape}; parse={failure}; "
        f"offset={offset}; chars={characters})"
    )


def _output_limit_condition(details: JsonObject) -> str:
    configured = _configured_output_limit(details)
    if configured is None:
        return (
            "the provider stopped because the declared structured output token limit was exhausted"
        )
    return (
        "the provider stopped because the declared structured output token limit was exhausted "
        f"(max_output_tokens={configured})"
    )


def _direct_invalid_json_expected_category(details: JsonObject) -> str:
    parsed = _json_parse_details(details)
    if parsed is not None:
        return (
            "an effective Prompt, Runtime Skill, and Direct output-encoding audit using the safe "
            "parse shape; make one explicit causal change before another real invocation"
        )
    return (
        "one safe Direct output transport investigation; improve terminal feedback before another "
        "real invocation if it remains ambiguous"
    )


def _direct_invalid_json_remediation(details: JsonObject) -> str:
    parsed = _json_parse_details(details)
    if parsed is not None:
        return (
            "Audit the effective output instructions and Runtime Skill against the safe parse "
            "shape; change the shared transport prompt or adapter only after identifying the cause."
        )
    return (
        "Improve the Direct malformed-output feedback projection before changing Prompt, Runtime "
        "Skill, adapter, or model route."
    )


def _direct_transport_expected_category(details: JsonObject) -> str:
    if _is_malformed_json_envelope_string(details):
        return (
            "a corrected shared json-envelope instruction that explicitly serializes the inner "
            "artifact, after auditing effective Prompt and Runtime Skill; do not blind retry"
        )
    return (
        "a corrected Direct output transport/adapter definition after auditing effective Prompt "
        "and Runtime Skill; do not blind retry"
    )


def _direct_transport_remediation(details: JsonObject) -> str:
    if _is_malformed_json_envelope_string(details):
        return (
            "Audit the shared json-envelope prompt for standard JSON string escaping and inspect "
            "any Runtime Skill output instruction; then run this frozen boundary once."
        )
    return (
        "Audit adapter decode logic, configured transport, effective Prompt, and Runtime Skill; "
        "make one explicit causal change before another real boundary execution."
    )


def _is_malformed_json_envelope_string(details: JsonObject) -> bool:
    return (
        details.get("transport") == "json_envelope"
        and details.get("envelope_shape") == "artifact_json_string"
        and _json_parse_details(details) is not None
    )


def _direct_invalid_request_condition(details: JsonObject) -> str:
    kind = _direct_invalid_request_kind(details)
    if kind == "structured_output_schema":
        return (
            "the Direct Provider rejected the declared structured-output schema before a "
            "structured response"
        )
    if kind == "request_parameter":
        return "the Direct Provider rejected a declared request/profile parameter before a response"
    if kind == "context_window":
        return "the Direct Provider rejected the declared request because its context is too large"
    if kind == "model_route":
        return "the Direct Provider rejected the declared model route before a response"
    return "the Direct Provider rejected a declared request before a structured response"


def _direct_provider_exception_condition(code: str, details: JsonObject) -> str:
    """Describe an HTTP-side Direct terminal without retaining provider prose."""

    conditions = {
        "direct_authentication_failed": "the Direct Provider rejected the configured credential",
        "direct_model_unavailable": "the Direct Provider does not offer the requested model route",
        "direct_provider_rejected": "the Direct Provider rejected the request before a response",
        "direct_provider_timeout": "the Direct Provider timed out before a structured response",
        "direct_provider_unavailable": (
            "the Direct Provider was unavailable before a structured response"
        ),
        "direct_rate_limited": "the Direct Provider rate-limited the request before a response",
    }
    condition = conditions.get(code, "the Direct Provider ended before a structured response")
    facts: list[str] = []
    status = details.get("http_status")
    if _safe_http_status(status):
        facts.append(f"http_status={status}")
    for key, label in (
        ("provider_error_shape", "shape"),
        ("provider_error_type", "type"),
        ("provider_error_code", "code"),
        ("provider_error_param", "param"),
    ):
        value = details.get(key)
        if isinstance(value, str):
            facts.append(f"{label}={value}")
    return f"{condition} ({'; '.join(facts)})" if facts else condition


def _direct_invalid_request_expected_category(details: JsonObject) -> str:
    kind = _direct_invalid_request_kind(details)
    if kind == "structured_output_schema":
        return (
            "a Direct route that accepts the declared structured-output schema, or an explicitly "
            "changed schema/transport definition; do not issue a model correction or blind retry"
        )
    if kind == "request_parameter":
        return (
            "a corrected Direct adapter/profile request parameter; do not issue a model correction "
            "or blind retry"
        )
    if kind == "context_window":
        return (
            "a smaller or split effective runtime input, or an explicitly authorized "
            "larger-context route; do not blind retry"
        )
    if kind == "model_route":
        return "an explicitly authorized model/provider route; do not blind retry"
    return (
        "one safe Direct HTTP rejection investigation that isolates adapter, profile, schema, or "
        "input; improve feedback before another real invocation if it remains ambiguous"
    )


def _direct_invalid_request_remediation(details: JsonObject) -> str:
    kind = _direct_invalid_request_kind(details)
    if kind == "structured_output_schema":
        return (
            "Inspect the effective Direct text.format schema, schema compiler, and gateway "
            "compatibility; then run this frozen boundary once after an explicit change."
        )
    if kind == "request_parameter":
        return (
            "Inspect the effective Direct request and profile fields named by the safe parameter "
            "class; then run this frozen boundary once after an explicit change."
        )
    if kind == "context_window":
        return (
            "Inspect effective Prompt, Runtime Skill, and input size; split or reduce the boundary "
            "before one new real execution."
        )
    if kind == "model_route":
        return "Inspect the Direct model/profile route before one authorized real execution."
    return (
        "Inspect the safe Direct rejection fingerprint and request construction; improve this "
        "feedback projection before another real node execution if it names no causal component."
    )


def _direct_invalid_request_kind(details: JsonObject) -> str:
    code = details.get("provider_error_code")
    param = details.get("provider_error_param")
    error_type = details.get("provider_error_type")
    if (
        code == "structured_output_schema"
        or param in {"structured_output_schema", "structured_output_format"}
        or error_type == "structured_output_schema"
    ):
        return "structured_output_schema"
    if code == "context_window" or error_type == "context_window":
        return "context_window"
    if code == "model_route" or param == "model":
        return "model_route"
    if (
        code == "request_parameter"
        or error_type == "request_parameter"
        or param
        in {
            "output_token_limit",
            "reasoning_effort",
            "input",
            "instructions",
        }
    ):
        return "request_parameter"
    return "unknown"


def _provider_unavailable_condition(details: JsonObject) -> str:
    source = details.get("codex_error_info")
    phrases = {
        "transport:http_connection_failed": "connection failed",
        "transport:response_stream_connection_failed": "response-stream connection failed",
        "transport:response_stream_disconnected": "response stream disconnected",
        "transport:response_too_many_failed_attempts": (
            "response stream exhausted connection attempts"
        ),
    }
    if isinstance(source, str) and source in phrases:
        return f"the Codex Provider {phrases[source]} before a terminal response"
    return "the configured Provider was unavailable before a terminal response"


def _provider_rejection_condition(details: JsonObject) -> str:
    shape = details.get("terminal_error_shape")
    if shape == "missing":
        return "the Codex SDK reported a failed turn without a terminal error envelope"
    if shape == "non_object":
        return "the Codex SDK reported a failed turn with a non-object terminal error envelope"
    source = details.get("codex_error_info")
    if source == "active_turn_not_steerable":
        return "the Codex SDK reported that the active turn could not be steered"
    if source == "object:other":
        return "the Codex SDK reported an unrecognized closed terminal error envelope"
    if source == "enum:other":
        return "the Codex SDK reported an unclassified closed terminal error enum"
    return "the Agent backend returned a non-success terminal result"


def _unclassified_terminal_condition(details: JsonObject) -> str:
    """Describe missing closed terminal data without inferring a Provider cause."""

    shape = details.get("terminal_error_shape")
    source = details.get("codex_error_info")
    advisory = _advisory_text_signal_phrase(details)
    if source == "absent":
        condition = (
            "the Codex SDK terminal envelope omitted a closed error kind; Provider, request, "
            "SDK, and runtime causes remain unclassified"
        )
    elif source == "non_object":
        condition = "the Codex SDK terminal envelope carried a non-object error kind"
    elif shape == "missing":
        condition = "the Codex SDK terminalized the turn without an error envelope"
    elif shape == "non_object":
        condition = "the Codex SDK terminalized the turn with a non-object error envelope"
    elif source == "object:other":
        condition = "the Codex SDK terminal envelope contained an unknown closed error variant"
    elif source == "enum:other":
        condition = "the Codex SDK terminal envelope contained an unknown closed error enum"
    else:
        condition = "the Codex runtime returned an unclassified terminal error"
    return f"{condition}; advisory redacted-text signals: {advisory}" if advisory else condition


def _advisory_text_signal_phrase(details: JsonObject) -> str | None:
    signals = details.get("advisory_text_signals")
    if (
        not isinstance(signals, list)
        or not signals
        or len(signals) > len(_CODEX_ADVISORY_TEXT_SIGNALS)
        or len(set(signals)) != len(signals)
        or not all(
            isinstance(signal, str) and signal in _CODEX_ADVISORY_TEXT_SIGNALS for signal in signals
        )
    ):
        return None
    return ", ".join(signal for signal in signals if isinstance(signal, str))


def _configured_output_limit(details: JsonObject) -> int | None:
    if (
        details.get("terminal_status") != "incomplete"
        or details.get("terminal_reason") != "max_output_tokens"
    ):
        return None
    value = details.get("configured_max_output_tokens")
    if (
        isinstance(value, int)
        and not isinstance(value, bool)
        and 1 <= value <= _MAX_SAFE_OUTPUT_TOKEN_LIMIT
    ):
        return value
    return None


def _json_parse_details(details: JsonObject) -> tuple[str, str, int, int] | None:
    shape = details.get("response_shape")
    failure = details.get("parse_failure")
    offset = details.get("parse_offset")
    characters = details.get("response_characters")
    if (
        not isinstance(shape, str)
        or shape not in _RESPONSE_SHAPES
        or not isinstance(failure, str)
        or failure not in _PARSE_FAILURES
        or not _bounded_nonnegative_int(offset)
        or not _bounded_nonnegative_int(characters)
    ):
        return None
    return shape, failure, offset, characters


def _bounded_nonnegative_int(value: object) -> TypeGuard[int]:
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and 0 <= value <= _MAX_SAFE_RESPONSE_CHARACTERS
    )


def _safe_http_status(value: object) -> TypeGuard[int]:
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and 100 <= value <= 599
    )


def _response_shape(output_text: str) -> str:
    stripped = output_text.lstrip()
    if not stripped:
        return "empty"
    if stripped.startswith("```"):
        return "markdown_fence"
    first = stripped[0]
    if first == "{":
        return "object"
    if first == "[":
        return "array"
    if first == '"':
        return "string"
    if first in "-0123456789":
        return "scalar"
    if first in "tfn":
        return "literal"
    return "non_json"


def _parse_failure(output_text: str, exc: Exception) -> str:
    if not isinstance(exc, json.JSONDecodeError):
        return "nonfinite_number"
    if exc.msg == "Extra data":
        return "extra_data"
    if exc.pos >= len(output_text) and _response_shape(output_text) in {
        "object",
        "array",
        "string",
    }:
        return "truncated"
    return "syntax"


def _parse_offset(exc: Exception) -> int:
    if not isinstance(exc, json.JSONDecodeError):
        return 0
    return min(max(0, exc.pos), _MAX_SAFE_RESPONSE_CHARACTERS)


def _envelope_shape(value: JsonValue) -> str:
    if isinstance(value, dict):
        return "artifact_json_object"
    if isinstance(value, list):
        return "artifact_json_array"
    return "artifact_json_scalar"


__all__ = [
    "direct_invalid_json_details",
    "direct_output_limit_details",
    "direct_provider_stream_stalled_details",
    "direct_provider_exception_details",
    "direct_transport_decode_details",
    "safe_terminal_code",
    "safe_terminal_condition",
    "safe_terminal_details",
    "safe_terminal_expected_category",
    "safe_terminal_remediation",
    "terminal_failure_retryable",
]
