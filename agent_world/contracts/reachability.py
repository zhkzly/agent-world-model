"""Closed contracts for independently proving generated task reachability.

The candidate task materializer never supplies a solution.  A framework-owned
strategy either instantiates one of these bounded Challenger-authored recipes
or drives a fresh Challenger session against the real episode.  Only the
Judge can issue a certificate after observing trusted success and termination.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, JsonValue, model_validator

from agent_world.agent_output_authority import (
    AgentOutputAuthority,
    EpisodeActionProposalOutput,
    register_agent_output_contract,
)

from .action import RuntimeAction
from .base import ArtifactRef, ContentHash, Identifier, NonEmptyStr, V2Contract
from .jobs import BudgetUsage


def _validate_pointer(pointer: str) -> None:
    if not pointer.startswith("/") or pointer == "/":
        raise ValueError("recipe pointers must be non-root RFC 6901 JSON pointers")
    if len(pointer) > 4096 or pointer.count("/") > 32:
        raise ValueError("recipe pointer exceeds framework limits")
    index = 0
    while index < len(pointer):
        if pointer[index] == "~":
            if index + 1 >= len(pointer) or pointer[index + 1] not in {"0", "1"}:
                raise ValueError("recipe pointer contains an invalid RFC 6901 escape")
            index += 1
        index += 1


class RecipeLiteral(V2Contract):
    kind: Literal["literal"] = "literal"
    value: JsonValue


class RecipePointer(V2Contract):
    """One safe value source visible to the solving Agent.

    ``initial_config``, evaluator goal, full snapshots, Rule IR and candidate
    source are intentionally absent.  Previous values are the same public
    result/observation envelopes that a training Agent would have received.
    """

    kind: Literal["pointer"] = "pointer"
    source: Literal[
        "public_goal",
        "reset_observation",
        "previous_tool_result",
        "previous_observation",
    ]
    pointer: NonEmptyStr
    previous_step_index: Annotated[int, Field(ge=0, le=31)] | None = None

    @model_validator(mode="after")
    def validate_source(self) -> RecipePointer:
        _validate_pointer(self.pointer)
        previous = self.source in {"previous_tool_result", "previous_observation"}
        if previous != (self.previous_step_index is not None):
            raise ValueError("previous result/observation sources require exactly one step index")
        return self


type RecipeArgument = Annotated[RecipeLiteral | RecipePointer, Field(discriminator="kind")]


class ParameterizedSolveStep(V2Contract):
    step_id: Identifier
    tool_id: Identifier
    arguments: dict[str, RecipeArgument] = Field(default_factory=dict)


class ParameterizedSolveRecipe(V2Contract):
    """A bounded action template, not a general programming language or proof."""

    recipe_id: Identifier
    task_type: Identifier
    preferred: bool = False
    steps: Annotated[tuple[ParameterizedSolveStep, ...], Field(min_length=1, max_length=32)]

    @model_validator(mode="after")
    def validate_steps(self) -> ParameterizedSolveRecipe:
        step_ids = [step.step_id for step in self.steps]
        if len(set(step_ids)) != len(step_ids):
            raise ValueError("solve recipe step ids must be unique")
        for index, step in enumerate(self.steps):
            for argument in step.arguments.values():
                if (
                    isinstance(argument, RecipePointer)
                    and argument.previous_step_index is not None
                    and argument.previous_step_index >= index
                ):
                    raise ValueError("solve recipe may only read results of earlier steps")
        return self


class ReachabilityPolicy(V2Contract):
    """Release/serve assurance without pretending a finite gate proves all seeds."""

    # Per-instance serve certification is intentionally not exposed until the
    # credential-free Consumer can execute the same independent certifier.  A
    # published policy must therefore match the only end-to-end executable mode.
    mode: Literal["sampled_release"] = "sampled_release"
    samples_per_task_actor: Annotated[int, Field(ge=1, le=64)] = 1
    random_tail_samples: Annotated[int, Field(ge=0, le=256)] = 1
    maximum_solver_attempts: Annotated[int, Field(ge=1, le=8)] = 2
    maximum_steps_per_attempt: Annotated[int, Field(ge=1, le=32)] = 16
    maximum_agent_turns_per_attempt: Annotated[int, Field(ge=1, le=64)] = 8
    maximum_llm_tokens_per_attempt: Annotated[int, Field(ge=1, le=131_072)] = 4_096
    maximum_wall_seconds_per_attempt: Annotated[float, Field(gt=0, le=900)] = 60


class ReachabilityInstance(V2Contract):
    """Exact private identity of one materialized task selected by framework code."""

    instance_id: Identifier
    materialization_digest: ContentHash
    seed: Annotated[int, Field(ge=0, le=2**64 - 1)]
    task_type: Identifier
    actor: Identifier
    difficulty: dict[str, JsonValue] = Field(default_factory=dict)


class InteractiveSolveDecision(EpisodeActionProposalOutput, V2Contract):
    """One Challenger decision; the declaration itself has no evaluator authority."""

    decision: Literal["action", "done", "blocked"]
    action: RuntimeAction | None = None
    reason: NonEmptyStr | None = None

    @model_validator(mode="after")
    def validate_decision(self) -> InteractiveSolveDecision:
        if self.decision == "action":
            if self.action is None or self.reason is not None:
                raise ValueError("action decisions require only an action")
        elif self.action is not None or self.reason is None:
            raise ValueError("done/blocked decisions require only a reason")
        return self


class ReachabilityAttempt(V2Contract):
    attempt_id: Identifier
    instance: ReachabilityInstance
    strategy: Literal["parameterized_recipe", "interactive_challenger"]
    strategy_version: NonEmptyStr
    status: Literal["certified", "failed", "inconclusive", "infrastructure_error"]
    executed_steps: Annotated[int, Field(ge=0, le=32)]
    executed_tool_ids: tuple[Identifier, ...] = ()
    trace_commitment: ContentHash | None = None
    solver_profile_hash: ContentHash | None = None
    budget_usage: BudgetUsage = Field(default_factory=BudgetUsage)
    failure_code: Identifier | None = None

    @model_validator(mode="after")
    def validate_terminal_shape(self) -> ReachabilityAttempt:
        if self.executed_steps != len(self.executed_tool_ids):
            raise ValueError("reachability step count must match executed tool ids")
        if self.status == "certified":
            if self.trace_commitment is None or self.failure_code is not None:
                raise ValueError("certified attempt requires a trace commitment and no failure")
        elif self.failure_code is None:
            raise ValueError("non-certified reachability attempts require a failure code")
        return self


class ReachabilityCertificate(V2Contract):
    """Judge-private certificate for one real, successfully executed task instance."""

    certificate_id: Identifier
    candidate_ref: ArtifactRef
    world_spec_hash: ContentHash
    runtime_source_ref: ArtifactRef
    task_materializer_ref: ArtifactRef
    renderer_version: NonEmptyStr
    projector_version: NonEmptyStr
    instance: ReachabilityInstance
    strategy: Literal["parameterized_recipe", "interactive_challenger"]
    strategy_version: NonEmptyStr
    executed_steps: Annotated[int, Field(ge=1, le=32)]
    executed_tool_ids: Annotated[tuple[Identifier, ...], Field(min_length=1, max_length=32)]
    final_state_digest: ContentHash
    trace_commitment: ContentHash
    certified_at: AwareDatetime

    @model_validator(mode="after")
    def validate_execution_shape(self) -> ReachabilityCertificate:
        if self.executed_steps != len(self.executed_tool_ids):
            raise ValueError("certificate step count must match executed tool ids")
        return self


class ReachabilityPublicEvidence(V2Contract):
    """Publishable aggregate; sealed seeds, recipes and action traces stay private."""

    release_claim: Literal["finite-stratified-sample-only"] = "finite-stratified-sample-only"
    campaign_commitment: ContentHash
    candidate_ref: ArtifactRef
    materialized_instances: Annotated[int, Field(ge=1)]
    certified_instances: Annotated[int, Field(ge=1)]
    failed_instances: Annotated[int, Field(ge=0)] = 0
    task_type_counts: dict[Identifier, Annotated[int, Field(ge=1)]]
    strategy_counts: dict[Identifier, Annotated[int, Field(ge=1)]]
    serve_policy_counts: dict[Identifier, Annotated[int, Field(ge=1)]]
    budget_usage: BudgetUsage = Field(default_factory=BudgetUsage)

    @model_validator(mode="after")
    def validate_counts(self) -> ReachabilityPublicEvidence:
        if self.certified_instances + self.failed_instances != self.materialized_instances:
            raise ValueError("reachability aggregate counts do not close")
        if sum(self.task_type_counts.values()) != self.materialized_instances:
            raise ValueError("task type reachability counts do not close")
        if sum(self.strategy_counts.values()) != self.certified_instances:
            raise ValueError("strategy counts must describe certified instances")
        if sum(self.serve_policy_counts.values()) != self.materialized_instances:
            raise ValueError("serve policy counts must describe every materialized instance")
        if self.serve_policy_counts != {"sampled_release": self.materialized_instances}:
            raise ValueError(
                "all published reachability samples must use the executable sampled_release mode"
            )
        return self


register_agent_output_contract(
    InteractiveSolveDecision,
    authority=AgentOutputAuthority.EPISODE_ACTION_PROPOSAL,
)


__all__ = [
    "InteractiveSolveDecision",
    "ParameterizedSolveRecipe",
    "ParameterizedSolveStep",
    "ReachabilityAttempt",
    "ReachabilityCertificate",
    "ReachabilityInstance",
    "ReachabilityPolicy",
    "ReachabilityPublicEvidence",
    "RecipeArgument",
    "RecipeLiteral",
    "RecipePointer",
]
