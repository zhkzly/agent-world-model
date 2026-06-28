import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import sys
import threading
from pathlib import Path

import pytest

from agent_world.agents import AgentBackendRegistry, AgentResult
from agent_world.fixtures.project_board_lite_codegen import (
    AGENT_GENERATED_BUNDLE_ID,
    DISALLOWED_FIXTURE_IMPORT,
    GENERATED_FILE_KINDS,
    check_project_board_generated_bundle,
    write_project_board_agent_candidate_files,
    write_project_board_generated_files,
)
from agent_world.pipeline import PipelineRunConfig, PipelineRunner, project_board_lite_node_registry


class ProjectBoardCodegenBackend:
    backend_kind = "mock"

    def __init__(self, *, variant: str = "success", secret: str = "") -> None:
        self.variant = variant
        self.secret = secret
        self.requests = []

    def invoke(self, request, config):
        self.requests.append(request)
        work_dir = Path(request.permissions["filesystem_root"])
        if self.variant == "malformed":
            return AgentResult(text="not json", trace_ref=f"mock://trace/{self.secret}")
        manifest = write_project_board_agent_candidate_files(
            work_dir,
            source_refs=request.input_artifact_ids,
            implementation_request_id=request.input_artifact_ids[0],
        )
        if self.variant == "path_traversal":
            manifest["generated_files"][0]["path"] = "../runtime.py"
        elif self.variant == "missing_file":
            (work_dir / "verifier.py").unlink()
        elif self.variant == "hash_mismatch":
            manifest["generated_files"][0]["sha256"] = "0" * 64
        elif self.variant == "undeclared_file":
            (work_dir / "extra.py").write_text("EXTRA = True\n", encoding="utf-8")
        elif self.variant == "fixture_import":
            (work_dir / "runtime.py").write_text(f"import {DISALLOWED_FIXTURE_IMPORT}\n", encoding="utf-8")
            manifest = _manifest_from_files(work_dir, request.input_artifact_ids)
        elif self.variant == "check_failure":
            (work_dir / "verifier.py").write_text(
                "def verify_task_completion(*args, **kwargs):\n"
                "    return {'success': False, 'checks': [{'name': 'forced_failure', 'passed': False}]}\n",
                encoding="utf-8",
            )
            manifest = _manifest_from_files(work_dir, request.input_artifact_ids)
        return AgentResult(
            text=json.dumps(manifest, sort_keys=True),
            evidence_refs=["mock://project-board-codegen", f"mock://evidence/{self.secret}"],
            output_artifact_ids=[AGENT_GENERATED_BUNDLE_ID],
            trace_ref="mock://trace/project-board-codegen",
        )


