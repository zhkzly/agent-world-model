from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from v3_fixture import (
    JudgeCandidateGraph,
    build_judge_candidate_graph,
    build_release_graph,
    candidate_files,
    commit_judged_manifest,
    judge_writer,
    portable_counter_contracts,
    write_candidate_project,
)

from agent_world.artifact_store import ArtifactStore
from agent_world.consumer import LocalEnvServiceProcess, LocalRolloutConsumer
from agent_world.contracts import (
    Budget,
    EnvironmentPackageManifest,
    JudgeReport,
    RolloutAction,
    SuiteSelectionRequest,
    TaskMaterializerCall,
    candidate_source_tree_digest,
)
from agent_world.contracts.supply_chain import (
    StaticAssuranceEvidence,
    SupplyChainEvidence,
)
from agent_world.judge import (
    CandidateSandboxRunner,
    CleanCandidateBuilder,
    EnvironmentJudge,
    IsolationPolicy,
    IsolationUnavailable,
    LaunchContract,
    ProtocolViolation,
    RuntimeSupervisor,
    decode_response,
    make_request,
)
from agent_world.judge.service import (
    _candidate_failure_summary,
    _runtime_contract_mismatch_paths,
)
from agent_world.registry import EnvironmentRegistry
from agent_world.task_materialization import TaskMaterializerV3Compiler


async def _require_real_isolation(purpose: str = "runtime") -> IsolationPolicy:
    isolation = IsolationPolicy(purpose=purpose)  # type: ignore[arg-type]
    try:
        await isolation.ensure_available()
    except IsolationUnavailable as exc:
        pytest.skip(f"real bubblewrap isolation unavailable: {exc.code}: {exc}")
    return isolation


def _json_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {nested for item in value.values() for nested in _json_keys(item)}
    if isinstance(value, list):
        return {nested for item in value for nested in _json_keys(item)}
    return set()


def test_candidate_component_visibility_uses_public_source_dependency_lattice() -> None:
    manifest = SimpleNamespace(
        files=(
            SimpleNamespace(path="environment/runtime.py", role="runtime"),
            SimpleNamespace(path="environment/world.py", role="runtime"),
            SimpleNamespace(path="environment/materializer.py", role="task_materializer"),
            SimpleNamespace(path="environment/public_check.py", role="public_verifier"),
            SimpleNamespace(path="tests/test_public.py", role="public_test"),
            SimpleNamespace(path="pyproject.toml", role="configuration"),
        )
    )

    assert EnvironmentJudge._role_visible_paths(manifest, "runtime") == (  # type: ignore[arg-type]  # noqa: SLF001
        "environment/runtime.py",
        "environment/world.py",
    )
    assert EnvironmentJudge._role_visible_paths(  # type: ignore[arg-type]  # noqa: SLF001
        manifest,
        "task_materializer",
    ) == (
        "environment/materializer.py",
        "environment/runtime.py",
        "environment/world.py",
    )
    assert EnvironmentJudge._role_visible_paths(  # type: ignore[arg-type]  # noqa: SLF001
        manifest,
        "public_verifier",
    ) == (
        "environment/materializer.py",
        "environment/public_check.py",
        "environment/runtime.py",
        "environment/world.py",
    )


def test_runtime_contract_diff_reports_all_repair_coordinates(tmp_path: Path) -> None:
    world_spec = portable_counter_contracts(
        ArtifactStore(tmp_path / "contract-artifacts")
    ).design.world_spec
    surface = world_spec.tools[0].surface
    observed = {
        "tool_id": surface.tool_id,
        "namespace": surface.namespace,
        "name": "wrong-name",
        "input_schema": {"type": "string"},
        "output_schema": surface.output_schema,
        "observation_schema": {"type": "null"},
    }

    assert _runtime_contract_mismatch_paths([observed], world_spec) == (
        "tools[counter.increment].name",
        "tools[counter.increment].input_schema",
        "tools[counter.increment].observation_schema",
    )


