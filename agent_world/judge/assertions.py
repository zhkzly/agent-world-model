"""Bind Challenger obligations to the framework-owned executable Rule IR."""

from __future__ import annotations

from agent_world.contracts import Rule, VerifierAssertion

from .models import AssertionCheck
from .rules import RuleEvaluationError, RuleExecutionContext, evaluate_rule


def evaluate_assertion(
    assertion: VerifierAssertion,
    rule: Rule,
    contexts: tuple[RuleExecutionContext, ...],
) -> AssertionCheck:
    """Evaluate the referenced Rule itself; labels cannot manufacture coverage."""

    if assertion.rule_id != rule.rule_id:
        return AssertionCheck(
            assertion_id=assertion.assertion_id,
            rule_id=assertion.rule_id,
            passed=False,
            expected=assertion.expected,
            summary="assertion is not bound to the supplied Rule",
        )
    if assertion.action_index >= len(contexts):
        return AssertionCheck(
            assertion_id=assertion.assertion_id,
            rule_id=assertion.rule_id,
            passed=False,
            expected=assertion.expected,
            summary="assertion references an unavailable action context",
        )
    try:
        observed = evaluate_rule(rule, contexts[assertion.action_index]).result
    except RuleEvaluationError as exc:
        return AssertionCheck(
            assertion_id=assertion.assertion_id,
            rule_id=assertion.rule_id,
            passed=False,
            expected=assertion.expected,
            summary=f"Rule evaluation failed closed: {exc}",
        )
    return AssertionCheck(
        assertion_id=assertion.assertion_id,
        rule_id=assertion.rule_id,
        passed=observed is assertion.expected,
        expected=assertion.expected,
        observed=observed,
        summary="typed Rule result matches obligation"
        if observed is assertion.expected
        else "typed Rule result differs from obligation",
    )


__all__ = ["evaluate_assertion"]
