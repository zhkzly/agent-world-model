"""Judge-private, data-only Verifier IR.

The IR is interpreted by framework code.  Challenger supplies only domain
inputs plus obligations against already-existing typed WorldSpec rules.  It
cannot invent a JSON-pointer assertion and attach an arbitrary ``rule_id``.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, JsonValue, model_validator

from .action import RuntimeAction, reject_evaluator_only_values
from .base import (
    ArtifactRef,
    ContentHash,
    Identifier,
    NonEmptyStr,
    V2Contract,
    canonical_json_bytes,
    sha256_digest,
)
from .reachability import ParameterizedSolveRecipe

MAX_VERIFIER_CASES = 64


class RuntimeCaseInput(V2Contract):
    """The complete case subset that the Judge is allowed to send to Runtime."""

    seed: Annotated[int, Field(ge=0, le=18_446_744_073_709_551_615)]
    actor: Identifier
    reset_config: dict[str, JsonValue] = Field(default_factory=dict)
    actions: Annotated[tuple[RuntimeAction, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def reject_judge_values(self) -> RuntimeCaseInput:
        reject_evaluator_only_values(self.reset_config)
        return self


class VerifierAssertion(V2Contract):
    """One framework-evaluated obligation against the canonical Rule IR."""

    assertion_id: Identifier
    rule_id: Identifier
    action_index: Annotated[int, Field(ge=0)]
    expected: bool


class VerifierCase(V2Contract):
    """Private case metadata plus the exact runtime inputs and Judge assertions."""

    case_id: Identifier
    partition: Literal["public", "repair", "sealed"]
    task_type: Identifier
    evaluator_goal: dict[str, JsonValue]
    seed: Annotated[int, Field(ge=0, le=18_446_744_073_709_551_615)]
    actor: Identifier
    reset_config: dict[str, JsonValue] = Field(default_factory=dict)
    actions: Annotated[tuple[RuntimeAction, ...], Field(min_length=1, max_length=32)]
    assertions: Annotated[tuple[VerifierAssertion, ...], Field(min_length=1, max_length=128)]

    @model_validator(mode="after")
    def validate_action_indexes(self) -> VerifierCase:
        reject_evaluator_only_values(self.reset_config)
        upper = len(self.actions)
        for assertion in self.assertions:
            if assertion.action_index >= upper:
                raise ValueError(
                    f"assertion {assertion.assertion_id} references an unknown action index"
                )
        assertion_ids = [item.assertion_id for item in self.assertions]
        if len(set(assertion_ids)) != len(assertion_ids):
            raise ValueError("VerifierAssertion ids must be unique within a case")
        obligations = [(item.rule_id, item.action_index, item.expected) for item in self.assertions]
        if len(set(obligations)) != len(obligations):
            raise ValueError("duplicate rule obligation within a case")
        return self

    def runtime_input(self) -> RuntimeCaseInput:
        return RuntimeCaseInput(
            seed=self.seed,
            actor=self.actor,
            reset_config=self.reset_config,
            actions=self.actions,
        )


class VerifierProperty(V2Contract):
    property_id: Identifier
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
    rule_ids: Annotated[tuple[Identifier, ...], Field(min_length=1)]
    case_ids: Annotated[tuple[Identifier, ...], Field(min_length=1)]
    hard: bool = True
    description: NonEmptyStr


class VerifierIR(V2Contract):
    verifier_ir_id: Identifier
    revision: Annotated[int, Field(ge=1)]
    world_spec_ref: ArtifactRef
    design_ref: ArtifactRef
    properties: Annotated[tuple[VerifierProperty, ...], Field(min_length=1)]
    cases: Annotated[
        tuple[VerifierCase, ...],
        Field(min_length=2, max_length=MAX_VERIFIER_CASES),
    ]
    solve_recipes: Annotated[tuple[ParameterizedSolveRecipe, ...], Field(max_length=64)] = ()

    @model_validator(mode="after")
    def validate_ir_references(self) -> VerifierIR:
        case_ids = [case.case_id for case in self.cases]
        property_ids = [item.property_id for item in self.properties]
        if len(set(case_ids)) != len(case_ids):
            raise ValueError("VerifierCase ids must be unique")
        if len(set(property_ids)) != len(property_ids):
            raise ValueError("VerifierProperty ids must be unique")
        case_set = set(case_ids)
        for item in self.properties:
            if not set(item.case_ids) <= case_set:
                raise ValueError(f"property {item.property_id} references unknown cases")
        total_actions = sum(len(case.actions) for case in self.cases)
        total_assertions = sum(len(case.assertions) for case in self.cases)
        if total_actions > 512 or total_assertions > 2048:
            raise ValueError("VerifierIR exceeds framework execution limits")
        recipe_ids = [recipe.recipe_id for recipe in self.solve_recipes]
        if len(set(recipe_ids)) != len(recipe_ids):
            raise ValueError("ParameterizedSolveRecipe ids must be unique")
        preferred_task_types = [
            recipe.task_type for recipe in self.solve_recipes if recipe.preferred
        ]
        if len(set(preferred_task_types)) != len(preferred_task_types):
            raise ValueError("each task type may have at most one preferred solve recipe")
        return self

    def persistence_projection(self) -> VerifierIRProjection:
        """Remove all sealed seeds, actions, actual/expected values before persistence."""

        public_cases = tuple(case for case in self.cases if case.partition != "sealed")
        sealed_cases = tuple(case for case in self.cases if case.partition == "sealed")
        recipe_task_type_counts: dict[str, int] = {}
        for recipe in self.solve_recipes:
            recipe_task_type_counts[recipe.task_type] = (
                recipe_task_type_counts.get(recipe.task_type, 0) + 1
            )
        recipe_commitment: ContentHash = sha256_digest(
            canonical_json_bytes(
                [recipe.model_dump(mode="json") for recipe in self.solve_recipes]
            )
        )
        return VerifierIRProjection(
            verifier_ir_id=self.verifier_ir_id,
            revision=self.revision,
            world_spec_ref=self.world_spec_ref,
            design_ref=self.design_ref,
            properties=tuple(
                VerifierPropertyProjection(
                    property_id=item.property_id,
                    kind=item.kind,
                    rule_ids=item.rule_ids,
                    hard=item.hard,
                )
                for item in self.properties
            ),
            public_and_repair_cases=public_cases,
            sealed_case_count=len(sealed_cases),
            sealed_action_count=sum(len(case.actions) for case in sealed_cases),
            sealed_obligation_count=sum(len(case.assertions) for case in sealed_cases),
            solve_recipe_count=len(self.solve_recipes),
            solve_recipe_task_type_counts=recipe_task_type_counts,
            solve_recipe_commitment=recipe_commitment,
        )


class VerifierPropertyProjection(V2Contract):
    property_id: Identifier
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
    rule_ids: Annotated[tuple[Identifier, ...], Field(min_length=1)]
    hard: bool


class VerifierIRProjection(V2Contract):
    """Durable projection; sealed case material exists only in Judge memory."""

    verifier_ir_id: Identifier
    revision: Annotated[int, Field(ge=1)]
    world_spec_ref: ArtifactRef
    design_ref: ArtifactRef
    properties: Annotated[tuple[VerifierPropertyProjection, ...], Field(min_length=1)]
    public_and_repair_cases: tuple[VerifierCase, ...] = ()
    sealed_case_count: Annotated[int, Field(ge=1, le=64)]
    sealed_action_count: Annotated[int, Field(ge=1, le=512)]
    sealed_obligation_count: Annotated[int, Field(ge=1, le=2048)]
    solve_recipe_count: Annotated[int, Field(ge=0, le=64)] = 0
    solve_recipe_task_type_counts: dict[Identifier, Annotated[int, Field(ge=1)]] = Field(
        default_factory=dict
    )
    solve_recipe_commitment: ContentHash

    @model_validator(mode="after")
    def validate_recipe_projection(self) -> VerifierIRProjection:
        if sum(self.solve_recipe_task_type_counts.values()) != self.solve_recipe_count:
            raise ValueError("solve recipe projection counts do not close")
        return self


__all__ = [
    "MAX_VERIFIER_CASES",
    "RuntimeAction",
    "RuntimeCaseInput",
    "VerifierAssertion",
    "VerifierCase",
    "VerifierIR",
    "VerifierIRProjection",
    "VerifierProperty",
    "VerifierPropertyProjection",
]
