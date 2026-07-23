from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import HttpUrl, ValidationError

from agent_world.config import (
    AgentBackendConfig,
    FoundryConfig,
    JudgeConfig,
    ResearchConfig,
)
from agent_world.doctor import DoctorCheck, _live_agent_failure_code, run_doctor
from agent_world.invocation import InvocationError, InvocationResult, InvocationStatus
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
