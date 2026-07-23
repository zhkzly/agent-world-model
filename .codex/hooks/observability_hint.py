#!/usr/bin/env python3
"""Bounded, read-only observability discovery for Trellis hooks.

The hook deliberately reads only the configured non-live durable state. It
does not import the application composition root (which could create local
stores), and it never emits a free-form value from a job record. A scope is
shown only when it has the framework-generated ``*-job:<sha256-prefix>``
shape.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tomllib
from pathlib import Path

_CONFIG_MAX_BYTES = 64 * 1024
_DIRECT_HEAD_MAX_BYTES = 128 * 1024
_JOB_MAX_BYTES = 128 * 1024
_HASH_PATTERN = re.compile(r"^sha256:([0-9a-f]{64})$")
_HEAD_FILENAME_PATTERN = re.compile(r"^[0-9a-f]{64}\.json$")
_FRAMEWORK_JOB_ID_PATTERN = re.compile(r"^(?:generate|expand)-job:[0-9a-f]{24}$")
_TERMINAL_FAILURE_STATUSES = frozenset({"failed", "needs_human", "budget_exhausted"})


def failed_direct_observability_hint() -> str | None:
    """Return one safe scene command for the newest unsuccessful Direct job.

    A missing, malformed, symlinked, or reserved-live state is intentionally a
    silent no-op: hook discovery is advisory and must never affect a session.
    """

    scope_id = _failed_direct_scope_id()
    if scope_id is None:
        return None
    return (
        "Failed Direct job detected. Before acting, run "
        f"`uv run agent-world observe scene {scope_id}`; 先读 scene.md。"
    )


def _failed_direct_scope_id() -> str | None:
    state_root = _configured_state_root()
    if state_root is None or ".agent-world-live" in state_root.parts:
        return None

    heads_dir = state_root / "direct-jobs" / "heads"
    if not _is_real_directory(heads_dir):
        return None

    candidates: list[tuple[int, str, dict[str, object]]] = []
    try:
        entries = tuple(heads_dir.iterdir())
    except OSError:
        return None
    for entry in entries:
        if _HEAD_FILENAME_PATTERN.fullmatch(entry.name) is None:
            continue
        try:
            metadata = entry.stat(follow_symlinks=False)
        except OSError:
            continue
        if not stat.S_ISREG(metadata.st_mode):
            continue
        head = _read_json_object(entry, limit=_DIRECT_HEAD_MAX_BYTES)
        if head is None or head.get("status") not in _TERMINAL_FAILURE_STATUSES:
            continue
        candidates.append((metadata.st_mtime_ns, entry.name, head))

    for _mtime_ns, _name, head in sorted(candidates, reverse=True):
        scope_id = _scope_id_from_job_blob(state_root, head)
        if scope_id is not None:
            return scope_id
    return None


def _configured_state_root() -> Path | None:
    configured = os.environ.get("AGENT_WORLD_CONFIG")
    config_path = (
        Path(configured).expanduser()
        if configured
        else Path.home() / ".config" / "agent-world" / "config.toml"
    )
    config_path = Path(os.path.abspath(config_path))
    if ".agent-world-live" in config_path.parts:
        return None
    config = _read_toml_object(config_path)
    if config is None:
        return None
    raw_state_root = config.get("state_root")
    if not isinstance(raw_state_root, str) or not raw_state_root.strip():
        return None
    requested = Path(raw_state_root).expanduser()
    if not requested.is_absolute():
        requested = config_path.parent / requested
    return Path(os.path.abspath(requested))


def _scope_id_from_job_blob(state_root: Path, head: dict[str, object]) -> str | None:
    job_ref = head.get("job_ref")
    if not isinstance(job_ref, dict):
        return None
    if job_ref.get("artifact_type") != "control.environment_job":
        return None
    content_hash = job_ref.get("content_hash")
    size_bytes = job_ref.get("size_bytes")
    if (
        not isinstance(content_hash, str)
        or not isinstance(size_bytes, int)
        or isinstance(size_bytes, bool)
    ):
        return None
    if size_bytes < 1 or size_bytes > _JOB_MAX_BYTES:
        return None
    match = _HASH_PATTERN.fullmatch(content_hash)
    if match is None:
        return None
    digest = match.group(1)
    blob_path = state_root / "artifacts" / "blobs" / "sha256" / digest[:2] / digest
    if not _is_real_directory(blob_path.parent):
        return None
    blob = _read_bytes(blob_path, limit=size_bytes)
    if blob is None or len(blob) != size_bytes:
        return None
    if hashlib.sha256(blob).hexdigest() != digest:
        return None
    try:
        value = json.loads(blob.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict):
        return None
    job_id = value.get("job_id")
    if not isinstance(job_id, str) or _FRAMEWORK_JOB_ID_PATTERN.fullmatch(job_id) is None:
        return None
    return job_id


def _read_toml_object(path: Path) -> dict[str, object] | None:
    raw = _read_bytes(path, limit=_CONFIG_MAX_BYTES)
    if raw is None:
        return None
    try:
        value = tomllib.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _read_json_object(path: Path, *, limit: int) -> dict[str, object] | None:
    raw = _read_bytes(path, limit=limit)
    if raw is None:
        return None
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _read_bytes(path: Path, *, limit: int) -> bytes | None:
    if limit < 1:
        return None
    try:
        before = path.stat(follow_symlinks=False)
    except OSError:
        return None
    if not stat.S_ISREG(before.st_mode):
        return None
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
        )
    except OSError:
        return None
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            return None
        with os.fdopen(descriptor, "rb", closefd=True) as stream:
            data = stream.read(limit + 1)
        descriptor = -1
    except OSError:
        return None
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    return data if len(data) <= limit else None


def _is_real_directory(path: Path) -> bool:
    try:
        metadata = path.stat(follow_symlinks=False)
    except OSError:
        return False
    return stat.S_ISDIR(metadata.st_mode)
