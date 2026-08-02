from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pyarrow.parquet as pq
import pytest

from agent_world.contracts import ArtifactRef, sha256_digest
from agent_world.control import MetricPoint, TelemetryError, TelemetryStore
from agent_world.control.telemetry import _invocation_metrics, classify_invocation_activity
from agent_world.invocation import (
    InvocationRequest,
    InvocationResult,
    InvocationStatus,
    InvocationUsage,
)


def _ref(name: str) -> ArtifactRef:
    digest = sha256_digest(name.encode())
    return ArtifactRef(
        artifact_id=name,
        revision_id=digest,
        artifact_type="test.telemetry_subject",
        content_hash=digest,
        media_type="application/json",
        size_bytes=0,
    )


def test_sqlite_telemetry_records_unknown_usage_and_real_exports(tmp_path: Path) -> None:
    store = TelemetryStore(tmp_path / "telemetry", commit_batch_size=2)
    subject = _ref("request:telemetry")
    root = store.start_span(
        trace_id="run:telemetry",
        component="controller",
        operation="direct.generate",
        run_id="run:telemetry",
        input_refs=(subject,),
    )
    child = store.start_span(
        trace_id="run:telemetry",
        component="research",
        operation="search.fetch.extract",
        parent_span_id=root.span_id,
        run_id="run:telemetry",
    )
    child.first_progress()
    time.sleep(0.002)
    child.finish(
        status="passed",
        metrics=(
            MetricPoint("research.search.calls", 3, "calls", "framework"),
            MetricPoint("invocation.tokens.total", None, "tokens", "unknown"),
        ),
    )
    store.record_event(
        trace_id="run:telemetry",
        span_id=root.span_id,
        event_type="node.checkpointed",
        payload={"node": "research", "revision": 1},
    )
    root.finish(status="passed", output_refs=(subject,))

    inspected = store.inspect_trace("run:telemetry")
    summary = inspected["summary"]
    assert summary["span_count"] == 2
    assert summary["metrics_sum"]["research.search.calls"] == 3
    assert summary["unknown_measurements"]["invocation.tokens.total"] == 1
    assert store.health()["journal_mode"] == "wal"

    json_path = store.export_json(tmp_path / "exports" / "trace.json", trace_id="run:telemetry")
    parquet_path = store.export_parquet(
        tmp_path / "exports" / "trace.parquet",
        trace_id="run:telemetry",
    )
    assert json.loads(json_path.read_text(encoding="utf-8"))["trace_id"] == "run:telemetry"
    table = pq.read_table(parquet_path)
    assert table.num_rows == 5
    assert set(table.column("record_kind").to_pylist()) == {"span", "metric", "event"}

    experiment = store.create_experiment_snapshot(
        trace_ids=("run:telemetry",),
        code_revision="git:test",
        config_hash=sha256_digest(b"config"),
        request_or_campaign_refs=(subject,),
        package_digests=(sha256_digest(b"package"),),
        labels={"suite": "telemetry-real-io"},
    )
    assert experiment["snapshot_digest"].startswith("sha256:")
    assert Path(store.health()["database"]).is_file()
    store.close()


def test_unpriced_invocation_records_unknown_monetary_cost_not_zero() -> None:
    request = cast(
        InvocationRequest,
        SimpleNamespace(
            profile=SimpleNamespace(
                model="compatible-model",
                model_provider="openai",
                reasoning_effort=SimpleNamespace(value="medium"),
                profile_id="profile:test",
            ),
            metadata={},
        ),
    )
    result = InvocationResult(
        invocation_id="invocation:unpriced",
        status=InvocationStatus.COMPLETED,
        session=None,
        turn_id="turn:unpriced",
        final_text="{}",
        structured_output={},
        usage=InvocationUsage(),
        events=(),
        error=None,
        duration_ms=1,
    )

    metric = next(
        point
        for point in _invocation_metrics(request, result)
        if point.name == "invocation.monetary_cost"
    )

    assert metric.value is None
    assert metric.provenance == "unknown"


def test_telemetry_rejects_secret_bearing_fields(tmp_path: Path) -> None:
    with TelemetryStore(tmp_path / "telemetry") as store:
        with pytest.raises(TelemetryError, match="sensitive telemetry field"):
            store.record_event(
                trace_id="run:secret-rejection",
                event_type="unsafe",
                payload={"api_key": "must-not-be-recorded"},
            )
        with pytest.raises(TelemetryError, match="sensitive telemetry value"):
            store.record_event(
                trace_id="run:secret-value-rejection",
                event_type="unsafe",
                payload={"detail": "sk-abcdefghijklmnopqrstuvwxyz012345"},
            )


