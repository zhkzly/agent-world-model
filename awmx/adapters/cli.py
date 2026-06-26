from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any

from awmx.artifacts.schemas import ValidationError
from awmx.harness.permissions import PermissionGate


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _append_jsonl(path: Path | None, event: str, payload: dict[str, Any]) -> None:
    if path is None:
        return
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "event": event,
                    "timestamp": _utc_now(),
                    "payload": payload,
                },
                ensure_ascii=True,
                sort_keys=True,
            )
        )
        handle.write("\n")


def _decode_output(value: bytes) -> str:
    return value.decode("utf-8", errors="replace")


def _summary(value: bytes, limit: int) -> str:
    decoded = _decode_output(value)
    if len(decoded) <= limit:
        return decoded
    return decoded[:limit] + "...[truncated]"


@dataclass
class CliCommandSpec:
    command: list[str] | tuple[str, ...] | str
    cwd: Path | str | None
    timeout_s: float
    env: dict[str, str] = field(default_factory=dict)
    read_paths: list[Path | str] = field(default_factory=list)
    write_paths: list[Path | str] = field(default_factory=list)


@dataclass
class CliCommandResult:
    command: list[str]
    cwd: str
    env: dict[str, str]
    exit_code: int | None
    duration_ms: int
    stdout_path: str
    stderr_path: str
    stdout_summary: str
    stderr_summary: str
    timed_out: bool
    failure_reason: str | None = None

    def to_observation(self) -> dict[str, Any]:
        return {
            "exit_code": self.exit_code,
            "duration_ms": self.duration_ms,
            "stdout_path": self.stdout_path,
            "stderr_path": self.stderr_path,
            "stdout_summary": self.stdout_summary,
            "stderr_summary": self.stderr_summary,
            "timed_out": self.timed_out,
            "failure_reason": self.failure_reason,
        }

    def to_evidence(self) -> dict[str, Any]:
        return {
            "command_audit": {
                "command": self.command,
                "cwd": self.cwd,
                "env": self.env,
                "exit_code": self.exit_code,
                "duration_ms": self.duration_ms,
                "stdout_path": self.stdout_path,
                "stderr_path": self.stderr_path,
                "stdout_summary": self.stdout_summary,
                "stderr_summary": self.stderr_summary,
                "timed_out": self.timed_out,
                "failure_reason": self.failure_reason,
            }
        }


