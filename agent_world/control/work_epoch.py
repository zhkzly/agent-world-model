"""Durable topology-epoch freezing for one real generation context.

Architecture determines physical behavior members, while the compiled
curriculum determines the real Challenger partition.  The runtime freezes each
fact only once and retains its exact commits in the next graph; it never turns
an unknown fan-out into hidden calls inside a nominal leaf. Each frozen
manifest also retains its full immutable WorkDefinition closure, including
nodes that have not yet dispatched, so a diagnostic test-node can reconstruct
a real target without replaying its historical output.
"""

from __future__ import annotations

from agent_world.artifact_store import ArtifactWriter
from agent_world.contracts import ArtifactRef, GenerationContext
from agent_world.diagnostic_state import has_test_node_diagnostic_marker

from .work import WorkAttempt, WorkCommit
from .work_graph import GenerationWorkGraph, WorkGraphEpoch, WorkGraphError, WorkGraphManifest
from .work_store import WorkControlStore, WorkResumeError

_BOOTSTRAP_STAGES = frozenset(
    {
        ("research", "research_plan"),
        ("research", "evidence_acquisition"),
        ("research", "evidence_synthesis"),
        ("design", "world_architecture"),
    }
)
_DIAGNOSTIC_OVERLAY_ARTIFACT_TYPES = frozenset(
    {
        "control.diagnostic_proposal_budget_override",
        "control.diagnostic_terminal_feedback_override",
        "control.diagnostic_runtime_implementation_override",
        "control.diagnostic_runtime_profile_override",
    }
)


