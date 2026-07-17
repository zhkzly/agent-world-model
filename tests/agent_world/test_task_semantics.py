from __future__ import annotations

from typing import cast

import pytest
from jsonschema import Draft202012Validator  # type: ignore[import-untyped]
from pydantic import JsonValue

from agent_world.contracts import (
    CurriculumRequirements,
    DifficultyDimension,
    EvaluatorGoalBinding,
    Rule,
    RuleClause,
    RuleConstant,
    RuleValueRef,
    StateEntitySchema,
    StateSchema,
    TaskMaterializerCall,
    TaskRequirement,
)
from agent_world.designer.service import EnvironmentDesigner
from agent_world.judge.task_semantics import (
    GeneratedTaskSemanticError,
    find_difficulty_contrast_candidates,
)
from agent_world.task_materialization import TaskMaterializerV3Compiler


def _goal_rule(rule_id: str, family: str) -> Rule:
    return Rule(
        rule_id=rule_id,
        family=family,  # type: ignore[arg-type]
        description="Counter reaches the evaluator target.",
        boolean_operator="all",
        case_sensitivity="positive_only",
        clauses=(
            RuleClause(
                clause_id=f"{rule_id}:clause",
                left=RuleValueRef(
                    source="post_state",
                    pointer="/counter/value",
                    value_type="number",
                ),
                operator="greater_or_equal",
                right=RuleValueRef(
                    source="task_goal",
                    pointer="/target",
                    value_type="number",
                ),
            ),
        ),
    )


def _curriculum() -> CurriculumRequirements:
    success = _goal_rule("rule:success", "task_success")
    terminal = _goal_rule("rule:terminal", "task_terminal")
    closed_integer: dict[str, JsonValue] = {
        "type": "object",
        "properties": {"target": {"type": "integer"}},
        "required": ["target"],
        "additionalProperties": False,
    }
    return CurriculumRequirements(
        task_types=(
            TaskRequirement(
                task_type="increase",
                objective="Reach the public counter target.",
                allowed_actor_ids=("user",),
                required_tool_ids=("counter.increment",),
                success_conditions=(success,),
                terminal_conditions=(terminal,),
                initial_config_schema={
                    "type": "object",
                    "properties": {"initial": {"type": "integer"}},
                    "required": ["initial"],
                    "additionalProperties": False,
                },
                public_goal_schema=closed_integer,
                evaluator_goal_schema=closed_integer,
                evaluator_goal_bindings=(
                    EvaluatorGoalBinding(
                        binding_id="binding:target",
                        public_pointer="/target",
                        evaluator_pointer="/target",
                    ),
                ),
                difficulty_dimensions=("scale",),
            ),
        ),
        difficulty_dimensions=(
            DifficultyDimension(
                dimension="scale",
                description="Required increment size.",
                levels=("small", "large"),
            ),
        ),
        generation_seed_space="all uint64 seeds",
    )


def _envelope(*, level: str, target: int, initial: int):
    compiler = TaskMaterializerV3Compiler(_curriculum())
    call = TaskMaterializerCall(
        seed=7,
        task_type="increase",
        actor="user",
        difficulty={"scale": level},
    )
    return compiler.materialize(
        call,
        {
            "schema_version": "v2",
            "task_schema_version": "task-materialization-v3",
            **call.call_arguments(),
            "public_goal": {"target": target},
            "initial_config": {"initial": initial},
        },
    )


def test_evaluator_goal_is_framework_projected_from_public_goal() -> None:
    envelope = _envelope(level="small", target=5, initial=2)

    assert envelope.materialization.public_goal == {"target": 5}
    assert envelope.evaluator_goal == {"target": 5}
    assert "Reach the public counter target" in envelope.public_instruction


def test_difficulty_requires_same_seed_semantic_change_beyond_call_echo() -> None:
    curriculum = _curriculum()
    echo_only = (
        _envelope(level="small", target=5, initial=2),
        _envelope(level="large", target=5, initial=2),
    )
    with pytest.raises(GeneratedTaskSemanticError, match="does not semantically respond"):
        find_difficulty_contrast_candidates(
            envelopes=echo_only,
            curriculum=curriculum,
        )

    initial_state_change = (
        echo_only[0],
        _envelope(level="large", target=5, initial=0),
    )
    candidates = find_difficulty_contrast_candidates(
        envelopes=initial_state_change,
        curriculum=curriculum,
    )
    candidate = candidates["increase"]["scale"][0]
    assert candidate.initial_config_changed
    assert not candidate.evaluator_goal_changed

    evaluator_change = (
        echo_only[0],
        _envelope(level="large", target=9, initial=2),
    )
    candidate = find_difficulty_contrast_candidates(
        envelopes=evaluator_change,
        curriculum=curriculum,
    )["increase"]["scale"][0]
    assert candidate.evaluator_goal_changed


