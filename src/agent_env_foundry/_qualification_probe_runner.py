"""Stdlib-only process for one Qualifier-authored public probe.

The probe receives no release or instance path.  Its only authority is the
remote ``session.open`` / ``reset`` / ``tools`` / ``invoke`` / ``close``
surface provided by the Host coordinator over JSON lines.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any


class _RemoteEnvironment:
    def __init__(self, client: _Client, handle: int) -> None:
        self._client = client
        self._handle = handle
        self._closed = False

    def reset(self, start: Any = None) -> Any:
        self._require_open()
        return self._client.call("reset", handle=self._handle, arguments={"start": start})

    def tools(self) -> tuple[Any, ...]:
        self._require_open()
        value = self._client.call("tools", handle=self._handle, arguments={})
        if not isinstance(value, list):
            raise RuntimeError("Host returned a non-array tool catalog")
        return tuple(value)

    def invoke(self, tool_name: Any, arguments: Any) -> Any:
        self._require_open()
        return self._client.call(
            "invoke",
            handle=self._handle,
            arguments={"tool_name": tool_name, "arguments": arguments},
        )

    def close(self) -> None:
        self._require_open()
        self._client.call("close", handle=self._handle, arguments={})
        self._closed = True

    def _require_open(self) -> None:
        if self._closed:
            raise RuntimeError("closed environment handle cannot be reused")


class _ProbeSession:
    def __init__(self, client: _Client) -> None:
        self._client = client

    def open(self, instance_key: str) -> _RemoteEnvironment:
        handle = self._client.call("open", instance=instance_key, arguments={})
        if not isinstance(handle, int) or isinstance(handle, bool) or handle <= 0:
            raise RuntimeError("Host returned an invalid environment handle")
        return _RemoteEnvironment(self._client, handle)


class _Client:
    def __init__(self, wire: Any) -> None:
        self._wire = wire
        self._next_seq = 1

    def call(
        self,
        operation: str,
        *,
        arguments: dict[str, Any],
        instance: str | None = None,
        handle: int | None = None,
    ) -> Any:
        seq = self._next_seq
        self._next_seq += 1
        self._wire.write(
            json.dumps(
                {
                    "type": "call",
                    "seq": seq,
                    "operation": operation,
                    "instance": instance,
                    "handle": handle,
                    "arguments": arguments,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
            + "\n"
        )
        self._wire.flush()
        line = sys.stdin.readline()
        if not line:
            raise RuntimeError("Host coordinator closed the private probe transport")
        response = json.loads(line)
        if (
            not isinstance(response, dict)
            or response.get("type") != "result"
            or response.get("seq") != seq
            or response.get("ok") is not True
            or set(response) != {"type", "seq", "ok", "value"}
        ):
            raise RuntimeError("Host coordinator returned an invalid probe result")
        return response["value"]


def _write(wire: Any, value: dict[str, Any]) -> None:
    wire.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")
    wire.flush()


def main() -> int:
    wire_fd = os.dup(sys.stdout.fileno())
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
    wire = os.fdopen(wire_fd, "w", encoding="utf-8", buffering=1)
    try:
        invocation = json.loads(sys.stdin.readline())
        if not isinstance(invocation, dict) or set(invocation) != {"source", "mode"}:
            raise ValueError("probe invocation has invalid members")
        source, mode = invocation["source"], invocation["mode"]
        if not isinstance(source, str) or not source or not isinstance(mode, str) or not mode:
            raise ValueError("probe invocation values must be non-empty strings")
        namespace: dict[str, Any] = {
            "__name__": "qualification_public_probe",
            "__file__": "<qualification-public-probe>",
        }
        exec(compile(source, "<qualification-public-probe>", "exec"), namespace)
        entry = namespace.get("run")
        if not callable(entry):
            raise TypeError("public_probe.py must define run(session, mode)")
        entry(_ProbeSession(_Client(wire)), mode)
    except Exception as exc:
        _write(
            wire,
            {
                "type": "done",
                "ok": False,
                "error": {"type": type(exc).__name__, "message": str(exc)},
            },
        )
        return 21
    _write(wire, {"type": "done", "ok": True})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
