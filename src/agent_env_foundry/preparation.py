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
from agent_env_foundry.project_identity import (
    ProjectIdentityError,
    ProjectRole,
    compute_authored_project_digest,
    copy_authored_project,
)
from agent_env_foundry.release import (
    DESCRIPTOR_FORMAT_V2,
    ValidatedReleaseV2,
    canonical_bytes,
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
    validate_bindings,
    validate_catalog,
    validate_start_cases,
)
from agent_env_foundry.tree_manifest import tree_manifest

ENVIRONMENT_RELEASE_V2_FORMAT = DESCRIPTOR_FORMAT_V2
_HEX = frozenset("0123456789abcdef")
PreparationFailureKind = Literal[
    "EnvironmentDefect",
    "InfrastructureFailure",
    "SemanticsDefect",
    "VerifierDefect",
]
_PREPARATION_FAILURE_KINDS = frozenset(
    {"EnvironmentDefect", "InfrastructureFailure", "SemanticsDefect", "VerifierDefect"}
)
_PROJECT_ROLES = frozenset({"actor", "semantics", "verifier"})


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
        before = tree_manifest(self._instance)
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
        after = tree_manifest(self._instance)
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
        validate_bindings(catalog[capability_id], values)
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

    @property
    def task_goals(self) -> JSONObject:
        if self._release.sealed_task_goals is None:
            raise PreparationContractError("prepared release has no admitted public task goals")
        return cast(
            JSONObject,
            json.loads(json.dumps(self._release.sealed_task_goals, ensure_ascii=False)),
        )

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
        semantics_transport: _ChildTransport | None = None
        try:
            semantics_transport = _ChildTransport(
                self._semantics.python,
                runner_root / "_semantics_runner.py",
                (self._release.descriptor.semantics_factory,),
                cwd=self._semantics.project_root,
                timeout=self._settings.command_timeout_seconds,
                role="semantics",
            )
            raw_tools = actor_transport.call("tools", {})
            if not isinstance(raw_tools, list):
                raise PreparationExecutionError(
                    "EnvironmentDefect",
                    "session_actor_not_ready",
                    "actor readiness tools response is not an array",
                )
            validate_tool_catalog(tuple(raw_tools), role="session actor readiness")
            raw_capabilities = semantics_transport.call("capabilities", {})
            if not isinstance(raw_capabilities, list):
                raise PreparationExecutionError(
                    "SemanticsDefect",
                    "session_semantics_not_ready",
                    "semantics readiness capabilities response is not an array",
                )
            validate_catalog(tuple(capability_from_document(item) for item in raw_capabilities))
        except Exception:
            actor_transport.close()
            if semantics_transport is not None:
                semantics_transport.close(operation="close")
            raise
        assert semantics_transport is not None
        events: list[TrustedCallEvent] = []
        actor = ActorProxy(
            actor_transport,
            start_schema=self._release.start_schema,
            reset_observation_schema=self._release.reset_observation_schema,
        )
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
    actor = materialize_project(
        ProjectMaterializationInput(
            source_root=release_cache / release.descriptor.actor_project,
            project_digest=release.descriptor.actor_project_digest,
            own_module=_module_name(release.descriptor.actor_factory),
            forbidden_modules=(
                _module_name(release.descriptor.semantics_factory),
                "generated_qualification_verifier",
                "agent_env_foundry",
            ),
            role="actor",
        ),
        runtime_root / "actor",
        settings=settings,
    )
    semantics = materialize_project(
        ProjectMaterializationInput(
            source_root=release_cache / release.descriptor.semantics_project,
            project_digest=release.descriptor.semantics_project_digest,
            own_module=_module_name(release.descriptor.semantics_factory),
            forbidden_modules=(
                _module_name(release.descriptor.actor_factory),
                "generated_qualification_verifier",
                "agent_env_foundry",
            ),
            role="semantics",
        ),
        runtime_root / "semantics",
        settings=settings,
    )
    _verify_live_sealed_catalogs(
        release,
        actor,
        semantics,
        runtime_root / ".catalog-probe",
        settings,
    )
    return OpenPreparedRelease(release, actor, semantics, settings)


