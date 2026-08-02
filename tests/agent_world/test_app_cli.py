from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import HttpUrl
from v3_fixture import build_judge_candidate_graph

from agent_world.agent_profiles import AgentProfileProvider
from agent_world.app import (
    ApplicationConfigurationError,
    DirectRunReader,
    build_application,
    open_consumption,
)
from agent_world.artifact_store import ArtifactStore, ArtifactStoreError, UnsafeArtifactError
from agent_world.builder import BuilderWorkspaceProgress, EnvironmentBuilder
from agent_world.cli import (
    _parse_capability_signal,
    _parse_rollout_action,
    _parse_suite_selection,
    _run_cli_coroutine,
    build_parser,
)
from agent_world.config import AgentBackendConfig, FoundryConfig, JudgeConfig, ResearchConfig
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
    LeaseBudgetLedger,
    NodeAttempt,
    TelemetryStore,
    WorkControlRuntime,
    WorkControlStore,
)
from agent_world.control.work import (
    OperationRun,
    ProposalExecution,
    ValidationIssue,
    ValidationReport,
    WorkAttempt,
    WorkCoordinate,
    WorkDefinition,
)
from agent_world.control.work_graph import tool_semantics_batch_definition
from agent_world.controller import FoundryController
from agent_world.designer import (
    EnvironmentDesigner,
    ExpansionDesigner,
    ExpansionSourceRouter,
)
from agent_world.invocation import InvocationControlPlane, InvocationControlStore
from agent_world.judge import (
    EnvironmentJudge,
    InteractiveChallengerStrategy,
    VerifierCompiler,
)
from agent_world.observability import (
    ObservabilityRoot,
    SceneProjector,
    runtime_subprocess_scene,
)
from agent_world.registry import EnvironmentRegistry


