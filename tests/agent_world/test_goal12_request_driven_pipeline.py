import hashlib
import json
import shutil
from pathlib import Path

from agent_world.agents import AgentBackendRegistry, AgentResult, MockAgentBackend
from agent_world.artifacts import GENERATED_PROJECT_FILE_KINDS, stable_json
from agent_world.candidate_check import check_generated_candidate
from agent_world.envpack import assemble_environment_pack, load_environment_pack, run_environment_pack_check, run_portable_envpkg_check
from agent_world.generated_project import run_packaged_generated_project_check
from agent_world.pipeline import PipelineRunConfig, run_request_driven_pipeline
from agent_world.replay_contract import build_framework_replay_contract
from agent_world.request_driven import run_summary


RAW_REQUEST = (
    "Generate an incident runbook environment that tracks alerts, owners, "
    "mitigation notes, handoff status, and final resolution summaries."
)


def test_goal12_raw_request_runs_generic_agent_pipeline_and_packages(tmp_path):
    backend = GenericCodegenBackend()
    record, context = run_request_driven_pipeline(
        _config(run_id="goal12-generic", output_dir=tmp_path, raw_request=RAW_REQUEST),
        agent_registry=_registry(backend),
    )

    assert record.status == "pass"
    assert len(backend.requests) == 1
    environment_id = context.artifacts["ReleaseManifest"]["environment_id"]
    project = context.artifacts["GeneratedEnvironmentProject"]
    assert project["implementation_mode"] == "agent_backed_contract_project"
    assert project["contract"]["runtime_abi_version"] == "agent-world.runtime-abi.v1"
    assert set(project["contract"]["interfaces"]) == {"describe", "setup", "reset", "health", "invoke", "verify", "export_trace", "teardown"}
    assert context.artifacts["ReleaseManifest"]["request_lineage"]["generated_project_ref"] == project["id"]
    assert {item["kind"] for item in project["generated_files"]}.issubset(GENERATED_PROJECT_FILE_KINDS)

    package_dir = tmp_path / "envpkg"
    runtime_dir = package_dir / "runtime" / "project"
    assert (package_dir / "manifest.json").is_file()
    assert (package_dir / "runtime" / "runtime_index.json").is_file()
    assert runtime_dir.is_dir()
    assert (runtime_dir / "contract.json").is_file()

    independent = context.artifacts["IndependentVerificationReport"]
    assert independent["success"] is True
    assert independent["positive_record_count"] == 3
    assert independent["negative_record_count"] == 3

    packaged_check = run_packaged_generated_project_check(package_dir)
    assert packaged_check["success"] is True
    candidate_check = check_generated_candidate(
        build_dir=runtime_dir,
        environment_id=environment_id,
        accepted_tasks=context.artifacts["TaskSet"]["tasks"],
    )
    assert candidate_check["success"] is True

    summary = run_summary(context)
    assert [item["artifact_type"] for item in summary["artifact_flow"]] == [
        "DomainPlan",
        "StrategySelection",
        "NeedSpec",
        "SourceEvidenceIndex",
        "KnowledgePack",
        "EnvironmentSpec",
        "LogicalToolGraph",
        "TaskSet",
        "SurfacePlan",
        "VerifierPlan",
        "FeasibilityReport",
        "ImplementationRequest",
        "GeneratedEnvironmentProject",
        "IndependentVerificationReport",
        "EnvironmentPackagePlan",
        "ReleaseManifest",
    ]


def test_goal12_publishable_envpkg_manifest_and_portable_check_survive_move(tmp_path):
    _, context = run_request_driven_pipeline(
        _config(run_id="goal12-portable-envpkg", output_dir=tmp_path, raw_request=RAW_REQUEST),
        agent_registry=_registry(GenericCodegenBackend()),
    )

    package_dir = tmp_path / "envpkg"
    manifest = json.loads((package_dir / "manifest.json").read_text(encoding="utf-8"))
    project_id = context.artifacts["GeneratedEnvironmentProject"]["id"]
    assert manifest["environment_id"] == context.artifacts["ReleaseManifest"]["environment_id"]
    assert manifest["implementation_id"] == project_id
    assert manifest["runtime_root"] == "runtime/project"
    assert manifest["bootstrap"]["reset"]["interface"] == "reset"
    assert manifest["bootstrap"]["invoke"]["interface"] == "invoke"

    moved = tmp_path / "moved" / "envpkg"
    shutil.copytree(package_dir, moved)
    portable_check = run_portable_envpkg_check(moved)
    assert portable_check["success"] is True
    assert portable_check["implementation_id"] == project_id


