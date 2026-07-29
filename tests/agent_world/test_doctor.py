from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import HttpUrl, ValidationError

import agent_world.doctor as doctor_module
from agent_world.config import (
    AgentBackendConfig,
    FoundryConfig,
    JudgeConfig,
    ResearchConfig,
)
from agent_world.control import TelemetryStore
from agent_world.doctor import (
    DoctorCheck,
    _live_agent_check,
    _live_agent_failure_code,
    _live_agent_probe_rollout_token_limit,
    run_doctor,
)
from agent_world.invocation import (
    InvocationControlStore,
    InvocationError,
    InvocationRequest,
    InvocationResult,
    InvocationSession,
    InvocationStatus,
)
from agent_world.judge import IsolationPolicy, IsolationUnavailable


def _doctor_config(tmp_path: Path, *, judge: JudgeConfig) -> FoundryConfig:
    return FoundryConfig(
        state_root=tmp_path / "state",
        agent=AgentBackendConfig(
            model="doctor-readiness-probe",
            api_key_environment="AGENT_WORLD_TEST_ABSENT_MODEL_KEY",
        ),
        research=ResearchConfig(
            provider="searxng",
            searxng_base_url=HttpUrl("http://127.0.0.1:18080"),
            searxng_allow_private_endpoint=True,
            use_jina_reader_fallback=False,
        ),
        judge=judge,
    )


def _check(report_checks: tuple[DoctorCheck, ...], name: str) -> DoctorCheck:
    matches = tuple(item for item in report_checks if item.check == name)
    assert len(matches) == 1
    return matches[0]


async def _require_real_isolation() -> None:
    if shutil.which("uv") is None:
        pytest.skip("real uv executable is unavailable")
    try:
        await IsolationPolicy(purpose="runtime").ensure_available()
        await IsolationPolicy(purpose="build").ensure_available()
    except IsolationUnavailable as exc:
        pytest.skip(f"real bubblewrap isolation unavailable: {exc.code}: {exc}")


@pytest.mark.asyncio
async def test_doctor_fails_closed_when_offline_cache_is_not_configured(
    tmp_path: Path,
) -> None:
    report = await run_doctor(
        _doctor_config(
            tmp_path,
            judge=JudgeConfig(),
        )
    )

    clean_build = _check(report.checks, "clean_build")
    assert clean_build.status == "fail"
    assert "explicit judge.uv_cache_dir" in clean_build.summary
    assert not report.ok
    assert not report.local_execution_ready
    assert not report.configuration_ready
    assert not report.live_agent_verified
    assert not report.live_research_verified
    assert not report.production_ready


@pytest.mark.asyncio
async def test_doctor_executes_real_offline_clean_build_and_runtime_probe(
    tmp_path: Path,
) -> None:
    await _require_real_isolation()
    cache = tmp_path / "uv-cache"
    cache.mkdir()
    report = await run_doctor(
        _doctor_config(
            tmp_path,
            judge=JudgeConfig(
                uv_cache_dir=cache,
                clean_build_timeout_seconds=60,
            ),
        )
    )

    clean_build = _check(report.checks, "clean_build")
    assert clean_build.status == "pass", clean_build.summary
    assert "exact Python 3.12" in clean_build.summary
    assert "configured read-only uv cache" in clean_build.summary
    assert _check(report.checks, "live_agent").status == "skipped"
    assert _check(report.checks, "live_research").status == "skipped"
    assert not report.production_ready


