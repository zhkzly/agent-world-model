"""EnvironmentRelease v2 preparation identities and projection protocols.

Checkpoint 1 freezes only the identity/projection contract.  Checkpoint 2 owns
locked installation, child processes, private transport and lifecycle behavior.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import stat
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import TracebackType
from typing import Any, Literal, Protocol, Self, cast, runtime_checkable

from agent_env_foundry.environment import (
    Environment,
    JSONObject,
    JSONValue,
    ToolSpec,
    validate_tool_catalog,
)
from agent_env_foundry.jsonvalue import is_json_object
from agent_env_foundry.physical_runtime import (
    ActorProxy as ActorProxy,
)
from agent_env_foundry.physical_runtime import (
    PreparationContractError as PreparationContractError,
)
from agent_env_foundry.physical_runtime import (
    PreparationExecutionError as PreparationExecutionError,
)
from agent_env_foundry.physical_runtime import (
    PreparationFailureKind as PreparationFailureKind,
)
from agent_env_foundry.physical_runtime import (
    PreparationSettings as PreparationSettings,
)
from agent_env_foundry.physical_runtime import (
    ProjectMaterializationInput as ProjectMaterializationInput,
)
from agent_env_foundry.physical_runtime import (
    RuntimeLock as RuntimeLock,
)
from agent_env_foundry.physical_runtime import (
    StateSnapshotEvent as StateSnapshotEvent,
)
from agent_env_foundry.physical_runtime import (
    StateSnapshotProxy as StateSnapshotProxy,
)
from agent_env_foundry.physical_runtime import (
    _ChildTransport as _ChildTransport,
)
from agent_env_foundry.physical_runtime import (
    _module_name as _module_name,
)
from agent_env_foundry.physical_runtime import (
    _probe_origin as _probe_origin,
)
from agent_env_foundry.physical_runtime import (
    _verify_runtime as _verify_runtime,
)
from agent_env_foundry.physical_runtime import (
    materialize_project as materialize_project,
)
from agent_env_foundry.physical_runtime import (
    read_actor_tool_catalog as read_actor_tool_catalog,
)
from agent_env_foundry.release import (
    DESCRIPTOR_FORMAT_V2,
    ValidatedReleaseV2,
    canonical_bytes,
    safe_member_path,
    verify_release_v2,
)
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
                mode = (info.external_attr >> 16) & 0xFFFF
                if info.is_dir():
                    if stat.S_IFMT(mode) not in {0, stat.S_IFDIR}:
                        raise PreparationContractError(
                            "v2 ZIP contains an invalid directory member"
                        )
                    target = incoming / relative
                    target.mkdir(parents=True, exist_ok=True)
                    target.chmod(stat.S_IMODE(mode))
                    continue
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