class WorkGraphEpochRuntime:
    """Freeze causal topology epochs from exact durable commits only."""

    def __init__(self, *, artifacts: ArtifactWriter, heads: WorkControlStore) -> None:
        self.artifacts = artifacts
        self.heads = heads

    def freeze_bootstrap(
        self,
        *,
        context_ref: ArtifactRef,
        graph: GenerationWorkGraph,
        topology_id: str,
        allow_diagnostic_predecessors: bool = False,
        diagnostic_overlay_ref: ArtifactRef | None = None,
    ) -> tuple[WorkGraphManifest, ArtifactRef, WorkGraphEpoch, ArtifactRef]:
        context = self._load_context(context_ref)
        if graph.mode != "diagnostic" or graph.release_eligible:
            raise WorkGraphError("bootstrap graph must be diagnostic and non-releasable")
        self._require_context_root(graph, context_ref)
        stages = {(item.coordinate.component, item.coordinate.stage) for item in graph.definitions}
        if not _BOOTSTRAP_STAGES <= stages:
            raise WorkGraphError(
                "bootstrap graph must include grounded Research through Architecture"
            )
        self._validate_diagnostic_overlay(
            diagnostic_overlay_ref,
            allow_diagnostic_predecessors=allow_diagnostic_predecessors,
        )
        definition_refs = self._persist_definition_closure(graph, context_ref=context_ref)
        overlay_dependencies = (
            (diagnostic_overlay_ref,) if diagnostic_overlay_ref is not None else ()
        )
        manifest = graph.manifest(
            topology_id=topology_id,
            external_root_refs=(context_ref,),
        )
        manifest_ref = self.artifacts.put_json(
            artifact_id=f"work-graph-manifest:{manifest.graph_id}",
            artifact_type="control.work_graph_manifest",
            value=manifest,
            dependencies=(context_ref, *definition_refs, *overlay_dependencies),
        )
        epoch = WorkGraphEpoch(
            epoch_id=f"epoch:bootstrap:{manifest.graph_digest.removeprefix('sha256:')[:24]}",
            scope_id=manifest.scope_id,
            epoch_kind="bootstrap",
            context_ref=context_ref,
            manifest_ref=manifest_ref,
        )
        epoch_ref = self.artifacts.put_json(
            artifact_id=epoch.epoch_id,
            artifact_type="control.work_graph_epoch",
            value=epoch,
            dependencies=(context_ref, manifest_ref, *definition_refs, *overlay_dependencies),
        )
        # This load also proves callers cannot pass an arbitrary context-shaped
        # artifact that was never issued under the closed contract.
        if context.kind not in {"generate", "expand"}:  # pragma: no cover - closed literal
            raise WorkGraphError("GenerationContext kind is not executable")
        return manifest, manifest_ref, epoch, epoch_ref

    def freeze_world(
        self,
        *,
        context_ref: ArtifactRef,
        bootstrap_epoch_ref: ArtifactRef,
        graph: GenerationWorkGraph,
        topology_id: str,
        allow_diagnostic_predecessors: bool = False,
        diagnostic_overlay_ref: ArtifactRef | None = None,
    ) -> tuple[WorkGraphManifest, ArtifactRef, WorkGraphEpoch, ArtifactRef]:
        """Freeze behavior, WorldRules, and the committed-plan discovery boundary."""

        self._load_context(context_ref)
        bootstrap = self._load_epoch(bootstrap_epoch_ref)
        if bootstrap.epoch_kind != "bootstrap" or bootstrap.context_ref != context_ref:
            raise WorkGraphError("world epoch must retain the exact bootstrap GenerationContext")
        bootstrap_manifest = self.artifacts.get_json(bootstrap.manifest_ref, WorkGraphManifest)
        if bootstrap_manifest.mode != "diagnostic" or bootstrap_manifest.releasable:
            raise WorkGraphError("world epoch predecessor is not a diagnostic bootstrap graph")
        if graph.mode != "diagnostic" or graph.release_eligible:
            raise WorkGraphError("world epoch must remain diagnostic and non-releasable")
        self._require_context_root(graph, context_ref)
        if graph.definitions[0].coordinate.scope_id != bootstrap.scope_id:
            raise WorkGraphError("bootstrap and world graph scopes differ")
        self._require_world_terminal(graph)
        if allow_diagnostic_predecessors and not has_test_node_diagnostic_marker(self.heads.root):
            raise WorkGraphError(
                "diagnostic world successors require an isolated test-node state root"
            )
        self._validate_diagnostic_overlay(
            diagnostic_overlay_ref,
            allow_diagnostic_predecessors=allow_diagnostic_predecessors,
        )
        retained = self._require_retained_predecessor_commits(
            bootstrap_manifest,
            graph,
            allow_diagnostic_predecessors=allow_diagnostic_predecessors,
        )
        definition_refs = self._persist_definition_closure(graph, context_ref=context_ref)
        overlay_dependencies = (
            (diagnostic_overlay_ref,) if diagnostic_overlay_ref is not None else ()
        )
        manifest = graph.manifest(
            topology_id=topology_id,
            external_root_refs=(context_ref,),
        )
        manifest_ref = self.artifacts.put_json(
            artifact_id=f"work-graph-manifest:{manifest.graph_id}",
            artifact_type="control.work_graph_manifest",
            value=manifest,
            dependencies=(
                context_ref,
                bootstrap_epoch_ref,
                *retained,
                *definition_refs,
                *overlay_dependencies,
            ),
        )
        epoch = WorkGraphEpoch(
            epoch_id=f"epoch:world:{manifest.graph_digest.removeprefix('sha256:')[:24]}",
            scope_id=manifest.scope_id,
            epoch_kind="world",
            context_ref=context_ref,
            manifest_ref=manifest_ref,
            predecessor_epoch_ref=bootstrap_epoch_ref,
            retained_commit_refs=retained,
        )
        epoch_ref = self.artifacts.put_json(
            artifact_id=epoch.epoch_id,
            artifact_type="control.work_graph_epoch",
            value=epoch,
            dependencies=(
                context_ref,
                bootstrap_epoch_ref,
                manifest_ref,
                *retained,
                *definition_refs,
                *overlay_dependencies,
            ),
        )
        return manifest, manifest_ref, epoch, epoch_ref

    def freeze_diagnostic_world_from_legacy_design(
        self,
        *,
        context_ref: ArtifactRef,
        legacy_design_epoch_ref: ArtifactRef,
        legacy_manifest_ref: ArtifactRef,
        graph: GenerationWorkGraph,
        topology_id: str,
        diagnostic_overlay_ref: ArtifactRef | None = None,
    ) -> tuple[WorkGraphManifest, ArtifactRef, WorkGraphEpoch, ArtifactRef]:
        """Freeze one diagnostic-only WorldRules-to-Plan topology migration.

        This is deliberately *not* a second normal ``freeze_world`` route.
        It exists only so a marked test-node state captured before task-family
        fan-out can prove the new, smaller ``CurriculumPlan`` boundary without
        re-running or rewriting its already committed WorldRules closure.

        Every committed definition from the historical Design manifest must be
        byte-for-byte retained and bound as an epoch dependency.  The only
        permitted omissions are the historical, still-unheaded tail
        (TaskCurriculum, ModelingBoundary and VerifierPlan); the sole added
        coordinate is the new unheaded CurriculumPlan.  This makes a topology
        migration auditable while keeping it isolated, diagnostic-only and
        permanently non-releasable.
        """

        self._load_context(context_ref)
        if not has_test_node_diagnostic_marker(self.heads.root):
            raise WorkGraphError(
                "legacy diagnostic world migration requires an isolated test-node state root"
            )
        self._validate_diagnostic_overlay(
            diagnostic_overlay_ref,
            allow_diagnostic_predecessors=True,
        )
        legacy = self._load_epoch(legacy_design_epoch_ref)
        if legacy.epoch_kind != "design" or legacy.context_ref != context_ref:
            raise WorkGraphError(
                "legacy diagnostic world migration requires one exact Design predecessor"
            )
        if legacy.manifest_ref != legacy_manifest_ref:
            raise WorkGraphError(
                "legacy diagnostic world migration manifest does not match its Design epoch"
            )
        legacy_manifest = self.artifacts.get_json(legacy_manifest_ref, WorkGraphManifest)
        if legacy_manifest.mode != "diagnostic" or legacy_manifest.releasable:
            raise WorkGraphError(
                "legacy diagnostic world migration requires a non-releasable Design manifest"
            )
        if graph.mode != "diagnostic" or graph.release_eligible:
            raise WorkGraphError("legacy diagnostic world migration must remain non-releasable")
        self._require_context_root(graph, context_ref)
        if graph.definitions[0].coordinate.scope_id != legacy.scope_id:
            raise WorkGraphError("legacy Design and diagnostic World graph scopes differ")
        self._require_world_terminal(graph)

        legacy_bindings = {binding.coordinate: binding for binding in legacy_manifest.node_bindings}
        migrated_definitions = {
            definition.coordinate: definition for definition in graph.definitions
        }
        allowed_unheaded_tail = frozenset(
            {
                ("design", "task_curriculum"),
                ("design", "modeling_boundary"),
                ("verifier", "verifier_plan"),
            }
        )
        retained: list[ArtifactRef] = []
        saw_diagnostic_commit = False

        for coordinate, binding in legacy_bindings.items():
            definition = migrated_definitions.get(coordinate)
            head = self.heads.read_head(coordinate)
            if definition is None:
                if (
                    coordinate.component,
                    coordinate.stage,
                ) not in allowed_unheaded_tail or head is not None:
                    raise WorkGraphError(
                        "legacy diagnostic world migration omits a historical committed "
                        "definition or an attempted tail node"
                    )
                continue
            if (
                definition.work_id != binding.work_id
                or definition.definition_digest != binding.definition_digest
            ):
                raise WorkGraphError(
                    "legacy diagnostic world migration changes an already-frozen definition"
                )
            if head is None or head.status != "committed":
                raise WorkResumeError(
                    "legacy diagnostic world migration requires every retained node commit"
                )
            if head.definition_digest != definition.definition_digest:
                raise WorkResumeError(
                    "legacy diagnostic world migration found a retained definition digest drift"
                )
            attempt = self.artifacts.get_json(head.attempt_ref, WorkAttempt)
            active = self.heads.require_active_or_diagnostic_commit(
                definition=definition,
                input_refs=attempt.input_refs,
                artifacts=self.artifacts,
            )
            if active is None:
                raise WorkResumeError(
                    "legacy diagnostic world migration lacks one exact retained WorkCommit"
                )
            commit, commit_ref = active
            if commit.coordinate != coordinate:
                raise WorkResumeError(
                    "legacy diagnostic world migration retained WorkCommit coordinate drifted"
                )
            if commit.diagnostic_only and not commit.releasable:
                saw_diagnostic_commit = True
            retained.append(commit_ref)

        introduced = tuple(
            definition
            for coordinate, definition in migrated_definitions.items()
            if coordinate not in legacy_bindings
        )
        planners = tuple(
            definition
            for definition in introduced
            if (definition.coordinate.component, definition.coordinate.stage)
            == ("design", "curriculum_plan")
        )
        if len(introduced) != 1 or len(planners) != 1:
            raise WorkGraphError(
                "legacy diagnostic world migration may introduce only one CurriculumPlan"
            )
        if self.heads.read_head(planners[0].coordinate) is not None:
            raise WorkGraphError(
                "legacy diagnostic world migration cannot reuse an attempted CurriculumPlan"
            )
        if not saw_diagnostic_commit:
            raise WorkGraphError(
                "legacy diagnostic world migration requires one real diagnostic parent commit"
            )
        if not retained:
            raise WorkGraphError(
                "legacy diagnostic world migration requires a retained committed closure"
            )

        definition_refs = self._persist_definition_closure(graph, context_ref=context_ref)
        overlay_dependencies = (
            (diagnostic_overlay_ref,) if diagnostic_overlay_ref is not None else ()
        )
        manifest = graph.manifest(
            topology_id=topology_id,
            external_root_refs=(context_ref,),
        )
        manifest_ref = self.artifacts.put_json(
            artifact_id=f"work-graph-manifest:{manifest.graph_id}",
            artifact_type="control.work_graph_manifest",
            value=manifest,
            dependencies=(
                context_ref,
                legacy_design_epoch_ref,
                legacy_manifest_ref,
                *retained,
                *definition_refs,
                *overlay_dependencies,
            ),
        )
        epoch = WorkGraphEpoch(
            epoch_id=(
                "epoch:world:diagnostic-legacy:"
                f"{legacy_manifest.graph_digest.removeprefix('sha256:')[:12]}:"
                f"{manifest.graph_digest.removeprefix('sha256:')[:12]}"
            ),
            scope_id=manifest.scope_id,
            epoch_kind="world",
            context_ref=context_ref,
            manifest_ref=manifest_ref,
            predecessor_epoch_ref=legacy_design_epoch_ref,
            retained_commit_refs=tuple(retained),
        )
        epoch_ref = self.artifacts.put_json(
            artifact_id=epoch.epoch_id,
            artifact_type="control.work_graph_epoch",
            value=epoch,
            dependencies=(
                context_ref,
                legacy_design_epoch_ref,
                legacy_manifest_ref,
                manifest_ref,
                *retained,
                *definition_refs,
                *overlay_dependencies,
            ),
        )
        return manifest, manifest_ref, epoch, epoch_ref

    def freeze_design_from_world(
        self,
        *,
        context_ref: ArtifactRef,
        world_epoch_ref: ArtifactRef,
        graph: GenerationWorkGraph,
        topology_id: str,
        allow_diagnostic_predecessors: bool = False,
        diagnostic_overlay_ref: ArtifactRef | None = None,
    ) -> tuple[WorkGraphManifest, ArtifactRef, WorkGraphEpoch, ArtifactRef]:
        """Freeze plan-derived task children, their deterministic join and VerifierPlan."""

        self._load_context(context_ref)
        world = self._load_epoch(world_epoch_ref)
        if world.epoch_kind != "world" or world.context_ref != context_ref:
            raise WorkGraphError("design epoch must retain the exact world GenerationContext")
        world_manifest = self.artifacts.get_json(world.manifest_ref, WorkGraphManifest)
        if world_manifest.mode != "diagnostic" or world_manifest.releasable:
            raise WorkGraphError("design epoch predecessor is not a diagnostic world graph")
        if graph.mode != "diagnostic" or graph.release_eligible:
            raise WorkGraphError("design epoch must remain diagnostic and non-releasable")
        self._require_context_root(graph, context_ref)
        if graph.definitions[0].coordinate.scope_id != world.scope_id:
            raise WorkGraphError("world and design graph scopes differ")
        self._require_design_terminal(graph)
        stages = {(item.coordinate.component, item.coordinate.stage) for item in graph.definitions}
        if (
            not {
                ("design", "curriculum_plan"),
                ("design", "task_requirement"),
            }
            <= stages
        ):
            raise WorkGraphError(
                "plan-derived design epoch requires CurriculumPlan and TaskRequirement nodes"
            )
        if allow_diagnostic_predecessors and not has_test_node_diagnostic_marker(self.heads.root):
            raise WorkGraphError(
                "diagnostic design successors require an isolated test-node state root"
            )
        self._validate_diagnostic_overlay(
            diagnostic_overlay_ref,
            allow_diagnostic_predecessors=allow_diagnostic_predecessors,
        )
        retained = self._require_retained_predecessor_commits(
            world_manifest,
            graph,
            allow_diagnostic_predecessors=allow_diagnostic_predecessors,
        )
        definition_refs = self._persist_definition_closure(graph, context_ref=context_ref)
        overlay_dependencies = (
            (diagnostic_overlay_ref,) if diagnostic_overlay_ref is not None else ()
        )
        manifest = graph.manifest(
            topology_id=topology_id,
            external_root_refs=(context_ref,),
        )
        manifest_ref = self.artifacts.put_json(
            artifact_id=f"work-graph-manifest:{manifest.graph_id}",
            artifact_type="control.work_graph_manifest",
            value=manifest,
            dependencies=(
                context_ref,
                world_epoch_ref,
                *retained,
                *definition_refs,
                *overlay_dependencies,
            ),
        )
        epoch = WorkGraphEpoch(
            epoch_id=f"epoch:design:{manifest.graph_digest.removeprefix('sha256:')[:24]}",
            scope_id=manifest.scope_id,
            epoch_kind="design",
            context_ref=context_ref,
            manifest_ref=manifest_ref,
            predecessor_epoch_ref=world_epoch_ref,
            retained_commit_refs=retained,
        )
        epoch_ref = self.artifacts.put_json(
            artifact_id=epoch.epoch_id,
            artifact_type="control.work_graph_epoch",
            value=epoch,
            dependencies=(
                context_ref,
                world_epoch_ref,
                manifest_ref,
                *retained,
                *definition_refs,
                *overlay_dependencies,
            ),
        )
        return manifest, manifest_ref, epoch, epoch_ref

    def freeze_final(
        self,
        *,
        context_ref: ArtifactRef,
        design_epoch_ref: ArtifactRef,
        graph: GenerationWorkGraph,
        topology_id: str,
        allow_diagnostic_predecessors: bool = False,
        diagnostic_overlay_ref: ArtifactRef | None = None,
    ) -> tuple[WorkGraphManifest, ArtifactRef, WorkGraphEpoch, ArtifactRef]:
        self._load_context(context_ref)
        design = self._load_epoch(design_epoch_ref)
        if design.epoch_kind != "design" or design.context_ref != context_ref:
            raise WorkGraphError("final epoch must retain the exact design GenerationContext")
        design_manifest = self.artifacts.get_json(design.manifest_ref, WorkGraphManifest)
        if design_manifest.mode != "diagnostic" or design_manifest.releasable:
            raise WorkGraphError("final epoch predecessor is not a diagnostic Design graph")
        if graph.mode != "production" or not graph.release_eligible:
            raise WorkGraphError("final epoch requires the complete releasable production graph")
        self._require_context_root(graph, context_ref)
        if graph.definitions[0].coordinate.scope_id != design.scope_id:
            raise WorkGraphError("design and final graph scopes differ")

        if allow_diagnostic_predecessors and not has_test_node_diagnostic_marker(self.heads.root):
            raise WorkGraphError(
                "diagnostic final successors require an isolated test-node state root"
            )
        self._validate_diagnostic_overlay(
            diagnostic_overlay_ref,
            allow_diagnostic_predecessors=allow_diagnostic_predecessors,
        )
        retained = self._require_retained_predecessor_commits(
            design_manifest,
            graph,
            allow_diagnostic_predecessors=allow_diagnostic_predecessors,
        )
        self._require_exact_final_verifier_partition(graph, retained)
        definition_refs = self._persist_definition_closure(graph, context_ref=context_ref)
        overlay_dependencies = (
            (diagnostic_overlay_ref,) if diagnostic_overlay_ref is not None else ()
        )
        manifest = graph.manifest(
            topology_id=topology_id,
            external_root_refs=(context_ref,),
        )
        manifest_ref = self.artifacts.put_json(
            artifact_id=f"work-graph-manifest:{manifest.graph_id}",
            artifact_type="control.work_graph_manifest",
            value=manifest,
            dependencies=(
                context_ref,
                design_epoch_ref,
                *retained,
                *definition_refs,
                *overlay_dependencies,
            ),
        )
        epoch = WorkGraphEpoch(
            epoch_id=f"epoch:final:{manifest.graph_digest.removeprefix('sha256:')[:24]}",
            scope_id=manifest.scope_id,
            epoch_kind="final",
            context_ref=context_ref,
            manifest_ref=manifest_ref,
            predecessor_epoch_ref=design_epoch_ref,
            retained_commit_refs=retained,
        )
        epoch_ref = self.artifacts.put_json(
            artifact_id=epoch.epoch_id,
            artifact_type="control.work_graph_epoch",
            value=epoch,
            dependencies=(
                context_ref,
                design_epoch_ref,
                manifest_ref,
                *retained,
                *definition_refs,
                *overlay_dependencies,
            ),
        )
        return manifest, manifest_ref, epoch, epoch_ref

    def freeze_design(
        self,
        *,
        context_ref: ArtifactRef,
        bootstrap_epoch_ref: ArtifactRef,
        graph: GenerationWorkGraph,
        topology_id: str,
        allow_diagnostic_predecessors: bool = False,
        diagnostic_overlay_ref: ArtifactRef | None = None,
    ) -> tuple[WorkGraphManifest, ArtifactRef, WorkGraphEpoch, ArtifactRef]:
        """Freeze a legacy bootstrap-to-design diagnostic graph.

        Normal Direct execution uses :meth:`freeze_world` followed by
        :meth:`freeze_design_from_world` so task-family fan-out is derived from
        a committed CurriculumPlan.  This narrow method remains for immutable
        pre-fan-out diagnostic manifests and their deterministic reconstruction;
        it never creates the normal production path.
        """

        self._load_context(context_ref)
        bootstrap = self._load_epoch(bootstrap_epoch_ref)
        if bootstrap.epoch_kind != "bootstrap" or bootstrap.context_ref != context_ref:
            raise WorkGraphError("design epoch must retain the exact bootstrap GenerationContext")
        bootstrap_manifest = self.artifacts.get_json(
            bootstrap.manifest_ref,
            WorkGraphManifest,
        )
        if bootstrap_manifest.mode != "diagnostic" or bootstrap_manifest.releasable:
            raise WorkGraphError("design epoch predecessor is not a diagnostic bootstrap graph")
        if graph.mode != "diagnostic" or graph.release_eligible:
            raise WorkGraphError("design epoch must remain diagnostic and non-releasable")
        self._require_context_root(graph, context_ref)
        if graph.definitions[0].coordinate.scope_id != bootstrap.scope_id:
            raise WorkGraphError("bootstrap and design graph scopes differ")
        self._require_design_terminal(graph)
        if allow_diagnostic_predecessors and not has_test_node_diagnostic_marker(self.heads.root):
            raise WorkGraphError(
                "diagnostic design successors require an isolated test-node state root"
            )
        self._validate_diagnostic_overlay(
            diagnostic_overlay_ref,
            allow_diagnostic_predecessors=allow_diagnostic_predecessors,
        )
        retained = self._require_retained_predecessor_commits(
            bootstrap_manifest,
            graph,
            allow_diagnostic_predecessors=allow_diagnostic_predecessors,
        )
        definition_refs = self._persist_definition_closure(graph, context_ref=context_ref)
        manifest = graph.manifest(
            topology_id=topology_id,
            external_root_refs=(context_ref,),
        )
        manifest_ref = self.artifacts.put_json(
            artifact_id=f"work-graph-manifest:{manifest.graph_id}",
            artifact_type="control.work_graph_manifest",
            value=manifest,
            dependencies=tuple(
                ref
                for ref in (
                    context_ref,
                    bootstrap_epoch_ref,
                    *retained,
                    *definition_refs,
                    diagnostic_overlay_ref,
                )
                if ref is not None
            ),
        )
        epoch = WorkGraphEpoch(
            epoch_id=f"epoch:design:{manifest.graph_digest.removeprefix('sha256:')[:24]}",
            scope_id=manifest.scope_id,
            epoch_kind="design",
            context_ref=context_ref,
            manifest_ref=manifest_ref,
            predecessor_epoch_ref=bootstrap_epoch_ref,
            retained_commit_refs=retained,
        )
        epoch_ref = self.artifacts.put_json(
            artifact_id=epoch.epoch_id,
            artifact_type="control.work_graph_epoch",
            value=epoch,
            dependencies=(
                context_ref,
                bootstrap_epoch_ref,
                manifest_ref,
                *retained,
                *definition_refs,
                *(() if diagnostic_overlay_ref is None else (diagnostic_overlay_ref,)),
            ),
        )
        return manifest, manifest_ref, epoch, epoch_ref

    def _validate_diagnostic_overlay(
        self,
        diagnostic_overlay_ref: ArtifactRef | None,
        *,
        allow_diagnostic_predecessors: bool,
    ) -> None:
        """Authorize one test-only overlay without changing graph semantics.

        The overlay is not an alternate execution path: it records why a
        copied diagnostic epoch has one changed proposal envelope, terminal-
        feedback capture, or current runtime implementation revision. Every
        epoch kind uses this same check so a bootstrap or world boundary is no
        less observable than a later Design/final boundary.
        """

        if diagnostic_overlay_ref is None:
            return
        if not allow_diagnostic_predecessors:
            raise WorkGraphError(
                "a diagnostic graph overlay requires diagnostic predecessor authority"
            )
        if not has_test_node_diagnostic_marker(self.heads.root):
            raise WorkGraphError(
                "a diagnostic graph overlay requires an isolated test-node state root"
            )
        if diagnostic_overlay_ref.artifact_type not in _DIAGNOSTIC_OVERLAY_ARTIFACT_TYPES:
            raise WorkGraphError("diagnostic graph overlay has the wrong artifact type")

    @staticmethod
    def _require_world_terminal(graph: GenerationWorkGraph) -> None:
        """Reject a graph that tries to fan out task work before plan discovery."""

        stages = {(item.coordinate.component, item.coordinate.stage) for item in graph.definitions}
        required = {
            ("research", "research_plan"),
            ("research", "evidence_acquisition"),
            ("research", "evidence_synthesis"),
            ("design", "world_architecture"),
            ("design", "world_rules"),
            ("design", "curriculum_plan"),
        }
        if not required <= stages or not any(
            component == "design"
            and stage in {"shared_tool_semantics", "world_behavior", "tool_semantics_batch"}
            for component, stage in stages
        ):
            raise WorkGraphError(
                "world epoch lacks the complete WorldRules-to-CurriculumPlan closure"
            )
        planners = tuple(
            item
            for item in graph.definitions
            if (item.coordinate.component, item.coordinate.stage) == ("design", "curriculum_plan")
        )
        if len(planners) != 1 or graph.required_terminal_coordinates != (planners[0].coordinate,):
            raise WorkGraphError("world epoch must terminate at one CurriculumPlan")

    @staticmethod
    def _require_design_terminal(graph: GenerationWorkGraph) -> None:
        """Reject a partial semantic graph before it can masquerade as final input."""

        stages = {(item.coordinate.component, item.coordinate.stage) for item in graph.definitions}
        required = {
            ("research", "research_plan"),
            ("research", "evidence_acquisition"),
            ("research", "evidence_synthesis"),
            ("design", "world_architecture"),
            ("design", "world_rules"),
            ("design", "task_curriculum"),
            ("design", "modeling_boundary"),
            ("verifier", "verifier_plan"),
        }
        if not required <= stages or not any(
            component == "design"
            and stage in {"shared_tool_semantics", "world_behavior", "tool_semantics_batch"}
            for component, stage in stages
        ):
            raise WorkGraphError("design epoch lacks the complete semantic closure")
        plans = tuple(
            item
            for item in graph.definitions
            if (item.coordinate.component, item.coordinate.stage) == ("verifier", "verifier_plan")
        )
        modeling = tuple(
            item
            for item in graph.definitions
            if (item.coordinate.component, item.coordinate.stage) == ("design", "modeling_boundary")
        )
        if (
            len(plans) != 1
            or len(modeling) != 1
            or plans[0].dependency_coordinates != (modeling[0].coordinate,)
            or graph.required_terminal_coordinates != (plans[0].coordinate,)
        ):
            raise WorkGraphError(
                "design epoch must terminate at one direct Modeling-to-VerifierPlan"
            )

    def _require_exact_final_verifier_partition(
        self,
        graph: GenerationWorkGraph,
        retained_refs: tuple[ArtifactRef, ...],
    ) -> None:
        """Bind every physical Challenger node to the committed deterministic plan."""

        plan_definitions = tuple(
            item
            for item in graph.definitions
            if (item.coordinate.component, item.coordinate.stage) == ("verifier", "verifier_plan")
        )
        if len(plan_definitions) != 1:
            raise WorkGraphError("final graph must retain one deterministic VerifierPlan")
        plan_coordinate = plan_definitions[0].coordinate
        # Keep the control layer independent from Judge implementation while
        # still validating the closed persisted plan contract.  Importing this
        # data model here creates no execution dependency or circular authority.
        from agent_world.judge.models import VerifierBatchPlan

        retained_commits = self.artifacts.get_json_many(retained_refs, WorkCommit)
        plan_commits = [
            commit for commit in retained_commits if commit.coordinate == plan_coordinate
        ]
        if len(plan_commits) != 1:
            raise WorkGraphError("final graph lacks the retained committed VerifierPlan")
        modeling_definitions = tuple(
            item
            for item in graph.definitions
            if (item.coordinate.component, item.coordinate.stage) == ("design", "modeling_boundary")
        )
        if len(modeling_definitions) != 1:
            raise WorkGraphError("final graph must retain one committed ModelingBoundary")
        modeling_commits = tuple(
            commit
            for commit in retained_commits
            if commit.coordinate == modeling_definitions[0].coordinate
        )
        if len(modeling_commits) != 1:
            raise WorkGraphError("final graph lacks the retained committed ModelingBoundary")
        plan_refs = tuple(
            ref
            for ref in plan_commits[0].consumer_refs
            if ref.artifact_type == "judge.verifier_batch_plan"
        )
        if len(plan_refs) != 1:
            raise WorkGraphError("retained VerifierPlan must expose one exact batch-plan Artifact")
        plan = self.artifacts.get_json(plan_refs[0], VerifierBatchPlan)
        modeling_outputs = modeling_commits[0].consumer_refs
        if plan.design_ref not in modeling_outputs or plan.world_spec_ref not in modeling_outputs:
            raise WorkGraphError(
                "VerifierPlan Design closure must be produced by the retained ModelingBoundary"
            )
        batches = tuple(
            item
            for item in graph.definitions
            if (item.coordinate.component, item.coordinate.stage)
            == ("verifier", "verifier_intent_batch")
        )
        expected_shards = tuple(f"batch-{index + 1}" for index in range(len(plan.batches)))
        if (
            len(batches) != len(plan.batches)
            or tuple(sorted(item.coordinate.shard_id or "" for item in batches)) != expected_shards
            or any(item.dependency_coordinates != (plan_coordinate,) for item in batches)
            or any(item.proposal_policy.budget.agent_turns != 1 for item in batches)
        ):
            raise WorkGraphError(
                "final Challenger WorkDefinitions do not exactly match the committed VerifierPlan"
            )
        aggregates = tuple(
            item
            for item in graph.definitions
            if (item.coordinate.component, item.coordinate.stage) == ("verifier", "verifier_intent")
        )
        aggregate_groups = (
            tuple(
                group
                for group in graph.groups
                if group.aggregate_coordinate == aggregates[0].coordinate
            )
            if len(aggregates) == 1
            else ()
        )
        if (
            len(aggregates) != 1
            or len(aggregate_groups) != 1
            or aggregates[0].dependency_coordinates != aggregate_groups[0].member_coordinates
        ):
            raise WorkGraphError(
                "final Challenger aggregate must join exactly the frozen physical batch set"
            )

    def _require_retained_predecessor_commits(
        self,
        predecessor_manifest: WorkGraphManifest,
        final_graph: GenerationWorkGraph,
        *,
        allow_diagnostic_predecessors: bool = False,
    ) -> tuple[ArtifactRef, ...]:
        retained: list[ArtifactRef] = []
        for binding in predecessor_manifest.node_bindings:
            try:
                definition = final_graph.require(binding.coordinate)
            except WorkGraphError as exc:
                raise WorkGraphError(
                    "next graph omits a predecessor coordinate and would create a shadow path"
                ) from exc
            if (
                definition.work_id != binding.work_id
                or definition.definition_digest != binding.definition_digest
            ):
                raise WorkGraphError(
                    "next graph changes a predecessor definition instead of "
                    "invalidating it explicitly"
                )
            head = self.heads.read_head(binding.coordinate)
            if head is None or head.status != "committed":
                raise WorkResumeError("next graph cannot retain an uncommitted predecessor node")
            attempt = self.artifacts.get_json(head.attempt_ref, WorkAttempt)
            active = (
                self.heads.require_active_or_diagnostic_commit(
                    definition=definition,
                    input_refs=attempt.input_refs,
                    artifacts=self.artifacts,
                )
                if allow_diagnostic_predecessors
                else self.heads.require_active_commit(
                    definition=definition,
                    input_refs=attempt.input_refs,
                    artifacts=self.artifacts,
                )
            )
            if active is None:
                raise WorkResumeError("predecessor WorkCommit is not active for the next graph")
            commit, commit_ref = active
            if commit.coordinate != binding.coordinate:
                raise WorkResumeError("predecessor WorkCommit coordinate changed unexpectedly")
            retained.append(commit_ref)
        if not retained:
            raise WorkGraphError("next graph requires a non-empty retained predecessor closure")
        return tuple(retained)

    def _load_context(self, context_ref: ArtifactRef) -> GenerationContext:
        if context_ref.artifact_type != "control.generation_context":
            raise WorkGraphError("WorkGraph epoch requires a GenerationContext Artifact")
        return self.artifacts.get_json(context_ref, GenerationContext)

    def _load_epoch(self, epoch_ref: ArtifactRef) -> WorkGraphEpoch:
        if epoch_ref.artifact_type != "control.work_graph_epoch":
            raise WorkGraphError("final graph predecessor must be a WorkGraphEpoch Artifact")
        return self.artifacts.get_json(epoch_ref, WorkGraphEpoch)

    def _persist_definition_closure(
        self,
        graph: GenerationWorkGraph,
        *,
        context_ref: ArtifactRef,
    ) -> tuple[ArtifactRef, ...]:
        """Persist every immutable definition before an epoch references it.

        Runtime dispatch later writes an input-bound revision for commit
        authorization. This context-bound revision is deliberately separate:
        it is the complete topology contract needed to reconstruct an
        unexecuted sibling in a diagnostic state copy.
        """

        return tuple(
            self.artifacts.put_json(
                artifact_id=f"work-definition:{definition.work_id}",
                artifact_type="control.work_definition",
                value=definition,
                dependencies=(context_ref,),
            )
            for definition in graph.definitions
        )

    @staticmethod
    def _require_context_root(graph: GenerationWorkGraph, context_ref: ArtifactRef) -> None:
        # Callers create a manifest only through this runtime; accepting extra
        # roots would let a later leaf consume implicit Controller state.
        probe = graph.manifest(
            topology_id="topology:context-root-probe",
            external_root_refs=(context_ref,),
        )
        if probe.external_root_refs != (context_ref,):  # pragma: no cover - constructor fact
            raise WorkGraphError("WorkGraph roots must be exactly the GenerationContext")


__all__ = ["WorkGraphEpochRuntime"]
