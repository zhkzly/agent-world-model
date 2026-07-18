"""Framework-owned Task Materializer v3 compilation and validation.

Candidate code receives a framework-selected :class:`TaskMaterializerCall` and
may emit only public task parameters plus Runtime reset configuration.  The
framework deterministically renders the instruction and identity-projects the
public goal into the evaluator-only goal declared by the frozen curriculum.
There is no candidate-authored answer, witness, evaluator goal, or fallback to
the task-v2 boundary.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Mapping
from typing import Any, cast

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from pydantic import JsonValue, ValidationError

from agent_world.contracts.base import canonical_json_bytes
from agent_world.contracts.design import CurriculumRequirements, TaskRequirement
from agent_world.contracts.task import (
    TASK_MATERIALIZATION_SCHEMA_VERSION,
    FrameworkTaskEnvelope,
    TaskMaterializationV3,
    TaskMaterializerCall,
)

TASK_MATERIALIZER_OUTPUT_SCHEMA_ID = "urn:agent-world:task-materialization:v3"
MAX_PUBLIC_INSTRUCTION_BYTES = 64 * 1024
_MAX_POINTER_LENGTH = 4096
_MAX_POINTER_SEGMENTS = 32


class TaskMaterializationError(ValueError):
    """A classified design-contract or candidate-materialization rejection."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class TaskMaterializerV3Compiler:
    """Immutable framework compiler for one committed curriculum revision."""

    __slots__ = (
        "_base_validator",
        "_branch_validators",
        "_curriculum",
        "_output_schema",
        "_requirements",
    )

    def __init__(self, curriculum: CurriculumRequirements) -> None:
        self._curriculum = CurriculumRequirements.model_validate_json(
            curriculum.stable_json_bytes()
        )
        self._requirements = {
            requirement.task_type: requirement for requirement in self._curriculum.task_types
        }
        self._output_schema = _compile_output_schema(self._curriculum)
        base_schema = copy.deepcopy(self._output_schema)
        branches = base_schema.pop("oneOf")
        assert isinstance(branches, list)
        self._base_validator = Draft202012Validator(base_schema)
        self._branch_validators: dict[str, Draft202012Validator] = {}
        for branch in branches:
            assert isinstance(branch, dict)
            properties = branch["properties"]
            assert isinstance(properties, dict)
            task_schema = properties["task_type"]
            assert isinstance(task_schema, dict)
            task_type = task_schema["const"]
            assert isinstance(task_type, str)
            self._branch_validators[task_type] = Draft202012Validator(branch)

    @property
    def output_schema(self) -> dict[str, JsonValue]:
        """Return a defensive copy of the closed candidate output schema."""

        return copy.deepcopy(self._output_schema)

    @property
    def curriculum_digest(self) -> str:
        return self._curriculum.content_digest()

    def validate_call(self, call: TaskMaterializerCall) -> TaskMaterializerCall:
        """Validate and defensively freeze a framework-selected callable input."""

        frozen = TaskMaterializerCall.model_validate_json(call.stable_json_bytes())
        requirement = self._requirements.get(frozen.task_type)
        if requirement is None:
            raise TaskMaterializationError(
                "unknown_task_type",
                f"task materializer call references unknown task type {frozen.task_type}",
            )
        if frozen.actor not in requirement.allowed_actor_ids:
            raise TaskMaterializationError(
                "actor_not_allowed",
                f"actor {frozen.actor} is not allowed for task type {frozen.task_type}",
            )
        dimensions = {
            dimension.dimension: dimension for dimension in self._curriculum.difficulty_dimensions
        }
        expected = frozenset(requirement.difficulty_dimensions)
        actual = frozenset(frozen.difficulty)
        if actual != expected:
            raise TaskMaterializationError(
                "difficulty_shape_mismatch",
                f"task {frozen.task_type} difficulty keys must be exactly {sorted(expected)}",
            )
        for dimension_id in requirement.difficulty_dimensions:
            value = frozen.difficulty[dimension_id]
            if not isinstance(value, str) or value not in dimensions[dimension_id].levels:
                raise TaskMaterializationError(
                    "difficulty_level_invalid",
                    f"task {frozen.task_type} has invalid level for {dimension_id}",
                )
        return frozen

    def materialize(
        self,
        call: TaskMaterializerCall,
        candidate_output: Mapping[str, Any],
    ) -> FrameworkTaskEnvelope:
        """Validate candidate JSON and create the framework-private task envelope."""

        frozen_call = self.validate_call(call)
        normalized = _copy_json_object(candidate_output, error_code="candidate_json_invalid")
        schema_errors = sorted(
            (
                *self._base_validator.iter_errors(normalized),
                *self._branch_validators[frozen_call.task_type].iter_errors(normalized),
            ),
            key=lambda error: (tuple(str(item) for item in error.path), error.message),
        )
        if schema_errors:
            all_diagnostics = tuple(
                dict.fromkeys(_schema_error_diagnostic(error) for error in schema_errors)
            )
            diagnostics = all_diagnostics[:16]
            suffix = (
                f"; ... {len(all_diagnostics) - 16} more"
                if len(all_diagnostics) > 16
                else ""
            )
            raise TaskMaterializationError(
                "candidate_schema_violation",
                "task materialization violates its task-specific v3 output schema: "
                + "; ".join(diagnostics)
                + suffix,
            )
        try:
            materialization = TaskMaterializationV3.model_validate(normalized)
        except ValidationError as exc:
            raise TaskMaterializationError(
                "candidate_contract_violation",
                "task materialization violates the typed v3 contract",
            ) from exc
        if materialization.call() != frozen_call:
            raise TaskMaterializationError(
                "call_echo_mismatch",
                "task materialization must echo the exact framework-selected call",
            )

        requirement = self._requirements[frozen_call.task_type]
        _validate_instance_schema(
            requirement.public_goal_schema,
            materialization.public_goal,
            code="public_goal_schema_violation",
            label=f"task {frozen_call.task_type} public_goal",
        )
        _validate_instance_schema(
            requirement.initial_config_schema,
            materialization.initial_config,
            code="initial_config_schema_violation",
            label=f"task {frozen_call.task_type} initial_config",
        )
        instruction = render_public_instruction(requirement, materialization.public_goal)
        evaluator_goal = project_evaluator_goal(requirement, materialization.public_goal)
        return FrameworkTaskEnvelope(
            call=frozen_call,
            materialization=materialization,
            public_instruction=instruction,
            evaluator_goal=evaluator_goal,
            materializer_digest=materialization.content_digest(),
        )


