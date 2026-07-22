"""Readiness derived only from active WorkHeads and exact WorkCommits."""

from __future__ import annotations

from typing import Literal

from pydantic import ValidationError, model_validator

from agent_world.artifact_store import ArtifactWriter
from agent_world.contracts import ArtifactRef, ContentHash, V2Contract

from .work import FeedbackEvaluation, WorkAttempt, WorkCommit, WorkCoordinate
from .work_graph import GenerationWorkGraph, WorkGraphManifest
from .work_store import WorkControlStore, WorkResumeError


class WorkMilestoneState(V2Contract):
    milestone_id: str
    kind: Literal["progress", "release_candidate", "released"]
    establishes: str
    status: Literal["ready", "blocked", "incomplete"]
    satisfied_commit_refs: tuple[ArtifactRef, ...] = ()
    blocking_evaluation_refs: tuple[ArtifactRef, ...] = ()
    missing_coordinates: tuple[WorkCoordinate, ...] = ()

    @model_validator(mode="after")
    def validate_derived_state(self) -> WorkMilestoneState:
        expected = (
            "blocked"
            if self.blocking_evaluation_refs
            else "incomplete"
            if self.missing_coordinates
            else "ready"
        )
        if self.status != expected:
            raise ValueError("milestone status is not derived from its required work")
        return self


