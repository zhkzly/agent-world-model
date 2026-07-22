"""Pre-package release evidence assembled from active final-graph commits."""

from __future__ import annotations

from pydantic import model_validator

from agent_world.artifact_store import ArtifactWriter
from agent_world.contracts import (
    ArtifactRef,
    GenerationContext,
    Identifier,
    ReleaseProfile,
    V2Contract,
)

from .work import WorkAttempt, WorkCommit
from .work_graph import GenerationWorkGraph, WorkGraphEpoch, WorkGraphManifest
from .work_store import WorkControlStore, WorkResumeError


class ReleaseDossier(V2Contract):
    """Framework-authored pre-package closure with no readiness/package cycle.

    It is deliberately distinct from Registry's later physical publication
    receipt.  Every reference describes work that has already committed before
    package assembly; there is no Manifest, reservation, Package WorkCommit or
    readiness snapshot in this record.
    """

    dossier_id: Identifier
    context_ref: ArtifactRef
    final_epoch_ref: ArtifactRef
    final_manifest_ref: ArtifactRef
    design_ref: ArtifactRef
    candidate_ref: ArtifactRef
    candidate_manifest_ref: ArtifactRef
    build_record_ref: ArtifactRef
    implementation_lineage_ref: ArtifactRef
    verifier_ref: ArtifactRef
    integration_report_ref: ArtifactRef
    judge_report_ref: ArtifactRef
    telemetry_summary_ref: ArtifactRef
    prepackage_commit_refs: tuple[ArtifactRef, ...]
    release_profile: ReleaseProfile

    @model_validator(mode="after")
    def validate_closure(self) -> ReleaseDossier:
        expected_types = {
            "context_ref": "control.generation_context",
            "final_epoch_ref": "control.work_graph_epoch",
            "final_manifest_ref": "control.work_graph_manifest",
            "design_ref": "design.environment_design",
            "candidate_ref": "build.environment_candidate",
            "candidate_manifest_ref": "build.candidate_manifest",
            "build_record_ref": "build.record",
            "implementation_lineage_ref": "build.implementation_lineage",
            "verifier_ref": "judge.verifier_ir_projection",
            "integration_report_ref": "judge.integration_report",
            "judge_report_ref": "judge_report",
            "telemetry_summary_ref": "release.telemetry_summary",
        }
        if any(
            getattr(self, field).artifact_type != artifact_type
            for field, artifact_type in expected_types.items()
        ):
            raise ValueError("ReleaseDossier contains a reference with the wrong artifact type")
        if not self.prepackage_commit_refs or any(
            ref.artifact_type != "control.work_commit" for ref in self.prepackage_commit_refs
        ):
            raise ValueError("ReleaseDossier requires exact pre-package WorkCommits")
        if len(set(self.prepackage_commit_refs)) != len(self.prepackage_commit_refs):
            raise ValueError("ReleaseDossier WorkCommit refs must be unique")
        return self