@pytest.mark.asyncio
async def test_doctor_accepts_short_opaque_api_key_handle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Doctor must agree with application assembly on redaction-safe key length."""

    environment_name = "AGENT_WORLD_TEST_SHORT_OPAQUE_KEY"
    monkeypatch.setenv(environment_name, "tok_6x")
    config = FoundryConfig(
        state_root=tmp_path / "state",
        agent=AgentBackendConfig(
            model="doctor-readiness-probe",
            api_key_environment=environment_name,
        ),
        research=ResearchConfig(
            provider="searxng",
            searxng_base_url=HttpUrl("http://127.0.0.1:18080"),
            searxng_allow_private_endpoint=True,
            use_jina_reader_fallback=False,
        ),
        judge=JudgeConfig(),
    )

    report = await run_doctor(config)
    assert _check(report.checks, "model_authentication").status == "pass"


def test_judge_config_rejects_removed_online_build_policy() -> None:
    with pytest.raises(ValidationError):
        JudgeConfig.model_validate(
            {
                "build_offline": False,
                "allow_build_network": True,
            }
        )


def test_live_agent_probe_retains_only_safe_backend_failure_code() -> None:
    result = InvocationResult(
        invocation_id="doctor-live-agent-round-trip",
        status=InvocationStatus.FAILED,
        session=None,
        turn_id=None,
        final_text=None,
        structured_output=None,
        usage=None,
        events=(),
        error=InvocationError(
            code="provider_invalid_request",
            message="raw provider text must not reach doctor output",
        ),
        duration_ms=1,
        backend_version="test-backend",
    )

    assert _live_agent_failure_code(result) == "provider_invalid_request"


def test_live_agent_probe_uses_the_largest_configured_real_agent_envelope(
    tmp_path: Path,
) -> None:
    config = FoundryConfig(
        state_root=tmp_path / "state",
        agent=AgentBackendConfig(
            model="doctor-readiness-probe",
            api_key_environment="AGENT_WORLD_TEST_ABSENT_MODEL_KEY",
            structured_turn_token_limit=65_536,
            environment_codegen_turn_token_limit=5_000_000,
        ),
        research=ResearchConfig(
            provider="searxng",
            searxng_base_url=HttpUrl("http://127.0.0.1:18080"),
            searxng_allow_private_endpoint=True,
            use_jina_reader_fallback=False,
        ),
        judge=JudgeConfig(),
    )

    assert _live_agent_probe_rollout_token_limit(config) == 5_000_000


@pytest.mark.asyncio
async def test_live_agent_probe_publishes_live_safe_trace_and_terminal_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A constructed backend proves Doctor's live liveness boundary, not a unit stub."""

    environment_name = "AGENT_WORLD_TEST_OBSERVABLE_DOCTOR_KEY"
    monkeypatch.setenv(environment_name, "test-key")
    config = FoundryConfig(
        state_root=tmp_path / "state",
        agent=AgentBackendConfig(
            model="doctor-readiness-probe",
            api_key_environment=environment_name,
            structured_turn_token_limit=65_536,
            environment_codegen_turn_token_limit=5_000_000,
            structured_invocation_timeout_seconds=28_800,
        ),
        research=ResearchConfig(
            provider="searxng",
            searxng_base_url=HttpUrl("http://127.0.0.1:18080"),
            searxng_allow_private_endpoint=True,
            use_jina_reader_fallback=False,
        ),
        judge=JudgeConfig(),
    )
    entered = asyncio.Event()
    release = asyncio.Event()
    received: list[InvocationRequest] = []

    class HoldingBackend:
        def __init__(self, *, telemetry: TelemetryStore) -> None:
            self.telemetry = telemetry

        async def invoke(self, request: InvocationRequest) -> InvocationResult:
            received.append(request)
            span = self.telemetry.start_invocation(request)
            span.first_progress()
            entered.set()
            await release.wait()
            span.finish(status="passed")
            return InvocationResult(
                invocation_id=request.invocation_id,
                status=InvocationStatus.COMPLETED,
                session=InvocationSession(
                    thread_id="doctor-test-thread",
                    lineage_id=request.profile.lineage_id,
                    workspace=request.profile.workspace,
                    profile_hash=request.profile.profile_hash,
                    codex_config_sha256=request.profile.codex_config_sha256,
                ),
                turn_id="doctor-test-turn",
                final_text=None,
                structured_output={"status": "ok"},
                usage=None,
                events=(),
                error=None,
                duration_ms=1,
                backend_version="test-backend",
            )

    monkeypatch.setattr(doctor_module, "CodexSdkBackend", HoldingBackend)
    check_task = asyncio.create_task(_live_agent_check(config))
    await asyncio.wait_for(entered.wait(), timeout=5)

    status_path = config.state_root / "doctor-live-agent.json"
    running = json.loads(status_path.read_text(encoding="utf-8"))
    assert running["status"] == "running"
    assert running["rollout_token_limit"] == 5_000_000
    assert running["wall_timeout_seconds"] == 28_800
    assert received and received[0].metadata["trace_id"] == running["trace_id"]
    assert received[0].metadata["run_id"] == running["trace_id"]

    with TelemetryStore(config.state_root / "telemetry") as reader:
        active = reader.active_work(running["trace_id"])
    assert len(active) == 1
    assert active[0]["first_progress_at_ns"] is not None
    assert active[0]["last_progress_at_ns"] is not None

    release.set()
    check = await check_task
    assert check.status == "pass"
    terminal = json.loads(status_path.read_text(encoding="utf-8"))
    assert terminal["status"] == "passed"
    assert terminal["trace_id"] == running["trace_id"]
    serialized = json.dumps(terminal, sort_keys=True)
    assert "production InvocationBackend readiness probe" not in serialized
    assert "test-key" not in serialized


