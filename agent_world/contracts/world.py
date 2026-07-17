"""Typed semantic source of truth for generated programmatic worlds."""

from __future__ import annotations

import math
from typing import Annotated, Literal

from jsonschema import Draft202012Validator, SchemaError  # type: ignore[import-untyped]
from pydantic import Field, JsonValue, model_validator

from .base import ArtifactRef, Identifier, NonEmptyStr, V2Contract


class ActorBoundary(V2Contract):
    actor: Identifier
    authorities: Annotated[tuple[Identifier, ...], Field(min_length=1)]
    visibility: tuple[Identifier, ...] = ()


class WorldBoundary(V2Contract):
    primary_domain: Identifier
    actors_and_authority: Annotated[tuple[ActorBoundary, ...], Field(min_length=1)]
    systems_of_record: Annotated[tuple[Identifier, ...], Field(min_length=1)]
    core_resources: Annotated[tuple[Identifier, ...], Field(min_length=1)]
    transition_authorities: Annotated[tuple[Identifier, ...], Field(min_length=1)]
    tool_namespaces: Annotated[tuple[Identifier, ...], Field(min_length=1)]
    core_invariants: Annotated[tuple[NonEmptyStr, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def validate_boundary_sets(self) -> WorldBoundary:
        actors = [item.actor for item in self.actors_and_authority]
        if len(set(actors)) != len(actors):
            raise ValueError("WorldBoundary actor ids must be unique")
        for actor in self.actors_and_authority:
            if len(set(actor.authorities)) != len(actor.authorities):
                raise ValueError(f"actor {actor.actor} authorities must be unique")
        for label, values in (
            ("systems_of_record", self.systems_of_record),
            ("core_resources", self.core_resources),
            ("transition_authorities", self.transition_authorities),
            ("tool_namespaces", self.tool_namespaces),
            ("core_invariants", self.core_invariants),
        ):
            if len(set(values)) != len(values):
                raise ValueError(f"WorldBoundary {label} values must be unique")
        return self


type RuleValueType = Literal["null", "boolean", "number", "string", "array", "object", "any"]
type RuleValueSource = Literal[
    "actor",
    "pre_state",
    "post_state",
    "args",
    "tool_result",
    "error",
    "observation",
    "events",
    "reset_config",
    "task_goal",
    "seed",
    "terminated",
    "truncated",
]
type RuleFamily = Literal[
    "initial_state",
    "invariant",
    "precondition",
    "transition",
    "postcondition",
    "error_condition",
    "permission",
    "task_success",
    "task_failure",
    "task_terminal",
    "sampling",
]
type RuleOrdering = Literal["number", "date", "date-time"]


class RuleConstant(V2Contract):
    """One JSON constant in the closed rule language."""

    kind: Literal["constant"] = "constant"
    value_type: RuleValueType
    value: JsonValue

    @model_validator(mode="after")
    def validate_declared_type(self) -> RuleConstant:
        if self.value_type == "any":
            raise ValueError("RuleConstant value_type cannot be any")
        if _json_value_type(self.value) != self.value_type:
            raise ValueError("RuleConstant value does not match value_type")
        if isinstance(self.value, float) and not math.isfinite(self.value):
            raise ValueError("RuleConstant numbers must be finite")
        return self


class RuleValueRef(V2Contract):
    """A typed reference into framework-owned execution context."""

    kind: Literal["reference"] = "reference"
    source: RuleValueSource
    pointer: str = ""
    value_type: RuleValueType

    @model_validator(mode="after")
    def validate_pointer(self) -> RuleValueRef:
        _validate_json_pointer(self.pointer)
        return self


type RuleAtom = Annotated[RuleConstant | RuleValueRef, Field(discriminator="kind")]


class RuleArithmetic(V2Contract):
    """One bounded arithmetic operation over two numeric atoms.

    Arithmetic is deliberately non-recursive.  This keeps evaluation cost fixed,
    makes the generated JSON Schema finite, and rules out expression-language
    escape hatches.
    """

    kind: Literal["arithmetic"] = "arithmetic"
    operator: Literal["add", "subtract", "multiply", "divide", "modulo"]
    left: RuleAtom
    right: RuleAtom
    value_type: Literal["number"] = "number"

    @model_validator(mode="after")
    def validate_numeric_atoms(self) -> RuleArithmetic:
        if self.left.value_type != "number" or self.right.value_type != "number":
            raise ValueError("RuleArithmetic operands must declare number value_type")
        if (
            self.operator in {"divide", "modulo"}
            and isinstance(self.right, RuleConstant)
            and self.right.value == 0
        ):
            raise ValueError("RuleArithmetic divisor cannot be the constant zero")
        return self


type RuleTerm = Annotated[
    RuleConstant | RuleValueRef | RuleArithmetic,
    Field(discriminator="kind"),
]


class RuleClause(V2Contract):
    """One finite comparison; Rule combines clauses with all/any boolean logic."""

    clause_id: Identifier
    left: RuleTerm
    operator: Literal[
        "exists",
        "not_exists",
        "equal",
        "not_equal",
        "greater_than",
        "greater_or_equal",
        "less_than",
        "less_or_equal",
        "contains",
        "not_contains",
        "schema_valid",
    ]
    right: RuleTerm | None = None
    json_schema: dict[str, JsonValue] | None = None
    ordering: RuleOrdering | None = None
    negate: bool = False

    @model_validator(mode="after")
    def validate_operator_shape(self) -> RuleClause:
        if self.operator in {"exists", "not_exists"}:
            if self.right is not None or self.json_schema is not None or self.ordering is not None:
                raise ValueError(f"{self.operator} forbids right, json_schema, and ordering")
            return self
        if self.operator == "schema_valid":
            if self.right is not None or self.json_schema is None or self.ordering is not None:
                raise ValueError("schema_valid requires json_schema and forbids right and ordering")
            if not self.json_schema:
                raise ValueError("schema_valid forbids the tautological empty JSON Schema")
            _check_json_schema(self.json_schema, f"rule clause {self.clause_id}")
            return self
        if self.right is None or self.json_schema is not None:
            raise ValueError(f"{self.operator} requires right and forbids json_schema")
        ordered = self.operator in {
            "greater_than",
            "greater_or_equal",
            "less_than",
            "less_or_equal",
        }
        if ordered:
            if self.ordering is None:
                if self.left.value_type in {"number", "any"} and self.right.value_type in {
                    "number",
                    "any",
                }:
                    # Deterministic migration for already-compiled numeric Rule IR.
                    object.__setattr__(self, "ordering", "number")
                else:
                    raise ValueError(f"{self.operator} requires an explicit ordering")
            assert self.ordering is not None
            allowed_types = {"number", "any"} if self.ordering == "number" else {"string", "any"}
            if (
                self.left.value_type not in allowed_types
                or self.right.value_type not in allowed_types
            ):
                raise ValueError(f"{self.operator} terms do not match {self.ordering} ordering")
        elif self.ordering is not None:
            raise ValueError(f"{self.operator} forbids ordering")
        if self.operator in {"contains", "not_contains"} and self.left.value_type not in {
            "array",
            "object",
            "string",
            "any",
        }:
            raise ValueError(f"{self.operator} requires a container on the left")
        return self


class Rule(V2Contract):
    """Closed, data-only executable rule owned by the framework.

    There is intentionally no source string, CEL/JSONLogic/Python language tag,
    function call, template, or unbounded recursive expression.
    """

    rule_id: Identifier
    family: RuleFamily
    description: NonEmptyStr
    boolean_operator: Literal["all", "any"]
    clauses: Annotated[tuple[RuleClause, ...], Field(min_length=1, max_length=64)]
    case_sensitivity: Literal["positive_only", "positive_and_negative"]
    evidence_claim_ids: tuple[Identifier, ...] = ()

    @model_validator(mode="after")
    def validate_clauses(self) -> Rule:
        clause_ids = [clause.clause_id for clause in self.clauses]
        if len(set(clause_ids)) != len(clause_ids):
            raise ValueError("Rule clause_id values must be unique")
        return self


class StateEntitySchema(V2Contract):
    entity: Identifier
    json_schema: dict[str, JsonValue]
    primary_key_fields: Annotated[tuple[Identifier, ...], Field(min_length=1)]
    mutable_fields: tuple[Identifier, ...] = ()
    lifecycle_states: tuple[Identifier, ...] = ()
    evidence_claim_ids: tuple[Identifier, ...] = ()

    @model_validator(mode="after")
    def validate_entity_schema(self) -> StateEntitySchema:
        _check_json_schema(self.json_schema, f"state entity {self.entity}")
        properties = self.json_schema.get("properties")
        if self.json_schema.get("type") != "object" or not isinstance(properties, dict):
            raise ValueError(f"state entity {self.entity} must be an object JSON Schema")
        fields = set(properties)
        unknown_primary = set(self.primary_key_fields) - fields
        unknown_mutable = set(self.mutable_fields) - fields
        if unknown_primary:
            raise ValueError(
                f"state entity {self.entity} primary keys are absent from schema: "
                f"{sorted(unknown_primary)}"
            )
        if unknown_mutable:
            raise ValueError(
                f"state entity {self.entity} mutable fields are absent from schema: "
                f"{sorted(unknown_mutable)}"
            )
        return self


class StateSchema(V2Contract):
    entities: Annotated[tuple[StateEntitySchema, ...], Field(min_length=1)]
    root_state_schema: dict[str, JsonValue]
    initial_state_constraints: tuple[Rule, ...] = ()

    @model_validator(mode="after")
    def unique_entities(self) -> StateSchema:
        _check_json_schema(self.root_state_schema, "root state")
        names = [entity.entity for entity in self.entities]
        if len(set(names)) != len(names):
            raise ValueError("state entity names must be unique")
        goal_dependent_initial = {
            rule.rule_id
            for rule in self.initial_state_constraints
            if "task_goal" in _rule_sources(rule)
        }
        if goal_dependent_initial:
            raise ValueError(
                "world initial-state constraints cannot read evaluator-only task_goal: "
                f"{sorted(goal_dependent_initial)}"
            )
        return self


class ToolSurface(V2Contract):
    tool_id: Identifier
    namespace: Identifier
    name: Identifier
    description: NonEmptyStr
    transport: Literal["runtime", "mcp", "http", "cli", "python", "database"]
    input_schema: dict[str, JsonValue]
    output_schema: dict[str, JsonValue]
    observation_schema: dict[str, JsonValue]

    @model_validator(mode="after")
    def validate_surface(self) -> ToolSurface:
        if self.tool_id != f"{self.namespace}.{self.name}":
            raise ValueError("tool_id must equal '<namespace>.<name>'")
        _check_json_schema(self.input_schema, f"tool {self.tool_id} input")
        _check_json_schema(self.output_schema, f"tool {self.tool_id} output")
        _check_json_schema(self.observation_schema, f"tool {self.tool_id} observation")
        return self


class ToolError(V2Contract):
    error_code: Identifier
    when: Rule
    observation: NonEmptyStr
    state_effect: Literal["none", "partial", "rolled_back", "unknown"]
    retryable: bool
    evidence_claim_ids: tuple[Identifier, ...] = ()


class PermissionRule(V2Contract):
    permission_id: Identifier
    allowed_actors: Annotated[tuple[Identifier, ...], Field(min_length=1)]
    required_scopes_by_actor: dict[Identifier, tuple[Identifier, ...]]
    condition: Rule | None = None
    denied_observation: NonEmptyStr

    @model_validator(mode="after")
    def validate_actor_scopes(self) -> PermissionRule:
        if set(self.required_scopes_by_actor) != set(self.allowed_actors):
            raise ValueError("required_scopes_by_actor must cover exactly every allowed actor")
        for actor, scopes in self.required_scopes_by_actor.items():
            if len(set(scopes)) != len(scopes):
                raise ValueError(f"permission scopes for actor {actor} must be unique")
        return self


class ObservationSemantics(V2Contract):
    visible_fields_by_actor: dict[Identifier, tuple[Identifier, ...]]
    redacted_fields_by_actor: dict[Identifier, tuple[Identifier, ...]]
    consistency: Literal["strong", "read_after_write", "eventual", "snapshot"] = "strong"
    staleness_bound_seconds: Annotated[float, Field(ge=0)] | None = None

    @model_validator(mode="after")
    def validate_actor_projections(self) -> ObservationSemantics:
        if set(self.redacted_fields_by_actor) != set(self.visible_fields_by_actor):
            raise ValueError("redacted_fields_by_actor must cover exactly every observation actor")
        for actor, visible in self.visible_fields_by_actor.items():
            redacted = self.redacted_fields_by_actor[actor]
            if len(set(visible)) != len(visible):
                raise ValueError(f"visible observation fields for actor {actor} must be unique")
            if len(set(redacted)) != len(redacted):
                raise ValueError(f"redacted observation fields for actor {actor} must be unique")
            if set(visible) & set(redacted):
                raise ValueError(
                    f"observation fields cannot be visible and redacted for actor {actor}"
                )
        return self


class IdempotencySemantics(V2Contract):
    mode: Literal["not_supported", "natural", "idempotency_key"]
    key_field: Identifier | None = None
    retention_seconds: Annotated[float, Field(gt=0)] | None = None
    duplicate_observation: NonEmptyStr

    @model_validator(mode="after")
    def validate_key(self) -> IdempotencySemantics:
        if self.mode == "idempotency_key" and self.key_field is None:
            raise ValueError("idempotency_key mode requires key_field")
        if self.mode != "idempotency_key" and self.key_field is not None:
            raise ValueError("key_field is only valid for idempotency_key mode")
        return self


class RetrySemantics(V2Contract):
    maximum_attempts: Annotated[int, Field(ge=1)]
    backoff: Literal["none", "fixed", "exponential"] = "none"
    retryable_error_codes: tuple[Identifier, ...] = ()
    requires_same_idempotency_key: bool = True


class TimeoutSemantics(V2Contract):
    operation_timeout_seconds: Annotated[float, Field(gt=0)]
    timeout_error_code: Identifier
    cancellation_effect: Literal["no_effect", "may_commit", "rolled_back", "unknown"]


class TransactionSemantics(V2Contract):
    atomicity: Literal["atomic", "best_effort", "saga", "none"]
    commit_point: NonEmptyStr
    partial_commit_observable: bool


class RollbackSemantics(V2Contract):
    supported: bool
    rollback_trigger_codes: tuple[Identifier, ...] = ()
    compensation_tools: tuple[Identifier, ...] = ()
    guarantees: NonEmptyStr


class ConcurrencySemantics(V2Contract):
    isolation: Literal[
        "serial",
        "serializable",
        "snapshot",
        "read_committed",
        "optimistic",
        "last_write_wins",
    ]
    conflict_detection: NonEmptyStr
    conflict_error_code: Identifier | None = None
    ordering_guarantee: NonEmptyStr


class ToolSemantics(V2Contract):
    preconditions: tuple[Rule, ...] = ()
    transition: Annotated[tuple[Rule, ...], Field(min_length=1)]
    postconditions: tuple[Rule, ...] = ()
    errors: tuple[ToolError, ...] = ()
    permission: PermissionRule
    observation: ObservationSemantics
    idempotency: IdempotencySemantics
    retry: RetrySemantics
    timeout: TimeoutSemantics
    transaction: TransactionSemantics
    rollback: RollbackSemantics
    concurrency: ConcurrencySemantics

    @model_validator(mode="after")
    def validate_error_relations(self) -> ToolSemantics:
        _require_rule_family(self.preconditions, "precondition", "tool preconditions")
        _require_rule_family(self.transition, "transition", "tool transition")
        _require_rule_family(self.postconditions, "postcondition", "tool postconditions")
        for error in self.errors:
            _require_rule_family((error.when,), "error_condition", "tool error condition")
        if self.permission.condition is not None:
            _require_rule_family(
                (self.permission.condition,), "permission", "tool permission condition"
            )
        error_codes = [item.error_code for item in self.errors]
        if len(set(error_codes)) != len(error_codes):
            raise ValueError("tool error codes must be unique")
        known = set(error_codes)
        unknown_retry = set(self.retry.retryable_error_codes) - known
        if unknown_retry:
            raise ValueError(f"retry semantics references unknown errors: {sorted(unknown_retry)}")
        if self.timeout.timeout_error_code not in known:
            raise ValueError("timeout_error_code must be declared in tool errors")
        return self


class ToolContract(V2Contract):
    surface: ToolSurface
    semantics: ToolSemantics
    evidence_claim_ids: Annotated[tuple[Identifier, ...], Field(min_length=1)]


class FidelityStatement(V2Contract):
    statement_id: Identifier
    claim: NonEmptyStr
    level: Literal["faithful", "bounded_approximation", "synthetic_policy"]
    known_divergence: NonEmptyStr | None = None
    evidence_claim_ids: tuple[Identifier, ...] = ()


class WorldSpec(V2Contract):
    world_spec_id: Identifier
    revision: Annotated[int, Field(ge=1)]
    boundary: WorldBoundary
    state: StateSchema
    tools: Annotated[tuple[ToolContract, ...], Field(min_length=1)]
    invariants: Annotated[tuple[Rule, ...], Field(min_length=1, max_length=512)]
    task_dimensions: Annotated[tuple[Identifier, ...], Field(min_length=1)]
    fidelity: Annotated[tuple[FidelityStatement, ...], Field(min_length=1)]
    unknowns: tuple[NonEmptyStr, ...] = ()
    evidence_graph_ref: ArtifactRef
    coverage_map_ref: ArtifactRef

    @model_validator(mode="after")
    def validate_world_references(self) -> WorldSpec:
        _require_rule_family(self.invariants, "invariant", "world invariants")
        _require_rule_family(
            self.state.initial_state_constraints,
            "initial_state",
            "initial state constraints",
        )
        goal_dependent_initial = {
            rule.rule_id
            for rule in self.state.initial_state_constraints
            if "task_goal" in _rule_sources(rule)
        }
        if goal_dependent_initial:
            raise ValueError(
                "world initial-state constraints cannot read evaluator-only task_goal: "
                f"{sorted(goal_dependent_initial)}"
            )
        world_rules = [*self.invariants, *self.state.initial_state_constraints]
        for tool in self.tools:
            semantics = tool.semantics
            world_rules.extend(semantics.preconditions)
            world_rules.extend(semantics.transition)
            world_rules.extend(semantics.postconditions)
            world_rules.extend(error.when for error in semantics.errors)
            if semantics.permission.condition is not None:
                world_rules.append(semantics.permission.condition)
        goal_dependent_world = {
            rule.rule_id for rule in world_rules if "task_goal" in _rule_sources(rule)
        }
        if goal_dependent_world:
            raise ValueError(
                "WorldSpec behavior rules cannot read evaluator-only task_goal: "
                f"{sorted(goal_dependent_world)}"
            )
        tool_ids = [tool.surface.tool_id for tool in self.tools]
        if len(set(tool_ids)) != len(tool_ids):
            raise ValueError("tool_id values must be unique")
        namespaces = set(self.boundary.tool_namespaces)
        undeclared = {tool.surface.namespace for tool in self.tools} - namespaces
        if undeclared:
            raise ValueError(f"tool namespaces are absent from WorldBoundary: {sorted(undeclared)}")
        actors = {item.actor for item in self.boundary.actors_and_authority}
        authorities_by_actor = {
            item.actor: set(item.authorities) for item in self.boundary.actors_and_authority
        }
        root_properties = self.state.root_state_schema.get("properties")
        if self.state.root_state_schema.get("type") != "object" or not isinstance(
            root_properties, dict
        ):
            raise ValueError("root_state_schema must be an object JSON Schema with properties")
        for boundary_actor in self.boundary.actors_and_authority:
            if len(set(boundary_actor.visibility)) != len(boundary_actor.visibility):
                raise ValueError(
                    f"actor {boundary_actor.actor} reset visibility fields must be unique"
                )
            unknown_reset_fields = set(boundary_actor.visibility) - set(root_properties)
            if unknown_reset_fields:
                raise ValueError(
                    f"actor {boundary_actor.actor} reset visibility references unknown "
                    "root fields: "
                    f"{sorted(unknown_reset_fields)}"
                )
        for tool in self.tools:
            unknown_permission_actors = set(tool.semantics.permission.allowed_actors) - actors
            if unknown_permission_actors:
                raise ValueError(
                    f"tool {tool.surface.tool_id} permission references unknown actors: "
                    f"{sorted(unknown_permission_actors)}"
                )
            required_by_actor = tool.semantics.permission.required_scopes_by_actor
            missing_scopes_by_actor = {
                actor: set(required_by_actor[actor]) - authorities_by_actor[actor]
                for actor in tool.semantics.permission.allowed_actors
            }
            missing_scopes_by_actor = {
                actor: scopes for actor, scopes in missing_scopes_by_actor.items() if scopes
            }
            if missing_scopes_by_actor:
                raise ValueError(
                    f"tool {tool.surface.tool_id} allowed actors lack required scopes: "
                    f"{missing_scopes_by_actor}"
                )
            permission_condition = tool.semantics.permission.condition
            if permission_condition is not None:
                invalid_permission_sources = _rule_sources(permission_condition) - {
                    "actor",
                    "pre_state",
                    "args",
                    "reset_config",
                    "seed",
                }
                if invalid_permission_sources:
                    raise ValueError(
                        f"tool {tool.surface.tool_id} permission condition reads post-execution "
                        f"sources: {sorted(invalid_permission_sources)}"
                    )
            if set(tool.semantics.permission.allowed_actors) == actors:
                if permission_condition is None:
                    raise ValueError(
                        f"tool {tool.surface.tool_id} has no executable permission denial path"
                    )
                if permission_condition.case_sensitivity != "positive_and_negative":
                    raise ValueError(
                        f"tool {tool.surface.tool_id} permission condition must require positive "
                        "and negative verification when every actor is statically allowed"
                    )
            unknown_visibility_actors = (
                set(tool.semantics.observation.visible_fields_by_actor) - actors
            )
            if unknown_visibility_actors:
                raise ValueError(
                    f"tool {tool.surface.tool_id} observation references unknown actors: "
                    f"{sorted(unknown_visibility_actors)}"
                )
            missing_visibility_actors = actors - set(
                tool.semantics.observation.visible_fields_by_actor
            )
            if missing_visibility_actors:
                raise ValueError(
                    f"tool {tool.surface.tool_id} observation omits actor projections: "
                    f"{sorted(missing_visibility_actors)}"
                )
            redaction_actors = set(tool.semantics.observation.redacted_fields_by_actor)
            if redaction_actors != actors:
                raise ValueError(
                    f"tool {tool.surface.tool_id} observation redaction must cover exactly "
                    f"every boundary actor: {sorted(actors)}"
                )
            observation_properties = tool.surface.observation_schema.get("properties")
            if tool.surface.observation_schema.get("type") != "object" or not isinstance(
                observation_properties, dict
            ):
                raise ValueError(
                    f"tool {tool.surface.tool_id} observation_schema must be an object "
                    "JSON Schema with properties"
                )
            observation_fields = set(observation_properties)
            for actor, visible_fields in tool.semantics.observation.visible_fields_by_actor.items():
                redacted_fields = tool.semantics.observation.redacted_fields_by_actor[actor]
                classified_fields = set(visible_fields) | set(redacted_fields)
                unknown_observation_fields = classified_fields - observation_fields
                if unknown_observation_fields:
                    raise ValueError(
                        f"tool {tool.surface.tool_id} observation policy for actor {actor} "
                        f"references unknown fields: {sorted(unknown_observation_fields)}"
                    )
                unclassified_observation_fields = observation_fields - classified_fields
                if unclassified_observation_fields:
                    raise ValueError(
                        f"tool {tool.surface.tool_id} observation schema has fields unclassified "
                        f"for actor {actor}: {sorted(unclassified_observation_fields)}"
                    )
            unknown_compensation = set(tool.semantics.rollback.compensation_tools) - set(tool_ids)
            if unknown_compensation:
                raise ValueError(
                    f"tool {tool.surface.tool_id} rollback references unknown tools: "
                    f"{sorted(unknown_compensation)}"
                )
        rule_ids: list[str] = [rule.rule_id for rule in self.invariants]
        rule_ids.extend(rule.rule_id for rule in self.state.initial_state_constraints)
        for tool in self.tools:
            semantics = tool.semantics
            rule_ids.extend(rule.rule_id for rule in semantics.preconditions)
            rule_ids.extend(rule.rule_id for rule in semantics.transition)
            rule_ids.extend(rule.rule_id for rule in semantics.postconditions)
            rule_ids.extend(error.when.rule_id for error in semantics.errors)
            if semantics.permission.condition is not None:
                rule_ids.append(semantics.permission.condition.rule_id)
        if len(set(rule_ids)) != len(rule_ids):
            raise ValueError("rule_id values must be unique across a WorldSpec")
        for statement in self.fidelity:
            if statement.level == "bounded_approximation" and statement.known_divergence is None:
                raise ValueError("bounded approximation requires known_divergence")
            if statement.level == "faithful" and statement.known_divergence is not None:
                raise ValueError("faithful fidelity statement cannot declare known_divergence")
        return self


def _check_json_schema(schema: dict[str, JsonValue], label: str) -> None:
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise ValueError(f"{label} contains invalid JSON Schema: {exc.message}") from exc


def _require_rule_family(rules: tuple[Rule, ...], expected: RuleFamily, label: str) -> None:
    wrong = [rule.rule_id for rule in rules if rule.family != expected]
    if wrong:
        raise ValueError(f"{label} contains rules with the wrong family: {wrong}")


def _rule_sources(rule: Rule) -> set[RuleValueSource]:
    sources: set[RuleValueSource] = set()

    def collect(term: RuleTerm | None) -> None:
        if isinstance(term, RuleValueRef):
            sources.add(term.source)
        elif isinstance(term, RuleArithmetic):
            collect(term.left)
            collect(term.right)

    for clause in rule.clauses:
        collect(clause.left)
        collect(clause.right)
    return sources


def _validate_json_pointer(pointer: str) -> None:
    if pointer and not pointer.startswith("/"):
        raise ValueError("rule pointer must be empty or an RFC 6901 absolute pointer")
    if len(pointer) > 4096 or pointer.count("/") > 64:
        raise ValueError("rule pointer exceeds framework limits")
    index = 0
    while index < len(pointer):
        if pointer[index] == "~":
            if index + 1 >= len(pointer) or pointer[index + 1] not in {"0", "1"}:
                raise ValueError("rule pointer contains an invalid RFC 6901 escape")
            index += 2
        else:
            index += 1


def _json_value_type(value: JsonValue) -> RuleValueType:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    return "object"


__all__ = [
    "ActorBoundary",
    "ConcurrencySemantics",
    "FidelityStatement",
    "IdempotencySemantics",
    "ObservationSemantics",
    "PermissionRule",
    "RetrySemantics",
    "RollbackSemantics",
    "Rule",
    "RuleArithmetic",
    "RuleAtom",
    "RuleClause",
    "RuleConstant",
    "RuleOrdering",
    "RuleFamily",
    "RuleTerm",
    "RuleValueRef",
    "RuleValueSource",
    "RuleValueType",
    "StateEntitySchema",
    "StateSchema",
    "TimeoutSemantics",
    "ToolContract",
    "ToolError",
    "ToolSemantics",
    "ToolSurface",
    "TransactionSemantics",
    "WorldBoundary",
    "WorldSpec",
]
