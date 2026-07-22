"""Vector budget accounting; dimensions are never silently exchanged."""

from __future__ import annotations

import fcntl
import hashlib
import os
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Annotated

from pydantic import AwareDatetime, Field, model_validator

from agent_world.contracts import Budget, BudgetUsage, Identifier, V2Contract

from .models import BudgetLease

_FIELDS = tuple(field for field in Budget.model_fields if field != "schema_version")


class BudgetExceeded(RuntimeError):
    def __init__(self, dimensions: tuple[str, ...]) -> None:
        super().__init__(f"budget exhausted: {', '.join(dimensions)}")
        self.dimensions = dimensions


@dataclass(slots=True)
class BudgetLedger:
    reserved: Budget
    _used: BudgetUsage
    _observed_actual: BudgetUsage
    _unknown_upper_bound: BudgetUsage

    def __init__(self, reserved: Budget, used: BudgetUsage | None = None) -> None:
        self.reserved = reserved
        self._used = used or BudgetUsage()
        self._observed_actual = self._used
        self._unknown_upper_bound = BudgetUsage()
        self._assert_within(self._used)

    @property
    def used(self) -> BudgetUsage:
        """Return the conservative commitment used for admission."""

        return self._used

    @property
    def observed_actual(self) -> BudgetUsage:
        return self._observed_actual

    @property
    def unknown_upper_bound(self) -> BudgetUsage:
        return self._unknown_upper_bound

    @property
    def remaining(self) -> Budget:
        return Budget.model_validate(
            {
                field: _subtract(
                    getattr(self.reserved, field),
                    getattr(self._used, field),
                )
                for field in _FIELDS
            }
        )

    def can_consume(self, usage: BudgetUsage) -> bool:
        candidate = self._sum(usage)
        return not self._exceeded(candidate)

    def consume(self, usage: BudgetUsage) -> BudgetUsage:
        return self.consume_uncertain(
            observed_actual=usage,
            unknown_upper_bound=BudgetUsage(),
        )

    def consume_uncertain(
        self,
        *,
        observed_actual: BudgetUsage,
        unknown_upper_bound: BudgetUsage,
    ) -> BudgetUsage:
        committed = _sum_usage(observed_actual, unknown_upper_bound)
        candidate = self._sum(committed)
        exceeded = self._exceeded(candidate)
        if exceeded:
            raise BudgetExceeded(exceeded)
        self._used = candidate
        self._observed_actual = _sum_usage(self._observed_actual, observed_actual)
        self._unknown_upper_bound = _sum_usage(
            self._unknown_upper_bound,
            unknown_upper_bound,
        )
        return self._used

    def _sum(self, usage: BudgetUsage) -> BudgetUsage:
        return BudgetUsage.model_validate(
            {field: _add(getattr(self._used, field), getattr(usage, field)) for field in _FIELDS}
        )

    def _assert_within(self, usage: BudgetUsage) -> None:
        exceeded = self._exceeded(usage)
        if exceeded:
            raise BudgetExceeded(exceeded)

    def _exceeded(self, usage: BudgetUsage) -> tuple[str, ...]:
        return tuple(
            field
            for field in _FIELDS
            if Decimal(str(getattr(usage, field))) > Decimal(str(getattr(self.reserved, field)))
        )


