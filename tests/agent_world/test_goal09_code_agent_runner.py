import json
import sys
from pathlib import Path

from agent_world.fixtures.project_board_lite_codegen import (
    AGENT_GENERATED_BUNDLE_ID,
    DISALLOWED_FIXTURE_IMPORT,
    check_project_board_generated_bundle,
)
from agent_world.generated_bundle import run_packaged_generated_bundle_check
from agent_world.pipeline import PipelineRunConfig, PipelineRunner, project_board_lite_node_registry


def test_goal09_code_agent_runner_writes_workspace_checks_and_releases_bundle(tmp_path):
    helper = Path(__file__).resolve().parents[1] / "fixtures" / "project_board_code_agent_runner.py"
    env = {
        "AGENT_WORLD_AGENT_BACKEND": "code_agent_runner",
        "AGENT_WORLD_CODE_AGENT_CMD": f"{sys.executable} {helper}",
        "AGENT_WORLD_PROCESS_AGENT_ALLOWLIST": sys.executable,
        "AGENT_WORLD_AGENT_TIMEOUT_MS": "30000",
    }

    record, context = PipelineRunner(project_board_lite_node_registry()).run(
        PipelineRunConfig(
            run_id="code-agent-runner-test",
            output_dir=tmp_path,
            raw_request="Generate project-board-lite with a real code agent runner workspace.",
            implementation_mode="agent",
            env=env,
        )
    )

    bundle = context.artifacts["GeneratedEnvironmentBundle"]
    invocation = context.agent_invocations[-1]
    generated_dir = Path(bundle["build_dir"])
    workspace = generated_dir.parent

    assert record.status == "pass"
    assert bundle["id"] == AGENT_GENERATED_BUNDLE_ID
    assert bundle["status"] == "accepted"
    assert bundle["implementation_mode"] == "agent_backed_codegen"
    assert invocation["backend_kind"] == "code_agent_runner"
    assert invocation["permissions"]["filesystem"] == "isolated_agent_workspace"
    assert invocation["permissions"]["filesystem_root"] == str(workspace)
    assert invocation["allowed_tool_access"] == [
        "read_workspace_packet",
        "write_generated_bundle_files",
        "run_local_checks",
        "repair_generated_bundle",
        "write_candidate_manifest",
    ]
    assert (workspace / "input" / "implementation-brief.md").is_file()
    brief_text = (workspace / "input" / "implementation-brief.md").read_text(encoding="utf-8")
    assert "required_runtime_entrypoint: runtime.ProjectBoardLite" in brief_text
    assert "required_runtime_constructor: __init__(state, trace_path=None, task_id=None, call_group=None)" in brief_text
    assert "required_runtime_helpers: runtime.load_seed_state(seed_path), runtime.reset_environment(seed_state)" in brief_text
    assert "required_trace_jsonl" in brief_text
    assert "surface_trace_path" in brief_text
    assert "framework_replay_expectation" in brief_text
    assert (workspace / "input" / "expected-bundle-layout.md").is_file()
    layout_text = (workspace / "input" / "expected-bundle-layout.md").read_text(encoding="utf-8")
    acceptance_text = (workspace / "input" / "acceptance-checks.md").read_text(encoding="utf-8")
    assert "`runtime.py` must expose `runtime.ProjectBoardLite`" in layout_text
    assert "RuntimeClass(state, trace_path=Path(...), task_id=task_id" in layout_text
    assert "append one JSONL record to `trace_path`" in layout_text
    assert "`runtime.py` -> `runtime_code`" in layout_text
    assert '"kind": "runtime_code"' in layout_text
    assert "generated_files[]` item declares exact `path`, exact `kind`" in acceptance_text
    assert (workspace / "input" / "skills" / "environment-codegen.md").is_file()
    assert (workspace / "input" / "artifacts" / "ImplementationRequest.json").is_file()
    assert (workspace / "agent-output" / "candidate_manifest.json").is_file()
    assert (workspace / "agent-output" / "runner-command-log.jsonl").is_file()
    assert (workspace / "agent-output" / "self-check-log.jsonl").is_file()
    assert generated_dir.name == "generated"
    assert DISALLOWED_FIXTURE_IMPORT not in (generated_dir / "runtime.py").read_text(encoding="utf-8")
    assert "agent-output/candidate_manifest.json" in json.dumps(invocation["evidence_refs"])

    manifest = json.loads((workspace / "agent-output" / "candidate_manifest.json").read_text(encoding="utf-8"))
    assert manifest["candidate_dir"] == "generated"
    assert {item["path"] for item in manifest["generated_files"]} == {
        "runtime.py",
        "seed_state.json",
        "verifier.py",
        "surface_descriptor.json",
        "check_replay.py",
        "build_manifest.yaml",
    }
    assert {item["kind"] for item in manifest["generated_files"]} == {
        "runtime_code",
        "seed_fixture",
        "verifier_code",
        "surface_descriptor",
        "test_or_check",
        "build_manifest",
    }
    command_log = (workspace / "agent-output" / "runner-command-log.jsonl").read_text(encoding="utf-8")
    assert str(helper) in command_log
    self_check = (workspace / "agent-output" / "self-check-log.jsonl").read_text(encoding="utf-8")
    assert "check_replay.py" in self_check

    check = check_project_board_generated_bundle(generated_dir)
    assert check["success"] is True
    assert check["positive_verifier_result"]["success"] is True
    assert check["negative_verifier_result"]["success"] is False

    package_dir = tmp_path / "envpkg"
    packaged_runtime_dir = package_dir / "runtime" / "generated" / bundle["id"]
    assert (packaged_runtime_dir / "runtime.py").is_file()
    packaged_check = run_packaged_generated_bundle_check(package_dir)
    assert packaged_check["success"] is True


def test_goal09_code_agent_runner_missing_manifest_stops_release(tmp_path):
    helper = Path(__file__).resolve().parents[1] / "fixtures" / "project_board_code_agent_runner.py"
    env = {
        "AGENT_WORLD_AGENT_BACKEND": "code_agent_runner",
        "AGENT_WORLD_CODE_AGENT_CMD": f"{sys.executable} {helper} fail-before-manifest",
        "AGENT_WORLD_PROCESS_AGENT_ALLOWLIST": sys.executable,
        "AGENT_WORLD_AGENT_TIMEOUT_MS": "30000",
    }

    record, context = PipelineRunner(project_board_lite_node_registry()).run(
        PipelineRunConfig(
            run_id="code-agent-runner-fail-test",
            output_dir=tmp_path,
            raw_request="Generate project-board-lite with a runner that fails to publish a manifest.",
            implementation_mode="agent",
            env=env,
        )
    )

    assert record.status == "fail"
    assert record.failure_class == "missing_runner_manifest"
    assert context.agent_invocations[-1]["backend_kind"] == "code_agent_runner"
    assert "GeneratedEnvironmentBundle" not in context.artifacts
    assert "ReleaseManifest" not in context.artifacts
