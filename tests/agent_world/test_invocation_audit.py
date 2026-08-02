from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

import agent_world.invocation.audit as audit
from agent_world.builder.models import CandidateCompletion
from agent_world.config import AgentBackendConfig, FoundryConfig, ResearchConfig
from agent_world.invocation.capabilities import NodeCapabilityRequirement
from agent_world.invocation.codex_sdk import _provider_output_schema
from agent_world.invocation.contracts import (
    InvocationError,
    InvocationExecutionMode,
    InvocationLimits,
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
        workspace.mkdir(parents=True)
        return cast(
            ResolvedAgentProfile,
            SimpleNamespace(
                allowed_builtin_tools=builtin_tools,
                output_schema=output_schema,
                workspace=workspace,
                lineage_id=lineage_id,
                model="audit-model",
                profile_hash="a" * 64,
                codex_config_sha256="b" * 64,
                skills=(),
                limits=InvocationLimits(),
                rollout_token_limit=None,
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
        if "workspace_edit" in profile.allowed_builtin_tools and request.session is None:
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
                dict(audit._CANDIDATE_COMPLETION_BLOCKED_VALUE)
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


class _CandidateCompletionMismatchBackend(_FakeRoutedBackend):
    async def invoke(self, request: InvocationRequest) -> InvocationResult:
        result = await super().invoke(request)
        properties = request.profile.output_schema.get("properties", {})
        if isinstance(properties, dict) and "blocking_reason" in properties:
            return replace(
                result,
                structured_output={
                    **audit._CANDIDATE_COMPLETION_BLOCKED_VALUE,
                    "blocking_reason": "untrusted-model-text-must-not-persist",
                },
            )
        return result


class _CandidateCompletionTerminalExcerptBackend(_FakeRoutedBackend):
    requests: list[InvocationRequest] = []

    async def invoke(self, request: InvocationRequest) -> InvocationResult:
        type(self).requests.append(request)
        result = await super().invoke(request)
        properties = request.profile.output_schema.get("properties", {})
        if not isinstance(properties, dict) or "blocking_reason" not in properties:
            return result
        opaque = "a" * 40
        return replace(
            result,
            status=InvocationStatus.FAILED,
            structured_output=None,
            error=InvocationError(
                code="turn_failed_unclassified_codex_error",
                message="provider terminal failed",
                retryable=True,
                details={
                    "terminal_error_shape": "object",
                    "codex_error_info": "enum:other",
                    "diagnostic_error_excerpt": (
                        "unsupported response format at "
                        "https://provider.example.test/v1?api_key=must-not-persist "
                        f"token={opaque}"
                    ),
                },
            ),
        )


class _BlockingRoutedBackend:
    instances: list[_BlockingRoutedBackend] = []
    created: asyncio.Event | None = None

    def __init__(self, **_: object) -> None:
        self.started = asyncio.Event()
        type(self).instances.append(self)
        if type(self).created is not None:
            type(self).created.set()

    async def invoke(self, _: InvocationRequest) -> InvocationResult:
        self.started.set()
        await asyncio.Event().wait()
        raise AssertionError("the blocking audit backend unexpectedly resumed")

    async def cancel(self, _: str) -> bool:
        return True


def _config(tmp_path: Path) -> FoundryConfig:
    return FoundryConfig(
        state_root=tmp_path / "state",
        agent=AgentBackendConfig(
            model="audit-model",
            api_key_environment="OPENAI_API_KEY",
        ),
        research=ResearchConfig(provider="bing_rss"),
    )


@pytest.mark.asyncio
async def test_invocation_audit_covers_all_distinct_real_mechanisms_safely(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(audit, "TelemetryStore", _FakeTelemetry)
    monkeypatch.setattr(audit, "AgentProfileProvider", _FakeProfileProvider)
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
    assert workspace.node_id == "invocation-audit.engineer-workspace-write"
    engineer_read = next(item for item in report.lanes if item.lane_id == "codex_engineer_read")
    assert engineer_read.node_id == "invocation-audit.engineer-read"
    assert engineer_read.physical_turn_count == 2
    assert engineer_read.session_continuity_scope == "same_backend_instance"
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
    attempts = tuple(
        json.loads(path.read_text(encoding="utf-8"))
        for path in (tmp_path / "state" / "invocation-control" / "attempts").glob("*.json")
    )
    assert attempts
    assert all(item["owner"]["owner_kind"] == "diagnostic_audit" for item in attempts)
    assert all(item["owner"]["scope_id"] == report.run_id for item in attempts)
    assert all(item["owner"]["coordinate"].startswith("invocation_audit.") for item in attempts)
    assert all(item["owner"]["owner_id"] == item["invocation_id"] for item in attempts)


def test_invocation_audit_rejects_unknown_lane_before_a_provider_call() -> None:
    with pytest.raises(ValueError, match="unknown invocation audit lane"):
        audit._select_lanes(("not-a-lane",))


def test_invocation_audit_uses_diagnostic_or_exact_profile_coordinates() -> None:
    lanes = {item.lane_id: item for item in audit._AUDIT_LANES}

    assert lanes["direct_engineer_structured"].node_id == "invocation-audit.direct-engineer"
    assert lanes["codex_engineer_read"].node_id == "invocation-audit.engineer-read"
    assert lanes["codex_engineer_workspace_write"].node_id == (
        "invocation-audit.engineer-workspace-write"
    )
    assert lanes["codex_engineer_candidate_completion"].node_id == (
        "environment-engineer.runtime-build"
    )
    assert lanes["codex_engineer_read"].require_session_resume is True
    workspace_prompt = audit._prompt_for_lane(lanes["codex_engineer_workspace_write"])
    assert "Follow the one mounted Agent World Skill" in workspace_prompt
    assert "direct-host production InvocationBackend audit" in workspace_prompt
    assert ".agent-world-tools" not in workspace_prompt
    direct_prompt = audit._prompt_for_lane(lanes["direct_engineer_structured"])
    assert "Return exactly this logical artifact" in direct_prompt
    assert "Runtime Skill" not in direct_prompt
    assert lanes["codex_engineer_candidate_completion"].output_contract == (
        "candidate_completion_blocked"
    )


def test_candidate_completion_audit_uses_json_mode_like_the_builder() -> None:
    lane = next(
        item for item in audit._AUDIT_LANES if item.lane_id == "codex_engineer_candidate_completion"
    )
    result = InvocationResult(
        invocation_id="audit-candidate-json-mode",
        status=InvocationStatus.COMPLETED,
        session=None,
        turn_id=None,
        final_text=None,
        structured_output=CandidateCompletion(
            status="blocked",
            blocking_reason="invocation-audit-complete",
        ).model_dump(mode="json"),
        usage=None,
        events=(),
        error=None,
        duration_ms=1,
    )

    observation = audit._structured_output_observation(lane, result)

    assert observation.kind == "exact_match"


def test_candidate_completion_audit_blocked_value_fits_strict_schema() -> None:
    """The exact Agent instruction must fit Codex's strict transport schema.

    The logical model permits omitted inactive fields, while the compiled
    provider schema requires every property.  An audit must make that physical
    difference explicit rather than asking the Agent for an impossible short
    object and then treating its placeholders as a semantic failure.
    """

    lane = next(
        item for item in audit._AUDIT_LANES if item.lane_id == "codex_engineer_candidate_completion"
    )
    expected = audit._expected_output_for_lane(lane)
    provider_schema = _provider_output_schema(audit._output_schema_for_lane(lane))  # noqa: SLF001
    required = provider_schema.get("required")

    assert isinstance(required, list)
    assert set(expected) == set(required)
    completion = CandidateCompletion.model_validate_json(json.dumps(expected))
    assert completion.status == "blocked"
    assert completion.files == ()
    assert completion.public_test_paths == ()
    prompt = audit._prompt_for_lane(lane)
    assert '"project_root":null' in prompt
    assert "transport placeholders" in prompt


def test_candidate_completion_audit_observation_keeps_only_closed_schema_categories() -> None:
    lane = next(
        item for item in audit._AUDIT_LANES if item.lane_id == "codex_engineer_candidate_completion"
    )
    result = InvocationResult(
        invocation_id="audit-candidate-invalid",
        status=InvocationStatus.COMPLETED,
        session=None,
        turn_id=None,
        final_text=None,
        structured_output={"untrusted_field": "untrusted-value"},
        usage=None,
        events=(),
        error=None,
        duration_ms=1,
    )

    observation = audit._structured_output_observation(lane, result)

    assert observation.kind == "candidate_completion_invalid"
    assert observation.validation_issue_codes == ("schema_value",)
    assert observation.validation_issue_categories == (
        "missing_required_field",
        "unexpected_field",
    )


@pytest.mark.asyncio
async def test_invocation_audit_reports_backend_phase_without_raw_exception_text(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(audit, "TelemetryStore", _FakeTelemetry)
    monkeypatch.setattr(audit, "AgentProfileProvider", _FakeProfileProvider)
    monkeypatch.setattr(audit, "CodexSdkBackend", lambda **_: object())
    monkeypatch.setattr(audit, "DirectLlmBackend", lambda **_: object())
    monkeypatch.setattr(audit, "RoutedInvocationBackend", _RaisingRoutedBackend)

    report = await audit.run_invocation_audit(
        _config(tmp_path),
        lane_ids=("direct_challenger_episode_solver",),
    )

    lane = report.lanes[0]
    assert report.status == "failed"
    assert lane.failure_code == "invocation_audit_backend_invoke_exception"
    assert lane.terminal_details == {
        "phase": "backend_invoke",
    }
    serialized = (tmp_path / "state" / "invocation-audit.json").read_text(encoding="utf-8")
    assert "raw provider detail" not in serialized


@pytest.mark.asyncio
async def test_invocation_audit_reports_the_exact_failed_physical_turn_safely(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(audit, "TelemetryStore", _FakeTelemetry)
    monkeypatch.setattr(audit, "AgentProfileProvider", _FakeProfileProvider)
    monkeypatch.setattr(audit, "CodexSdkBackend", lambda **_: object())
    monkeypatch.setattr(audit, "DirectLlmBackend", lambda **_: object())
    monkeypatch.setattr(audit, "RoutedInvocationBackend", _ResumeFailingRoutedBackend)

    report = await audit.run_invocation_audit(
        _config(tmp_path),
        lane_ids=("codex_engineer_read",),
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
async def test_invocation_audit_reports_a_closed_candidate_completion_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(audit, "TelemetryStore", _FakeTelemetry)
    monkeypatch.setattr(audit, "AgentProfileProvider", _FakeProfileProvider)
    monkeypatch.setattr(audit, "CodexSdkBackend", lambda **_: object())
    monkeypatch.setattr(audit, "DirectLlmBackend", lambda **_: object())
    monkeypatch.setattr(audit, "RoutedInvocationBackend", _CandidateCompletionMismatchBackend)

    report = await audit.run_invocation_audit(
        _config(tmp_path),
        lane_ids=("codex_engineer_candidate_completion",),
    )

    lane = report.lanes[0]
    assert report.status == "failed"
    assert lane.failure_code == "invocation_audit_structured_output_mismatch"
    assert [item.kind for item in lane.structured_output_observations] == [
        "candidate_completion_blocking_reason_mismatch"
    ]
    assert lane.structured_output_observations[0].validation_issue_codes == ()
    serialized = (tmp_path / "state" / "invocation-audit.json").read_text(encoding="utf-8")
    assert "untrusted-model-text-must-not-persist" not in serialized


@pytest.mark.asyncio
async def test_candidate_completion_audit_writes_only_a_redacted_opted_in_terminal_sidecar(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _CandidateCompletionTerminalExcerptBackend.requests.clear()
    monkeypatch.setattr(audit, "TelemetryStore", _FakeTelemetry)
    monkeypatch.setattr(audit, "AgentProfileProvider", _FakeProfileProvider)
    monkeypatch.setattr(audit, "CodexSdkBackend", lambda **_: object())
    monkeypatch.setattr(audit, "DirectLlmBackend", lambda **_: object())
    monkeypatch.setattr(
        audit,
        "RoutedInvocationBackend",
        _CandidateCompletionTerminalExcerptBackend,
    )

    report = await audit.run_invocation_audit(
        _config(tmp_path),
        lane_ids=("codex_engineer_candidate_completion",),
    )

    lane = report.lanes[0]
    assert report.status == "failed"
    assert lane.failure_code == "turn_failed_unclassified_codex_error"
    assert lane.diagnostic_terminal_feedback_path is not None
    assert (
        _CandidateCompletionTerminalExcerptBackend.requests[0].metadata[
            "diagnostic_capture_terminal_excerpt"
        ]
        is True
    )
    debug_path = Path(lane.diagnostic_terminal_feedback_path)
    # This is a bounded local sidecar read after the audited invocation has
    # already settled.  Keep it synchronous: the test proves its contents, not
    # a thread-pool boundary, and must remain runnable where thread creation is
    # deliberately unavailable to the test harness.
    debug = json.loads(debug_path.read_text(encoding="utf-8"))  # noqa: ASYNC240 - assertion
    assert debug["kind"] == "invocation_audit_terminal_debug"
    assert debug["failure_code"] == "turn_failed_unclassified_codex_error"
    assert debug["terminal_error_excerpt"].startswith("unsupported response format")
    assert "provider.example.test" not in debug["terminal_error_excerpt"]
    assert "a" * 40 not in debug["terminal_error_excerpt"]
    serialized = (tmp_path / "state" / "invocation-audit.json").read_text(encoding="utf-8")
    assert "unsupported response format" not in serialized
    assert "provider.example.test" not in serialized


@pytest.mark.asyncio
async def test_invocation_audit_keeps_prior_run_record_when_a_subset_runs_later(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(audit, "TelemetryStore", _FakeTelemetry)
    monkeypatch.setattr(audit, "AgentProfileProvider", _FakeProfileProvider)
    monkeypatch.setattr(audit, "CodexSdkBackend", lambda **_: object())
    monkeypatch.setattr(audit, "DirectLlmBackend", lambda **_: object())
    monkeypatch.setattr(audit, "RoutedInvocationBackend", _FakeRoutedBackend)

    first = await audit.run_invocation_audit(
        _config(tmp_path),
        lane_ids=("direct_researcher_structured",),
    )
    second = await audit.run_invocation_audit(
        _config(tmp_path),
        lane_ids=("direct_challenger_episode_solver",),
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


@pytest.mark.asyncio
async def test_invocation_audit_cancellation_writes_non_running_report_and_attempt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cancellation is an owner terminal, never an indefinitely running audit."""

    _BlockingRoutedBackend.instances.clear()
    _BlockingRoutedBackend.created = asyncio.Event()
    monkeypatch.setattr(audit, "TelemetryStore", _FakeTelemetry)
    monkeypatch.setattr(audit, "AgentProfileProvider", _FakeProfileProvider)
    monkeypatch.setattr(audit, "CodexSdkBackend", lambda **_: object())
    monkeypatch.setattr(audit, "DirectLlmBackend", lambda **_: object())
    monkeypatch.setattr(audit, "RoutedInvocationBackend", _BlockingRoutedBackend)

    task = asyncio.create_task(
        audit.run_invocation_audit(
            _config(tmp_path),
            lane_ids=("direct_challenger_episode_solver",),
        )
    )
    await _BlockingRoutedBackend.created.wait()
    await _BlockingRoutedBackend.instances[0].started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    report = json.loads((tmp_path / "state" / "invocation-audit.json").read_text(encoding="utf-8"))
    assert report["status"] == "interrupted"
    lane = report["lanes"][0]
    assert lane["status"] == "interrupted"
    assert lane["failure_code"] == "owner_process_interrupted"
    records = tuple((tmp_path / "state" / "invocation-control" / "attempts").glob("*.json"))
    assert len(records) == 1
    attempt = json.loads(records[0].read_text(encoding="utf-8"))
    assert attempt["status"] == "settled"
    assert attempt["terminal"] == {
        "status": "cancelled",
        "code": "owner_cancelled",
        "retryable": False,
    }
