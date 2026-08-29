"""Immutable inputs for the release-local TaskSemantics author."""

from __future__ import annotations

import hashlib
import stat
from dataclasses import dataclass
from pathlib import Path

EXPECTED_TASK_SEMANTICS_NAME = "EXPECTED_TASK_SEMANTICS.json"
PUBLIC_SURFACE_NAME = "PUBLIC_SURFACE.json"
TASK_SEMANTICS_CONTRACT_NAME = "TASK_SEMANTICS_CONTRACT.md"
VIEW_NAME = "candidate-view"
VIEW_MANIFEST_NAME = "CANDIDATE_VIEW_MANIFEST.json"


class SemanticsInputError(ValueError):
    """A frozen TaskSemantics author input changed after Host staging."""


@dataclass(frozen=True)
class ViewFile:
    path: str
    digest: str


@dataclass(frozen=True)
class CandidateViewManifest:
    candidate_digest: str
    files: tuple[ViewFile, ...]
    view_digest: str

    def to_document(self) -> dict[str, object]:
        return {
            "format": "candidate-view/1",
            "candidate_digest": self.candidate_digest,
            "files": [{"path": item.path, "digest": item.digest} for item in self.files],
            "view_digest": self.view_digest,
        }


@dataclass(frozen=True)
class PreparedSemanticsAuthorWorkspace:
    root: Path
    input_digests: dict[str, str]
    view_manifest: CandidateViewManifest

    def verify_inputs(self) -> None:
        for name, digest in self.input_digests.items():
            _verify_readonly(self.root / name, digest, "TaskSemantics author input")
        _verify_staged_view(self.root / VIEW_NAME, self.view_manifest)


def _verify_staged_view(view: Path, manifest: CandidateViewManifest) -> None:
    actual = {
        path.relative_to(view).as_posix()
        for path in view.rglob("*")
        if path.is_file() or path.is_symlink()
    }
    expected = {item.path for item in manifest.files}
    if actual != expected:
        raise SemanticsInputError("Candidate view members differ from its Host manifest")
    directories = (view, *(path for path in view.rglob("*") if path.is_dir()))
    if any(stat.S_IMODE(path.stat().st_mode) != 0o555 for path in directories):
        raise SemanticsInputError("Candidate view directories must remain read-only")
    for item in manifest.files:
        _verify_readonly(view / item.path, item.digest, "candidate view member")


def _verify_readonly(path: Path, digest: str, role: str) -> None:
    actual = (
        hashlib.sha256(path.read_bytes()).hexdigest()
        if path.is_file() and not path.is_symlink()
        else None
    )
    mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else None
    if actual != digest or mode != 0o444:
        raise SemanticsInputError(f"{role} changed after Host staging: {path}")
