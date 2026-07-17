from __future__ import annotations

import copy

import pytest
from jsonschema import Draft202012Validator  # type: ignore[import-untyped]
from pydantic import JsonValue, ValidationError

from agent_world.contracts.design import (
    CurriculumRequirements,
    DifficultyDimension,
    EvaluatorGoalBinding,
    TaskRequirement,
)
from agent_world.contracts.task import TaskMaterializerCall
from agent_world.contracts.world import Rule, RuleClause, RuleValueRef
from agent_world.task_materialization import (
    TaskMaterializationError,
    TaskMaterializerV3Compiler,
    compile_task_materializer_output_schema,
    project_evaluator_goal,
    render_public_instruction,
)


def _goal_rule(rule_id: str, family: str, pointer: str = "/target") -> Rule:
    object_goal = pointer == "/account"
    return Rule(
        rule_id=rule_id,
        family=family,  # type: ignore[arg-type]
        description="The counter reaches the framework-projected goal.",
        boolean_operator="all",
        case_sensitivity="positive_only",
        clauses=(
            RuleClause(
                clause_id=f"{rule_id}:goal",
                left=RuleValueRef(
                    source="post_state",
                    pointer="/account" if object_goal else "/counter/value",
                    value_type="object" if object_goal else "number",
                ),
                operator="equal" if object_goal else "greater_or_equal",
                right=RuleValueRef(
                    source="task_goal",
                    pointer=pointer,
                    value_type="object" if object_goal else "number",
                ),
            ),
        ),
    )


def _initial_config_schema() -> dict[str, JsonValue]:
    return {
        "type": "object",
        "properties": {
            "initial": {"type": "integer", "minimum": 0},
            "context": {
                "type": "object",
                "properties": {"region": {"type": "string"}},
                "required": ["region"],
                "additionalProperties": False,
            },
        },
        "required": ["initial", "context"],
        "additionalProperties": False,
    }


def _requirement() -> TaskRequirement:
    public_schema: dict[str, JsonValue] = {
        "type": "object",
        "properties": {
            "target": {"type": "integer", "minimum": 1},
            "account": {
                "type": "object",
                "properties": {"id": {"type": "string", "minLength": 1}},
                "required": ["id"],
                "additionalProperties": False,
            },
            "display_hint": {"type": "string"},
        },
        "required": ["target", "account"],
        "additionalProperties": False,
    }
    evaluator_schema = copy.deepcopy(public_schema)
    evaluator_properties = evaluator_schema["properties"]
    assert isinstance(evaluator_properties, dict)
    evaluator_properties.pop("display_hint")
    return TaskRequirement(
        task_type="increase",
        objective="Increase the counter to the requested target.",
        allowed_actor_ids=("operator",),
        required_tool_ids=("counter.increment",),
        success_conditions=(_goal_rule("rule:success", "task_success"),),
        terminal_conditions=(_goal_rule("rule:terminal", "task_terminal"),),
        initial_config_schema=_initial_config_schema(),
        public_goal_schema=public_schema,
        evaluator_goal_schema=evaluator_schema,
        evaluator_goal_bindings=(
            EvaluatorGoalBinding(
                binding_id="binding:target",
                public_pointer="/target",
                evaluator_pointer="/target",
            ),
            EvaluatorGoalBinding(
                binding_id="binding:account-id",
                public_pointer="/account/id",
                evaluator_pointer="/account/id",
            ),
        ),
        difficulty_dimensions=("scale",),
    )


def _curriculum(requirement: TaskRequirement | None = None) -> CurriculumRequirements:
    return CurriculumRequirements(
        task_types=(requirement or _requirement(),),
        difficulty_dimensions=(
            DifficultyDimension(
                dimension="scale",
                description="Distance from the initial counter value.",
                levels=("small", "large"),
            ),
        ),
        generation_seed_space="all uint64 seeds",
    )


def _call(**updates: object) -> TaskMaterializerCall:
    values: dict[str, object] = {
        "seed": 7,
        "task_type": "increase",
        "actor": "operator",
        "difficulty": {"scale": "small"},
    }
    values.update(updates)
    return TaskMaterializerCall.model_validate(values)