def test_goal12_environment_pack_materializes_identity_paths_and_loader(tmp_path):
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"
    _, first_context = run_request_driven_pipeline(
        _config(run_id="goal12-pack-first", output_dir=first_dir, raw_request=RAW_REQUEST),
        agent_registry=_registry(GenericCodegenBackend()),
    )
    _, second_context = run_request_driven_pipeline(
        _config(
            run_id="goal12-pack-second",
            output_dir=second_dir,
            raw_request="Generate a support ticket environment with queues, priorities, replies, escalations, and resolution notes.",
        ),
        agent_registry=_registry(GenericCodegenBackend()),
    )

    pack_dir = tmp_path / "environment-pack"
    result = assemble_environment_pack([first_dir / "envpkg", second_dir / "envpkg"], out_dir=pack_dir, pack_id="goal12-pack")

    expected_ids = {
        first_context.artifacts["ReleaseManifest"]["environment_id"],
        second_context.artifacts["ReleaseManifest"]["environment_id"],
    }
    assert result["success"] is True
    loaded = load_environment_pack(pack_dir)
    assert {row["environment_id"] for row in loaded["environments"]} == expected_ids
    for row in loaded["environments"]:
        envpkg_path = pack_dir / "packages" / row["environment_id"] / row["version"] / "envpkg"
        assert envpkg_path.is_dir()
        assert row["package_ref"] == f"packages/{row['environment_id']}/{row['version']}/envpkg"
        assert (envpkg_path / "runtime" / "project" / "contract.json").is_file()

    pack_check = run_environment_pack_check(pack_dir)
    assert pack_check["success"] is True
    assert pack_check["environment_count"] == 2


def test_goal12_environment_pack_rejects_duplicate_environment_version(tmp_path):
    run_request_driven_pipeline(
        _config(run_id="goal12-pack-duplicate", output_dir=tmp_path, raw_request=RAW_REQUEST),
        agent_registry=_registry(GenericCodegenBackend()),
    )

    try:
        assemble_environment_pack([tmp_path / "envpkg", tmp_path / "envpkg"], out_dir=tmp_path / "pack", pack_id="duplicate-pack")
    except ValueError as exc:
        assert "duplicate environment identity" in str(exc)
    else:
        raise AssertionError("duplicate environment identity should be rejected")


def test_goal12_replay_contract_is_generated_from_taskset(tmp_path):
    _, context = run_request_driven_pipeline(
        _config(run_id="goal12-contract", output_dir=tmp_path, raw_request=RAW_REQUEST),
        agent_registry=_registry(GenericCodegenBackend()),
    )

    contract = build_framework_replay_contract(context.artifacts)
    task_by_id = {task["task_id"]: task for task in context.artifacts["TaskSet"]["tasks"]}
    assert contract["environment_id"] == context.artifacts["ReleaseManifest"]["environment_id"]
    assert contract["project_layout"]["required_refs"] == ["contract.json", "source/", "state/", "adapters/", "scripts/", "spec/"]
    assert len(contract["replay_cases"]) == 3
    for case in contract["replay_cases"]:
        task = task_by_id[case["task_id"]]
        assert case["tool_calls"] == task["framework_replay"]["tool_calls"]
        assert case["expected_dependency_path"] == task["dependency_path"]
    assert "manual_registry" not in stable_json(contract)


