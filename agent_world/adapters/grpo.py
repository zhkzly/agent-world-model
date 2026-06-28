from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from agent_world.artifacts import read_yaml, stable_json, write_jsonl, write_yaml
from agent_world.online_runtime import (
    ONLINE_RUNTIME_CONTRACT_VERSION,
    validate_runtime_index,
    validate_surface_runtime_index,
)
from agent_world.rollout import FIXED_CREATED_AT, REWARD_SOURCE, validate_no_secret_material
from agent_world.training import read_jsonl


@dataclass(frozen=True)
class GrpoAdapterConfig:
    adapter_id: str
    adapter_kind: str
    runtime_index_ref: str
    surface_runtime_index_ref: str
    prompt_dataset_ref: str
    reward_bridge_config_ref: str
    online_step_records_ref: str
    online_final_records_ref: str
    status: str = "metadata_only"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class VerlAdapterExport:
    config_ref: str
    adapter_kind: str
    dependency_policy: str
    reward_source: str
    status: str = "metadata_only"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class GrpoAdapterExportResult:
    package_dir: Path
    prompt_dataset_path: Path
    adapter_index_path: Path
    verl_adapter_config_path: Path
    prompt_records: list[dict[str, Any]]
    adapter_index: dict[str, Any]
    verl_adapter_config: dict[str, Any]


def build_prompt_dataset(package_dir: Path) -> list[dict[str, Any]]:
    package_dir = Path(package_dir)
    release = read_yaml(package_dir / "release" / "release-manifest.yaml")
    tasks = read_yaml(package_dir / "spec" / "tasks.yaml")["tasks"]
    records = []
    for task in tasks:
        record = {
            "record_id": f"grpo-prompt-{task['task_id']}",
            "record_type": "grpo_prompt",
            "environment_id": release["environment_id"],
            "release_id": release["release_id"],
            "task_id": task["task_id"],
            "messages": [{"role": "user", "content": task["natural_request"]}],
            "available_tools": list(task["allowed_logical_tool_ids"]),
            "runtime_contract_ref": "release/runtime-index.yaml",
            "surface_runtime_index_ref": "release/surface-runtime-index.yaml",
            "reward_bridge_config_ref": "training/verl-adapter-config.yaml",
            "metadata": {
                "target_capability": task["target_capability"],
                "difficulty": {
                    "level": task["difficulty"].get("level", ""),
                    "requires_state_change": bool(task["difficulty"].get("requires_state_change")),
                },
            },
            "created_at": FIXED_CREATED_AT,
        }
        validate_prompt_record(record)
        records.append(record)
    return records


def build_reward_bridge_config(package_dir: Path) -> dict[str, Any]:
    package_dir = Path(package_dir)
    release = read_yaml(package_dir / "release" / "release-manifest.yaml")
    runtime_index = read_yaml(package_dir / "release" / "runtime-index.yaml")
    surface_runtime_index = read_yaml(package_dir / "release" / "surface-runtime-index.yaml")
    validate_runtime_index(package_dir, runtime_index)
    validate_surface_runtime_index(package_dir, surface_runtime_index)
    config = {
        "verl_adapter_config_id": f"verl-adapter-{release['environment_id']}",
        "adapter_kind": "grpo_verl_bridge_skeleton",
        "status": "metadata_only",
        "environment_id": release["environment_id"],
        "release_id": release["release_id"],
        "runtime_contract_version": ONLINE_RUNTIME_CONTRACT_VERSION,
        "runtime": {
            "loader": runtime_index["runtime_loader"],
            "runtime_index_ref": "release/runtime-index.yaml",
            "surface_runtime_index_ref": "release/surface-runtime-index.yaml",
            "lifecycle": list(runtime_index["lifecycle"]),
        },
        "prompt_dataset_ref": "training/grpo-prompt-dataset.jsonl",
        "action_mapping": {
            "runtime_action_class": "agent_world.online_runtime.RuntimeAction",
            "accepted_action_kinds": ["tool_call", "final_answer", "noop"],
            "tool_name_source": "surface exposure name from RuntimeObservation.available_tools",
            "arguments_source": "policy-produced JSON object",
        },
        "reward_mapping": {
            "reward_source": REWARD_SOURCE,
            "success_reward": 1.0,
            "failure_reward": 0.0,
            "final_result_field": "RuntimeFinalResult.reward",
            "verifier_result_field": "RuntimeFinalResult.verifier_result",
        },
        "record_writes": {
            "online_step_records_ref": "checks/online-step-records.jsonl",
            "online_final_records_ref": "checks/online-final-records.jsonl",
            "run_records_dir": "online_rollouts/",
        },
        "framework": {
            "name": "verl",
            "dependency_policy": "not_required",
            "integration_status": "skeleton_metadata_only",
        },
        "known_limits": [
            "This export does not import or configure real verl workers.",
            "No Ray, vLLM, SGLang, or GPU trainer runtime is started.",
            "A future optional adapter can translate this metadata into a trainer-specific tool contract.",
        ],
        "created_at": FIXED_CREATED_AT,
    }
    validate_verl_adapter_config(config)
    return config