def test_runtime_contract_diff_reports_shape_id_and_duplicate_errors(tmp_path: Path) -> None:
    world_spec = portable_counter_contracts(
        ArtifactStore(tmp_path / "contract-artifacts")
    ).design.world_spec
    surface = world_spec.tools[0].surface
    valid = {
        "tool_id": surface.tool_id,
        "namespace": surface.namespace,
        "name": surface.name,
        "input_schema": surface.input_schema,
        "output_schema": surface.output_schema,
        "observation_schema": surface.observation_schema,
    }

    assert _runtime_contract_mismatch_paths(
        [valid, valid, {"tool_id": "extra.tool"}, None, {"name": "missing-id"}],
        world_spec,
    ) == (
        "tools[3][type=object]",
        "tools[4].tool_id[type=non-empty-string]",
        "tools[extra.tool][unexpected]",
        "tools[counter.increment][duplicate:2]",
    )
    assert _runtime_contract_mismatch_paths({"not": "an array"}, world_spec) == (
        "tools[type=array]",
    )


def test_protocol_failure_summary_preserves_missing_and_extra_coordinates() -> None:
    failure = ProtocolViolation(
        "schema_mismatch",
        "response.result[handshake].tools[0] has invalid keys",
        details={"missing": ["name"], "extra": ["schema_version", "transport"]},
    )

    assert _candidate_failure_summary(failure) == (
        "response.result[handshake].tools[0] has invalid keys; missing=name; "
        "extra=schema_version,transport"
    )


async def _evaluate_real_judge_graph(
    *,
    state_root: Path,
    store: ArtifactStore,
    graph: JudgeCandidateGraph,
    run_id: str,
) -> JudgeReport:
    """Run a Builder-shaped candidate through the real clean-build Judge path."""

    judge = EnvironmentJudge(
        artifact_store=judge_writer(store),
        clean_builder=CleanCandidateBuilder(
            build_isolation=await _require_real_isolation("build"),
            uv_path=graph.uv_path,
            uv_cache_dir=graph.uv_cache_dir,
            timeout_seconds=60,
        ),
        runtime_isolation=await _require_real_isolation(),
    )
    budget = judge.required_evaluation_budget(
        design=graph.design,
        verifier=graph.verifier,
        available=Budget(container_seconds=600, wall_seconds=600),
    )
    judged = await judge.evaluate(
        candidate=graph.candidate,
        candidate_ref=graph.candidate_ref,
        source_dir=graph.workspace,
        world_spec=graph.design.world_spec,
        world_spec_ref=graph.world_spec_ref,
        verifier=graph.verifier,
        verifier_ref=graph.verifier_ref,
        release_profile=graph.release_profile,
        budget=budget,
        reachability_workspace=state_root / f"reachability-{run_id}",
        run_id=run_id,
    )
    return judged.report


@pytest.mark.asyncio
async def test_integration_runs_before_verifier_and_cannot_authorize_release(
    tmp_path: Path,
) -> None:
    """Build readiness uses real isolation but carries no release authority."""

    store = ArtifactStore(tmp_path / "artifacts")
    graph = build_judge_candidate_graph(tmp_path, store)
    judge = EnvironmentJudge(
        artifact_store=judge_writer(store),
        clean_builder=CleanCandidateBuilder(
            build_isolation=await _require_real_isolation("build"),
            uv_path=graph.uv_path,
            uv_cache_dir=graph.uv_cache_dir,
            timeout_seconds=60,
        ),
        runtime_isolation=await _require_real_isolation(),
    )
    budget = judge.required_integration_budget(
        design=graph.design,
        available=Budget(container_seconds=600, wall_seconds=600),
    )

    integrated = await judge.evaluate_integration(
        candidate=graph.candidate,
        candidate_ref=graph.candidate_ref,
        source_dir=graph.workspace,
        world_spec=graph.design.world_spec,
        world_spec_ref=graph.world_spec_ref,
        release_profile=graph.release_profile,
        budget=budget,
        run_id="integration-before-verifier",
    )

    assert integrated.report.status == "ready", [
        (item.gate_id, item.status, item.summary)
        for item in integrated.report.gate_results
    ] + [
        (item.category, item.suggested_repair) for item in integrated.report.findings
    ]
    assert integrated.report_ref.artifact_type == "judge.integration_report"
    assert {item.gate_id for item in integrated.report.gate_results} == {
        "schema",
        "supply_chain",
        "static_assurance",
        "public_self_check",
        "runtime_protocol",
        "task_materialization",
        "clean_deployment",
    }
    assert all(item.status == "pass" for item in integrated.report.gate_results)


