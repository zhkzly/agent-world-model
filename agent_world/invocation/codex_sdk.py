"""Real ``openai-codex`` backend supervised through a dedicated worker.

There is exactly one production implementation in this module.  It launches a
fixed Python worker that calls ``AsyncCodex``; it never falls back to a CLI,
generic shell command, template generator, manual backend, or mock backend.
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import sys
import tempfile
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agent_world.control.telemetry import TelemetryStore, WorkSpan

from ._codex_worker import PROTOCOL_VERSION
from .contracts import (
    InvocationError,
    InvocationEvent,
    InvocationRequest,
    InvocationResult,
    InvocationSession,
    InvocationStatus,
    InvocationUsage,
    JsonObject,
    JsonValue,
    TokenBreakdown,
    json_compatible,
)
from .profiles import ProfileResolutionError, verify_resolved_profile
from .redaction import Redactor

_PROVIDER_SCHEMA_OMIT_KEYS = frozenset({"default", "discriminator"})
_JSON_VALUE_IR = "AgentWorldJsonValueIR"
_JSON_OBJECT_IR = "AgentWorldJsonObjectIR"
_JSON_ENTRY_IR = "AgentWorldJsonEntryIR"
# /dev/shm is the fixed kernel tmpfs mount.  TemporaryDirectory creates a
# mode-0700 child there; falling back to a disk temp directory is forbidden.
_EPHEMERAL_SQLITE_PARENT = Path("/dev/shm")  # noqa: S108
_EPHEMERAL_SQLITE_PREFIX = "agent-world-codex-sqlite-"


@dataclass(slots=True)
class _ActiveWorker:
    process: asyncio.subprocess.Process
    kill_grace_seconds: float


@dataclass(slots=True)
class _StdoutCapture:
    events: list[InvocationEvent]
    result: dict[str, Any] | None
    errors: list[str]
    overflowed: bool


def _consume_task_result(task: asyncio.Task[object]) -> None:
    """Drain a detached cleanup task without surfacing cancellation noise."""

    try:
        task.result()
    except BaseException:
        return


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number is forbidden: {value}")


def _open_ephemeral_sqlite_home() -> tempfile.TemporaryDirectory[str]:
    """Allocate a memory-backed Codex SQLite home for exactly one worker.

    Codex app-server 0.144.4 creates local SQLite state/log databases even
    when history, analytics, and feedback are disabled.  That vendor-local
    state must not live below the durable profile/artifact root because a
    custom provider's runtime configuration can otherwise be recorded there.
    A missing memory-backed runtime is a fail-closed configuration error, not
    a reason to fall back to a disk-backed directory.
    """

    if (
        os.name != "posix"
        or not _EPHEMERAL_SQLITE_PARENT.is_dir()
        or not os.access(_EPHEMERAL_SQLITE_PARENT, os.W_OK | os.X_OK)
    ):
        raise OSError("memory-backed Codex SQLite runtime is unavailable")
    return tempfile.TemporaryDirectory(
        prefix=_EPHEMERAL_SQLITE_PREFIX,
        dir=_EPHEMERAL_SQLITE_PARENT,
    )


def _worker_environment_with_ephemeral_sqlite_home(
    profile_environment: Mapping[str, str],
    sqlite_home: Path,
) -> dict[str, str]:
    """Add the volatile SQLite root without widening a profile's environment."""

    resolved_sqlite_home = sqlite_home.resolve(strict=True)
    if not resolved_sqlite_home.is_relative_to(_EPHEMERAL_SQLITE_PARENT):
        raise ValueError("Codex SQLite runtime must stay in the memory-backed parent")
    environment = dict(profile_environment)
    environment["CODEX_SQLITE_HOME"] = str(resolved_sqlite_home)
    return environment