def test_task_contract_rejects_unprojected_evaluator_goal_pointer() -> None:
    requirement = _curriculum().task_types[0]
    unbound = _goal_rule("rule:failure", "task_failure").model_copy(
        update={
            "clauses": (
                RuleClause(
                    clause_id="rule:failure:clause",
                    left=RuleValueRef(
                        source="task_goal",
                        pointer="/hidden_limit",
                        value_type="number",
                    ),
                    operator="greater_than",
                    right=RuleConstant(value_type="number", value=0),
                ),
            )
        }
    )
    with pytest.raises(ValueError, match="non-required or unprojected"):
        TaskRequirement(
            **requirement.model_dump(exclude={"failure_conditions"}),
            failure_conditions=(unbound,),
        )


def test_task_contract_bounds_minimum_tool_calls() -> None:
    requirement = _curriculum().task_types[0]

    with pytest.raises(ValueError):
        TaskRequirement(
            **requirement.model_dump(exclude={"minimum_tool_calls"}),
            minimum_tool_calls=33,
        )


def test_task_initial_config_accepts_closed_scalar_type_unions() -> None:
    requirement = _curriculum().task_types[0]

    compiled = TaskRequirement(
        **requirement.model_dump(exclude={"initial_config_schema"}),
        initial_config_schema={
            "type": "object",
            "properties": {"note": {"type": ["string", "null"]}},
            "required": ["note"],
            "additionalProperties": False,
        },
    )

    assert compiled.initial_config_schema["properties"] == {"note": {"type": ["string", "null"]}}


