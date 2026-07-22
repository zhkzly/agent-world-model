"""Deterministic scheduler projection for the single generation WorkGraph.

The scheduler owns readiness and joins.  Components never infer that a parent
passed from a file existing on disk, and a failed sibling never invalidates an
already committed sibling.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from typing import Literal

from pydantic import model_validator

from agent_world.artifact_store import ArtifactWriter
from agent_world.contracts import (
    ArtifactRef,
    ContentHash,
    V2Contract,
    canonical_json_bytes,
    sha256_digest,
)

from .budget import BudgetExceeded
from .work import (
    FeedbackEvaluation,
    ParentRepairRoute,
    RepairAction,
    ValidationReport,
    WorkAttempt,
    WorkCommit,
    WorkCoordinate,
    WorkDefinition,
)
from .work_graph import (
    GenerationWorkGraph,
    ResolvedWorkInputs,
    WorkGraphManifest,
    WorkGroupDefinition,
)
from .work_runtime import WorkControlRuntime, WorkRuntimeError
from .work_store import WorkControlStore, WorkResumeError

type ScheduledState = Literal[
    "ready", "repair_ready", "waiting", "running", "committed", "blocked", "stale"
]

type WorkExecutor = Callable[["WorkExecutionContext"], Awaitable[None]]


class WorkExecutorMissingError(WorkRuntimeError):
    """A frozen ready Work has no framework-owned executor binding.

    This is a graph/runtime integration defect, never a semantic finding an
    Agent may repair.  Retaining exact coordinates makes a Direct failure
    diagnosable without exposing any proposal, prompt, or repair-control data.
    """

    def __init__(self, coordinates: tuple[WorkCoordinate, ...]) -> None:
        if not coordinates:
            raise ValueError("missing-executor error requires at least one WorkCoordinate")
        self.coordinates = coordinates
        rendered = ", ".join(
            ".".join(
                part
                for part in (
                    coordinate.component,
                    coordinate.stage,
                    coordinate.artifact_slot,
                    coordinate.group_id,
                    coordinate.shard_id,
                )
                if part is not None
            )
            for coordinate in coordinates
        )
        super().__init__(f"Scheduler has no executor for ready Work: {rendered}")


class WorkExecutionContext(V2Contract):
    """Exact immutable dispatch envelope passed to one leaf executor."""

    definition_ref: ArtifactRef
    coordinate: WorkCoordinate
    graph_digest: ContentHash
    external_input_refs: tuple[ArtifactRef, ...] = ()
    parent_commit_refs: tuple[ArtifactRef, ...] = ()
    parent_output_refs: tuple[ArtifactRef, ...] = ()
    repair_action_ref: ArtifactRef | None = None


class WorkDispatchResult(V2Contract):
    coordinate: WorkCoordinate
    before_state: Literal["ready", "repair_ready", "stale"]
    after_state: Literal["committed", "repair_ready", "blocked"]
    attempt_ref: ArtifactRef
    commit_ref: ArtifactRef | None = None
    evaluation_ref: ArtifactRef | None = None


class ScheduledWork(V2Contract):
    coordinate: WorkCoordinate
    state: ScheduledState
    commit_ref: ArtifactRef | None = None
    blocking_evaluation_refs: tuple[ArtifactRef, ...] = ()
    waiting_on: tuple[WorkCoordinate, ...] = ()

    @model_validator(mode="after")
    def validate_state(self) -> ScheduledWork:
        if (self.state == "committed") != (self.commit_ref is not None):
            raise ValueError("committed scheduling state requires one WorkCommit")
        if (self.state == "blocked") != bool(self.blocking_evaluation_refs):
            raise ValueError("blocked scheduling state requires boundary evaluations")
        if len(set(self.blocking_evaluation_refs)) != len(
            self.blocking_evaluation_refs
        ):
            raise ValueError("blocking evaluation refs must be unique")
        if self.state == "waiting" and not self.waiting_on:
            raise ValueError("waiting scheduling state requires unmet dependencies")
        if self.state != "waiting" and self.waiting_on:
            raise ValueError("only waiting work may name unmet dependencies")
        return self


class WorkGroupState(V2Contract):
    group_id: str
    status: Literal["waiting", "ready", "blocked"]
    committed_member_refs: tuple[ArtifactRef, ...] = ()
    running_members: tuple[WorkCoordinate, ...] = ()
    blocked_members: tuple[WorkCoordinate, ...] = ()
    blocking_evaluation_refs: tuple[ArtifactRef, ...] = ()
    missing_members: tuple[WorkCoordinate, ...] = ()


class WorkScheduleSnapshot(V2Contract):
    graph_digest: ContentHash
    work: tuple[ScheduledWork, ...]
    groups: tuple[WorkGroupState, ...] = ()

    @property
    def ready_coordinates(self) -> tuple[WorkCoordinate, ...]:
        return tuple(item.coordinate for item in self.work if item.state == "ready")


class WorkScheduler:
    """Project exact runnable work from immutable graph and durable heads."""

    def __init__(
        self,
        *,
        graph: GenerationWorkGraph,
        manifest: WorkGraphManifest,
        manifest_ref: ArtifactRef,
        heads: WorkControlStore,
        artifacts: ArtifactWriter,
        runtime: WorkControlRuntime | None = None,
    ) -> None:
        self.graph = graph
        self.manifest = WorkGraphManifest.model_validate(
            manifest.model_dump(mode="python")
        )
        self.manifest_ref = manifest_ref
        self.heads = heads
        self.artifacts = artifacts
        self.runtime = runtime
        self.artifacts.require_exact_json(
            manifest_ref,
            self.manifest,
            artifact_types=("control.work_graph_manifest",),
        )
        expected = graph.manifest(
            topology_id=manifest.topology_id,
            external_root_refs=manifest.external_root_refs,
        )
        if expected != self.manifest:
            raise WorkResumeError("scheduler manifest does not bind its executable graph")
        self.external_root_refs = self.manifest.external_root_refs

    def snapshot(self) -> WorkScheduleSnapshot:
        active: dict[str, tuple[WorkCommit, ArtifactRef]] = {}
        scheduled: dict[str, ScheduledWork] = {}
        groups_by_aggregate = {
            item.aggregate_coordinate.coordinate_key: item for item in self.graph.groups
        }
        group_states: list[WorkGroupState] = []

        for definition in self.graph.topological_definitions():
            key = definition.coordinate.coordinate_key
            head = self.heads.read_head(definition.coordinate)
            parent_keys = tuple(
                item.coordinate_key for item in definition.dependency_coordinates
            )
            parents_available = all(item in active for item in parent_keys)
            # Commit reuse must derive the *same* input closure as a future
            # dispatch.  A causal parent WorkCommit invalidates the child, but
            # does not disclose every one of its outputs to the child.  Using
            # all parent consumer refs here while ``resolve_inputs`` used typed
            # input slots made every least-privilege commit look stale during
            # recovery, so an otherwise complete release graph never reached
            # Package.
            expected_inputs = (
                self._all_input_refs(
                    definition,
                    tuple(active[parent_key][0] for parent_key in parent_keys),
                )
                if parents_available
                else None
            )
            if head is not None and head.status == "committed":
                committed = (
                    None
                    if expected_inputs is None
                    else self.heads.require_active_commit(
                        definition=definition,
                        input_refs=expected_inputs,
                        artifacts=self.artifacts,
                    )
                )
                if committed is None:
                    scheduled[key] = ScheduledWork(
                        coordinate=definition.coordinate,
                        state="stale",
                    )
                    continue
                group = groups_by_aggregate.get(key)
                if group is not None:
                    exact_children = tuple(
                        active[item.coordinate_key][1]
                        for item in group.member_coordinates
                        if item.coordinate_key in active
                    )
                    if (
                        len(exact_children) != len(group.member_coordinates)
                        or not committed[0].aggregate
                        or committed[0].child_commit_refs != exact_children
                    ):
                        scheduled[key] = ScheduledWork(
                            coordinate=definition.coordinate,
                            state="stale",
                        )
                        continue
                active[key] = committed
                scheduled[key] = ScheduledWork(
                    coordinate=definition.coordinate,
                    state="committed",
                    commit_ref=committed[1],
                )
                continue
            if head is not None and head.status == "repair_authorized":
                scheduled[key] = ScheduledWork(
                    coordinate=definition.coordinate,
                    state="repair_ready",
                )
                continue
            if head is not None and head.status == "running":
                scheduled[key] = ScheduledWork(
                    coordinate=definition.coordinate,
                    state="running",
                )
                continue
            if head is not None and head.status in {"failed", "needs_human", "interrupted"}:
                # Terminal failure is a boundary only for the exact immutable
                # input closure it evaluated.  Once a causally repaired parent
                # commits different consumer refs, retaining that old failure
                # would permanently block the new candidate.  Treat it as
                # stale; dispatch will create a new attempt under the changed
                # input fingerprint, never silently reuse the old verdict.
                if (
                    expected_inputs is not None
                    and head.input_fingerprint
                    != self.heads.input_fingerprint(expected_inputs)
                ):
                    scheduled[key] = ScheduledWork(
                        coordinate=definition.coordinate,
                        state="stale",
                    )
                    continue
                if head.evaluation_ref is None:
                    raise WorkResumeError("terminal Work head lacks its boundary evaluation")
                evaluation = self.artifacts.get_json(
                    head.evaluation_ref,
                    FeedbackEvaluation,
                )
                if evaluation.readiness_effect not in {"blocks", "invalidates"}:
                    raise WorkResumeError("terminal Work evaluation does not block readiness")
                scheduled[key] = ScheduledWork(
                    coordinate=definition.coordinate,
                    state="blocked",
                    blocking_evaluation_refs=(head.evaluation_ref,),
                )
                continue

            group = groups_by_aggregate.get(key)
            if group is not None:
                group_state = self._group_state(group, scheduled, active)
                group_states.append(group_state)
                if group_state.status == "ready":
                    scheduled[key] = ScheduledWork(
                        coordinate=definition.coordinate,
                        state="ready",
                    )
                elif group_state.status == "blocked":
                    scheduled[key] = ScheduledWork(
                        coordinate=definition.coordinate,
                        state="blocked",
                        blocking_evaluation_refs=(
                            group_state.blocking_evaluation_refs
                        ),
                    )
                else:
                    waiting = tuple(
                        item
                        for item in definition.dependency_coordinates
                        if item.coordinate_key not in active
                    )
                    scheduled[key] = ScheduledWork(
                        coordinate=definition.coordinate,
                        state="waiting",
                        waiting_on=waiting,
                    )
                continue

            unmet = tuple(
                dependency
                for dependency in definition.dependency_coordinates
                if dependency.coordinate_key not in active
            )
            scheduled[key] = ScheduledWork(
                coordinate=definition.coordinate,
                state="waiting" if unmet else "ready",
                waiting_on=unmet,
            )

        ordered = tuple(
            scheduled[item.coordinate.coordinate_key]
            for item in self.graph.topological_definitions()
        )
        return WorkScheduleSnapshot(
            graph_digest=self.manifest.graph_digest,
            work=ordered,
            groups=tuple(sorted(group_states, key=lambda item: item.group_id)),
        )

    async def dispatch_one(
        self,
        coordinate: WorkCoordinate,
        *,
        executors: Mapping[str, WorkExecutor],
    ) -> WorkDispatchResult:
        """Dispatch one ready logical item and require a durable terminal decision.

        Executors are intentionally leaf-shaped: they may perform the proposal,
        deterministic validation and assurance declared by their WorkDefinition,
        but they cannot choose another coordinate or recursively retry.  A repair
        attempt is opened here, by the scheduler, before the leaf is invoked.
        """

        if self.runtime is None:
            raise WorkRuntimeError("scheduler dispatch requires WorkControlRuntime")
        definition = self.graph.require(coordinate)
        executor = executors.get(definition.work_id)
        if executor is None:
            raise WorkRuntimeError(
                f"no leaf executor registered for {definition.coordinate.coordinate_key}"
            )
        scheduled = next(
            (item for item in self.snapshot().work if item.coordinate == coordinate),
            None,
        )
        if scheduled is None or scheduled.state not in {"ready", "repair_ready", "stale"}:
            raise WorkRuntimeError("scheduler may dispatch only ready work")
        before_state: Literal["ready", "repair_ready", "stale"]
        if scheduled.state == "repair_ready":
            before_state = "repair_ready"
        elif scheduled.state == "stale":
            before_state = "stale"
        else:
            before_state = "ready"
        resolved = self.resolve_inputs(coordinate)
        repair_action_ref: ArtifactRef | None = None
        if scheduled.state == "repair_ready":
            with self.heads.exclusive(coordinate) as lock:
                head = self.heads.read_head(coordinate)
                if head is None or head.status != "repair_authorized":
                    raise WorkRuntimeError("repair-ready Work changed before dispatch")
                repair_action_ref = head.repair_action_ref
                if repair_action_ref is None:
                    raise WorkRuntimeError("repair-ready Work lacks RepairAction")
                action = self.artifacts.get_json(repair_action_ref, RepairAction)
                if action.target_coordinate != coordinate:
                    raise WorkRuntimeError(
                        "parent repair must be scheduled at its causal target coordinate"
                    )
                self.runtime.begin_authorized_repair(lock, definition=definition)
        elif scheduled.state == "stale":
            with self.heads.exclusive(coordinate) as lock:
                head = self.heads.read_head(coordinate)
                if head is None:
                    raise WorkRuntimeError("stale Work head disappeared before reconciliation")
                self.runtime.supersede_stale(
                    lock,
                    definition=definition,
                    input_refs=resolved.all_input_refs,
                    previous=head,
                    elapsed_wall_seconds=0,
                )
        else:
            # The scheduler, rather than a component leaf, is the sole authority
            # that opens the initial WorkAttempt.  A leaf may only turn this
            # durable running attempt into proposal/validation/assurance evidence.
            with self.heads.exclusive(coordinate) as lock:
                head = self.heads.read_head(coordinate)
                if head is None:
                    self.runtime.begin(
                        lock,
                        definition=definition,
                        input_refs=resolved.all_input_refs,
                        elapsed_wall_seconds=0,
                    )
                elif head.status != "running" or head.active_operation_ref is not None:
                    raise WorkRuntimeError("ready Work changed before initial dispatch")
        definition_ref = self.artifacts.put_json(
            artifact_id=f"work-definition:{definition.work_id}",
            artifact_type="control.work_definition",
            value=definition,
        )
        context = WorkExecutionContext(
            definition_ref=definition_ref,
            coordinate=coordinate,
            graph_digest=self.manifest.graph_digest,
            external_input_refs=resolved.external_input_refs,
            parent_commit_refs=resolved.parent_commit_refs,
            parent_output_refs=resolved.parent_output_refs,
            repair_action_ref=repair_action_ref,
        )
        try:
            await executor(context)
        except BudgetExceeded as exc:
            # An operation lease is acquired inside a leaf only after the
            # Scheduler opened its WorkAttempt.  If admission rejects that
            # lease, no real Agent/tool/process work has begun, but the
            # attempt must still receive a durable terminal boundary instead
            # of remaining ``running`` indefinitely.  Runtime owns the exact
            # evidence/report/evaluation projection; Scheduler merely routes
            # this deterministic admission outcome.
            with self.heads.exclusive(coordinate) as lock:
                self.runtime.terminate_budget_exhausted(
                    lock,
                    definition=definition,
                    dimensions=exc.dimensions,
                )
        self._route_parent_repair_if_requested(definition)
        head = self.heads.read_head(coordinate)
        if head is None or head.active_operation_ref is not None:
            raise WorkRuntimeError("leaf executor returned with unfinished operation authority")
        after_state: Literal["committed", "repair_ready", "blocked"]
        if head.status == "committed":
            after_state = "committed"
        elif head.status == "repair_authorized":
            after_state = "repair_ready"
        elif head.status in {"failed", "needs_human", "interrupted"}:
            after_state = "blocked"
        else:
            raise WorkRuntimeError(
                "leaf executor returned without WorkCommit, RepairAction, or terminal evaluation"
            )
        return WorkDispatchResult(
            coordinate=coordinate,
            before_state=before_state,
            after_state=after_state,
            attempt_ref=head.attempt_ref,
            commit_ref=head.commit_ref,
            evaluation_ref=head.evaluation_ref,
        )

    async def run_until_stalled(
        self,
        *,
        executors: Mapping[str, WorkExecutor],
        maximum_concurrency: int = 2,
        maximum_dispatches: int = 128,
    ) -> tuple[WorkDispatchResult, ...]:
        """Execute ready waves until a durable terminal state or framework error.

        A ready Work without an executor is not a normal stalled state: the
        frozen graph requires that exact unit of work, but framework wiring
        cannot perform it.  Raise a typed error rather than silently returning
        an empty wave and letting a caller misreport an unknown semantic block.
        """

        if maximum_concurrency < 1 or maximum_dispatches < 1:
            raise ValueError("scheduler bounds must be positive")
        results: list[WorkDispatchResult] = []
        semaphore = asyncio.Semaphore(maximum_concurrency)

        async def dispatch(coordinate: WorkCoordinate) -> WorkDispatchResult:
            async with semaphore:
                return await self.dispatch_one(coordinate, executors=executors)

        while len(results) < maximum_dispatches:
            snapshot = self.snapshot()
            missing_executors = tuple(
                item.coordinate
                for item in snapshot.work
                if item.state in {"ready", "repair_ready"}
                and self.graph.require(item.coordinate).work_id not in executors
            )
            if missing_executors:
                raise WorkExecutorMissingError(missing_executors)
            ready: list[WorkCoordinate] = []
            for item in snapshot.work:
                if (
                    item.state not in {"ready", "repair_ready", "stale"}
                    or self.graph.require(item.coordinate).work_id not in executors
                ):
                    continue
                if item.state == "stale":
                    try:
                        self.resolve_inputs(item.coordinate)
                    except WorkResumeError:
                        # A stale descendant is intentionally held until its
                        # changed parent has a new active WorkCommit.
                        continue
                ready.append(item.coordinate)
            if not ready:
                return tuple(results)
            remaining = maximum_dispatches - len(results)
            wave = tuple(ready[:remaining])
            completed = await asyncio.gather(*(dispatch(item) for item in wave))
            results.extend(completed)
        if any(
            item.state in {"ready", "repair_ready", "stale"}
            for item in self.snapshot().work
        ):
            raise WorkRuntimeError("scheduler dispatch limit exhausted before convergence")
        return tuple(results)

    def resolve_inputs(self, coordinate: WorkCoordinate) -> ResolvedWorkInputs:
        definition = self.graph.require(coordinate)
        parent_commit_refs: list[ArtifactRef] = []
        parent_commits: list[WorkCommit] = []
        for parent_coordinate in definition.dependency_coordinates:
            parent = self.graph.require(parent_coordinate)
            head = self.heads.read_head(parent.coordinate)
            if head is None or head.status != "committed":
                raise WorkResumeError("cannot resolve inputs before every parent commits")
            attempt = self.artifacts.get_json(head.attempt_ref, WorkAttempt)
            active = self.heads.require_active_commit(
                definition=parent,
                input_refs=attempt.input_refs,
                artifacts=self.artifacts,
            )
            if active is None:
                raise WorkResumeError("parent WorkCommit is no longer active")
            commit, commit_ref = active
            parent_commit_refs.append(commit_ref)
            parent_commits.append(commit)
        # ``GenerationContext`` is the immutable common root of the whole
        # graph, not an input consumed only by its first node.  Keeping it in
        # every WorkAttempt fingerprint makes permissions, job/request lineage
        # and expansion roots explicit for every downstream tool, build and
        # release decision.  Parent consumer refs remain the causal data
        # products; the context is their stable shared authority boundary.
        external = self.external_root_refs
        parent_output_refs = self._parent_output_refs(definition, tuple(parent_commits))
        payload = {
            "graph_digest": self.manifest.graph_digest,
            "coordinate": coordinate.model_dump(mode="json"),
            "external_input_refs": tuple(
                ref.model_dump(mode="json") for ref in external
            ),
            "parent_commit_refs": tuple(
                ref.model_dump(mode="json") for ref in parent_commit_refs
            ),
            "parent_output_refs": tuple(
                ref.model_dump(mode="json") for ref in parent_output_refs
            ),
        }
        return ResolvedWorkInputs(
            graph_digest=self.manifest.graph_digest,
            coordinate=coordinate,
            external_input_refs=external,
            parent_commit_refs=tuple(parent_commit_refs),
            parent_output_refs=parent_output_refs,
            input_fingerprint=sha256_digest(canonical_json_bytes(payload)),
        )

    def _all_input_refs(
        self,
        definition: WorkDefinition,
        parent_commits: tuple[WorkCommit, ...],
    ) -> tuple[ArtifactRef, ...]:
        """Return the exact WorkAttempt closure for reuse and dispatch alike."""

        return tuple(
            dict.fromkeys(
                (*self.external_root_refs, *self._parent_output_refs(definition, parent_commits))
            )
        )

    @staticmethod
    def _parent_output_refs(
        definition: WorkDefinition,
        parent_commits: tuple[WorkCommit, ...],
    ) -> tuple[ArtifactRef, ...]:
        """Project causal parents through the child's typed disclosure slots."""

        accepted_parent_types = frozenset(
            artifact_type
            for slot in definition.input_slots
            for artifact_type in slot.artifact_types
        )
        if definition.input_slots:
            return tuple(
                ref
                for commit in parent_commits
                for ref in commit.consumer_refs
                if ref.artifact_type in accepted_parent_types
            )
        # Generic diagnostic graphs are permitted to omit slots while being
        # assembled.  Production Direct/Evolve graphs compile with strict
        # input contracts and can never enter this compatibility-free branch.
        return tuple(ref for commit in parent_commits for ref in commit.consumer_refs)

    def invalidation_scope(self, coordinate: WorkCoordinate) -> tuple[WorkCoordinate, ...]:
        """Return only causal descendants; siblings are deliberately absent."""

        return self.graph.descendants(coordinate)

    def _route_parent_repair_if_requested(self, definition: WorkDefinition) -> None:
        """Apply one safe downstream-to-owner repair route, if a leaf emitted it.

        The leaf has already persisted a normal failed ValidationReport.  This
        Scheduler-owned router merely verifies that the requested target is an
        explicit one-hop causal parent and lets the target's own repair policy
        decide whether a new physical attempt is affordable.  No string owner
        label, LLM verdict, or undeclared ancestor can reopen work here.
        """

        if self.runtime is None:
            return
        source_head = self.heads.read_head(definition.coordinate)
        if source_head is None or source_head.status != "failed":
            return
        if source_head.evaluation_ref is None:
            raise WorkRuntimeError("failed source Work lacks its FeedbackEvaluation")
        source_attempt = self.artifacts.get_json(source_head.attempt_ref, WorkAttempt)
        report_ref = source_attempt.validation_report_ref
        if report_ref is None:
            raise WorkRuntimeError("failed source Work lacks its ValidationReport")
        report = self.artifacts.get_json(report_ref, ValidationReport)
        route_refs = tuple(
            ref
            for ref in report.evidence_refs
            if ref.artifact_type == "control.parent_repair_route"
        )
        if not route_refs:
            return
        if len(route_refs) != 1:
            raise WorkRuntimeError("one failed Work may request at most one causal repair route")
        route_ref = route_refs[0]
        route = self.artifacts.get_json(route_ref, ParentRepairRoute)
        if (
            route.source_coordinate != definition.coordinate
            or route.source_attempt_id != source_attempt.attempt_id
            or route.source_definition_digest != definition.definition_digest
            or tuple(item.normalized_identity for item in report.issues)
            != route.issue_identities
            or report.status != "failed"
            or not report.repair_actionable
        ):
            raise WorkRuntimeError("causal repair route does not bind the terminal source finding")
        target = self.graph.automatic_repair_target(
            current=definition.coordinate,
            proposed_target=route.target_coordinate,
        )
        resolved_target = self.resolve_inputs(target.coordinate)
        with self.heads.exclusive(target.coordinate) as lock:
            self.runtime.authorize_causal_repair(
                lock,
                definition=target,
                input_refs=resolved_target.all_input_refs,
                source_evaluation_ref=source_head.evaluation_ref,
                source_report_ref=report_ref,
                route_ref=route_ref,
            )

    @staticmethod
    def _group_state(
        group: WorkGroupDefinition,
        scheduled: dict[str, ScheduledWork],
        active: dict[str, tuple[WorkCommit, ArtifactRef]],
    ) -> WorkGroupState:
        committed = tuple(
            active[item.coordinate_key][1]
            for item in group.member_coordinates
            if item.coordinate_key in active
        )
        running = tuple(
            item
            for item in group.member_coordinates
            if scheduled.get(item.coordinate_key) is not None
            and scheduled[item.coordinate_key].state == "running"
        )
        blocked = tuple(
            item
            for item in group.member_coordinates
            if scheduled.get(item.coordinate_key) is not None
            and scheduled[item.coordinate_key].state == "blocked"
        )
        missing = tuple(
            item
            for item in group.member_coordinates
            if item.coordinate_key not in scheduled
            or scheduled[item.coordinate_key].state in {"ready", "waiting"}
        )
        required = len(group.member_coordinates)
        if len(committed) >= required:
            status: Literal["waiting", "ready", "blocked"] = "ready"
        elif blocked and len(committed) + len(running) + len(missing) < required:
            status = "blocked"
        else:
            status = "waiting"
        return WorkGroupState(
            group_id=group.group_id,
            status=status,
            committed_member_refs=committed,
            running_members=running,
            blocked_members=blocked,
            blocking_evaluation_refs=tuple(
                dict.fromkeys(
                    ref
                    for item in blocked
                    for ref in scheduled[item.coordinate_key].blocking_evaluation_refs
                )
            ),
            missing_members=missing,
        )


__all__ = [
    "ScheduledState",
    "ScheduledWork",
    "WorkDispatchResult",
    "WorkExecutionContext",
    "WorkExecutor",
    "WorkGroupState",
    "WorkScheduleSnapshot",
    "WorkScheduler",
]
