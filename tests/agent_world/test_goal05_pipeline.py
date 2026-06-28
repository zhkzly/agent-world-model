import json
from pathlib import Path

from agent_world.agents import AgentBackendRegistry, AgentResult, MockAgentBackend
from agent_world.artifacts import read_yaml
from agent_world.fixtures.support_desk_lite_nodes import SUPPORT_DESK_LITE_PRD_PATH
from agent_world.pipeline import PipelineRunConfig, PipelineRunner, support_desk_lite_fixture_node_registry
from agent_world.sources import LocalSourceConnector, SupportDeskLiteKnowledgeExtractor


def test_goal05_local_source_connector_indexes_path_hash_and_line_refs():
    fields = LocalSourceConnector(base_dir=Path.cwd()).build_index_fields([SUPPORT_DESK_LITE_PRD_PATH])

    assert fields["sources"][0]["kind"] == "prd"
    assert fields["sources"][0]["uri_or_path"] == "agent_world/fixtures/support_desk_lite_prd.md"
    assert len(fields["sources"][0]["version_or_hash"]) == 64
    assert any("state-objects" in ref for ref in fields["sources"][0]["section_refs"])
    operation = next(obj for obj in fields["extractable_objects"] if obj["name"] == "resolve_ticket")
    assert operation["object_kind"] == "operation"
    assert operation["evidence_refs"][0].startswith("agent_world/fixtures/support_desk_lite_prd.md#L")


def test_goal05_knowledge_pack_extracts_source_refs_from_connector():
    source_index = LocalSourceConnector(base_dir=Path.cwd()).build_index_fields([SUPPORT_DESK_LITE_PRD_PATH])
    knowledge = SupportDeskLiteKnowledgeExtractor(base_dir=Path.cwd()).build_knowledge_fields(source_index)

    assert not knowledge["uncertainties"]
    ticket = next(item for item in knowledge["state_objects"] if item["object_id"] == "ticket")
    resolve = next(item for item in knowledge["operations"] if item["operation_id"] == "resolve_ticket")
    assert ticket["source_refs"][0].startswith("source-agent-world-fixtures-support-desk-lite-prd-md#L")
    assert resolve["writes"] == ["ticket", "ticket_note", "audit_event"]
    assert resolve["source_refs"]


def test_goal05_pipeline_registry_runs_source_grounded_nodes_and_deterministic_implementation(tmp_path):
    registry = support_desk_lite_fixture_node_registry()
    assert {"S0", "S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9", "IMPLEMENT", "S10", "S11"}.issubset(set(registry.stages()))

    record, context = PipelineRunner(registry).run(PipelineRunConfig(output_dir=tmp_path))

    assert record.status == "pass"
    assert context.artifacts["SourceEvidenceIndex"]["sources"][0]["uri_or_path"].endswith("support_desk_lite_prd.md")
    assert {tool["tool_id"] for tool in context.artifacts["EnvironmentSpec"]["logical_tools"]} == {
        operation["operation_id"] for operation in context.artifacts["KnowledgePack"]["operations"]
    }
    assert context.build_check_replay_records[0]["status"] == "pass"
    assert context.build_check_replay_records[0]["verifier_result"]["success"] is True
    stored_record = read_yaml(tmp_path / "pipeline-store" / "pipeline-run-record.yaml")
    assert stored_record["status"] == "pass"
    assert stored_record["build_check_replay_records"][0]["replay_command"] == "verify_task_completion task-1 over isolated SQLite copy"


def test_goal05_missing_operation_source_fails_downstream_gate(tmp_path):
    broken = tmp_path / "support_desk_missing_resolve.md"
    broken.write_text(
        "\n".join(line for line in SUPPORT_DESK_LITE_PRD_PATH.read_text(encoding="utf-8").splitlines() if "`resolve_ticket` operation" not in line),
        encoding="utf-8",
    )

    record, context = PipelineRunner().run(PipelineRunConfig(output_dir=tmp_path / "run", source_paths=[broken]))

    assert record.status == "fail"
    assert record.node_results[-1].stage == "S5"
    assert "at least five accepted tasks" in record.recovery_suggestion
    assert any("resolve_ticket" in item["question"] for item in context.artifacts["KnowledgePack"]["uncertainties"])
    assert "ReleaseManifest" not in context.artifacts


def test_goal05_missing_business_rule_needs_human_before_implementation(tmp_path):
    broken = tmp_path / "support_desk_missing_rule.md"
    broken.write_text(
        "\n".join(line for line in SUPPORT_DESK_LITE_PRD_PATH.read_text(encoding="utf-8").splitlines() if "`audit-on-write` rule" not in line),
        encoding="utf-8",
    )

    record, context = PipelineRunner().run(PipelineRunConfig(output_dir=tmp_path / "run", source_paths=[broken]))

    assert record.status == "fail"
    assert record.node_results[-1].stage == "S8"
    assert "FeasibilityReport must pass" in record.recovery_suggestion
    assert context.artifacts["FeasibilityReport"]["status"] == "needs_human"
    assert any("audit-on-write" in item["question"] for item in context.artifacts["KnowledgePack"]["uncertainties"])
    assert "ImplementationRequest" not in context.artifacts


def test_goal05_agent_backed_implementation_uses_agent_backend_and_stops_before_release(tmp_path):
    class RecordingBackend(MockAgentBackend):
        def __init__(self):
            super().__init__()
            self.requests = []

        def invoke(self, request, config):
            self.requests.append(request)
            return AgentResult(text=json.dumps({"generated_paths": ["isolated/package.py"]}), trace_ref="mock://implement")

    backend = RecordingBackend()
    registry = AgentBackendRegistry()
    registry.register(backend)

    record, context = PipelineRunner(agent_registry=registry).run(
        PipelineRunConfig(output_dir=tmp_path, implementation_mode="agent")
    )

    assert record.status == "needs_human"
    assert backend.requests[-1].node_purpose == "implement"
    assert context.agent_invocations[-1]["node_purpose"] == "implement"
    assert context.agent_invocations[-1]["backend_kind"] == "mock"
    assert context.build_check_replay_records[-1]["status"] == "needs_human"
    assert context.build_check_replay_records[-1]["agent_invocation_id"] == context.agent_invocations[-1]["id"]
    assert "ReleaseManifest" not in context.artifacts
