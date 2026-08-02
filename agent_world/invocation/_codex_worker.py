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
    redacted_local_diagnostic_excerpt,
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
from agent_world.invocation.structured_diagnostics import (  # noqa: E402
    advisory_provider_unavailable,
    advisory_terminal_text_signals,
)

PROTOCOL_VERSION = "agent-world.codex-worker.v1"
SUPPORTED_SDK_VERSION = "0.144.4"
_ENVIRONMENT_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
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
    # The generated protocol supplied no recognized closed kind.  Do not retain
    # ``code``, ``type``, ``message`` or ``additionalDetails``.  Reduce the
    # message inside this private worker to bounded signals; when *all* signals
    # identify only a transport disconnect or Provider internal failure, treat
    # the terminal as unavailable so the central policy can spend its bounded
    # infrastructure retry.  Mixed/semantic/auth/quota signals remain
    # unclassified and cannot mutate Prompt, Skill, schema, or candidate.
    _add_advisory_terminal_text_signals(details, error)
    if advisory_provider_unavailable(details):
        return "turn_failed_provider_unavailable", details
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

    signals = advisory_terminal_text_signals(error.get("message"))
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


def _sdk_execution_error_details(
    phase: str,
    *,
    diagnostic_exception: object | None = None,
    diagnostic_redactor: Redactor | None = None,
) -> dict[str, Any]:
    """Return safe SDK-startup facts, with an opt-in local excerpt when needed.

    The outer exception can include a Provider body, runtime route, or local
    filesystem detail.  The phase is framework-owned control flow, so it is
    enough to distinguish a failed continuation restore from a failure after a
    model turn began without retaining exception prose.  The one exception is
    an explicitly diagnostic probe: a bounded, path/URL/secret-scrubbed
    exception excerpt lets a project-execution Agent tell an app-server boot
    problem from a malformed request.  It is stripped from normal feedback by
    ``safe_terminal_details`` and written only to the private audit/Doctor
    sidecar.
    """

    details: dict[str, Any] = {
        "worker_phase": phase if phase in _SDK_EXECUTION_PHASES else "unknown",
    }
    if diagnostic_exception is not None and diagnostic_redactor is not None:
        excerpt = redacted_local_diagnostic_excerpt(
            diagnostic_exception,
            redactor=diagnostic_redactor,
        )
        if excerpt is not None:
            details["diagnostic_error_excerpt"] = excerpt
    return details


def _structured_output_invalid_json_details(
    final_text: str,
    error: json.JSONDecodeError | ValueError,
    *,
    diagnostic_capture_terminal_excerpt: bool,
    redactor: Redactor,
) -> dict[str, Any]:
    """Describe a malformed final response without retaining its contents.

    A Codex Agent can complete its turn yet emit prose, a markdown fence, or a
    truncated JSON value where the profile requires structured output.  The
    normal failure path needs only closed shape/parse facts; raw final text is
    not Scheduler feedback.  An explicitly opted-in local diagnostic may add
    one bounded, double-redacted excerpt so the project-execution Agent can
    distinguish an instruction/Skill conflict from an adapter/schema issue.
    """

    stripped = final_text.lstrip()
    if not stripped:
        response_shape = "empty"
    elif stripped.startswith("```"):
        response_shape = "markdown_fence"
    elif stripped.startswith("{"):
        response_shape = "object"
    elif stripped.startswith("["):
        response_shape = "array"
    else:
        response_shape = "non_json"

    parse_failure = "syntax"
    parse_offset: int | None = None
    if isinstance(error, json.JSONDecodeError):
        parse_offset = max(0, error.pos)
        if error.msg == "Extra data":
            parse_failure = "extra_data"
        elif error.msg.startswith("Unterminated") or error.pos >= len(final_text):
            parse_failure = "truncated"
    elif "constant" in str(error).lower():
        parse_failure = "nonfinite_number"

    details: dict[str, Any] = {
        "response_shape": response_shape,
        "parse_failure": parse_failure,
        "response_characters": len(final_text),
    }
    if parse_offset is not None:
        details["parse_offset"] = parse_offset
    if diagnostic_capture_terminal_excerpt:
        excerpt = redacted_terminal_diagnostic_excerpt(final_text, redactor=redactor)
        if excerpt is not None:
            details["diagnostic_error_excerpt"] = excerpt
    return details


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


