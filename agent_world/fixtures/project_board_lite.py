from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from agent_world.artifacts import stable_json


def create_seed_state() -> dict[str, Any]:
    return {
        "board": [
            {"id": "board-alpha", "name": "Launch Board", "workflow_statuses": ["todo", "in_progress", "blocked", "in_review", "done"]},
        ],
        "card": [
            {"id": "C-10", "board_id": "board-alpha", "title": "Checkout bug", "status": "todo", "priority": "high", "assignee": "unassigned"},
            {"id": "C-11", "board_id": "board-alpha", "title": "Payment API failing", "status": "blocked", "priority": "urgent", "assignee": "mei"},
            {"id": "C-12", "board_id": "board-alpha", "title": "Settings page polish", "status": "in_progress", "priority": "medium", "assignee": "eve"},
        ],
        "comment": [],
        "audit_event": [],
    }


def reset_environment(seed_state: dict[str, Any] | None = None) -> dict[str, Any]:
    return copy.deepcopy(seed_state or create_seed_state())


class ProjectBoardLite:
    """Python callable fixture surface for Goal 06 pipeline verification."""

    def __init__(self, state: dict[str, Any], *, trace_path: Path | None = None, task_id: str | None = None, call_group: str | None = None):
        self.state = state
        self.trace_path = Path(trace_path) if trace_path else None
        self.task_id = task_id
        self.call_group = call_group or task_id or "ad-hoc"

    def card_list(self, *, status: str | None = None, assignee: str | None = None, priority: str | None = None) -> list[dict[str, Any]]:
        cards = [
            copy.deepcopy(card)
            for card in self.state["card"]
            if (status is None or card["status"] == status)
            and (assignee is None or card["assignee"] == assignee)
            and (priority is None or card["priority"] == priority)
        ]
        self._trace("card_list", {"status": status, "assignee": assignee, "priority": priority}, cards)
        return cards

    def card_get(self, card_id: str) -> dict[str, Any]:
        card = _card_detail(self.state, card_id)
        self._trace("card_get", {"card_id": card_id}, {"card_id": card_id})
        return card

    def card_move(self, *, card_id: str, status: str, note: str) -> dict[str, Any]:
        _ensure_status(self.state, status)
        card = _card(self.state, card_id)
        old = card["status"]
        card["status"] = status
        _audit(self.state, card_id, "card_moved", "status", old, status, note)
        result = _card_detail(self.state, card_id)
        self._trace("card_move", {"card_id": card_id, "status": status, "note": note}, {"card_id": card_id, "status": status})
        return result

    def card_assign(self, *, card_id: str, assignee: str, note: str) -> dict[str, Any]:
        card = _card(self.state, card_id)
        old = card["assignee"]
        card["assignee"] = assignee
        _audit(self.state, card_id, "card_assigned", "assignee", old, assignee, note)
        result = _card_detail(self.state, card_id)
        self._trace("card_assign", {"card_id": card_id, "assignee": assignee, "note": note}, {"card_id": card_id, "assignee": assignee})
        return result

    def comment_add(self, *, card_id: str, body: str) -> dict[str, Any]:
        _card(self.state, card_id)
        comment = {"card_id": card_id, "body": body, "created_by": "agent"}
        self.state["comment"].append(comment)
        _audit(self.state, card_id, "comment_added", "comment", "", body, body)
        self._trace("comment_add", {"card_id": card_id, "body": body}, comment)
        return copy.deepcopy(comment)

    def _trace(self, tool: str, inputs: dict[str, Any], output: Any) -> None:
        if not self.trace_path:
            return
        self.trace_path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "tool": tool,
            "task_id": self.task_id,
            "call_group": self.call_group,
            "inputs": inputs,
            "output_preview": str(output)[:500],
            "snapshot_hash": snapshot_hash(self.state),
        }
        with self.trace_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True))
            handle.write("\n")


