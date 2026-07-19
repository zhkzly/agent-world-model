"""Crash-safe CAS heads for the clean-break generation WorkGraph.

Immutable attempts, reports, evaluations, actions, and commits live in the
Artifact Store.  This store owns only the smallest mutable pointer needed to
schedule one coordinate exactly once and to recover after process failure.
"""

from __future__ import annotations

import fcntl
import hashlib
import os
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, ValidationError, model_validator

from agent_world.artifact_store import ArtifactWriter
from agent_world.contracts import ArtifactRef, ContentHash, Identifier, V2Contract

from .models import BudgetLease
from .work import (
    FeedbackEvaluation,
    ProposalExecution,
    ValidationReport,
    WorkAttempt,
    WorkCommit,
    WorkCoordinate,
    WorkDefinition,
)

type WorkHeadStatus = Literal[
    "running",
    "repair_authorized",
    "committed",
    "failed",
    "needs_human",
    "interrupted",
]


class WorkControlStoreError(RuntimeError):
    """Base error for WorkGraph mutable-head coordination."""


class WorkAlreadyRunningError(WorkControlStoreError):
    """Another process owns the exact WorkCoordinate lock."""


class WorkHeadConflictError(WorkControlStoreError):
    """The durable head changed or an invalid state transition was requested."""


class WorkResumeError(WorkControlStoreError):
    """A head cannot prove an exact reusable WorkCommit."""


class WorkControlHead(V2Contract):
    """Mutable pointer to immutable WorkGraph authority Artifacts."""

    scope_id: Identifier
    coordinate: WorkCoordinate
    work_id: Identifier
    definition_digest: ContentHash
    input_fingerprint: ContentHash
    revision: Annotated[int, Field(ge=1)]
    status: WorkHeadStatus
    attempt_ref: ArtifactRef
    evaluation_ref: ArtifactRef | None = None
    repair_action_ref: ArtifactRef | None = None
    commit_ref: ArtifactRef | None = None
    invalidated_by_refs: tuple[ArtifactRef, ...] = ()
    updated_at: AwareDatetime

    @model_validator(mode="after")
    def validate_head(self) -> WorkControlHead:
        if self.scope_id != self.coordinate.scope_id:
            raise ValueError("work head scope must match its coordinate")
        if self.attempt_ref.artifact_type != "control.work_attempt":
            raise ValueError("work head attempt_ref has the wrong Artifact type")
        if self.evaluation_ref is not None and (
            self.evaluation_ref.artifact_type != "control.feedback_evaluation"
        ):
            raise ValueError("work head evaluation_ref has the wrong Artifact type")
        if self.repair_action_ref is not None and (
            self.repair_action_ref.artifact_type != "control.repair_action"
        ):
            raise ValueError("work head repair_action_ref has the wrong Artifact type")
        if self.commit_ref is not None and self.commit_ref.artifact_type != "control.work_commit":
            raise ValueError("work head commit_ref has the wrong Artifact type")
        if self.status == "repair_authorized" and (
            self.evaluation_ref is None or self.repair_action_ref is None
        ):
            raise ValueError("repair-authorized head requires evaluation and action refs")
        if self.status == "committed" and (
            self.evaluation_ref is None or self.commit_ref is None
        ):
            raise ValueError("committed head requires evaluation and commit refs")
        if self.status != "committed" and self.commit_ref is not None:
            raise ValueError("only committed heads may point to WorkCommit")
        if len(set(self.invalidated_by_refs)) != len(self.invalidated_by_refs):
            raise ValueError("work head invalidating refs must be unique")
        return self


@dataclass(frozen=True, slots=True)
class WorkControlLock:
    scope_id: str
    coordinate_key: str
    nonce: str


