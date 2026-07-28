from dataclasses import dataclass
from pathlib import Path

import pytest

from agent_world.invocation._codex_worker import (
    _app_server_environment,
    _app_server_launch_args,
    _compact_notification_payload,
    _completed_turn_payload,
    _notification_payload,
    _redactor_for_payload,
    _sdk_execution_error_details,
    _terminal_turn_failure,
    _terminal_turn_failure_code,
    _thread_config_for_api_key_provider,
)
from agent_world.invocation.contracts import InvocationError
from agent_world.invocation.redaction import Redactor, redacted_terminal_diagnostic_excerpt
from agent_world.invocation.structured_diagnostics import safe_terminal_details


@dataclass
class UnknownNotification:
    params: dict[str, object]


def test_worker_stops_on_wire_terminal_event_for_exact_turn() -> None:
    payload = {
        "turn": {
            "id": "turn-expected",
            "status": "completed",
            "futureCliField": {"isAcceptedByBetaSdk": False},
        }
    }

    assert (
        _completed_turn_payload(
            "turn/completed",
            payload,
            "turn-expected",
        )
        == payload["turn"]
    )
    assert _completed_turn_payload("turn/started", payload, "turn-expected") is None
    assert _completed_turn_payload("turn/completed", payload, "turn-other") is None


def test_unknown_sdk_notification_is_unwrapped_to_wire_payload() -> None:
    payload: dict[str, object] = {
        "threadId": "thread-1",
        "turn": {"id": "turn-expected", "status": "completed"},
    }

    assert _notification_payload(UnknownNotification(params=payload)) == payload


def test_terminal_turn_failure_without_closed_codex_kind_stays_unclassified() -> None:
    """Opaque prose may add non-routing clues but cannot assert a Provider cause."""

    routing_canary = "https://provider.example.test/v1?key=do-not-persist"
    code, details = _terminal_turn_failure(
        {
            "code": "invalid_request_error",
            "type": "server_error",
            "message": (
                "maximum context length exceeded; invalid JSON schema; "
                f"opaque route {routing_canary}"
            ),
            "additionalDetails": f"credential transcript: {routing_canary}",
        }
    )

    assert code == "turn_failed_unclassified_codex_error"
    assert details == {
        "terminal_error_shape": "object",
        "codex_error_info": "absent",
        "advisory_text_signals": [
            "context_or_token_limit",
            "request_or_schema_compatibility",
        ],
    }
    assert routing_canary not in repr((code, details))
    assert _terminal_turn_failure_code(None) == "turn_failed_unclassified_codex_error"


def test_sdk_execution_failure_details_expose_only_a_closed_worker_phase() -> None:
    assert _sdk_execution_error_details("thread_resume") == {"worker_phase": "thread_resume"}
    assert _sdk_execution_error_details("opaque provider exception") == {"worker_phase": "unknown"}


def test_terminal_turn_failure_prefers_closed_codex_error_info_over_opaque_message() -> None:
    routing_canary = "https://provider.example.test/v1?key=do-not-persist"

    assert (
        _terminal_turn_failure_code(
            {
                "codexErrorInfo": {"httpConnectionFailed": {"httpStatusCode": 400}},
                "message": f"opaque provider body includes {routing_canary}",
                "additionalDetails": f"credential transcript: {routing_canary}",
            }
        )
        == "turn_failed_invalid_request"
    )
    assert (
        _terminal_turn_failure_code(
            {
                "codexErrorInfo": "unauthorized",
                "message": f"opaque provider body includes {routing_canary}",
            }
        )
        == "turn_failed_authentication"
    )


def test_terminal_turn_failure_classifies_explicit_output_ceiling_without_prose() -> None:
    routing_canary = "https://provider.example.test/v1?key=do-not-persist"

    code, details = _terminal_turn_failure(
        {
            "codexErrorInfo": "other",
            "message": (
                "stream disconnected before completion: Incomplete response returned, "
                f"reason: max_output_tokens; opaque route {routing_canary}"
            ),
            "additionalDetails": f"credential transcript: {routing_canary}",
        }
    )

    assert code == "turn_failed_output_limit"
    assert details == {
        "terminal_error_shape": "object",
        "codex_error_info": "enum:other",
        "terminal_status": "incomplete",
        "terminal_reason": "max_output_tokens",
    }
    assert routing_canary not in repr((code, details))


