"""Task Materializer v3 contracts with no candidate-owned evaluator authority."""

from __future__ import annotations

import copy
from typing import Annotated, Literal

from pydantic import Field, JsonValue, model_validator

from .base import ContentHash, Identifier, NonEmptyStr, V2Contract

TASK_MATERIALIZER_PROTOCOL: Literal["python-callable-v3"] = "python-callable-v3"
TASK_MATERIALIZATION_SCHEMA_VERSION: Literal["task-materialization-v3"] = (
    "task-materialization-v3"
)
TASK_INSTRUCTION_RENDERER_VERSION: Literal["objective-public-goal-v1"] = (
    "objective-public-goal-v1"
)
EVALUATOR_GOAL_PROJECTOR_VERSION: Literal["identity-bindings-v1"] = "identity-bindings-v1"


class TaskMaterializerCall(V2Contract):
    """Framework-selected inputs; a candidate may not choose its own test identity."""

    seed: Annotated[int, Field(ge=0, le=2**64 - 1)]
    task_type: Identifier
    actor: Identifier
    difficulty: dict[str, JsonValue] = Field(default_factory=dict)

    def call_arguments(self) -> dict[str, JsonValue]:
        """Return the exact candidate ABI payload without framework schema metadata."""

        return {
            "seed": self.seed,
            "task_type": self.task_type,
            "actor": self.actor,
            "difficulty": copy.deepcopy(self.difficulty),
        }


class TaskMaterializationV3(V2Contract):
    """The complete and only candidate-authored task output.

    ``initial_config`` is Runtime reset input, not a private answer.  Instruction,
    evaluator goal, solution/witness, expected output and release metadata are
    deliberately absent.
    """

    task_schema_version: Literal["task-materialization-v3"] = (
        TASK_MATERIALIZATION_SCHEMA_VERSION
    )
    seed: Annotated[int, Field(ge=0, le=2**64 - 1)]
    task_type: Identifier
    actor: Identifier
    difficulty: dict[str, JsonValue] = Field(default_factory=dict)
    public_goal: dict[str, JsonValue]
    initial_config: dict[str, JsonValue]

    def call(self) -> TaskMaterializerCall:
        return TaskMaterializerCall(
            seed=self.seed,
            task_type=self.task_type,
            actor=self.actor,
            difficulty=copy.deepcopy(self.difficulty),
        )


class FrameworkTaskEnvelope(V2Contract):
    """Framework-private task after deterministic rendering and goal projection."""

    call: TaskMaterializerCall
    materialization: TaskMaterializationV3
    public_instruction: NonEmptyStr
    evaluator_goal: dict[str, JsonValue]
    materializer_digest: ContentHash
    renderer_version: Literal["objective-public-goal-v1"] = TASK_INSTRUCTION_RENDERER_VERSION
    projector_version: Literal["identity-bindings-v1"] = EVALUATOR_GOAL_PROJECTOR_VERSION

    @model_validator(mode="after")
    def validate_identity(self) -> FrameworkTaskEnvelope:
        if self.materialization.call() != self.call:
            raise ValueError("task materialization did not echo the exact framework call")
        if self.materialization.content_digest() != self.materializer_digest:
            raise ValueError("task materializer digest does not match canonical output")
        return self


__all__ = [
    "EVALUATOR_GOAL_PROJECTOR_VERSION",
    "FrameworkTaskEnvelope",
    "TASK_INSTRUCTION_RENDERER_VERSION",
    "TASK_MATERIALIZATION_SCHEMA_VERSION",
    "TASK_MATERIALIZER_PROTOCOL",
    "TaskMaterializationV3",
    "TaskMaterializerCall",
]
