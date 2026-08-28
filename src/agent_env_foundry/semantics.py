"""Protected task-semantics contract for EnvironmentRelease v2.

This module defines generic framework types only.  A release-local semantics
project implements :class:`TaskSemantics` and is independently qualified against
native state.  Acting policies never receive this surface.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol, runtime_checkable

from agent_env_foundry.jsonvalue import is_json_object, is_json_value
from agent_env_foundry.schema import SchemaError, require_object_root, validate_instance

JSONValue = None | bool | int | float | str | list["JSONValue"] | dict[str, "JSONValue"]
JSONObject = dict[str, JSONValue]
FacetOperator = Literal["eq", "neq", "lt", "lte", "gt", "gte", "min", "max"]
GoalKind = Literal["atom", "all", "if", "foreach"]
TaskKind = Literal["query", "state_change", "process"]
CheckStatus = Literal["satisfied", "failed", "abstain"]


class SemanticsContractError(ValueError):
    """A release-local semantics object violates the generic contract."""


@dataclass(frozen=True, slots=True)
class StartCase:
    case_id: str
    reset_input: JSONObject | None
    regime_tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _identifier(self.case_id, "case_id")
        if self.reset_input is not None and not is_json_object(self.reset_input):
            raise SemanticsContractError("reset_input must be a JSON object or None")
        _unique(self.regime_tags, "regime_tags")

    def to_document(self) -> JSONObject:
        return {
            "case_id": self.case_id,
            "reset_input": _json(self.reset_input),
            "regime_tags": list(self.regime_tags),
        }


@dataclass(frozen=True, slots=True)
class AnswerFieldSpec:
    name: str
    public_label: str
    value_schema: JSONObject

    def __post_init__(self) -> None:
        _identifier(self.name, "answer field name")
        _text(self.public_label, "answer field label")
        _schema(self.value_schema, f"answer field {self.name!r}")

    def to_document(self) -> JSONObject:
        return {
            "name": self.name,
            "public_label": self.public_label,
            "value_schema": _json(self.value_schema),
        }


@dataclass(frozen=True, slots=True)
class FacetSpec:
    name: str
    public_label: str
    value_schema: JSONObject
    allowed_operators: tuple[FacetOperator, ...]
    visibility: Literal["task_literal", "reset", "public_tool"]
    output_pointer: str | None = None

    def __post_init__(self) -> None:
        _identifier(self.name, "facet name")
        _text(self.public_label, "facet label")
        _schema(self.value_schema, f"facet {self.name!r}")
        if not self.allowed_operators:
            raise SemanticsContractError("facet operators must not be empty")
        _unique(self.allowed_operators, "facet operators")
        if self.visibility == "public_tool":
            _pointer(self.output_pointer, "public_tool facet output_pointer")

    def to_document(self) -> JSONObject:
        return {
            "name": self.name,
            "public_label": self.public_label,
            "value_schema": _json(self.value_schema),
            "allowed_operators": list(self.allowed_operators),
            "visibility": self.visibility,
            "output_pointer": self.output_pointer,
        }


@dataclass(frozen=True, slots=True)
class CompositionRule:
    rule_id: str
    workflow_id: str
    capability_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _identifier(self.rule_id, "composition rule ID")
        _identifier(self.workflow_id, "workflow ID")
        if len(self.capability_ids) < 2:
            raise SemanticsContractError("composition rule needs at least two capabilities")
        _unique(self.capability_ids, "composition capability IDs")

    def to_document(self) -> JSONObject:
        return {
            "rule_id": self.rule_id,
            "workflow_id": self.workflow_id,
            "capability_ids": list(self.capability_ids),
        }


@dataclass(frozen=True, slots=True)
class ConditionSpec:
    condition_id: str
    public_label: str
    visibility: Literal["reset", "public_tool"]
    true_capability_ids: tuple[str, ...] = ()
    false_capability_ids: tuple[str, ...] = ()
    report_field: AnswerFieldSpec | None = None
    output_pointer: str | None = None

    def __post_init__(self) -> None:
        _identifier(self.condition_id, "condition ID")
        _text(self.public_label, "condition label")
        _unique(self.true_capability_ids, "condition true capabilities")
        _unique(self.false_capability_ids, "condition false capabilities")
        if not self.true_capability_ids and not self.false_capability_ids and self.report_field is None:
            raise SemanticsContractError("condition licenses neither a branch nor a report")
        if self.visibility == "public_tool":
            _pointer(self.output_pointer, "condition output_pointer")

    def to_document(self) -> JSONObject:
        return {
            "condition_id": self.condition_id,
            "public_label": self.public_label,
            "visibility": self.visibility,
            "true_capability_ids": list(self.true_capability_ids),
            "false_capability_ids": list(self.false_capability_ids),
            "report_field": self.report_field.to_document() if self.report_field else None,
            "output_pointer": self.output_pointer,
        }


@dataclass(frozen=True, slots=True)
class RenderingSpec:
    target_singular: str
    target_plural: str
    action_phrase: str

    def __post_init__(self) -> None:
        _text(self.target_singular, "singular target label")
        _text(self.target_plural, "plural target label")
        _text(self.action_phrase, "action phrase")

    def to_document(self) -> JSONObject:
        return {
            "target_singular": self.target_singular,
            "target_plural": self.target_plural,
            "action_phrase": self.action_phrase,
        }


@dataclass(frozen=True, slots=True)
class CapabilitySpec:
    capability_id: str
    requirement_ids: tuple[str, ...]
    workflow_ids: tuple[str, ...]
    actor_role: str
    task_kind: TaskKind
    intent_label: str
    protected_binding_schema: JSONObject
    public_descriptor_schema: JSONObject
    facets: tuple[FacetSpec, ...]
    composition_rules: tuple[CompositionRule, ...] = ()
    conditions: tuple[ConditionSpec, ...] = ()
    answer_fields: tuple[AnswerFieldSpec, ...] = ()
    read_scopes: tuple[str, ...] = ()
    write_scopes: tuple[str, ...] = ()
    supported_goal_kinds: tuple[GoalKind, ...] = ("atom",)
    rendering: RenderingSpec = field(
        default_factory=lambda: RenderingSpec("item", "items", "process")
    )

    def __post_init__(self) -> None:
        _identifier(self.capability_id, "capability ID")
        if not self.requirement_ids or not self.workflow_ids:
            raise SemanticsContractError("capability must be Requirement- and workflow-anchored")
        _unique(self.requirement_ids, "requirement IDs")
        _unique(self.workflow_ids, "workflow IDs")
        _text(self.actor_role, "actor role")
        _text(self.intent_label, "intent label")
        _object_schema(self.protected_binding_schema, "protected binding")
        _object_schema(self.public_descriptor_schema, "public descriptor")
        if "atom" not in self.supported_goal_kinds:
            raise SemanticsContractError("every capability must support atom")
        _unique(self.supported_goal_kinds, "goal kinds")
        _unique_by(self.facets, "name", "facets")
        _unique_by(self.conditions, "condition_id", "conditions")
        _unique_by(self.answer_fields, "name", "answer fields")
        _unique_by(self.composition_rules, "rule_id", "composition rules")
        for rule in self.composition_rules:
            if self.capability_id not in rule.capability_ids:
                raise SemanticsContractError("attached composition rule omits capability")
            if rule.workflow_id not in self.workflow_ids:
                raise SemanticsContractError("composition rule uses undeclared workflow")

    def to_document(self) -> JSONObject:
        return {
            "capability_id": self.capability_id,
            "requirement_ids": list(self.requirement_ids),
            "workflow_ids": list(self.workflow_ids),
            "actor_role": self.actor_role,
            "task_kind": self.task_kind,
            "intent_label": self.intent_label,
            "protected_binding_schema": _json(self.protected_binding_schema),
            "public_descriptor_schema": _json(self.public_descriptor_schema),
            "facets": [value.to_document() for value in self.facets],
            "composition_rules": [value.to_document() for value in self.composition_rules],
            "conditions": [value.to_document() for value in self.conditions],
            "answer_fields": [value.to_document() for value in self.answer_fields],
            "read_scopes": list(self.read_scopes),
            "write_scopes": list(self.write_scopes),
            "supported_goal_kinds": list(self.supported_goal_kinds),
            "rendering": self.rendering.to_document(),
        }


@dataclass(frozen=True, slots=True)
class BindingCandidate:
    semantic_key: str
    eligible: bool
    protected_binding: JSONObject
    public_descriptor: JSONObject
    facets: JSONObject
    reason_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _identifier(self.semantic_key, "semantic key")
        if not all(is_json_object(value) for value in (
            self.protected_binding, self.public_descriptor, self.facets
        )):
            raise SemanticsContractError("binding projections must be JSON objects")
        _unique(self.reason_codes, "binding reason codes")
        if self.eligible and self.reason_codes:
            raise SemanticsContractError("eligible binding cannot have rejection reasons")

    def public_document(self) -> JSONObject:
        return {
            "semantic_key": self.semantic_key,
            "eligible": self.eligible,
            "public_descriptor": _json(self.public_descriptor),
            "facets": _json(self.facets),
        }


@dataclass(frozen=True, slots=True)
class TraceEvent:
    seq: int
    tool_name: str
    arguments: JSONObject
    observation: JSONObject

    def __post_init__(self) -> None:
        if self.seq <= 0:
            raise SemanticsContractError("trace sequence must be positive")
        _identifier(self.tool_name, "tool name")
        if not is_json_object(self.arguments) or not is_json_object(self.observation):
            raise SemanticsContractError("trace arguments/observation must be JSON objects")


@dataclass(frozen=True, slots=True)
class AtomCheckRequest:
    capability_id: str
    before_facts: JSONValue
    after_facts: JSONValue
    protected_binding: JSONObject
    trace: tuple[TraceEvent, ...]
    final_answer: JSONValue


@dataclass(frozen=True, slots=True)
class AtomCheckResult:
    status: CheckStatus
    initially_satisfied: bool
    required_effects_satisfied: bool
    collateral_ok: bool
    answer_values: JSONObject = field(default_factory=dict)
    process_ok: bool | None = None
    failures: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not is_json_object(self.answer_values):
            raise SemanticsContractError("answer_values must be a JSON object")
        _unique(self.failures, "atomic failures")
        if self.status == "satisfied" and (
            not self.required_effects_satisfied
            or not self.collateral_ok
            or self.process_ok is False
            or self.failures
        ):
            raise SemanticsContractError("satisfied atomic result is contradictory")


@dataclass(frozen=True, slots=True)
class ConditionCheckRequest:
    condition_id: str
    before_facts: JSONValue
    protected_binding: JSONObject | None
    trace: tuple[TraceEvent, ...]


@dataclass(frozen=True, slots=True)
class ConditionCheckResult:
    status: Literal["true", "false", "abstain"]
    report_values: JSONObject = field(default_factory=dict)
    failures: tuple[str, ...] = ()


@runtime_checkable
class TaskSemantics(Protocol):
    def start_cases(self, seed: int, limit: int) -> tuple[StartCase, ...]: ...
    def inspect(self, instance_directory: Path) -> JSONValue: ...
    def capabilities(self) -> tuple[CapabilitySpec, ...]: ...
    def enumerate_bindings(
        self, capability_id: str, facts: JSONValue
    ) -> tuple[BindingCandidate, ...]: ...
    def evaluate_atom(self, request: AtomCheckRequest) -> AtomCheckResult: ...
    def evaluate_condition(self, request: ConditionCheckRequest) -> ConditionCheckResult: ...


def validate_catalog(specs: tuple[CapabilitySpec, ...]) -> dict[str, CapabilitySpec]:
    if not isinstance(specs, tuple):
        raise SemanticsContractError("capabilities() must return a tuple")
    catalog = {spec.capability_id: spec for spec in specs}
    if len(catalog) != len(specs):
        raise SemanticsContractError("duplicate capability ID")
    rules: dict[str, CompositionRule] = {}
    for spec in specs:
        for rule in spec.composition_rules:
            previous = rules.setdefault(rule.rule_id, rule)
            if previous != rule:
                raise SemanticsContractError("inconsistent composition rule declarations")
    for rule in rules.values():
        if not set(rule.capability_ids) <= set(catalog):
            raise SemanticsContractError("composition rule references missing capability")
    return catalog


def validate_binding(spec: CapabilitySpec, binding: BindingCandidate) -> None:
    try:
        validate_instance(binding.protected_binding, spec.protected_binding_schema, role="binding")
        validate_instance(
            binding.public_descriptor, spec.public_descriptor_schema, role="public descriptor"
        )
    except SchemaError as exc:
        raise SemanticsContractError(str(exc)) from exc
    facets = {facet.name: facet for facet in spec.facets}
    if not set(binding.facets) <= set(facets):
        raise SemanticsContractError("binding contains undeclared facet")
    for name, value in binding.facets.items():
        try:
            validate_instance(value, facets[name].value_schema, role=f"facet {name!r}")
        except SchemaError as exc:
            raise SemanticsContractError(str(exc)) from exc


def validate_start_cases(
    cases: tuple[StartCase, ...], *, start_schema: JSONObject | None, limit: int
) -> None:
    if not isinstance(cases, tuple) or len(cases) > limit:
        raise SemanticsContractError("invalid start-case result")
    _unique(tuple(case.case_id for case in cases), "start-case IDs")
    for case in cases:
        if case.reset_input is not None and start_schema is not None:
            try:
                validate_instance(case.reset_input, start_schema, role=f"start {case.case_id!r}")
            except SchemaError as exc:
                raise SemanticsContractError(str(exc)) from exc


def _schema(value: JSONObject, role: str) -> None:
    try:
        from agent_env_foundry.schema import validate_schema_document

        validate_schema_document(value, role=role)
    except SchemaError as exc:
        raise SemanticsContractError(str(exc)) from exc


def _object_schema(value: JSONObject, role: str) -> None:
    try:
        require_object_root(value, role=role)
    except SchemaError as exc:
        raise SemanticsContractError(str(exc)) from exc


def _identifier(value: str, role: str) -> None:
    if not value or value.strip() != value or any(char.isspace() for char in value):
        raise SemanticsContractError(f"{role} must be a non-empty whitespace-free string")


def _text(value: str, role: str) -> None:
    if not value.strip():
        raise SemanticsContractError(f"{role} must be non-empty")


def _pointer(value: str | None, role: str) -> None:
    if not isinstance(value, str) or (value and not value.startswith("/")):
        raise SemanticsContractError(f"{role} must be an RFC 6901 pointer")


def _unique(values: tuple[Any, ...], role: str) -> None:
    if len(values) != len(set(values)):
        raise SemanticsContractError(f"{role} must be unique")


def _unique_by(values: tuple[Any, ...], attribute: str, role: str) -> None:
    _unique(tuple(getattr(value, attribute) for value in values), role)


def _json(value: Any) -> JSONValue:
    if value is None or isinstance(value, (bool, int, float, str)):
        if not is_json_value(value):
            raise SemanticsContractError("non-finite JSON number")
        return value
    if isinstance(value, (list, tuple)):
        return [_json(item) for item in value]
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise SemanticsContractError("JSON object keys must be strings")
        return {key: _json(item) for key, item in value.items()}
    if hasattr(value, "to_document"):
        return _json(value.to_document())
    raise SemanticsContractError(f"not JSON-compatible: {type(value).__name__}")
