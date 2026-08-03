"""One real Direct-generation vertical slice driven only by the WorkGraph.

This is the production replacement for the former Controller component loops.
It does not call ``EnvironmentDesigner.generate`` or any legacy repair
orchestrator.  Each model, research-tool, runtime, and release action is a
Scheduler leaf with one durable WorkAttempt, while this runner owns the four
topology freezes required to turn discovered cardinality into physical work.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pydantic import model_validator

from agent_world.artifact_store import ArtifactWriter
from agent_world.builder import BuilderLeaf, BuildPlanningLeaf, EnvironmentBuilder
from agent_world.contracts import (
    ArtifactRef,
    Budget,
    BudgetUsage,
    EnvironmentDesign,
    EnvironmentJob,
    EnvironmentRequest,
    GenerationContext,
    V2Contract,
)
from agent_world.designer import (
    EvidenceSynthesisLeaf,
    ResearchAcquisitionLeaf,
    ResearchPlanLeaf,
    WorldArchitectureLeaf,
)
from agent_world.designer.final_design_leaves import (
    CurriculumPlanLeaf,
    ModelingBoundaryLeaf,
    SharedToolSemanticsLeaf,
    TaskCurriculumJoinLeaf,
    TaskRequirementLeaf,
    ToolSemanticsBatchLeaf,
    WorldRulesLeaf,
)
from agent_world.designer.models import CurriculumPlanSourceDraft, ToolCouplingPlan
from agent_world.invocation import RouteLivenessChecker
from agent_world.judge import (
    EnvironmentJudge,
    IntegrationLeaf,
    ReleaseAssuranceLeaf,
    VerifierAggregateLeaf,
    VerifierBatchLeaf,
    VerifierBatchPlan,
    VerifierCompiler,
    VerifierPlanLeaf,
)
from agent_world.registry import EnvironmentRegistry, ReleaseRecord

from .budget import LeaseBudgetLedger
from .continuation_store import NodeContinuationStore
from .leaf_executor import SchedulerLeafExecutor
from .models import JobRunSnapshot
from .release_dossier import ReleaseDossierCompiler
from .release_leaf import ObservabilityLeaf, PackageLeaf, RegistryPublicationLeaf
from .telemetry import TelemetryStore
from .work import (
    NodeResumeAuthority,
    ParentRepairRoute,
    RepairAction,
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
    WorkGroupDefinition,
    bind_model_route_recovery_policy,
    compile_design_work_graph,
    compile_world_work_graph,
    complete_generation_work_graph,
    derive_task_requirement_design_definitions,
    derive_world_plan_definitions,
    research_acquisition_work_definition,
    research_plan_work_definition,
    research_synthesis_work_definition,
    verifier_plan_work_definition,
    world_architecture_work_definition,
)
from .work_runtime import WorkControlRuntime
from .work_scheduler import WorkExecutionContext, WorkScheduler, WorkScheduleSnapshot
from .work_store import WorkControlStore, WorkResumeError

if TYPE_CHECKING:
    from agent_world.designer import EnvironmentDesigner
    from agent_world.observability.projector import SceneProjector


class DirectWorkRunnerError(RuntimeError):
    """The scheduler vertical slice cannot start from its frozen inputs."""

    def __init__(
        self,
        message: str,
        *,
        safe_code: str | None = None,
        safe_coordinate_keys: tuple[str, ...] = (),
    ) -> None:
        super().__init__(message)
        self.safe_code = safe_code
        self.safe_coordinate_keys = safe_coordinate_keys


class DirectWorkRun(V2Contract):
    """Durable terminal projection of one scheduler-owned Direct attempt."""

    run_id: str
    context_ref: ArtifactRef
    status: Literal["released", "blocked"]
    bootstrap_epoch_ref: ArtifactRef
    observed_actual: BudgetUsage
    unknown_upper_bound: BudgetUsage
    design_epoch_ref: ArtifactRef | None = None
    world_epoch_ref: ArtifactRef | None = None
    final_epoch_ref: ArtifactRef | None = None
    package_manifest_ref: ArtifactRef | None = None
    release_ref: ArtifactRef | None = None
    blocked_coordinates: tuple[str, ...] = ()


class SemanticPrefixRun(V2Contract):
    """One normal Direct semantic closure with no final-epoch execution.

    This is deliberately not a ``DirectWorkRun`` and cannot claim a Package or
    Registry release.  It exists only to make the exact, active
    ``ModelingBoundary -> VerifierPlan`` closure available as an input to a
    later isolated downstream-node test.  The commits themselves are normal
    Scheduler commits, not diagnostic-test commits or replayed output.
    """

    run_id: str
    scope_id: str
    context_ref: ArtifactRef
    status: Literal["semantic_prefix_ready", "blocked"]
    bootstrap_epoch_ref: ArtifactRef
    world_epoch_ref: ArtifactRef | None = None
    design_epoch_ref: ArtifactRef | None = None
    modeling_commit_ref: ArtifactRef | None = None
    verifier_plan_commit_ref: ArtifactRef | None = None
    environment_design_ref: ArtifactRef | None = None
    verifier_batch_plan_ref: ArtifactRef | None = None
    observed_actual: BudgetUsage
    unknown_upper_bound: BudgetUsage
    blocked_coordinates: tuple[str, ...] = ()
    diagnostic_only: Literal[False] = False
    release_attempted: Literal[False] = False

    @model_validator(mode="after")
    def validate_terminal_state(self) -> SemanticPrefixRun:
        ready_refs = (
            self.design_epoch_ref,
            self.modeling_commit_ref,
            self.verifier_plan_commit_ref,
            self.environment_design_ref,
            self.verifier_batch_plan_ref,
        )
        if self.status == "semantic_prefix_ready":
            if any(ref is None for ref in ready_refs):
                raise ValueError("ready semantic prefix requires its complete typed commit closure")
            if self.blocked_coordinates:
                raise ValueError("ready semantic prefix cannot name blocked coordinates")
        elif any(
            ref is not None
            for ref in (
                self.modeling_commit_ref,
                self.verifier_plan_commit_ref,
                self.environment_design_ref,
                self.verifier_batch_plan_ref,
            )
        ):
            raise ValueError("blocked semantic prefix cannot claim active terminal commits")
        return self


@dataclass(slots=True)
class _SemanticPrefixExecution:
    """Internal exact state retained between Direct topology epochs."""

    runtime: WorkControlRuntime
    workspace: Path
    bootstrap_epoch_ref: ArtifactRef
    world_epoch_ref: ArtifactRef | None = None
    design_epoch_ref: ArtifactRef | None = None
    design_graph: GenerationWorkGraph | None = None
    modeling_definition: WorkDefinition | None = None
    verifier_plan_definition: WorkDefinition | None = None
    ready: bool = False
    blocked_coordinates: tuple[str, ...] = ()


@dataclass(slots=True)
class _WorldSuffixExecution:
    """One world epoch derived after an already-committed bootstrap epoch."""

    graph: GenerationWorkGraph
    epoch_ref: ArtifactRef
    modeling_template: WorkDefinition
    snapshot: WorkScheduleSnapshot


@dataclass(slots=True)
class _DesignSuffixExecution:
    """One design epoch derived after an already-committed world epoch."""

    graph: GenerationWorkGraph
    epoch_ref: ArtifactRef
    snapshot: WorkScheduleSnapshot


@dataclass(slots=True)
class _FrozenRecoveryProtection:
    """The immutable prefix and the narrowly authorized causal backjump cone.

    A selected frozen coordinate normally treats every ancestor as an immutable
    prerequisite.  A descendant gate may, however, have already caused the
    Scheduler to authorize one exact repair on such an ancestor.  In that case
    the target and its causal descendants must be allowed to refresh; otherwise
    the runner would reject the Scheduler's own repair route before the repair
    leaf can start.  ``mutable_coordinate_keys`` is deliberately process-local:
    the durable authority remains the target head's ``RepairAction``.
    """

    protected_coordinate_keys: frozenset[str]
    mutable_coordinate_keys: set[str]


@dataclass(slots=True)
class DirectWorkRunner:
    """Execute one complete Direct WorkGraph through Registry publication.

    The runner has no semantic authority: all semantic source drafts are
    produced by isolated role leaves, all state-transition structure is
    compiled by deterministic code, and every failed node remains a durable
    Scheduler boundary.  Its only dynamic topology decisions are derived from
    committed ``ToolCouplingPlan`` and ``VerifierBatchPlan`` artifacts.
    """

    artifacts: ArtifactWriter
    heads: WorkControlStore
    designer: EnvironmentDesigner
    builder: EnvironmentBuilder
    verifier_compiler: VerifierCompiler
    judge: EnvironmentJudge
    registry: EnvironmentRegistry
    telemetry: TelemetryStore
    workspace_root: Path
    structured_turn_token_limit: int
    structured_turn_wall_seconds: float
    environment_codegen_session_token_limit: int
    environment_codegen_session_wall_seconds: float
    environment_codegen_physical_turn_token_limit: int
    # Complete, explicitly configured order including the primary model.
    # WorkRuntime alone may choose a later route after a classified transient;
    # leaves never mutate their profile route themselves.
    model_routes: tuple[str, ...] = ()
    route_liveness_checker: RouteLivenessChecker | None = None
    require_route_liveness_gate: bool = False
    infrastructure_retry_backoff_seconds: float = 0.0
    maximum_same_model_infrastructure_retries: int = 1
    maximum_concurrency: int = 4
    projector: SceneProjector | None = None

    async def run(
        self,
        *,
        context_ref: ArtifactRef,
        run_id: str | None = None,
        recovering: bool = False,
        recovery_snapshot: JobRunSnapshot | None = None,
        recovery_snapshot_ref: ArtifactRef | None = None,
        recovery_epoch_ref: ArtifactRef | None = None,
        recovery_coordinate: WorkCoordinate | None = None,
        resume_authority_ref: ArtifactRef | None = None,
        recovery_frontier: bool = False,
    ) -> DirectWorkRun:
        context, job, request = self._load_context(context_ref)
        self._validate_execution_configuration()

        # Controller owns DirectJob identity.  The Scheduler must use that
        # exact id for root and child telemetry so ``run inspect --metrics``
        # exposes real model/tool/process work rather than an orphan trace.
        run_id = run_id or f"scheduler-direct:{context.context_id}"
        trace_id = run_id
        if recovering:
            self.telemetry.reconcile_abandoned_trace(trace_id)
        root = self.telemetry.start_span(
            trace_id=trace_id,
            component="controller",
            operation="direct.generate",
            run_id=run_id,
            node="request",
            input_refs=(context_ref,),
            attributes={"topology": "four-epoch-direct-v2"},
        )
        self.telemetry.activate_trace(
            trace_id=trace_id,
            run_id=run_id,
            parent_span_id=root.span_id,
        )
        try:
            outcome = await self._run_under_trace(
                context_ref=context_ref,
                context=context,
                job=job,
                request=request,
                run_id=run_id,
                trace_id=trace_id,
                recovery_snapshot=recovery_snapshot,
                recovery_snapshot_ref=recovery_snapshot_ref,
                recovery_epoch_ref=recovery_epoch_ref,
                recovery_coordinate=recovery_coordinate,
                resume_authority_ref=resume_authority_ref,
                recovery_frontier=recovery_frontier,
            )
        except Exception as exc:
            root.finish(status="error", error_code=type(exc).__name__)
            self.telemetry.flush()
            raise
        if outcome.status == "released":
            output_refs = tuple(
                ref
                for ref in (outcome.package_manifest_ref, outcome.release_ref)
                if ref is not None
            )
            root.finish(status="passed", output_refs=output_refs)
        else:
            root.finish(status="failed", error_code="scheduler_blocked")
        self.telemetry.flush()
        return outcome

    async def run_semantic_prefix(
        self,
        *,
        context_ref: ArtifactRef,
        run_id: str | None = None,
    ) -> SemanticPrefixRun:
        """Execute real Direct work only through the committed VerifierPlan.

        The normal ``run`` method remains the only production route to a
        release.  This explicit staged entry is a test-control boundary: it
        uses the same non-diagnostic Scheduler, role leaves, invocation
        backend, ArtifactStore, and active-commit rules, then stops before the
        final epoch exists.  It cannot create a Package or Registry result.
        """

        context, job, request = self._load_context(context_ref)
        self._validate_execution_configuration()
        run_id = run_id or f"semantic-prefix:{context.context_id}"
        trace_id = run_id
        root = self.telemetry.start_span(
            trace_id=trace_id,
            component="controller",
            operation="direct.semantic_prefix",
            run_id=run_id,
            node="request",
            input_refs=(context_ref,),
            attributes={
                "topology": "bootstrap-world-design-prefix-v2",
                "release_attempted": False,
            },
        )
        self.telemetry.activate_trace(
            trace_id=trace_id,
            run_id=run_id,
            parent_span_id=root.span_id,
        )
        try:
            prefix = await self._run_semantic_prefix_under_trace(
                context_ref=context_ref,
                context=context,
                job=job,
                request=request,
                run_id=run_id,
                trace_id=trace_id,
            )
            outcome = self._semantic_prefix_outcome(
                prefix=prefix,
                context_ref=context_ref,
                scope_id=job.job_id,
                run_id=run_id,
            )
        except Exception as exc:
            root.finish(status="error", error_code=type(exc).__name__)
            self.telemetry.flush()
            raise
        output_refs = tuple(
            ref
            for ref in (
                outcome.bootstrap_epoch_ref,
                outcome.world_epoch_ref,
                outcome.design_epoch_ref,
                outcome.modeling_commit_ref,
                outcome.verifier_plan_commit_ref,
                outcome.environment_design_ref,
                outcome.verifier_batch_plan_ref,
            )
            if ref is not None
        )
        if outcome.status == "semantic_prefix_ready":
            root.finish(status="passed", output_refs=output_refs)
        else:
            root.finish(
                status="failed",
                error_code="semantic_prefix_blocked",
                output_refs=output_refs,
            )
        self.telemetry.flush()
        return outcome

    async def _run_under_trace(
        self,
        *,
        context_ref: ArtifactRef,
        context: GenerationContext,
        job: EnvironmentJob,
        request: EnvironmentRequest,
        run_id: str,
        trace_id: str,
        recovery_snapshot: JobRunSnapshot | None = None,
        recovery_snapshot_ref: ArtifactRef | None = None,
        recovery_epoch_ref: ArtifactRef | None = None,
        recovery_coordinate: WorkCoordinate | None = None,
        resume_authority_ref: ArtifactRef | None = None,
        recovery_frontier: bool = False,
        protected_coordinate_keys: frozenset[str] = frozenset(),
    ) -> DirectWorkRun:
        if recovery_frontier:
            if recovery_coordinate is not None or resume_authority_ref is not None:
                raise DirectWorkRunnerError(
                    "committed-frontier recovery cannot bind a stopped node or resume authority"
                )
            if (
                recovery_snapshot is None
                or recovery_snapshot_ref is None
                or recovery_epoch_ref is None
            ):
                raise DirectWorkRunnerError(
                    "committed-frontier recovery requires snapshot, snapshot ref, and epoch"
                )
            return await self._run_from_committed_frozen_frontier(
                context_ref=context_ref,
                context=context,
                job=job,
                run_id=run_id,
                trace_id=trace_id,
                snapshot=recovery_snapshot,
                snapshot_ref=recovery_snapshot_ref,
                epoch_ref=recovery_epoch_ref,
            )
        recovery_args = (
            recovery_snapshot,
            recovery_snapshot_ref,
            recovery_epoch_ref,
            recovery_coordinate,
        )
        if any(item is not None for item in recovery_args):
            if any(item is None for item in recovery_args):
                raise DirectWorkRunnerError(
                    "frozen node recovery requires snapshot, snapshot ref, epoch, and coordinate"
                )
            assert recovery_snapshot is not None
            assert recovery_snapshot_ref is not None
            assert recovery_epoch_ref is not None
            assert recovery_coordinate is not None
            return await self._run_from_frozen_epoch(
                context_ref=context_ref,
                context=context,
                job=job,
                run_id=run_id,
                trace_id=trace_id,
                snapshot=recovery_snapshot,
                snapshot_ref=recovery_snapshot_ref,
                epoch_ref=recovery_epoch_ref,
                coordinate=recovery_coordinate,
                resume_authority_ref=resume_authority_ref,
            )
        prefix = await self._run_semantic_prefix_under_trace(
            context_ref=context_ref,
            context=context,
            job=job,
            request=request,
            run_id=run_id,
            trace_id=trace_id,
            protected_coordinate_keys=protected_coordinate_keys,
        )
        runtime = prefix.runtime
        if not prefix.ready:
            usage = self._scope_budget_usage(runtime=runtime, scope_id=job.job_id)
            return self._persist_outcome(
                run_id=run_id,
                context_ref=context_ref,
                status="blocked",
                bootstrap_epoch_ref=prefix.bootstrap_epoch_ref,
                world_epoch_ref=prefix.world_epoch_ref,
                design_epoch_ref=prefix.design_epoch_ref,
                observed_actual=usage["observed_actual"],
                unknown_upper_bound=usage["unknown_upper_bound"],
                blocked_coordinates=prefix.blocked_coordinates,
            )

        if prefix.design_graph is None or prefix.design_epoch_ref is None:
            raise DirectWorkRunnerError(
                "ready semantic prefix lacks its exact Design graph closure"
            )
        if prefix.world_epoch_ref is None:
            raise DirectWorkRunnerError("ready semantic prefix lacks its exact World epoch")
        return await self._run_final_suffix_from_design(
            context_ref=context_ref,
            context=context,
            job=job,
            run_id=run_id,
            trace_id=trace_id,
            workspace=prefix.workspace,
            runtime=runtime,
            bootstrap_epoch_ref=prefix.bootstrap_epoch_ref,
            world_epoch_ref=prefix.world_epoch_ref,
            design_epoch_ref=prefix.design_epoch_ref,
            design_graph=prefix.design_graph,
            protected_coordinate_keys=protected_coordinate_keys,
        )

    async def _run_from_committed_frozen_frontier(
        self,
        *,
        context_ref: ArtifactRef,
        context: GenerationContext,
        job: EnvironmentJob,
        run_id: str,
        trace_id: str,
        snapshot: JobRunSnapshot,
        snapshot_ref: ArtifactRef,
        epoch_ref: ArtifactRef,
    ) -> DirectWorkRun:
        """Advance one explicitly selected, fully committed frozen epoch.

        This is deliberately distinct from node retry.  A caller selects an
        immutable epoch whose *entire* graph is already the active committed
        closure; no node in that graph is re-executed.  The runner then derives
        only its causal successor epoch.  It is how a fixed control-plane bug
        can be tested against the same durable job without replaying an
        unrelated prefix.
        """

        if snapshot.job_ref != context.job_ref:
            raise DirectWorkRunnerError(
                "frozen frontier snapshot belongs to another Direct job",
                safe_code="frozen_frontier_snapshot_job_mismatch",
            )
        self.artifacts.require_exact_json(
            snapshot_ref,
            snapshot,
            artifact_types=("control.job_run_snapshot",),
        )
        epoch, manifest, graph = self._load_exact_frozen_epoch_graph(
            context_ref=context_ref,
            job=job,
            epoch_ref=epoch_ref,
        )
        # An epoch keeps exact predecessor Commit revisions.  Checking merely
        # that today's heads say "committed" would permit a frontier to cross a
        # historical repair and mix two semantic closures.
        self._require_epoch_retained_commits_active(
            graph=graph,
            retained_commit_refs=epoch.retained_commit_refs,
        )

        workspace, runtime = self._new_runtime(
            context=context,
            job=job,
            run_id=run_id,
            trace_id=trace_id,
        )
        scheduler = WorkScheduler(
            graph=graph,
            manifest=manifest,
            manifest_ref=epoch.manifest_ref,
            heads=self.heads,
            artifacts=self.artifacts,
            runtime=runtime,
        )
        frontier_snapshot = scheduler.snapshot()
        if not self._all_committed(frontier_snapshot):
            non_committed = tuple(
                item.coordinate.coordinate_key
                for item in frontier_snapshot.work
                if item.state != "committed"
            )
            raise DirectWorkRunnerError(
                "selected frozen epoch is not a fully committed active frontier",
                safe_code="frozen_frontier_not_fully_committed",
                safe_coordinate_keys=non_committed,
            )

        epoch_refs_by_kind = self._epoch_refs_by_kind(
            epoch_ref=epoch_ref,
            context_ref=context_ref,
        )
        usage = self._scope_budget_usage(runtime=runtime, scope_id=job.job_id)
        if epoch.epoch_kind == "final":
            publication = self._one_definition(graph, component="registry", stage="publication")
            release_ref = self._active_output(publication, artifact_type="release.record")
            self.artifacts.get_json(release_ref, ReleaseRecord)
            package = self._one_definition(graph, component="release", stage="package")
            package_manifest_ref = self._active_output(
                package,
                artifact_type="environment_package_manifest",
            )
            return self._persist_outcome(
                run_id=run_id,
                context_ref=context_ref,
                status="released",
                bootstrap_epoch_ref=epoch_refs_by_kind["bootstrap"],
                world_epoch_ref=epoch_refs_by_kind.get("world"),
                design_epoch_ref=epoch_refs_by_kind.get("design"),
                final_epoch_ref=epoch_ref,
                package_manifest_ref=package_manifest_ref,
                release_ref=release_ref,
                observed_actual=usage["observed_actual"],
                unknown_upper_bound=usage["unknown_upper_bound"],
            )
        return await self._advance_from_recovered_epoch(
            context_ref=context_ref,
            context=context,
            job=job,
            run_id=run_id,
            trace_id=trace_id,
            epoch=epoch,
            epoch_ref=epoch_ref,
            graph=graph,
            epoch_refs_by_kind=epoch_refs_by_kind,
            workspace=workspace,
            runtime=runtime,
            kernel=SchedulerLeafExecutor(runtime=runtime),
        )

    def _load_exact_frozen_epoch_graph(
        self,
        *,
        context_ref: ArtifactRef,
        job: EnvironmentJob,
        epoch_ref: ArtifactRef,
    ) -> tuple[WorkGraphEpoch, WorkGraphManifest, GenerationWorkGraph]:
        """Load one exact epoch only after proving its immutable root closure."""

        if epoch_ref.artifact_type != "control.work_graph_epoch":
            raise DirectWorkRunnerError(
                "frozen recovery requires a WorkGraphEpoch Artifact",
                safe_code="frozen_epoch_artifact_type_invalid",
            )
        epoch = self.artifacts.get_json(epoch_ref, WorkGraphEpoch)
        self.artifacts.require_exact_json(
            epoch_ref,
            epoch,
            artifact_types=("control.work_graph_epoch",),
        )
        if epoch.context_ref != context_ref or epoch.scope_id != job.job_id:
            raise DirectWorkRunnerError(
                "selected frozen epoch does not bind this Direct GenerationContext",
                safe_code="frozen_epoch_context_mismatch",
            )
        manifest = self.artifacts.get_json(epoch.manifest_ref, WorkGraphManifest)
        graph = self._reconstruct_frozen_graph(manifest)
        expected_manifest = graph.manifest(
            topology_id=manifest.topology_id,
            external_root_refs=manifest.external_root_refs,
        )
        if expected_manifest != manifest:
            raise DirectWorkRunnerError(
                "frozen WorkGraph manifest cannot be reconstructed exactly",
                safe_code="frozen_epoch_manifest_reconstruction_failed",
            )
        if manifest.external_root_refs != (context_ref,):
            raise DirectWorkRunnerError(
                "frozen WorkGraph has an incompatible root closure",
                safe_code="frozen_epoch_root_closure_mismatch",
            )
        return epoch, manifest, graph

    async def _run_from_frozen_epoch(
        self,
        *,
        context_ref: ArtifactRef,
        context: GenerationContext,
        job: EnvironmentJob,
        run_id: str,
        trace_id: str,
        snapshot: JobRunSnapshot,
        snapshot_ref: ArtifactRef,
        epoch_ref: ArtifactRef,
        coordinate: WorkCoordinate,
        resume_authority_ref: ArtifactRef | None,
    ) -> DirectWorkRun:
        """Resume one exact frozen graph without redispatching its ancestors.

        The selected epoch is immutable provenance, not a hint to rebuild the
        whole pipeline.  A terminal target needs a separately persisted
        ``NodeResumeAuthority``; a pre-existing Scheduler repair remains on
        its ordinary repair path.  Once this epoch reaches a committed
        frontier, only its causal successor epoch may be derived.  The normal
        root topology must never be re-derived here: that would convert a
        physical control-plane fix into a second spend of already-committed
        semantic work.
        """

        if snapshot.job_ref != context.job_ref:
            raise DirectWorkRunnerError("frozen recovery snapshot belongs to another Direct job")
        epoch, manifest, graph = self._load_exact_frozen_epoch_graph(
            context_ref=context_ref,
            job=job,
            epoch_ref=epoch_ref,
        )
        try:
            target = graph.require(coordinate)
        except Exception as exc:
            raise DirectWorkRunnerError(
                "selected coordinate is absent from the frozen WorkGraph"
            ) from exc

        if resume_authority_ref is not None:
            authority = self.artifacts.get_json(resume_authority_ref, NodeResumeAuthority)
            self.artifacts.require_exact_json(
                resume_authority_ref,
                authority,
                artifact_types=("control.node_resume_authority",),
            )
            if (
                authority.source_snapshot_ref != snapshot_ref
                or authority.source_context_ref != context_ref
                or authority.source_epoch_ref != epoch_ref
                or authority.coordinate != coordinate
                or authority.source_definition_digest != target.definition_digest
            ):
                raise DirectWorkRunnerError(
                    "node resume authority does not bind this frozen target"
                )

        workspace, runtime = self._new_runtime(
            context=context,
            job=job,
            run_id=run_id,
            trace_id=trace_id,
        )
        self._require_epoch_retained_commits_active(
            graph=graph,
            retained_commit_refs=epoch.retained_commit_refs,
        )
        protected = frozenset(item.coordinate_key for item in graph.ancestors(coordinate))
        protection = self._frozen_recovery_protection(
            graph=graph,
            coordinate=coordinate,
            protected_coordinate_keys=protected,
        )
        kernel = SchedulerLeafExecutor(runtime=runtime)
        executors = self._executors_for_frozen_epoch(
            epoch=epoch,
            epoch_ref=epoch_ref,
            manifest_ref=epoch.manifest_ref,
            context_ref=context_ref,
            context=context,
            workspace=workspace,
            run_id=run_id,
            trace_id=trace_id,
            kernel=kernel,
            graph=graph,
        )
        scheduler = WorkScheduler(
            graph=graph,
            manifest=manifest,
            manifest_ref=epoch.manifest_ref,
            heads=self.heads,
            artifacts=self.artifacts,
            runtime=runtime,
        )
        self._require_frozen_recovery_protection(
            scheduler=scheduler,
            graph=graph,
            protection=protection,
        )
        if resume_authority_ref is not None:
            resolved = scheduler.resolve_inputs(coordinate)
            with self.heads.exclusive(coordinate) as lock:
                runtime.resume_terminal_by_authority(
                    lock,
                    definition=target,
                    input_refs=resolved.all_input_refs,
                    authority_ref=resume_authority_ref,
                )

        epoch_snapshot = await self._run_graph(
            graph=graph,
            manifest=manifest,
            manifest_ref=epoch.manifest_ref,
            runtime=runtime,
            executors=executors,
            protected_coordinate_keys=protected,
            frozen_recovery_protection=protection,
        )
        epoch_refs_by_kind = self._epoch_refs_by_kind(
            epoch_ref=epoch_ref,
            context_ref=context_ref,
        )
        usage = self._scope_budget_usage(runtime=runtime, scope_id=job.job_id)
        if not self._all_committed(epoch_snapshot):
            return self._persist_outcome(
                run_id=run_id,
                context_ref=context_ref,
                status="blocked",
                bootstrap_epoch_ref=epoch_refs_by_kind["bootstrap"],
                world_epoch_ref=epoch_refs_by_kind.get("world"),
                design_epoch_ref=epoch_refs_by_kind.get("design"),
                final_epoch_ref=epoch_refs_by_kind.get("final"),
                observed_actual=usage["observed_actual"],
                unknown_upper_bound=usage["unknown_upper_bound"],
                blocked_coordinates=self._blocked_coordinates(epoch_snapshot),
            )

        if epoch.epoch_kind == "final":
            publication = self._one_definition(graph, component="registry", stage="publication")
            release_ref = self._active_output(publication, artifact_type="release.record")
            self.artifacts.get_json(release_ref, ReleaseRecord)
            package = self._one_definition(graph, component="release", stage="package")
            package_manifest_ref = self._active_output(
                package,
                artifact_type="environment_package_manifest",
            )
            return self._persist_outcome(
                run_id=run_id,
                context_ref=context_ref,
                status="released",
                bootstrap_epoch_ref=epoch_refs_by_kind["bootstrap"],
                world_epoch_ref=epoch_refs_by_kind.get("world"),
                design_epoch_ref=epoch_refs_by_kind.get("design"),
                final_epoch_ref=epoch_ref,
                package_manifest_ref=package_manifest_ref,
                release_ref=release_ref,
                observed_actual=usage["observed_actual"],
                unknown_upper_bound=usage["unknown_upper_bound"],
            )

        return await self._advance_from_recovered_epoch(
            context_ref=context_ref,
            context=context,
            job=job,
            run_id=run_id,
            trace_id=trace_id,
            epoch=epoch,
            epoch_ref=epoch_ref,
            graph=graph,
            epoch_refs_by_kind=epoch_refs_by_kind,
            workspace=workspace,
            runtime=runtime,
            kernel=kernel,
        )

    async def _advance_from_recovered_epoch(
        self,
        *,
        context_ref: ArtifactRef,
        context: GenerationContext,
        job: EnvironmentJob,
        run_id: str,
        trace_id: str,
        epoch: WorkGraphEpoch,
        epoch_ref: ArtifactRef,
        graph: GenerationWorkGraph,
        epoch_refs_by_kind: dict[str, ArtifactRef],
        workspace: Path,
        runtime: WorkControlRuntime,
        kernel: SchedulerLeafExecutor,
    ) -> DirectWorkRun:
        """Advance exactly one recovered frozen frontier into its successors.

        This is deliberately separate from :meth:`_run_under_trace`.  The
        latter is the root constructor for a brand-new job; calling it after a
        recovery would recompute prior definitions using today's implementation
        revisions and can mark an immutable committed prefix ``stale``.  A
        recovered epoch instead supplies the exact predecessor graph and its
        active commits to the next compiler boundary.
        """

        if epoch.epoch_kind == "bootstrap":
            world = await self._run_world_suffix_from_bootstrap(
                context_ref=context_ref,
                context=context,
                job=job,
                bootstrap_epoch_ref=epoch_ref,
                bootstrap_graph=graph,
                workspace=workspace,
                runtime=runtime,
                kernel=kernel,
            )
            if not self._all_committed(world.snapshot):
                return self._blocked_recovered_outcome(
                    context_ref=context_ref,
                    job=job,
                    run_id=run_id,
                    runtime=runtime,
                    bootstrap_epoch_ref=epoch_ref,
                    world_epoch_ref=world.epoch_ref,
                    snapshot=world.snapshot,
                )
            return await self._advance_from_world_epoch(
                context_ref=context_ref,
                context=context,
                job=job,
                run_id=run_id,
                trace_id=trace_id,
                bootstrap_epoch_ref=epoch_ref,
                world_epoch_ref=world.epoch_ref,
                world_graph=world.graph,
                modeling_template=world.modeling_template,
                workspace=workspace,
                runtime=runtime,
                kernel=kernel,
            )

        if epoch.epoch_kind == "world":
            bootstrap_epoch_ref = epoch_refs_by_kind["bootstrap"]
            return await self._advance_from_world_epoch(
                context_ref=context_ref,
                context=context,
                job=job,
                run_id=run_id,
                trace_id=trace_id,
                bootstrap_epoch_ref=bootstrap_epoch_ref,
                world_epoch_ref=epoch_ref,
                world_graph=graph,
                modeling_template=self._modeling_template_from_frozen_world_epoch(
                    context=context,
                    job=job,
                    world_epoch=epoch,
                ),
                workspace=workspace,
                runtime=runtime,
                kernel=kernel,
            )

        if epoch.epoch_kind == "design":
            world_epoch_ref = epoch_refs_by_kind.get("world")
            if world_epoch_ref is None:
                raise DirectWorkRunnerError("frozen Design epoch lacks its World predecessor")
            return await self._run_final_suffix_from_design(
                context_ref=context_ref,
                context=context,
                job=job,
                run_id=run_id,
                trace_id=trace_id,
                workspace=workspace,
                runtime=runtime,
                bootstrap_epoch_ref=epoch_refs_by_kind["bootstrap"],
                world_epoch_ref=world_epoch_ref,
                design_epoch_ref=epoch_ref,
                design_graph=graph,
                protected_coordinate_keys=self._coordinate_keys(graph),
            )

        raise DirectWorkRunnerError("unknown recovered epoch kind")

    async def _advance_from_world_epoch(
        self,
        *,
        context_ref: ArtifactRef,
        context: GenerationContext,
        job: EnvironmentJob,
        run_id: str,
        trace_id: str,
        bootstrap_epoch_ref: ArtifactRef,
        world_epoch_ref: ArtifactRef,
        world_graph: GenerationWorkGraph,
        modeling_template: WorkDefinition,
        workspace: Path,
        runtime: WorkControlRuntime,
        kernel: SchedulerLeafExecutor,
    ) -> DirectWorkRun:
        """Derive and run only the Design/final suffix of a recovered World."""

        design = await self._run_design_suffix_from_world(
            context_ref=context_ref,
            context=context,
            job=job,
            world_epoch_ref=world_epoch_ref,
            world_graph=world_graph,
            modeling_template=modeling_template,
            workspace=workspace,
            runtime=runtime,
            kernel=kernel,
        )
        if not self._all_committed(design.snapshot):
            return self._blocked_recovered_outcome(
                context_ref=context_ref,
                job=job,
                run_id=run_id,
                runtime=runtime,
                bootstrap_epoch_ref=bootstrap_epoch_ref,
                world_epoch_ref=world_epoch_ref,
                design_epoch_ref=design.epoch_ref,
                snapshot=design.snapshot,
            )
        return await self._run_final_suffix_from_design(
            context_ref=context_ref,
            context=context,
            job=job,
            run_id=run_id,
            trace_id=trace_id,
            workspace=workspace,
            runtime=runtime,
            bootstrap_epoch_ref=bootstrap_epoch_ref,
            world_epoch_ref=world_epoch_ref,
            design_epoch_ref=design.epoch_ref,
            design_graph=design.graph,
            protected_coordinate_keys=self._coordinate_keys(design.graph),
        )

    async def _run_world_suffix_from_bootstrap(
        self,
        *,
        context_ref: ArtifactRef,
        context: GenerationContext,
        job: EnvironmentJob,
        bootstrap_epoch_ref: ArtifactRef,
        bootstrap_graph: GenerationWorkGraph,
        workspace: Path,
        runtime: WorkControlRuntime,
        kernel: SchedulerLeafExecutor,
    ) -> _WorldSuffixExecution:
        """Compile a World successor while preserving the frozen bootstrap bytes."""

        architecture = self._one_definition(
            bootstrap_graph,
            component="design",
            stage="world_architecture",
        )
        architecture_ref = self._active_output(
            architecture,
            artifact_type="design.world_architecture_source",
        )
        coupling_ref = self._active_output(
            architecture,
            artifact_type="design.tool_coupling_plan",
        )
        coupling_plan = self.artifacts.get_json(coupling_ref, ToolCouplingPlan)
        world_definitions, modeling_template = derive_world_plan_definitions(
            scope_id=job.job_id,
            bootstrap_definitions=bootstrap_graph.definitions,
            architecture_source_ref=architecture_ref,
            coupling_plan=coupling_plan,
            agent_wall_seconds=self._agent_wall(context.budget),
            agent_token_limit=self._agent_tokens(context.budget),
        )
        world_definitions = self._bind_model_route_recovery_definitions(
            world_definitions,
            preserve_coordinate_keys=self._coordinate_keys(bootstrap_graph),
        )
        world_graph = compile_world_work_graph(
            scope_id=job.job_id,
            world_definitions=world_definitions,
            strict_input_contracts=True,
        )
        epochs = WorkGraphEpochRuntime(artifacts=self.artifacts, heads=self.heads)
        world_manifest, world_manifest_ref, _world_epoch, world_epoch_ref = epochs.freeze_world(
            context_ref=context_ref,
            bootstrap_epoch_ref=bootstrap_epoch_ref,
            graph=world_graph,
            topology_id=f"topology:direct-world:{context.context_id}",
        )
        world_snapshot = await self._run_graph(
            graph=world_graph,
            manifest=world_manifest,
            manifest_ref=world_manifest_ref,
            runtime=runtime,
            executors=self._design_executors(
                context_ref=context_ref,
                workspace=workspace,
                kernel=kernel,
                graph=world_graph,
                verifier_plan=None,
            ),
            protected_coordinate_keys=self._coordinate_keys(bootstrap_graph),
        )
        return _WorldSuffixExecution(
            graph=world_graph,
            epoch_ref=world_epoch_ref,
            modeling_template=modeling_template,
            snapshot=world_snapshot,
        )

    def _modeling_template_from_frozen_world_epoch(
        self,
        *,
        context: GenerationContext,
        job: EnvironmentJob,
        world_epoch: WorkGraphEpoch,
    ) -> WorkDefinition:
        """Recreate only the unpersisted Modeling template from frozen parents.

        The template is a deterministic downstream compiler input, not an
        Agent result.  The committed World graph itself stays byte-for-byte
        frozen; this helper only obtains the next-stage template that was not
        yet materialized when the owner stopped.
        """

        bootstrap_epoch_ref = world_epoch.predecessor_epoch_ref
        if bootstrap_epoch_ref is None:
            raise DirectWorkRunnerError("frozen World epoch lacks its Bootstrap predecessor")
        bootstrap_epoch = self.artifacts.get_json(bootstrap_epoch_ref, WorkGraphEpoch)
        if bootstrap_epoch.epoch_kind != "bootstrap":
            raise DirectWorkRunnerError("frozen World epoch has an invalid Bootstrap predecessor")
        bootstrap_manifest = self.artifacts.get_json(
            bootstrap_epoch.manifest_ref,
            WorkGraphManifest,
        )
        bootstrap_graph = self._reconstruct_frozen_graph(bootstrap_manifest)
        architecture = self._one_definition(
            bootstrap_graph,
            component="design",
            stage="world_architecture",
        )
        architecture_ref = self._active_output(
            architecture,
            artifact_type="design.world_architecture_source",
        )
        coupling_ref = self._active_output(
            architecture,
            artifact_type="design.tool_coupling_plan",
        )
        coupling_plan = self.artifacts.get_json(coupling_ref, ToolCouplingPlan)
        _world_definitions, modeling_template = derive_world_plan_definitions(
            scope_id=job.job_id,
            bootstrap_definitions=bootstrap_graph.definitions,
            architecture_source_ref=architecture_ref,
            coupling_plan=coupling_plan,
            agent_wall_seconds=self._agent_wall(context.budget),
            agent_token_limit=self._agent_tokens(context.budget),
        )
        return modeling_template

    async def _run_design_suffix_from_world(
        self,
        *,
        context_ref: ArtifactRef,
        context: GenerationContext,
        job: EnvironmentJob,
        world_epoch_ref: ArtifactRef,
        world_graph: GenerationWorkGraph,
        modeling_template: WorkDefinition,
        workspace: Path,
        runtime: WorkControlRuntime,
        kernel: SchedulerLeafExecutor,
    ) -> _DesignSuffixExecution:
        """Compile a Design successor while preserving the frozen World graph."""

        curriculum_plan_definition = self._one_definition(
            world_graph,
            component="design",
            stage="curriculum_plan",
        )
        curriculum_plan_ref = self._active_output(
            curriculum_plan_definition,
            artifact_type="design.curriculum_plan_source",
        )
        curriculum_plan = self.artifacts.get_json(
            curriculum_plan_ref,
            CurriculumPlanSourceDraft,
        )
        final_design_definitions, modeling = derive_task_requirement_design_definitions(
            scope_id=job.job_id,
            world_definitions=world_graph.definitions,
            curriculum_plan_ref=curriculum_plan_ref,
            curriculum_plan=curriculum_plan,
            modeling_template=modeling_template,
            agent_wall_seconds=self._agent_wall(context.budget),
            agent_token_limit=self._agent_tokens(context.budget),
        )
        final_design_definitions = self._bind_model_route_recovery_definitions(
            final_design_definitions,
            preserve_coordinate_keys=self._coordinate_keys(world_graph),
        )
        task_requirement_order = tuple(
            item.coordinate
            for item in final_design_definitions
            if (item.coordinate.component, item.coordinate.stage) == ("design", "task_requirement")
        )
        verifier_plan = verifier_plan_work_definition(
            scope_id=job.job_id,
            modeling_coordinate=modeling.coordinate,
        )
        design_graph = compile_design_work_graph(
            scope_id=job.job_id,
            design_definitions=final_design_definitions,
            modeling_definition=modeling,
            verifier_plan_definition=verifier_plan,
            strict_input_contracts=True,
        )
        epochs = WorkGraphEpochRuntime(artifacts=self.artifacts, heads=self.heads)
        design_manifest, design_manifest_ref, _design_epoch, design_epoch_ref = (
            epochs.freeze_design_from_world(
                context_ref=context_ref,
                world_epoch_ref=world_epoch_ref,
                graph=design_graph,
                topology_id=f"topology:direct-design:{context.context_id}",
            )
        )
        design_snapshot = await self._run_graph(
            graph=design_graph,
            manifest=design_manifest,
            manifest_ref=design_manifest_ref,
            runtime=runtime,
            executors=self._design_executors(
                context_ref=context_ref,
                workspace=workspace,
                kernel=kernel,
                graph=design_graph,
                verifier_plan=verifier_plan,
            ),
            stop_after_first_block=True,
            preferred_order=task_requirement_order,
            protected_coordinate_keys=self._coordinate_keys(world_graph),
        )
        return _DesignSuffixExecution(
            graph=design_graph,
            epoch_ref=design_epoch_ref,
            snapshot=design_snapshot,
        )

    async def _run_final_suffix_from_design(
        self,
        *,
        context_ref: ArtifactRef,
        context: GenerationContext,
        job: EnvironmentJob,
        run_id: str,
        trace_id: str,
        workspace: Path,
        runtime: WorkControlRuntime,
        bootstrap_epoch_ref: ArtifactRef,
        world_epoch_ref: ArtifactRef,
        design_epoch_ref: ArtifactRef,
        design_graph: GenerationWorkGraph,
        protected_coordinate_keys: frozenset[str] = frozenset(),
    ) -> DirectWorkRun:
        """Run the production suffix from one exact committed Design graph."""

        verifier_plan = self._one_definition(
            design_graph,
            component="verifier",
            stage="verifier_plan",
        )
        plan_ref = self._active_output(verifier_plan, artifact_type="judge.verifier_batch_plan")
        plan = self.artifacts.get_json(plan_ref, VerifierBatchPlan)
        modeling_definition = self._one_definition(
            design_graph,
            component="design",
            stage="modeling_boundary",
        )
        design_ref = self._active_output(
            modeling_definition,
            artifact_type="design.environment_design",
        )
        design = self.artifacts.get_json(design_ref, EnvironmentDesign)
        if plan.design_ref != design_ref:
            raise DirectWorkRunnerError(
                "committed VerifierPlan does not bind the final graph EnvironmentDesign"
            )
        final_graph = self._bind_model_route_recovery_graph(
            complete_generation_work_graph(
                scope_id=job.job_id,
                design_graph=design_graph,
                implementation_plan_token_limit=self._codegen_physical_turn_tokens(context.budget),
                implementation_plan_wall_seconds=self._codegen_session_wall(context.budget),
                implementation_plan_session_token_limit=self._codegen_session_tokens(
                    context.budget
                ),
                implementation_plan_session_wall_seconds=self._codegen_session_wall(context.budget),
                builder_token_limit=self._codegen_physical_turn_tokens(context.budget),
                builder_wall_seconds=self._codegen_session_wall(context.budget),
                builder_session_token_limit=self._codegen_session_tokens(context.budget),
                builder_session_wall_seconds=self._codegen_session_wall(context.budget),
                verifier_batch_count=len(plan.batches),
                verifier_token_limit=self._verifier_group_tokens(
                    context.budget, batch_count=len(plan.batches)
                ),
                verifier_wall_seconds=self._verifier_group_wall(
                    context.budget, batch_count=len(plan.batches)
                ),
                environment_design=design,
                verifier_batch_plan=plan,
                strict_input_contracts=True,
            ),
            preserve_coordinate_keys=protected_coordinate_keys,
        )
        epochs = WorkGraphEpochRuntime(artifacts=self.artifacts, heads=self.heads)
        final_manifest, final_manifest_ref, _final_epoch, final_epoch_ref = epochs.freeze_final(
            context_ref=context_ref,
            design_epoch_ref=design_epoch_ref,
            graph=final_graph,
            topology_id=f"topology:direct-final:{context.context_id}",
        )
        kernel = SchedulerLeafExecutor(runtime=runtime)
        final_snapshot = await self._run_graph(
            graph=final_graph,
            manifest=final_manifest,
            manifest_ref=final_manifest_ref,
            runtime=runtime,
            executors=self._final_executors(
                context_ref=context_ref,
                context=context,
                workspace=workspace,
                run_id=run_id,
                trace_id=trace_id,
                kernel=kernel,
                graph=final_graph,
                final_epoch_ref=final_epoch_ref,
                final_manifest_ref=final_manifest_ref,
            ),
            protected_coordinate_keys=protected_coordinate_keys,
        )
        if not self._all_committed(final_snapshot):
            return self._blocked_recovered_outcome(
                context_ref=context_ref,
                job=job,
                run_id=run_id,
                runtime=runtime,
                bootstrap_epoch_ref=bootstrap_epoch_ref,
                world_epoch_ref=world_epoch_ref,
                design_epoch_ref=design_epoch_ref,
                final_epoch_ref=final_epoch_ref,
                snapshot=final_snapshot,
            )

        publication = self._one_definition(final_graph, component="registry", stage="publication")
        release_ref = self._active_output(publication, artifact_type="release.record")
        self.artifacts.get_json(release_ref, ReleaseRecord)
        package = self._one_definition(final_graph, component="release", stage="package")
        package_manifest_ref = self._active_output(
            package,
            artifact_type="environment_package_manifest",
        )
        usage = self._scope_budget_usage(runtime=runtime, scope_id=job.job_id)
        return self._persist_outcome(
            run_id=run_id,
            context_ref=context_ref,
            status="released",
            bootstrap_epoch_ref=bootstrap_epoch_ref,
            world_epoch_ref=world_epoch_ref,
            design_epoch_ref=design_epoch_ref,
            final_epoch_ref=final_epoch_ref,
            package_manifest_ref=package_manifest_ref,
            release_ref=release_ref,
            observed_actual=usage["observed_actual"],
            unknown_upper_bound=usage["unknown_upper_bound"],
        )

    def _blocked_recovered_outcome(
        self,
        *,
        context_ref: ArtifactRef,
        job: EnvironmentJob,
        run_id: str,
        runtime: WorkControlRuntime,
        bootstrap_epoch_ref: ArtifactRef,
        snapshot: WorkScheduleSnapshot,
        world_epoch_ref: ArtifactRef | None = None,
        design_epoch_ref: ArtifactRef | None = None,
        final_epoch_ref: ArtifactRef | None = None,
    ) -> DirectWorkRun:
        usage = self._scope_budget_usage(runtime=runtime, scope_id=job.job_id)
        return self._persist_outcome(
            run_id=run_id,
            context_ref=context_ref,
            status="blocked",
            bootstrap_epoch_ref=bootstrap_epoch_ref,
            world_epoch_ref=world_epoch_ref,
            design_epoch_ref=design_epoch_ref,
            final_epoch_ref=final_epoch_ref,
            observed_actual=usage["observed_actual"],
            unknown_upper_bound=usage["unknown_upper_bound"],
            blocked_coordinates=self._blocked_coordinates(snapshot),
        )

    @staticmethod
    def _coordinate_keys(graph: GenerationWorkGraph) -> frozenset[str]:
        return frozenset(item.coordinate.coordinate_key for item in graph.definitions)

    def _epoch_refs_by_kind(
        self,
        *,
        epoch_ref: ArtifactRef,
        context_ref: ArtifactRef,
    ) -> dict[str, ArtifactRef]:
        """Resolve one selected epoch's predecessor chain without chronology guesses."""

        refs: dict[str, ArtifactRef] = {}
        current_ref: ArtifactRef | None = epoch_ref
        while current_ref is not None:
            epoch = self.artifacts.get_json(current_ref, WorkGraphEpoch)
            self.artifacts.require_exact_json(
                current_ref,
                epoch,
                artifact_types=("control.work_graph_epoch",),
            )
            if epoch.context_ref != context_ref:
                raise DirectWorkRunnerError("frozen epoch chain has an incompatible context")
            prior = refs.setdefault(epoch.epoch_kind, current_ref)
            if prior != current_ref:
                raise DirectWorkRunnerError("frozen epoch chain has duplicate epoch kinds")
            current_ref = epoch.predecessor_epoch_ref
        if "bootstrap" not in refs:
            raise DirectWorkRunnerError("frozen epoch chain lacks its bootstrap root")
        return refs

    def _executors_for_frozen_epoch(
        self,
        *,
        epoch: WorkGraphEpoch,
        epoch_ref: ArtifactRef,
        manifest_ref: ArtifactRef,
        context_ref: ArtifactRef,
        context: GenerationContext,
        workspace: Path,
        run_id: str,
        trace_id: str,
        kernel: SchedulerLeafExecutor,
        graph: GenerationWorkGraph,
    ) -> dict[str, object]:
        if epoch.epoch_kind == "bootstrap":
            return self._bootstrap_executors(
                context_ref=context_ref,
                workspace=workspace,
                kernel=kernel,
                definitions=graph.definitions,
            )
        if epoch.epoch_kind in {"world", "design"}:
            verifier_plan = next(
                (
                    definition
                    for definition in graph.definitions
                    if definition.coordinate.stage == "verifier_plan"
                ),
                None,
            )
            return self._design_executors(
                context_ref=context_ref,
                workspace=workspace,
                kernel=kernel,
                graph=graph,
                verifier_plan=verifier_plan,
            )
        if epoch.epoch_kind == "final":
            return self._final_executors(
                context_ref=context_ref,
                context=context,
                workspace=workspace,
                run_id=run_id,
                trace_id=trace_id,
                kernel=kernel,
                graph=graph,
                final_epoch_ref=epoch_ref,
                final_manifest_ref=manifest_ref,
            )
        raise DirectWorkRunnerError("unknown frozen epoch kind")

    @staticmethod
    def _require_protected_ancestors_committed(
        *,
        scheduler: WorkScheduler,
        protected_coordinate_keys: frozenset[str],
    ) -> None:
        if not protected_coordinate_keys:
            return
        states = {item.coordinate.coordinate_key: item.state for item in scheduler.snapshot().work}
        missing = tuple(
            key
            for key in sorted(protected_coordinate_keys)
            if key in states and states[key] != "committed"
        )
        if missing:
            raise DirectWorkRunnerError(
                "frozen resume will not redispatch a prerequisite: " + ", ".join(missing),
                safe_code="frozen_protected_prerequisite_not_committed",
                safe_coordinate_keys=missing,
            )

    @staticmethod
    def _frozen_recovery_protection(
        *,
        graph: GenerationWorkGraph,
        coordinate: WorkCoordinate,
        protected_coordinate_keys: frozenset[str],
    ) -> _FrozenRecoveryProtection:
        """Seed the mutable set with the selected suffix, never its ancestors."""

        mutable = {
            coordinate.coordinate_key,
            *(item.coordinate_key for item in graph.descendants(coordinate)),
        }
        return _FrozenRecoveryProtection(
            protected_coordinate_keys=protected_coordinate_keys,
            mutable_coordinate_keys=mutable,
        )

    def _require_frozen_recovery_protection(
        self,
        *,
        scheduler: WorkScheduler,
        graph: GenerationWorkGraph,
        protection: _FrozenRecoveryProtection,
    ) -> None:
        """Keep the frozen prefix closed except for Scheduler-authorized backjumps.

        A ``repair_authorized`` status alone is insufficient: it might belong to
        an unrelated earlier recovery.  The carveout is admitted only when its
        durable RepairAction is the target-local form produced for an exact
        ``ParentRepairRoute`` whose source sits in the already selected mutable
        suffix and whose graph edge is still declared.  Once admitted, the
        target's descendants must also be mutable because a new parent commit
        makes their old input fingerprints stale.
        """

        changed = True
        while changed:
            changed = False
            for definition in graph.topological_definitions():
                coordinate = definition.coordinate
                key = coordinate.coordinate_key
                if (
                    key not in protection.protected_coordinate_keys
                    or key in protection.mutable_coordinate_keys
                ):
                    continue
                head = self.heads.read_head(coordinate)
                if (
                    head is None
                    or head.status != "repair_authorized"
                    or head.repair_action_ref is None
                ):
                    continue
                action = self.artifacts.get_json(head.repair_action_ref, RepairAction)
                if (
                    action.current_coordinate != coordinate
                    or action.target_coordinate != coordinate
                    or action.definition_digest != definition.definition_digest
                    or action.input_fingerprint != head.input_fingerprint
                    or action.decision != "local_correction"
                    or action.reason_code != "causal_downstream_failure"
                ):
                    continue
                route_refs = tuple(
                    ref
                    for ref in action.causal_evidence_refs
                    if ref.artifact_type == "control.parent_repair_route"
                )
                if len(route_refs) != 1:
                    continue
                route = self.artifacts.get_json(route_refs[0], ParentRepairRoute)
                if (
                    route.target_coordinate != coordinate
                    or route.source_coordinate.coordinate_key
                    not in protection.mutable_coordinate_keys
                ):
                    continue
                try:
                    declared_target = graph.automatic_repair_target(
                        current=route.source_coordinate,
                        proposed_target=route.target_coordinate,
                    )
                except WorkGraphError:
                    continue
                if declared_target.coordinate != coordinate:
                    continue
                protection.mutable_coordinate_keys.add(key)
                protection.mutable_coordinate_keys.update(
                    item.coordinate_key for item in graph.descendants(coordinate)
                )
                changed = True

        self._require_protected_ancestors_committed(
            scheduler=scheduler,
            protected_coordinate_keys=(
                protection.protected_coordinate_keys - protection.mutable_coordinate_keys
            ),
        )

    def _new_runtime(
        self,
        *,
        context: GenerationContext,
        job: EnvironmentJob,
        run_id: str,
        trace_id: str,
    ) -> tuple[Path, WorkControlRuntime]:
        workspace = self.workspace_root / context.context_id
        workspace.mkdir(parents=True, exist_ok=True)
        runtime = WorkControlRuntime(
            artifacts=self.artifacts,
            heads=self.heads,
            budget=LeaseBudgetLedger(context.budget),
            repair_scope_id=job.job_id,
            continuations=NodeContinuationStore(workspace / ".continuations"),
            continuation_workspace_root=workspace,
            telemetry=self.telemetry,
            projector=self.projector,
            trace_id=trace_id,
            run_id=run_id,
            model_routes=self.model_routes,
            route_liveness_checker=self.route_liveness_checker,
            require_route_liveness_gate=self.require_route_liveness_gate,
            infrastructure_retry_backoff_seconds=self.infrastructure_retry_backoff_seconds,
        )
        return workspace, runtime

    @staticmethod
    def _snapshot_refs(snapshot: JobRunSnapshot) -> tuple[ArtifactRef, ...]:
        return tuple(dict.fromkeys(snapshot.latest_artifact_refs))

    def _reconstruct_frozen_graph(self, manifest: WorkGraphManifest) -> GenerationWorkGraph:
        definitions = tuple(
            self._definition_for_binding(
                binding.coordinate,
                binding.work_id,
                binding.definition_digest,
            )
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
            raise DirectWorkRunnerError("frozen WorkGraph group cannot be reconstructed")
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
            raise DirectWorkRunnerError("frozen WorkGraph milestone cannot be reconstructed")
        return GenerationWorkGraph.compile(
            definitions,
            mode=manifest.mode,
            strict_input_contracts=True,
            required_terminal_coordinates=manifest.required_terminal_coordinates,
            groups=groups,
            milestones=milestones,
        )

    def _definition_for_binding(
        self,
        coordinate: WorkCoordinate,
        work_id: str,
        definition_digest: str,
    ) -> WorkDefinition:
        candidates: list[WorkDefinition] = []
        for ref in self.artifacts.list_revisions():
            if (
                ref.artifact_type != "control.work_definition"
                or ref.content_hash != definition_digest
            ):
                continue
            try:
                definition = self.artifacts.get_json(ref, WorkDefinition)
            except ValueError:
                continue
            if (
                definition.coordinate == coordinate
                and definition.work_id == work_id
                and definition.definition_digest == definition_digest
            ):
                candidates.append(definition)
        if not candidates or any(item != candidates[0] for item in candidates[1:]):
            raise DirectWorkRunnerError("frozen WorkGraph lacks one exact WorkDefinition")
        return candidates[0]

    def _require_epoch_retained_commits_active(
        self,
        *,
        graph: GenerationWorkGraph,
        retained_commit_refs: tuple[ArtifactRef, ...],
    ) -> None:
        """Prove the frozen ancestor closure still is the active closure.

        A selected epoch may reuse its retained committed parents only when
        their exact commits remain active. Do not reactivate an old commit over
        a current repair, failure, or new semantic revision: that would turn a
        recovery command into an implicit history rewrite.
        """

        for commit_ref in retained_commit_refs:
            commit = self.artifacts.get_json(commit_ref, WorkCommit)
            definition = graph.require(commit.coordinate)
            if (
                commit.definition_digest != definition.definition_digest
                or commit.acceptance_digest != definition.acceptance_digest
            ):
                raise DirectWorkRunnerError(
                    "frozen retained WorkCommit does not match its graph",
                    safe_code="frozen_retained_commit_definition_mismatch",
                    safe_coordinate_keys=(commit.coordinate.coordinate_key,),
                )
            head = self.heads.read_head(definition.coordinate)
            if (
                head is None
                or head.status != "committed"
                or head.commit_ref != commit_ref
                or head.definition_digest != definition.definition_digest
                or head.acceptance_digest != definition.acceptance_digest
                or head.input_fingerprint != self.heads.input_fingerprint(commit.input_refs)
            ):
                raise DirectWorkRunnerError(
                    "frozen recovery requires an unchanged active ancestor commit: "
                    + commit.coordinate.coordinate_key,
                    safe_code="frozen_retained_commit_not_active",
                    safe_coordinate_keys=(commit.coordinate.coordinate_key,),
                )

    async def _run_semantic_prefix_under_trace(
        self,
        *,
        context_ref: ArtifactRef,
        context: GenerationContext,
        job: EnvironmentJob,
        request: EnvironmentRequest,
        run_id: str,
        trace_id: str,
        protected_coordinate_keys: frozenset[str] = frozenset(),
    ) -> _SemanticPrefixExecution:
        """Run the shared normal bootstrap/design prefix exactly once."""

        # Keep the same typed request load in this shared path even though the
        # semantic leaves consume it through ``context_ref`` rather than as a
        # mutable Python argument.
        _ = request
        workspace, runtime = self._new_runtime(
            context=context,
            job=job,
            run_id=run_id,
            trace_id=trace_id,
        )
        kernel = SchedulerLeafExecutor(runtime=runtime)
        epochs = WorkGraphEpochRuntime(artifacts=self.artifacts, heads=self.heads)

        bootstrap_definitions = self._bind_model_route_recovery_definitions(
            self._bootstrap_definitions(job)
        )
        bootstrap_graph = GenerationWorkGraph.compile(
            bootstrap_definitions,
            mode="diagnostic",
            strict_input_contracts=True,
        )
        bootstrap_manifest, bootstrap_manifest_ref, _epoch, bootstrap_epoch_ref = (
            epochs.freeze_bootstrap(
                context_ref=context_ref,
                graph=bootstrap_graph,
                topology_id=f"topology:direct-bootstrap:{context.context_id}",
            )
        )
        bootstrap_snapshot = await self._run_graph(
            graph=bootstrap_graph,
            manifest=bootstrap_manifest,
            manifest_ref=bootstrap_manifest_ref,
            runtime=runtime,
            executors=self._bootstrap_executors(
                context_ref=context_ref,
                workspace=workspace,
                kernel=kernel,
                definitions=bootstrap_definitions,
            ),
            protected_coordinate_keys=protected_coordinate_keys,
        )
        if not self._all_committed(bootstrap_snapshot):
            return _SemanticPrefixExecution(
                runtime=runtime,
                workspace=workspace,
                bootstrap_epoch_ref=bootstrap_epoch_ref,
                blocked_coordinates=self._blocked_coordinates(bootstrap_snapshot),
            )

        architecture_definition = self._one_definition(
            bootstrap_graph,
            component="design",
            stage="world_architecture",
        )
        architecture_ref = self._active_output(
            architecture_definition,
            artifact_type="design.world_architecture_source",
        )
        coupling_ref = self._active_output(
            architecture_definition,
            artifact_type="design.tool_coupling_plan",
        )
        coupling_plan = self.artifacts.get_json(coupling_ref, ToolCouplingPlan)
        world_definitions, modeling_template = derive_world_plan_definitions(
            scope_id=job.job_id,
            bootstrap_definitions=bootstrap_definitions,
            architecture_source_ref=architecture_ref,
            coupling_plan=coupling_plan,
            agent_wall_seconds=self._agent_wall(context.budget),
            agent_token_limit=self._agent_tokens(context.budget),
        )
        world_definitions = self._bind_model_route_recovery_definitions(world_definitions)
        world_graph = compile_world_work_graph(
            scope_id=job.job_id,
            world_definitions=world_definitions,
            strict_input_contracts=True,
        )
        (
            world_manifest,
            world_manifest_ref,
            _world_epoch,
            world_epoch_ref,
        ) = epochs.freeze_world(
            context_ref=context_ref,
            bootstrap_epoch_ref=bootstrap_epoch_ref,
            graph=world_graph,
            topology_id=f"topology:direct-world:{context.context_id}",
        )
        world_snapshot = await self._run_graph(
            graph=world_graph,
            manifest=world_manifest,
            manifest_ref=world_manifest_ref,
            runtime=runtime,
            executors=self._design_executors(
                context_ref=context_ref,
                workspace=workspace,
                kernel=kernel,
                graph=world_graph,
                verifier_plan=None,
            ),
            protected_coordinate_keys=protected_coordinate_keys,
        )
        if not self._all_committed(world_snapshot):
            return _SemanticPrefixExecution(
                runtime=runtime,
                workspace=workspace,
                bootstrap_epoch_ref=bootstrap_epoch_ref,
                world_epoch_ref=world_epoch_ref,
                blocked_coordinates=self._blocked_coordinates(world_snapshot),
            )

        curriculum_plan_definition = self._one_definition(
            world_graph,
            component="design",
            stage="curriculum_plan",
        )
        curriculum_plan_ref = self._active_output(
            curriculum_plan_definition,
            artifact_type="design.curriculum_plan_source",
        )
        curriculum_plan = self.artifacts.get_json(
            curriculum_plan_ref,
            CurriculumPlanSourceDraft,
        )
        final_design_definitions, modeling = derive_task_requirement_design_definitions(
            scope_id=job.job_id,
            world_definitions=world_definitions,
            curriculum_plan_ref=curriculum_plan_ref,
            curriculum_plan=curriculum_plan,
            modeling_template=modeling_template,
            agent_wall_seconds=self._agent_wall(context.budget),
            agent_token_limit=self._agent_tokens(context.budget),
        )
        final_design_definitions = self._bind_model_route_recovery_definitions(
            final_design_definitions
        )
        task_requirement_order = tuple(
            item.coordinate
            for item in final_design_definitions
            if (item.coordinate.component, item.coordinate.stage) == ("design", "task_requirement")
        )
        verifier_plan = verifier_plan_work_definition(
            scope_id=job.job_id,
            modeling_coordinate=modeling.coordinate,
        )
        design_graph = compile_design_work_graph(
            scope_id=job.job_id,
            design_definitions=final_design_definitions,
            modeling_definition=modeling,
            verifier_plan_definition=verifier_plan,
            strict_input_contracts=True,
        )
        (
            design_manifest,
            design_manifest_ref,
            _design_epoch,
            design_epoch_ref,
        ) = epochs.freeze_design_from_world(
            context_ref=context_ref,
            world_epoch_ref=world_epoch_ref,
            graph=design_graph,
            topology_id=f"topology:direct-design:{context.context_id}",
        )
        design_snapshot = await self._run_graph(
            graph=design_graph,
            manifest=design_manifest,
            manifest_ref=design_manifest_ref,
            runtime=runtime,
            executors=self._design_executors(
                context_ref=context_ref,
                workspace=workspace,
                kernel=kernel,
                graph=design_graph,
                verifier_plan=verifier_plan,
            ),
            stop_after_first_block=True,
            preferred_order=task_requirement_order,
            protected_coordinate_keys=protected_coordinate_keys,
        )
        return _SemanticPrefixExecution(
            runtime=runtime,
            workspace=workspace,
            bootstrap_epoch_ref=bootstrap_epoch_ref,
            world_epoch_ref=world_epoch_ref,
            design_epoch_ref=design_epoch_ref,
            design_graph=design_graph,
            modeling_definition=modeling,
            verifier_plan_definition=verifier_plan,
            ready=self._all_committed(design_snapshot),
            blocked_coordinates=self._blocked_coordinates(design_snapshot),
        )

    def _bootstrap_definitions(self, job: EnvironmentJob) -> tuple[WorkDefinition, ...]:
        agent_wall = self._agent_wall(job.budget)
        agent_tokens = self._agent_tokens(job.budget)
        plan = research_plan_work_definition(
            scope_id=job.job_id,
            agent_wall_seconds=agent_wall,
            agent_token_limit=agent_tokens,
        )
        search_calls = min(6, job.budget.search_calls)
        tool_calls = min(48, job.budget.tool_calls)
        if search_calls < 1 or tool_calls < search_calls + 2:
            raise DirectWorkRunnerError(
                "Direct generation budget cannot admit one real search/fetch/extract boundary"
            )
        acquisition = research_acquisition_work_definition(
            scope_id=job.job_id,
            dependency_coordinate=plan.coordinate,
            wall_seconds=min(600.0, max(1.0, job.budget.wall_seconds)),
            maximum_search_calls=search_calls,
            maximum_tool_calls=tool_calls,
        )
        synthesis = research_synthesis_work_definition(
            scope_id=job.job_id,
            dependency_coordinate=acquisition.coordinate,
            agent_wall_seconds=agent_wall,
            agent_token_limit=agent_tokens,
        )
        architecture = world_architecture_work_definition(
            scope_id=job.job_id,
            dependency_coordinate=synthesis.coordinate,
            agent_wall_seconds=agent_wall,
            agent_token_limit=agent_tokens,
        )
        return plan, acquisition, synthesis, architecture

    def _bind_model_route_recovery_definitions(
        self,
        definitions: tuple[WorkDefinition, ...],
        *,
        preserve_coordinate_keys: frozenset[str] = frozenset(),
    ) -> tuple[WorkDefinition, ...]:
        """Freeze route policy only into newly derived Agent definitions.

        A model-route retry/fallback policy is physical invocation control.  It
        is definition-bound for new leaves so its authority is durable, but a
        recovery must never retrofit it onto a committed frozen ancestor: doing
        so changes that ancestor's digest and turns a control-plane change into
        an unnecessary semantic replay.
        """

        fresh = tuple(
            definition
            for definition in definitions
            if definition.coordinate.coordinate_key not in preserve_coordinate_keys
        )
        rebound_by_coordinate = {
            definition.coordinate.coordinate_key: definition
            for definition in bind_model_route_recovery_policy(
                fresh,
                model_routes=self.model_routes,
                maximum_same_model_infrastructure_retries=(
                    self.maximum_same_model_infrastructure_retries
                ),
            )
        }
        return tuple(
            definition
            if definition.coordinate.coordinate_key in preserve_coordinate_keys
            else rebound_by_coordinate[definition.coordinate.coordinate_key]
            for definition in definitions
        )

    def _bind_model_route_recovery_graph(
        self,
        graph: GenerationWorkGraph,
        *,
        preserve_coordinate_keys: frozenset[str] = frozenset(),
    ) -> GenerationWorkGraph:
        """Recompile a graph after binding route policy to new descendants."""

        definitions = self._bind_model_route_recovery_definitions(
            graph.definitions,
            preserve_coordinate_keys=preserve_coordinate_keys,
        )
        if definitions == graph.definitions:
            return graph
        return GenerationWorkGraph.compile(
            definitions,
            mode=graph.mode,
            strict_input_contracts=True,
            required_terminal_coordinates=graph.required_terminal_coordinates,
            groups=graph.groups,
            milestones=graph.milestones,
        )

    def _bootstrap_executors(
        self,
        *,
        context_ref: ArtifactRef,
        workspace: Path,
        kernel: SchedulerLeafExecutor,
        definitions: tuple[WorkDefinition, ...],
    ) -> dict[str, object]:
        plan, acquisition, synthesis, architecture = definitions
        designer = self.designer
        leaves = (
            (
                plan,
                ResearchPlanLeaf(
                    context_ref=context_ref,
                    workspace_root=workspace,
                    backend=designer.backend,
                    profiles=designer.profiles,
                    kernel=kernel,
                ),
            ),
            (
                acquisition,
                ResearchAcquisitionLeaf(
                    context_ref=context_ref,
                    research=designer.research,
                    research_artifacts=designer.research_artifacts,
                    workspace_root=workspace,
                    kernel=kernel,
                ),
            ),
            (
                synthesis,
                EvidenceSynthesisLeaf(
                    context_ref=context_ref,
                    workspace_root=workspace,
                    backend=designer.backend,
                    profiles=designer.profiles,
                    kernel=kernel,
                ),
            ),
            (
                architecture,
                WorldArchitectureLeaf(
                    context_ref=context_ref,
                    workspace_root=workspace,
                    backend=designer.backend,
                    profiles=designer.profiles,
                    kernel=kernel,
                ),
            ),
        )
        return {
            definition.work_id: self._leaf_executor(leaf, definition) for definition, leaf in leaves
        }

    def _design_executors(
        self,
        *,
        context_ref: ArtifactRef,
        workspace: Path,
        kernel: SchedulerLeafExecutor,
        graph: GenerationWorkGraph,
        verifier_plan: WorkDefinition | None,
    ) -> dict[str, object]:
        designer = self.designer
        executors: dict[str, object] = {}
        for definition in graph.definitions:
            stage = definition.coordinate.stage
            leaf: object | None = None
            if stage == "shared_tool_semantics":
                leaf = SharedToolSemanticsLeaf(
                    context_ref=context_ref,
                    workspace_root=workspace,
                    backend=designer.backend,
                    profiles=designer.profiles,
                    kernel=kernel,
                )
            elif definition.coordinate.artifact_slot == "tool_semantics_batch":
                leaf = ToolSemanticsBatchLeaf(
                    context_ref=context_ref,
                    workspace_root=workspace,
                    backend=designer.backend,
                    profiles=designer.profiles,
                    kernel=kernel,
                )
            elif stage == "world_rules":
                leaf = WorldRulesLeaf(
                    context_ref=context_ref,
                    workspace_root=workspace,
                    backend=designer.backend,
                    profiles=designer.profiles,
                    kernel=kernel,
                )
            elif stage == "curriculum_plan":
                leaf = CurriculumPlanLeaf(
                    context_ref=context_ref,
                    workspace_root=workspace,
                    backend=designer.backend,
                    profiles=designer.profiles,
                    kernel=kernel,
                )
            elif stage == "task_requirement":
                leaf = TaskRequirementLeaf(
                    context_ref=context_ref,
                    workspace_root=workspace,
                    backend=designer.backend,
                    profiles=designer.profiles,
                    kernel=kernel,
                )
            elif stage == "task_curriculum":
                leaf = TaskCurriculumJoinLeaf(context_ref=context_ref, kernel=kernel)
            elif stage == "modeling_boundary":
                leaf = ModelingBoundaryLeaf(context_ref=context_ref, kernel=kernel)
            elif verifier_plan is not None and definition.coordinate == verifier_plan.coordinate:
                leaf = VerifierPlanLeaf(compiler=self.verifier_compiler, kernel=kernel)
            if leaf is not None:
                executors[definition.work_id] = self._leaf_executor(leaf, definition)
        return executors

    def _final_executors(
        self,
        *,
        context_ref: ArtifactRef,
        context: GenerationContext,
        workspace: Path,
        run_id: str,
        trace_id: str,
        kernel: SchedulerLeafExecutor,
        graph: GenerationWorkGraph,
        final_epoch_ref: ArtifactRef,
        final_manifest_ref: ArtifactRef,
    ) -> dict[str, object]:
        release_judge = EnvironmentJudge(
            artifact_store=self.judge.artifacts,
            clean_builder=self.judge.clean_builder,
            runtime_execution=self.judge.runtime_execution,
            telemetry=self.judge.telemetry,
            known_secret_canaries=self.judge.known_secret_canaries,
            runtime_episode_concurrency=self.judge.runtime_episode_concurrency,
        )
        dossier_compiler = ReleaseDossierCompiler(artifacts=self.artifacts, heads=self.heads)
        executors: dict[str, object] = {}
        for definition in graph.definitions:
            stage = definition.coordinate.stage
            leaf: object | None = None
            if stage == "implementation_plan":
                leaf = BuildPlanningLeaf(
                    builder=self.builder,
                    workspace_root=workspace / "builder-plan",
                    kernel=kernel,
                )
            elif stage == "candidate_build":
                leaf = BuilderLeaf(
                    builder=self.builder,
                    workspace_root=workspace / "builder",
                    run_id=run_id,
                    kernel=kernel,
                )
            elif stage == "verifier_intent_batch":
                leaf = VerifierBatchLeaf(
                    compiler=self.verifier_compiler,
                    workspace_root=workspace / "verifier",
                    kernel=kernel,
                )
            elif stage == "verifier_intent":
                leaf = VerifierAggregateLeaf(compiler=self.verifier_compiler, kernel=kernel)
            elif stage == "runtime_integration":
                leaf = IntegrationLeaf(
                    builder=self.builder,
                    judge=self.judge,
                    release_profile=context.release_profile,
                    workspace_root=workspace / "integration",
                    run_id=run_id,
                    kernel=kernel,
                )
            elif stage == "release_assurance":
                leaf = ReleaseAssuranceLeaf(
                    builder=self.builder,
                    judge=release_judge,
                    release_profile=context.release_profile,
                    workspace_root=workspace / "release-assurance",
                    run_id=run_id,
                    kernel=kernel,
                )
            elif stage == "observability_closure":
                leaf = ObservabilityLeaf(
                    heads=self.heads,
                    graph=graph,
                    telemetry=self.telemetry,
                    trace_id=trace_id,
                    kernel=kernel,
                )
            elif stage == "package":
                leaf = PackageLeaf(
                    builder=self.builder,
                    graph=graph,
                    final_epoch_ref=final_epoch_ref,
                    final_manifest_ref=final_manifest_ref,
                    release_profile=context.release_profile,
                    workspace_root=workspace / "package",
                    dossier_compiler=dossier_compiler,
                    kernel=kernel,
                )
            elif stage == "publication":
                leaf = RegistryPublicationLeaf(
                    builder=self.builder,
                    registry=self.registry,
                    workspace_root=workspace / "registry",
                    kernel=kernel,
                )
            if leaf is not None:
                executors[definition.work_id] = self._leaf_executor(leaf, definition)
        return executors

    async def _run_graph(
        self,
        *,
        graph: GenerationWorkGraph,
        manifest: object,
        manifest_ref: ArtifactRef,
        runtime: WorkControlRuntime,
        executors: dict[str, object],
        stop_after_first_block: bool = False,
        preferred_order: tuple[WorkCoordinate, ...] = (),
        protected_coordinate_keys: frozenset[str] = frozenset(),
        frozen_recovery_protection: _FrozenRecoveryProtection | None = None,
    ) -> WorkScheduleSnapshot:
        scheduler = WorkScheduler(
            graph=graph,
            manifest=manifest,  # type: ignore[arg-type]
            manifest_ref=manifest_ref,
            heads=self.heads,
            artifacts=self.artifacts,
            runtime=runtime,
        )
        # The DirectJob writer lock proves that a new runner is not concurrent
        # with an owner of this graph.  Reconcile any prior process that died
        # after its dispatch fence before considering a new ready wave; never
        # allow an active lease to turn a recovery into a misleading budget
        # exhaustion.
        self._reconcile_abandoned_operations(
            graph=graph,
            runtime=runtime,
            scheduler=scheduler,
        )
        self._require_current_recovery_protection(
            scheduler=scheduler,
            graph=graph,
            protected_coordinate_keys=protected_coordinate_keys,
            frozen_recovery_protection=frozen_recovery_protection,
        )
        if stop_after_first_block or protected_coordinate_keys:
            preferred_keys = {
                coordinate.coordinate_key: index for index, coordinate in enumerate(preferred_order)
            }
            while True:
                snapshot = scheduler.snapshot()
                self._require_current_recovery_protection(
                    scheduler=scheduler,
                    graph=graph,
                    protected_coordinate_keys=protected_coordinate_keys,
                    frozen_recovery_protection=frozen_recovery_protection,
                )
                missing = tuple(
                    item.coordinate
                    for item in snapshot.work
                    if item.state in {"ready", "repair_ready"}
                    and graph.require(item.coordinate).work_id not in executors
                )
                if missing:
                    rendered = ", ".join(item.coordinate_key for item in missing)
                    raise DirectWorkRunnerError(
                        f"sequential graph has no executor for required work: {rendered}"
                    )
                ready: list[WorkCoordinate] = []
                for item in snapshot.work:
                    if (
                        item.state not in {"ready", "repair_ready", "stale"}
                        or graph.require(item.coordinate).work_id not in executors
                    ):
                        continue
                    if item.state == "stale":
                        try:
                            scheduler.resolve_inputs(item.coordinate)
                        except WorkResumeError:
                            continue
                    ready.append(item.coordinate)
                if not ready:
                    return snapshot
                ready.sort(
                    key=lambda coordinate: (
                        preferred_keys.get(coordinate.coordinate_key, len(preferred_keys)),
                        coordinate.coordinate_key,
                    )
                )
                await scheduler.dispatch_one(
                    ready[0],
                    executors=executors,  # type: ignore[arg-type]
                )
                terminal_snapshot = scheduler.snapshot()
                self._require_current_recovery_protection(
                    scheduler=scheduler,
                    graph=graph,
                    protected_coordinate_keys=protected_coordinate_keys,
                    frozen_recovery_protection=frozen_recovery_protection,
                )
                # A selected frozen target can fail while the Scheduler
                # simultaneously authorizes an exact repair on one protected
                # causal parent.  That failed source remains durable evidence;
                # it must not make the sequential recovery return before the
                # target repair and its stale descendants can run.  The normal
                # no-ready check above still returns a genuinely blocked graph.
                if stop_after_first_block and any(
                    item.state == "blocked" for item in terminal_snapshot.work
                ):
                    return terminal_snapshot
        await scheduler.run_until_stalled(
            executors=executors,  # type: ignore[arg-type]
            maximum_concurrency=self.maximum_concurrency,
        )
        return scheduler.snapshot()

    def _require_current_recovery_protection(
        self,
        *,
        scheduler: WorkScheduler,
        graph: GenerationWorkGraph,
        protected_coordinate_keys: frozenset[str],
        frozen_recovery_protection: _FrozenRecoveryProtection | None,
    ) -> None:
        """Apply the correct protection rule for ordinary and frozen graph runs."""

        if frozen_recovery_protection is None:
            self._require_protected_ancestors_committed(
                scheduler=scheduler,
                protected_coordinate_keys=protected_coordinate_keys,
            )
            return
        if frozen_recovery_protection.protected_coordinate_keys != protected_coordinate_keys:
            raise DirectWorkRunnerError(
                "frozen recovery protection does not bind this graph prefix",
                safe_code="frozen_recovery_protection_mismatch",
            )
        self._require_frozen_recovery_protection(
            scheduler=scheduler,
            graph=graph,
            protection=frozen_recovery_protection,
        )

    @staticmethod
    def _reconcile_abandoned_operations(
        *,
        graph: GenerationWorkGraph,
        runtime: WorkControlRuntime,
        scheduler: WorkScheduler,
    ) -> None:
        for definition in graph.topological_definitions():
            with runtime.heads.exclusive(definition.coordinate) as lock:
                head = runtime.heads.read_head(definition.coordinate)
                if head is None or head.status != "running":
                    continue
                if head.active_operation_ref is None:
                    # A never-commenced orphan: the prior process died between the
                    # Scheduler's durable ``begin`` and the leaf's first
                    # ``start_operation``.  No OperationRun exists to settle, so the
                    # ordinary reconcile path skips it and the Scheduler would pin it
                    # ``running`` forever.  Reset it to a fresh running attempt only
                    # when the current graph definition matches the frozen head:
                    # it is then the SAME definition/inputs and consumed zero work,
                    # so re-opening one attempt cannot double-spend.  A head whose
                    # frozen definition differs from the current graph is a
                    # changed-definition case (supersede authority), not a
                    # never-commenced same-definition reset, and is left untouched.
                    if (
                        head.work_id == definition.work_id
                        and head.definition_digest == definition.definition_digest
                    ):
                        resolved = scheduler.resolve_inputs(definition.coordinate)
                        runtime.resume_uncommenced_running(
                            lock,
                            definition=definition,
                            input_refs=resolved.all_input_refs,
                        )
                    continue
                recovery_definition = (
                    definition
                    if (
                        head.work_id == definition.work_id
                        and head.definition_digest == definition.definition_digest
                    )
                    else runtime.heads.require_running_definition(
                        head=head,
                        artifacts=runtime.artifacts,
                    )
                )
                runtime.reconcile_abandoned_operation(lock, definition=recovery_definition)

    @staticmethod
    def _leaf_executor(leaf: object, definition: WorkDefinition):
        async def execute(context: WorkExecutionContext) -> None:
            await leaf.execute(context, definition=definition)  # type: ignore[attr-defined]

        return execute

    def _load_context(
        self,
        context_ref: ArtifactRef,
    ) -> tuple[GenerationContext, EnvironmentJob, EnvironmentRequest]:
        if context_ref.artifact_type != "control.generation_context":
            raise DirectWorkRunnerError("Direct scheduler requires a GenerationContext Artifact")
        context = self.artifacts.get_json(context_ref, GenerationContext)
        if context.kind != "generate" or context.request_ref is None:
            raise DirectWorkRunnerError("Direct scheduler currently accepts only generate contexts")
        job = self.artifacts.get_json(context.job_ref, EnvironmentJob)
        request = self.artifacts.get_json(context.request_ref, EnvironmentRequest)
        if (
            job.kind != "generate"
            or job.request_ref != context.request_ref
            or job.permissions != context.permissions
            or request.permissions != context.permissions
        ):
            raise DirectWorkRunnerError("GenerationContext has an inconsistent Direct root closure")
        return context, job, request

    def _validate_execution_configuration(self) -> None:
        if self.maximum_concurrency < 1:
            raise DirectWorkRunnerError("maximum_concurrency must be positive")
        if self.structured_turn_token_limit < 1 or self.structured_turn_wall_seconds <= 0:
            raise DirectWorkRunnerError("Direct scheduler requires positive structured-turn limits")
        if (
            self.environment_codegen_session_token_limit < 1
            or self.environment_codegen_session_wall_seconds <= 0
            or self.environment_codegen_physical_turn_token_limit < 1
        ):
            raise DirectWorkRunnerError(
                "Direct scheduler requires positive Environment Builder session/turn limits"
            )

    def _semantic_prefix_outcome(
        self,
        *,
        prefix: _SemanticPrefixExecution,
        context_ref: ArtifactRef,
        scope_id: str,
        run_id: str,
    ) -> SemanticPrefixRun:
        usage = self._scope_budget_usage(runtime=prefix.runtime, scope_id=scope_id)
        if not prefix.ready:
            return self._persist_semantic_prefix_outcome(
                run_id=run_id,
                scope_id=scope_id,
                context_ref=context_ref,
                status="blocked",
                bootstrap_epoch_ref=prefix.bootstrap_epoch_ref,
                world_epoch_ref=prefix.world_epoch_ref,
                design_epoch_ref=prefix.design_epoch_ref,
                observed_actual=usage["observed_actual"],
                unknown_upper_bound=usage["unknown_upper_bound"],
                blocked_coordinates=prefix.blocked_coordinates,
            )
        if (
            prefix.design_epoch_ref is None
            or prefix.design_graph is None
            or prefix.modeling_definition is None
            or prefix.verifier_plan_definition is None
        ):
            raise DirectWorkRunnerError(
                "ready semantic prefix lacks its exact active commit definitions"
            )
        modeling_commit_ref = self._active_commit_ref(prefix.modeling_definition)
        verifier_plan_commit_ref = self._active_commit_ref(prefix.verifier_plan_definition)
        environment_design_ref = self._active_output(
            prefix.modeling_definition,
            artifact_type="design.environment_design",
        )
        verifier_batch_plan_ref = self._active_output(
            prefix.verifier_plan_definition,
            artifact_type="judge.verifier_batch_plan",
        )
        return self._persist_semantic_prefix_outcome(
            run_id=run_id,
            scope_id=scope_id,
            context_ref=context_ref,
            status="semantic_prefix_ready",
            bootstrap_epoch_ref=prefix.bootstrap_epoch_ref,
            world_epoch_ref=prefix.world_epoch_ref,
            design_epoch_ref=prefix.design_epoch_ref,
            modeling_commit_ref=modeling_commit_ref,
            verifier_plan_commit_ref=verifier_plan_commit_ref,
            environment_design_ref=environment_design_ref,
            verifier_batch_plan_ref=verifier_batch_plan_ref,
            observed_actual=usage["observed_actual"],
            unknown_upper_bound=usage["unknown_upper_bound"],
        )

    def _active_commit_ref(self, definition: WorkDefinition) -> ArtifactRef:
        """Require one normal active commit; diagnostic adoption is forbidden."""

        head = self.heads.read_head(definition.coordinate)
        if head is None or head.status != "committed":
            raise WorkResumeError("required scheduler Work has no committed head")
        attempt = self.artifacts.get_json(head.attempt_ref, WorkAttempt)
        active = self.heads.require_active_commit(
            definition=definition,
            input_refs=attempt.input_refs,
            artifacts=self.artifacts,
        )
        if active is None:
            raise WorkResumeError("required scheduler WorkCommit is not normally active")
        _commit, commit_ref = active
        return commit_ref

    def _active_output(self, definition: WorkDefinition, *, artifact_type: str) -> ArtifactRef:
        head = self.heads.read_head(definition.coordinate)
        if head is None or head.status != "committed" or head.commit_ref is None:
            raise WorkResumeError("required scheduler Work has no active commit")
        commit = self.artifacts.get_json(head.commit_ref, WorkCommit)
        matches = tuple(ref for ref in commit.consumer_refs if ref.artifact_type == artifact_type)
        if len(matches) != 1:
            raise WorkResumeError("required scheduler Work does not expose one typed output")
        return matches[0]

    @staticmethod
    def _one_definition(
        graph: GenerationWorkGraph,
        *,
        component: str,
        stage: str,
    ) -> WorkDefinition:
        matches = tuple(
            item
            for item in graph.definitions
            if item.coordinate.component == component and item.coordinate.stage == stage
        )
        if len(matches) != 1:
            raise DirectWorkRunnerError("frozen graph lacks one required unique WorkDefinition")
        return matches[0]

    @staticmethod
    def _all_committed(snapshot: WorkScheduleSnapshot) -> bool:
        return all(item.state == "committed" for item in snapshot.work)

    @staticmethod
    def _blocked_coordinates(snapshot: WorkScheduleSnapshot) -> tuple[str, ...]:
        blocked = tuple(item for item in snapshot.work if item.state == "blocked")
        return tuple(
            ".".join(
                part
                for part in (
                    item.coordinate.component,
                    item.coordinate.stage,
                    item.coordinate.artifact_slot,
                    item.coordinate.group_id,
                    item.coordinate.shard_id,
                )
                if part is not None
            )
            for item in blocked
        )

    @staticmethod
    def _scope_budget_usage(
        *,
        runtime: WorkControlRuntime,
        scope_id: str,
    ) -> dict[str, BudgetUsage]:
        """Project durable Scheduler leases into the DirectJob budget snapshot."""

        try:
            snapshot = runtime.budget_coordinator.snapshot(scope_id=scope_id)
        except ValueError:
            return {
                "observed_actual": BudgetUsage(),
                "unknown_upper_bound": BudgetUsage(),
            }
        actual = BudgetUsage()
        unknown = BudgetUsage()
        fields = tuple(
            field_name for field_name in BudgetUsage.model_fields if field_name != "schema_version"
        )
        for lease in snapshot.leases:
            if lease.status != "settled":
                continue
            actual = BudgetUsage.model_validate(
                {
                    field_name: getattr(actual, field_name)
                    + getattr(lease.observed_actual, field_name)
                    for field_name in fields
                }
            )
            unknown = BudgetUsage.model_validate(
                {
                    field_name: getattr(unknown, field_name)
                    + getattr(lease.unknown_upper_bound, field_name)
                    for field_name in fields
                }
            )
        return {"observed_actual": actual, "unknown_upper_bound": unknown}

    def _persist_semantic_prefix_outcome(
        self,
        *,
        run_id: str,
        scope_id: str,
        context_ref: ArtifactRef,
        status: Literal["semantic_prefix_ready", "blocked"],
        bootstrap_epoch_ref: ArtifactRef,
        observed_actual: BudgetUsage,
        unknown_upper_bound: BudgetUsage,
        world_epoch_ref: ArtifactRef | None = None,
        design_epoch_ref: ArtifactRef | None = None,
        modeling_commit_ref: ArtifactRef | None = None,
        verifier_plan_commit_ref: ArtifactRef | None = None,
        environment_design_ref: ArtifactRef | None = None,
        verifier_batch_plan_ref: ArtifactRef | None = None,
        blocked_coordinates: tuple[str, ...] = (),
    ) -> SemanticPrefixRun:
        result = SemanticPrefixRun(
            run_id=run_id,
            scope_id=scope_id,
            context_ref=context_ref,
            status=status,
            bootstrap_epoch_ref=bootstrap_epoch_ref,
            world_epoch_ref=world_epoch_ref,
            design_epoch_ref=design_epoch_ref,
            modeling_commit_ref=modeling_commit_ref,
            verifier_plan_commit_ref=verifier_plan_commit_ref,
            environment_design_ref=environment_design_ref,
            verifier_batch_plan_ref=verifier_batch_plan_ref,
            observed_actual=observed_actual,
            unknown_upper_bound=unknown_upper_bound,
            blocked_coordinates=blocked_coordinates,
        )
        self.artifacts.put_json(
            artifact_id=f"semantic-prefix-run:{run_id}",
            artifact_type="control.semantic_prefix_run",
            value=result,
            dependencies=tuple(
                ref
                for ref in (
                    context_ref,
                    bootstrap_epoch_ref,
                    world_epoch_ref,
                    design_epoch_ref,
                    modeling_commit_ref,
                    verifier_plan_commit_ref,
                    environment_design_ref,
                    verifier_batch_plan_ref,
                )
                if ref is not None
            ),
        )
        return result

    def _persist_outcome(
        self,
        *,
        run_id: str,
        context_ref: ArtifactRef,
        status: Literal["released", "blocked"],
        bootstrap_epoch_ref: ArtifactRef,
        observed_actual: BudgetUsage,
        unknown_upper_bound: BudgetUsage,
        world_epoch_ref: ArtifactRef | None = None,
        design_epoch_ref: ArtifactRef | None = None,
        final_epoch_ref: ArtifactRef | None = None,
        package_manifest_ref: ArtifactRef | None = None,
        release_ref: ArtifactRef | None = None,
        blocked_coordinates: tuple[str, ...] = (),
    ) -> DirectWorkRun:
        result = DirectWorkRun(
            run_id=run_id,
            context_ref=context_ref,
            status=status,
            bootstrap_epoch_ref=bootstrap_epoch_ref,
            observed_actual=observed_actual,
            unknown_upper_bound=unknown_upper_bound,
            world_epoch_ref=world_epoch_ref,
            design_epoch_ref=design_epoch_ref,
            final_epoch_ref=final_epoch_ref,
            package_manifest_ref=package_manifest_ref,
            release_ref=release_ref,
            blocked_coordinates=blocked_coordinates,
        )
        self.artifacts.put_json(
            artifact_id=f"direct-work-run:{run_id}",
            artifact_type="control.direct_work_run",
            value=result,
            dependencies=tuple(
                ref
                for ref in (
                    context_ref,
                    bootstrap_epoch_ref,
                    world_epoch_ref,
                    design_epoch_ref,
                    final_epoch_ref,
                    package_manifest_ref,
                    release_ref,
                )
                if ref is not None
            ),
        )
        return result

    def _agent_wall(self, budget: Budget) -> float:
        return min(self.structured_turn_wall_seconds, max(1.0, budget.wall_seconds))

    def _agent_tokens(self, budget: Budget) -> int:
        return min(self.structured_turn_token_limit, max(1, budget.llm_tokens))

    def _verifier_group_tokens(self, budget: Budget, *, batch_count: int) -> int:
        """Size the whole verifier-intent group so each batch keeps a full turn.

        ``_verifier_intent_group`` splits the group token limit evenly across its
        batches (``token_limit // batch_count``), and each batch is one real
        Challenger turn. The canonical control-plane sizes a structured verifier
        turn at ``structured_turn_token_limit`` (the same per-turn cap the legacy
        controller reserves via ``verifier_turn_cap``). A high ``reasoning_challenger``
        turn genuinely spends ~49-56k tokens, so a batch must receive that full
        per-turn envelope rather than the frozen 48k graph default, which is
        below the reasoning floor and turns every clean judge turn into a fatal
        ``budget_exhausted(llm_tokens)`` settle overshoot. Multiply the per-turn
        cap by the batch count so the even split restores a full turn per batch,
        clamped to the remaining scope tokens.
        """

        per_turn = self._agent_tokens(budget)
        return min(max(1, per_turn * max(1, batch_count)), max(1, budget.llm_tokens))

    def _verifier_group_wall(self, budget: Budget, *, batch_count: int) -> float:
        """Size the whole verifier-intent group so each batch keeps a full turn wall.

        ``_verifier_intent_group`` splits the group wall evenly across its batches
        (``wall_seconds / batch_count``), and each batch is one real Challenger
        turn. The canonical control-plane grants the verifier group the full
        remaining scope wall and sizes a structured turn at
        ``structured_turn_wall_seconds`` (the transport timeout envelope). The
        frozen 900s graph default splits to 450s per batch, which a genuine
        high-``reasoning_challenger`` turn (observed ~456s of continuous provider
        progress, well inside the idle-timeout liveness window) overruns — turning
        a clean judge turn into a fatal ``budget_exhausted(wall_seconds)`` settle
        overshoot on the first attempt. This is the wall analogue of the
        undersized token lease and is disjoint from the transport-liveness clamp:
        the clamp only rescues a *false* overshoot where a stalled turn's
        last-progress→terminal gap equals the idle timeout, whereas this is real
        work that needs a real lease. Multiply the per-turn wall by the batch
        count so the even split restores a full turn per batch, clamped to the
        remaining scope wall.
        """

        per_turn = self._agent_wall(budget)
        return min(max(1.0, per_turn * max(1, batch_count)), max(1.0, budget.wall_seconds))

    def _codegen_session_tokens(self, budget: Budget) -> int:
        return min(self.environment_codegen_session_token_limit, max(1, budget.llm_tokens))

    def _codegen_session_wall(self, budget: Budget) -> float:
        return min(
            self.environment_codegen_session_wall_seconds,
            max(1.0, budget.build_seconds),
            max(1.0, budget.wall_seconds),
        )

    def _codegen_physical_turn_tokens(self, budget: Budget) -> int:
        return min(
            self.environment_codegen_physical_turn_token_limit,
            self._codegen_session_tokens(budget),
        )


__all__ = [
    "DirectWorkRun",
    "DirectWorkRunner",
    "DirectWorkRunnerError",
    "SemanticPrefixRun",
]
