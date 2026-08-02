"""Deterministic scheduler projection for the single generation WorkGraph.

The scheduler owns readiness and joins.  Components never infer that a parent
passed from a file existing on disk, and a failed sibling never invalidates an
already committed sibling.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
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
from agent_world.diagnostic_state import has_test_node_diagnostic_marker

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
from .work_store import WorkControlStore, WorkDependencyUnavailableError, WorkResumeError

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
    # The physical action may be a transport retry/fallback.  In that case
    # this separately binds the original semantic action whose precise
    # feedback remains authorized for the fresh Provider turn.
    semantic_repair_context_ref: ArtifactRef | None = None


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
        if len(set(self.blocking_evaluation_refs)) != len(self.blocking_evaluation_refs):
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
        allow_diagnostic_ancestors: bool = False,
    ) -> None:
        self.graph = graph
        self.manifest = WorkGraphManifest.model_validate(manifest.model_dump(mode="python"))
        self.manifest_ref = manifest_ref
        self.heads = heads
        self.artifacts = artifacts
        self.runtime = runtime
        if allow_diagnostic_ancestors and (
            runtime is None
            or not runtime.diagnostic_only
            or not has_test_node_diagnostic_marker(heads.root)
        ):
            raise WorkRuntimeError("diagnostic ancestor reuse requires a marked diagnostic runtime")
        self.allow_diagnostic_ancestors = allow_diagnostic_ancestors
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

    def _diagnostic_terminal_blocks(self, evaluation: FeedbackEvaluation) -> bool:
        """Whether a diagnostic terminal may still be treated as blocking.

        ``FeedbackEvaluation`` *requires* ``readiness_effect == "observes"``
        whenever ``diagnostic_only`` is set (see its validator): a diagnostic
        verdict must never claim authority to block the captured graph it was
        cloned from.  Without this allowance, one diagnostic terminal in a
        ``test-node`` copy makes ``snapshot()`` unbuildable, so *every* other
        coordinate in that scope becomes permanently undispatchable -- the
        diagnostic clone poisons itself.

        Inside a marked diagnostic runtime the copy is already the throwaway
        artifact, so treating that terminal as locally blocking is exactly the
        honest reading: the node did terminate, and this scheduler cannot
        release anything.  The guard deliberately mirrors the conditions of
        ``allow_diagnostic_ancestors``; a normal release runtime keeps the
        original strict invariant and can never reach this branch.
        """

        return (
            evaluation.diagnostic_only
            and not evaluation.releasable
            and self.runtime is not None
            and self.runtime.diagnostic_only
            and has_test_node_diagnostic_marker(self.heads.root)
        )

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
            parent_keys = tuple(item.coordinate_key for item in definition.dependency_coordinates)
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
            unavailable_dependencies = tuple(
                dependency
                for dependency in definition.dependency_coordinates
                if dependency.coordinate_key not in active
            )
            if head is not None and head.status == "committed":
                if expected_inputs is None:
                    scheduled[key] = ScheduledWork(
                        coordinate=definition.coordinate,
                        state="waiting",
                        waiting_on=unavailable_dependencies,
                    )
                    continue
                committed = (
                    self._require_usable_commit(
                        definition=definition,
                        input_refs=expected_inputs,
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
                # Repair authority is bound to the exact immutable definition
                # and input closure that produced it.  A new definition (for
                # example, an explicitly frozen diagnostic-feedback variant)
                # must not inherit that old authority.  Reconcile it as stale
                # so ``dispatch_one`` opens a fresh WorkAttempt instead.
                #
                # The exact input closure is unknowable until every causal
                # parent has an active commit.  Treating an old authorization
                # as repair-ready in that state lets dispatch outrun snapshot:
                # ``resolve_inputs`` then fails on the unavailable parent.
                # Hold the child at the causal boundary instead.
                if expected_inputs is None:
                    scheduled[key] = ScheduledWork(
                        coordinate=definition.coordinate,
                        state="waiting",
                        waiting_on=unavailable_dependencies,
                    )
                    continue
                if head.definition_digest != definition.definition_digest or (
                    head.input_fingerprint != self.heads.input_fingerprint(expected_inputs)
                ):
                    scheduled[key] = ScheduledWork(
                        coordinate=definition.coordinate,
                        state="stale",
                    )
                    continue
                scheduled[key] = ScheduledWork(
                    coordinate=definition.coordinate,
                    state="repair_ready",
                )
                continue
            if head is not None and head.status == "running":
                # A ``running`` head with no active OperationRun never crossed the
                # dispatch fence: the Scheduler durably wrote it in ``begin`` before
                # a leaf opened its first operation, and a crash in that window left
                # a never-commenced attempt that consumed zero work.  Recovery
                # (``_reconcile_abandoned_operations``) runs before the first
                # snapshot and resets such an orphan to a fresh running attempt via
                # ``resume_uncommenced_running``; that fresh attempt is still
                # ``running & active_operation_ref is None`` and must be
                # re-dispatchable rather than pinned forever.  ``dispatch_one``'s
                # ready branch already tolerates an existing running head with no
                # active operation, so it re-runs the fresh attempt cleanly.
                if head.active_operation_ref is None:
                    scheduled[key] = ScheduledWork(
                        coordinate=definition.coordinate,
                        state="ready",
                    )
                    continue
                scheduled[key] = ScheduledWork(
                    coordinate=definition.coordinate,
                    state="running",
                )
                continue
            if head is not None and head.status in {"failed", "needs_human", "interrupted"}:
                # A terminal failure is a boundary only for the exact immutable
                # definition *and* input closure it evaluated.  A causally
                # repaired parent may change consumer refs, and a feedback-only
                # test-node run may freeze a new definition with the same
                # inputs.  Either change invalidates the old terminal verdict;
                # dispatch will create a new attempt rather than silently reuse
                # it or leave the replacement definition permanently blocked.
                if expected_inputs is None:
                    scheduled[key] = ScheduledWork(
                        coordinate=definition.coordinate,
                        state="waiting",
                        waiting_on=unavailable_dependencies,
                    )
                    continue
                if head.definition_digest != definition.definition_digest or (
                    head.input_fingerprint != self.heads.input_fingerprint(expected_inputs)
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
                if evaluation.readiness_effect not in {
                    "blocks",
                    "invalidates",
                } and not self._diagnostic_terminal_blocks(evaluation):
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
                        blocking_evaluation_refs=(group_state.blocking_evaluation_refs),
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
        semantic_repair_context_ref: ArtifactRef | None = None
        if scheduled.state == "repair_ready":
            action: RepairAction
            with self.heads.exclusive(coordinate) as lock:
                head = self.heads.read_head(coordinate)
                if head is None or head.status != "repair_authorized":
                    raise WorkRuntimeError("repair-ready Work changed before dispatch")
                repair_action_ref = head.repair_action_ref
                if repair_action_ref is None:
                    raise WorkRuntimeError("repair-ready Work lacks RepairAction")
                action = self.artifacts.get_json(repair_action_ref, RepairAction)
                semantic_repair_context_ref = (
                    repair_action_ref
                    if action.decision in {"local_correction", "parent_correction"}
                    else action.semantic_repair_context_ref
                )
            if action.route_liveness_required:
                await self._await_retry_backoff(action)
            with self.heads.exclusive(coordinate) as lock:
                head = self.heads.read_head(coordinate)
                if (
                    head is None
                    or head.status != "repair_authorized"
                    or head.repair_action_ref != repair_action_ref
                ):
                    raise WorkRuntimeError("repair-ready Work changed during retry admission")
                action = self.artifacts.get_json(repair_action_ref, RepairAction)
                semantic_repair_context_ref = (
                    repair_action_ref
                    if action.decision in {"local_correction", "parent_correction"}
                    else action.semantic_repair_context_ref
                )
                if action.target_coordinate != coordinate:
                    raise WorkRuntimeError(
                        "parent repair must be scheduled at its causal target coordinate"
                    )
                route_liveness_evidence_ref: ArtifactRef | None = None
                if action.route_liveness_required:
                    check, route_liveness_evidence_ref = (
                        self.runtime.check_authorized_route_liveness(
                            lock,
                            definition=definition,
                        )
                    )
                    if check.status == "rejected":
                        failed = self.runtime.reject_authorized_route_liveness(
                            lock,
                            definition=definition,
                            evidence_ref=route_liveness_evidence_ref,
                        )
                        return WorkDispatchResult(
                            coordinate=coordinate,
                            before_state="repair_ready",
                            after_state="blocked",
                            attempt_ref=failed.attempt_ref,
                            evaluation_ref=failed.evaluation_ref,
                        )
                self.runtime.begin_authorized_repair(
                    lock,
                    definition=definition,
                    route_liveness_evidence_ref=route_liveness_evidence_ref,
                )
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
            semantic_repair_context_ref=semantic_repair_context_ref,
        )
        try:
            # Do not pay for a real model/tool proposal when the complete
            # success path already cannot reserve its declared deterministic
            # validation or assurance boundary. This is only an early
            # observation; individual operations still acquire durable leases
            # immediately before execution.
            self.runtime.assert_attempt_operation_envelope_admissible(
                definition=definition,
                elapsed_wall_seconds=0,
            )
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
        except KeyboardInterrupt:
            # A terminal SIGINT can surface as ``KeyboardInterrupt`` rather
            # than task cancellation.  Settle the durable Work boundary
            # before letting the CLI preserve its conventional exit-130
            # behavior; otherwise a dead owner can strand a running head.
            self._settle_cancelled_dispatch(definition)
            raise
        except asyncio.CancelledError:
            # A cooperative Scheduler leaf normally performs this same
            # settlement before re-raising.  Keep the command/scheduler
            # boundary as a second, idempotent owner-recovery fence for a
            # signal that lands between the durable dispatch CAS and a leaf's
            # own cancellation translation.  Cancellation never admits an
            # infrastructure retry here.
            self._settle_cancelled_dispatch(definition)
            raise
        except Exception:
            # A leaf may finish its external work and then fail while
            # checkpointing deterministic proposal/validation state. Keep a
            # final owner fence here so an unhandled framework exception
            # cannot leave an active OperationRun publicly ``running``. The
            # leaf kernel normally emits the more precise framework report;
            # this path is only the non-retryable last resort.
            self._settle_failed_dispatch(definition)
            raise
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

    @staticmethod
    async def _await_retry_backoff(action: RepairAction) -> None:
        """Wait outside the Work lock until the policy-recorded retry instant."""

        if not action.route_liveness_required:
            return
        if action.retry_not_before is None:
            raise WorkRuntimeError("route-gated retry lacks a retry backoff timestamp")
        remaining = (action.retry_not_before - datetime.now(UTC)).total_seconds()
        if remaining > 0:
            await asyncio.sleep(remaining)

    def _settle_cancelled_dispatch(self, definition: WorkDefinition) -> None:
        """Converge an active operation after external owner interruption.

        This method deliberately delegates to the normal WorkRuntime terminal
        chain, so budget accounting and Evaluation evidence stay identical to
        ordinary recovery.  It is idempotent because a leaf may already have
        settled the active operation while handling the same cancellation.
        """

        if self.runtime is None:
            return
        with self.heads.exclusive(definition.coordinate) as lock:
            head = self.heads.read_head(definition.coordinate)
            if head is None or head.status != "running" or head.active_operation_ref is None:
                return
            self.runtime.reconcile_abandoned_operation(
                lock,
                definition=definition,
                interrupted_dispatch_code="process_interrupted_cancelled",
                allow_infrastructure_retry=False,
            )

    def _settle_failed_dispatch(self, definition: WorkDefinition) -> None:
        """Terminalize one unhandled executor failure without authorizing retry."""

        if self.runtime is None:
            return
        with self.heads.exclusive(definition.coordinate) as lock:
            head = self.heads.read_head(definition.coordinate)
            if head is None or head.status != "running" or head.active_operation_ref is None:
                return
            self.runtime.reconcile_abandoned_operation(
                lock,
                definition=definition,
                interrupted_dispatch_code="scheduler_executor_framework_error",
                allow_infrastructure_retry=False,
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
        if any(item.state in {"ready", "repair_ready", "stale"} for item in self.snapshot().work):
            raise WorkRuntimeError("scheduler dispatch limit exhausted before convergence")
        return tuple(results)

    def resolve_inputs(self, coordinate: WorkCoordinate) -> ResolvedWorkInputs:
        definition = self.graph.require(coordinate)
        parent_commit_refs: list[ArtifactRef] = []
        parent_commits: list[WorkCommit] = []
        for parent_coordinate in definition.dependency_coordinates:
            parent = self.graph.require(parent_coordinate)
            head = self.heads.read_head(parent.coordinate)
            if head is None:
                raise WorkDependencyUnavailableError(
                    child=coordinate,
                    parent=parent.coordinate,
                    parent_status="missing",
                    reason_code="parent_head_missing",
                )
            if head.status != "committed":
                raise WorkDependencyUnavailableError(
                    child=coordinate,
                    parent=parent.coordinate,
                    parent_status=head.status,
                    reason_code="parent_not_committed",
                )
            attempt = self.artifacts.get_json(head.attempt_ref, WorkAttempt)
            active = self._require_usable_commit(
                definition=parent,
                input_refs=attempt.input_refs,
            )
            if active is None:
                raise WorkDependencyUnavailableError(
                    child=coordinate,
                    parent=parent.coordinate,
                    parent_status=head.status,
                    reason_code="parent_commit_inactive",
                )
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
            "external_input_refs": tuple(ref.model_dump(mode="json") for ref in external),
            "parent_commit_refs": tuple(ref.model_dump(mode="json") for ref in parent_commit_refs),
            "parent_output_refs": tuple(ref.model_dump(mode="json") for ref in parent_output_refs),
        }
        return ResolvedWorkInputs(
            graph_digest=self.manifest.graph_digest,
            coordinate=coordinate,
            external_input_refs=external,
            parent_commit_refs=tuple(parent_commit_refs),
            parent_output_refs=parent_output_refs,
            input_fingerprint=sha256_digest(canonical_json_bytes(payload)),
        )

    def _require_usable_commit(
        self,
        *,
        definition: WorkDefinition,
        input_refs: tuple[ArtifactRef, ...],
    ) -> tuple[WorkCommit, ArtifactRef] | None:
        """Resolve normal authority, with an explicit diagnostic-only escape hatch.

        The scheduler's normal path never calls the diagnostic method.  The
        opt-in exists solely for one fresh successor node inside a marked
        ``test-node`` copy, where the predecessor was itself genuinely
        executed but deliberately made non-releasable.
        """

        if self.allow_diagnostic_ancestors:
            return self.heads.require_active_or_diagnostic_commit(
                definition=definition,
                input_refs=input_refs,
                artifacts=self.artifacts,
            )
        return self.heads.require_active_commit(
            definition=definition,
            input_refs=input_refs,
            artifacts=self.artifacts,
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
            or tuple(item.normalized_identity for item in report.issues) != route.issue_identities
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
