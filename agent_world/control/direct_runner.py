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
from .release_dossier import ReleaseDossierCompiler
from .release_leaf import ObservabilityLeaf, PackageLeaf, RegistryPublicationLeaf
from .telemetry import TelemetryStore
from .work import WorkAttempt, WorkCommit, WorkCoordinate, WorkDefinition
from .work_epoch import WorkGraphEpochRuntime
from .work_graph import (
    GenerationWorkGraph,
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
    maximum_concurrency: int = 4
    projector: SceneProjector | None = None

    async def run(
        self,
        *,
        context_ref: ArtifactRef,
        run_id: str | None = None,
        recovering: bool = False,
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
    ) -> DirectWorkRun:
        prefix = await self._run_semantic_prefix_under_trace(
            context_ref=context_ref,
            context=context,
            job=job,
            request=request,
            run_id=run_id,
            trace_id=trace_id,
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

        if (
            prefix.design_graph is None
            or prefix.design_epoch_ref is None
            or prefix.verifier_plan_definition is None
        ):
            raise DirectWorkRunnerError(
                "ready semantic prefix lacks its exact Design graph closure"
            )
        design_graph = prefix.design_graph
        bootstrap_epoch_ref = prefix.bootstrap_epoch_ref
        world_epoch_ref = prefix.world_epoch_ref
        design_epoch_ref = prefix.design_epoch_ref
        verifier_plan = prefix.verifier_plan_definition
        workspace = prefix.workspace
        epochs = WorkGraphEpochRuntime(artifacts=self.artifacts, heads=self.heads)
        kernel = SchedulerLeafExecutor(runtime=runtime)
        plan_ref = self._active_output(verifier_plan, artifact_type="judge.verifier_batch_plan")
        plan = self.artifacts.get_json(plan_ref, VerifierBatchPlan)
        final_graph = complete_generation_work_graph(
            scope_id=job.job_id,
            design_graph=design_graph,
            implementation_plan_token_limit=self._codegen_physical_turn_tokens(context.budget),
            implementation_plan_wall_seconds=self._codegen_session_wall(context.budget),
            implementation_plan_session_token_limit=self._codegen_session_tokens(context.budget),
            implementation_plan_session_wall_seconds=self._codegen_session_wall(context.budget),
            builder_token_limit=self._codegen_physical_turn_tokens(context.budget),
            builder_wall_seconds=self._codegen_session_wall(context.budget),
            builder_session_token_limit=self._codegen_session_tokens(context.budget),
            builder_session_wall_seconds=self._codegen_session_wall(context.budget),
            verifier_batch_count=len(plan.batches),
            strict_input_contracts=True,
        )
        final_manifest, final_manifest_ref, _final_epoch, final_epoch_ref = epochs.freeze_final(
            context_ref=context_ref,
            design_epoch_ref=design_epoch_ref,
            graph=final_graph,
            topology_id=f"topology:direct-final:{context.context_id}",
        )
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
        )
        if not self._all_committed(final_snapshot):
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
                blocked_coordinates=self._blocked_coordinates(final_snapshot),
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

    async def _run_semantic_prefix_under_trace(
        self,
        *,
        context_ref: ArtifactRef,
        context: GenerationContext,
        job: EnvironmentJob,
        request: EnvironmentRequest,
        run_id: str,
        trace_id: str,
    ) -> _SemanticPrefixExecution:
        """Run the shared normal bootstrap/design prefix exactly once."""

        # Keep the same typed request load in this shared path even though the
        # semantic leaves consume it through ``context_ref`` rather than as a
        # mutable Python argument.
        _ = request
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
        kernel = SchedulerLeafExecutor(runtime=runtime)
        epochs = WorkGraphEpochRuntime(artifacts=self.artifacts, heads=self.heads)

        bootstrap_definitions = self._bootstrap_definitions(job)
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
            runtime_isolation=self.judge.runtime_isolation,
            telemetry=self.judge.telemetry,
            known_secret_canaries=self.judge.known_secret_canaries,
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
        self._reconcile_abandoned_operations(graph=graph, runtime=runtime)
        if stop_after_first_block:
            preferred_keys = {
                coordinate.coordinate_key: index for index, coordinate in enumerate(preferred_order)
            }
            for _dispatch_count in range(128):
                snapshot = scheduler.snapshot()
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
                if any(item.state == "blocked" for item in terminal_snapshot.work):
                    return terminal_snapshot
            raise DirectWorkRunnerError("sequential graph exceeded its bounded dispatch budget")
        await scheduler.run_until_stalled(
            executors=executors,  # type: ignore[arg-type]
            maximum_concurrency=self.maximum_concurrency,
        )
        return scheduler.snapshot()

    @staticmethod
    def _reconcile_abandoned_operations(
        *,
        graph: GenerationWorkGraph,
        runtime: WorkControlRuntime,
    ) -> None:
        for definition in graph.topological_definitions():
            with runtime.heads.exclusive(definition.coordinate) as lock:
                head = runtime.heads.read_head(definition.coordinate)
                if head is None or head.status != "running" or head.active_operation_ref is None:
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
