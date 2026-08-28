"""Private Qualification runner that owns canonical environment-call journals."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import runpy
import shutil
import stat
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal, cast

import rfc8785

from agent_env_foundry.environment import ValidatedEnvironment, load_environment
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
_JOURNAL_ENV = "AGENT_ENV_FOUNDRY_JOURNAL"
_RUN_ID_ENV = "AGENT_ENV_FOUNDRY_RUN_ID"


class CandidateExecutionFailure(RuntimeError):
    """A canonical environment load/call failed inside a Qualifier probe."""

    def __init__(self, cause: Exception) -> None:
        super().__init__(str(cause))
        self.error_type = type(cause).__name__


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
        environment: ValidatedEnvironment,
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
        except Exception as exc:
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
    def __init__(self, path: Path, run_id: str) -> None:
        if not isinstance(run_id, str) or not run_id:
            raise ValueError("run_id must be a non-empty string")
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        self._stream = os.fdopen(descriptor, "wb")
        self._run_id = run_id
        self._next_seq = 1

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
        self._stream.write(rfc8785.dumps(event.to_document()) + b"\n")
        self._stream.flush()
        self._next_seq += 1

    def close(self) -> None:
        self._stream.close()


def _create_probe_session(
    release_path: Path,
    instances_root: Path,
    run_id: str,
    journal_path: Path,
) -> tuple[ProbeSession, _JournalRecorder]:
    release = release_path.resolve()
    instances = instances_root.resolve()
    instances.mkdir(parents=True, exist_ok=True)
    recorder = _JournalRecorder(journal_path, run_id)
    active_instances: set[str] = set()

    def open_environment(instance_key: str) -> RecordedEnvironment:
        _validate_instance_key(instance_key)
        if instance_key in active_instances:
            raise RuntimeError("instance already has an active environment handle")
        try:
            environment = load_environment(release, instances / instance_key)
        except Exception as exc:
            recorder.record(
                instance_key,
                "open",
                {},
                {
                    "host_exception": {
                        "type": type(exc).__name__,
                        "message": str(exc),
                    }
                },
            )
            raise CandidateExecutionFailure(exc) from exc
        recorder.record(instance_key, "open", {}, {"attached": True})
        active_instances.add(instance_key)
        return RecordedEnvironment(
            _ENVIRONMENT_TOKEN,
            environment,
            instance_key,
            recorder,
            active_instances.discard,
        )

    return ProbeSession(_SESSION_TOKEN, open_environment), recorder


def _run_public_probe(
    probe_path: Path,
    release_path: Path,
    instances_root: Path,
    run_id: str,
    journal_path: Path,
    mode: str,
) -> None:
    session, recorder = _create_probe_session(
        release_path,
        instances_root,
        run_id,
        journal_path,
    )
    original_argv = sys.argv
    original_path = sys.path[:]
    original_dont_write_bytecode = sys.dont_write_bytecode
    sys.argv = [str(probe_path), mode]
    sys.path.insert(0, str(release_path.resolve() / "src"))
    sys.dont_write_bytecode = True
    try:
        namespace = runpy.run_path(str(probe_path), run_name="qualification_public_probe")
        entry = namespace.get("run")
        if not callable(entry):
            raise TypeError("public_probe.py must define run(session, mode)")
        entry(session, mode)
    finally:
        sys.argv = original_argv
        sys.path[:] = original_path
        sys.dont_write_bytecode = original_dont_write_bytecode
        recorder.close()


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
        return set(arguments) == {"start"} and (
            arguments["start"] is None or isinstance(arguments["start"], dict)
        )
    if operation == "invoke":
        return (
            set(arguments) == {"tool_name", "arguments"}
            and isinstance(arguments["tool_name"], str)
            and isinstance(arguments["arguments"], dict)
        )
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


def _required_private_env(name: str) -> str:
    value = os.environ.pop(name, None)
    if not value:
        raise ValueError(f"missing private runner environment {name}")
    return value


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run one Host-journaled public probe")
    parser.add_argument("--probe", type=Path, required=True)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--instances", type=Path, required=True)
    parser.add_argument("--mode", required=True)
    arguments = parser.parse_args(argv)
    try:
        run_id = _required_private_env(_RUN_ID_ENV)
        journal = Path(_required_private_env(_JOURNAL_ENV))
        _run_public_probe(
            arguments.probe,
            arguments.release,
            arguments.instances,
            run_id,
            journal,
            arguments.mode,
        )
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