@pytest.mark.asyncio
async def test_role_file_view_rejects_escape_and_symlink_paths(tmp_path: Path) -> None:
    isolation = await _require_real_isolation()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / ".venv").mkdir()
    (workspace / "runtime.py").write_text("pass\n", encoding="utf-8")
    (workspace / "real").mkdir()
    (workspace / "real" / "module.py").write_text("pass\n", encoding="utf-8")
    (workspace / "runtime-link.py").symlink_to("runtime.py")
    (workspace / "linked-parent").symlink_to("real", target_is_directory=True)
    state = tmp_path / "state"
    state.mkdir()

    for visible_path in ("../runtime.py", "runtime-link.py", "linked-parent/module.py"):
        with pytest.raises(IsolationUnavailable):
            isolation.wrap_command(
                workspace=workspace,
                cwd_relative=".",
                argv=("/usr/bin/true",),
                state_dir=state,
                visible_workspace_paths=(visible_path,),
            )


@pytest.mark.asyncio
async def test_clean_build_and_runtime_supervisor_execute_complete_abi_v2(
    tmp_path: Path,
) -> None:
    source, uv_path, uv_cache = write_candidate_project(tmp_path)
    runtime_isolation = await _require_real_isolation()
    build_isolation = await _require_real_isolation("build")
    builder = CleanCandidateBuilder(
        build_isolation=build_isolation,
        uv_path=uv_path,
        uv_cache_dir=uv_cache,
        timeout_seconds=60,
    )
    files = candidate_files(source)
    source_digest = candidate_source_tree_digest(files)

    async with builder.materialize(
        source,
        expected_source_files=files,
        expected_source_tree_digest=source_digest,
    ) as candidate:
        assert candidate.install.success
        assert candidate.candidate_source_tree_digest == source_digest
        assert candidate.root != source
        interpreter = candidate.root / ".venv" / "bin" / "python"
        assert interpreter.is_symlink()
        assert os.readlink(interpreter) == "/opt/agent-world/python/bin/python3.12"

        supervisor = RuntimeSupervisor(
            candidate.root,
            LaunchContract(argv=(".venv/bin/python", "runtime.py")),
            visible_workspace_paths=("runtime.py",),
            isolation=runtime_isolation,
            request_timeout_seconds=5,
        )
        handshake = await supervisor.start()
        assert handshake.ok
        assert handshake.result is not None
        assert handshake.result["runtime_id"] == "counter-runtime-v3"
        tools = handshake.result["tools"]
        assert isinstance(tools, list)
        first_tool = tools[0]
        assert isinstance(first_tool, dict)
        assert first_tool["tool_id"] == "counter.increment"

        reset = await supervisor.reset(seed=41, actor="user", config={"initial": 2})
        assert reset.result is not None
        assert reset.result["observation"] == {"counter": {"value": 2}}
        reset_digest = reset.result["state_digest"]

        first = await supervisor.invoke(
            tool="counter.increment",
            args={"amount": 3},
            idempotency_key="increment-once",
        )
        assert first.result is not None
        assert first.result["tool_result"] == {"value": 5}
        assert first.result["state_digest"] != reset_digest

        repeated = await supervisor.invoke(
            tool="counter.increment",
            args={"amount": 3},
            idempotency_key="increment-once",
        )
        assert repeated.result == first.result

        snapshot = await supervisor.snapshot()
        assert snapshot.result is not None
        assert snapshot.result["observation"] == {"counter": {"value": 5}}
        assert snapshot.result["state_digest"] == first.result["state_digest"]

        unknown = await supervisor.invoke(
            tool="counter.missing",
            args={},
            idempotency_key="unknown-tool",
        )
        assert not unknown.ok
        assert unknown.error is not None
        assert unknown.error.code == "unknown_tool"

        await supervisor.reset(seed=41, actor="auditor", config={"initial": 2})
        denied_before = await supervisor.snapshot()
        denied = await supervisor.invoke(
            tool="counter.increment",
            args={"amount": 3},
            idempotency_key="auditor-denied",
        )
        denied_after = await supervisor.snapshot()
        assert not denied.ok
        assert denied.error is not None and denied.error.code == "permission_denied"
        assert denied.result is not None and denied.result["observation"] == {}
        assert denied_before.result is not None and denied_after.result is not None
        assert denied_before.result["state_digest"] == denied_after.result["state_digest"]

        closed = await supervisor.close()
        assert closed is not None and closed.ok
        assert supervisor.pid is None

        async def reset_in_fresh_process(seed: int) -> dict[str, object]:
            async with RuntimeSupervisor(
                candidate.root,
                LaunchContract(argv=(".venv/bin/python", "runtime.py")),
                visible_workspace_paths=("runtime.py",),
                isolation=runtime_isolation,
                request_timeout_seconds=5,
            ) as fresh:
                response = await fresh.reset(
                    seed=seed,
                    actor="user",
                    config={"initial": seed % 97},
                )
                assert response.result is not None
                return dict(response.result)

        replay_first = await reset_in_fresh_process(11_000_001)
        replay_second = await reset_in_fresh_process(11_000_001)
        different_seed = await reset_in_fresh_process(11_000_002)
        assert replay_first == replay_second
        assert replay_first["state_digest"] != different_seed["state_digest"]


