"""True DirectJob feedback-boundary proof for escaped Scheduler exceptions.

This deliberately does not simulate an Agent response.  The public Controller
and DirectJobStore execute normally; the frozen Scheduler's own input-bound
invariant raises before any invocation can be admitted.  It proves the
project-execution diagnostic projection without spending a Provider turn.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import HttpUrl

from agent_world.app import build_application
from agent_world.config import AgentBackendConfig, FoundryConfig, ResearchConfig
from agent_world.control import (
    JobRunSnapshot,
    WorkCoordinate,
    WorkDependencyUnavailableError,
    WorkScheduler,
)


def _config(tmp_path: Path) -> FoundryConfig:
    return FoundryConfig(
        state_root=tmp_path / "state",
        agent=AgentBackendConfig(
            model="grok-4.5",
            api_key_environment="OPENAI_API_KEY",
            openai_base_url_environment="OPENAI_BASE_URL",
        ),
        research=ResearchConfig(
            provider="searxng",
            searxng_base_url=HttpUrl("http://127.0.0.1:18080"),
            searxng_allow_private_endpoint=True,
            use_jina_reader_fallback=False,
        ),
    )


@pytest.mark.asyncio
async def test_direct_job_records_text_free_scheduler_exception_diagnostic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "unit-test-credential-canary")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://unit.invalid/v1")
    app = build_application(_config(tmp_path))

    class _InvariantFailureRunner:
        async def run(self, **_kwargs: object) -> object:
            # This is a real Scheduler invariant, not a fake Agent outcome.
            scheduler = object.__new__(WorkScheduler)
            return await scheduler.run_until_stalled(
                executors={},
                maximum_concurrency=0,
            )

    app.controller.direct_work_runner = _InvariantFailureRunner()  # type: ignore[assignment]

    result = await app.controller.generate(
        "生成一个最小本地预约环境",
        request_id="scheduler-diagnostic:boundary",
    )

    assert result.status == "failed"
    assert result.failure_code == "scheduler_direct_execution_error"
    assert result.failure_summary is not None
    assert "scheduler bounds must be positive" not in result.failure_summary
    assert "scheduler-direct-diagnostic:" in result.failure_summary

    snapshot = app.controller.artifacts.get_json(result.final_snapshot_ref, JobRunSnapshot)
    diagnostics = tuple(
        ref
        for ref in snapshot.latest_artifact_refs
        if ref.artifact_type == "control.scheduler_execution_diagnostic"
    )
    assert len(diagnostics) == 1
    diagnostic = app.controller.artifacts.get_json(diagnostics[0])
    assert diagnostic["error_type"] == "ValueError"
    assert str(diagnostic["error_site"]).startswith("agent_world/control/work_scheduler.py:")
    assert diagnostic["message_fingerprint"].startswith("sha256:")
    assert "scheduler bounds must be positive" not in str(diagnostic)


@pytest.mark.asyncio
async def test_direct_job_diagnostic_names_safe_unavailable_dependency(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A scheduling race exposes actionable coordinates without raw exception text."""

    monkeypatch.setenv("OPENAI_API_KEY", "unit-test-credential-canary")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://unit.invalid/v1")
    app = build_application(_config(tmp_path))
    child = WorkCoordinate(
        scope_id="job:safe-dependency-diagnostic",
        component="design",
        stage="world_architecture",
        artifact_slot="world_architecture",
    )
    parent = WorkCoordinate(
        scope_id="job:safe-dependency-diagnostic",
        component="research",
        stage="evidence_synthesis",
        artifact_slot="evidence_synthesis",
    )

    class _DependencyRaceRunner:
        async def run(self, **_kwargs: object) -> object:
            raise WorkDependencyUnavailableError(
                child=child,
                parent=parent,
                parent_status="failed",
                reason_code="parent_not_committed",
            )

    app.controller.direct_work_runner = _DependencyRaceRunner()  # type: ignore[assignment]
    result = await app.controller.generate(
        "生成一个最小本地预约环境",
        request_id="scheduler-diagnostic:dependency",
    )

    snapshot = app.controller.artifacts.get_json(result.final_snapshot_ref, JobRunSnapshot)
    diagnostic_ref = next(
        ref
        for ref in snapshot.latest_artifact_refs
        if ref.artifact_type == "control.scheduler_execution_diagnostic"
    )
    diagnostic = app.controller.artifacts.get_json(diagnostic_ref)
    assert diagnostic["work_dependency"] == {
        "child_coordinate_key": child.coordinate_key,
        "parent_coordinate_key": parent.coordinate_key,
        "parent_status": "failed",
        "reason_code": "parent_not_committed",
    }
    assert "evidence_synthesis" not in str(diagnostic)
