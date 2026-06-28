import pytest

from agent_world.adapters.grpo import (
    build_prompt_dataset,
    consume_runtime_contract,
    validate_grpo_adapter_index,
    validate_verl_adapter_config,
)
from agent_world.artifacts import read_yaml, stable_json
from agent_world.full_chain import run_support_desk_lite_full_chain
from agent_world.online_runtime import (
    RuntimeAction,
    load_online_runtime,
    validate_online_final_record,
    validate_online_records,
    validate_online_step_record,
    validate_runtime_index,
    validate_surface_runtime_index,
)
from agent_world.training import read_jsonl


@pytest.fixture()
def package_dir(tmp_path):
    return run_support_desk_lite_full_chain(tmp_path / "envpkg").workflow.package.package_dir


def test_goal03_online_runtime_success_and_failure_paths(package_dir):
    runtime = load_online_runtime(package_dir)
    runtime.start()
    try:
        session = runtime.reset("task-1", run_id="online-success")
        observation = session.observe()
        encoded_observation = stable_json(observation.to_dict()).lower()
        assert "verifier" not in encoded_observation
        assert "sqlite" not in encoded_observation
        assert "dependency_path" not in encoded_observation
        assert "backend" not in encoded_observation

        session.step(
            RuntimeAction(
                action_id="success-1",
                kind="tool_call",
                tool_name="search_tickets",
                arguments={"status": "open", "customer_tier": "vip", "keyword": "refund"},
            )
        )
        session.step(RuntimeAction(action_id="success-2", kind="tool_call", tool_name="get_ticket", arguments={"ticket_id": "T-100"}))
        session.step(
            RuntimeAction(
                action_id="success-3",
                kind="tool_call",
                tool_name="add_ticket_note",
                arguments={"ticket_id": "T-100", "visibility": "internal", "body": "Refund follow-up queued with billing."},
            )
        )
        final = session.finalize()
        assert final.success is True
        assert final.reward == 1.0
        assert final.reward_source == "deterministic_verifier"

        bad_session = runtime.reset("task-2", run_id="online-failure")
        bad_session.step(
            RuntimeAction(
                action_id="failure-1",
                kind="tool_call",
                tool_name="search_tickets",
                arguments={"status": "open", "customer_tier": "standard", "keyword": "login"},
            )
        )
        bad_session.step(
            RuntimeAction(
                action_id="failure-2",
                kind="tool_call",
                tool_name="assign_ticket",
                arguments={"ticket_id": "T-101", "queue": "enterprise-support", "assignee": "not-iris", "note": "Moved queue only."},
            )
        )
        failed = bad_session.finalize()
        assert failed.success is False
        assert failed.reward == 0.0
        assert failed.failure_class == "deterministic_verifier_failed"
        assert failed.recovery_suggestion
        assert any(check["name"] == "target_assignee_changed" and check["passed"] is False for check in failed.verifier_result["checks"])
    finally:
        runtime.close()

    counts = validate_online_records(package_dir)
    assert counts == {"online_step_records": 5, "online_final_records": 2}
    step_records = read_jsonl(package_dir / "checks" / "online-step-records.jsonl")
    final_records = read_jsonl(package_dir / "checks" / "online-final-records.jsonl")
    for record in step_records:
        validate_online_step_record(record)
    for record in final_records:
        validate_online_final_record(record)
    encoded_records = stable_json({"steps": step_records, "finals": final_records}).lower()
    assert "db_path" not in encoded_records
    assert "api_key" not in encoded_records
    assert "password" not in encoded_records


def test_goal03_each_task_can_create_isolated_online_session(package_dir):
    runtime = load_online_runtime(package_dir)
    runtime.start()
    try:
        session_ids = set()
        initial_hashes = set()
        for index in range(1, 6):
            session = runtime.reset(f"task-{index}", run_id=f"online-isolation-{index}")
            session_ids.add(session.session_id)
            initial_hashes.add(session.initial_snapshot_hash)
            observation = session.observe()
            assert observation.task_id == f"task-{index}"
            assert observation.done is False
    finally:
        runtime.close()

    assert len(session_ids) == 5
    assert len(initial_hashes) == 1


def test_goal03_package_manifest_runtime_and_grpo_adapter_refs(package_dir):
    required_refs = {
        "release/runtime-index.yaml",
        "release/surface-runtime-index.yaml",
        "checks/online-step-records.jsonl",
        "checks/online-final-records.jsonl",
        "training/grpo-prompt-dataset.jsonl",
        "training/grpo-adapter-index.yaml",
        "training/verl-adapter-config.yaml",
    }
    release_manifest = read_yaml(package_dir / "release" / "release-manifest.yaml")
    package_plan = read_yaml(package_dir / "package.yaml")
    consumer_index = read_yaml(package_dir / "release" / "consumer-index.yaml")

    assert required_refs.issubset(set(release_manifest["consumer_outputs"]))
    assert required_refs.issubset(set(package_plan["consumer_output_refs"]))
    for ref in required_refs:
        assert (package_dir / ref).exists(), ref

    assert release_manifest["runtime_refs"]["online_runtime_loader"] == "agent_world.online_runtime.load_online_runtime"
    assert release_manifest["runtime_refs"]["runtime_index_ref"] == "release/runtime-index.yaml"
    assert release_manifest["runtime_refs"]["grpo_adapter_index_ref"] == "training/grpo-adapter-index.yaml"
    assert consumer_index["runtime_index_ref"] == "release/runtime-index.yaml"
    assert consumer_index["online_step_records_ref"] == "checks/online-step-records.jsonl"

    runtime_index = read_yaml(package_dir / "release" / "runtime-index.yaml")
    surface_runtime_index = read_yaml(package_dir / "release" / "surface-runtime-index.yaml")
    validate_runtime_index(package_dir, runtime_index)
    validate_surface_runtime_index(package_dir, surface_runtime_index)
    assert runtime_index["reward"]["reward_source"] == "deterministic_verifier"
    assert {descriptor["kind"] for descriptor in surface_runtime_index["descriptors"]} == {
        "python_callable",
        "mcp_server",
        "runtime_control_cli",
        "environment_cli",
        "http_service",
    }

    adapter_index = read_yaml(package_dir / "training" / "grpo-adapter-index.yaml")
    verl_config = read_yaml(package_dir / "training" / "verl-adapter-config.yaml")
    validate_grpo_adapter_index(package_dir, adapter_index)
    validate_verl_adapter_config(verl_config)
    consumed = consume_runtime_contract(package_dir)
    assert consumed["status"] == "pass"
    assert consumed["reward_source"] == "deterministic_verifier"
    assert verl_config["framework"]["dependency_policy"] == "not_required"

    prompt_records = build_prompt_dataset(package_dir)
    assert len(prompt_records) == 5
    encoded_prompts = stable_json(prompt_records).lower()
    assert "dependency_path" not in encoded_prompts
    assert "verifier" not in encoded_prompts
    assert "sqlite" not in encoded_prompts
