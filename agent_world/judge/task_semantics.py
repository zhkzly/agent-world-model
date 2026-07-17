"""Framework-owned semantic checks for Task Materialization v3."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from itertools import combinations

from pydantic import JsonValue

from agent_world.contracts import CurriculumRequirements, FrameworkTaskEnvelope
from agent_world.contracts.base import canonical_json_bytes, sha256_digest


class GeneratedTaskSemanticError(ValueError):
    """A schema-valid materialization is semantically unsuitable for training."""


@dataclass(frozen=True, slots=True)
class DifficultyContrastCandidate:
    """One same-seed v3 pair awaiting proof from real Runtime resets."""

    task_type: str
    dimension: str
    left_index: int
    right_index: int
    initial_config_changed: bool
    evaluator_goal_changed: bool
    left_semantic_hash: str
    right_semantic_hash: str


def find_difficulty_contrast_candidates(
    *,
    envelopes: tuple[FrameworkTaskEnvelope, ...],
    curriculum: CurriculumRequirements,
) -> dict[str, dict[str, tuple[DifficultyContrastCandidate, ...]]]:
    """Collect every v3 pair whose declared difficulty has a semantic effect."""

    grouped: dict[
        tuple[str, int, str],
        list[tuple[int, FrameworkTaskEnvelope]],
    ] = defaultdict(list)
    for index, envelope in enumerate(envelopes):
        call = envelope.call
        grouped[(call.task_type, call.seed, call.actor)].append((index, envelope))

    result: dict[str, dict[str, tuple[DifficultyContrastCandidate, ...]]] = {}
    for requirement in curriculum.task_types:
        dimension_candidates: dict[str, tuple[DifficultyContrastCandidate, ...]] = {}
        for dimension in requirement.difficulty_dimensions:
            candidates: list[DifficultyContrastCandidate] = []
            for pairs in grouped.values():
                for (left_index, left), (right_index, right) in combinations(pairs, 2):
                    if left.call.task_type != requirement.task_type:
                        continue
                    left_without = dict(left.call.difficulty)
                    right_without = dict(right.call.difficulty)
                    left_level = left_without.pop(dimension, None)
                    right_level = right_without.pop(dimension, None)
                    if (
                        left_level == right_level
                        or canonical_json_bytes(left_without)
                        != canonical_json_bytes(right_without)
                    ):
                        continue
                    left_initial = left.materialization.initial_config
                    right_initial = right.materialization.initial_config
                    initial_changed = canonical_json_bytes(left_initial) != canonical_json_bytes(
                        right_initial
                    )
                    evaluator_changed = canonical_json_bytes(
                        left.evaluator_goal
                    ) != canonical_json_bytes(right.evaluator_goal)
                    if not initial_changed and not evaluator_changed:
                        continue
                    left_projection: dict[str, JsonValue] = {
                        "initial_config": left_initial,
                        "evaluator_goal": left.evaluator_goal,
                    }
                    right_projection: dict[str, JsonValue] = {
                        "initial_config": right_initial,
                        "evaluator_goal": right.evaluator_goal,
                    }
                    candidates.append(
                        DifficultyContrastCandidate(
                            task_type=requirement.task_type,
                            dimension=dimension,
                            left_index=left_index,
                            right_index=right_index,
                            initial_config_changed=initial_changed,
                            evaluator_goal_changed=evaluator_changed,
                            left_semantic_hash=sha256_digest(
                                canonical_json_bytes(left_projection)
                            ),
                            right_semantic_hash=sha256_digest(
                                canonical_json_bytes(right_projection)
                            ),
                        )
                    )
            if not candidates:
                raise GeneratedTaskSemanticError(
                    f"task type {requirement.task_type} does not semantically respond to "
                    f"difficulty dimension {dimension} under a same-seed contrast"
                )
            dimension_candidates[dimension] = tuple(candidates)
        result[requirement.task_type] = dimension_candidates
    return result


__all__ = [
    "DifficultyContrastCandidate",
    "GeneratedTaskSemanticError",
    "find_difficulty_contrast_candidates",
]