class CodexSdkBackend:
    """Invoke the pinned Codex Python SDK in a new process for every turn."""

    supported_executor_revision_ids = (
        "framework.executor.v1",
        "framework.codex-structured-protocol.v2",
        "framework.codex-structured-protocol.v3",
    )

    def __init__(
        self,
        *,
        max_concurrent_invocations: int = 1,
        telemetry: TelemetryStore | None = None,
    ) -> None:
        if not 1 <= max_concurrent_invocations <= 32:
            raise ValueError("max_concurrent_invocations must be between 1 and 32")
        self._worker_path = Path(__file__).with_name("_codex_worker.py").resolve()
        self._active: dict[str, _ActiveWorker] = {}
        self._cancelled: set[str] = set()
        self._lock = asyncio.Lock()
        self._capacity = asyncio.Semaphore(max_concurrent_invocations)
        self._telemetry = telemetry
        self._telemetry_failures = 0

    @property
    def telemetry_failures(self) -> int:
        return self._telemetry_failures

    async def invoke(self, request: InvocationRequest) -> InvocationResult:
        # Queueing is controller/backend scheduling, not model execution.  Acquire
        # capacity before starting either the per-turn clock or the worker watchdog.
        telemetry_span: WorkSpan | None = None
        telemetry_progress_disabled = False
        queue_started = time.perf_counter_ns()
        if self._telemetry is not None:
            try:
                telemetry_span = self._telemetry.start_invocation(request)
            except Exception:
                self._telemetry_failures += 1
        try:
            async with self._capacity:
                queue_duration_ms = (time.perf_counter_ns() - queue_started) / 1_000_000

                def mark_provider_progress(method: str) -> None:
                    nonlocal telemetry_progress_disabled
                    if telemetry_span is None or telemetry_progress_disabled:
                        return
                    try:
                        telemetry_span.progress(method)
                    except Exception:
                        self._telemetry_failures += 1
                        telemetry_progress_disabled = True

                result = await self._invoke_bounded(
                    request,
                    on_first_progress=mark_provider_progress,
                )
        except asyncio.CancelledError:
            if telemetry_span is not None:
                try:
                    telemetry_span.finish(status="cancelled", error_code="cancelled")
                except Exception:
                    self._telemetry_failures += 1
            raise
        except Exception as exc:
            if telemetry_span is not None and not telemetry_span.closed:
                try:
                    telemetry_span.finish(
                        status="error",
                        error_code=type(exc).__name__,
                    )
                except Exception:
                    self._telemetry_failures += 1
            raise
        if self._telemetry is not None and telemetry_span is not None:
            try:
                self._telemetry.finish_invocation(
                    telemetry_span,
                    request,
                    result,
                    queue_duration_ms=queue_duration_ms,
                )
            except Exception:
                self._telemetry_failures += 1
        return result

    async def _invoke_bounded(
        self,
        request: InvocationRequest,
        *,
        on_first_progress: Callable[[str], None] | None = None,
    ) -> InvocationResult:
        """Bound the complete parent-side worker lifecycle and account its elapsed time."""

        started = time.monotonic()
        limits = request.profile.limits
        normal_lifecycle_ceiling = (
            limits.timeout_seconds + limits.interrupt_grace_seconds + 0.5
        )
        invocation_task = asyncio.create_task(
            self._invoke_with_capacity(
                request,
                on_first_progress=on_first_progress,
            ),
            name=f"codex-worker-{request.invocation_id}",
        )
        try:
            result = await asyncio.wait_for(
                asyncio.shield(invocation_task),
                timeout=normal_lifecycle_ceiling,
            )
        except TimeoutError:
            await self._bounded_worker_cleanup(
                request.invocation_id,
                invocation_task,
                kill_grace_seconds=limits.kill_grace_seconds,
            )
            result = _local_failure(
                request,
                status=InvocationStatus.TIMED_OUT,
                code="hard_timeout",
                message="complete worker lifecycle exceeded its parent-side hard deadline",
                started=started,
            )
        except asyncio.CancelledError:
            await self._bounded_worker_cleanup(
                request.invocation_id,
                invocation_task,
                kill_grace_seconds=limits.kill_grace_seconds,
            )
            raise
        parent_duration_ms = max(0, int((time.monotonic() - started) * 1000))
        return replace(result, duration_ms=parent_duration_ms)

    async def _bounded_worker_cleanup(
        self,
        invocation_id: str,
        invocation_task: asyncio.Task[InvocationResult],
        *,
        kill_grace_seconds: float,
    ) -> None:
        """Spend only the reserved two kill-grace windows on worker cleanup."""

        cancel_task = asyncio.create_task(
            self.cancel(invocation_id),
            name=f"cancel-codex-worker-{invocation_id}",
        )
        invocation_task.cancel()
        try:
            async with asyncio.timeout(2 * kill_grace_seconds):
                await asyncio.gather(cancel_task, invocation_task, return_exceptions=True)
        except TimeoutError:
            cancel_task.cancel()
            invocation_task.cancel()
            for task in (cancel_task, invocation_task):
                task.add_done_callback(_consume_task_result)

    async def _invoke_with_capacity(
        self,
        request: InvocationRequest,
        *,
        on_first_progress: Callable[[str], None] | None = None,
    ) -> InvocationResult:
        started = time.monotonic()
        redactor = Redactor.from_values(request.profile.secret_values)
        try:
            verify_resolved_profile(request.profile)
        except ProfileResolutionError as exc:
            return _local_failure(
                request,
                status=InvocationStatus.FAILED,
                code="profile_integrity_error",
                message=redactor.text(str(exc)),
                started=started,
            )
        except OSError as exc:
            return _local_failure(
                request,
                status=InvocationStatus.FAILED,
                code="profile_io_error",
                message=redactor.text(str(exc) or type(exc).__name__),
                started=started,
                retryable=True,
            )

        payload = self._worker_payload(request)
        encoded_payload = (
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
        ).encode("utf-8")
        if len(encoded_payload) > 8 * 1024 * 1024:
            return _local_failure(
                request,
                status=InvocationStatus.FAILED,
                code="worker_request_too_large",
                message="invocation request exceeds the fixed worker protocol limit",
                started=started,
            )

        try:
            with _open_ephemeral_sqlite_home() as sqlite_home_text:
                return await self._invoke_worker_process(
                    request,
                    encoded_payload=encoded_payload,
                    redactor=redactor,
                    sqlite_home=Path(sqlite_home_text),
                    started=started,
                    on_first_progress=on_first_progress,
                )
        except OSError:
            return _local_failure(
                request,
                status=InvocationStatus.NEEDS_HUMAN,
                code="ephemeral_sqlite_runtime_unavailable",
                message="memory-backed Codex SQLite isolation is unavailable",
                started=started,
            )

    async def _invoke_worker_process(
        self,
        request: InvocationRequest,
        *,
        encoded_payload: bytes,
        redactor: Redactor,
        sqlite_home: Path,
        started: float,
        on_first_progress: Callable[[str], None] | None = None,
    ) -> InvocationResult:
        process_kwargs: dict[str, Any] = {
            "stdin": asyncio.subprocess.PIPE,
            "stdout": asyncio.subprocess.PIPE,
            "stderr": asyncio.subprocess.PIPE,
            "cwd": str(request.profile.materialization_root),
            "env": _worker_environment_with_ephemeral_sqlite_home(
                request.profile.worker_environment(),
                sqlite_home,
            ),
            "limit": max(8 * 1024 * 1024, request.profile.limits.max_protocol_bytes + 1024),
        }
        if os.name == "posix":
            process_kwargs["start_new_session"] = True
        elif os.name == "nt":
            process_kwargs["creationflags"] = 0x00000200  # CREATE_NEW_PROCESS_GROUP

        async with self._lock:
            if request.invocation_id in self._active:
                return _local_failure(
                    request,
                    status=InvocationStatus.FAILED,
                    code="duplicate_invocation_id",
                    message="an invocation with this id is already active",
                    started=started,
                )
            self._cancelled.discard(request.invocation_id)
            # Keep the reservation lock through process creation.  This closes
            # the otherwise observable gap where a duplicate invocation or a
            # cancellation could race before the worker was registered.
            try:
                process = await asyncio.create_subprocess_exec(
                    sys.executable,
                    str(self._worker_path),
                    **process_kwargs,
                )
            except (FileNotFoundError, PermissionError) as exc:
                return _local_failure(
                    request,
                    status=InvocationStatus.NEEDS_HUMAN,
                    code="worker_unavailable",
                    message=redactor.text(str(exc) or type(exc).__name__),
                    started=started,
                )
            except OSError as exc:
                return _local_failure(
                    request,
                    status=InvocationStatus.FAILED,
                    code="worker_spawn_error",
                    message=redactor.text(str(exc) or type(exc).__name__),
                    started=started,
                    retryable=True,
                )
            self._active[request.invocation_id] = _ActiveWorker(
                process=process,
                kill_grace_seconds=request.profile.limits.kill_grace_seconds,
            )

        stdout_capture_task = asyncio.create_task(
            _capture_stdout(
                process.stdout,
                request=request,
                redactor=redactor,
                on_first_progress=on_first_progress,
            )
        )
        stderr_capture_task = asyncio.create_task(
            _capture_stderr(
                process.stderr,
                max_bytes=request.profile.limits.max_stderr_bytes,
                redactor=redactor,
            )
        )
        hard_timed_out = False
        try:
            assert process.stdin is not None
            process.stdin.write(encoded_payload)
            await process.stdin.drain()
            process.stdin.close()
            hard_timeout = (
                request.profile.limits.timeout_seconds
                + request.profile.limits.interrupt_grace_seconds
                + 0.5
            )
            try:
                await asyncio.wait_for(process.wait(), timeout=hard_timeout)
            except TimeoutError:
                hard_timed_out = True
                await _terminate_process_tree(
                    process,
                    grace_seconds=request.profile.limits.kill_grace_seconds,
                )
        except asyncio.CancelledError:
            await _terminate_process_tree(
                process,
                grace_seconds=request.profile.limits.kill_grace_seconds,
            )
            raise
        except (BrokenPipeError, ConnectionResetError, OSError) as exc:
            await _terminate_process_tree(
                process,
                grace_seconds=request.profile.limits.kill_grace_seconds,
            )
            stdout_capture = await _finish_stdout_capture(stdout_capture_task)
            stderr_text = await _finish_stderr_capture(stderr_capture_task)
            return _local_failure(
                request,
                status=InvocationStatus.FAILED,
                code="worker_transport_error",
                message=redactor.text(str(exc) or type(exc).__name__),
                started=started,
                events=tuple(stdout_capture.events),
                details={"stderr": stderr_text} if stderr_text else {},
                worker_exit_code=process.returncode,
                retryable=True,
            )
        finally:
            async with self._lock:
                self._active.pop(request.invocation_id, None)

        stdout_capture = await _finish_stdout_capture(stdout_capture_task)
        stderr_text = await _finish_stderr_capture(stderr_capture_task)
        async with self._lock:
            was_cancelled = request.invocation_id in self._cancelled
            self._cancelled.discard(request.invocation_id)

        if was_cancelled:
            return _local_failure(
                request,
                status=InvocationStatus.CANCELLED,
                code="cancelled",
                message="invocation was cancelled by the controller",
                started=started,
                events=tuple(stdout_capture.events),
                worker_exit_code=process.returncode,
            )
        if hard_timed_out:
            return _local_failure(
                request,
                status=InvocationStatus.TIMED_OUT,
                code="hard_timeout",
                message="worker did not stop after the SDK interrupt grace period and was killed",
                started=started,
                events=tuple(stdout_capture.events),
                worker_exit_code=process.returncode,
            )
        if stdout_capture.overflowed:
            return _local_failure(
                request,
                status=InvocationStatus.BUDGET_EXHAUSTED,
                code="protocol_budget_exhausted",
                message="worker protocol output exceeded the resolved profile limit",
                started=started,
                events=tuple(stdout_capture.events),
                worker_exit_code=process.returncode,
            )
        if stdout_capture.errors:
            return _local_failure(
                request,
                status=InvocationStatus.FAILED,
                code="worker_protocol_error",
                message="; ".join(stdout_capture.errors),
                started=started,
                events=tuple(stdout_capture.events),
                details={"stderr": stderr_text} if stderr_text else {},
                worker_exit_code=process.returncode,
                retryable=True,
            )
        if stdout_capture.result is None:
            return _local_failure(
                request,
                status=InvocationStatus.FAILED,
                code="worker_result_missing",
                message="worker exited without a terminal result",
                started=started,
                events=tuple(stdout_capture.events),
                details={"stderr": stderr_text} if stderr_text else {},
                worker_exit_code=process.returncode,
            )
        try:
            return _result_from_worker(
                request,
                raw=stdout_capture.result,
                events=tuple(stdout_capture.events),
                worker_exit_code=process.returncode,
                started=started,
                redactor=redactor,
            )
        except (TypeError, ValueError, OverflowError) as exc:
            return _local_failure(
                request,
                status=InvocationStatus.FAILED,
                code="worker_protocol_error",
                message=redactor.text(str(exc) or type(exc).__name__),
                started=started,
                events=tuple(stdout_capture.events),
                worker_exit_code=process.returncode,
                retryable=True,
            )

    async def cancel(self, invocation_id: str) -> bool:
        async with self._lock:
            active = self._active.get(invocation_id)
            if active is None:
                return False
            self._cancelled.add(invocation_id)
        await _terminate_process_tree(
            active.process,
            grace_seconds=active.kill_grace_seconds,
        )
        return True

    @staticmethod
    def _worker_payload(request: InvocationRequest) -> JsonObject:
        profile = request.profile
        limits = profile.limits
        output_schema = profile.output_schema
        return {
            "protocol_version": PROTOCOL_VERSION,
            "invocation_id": request.invocation_id,
            "prompt": request.prompt,
            "workspace": str(profile.workspace),
            "model": profile.model,
            "model_provider": profile.model_provider,
            "reasoning_effort": profile.reasoning_effort.value,
            "base_instructions": profile.base_instructions,
            "developer_instructions": profile.developer_instructions,
            "sandbox": profile.sandbox.value,
            "output_schema": (
                _transport_output_schema(
                    output_schema,
                    transport=profile.structured_output_transport,
                )
                if output_schema is not None
                else None
            ),
            "structured_output_transport": profile.structured_output_transport,
            "thread_id": request.session.thread_id if request.session else None,
            "authentication_kind": profile.authentication_kind,
            "authentication_environment": profile.authentication_environment,
            "openai_base_url_environment": profile.openai_base_url_environment,
            "codex_bin": str(profile.codex_bin) if profile.codex_bin is not None else None,
            "codex_bin_sha256": profile.codex_bin_sha256,
            "sensitive_environment_names": list(profile.sensitive_environment_names),
            "hooks_enabled": bool(profile.hooks),
            "limits": {
                "timeout_seconds": limits.timeout_seconds,
                "interrupt_grace_seconds": limits.interrupt_grace_seconds,
                "max_events": limits.max_events,
                "max_protocol_bytes": limits.max_protocol_bytes,
            },
        }


