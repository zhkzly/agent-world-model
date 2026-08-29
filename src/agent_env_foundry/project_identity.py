"""One canonical path/mode/content identity for authored Python projects."""

from __future__ import annotations

import hashlib
import shutil
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

import rfc8785

ProjectRole = Literal["actor", "semantics", "verifier"]

_COMMON_EXCLUDED_PARTS = frozenset(
    {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "__pycache__",
        "dist",
    }
)
_ROLE_EXCLUDED_PARTS: dict[ProjectRole, frozenset[str]] = {
    "actor": frozenset(),
    "semantics": frozenset({"candidate-view"}),
    "verifier": frozenset({"actor-view"}),
}
_ROLE_EXCLUDED_NAMES: dict[ProjectRole, frozenset[str]] = {
    "actor": frozenset({"BUILDER_PROJECTION.json", "ENVIRONMENT_CONTRACT.md"}),
    "semantics": frozenset(
        {
            "EXPECTED_TASK_SEMANTICS.json",
            "PUBLIC_SURFACE.json",
            "TASK_SEMANTICS_CONTRACT.md",
            "CANDIDATE_VIEW_MANIFEST.json",
        }
    ),
    "verifier": frozenset(
        {
            "EXPECTED_TASK_SEMANTICS.json",
            "PUBLIC_SURFACE.json",
            "QUALIFICATION_VERIFIER_CONTRACT.md",
            "ACTOR_VIEW_MANIFEST.json",
        }
    ),
}


class ProjectIdentityError(ValueError):
    def __init__(self, code: str, message: str, *, path: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.path = path


@dataclass(frozen=True, slots=True)
class ProjectFileRecord:
    path: str
    mode: int
    digest: str

    def to_document(self) -> dict[str, object]:
        return {"path": self.path, "mode": self.mode, "digest": self.digest}


def project_files(root: Path, role: ProjectRole) -> tuple[Path, ...]:
    base = Path(root)
    if base.is_symlink() or not base.is_dir():
        raise ProjectIdentityError(
            "project_root_invalid",
            "project root must be a non-symlink directory",
            path=str(base),
        )
    excluded_parts = _COMMON_EXCLUDED_PARTS | _ROLE_EXCLUDED_PARTS[role]
    excluded_names = _ROLE_EXCLUDED_NAMES[role]
    files: list[Path] = []
    for path in base.rglob("*"):
        relative = path.relative_to(base)
        if any(part in excluded_parts for part in relative.parts):
            continue
        if path.is_symlink():
            raise ProjectIdentityError(
                "project_symlink_forbidden",
                "project identity does not accept symlinks",
                path=relative.as_posix(),
            )
        if path.is_file() and path.name not in excluded_names:
            files.append(path)
    return tuple(sorted(files, key=lambda item: item.relative_to(base).as_posix()))


def project_records(root: Path, role: ProjectRole) -> tuple[ProjectFileRecord, ...]:
    base = Path(root)
    return tuple(
        ProjectFileRecord(
            path.relative_to(base).as_posix(),
            stat.S_IMODE(path.stat().st_mode),
            hashlib.sha256(path.read_bytes()).hexdigest(),
        )
        for path in project_files(base, role)
    )


def project_digest(
    records: tuple[ProjectFileRecord, ...],
    *,
    require_locked_project: bool,
) -> str:
    paths = tuple(item.path for item in records)
    if paths != tuple(sorted(paths)) or len(set(paths)) != len(paths):
        raise ProjectIdentityError("project_records_invalid", "project records must be unique")
    if require_locked_project and not {"pyproject.toml", "uv.lock"} <= set(paths):
        raise ProjectIdentityError(
            "project_lock_incomplete",
            "project identity requires pyproject.toml and uv.lock",
        )
    return hashlib.sha256(
        rfc8785.dumps(cast(Any, {"files": [item.to_document() for item in records]}))
    ).hexdigest()


def compute_authored_project_digest(
    root: Path,
    role: ProjectRole,
    *,
    require_locked_project: bool = False,
) -> str:
    return project_digest(
        project_records(root, role),
        require_locked_project=require_locked_project,
    )


def copy_authored_project(source: Path, destination: Path, role: ProjectRole) -> str:
    source_root = Path(source)
    target_root = Path(destination)
    records = project_records(source_root, role)
    expected = project_digest(records, require_locked_project=True)
    if target_root.exists():
        raise ProjectIdentityError(
            "project_destination_exists",
            "project copy destination already exists",
            path=str(target_root),
        )
    target_root.mkdir(parents=True)
    for record in records:
        source_path = source_root / record.path
        actual = ProjectFileRecord(
            record.path,
            stat.S_IMODE(source_path.stat().st_mode),
            hashlib.sha256(source_path.read_bytes()).hexdigest(),
        )
        if source_path.is_symlink() or actual != record:
            raise ProjectIdentityError(
                "project_source_changed",
                "project source changed while being copied",
                path=record.path,
            )
        target = target_root / record.path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_path, target)
        target.chmod(record.mode)
    actual_copy = compute_authored_project_digest(
        target_root,
        role,
        require_locked_project=True,
    )
    if actual_copy != expected:
        raise ProjectIdentityError(
            "project_copy_mismatch",
            "copied project differs from source identity",
        )
    return expected


__all__ = [
    "ProjectFileRecord",
    "ProjectIdentityError",
    "ProjectRole",
    "compute_authored_project_digest",
    "copy_authored_project",
    "project_digest",
    "project_files",
    "project_records",
]
