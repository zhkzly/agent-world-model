"""Internal actor-only preparation for EnvironmentRelease/3."""

from __future__ import annotations

import shutil
import stat
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import TracebackType
from typing import Self

from agent_env_foundry.environment import JSONValue
from agent_env_foundry.physical_runtime import (
    ActorProxy as ActorProxyV3,
)
from agent_env_foundry.physical_runtime import (
    PreparationContractError as PreparationContractErrorV3,
)
from agent_env_foundry.physical_runtime import (
    PreparationExecutionError as PreparationExecutionErrorV3,
)
from agent_env_foundry.physical_runtime import (
    PreparationSettings as PreparationSettingsV3,
)
from agent_env_foundry.physical_runtime import (
    ProjectMaterializationInput,
    RuntimeLock,
    StateSnapshotProxy,
    _ChildTransport,
    _module_name,
    _verify_runtime,
    materialize_project,
)
from agent_env_foundry.physical_runtime import (
    StateSnapshotEvent as StateSnapshotEventV3,
)
from agent_env_foundry.release import canonical_bytes, safe_member_path, sha256_hex
from agent_env_foundry.release_v3 import ValidatedReleaseV3, verify_release_v3_internal
from agent_env_foundry.release_v3_contract import DESCRIPTOR_FORMAT_V3

_FORBIDDEN_ACTOR_MODULES = (
    "agent_env_foundry",
    "generated_task_semantics",
    "generated_qualification_verifier",
)


@dataclass(frozen=True, slots=True)
class PreparedReleaseIdentityV3:
    format: str
    release_id: str
    actor_digest: str
    state_schema_digest: str

    def __post_init__(self) -> None:
        if self.format != DESCRIPTOR_FORMAT_V3:
            raise PreparationContractErrorV3("prepared format must be environment-release/3")
        for name in ("release_id", "actor_digest", "state_schema_digest"):
            value = getattr(self, name)
            if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
                raise PreparationContractErrorV3(f"prepared {name} must be a sha256 digest")


@dataclass(frozen=True, slots=True)
class PreparedSessionIdentityV3:
    release_id: str
    actor_digest: str
    materialization_id: str


class OpenPreparedSessionV3:
    def __init__(self, identity: PreparedSessionIdentityV3, actor: ActorProxyV3) -> None:
        self.identity = identity
        self.actor = actor
        self._closed = False

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.actor.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()


class OpenPreparedReleaseV3:
    def __init__(
        self,
        release: ValidatedReleaseV3,
        actor: RuntimeLock,
        settings: PreparationSettingsV3,
    ) -> None:
        self.identity = PreparedReleaseIdentityV3(
            DESCRIPTOR_FORMAT_V3,
            release.release_id,
            release.descriptor.actor_project_digest,
            release.receipt.state_schema_digest,
        )
        self._release = release
        self._actor = actor
        self._settings = settings
        self._state_events: list[StateSnapshotEventV3] = []

    @property
    def state_events(self) -> tuple[StateSnapshotEventV3, ...]:
        return tuple(self._state_events)

    def open(self, instance_directory: Path) -> OpenPreparedSessionV3:
        _verify_runtime(self._actor, self._settings.command_timeout_seconds)
        instance = _instance_directory(instance_directory)
        transport = _ChildTransport(
            self._actor.python,
            Path(__file__).resolve().parent / "_actor_runner.py",
            (self._release.descriptor.actor_factory, str(instance)),
            cwd=self._actor.project_root,
            timeout=self._settings.command_timeout_seconds,
            role="actor",
        )
        actor = ActorProxyV3(
            transport,
            start_schema=self._release.start_schema,
            reset_observation_schema=self._release.reset_observation_schema,
        )
        try:
            _verify_live_tool_catalog(actor, self._release)
        except Exception:
            actor.close()
            raise
        identity = PreparedSessionIdentityV3(
            self.identity.release_id,
            self.identity.actor_digest,
            sha256_hex(f"{self.identity.release_id}\0{uuid.uuid4().hex}".encode()),
        )
        return OpenPreparedSessionV3(identity, actor)

    def read_state(self, instance_directory: Path) -> JSONValue:
        """Read protected task-neutral state twice without exposing its transport."""

        _verify_runtime(self._actor, self._settings.command_timeout_seconds)
        instance = _existing_instance_directory(instance_directory)
        transport = _ChildTransport(
            self._actor.python,
            Path(__file__).resolve().parent / "_state_runner.py",
            (self._release.descriptor.state_reader_factory,),
            cwd=self._actor.project_root,
            timeout=self._settings.command_timeout_seconds,
            role="actor",
        )
        proxy = StateSnapshotProxy(
            transport,
            state_schema=self._release.state_schema,
            events=self._state_events,
        )
        try:
            first = proxy.read(instance)
            proxy.read(instance)
            return first
        finally:
            proxy.close()


