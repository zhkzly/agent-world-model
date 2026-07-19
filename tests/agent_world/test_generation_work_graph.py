from __future__ import annotations

import pytest

from agent_world.control.work import WorkCoordinate
from agent_world.control.work_graph import (
    GenerationWorkGraph,
    WorkGraphError,
    tool_semantics_batch_definition,
)


def _coordinate(slot: str) -> WorkCoordinate:
    return WorkCoordinate(
        scope_id="job:hotel",
        component="design",
        stage=slot,
        artifact_slot=slot,
    )


def _definition(slot: str, dependencies: tuple[WorkCoordinate, ...] = ()):
    return tool_semantics_batch_definition(
        job_id="job:hotel",
        group_id=f"group:{slot}",
        batch_id=f"batch:{slot}",
        dependency_coordinates=dependencies,
        agent_wall_seconds=120,
        agent_token_limit=10_000,
    ).model_copy(
        update={
            "work_id": f"work:{slot}",
            "coordinate": _coordinate(slot),
            "dependency_coordinates": dependencies,
        }
    )


def test_graph_derives_descendant_invalidation_and_exact_parent_repair() -> None:
    architecture = _definition("architecture")
    behavior = _definition("behavior", (architecture.coordinate,))
    rules = _definition("rules", (behavior.coordinate,))
    curriculum = _definition("curriculum", (rules.coordinate,))
    graph = GenerationWorkGraph.compile((architecture, behavior, rules, curriculum))

    assert graph.descendants(architecture.coordinate) == (
        behavior.coordinate,
        rules.coordinate,
        curriculum.coordinate,
    )
    assert graph.automatic_repair_target(
        current=behavior.coordinate,
        proposed_target=behavior.coordinate,
    ) == behavior
    with pytest.raises(WorkGraphError, match="forbids"):
        graph.automatic_repair_target(
            current=behavior.coordinate,
            proposed_target=architecture.coordinate,
        )
    with pytest.raises(WorkGraphError, match="exact parent"):
        graph.automatic_repair_target(
            current=curriculum.coordinate,
            proposed_target=architecture.coordinate,
        )


def test_graph_rejects_missing_dependencies_duplicate_coordinates_and_cycles() -> None:
    architecture = _definition("architecture")
    missing = _definition("behavior", (_coordinate("not-registered"),))
    with pytest.raises(WorkGraphError, match="not registered"):
        GenerationWorkGraph.compile((architecture, missing))
    with pytest.raises(WorkGraphError, match="duplicate coordinates"):
        GenerationWorkGraph.compile(
            (architecture, architecture.model_copy(update={"work_id": "work:duplicate"}))
        )

    left = _definition("left")
    right = _definition("right", (left.coordinate,))
    cyclic_left = left.model_copy(update={"dependency_coordinates": (right.coordinate,)})
    with pytest.raises(WorkGraphError, match="cycle"):
        GenerationWorkGraph.compile((cyclic_left, right))


def test_tool_semantics_policy_has_one_base_correction_progress_bonus_and_infra_retry() -> None:
    definition = tool_semantics_batch_definition(
        job_id="job:hotel",
        group_id="coupling:booking",
        batch_id="batch:1",
        dependency_coordinates=(_coordinate("architecture"),),
        agent_wall_seconds=300,
        agent_token_limit=20_000,
    )

    assert definition.coordinate.artifact_slot == "tool_semantics_batch"
    assert definition.proposal_policy.budget.agent_turns == 1
    assert definition.repair_policy.maximum_local_corrections == 1
    assert definition.repair_policy.strict_progress_bonus_corrections == 1
    assert definition.repair_policy.maximum_infrastructure_retries == 1
    assert definition.repair_policy.maximum_automatic_backjump == 0
