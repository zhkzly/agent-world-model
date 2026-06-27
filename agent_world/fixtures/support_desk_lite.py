from __future__ import annotations

import shutil
import sqlite3
import json
import hashlib
from pathlib import Path
from typing import Any


SCHEMA_SQL = """
CREATE TABLE customer (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  tier TEXT NOT NULL,
  region TEXT NOT NULL,
  email TEXT NOT NULL
);

CREATE TABLE ticket (
  id TEXT PRIMARY KEY,
  customer_id TEXT NOT NULL REFERENCES customer(id),
  status TEXT NOT NULL,
  priority TEXT NOT NULL,
  subject TEXT NOT NULL,
  description TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE ticket_note (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ticket_id TEXT NOT NULL REFERENCES ticket(id),
  visibility TEXT NOT NULL,
  body TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE assignment (
  ticket_id TEXT PRIMARY KEY REFERENCES ticket(id),
  assignee TEXT NOT NULL,
  queue TEXT NOT NULL
);

CREATE TABLE audit_event (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ticket_id TEXT NOT NULL REFERENCES ticket(id),
  event_type TEXT NOT NULL,
  field TEXT NOT NULL,
  old_value TEXT NOT NULL,
  new_value TEXT NOT NULL,
  note TEXT NOT NULL,
  created_at TEXT NOT NULL
);
"""

SEED_ROWS = {
    "customer": [
        ("cust-vip", "Acme Corp", "vip", "na", "ops@acme.example"),
        ("cust-standard", "Northwind", "standard", "eu", "help@northwind.example"),
    ],
    "ticket": [
        (
            "T-100",
            "cust-vip",
            "open",
            "medium",
            "Refund delayed for enterprise renewal",
            "VIP customer reports that a refund for a double-charged renewal has not arrived.",
            "2026-06-20T09:00:00Z",
            "2026-06-20T09:00:00Z",
        ),
        (
            "T-101",
            "cust-standard",
            "open",
            "high",
            "Login outage after SSO change",
            "High-priority outage has been idle for more than 48 hours.",
            "2026-06-18T10:00:00Z",
            "2026-06-18T10:00:00Z",
        ),
        (
            "T-102",
            "cust-vip",
            "open",
            "low",
            "Duplicate refund confirmation",
            "Customer asks whether a duplicate refund confirmation can be closed.",
            "2026-06-21T11:00:00Z",
            "2026-06-21T11:00:00Z",
        ),
        (
            "T-103",
            "cust-vip",
            "resolved",
            "high",
            "Previous invoice correction",
            "Resolved invoice correction kept for history.",
            "2026-06-10T08:00:00Z",
            "2026-06-12T08:00:00Z",
        ),
    ],
    "assignment": [
        ("T-100", "mira", "billing"),
        ("T-101", "unassigned", "frontline"),
        ("T-102", "mira", "billing"),
        ("T-103", "sora", "billing"),
    ],
}


