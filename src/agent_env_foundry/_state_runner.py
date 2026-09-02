"""Private stdlib-only protected state reader child."""

from __future__ import annotations

import importlib
import json
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast


def _load(reference: str) -> Callable[[Path], Any]:
    module_name, _, attribute = reference.partition(":")
    reader = getattr(importlib.import_module(module_name), attribute)
    if not callable(reader):
        raise TypeError("state reader entrypoint must be callable")
    return cast(Callable[[Path], Any], reader)


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


def _dispatch(
    reader: Callable[[Path], Any],
    operation: str,
    arguments: dict[str, Any],
) -> Any:
    if operation == "read":
        return reader(Path(arguments["instance_directory"]))
    if operation == "close":
        return None
    raise ValueError(f"unknown state operation {operation!r}")


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: _state_runner.py module:reader")
    wire_fd = os.dup(sys.stdout.fileno())
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
    wire = os.fdopen(wire_fd, "w", encoding="utf-8", buffering=1)
    reader = _load(sys.argv[1])
    for line in sys.stdin:
        seq = 0
        operation = ""
        try:
            seq, operation, arguments = _request(line)
            value = _dispatch(reader, operation, arguments)
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
