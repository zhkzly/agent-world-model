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
from agent_world.contracts import ArtifactRef, BudgetUsage, ContentHash, Identifier, V2Contract
from agent_world.diagnostic_state import (
    TEST_NODE_DIAGNOSTIC_MARKER,
    TEST_NODE_DIAGNOSTIC_MARKER_CONTENT,
    has_test_node_diagnostic_marker,
)

from .models import BudgetLease
from .work import (
    AssuranceExecution,
    AssuranceReport,
    FeedbackEvaluation,
    OperationRun,
    ProposalExecution,
    ValidationExecution,
    ValidationReport,
    WorkAttempt,
    WorkCommit,
    WorkCoordinate,
    WorkDefinition,
    work_input_fingerprint,
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
    acceptance_digest: ContentHash
    input_fingerprint: ContentHash
    revision: Annotated[int, Field(ge=1)]
    status: WorkHeadStatus
    attempt_ref: ArtifactRef
    active_operation_ref: ArtifactRef | None = None
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
        if self.active_operation_ref is not None and (
            self.active_operation_ref.artifact_type != "control.operation_run"
        ):
            raise ValueError("work head active_operation_ref has the wrong Artifact type")
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
        if self.status == "committed" and (self.evaluation_ref is None or self.commit_ref is None):
            raise ValueError("committed head requires evaluation and commit refs")
        if self.status != "running" and self.active_operation_ref is not None:
            raise ValueError("only running Work may authorize an active operation")
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

    def read_scope_heads(self, scope_id: str) -> tuple[WorkControlHead, ...]:
        """Return every durable head in one stable scope partition.

        Head filenames are intentionally one-way hashes, so an agent-facing
        projection must validate the durable JSON records rather than infer a
        coordinate from a filename.  This method is read-only and does not
        grant any scheduling authority.
        """

        if not scope_id:
            raise WorkControlStoreError("scope id cannot be empty")
        return tuple(head for head in self._read_all_heads() if head.scope_id == scope_id)

    def latest_scope_id(self) -> str | None:
        """Return the most recently updated durable scope without scheduling it.

        The read-side observability CLI needs a deterministic ``--latest``
        selector, but must not infer a scope from cache directory names.  Heads
        remain the only authority for that choice.
        """

        heads = self._read_all_heads()
        if not heads:
            return None
        latest = max(
            heads,
            key=lambda item: (
                item.updated_at,
                item.scope_id,
                item.coordinate.coordinate_key,
            ),
        )
        return latest.scope_id

    def _read_all_heads(self) -> tuple[WorkControlHead, ...]:
        directory = self.root / "heads"
        if directory.is_symlink() or not directory.is_dir():
            raise WorkControlStoreError("Work control heads must be a real directory")
        heads: list[WorkControlHead] = []
        for entry in sorted(directory.iterdir(), key=lambda item: item.name):
            name = entry.name
            digest = name.removesuffix(".json")
            if (
                not name.endswith(".json")
                or len(digest) != 64
                or any(character not in "0123456789abcdef" for character in digest)
            ):
                continue
            flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
            try:
                descriptor = os.open(entry, flags)
            except OSError as exc:
                raise WorkControlStoreError("cannot safely read WorkGraph head") from exc
            with os.fdopen(descriptor, "rb", closefd=True) as stream:
                raw = stream.read()
            try:
                head = WorkControlHead.model_validate_json(raw)
            except Exception as exc:
                raise WorkControlStoreError("invalid WorkGraph head") from exc
            expected_path = self._head_path(
                head.scope_id,
                head.coordinate.coordinate_key,
            )
            if expected_path != entry:
                raise WorkControlStoreError("WorkGraph head path does not match its identity")
            heads.append(head)
        return tuple(sorted(heads, key=lambda item: item.coordinate.coordinate_key))

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

    def supersede_stale(
        self,
        lock: WorkControlLock,
        *,
        expected_head: WorkControlHead,
        next_head: WorkControlHead,
    ) -> WorkControlHead:
        """Replace a crash-left head whose immutable definition or inputs changed.

        Holding the exclusive coordinate lock proves that no live runner can
        still publish the previous attempt.  An unchanged definition/input pair
        is rejected so this operation cannot bypass repair-budget authority.
        """

        next_head = WorkControlHead.model_validate(next_head.model_dump(mode="python"))
        self._validate_lock(lock, next_head.coordinate)
        current = self.read_head(next_head.coordinate)
        if current != expected_head:
            raise WorkHeadConflictError("WorkGraph head changed since it was loaded")
        changed = (
            next_head.definition_digest != current.definition_digest
            or next_head.input_fingerprint != current.input_fingerprint
        )
        if (
            not changed
            or next_head.scope_id != current.scope_id
            or next_head.coordinate != current.coordinate
            or next_head.work_id != current.work_id
            or next_head.revision != current.revision + 1
            or next_head.status != "running"
            or next_head.attempt_ref == current.attempt_ref
            or next_head.commit_ref is not None
            or next_head.evaluation_ref is not None
            or not next_head.invalidated_by_refs
        ):
            raise WorkHeadConflictError("invalid stale WorkGraph supersede transition")
        self._atomic_write(
            self._head_path(next_head.scope_id, next_head.coordinate.coordinate_key),
            next_head.stable_json_bytes(),
        )
        return next_head

    def archive_terminal_head_for_diagnostic(
        self,
        lock: WorkControlLock,
        *,
        expected_head: WorkControlHead,
    ) -> Path:
        """Remove one copied terminal head from scheduling without erasing it.

        ``test-node`` needs a fresh physical attempt with the same scope and
        coordinate key so durable ancestor commits remain resolvable.  Normal
        supersession deliberately rejects that unchanged input/definition
        pair, because production code must not use diagnostics to bypass
        repair authority.  This narrow operation is therefore only suitable
        for an already-isolated state-root copy: it moves the exact terminal
        head out of ``heads/`` into an audit directory and leaves every
        Artifact revision untouched.
        """

        self._validate_lock(lock, expected_head.coordinate)
        self._require_diagnostic_archive_marker()
        current = self.read_head(expected_head.coordinate)
        if current != expected_head:
            raise WorkHeadConflictError("WorkGraph head changed before diagnostic archive")
        if current.status not in {"committed", "failed", "needs_human", "interrupted"}:
            raise WorkHeadConflictError("diagnostic archive requires a terminal WorkGraph head")
        source = self._head_path(current.scope_id, current.coordinate.coordinate_key)
        archive_directory = self.root / "diagnostic-superseded"
        archive_directory.mkdir(mode=0o700, exist_ok=True)
        if archive_directory.is_symlink() or not archive_directory.is_dir():
            raise WorkControlStoreError("diagnostic archive directory must be real")
        destination = archive_directory / f"{source.stem}-{uuid.uuid4().hex}.json"
        try:
            os.replace(source, destination)
            for directory_path in (archive_directory, source.parent):
                descriptor = os.open(directory_path, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
        except OSError as exc:
            raise WorkControlStoreError("cannot archive diagnostic WorkGraph head") from exc
        return destination

    def mark_test_node_diagnostic_clone(self) -> None:
        """Authorize diagnostic-head archiving for one freshly copied state root.

        This is deliberately not part of normal WorkGraph state transitions.
        The marker contains only the two public diagnostic flags and is written
        before the copied root is opened for a test-node dispatch.
        """

        marker = self.root / TEST_NODE_DIAGNOSTIC_MARKER
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(marker, flags, 0o600)
        except FileExistsError:
            self._require_diagnostic_archive_marker()
            return
        except OSError as exc:
            raise WorkControlStoreError("cannot mark test-node diagnostic state") from exc
        try:
            with os.fdopen(descriptor, "wb", closefd=True) as stream:
                stream.write(TEST_NODE_DIAGNOSTIC_MARKER_CONTENT)
                stream.flush()
                os.fsync(stream.fileno())
            directory = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        except OSError as exc:
            raise WorkControlStoreError("cannot mark test-node diagnostic state") from exc

    def _require_diagnostic_archive_marker(self) -> None:
        if not has_test_node_diagnostic_marker(self.root):
            raise WorkControlStoreError(
                "diagnostic head archive requires an isolated test-node state root"
            )

    def require_test_node_diagnostic_clone(self) -> None:
        """Prove this store belongs to an isolated marked diagnostic copy."""

        self._require_diagnostic_archive_marker()

    def authorize_causal_repair(
        self,
        lock: WorkControlLock,
        *,
        expected_head: WorkControlHead,
        next_head: WorkControlHead,
    ) -> WorkControlHead:
        """Install one already-authorized repair on a terminal causal target.

        Normal ``compare_and_swap`` deliberately forbids reopening a terminal
        head.  This narrow transition is the only exception: a Scheduler has
        proved a declared one-hop downstream finding and the target's own
        RepairAction/ledger has already accepted the target-local mutation
        budget.  The previous attempt remains immutable audit evidence; the
        following ``begin_authorized_repair`` creates the new physical attempt.
        """

        return self._authorize_terminal_repair(
            lock,
            expected_head=expected_head,
            next_head=next_head,
            allowed_statuses=frozenset({"committed", "failed", "needs_human", "interrupted"}),
            conflict_prefix="causal repair",
        )

    def authorize_infrastructure_retry(
        self,
        lock: WorkControlLock,
        *,
        expected_head: WorkControlHead,
        next_head: WorkControlHead,
    ) -> WorkControlHead:
        """Install one framework-authorized retry from a failed terminal head.

        The caller must already have validated the exact retryable
        ``ValidationReport`` and constructed a bound ``RepairAction`` / ledger
        entry.  This store method owns only the otherwise-forbidden terminal
        ``failed -> repair_authorized`` pointer transition; it never infers
        retry authority from a status or error string.
        """

        return self._authorize_terminal_repair(
            lock,
            expected_head=expected_head,
            next_head=next_head,
            allowed_statuses=frozenset({"failed"}),
            conflict_prefix="infrastructure retry",
        )

    def authorize_model_fallback(
        self,
        lock: WorkControlLock,
        *,
        expected_head: WorkControlHead,
        next_head: WorkControlHead,
    ) -> WorkControlHead:
        """Install one explicit fallback after a failed transient route.

        The recovery policy and repair ledger have already proved the failed
        model route, the compatible replacement, and the immutable input
        closure.  This method owns the otherwise-forbidden terminal
        ``failed -> repair_authorized`` pointer transition for that distinct
        recovery decision; it does not select a model or infer retry
        authority from an error string.
        """

        return self._authorize_terminal_repair(
            lock,
            expected_head=expected_head,
            next_head=next_head,
            allowed_statuses=frozenset({"failed"}),
            conflict_prefix="model fallback",
        )

    def authorize_diagnostic_semantic_repair(
        self,
        lock: WorkControlLock,
        *,
        expected_head: WorkControlHead,
        next_head: WorkControlHead,
    ) -> WorkControlHead:
        """Install one semantic repair only inside a marked diagnostic clone.

        A production failed head remains terminal unless its ordinary Scheduler
        authorizes the repair before settlement.  A diagnostic node deliberately
        stops after that first settled failure, so proving a feedback-bound
        correction requires this explicit opt-in transition in an isolated
        state root.  The caller still has to bind a normal RepairAction and
        repair ledger before this store changes the head.
        """

        self.require_test_node_diagnostic_clone()
        return self._authorize_terminal_repair(
            lock,
            expected_head=expected_head,
            next_head=next_head,
            allowed_statuses=frozenset({"failed"}),
            conflict_prefix="diagnostic semantic repair",
        )

    def _authorize_terminal_repair(
        self,
        lock: WorkControlLock,
        *,
        expected_head: WorkControlHead,
        next_head: WorkControlHead,
        allowed_statuses: frozenset[WorkHeadStatus],
        conflict_prefix: str,
    ) -> WorkControlHead:
        """Validate the one terminal-head exception used by repair authority."""

        next_head = WorkControlHead.model_validate(next_head.model_dump(mode="python"))
        self._validate_lock(lock, next_head.coordinate)
        current = self.read_head(next_head.coordinate)
        if current != expected_head:
            raise WorkHeadConflictError(f"WorkGraph head changed before {conflict_prefix}")
        if current.status not in allowed_statuses:
            raise WorkHeadConflictError(f"{conflict_prefix} target is not terminal")
        if (
            next_head.scope_id != current.scope_id
            or next_head.coordinate != current.coordinate
            or next_head.work_id != current.work_id
            or next_head.definition_digest != current.definition_digest
            or next_head.acceptance_digest != current.acceptance_digest
            or next_head.input_fingerprint != current.input_fingerprint
            or next_head.revision != current.revision + 1
            or next_head.status != "repair_authorized"
            or next_head.attempt_ref != current.attempt_ref
            or next_head.active_operation_ref is not None
            or next_head.evaluation_ref is None
            or next_head.repair_action_ref is None
            or next_head.commit_ref is not None
            or not next_head.invalidated_by_refs
        ):
            raise WorkHeadConflictError(f"invalid {conflict_prefix} authorization transition")
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
            "acceptance_digest",
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
            "repair_authorized": frozenset(
                {"repair_authorized", "running", "failed", "needs_human"}
            ),
            "interrupted": frozenset({"running", "failed", "needs_human"}),
            "committed": frozenset(),
            "failed": frozenset(),
            "needs_human": frozenset(),
        }
        if next_head.status not in allowed[current.status]:
            raise WorkHeadConflictError(
                f"invalid WorkGraph transition: {current.status}->{next_head.status}"
            )
        if current.status == next_head.status == "repair_authorized" and (
            next_head.evaluation_ref != current.evaluation_ref
            or next_head.repair_action_ref != current.repair_action_ref
            or next_head.commit_ref is not None
            or next_head.attempt_ref == current.attempt_ref
        ):
            raise WorkHeadConflictError(
                "repair continuation binding must preserve exact repair authority"
            )
        if current.active_operation_ref is not None and (
            next_head.active_operation_ref == current.active_operation_ref
        ):
            raise WorkHeadConflictError("active OperationRun must advance or terminate")
        if next_head.status == "running" and next_head.attempt_ref == current.attempt_ref:
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
            or head.acceptance_digest != definition.acceptance_digest
            or head.input_fingerprint != expected_input_fingerprint
        ):
            return None
        # A correctly marked diagnostic commit is non-active normal authority,
        # not a corrupt production head.  Returning ``None`` lets ordinary
        # schedulers hold it stale; the explicit diagnostic path below still
        # validates its complete authority chain before a marked successor may
        # consume it.
        commit = artifacts.get_json(head.commit_ref, WorkCommit)
        if commit.diagnostic_only:
            return None
        return self._validate_commit_head(
            head=head,
            definition=definition,
            input_refs=input_refs,
            artifacts=artifacts,
        )

    def require_diagnostic_commit(
        self,
        *,
        definition: WorkDefinition,
        input_refs: tuple[ArtifactRef, ...],
        artifacts: ArtifactWriter,
    ) -> tuple[WorkCommit, ArtifactRef] | None:
        """Return one exact passed diagnostic commit inside a marked test-node copy.

        This is intentionally separate from :meth:`require_active_commit`.
        A diagnostic result is never normal release authority, even when its
        validator passed.  The only permitted consumer is a second isolated
        diagnostic node whose state root bears the exact test-node marker.
        """

        if not has_test_node_diagnostic_marker(self.root):
            raise WorkResumeError(
                "diagnostic WorkCommit reuse requires an isolated test-node state root"
            )
        head = self.read_head(definition.coordinate)
        if head is None or head.status != "committed" or head.commit_ref is None:
            return None
        expected_input_fingerprint = self.input_fingerprint(input_refs)
        if (
            head.work_id != definition.work_id
            or head.definition_digest != definition.definition_digest
            or head.acceptance_digest != definition.acceptance_digest
            or head.input_fingerprint != expected_input_fingerprint
        ):
            return None
        return self._validate_commit_head(
            head=head,
            definition=definition,
            input_refs=input_refs,
            artifacts=artifacts,
            diagnostic_only=True,
        )

    def require_active_or_diagnostic_commit(
        self,
        *,
        definition: WorkDefinition,
        input_refs: tuple[ArtifactRef, ...],
        artifacts: ArtifactWriter,
    ) -> tuple[WorkCommit, ArtifactRef] | None:
        """Return normal authority first, then a marker-gated diagnostic commit.

        Callers must opt into this method explicitly.  It is deliberately not
        used by normal scheduling, epoch freezing, cache recovery, final
        topology derivation, or release code.
        """

        active = self.require_active_commit(
            definition=definition,
            input_refs=input_refs,
            artifacts=artifacts,
        )
        if active is not None:
            return active
        return self.require_diagnostic_commit(
            definition=definition,
            input_refs=input_refs,
            artifacts=artifacts,
        )

    def reactivate_historical_commit(
        self,
        lock: WorkControlLock,
        *,
        definition: WorkDefinition,
        input_refs: tuple[ArtifactRef, ...],
        artifacts: ArtifactWriter,
    ) -> tuple[WorkCommit, ArtifactRef] | None:
        """Restore one exact immutable commit after an unrelated head superseded it.

        This is a cache reactivation, not a new success decision.  The complete
        proposal/validation/budget authority chain is revalidated before the
        mutable projection moves.  Ambiguous historical successes are rejected
        rather than choosing one semantic output by ordering accident.
        """

        self._validate_lock(lock, definition.coordinate)
        current = self.read_head(definition.coordinate)
        if current is None:
            return None
        found = self.find_historical_commit(
            definition=definition,
            input_refs=input_refs,
            artifacts=artifacts,
        )
        if found is None:
            return None
        commit, commit_ref, attempt_ref = found
        expected_fingerprint = self.input_fingerprint(input_refs)
        next_head = WorkControlHead(
            scope_id=definition.coordinate.scope_id,
            coordinate=definition.coordinate,
            work_id=definition.work_id,
            definition_digest=definition.definition_digest,
            acceptance_digest=definition.acceptance_digest,
            input_fingerprint=expected_fingerprint,
            revision=current.revision + 1,
            status="committed",
            attempt_ref=attempt_ref,
            evaluation_ref=commit.feedback_evaluation_ref,
            commit_ref=commit_ref,
            invalidated_by_refs=tuple(
                dict.fromkeys(
                    (
                        current.attempt_ref,
                        *(ref for ref in (current.commit_ref,) if ref is not None),
                    )
                )
            ),
            updated_at=datetime.now(UTC),
        )
        self._validate_commit_head(
            head=next_head,
            definition=definition,
            input_refs=input_refs,
            artifacts=artifacts,
        )
        latest = self.read_head(definition.coordinate)
        if latest != current:
            raise WorkHeadConflictError("WorkGraph head changed during historical recovery")
        self._atomic_write(
            self._head_path(next_head.scope_id, next_head.coordinate.coordinate_key),
            next_head.stable_json_bytes(),
        )
        return commit, commit_ref

    def find_historical_commit(
        self,
        *,
        definition: WorkDefinition,
        input_refs: tuple[ArtifactRef, ...],
        artifacts: ArtifactWriter,
    ) -> tuple[WorkCommit, ArtifactRef, ArtifactRef] | None:
        """Find one exact prior success without changing the mutable projection."""

        expected_fingerprint = self.input_fingerprint(input_refs)
        candidates: dict[str, tuple[WorkCommit, ArtifactRef, ArtifactRef]] = {}
        for commit_ref in artifacts.list_revisions():
            if commit_ref.artifact_type != "control.work_commit":
                continue
            try:
                commit = artifacts.get_json(commit_ref, WorkCommit)
            except ValidationError:
                continue
            if (
                commit.work_id != definition.work_id
                or commit.coordinate != definition.coordinate
                or commit.acceptance_digest != definition.acceptance_digest
                or frozenset(commit.input_refs) != frozenset(input_refs)
            ):
                continue
            dependencies = artifacts.dependencies(commit_ref)
            attempt_refs = tuple(
                ref for ref in dependencies if ref.artifact_type == "control.work_attempt"
            )
            if len(attempt_refs) != 1:
                continue
            candidate_head = WorkControlHead(
                scope_id=definition.coordinate.scope_id,
                coordinate=definition.coordinate,
                work_id=definition.work_id,
                definition_digest=definition.definition_digest,
                acceptance_digest=definition.acceptance_digest,
                input_fingerprint=expected_fingerprint,
                revision=1,
                status="committed",
                attempt_ref=attempt_refs[0],
                evaluation_ref=commit.feedback_evaluation_ref,
                commit_ref=commit_ref,
                invalidated_by_refs=(),
                updated_at=datetime.now(UTC),
            )
            try:
                self._validate_commit_head(
                    head=candidate_head,
                    definition=definition,
                    input_refs=input_refs,
                    artifacts=artifacts,
                )
            except WorkResumeError:
                continue
            candidates[commit_ref.revision_id] = (
                commit,
                commit_ref,
                attempt_refs[0],
            )
        if not candidates:
            return None
        if len(candidates) != 1:
            raise WorkResumeError(
                "multiple exact historical WorkCommits require explicit invalidation"
            )
        return next(iter(candidates.values()))

    def _validate_commit_head(
        self,
        *,
        head: WorkControlHead,
        definition: WorkDefinition,
        input_refs: tuple[ArtifactRef, ...],
        artifacts: ArtifactWriter,
        diagnostic_only: bool = False,
    ) -> tuple[WorkCommit, ArtifactRef]:
        """Validate one candidate committed head without consulting current projection."""

        if head.status != "committed" or head.commit_ref is None:
            raise WorkResumeError("candidate WorkGraph head is not committed")
        commit = artifacts.get_json(head.commit_ref, WorkCommit)
        original_definition = self._require_commit_definition(
            commit=commit,
            artifacts=artifacts,
        )
        if (
            commit.work_id != definition.work_id
            or commit.coordinate != definition.coordinate
            or commit.acceptance_digest != definition.acceptance_digest
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
            or attempt.definition_digest != commit.definition_digest
            or attempt.validation_policy_digest != commit.validation_policy_digest
            or frozenset(attempt.input_refs) != frozenset(input_refs)
            or attempt.output_refs != commit.output_refs
            or attempt.child_commit_refs != commit.child_commit_refs
            or attempt.feedback_evaluation_ref != commit.feedback_evaluation_ref
            or attempt.operation_run_refs != commit.operation_run_refs
            or attempt.assurance_report_ref != commit.assurance_report_ref
            or attempt.validation_report_ref is None
            or len(attempt.operation_run_refs) < 2
        ):
            raise WorkResumeError("active WorkCommit lacks its exact successful WorkAttempt")
        report = artifacts.get_json(attempt.validation_report_ref, ValidationReport)
        evaluation = artifacts.get_json(
            commit.feedback_evaluation_ref,
            FeedbackEvaluation,
        )
        expected_releasable = not diagnostic_only
        expected_readiness = "observes" if diagnostic_only else "satisfies"
        if (
            attempt.diagnostic_only != diagnostic_only
            or attempt.releasable != expected_releasable
            or commit.diagnostic_only != diagnostic_only
            or commit.releasable != expected_releasable
            or report.diagnostic_only != diagnostic_only
            or report.releasable != expected_releasable
            or evaluation.diagnostic_only != diagnostic_only
            or evaluation.releasable != expected_releasable
        ):
            raise WorkResumeError("WorkCommit diagnostic authority marking is inconsistent")
        if (
            evaluation.work_id != definition.work_id
            or evaluation.coordinate != definition.coordinate
            or evaluation.attempt_id != commit.attempt_id
            or evaluation.claim_id != original_definition.required_claim_id
            or evaluation.acceptance_digest != commit.acceptance_digest
            or evaluation.policy_digest != commit.validation_policy_digest
            or evaluation.effect != original_definition.validation_policy.effect
            or evaluation.status != "passed"
            or evaluation.readiness_effect != expected_readiness
            or evaluation.subject_refs != commit.validated_subject_refs
        ):
            raise WorkResumeError("active WorkCommit lacks an exact passing evaluation")
        if (
            evaluation.validation_report_ref != attempt.validation_report_ref
            or report.attempt_id != attempt.attempt_id
            or report.coordinate != definition.coordinate
            or report.policy_id != original_definition.validation_policy.policy_id
            or report.policy_digest != commit.validation_policy_digest
            or report.status != "passed"
            or report.subject_refs != evaluation.subject_refs
        ):
            raise WorkResumeError("active WorkCommit lacks its exact passing ValidationReport")
        operations = tuple(
            artifacts.get_json(ref, OperationRun) for ref in attempt.operation_run_refs
        )
        if any(
            operation.attempt_id != attempt.attempt_id
            or operation.coordinate != definition.coordinate
            or operation.status != "terminal"
            or operation.execution_ref is None
            for operation in operations
        ):
            raise WorkResumeError("WorkAttempt contains incomplete OperationRun evidence")
        proposal_runs = tuple(item for item in operations if item.kind == "proposal")
        validation_runs = tuple(item for item in operations if item.kind == "validation")
        assurance_runs = tuple(item for item in operations if item.kind == "assurance")
        if not proposal_runs or len(validation_runs) != 1:
            raise WorkResumeError("WorkAttempt lacks proposal or validation OperationRun")
        proposal_executions = tuple(
            artifacts.get_json(item.execution_ref, ProposalExecution)
            for item in proposal_runs
            if item.execution_ref is not None
        )
        if any(
            execution.attempt_id != attempt.attempt_id
            or execution.executor != original_definition.proposal_policy.executor
            or execution.operation != original_definition.proposal_policy.operation
            or execution.status != "completed"
            for execution in proposal_executions
        ):
            raise WorkResumeError("active WorkAttempt lacks exact completed proposal evidence")
        if not any(
            execution.output_commitment == subject.content_hash
            for execution in proposal_executions
            for subject in evaluation.subject_refs
        ):
            raise WorkResumeError("proposal output commitment does not bind committed subject")
        validation_run = validation_runs[0]
        assert validation_run.execution_ref is not None
        validation_execution = artifacts.get_json(
            validation_run.execution_ref,
            ValidationExecution,
        )
        assurance_executions = tuple(
            artifacts.get_json(item.execution_ref, AssuranceExecution)
            for item in assurance_runs
            if item.execution_ref is not None
        )
        assurance_report = (
            artifacts.get_json(attempt.assurance_report_ref, AssuranceReport)
            if attempt.assurance_report_ref is not None
            else None
        )
        assurance_policy = original_definition.assurance_policy
        if (
            assurance_policy is None and (assurance_executions or assurance_report is not None)
        ) or (
            assurance_policy is not None and (not assurance_executions or assurance_report is None)
        ):
            raise WorkResumeError("assurance executions do not match WorkDefinition policy")
        if (
            validation_execution.attempt_id != attempt.attempt_id
            or validation_execution.policy_id != original_definition.validation_policy.policy_id
            or validation_execution.validator_id
            != original_definition.validation_policy.validator_id
            or validation_execution.validator_revision_id
            != original_definition.validation_policy.validator_revision_id
            or validation_execution.status != "completed"
            or attempt.validation_report_ref not in validation_run.output_refs
        ):
            raise WorkResumeError("WorkAttempt lacks exact validation execution evidence")
        if len(assurance_executions) != len(assurance_runs) or any(
            execution.attempt_id != attempt.attempt_id
            or execution.status != "completed"
            or assurance_policy is None
            or execution.policy_id != assurance_policy.policy_id
            or execution.runtime_profile_id != assurance_policy.runtime_profile_id
            or execution.probe_ids != assurance_policy.probe_ids
            or execution.evidence_freshness != assurance_policy.evidence_freshness
            for execution in assurance_executions
        ):
            raise WorkResumeError("WorkAttempt lacks exact assurance execution evidence")
        if assurance_report is not None and (
            assurance_policy is None
            or assurance_report.attempt_id != attempt.attempt_id
            or assurance_report.coordinate != definition.coordinate
            or assurance_report.policy_id != assurance_policy.policy_id
            or assurance_report.policy_digest != assurance_policy.content_digest()
            or assurance_report.runtime_profile_id != assurance_policy.runtime_profile_id
            or assurance_report.evidence_freshness != assurance_policy.evidence_freshness
            or tuple(item.probe_id for item in assurance_report.probe_results)
            != assurance_policy.probe_ids
            or assurance_report.status != "passed"
            or commit.assurance_report_ref != attempt.assurance_report_ref
            or evaluation.assurance_report_ref != attempt.assurance_report_ref
        ):
            raise WorkResumeError("WorkAttempt lacks one exact passing AssuranceReport")
        assurance_evidence_refs = (
            assurance_report.evidence_refs if assurance_report is not None else ()
        )
        if evaluation.assurance_evidence_refs != assurance_evidence_refs:
            raise WorkResumeError("evaluation does not bind exact assurance evidence")
        actual = BudgetUsage()
        unknown = BudgetUsage()
        committed_usage = BudgetUsage()
        for operation in operations:
            owned_lease = artifacts.get_json(operation.budget_lease_ref, BudgetLease)
            if (
                owned_lease.status != "settled"
                or owned_lease.owner_id != operation.operation_run_id
                or owned_lease.observed_actual != operation.observed_actual
                or owned_lease.unknown_upper_bound != operation.unknown_upper_bound
                or owned_lease.conservative_committed != operation.conservative_committed
            ):
                raise WorkResumeError("OperationRun lacks its exact settled lease")
            actual = self._add_usage(actual, owned_lease.observed_actual)
            unknown = self._add_usage(unknown, owned_lease.unknown_upper_bound)
            committed_usage = self._add_usage(
                committed_usage,
                owned_lease.conservative_committed,
            )
        if (
            actual != attempt.observed_actual
            or unknown != attempt.unknown_upper_bound
            or committed_usage != attempt.conservative_committed
        ):
            raise WorkResumeError("active WorkAttempt lacks exact settled operation leases")
        commit_dependencies = frozenset(artifacts.dependencies(head.commit_ref))
        required_commit_dependencies = frozenset(
            (
                head.attempt_ref,
                *commit.operation_run_refs,
                *((commit.assurance_report_ref,) if commit.assurance_report_ref else ()),
                commit.feedback_evaluation_ref,
                *commit.input_refs,
                *commit.validated_subject_refs,
                *commit.output_refs,
                *commit.child_commit_refs,
            )
        )
        if commit_dependencies != required_commit_dependencies:
            raise WorkResumeError("WorkCommit dependency DAG does not match its authority chain")
        for ref in (*commit.input_refs, *commit.output_refs):
            artifacts.get_revision(ref)
        return commit, head.commit_ref

    @staticmethod
    def _add_usage(left: BudgetUsage, right: BudgetUsage) -> BudgetUsage:
        return BudgetUsage.model_validate(
            {
                field_name: getattr(left, field_name) + getattr(right, field_name)
                for field_name in BudgetUsage.model_fields
                if field_name != "schema_version"
            }
        )

    @staticmethod
    def require_running_definition(
        *,
        head: WorkControlHead,
        artifacts: ArtifactWriter,
    ) -> WorkDefinition:
        """Recover the immutable definition that owns one running operation.

        A restart can derive a newer graph while an earlier process still owns
        an operation under its frozen definition.  The historical definition is
        authority only to settle that operation; callers must still project the
        resulting terminal head against their current graph before dispatching
        anything new.
        """

        if head.status != "running" or head.active_operation_ref is None:
            raise WorkResumeError("running definition recovery requires one active Work operation")
        try:
            attempt = artifacts.get_json(head.attempt_ref, WorkAttempt)
        except ValidationError as exc:
            raise WorkResumeError("running Work head lacks its exact WorkAttempt") from exc
        if (
            attempt.work_id != head.work_id
            or attempt.coordinate != head.coordinate
            or attempt.definition_digest != head.definition_digest
            or WorkControlStore.input_fingerprint(attempt.input_refs) != head.input_fingerprint
        ):
            raise WorkResumeError("running Work head does not bind its exact WorkAttempt")

        candidates: list[WorkDefinition] = []
        for ref in artifacts.list_revisions():
            if (
                ref.artifact_type != "control.work_definition"
                or ref.content_hash != head.definition_digest
            ):
                continue
            try:
                candidate = artifacts.get_json(ref, WorkDefinition)
            except ValidationError:
                continue
            if (
                candidate.work_id == head.work_id
                and candidate.coordinate == head.coordinate
                and candidate.definition_digest == head.definition_digest
                and candidate.acceptance_digest == head.acceptance_digest
                and candidate.proposal_policy.content_digest() == attempt.proposal_policy_digest
                and candidate.validation_policy.content_digest() == attempt.validation_policy_digest
                and (
                    None
                    if candidate.assurance_policy is None
                    else candidate.assurance_policy.content_digest()
                )
                == attempt.assurance_policy_digest
                and candidate.repair_policy.content_digest() == attempt.repair_policy_digest
            ):
                candidates.append(candidate)
        if not candidates or any(candidate != candidates[0] for candidate in candidates[1:]):
            raise WorkResumeError("running Work head lacks one exact originating WorkDefinition")
        return candidates[0]

    @staticmethod
    def _require_commit_definition(
        *,
        commit: WorkCommit,
        artifacts: ArtifactWriter,
    ) -> WorkDefinition:
        """Recover and verify the immutable definition that authorized a commit."""

        candidates: list[WorkDefinition] = []
        for ref in artifacts.list_revisions():
            if (
                ref.artifact_type != "control.work_definition"
                or ref.content_hash != commit.definition_digest
                or frozenset(artifacts.dependencies(ref)) != frozenset(commit.input_refs)
            ):
                continue
            try:
                candidate = artifacts.get_json(ref, WorkDefinition)
            except ValidationError:
                continue
            if (
                candidate.work_id == commit.work_id
                and candidate.coordinate == commit.coordinate
                and candidate.definition_digest == commit.definition_digest
                and candidate.acceptance_digest == commit.acceptance_digest
                and candidate.validation_policy.content_digest() == commit.validation_policy_digest
            ):
                candidates.append(candidate)
        if not candidates or any(candidate != candidates[0] for candidate in candidates[1:]):
            raise WorkResumeError("WorkCommit lacks one exact originating WorkDefinition")
        return candidates[0]

    @staticmethod
    def input_fingerprint(refs: tuple[ArtifactRef, ...]) -> ContentHash:
        return work_input_fingerprint(refs)

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
            acceptance_digest=definition.acceptance_digest,
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
