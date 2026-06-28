import json
from pathlib import Path

from agent_world.agents import AgentBackendRegistry, AgentResult, MockAgentBackend
from agent_world.artifacts import read_yaml
from agent_world.fixtures.project_board_lite import ProjectBoardLite, create_seed_state, reset_environment, verify_task_completion
from agent_world.fixtures.project_board_lite_nodes import (
    PROJECT_BOARD_LITE_CLI_HELP_PATH,
    PROJECT_BOARD_LITE_EXAMPLES_PATH,
    PROJECT_BOARD_LITE_SCHEMA_PATH,
    ProjectBoardLiteKnowledgeExtractor,
)
from agent_world.pipeline import PipelineRunConfig, PipelineRunner, project_board_lite_node_registry
from agent_world.sources import LocalSourceConnector


def test_goal06_local_source_connector_indexes_cli_schema_and_examples():
    fields = LocalSourceConnector(base_dir=Path.cwd()).build_index_fields(
        [PROJECT_BOARD_LITE_CLI_HELP_PATH, PROJECT_BOARD_LITE_SCHEMA_PATH, PROJECT_BOARD_LITE_EXAMPLES_PATH]
    )

    by_name = {item["name"]: item for item in fields["extractable_objects"]}
    assert fields["sources"][0]["kind"] == "cli_help"
    assert len(fields["sources"][0]["version_or_hash"]) == 64
    assert by_name["card_move"]["object_kind"] == "operation"
    assert by_name["card"]["object_kind"] == "state_entity"
    assert by_name["audit-on-write"]["object_kind"] == "business_rule"
    assert by_name["task-move-blocked-card"]["object_kind"] == "example"
    assert by_name["card_move"]["evidence_refs"][0].startswith("agent_world/fixtures/project_board_lite_cli_help.txt#L")


def test_goal06_project_board_knowledge_pack_is_source_grounded():
    source_index = LocalSourceConnector(base_dir=Path.cwd()).build_index_fields(
        [PROJECT_BOARD_LITE_CLI_HELP_PATH, PROJECT_BOARD_LITE_SCHEMA_PATH, PROJECT_BOARD_LITE_EXAMPLES_PATH]
    )
    knowledge = ProjectBoardLiteKnowledgeExtractor(base_dir=Path.cwd()).build_knowledge_fields(source_index)

    assert not knowledge["uncertainties"]
    assert {item["object_id"] for item in knowledge["state_objects"]} == {"board", "card", "comment", "audit_event"}
    assert {item["operation_id"] for item in knowledge["operations"]} == {"card_list", "card_get", "card_move", "card_assign", "comment_add"}
    assert all(item["source_refs"] for item in knowledge["state_objects"])
    assert all(item["source_refs"] for item in knowledge["operations"])
    assert all(item["source_refs"] for item in knowledge["business_rules"])


def test_goal06_project_board_verifier_positive_and_negative(tmp_path):
    seed = create_seed_state()
    initial = reset_environment(seed)
    final = reset_environment(seed)
    trace = tmp_path / "trace.jsonl"
    surface = ProjectBoardLite(final, trace_path=trace, task_id="pb-task-1")
    surface.card_list(status="blocked")
    surface.card_get("C-11")
    surface.card_move(card_id="C-11", status="in_review", note="Ready for review after checking the blocker.")

    positive = verify_task_completion("pb-task-1", initial, final, surface_trace_path=trace)

    bad_final = reset_environment(seed)
    bad_trace = tmp_path / "bad-trace.jsonl"
    bad_surface = ProjectBoardLite(bad_final, trace_path=bad_trace, task_id="pb-task-1")
    bad_surface.card_list(status="blocked")
    bad_surface.card_get("C-11")
    negative = verify_task_completion("pb-task-1", reset_environment(seed), bad_final, surface_trace_path=bad_trace)

    assert positive["success"] is True
    assert negative["success"] is False
    assert any(check["name"] == "target_card_moved" and check["passed"] is False for check in negative["checks"])


def test_goal06_second_source_family_pipeline_reuses_runner_and_releases(tmp_path):
    registry = project_board_lite_node_registry()
    assert {"S0", "S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9", "IMPLEMENT", "S10", "S11"}.issubset(set(registry.stages()))

    record, context = PipelineRunner(registry).run(
        PipelineRunConfig(run_id="project-board-test", raw_request="Generate project-board-lite.", output_dir=tmp_path)
    )

    assert record.status == "pass"
    assert context.artifacts["ReleaseManifest"]["environment_id"] == "project-board-lite"
    assert len(context.artifacts["TaskSet"]["tasks"]) == 3
    assert sum(bool(task["expected_state_delta"]) for task in context.artifacts["TaskSet"]["tasks"]) == 2
    assert any(task["expected_answer"] for task in context.artifacts["TaskSet"]["tasks"])
    assert {tool["tool_id"] for tool in context.artifacts["EnvironmentSpec"]["logical_tools"]} == {
        operation["operation_id"] for operation in context.artifacts["KnowledgePack"]["operations"]
    }
    assert context.build_check_replay_records[-1]["status"] == "pass"
    assert context.build_check_replay_records[-1]["verifier_result"]["success"] is True
    assert context.build_check_replay_records[-1]["negative_verifier_result"]["success"] is False
    stored = read_yaml(tmp_path / "pipeline-store" / "pipeline-run-record.yaml")
    assert stored["status"] == "pass"
    assert stored["build_check_replay_records"][-1]["environment_id"] == "project-board-lite"


