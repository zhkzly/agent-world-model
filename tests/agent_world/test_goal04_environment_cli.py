import subprocess
import sys

import pytest

from agent_world.artifacts import read_yaml, stable_json
from agent_world.full_chain import run_support_desk_lite_full_chain
from agent_world.online_runtime import RuntimeAction, load_online_runtime
from agent_world.training import read_jsonl


@pytest.fixture()
def package_dir(tmp_path):
    return run_support_desk_lite_full_chain(tmp_path / "envpkg").workflow.package.package_dir


def test_goal04_surface_runtime_index_splits_runtime_control_and_environment_cli(package_dir):
    surface_index = read_yaml(package_dir / "release" / "surface-runtime-index.yaml")
    descriptors = {descriptor["kind"]: descriptor for descriptor in surface_index["descriptors"]}

    assert "cli" not in descriptors
    assert descriptors["runtime_control_cli"]["status"] == "implemented"
    assert descriptors["runtime_control_cli"]["purpose"] == "harness_control"
    assert descriptors["runtime_control_cli"]["module"] == "agent_world.cli_runtime"

    environment_cli = descriptors["environment_cli"]
    assert environment_cli["status"] == "implemented"
    assert environment_cli["purpose"] == "agent_tool_surface"
    assert environment_cli["module"] == "agent_world.fixtures.support_desk_lite_cli"
    assert environment_cli["discovery"]["help_command"] == ["python", "-m", "agent_world.fixtures.support_desk_lite_cli", "--help"]
    assert set(environment_cli["allowed_tool_names"]) == {
        "search_tickets",
        "get_ticket",
        "add_ticket_note",
        "update_ticket_priority",
        "assign_ticket",
        "resolve_ticket",
    }
    for template in environment_cli["tool_command_templates"]:
        assert template["argv_template"][:3] == ["{python_executable}", "-m", "agent_world.fixtures.support_desk_lite_cli"]
        assert template["input_schema"]["additionalProperties"] is False
        assert template["output_parser"] == "json_stdout"
        assert template["allowed_exit_codes"] == [0]
        assert template["timeout_ms"] == 1000
        assert template["state_scope"] == "session"

    help_result = subprocess.run(
        [sys.executable, "-m", "agent_world.fixtures.support_desk_lite_cli", "--help"],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert help_result.returncode == 0
    assert "search-tickets" in help_result.stdout


def test_goal04_environment_cli_surface_executes_task1_success_path(package_dir):
    runtime = load_online_runtime(package_dir)
    runtime.start()
    try:
        session = runtime.reset("task-1", run_id="environment-cli-success")
        session.step(_env_cli_action("env-cli-success-1", "search_tickets", {"status": "open", "customer_tier": "vip", "keyword": "refund"}))
        session.step(_env_cli_action("env-cli-success-2", "get_ticket", {"ticket_id": "T-100"}))
        session.step(
            _env_cli_action(
                "env-cli-success-3",
                "add_ticket_note",
                {"ticket_id": "T-100", "visibility": "internal", "body": "Refund follow-up queued with billing."},
            )
        )
        final = session.finalize()
    finally:
        runtime.close()

    assert final.success is True
    assert final.reward == 1.0
    assert final.reward_source == "deterministic_verifier"

    records = read_jsonl(package_dir / "checks" / "online-step-records.jsonl")
    cli_records = [record for record in records if record["session_id"] == "session-environment-cli-success-task-1"]
    assert len(cli_records) == 3
    for record in cli_records:
        assert record["surface_kind"] == "environment_cli"
        assert record["command_descriptor_ref"] == "release/surface-runtime-index.yaml#environment-cli-support-desk-lite"
        assert record["command_template_id"].startswith("environment-cli-")
        assert record["rendered_argv"][:3] != ["python", "-m", "agent_world.cli_runtime"]
        assert "agent_world.fixtures.support_desk_lite_cli" in record["rendered_argv"]
        assert record["exit_code"] == 0
        assert record["stdout_preview"]
        assert record["stderr_preview"] == ""
        assert record["parsed_output_preview"]
    encoded_records = stable_json(cli_records)
    assert str(package_dir) not in encoded_records
    assert "db_path" not in encoded_records


def test_goal04_environment_cli_surface_failure_path_gets_deterministic_reward_zero(package_dir):
    runtime = load_online_runtime(package_dir)
    runtime.start()
    try:
        session = runtime.reset("task-2", run_id="environment-cli-failure")
        session.step(_env_cli_action("env-cli-failure-1", "search_tickets", {"status": "open", "customer_tier": "standard", "keyword": "login"}))
        session.step(
            _env_cli_action(
                "env-cli-failure-2",
                "assign_ticket",
                {"ticket_id": "T-101", "queue": "enterprise-support", "assignee": "not-iris", "note": "Moved queue only."},
            )
        )
        final = session.finalize()
    finally:
        runtime.close()

    assert final.success is False
    assert final.reward == 0.0
    assert final.failure_class == "deterministic_verifier_failed"
    assert any(check["name"] == "target_assignee_changed" and check["passed"] is False for check in final.verifier_result["checks"])


def test_goal04_environment_cli_rejects_undeclared_tools_and_shell_features(package_dir):
    runtime = load_online_runtime(package_dir)
    runtime.start()
    try:
        session = runtime.reset("task-1", run_id="environment-cli-security")
        rejected_unknown = session.step(_env_cli_action("env-cli-security-1", "delete_ticket", {"ticket_id": "T-100"}))
        assert rejected_unknown.error["type"] == "invalid_tool"

        rejected_semicolon = session.step(
            _env_cli_action(
                "env-cli-security-2",
                "add_ticket_note",
                {"ticket_id": "T-100", "visibility": "internal", "body": "refund; rm -rf tmp"},
            )
        )
        assert rejected_semicolon.error["type"] == "ValueError"
        assert "Forbidden shell feature" in rejected_semicolon.error["message"]

        rejected_bash = session.step(
            _env_cli_action(
                "env-cli-security-3",
                "add_ticket_note",
                {"ticket_id": "T-100", "visibility": "internal", "body": "bash -c echo bad"},
            )
        )
        assert rejected_bash.error["type"] == "ValueError"
        assert "Forbidden shell executable" in rejected_bash.error["message"]

        rejected_pipe = session.step(
            _env_cli_action(
                "env-cli-security-4",
                "add_ticket_note",
                {"ticket_id": "T-100", "visibility": "internal", "body": "refund | cat"},
            )
        )
        assert rejected_pipe.error["type"] == "ValueError"
        assert "Forbidden shell feature" in rejected_pipe.error["message"]

        rejected_redirect = session.step(
            _env_cli_action(
                "env-cli-security-5",
                "add_ticket_note",
                {"ticket_id": "T-100", "visibility": "internal", "body": "refund > out"},
            )
        )
        assert rejected_redirect.error["type"] == "ValueError"
        assert "Forbidden shell feature" in rejected_redirect.error["message"]
    finally:
        runtime.close()


def _env_cli_action(action_id, tool_name, arguments):
    return RuntimeAction(
        action_id=action_id,
        kind="tool_call",
        tool_name=tool_name,
        arguments=arguments,
        metadata={"surface": "environment_cli"},
    )
