from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import HttpUrl

from agent_world.agent_profiles import IsolatedAgentProfileProvider
from agent_world.app import ApplicationConfigurationError, DirectRunReader, build_application
from agent_world.artifact_store import ArtifactStoreError, UnsafeArtifactError
from agent_world.builder import BuilderWorkspaceProgress, EnvironmentBuilder
from agent_world.cli import (
    _parse_capability_signal,
    _parse_rollout_action,
    _parse_suite_selection,
    build_parser,
)
from agent_world.config import AgentBackendConfig, FoundryConfig, ResearchConfig
from agent_world.contracts import (
    ArtifactRef,
    Budget,
    BudgetUsage,
    CurriculumSamplingPolicy,
    EnvironmentJob,
    ReleaseProfile,
    sha256_digest,
)
from agent_world.control import (
    BudgetLease,
    DurableLeaseBudgetCoordinator,
    JobRunSnapshot,
    NodeAttempt,
    WorkControlStore,
)
from agent_world.controller import FoundryController
from agent_world.designer import (
    EnvironmentDesigner,
    ExpansionDesigner,
    ExpansionSourceRouter,
)
from agent_world.invocation import CodexSdkBackend
from agent_world.judge import (
    EnvironmentJudge,
    InteractiveChallengerStrategy,
    VerifierCompiler,
)
from agent_world.registry import EnvironmentRegistry


def _filesystem_config(tmp_path: Path, auth_file: Path) -> FoundryConfig:
    return FoundryConfig(
        state_root=tmp_path / "state",
        agent=AgentBackendConfig(
            model="configured-real-model",
            chatgpt_auth_file=auth_file.resolve(),
        ),
        research=ResearchConfig(
            provider="searxng",
            searxng_base_url=HttpUrl("http://127.0.0.1:18080"),
            searxng_allow_private_endpoint=True,
            use_jina_reader_fallback=False,
        ),
    )


def _write_auth_file(path: Path, secret: str, *, mode: int = 0o600) -> None:
    path.write_text(
        json.dumps({"tokens": {"access_token": secret}}),
        encoding="utf-8",
    )
    path.chmod(mode)


def test_production_app_assembles_real_components_and_secret_canaries(tmp_path: Path) -> None:
    canary = "credential-canary-A19xQ7mR"
    with tempfile.TemporaryDirectory(prefix="agent-world-auth-", dir="/tmp") as auth_root:
        auth_file = Path(auth_root) / "auth.json"
        _write_auth_file(auth_file, canary)
        app = build_application(_filesystem_config(tmp_path, auth_file))

    assert isinstance(app.profiles, IsolatedAgentProfileProvider)
    assert isinstance(app.backend, CodexSdkBackend)
    assert isinstance(app.designer, EnvironmentDesigner)
    assert isinstance(app.expansion_source, ExpansionSourceRouter)
    assert isinstance(app.expansion_designer, ExpansionDesigner)
    assert isinstance(app.builder, EnvironmentBuilder)
    assert isinstance(app.verifier_compiler, VerifierCompiler)
    assert (
        app.verifier_compiler.maximum_structured_reworks
        == app.config.judge.maximum_structured_reworks
    )
    assert isinstance(app.judge, EnvironmentJudge)
    assert isinstance(app.judge.interactive_challenger, InteractiveChallengerStrategy)
    assert app.judge.interactive_challenger.backend is app.backend
    assert app.judge.interactive_challenger.profiles is app.profiles
    assert isinstance(app.registry, EnvironmentRegistry)
    assert isinstance(app.controller, FoundryController)
    assert app.artifacts.capability_issuance_sealed

    with pytest.raises(ArtifactStoreError, match="issuance is sealed"):
        app.artifacts.issue_writer(
            producer="environment-judge",
            allowed_artifact_types=("judge_report",),
        )

    with pytest.raises(UnsafeArtifactError):
        app.controller.artifacts.put_blob(
            artifact_id="secret-leak-attempt",
            artifact_type="control.security_probe",
            content=f"prefix {canary} suffix".encode(),
            media_type="text/plain",
        )