def test_goal12_source_failure_writes_failure_packet_and_stops_before_release(tmp_path):
    record, context = run_request_driven_pipeline(
        _config(output_dir=tmp_path, raw_request=RAW_REQUEST, env={"AGENT_WORLD_REQUEST_SOURCE_STRATEGY": "none"}),
        agent_registry=_registry(GenericCodegenBackend()),
    )

    assert record.status == "fail"
    assert record.node_results[-1].stage == "S1"
    assert context.repair_failure_packets
    assert context.repair_failure_packets[-1]["stage"] == "S1"
    assert "ReleaseManifest" not in context.artifacts


def test_goal12_forged_self_check_is_rejected_before_release(tmp_path):
    record, context = run_request_driven_pipeline(
        _config(output_dir=tmp_path, raw_request=RAW_REQUEST),
        agent_registry=_registry(GenericCodegenBackend(force_verify_failure=True)),
    )

    assert record.status == "fail"
    assert record.failure_class in {"framework_candidate_check_failed", "independent_generated_project_verification_failed"}
    assert context.artifacts["GeneratedEnvironmentProject"]["status"] == "fail"
    assert context.artifacts["IndependentVerificationReport"]["status"] == "fail"
    assert "ReleaseManifest" not in context.artifacts


def test_goal12_bounded_repair_retries_agent_candidate_and_releases(tmp_path):
    backend = GenericCodegenBackend(fail_first=True)
    record, context = run_request_driven_pipeline(
        _config(output_dir=tmp_path, raw_request=RAW_REQUEST, max_repair_attempts=1),
        agent_registry=_registry(backend),
    )

    assert record.status == "pass"
    assert len(backend.requests) == 2
    assert [item["attempt_index"] for item in context.implementation_check_records] == [1, 2]
    assert context.implementation_check_records[0]["status"] == "fail"
    assert context.implementation_check_records[1]["status"] == "pass"
    repair_packet = context.repair_failure_packets[0]
    assert repair_packet["stage"] == "IMPLEMENT"
    assert repair_packet["failed_task_ids"]
    assert repair_packet["framework_check_observation"]["schema_version"] == "agent-world.framework-check-observation.v1"
    assert "Previous failure packet JSON" in backend.requests[1].instruction


def test_goal12_bounded_repair_exhaustion_stops_before_release(tmp_path):
    record, context = run_request_driven_pipeline(
        _config(output_dir=tmp_path, raw_request=RAW_REQUEST, max_repair_attempts=1),
        agent_registry=_registry(GenericCodegenBackend(always_fail=True)),
    )

    assert record.status == "fail"
    assert record.failure_class in {"framework_candidate_check_failed", "independent_generated_project_verification_failed"}
    assert len(context.repair_failure_packets) == 2
    assert context.artifacts["GeneratedEnvironmentProject"]["status"] == "fail"
    assert "ReleaseManifest" not in context.artifacts


def test_goal12_framework_candidate_check_returns_traceback_observation(tmp_path):
    _, context = run_request_driven_pipeline(
        _config(output_dir=tmp_path, raw_request=RAW_REQUEST),
        agent_registry=_registry(GenericCodegenBackend()),
    )
    build_dir = Path(context.artifacts["GeneratedEnvironmentProject"]["build_dir"])
    adapter_path = build_dir / "adapters" / "runtime_adapter.py"
    adapter_path.write_text(
        adapter_path.read_text(encoding="utf-8").replace(
            "events.append({'episode_id': episode_id, 'task_id': task_id, 'tool_id': tool_id, 'step_index': step_index, 'arguments': arguments})",
            "raise IndexError('forced replay failure')",
        ),
        encoding="utf-8",
    )

    check = check_generated_candidate(
        build_dir=build_dir,
        environment_id=context.artifacts["ReleaseManifest"]["environment_id"],
        accepted_tasks=context.artifacts["TaskSet"]["tasks"],
    )

    assert check["success"] is False
    observation = check["framework_check_observation"]
    assert observation["schema_version"] == "agent-world.framework-check-observation.v1"
    assert context.artifacts["TaskSet"]["tasks"][0]["task_id"] in observation["failed_task_ids"]
    failed_task = next(item for item in observation["task_observations"] if item["task_id"] == context.artifacts["TaskSet"]["tasks"][0]["task_id"])
    assert failed_task["phase"] == "task_replay"
    assert failed_task["exception"]["type"] == "IndexError"
    assert "Traceback" in failed_task["exception"]["traceback"]


