"""Scheduler-owned release leaves: observability, packaging and publication.

These leaves are deliberately code-only.  They assemble and publish bytes that
have already passed the independent Builder/Judge path; they never ask an LLM
to decide identity, manufacture evidence, or approve a release.  Keeping this
closure in the WorkGraph prevents the old Controller's ClaimVector/repair loop
from becoming a second release authority.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from agent_world.contracts import (
    ArtifactRef,
    CandidateManifest,
    EnvironmentCandidate,
    EnvironmentDesign,
    EnvironmentJob,
    EnvironmentPackageManifest,
    FrameworkPackagePayload,
    GenerationContext,
    IdentityDecision,
    ImplementationLineage,
    IntegrationReport,
    JudgeReport,
    PackageLineage,
    ReleaseProfile,
    SemanticLineage,
    TrustedEvaluatorDescriptor,
    canonical_json_bytes,
    compile_framework_package_payloads,
    sha256_digest,
)

from .assurance import TelemetryReleaseSummary
from .leaf_executor import (
    LeafExecutionFailure,
    LeafProposal,
    SchedulerLeafExecutor,
)
from .release_dossier import ReleaseDossier, ReleaseDossierCompiler
from .telemetry import TelemetryStore
from .work import OperationRun, ProposalExecution, WorkAttempt, WorkDefinition
from .work_graph import GenerationWorkGraph
from .work_scheduler import WorkExecutionContext
from .work_store import WorkControlStore

if TYPE_CHECKING:
    from agent_world.builder.service import EnvironmentBuilder
    from agent_world.registry.models import ReleaseRecord
    from agent_world.registry.registry import EnvironmentRegistry

@dataclass(slots=True)
class _ReleaseClosure:
    """Exact immutable records selected from active final-graph commits."""

    context_ref: ArtifactRef
    context: GenerationContext
    design_ref: ArtifactRef
    design: EnvironmentDesign
    world_spec_ref: ArtifactRef
    candidate_ref: ArtifactRef
    candidate: EnvironmentCandidate
    candidate_manifest_ref: ArtifactRef
    candidate_manifest: CandidateManifest
    build_record_ref: ArtifactRef
    implementation_lineage_ref: ArtifactRef
    implementation_lineage: ImplementationLineage
    verifier_ref: ArtifactRef
    integration_report_ref: ArtifactRef
    integration_report: IntegrationReport
    judge_report_ref: ArtifactRef
    judge_report: JudgeReport


@dataclass(slots=True)
class ObservabilityLeaf:
    """Freeze the real, sanitized trace cut immediately before packaging."""

    heads: WorkControlStore
    graph: GenerationWorkGraph
    telemetry: TelemetryStore
    trace_id: str
    kernel: SchedulerLeafExecutor

    async def execute(
        self,
        context: WorkExecutionContext,
        *,
        definition: WorkDefinition,
    ) -> None:
        async def proposal(
            _context: WorkExecutionContext,
            attempt: WorkAttempt,
            _dispatch_id: str,
        ) -> LeafProposal:
            summary_ref = self._compile_summary(attempt)
            return LeafProposal(output_refs=(summary_ref,), subject_refs=(summary_ref,))

        await self.kernel.execute(context, definition=definition, proposal_runner=proposal)

    def _compile_summary(self, attempt: WorkAttempt) -> ArtifactRef:
        self.telemetry.flush()
        health = self.telemetry.health()
        if health.get("journal_mode") != "wal":
            raise LeafExecutionFailure(
                code="preflight_telemetry_journal_unhealthy",
                category="TelemetryStore journal is not WAL",
            )
        inspected = self.telemetry.inspect_trace(self.trace_id)
        summary = inspected["summary"]
        spans = tuple(inspected["spans"])
        metrics = tuple(inspected["metrics"])
        events = tuple(inspected["events"])
        open_spans = tuple(item for item in spans if item["status"] == "running")
        # The root lives until publication completes; the currently executing
        # closure leaf is the only permitted additional open span.  Any other
        # live work would make this package's operational evidence incomplete.
        if len(open_spans) != 2:
            raise LeafExecutionFailure(
                code="preflight_telemetry_prepackage_open_span_count",
                category="pre-package telemetry must contain only root and closure spans",
            )
        if not any(item["operation"] == "direct.generate" for item in open_spans):
            raise LeafExecutionFailure(
                code="preflight_telemetry_generation_root_missing",
                category="pre-package telemetry lacks the live generation root",
            )
        if attempt.telemetry_span_id not in {item["span_id"] for item in open_spans}:
            raise LeafExecutionFailure(
                code="preflight_telemetry_closure_span_missing",
                category="observability attempt is not represented in the trace cut",
            )

        committed_attempts = self._prepackage_attempts()
        missing_attempt_spans = tuple(
            item.attempt_id
            for item in committed_attempts
            if item.telemetry_trace_id != self.trace_id or item.telemetry_span_id is None
        )
        if missing_attempt_spans:
            raise LeafExecutionFailure(
                code="preflight_telemetry_work_attempt_missing",
                category="committed pre-package Work lacks trace ownership",
            )
        spans_by_id = {str(item["span_id"]): item for item in spans}
        if any(
            spans_by_id.get(str(item.telemetry_span_id), {}).get("status") != "passed"
            for item in committed_attempts
        ):
            raise LeafExecutionFailure(
                code="preflight_telemetry_work_attempt_not_terminal",
                category="committed pre-package Work has no passed trace span",
            )

        invocation_count = sum(
            1
            for item in spans
            if item["operation"] == "agent.invoke" and item["status"] == "passed"
        )
        agent_attempt_count = sum(
            1
            for item in committed_attempts
            if self._attempt_has_agent_proposal(item)
        )
        if invocation_count < agent_attempt_count:
            raise LeafExecutionFailure(
                code="preflight_telemetry_agent_invocation_underreported",
                category="trace does not account for every committed Agent proposal",
            )
        operation_counts = {
            name: sum(
                1 for item in spans if item["operation"] == name and item["status"] == "passed"
            )
            for name in ("research.search", "research.fetch", "research.extract")
        }
        if any(value < 1 for value in operation_counts.values()):
            raise LeafExecutionFailure(
                code="preflight_telemetry_research_operation_missing",
                category="fresh Direct research did not expose search/fetch/extract accounting",
            )
        metric_counts = {
            name: sum(1 for item in metrics if item["name"] == name)
            for name in (
                "invocation.tokens.total",
                "research.search.calls",
                "research.fetch.calls",
                "research.documents.extracted",
            )
        }
        if any(value < 1 for value in metric_counts.values()):
            raise LeafExecutionFailure(
                code="preflight_telemetry_required_metric_missing",
                category="trace omits a required released-path measurement",
            )
        node_counts = {
            f"{item.coordinate.component}.{item.coordinate.stage}": 1
            for item in committed_attempts
        }
        telemetry = TelemetryReleaseSummary(
            trace_id=self.trace_id,
            run_id=self.trace_id,
            collected_at=datetime.now(UTC),
            cut_stage="pre_publish",
            as_of_ns=int(summary["as_of_ns"]),
            open_span_count=len(open_spans),
            provisional=True,
            span_count=len(spans),
            metric_count=len(metrics),
            event_count=len(events),
            invocation_count=invocation_count,
            required_node_attempts=node_counts,
            required_operation_attempts=operation_counts,
            required_metric_observations=metric_counts,
            unknown_measurement_count=sum(
                int(value) for value in summary["unknown_measurements"].values()
            ),
            summary=summary,
            summary_digest=sha256_digest(canonical_json_bytes(summary)),
        )
        dependencies = tuple(
            dict.fromkeys(
                (
                    *self._prepackage_commit_refs(),
                    *(
                        ref
                        for item in committed_attempts
                        for ref in item.operation_run_refs
                    ),
                )
            )
        )
        return self.kernel.runtime.artifacts.put_json(
            artifact_id=f"telemetry-summary:{self.trace_id}",
            artifact_type="release.telemetry_summary",
            value=telemetry,
            dependencies=dependencies,
        )

    def _prepackage_attempts(self) -> tuple[WorkAttempt, ...]:
        """Return every committed prerequisite attempt in the frozen graph.

        A release telemetry summary cannot claim end-to-end accounting while
        silently omitting Architecture, behavior, rules, curriculum or a
        verifier shard.  Package and Registry are excluded because they occur
        after this pre-package trace cut; every other final-graph definition is
        mandatory and must expose the same trace identity.
        """

        attempts: list[WorkAttempt] = []
        for definition in self.graph.topological_definitions():
            if definition.coordinate.component in {"release", "registry"}:
                continue
            head = self.heads.read_head(definition.coordinate)
            if head is None or head.status != "committed":
                raise LeafExecutionFailure(
                    code="preflight_telemetry_prepackage_work_uncommitted",
                    category="released trace closure has an uncommitted prerequisite",
                )
            attempts.append(
                self.kernel.runtime.artifacts.get_json(head.attempt_ref, WorkAttempt)
            )
        return tuple(attempts)

    def _prepackage_commit_refs(self) -> tuple[ArtifactRef, ...]:
        refs: list[ArtifactRef] = []
        for definition in self.graph.topological_definitions():
            if definition.coordinate.component in {"release", "registry"}:
                continue
            head = self.heads.read_head(definition.coordinate)
            if head is not None and head.status == "committed" and head.commit_ref is not None:
                refs.append(head.commit_ref)
        return tuple(refs)

    def _attempt_has_agent_proposal(self, attempt: WorkAttempt) -> bool:
        for ref in attempt.operation_run_refs:
            operation = self.kernel.runtime.artifacts.get_json(ref, OperationRun)
            if operation.kind != "proposal":
                continue
            if operation.execution_ref is None:
                continue
            execution = self.kernel.runtime.artifacts.get_json(
                operation.execution_ref,
                ProposalExecution,
            )
            if execution.executor == "agent":
                return True
        return False


@dataclass(slots=True)
class PackageLeaf:
    """Compile one envpkg v3 manifest from the active pre-package closure."""

    builder: EnvironmentBuilder
    graph: GenerationWorkGraph
    final_epoch_ref: ArtifactRef
    final_manifest_ref: ArtifactRef
    release_profile: ReleaseProfile
    workspace_root: Path
    dossier_compiler: ReleaseDossierCompiler
    kernel: SchedulerLeafExecutor

    async def execute(
        self,
        context: WorkExecutionContext,
        *,
        definition: WorkDefinition,
    ) -> None:
        async def proposal(
            current_context: WorkExecutionContext,
            attempt: WorkAttempt,
            _dispatch_id: str,
        ) -> LeafProposal:
            closure = self._closure(current_context)
            telemetry_ref = self._one_parent(current_context, "release.telemetry_summary")
            _dossier, dossier_ref = self.dossier_compiler.compile(
                final_epoch_ref=self.final_epoch_ref,
                graph=self.graph,
                manifest_ref=self.final_manifest_ref,
                design_ref=closure.design_ref,
                candidate_ref=closure.candidate_ref,
                candidate_manifest_ref=closure.candidate_manifest_ref,
                build_record_ref=closure.build_record_ref,
                implementation_lineage_ref=closure.implementation_lineage_ref,
                verifier_ref=closure.verifier_ref,
                integration_report_ref=closure.integration_report_ref,
                judge_report_ref=closure.judge_report_ref,
                telemetry_summary_ref=telemetry_ref,
                release_profile=self.release_profile,
            )
            package_id, version, lineage, lineage_refs = self._direct_identity(closure)
            from agent_world.builder.service import BuilderError

            try:
                source_root = self.builder.materialize_exact_candidate(
                    candidate=closure.candidate,
                    candidate_ref=closure.candidate_ref,
                    workspace=self.workspace_root / attempt.attempt_id,
                )
                pyproject_bytes = (source_root / "pyproject.toml").read_bytes()
                uv_lock_bytes = (source_root / "uv.lock").read_bytes()
            except (BuilderError, OSError) as exc:
                raise LeafExecutionFailure(
                    code="package_candidate_snapshot_materialization_failed",
                    category="exact Candidate package inputs cannot be restored",
                ) from exc
            framework_payloads = compile_framework_package_payloads(
                closure.design,
                package_id=package_id,
                version=version,
                candidate_manifest=closure.candidate_manifest,
                judge_report=closure.judge_report,
                integration_report=closure.integration_report,
                lineage=lineage,
                design_ref=closure.design_ref,
                world_spec_ref=closure.world_spec_ref,
                candidate_ref=closure.candidate_ref,
                candidate_manifest_ref=closure.candidate_manifest_ref,
                build_record_ref=closure.build_record_ref,
                implementation_lineage_ref=closure.implementation_lineage_ref,
                judge_report_ref=closure.judge_report_ref,
                integration_report_ref=closure.integration_report_ref,
                release_dossier_ref=dossier_ref,
                telemetry_summary_ref=telemetry_ref,
                pyproject_bytes=pyproject_bytes,
                uv_lock_bytes=uv_lock_bytes,
            )
            manifest = EnvironmentPackageManifest(
                package_id=package_id,
                version=version,
                created_at=datetime.now(UTC),
                world_boundary_hash=closure.design.world_spec.boundary.content_digest(),
                world_spec_hash=closure.design.world_spec.content_digest(),
                candidate_source_tree_digest=closure.candidate_manifest.candidate_source_tree_digest,
                design_ref=closure.design_ref,
                world_spec_ref=closure.world_spec_ref,
                candidate_ref=closure.candidate_ref,
                candidate_manifest_ref=closure.candidate_manifest_ref,
                build_record_ref=closure.build_record_ref,
                implementation_lineage_ref=closure.implementation_lineage_ref,
                judge_report_ref=closure.judge_report_ref,
                integration_report_ref=closure.integration_report_ref,
                release_dossier_ref=dossier_ref,
                telemetry_summary_ref=telemetry_ref,
                runtime=closure.candidate.runtime,
                task_materializer=closure.candidate.task_materializer,
                trusted_evaluator=TrustedEvaluatorDescriptor(),
                public_self_check=closure.candidate.public_self_check,
                public_verifier_ref=closure.candidate.public_verifier_ref,
                files=(
                    *closure.candidate_manifest.files,
                    *(item.descriptor() for item in framework_payloads),
                ),
                lineage=lineage,
                known_limits=closure.candidate_manifest.known_limits,
            )
            manifest_identity = sha256_digest(
                canonical_json_bytes((package_id, version, dossier_ref.revision_id))
            ).removeprefix("sha256:")[:32]
            manifest_ref = self.kernel.runtime.artifacts.put_json(
                artifact_id=(
                    "environment-package-manifest:"
                    f"{manifest_identity}"
                ),
                artifact_type="environment_package_manifest",
                value=manifest,
                dependencies=tuple(
                    dict.fromkeys(
                        (
                            closure.design_ref,
                            closure.world_spec_ref,
                            closure.candidate_ref,
                            closure.candidate_manifest_ref,
                            closure.build_record_ref,
                            closure.implementation_lineage_ref,
                            closure.judge_report_ref,
                            closure.integration_report_ref,
                            closure.verifier_ref,
                            telemetry_ref,
                            dossier_ref,
                            closure.candidate.public_verifier_ref,
                            closure.candidate.task_materializer.output_schema_ref,
                            closure.candidate.task_materializer.curriculum_ref,
                            *lineage_refs,
                        )
                    )
                ),
            )
            return LeafProposal(
                output_refs=(manifest_ref,),
                subject_refs=(manifest_ref,),
            )

        await self.kernel.execute(context, definition=definition, proposal_runner=proposal)

    def _closure(self, context: WorkExecutionContext) -> _ReleaseClosure:
        artifacts = self.kernel.runtime.artifacts
        # Package is a normal Scheduler leaf, not a second controller.  Its
        # complete release closure must therefore arrive through the frozen
        # WorkDefinition input slots.  Reading arbitrary active Work heads
        # here used to create a hidden data edge: a later graph edit could
        # change package bytes without changing this attempt's input
        # fingerprint or invalidation lineage.
        context_ref = self._one_external(context, "control.generation_context")
        generation = artifacts.get_json(context_ref, GenerationContext)
        design_ref = self._one_parent(context, "design.environment_design")
        design = artifacts.get_json(design_ref, EnvironmentDesign)
        world_spec_ref = self._one_parent(context, "design.world_spec")
        if design.world_spec.content_digest() != world_spec_ref.content_hash:
            raise LeafExecutionFailure(
                code="preflight_package_design_world_closure_invalid",
                category="package Design does not bind its exact WorldSpec input",
            )
        artifacts.require_exact_json(
            world_spec_ref,
            design.world_spec,
            artifact_types=("design.world_spec",),
        )
        candidate_ref = self._one_parent(context, "build.environment_candidate")
        candidate = artifacts.get_json(candidate_ref, EnvironmentCandidate)
        candidate_manifest_ref = self._one_parent(context, "build.candidate_manifest")
        candidate_manifest = artifacts.get_json(candidate_manifest_ref, CandidateManifest)
        build_record_ref = self._one_parent(context, "build.record")
        implementation_lineage_ref = self._one_parent(context, "build.implementation_lineage")
        implementation_lineage = artifacts.get_json(
            implementation_lineage_ref,
            ImplementationLineage,
        )
        verifier_ref = self._one_parent(context, "judge.verifier_ir_projection")
        integration_report_ref = self._one_parent(context, "judge.integration_report")
        judge_report_ref = self._one_parent(context, "judge_report")
        integration = artifacts.get_json(integration_report_ref, IntegrationReport)
        judge = artifacts.get_json(judge_report_ref, JudgeReport)
        if (
            candidate.design_ref != design_ref
            or candidate.candidate_manifest_ref != candidate_manifest_ref
            or candidate.implementation_lineage_ref != implementation_lineage_ref
            or candidate.build_artifact_ref != build_record_ref
        ):
            raise LeafExecutionFailure(
                code="preflight_package_active_closure_mismatch",
                category="active package inputs do not form one Candidate closure",
            )
        return _ReleaseClosure(
            context_ref=context_ref,
            context=generation,
            design_ref=design_ref,
            design=design,
            world_spec_ref=world_spec_ref,
            candidate_ref=candidate_ref,
            candidate=candidate,
            candidate_manifest_ref=candidate_manifest_ref,
            candidate_manifest=candidate_manifest,
            build_record_ref=build_record_ref,
            implementation_lineage_ref=implementation_lineage_ref,
            implementation_lineage=implementation_lineage,
            verifier_ref=verifier_ref,
            integration_report_ref=integration_report_ref,
            integration_report=integration,
            judge_report_ref=judge_report_ref,
            judge_report=judge,
        )

    def _direct_identity(
        self,
        closure: _ReleaseClosure,
    ) -> tuple[str, str, PackageLineage, tuple[ArtifactRef, ...]]:
        """Compile initial-package identity; expansion has its own admitted lineage.

        The first vertical slice is deliberately Direct-only.  Treating an
        expansion as an initial package would erase parents/operator evidence,
        so it fails closed until the Expansion scheduler provides its admitted
        identity and parent-release resolver as typed inputs.
        """

        if closure.context.kind != "generate" or closure.design.semantic_lineage_ref is not None:
            raise LeafExecutionFailure(
                code="preflight_package_expansion_identity_unavailable",
                category="Expansion package identity requires its admitted lineage route",
            )
        job = self.kernel.runtime.artifacts.get_json(closure.context.job_ref, EnvironmentJob)
        boundary_hash = closure.design.world_spec.boundary.content_digest()
        world_spec_hash = closure.design.world_spec.content_digest()
        tool_hash = sha256_digest(
            canonical_json_bytes(
                [
                    item.model_dump(mode="json", exclude_none=False)
                    for item in sorted(
                        closure.design.world_spec.tools,
                        key=lambda value: value.surface.tool_id,
                    )
                ]
            )
        )
        identity = IdentityDecision(
            decision_id=f"identity:{boundary_hash.removeprefix('sha256:')[:32]}",
            target_kind="new_package",
            boundary_after_hash=boundary_hash,
            changed_boundary_dimensions=(),
            rationale=(
                "Initial Direct Generation has no semantic parent; immutable identity derives "
                "from the compiled WorldBoundary rather than generated source code."
            ),
            confidence=1.0,
        )
        identity_ref = self.kernel.runtime.artifacts.put_json(
            artifact_id=f"release-identity:{boundary_hash.removeprefix('sha256:')[:32]}",
            artifact_type="release.identity_decision",
            value=identity,
            dependencies=(closure.design_ref, closure.world_spec_ref),
        )
        # The frozen EvidenceGraph revision itself is a sufficient immutable
        # provenance root.  Package assembly must not re-interpret evidence or
        # assume a particular source transport at release time.
        evidence_refs = (closure.design.evidence_graph_ref,)
        seed = int(
            hashlib.sha256(f"{job.job_id}\0{closure.design_ref.revision_id}".encode()).hexdigest()[:16],
            16,
        )
        semantic = SemanticLineage(
            lineage_id=(
                "semantic-lineage:"
                f"{closure.design_ref.revision_id.removeprefix('sha256:')[:32]}"
            ),
            evidence_refs=evidence_refs,
            operator_id="initial_generation",
            operator_version="1",
            operator_parameters={"origin": "direct_generate"},
            seed=seed,
            tool_contract_set_after_hash=tool_hash,
            world_spec_after_hash=world_spec_hash,
            semantic_delta_hash=sha256_digest(
                canonical_json_bytes(
                    {
                        "operator": "initial_generation",
                        "world_boundary_hash": boundary_hash,
                        "world_spec_hash": world_spec_hash,
                        "tool_contract_set_hash": tool_hash,
                    }
                )
            ),
            identity_decision=identity,
        )
        semantic_ref = self.kernel.runtime.artifacts.put_json(
            artifact_id=f"release-semantic-lineage:{closure.design_ref.revision_id.removeprefix('sha256:')[:32]}",
            artifact_type="release.semantic_lineage",
            value=semantic,
            dependencies=(identity_ref, closure.design_ref, closure.world_spec_ref, *evidence_refs),
        )
        return (
            f"env:{boundary_hash.removeprefix('sha256:')[:32]}",
            "1.0.0",
            PackageLineage(semantic=semantic, implementation=closure.implementation_lineage),
            (identity_ref, semantic_ref),
        )

    @staticmethod
    def _one_parent(context: WorkExecutionContext, artifact_type: str) -> ArtifactRef:
        matches = tuple(
            ref for ref in context.parent_output_refs if ref.artifact_type == artifact_type
        )
        if len(matches) != 1:
            raise LeafExecutionFailure(
                code="preflight_package_parent_output_missing",
                category="Package lacks one exact typed Scheduler input",
            )
        return matches[0]

    @staticmethod
    def _one_external(context: WorkExecutionContext, artifact_type: str) -> ArtifactRef:
        matches = tuple(
            ref for ref in context.external_input_refs if ref.artifact_type == artifact_type
        )
        if len(matches) != 1:
            raise LeafExecutionFailure(
                code="preflight_package_generation_context_missing",
                category="Package lacks its immutable GenerationContext root",
            )
        return matches[0]


@dataclass(slots=True)
class RegistryPublicationLeaf:
    """Reserve, stage, validate and atomically publish one exact envpkg."""

    builder: EnvironmentBuilder
    registry: EnvironmentRegistry
    workspace_root: Path
    kernel: SchedulerLeafExecutor

    async def execute(
        self,
        context: WorkExecutionContext,
        *,
        definition: WorkDefinition,
    ) -> None:
        async def proposal(
            current_context: WorkExecutionContext,
            attempt: WorkAttempt,
            _dispatch_id: str,
        ) -> LeafProposal:
            manifest_ref = PackageLeaf._one_parent(
                current_context,
                "environment_package_manifest",
            )
            manifest = self.kernel.runtime.artifacts.get_json(
                manifest_ref,
                EnvironmentPackageManifest,
            )
            record = self._publish_exact(manifest_ref, manifest, attempt.attempt_id)
            record_ref = self.kernel.runtime.artifacts.put_json(
                artifact_id=f"release-record:{record.release_id}",
                artifact_type="release.record",
                value=record,
                dependencies=(
                    manifest_ref,
                    manifest.judge_report_ref,
                    manifest.integration_report_ref,
                    manifest.release_dossier_ref,
                    manifest.telemetry_summary_ref,
                    manifest.candidate_ref,
                ),
            )
            return LeafProposal(output_refs=(record_ref,), subject_refs=(record_ref,))

        await self.kernel.execute(context, definition=definition, proposal_runner=proposal)

    def _publish_exact(
        self,
        manifest_ref: ArtifactRef,
        manifest: EnvironmentPackageManifest,
        attempt_id: str,
    ) -> ReleaseRecord:
        artifacts = self.kernel.runtime.artifacts
        dossier = artifacts.get_json(manifest.release_dossier_ref, ReleaseDossier)
        context = artifacts.get_json(dossier.context_ref, GenerationContext)
        from agent_world.builder.service import BuilderError

        try:
            reservation = self.registry.reserve_package_version(
                manifest.package_id,
                manifest.version,
                context.job_ref,
            )
            if reservation.status == "consumed":
                record = self.registry.require_released_manifest(manifest_ref)
                if record.reservation_id != reservation.reservation_id:
                    raise LeafExecutionFailure(
                        code="preflight_registry_consumed_reservation_mismatch",
                        category="consumed reservation does not bind this exact manifest",
                    )
                return record
            candidate = artifacts.get_json(manifest.candidate_ref, EnvironmentCandidate)
            source_root = self.builder.materialize_exact_candidate(
                candidate=candidate,
                candidate_ref=manifest.candidate_ref,
                workspace=self.workspace_root / attempt_id,
            )
            framework_payloads = self._framework_payloads(manifest)
            prepared = self.registry.prepare(
                candidate_workspace=source_root,
                manifest_ref=manifest_ref,
                judge_report_ref=manifest.judge_report_ref,
                release_profile=context.release_profile,
                reservation=reservation,
                framework_payloads=framework_payloads,
            )
            return self.registry.publish(prepared)
        except LeafExecutionFailure:
            raise
        except (BuilderError, OSError) as exc:
            raise LeafExecutionFailure(
                code="registry_candidate_snapshot_materialization_failed",
                category="exact Candidate cannot be restored for Registry staging",
            ) from exc
        except Exception as exc:
            raise LeafExecutionFailure(
                code="registry_publication_error",
                category=type(exc).__name__,
            ) from exc

    def _framework_payloads(
        self,
        manifest: EnvironmentPackageManifest,
    ) -> tuple[FrameworkPackagePayload, ...]:
        """Reconstruct exact framework bytes from the immutable manifest inputs.

        Registry receives payload bytes rather than opaque paths.  Recompiling
        them deterministically from the same closure means a Scheduler restart
        cannot accidentally stage a Controller workspace or a newer candidate.
        """

        artifacts = self.kernel.runtime.artifacts
        design = artifacts.get_json(manifest.design_ref, EnvironmentDesign)
        candidate_manifest = artifacts.get_json(
            manifest.candidate_manifest_ref,
            CandidateManifest,
        )
        judge = artifacts.get_json(manifest.judge_report_ref, JudgeReport)
        integration = artifacts.get_json(manifest.integration_report_ref, IntegrationReport)
        lineage = manifest.lineage
        candidate = artifacts.get_json(manifest.candidate_ref, EnvironmentCandidate)
        from agent_world.builder.service import BuilderError

        try:
            source_root = self.builder.materialize_exact_candidate(
                candidate=candidate,
                candidate_ref=manifest.candidate_ref,
                workspace=self.workspace_root / "payload-rebuild",
            )
            return compile_framework_package_payloads(
                design,
                package_id=manifest.package_id,
                version=manifest.version,
                candidate_manifest=candidate_manifest,
                judge_report=judge,
                integration_report=integration,
                lineage=lineage,
                design_ref=manifest.design_ref,
                world_spec_ref=manifest.world_spec_ref,
                candidate_ref=manifest.candidate_ref,
                candidate_manifest_ref=manifest.candidate_manifest_ref,
                build_record_ref=manifest.build_record_ref,
                implementation_lineage_ref=manifest.implementation_lineage_ref,
                judge_report_ref=manifest.judge_report_ref,
                integration_report_ref=manifest.integration_report_ref,
                release_dossier_ref=manifest.release_dossier_ref,
                telemetry_summary_ref=manifest.telemetry_summary_ref,
                pyproject_bytes=(source_root / "pyproject.toml").read_bytes(),
                uv_lock_bytes=(source_root / "uv.lock").read_bytes(),
            )
        except (BuilderError, OSError) as exc:
            raise LeafExecutionFailure(
                code="registry_framework_payload_rebuild_failed",
                category="exact envpkg framework payloads cannot be reconstructed",
            ) from exc


__all__ = ["ObservabilityLeaf", "PackageLeaf", "RegistryPublicationLeaf"]