def create_seed_db(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    conn = sqlite3.connect(path)
    try:
        conn.executescript(SCHEMA_SQL)
        conn.executemany("INSERT INTO customer VALUES (?, ?, ?, ?, ?)", SEED_ROWS["customer"])
        conn.executemany("INSERT INTO ticket VALUES (?, ?, ?, ?, ?, ?, ?, ?)", SEED_ROWS["ticket"])
        conn.executemany("INSERT INTO assignment VALUES (?, ?, ?)", SEED_ROWS["assignment"])
        conn.commit()
    finally:
        conn.close()
    return path


def reset_environment(seed_db: Path, run_dir: Path) -> Path:
    run_dir.mkdir(parents=True, exist_ok=True)
    final_db = run_dir / "support-desk-lite.sqlite"
    shutil.copyfile(seed_db, final_db)
    return final_db


def snapshot_state(db_path: Path) -> dict[str, list[dict[str, Any]]]:
    conn = _connect(db_path)
    try:
        return {
            table: _query(conn, f"SELECT * FROM {table} ORDER BY 1")
            for table in ["customer", "ticket", "ticket_note", "assignment", "audit_event"]
        }
    finally:
        conn.close()


class SupportDeskLite:
    """Python callable surface for the first runnable fixture."""

    def __init__(
        self,
        db_path: Path,
        trace_path: Path | None = None,
        task_id: str | None = None,
        call_group: str | None = None,
    ):
        self.db_path = Path(db_path)
        self.trace_path = Path(trace_path) if trace_path else None
        self.task_id = task_id
        self.call_group = call_group or task_id or "ad-hoc"

    def search_tickets(
        self,
        *,
        status: str | None = None,
        customer_tier: str | None = None,
        keyword: str | None = None,
        queue: str | None = None,
    ) -> list[dict[str, Any]]:
        sql = """
        SELECT t.id, t.status, t.priority, t.subject, t.description,
               c.id AS customer_id, c.name AS customer_name, c.tier AS customer_tier,
               a.assignee, a.queue
        FROM ticket t
        JOIN customer c ON c.id = t.customer_id
        JOIN assignment a ON a.ticket_id = t.id
        WHERE 1=1
        """
        params: list[Any] = []
        if status:
            sql += " AND t.status = ?"
            params.append(status)
        if customer_tier:
            sql += " AND c.tier = ?"
            params.append(customer_tier)
        if keyword:
            sql += " AND (LOWER(t.subject) LIKE ? OR LOWER(t.description) LIKE ?)"
            needle = f"%{keyword.lower()}%"
            params.extend([needle, needle])
        if queue:
            sql += " AND a.queue = ?"
            params.append(queue)
        sql += " ORDER BY t.id"
        conn = _connect(self.db_path)
        try:
            result = _query(conn, sql, params)
            self._trace("search_tickets", {"status": status, "customer_tier": customer_tier, "keyword": keyword, "queue": queue}, result)
            return result
        finally:
            conn.close()

    def get_ticket(self, ticket_id: str) -> dict[str, Any]:
        conn = _connect(self.db_path)
        try:
            ticket = _ticket_detail(conn, ticket_id)
            self._trace("get_ticket", {"ticket_id": ticket_id}, {"ticket_id": ticket_id})
            return ticket
        finally:
            conn.close()

    def add_ticket_note(self, *, ticket_id: str, visibility: str, body: str) -> dict[str, Any]:
        if visibility not in {"internal", "customer"}:
            raise ValueError("visibility must be internal or customer")
        conn = _connect(self.db_path)
        try:
            _ensure_ticket(conn, ticket_id)
            conn.execute(
                "INSERT INTO ticket_note(ticket_id, visibility, body, created_at) VALUES (?, ?, ?, ?)",
                [ticket_id, visibility, body, _now()],
            )
            _audit(conn, ticket_id, "note_added", "ticket_note", "", visibility, body)
            conn.commit()
            note = _ticket_detail(conn, ticket_id)["notes"][-1]
            self._trace("add_ticket_note", {"ticket_id": ticket_id, "visibility": visibility, "body": body}, note)
            return note
        finally:
            conn.close()

    def update_ticket_priority(self, *, ticket_id: str, priority: str, note: str) -> dict[str, Any]:
        if priority not in {"low", "medium", "high", "urgent"}:
            raise ValueError("priority must be low, medium, high, or urgent")
        conn = _connect(self.db_path)
        try:
            old = _query_one(conn, "SELECT priority FROM ticket WHERE id = ?", [ticket_id])
            if not old:
                raise KeyError(f"Unknown ticket: {ticket_id}")
            conn.execute("UPDATE ticket SET priority = ?, updated_at = ? WHERE id = ?", [priority, _now(), ticket_id])
            _audit(conn, ticket_id, "priority_updated", "priority", old["priority"], priority, note)
            conn.commit()
            result = _ticket_detail(conn, ticket_id)
            self._trace("update_ticket_priority", {"ticket_id": ticket_id, "priority": priority, "note": note}, {"ticket_id": ticket_id, "priority": priority})
            return result
        finally:
            conn.close()

    def assign_ticket(self, *, ticket_id: str, queue: str, assignee: str, note: str) -> dict[str, Any]:
        conn = _connect(self.db_path)
        try:
            old = _query_one(conn, "SELECT queue, assignee FROM assignment WHERE ticket_id = ?", [ticket_id])
            if not old:
                raise KeyError(f"Unknown ticket: {ticket_id}")
            conn.execute("UPDATE assignment SET queue = ?, assignee = ? WHERE ticket_id = ?", [queue, assignee, ticket_id])
            _audit(conn, ticket_id, "assignment_updated", "assignment", f"{old['queue']}:{old['assignee']}", f"{queue}:{assignee}", note)
            conn.commit()
            result = _ticket_detail(conn, ticket_id)
            self._trace("assign_ticket", {"ticket_id": ticket_id, "queue": queue, "assignee": assignee, "note": note}, {"ticket_id": ticket_id, "queue": queue, "assignee": assignee})
            return result
        finally:
            conn.close()

    def resolve_ticket(self, *, ticket_id: str, resolution_note: str) -> dict[str, Any]:
        conn = _connect(self.db_path)
        try:
            old = _query_one(conn, "SELECT status FROM ticket WHERE id = ?", [ticket_id])
            if not old:
                raise KeyError(f"Unknown ticket: {ticket_id}")
            conn.execute("UPDATE ticket SET status = ?, updated_at = ? WHERE id = ?", ["resolved", _now(), ticket_id])
            conn.execute(
                "INSERT INTO ticket_note(ticket_id, visibility, body, created_at) VALUES (?, ?, ?, ?)",
                [ticket_id, "customer", resolution_note, _now()],
            )
            _audit(conn, ticket_id, "ticket_resolved", "status", old["status"], "resolved", resolution_note)
            conn.commit()
            result = _ticket_detail(conn, ticket_id)
            self._trace("resolve_ticket", {"ticket_id": ticket_id, "resolution_note": resolution_note}, {"ticket_id": ticket_id, "status": "resolved"})
            return result
        finally:
            conn.close()

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
            "db_path": str(self.db_path),
            "snapshot_hash": snapshot_hash(self.db_path),
            "created_at": _now(),
        }
        with self.trace_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True))
            handle.write("\n")


