from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol

from agent_world.artifacts import read_yaml, stable_json, write_jsonl, write_yaml
from agent_world.rollout import (
    DEFAULT_RUN_ID,
    FIXED_CREATED_AT,
    REWARD_SOURCE,
    validate_no_secret_material,
    validate_reward_record,
    validate_rollout_record,
)


@dataclass(frozen=True)
class TrainingConsumerRecord:
    adapter_id: str
    adapter_kind: str
    dataset_manifest_ref: str
    environment_id: str
    release_id: str
    consumed_record_counts: dict[str, int]
    status: str
    failure_class: str = ""
    recovery_suggestion: str = ""
    created_at: str = FIXED_CREATED_AT

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TrainingExportResult:
    package_dir: Path
    dataset_manifest_path: Path
    adapter_index_path: Path
    rollout_records_path: Path
    reward_records_path: Path
    sft_records_path: Path
    dataset_manifest: dict[str, Any]
    sft_records: list[dict[str, Any]]


class TrainerAdapter(Protocol):
    adapter_id: str
    adapter_kind: str

    def consume(
        self,
        package_dir: Path,
        *,
        dataset_manifest_ref: str = "training/dataset-manifest.yaml",
    ) -> TrainingConsumerRecord:
        ...


class DatasetOnlyAdapter:
    adapter_id = "dataset-only"
    adapter_kind = "dataset_only"

    def consume(
        self,
        package_dir: Path,
        *,
        dataset_manifest_ref: str = "training/dataset-manifest.yaml",
    ) -> TrainingConsumerRecord:
        package_dir = Path(package_dir)
        try:
            manifest = read_yaml(package_dir / dataset_manifest_ref)
            counts = validate_dataset_manifest(package_dir, manifest)
            return TrainingConsumerRecord(
                adapter_id=self.adapter_id,
                adapter_kind=self.adapter_kind,
                dataset_manifest_ref=dataset_manifest_ref,
                environment_id=manifest["environment_id"],
                release_id=manifest["release_id"],
                consumed_record_counts=counts,
                status="pass",
            )
        except Exception as exc:
            return TrainingConsumerRecord(
                adapter_id=self.adapter_id,
                adapter_kind=self.adapter_kind,
                dataset_manifest_ref=dataset_manifest_ref,
                environment_id="",
                release_id="",
                consumed_record_counts={},
                status="fail",
                failure_class=exc.__class__.__name__,
                recovery_suggestion=str(exc),
            )


class NoopTrainerAdapter:
    adapter_id = "noop"
    adapter_kind = "noop"

    def consume(
        self,
        package_dir: Path,
        *,
        dataset_manifest_ref: str = "training/dataset-manifest.yaml",
    ) -> TrainingConsumerRecord:
        package_dir = Path(package_dir)
        manifest = read_yaml(package_dir / dataset_manifest_ref)
        counts = dict(manifest.get("record_counts", {}))
        return TrainingConsumerRecord(
            adapter_id=self.adapter_id,
            adapter_kind=self.adapter_kind,
            dataset_manifest_ref=dataset_manifest_ref,
            environment_id=manifest.get("environment_id", ""),
            release_id=manifest.get("release_id", ""),
            consumed_record_counts={key: int(value) for key, value in counts.items()},
            status="pass",
        )


