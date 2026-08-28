"""Private stdlib-only actor child for a prepared release runtime."""

from __future__ import annotations

import importlib
import json
import os
import sys
from pathlib import Path
from typing import Any


def _load(reference: str, instance: Path) -> Any:
    module_name, _, attribute = reference.partition(":")
    factory = getattr(importlib.import_module(module_name), attribute)
    return factory(instance)


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
    if len(sys.argv) != 3:
        raise SystemExit("usage: _actor_runner.py module:factory INSTANCE")
    wire_fd = os.dup(sys.stdout.fileno())
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
    wire = os.fdopen(wire_fd, "w", encoding="utf-8", buffering=1)
    environment = _load(sys.argv[1], Path(sys.argv[2]))
    closed = False
    for line in sys.stdin:
        seq = 0
        try:
            seq, operation, arguments = _request(line)
            if operation == "reset":
                value = environment.reset(arguments.get("start"))
            elif operation == "tools":
                value = list(environment.tools())
            elif operation == "invoke":
                value = environment.invoke(arguments["tool_name"], arguments["arguments"])
            elif operation == "close":
                environment.close()
                closed = True
                value = None
            else:
                raise ValueError(f"unknown actor operation {operation!r}")
            response = {"seq": seq, "ok": True, "value": value}
        except Exception as exc:
            response = {
                "seq": seq,
                "ok": False,
                "error": {"type": type(exc).__name__, "message": str(exc)},
            }
        wire.write(json.dumps(response, ensure_ascii=False, sort_keys=True) + "\n")
        wire.flush()
        if closed:
            return 0
    if not closed:
        try:
            environment.close()
        except Exception:
            return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