def test_opted_in_doctor_terminal_excerpt_is_redacted_and_stays_out_of_normal_feedback() -> None:
    routing_canary = "https://provider.example.test/v1?key=do-not-persist"
    redaction_canary = "terminal-diagnostic-opaque"

    code, details = _terminal_turn_failure(
        {
            "codexErrorInfo": "other",
            "message": (f"Unsupported response_format for {redaction_canary} at {routing_canary}"),
        },
        diagnostic_capture_terminal_excerpt=True,
        redactor=Redactor.from_values((redaction_canary,)),
    )

    assert code == "turn_failed_unclassified_codex_error"
    assert details["advisory_text_signals"] == ["request_or_schema_compatibility"]
    assert "Unsupported response_format" in details["diagnostic_error_excerpt"]
    assert routing_canary not in details["diagnostic_error_excerpt"]
    assert redaction_canary not in details["diagnostic_error_excerpt"]


def test_opted_in_terminal_excerpt_is_available_for_a_known_codex_error_enum() -> None:
    routing_canary = "https://provider.example.test/v1?key=do-not-persist"
    redaction_canary = "known-enum-terminal-secret"

    code, details = _terminal_turn_failure(
        {
            "codexErrorInfo": "internalServerError",
            "message": f"Internal provider error for {redaction_canary} at {routing_canary}",
        },
        diagnostic_capture_terminal_excerpt=True,
        redactor=Redactor.from_values((redaction_canary,)),
    )

    assert code == "turn_failed_provider_unavailable"
    assert details["codex_error_info"] == "enum:internalservererror"
    assert "Internal provider error" in details["diagnostic_error_excerpt"]
    assert routing_canary not in details["diagnostic_error_excerpt"]
    assert redaction_canary not in details["diagnostic_error_excerpt"]
    assert safe_terminal_details(
        InvocationError(
            code=code,
            message=code,
            retryable=True,
            details=details,
        )
    ) == {
        "terminal_error_shape": "object",
        "codex_error_info": "enum:internalservererror",
    }


def test_terminal_diagnostic_excerpt_is_defensively_rescrubbed_before_local_write() -> None:
    redaction_canary = "diagnostic-sidecar-secret"
    opaque = "a" * 40

    excerpt = redacted_terminal_diagnostic_excerpt(
        (
            f"request failed at https://provider.example.test/v1 api_key={opaque} "
            f"secret={redaction_canary} token={opaque}"
        ),
        redactor=Redactor.from_values((redaction_canary,)),
    )

    assert excerpt is not None
    assert "provider.example.test" not in excerpt
    assert opaque not in excerpt
    assert redaction_canary not in excerpt
    assert "[REDACTED_URL]" in excerpt
    assert "[REDACTED]" in excerpt


def test_terminal_turn_failure_distinguishes_session_budget_from_provider_usage_limit() -> None:
    """The two closed Codex enums require different next investigations."""

    routing_canary = "https://provider.example.test/v1?key=do-not-persist"
    session_code, session_details = _terminal_turn_failure(
        {
            "codexErrorInfo": "sessionBudgetExceeded",
            "message": f"opaque provider body includes {routing_canary}",
        }
    )
    usage_code, usage_details = _terminal_turn_failure(
        {
            "codexErrorInfo": "usageLimitExceeded",
            "message": f"opaque provider body includes {routing_canary}",
        }
    )

    assert session_code == "turn_failed_session_budget_exhausted"
    assert usage_code == "turn_failed_usage_limit_exceeded"
    assert session_details == {
        "terminal_error_shape": "object",
        "codex_error_info": "enum:sessionbudgetexceeded",
    }
    assert usage_details == {
        "terminal_error_shape": "object",
        "codex_error_info": "enum:usagelimitexceeded",
    }
    assert routing_canary not in repr((session_details, usage_details))


