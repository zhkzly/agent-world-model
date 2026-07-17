"""Typed, framework-private records produced while judging a candidate."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, JsonValue

from agent_world.agent_output_authority import (
    AgentOutputAuthority,
    SemanticAdvisoryOutput,
    register_agent_output_contract,
)
from agent_world.contracts import (
    Identifier,
    NonEmptyStr,
    RuntimeAction,
    V2Contract,
    VerifierCase,
    VerifierProperty,
)
from agent_world.contracts.reachability import ParameterizedSolveRecipe


class RuntimeActionObservation(V2Contract):
    action_index: Annotated[int, Field(ge=0)]
    tool_id: Identifier
    arguments: dict[str, JsonValue]
    idempotency_key: NonEmptyStr
    response_ok: bool
    result: dict[str, JsonValue] | None = None
    error_code: Identifier | None = None
    error_message: str | None = None
    error_details: dict[str, JsonValue] = Field(default_factory=dict)
    events: JsonValue = Field(default_factory=list)
    pre_snapshot: dict[str, JsonValue]
    snapshot: dict[str, JsonValue]
    state_digest: JsonValue = None
    reward: Annotated[float, Field(allow_inf_nan=False)] | None = None
    terminated: bool | None = None
    truncated: bool | None = None
    trusted_reward: Annotated[float, Field(allow_inf_nan=False)] | None = None
    trusted_terminated: bool | None = None
    trusted_succeeded: bool | None = None
    trusted_failed: bool | None = None


class AssertionCheck(V2Contract):
    assertion_id: Identifier
    rule_id: Identifier
    passed: bool
    expected: bool
    observed: bool | None = None
    summary: NonEmptyStr


class CaseEvaluation(V2Contract):
    case_id: Identifier
    partition: Literal["public", "repair", "sealed"]
    seed: Annotated[int, Field(ge=0)]
    passed: bool
    reset_ok: bool
    actions: tuple[RuntimeActionObservation, ...]
    assertions: tuple[AssertionCheck, ...]
    failure_class: Identifier | None = None
    failure_summary: str | None = None


class VerifierDraft(V2Contract):
    """Framework-private verifier draft after ids, partitions, seeds, and Rules bind."""

    properties: Annotated[tuple[VerifierProperty, ...], Field(min_length=1)]
    cases: Annotated[tuple[VerifierCase, ...], Field(min_length=1)]
    solve_recipes: Annotated[tuple[ParameterizedSolveRecipe, ...], Field(max_length=64)] = ()


class PropertyExpectationIntent(V2Contract):
    """Compact semantic label expanded to exact Rule obligations by the framework."""

    kind: Literal[
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
    ]
    after_action_ordinal: Annotated[
        int,
        Field(
            ge=1,
            le=32,
            description=(
                "One-based action ordinal. For a trajectory containing one action, the only "
                "valid value is 1. Framework code compiles this to an internal zero-based index."
            ),
        ),
    ]
    expected: bool

    @property
    def action_index(self) -> int:
        """Framework-private zero-based index used by executable Verifier IR."""

        return self.after_action_ordinal - 1


class VerifierCaseIntent(V2Contract):
    """Agent-authored semantic trajectory without verifier control metadata."""

    task_type: Identifier
    evaluator_goal: dict[str, JsonValue]
    actor: Identifier
    reset_config: dict[str, JsonValue] = Field(default_factory=dict)
    actions: Annotated[tuple[RuntimeAction, ...], Field(min_length=1, max_length=32)]
    expectations: Annotated[
        tuple[PropertyExpectationIntent, ...],
        Field(min_length=1, max_length=64),
    ]

    @property
    def expectation_keys(self) -> frozenset[tuple[str, int, bool]]:
        return frozenset(
            (item.kind, item.action_index, item.expected) for item in self.expectations
        )


class BoundVerifierCaseIntent(V2Contract):
    """Framework-private case after disclosure identity and seed are bound."""

    case_id: Identifier
    partition: Literal["public", "repair", "sealed"]
    task_type: Identifier
    evaluator_goal: dict[str, JsonValue]
    seed: Annotated[int, Field(ge=0, le=18_446_744_073_709_551_615)]
    actor: Identifier
    reset_config: dict[str, JsonValue] = Field(default_factory=dict)
    actions: Annotated[tuple[RuntimeAction, ...], Field(min_length=1, max_length=32)]
    expectations: Annotated[
        tuple[PropertyExpectationIntent, ...],
        Field(min_length=1, max_length=64),
    ]


class VerifierIntent(SemanticAdvisoryOutput, V2Contract):
    """Small Challenger output; framework owns Rule closure and property bindings."""

    cases: Annotated[tuple[VerifierCaseIntent, ...], Field(min_length=2, max_length=64)]
    solve_recipes: Annotated[tuple[ParameterizedSolveRecipe, ...], Field(max_length=64)] = ()


class VerifierIntentCheckpoint(V2Contract):
    """Durable batch completion without persisting sealed trajectory inputs."""

    checkpoint_id: Identifier
    batch_index: Annotated[int, Field(ge=0)]
    context_hash: str
    public_and_repair_cases: tuple[BoundVerifierCaseIntent, ...] = ()
    sealed_case_count: Annotated[int, Field(ge=1, le=64)]
    sealed_commitment: str
    solve_recipe_count: Annotated[int, Field(ge=0, le=64)] = 0
    invocation_result_count: Annotated[int, Field(ge=1)]


register_agent_output_contract(
    VerifierIntent,
    authority=AgentOutputAuthority.SEMANTIC_ADVISORY,
)


__all__ = [
    "AssertionCheck",
    "BoundVerifierCaseIntent",
    "CaseEvaluation",
    "PropertyExpectationIntent",
    "RuntimeActionObservation",
    "VerifierCaseIntent",
    "VerifierDraft",
    "VerifierIntent",
    "VerifierIntentCheckpoint",
]