def verify_task_completion(
    task_id: str,
    initial_db_path: Path,
    final_db_path: Path,
    final_answer: Any = None,
    surface_trace_path: Path | None = None,
    expected_dependency_path: list[str] | None = None,
    trace_call_group: str | None = None,
) -> dict[str, Any]:
    initial = snapshot_state(initial_db_path)
    final = snapshot_state(final_db_path)
    checks: list[dict[str, Any]] = []

    def add(name: str, passed: bool, detail: Any) -> None:
        checks.append({"name": name, "passed": bool(passed), "detail": detail})

    expected_dependency_path = expected_dependency_path or _expected_dependency_path(task_id)
    add(
        "dependency_path_trace_matches",
        bool(surface_trace_path and expected_dependency_path and _trace_matches(surface_trace_path, task_id, expected_dependency_path, trace_call_group)),
        {
            "trace_path": str(surface_trace_path) if surface_trace_path else "",
            "expected_dependency_path": expected_dependency_path,
            "trace_call_group": trace_call_group or "",
        },
    )

    if task_id == "task-1":
        notes = [row for row in final["ticket_note"] if row["ticket_id"] == "T-100" and row["visibility"] == "internal"]
        add("target_internal_note_added", any("refund" in row["body"].lower() for row in notes), notes)
        add("audit_fields_match", _has_audit(final, "T-100", "note_added", field="ticket_note", new_value="internal"), final["audit_event"])
        add("non_target_records_unchanged", _non_target_unchanged(initial, final, target_ticket_ids={"T-100"}, allow_new_notes_for={"T-100"}), "non-target rows")
    elif task_id == "task-2":
        assignment = _assignment(final, "T-101")
        add("target_queue_changed", assignment["queue"] == "enterprise-support", assignment)
        add("target_assignee_changed", assignment["assignee"] == "iris", assignment)
        add("audit_fields_match", _has_audit(final, "T-101", "assignment_updated", field="assignment", new_value="enterprise-support:iris"), final["audit_event"])
        add("non_target_records_unchanged", _non_target_unchanged(initial, final, target_ticket_ids={"T-101"}), "non-target rows")
    elif task_id == "task-3":
        ticket = _ticket(final, "T-100")
        add("priority_is_high", ticket["priority"] == "high", ticket)
        add("audit_fields_match", _has_audit(final, "T-100", "priority_updated", field="priority", new_value="high"), final["audit_event"])
        add("non_target_records_unchanged", _non_target_unchanged(initial, final, target_ticket_ids={"T-100"}), "non-target rows")
    elif task_id == "task-4":
        expected = {"customer_id": "cust-vip", "open_ticket_count": 2, "highest_priority": "medium"}
        add("answer_matches", final_answer == expected, {"expected": expected, "actual": final_answer})
        add("state_unchanged", initial == final, "read-only task")
    elif task_id == "task-5":
        ticket = _ticket(final, "T-102")
        add("ticket_resolved", ticket["status"] == "resolved", ticket)
        notes = [row for row in final["ticket_note"] if row["ticket_id"] == "T-102" and row["visibility"] == "customer"]
        add("customer_resolution_note_added", any("resolved" in row["body"].lower() or "closed" in row["body"].lower() for row in notes), notes)
        add("audit_fields_match", _has_audit(final, "T-102", "ticket_resolved", field="status", new_value="resolved"), final["audit_event"])
        add("non_target_records_unchanged", _non_target_unchanged(initial, final, target_ticket_ids={"T-102"}, allow_new_notes_for={"T-102"}), "non-target rows")
    else:
        add("known_task", False, task_id)
    return {"task_id": task_id, "success": all(check["passed"] for check in checks), "checks": checks}


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _query(conn: sqlite3.Connection, sql: str, params: list[Any] | None = None) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(sql, params or []).fetchall()]