@pytest.mark.asyncio
async def test_candidate_materializer_is_public_only_and_framework_compiles_goal(
    tmp_path: Path,
) -> None:
    source, uv_path, uv_cache = write_candidate_project(tmp_path)
    isolation = await _require_real_isolation()
    builder = CleanCandidateBuilder(
        build_isolation=await _require_real_isolation("build"),
        uv_path=uv_path,
        uv_cache_dir=uv_cache,
        timeout_seconds=60,
    )
    store = ArtifactStore(tmp_path / "contracts")
    portable = portable_counter_contracts(store)
    compiler = TaskMaterializerV3Compiler(portable.design.curriculum)
    calls = (
        TaskMaterializerCall(
            seed=8_459_123,
            task_type="increase_counter",
            actor="user",
            difficulty={"scale": "small"},
        ),
        TaskMaterializerCall(
            seed=9_912_731,
            task_type="increase_counter",
            actor="user",
            difficulty={"scale": "large"},
        ),
    )

    assert "task_materializer" not in sys.modules
    async with builder.materialize(source) as candidate:
        runner = CandidateSandboxRunner(
            isolation=isolation,
            timeout_seconds=10,
            max_output_bytes=128 * 1024,
        )
        first = await runner.run_task_materializer(
            candidate.root,
            entrypoint="task_materializer:materialize",
            calls=tuple(call.call_arguments() for call in calls),
            visible_workspace_paths=("runtime.py", "task_materializer.py"),
        )
        second = await runner.run_task_materializer(
            candidate.root,
            entrypoint="task_materializer:materialize",
            calls=tuple(call.call_arguments() for call in calls),
            visible_workspace_paths=("runtime.py", "task_materializer.py"),
        )
        assert first.succeeded, (first.failure_class, first.stderr)
        assert second.succeeded, (second.failure_class, second.stderr)
        assert json.loads(first.stdout) == json.loads(second.stdout)
        payload = json.loads(first.stdout)
        assert payload["protocol"] == "agent-world.task-materializer-runner.v3"
        materializations = payload["materializations"]
        assert len(materializations) == 2
        assert set(materializations[0]) == {
            "schema_version",
            "task_schema_version",
            "seed",
            "task_type",
            "actor",
            "difficulty",
            "public_goal",
            "initial_config",
        }
        envelope = compiler.materialize(calls[0], materializations[0])
        assert envelope.evaluator_goal == materializations[0]["public_goal"]
        assert envelope.public_instruction.startswith(
            "Increase the counter until the public target is reached."
        )

        public_check = await runner.run(
            candidate.root,
            argv=(".venv/bin/python", "-m", "public_check"),
            visible_workspace_paths=(
                "runtime.py",
                "task_materializer.py",
                "public_check.py",
            ),
            timeout_seconds=10,
            max_output_bytes=128 * 1024,
            failure_prefix="public_self_check",
        )
        assert public_check.succeeded, (public_check.failure_class, public_check.stderr)
        assert json.loads(public_check.stdout) == {
            "network_required": False,
            "status": "pass",
        }

    assert "task_materializer" not in sys.modules


