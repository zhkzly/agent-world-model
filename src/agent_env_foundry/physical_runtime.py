"""Task-neutral uv materialization and private actor/state subprocesses."""

from __future__ import annotations

import hashlib
import json
import os
import select
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, TextIO, cast

from agent_env_foundry.environment import (
    JSONObject,
    JSONValue,
    ToolObservation,
    ToolSpec,
    invalid_arguments_observation,
    unknown_tool_observation,
    validate_observation,
    validate_tool_catalog,
)
from agent_env_foundry.jsonvalue import is_json_object, is_json_value
from agent_env_foundry.project_identity import (
    ProjectIdentityError,
    ProjectRole,
    compute_authored_project_digest,
    copy_authored_project,
)
from agent_env_foundry.release import canonical_bytes
from agent_env_foundry.schema import SchemaError, validate_instance
from agent_env_foundry.tree_manifest import tree_manifest

PreparationFailureKind = Literal[
    "EnvironmentDefect",
    "InfrastructureFailure",
    "CheckerDefect",
]
_PREPARATION_FAILURE_KINDS = frozenset(
    {
        "EnvironmentDefect",
        "InfrastructureFailure",
        "CheckerDefect",
    }
)
_PROJECT_ROLES = frozenset({"actor", "checker"})


class PreparationContractError(ValueError):
    """A caller or prepared value violates the physical runtime contract."""


class PreparationExecutionError(RuntimeError):
    """A project, infrastructure or child runtime failed closed."""

    def __init__(
        self,
        kind: PreparationFailureKind,
        code: str,
        message: str,
        **details: Any,
    ) -> None:
        super().__init__(message)
        if kind not in _PREPARATION_FAILURE_KINDS:
            raise ValueError("invalid preparation failure kind")
        self.kind = kind
        self.code = code
        self.details = details


@dataclass(frozen=True, slots=True)
class PreparationSettings:
    uv_cache_dir: Path
    command_timeout_seconds: float = 300.0

    def __post_init__(self) -> None:
        if self.command_timeout_seconds <= 0:
            raise ValueError("command_timeout_seconds must be positive")


@dataclass(frozen=True, slots=True)
class StateSnapshotEvent:
    seq: int
    request_digest: str
    response_digest: str
    before_tree_digest: str
    after_tree_digest: str

    def __post_init__(self) -> None:
        if self.seq <= 0:
            raise PreparationContractError("state snapshot seq must be positive")
        for name in (
            "request_digest",
            "response_digest",
            "before_tree_digest",
            "after_tree_digest",
        ):
            _digest(getattr(self, name), name)

    @property
    def unchanged(self) -> bool:
        return self.before_tree_digest == self.after_tree_digest

    def to_document(self) -> JSONObject:
        return {
            "seq": self.seq,
            "operation": "read_state",
            "request_digest": self.request_digest,
            "response_digest": self.response_digest,
            "before_tree_digest": self.before_tree_digest,
            "after_tree_digest": self.after_tree_digest,
            "unchanged": self.unchanged,
        }


@dataclass(frozen=True, slots=True)
class ProjectMaterializationInput:
    source_root: Path
    project_digest: str
    own_module: str
    forbidden_modules: tuple[str, ...]
    role: ProjectRole

    def __post_init__(self) -> None:
        _digest(self.project_digest, "materialized project_digest")
        if self.role not in _PROJECT_ROLES:
            raise ValueError("materialized project role is invalid")
        if not self.own_module or "." in self.own_module:
            raise ValueError("materialized own_module must be one top-level module")
        if (
            not self.forbidden_modules
            or len(set(self.forbidden_modules)) != len(self.forbidden_modules)
            or any(not item or "." in item for item in self.forbidden_modules)
            or self.own_module in self.forbidden_modules
        ):
            raise ValueError("materialized forbidden_modules are invalid")


@dataclass(frozen=True, slots=True)
class RuntimeLock:
    project_root: Path
    project_digest: str
    python: Path
    own_module: str
    forbidden_modules: tuple[str, ...]
    role: ProjectRole


