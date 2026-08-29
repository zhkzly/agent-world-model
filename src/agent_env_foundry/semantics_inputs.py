"""Immutable inputs for the release-local TaskSemantics author."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from agent_env_foundry.frozen_inputs import verify_readonly, verify_staged_view

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
            verify_readonly(
                self.root / name,
                digest,
                "TaskSemantics author input",
                error_type=SemanticsInputError,
            )
        verify_staged_view(
            self.root / VIEW_NAME,
            self.view_manifest,
            role="Candidate view",
            error_type=SemanticsInputError,
        )
