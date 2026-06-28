from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from agent_world.artifacts import stable_json
from agent_world.fixtures.support_desk_lite import SupportDeskLite


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    surface = SupportDeskLite(
        Path(args.db),
        trace_path=Path(args.trace) if args.trace else None,
        task_id=args.task_id,
        call_group=args.call_group,
    )
    try:
        result = _execute(surface, args)
    except Exception as exc:
        sys.stderr.write(stable_json({"status": "error", "error": exc.__class__.__name__, "message": str(exc)}))
        sys.stderr.write("\n")
        return 2
    sys.stdout.write(stable_json({"status": "ok", "tool": _tool_name(args.command), "result": result}))
    sys.stdout.write("\n")
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m agent_world.fixtures.support_desk_lite_cli")
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--trace", default="")
    parser.add_argument("--task-id", default="")
    parser.add_argument("--call-group", default="")
    subparsers = parser.add_subparsers(dest="command", required=True)

    search = subparsers.add_parser("search-tickets")
    search.add_argument("--status", default="")
    search.add_argument("--customer-tier", default="")
    search.add_argument("--keyword", default="")
    search.add_argument("--queue", default="")

    get = subparsers.add_parser("get-ticket")
    get.add_argument("--ticket-id", required=True)

    note = subparsers.add_parser("add-ticket-note")
    note.add_argument("--ticket-id", required=True)
    note.add_argument("--visibility", required=True)
    note.add_argument("--body", required=True)

    priority = subparsers.add_parser("update-ticket-priority")
    priority.add_argument("--ticket-id", required=True)
    priority.add_argument("--priority", required=True)
    priority.add_argument("--note", required=True)

    assign = subparsers.add_parser("assign-ticket")
    assign.add_argument("--ticket-id", required=True)
    assign.add_argument("--queue", required=True)
    assign.add_argument("--assignee", required=True)
    assign.add_argument("--note", required=True)

    resolve = subparsers.add_parser("resolve-ticket")
    resolve.add_argument("--ticket-id", required=True)
    resolve.add_argument("--resolution-note", required=True)
    return parser


def _execute(surface: SupportDeskLite, args: argparse.Namespace) -> Any:
    if args.command == "search-tickets":
        return surface.search_tickets(
            status=_optional(args.status),
            customer_tier=_optional(args.customer_tier),
            keyword=_optional(args.keyword),
            queue=_optional(args.queue),
        )
    if args.command == "get-ticket":
        return surface.get_ticket(args.ticket_id)
    if args.command == "add-ticket-note":
        return surface.add_ticket_note(ticket_id=args.ticket_id, visibility=args.visibility, body=args.body)
    if args.command == "update-ticket-priority":
        return surface.update_ticket_priority(ticket_id=args.ticket_id, priority=args.priority, note=args.note)
    if args.command == "assign-ticket":
        return surface.assign_ticket(ticket_id=args.ticket_id, queue=args.queue, assignee=args.assignee, note=args.note)
    if args.command == "resolve-ticket":
        return surface.resolve_ticket(ticket_id=args.ticket_id, resolution_note=args.resolution_note)
    raise ValueError(f"Unsupported support-desk-lite CLI command: {args.command}")


def _optional(value: str) -> str | None:
    return value or None


def _tool_name(command: str) -> str:
    return command.replace("-", "_")


if __name__ == "__main__":
    raise SystemExit(main())
