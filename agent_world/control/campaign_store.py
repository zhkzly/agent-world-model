"""Single-writer campaign head and crash-safe compare-and-swap metadata."""

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

from pydantic import AwareDatetime

from agent_world.contracts import ArtifactRef, Identifier, V2Contract

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")


class CampaignStoreError(RuntimeError):
    pass


class CampaignAlreadyRunningError(CampaignStoreError):
    pass


class CampaignHeadConflictError(CampaignStoreError):
    pass


class CampaignHead(V2Contract):
    campaign_id: Identifier
    checkpoint_ref: ArtifactRef
    checkpoint_revision: int
    updated_at: AwareDatetime
    report_ref: ArtifactRef | None = None


@dataclass(frozen=True, slots=True)
class CampaignLock:
    campaign_id: str
    nonce: str


class CampaignStore:
    """Own the mutable pointer; all semantic history remains immutable artifacts."""

    def __init__(self, root: str | os.PathLike[str]) -> None:
        requested = Path(root).expanduser()
        if requested.exists() and requested.is_symlink():
            raise CampaignStoreError("campaign store root cannot be a symlink")
        requested.mkdir(parents=True, exist_ok=True)
        if requested.is_symlink() or not requested.is_dir():
            raise CampaignStoreError("campaign store root must be a real directory")
        self.root = requested.resolve(strict=True)
        for name in ("heads", "locks", "tmp"):
            path = self.root / name
            path.mkdir(mode=0o700, exist_ok=True)
            if path.is_symlink() or not path.is_dir():
                raise CampaignStoreError(f"campaign store {name} must be a real directory")

    @contextmanager
    def exclusive(self, campaign_id: str) -> Iterator[CampaignLock]:
        self._validate_campaign_id(campaign_id)
        lock_path = self.root / "locks" / f"{self._key(campaign_id)}.lock"
        descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o600)
        try:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise CampaignAlreadyRunningError(
                    f"campaign already has an active runner: {campaign_id}"
                ) from exc
            yield CampaignLock(campaign_id=campaign_id, nonce=uuid.uuid4().hex)
        finally:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)

    def read_head(self, campaign_id: str) -> CampaignHead | None:
        self._validate_campaign_id(campaign_id)
        path = self._head_path(campaign_id)
        try:
            raw = path.read_bytes()
        except FileNotFoundError:
            return None
        try:
            head = CampaignHead.model_validate_json(raw)
        except Exception as exc:
            raise CampaignStoreError(f"invalid campaign head: {campaign_id}") from exc
        if head.campaign_id != campaign_id:
            raise CampaignStoreError("campaign head identity mismatch")
        return head

    def compare_and_swap(
        self,
        lock: CampaignLock,
        *,
        expected_checkpoint_ref: ArtifactRef | None,
        checkpoint_ref: ArtifactRef,
        checkpoint_revision: int,
        report_ref: ArtifactRef | None = None,
    ) -> CampaignHead:
        self._validate_lock(lock)
        current = self.read_head(lock.campaign_id)
        current_ref = current.checkpoint_ref if current is not None else None
        if current_ref != expected_checkpoint_ref:
            raise CampaignHeadConflictError("campaign head changed since the loaded checkpoint")
        if current is not None and checkpoint_revision <= current.checkpoint_revision:
            raise CampaignHeadConflictError("campaign checkpoint revision must increase")
        if current is None and checkpoint_revision != 1:
            raise CampaignHeadConflictError("initial campaign checkpoint revision must be one")
        head = CampaignHead(
            campaign_id=lock.campaign_id,
            checkpoint_ref=checkpoint_ref,
            checkpoint_revision=checkpoint_revision,
            updated_at=datetime.now(UTC),
            report_ref=report_ref,
        )
        self._atomic_write(self._head_path(lock.campaign_id), head.stable_json_bytes())
        return head

    def _head_path(self, campaign_id: str) -> Path:
        return self.root / "heads" / f"{self._key(campaign_id)}.json"

    def _atomic_write(self, destination: Path, content: bytes) -> None:
        temporary = self.root / "tmp" / f"{uuid.uuid4().hex}.tmp"
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC,
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

    @staticmethod
    def _key(campaign_id: str) -> str:
        return hashlib.sha256(campaign_id.encode("utf-8")).hexdigest()

    @staticmethod
    def _validate_campaign_id(campaign_id: str) -> None:
        if _IDENTIFIER.fullmatch(campaign_id) is None:
            raise ValueError("invalid campaign id")

    @staticmethod
    def _validate_lock(lock: CampaignLock) -> None:
        if not lock.nonce or _IDENTIFIER.fullmatch(lock.campaign_id) is None:
            raise CampaignStoreError("invalid campaign lock token")


__all__ = [
    "CampaignAlreadyRunningError",
    "CampaignHead",
    "CampaignHeadConflictError",
    "CampaignLock",
    "CampaignStore",
    "CampaignStoreError",
]
