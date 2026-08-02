"""Single-writer Direct Generation heads and durable request idempotency.

The mutable head is intentionally tiny.  Environment requests, jobs, run
snapshots, terminal results, and releases remain immutable Artifact Store or
Registry records; this store only performs compare-and-swap over their exact
references.
"""

from __future__ import annotations

import fcntl
import hashlib
import os
import re
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, model_validator

from agent_world.contracts import ArtifactRef, ContentHash, Identifier, V2Contract

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")

type DirectJobStatus = Literal[
    "running",
    "released",
    "failed",
    "needs_human",
    "budget_exhausted",
]


class DirectJobStoreError(RuntimeError):
    """Base error for Direct Generation head coordination."""


class DirectJobAlreadyRunningError(DirectJobStoreError):
    """The same request id currently has another process holding its lock."""


class DirectRequestConflictError(DirectJobStoreError):
    """A request id was reused for different canonical request semantics."""


class DirectJobHeadConflictError(DirectJobStoreError):
    """The durable Direct Generation head changed since it was read."""


class DirectJobResumeRequiredError(DirectJobStoreError):
    """A checkpoint exists but cannot be resumed without replaying unknown work."""


class DirectJobHead(V2Contract):
    """Mutable pointer to immutable Direct Generation state."""

    request_id: Identifier
    request_fingerprint: ContentHash
    request_ref: ArtifactRef
    job_ref: ArtifactRef
    scope_id: Identifier | None = None
    run_id: Identifier
    snapshot_ref: ArtifactRef
    snapshot_revision: Annotated[int, Field(ge=1)]
    status: DirectJobStatus
    result_ref: ArtifactRef | None = None
    previous_result_ref: ArtifactRef | None = None
    updated_at: AwareDatetime

    @model_validator(mode="after")
    def validate_result_state(self) -> DirectJobHead:
        if self.status == "running" and self.result_ref is not None:
            raise ValueError("running Direct job head cannot contain a terminal result")
        return self


@dataclass(frozen=True, slots=True)
class DirectJobLock:
    request_id: str
    nonce: str