def consume_runtime_contract(package_dir: Path) -> dict[str, Any]:
    package_dir = Path(package_dir)
    runtime_index = read_yaml(package_dir / "release" / "runtime-index.yaml")
    surface_runtime_index = read_yaml(package_dir / "release" / "surface-runtime-index.yaml")
    validate_runtime_index(package_dir, runtime_index)
    validate_surface_runtime_index(package_dir, surface_runtime_index)
    return {
        "status": "pass",
        "environment_id": runtime_index["environment_id"],
        "release_id": runtime_index["release_id"],
        "runtime_index_ref": "release/runtime-index.yaml",
        "surface_runtime_index_ref": "release/surface-runtime-index.yaml",
        "runtime_loader": runtime_index["runtime_loader"],
        "lifecycle": list(runtime_index["lifecycle"]),
        "reward_source": runtime_index["reward"]["reward_source"],
    }


def export_grpo_adapter_metadata(package_dir: Path) -> GrpoAdapterExportResult:
    package_dir = Path(package_dir)
    release = read_yaml(package_dir / "release" / "release-manifest.yaml")
    consume_runtime_contract(package_dir)
    prompt_records = build_prompt_dataset(package_dir)
    adapter_index = grpo_adapter_index_for_release(
        release=release,
        prompt_record_count=len(prompt_records),
        status="ready",
    )
    verl_config = build_reward_bridge_config(package_dir)
    training_dir = package_dir / "training"
    training_dir.mkdir(parents=True, exist_ok=True)
    prompt_dataset_path = training_dir / "grpo-prompt-dataset.jsonl"
    adapter_index_path = training_dir / "grpo-adapter-index.yaml"
    verl_adapter_config_path = training_dir / "verl-adapter-config.yaml"
    write_jsonl(prompt_dataset_path, prompt_records)
    write_yaml(adapter_index_path, adapter_index)
    write_yaml(verl_adapter_config_path, verl_config)
    validate_grpo_adapter_index(package_dir, adapter_index)
    validate_verl_adapter_config(verl_config)
    return GrpoAdapterExportResult(
        package_dir=package_dir,
        prompt_dataset_path=prompt_dataset_path,
        adapter_index_path=adapter_index_path,
        verl_adapter_config_path=verl_adapter_config_path,
        prompt_records=prompt_records,
        adapter_index=adapter_index,
        verl_adapter_config=verl_config,
    )


def grpo_adapter_index_for_release(
    *,
    release: dict[str, Any] | None = None,
    prompt_record_count: int = 0,
    status: str = "pending_runtime_rollout",
) -> dict[str, Any]:
    release = release or {"environment_id": "support-desk-lite", "release_id": "release-support-desk-lite"}
    return {
        "grpo_adapter_index_id": f"grpo-adapter-{release['environment_id']}",
        "environment_id": release["environment_id"],
        "release_id": release["release_id"],
        "status": status,
        "adapter": GrpoAdapterConfig(
            adapter_id="grpo-runtime-bridge",
            adapter_kind="grpo_runtime_bridge_skeleton",
            runtime_index_ref="release/runtime-index.yaml",
            surface_runtime_index_ref="release/surface-runtime-index.yaml",
            prompt_dataset_ref="training/grpo-prompt-dataset.jsonl",
            reward_bridge_config_ref="training/verl-adapter-config.yaml",
            online_step_records_ref="checks/online-step-records.jsonl",
            online_final_records_ref="checks/online-final-records.jsonl",
            status=status,
        ).to_dict(),
        "exports": {
            "prompt_dataset_ref": "training/grpo-prompt-dataset.jsonl",
            "reward_bridge_config_ref": "training/verl-adapter-config.yaml",
            "runtime_index_ref": "release/runtime-index.yaml",
            "surface_runtime_index_ref": "release/surface-runtime-index.yaml",
            "online_step_records_ref": "checks/online-step-records.jsonl",
            "online_final_records_ref": "checks/online-final-records.jsonl",
        },
        "record_counts": {"prompt_records": prompt_record_count},
        "adapter_functions": {
            "build_prompt_dataset": "agent_world.adapters.grpo.build_prompt_dataset",
            "build_reward_bridge_config": "agent_world.adapters.grpo.build_reward_bridge_config",
            "consume_runtime_contract": "agent_world.adapters.grpo.consume_runtime_contract",
        },
        "framework_mappings": [
            {
                "framework": "verl",
                "status": "metadata_only_no_dependency",
                "config_ref": "training/verl-adapter-config.yaml",
            }
        ],
        "created_at": FIXED_CREATED_AT,
    }