def test_goal08_project_board_agent_backed_codegen_releases_verified_bundle(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_WORLD_OPENAI_API_KEY", "secret-value")
    backend = ProjectBoardCodegenBackend(secret="secret-value")
    registry = AgentBackendRegistry()
    registry.register(backend)

    record, context = PipelineRunner(project_board_lite_node_registry(), agent_registry=registry).run(
        PipelineRunConfig(
            output_dir=tmp_path,
            raw_request="Generate project-board-lite.",
            implementation_mode="agent",
            env={"AGENT_WORLD_AGENT_BACKEND": "mock", "AGENT_WORLD_OPENAI_API_KEY": "secret-value"},
        )
    )

    bundle = context.artifacts["GeneratedEnvironmentBundle"]
    release = context.artifacts["ReleaseManifest"]
    invocation = context.agent_invocations[-1]
    work_dir = Path(bundle["build_dir"])

    assert record.status == "pass"
    assert bundle["id"] == AGENT_GENERATED_BUNDLE_ID
    assert bundle["status"] == "accepted"
    assert bundle["implementation_mode"] == "agent_backed_codegen"
    assert bundle["agent_invocation_ref"] == invocation["id"]
    assert release["generated_bundle_ref"] == bundle["id"]
    assert "agent-backed codegen path" in release["known_limits"][0]
    assert invocation["node_purpose"] == "implement"
    assert invocation["output_artifact_ids"] == [bundle["id"]]
    assert "secret-value" not in json.dumps(invocation)
    assert "[REDACTED_SECRET]" in json.dumps(invocation["evidence_refs"])
    assert backend.requests[-1].permissions["filesystem"] == "isolated_workdir"
    assert backend.requests[-1].permissions["filesystem_root"] == str(work_dir)
    assert work_dir.is_relative_to(tmp_path / "pipeline-store" / "build" / "agent-runs")

    files_by_name = {Path(item["path"]).name: item for item in bundle["generated_files"]}
    assert set(files_by_name) == set(GENERATED_FILE_KINDS)
    for name, kind in GENERATED_FILE_KINDS.items():
        assert files_by_name[name]["kind"] == kind
        assert files_by_name[name]["sha256"] == _sha256(work_dir / name)
        assert files_by_name[name]["source_refs"]
    assert DISALLOWED_FIXTURE_IMPORT not in (work_dir / "runtime.py").read_text(encoding="utf-8")

    check = check_project_board_generated_bundle(work_dir)
    assert check["success"] is True
    assert check["positive_verifier_result"]["success"] is True
    assert check["negative_verifier_result"]["success"] is False


def test_goal08_process_agent_adapter_writes_isolated_bundle(tmp_path):
    helper = Path(__file__).resolve().parents[1] / "fixtures" / "project_board_codegen_agent.py"
    env = {
        "AGENT_WORLD_AGENT_BACKEND": "process_agent",
        "AGENT_WORLD_CODE_AGENT_CMD": f"{sys.executable} {helper}",
        "AGENT_WORLD_PROCESS_AGENT_ALLOWLIST": sys.executable,
    }

    record, context = PipelineRunner(project_board_lite_node_registry()).run(
        PipelineRunConfig(output_dir=tmp_path, raw_request="Generate project-board-lite.", implementation_mode="agent", env=env)
    )

    assert record.status == "pass"
    assert context.artifacts["AgentBackendConfig"]["command"]["argv"] == [sys.executable, str(helper)]
    assert context.agent_invocations[-1]["backend_kind"] == "process_agent"
    assert context.artifacts["GeneratedEnvironmentBundle"]["id"] == AGENT_GENERATED_BUNDLE_ID
    assert context.build_check_replay_records[-1]["status"] == "pass"


def test_goal08_openai_codegen_backend_writes_model_returned_files(tmp_path, monkeypatch):
    model_files_dir = tmp_path / "model-files"
    write_project_board_generated_files(model_files_dir)
    write_project_board_agent_candidate_files(model_files_dir, source_refs=["model://project-board"], implementation_request_id="impl-project-board-lite-first-slice")
    response_content = json.dumps(
        {
            "files": [
                {
                    "path": filename,
                    "content": (model_files_dir / filename).read_text(encoding="utf-8"),
                    "source_refs": ["model://project-board"],
                }
                for filename in GENERATED_FILE_KINDS
            ],
            "evidence_refs": ["model://project-board-codegen"],
        },
        sort_keys=True,
    )
    seen_requests: list[dict[str, object]] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            body = self.rfile.read(int(self.headers.get("Content-Length", "0"))).decode("utf-8")
            seen_requests.append({"path": self.path, "authorization": self.headers.get("Authorization", ""), "body": json.loads(body)})
            payload = {
                "id": "chatcmpl-test",
                "object": "chat.completion",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": response_content}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 100, "total_tokens": 200},
            }
            encoded = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, format, *args):  # noqa: A002
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("AGENT_WORLD_OPENAI_API_KEY", "test-secret-key")
    try:
        env = {
            "AGENT_WORLD_AGENT_BACKEND": "openai_codegen",
            "AGENT_WORLD_OPENAI_BASE_URL": f"http://127.0.0.1:{server.server_port}/v1",
            "AGENT_WORLD_OPENAI_API_KEY": "test-secret-key",
            "AGENT_WORLD_OPENAI_MODEL": "fake-codegen-model",
            "AGENT_WORLD_AGENT_NETWORK": "1",
            "AGENT_WORLD_AGENT_MAX_TOKENS": "12000",
        }
        record, context = PipelineRunner(project_board_lite_node_registry()).run(
            PipelineRunConfig(run_id="openai-codegen-test", output_dir=tmp_path / "run", raw_request="Generate project-board-lite.", implementation_mode="agent", env=env)
        )
    finally:
        server.shutdown()
        server.server_close()

    bundle = context.artifacts["GeneratedEnvironmentBundle"]
    invocation = context.agent_invocations[-1]
    work_dir = Path(bundle["build_dir"])

    assert record.status == "pass"
    assert seen_requests
    assert seen_requests[-1]["path"] == "/v1/chat/completions"
    assert seen_requests[-1]["authorization"] == "Bearer test-secret-key"
    request_body = seen_requests[-1]["body"]
    assert request_body["model"] == "fake-codegen-model"
    assert "Accepted artifact context JSON" in request_body["messages"][1]["content"]
    assert "ImplementationRequest" in request_body["messages"][1]["content"]
    assert bundle["id"] == AGENT_GENERATED_BUNDLE_ID
    assert bundle["status"] == "accepted"
    assert bundle["implementation_mode"] == "agent_backed_codegen"
    assert invocation["backend_kind"] == "openai_codegen"
    assert invocation["permissions"]["network"] is True
    assert invocation["permissions"]["auth"] is True
    assert "test-secret-key" not in json.dumps(invocation)
    assert (work_dir / "runtime.py").read_text(encoding="utf-8") == (model_files_dir / "runtime.py").read_text(encoding="utf-8")
    check = check_project_board_generated_bundle(work_dir)
    assert check["success"] is True


