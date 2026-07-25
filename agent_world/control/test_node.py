"""Isolated, one-node diagnostic execution for a frozen WorkGraph scope.

The harness intentionally does not offer a replay shortcut.  It copies a
captured state root, verifies the target's committed ancestor closure against
the exact persisted WorkGraph manifest, removes *only* the copied target head
from scheduling, and lets :meth:`WorkScheduler.dispatch_one` invoke the real
leaf once.  The copied run has a fresh, target-sized budget and every new
control artifact is explicitly diagnostic-only and non-releasable.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal, cast

from agent_world.artifact_store import ArtifactWriter
from agent_world.config import FoundryConfig
from agent_world.contracts import ArtifactRef, Budget, BudgetUsage, GenerationContext, V2Contract
from agent_world.diagnostic_state import is_marked_test_node_diagnostic_state_root

from .budget import LeaseBudgetLedger
from .leaf_executor import SchedulerLeafExecutor
from .work import (
    OperationRun,
    ProposalExecution,
    ValidationReport,
    WorkAttempt,
    WorkCommit,
    WorkCoordinate,
    WorkDefinition,
)
from .work_epoch import WorkGraphEpochRuntime
from .work_graph import (
    GenerationWorkGraph,
    WorkGraphEpoch,
    WorkGraphError,
    WorkGraphManifest,
    WorkGraphMilestone,
    WorkGraphNodeBinding,
    WorkGroupDefinition,
    compile_design_work_graph,
    derive_final_design_definitions,
    verifier_plan_work_definition,
)
from .work_runtime import WorkControlRuntime
from .work_scheduler import WorkExecutor, WorkScheduler
from .work_store import (
    WorkControlHead,
    WorkControlStore,
    WorkControlStoreError,
    WorkResumeError,
)

if TYPE_CHECKING:
    from agent_world.app import FoundryApplication


# Only ``artifacts/`` and ``work-control/`` hold the frozen WorkGraph input
# closure. The other top-level stores are previous process workspaces,
# observability projections, consumer state, or Registry state; none may
# become an input to an isolated diagnostic dispatch. In particular, old agent
# runtime homes can hold transient tool symlinks or private auth material.
_NON_DURABLE_STATE_DIRECTORIES = frozenset(
    {
        "campaigns",
        "direct-jobs",
        "expansion-source-runs",
        "registry",
        "runs",
        "telemetry",
    }
)


class TestNodeError(RuntimeError):
    """One safe, machine-readable reason a node cannot be isolated."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class TestNodeResult(V2Contract):
    """Safe CLI projection of one genuinely rerun diagnostic node."""

    source_scope_id: str
    target_coordinate: WorkCoordinate
    source_state_root: str
    diagnostic_state_root: str
    source_head_revision: int
    source_attempt_ref: ArtifactRef
    archived_source_head_path: str
    target_attempt_ref: ArtifactRef
    target_evaluation_ref: ArtifactRef
    target_commit_ref: ArtifactRef | None = None
    status: Literal["committed", "failed", "needs_human", "interrupted"]
    validation_report: ValidationReport
    proposal_executions: tuple[ProposalExecution, ...] = ()
    actual_usage: BudgetUsage
    unknown_usage: BudgetUsage
    conservative_usage: BudgetUsage
    reserved_budget: Budget
    scene: dict[str, object]
    diagnostic_only: Literal[True] = True
    releasable: Literal[False] = False


class DiagnosticSuccessorNodeResult(V2Contract):
    """One fresh semantic node derived from a diagnostic Architecture commit.

    This is not a release result and is deliberately distinct from
    :class:`TestNodeResult`: the physical target did not exist in the captured
    pre-Architecture graph, so it cannot be replayed or archived as a former
    target head.  Its predecessor Architecture commit was nevertheless
    genuinely executed by ``test-node`` in the marked source copy, then used
    byte-for-byte as an input in a fresh diagnostic child copy.
    """

    source_scope_id: str
    target_coordinate: WorkCoordinate
    source_diagnostic_state_root: str
    diagnostic_state_root: str
    bootstrap_epoch_ref: ArtifactRef
    design_epoch_ref: ArtifactRef
    design_manifest_ref: ArtifactRef
    architecture_attempt_ref: ArtifactRef
    architecture_commit_ref: ArtifactRef
    target_attempt_ref: ArtifactRef
    target_evaluation_ref: ArtifactRef
    target_commit_ref: ArtifactRef | None = None
    status: Literal["committed", "failed", "needs_human", "interrupted"]
    validation_report: ValidationReport
    proposal_executions: tuple[ProposalExecution, ...] = ()
    actual_usage: BudgetUsage
    unknown_usage: BudgetUsage
    conservative_usage: BudgetUsage
    reserved_budget: Budget
    scene: dict[str, object]
    diagnostic_only: Literal[True] = True
    releasable: Literal[False] = False


@dataclass(frozen=True, slots=True)
class TestNodeExecution:
    """All immutable context available to one test-node executor resolver."""

    app: FoundryApplication
    graph: GenerationWorkGraph
    manifest: WorkGraphManifest
    manifest_ref: ArtifactRef
    definition: WorkDefinition
    context: GenerationContext
    context_ref: ArtifactRef
    runtime: WorkControlRuntime
    workspace_root: Path
    run_id: str
    trace_id: str


@dataclass(frozen=True, slots=True)
class _FrozenTarget:
    graph: GenerationWorkGraph
    manifest: WorkGraphManifest
    manifest_ref: ArtifactRef
    definition: WorkDefinition
    context: GenerationContext
    context_ref: ArtifactRef
    source_head: WorkControlHead


TestNodeExecutorFactory = Callable[[TestNodeExecution], WorkExecutor]


