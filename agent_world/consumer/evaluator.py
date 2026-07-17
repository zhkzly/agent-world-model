"""Framework-owned evaluator for the portable closed Rule IR in envpkg v3."""

from __future__ import annotations

from dataclasses import dataclass

from agent_world.contracts import (
    CurriculumRequirements,
    TrustedEvaluatorSpec,
    WorldSpec,
)
from agent_world.judge.rules import (
    RewardEvaluation,
    RuleExecutionContext,
    evaluate_task_reward_contract,
)


@dataclass(frozen=True, slots=True)
class PortableTrustedEvaluator:
    world_spec: WorldSpec
    curriculum: CurriculumRequirements
    evaluator_spec: TrustedEvaluatorSpec

    def __post_init__(self) -> None:
        if self.world_spec.content_digest() != self.evaluator_spec.world_spec_hash:
            raise ValueError("trusted evaluator WorldSpec hash mismatch")
        if self.curriculum.content_digest() != self.evaluator_spec.curriculum_hash:
            raise ValueError("trusted evaluator curriculum hash mismatch")

    def evaluate(
        self,
        task_type: str,
        context: RuleExecutionContext,
    ) -> RewardEvaluation:
        return evaluate_task_reward_contract(
            self.world_spec,
            self.curriculum,
            self.evaluator_spec.reward,
            task_type,
            context,
        )


__all__ = ["PortableTrustedEvaluator"]
