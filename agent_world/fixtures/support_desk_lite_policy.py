from __future__ import annotations

from typing import Any, Mapping

from agent_world.fixtures.support_desk_lite import SupportDeskLite


POLICY_ID = "scripted-support-desk-lite-v1"


def execute_support_desk_lite_policy(surface: SupportDeskLite, task: Mapping[str, Any]) -> Any:
    """Deterministic fixture policy used by replay and Goal 02 rollout consumers."""
    task_id = str(task["task_id"])
    path = list(task["dependency_path"])
    ticket_id = "T-100"
    if task_id == "task-2":
        ticket_id = "T-101"
    elif task_id == "task-5":
        ticket_id = "T-102"

    if "search_tickets" in path:
        if task_id in {"task-1", "task-3"}:
            surface.search_tickets(status="open", customer_tier="vip", keyword="refund")
        elif task_id == "task-2":
            surface.search_tickets(status="open", customer_tier="standard", keyword="login")
        elif task_id == "task-4":
            surface.search_tickets(status="open", customer_tier="vip")
        elif task_id == "task-5":
            surface.search_tickets(status="open", customer_tier="vip", keyword="duplicate")
    if "get_ticket" in path:
        surface.get_ticket(ticket_id)

    if task_id == "task-1":
        surface.add_ticket_note(ticket_id="T-100", visibility="internal", body="Refund follow-up queued with billing.")
    elif task_id == "task-2":
        surface.assign_ticket(ticket_id="T-101", queue="enterprise-support", assignee="iris", note="Moved to enterprise support.")
    elif task_id == "task-3":
        surface.update_ticket_priority(ticket_id="T-100", priority="high", note="VIP refund issue is under-prioritized.")
    elif task_id == "task-4":
        return {"customer_id": "cust-vip", "open_ticket_count": 2, "highest_priority": "medium"}
    elif task_id == "task-5":
        surface.resolve_ticket(ticket_id="T-102", resolution_note="Resolved and closed duplicate refund confirmation.")
    return None