def test_task_initial_config_compiler_normalizes_nullable_scalar_any_of() -> None:
    requirement = _curriculum().task_types[0]
    world_schema: dict[str, JsonValue] = {
        "type": "object",
        "properties": {
            "payment_state": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "authorization_id": {
                            "description": "Optional gateway authorization id.",
                            "anyOf": [
                                {
                                    "type": "string",
                                    "format": "uuid",
                                    "minLength": 1,
                                    "description": "Gateway identifier.",
                                },
                                {"type": "null", "description": "Not authorized yet."},
                            ],
                        }
                    },
                    "required": ["authorization_id"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["payment_state"],
        "additionalProperties": False,
    }

    compiled_schema = EnvironmentDesigner._compile_task_initial_config_schema(world_schema)
    root_properties = cast(dict[str, JsonValue], compiled_schema["properties"])
    payment_state = cast(dict[str, JsonValue], root_properties["payment_state"])
    payment_items = cast(dict[str, JsonValue], payment_state["items"])
    payment_properties = cast(dict[str, JsonValue], payment_items["properties"])
    authorization = payment_properties["authorization_id"]
    assert authorization == {
        "description": "Optional gateway authorization id.",
        "format": "uuid",
        "minLength": 1,
        "type": ["string", "null"],
    }
    original_authorization = cast(
        dict[str, JsonValue],
        cast(
            dict[str, JsonValue],
            cast(
                dict[str, JsonValue],
                cast(dict[str, JsonValue], world_schema["properties"])["payment_state"],
            )["items"],
        )["properties"],
    )["authorization_id"]
    for candidate in (None, "", "gateway-id", 7):
        assert Draft202012Validator(cast(dict[str, JsonValue], original_authorization)).is_valid(
            candidate
        ) == Draft202012Validator(cast(dict[str, JsonValue], authorization)).is_valid(candidate)

    # Exercise the actual TaskRequirement gate, not only the compiler helper.
    TaskRequirement(
        **requirement.model_dump(exclude={"initial_config_schema"}),
        initial_config_schema=compiled_schema,
    )


@pytest.mark.parametrize(
    ("branch_constraint", "accepted", "rejected"),
    [
        ({"enum": ["authorized"]}, (None, "authorized"), ("declined", 1)),
        ({"const": "authorized"}, (None, "authorized"), ("declined", 1)),
    ],
)
def test_task_initial_config_nullable_scalar_enum_and_const_are_equivalent(
    branch_constraint: dict[str, JsonValue],
    accepted: tuple[JsonValue, ...],
    rejected: tuple[JsonValue, ...],
) -> None:
    nullable: dict[str, JsonValue] = {
        "anyOf": [
            {"type": "string", **branch_constraint},
            {"type": "null"},
        ]
    }
    world_schema: dict[str, JsonValue] = {
        "type": "object",
        "properties": {"authorization_id": nullable},
        "required": ["authorization_id"],
        "additionalProperties": False,
    }

    compiled = EnvironmentDesigner._compile_task_initial_config_schema(world_schema)
    compiled_properties = cast(dict[str, JsonValue], compiled["properties"])
    compiled_nullable = cast(dict[str, JsonValue], compiled_properties["authorization_id"])
    assert compiled_nullable["enum"] == ["authorized", None]
    assert compiled_nullable["type"] == ["string", "null"]
    for candidate in (*accepted, *rejected):
        assert Draft202012Validator(nullable).is_valid(candidate) == Draft202012Validator(
            compiled_nullable
        ).is_valid(candidate)
    assert all(Draft202012Validator(compiled_nullable).is_valid(item) for item in accepted)
    assert not any(Draft202012Validator(compiled_nullable).is_valid(item) for item in rejected)


def test_task_initial_config_nullable_compiler_fails_closed_on_assertion_collision() -> None:
    world_schema: dict[str, JsonValue] = {
        "type": "object",
        "properties": {
            "authorization_id": {
                "minLength": 3,
                "anyOf": [
                    {"type": "string", "minLength": 1},
                    {"type": "null"},
                ],
            }
        },
        "required": ["authorization_id"],
        "additionalProperties": False,
    }

    compiled = EnvironmentDesigner._compile_task_initial_config_schema(world_schema)
    properties = cast(dict[str, JsonValue], compiled["properties"])
    assert "anyOf" in cast(dict[str, JsonValue], properties["authorization_id"])


def test_task_initial_config_compiler_does_not_weaken_structural_any_of() -> None:
    world_schema: dict[str, JsonValue] = {
        "type": "object",
        "properties": {
            "ambiguous": {
                "anyOf": [
                    {
                        "type": "object",
                        "properties": {},
                        "additionalProperties": False,
                    },
                    {"type": "null"},
                ]
            }
        },
        "required": ["ambiguous"],
        "additionalProperties": False,
    }

    compiled_schema = EnvironmentDesigner._compile_task_initial_config_schema(world_schema)
    requirement = _curriculum().task_types[0]
    with pytest.raises(ValueError, match="unsupported open/composed"):
        TaskRequirement(
            **requirement.model_dump(exclude={"initial_config_schema"}),
            initial_config_schema=compiled_schema,
        )


def test_task_schema_rejects_structural_type_unions() -> None:
    requirement = _curriculum().task_types[0]

    with pytest.raises(ValueError, match="scalar type unions"):
        TaskRequirement(
            **requirement.model_dump(exclude={"initial_config_schema"}),
            initial_config_schema={
                "type": "object",
                "properties": {"ambiguous": {"type": ["object", "null"]}},
                "required": ["ambiguous"],
                "additionalProperties": False,
            },
        )


def test_initial_and_sampling_rules_cannot_read_evaluator_goal() -> None:
    curriculum = _curriculum()
    requirement = curriculum.task_types[0]
    initial = _goal_rule("rule:initial-hidden-goal", "initial_state")
    sampling = _goal_rule("rule:sampling-hidden-goal", "sampling")

    with pytest.raises(ValueError, match="initial-state constraints cannot read"):
        TaskRequirement(
            **requirement.model_dump(exclude={"initial_state_constraints"}),
            initial_state_constraints=(initial,),
        )

    with pytest.raises(ValueError, match="sampling constraints cannot read"):
        CurriculumRequirements(
            **curriculum.model_dump(exclude={"sampling_constraints"}),
            sampling_constraints=(sampling,),
        )

    with pytest.raises(ValueError, match="world initial-state constraints cannot read"):
        StateSchema(
            entities=(
                StateEntitySchema(
                    entity="counter",
                    json_schema={
                        "type": "object",
                        "properties": {"id": {"type": "string"}},
                        "required": ["id"],
                    },
                    primary_key_fields=("id",),
                ),
            ),
            root_state_schema={
                "type": "object",
                "properties": {"counter": {"type": "object"}},
                "required": ["counter"],
            },
            initial_state_constraints=(initial,),
        )