def _output(**updates: object) -> dict[str, object]:
    values: dict[str, object] = {
        "schema_version": "v2",
        "task_schema_version": "task-materialization-v3",
        "seed": 7,
        "task_type": "increase",
        "actor": "operator",
        "difficulty": {"scale": "small"},
        "public_goal": {
            "account": {"id": "account-7"},
            "display_hint": "Use the increment tool.",
            "target": 9,
        },
        "initial_config": {"context": {"region": "eu"}, "initial": 2},
    }
    values.update(updates)
    return values


def test_compiled_v3_schema_contains_only_candidate_parameter_fields() -> None:
    curriculum = _curriculum()
    schema = compile_task_materializer_output_schema(curriculum)
    properties = schema["properties"]
    assert isinstance(properties, dict)
    assert set(properties) == {
        "schema_version",
        "task_schema_version",
        "seed",
        "task_type",
        "actor",
        "difficulty",
        "public_goal",
        "initial_config",
    }
    assert schema["additionalProperties"] is False
    assert not tuple(Draft202012Validator(schema).iter_errors(_output()))

    compiler = TaskMaterializerV3Compiler(curriculum)
    for forbidden in (
        "public_instruction",
        "evaluator_goal",
        "private_goal",
        "evaluation_witness",
        "answer",
        "expected_output",
    ):
        with pytest.raises(TaskMaterializationError) as rejected:
            compiler.materialize(_call(), _output(**{forbidden: {"target": 9}}))
        assert rejected.value.code == "candidate_schema_violation"


def test_compiled_output_schema_is_a_defensive_copy() -> None:
    compiler = TaskMaterializerV3Compiler(_curriculum())
    first = compiler.output_schema
    first["additionalProperties"] = True
    properties = first["properties"]
    assert isinstance(properties, dict)
    properties["evaluator_goal"] = {"type": "object"}

    second = compiler.output_schema
    assert second["additionalProperties"] is False
    second_properties = second["properties"]
    assert isinstance(second_properties, dict)
    assert "evaluator_goal" not in second_properties


def test_materialize_requires_exact_framework_call_echo() -> None:
    compiler = TaskMaterializerV3Compiler(_curriculum())
    with pytest.raises(TaskMaterializationError) as rejected:
        compiler.materialize(_call(), _output(seed=8))
    assert rejected.value.code == "call_echo_mismatch"

    with pytest.raises(TaskMaterializationError) as rejected:
        compiler.materialize(_call(), _output(difficulty={"scale": "large"}))
    assert rejected.value.code == "call_echo_mismatch"


def test_framework_call_validates_task_actor_and_complete_difficulty() -> None:
    compiler = TaskMaterializerV3Compiler(_curriculum())

    with pytest.raises(TaskMaterializationError) as rejected:
        compiler.validate_call(_call(task_type="unknown"))
    assert rejected.value.code == "unknown_task_type"

    with pytest.raises(TaskMaterializationError) as rejected:
        compiler.validate_call(_call(actor="intruder"))
    assert rejected.value.code == "actor_not_allowed"

    with pytest.raises(TaskMaterializationError) as rejected:
        compiler.validate_call(_call(difficulty={}))
    assert rejected.value.code == "difficulty_shape_mismatch"

    with pytest.raises(TaskMaterializationError) as rejected:
        compiler.validate_call(_call(difficulty={"scale": "impossible"}))
    assert rejected.value.code == "difficulty_level_invalid"


def test_call_arguments_exclude_framework_contract_metadata() -> None:
    call = _call()
    arguments = call.call_arguments()

    assert arguments == {
        "seed": 7,
        "task_type": "increase",
        "actor": "operator",
        "difficulty": {"scale": "small"},
    }
    assert "schema_version" not in arguments
    difficulty = arguments["difficulty"]
    assert isinstance(difficulty, dict)
    difficulty["scale"] = "large"
    assert call.difficulty == {"scale": "small"}


def test_task_requirement_owns_recursively_closed_candidate_schemas() -> None:
    compiler = TaskMaterializerV3Compiler(_curriculum())
    with pytest.raises(TaskMaterializationError) as rejected:
        compiler.materialize(
            _call(),
            _output(public_goal={"account": {"id": "a"}, "target": 9, "secret": 1}),
        )
    assert rejected.value.code == "candidate_schema_violation"

    values = _requirement().model_dump(mode="python")
    initial_schema = values["initial_config_schema"]
    assert isinstance(initial_schema, dict)
    properties = initial_schema["properties"]
    assert isinstance(properties, dict)
    context = properties["context"]
    assert isinstance(context, dict)
    context["additionalProperties"] = True
    with pytest.raises(ValidationError, match="additionalProperties=false"):
        TaskRequirement.model_validate(values)


