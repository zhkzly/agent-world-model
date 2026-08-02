"""Durable, redacted physical-attempt records for real invocations.

The store is intentionally smaller than the Artifact DAG and has no semantic
authority.  It records only framework-owned lifecycle/terminal facts so a
crashed parent cannot leave an invocation audit or control view indefinitely
``running``.  Prompts, responses, endpoints, private sessions, and workspace
paths are rejected by construction: they simply have no fields here.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal

from .contracts import (
    InvocationLifecyclePhase,
    InvocationOwnership,
    InvocationResult,
    InvocationStatus,
)

_SCHEMA_VERSION = 5
_PREVIOUS_SCHEMA_VERSION = 4
_OLDER_SCHEMA_VERSION = 3
_LEGACY_SCHEMA_VERSION = 2
_OLDEST_SCHEMA_VERSION = 1
_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_SAFE_CODE = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,159}$")
_SAFE_ACTIVITY = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


class InvocationControlStoreError(RuntimeError):
    """A safe local persistence/consistency failure."""


class InvocationAlreadyActiveError(InvocationControlStoreError):
    """The same physical invocation id already owns a nonterminal record."""


class InvocationPhysicalStatus(StrEnum):
    RUNNING = "running"
    CANCEL_REQUESTED = "cancel_requested"
    DECLARED_WALL_EXPIRED = "declared_wall_expired"
    SETTLED = "settled"


@dataclass(frozen=True, slots=True)
class InvocationTerminalFact:
    """Small safe terminal fact; error prose/details never enter this record."""

    status: InvocationStatus
    code: str
    retryable: bool

    def __post_init__(self) -> None:
        if not _SAFE_CODE.fullmatch(self.code):
            raise ValueError("terminal code must use the safe closed identifier alphabet")

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "code": self.code,
            "retryable": self.retryable,
        }

    @classmethod
    def from_dict(cls, raw: object) -> InvocationTerminalFact:
        if not isinstance(raw, dict) or set(raw) != {"status", "code", "retryable"}:
            raise InvocationControlStoreError("invalid invocation terminal fact")
        try:
            status = InvocationStatus(_required_string(raw["status"], "terminal status"))
        except ValueError as exc:
            raise InvocationControlStoreError("invalid invocation terminal status") from exc
        code = _required_string(raw["code"], "terminal code")
        retryable = raw["retryable"]
        if not isinstance(retryable, bool):
            raise InvocationControlStoreError("invalid invocation terminal retryability")
        try:
            return cls(status=status, code=code, retryable=retryable)
        except ValueError as exc:
            raise InvocationControlStoreError("invalid invocation terminal fact") from exc


@dataclass(frozen=True, slots=True)
class InvocationRequestShape:
    """Content-free dimensions of one request at the real adapter boundary.

    The control record must never become a second prompt or profile store.
    These are deliberately only scalar byte counts and closed transport/mode
    labels.  They let a project-execution Agent distinguish a small passing
    probe from a large zero-event request without disclosing either request's
    text, JSON schema, endpoint, credentials, session id, or workspace.
    """

    prompt_bytes: int
    runtime_skill_count: int
    output_schema_bytes: int | None
    allowed_builtin_tool_count: int
    execution_mode: Literal["agentic", "single_shot_structured"]
    continued_session: bool

    def __post_init__(self) -> None:
        for label, value in (
            ("prompt_bytes", self.prompt_bytes),
            ("runtime_skill_count", self.runtime_skill_count),
            ("allowed_builtin_tool_count", self.allowed_builtin_tool_count),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(f"{label} must be a non-negative integer")
        if self.output_schema_bytes is not None and (
            not isinstance(self.output_schema_bytes, int)
            or isinstance(self.output_schema_bytes, bool)
            or self.output_schema_bytes < 0
        ):
            raise ValueError("output_schema_bytes must be null or a non-negative integer")

    def to_dict(self) -> dict[str, object]:
        return {
            "prompt_bytes": self.prompt_bytes,
            "runtime_skill_count": self.runtime_skill_count,
            "output_schema_bytes": self.output_schema_bytes,
            "allowed_builtin_tool_count": self.allowed_builtin_tool_count,
            "execution_mode": self.execution_mode,
            "continued_session": self.continued_session,
        }

    @classmethod
    def from_dict(cls, raw: object) -> InvocationRequestShape:
        expected = {
            "prompt_bytes",
            "runtime_skill_count",
            "output_schema_bytes",
            "allowed_builtin_tool_count",
            "execution_mode",
            "continued_session",
        }
        if not isinstance(raw, dict) or set(raw) != expected:
            raise InvocationControlStoreError("invalid invocation request shape")
        execution_mode = raw["execution_mode"]
        continued_session = raw["continued_session"]
        if execution_mode not in {"agentic", "single_shot_structured"}:
            raise InvocationControlStoreError("invalid invocation request execution mode")
        if not isinstance(continued_session, bool):
            raise InvocationControlStoreError("invalid invocation request continuation flag")
        try:
            return cls(
                prompt_bytes=_nonnegative_int(raw["prompt_bytes"], "prompt_bytes"),
                runtime_skill_count=_nonnegative_int(
                    raw["runtime_skill_count"], "runtime_skill_count"
                ),
                output_schema_bytes=(
                    None
                    if raw["output_schema_bytes"] is None
                    else _nonnegative_int(raw["output_schema_bytes"], "output_schema_bytes")
                ),
                allowed_builtin_tool_count=_nonnegative_int(
                    raw["allowed_builtin_tool_count"], "allowed_builtin_tool_count"
                ),
                execution_mode=execution_mode,
                continued_session=continued_session,
            )
        except ValueError as exc:
            raise InvocationControlStoreError("invalid invocation request shape") from exc


@dataclass(frozen=True, slots=True)
class InvocationControlRecord:
    """One redacted record for one physical invocation attempt."""

    invocation_id: str
    owner: InvocationOwnership
    route: Literal["codex_sdk", "direct_llm"]
    model: str
    profile_digest: str
    envelope_digest: str
    declared_wall_seconds: float
    request_shape: InvocationRequestShape | None
    owner_pid: int
    # A PID alone is not a durable owner identity: it can be reused after a
    # crash and, crucially, it may be a PID from a different namespace.  Linux
    # records therefore bind a digest of boot id + PID + /proc start ticks.
    # The digest is safe to persist and lets a later process prove it is
    # looking at the same owner without exposing host/process details.
    owner_process_identity_kind: Literal["linux_proc", "pid_only", "legacy"]
    owner_process_identity: str | None
    status: InvocationPhysicalStatus
    started_at: datetime
    updated_at: datetime
    local_event_count: int
    provider_progress_count: int
    last_local_phase: InvocationLifecyclePhase
    first_provider_progress_at: datetime | None = None
    last_provider_progress_at: datetime | None = None
    last_local_activity_at: datetime | None = None
    last_provider_activity: str | None = None
    terminal: InvocationTerminalFact | None = None

    def __post_init__(self) -> None:
        for label, value in (
            ("invocation_id", self.invocation_id),
            ("model", self.model),
            ("profile_digest", self.profile_digest),
        ):
            if not _SAFE_IDENTIFIER.fullmatch(value):
                raise ValueError(f"{label} must be a safe bounded identifier")
        if len(self.envelope_digest) != 64 or any(
            character not in "0123456789abcdef" for character in self.envelope_digest
        ):
            raise ValueError("envelope_digest must be a sha256 hex digest")
        if self.declared_wall_seconds <= 0:
            raise ValueError("declared_wall_seconds must be positive")
        if self.owner_pid <= 0:
            raise ValueError("owner_pid must be positive")
        if self.owner_process_identity_kind == "linux_proc":
            if (
                self.owner_process_identity is None
                or len(self.owner_process_identity) != 64
                or any(
                    character not in "0123456789abcdef" for character in self.owner_process_identity
                )
            ):
                raise ValueError("linux owner identity must be a sha256 hex digest")
        elif self.owner_process_identity is not None:
            raise ValueError("only a linux owner identity may carry a process digest")
        if self.local_event_count < 0 or self.provider_progress_count < 0:
            raise ValueError("lifecycle event counts must be non-negative")
        if self.last_provider_activity is not None and not _SAFE_ACTIVITY.fullmatch(
            self.last_provider_activity
        ):
            raise ValueError("last_provider_activity must be a safe activity label")
        timestamps = (
            self.first_provider_progress_at,
            self.last_provider_progress_at,
            self.last_local_activity_at,
        )
        for timestamp in timestamps:
            if timestamp is None:
                continue
            if timestamp.tzinfo is None:
                raise ValueError("invocation control timestamps must be timezone-aware")
            if timestamp < self.started_at or timestamp > self.updated_at:
                raise ValueError("invocation control timestamps must remain within the attempt")
        if (self.first_provider_progress_at is None) != (self.last_provider_progress_at is None):
            raise ValueError("provider progress timestamps must be recorded as a pair")
        if (
            self.first_provider_progress_at is not None
            and self.last_provider_progress_at is not None
            and self.last_provider_progress_at < self.first_provider_progress_at
        ):
            raise ValueError("last provider progress cannot precede first provider progress")
        if (self.status is InvocationPhysicalStatus.SETTLED) != (self.terminal is not None):
            raise ValueError("only settled invocation records may carry a terminal fact")

    @property
    def settled(self) -> bool:
        return self.status is InvocationPhysicalStatus.SETTLED

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": _SCHEMA_VERSION,
            "invocation_id": self.invocation_id,
            "owner": self.owner.to_safe_dict(),
            "route": self.route,
            "model": self.model,
            "profile_digest": self.profile_digest,
            "envelope_digest": self.envelope_digest,
            "declared_wall_seconds": self.declared_wall_seconds,
            "request_shape": (
                self.request_shape.to_dict() if self.request_shape is not None else None
            ),
            "owner_pid": self.owner_pid,
            "owner_process_identity_kind": self.owner_process_identity_kind,
            "owner_process_identity": self.owner_process_identity,
            "status": self.status.value,
            "started_at": self.started_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "first_provider_progress_at": (
                self.first_provider_progress_at.isoformat()
                if self.first_provider_progress_at is not None
                else None
            ),
            "last_provider_progress_at": (
                self.last_provider_progress_at.isoformat()
                if self.last_provider_progress_at is not None
                else None
            ),
            "last_local_activity_at": (
                self.last_local_activity_at.isoformat()
                if self.last_local_activity_at is not None
                else None
            ),
            "local_event_count": self.local_event_count,
            "provider_progress_count": self.provider_progress_count,
            "last_local_phase": self.last_local_phase.value,
            "last_provider_activity": self.last_provider_activity,
            "terminal": self.terminal.to_dict() if self.terminal is not None else None,
        }

    @classmethod
    def from_dict(cls, raw: object) -> InvocationControlRecord:
        if not isinstance(raw, dict):
            raise InvocationControlStoreError("invalid invocation control record")
        version = raw.get("schema_version")
        expected = {
            "schema_version",
            "invocation_id",
            "owner",
            "route",
            "model",
            "profile_digest",
            "envelope_digest",
            "declared_wall_seconds",
            "owner_pid",
            "status",
            "started_at",
            "updated_at",
            "local_event_count",
            "provider_progress_count",
            "last_local_phase",
            "last_provider_activity",
            "terminal",
        }
        if version == _SCHEMA_VERSION:
            expected.update(
                {
                    "first_provider_progress_at",
                    "last_provider_progress_at",
                    "last_local_activity_at",
                    "owner_process_identity_kind",
                    "owner_process_identity",
                    "request_shape",
                }
            )
        elif version == _PREVIOUS_SCHEMA_VERSION:
            expected.update(
                {
                    "first_provider_progress_at",
                    "last_provider_progress_at",
                    "last_local_activity_at",
                    "owner_process_identity_kind",
                    "owner_process_identity",
                    "request_shape",
                }
            )
        elif version == _OLDER_SCHEMA_VERSION:
            expected.update(
                {
                    "first_provider_progress_at",
                    "last_provider_progress_at",
                    "last_local_activity_at",
                }
            )
        elif version == _LEGACY_SCHEMA_VERSION:
            expected.update(
                {
                    "first_provider_progress_at",
                    "last_provider_progress_at",
                    "last_local_activity_at",
                }
            )
        elif version != _OLDEST_SCHEMA_VERSION:
            raise InvocationControlStoreError("invalid invocation control record shape")
        if set(raw) != expected:
            raise InvocationControlStoreError("invalid invocation control record shape")
        owner = _ownership_from_safe_dict(raw["owner"])
        route = raw["route"]
        if route not in {"codex_sdk", "direct_llm"}:
            raise InvocationControlStoreError("invalid invocation control route")
        try:
            status = InvocationPhysicalStatus(_required_string(raw["status"], "status"))
            phase = InvocationLifecyclePhase(
                _required_string(raw["last_local_phase"], "last_local_phase")
            )
        except ValueError as exc:
            raise InvocationControlStoreError("invalid invocation control status/phase") from exc
        terminal_raw = raw["terminal"]
        terminal = None if terminal_raw is None else InvocationTerminalFact.from_dict(terminal_raw)
        try:
            started_at = _parse_datetime(raw["started_at"], "started_at")
            updated_at = _parse_datetime(raw["updated_at"], "updated_at")
            record = cls(
                invocation_id=_required_string(raw["invocation_id"], "invocation_id"),
                owner=owner,
                route=route,
                model=_required_string(raw["model"], "model"),
                profile_digest=_required_string(raw["profile_digest"], "profile_digest"),
                envelope_digest=_required_string(raw["envelope_digest"], "envelope_digest"),
                declared_wall_seconds=_positive_float(
                    raw["declared_wall_seconds"], "declared_wall_seconds"
                ),
                request_shape=(
                    None
                    if raw["request_shape"] is None
                    else InvocationRequestShape.from_dict(raw["request_shape"])
                )
                if version == _SCHEMA_VERSION
                else None,
                owner_pid=_positive_int(raw["owner_pid"], "owner_pid"),
                owner_process_identity_kind=(
                    _owner_identity_kind(raw["owner_process_identity_kind"])
                    if version in {_SCHEMA_VERSION, _PREVIOUS_SCHEMA_VERSION}
                    else "legacy"
                ),
                owner_process_identity=(
                    _optional_process_identity(raw["owner_process_identity"])
                    if version in {_SCHEMA_VERSION, _PREVIOUS_SCHEMA_VERSION}
                    else None
                ),
                status=status,
                started_at=started_at,
                updated_at=updated_at,
                first_provider_progress_at=(
                    _optional_datetime(
                        raw["first_provider_progress_at"],
                        "first_provider_progress_at",
                    )
                    if version
                    in {
                        _SCHEMA_VERSION,
                        _PREVIOUS_SCHEMA_VERSION,
                        _OLDER_SCHEMA_VERSION,
                        _LEGACY_SCHEMA_VERSION,
                    }
                    else None
                ),
                last_provider_progress_at=(
                    _optional_datetime(
                        raw["last_provider_progress_at"],
                        "last_provider_progress_at",
                    )
                    if version
                    in {
                        _SCHEMA_VERSION,
                        _PREVIOUS_SCHEMA_VERSION,
                        _OLDER_SCHEMA_VERSION,
                        _LEGACY_SCHEMA_VERSION,
                    }
                    else None
                ),
                last_local_activity_at=(
                    _optional_datetime(raw["last_local_activity_at"], "last_local_activity_at")
                    if version
                    in {
                        _SCHEMA_VERSION,
                        _PREVIOUS_SCHEMA_VERSION,
                        _OLDER_SCHEMA_VERSION,
                        _LEGACY_SCHEMA_VERSION,
                    }
                    else None
                ),
                local_event_count=_nonnegative_int(raw["local_event_count"], "local_event_count"),
                provider_progress_count=_nonnegative_int(
                    raw["provider_progress_count"], "provider_progress_count"
                ),
                last_local_phase=phase,
                last_provider_activity=_optional_activity(raw["last_provider_activity"]),
                terminal=terminal,
            )
        except ValueError as exc:
            raise InvocationControlStoreError("invalid invocation control record values") from exc
        return record


class InvocationControlStore:
    """Crash-safe, per-attempt control records with no workflow authority."""

    def __init__(self, root: str | os.PathLike[str]) -> None:
        requested = Path(root).expanduser()
        if requested.exists() and requested.is_symlink():
            raise InvocationControlStoreError("invocation control root cannot be a symlink")
        requested.mkdir(parents=True, exist_ok=True, mode=0o700)
        if requested.is_symlink() or not requested.is_dir():
            raise InvocationControlStoreError("invocation control root must be a real directory")
        self.root = requested.resolve(strict=True)
        for name in ("attempts", "locks", "tmp"):
            directory = self.root / name
            directory.mkdir(mode=0o700, exist_ok=True)
            if directory.is_symlink() or not directory.is_dir():
                raise InvocationControlStoreError(
                    "invocation control store directories must be real directories"
                )

    def begin(
        self,
        *,
        invocation_id: str,
        owner: InvocationOwnership,
        route: Literal["codex_sdk", "direct_llm"],
        model: str,
        profile_digest: str,
        envelope_digest: str,
        declared_wall_seconds: float,
        request_shape: InvocationRequestShape | None = None,
    ) -> InvocationControlRecord:
        now = datetime.now(UTC)
        owner_pid = os.getpid()
        owner_identity_kind, owner_identity = _current_owner_process_identity(owner_pid)
        try:
            record = InvocationControlRecord(
                invocation_id=invocation_id,
                owner=owner,
                route=route,
                model=model,
                profile_digest=profile_digest,
                envelope_digest=envelope_digest,
                declared_wall_seconds=declared_wall_seconds,
                request_shape=request_shape,
                owner_pid=owner_pid,
                owner_process_identity_kind=owner_identity_kind,
                owner_process_identity=owner_identity,
                status=InvocationPhysicalStatus.RUNNING,
                started_at=now,
                updated_at=now,
                last_local_activity_at=now,
                local_event_count=1,
                provider_progress_count=0,
                last_local_phase=InvocationLifecyclePhase.QUEUED,
            )
        except ValueError as exc:
            raise InvocationControlStoreError("unsafe invocation control identity") from exc
        with self._exclusive(invocation_id):
            existing = self._read_unlocked(invocation_id)
            if existing is not None:
                if not existing.settled:
                    raise InvocationAlreadyActiveError("physical invocation is already active")
                raise InvocationControlStoreError("physical invocation id was already settled")
            self._write_unlocked(record)
        return record

    def read(self, invocation_id: str) -> InvocationControlRecord | None:
        _validate_invocation_id(invocation_id)
        with self._exclusive(invocation_id):
            return self._read_unlocked(invocation_id)

    def read_settled_snapshot(self, invocation_id: str) -> InvocationControlRecord | None:
        """Read one immutable terminal record without touching the source store.

        A settled control record is immutable.  Diagnostic recovery may need to
        carry exactly that safe fact into a new marked diagnostic state root so its
        route-liveness gate can verify the prior physical attempt.  Unlike
        :meth:`read`, this deliberately creates no source-side lock file: the
        caller is reading a historical snapshot, not coordinating a live
        invocation.
        """

        _validate_invocation_id(invocation_id)
        record = self._read_unlocked(invocation_id)
        return record if record is not None and record.settled else None

    def import_settled_snapshot(
        self,
        record: InvocationControlRecord,
    ) -> InvocationControlRecord:
        """Persist one exact settled record for a diagnostic liveness check.

        This is intentionally narrower than copying an invocation-control
        directory.  It accepts only an already settled, redacted physical
        record and is idempotent only when an existing record is byte-for-byte
        equal.  It never imports a live owner, workspace, session, prompt, or
        Provider payload because those values are not representable here.
        """

        if not record.settled:
            raise InvocationControlStoreError(
                "only a settled invocation record may enter a diagnostic snapshot"
            )
        with self._exclusive(record.invocation_id):
            existing = self._read_unlocked(record.invocation_id)
            if existing is not None:
                if existing != record:
                    raise InvocationControlStoreError(
                        "diagnostic invocation snapshot conflicts with an existing record"
                    )
                return existing
            self._write_unlocked(record)
        return record

    def record_local(
        self,
        invocation_id: str,
        phase: InvocationLifecyclePhase,
    ) -> InvocationControlRecord:
        now = datetime.now(UTC)
        return self._update_active(
            invocation_id,
            lambda record: replace(
                record,
                updated_at=now,
                last_local_activity_at=now,
                local_event_count=record.local_event_count + 1,
                last_local_phase=phase,
            ),
        )

    def record_provider_progress(
        self,
        invocation_id: str,
        *,
        activity: str = "provider_event",
    ) -> InvocationControlRecord:
        if not _SAFE_ACTIVITY.fullmatch(activity):
            activity = "provider_event"
        now = datetime.now(UTC)
        return self._update_active(
            invocation_id,
            lambda record: replace(
                record,
                updated_at=now,
                first_provider_progress_at=record.first_provider_progress_at or now,
                last_provider_progress_at=now,
                provider_progress_count=record.provider_progress_count + 1,
                last_provider_activity=activity,
            ),
        )

    def request_cancel(self, invocation_id: str) -> InvocationControlRecord:
        now = datetime.now(UTC)
        return self._update_active(
            invocation_id,
            lambda record: replace(
                record,
                status=InvocationPhysicalStatus.CANCEL_REQUESTED,
                updated_at=now,
                last_local_activity_at=now,
                local_event_count=record.local_event_count + 1,
                last_local_phase=InvocationLifecyclePhase.CANCEL_REQUESTED,
            ),
        )

    def expire_declared_wall(self, invocation_id: str) -> InvocationControlRecord:
        now = datetime.now(UTC)
        return self._update_active(
            invocation_id,
            lambda record: replace(
                record,
                status=InvocationPhysicalStatus.DECLARED_WALL_EXPIRED,
                updated_at=now,
                last_local_activity_at=now,
                local_event_count=record.local_event_count + 1,
                last_local_phase=InvocationLifecyclePhase.DECLARED_WALL_EXPIRED,
            ),
        )

    def settle(
        self,
        invocation_id: str,
        *,
        terminal: InvocationTerminalFact,
        final_phase: InvocationLifecyclePhase = InvocationLifecyclePhase.TERMINAL_RECEIVED,
    ) -> InvocationControlRecord:
        _validate_invocation_id(invocation_id)
        with self._exclusive(invocation_id):
            record = self._require_unlocked(invocation_id)
            if record.settled:
                # Physical terminalization is first-writer-wins.  A later
                # cancellation, worker exit, or recovery scan observes the
                # durable terminal fact rather than creating a second result.
                return record
            now = datetime.now(UTC)
            settled = replace(
                record,
                status=InvocationPhysicalStatus.SETTLED,
                updated_at=now,
                last_local_activity_at=now,
                local_event_count=record.local_event_count + 1,
                last_local_phase=final_phase,
                terminal=terminal,
            )
            self._write_unlocked(settled)
            return settled

    def settle_result(self, result: InvocationResult) -> InvocationControlRecord:
        error = result.error
        code = (
            error.code
            if error is not None and _SAFE_CODE.fullmatch(error.code)
            else result.status.value
        )
        retryable = bool(error.retryable) if error is not None else False
        return self.settle(
            result.invocation_id,
            terminal=InvocationTerminalFact(
                status=result.status,
                code=code,
                retryable=retryable,
            ),
        )

    def reconcile_owner_loss(self) -> tuple[InvocationControlRecord, ...]:
        """Settle records whose recorded local owner process no longer exists.

        This intentionally does not retry anything.  Workflow recovery still
        needs the owning Scheduler/ledger to decide whether a new logical
        operation is authorized.
        """

        settled: list[InvocationControlRecord] = []
        for record in self.list_records():
            if record.settled or _owner_process_is_live(record):
                continue
            try:
                settled.append(
                    self.settle(
                        record.invocation_id,
                        terminal=InvocationTerminalFact(
                            status=InvocationStatus.FAILED,
                            code="owner_process_interrupted",
                            retryable=False,
                        ),
                        final_phase=InvocationLifecyclePhase.OWNER_LOST,
                    )
                )
            except InvocationControlStoreError:
                # A concurrent owner/recovery may have settled it after the
                # read. The next read is the authoritative observation.
                continue
        return tuple(settled)

    def list_records(self) -> tuple[InvocationControlRecord, ...]:
        records: list[InvocationControlRecord] = []
        directory = self.root / "attempts"
        for path in sorted(directory.glob("*.json"), key=lambda item: item.name):
            if path.is_symlink():
                raise InvocationControlStoreError("invocation attempt record cannot be a symlink")
            raw = self._read_path(path)
            record = InvocationControlRecord.from_dict(raw)
            if path != self._record_path(record.invocation_id):
                raise InvocationControlStoreError("invocation attempt record path mismatch")
            records.append(record)
        return tuple(records)

    def _update_active(
        self,
        invocation_id: str,
        updater: Callable[[InvocationControlRecord], InvocationControlRecord],
    ) -> InvocationControlRecord:
        _validate_invocation_id(invocation_id)
        with self._exclusive(invocation_id):
            record = self._require_unlocked(invocation_id)
            if record.settled:
                return record
            next_record = updater(record)
            if (
                next_record.invocation_id != record.invocation_id
                or next_record.owner != record.owner
            ):
                raise InvocationControlStoreError("invocation control identity is immutable")
            self._write_unlocked(next_record)
            return next_record

    @contextmanager
    def _exclusive(self, invocation_id: str) -> Iterator[None]:
        _validate_invocation_id(invocation_id)
        path = self.root / "locks" / f"{_digest(invocation_id)}.lock"
        descriptor = os.open(
            path,
            os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            yield
        finally:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)

    def _read_unlocked(self, invocation_id: str) -> InvocationControlRecord | None:
        path = self._record_path(invocation_id)
        if not path.exists():
            return None
        return InvocationControlRecord.from_dict(self._read_path(path))

    def _require_unlocked(self, invocation_id: str) -> InvocationControlRecord:
        record = self._read_unlocked(invocation_id)
        if record is None:
            raise InvocationControlStoreError("invocation control record does not exist")
        return record

    def _write_unlocked(self, record: InvocationControlRecord) -> None:
        payload = json.dumps(
            record.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        self._atomic_write(
            self._record_path(record.invocation_id),
            (payload + "\n").encode("utf-8"),
        )

    def _record_path(self, invocation_id: str) -> Path:
        _validate_invocation_id(invocation_id)
        return self.root / "attempts" / f"{_digest(invocation_id)}.json"

    @staticmethod
    def _read_path(path: Path) -> object:
        flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(path, flags)
        except OSError as exc:
            raise InvocationControlStoreError(
                "cannot safely read invocation control record"
            ) from exc
        with os.fdopen(descriptor, "rb", closefd=True) as stream:
            raw = stream.read()
        try:
            return json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise InvocationControlStoreError("invalid invocation control record JSON") from exc

    def _atomic_write(self, destination: Path, payload: bytes) -> None:
        if destination.parent != self.root / "attempts":
            raise InvocationControlStoreError("invalid invocation control destination")
        descriptor, temporary_name = tempfile.mkstemp(
            prefix="attempt-",
            suffix=".tmp",
            dir=self.root / "tmp",
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb", closefd=True) as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, destination)
            directory_fd = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            if temporary.exists():
                temporary.unlink(missing_ok=True)


def _ownership_from_safe_dict(raw: object) -> InvocationOwnership:
    if not isinstance(raw, dict) or set(raw) != {
        "owner_kind",
        "owner_id",
        "scope_id",
        "coordinate",
        "immutable_input_closure_digest",
    }:
        raise InvocationControlStoreError("invalid invocation ownership")
    try:
        from .contracts import InvocationOwnerKind

        owner = InvocationOwnership(
            owner_kind=InvocationOwnerKind(_required_string(raw["owner_kind"], "owner_kind")),
            owner_id=_required_string(raw["owner_id"], "owner_id"),
            scope_id=_required_string(raw["scope_id"], "scope_id"),
            coordinate=_optional_identifier(raw["coordinate"]),
            immutable_input_closure_digest=_optional_digest(raw["immutable_input_closure_digest"]),
        )
    except (TypeError, ValueError) as exc:
        raise InvocationControlStoreError("invalid invocation ownership") from exc
    return owner


def _required_string(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise InvocationControlStoreError(f"invalid invocation control {label}")
    return value


def _optional_identifier(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not _SAFE_IDENTIFIER.fullmatch(value):
        raise InvocationControlStoreError("invalid invocation control coordinate")
    return value


def _optional_digest(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise InvocationControlStoreError("invalid invocation closure digest")
    return value


def _optional_activity(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not _SAFE_ACTIVITY.fullmatch(value):
        raise InvocationControlStoreError("invalid invocation activity")
    return value


def _owner_identity_kind(value: object) -> Literal["linux_proc", "pid_only", "legacy"]:
    if value == "linux_proc":
        return "linux_proc"
    if value == "pid_only":
        return "pid_only"
    if value == "legacy":
        return "legacy"
    raise InvocationControlStoreError("invalid invocation owner identity kind")


def _optional_process_identity(value: object) -> str | None:
    if value is None:
        return None
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise InvocationControlStoreError("invalid invocation owner process identity")
    return value


def _positive_float(value: object, label: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
        raise InvocationControlStoreError(f"invalid invocation control {label}")
    return float(value)


def _positive_int(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise InvocationControlStoreError(f"invalid invocation control {label}")
    return value


def _nonnegative_int(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise InvocationControlStoreError(f"invalid invocation control {label}")
    return value


def _parse_datetime(value: object, label: str) -> datetime:
    if not isinstance(value, str):
        raise InvocationControlStoreError(f"invalid invocation control {label}")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise InvocationControlStoreError(f"invalid invocation control {label}") from exc
    if parsed.tzinfo is None:
        raise InvocationControlStoreError(f"invalid invocation control {label}")
    return parsed


def _optional_datetime(value: object, label: str) -> datetime | None:
    if value is None:
        return None
    return _parse_datetime(value, label)


def _validate_invocation_id(invocation_id: str) -> None:
    if not _SAFE_IDENTIFIER.fullmatch(invocation_id):
        raise InvocationControlStoreError("invocation id must be a safe bounded identifier")


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _current_owner_process_identity(
    pid: int,
) -> tuple[Literal["linux_proc", "pid_only"], str | None]:
    """Capture a safe birth identity when the host exposes Linux ``/proc``.

    ``os.kill(pid, 0)`` only proves that *some* process with that numeric PID
    exists.  It cannot distinguish a reused PID or a process observed through
    a different PID namespace.  The start-time field from ``/proc/<pid>/stat``
    plus the kernel boot id does.  On a non-Linux host we retain the previous
    PID-only behavior rather than inventing a platform-specific approximation.
    """

    identity = _process_identity_for_pid(pid)
    return ("linux_proc", identity) if identity is not None else ("pid_only", None)


def _process_identity_for_pid(pid: int) -> str | None:
    """Return a redacted Linux process birth digest, if it can be read safely."""

    try:
        boot_id = Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip()
        stat_payload = Path(f"/proc/{pid}/stat").read_text(encoding="ascii")
    except (OSError, UnicodeError):
        return None
    # ``comm`` is parenthesized and may contain spaces or parentheses. Split
    # only at the final ``) `` before the stable field sequence (field 3+).
    try:
        fields = stat_payload.rsplit(") ", maxsplit=1)[1].split()
        start_ticks = fields[19]  # proc(5) field 22; fields[0] is field 3.
    except (IndexError, ValueError):
        return None
    if not boot_id or not start_ticks.isdigit():
        return None
    payload = f"linux-proc-v1\0{boot_id}\0{pid}\0{start_ticks}".encode("ascii")
    return hashlib.sha256(payload).hexdigest()


def _owner_process_is_live(record: InvocationControlRecord) -> bool:
    """Return true only when the durable owner identity still matches.

    Schema-v1/v2 records intentionally fail closed here. They did not record a
    process birth identity, so a current PID could denote a completely
    unrelated owner. Settling that stale record is safer than allowing an
    indeterminate invocation to remain ``running`` indefinitely.
    """

    if record.owner_process_identity_kind == "linux_proc":
        current = _process_identity_for_pid(record.owner_pid)
        return current is not None and current == record.owner_process_identity
    if record.owner_process_identity_kind == "pid_only":
        return _pid_is_alive(record.owner_pid)
    return False


def _pid_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
