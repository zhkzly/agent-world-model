"""Pure, frozen-input sizing for framework-owned Judge operations.

These functions size real Candidate work from the committed Design and
VerifierPlan.  They intentionally do not infer business meaning, inspect a
Candidate workspace, or initialize the Judge package.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from agent_world.contracts import (
    MAX_ACTORS_PER_TASK,
    MAX_DIFFICULTY_DIMENSIONS,
    MAX_DISTINCT_CURRICULUM_SAMPLES,
    CurriculumRequirements,
    EnvironmentDesign,
)
from agent_world.contracts.supply_chain import MAX_PUBLIC_TESTS

if TYPE_CHECKING:
    from agent_world.judge.models import VerifierBatchPlan

_MAX_ACTIONS_PER_VERIFIER_CASE = 32
_AGENT_WORKSPACE_PROJECTION_PROCESS_CALLS = 1


@dataclass(frozen=True, slots=True)
class JudgeOperationBudgetRequirements:
    """Non-wall operation dimensions derived from frozen framework inputs."""

    llm_tokens: int = 0
    agent_turns: int = 0
    tool_calls: int = 0
    evaluation_episodes: int = 0


def task_materializer_call_counts(
    curriculum: CurriculumRequirements,
) -> dict[str, int]:
    """Compile each task type's finite stratified materialization sample."""

    # Hard clamp even if a model bypassed the schema caps (defense-in-depth):
    # the budget engine must never amplify evaluation cost beyond framework
    # bounds.  actor/dimension counts and the distinctness floor are all
    # clamped so a malformed-but-valid-typed curriculum stays within budget.
    return {
        requirement.task_type: (
            min(len(requirement.allowed_actor_ids), MAX_ACTORS_PER_TASK)
            * (
                min(
                    max(
                        2,
                        curriculum.minimum_distinct_initial_states,
                        curriculum.minimum_distinct_tasks_per_type,
                        requirement.reachability_policy.samples_per_task_actor,
                    ),
                    MAX_DISTINCT_CURRICULUM_SAMPLES,
                )
                + 2 * min(len(requirement.difficulty_dimensions), MAX_DIFFICULTY_DIMENSIONS)
            )
            + requirement.reachability_policy.random_tail_samples
        )
        for requirement in curriculum.task_types
    }


def integration_budget_requirements(
    design: EnvironmentDesign,
) -> JudgeOperationBudgetRequirements:
    """Return the exact Integration reservation for one frozen Design."""

    task_calls = sum(task_materializer_call_counts(design.curriculum).values())
    return JudgeOperationBudgetRequirements(
        tool_calls=MAX_PUBLIC_TESTS + _AGENT_WORKSPACE_PROJECTION_PROCESS_CALLS + 2,
        evaluation_episodes=task_calls + 2,
    )


def release_without_interactive_budget_requirements(
    design: EnvironmentDesign,
    verifier_plan: VerifierBatchPlan,
) -> JudgeOperationBudgetRequirements:
    """Return the release envelope when its Judge has no hidden LLM solver.

    ``ReleaseAssuranceLeaf`` deliberately creates its Judge without an
    ``InteractiveChallengerStrategy``: model calls must have their own visible
    Scheduler nodes.  A final graph is frozen before Challenger output exists,
    so this is the largest real no-hidden-Agent path permitted by the frozen
    Design and VerifierPlan, rather than an arbitrary probe-count heuristic.
    """

    call_counts = task_materializer_call_counts(design.curriculum)
    task_calls = sum(call_counts.values())
    # The final graph is frozen before batch drafts reveal the exact VerifierIR.
    # It must therefore reserve the maximum number of cases the committed plan
    # permits, rather than treating the eventual number of cases as known.
    maximum_verifier_cases = sum(item.semantic_case_limit for item in verifier_plan.batches)
    paired_verifier_cases = 2 * maximum_verifier_cases
    recipe_tool_calls = sum(
        call_counts[requirement.task_type]
        * requirement.reachability_policy.maximum_steps_per_attempt
        for requirement in design.curriculum.task_types
    )
    return JudgeOperationBudgetRequirements(
        tool_calls=(
            recipe_tool_calls
            + paired_verifier_cases * _MAX_ACTIONS_PER_VERIFIER_CASE
            + MAX_PUBLIC_TESTS
            + _AGENT_WORKSPACE_PROJECTION_PROCESS_CALLS
            + 2
        ),
        evaluation_episodes=(
            # ``EnvironmentJudge.required_evaluation_episodes`` counts the
            # materialization pass itself and one possible additional recipe
            # attempt for every materialized task when a task allows two or
            # more solver attempts.  A no-hidden-Agent release graph cannot
            # know which batches will supply recipes, so freeze that maximum.
            task_calls
            + (design.verification.minimum_unknown_seed_episodes + 1)
            + 2 * task_calls
            + maximum_verifier_cases
            + 2
        ),
    )


__all__ = [
    "JudgeOperationBudgetRequirements",
    "integration_budget_requirements",
    "release_without_interactive_budget_requirements",
    "task_materializer_call_counts",
]