@pytest.mark.parametrize(
    ("variant", "failure_class"),
    [
        ("malformed", "malformed_agent_output"),
        ("path_traversal", "path_traversal_rejected"),
        ("missing_file", "missing_generated_file"),
        ("hash_mismatch", "hash_mismatch"),
        ("undeclared_file", "undeclared_generated_file"),
        ("fixture_import", "fixture_runtime_import"),
        ("check_failure", "generated_bundle_check_failed"),
    ],
)
def test_goal08_bad_agent_candidate_stops_before_release(tmp_path, variant, failure_class):
    registry = AgentBackendRegistry()
    registry.register(ProjectBoardCodegenBackend(variant=variant))

    record, context = PipelineRunner(project_board_lite_node_registry(), agent_registry=registry).run(
        PipelineRunConfig(output_dir=tmp_path, raw_request="Generate project-board-lite.", implementation_mode="agent")
    )

    assert record.status == "fail"
    assert record.node_results[-1].stage == "IMPLEMENT"
    assert record.failure_class == failure_class
    assert context.build_check_replay_records[-1]["failure_class"] == failure_class
    assert "ReleaseManifest" not in context.artifacts
    if variant == "check_failure":
        assert context.artifacts["GeneratedEnvironmentBundle"]["status"] == "fail"
    else:
        assert "GeneratedEnvironmentBundle" not in context.artifacts


class RepairingProjectBoardCodegenBackend:
    backend_kind = "mock"

    def __init__(self, *, always_fail: bool = False) -> None:
        self.always_fail = always_fail
        self.requests = []

    def invoke(self, request, config):
        self.requests.append(request)
        work_dir = Path(request.permissions["filesystem_root"])
        manifest = write_project_board_agent_candidate_files(
            work_dir,
            source_refs=request.input_artifact_ids,
            implementation_request_id=request.input_artifact_ids[0],
        )
        if self.always_fail or len(self.requests) == 1:
            (work_dir / "verifier.py").write_text(
                "def verify_task_completion(*args, **kwargs):\n"
                "    return {'success': False, 'checks': [{'name': 'forced_failure', 'passed': False}]}\n",
                encoding="utf-8",
            )
            manifest = _manifest_from_files(work_dir, request.input_artifact_ids)
        return AgentResult(
            text=json.dumps(manifest, sort_keys=True),
            evidence_refs=[f"mock://repair-attempt-{len(self.requests)}"],
            output_artifact_ids=[AGENT_GENERATED_BUNDLE_ID],
            trace_ref=f"mock://trace/repair-attempt-{len(self.requests)}",
        )


