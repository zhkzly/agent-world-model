from __future__ import annotations

import pytest

from agent_world.contracts import Budget, BudgetUsage
from agent_world.control import LeaseBudgetLedger
from agent_world.designer.budget import (
    DesignerBudgetExhausted,
    DesignerBudgetPlanError,
    DesignerInvocationBudget,
    derive_designer_invocation_budget,
)
from agent_world.invocation import (
    InvocationResult,
    InvocationStatus,
    InvocationUsage,
    TokenBreakdown,
)


def _result(*, invocation_id: str, tokens: int, usage_known: bool = True) -> InvocationResult:
    return InvocationResult(
        invocation_id=invocation_id,
        status=InvocationStatus.FAILED,
        session=None,
        turn_id=None,
        final_text=None,
        structured_output=None,
        usage=(InvocationUsage(turn=TokenBreakdown(total_tokens=tokens)) if usage_known else None),
        events=(),
        error=None,
        duration_ms=10,
    )


def test_designer_budget_uses_fixed_cap_and_charges_structured_correction() -> None:
    clock = [100.0]
    meter = DesignerInvocationBudget(
        Budget(llm_tokens=90, agent_turns=3, repair_attempts=1, wall_seconds=30),
        monotonic=lambda: clock[0],
    )

    assert meter.rollout_token_limit == 30
    meter.authorize_turn(correction=False)
    meter.record_result(_result(invocation_id="first", tokens=11))
    meter.authorize_turn(correction=True)
    meter.record_result(_result(invocation_id="correction", tokens=17))

    assert meter.usage == BudgetUsage(llm_tokens=28, agent_turns=2, repair_attempts=1)
    with pytest.raises(DesignerBudgetExhausted, match="repair"):
        meter.authorize_turn(correction=True)


def test_designer_budget_bounds_only_the_started_turn_when_backend_usage_is_missing() -> None:
    reserved = Budget(
        llm_tokens=120,
        agent_turns=4,
        repair_attempts=2,
        wall_seconds=60,
        monetary_cost=3.5,
    )
    meter = DesignerInvocationBudget(reserved)
    meter.authorize_turn(correction=False)
    meter.record_result(_result(invocation_id="unknown", tokens=0, usage_known=False))

    assert meter.observed_actual == BudgetUsage(agent_turns=1)
    assert meter.unknown_upper_bound == BudgetUsage(
        llm_tokens=30,
        monetary_cost=0.875,
    )
    usage = meter.usage
    assert usage == BudgetUsage(llm_tokens=30, agent_turns=1, monetary_cost=0.875)
    ledger = LeaseBudgetLedger(reserved)
    lease = ledger.reserve(
        lease_id="lease:designer",
        owner_id="designer:node",
        requested=reserved,
        elapsed_wall_seconds=0,
    )
    settled = ledger.settle(
        lease.lease_id,
        meter.observed_actual,
        unknown_upper_bound=meter.unknown_upper_bound,
    )
    assert settled.observed_actual == BudgetUsage(agent_turns=1)
    assert settled.unknown_upper_bound == BudgetUsage(
        llm_tokens=30,
        monetary_cost=0.875,
    )
    assert settled.conservative_committed == usage


def test_designer_budget_keeps_monetary_unknown_when_provider_tokens_are_known() -> None:
    meter = DesignerInvocationBudget(
        Budget(
            llm_tokens=120,
            agent_turns=4,
            wall_seconds=60,
            monetary_cost=3.5,
        )
    )
    meter.authorize_turn(correction=False)
    meter.record_result(_result(invocation_id="known", tokens=17))

    assert meter.observed_actual == BudgetUsage(llm_tokens=17, agent_turns=1)
    assert meter.unknown_upper_bound == BudgetUsage(monetary_cost=0.875)
    assert meter.usage == BudgetUsage(
        llm_tokens=17,
        agent_turns=1,
        monetary_cost=0.875,
    )


def test_designer_budget_tracks_multiple_bounded_turns_in_flight() -> None:
    meter = DesignerInvocationBudget(Budget(llm_tokens=120, agent_turns=4, wall_seconds=60))

    meter.authorize_turn(correction=False)
    meter.authorize_turn(correction=False)
    assert meter.remaining_turns == 2
    meter.record_result(_result(invocation_id="second", tokens=17))
    meter.record_result(_result(invocation_id="first", tokens=11))

    assert meter.usage == BudgetUsage(llm_tokens=28, agent_turns=2)


def test_designer_budget_refuses_turn_after_shared_wall_deadline() -> None:
    clock = [10.0]
    meter = DesignerInvocationBudget(
        Budget(llm_tokens=10, agent_turns=1, wall_seconds=5),
        monotonic=lambda: clock[0],
    )
    clock[0] = 15.1

    with pytest.raises(DesignerBudgetExhausted, match="wall-time"):
        meter.authorize_turn(correction=False)


def test_controller_derives_non_exchangeable_designer_budget_slice() -> None:
    remaining = Budget(
        llm_tokens=1_000,
        agent_turns=10,
        search_calls=5,
        tool_calls=20,
        build_seconds=300,
        evaluation_episodes=20,
        repair_attempts=3,
        wall_seconds=600,
        monetary_cost=10,
    )

    reserved = derive_designer_invocation_budget(
        remaining,
        base_turns=3,
        maximum_corrections=6,
    )

    assert reserved == Budget(
        llm_tokens=600,
        agent_turns=6,
        repair_attempts=3,
        wall_seconds=600,
        monetary_cost=6,
    )
    assert reserved.llm_tokens // reserved.agent_turns == 100


def test_designer_budget_plan_reports_exact_token_envelope_shortfall() -> None:
    with pytest.raises(DesignerBudgetPlanError) as captured:
        derive_designer_invocation_budget(
            Budget(llm_tokens=80_000, agent_turns=4, wall_seconds=900),
            base_turns=2,
            maximum_corrections=0,
            rollout_token_limit=65_536,
        )

    failure = captured.value
    assert failure.dimension == "llm_tokens"
    assert failure.reserved == 80_000
    assert failure.required == 131_072
    assert failure.base_turns == 2
    assert failure.rollout_token_limit == 65_536


def test_designer_budget_reserves_configured_semantic_turn_envelopes() -> None:
    remaining = Budget(
        llm_tokens=1_200_000,
        agent_turns=128,
        repair_attempts=3,
        wall_seconds=7_200,
    )

    reserved = derive_designer_invocation_budget(
        remaining,
        base_turns=3,
        maximum_corrections=6,
        rollout_token_limit=65_536,
    )

    assert reserved.agent_turns == 6
    assert reserved.repair_attempts == 3
    assert reserved.llm_tokens == 6 * 65_536
    assert DesignerInvocationBudget(reserved).rollout_token_limit == 65_536