def export_training_dataset(
    package_dir: Path,
    *,
    run_id: str = DEFAULT_RUN_ID,
) -> TrainingExportResult:
    package_dir = Path(package_dir)
    release = read_yaml(package_dir / "release" / "release-manifest.yaml")
    tasks = {task["task_id"]: task for task in read_yaml(package_dir / "spec" / "tasks.yaml")["tasks"]}
    rollout_records = read_jsonl(package_dir / "checks" / "rollout-records.jsonl")
    reward_records = read_jsonl(package_dir / "checks" / "reward-records.jsonl")
    if not rollout_records or not reward_records:
        raise ValueError("Rollout and reward records must be produced before training export")
    for record in rollout_records:
        validate_rollout_record(record)
    for record in reward_records:
        validate_reward_record(record)

    rewards_by_task = {record["task_id"]: record for record in reward_records}
    sft_records = [
        _sft_record(release=release, task=tasks[rollout["task_id"]], rollout=rollout, reward=rewards_by_task[rollout["task_id"]])
        for rollout in rollout_records
    ]
    for record in sft_records:
        validate_sft_record(record)

    training_dir = package_dir / "training"
    training_dir.mkdir(parents=True, exist_ok=True)
    rollout_records_path = training_dir / "rollout-records.jsonl"
    reward_records_path = training_dir / "reward-records.jsonl"
    sft_records_path = training_dir / "sft-records.jsonl"
    write_jsonl(rollout_records_path, rollout_records)
    write_jsonl(reward_records_path, reward_records)
    write_jsonl(sft_records_path, sft_records)

    counts = {
        "rollout_records": len(rollout_records),
        "reward_records": len(reward_records),
        "sft_records": len(sft_records),
    }
    dataset_manifest = dataset_manifest_for_release(release=release, run_id=run_id, record_counts=counts, status="ready")
    adapter_index = adapter_index_for_release(release=release, status="ready")
    training_consumer_index = training_consumer_index_for_release(release=release, record_counts=counts, status="ready")
    dataset_manifest_path = training_dir / "dataset-manifest.yaml"
    adapter_index_path = training_dir / "adapter-index.yaml"
    write_yaml(dataset_manifest_path, dataset_manifest)
    write_yaml(adapter_index_path, adapter_index)
    write_yaml(package_dir / "release" / "training-consumer-index.yaml", training_consumer_index)
    validate_dataset_manifest(package_dir, dataset_manifest)
    return TrainingExportResult(
        package_dir=package_dir,
        dataset_manifest_path=dataset_manifest_path,
        adapter_index_path=adapter_index_path,
        rollout_records_path=rollout_records_path,
        reward_records_path=reward_records_path,
        sft_records_path=sft_records_path,
        dataset_manifest=dataset_manifest,
        sft_records=sft_records,
    )


def dataset_manifest_for_release(
    *,
    release: dict[str, Any] | None = None,
    run_id: str = DEFAULT_RUN_ID,
    record_counts: dict[str, int] | None = None,
    status: str = "pending_rollout_export",
) -> dict[str, Any]:
    release = release or {"environment_id": "support-desk-lite", "release_id": "release-support-desk-lite"}
    counts = record_counts or {"rollout_records": 0, "reward_records": 0, "sft_records": 0}
    return {
        "dataset_manifest_id": f"dataset-{release['environment_id']}-{run_id}",
        "environment_id": release["environment_id"],
        "release_id": release["release_id"],
        "run_id": run_id,
        "status": status,
        "created_at": FIXED_CREATED_AT,
        "source_records": {
            "rollout_records_ref": "checks/rollout-records.jsonl",
            "reward_records_ref": "checks/reward-records.jsonl",
        },
        "records": {
            "rollout_records_ref": "training/rollout-records.jsonl",
            "reward_records_ref": "training/reward-records.jsonl",
            "sft_records_ref": "training/sft-records.jsonl",
        },
        "record_counts": counts,
        "reward_source": REWARD_SOURCE,
        "adapter_index_ref": "training/adapter-index.yaml",
        "record_schema": {
            "sft": {
                "environment_id": "string",
                "task_id": "string",
                "messages": "array",
                "tool_trace": "array",
                "reward": "number",
                "verifier_result": "object",
            }
        },
        "secret_policy": "Records store package-relative refs and no credential values.",
    }


def adapter_index_for_release(*, release: dict[str, Any] | None = None, status: str = "pending_rollout_export") -> dict[str, Any]:
    release = release or {"environment_id": "support-desk-lite", "release_id": "release-support-desk-lite"}
    return {
        "adapter_index_id": f"adapter-index-{release['environment_id']}",
        "environment_id": release["environment_id"],
        "release_id": release["release_id"],
        "status": status,
        "dataset_manifest_ref": "training/dataset-manifest.yaml",
        "adapters": [
            {
                "adapter_id": DatasetOnlyAdapter.adapter_id,
                "adapter_kind": DatasetOnlyAdapter.adapter_kind,
                "consumer_module": "agent_world.training",
                "consumer_class": "DatasetOnlyAdapter",
                "status": "implemented",
            },
            {
                "adapter_id": NoopTrainerAdapter.adapter_id,
                "adapter_kind": NoopTrainerAdapter.adapter_kind,
                "consumer_module": "agent_world.training",
                "consumer_class": "NoopTrainerAdapter",
                "status": "implemented",
            },
        ],
        "framework_mappings": [
            {"framework": "verl", "status": "described_not_implemented", "notes": "Future adapter may map sft/reward records externally."},
            {"framework": "LLaMA-Factory", "status": "described_not_implemented", "notes": "Future adapter may map messages externally."},
            {"framework": "OpenRLHF", "status": "described_not_implemented", "notes": "Future adapter may map reward records externally."},
            {"framework": "TRL", "status": "described_not_implemented", "notes": "Future adapter may map dataset records externally."},
        ],
    }


