"""Crash-safe filesystem layout for the non-authoritative Tier A scene cache."""

from __future__ import annotations

import fcntl
import os
import re
import shutil
import uuid
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path

from agent_world.diagnostic_state import is_marked_test_node_diagnostic_state_root

from .scene import (
    MAX_ROOT_INDEX_ENTRIES,
    CoordinateScene,
    FrontierRecord,
    ObservabilityIndex,
    RunSceneIndex,
    ScopeIndexEntry,
)


class ObservabilityError(RuntimeError):
    """A safe Tier A cache path or payload could not be read or written."""

    def __init__(self, message: str, *, code: str = "observability") -> None:
        super().__init__(message)
        self.code = code


_SCOPE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
_CONTENT_HASH_PATTERN = re.compile(r"^sha256:([0-9a-f]{64})$")
_DEBUG_TRANSCRIPT_FILENAME_PATTERN = re.compile(r"^[0-9a-f]{64}\.txt$")


class ObservabilityRoot:
    """Own the bounded scene files rooted at ``<state_root>/observability``.

    The files are only a rebuildable projection, but writes still use an
    fsync-plus-replace discipline so a partial cache record is never mistaken
    for a complete scene.
    """

    def __init__(self, state_root: str | os.PathLike[str]) -> None:
        requested = Path(state_root).expanduser()
        if ".agent-world-live" in requested.parts and not is_marked_test_node_diagnostic_state_root(
            requested
        ):
            raise ObservabilityError(
                "observability cannot access the reserved live state directory"
            )
        if requested.exists() and requested.is_symlink():
            raise ObservabilityError("observability state root cannot be a symlink")
        requested.mkdir(parents=True, exist_ok=True)
        if requested.is_symlink() or not requested.is_dir():
            raise ObservabilityError("observability state root must be a real directory")
        self.state_root = requested.resolve(strict=True)
        self.root = self.state_root / "observability"
        self._ensure_directory(self.root)
        self._ensure_directory(self.root / "tmp")

    def scene_json_path(self, scope_id: str) -> Path:
        return self._scope_dir(scope_id) / "scene.json"

    def scene_markdown_path(self, scope_id: str) -> Path:
        return self._scope_dir(scope_id) / "scene.md"

    def coordinate_json_path(self, scope_id: str, coordinate_key: str) -> Path:
        filename = f"{self._coordinate_name(coordinate_key)}.json"
        return self._scope_dir(scope_id) / "coordinates" / filename

    def coordinate_markdown_path(self, scope_id: str, coordinate_key: str) -> Path:
        filename = f"{self._coordinate_name(coordinate_key)}.md"
        return self._scope_dir(scope_id) / "coordinates" / filename

    def frontier_path(self, scope_id: str, coordinate_key: str) -> Path:
        filename = f"{self._coordinate_name(coordinate_key)}.jsonl"
        return self._scope_dir(scope_id) / "frontier" / filename

    def subprocess_path(self, scope_id: str, coordinate_key: str) -> Path:
        filename = f"{self._coordinate_name(coordinate_key)}.json"
        return self._scope_dir(scope_id) / "subprocess" / filename

    @property
    def index_path(self) -> Path:
        return self.root / "index.json"

    def write_scene(self, scope_id: str, scene: RunSceneIndex, markdown: str) -> None:
        self._atomic_write(self.scene_json_path(scope_id), scene.stable_json_bytes())
        self._atomic_write(self.scene_markdown_path(scope_id), markdown.encode("utf-8"))
        self._touch_scope(scope_id)

    def write_coordinate(
        self,
        scope_id: str,
        scene: CoordinateScene,
        markdown: str,
    ) -> None:
        self._atomic_write(
            self.coordinate_json_path(scope_id, scene.coordinate_key),
            scene.stable_json_bytes(),
        )
        self._atomic_write(
            self.coordinate_markdown_path(scope_id, scene.coordinate_key),
            markdown.encode("utf-8"),
        )
        self._touch_scope(scope_id)

    def write_subprocess(
        self,
        scope_id: str,
        coordinate_key: str,
        payload: bytes,
    ) -> None:
        """Materialize one on-demand, non-authoritative subprocess view."""

        self._atomic_write(self.subprocess_path(scope_id, coordinate_key), payload)
        self._touch_scope(scope_id)

    def write_debug_transcript(
        self,
        scope_id: str,
        filename: str,
        payload: bytes,
    ) -> Path:
        """Write one explicitly opted-in local transcript outside the read surface."""

        if _DEBUG_TRANSCRIPT_FILENAME_PATTERN.fullmatch(filename) is None:
            raise ObservabilityError("debug transcript filename is invalid")
        directory = self._scope_dir(scope_id) / "_debug"
        destination = directory / filename
        self._atomic_write(destination, payload)
        self._touch_scope(scope_id)
        return destination

    def read_scene(self, scope_id: str) -> RunSceneIndex | None:
        """Read a cached map layer without creating a scope directory."""

        raw = self._read_optional(self._scope_path(scope_id) / "scene.json")
        if raw is None:
            return None
        try:
            return RunSceneIndex.model_validate_json(raw)
        except Exception as exc:
            raise ObservabilityError("invalid observability scene cache") from exc

    def read_coordinate(self, scope_id: str, coordinate_key: str) -> CoordinateScene | None:
        """Read one cached terrain layer without changing the cache layout."""

        filename = f"{self._coordinate_name(coordinate_key)}.json"
        raw = self._read_optional(self._scope_path(scope_id) / "coordinates" / filename)
        if raw is None:
            return None
        try:
            return CoordinateScene.model_validate_json(raw)
        except Exception as exc:
            raise ObservabilityError("invalid observability coordinate cache") from exc

    def read_frontier(self, scope_id: str, coordinate_key: str) -> tuple[FrontierRecord, ...]:
        """Read one append-only compact frontier history without creating cache paths."""

        filename = f"{self._coordinate_name(coordinate_key)}.jsonl"
        raw = self._read_optional(self._scope_path(scope_id) / "frontier" / filename)
        if raw is None:
            return ()
        records: list[FrontierRecord] = []
        for line in raw.splitlines():
            if not line:
                continue
            try:
                record = FrontierRecord.model_validate_json(line)
            except Exception as exc:
                raise ObservabilityError("invalid frontier cache record") from exc
            if record.coordinate_key != coordinate_key:
                raise ObservabilityError("frontier cache record has the wrong coordinate")
            records.append(record)
        return tuple(records)

    def append_frontier_once(self, scope_id: str, record: FrontierRecord) -> None:
        """Append one compact attempt sample, avoiding duplicate hook retries."""

        path = self.frontier_path(scope_id, record.coordinate_key)
        existing = self._read_optional(path)
        if existing is not None:
            for line in existing.splitlines():
                if not line:
                    continue
                try:
                    parsed = FrontierRecord.model_validate_json(line)
                except Exception as exc:
                    raise ObservabilityError("invalid frontier cache record") from exc
                if parsed.attempt_ref_revision == record.attempt_ref_revision:
                    return
        self._append(path, record.stable_json_bytes() + b"\n")
        self._touch_scope(scope_id)

    def prune_scopes(
        self,
        *,
        keep_last: int,
        preserve_scope_ids: Iterable[str] = (),
    ) -> tuple[str, ...]:
        """Delete old Tier A scope directories without following links.

        Tier A is a rebuildable cache, so retention is deliberately scoped to
        its per-scope directories.  The durable Work heads, Artifacts, and
        Tier B SQLite evidence are never considered deletion candidates.
        """

        if isinstance(keep_last, bool) or keep_last < 1:
            raise ObservabilityError("Tier A retention must keep at least one scope")
        preserved = {self._scope_path(scope_id).name for scope_id in preserve_scope_ids}
        entries: list[tuple[int, str, Path]] = []
        for entry in self.root.iterdir():
            if entry.name == "tmp" or _SCOPE_PATTERN.fullmatch(entry.name) is None:
                continue
            if entry.is_symlink():
                raise ObservabilityError("observability scope directory cannot be a symlink")
            if not entry.is_dir():
                continue
            try:
                mtime_ns = entry.stat(follow_symlinks=False).st_mtime_ns
            except OSError as exc:
                raise ObservabilityError("cannot inspect observability scope retention") from exc
            entries.append((mtime_ns, entry.name, entry))

        ordered = sorted(entries, key=lambda item: (item[0], item[1]), reverse=True)
        retained = {name for _mtime, name, _path in ordered[:keep_last]} | preserved
        removed: list[str] = []
        for _mtime, name, directory in ordered:
            if name in retained:
                continue
            if directory.parent != self.root or directory.is_symlink() or not directory.is_dir():
                raise ObservabilityError("unsafe observability scope retention target")
            try:
                shutil.rmtree(directory)
            except OSError as exc:
                raise ObservabilityError("cannot remove expired observability scope") from exc
            removed.append(name)

        if removed:
            self._remove_scopes_from_index(frozenset(removed))
        return tuple(removed)

    def update_index(self, scene: RunSceneIndex) -> None:
        """Best-effort, bounded cross-scope pointer update under one local lock."""

        with self._index_lock():
            current = self._read_index()
            entry = ScopeIndexEntry(
                scope_id=scene.scope_id,
                overall_status=scene.overall_status,
                updated_at=scene.watermark.projected_at,
                stuck_coordinate_key=(
                    scene.stuck_coordinate.coordinate_key
                    if scene.stuck_coordinate is not None
                    else None
                ),
            )
            by_scope = {item.scope_id: item for item in current.entries}
            by_scope[entry.scope_id] = entry
            ordered = tuple(
                sorted(
                    by_scope.values(),
                    key=lambda item: (item.updated_at, item.scope_id),
                    reverse=True,
                )
            )
            index = ObservabilityIndex(
                entries=ordered[:MAX_ROOT_INDEX_ENTRIES],
                overflow_count=max(0, len(ordered) - MAX_ROOT_INDEX_ENTRIES),
            )
            self._atomic_write(self.index_path, index.stable_json_bytes())

    def _scope_dir(self, scope_id: str) -> Path:
        path = self._scope_path(scope_id)
        self._ensure_directory(path)
        return path

    def _scope_path(self, scope_id: str) -> Path:
        if _SCOPE_PATTERN.fullmatch(scope_id) is None:
            raise ObservabilityError("scope id cannot safely name an observability directory")
        return self.root / scope_id

    @staticmethod
    def _coordinate_name(coordinate_key: str) -> str:
        match = _CONTENT_HASH_PATTERN.fullmatch(coordinate_key)
        if match is None:
            raise ObservabilityError("coordinate key must be a sha256 content hash")
        return match.group(1)

    def _read_index(self) -> ObservabilityIndex:
        raw = self._read_optional(self.index_path)
        if raw is None:
            return ObservabilityIndex()
        try:
            return ObservabilityIndex.model_validate_json(raw)
        except Exception as exc:
            raise ObservabilityError("invalid observability root index") from exc

    def _remove_scopes_from_index(self, removed: frozenset[str]) -> None:
        with self._index_lock():
            current = self._read_index()
            entries = tuple(item for item in current.entries if item.scope_id not in removed)
            if len(entries) == len(current.entries):
                return
            self._atomic_write(
                self.index_path,
                ObservabilityIndex(
                    entries=entries,
                    overflow_count=current.overflow_count,
                ).stable_json_bytes(),
            )

    def _touch_scope(self, scope_id: str) -> None:
        path = self._scope_dir(scope_id)
        try:
            os.utime(path, None, follow_symlinks=False)
        except OSError as exc:
            raise ObservabilityError("cannot update observability scope retention") from exc

    @contextmanager
    def _index_lock(self) -> Iterator[None]:
        path = self.root / "index.lock"
        descriptor = os.open(
            path,
            os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            yield
        finally:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)

    def _ensure_directory(self, path: Path) -> None:
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        if path.is_symlink() or not path.is_dir():
            raise ObservabilityError("observability cache path must be a real directory")

    def _atomic_write(self, destination: Path, content: bytes) -> None:
        self._ensure_directory(destination.parent)
        if destination.exists() and destination.is_symlink():
            raise ObservabilityError("observability cache destination cannot be a symlink")
        temporary = self.root / "tmp" / f"{uuid.uuid4().hex}.tmp"
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        try:
            with os.fdopen(descriptor, "wb", closefd=True) as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, destination)
            directory = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            temporary.unlink(missing_ok=True)

    def _append(self, destination: Path, content: bytes) -> None:
        self._ensure_directory(destination.parent)
        if destination.exists() and destination.is_symlink():
            raise ObservabilityError("observability cache destination cannot be a symlink")
        descriptor = os.open(
            destination,
            os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        try:
            with os.fdopen(descriptor, "ab", closefd=True) as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
        finally:
            try:
                os.close(descriptor)
            except OSError:
                pass

    @staticmethod
    def _read_optional(path: Path) -> bytes | None:
        if not path.exists():
            return None
        if path.is_symlink():
            raise ObservabilityError("observability cache source cannot be a symlink")
        try:
            descriptor = os.open(
                path,
                os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
            )
        except OSError as exc:
            raise ObservabilityError("cannot safely read observability cache") from exc
        with os.fdopen(descriptor, "rb", closefd=True) as stream:
            return stream.read()


__all__ = ["ObservabilityError", "ObservabilityRoot"]