def compile_task_materializer_output_schema(
    curriculum: CurriculumRequirements,
) -> dict[str, JsonValue]:
    """Compile the closed output schema from the curriculum itself."""

    return TaskMaterializerV3Compiler(curriculum).output_schema


def render_public_instruction(
    requirement: TaskRequirement,
    public_goal: Mapping[str, JsonValue],
) -> str:
    """Render a deterministic instruction from framework-owned objective and goal."""

    _validate_instance_schema(
        requirement.public_goal_schema,
        public_goal,
        code="public_goal_schema_violation",
        label=f"task {requirement.task_type} public_goal",
    )
    canonical_goal = canonical_json_bytes(public_goal).decode("utf-8")
    rendered = (
        f"{requirement.objective}\n\n"
        "Machine-readable public goal (canonical JSON):\n"
        f"{canonical_goal}"
    )
    if len(rendered.encode("utf-8")) > MAX_PUBLIC_INSTRUCTION_BYTES:
        raise TaskMaterializationError(
            "public_instruction_too_large",
            "framework-rendered public instruction exceeds the v3 byte limit",
        )
    return rendered


def project_evaluator_goal(
    requirement: TaskRequirement,
    public_goal: Mapping[str, JsonValue],
) -> dict[str, JsonValue]:
    """Identity-project all required evaluator leaves from a validated public goal."""

    _validate_instance_schema(
        requirement.public_goal_schema,
        public_goal,
        code="public_goal_schema_violation",
        label=f"task {requirement.task_type} public_goal",
    )
    result: dict[str, JsonValue] = {}
    for binding in requirement.evaluator_goal_bindings:
        value = _resolve_pointer(public_goal, binding.public_pointer)
        _assign_pointer(result, binding.evaluator_pointer, copy.deepcopy(value))
    _validate_instance_schema(
        requirement.evaluator_goal_schema,
        result,
        code="evaluator_goal_projection_invalid",
        label=f"task {requirement.task_type} evaluator_goal projection",
    )
    return result


def _compile_output_schema(curriculum: CurriculumRequirements) -> dict[str, JsonValue]:
    dimensions = {dimension.dimension: dimension for dimension in curriculum.difficulty_dimensions}
    branches: list[JsonValue] = []
    for requirement in curriculum.task_types:
        difficulty_properties: dict[str, JsonValue] = {
            dimension_id: {
                "type": "string",
                "enum": list(dimensions[dimension_id].levels),
            }
            for dimension_id in requirement.difficulty_dimensions
        }
        branches.append(
            {
                "type": "object",
                "properties": {
                    "task_type": {"const": requirement.task_type},
                    "actor": {"enum": list(requirement.allowed_actor_ids)},
                    "difficulty": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": list(requirement.difficulty_dimensions),
                        "properties": difficulty_properties,
                    },
                    "public_goal": copy.deepcopy(requirement.public_goal_schema),
                    "initial_config": copy.deepcopy(requirement.initial_config_schema),
                },
                "required": [
                    "task_type",
                    "actor",
                    "difficulty",
                    "public_goal",
                    "initial_config",
                ],
            }
        )
    schema: dict[str, JsonValue] = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": TASK_MATERIALIZER_OUTPUT_SCHEMA_ID,
        "type": "object",
        "additionalProperties": False,
        "required": [
            "schema_version",
            "task_schema_version",
            "seed",
            "task_type",
            "actor",
            "difficulty",
            "public_goal",
            "initial_config",
        ],
        "properties": {
            "schema_version": {"const": "v2"},
            "task_schema_version": {"const": TASK_MATERIALIZATION_SCHEMA_VERSION},
            "seed": {"type": "integer", "minimum": 0, "maximum": 2**64 - 1},
            "task_type": {
                "type": "string",
                "enum": [requirement.task_type for requirement in curriculum.task_types],
            },
            "actor": {"type": "string", "minLength": 1, "maxLength": 160},
            "difficulty": {"type": "object"},
            "public_goal": {"type": "object"},
            "initial_config": {"type": "object"},
        },
        "oneOf": branches,
    }
    Draft202012Validator.check_schema(schema)
    return schema