def training_consumer_index_for_release(
    *,
    release: dict[str, Any] | None = None,
    record_counts: dict[str, int] | None = None,
    status: str = "pending_rollout_export",
) -> dict[str, Any]:
    release = release or {"environment_id": "support-desk-lite", "release_id": "release-support-desk-lite"}
    return {
        "training_consumer_index_id": f"training-consumer-{release['environment_id']}",
        "environment_id": release["environment_id"],
        "release_id": release["release_id"],
        "status": status,
        "dataset_manifest_ref": "training/dataset-manifest.yaml",
        "adapter_index_ref": "training/adapter-index.yaml",
        "rollout_records_ref": "checks/rollout-records.jsonl",
        "reward_records_ref": "checks/reward-records.jsonl",
        "training_records_ref": "training/sft-records.jsonl",
        "record_counts": record_counts or {"rollout_records": 0, "reward_records": 0, "sft_records": 0},
        "adapter_notes": "DatasetOnlyAdapter and NoopTrainerAdapter consume exported records without binding a training framework.",
    }


def validate_dataset_manifest(package_dir: Path, manifest: dict[str, Any]) -> dict[str, int]:
    required = [
        "dataset_manifest_id",
        "environment_id",
        "release_id",
        "run_id",
        "source_records",
        "records",
        "record_counts",
        "reward_source",
        "adapter_index_ref",
    ]
    _require(manifest, required, "DatasetManifest")
    if manifest["reward_source"] != REWARD_SOURCE:
        raise ValueError("DatasetManifest.reward_source must be deterministic_verifier")
    refs = manifest["source_records"] | manifest["records"] | {"adapter_index_ref": manifest["adapter_index_ref"]}
    for ref in refs.values():
        if Path(ref).is_absolute():
            raise ValueError("DatasetManifest refs must be package-relative")
        if not (Path(package_dir) / ref).exists():
            raise FileNotFoundError(Path(package_dir) / ref)
    rollout_records = read_jsonl(Path(package_dir) / manifest["records"]["rollout_records_ref"])
    reward_records = read_jsonl(Path(package_dir) / manifest["records"]["reward_records_ref"])
    sft_records = read_jsonl(Path(package_dir) / manifest["records"]["sft_records_ref"])
    for record in rollout_records:
        validate_rollout_record(record)
    for record in reward_records:
        validate_reward_record(record)
    for record in sft_records:
        validate_sft_record(record)
    actual_counts = {
        "rollout_records": len(rollout_records),
        "reward_records": len(reward_records),
        "sft_records": len(sft_records),
    }
    if actual_counts != manifest["record_counts"]:
        raise ValueError(f"DatasetManifest counts do not match exported records: {actual_counts} != {manifest['record_counts']}")
    validate_no_secret_material(manifest)
    return actual_counts


def validate_sft_record(record: dict[str, Any]) -> None:
    required = [
        "record_id",
        "environment_id",
        "release_id",
        "task_id",
        "run_id",
        "messages",
        "tool_trace",
        "reward",
        "reward_source",
        "verifier_result",
        "created_at",
    ]
    _require(record, required, "SftRecord")
    if record["reward_source"] != REWARD_SOURCE:
        raise ValueError("SftRecord.reward_source must be deterministic_verifier")
    roles = [message.get("role") for message in record["messages"]]
    if roles != ["user", "assistant"]:
        raise ValueError("SftRecord.messages must contain user then assistant")
    validate_no_secret_material(record)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(path)
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _sft_record(
    *,
    release: dict[str, Any],
    task: dict[str, Any],
    rollout: dict[str, Any],
    reward: dict[str, Any],
) -> dict[str, Any]:
    assistant_payload = {
        "final_answer": rollout["final_answer"],
        "dependency_path_observed": rollout["dependency_path_observed"],
        "verifier_success": rollout["success"],
    }
    record = {
        "record_id": f"sft-{rollout['run_id']}-{rollout['task_id']}",
        "environment_id": release["environment_id"],
        "release_id": release["release_id"],
        "task_id": rollout["task_id"],
        "run_id": rollout["run_id"],
        "messages": [
            {"role": "user", "content": task["natural_request"]},
            {"role": "assistant", "content": stable_json(assistant_payload)},
        ],
        "tool_trace": rollout["tool_trace"],
        "reward": reward["reward"],
        "reward_source": reward["reward_source"],
        "verifier_result": {"success": reward["success"], "checks": reward["verifier_checks"]},
        "created_at": FIXED_CREATED_AT,
    }
    return record


def _require(record: dict[str, Any], fields: list[str], label: str) -> None:
    missing = [field for field in fields if field not in record]
    if missing:
        raise ValueError(f"{label} missing required fields: {missing}")