def test_goal08_bounded_repair_retries_agent_candidate_and_releases(tmp_path):
    backend = RepairingProjectBoardCodegenBackend()
    registry = AgentBackendRegistry()
    registry.register(backend)

    record, context = PipelineRunner(project_board_lite_node_registry(), agent_registry=registry).run(
        PipelineRunConfig(
            output_dir=tmp_path,
            raw_request="Generate project-board-lite with one repair.",
            implementation_mode="agent",
            max_repair_attempts=1,
        )
    )

    assert record.status == "pass"
    assert len(backend.requests) == 2
    assert len(context.agent_invocations) == 2
    assert [item["attempt_index"] for item in context.build_check_replay_records] == [1, 2]
    assert context.build_check_replay_records[0]["status"] == "fail"
    assert context.build_check_replay_records[1]["status"] == "pass"
    assert len(context.repair_failure_packets) == 1
    assert context.repair_failure_packets[0]["failure_class"] == "generated_bundle_check_failed"
    assert set(context.repair_failure_packets[0]["failed_task_ids"]) == {"pb-task-1", "pb-task-2", "pb-task-3"}
    assert "Previous failure packet JSON" in backend.requests[1].instruction
    assert "failure-packet-implement-attempt-1" in backend.requests[1].input_artifact_ids
    assert context.artifacts["GeneratedEnvironmentBundle"]["status"] == "accepted"
    assert context.artifacts["ReleaseManifest"]["generated_bundle_ref"] == AGENT_GENERATED_BUNDLE_ID


def test_goal08_bounded_repair_exhaustion_stops_before_release(tmp_path):
    backend = RepairingProjectBoardCodegenBackend(always_fail=True)
    registry = AgentBackendRegistry()
    registry.register(backend)

    record, context = PipelineRunner(project_board_lite_node_registry(), agent_registry=registry).run(
        PipelineRunConfig(
            output_dir=tmp_path,
            raw_request="Generate project-board-lite with bounded repair exhaustion.",
            implementation_mode="agent",
            max_repair_attempts=0,
            env={"AGENT_WORLD_MAX_REPAIR_ATTEMPTS": "1"},
        )
    )

    assert record.status == "fail"
    assert record.failure_class == "generated_bundle_check_failed"
    assert len(backend.requests) == 2
    assert len(context.agent_invocations) == 2
    assert len(context.repair_failure_packets) == 2
    assert context.build_check_replay_records[-1]["attempt_index"] == 2
    assert context.artifacts["GeneratedEnvironmentBundle"]["status"] == "fail"
    assert "ReleaseManifest" not in context.artifacts


def test_goal08_live_backend_smoke_skips_without_explicit_config():
    if not (os.environ.get("AGENT_WORLD_LIVE_CODEGEN_SMOKE") and os.environ.get("AGENT_WORLD_CODE_AGENT_CMD")):
        pytest.skip("live backend smoke requires AGENT_WORLD_LIVE_CODEGEN_SMOKE=1 and explicit backend config")


def _manifest_from_files(work_dir: Path, source_refs: list[str]) -> dict[str, object]:
    return {
        "candidate_dir": ".",
        "bundle_id": AGENT_GENERATED_BUNDLE_ID,
        "environment_id": "project-board-lite",
        "generated_files": [
            {
                "path": filename,
                "kind": kind,
                "sha256": _sha256(work_dir / filename),
                "source_refs": source_refs,
            }
            for filename, kind in GENERATED_FILE_KINDS.items()
        ],
        "runtime_entrypoint": "runtime.ProjectBoardLite",
        "seed_fixture_ref": "seed_state.json",
        "verifier_entrypoint": "verifier.verify_task_completion",
        "surface_descriptors": ["surface_descriptor.json"],
        "check_commands": [["python", "check_replay.py"]],
        "replay_commands": [["python", "check_replay.py", "--task", task_id] for task_id in ["pb-task-1", "pb-task-2", "pb-task-3"]],
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
