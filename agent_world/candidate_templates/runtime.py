#!/usr/bin/env python3
"""Candidate Runtime — framework-provided protocol scaffold.

The protocol loop (main) below is correct: DO NOT modify it. Fill the TODO
sections in do_reset, do_invoke, do_snapshot, and do_close with your
environment's actual logic. Use only the Python standard library.
"""
import json
import sys

OPERATIONS = ("handshake", "reset", "invoke", "snapshot", "close")

# ---------------------------------------------------------------------------
# State — TODO: declare your world state variables here.
# ---------------------------------------------------------------------------
_state: dict = {}


# ---------------------------------------------------------------------------
# Protocol loop — DO NOT MODIFY.
# ---------------------------------------------------------------------------
def main() -> None:
    for line in sys.stdin:
        request = json.loads(line)
        op = request.get("op")
        if op == "handshake":
            response = {"operations": list(OPERATIONS)}
        elif op == "reset":
            response = do_reset(request)
        elif op == "invoke":
            response = do_invoke(request)
        elif op == "snapshot":
            response = do_snapshot()
        elif op == "close":
            response = do_close()
        else:
            response = {"status": "error", "error": f"unknown op: {op}"}
        sys.stdout.write(json.dumps(response) + "\n")
        sys.stdout.flush()


# ---------------------------------------------------------------------------
# Operations — TODO: implement these with your environment's logic.
# ---------------------------------------------------------------------------

def do_reset(request: dict) -> dict:
    """Initialize from seed, actor, and initial_config.

    request = {"op": "reset", "seed": int, "task_type": str, "actor": str,
               "difficulty": {...}, "initial_config": {...}}
    Store seed, actor, initial_config in _state.
    Set up default tool result values for snapshot.
    Return {"status": "ok"}.
    """
    # TODO: implement state initialization.
    return {"status": "ok"}


def do_invoke(request: dict) -> dict:
    """Execute a tool transition.

    request = {"op": "invoke", "tool_id": str, "arguments": {...},
               "idempotency_key": str}
    Dispatch to the correct tool, update _state, return the tool's result.
    Return {"status": "ok", "result": <tool-specific result>}.
    """
    # TODO: implement tool dispatch + state transitions.
    return {"status": "ok", "result": {}}


def do_snapshot() -> dict:
    """Return full program state (framework-private).

    MUST return {"state": {"tools": {tool_name: {result_field: value}}}}
    where tool_name is the NAME of each declared tool (e.g. "register_member",
    "lookup_member" — read them from inputs/design.json's tools[].name), NOT the
    tool's numeric index (NOT "1" or "2"). result_field is each field name in
    that tool's result_fields. Each value must match its declared category.
    """
    # TODO: return the current state with every tool name and result_field.
    # Example for two tools named register_member + lookup_member:
    #   return {"state": {"tools": {
    #       "register_member": {"member_id": "", "status": ""},
    #       "lookup_member": {"member_id": "", "found": False},
    #   }}}
    return {"state": {"tools": {}}}


def do_close() -> dict:
    """Release episode resources."""
    # TODO: cleanup if needed.
    return {"status": "ok"}


if __name__ == "__main__":
    main()