class WorkControlStore:
    """Own a crash-safe single-writer head for every exact WorkCoordinate."""

    def __init__(self, root: str | os.PathLike[str]) -> None:
        requested = Path(root).expanduser()
        if requested.exists() and requested.is_symlink():
            raise WorkControlStoreError("Work control root cannot be a symlink")
        requested.mkdir(parents=True, exist_ok=True)
        if requested.is_symlink() or not requested.is_dir():
            raise WorkControlStoreError("Work control root must be a real directory")
        self.root = requested.resolve(strict=True)
        self._active_locks: dict[str, tuple[int, str, str]] = {}
        for name in ("heads", "locks", "tmp"):
            path = self.root / name
            path.mkdir(mode=0o700, exist_ok=True)
            if path.is_symlink() or not path.is_dir():
                raise WorkControlStoreError(f"Work control {name} must be a real directory")

    @contextmanager
    def exclusive(self, coordinate: WorkCoordinate) -> Iterator[WorkControlLock]:
        key = self._key(coordinate.scope_id, coordinate.coordinate_key)
        path = self.root / "locks" / f"{key}.lock"
        descriptor = os.open(
            path,
            os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        try:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise WorkAlreadyRunningError(
                    f"coordinate already has an active runner: {coordinate.coordinate_key}"
                ) from exc
            lock = WorkControlLock(
                scope_id=coordinate.scope_id,
                coordinate_key=coordinate.coordinate_key,
                nonce=uuid.uuid4().hex,
            )
            self._active_locks[lock.nonce] = (
                descriptor,
                lock.scope_id,
                lock.coordinate_key,
            )
            yield lock
        finally:
            if "lock" in locals():
                self._active_locks.pop(lock.nonce, None)
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)

    def read_head(self, coordinate: WorkCoordinate) -> WorkControlHead | None:
        path = self._head_path(coordinate.scope_id, coordinate.coordinate_key)
        flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(path, flags)
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise WorkControlStoreError("cannot safely read WorkGraph head") from exc
        with os.fdopen(descriptor, "rb", closefd=True) as stream:
            raw = stream.read()
        try:
            head = WorkControlHead.model_validate_json(raw)
        except Exception as exc:
            raise WorkControlStoreError("invalid WorkGraph head") from exc
        if head.coordinate != coordinate:
            raise WorkControlStoreError("WorkGraph head coordinate mismatch")
        return head

    def compare_and_swap(
        self,
        lock: WorkControlLock,
        *,
        expected_head: WorkControlHead | None,
        next_head: WorkControlHead,
    ) -> WorkControlHead:
        next_head = WorkControlHead.model_validate(next_head.model_dump(mode="python"))
        self._validate_lock(lock, next_head.coordinate)
        current = self.read_head(next_head.coordinate)
        if current != expected_head:
            raise WorkHeadConflictError("WorkGraph head changed since it was loaded")
        if current is None:
            if next_head.revision != 1 or next_head.status != "running":
                raise WorkHeadConflictError("initial WorkGraph head must be running revision one")
        else:
            self._validate_transition(current, next_head)
        self._atomic_write(
            self._head_path(next_head.scope_id, next_head.coordinate.coordinate_key),
            next_head.stable_json_bytes(),
        )
        return next_head

    def supersede(
        self,
        lock: WorkControlLock,
        *,
        expected_head: WorkControlHead,
        next_head: WorkControlHead,
    ) -> WorkControlHead:
        """Reopen one terminal coordinate after explicit DAG invalidation."""

        next_head = WorkControlHead.model_validate(next_head.model_dump(mode="python"))
        self._validate_lock(lock, next_head.coordinate)
        current = self.read_head(next_head.coordinate)
        if current != expected_head:
            raise WorkHeadConflictError("WorkGraph head changed since it was loaded")
        if current.status not in {"committed", "failed", "needs_human", "interrupted"}:
            raise WorkHeadConflictError("only terminal WorkGraph heads may be superseded")
        if (
            next_head.scope_id != current.scope_id
            or next_head.coordinate != current.coordinate
            or next_head.work_id != current.work_id
            or next_head.revision != current.revision + 1
            or next_head.status != "running"
            or next_head.attempt_ref == current.attempt_ref
            or next_head.commit_ref is not None
            or next_head.evaluation_ref is not None
            or not next_head.invalidated_by_refs
        ):
            raise WorkHeadConflictError("invalid WorkGraph supersede transition")
        self._atomic_write(
            self._head_path(next_head.scope_id, next_head.coordinate.coordinate_key),
            next_head.stable_json_bytes(),
        )
        return next_head

    @staticmethod
    def _validate_transition(current: WorkControlHead, next_head: WorkControlHead) -> None:
        immutable = (
            "scope_id",
            "coordinate",
            "work_id",
            "definition_digest",
            "input_fingerprint",
        )
        if any(getattr(current, name) != getattr(next_head, name) for name in immutable):
            raise WorkHeadConflictError("WorkGraph identity and policy binding cannot change")
        if next_head.revision != current.revision + 1:
            raise WorkHeadConflictError("WorkGraph head revision must advance exactly once")
        allowed: dict[WorkHeadStatus, frozenset[WorkHeadStatus]] = {
            "running": frozenset(
                {
                    "running",
                    "repair_authorized",
                    "committed",
                    "failed",
                    "needs_human",
                    "interrupted",
                }
            ),
            "repair_authorized": frozenset({"running", "failed", "needs_human"}),
            "interrupted": frozenset({"running", "failed", "needs_human"}),
            "committed": frozenset(),
            "failed": frozenset(),
            "needs_human": frozenset(),
        }
        if next_head.status not in allowed[current.status]:
            raise WorkHeadConflictError(
                f"invalid WorkGraph transition: {current.status}->{next_head.status}"
            )
        if (
            next_head.status == "running"
            and next_head.attempt_ref == current.attempt_ref
        ):
            raise WorkHeadConflictError("a resumed/repaired run requires a new WorkAttempt")

    def require_active_commit(
        self,
        *,
        definition: WorkDefinition,
        input_refs: tuple[ArtifactRef, ...],
        artifacts: ArtifactWriter,
    ) -> tuple[WorkCommit, ArtifactRef] | None:
        """Return only an exact digest-bound, passing, immutable active commit."""

        head = self.read_head(definition.coordinate)
        if head is None or head.status != "committed" or head.commit_ref is None:
            return None
        expected_input_fingerprint = self.input_fingerprint(input_refs)
        if (
            head.work_id != definition.work_id
            or head.definition_digest != definition.definition_digest
            or head.input_fingerprint != expected_input_fingerprint
        ):
            return None
        commit = artifacts.get_json(head.commit_ref, WorkCommit)
        if (
            commit.work_id != definition.work_id
            or commit.coordinate != definition.coordinate
            or commit.definition_digest != definition.definition_digest
            or commit.validation_policy_digest
            != definition.validation_policy.content_digest()
            or frozenset(commit.input_refs) != frozenset(input_refs)
            or commit.feedback_evaluation_ref != head.evaluation_ref
        ):
            raise WorkResumeError("active WorkCommit does not match its WorkDefinition head")
        try:
            attempt = artifacts.get_json(head.attempt_ref, WorkAttempt)
        except ValidationError as exc:
            raise WorkResumeError(
                "active WorkCommit lacks its exact successful WorkAttempt"
            ) from exc
        if (
            attempt.status != "succeeded"
            or attempt.attempt_id != commit.attempt_id
            or attempt.work_id != definition.work_id
            or attempt.coordinate != definition.coordinate
            or attempt.definition_digest != definition.definition_digest
            or attempt.proposal_policy_digest != definition.proposal_policy.content_digest()
            or attempt.validation_policy_digest
            != definition.validation_policy.content_digest()
            or attempt.repair_policy_digest != definition.repair_policy.content_digest()
            or frozenset(attempt.input_refs) != frozenset(input_refs)
            or attempt.output_refs != commit.output_refs
            or attempt.feedback_evaluation_ref != commit.feedback_evaluation_ref
            or attempt.validation_report_ref is None
            or not attempt.proposal_execution_refs
        ):
            raise WorkResumeError("active WorkCommit lacks its exact successful WorkAttempt")
        report = artifacts.get_json(attempt.validation_report_ref, ValidationReport)
        evaluation = artifacts.get_json(
            commit.feedback_evaluation_ref,
            FeedbackEvaluation,
        )
        if (
            evaluation.work_id != definition.work_id
            or evaluation.coordinate != definition.coordinate
            or evaluation.attempt_id != commit.attempt_id
            or evaluation.claim_id != definition.required_claim_id
            or evaluation.policy_digest != definition.validation_policy.content_digest()
            or evaluation.effect != definition.validation_policy.effect
            or evaluation.status != "passed"
            or evaluation.readiness_effect != "satisfies"
            or evaluation.subject_ref not in commit.output_refs
            or not evaluation.releasable
        ):
            raise WorkResumeError("active WorkCommit lacks an exact passing evaluation")
        if (
            evaluation.validation_report_ref != attempt.validation_report_ref
            or report.attempt_id != attempt.attempt_id
            or report.coordinate != definition.coordinate
            or report.policy_id != definition.validation_policy.policy_id
            or report.policy_digest != definition.validation_policy.content_digest()
            or report.status != "passed"
            or report.subject_ref != evaluation.subject_ref
        ):
            raise WorkResumeError("active WorkCommit lacks its exact passing ValidationReport")
        executions = tuple(
            artifacts.get_json(ref, ProposalExecution)
            for ref in attempt.proposal_execution_refs
        )
        if any(
            execution.attempt_id != attempt.attempt_id
            or execution.executor != definition.proposal_policy.executor
            or execution.operation != definition.proposal_policy.operation
            or execution.status != "completed"
            for execution in executions
        ):
            raise WorkResumeError("active WorkAttempt lacks exact completed proposal evidence")
        subject = evaluation.subject_ref
        assert subject is not None
        if not any(execution.output_commitment == subject.content_hash for execution in executions):
            raise WorkResumeError("proposal output commitment does not bind committed subject")
        lease = artifacts.get_json(attempt.budget_lease_ref, BudgetLease)
        if (
            lease.status != "settled"
            or lease.observed_actual != attempt.observed_actual
            or lease.unknown_upper_bound != attempt.unknown_upper_bound
            or lease.conservative_committed != attempt.conservative_committed
        ):
            raise WorkResumeError("active WorkAttempt lacks an exact settled BudgetLease")
        commit_dependencies = frozenset(artifacts.dependencies(head.commit_ref))
        required_commit_dependencies = frozenset(
            (
                head.attempt_ref,
                commit.feedback_evaluation_ref,
                *commit.input_refs,
                *commit.output_refs,
            )
        )
        if commit_dependencies != required_commit_dependencies:
            raise WorkResumeError("WorkCommit dependency DAG does not match its authority chain")
        for ref in (*commit.input_refs, *commit.output_refs):
            artifacts.get_revision(ref)
        return commit, head.commit_ref

    @staticmethod
    def input_fingerprint(refs: tuple[ArtifactRef, ...]) -> ContentHash:
        if len(set(refs)) != len(refs):
            raise ValueError("WorkGraph input refs must be unique")
        body = "\0".join(sorted(ref.revision_id for ref in refs)).encode("utf-8")
        return "sha256:" + hashlib.sha256(body).hexdigest()

    @staticmethod
    def new_head(
        *,
        definition: WorkDefinition,
        input_refs: tuple[ArtifactRef, ...],
        attempt_ref: ArtifactRef,
    ) -> WorkControlHead:
        return WorkControlHead(
            scope_id=definition.coordinate.scope_id,
            coordinate=definition.coordinate,
            work_id=definition.work_id,
            definition_digest=definition.definition_digest,
            input_fingerprint=WorkControlStore.input_fingerprint(input_refs),
            revision=1,
            status="running",
            attempt_ref=attempt_ref,
            updated_at=datetime.now(UTC),
        )

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

    def _head_path(self, scope_id: str, coordinate_key: str) -> Path:
        return self.root / "heads" / f"{self._key(scope_id, coordinate_key)}.json"

    @staticmethod
    def _key(scope_id: str, coordinate_key: str) -> str:
        return hashlib.sha256(f"{scope_id}\0{coordinate_key}".encode()).hexdigest()

    def _validate_lock(self, lock: WorkControlLock, coordinate: WorkCoordinate) -> None:
        active = self._active_locks.get(lock.nonce)
        if (
            not lock.nonce
            or lock.scope_id != coordinate.scope_id
            or lock.coordinate_key != coordinate.coordinate_key
            or active is None
            or active[1:] != (coordinate.scope_id, coordinate.coordinate_key)
        ):
            raise WorkControlStoreError("invalid WorkGraph lock token")


__all__ = [
    "WorkAlreadyRunningError",
    "WorkControlHead",
    "WorkControlLock",
    "WorkControlStore",
    "WorkControlStoreError",
    "WorkHeadConflictError",
    "WorkHeadStatus",
    "WorkResumeError",
]
