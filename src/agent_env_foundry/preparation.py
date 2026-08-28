"""EnvironmentRelease v2 preparation identities and projection protocols.

Checkpoint 1 freezes only the identity/projection contract.  Checkpoint 2 owns
locked installation, child processes, private transport and lifecycle behavior.
"""

from __future__ import annotations

import hashlib
import json
import os
import select
import shutil
import stat
import subprocess
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import TracebackType
from typing import Any, Literal, Protocol, Self, TextIO, cast, runtime_checkable

from agent_env_foundry._qualification_runner import _tree_manifest
from agent_env_foundry.environment import (
    Environment,
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
from agent_env_foundry.release import (
    DESCRIPTOR_FORMAT_V2,
    PayloadRecord,
    ValidatedReleaseV2,
    canonical_bytes,
    compute_project_digest,
    safe_member_path,
    verify_release_v2,
)
from agent_env_foundry.schema import SchemaError, validate_instance
from agent_env_foundry.semantics import (
    AtomCheckRequest,
    AtomCheckResult,
    BindingCandidate,
    CapabilitySpec,
    ConditionCheckRequest,
    ConditionCheckResult,
    StartCase,
    TaskSemantics,
    atom_result_from_document,
    binding_from_document,
    capability_from_document,
    condition_result_from_document,
    start_case_from_document,
    validate_binding,
    validate_catalog,
    validate_start_cases,
)

ENVIRONMENT_RELEASE_V2_FORMAT = DESCRIPTOR_FORMAT_V2
_HEX = frozenset("0123456789abcdef")
PreparationFailureKind = Literal["EnvironmentDefect", "InfrastructureFailure", "SemanticsDefect"]
_PREPARATION_FAILURE_KINDS = frozenset(
    {"EnvironmentDefect", "InfrastructureFailure", "SemanticsDefect"}
)


class PreparationContractError(ValueError):
    """A prepared release/session value violates the v2 trust contract."""


class PreparationExecutionError(RuntimeError):
    """A release, infrastructure or semantics runtime failed closed."""

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
class PublicReleaseIdentity:
    format: str
    release_id: str

    def __post_init__(self) -> None:
        _format(self.format)
        _digest(self.release_id, "release_id")

    def to_document(self) -> JSONObject:
        return {"format": self.format, "release_id": self.release_id}


@dataclass(frozen=True, slots=True)
class PreparedReleaseIdentity:
    format: str
    release_id: str
    actor_digest: str
    semantics_digest: str

    def __post_init__(self) -> None:
        _format(self.format)
        _digest(self.release_id, "release_id")
        _digest(self.actor_digest, "actor_digest")
        _digest(self.semantics_digest, "semantics_digest")

    def public_document(self) -> JSONObject:
        return PublicReleaseIdentity(self.format, self.release_id).to_document()

    def trusted_document(self) -> JSONObject:
        return {
            "format": self.format,
            "release_id": self.release_id,
            "actor_digest": self.actor_digest,
            "semantics_digest": self.semantics_digest,
        }


@dataclass(frozen=True, slots=True)
class PreparedSessionIdentity:
    release_id: str
    actor_digest: str
    semantics_digest: str
    materialization_id: str

    def __post_init__(self) -> None:
        _digest(self.release_id, "release_id")
        _digest(self.actor_digest, "actor_digest")
        _digest(self.semantics_digest, "semantics_digest")
        _digest(self.materialization_id, "materialization_id")

    def to_document(self) -> JSONObject:
        return {
            "release_id": self.release_id,
            "actor_digest": self.actor_digest,
            "semantics_digest": self.semantics_digest,
            "materialization_id": self.materialization_id,
        }


TrustedOperation = Literal[
    "start_cases",
    "inspect",
    "capabilities",
    "enumerate_bindings",
    "evaluate_atom",
    "evaluate_condition",
]
_TRUSTED_OPERATIONS = frozenset(
    {
        "start_cases",
        "inspect",
        "capabilities",
        "enumerate_bindings",
        "evaluate_atom",
        "evaluate_condition",
    }
)


@dataclass(frozen=True, slots=True)
class TrustedCallEvent:
    seq: int
    session: PreparedSessionIdentity
    operation: TrustedOperation
    request_digest: str
    response_digest: str
    before_tree_digest: str
    after_tree_digest: str

    def __post_init__(self) -> None:
        if self.seq <= 0:
            raise PreparationContractError("trusted call seq must be positive")
        if self.operation not in _TRUSTED_OPERATIONS:
            raise PreparationContractError("trusted call operation is invalid")
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
            "session": self.session.to_document(),
            "operation": self.operation,
            "request_digest": self.request_digest,
            "response_digest": self.response_digest,
            "before_tree_digest": self.before_tree_digest,
            "after_tree_digest": self.after_tree_digest,
            "unchanged": self.unchanged,
        }