def _app_server_launch_args(codex_binary: Path) -> tuple[str, ...]:
    """Build a Codex app-server command without upstream routing material."""

    # No ``--strict-config``.  It makes the app-server refuse to start on any key
    # it does not recognize, which turns a harmless or newly-renamed setting into
    # an opaque ``sdk_session_open`` failure with no indication of which line was
    # at fault.  Codex ignoring a setting it does not understand is the tolerant
    # behavior we want; the settings that actually matter are asserted by the
    # framework itself rather than by refusing to boot.
    return (str(codex_binary), "app-server", "--listen", "stdio://")


def _thread_config_for_api_key_provider(
    base_url: str, *, transport_max_retries: int = 0
) -> dict[str, Any]:
    """Return the private, in-memory custom-provider override for one thread.

    Codex 0.144.4 no longer implicitly authenticates its built-in ``openai``
    provider from ``OPENAI_API_KEY``.  The app-server accepts this map only as
    a thread-start/resume request override; it is never written to the
    materialized ``config.toml`` or passed on the process command line.
    """

    retries = transport_max_retries if isinstance(transport_max_retries, int) else 0
    retries = max(0, retries)
    return {
        f"model_providers.{_API_KEY_RUNTIME_PROVIDER}": {
            "name": "Agent World API-key provider",
            "base_url": base_url,
            "env_key": _OPENAI_API_KEY_ENVIRONMENT,
            "wire_api": "responses",
            # The Scheduler still owns semantic and turn-level retries.  These
            # bounded transport retries only cover connection failures / 429 /
            # >=500 *before* a Provider event is observed; Codex never resumes a
            # stream that already emitted content, so a smoothed intermittent
            # relay does not hide a turn failure.  ``0`` restores the prior
            # "Scheduler owns every retry" policy.
            "request_max_retries": retries,
            "stream_max_retries": retries,
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
            Sandbox,
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
    if sandbox_name != "full-access":
        raise ValueError(f"unsupported execution mode: {sandbox_name!r}")
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
    diagnostic_capture_terminal_excerpt = payload.get("diagnostic_capture_terminal_excerpt", False)
    if not isinstance(diagnostic_capture_terminal_excerpt, bool):
        raise ValueError("diagnostic_capture_terminal_excerpt must be a boolean")
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
        launch_args = _app_server_launch_args(codex_binary)
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
            model = _require_string(payload.get("model"), "model")
            model_provider = _optional_string(payload.get("model_provider"), "model_provider")
            if model_provider != _API_KEY_RUNTIME_PROVIDER:
                raise ValueError("API-key profile must use the framework-owned custom provider")
            raw_transport_retries = payload.get("provider_transport_max_retries", 0)
            transport_max_retries = (
                raw_transport_retries
                if isinstance(raw_transport_retries, int)
                and not isinstance(raw_transport_retries, bool)
                and raw_transport_retries >= 0
                else 0
            )
            thread_config = _thread_config_for_api_key_provider(
                base_url, transport_max_retries=transport_max_retries
            )
            requested_thread_id = payload.get("thread_id")
            if requested_thread_id is None:
                worker_phase = "thread_start"
                emitter.lifecycle(worker_phase)
                thread = await codex.thread_start(
                    approval_mode=ApprovalMode.deny_all,
                    config=thread_config,
                    cwd=str(workspace),
                    # The parent binds this persisted Codex thread to a
                    # mode-0700 SQLite home below /dev/shm for the lifetime of
                    # its private framework session.  A new physical worker
                    # can then resume the same thread without putting rollout
                    # state into Artifacts, telemetry, or the Agent workspace.
                    ephemeral=False,
                    model=model,
                    model_provider=model_provider,
                    sandbox=Sandbox.full_access,
                )
            else:
                worker_phase = "thread_resume"
                emitter.lifecycle(worker_phase)
                thread = await codex.thread_resume(
                    _require_string(requested_thread_id, "thread_id"),
                    approval_mode=ApprovalMode.deny_all,
                    config=thread_config,
                    cwd=str(workspace),
                    model=model,
                    model_provider=model_provider,
                    sandbox=Sandbox.full_access,
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
                sandbox=Sandbox.full_access,
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
                            _compact_notification_payload(notification.method, event_payload),
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
                error_details=_sdk_execution_error_details(
                    worker_phase,
                    diagnostic_exception=(message if diagnostic_capture_terminal_excerpt else None),
                    diagnostic_redactor=(redactor if diagnostic_capture_terminal_excerpt else None),
                ),
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
                    error_details=_structured_output_invalid_json_details(
                        final_text,
                        exc,
                        diagnostic_capture_terminal_excerpt=diagnostic_capture_terminal_excerpt,
                        redactor=redactor,
                    ),
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
