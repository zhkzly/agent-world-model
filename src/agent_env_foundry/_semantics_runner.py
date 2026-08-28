"""Private stdlib-only semantics child for a prepared release runtime."""

from __future__ import annotations

import importlib
import json
import os
import sys
from pathlib import Path
from typing import Any


def _load(reference: str) -> Any:
    module_name, _, attribute = reference.partition(":")
    return getattr(importlib.import_module(module_name), attribute)()


def _request(line: str) -> tuple[int, str, dict[str, Any]]:
    value = json.loads(line)
    if not isinstance(value, dict) or set(value) != {"seq", "op", "args"}:
        raise ValueError("request must contain exactly seq, op and args")
    seq, operation, arguments = value["seq"], value["op"], value["args"]
    if not isinstance(seq, int) or isinstance(seq, bool) or seq <= 0:
        raise ValueError("request seq must be a positive integer")
    if not isinstance(operation, str) or not isinstance(arguments, dict):
        raise ValueError("request op/args are invalid")
    return seq, operation, arguments


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: _semantics_runner.py module:factory")
    wire_fd = os.dup(sys.stdout.fileno())
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
    wire = os.fdopen(wire_fd, "w", encoding="utf-8", buffering=1)
    semantics = _load(sys.argv[1])
    for line in sys.stdin:
        seq = 0
        operation = ""
        try:
            seq, operation, arguments = _request(line)
            if operation == "start_cases":
                value = semantics.start_cases(arguments["seed"], arguments["limit"])
            elif operation == "inspect":
                value = semantics.inspect(Path(arguments["instance_directory"]))
            elif operation == "capabilities":
                value = semantics.capabilities()
            elif operation == "enumerate_bindings":
                value = semantics.enumerate_bindings(arguments["capability_id"], arguments["facts"])
            elif operation == "evaluate_atom":
                value = semantics.evaluate_atom(arguments["request"])
            elif operation == "evaluate_condition":
                value = semantics.evaluate_condition(arguments["request"])
            elif operation == "close":
                value = None
            else:
                raise ValueError(f"unknown semantics operation {operation!r}")
            response = {"seq": seq, "ok": True, "value": value}
        except Exception as exc:
            response = {
                "seq": seq,
                "ok": False,
                "error": {"type": type(exc).__name__, "message": str(exc)},
            }
        wire.write(json.dumps(response, ensure_ascii=False, sort_keys=True) + "\n")
        wire.flush()
        if operation == "close":
            return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
