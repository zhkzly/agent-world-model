from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

import agent_world.invocation.audit as audit
from agent_world.config import AgentBackendConfig, FoundryConfig, ResearchConfig
from agent_world.invocation.capabilities import NodeCapabilityRequirement
from agent_world.invocation.contracts import (
    InvocationError,
    InvocationExecutionMode,
    InvocationRequest,
    InvocationResult,
    InvocationSession,
    InvocationStatus,
    ResolvedAgentProfile,
)


class _FakeTelemetry:
    def __init__(self, *_: object, **__: object) -> None:
        pass

    def close(self) -> None:
        pass

    def inspect_trace(self, _: str) -> dict[str, object]:
        return {
            "summary": {
                "metrics_sum": {
                    "invocation.events.observed_delta": 2,
                    "invocation.activity.agent_message_event_delta": 1,
                    "invocation.activity.other_event_delta": 1,
                }
            }
        }


class _FakeProfileProvider:
    def __init__(self, *_: object, **__: object) -> None:
        pass

    def resolve(
        self,
        *,
        lineage_id: str,
        workspace: Path,
        output_schema: dict[str, object],
        requirement: NodeCapabilityRequirement,
        **_: object,
    ) -> ResolvedAgentProfile:
        builtin_tools = requirement.intrinsic_builtin_tools
        agent_workspace = workspace / ".agent-runtime" / "workspace"
        agent_workspace.mkdir(parents=True)
        return cast(
            ResolvedAgentProfile,
            SimpleNamespace(
                allowed_builtin_tools=builtin_tools,
                output_schema=output_schema,
                structured_output_transport=(
                    "json_object" if not builtin_tools else "provider_schema"
                ),
                workspace=agent_workspace,
                lineage_id=lineage_id,
                profile_hash="a" * 64,
                codex_config_sha256="b" * 64,
            ),
        )

    def resolve_solver(
        self,
        *,
        lineage_id: str,
        workspace: Path,
        output_schema: dict[str, object],
        **_: object,
    ) -> ResolvedAgentProfile:
        return self.resolve(
            lineage_id=lineage_id,
            workspace=workspace,
            output_schema=output_schema,
            requirement=cast(
                NodeCapabilityRequirement,
                SimpleNamespace(intrinsic_builtin_tools=()),
            ),
        )


class _FakeRoutedBackend:
    def __init__(self, **_: object) -> None:
        pass

    async def invoke(self, request: InvocationRequest) -> InvocationResult:
        profile = request.profile
        execution_mode = request.execution_mode
        if "workspace_edit" in profile.allowed_builtin_tools:
            marker = profile.workspace / "candidate" / "invocation-audit-marker.txt"
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text("ok", encoding="utf-8")
        session = None
        if execution_mode is InvocationExecutionMode.AGENTIC:
            session = InvocationSession(
                thread_id="audit-thread",
                lineage_id=profile.lineage_id,
                workspace=profile.workspace,
                profile_hash=profile.profile_hash,
                codex_config_sha256=profile.codex_config_sha256,
            )
        properties = profile.output_schema.get("properties", {})
        candidate_completion = isinstance(properties, dict) and "blocking_reason" in properties
        return InvocationResult(
            invocation_id=request.invocation_id,
            status=InvocationStatus.COMPLETED,
            session=session,
            turn_id=None,
            final_text=None,
            structured_output=(
                {
                    "status": "blocked",
                    "blocking_reason": "invocation-audit-complete",
                }
                if candidate_completion
                else {"status": "ok"}
            ),
            usage=None,
            events=(),
            error=None,
            duration_ms=1,
            backend_version="fake-audit",
        )


class _RaisingRoutedBackend:
    def __init__(self, **_: object) -> None:
        pass

    async def invoke(self, _: InvocationRequest) -> InvocationResult:
        raise RuntimeError("raw provider detail must not escape the audit report")