def test_auth_file_error_never_contains_credential_material(tmp_path: Path) -> None:
    canary = "credential-that-must-not-appear-B72kL9"
    with tempfile.TemporaryDirectory(prefix="agent-world-auth-", dir="/tmp") as auth_root:
        auth_file = Path(auth_root) / "auth.json"
        _write_auth_file(auth_file, canary, mode=0o644)
        with pytest.raises(ApplicationConfigurationError) as captured:
            build_application(_filesystem_config(tmp_path, auth_file))

        assert canary not in str(captured.value)
        assert "permissions" in str(captured.value)


def test_application_accepts_short_opaque_api_key_and_still_seals_its_canary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A compatible gateway token needs the same no-leak protection as a long key."""

    credential = "tok_6x"
    environment_name = "AGENT_WORLD_TEST_SHORT_OPAQUE_KEY"
    monkeypatch.setenv(environment_name, credential)
    config = FoundryConfig(
        state_root=tmp_path / "state",
        agent=AgentBackendConfig(
            model="configured-real-model",
            api_key_environment=environment_name,
        ),
        research=ResearchConfig(
            provider="searxng",
            searxng_base_url=HttpUrl("http://127.0.0.1:18080"),
            searxng_allow_private_endpoint=True,
            use_jina_reader_fallback=False,
        ),
    )

    app = build_application(config)
    with pytest.raises(UnsafeArtifactError):
        app.controller.artifacts.put_blob(
            artifact_id="short-credential-leak-attempt",
            artifact_type="control.security_probe",
            content=f"prefix {credential} suffix".encode(),
            media_type="text/plain",
        )


def test_module_and_installed_console_help_are_executable() -> None:
    commands = (
        (sys.executable, "-m", "agent_world.cli", "--help"),
        (str(Path(sys.executable).with_name("agent-world")), "--help"),
    )
    for command in commands:
        completed = subprocess.run(  # noqa: S603 - fixed interpreter/installed entry point
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        )
        assert completed.returncode == 0, completed.stderr
        assert "generate" in completed.stdout
        assert "run" in completed.stdout
        assert "discovery" in completed.stdout
        assert "registry" in completed.stdout
        assert "expand" in completed.stdout
        assert "suite" in completed.stdout
        assert "feedback" in completed.stdout


def test_suite_cli_exposes_machine_parseable_create_start_and_rollout_contracts() -> None:
    parser = build_parser()
    created = parser.parse_args(
        ["suite", "create", "--package", "inventory@1.2.3=2.5", "--max-steps", "37"]
    )
    started = parser.parse_args(["suite", "start", "suite_abc", "--seed", "19"])
    rollout = parser.parse_args(
        [
            "suite",
            "rollout",
            "suite_abc",
            "--seed",
            "19",
            "--action",
            'inventory.reserve={"sku":"A-1","quantity":2}',
        ]
    )

    assert created.suite_command == "create"
    assert started.suite_command == "start"
    assert started.seed == 19
    assert rollout.suite_command == "rollout"
    policy = CurriculumSamplingPolicy(maximum_steps=created.max_steps)
    selection = _parse_suite_selection(created.package[0], policy=policy)
    action = _parse_rollout_action(rollout.action[0])
    assert selection.package_id == "inventory"
    assert selection.version == "1.2.3"
    assert selection.weight == Decimal("2.5")
    assert selection.curriculum_policy.maximum_steps == 37
    assert action.tool_id == "inventory.reserve"
    assert action.arguments == {"sku": "A-1", "quantity": 2}


def test_discovery_cli_exposes_independent_resume_contract() -> None:
    parsed = build_parser().parse_args(["discovery", "resume", "discovery-run:abc"])

    assert parsed.command == "discovery"
    assert parsed.discovery_command == "resume"
    assert parsed.discovery_run_id == "discovery-run:abc"


def test_direct_run_cli_exposes_offline_progress_inspection() -> None:
    parsed = build_parser().parse_args(["run", "inspect", "request:abc"])

    assert parsed.command == "run"
    assert parsed.run_command == "inspect"
    assert parsed.request_id == "request:abc"

    resumed = build_parser().parse_args(["run", "resume", "request:abc"])
    assert resumed.command == "run"
    assert resumed.run_command == "resume"
    assert resumed.request_id == "request:abc"


def test_direct_run_reader_exposes_live_progress_and_budget_without_content() -> None:
    def ref(name: str, artifact_type: str) -> ArtifactRef:
        digest = sha256_digest(name.encode())
        return ArtifactRef(
            artifact_id=name,
            revision_id=digest,
            artifact_type=artifact_type,
            content_hash=digest,
            media_type="application/json",
            size_bytes=0,
        )

    now = datetime.now(UTC)
    job_ref = ref("job:live", "control.environment_job")
    request_ref = ref("request:live", "control.environment_request")
    snapshot_ref = ref("run:live:state", "control.job_run_snapshot")
    design_ref = ref("design:live", "design.environment_design")
    lease_ref = ref("lease:live", "control.budget_lease")
    lease_two_ref = ref("lease:live-two", "control.budget_lease")
    progress_ref = ref("candidate:live:workspace-progress", "build.workspace_progress")
    lease = BudgetLease(
        lease_id="lease:live",
        owner_id="attempt:build-live",
        reserved=Budget(llm_tokens=1000, agent_turns=2, wall_seconds=120),
        created_at=now,
    )
    lease_two = BudgetLease(
        lease_id="lease:live-two",
        owner_id="attempt:verifier-live",
        reserved=Budget(llm_tokens=500, agent_turns=1, wall_seconds=100),
        created_at=now,
    )
    snapshot = JobRunSnapshot(
        run_id="run:live",
        job_ref=job_ref,
        revision=2,
        status="running",
        reserved_budget=Budget(llm_tokens=5000),
        observed_actual_budget=BudgetUsage(llm_tokens=250),
        unknown_upper_bound_budget=BudgetUsage(),
        conservative_committed_budget=BudgetUsage(llm_tokens=250),
        attempts=(
            NodeAttempt(
                attempt_id="attempt:build-live",
                node="build",
                ordinal=1,
                status="running",
                started_at=now - timedelta(seconds=10),
                input_refs=(design_ref,),
            ),
        ),
        latest_artifact_refs=(design_ref, lease_ref, lease_two_ref),
    )
    progress = BuilderWorkspaceProgress(
        run_id="run:live",
        attempt_id="attempt:build-live",
        lineage_id="run:live.builder",
        observed_at=now,
        status="changed",
        file_count=7,
        total_bytes=4096,
        metadata_digest=sha256_digest(b"metadata-only"),
    )
    head = SimpleNamespace(
        run_id="run:live",
        job_ref=job_ref,
        request_ref=request_ref,
        snapshot_ref=snapshot_ref,
        model_dump=lambda **_kwargs: {"run_id": "run:live"},
    )

    class FakeArtifacts:
        def get_json(self, target: ArtifactRef, model: object) -> Any:
            del model
            return {
                snapshot_ref: snapshot,
                lease_ref: lease,
                lease_two_ref: lease_two,
                progress_ref: progress,
            }[target]

        def list_events_for_run(self, *_args: object, **_kwargs: object) -> tuple[()]:
            return ()

        def list_revisions(self, artifact_id: str | None = None) -> tuple[ArtifactRef, ...]:
            assert artifact_id == "run:live:workspace-progress:attempt:build-live"
            return (progress_ref,)

    telemetry_span = {
        "span_id": "span:live",
        "observed_event_count": 129,
        "observed_protocol_tool_event_count": 8,
        "observed_token_count": None,
    }
    reader = DirectRunReader(
        SimpleNamespace(read_head=lambda _request_id: head),  # type: ignore[arg-type]
        FakeArtifacts(),  # type: ignore[arg-type]
        SimpleNamespace(active_work=lambda _run_id: (telemetry_span,)),  # type: ignore[arg-type]
    )

    inspected = reader.inspect("request:live")
    active = inspected["active_work"]

    assert isinstance(active, dict)
    assert active["builder_workspace"]["progress"]["file_count"] == 7
    assert active["usage"]["observed_actual"]["llm_tokens"] == 250
    assert active["usage"]["unknown_upper_bound"]["llm_tokens"] == 0
    assert active["usage"]["conservative_committed"]["llm_tokens"] == 250
    assert active["usage"]["active_reserved_exposure"]["llm_tokens"] == 1500
    assert active["usage"]["active_reserved_exposure"]["wall_seconds"] == 120
    assert active["usage"]["inflight_observed"]["llm_tokens"] is None
    assert "metadata-only" not in json.dumps(inspected)

    terminal = snapshot.model_copy(
        update={
            "status": "failed",
            "failure_code": "test_terminal",
            "failure_summary": "terminal test state",
        }
    )
    terminal_active = reader._active_work("run:live", terminal)  # noqa: SLF001
    assert terminal_active["spans"] == []
    assert terminal_active["orphaned_spans"] == [telemetry_span]
    assert terminal_active["usage"]["active_lease_count"] == 0
    assert terminal_active["usage"]["orphaned_lease_count"] == 2


def test_direct_run_reader_uses_scheduler_ledger_for_live_budget(tmp_path: Path) -> None:
    """A live Direct read must not project the stale summary as zero usage."""

    def ref(name: str, artifact_type: str) -> ArtifactRef:
        digest = sha256_digest(name.encode())
        return ArtifactRef(
            artifact_id=name,
            revision_id=digest,
            artifact_type=artifact_type,
            content_hash=digest,
            media_type="application/json",
            size_bytes=0,
        )

    job_ref = ref("job:scheduler-live", "control.environment_job")
    request_ref = ref("request:scheduler-live", "control.environment_request")
    snapshot_ref = ref("run:scheduler-live:state", "control.job_run_snapshot")
    job = EnvironmentJob(
        job_id="job:scheduler-live",
        kind="generate",
        request_ref=request_ref,
        release_profile=ReleaseProfile(profile_id="release:scheduler-live"),
    )
    snapshot = JobRunSnapshot(
        run_id="run:scheduler-live",
        job_ref=job_ref,
        revision=1,
        status="running",
        reserved_budget=Budget(llm_tokens=1_000, agent_turns=4, wall_seconds=120),
        observed_actual_budget=BudgetUsage(),
        unknown_upper_bound_budget=BudgetUsage(),
        conservative_committed_budget=BudgetUsage(),
    )
    heads = WorkControlStore(tmp_path / "work-control")
    coordinator = DurableLeaseBudgetCoordinator(heads.root / "scope-budgets")
    coordinator.initialize(scope_id=job.job_id, reserved=snapshot.reserved_budget)
    coordinator.reserve(
        scope_id=job.job_id,
        lease_id="lease:settled",
        owner_id="operation:settled",
        requested=Budget(llm_tokens=400, agent_turns=1, wall_seconds=30),
        elapsed_wall_seconds=0,
    )
    coordinator.settle(
        scope_id=job.job_id,
        lease_id="lease:settled",
        observed_actual=BudgetUsage(llm_tokens=240, agent_turns=1),
        unknown_upper_bound=BudgetUsage(llm_tokens=40),
    )
    coordinator.reserve(
        scope_id=job.job_id,
        lease_id="lease:active",
        owner_id="operation:active",
        requested=Budget(llm_tokens=500, agent_turns=2, wall_seconds=60),
        elapsed_wall_seconds=1,
    )
    head = SimpleNamespace(
        run_id=snapshot.run_id,
        job_ref=job_ref,
        request_ref=request_ref,
        snapshot_ref=snapshot_ref,
        model_dump=lambda **_kwargs: {"run_id": snapshot.run_id},
    )

    class FakeArtifacts:
        def get_json(self, target: ArtifactRef, model: object) -> Any:
            del model
            return {snapshot_ref: snapshot, job_ref: job}[target]

        def list_events_for_run(self, *_args: object, **_kwargs: object) -> tuple[()]:
            return ()

        def list_revisions(self, *_args: object, **_kwargs: object) -> tuple[()]:
            return ()

    reader = DirectRunReader(
        SimpleNamespace(read_head=lambda _request_id: head),  # type: ignore[arg-type]
        FakeArtifacts(),  # type: ignore[arg-type]
        SimpleNamespace(active_work=lambda _run_id: ()),  # type: ignore[arg-type]
        heads,
    )

    usage = reader.inspect("request:scheduler-live")["active_work"]["usage"]

    assert usage["projection_source"] == "scheduler_scope_lease_ledger"
    assert usage["observed_actual"]["llm_tokens"] == 240
    assert usage["unknown_upper_bound"]["llm_tokens"] == 40
    assert usage["conservative_committed"]["llm_tokens"] == 280
    assert usage["active_lease_count"] == 1
    assert usage["active_reserved_exposure"]["llm_tokens"] == 500
    assert usage["active_reserved_exposure"]["agent_turns"] == 2
    assert usage["active_reserved_exposure"]["wall_seconds"] == 60


def test_metrics_cli_exposes_multi_run_summary_and_baseline_comparison() -> None:
    summarized = build_parser().parse_args(
        [
            "metrics",
            "summarize",
            "--trace-id",
            "run:one",
            "--trace-id",
            "run:two",
        ]
    )
    compared = build_parser().parse_args(
        [
            "metrics",
            "compare",
            "--trace-id",
            "run:baseline",
            "--trace-id",
            "run:candidate",
        ]
    )

    assert summarized.metrics_command == "summarize"
    assert summarized.trace_id == ["run:one", "run:two"]
    assert compared.metrics_command == "compare"
    assert compared.trace_id == ["run:baseline", "run:candidate"]


def test_feedback_cli_accepts_only_closed_aggregate_signals() -> None:
    raw = json.dumps(
        {
            "signal_type": "coverage_gap",
            "capability_dimension": "inventory.reconciliation",
            "sample_count": 20,
            "confidence": 0.9,
            "gap": "low_success",
            "severity": 0.35,
        }
    )
    parsed = build_parser().parse_args(
        ["feedback", "record", "suite_abc", "--signal", raw]
    )
    signal = _parse_capability_signal(parsed.signal[0])

    assert parsed.feedback_command == "record"
    assert parsed.snapshot_id == "suite_abc"
    assert signal.signal_type == "coverage_gap"
    assert signal.capability_dimension == "inventory.reconciliation"

    with pytest.raises(ValueError, match="JSON object"):
        _parse_capability_signal("[]")


def test_suite_cli_errors_are_single_machine_readable_json_objects(tmp_path: Path) -> None:
    config_path = tmp_path / "foundry.toml"
    config_path.write_text(
        "\n".join(
            (
                'state_root = "state"',
                "",
                "[agent]",
                'model = "configured-real-model"',
                'api_key_environment = "AGENT_WORLD_UNUSED_MODEL_KEY"',
                "",
                "[research]",
                'provider = "searxng"',
                'searxng_base_url = "http://127.0.0.1:18080"',
                "searxng_allow_private_endpoint = true",
                "use_jina_reader_fallback = false",
                "",
            )
        ),
        encoding="utf-8",
    )
    completed = subprocess.run(  # noqa: S603 - fixed interpreter and module
        (
            sys.executable,
            "-m",
            "agent_world.cli",
            "--config",
            str(config_path),
            "suite",
            "inspect",
            f"suite_{'0' * 64}",
        ),
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )

    assert completed.returncode == 1
    assert completed.stdout == ""
    error = json.loads(completed.stderr)
    assert error["error"]["code"] == "registry"
    assert isinstance(error["error"]["message"], str)


def test_registry_list_is_offline_json_and_does_not_require_model_auth(tmp_path: Path) -> None:
    environment_name = "AGENT_WORLD_TEST_UNAVAILABLE_MODEL_KEY"
    config_path = tmp_path / "foundry.toml"
    config_path.write_text(
        "\n".join(
            (
                'state_root = "state"',
                "",
                "[agent]",
                'model = "configured-real-model"',
                f'api_key_environment = "{environment_name}"',
                "",
                "[research]",
                'provider = "searxng"',
                'searxng_base_url = "http://127.0.0.1:18080"',
                "searxng_allow_private_endpoint = true",
                "use_jina_reader_fallback = false",
                "",
            )
        ),
        encoding="utf-8",
    )
    environment = dict(os.environ)
    environment.pop(environment_name, None)
    completed = subprocess.run(  # noqa: S603 - fixed interpreter and module
        (
            sys.executable,
            "-m",
            "agent_world.cli",
            "--config",
            str(config_path),
            "registry",
            "list",
        ),
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
        env=environment,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stderr == ""
    assert json.loads(completed.stdout) == {"count": 0, "releases": []}
    assert (tmp_path / "state" / "registry" / "index.json").is_file()
