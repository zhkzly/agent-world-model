"""One real Direct-generation vertical slice driven only by the WorkGraph.

This is the production replacement for the former Controller component loops.
It does not call ``EnvironmentDesigner.generate`` or any legacy repair
orchestrator.  Each model, research-tool, runtime, and release action is a
Scheduler leaf with one durable WorkAttempt, while this runner owns only the
three topology freezes required to turn discovered cardinality into physical
work.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from agent_world.artifact_store import ArtifactWriter
from agent_world.builder import BuilderLeaf, EnvironmentBuilder
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
    ModelingBoundaryLeaf,
    SharedToolSemanticsLeaf,
    TaskCurriculumLeaf,
    ToolSemanticsBatchLeaf,
    WorldRulesLeaf,
)
from agent_world.designer.models import ToolCouplingPlan
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
from .leaf_executor import SchedulerLeafExecutor
from .release_dossier import ReleaseDossierCompiler
from .release_leaf import ObservabilityLeaf, PackageLeaf, RegistryPublicationLeaf
from .telemetry import TelemetryStore
from .work import WorkCommit, WorkDefinition
from .work_epoch import WorkGraphEpochRuntime
from .work_graph import (
    GenerationWorkGraph,
    compile_design_work_graph,
    complete_generation_work_graph,
    derive_final_design_definitions,
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
    final_epoch_ref: ArtifactRef | None = None
    package_manifest_ref: ArtifactRef | None = None
    release_ref: ArtifactRef | None = None
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
        if self.maximum_concurrency < 1:
            raise DirectWorkRunnerError("maximum_concurrency must be positive")
        if self.structured_turn_token_limit < 1 or self.structured_turn_wall_seconds <= 0:
            raise DirectWorkRunnerError("Direct scheduler requires positive structured-turn limits")

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
            attributes={"topology": "three-epoch-direct-v1"},
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
        runtime = WorkControlRuntime(
            artifacts=self.artifacts,
            heads=self.heads,
            budget=LeaseBudgetLedger(context.budget),
            repair_scope_id=job.job_id,
            telemetry=self.telemetry,
            projector=self.projector,
            trace_id=trace_id,
            run_id=run_id,
        )
        kernel = SchedulerLeafExecutor(runtime=runtime)
        epochs = WorkGraphEpochRuntime(artifacts=self.artifacts, heads=self.heads)
        workspace = self.workspace_root / context.context_id
        workspace.mkdir(parents=True, exist_ok=True)

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
            usage = self._scope_budget_usage(runtime=runtime, scope_id=job.job_id)
            return self._persist_outcome(
                run_id=run_id,
                context_ref=context_ref,
                status="blocked",
                bootstrap_epoch_ref=bootstrap_epoch_ref,
                observed_actual=usage["observed_actual"],
                unknown_upper_bound=usage["unknown_upper_bound"],
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
        final_design_definitions, modeling = derive_final_design_definitions(
            scope_id=job.job_id,
            bootstrap_definitions=bootstrap_definitions,
            architecture_source_ref=architecture_ref,
            coupling_plan=coupling_plan,
            agent_wall_seconds=self._agent_wall(context.budget),
            agent_token_limit=self._agent_tokens(context.budget),
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
        ) = epochs.freeze_design(
            context_ref=context_ref,
            bootstrap_epoch_ref=bootstrap_epoch_ref,
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
        )
        if not self._all_committed(design_snapshot):
            usage = self._scope_budget_usage(runtime=runtime, scope_id=job.job_id)
            return self._persist_outcome(
                run_id=run_id,
                context_ref=context_ref,
                status="blocked",
                bootstrap_epoch_ref=bootstrap_epoch_ref,
                design_epoch_ref=design_epoch_ref,
                observed_actual=usage["observed_actual"],
                unknown_upper_bound=usage["unknown_upper_bound"],
                blocked_coordinates=self._blocked_coordinates(design_snapshot),
            )

        plan_ref = self._active_output(verifier_plan, artifact_type="judge.verifier_batch_plan")
        plan = self.artifacts.get_json(plan_ref, VerifierBatchPlan)
        final_graph = complete_generation_work_graph(
            scope_id=job.job_id,
            design_graph=design_graph,
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
            design_epoch_ref=design_epoch_ref,
            final_epoch_ref=final_epoch_ref,
            package_manifest_ref=package_manifest_ref,
            release_ref=release_ref,
            observed_actual=usage["observed_actual"],
            unknown_upper_bound=usage["unknown_upper_bound"],
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
            (plan, ResearchPlanLeaf(
                context_ref=context_ref,
                workspace_root=workspace,
                backend=designer.backend,
                profiles=designer.profiles,
                kernel=kernel,
            )),
            (acquisition, ResearchAcquisitionLeaf(
                context_ref=context_ref,
                research=designer.research,
                research_artifacts=designer.research_artifacts,
                workspace_root=workspace,
                kernel=kernel,
            )),
            (synthesis, EvidenceSynthesisLeaf(
                context_ref=context_ref,
                workspace_root=workspace,
                backend=designer.backend,
                profiles=designer.profiles,
                kernel=kernel,
            )),
            (architecture, WorldArchitectureLeaf(
                context_ref=context_ref,
                workspace_root=workspace,
                backend=designer.backend,
                profiles=designer.profiles,
                kernel=kernel,
            )),
        )
        return {
            definition.work_id: self._leaf_executor(leaf, definition)
            for definition, leaf in leaves
        }

    def _design_executors(
        self,
        *,
        context_ref: ArtifactRef,
        workspace: Path,
        kernel: SchedulerLeafExecutor,
        graph: GenerationWorkGraph,
        verifier_plan: WorkDefinition,
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
            elif stage == "task_curriculum":
                leaf = TaskCurriculumLeaf(
                    context_ref=context_ref,
                    workspace_root=workspace,
                    backend=designer.backend,
                    profiles=designer.profiles,
                    kernel=kernel,
                )
            elif stage == "modeling_boundary":
                leaf = ModelingBoundaryLeaf(context_ref=context_ref, kernel=kernel)
            elif definition.coordinate == verifier_plan.coordinate:
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
            if stage == "candidate_build":
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
                runtime.reconcile_abandoned_operation(lock, definition=definition)

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
            field_name
            for field_name in BudgetUsage.model_fields
            if field_name != "schema_version"
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

    def _persist_outcome(
        self,
        *,
        run_id: str,
        context_ref: ArtifactRef,
        status: Literal["released", "blocked"],
        bootstrap_epoch_ref: ArtifactRef,
        observed_actual: BudgetUsage,
        unknown_upper_bound: BudgetUsage,
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


__all__ = ["DirectWorkRun", "DirectWorkRunner", "DirectWorkRunnerError"]
