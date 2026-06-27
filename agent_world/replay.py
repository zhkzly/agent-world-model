from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

from agent_world.fixtures.support_desk_lite import SupportDeskLite, reset_environment, verify_task_completion
from agent_world.fixtures.support_desk_lite import snapshot_hash


def replay_package(package_dir: Path, task_id: str) -> dict:
    tasks = {task["task_id"]: task for task in _load_yaml(package_dir / "spec" / "tasks.yaml")["tasks"]}
    replay_plan = _load_yaml(package_dir / "checks" / "replay-plan.yaml")
    if task_id not in tasks:
        raise ValueError(f"Unknown task_id: {task_id}")
    if task_id not in replay_plan["task_ids"]:
        raise ValueError(f"Task is not in replay plan: {task_id}")
    task = tasks[task_id]
    seed = package_dir / "fixtures" / "seed" / "support-desk-lite.sqlite"
    run_dir = package_dir / "replay" / task_id
    final = reset_environment(seed, run_dir)
    trace_path = package_dir / "checks" / "surface-traces.jsonl"
    call_group = _next_call_group(trace_path, task_id)
    initial_hash = snapshot_hash(final)
    surface = SupportDeskLite(final, trace_path=trace_path, task_id=task_id, call_group=call_group)
    _execute_declared_path(surface, task)
    if task_id == "task-4":
        answer = {"customer_id": "cust-vip", "open_ticket_count": 2, "highest_priority": "medium"}
    else:
        answer = None
    verifier_result = verify_task_completion(
        task_id,
        seed,
        final,
        final_answer=answer,
        surface_trace_path=trace_path,
        expected_dependency_path=task["dependency_path"],
        trace_call_group=call_group,
    )
    _append_summary_trace(trace_path, task_id, call_group, task["dependency_path"], initial_hash, snapshot_hash(final), verifier_result)
    return verifier_result


def _execute_declared_path(surface: SupportDeskLite, task: dict) -> None:
    task_id = task["task_id"]
    path = task["dependency_path"]
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
        return
    elif task_id == "task-5":
        surface.resolve_ticket(ticket_id="T-102", resolution_note="Resolved and closed duplicate refund confirmation.")


def _append_summary_trace(trace_path: Path, task_id: str, call_group: str, dependency_path: list[str], initial_hash: str, final_hash: str, verifier_result: dict) -> None:
    record = {
        "task_id": task_id,
        "call_group": call_group,
        "surface_calls": dependency_path,
        "initial_snapshot_hash": initial_hash,
        "final_snapshot_hash": final_hash,
        "verifier_result": verifier_result,
    }
    with trace_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True))
            handle.write("\n")


def _next_call_group(trace_path: Path, task_id: str) -> str:
    next_index = 1
    if trace_path.exists():
        for line in trace_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            if record.get("task_id") == task_id and "surface_calls" in record:
                next_index += 1
    return f"{task_id}-run-{next_index}"


def _load_yaml(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", required=True, type=Path)
    parser.add_argument("--task", required=True)
    args = parser.parse_args()
    result = replay_package(args.package, args.task)
    print(result)
    raise SystemExit(0 if result["success"] else 1)


if __name__ == "__main__":
    main()
