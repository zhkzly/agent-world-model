"""Durable topology-epoch freezing for one real generation context.

Architecture determines physical behavior members, while the compiled
curriculum determines the real Challenger partition.  The runtime freezes each
fact only once and retains its exact commits in the next graph; it never turns
an unknown fan-out into hidden calls inside a nominal leaf.
"""

from __future__ import annotations

from agent_world.artifact_store import ArtifactWriter
from agent_world.contracts import ArtifactRef, GenerationContext

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


class WorkGraphEpochRuntime:
    """Freeze bootstrap/final graph epochs from exact durable commits only."""

    def __init__(self, *, artifacts: ArtifactWriter, heads: WorkControlStore) -> None:
        self.artifacts = artifacts
        self.heads = heads

    def freeze_bootstrap(
        self,
        *,
        context_ref: ArtifactRef,
        graph: GenerationWorkGraph,
        topology_id: str,
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
        manifest = graph.manifest(
            topology_id=topology_id,
            external_root_refs=(context_ref,),
        )
        manifest_ref = self.artifacts.put_json(
            artifact_id=f"work-graph-manifest:{manifest.graph_id}",
            artifact_type="control.work_graph_manifest",
            value=manifest,
            dependencies=(context_ref,),
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
            dependencies=(context_ref, manifest_ref),
        )
        # This load also proves callers cannot pass an arbitrary context-shaped
        # artifact that was never issued under the closed contract.
        if context.kind not in {"generate", "expand"}:  # pragma: no cover - closed literal
            raise WorkGraphError("GenerationContext kind is not executable")
        return manifest, manifest_ref, epoch, epoch_ref

    def freeze_final(
        self,
        *,
        context_ref: ArtifactRef,
        design_epoch_ref: ArtifactRef,
        graph: GenerationWorkGraph,
        topology_id: str,
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

        retained = self._require_retained_predecessor_commits(design_manifest, graph)
        self._require_exact_final_verifier_partition(graph, retained)
        manifest = graph.manifest(
            topology_id=topology_id,
            external_root_refs=(context_ref,),
        )
        manifest_ref = self.artifacts.put_json(
            artifact_id=f"work-graph-manifest:{manifest.graph_id}",
            artifact_type="control.work_graph_manifest",
            value=manifest,
            dependencies=(context_ref, design_epoch_ref, *retained),
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
            dependencies=(context_ref, design_epoch_ref, manifest_ref, *retained),
        )
        return manifest, manifest_ref, epoch, epoch_ref

    def freeze_design(
        self,
        *,
        context_ref: ArtifactRef,
        bootstrap_epoch_ref: ArtifactRef,
        graph: GenerationWorkGraph,
        topology_id: str,
    ) -> tuple[WorkGraphManifest, ArtifactRef, WorkGraphEpoch, ArtifactRef]:
        """Freeze behavior/curriculum and one deterministic VerifierPlan.

        This intermediate epoch exists solely because Verifier batch cardinality
        is a fact of the compiled curriculum, not of Architecture.  It is
        diagnostic and cannot itself establish release maturity.
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
        retained = self._require_retained_predecessor_commits(bootstrap_manifest, graph)
        manifest = graph.manifest(
            topology_id=topology_id,
            external_root_refs=(context_ref,),
        )
        manifest_ref = self.artifacts.put_json(
            artifact_id=f"work-graph-manifest:{manifest.graph_id}",
            artifact_type="control.work_graph_manifest",
            value=manifest,
            dependencies=(context_ref, bootstrap_epoch_ref, *retained),
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
            dependencies=(context_ref, bootstrap_epoch_ref, manifest_ref, *retained),
        )
        return manifest, manifest_ref, epoch, epoch_ref

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
            component == "design" and stage in {"shared_tool_semantics", "tool_semantics_batch"}
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
            if (item.coordinate.component, item.coordinate.stage)
            == ("design", "modeling_boundary")
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
        plan_commits: list[WorkCommit] = []
        for ref in retained_refs:
            commit = self.artifacts.get_json(ref, WorkCommit)
            if commit.coordinate == plan_coordinate:
                plan_commits.append(commit)
        if len(plan_commits) != 1:
            raise WorkGraphError("final graph lacks the retained committed VerifierPlan")
        modeling_definitions = tuple(
            item
            for item in graph.definitions
            if (item.coordinate.component, item.coordinate.stage)
            == ("design", "modeling_boundary")
        )
        if len(modeling_definitions) != 1:
            raise WorkGraphError("final graph must retain one committed ModelingBoundary")
        modeling_commits = tuple(
            self.artifacts.get_json(ref, WorkCommit)
            for ref in retained_refs
            if self.artifacts.get_json(ref, WorkCommit).coordinate
            == modeling_definitions[0].coordinate
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
        if (
            plan.design_ref not in modeling_outputs
            or plan.world_spec_ref not in modeling_outputs
        ):
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
            or tuple(sorted(item.coordinate.shard_id or "" for item in batches))
            != expected_shards
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
        if (
            len(aggregates) != 1
            or aggregates[0].dependency_coordinates
            != tuple(item.coordinate for item in batches)
        ):
            raise WorkGraphError(
                "final Challenger aggregate must join exactly the frozen physical batch set"
            )

    def _require_retained_predecessor_commits(
        self,
        predecessor_manifest: WorkGraphManifest,
        final_graph: GenerationWorkGraph,
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
            active = self.heads.require_active_commit(
                definition=definition,
                input_refs=attempt.input_refs,
                artifacts=self.artifacts,
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