def test_goal12_agent_candidate_ignores_python_bytecode_cache(tmp_path):
    record, _ = run_request_driven_pipeline(
        _config(output_dir=tmp_path, raw_request=RAW_REQUEST),
        agent_registry=_registry(GenericCodegenBackend(write_pycache=True)),
    )

    assert record.status == "pass"


def test_goal12_runner_workspace_injects_skill_and_schemas(tmp_path):
    backend = RunnerProbeBackend()
    record, _ = run_request_driven_pipeline(
        _config(output_dir=tmp_path, raw_request=RAW_REQUEST, env={"AGENT_WORLD_AGENT_BACKEND": "code_agent_runner"}),
        agent_registry=_registry(backend),
    )

    assert record.status == "pass"
    workspace = backend.workspaces[0]
    assert (workspace / "input" / "skills" / "agent-world-environment-codegen" / "SKILL.md").is_file()
    assert (workspace / "input" / "schemas" / "candidate_manifest.schema.json").is_file()
    assert (workspace / "input" / "implementation_contract.json").is_file()
    assert json.loads((workspace / "input" / "implementation_contract.json").read_text(encoding="utf-8"))["required_interfaces"] == [
        "describe",
        "export_trace",
        "health",
        "invoke",
        "reset",
        "setup",
        "teardown",
        "verify",
    ]


class GenericCodegenBackend(MockAgentBackend):
    def __init__(self, *, fail_first=False, always_fail=False, force_verify_failure=False, write_pycache=False) -> None:
        super().__init__()
        self.requests = []
        self.fail_first = fail_first
        self.always_fail = always_fail
        self.force_verify_failure = force_verify_failure
        self.write_pycache = write_pycache

    def invoke(self, request, config):
        self.requests.append(request)
        artifacts = _artifacts_from_instruction(request.instruction)
        work_dir = Path(request.permissions["filesystem_root"])
        manifest = write_contract_project_candidate(
            work_dir,
            artifacts=artifacts,
            source_refs=request.input_artifact_ids,
            force_verify_failure=self.force_verify_failure or self.always_fail or (self.fail_first and len(self.requests) == 1),
            write_pycache=self.write_pycache,
        )
        return AgentResult(
            text=json.dumps(manifest, sort_keys=True),
            evidence_refs=[f"mock://contract-project-attempt-{len(self.requests)}"],
            output_artifact_ids=[manifest["implementation_id"]],
            trace_ref=f"mock://trace/contract-project-attempt-{len(self.requests)}",
        )


class RunnerProbeBackend(GenericCodegenBackend):
    backend_kind = "code_agent_runner"

    def __init__(self) -> None:
        super().__init__()
        self.workspaces = []

    def invoke(self, request, config):
        self.requests.append(request)
        work_dir = Path(request.permissions["filesystem_root"])
        self.workspaces.append(work_dir)
        artifacts = {
            path.stem: json.loads(path.read_text(encoding="utf-8"))
            for path in (work_dir / "input" / "artifacts").glob("*.json")
        }
        manifest = write_contract_project_candidate(work_dir, artifacts=artifacts, source_refs=request.input_artifact_ids)
        output = work_dir / "agent-output"
        output.mkdir(parents=True, exist_ok=True)
        (output / "candidate_manifest.json").write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
        return AgentResult(
            text=json.dumps({"candidate_manifest_ref": "agent-output/candidate_manifest.json"}, sort_keys=True),
            evidence_refs=["mock://runner-probe"],
            output_artifact_ids=[manifest["implementation_id"]],
            trace_ref="mock://runner-probe",
        )


