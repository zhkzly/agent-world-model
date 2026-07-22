from dataclasses import dataclass

from agent_world.invocation._codex_worker import (
    _compact_notification_payload,
    _completed_turn_payload,
    _notification_payload,
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