class LeaseBudgetLedger:
    """Reserve and settle child work without exchanging budget dimensions."""

    def __init__(
        self,
        reserved: Budget,
        *,
        leases: tuple[BudgetLease, ...] = (),
    ) -> None:
        self.reserved = reserved
        self._leases: dict[str, BudgetLease] = {}
        self._used = BudgetUsage()
        for lease in leases:
            if lease.lease_id in self._leases:
                raise ValueError(f"duplicate restored lease: {lease.lease_id}")
            if lease.reserved.wall_seconds > reserved.wall_seconds:
                raise BudgetExceeded(("wall_seconds",))
            self._leases[lease.lease_id] = lease
            if lease.status == "settled":
                self._used = _sum_usage(
                    self._used,
                    _without_wall(lease.conservative_committed),
                )
        self._assert_non_wall_capacity()

    @property
    def leases(self) -> tuple[BudgetLease, ...]:
        return tuple(sorted(self._leases.values(), key=lambda item: item.lease_id))

    @property
    def active_leases(self) -> tuple[BudgetLease, ...]:
        return tuple(item for item in self.leases if item.status == "active")

    def usage(self, *, elapsed_wall_seconds: float) -> BudgetUsage:
        elapsed = _bounded_elapsed(elapsed_wall_seconds, self.reserved.wall_seconds)
        return self._used.model_copy(update={"wall_seconds": elapsed})

    def remaining(self, *, elapsed_wall_seconds: float) -> Budget:
        active = BudgetUsage()
        for lease in self.active_leases:
            active = _sum_usage(active, _without_wall(lease.reserved))
        committed = _sum_usage(self._used, active)
        values = {
            field: _subtract(getattr(self.reserved, field), getattr(committed, field))
            for field in _FIELDS
        }
        values["wall_seconds"] = _subtract(
            self.reserved.wall_seconds,
            _bounded_elapsed(elapsed_wall_seconds, self.reserved.wall_seconds),
        )
        return Budget.model_validate(values)

    def reserve(
        self,
        *,
        lease_id: str,
        owner_id: str,
        requested: Budget,
        elapsed_wall_seconds: float,
    ) -> BudgetLease:
        existing = self._leases.get(lease_id)
        if existing is not None:
            if (
                existing.owner_id != owner_id
                or existing.reserved != requested
                or existing.status != "active"
            ):
                raise ValueError("lease id is already bound to different or terminal work")
            return existing
        available = self.remaining(elapsed_wall_seconds=elapsed_wall_seconds)
        exceeded = tuple(
            field
            for field in _FIELDS
            if Decimal(str(getattr(requested, field))) > Decimal(str(getattr(available, field)))
        )
        if exceeded:
            raise BudgetExceeded(exceeded)
        lease = BudgetLease(
            lease_id=lease_id,
            owner_id=owner_id,
            reserved=requested,
            created_at=datetime.now(UTC),
        )
        self._leases[lease_id] = lease
        return lease

    def settle(
        self,
        lease_id: str,
        observed_actual: BudgetUsage,
        *,
        unknown_upper_bound: BudgetUsage | None = None,
    ) -> BudgetLease:
        lease = self._active(lease_id)
        unknown = unknown_upper_bound or BudgetUsage()
        committed = _sum_usage(observed_actual, unknown)
        lease_exceeded = _exceeded_usage(committed, lease.reserved, include_wall=True)
        if lease_exceeded:
            raise BudgetExceeded(lease_exceeded)
        settled = BudgetLease(
            lease_id=lease.lease_id,
            owner_id=lease.owner_id,
            reserved=lease.reserved,
            status="settled",
            observed_actual=observed_actual,
            unknown_upper_bound=unknown,
            conservative_committed=committed,
            created_at=lease.created_at,
            finished_at=datetime.now(UTC),
        )
        candidate = _sum_usage(self._used, _without_wall(committed))
        exceeded = _exceeded_usage(candidate, self.reserved, include_wall=False)
        if exceeded:
            raise BudgetExceeded(exceeded)
        self._leases[lease_id] = settled
        self._used = candidate
        return settled

    def release(self, lease_id: str) -> BudgetLease:
        lease = self._active(lease_id)
        released = BudgetLease(
            lease_id=lease.lease_id,
            owner_id=lease.owner_id,
            reserved=lease.reserved,
            status="released",
            created_at=lease.created_at,
            finished_at=datetime.now(UTC),
        )
        self._leases[lease_id] = released
        return released

    def _active(self, lease_id: str) -> BudgetLease:
        try:
            lease = self._leases[lease_id]
        except KeyError as exc:
            raise ValueError(f"unknown budget lease: {lease_id}") from exc
        if lease.status != "active":
            raise ValueError(f"budget lease is already terminal: {lease_id}")
        return lease

    def _assert_non_wall_capacity(self) -> None:
        committed = self._used
        for lease in self.active_leases:
            committed = _sum_usage(committed, _without_wall(lease.reserved))
        exceeded = _exceeded_usage(committed, self.reserved, include_wall=False)
        if exceeded:
            raise BudgetExceeded(exceeded)


