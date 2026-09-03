"""Compact, domain-free Goal truth and evaluation for S2 Tasks."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from typing import Any, Literal, Self, cast

from agent_env_foundry.environment import JSONObject, JSONValue
from agent_env_foundry.jsonvalue import is_json_object, is_json_value
from agent_env_foundry.release import canonical_bytes, sha256_hex
from agent_env_foundry.schema import (
    SchemaError,
    require_object_root,
    validate_instance,
    validate_schema_document,
)

GOAL_TRUTH_FORMAT = "goal-truth/1"
OutcomeClass = Literal["query", "transition", "refusal"]
ScalarOperator = Literal["eq", "neq", "lt", "lte", "gt", "gte"]
_OUTCOMES = frozenset({"query", "transition", "refusal"})
_OPERATORS = frozenset({"eq", "neq", "lt", "lte", "gt", "gte"})
_OBSERVATION_KEYS = frozenset({"ok", "data", "error"})
_CHECKED = ("reset", "before_state", "after_state", "answer_schema", "answer", "goal")


@dataclass(frozen=True, slots=True)
class TraceEvent:
    seq: int
    tool_name: str
    arguments: JSONObject
    observation: JSONObject

    def __post_init__(self) -> None:
        if not isinstance(self.seq, int) or isinstance(self.seq, bool) or self.seq <= 0:
            raise ValueError("trace seq must be a positive integer")
        _text(self.tool_name, "trace tool_name")
        if not is_json_object(self.arguments):
            raise ValueError("trace arguments must be a JSON object")
        _validate_observation(self.observation)
        object.__setattr__(self, "arguments", _copy_object(self.arguments))
        object.__setattr__(self, "observation", _copy_object(self.observation))

    def to_document(self) -> JSONObject:
        return {
            "seq": self.seq,
            "tool_name": self.tool_name,
            "arguments": _copy_object(self.arguments),
            "observation": _copy_object(self.observation),
        }


@dataclass(frozen=True, slots=True)
class AtomGoal:
    tool_name: str
    arguments: JSONObject
    outcome: OutcomeClass
    error_code: str | None = None

    def __post_init__(self) -> None:
        _text(self.tool_name, "Atom tool_name")
        if not is_json_object(self.arguments):
            raise ValueError("Atom arguments must be a JSON object")
        if self.outcome not in _OUTCOMES:
            raise ValueError("Atom outcome must be query, transition, or refusal")
        if self.outcome == "refusal":
            _text(self.error_code, "refusal error_code")
            if cast(str, self.error_code).startswith("contract."):
                raise ValueError("contract errors cannot be business refusal Goals")
        elif self.error_code is not None:
            raise ValueError("successful Atom cannot have an error_code")
        object.__setattr__(self, "arguments", _copy_object(self.arguments))

    def to_document(self) -> JSONObject:
        return {
            "kind": "atom",
            "tool_name": self.tool_name,
            "arguments": _copy_object(self.arguments),
            "outcome": self.outcome,
            "error_code": self.error_code,
        }


@dataclass(frozen=True, slots=True)
class AllGoal:
    children: tuple[Goal, ...]

    def __post_init__(self) -> None:
        if len(self.children) < 2 or any(not _is_goal(child) for child in self.children):
            raise ValueError("AllGoal requires at least two Goal children")
        identities = [_digest(child.to_document()) for child in self.children]
        if len(identities) != len(set(identities)):
            raise ValueError("AllGoal children must be structurally unique")

    def to_document(self) -> JSONObject:
        return {"kind": "all", "children": [child.to_document() for child in self.children]}


@dataclass(frozen=True, slots=True)
class GoalValueSource:
    kind: Literal["reset", "observation"]
    pointer: str
    tool_name: str | None = None
    arguments: JSONObject | None = None

    def __post_init__(self) -> None:
        _pointer(self.pointer, "Goal source pointer")
        if self.kind == "reset":
            if self.tool_name is not None or self.arguments is not None:
                raise ValueError("reset Goal source cannot name a tool")
        elif self.kind == "observation":
            _text(self.tool_name, "Goal source tool_name")
            if not is_json_object(self.arguments):
                raise ValueError("observation Goal source requires arguments")
            object.__setattr__(self, "arguments", _copy_object(cast(JSONObject, self.arguments)))
        else:
            raise ValueError("unsupported Goal source kind")

    @classmethod
    def reset(cls, pointer: str) -> Self:
        return cls("reset", pointer)

    @classmethod
    def observation(cls, tool_name: str, arguments: JSONObject, pointer: str) -> Self:
        return cls("observation", pointer, tool_name, arguments)

    def to_document(self) -> JSONObject:
        if self.kind == "reset":
            return {"kind": self.kind, "pointer": self.pointer}
        return {
            "kind": self.kind,
            "tool_name": cast(str, self.tool_name),
            "arguments": _copy_object(cast(JSONObject, self.arguments)),
            "pointer": self.pointer,
        }


@dataclass(frozen=True, slots=True)
class ScalarCondition:
    source: GoalValueSource
    operator: ScalarOperator
    value: JSONValue

    def __post_init__(self) -> None:
        if not isinstance(self.source, GoalValueSource) or self.operator not in _OPERATORS:
            raise ValueError("condition requires a public source and supported operator")
        if isinstance(self.value, (dict, list)) or not is_json_value(self.value):
            raise ValueError("condition comparison value must be a JSON scalar")
        object.__setattr__(self, "value", _copy_json(self.value))

    def to_document(self) -> JSONObject:
        return {
            "source": self.source.to_document(),
            "operator": self.operator,
            "value": _copy_json(self.value),
        }


@dataclass(frozen=True, slots=True)
class IfGoal:
    condition: ScalarCondition
    then_goal: Goal | None
    else_goal: Goal | None

    def __post_init__(self) -> None:
        if not isinstance(self.condition, ScalarCondition):
            raise ValueError("IfGoal requires a ScalarCondition")
        branches = (self.then_goal, self.else_goal)
        if all(branch is None for branch in branches):
            raise ValueError("IfGoal requires at least one branch")
        if any(branch is not None and not _is_goal(branch) for branch in branches):
            raise ValueError("IfGoal branches must be Goals or null")

    def to_document(self) -> JSONObject:
        return {
            "kind": "if",
            "condition": self.condition.to_document(),
            "then_goal": self.then_goal.to_document() if self.then_goal else None,
            "else_goal": self.else_goal.to_document() if self.else_goal else None,
        }


@dataclass(frozen=True, slots=True)
class ForEachGoal:
    members_source: GoalValueSource
    member_key_pointer: str
    member_argument_pointer: str
    children: tuple[AtomGoal, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.members_source, GoalValueSource):
            raise ValueError("ForEachGoal requires a public members source")
        _pointer(self.member_key_pointer, "ForEach member key pointer")
        _pointer(self.member_argument_pointer, "ForEach member argument pointer")
        if len(self.children) < 2 or any(
            not isinstance(child, AtomGoal) for child in self.children
        ):
            raise ValueError("ForEachGoal requires at least two Atom children")
        if len({child.tool_name for child in self.children}) != 1:
            raise ValueError("ForEachGoal children must use one body tool")

    def to_document(self) -> JSONObject:
        return {
            "kind": "foreach",
            "members_source": self.members_source.to_document(),
            "member_key_pointer": self.member_key_pointer,
            "member_argument_pointer": self.member_argument_pointer,
            "children": [child.to_document() for child in self.children],
        }


type Goal = AtomGoal | AllGoal | IfGoal | ForEachGoal


@dataclass(frozen=True, slots=True)
class GoalTruth:
    goal: Goal
    expected_reset: JSONValue
    expected_before: JSONValue
    expected_after: JSONValue
    expected_answer: JSONObject
    final_answer_schema: JSONObject

    def __post_init__(self) -> None:
        if not _is_goal(self.goal):
            raise ValueError("GoalTruth goal must be a Goal")
        for value, role in (
            (self.expected_reset, "expected_reset"),
            (self.expected_before, "expected_before"),
            (self.expected_after, "expected_after"),
        ):
            if not is_json_value(value):
                raise ValueError(f"{role} must be a JSON value")
        if not is_json_object(self.expected_answer):
            raise ValueError("expected_answer must be a JSON object")
        schema = _answer_schema(self.final_answer_schema)
        try:
            validate_instance(self.expected_answer, schema, role="GoalTruth expected_answer")
        except SchemaError as exc:
            raise ValueError(str(exc)) from exc
        changed = not _same(self.expected_before, self.expected_after)
        transition = _transition_requirement(self.goal)
        if transition is True and not changed:
            raise ValueError("transition Goal requires a state change")
        if transition is False and changed:
            raise ValueError("query/refusal Goal requires unchanged state")
        for name in ("expected_reset", "expected_before", "expected_after"):
            object.__setattr__(self, name, _copy_json(cast(JSONValue, getattr(self, name))))
        object.__setattr__(self, "expected_answer", _copy_object(self.expected_answer))
        object.__setattr__(self, "final_answer_schema", schema)

    @property
    def truth_id(self) -> str:
        return _digest(self.to_document())

    def to_document(self) -> JSONObject:
        return {
            "format": GOAL_TRUTH_FORMAT,
            "goal": self.goal.to_document(),
            "expected_reset": _copy_json(self.expected_reset),
            "expected_before": _copy_json(self.expected_before),
            "expected_after": _copy_json(self.expected_after),
            "expected_answer": _copy_object(self.expected_answer),
            "final_answer_schema": _copy_object(self.final_answer_schema),
        }


@dataclass(frozen=True, slots=True)
class EvaluationContext:
    reset_observation: JSONValue
    before_state: JSONValue
    after_state: JSONValue
    trace: tuple[TraceEvent, ...]
    final_answer: JSONObject

    def __post_init__(self) -> None:
        for value, role in (
            (self.reset_observation, "reset_observation"),
            (self.before_state, "before_state"),
            (self.after_state, "after_state"),
        ):
            if not is_json_value(value):
                raise ValueError(f"evaluation {role} must be a JSON value")
        if not isinstance(self.trace, tuple) or any(
            not isinstance(item, TraceEvent) for item in self.trace
        ):
            raise ValueError("evaluation trace must contain TraceEvents")
        sequences = [item.seq for item in self.trace]
        if len(sequences) != len(set(sequences)):
            raise ValueError("evaluation trace seq values must be unique")
        if not is_json_object(self.final_answer):
            raise ValueError("evaluation final_answer must be a JSON object")
        for name in ("reset_observation", "before_state", "after_state"):
            object.__setattr__(self, name, _copy_json(cast(JSONValue, getattr(self, name))))
        object.__setattr__(self, "final_answer", _copy_object(self.final_answer))


@dataclass(frozen=True, slots=True)
class EvaluationResult:
    passed: bool
    reset: bool
    before_state: bool
    after_state: bool
    answer_schema: bool
    answer: bool
    goal: bool
    checked: tuple[str, ...]
    reason_codes: tuple[str, ...]

    def to_document(self) -> JSONObject:
        return {
            "passed": self.passed,
            "reset": self.reset,
            "before_state": self.before_state,
            "after_state": self.after_state,
            "answer_schema": self.answer_schema,
            "answer": self.answer,
            "goal": self.goal,
            "checked": list(self.checked),
            "reason_codes": list(self.reason_codes),
        }


def evaluate_goal(truth: GoalTruth, context: EvaluationContext) -> EvaluationResult:
    if not isinstance(truth, GoalTruth) or not isinstance(context, EvaluationContext):
        raise TypeError("evaluate_goal requires GoalTruth and EvaluationContext")
    reset_ok = _same(context.reset_observation, truth.expected_reset)
    before_ok = _same(context.before_state, truth.expected_before)
    after_ok = _same(context.after_state, truth.expected_after)
    try:
        validate_instance(context.final_answer, truth.final_answer_schema, role="final_answer")
        schema_ok = True
    except SchemaError:
        schema_ok = False
    answer_ok = _same(context.final_answer, truth.expected_answer)
    goal_ok, details, _ = _evaluate_node(truth.goal, context, frozenset())
    reasons = [
        code
        for passed, code in (
            (reset_ok, "reset_mismatch"),
            (before_ok, "before_state_mismatch"),
            (after_ok, "after_state_mismatch"),
            (schema_ok, "answer_schema_mismatch"),
            (answer_ok, "answer_mismatch"),
        )
        if not passed
    ]
    if not goal_ok:
        reasons.extend(("goal_unsatisfied", *details))
    codes = tuple(dict.fromkeys(reasons))
    return EvaluationResult(
        not codes, reset_ok, before_ok, after_ok, schema_ok, answer_ok, goal_ok, _CHECKED, codes
    )


def goal_truth_from_document(document: Any) -> GoalTruth:
    value = _exact(
        document,
        {
            "format",
            "goal",
            "expected_reset",
            "expected_before",
            "expected_after",
            "expected_answer",
            "final_answer_schema",
        },
        "GoalTruth",
    )
    if value["format"] != GOAL_TRUTH_FORMAT:
        raise ValueError(f"GoalTruth format must be {GOAL_TRUTH_FORMAT!r}")
    return GoalTruth(
        _goal_from_document(value["goal"]),
        value["expected_reset"],
        value["expected_before"],
        value["expected_after"],
        cast(JSONObject, value["expected_answer"]),
        cast(JSONObject, value["final_answer_schema"]),
    )


def _evaluate_node(
    goal: Goal, context: EvaluationContext, used: frozenset[int]
) -> tuple[bool, tuple[str, ...], frozenset[int]]:
    if isinstance(goal, AtomGoal):
        event = next(
            (
                item
                for item in sorted(context.trace, key=lambda value: value.seq)
                if item.seq not in used and _atom_matches(goal, item)
            ),
            None,
        )
        return (
            (True, (), used | {event.seq})
            if event is not None
            else (False, ("atom_missing",), used)
        )
    if isinstance(goal, AllGoal):
        matched = used
        failures: list[str] = []
        for child in goal.children:
            passed, details, matched = _evaluate_node(child, context, matched)
            if not passed:
                failures.extend(details)
        return not failures, tuple(failures), matched
    if isinstance(goal, IfGoal):
        return _evaluate_if(goal, context, used)
    return _evaluate_foreach(goal, context, used)


def _evaluate_if(
    goal: IfGoal, context: EvaluationContext, used: frozenset[int]
) -> tuple[bool, tuple[str, ...], frozenset[int]]:
    candidates = _source_candidates(goal.condition.source, context)
    if any(isinstance(value, (dict, list)) for value, _ in candidates):
        return False, ("condition_not_scalar",), used
    for value, source_seq in reversed(candidates):
        outcome = _compare(value, goal.condition.operator, goal.condition.value)
        if outcome is None:
            continue
        branch = goal.then_goal if outcome else goal.else_goal
        if branch is None:
            return True, (), used
        branch_used = used | {source_seq}
        passed, details, matched = _evaluate_node(branch, context, branch_used)
        if not passed:
            continue
        branch_matches = matched - branch_used
        if not branch_matches or source_seq >= min(branch_matches):
            continue
        return True, (), matched
    return False, ("condition_unresolved",), used


def _evaluate_foreach(
    goal: ForEachGoal, context: EvaluationContext, used: frozenset[int]
) -> tuple[bool, tuple[str, ...], frozenset[int]]:
    matched = used
    failures: list[str] = []
    for child in goal.children:
        passed, details, matched = _evaluate_node(child, context, matched)
        if not passed:
            failures.extend(details)
    sources = [
        (value, seq)
        for value, seq in _source_candidates(goal.members_source, context)
        if isinstance(value, list) and (not matched or seq < min(matched))
    ]
    if not sources:
        return False, tuple(dict.fromkeys((*failures, "foreach_source_unresolved"))), matched
    try:
        members = sources[-1][0]
        expected = [_pointer_value(item, goal.member_key_pointer) for item in members]
        body_tool = goal.children[0].tool_name
        actual = [
            _pointer_value(item.arguments, goal.member_argument_pointer)
            for item in context.trace
            if item.tool_name == body_tool
            and _outcome_matches(goal.children[0].outcome, None, item)
        ]
        if len(expected) < 2 or _counter(actual) != _counter(expected):
            failures.append("foreach_members_mismatch")
    except (KeyError, IndexError, TypeError, ValueError):
        failures.append("foreach_members_mismatch")
    return not failures, tuple(dict.fromkeys(failures)), matched


def _atom_matches(goal: AtomGoal, event: TraceEvent) -> bool:
    return (
        event.tool_name == goal.tool_name
        and _same(event.arguments, goal.arguments)
        and _outcome_matches(goal.outcome, goal.error_code, event)
    )


def _outcome_matches(outcome: OutcomeClass, code: str | None, event: TraceEvent) -> bool:
    if outcome in {"query", "transition"}:
        return event.observation["ok"] is True
    error = event.observation["error"]
    return (
        event.observation["ok"] is False
        and isinstance(error, dict)
        and (code is None or error.get("code") == code)
    )


def _source_candidates(
    source: GoalValueSource, context: EvaluationContext
) -> list[tuple[JSONValue, int]]:
    if source.kind == "reset":
        try:
            return [(_pointer_value(context.reset_observation, source.pointer), 0)]
        except (KeyError, IndexError, TypeError, ValueError):
            return []
    result = []
    for event in sorted(context.trace, key=lambda item: item.seq):
        if event.tool_name != source.tool_name or not _same(event.arguments, source.arguments):
            continue
        try:
            result.append((_pointer_value(event.observation, source.pointer), event.seq))
        except (KeyError, IndexError, TypeError, ValueError):
            pass
    return result


def _compare(left: JSONValue, operator: ScalarOperator, right: JSONValue) -> bool | None:
    if operator == "eq":
        return type(left) is type(right) and left == right
    if operator == "neq":
        return not (type(left) is type(right) and left == right)
    if isinstance(left, bool) or isinstance(right, bool):
        return None
    if isinstance(left, str) and isinstance(right, str):
        if operator == "lt":
            return left < right
        if operator == "lte":
            return left <= right
        if operator == "gt":
            return left > right
        return left >= right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        first, second = float(left), float(right)
        if operator == "lt":
            return first < second
        if operator == "lte":
            return first <= second
        if operator == "gt":
            return first > second
        return first >= second
    return None


def _goal_from_document(document: Any) -> Goal:
    if not is_json_object(document):
        raise ValueError("Goal must be a JSON object")
    kind = document.get("kind")
    if kind == "atom":
        value = _exact(
            document, {"kind", "tool_name", "arguments", "outcome", "error_code"}, "AtomGoal"
        )
        return AtomGoal(
            cast(str, value["tool_name"]),
            cast(JSONObject, value["arguments"]),
            cast(OutcomeClass, value["outcome"]),
            cast(str | None, value["error_code"]),
        )
    if kind == "all":
        value = _exact(document, {"kind", "children"}, "AllGoal")
        return AllGoal(tuple(_goal_from_document(item) for item in _array(value["children"])))
    if kind == "if":
        value = _exact(document, {"kind", "condition", "then_goal", "else_goal"}, "IfGoal")
        return IfGoal(
            _condition_from_document(value["condition"]),
            _goal_from_document(value["then_goal"]) if value["then_goal"] is not None else None,
            _goal_from_document(value["else_goal"]) if value["else_goal"] is not None else None,
        )
    if kind == "foreach":
        value = _exact(
            document,
            {
                "kind",
                "members_source",
                "member_key_pointer",
                "member_argument_pointer",
                "children",
            },
            "ForEachGoal",
        )
        children = tuple(_goal_from_document(item) for item in _array(value["children"]))
        if any(not isinstance(child, AtomGoal) for child in children):
            raise ValueError("ForEachGoal children must be Atoms")
        return ForEachGoal(
            _source_from_document(value["members_source"]),
            cast(str, value["member_key_pointer"]),
            cast(str, value["member_argument_pointer"]),
            cast(tuple[AtomGoal, ...], children),
        )
    raise ValueError("Goal has unsupported kind")


def _condition_from_document(document: Any) -> ScalarCondition:
    value = _exact(document, {"source", "operator", "value"}, "ScalarCondition")
    return ScalarCondition(
        _source_from_document(value["source"]),
        cast(ScalarOperator, value["operator"]),
        value["value"],
    )


def _source_from_document(document: Any) -> GoalValueSource:
    if not is_json_object(document):
        raise ValueError("GoalValueSource must be a JSON object")
    if document.get("kind") == "reset":
        value = _exact(document, {"kind", "pointer"}, "reset GoalValueSource")
        return GoalValueSource.reset(cast(str, value["pointer"]))
    value = _exact(
        document,
        {"kind", "tool_name", "arguments", "pointer"},
        "observation GoalValueSource",
    )
    if value["kind"] != "observation":
        raise ValueError("GoalValueSource has unsupported kind")
    return GoalValueSource.observation(
        cast(str, value["tool_name"]),
        cast(JSONObject, value["arguments"]),
        cast(str, value["pointer"]),
    )


def _transition_requirement(goal: Goal) -> bool | None:
    if isinstance(goal, AtomGoal):
        return goal.outcome == "transition"
    if isinstance(goal, AllGoal):
        requirements = [_transition_requirement(child) for child in goal.children]
        if True in requirements:
            return True
        return None if None in requirements else False
    if isinstance(goal, IfGoal):
        requirements = [
            False if branch is None else _transition_requirement(branch)
            for branch in (goal.then_goal, goal.else_goal)
        ]
        return requirements[0] if requirements[0] == requirements[1] else None
    return any(child.outcome == "transition" for child in goal.children)


def _is_goal(value: object) -> bool:
    return isinstance(value, (AtomGoal, AllGoal, IfGoal, ForEachGoal))


def _validate_observation(document: Any) -> None:
    if not is_json_object(document) or set(document) != _OBSERVATION_KEYS:
        raise ValueError("trace observation must be a ToolObservation object")
    ok, data, error = document["ok"], document["data"], document["error"]
    if ok is True and error is None:
        return
    if (
        ok is False
        and data is None
        and is_json_object(error)
        and isinstance(error.get("code"), str)
        and isinstance(error.get("message"), str)
    ):
        return
    raise ValueError("trace observation has an invalid success/error variant")


def _answer_schema(schema: JSONObject) -> JSONObject:
    copied = _copy_object(schema)
    try:
        require_object_root(copied, role="GoalTruth final_answer_schema")
        validate_schema_document(copied, role="GoalTruth final_answer_schema")
    except SchemaError as exc:
        raise ValueError(str(exc)) from exc
    return copied


def _pointer(value: str | None, role: str) -> None:
    if not isinstance(value, str) or value != "" and not value.startswith("/"):
        raise ValueError(f"{role} must be an RFC 6901 pointer")
    _pointer_tokens(value)


def _pointer_tokens(pointer: str) -> tuple[str, ...]:
    if pointer == "":
        return ()
    if not pointer.startswith("/"):
        raise ValueError("JSON pointer must start with /")
    result = []
    for raw in pointer[1:].split("/"):
        index = 0
        while index < len(raw):
            if raw[index] == "~" and (index + 1 >= len(raw) or raw[index + 1] not in "01"):
                raise ValueError("JSON pointer contains an invalid escape")
            index += 2 if raw[index] == "~" else 1
        result.append(raw.replace("~1", "/").replace("~0", "~"))
    return tuple(result)


def _pointer_value(document: JSONValue, pointer: str) -> JSONValue:
    current = document
    for token in _pointer_tokens(pointer):
        if isinstance(current, dict):
            current = current[token]
        elif isinstance(current, list):
            current = current[int(token)]
        else:
            raise TypeError("JSON pointer traverses a scalar")
    return _copy_json(current)


def _counter(values: list[JSONValue]) -> Counter[bytes]:
    return Counter(canonical_bytes(value) for value in values)


def _array(value: JSONValue) -> list[JSONValue]:
    if not isinstance(value, list):
        raise ValueError("Goal children must be an array")
    return value


def _exact(document: Any, keys: set[str], role: str) -> JSONObject:
    if not is_json_object(document) or set(document) != keys:
        actual = sorted(document) if isinstance(document, dict) else type(document).__name__
        raise ValueError(f"{role} has invalid fields: expected {sorted(keys)}, got {actual}")
    return cast(JSONObject, document)


def _text(value: str | None, role: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{role} must be non-empty text")


def _same(left: JSONValue, right: JSONValue) -> bool:
    return canonical_bytes(left) == canonical_bytes(right)


def _digest(document: JSONObject) -> str:
    return sha256_hex(canonical_bytes(document))


def _copy_json(value: JSONValue) -> JSONValue:
    return cast(JSONValue, json.loads(json.dumps(value, ensure_ascii=False)))


def _copy_object(value: JSONObject) -> JSONObject:
    return cast(JSONObject, _copy_json(value))


__all__ = [
    "GOAL_TRUTH_FORMAT",
    "AllGoal",
    "AtomGoal",
    "EvaluationContext",
    "EvaluationResult",
    "ForEachGoal",
    "GoalTruth",
    "GoalValueSource",
    "IfGoal",
    "ScalarCondition",
    "TraceEvent",
    "evaluate_goal",
    "goal_truth_from_document",
]