def _transport_output_schema(schema: JsonObject, *, transport: str) -> JsonObject:
    if transport == "provider_schema":
        return _provider_output_schema(schema)
    if transport == "json_envelope":
        # The inner source contract travels in the prompt and remains subject
        # to local Pydantic/compiler validation. This outer contract exists
        # only for OpenAI-compatible gateways that reject nested schemas.
        return {
            "type": "object",
            "properties": {"artifact_json": {"type": "string"}},
            "required": ["artifact_json"],
            "additionalProperties": False,
        }
    raise ValueError("unsupported structured output transport")


def _provider_output_schema(schema: JsonObject) -> JsonObject:
    """Compile a logical schema to the provider's strict-output subset.

    The logical schema remains on ``ResolvedAgentProfile`` and is enforced by
    Pydantic after the turn.  This derived schema only guides generation.
    """

    used_ir: set[str] = set()
    normalized = _normalize_provider_schema_node(schema, used_ir=used_ir)
    if not isinstance(normalized, dict):
        raise TypeError("provider output schema root must remain an object")
    if normalized.get("type") != "object" or "anyOf" in normalized:
        raise ValueError("provider output schema root must be a non-union object")
    if used_ir:
        defs = normalized.setdefault("$defs", {})
        if not isinstance(defs, dict):
            raise TypeError("provider output schema $defs must be an object")
        synthetic = _provider_json_ir_defs()
        for name in (_JSON_ENTRY_IR, _JSON_VALUE_IR, _JSON_OBJECT_IR):
            if name in defs:
                raise ValueError(f"logical schema collides with provider IR definition {name}")
            defs[name] = synthetic[name]
    return normalized


