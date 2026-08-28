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
FacetVisibility = Literal["task_literal", "reset", "public_tool"]
ConditionVisibility = Literal["reset", "public_tool"]
BindingScope = Literal["world", "selected_binding"]
_FACET_OPERATORS = frozenset({"eq", "neq", "lt", "lte", "gt", "gte", "min", "max"})
_FACET_VISIBILITIES = frozenset({"task_literal", "reset", "public_tool"})
_CONDITION_VISIBILITIES = frozenset({"reset", "public_tool"})
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
class AnswerFieldSpec:
    field_id: str
    schema: JSONObject
    public_label: str

    def __post_init__(self) -> None:
        _identifier(self.field_id, "answer field_id")
        _schema(self.schema, f"answer field {self.field_id!r}")
        _text(self.public_label, "answer field public_label")

    def to_document(self) -> JSONObject:
        return {
            "field_id": self.field_id,
            "schema": _json(self.schema),
            "public_label": self.public_label,
        }


@dataclass(frozen=True, slots=True)
class FacetSpec:
    name: str
    public_label: str
    value_schema: JSONObject
    allowed_operators: tuple[FacetOperator, ...]
    visibility: FacetVisibility
    tool_name: str | None = None
    output_schema_pointer: str | None = None

    def __post_init__(self) -> None:
        _identifier(self.name, "facet name")
        _text(self.public_label, "facet public_label")
        _schema(self.value_schema, f"facet {self.name!r}")
        if not self.allowed_operators:
            raise SemanticsContractError("facet allowed_operators must not be empty")
        _unique(self.allowed_operators, "facet allowed_operators")
        if any(operator not in _FACET_OPERATORS for operator in self.allowed_operators):
            raise SemanticsContractError("facet contains an unsupported operator")
        if self.visibility not in _FACET_VISIBILITIES:
            raise SemanticsContractError("facet visibility is invalid")
        _tool_projection(
            visibility=self.visibility,
            tool_name=self.tool_name,
            pointer=self.output_schema_pointer,
            role="facet",
        )

    def to_document(self) -> JSONObject:
        return {
            "name": self.name,
            "public_label": self.public_label,
            "value_schema": _json(self.value_schema),
            "allowed_operators": list(self.allowed_operators),
            "visibility": self.visibility,
            "tool_name": self.tool_name,
            "output_schema_pointer": self.output_schema_pointer,
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
    visibility: ConditionVisibility
    binding_scope: BindingScope
    true_capability_ids: tuple[str, ...]
    false_capability_ids: tuple[str, ...]
    report_field: AnswerFieldSpec | None
    tool_name: str | None = None
    output_schema_pointer: str | None = None

    def __post_init__(self) -> None:
        _identifier(self.condition_id, "condition_id")
        _text(self.public_label, "condition public_label")
        _unique(self.true_capability_ids, "condition true_capability_ids")
        _unique(self.false_capability_ids, "condition false_capability_ids")
        if self.visibility not in _CONDITION_VISIBILITIES:
            raise SemanticsContractError("condition visibility is invalid")
        if self.binding_scope not in _BINDING_SCOPES:
            raise SemanticsContractError("condition binding_scope is invalid")
        if (
            not self.true_capability_ids
            and not self.false_capability_ids
            and self.report_field is None
        ):
            raise SemanticsContractError("condition licenses neither a branch nor a report")
        _tool_projection(
            visibility=self.visibility,
            tool_name=self.tool_name,
            pointer=self.output_schema_pointer,
            role="condition",
        )

    def to_document(self) -> JSONObject:
        return {
            "condition_id": self.condition_id,
            "public_label": self.public_label,
            "visibility": self.visibility,
            "binding_scope": self.binding_scope,
            "true_capability_ids": list(self.true_capability_ids),
            "false_capability_ids": list(self.false_capability_ids),
            "report_field": self.report_field.to_document() if self.report_field else None,
            "tool_name": self.tool_name,
            "output_schema_pointer": self.output_schema_pointer,
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
    read_scopes: tuple[str, ...]
    write_scopes: tuple[str, ...]
    supported_goal_kinds: tuple[GoalKind, ...]
    rendering: RenderingSpec

    def __post_init__(self) -> None:
        _identifier(self.capability_id, "capability_id")
        if not self.requirement_ids or not self.workflow_ids:
            raise SemanticsContractError("capability must be Requirement- and workflow-anchored")
        for values, role in (
            (self.requirement_ids, "requirement_ids"),
            (self.workflow_ids, "workflow_ids"),
            (self.read_scopes, "read_scopes"),
            (self.write_scopes, "write_scopes"),
            (self.supported_goal_kinds, "supported_goal_kinds"),
        ):
            _unique(values, role)
        _text(self.actor_role, "actor_role")
        _text(self.intent_label, "intent_label")
        if self.task_kind not in _TASK_KINDS:
            raise SemanticsContractError("capability task_kind is invalid")
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
            "read_scopes": list(self.read_scopes),
            "write_scopes": list(self.write_scopes),
            "supported_goal_kinds": list(self.supported_goal_kinds),
            "rendering": self.rendering.to_document(),
        }


@dataclass(frozen=True, slots=True)
class BindingCandidate:
    semantic_key: str
    eligible: bool
    reason_codes: tuple[str, ...]
    protected_binding: JSONObject
    public_descriptor: JSONObject
    facets: JSONObject

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
class AtomCheckRequest:
    capability_id: str
    before_facts: JSONValue
    after_facts: JSONValue
    protected_binding: JSONObject
    trace_projection: tuple[TraceEvent, ...]
    final_answer: JSONValue | None

    def to_document(self) -> JSONObject:
        return {
            "capability_id": self.capability_id,
            "before_facts": _json(self.before_facts),
            "after_facts": _json(self.after_facts),
            "protected_binding": _json(self.protected_binding),
            "trace_projection": [item.to_document() for item in self.trace_projection],
            "final_answer": _json(self.final_answer),
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
        "read_scopes",
        "write_scopes",
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
        read_scopes=_string_tuple(document["read_scopes"], "read_scopes"),
        write_scopes=_string_tuple(document["write_scopes"], "write_scopes"),
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
    document = _exact(value, {"field_id", "schema", "public_label"}, "AnswerFieldSpec")
    return AnswerFieldSpec(
        _string(document["field_id"], "field_id"),
        _object(document["schema"], "schema"),
        _string(document["public_label"], "public_label"),
    )


def _facet(value: Any) -> FacetSpec:
    keys = {
        "name",
        "public_label",
        "value_schema",
        "allowed_operators",
        "visibility",
        "tool_name",
        "output_schema_pointer",
    }
    document = _exact(value, keys, "FacetSpec")
    tool_name = document["tool_name"]
    pointer = document["output_schema_pointer"]
    if tool_name is not None and not isinstance(tool_name, str):
        raise SemanticsContractError("FacetSpec tool_name must be string or null")
    if pointer is not None and not isinstance(pointer, str):
        raise SemanticsContractError("FacetSpec output_schema_pointer must be string or null")
    return FacetSpec(
        _string(document["name"], "name"),
        _string(document["public_label"], "public_label"),
        _object(document["value_schema"], "value_schema"),
        cast(
            tuple[FacetOperator, ...],
            _string_tuple(document["allowed_operators"], "allowed_operators"),
        ),
        cast(FacetVisibility, _string(document["visibility"], "visibility")),
        tool_name,
        pointer,
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
        "visibility",
        "binding_scope",
        "true_capability_ids",
        "false_capability_ids",
        "report_field",
        "tool_name",
        "output_schema_pointer",
    }
    document = _exact(value, keys, "ConditionSpec")
    report = document["report_field"]
    tool_name = document["tool_name"]
    pointer = document["output_schema_pointer"]
    if tool_name is not None and not isinstance(tool_name, str):
        raise SemanticsContractError("ConditionSpec tool_name must be string or null")
    if pointer is not None and not isinstance(pointer, str):
        raise SemanticsContractError("ConditionSpec output_schema_pointer must be string or null")
    return ConditionSpec(
        _string(document["condition_id"], "condition_id"),
        _string(document["public_label"], "public_label"),
        cast(ConditionVisibility, _string(document["visibility"], "visibility")),
        cast(BindingScope, _string(document["binding_scope"], "binding_scope")),
        _string_tuple(document["true_capability_ids"], "true_capability_ids"),
        _string_tuple(document["false_capability_ids"], "false_capability_ids"),
        None if report is None else _answer_field(report),
        tool_name,
        pointer,
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


def _tool_projection(
    *,
    visibility: str,
    tool_name: str | None,
    pointer: str | None,
    role: str,
) -> None:
    if visibility == "public_tool":
        if tool_name is None:
            raise SemanticsContractError(f"public_tool {role} requires tool_name")
        _identifier(tool_name, f"public_tool {role} tool_name")
        if pointer is None:
            raise SemanticsContractError(f"public_tool {role} requires output_schema_pointer")
        _pointer(pointer, f"public_tool {role} output_schema_pointer")
    elif tool_name is not None or pointer is not None:
        raise SemanticsContractError(f"non-tool {role} must not declare tool provenance")


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
