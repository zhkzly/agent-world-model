"""Stdlib-only Candidate child for one Qualification environment handle.

The Qualifier-authored public probe never imports Candidate code.  This child
owns only the raw Candidate import and calls.  The Host process owns canonical
contract validation and exposes the four transport-neutral Environment
operations over a private JSON-lines pipe.
"""

from __future__ import annotations

import importlib
import json
import os
import sys
from pathlib import Path
from typing import Any


def _write(wire: Any, value: dict[str, Any]) -> None:
    wire.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")
    wire.flush()


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
    if len(sys.argv) != 5:
        raise SystemExit(
            "usage: _qualification_actor_runner.py FACTORY SOURCE_ROOT INSTANCE DEPENDENCIES"
        )
    factory_reference = sys.argv[1]
    source_root = Path(sys.argv[2]).resolve()
    instance = Path(sys.argv[3]).resolve()
    dependencies = Path(sys.argv[4]).resolve()

    # Preserve one private response stream before Candidate code can print.
    wire_fd = os.dup(sys.stdout.fileno())
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
    wire = os.fdopen(wire_fd, "w", encoding="utf-8", buffering=1)

    sys.path[:0] = [str(source_root), str(dependencies)]
    try:
        module_name, separator, attribute = factory_reference.partition(":")
        if not separator or not module_name or not attribute:
            raise ValueError("factory reference must be module:attribute")
        factory = getattr(importlib.import_module(module_name), attribute)
        environment = factory(instance)
        for method in ("reset", "tools", "invoke", "close"):
            if not callable(getattr(environment, method, None)):
                raise TypeError(f"Candidate environment is missing {method}()")
    except Exception as exc:
        _write(
            wire,
            {
                "type": "ready",
                "ok": False,
                "error": {
                    "owner": "candidate",
                    "type": type(exc).__name__,
                    "message": str(exc),
                },
            },
        )
        return 20

    _write(wire, {"type": "ready", "ok": True})
    closed = False
    for line in sys.stdin:
        seq = 0
        try:
            seq, operation, arguments = _request(line)
            value: Any
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
                raise ValueError(f"unknown environment operation {operation!r}")
            _write(wire, {"seq": seq, "ok": True, "value": value})
        except Exception as exc:
            _write(
                wire,
                {
                    "seq": seq,
                    "ok": False,
                    "error": {
                        "owner": "candidate",
                        "type": type(exc).__name__,
                        "message": str(exc),
                    },
                },
            )
        if closed:
            return 0
    if not closed:
        try:
            environment.close()
        except Exception:
            return 20
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