def _normalize_provider_schema_node(
    value: JsonValue,
    *,
    used_ir: set[str],
) -> JsonValue:
    if not isinstance(value, dict):
        raise TypeError("JSON Schema nodes must be objects")
    if not value:
        used_ir.add(_JSON_VALUE_IR)
        return {"$ref": f"#/$defs/{_JSON_VALUE_IR}"}
    additional = value.get("additionalProperties")
    if (
        value.get("type") == "object"
        and additional is not None
        and additional is not False
    ):
        if additional is True or additional == {}:
            used_ir.add(_JSON_OBJECT_IR)
            return {"$ref": f"#/$defs/{_JSON_OBJECT_IR}"}
        if not isinstance(additional, dict):
            raise TypeError("provider map additionalProperties must be a schema object")
        property_names = value.get("propertyNames", {"type": "string"})
        if not isinstance(property_names, dict):
            raise TypeError("provider map propertyNames must be a schema object")
        entries: JsonObject = {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "aw_key": _normalize_provider_schema_node(
                        property_names,
                        used_ir=used_ir,
                    ),
                    "aw_value": _normalize_provider_schema_node(
                        additional,
                        used_ir=used_ir,
                    ),
                },
                "required": ["aw_key", "aw_value"],
                "additionalProperties": False,
            },
        }
        for source_key, target_key in (
            ("minProperties", "minItems"),
            ("maxProperties", "maxItems"),
        ):
            if source_key in value:
                entries[target_key] = value[source_key]
        normalized_map: JsonObject = {
            "type": "object",
            "properties": {"aw_object_entries": entries},
            "required": ["aw_object_entries"],
            "additionalProperties": False,
        }
        if isinstance(value.get("description"), str):
            normalized_map["description"] = value["description"]
        return normalized_map
    normalized: JsonObject = {}
    for key, child in value.items():
        if key in _PROVIDER_SCHEMA_OMIT_KEYS:
            continue
        target_key = "anyOf" if key == "oneOf" else key
        if target_key in normalized:
            raise ValueError(f"provider schema contains conflicting {target_key}")
        if key in {"properties", "$defs"}:
            if not isinstance(child, dict):
                raise TypeError(f"provider schema {key} must be an object")
            normalized[target_key] = {
                name: _normalize_provider_schema_node(item, used_ir=used_ir)
                for name, item in child.items()
            }
        elif key in {"anyOf", "oneOf"}:
            if not isinstance(child, list):
                raise TypeError(f"provider schema {key} must be an array")
            normalized[target_key] = [
                _normalize_provider_schema_node(item, used_ir=used_ir)
                for item in child
            ]
        elif key == "items":
            normalized[target_key] = _normalize_provider_schema_node(
                child,
                used_ir=used_ir,
            )
        else:
            normalized[target_key] = child

    if normalized.get("type") == "object" or "properties" in normalized:
        properties = normalized.get("properties", {})
        if not isinstance(properties, dict):
            raise TypeError("provider object schema properties must be an object")
        normalized["properties"] = properties
        normalized["required"] = list(properties)
        normalized["additionalProperties"] = False
    return normalized


