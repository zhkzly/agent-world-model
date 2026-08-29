"""Immutable inputs for the release-local TaskSemantics author."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from agent_env_foundry.builder import candidate_files, compute_candidate_digest
from agent_env_foundry.frozen_inputs import (
    stage_readonly_view,
    verify_readonly,
    verify_staged_view,
)
from agent_env_foundry.qualification_contracts import PublicSurfaceManifest
from agent_env_foundry.release import canonical_bytes
from agent_env_foundry.semantics_wire import semantics_wire_document

EXPECTED_TASK_SEMANTICS_NAME = "EXPECTED_TASK_SEMANTICS.json"
PUBLIC_SURFACE_NAME = "PUBLIC_SURFACE.json"
TASK_SEMANTICS_CONTRACT_NAME = "TASK_SEMANTICS_CONTRACT.md"
TASK_SEMANTICS_WIRE_NAME = "TASK_SEMANTICS_WIRE.json"
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
        expected_names = {
            EXPECTED_TASK_SEMANTICS_NAME,
            PUBLIC_SURFACE_NAME,
            TASK_SEMANTICS_CONTRACT_NAME,
            TASK_SEMANTICS_WIRE_NAME,
            VIEW_MANIFEST_NAME,
        }
        if set(self.input_digests) != expected_names:
            raise SemanticsInputError("TaskSemantics Author frozen input set is incomplete")
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


def prepare_semantics_author_workspace(
    destination: Path,
    *,
    actor_root: Path,
    actor_digest: str,
    expected_semantics_payload: bytes,
    expected_semantics_digest: str,
    public_surface: PublicSurfaceManifest,
) -> PreparedSemanticsAuthorWorkspace:
    root = Path(destination).resolve()
    if root.exists() and (not root.is_dir() or any(root.iterdir())):
        raise SemanticsInputError("TaskSemantics Author workspace must be absent or empty")
    root.mkdir(parents=True, exist_ok=True)
    actor = Path(actor_root).resolve()
    actual_actor_digest = compute_candidate_digest(actor)
    if actual_actor_digest != actor_digest:
        raise SemanticsInputError("Actor project digest differs before semantics staging")
    if hashlib.sha256(expected_semantics_payload).hexdigest() != expected_semantics_digest:
        raise SemanticsInputError("Expected semantics digest differs before semantics staging")
    if not isinstance(public_surface, PublicSurfaceManifest):
        raise SemanticsInputError(
            "TaskSemantics Author requires one frozen public-surface/2 manifest"
        )

    records = tuple(
        ViewFile(path, digest)
        for path, digest in stage_readonly_view(
            actor,
            root / VIEW_NAME,
            candidate_files(actor),
        )
    )
    view_preimage = {
        "candidate_digest": actor_digest,
        "files": [{"path": item.path, "digest": item.digest} for item in records],
    }
    manifest = CandidateViewManifest(
        actor_digest,
        records,
        hashlib.sha256(canonical_bytes(view_preimage)).hexdigest(),
    )
    payloads = {
        EXPECTED_TASK_SEMANTICS_NAME: expected_semantics_payload,
        PUBLIC_SURFACE_NAME: canonical_bytes(public_surface.to_document()),
        VIEW_MANIFEST_NAME: canonical_bytes(manifest.to_document()),
        TASK_SEMANTICS_CONTRACT_NAME: (
            Path(__file__).parent
            / "runtime_skills/task-semantics-codegen/TASK_SEMANTICS_CONTRACT.md"
        ).read_bytes(),
        TASK_SEMANTICS_WIRE_NAME: canonical_bytes(semantics_wire_document()),
    }
    input_digests: dict[str, str] = {}
    for name, payload in payloads.items():
        path = root / name
        path.write_bytes(payload)
        path.chmod(0o444)
        input_digests[name] = hashlib.sha256(payload).hexdigest()
    prepared = PreparedSemanticsAuthorWorkspace(root, input_digests, manifest)
    prepared.verify_inputs()
    return prepared


__all__ = [
    "EXPECTED_TASK_SEMANTICS_NAME",
    "PUBLIC_SURFACE_NAME",
    "TASK_SEMANTICS_CONTRACT_NAME",
    "TASK_SEMANTICS_WIRE_NAME",
    "VIEW_MANIFEST_NAME",
    "VIEW_NAME",
    "CandidateViewManifest",
    "PreparedSemanticsAuthorWorkspace",
    "SemanticsInputError",
    "ViewFile",
    "prepare_semantics_author_workspace",
]