def test_trace_summary_and_baseline_comparison_preserve_unknowns(tmp_path: Path) -> None:
    with TelemetryStore(tmp_path / "telemetry") as store:
        for trace_id, tokens, searches in (
            ("run:baseline", 100, 2),
            ("run:candidate", 150, 3),
        ):
            span = store.start_span(
                trace_id=trace_id,
                component="controller",
                operation="node.design",
                run_id=trace_id,
                node="design",
            )
            span.finish(
                status="passed",
                metrics=(
                    MetricPoint("invocation.tokens.total", tokens, "tokens", "provider"),
                    MetricPoint("research.search.calls", searches, "calls", "framework"),
                    MetricPoint("invocation.tokens.input", None, "tokens", "unknown"),
                ),
            )

        summary = store.summarize_traces(("run:baseline", "run:candidate"))
        comparison = store.compare_traces(("run:baseline", "run:candidate"))

        assert summary["distributions"]["tokens_total"]["sum"] == 250
        assert summary["distributions"]["tokens_input"]["unknown_count"] == 2
        token_delta = comparison["comparisons"][0]["deltas"]["tokens_total"]
        assert token_delta["absolute_delta"] == 50
        assert token_delta["relative_delta_percent"] == 50


def test_live_trace_reports_running_time_as_provisional(tmp_path: Path) -> None:
    with TelemetryStore(tmp_path / "telemetry", commit_batch_size=1) as store:
        root = store.start_span(
            trace_id="run:live",
            component="controller",
            operation="direct.generate",
            run_id="run:live",
        )
        child = store.start_span(
            trace_id="run:live",
            component="invocation",
            operation="agent.invoke",
            parent_span_id=root.span_id,
            run_id="run:live",
        )
        time.sleep(0.002)

        live = store.inspect_trace("run:live")["summary"]
        assert live["provisional"] is True
        assert live["open_span_count"] == 2
        assert live["terminal_span_count"] == 0
        assert live["wall_ms"] > 0
        assert live["invocation_duration_ms"] > 0
        assert live["critical_path_method"] == "provisional_trace_wall_envelope"

        child.finish(status="passed")
        root.finish(status="passed")
        complete = store.inspect_trace("run:live")["summary"]
        assert complete["provisional"] is False
        assert complete["open_span_count"] == 0
        assert complete["terminal_span_count"] == 2


def test_recovery_closes_orphaned_trace_spans_without_erasing_provider_metrics(
    tmp_path: Path,
) -> None:
    with TelemetryStore(tmp_path / "telemetry", commit_batch_size=1) as store:
        root = store.start_span(
            trace_id="run:abandoned",
            component="controller",
            operation="direct.generate",
            run_id="run:abandoned",
        )
        child = store.start_span(
            trace_id="run:abandoned",
            component="invocation",
            operation="agent.invoke",
            parent_span_id=root.span_id,
            run_id="run:abandoned",
        )
        store.record_metrics(
            "run:abandoned",
            child.span_id,
            (MetricPoint("invocation.events.observed_delta", 1, "events", "sdk"),),
        )

        assert store.reconcile_abandoned_trace("run:abandoned") == 2
        inspected = store.inspect_trace("run:abandoned")

        assert inspected["summary"]["open_span_count"] == 0
        assert inspected["summary"]["metrics_sum"]["invocation.events.observed_delta"] == 1
        assert {row["status"] for row in inspected["spans"]} == {"error"}
        assert {row["error_code"] for row in inspected["spans"]} == {"owner_process_interrupted"}


def test_semantic_transaction_costs_are_aggregated_without_prompt_content(
    tmp_path: Path,
) -> None:
    with TelemetryStore(tmp_path / "telemetry") as store:
        span = store.start_span(
            trace_id="run:transactions",
            component="invocation",
            operation="agent.invoke",
            run_id="run:transactions",
            attributes={
                "semantic_transaction": "design.world-architecture",
                "repair_mode": "contract-correction",
            },
        )
        span.finish(
            status="passed",
            metrics=(
                MetricPoint(
                    "invocation.tokens.total",
                    1200,
                    "tokens",
                    "provider",
                    {
                        "transaction": "design.world-architecture",
                        "repair_mode": "contract-correction",
                    },
                ),
                MetricPoint(
                    "invocation.tokens.input",
                    900,
                    "tokens",
                    "provider",
                    {
                        "transaction": "design.world-architecture",
                        "repair_mode": "contract-correction",
                    },
                ),
            ),
        )

        transaction = store.inspect_trace("run:transactions")["summary"]["semantic_transactions"][
            "design.world-architecture"
        ]
        assert transaction["turns"] == 1
        assert transaction["tokens_total"] == 1200
        assert transaction["tokens_input"] == 900
        assert transaction["duration_ms"] >= 0
        repair = store.inspect_trace("run:transactions")["summary"]["repair_modes"][
            "contract-correction"
        ]
        assert repair["turns"] == 1
        assert repair["tokens_total"] == 1200