def _validate_instance_schema(
    schema: Mapping[str, JsonValue],
    value: Mapping[str, JsonValue],
    *,
    code: str,
    label: str,
) -> None:
    errors = sorted(
        Draft202012Validator(schema).iter_errors(value),
        key=lambda error: (tuple(str(item) for item in error.path), error.message),
    )
    if errors:
        first = errors[0]
        path = "/".join(str(item) for item in first.path) or "<root>"
        raise TaskMaterializationError(code, f"{label} violates its schema at {path}")


def _schema_error_diagnostic(error: JsonSchemaValidationError) -> str:
    path = "/" + "/".join(str(item) for item in error.absolute_path)
    if path == "/":
        path = "<root>"
    keyword = str(error.validator)
    detail = ""
    if keyword == "required" and isinstance(error.instance, Mapping):
        required = error.validator_value
        if isinstance(required, list):
            missing = sorted(
                item for item in required if isinstance(item, str) and item not in error.instance
            )
            detail = f" missing={missing}"
    elif keyword == "additionalProperties" and isinstance(error.instance, Mapping):
        properties = error.schema.get("properties", {})
        if isinstance(properties, dict):
            unexpected = sorted(str(item) for item in set(error.instance) - set(properties))
            detail = f" unexpected={unexpected}"
    elif keyword == "type":
        detail = f" expected={error.validator_value}"
    elif keyword == "format":
        detail = f" expected={error.validator_value}"
    return f"path={path} keyword={keyword}{detail}"


def _resolve_pointer(value: Mapping[str, JsonValue], pointer: str) -> JsonValue:
    current: JsonValue = cast(dict[str, JsonValue], value)
    for token in _decode_pointer(pointer, label="public goal binding"):
        if not isinstance(current, dict) or token not in current:
            raise TaskMaterializationError(
                "public_goal_pointer_missing",
                f"required public goal pointer {pointer} is absent",
            )
        current = current[token]
    return current


def _assign_pointer(target: dict[str, JsonValue], pointer: str, value: JsonValue) -> None:
    tokens = _decode_pointer(pointer, label="evaluator goal binding")
    current = target
    for token in tokens[:-1]:
        existing = current.get(token)
        if existing is None:
            child: dict[str, JsonValue] = {}
            current[token] = child
            current = child
        elif isinstance(existing, dict):
            current = existing
        else:
            raise TaskMaterializationError(
                "evaluator_projection_collision",
                f"evaluator goal pointer {pointer} collides with another binding",
            )
    final = tokens[-1]
    if final in current:
        raise TaskMaterializationError(
            "evaluator_projection_collision",
            f"evaluator goal pointer {pointer} is assigned more than once",
        )
    current[final] = value


def _decode_pointer(pointer: str, *, label: str) -> tuple[str, ...]:
    if not pointer.startswith("/") or pointer == "/":
        raise ValueError(f"{label} must be a non-root RFC 6901 JSON pointer")
    if len(pointer) > _MAX_POINTER_LENGTH or pointer.count("/") > _MAX_POINTER_SEGMENTS:
        raise ValueError(f"{label} exceeds framework pointer limits")
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


def _copy_json_object(
    value: Mapping[str, Any],
    *,
    error_code: str = "contract_json_invalid",
) -> dict[str, JsonValue]:
    try:
        encoded = canonical_json_bytes(value)
        decoded = cast(object, json.loads(encoded))
    except (TypeError, ValueError) as exc:
        raise TaskMaterializationError(error_code, "value is not canonical JSON") from exc
    if not isinstance(decoded, dict) or not all(isinstance(key, str) for key in decoded):
        raise TaskMaterializationError(error_code, "value must be a JSON object")
    return cast(dict[str, JsonValue], decoded)


__all__ = [
    "MAX_PUBLIC_INSTRUCTION_BYTES",
    "TASK_MATERIALIZER_OUTPUT_SCHEMA_ID",
    "TaskMaterializationError",
    "TaskMaterializerV3Compiler",
    "compile_task_materializer_output_schema",
    "project_evaluator_goal",
    "render_public_instruction",
]