def prepare_release_v3_internal(
    release_path: Path,
    cache_root: Path,
    *,
    settings: PreparationSettingsV3 | None = None,
) -> OpenPreparedReleaseV3:
    selected = settings or PreparationSettingsV3(Path("/tmp/agent-env-foundry-v3-uv-cache"))
    cache = Path(cache_root).resolve()
    cache.mkdir(parents=True, exist_ok=True)
    source, ephemeral = _stage_release_v3(Path(release_path), cache)
    try:
        release = verify_release_v3_internal(source)
        release_cache = cache / "releases" / release.release_id
        if not release_cache.exists():
            release_cache.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(source, release_cache, symlinks=False)
    finally:
        if ephemeral:
            shutil.rmtree(source)
    release = verify_release_v3_internal(release_cache)
    actor = materialize_project(
        ProjectMaterializationInput(
            release_cache / release.descriptor.actor_project,
            release.descriptor.actor_project_digest,
            _module_name(release.descriptor.actor_factory),
            _FORBIDDEN_ACTOR_MODULES,
            "actor",
        ),
        cache / "runtimes" / release.release_id / "actor",
        settings=selected,
    )
    prepared = OpenPreparedReleaseV3(release, actor, selected)
    with prepared.open(cache / "probes" / release.release_id):
        pass
    return prepared


def _verify_live_tool_catalog(actor: ActorProxyV3, release: ValidatedReleaseV3) -> None:
    tools = actor.tools()
    digest = sha256_hex(canonical_bytes({"tools": [dict(item) for item in tools]}))
    if digest != release.receipt.tool_catalog_digest:
        raise PreparationExecutionErrorV3(
            "EnvironmentDefect",
            "sealed_tool_catalog_mismatch",
            "live actor ToolSpecs differ from the conformance receipt",
            expected=release.receipt.tool_catalog_digest,
            actual=digest,
        )


def _stage_release_v3(source: Path, cache: Path) -> tuple[Path, bool]:
    if source.is_dir() and not source.is_symlink():
        return source.resolve(), False
    if source.is_symlink() or not source.is_file():
        raise PreparationContractErrorV3("v3 release source must be a directory or ZIP file")
    incoming = cache / ".incoming" / uuid.uuid4().hex
    incoming.mkdir(parents=True)
    seen: set[PurePosixPath] = set()
    try:
        with zipfile.ZipFile(source, "r") as package:
            for info in package.infolist():
                relative = safe_member_path(info.filename, field="v3 ZIP member")
                if relative in seen:
                    raise PreparationContractErrorV3("v3 ZIP contains duplicate members")
                seen.add(relative)
                mode = (info.external_attr >> 16) & 0xFFFF
                target = incoming / relative
                if info.is_dir():
                    if stat.S_IFMT(mode) not in {0, stat.S_IFDIR}:
                        raise PreparationContractErrorV3(
                            "v3 ZIP contains an invalid directory member"
                        )
                    target.mkdir(parents=True, exist_ok=True)
                    target.chmod(stat.S_IMODE(mode))
                    continue
                if stat.S_IFMT(mode) not in {0, stat.S_IFREG}:
                    raise PreparationContractErrorV3("v3 ZIP contains a non-regular member")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(package.read(info))
                target.chmod(stat.S_IMODE(mode))
        verify_release_v3_internal(incoming)
        return incoming, True
    except (OSError, zipfile.BadZipFile) as exc:
        shutil.rmtree(incoming, ignore_errors=True)
        raise PreparationExecutionErrorV3(
            "EnvironmentDefect",
            "release_zip_invalid",
            f"cannot extract v3 release: {exc}",
        ) from exc
    except Exception:
        shutil.rmtree(incoming, ignore_errors=True)
        raise


def _existing_instance_directory(path: Path) -> Path:
    requested = Path(path)
    if requested.is_symlink() or not requested.is_dir():
        raise PreparationContractErrorV3("instance_directory must be a real directory")
    return requested.resolve()


def _instance_directory(path: Path) -> Path:
    requested = Path(path)
    if requested.is_symlink() or (requested.exists() and not requested.is_dir()):
        raise PreparationContractErrorV3("instance_directory must be a real directory")
    requested.mkdir(parents=True, exist_ok=True)
    return requested.resolve()


__all__ = [
    "ActorProxyV3",
    "OpenPreparedReleaseV3",
    "OpenPreparedSessionV3",
    "PreparationContractErrorV3",
    "PreparationExecutionErrorV3",
    "PreparationSettingsV3",
    "PreparedReleaseIdentityV3",
    "PreparedSessionIdentityV3",
    "StateSnapshotEventV3",
    "prepare_release_v3_internal",
]