def test_invocation_admission_is_visible_to_an_independent_reader(tmp_path: Path) -> None:
    root = tmp_path / "telemetry"
    with (
        TelemetryStore(root, commit_batch_size=128) as writer,
        TelemetryStore(root, commit_batch_size=128) as reader,
    ):
        profile = SimpleNamespace(
            lineage_id="lineage:telemetry",
            profile_hash="sha256:" + "1" * 64,
            backend="codex-sdk",
            model="test-model",
            model_provider="test-provider",
            reasoning_effort=SimpleNamespace(value="medium"),
            output_schema={"type": "object"},
        )
        request = cast(
            InvocationRequest,
            SimpleNamespace(
                invocation_id="invocation:telemetry",
                prompt="content-must-not-be-persisted",
                profile=profile,
                session=None,
                metadata={
                    "trace_id": "run:invocation-live",
                    "role": "designer",
                    "repair_mode": "contract_correction",
                },
            ),
        )

        span = writer.start_invocation(request)
        observed = reader.inspect_trace("run:invocation-live")

        assert len(observed["spans"]) == 1
        assert observed["spans"][0]["status"] == "running"
        attributes = json.loads(observed["spans"][0]["attributes_json"])
        assert attributes["input_bytes"] == len(request.prompt.encode("utf-8"))
        assert attributes["repair_mode"] == "contract_correction"
        assert observed["summary"]["repair_modes"]["contract_correction"]["turns"] == 1
        assert "prompt_bytes" not in attributes
        assert request.prompt not in observed["spans"][0]["attributes_json"]
        span.finish(status="passed")


def test_running_invocation_projects_throttled_safe_progress(tmp_path: Path) -> None:
    root = tmp_path / "telemetry"
    with (
        TelemetryStore(root, commit_batch_size=128) as writer,
        TelemetryStore(root, commit_batch_size=128) as reader,
    ):
        profile = SimpleNamespace(
            lineage_id="lineage:progress",
            profile_hash="sha256:" + "2" * 64,
            backend="codex-sdk",
            model="test-model",
            model_provider="test-provider",
            reasoning_effort=SimpleNamespace(value="medium"),
            output_schema={"type": "object"},
        )
        request = cast(
            InvocationRequest,
            SimpleNamespace(
                invocation_id="invocation:progress",
                prompt="source-content-must-remain-private",
                profile=profile,
                session=None,
                metadata={"trace_id": "run:progress", "role": "builder"},
            ),
        )

        span = writer.start_invocation(request)
        span.progress(
            "item.started",
            {"item": {"id": "reasoning-canary-must-not-persist", "type": "reasoning"}},
        )
        for _ in range(128):
            span.progress(
                "item.updated",
                {
                    "item": {
                        "id": "command-canary-must-not-persist",
                        "type": "commandExecution",
                    }
                },
            )

        inspected = reader.inspect_trace("run:progress")
        live = reader.active_work("run:progress")

        assert inspected["spans"][0]["first_progress_at_ns"] is not None
        assert inspected["spans"][0]["last_progress_at_ns"] is not None
        assert len(live) == 1
        assert live[0]["observed_event_count"] == 129
        assert live[0]["activity_classification_available"] is True
        assert live[0]["observed_activity_event_counts"] == {
            "reasoning": 1,
            "agent_message": 0,
            "command": 128,
            "file_change": 0,
            "tool": 0,
            "other": 0,
            "unclassified": 0,
        }
        assert live[0]["observed_token_count"] is None
        serialized = json.dumps({"trace": inspected, "active": live})
        assert request.prompt not in serialized
        assert "reasoning-canary-must-not-persist" not in serialized
        assert "command-canary-must-not-persist" not in serialized
        span.finish(status="passed")


def test_finishing_span_preserves_buffered_provider_event_time(tmp_path: Path) -> None:
    """A terminal write must not masquerade as fresh Provider progress.

    The last event below remains buffered when the span finishes.  Keeping its
    observed timestamp lets a scene distinguish an idle Provider stream from a
    merely late terminal cleanup.
    """

    with TelemetryStore(tmp_path / "telemetry") as store:
        span = store.start_span(
            trace_id="run:provider-idle",
            component="invocation",
            operation="agent.invoke",
        )
        span.progress("item.started", {"item": {"type": "reasoning"}})
        time.sleep(0.01)
        span.progress("item.updated", {"item": {"type": "commandExecution"}})
        time.sleep(0.02)
        span.finish(status="failed", error_code="provider_stream_stalled")

        inspected = store.inspect_trace("run:provider-idle")

    row = inspected["spans"][0]
    assert row["last_progress_at_ns"] is not None
    assert row["ended_at_ns"] is not None
    assert row["ended_at_ns"] - row["last_progress_at_ns"] >= 10_000_000


@pytest.mark.parametrize(
    ("item_type", "expected"),
    (
        ("direct_stream_reasoning", "reasoning"),
        ("direct_stream_output", "agent_message"),
        ("direct_stream_unclassified", "unclassified"),
        ("direct_stream_lifecycle", "other"),
        ("direct_stream_completion", "other"),
    ),
)
def test_direct_stream_activity_projection_preserves_safe_meaning(
    item_type: str,
    expected: str,
) -> None:
    """Direct stream sentinels stay content-free but remain debuggable live."""

    assert classify_invocation_activity({"item": {"type": item_type}}) == expected
