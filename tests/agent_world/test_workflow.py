from agent_world.agents import AgentBackendRegistry, AgentResult
from agent_world.artifacts import read_yaml, validate_artifact
from agent_world.workflow import FirstSliceWorkflow
import sys
from pathlib import Path


def test_first_slice_workflow_assembles_surface_neutral_package(tmp_path):
    result = FirstSliceWorkflow().run(output_dir=tmp_path / "envpkg")

    expected_files = [
        "package.yaml",
        "sources/evidence-index.yaml",
        "spec/need.yaml",
        "spec/knowledge-pack.yaml",
        "spec/environment.yaml",
        "spec/tool-graph.yaml",
        "spec/tasks.yaml",
        "spec/surfaces.yaml",
        "spec/verifiers.yaml",
        "spec/feasibility.yaml",
        "spec/implementation-request.yaml",
        "spec/package-plan.yaml",
        "checks/agent-backend-config.yaml",
        "checks/gate-records.yaml",
        "checks/review-records.yaml",
        "checks/agent-invocations.jsonl",
        "checks/surface-traces.jsonl",
        "checks/replay-plan.yaml",
        "release/release-manifest.yaml",
        "release/task-records.jsonl",
        "release/verifier-records.jsonl",
        "release/consumer-index.yaml",
        "fixtures/seed/support-desk-lite.sqlite",
    ]
    for relative in expected_files:
        assert (result.package.package_dir / relative).exists(), relative

    assert len(result.review_records) == 15
    reviewed_stages = {record["source_stage"] for record in result.review_records}
    assert reviewed_stages == {f"S{i}" for i in range(12)}
    for artifact_type in ["AgentBackendConfig", "ReplayPlan", "ConsumerIndex"]:
        artifact_id = result.artifacts[artifact_type]["id"]
        assert any(artifact_id in record["reviewed_artifact_ids"] for record in result.review_records)
        assert any(artifact_id in record["checked_artifact_ids"] for record in result.gate_records)
    invocation_ids = [record["id"] for record in result.agent_invocations]
    assert len(invocation_ids) == len(set(invocation_ids))
    assert any(record["gate_id"] == "G14" for record in result.gate_records)
    assert result.artifacts["ReplayPlan"]["snapshot_hashes"]["seed"]
    assert result.artifacts["ReplayPlan"]["replay_commands"]
    assert result.artifacts["SurfacePlan"]["surface_status"] == {
        "python": "required_for_first_slice",
        "cli": "deferred",
        "http": "deferred",
        "mcp": "deferred",
    }
    assert result.artifacts["ReleaseManifest"]["environment_id"] == "support-desk-lite"
    assert "awm" not in result.artifacts["ReleaseManifest"]["environment_id"]
    assert result.artifacts["ConsumerIndex"]["id"] == "consumer-support-desk-lite"
    assert result.artifacts["ReleaseManifest"]["id"] == "release-support-desk-lite"
    assert result.artifacts["ReleaseManifest"]["id"] not in result.artifacts["ReleaseManifest"]["inputs"]

    validate_artifact("ReleaseManifest", read_yaml(result.package.package_dir / "release/release-manifest.yaml"))


def test_legacy_awm_cli_module_still_imports():
    import awm.cli

    assert callable(awm.cli.main)


def test_first_slice_workflow_runs_with_process_agent_backend(tmp_path):
    helper = Path(__file__).resolve().parents[1] / "fixtures" / "workflow_agent.py"
    env = {
        "AGENT_WORLD_AGENT_BACKEND": "process_agent",
        "AGENT_WORLD_CODEX_CMD": f"{sys.executable} {helper}",
        "AGENT_WORLD_PROCESS_AGENT_ALLOWLIST": sys.executable,
    }

    result = FirstSliceWorkflow().run(output_dir=tmp_path / "envpkg", env=env)

    assert result.artifacts["AgentBackendConfig"]["backend_kind"] == "process_agent"
    assert result.agent_invocations
    assert all(record["backend_kind"] == "process_agent" for record in result.agent_invocations)
    assert all(record["status"] == "pass" for record in result.agent_invocations)


def test_invocation_ids_keep_artifact_type_prefixes(tmp_path):
    result = FirstSliceWorkflow().run(output_dir=tmp_path / "envpkg")

    assert any(
        record["id"].startswith("invoke-s6-synthesize-logicaltoolgraph-")
        for record in result.agent_invocations
    )
    assert not any("synthesize-icaltoolgraph" in record["id"] for record in result.agent_invocations)


def test_first_slice_workflow_passes_explicit_permissions_to_llm_backend(tmp_path):
    class RecordingLlmBackend:
        backend_kind = "llm"

        def __init__(self):
            self.requests = []

        def invoke(self, request, config):
            self.requests.append(request)
            if request.node_purpose == "review":
                return AgentResult(
                    text=(
                        '{"alignment_status":"pass",'
                        f'"reviewed_artifact_ids":["{request.input_artifact_ids[0]}"],'
                        '"drift_findings":[],"required_fixes":[],"waived_risks":[],'
                        '"reviewer_note":"recording llm review"}'
                    )
                )
            return AgentResult(text=f"recording llm output for {request.stage}:{request.node_purpose}")

    backend = RecordingLlmBackend()
    registry = AgentBackendRegistry()
    registry.register(backend)
    env = {
        "AGENT_WORLD_AGENT_BACKEND": "llm",
        "AGENT_WORLD_OPENAI_API_KEY": "test-secret",
        "AGENT_WORLD_OPENAI_MODEL": "test-model",
        "AGENT_WORLD_AGENT_NETWORK": "1",
    }

    result = FirstSliceWorkflow(registry=registry).run(output_dir=tmp_path / "envpkg", env=env)

    assert result.artifacts["AgentBackendConfig"]["backend_kind"] == "llm"
    assert backend.requests
    assert all(request.permissions["network"] is True for request in backend.requests)
    assert all(request.permissions["auth"] is True for request in backend.requests)
    review_requests = [request for request in backend.requests if request.node_purpose == "review"]
    assert review_requests
    assert all("Return only a JSON object" in request.instruction for request in review_requests)
    assert all("Artifact JSON:" in request.instruction for request in review_requests)
    assert all("evaluated after this review record is produced" in request.instruction for request in review_requests)