@pytest.mark.asyncio
async def test_released_envpkg_v3_runs_framework_consumer_and_rpc_process(
    tmp_path: Path,
) -> None:
    state_root = tmp_path / "state"
    store = ArtifactStore(state_root / "artifacts")
    graph = build_release_graph(state_root, store)
    runtime_isolation = await _require_real_isolation()
    builder = CleanCandidateBuilder(
        build_isolation=await _require_real_isolation("build"),
        uv_path=graph.uv_path,
        uv_cache_dir=graph.uv_cache_dir,
        timeout_seconds=60,
    )
    registry = EnvironmentRegistry(state_root / "registry", store)
    reservation = registry.reserve_package_version(
        graph.package_id,
        graph.version,
        graph.owner_ref,
    )
    prepared = registry.prepare(
        candidate_workspace=graph.workspace,
        manifest_ref=graph.manifest_ref,
        judge_report_ref=graph.report_ref,
        release_profile=graph.release_profile,
        reservation=reservation,
        framework_payloads=graph.framework_payloads,
    )
    release = registry.publish(prepared)
    snapshot = registry.create_suite_snapshot(
        (
            SuiteSelectionRequest(
                package_id=release.coordinate.package_id,
                version=release.coordinate.version,
            ),
        )
    )
    manifest = store.get_json(graph.manifest_ref, EnvironmentPackageManifest)
    declared = {item.path: item.role for item in manifest.files}
    assert declared["tasks/materializer_protocol.json"] == "materializer_protocol"
    assert declared["tasks/curriculum.json"] == "curriculum"
    assert declared["world/rule_ir.json"] == "rule_ir"
    assert declared["world/world_spec.json"] == "world_spec"

    consumer = LocalRolloutConsumer(
        registry=registry,
        clean_builder=builder,
        runtime_isolation=runtime_isolation,
    )
    episode = await consumer.start(snapshot.snapshot_id, seed=8_459_123)
    async with episode:
        started = episode.start_result()
        reset_view = started.reset.agent_view
        assert isinstance(reset_view, dict)
        observation = reset_view["observation"]
        assert isinstance(observation, dict)
        counter = observation["counter"]
        assert isinstance(counter, dict)
        initial = counter["value"]
        target = started.task.public_goal["target"]
        assert isinstance(initial, int) and isinstance(target, int)
        step = await episode.step(
            RolloutAction(
                tool_id="counter.increment",
                arguments={"amount": target - initial},
            )
        )
        rollout = episode.result()

    assert rollout.package.package_digest == release.coordinate.package_digest
    assert rollout.task.task_schema_version == "public-task-v3"
    assert rollout.task.actor == "user"
    assert step.reward == 1
    assert step.terminated and step.succeeded and not step.failed
    forbidden_consumer_keys = {
        "initial_config",
        "evaluator_goal",
        "rule_ir",
        "snapshot",
        "source_tree",
    }
    assert not (forbidden_consumer_keys & _json_keys(json.loads(rollout.stable_json())))

    config_path = tmp_path / "local-env-service.toml"
    config_path.write_text(
        "\n".join(
            (
                f'state_root = "{state_root.as_posix()}"',
                "",
                "[agent]",
                'model = "unused-by-local-consumer"',
                'api_key_environment = "AGENT_WORLD_UNUSED_MODEL_KEY"',
                "",
                "[research]",
                'provider = "searxng"',
                'searxng_base_url = "http://127.0.0.1:18080"',
                "searxng_allow_private_endpoint = true",
                "use_jina_reader_fallback = false",
                "",
                "[judge]",
                "clean_build_timeout_seconds = 60",
                f'uv_cache_dir = "{graph.uv_cache_dir.as_posix()}"',
                "",
            )
        ),
        encoding="utf-8",
    )
    config_path.chmod(0o600)
    service = await LocalEnvServiceProcess.launch(
        config_path=config_path,
        snapshot_id=snapshot.snapshot_id,
        seed=8_459_123,
    )
    async with service:
        assert service.pid != os.getpid()
        remote_started = await service.client.start()
        assert not (forbidden_consumer_keys & _json_keys(json.loads(remote_started.stable_json())))
        remote_reset = remote_started.reset.agent_view
        assert isinstance(remote_reset, dict)
        remote_observation = remote_reset["observation"]
        assert isinstance(remote_observation, dict)
        remote_counter = remote_observation["counter"]
        assert isinstance(remote_counter, dict)
        remote_initial = remote_counter["value"]
        remote_target = remote_started.task.public_goal["target"]
        assert isinstance(remote_initial, int) and isinstance(remote_target, int)
        remote_step = await service.client.step(
            RolloutAction(
                tool_id="counter.increment",
                arguments={"amount": remote_target - remote_initial},
            )
        )
        remote_result = await service.client.result()
        assert remote_step.reward == 1 and remote_step.terminated
        assert remote_result.succeeded
        await service.client.close()
    assert service.stderr == ""