@pytest.mark.asyncio
async def test_live_agent_probe_mints_a_new_physical_invocation_for_each_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A repeated readiness probe must not collide with a settled control record."""

    environment_name = "AGENT_WORLD_TEST_REPEAT_DOCTOR_KEY"
    monkeypatch.setenv(environment_name, "test-key")
    config = FoundryConfig(
        state_root=tmp_path / "state",
        agent=AgentBackendConfig(
            model="doctor-readiness-probe",
            api_key_environment=environment_name,
        ),
        research=ResearchConfig(
            provider="searxng",
            searxng_base_url=HttpUrl("http://127.0.0.1:18080"),
            searxng_allow_private_endpoint=True,
            use_jina_reader_fallback=False,
        ),
        judge=JudgeConfig(),
    )
    invocation_ids: list[str] = []

    class CompletingBackend:
        def __init__(self, *, telemetry: TelemetryStore) -> None:
            self.telemetry = telemetry

        async def invoke(self, request: InvocationRequest) -> InvocationResult:
            invocation_ids.append(request.invocation_id)
            span = self.telemetry.start_invocation(request)
            span.first_progress()
            span.finish(status="passed")
            return InvocationResult(
                invocation_id=request.invocation_id,
                status=InvocationStatus.COMPLETED,
                session=InvocationSession(
                    thread_id=f"doctor-thread:{len(invocation_ids)}",
                    lineage_id=request.profile.lineage_id,
                    workspace=request.profile.workspace,
                    profile_hash=request.profile.profile_hash,
                    codex_config_sha256=request.profile.codex_config_sha256,
                ),
                turn_id=f"doctor-turn:{len(invocation_ids)}",
                final_text=None,
                structured_output={"status": "ok"},
                usage=None,
                events=(),
                error=None,
                duration_ms=1,
                backend_version="test-backend",
            )

    monkeypatch.setattr(doctor_module, "CodexSdkBackend", CompletingBackend)

    first = await _live_agent_check(config)
    second = await _live_agent_check(config)

    assert first.status == "pass"
    assert second.status == "pass"
    assert len(invocation_ids) == 2
    assert invocation_ids[0] != invocation_ids[1]
    records = InvocationControlStore(config.state_root / "invocation-control").list_records()
    assert {record.invocation_id for record in records} == set(invocation_ids)
    assert all(record.settled for record in records)


@pytest.mark.asyncio
async def test_live_agent_probe_status_does_not_expose_provider_message(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environment_name = "AGENT_WORLD_TEST_DOCTOR_FAILURE_KEY"
    monkeypatch.setenv(environment_name, "test-key")
    config = FoundryConfig(
        state_root=tmp_path / "state",
        agent=AgentBackendConfig(
            model="doctor-readiness-probe",
            api_key_environment=environment_name,
        ),
        research=ResearchConfig(
            provider="searxng",
            searxng_base_url=HttpUrl("http://127.0.0.1:18080"),
            searxng_allow_private_endpoint=True,
            use_jina_reader_fallback=False,
        ),
        judge=JudgeConfig(),
    )

    class FailingBackend:
        def __init__(self, *, telemetry: TelemetryStore) -> None:
            self.telemetry = telemetry

        async def invoke(self, request: InvocationRequest) -> InvocationResult:
            span = self.telemetry.start_invocation(request)
            span.finish(status="failed", error_code="provider_invalid_request")
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
                    code="turn_failed_unclassified_codex_error",
                    message="provider-secret-text-must-not-be-persisted",
                    details={
                        "terminal_error_shape": "object",
                        "codex_error_info": "absent",
                        "advisory_text_signals": ["request_or_schema_compatibility"],
                        "diagnostic_error_excerpt": "unsupported response_format [REDACTED_URL]",
                        "provider_message": "provider-secret-text-must-not-be-persisted",
                    },
                ),
                duration_ms=1,
                backend_version="test-backend",
            )

    monkeypatch.setattr(doctor_module, "CodexSdkBackend", FailingBackend)
    check = await _live_agent_check(config)

    assert check.status == "fail"
    status = json.loads((config.state_root / "doctor-live-agent.json").read_text(encoding="utf-8"))
    assert status["status"] == "failed"
    assert status["failure_code"] == "turn_failed_unclassified_codex_error"
    assert status["terminal_details"] == {
        "advisory_text_signals": ["request_or_schema_compatibility"],
        "codex_error_info": "absent",
        "terminal_error_shape": "object",
    }
    debug_path = Path(status["debug_feedback_path"])
    debug = json.loads(await asyncio.to_thread(debug_path.read_text, encoding="utf-8"))
    assert debug["terminal_error_excerpt"] == "unsupported response_format [REDACTED_URL]"
    assert debug["trace_id"] == status["trace_id"]
    assert "provider-secret-text-must-not-be-persisted" not in json.dumps(status, sort_keys=True)
    assert "provider-secret-text-must-not-be-persisted" not in json.dumps(debug, sort_keys=True)


def test_doctor_cli_reports_offline_cache_blocker_as_structured_failure(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "foundry.toml"
    config_path.write_text(
        "\n".join(
            (
                'state_root = "state"',
                "",
                "[agent]",
                'model = "doctor-readiness-probe"',
                'api_key_environment = "AGENT_WORLD_TEST_ABSENT_MODEL_KEY"',
                "",
                "[research]",
                'provider = "searxng"',
                'searxng_base_url = "http://127.0.0.1:18080"',
                "searxng_allow_private_endpoint = true",
                "use_jina_reader_fallback = false",
                "",
                "[judge]",
                "clean_build_timeout_seconds = 60",
                "",
            )
        ),
        encoding="utf-8",
    )
    environment = dict(os.environ)
    environment.pop("AGENT_WORLD_TEST_ABSENT_MODEL_KEY", None)
    completed = subprocess.run(  # noqa: S603 - fixed interpreter and module
        (
            sys.executable,
            "-m",
            "agent_world.cli",
            "--config",
            str(config_path),
            "doctor",
        ),
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
        env=environment,
    )

    assert completed.returncode == 1, completed.stderr
    assert completed.stderr == ""
    report = json.loads(completed.stdout)
    clean_build = next(item for item in report["checks"] if item["check"] == "clean_build")
    assert clean_build["status"] == "fail"
    assert "explicit judge.uv_cache_dir" in clean_build["summary"]
