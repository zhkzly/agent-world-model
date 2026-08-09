"""Framework-owned harness for an untrusted candidate JSONL runtime."""

from __future__ import annotations

import json
import math
import select
import subprocess
import sys
from pathlib import Path
from typing import Any

from agent_world.contracts import PublicStep

_OPERATIONS = ("handshake", "reset", "invoke", "close")
_CALL_TIMEOUT_SECONDS = 20
_STOP_TIMEOUT_SECONDS = 5


class CandidateRuntimeError(RuntimeError):
    """A safe protocol/process failure; never includes candidate output."""


def _object(line: str, code: str) -> dict[str, Any]:
    try:
        value = json.loads(line)
    except json.JSONDecodeError as exc:
        raise CandidateRuntimeError(code) from exc
    if not isinstance(value, dict):
        raise CandidateRuntimeError(code)
    return value


class CandidateProcess:
    """A candidate is only ever executed in a child process, never imported."""

    def __init__(self, candidate_root: Path, entrypoint: str = "runtime.py") -> None:
        self.candidate_root = candidate_root
        self.entrypoint = entrypoint
        self.process: subprocess.Popen[str] | None = None
        self.closed = False

    def __enter__(self) -> CandidateProcess:
        path = self.candidate_root / self.entrypoint
        if not path.is_file():
            raise CandidateRuntimeError("candidate_entrypoint_missing")
        try:
            self.process = subprocess.Popen(  # noqa: S603 - deliberately launches untrusted candidate
                [sys.executable, str(path)],
                cwd=self.candidate_root,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
            )
        except OSError as exc:
            raise CandidateRuntimeError("candidate_launch_failed") from exc
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def call(self, payload: dict[str, Any]) -> dict[str, Any]:
        process = self.process
        if process is None or process.stdin is None or process.stdout is None:
            raise CandidateRuntimeError("candidate_not_running")
        if process.poll() is not None:
            raise CandidateRuntimeError("candidate_exited_early")
        try:
            process.stdin.write(json.dumps(payload, separators=(",", ":")) + "\n")
            process.stdin.flush()
        except OSError as exc:
            raise CandidateRuntimeError("candidate_stdin_failed") from exc
        ready, _, _ = select.select([process.stdout], [], [], _CALL_TIMEOUT_SECONDS)
        if not ready:
            raise CandidateRuntimeError("candidate_protocol_timeout")
        line = process.stdout.readline()
        if not line:
            raise CandidateRuntimeError("candidate_stdout_closed")
        return _object(line, "candidate_protocol_invalid_json")

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        process = self.process
        if process is None:
            return
        if process.poll() is None:
            try:
                response = self.call({"op": "close"})
                if response.get("status") != "ok":
                    raise CandidateRuntimeError("candidate_close_rejected")
            except CandidateRuntimeError:
                process.terminate()
        try:
            code = process.wait(timeout=_STOP_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=_STOP_TIMEOUT_SECONDS)
            raise CandidateRuntimeError("candidate_teardown_timeout") from None
        if code != 0:
            raise CandidateRuntimeError("candidate_teardown_failed")


def _require_ok(response: dict[str, Any], code: str) -> None:
    if response.get("status") != "ok":
        raise CandidateRuntimeError(code)


def _require_protocol(response: dict[str, Any]) -> None:
    operations = response.get("operations")
    if not isinstance(operations, list) or tuple(operations) != _OPERATIONS:
        raise CandidateRuntimeError("candidate_protocol_mismatch")


def _materialize(candidate_root: Path) -> None:
    with CandidateProcess(candidate_root) as runtime:
        _require_ok(runtime.call({"op": "reset"}), "candidate_reset_rejected")


def _protocol(candidate_root: Path) -> None:
    with CandidateProcess(candidate_root) as runtime:
        _require_protocol(runtime.call({"op": "handshake"}))


def _property(candidate_root: Path, step: PublicStep) -> None:
    with CandidateProcess(candidate_root) as runtime:
        _require_ok(runtime.call({"op": "reset"}), "candidate_reset_rejected")
        response = runtime.call({"op": "invoke", "tool": step.tool, "arguments": step.arguments})
        _require_ok(response, "candidate_invoke_rejected")
        result = response.get("result")
        if not isinstance(result, dict) or not step.expected_result:
            raise CandidateRuntimeError("candidate_property_mismatch")
        for field, expected in step.expected_result.items():
            if field not in result:
                raise CandidateRuntimeError("candidate_property_mismatch")
            actual = result[field]
            if (
                type(actual) is not type(expected)
                or type(expected) not in (type(None), bool, int, float, str)
                or (
                    type(expected) is float
                    and (not math.isfinite(expected) or not math.isfinite(actual))
                )
                or actual != expected
            ):
                raise CandidateRuntimeError("candidate_property_mismatch")


def _restart_teardown(candidate_root: Path) -> None:
    for _ in range(2):
        with CandidateProcess(candidate_root) as runtime:
            _require_protocol(runtime.call({"op": "handshake"}))
            _require_ok(runtime.call({"op": "reset"}), "candidate_reset_rejected")


def _gate(gate_id: str, check: object) -> dict[str, str]:
    try:
        if not callable(check):  # pragma: no cover - internal misuse guard
            raise CandidateRuntimeError("judge_internal_error")
        check()
    except CandidateRuntimeError as exc:
        return {"gate_id": gate_id, "status": "failed", "code": str(exc)}
    return {"gate_id": gate_id, "status": "passed", "code": "ok"}


def integrate(candidate_root: Path, step: PublicStep) -> dict[str, str]:
    """Builder-owned public smoke. Judge repeats its checks independently."""

    try:
        _protocol(candidate_root)
        _property(candidate_root, step)
    except CandidateRuntimeError as exc:
        return {"status": "failed", "code": str(exc)}
    return {"status": "passed", "code": "ok"}


def judge(candidate_root: Path, step: PublicStep) -> tuple[dict[str, str], ...]:
    """Run every required hard gate in fresh candidate processes."""

    return (
        _gate("task_materialization", lambda: _materialize(candidate_root)),
        _gate("protocol", lambda: _protocol(candidate_root)),
        _gate("core_property", lambda: _property(candidate_root, step)),
        _gate("restart_teardown", lambda: _restart_teardown(candidate_root)),
    )