class WorkReadinessSnapshot(V2Contract):
    scope_id: str
    manifest_ref: ArtifactRef
    graph_digest: ContentHash
    graph_mode: Literal["diagnostic", "production"]
    status: Literal["ready", "blocked", "incomplete"]
    release_candidate_ready: bool
    released: bool
    satisfied_commit_refs: tuple[ArtifactRef, ...] = ()
    blocking_evaluation_refs: tuple[ArtifactRef, ...] = ()
    missing_coordinates: tuple[WorkCoordinate, ...] = ()
    maturity_ids: tuple[str, ...] = ()
    milestones: tuple[WorkMilestoneState, ...] = ()

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
        release_candidate_states = tuple(
            item for item in self.milestones if item.kind == "release_candidate"
        )
        released_states = tuple(item for item in self.milestones if item.kind == "released")
        expected_candidate = (
            self.graph_mode == "production"
            and len(release_candidate_states) == 1
            and release_candidate_states[0].status == "ready"
        )
        expected_released = (
            self.graph_mode == "production"
            and len(released_states) == 1
            and released_states[0].status == "ready"
        )
        if self.release_candidate_ready != expected_candidate:
            raise ValueError("release-candidate readiness must come from its milestone")
        if self.released != expected_released:
            raise ValueError("released state must come from Registry publication milestone")
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
        manifest: WorkGraphManifest,
        manifest_ref: ArtifactRef,
        work_store: WorkControlStore,
        artifacts: ArtifactWriter,
    ) -> WorkReadinessSnapshot:
        artifacts.require_exact_json(
            manifest_ref,
            manifest,
            artifact_types=("control.work_graph_manifest",),
        )
        expected_manifest = graph.manifest(
            topology_id=manifest.topology_id,
            external_root_refs=manifest.external_root_refs,
        )
        if manifest != expected_manifest:
            raise ValueError("WorkGraph manifest does not bind the executable graph")
        satisfied: list[ArtifactRef] = []
        blocking: list[ArtifactRef] = []
        missing: list[WorkCoordinate] = []
        maturities: list[str] = []
        scopes = {definition.coordinate.scope_id for definition in graph.definitions}
        scope_id = next(iter(scopes), "empty-work-graph")
        active_by_coordinate: dict[str, tuple[WorkCommit, ArtifactRef]] = {}
        blocked_by_coordinate: dict[str, ArtifactRef] = {}

        def descends_from(candidate: ArtifactRef, ancestor: ArtifactRef) -> bool:
            if candidate == ancestor:
                return True
            pending = list(artifacts.dependencies(candidate))
            visited: set[str] = set()
            while pending:
                current = pending.pop()
                if current == ancestor:
                    return True
                if current.revision_id in visited:
                    continue
                visited.add(current.revision_id)
                pending.extend(artifacts.dependencies(current))
            return False

        for definition in graph.topological_definitions():
            coordinate_key = definition.coordinate.coordinate_key
            head = work_store.read_head(definition.coordinate)
            if head is None:
                missing.append(definition.coordinate)
                continue
            if head.status != "committed":
                if head.evaluation_ref is not None:
                    evaluation = artifacts.get_json(
                        head.evaluation_ref,
                        FeedbackEvaluation,
                    )
                    if evaluation.readiness_effect in {"blocks", "invalidates"}:
                        blocking.append(head.evaluation_ref)
                        blocked_by_coordinate[coordinate_key] = head.evaluation_ref
                        continue
                missing.append(definition.coordinate)
                continue
            try:
                attempt = artifacts.get_json(head.attempt_ref, WorkAttempt)
            except ValidationError as exc:
                raise WorkResumeError(
                    "active WorkCommit lacks its exact successful WorkAttempt"
                ) from exc
            inputs = attempt.input_refs
            if definition.dependency_coordinates:
                parents = tuple(
                    active_by_coordinate.get(parent.coordinate_key)
                    for parent in definition.dependency_coordinates
                )
                if any(parent is None for parent in parents):
                    missing.append(definition.coordinate)
                    continue
                if any(
                    not any(
                        descends_from(child_input, parent_output)
                        for child_input in inputs
                    )
                    for parent in parents
                    if parent is not None
                    for parent_output in parent[0].consumer_refs
                ):
                    missing.append(definition.coordinate)
                    continue
            else:
                if not set(inputs) <= set(manifest.external_root_refs):
                    missing.append(definition.coordinate)
                    continue
            active = work_store.require_active_commit(
                definition=definition,
                input_refs=inputs,
                artifacts=artifacts,
            )
            if active is None:
                missing.append(definition.coordinate)
                continue
            commit, commit_ref = active
            satisfied.append(commit_ref)
            maturities.append(definition.success_maturity)
            active_by_coordinate[coordinate_key] = (commit, commit_ref)
        milestone_states: list[WorkMilestoneState] = []
        for milestone in graph.milestones:
            relevant_keys = {
                item.coordinate_key for item in milestone.required_coordinates
            }
            for coordinate in milestone.required_coordinates:
                relevant_keys.update(
                    item.coordinate_key for item in graph.ancestors(coordinate)
                )
            milestone_blocking = tuple(
                dict.fromkeys(
                    blocked_by_coordinate[key]
                    for key in sorted(relevant_keys)
                    if key in blocked_by_coordinate
                )
            )
            milestone_missing = tuple(
                coordinate
                for coordinate in milestone.required_coordinates
                if coordinate.coordinate_key not in active_by_coordinate
            )
            milestone_commits = tuple(
                active_by_coordinate[coordinate.coordinate_key][1]
                for coordinate in milestone.required_coordinates
                if coordinate.coordinate_key in active_by_coordinate
            )
            milestone_status: Literal["ready", "blocked", "incomplete"] = (
                "blocked"
                if milestone_blocking
                else "incomplete"
                if milestone_missing
                else "ready"
            )
            milestone_states.append(
                WorkMilestoneState(
                    milestone_id=milestone.milestone_id,
                    kind=milestone.kind,
                    establishes=milestone.establishes,
                    status=milestone_status,
                    satisfied_commit_refs=milestone_commits,
                    blocking_evaluation_refs=milestone_blocking,
                    missing_coordinates=milestone_missing,
                )
            )
        status: Literal["ready", "blocked", "incomplete"] = (
            "blocked" if blocking else "incomplete" if missing else "ready"
        )
        return WorkReadinessSnapshot(
            scope_id=scope_id,
            manifest_ref=manifest_ref,
            graph_digest=manifest.graph_digest,
            graph_mode=manifest.mode,
            status=status,
            release_candidate_ready=(
                manifest.releasable
                and any(
                    item.kind == "release_candidate" and item.status == "ready"
                    for item in milestone_states
                )
            ),
            released=(
                manifest.releasable
                and any(
                    item.kind == "released" and item.status == "ready"
                    for item in milestone_states
                )
            ),
            satisfied_commit_refs=tuple(satisfied),
            blocking_evaluation_refs=tuple(blocking),
            missing_coordinates=tuple(missing),
            maturity_ids=tuple(
                dict.fromkeys(
                    (
                        *maturities,
                        *(
                            item.establishes
                            for item in milestone_states
                            if item.status == "ready"
                        ),
                    )
                )
            ),
            milestones=tuple(milestone_states),
        )


__all__ = ["WorkMilestoneState", "WorkReadinessProjection", "WorkReadinessSnapshot"]
