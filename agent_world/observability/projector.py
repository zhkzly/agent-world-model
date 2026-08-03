"""Best-effort projector from durable WorkGraph facts to Tier A scenes."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Literal, TypeGuard

from agent_world.artifact_store import ArtifactStore, ArtifactWriter
from agent_world.builder.models import BuilderWorkspaceProgress, BuildRecord
from agent_world.builder.service import EnvironmentBuilder
from agent_world.contracts import (
    ArtifactRef,
    Budget,
    EnvironmentCandidate,
    canonical_json_bytes,
    sha256_digest,
)
from agent_world.control.telemetry import (
    INVOCATION_ACTIVITY_CLASSES,
    TelemetryStore,
    invocation_activity_metric_name,
)
from agent_world.control.work import (
    FeedbackEvaluation,
    OperationRun,
    ProposalExecution,
    ValidationIssue,
    ValidationReport,
    WorkAttempt,
    classify_progress,
    work_input_fingerprint,
)
from agent_world.control.work_graph import WorkGraphManifest
from agent_world.control.work_store import WorkControlHead, WorkControlStore
from agent_world.invocation import InvocationControlRecord, InvocationControlStore

from .paths import ObservabilityError, ObservabilityRoot
from .render import render_coordinate, render_scene
from .scene import (
    MAX_WATERMARK_COORDINATES,
    ActiveWorkPointer,
    BudgetAdmissionDimension,
    BudgetExhaustion,
    CandidateWorkspaceLiveness,
    CodexTerminalEnvelope,
    FrontierProgress,
    InvocationLivenessPhase,
    OperationPhase,
    PipelineStage,
    RepairAuthority,
    RunSceneIndex,
    RuntimeAgentActivityCounts,
    RuntimeAgentLiveness,
    RuntimeAgentRequestShape,
    Scene,
    SceneHead,
    SceneIssue,
    SceneTierBEvent,
    active_work_digest,
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
        invocation_control: InvocationControlStore | None = None,
        known_secret_canaries: Sequence[str | bytes] = (),
    ) -> None:
        self.root = root
        self.artifacts = artifacts
        self.heads = heads
        self.telemetry = telemetry
        self.invocation_control = invocation_control
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
        observed_at = datetime.now(UTC)
        scene_heads = tuple(
            self._scene_head(
                head,
                attempt=attempt,
                graph_digest=graph_digest,
                run_id=run_id,
                observed_at=observed_at,
            )
            for head, attempt in zip(heads, attempts, strict=True)
        )
        events = self._tier_b_events(
            tuple(attempt.telemetry_trace_id or run_id for attempt in attempts)
        )
        active_work = self._active_work(scope_id, heads)
        scene = fold(scene_heads, events, active_work=active_work)
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
                    for (
                        coordinate_key,
                        revision,
                        status,
                        attempt_ref_revision,
                    ) in expected_coordinates
                )
            )
        )
        active_work = self._active_work(scope_id, heads)
        return (
            cached_coordinates == expected_visible
            and cached.watermark.coordinate_overflow_count
            == max(0, len(expected_coordinates) - len(expected_visible))
            and cached.watermark.aggregate_digest == expected_aggregate
            and cached.watermark.graph_digest == self._graph_digest(scope_id, ordered)
            and cached.watermark.active_work_digest == active_work_digest(active_work)
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
        observed_at: datetime,
    ) -> SceneHead:
        attempt = attempt or self.artifacts.get_json(head.attempt_ref, WorkAttempt)
        # A causal parent repair keeps the original committed attempt as the
        # head's physical lineage, while ``evaluation_ref`` names the new
        # target-local proxy report that actually authorized the next turn.
        # Showing the old passing report made the project-execution Agent see
        # ``repair_authorized`` with no issues and incorrectly focus on the
        # failed descendant instead of the permitted Builder repair.
        report = self._repair_authorization_report(head) or self._validation_report(attempt)
        candidate_files = self.candidate_files_for_attempt(attempt)
        previous_reports = self._previous_validation_reports(
            attempt,
            policy_digest=(report.policy_digest if report is not None else None),
        )
        prior_issue_ids = previous_reports[-1].blocking_issue_ids if previous_reports else ()
        source_run_id = run_id or attempt.telemetry_trace_id
        issues = tuple(
            self._scene_issue(issue, candidate_files=candidate_files)
            for issue in (report.issues if report is not None else ())
            if issue.severity == "blocker"
        )
        (
            last_completed_phase,
            terminal_failure_phase,
            terminal_failure_elapsed_ms,
        ) = self._operation_timing(attempt)
        runtime_agent_liveness = self._runtime_agent_liveness(attempt)
        runtime_agent_request_shape = self._runtime_agent_request_shape(attempt)
        attempt_elapsed_ms, attempt_elapsed_estimated = _attempt_elapsed_ms(
            attempt,
            observed_at=observed_at,
        )
        first_progress_elapsed_ms = _elapsed_ms(
            attempt.started_at,
            attempt.first_progress_at,
        )
        if first_progress_elapsed_ms is None and runtime_agent_liveness is not None:
            first_progress_elapsed_ms = runtime_agent_liveness.first_progress_elapsed_ms
        candidate_workspace_liveness = self._candidate_workspace_liveness(
            attempt,
            source_run_id=source_run_id,
        )
        budget_exhaustion = self._budget_exhaustion(attempt, report)
        codex_terminal_envelope = self._codex_terminal_envelope(attempt, report)
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
            frontier_progress=self._frontier_progress(report, previous_reports),
            run_id=self._safe(source_run_id) if source_run_id is not None else None,
            graph_digest=graph_digest,
            updated_at=head.updated_at,
            attempt_elapsed_ms=attempt_elapsed_ms,
            attempt_elapsed_estimated=attempt_elapsed_estimated,
            first_progress_elapsed_ms=first_progress_elapsed_ms,
            last_completed_phase=last_completed_phase,
            terminal_failure_phase=terminal_failure_phase,
            terminal_failure_elapsed_ms=terminal_failure_elapsed_ms,
            runtime_agent_liveness=runtime_agent_liveness,
            codex_terminal_envelope=codex_terminal_envelope,
            runtime_agent_request_shape=runtime_agent_request_shape,
            candidate_workspace_liveness=candidate_workspace_liveness,
            budget_exhaustion=budget_exhaustion,
        )

    def _active_work(
        self,
        scope_id: str,
        heads: Sequence[WorkControlHead],
    ) -> tuple[ActiveWorkPointer, ...]:
        """Aggregate live control records without leaking private invocation data.

        A WorkControlHead is updated after a Scheduler transition, whereas an
        InvocationControlRecord is written before dispatch.  During a retry,
        that gap is expected: the durable head can still say ``failed`` or
        ``repair_authorized`` while a successor physical turn is actually
        running.  The top-level Scene must show both facts.
        """

        if self.invocation_control is None:
            return ()
        labels = {
            head.coordinate.coordinate_key: self._safe(
                f"{head.coordinate.component}.{head.coordinate.stage}.{head.coordinate.artifact_slot}"
            )
            for head in heads
        }
        try:
            records = self.invocation_control.list_records()
        except Exception:
            return ()
        grouped: dict[str, list[InvocationControlRecord]] = {}
        for record in records:
            coordinate_key = record.owner.coordinate
            if (
                record.settled
                or record.owner.owner_kind.value != "work_operation"
                or record.owner.scope_id != scope_id
                or coordinate_key not in labels
            ):
                continue
            grouped.setdefault(coordinate_key, []).append(record)
        active: list[ActiveWorkPointer] = []
        for coordinate_key, grouped_records in grouped.items():
            routes = {item.route for item in grouped_records}
            route: Literal["codex_sdk", "direct_llm", "mixed"] = (
                "codex_sdk"
                if routes == {"codex_sdk"}
                else "direct_llm" if routes == {"direct_llm"} else "mixed"
            )
            activity_times = tuple(
                item.last_provider_progress_at
                or item.last_local_activity_at
                or item.updated_at
                for item in grouped_records
            )
            first_provider_times = tuple(
                item.first_provider_progress_at
                for item in grouped_records
                if item.first_provider_progress_at is not None
            )
            active.append(
                ActiveWorkPointer(
                    coordinate_key=coordinate_key,
                    coordinate_label=labels[coordinate_key],
                    route=route,
                    active_turn_count=len(grouped_records),
                    provider_progress_count=sum(
                        item.provider_progress_count for item in grouped_records
                    ),
                    started_at=min(item.started_at for item in grouped_records),
                    last_activity_at=max(activity_times),
                    first_provider_progress_at=(
                        min(first_provider_times) if first_provider_times else None
                    ),
                )
            )
        return tuple(sorted(active, key=lambda item: (item.started_at, item.coordinate_key)))

    def _operation_timing(
        self,
        attempt: WorkAttempt,
    ) -> tuple[OperationPhase | None, OperationPhase | None, int | None]:
        """Return only durable, bounded timing facts for the current attempt."""

        completed: list[OperationRun] = []
        for reference in attempt.operation_run_refs:
            try:
                operation = self.artifacts.get_json(reference, OperationRun)
            except ValueError:
                # Projection remains best-effort. A malformed historical
                # operation cannot make the durable Work head disappear.
                continue
            if operation.status == "terminal" and operation.finished_at is not None:
                completed.append(operation)
        if not completed:
            return None, None, None
        last_completed = max(completed, key=_finished_at)
        failures = tuple(operation for operation in completed if operation.error_code is not None)
        if not failures:
            return last_completed.kind, None, None
        terminal_failure = max(failures, key=_finished_at)
        return (
            last_completed.kind,
            terminal_failure.kind,
            _elapsed_ms(terminal_failure.started_at, terminal_failure.finished_at),
        )

    def _runtime_agent_liveness(self, attempt: WorkAttempt) -> RuntimeAgentLiveness | None:
        """Project safe liveness for every physical turn of one proposal operation.

        Telemetry remains the richer primary source when it contains one exact
        span.  A durable invocation-control record is the fallback when a
        worker exited or a parent recovered before telemetry could materialize
        a usable terminal span.  Neither path exposes prompt, response,
        endpoint, private session, or workspace data.

        A Code Agent may legitimately use a bounded same-workspace pre-commit
        correction.  Those are multiple *physical* InvocationBackend calls
        beneath one Scheduler Proposal operation, so the operation ownership
        (rather than only its first dispatch id) is the fence for the control
        projection.  This keeps a live second turn observable without turning
        it into a Scheduler repair or leaking private invocation identities.
        """

        control_records = self._control_records_for_attempt(attempt)
        control_liveness = self._control_runtime_agent_liveness(
            attempt,
            records=control_records,
        )
        if not control_records:
            # Older/synthetic telemetry-only states and a newly started
            # operation before control admission still retain one exact
            # dispatch fence.  Preserve that established telemetry path; the
            # ownership aggregate is an enhancement, not a prerequisite for
            # observing a live Agent turn.
            invocation_id = self._proposal_invocation_id(attempt)
            if invocation_id is None:
                return None
            return self._telemetry_runtime_agent_liveness(attempt, invocation_id)
        # A one-turn proposal still benefits from the richer telemetry activity
        # breakdown.  With several records, the control aggregate is the only
        # unambiguous view: a per-invocation telemetry span must not be
        # double-counted or arbitrarily selected.
        if len(control_records) != 1:
            return control_liveness
        telemetry_liveness = self._telemetry_runtime_agent_liveness(
            attempt,
            control_records[0].invocation_id,
        )
        if telemetry_liveness is None:
            return control_liveness
        if control_liveness is None:
            return telemetry_liveness
        return _merge_runtime_agent_liveness(telemetry_liveness, control_liveness)

    def _telemetry_runtime_agent_liveness(
        self,
        attempt: WorkAttempt,
        invocation_id: str,
    ) -> RuntimeAgentLiveness | None:
        """Return the richer trace projection when its exact span is available."""

        if self.telemetry is None or attempt.telemetry_trace_id is None:
            return None
        try:
            trace = self.telemetry.inspect_trace(attempt.telemetry_trace_id)
        except Exception:
            return None
        expected_invocation_hash = sha256_digest(invocation_id.encode("utf-8"))
        matches: list[dict[str, object]] = []
        for raw_span in trace.get("spans", ()):  # type: ignore[union-attr]
            if not isinstance(raw_span, dict):
                continue
            if (
                raw_span.get("component") != "invocation"
                or raw_span.get("operation") != "agent.invoke"
            ):
                continue
            try:
                attributes = json.loads(str(raw_span.get("attributes_json", "{}")))
            except (TypeError, ValueError):
                continue
            if not isinstance(attributes, dict):
                continue
            if attributes.get("invocation_id_hash") != expected_invocation_hash:
                continue
            matches.append(raw_span)
        # An invocation id is a one-physical-turn identity.  A duplicate span
        # would be an observability defect, not a license to fabricate a
        # liveness summary from ambiguous evidence.
        if len(matches) != 1:
            return None
        span = matches[0]
        started_elapsed_ms = _elapsed_from_attempt_ns(attempt.started_at, span.get("started_at_ns"))
        if started_elapsed_ms is None:
            return None
        span_id = span.get("span_id")
        if not isinstance(span_id, str):
            return None
        event_count, activity = self._invocation_event_counts(
            trace.get("metrics", ()),  # type: ignore[union-attr]
            span_id=span_id,
        )
        return RuntimeAgentLiveness(
            started_elapsed_ms=started_elapsed_ms,
            first_progress_elapsed_ms=_elapsed_from_attempt_ns(
                attempt.started_at,
                span.get("first_progress_at_ns"),
            ),
            last_progress_elapsed_ms=_elapsed_from_attempt_ns(
                attempt.started_at,
                span.get("last_progress_at_ns"),
            ),
            last_local_heartbeat_elapsed_ms=_elapsed_from_attempt_ns(
                attempt.started_at,
                span.get("last_heartbeat_at_ns"),
            ),
            last_local_heartbeat_phase=_direct_liveness_phase(span.get("last_heartbeat_phase")),
            terminal_elapsed_ms=_elapsed_from_attempt_ns(
                attempt.started_at,
                span.get("ended_at_ns"),
            ),
            observed_event_count=event_count,
            activity=activity,
        )

    def _control_runtime_agent_liveness(
        self,
        attempt: WorkAttempt,
        *,
        records: tuple[InvocationControlRecord, ...] | None = None,
    ) -> RuntimeAgentLiveness | None:
        """Project redacted control facts after exact Work ownership checks."""

        records = records if records is not None else self._control_records_for_attempt(attempt)
        if not records:
            return None
        started = tuple(
            elapsed
            for record in records
            if (elapsed := _elapsed_ms(attempt.started_at, record.started_at)) is not None
        )
        if not started:
            return None
        first_progress = tuple(
            elapsed
            for record in records
            if (
                elapsed := _elapsed_ms(
                    attempt.started_at,
                    record.first_provider_progress_at,
                )
            )
            is not None
        )
        last_progress = tuple(
            elapsed
            for record in records
            if (
                elapsed := _elapsed_ms(
                    attempt.started_at,
                    record.last_provider_progress_at,
                )
            )
            is not None
        )
        heartbeats = tuple(
            (elapsed, _control_liveness_phase(record.last_local_phase.value))
            for record in records
            if (
                elapsed := _elapsed_ms(
                    attempt.started_at,
                    record.last_local_activity_at,
                )
            )
            is not None
        )
        terminal = tuple(
            elapsed
            for record in records
            if record.settled
            and (elapsed := _elapsed_ms(attempt.started_at, record.updated_at)) is not None
        )
        latest_heartbeat = max(heartbeats, key=lambda item: item[0], default=None)
        return RuntimeAgentLiveness(
            started_elapsed_ms=min(started),
            first_progress_elapsed_ms=min(first_progress) if first_progress else None,
            last_progress_elapsed_ms=max(last_progress) if last_progress else None,
            last_local_heartbeat_elapsed_ms=(
                latest_heartbeat[0] if latest_heartbeat is not None else None
            ),
            last_local_heartbeat_phase=(
                latest_heartbeat[1] if latest_heartbeat is not None else None
            ),
            terminal_elapsed_ms=max(terminal) if terminal else None,
            observed_event_count=sum(record.provider_progress_count for record in records),
        )

    def _runtime_agent_request_shape(
        self,
        attempt: WorkAttempt,
    ) -> RuntimeAgentRequestShape | None:
        """Project safe request dimensions only from an exact control record.

        A telemetry trace may be absent precisely when a Direct stream emitted
        no first Provider event.  The durable control-plane record is therefore
        the authoritative source for request-shape comparison, but never for
        raw Prompt/Skill/schema content.
        """

        records = tuple(
            record
            for record in self._control_records_for_attempt(attempt)
            if record.request_shape is not None
        )
        if not records:
            return None
        # The latest physical turn is the effective request currently being
        # executed (or whose result became the accepted Candidate); it is also
        # the only request shape a project-execution Agent needs to compare
        # against the preceding scene.
        record = max(records, key=lambda item: (item.updated_at, item.invocation_id))
        shape = record.request_shape
        if shape is None:  # pragma: no cover - filtered above
            return None
        return RuntimeAgentRequestShape(
            prompt_bytes=shape.prompt_bytes,
            runtime_skill_count=shape.runtime_skill_count,
            output_schema_bytes=shape.output_schema_bytes,
            allowed_builtin_tool_count=shape.allowed_builtin_tool_count,
            execution_mode=shape.execution_mode,
            continued_session=shape.continued_session,
        )

    def _control_records_for_attempt(
        self,
        attempt: WorkAttempt,
    ) -> tuple[InvocationControlRecord, ...]:
        """Return all exact physical records owned by one Proposal operation.

        The Work operation id and immutable input fingerprint are the durable
        fence.  An invocation id alone cannot identify a bounded internal
        Code-Agent correction because its second turn intentionally has a new
        physical id.
        """

        if self.invocation_control is None:
            return ()
        try:
            operations = tuple(
                self.artifacts.get_json(reference, OperationRun)
                for reference in attempt.operation_run_refs
            )
        except Exception:
            return ()
        proposal_operations = tuple(item for item in operations if item.kind == "proposal")
        if len(proposal_operations) != 1:
            return ()
        operation = proposal_operations[0]
        expected_closure = work_input_fingerprint(operation.input_refs).removeprefix("sha256:")
        try:
            records = self.invocation_control.list_records()
        except Exception:
            return ()
        return tuple(
            record
            for record in records
            if record.owner.owner_kind.value == "work_operation"
            and record.owner.owner_id == operation.operation_run_id
            and record.owner.scope_id == attempt.coordinate.scope_id
            and record.owner.coordinate == attempt.coordinate.coordinate_key
            and record.owner.immutable_input_closure_digest == expected_closure
        )

    def _control_record_belongs_to_attempt(
        self,
        owner_kind: str,
        owner_id: str,
        owner_scope_id: str,
        owner_coordinate: str | None,
        owner_input_closure_digest: str | None,
        attempt: WorkAttempt,
        invocation_id: str,
    ) -> bool:
        """Require the control record to match one exact proposal operation."""

        if (
            owner_kind != "work_operation"
            or owner_scope_id != attempt.coordinate.scope_id
            or owner_coordinate != attempt.coordinate.coordinate_key
            or owner_input_closure_digest is None
        ):
            return False
        matches: list[OperationRun] = []
        for reference in attempt.operation_run_refs:
            try:
                operation = self.artifacts.get_json(reference, OperationRun)
            except ValueError:
                continue
            if operation.kind != "proposal" or operation.dispatch_id != invocation_id:
                continue
            matches.append(operation)
        if len(matches) != 1:
            return False
        operation = matches[0]
        return (
            owner_id == operation.operation_run_id
            and owner_input_closure_digest
            == work_input_fingerprint(operation.input_refs).removeprefix("sha256:")
        )

    def _proposal_invocation_id(self, attempt: WorkAttempt) -> str | None:
        active: list[str] = []
        candidates: list[tuple[datetime, str]] = []
        for reference in attempt.operation_run_refs:
            try:
                operation = self.artifacts.get_json(reference, OperationRun)
            except ValueError:
                continue
            if operation.kind != "proposal":
                continue
            if operation.status == "running" and operation.dispatch_id is not None:
                active.append(operation.dispatch_id)
                continue
            if (
                operation.status != "terminal"
                or operation.execution_ref is None
                or operation.finished_at is None
            ):
                continue
            try:
                execution = self.artifacts.get_json(operation.execution_ref, ProposalExecution)
            except ValueError:
                continue
            invocation_id = execution.invocation_id
            if (
                invocation_id is None
                and execution.executor == "agent"
                and execution.status == "interrupted"
                and execution.error_code is not None
                and execution.error_code.startswith("process_interrupted")
            ):
                # Pre-v2 recovery records could lose the invocation field even
                # though the terminal OperationRun retained the immutable
                # Scheduler dispatch fence.  An Agent leaf uses that exact
                # dispatch id for its physical InvocationRequest, so this is
                # evidence recovery—not a guessed provider/session identity.
                invocation_id = operation.dispatch_id
            if invocation_id is not None:
                candidates.append((operation.finished_at, invocation_id))
        # A running WorkAttempt has exactly one active OperationRun.  Keeping
        # this explicit protects a scene from attributing a sibling invocation
        # if malformed historical state ever contains more than one.
        if len(active) == 1:
            return active[0]
        if active or not candidates:
            return None
        return max(candidates, key=lambda item: item[0])[1]

    @staticmethod
    def _invocation_event_counts(
        metrics: object,
        *,
        span_id: str,
    ) -> tuple[int, RuntimeAgentActivityCounts | None]:
        if not isinstance(metrics, (list, tuple)):
            return 0, None
        event_metric = "invocation.events.observed_delta"
        activity_metric_to_class = {
            invocation_activity_metric_name(activity): activity
            for activity in INVOCATION_ACTIVITY_CLASSES
        }
        event_count = 0
        activity_counts = {activity: 0 for activity in INVOCATION_ACTIVITY_CLASSES}
        activity_available = False
        for metric in metrics:
            if not isinstance(metric, dict) or metric.get("span_id") != span_id:
                continue
            name = metric.get("name")
            if name != event_metric and name not in activity_metric_to_class:
                continue
            value = metric.get("value_integer")
            if not _nonnegative_int(value):
                continue
            if name == event_metric:
                event_count += value
                continue
            activity_available = True
            activity_counts[activity_metric_to_class[name]] += value
        if not activity_available:
            return event_count, None
        return event_count, RuntimeAgentActivityCounts(
            reasoning_event_count=activity_counts["reasoning"],
            agent_message_event_count=activity_counts["agent_message"],
            command_event_count=activity_counts["command"],
            file_change_event_count=activity_counts["file_change"],
            tool_event_count=activity_counts["tool"],
            other_event_count=activity_counts["other"],
            unclassified_event_count=activity_counts["unclassified"],
        )

    def _candidate_workspace_liveness(
        self,
        attempt: WorkAttempt,
        *,
        source_run_id: str | None,
    ) -> CandidateWorkspaceLiveness | None:
        """Read the newest content-free Builder heartbeat for one attempt.

        The first lookup uses the canonical run/attempt identity.  The fallback
        covers a historical scene rebuilt after a controller changed its run-id
        projection, while still requiring an exact durable attempt id.
        """

        references: tuple[ArtifactRef, ...] = ()
        if source_run_id is not None:
            artifact_id = EnvironmentBuilder.workspace_progress_artifact_id(
                source_run_id,
                attempt.attempt_id,
            )
            references = self.artifacts.list_revisions(artifact_id)
        if not references:
            references = tuple(
                reference
                for reference in self.artifacts.list_revisions()
                if reference.artifact_type == "build.workspace_progress"
                and reference.artifact_id.endswith(f":workspace-progress:{attempt.attempt_id}")
            )
        candidates: list[BuilderWorkspaceProgress] = []
        for reference in references:
            if reference.artifact_type != "build.workspace_progress":
                continue
            try:
                progress = self.artifacts.get_json(reference, BuilderWorkspaceProgress)
            except ValueError:
                continue
            if progress.attempt_id != attempt.attempt_id:
                continue
            if attempt.started_at is not None and progress.observed_at < attempt.started_at:
                continue
            candidates.append(progress)
        if not candidates:
            return None
        progress = max(candidates, key=lambda item: item.observed_at)
        observed_elapsed_ms = _elapsed_ms(attempt.started_at, progress.observed_at)
        if observed_elapsed_ms is None:
            return None
        changed = max(
            (item for item in candidates if item.status == "changed"),
            key=lambda item: item.observed_at,
            default=None,
        )
        return CandidateWorkspaceLiveness(
            status=progress.status,
            observed_elapsed_ms=observed_elapsed_ms,
            last_changed_elapsed_ms=(
                _elapsed_ms(attempt.started_at, changed.observed_at)
                if changed is not None
                else None
            ),
            file_count=progress.file_count,
            total_bytes=progress.total_bytes,
            error_code=(
                self._safe(progress.error_code) if progress.error_code is not None else None
            ),
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
            remediation=(self._safe(issue.remediation) if issue.remediation is not None else None),
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

    def _repair_authorization_report(
        self,
        head: WorkControlHead,
    ) -> ValidationReport | None:
        """Return the exact target-local report behind an authorized repair.

        This is a read-only projection aid, never repair authority.  The
        Runtime has already bound ``head.evaluation_ref`` to the RepairAction;
        we merely surface its safe blocker diagnostics in the project Agent's
        compact scene.
        """

        if head.status != "repair_authorized" or head.evaluation_ref is None:
            return None
        evaluation = self.artifacts.get_json(head.evaluation_ref, FeedbackEvaluation)
        if evaluation.coordinate != head.coordinate or evaluation.validation_report_ref is None:
            return None
        report = self.artifacts.get_json(
            evaluation.validation_report_ref,
            ValidationReport,
        )
        if report.coordinate != head.coordinate or report.attempt_id != evaluation.attempt_id:
            return None
        return report

    def _budget_exhaustion(
        self,
        attempt: WorkAttempt,
        report: ValidationReport | None,
    ) -> BudgetExhaustion | None:
        """Project only typed pre-admission facts from the terminal evidence.

        A failed operation has its own durable ``OperationRun`` and must not be
        summarized as though the model never ran.  This projection is therefore
        available only for the Scheduler-owned terminal evidence and explicitly
        reports whether *this attempt* had opened any operation at all.
        """

        if attempt.failure_code != "budget_exhausted" or report is None:
            return None
        evidence_refs = tuple(
            ref
            for ref in report.evidence_refs
            if ref.artifact_type == "control.budget_exhaustion_evidence"
        )
        if len(evidence_refs) != 1:
            return None
        try:
            evidence = self.artifacts.get_json(evidence_refs[0])
        except ValueError:
            return None
        if not isinstance(evidence, dict):
            return None
        if (
            evidence.get("attempt_id") != attempt.attempt_id
            or evidence.get("failure_code") != "budget_exhausted"
        ):
            return None
        dimensions = evidence.get("exhausted_dimensions")
        allowed_dimensions = set(Budget.model_fields) - {"schema_version"}
        if (
            not isinstance(dimensions, list)
            or not dimensions
            or any(
                not isinstance(dimension, str) or dimension not in allowed_dimensions
                for dimension in dimensions
            )
        ):
            return None
        normalized_dimensions = tuple(sorted(set(dimensions)))
        if tuple(dimensions) != normalized_dimensions:
            return None
        raw_admission = evidence.get("admission")
        if raw_admission is None:
            admission: tuple[BudgetAdmissionDimension, ...] = ()
        elif not isinstance(raw_admission, list):
            return None
        else:
            try:
                admission = tuple(
                    BudgetAdmissionDimension.model_validate(item) for item in raw_admission
                )
            except ValueError:
                return None
            if tuple(item.dimension for item in admission) != normalized_dimensions:
                return None
        return BudgetExhaustion(
            exhausted_dimensions=normalized_dimensions,
            admission=admission,
            during_authorized_repair=attempt.repair_action_ref is not None,
            operation_not_started=not attempt.operation_run_refs,
        )

    def _codex_terminal_envelope(
        self,
        attempt: WorkAttempt,
        report: ValidationReport | None,
    ) -> CodexTerminalEnvelope | None:
        """Project one verified closed Codex terminal fact for investigation.

        This is deliberately not generic feedback.  A Code Agent cannot act
        on an app-server terminal envelope, and no provider prose is useful or
        safe in a project view.  The compact fact lets the project-execution
        Agent distinguish a known terminal category from a missing/opaque
        envelope before choosing a D-layer investigation.
        """

        if report is None or report.status != "error" or len(report.issues) != 1:
            return None
        failure_code = report.issues[0].code
        if not failure_code.startswith("turn_failed_"):
            return None
        evidence_refs = tuple(
            ref
            for ref in report.evidence_refs
            if ref.artifact_type == "control.leaf_failure_evidence"
        )
        if len(evidence_refs) != 1:
            return None
        try:
            evidence = self.artifacts.get_json(evidence_refs[0])
        except ValueError:
            return None
        if not isinstance(evidence, Mapping):
            return None
        if (
            evidence.get("attempt_id") != attempt.attempt_id
            or evidence.get("failure_code") != failure_code
            or evidence.get("coordinate") != report.coordinate.model_dump(mode="json")
        ):
            return None
        details = evidence.get("terminal_details")
        if not isinstance(details, Mapping):
            return None
        candidate: dict[str, object] = {}
        for key in ("terminal_error_shape", "codex_error_info"):
            value = details.get(key)
            if isinstance(value, str):
                candidate[key] = value
        http_status = details.get("http_status")
        if isinstance(http_status, int) and not isinstance(http_status, bool):
            candidate["http_status"] = http_status
        advisory_signals = details.get("advisory_text_signals")
        if isinstance(advisory_signals, list) and all(
            isinstance(signal, str) for signal in advisory_signals
        ):
            candidate["advisory_text_signals"] = tuple(advisory_signals)
        if not candidate:
            return None
        try:
            return CodexTerminalEnvelope.model_validate(candidate)
        except ValueError:
            # The Artifact is Tier B input.  A malformed or newly introduced
            # value must disappear from the compact Agent view rather than
            # becoming raw dynamic text or a speculative new repair route.
            return None

    def _previous_validation_reports(
        self,
        attempt: WorkAttempt,
        *,
        policy_digest: str | None,
    ) -> tuple[ValidationReport, ...]:
        """Return the durable prior report lineage for one coordinate.

        The control plane's progress lattice needs the earlier states to
        distinguish genuine sibling progress from A -> B -> A oscillation.
        A scene must project that result, not infer authority from a raw issue
        count or only the last pair of identifiers.
        """

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
        reports = tuple(
            report
            for candidate in sorted(
                candidates,
                key=lambda item: (item.finished_at or item.scheduled_at, item.ordinal),
            )
            if (report := self._validation_report(candidate)) is not None
            and (policy_digest is None or report.policy_digest == policy_digest)
        )
        return reports

    @staticmethod
    def _frontier_progress(
        report: ValidationReport | None,
        previous_reports: tuple[ValidationReport, ...],
    ) -> FrontierProgress | None:
        """Map the authoritative repair classification into the scene vocabulary.

        This is a read-only projection.  It grants no repair authority; that
        remains exclusively in the WorkRepairLedger.  Returning ``None`` asks
        the pure scene reducer to use its conservative fallback when no exact
        same-policy lineage is available.
        """

        if report is None or not previous_reports:
            return None
        previous = previous_reports[-1]
        if (
            previous.coordinate != report.coordinate
            or previous.policy_digest != report.policy_digest
            or any(
                item.coordinate != report.coordinate or item.policy_digest != report.policy_digest
                for item in previous_reports
            )
        ):
            return None
        classification = classify_progress(
            previous,
            report,
            history=previous_reports[:-1],
        )
        if classification == "resolved":
            return "resolved"
        if classification == "strict_progress":
            return "strict_progress"
        if classification in {"unchanged", "oscillating", "regressed"}:
            return "no_progress"
        return "unknown"

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
                events.append(SceneTierBEvent(event_type=event_type, coordinate_key=coordinate_key))
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


def _elapsed_ms(started_at: datetime | None, finished_at: datetime | None) -> int | None:
    """Return a bounded projection fact, never a live clock calculation."""

    if started_at is None or finished_at is None:
        return None
    return max(0, round((finished_at - started_at).total_seconds() * 1_000))


def _attempt_elapsed_ms(
    attempt: WorkAttempt,
    *,
    observed_at: datetime,
) -> tuple[int | None, bool]:
    """Return terminal elapsed time or one labelled running-time estimate.

    The estimate deliberately uses the one rebuild checkpoint rather than an
    invented scheduler snapshot.  It is presentation-only Tier A data and is
    never reused for budget settlement, timeout enforcement, or release.
    """

    if attempt.started_at is None:
        return None, False
    if attempt.finished_at is not None:
        return _elapsed_ms(attempt.started_at, attempt.finished_at), False
    if attempt.status == "running":
        return _elapsed_ms(attempt.started_at, observed_at), True
    return None, False


def _elapsed_from_attempt_ns(started_at: datetime | None, observed_at_ns: object) -> int | None:
    """Project a telemetry wall-clock instant relative to one WorkAttempt."""

    if started_at is None or not _nonnegative_int(observed_at_ns):
        return None
    started_at_ns = round(started_at.timestamp() * 1_000_000_000)
    return max(0, round((observed_at_ns - started_at_ns) / 1_000_000))


def _merge_runtime_agent_liveness(
    telemetry: RuntimeAgentLiveness,
    control: RuntimeAgentLiveness,
) -> RuntimeAgentLiveness:
    """Combine two exact, redacted views without treating a heartbeat as progress."""

    telemetry_heartbeat = (
        telemetry.last_local_heartbeat_elapsed_ms,
        telemetry.last_local_heartbeat_phase,
    )
    control_heartbeat = (
        control.last_local_heartbeat_elapsed_ms,
        control.last_local_heartbeat_phase,
    )
    latest_heartbeat = max(
        (telemetry_heartbeat, control_heartbeat),
        key=lambda item: item[0] if item[0] is not None else -1,
    )
    return RuntimeAgentLiveness(
        started_elapsed_ms=min(telemetry.started_elapsed_ms, control.started_elapsed_ms),
        first_progress_elapsed_ms=_earliest_elapsed(
            telemetry.first_progress_elapsed_ms,
            control.first_progress_elapsed_ms,
        ),
        last_progress_elapsed_ms=_latest_elapsed(
            telemetry.last_progress_elapsed_ms,
            control.last_progress_elapsed_ms,
        ),
        last_local_heartbeat_elapsed_ms=latest_heartbeat[0],
        last_local_heartbeat_phase=latest_heartbeat[1],
        terminal_elapsed_ms=_latest_elapsed(
            telemetry.terminal_elapsed_ms,
            control.terminal_elapsed_ms,
        ),
        observed_event_count=max(
            telemetry.observed_event_count,
            control.observed_event_count,
        ),
        activity=telemetry.activity,
    )


def _earliest_elapsed(*values: int | None) -> int | None:
    observed = tuple(value for value in values if value is not None)
    return min(observed) if observed else None


def _latest_elapsed(*values: int | None) -> int | None:
    observed = tuple(value for value in values if value is not None)
    return max(observed) if observed else None


_CONTROL_LIVENESS_PHASE_BY_VALUE: dict[str, InvocationLivenessPhase] = {
    "queued": "queued",
    "admitted": "admitted",
    "profile_verifying": "profile_verifying",
    "profile_verified": "profile_verified",
    "worker_spawned": "worker_spawned",
    "payload_dispatched": "payload_dispatched",
    "sdk_session_open": "sdk_session_open",
    "thread_start": "thread_start",
    "thread_resume": "thread_resume",
    "turn_start": "turn_start",
    "turn_stream": "turn_stream",
    "parent_waiting": "parent_waiting",
    "worker_exited": "worker_exited",
    "direct_request_dispatched": "direct_request_dispatched",
    "direct_dispatched": "direct_dispatched",
    "direct_awaiting_response": "direct_awaiting_response",
    "direct_stream_opened": "direct_stream_opened",
    "direct_awaiting_stream_event": "direct_awaiting_stream_event",
    "cancel_requested": "cancel_requested",
    "declared_wall_expired": "declared_wall_expired",
    "cleanup_running": "cleanup_running",
    "cleanup_finished": "cleanup_finished",
    "terminal_received": "terminal_received",
    "owner_lost": "owner_lost",
}


def _control_liveness_phase(value: object) -> InvocationLivenessPhase | None:
    """Keep only closed framework lifecycle labels in the project Agent view."""

    return _CONTROL_LIVENESS_PHASE_BY_VALUE.get(value) if isinstance(value, str) else None


def _direct_liveness_phase(value: object) -> InvocationLivenessPhase | None:
    """Keep only the closed local wait phases that are safe in a scene."""

    return _control_liveness_phase(value)


def _nonnegative_int(value: object) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _finished_at(operation: OperationRun) -> datetime:
    """Return the timestamp guaranteed by the terminal-operation filter."""

    if operation.finished_at is None:
        raise ValueError("terminal operation is missing finished_at")
    return operation.finished_at


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
