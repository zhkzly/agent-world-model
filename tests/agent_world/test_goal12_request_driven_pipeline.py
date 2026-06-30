import hashlib
import json
from pathlib import Path

from agent_world.agents import AgentBackendRegistry, AgentResult, MockAgentBackend
from agent_world.artifacts import GENERATED_BUNDLE_FILE_KINDS, stable_json
from agent_world.candidate_check import check_generated_candidate
from agent_world.generated_bundle import run_packaged_generated_bundle_check
from agent_world.pipeline import PipelineRunConfig, run_request_driven_pipeline
from agent_world.replay_contract import build_framework_replay_contract
from agent_world.request_driven import GENERATED_FILE_KINDS, run_summary


RAW_REQUEST = (
    "Generate an incident runbook environment that tracks alerts, owners, "
    "mitigation notes, handoff status, and final resolution summaries."
)


def test_goal12_raw_request_runs_generic_agent_pipeline_and_packages(tmp_path):
    backend = GenericCodegenBackend()
    registry = AgentBackendRegistry()
    registry.register(backend)

    record, context = run_request_driven_pipeline(
        _config(run_id="goal12-generic", output_dir=tmp_path, raw_request=RAW_REQUEST),
        agent_registry=registry,
    )

    assert record.status == "pass"
    assert len(backend.requests) == 1
    assert context.config.implementation_mode == "agent"
    environment_id = context.artifacts["ReleaseManifest"]["environment_id"]
    assert environment_id.startswith("env-")
    assert context.artifacts["DomainPlan"]["domain_seed"] == environment_id
    assert context.artifacts["GeneratedEnvironmentBundle"]["implementation_mode"] == "agent_backed_codegen"
    assert context.artifacts["ReleaseManifest"]["request_lineage"]["generated_bundle_ref"] == context.artifacts["GeneratedEnvironmentBundle"]["id"]

    package_dir = tmp_path / "envpkg"
    runtime_index_path = package_dir / "release" / "generated-runtime-index.yaml"
    runtime_dir = package_dir / "runtime" / "generated" / context.artifacts["GeneratedEnvironmentBundle"]["id"]
    assert runtime_index_path.is_file()
    assert runtime_dir.is_dir()
    assert set(Path(item["path"]).name for item in context.artifacts["GeneratedEnvironmentBundle"]["generated_files"]) == set(GENERATED_FILE_KINDS)

    independent = context.artifacts["IndependentVerificationReport"]
    assert independent["success"] is True
    assert independent["positive_record_count"] == 3
    assert independent["negative_record_count"] == 3
    assert set(independent["verified_task_ids"]) == {task["task_id"] for task in context.artifacts["TaskSet"]["tasks"]}

    packaged_check = run_packaged_generated_bundle_check(package_dir)
    assert packaged_check["success"] is True
    candidate_check = check_generated_candidate(
        build_dir=runtime_dir,
        environment_id=environment_id,
        accepted_tasks=context.artifacts["TaskSet"]["tasks"],
        runtime_entrypoint="runtime.GeneratedEnvironment",
    )
    assert candidate_check["success"] is True

    summary = run_summary(context)
    assert summary["environment_id"] == environment_id
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
        "GeneratedEnvironmentBundle",
        "IndependentVerificationReport",
        "EnvironmentPackagePlan",
        "ReleaseManifest",
    ]


def test_goal12_replay_contract_is_generated_from_taskset(tmp_path):
    backend = GenericCodegenBackend()
    registry = AgentBackendRegistry()
    registry.register(backend)
    _, context = run_request_driven_pipeline(
        _config(run_id="goal12-contract", output_dir=tmp_path, raw_request=RAW_REQUEST),
        agent_registry=registry,
    )

    contract = build_framework_replay_contract(context.artifacts)
    task_by_id = {task["task_id"]: task for task in context.artifacts["TaskSet"]["tasks"]}
    assert contract["environment_id"] == context.artifacts["ReleaseManifest"]["environment_id"]
    assert len(contract["replay_cases"]) == 3
    for case in contract["replay_cases"]:
        task = task_by_id[case["task_id"]]
        assert case["tool_calls"] == task["framework_replay"]["tool_calls"]
        assert case["expected_dependency_path"] == task["dependency_path"]
    assert "manual_registry" not in stable_json(contract)