def _verify_live_sealed_catalogs(
    release: ValidatedReleaseV2,
    actor_lock: RuntimeLock,
    semantics_lock: RuntimeLock,
    probe_instance: Path,
    settings: PreparationSettings,
) -> None:
    sealed = (
        release.sealed_tool_specs,
        release.sealed_capabilities,
        release.sealed_start_cases,
        release.sealed_start_seed,
        release.sealed_start_limit,
    )
    if any(item is None for item in sealed):
        return  # Structural fixture path used only by lower-level tests.
    actor_manifest = tree_manifest(actor_lock.project_root)
    semantics_manifest = tree_manifest(semantics_lock.project_root)
    actor_transport = _ChildTransport(
        actor_lock.python,
        Path(__file__).resolve().parent / "_actor_runner.py",
        (release.descriptor.actor_factory, str(probe_instance)),
        cwd=actor_lock.project_root,
        timeout=settings.command_timeout_seconds,
        role="actor",
    )
    semantics_transport: _ChildTransport | None = None
    try:
        actor_proxy = ActorProxy(
            actor_transport,
            start_schema=release.start_schema,
            reset_observation_schema=release.reset_observation_schema,
        )
        live_tools = actor_proxy.tools()
        if canonical_bytes([dict(item) for item in live_tools]) != canonical_bytes(
            [dict(item) for item in cast(tuple[ToolSpec, ...], release.sealed_tool_specs)]
        ):
            raise PreparationExecutionError(
                "EnvironmentDefect",
                "sealed_tool_catalog_mismatch",
                "live actor ToolSpecs differ from the sealed Public Surface",
            )
        semantics_transport = _ChildTransport(
            semantics_lock.python,
            Path(__file__).resolve().parent / "_semantics_runner.py",
            (release.descriptor.semantics_factory,),
            cwd=semantics_lock.project_root,
            timeout=settings.command_timeout_seconds,
            role="semantics",
        )
        raw_capabilities = semantics_transport.call("capabilities", {})
        if not isinstance(raw_capabilities, list):
            raise PreparationExecutionError(
                "SemanticsDefect",
                "sealed_capability_catalog_invalid",
                "live TaskSemantics capabilities are not an array",
            )
        live_capabilities = tuple(capability_from_document(item) for item in raw_capabilities)
        validate_catalog(live_capabilities)
        if canonical_bytes([item.to_document() for item in live_capabilities]) != canonical_bytes(
            [
                item.to_document()
                for item in cast(tuple[CapabilitySpec, ...], release.sealed_capabilities)
            ]
        ):
            raise PreparationExecutionError(
                "SemanticsDefect",
                "sealed_capability_catalog_mismatch",
                "live TaskSemantics capabilities differ from the sealed catalog",
            )
        raw_starts = semantics_transport.call(
            "start_cases",
            {
                "seed": cast(int, release.sealed_start_seed),
                "limit": cast(int, release.sealed_start_limit),
            },
        )
        if not isinstance(raw_starts, list):
            raise PreparationExecutionError(
                "SemanticsDefect",
                "sealed_start_cases_invalid",
                "live TaskSemantics StartCases are not an array",
            )
        live_starts = tuple(start_case_from_document(item) for item in raw_starts)
        validate_start_cases(
            live_starts,
            start_schema=release.start_schema,
            limit=cast(int, release.sealed_start_limit),
        )
        if canonical_bytes([item.to_document() for item in live_starts]) != canonical_bytes(
            [item.to_document() for item in cast(tuple[StartCase, ...], release.sealed_start_cases)]
        ):
            raise PreparationExecutionError(
                "SemanticsDefect",
                "sealed_start_cases_mismatch",
                "live TaskSemantics StartCases differ from the sealed set",
            )
    finally:
        actor_transport.close(operation="close")
        if semantics_transport is not None:
            semantics_transport.close(operation="close")
        shutil.rmtree(probe_instance, ignore_errors=True)
    changed = {
        role: {"before": before.digest, "after": tree_manifest(path).digest}
        for role, before, path in (
            ("actor", actor_manifest, actor_lock.project_root),
            ("semantics", semantics_manifest, semantics_lock.project_root),
        )
        if before.digest != tree_manifest(path).digest
    }
    if changed:
        raise PreparationExecutionError(
            "EnvironmentDefect",
            "catalog_probe_mutated_runtime",
            "live catalog verification changed a prepared project",
            changed=changed,
        )


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
            _role_defect(lock.role),
            "prepared_project_missing",
            "prepared project is missing",
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
        return compute_authored_project_digest(
            project,
            role,
            require_locked_project=True,
        )
    except ProjectIdentityError as exc:
        raise PreparationExecutionError(
            _role_defect(role),
            exc.code,
            str(exc),
            path=exc.path,
        ) from exc


def _role_defect(role: ProjectRole) -> PreparationFailureKind:
    if role == "actor":
        return "EnvironmentDefect"
    if role == "semantics":
        return "SemanticsDefect"
    return "VerifierDefect"
