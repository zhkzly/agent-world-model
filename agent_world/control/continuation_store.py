"""Private durable continuation state for one WorkAttempt.

Opaque backend sessions and the last shape-valid candidate are deliberately not
Artifact DAG members and never enter release packages or public telemetry.  A
public WorkAttempt stores only ``session_commitment``; this private store can
resume only when every binding digest still matches.
"""

from __future__ import annotations

import hashlib
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

from pydantic import AwareDatetime, JsonValue, model_validator

from agent_world.contracts import (
    ContentHash,
    Identifier,
    NonEmptyStr,
    V2Contract,
    canonical_json_bytes,
    sha256_digest,
)
from agent_world.invocation.contracts import InvocationSession
from agent_world.research.security import assert_secret_free

_MAX_PRIVATE_CANDIDATE_BYTES = 4 * 1024 * 1024


class ContinuationStoreError(RuntimeError):
    """Private continuation state is unsafe, conflicting, or corrupted."""


class NodeContinuationRecord(V2Contract):
    continuation_id: Identifier
    work_id: Identifier
    attempt_id: Identifier
    thread_id: NonEmptyStr
    lineage_id: Identifier
    workspace: NonEmptyStr
    profile_digest: ContentHash
    codex_config_digest: ContentHash
    model: NonEmptyStr
    output_schema_digest: ContentHash
    previous_candidate: JsonValue | None = None
    candidate_commitment: ContentHash | None = None
    allowed_mutation_roots: tuple[NonEmptyStr, ...] = ()
    session_commitment: ContentHash
    created_at: AwareDatetime

    @model_validator(mode="after")
    def validate_private_binding(self) -> NodeContinuationRecord:
        if not Path(self.workspace).is_absolute():
            raise ValueError("continuation workspace must be absolute")
        if len(set(self.allowed_mutation_roots)) != len(self.allowed_mutation_roots):
            raise ValueError("continuation mutation roots must be unique")
        candidate_bytes = canonical_json_bytes(self.previous_candidate)
        if len(candidate_bytes) > _MAX_PRIVATE_CANDIDATE_BYTES:
            raise ValueError("private continuation candidate exceeds 4 MiB")
        expected_candidate = (
            sha256_digest(candidate_bytes) if self.previous_candidate is not None else None
        )
        if self.candidate_commitment != expected_candidate:
            raise ValueError("continuation candidate commitment mismatch")
        expected_session = self.compute_session_commitment(
            thread_id=self.thread_id,
            lineage_id=self.lineage_id,
            workspace=self.workspace,
            profile_digest=self.profile_digest,
            codex_config_digest=self.codex_config_digest,
            model=self.model,
            output_schema_digest=self.output_schema_digest,
        )
        if self.session_commitment != expected_session:
            raise ValueError("continuation session commitment mismatch")
        return self

    @staticmethod
    def compute_session_commitment(
        *,
        thread_id: str,
        lineage_id: str,
        workspace: str,
        profile_digest: str,
        codex_config_digest: str,
        model: str,
        output_schema_digest: str,
    ) -> ContentHash:
        return sha256_digest(
            canonical_json_bytes(
                {
                    "thread_id": thread_id,
                    "lineage_id": lineage_id,
                    "workspace": workspace,
                    "profile_digest": profile_digest,
                    "codex_config_digest": codex_config_digest,
                    "model": model,
                    "output_schema_digest": output_schema_digest,
                }
            )
        )

    @classmethod
    def capture(
        cls,
        *,
        work_id: Identifier,
        attempt_id: Identifier,
        session: InvocationSession,
        model: str,
        output_schema_digest: ContentHash,
        previous_candidate: JsonValue | None,
        allowed_mutation_roots: tuple[str, ...],
    ) -> NodeContinuationRecord:
        candidate_commitment = (
            sha256_digest(canonical_json_bytes(previous_candidate))
            if previous_candidate is not None
            else None
        )
        profile_digest = cls._normalize_digest(session.profile_hash)
        config_digest = cls._normalize_digest(session.codex_config_sha256)
        workspace = str(session.workspace.resolve())
        session_commitment = cls.compute_session_commitment(
            thread_id=session.thread_id,
            lineage_id=session.lineage_id,
            workspace=workspace,
            profile_digest=profile_digest,
            codex_config_digest=config_digest,
            model=model,
            output_schema_digest=output_schema_digest,
        )
        identity = hashlib.sha256(
            f"{work_id}\0{attempt_id}\0{session_commitment}".encode()
        ).hexdigest()[:24]
        return cls(
            continuation_id=f"continuation:{identity}",
            work_id=work_id,
            attempt_id=attempt_id,
            thread_id=session.thread_id,
            lineage_id=session.lineage_id,
            workspace=workspace,
            profile_digest=profile_digest,
            codex_config_digest=config_digest,
            model=model,
            output_schema_digest=output_schema_digest,
            previous_candidate=previous_candidate,
            candidate_commitment=candidate_commitment,
            allowed_mutation_roots=allowed_mutation_roots,
            session_commitment=session_commitment,
            created_at=datetime.now(UTC),
        )

    def restore_session(self) -> InvocationSession:
        return InvocationSession(
            thread_id=self.thread_id,
            lineage_id=self.lineage_id,
            workspace=Path(self.workspace),
            profile_hash=self.profile_digest.removeprefix("sha256:"),
            codex_config_sha256=self.codex_config_digest.removeprefix("sha256:"),
        )

    @staticmethod
    def _normalize_digest(value: str) -> ContentHash:
        return value if value.startswith("sha256:") else f"sha256:{value}"