@pytest.mark.asyncio
async def test_complete_environment_judge_report_releases_and_serves_over_rpc(
    tmp_path: Path,
) -> None:
    """Only the complete real Judge path may authorize this envpkg release."""

    state_root = tmp_path / "state"
    store = ArtifactStore(state_root / "artifacts")
    graph = build_judge_candidate_graph(state_root, store)
    runtime_isolation = await _require_real_isolation()
    clean_builder = CleanCandidateBuilder(
        build_isolation=await _require_real_isolation("build"),
        uv_path=graph.uv_path,
        uv_cache_dir=graph.uv_cache_dir,
        timeout_seconds=60,
    )
    judge = EnvironmentJudge(
        artifact_store=judge_writer(store),
        clean_builder=clean_builder,
        runtime_isolation=runtime_isolation,
    )
    integration_budget = judge.required_integration_budget(
        design=graph.design,
        available=Budget(container_seconds=600, wall_seconds=600),
    )
    integrated = await judge.evaluate_integration(
        candidate=graph.candidate,
        candidate_ref=graph.candidate_ref,
        source_dir=graph.workspace,
        world_spec=graph.design.world_spec,
        world_spec_ref=graph.world_spec_ref,
        release_profile=graph.release_profile,
        budget=integration_budget,
        run_id="judge-e2e-integration",
    )
    assert integrated.report.status == "ready", integrated.report.findings
    budget = judge.required_evaluation_budget(
        design=graph.design,
        verifier=graph.verifier,
        available=Budget(container_seconds=600, wall_seconds=600),
    )

    judged = await judge.evaluate(
        candidate=graph.candidate,
        candidate_ref=graph.candidate_ref,
        source_dir=graph.workspace,
        world_spec=graph.design.world_spec,
        world_spec_ref=graph.world_spec_ref,
        verifier=graph.verifier,
        verifier_ref=graph.verifier_ref,
        release_profile=graph.release_profile,
        budget=budget,
        reachability_workspace=state_root / "reachability",
        run_id="judge-e2e",
    )

    canonical_gates = (
        "schema",
        "supply_chain",
        "static_assurance",
        "public_self_check",
        "runtime_protocol",
        "task_materialization",
        "task_reachability",
        "behavior",
        "sealed_release",
        "clean_deployment",
    )
    assert judged.report.verdict == "pass", judged.report.findings
    assert tuple(result.gate_id for result in judged.report.gate_results) == canonical_gates
    assert all(result.hard and result.status == "pass" for result in judged.report.gate_results)
    assert not judged.report.findings

    manifest, manifest_ref, framework_payloads = commit_judged_manifest(
        store,
        graph,
        judged.report_ref,
        integrated.report_ref,
    )
    assert manifest.judge_report_ref == judged.report_ref
    registry = EnvironmentRegistry(state_root / "registry", store)
    reservation = registry.reserve_package_version(
        graph.package_id,
        graph.version,
        graph.owner_ref,
    )
    prepared = registry.prepare(
        candidate_workspace=graph.workspace,
        manifest_ref=manifest_ref,
        judge_report_ref=judged.report_ref,
        release_profile=graph.release_profile,
        reservation=reservation,
        framework_payloads=framework_payloads,
    )
    release = registry.publish(prepared)
    snapshot = registry.create_suite_snapshot(
        (
            SuiteSelectionRequest(
                package_id=release.coordinate.package_id,
                version=release.coordinate.version,
            ),
        )
    )

    consumer = LocalRolloutConsumer(
        registry=registry,
        clean_builder=clean_builder,
        runtime_isolation=runtime_isolation,
    )
    episode = await consumer.start(snapshot.snapshot_id, seed=17)
    async with episode:
        started = episode.start_result()
        reset_view = started.reset.agent_view
        assert isinstance(reset_view, dict)
        observation = reset_view["observation"]
        assert isinstance(observation, dict)
        counter = observation["counter"]
        assert isinstance(counter, dict)
        initial = counter["value"]
        target = started.task.public_goal["target"]
        assert isinstance(initial, int) and isinstance(target, int)
        local_step = await episode.step(
            RolloutAction(
                tool_id="counter.increment",
                arguments={"amount": target - initial},
            )
        )
        local_result = episode.result()
    assert local_step.reward == 1 and local_step.terminated and local_step.succeeded
    assert local_result.package.package_digest == release.coordinate.package_digest

    config_path = tmp_path / "judge-e2e-local-env-service.toml"
    config_path.write_text(
        "\n".join(
            (
                f'state_root = "{state_root.as_posix()}"',
                "",
                "[agent]",
                'model = "unused-by-local-consumer"',
                'api_key_environment = "AGENT_WORLD_UNUSED_MODEL_KEY"',
                "",
                "[research]",
                'provider = "searxng"',
                'searxng_base_url = "http://127.0.0.1:18080"',
                "searxng_allow_private_endpoint = true",
                "use_jina_reader_fallback = false",
                "",
                "[judge]",
                "clean_build_timeout_seconds = 60",
                f'uv_cache_dir = "{graph.uv_cache_dir.as_posix()}"',
                "",
            )
        ),
        encoding="utf-8",
    )
    config_path.chmod(0o600)
    service = await LocalEnvServiceProcess.launch(
        config_path=config_path,
        snapshot_id=snapshot.snapshot_id,
        seed=17,
    )
    async with service:
        remote_started = await service.client.start()
        remote_view = remote_started.reset.agent_view
        assert isinstance(remote_view, dict)
        remote_observation = remote_view["observation"]
        assert isinstance(remote_observation, dict)
        remote_counter = remote_observation["counter"]
        assert isinstance(remote_counter, dict)
        remote_initial = remote_counter["value"]
        remote_target = remote_started.task.public_goal["target"]
        assert isinstance(remote_initial, int) and isinstance(remote_target, int)
        remote_step = await service.client.step(
            RolloutAction(
                tool_id="counter.increment",
                arguments={"amount": remote_target - remote_initial},
            )
        )
        remote_result = await service.client.result()
        assert remote_step.reward == 1 and remote_step.terminated and remote_step.succeeded
        assert remote_result.package.package_digest == release.coordinate.package_digest
        await service.client.close()
    assert service.stderr == ""


