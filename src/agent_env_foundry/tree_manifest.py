"""Deterministic filesystem-tree evidence for prepared runtime boundaries."""

from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import rfc8785


@dataclass(frozen=True, slots=True)
class TreeRecord:
    path: str
    object_type: str
    mode: int
    digest: str | None = None
    symlink_target: str | None = None

    def to_document(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class TreeManifest:
    records: tuple[TreeRecord, ...]
    digest: str

    def to_document(self) -> dict[str, object]:
        return asdict(self)


def tree_manifest(root: Path) -> TreeManifest:
    """Bind every object, mode, file byte and symlink target below ``root``."""

    base = Path(root)
    if not base.is_dir() or base.is_symlink():
        raise ValueError(f"manifest root must be a non-symlink directory: {base}")
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
    document: Any = {"records": [record.to_document() for record in records]}
    return TreeManifest(tuple(records), hashlib.sha256(rfc8785.dumps(document)).hexdigest())


__all__ = ["TreeManifest", "TreeRecord", "tree_manifest"]
