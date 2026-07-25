"""Best-effort projector from durable WorkGraph facts to Tier A scenes."""

from __future__ import annotations

import json
from collections.abc import Sequence

from agent_world.artifact_store import ArtifactStore, ArtifactWriter
from agent_world.builder.models import BuildRecord
from agent_world.contracts import EnvironmentCandidate, canonical_json_bytes, sha256_digest
from agent_world.control.telemetry import TelemetryStore
from agent_world.control.work import ValidationIssue, ValidationReport, WorkAttempt
from agent_world.control.work_graph import WorkGraphManifest
from agent_world.control.work_store import WorkControlHead, WorkControlStore

from .paths import ObservabilityError, ObservabilityRoot
from .render import render_coordinate, render_scene
from .scene import (
    MAX_WATERMARK_COORDINATES,
    PipelineStage,
    RepairAuthority,
    RunSceneIndex,
    Scene,
    SceneHead,
    SceneIssue,
    SceneTierBEvent,
    fold,
)
from .subprocess_scene import safe_dynamic_text

_PIPELINE_STAGE_BY_COMPONENT: dict[str, PipelineStage] = {
    "research": "Research",
    "design": "Designer",
    "build": "Builder",
    "integration": "Integration",
    "judge": "Judge",
    "verifier": "Judge",
    "release": "Registry",
    "registry": "Registry",
}
_SINGLE_FILE_GATE_ROLES: dict[str, str] = {
    "runtime_protocol": "runtime",
    "task_materialization": "task_materializer",
    "public_self_check": "public_verifier",
    "task_reachability": "runtime",
    "behavior": "runtime",
    "sealed_release": "runtime",
}
_MULTI_FILE_GATES = frozenset({"supply_chain", "static_assurance", "clean_deployment"})
_GATE_STATUSES = ("pass", "fail", "inconclusive", "error")