def test_terminal_turn_failure_preserves_closed_sandbox_and_unknown_codex_kinds() -> None:
    routing_canary = "https://provider.example.test/v1?key=do-not-persist"

    sandbox_code, sandbox_details = _terminal_turn_failure(
        {
            "codexErrorInfo": "sandboxError",
            "message": f"opaque provider body includes {routing_canary}",
        }
    )
    unknown_code, unknown_details = _terminal_turn_failure(
        {
            "codexErrorInfo": "newFutureCodexTerminal",
            "message": f"opaque provider body includes {routing_canary}",
        }
    )

    assert sandbox_code == "turn_failed_sandbox_error"
    assert sandbox_details == {
        "terminal_error_shape": "object",
        "codex_error_info": "enum:sandboxerror",
    }
    assert unknown_code == "turn_failed_unclassified_codex_error"
    assert unknown_details == {
        "terminal_error_shape": "object",
        "codex_error_info": "enum:other",
    }
    assert routing_canary not in repr((sandbox_details, unknown_details))


def test_terminal_stream_disconnect_is_safe_retryable_provider_unavailability() -> None:
    routing_canary = "https://provider.example.test/v1?key=do-not-persist"

    code, details = _terminal_turn_failure(
        {
            "codexErrorInfo": {
                "responseStreamDisconnected": {"httpStatusCode": None},
            },
            "message": f"opaque provider body includes {routing_canary}",
            "additionalDetails": f"credential transcript: {routing_canary}",
        }
    )

    assert code == "turn_failed_provider_unavailable"
    assert details == {
        "terminal_error_shape": "object",
        "codex_error_info": "transport:response_stream_disconnected",
    }
    assert routing_canary not in repr(details)


def test_terminal_stream_http_status_stays_safe_and_specific() -> None:
    routing_canary = "https://provider.example.test/v1?key=do-not-persist"

    code, details = _terminal_turn_failure(
        {
            "codexErrorInfo": {
                "responseStreamConnectionFailed": {"httpStatusCode": 422},
            },
            "message": f"opaque provider body includes {routing_canary}",
        }
    )

    assert code == "turn_failed_invalid_request"
    assert details == {
        "terminal_error_shape": "object",
        "codex_error_info": "transport:response_stream_connection_failed",
        "http_status": 422,
    }
    assert routing_canary not in repr(details)


def test_worker_compacts_repeated_text_delta_without_losing_progress_metadata() -> None:
    payload = {
        "threadId": "thread-1",
        "turnId": "turn-1",
        "item": {
            "id": "item-1",
            "type": "agentMessage",
            "phase": "analysis",
            "text": "large repeated private reasoning delta" * 10_000,
        },
        "tokenUsage": {"inputTokens": 123, "outputTokens": 45},
        "futureLargeField": {"text": "not part of the worker protocol" * 10_000},
    }

    compact = _compact_notification_payload("item/agentMessage/delta", payload)

    assert compact == {
        "threadId": "thread-1",
        "turnId": "turn-1",
        "item": {"id": "item-1", "type": "agentMessage", "phase": "analysis"},
        "tokenUsage": {"inputTokens": 123, "outputTokens": 45},
        "sourceMethod": "item/agentMessage/delta",
    }
    assert len(str(compact)) < 512


def test_worker_keeps_custom_provider_routing_off_argv() -> None:
    routing_canary = "https://provider.example.test/v1"

    launch_args = _app_server_launch_args(
        Path("/opt/codex"),
        hooks_enabled=False,
    )

    assert launch_args == ("/opt/codex", "--strict-config", "app-server", "--listen", "stdio://")
    assert "--config" not in launch_args
    assert routing_canary not in " ".join(launch_args)
    assert _thread_config_for_api_key_provider(routing_canary) == {
        "model_providers.agent_world_api_key": {
            "name": "Agent World API-key provider",
            "base_url": routing_canary,
            "env_key": "OPENAI_API_KEY",
            "wire_api": "responses",
            "request_max_retries": 0,
            "stream_max_retries": 0,
            "supports_websockets": False,
        }
    }


def test_worker_forces_error_only_app_server_logging() -> None:
    environment = _app_server_environment(
        {"PATH": "/usr/bin", "RUST_LOG": "trace"},
        runtime_path=None,
    )

    assert environment["RUST_LOG"] == "error"
    assert environment["PATH"] == "/usr/bin"


def test_outer_worker_error_redactor_includes_runtime_routing_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-worker-key-value")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://provider.example.test/v1")

    redactor = _redactor_for_payload({"sensitive_environment_names": []})

    assert "test-worker-key-value" not in redactor.text(
        "failed for test-worker-key-value at https://provider.example.test/v1"
    )
    assert "https://provider.example.test/v1" not in redactor.text(
        "failed for test-worker-key-value at https://provider.example.test/v1"
    )
