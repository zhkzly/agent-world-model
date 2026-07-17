from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent_world.contracts import (
    Rule,
    RuleArithmetic,
    RuleClause,
    RuleConstant,
    RuleValueRef,
    VerifierAssertion,
)
from agent_world.judge.assertions import evaluate_assertion
from agent_world.judge.rules import RuleEvaluationError, RuleExecutionContext, evaluate_rule


def _context(*, before: int = 2, after: int = 5) -> RuleExecutionContext:
    return RuleExecutionContext(
        actor="user",
        pre_state={"counter": {"value": before}},
        post_state={"counter": {"value": after}},
        args={"amount": after - before},
        tool_result={"value": after},
        error=None,
        observation={"counter": {"value": after}},
        events=[{"event_type": "counter.incremented"}],
        reset_config={"initial": before},
        task_goal={"target": after},
        seed=41,
        terminated=False,
        truncated=False,
    )


def _reference(source: str, pointer: str, value_type: str) -> RuleValueRef:
    return RuleValueRef(
        source=source,  # type: ignore[arg-type]
        pointer=pointer,
        value_type=value_type,  # type: ignore[arg-type]
    )


def _number(value: int) -> RuleConstant:
    return RuleConstant(value_type="number", value=value)


def test_closed_rule_interpreter_executes_refs_arithmetic_comparison_and_boolean() -> None:
    rule = Rule(
        rule_id="rule:counter-transition",
        family="transition",
        description="Post-state equals pre-state plus the requested amount.",
        boolean_operator="all",
        case_sensitivity="positive_and_negative",
        clauses=(
            RuleClause(
                clause_id="clause:arithmetic",
                left=_reference("post_state", "/counter/value", "number"),
                operator="equal",
                right=RuleArithmetic(
                    operator="add",
                    left=_reference("pre_state", "/counter/value", "number"),
                    right=_reference("args", "/amount", "number"),
                ),
            ),
            RuleClause(
                clause_id="clause:event",
                left=_reference("events", "", "array"),
                operator="contains",
                right=RuleConstant(
                    value_type="object",
                    value={"event_type": "counter.incremented"},
                ),
            ),
        ),
    )

    evaluation = evaluate_rule(rule, _context())

    assert evaluation.result
    assert evaluation.clause_results == (True, True)


def test_numeric_comparison_preserves_uint64_integer_precision() -> None:
    rule = Rule(
        rule_id="rule:uint64-precision",
        family="postcondition",
        description="Adjacent integers above IEEE-754 precision remain distinct.",
        boolean_operator="all",
        case_sensitivity="positive_and_negative",
        clauses=(
            RuleClause(
                clause_id="clause:uint64-precision",
                left=RuleConstant(value_type="number", value=2**53),
                operator="not_equal",
                right=RuleConstant(value_type="number", value=2**53 + 1),
            ),
        ),
    )

    assert evaluate_rule(rule, _context()).result


def test_rule_reference_type_or_missing_value_fails_closed() -> None:
    wrong_type = Rule(
        rule_id="rule:typed",
        family="postcondition",
        description="Counter is typed numeric.",
        boolean_operator="all",
        case_sensitivity="positive_only",
        clauses=(
            RuleClause(
                clause_id="clause:typed",
                left=_reference("post_state", "/counter/value", "string"),
                operator="equal",
                right=RuleConstant(value_type="string", value="5"),
            ),
        ),
    )
    missing = wrong_type.model_copy(
        update={
            "clauses": (
                RuleClause(
                    clause_id="clause:missing",
                    left=_reference("post_state", "/counter/missing", "number"),
                    operator="equal",
                    right=_number(5),
                ),
            )
        }
    )

    with pytest.raises(RuleEvaluationError, match="expected string"):
        evaluate_rule(wrong_type, _context())
    with pytest.raises(RuleEvaluationError, match="left value is absent"):
        evaluate_rule(missing, _context())


def test_verifier_assertion_can_only_obligate_the_real_rule() -> None:
    rule = Rule(
        rule_id="rule:result",
        family="postcondition",
        description="Tool result reports the new counter value.",
        boolean_operator="all",
        case_sensitivity="positive_only",
        clauses=(
            RuleClause(
                clause_id="clause:result",
                left=_reference("tool_result", "/value", "number"),
                operator="equal",
                right=_number(5),
            ),
        ),
    )
    assertion = VerifierAssertion(
        assertion_id="assertion:result",
        rule_id=rule.rule_id,
        action_index=0,
        expected=True,
    )

    check = evaluate_assertion(assertion, rule, (_context(),))

    assert check.passed
    assert check.rule_id == rule.rule_id
    assert check.observed is True


def test_weak_exists_assertion_shape_is_not_expressible() -> None:
    with pytest.raises(ValidationError):
        VerifierAssertion.model_validate(
            {
                "assertion_id": "assertion:weak",
                "source": "result",
                "json_pointer": "/anything",
                "operator": "exists",
                "rule_ids": ["rule:arbitrary"],
                "action_index": 0,
            }
        )