def _provider_json_ir_defs() -> JsonObject:
    value_ref: JsonObject = {"$ref": f"#/$defs/{_JSON_VALUE_IR}"}
    entry_ref: JsonObject = {"$ref": f"#/$defs/{_JSON_ENTRY_IR}"}
    scalar_variants: list[JsonObject] = []
    for kind, value_type in (
        ("boolean", "boolean"),
        ("number", "number"),
        ("string", "string"),
    ):
        scalar_variants.append(
            {
                "type": "object",
                "properties": {
                    "aw_kind": {"const": kind, "type": "string"},
                    "aw_value": {"type": value_type},
                },
                "required": ["aw_kind", "aw_value"],
                "additionalProperties": False,
            }
        )
    return {
        _JSON_ENTRY_IR: {
            "type": "object",
            "properties": {
                "aw_key": {"type": "string"},
                "aw_value": value_ref,
            },
            "required": ["aw_key", "aw_value"],
            "additionalProperties": False,
        },
        _JSON_VALUE_IR: {
            "anyOf": [
                {
                    "type": "object",
                    "properties": {"aw_kind": {"const": "null", "type": "string"}},
                    "required": ["aw_kind"],
                    "additionalProperties": False,
                },
                *scalar_variants,
                {
                    "type": "object",
                    "properties": {
                        "aw_kind": {"const": "array", "type": "string"},
                        "aw_items": {"type": "array", "items": value_ref},
                    },
                    "required": ["aw_kind", "aw_items"],
                    "additionalProperties": False,
                },
                {
                    "type": "object",
                    "properties": {
                        "aw_kind": {"const": "object", "type": "string"},
                        "aw_entries": {"type": "array", "items": entry_ref},
                    },
                    "required": ["aw_kind", "aw_entries"],
                    "additionalProperties": False,
                },
            ]
        },
        _JSON_OBJECT_IR: {
            "type": "object",
            "properties": {
                "aw_object_entries": {"type": "array", "items": entry_ref}
            },
            "required": ["aw_object_entries"],
            "additionalProperties": False,
        },
    }


