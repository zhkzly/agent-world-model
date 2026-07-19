"""Readiness derived only from active WorkHeads and exact WorkCommits."""

from __future__ import annotations

from typing import Literal

from pydantic import model_validator

from agent_world.artifact_store import ArtifactWriter
from agent_world.contracts import ArtifactRef, V2Contract

from .work import FeedbackEvaluation, WorkCoordinate
from .work_graph import GenerationWorkGraph
from .work_store import WorkControlStore


class WorkReadinessSnapshot(V2Contract):
    scope_id: str
    status: Literal["ready", "blocked", "incomplete"]
    satisfied_commit_refs: tuple[ArtifactRef, ...] = ()
    blocking_evaluation_refs: tuple[ArtifactRef, ...] = ()
    missing_coordinates: tuple[WorkCoordinate, ...] = ()
    maturity_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def derive_status(self) -> WorkReadinessSnapshot:
        expected = (
            "blocked"
            if self.blocking_evaluation_refs
            else "incomplete"
            if self.missing_coordinates
            else "ready"
        )
        if self.status != expected:
            raise ValueError("readiness status is not derived from active WorkGraph state")
        if len(set(self.satisfied_commit_refs)) != len(self.satisfied_commit_refs):
            raise ValueError("readiness commit refs must be unique")
        if len(set(self.blocking_evaluation_refs)) != len(self.blocking_evaluation_refs):
            raise ValueError("readiness blocking refs must be unique")
        return self


class WorkReadinessProjection:
    """Fail-closed projection; reports and events never satisfy readiness directly."""

    @staticmethod
    def project(
        *,
        graph: GenerationWorkGraph,
        work_store: WorkControlStore,
        artifacts: ArtifactWriter,
        input_refs_by_coordinate: dict[str, tuple[ArtifactRef, ...]],
    ) -> WorkReadinessSnapshot:
        satisfied: list[ArtifactRef] = []
        blocking: list[ArtifactRef] = []
        missing: list[WorkCoordinate] = []
        maturities: list[str] = []
        scopes = {definition.coordinate.scope_id for definition in graph.definitions}
        scope_id = next(iter(scopes), "empty-work-graph")
        for definition in graph.definitions:
            inputs = input_refs_by_coordinate.get(definition.coordinate.coordinate_key)
            head = work_store.read_head(definition.coordinate)
            if inputs is None or head is None:
                missing.append(definition.coordinate)
                continue
            if head.status == "committed":
                active = work_store.require_active_commit(
                    definition=definition,
                    input_refs=inputs,
                    artifacts=artifacts,
                )
                if active is None:
                    missing.append(definition.coordinate)
                    continue
                _commit, commit_ref = active
                satisfied.append(commit_ref)
                maturities.append(definition.success_maturity)
                continue
            if head.evaluation_ref is not None:
                evaluation = artifacts.get_json(
                    head.evaluation_ref,
                    FeedbackEvaluation,
                )
                if evaluation.readiness_effect in {"blocks", "invalidates"}:
                    blocking.append(head.evaluation_ref)
                    continue
            missing.append(definition.coordinate)
        status: Literal["ready", "blocked", "incomplete"] = (
            "blocked" if blocking else "incomplete" if missing else "ready"
        )
        return WorkReadinessSnapshot(
            scope_id=scope_id,
            status=status,
            satisfied_commit_refs=tuple(satisfied),
            blocking_evaluation_refs=tuple(blocking),
            missing_coordinates=tuple(missing),
            maturity_ids=tuple(maturities),
        )


__all__ = ["WorkReadinessProjection", "WorkReadinessSnapshot"]