def verl_adapter_config_for_release(*, release: dict[str, Any] | None = None) -> dict[str, Any]:
    release = release or {"environment_id": "support-desk-lite", "release_id": "release-support-desk-lite"}
    return {
        "verl_adapter_config_id": f"verl-adapter-{release['environment_id']}",
        "adapter_kind": "grpo_verl_bridge_skeleton",
        "status": "pending_runtime_contract",
        "environment_id": release["environment_id"],
        "release_id": release["release_id"],
        "runtime_contract_version": ONLINE_RUNTIME_CONTRACT_VERSION,
        "runtime": {
            "loader": "agent_world.online_runtime.load_online_runtime",
            "runtime_index_ref": "release/runtime-index.yaml",
            "surface_runtime_index_ref": "release/surface-runtime-index.yaml",
            "lifecycle": ["start", "reset", "observe", "step", "finalize", "close"],
        },
        "prompt_dataset_ref": "training/grpo-prompt-dataset.jsonl",
        "action_mapping": {
            "runtime_action_class": "agent_world.online_runtime.RuntimeAction",
            "accepted_action_kinds": ["tool_call", "final_answer", "noop"],
            "tool_name_source": "surface exposure name from RuntimeObservation.available_tools",
            "arguments_source": "policy-produced JSON object",
        },
        "reward_mapping": {
            "reward_source": REWARD_SOURCE,
            "success_reward": 1.0,
            "failure_reward": 0.0,
            "final_result_field": "RuntimeFinalResult.reward",
            "verifier_result_field": "RuntimeFinalResult.verifier_result",
        },
        "record_writes": {
            "online_step_records_ref": "checks/online-step-records.jsonl",
            "online_final_records_ref": "checks/online-final-records.jsonl",
            "run_records_dir": "online_rollouts/",
        },
        "framework": {
            "name": "verl",
            "dependency_policy": "not_required",
            "integration_status": "skeleton_metadata_only",
        },
        "known_limits": [
            "This export does not import or configure real verl workers.",
            "No Ray, vLLM, SGLang, or GPU trainer runtime is started.",
        ],
        "created_at": FIXED_CREATED_AT,
    }


def validate_prompt_record(record: dict[str, Any]) -> None:
    _require(
        record,
        [
            "record_id",
            "record_type",
            "environment_id",
            "release_id",
            "task_id",
            "messages",
            "available_tools",
            "runtime_contract_ref",
            "surface_runtime_index_ref",
            "reward_bridge_config_ref",
            "metadata",
            "created_at",
        ],
        "GrpoPromptRecord",
    )
    if record["record_type"] != "grpo_prompt":
        raise ValueError("GrpoPromptRecord.record_type must be grpo_prompt")
    if [message.get("role") for message in record["messages"]] != ["user"]:
        raise ValueError("GrpoPromptRecord.messages must contain one user message")
    encoded = stable_json(record).lower()
    for forbidden in ["dependency_path", "verifier", "backend", "sqlite"]:
        if forbidden in encoded:
            raise ValueError(f"GrpoPromptRecord leaks implementation detail: {forbidden}")
    validate_no_secret_material(record)


def validate_grpo_adapter_index(package_dir: Path, index: dict[str, Any]) -> None:
    _require(
        index,
        [
            "grpo_adapter_index_id",
            "environment_id",
            "release_id",
            "status",
            "adapter",
            "exports",
            "record_counts",
            "adapter_functions",
            "framework_mappings",
            "created_at",
        ],
        "GrpoAdapterIndex",
    )
    refs = dict(index["exports"])
    for ref in refs.values():
        _validate_package_ref(package_dir, ref)
    records = read_jsonl(Path(package_dir) / index["exports"]["prompt_dataset_ref"])
    for record in records:
        validate_prompt_record(record)
    if len(records) != index["record_counts"]["prompt_records"]:
        raise ValueError("GrpoAdapterIndex prompt record count does not match dataset")
    validate_no_secret_material(index)


def validate_verl_adapter_config(config: dict[str, Any]) -> None:
    _require(
        config,
        [
            "verl_adapter_config_id",
            "adapter_kind",
            "status",
            "environment_id",
            "release_id",
            "runtime",
            "prompt_dataset_ref",
            "action_mapping",
            "reward_mapping",
            "record_writes",
            "framework",
            "known_limits",
            "created_at",
        ],
        "VerlAdapterConfig",
    )
    if config["reward_mapping"]["reward_source"] != REWARD_SOURCE:
        raise ValueError("VerlAdapterConfig reward source must be deterministic verifier")
    if config["framework"]["dependency_policy"] != "not_required":
        raise ValueError("VerlAdapterConfig must not require verl as a core dependency")
    validate_no_secret_material(config)


def _validate_package_ref(package_dir: Path, ref: str) -> None:
    if Path(ref).is_absolute():
        raise ValueError(f"Adapter ref must be package-relative: {ref}")
    if not (Path(package_dir) / ref).exists():
        raise FileNotFoundError(Path(package_dir) / ref)


def _require(record: dict[str, Any], fields: list[str], label: str) -> None:
    missing = [field for field in fields if field not in record]
    if missing:
        raise ValueError(f"{label} missing required fields: {missing}")