def test_framework_instruction_is_deterministic_canonical_data() -> None:
    requirement = _requirement()
    left = render_public_instruction(
        requirement,
        {
            "target": 9,
            "display_hint": "Use the increment tool.",
            "account": {"id": "account-7"},
        },
    )
    right = render_public_instruction(
        requirement,
        {
            "account": {"id": "account-7"},
            "display_hint": "Use the increment tool.",
            "target": 9,
        },
    )
    assert left == right
    assert left.endswith(
        '{"account":{"id":"account-7"},'
        '"display_hint":"Use the increment tool.","target":9}'
    )


def test_identity_projection_is_complete_nested_and_deep_copied() -> None:
    requirement = _requirement()
    public_goal: dict[str, JsonValue] = {
        "target": 9,
        "account": {"id": "account-7"},
        "display_hint": "Agent-visible but evaluator-unused.",
    }
    projected = project_evaluator_goal(requirement, public_goal)
    assert projected == {"target": 9, "account": {"id": "account-7"}}
    assert projected is not public_goal
    assert projected["account"] is not public_goal["account"]

    account = public_goal["account"]
    assert isinstance(account, dict)
    account["id"] = "mutated"
    assert projected["account"] == {"id": "account-7"}


def test_requirement_binds_every_evaluator_required_leaf_exactly_once() -> None:
    base = _requirement()
    values = base.model_dump(mode="python", exclude={"evaluator_goal_bindings"})
    with pytest.raises(ValidationError, match="cover exactly every required evaluator leaf"):
        TaskRequirement(
            **values,
            evaluator_goal_bindings=(
                EvaluatorGoalBinding(
                    binding_id="binding:target",
                    public_pointer="/target",
                    evaluator_pointer="/target",
                ),
            ),
        )


def test_task_goal_rules_may_read_only_required_projected_leaves() -> None:
    base = _requirement()
    values = base.model_dump(mode="python", exclude={"success_conditions"})
    with pytest.raises(ValidationError, match="non-required or unprojected"):
        TaskRequirement(
            **values,
            success_conditions=(_goal_rule("rule:parent", "task_success", "/account"),),
        )


def test_rfc6901_escaped_identity_binding_is_executed_not_interpreted() -> None:
    base = _requirement()
    escaped_schema: dict[str, JsonValue] = {
        "type": "object",
        "properties": {"target/value": {"type": "integer"}},
        "required": ["target/value"],
        "additionalProperties": False,
    }
    values = base.model_dump(
        mode="python",
        exclude={
            "success_conditions",
            "terminal_conditions",
            "public_goal_schema",
            "evaluator_goal_schema",
            "evaluator_goal_bindings",
        },
    )
    requirement = TaskRequirement(
        **values,
        success_conditions=(
            _goal_rule("rule:escaped", "task_success", pointer="/target~1value"),
        ),
        terminal_conditions=(
            _goal_rule("rule:escaped-terminal", "task_terminal", pointer="/target~1value"),
        ),
        public_goal_schema=escaped_schema,
        evaluator_goal_schema=escaped_schema,
        evaluator_goal_bindings=(
            EvaluatorGoalBinding(
                binding_id="binding:escaped",
                public_pointer="/target~1value",
                evaluator_pointer="/target~1value",
            ),
        ),
    )
    assert project_evaluator_goal(requirement, {"target/value": 11}) == {"target/value": 11}


def test_framework_envelope_owns_instruction_goal_and_materializer_digest() -> None:
    envelope = TaskMaterializerV3Compiler(_curriculum()).materialize(_call(), _output())

    assert envelope.call == _call()
    assert envelope.materialization.call() == envelope.call
    assert envelope.materializer_digest == envelope.materialization.content_digest()
    assert envelope.evaluator_goal == {"account": {"id": "account-7"}, "target": 9}
    assert envelope.public_instruction.startswith("Increase the counter")
    assert set(envelope.materialization.model_fields_set) == {
        "schema_version",
        "task_schema_version",
        "seed",
        "task_type",
        "actor",
        "difficulty",
        "public_goal",
        "initial_config",
    }
