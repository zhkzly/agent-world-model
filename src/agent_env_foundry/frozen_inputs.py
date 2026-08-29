"""Shared immutable-file and read-only-view checks for isolated code authors."""

from __future__ import annotations

import hashlib
import stat
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol


class ViewFileLike(Protocol):
    @property
    def path(self) -> str: ...

    @property
    def digest(self) -> str: ...


class ViewManifestLike(Protocol):
    @property
    def files(self) -> Sequence[ViewFileLike]: ...


def verify_staged_view(
    view: Path,
    manifest: ViewManifestLike,
    *,
    role: str,
    error_type: type[ValueError],
) -> None:
    actual = {
        path.relative_to(view).as_posix()
        for path in view.rglob("*")
        if path.is_file() or path.is_symlink()
    }
    expected = {item.path for item in manifest.files}
    if actual != expected:
        raise error_type(f"{role} members differ from its Host manifest")
    directories = (view, *(path for path in view.rglob("*") if path.is_dir()))
    if any(stat.S_IMODE(path.stat().st_mode) != 0o555 for path in directories):
        raise error_type(f"{role} directories must remain read-only")
    for item in manifest.files:
        verify_readonly(
            view / item.path,
            item.digest,
            f"{role} member",
            error_type=error_type,
        )


def verify_readonly(
    path: Path,
    digest: str,
    role: str,
    *,
    error_type: type[ValueError],
) -> None:
    actual = (
        hashlib.sha256(path.read_bytes()).hexdigest()
        if path.is_file() and not path.is_symlink()
        else None
    )
    mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else None
    if actual != digest or mode != 0o444:
        raise error_type(f"{role} changed after Host staging: {path}")


__all__ = ["ViewFileLike", "ViewManifestLike", "verify_readonly", "verify_staged_view"]
