"""Vector budget accounting; dimensions are never silently exchanged."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from agent_world.contracts import Budget, BudgetUsage

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
            {
                field: _add(getattr(self._used, field), getattr(usage, field))
                for field in _FIELDS
            }
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
            if Decimal(str(getattr(requested, field)))
            > Decimal(str(getattr(available, field)))
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
        {
            field: 0 if field == "wall_seconds" else getattr(value, field)
            for field in _FIELDS
        }
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