@pytest.mark.asyncio
async def test_real_public_test_failure_blocks_release_with_typed_static_evidence(
    tmp_path: Path,
) -> None:
    state_root = tmp_path / "state"
    store = ArtifactStore(state_root / "artifacts")
    graph = build_judge_candidate_graph(
        state_root,
        store,
        public_test_source="raise SystemExit(7)\n",
    )

    report = await _evaluate_real_judge_graph(
        state_root=state_root,
        store=store,
        graph=graph,
        run_id="judge-public-test-failure",
    )

    gates = {result.gate_id: result for result in report.gate_results}
    assert report.verdict == "fail"
    assert gates["supply_chain"].status == "pass"
    assert gates["static_assurance"].status == "fail"
    assert "public_test.py" in gates["static_assurance"].summary
    evidence_ref = next(
        ref
        for ref in gates["static_assurance"].evidence_refs
        if ref.artifact_type == "judge.static_assurance_evidence"
    )
    evidence = store.get_json(evidence_ref, StaticAssuranceEvidence)
    assert evidence.status == "fail"
    assert evidence.failure_codes == ("static_public_test_failed",)
    assert len(evidence.public_tests) == 1
    assert evidence.public_tests[0].exit_code == 7
    assert not evidence.public_tests[0].passed


@pytest.mark.asyncio
async def test_unknown_root_license_blocks_release_with_typed_supply_evidence(
    tmp_path: Path,
) -> None:
    state_root = tmp_path / "state"
    store = ArtifactStore(state_root / "artifacts")
    graph = build_judge_candidate_graph(
        state_root,
        store,
        project_license=None,
    )

    report = await _evaluate_real_judge_graph(
        state_root=state_root,
        store=store,
        graph=graph,
        run_id="judge-unknown-root-license",
    )

    gates = {result.gate_id: result for result in report.gate_results}
    assert report.verdict == "fail"
    assert gates["supply_chain"].status == "fail"
    assert gates["static_assurance"].status == "pass"
    evidence_ref = next(
        ref
        for ref in gates["supply_chain"].evidence_refs
        if ref.artifact_type == "judge.supply_chain_evidence"
    )
    evidence = store.get_json(evidence_ref, SupplyChainEvidence)
    assert evidence.status == "fail"
    assert evidence.root_license is not None
    assert evidence.root_license.status == "unknown"
    assert evidence.candidate_license_files
    assert "supply_root_license_unknown" in evidence.failure_codes


