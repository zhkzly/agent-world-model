"""Pure, frozen-input sizing for framework-owned Judge operations.

These functions size real Candidate work from the committed Design and
VerifierPlan.  They intentionally do not infer business meaning, inspect a
Candidate workspace, or initialize the Judge package.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from agent_world.contracts import CurriculumRequirements, EnvironmentDesign
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

    return {
        requirement.task_type: (
            len(requirement.allowed_actor_ids)
            * (
                max(
                    2,
                    curriculum.minimum_distinct_initial_states,
                    curriculum.minimum_distinct_tasks_per_type,
                    requirement.reachability_policy.samples_per_task_actor,
                )
                + 2 * len(requirement.difficulty_dimensions)
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
    paired_verifier_cases = 2 * sum(item.semantic_case_limit for item in verifier_plan.batches)
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
            task_calls
            + (design.verification.minimum_unknown_seed_episodes + 1)
            + task_calls
            + paired_verifier_cases
            + 2
        ),
    )


__all__ = [
    "JudgeOperationBudgetRequirements",
    "integration_budget_requirements",
    "release_without_interactive_budget_requirements",
    "task_materializer_call_counts",
]