@runtime_checkable
class PreparedSession(Protocol):
    identity: PreparedSessionIdentity
    actor: Environment
    trusted: TaskSemantics

    def close(self) -> None: ...
    def __enter__(self) -> Self: ...
    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...


@runtime_checkable
class PreparedRelease(Protocol):
    identity: PreparedReleaseIdentity

    def open(self, instance_directory: Path) -> PreparedSession: ...


@dataclass(frozen=True, slots=True)
class RuntimeLock:
    project_root: Path
    project_digest: str
    python: Path
    own_module: str
    forbidden_module: str
    role: Literal["actor", "semantics"]


class _ChildTransport:
    def __init__(
        self,
        python: Path,
        runner: Path,
        arguments: tuple[str, ...],
        *,
        cwd: Path,
        timeout: float,
        role: Literal["actor", "semantics"],
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
                "EnvironmentDefect" if self._role == "actor" else "SemanticsDefect",
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
        self._stdin.close()
        try:
            self._process.wait(timeout=self._timeout)
        except subprocess.TimeoutExpired:
            self._process.kill()
            self._process.wait()

    def _failure(self, code: str, cause: Exception | None) -> PreparationExecutionError:
        status = self._process.poll()
        stderr = self._stderr.read() if status is not None else ""
        if code == "child_exited" and self._next_seq == 2:
            kind: PreparationFailureKind = (
                "EnvironmentDefect" if self._role == "actor" else "SemanticsDefect"
            )
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


class ActorProxy:
    def __init__(self, transport: _ChildTransport, release: ValidatedReleaseV2) -> None:
        self._transport = transport
        self._start_schema = release.start_schema
        self._reset_schema = release.reset_observation_schema

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


class TrustedProxy:
    def __init__(
        self,
        transport: _ChildTransport,
        release: ValidatedReleaseV2,
        instance: Path,
        identity: PreparedSessionIdentity,
        events: list[TrustedCallEvent],
    ) -> None:
        self._transport = transport
        self._release = release
        self._instance = instance.resolve()
        self._identity = identity
        self._events = events
        self._catalog: dict[str, CapabilitySpec] | None = None

    def _call(self, operation: TrustedOperation, arguments: JSONObject) -> JSONValue:
        before = _tree_manifest(self._instance)
        failure: PreparationExecutionError | None = None
        try:
            value = self._transport.call(operation, arguments)
            response_document: JSONValue = value
        except PreparationExecutionError as exc:
            failure = exc
            response_document = {
                "kind": exc.kind,
                "code": exc.code,
                "message": str(exc),
            }
        after = _tree_manifest(self._instance)
        event = TrustedCallEvent(
            len(self._events) + 1,
            self._identity,
            operation,
            _sha(canonical_bytes(arguments)),
            _sha(canonical_bytes(response_document)),
            before.digest,
            after.digest,
        )
        self._events.append(event)
        if not event.unchanged:
            raise PreparationExecutionError(
                "SemanticsDefect", "trusted_state_mutation", "trusted semantics mutated instance"
            ) from failure
        if failure is not None:
            raise failure
        return value

    def start_cases(self, seed: int, limit: int) -> tuple[StartCase, ...]:
        raw = self._call("start_cases", {"seed": seed, "limit": limit})
        if not isinstance(raw, list):
            raise PreparationExecutionError(
                "SemanticsDefect", "start_cases_shape", "start_cases must be array"
            )
        values = tuple(start_case_from_document(item) for item in raw)
        validate_start_cases(values, start_schema=self._release.start_schema, limit=limit)
        return values

    def inspect(self, instance_directory: Path) -> JSONValue:
        if Path(instance_directory).resolve() != self._instance:
            raise PreparationContractError("inspect is bound to the session instance_directory")
        return self._call("inspect", {"instance_directory": str(self._instance)})

    def capabilities(self) -> tuple[CapabilitySpec, ...]:
        raw = self._call("capabilities", {})
        if not isinstance(raw, list):
            raise PreparationExecutionError(
                "SemanticsDefect", "capabilities_shape", "capabilities must be array"
            )
        values = tuple(capability_from_document(item) for item in raw)
        self._catalog = validate_catalog(values)
        return values

    def enumerate_bindings(
        self, capability_id: str, facts: JSONValue
    ) -> tuple[BindingCandidate, ...]:
        raw = self._call("enumerate_bindings", {"capability_id": capability_id, "facts": facts})
        if not isinstance(raw, list):
            raise PreparationExecutionError(
                "SemanticsDefect", "bindings_shape", "bindings must be array"
            )
        values = tuple(binding_from_document(item) for item in raw)
        catalog = self._catalog or validate_catalog(self.capabilities())
        if capability_id not in catalog:
            raise PreparationContractError(f"unknown capability {capability_id!r}")
        for value in values:
            validate_binding(catalog[capability_id], value)
        return values

    def evaluate_atom(self, request: AtomCheckRequest) -> AtomCheckResult:
        return atom_result_from_document(
            self._call("evaluate_atom", {"request": request.to_document()})
        )

    def evaluate_condition(self, request: ConditionCheckRequest) -> ConditionCheckResult:
        return condition_result_from_document(
            self._call("evaluate_condition", {"request": request.to_document()})
        )

    def close(self) -> None:
        self._transport.close(operation="close")


class OpenPreparedSession:
    def __init__(
        self,
        identity: PreparedSessionIdentity,
        actor: ActorProxy,
        trusted: TrustedProxy,
        events: list[TrustedCallEvent],
    ) -> None:
        self.identity = identity
        self.actor = actor
        self.trusted = trusted
        self._events = events
        self._closed = False

    @property
    def trusted_events(self) -> tuple[TrustedCallEvent, ...]:
        return tuple(self._events)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.actor.close()
        self.trusted.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()


class OpenPreparedRelease:
    def __init__(
        self,
        release: ValidatedReleaseV2,
        actor: RuntimeLock,
        semantics: RuntimeLock,
        settings: PreparationSettings,
    ) -> None:
        self.identity = release.identity
        self._release = release
        self._actor = actor
        self._semantics = semantics
        self._settings = settings

    def open(self, instance_directory: Path) -> OpenPreparedSession:
        _verify_runtime(self._actor, self._settings.command_timeout_seconds)
        _verify_runtime(self._semantics, self._settings.command_timeout_seconds)
        instance = Path(instance_directory).resolve()
        instance.mkdir(parents=True, exist_ok=True)
        materialization_id = hashlib.sha256(
            f"{self.identity.release_id}\0{uuid.uuid4().hex}".encode()
        ).hexdigest()
        identity = PreparedSessionIdentity(
            self.identity.release_id,
            self.identity.actor_digest,
            self.identity.semantics_digest,
            materialization_id,
        )
        runner_root = Path(__file__).resolve().parent
        actor_transport = _ChildTransport(
            self._actor.python,
            runner_root / "_actor_runner.py",
            (self._release.descriptor.actor_factory, str(instance)),
            cwd=self._actor.project_root,
            timeout=self._settings.command_timeout_seconds,
            role="actor",
        )
        try:
            semantics_transport = _ChildTransport(
                self._semantics.python,
                runner_root / "_semantics_runner.py",
                (self._release.descriptor.semantics_factory,),
                cwd=self._semantics.project_root,
                timeout=self._settings.command_timeout_seconds,
                role="semantics",
            )
        except Exception:
            actor_transport.close()
            raise
        events: list[TrustedCallEvent] = []
        actor = ActorProxy(actor_transport, self._release)
        trusted = TrustedProxy(semantics_transport, self._release, instance, identity, events)
        return OpenPreparedSession(identity, actor, trusted, events)


def prepare_release(
    release_path: Path,
    cache_root: Path,
    *,
    settings: PreparationSettings | None = None,
) -> OpenPreparedRelease:
    if settings is None:
        settings = PreparationSettings(Path("/tmp/agent-env-foundry-v2-uv-cache"))
    cache = Path(cache_root).resolve()
    cache.mkdir(parents=True, exist_ok=True)
    source, ephemeral = _stage_release(Path(release_path), cache)
    try:
        release = verify_release_v2(source)
        release_cache = cache / "releases" / release.release_id
        if not release_cache.exists():
            release_cache.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(source, release_cache, symlinks=False)
    finally:
        if ephemeral:
            shutil.rmtree(source)
    release = verify_release_v2(release_cache)
    runtime_root = cache / "runtimes" / release.release_id
    actor = _prepare_runtime(
        release_cache / release.descriptor.actor_project,
        runtime_root / "actor",
        release.descriptor.actor_project_digest,
        _module_name(release.descriptor.actor_factory),
        _module_name(release.descriptor.semantics_factory),
        "actor",
        settings,
    )
    semantics = _prepare_runtime(
        release_cache / release.descriptor.semantics_project,
        runtime_root / "semantics",
        release.descriptor.semantics_project_digest,
        _module_name(release.descriptor.semantics_factory),
        _module_name(release.descriptor.actor_factory),
        "semantics",
        settings,
    )
    return OpenPreparedRelease(release, actor, semantics, settings)


def parse_public_release_identity(document: Any) -> PublicReleaseIdentity:
    """Decode only the actor-visible identity; trusted fields are rejected."""

    if not is_json_object(document) or set(document) != {"format", "release_id"}:
        raise PreparationContractError(
            "public release identity must contain exactly format and release_id"
        )
    format_value = document["format"]
    release_id = document["release_id"]
    if not isinstance(format_value, str) or not isinstance(release_id, str):
        raise PreparationContractError("public release identity fields must be strings")
    return PublicReleaseIdentity(format_value, release_id)


def _format(value: str) -> None:
    if value != ENVIRONMENT_RELEASE_V2_FORMAT:
        raise PreparationContractError(
            f"prepared release format must be {ENVIRONMENT_RELEASE_V2_FORMAT!r}"
        )


def _digest(value: str, role: str) -> None:
    if len(value) != 64 or any(character not in _HEX for character in value):
        raise PreparationContractError(f"{role} must be a lowercase SHA-256 digest")


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _module_name(reference: str) -> str:
    return reference.partition(":")[0].partition(".")[0]


def _stage_release(source: Path, cache: Path) -> tuple[Path, bool]:
    if source.is_dir():
        return source.resolve(), False
    incoming = cache / ".incoming" / uuid.uuid4().hex
    incoming.mkdir(parents=True)
    seen: set[PurePosixPath] = set()
    try:
        with zipfile.ZipFile(source, "r") as package:
            for info in package.infolist():
                relative = safe_member_path(info.filename, field="v2 ZIP member")
                if relative in seen:
                    raise PreparationContractError("v2 ZIP contains duplicate members")
                seen.add(relative)
                if info.is_dir():
                    continue
                mode = (info.external_attr >> 16) & 0xFFFF
                if stat.S_IFMT(mode) not in {0, stat.S_IFREG}:
                    raise PreparationContractError("v2 ZIP contains a non-regular member")
                target = incoming / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(package.read(info))
                target.chmod(mode & 0o777)
    except (OSError, zipfile.BadZipFile) as exc:
        raise PreparationExecutionError(
            "EnvironmentDefect", "release_zip_invalid", f"cannot extract v2 release: {exc}"
        ) from exc
    verify_release_v2(incoming)
    return incoming, True


def _prepare_runtime(
    source: Path,
    runtime_root: Path,
    expected_digest: str,
    own_module: str,
    forbidden_module: str,
    role: Literal["actor", "semantics"],
    settings: PreparationSettings,
) -> RuntimeLock:
    project = runtime_root / "project"
    if not runtime_root.exists():
        runtime_root.parent.mkdir(parents=True, exist_ok=True)
        temporary = runtime_root.parent / f".{runtime_root.name}.{uuid.uuid4().hex}.tmp"
        shutil.copytree(source, temporary / "project", symlinks=False)
        temporary.rename(runtime_root)
        try:
            _run_uv_sync(project, settings)
        except Exception:
            shutil.rmtree(runtime_root)
            raise
    python = project / ".venv/bin/python"
    lock = RuntimeLock(project, expected_digest, python, own_module, forbidden_module, role)
    _verify_runtime(lock, settings.command_timeout_seconds)
    return lock


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
            "EnvironmentDefect", "prepared_project_missing", "prepared project is missing"
        )
    actual = _project_source_digest(lock.project_root)
    if actual != lock.project_digest:
        raise PreparationExecutionError(
            "EnvironmentDefect",
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
        forbidden_origin = _probe_origin(
            lock.python, lock.project_root, lock.forbidden_module, timeout
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PreparationExecutionError(
            "InfrastructureFailure", "runtime_import_probe_failed", str(exc)
        ) from exc
    expected_source = (lock.project_root / "src").resolve()
    if own_origin is None or not own_origin.resolve().is_relative_to(expected_source):
        raise PreparationExecutionError(
            "EnvironmentDefect",
            "runtime_package_origin_invalid",
            f"runtime package {lock.own_module} is not bound to prepared source",
            origin=str(own_origin) if own_origin else None,
        )
    if forbidden_origin is not None:
        kind: PreparationFailureKind = (
            "EnvironmentDefect" if lock.role == "actor" else "SemanticsDefect"
        )
        raise PreparationExecutionError(
            kind,
            "runtime_import_leak",
            f"runtime can import forbidden package {lock.forbidden_module}",
            origin=str(forbidden_origin),
        )


def _project_source_digest(project: Path) -> str:
    records: list[PayloadRecord] = []
    for path in sorted(project.rglob("*"), key=lambda item: item.relative_to(project).as_posix()):
        relative = path.relative_to(project)
        if ".venv" in relative.parts:
            continue
        if path.is_symlink():
            raise PreparationExecutionError(
                "EnvironmentDefect", "prepared_project_symlink", "prepared project has symlink"
            )
        if path.is_file():
            records.append(
                PayloadRecord(
                    PurePosixPath(relative.as_posix()),
                    "file",
                    stat.S_IMODE(path.stat().st_mode),
                    _sha(path.read_bytes()),
                )
            )
    return compute_project_digest(records, PurePosixPath("."))