class ReleaseDossierCompiler:
    """Build a dossier only from active commits in a final frozen graph."""

    _REQUIRED_COORDINATES = {
        ("design", "modeling_boundary"),
        ("build", "candidate_build"),
        ("verifier", "verifier_intent"),
        ("integration", "runtime_integration"),
        ("judge", "release_assurance"),
        ("release", "observability_closure"),
    }

    def __init__(self, *, artifacts: ArtifactWriter, heads: WorkControlStore) -> None:
        self.artifacts = artifacts
        self.heads = heads

    def compile(
        self,
        *,
        final_epoch_ref: ArtifactRef,
        graph: GenerationWorkGraph,
        manifest_ref: ArtifactRef,
        design_ref: ArtifactRef,
        candidate_ref: ArtifactRef,
        candidate_manifest_ref: ArtifactRef,
        build_record_ref: ArtifactRef,
        implementation_lineage_ref: ArtifactRef,
        verifier_ref: ArtifactRef,
        integration_report_ref: ArtifactRef,
        judge_report_ref: ArtifactRef,
        telemetry_summary_ref: ArtifactRef,
        release_profile: ReleaseProfile,
    ) -> tuple[ReleaseDossier, ArtifactRef]:
        if graph.mode != "production" or not graph.release_eligible:
            raise WorkResumeError("ReleaseDossier requires the complete final production graph")
        epoch = self.artifacts.get_json(final_epoch_ref, WorkGraphEpoch)
        manifest = self.artifacts.get_json(manifest_ref, WorkGraphManifest)
        if (
            final_epoch_ref.artifact_type != "control.work_graph_epoch"
            or epoch.epoch_kind != "final"
            or epoch.manifest_ref != manifest_ref
            or manifest.releasable is not True
            or manifest.graph_digest
            != graph.manifest(
                topology_id=manifest.topology_id,
                external_root_refs=manifest.external_root_refs,
            ).graph_digest
        ):
            raise WorkResumeError("ReleaseDossier graph epoch does not bind the final topology")
        if manifest.external_root_refs != (epoch.context_ref,):
            raise WorkResumeError("final WorkGraph must have only its GenerationContext root")
        self.artifacts.get_json(epoch.context_ref, GenerationContext)
        commits = self._require_prepackage_commits(graph)
        outputs = {
            key: self.artifacts.get_json(commit_ref, WorkCommit).consumer_refs
            for key, commit_ref in commits.items()
        }
        expected_outputs = {
            ("design", "modeling_boundary"): (design_ref,),
            (
                "build",
                "candidate_build",
            ): (
                candidate_ref,
                candidate_manifest_ref,
                build_record_ref,
                implementation_lineage_ref,
            ),
            ("verifier", "verifier_intent"): (verifier_ref,),
            ("integration", "runtime_integration"): (integration_report_ref,),
            ("judge", "release_assurance"): (judge_report_ref,),
            ("release", "observability_closure"): (telemetry_summary_ref,),
        }
        for key, refs in expected_outputs.items():
            if not set(refs) <= set(outputs[key]):
                raise WorkResumeError(
                    "ReleaseDossier inputs are not outputs of their exact active WorkCommit"
                )
        dossier = ReleaseDossier(
            dossier_id=f"release-dossier:{manifest.graph_digest.removeprefix('sha256:')[:24]}",
            context_ref=epoch.context_ref,
            final_epoch_ref=final_epoch_ref,
            final_manifest_ref=manifest_ref,
            design_ref=design_ref,
            candidate_ref=candidate_ref,
            candidate_manifest_ref=candidate_manifest_ref,
            build_record_ref=build_record_ref,
            implementation_lineage_ref=implementation_lineage_ref,
            verifier_ref=verifier_ref,
            integration_report_ref=integration_report_ref,
            judge_report_ref=judge_report_ref,
            telemetry_summary_ref=telemetry_summary_ref,
            prepackage_commit_refs=tuple(commits.values()),
            release_profile=release_profile,
        )
        dossier_ref = self.artifacts.put_json(
            artifact_id=dossier.dossier_id,
            artifact_type="release.dossier",
            value=dossier,
            dependencies=(
                epoch.context_ref,
                final_epoch_ref,
                manifest_ref,
                *dossier.prepackage_commit_refs,
                design_ref,
                candidate_ref,
                candidate_manifest_ref,
                build_record_ref,
                implementation_lineage_ref,
                verifier_ref,
                integration_report_ref,
                judge_report_ref,
                telemetry_summary_ref,
            ),
        )
        return dossier, dossier_ref

    def _require_prepackage_commits(
        self,
        graph: GenerationWorkGraph,
    ) -> dict[tuple[str, str], ArtifactRef]:
        commits: dict[tuple[str, str], ArtifactRef] = {}
        for definition in graph.topological_definitions():
            key = (definition.coordinate.component, definition.coordinate.stage)
            if key not in self._REQUIRED_COORDINATES:
                continue
            head = self.heads.read_head(definition.coordinate)
            if head is None or head.status != "committed":
                raise WorkResumeError("pre-package Work is not committed")
            attempt = self.artifacts.get_json(head.attempt_ref, WorkAttempt)
            active = self.heads.require_active_commit(
                definition=definition,
                input_refs=attempt.input_refs,
                artifacts=self.artifacts,
            )
            if active is None:
                raise WorkResumeError("pre-package WorkCommit is not active")
            commits[key] = active[1]
        if set(commits) != self._REQUIRED_COORDINATES:
            raise WorkResumeError("final graph omits a required pre-package commit")
        return commits


__all__ = ["ReleaseDossier", "ReleaseDossierCompiler"]
