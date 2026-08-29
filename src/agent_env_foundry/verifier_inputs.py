"""Immutable inputs for the mutually blind Qualification Verifier Author."""

from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass
from pathlib import Path

from agent_env_foundry.builder import candidate_files, compute_candidate_digest
from agent_env_foundry.frozen_inputs import verify_readonly, verify_staged_view
from agent_env_foundry.qualification_contracts import PublicSurfaceManifest
from agent_env_foundry.release import canonical_bytes
from agent_env_foundry.semantics_inputs import (
    EXPECTED_TASK_SEMANTICS_NAME,
    PUBLIC_SURFACE_NAME,
    ViewFile,
)

ACTOR_VIEW_NAME = "actor-view"
ACTOR_VIEW_MANIFEST_NAME = "ACTOR_VIEW_MANIFEST.json"
QUALIFICATION_VERIFIER_CONTRACT_NAME = "QUALIFICATION_VERIFIER_CONTRACT.md"


class VerifierInputError(ValueError):
    """A frozen Verifier Author input changed after Host staging."""


@dataclass(frozen=True)
class ActorViewManifest:
    actor_digest: str
    files: tuple[ViewFile, ...]
    view_digest: str

    def to_document(self) -> dict[str, object]:
        return {
            "format": "actor-view/1",
            "actor_digest": self.actor_digest,
            "files": [{"path": item.path, "digest": item.digest} for item in self.files],
            "view_digest": self.view_digest,
        }


@dataclass(frozen=True)
class PreparedVerifierAuthorWorkspace:
    root: Path
    input_digests: dict[str, str]
    view_manifest: ActorViewManifest

    def verify_inputs(self) -> None:
        expected_names = {
            EXPECTED_TASK_SEMANTICS_NAME,
            PUBLIC_SURFACE_NAME,
            QUALIFICATION_VERIFIER_CONTRACT_NAME,
            ACTOR_VIEW_MANIFEST_NAME,
        }
        if set(self.input_digests) != expected_names:
            raise VerifierInputError("Verifier Author frozen input set is incomplete")
        for name, digest in self.input_digests.items():
            verify_readonly(
                self.root / name,
                digest,
                "Verifier Author input",
                error_type=VerifierInputError,
            )
        verify_staged_view(
            self.root / ACTOR_VIEW_NAME,
            self.view_manifest,
            role="Actor view",
            error_type=VerifierInputError,
        )


def prepare_verifier_author_workspace(
    destination: Path,
    *,
    actor_root: Path,
    actor_digest: str,
    expected_semantics_payload: bytes,
    expected_semantics_digest: str,
    public_surface: PublicSurfaceManifest,
) -> PreparedVerifierAuthorWorkspace:
    """Stage the verifier's mutually blind immutable inputs from frozen Host bytes."""

    root = Path(destination).resolve()
    if root.exists() and (not root.is_dir() or any(root.iterdir())):
        raise VerifierInputError("Verifier Author workspace must be absent or empty")
    root.mkdir(parents=True, exist_ok=True)
    actor = Path(actor_root).resolve()
    actual_actor_digest = compute_candidate_digest(actor)
    if actual_actor_digest != actor_digest:
        raise VerifierInputError("Actor project digest differs before verifier staging")
    if hashlib.sha256(expected_semantics_payload).hexdigest() != expected_semantics_digest:
        raise VerifierInputError("Expected semantics digest differs before verifier staging")
    if not isinstance(public_surface, PublicSurfaceManifest):
        raise VerifierInputError("Verifier Author requires one frozen public-surface/2 manifest")

    view = root / ACTOR_VIEW_NAME
    view.mkdir()
    records: list[ViewFile] = []
    for source in candidate_files(actor):
        relative = source.relative_to(actor)
        target = view / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        target.chmod(0o444)
        records.append(
            ViewFile(relative.as_posix(), hashlib.sha256(target.read_bytes()).hexdigest())
        )
    for directory in sorted(
        (path for path in view.rglob("*") if path.is_dir()),
        reverse=True,
    ):
        directory.chmod(0o555)
    view.chmod(0o555)
    view_preimage = {
        "actor_digest": actor_digest,
        "files": [{"path": item.path, "digest": item.digest} for item in records],
    }
    manifest = ActorViewManifest(
        actor_digest,
        tuple(records),
        hashlib.sha256(canonical_bytes(view_preimage)).hexdigest(),
    )

    payloads = {
        EXPECTED_TASK_SEMANTICS_NAME: expected_semantics_payload,
        PUBLIC_SURFACE_NAME: canonical_bytes(public_surface.to_document()),
        ACTOR_VIEW_MANIFEST_NAME: canonical_bytes(manifest.to_document()),
        QUALIFICATION_VERIFIER_CONTRACT_NAME: (
            Path(__file__).parent
            / "runtime_skills/qualification-verifier-codegen/QUALIFICATION_VERIFIER_CONTRACT.md"
        ).read_bytes(),
    }
    input_digests: dict[str, str] = {}
    for name, payload in payloads.items():
        path = root / name
        path.write_bytes(payload)
        path.chmod(0o444)
        input_digests[name] = hashlib.sha256(payload).hexdigest()
    prepared = PreparedVerifierAuthorWorkspace(root, input_digests, manifest)
    prepared.verify_inputs()
    return prepared


__all__ = [
    "ACTOR_VIEW_MANIFEST_NAME",
    "ACTOR_VIEW_NAME",
    "EXPECTED_TASK_SEMANTICS_NAME",
    "PUBLIC_SURFACE_NAME",
    "QUALIFICATION_VERIFIER_CONTRACT_NAME",
    "ActorViewManifest",
    "PreparedVerifierAuthorWorkspace",
    "VerifierInputError",
    "prepare_verifier_author_workspace",
]