class TestNodeRunner:
    """Copy one scope and dispatch exactly one target node in that copy."""

    def __init__(
        self,
        *,
        config: FoundryConfig,
        source_state_root: Path | None = None,
        diagnostic_parent: Path | None = None,
        executor_factory: TestNodeExecutorFactory | None = None,
    ) -> None:
        self.config = config
        self.source_state_root = source_state_root
        self.diagnostic_parent = diagnostic_parent
        self.executor_factory = executor_factory or self._production_executor

    async def run(self, *, scope_id: str, target_coordinate: str) -> TestNodeResult:
        source_root = self._resolve_source_root()
        diagnostic_root = self._new_diagnostic_root(source_root)
        self._copy_state_root(source_root, diagnostic_root)
        try:
            WorkControlStore(diagnostic_root / "work-control").mark_test_node_diagnostic_clone()
        except WorkControlStoreError as exc:
            raise TestNodeError(
                "test_node_diagnostic_marker_failed",
                "isolated diagnostic state could not be marked",
            ) from exc

        # Import here to keep the production composition root free of an
        # import cycle with ``agent_world.control``.
        from agent_world.app import build_application

        app = build_application(self.config.model_copy(update={"state_root": diagnostic_root}))
        heads = app.controller.work_control
        target = self._resolve_coordinate(
            heads.read_scope_heads(scope_id),
            target_coordinate,
        )
        frozen = self._load_frozen_target(
            app=app,
            scope_id=scope_id,
            target=target,
        )

        self._assert_complete_ancestor_closure(
            app=app,
            graph=frozen.graph,
            target=target,
        )
        scheduler = WorkScheduler(
            graph=frozen.graph,
            manifest=frozen.manifest,
            manifest_ref=frozen.manifest_ref,
            heads=heads,
            artifacts=app.controller.artifacts,
        )
        try:
            resolved = scheduler.resolve_inputs(target)
        except WorkResumeError as exc:
            raise TestNodeError(
                "missing_ancestor_closure",
                "the copied scope does not retain one committed ancestor closure",
            ) from exc
        source_attempt = app.artifacts.get_json(frozen.source_head.attempt_ref, WorkAttempt)
        if resolved.all_input_refs != source_attempt.input_refs:
            raise TestNodeError(
                "test_node_input_closure_mismatch",
                "the persisted target input closure does not match its frozen graph",
            )

        # The only head mutation is an audit-preserving archive of the target
        # head inside the copied state root.  Ancestor heads remain readable
        # immutable inputs and none of the source state is opened for writing.
        with heads.exclusive(target) as lock:
            archived_head_path = heads.archive_terminal_head_for_diagnostic(
                lock,
                expected_head=frozen.source_head,
            )

        budget = self._single_attempt_budget(frozen.definition)
        run_token = uuid.uuid4().hex
        run_id = f"test-node:{run_token}"
        trace_id = run_id
        root_span = app.telemetry.start_span(
            trace_id=trace_id,
            component="controller",
            operation="test_node.dispatch",
            run_id=run_id,
            node=frozen.definition.work_id,
            input_refs=resolved.all_input_refs,
            attributes={"diagnostic_only": True, "releasable": False},
        )
        app.telemetry.activate_trace(
            trace_id=trace_id,
            run_id=run_id,
            parent_span_id=root_span.span_id,
        )
        runtime = WorkControlRuntime(
            artifacts=app.controller.artifacts,
            heads=heads,
            budget=LeaseBudgetLedger(budget),
            # A test-node run intentionally has no authority to continue an
            # old RepairLedger entry.  ``diagnostic_only`` causes every
            # non-passing result to terminate after this one dispatch.
            telemetry=app.telemetry,
            projector=app.controller.scene_projector,
            trace_id=trace_id,
            run_id=run_id,
            diagnostic_only=True,
        )
        workspace_root = diagnostic_root / "runs" / "test-node" / run_token
        workspace_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        execution = TestNodeExecution(
            app=app,
            graph=frozen.graph,
            manifest=frozen.manifest,
            manifest_ref=frozen.manifest_ref,
            definition=frozen.definition,
            context=frozen.context,
            context_ref=frozen.context_ref,
            runtime=runtime,
            workspace_root=workspace_root,
            run_id=run_id,
            trace_id=trace_id,
        )
        executor = self.executor_factory(execution)
        diagnostic_scheduler = WorkScheduler(
            graph=frozen.graph,
            manifest=frozen.manifest,
            manifest_ref=frozen.manifest_ref,
            heads=heads,
            artifacts=app.controller.artifacts,
            runtime=runtime,
        )
        try:
            dispatch = await diagnostic_scheduler.dispatch_one(
                target,
                executors={frozen.definition.work_id: executor},
            )
        except asyncio.CancelledError:
            # SchedulerLeafExecutor is required to settle a cancellation into
            # terminal evidence before it propagates.  A diagnostic command
            # can therefore return that honest bounded result rather than
            # leaving its copied head running.  If cancellation arrived before
            # the leaf could settle, retain normal cancellation semantics.
            interrupted_head = heads.read_head(target)
            if interrupted_head is None or interrupted_head.status not in {
                "committed",
                "failed",
                "needs_human",
                "interrupted",
            }:
                root_span.finish(status="cancelled", error_code="test_node_dispatch_cancelled")
                app.telemetry.flush()
                raise
            dispatch = None
            root_span.finish(
                status="cancelled",
                output_refs=tuple(
                    ref
                    for ref in (
                        interrupted_head.commit_ref,
                        interrupted_head.evaluation_ref,
                    )
                    if ref is not None
                ),
            )
            app.telemetry.flush()
        except Exception:
            root_span.finish(status="error", error_code="test_node_dispatch_error")
            app.telemetry.flush()
            raise
        if dispatch is not None:
            root_span.finish(
                status="passed" if dispatch.after_state == "committed" else "failed",
                output_refs=tuple(
                    ref for ref in (dispatch.commit_ref, dispatch.evaluation_ref) if ref is not None
                ),
            )
            app.telemetry.flush()

        head = heads.read_head(target)
        if head is None or head.status not in {"committed", "failed", "needs_human", "interrupted"}:
            raise TestNodeError(
                "test_node_no_terminal_result",
                "the real target dispatch did not produce one terminal Work head",
            )
        attempt = app.artifacts.get_json(head.attempt_ref, WorkAttempt)
        if attempt.validation_report_ref is None or head.evaluation_ref is None:
            raise TestNodeError(
                "test_node_missing_validation_report",
                "the target dispatch did not persist its ValidationReport and evaluation",
            )
        report = app.artifacts.get_json(attempt.validation_report_ref, ValidationReport)
        evaluation = app.artifacts.get_json(head.evaluation_ref)
        commit = (
            app.artifacts.get_json(head.commit_ref, WorkCommit)
            if head.commit_ref is not None
            else None
        )
        if not (
            attempt.diagnostic_only
            and not attempt.releasable
            and report.diagnostic_only
            and not report.releasable
            and bool(evaluation.get("diagnostic_only"))
            and not bool(evaluation.get("releasable"))
            and (commit is None or (commit.diagnostic_only and not commit.releasable))
        ):
            raise TestNodeError(
                "test_node_diagnostic_marking_failed",
                "the target result was not fully marked diagnostic-only and non-releasable",
            )
        scene = self._scene_payload(app, scope_id=scope_id, run_id=run_id)
        return TestNodeResult(
            source_scope_id=scope_id,
            target_coordinate=target,
            source_state_root=str(source_root),
            diagnostic_state_root=str(diagnostic_root),
            source_head_revision=frozen.source_head.revision,
            source_attempt_ref=frozen.source_head.attempt_ref,
            archived_source_head_path=str(archived_head_path),
            target_attempt_ref=head.attempt_ref,
            target_evaluation_ref=head.evaluation_ref,
            target_commit_ref=head.commit_ref,
            status=cast(
                Literal["committed", "failed", "needs_human", "interrupted"],
                head.status,
            ),
            validation_report=report,
            proposal_executions=self._proposal_executions(app.controller.artifacts, attempt),
            actual_usage=attempt.observed_actual,
            unknown_usage=attempt.unknown_upper_bound,
            conservative_usage=attempt.conservative_committed,
            reserved_budget=budget,
            scene=scene,
        )

    def _resolve_source_root(self) -> Path:
        selected = self.source_state_root or self.config.state_root
        candidate = selected.expanduser()
        if candidate.exists() and candidate.is_symlink():
            raise TestNodeError(
                "test_node_source_state_symlink",
                "source state root cannot be a link",
            )
        try:
            resolved = candidate.resolve(strict=True)
        except OSError as exc:
            raise TestNodeError(
                "test_node_source_state_missing",
                "source state root is unavailable",
            ) from exc
        if not resolved.is_dir():
            raise TestNodeError(
                "test_node_source_state_invalid",
                "source state root must be a real directory",
            )
        return resolved

    def _new_diagnostic_root(self, source_root: Path) -> Path:
        parent = self.diagnostic_parent or self._diagnostic_parent(source_root)
        if parent.exists() and parent.is_symlink():
            raise TestNodeError(
                "test_node_diagnostic_parent_symlink",
                "diagnostic parent cannot be a link",
            )
        try:
            parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            parent.chmod(0o700)
        except OSError as exc:
            raise TestNodeError(
                "test_node_diagnostic_parent_unavailable",
                "diagnostic parent is unavailable",
            ) from exc
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        return parent / f"test-node-{timestamp}-{uuid.uuid4().hex[:12]}"

    def _diagnostic_parent(self, source_root: Path) -> Path:
        for candidate in (*source_root.parents, *self.config.state_root.parents):
            if candidate.name == ".agent-world-live":
                return candidate
        return Path.cwd() / ".agent-world-live"

    @staticmethod
    def _copy_state_root(source_root: Path, diagnostic_root: Path) -> None:
        TestNodeRunner._assert_no_symlinks(source_root)

        def ignore(directory: str, names: list[str]) -> set[str]:
            relative = Path(directory).resolve().relative_to(source_root)
            ignored: set[str] = set()
            if relative == Path("."):
                # ``runs`` is an execution workspace, not the frozen input
                # closure.  Excluding it also prevents old agent runtime
                # homes or their symlinks from entering diagnostic evidence.
                ignored.update(name for name in names if name in _NON_DURABLE_STATE_DIRECTORIES)
            if relative == Path("work-control"):
                # Budget reservations and locks are mutable execution authority.
                # The target receives a fresh, one-attempt diagnostic ledger;
                # ancestor Artifact/commit/head closure remains byte-for-byte.
                ignored.update(name for name in names if name in {"scope-budgets", "locks", "tmp"})
            return ignored

        try:
            shutil.copytree(
                source_root,
                diagnostic_root,
                copy_function=shutil.copy2,
                ignore=ignore,
            )
            diagnostic_root.chmod(0o700)
        except OSError as exc:
            raise TestNodeError(
                "test_node_state_copy_failed",
                "could not create an isolated diagnostic state copy",
            ) from exc

    @staticmethod
    def _assert_no_symlinks(source_root: Path) -> None:
        for directory, directories, files in os.walk(source_root, followlinks=False):
            relative = Path(directory).resolve().relative_to(source_root)
            if relative == Path("."):
                # Match the copy policy exactly: transient execution
                # workspaces are outside the frozen WorkGraph input closure.
                directories[:] = [
                    name for name in directories if name not in _NON_DURABLE_STATE_DIRECTORIES
                ]
            for name in (*directories, *files):
                if (Path(directory) / name).is_symlink():
                    raise TestNodeError(
                        "test_node_source_state_symlink",
                        "source state root contains a symbolic link",
                    )

    @staticmethod
    def _resolve_coordinate(
        heads: tuple[WorkControlHead, ...],
        supplied: str,
    ) -> WorkCoordinate:
        if not heads:
            raise TestNodeError("test_node_scope_not_found", "scope has no durable Work heads")
        expected: WorkCoordinate | None = None
        if supplied.startswith("{"):
            try:
                expected = WorkCoordinate.model_validate(json.loads(supplied))
            except (ValueError, TypeError):
                raise TestNodeError(
                    "test_node_coordinate_invalid",
                    "target coordinate must be an exact coordinate key or JSON object",
                ) from None
        matches = tuple(
            head.coordinate
            for head in heads
            if (
                head.coordinate.coordinate_key == supplied
                or TestNodeRunner._coordinate_label(head.coordinate) == supplied
                or (expected is not None and head.coordinate == expected)
            )
        )
        if len(matches) != 1:
            raise TestNodeError(
                "test_node_coordinate_not_found",
                "target coordinate does not resolve to one captured Work head",
            )
        return matches[0]

    @staticmethod
    def _coordinate_label(coordinate: WorkCoordinate) -> str:
        return "|".join(
            (
                coordinate.component,
                coordinate.stage,
                coordinate.artifact_slot,
                coordinate.group_id or "",
                coordinate.shard_id or "",
            )
        )

    def _load_frozen_target(
        self,
        *,
        app: FoundryApplication,
        scope_id: str,
        target: WorkCoordinate,
    ) -> _FrozenTarget:
        heads = app.controller.work_control
        source_head = heads.read_head(target)
        if source_head is None:
            raise TestNodeError("test_node_target_not_captured", "target has no captured Work head")
        if source_head.status not in {"committed", "failed", "needs_human", "interrupted"}:
            raise TestNodeError(
                "test_node_target_not_terminal",
                "target must be terminal before it can be isolated",
            )
        source_attempt = app.artifacts.get_json(source_head.attempt_ref, WorkAttempt)
        candidates: list[_FrozenTarget] = []
        saw_matching_manifest = False
        saw_incomplete_definition_closure = False
        saw_missing_ancestor_closure = False
        saw_input_closure_mismatch = False
        for manifest_ref in app.artifacts.list_revisions():
            if manifest_ref.artifact_type != "control.work_graph_manifest":
                continue
            try:
                manifest = app.artifacts.get_json(manifest_ref, WorkGraphManifest)
            except ValueError:
                continue
            if manifest.scope_id != scope_id or not any(
                item.work_id == source_head.work_id
                and item.definition_digest == source_head.definition_digest
                and item.coordinate == target
                for item in manifest.node_bindings
            ):
                continue
            saw_matching_manifest = True
            try:
                graph = self._reconstruct_graph(app.controller.artifacts, manifest)
                rendered = graph.manifest(
                    topology_id=manifest.topology_id,
                    external_root_refs=manifest.external_root_refs,
                )
            except WorkResumeError:
                saw_incomplete_definition_closure = True
                continue
            except ValueError:
                continue
            if rendered != manifest:
                continue
            definition = graph.require(target)
            contexts = tuple(
                ref
                for ref in manifest.external_root_refs
                if ref.artifact_type == "control.generation_context"
            )
            if len(contexts) != 1:
                continue
            context_ref = contexts[0]
            try:
                context = app.artifacts.get_json(context_ref, GenerationContext)
            except ValueError:
                continue
            scheduler = WorkScheduler(
                graph=graph,
                manifest=manifest,
                manifest_ref=manifest_ref,
                heads=heads,
                artifacts=app.controller.artifacts,
            )
            try:
                self._assert_complete_ancestor_closure(app=app, graph=graph, target=target)
                resolved = scheduler.resolve_inputs(target)
            except TestNodeError as exc:
                if exc.code != "missing_ancestor_closure":
                    raise
                saw_missing_ancestor_closure = True
                continue
            except WorkResumeError:
                saw_missing_ancestor_closure = True
                continue
            if resolved.all_input_refs != source_attempt.input_refs:
                saw_input_closure_mismatch = True
                continue
            candidates.append(
                _FrozenTarget(
                    graph=graph,
                    manifest=manifest,
                    manifest_ref=manifest_ref,
                    definition=definition,
                    context=context,
                    context_ref=context_ref,
                    source_head=source_head,
                )
            )
        if candidates:
            return min(
                candidates,
                key=lambda item: (len(item.graph.definitions), item.manifest.topology_id),
            )
        if saw_incomplete_definition_closure:
            raise TestNodeError(
                "test_node_frozen_graph_incomplete",
                "the frozen graph does not retain its exact WorkDefinition closure",
            )
        if saw_missing_ancestor_closure:
            raise TestNodeError(
                "missing_ancestor_closure",
                "the copied scope does not retain one committed ancestor closure",
            )
        if saw_input_closure_mismatch:
            raise TestNodeError(
                "test_node_input_closure_mismatch",
                "the persisted target input closure does not match its frozen graph",
            )
        if saw_matching_manifest:
            raise TestNodeError(
                "test_node_frozen_graph_invalid",
                "the frozen graph cannot be reconstructed exactly",
            )
        raise TestNodeError(
            "test_node_frozen_graph_not_found",
            "no exact frozen WorkGraph manifest is available for the target",
        )

    @staticmethod
    def _reconstruct_graph(
        artifacts: ArtifactWriter,
        manifest: WorkGraphManifest,
    ) -> GenerationWorkGraph:
        definitions = tuple(
            TestNodeRunner._definition_for_binding(artifacts, binding)
            for binding in manifest.node_bindings
        )
        groups = tuple(
            WorkGroupDefinition(
                group_id=binding.group_id,
                scope_id=manifest.scope_id,
                member_coordinates=binding.member_coordinates,
                aggregate_coordinate=binding.aggregate_coordinate,
            )
            for binding in manifest.group_bindings
        )
        if any(
            group.content_digest() != binding.group_digest
            for group, binding in zip(groups, manifest.group_bindings, strict=True)
        ):
            raise WorkResumeError("persisted WorkGraph group binding cannot be reconstructed")
        milestones = tuple(
            WorkGraphMilestone(
                milestone_id=binding.milestone_id,
                kind=binding.kind,
                required_coordinates=binding.required_coordinates,
                establishes=binding.establishes,
            )
            for binding in manifest.milestone_bindings
        )
        if any(
            milestone.content_digest() != binding.milestone_digest
            for milestone, binding in zip(milestones, manifest.milestone_bindings, strict=True)
        ):
            raise WorkResumeError("persisted WorkGraph milestone cannot be reconstructed")
        return GenerationWorkGraph.compile(
            definitions,
            mode=manifest.mode,
            required_terminal_coordinates=manifest.required_terminal_coordinates,
            groups=groups,
            milestones=milestones,
        )

    @staticmethod
    def _definition_for_binding(
        artifacts: ArtifactWriter,
        binding: WorkGraphNodeBinding,
    ) -> WorkDefinition:
        # ``WorkGraphNodeBinding`` is intentionally compact; the immutable
        # WorkDefinition revision is the executable contract.  Recover only a
        # byte-equivalent definition bearing this exact digest and coordinate.
        definition_digest = binding.definition_digest
        coordinate = binding.coordinate
        work_id = binding.work_id
        candidates: list[WorkDefinition] = []
        for ref in artifacts.list_revisions():
            if (
                ref.artifact_type != "control.work_definition"
                or ref.content_hash != definition_digest
            ):
                continue
            try:
                definition = artifacts.get_json(ref, WorkDefinition)
            except ValueError:
                continue
            if (
                definition.work_id == work_id
                and definition.coordinate == coordinate
                and definition.definition_digest == definition_digest
            ):
                candidates.append(definition)
        if not candidates or any(item != candidates[0] for item in candidates[1:]):
            raise WorkResumeError("frozen WorkGraph node lacks one exact WorkDefinition")
        return candidates[0]

    @staticmethod
    def _assert_complete_ancestor_closure(
        *,
        app: FoundryApplication,
        graph: GenerationWorkGraph,
        target: WorkCoordinate,
    ) -> None:
        visited: set[str] = set()

        def visit(coordinate: WorkCoordinate) -> None:
            definition = graph.require(coordinate)
            for parent_coordinate in definition.dependency_coordinates:
                key = parent_coordinate.coordinate_key
                if key in visited:
                    continue
                visited.add(key)
                parent_definition = graph.require(parent_coordinate)
                parent_head = app.controller.work_control.read_head(parent_coordinate)
                if parent_head is None or parent_head.status != "committed":
                    raise TestNodeError(
                        "missing_ancestor_closure",
                        "the copied scope does not retain one committed ancestor closure",
                    )
                parent_attempt = app.artifacts.get_json(parent_head.attempt_ref, WorkAttempt)
                try:
                    active = app.controller.work_control.require_active_commit(
                        definition=parent_definition,
                        input_refs=parent_attempt.input_refs,
                        artifacts=app.controller.artifacts,
                    )
                except WorkResumeError as exc:
                    raise TestNodeError(
                        "missing_ancestor_closure",
                        "the copied scope does not retain one active ancestor commit",
                    ) from exc
                if active is None:
                    raise TestNodeError(
                        "missing_ancestor_closure",
                        "the copied scope does not retain one active ancestor commit",
                    )
                visit(parent_coordinate)

        visit(target)

    @staticmethod
    def _single_attempt_budget(definition: WorkDefinition) -> Budget:
        operation_budgets = [definition.proposal_policy.budget, definition.validation_policy.budget]
        if definition.assurance_policy is not None:
            operation_budgets.append(definition.assurance_policy.budget)
        values: dict[str, int | float] = {}
        for field_name in Budget.model_fields:
            if field_name == "schema_version":
                continue
            if field_name == "repair_attempts":
                values[field_name] = 0
            else:
                values[field_name] = sum(
                    getattr(item, field_name) for item in operation_budgets
                )
        return Budget.model_validate(values)

    def _production_executor(self, execution: TestNodeExecution) -> WorkExecutor:
        runner = execution.app.controller.direct_work_runner
        if runner is None:
            raise TestNodeError(
                "test_node_executor_missing",
                "the configured application has no Direct WorkGraph executor",
            )
        kernel = SchedulerLeafExecutor(runtime=execution.runtime)
        epoch_ref, epoch = self._epoch_for_manifest(
            execution.app.controller.artifacts,
            execution.manifest_ref,
        )
        if epoch.epoch_kind == "bootstrap":
            definitions = tuple(
                self._one_definition(execution.graph, component, node_stage)
                for component, node_stage in (
                    ("research", "research_plan"),
                    ("research", "evidence_acquisition"),
                    ("research", "evidence_synthesis"),
                    ("design", "world_architecture"),
                )
            )
            executors = runner._bootstrap_executors(  # noqa: SLF001 - frozen runner assembly
                context_ref=execution.context_ref,
                workspace=execution.workspace_root,
                kernel=kernel,
                definitions=definitions,
            )
        elif epoch.epoch_kind == "design":
            verifier_plan = self._one_definition(execution.graph, "verifier", "verifier_plan")
            executors = runner._design_executors(  # noqa: SLF001 - frozen runner assembly
                context_ref=execution.context_ref,
                workspace=execution.workspace_root,
                kernel=kernel,
                graph=execution.graph,
                verifier_plan=verifier_plan,
            )
        elif epoch.epoch_kind == "final":
            executors = runner._final_executors(  # noqa: SLF001 - frozen runner assembly
                context_ref=execution.context_ref,
                context=execution.context,
                workspace=execution.workspace_root,
                run_id=execution.run_id,
                trace_id=execution.trace_id,
                kernel=kernel,
                graph=execution.graph,
                final_epoch_ref=epoch_ref,
                final_manifest_ref=execution.manifest_ref,
            )
        else:  # pragma: no cover - WorkGraphEpoch has a closed literal
            raise TestNodeError(
                "test_node_frozen_graph_epoch_invalid",
                "frozen graph epoch has an unsupported kind",
            )
        try:
            return executors[execution.definition.work_id]  # type: ignore[return-value]
        except KeyError as exc:
            raise TestNodeError(
                "test_node_executor_missing",
                "the frozen target has no framework-owned leaf executor",
            ) from exc

    @staticmethod
    def _one_definition(
        graph: GenerationWorkGraph,
        component: str,
        stage: str,
    ) -> WorkDefinition:
        matches = tuple(
            definition
            for definition in graph.definitions
            if definition.coordinate.component == component and definition.coordinate.stage == stage
        )
        if len(matches) != 1:
            raise TestNodeError(
                "test_node_frozen_graph_invalid",
                "frozen graph lacks one required unique work definition",
            )
        return matches[0]

    @staticmethod
    def _epoch_for_manifest(
        artifacts: ArtifactWriter,
        manifest_ref: ArtifactRef,
    ) -> tuple[ArtifactRef, WorkGraphEpoch]:
        matches: list[tuple[ArtifactRef, WorkGraphEpoch]] = []
        for ref in artifacts.list_revisions():
            if ref.artifact_type != "control.work_graph_epoch":
                continue
            try:
                epoch = artifacts.get_json(ref, WorkGraphEpoch)
            except ValueError:
                continue
            if epoch.manifest_ref == manifest_ref:
                matches.append((ref, epoch))
        if len(matches) != 1:
            raise TestNodeError(
                "test_node_frozen_graph_epoch_missing",
                "frozen target requires one exact WorkGraph epoch",
            )
        return matches[0]

    @staticmethod
    def _proposal_executions(
        artifacts: ArtifactWriter,
        attempt: WorkAttempt,
    ) -> tuple[ProposalExecution, ...]:
        executions: list[ProposalExecution] = []
        for operation_ref in attempt.operation_run_refs:
            operation = artifacts.get_json(operation_ref, OperationRun)
            if operation.kind != "proposal" or operation.execution_ref is None:
                continue
            executions.append(artifacts.get_json(operation.execution_ref, ProposalExecution))
        return tuple(executions)

    @staticmethod
    def _scene_payload(
        app: FoundryApplication,
        *,
        scope_id: str,
        run_id: str,
    ) -> dict[str, object]:
        try:
            scene = app.controller.scene_projector.rebuild(scope_id, run_id=run_id)
        except Exception as exc:
            raise TestNodeError(
                "test_node_scene_unavailable",
                "diagnostic scene could not be rebuilt from durable facts",
            ) from exc
        return {
            "index": scene.index.model_dump(mode="json"),
            "coordinates": [item.model_dump(mode="json") for item in scene.coordinates],
        }


