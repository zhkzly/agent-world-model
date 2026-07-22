"""Production telemetry and reproducible experiment snapshots.

This module is an internal Controller mechanism, not a sixth Foundry component.
It records operational facts without granting telemetry any workflow or release
authority.  High-frequency data uses SQLite WAL with bounded batched commits;
release-relevant facts remain signed ArtifactStore events owned elsewhere.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import time
import uuid
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast

from agent_world.contracts import ArtifactRef, canonical_json_bytes, sha256_digest
from agent_world.invocation.contracts import InvocationRequest, InvocationResult
from agent_world.invocation.redaction import Redactor
from agent_world.research.models import ResearchBundle

type ComponentName = Literal[
    "controller",
    "designer",
    "builder",
    "judge",
    "registry",
    "research",
    "invocation",
    "consumer",
    "expansion",
]
type TelemetryStatus = Literal[
    "running",
    "passed",
    "failed",
    "error",
    "cancelled",
    "timed_out",
    "budget_exhausted",
    "needs_human",
    "unknown",
]
type UsageProvenance = Literal[
    "provider",
    "sdk",
    "framework",
    "derived",
    "estimated",
    "unknown",
]

_SCHEMA_VERSION = 1
_CURRENT_TRACE: ContextVar[tuple[str, str, str | None, str | None, str | None] | None] = ContextVar(
    "agent_world_telemetry_trace", default=None
)
_SENSITIVE_KEY_PARTS = (
    "api_key",
    "authorization",
    "bearer",
    "cookie",
    "credential",
    "evaluator_goal",
    "expected_state",
    "password",
    "prompt",
    "sealed",
    "secret",
    "token_value",
)


class TelemetryError(RuntimeError):
    """Telemetry persistence or contract failure."""


@dataclass(frozen=True, slots=True)
class MetricPoint:
    name: str
    value: int | float | None
    unit: str
    provenance: UsageProvenance
    labels: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.name or not self.unit:
            raise ValueError("metric name and unit must not be empty")
        if self.value is not None and isinstance(self.value, bool):
            raise ValueError("metric values cannot be boolean")
        _safe_mapping(self.labels)


@dataclass(slots=True)
class WorkSpan:
    """Live handle for one hierarchical unit of real framework work."""

    store: TelemetryStore
    span_id: str
    trace_id: str
    started_perf_ns: int
    first_progress_recorded: bool = False
    last_progress_perf_ns: int = 0
    pending_event_count: int = 0
    pending_tool_event_count: int = 0
    closed: bool = False

    def first_progress(self) -> None:
        if self.closed or self.first_progress_recorded:
            return
        self.store.mark_first_progress(self.span_id)
        self.first_progress_recorded = True
        self.last_progress_perf_ns = time.perf_counter_ns()

    def progress(self, method: str) -> None:
        """Record bounded provider liveness without persisting event payloads."""

        if self.closed:
            return
        self.pending_event_count += 1
        if "tool" in method.casefold():
            self.pending_tool_event_count += 1
        now = time.perf_counter_ns()
        should_flush = (
            not self.first_progress_recorded
            or self.pending_event_count >= 128
            or now - self.last_progress_perf_ns >= 5_000_000_000
        )
        if should_flush:
            self._flush_progress(now)

    def _flush_progress(self, now_perf_ns: int | None = None) -> None:
        if not self.pending_event_count:
            return
        points = [
            MetricPoint(
                "invocation.events.observed_delta",
                self.pending_event_count,
                "events",
                "sdk",
            )
        ]
        if self.pending_tool_event_count:
            points.append(
                MetricPoint(
                    "invocation.protocol_tool_events.observed_delta",
                    self.pending_tool_event_count,
                    "events",
                    "sdk",
                )
            )
        self.store.mark_progress(
            self.span_id,
            first=not self.first_progress_recorded,
            metrics=tuple(points),
        )
        self.first_progress_recorded = True
        self.pending_event_count = 0
        self.pending_tool_event_count = 0
        self.last_progress_perf_ns = now_perf_ns or time.perf_counter_ns()

    def metric(self, point: MetricPoint) -> None:
        if self.closed:
            raise TelemetryError("cannot append a metric to a closed WorkSpan")
        self.store.record_metrics(self.trace_id, self.span_id, (point,))

    def finish(
        self,
        *,
        status: TelemetryStatus,
        error_code: str | None = None,
        output_refs: Sequence[ArtifactRef] = (),
        metrics: Sequence[MetricPoint] = (),
    ) -> None:
        if self.closed:
            raise TelemetryError("WorkSpan is already closed")
        self._flush_progress()
        self.store.finish_span(
            self.span_id,
            status=status,
            duration_ns=max(0, time.perf_counter_ns() - self.started_perf_ns),
            error_code=error_code,
            output_refs=output_refs,
            metrics=metrics,
        )
        self.closed = True


class TelemetryStore:
    """Thread-safe SQLite WAL store for non-authoritative operational evidence."""

    def __init__(self, root: str | os.PathLike[str], *, commit_batch_size: int = 32) -> None:
        if commit_batch_size < 1:
            raise ValueError("commit_batch_size must be positive")
        requested = Path(root).expanduser()
        if requested.exists() and requested.is_symlink():
            raise TelemetryError("telemetry root cannot be a symlink")
        requested.mkdir(parents=True, exist_ok=True)
        if requested.is_symlink() or not requested.is_dir():
            raise TelemetryError("telemetry root must be a real directory")
        self.root = requested.resolve(strict=True)
        self._store_id = f"telemetry-store:{uuid.uuid4().hex}"
        self.database_path = self.root / "telemetry.sqlite"
        self.commit_batch_size = commit_batch_size
        self._lock = threading.RLock()
        self._pending = 0
        self._connection = sqlite3.connect(
            self.database_path,
            timeout=30,
            isolation_level="DEFERRED",
            check_same_thread=False,
        )
        self._connection.row_factory = sqlite3.Row
        self._configure()
        self._create_schema()

    def close(self) -> None:
        with self._lock:
            if self._connection is None:
                return
            self.flush()
            self._connection.close()
            self._connection = None  # type: ignore[assignment]
            active = _CURRENT_TRACE.get()
            if active is not None and active[0] == self._store_id:
                _CURRENT_TRACE.set(None)

    def flush(self) -> None:
        with self._lock:
            if self._connection is None:
                return
            started = time.perf_counter_ns()
            pending = self._pending
            self._connection.commit()
            self._pending = 0
            if pending:
                self._insert_health_uncommitted(
                    "telemetry.flush.duration_ms",
                    (time.perf_counter_ns() - started) / 1_000_000,
                    "ms",
                    labels={"batch_size": str(pending)},
                )
                self._connection.commit()

    def __enter__(self) -> TelemetryStore:
        return self

    def __exit__(self, _type: object, _value: object, _traceback: object) -> None:
        self.close()

    def start_span(
        self,
        *,
        trace_id: str,
        component: ComponentName,
        operation: str,
        parent_span_id: str | None = None,
        run_id: str | None = None,
        campaign_id: str | None = None,
        node: str | None = None,
        attempt: int = 1,
        repair_depth: int = 0,
        input_refs: Sequence[ArtifactRef] = (),
        scheduled_at_ns: int | None = None,
        attributes: Mapping[str, str | int | float | bool | None] | None = None,
    ) -> WorkSpan:
        if not trace_id or not operation or attempt < 1 or repair_depth < 0:
            raise ValueError("invalid WorkSpan identity or attempt metadata")
        safe_attributes = _safe_mapping(attributes or {})
        span_id = f"span:{uuid.uuid4().hex}"
        now_ns = time.time_ns()
        scheduled = scheduled_at_ns or now_ns
        input_json = _refs_json(input_refs)
        with self._lock:
            self._connection.execute(
                """
                INSERT INTO spans(
                    span_id, trace_id, parent_span_id, run_id, campaign_id,
                    component, node, operation, attempt, repair_depth, status,
                    scheduled_at_ns, started_at_ns, input_refs_json, attributes_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'running', ?, ?, ?, ?)
                """,
                (
                    span_id,
                    trace_id,
                    parent_span_id,
                    run_id,
                    campaign_id,
                    component,
                    node,
                    operation,
                    attempt,
                    repair_depth,
                    scheduled,
                    now_ns,
                    input_json,
                    _canonical_text(safe_attributes),
                ),
            )
            self._touch()
        return WorkSpan(
            store=self,
            span_id=span_id,
            trace_id=trace_id,
            started_perf_ns=time.perf_counter_ns(),
        )

    def activate_trace(
        self,
        *,
        trace_id: str,
        run_id: str | None = None,
        campaign_id: str | None = None,
        parent_span_id: str | None = None,
    ) -> None:
        """Bind trace identity to this async context and its child tasks."""

        if not trace_id:
            raise ValueError("trace_id must not be empty")
        _CURRENT_TRACE.set((self._store_id, trace_id, run_id, campaign_id, parent_span_id))

    def current_trace(
        self,
    ) -> tuple[str, str | None, str | None, str | None] | None:
        active = _CURRENT_TRACE.get()
        if active is None or active[0] != self._store_id:
            return None
        return active[1:]

    @contextmanager
    def span(self, **kwargs: Any) -> Iterator[WorkSpan]:
        handle = self.start_span(**kwargs)
        try:
            yield handle
        except BaseException as exc:
            handle.finish(status="error", error_code=type(exc).__name__)
            raise
        else:
            handle.finish(status="passed")

    def mark_first_progress(self, span_id: str) -> None:
        self.mark_progress(span_id, first=True)

    def mark_progress(
        self,
        span_id: str,
        *,
        first: bool = False,
        metrics: Sequence[MetricPoint] = (),
    ) -> None:
        """Update liveness and bounded deltas for an active WorkSpan."""

        now_ns = time.time_ns()
        with self._lock:
            cursor = self._connection.execute(
                """
                UPDATE spans
                SET first_progress_at_ns = CASE
                        WHEN ? THEN COALESCE(first_progress_at_ns, ?)
                        ELSE first_progress_at_ns
                    END,
                    last_progress_at_ns = ?
                WHERE span_id = ? AND status = 'running'
                """,
                (int(first), now_ns, now_ns, span_id),
            )
            if cursor.rowcount != 1:
                raise TelemetryError("cannot mark progress for a missing or closed WorkSpan")
            row = self._connection.execute(
                "SELECT trace_id FROM spans WHERE span_id = ?",
                (span_id,),
            ).fetchone()
            assert row is not None
            self._record_metrics_uncommitted(row["trace_id"], span_id, metrics)
            self._touch(1 + len(metrics))
        # Provider progress is a live-operability signal. Flush only the
        # WorkSpan-throttled samples, never every raw SDK event.
        self.flush()

    def finish_span(
        self,
        span_id: str,
        *,
        status: TelemetryStatus,
        duration_ns: int,
        error_code: str | None = None,
        output_refs: Sequence[ArtifactRef] = (),
        metrics: Sequence[MetricPoint] = (),
    ) -> None:
        if status == "running" or duration_ns < 0:
            raise ValueError("finished WorkSpan requires a terminal status and duration")
        with self._lock:
            cursor = self._connection.execute(
                """
                UPDATE spans
                SET status = ?, ended_at_ns = ?, duration_ns = ?, error_code = ?,
                    output_refs_json = ?
                WHERE span_id = ? AND status = 'running'
                """,
                (
                    status,
                    time.time_ns(),
                    duration_ns,
                    error_code,
                    _refs_json(output_refs),
                    span_id,
                ),
            )
            if cursor.rowcount != 1:
                raise TelemetryError("cannot finish a missing or closed WorkSpan")
            row = self._connection.execute(
                "SELECT trace_id FROM spans WHERE span_id = ?",
                (span_id,),
            ).fetchone()
            assert row is not None
            self._record_metrics_uncommitted(row["trace_id"], span_id, metrics)
            self._touch(1 + len(metrics))

    def record_metrics(
        self,
        trace_id: str,
        span_id: str | None,
        metrics: Sequence[MetricPoint],
    ) -> None:
        with self._lock:
            self._record_metrics_uncommitted(trace_id, span_id, metrics)
            self._touch(len(metrics))

    def record_event(
        self,
        *,
        trace_id: str,
        event_type: str,
        span_id: str | None = None,
        payload: Mapping[str, str | int | float | bool | None] | None = None,
    ) -> None:
        if not trace_id or not event_type:
            raise ValueError("telemetry event identity cannot be empty")
        safe_payload = _safe_mapping(payload or {})
        with self._lock:
            self._connection.execute(
                """
                INSERT INTO events(trace_id, span_id, event_type, recorded_at_ns, payload_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (trace_id, span_id, event_type, time.time_ns(), _canonical_text(safe_payload)),
            )
            self._touch()

    def record_invocation(
        self,
        request: InvocationRequest,
        result: InvocationResult,
        *,
        parent_span_id: str | None = None,
        queue_duration_ms: float = 0,
    ) -> str:
        """Persist one completed real InvocationBackend result without prompt content."""

        trace_id = _trace_id_for_invocation(request)
        span = self.start_span(
            trace_id=trace_id,
            component="invocation",
            operation="agent.invoke",
            parent_span_id=parent_span_id,
            run_id=_optional_metadata_string(request.metadata, "run_id"),
            campaign_id=_optional_metadata_string(request.metadata, "campaign_id"),
            node=_optional_metadata_string(request.metadata, "role"),
            attempt=max(1, _optional_metadata_int(request.metadata, "attempt") + 1),
            attributes={
                "invocation_id_hash": _hash_text(request.invocation_id),
                "lineage_id_hash": _hash_text(request.profile.lineage_id),
                "profile_hash": request.profile.profile_hash,
                "backend": request.profile.backend,
                "model": request.profile.model,
                "model_provider": request.profile.model_provider or "unknown",
                "reasoning_effort": request.profile.reasoning_effort.value,
                "continued_session": request.session is not None,
                "semantic_transaction": _optional_metadata_string(
                    request.metadata,
                    "semantic_transaction",
                )
                or "unknown",
                "repair_mode": _optional_metadata_string(
                    request.metadata,
                    "repair_mode",
                )
                or "initial",
                # Record only a scalar size.  The key deliberately avoids the
                # secret scanner's prompt marker so this safe aggregate cannot
                # disable the entire invocation span.
                "input_bytes": len(request.prompt.encode("utf-8")),
                "output_schema": request.profile.output_schema is not None,
            },
        )
        metrics = list(_invocation_metrics(request, result))
        metrics.append(
            MetricPoint(
                "invocation.queue.duration_ms",
                queue_duration_ms,
                "ms",
                "framework",
                {"role": request.profile.profile_id},
            )
        )
        status = cast(
            TelemetryStatus,
            {
                "completed": "passed",
                "failed": "failed",
                "needs_human": "needs_human",
                "timed_out": "timed_out",
                "cancelled": "cancelled",
                "budget_exhausted": "budget_exhausted",
            }[result.status.value],
        )
        span.finish(
            status=status,
            error_code=result.error.code if result.error else None,
            metrics=metrics,
        )
        # A long design node may contain many sequential Agent turns. Persist
        # each terminal turn without waiting for the enclosing node checkpoint.
        self.flush()
        return span.span_id

    def finish_invocation(
        self,
        span: WorkSpan,
        request: InvocationRequest,
        result: InvocationResult,
        *,
        queue_duration_ms: float,
    ) -> None:
        """Close a span started before backend capacity acquisition."""

        metrics = [
            *_invocation_metrics(request, result),
            MetricPoint(
                "invocation.queue.duration_ms",
                queue_duration_ms,
                "ms",
                "framework",
                {"role": request.profile.profile_id},
            ),
        ]
        status = cast(
            TelemetryStatus,
            {
                "completed": "passed",
                "failed": "failed",
                "needs_human": "needs_human",
                "timed_out": "timed_out",
                "cancelled": "cancelled",
                "budget_exhausted": "budget_exhausted",
            }[result.status.value],
        )
        span.finish(
            status=status,
            error_code=result.error.code if result.error else None,
            metrics=metrics,
        )
        self.flush()

    def start_invocation(self, request: InvocationRequest) -> WorkSpan:
        """Open a real-Agent span without recording prompt or output content."""

        current = self.current_trace()
        trace_id = _trace_id_for_invocation(request)
        run_id = _optional_metadata_string(request.metadata, "run_id")
        campaign_id = _optional_metadata_string(request.metadata, "campaign_id")
        parent_span_id = None
        if current is not None:
            trace_id = current[0]
            run_id = run_id or current[1]
            campaign_id = campaign_id or current[2]
            parent_span_id = current[3]
        span = self.start_span(
            trace_id=trace_id,
            component="invocation",
            operation="agent.invoke",
            parent_span_id=parent_span_id,
            run_id=run_id,
            campaign_id=campaign_id,
            node=_optional_metadata_string(request.metadata, "role"),
            attempt=max(1, _optional_metadata_int(request.metadata, "attempt") + 1),
            attributes={
                "invocation_id_hash": _hash_text(request.invocation_id),
                "lineage_id_hash": _hash_text(request.profile.lineage_id),
                "profile_hash": request.profile.profile_hash,
                "backend": request.profile.backend,
                "model": request.profile.model,
                "model_provider": request.profile.model_provider or "unknown",
                "reasoning_effort": request.profile.reasoning_effort.value,
                "continued_session": request.session is not None,
                "semantic_transaction": _optional_metadata_string(
                    request.metadata,
                    "semantic_transaction",
                )
                or "unknown",
                "repair_mode": _optional_metadata_string(
                    request.metadata,
                    "repair_mode",
                )
                or "initial",
                "input_bytes": len(request.prompt.encode("utf-8")),
                "output_schema": request.profile.output_schema is not None,
            },
        )
        # Invocation admission must be observable while the provider is still
        # running, including from a separate CLI process.
        self.flush()
        return span

    def record_research_bundle(
        self,
        *,
        trace_id: str,
        bundle: ResearchBundle,
        span_id: str | None = None,
    ) -> None:
        unique_urls = {hit.url for search in bundle.searches for hit in search.hits}
        raw_bytes = sum(len(item.source.body) for item in bundle.documents)
        extracted_bytes = sum(len(item.text.encode("utf-8")) for item in bundle.documents)
        points = (
            MetricPoint("research.search.calls", bundle.search_calls, "calls", "framework"),
            MetricPoint("research.fetch.calls", bundle.fetch_calls, "calls", "framework"),
            MetricPoint("research.extract.calls", bundle.extract_calls, "calls", "framework"),
            MetricPoint(
                "research.search.results",
                sum(len(item.hits) for item in bundle.searches),
                "items",
                "provider",
            ),
            MetricPoint("research.urls.unique", len(unique_urls), "items", "derived"),
            MetricPoint(
                "research.documents.extracted",
                len(bundle.documents),
                "documents",
                "framework",
            ),
            MetricPoint("research.failures", len(bundle.failures), "items", "framework"),
            MetricPoint("research.raw_bytes", raw_bytes, "bytes", "framework"),
            MetricPoint("research.extracted_bytes", extracted_bytes, "bytes", "framework"),
        )
        self.record_metrics(trace_id, span_id, points)

    def inspect_trace(self, trace_id: str) -> dict[str, Any]:
        """Return a stable aggregate plus raw span/metric rows for one trace."""

        with self._lock:
            self.flush()
            spans = [
                dict(row)
                for row in self._connection.execute(
                    "SELECT * FROM spans WHERE trace_id = ? ORDER BY started_at_ns, span_id",
                    (trace_id,),
                )
            ]
            metrics = [
                dict(row)
                for row in self._connection.execute(
                    "SELECT * FROM metrics WHERE trace_id = ? ORDER BY metric_id",
                    (trace_id,),
                )
            ]
            events = [
                dict(row)
                for row in self._connection.execute(
                    "SELECT * FROM events WHERE trace_id = ? ORDER BY event_id",
                    (trace_id,),
                )
            ]
        summary = _summarize_trace(spans, metrics, as_of_ns=time.time_ns())
        return {
            "schema_version": _SCHEMA_VERSION,
            "trace_id": trace_id,
            "summary": summary,
            "spans": spans,
            "metrics": metrics,
            "events": events,
        }

    def active_work(self, trace_id: str) -> tuple[dict[str, Any], ...]:
        """Project safe liveness signals for unfinished work.

        This projection is operational rather than release-authoritative.  It
        deliberately exposes neither prompts nor provider payloads, and token
        usage remains unknown until a terminal provider result is available.
        """

        with self._lock:
            self.flush()
            rows = [
                dict(row)
                for row in self._connection.execute(
                    """
                    SELECT span_id, parent_span_id, component, node, operation,
                           attempt, started_at_ns, first_progress_at_ns,
                           last_progress_at_ns
                    FROM spans
                    WHERE trace_id = ? AND status = 'running'
                    ORDER BY started_at_ns, span_id
                    """,
                    (trace_id,),
                )
            ]
            metric_rows = self._connection.execute(
                """
                SELECT span_id, name,
                       SUM(COALESCE(value_integer, value_real)) AS observed
                FROM metrics
                WHERE trace_id = ?
                  AND name IN (
                      'invocation.events.observed_delta',
                      'invocation.protocol_tool_events.observed_delta'
                  )
                GROUP BY span_id, name
                """,
                (trace_id,),
            ).fetchall()
        observed_by_span: dict[str, dict[str, int | float]] = {}
        for metric in metric_rows:
            if metric["span_id"] is None or metric["observed"] is None:
                continue
            observed_by_span.setdefault(str(metric["span_id"]), {})[
                str(metric["name"])
            ] = metric["observed"]
        now_ns = time.time_ns()
        return tuple(
            {
                **row,
                "elapsed_ms": max(0, now_ns - int(row["started_at_ns"])) / 1_000_000,
                "observed_event_count": observed_by_span.get(row["span_id"], {}).get(
                    "invocation.events.observed_delta", 0
                ),
                "observed_protocol_tool_event_count": observed_by_span.get(
                    row["span_id"], {}
                ).get(
                    "invocation.protocol_tool_events.observed_delta", 0
                ),
                "observed_token_count": None,
            }
            for row in rows
        )

    def reconcile_released_trace(
        self,
        trace_id: str,
        *,
        output_refs: Sequence[ArtifactRef],
    ) -> None:
        """Idempotently terminalize a trace after Registry proves publication."""

        if not trace_id:
            raise ValueError("trace_id cannot be empty")
        now_ns = time.time_ns()
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT span_id, parent_span_id, operation, started_at_ns
                FROM spans WHERE trace_id = ? AND status = 'running'
                ORDER BY started_at_ns, span_id
                """,
                (trace_id,),
            ).fetchall()
            roots = [
                row
                for row in rows
                if row["parent_span_id"] is None and row["operation"] == "direct.generate"
            ]
            if len(roots) > 1:
                raise TelemetryError("released trace contains multiple running Direct roots")
            root_ids = {str(row["span_id"]) for row in roots}
            for row in rows:
                is_root = str(row["span_id"]) in root_ids
                self._connection.execute(
                    """
                    UPDATE spans
                    SET status = ?, ended_at_ns = ?, duration_ns = ?, error_code = ?,
                        output_refs_json = ?
                    WHERE span_id = ? AND status = 'running'
                    """,
                    (
                        "passed" if is_root else "error",
                        now_ns,
                        max(0, now_ns - int(row["started_at_ns"])),
                        None if is_root else "post_publish_reconciliation",
                        _refs_json(output_refs if is_root else ()),
                        row["span_id"],
                    ),
                )
            self._touch(len(rows))
            self.flush()

    def reconcile_abandoned_trace(
        self,
        trace_id: str,
        *,
        error_code: str = "owner_process_interrupted",
    ) -> int:
        """Close spans left by a dead DirectJob owner before recovery starts.

        The caller must already hold the durable DirectJob writer lock. This
        is observability reconciliation only: it never cancels a live worker
        and it preserves the original span timing and provider metrics.
        """

        if not trace_id or not error_code:
            raise ValueError("trace recovery requires trace_id and error_code")
        now_ns = time.time_ns()
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT span_id, started_at_ns
                FROM spans
                WHERE trace_id = ? AND status = 'running'
                ORDER BY started_at_ns, span_id
                """,
                (trace_id,),
            ).fetchall()
            for row in rows:
                self._connection.execute(
                    """
                    UPDATE spans
                    SET status = 'error', ended_at_ns = ?, duration_ns = ?, error_code = ?
                    WHERE span_id = ? AND status = 'running'
                    """,
                    (
                        now_ns,
                        max(0, now_ns - int(row["started_at_ns"])),
                        error_code,
                        row["span_id"],
                    ),
                )
            self._touch(len(rows))
            self.flush()
        return len(rows)

    def summarize_traces(self, trace_ids: Sequence[str]) -> dict[str, Any]:
        """Aggregate comparable, credential-free experiment measures across runs."""

        unique_trace_ids = tuple(dict.fromkeys(trace_ids))
        if not unique_trace_ids:
            raise ValueError("trace summary requires at least one trace id")
        inspected = tuple(self.inspect_trace(trace_id) for trace_id in unique_trace_ids)
        per_trace = tuple(_trace_measurements(item) for item in inspected)
        measure_names = tuple(
            dict.fromkeys(
                name
                for item in per_trace
                for name in cast(dict[str, float | None], item["measurements"])
            )
        )
        return {
            "schema_version": _SCHEMA_VERSION,
            "trace_count": len(per_trace),
            "trace_ids": list(unique_trace_ids),
            "per_trace": list(per_trace),
            "distributions": {
                name: _numeric_distribution(
                    tuple(
                        cast(dict[str, float | None], item["measurements"]).get(name)
                        for item in per_trace
                    )
                )
                for name in measure_names
            },
        }

    def compare_traces(self, trace_ids: Sequence[str]) -> dict[str, Any]:
        """Compare each run with the first trace as an explicit baseline."""

        summary = self.summarize_traces(trace_ids)
        per_trace = cast(list[dict[str, Any]], summary["per_trace"])
        if len(per_trace) < 2:
            raise ValueError("trace comparison requires a baseline and at least one candidate")
        baseline = per_trace[0]
        baseline_measurements = cast(dict[str, float | None], baseline["measurements"])
        comparisons: list[dict[str, Any]] = []
        for candidate in per_trace[1:]:
            candidate_measurements = cast(
                dict[str, float | None],
                candidate["measurements"],
            )
            deltas: dict[str, dict[str, float | None]] = {}
            for name in dict.fromkeys((*baseline_measurements, *candidate_measurements)):
                baseline_value = baseline_measurements.get(name)
                candidate_value = candidate_measurements.get(name)
                absolute = (
                    candidate_value - baseline_value
                    if baseline_value is not None and candidate_value is not None
                    else None
                )
                relative = (
                    absolute / baseline_value * 100
                    if absolute is not None and baseline_value is not None and baseline_value != 0
                    else None
                )
                deltas[name] = {
                    "baseline": baseline_value,
                    "candidate": candidate_value,
                    "absolute_delta": absolute,
                    "relative_delta_percent": relative,
                }
            comparisons.append(
                {
                    "trace_id": candidate["trace_id"],
                    "deltas": deltas,
                }
            )
        return {
            "schema_version": _SCHEMA_VERSION,
            "baseline_trace_id": baseline["trace_id"],
            "comparisons": comparisons,
            "summary": summary,
        }

    def find_trace_ids(
        self,
        *,
        run_id: str | None = None,
        campaign_id: str | None = None,
    ) -> tuple[str, ...]:
        if (run_id is None) == (campaign_id is None):
            raise ValueError("select exactly one of run_id or campaign_id")
        column, value = ("run_id", run_id) if run_id is not None else ("campaign_id", campaign_id)
        with self._lock:
            rows = self._connection.execute(
                f"SELECT DISTINCT trace_id FROM spans WHERE {column} = ? ORDER BY trace_id",  # noqa: S608 - fixed column allowlist
                (value,),
            ).fetchall()
        return tuple(str(row[0]) for row in rows)

    def export_json(self, destination: str | os.PathLike[str], *, trace_id: str) -> Path:
        target = _safe_output_path(destination)
        payload = canonical_json_bytes(self.inspect_trace(trace_id)) + b"\n"
        _atomic_write(target, payload)
        return target

    def export_parquet(self, destination: str | os.PathLike[str], *, trace_id: str) -> Path:
        """Export normalized span/metric/event rows to one Parquet file.

        PyArrow is imported lazily so normal Foundry execution does not pay its
        import cost.  Missing export capability fails honestly; it never writes a
        JSON file with a parquet extension.
        """

        try:
            import pyarrow as pa  # type: ignore[import-untyped]
            import pyarrow.parquet as pq  # type: ignore[import-untyped]
        except ImportError as exc:  # pragma: no cover - exercised when optional install absent
            raise TelemetryError(
                "Parquet export requires the production pyarrow dependency"
            ) from exc
        target = _safe_output_path(destination)
        inspected = self.inspect_trace(trace_id)
        rows: list[dict[str, Any]] = []
        for kind in ("spans", "metrics", "events"):
            for row in inspected[kind]:
                rows.append({"record_kind": kind[:-1], **row})
        table = pa.Table.from_pylist(rows)
        temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
        pq.write_table(table, temporary, compression="zstd")
        os.replace(temporary, target)
        return target

    def create_experiment_snapshot(
        self,
        *,
        trace_ids: Sequence[str],
        code_revision: str | None,
        config_hash: str,
        request_or_campaign_refs: Sequence[ArtifactRef],
        package_digests: Sequence[str] = (),
        labels: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        if not trace_ids or not config_hash:
            raise ValueError("experiment snapshot requires traces and a config hash")
        safe_labels = _safe_mapping(labels or {})
        traces = [self.inspect_trace(trace_id) for trace_id in trace_ids]
        created_at = datetime.now(UTC).isoformat()
        manifest = {
            "schema_version": _SCHEMA_VERSION,
            "created_at": created_at,
            "code_revision": code_revision,
            "config_hash": config_hash,
            "trace_ids": list(dict.fromkeys(trace_ids)),
            "request_or_campaign_refs": [
                ref.model_dump(mode="json") for ref in request_or_campaign_refs
            ],
            "package_digests": list(dict.fromkeys(package_digests)),
            "labels": safe_labels,
            "traces": traces,
        }
        digest = sha256_digest(canonical_json_bytes(manifest))
        snapshot_id = f"experiment:{digest.removeprefix('sha256:')[:32]}"
        payload = {**manifest, "snapshot_id": snapshot_id, "snapshot_digest": digest}
        experiments = self.root.parent / "experiments" / "snapshots"
        experiments.mkdir(parents=True, exist_ok=True)
        target = experiments / f"{snapshot_id.replace(':', '-')}.json"
        _atomic_write(target, canonical_json_bytes(payload) + b"\n")
        with self._lock:
            self._connection.execute(
                """
                INSERT OR IGNORE INTO experiments(
                    snapshot_id, snapshot_digest, created_at, manifest_path, trace_ids_json
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (snapshot_id, digest, created_at, str(target), _canonical_text(trace_ids)),
            )
            self._touch()
        return payload

    def health(self) -> dict[str, Any]:
        with self._lock:
            self.flush()
            journal = self._connection.execute("PRAGMA journal_mode").fetchone()[0]
            counts = {
                table: int(self._connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])  # noqa: S608 - fixed internal table names
                for table in ("spans", "metrics", "events", "experiments", "telemetry_health")
            }
        return {
            "schema_version": _SCHEMA_VERSION,
            "database": str(self.database_path),
            "journal_mode": journal,
            "pending_records": self._pending,
            "counts": counts,
        }

    def _configure(self) -> None:
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA synchronous=NORMAL")
        self._connection.execute("PRAGMA foreign_keys=ON")
        self._connection.execute("PRAGMA busy_timeout=30000")

    def _create_schema(self) -> None:
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS telemetry_meta(
                schema_version INTEGER NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS spans(
                span_id TEXT PRIMARY KEY,
                trace_id TEXT NOT NULL,
                parent_span_id TEXT,
                run_id TEXT,
                campaign_id TEXT,
                component TEXT NOT NULL,
                node TEXT,
                operation TEXT NOT NULL,
                attempt INTEGER NOT NULL,
                repair_depth INTEGER NOT NULL,
                status TEXT NOT NULL,
                scheduled_at_ns INTEGER NOT NULL,
                started_at_ns INTEGER NOT NULL,
                first_progress_at_ns INTEGER,
                last_progress_at_ns INTEGER,
                ended_at_ns INTEGER,
                duration_ns INTEGER,
                error_code TEXT,
                input_refs_json TEXT NOT NULL,
                output_refs_json TEXT NOT NULL DEFAULT '[]',
                attributes_json TEXT NOT NULL,
                FOREIGN KEY(parent_span_id) REFERENCES spans(span_id)
            );
            CREATE INDEX IF NOT EXISTS spans_trace_idx ON spans(trace_id, started_at_ns);
            CREATE INDEX IF NOT EXISTS spans_run_idx ON spans(run_id, started_at_ns);
            CREATE INDEX IF NOT EXISTS spans_campaign_idx ON spans(campaign_id, started_at_ns);
            CREATE TABLE IF NOT EXISTS metrics(
                metric_id INTEGER PRIMARY KEY AUTOINCREMENT,
                trace_id TEXT NOT NULL,
                span_id TEXT,
                name TEXT NOT NULL,
                value_integer INTEGER,
                value_real REAL,
                value_unknown INTEGER NOT NULL,
                unit TEXT NOT NULL,
                provenance TEXT NOT NULL,
                labels_json TEXT NOT NULL,
                recorded_at_ns INTEGER NOT NULL,
                FOREIGN KEY(span_id) REFERENCES spans(span_id)
            );
            CREATE INDEX IF NOT EXISTS metrics_trace_idx ON metrics(trace_id, name);
            CREATE TABLE IF NOT EXISTS events(
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                trace_id TEXT NOT NULL,
                span_id TEXT,
                event_type TEXT NOT NULL,
                recorded_at_ns INTEGER NOT NULL,
                payload_json TEXT NOT NULL,
                FOREIGN KEY(span_id) REFERENCES spans(span_id)
            );
            CREATE INDEX IF NOT EXISTS events_trace_idx ON events(trace_id, recorded_at_ns);
            CREATE TABLE IF NOT EXISTS experiments(
                snapshot_id TEXT PRIMARY KEY,
                snapshot_digest TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL,
                manifest_path TEXT NOT NULL,
                trace_ids_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS telemetry_health(
                health_id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                value_real REAL NOT NULL,
                unit TEXT NOT NULL,
                labels_json TEXT NOT NULL,
                recorded_at_ns INTEGER NOT NULL
            );
            """
        )
        span_columns = {
            str(row[1]) for row in self._connection.execute("PRAGMA table_info(spans)").fetchall()
        }
        if "last_progress_at_ns" not in span_columns:
            self._connection.execute(
                "ALTER TABLE spans ADD COLUMN last_progress_at_ns INTEGER"
            )
        row = self._connection.execute("SELECT schema_version FROM telemetry_meta").fetchone()
        if row is None:
            self._connection.execute(
                "INSERT INTO telemetry_meta(schema_version, created_at) VALUES (?, ?)",
                (_SCHEMA_VERSION, datetime.now(UTC).isoformat()),
            )
        elif int(row[0]) != _SCHEMA_VERSION:
            raise TelemetryError("unsupported telemetry schema version")
        self._connection.commit()

    def _record_metrics_uncommitted(
        self,
        trace_id: str,
        span_id: str | None,
        metrics: Sequence[MetricPoint],
    ) -> None:
        now = time.time_ns()
        for point in metrics:
            integer = point.value if isinstance(point.value, int) else None
            real = float(point.value) if isinstance(point.value, float) else None
            self._connection.execute(
                """
                INSERT INTO metrics(
                    trace_id, span_id, name, value_integer, value_real, value_unknown,
                    unit, provenance, labels_json, recorded_at_ns
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    trace_id,
                    span_id,
                    point.name,
                    integer,
                    real,
                    int(point.value is None),
                    point.unit,
                    point.provenance,
                    _canonical_text(_safe_mapping(point.labels)),
                    now,
                ),
            )

    def _insert_health_uncommitted(
        self,
        name: str,
        value: float,
        unit: str,
        *,
        labels: Mapping[str, str],
    ) -> None:
        self._connection.execute(
            """
            INSERT INTO telemetry_health(name, value_real, unit, labels_json, recorded_at_ns)
            VALUES (?, ?, ?, ?, ?)
            """,
            (name, value, unit, _canonical_text(_safe_mapping(labels)), time.time_ns()),
        )

    def _touch(self, count: int = 1) -> None:
        self._pending += count
        if self._pending >= self.commit_batch_size:
            started = time.perf_counter_ns()
            batch_size = self._pending
            self._connection.commit()
            self._pending = 0
            self._insert_health_uncommitted(
                "telemetry.commit.duration_ms",
                (time.perf_counter_ns() - started) / 1_000_000,
                "ms",
                labels={"batch_size": str(batch_size)},
            )
            self._connection.commit()


def _invocation_metrics(
    request: InvocationRequest,
    result: InvocationResult,
) -> tuple[MetricPoint, ...]:
    labels = {
        "model": request.profile.model,
        "provider": request.profile.model_provider or "unknown",
        "reasoning_effort": request.profile.reasoning_effort.value,
        "role": request.profile.profile_id,
        "transaction": _optional_metadata_string(
            request.metadata,
            "semantic_transaction",
        )
        or "unknown",
        "repair_mode": _optional_metadata_string(request.metadata, "repair_mode")
        or "initial",
    }
    metrics: list[MetricPoint] = [
        MetricPoint("invocation.duration_ms", result.duration_ms, "ms", "framework", labels),
        MetricPoint("invocation.events", len(result.events), "events", "sdk", labels),
        MetricPoint(
            "invocation.context_window_tokens",
            result.usage.model_context_window if result.usage else None,
            "tokens",
            "sdk" if result.usage else "unknown",
            labels,
        ),
    ]
    turn = result.usage.turn if result.usage else None
    for name, value in (
        ("input", turn.input_tokens if turn else None),
        ("cached_input", turn.cached_input_tokens if turn else None),
        ("output", turn.output_tokens if turn else None),
        ("reasoning_output", turn.reasoning_output_tokens if turn else None),
        ("total", turn.total_tokens if turn else None),
    ):
        metrics.append(
            MetricPoint(
                f"invocation.tokens.{name}",
                value,
                "tokens",
                "provider" if turn else "unknown",
                labels,
            )
        )
    monetary_cost = result.usage.monetary_cost if result.usage else None
    metrics.append(
        MetricPoint(
            "invocation.monetary_cost",
            monetary_cost,
            "currency",
            "provider" if monetary_cost is not None else "unknown",
            labels,
        )
    )
    return tuple(metrics)


def _summarize_trace(
    spans: Sequence[Mapping[str, Any]],
    metrics: Sequence[Mapping[str, Any]],
    *,
    as_of_ns: int | None = None,
) -> dict[str, Any]:
    observed_at_ns = as_of_ns if as_of_ns is not None else time.time_ns()
    completed = [row for row in spans if row.get("duration_ns") is not None]
    open_spans = [row for row in spans if row.get("duration_ns") is None]

    def effective_end(row: Mapping[str, Any]) -> int:
        ended_at = row.get("ended_at_ns")
        return int(ended_at) if ended_at is not None else observed_at_ns

    def effective_duration(row: Mapping[str, Any]) -> int:
        duration = row.get("duration_ns")
        if duration is not None:
            return max(0, int(duration))
        return max(0, observed_at_ns - int(row["started_at_ns"]))

    wall_start = min((int(row["started_at_ns"]) for row in spans), default=None)
    wall_end = max((effective_end(row) for row in spans), default=None)
    wall_ns = (
        max(0, wall_end - wall_start) if wall_start is not None and wall_end is not None else None
    )
    node_work = [row for row in spans if str(row["operation"]).startswith("node.")]
    parent_ids = {
        str(row["parent_span_id"]) for row in spans if row.get("parent_span_id") is not None
    }
    leaf_work = [row for row in spans if str(row["span_id"]) not in parent_ids]
    accounting_work = node_work or leaf_work
    sum_work_ns = sum(effective_duration(row) for row in accounting_work)
    # Node spans are the top-level orchestration envelopes. Agent/research spans
    # are reported separately and never added to their enclosing node duration,
    # even when a provider cannot propagate an explicit parent context.
    intervals = sorted((int(row["started_at_ns"]), effective_end(row)) for row in accounting_work)
    covered_ns = 0
    covered_end = 0
    for interval_start, interval_end in intervals:
        if interval_end <= covered_end:
            continue
        covered_ns += interval_end - max(interval_start, covered_end)
        covered_end = interval_end
    critical_path_ns = (
        wall_ns
        if wall_ns is not None
        else max((effective_duration(row) for row in accounting_work), default=0)
    )
    node_duration_ms: dict[str, float] = {}
    for row in node_work:
        node = str(row.get("node") or "unknown")
        node_duration_ms[node] = node_duration_ms.get(node, 0.0) + (
            effective_duration(row) / 1_000_000
        )
    invocation_ns = sum(
        effective_duration(row) for row in spans if row["operation"] == "agent.invoke"
    )
    semantic_transactions: dict[str, dict[str, float | int]] = {}
    repair_modes: dict[str, dict[str, float | int]] = {}
    for row in spans:
        if row["operation"] != "agent.invoke":
            continue
        try:
            attributes = json.loads(str(row.get("attributes_json") or "{}"))
        except json.JSONDecodeError:
            attributes = {}
        transaction = str(attributes.get("semantic_transaction") or "unknown")
        aggregate = semantic_transactions.setdefault(
            transaction,
            {"turns": 0, "duration_ms": 0.0, "unknown_token_measurements": 0},
        )
        aggregate["turns"] = int(aggregate["turns"]) + 1
        aggregate["duration_ms"] = float(aggregate["duration_ms"]) + (
            effective_duration(row) / 1_000_000
        )
        repair_mode = str(attributes.get("repair_mode") or "initial")
        repair_aggregate = repair_modes.setdefault(
            repair_mode,
            {"turns": 0, "duration_ms": 0.0, "unknown_token_measurements": 0},
        )
        repair_aggregate["turns"] = int(repair_aggregate["turns"]) + 1
        repair_aggregate["duration_ms"] = float(repair_aggregate["duration_ms"]) + (
            effective_duration(row) / 1_000_000
        )
    transaction_token_names = {
        "invocation.tokens.input": "tokens_input",
        "invocation.tokens.output": "tokens_output",
        "invocation.tokens.reasoning_output": "tokens_reasoning_output",
        "invocation.tokens.total": "tokens_total",
    }
    for row in metrics:
        output_name = transaction_token_names.get(str(row["name"]))
        if output_name is None:
            continue
        try:
            labels = json.loads(str(row.get("labels_json") or "{}"))
        except json.JSONDecodeError:
            labels = {}
        transaction = str(labels.get("transaction") or "unknown")
        aggregate = semantic_transactions.setdefault(
            transaction,
            {"turns": 0, "duration_ms": 0.0, "unknown_token_measurements": 0},
        )
        repair_mode = str(labels.get("repair_mode") or "initial")
        repair_aggregate = repair_modes.setdefault(
            repair_mode,
            {"turns": 0, "duration_ms": 0.0, "unknown_token_measurements": 0},
        )
        if int(row["value_unknown"]):
            aggregate["unknown_token_measurements"] = (
                int(aggregate["unknown_token_measurements"]) + 1
            )
            repair_aggregate["unknown_token_measurements"] = (
                int(repair_aggregate["unknown_token_measurements"]) + 1
            )
            continue
        value = row["value_integer"] if row["value_integer"] is not None else row["value_real"]
        aggregate[output_name] = float(aggregate.get(output_name, 0.0)) + float(value)
        repair_aggregate[output_name] = float(
            repair_aggregate.get(output_name, 0.0)
        ) + float(value)
    open_work_ns = sum(effective_duration(row) for row in open_spans)
    numeric: dict[str, float] = {}
    unknown: dict[str, int] = {}
    for row in metrics:
        name = str(row["name"])
        if int(row["value_unknown"]):
            unknown[name] = unknown.get(name, 0) + 1
            continue
        value = row["value_integer"] if row["value_integer"] is not None else row["value_real"]
        numeric[name] = numeric.get(name, 0.0) + float(value)
    return {
        "span_count": len(spans),
        "terminal_span_count": len(completed),
        "open_span_count": len(open_spans),
        "as_of_ns": observed_at_ns,
        "provisional": bool(open_spans),
        "open_span_work_ms": open_work_ns / 1_000_000,
        "wall_ms": wall_ns / 1_000_000 if wall_ns is not None else None,
        "sum_work_ms": sum_work_ns / 1_000_000,
        "critical_path_ms": critical_path_ns / 1_000_000,
        "critical_path_method": (
            "provisional_trace_wall_envelope" if open_spans else "observed_trace_wall_envelope"
        ),
        "parallel_savings_ms": max(0, sum_work_ns - critical_path_ns) / 1_000_000,
        "framework_overhead_ms": max(0, critical_path_ns - covered_ns) / 1_000_000,
        "node_duration_ms": dict(sorted(node_duration_ms.items())),
        "invocation_duration_ms": invocation_ns / 1_000_000,
        "semantic_transactions": dict(sorted(semantic_transactions.items())),
        "repair_modes": dict(sorted(repair_modes.items())),
        "metrics_sum": numeric,
        "unknown_measurements": unknown,
    }


def _trace_measurements(inspected: Mapping[str, Any]) -> dict[str, Any]:
    summary = cast(Mapping[str, Any], inspected["summary"])
    metric_sums = cast(Mapping[str, float], summary["metrics_sum"])
    events = cast(Sequence[Mapping[str, Any]], inspected["events"])

    def metric(name: str) -> float | None:
        value = metric_sums.get(name)
        return float(value) if value is not None else None

    measurements: dict[str, float | None] = {
        "wall_ms": _optional_float(summary.get("wall_ms")),
        "critical_path_ms": _optional_float(summary.get("critical_path_ms")),
        "sum_work_ms": _optional_float(summary.get("sum_work_ms")),
        "parallel_savings_ms": _optional_float(summary.get("parallel_savings_ms")),
        "framework_overhead_ms": _optional_float(summary.get("framework_overhead_ms")),
        "invocation_duration_ms": _optional_float(summary.get("invocation_duration_ms")),
        "tokens_total": metric("invocation.tokens.total"),
        "tokens_input": metric("invocation.tokens.input"),
        "tokens_output": metric("invocation.tokens.output"),
        "tokens_reasoning_output": metric("invocation.tokens.reasoning_output"),
        "search_calls": metric("research.search.calls"),
        "fetch_calls": metric("research.fetch.calls"),
        "extract_calls": metric("research.extract.calls"),
        "documents_extracted": metric("research.documents.extracted"),
        "research_failures": metric("research.failures"),
        "repair_authorizations": float(
            sum(item.get("event_type") == "repair.authorized" for item in events)
        ),
        "repair_completions": float(
            sum(item.get("event_type") == "repair.completed" for item in events)
        ),
    }
    node_durations = cast(Mapping[str, float], summary.get("node_duration_ms", {}))
    measurements.update(
        {f"node.{node}.duration_ms": float(value) for node, value in node_durations.items()}
    )
    transaction_metrics = cast(
        Mapping[str, Mapping[str, float | int]],
        summary.get("semantic_transactions", {}),
    )
    for transaction, values in transaction_metrics.items():
        for name, value in values.items():
            measurements[f"transaction.{transaction}.{name}"] = float(value)
    repair_metrics = cast(
        Mapping[str, Mapping[str, float | int]],
        summary.get("repair_modes", {}),
    )
    for repair_mode, values in repair_metrics.items():
        for name, value in values.items():
            measurements[f"repair_mode.{repair_mode}.{name}"] = float(value)
    return {
        "trace_id": inspected["trace_id"],
        "provisional": bool(summary["provisional"]),
        "open_span_count": int(summary["open_span_count"]),
        "measurements": measurements,
        "unknown_measurements": dict(cast(Mapping[str, int], summary["unknown_measurements"])),
    }


def _numeric_distribution(values: Sequence[float | None]) -> dict[str, float | int | None]:
    observed = sorted(value for value in values if value is not None)
    if not observed:
        return {
            "observed_count": 0,
            "unknown_count": len(values),
            "sum": None,
            "mean": None,
            "minimum": None,
            "median": None,
            "p95": None,
            "maximum": None,
        }
    midpoint = len(observed) // 2
    median = (
        observed[midpoint]
        if len(observed) % 2
        else (observed[midpoint - 1] + observed[midpoint]) / 2
    )
    p95_index = max(0, (95 * len(observed) + 99) // 100 - 1)
    total = sum(observed)
    return {
        "observed_count": len(observed),
        "unknown_count": len(values) - len(observed),
        "sum": total,
        "mean": total / len(observed),
        "minimum": observed[0],
        "median": median,
        "p95": observed[p95_index],
        "maximum": observed[-1],
    }


def _optional_float(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _trace_id_for_invocation(request: InvocationRequest) -> str:
    for key in ("trace_id", "run_id", "campaign_id"):
        value = request.metadata.get(key)
        if isinstance(value, str) and value:
            return value
    return f"lineage:{_hash_text(request.profile.lineage_id)}"


def _optional_metadata_string(metadata: Mapping[str, Any], key: str) -> str | None:
    value = metadata.get(key)
    return value if isinstance(value, str) and value else None


def _optional_metadata_int(metadata: Mapping[str, Any], key: str) -> int:
    value = metadata.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _safe_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for raw_key, raw_value in value.items():
        if not isinstance(raw_key, str) or not raw_key:
            raise TelemetryError("telemetry keys must be non-empty strings")
        lowered = raw_key.casefold()
        if any(part in lowered for part in _SENSITIVE_KEY_PARTS):
            raise TelemetryError(f"sensitive telemetry field is forbidden: {raw_key}")
        if raw_value is not None and not isinstance(raw_value, (str, int, float, bool)):
            raise TelemetryError("telemetry values must be scalar")
        if isinstance(raw_value, str) and Redactor().text(raw_value) != raw_value:
            raise TelemetryError(f"sensitive telemetry value is forbidden: {raw_key}")
        output[raw_key] = raw_value
    return output


def _refs_json(refs: Sequence[ArtifactRef]) -> str:
    return _canonical_text([ref.model_dump(mode="json") for ref in refs])


def _canonical_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash_text(value: str) -> str:
    return f"sha256:{hashlib.sha256(value.encode('utf-8')).hexdigest()}"


def _safe_output_path(value: str | os.PathLike[str]) -> Path:
    target = Path(value).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.is_symlink():
        raise TelemetryError("telemetry export target cannot be a symlink")
    return target.resolve(strict=False)


def _atomic_write(target: Path, payload: bytes) -> None:
    temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        with os.fdopen(descriptor, "wb", closefd=True) as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


__all__ = [
    "MetricPoint",
    "TelemetryError",
    "TelemetryStore",
    "WorkSpan",
]
