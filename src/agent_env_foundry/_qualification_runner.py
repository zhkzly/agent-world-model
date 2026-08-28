"""Private Qualification runner that owns canonical environment-call journals."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import select
import shutil
import signal
import stat
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol, TextIO, cast

import rfc8785

from agent_env_foundry.environment import ValidatedEnvironment
from agent_env_foundry.errors import EnvironmentContractError
from agent_env_foundry.release import (
    canonical_bytes,
    compute_payload_digest,
    parse_descriptor,
    parse_manifest,
    verify_release,
)

type Operation = Literal["open", "reset", "tools", "invoke", "close"]

_OPERATIONS = frozenset({"open", "reset", "tools", "invoke", "close"})
_SESSION_TOKEN = object()
_ENVIRONMENT_TOKEN = object()
_JOURNAL_ORIGIN = object()
_CARRIER_ORIGIN = object()
_CHILD_TIMEOUT_SECONDS = 10.0


class CandidateExecutionFailure(RuntimeError):
    """A canonical environment load/call failed inside a Qualifier probe."""

    def __init__(
        self,
        cause: Exception | None = None,
        *,
        error_type: str | None = None,
        message: str | None = None,
    ) -> None:
        if cause is None and (not error_type or message is None):
            raise TypeError("remote Candidate failure requires error_type and message")
        super().__init__(str(cause) if cause is not None else message)
        self.error_type = type(cause).__name__ if cause is not None else cast(str, error_type)


class RunnerInfrastructureFailure(RuntimeError):
    """The private Candidate transport failed independently of domain behavior."""


@dataclass(frozen=True, slots=True)
class _SandboxContext:
    codex_binary: Path
    codex_home: Path
    candidate_root: Path
    qualification_root: Path


def _sandbox_command(
    context: _SandboxContext,
    *,
    profile: str,
    cwd: Path,
    entries: Sequence[tuple[Path, str]],
    inner: Sequence[str],
) -> tuple[str, ...]:
    filesystem = (
        "{"
        + ",".join(f'{json.dumps(str(path.resolve()))}="{access}"' for path, access in entries)
        + "}"
    )
    overrides = (
        f'default_permissions="{profile}"',
        f'permissions.{profile}.extends=":read-only"',
        f"permissions.{profile}.filesystem={filesystem}",
        f"permissions.{profile}.network.enabled=false",
    )
    command = [str(context.codex_binary), "sandbox", "-C", str(cwd.resolve())]
    for override in overrides:
        command.extend(("-c", override))
    command.extend(("-P", profile, *inner))
    return tuple(command)


def _candidate_private_paths(
    context: _SandboxContext,
    release: Path,
    instances: Path,
    dependencies: Path,
) -> tuple[Path, ...]:
    qualification = context.qualification_root.resolve()
    candidate = context.candidate_root.resolve()
    private: set[Path] = set()
    for child in candidate.iterdir():
        if child.name != ".venv":
            private.add(child.resolve())
    for sibling in candidate.parent.iterdir():
        resolved = sibling.resolve()
        if resolved not in {candidate, qualification}:
            private.add(resolved)
    if qualification.is_dir():
        for child in qualification.iterdir():
            if child.name != "runtime":
                private.add(child.resolve())
    runtime = qualification / "runtime"
    if runtime.is_dir():
        release_root = release.resolve()
        instance_root = instances.resolve()
        dependency_root = dependencies.resolve()
        for path in runtime.rglob("*"):
            if not path.is_file():
                continue
            resolved = path.resolve()
            if any(
                resolved.is_relative_to(root)
                for root in (release_root, instance_root, dependency_root)
            ):
                continue
            private.add(resolved)
    return tuple(sorted(private))


def _probe_denied_paths(
    context: _SandboxContext,
    release: Path,
    instances: Path,
) -> tuple[Path, ...]:
    requested = {
        context.candidate_root.parent.resolve(),
        context.qualification_root.resolve(),
        release.resolve(),
        instances.resolve(),
    }
    selected: list[Path] = []
    for path in sorted(requested, key=lambda item: (len(item.parts), str(item))):
        if not any(path.is_relative_to(parent) for parent in selected):
            selected.append(path)
    return tuple(selected)


class _EnvironmentHandle(Protocol):
    def reset(self, start: dict[str, Any] | None = None) -> Any: ...
    def tools(self) -> tuple[Any, ...]: ...
    def invoke(self, tool_name: str, arguments: dict[str, Any]) -> Any: ...
    def close(self) -> None: ...


class _CandidateActorTransport:
    """Host-side private transport to one Candidate-only interpreter."""

    def __init__(
        self,
        actor_python: Path,
        factory: str,
        source_root: Path,
        release: Path,
        instance: Path,
        dependencies: Path,
        sandbox: _SandboxContext | None,
    ) -> None:
        runner = Path(__file__).resolve().with_name("_qualification_actor_runner.py")
        environment = {
            name: os.environ[name]
            for name in ("PATH", "LANG", "LC_ALL", "TZ")
            if name in os.environ
        }
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        inner = (
            str(actor_python),
            "-I",
            "-B",
            str(runner),
            factory,
            str(source_root.resolve()),
            str(instance.resolve()),
            str(dependencies.resolve()),
        )
        command: tuple[str, ...] = inner
        if sandbox is not None:
            command = _sandbox_command(
                sandbox,
                profile="foundry_candidate_actor",
                cwd=release,
                entries=(
                    *(
                        (path, "deny")
                        for path in _candidate_private_paths(
                            sandbox,
                            release,
                            instance,
                            dependencies,
                        )
                    ),
                    (instance.parent.resolve(), "deny"),
                    (instance.resolve(), "write"),
                ),
                inner=inner,
            )
            environment["CODEX_HOME"] = str(sandbox.codex_home)
        self._process = subprocess.Popen(
            command,
            cwd=release,
            env=environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=sys.stderr,
            close_fds=True,
            start_new_session=True,
            text=True,
            bufsize=1,
        )
        if self._process.stdin is None or self._process.stdout is None:
            self._process.kill()
            self._process.wait()
            raise RunnerInfrastructureFailure("Candidate child pipes are unavailable")
        self._stdin = cast(TextIO, self._process.stdin)
        self._stdout = cast(TextIO, self._process.stdout)
        self._next_seq = 1
        self._closed = False
        ready = self._read_response()
        if ready != {"type": "ready", "ok": True}:
            self.abort()
            self._raise_remote(ready)

    def call(self, operation: str, arguments: dict[str, Any]) -> Any:
        if self._closed:
            raise RuntimeError("Candidate child is closed")
        seq = self._next_seq
        self._next_seq += 1
        try:
            self._stdin.write(
                json.dumps(
                    {"seq": seq, "op": operation, "args": arguments},
                    ensure_ascii=False,
                    sort_keys=True,
                )
                + "\n"
            )
            self._stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise RunnerInfrastructureFailure("Candidate child transport failed") from exc
        response = self._read_response()
        if not isinstance(response, dict) or response.get("seq") != seq:
            raise RunnerInfrastructureFailure("Candidate child returned an invalid sequence")
        if response.get("ok") is True and set(response) == {"seq", "ok", "value"}:
            return response["value"]
        self._raise_remote(response)

    def close(self) -> None:
        if self._closed:
            return
        try:
            self.call("close", {})
            self._stdin.close()
            status = self._process.wait(timeout=_CHILD_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired as exc:
            self._force_stop()
            raise RunnerInfrastructureFailure("Candidate child did not exit after close") from exc
        except Exception:
            self._force_stop()
            raise
        finally:
            self._closed = True
        descendants = self._kill_process_group()
        if status != 0:
            raise RunnerInfrastructureFailure(f"Candidate child exited {status}")
        if descendants:
            raise RunnerInfrastructureFailure("Candidate child left running descendants")

    def abort(self) -> None:
        self._closed = True
        try:
            self._stdin.close()
        except (BrokenPipeError, OSError):
            pass
        self._force_stop()

    def _force_stop(self) -> None:
        self._kill_process_group()
        if self._process.poll() is None:
            self._process.kill()
        self._process.wait()

    def _kill_process_group(self) -> bool:
        try:
            os.killpg(self._process.pid, signal.SIGKILL)
        except ProcessLookupError:
            return False
        return True

    def _read_response(self) -> Any:
        ready, _, _ = select.select([self._stdout], [], [], _CHILD_TIMEOUT_SECONDS)
        if not ready:
            self.abort()
            raise RunnerInfrastructureFailure("Candidate child timed out")
        line = self._stdout.readline()
        if not line:
            status = self._process.poll()
            raise RunnerInfrastructureFailure(f"Candidate child exited before replying ({status})")
        try:
            return json.loads(line)
        except json.JSONDecodeError as exc:
            raise RunnerInfrastructureFailure("Candidate child returned invalid JSON") from exc

    @staticmethod
    def _raise_remote(response: Any) -> None:
        error = response.get("error") if isinstance(response, dict) else None
        if not isinstance(error, dict):
            raise RunnerInfrastructureFailure("Candidate child returned an invalid failure")
        error_type = error.get("type")
        message = error.get("message")
        if (
            error.get("owner") != "candidate"
            or not isinstance(error_type, str)
            or not isinstance(message, str)
        ):
            raise RunnerInfrastructureFailure("Candidate child returned an invalid error object")
        raise CandidateExecutionFailure(error_type=error_type, message=message)


class _CandidateEnvironmentProxy:
    def __init__(self, transport: _CandidateActorTransport) -> None:
        self._transport = transport

    def reset(self, start: Any = None) -> Any:
        return self._transport.call("reset", {"start": start})

    def tools(self) -> tuple[Any, ...]:
        value = self._transport.call("tools", {})
        if not isinstance(value, list):
            raise CandidateExecutionFailure(
                error_type="EnvironmentRuntimeError",
                message="Candidate child tools response is not an array",
            )
        return tuple(value)

    def invoke(self, tool_name: Any, arguments: Any) -> Any:
        return self._transport.call(
            "invoke",
            {"tool_name": tool_name, "arguments": arguments},
        )

    def close(self) -> None:
        self._transport.close()


@dataclass(frozen=True, slots=True)
class JournalEvent:
    run_id: str
    seq: int
    instance: str
    operation: Operation
    arguments: dict[str, Any]
    result: Any

    def to_document(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class HostJournal:
    run_id: str
    events: tuple[JournalEvent, ...]
    digest: str
    _origin: object = field(repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class TreeRecord:
    path: str
    object_type: str
    mode: int
    digest: str | None = None
    symlink_target: str | None = None

    def to_document(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class TreeManifest:
    records: tuple[TreeRecord, ...]
    digest: str

    def to_document(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ControlledRunCarrier:
    run_id: str
    release_root: Path
    instance_root: Path
    release_before: TreeManifest
    release_after: TreeManifest
    instance_before: TreeManifest
    instance_after: TreeManifest
    journal: HostJournal
    original_candidate_digest: str
    executed_copy_digest: str
    _origin: object = field(repr=False, compare=False)

    def to_document(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "release_root": str(self.release_root),
            "instance_root": str(self.instance_root),
            "release_before": self.release_before.to_document(),
            "release_after": self.release_after.to_document(),
            "instance_before": self.instance_before.to_document(),
            "instance_after": self.instance_after.to_document(),
            "journal_digest": self.journal.digest,
            "original_candidate_digest": self.original_candidate_digest,
            "executed_copy_digest": self.executed_copy_digest,
        }


class RecordedEnvironment:
    """Canonical Environment wrapper whose only extra behavior is Host journaling."""

    __slots__ = ("__closed", "__environment", "__instance_key", "__on_close", "__recorder")

    def __init__(
        self,
        token: object,
        environment: _EnvironmentHandle,
        instance_key: str,
        recorder: _JournalRecorder,
        on_close: Callable[[str], None],
    ) -> None:
        if token is not _ENVIRONMENT_TOKEN:
            raise TypeError("RecordedEnvironment is created only by ProbeSession")
        self.__environment = environment
        self.__instance_key = instance_key
        self.__recorder = recorder
        self.__on_close = on_close
        self.__closed = False

    def reset(self, start: dict[str, Any] | None = None) -> Any:
        self.__require_open()
        return self.__forward(
            "reset",
            {"start": start},
            lambda: self.__environment.reset(start),
        )

    def tools(self) -> tuple[Any, ...]:
        self.__require_open()
        return cast(
            tuple[Any, ...],
            self.__forward("tools", {}, self.__environment.tools),
        )

    def invoke(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        self.__require_open()
        return self.__forward(
            "invoke",
            {"tool_name": tool_name, "arguments": arguments},
            lambda: self.__environment.invoke(tool_name, arguments),
        )

    def close(self) -> None:
        self.__require_open()
        self.__forward("close", {}, self.__environment.close)
        self.__closed = True
        self.__on_close(self.__instance_key)

    def __require_open(self) -> None:
        if self.__closed:
            raise RuntimeError("closed environment handle cannot be reused")

    def __forward(
        self,
        operation: Operation,
        arguments: dict[str, Any],
        call: Callable[[], Any],
    ) -> Any:
        try:
            result = call()
        except RunnerInfrastructureFailure as exc:
            self.__recorder.record(
                self.__instance_key,
                operation,
                arguments,
                {
                    "host_infrastructure_exception": {
                        "type": type(exc).__name__,
                    }
                },
            )
            raise
        except CandidateExecutionFailure as exc:
            self.__recorder.record(
                self.__instance_key,
                operation,
                arguments,
                {
                    "host_exception": {
                        "type": exc.error_type,
                        "message": str(exc),
                    }
                },
            )
            raise
        except EnvironmentContractError as exc:
            self.__recorder.record(
                self.__instance_key,
                operation,
                arguments,
                {
                    "host_exception": {
                        "type": type(exc).__name__,
                        "message": str(exc),
                    }
                },
            )
            raise
        except Exception as exc:
            infrastructure = _exception_cause(exc, RunnerInfrastructureFailure)
            if infrastructure is not None:
                self.__recorder.record(
                    self.__instance_key,
                    operation,
                    arguments,
                    {
                        "host_infrastructure_exception": {
                            "type": type(infrastructure).__name__,
                        }
                    },
                )
                raise infrastructure from exc
            self.__recorder.record(
                self.__instance_key,
                operation,
                arguments,
                {
                    "host_exception": {
                        "type": type(exc).__name__,
                        "message": str(exc),
                    }
                },
            )
            raise CandidateExecutionFailure(exc) from exc
        self.__recorder.record(
            self.__instance_key,
            operation,
            arguments,
            result,
        )
        return result


class ProbeSession:
    """The complete surface supplied to a Qualifier-authored public probe."""

    __slots__ = ("__open_environment",)

    def __init__(
        self,
        token: object,
        open_environment: Callable[[str], RecordedEnvironment],
    ) -> None:
        if token is not _SESSION_TOKEN:
            raise TypeError("ProbeSession is Host-created")
        self.__open_environment = open_environment

    def open(self, instance_key: str) -> RecordedEnvironment:
        return self.__open_environment(instance_key)


class _JournalRecorder:
    def __init__(self, path: Path | None, run_id: str) -> None:
        if not isinstance(run_id, str) or not run_id:
            raise ValueError("run_id must be a non-empty string")
        self._stream: Any | None = None
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            self._stream = os.fdopen(descriptor, "wb")
        self._run_id = run_id
        self._next_seq = 1
        self._payload = bytearray()

    def record(
        self,
        instance: str,
        operation: Operation,
        arguments: dict[str, Any],
        result: Any,
    ) -> None:
        event = JournalEvent(
            run_id=self._run_id,
            seq=self._next_seq,
            instance=instance,
            operation=operation,
            arguments=cast(dict[str, Any], _json_copy(arguments)),
            result=_json_copy(result),
        )
        encoded = rfc8785.dumps(event.to_document()) + b"\n"
        self._payload.extend(encoded)
        if self._stream is not None:
            self._stream.write(encoded)
            self._stream.flush()
        self._next_seq += 1

    def close(self) -> None:
        if self._stream is not None:
            self._stream.close()

    @property
    def payload(self) -> bytes:
        return bytes(self._payload)


def _create_probe_session(
    release_path: Path,
    instances_root: Path,
    run_id: str,
    journal_path: Path | None,
    dependencies_root: Path | None = None,
    actor_python: Path | None = None,
    sandbox: _SandboxContext | None = None,
) -> tuple[
    ProbeSession,
    _JournalRecorder,
    Callable[[], None],
    Callable[[], None],
]:
    release = release_path.resolve()
    verified = verify_release(release)
    instances = instances_root.resolve()
    dependencies = (
        Path(dependencies_root).resolve()
        if dependencies_root is not None
        else Path(__file__).resolve().parents[1]
    )
    python = Path(actor_python).absolute() if actor_python is not None else Path(sys.executable)
    instances.mkdir(parents=True, exist_ok=True)
    recorder = _JournalRecorder(journal_path, run_id)
    active_instances: set[str] = set()
    active_transports: dict[str, _CandidateActorTransport] = {}

    def open_environment(instance_key: str) -> RecordedEnvironment:
        _validate_instance_key(instance_key)
        if instance_key in active_instances:
            raise RuntimeError("instance already has an active environment handle")
        instance_path = instances / instance_key
        instance_path.mkdir(parents=True, exist_ok=True)
        transport: _CandidateActorTransport | None = None
        try:
            transport = _CandidateActorTransport(
                python,
                verified.descriptor.environment_factory,
                release / "src",
                release,
                instance_path,
                dependencies,
                sandbox,
            )
            environment = ValidatedEnvironment(
                _CandidateEnvironmentProxy(transport),
                start_schema=verified.start_schema,
                reset_observation_schema=verified.reset_observation_schema,
            )
        except RunnerInfrastructureFailure:
            if transport is not None:
                transport.abort()
            raise
        except Exception as exc:
            if transport is not None:
                transport.abort()
            infrastructure = _exception_cause(exc, RunnerInfrastructureFailure)
            if infrastructure is not None:
                raise infrastructure from exc
            failure = (
                exc
                if isinstance(exc, CandidateExecutionFailure)
                else CandidateExecutionFailure(exc)
            )
            recorder.record(
                instance_key,
                "open",
                {},
                {
                    "host_exception": {
                        "type": failure.error_type,
                        "message": str(failure),
                    }
                },
            )
            raise failure from exc
        recorder.record(instance_key, "open", {}, {"attached": True})
        active_instances.add(instance_key)
        active_transports[instance_key] = transport

        def mark_closed(key: str) -> None:
            active_instances.discard(key)
            active_transports.pop(key, None)

        return RecordedEnvironment(
            _ENVIRONMENT_TOKEN,
            environment,
            instance_key,
            recorder,
            mark_closed,
        )

    def cleanup() -> None:
        for transport in tuple(active_transports.values()):
            transport.abort()
        active_transports.clear()
        active_instances.clear()

    def assert_closed() -> None:
        if active_instances:
            raise RuntimeError(
                "public probe returned with active environment handles: "
                + ", ".join(sorted(active_instances))
            )

    return ProbeSession(_SESSION_TOKEN, open_environment), recorder, cleanup, assert_closed


def _run_public_probe(
    probe_path: Path,
    release_path: Path,
    instances_root: Path,
    run_id: str,
    journal_path: Path,
    mode: str,
) -> None:
    _run_public_probe_source(
        probe_path.read_text(encoding="utf-8"),
        release_path,
        instances_root,
        run_id,
        journal_path,
        mode,
    )


def _run_public_probe_source(
    probe_source: str,
    release_path: Path,
    instances_root: Path,
    run_id: str,
    journal_path: Path | None,
    mode: str,
    dependencies_root: Path | None = None,
    actor_python: Path | None = None,
    sandbox: _SandboxContext | None = None,
) -> bytes:
    session, recorder, cleanup, assert_closed = _create_probe_session(
        release_path,
        instances_root,
        run_id,
        journal_path,
        dependencies_root,
        actor_python,
        sandbox,
    )
    probe_runner = Path(__file__).resolve().with_name("_qualification_probe_runner.py")
    inner = (str(Path(sys.executable).absolute()), "-I", "-B", str(probe_runner))
    command: tuple[str, ...] = inner
    environment = {
        name: os.environ[name] for name in ("PATH", "LANG", "LC_ALL", "TZ") if name in os.environ
    }
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    if sandbox is not None:
        command = _sandbox_command(
            sandbox,
            profile="foundry_public_probe",
            cwd=probe_runner.parent,
            entries=tuple(
                (path, "deny")
                for path in _probe_denied_paths(
                    sandbox,
                    Path(release_path),
                    Path(instances_root),
                )
            ),
            inner=inner,
        )
        environment["CODEX_HOME"] = str(sandbox.codex_home)
    process = subprocess.Popen(
        command,
        cwd=probe_runner.parent,
        env=environment,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=sys.stderr,
        close_fds=True,
        text=True,
        bufsize=1,
    )
    if process.stdin is None or process.stdout is None:
        process.kill()
        process.wait()
        cleanup()
        recorder.close()
        raise RunnerInfrastructureFailure("public probe pipes are unavailable")
    probe_input = cast(TextIO, process.stdin)
    probe_output = cast(TextIO, process.stdout)
    handles: dict[int, RecordedEnvironment] = {}
    next_handle = 1
    next_probe_sequence = 1
    try:
        probe_input.write(
            json.dumps({"source": probe_source, "mode": mode}, ensure_ascii=False) + "\n"
        )
        probe_input.flush()
        while True:
            ready, _, _ = select.select([probe_output], [], [], 60.0)
            if not ready:
                raise RunnerInfrastructureFailure("public probe transport timed out")
            line = probe_output.readline()
            if not line:
                raise RunnerInfrastructureFailure("public probe exited before completion")
            try:
                message = json.loads(line)
            except json.JSONDecodeError as exc:
                raise RunnerInfrastructureFailure("public probe returned invalid JSON") from exc
            if isinstance(message, dict) and message.get("type") == "done":
                if message == {"type": "done", "ok": True}:
                    assert_closed()
                    break
                error = message.get("error")
                if (
                    message.get("ok") is False
                    and set(message) == {"type", "ok", "error"}
                    and isinstance(error, dict)
                    and isinstance(error.get("type"), str)
                    and isinstance(error.get("message"), str)
                ):
                    if error["type"] == "AssertionError":
                        raise AssertionError(error["message"])
                    raise RuntimeError(error["message"])
                raise RunnerInfrastructureFailure("public probe returned an invalid completion")
            request = _parse_probe_call(message)
            sequence, operation, instance, handle, arguments = request
            if sequence != next_probe_sequence:
                raise RunnerInfrastructureFailure("public probe call sequence is not monotonic")
            next_probe_sequence += 1
            if operation == "open":
                environment_handle = session.open(cast(str, instance))
                handle_id = next_handle
                next_handle += 1
                handles[handle_id] = environment_handle
                value: Any = handle_id
            else:
                active_handle = handles.get(cast(int, handle))
                if active_handle is None:
                    raise RuntimeError("public probe used an unknown environment handle")
                if operation == "reset":
                    value = active_handle.reset(arguments["start"])
                elif operation == "tools":
                    value = list(active_handle.tools())
                elif operation == "invoke":
                    value = active_handle.invoke(
                        arguments["tool_name"],
                        arguments["arguments"],
                    )
                else:
                    active_handle.close()
                    handles.pop(cast(int, handle), None)
                    value = None
            probe_input.write(
                json.dumps(
                    {
                        "type": "result",
                        "seq": sequence,
                        "ok": True,
                        "value": _json_copy(value),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
                + "\n"
            )
            probe_input.flush()
    finally:
        try:
            probe_input.close()
        except (BrokenPipeError, OSError):
            pass
        if process.poll() is None:
            process.kill()
        process.wait()
        cleanup()
        recorder.close()
    return recorder.payload


def _exception_cause[T: BaseException](
    error: BaseException,
    expected: type[T],
) -> T | None:
    current: BaseException | None = error
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        if isinstance(current, expected):
            return current
        seen.add(id(current))
        current = current.__cause__ or current.__context__
    return None


def _parse_probe_call(
    value: Any,
) -> tuple[int, Operation, str | None, int | None, dict[str, Any]]:
    required = {"type", "seq", "operation", "instance", "handle", "arguments"}
    if not isinstance(value, dict) or set(value) != required or value.get("type") != "call":
        raise RunnerInfrastructureFailure("public probe returned an invalid call")
    sequence = value["seq"]
    operation = value["operation"]
    instance = value["instance"]
    handle = value["handle"]
    arguments = value["arguments"]
    if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence <= 0:
        raise RunnerInfrastructureFailure("public probe call sequence is invalid")
    if operation not in _OPERATIONS or not isinstance(arguments, dict):
        raise RunnerInfrastructureFailure("public probe operation is invalid")
    expected_arguments = (
        {"start"}
        if operation == "reset"
        else {"tool_name", "arguments"}
        if operation == "invoke"
        else set()
    )
    if operation == "open":
        if not isinstance(instance, str) or handle is not None or arguments:
            raise RunnerInfrastructureFailure("public probe open call is invalid")
    elif (
        instance is not None
        or not isinstance(handle, int)
        or isinstance(handle, bool)
        or handle <= 0
        or set(arguments) != expected_arguments
    ):
        raise RunnerInfrastructureFailure("public probe handle call is invalid")
    return (
        sequence,
        cast(Operation, operation),
        cast(str | None, instance),
        cast(int | None, handle),
        cast(dict[str, Any], arguments),
    )


def _load_host_journal(path: Path, expected_run_id: str) -> HostJournal:
    events: list[JournalEvent] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ValueError(f"cannot read Host journal: {exc}") from exc
    for position, line in enumerate(lines, start=1):
        if not line.strip():
            raise ValueError(f"Host journal line {position} is empty")
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Host journal line {position} is invalid JSON") from exc
        events.append(_parse_event(raw, expected_run_id, position))
    document: dict[str, Any] = {
        "run_id": expected_run_id,
        "events": [event.to_document() for event in events],
    }
    return HostJournal(
        expected_run_id,
        tuple(events),
        hashlib.sha256(rfc8785.dumps(document)).hexdigest(),
        _JOURNAL_ORIGIN,
    )


def _is_host_journal(value: object) -> bool:
    return isinstance(value, HostJournal) and value._origin is _JOURNAL_ORIGIN


def _tree_manifest(root: Path) -> TreeManifest:
    base = Path(root)
    if not base.is_dir() or base.is_symlink():
        raise ValueError(f"controlled root must be a non-symlink directory: {base}")
    records: list[TreeRecord] = []

    def visit(path: Path, relative: str) -> None:
        metadata = path.lstat()
        mode = stat.S_IMODE(metadata.st_mode)
        if path.is_symlink():
            records.append(TreeRecord(relative, "symlink", mode, symlink_target=os.readlink(path)))
            return
        if stat.S_ISREG(metadata.st_mode):
            records.append(
                TreeRecord(relative, "file", mode, hashlib.sha256(path.read_bytes()).hexdigest())
            )
            return
        if not stat.S_ISDIR(metadata.st_mode):
            records.append(TreeRecord(relative, "other", mode))
            return
        records.append(TreeRecord(relative, "directory", mode))
        for child in sorted(path.iterdir(), key=lambda item: item.name):
            child_relative = child.name if relative == "." else f"{relative}/{child.name}"
            visit(child, child_relative)

    visit(base, ".")
    document = {"records": [record.to_document() for record in records]}
    return TreeManifest(tuple(records), hashlib.sha256(rfc8785.dumps(document)).hexdigest())


def _copy_release(source: Path, destination: Path) -> None:
    origin, target = Path(source), Path(destination)
    if target.exists():
        raise ValueError(f"release copy destination already exists: {target}")
    verify_release(origin)
    descriptor_document = _read_json(origin / "release.json")
    descriptor = parse_descriptor(descriptor_document)
    manifest_document = _read_json(origin / descriptor.payload_manifest)
    records = parse_manifest(manifest_document)
    members = [
        Path("release.json"),
        Path(descriptor.payload_manifest),
        *map(lambda r: Path(r.path), records),
    ]
    for relative in members:
        source_path = origin / relative
        if source_path.is_symlink() or not source_path.is_file():
            raise ValueError(f"release member is not a regular file: {relative}")
        target_path = target / relative
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_path, target_path)
        target_path.chmod(stat.S_IMODE(source_path.stat().st_mode))
    verify_release(target)


def _rebind_release_copy(root: Path) -> TreeManifest:
    release = Path(root)
    descriptor_path = release / "release.json"
    descriptor_document = _read_json(descriptor_path)
    descriptor = parse_descriptor(descriptor_document)
    protected = {"release.json", str(descriptor.payload_manifest)}
    records: list[dict[str, Any]] = []
    for item in _tree_manifest(release).records:
        if item.path == "." or item.object_type == "directory" or item.path in protected:
            continue
        if item.object_type != "file" or item.digest is None:
            raise ValueError(f"rebound release contains unsupported object: {item.path}")
        records.append(
            {"path": item.path, "type": "file", "mode": item.mode, "digest": item.digest}
        )
    manifest_document = {"files": sorted(records, key=lambda item: item["path"])}
    (release / descriptor.payload_manifest).write_bytes(canonical_bytes(manifest_document))
    descriptor_document["payload_digest"] = compute_payload_digest(manifest_document)
    descriptor_path.write_bytes(canonical_bytes(descriptor_document))
    verify_release(release)
    return _tree_manifest(release)


def _make_run_carrier(
    run_id: str,
    release_root: Path,
    instance_root: Path,
    release_before: TreeManifest,
    release_after: TreeManifest,
    instance_before: TreeManifest,
    instance_after: TreeManifest,
    journal: HostJournal,
    original_candidate_digest: str,
) -> ControlledRunCarrier:
    if not _is_host_journal(journal) or journal.run_id != run_id:
        raise ValueError("controlled run requires its own Host journal")
    return ControlledRunCarrier(
        run_id,
        Path(release_root),
        Path(instance_root),
        release_before,
        release_after,
        instance_before,
        instance_after,
        journal,
        original_candidate_digest,
        release_after.digest,
        _CARRIER_ORIGIN,
    )


def _is_run_carrier(value: object) -> bool:
    return isinstance(value, ControlledRunCarrier) and value._origin is _CARRIER_ORIGIN


def _read_json(path: Path) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read release JSON {path}: {exc}") from exc
    if not isinstance(document, dict):
        raise ValueError(f"release JSON must be an object: {path}")
    return document


def _parse_event(raw: Any, run_id: str, position: int) -> JournalEvent:
    required = {"run_id", "seq", "instance", "operation", "arguments", "result"}
    if not isinstance(raw, dict) or set(raw) != required:
        raise ValueError(f"Host journal line {position} has invalid members")
    if raw["run_id"] != run_id or raw["seq"] != position:
        raise ValueError(f"Host journal line {position} breaks run/sequence binding")
    instance = raw["instance"]
    operation = raw["operation"]
    if not isinstance(instance, str) or not instance:
        raise ValueError(f"Host journal line {position} has invalid instance")
    if operation not in _OPERATIONS:
        raise ValueError(f"Host journal line {position} has invalid operation")
    arguments = raw["arguments"]
    if not isinstance(arguments, dict) or not _valid_arguments(operation, arguments):
        raise ValueError(f"Host journal line {position} has invalid arguments")
    return JournalEvent(
        run_id=run_id,
        seq=position,
        instance=instance,
        operation=cast(Operation, operation),
        arguments=cast(dict[str, Any], _json_copy(arguments)),
        result=_json_copy(raw["result"]),
    )


def _valid_arguments(operation: str, arguments: dict[str, Any]) -> bool:
    if operation == "reset":
        return set(arguments) == {"start"}
    if operation == "invoke":
        return set(arguments) == {"tool_name", "arguments"}
    return not arguments


def _validate_instance_key(instance_key: str) -> None:
    if (
        not isinstance(instance_key, str)
        or not instance_key
        or instance_key in {".", ".."}
        or Path(instance_key).name != instance_key
    ):
        raise ValueError("instance_key must be one non-empty path segment")


def _json_copy(value: Any) -> Any:
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, tuple | list):
        return [_json_copy(item) for item in value]
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("journal objects require string keys")
        return {key: _json_copy(item) for key, item in value.items()}
    raise TypeError(f"journal value is not JSON-compatible: {type(value).__name__}")


def _terminate_coordinator(signum: int, frame: Any) -> None:
    del signum, frame
    raise RunnerInfrastructureFailure("Qualification coordinator was terminated")


def main(argv: Sequence[str] | None = None) -> int:
    signal.signal(signal.SIGTERM, _terminate_coordinator)
    parser = argparse.ArgumentParser(description="Run one Host-journaled public probe")
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--instances", type=Path, required=True)
    parser.add_argument("--dependencies", type=Path, required=True)
    parser.add_argument("--actor-python", type=Path, required=True)
    parser.add_argument("--codex-binary", type=Path, required=True)
    parser.add_argument("--codex-home", type=Path, required=True)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--qualification-root", type=Path, required=True)
    arguments = parser.parse_args(argv)
    try:
        sandbox = _SandboxContext(
            arguments.codex_binary,
            arguments.codex_home,
            arguments.candidate_root,
            arguments.qualification_root,
        )
        invocation = json.loads(sys.stdin.read())
        if not isinstance(invocation, dict) or set(invocation) != {
            "run_id",
            "mode",
            "probe_source",
        }:
            raise ValueError("private invocation has invalid members")
        run_id = invocation["run_id"]
        mode = invocation["mode"]
        source = invocation["probe_source"]
        if not all(isinstance(value, str) and value for value in (run_id, mode, source)):
            raise ValueError("private invocation values must be non-empty strings")
        result_fd = os.dup(sys.stdout.fileno())
        os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
        payload = _run_public_probe_source(
            cast(str, source),
            arguments.release,
            arguments.instances,
            cast(str, run_id),
            None,
            cast(str, mode),
            arguments.dependencies,
            arguments.actor_python,
            sandbox,
        )
        with os.fdopen(result_fd, "wb", closefd=True) as result_stream:
            result_stream.write(payload)
            result_stream.flush()
    except RunnerInfrastructureFailure as exc:
        print(
            json.dumps({"error_type": type(exc).__name__, "message": str(exc)}),
            file=sys.stderr,
        )
        return 22
    except CandidateExecutionFailure as exc:
        print(
            json.dumps({"error_type": exc.error_type, "message": str(exc)}),
            file=sys.stderr,
        )
        return 20
    except Exception as exc:
        print(
            json.dumps({"error_type": type(exc).__name__, "message": str(exc)}),
            file=sys.stderr,
        )
        return 21
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