class _ChildTransport:
    def __init__(
        self,
        python: Path,
        runner: Path,
        arguments: tuple[str, ...],
        *,
        cwd: Path,
        timeout: float,
        role: Literal["actor", "checker"],
    ) -> None:
        environment = dict(os.environ)
        for name in ("VIRTUAL_ENV", "PYTHONPATH", "PYTHONHOME"):
            environment.pop(name, None)
        self._process = subprocess.Popen(
            (str(python), "-I", "-B", str(runner), *arguments),
            cwd=cwd,
            env=environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        if (
            self._process.stdin is None
            or self._process.stdout is None
            or self._process.stderr is None
        ):
            raise PreparationExecutionError(
                "InfrastructureFailure", "child_pipe_missing", "child pipes unavailable"
            )
        self._stdin = cast(TextIO, self._process.stdin)
        self._stdout = cast(TextIO, self._process.stdout)
        self._stderr = cast(TextIO, self._process.stderr)
        self._next_seq = 1
        self._timeout = timeout
        self._role = role
        self._closed = False

    def call(self, operation: str, arguments: JSONObject) -> JSONValue:
        if self._closed:
            raise PreparationExecutionError(
                "InfrastructureFailure", "child_closed", "child is closed"
            )
        seq = self._next_seq
        self._next_seq += 1
        request = {"seq": seq, "op": operation, "args": arguments}
        try:
            self._stdin.write(json.dumps(request, ensure_ascii=False, sort_keys=True) + "\n")
            self._stdin.flush()
            ready, _, _ = select.select([self._stdout], [], [], self._timeout)
            if not ready:
                self._process.kill()
                self._process.wait()
                raise self._failure("child_timeout", None)
            line = self._stdout.readline()
        except (BrokenPipeError, OSError) as exc:
            raise self._failure("child_transport_failed", exc) from exc
        if not line:
            raise self._failure("child_exited", None)
        try:
            response = json.loads(line)
        except json.JSONDecodeError as exc:
            raise self._failure("child_response_invalid", exc) from exc
        if not isinstance(response, dict) or response.get("seq") != seq:
            raise self._failure("child_sequence_mismatch", None)
        if response.get("ok") is True and set(response) == {"seq", "ok", "value"}:
            value = response["value"]
            if not is_json_value(value):
                raise self._failure("child_value_not_json", None)
            return cast(JSONValue, value)
        if response.get("ok") is False and set(response) == {"seq", "ok", "error"}:
            error = response["error"]
            message = error.get("message") if isinstance(error, dict) else str(error)
            raise PreparationExecutionError(
                _child_defect(self._role),
                "child_call_failed",
                f"child {operation} failed: {message}",
                operation=operation,
                error=error,
            )
        raise self._failure("child_response_shape", None)

    def close(self, *, operation: str | None = None) -> None:
        if self._closed:
            return
        if operation is not None and self._process.poll() is None:
            try:
                self.call(operation, {})
            except PreparationExecutionError:
                pass
        self._closed = True
        try:
            self._stdin.close()
        except (BrokenPipeError, OSError):
            pass
        try:
            self._process.wait(timeout=self._timeout)
        except subprocess.TimeoutExpired:
            self._process.kill()
            self._process.wait()

    def _failure(self, code: str, cause: Exception | None) -> PreparationExecutionError:
        status = self._process.poll()
        stderr = self._stderr.read() if status is not None else ""
        if code in {"child_exited", "child_transport_failed"} and self._next_seq == 2:
            kind: PreparationFailureKind = _child_defect(self._role)
            code = "child_startup_failed"
        else:
            kind = "InfrastructureFailure"
        return PreparationExecutionError(
            kind,
            code,
            f"child transport failed ({code})",
            returncode=status,
            stderr=stderr,
            cause=f"{type(cause).__name__}: {cause}" if cause else None,
        )


class StateSnapshotProxy:
    """Host-only, task-neutral state readback over one frozen actor project."""

    def __init__(
        self,
        transport: _ChildTransport,
        *,
        state_schema: JSONObject,
        events: list[StateSnapshotEvent],
    ) -> None:
        self._transport = transport
        self._state_schema = state_schema
        self._events = events
        self._accepted_by_tree: dict[str, str] = {}

    def read(self, instance_directory: Path) -> JSONValue:
        requested = Path(instance_directory)
        if requested.is_symlink() or not requested.is_dir():
            raise PreparationContractError(
                "state snapshot instance_directory must be a real directory"
            )
        instance = requested.resolve()
        before = tree_manifest(instance)
        failure: PreparationExecutionError | None = None
        try:
            value = self._transport.call("read", {"instance_directory": str(instance)})
            response_document: JSONValue = value
        except PreparationExecutionError as exc:
            failure = exc
            response_document = {"kind": exc.kind, "code": exc.code, "message": str(exc)}
            value = None
        after = tree_manifest(instance)
        response_digest = _sha(canonical_bytes(response_document))
        event = StateSnapshotEvent(
            len(self._events) + 1,
            _sha(canonical_bytes({"before_tree_digest": before.digest})),
            response_digest,
            before.digest,
            after.digest,
        )
        self._events.append(event)
        if not event.unchanged:
            raise PreparationExecutionError(
                "EnvironmentDefect",
                "state_snapshot_mutation",
                "protected state reader mutated the native instance",
            ) from failure
        if failure is not None:
            raise failure
        try:
            validate_instance(value, self._state_schema, role="protected state snapshot")
        except SchemaError as exc:
            raise PreparationExecutionError(
                "EnvironmentDefect", "state_snapshot_schema", str(exc)
            ) from exc
        previous = self._accepted_by_tree.setdefault(before.digest, response_digest)
        if previous != response_digest:
            raise PreparationExecutionError(
                "EnvironmentDefect",
                "state_snapshot_nondeterministic",
                "unchanged native bytes produced different protected state snapshots",
            )
        return value

    def close(self) -> None:
        self._transport.close(operation="close")


class ActorProxy:
    def __init__(
        self,
        transport: _ChildTransport,
        *,
        start_schema: JSONObject,
        reset_observation_schema: JSONObject,
    ) -> None:
        self._transport = transport
        self._start_schema = start_schema
        self._reset_schema = reset_observation_schema

    def reset(self, start: JSONObject | None = None) -> JSONValue:
        if start is not None:
            try:
                validate_instance(start, self._start_schema, role="reset start")
            except SchemaError as exc:
                raise PreparationContractError(str(exc)) from exc
        value = self._transport.call("reset", {"start": start})
        try:
            validate_instance(value, self._reset_schema, role="reset observation")
        except SchemaError as exc:
            raise PreparationExecutionError("EnvironmentDefect", "reset_schema", str(exc)) from exc
        return value

    def tools(self) -> tuple[ToolSpec, ...]:
        raw = self._transport.call("tools", {})
        if not isinstance(raw, list):
            raise PreparationExecutionError(
                "EnvironmentDefect", "tools_shape", "tools must be an array"
            )
        try:
            return tuple(validate_tool_catalog(tuple(raw), role="prepared tools").values())
        except Exception as exc:
            raise PreparationExecutionError("EnvironmentDefect", "tools_invalid", str(exc)) from exc

    def invoke(self, tool_name: str, arguments: JSONObject) -> ToolObservation:
        if not isinstance(tool_name, str) or not is_json_object(arguments):
            return invalid_arguments_observation("tool_name/arguments are invalid")
        catalog = {item["name"]: item for item in self.tools()}
        spec = catalog.get(tool_name)
        if spec is None:
            return unknown_tool_observation(tool_name)
        try:
            validate_instance(arguments, spec["input_schema"], role=f"tool {tool_name!r} arguments")
        except SchemaError as exc:
            return invalid_arguments_observation(str(exc), tool_name=tool_name)
        raw = self._transport.call("invoke", {"tool_name": tool_name, "arguments": arguments})
        if not is_json_object(raw):
            raise PreparationExecutionError(
                "EnvironmentDefect", "observation_shape", "observation must be an object"
            )
        observation = cast(ToolObservation, raw)
        try:
            validate_observation(observation, spec, role=f"prepared invoke {tool_name!r}")
        except Exception as exc:
            raise PreparationExecutionError(
                "EnvironmentDefect", "observation_invalid", str(exc)
            ) from exc
        return observation

    def close(self) -> None:
        self._transport.close(operation="close")


def materialize_project(
    project_input: ProjectMaterializationInput,
    runtime_root: Path,
    *,
    settings: PreparationSettings,
) -> RuntimeLock:
    if project_input.source_root.is_symlink():
        raise PreparationExecutionError(
            _role_defect(project_input.role),
            "source_project_symlink",
            "source project root must not be a symlink",
        )
    source = project_input.source_root.resolve()
    actual_source_digest = _project_source_digest(source, project_input.role)
    if actual_source_digest != project_input.project_digest:
        raise PreparationExecutionError(
            _role_defect(project_input.role),
            "source_project_digest_mismatch",
            "source project differs from its accepted project identity",
            expected=project_input.project_digest,
            actual=actual_source_digest,
        )
    project = runtime_root / "project"
    if not runtime_root.exists():
        runtime_root.parent.mkdir(parents=True, exist_ok=True)
        temporary = runtime_root.parent / f".{runtime_root.name}.{uuid.uuid4().hex}.tmp"
        try:
            copied_digest = copy_authored_project(
                source,
                temporary / "project",
                project_input.role,
            )
            if copied_digest != project_input.project_digest:
                raise PreparationExecutionError(
                    _role_defect(project_input.role),
                    "copied_project_digest_mismatch",
                    "copied project differs from its accepted project identity",
                    expected=project_input.project_digest,
                    actual=copied_digest,
                )
            temporary.rename(runtime_root)
            _run_uv_sync(project, settings)
        except Exception as exc:
            if runtime_root.exists():
                shutil.rmtree(runtime_root)
            elif temporary.exists():
                shutil.rmtree(temporary)
            if isinstance(exc, ProjectIdentityError):
                raise PreparationExecutionError(
                    _role_defect(project_input.role),
                    exc.code,
                    str(exc),
                    path=exc.path,
                ) from exc
            raise
    python = project / ".venv/bin/python"
    lock = RuntimeLock(
        project,
        project_input.project_digest,
        python,
        project_input.own_module,
        project_input.forbidden_modules,
        project_input.role,
    )
    _verify_runtime(lock, settings.command_timeout_seconds)
    return lock


def read_actor_tool_catalog(
    project_input: ProjectMaterializationInput,
    runtime_root: Path,
    *,
    factory: str,
    settings: PreparationSettings,
) -> tuple[ToolSpec, ...]:
    lock = materialize_project(project_input, runtime_root, settings=settings)
    probe_instance = runtime_root / "probe-instance"
    probe_instance.mkdir(parents=True, exist_ok=True)
    transport = _ChildTransport(
        lock.python,
        Path(__file__).resolve().parent / "_actor_runner.py",
        (factory, str(probe_instance)),
        cwd=lock.project_root,
        timeout=settings.command_timeout_seconds,
        role="actor",
    )
    try:
        raw = transport.call("tools", {})
    finally:
        transport.close(operation="close")
    if not isinstance(raw, list):
        raise PreparationExecutionError(
            "EnvironmentDefect",
            "actor_tools_invalid",
            "materialized actor tools response is not an array",
        )
    return tuple(validate_tool_catalog(tuple(raw), role="materialized actor tools").values())


def _run_uv_sync(project: Path, settings: PreparationSettings) -> None:
    environment = dict(os.environ)
    for name in ("VIRTUAL_ENV", "PYTHONPATH", "PYTHONHOME"):
        environment.pop(name, None)
    environment["UV_CACHE_DIR"] = str(Path(settings.uv_cache_dir).resolve())
    try:
        result = subprocess.run(
            ("uv", "sync", "--frozen", "--all-groups", "--link-mode", "copy"),
            cwd=project,
            env=environment,
            text=True,
            capture_output=True,
            timeout=settings.command_timeout_seconds,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PreparationExecutionError(
            "InfrastructureFailure", "uv_sync_unavailable", f"uv sync could not run: {exc}"
        ) from exc
    if result.returncode:
        raise PreparationExecutionError(
            "InfrastructureFailure",
            "uv_sync_failed",
            "locked uv sync failed",
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
        )


def _probe_origin(python: Path, project: Path, module: str, timeout: float) -> Path | None:
    result = subprocess.run(
        (
            str(python),
            "-I",
            "-B",
            "-c",
            "import importlib.util,sys;spec=importlib.util.find_spec(sys.argv[1]);"
            "print(spec.origin if spec and spec.origin else '')",
            module,
        ),
        cwd=project,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode or not result.stdout.strip():
        return None
    return Path(result.stdout.strip())


def _verify_runtime(lock: RuntimeLock, timeout: float) -> None:
    if lock.project_root.is_symlink() or not lock.project_root.is_dir():
        raise PreparationExecutionError(
            _role_defect(lock.role), "prepared_project_missing", "prepared project is missing"
        )
    actual = _project_source_digest(lock.project_root, lock.role)
    if actual != lock.project_digest:
        raise PreparationExecutionError(
            _role_defect(lock.role),
            "prepared_project_tampered",
            "prepared project digest differs",
            expected=lock.project_digest,
            actual=actual,
        )
    if not lock.python.exists() or not lock.python.resolve().is_file():
        raise PreparationExecutionError(
            "InfrastructureFailure", "prepared_python_missing", "prepared Python is missing"
        )
    try:
        own_origin = _probe_origin(lock.python, lock.project_root, lock.own_module, timeout)
        forbidden_origins = {
            module: _probe_origin(lock.python, lock.project_root, module, timeout)
            for module in lock.forbidden_modules
        }
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PreparationExecutionError(
            "InfrastructureFailure", "runtime_import_probe_failed", str(exc)
        ) from exc
    expected_source = (lock.project_root / "src").resolve()
    if own_origin is None or not own_origin.resolve().is_relative_to(expected_source):
        raise PreparationExecutionError(
            _role_defect(lock.role),
            "runtime_package_origin_invalid",
            f"runtime package {lock.own_module} is not bound to prepared source",
            origin=str(own_origin) if own_origin else None,
        )
    visible = {
        module: str(origin) for module, origin in forbidden_origins.items() if origin is not None
    }
    if visible:
        raise PreparationExecutionError(
            _role_defect(lock.role),
            "runtime_import_leak",
            "runtime can import forbidden packages",
            origins=visible,
        )


def _project_source_digest(project: Path, role: ProjectRole) -> str:
    try:
        return compute_authored_project_digest(project, role, require_locked_project=True)
    except ProjectIdentityError as exc:
        raise PreparationExecutionError(
            _role_defect(role), exc.code, str(exc), path=exc.path
        ) from exc


def _role_defect(role: ProjectRole) -> PreparationFailureKind:
    if role == "actor":
        return "EnvironmentDefect"
    return "CheckerDefect"


def _child_defect(role: Literal["actor", "checker"]) -> PreparationFailureKind:
    if role == "actor":
        return "EnvironmentDefect"
    return "CheckerDefect"


def _module_name(reference: str) -> str:
    return reference.partition(":")[0].partition(".")[0]


def _digest(value: str, role: str) -> None:
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise PreparationContractError(f"{role} must be a sha256 digest")


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


__all__ = [
    "ActorProxy",
    "PreparationContractError",
    "PreparationExecutionError",
    "PreparationFailureKind",
    "PreparationSettings",
    "ProjectMaterializationInput",
    "RuntimeLock",
    "StateSnapshotEvent",
    "StateSnapshotProxy",
    "_ChildTransport",
    "_module_name",
    "_probe_origin",
    "_verify_runtime",
    "materialize_project",
    "read_actor_tool_catalog",
]
