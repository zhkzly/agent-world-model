"""Release-local protected task-semantics contracts for EnvironmentRelease v2."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol, cast, runtime_checkable

from agent_env_foundry.environment import JSONObject, JSONValue
from agent_env_foundry.jsonvalue import is_json_object, is_json_value
from agent_env_foundry.schema import (
    SchemaError,
    require_object_root,
    validate_instance,
    validate_schema_document,
)

FacetOperator = Literal["eq", "neq", "lt", "lte", "gt", "gte", "min", "max"]
GoalKind = Literal["atom", "all", "if", "foreach"]
TaskKind = Literal["query", "state_change", "process"]
ConditionStatus = Literal["true", "false", "abstain"]
PublicValueKind = Literal["task_literal", "reset", "tool_output", "tool_schema_constant"]
BindingScope = Literal["world", "selected_binding"]
_FACET_OPERATORS = frozenset({"eq", "neq", "lt", "lte", "gt", "gte", "min", "max"})
_PUBLIC_VALUE_KINDS = frozenset({"task_literal", "reset", "tool_output", "tool_schema_constant"})
_BINDING_SCOPES = frozenset({"world", "selected_binding"})
_TASK_KINDS = frozenset({"query", "state_change", "process"})
_GOAL_KINDS = frozenset({"atom", "all", "if", "foreach"})


class SemanticsContractError(ValueError):
    """A release-local semantics value violates the generic Host contract."""


@dataclass(frozen=True, slots=True)
class StartCase:
    case_id: str
    reset_input: JSONObject | None
    regime_tags: tuple[str, ...]

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
class PublicValueSource:
    kind: PublicValueKind
    tool_name: str | None
    json_pointer: str | None
    value: JSONValue | None

    def __post_init__(self) -> None:
        if self.kind not in _PUBLIC_VALUE_KINDS:
            raise SemanticsContractError("public value source kind is invalid")
        if self.kind == "task_literal":
            if self.tool_name is not None or self.json_pointer is not None:
                raise SemanticsContractError(
                    "task_literal source must not declare tool_name or json_pointer"
                )
            return
        if self.kind == "reset":
            if self.tool_name is not None:
                raise SemanticsContractError("reset source must not declare tool_name")
            if self.json_pointer is None:
                raise SemanticsContractError("reset source requires json_pointer")
            _pointer(self.json_pointer, "reset source json_pointer")
            if self.value is not None:
                raise SemanticsContractError("reset source must not declare value")
            return
        if self.tool_name is None:
            raise SemanticsContractError(f"{self.kind} source requires tool_name")
        _identifier(self.tool_name, f"{self.kind} source tool_name")
        if self.json_pointer is None:
            raise SemanticsContractError(f"{self.kind} source requires json_pointer")
        _pointer(self.json_pointer, f"{self.kind} source json_pointer")
        if self.kind == "tool_output" and self.value is not None:
            raise SemanticsContractError("tool_output source must not declare value")

    def to_document(self) -> JSONObject:
        return {
            "kind": self.kind,
            "tool_name": self.tool_name,
            "json_pointer": self.json_pointer,
            "value": _json(self.value),
        }


@dataclass(frozen=True, slots=True)
class AnswerFieldSpec:
    field_id: str
    schema: JSONObject
    public_label: str
    public_source: PublicValueSource

    def __post_init__(self) -> None:
        _identifier(self.field_id, "answer field_id")
        _schema(self.schema, f"answer field {self.field_id!r}")
        _text(self.public_label, "answer field public_label")

    def to_document(self) -> JSONObject:
        return {
            "field_id": self.field_id,
            "schema": _json(self.schema),
            "public_label": self.public_label,
            "public_source": self.public_source.to_document(),
        }


@dataclass(frozen=True, slots=True)
class FacetSpec:
    name: str
    public_label: str
    value_schema: JSONObject
    allowed_operators: tuple[FacetOperator, ...]

    def __post_init__(self) -> None:
        _identifier(self.name, "facet name")
        _text(self.public_label, "facet public_label")
        _schema(self.value_schema, f"facet {self.name!r}")
        if not self.allowed_operators:
            raise SemanticsContractError("facet allowed_operators must not be empty")
        _unique(self.allowed_operators, "facet allowed_operators")
        if any(operator not in _FACET_OPERATORS for operator in self.allowed_operators):
            raise SemanticsContractError("facet contains an unsupported operator")

    def to_document(self) -> JSONObject:
        return {
            "name": self.name,
            "public_label": self.public_label,
            "value_schema": _json(self.value_schema),
            "allowed_operators": list(self.allowed_operators),
        }


@dataclass(frozen=True, slots=True)
class CompositionRule:
    rule_id: str
    workflow_id: str
    kind: Literal["all"]
    capability_ids: tuple[str, ...]
    max_occurrences: int

    def __post_init__(self) -> None:
        _identifier(self.rule_id, "composition rule_id")
        _identifier(self.workflow_id, "composition workflow_id")
        if self.kind != "all":
            raise SemanticsContractError("composition kind must be 'all'")
        if len(self.capability_ids) < 2:
            raise SemanticsContractError("composition rule needs at least two capabilities")
        _unique(self.capability_ids, "composition capability_ids")
        if self.max_occurrences <= 0:
            raise SemanticsContractError("composition max_occurrences must be positive")

    def to_document(self) -> JSONObject:
        return {
            "rule_id": self.rule_id,
            "workflow_id": self.workflow_id,
            "kind": self.kind,
            "capability_ids": list(self.capability_ids),
            "max_occurrences": self.max_occurrences,
        }


@dataclass(frozen=True, slots=True)
class ConditionSpec:
    condition_id: str
    public_label: str
    binding_scope: BindingScope
    true_capability_ids: tuple[str, ...]
    false_capability_ids: tuple[str, ...]
    report_field: AnswerFieldSpec | None
    public_source: PublicValueSource

    def __post_init__(self) -> None:
        _identifier(self.condition_id, "condition_id")
        _text(self.public_label, "condition public_label")
        _unique(self.true_capability_ids, "condition true_capability_ids")
        _unique(self.false_capability_ids, "condition false_capability_ids")
        if self.binding_scope not in _BINDING_SCOPES:
            raise SemanticsContractError("condition binding_scope is invalid")
        if (
            not self.true_capability_ids
            and not self.false_capability_ids
            and self.report_field is None
        ):
            raise SemanticsContractError("condition licenses neither a branch nor a report")

    def to_document(self) -> JSONObject:
        return {
            "condition_id": self.condition_id,
            "public_label": self.public_label,
            "binding_scope": self.binding_scope,
            "true_capability_ids": list(self.true_capability_ids),
            "false_capability_ids": list(self.false_capability_ids),
            "report_field": self.report_field.to_document() if self.report_field else None,
            "public_source": self.public_source.to_document(),
        }


@dataclass(frozen=True, slots=True)
class RenderingSpec:
    imperative: str
    target_noun: str
    answer_phrase: str | None

    def __post_init__(self) -> None:
        _text(self.imperative, "rendering imperative")
        _text(self.target_noun, "rendering target_noun")
        if self.answer_phrase is not None:
            _text(self.answer_phrase, "rendering answer_phrase")

    def to_document(self) -> JSONObject:
        return {
            "imperative": self.imperative,
            "target_noun": self.target_noun,
            "answer_phrase": self.answer_phrase,
        }


@dataclass(frozen=True, slots=True)
class CapabilitySpec:
    capability_id: str
    requirement_ids: tuple[str, ...]
    workflow_ids: tuple[str, ...]
    composition_rules: tuple[CompositionRule, ...]
    actor_role: str
    task_kind: TaskKind
    intent_label: str
    protected_binding_schema: JSONObject
    public_descriptor_schema: JSONObject
    facets: tuple[FacetSpec, ...]
    conditions: tuple[ConditionSpec, ...]
    answer_fields: tuple[AnswerFieldSpec, ...]
    supported_goal_kinds: tuple[GoalKind, ...]
    rendering: RenderingSpec

    def __post_init__(self) -> None:
        _identifier(self.capability_id, "capability_id")
        if not self.requirement_ids or not self.workflow_ids:
            raise SemanticsContractError("capability must be Requirement- and workflow-anchored")
        for values, role in (
            (self.requirement_ids, "requirement_ids"),
            (self.workflow_ids, "workflow_ids"),
            (self.supported_goal_kinds, "supported_goal_kinds"),
        ):
            _unique(values, role)
        _text(self.actor_role, "actor_role")
        _text(self.intent_label, "intent_label")
        if self.task_kind not in _TASK_KINDS:
            raise SemanticsContractError("capability task_kind is invalid")
        if self.task_kind == "query" and not self.answer_fields:
            raise SemanticsContractError("query capability requires answer_fields")
        if self.task_kind == "query" and self.rendering.answer_phrase is None:
            raise SemanticsContractError("query capability requires rendering answer_phrase")
        _object_schema(self.protected_binding_schema, "protected_binding")
        _object_schema(self.public_descriptor_schema, "public_descriptor")
        if "atom" not in self.supported_goal_kinds:
            raise SemanticsContractError("every capability must support atom")
        if any(kind not in _GOAL_KINDS for kind in self.supported_goal_kinds):
            raise SemanticsContractError("capability supported_goal_kinds is invalid")
        _unique_by(self.facets, "name", "facets")
        _unique_by(self.conditions, "condition_id", "conditions")
        _unique_by(self.answer_fields, "field_id", "answer_fields")
        _unique_by(self.composition_rules, "rule_id", "composition_rules")
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
            "composition_rules": [value.to_document() for value in self.composition_rules],
            "actor_role": self.actor_role,
            "task_kind": self.task_kind,
            "intent_label": self.intent_label,
            "protected_binding_schema": _json(self.protected_binding_schema),
            "public_descriptor_schema": _json(self.public_descriptor_schema),
            "facets": [value.to_document() for value in self.facets],
            "conditions": [value.to_document() for value in self.conditions],
            "answer_fields": [value.to_document() for value in self.answer_fields],
            "supported_goal_kinds": list(self.supported_goal_kinds),
            "rendering": self.rendering.to_document(),
        }


@dataclass(frozen=True, slots=True)
class PublicFieldSource:
    field_pointer: str
    source: PublicValueSource

    def __post_init__(self) -> None:
        if not self.field_pointer.startswith("/"):
            raise SemanticsContractError("public field_pointer must be an RFC 6901 pointer")
        _pointer(self.field_pointer, "public field_pointer")

    def to_document(self) -> JSONObject:
        return {
            "field_pointer": self.field_pointer,
            "source": self.source.to_document(),
        }


@dataclass(frozen=True, slots=True)
class BindingCandidate:
    semantic_key: str
    eligible: bool
    reason_codes: tuple[str, ...]
    protected_binding: JSONObject
    public_descriptor: JSONObject
    facets: JSONObject
    public_sources: tuple[PublicFieldSource, ...]

    def __post_init__(self) -> None:
        _identifier(self.semantic_key, "semantic_key")
        _unique(self.reason_codes, "reason_codes")
        if self.eligible and self.reason_codes:
            raise SemanticsContractError("eligible binding reason_codes must be empty")
        if not self.eligible and not self.reason_codes:
            raise SemanticsContractError("ineligible binding requires reason_codes")
        if not all(
            is_json_object(value)
            for value in (self.protected_binding, self.public_descriptor, self.facets)
        ):
            raise SemanticsContractError("binding projections must be JSON objects")
        pointers = tuple(item.field_pointer for item in self.public_sources)
        if len(pointers) != len(set(pointers)):
            raise SemanticsContractError("duplicate binding public source pointer")
        if set(pointers) != _public_leaf_pointers(self.public_descriptor, self.facets):
            raise SemanticsContractError(
                "binding public_sources must cover every public leaf exactly"
            )
        public_values = {
            item.field_pointer: _resolve_public_pointer(
                self.public_descriptor,
                self.facets,
                item.field_pointer,
            )
            for item in self.public_sources
        }
        for item in self.public_sources:
            if (
                item.source.kind == "task_literal"
                and item.source.value != public_values[item.field_pointer]
            ):
                raise SemanticsContractError(
                    "task_literal public source value differs from its public leaf"
                )

    def public_document(self) -> JSONObject:
        return {
            "public_descriptor": _json(self.public_descriptor),
            "facets": _json(self.facets),
        }

    def to_document(self) -> JSONObject:
        return {
            "semantic_key": self.semantic_key,
            "eligible": self.eligible,
            "reason_codes": list(self.reason_codes),
            "protected_binding": _json(self.protected_binding),
            "public_descriptor": _json(self.public_descriptor),
            "facets": _json(self.facets),
            "public_sources": [item.to_document() for item in self.public_sources],
        }


@dataclass(frozen=True, slots=True)
class TraceEvent:
    seq: int
    tool_name: str
    arguments: JSONObject
    observation: JSONObject

    def __post_init__(self) -> None:
        if self.seq <= 0:
            raise SemanticsContractError("trace seq must be positive")
        _identifier(self.tool_name, "trace tool_name")
        if not is_json_object(self.arguments) or not is_json_object(self.observation):
            raise SemanticsContractError("trace arguments and observation must be JSON objects")

    def to_document(self) -> JSONObject:
        return {
            "seq": self.seq,
            "tool_name": self.tool_name,
            "arguments": _json(self.arguments),
            "observation": _json(self.observation),
        }


@dataclass(frozen=True, slots=True)
class EvaluationBinding:
    slot: str
    capability_id: str
    semantic_key: str
    protected_binding: JSONObject

    def __post_init__(self) -> None:
        _identifier(self.slot, "evaluation binding slot")
        _identifier(self.capability_id, "evaluation binding capability_id")
        _identifier(self.semantic_key, "evaluation binding semantic_key")
        if not is_json_object(self.protected_binding):
            raise SemanticsContractError("evaluation protected_binding must be a JSON object")

    def to_document(self) -> JSONObject:
        return {
            "slot": self.slot,
            "capability_id": self.capability_id,
            "semantic_key": self.semantic_key,
            "protected_binding": _json(self.protected_binding),
        }


@dataclass(frozen=True, slots=True)
class GoalEvaluationContext:
    current_slot: str
    resolved_bindings: tuple[EvaluationBinding, ...]
    composition_rule_id: str | None
    foreach_selector_id: str | None
    permitted_sibling_slots: tuple[str, ...]

    def __post_init__(self) -> None:
        _identifier(self.current_slot, "evaluation current_slot")
        if self.composition_rule_id is not None:
            _identifier(self.composition_rule_id, "evaluation composition_rule_id")
        if self.foreach_selector_id is not None:
            _identifier(self.foreach_selector_id, "evaluation foreach_selector_id")
        if self.composition_rule_id is not None and self.foreach_selector_id is not None:
            raise SemanticsContractError(
                "composition_rule_id and foreach_selector_id are mutually exclusive"
            )
        slots = tuple(item.slot for item in self.resolved_bindings)
        _unique(slots, "evaluation binding slots")
        if self.current_slot not in slots:
            raise SemanticsContractError("evaluation current_slot is not resolved")
        _unique(self.permitted_sibling_slots, "permitted_sibling_slots")
        allowed = set(slots) - {self.current_slot}
        if set(self.permitted_sibling_slots) != allowed:
            raise SemanticsContractError(
                "permitted_sibling_slots must contain exactly all selected siblings"
            )
        if self.composition_rule_id is not None and not allowed:
            raise SemanticsContractError("composition evaluation requires a selected sibling")
        if (
            self.composition_rule_id is None
            and self.foreach_selector_id is None
            and self.permitted_sibling_slots
        ):
            raise SemanticsContractError(
                "atom evaluation without composition/foreach cannot permit siblings"
            )

    def to_document(self) -> JSONObject:
        return {
            "current_slot": self.current_slot,
            "resolved_bindings": [item.to_document() for item in self.resolved_bindings],
            "composition_rule_id": self.composition_rule_id,
            "foreach_selector_id": self.foreach_selector_id,
            "permitted_sibling_slots": list(self.permitted_sibling_slots),
        }


@dataclass(frozen=True, slots=True)
class AtomCheckRequest:
    capability_id: str
    before_facts: JSONValue
    after_facts: JSONValue
    protected_binding: JSONObject
    trace_projection: tuple[TraceEvent, ...]
    final_answer: JSONValue | None
    evaluation_context: GoalEvaluationContext

    def __post_init__(self) -> None:
        _identifier(self.capability_id, "atom capability_id")
        if not is_json_value(self.before_facts) or not is_json_value(self.after_facts):
            raise SemanticsContractError("atom facts must be JSON values")
        if not is_json_object(self.protected_binding):
            raise SemanticsContractError("atom protected_binding must be a JSON object")
        _unique(tuple(item.seq for item in self.trace_projection), "trace sequence numbers")
        current = next(
            item
            for item in self.evaluation_context.resolved_bindings
            if item.slot == self.evaluation_context.current_slot
        )
        if current.capability_id != self.capability_id:
            raise SemanticsContractError("evaluation current binding uses another capability")
        if current.protected_binding != self.protected_binding:
            raise SemanticsContractError("evaluation current binding differs from request binding")

    def to_document(self) -> JSONObject:
        return {
            "capability_id": self.capability_id,
            "before_facts": _json(self.before_facts),
            "after_facts": _json(self.after_facts),
            "protected_binding": _json(self.protected_binding),
            "trace_projection": [item.to_document() for item in self.trace_projection],
            "final_answer": _json(self.final_answer),
            "evaluation_context": self.evaluation_context.to_document(),
        }


@dataclass(frozen=True, slots=True)
class AtomCheckResult:
    initially_satisfied: bool
    satisfied: bool
    required_effects_ok: bool
    collateral_ok: bool
    answer_ok: bool | None
    process_ok: bool | None
    report_values: JSONObject
    failure_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        if not is_json_object(self.report_values):
            raise SemanticsContractError("report_values must be a JSON object")
        _unique(self.failure_codes, "failure_codes")
        if self.satisfied and (
            not self.required_effects_ok
            or not self.collateral_ok
            or self.answer_ok is False
            or self.process_ok is False
            or self.failure_codes
        ):
            raise SemanticsContractError("satisfied atomic result is contradictory")

    def to_document(self) -> JSONObject:
        return {
            "initially_satisfied": self.initially_satisfied,
            "satisfied": self.satisfied,
            "required_effects_ok": self.required_effects_ok,
            "collateral_ok": self.collateral_ok,
            "answer_ok": self.answer_ok,
            "process_ok": self.process_ok,
            "report_values": _json(self.report_values),
            "failure_codes": list(self.failure_codes),
        }


@dataclass(frozen=True, slots=True)
class ConditionCheckRequest:
    condition_id: str
    before_facts: JSONValue
    protected_binding: JSONObject | None
    trace_projection: tuple[TraceEvent, ...]

    def to_document(self) -> JSONObject:
        return {
            "condition_id": self.condition_id,
            "before_facts": _json(self.before_facts),
            "protected_binding": _json(self.protected_binding),
            "trace_projection": [item.to_document() for item in self.trace_projection],
        }


@dataclass(frozen=True, slots=True)
class ConditionCheckResult:
    status: ConditionStatus
    report_values: JSONObject
    failure_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.status not in ("true", "false", "abstain"):
            raise SemanticsContractError("invalid condition status")
        if not is_json_object(self.report_values):
            raise SemanticsContractError("condition report_values must be a JSON object")
        _unique(self.failure_codes, "condition failure_codes")

    def to_document(self) -> JSONObject:
        return {
            "status": self.status,
            "report_values": _json(self.report_values),
            "failure_codes": list(self.failure_codes),
        }


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
        for condition in spec.conditions:
            referenced = set(condition.true_capability_ids) | set(condition.false_capability_ids)
            if not referenced <= set(catalog):
                raise SemanticsContractError("condition references missing capability")
    for rule in rules.values():
        if not set(rule.capability_ids) <= set(catalog):
            raise SemanticsContractError("composition rule references missing capability")
    return catalog


def validate_binding(spec: CapabilitySpec, binding: BindingCandidate) -> None:
    try:
        validate_instance(
            binding.protected_binding,
            spec.protected_binding_schema,
            role="protected binding",
        )
        validate_instance(
            binding.public_descriptor,
            spec.public_descriptor_schema,
            role="public descriptor",
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


def validate_bindings(
    spec: CapabilitySpec,
    bindings: tuple[BindingCandidate, ...],
) -> None:
    if not isinstance(bindings, tuple):
        raise SemanticsContractError("bindings must be a tuple")
    _unique(tuple(item.semantic_key for item in bindings), "binding semantic keys")
    public_documents: list[JSONObject] = []
    for binding in bindings:
        validate_binding(spec, binding)
        public = binding.public_document()
        if public in public_documents:
            raise SemanticsContractError("different semantic keys are publicly indistinguishable")
        public_documents.append(public)


def validate_start_cases(
    cases: tuple[StartCase, ...],
    *,
    start_schema: JSONObject | None,
    limit: int,
) -> None:
    if limit <= 0:
        raise SemanticsContractError("start-case limit must be positive")
    if not isinstance(cases, tuple) or len(cases) > limit:
        raise SemanticsContractError("invalid start-case result or limit")
    _unique(tuple(case.case_id for case in cases), "start-case IDs")
    for case in cases:
        if case.reset_input is None:
            continue
        if start_schema is None:
            raise SemanticsContractError("reset_input requires a public start schema")
        try:
            validate_instance(case.reset_input, start_schema, role=f"start {case.case_id!r}")
        except SchemaError as exc:
            raise SemanticsContractError(str(exc)) from exc


def start_case_from_document(value: Any) -> StartCase:
    document = _exact(value, {"case_id", "reset_input", "regime_tags"}, "StartCase")
    return StartCase(
        _string(document["case_id"], "case_id"),
        _optional_object(document["reset_input"], "reset_input"),
        _string_tuple(document["regime_tags"], "regime_tags"),
    )


def capability_from_document(value: Any) -> CapabilitySpec:
    keys = {
        "capability_id",
        "requirement_ids",
        "workflow_ids",
        "composition_rules",
        "actor_role",
        "task_kind",
        "intent_label",
        "protected_binding_schema",
        "public_descriptor_schema",
        "facets",
        "conditions",
        "answer_fields",
        "supported_goal_kinds",
        "rendering",
    }
    document = _exact(value, keys, "CapabilitySpec")
    return CapabilitySpec(
        capability_id=_string(document["capability_id"], "capability_id"),
        requirement_ids=_string_tuple(document["requirement_ids"], "requirement_ids"),
        workflow_ids=_string_tuple(document["workflow_ids"], "workflow_ids"),
        composition_rules=tuple(
            _composition(item)
            for item in _array(document["composition_rules"], "composition_rules")
        ),
        actor_role=_string(document["actor_role"], "actor_role"),
        task_kind=cast(TaskKind, _string(document["task_kind"], "task_kind")),
        intent_label=_string(document["intent_label"], "intent_label"),
        protected_binding_schema=_object(
            document["protected_binding_schema"], "protected_binding_schema"
        ),
        public_descriptor_schema=_object(
            document["public_descriptor_schema"], "public_descriptor_schema"
        ),
        facets=tuple(_facet(item) for item in _array(document["facets"], "facets")),
        conditions=tuple(_condition(item) for item in _array(document["conditions"], "conditions")),
        answer_fields=tuple(
            _answer_field(item) for item in _array(document["answer_fields"], "answer_fields")
        ),
        supported_goal_kinds=cast(
            tuple[GoalKind, ...],
            _string_tuple(document["supported_goal_kinds"], "supported_goal_kinds"),
        ),
        rendering=_rendering(document["rendering"]),
    )


def binding_from_document(value: Any) -> BindingCandidate:
    document = _exact(
        value,
        {
            "semantic_key",
            "eligible",
            "reason_codes",
            "protected_binding",
            "public_descriptor",
            "facets",
            "public_sources",
        },
        "BindingCandidate",
    )
    eligible = document["eligible"]
    if not isinstance(eligible, bool):
        raise SemanticsContractError("BindingCandidate eligible must be boolean")
    return BindingCandidate(
        _string(document["semantic_key"], "semantic_key"),
        eligible,
        _string_tuple(document["reason_codes"], "reason_codes"),
        _object(document["protected_binding"], "protected_binding"),
        _object(document["public_descriptor"], "public_descriptor"),
        _object(document["facets"], "facets"),
        tuple(
            _public_field_source(item)
            for item in _array(document["public_sources"], "public_sources")
        ),
    )


def trace_event_from_document(value: Any) -> TraceEvent:
    document = _exact(
        value,
        {"seq", "tool_name", "arguments", "observation"},
        "TraceEvent",
    )
    seq = document["seq"]
    if not isinstance(seq, int) or isinstance(seq, bool):
        raise SemanticsContractError("TraceEvent seq must be integer")
    return TraceEvent(
        seq,
        _string(document["tool_name"], "tool_name"),
        _object(document["arguments"], "arguments"),
        _object(document["observation"], "observation"),
    )


def atom_result_from_document(value: Any) -> AtomCheckResult:
    keys = {
        "initially_satisfied",
        "satisfied",
        "required_effects_ok",
        "collateral_ok",
        "answer_ok",
        "process_ok",
        "report_values",
        "failure_codes",
    }
    document = _exact(value, keys, "AtomCheckResult")
    return AtomCheckResult(
        _boolean(document["initially_satisfied"], "initially_satisfied"),
        _boolean(document["satisfied"], "satisfied"),
        _boolean(document["required_effects_ok"], "required_effects_ok"),
        _boolean(document["collateral_ok"], "collateral_ok"),
        _optional_boolean(document["answer_ok"], "answer_ok"),
        _optional_boolean(document["process_ok"], "process_ok"),
        _object(document["report_values"], "report_values"),
        _string_tuple(document["failure_codes"], "failure_codes"),
    )


def condition_result_from_document(value: Any) -> ConditionCheckResult:
    document = _exact(value, {"status", "report_values", "failure_codes"}, "ConditionCheckResult")
    return ConditionCheckResult(
        cast(ConditionStatus, _string(document["status"], "status")),
        _object(document["report_values"], "report_values"),
        _string_tuple(document["failure_codes"], "failure_codes"),
    )


def _answer_field(value: Any) -> AnswerFieldSpec:
    document = _exact(
        value,
        {"field_id", "schema", "public_label", "public_source"},
        "AnswerFieldSpec",
    )
    return AnswerFieldSpec(
        _string(document["field_id"], "field_id"),
        _object(document["schema"], "schema"),
        _string(document["public_label"], "public_label"),
        _public_value_source(document["public_source"]),
    )


def _facet(value: Any) -> FacetSpec:
    keys = {
        "name",
        "public_label",
        "value_schema",
        "allowed_operators",
    }
    document = _exact(value, keys, "FacetSpec")
    return FacetSpec(
        _string(document["name"], "name"),
        _string(document["public_label"], "public_label"),
        _object(document["value_schema"], "value_schema"),
        cast(
            tuple[FacetOperator, ...],
            _string_tuple(document["allowed_operators"], "allowed_operators"),
        ),
    )


def _composition(value: Any) -> CompositionRule:
    document = _exact(
        value,
        {"rule_id", "workflow_id", "kind", "capability_ids", "max_occurrences"},
        "CompositionRule",
    )
    maximum = document["max_occurrences"]
    if not isinstance(maximum, int) or isinstance(maximum, bool):
        raise SemanticsContractError("CompositionRule max_occurrences must be integer")
    return CompositionRule(
        _string(document["rule_id"], "rule_id"),
        _string(document["workflow_id"], "workflow_id"),
        cast(Literal["all"], _string(document["kind"], "kind")),
        _string_tuple(document["capability_ids"], "capability_ids"),
        maximum,
    )


def _condition(value: Any) -> ConditionSpec:
    keys = {
        "condition_id",
        "public_label",
        "binding_scope",
        "true_capability_ids",
        "false_capability_ids",
        "report_field",
        "public_source",
    }
    document = _exact(value, keys, "ConditionSpec")
    report = document["report_field"]
    return ConditionSpec(
        _string(document["condition_id"], "condition_id"),
        _string(document["public_label"], "public_label"),
        cast(BindingScope, _string(document["binding_scope"], "binding_scope")),
        _string_tuple(document["true_capability_ids"], "true_capability_ids"),
        _string_tuple(document["false_capability_ids"], "false_capability_ids"),
        None if report is None else _answer_field(report),
        _public_value_source(document["public_source"]),
    )


def _rendering(value: Any) -> RenderingSpec:
    document = _exact(value, {"imperative", "target_noun", "answer_phrase"}, "RenderingSpec")
    phrase = document["answer_phrase"]
    if phrase is not None and not isinstance(phrase, str):
        raise SemanticsContractError("RenderingSpec answer_phrase must be string or null")
    return RenderingSpec(
        _string(document["imperative"], "imperative"),
        _string(document["target_noun"], "target_noun"),
        phrase,
    )


def _public_value_source(value: Any) -> PublicValueSource:
    document = _exact(
        value,
        {"kind", "tool_name", "json_pointer", "value"},
        "PublicValueSource",
    )
    tool_name = document["tool_name"]
    pointer = document["json_pointer"]
    if tool_name is not None and not isinstance(tool_name, str):
        raise SemanticsContractError("PublicValueSource tool_name must be string or null")
    if pointer is not None and not isinstance(pointer, str):
        raise SemanticsContractError("PublicValueSource json_pointer must be string or null")
    return PublicValueSource(
        cast(PublicValueKind, _string(document["kind"], "public source kind")),
        tool_name,
        pointer,
        _json(document["value"]),
    )


def _public_field_source(value: Any) -> PublicFieldSource:
    document = _exact(
        value,
        {"field_pointer", "source"},
        "PublicFieldSource",
    )
    return PublicFieldSource(
        _string(document["field_pointer"], "field_pointer"),
        _public_value_source(document["source"]),
    )


def _exact(value: Any, keys: set[str], role: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        actual = sorted(value) if isinstance(value, dict) else type(value).__name__
        raise SemanticsContractError(f"{role} must have exactly {sorted(keys)}, got {actual}")
    return cast(dict[str, Any], value)


def _array(value: Any, role: str) -> list[Any]:
    if not isinstance(value, list):
        raise SemanticsContractError(f"{role} must be an array")
    return value


def _string(value: Any, role: str) -> str:
    if not isinstance(value, str):
        raise SemanticsContractError(f"{role} must be a string")
    return value


def _string_tuple(value: Any, role: str) -> tuple[str, ...]:
    values = _array(value, role)
    if any(not isinstance(item, str) for item in values):
        raise SemanticsContractError(f"{role} must contain only strings")
    return tuple(cast(list[str], values))


def _object(value: Any, role: str) -> JSONObject:
    if not is_json_object(value):
        raise SemanticsContractError(f"{role} must be a JSON object")
    return cast(JSONObject, value)


def _optional_object(value: Any, role: str) -> JSONObject | None:
    return None if value is None else _object(value, role)


def _boolean(value: Any, role: str) -> bool:
    if not isinstance(value, bool):
        raise SemanticsContractError(f"{role} must be boolean")
    return value


def _optional_boolean(value: Any, role: str) -> bool | None:
    return None if value is None else _boolean(value, role)


def _schema(value: JSONObject, role: str) -> None:
    try:
        validate_schema_document(value, role=role)
    except SchemaError as exc:
        raise SemanticsContractError(str(exc)) from exc


def _object_schema(value: JSONObject, role: str) -> None:
    try:
        require_object_root(value, role=role)
    except SchemaError as exc:
        raise SemanticsContractError(str(exc)) from exc


def _identifier(value: str, role: str) -> None:
    if not value or value.strip() != value or any(character.isspace() for character in value):
        raise SemanticsContractError(f"{role} must be a non-empty whitespace-free string")


def _text(value: str, role: str) -> None:
    if not value.strip():
        raise SemanticsContractError(f"{role} must be non-empty")


def _pointer(value: str, role: str) -> None:
    if value and not value.startswith("/"):
        raise SemanticsContractError(f"{role} must be an RFC 6901 pointer")


def _unique(values: tuple[Any, ...], role: str) -> None:
    if len(values) != len(set(values)):
        raise SemanticsContractError(f"{role} must be unique")


def _unique_by(values: tuple[Any, ...], attribute: str, role: str) -> None:
    _unique(tuple(getattr(value, attribute) for value in values), role)


def _public_leaf_pointers(public_descriptor: JSONObject, facets: JSONObject) -> set[str]:
    pointers: set[str] = set()

    def visit(value: JSONValue, path: str) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                escaped = key.replace("~", "~0").replace("/", "~1")
                visit(child, f"{path}/{escaped}")
            return
        if isinstance(value, list):
            for index, child in enumerate(value):
                visit(child, f"{path}/{index}")
            return
        pointers.add(path)

    visit(_json(public_descriptor), "/public_descriptor")
    visit(_json(facets), "/facets")
    return pointers


def _resolve_public_pointer(
    public_descriptor: JSONObject,
    facets: JSONObject,
    pointer: str,
) -> JSONValue:
    current: JSONValue = {
        "public_descriptor": _json(public_descriptor),
        "facets": _json(facets),
    }
    for raw_token in pointer.removeprefix("/").split("/"):
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict) and token in current:
            current = current[token]
            continue
        if isinstance(current, list) and token.isdigit() and int(token) < len(current):
            current = current[int(token)]
            continue
        raise SemanticsContractError(f"public source pointer {pointer!r} does not resolve")
    return current


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