class DiagnosticSuccessorNodeRunner:
    """Run one new semantic node after a real diagnostic Architecture commit.

    Architecture is the only topology-discovery boundary.  A historic
    ``test-node`` target can therefore prove Architecture itself, but it
    cannot name the downstream physical semantic coordinates until the fresh
    Architecture output has been compiled.  This narrow runner closes that
    gap without weakening the regular ``test-node`` contract:

    * it operates only from a previously marked ``test-node-*`` state copy;
    * it makes one fresh marked child copy, excluding mutable scope budgets
      and execution workspaces just as ``test-node`` does;
    * it accepts only a passed, non-releasable Architecture commit from that
      copied ancestor closure;
    * framework code derives and freezes the Design graph from its exact
      coupling plan; and
    * it dispatches exactly one *new* semantic coordinate with no existing
      head, so no captured target output can be replayed.

    Normal schedulers, normal epoch freezing, final topology derivation, and
    Registry publication never opt into diagnostic ancestors.
    """

    _ALLOWED_STAGES = frozenset({"shared_tool_semantics", "world_behavior"})

    def __init__(
        self,
        *,
        config: FoundryConfig,
        diagnostic_state_root: Path,
        executor_factory: TestNodeExecutorFactory | None = None,
    ) -> None:
        self.config = config
        self.diagnostic_state_root = diagnostic_state_root
        self.executor_factory = executor_factory

    async def run(
        self,
        *,
        scope_id: str,
        target_coordinate: str,
    ) -> DiagnosticSuccessorNodeResult:
        source_diagnostic_root = self._resolve_diagnostic_root()
        copy_helper = TestNodeRunner(config=self.config)
        diagnostic_root = copy_helper._new_diagnostic_root(source_diagnostic_root)  # noqa: SLF001
        try:
            copy_helper._copy_state_root(source_diagnostic_root, diagnostic_root)  # noqa: SLF001
            WorkControlStore(diagnostic_root / "work-control").mark_test_node_diagnostic_clone()
        except TestNodeError:
            raise
        except WorkControlStoreError as exc:
            raise TestNodeError(
                "test_successor_diagnostic_marker_failed",
                "fresh diagnostic successor state could not be marked",
            ) from exc
        # Import lazily for the same composition-root cycle boundary as
        # ``TestNodeRunner``.
        from agent_world.app import build_application
        from agent_world.designer.models import ToolCouplingPlan

        app = build_application(self.config.model_copy(update={"state_root": diagnostic_root}))
        heads = app.controller.work_control
        architecture_coordinate = self._architecture_coordinate(
            heads.read_scope_heads(scope_id)
        )
        frozen = TestNodeRunner(config=self.config)._load_frozen_target(
            app=app,
            scope_id=scope_id,
            target=architecture_coordinate,
        )
        bootstrap_epoch_ref, bootstrap_epoch = TestNodeRunner._epoch_for_manifest(
            app.controller.artifacts,
            frozen.manifest_ref,
        )
        if bootstrap_epoch.epoch_kind != "bootstrap":
            raise TestNodeError(
                "test_successor_bootstrap_epoch_invalid",
                "diagnostic successor requires a frozen bootstrap Architecture graph",
            )

        architecture_attempt = app.artifacts.get_json(
            frozen.source_head.attempt_ref,
            WorkAttempt,
        )
        diagnostic_architecture = heads.require_diagnostic_commit(
            definition=frozen.definition,
            input_refs=architecture_attempt.input_refs,
            artifacts=app.controller.artifacts,
        )
        if diagnostic_architecture is None:
            raise TestNodeError(
                "test_successor_architecture_not_diagnostic",
                "the retained Architecture head is not one passed diagnostic test-node commit",
            )
        architecture_commit, architecture_commit_ref = diagnostic_architecture
        architecture_source_ref = self._one_consumer_ref(
            architecture_commit,
            artifact_type="design.world_architecture_source",
        )
        coupling_ref = self._one_consumer_ref(
            architecture_commit,
            artifact_type="design.tool_coupling_plan",
        )
        coupling_plan = app.controller.artifacts.get_json(coupling_ref, ToolCouplingPlan)
        try:
            design_definitions, modeling = derive_final_design_definitions(
                scope_id=scope_id,
                bootstrap_definitions=frozen.graph.definitions,
                architecture_source_ref=architecture_source_ref,
                coupling_plan=coupling_plan,
                agent_wall_seconds=frozen.definition.proposal_policy.budget.wall_seconds,
                agent_token_limit=frozen.definition.proposal_policy.budget.llm_tokens,
            )
            verifier_plan = verifier_plan_work_definition(
                scope_id=scope_id,
                modeling_coordinate=modeling.coordinate,
            )
            design_graph = compile_design_work_graph(
                scope_id=scope_id,
                design_definitions=design_definitions,
                modeling_definition=modeling,
                verifier_plan_definition=verifier_plan,
                strict_input_contracts=True,
            )
        except WorkGraphError as exc:
            raise TestNodeError(
                "test_successor_topology_derivation_failed",
                "the diagnostic Architecture output cannot derive one closed two-tool Design graph",
            ) from exc

        target = self._resolve_fresh_semantic_coordinate(design_graph, target_coordinate)
        if heads.read_head(target) is not None:
            raise TestNodeError(
                "test_successor_target_already_captured",
                "a diagnostic successor never archives or replays an existing target head",
            )
        epochs = WorkGraphEpochRuntime(
            artifacts=app.controller.artifacts,
            heads=heads,
        )
        try:
            _design_manifest, design_manifest_ref, _design_epoch, design_epoch_ref = (
                epochs.freeze_design(
                    context_ref=frozen.context_ref,
                    bootstrap_epoch_ref=bootstrap_epoch_ref,
                    graph=design_graph,
                    topology_id=(
                        "topology:test-successor-design:"
                        f"{scope_id}:{architecture_commit_ref.content_hash.removeprefix('sha256:')[:16]}"
                    ),
                    allow_diagnostic_predecessors=True,
                )
            )
        except (WorkGraphError, WorkResumeError) as exc:
            raise TestNodeError(
                "test_successor_epoch_freeze_failed",
                "the diagnostic Architecture commit cannot retain one closed Design epoch",
            ) from exc

        design_manifest = app.controller.artifacts.get_json(
            design_manifest_ref,
            WorkGraphManifest,
        )
        budget = TestNodeRunner._single_attempt_budget(design_graph.require(target))
        run_token = uuid.uuid4().hex
        run_id = f"test-successor-node:{run_token}"
        trace_id = run_id
        runtime = WorkControlRuntime(
            artifacts=app.controller.artifacts,
            heads=heads,
            budget=LeaseBudgetLedger(budget),
            telemetry=app.telemetry,
            projector=app.controller.scene_projector,
            trace_id=trace_id,
            run_id=run_id,
            diagnostic_only=True,
        )
        scheduler = WorkScheduler(
            graph=design_graph,
            manifest=design_manifest,
            manifest_ref=design_manifest_ref,
            heads=heads,
            artifacts=app.controller.artifacts,
            runtime=runtime,
            allow_diagnostic_ancestors=True,
        )
        try:
            resolved = scheduler.resolve_inputs(target)
        except WorkResumeError as exc:
            raise TestNodeError(
                "test_successor_ancestor_closure_missing",
                "the fresh semantic target lacks one exact committed diagnostic ancestor",
            ) from exc
        root_span = app.telemetry.start_span(
            trace_id=trace_id,
            component="controller",
            operation="test_successor_node.dispatch",
            run_id=run_id,
            node=design_graph.require(target).work_id,
            input_refs=resolved.all_input_refs,
            attributes={"diagnostic_only": True, "releasable": False},
        )
        app.telemetry.activate_trace(
            trace_id=trace_id,
            run_id=run_id,
            parent_span_id=root_span.span_id,
        )
        workspace_root = diagnostic_root / "runs" / "test-successor-node" / run_token
        workspace_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        definition = design_graph.require(target)
        execution = TestNodeExecution(
            app=app,
            graph=design_graph,
            manifest=design_manifest,
            manifest_ref=design_manifest_ref,
            definition=definition,
            context=frozen.context,
            context_ref=frozen.context_ref,
            runtime=runtime,
            workspace_root=workspace_root,
            run_id=run_id,
            trace_id=trace_id,
        )
        executor = (
            self.executor_factory(execution)
            if self.executor_factory is not None
            else TestNodeRunner(config=self.config)._production_executor(execution)
        )
        try:
            dispatch = await scheduler.dispatch_one(
                target,
                executors={definition.work_id: executor},
            )
        except asyncio.CancelledError:
            head = heads.read_head(target)
            if head is None or head.status not in {
                "committed",
                "failed",
                "needs_human",
                "interrupted",
            }:
                root_span.finish(
                    status="cancelled",
                    error_code="test_successor_node_dispatch_cancelled",
                )
                app.telemetry.flush()
                raise
            dispatch = None
            root_span.finish(
                status="cancelled",
                output_refs=tuple(
                    ref
                    for ref in (head.commit_ref, head.evaluation_ref)
                    if ref is not None
                ),
            )
            app.telemetry.flush()
        except Exception:
            root_span.finish(
                status="error",
                error_code="test_successor_node_dispatch_error",
            )
            app.telemetry.flush()
            raise
        if dispatch is not None:
            root_span.finish(
                status="passed" if dispatch.after_state == "committed" else "failed",
                output_refs=tuple(
                    ref for ref in (dispatch.commit_ref, dispatch.evaluation_ref) if ref is not None
                ),
            )
            app.telemetry.flush()

        head = heads.read_head(target)
        if head is None or head.status not in {"committed", "failed", "needs_human", "interrupted"}:
            raise TestNodeError(
                "test_successor_no_terminal_result",
                "the fresh semantic dispatch did not produce one terminal Work head",
            )
        attempt = app.artifacts.get_json(head.attempt_ref, WorkAttempt)
        if attempt.validation_report_ref is None or head.evaluation_ref is None:
            raise TestNodeError(
                "test_successor_missing_validation_report",
                "the fresh semantic dispatch did not persist ValidationReport and evaluation",
            )
        report = app.artifacts.get_json(attempt.validation_report_ref, ValidationReport)
        evaluation = app.artifacts.get_json(head.evaluation_ref)
        commit = (
            app.artifacts.get_json(head.commit_ref, WorkCommit)
            if head.commit_ref is not None
            else None
        )
        if not (
            attempt.diagnostic_only
            and not attempt.releasable
            and report.diagnostic_only
            and not report.releasable
            and bool(evaluation.get("diagnostic_only"))
            and not bool(evaluation.get("releasable"))
            and (commit is None or (commit.diagnostic_only and not commit.releasable))
        ):
            raise TestNodeError(
                "test_successor_diagnostic_marking_failed",
                "the fresh semantic result was not fully diagnostic-only and non-releasable",
            )
        return DiagnosticSuccessorNodeResult(
            source_scope_id=scope_id,
            target_coordinate=target,
            source_diagnostic_state_root=str(source_diagnostic_root),
            diagnostic_state_root=str(diagnostic_root),
            bootstrap_epoch_ref=bootstrap_epoch_ref,
            design_epoch_ref=design_epoch_ref,
            design_manifest_ref=design_manifest_ref,
            architecture_attempt_ref=frozen.source_head.attempt_ref,
            architecture_commit_ref=architecture_commit_ref,
            target_attempt_ref=head.attempt_ref,
            target_evaluation_ref=head.evaluation_ref,
            target_commit_ref=head.commit_ref,
            status=cast(
                Literal["committed", "failed", "needs_human", "interrupted"],
                head.status,
            ),
            validation_report=report,
            proposal_executions=TestNodeRunner._proposal_executions(
                app.controller.artifacts,
                attempt,
            ),
            actual_usage=attempt.observed_actual,
            unknown_usage=attempt.unknown_upper_bound,
            conservative_usage=attempt.conservative_committed,
            reserved_budget=budget,
            scene=TestNodeRunner._scene_payload(app, scope_id=scope_id, run_id=run_id),
        )

    def _resolve_diagnostic_root(self) -> Path:
        candidate = self.diagnostic_state_root.expanduser()
        if not is_marked_test_node_diagnostic_state_root(candidate):
            raise TestNodeError(
                "test_successor_state_not_marked",
                "diagnostic successor requires one marked .agent-world-live/test-node-* state root",
            )
        try:
            return candidate.resolve(strict=True)
        except OSError as exc:  # pragma: no cover - marker checks the same path first
            raise TestNodeError(
                "test_successor_state_missing",
                "diagnostic successor state root is unavailable",
            ) from exc

    @staticmethod
    def _architecture_coordinate(heads: tuple[WorkControlHead, ...]) -> WorkCoordinate:
        matches = tuple(
            head.coordinate
            for head in heads
            if (
                head.coordinate.component == "design"
                and head.coordinate.stage == "world_architecture"
                and head.status == "committed"
            )
        )
        if len(matches) != 1:
            raise TestNodeError(
                "test_successor_architecture_ambiguous",
                "diagnostic successor requires exactly one committed Architecture head",
            )
        return matches[0]

    @classmethod
    def _resolve_fresh_semantic_coordinate(
        cls,
        graph: GenerationWorkGraph,
        supplied: str,
    ) -> WorkCoordinate:
        expected: WorkCoordinate | None = None
        if supplied.startswith("{"):
            try:
                expected = WorkCoordinate.model_validate(json.loads(supplied))
            except (ValueError, TypeError):
                raise TestNodeError(
                    "test_successor_coordinate_invalid",
                    "target coordinate must be an exact coordinate key or JSON object",
                ) from None
        matches = tuple(
            definition.coordinate
            for definition in graph.definitions
            if (
                definition.coordinate.component == "design"
                and definition.coordinate.stage in cls._ALLOWED_STAGES
                and (
                    definition.coordinate.coordinate_key == supplied
                    or TestNodeRunner._coordinate_label(definition.coordinate) == supplied
                    or (expected is not None and definition.coordinate == expected)
                )
            )
        )
        if len(matches) != 1:
            raise TestNodeError(
                "test_successor_coordinate_not_fresh_semantic",
                "target must be one newly derived shared or physical ToolSemantics coordinate",
            )
        return matches[0]

    @staticmethod
    def _one_consumer_ref(commit: WorkCommit, *, artifact_type: str) -> ArtifactRef:
        matches = tuple(ref for ref in commit.consumer_refs if ref.artifact_type == artifact_type)
        if len(matches) != 1:
            raise TestNodeError(
                "test_successor_architecture_output_invalid",
                "diagnostic Architecture commit lacks one exact derived topology artifact",
            )
        return matches[0]


__all__ = [
    "DiagnosticSuccessorNodeResult",
    "DiagnosticSuccessorNodeRunner",
    "TestNodeError",
    "TestNodeExecution",
    "TestNodeResult",
    "TestNodeRunner",
]