def write_contract_project_candidate(
    work_dir: Path,
    *,
    artifacts: dict[str, dict],
    source_refs: list[str],
    force_verify_failure: bool = False,
    write_pycache: bool = False,
) -> dict[str, object]:
    generated = work_dir / "generated"
    for dirname in ["source", "state", "adapters", "scripts", "spec"]:
        (generated / dirname).mkdir(parents=True, exist_ok=True)
    tasks = artifacts["TaskSet"]["tasks"]
    environment_id = artifacts["ImplementationRequest"]["environment_id"]
    (generated / "source" / "env_impl.py").write_text("# free-form generated environment implementation\n", encoding="utf-8")
    (generated / "state" / "seed.json").write_text(stable_json({"environment_id": environment_id, "episodes": {}}), encoding="utf-8")
    (generated / "spec" / "tasks.json").write_text(json.dumps(tasks, sort_keys=True), encoding="utf-8")
    (generated / "spec" / "tools.json").write_text(json.dumps({"tools": artifacts["LogicalToolGraph"]["tools"]}, sort_keys=True), encoding="utf-8")
    (generated / "adapters" / "__init__.py").write_text("", encoding="utf-8")
    (generated / "adapters" / "runtime_adapter.py").write_text(_runtime_adapter_py(environment_id, tasks, force_verify_failure), encoding="utf-8")
    (generated / "scripts" / "self_check.py").write_text(_self_check_py(), encoding="utf-8")
    (generated / "contract.json").write_text(json.dumps(_contract(environment_id), sort_keys=True), encoding="utf-8")
    if write_pycache:
        pycache = generated / "adapters" / "__pycache__"
        pycache.mkdir(exist_ok=True)
        (pycache / "runtime_adapter.cpython-312.pyc").write_bytes(b"bytecode")
    manifest = _manifest_from_generated(generated, environment_id=environment_id, source_refs=source_refs)
    output = work_dir / "agent-output"
    output.mkdir(parents=True, exist_ok=True)
    (output / "local_check_report.json").write_text(json.dumps({"success": True}, sort_keys=True), encoding="utf-8")
    return manifest


def _contract(environment_id: str) -> dict:
    interfaces = {
        name: {"kind": "python_callable", "entrypoint": f"adapters.runtime_adapter:{name}"}
        for name in ["describe", "setup", "reset", "health", "invoke", "verify", "export_trace", "teardown"]
    }
    return {
        "schema_version": "agent-world.environment-project.v1",
        "environment_id": environment_id,
        "version": "0.1.0",
        "implementation_id": f"project-{environment_id}-agent-generated",
        "runtime_abi_version": "agent-world.runtime-abi.v1",
        "interfaces": interfaces,
        "tools": [],
        "state": {"kind": "in_memory", "reset_strategy": "episode"},
        "trace": {"kind": "in_memory_events"},
        "surfaces": [{"surface": "python_callable", "adapter": "adapters.runtime_adapter"}],
    }


