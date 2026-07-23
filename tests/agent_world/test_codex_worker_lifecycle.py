from dataclasses import dataclass

from agent_world.invocation._codex_worker import (
    _compact_notification_payload,
    _completed_turn_payload,
    _notification_payload,
    _terminal_turn_failure_code,
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