def test_goal12_source_failure_writes_failure_packet_and_stops_before_release(tmp_path):
    record, context = run_request_driven_pipeline(
        _config(
            output_dir=tmp_path,
            raw_request=RAW_REQUEST,
            env={"AGENT_WORLD_REQUEST_SOURCE_STRATEGY": "none"},
        ),
        agent_registry=_registry(GenericCodegenBackend()),
    )

    assert record.status == "fail"
    assert record.node_results[-1].stage == "S1"
    assert context.repair_failure_packets
    assert context.repair_failure_packets[-1]["stage"] == "S1"
    assert "ReleaseManifest" not in context.artifacts


def test_goal12_forged_generated_check_replay_is_rejected_before_release(tmp_path):
    backend = GenericCodegenBackend(forge_check=True)
    record, context = run_request_driven_pipeline(
        _config(output_dir=tmp_path, raw_request=RAW_REQUEST),
        agent_registry=_registry(backend),
    )

    assert record.status == "fail"
    assert record.failure_class in {"framework_candidate_check_failed", "independent_generated_bundle_verification_failed"}
    assert context.artifacts["GeneratedEnvironmentBundle"]["status"] == "fail"
    assert context.artifacts["IndependentVerificationReport"]["status"] == "fail"
    assert "ReleaseManifest" not in context.artifacts


def test_goal12_bounded_repair_retries_agent_candidate_and_releases(tmp_path):
    backend = GenericCodegenBackend(fail_first=True)
    record, context = run_request_driven_pipeline(
        _config(
            output_dir=tmp_path,
            raw_request=RAW_REQUEST,
            max_repair_attempts=1,
        ),
        agent_registry=_registry(backend),
    )

    assert record.status == "pass"
    assert len(backend.requests) == 2
    assert [item["attempt_index"] for item in context.build_check_replay_records] == [1, 2]
    assert context.build_check_replay_records[0]["status"] == "fail"
    assert context.build_check_replay_records[1]["status"] == "pass"
    assert len(context.repair_failure_packets) == 1
    repair_packet = context.repair_failure_packets[0]
    assert repair_packet["stage"] == "IMPLEMENT"
    assert repair_packet["failed_task_ids"]
    assert repair_packet["framework_check_observation"]["schema_version"] == "agent-world.framework-check-observation.v1"
    assert "Previous failure packet JSON" in backend.requests[1].instruction
    assert "Keep candidate_manifest.json paths relative to candidate_dir" in backend.requests[1].instruction


def test_goal12_bounded_repair_exhaustion_stops_before_release(tmp_path):
    backend = GenericCodegenBackend(always_fail=True)
    record, context = run_request_driven_pipeline(
        _config(
            output_dir=tmp_path,
            raw_request=RAW_REQUEST,
            max_repair_attempts=1,
        ),
        agent_registry=_registry(backend),
    )

    assert record.status == "fail"
    assert record.failure_class == "generated_bundle_check_failed"
    assert len(backend.requests) == 2
    assert len(context.repair_failure_packets) == 2
    assert context.artifacts["GeneratedEnvironmentBundle"]["status"] == "fail"
    assert "ReleaseManifest" not in context.artifacts


