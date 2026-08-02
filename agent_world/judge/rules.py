"""Safe framework interpreter for the closed WorldSpec Rule IR."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker  # type: ignore[import-untyped]

from agent_world.contracts import (
    CurriculumRequirements,
    EnvironmentDesign,
    RewardSpec,
    Rule,
    RuleArithmetic,
    RuleConstant,
    RuleLookupByKey,
    RuleTerm,
    RuleValueRef,
    WorldSpec,
    canonical_json_bytes,
)

_MISSING = object()
_MAX_RUNTIME_CONTAINER_ITEMS = 10_000
_MAX_INTEGER_BITS = 4096
_FORMAT_CHECKER = FormatChecker()
_RESET_UNAVAILABLE_RULE_SOURCES = frozenset(
    {"args", "tool_result", "error", "events", "terminated", "truncated"}
)


class RuleEvaluationError(ValueError):
    """A Rule cannot be safely evaluated against the observed execution context."""


@dataclass(frozen=True, slots=True)
class RuleExecutionContext:
    actor: str
    pre_state: Any
    post_state: Any
    args: Any
    tool_result: Any
    error: Any
    observation: Any
    events: Any
    reset_config: Any
    task_goal: Any
    seed: int | str
    terminated: bool
    truncated: bool


@dataclass(frozen=True, slots=True)
class RuleEvaluation:
    rule_id: str
    result: bool
    clause_results: tuple[bool, ...]


@dataclass(frozen=True, slots=True)
class RewardEvaluation:
    reward: float
    terminated: bool
    succeeded: bool
    failed: bool
    rule_results: Mapping[str, bool]


def design_rule_index(design: EnvironmentDesign) -> dict[str, Rule]:
    """Return every executable rule, rejecting duplicate identities fail-closed."""

    return contract_rule_index(design.world_spec, design.curriculum)


def contract_rule_index(
    world_spec: WorldSpec,
    curriculum: CurriculumRequirements,
) -> dict[str, Rule]:
    """Index the portable Rule contracts shipped in a released envpkg."""

    rules: dict[str, Rule] = {}

    def add(rule: Rule) -> None:
        if rule.rule_id in rules:
            raise RuleEvaluationError(f"duplicate Rule id: {rule.rule_id}")
        rules[rule.rule_id] = rule

    for rule in world_spec.invariants:
        add(rule)
    for rule in world_spec.state.initial_state_constraints:
        add(rule)
    for tool in world_spec.tools:
        semantics = tool.semantics
        for rule in (*semantics.preconditions, *semantics.transition, *semantics.postconditions):
            add(rule)
        for error in semantics.errors:
            add(error.when)
        if semantics.permission.condition is not None:
            add(semantics.permission.condition)
    for task in curriculum.task_types:
        for rule in (
            *task.initial_state_constraints,
            *task.success_conditions,
            *task.failure_conditions,
            *task.terminal_conditions,
        ):
            add(rule)
    for rule in curriculum.sampling_constraints:
        add(rule)
    if len(rules) > 1024:
        raise RuleEvaluationError("design exceeds the 1024 Rule evaluation limit")
    return rules


def evaluate_rule(rule: Rule, context: RuleExecutionContext) -> RuleEvaluation:
    """Execute one finite Rule without eval, imports, callbacks, or candidate code."""

    clause_results = tuple(_evaluate_clause(clause, context) for clause in rule.clauses)
    result = all(clause_results) if rule.boolean_operator == "all" else any(clause_results)
    return RuleEvaluation(rule.rule_id, result, clause_results)


def rule_value_sources(rule: Rule) -> frozenset[str]:
    """Return the execution-context roots read by one closed Rule."""

    sources: set[str] = set()

    def visit(term: RuleTerm) -> None:
        if isinstance(term, RuleValueRef):
            sources.add(term.source)
        elif isinstance(term, RuleLookupByKey):
            sources.add(term.source)
            visit(term.key)
        elif isinstance(term, RuleArithmetic):
            visit(term.left)
            visit(term.right)

    for clause in rule.clauses:
        visit(clause.left)
        if clause.right is not None:
            visit(clause.right)
    return frozenset(sources)


def initially_evaluable_rules(rules: Iterable[Rule]) -> tuple[Rule, ...]:
    """Keep only Rules whose declared inputs exist at Runtime reset.

    Action-scoped roots intentionally contain no meaningful value during reset. Callers
    must not fabricate an empty action merely to evaluate them: World invariants remain
    mandatory in ``validate_tool_execution`` after every real action, while task and
    sampling rules are evaluated only by a boundary that has their declared inputs.
    """

    return tuple(
        rule
        for rule in rules
        if not (rule_value_sources(rule) & _RESET_UNAVAILABLE_RULE_SOURCES)
    )


def initially_evaluable_invariants(invariants: tuple[Rule, ...]) -> tuple[Rule, ...]:
    """Backward-compatible invariant-specific name for reset routing."""

    return initially_evaluable_rules(invariants)


def evaluate_task_reward(
    design: EnvironmentDesign,
    task_type: str,
    context: RuleExecutionContext,
) -> RewardEvaluation:
    """Recompute reward for exactly one task type without cross-task leakage."""

    return evaluate_task_reward_contract(
        design.world_spec,
        design.curriculum,
        design.reward,
        task_type,
        context,
    )


def evaluate_task_reward_contract(
    world_spec: WorldSpec,
    curriculum: CurriculumRequirements,
    reward_spec: RewardSpec,
    task_type: str,
    context: RuleExecutionContext,
) -> RewardEvaluation:
    """Evaluate one task from only the data physically shipped in envpkg v3."""

    requirement = next(
        (item for item in curriculum.task_types if item.task_type == task_type),
        None,
    )
    if requirement is None:
        raise RuleEvaluationError(f"unknown task type: {task_type}")
    rules = contract_rule_index(world_spec, curriculum)
    active_task_ids = {
        *[item.rule_id for item in requirement.success_conditions],
        *[item.rule_id for item in requirement.failure_conditions],
        *[item.rule_id for item in requirement.terminal_conditions],
    }
    spec = reward_spec
    terminal_ids = tuple(item for item in spec.terminal_rule_ids if item in active_task_ids)
    success_ids = tuple(item for item in spec.success_rule_ids if item in active_task_ids)
    failure_ids = tuple(item for item in spec.failure_rule_ids if item in active_task_ids)
    needed = set(terminal_ids) | set(success_ids) | set(failure_ids)
    results = {rule_id: evaluate_rule(rules[rule_id], context).result for rule_id in needed}
    matched_success = any(results[item] for item in success_ids)
    matched_failure = any(results[item] for item in failure_ids)
    failed = matched_failure
    succeeded = matched_success and not failed
    reward = (
        spec.failure_reward if failed else spec.success_reward if succeeded else spec.default_reward
    )
    return RewardEvaluation(
        reward=reward,
        terminated=any(results[item] for item in terminal_ids),
        succeeded=succeeded,
        failed=failed,
        rule_results=results,
    )


def _evaluate_clause(clause: Any, context: RuleExecutionContext) -> bool:
    left = _resolve_term(clause.left, context)
    operator = clause.operator
    if operator == "exists":
        result = left is not _MISSING
    elif operator == "not_exists":
        result = left is _MISSING
    else:
        if left is _MISSING:
            raise RuleEvaluationError(f"clause {clause.clause_id} left value is absent")
        if operator == "schema_valid":
            assert clause.json_schema is not None
            result = not tuple(Draft202012Validator(clause.json_schema).iter_errors(left))
        else:
            assert clause.right is not None
            right = _resolve_term(clause.right, context)
            if right is _MISSING:
                raise RuleEvaluationError(f"clause {clause.clause_id} right value is absent")
            result = _compare(operator, left, right, ordering=clause.ordering)
    return not result if clause.negate else result


def _resolve_term(term: RuleTerm, context: RuleExecutionContext) -> Any:
    if isinstance(term, RuleConstant):
        return term.value
    if isinstance(term, RuleValueRef):
        root = getattr(context, term.source)
        value = _resolve_pointer(root, term.pointer)
        if value is not _MISSING:
            _require_declared_type(value, term.value_type)
        return value
    if isinstance(term, RuleLookupByKey):
        root = getattr(context, term.source)
        collection = _resolve_pointer(root, term.collection_pointer)
        if collection is _MISSING:
            return _MISSING
        if not isinstance(collection, list):
            raise RuleEvaluationError("lookup_by_key collection is not an array")
        if len(collection) > _MAX_RUNTIME_CONTAINER_ITEMS:
            raise RuleEvaluationError("lookup_by_key collection exceeds framework limits")
        key = _resolve_term(term.key, context)
        if key is _MISSING:
            raise RuleEvaluationError("lookup_by_key key is absent")
        matches = [
            item
            for item in collection
            if isinstance(item, Mapping)
            and term.key_field in item
            and _canonical_equal(item[term.key_field], key)
        ]
        if not matches:
            return _MISSING
        if len(matches) != 1:
            raise RuleEvaluationError("lookup_by_key matched more than one state record")
        value = _resolve_pointer(matches[0], term.value_pointer)
        if value is not _MISSING:
            _require_declared_type(value, term.value_type)
        return value
    if not isinstance(term, RuleArithmetic):
        raise RuleEvaluationError("unsupported Rule term")
    left = _resolve_term(term.left, context)
    right = _resolve_term(term.right, context)
    if left is _MISSING or right is _MISSING:
        raise RuleEvaluationError("arithmetic operand is absent")
    left_number = _number(left)
    right_number = _number(right)
    try:
        if term.operator == "add":
            result = left_number + right_number
        elif term.operator == "subtract":
            result = left_number - right_number
        elif term.operator == "multiply":
            result = left_number * right_number
        elif term.operator == "divide":
            if right_number == 0:
                raise RuleEvaluationError("division by zero")
            result = left_number / right_number
        else:
            if right_number == 0:
                raise RuleEvaluationError("modulo by zero")
            result = left_number % right_number
    except OverflowError as exc:
        raise RuleEvaluationError("arithmetic result exceeds framework limits") from exc
    if isinstance(result, float) and not math.isfinite(result):
        raise RuleEvaluationError("arithmetic result is non-finite")
    if isinstance(result, int) and result.bit_length() > _MAX_INTEGER_BITS:
        raise RuleEvaluationError("arithmetic integer exceeds framework limits")
    return result


def _resolve_pointer(value: Any, pointer: str) -> Any:
    if pointer == "":
        return value
    current = value
    for raw_token in pointer.removeprefix("/").split("/"):
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, Mapping):
            if len(current) > _MAX_RUNTIME_CONTAINER_ITEMS or token not in current:
                return _MISSING
            current = current[token]
        elif isinstance(current, list):
            if len(current) > _MAX_RUNTIME_CONTAINER_ITEMS or not token.isdecimal():
                return _MISSING
            index = int(token)
            if index >= len(current):
                return _MISSING
            current = current[index]
        else:
            return _MISSING
    return current


def _compare(
    operator: str,
    left: Any,
    right: Any,
    *,
    ordering: str | None,
) -> bool:
    if operator == "equal":
        if _both_numbers(left, right):
            return _number(left) == _number(right)
        return _canonical_equal(left, right)
    if operator == "not_equal":
        if _both_numbers(left, right):
            return _number(left) != _number(right)
        return not _canonical_equal(left, right)
    if operator == "greater_than":
        left_ordered, right_ordered = _ordered_pair(left, right, ordering)
        return left_ordered > right_ordered
    if operator == "greater_or_equal":
        left_ordered, right_ordered = _ordered_pair(left, right, ordering)
        return left_ordered >= right_ordered
    if operator == "less_than":
        left_ordered, right_ordered = _ordered_pair(left, right, ordering)
        return left_ordered < right_ordered
    if operator == "less_or_equal":
        left_ordered, right_ordered = _ordered_pair(left, right, ordering)
        return left_ordered <= right_ordered
    if operator in {"contains", "not_contains"}:
        contained = _contains(left, right)
        return not contained if operator == "not_contains" else contained
    raise RuleEvaluationError(f"unsupported Rule comparison: {operator}")


def _ordered_pair(
    left: Any,
    right: Any,
    ordering: str | None,
) -> tuple[Any, Any]:
    if ordering == "number":
        return _number(left), _number(right)
    if ordering not in {"date", "date-time"}:
        raise RuleEvaluationError("ordered Rule comparison has no supported ordering")
    if not isinstance(left, str) or not isinstance(right, str):
        raise RuleEvaluationError("temporal Rule comparison received a non-string")
    if len(left) > 128 or len(right) > 128:
        raise RuleEvaluationError("temporal Rule value exceeds framework limits")
    if not _FORMAT_CHECKER.conforms(left, ordering) or not _FORMAT_CHECKER.conforms(
        right,
        ordering,
    ):
        raise RuleEvaluationError(f"temporal Rule comparison received an invalid {ordering} value")
    try:
        if ordering == "date":
            return date.fromisoformat(left), date.fromisoformat(right)
        left_datetime = datetime.fromisoformat(left.replace("Z", "+00:00"))
        right_datetime = datetime.fromisoformat(right.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RuleEvaluationError(
            f"temporal Rule comparison received an invalid {ordering} value"
        ) from exc
    if left_datetime.utcoffset() is None or right_datetime.utcoffset() is None:
        raise RuleEvaluationError("date-time Rule comparison requires explicit UTC offsets")
    return left_datetime, right_datetime


def _contains(container: Any, value: Any) -> bool:
    if isinstance(container, str):
        return isinstance(value, str) and value in container
    if isinstance(container, list):
        return any(_canonical_equal(item, value) for item in container)
    if isinstance(container, Mapping):
        if isinstance(value, str):
            return value in container
        if isinstance(value, Mapping):
            return all(
                key in container and _canonical_equal(container[key], item)
                for key, item in value.items()
            )
    return False


def _canonical_equal(left: Any, right: Any) -> bool:
    try:
        return canonical_json_bytes(left) == canonical_json_bytes(right)
    except (TypeError, ValueError):
        return False


def _number(value: Any) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RuleEvaluationError("numeric Rule operation received a non-number")
    if isinstance(value, int):
        if value.bit_length() > _MAX_INTEGER_BITS:
            raise RuleEvaluationError("numeric Rule integer exceeds framework limits")
        return value
    if not math.isfinite(value):
        raise RuleEvaluationError("numeric Rule operation received a non-finite number")
    return value


def _both_numbers(left: Any, right: Any) -> bool:
    return (
        not isinstance(left, bool)
        and not isinstance(right, bool)
        and isinstance(left, (int, float))
        and isinstance(right, (int, float))
    )


def _require_declared_type(value: Any, expected: str) -> None:
    if expected == "any":
        return
    if value is None:
        actual = "null"
    elif isinstance(value, bool):
        actual = "boolean"
    elif isinstance(value, (int, float)):
        actual = "number"
    elif isinstance(value, str):
        actual = "string"
    elif isinstance(value, list):
        actual = "array"
    elif isinstance(value, Mapping):
        actual = "object"
    else:
        raise RuleEvaluationError("Rule reference resolved to a non-JSON value")
    if actual != expected:
        raise RuleEvaluationError(f"Rule reference expected {expected}, observed {actual}")


__all__ = [
    "RewardEvaluation",
    "RuleEvaluation",
    "RuleEvaluationError",
    "RuleExecutionContext",
    "contract_rule_index",
    "design_rule_index",
    "evaluate_task_reward",
    "evaluate_task_reward_contract",
    "evaluate_rule",
    "initially_evaluable_rules",
    "initially_evaluable_invariants",
    "rule_value_sources",
]
