"""Hard, pre-authorized budget accounting for Designer Agent turns.

The Controller reserves a vector budget before entering a Designer work order.
This module turns that reservation into a fixed per-turn Codex rollout limit and
accounts every initial/correction turn.  It deliberately contains no backend or
test-double implementation.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Literal

from agent_world.contracts import Budget, BudgetUsage
from agent_world.invocation.contracts import InvocationResult


class DesignerBudgetExhausted(RuntimeError):
    """Raised before an invocation that has no remaining hard authorization."""


class DesignerBudgetPlanError(DesignerBudgetExhausted):
    """Structured preflight failure before a Designer work lease is admitted."""

    def __init__(
        self,
        *,
        dimension: Literal["agent_turns", "llm_tokens", "wall_seconds"],
        reserved: int | float,
        required: int | float,
        base_turns: int,
        rollout_token_limit: int | None,
    ) -> None:
        self.dimension = dimension
        self.reserved = reserved
        self.required = required
        self.base_turns = base_turns
        self.rollout_token_limit = rollout_token_limit
        super().__init__(f"Designer work requires {required} {dimension}; {reserved} is reserved")


class DesignerInvocationBudget:
    """Meter one pre-reserved Designer work order.

    A fixed rollout limit is used for every turn so a same-session correction
    keeps the exact same resolved profile.  Because ``turn_limit * turns`` never
    exceeds the reservation, the backend cannot spend unreserved LLM tokens even
    when every allowed correction is used.
    """

    def __init__(
        self,
        reserved: Budget,
        *,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if reserved.llm_tokens <= 0:
            raise DesignerBudgetExhausted("Designer work requires reserved LLM tokens")
        if reserved.agent_turns <= 0:
            raise DesignerBudgetExhausted("Designer work requires reserved Agent turns")
        if reserved.wall_seconds <= 0:
            raise DesignerBudgetExhausted("Designer work requires reserved wall time")
        self.reserved = reserved
        self._monotonic = monotonic
        self._started = monotonic()
        self._authorized_turns = 0
        self._authorized_reworks = 0
        self._results: list[InvocationResult] = []
        self._pending_turns = 0
        self._reported_over_budget = False

    @property
    def rollout_token_limit(self) -> int:
        """Return the fixed hard cap installed into every resolved profile."""

        return self.reserved.llm_tokens // self.reserved.agent_turns

    @property
    def remaining_turns(self) -> int:
        return self.reserved.agent_turns - self._authorized_turns

    @property
    def results(self) -> tuple[InvocationResult, ...]:
        return tuple(self._results)

    @property
    def remaining_wall_seconds(self) -> float:
        elapsed = max(0.0, self._monotonic() - self._started)
        return max(0.0, self.reserved.wall_seconds - elapsed)

    def authorize_turn(self, *, correction: bool) -> None:
        """Consume authorization immediately before crossing the backend boundary."""

        if self.rollout_token_limit <= 0:
            raise DesignerBudgetExhausted(
                "reserved LLM tokens cannot provide a positive per-turn rollout limit"
            )
        if self.remaining_turns <= 0:
            raise DesignerBudgetExhausted("Designer Agent-turn reservation is exhausted")
        if self.remaining_wall_seconds <= 0:
            raise DesignerBudgetExhausted("Designer wall-time reservation is exhausted")
        if correction and self._authorized_reworks >= self.reserved.repair_attempts:
            raise DesignerBudgetExhausted("Designer structured-repair reservation is exhausted")
        self._authorized_turns += 1
        if correction:
            self._authorized_reworks += 1
        self._pending_turns += 1

    def record_result(self, result: InvocationResult) -> None:
        """Bind auditable backend evidence to one authorized in-flight turn."""

        if self._pending_turns <= 0:
            raise RuntimeError("InvocationResult has no authorized Designer turn")
        self._results.append(result)
        self._pending_turns -= 1
        known_tokens = sum(
            max(0, item.usage.turn.total_tokens)
            for item in self._results
            if item.usage is not None and item.usage.turn is not None
        )
        if known_tokens > self.reserved.llm_tokens:
            self._reported_over_budget = True
            raise DesignerBudgetExhausted(
                "backend-reported Designer token usage exceeds the reserved work budget"
            )

    @property
    def observed_actual(self) -> BudgetUsage:
        """Return dimensions directly observed by the framework/provider."""

        tokens = sum(
            max(0, item.usage.turn.total_tokens)
            for item in self._results
            if item.usage is not None and item.usage.turn is not None
        )
        return BudgetUsage(
            llm_tokens=min(tokens, self.reserved.llm_tokens),
            agent_turns=self._authorized_turns,
            repair_attempts=self._authorized_reworks,
        )

    @property
    def unknown_upper_bound(self) -> BudgetUsage:
        """Bound unobserved token and monetary usage without inventing actuals.

        Token uncertainty applies only to started turns whose provider usage is
        missing.  Provider monetary actuals are unavailable for every Designer
        turn, so their conservative upper bound is proportional to all turns
        that crossed the backend boundary, regardless of token observability.
        """

        missing_results = sum(
            item.usage is None or item.usage.turn is None for item in self._results
        )
        unknown_turns = min(
            self._authorized_turns,
            missing_results + self._pending_turns,
        )
        if self._reported_over_budget:
            unknown_tokens = max(0, self.reserved.llm_tokens - self.observed_actual.llm_tokens)
        else:
            unknown_tokens = min(
                max(0, self.reserved.llm_tokens - self.observed_actual.llm_tokens),
                unknown_turns * self.rollout_token_limit,
            )
        return BudgetUsage(
            llm_tokens=unknown_tokens,
            monetary_cost=min(
                self.reserved.monetary_cost,
                self.reserved.monetary_cost
                * self._authorized_turns
                / self.reserved.agent_turns,
            ),
        )

    @property
    def usage(self) -> BudgetUsage:
        """Return the conservative commitment used for admission."""

        actual = self.observed_actual
        unknown = self.unknown_upper_bound
        return BudgetUsage.model_validate(
            {
                field: getattr(actual, field) + getattr(unknown, field)
                for field in Budget.model_fields
                if field != "schema_version"
            }
        )


def derive_designer_invocation_budget(
    remaining: Budget,
    *,
    base_turns: int,
    maximum_corrections: int,
    rollout_token_limit: int | None = None,
) -> Budget:
    """Partition a semantic work lease without borrowing unrelated dimensions."""

    if base_turns <= 0 or maximum_corrections < 0:
        raise ValueError("Designer work shape must contain positive base turns")
    if rollout_token_limit is not None and rollout_token_limit <= 0:
        raise ValueError("rollout_token_limit must be positive when configured")
    if remaining.agent_turns < base_turns:
        raise DesignerBudgetPlanError(
            dimension="agent_turns",
            reserved=remaining.agent_turns,
            required=base_turns,
            base_turns=base_turns,
            rollout_token_limit=rollout_token_limit,
        )
    if remaining.wall_seconds <= 0:
        raise DesignerBudgetPlanError(
            dimension="wall_seconds",
            reserved=remaining.wall_seconds,
            required=1,
            base_turns=base_turns,
            rollout_token_limit=rollout_token_limit,
        )
    minimum_tokens = base_turns if rollout_token_limit is None else base_turns * rollout_token_limit
    if remaining.llm_tokens < minimum_tokens:
        raise DesignerBudgetPlanError(
            dimension="llm_tokens",
            reserved=remaining.llm_tokens,
            required=minimum_tokens,
            base_turns=base_turns,
            rollout_token_limit=rollout_token_limit,
        )
    token_turn_capacity = (
        remaining.agent_turns
        if rollout_token_limit is None
        else remaining.llm_tokens // rollout_token_limit
    )
    correction_turns = min(
        maximum_corrections,
        remaining.repair_attempts,
        max(0, remaining.agent_turns - base_turns),
        max(0, token_turn_capacity - base_turns),
    )
    turns = base_turns + correction_turns
    if remaining.llm_tokens < turns:
        raise DesignerBudgetPlanError(
            dimension="llm_tokens",
            reserved=remaining.llm_tokens,
            required=turns,
            base_turns=base_turns,
            rollout_token_limit=rollout_token_limit,
        )
    tokens = (
        rollout_token_limit * turns
        if rollout_token_limit is not None
        else max(
            turns,
            remaining.llm_tokens * turns // max(1, remaining.agent_turns),
        )
    )
    monetary = remaining.monetary_cost * turns / max(1, remaining.agent_turns)
    return Budget(
        llm_tokens=tokens,
        agent_turns=turns,
        repair_attempts=correction_turns,
        wall_seconds=remaining.wall_seconds,
        monetary_cost=monetary,
    )


__all__ = [
    "DesignerBudgetExhausted",
    "DesignerBudgetPlanError",
    "DesignerInvocationBudget",
    "derive_designer_invocation_budget",
]
