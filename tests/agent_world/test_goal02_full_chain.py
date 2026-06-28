from agent_world.artifacts import read_yaml, stable_json
from agent_world.full_chain import run_support_desk_lite_full_chain
from agent_world.training import DatasetOnlyAdapter, NoopTrainerAdapter, read_jsonl, validate_dataset_manifest


def test_goal02_support_desk_lite_full_chain_outputs_and_dataset_consumer(tmp_path):
    result = run_support_desk_lite_full_chain(tmp_path / "envpkg")
    package_dir = result.workflow.package.package_dir

    rollout_records = read_jsonl(package_dir / "checks" / "rollout-records.jsonl")
    reward_records = read_jsonl(package_dir / "checks" / "reward-records.jsonl")
    sft_records = read_jsonl(package_dir / "training" / "sft-records.jsonl")

    assert len(result.replay_results) == 5
    assert all(record["success"] is True for record in result.replay_results)
    assert len(rollout_records) == 5
    assert len(reward_records) == 5
    assert len(sft_records) == 5
    assert {record["task_id"] for record in rollout_records} == {f"task-{index}" for index in range(1, 6)}
    assert all(record["success"] is True for record in rollout_records)
    assert all(record["verifier_result"]["success"] is True for record in rollout_records)
    assert all(record["reward_source"] == "deterministic_verifier" for record in reward_records)
    assert all(record["reward"] == 1.0 for record in reward_records)
    assert all(record["dependency_path_expected"] == record["dependency_path_observed"] for record in reward_records)
    assert all(record["reward_source"] == "deterministic_verifier" for record in sft_records)

    manifest = read_yaml(package_dir / "training" / "dataset-manifest.yaml")
    counts = validate_dataset_manifest(package_dir, manifest)
    assert counts == {"rollout_records": 5, "reward_records": 5, "sft_records": 5}
    assert manifest["record_counts"] == counts

    consumer_record = DatasetOnlyAdapter().consume(package_dir)
    assert consumer_record.status == "pass"
    assert consumer_record.consumed_record_counts == counts
    noop_record = NoopTrainerAdapter().consume(package_dir)
    assert noop_record.status == "pass"
    assert noop_record.consumed_record_counts == counts

    release_manifest = read_yaml(package_dir / "release" / "release-manifest.yaml")
    package_plan = read_yaml(package_dir / "package.yaml")
    required_refs = {
        "checks/rollout-records.jsonl",
        "checks/reward-records.jsonl",
        "training/dataset-manifest.yaml",
        "training/rollout-records.jsonl",
        "training/reward-records.jsonl",
        "training/sft-records.jsonl",
        "training/adapter-index.yaml",
        "release/training-consumer-index.yaml",
        "release/runtime-index.yaml",
        "release/surface-runtime-index.yaml",
        "checks/online-step-records.jsonl",
        "checks/online-final-records.jsonl",
        "training/grpo-prompt-dataset.jsonl",
        "training/grpo-adapter-index.yaml",
        "training/verl-adapter-config.yaml",
    }
    assert required_refs.issubset(set(release_manifest["consumer_outputs"]))
    assert required_refs.issubset(set(package_plan["consumer_output_refs"]))
    for ref in required_refs:
        assert (package_dir / ref).exists(), ref
    assert release_manifest["runtime_refs"]["verifier_function"] == "agent_world.fixtures.support_desk_lite.verify_task_completion"

    training_index = read_yaml(package_dir / "release" / "training-consumer-index.yaml")
    assert training_index["record_counts"] == counts
    assert training_index["dataset_manifest_ref"] == "training/dataset-manifest.yaml"

    exported_payload = stable_json({"rollouts": rollout_records, "rewards": reward_records, "sft": sft_records}).lower()
    assert "api_key" not in exported_payload
    assert "password" not in exported_payload
    assert "bearer " not in exported_payload