class SceneProjector:
    """Materialize a non-authoritative scene without changing WorkAttempt flow."""

    def __init__(
        self,
        *,
        root: ObservabilityRoot,
        artifacts: ArtifactStore | ArtifactWriter,
        heads: WorkControlStore,
        telemetry: TelemetryStore | None = None,
        known_secret_canaries: Sequence[str | bytes] = (),
    ) -> None:
        self.root = root
        self.artifacts = artifacts
        self.heads = heads
        self.telemetry = telemetry
        self.known_secret_canaries = tuple(known_secret_canaries)

    def project_attempt(self, *, attempt: WorkAttempt, run_id: str | None = None) -> None:
        """Project one post-CAS attempt transition, swallowing every failure.

        The durable head and artifact writes have already happened by the time
        this method is called.  Losing this cache must therefore never alter a
        scheduler transition or turn into a WorkAttempt failure.
        """

        try:
            self._project_attempt(attempt=attempt, run_id=run_id)
        except Exception as exc:
            self._record_projection_failure(attempt, exc)

    def _project_attempt(self, *, attempt: WorkAttempt, run_id: str | None) -> None:
        scene = self.rebuild(attempt.coordinate.scope_id, run_id=run_id)
        self._append_current_frontier(scene, attempt)

    def rebuild(self, scope_id: str, *, run_id: str | None = None) -> Scene:
        """Re-fold one scope from durable heads and Tier B facts.

        This is deliberately the same cold-input reducer used by the eager
        hook.  It has no scheduler side effects; the only writes are
        replaceable Tier A cache files.
        """

        heads = self.heads.read_scope_heads(scope_id)
        if not heads:
            raise ObservabilityError(
                "no durable WorkAttempt heads exist for this scope",
                code="observability_scope_not_found",
            )
        graph_digest = self._graph_digest(scope_id, heads)
        attempts = tuple(self.artifacts.get_json(head.attempt_ref, WorkAttempt) for head in heads)
        scene_heads = tuple(
            self._scene_head(
                head,
                attempt=attempt,
                graph_digest=graph_digest,
                run_id=run_id,
            )
            for head, attempt in zip(heads, attempts, strict=True)
        )
        events = self._tier_b_events(
            tuple(
                attempt.telemetry_trace_id or run_id
                for attempt in attempts
            )
        )
        scene = fold(scene_heads, events)
        self._materialize(scene)
        return scene

    def watermark_matches(self, scope_id: str, cached: RunSceneIndex) -> bool:
        """Check a cached map against every durable head before trusting it."""

        heads = self.heads.read_scope_heads(scope_id)
        if not heads or cached.scope_id != self.safe_scope_id(scope_id):
            return False
        ordered = tuple(sorted(heads, key=lambda item: item.coordinate.coordinate_key))
        expected_coordinates = tuple(
            (
                item.coordinate.coordinate_key,
                item.revision,
                item.status,
                item.attempt_ref.revision_id,
            )
            for item in ordered
        )
        cached_coordinates = tuple(
            (
                item.coordinate_key,
                item.revision,
                item.status,
                item.attempt_ref_revision,
            )
            for item in cached.watermark.coordinates
        )
        expected_visible = expected_coordinates[:MAX_WATERMARK_COORDINATES]
        expected_aggregate = sha256_digest(
            canonical_json_bytes(
                tuple(
                    {
                        "coordinate_key": coordinate_key,
                        "revision": revision,
                        "status": status,
                        "attempt_ref_revision": attempt_ref_revision,
                    }
                    for coordinate_key, revision, status, attempt_ref_revision
                    in expected_coordinates
                )
            )
        )
        return (
            cached_coordinates == expected_visible
            and cached.watermark.coordinate_overflow_count
            == max(0, len(expected_coordinates) - len(expected_visible))
            and cached.watermark.aggregate_digest == expected_aggregate
            and cached.watermark.graph_digest == self._graph_digest(scope_id, ordered)
        )

    def safe_scope_id(self, scope_id: str) -> str:
        """Return the only safe scope representation permitted in Tier A paths."""

        return self._safe(scope_id)

    def _materialize(self, scene: Scene) -> None:
        # ``scope_id`` is a stable control-plane identifier, but it can still
        # be caller supplied.  Folded scene values have already gone through
        # ``_safe``; use that same value for the Tier A directory name rather
        # than letting an otherwise redacted canary leak through a path.
        scene_scope_id = scene.index.scope_id
        self.root.write_scene(
            scene_scope_id,
            scene.index,
            render_scene(scene.index, scene.coordinates),
        )
        for coordinate in scene.coordinates:
            self.root.write_coordinate(
                scene_scope_id,
                coordinate,
                render_coordinate(coordinate),
            )
        self.root.update_index(scene.index)

    def _append_current_frontier(
        self,
        scene: Scene,
        attempt: WorkAttempt,
    ) -> None:
        for record in scene.frontier_records:
            if (
                record.coordinate_key == attempt.coordinate.coordinate_key
                and record.attempt_ordinal == attempt.ordinal
            ):
                self.root.append_frontier_once(scene.index.scope_id, record)
                return

    def _scene_head(
        self,
        head: WorkControlHead,
        *,
        attempt: WorkAttempt | None = None,
        graph_digest: str,
        run_id: str | None,
    ) -> SceneHead:
        attempt = attempt or self.artifacts.get_json(head.attempt_ref, WorkAttempt)
        report = self._validation_report(attempt)
        candidate_files = self.candidate_files_for_attempt(attempt)
        prior_issue_ids = self._previous_issue_ids(attempt)
        source_run_id = run_id or attempt.telemetry_trace_id
        issues = tuple(
            self._scene_issue(issue, candidate_files=candidate_files)
            for issue in (report.issues if report is not None else ())
            if issue.severity == "blocker"
        )
        coordinate = head.coordinate
        return SceneHead(
            scope_id=self._safe(head.scope_id),
            coordinate_key=coordinate.coordinate_key,
            coordinate_label=self._safe(
                f"{coordinate.component}.{coordinate.stage}.{coordinate.artifact_slot}"
            ),
            head_status=head.status,
            revision=head.revision,
            attempt_ref_revision=head.attempt_ref.revision_id,
            attempt_ref_id=self._safe(head.attempt_ref.artifact_id),
            attempt_ordinal=attempt.ordinal,
            failure_code=(self._safe(attempt.failure_code) if attempt.failure_code else None),
            validation_status=(report.status if report is not None else None),
            routes_repair_to_parent=self._routes_repair_to_parent(report),
            frontier_ordinal=(report.frontier_ordinal if report is not None else 0),
            pipeline_stage=_PIPELINE_STAGE_BY_COMPONENT.get(coordinate.component, "Registry"),
            repair_authority=self._repair_authority(head, attempt, report),
            input_fingerprint=head.input_fingerprint,
            issues=issues,
            previous_issue_ids=prior_issue_ids,
            run_id=self._safe(source_run_id) if source_run_id is not None else None,
            graph_digest=graph_digest,
            updated_at=head.updated_at,
        )

    def _scene_issue(
        self,
        issue: ValidationIssue,
        *,
        candidate_files: dict[str, str],
    ) -> SceneIssue:
        gate_id = _gate_id(issue.code)
        multi_file_gate = gate_id in _MULTI_FILE_GATES
        candidate_file = (
            candidate_files.get(gate_id) if gate_id is not None and not multi_file_gate else None
        )
        return SceneIssue(
            normalized_identity=issue.normalized_identity,
            code=self._safe(issue.code),
            path=tuple(self._safe(part) if isinstance(part, str) else part for part in issue.path),
            violated_condition=self._safe(issue.violated_condition),
            expected_category=self._safe(issue.expected_category),
            severity=issue.severity,
            actionable=issue.actionable,
            gate_id=gate_id,
            candidate_file=(self._safe(candidate_file) if candidate_file is not None else None),
            multi_file_gate=multi_file_gate,
        )

    def _validation_report(self, attempt: WorkAttempt) -> ValidationReport | None:
        if attempt.validation_report_ref is None:
            return None
        return self.artifacts.get_json(attempt.validation_report_ref, ValidationReport)

    def _previous_issue_ids(self, attempt: WorkAttempt) -> tuple[str, ...]:
        if attempt.parent_attempt_id is None:
            return ()
        candidates: list[WorkAttempt] = []
        for ref in self.artifacts.list_revisions(attempt.parent_attempt_id):
            if ref.artifact_type != "control.work_attempt":
                continue
            candidate = self.artifacts.get_json(ref, WorkAttempt)
            if (
                candidate.coordinate == attempt.coordinate
                and candidate.ordinal < attempt.ordinal
                and candidate.validation_report_ref is not None
                and candidate.finished_at is not None
            ):
                candidates.append(candidate)
        if not candidates:
            return ()
        previous = max(
            candidates,
            key=lambda item: (item.finished_at or item.scheduled_at, item.ordinal),
        )
        report = self._validation_report(previous)
        if report is None:
            return ()
        return tuple(
            sorted(
                issue.normalized_identity for issue in report.issues if issue.severity == "blocker"
            )
        )

    def candidate_files_for_attempt(self, attempt: WorkAttempt) -> dict[str, str]:
        """Resolve only declared generated files from gate id -> role -> BuildRecord.

        ``subject_refs`` are intentionally never considered: failed leaf paths
        commonly leave them empty and ArtifactRef has no source-file path.
        Multi-file gates deliberately remain absent so the reducer emits a
        needs-human target instead of inventing an editable filename.
        """

        candidate_refs = tuple(
            ref for ref in attempt.input_refs if ref.artifact_type == "build.environment_candidate"
        )
        if len(candidate_refs) != 1:
            return {}
        candidate = self.artifacts.get_json(candidate_refs[0], EnvironmentCandidate)
        record = self.artifacts.get_json(candidate.build_artifact_ref, BuildRecord)

        paths_by_role: dict[str, str] = {}
        runtime_paths = tuple(item.path for item in record.files if item.role == "runtime")
        if len(runtime_paths) == 1:
            paths_by_role["runtime"] = runtime_paths[0]
        for role, entry_path in (
            ("task_materializer", candidate.task_materializer.entry_path),
            ("public_verifier", candidate.public_self_check.entry_path),
        ):
            matches = tuple(
                item.path for item in record.files if item.role == role and item.path == entry_path
            )
            if len(matches) == 1:
                paths_by_role[role] = matches[0]
        return {
            gate_id: paths_by_role[role]
            for gate_id, role in _SINGLE_FILE_GATE_ROLES.items()
            if role in paths_by_role
        }

    def candidate_file_for_attempt(self, attempt: WorkAttempt) -> str | None:
        """Return one exact editable source path, or no path when it is ambiguous.

        A Judge coordinate can fail several gates.  The reader must not pick a
        file merely because it is convenient: only a single failed single-file
        gate is actionable, while multi-file or mixed failures stay honest.
        """

        report = self._validation_report(attempt)
        if report is None:
            return None
        by_gate = self.candidate_files_for_attempt(attempt)
        paths = {
            by_gate[gate_id]
            for issue in report.issues
            if issue.severity == "blocker"
            for gate_id in (_gate_id(issue.code),)
            if gate_id is not None and gate_id not in _MULTI_FILE_GATES and gate_id in by_gate
        }
        return next(iter(paths)) if len(paths) == 1 else None

    def _graph_digest(self, scope_id: str, heads: tuple[WorkControlHead, ...]) -> str:
        head_keys = {item.coordinate.coordinate_key for item in heads}
        candidates: list[tuple[int, str]] = []
        for ref in self.artifacts.list_revisions():
            if ref.artifact_type != "control.work_graph_manifest":
                continue
            try:
                manifest = self.artifacts.get_json(ref, WorkGraphManifest)
            except Exception:
                manifest = None
            if manifest is None:
                continue
            manifest_keys = {item.coordinate.coordinate_key for item in manifest.node_bindings}
            if manifest.scope_id == scope_id and head_keys <= manifest_keys:
                candidates.append((len(manifest_keys), manifest.graph_digest))
        if candidates:
            return max(candidates, key=lambda item: (item[0], item[1]))[1]
        return sha256_digest(
            canonical_json_bytes(
                tuple(
                    {
                        "coordinate_key": head.coordinate.coordinate_key,
                        "definition_digest": head.definition_digest,
                    }
                    for head in sorted(heads, key=lambda item: item.coordinate.coordinate_key)
                )
            )
        )

    def _tier_b_events(self, trace_ids: Sequence[str | None]) -> tuple[SceneTierBEvent, ...]:
        if self.telemetry is None:
            return ()
        events: list[SceneTierBEvent] = []
        for trace_id in sorted({item for item in trace_ids if item}):
            try:
                rows = self.telemetry.inspect_trace(trace_id)["events"]
            except Exception:
                rows = ()
            for row in rows:
                event_type = row.get("event_type")
                if not isinstance(event_type, str):
                    continue
                coordinate_key: str | None = None
                try:
                    payload = json.loads(str(row.get("payload_json", "{}")))
                except (TypeError, ValueError):
                    payload = {}
                raw_coordinate_key = (
                    payload.get("coordinate_key") if isinstance(payload, dict) else None
                )
                if isinstance(raw_coordinate_key, str) and raw_coordinate_key.startswith("sha256:"):
                    coordinate_key = raw_coordinate_key
                events.append(
                    SceneTierBEvent(event_type=event_type, coordinate_key=coordinate_key)
                )
        return tuple(events)

    def _record_projection_failure(self, attempt: WorkAttempt, exc: Exception) -> None:
        if self.telemetry is None or attempt.telemetry_trace_id is None:
            return
        try:
            self.telemetry.record_event(
                trace_id=attempt.telemetry_trace_id,
                span_id=attempt.telemetry_span_id,
                event_type="observability_projection_failed",
                payload={
                    "error_class": type(exc).__name__,
                    "coordinate_key": attempt.coordinate.coordinate_key,
                },
            )
            self.telemetry.flush()
        except Exception:
            return

    def _routes_repair_to_parent(self, report: ValidationReport | None) -> bool:
        """Whether this terminal report handed its repair to an ancestor.

        ``SchedulerLeafExecutor`` commits a ``control.parent_repair_route``
        artifact exactly when a leaf declared a ``parent_repair_target``.  Its
        presence is therefore the authoritative statement that the defect is not
        owned by the coordinate that produced the rejected output; its absence
        means the proposal itself is the repair subject.
        """

        if report is None:
            return False
        return any(
            ref.artifact_type == "control.parent_repair_route" for ref in report.evidence_refs
        )

    def _repair_authority(
        self,
        head: WorkControlHead,
        attempt: WorkAttempt,
        report: ValidationReport | None,
    ) -> RepairAuthority:
        if head.status == "repair_authorized":
            return "authorized"
        if head.status == "needs_human":
            return "needs_human"
        if attempt.repair_action_ref is not None and head.status == "running":
            return "in_progress"
        if report is not None and report.repair_actionable and head.status == "running":
            return "eligible"
        return "none"

    def _safe(self, value: str) -> str:
        return safe_dynamic_text(
            value,
            known_secret_canaries=self.known_secret_canaries,
        )


def _gate_id(code: str) -> str | None:
    stage, marker, remainder = code.partition("_gate_")
    if not marker or not stage:
        return None
    for status in _GATE_STATUSES:
        suffix = f"_{status}"
        if remainder.endswith(suffix):
            gate_id = remainder.removesuffix(suffix)
            if gate_id:
                return gate_id
    return None


__all__ = ["SceneProjector"]
