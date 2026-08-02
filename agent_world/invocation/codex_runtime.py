"""Resolve the exact Codex app-server executable a profile must authorize.

The outer Python worker and the SDK app-server both execute directly on the
host.  Therefore the same content-pinned executable has to be part of the
resolved Agent profile; leaving bundled-runtime discovery only in the worker
creates an invisible runtime dependency for the app-server.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal


class CodexRuntimeUnavailable(RuntimeError):
    """Raised when no verified app-server runtime can be bound to a profile."""


@dataclass(frozen=True, slots=True)
class ResolvedCodexRuntime:
    """One immutable executable identity usable by outer and inner Codex."""

    path: Path
    sha256: str
    source: Literal["configured", "sdk_bundled"]


def resolve_codex_runtime(configured: Path | None) -> ResolvedCodexRuntime:
    """Return a verified explicit runtime or the SDK-bundled one.

    The bundled resolution is cached for the process lifetime.  A later file
    change is still fail-closed: every materialized profile re-hashes this
    exact path before a worker starts.
    """

    if configured is not None:
        return _pin_runtime(configured, source="configured")
    return _resolve_sdk_bundled_runtime()


@lru_cache(maxsize=1)
def _resolve_sdk_bundled_runtime() -> ResolvedCodexRuntime:
    try:
        from codex_cli_bin import bundled_codex_path  # type: ignore[import-untyped]

        sdk_version = importlib.metadata.version("openai-codex")
        runtime_version = importlib.metadata.version("openai-codex-cli-bin")
    except (ImportError, importlib.metadata.PackageNotFoundError) as exc:
        raise CodexRuntimeUnavailable("SDK-bundled Codex runtime is unavailable") from exc
    if sdk_version != runtime_version:
        raise CodexRuntimeUnavailable(
            "SDK-bundled Codex runtime version does not match openai-codex"
        )
    return _pin_runtime(Path(bundled_codex_path()), source="sdk_bundled")


def _pin_runtime(
    candidate: Path,
    *,
    source: Literal["configured", "sdk_bundled"],
) -> ResolvedCodexRuntime:
    requested = candidate.expanduser()
    if requested.is_symlink():
        raise CodexRuntimeUnavailable("Codex runtime must not be a symbolic link")
    try:
        path = requested.resolve(strict=True)
    except OSError as exc:
        raise CodexRuntimeUnavailable("Codex runtime is unavailable") from exc
    if path.is_symlink() or not path.is_file() or not os.access(path, os.X_OK):
        raise CodexRuntimeUnavailable("Codex runtime must be a real executable file")
    return ResolvedCodexRuntime(
        path=path,
        sha256=_sha256(path),
        source=source,
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = [
    "CodexRuntimeUnavailable",
    "ResolvedCodexRuntime",
    "resolve_codex_runtime",
]