class CliAdapter:
    def __init__(
        self,
        *,
        allowed_commands: set[str],
        permission_gate: PermissionGate,
        logs_dir: Path | str,
        events_path: Path | str | None = None,
        allowed_env_keys: set[str] | None = None,
        base_env: dict[str, str] | None = None,
        stdout_limit: int = 2000,
        stderr_limit: int = 2000,
    ) -> None:
        self.allowed_commands = set(allowed_commands)
        self.permission_gate = permission_gate
        self.logs_dir = Path(logs_dir)
        self.events_path = Path(events_path) if events_path is not None else None
        self.allowed_env_keys = set(allowed_env_keys or set())
        self.base_env = dict(base_env or {})
        self.stdout_limit = stdout_limit
        self.stderr_limit = stderr_limit
        self._sequence = 0

    def run(self, spec: CliCommandSpec) -> CliCommandResult:
        command = self._validate_command(spec.command)
        self._validate_allowlist(command)
        env = self._build_env(spec.env)
        timeout_s = self._validate_timeout(spec.timeout_s)

        action = {
            "kind": "command",
            "command": command,
            "cwd": str(spec.cwd) if spec.cwd is not None else None,
            "read_paths": [str(path) for path in spec.read_paths],
            "write_paths": [str(path) for path in spec.write_paths],
        }
        permission = self.permission_gate.decide(action)
        if not permission["allowed"]:
            self._record_rejection(action=action, permission=permission, reason=permission["reason"])
            raise ValidationError(permission["reason"])

        cwd = permission["cwd"]
        self._validate_logs_dir(action)
        stdout_path, stderr_path = self._next_log_paths()
        payload = {
            "command": command,
            "cwd": cwd,
            "env": env,
            "timeout_s": timeout_s,
            "stdout_path": str(stdout_path),
            "stderr_path": str(stderr_path),
        }
        _append_jsonl(self.events_path, "cli_command_started", payload)

        start = perf_counter()
        try:
            completed = subprocess.run(
                command,
                cwd=cwd,
                env=env,
                capture_output=True,
                timeout=timeout_s,
                check=False,
                shell=False,
            )
            duration_ms = int((perf_counter() - start) * 1000)
            stdout = self._coerce_output(completed.stdout)
            stderr = self._coerce_output(completed.stderr)
            exit_code = completed.returncode
            timed_out = False
            failure_reason = None if exit_code == 0 else "exit_code"
            exception: dict[str, str] | None = None
        except subprocess.TimeoutExpired as exc:
            duration_ms = int((perf_counter() - start) * 1000)
            stdout = self._coerce_output(exc.stdout)
            stderr = self._coerce_output(exc.stderr)
            exit_code = None
            timed_out = True
            failure_reason = "timeout"
            exception = None
        except OSError as exc:
            duration_ms = int((perf_counter() - start) * 1000)
            stdout = b""
            stderr = str(exc).encode("utf-8", errors="replace")
            exit_code = None
            timed_out = False
            failure_reason = "exec_error"
            exception = {
                "type": type(exc).__name__,
                "message": str(exc),
            }

        stdout_path.write_bytes(stdout)
        stderr_path.write_bytes(stderr)

        result = CliCommandResult(
            command=command,
            cwd=cwd,
            env=env,
            exit_code=exit_code,
            duration_ms=duration_ms,
            stdout_path=str(stdout_path),
            stderr_path=str(stderr_path),
            stdout_summary=_summary(stdout, self.stdout_limit),
            stderr_summary=_summary(stderr, self.stderr_limit),
            timed_out=timed_out,
            failure_reason=failure_reason,
        )

        event_name = "cli_command_failed" if failure_reason else "cli_command_completed"
        _append_jsonl(
            self.events_path,
            event_name,
            {
                **payload,
                "exit_code": exit_code,
                "duration_ms": duration_ms,
                "stdout_summary": result.stdout_summary,
                "stderr_summary": result.stderr_summary,
                "timed_out": timed_out,
                "reason": failure_reason,
                "exception": exception,
            },
        )
        return result

    def _validate_command(self, command: list[str] | tuple[str, ...] | str) -> list[str]:
        if isinstance(command, str):
            self._record_rejection(action={"kind": "command", "command": command}, reason="command must be a list")
            raise ValidationError("command must be a list of argv strings; shell strings are not allowed")
        if not isinstance(command, list | tuple) or not command:
            self._record_rejection(action={"kind": "command", "command": command}, reason="command must be a list")
            raise ValidationError("command must be a list of argv strings")
        if not all(isinstance(item, str) and item for item in command):
            self._record_rejection(action={"kind": "command", "command": command}, reason="command contains invalid argv")
            raise ValidationError("command must contain only non-empty strings")
        return list(command)

    def _validate_allowlist(self, command: list[str]) -> None:
        executable = command[0]
        if executable not in self.allowed_commands:
            self._record_rejection(
                action={"kind": "command", "command": command},
                reason=f"command is not allowlisted: {executable}",
            )
            raise ValidationError(f"command is not allowlisted: {executable}")

    def _build_env(self, requested_env: dict[str, str]) -> dict[str, str]:
        if not isinstance(requested_env, dict):
            self._record_rejection(action={"kind": "command"}, reason="env must be a mapping")
            raise ValidationError("env must be a mapping")
        for key, value in requested_env.items():
            if key not in self.allowed_env_keys:
                self._record_rejection(action={"kind": "command"}, reason=f"env key is not allowed: {key}")
                raise ValidationError(f"env key is not allowed: {key}")
            if not isinstance(value, str):
                self._record_rejection(action={"kind": "command"}, reason=f"env value must be a string: {key}")
                raise ValidationError(f"env value must be a string: {key}")
        env = dict(self.base_env)
        env.update(requested_env)
        return env

    def _validate_timeout(self, timeout_s: float) -> float:
        if isinstance(timeout_s, bool) or not isinstance(timeout_s, int | float) or timeout_s <= 0:
            self._record_rejection(action={"kind": "command"}, reason="timeout_s must be positive")
            raise ValidationError("timeout_s must be a positive number")
        return float(timeout_s)

    def _next_log_paths(self) -> tuple[Path, Path]:
        self._sequence += 1
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        return (
            self.logs_dir / f"cli-{self._sequence:04d}.stdout",
            self.logs_dir / f"cli-{self._sequence:04d}.stderr",
        )

    def _validate_logs_dir(self, action: dict[str, Any]) -> None:
        try:
            logs_dir = self.logs_dir.resolve()
        except (TypeError, ValueError, OSError) as exc:
            self._record_rejection(action=action, reason=f"logs_dir must be a valid path: {exc}")
            raise ValidationError("logs_dir must be a valid path") from exc

        if not self.permission_gate.writable_roots:
            self._record_rejection(action=action, reason=f"logs_dir requires a writable root: {logs_dir}")
            raise ValidationError(f"logs_dir requires a writable root: {logs_dir}")
        if not any(self._is_within(logs_dir, root) for root in self.permission_gate.writable_roots):
            self._record_rejection(action=action, reason=f"logs_dir is outside writable roots: {logs_dir}")
            raise ValidationError(f"logs_dir is outside writable roots: {logs_dir}")

    @staticmethod
    def _is_within(path: Path, root: Path) -> bool:
        try:
            path.relative_to(root)
            return True
        except ValueError:
            return False

    def _record_rejection(
        self,
        *,
        action: dict[str, Any],
        reason: str,
        permission: dict[str, Any] | None = None,
    ) -> None:
        payload = {
            "action": action,
            "reason": reason,
        }
        if permission is not None:
            payload["permission"] = permission
        _append_jsonl(self.events_path, "cli_command_rejected", payload)

    @staticmethod
    def _coerce_output(value: Any) -> bytes:
        if value is None:
            return b""
        if isinstance(value, bytes):
            return value
        return str(value).encode("utf-8", errors="replace")
