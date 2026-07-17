from dataclasses import dataclass

from agent_world.invocation._codex_worker import (
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
