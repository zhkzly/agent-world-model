"""Framework-owned WorkDefinition catalog and dependency/invalidation graph."""

from __future__ import annotations

import hashlib
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass

from agent_world.contracts import Identifier

from .work import (
    OperationBudget,
    ProposalPolicy,
    RepairPolicy,
    ValidationPolicy,
    WorkCoordinate,
    WorkDefinition,
)


class WorkGraphError(RuntimeError):
    """The framework WorkGraph is incomplete, cyclic, or identity-conflicting."""


@dataclass(frozen=True, slots=True)
class GenerationWorkGraph:
    """Immutable dependency graph; only framework definitions may enter it."""

    _definitions: tuple[WorkDefinition, ...]

    @classmethod
    def compile(cls, definitions: Iterable[WorkDefinition]) -> GenerationWorkGraph:
        items = tuple(
            WorkDefinition.model_validate(item.model_dump(mode="python"))
            for item in definitions
        )
        if not items:
            raise WorkGraphError("WorkGraph cannot be empty")
        by_key = {item.coordinate.coordinate_key: item for item in items}
        if len(by_key) != len(items):
            raise WorkGraphError("WorkGraph contains duplicate coordinates")
        if len({item.work_id for item in items}) != len(items):
            raise WorkGraphError("WorkGraph contains duplicate work ids")
        scopes = {item.coordinate.scope_id for item in items}
        if len(scopes) > 1:
            raise WorkGraphError("one WorkGraph cannot mix generation scopes")
        for item in items:
            missing = tuple(
                dependency
                for dependency in item.dependency_coordinates
                if dependency.coordinate_key not in by_key
            )
            if missing:
                raise WorkGraphError(
                    f"WorkGraph dependency is not registered: {missing[0].coordinate_key}"
                )
        cls._assert_acyclic(items, by_key)
        return cls(tuple(sorted(items, key=lambda item: item.coordinate.coordinate_key)))

    @staticmethod
    def _assert_acyclic(
        definitions: tuple[WorkDefinition, ...],
        by_key: dict[str, WorkDefinition],
    ) -> None:
        indegree = {item.coordinate.coordinate_key: 0 for item in definitions}
        children: dict[str, list[str]] = {key: [] for key in indegree}
        for item in definitions:
            child_key = item.coordinate.coordinate_key
            for dependency in item.dependency_coordinates:
                parent_key = dependency.coordinate_key
                indegree[child_key] += 1
                children[parent_key].append(child_key)
        ready = deque(key for key, degree in indegree.items() if degree == 0)
        visited = 0
        while ready:
            key = ready.popleft()
            visited += 1
            for child in children[key]:
                indegree[child] -= 1
                if indegree[child] == 0:
                    ready.append(child)
        if visited != len(by_key):
            raise WorkGraphError("WorkGraph contains a dependency cycle")

    @property
    def definitions(self) -> tuple[WorkDefinition, ...]:
        return self._definitions

    def require(self, coordinate: WorkCoordinate) -> WorkDefinition:
        definition = next(
            (item for item in self._definitions if item.coordinate == coordinate),
            None,
        )
        if definition is None:
            raise WorkGraphError(f"unknown WorkCoordinate: {coordinate.coordinate_key}")
        return definition

    def descendants(self, coordinate: WorkCoordinate) -> tuple[WorkCoordinate, ...]:
        """Return all and only transitive consumers in deterministic topological order."""

        self.require(coordinate)
        reached: set[str] = set()
        queue = deque((coordinate.coordinate_key,))
        ordered: list[WorkCoordinate] = []
        while queue:
            parent_key = queue.popleft()
            children = sorted(
                (
                    item
                    for item in self._definitions
                    if any(
                        dependency.coordinate_key == parent_key
                        for dependency in item.dependency_coordinates
                    )
                ),
                key=lambda item: item.coordinate.coordinate_key,
            )
            for child in children:
                key = child.coordinate.coordinate_key
                if key in reached:
                    continue
                reached.add(key)
                ordered.append(child.coordinate)
                queue.append(key)
        return tuple(ordered)

    def automatic_repair_target(
        self,
        *,
        current: WorkCoordinate,
        proposed_target: WorkCoordinate,
    ) -> WorkDefinition:
        """Permit local or exact-parent repair only; anything farther needs human authority."""

        current_definition = self.require(current)
        target = self.require(proposed_target)
        if proposed_target == current:
            return target
        if proposed_target not in current_definition.dependency_coordinates:
            raise WorkGraphError("automatic repair may jump only to an exact parent")
        if current_definition.repair_policy.maximum_automatic_backjump < 1:
            raise WorkGraphError("this WorkDefinition forbids automatic parent correction")
        return target


def tool_semantics_batch_definition(
    *,
    job_id: Identifier,
    group_id: Identifier,
    batch_id: Identifier,
    dependency_coordinates: tuple[WorkCoordinate, ...],
    agent_wall_seconds: float,
    agent_token_limit: int,
    agent_monetary_limit: float = 1.0,
    validation_wall_seconds: float = 10.0,
) -> WorkDefinition:
    """Compile framework policy for one real ToolSemanticsBatch shard."""

    coordinate = WorkCoordinate(
        scope_id=job_id,
        component="design",
        stage="world_behavior",
        artifact_slot="tool_semantics_batch",
        group_id=group_id,
        shard_id=batch_id,
    )
    digest = hashlib.sha256(
        f"{job_id}\0{group_id}\0{batch_id}".encode()
    ).hexdigest()[:24]
    claim_id = "design.tool_semantics.compiles"
    return WorkDefinition(
        work_id=f"work:tool-semantics:{digest}",
        coordinate=coordinate,
        claim=(
            "The exact tool batch compiles against the frozen world schema, "
            "Rule IR context, and shared multi-tool constraints."
        ),
        timing_reason=(
            "World rules and task materialization may consume this batch only after "
            "its deterministic semantic frontier closes."
        ),
        dependency_coordinates=dependency_coordinates,
        proposal_policy=ProposalPolicy(
            policy_id=f"proposal:tool-semantics:{digest}",
            executor="agent",
            operation="design.tool_semantics_batch",
            budget=OperationBudget(
                wall_seconds=agent_wall_seconds,
                first_progress_seconds=min(60.0, agent_wall_seconds),
                llm_tokens=agent_token_limit,
                agent_turns=1,
                monetary_cost=agent_monetary_limit,
            ),
            agent_role="environment_engineer",
            capability_profile_id="profile:environment-engineer",
            output_contract_id="contract:tool-semantics-batch-source",
        ),
        validation_policy=ValidationPolicy(
            policy_id=f"validation:tool-semantics:{digest}",
            validator_id="validator:tool-semantics-batch",
            validation_phase="tool_semantics",
            frontier_ordinal=20,
            claim_id=claim_id,
            effect="block_compile",
            budget=OperationBudget(wall_seconds=validation_wall_seconds),
        ),
        repair_policy=RepairPolicy(
            policy_id=f"repair:tool-semantics:{digest}",
            maximum_local_corrections=1,
            strict_progress_bonus_corrections=1,
            maximum_infrastructure_retries=1,
            maximum_automatic_backjump=0,
            maximum_total_repair_attempts=3,
        ),
        required_claim_id=claim_id,
        allowed_mutation_roots=("/tools",),
        success_maturity="semantic_compiled",
    )


__all__ = [
    "GenerationWorkGraph",
    "WorkGraphError",
    "tool_semantics_batch_definition",
]