def test_goal06_missing_required_cli_command_stops_before_release(tmp_path):
    cli = tmp_path / "project_board_missing_move_help.txt"
    cli.write_text(
        "\n".join(line for line in PROJECT_BOARD_LITE_CLI_HELP_PATH.read_text(encoding="utf-8").splitlines() if "operation=card_move" not in line),
        encoding="utf-8",
    )

    record, context = PipelineRunner(project_board_lite_node_registry()).run(
        PipelineRunConfig(output_dir=tmp_path / "run", source_paths=[cli, PROJECT_BOARD_LITE_SCHEMA_PATH, PROJECT_BOARD_LITE_EXAMPLES_PATH])
    )

    assert record.status == "fail"
    assert record.node_results[-1].stage == "S5"
    assert "at least three accepted tasks" in record.recovery_suggestion
    assert any("card_move" in item["question"] for item in context.artifacts["KnowledgePack"]["uncertainties"])
    assert "ReleaseManifest" not in context.artifacts


def test_goal06_missing_required_schema_state_stops_before_release(tmp_path):
    schema = tmp_path / "project_board_missing_audit.yaml"
    schema.write_text(
        PROJECT_BOARD_LITE_SCHEMA_PATH.read_text(encoding="utf-8").replace(
            "  - object_id: audit_event\n    name: card audit event\n    fields: [card_id, event_type, field, old_value, new_value, note]\n    relations: [card]\n",
            "",
        ),
        encoding="utf-8",
    )

    record, context = PipelineRunner(project_board_lite_node_registry()).run(
        PipelineRunConfig(output_dir=tmp_path / "run", source_paths=[PROJECT_BOARD_LITE_CLI_HELP_PATH, schema, PROJECT_BOARD_LITE_EXAMPLES_PATH])
    )

    assert record.status == "fail"
    assert record.node_results[-1].stage == "S4"
    assert "unknown state entities" in record.recovery_suggestion
    assert any("audit_event" in item["question"] for item in context.artifacts["KnowledgePack"]["uncertainties"])
    assert "ReleaseManifest" not in context.artifacts


def test_goal06_missing_required_rule_needs_human_before_release(tmp_path):
    examples = tmp_path / "project_board_missing_rule.yaml"
    source_lines = PROJECT_BOARD_LITE_EXAMPLES_PATH.read_text(encoding="utf-8").splitlines()
    filtered = []
    skip_next_description = False
    for line in source_lines:
        if "rule_id: audit-on-write" in line:
            skip_next_description = True
            continue
        if skip_next_description and "description:" in line:
            skip_next_description = False
            continue
        filtered.append(line)
    examples.write_text(
        "\n".join(filtered),
        encoding="utf-8",
    )

    record, context = PipelineRunner(project_board_lite_node_registry()).run(
        PipelineRunConfig(output_dir=tmp_path / "run", source_paths=[PROJECT_BOARD_LITE_CLI_HELP_PATH, PROJECT_BOARD_LITE_SCHEMA_PATH, examples])
    )

    assert record.status == "fail"
    assert record.node_results[-1].stage == "S8"
    assert "FeasibilityReport must pass" in record.recovery_suggestion
    assert context.artifacts["FeasibilityReport"]["status"] == "needs_human"
    assert any("audit-on-write" in item["question"] for item in context.artifacts["KnowledgePack"]["uncertainties"])
    assert "ReleaseManifest" not in context.artifacts


def test_goal06_agent_backed_implementation_writes_invocation_and_stops_before_release(tmp_path):
    class RecordingBackend(MockAgentBackend):
        def __init__(self):
            super().__init__()
            self.requests = []

        def invoke(self, request, config):
            self.requests.append(request)
            return AgentResult(text=json.dumps({"generated_paths": ["isolated/project_board.py"]}), trace_ref="mock://project-board-implement")

    backend = RecordingBackend()
    registry = AgentBackendRegistry()
    registry.register(backend)

    record, context = PipelineRunner(project_board_lite_node_registry(), agent_registry=registry).run(
        PipelineRunConfig(output_dir=tmp_path, implementation_mode="agent")
    )

    assert record.status == "fail"
    assert record.failure_class == "missing_candidate_files"
    assert backend.requests[-1].node_purpose == "implement"
    assert "project-board-lite" in backend.requests[-1].instruction
    assert context.agent_invocations[-1]["node_purpose"] == "implement"
    assert context.agent_invocations[-1]["backend_kind"] == "mock"
    assert context.build_check_replay_records[-1]["environment_id"] == "project-board-lite"
    assert context.build_check_replay_records[-1]["agent_invocation_id"] == context.agent_invocations[-1]["id"]
    assert context.build_check_replay_records[-1]["failure_class"] == "missing_candidate_files"
    assert "ReleaseManifest" not in context.artifacts