def _decode_provider_json_ir(value: JsonValue) -> JsonValue:
    if isinstance(value, list):
        return [_decode_provider_json_ir(item) for item in value]
    if not isinstance(value, dict):
        return value
    keys = set(value)
    if keys == {"aw_kind"} and value["aw_kind"] == "null":
        return None
    if keys == {"aw_kind", "aw_value"}:
        kind = value["aw_kind"]
        scalar = value["aw_value"]
        if (
            (kind == "boolean" and isinstance(scalar, bool))
            or (
                kind == "number"
                and isinstance(scalar, (int, float))
                and not isinstance(scalar, bool)
            )
            or (kind == "string" and isinstance(scalar, str))
        ):
            return scalar
        raise ValueError("provider JsonValue IR scalar variant is inconsistent")
    if keys == {"aw_kind", "aw_items"} and value["aw_kind"] == "array":
        items = value["aw_items"]
        if not isinstance(items, list):
            raise ValueError("provider JsonValue IR array variant is invalid")
        return [_decode_provider_json_ir(item) for item in items]
    if keys == {"aw_kind", "aw_entries"} and value["aw_kind"] == "object":
        return _decode_provider_json_entries(value["aw_entries"])
    if keys == {"aw_object_entries"}:
        return _decode_provider_json_entries(value["aw_object_entries"])
    return {key: _decode_provider_json_ir(item) for key, item in value.items()}


def _decode_json_envelope(value: JsonValue) -> JsonValue:
    """Decode a shallow envelope, or preserve a gateway's direct JSON object.

    A compatibility gateway can ignore a requested output schema and return the
    logical document directly. That document still receives the exact same
    local Pydantic validation; accepting it avoids reclassifying a usable typed
    proposal as a transport failure.  Some compatible gateways enforce the
    outer object name but not its string-valued field and return the logical
    JSON object directly under ``artifact_json``.  That is still only an
    encoding variation: it is passed through the same exact local Pydantic and
    deterministic compiler checks as a decoded string.  Scalars and arrays
    remain invalid, so this never accepts an abbreviated or untyped candidate.
    """

    if not isinstance(value, Mapping) or set(value) != {"artifact_json"}:
        return value
    encoded = value["artifact_json"]
    if isinstance(encoded, Mapping):
        return json_compatible(encoded)
    if not isinstance(encoded, str):
        raise ValueError(
            "structured output envelope artifact_json must be a JSON string or object"
        )
    return json_compatible(json.loads(encoded, parse_constant=_reject_json_constant))


def _decode_provider_json_entries(value: JsonValue) -> JsonObject:
    if not isinstance(value, list):
        raise ValueError("provider JsonValue IR object entries must be an array")
    decoded: JsonObject = {}
    for entry in value:
        if not isinstance(entry, dict) or set(entry) != {"aw_key", "aw_value"}:
            raise ValueError("provider JsonValue IR entry shape is invalid")
        key = entry["aw_key"]
        if not isinstance(key, str):
            raise ValueError("provider JsonValue IR entry key must be a string")
        if key in decoded:
            raise ValueError("provider JsonValue IR object contains duplicate keys")
        decoded[key] = _decode_provider_json_ir(entry["aw_value"])
    return decoded