def _runtime_adapter_py(environment_id: str, tasks: list[dict], force_verify_failure: bool) -> str:
    task_specs = {task["task_id"]: {"expected_path": task["dependency_path"]} for task in tasks}
    return (
        "from __future__ import annotations\n"
        "import copy\n\n"
        f"ENVIRONMENT_ID = {environment_id!r}\n"
        f"TASK_SPECS = {task_specs!r}\n"
        f"FORCE_VERIFY_FAILURE = {bool(force_verify_failure)!r}\n"
        "EPISODES = {}\n\n"
        "def _ok(**kwargs):\n"
        "    return {'status': 'pass', **kwargs}\n\n"
        "def describe(payload):\n"
        "    return _ok(environment_id=ENVIRONMENT_ID, tools=sorted({tool for spec in TASK_SPECS.values() for tool in spec['expected_path']}))\n\n"
        "def setup(payload):\n"
        "    return _ok(environment_id=ENVIRONMENT_ID)\n\n"
        "def health(payload):\n"
        "    return _ok(success=True, environment_id=ENVIRONMENT_ID)\n\n"
        "def reset(payload):\n"
        "    task_id = payload.get('task_id') or payload.get('task', {}).get('task_id')\n"
        "    case = payload.get('case', 'positive')\n"
        "    episode_id = f'{task_id}-{case}'\n"
        "    EPISODES[episode_id] = {'task_id': task_id, 'case': case, 'events': []}\n"
        "    return _ok(success=True, episode_id=episode_id, available_tool_ids=TASK_SPECS[task_id]['expected_path'], initial_observation={})\n\n"
        "def invoke(payload):\n"
        "    episode_id = payload['episode_id']\n"
        "    tool_id = payload['tool_id']\n"
        "    task_id = payload.get('task_id') or EPISODES[episode_id]['task_id']\n"
        "    step_index = int(payload.get('step_index', len(EPISODES[episode_id]['events'])))\n"
        "    arguments = copy.deepcopy(payload.get('arguments') or {})\n"
        "    events = EPISODES[episode_id]['events']\n"
        "    events.append({'episode_id': episode_id, 'task_id': task_id, 'tool_id': tool_id, 'step_index': step_index, 'arguments': arguments})\n"
        "    return _ok(success=True, episode_id=episode_id, tool_id=tool_id, result={'accepted': True, 'tool_id': tool_id})\n\n"
        "def verify(payload):\n"
        "    task_id = payload.get('task_id') or payload.get('task', {}).get('task_id')\n"
        "    episode_id = payload['episode_id']\n"
        "    expected = list(payload.get('expected_dependency_path') or TASK_SPECS[task_id]['expected_path'])\n"
        "    actual = [event['tool_id'] for event in EPISODES.get(episode_id, {}).get('events', [])]\n"
        "    success = (not FORCE_VERIFY_FAILURE) and actual == expected and payload.get('case') != 'negative'\n"
        "    return {'status': 'pass' if success else 'fail', 'success': success, 'checks': [{'name': 'dependency_path', 'passed': actual == expected, 'expected': expected, 'actual': actual}]}\n\n"
        "def export_trace(payload):\n"
        "    episode_id = payload['episode_id']\n"
        "    return _ok(success=True, episode_id=episode_id, events=copy.deepcopy(EPISODES.get(episode_id, {}).get('events', [])))\n\n"
        "def teardown(payload):\n"
        "    EPISODES.clear()\n"
        "    return _ok(success=True)\n"
    )


def _self_check_py() -> str:
    return (
        "import json\n"
        "from pathlib import Path\n"
        "Path('../agent-output').mkdir(exist_ok=True)\n"
        "Path('../agent-output/local_check_report.json').write_text(json.dumps({'success': True}, sort_keys=True), encoding='utf-8')\n"
        "print(json.dumps({'success': True}, sort_keys=True))\n"
    )


def _manifest_from_generated(generated: Path, *, environment_id: str, source_refs: list[str]) -> dict[str, object]:
    files = []
    for path in sorted(item for item in generated.rglob("*") if item.is_file()):
        rel = path.relative_to(generated).as_posix()
        if "__pycache__" in path.parts or path.suffix in {".pyc", ".pyo"}:
            continue
        files.append({"path": rel, "kind": _kind(rel), "sha256": _sha256(path), "source_refs": source_refs})
    return {
        "candidate_dir": "generated",
        "environment_id": environment_id,
        "implementation_id": f"project-{environment_id}-agent-generated",
        "contract_ref": "contract.json",
        "generated_files": files,
        "self_check": {"command": ["python", "scripts/self_check.py"], "report_ref": "../agent-output/local_check_report.json"},
        "replay_commands": [["framework-abi-replay", task_id] for task_id in []],
    }


def _kind(relative_path: str) -> str:
    if relative_path == "contract.json":
        return "contract"
    first = relative_path.split("/", 1)[0]
    return {"source": "source", "state": "state", "adapters": "adapter", "scripts": "script", "spec": "spec"}.get(first, "other")


def _artifacts_from_instruction(instruction: str) -> dict[str, dict]:
    marker = "Accepted artifact context JSON:\n"
    assert marker in instruction
    return json.loads(instruction.split(marker, 1)[1])


def _registry(backend):
    registry = AgentBackendRegistry()
    registry.register(backend)
    return registry


def _config(**kwargs):
    env = {"AGENT_WORLD_AGENT_BACKEND": "mock"}
    env.update(kwargs.pop("env", {}) or {})
    return PipelineRunConfig(env=env, **kwargs)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