def test_goal12_framework_candidate_check_returns_traceback_observation(tmp_path):
    backend = GenericCodegenBackend()
    _, context = run_request_driven_pipeline(
        _config(output_dir=tmp_path, raw_request=RAW_REQUEST),
        agent_registry=_registry(backend),
    )
    build_dir = Path(context.artifacts["GeneratedEnvironmentBundle"]["build_dir"])
    first_tool = context.artifacts["TaskSet"]["tasks"][0]["dependency_path"][0]
    runtime_path = build_dir / "runtime.py"
    runtime_path.write_text(
        runtime_path.read_text(encoding="utf-8").replace(
            f"return self._apply({first_tool!r}, payload=payload, note=note)",
            "raise IndexError('forced replay failure')",
        ),
        encoding="utf-8",
    )

    check = check_generated_candidate(
        build_dir=build_dir,
        environment_id=context.artifacts["ReleaseManifest"]["environment_id"],
        accepted_tasks=context.artifacts["TaskSet"]["tasks"],
        runtime_entrypoint="runtime.GeneratedEnvironment",
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
    backend = GenericCodegenBackend(write_pycache=True)
    record, context = run_request_driven_pipeline(
        _config(output_dir=tmp_path, raw_request=RAW_REQUEST),
        agent_registry=_registry(backend),
    )

    assert record.status == "pass"


class GenericCodegenBackend(MockAgentBackend):
    def __init__(
        self,
        *,
        fail_first: bool = False,
        always_fail: bool = False,
        forge_check: bool = False,
        write_pycache: bool = False,
    ) -> None:
        super().__init__()
        self.requests = []
        self.fail_first = fail_first
        self.always_fail = always_fail
        self.forge_check = forge_check
        self.write_pycache = write_pycache

    def invoke(self, request, config):
        self.requests.append(request)
        artifacts = _artifacts_from_instruction(request.instruction)
        work_dir = Path(request.permissions["filesystem_root"])
        manifest = write_generic_agent_candidate_files(
            work_dir,
            artifacts=artifacts,
            source_refs=request.input_artifact_ids,
            force_verifier_failure=self.always_fail or (self.fail_first and len(self.requests) == 1),
            forge_check=self.forge_check,
            write_pycache=self.write_pycache,
        )
        return AgentResult(
            text=json.dumps(manifest, sort_keys=True),
            evidence_refs=[f"mock://generic-codegen-attempt-{len(self.requests)}"],
            output_artifact_ids=[manifest["bundle_id"]],
            trace_ref=f"mock://trace/generic-codegen-attempt-{len(self.requests)}",
        )


def write_generic_agent_candidate_files(
    build_dir: Path,
    *,
    artifacts: dict[str, dict],
    source_refs: list[str],
    force_verifier_failure: bool = False,
    forge_check: bool = False,
    write_pycache: bool = False,
) -> dict[str, object]:
    build_dir.mkdir(parents=True, exist_ok=True)
    tasks = artifacts["TaskSet"]["tasks"]
    environment_id = artifacts["ImplementationRequest"]["environment_id"]
    (build_dir / "runtime.py").write_text(_runtime_py(tasks), encoding="utf-8")
    (build_dir / "seed_state.json").write_text(stable_json({"records": [], "summaries": {}, "meta": {"environment_id": environment_id}}), encoding="utf-8")
    (build_dir / "verifier.py").write_text(_verifier_py(tasks, force_failure=force_verifier_failure), encoding="utf-8")
    (build_dir / "surface_descriptor.json").write_text(stable_json({"environment_id": environment_id, "surfaces": {"python": "implemented"}}), encoding="utf-8")
    if forge_check:
        (build_dir / "check_replay.py").write_text("import json\nprint(json.dumps({'success': True}))\n", encoding="utf-8")
    else:
        (build_dir / "check_replay.py").write_text(_check_replay_py(tasks), encoding="utf-8")
    (build_dir / "build_manifest.yaml").write_text(
        json.dumps({"environment_id": environment_id, "runtime_entrypoint": "runtime.GeneratedEnvironment"}, sort_keys=True),
        encoding="utf-8",
    )
    if write_pycache:
        pycache = build_dir / "__pycache__"
        pycache.mkdir(exist_ok=True)
        (pycache / "runtime.cpython-312.pyc").write_bytes(b"bytecode")
    return _manifest_from_files(build_dir, environment_id=environment_id, source_refs=source_refs)


def _runtime_py(tasks: list[dict]) -> str:
    expected_by_task = {task["task_id"]: task.get("expected_answer") for task in tasks if task.get("expected_answer") not in (None, "", {})}
    methods = []
    for task in tasks:
        tool = task["dependency_path"][0]
        methods.append(
            "    def {tool}(self, *, payload, note=None):\n"
            "        return self._apply({tool!r}, payload=payload, note=note)\n".format(tool=tool)
        )
    return (
        "from __future__ import annotations\n"
        "import copy, json\n"
        "from pathlib import Path\n\n"
        f"EXPECTED_BY_TASK = {expected_by_task!r}\n\n"
        "def load_seed_state(seed_path):\n"
        "    return json.loads(Path(seed_path).read_text(encoding='utf-8'))\n\n"
        "def reset_environment(seed_state):\n"
        "    return copy.deepcopy(seed_state)\n\n"
        "class GeneratedEnvironment:\n"
        "    def __init__(self, state, trace_path=None, task_id=None, call_group=None):\n"
        "        self.state = state\n"
        "        self.trace_path = Path(trace_path) if trace_path else None\n"
        "        self.task_id = task_id or ''\n"
        "        self.call_group = call_group or ''\n\n"
        "    def _apply(self, tool, *, payload, note=None):\n"
        "        expected = EXPECTED_BY_TASK.get(self.task_id)\n"
        "        if expected:\n"
        "            result = copy.deepcopy(expected)\n"
        "        else:\n"
        "            result = {'task_id': self.task_id, 'tool': tool, 'accepted': True, 'payload': payload}\n"
        "            self.state.setdefault('records', []).append({'task_id': self.task_id, 'tool': tool, 'payload': payload, 'note': note})\n"
        "        self._trace(tool, {'payload': payload, 'note': note}, result)\n"
        "        return copy.deepcopy(result)\n\n"
        "    def _trace(self, tool, args, result):\n"
        "        if not self.trace_path:\n"
        "            return\n"
        "        self.trace_path.parent.mkdir(parents=True, exist_ok=True)\n"
        "        with self.trace_path.open('a', encoding='utf-8') as handle:\n"
        "            handle.write(json.dumps({'tool': tool, 'task_id': self.task_id, 'call_group': self.call_group, 'args': args, 'result': result}, sort_keys=True) + '\\n')\n\n"
        + "\n".join(methods)
    )


def _verifier_py(tasks: list[dict], *, force_failure: bool) -> str:
    specs = {
        task["task_id"]: {
            "expected_answer": task.get("expected_answer"),
            "requires_state_change": bool(task.get("expected_state_delta")),
        }
        for task in tasks
    }
    force = "True" if force_failure else "False"
    return (
        "from __future__ import annotations\n"
        "import copy, json\n"
        "from pathlib import Path\n\n"
        f"TASK_SPECS = {specs!r}\n"
        f"FORCE_FAILURE = {force}\n\n"
        "def _trace_tools(path, task_id, call_group):\n"
        "    path = Path(path)\n"
        "    if not path.exists():\n"
        "        return []\n"
        "    tools = []\n"
        "    for line in path.read_text(encoding='utf-8').splitlines():\n"
        "        if not line.strip():\n"
        "            continue\n"
        "        record = json.loads(line)\n"
        "        if record.get('task_id') == task_id and record.get('call_group') in {call_group, None, ''}:\n"
        "            tools.append(record.get('tool'))\n"
        "    return tools\n\n"
        "def verify_task_completion(task_id, initial_state, final_state, *, surface_trace_path=None, expected_dependency_path=None, trace_call_group='positive', final_answer=None):\n"
        "    spec = TASK_SPECS[task_id]\n"
        "    expected_dependency_path = list(expected_dependency_path or [])\n"
        "    trace_tools = _trace_tools(surface_trace_path, task_id, trace_call_group) if surface_trace_path else []\n"
        "    checks = []\n"
        "    checks.append({'name': 'forced_failure', 'passed': not FORCE_FAILURE})\n"
        "    checks.append({'name': 'dependency_trace', 'passed': trace_tools == expected_dependency_path, 'detail': {'expected': expected_dependency_path, 'actual': trace_tools}})\n"
        "    expected_answer = spec.get('expected_answer')\n"
        "    if expected_answer not in (None, '', {}):\n"
        "        checks.append({'name': 'expected_answer', 'passed': final_answer == expected_answer, 'detail': {'expected': expected_answer, 'actual': final_answer}})\n"
        "        checks.append({'name': 'query_state_unchanged', 'passed': initial_state == final_state})\n"
        "    elif spec.get('requires_state_change'):\n"
        "        checks.append({'name': 'state_changed', 'passed': initial_state != final_state})\n"
        "    else:\n"
        "        checks.append({'name': 'answer_present', 'passed': final_answer not in (None, '', {})})\n"
        "    return {'task_id': task_id, 'success': all(item['passed'] for item in checks), 'checks': checks}\n"
    )


def _check_replay_py(tasks: list[dict]) -> str:
    return (
        "from __future__ import annotations\n"
        "import argparse, json, tempfile\n"
        "from pathlib import Path\n"
        "import runtime\n"
        "import verifier\n\n"
        f"TASKS = {tasks!r}\n"
        "SEED = 'seed_state.json'\n\n"
        "def _run_task(task):\n"
        "    with tempfile.TemporaryDirectory() as td:\n"
        "        trace = Path(td) / f\"{task['task_id']}.jsonl\"\n"
        "        seed = runtime.load_seed_state(SEED)\n"
        "        initial = runtime.reset_environment(seed)\n"
        "        final = runtime.reset_environment(seed)\n"
        "        env = runtime.GeneratedEnvironment(final, trace_path=trace, task_id=task['task_id'], call_group='positive')\n"
        "        answer = None\n"
        "        for call in task['framework_replay']['tool_calls']:\n"
        "            answer = getattr(env, call['tool'])(**call.get('kwargs', {}))\n"
        "        positive = verifier.verify_task_completion(task['task_id'], initial, final, surface_trace_path=trace, expected_dependency_path=task['dependency_path'], trace_call_group='positive', final_answer=answer)\n"
        "        negative = verifier.verify_task_completion(task['task_id'], runtime.reset_environment(seed), runtime.reset_environment(seed), surface_trace_path=Path(td) / 'negative.jsonl', expected_dependency_path=task['dependency_path'], trace_call_group='negative', final_answer={'accepted': False})\n"
        "        return {'task_id': task['task_id'], 'success': positive.get('success') is True and negative.get('success') is False, 'positive_verifier_result': positive, 'negative_verifier_result': negative}\n\n"
        "def main(argv=None):\n"
        "    parser = argparse.ArgumentParser()\n"
        "    parser.add_argument('--task', default='')\n"
        "    args = parser.parse_args(argv)\n"
        "    selected = [task for task in TASKS if not args.task or task['task_id'] == args.task]\n"
        "    records = [_run_task(task) for task in selected]\n"
        "    result = {'success': bool(records) and all(record['success'] for record in records), 'task_records': records, 'positive_verifier_result': records[0]['positive_verifier_result'] if records else {}, 'negative_verifier_result': records[0]['negative_verifier_result'] if records else {}}\n"
        "    print(json.dumps(result, sort_keys=True))\n"
        "    return 0 if result['success'] else 1\n\n"
        "if __name__ == '__main__':\n"
        "    raise SystemExit(main())\n"
    )


def _manifest_from_files(build_dir: Path, *, environment_id: str, source_refs: list[str]) -> dict[str, object]:
    return {
        "candidate_dir": ".",
        "bundle_id": f"bundle-{environment_id}-agent-generated",
        "environment_id": environment_id,
        "generated_files": [
            {
                "path": filename,
                "kind": kind,
                "sha256": _sha256(build_dir / filename),
                "source_refs": source_refs,
            }
            for filename, kind in GENERATED_BUNDLE_FILE_KINDS.items()
        ],
        "runtime_entrypoint": "runtime.GeneratedEnvironment",
        "seed_fixture_ref": "seed_state.json",
        "verifier_entrypoint": "verifier.verify_task_completion",
        "surface_descriptors": ["surface_descriptor.json"],
        "check_commands": [["python", "check_replay.py"]],
        "replay_commands": [["python", "check_replay.py", "--task", task_id] for task_id in []],
    }


def _artifacts_from_instruction(instruction: str) -> dict[str, dict]:
    marker = "Accepted artifact context JSON:\n"
    assert marker in instruction
    payload = instruction.split(marker, 1)[1]
    return json.loads(payload)


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