async def _capture_stdout(
    stream: asyncio.StreamReader | None,
    *,
    request: InvocationRequest,
    redactor: Redactor,
    on_first_progress: Callable[[str], None] | None = None,
) -> _StdoutCapture:
    if stream is None:
        return _StdoutCapture([], None, ["worker stdout was not connected"], False)
    events: list[InvocationEvent] = []
    result: dict[str, Any] | None = None
    errors: list[str] = []
    total_bytes = 0
    overflowed = False
    expected_sequence = 0
    while True:
        try:
            line = await stream.readline()
        except (ValueError, asyncio.LimitOverrunError) as exc:
            errors.append(f"oversized worker protocol record: {exc}")
            break
        if not line:
            break
        total_bytes += len(line)
        if total_bytes > request.profile.limits.max_protocol_bytes + 2 * 1024 * 1024:
            overflowed = True
        decoded = line.decode("utf-8", errors="replace")
        if any(secret and secret in decoded for secret in request.profile.secret_values):
            errors.append("worker emitted unredacted credential material")
        decoded = redactor.text(decoded)
        try:
            record = json.loads(decoded, parse_constant=_reject_json_constant)
        except (json.JSONDecodeError, ValueError) as exc:
            errors.append(f"invalid worker JSON: {exc}")
            continue
        if not isinstance(record, dict) or record.get("protocol_version") != PROTOCOL_VERSION:
            errors.append("worker protocol version or record shape is invalid")
            continue
        record_type = record.get("type")
        if record_type == "event":
            raw_event = record.get("event")
            if not isinstance(raw_event, dict):
                errors.append("worker event is not an object")
                continue
            sequence = raw_event.get("sequence")
            method = raw_event.get("method")
            payload = raw_event.get("payload")
            if (
                sequence != expected_sequence
                or not isinstance(method, str)
                or not isinstance(payload, dict)
            ):
                errors.append("worker event ordering or shape is invalid")
                continue
            if on_first_progress is not None:
                on_first_progress(method)
            expected_sequence += 1
            if len(events) >= request.profile.limits.max_events:
                overflowed = True
                continue
            events.append(
                InvocationEvent(
                    sequence=sequence,
                    method=method,
                    payload=redactor.object(payload),
                )
            )
        elif record_type == "result":
            raw_result = record.get("result")
            if not isinstance(raw_result, dict):
                errors.append("worker result is not an object")
            elif result is not None:
                errors.append("worker emitted more than one terminal result")
            else:
                result = raw_result
        else:
            errors.append(f"unknown worker record type: {record_type!r}")
    return _StdoutCapture(events, result, errors, overflowed)


async def _capture_stderr(
    stream: asyncio.StreamReader | None,
    *,
    max_bytes: int,
    redactor: Redactor,
) -> str:
    if stream is None:
        return ""
    chunks: list[bytes] = []
    stored = 0
    while True:
        chunk = await stream.read(64 * 1024)
        if not chunk:
            break
        if stored < max_bytes:
            retained = chunk[: max_bytes - stored]
            chunks.append(retained)
            stored += len(retained)
    return redactor.text(b"".join(chunks).decode("utf-8", errors="replace"))


async def _finish_stdout_capture(task: asyncio.Task[_StdoutCapture]) -> _StdoutCapture:
    try:
        return await task
    except Exception as exc:
        return _StdoutCapture([], None, [f"stdout capture failed: {exc}"], False)


async def _finish_stderr_capture(task: asyncio.Task[str]) -> str:
    try:
        return await task
    except Exception:
        return ""


async def _terminate_process_tree(
    process: asyncio.subprocess.Process,
    *,
    grace_seconds: float,
) -> None:
    """Terminate a worker whether or not it owns a separate POSIX process group.

    Real SDK workers are launched in their own session, but the cancellation
    primitive is also used by recovery and must remain correct for a worker
    observed between ``create_subprocess_exec`` and session establishment.  In
    that race ``killpg(pid, ...)`` raises ``ProcessLookupError`` even though
    the direct child is still alive.  Falling back to the child signal keeps
    cancellation bounded rather than leaving the caller to wait for its full
    invocation timeout.
    """

    if process.returncode is not None:
        return

    def signal_process_tree(signal_value: int) -> None:
        if process.returncode is not None:
            return
        if os.name == "posix":
            try:
                os.killpg(process.pid, signal_value)
                return
            except ProcessLookupError:
                # The child can exist without a process group with its own
                # pid during startup.  Signal the direct child in that case.
                pass
        try:
            if signal_value == signal.SIGTERM:
                process.terminate()
            else:
                process.kill()
        except ProcessLookupError:
            return

    signal_process_tree(signal.SIGTERM)
    # Yield once so the asyncio child watcher can observe a signal sent during
    # subprocess startup before the bounded wait begins.
    await asyncio.sleep(0)
    try:
        await asyncio.wait_for(process.wait(), timeout=grace_seconds)
        return
    except TimeoutError:
        pass
    signal_process_tree(signal.SIGKILL)
    await asyncio.sleep(0)
    try:
        await asyncio.wait_for(process.wait(), timeout=grace_seconds)
    except TimeoutError:
        return