def _filesystem_config(tmp_path: Path) -> FoundryConfig:
    return FoundryConfig(
        state_root=tmp_path / "state",
        agent=AgentBackendConfig(
            model="configured-real-model",
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


def test_cli_runner_bounds_post_terminal_default_executor_shutdown() -> None:
    """A settled Direct failure must not spend asyncio's default 300-second grace.

    This simulates only a stuck SDK-owned executor thread after the coroutine
    has already returned.  It does not model a Provider call or change its
    lifetime policy.
    """

    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()

    def blocked_executor_work() -> None:
        started.set()
        release.wait()
        finished.set()

    async def settled_command() -> str:
        asyncio.get_running_loop().run_in_executor(None, blocked_executor_work)
        while not started.is_set():
            await asyncio.sleep(0)
        return "settled"

    try:
        started_at = time.monotonic()
        with pytest.warns(RuntimeWarning, match="executor did not finishing joining"):
            result = _run_cli_coroutine(
                settled_command(),
                executor_shutdown_seconds=0.01,
            )
        elapsed = time.monotonic() - started_at
    finally:
        release.set()

    assert result == "settled"
    assert elapsed < 1
    assert finished.wait(timeout=1)


def _observe_execution(attempt: WorkAttempt, definition: WorkDefinition) -> ProposalExecution:
    now = datetime.now(UTC)
    actual = BudgetUsage(llm_tokens=100, agent_turns=1, monetary_cost=0.1)
    return ProposalExecution(
        execution_id=f"execution:observe:{attempt.ordinal}",
        attempt_id=attempt.attempt_id,
        executor="agent",
        operation=definition.proposal_policy.operation,
        status="completed",
        invocation_id=f"invocation:observe:{attempt.ordinal}",
        provider="openai",
        model="gpt-5.4-mini",
        profile_digest=sha256_digest(b"observe-profile"),
        output_schema_digest=sha256_digest(b"observe-schema"),
        output_commitment=sha256_digest(f"observe:{attempt.ordinal}".encode()),
        continuation_commitment=sha256_digest(b"observe-continuation"),
        observed_actual=actual,
        conservative_committed=actual,
        started_at=now,
        finished_at=now + timedelta(milliseconds=10),
        duration_ms=10,
    )


def _seed_observe_scope(tmp_path: Path, canary: str) -> tuple[str, str, WorkControlStore]:
    """Create a real typed Candidate/source closure and failed WorkAttempt.

    This fixture exercises the same source tar, BuildRecord, WorkControl CAS,
    Tier B event and pure projector path that the CLI reads.  It deliberately
    does not fabricate a production success path.
    """

    state_root = tmp_path / "state"
    store = ArtifactStore(state_root / "artifacts", known_secret_canaries=(canary,))
    fixture_root = tmp_path / "candidate-fixture"
    fixture_root.mkdir()
    candidate_graph = build_judge_candidate_graph(fixture_root, store)
    artifacts = store.issue_writer(
        producer="work-controller",
        allowed_artifact_type_prefixes=("control.",),
    )
    heads = WorkControlStore(state_root / "work-control")
    telemetry = TelemetryStore(state_root / "telemetry")
    projector = SceneProjector(
        root=ObservabilityRoot(state_root),
        artifacts=artifacts,
        heads=heads,
        telemetry=telemetry,
        known_secret_canaries=(canary,),
    )
    runtime = WorkControlRuntime(
        artifacts=artifacts,
        heads=heads,
        budget=LeaseBudgetLedger(
            Budget(
                llm_tokens=10_000,
                agent_turns=5,
                repair_attempts=3,
                tool_calls=10,
                process_calls=10,
                evaluation_episodes=10,
                wall_seconds=1_000,
                monetary_cost=5,
            )
        ),
        telemetry=telemetry,
        projector=projector,
        trace_id="trace:observe-cli",
        run_id="run:observe-cli",
    )
    scope_id = "job:observe-cli"
    base = tool_semantics_batch_definition(
        job_id=scope_id,
        group_id="group:observe",
        batch_id="batch:observe",
        dependency_coordinates=(),
        agent_wall_seconds=120,
        agent_token_limit=1_000,
        agent_monetary_limit=1,
    )
    coordinate = WorkCoordinate(
        scope_id=scope_id,
        component="integration",
        stage="runtime_integration",
        artifact_slot="integration_report",
    )
    definition = WorkDefinition.model_validate(
        base.model_copy(update={"coordinate": coordinate}).model_dump(mode="python")
    )

    with heads.exclusive(definition.coordinate) as lock:
        head = runtime.begin(
            lock,
            definition=definition,
            input_refs=(candidate_graph.design_ref, candidate_graph.candidate_ref),
            elapsed_wall_seconds=0,
        )
        attempt = artifacts.get_json(head.attempt_ref, WorkAttempt)
        assert attempt.telemetry_trace_id is not None
        subprocess_payload = runtime_subprocess_scene(
            operation="handshake",
            exit_code=17,
            stderr="candidate runtime exited before response",
            launch_argv=(".venv/bin/python", "-m", "runtime"),
            known_secret_canaries=(canary,),
        ).telemetry_payload()
        subprocess_payload["coordinate_key"] = definition.coordinate.coordinate_key
        telemetry.record_event(
            trace_id=attempt.telemetry_trace_id,
            event_type="runtime_subprocess_scene",
            payload=subprocess_payload,
        )
        runtime.schedule_operation(
            lock,
            definition=definition,
            kind="proposal",
            replay_mode="queryable",
            elapsed_wall_seconds=0,
        )
        head = runtime.start_operation(
            lock,
            definition=definition,
            dispatch_id=f"invocation:observe:{attempt.ordinal}",
        )
        operation = artifacts.get_json(head.active_operation_ref, OperationRun)
        assert operation.started_at is not None
        execution = _observe_execution(
            artifacts.get_json(head.attempt_ref, WorkAttempt),
            definition,
        ).model_copy(
            update={
                "started_at": operation.started_at,
                "finished_at": operation.started_at + timedelta(milliseconds=10),
            }
        )
        head = runtime.checkpoint_proposal(
            lock,
            definition=definition,
            execution=execution,
        )
        current_attempt = artifacts.get_json(head.attempt_ref, WorkAttempt)
        report = ValidationReport(
            report_id="report:observe-cli",
            attempt_id=current_attempt.attempt_id,
            coordinate=definition.coordinate,
            policy_id=definition.validation_policy.policy_id,
            policy_digest=definition.validation_policy.content_digest(),
            status="failed",
            validation_phase=definition.validation_policy.validation_phase,
            frontier_ordinal=20,
            issues=(
                ValidationIssue(
                    code="integration_gate_runtime_protocol_fail",
                    path=("integration", "gate", 0),
                    violated_condition="Runtime handshake crashed before a response.",
                    expected_category="the frozen Runtime v2 handshake contract",
                ),
            ),
            diagnostic_quality="actionable",
            evaluated_at=datetime.now(UTC),
        )
        runtime.schedule_operation(
            lock,
            definition=definition,
            kind="validation",
            replay_mode="deterministic",
            elapsed_wall_seconds=0,
        )
        runtime.start_operation(
            lock,
            definition=definition,
            dispatch_id="observe-validation",
        )
        head = runtime.checkpoint_validation(
            lock,
            definition=definition,
            report=report,
            observed_actual=BudgetUsage(),
        )
        head = runtime.evaluate(
            lock,
            definition=definition,
            report=report,
            elapsed_wall_seconds=0,
        )
    assert head.status == "repair_authorized"
    telemetry.close()
    return scope_id, definition.coordinate.coordinate_key, heads


def test_production_app_assembles_real_components_and_secret_canaries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canary = "credential-canary-A19xQ7mR"
    routing_canary = "https://provider.example.test/v1"
    monkeypatch.setenv("OPENAI_API_KEY", canary)
    monkeypatch.setenv("OPENAI_BASE_URL", routing_canary)
    config = _filesystem_config(tmp_path)
    app = build_application(
        config.model_copy(
            update={"agent": config.agent.model_copy(update={"max_concurrent_invocations": 2})}
        )
    )

    assert isinstance(app.profiles, AgentProfileProvider)
    assert isinstance(app.backend, InvocationControlPlane)
    assert app.backend.require_explicit_ownership
    assert isinstance(app.invocation_control, InvocationControlStore)
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
    assert app.controller.direct_work_runner is not None
    assert app.controller.direct_work_runner.maximum_concurrency == 2
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
    with pytest.raises(UnsafeArtifactError):
        app.controller.artifacts.put_blob(
            artifact_id="routing-leak-attempt",
            artifact_type="control.security_probe",
            content=f"prefix {routing_canary} suffix".encode(),
            media_type="text/plain",
        )


def test_missing_base_url_environment_never_contains_credential_material(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canary = "credential-that-must-not-appear-B72kL9"
    monkeypatch.setenv("OPENAI_API_KEY", canary)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    with pytest.raises(ApplicationConfigurationError) as captured:
        build_application(_filesystem_config(tmp_path))

    assert canary not in str(captured.value)
    assert "routing" in str(captured.value)


def test_invalid_judge_cache_is_a_safe_application_configuration_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both clean-builder assembly paths preserve a useful, secret-safe cause."""

    credential = "credential-that-must-not-appear-H38sL2"
    routing_canary = "https://provider.example.test/v1"
    missing_cache = tmp_path / "missing-uv-cache"
    monkeypatch.setenv("OPENAI_API_KEY", credential)
    monkeypatch.setenv("OPENAI_BASE_URL", routing_canary)
    config = _filesystem_config(tmp_path).model_copy(
        update={"judge": JudgeConfig(uv_cache_dir=missing_cache)}
    )

    for assemble in (build_application, open_consumption):
        with pytest.raises(ApplicationConfigurationError) as captured:
            assemble(config)

        message = str(captured.value)
        assert "judge clean-build configuration" in message
        assert "judge.uv_cache_dir" in message
        assert str(missing_cache) not in message
        assert credential not in message
        assert routing_canary not in message


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


def test_observe_cli_exposes_phase_four_query_syntax() -> None:
    parser = build_parser()

    frontier_diff = parser.parse_args(
        [
            "observe",
            "frontier-diff",
            "job:alpha",
            "sha256:" + "a" * 64,
            "--from",
            "1",
            "--to",
            "2",
        ]
    )
    comparison = parser.parse_args(
        ["observe", "compare", "--scope", "job:alpha", "--scope", "job:beta"]
    )
    replay = parser.parse_args(["observe", "replay", "job:alpha", "sha256:" + "b" * 64])

    assert frontier_diff.from_attempt_ordinal == 1
    assert frontier_diff.to_attempt_ordinal == 2
    assert comparison.scope_ids == ["job:alpha", "job:beta"]
    assert replay.coordinate == "sha256:" + "b" * 64


def test_observe_cli_rebuilds_stale_scene_and_reads_real_candidate_contract(
    tmp_path: Path,
) -> None:
    canary = "observe-cli-model-canary"
    scope_id, coordinate_key, heads = _seed_observe_scope(tmp_path, canary)
    config_path = tmp_path / "foundry.toml"
    config_path.write_text(
        "\n".join(
            (
                'state_root = "state"',
                "",
                "[agent]",
                'model = "configured-real-model"',
                'api_key_environment = "AGENT_WORLD_OBSERVE_TEST_KEY"',
                "",
                "[research]",
                'provider = "searxng"',
                'searxng_base_url = "http://127.0.0.1:18080"',
                "searxng_allow_private_endpoint = true",
                "use_jina_reader_fallback = false",
            )
        ),
        encoding="utf-8",
    )
    environment = {**os.environ, "AGENT_WORLD_OBSERVE_TEST_KEY": canary}

    def observe(*arguments: str) -> dict[str, object]:
        completed = subprocess.run(  # noqa: S603 - fixed interpreter and local module
            (
                sys.executable,
                "-m",
                "agent_world.cli",
                "--config",
                str(config_path),
                "observe",
                *arguments,
            ),
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
            env=environment,
        )
        assert completed.returncode == 0, completed.stderr
        assert completed.stderr == ""
        parsed = json.loads(completed.stdout)
        assert isinstance(parsed, dict)
        return parsed

    scene = observe("scene", "--latest")
    assert scene["cache_status"] == "hit"
    assert scene["stuck_coordinate"] is not None

    candidate = observe("candidate", scope_id, coordinate_key)
    assert candidate["path"] == "runtime.py"
    assert "counter" in str(candidate["source"])
    assert candidate["read_only"] is True

    contract = observe("contract", scope_id, coordinate_key)
    assert contract["read_only_reference"] is True
    assert contract["do_not_modify"] == ["world_spec", "gate"]
    tool_surface = contract["world_spec_tool_surface"]
    assert isinstance(tool_surface, list)
    assert tool_surface[0]["tool_id"] == "counter.increment"

    subprocess_scene = observe("subprocess", scope_id, coordinate_key)
    assert subprocess_scene["subprocess"]["exit_code"] == 17
    assert "before response" in subprocess_scene["subprocess"]["stderr_tail"]

    replay = observe("replay", scope_id, coordinate_key)
    assert replay["source"] == "tier_b_telemetry"
    assert replay["attempts"][0]["status"] == "failed"

    current = heads.read_head(
        WorkCoordinate(
            scope_id=scope_id,
            component="integration",
            stage="runtime_integration",
            artifact_slot="integration_report",
        )
    )
    assert current is not None
    with heads.exclusive(current.coordinate) as lock:
        heads.compare_and_swap(
            lock,
            expected_head=current,
            next_head=current.model_copy(
                update={
                    "revision": current.revision + 1,
                    "status": "failed",
                    "repair_action_ref": None,
                    "updated_at": datetime.now(UTC),
                }
            ),
        )

    rebuilt = observe("scene", scope_id)
    assert rebuilt["cache_status"] == "rebuilt_after_stale_watermark"
    assert rebuilt["stale_cache_hint_suppressed"] is True
    assert rebuilt["next_action_hint"] is None
    assert rebuilt["overall_status"] == "failed"


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
        scope_id="job:live",
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
        "activity_classification_available": True,
        "observed_activity_event_counts": {
            "reasoning": 4,
            "agent_message": 1,
            "command": 8,
            "file_change": 2,
            "tool": 0,
            "other": 0,
            "unclassified": 0,
        },
        "observed_token_count": None,
    }
    reader = DirectRunReader(
        SimpleNamespace(read_head=lambda _request_id: head),  # type: ignore[arg-type]
        FakeArtifacts(),  # type: ignore[arg-type]
        SimpleNamespace(active_work=lambda _run_id: (telemetry_span,)),  # type: ignore[arg-type]
    )

    inspected = reader.inspect("request:live")
    active = inspected["active_work"]

    # AC2: inspect surfaces the persisted head.scope_id directly.
    assert inspected["scope_id"] == "job:live"
    assert isinstance(active, dict)
    assert active["builder_workspace"]["progress"]["file_count"] == 7
    assert active["usage"]["observed_actual"]["llm_tokens"] == 250
    assert active["usage"]["unknown_upper_bound"]["llm_tokens"] == 0
    assert active["usage"]["conservative_committed"]["llm_tokens"] == 250
    assert active["usage"]["active_reserved_exposure"]["llm_tokens"] == 1500
    assert active["usage"]["inflight_observed"]["activity_classification_available"] is True
    assert active["usage"]["inflight_observed"]["activity_event_counts"] == {
        "reasoning": 4,
        "agent_message": 1,
        "command": 8,
        "file_change": 2,
        "tool": 0,
        "other": 0,
        "unclassified": 0,
    }
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
    # A pre-migration head has no persisted scope_id; inspect must fall back to
    # the EnvironmentJob.job_id deref (AC2).
    head = SimpleNamespace(
        run_id=snapshot.run_id,
        job_ref=job_ref,
        scope_id=None,
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

    inspected = reader.inspect("request:scheduler-live")
    assert inspected["scope_id"] == job.job_id
    usage = inspected["active_work"]["usage"]

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
    parsed = build_parser().parse_args(["feedback", "record", "suite_abc", "--signal", raw])
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