class NodeContinuationStore:
    """Permission-restricted immutable store for opaque continuation records."""

    def __init__(self, root: str | os.PathLike[str]) -> None:
        requested = Path(root).expanduser()
        if requested.exists() and requested.is_symlink():
            raise ContinuationStoreError("continuation root cannot be a symlink")
        requested.mkdir(mode=0o700, parents=True, exist_ok=True)
        if requested.is_symlink() or not requested.is_dir():
            raise ContinuationStoreError("continuation root must be a real directory")
        os.chmod(requested, 0o700)
        self.root = requested.resolve(strict=True)

    def save(
        self,
        record: NodeContinuationRecord,
        *,
        known_secret_values: tuple[str, ...] = (),
    ) -> NodeContinuationRecord:
        record = NodeContinuationRecord.model_validate(record.model_dump(mode="python"))
        content = record.stable_json_bytes()
        assert_secret_free(
            content,
            known_secret_values=known_secret_values,
            context="private continuation state",
        )
        destination = self._path(record.continuation_id)
        temporary = self.root / f".{uuid.uuid4().hex}.tmp"
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
            try:
                os.link(temporary, destination, follow_symlinks=False)
            except FileExistsError:
                if destination.read_bytes() != content:
                    raise ContinuationStoreError(
                        "continuation id already binds other state"
                    ) from None
            directory = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            temporary.unlink(missing_ok=True)
        return record

    def load_exact(
        self,
        continuation_id: Identifier,
        *,
        work_id: Identifier,
        session_commitment: ContentHash,
        model: str,
        output_schema_digest: ContentHash,
    ) -> NodeContinuationRecord | None:
        path = self._path(continuation_id)
        flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(path, flags)
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise ContinuationStoreError("cannot safely read continuation state") from exc
        with os.fdopen(descriptor, "rb", closefd=True) as stream:
            raw = stream.read()
        try:
            record = NodeContinuationRecord.model_validate_json(raw)
        except Exception as exc:
            raise ContinuationStoreError("invalid private continuation state") from exc
        if (
            record.continuation_id != continuation_id
            or record.work_id != work_id
            or record.session_commitment != session_commitment
            or record.model != model
            or record.output_schema_digest != output_schema_digest
        ):
            return None
        return record

    def _path(self, continuation_id: str) -> Path:
        key = hashlib.sha256(continuation_id.encode("utf-8")).hexdigest()
        return self.root / f"{key}.json"


__all__ = [
    "ContinuationStoreError",
    "NodeContinuationRecord",
    "NodeContinuationStore",
]
