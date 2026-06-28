import json
import subprocess
import sys

from agent_world.artifacts import read_yaml
from agent_world.full_chain import run_support_desk_lite_full_chain
from agent_world.training import read_jsonl


def test_goal03_cli_runtime_executes_task_and_records_command_metadata(tmp_path):
    package_dir = run_support_desk_lite_full_chain(tmp_path / "envpkg").workflow.package.package_dir

    health = _cli_json(package_dir, "health")
    assert health["status"] == "ok"
    assert health["surface"] == "runtime_control_cli"
    assert health["descriptor"]["kind"] == "runtime_control_cli"
    assert health["descriptor"]["purpose"] == "harness_control"
    assert health["descriptor"]["status"] == "implemented"

    reset = _cli_json(package_dir, "reset", "--task", "task-1", "--run", "cli-demo")
    session_id = reset["session_id"]
    assert reset["observation"]["task_id"] == "task-1"
    observed = _cli_json(package_dir, "observe", "--session", session_id)
    assert observed["observation"]["task_id"] == "task-1"
    assert observed["observation"]["done"] is False

    _cli_json(
        package_dir,
        "step",
        "--session",
        session_id,
        "--tool",
        "search_tickets",
        "--args-json",
        json.dumps({"status": "open", "customer_tier": "vip", "keyword": "refund"}),
    )
    _cli_json(
        package_dir,
        "step",
        "--session",
        session_id,
        "--tool",
        "get_ticket",
        "--args-json",
        json.dumps({"ticket_id": "T-100"}),
    )
    step = _cli_json(
        package_dir,
        "step",
        "--session",
        session_id,
        "--tool",
        "add_ticket_note",
        "--args-json",
        json.dumps({"ticket_id": "T-100", "visibility": "internal", "body": "Refund follow-up queued with billing."}),
    )
    assert step["command"]["exit_code"] == 0
    assert step["step"]["observation"]["command"]["template_id"] == "runtime-control-cli-step-add_ticket_note"

    final = _cli_json(package_dir, "finalize", "--session", session_id)
    assert final["final"]["success"] is True
    assert final["final"]["reward"] == 1.0
    assert final["final"]["reward_source"] == "deterministic_verifier"

    records = read_jsonl(package_dir / "checks" / "online-step-records.jsonl")
    cli_records = [record for record in records if record["session_id"] == session_id]
    assert len(cli_records) == 3
    assert all(record["surface_kind"] == "runtime_control_cli" for record in cli_records)
    assert all(record["command"]["exit_code"] == 0 for record in cli_records)
    assert all(record["command_argv"][:3] == ["python", "-m", "agent_world.cli_runtime"] for record in cli_records)
    assert all(record["stdout_preview"] for record in cli_records)
    assert all(record["stderr_preview"] == "" for record in cli_records)
    assert all(record["command_descriptor_ref"] == "release/surface-runtime-index.yaml#runtime-control-cli-support-desk-lite" for record in cli_records)

    observation_ref = cli_records[-1]["observation_ref"]
    observation = json.loads((package_dir / observation_ref).read_text(encoding="utf-8"))
    assert observation["command"]["template_id"] == "runtime-control-cli-step-add_ticket_note"


def test_goal03_cli_runtime_wrong_path_gets_deterministic_verifier_failure(tmp_path):
    package_dir = run_support_desk_lite_full_chain(tmp_path / "envpkg").workflow.package.package_dir
    reset = _cli_json(package_dir, "reset", "--task", "task-2", "--run", "cli-failure")
    session_id = reset["session_id"]

    _cli_json(
        package_dir,
        "step",
        "--session",
        session_id,
        "--tool",
        "search_tickets",
        "--args-json",
        json.dumps({"status": "open", "customer_tier": "standard", "keyword": "login"}),
    )
    _cli_json(
        package_dir,
        "step",
        "--session",
        session_id,
        "--tool",
        "assign_ticket",
        "--args-json",
        json.dumps({"ticket_id": "T-101", "queue": "enterprise-support", "assignee": "not-iris", "note": "Moved queue only."}),
    )

    final = _cli_json(package_dir, "finalize", "--session", session_id)
    assert final["final"]["success"] is False
    assert final["final"]["reward"] == 0.0
    assert final["final"]["failure_class"] == "deterministic_verifier_failed"
    assert any(check["name"] == "target_assignee_changed" and check["passed"] is False for check in final["final"]["verifier_result"]["checks"])


def test_goal03_cli_runtime_rejects_non_allowlisted_tool_and_manifest_marks_cli_implemented(tmp_path):
    package_dir = run_support_desk_lite_full_chain(tmp_path / "envpkg").workflow.package.package_dir
    reset = _cli_json(package_dir, "reset", "--task", "task-1", "--run", "cli-security")
    failed = _cli(package_dir, "step", "--session", reset["session_id"], "--tool", "bash", "--args-json", "{}")

    assert failed.returncode == 2
    assert "Forbidden shell executable" in failed.stderr

    surface_index = read_yaml(package_dir / "release" / "surface-runtime-index.yaml")
    cli_descriptor = next(descriptor for descriptor in surface_index["descriptors"] if descriptor["kind"] == "runtime_control_cli")
    assert cli_descriptor["status"] == "implemented"
    assert cli_descriptor["purpose"] == "harness_control"
    assert cli_descriptor["allowed_subcommands"] == ["health", "reset", "observe", "step", "finalize"]
    assert set(cli_descriptor["allowed_runtime_tools"]) == {
        "search_tickets",
        "get_ticket",
        "add_ticket_note",
        "update_ticket_priority",
        "assign_ticket",
        "resolve_ticket",
    }
    release = read_yaml(package_dir / "release" / "release-manifest.yaml")
    assert release["runtime_surface_status"]["runtime_control_cli"] == "implemented"
    assert release["runtime_surface_status"]["environment_cli"] == "implemented"
    assert release["runtime_refs"]["cli_runtime_module"] == "agent_world.cli_runtime"
    assert release["runtime_refs"]["environment_cli_module"] == "agent_world.fixtures.support_desk_lite_cli"


def _cli_json(package_dir, *args):
    completed = _cli(package_dir, *args)
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def _cli(package_dir, *args):
    return subprocess.run(
        [sys.executable, "-m", "agent_world.cli_runtime", "--package", str(package_dir), *args],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