@pytest.mark.parametrize(
    "framework_only_payload",
    [
        {"seed": 1, "actor": "user", "config": {"expected_answer": 5}},
        {"seed": 1, "actor": "user", "config": {"sealed_case": "case-7"}},
        {"seed": 1, "actor": "user", "config": {"verifier_ir": {"rule": "hidden"}}},
        {"seed": 1, "actor": "user", "config": {"evaluator_goal": {"target": 5}}},
        {"seed": 1, "actor": "user", "config": {"release_threshold": 0.9}},
    ],
)
def test_protocol_rejects_framework_evaluation_data_before_runtime_boundary(
    framework_only_payload: dict[str, object],
) -> None:
    with pytest.raises(ProtocolViolation) as error:
        make_request("reset", framework_only_payload)  # type: ignore[arg-type]
    assert error.value.code == "private_evaluation_data_rejected"


def test_protocol_allows_domain_fields_that_only_share_generic_words() -> None:
    request = make_request(
        "reset",
        {
            "seed": 1,
            "actor": "user",
            "config": {
                "expected_delivery_date": "2026-08-01",
                "release_date": "2026-07-31",
                "purchase_order_number": "PO-42",
            },
        },
    )
    assert request.payload["config"] == {
        "expected_delivery_date": "2026-08-01",
        "release_date": "2026-07-31",
        "purchase_order_number": "PO-42",
    }


def test_invoke_cannot_override_the_actor_bound_by_reset() -> None:
    with pytest.raises(ProtocolViolation) as error:
        make_request(
            "invoke",
            {
                "tool": "counter.increment",
                "args": {"amount": 1},
                "idempotency_key": "actor-forgery",
                "actor": "auditor",
            },
        )
    assert error.value.code == "schema_mismatch"


@pytest.mark.parametrize(
    ("operation", "request_payload", "result", "runtime_error", "expected_code"),
    [
        (
            "reset",
            {"seed": 1, "actor": "user", "config": {"initial": 0}},
            {
                "observation": {},
                "state_digest": "sha256:" + "0" * 64,
                "terminated": False,
                "info": {"hidden": True},
            },
            None,
            "unmodeled_reset_info",
        ),
        (
            "invoke",
            {"tool": "counter.increment", "args": {"amount": 1}, "idempotency_key": "k"},
            {
                "tool_result": {},
                "observation": {},
                "events": [{"hidden": True}],
                "state_digest": "sha256:" + "0" * 64,
                "reward": 0,
                "terminated": False,
                "truncated": False,
                "info": {},
            },
            None,
            "unmodeled_invoke_events",
        ),
        (
            "invoke",
            {"tool": "counter.increment", "args": {"amount": 1}, "idempotency_key": "k"},
            {
                "tool_result": None,
                "observation": {},
                "events": [],
                "state_digest": "sha256:" + "0" * 64,
                "reward": 0,
                "terminated": False,
                "truncated": False,
                "info": {},
            },
            {
                "code": "invalid_amount",
                "message": "invalid",
                "retryable": False,
                "details": {"hidden": True},
            },
            "unmodeled_error_details",
        ),
    ],
)
def test_protocol_closes_unmodeled_agent_facing_channels(
    operation: str,
    request_payload: dict[str, object],
    result: dict[str, object],
    runtime_error: dict[str, object] | None,
    expected_code: str,
) -> None:
    request = make_request(operation, request_payload)  # type: ignore[arg-type]
    wire: dict[str, object] = {
        "abi_version": "agent-world.runtime.v2",
        "request_id": request.request_id,
        "operation": operation,
        "ok": runtime_error is None,
        "result": result,
    }
    if runtime_error is not None:
        wire["error"] = runtime_error

    with pytest.raises(ProtocolViolation) as error:
        decode_response(
            (json.dumps(wire, separators=(",", ":")) + "\n").encode(),
            expected_request=request,
        )
    assert error.value.code == expected_code
