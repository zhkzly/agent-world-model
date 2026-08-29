from __future__ import annotations

from types import SimpleNamespace

import pytest

import agent_env_foundry.qualification_runner as runner_module
from agent_env_foundry.qualification_contracts import NativeVerificationResult
from agent_env_foundry.qualification_runner import QualificationBudget
from agent_env_foundry.semantics import AtomCheckResult


def test_qualification_budget_is_bounded_and_positive() -> None:
    budget = QualificationBudget(
        start_seed=7,
        start_limit=3,
        max_provider_turns=9,
    )
    assert budget.start_seed == 7
    assert budget.start_limit == 3
    assert budget.max_provider_turns == 9

    for field in ("start_limit", "max_provider_turns"):
        values = {
            "start_seed": 0,
            "start_limit": 1,
            "max_provider_turns": 1,
        }
        values[field] = 0
        with pytest.raises(ValueError, match=field):
            QualificationBudget(**values)


def _result(*, effects: bool = True, collateral: bool = True) -> AtomCheckResult:
    return AtomCheckResult(
        initially_satisfied=False,
        satisfied=effects and collateral,
        required_effects_ok=effects,
        collateral_ok=collateral,
        answer_ok=None,
        process_ok=effects,
        report_values={},
        failure_codes=() if effects and collateral else ("REJECTED",),
    )


def _native(*, effects: bool = True, collateral: bool = True) -> NativeVerificationResult:
    return NativeVerificationResult(
        initially_satisfied=False,
        satisfied=effects and collateral,
        required_effects_ok=effects,
        collateral_ok=collateral,
        answer_ok=None,
        process_ok=effects,
        report_values={},
        failure_codes=() if effects and collateral else ("INDEPENDENT_REJECTION",),
    )


def test_result_axis_mutants_are_killed_by_independent_physical_cases() -> None:
    capability = SimpleNamespace(capability_id="cap-1")
    no_op = SimpleNamespace(
        category="no_op",
        capability=capability,
        semantics_result=_result(effects=False),
        verifier_result=_native(effects=False),
    )
    collateral = SimpleNamespace(
        category="collateral",
        capability=capability,
        semantics_result=_result(collateral=False),
        verifier_result=_native(collateral=False),
    )

    records = runner_module._mutation_records((no_op, collateral))  # type: ignore[arg-type]

    assert tuple(item["target_role"] for item in records) == ("semantics", "verifier")
    assert all(item["killed"] is True for item in records)
    assert all(item["killed_by"] == "physical_axis_comparison" for item in records)


def test_task_kind_must_match_observed_semantic_state_change() -> None:
    unchanged = {"count": 1}
    changed = {"count": 2}
    query = SimpleNamespace(capability_id="query", task_kind="query")
    process = SimpleNamespace(capability_id="process", task_kind="process")
    state_change = SimpleNamespace(capability_id="state", task_kind="state_change")

    runner_module._validate_task_kind_transition(query, unchanged, unchanged)
    runner_module._validate_task_kind_transition(process, unchanged, unchanged)
    runner_module._validate_task_kind_transition(state_change, unchanged, changed)

    for capability, before, after in (
        (query, unchanged, changed),
        (process, unchanged, changed),
        (state_change, unchanged, unchanged),
    ):
        with pytest.raises(runner_module.QualificationV2Error) as caught:
            runner_module._validate_task_kind_transition(capability, before, after)
        assert caught.value.code == "qualification_task_kind_mismatch"
