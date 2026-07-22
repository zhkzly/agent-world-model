"""Private one-request worker for :class:`CodexSdkBackend`.

The worker is intentionally a fixed Python entry point, not a generic process
runner.  It imports the real ``openai_codex.AsyncCodex`` SDK only in this child
process and speaks a small NDJSON protocol with the trusted parent.
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib.metadata
import json
import os
import re
import sys
import time
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    # Allow a source checkout to run this fixed file without leaking PYTHONPATH
    # into the Codex/app-server environment.
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent_world.invocation.redaction import Redactor  # noqa: E402

PROTOCOL_VERSION = "agent-world.codex-worker.v1"
SUPPORTED_SDK_VERSION = "0.144.4"
SUPPORTED_RUNTIME_VERSION = "0.144.4"
_ENVIRONMENT_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_RESULT_RESERVE_BYTES = 64 * 1024


class ProtocolBudgetExceeded(RuntimeError):
    pass


class Emitter:
    def __init__(
        self,
        *,
        redactor: Redactor,
        max_events: int,
        max_protocol_bytes: int,
    ) -> None:
        self.redactor = redactor
        self.max_events = max_events
        self.max_protocol_bytes = max_protocol_bytes
        self.event_count = 0
        self.protocol_bytes = 0

    def event(self, method: str, payload: Mapping[str, Any]) -> None:
        if self.event_count >= self.max_events:
            raise ProtocolBudgetExceeded("SDK event count exceeded the resolved profile limit")
        record = {
            "type": "event",
            "protocol_version": PROTOCOL_VERSION,
            "event": {
                "sequence": self.event_count,
                "method": method,
                "payload": self.redactor.object(payload),
            },
        }
        encoded = _encode_record(record)
        event_budget = self.max_protocol_bytes - _RESULT_RESERVE_BYTES
        if self.protocol_bytes + len(encoded) > event_budget:
            raise ProtocolBudgetExceeded("SDK event bytes exceeded the resolved profile limit")
        self.event_count += 1
        self.protocol_bytes += len(encoded)
        _write_encoded(encoded)

    def result(self, payload: Mapping[str, Any]) -> None:
        record = {
            "type": "result",
            "protocol_version": PROTOCOL_VERSION,
            "result": self.redactor.object(payload),
        }
        encoded = _encode_record(record)
        if self.protocol_bytes + len(encoded) > self.max_protocol_bytes:
            record = {
                "type": "result",
                "protocol_version": PROTOCOL_VERSION,
                "result": {
                    "status": "budget_exhausted",
                    "duration_ms": payload.get("duration_ms", 0),
                    "error": {
                        "code": "terminal_result_budget_exhausted",
                        "message": "terminal worker result exceeded the resolved profile limit",
                        "retryable": False,
                    },
                },
            }
            encoded = _encode_record(record)
        self.protocol_bytes += len(encoded)
        _write_encoded(encoded)


def _encode_record(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


def _write_encoded(value: bytes) -> None:
    sys.stdout.buffer.write(value)
    sys.stdout.buffer.flush()


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number is forbidden: {value}")


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Enum):
        return _json_value(value.value)
    if hasattr(value, "model_dump"):
        return _json_value(value.model_dump(by_alias=True, exclude_none=True, mode="json"))
    if is_dataclass(value):
        return {item.name: _json_value(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return str(value)


def _notification_payload(value: Any) -> dict[str, Any]:
    """Return the wire payload represented by one SDK notification model.

    The preview SDK deliberately wraps notifications it cannot validate as an
    ``UnknownNotification(params=...)`` dataclass.  Those notifications are
    still routed to the correct turn by the SDK, but serializing the wrapper
    verbatim would add a synthetic ``params`` level and hide the terminal
    ``turn`` object from this adapter's protocol checks.  Unwrap only that
    exact SDK compatibility type; ordinary notification payloads keep their
    normal shape.
    """

    if type(value).__name__ == "UnknownNotification":
        params = getattr(value, "params", None)
        if isinstance(params, Mapping):
            unwrapped = _json_value(params)
            if isinstance(unwrapped, dict):
                return unwrapped
    converted = _json_value(value)
    if isinstance(converted, dict):
        return converted
    return {"value": converted}


def _require_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _require_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a non-empty string")
    return value


def _optional_string(value: Any, label: str) -> str | None:
    if value is None:
        return None
    return _require_string(value, label)


def _completed_turn_payload(
    method: str,
    event_payload: Mapping[str, Any],
    expected_turn_id: str,
) -> dict[str, Any] | None:
    if method != "turn/completed":
        return None
    turn = event_payload.get("turn")
    if not isinstance(turn, dict) or turn.get("id") != expected_turn_id:
        return None
    return turn


def _compact_notification_payload(
    method: str,
    event_payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Project SDK notifications to bounded telemetry metadata.

    Codex delta notifications may repeat a growing text buffer.  Forwarding
    those buffers across the private NDJSON protocol makes protocol bytes grow
    much faster than model tokens and can terminate an otherwise healthy turn.
    The worker itself retains the full notification long enough to extract the
    final answer, terminal turn and token usage; the parent needs only event
    ordering, stable identities, phases, statuses and numeric usage.
    """

    compact: dict[str, Any] = {}
    for key in ("threadId", "turnId"):
        value = event_payload.get(key)
        if isinstance(value, str):
            compact[key] = value
    for key in ("turn", "item"):
        value = event_payload.get(key)
        if not isinstance(value, dict):
            continue
        projected = {
            field: value[field]
            for field in ("id", "type", "phase", "status")
            if isinstance(value.get(field), str)
        }
        if projected:
            compact[key] = projected
    token_usage = event_payload.get("tokenUsage")
    if isinstance(token_usage, dict):
        compact["tokenUsage"] = {
            key: value
            for key, value in token_usage.items()
            if isinstance(key, str)
            and isinstance(value, (int, float))
            and not isinstance(value, bool)
        }
    compact["sourceMethod"] = method
    return compact