class ScopeBudgetSnapshot(V2Contract):
    """Durable authority for all operation leases in one WorkGraph scope."""

    scope_id: Identifier
    reserved: Budget
    revision: Annotated[int, Field(ge=0)] = 0
    leases: tuple[BudgetLease, ...] = ()
    updated_at: AwareDatetime

    @model_validator(mode="after")
    def validate_capacity(self) -> ScopeBudgetSnapshot:
        if len({item.lease_id for item in self.leases}) != len(self.leases):
            raise ValueError("scope budget lease ids must be unique")
        LeaseBudgetLedger(self.reserved, leases=self.leases)
        return self


class DurableLeaseBudgetCoordinator:
    """Cross-process budget admission and idempotent settlement.

    The snapshot is the mutable budget authority. Immutable BudgetLease
    Artifacts remain evidence, but cannot independently reserve capacity.
    """

    def __init__(self, root: str | os.PathLike[str]) -> None:
        requested = Path(root).expanduser()
        if requested.exists() and requested.is_symlink():
            raise ValueError("budget coordinator root cannot be a symlink")
        requested.mkdir(parents=True, exist_ok=True)
        if requested.is_symlink() or not requested.is_dir():
            raise ValueError("budget coordinator root must be a real directory")
        self.root = requested.resolve(strict=True)
        for name in ("snapshots", "locks", "tmp"):
            path = self.root / name
            path.mkdir(mode=0o700, exist_ok=True)
            if path.is_symlink() or not path.is_dir():
                raise ValueError("budget coordinator directories must be real")

    def initialize(
        self,
        *,
        scope_id: str,
        reserved: Budget,
        leases: tuple[BudgetLease, ...] = (),
    ) -> ScopeBudgetSnapshot:
        with self._exclusive(scope_id):
            current = self._read(scope_id)
            if current is not None:
                if current.reserved != reserved:
                    raise ValueError("scope budget cannot change after initialization")
                return current
            snapshot = ScopeBudgetSnapshot(
                scope_id=scope_id,
                reserved=reserved,
                leases=leases,
                updated_at=datetime.now(UTC),
            )
            self._write(snapshot)
            return snapshot

    def snapshot(self, *, scope_id: str) -> ScopeBudgetSnapshot:
        current = self._read(scope_id)
        if current is None:
            raise ValueError("scope budget is not initialized")
        return current

    def reserve(
        self,
        *,
        scope_id: str,
        lease_id: str,
        owner_id: str,
        requested: Budget,
        elapsed_wall_seconds: float,
    ) -> BudgetLease:
        with self._exclusive(scope_id):
            current = self._require(scope_id)
            existing = next(
                (item for item in current.leases if item.lease_id == lease_id),
                None,
            )
            if existing is not None:
                if (
                    existing.owner_id == owner_id
                    and existing.reserved == requested
                    and existing.status == "active"
                ):
                    return existing
                raise ValueError("lease id is already bound to different or terminal work")
            ledger = LeaseBudgetLedger(current.reserved, leases=current.leases)
            lease = ledger.reserve(
                lease_id=lease_id,
                owner_id=owner_id,
                requested=requested,
                elapsed_wall_seconds=elapsed_wall_seconds,
            )
            self._write_next(current, ledger.leases)
            return lease

    def settle(
        self,
        *,
        scope_id: str,
        lease_id: str,
        observed_actual: BudgetUsage,
        unknown_upper_bound: BudgetUsage | None = None,
    ) -> BudgetLease:
        unknown = unknown_upper_bound or BudgetUsage()
        with self._exclusive(scope_id):
            current = self._require(scope_id)
            existing = next(
                (item for item in current.leases if item.lease_id == lease_id),
                None,
            )
            if existing is None:
                raise ValueError(f"unknown budget lease: {lease_id}")
            if existing.status == "settled":
                if (
                    existing.observed_actual == observed_actual
                    and existing.unknown_upper_bound == unknown
                ):
                    return existing
                raise ValueError("settled lease cannot be changed")
            if existing.status != "active":
                raise ValueError("released lease cannot be settled")
            ledger = LeaseBudgetLedger(current.reserved, leases=current.leases)
            settled = ledger.settle(
                lease_id,
                observed_actual,
                unknown_upper_bound=unknown,
            )
            self._write_next(current, ledger.leases)
            return settled

    def release(self, *, scope_id: str, lease_id: str) -> BudgetLease:
        with self._exclusive(scope_id):
            current = self._require(scope_id)
            existing = next(
                (item for item in current.leases if item.lease_id == lease_id),
                None,
            )
            if existing is None:
                raise ValueError(f"unknown budget lease: {lease_id}")
            if existing.status == "released":
                return existing
            if existing.status != "active":
                raise ValueError("settled lease cannot be released")
            ledger = LeaseBudgetLedger(current.reserved, leases=current.leases)
            released = ledger.release(lease_id)
            self._write_next(current, ledger.leases)
            return released

    def _write_next(
        self,
        current: ScopeBudgetSnapshot,
        leases: tuple[BudgetLease, ...],
    ) -> ScopeBudgetSnapshot:
        next_snapshot = current.model_copy(
            update={
                "revision": current.revision + 1,
                "leases": leases,
                "updated_at": datetime.now(UTC),
            }
        )
        self._write(next_snapshot)
        return next_snapshot

    def _require(self, scope_id: str) -> ScopeBudgetSnapshot:
        current = self._read(scope_id)
        if current is None:
            raise ValueError("scope budget is not initialized")
        return current

    def _path(self, scope_id: str, kind: str) -> Path:
        digest = hashlib.sha256(scope_id.encode("utf-8")).hexdigest()
        suffix = "lock" if kind == "locks" else "json"
        return self.root / kind / f"{digest}.{suffix}"

    def _read(self, scope_id: str) -> ScopeBudgetSnapshot | None:
        path = self._path(scope_id, "snapshots")
        try:
            raw = path.read_bytes()
        except FileNotFoundError:
            return None
        snapshot = ScopeBudgetSnapshot.model_validate_json(raw)
        if snapshot.scope_id != scope_id:
            raise ValueError("scope budget identity mismatch")
        return snapshot

    def _write(self, snapshot: ScopeBudgetSnapshot) -> None:
        snapshot = ScopeBudgetSnapshot.model_validate(snapshot.model_dump(mode="python"))
        destination = self._path(snapshot.scope_id, "snapshots")
        temporary = self.root / "tmp" / f"{uuid.uuid4().hex}.json"
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC,
            0o600,
        )
        try:
            with os.fdopen(descriptor, "wb", closefd=True) as stream:
                stream.write(snapshot.stable_json_bytes())
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, destination)
            directory_fd = os.open(destination.parent, os.O_RDONLY | os.O_CLOEXEC)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass

    def _exclusive(self, scope_id: str) -> _BudgetFileLock:
        return _BudgetFileLock(self._path(scope_id, "locks"))


