"""Bounded, secret-safe Runtime subprocess facts for observability.

This module only normalizes diagnostic facts.  It owns neither retry policy nor
any workflow state transition, so emitting a scene can never become a new
control authority.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace

from agent_world.invocation.redaction import Redactor

MAX_STDERR_TAIL_BYTES = 16 * 1024


@dataclass(frozen=True, slots=True)
class RuntimeSubprocessScene:
    """One bounded Runtime crash scene, safe for Tier B persistence."""

    operation: str
    exit_code: int | None
    stderr_tail: str
    stderr_truncated: bool
    launch_argv: tuple[str, ...]
    text_redacted: bool

    def evidence_fields(self) -> dict[str, object]:
        """Return the exact bounded fields retained with Judge evidence."""

        return {
            "exit_code": self.exit_code,
            "stderr": self.stderr_tail,
            "stderr_truncated": self.stderr_truncated,
            "launch_argv": list(self.launch_argv),
            "subprocess_operation": self.operation,
            "subprocess_text_redacted": self.text_redacted,
        }

    def telemetry_payload(self) -> dict[str, str | int | bool | None]:
        """Flatten the scene for TelemetryStore's scalar-only event payload."""

        return {
            "operation": self.operation,
            "failure_class": "RuntimeProcessCrashed",
            "exit_code": self.exit_code,
            "stderr_tail": self.stderr_tail,
            "stderr_truncated": self.stderr_truncated,
            "launch_argv_json": json.dumps(
                self.launch_argv,
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            "text_redacted": self.text_redacted,
        }


def runtime_subprocess_scene(
    *,
    operation: str,
    exit_code: object,
    stderr: object,
    launch_argv: Sequence[str],
    known_secret_canaries: Sequence[str | bytes] = (),
) -> RuntimeSubprocessScene:
    """Normalize one Runtime crash without retaining more than a stderr tail."""

    canaries = _known_canary_bytes(known_secret_canaries)
    safe_operation, operation_redacted = _safe_text(operation, canaries)
    raw_stderr = stderr if isinstance(stderr, str) else ""
    stderr_bytes = raw_stderr.encode("utf-8", errors="replace")
    stderr_truncated = len(stderr_bytes) > MAX_STDERR_TAIL_BYTES
    stderr_tail = stderr_bytes[-MAX_STDERR_TAIL_BYTES:].decode("utf-8", errors="replace")
    safe_stderr, stderr_redacted = _safe_text(stderr_tail, canaries)

    safe_argv: list[str] = []
    argv_redacted = False
    for argument in launch_argv:
        safe_argument, redacted = _safe_text(argument, canaries)
        safe_argv.append(safe_argument)
        argv_redacted = argv_redacted or redacted

    normalized_exit_code = (
        exit_code if isinstance(exit_code, int) and not isinstance(exit_code, bool) else None
    )
    return RuntimeSubprocessScene(
        operation=safe_operation,
        exit_code=normalized_exit_code,
        stderr_tail=safe_stderr,
        stderr_truncated=stderr_truncated,
        launch_argv=tuple(safe_argv),
        text_redacted=operation_redacted or stderr_redacted or argv_redacted,
    )


def runtime_subprocess_scene_from_payload(
    payload: Mapping[str, object],
    *,
    known_secret_canaries: Sequence[str | bytes] = (),
) -> RuntimeSubprocessScene | None:
    """Re-screen a scalar Tier B event before returning it to an agent."""

    raw_operation = payload.get("operation")
    raw_argv = payload.get("launch_argv_json")
    if not isinstance(raw_operation, str) or not isinstance(raw_argv, str):
        return None
    try:
        decoded_argv = json.loads(raw_argv)
    except (TypeError, ValueError):
        return None
    if not isinstance(decoded_argv, list) or not all(
        isinstance(item, str) for item in decoded_argv
    ):
        return None
    scene = runtime_subprocess_scene(
        operation=raw_operation,
        exit_code=payload.get("exit_code"),
        stderr=payload.get("stderr_tail"),
        launch_argv=tuple(decoded_argv),
        known_secret_canaries=known_secret_canaries,
    )
    if payload.get("stderr_truncated") is True:
        scene = replace(scene, stderr_truncated=True)
    return scene


def safe_dynamic_text(
    value: str,
    *,
    known_secret_canaries: Sequence[str | bytes] = (),
) -> str:
    """Return text only when it is safe to persist; otherwise return a hash."""

    return _safe_text(value, _known_canary_bytes(known_secret_canaries))[0]


def _safe_text(value: str, canaries: tuple[bytes, ...]) -> tuple[str, bool]:
    encoded = value.encode("utf-8", errors="replace")
    if any(canary in encoded for canary in canaries):
        return _digest_text(value), True

    canary_text = tuple(canary.decode("utf-8") for canary in canaries if _is_utf8(canary))
    if Redactor.from_values(canary_text).text(value) != value:
        return _digest_text(value), True
    if Redactor().text(value) != value:
        return _digest_text(value), True
    return value, False


def _known_canary_bytes(values: Sequence[str | bytes]) -> tuple[bytes, ...]:
    normalised: set[bytes] = set()
    for value in values:
        encoded = value.encode("utf-8") if isinstance(value, str) else value
        if isinstance(encoded, bytes) and 4 <= len(encoded) <= 8192:
            normalised.add(encoded)
    return tuple(sorted(normalised))


def _is_utf8(value: bytes) -> bool:
    try:
        value.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def _digest_text(value: str) -> str:
    return f"sha256:{hashlib.sha256(value.encode('utf-8', errors='replace')).hexdigest()}"
