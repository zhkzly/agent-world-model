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
    _terminal_turn_failure_code,
    _thread_config_for_api_key_provider,
)


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

    assert _completed_turn_payload(
        "turn/completed",
        payload,
        "turn-expected",
    ) == payload["turn"]
    assert _completed_turn_payload("turn/started", payload, "turn-expected") is None
    assert _completed_turn_payload("turn/completed", payload, "turn-other") is None


def test_unknown_sdk_notification_is_unwrapped_to_wire_payload() -> None:
    payload = {
        "threadId": "thread-1",
        "turn": {"id": "turn-expected", "status": "completed"},
    }

    assert _notification_payload(UnknownNotification(params=payload)) == payload


def test_terminal_turn_failure_retains_only_a_fixed_safe_category() -> None:
    assert _terminal_turn_failure_code(
        {
            "code": "invalid_request_error",
            "message": "request body includes a private endpoint and API key",
        }
    ) == "turn_failed_invalid_request"
    assert _terminal_turn_failure_code(
        {"message": "unrecognized opaque provider response 8f4d"}
    ) == "turn_failed_provider_rejected"
    assert _terminal_turn_failure_code(
        {"message": "maximum context length exceeded"}
    ) == "turn_failed_context_window"
    assert _terminal_turn_failure_code(
        {"message": "invalid JSON schema for response format"}
    ) == "turn_failed_output_schema"


def test_terminal_turn_failure_prefers_closed_codex_error_info_over_opaque_message() -> None:
    routing_canary = "https://provider.example.test/v1?key=do-not-persist"

    assert _terminal_turn_failure_code(
        {
            "codexErrorInfo": {"httpConnectionFailed": {"httpStatusCode": 400}},
            "message": f"opaque provider body includes {routing_canary}",
            "additionalDetails": f"credential transcript: {routing_canary}",
        }
    ) == "turn_failed_invalid_request"
    assert _terminal_turn_failure_code(
        {
            "codexErrorInfo": "unauthorized",
            "message": f"opaque provider body includes {routing_canary}",
        }
    ) == "turn_failed_authentication"


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