class _BudgetFileLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.descriptor: int | None = None

    def __enter__(self) -> None:
        descriptor = os.open(
            self.path,
            os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        self.descriptor = descriptor

    def __exit__(self, *_args: object) -> None:
        assert self.descriptor is not None
        try:
            fcntl.flock(self.descriptor, fcntl.LOCK_UN)
        finally:
            os.close(self.descriptor)
            self.descriptor = None


def _add(left: int | float, right: int | float) -> int | float:
    value = Decimal(str(left)) + Decimal(str(right))
    if isinstance(left, int) and isinstance(right, int):
        return int(value)
    return float(value)


def _subtract(left: int | float, right: int | float) -> int | float:
    value = Decimal(str(left)) - Decimal(str(right))
    if isinstance(left, int) and isinstance(right, int):
        return max(0, int(value))
    return max(0.0, float(value))


def _without_wall(value: Budget | BudgetUsage) -> BudgetUsage:
    return BudgetUsage.model_validate(
        {field: 0 if field == "wall_seconds" else getattr(value, field) for field in _FIELDS}
    )


def _sum_usage(left: BudgetUsage, right: Budget | BudgetUsage) -> BudgetUsage:
    return BudgetUsage.model_validate(
        {field: _add(getattr(left, field), getattr(right, field)) for field in _FIELDS}
    )


def _exceeded_usage(
    usage: BudgetUsage,
    reserved: Budget,
    *,
    include_wall: bool,
) -> tuple[str, ...]:
    return tuple(
        field
        for field in _FIELDS
        if (include_wall or field != "wall_seconds")
        and Decimal(str(getattr(usage, field))) > Decimal(str(getattr(reserved, field)))
    )


def _bounded_elapsed(value: float, maximum: float) -> float:
    if value < 0:
        raise ValueError("elapsed_wall_seconds cannot be negative")
    return min(float(value), maximum)


__all__ = ["BudgetExceeded", "BudgetLedger", "LeaseBudgetLedger"]