def _result_from_worker(
    request: InvocationRequest,
    *,
    raw: dict[str, Any],
    events: tuple[InvocationEvent, ...],
    worker_exit_code: int | None,
    started: float,
    redactor: Redactor,
) -> InvocationResult:
    try:
        status = InvocationStatus(str(raw.get("status")))
    except ValueError:
        return _local_failure(
            request,
            status=InvocationStatus.FAILED,
            code="worker_status_invalid",
            message=f"worker returned unknown status: {raw.get('status')!r}",
            started=started,
            events=events,
            worker_exit_code=worker_exit_code,
        )
    thread_id = raw.get("thread_id")
    session = None
    if isinstance(thread_id, str) and thread_id:
        session = InvocationSession(
            thread_id=thread_id,
            lineage_id=request.profile.lineage_id,
            workspace=request.profile.workspace,
            profile_hash=request.profile.profile_hash,
            codex_config_sha256=request.profile.codex_config_sha256,
        )
    elif status is InvocationStatus.COMPLETED:
        return _local_failure(
            request,
            status=InvocationStatus.FAILED,
            code="worker_thread_id_missing",
            message="completed worker result has no thread id",
            started=started,
            events=events,
            worker_exit_code=worker_exit_code,
        )

    raw_error = raw.get("error")
    invocation_error = None
    if isinstance(raw_error, dict):
        details = raw_error.get("details")
        invocation_error = InvocationError(
            code=str(raw_error.get("code") or "worker_error"),
            message=redactor.text(str(raw_error.get("message") or "worker error")),
            retryable=bool(raw_error.get("retryable", False)),
            details=redactor.object(details) if isinstance(details, dict) else {},
        )
    final_text = raw.get("final_text")
    if final_text is not None:
        final_text = redactor.text(str(final_text))
    structured_output: JsonValue | None = None
    if raw.get("structured_output") is not None:
        provider_output = json_compatible(redactor.value(raw["structured_output"]))
        transport = raw.get("structured_output_transport", "provider_schema")
        try:
            if transport == "provider_schema":
                structured_output = _decode_provider_json_ir(provider_output)
            elif transport == "json_envelope":
                structured_output = _decode_json_envelope(provider_output)
            else:
                raise ValueError("worker returned an unsupported structured output transport")
        except (TypeError, ValueError, json.JSONDecodeError):
            return _local_failure(
                request,
                status=InvocationStatus.FAILED,
                code="structured_output_transport_invalid",
                message="worker returned an invalid structured output transport envelope",
                started=started,
                events=events,
                worker_exit_code=worker_exit_code,
            )

    duration_ms = max(0, int((time.monotonic() - started) * 1000))
    return InvocationResult(
        invocation_id=request.invocation_id,
        status=status,
        session=session,
        turn_id=str(raw["turn_id"]) if raw.get("turn_id") is not None else None,
        final_text=final_text,
        structured_output=structured_output,
        usage=_parse_usage(raw.get("usage")),
        events=events,
        error=invocation_error,
        duration_ms=duration_ms,
        backend_version=(
            str(raw["backend_version"]) if raw.get("backend_version") is not None else None
        ),
        worker_exit_code=worker_exit_code,
    )


def _parse_usage(value: Any) -> InvocationUsage | None:
    if not isinstance(value, dict):
        return None
    return InvocationUsage(
        turn=_parse_breakdown(value.get("last")),
        thread_total=_parse_breakdown(value.get("total")),
        model_context_window=_optional_int(value.get("modelContextWindow")),
    )


def _parse_breakdown(value: Any) -> TokenBreakdown | None:
    if not isinstance(value, dict):
        return None
    return TokenBreakdown(
        cached_input_tokens=int(value.get("cachedInputTokens", 0)),
        input_tokens=int(value.get("inputTokens", 0)),
        output_tokens=int(value.get("outputTokens", 0)),
        reasoning_output_tokens=int(value.get("reasoningOutputTokens", 0)),
        total_tokens=int(value.get("totalTokens", 0)),
    )


def _optional_int(value: Any) -> int | None:
    return int(value) if isinstance(value, (int, float)) else None


def _local_failure(
    request: InvocationRequest,
    *,
    status: InvocationStatus,
    code: str,
    message: str,
    started: float,
    events: tuple[InvocationEvent, ...] = (),
    details: JsonObject | None = None,
    worker_exit_code: int | None = None,
    retryable: bool = False,
) -> InvocationResult:
    return InvocationResult(
        invocation_id=request.invocation_id,
        status=status,
        session=request.session,
        turn_id=None,
        final_text=None,
        structured_output=None,
        usage=None,
        events=events,
        error=InvocationError(
            code=code,
            message=message,
            retryable=retryable,
            details=details or {},
        ),
        duration_ms=int((time.monotonic() - started) * 1000),
        worker_exit_code=worker_exit_code,
    )