class _ResumeFailingRoutedBackend(_FakeRoutedBackend):
    async def invoke(self, request: InvocationRequest) -> InvocationResult:
        if request.session is None:
            return await super().invoke(request)
        return InvocationResult(
            invocation_id=request.invocation_id,
            status=InvocationStatus.FAILED,
            session=None,
            turn_id=None,
            final_text=None,
            structured_output=None,
            usage=None,
            events=(),
            error=InvocationError(
                code="resume_provider_unavailable",
                message="raw resume provider detail must not escape the audit report",
                retryable=True,
            ),
            duration_ms=3,
            backend_version="fake-audit",
        )


def _config(tmp_path: Path) -> FoundryConfig:
    return FoundryConfig(
        state_root=tmp_path / "state",
        agent=AgentBackendConfig(
            model="audit-model",
            api_key_environment="OPENAI_API_KEY",
            structured_output_transport="json_object",
        ),
        research=ResearchConfig(provider="bing_rss"),
    )


@pytest.mark.asyncio
async def test_invocation_audit_covers_all_distinct_real_mechanisms_safely(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(audit, "TelemetryStore", _FakeTelemetry)
    monkeypatch.setattr(audit, "IsolatedAgentProfileProvider", _FakeProfileProvider)
    monkeypatch.setattr(audit, "CodexSdkBackend", lambda **_: object())
    monkeypatch.setattr(audit, "DirectLlmBackend", lambda **_: object())
    monkeypatch.setattr(audit, "RoutedInvocationBackend", _FakeRoutedBackend)

    report = await audit.run_invocation_audit(_config(tmp_path))

    assert report.status == "passed"
    assert tuple(item.lane_id for item in report.lanes) == audit.INVOCATION_AUDIT_LANE_IDS
    assert {item.expected_backend for item in report.lanes} == {"direct_llm", "codex_sdk"}
    workspace = next(
        item for item in report.lanes if item.lane_id == "codex_engineer_workspace_write"
    )
    assert workspace.workspace_write_verified is True
    assert workspace.node_id == "environment-engineer.runtime-build"
    plan = next(
        item for item in report.lanes if item.lane_id == "codex_engineer_implementation_plan_read"
    )
    assert plan.node_id == "environment-engineer.implementation-plan"
    candidate_completion = next(
        item for item in report.lanes if item.lane_id == "codex_engineer_candidate_completion"
    )
    assert candidate_completion.node_id == "environment-engineer.runtime-build"
    assert candidate_completion.output_contract == "candidate_completion_blocked"
    assert candidate_completion.physical_turn_count == 1
    assert candidate_completion.workspace_write_verified is True
    assert all(
        item.physical_turn_count == (2 if item.session_continuity_scope is not None else 1)
        for item in report.lanes
    )
    assert all(
        item.same_backend_session_resume_verified is True
        for item in report.lanes
        if item.session_continuity_scope is not None
    )
    assert all(
        item.session_continuity_scope == "same_backend_instance"
        for item in report.lanes
        if item.session_continuity_scope is not None
    )
    assert all(item.provider_event_count == 2 for item in report.lanes)
    serialized = (tmp_path / "state" / "invocation-audit.json").read_text(encoding="utf-8")
    assert "Return the required structured status object" not in serialized
    assert '"status":"passed"' in serialized
    records = tuple((tmp_path / "state" / "invocation-audit-runs").glob("*.json"))
    assert len(records) == 1
    assert json.loads(records[0].read_text(encoding="utf-8"))["run_id"] == report.run_id


def test_invocation_audit_rejects_unknown_lane_before_a_provider_call() -> None:
    with pytest.raises(ValueError, match="unknown invocation audit lane"):
        audit._select_lanes(("not-a-lane",))


def test_invocation_audit_uses_the_real_special_engineer_profile_coordinates() -> None:
    lanes = {item.lane_id: item for item in audit._AUDIT_LANES}

    assert lanes["direct_engineer_structured"].node_id == (
        "environment-engineer.tool-semantics-batch"
    )
    assert lanes["codex_engineer_implementation_plan_read"].node_id == (
        "environment-engineer.implementation-plan"
    )
    assert lanes["codex_engineer_workspace_write"].node_id == ("environment-engineer.runtime-build")
    assert lanes["codex_engineer_candidate_completion"].output_contract == (
        "candidate_completion_blocked"
    )


@pytest.mark.asyncio
async def test_invocation_audit_reports_backend_phase_without_raw_exception_text(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(audit, "TelemetryStore", _FakeTelemetry)
    monkeypatch.setattr(audit, "IsolatedAgentProfileProvider", _FakeProfileProvider)
    monkeypatch.setattr(audit, "CodexSdkBackend", lambda **_: object())
    monkeypatch.setattr(audit, "DirectLlmBackend", lambda **_: object())
    monkeypatch.setattr(audit, "RoutedInvocationBackend", _RaisingRoutedBackend)

    report = await audit.run_invocation_audit(
        _config(tmp_path),
        lane_ids=("codex_challenger_solver",),
    )

    lane = report.lanes[0]
    assert report.status == "failed"
    assert lane.failure_code == "invocation_audit_backend_invoke_exception"
    assert lane.terminal_details == {
        "phase": "backend_invoke",
        "structured_output_transport": "json_object",
    }
    serialized = (tmp_path / "state" / "invocation-audit.json").read_text(encoding="utf-8")
    assert "raw provider detail" not in serialized


@pytest.mark.asyncio
async def test_invocation_audit_reports_the_exact_failed_physical_turn_safely(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(audit, "TelemetryStore", _FakeTelemetry)
    monkeypatch.setattr(audit, "IsolatedAgentProfileProvider", _FakeProfileProvider)
    monkeypatch.setattr(audit, "CodexSdkBackend", lambda **_: object())
    monkeypatch.setattr(audit, "DirectLlmBackend", lambda **_: object())
    monkeypatch.setattr(audit, "RoutedInvocationBackend", _ResumeFailingRoutedBackend)

    report = await audit.run_invocation_audit(
        _config(tmp_path),
        lane_ids=("codex_engineer_implementation_plan_read",),
    )

    lane = report.lanes[0]
    assert report.status == "failed"
    assert lane.failure_phase == "session_resume"
    assert lane.physical_turn_count == 2
    assert [(item.turn_index, item.status, item.failure_code) for item in lane.physical_turns] == [
        (1, "passed", None),
        (2, "failed", "resume_provider_unavailable"),
    ]
    serialized = (tmp_path / "state" / "invocation-audit.json").read_text(encoding="utf-8")
    assert "raw resume provider detail" not in serialized


@pytest.mark.asyncio
async def test_invocation_audit_keeps_prior_run_record_when_a_subset_runs_later(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(audit, "TelemetryStore", _FakeTelemetry)
    monkeypatch.setattr(audit, "IsolatedAgentProfileProvider", _FakeProfileProvider)
    monkeypatch.setattr(audit, "CodexSdkBackend", lambda **_: object())
    monkeypatch.setattr(audit, "DirectLlmBackend", lambda **_: object())
    monkeypatch.setattr(audit, "RoutedInvocationBackend", _FakeRoutedBackend)

    first = await audit.run_invocation_audit(
        _config(tmp_path),
        lane_ids=("direct_researcher_structured",),
    )
    second = await audit.run_invocation_audit(
        _config(tmp_path),
        lane_ids=("codex_challenger_solver",),
    )

    records = {
        json.loads(path.read_text(encoding="utf-8"))["run_id"]: json.loads(
            path.read_text(encoding="utf-8")
        )
        for path in (tmp_path / "state" / "invocation-audit-runs").glob("*.json")
    }
    current = json.loads((tmp_path / "state" / "invocation-audit.json").read_text(encoding="utf-8"))
    assert set(records) == {first.run_id, second.run_id}
    assert records[first.run_id]["lanes"][0]["lane_id"] == "direct_researcher_structured"
    assert current["run_id"] == second.run_id