def verify_task_completion(
    task_id: str,
    initial_state: dict[str, Any],
    final_state: dict[str, Any],
    final_answer: Any = None,
    surface_trace_path: Path | None = None,
    expected_dependency_path: list[str] | None = None,
    trace_call_group: str | None = None,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def add(name: str, passed: bool, detail: Any) -> None:
        checks.append({"name": name, "passed": bool(passed), "detail": detail})

    expected_dependency_path = expected_dependency_path or _expected_dependency_path(task_id)
    add(
        "dependency_path_trace_matches",
        bool(surface_trace_path and expected_dependency_path and _trace_matches(surface_trace_path, task_id, expected_dependency_path, trace_call_group)),
        {"trace_path": str(surface_trace_path) if surface_trace_path else "", "expected": expected_dependency_path},
    )
    if task_id == "pb-task-1":
        add("target_card_moved", _card(final_state, "C-11")["status"] == "in_review", _card(final_state, "C-11"))
        add("audit_written", _has_audit(final_state, "C-11", "card_moved", "status", "in_review"), final_state["audit_event"])
        add("non_target_cards_preserved", _non_target_cards_preserved(initial_state, final_state, {"C-11"}), "")
    elif task_id == "pb-task-2":
        add("target_card_assigned", _card(final_state, "C-10")["assignee"] == "sam", _card(final_state, "C-10"))
        add("target_comment_added", any(comment["card_id"] == "C-10" and "triage" in comment["body"].lower() for comment in final_state["comment"]), final_state["comment"])
        add("audit_written", _has_audit(final_state, "C-10", "card_assigned", "assignee", "sam"), final_state["audit_event"])
        add("non_target_cards_preserved", _non_target_cards_preserved(initial_state, final_state, {"C-10"}), "")
    elif task_id == "pb-task-3":
        expected = {"status": "in_progress", "assignee": "eve", "card_count": 1, "highest_priority": "medium"}
        add("answer_matches", final_answer == expected, {"expected": expected, "actual": final_answer})
        add("state_unchanged", initial_state == final_state, "")
    else:
        add("known_task", False, task_id)
    return {"task_id": task_id, "success": all(check["passed"] for check in checks), "checks": checks}


def snapshot_hash(state: dict[str, Any]) -> str:
    import hashlib

    return hashlib.sha256(stable_json(state).encode("utf-8")).hexdigest()


def _card(state: dict[str, Any], card_id: str) -> dict[str, Any]:
    for card in state["card"]:
        if card["id"] == card_id:
            return card
    raise KeyError(f"Unknown card: {card_id}")


def _card_detail(state: dict[str, Any], card_id: str) -> dict[str, Any]:
    card = copy.deepcopy(_card(state, card_id))
    card["comments"] = [copy.deepcopy(comment) for comment in state["comment"] if comment["card_id"] == card_id]
    card["audit_events"] = [copy.deepcopy(event) for event in state["audit_event"] if event["card_id"] == card_id]
    return card


def _ensure_status(state: dict[str, Any], status: str) -> None:
    statuses = state["board"][0]["workflow_statuses"]
    if status not in statuses:
        raise ValueError(f"status must be one of {statuses}")


def _audit(state: dict[str, Any], card_id: str, event_type: str, field: str, old_value: str, new_value: str, note: str) -> None:
    state["audit_event"].append(
        {
            "card_id": card_id,
            "event_type": event_type,
            "field": field,
            "old_value": old_value,
            "new_value": new_value,
            "note": note,
        }
    )


def _has_audit(state: dict[str, Any], card_id: str, event_type: str, field: str, new_value: str) -> bool:
    return any(
        event["card_id"] == card_id
        and event["event_type"] == event_type
        and event["field"] == field
        and event["new_value"] == new_value
        for event in state["audit_event"]
    )


def _non_target_cards_preserved(initial: dict[str, Any], final: dict[str, Any], target_ids: set[str]) -> bool:
    initial_cards = {card["id"]: card for card in initial["card"] if card["id"] not in target_ids}
    final_cards = {card["id"]: card for card in final["card"] if card["id"] not in target_ids}
    return initial_cards == final_cards


def _expected_dependency_path(task_id: str) -> list[str]:
    return {
        "pb-task-1": ["card_list", "card_get", "card_move"],
        "pb-task-2": ["card_list", "card_assign", "comment_add"],
        "pb-task-3": ["card_list"],
    }.get(task_id, [])


def _trace_matches(trace_path: Path, task_id: str, expected: list[str], call_group: str | None) -> bool:
    if not trace_path.exists():
        return False
    records = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    filtered = [
        record
        for record in records
        if record.get("task_id") == task_id and (call_group is None or record.get("call_group") == call_group)
    ]
    return [record["tool"] for record in filtered] == expected