def _query_one(conn: sqlite3.Connection, sql: str, params: list[Any] | None = None) -> dict[str, Any] | None:
    row = conn.execute(sql, params or []).fetchone()
    return dict(row) if row else None


def _ensure_ticket(conn: sqlite3.Connection, ticket_id: str) -> None:
    if not _query_one(conn, "SELECT id FROM ticket WHERE id = ?", [ticket_id]):
        raise KeyError(f"Unknown ticket: {ticket_id}")


def _ticket_detail(conn: sqlite3.Connection, ticket_id: str) -> dict[str, Any]:
    ticket = _query_one(
        conn,
        """
        SELECT t.*, c.name AS customer_name, c.tier AS customer_tier, c.region, c.email,
               a.assignee, a.queue
        FROM ticket t
        JOIN customer c ON c.id = t.customer_id
        JOIN assignment a ON a.ticket_id = t.id
        WHERE t.id = ?
        """,
        [ticket_id],
    )
    if not ticket:
        raise KeyError(f"Unknown ticket: {ticket_id}")
    ticket["notes"] = _query(conn, "SELECT * FROM ticket_note WHERE ticket_id = ? ORDER BY id", [ticket_id])
    ticket["audit_events"] = _query(conn, "SELECT * FROM audit_event WHERE ticket_id = ? ORDER BY id", [ticket_id])
    return ticket


def _audit(conn: sqlite3.Connection, ticket_id: str, event_type: str, field: str, old: str, new: str, note: str) -> None:
    conn.execute(
        """
        INSERT INTO audit_event(ticket_id, event_type, field, old_value, new_value, note, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [ticket_id, event_type, field, old, new, note, _now()],
    )


def _now() -> str:
    return "2026-06-27T00:00:00Z"


def _ticket(snapshot: dict[str, list[dict[str, Any]]], ticket_id: str) -> dict[str, Any]:
    return next(row for row in snapshot["ticket"] if row["id"] == ticket_id)


def _assignment(snapshot: dict[str, list[dict[str, Any]]], ticket_id: str) -> dict[str, Any]:
    return next(row for row in snapshot["assignment"] if row["ticket_id"] == ticket_id)


def _has_audit(
    snapshot: dict[str, list[dict[str, Any]]],
    ticket_id: str,
    event_type: str,
    *,
    field: str | None = None,
    new_value: str | None = None,
) -> bool:
    return any(
        row["ticket_id"] == ticket_id
        and row["event_type"] == event_type
        and (field is None or row["field"] == field)
        and (new_value is None or row["new_value"] == new_value)
        for row in snapshot["audit_event"]
    )


def _non_target_unchanged(
    initial: dict[str, list[dict[str, Any]]],
    final: dict[str, list[dict[str, Any]]],
    *,
    target_ticket_ids: set[str],
    allow_new_notes_for: set[str] | None = None,
) -> bool:
    allow_new_notes_for = allow_new_notes_for or set()
    if initial["customer"] != final["customer"]:
        return False
    for ticket in initial["ticket"]:
        final_ticket = _ticket(final, ticket["id"])
        if ticket["id"] not in target_ticket_ids and ticket != final_ticket:
            return False
    for assignment in initial["assignment"]:
        final_assignment = _assignment(final, assignment["ticket_id"])
        if assignment["ticket_id"] not in target_ticket_ids and assignment != final_assignment:
            return False
    initial_notes_by_id = {row["id"]: row for row in initial["ticket_note"]}
    for note in final["ticket_note"]:
        if note["id"] in initial_notes_by_id:
            if note != initial_notes_by_id[note["id"]]:
                return False
        elif note["ticket_id"] not in allow_new_notes_for:
            return False
    for event in final["audit_event"]:
        if event["ticket_id"] not in target_ticket_ids:
            return False
    return True


def snapshot_hash(db_path: Path) -> str:
    encoded = json.dumps(snapshot_state(db_path), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _trace_matches(trace_path: Path, task_id: str, expected_dependency_path: list[str], trace_call_group: str | None = None) -> bool:
    if not trace_path.exists():
        return False
    calls: list[str] = []
    for line in trace_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        if record.get("task_id") != task_id:
            continue
        if trace_call_group and record.get("call_group") != trace_call_group:
            continue
        if "tool" in record:
            calls.append(record["tool"])
    return calls == expected_dependency_path


def _expected_dependency_path(task_id: str) -> list[str]:
    paths = {
        "task-1": ["search_tickets", "get_ticket", "add_ticket_note"],
        "task-2": ["search_tickets", "assign_ticket"],
        "task-3": ["search_tickets", "get_ticket", "update_ticket_priority"],
        "task-4": ["search_tickets"],
        "task-5": ["search_tickets", "get_ticket", "resolve_ticket"],
    }
    return paths.get(task_id, [])