def _validated_codex_binary(path_text: str, expected_digest: str) -> Path:
    path = Path(path_text)
    if (
        not path.is_absolute()
        or path.is_symlink()
        or not path.is_file()
        or not os.access(path, os.X_OK)
    ):
        raise OSError("the explicitly configured Codex runtime is unavailable")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != expected_digest:
        raise OSError("the explicitly configured Codex runtime changed after resolution")
    return path


def _status_result(
    *,
    status: str,
    started: float,
    code: str | None = None,
    message: str | None = None,
    retryable: bool = False,
    **extra: Any,
) -> dict[str, Any]:
    error = None
    if code is not None:
        error = {"code": code, "message": message or code, "retryable": retryable}
    return {
        "status": status,
        "duration_ms": int((time.monotonic() - started) * 1000),
        "error": error,
        **extra,
    }


async def _interrupt(turn: Any, timeout_seconds: float) -> None:
    try:
        await asyncio.wait_for(turn.interrupt(), timeout=timeout_seconds)
    except Exception:
        # The parent hard watchdog will terminate the complete worker tree.
        return


async def _run(payload: dict[str, Any]) -> None:
    started = time.monotonic()
    raw_credential_names = payload.get("credential_environment_names", [])
    if not isinstance(raw_credential_names, list) or not all(
        isinstance(name, str) and _ENVIRONMENT_NAME.fullmatch(name) for name in raw_credential_names
    ):
        raise ValueError("credential_environment_names must contain environment names")
    credential_values = [os.environ[name] for name in raw_credential_names if os.environ.get(name)]
    redactor = Redactor.from_values(credential_values)
    limits = _require_object(payload.get("limits"), "limits")
    emitter = Emitter(
        redactor=redactor,
        max_events=int(limits.get("max_events", 20_000)),
        max_protocol_bytes=int(limits.get("max_protocol_bytes", 32 * 1024 * 1024)),
    )

    authentication_kind = _require_string(payload.get("authentication_kind"), "authentication_kind")
    api_key: str | None = None
    if authentication_kind == "api_key":
        authentication_environment = _require_string(
            payload.get("authentication_environment"), "authentication_environment"
        )
        api_key = os.environ.pop(authentication_environment, None)
        if not api_key:
            emitter.result(
                _status_result(
                    status="needs_human",
                    started=started,
                    code="authentication_missing",
                    message="the resolved API-key credential is unavailable in the worker",
                )
            )
            return
    elif authentication_kind != "chatgpt":
        raise ValueError(f"unsupported authentication_kind: {authentication_kind!r}")

    try:
        from openai_codex import (  # type: ignore[import-not-found]
            ApprovalMode,
            AsyncCodex,
            CodexConfig,
        )
        from openai_codex import (
            __version__ as sdk_version,
        )
        from openai_codex.generated.v2_all import ReasoningEffort as SdkReasoningEffort
    except (ImportError, ModuleNotFoundError) as exc:
        emitter.result(
            _status_result(
                status="needs_human",
                started=started,
                code="sdk_unavailable",
                message=f"openai-codex is not installed: {exc}",
            )
        )
        return

    if sdk_version != SUPPORTED_SDK_VERSION:
        emitter.result(
            _status_result(
                status="needs_human",
                started=started,
                code="sdk_version_unsupported",
                message=(
                    f"openai-codex {sdk_version} is installed; this adapter is pinned to "
                    f"{SUPPORTED_SDK_VERSION} because the SDK API is beta"
                ),
                backend_version=sdk_version,
            )
        )
        return

    configured_codex_bin = _optional_string(payload.get("codex_bin"), "codex_bin")
    configured_codex_digest = _optional_string(
        payload.get("codex_bin_sha256"),
        "codex_bin_sha256",
    )
    if (configured_codex_bin is None) != (configured_codex_digest is None):
        raise ValueError("codex_bin and codex_bin_sha256 must be present together")
    runtime_path: Path | None = None
    if configured_codex_bin is not None:
        assert configured_codex_digest is not None
        try:
            codex_binary = await asyncio.to_thread(
                _validated_codex_binary,
                configured_codex_bin,
                configured_codex_digest,
            )
        except OSError as exc:
            emitter.result(
                _status_result(
                    status="needs_human",
                    started=started,
                    code="codex_runtime_unavailable",
                    message=str(exc),
                    backend_version=sdk_version,
                )
            )
            return
    else:
        try:
            from codex_cli_bin import (  # type: ignore[import-untyped]
                bundled_codex_path,
                bundled_path_dir,
            )
        except (ImportError, ModuleNotFoundError):
            emitter.result(
                _status_result(
                    status="needs_human",
                    started=started,
                    code="codex_runtime_unavailable",
                    message="the runtime package pinned by openai-codex is not installed",
                    backend_version=sdk_version,
                )
            )
            return
        try:
            runtime_version = importlib.metadata.version("openai-codex-cli-bin")
        except importlib.metadata.PackageNotFoundError:
            runtime_version = None
        if runtime_version != SUPPORTED_RUNTIME_VERSION:
            emitter.result(
                _status_result(
                    status="needs_human",
                    started=started,
                    code="codex_runtime_version_unsupported",
                    message=(
                        f"openai-codex-cli-bin {runtime_version or 'missing'} is installed; "
                        f"this adapter requires {SUPPORTED_RUNTIME_VERSION}"
                    ),
                    backend_version=sdk_version,
                )
            )
            return
        codex_binary = bundled_codex_path()
        runtime_path = bundled_path_dir()

    workspace = Path(_require_string(payload.get("workspace"), "workspace")).resolve()  # noqa: ASYNC240
    if not workspace.is_dir():
        emitter.result(
            _status_result(
                status="failed",
                started=started,
                code="workspace_missing",
                message="the resolved workspace no longer exists",
                backend_version=sdk_version,
            )
        )
        return
    sandbox_name = _require_string(payload.get("sandbox"), "sandbox")
    if sandbox_name not in {"read-only", "workspace-write"}:
        raise ValueError(f"unsupported sandbox: {sandbox_name!r}")
    reasoning_name = _require_string(payload.get("reasoning_effort"), "reasoning_effort")
    reasoning_effort = {
        "low": SdkReasoningEffort.low,
        "medium": SdkReasoningEffort.medium,
        "high": SdkReasoningEffort.high,
        "xhigh": SdkReasoningEffort.xhigh,
    }.get(reasoning_name)
    if reasoning_effort is None:
        emitter.result(
            _status_result(
                status="failed",
                started=started,
                code="reasoning_effort_unsupported",
                message=f"unsupported reasoning effort: {reasoning_name!r}",
                backend_version=sdk_version,
            )
        )
        return

    timeout_seconds = float(limits.get("timeout_seconds", 600.0))
    interrupt_grace_seconds = float(limits.get("interrupt_grace_seconds", 5.0))
    hooks_enabled = payload.get("hooks_enabled", False)
    if not isinstance(hooks_enabled, bool):
        raise ValueError("hooks_enabled must be a boolean")
    deadline = started + timeout_seconds
    thread_id: str | None = None
    turn_id: str | None = None
    final_text: str | None = None
    unknown_phase_text: str | None = None
    usage: dict[str, Any] | None = None
    completed_turn: dict[str, Any] | None = None

    try:
        app_server_environment = dict(os.environ)
        if runtime_path is not None:
            current_path = app_server_environment.get("PATH", "")
            entries = [str(runtime_path)]
            entries.extend(
                entry
                for entry in current_path.split(os.pathsep)
                if entry and entry != str(runtime_path)
            )
            app_server_environment["PATH"] = os.pathsep.join(entries)
        launch_args = [str(codex_binary), "--strict-config"]
        if hooks_enabled:
            # Resolver-vetted hooks are copied into the otherwise empty
            # CODEX_HOME.  The SDK has no hook-trust API, so automation must use
            # the official CLI flag with the exact runtime bundled by the SDK.
            launch_args.append("--dangerously-bypass-hook-trust")
        launch_args.extend(("app-server", "--listen", "stdio://"))
        config = CodexConfig(
            cwd=str(workspace),
            env=app_server_environment,
            launch_args_override=tuple(launch_args),
            client_name="agent_world_foundry",
            client_title="Agent World Foundry",
            client_version=PROTOCOL_VERSION,
        )
        async with AsyncCodex(config) as codex:
            if authentication_kind == "api_key":
                try:
                    await codex.login_api_key(str(api_key))
                finally:
                    api_key = None
            account = await codex.account(refresh_token=False)
            if getattr(account, "account", None) is None:
                emitter.result(
                    _status_result(
                        status="needs_human",
                        started=started,
                        code="authentication_failed",
                        message=(
                            "Codex did not report an authenticated account in the isolated home"
                        ),
                        backend_version=sdk_version,
                    )
                )
                return

            base_instructions = _require_string(
                payload.get("base_instructions"), "base_instructions"
            )
            developer_instructions = _optional_string(
                payload.get("developer_instructions"), "developer_instructions"
            )
            model = _require_string(payload.get("model"), "model")
            model_provider = _optional_string(payload.get("model_provider"), "model_provider")
            requested_thread_id = payload.get("thread_id")
            if requested_thread_id is None:
                thread = await codex.thread_start(
                    approval_mode=ApprovalMode.deny_all,
                    base_instructions=base_instructions,
                    cwd=str(workspace),
                    developer_instructions=developer_instructions,
                    ephemeral=False,
                    model=model,
                    model_provider=model_provider,
                )
            else:
                thread = await codex.thread_resume(
                    _require_string(requested_thread_id, "thread_id"),
                    approval_mode=ApprovalMode.deny_all,
                    base_instructions=base_instructions,
                    cwd=str(workspace),
                    developer_instructions=developer_instructions,
                    model=model,
                    model_provider=model_provider,
                )
            thread_id = thread.id
            if requested_thread_id is not None and thread_id != requested_thread_id:
                raise RuntimeError("Codex resumed a different thread id")

            turn = await thread.turn(
                _require_string(payload.get("prompt"), "prompt"),
                approval_mode=ApprovalMode.deny_all,
                cwd=str(workspace),
                effort=reasoning_effort,
                model=model,
                output_schema=payload.get("output_schema"),
            )
            turn_id = turn.id
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                await _interrupt(turn, interrupt_grace_seconds)
                emitter.result(
                    _status_result(
                        status="timed_out",
                        started=started,
                        code="soft_timeout",
                        message="invocation deadline elapsed before the turn stream began",
                        thread_id=thread_id,
                        turn_id=turn_id,
                        backend_version=sdk_version,
                    )
                )
                return

            try:
                async with asyncio.timeout(remaining):
                    async for notification in turn.stream():
                        event_payload = _notification_payload(notification.payload)
                        item = event_payload.get("item")
                        if isinstance(item, dict) and item.get("type") == "agentMessage":
                            text = item.get("text")
                            phase = item.get("phase")
                            if isinstance(text, str):
                                if phase == "final_answer":
                                    final_text = text
                                elif phase is None:
                                    unknown_phase_text = text
                        token_usage = event_payload.get("tokenUsage")
                        if isinstance(token_usage, dict):
                            usage = token_usage
                        terminal_turn = _completed_turn_payload(
                            notification.method,
                            event_payload,
                            turn_id,
                        )
                        emitter.event(
                            notification.method,
                            _compact_notification_payload(
                                notification.method,
                                event_payload,
                            ),
                        )
                        if terminal_turn is not None:
                            completed_turn = terminal_turn
                            # A newer explicitly selected Codex CLI can add
                            # fields that the beta Python SDK decodes as an
                            # unknown notification model.  AsyncTurnHandle's
                            # own iterator then fails its concrete-class stop
                            # check even though the wire event is the exact
                            # terminal event for this turn.  The adapter owns
                            # the wire compatibility boundary, so stop on the
                            # validated method + exact turn id instead of
                            # waiting until the whole invocation deadline.
                            break
            except TimeoutError:
                await _interrupt(turn, interrupt_grace_seconds)
                emitter.result(
                    _status_result(
                        status="timed_out",
                        started=started,
                        code="soft_timeout",
                        message="Codex turn exceeded its resolved profile deadline",
                        thread_id=thread_id,
                        turn_id=turn_id,
                        usage=usage,
                        backend_version=sdk_version,
                    )
                )
                return
            except ProtocolBudgetExceeded as exc:
                await _interrupt(turn, interrupt_grace_seconds)
                emitter.result(
                    _status_result(
                        status="budget_exhausted",
                        started=started,
                        code="event_budget_exhausted",
                        message=str(exc),
                        thread_id=thread_id,
                        turn_id=turn_id,
                        usage=usage,
                        backend_version=sdk_version,
                    )
                )
                return
    except (FileNotFoundError, ImportError) as exc:
        emitter.result(
            _status_result(
                status="needs_human",
                started=started,
                code="codex_runtime_unavailable",
                message=str(exc),
                thread_id=thread_id,
                turn_id=turn_id,
                backend_version=sdk_version,
            )
        )
        return
    except Exception as exc:
        message = redactor.text(str(exc))
        lowered = message.lower()
        authentication_error = any(
            marker in lowered
            for marker in ("auth", "api key", "unauthorized", "forbidden", "login")
        )
        emitter.result(
            _status_result(
                status="needs_human" if authentication_error else "failed",
                started=started,
                code="authentication_failed" if authentication_error else "sdk_execution_failed",
                message=message or type(exc).__name__,
                retryable=not authentication_error,
                thread_id=thread_id,
                turn_id=turn_id,
                usage=usage,
                backend_version=sdk_version,
            )
        )
        return

    final_text = final_text if final_text is not None else unknown_phase_text
    if completed_turn is None:
        emitter.result(
            _status_result(
                status="failed",
                started=started,
                code="turn_completion_missing",
                message="Codex event stream ended without turn/completed",
                retryable=True,
                thread_id=thread_id,
                turn_id=turn_id,
                final_text=final_text,
                usage=usage,
                backend_version=sdk_version,
            )
        )
        return
    turn_status = completed_turn.get("status")
    if turn_status != "completed":
        error = completed_turn.get("error")
        error_message = error.get("message") if isinstance(error, dict) else None
        emitter.result(
            _status_result(
                status="failed" if turn_status == "failed" else "cancelled",
                started=started,
                code=f"turn_{turn_status or 'unknown'}",
                message=str(error_message or f"Codex turn ended with {turn_status!r}"),
                retryable=turn_status == "failed",
                thread_id=thread_id,
                turn_id=turn_id,
                final_text=final_text,
                usage=usage,
                backend_version=sdk_version,
            )
        )
        return

    structured_output: Any = None
    if payload.get("output_schema") is not None:
        if final_text is None:
            emitter.result(
                _status_result(
                    status="failed",
                    started=started,
                    code="structured_output_missing",
                    message="Codex completed without the required structured final response",
                    thread_id=thread_id,
                    turn_id=turn_id,
                    usage=usage,
                    backend_version=sdk_version,
                )
            )
            return
        try:
            structured_output = json.loads(final_text, parse_constant=_reject_json_constant)
        except (json.JSONDecodeError, ValueError) as exc:
            emitter.result(
                _status_result(
                    status="failed",
                    started=started,
                    code="structured_output_invalid_json",
                    message=f"output_schema was requested but final response is not JSON: {exc}",
                    thread_id=thread_id,
                    turn_id=turn_id,
                    final_text=final_text,
                    usage=usage,
                    backend_version=sdk_version,
                )
            )
            return

    emitter.result(
        _status_result(
            status="completed",
            started=started,
            thread_id=thread_id,
            turn_id=turn_id,
            final_text=final_text,
            structured_output=structured_output,
            usage=usage,
            backend_version=sdk_version,
        )
    )


def main() -> int:
    started = time.monotonic()
    line = sys.stdin.buffer.readline(8 * 1024 * 1024 + 1)
    if len(line) > 8 * 1024 * 1024:
        _write_encoded(
            _encode_record(
                {
                    "type": "result",
                    "protocol_version": PROTOCOL_VERSION,
                    "result": _status_result(
                        status="failed",
                        started=started,
                        code="worker_request_too_large",
                        message="worker request exceeded 8 MiB",
                    ),
                }
            )
        )
        return 2
    try:
        payload = json.loads(line, parse_constant=_reject_json_constant)
        if not isinstance(payload, dict):
            raise ValueError("worker request must be a JSON object")
        if payload.get("protocol_version") != PROTOCOL_VERSION:
            raise ValueError("worker protocol version mismatch")
        asyncio.run(_run(payload))
        return 0
    except Exception as exc:
        redactor = Redactor()
        _write_encoded(
            _encode_record(
                {
                    "type": "result",
                    "protocol_version": PROTOCOL_VERSION,
                    "result": _status_result(
                        status="failed",
                        started=started,
                        code="worker_request_invalid",
                        message=redactor.text(str(exc) or type(exc).__name__),
                    ),
                }
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