class DirectJobStore:
    """Own one crash-safe head and one non-blocking writer lock per request id."""

    def __init__(self, root: str | os.PathLike[str]) -> None:
        requested = Path(root).expanduser()
        if requested.exists() and requested.is_symlink():
            raise DirectJobStoreError("Direct job store root cannot be a symlink")
        requested.mkdir(parents=True, exist_ok=True)
        if requested.is_symlink() or not requested.is_dir():
            raise DirectJobStoreError("Direct job store root must be a real directory")
        self.root = requested.resolve(strict=True)
        for name in ("heads", "locks", "tmp"):
            path = self.root / name
            path.mkdir(mode=0o700, exist_ok=True)
            if path.is_symlink() or not path.is_dir():
                raise DirectJobStoreError(f"Direct job store {name} must be a real directory")

    @contextmanager
    def exclusive(self, request_id: str) -> Iterator[DirectJobLock]:
        self._validate_request_id(request_id)
        lock_path = self.root / "locks" / f"{self._key(request_id)}.lock"
        descriptor = os.open(
            lock_path,
            os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        try:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise DirectJobAlreadyRunningError(
                    f"request already has an active Direct Generation runner: {request_id}"
                ) from exc
            yield DirectJobLock(request_id=request_id, nonce=uuid.uuid4().hex)
        finally:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)

    def read_head(self, request_id: str) -> DirectJobHead | None:
        self._validate_request_id(request_id)
        path = self._head_path(request_id)
        flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(path, flags)
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise DirectJobStoreError(f"cannot safely read Direct job head: {request_id}") from exc
        with os.fdopen(descriptor, "rb", closefd=True) as stream:
            raw = stream.read()
        try:
            head = DirectJobHead.model_validate_json(raw)
        except Exception as exc:
            raise DirectJobStoreError(f"invalid Direct job head: {request_id}") from exc
        if head.request_id != request_id:
            raise DirectJobStoreError("Direct job head identity mismatch")
        return head

    def compare_and_swap(
        self,
        lock: DirectJobLock,
        *,
        expected_head: DirectJobHead | None,
        next_head: DirectJobHead,
        allow_terminal_restart: bool = False,
        allow_registry_reconciliation: bool = False,
    ) -> DirectJobHead:
        """Advance the head without permitting identity drift or state regression."""

        self._validate_lock(lock)
        if next_head.request_id != lock.request_id:
            raise DirectJobHeadConflictError("Direct job head does not match the held lock")
        current = self.read_head(lock.request_id)
        if current != expected_head:
            raise DirectJobHeadConflictError("Direct job head changed since it was loaded")
        if current is None:
            if next_head.snapshot_revision != 1 or next_head.status != "running":
                raise DirectJobHeadConflictError(
                    "initial Direct job head must point to running snapshot revision one"
                )
        else:
            self._validate_transition(
                current,
                next_head,
                allow_terminal_restart=allow_terminal_restart,
                allow_registry_reconciliation=allow_registry_reconciliation,
            )
        self._atomic_write(self._head_path(lock.request_id), next_head.stable_json_bytes())
        return next_head

    @staticmethod
    def _validate_transition(
        current: DirectJobHead,
        next_head: DirectJobHead,
        *,
        allow_terminal_restart: bool,
        allow_registry_reconciliation: bool,
    ) -> None:
        if allow_terminal_restart and allow_registry_reconciliation:
            raise DirectJobHeadConflictError(
                "Direct transition cannot be restart and Registry reconciliation"
            )
        if allow_registry_reconciliation:
            valid_reconciliation = (
                current.status in {"failed", "needs_human", "budget_exhausted"}
                and current.result_ref is not None
                and next_head.status == "released"
                and next_head.result_ref is None
                and next_head.request_id == current.request_id
                and next_head.request_fingerprint == current.request_fingerprint
                and next_head.request_ref == current.request_ref
                and next_head.job_ref == current.job_ref
                and next_head.run_id == current.run_id
                and next_head.snapshot_revision > current.snapshot_revision
                and next_head.previous_result_ref == current.result_ref
            )
            if not valid_reconciliation:
                raise DirectJobHeadConflictError(
                    "invalid Registry-authoritative Direct reconciliation"
                )
            return
        if allow_terminal_restart:
            valid_restart = (
                current.status in {"failed", "needs_human", "budget_exhausted"}
                and current.result_ref is not None
                and next_head.status == "running"
                and next_head.result_ref is None
                and next_head.previous_result_ref == current.result_ref
                and next_head.request_id == current.request_id
                and next_head.request_fingerprint == current.request_fingerprint
                and next_head.request_ref == current.request_ref
                and next_head.job_ref == current.job_ref
                and next_head.run_id != current.run_id
                and next_head.snapshot_revision == 1
            )
            if not valid_restart:
                raise DirectJobHeadConflictError("invalid explicit terminal Direct restart")
            return
        immutable_fields = (
            "request_id",
            "request_fingerprint",
            "request_ref",
            "job_ref",
            "run_id",
            "previous_result_ref",
        )
        if any(getattr(current, field) != getattr(next_head, field) for field in immutable_fields):
            raise DirectJobHeadConflictError("Direct job identity cannot change")
        # scope_id is derived from job.job_id and stable for the life of a run.
        # Heads written before this field existed carry None; the first
        # checkpoint after upgrade may promote None -> concrete, but a concrete
        # scope_id can never drift to a different value.
        if current.scope_id is not None and current.scope_id != next_head.scope_id:
            raise DirectJobHeadConflictError("Direct job scope identity cannot change")
        if current.result_ref is not None:
            raise DirectJobHeadConflictError("completed Direct job head is immutable")
        if next_head.snapshot_revision < current.snapshot_revision:
            raise DirectJobHeadConflictError("Direct job snapshot revision cannot regress")
        if next_head.snapshot_revision == current.snapshot_revision:
            completion_only = (
                next_head.snapshot_ref == current.snapshot_ref
                and next_head.status == current.status
                and next_head.result_ref is not None
            )
            if not completion_only:
                raise DirectJobHeadConflictError(
                    "same-revision Direct job update may only attach its terminal result"
                )
        elif next_head.result_ref is not None:
            raise DirectJobHeadConflictError(
                "a new snapshot must be checkpointed before attaching its terminal result"
            )
        if current.status != "running" and next_head.status != current.status:
            raise DirectJobHeadConflictError("terminal Direct job status cannot change")

    def _atomic_write(self, destination: Path, content: bytes) -> None:
        temporary = self.root / "tmp" / f"{uuid.uuid4().hex}.tmp"
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
            os.replace(temporary, destination)
            directory = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            temporary.unlink(missing_ok=True)

    def _head_path(self, request_id: str) -> Path:
        return self.root / "heads" / f"{self._key(request_id)}.json"

    @staticmethod
    def _key(request_id: str) -> str:
        return hashlib.sha256(request_id.encode("utf-8")).hexdigest()

    @staticmethod
    def _validate_request_id(request_id: str) -> None:
        if _IDENTIFIER.fullmatch(request_id) is None:
            raise ValueError("invalid request id")

    @staticmethod
    def _validate_lock(lock: DirectJobLock) -> None:
        if not lock.nonce or _IDENTIFIER.fullmatch(lock.request_id) is None:
            raise DirectJobStoreError("invalid Direct job lock token")


def new_direct_job_head(
    *,
    request_id: str,
    request_fingerprint: str,
    request_ref: ArtifactRef,
    job_ref: ArtifactRef,
    run_id: str,
    snapshot_ref: ArtifactRef,
    snapshot_revision: int,
    status: DirectJobStatus,
    scope_id: Identifier | None = None,
    result_ref: ArtifactRef | None = None,
    previous_result_ref: ArtifactRef | None = None,
) -> DirectJobHead:
    """Create a head with framework-observed wall-clock provenance."""

    return DirectJobHead(
        request_id=request_id,
        request_fingerprint=request_fingerprint,
        request_ref=request_ref,
        job_ref=job_ref,
        scope_id=scope_id,
        run_id=run_id,
        snapshot_ref=snapshot_ref,
        snapshot_revision=snapshot_revision,
        status=status,
        result_ref=result_ref,
        previous_result_ref=previous_result_ref,
        updated_at=datetime.now(UTC),
    )


__all__ = [
    "DirectJobAlreadyRunningError",
    "DirectJobHead",
    "DirectJobHeadConflictError",
    "DirectJobLock",
    "DirectJobResumeRequiredError",
    "DirectJobStatus",
    "DirectJobStore",
    "DirectJobStoreError",
    "DirectRequestConflictError",
    "new_direct_job_head",
]
