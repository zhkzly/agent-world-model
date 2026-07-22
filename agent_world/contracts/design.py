"""The Designer-to-Builder contract and task/curriculum requirements."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Annotated, Literal, cast

from jsonschema import Draft202012Validator, SchemaError  # type: ignore[import-untyped]
from pydantic import Field, JsonValue, model_validator

from .base import ArtifactRef, Identifier, NonEmptyStr, V2Contract
from .reachability import ReachabilityPolicy
from .world import Rule, RuleArithmetic, RuleLookupByKey, RuleTerm, RuleValueRef, WorldSpec

_RULE_PROPERTY_FAMILY = {
    "initial_state": "initial_state",
    "invariant": "invariant",
    "precondition": "precondition",
    "transition": "transition",
    "postcondition": "postcondition",
    "error_condition": "error_semantics",
    "permission": "permission",
    "task_success": "task_success",
    "task_failure": "task_failure",
    "task_terminal": "task_terminal",
    "sampling": "sampling",
}

_MAX_POINTER_LENGTH = 4096
_MAX_POINTER_SEGMENTS = 32
_UNSAFE_TASK_SCHEMA_KEYS = frozenset(
    {
        "$dynamicRef",
        "$recursiveRef",
        "$ref",
        "allOf",
        "anyOf",
        "dependentSchemas",
        "else",
        "if",
        "not",
        "oneOf",
        "patternProperties",
        "prefixItems",
        "then",
        "unevaluatedProperties",
    }
)


def _term_sources(term: RuleTerm) -> frozenset[str]:
    if isinstance(term, RuleValueRef):
        return frozenset((term.source,))
    if isinstance(term, RuleLookupByKey):
        return frozenset((term.source,)) | _term_sources(term.key)
    if isinstance(term, RuleArithmetic):
        return _term_sources(term.left) | _term_sources(term.right)
    return frozenset()


def _rule_sources(rule: Rule) -> frozenset[str]:
    sources: set[str] = set()
    for clause in rule.clauses:
        sources.update(_term_sources(clause.left))
        if clause.right is not None:
            sources.update(_term_sources(clause.right))
    return frozenset(sources)


def _term_goal_pointers(term: RuleTerm | None) -> frozenset[str]:
    if isinstance(term, RuleValueRef):
        return frozenset((term.pointer,)) if term.source == "task_goal" else frozenset()
    if isinstance(term, RuleLookupByKey):
        return _term_goal_pointers(term.key)
    if isinstance(term, RuleArithmetic):
        return _term_goal_pointers(term.left) | _term_goal_pointers(term.right)
    return frozenset()


class DifficultyDimension(V2Contract):
    dimension: Identifier
    description: NonEmptyStr
    levels: Annotated[tuple[Identifier, ...], Field(min_length=2)]


class EvaluatorGoalBinding(V2Contract):
    """One total identity projection from a public leaf to an evaluator leaf."""

    binding_id: Identifier
    public_pointer: NonEmptyStr
    evaluator_pointer: NonEmptyStr
    projection: Literal["identity"] = "identity"

    @model_validator(mode="after")
    def validate_pointers(self) -> EvaluatorGoalBinding:
        for label, pointer in (
            ("public_pointer", self.public_pointer),
            ("evaluator_pointer", self.evaluator_pointer),
        ):
            _decode_pointer(pointer, label=label)
        return self


class TaskRequirement(V2Contract):
    task_type: Identifier
    objective: NonEmptyStr
    allowed_actor_ids: Annotated[tuple[Identifier, ...], Field(min_length=1)]
    required_tool_ids: Annotated[tuple[Identifier, ...], Field(min_length=1)]
    initial_state_constraints: tuple[Rule, ...] = ()
    success_conditions: Annotated[tuple[Rule, ...], Field(min_length=1, max_length=64)]
    failure_conditions: Annotated[tuple[Rule, ...], Field(max_length=64)] = ()
    terminal_conditions: Annotated[tuple[Rule, ...], Field(min_length=1, max_length=64)]
    initial_config_schema: dict[str, JsonValue]
    public_goal_schema: dict[str, JsonValue]
    evaluator_goal_schema: dict[str, JsonValue]
    evaluator_goal_bindings: Annotated[
        tuple[EvaluatorGoalBinding, ...], Field(min_length=1, max_length=64)
    ]
    difficulty_dimensions: Annotated[tuple[Identifier, ...], Field(min_length=1)]
    minimum_tool_calls: Annotated[int, Field(ge=1, le=32)] = 1
    reachability_policy: ReachabilityPolicy = Field(default_factory=ReachabilityPolicy)

    @model_validator(mode="after")
    def validate_rule_families(self) -> TaskRequirement:
        if len(set(self.allowed_actor_ids)) != len(self.allowed_actor_ids):
            raise ValueError(f"task {self.task_type} allowed_actor_ids must be unique")
        if len(set(self.required_tool_ids)) != len(self.required_tool_ids):
            raise ValueError(f"task {self.task_type} required_tool_ids must be unique")
        for label, schema in (
            ("initial_config_schema", self.initial_config_schema),
            ("public_goal_schema", self.public_goal_schema),
            ("evaluator_goal_schema", self.evaluator_goal_schema),
        ):
            _validate_closed_object_schema(
                schema,
                label=f"task {self.task_type} {label}",
            )
        expected = (
            (self.initial_state_constraints, "initial_state"),
            (self.success_conditions, "task_success"),
            (self.failure_conditions, "task_failure"),
            (self.terminal_conditions, "task_terminal"),
        )
        for rules, family in expected:
            wrong = [rule.rule_id for rule in rules if rule.family != family]
            if wrong:
                raise ValueError(
                    f"task {self.task_type} {family} rules have the wrong family: {wrong}"
                )
        goal_dependent_initial = {
            rule.rule_id
            for rule in self.initial_state_constraints
            if "task_goal" in _rule_sources(rule)
        }
        if goal_dependent_initial:
            raise ValueError(
                "task initial-state constraints cannot read evaluator-only task_goal: "
                f"{sorted(goal_dependent_initial)}"
            )
        evaluator_rules = (
            *self.success_conditions,
            *self.failure_conditions,
            *self.terminal_conditions,
        )
        untrusted_sources = {
            rule.rule_id
            for rule in evaluator_rules
            if _rule_sources(rule) & {"terminated", "truncated"}
        }
        if untrusted_sources:
            raise ValueError(
                "task evaluator rules cannot depend on Runtime-reported termination flags: "
                f"{sorted(untrusted_sources)}"
            )
        if not any("task_goal" in _rule_sources(rule) for rule in self.success_conditions):
            raise ValueError(
                f"task {self.task_type} requires a task_success rule that reads task_goal"
            )
        if not any("task_goal" in _rule_sources(rule) for rule in self.terminal_conditions):
            raise ValueError(
                f"task {self.task_type} requires a task_terminal rule that reads task_goal"
            )
        binding_ids = [item.binding_id for item in self.evaluator_goal_bindings]
        if len(set(binding_ids)) != len(binding_ids):
            raise ValueError(f"task {self.task_type} evaluator goal binding ids must be unique")
        evaluator_pointers = [item.evaluator_pointer for item in self.evaluator_goal_bindings]
        if len(set(evaluator_pointers)) != len(evaluator_pointers):
            raise ValueError(
                f"task {self.task_type} may project each evaluator goal pointer only once"
            )
        decoded_pointers = [
            (pointer, _decode_pointer(pointer, label="evaluator_pointer"))
            for pointer in evaluator_pointers
        ]
        for index, (left_pointer, left_tokens) in enumerate(decoded_pointers):
            for right_pointer, right_tokens in decoded_pointers[index + 1 :]:
                shortest = min(len(left_tokens), len(right_tokens))
                if left_tokens[:shortest] == right_tokens[:shortest]:
                    raise ValueError(
                        f"task {self.task_type} evaluator goal bindings overlap: "
                        f"{left_pointer}, {right_pointer}"
                    )
        public_required_leaves = _required_leaf_pointers(self.public_goal_schema)
        evaluator_required_leaves = _required_leaf_pointers(self.evaluator_goal_schema)
        for binding in self.evaluator_goal_bindings:
            _require_schema_pointer(
                self.public_goal_schema,
                binding.public_pointer,
                f"task {self.task_type} public goal",
            )
            _require_schema_pointer(
                self.evaluator_goal_schema,
                binding.evaluator_pointer,
                f"task {self.task_type} evaluator goal",
            )
            if binding.public_pointer not in public_required_leaves:
                raise ValueError(
                    f"task {self.task_type} evaluator bindings may read only required "
                    f"public goal leaves: {binding.public_pointer}"
                )
        actual_evaluator_pointers = frozenset(evaluator_pointers)
        if actual_evaluator_pointers != evaluator_required_leaves:
            missing = sorted(evaluator_required_leaves - actual_evaluator_pointers)
            extra = sorted(actual_evaluator_pointers - evaluator_required_leaves)
            raise ValueError(
                f"task {self.task_type} evaluator bindings must cover exactly every "
                f"required evaluator leaf; missing={missing}, extra={extra}"
            )
        evaluator_goal_pointers = {
            pointer
            for rule in evaluator_rules
            for clause in rule.clauses
            for pointer in (_term_goal_pointers(clause.left) | _term_goal_pointers(clause.right))
        }
        uncovered = evaluator_goal_pointers - evaluator_required_leaves
        if uncovered:
            raise ValueError(
                f"task {self.task_type} evaluator Rules read non-required or unprojected "
                f"goal leaves: {sorted(uncovered)}"
            )
        return self


def _decode_pointer(pointer: str, *, label: str) -> tuple[str, ...]:
    if not pointer.startswith("/") or pointer == "/":
        raise ValueError(f"{label} must be a non-root RFC 6901 JSON pointer")
    if len(pointer) > _MAX_POINTER_LENGTH or pointer.count("/") > _MAX_POINTER_SEGMENTS:
        raise ValueError(f"{label} exceeds task goal pointer limits")
    tokens: list[str] = []
    for raw_token in pointer.split("/")[1:]:
        index = 0
        while index < len(raw_token):
            if raw_token[index] == "~":
                if index + 1 >= len(raw_token) or raw_token[index + 1] not in {"0", "1"}:
                    raise ValueError(f"{label} contains an invalid RFC 6901 escape")
                index += 1
            index += 1
        tokens.append(raw_token.replace("~1", "/").replace("~0", "~"))
    return tuple(tokens)


def _encode_pointer(tokens: Sequence[str]) -> str:
    return "/" + "/".join(token.replace("~", "~0").replace("/", "~1") for token in tokens)


def _validate_closed_object_schema(schema: Mapping[str, JsonValue], *, label: str) -> None:
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise ValueError(f"{label} is invalid: {exc.message}") from exc
    if schema.get("type") != "object":
        raise ValueError(f"{label} must describe an object")
    _validate_closed_schema_node(schema, label=label, depth=0)


def _validate_closed_schema_node(
    schema: Mapping[str, JsonValue],
    *,
    label: str,
    depth: int,
) -> None:
    if depth > _MAX_POINTER_SEGMENTS:
        raise ValueError(f"{label} nesting exceeds task schema limits")
    unsafe = sorted(_UNSAFE_TASK_SCHEMA_KEYS & schema.keys())
    if unsafe:
        raise ValueError(f"{label} uses unsupported open/composed schema keywords: {unsafe}")
    schema_type = schema.get("type")
    if schema_type == "object":
        if schema.get("additionalProperties") is not False:
            raise ValueError(f"{label} object schemas must set additionalProperties=false")
        properties = schema.get("properties")
        if not isinstance(properties, dict):
            raise ValueError(f"{label} object schemas require an explicit properties object")
        required = schema.get("required", [])
        if not isinstance(required, list) or not all(isinstance(item, str) for item in required):
            raise ValueError(f"{label} required must be an array of property names")
        if len(set(required)) != len(required) or not set(required) <= set(properties):
            raise ValueError(f"{label} required properties must be unique and declared")
        for property_name, child in properties.items():
            if not isinstance(property_name, str) or not isinstance(child, dict):
                raise ValueError(f"{label} properties must contain object schemas")
            _validate_closed_schema_node(
                cast(dict[str, JsonValue], child),
                label=f"{label}.{property_name}",
                depth=depth + 1,
            )
        return
    if schema_type == "array":
        items = schema.get("items")
        if not isinstance(items, dict):
            raise ValueError(f"{label} array schemas require one explicit items schema")
        _validate_closed_schema_node(
            cast(dict[str, JsonValue], items),
            label=f"{label}[]",
            depth=depth + 1,
        )
        return
    scalar_types = {"string", "integer", "number", "boolean", "null"}
    if isinstance(schema_type, list):
        if (
            not schema_type
            or not all(isinstance(item, str) for item in schema_type)
            or len(set(schema_type)) != len(schema_type)
            or not set(schema_type) <= scalar_types
        ):
            raise ValueError(f"{label} scalar type unions must contain unique supported JSON types")
        return
    if schema_type not in scalar_types:
        raise ValueError(f"{label} must declare one supported JSON type")


def _required_leaf_pointers(schema: Mapping[str, JsonValue]) -> frozenset[str]:
    leaves: set[str] = set()

    def visit(node: Mapping[str, JsonValue], tokens: tuple[str, ...]) -> None:
        properties = node.get("properties")
        required = node.get("required", [])
        if not isinstance(properties, dict) or not isinstance(required, list):
            return
        for property_name in required:
            if not isinstance(property_name, str):
                raise ValueError("required schema property names must be strings")
            child = properties[property_name]
            if not isinstance(child, dict):
                raise ValueError("required schema properties must contain schemas")
            next_tokens = (*tokens, property_name)
            child_required = child.get("required", [])
            if (
                child.get("type") == "object"
                and isinstance(child_required, list)
                and child_required
            ):
                visit(cast(dict[str, JsonValue], child), next_tokens)
            else:
                leaves.add(_encode_pointer(next_tokens))

    visit(schema, ())
    return frozenset(leaves)


def _require_schema_pointer(schema: dict[str, JsonValue], pointer: str, label: str) -> None:
    """Require a pointer to traverse required properties in a closed object schema."""

    current: JsonValue = schema
    for raw_token in pointer.split("/")[1:]:
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if not isinstance(current, dict) or current.get("type") != "object":
            raise ValueError(f"{label} pointer {pointer} traverses a non-object schema")
        properties = current.get("properties")
        required = current.get("required")
        if (
            not isinstance(properties, dict)
            or token not in properties
            or not isinstance(required, list)
            or token not in required
        ):
            raise ValueError(f"{label} pointer {pointer} must name required schema properties")
        current = properties[token]


class CurriculumRequirements(V2Contract):
    task_types: Annotated[tuple[TaskRequirement, ...], Field(min_length=1)]
    difficulty_dimensions: Annotated[tuple[DifficultyDimension, ...], Field(min_length=1)]
    generation_seed_space: NonEmptyStr
    minimum_distinct_initial_states: Annotated[int, Field(ge=2)] = 2
    minimum_distinct_tasks_per_type: Annotated[int, Field(ge=2)] = 2
    sampling_constraints: Annotated[tuple[Rule, ...], Field(max_length=128)] = ()

    @model_validator(mode="after")
    def validate_curriculum(self) -> CurriculumRequirements:
        task_types = [task.task_type for task in self.task_types]
        if len(set(task_types)) != len(task_types):
            raise ValueError("task_type values must be unique")
        dimensions = [item.dimension for item in self.difficulty_dimensions]
        if len(set(dimensions)) != len(dimensions):
            raise ValueError("difficulty dimensions must be unique")
        dimension_set = set(dimensions)
        for task in self.task_types:
            if not set(task.difficulty_dimensions) <= dimension_set:
                raise ValueError(f"task {task.task_type} references unknown difficulty dimensions")
        wrong_sampling = [
            rule.rule_id for rule in self.sampling_constraints if rule.family != "sampling"
        ]
        if wrong_sampling:
            raise ValueError(f"sampling constraints have the wrong family: {wrong_sampling}")
        goal_dependent_sampling = {
            rule.rule_id for rule in self.sampling_constraints if "task_goal" in _rule_sources(rule)
        }
        if goal_dependent_sampling:
            raise ValueError(
                "sampling constraints cannot read evaluator-only task_goal: "
                f"{sorted(goal_dependent_sampling)}"
            )
        return self


class RewardSpec(V2Contract):
    """Framework-owned task-outcome reward and termination contract.

    Agent-authored rules decide whether a task succeeded or failed, but their
    count never changes reward magnitude.  Failure wins if both outcomes match.
    """

    default_reward: Annotated[float, Field(ge=0.0, le=0.0, allow_inf_nan=False)] = 0.0
    success_reward: Annotated[float, Field(ge=1.0, le=1.0, allow_inf_nan=False)] = 1.0
    failure_reward: Annotated[float, Field(ge=-1.0, le=-1.0, allow_inf_nan=False)] = -1.0
    outcome_precedence: Literal["failure_over_success"] = "failure_over_success"
    terminal_rule_ids: Annotated[tuple[Identifier, ...], Field(min_length=1, max_length=128)]
    success_rule_ids: Annotated[tuple[Identifier, ...], Field(min_length=1, max_length=128)]
    failure_rule_ids: Annotated[tuple[Identifier, ...], Field(max_length=128)] = ()
    comparison_tolerance: Annotated[float, Field(ge=0, le=1e-6)] = 1e-9

    @model_validator(mode="after")
    def validate_reward_shape(self) -> RewardSpec:
        for label, values in (
            ("terminal_rule_ids", self.terminal_rule_ids),
            ("success_rule_ids", self.success_rule_ids),
            ("failure_rule_ids", self.failure_rule_ids),
        ):
            if len(set(values)) != len(values):
                raise ValueError(f"{label} must be unique")
        return self


class VerificationRequirements(V2Contract):
    required_rule_ids: Annotated[tuple[Identifier, ...], Field(min_length=1)]
    required_property_families: tuple[
        Literal[
            "invariant",
            "initial_state",
            "precondition",
            "transition",
            "postcondition",
            "error_semantics",
            "idempotency",
            "rollback",
            "permission",
            "concurrency",
            "metamorphic",
            "task_success",
            "task_failure",
            "task_terminal",
            "sampling",
        ],
        ...,
    ] = ()
    required_metamorphic_relations: tuple[Identifier, ...] = ()
    deployment_checks: tuple[Identifier, ...] = (
        "clean_install",
        "start",
        "health",
        "restart",
        "concurrency",
        "teardown",
        "package_relative",
    )
    minimum_unknown_seed_episodes: Annotated[int, Field(ge=2, le=8)] = 2

    @model_validator(mode="after")
    def validate_unique_requirements(self) -> VerificationRequirements:
        for label, values in (
            ("required_rule_ids", self.required_rule_ids),
            ("required_property_families", self.required_property_families),
            ("required_metamorphic_relations", self.required_metamorphic_relations),
            ("deployment_checks", self.deployment_checks),
        ):
            if len(set(values)) != len(values):
                raise ValueError(f"{label} must be unique")
        return self


class EnvironmentDesign(V2Contract):
    design_id: Identifier
    revision: Annotated[int, Field(ge=1)]
    job_ref: ArtifactRef
    request_ref: ArtifactRef
    evidence_graph_ref: ArtifactRef
    coverage_map_ref: ArtifactRef
    world_spec: WorldSpec
    curriculum: CurriculumRequirements
    reward: RewardSpec
    verification: VerificationRequirements
    target_kind: Literal["initial_package", "package_revision", "new_package"]
    semantic_lineage_ref: ArtifactRef | None = None
    unresolved_questions: tuple[NonEmptyStr, ...] = ()

    @model_validator(mode="after")
    def validate_reward_references(self) -> EnvironmentDesign:
        rules: dict[str, Rule] = {}

        def add(rule: Rule) -> None:
            if rule.rule_id in rules:
                raise ValueError(f"duplicate rule id across design: {rule.rule_id}")
            rules[rule.rule_id] = rule

        for rule in self.world_spec.invariants:
            add(rule)
        for rule in self.world_spec.state.initial_state_constraints:
            add(rule)
        for tool in self.world_spec.tools:
            semantics = tool.semantics
            for rule in (
                *semantics.preconditions,
                *semantics.transition,
                *semantics.postconditions,
            ):
                add(rule)
            for error in semantics.errors:
                add(error.when)
            if semantics.permission.condition is not None:
                add(semantics.permission.condition)
        for task in self.curriculum.task_types:
            for rule in (
                *task.initial_state_constraints,
                *task.success_conditions,
                *task.failure_conditions,
                *task.terminal_conditions,
            ):
                add(rule)
        for rule in self.curriculum.sampling_constraints:
            add(rule)

        world_actor_ids = {actor.actor for actor in self.world_spec.boundary.actors_and_authority}
        tools_by_id = {tool.surface.tool_id: tool for tool in self.world_spec.tools}
        for task in self.curriculum.task_types:
            unknown_actors = set(task.allowed_actor_ids) - world_actor_ids
            if unknown_actors:
                raise ValueError(
                    f"task {task.task_type} references unknown actors: {sorted(unknown_actors)}"
                )
            unknown_tools = set(task.required_tool_ids) - set(tools_by_id)
            if unknown_tools:
                raise ValueError(
                    f"task {task.task_type} references unknown tools: {sorted(unknown_tools)}"
                )
            for tool_id in task.required_tool_ids:
                tool = tools_by_id[tool_id]
                unavailable = set(task.allowed_actor_ids) - set(
                    tool.semantics.permission.allowed_actors
                )
                if unavailable:
                    raise ValueError(
                        f"task {task.task_type} allows actors without permission for {tool_id}: "
                        f"{sorted(unavailable)}"
                    )

        reward_ids = {
            *self.reward.terminal_rule_ids,
            *self.reward.success_rule_ids,
            *self.reward.failure_rule_ids,
        }
        unknown = reward_ids - set(rules)
        if unknown:
            raise ValueError(f"RewardSpec references unknown rules: {sorted(unknown)}")
        authority_leaks = {
            rule_id
            for rule_id in reward_ids
            if _rule_sources(rules[rule_id]) & {"terminated", "truncated"}
        }
        if authority_leaks:
            raise ValueError(
                "RewardSpec cannot depend on Runtime-reported termination flags: "
                f"{sorted(authority_leaks)}"
            )
        invalid_terminal = {
            rule_id
            for rule_id in self.reward.terminal_rule_ids
            if rules[rule_id].family != "task_terminal"
        }
        invalid_success = {
            rule_id
            for rule_id in self.reward.success_rule_ids
            if rules[rule_id].family != "task_success"
        }
        invalid_failure = {
            rule_id
            for rule_id in self.reward.failure_rule_ids
            if rules[rule_id].family != "task_failure"
        }
        if invalid_terminal or invalid_success or invalid_failure:
            raise ValueError(
                "RewardSpec terminal/success/failure refs must match task rule families"
            )
        expected_success_ids = {
            rule.rule_id for task in self.curriculum.task_types for rule in task.success_conditions
        }
        expected_failure_ids = {
            rule.rule_id for task in self.curriculum.task_types for rule in task.failure_conditions
        }
        expected_terminal_ids = {
            rule.rule_id for task in self.curriculum.task_types for rule in task.terminal_conditions
        }
        if (
            set(self.reward.success_rule_ids) != expected_success_ids
            or set(self.reward.failure_rule_ids) != expected_failure_ids
            or set(self.reward.terminal_rule_ids) != expected_terminal_ids
        ):
            raise ValueError(
                "RewardSpec must contain the complete task success/failure/terminal Rule closure"
            )
        for task in self.curriculum.task_types:
            success_ids = {item.rule_id for item in task.success_conditions}
            failure_ids = {item.rule_id for item in task.failure_conditions}
            terminal_ids = {item.rule_id for item in task.terminal_conditions}
            if not success_ids & set(self.reward.success_rule_ids):
                raise ValueError(f"RewardSpec has no success rule for task {task.task_type}")
            if not terminal_ids & set(self.reward.terminal_rule_ids):
                raise ValueError(f"RewardSpec has no terminal rule for task {task.task_type}")
            if failure_ids and not failure_ids & set(self.reward.failure_rule_ids):
                raise ValueError(f"RewardSpec has no failure rule for task {task.task_type}")
        required_rules = set(self.verification.required_rule_ids)
        all_rules = set(rules)
        if required_rules != all_rules:
            raise ValueError(
                "VerificationRequirements.required_rule_ids must be the framework-complete "
                f"Rule closure; missing={sorted(all_rules - required_rules)}, "
                f"extra={sorted(required_rules - all_rules)}"
            )
        required_families = set(self.verification.required_property_families)
        canonical_families = {_RULE_PROPERTY_FAMILY[rule.family] for rule in rules.values()}
        if missing_families := canonical_families - required_families:
            raise ValueError(
                "VerificationRequirements.required_property_families omits canonical Rule "
                f"families: {sorted(missing_families)}"
            )
        return self


__all__ = [
    "CurriculumRequirements",
    "DifficultyDimension",
    "EnvironmentDesign",
    "EvaluatorGoalBinding",
    "RewardSpec",
    "TaskRequirement",
    "VerificationRequirements",
]
