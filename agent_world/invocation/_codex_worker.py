"""Private one-request worker for :class:`CodexSdkBackend`.

The worker is intentionally a fixed Python entry point, not a generic process
runner.  It imports the real ``openai_codex.AsyncCodex`` SDK only in this child
process and speaks a small NDJSON protocol with the trusted parent.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import sys
import time
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    # Allow a source checkout to run this fixed file without leaking PYTHONPATH
    # into the Codex/app-server environment.
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent_world.invocation.redaction import (  # noqa: E402
    Redactor,
    redacted_command_diagnostic_excerpt,
    redacted_terminal_diagnostic_excerpt,
)
from agent_world.invocation.runtime_provider import (  # noqa: E402
    API_KEY_RUNTIME_PROVIDER as _API_KEY_RUNTIME_PROVIDER,
)
from agent_world.invocation.runtime_provider import (  # noqa: E402
    OPENAI_API_KEY_ENVIRONMENT as _OPENAI_API_KEY_ENVIRONMENT,
)
from agent_world.invocation.runtime_provider import (  # noqa: E402
    OPENAI_BASE_URL_ENVIRONMENT as _OPENAI_BASE_URL_ENVIRONMENT,
)

PROTOCOL_VERSION = "agent-world.codex-worker.v1"
SUPPORTED_SDK_VERSION = "0.144.4"
_ENVIRONMENT_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_DIAGNOSTIC_COMMAND_LABEL = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_DIAGNOSTIC_COMMAND_MAX_EXPECTATIONS = 8
_RESULT_RESERVE_BYTES = 64 * 1024
_SDK_EXECUTION_PHASES = frozenset(
    {
        "sdk_session_open",
        "thread_start",
        "thread_resume",
        "turn_start",
        "turn_stream",
    }
)


class ProtocolBudgetExceeded(RuntimeError):
    pass


class Emitter:
    def __init__(
        self,
        *,
        redactor: Redactor,
        max_events: int,
        max_protocol_bytes: int,
    ) -> None:
        self.redactor = redactor
        self.max_events = max_events
        self.max_protocol_bytes = max_protocol_bytes
        self.event_count = 0
        self.protocol_bytes = 0

    def event(self, method: str, payload: Mapping[str, Any]) -> None:
        if self.event_count >= self.max_events:
            raise ProtocolBudgetExceeded("SDK event count exceeded the resolved profile limit")
        record = {
            "type": "event",
            "protocol_version": PROTOCOL_VERSION,
            "event": {
                "sequence": self.event_count,
                "method": method,
                "payload": self.redactor.object(payload),
            },
        }
        encoded = _encode_record(record)
        event_budget = self.max_protocol_bytes - _RESULT_RESERVE_BYTES
        if self.protocol_bytes + len(encoded) > event_budget:
            raise ProtocolBudgetExceeded("SDK event bytes exceeded the resolved profile limit")
        self.event_count += 1
        self.protocol_bytes += len(encoded)
        _write_encoded(encoded)

    def lifecycle(self, phase: str) -> None:
        """Emit one bounded worker-local phase, distinct from SDK progress."""

        if phase not in _SDK_EXECUTION_PHASES:
            raise ValueError("unsupported worker lifecycle phase")
        record = {
            "type": "lifecycle",
            "protocol_version": PROTOCOL_VERSION,
            "phase": phase,
        }
        encoded = _encode_record(record)
        if self.protocol_bytes + len(encoded) > self.max_protocol_bytes:
            raise ProtocolBudgetExceeded(
                "worker lifecycle bytes exceeded the resolved profile limit"
            )
        self.protocol_bytes += len(encoded)
        _write_encoded(encoded)

    def result(self, payload: Mapping[str, Any]) -> None:
        record = {
            "type": "result",
            "protocol_version": PROTOCOL_VERSION,
            "result": self.redactor.object(payload),
        }
        encoded = _encode_record(record)
        if self.protocol_bytes + len(encoded) > self.max_protocol_bytes:
            record = {
                "type": "result",
                "protocol_version": PROTOCOL_VERSION,
                "result": {
                    "status": "budget_exhausted",
                    "duration_ms": payload.get("duration_ms", 0),
                    "error": {
                        "code": "terminal_result_budget_exhausted",
                        "message": "terminal worker result exceeded the resolved profile limit",
                        "retryable": False,
                    },
                },
            }
            encoded = _encode_record(record)
        self.protocol_bytes += len(encoded)
        _write_encoded(encoded)


def _encode_record(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


def _write_encoded(value: bytes) -> None:
    sys.stdout.buffer.write(value)
    sys.stdout.buffer.flush()


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number is forbidden: {value}")


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Enum):
        return _json_value(value.value)
    if hasattr(value, "model_dump"):
        return _json_value(value.model_dump(by_alias=True, exclude_none=True, mode="json"))
    if is_dataclass(value):
        return {item.name: _json_value(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return str(value)


def _notification_payload(value: Any) -> dict[str, Any]:
    """Return the wire payload represented by one SDK notification model.

    The preview SDK deliberately wraps notifications it cannot validate as an
    ``UnknownNotification(params=...)`` dataclass.  Those notifications are
    still routed to the correct turn by the SDK, but serializing the wrapper
    verbatim would add a synthetic ``params`` level and hide the terminal
    ``turn`` object from this adapter's protocol checks.  Unwrap only that
    exact SDK compatibility type; ordinary notification payloads keep their
    normal shape.
    """

    if type(value).__name__ == "UnknownNotification":
        params = getattr(value, "params", None)
        if isinstance(params, Mapping):
            unwrapped = _json_value(params)
            if isinstance(unwrapped, dict):
                return unwrapped
    converted = _json_value(value)
    if isinstance(converted, dict):
        return converted
    return {"value": converted}


def _require_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _require_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a non-empty string")
    return value


def _optional_string(value: Any, label: str) -> str | None:
    if value is None:
        return None
    return _require_string(value, label)


def _parse_diagnostic_command_expectations(value: object) -> tuple[tuple[str, str], ...]:
    """Validate private audit probes before they can affect event projection.

    The outer request type already restricts this to a diagnostic audit. The
    worker revalidates it because it is a protocol boundary. The command
    fragments never appear in compact events, telemetry, or the final result.
    """

    if value is None:
        return ()
    if not isinstance(value, list) or len(value) > _DIAGNOSTIC_COMMAND_MAX_EXPECTATIONS:
        raise ValueError("diagnostic_command_expectations must be a bounded list")
    parsed: list[tuple[str, str]] = []
    labels: set[str] = set()
    for item in value:
        if not isinstance(item, Mapping) or set(item) != {"label", "command_fragment"}:
            raise ValueError("diagnostic command expectation has an invalid shape")
        label = item.get("label")
        fragment = item.get("command_fragment")
        if (
            not isinstance(label, str)
            or not _DIAGNOSTIC_COMMAND_LABEL.fullmatch(label)
            or label in labels
            or not isinstance(fragment, str)
            or not fragment
            or len(fragment) > 256
            or "\n" in fragment
            or "\r" in fragment
        ):
            raise ValueError("diagnostic command expectation is invalid")
        labels.add(label)
        parsed.append((label, fragment))
    return tuple(parsed)


def _completed_turn_payload(
    method: str,
    event_payload: Mapping[str, Any],
    expected_turn_id: str,
) -> dict[str, Any] | None:
    if method != "turn/completed":
        return None
    turn = event_payload.get("turn")
    if not isinstance(turn, dict) or turn.get("id") != expected_turn_id:
        return None
    return turn


def _terminal_turn_failure_code(error: object) -> str:
    """Return a safe, actionable class for a terminal provider failure.

    Provider error payloads can contain the request, endpoint, credential
    hints, or arbitrary prose.  They must not cross the worker boundary, and
    neither may their wording become a false causal claim in a safe scene.
    Classify only the Codex app-server's closed ``codexErrorInfo`` protocol;
    an absent or unknown discriminator is explicitly unclassified.
    """

    return _terminal_turn_failure(error)[0]


def _terminal_turn_failure(
    error: object,
    *,
    diagnostic_capture_terminal_excerpt: bool = False,
    redactor: Redactor | None = None,
) -> tuple[str, dict[str, Any]]:
    """Classify a terminal turn and retain only its closed protocol facts.

    The SDK's ``codexErrorInfo`` union is a bounded, generated protocol.  A
    stream connection event without an HTTP response is materially different
    from a provider rejecting a request: it is an availability interruption
    and can be considered for the Scheduler's bounded infrastructure policy.
    Preserve that distinction without retaining an endpoint, request, provider
    message, or ``additionalDetails``.
    """

    details = _terminal_turn_failure_details(error)
    if not isinstance(error, Mapping):
        return "turn_failed_unclassified_codex_error", details

    # This text is never part of ordinary InvocationError feedback: the
    # Builder's normal projection strips it through ``safe_terminal_details``.
    # An explicitly opted-in local diagnostic needs the same bounded, double
    # redacted excerpt for a known closed enum as for an unknown one; otherwise
    # ``internalservererror`` misleadingly looks as though the Provider gave
    # no diagnosable terminal information at all.
    if diagnostic_capture_terminal_excerpt and redactor is not None:
        excerpt = _redacted_terminal_message_excerpt(error.get("message"), redactor)
        if excerpt is not None:
            details["diagnostic_error_excerpt"] = excerpt

    # The app-server's declared ``codexErrorInfo`` is a closed protocol enum
    # (with a few closed HTTP-status wrappers).  Prefer it over provider
    # message text: it both narrows diagnostics and ensures no opaque provider
    # payload needs to leave this worker process.
    codex_error_info = error.get("codexErrorInfo")
    if codex_error_info is None:
        # ``_json_value(..., by_alias=True)`` normally yields camel case, but
        # accept the SDK's Python spelling for forward-compatible unit inputs.
        codex_error_info = error.get("codex_error_info")
    structured_code = _codex_error_info_failure_code(codex_error_info)
    if structured_code is not None:
        return structured_code, details
    if _is_explicit_output_limit_terminal(error):
        # Some OpenAI-compatible Codex routes surface the provider's physical
        # turn-output ceiling only through the standard terminal message while
        # keeping ``codexErrorInfo`` at its closed ``other`` value.  The exact
        # pair below is a terminal-status signature, not a loose keyword
        # heuristic: retain only its two fixed facts and never persist the
        # provider message.  This changes investigation routing, not retry
        # authority; the Scheduler still needs an explicit continuation or
        # split-node policy before another real Agent turn can run.
        details.update(
            {
                "terminal_status": "incomplete",
                "terminal_reason": "max_output_tokens",
            }
        )
        return "turn_failed_output_limit", details
    # The generated protocol supplied no recognized closed kind.  Do not use
    # ``code``, ``type``, ``message`` or ``additionalDetails`` as a routing
    # proxy: provider-controlled prose cannot authorize a retry. It can,
    # however, be reduced in this private worker into bounded *advisory*
    # signals for the project-execution Agent. The signals never change the
    # terminal code and never retain a character of provider text.
    _add_advisory_terminal_text_signals(details, error)
    return "turn_failed_unclassified_codex_error", details


def _is_explicit_output_limit_terminal(error: Mapping[str, Any]) -> bool:
    """Recognize Codex's exact safe output-ceiling terminal signature.

    A generic mention of "tokens" or "output" in a Provider-controlled error
    body is not enough to classify an error.  The current Codex app-server
    emits this pair when it has received a terminal incomplete response whose
    sole declared reason is ``max_output_tokens``.  The raw body is inspected
    only inside this worker and is never sent to the parent process.
    """

    message = error.get("message")
    if not isinstance(message, str):
        return False
    text = message[:16_384].casefold()
    return "incomplete response returned" in text and "reason: max_output_tokens" in text


def _terminal_turn_failure_details(error: object) -> dict[str, Any]:
    """Project a terminal SDK error into a small, safe feedback vocabulary."""

    if error is None:
        return {"terminal_error_shape": "missing"}
    if not isinstance(error, Mapping):
        return {"terminal_error_shape": "non_object"}

    details: dict[str, Any] = {"terminal_error_shape": "object"}
    codex_error_info = error.get("codexErrorInfo")
    if codex_error_info is None:
        codex_error_info = error.get("codex_error_info")
    if codex_error_info is None:
        details["codex_error_info"] = "absent"
        return details
    if isinstance(codex_error_info, str):
        normalized = codex_error_info.replace("_", "").replace("-", "").lower()
        safe_values = {
            "contextwindowexceeded",
            "sessionbudgetexceeded",
            "usagelimitexceeded",
            "serveroverloaded",
            "internalservererror",
            "unauthorized",
            "badrequest",
            "cyberpolicy",
            "sandboxerror",
            "threadrollbackfailed",
            "other",
        }
        details["codex_error_info"] = (
            f"enum:{normalized}" if normalized in safe_values else "enum:other"
        )
        return details
    if not isinstance(codex_error_info, Mapping):
        details["codex_error_info"] = "non_object"
        return details

    for field, safe_name in (
        ("httpConnectionFailed", "http_connection_failed"),
        ("responseStreamConnectionFailed", "response_stream_connection_failed"),
        ("responseStreamDisconnected", "response_stream_disconnected"),
        ("responseTooManyFailedAttempts", "response_too_many_failed_attempts"),
    ):
        payload = codex_error_info.get(field)
        if not isinstance(payload, Mapping):
            continue
        details["codex_error_info"] = f"transport:{safe_name}"
        status = payload.get("httpStatusCode")
        if isinstance(status, int) and not isinstance(status, bool) and 100 <= status <= 599:
            details["http_status"] = status
        return details
    if isinstance(codex_error_info.get("activeTurnNotSteerable"), Mapping):
        details["codex_error_info"] = "active_turn_not_steerable"
        return details
    details["codex_error_info"] = "object:other"
    return details


def _add_advisory_terminal_text_signals(
    details: dict[str, Any],
    error: Mapping[str, Any],
) -> None:
    """Project ambiguous provider prose into non-routing, content-free clues.

    A custom OpenAI-compatible provider can legitimately return the declared
    Codex ``other`` enum with its only useful explanation in ``message``.
    ``additionalDetails`` is intentionally not even inspected because it is
    frequently a raw provider transcript. Keeping either prose would risk persisting routing,
    credential, prompt, or provider transcript material. These bounded
    signals retain only investigation hypotheses for a Code Agent; Scheduler
    must still treat the result as unclassified and must not use a signal to
    authorize a retry or mutation.
    """

    message = error.get("message")
    if not isinstance(message, str):
        return
    # Bound local inspection too: raw provider text never crosses the worker,
    # and an unbounded error body should not consume diagnostic CPU.
    text = message[:16_384].casefold()
    signals: list[str] = []
    for signal, markers in (
        (
            "authentication_or_authorization",
            (
                "unauthorized",
                "forbidden",
                "authentication",
                "api key",
                "credential",
                "permission denied",
                "access denied",
            ),
        ),
        (
            "model_or_route_availability",
            (
                "model not found",
                "model unavailable",
                "unknown model",
                "unsupported model",
                "deployment not found",
                "no such model",
            ),
        ),
        (
            "context_or_token_limit",
            (
                "context window",
                "context length",
                "maximum context",
                "too many tokens",
                "token limit",
                "input too long",
                "max tokens",
            ),
        ),
        (
            "request_or_schema_compatibility",
            (
                "json schema",
                "response format",
                "response_format",
                "output schema",
                "structured output",
                "unsupported parameter",
                "invalid parameter",
                "unknown parameter",
                "invalid request",
                "unsupported request",
            ),
        ),
        (
            "capacity_or_rate_limit",
            (
                "rate limit",
                "too many requests",
                "quota",
                "usage limit",
                "capacity",
                "overloaded",
            ),
        ),
        (
            "transport_or_connection",
            (
                "connection refused",
                "connection reset",
                "connection failed",
                "stream disconnected",
                "network error",
                "socket error",
                "dns",
            ),
        ),
        ("timeout_or_deadline", ("timed out", "timeout", "deadline exceeded")),
        (
            "policy_or_content_filter",
            ("content filter", "safety policy", "policy violation", "blocked by policy"),
        ),
        (
            "provider_internal_error",
            ("internal server error", "internal error", "server error", "http 5"),
        ),
    ):
        if any(marker in text for marker in markers):
            signals.append(signal)
    if signals:
        details["advisory_text_signals"] = signals


def _redacted_terminal_message_excerpt(value: object, redactor: Redactor) -> str | None:
    """Return one strictly local, bounded excerpt for an opted-in Doctor probe.

    This escape hatch exists only for a fixed-prompt provider readiness probe
    whose closed terminal envelope was too weak to diagnose. It is never
    copied into telemetry, artifacts, manifests, releases, or Scheduler
    feedback. Known runtime secrets, URLs, credential assignments, and long
    opaque tokens are removed before the parent can receive the text.
    """

    return redacted_terminal_diagnostic_excerpt(value, redactor=redactor)


def _codex_error_info_failure_code(value: object) -> str | None:
    """Map Codex's declared error enum to the worker's closed taxonomy.

    ``TurnError.additionalDetails`` and the provider's free-form ``message``
    are intentionally excluded.  They can contain request or routing
    material, whereas enum tags and numeric HTTP status are bounded protocol
    data safe to consume only for classification.
    """

    if isinstance(value, str):
        return {
            "contextwindowexceeded": "turn_failed_context_window",
            # These are materially different recovery routes.  A session
            # rollout-budget terminal can be tested again under a newly
            # declared envelope, whereas a Provider usage-limit terminal
            # cannot.  Keep the worker's closed classification precise so
            # the safe scene does not conflate them as generic "quota".
            "sessionbudgetexceeded": "turn_failed_session_budget_exhausted",
            "usagelimitexceeded": "turn_failed_usage_limit_exceeded",
            "serveroverloaded": "turn_failed_provider_unavailable",
            "internalservererror": "turn_failed_provider_unavailable",
            "unauthorized": "turn_failed_authentication",
            "badrequest": "turn_failed_invalid_request",
            "cyberpolicy": "turn_failed_content_filtered",
            "sandboxerror": "turn_failed_sandbox_error",
            "threadrollbackfailed": "turn_failed_thread_rollback",
        }.get(value.replace("_", "").replace("-", "").lower())
    if not isinstance(value, Mapping):
        return None

    for field in (
        "httpConnectionFailed",
        "responseStreamConnectionFailed",
        "responseStreamDisconnected",
        "responseTooManyFailedAttempts",
    ):
        transport_error = value.get(field)
        if not isinstance(transport_error, Mapping):
            continue
        status = transport_error.get("httpStatusCode")
        if isinstance(status, int) and not isinstance(status, bool):
            return _provider_http_status_failure_code(status)
        # The generated Codex protocol uses these variants only for an
        # interrupted connection/response stream.  Without an HTTP response,
        # this is a transient Provider availability event, not a request
        # incompatibility that the model should be asked to repair.
        return "turn_failed_provider_unavailable"
    return None


def _provider_http_status_failure_code(status: object) -> str:
    """Classify only a declared HTTP status, never a provider response body."""

    if not isinstance(status, int) or isinstance(status, bool):
        return "turn_failed_provider_rejected"
    if status in {400, 413, 422}:
        return "turn_failed_invalid_request"
    if status in {401, 403}:
        return "turn_failed_authentication"
    if status == 429:
        return "turn_failed_rate_limited"
    if status in {408, 504}:
        return "turn_failed_provider_timeout"
    if 500 <= status <= 599:
        return "turn_failed_provider_unavailable"
    return "turn_failed_provider_rejected"


def _compact_notification_payload(
    method: str,
    event_payload: Mapping[str, Any],
    *,
    diagnostic_command_expectations: tuple[tuple[str, str], ...] = (),
    diagnostic_command_matches: dict[str, tuple[str, ...]] | None = None,
    diagnostic_command_redactor: Redactor | None = None,
) -> dict[str, Any]:
    """Project SDK notifications to bounded telemetry metadata.

    Codex delta notifications may repeat a growing text buffer.  Forwarding
    those buffers across the private NDJSON protocol makes protocol bytes grow
    much faster than model tokens and can terminate an otherwise healthy turn.
    The worker itself retains the full notification long enough to extract the
    final answer, terminal turn and token usage; the parent needs only event
    ordering, stable identities, phases, statuses and numeric usage.
    """

    compact: dict[str, Any] = {}
    for key in ("threadId", "turnId"):
        value = event_payload.get(key)
        if isinstance(value, str):
            compact[key] = value
    for key in ("turn", "item"):
        value = event_payload.get(key)
        if not isinstance(value, dict):
            continue
        projected = {
            field: value[field]
            for field in ("id", "type", "phase", "status")
            if isinstance(value.get(field), str)
        }
        if projected:
            compact[key] = projected
        if key == "item" and value.get("type") == "commandExecution":
            command_proofs = _compact_diagnostic_command_proofs(
                value,
                diagnostic_command_expectations,
                diagnostic_command_matches,
                diagnostic_command_redactor,
            )
            if command_proofs:
                compact["diagnosticCommandProof"] = command_proofs
    token_usage = event_payload.get("tokenUsage")
    if isinstance(token_usage, dict):
        compact["tokenUsage"] = {
            key: value
            for key, value in token_usage.items()
            if isinstance(key, str)
            and isinstance(value, (int, float))
            and not isinstance(value, bool)
        }
    compact["sourceMethod"] = method
    return compact


def _compact_diagnostic_command_proofs(
    item: Mapping[str, Any],
    expectations: tuple[tuple[str, str], ...],
    matches_by_item_id: dict[str, tuple[str, ...]] | None,
    redactor: Redactor | None,
) -> list[dict[str, Any]]:
    """Project expected-command completion states, never command detail.

    Codex may emit a command text when an item starts and its exit code only
    when that same item completes. Keep their private item id in worker memory
    for this one turn so the safe projection does not falsely report an
    expected command as unobserved merely because the SDK split its fields.
    """

    if not expectations:
        return []
    item_id = item.get("id")
    command = item.get("command")
    status = item.get("status")
    exit_code = item.get("exitCode")
    labels: tuple[str, ...] = ()
    if isinstance(command, str):
        labels = tuple(label for label, fragment in expectations if fragment in command)
        if labels and isinstance(item_id, str) and matches_by_item_id is not None:
            matches_by_item_id[item_id] = labels
    if not labels and isinstance(item_id, str) and matches_by_item_id is not None:
        labels = matches_by_item_id.get(item_id, ())
    if not labels or not isinstance(status, str):
        return []
    if status == "completed" and exit_code == 0:
        outcome = "succeeded"
    elif exit_code == 127:
        outcome = "not_found"
    elif exit_code == 126:
        outcome = "not_executable"
    elif status == "failed" or isinstance(exit_code, int):
        outcome = "failed"
    elif status == "completed":
        outcome = "unknown"
    else:
        return []
    if isinstance(item_id, str) and matches_by_item_id is not None:
        matches_by_item_id.pop(item_id, None)
    safe_exit_code = (
        exit_code
        if isinstance(exit_code, int) and not isinstance(exit_code, bool) and 0 <= exit_code <= 255
        else None
    )
    excerpt = (
        redacted_command_diagnostic_excerpt(
            item.get("aggregatedOutput"),
            redactor=redactor,
        )
        if outcome != "succeeded" and redactor is not None
        else None
    )
    proofs: list[dict[str, Any]] = []
    for label in labels:
        proof: dict[str, Any] = {"label": label, "outcome": outcome}
        if safe_exit_code is not None:
            proof["exitCode"] = safe_exit_code
        if excerpt is not None:
            proof["diagnosticExcerpt"] = excerpt
        proofs.append(proof)
    return proofs


def _validated_codex_binary(path_text: str, expected_digest: str) -> Path:
    path = Path(path_text)
    if (
        not path.is_absolute()
        or path.is_symlink()
        or not path.is_file()
        or not os.access(path, os.X_OK)
    ):
        raise OSError("the explicitly configured Codex runtime is unavailable")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != expected_digest:
        raise OSError("the explicitly configured Codex runtime changed after resolution")
    return path


def _status_result(
    *,
    status: str,
    started: float,
    code: str | None = None,
    message: str | None = None,
    retryable: bool = False,
    error_details: Mapping[str, Any] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    error = None
    if code is not None:
        error = {"code": code, "message": message or code, "retryable": retryable}
        if error_details:
            error["details"] = dict(error_details)
    return {
        "status": status,
        "duration_ms": int((time.monotonic() - started) * 1000),
        "error": error,
        **extra,
    }


def _sdk_execution_error_details(phase: str) -> dict[str, str]:
    """Return the one safe phase fact for an otherwise opaque SDK exception.

    The outer exception can include a Provider body, runtime route, or local
    filesystem detail.  The phase is framework-owned control flow, so it is
    enough to distinguish a failed continuation restore from a failure after a
    model turn began without retaining exception prose.
    """

    return {
        "worker_phase": phase if phase in _SDK_EXECUTION_PHASES else "unknown",
    }


async def _interrupt(turn: Any, timeout_seconds: float) -> None:
    try:
        await asyncio.wait_for(turn.interrupt(), timeout=timeout_seconds)
    except Exception:
        # The parent hard watchdog will terminate the complete worker tree.
        return


def _app_server_environment(
    worker_environment: Mapping[str, str],
    runtime_path: Path | None,
) -> dict[str, str]:
    """Return the narrowly inherited app-server environment.

    The worker environment is already profile-resolved and contains only the
    allowlisted runtime variables plus the approved credential handles.  Codex
    feedback diagnostics otherwise serialize verbose startup context into its
    local SQLite feedback log, so keep the Rust log filter at ``error``.
    """

    environment = dict(worker_environment)
    environment["RUST_LOG"] = "error"
    if runtime_path is not None:
        current_path = environment.get("PATH", "")
        entries = [str(runtime_path)]
        entries.extend(
            entry
            for entry in current_path.split(os.pathsep)
            if entry and entry != str(runtime_path)
        )
        environment["PATH"] = os.pathsep.join(entries)
    return environment


def _app_server_launch_args(codex_binary: Path, *, hooks_enabled: bool) -> tuple[str, ...]:
    """Build a Codex app-server command without upstream routing material."""

    # No ``--strict-config``.  It makes the app-server refuse to start on any key
    # it does not recognize, which turns a harmless or newly-renamed setting into
    # an opaque ``sdk_session_open`` failure with no indication of which line was
    # at fault.  Codex ignoring a setting it does not understand is the tolerant
    # behavior we want; the settings that actually matter are asserted by the
    # framework itself rather than by refusing to boot.
    launch_args = [str(codex_binary)]
    if hooks_enabled:
        # Resolver-vetted hooks are copied into the otherwise empty
        # CODEX_HOME.  The SDK has no hook-trust API, so automation must use
        # the official CLI flag with the exact runtime bundled by the SDK.
        launch_args.append("--dangerously-bypass-hook-trust")
    launch_args.extend(("app-server", "--listen", "stdio://"))
    return tuple(launch_args)


def _thread_config_for_api_key_provider(base_url: str) -> dict[str, Any]:
    """Return the private, in-memory custom-provider override for one thread.

    Codex 0.144.4 no longer implicitly authenticates its built-in ``openai``
    provider from ``OPENAI_API_KEY``.  The app-server accepts this map only as
    a thread-start/resume request override; it is never written to the
    materialized ``config.toml`` or passed on the process command line.
    """

    return {
        f"model_providers.{_API_KEY_RUNTIME_PROVIDER}": {
            "name": "Agent World API-key provider",
            "base_url": base_url,
            "env_key": _OPENAI_API_KEY_ENVIRONMENT,
            "wire_api": "responses",
            # The Scheduler owns retries.  Do not permit invisible provider
            # retries below the InvocationBackend boundary.
            "request_max_retries": 0,
            "stream_max_retries": 0,
            "supports_websockets": False,
        }
    }


def _redactor_for_payload(payload: object) -> Redactor:
    """Build the outermost error redactor without trusting payload contents.

    Most failures become a typed worker result inside :func:`_run`, where the
    request's resolved sensitive environment names are available.  SDK/config
    construction can still throw before that inner handler.  The outer NDJSON
    protocol must therefore independently know the two framework-owned names,
    and may add only syntactically valid names supplied by the trusted parent.
    """

    names = {_OPENAI_API_KEY_ENVIRONMENT, _OPENAI_BASE_URL_ENVIRONMENT}
    if isinstance(payload, Mapping):
        raw_names = payload.get("sensitive_environment_names")
        if isinstance(raw_names, list):
            names.update(
                value
                for value in raw_names
                if isinstance(value, str) and _ENVIRONMENT_NAME.fullmatch(value)
            )
    return Redactor.from_values(value for name in names if (value := os.environ.get(name)))


async def _run(payload: dict[str, Any]) -> None:
    started = time.monotonic()
    raw_sensitive_names = payload.get("sensitive_environment_names", [])
    if not isinstance(raw_sensitive_names, list) or not all(
        isinstance(name, str) and _ENVIRONMENT_NAME.fullmatch(name) for name in raw_sensitive_names
    ):
        raise ValueError("sensitive_environment_names must contain environment names")
    redactor = _redactor_for_payload(payload)
    limits = _require_object(payload.get("limits"), "limits")
    emitter = Emitter(
        redactor=redactor,
        max_events=int(limits.get("max_events", 20_000)),
        max_protocol_bytes=int(limits.get("max_protocol_bytes", 32 * 1024 * 1024)),
    )
    structured_output_transport = payload.get("structured_output_transport", "provider_schema")
    if structured_output_transport not in {"provider_schema", "json_envelope"}:
        raise ValueError("unsupported structured output transport")

    authentication_kind = _require_string(payload.get("authentication_kind"), "authentication_kind")
    if authentication_kind != "api_key":
        raise ValueError("only API-key environment authentication is supported")
    authentication_environment = _require_string(
        payload.get("authentication_environment"), "authentication_environment"
    )
    if authentication_environment != _OPENAI_API_KEY_ENVIRONMENT:
        raise ValueError("API-key authentication must use OPENAI_API_KEY")
    if not os.environ.get(authentication_environment):
        emitter.result(
            _status_result(
                status="needs_human",
                started=started,
                code="authentication_missing",
                message="the resolved API-key credential is unavailable in the worker",
            )
        )
        return
    raw_base_url_environment = payload.get("openai_base_url_environment")
    if raw_base_url_environment is None:
        emitter.result(
            _status_result(
                status="needs_human",
                started=started,
                code="routing_configuration_missing",
                message="API-key runtime requires the OPENAI_BASE_URL environment handle",
            )
        )
        return
    base_url_environment = _require_string(raw_base_url_environment, "openai_base_url_environment")
    if base_url_environment != _OPENAI_BASE_URL_ENVIRONMENT:
        raise ValueError("openai_base_url_environment must be OPENAI_BASE_URL")
    base_url = os.environ.get(base_url_environment)
    if not base_url:
        emitter.result(
            _status_result(
                status="needs_human",
                started=started,
                code="routing_environment_missing",
                message="the resolved API base-URL environment is unavailable in the worker",
            )
        )
        return
    try:
        from openai_codex import (  # type: ignore[import-not-found]
            ApprovalMode,
            AsyncCodex,
            CodexConfig,
        )
        from openai_codex import (
            __version__ as sdk_version,
        )
        from openai_codex.generated.v2_all import ReasoningEffort as SdkReasoningEffort
    except (ImportError, ModuleNotFoundError) as exc:
        emitter.result(
            _status_result(
                status="needs_human",
                started=started,
                code="sdk_unavailable",
                message=f"openai-codex is not installed: {exc}",
            )
        )
        return

    if sdk_version != SUPPORTED_SDK_VERSION:
        emitter.result(
            _status_result(
                status="needs_human",
                started=started,
                code="sdk_version_unsupported",
                message=(
                    f"openai-codex {sdk_version} is installed; this adapter is pinned to "
                    f"{SUPPORTED_SDK_VERSION} because the SDK API is beta"
                ),
                backend_version=sdk_version,
            )
        )
        return

    configured_codex_bin = _optional_string(payload.get("codex_bin"), "codex_bin")
    configured_codex_digest = _optional_string(
        payload.get("codex_bin_sha256"),
        "codex_bin_sha256",
    )
    if (configured_codex_bin is None) != (configured_codex_digest is None):
        raise ValueError("codex_bin and codex_bin_sha256 must be present together")
    if configured_codex_bin is None or configured_codex_digest is None:
        emitter.result(
            _status_result(
                status="needs_human",
                started=started,
                code="profile_codex_runtime_missing",
                message="the resolved profile does not declare a pinned Codex runtime",
                backend_version=sdk_version,
            )
        )
        return
    try:
        codex_binary = await asyncio.to_thread(
            _validated_codex_binary,
            configured_codex_bin,
            configured_codex_digest,
        )
    except OSError as exc:
        emitter.result(
            _status_result(
                status="needs_human",
                started=started,
                code="codex_runtime_unavailable",
                message=str(exc),
                backend_version=sdk_version,
            )
        )
        return

    workspace = Path(_require_string(payload.get("workspace"), "workspace")).resolve()  # noqa: ASYNC240
    if not workspace.is_dir():
        emitter.result(
            _status_result(
                status="failed",
                started=started,
                code="workspace_missing",
                message="the resolved workspace no longer exists",
                backend_version=sdk_version,
            )
        )
        return
    sandbox_name = _require_string(payload.get("sandbox"), "sandbox")
    if sandbox_name not in {"read-only", "workspace-write"}:
        raise ValueError(f"unsupported sandbox: {sandbox_name!r}")
    reasoning_name = _require_string(payload.get("reasoning_effort"), "reasoning_effort")
    reasoning_effort = {
        "low": SdkReasoningEffort.low,
        "medium": SdkReasoningEffort.medium,
        "high": SdkReasoningEffort.high,
        "xhigh": SdkReasoningEffort.xhigh,
    }.get(reasoning_name)
    if reasoning_effort is None:
        emitter.result(
            _status_result(
                status="failed",
                started=started,
                code="reasoning_effort_unsupported",
                message=f"unsupported reasoning effort: {reasoning_name!r}",
                backend_version=sdk_version,
            )
        )
        return

    timeout_seconds = float(limits.get("timeout_seconds", 600.0))
    interrupt_grace_seconds = float(limits.get("interrupt_grace_seconds", 5.0))
    hooks_enabled = payload.get("hooks_enabled", False)
    if not isinstance(hooks_enabled, bool):
        raise ValueError("hooks_enabled must be a boolean")
    diagnostic_capture_terminal_excerpt = payload.get("diagnostic_capture_terminal_excerpt", False)
    if not isinstance(diagnostic_capture_terminal_excerpt, bool):
        raise ValueError("diagnostic_capture_terminal_excerpt must be a boolean")
    diagnostic_command_expectations = _parse_diagnostic_command_expectations(
        payload.get("diagnostic_command_expectations", [])
    )
    diagnostic_command_matches: dict[str, tuple[str, ...]] = {}
    deadline = started + timeout_seconds
    thread_id: str | None = None
    turn_id: str | None = None
    final_text: str | None = None
    unknown_phase_text: str | None = None
    usage: dict[str, Any] | None = None
    completed_turn: dict[str, Any] | None = None
    worker_phase = "sdk_session_open"

    try:
        app_server_environment = _app_server_environment(os.environ, runtime_path=None)
        launch_args = _app_server_launch_args(codex_binary, hooks_enabled=hooks_enabled)
        config = CodexConfig(
            cwd=str(workspace),
            env=app_server_environment,
            launch_args_override=launch_args,
            client_name="agent_world_foundry",
            client_title="Agent World Foundry",
            client_version=PROTOCOL_VERSION,
        )
        async with AsyncCodex(config) as codex:
            emitter.lifecycle("sdk_session_open")
            base_instructions = _require_string(
                payload.get("base_instructions"), "base_instructions"
            )
            developer_instructions = _optional_string(
                payload.get("developer_instructions"), "developer_instructions"
            )
            model = _require_string(payload.get("model"), "model")
            model_provider = _optional_string(payload.get("model_provider"), "model_provider")
            if model_provider != _API_KEY_RUNTIME_PROVIDER:
                raise ValueError("API-key profile must use the framework-owned custom provider")
            thread_config = _thread_config_for_api_key_provider(base_url)
            requested_thread_id = payload.get("thread_id")
            if requested_thread_id is None:
                worker_phase = "thread_start"
                emitter.lifecycle(worker_phase)
                thread = await codex.thread_start(
                    approval_mode=ApprovalMode.deny_all,
                    base_instructions=base_instructions,
                    config=thread_config,
                    cwd=str(workspace),
                    developer_instructions=developer_instructions,
                    # The parent binds this persisted Codex thread to a
                    # mode-0700 SQLite home below /dev/shm for the lifetime of
                    # its private framework session.  A new physical worker
                    # can then resume the same thread without putting rollout
                    # state into Artifacts, telemetry, or the Agent workspace.
                    ephemeral=False,
                    model=model,
                    model_provider=model_provider,
                )
            else:
                worker_phase = "thread_resume"
                emitter.lifecycle(worker_phase)
                thread = await codex.thread_resume(
                    _require_string(requested_thread_id, "thread_id"),
                    approval_mode=ApprovalMode.deny_all,
                    base_instructions=base_instructions,
                    config=thread_config,
                    cwd=str(workspace),
                    developer_instructions=developer_instructions,
                    model=model,
                    model_provider=model_provider,
                )
            thread_id = thread.id
            if requested_thread_id is not None and thread_id != requested_thread_id:
                raise RuntimeError("Codex resumed a different thread id")

            worker_phase = "turn_start"
            emitter.lifecycle(worker_phase)
            turn = await thread.turn(
                _require_string(payload.get("prompt"), "prompt"),
                approval_mode=ApprovalMode.deny_all,
                cwd=str(workspace),
                effort=reasoning_effort,
                model=model,
                output_schema=payload.get("output_schema"),
            )
            turn_id = turn.id
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                await _interrupt(turn, interrupt_grace_seconds)
                emitter.result(
                    _status_result(
                        status="timed_out",
                        started=started,
                        code="soft_timeout",
                        message="invocation deadline elapsed before the turn stream began",
                        thread_id=thread_id,
                        turn_id=turn_id,
                        backend_version=sdk_version,
                    )
                )
                return

            try:
                worker_phase = "turn_stream"
                emitter.lifecycle(worker_phase)
                async with asyncio.timeout(remaining):
                    async for notification in turn.stream():
                        event_payload = _notification_payload(notification.payload)
                        item = event_payload.get("item")
                        if isinstance(item, dict) and item.get("type") == "agentMessage":
                            text = item.get("text")
                            phase = item.get("phase")
                            if isinstance(text, str):
                                if phase == "final_answer":
                                    final_text = text
                                elif phase is None:
                                    unknown_phase_text = text
                        token_usage = event_payload.get("tokenUsage")
                        if isinstance(token_usage, dict):
                            usage = token_usage
                        terminal_turn = _completed_turn_payload(
                            notification.method,
                            event_payload,
                            turn_id,
                        )
                        emitter.event(
                            notification.method,
                            _compact_notification_payload(
                                notification.method,
                                event_payload,
                                diagnostic_command_expectations=diagnostic_command_expectations,
                                diagnostic_command_matches=diagnostic_command_matches,
                                diagnostic_command_redactor=redactor,
                            ),
                        )
                        if terminal_turn is not None:
                            completed_turn = terminal_turn
                            # A newer explicitly selected Codex CLI can add
                            # fields that the beta Python SDK decodes as an
                            # unknown notification model.  AsyncTurnHandle's
                            # own iterator then fails its concrete-class stop
                            # check even though the wire event is the exact
                            # terminal event for this turn.  The adapter owns
                            # the wire compatibility boundary, so stop on the
                            # validated method + exact turn id instead of
                            # waiting until the whole invocation deadline.
                            break
            except TimeoutError:
                await _interrupt(turn, interrupt_grace_seconds)
                emitter.result(
                    _status_result(
                        status="timed_out",
                        started=started,
                        code="soft_timeout",
                        message="Codex turn exceeded its resolved profile deadline",
                        thread_id=thread_id,
                        turn_id=turn_id,
                        usage=usage,
                        backend_version=sdk_version,
                    )
                )
                return
            except ProtocolBudgetExceeded as exc:
                await _interrupt(turn, interrupt_grace_seconds)
                emitter.result(
                    _status_result(
                        status="budget_exhausted",
                        started=started,
                        code="event_budget_exhausted",
                        message=str(exc),
                        thread_id=thread_id,
                        turn_id=turn_id,
                        usage=usage,
                        backend_version=sdk_version,
                    )
                )
                return
    except (FileNotFoundError, ImportError) as exc:
        emitter.result(
            _status_result(
                status="needs_human",
                started=started,
                code="codex_runtime_unavailable",
                message=str(exc),
                thread_id=thread_id,
                turn_id=turn_id,
                backend_version=sdk_version,
            )
        )
        return
    except Exception as exc:
        message = redactor.text(str(exc))
        lowered = message.lower()
        authentication_error = any(
            marker in lowered
            for marker in ("auth", "api key", "unauthorized", "forbidden", "login")
        )
        emitter.result(
            _status_result(
                status="needs_human" if authentication_error else "failed",
                started=started,
                code="authentication_failed" if authentication_error else "sdk_execution_failed",
                message=message or type(exc).__name__,
                retryable=not authentication_error,
                error_details=_sdk_execution_error_details(worker_phase),
                thread_id=thread_id,
                turn_id=turn_id,
                usage=usage,
                backend_version=sdk_version,
            )
        )
        return

    final_text = final_text if final_text is not None else unknown_phase_text
    if completed_turn is None:
        emitter.result(
            _status_result(
                status="failed",
                started=started,
                code="turn_completion_missing",
                message="Codex event stream ended without turn/completed",
                retryable=True,
                thread_id=thread_id,
                turn_id=turn_id,
                final_text=final_text,
                usage=usage,
                backend_version=sdk_version,
            )
        )
        return
    turn_status = completed_turn.get("status")
    if turn_status != "completed":
        error = completed_turn.get("error")
        terminal_code, terminal_details = (
            _terminal_turn_failure(
                error,
                diagnostic_capture_terminal_excerpt=diagnostic_capture_terminal_excerpt,
                redactor=redactor,
            )
            if turn_status == "failed"
            else (f"turn_{turn_status or 'unknown'}", {})
        )
        emitter.result(
            _status_result(
                status="failed" if turn_status == "failed" else "cancelled",
                started=started,
                code=terminal_code,
                # A provider's terminal ``message`` and ``additionalDetails``
                # are opaque response text. Persist only the fixed code and
                # closed details; the explicitly opted-in Doctor probe may
                # additionally receive its separately redacted local excerpt.
                message=terminal_code,
                retryable=turn_status == "failed",
                error_details=terminal_details,
                thread_id=thread_id,
                turn_id=turn_id,
                final_text=final_text,
                usage=usage,
                backend_version=sdk_version,
            )
        )
        return

    structured_output: Any = None
    if payload.get("output_schema") is not None:
        if final_text is None:
            emitter.result(
                _status_result(
                    status="failed",
                    started=started,
                    code="structured_output_missing",
                    message="Codex completed without the required structured final response",
                    thread_id=thread_id,
                    turn_id=turn_id,
                    usage=usage,
                    backend_version=sdk_version,
                )
            )
            return
        try:
            structured_output = json.loads(final_text, parse_constant=_reject_json_constant)
        except (json.JSONDecodeError, ValueError) as exc:
            emitter.result(
                _status_result(
                    status="failed",
                    started=started,
                    code="structured_output_invalid_json",
                    message=f"output_schema was requested but final response is not JSON: {exc}",
                    thread_id=thread_id,
                    turn_id=turn_id,
                    final_text=final_text,
                    usage=usage,
                    backend_version=sdk_version,
                )
            )
            return

    emitter.result(
        _status_result(
            status="completed",
            started=started,
            thread_id=thread_id,
            turn_id=turn_id,
            final_text=final_text,
            structured_output=structured_output,
            structured_output_transport=structured_output_transport,
            usage=usage,
            backend_version=sdk_version,
        )
    )


def main() -> int:
    started = time.monotonic()
    payload: object | None = None
    line = sys.stdin.buffer.readline(8 * 1024 * 1024 + 1)
    if len(line) > 8 * 1024 * 1024:
        _write_encoded(
            _encode_record(
                {
                    "type": "result",
                    "protocol_version": PROTOCOL_VERSION,
                    "result": _status_result(
                        status="failed",
                        started=started,
                        code="worker_request_too_large",
                        message="worker request exceeded 8 MiB",
                    ),
                }
            )
        )
        return 2
    try:
        payload = json.loads(line, parse_constant=_reject_json_constant)
        if not isinstance(payload, dict):
            raise ValueError("worker request must be a JSON object")
        if payload.get("protocol_version") != PROTOCOL_VERSION:
            raise ValueError("worker protocol version mismatch")
        asyncio.run(_run(payload))
        return 0
    except Exception as exc:
        redactor = _redactor_for_payload(payload)
        _write_encoded(
            _encode_record(
                {
                    "type": "result",
                    "protocol_version": PROTOCOL_VERSION,
                    "result": _status_result(
                        status="failed",
                        started=started,
                        code="worker_request_invalid",
                        message=redactor.text(str(exc) or type(exc).__name__),
                    ),
                }
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
