from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_world.artifacts import read_yaml, stable_json, write_jsonl
from agent_world.fixtures.support_desk_lite import (
    SupportDeskLite,
    reset_environment,
    snapshot_hash,
    verify_task_completion,
)
from agent_world.fixtures.support_desk_lite_policy import POLICY_ID, execute_support_desk_lite_policy


FIXED_CREATED_AT = "2026-06-27T00:00:00Z"
DEFAULT_RUN_ID = "run-support-desk-lite-001"
REWARD_SOURCE = "deterministic_verifier"
SECRET_VALUE_MARKERS = ("api_key", "password", "bearer ", "secret-value-must-not-be-written")


@dataclass(frozen=True)
class RolloutEvalResult:
    package_dir: Path
    run_id: str
    policy_id: str
    rollout_records_path: Path
    reward_records_path: Path
    rollout_records: list[dict[str, Any]]
    reward_records: list[dict[str, Any]]


def run_release_rollouts(
    package_dir: Path,
    *,
    run_id: str = DEFAULT_RUN_ID,
    policy_id: str = POLICY_ID,
) -> RolloutEvalResult:
    """Run deterministic support-desk-lite rollouts from an assembled release package."""
    package_dir = Path(package_dir)
    release = read_yaml(package_dir / "release" / "release-manifest.yaml")
    if release["environment_id"] != "support-desk-lite":
        raise ValueError("Goal 02 rollout consumer only supports support-desk-lite")

    tasks_doc = read_yaml(package_dir / "spec" / "tasks.yaml")
    replay_plan = read_yaml(package_dir / "checks" / "replay-plan.yaml")
    tasks_by_id = {task["task_id"]: task for task in tasks_doc["tasks"]}
    task_ids = list(replay_plan["task_ids"])
    missing = [task_id for task_id in task_ids if task_id not in tasks_by_id]
    if missing:
        raise ValueError(f"Replay plan references unknown tasks: {missing}")

    seed = package_dir / "fixtures" / "seed" / "support-desk-lite.sqlite"
    if not seed.exists():
        raise FileNotFoundError(seed)

    run_dir = package_dir / "rollouts" / run_id
    if run_dir.exists():
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)

    rollout_records: list[dict[str, Any]] = []
    reward_records: list[dict[str, Any]] = []
    for task_id in task_ids:
        rollout, reward = _run_task_rollout(
            package_dir=package_dir,
            release=release,
            seed=seed,
            run_dir=run_dir,
            run_id=run_id,
            policy_id=policy_id,
            task=tasks_by_id[task_id],
        )
        validate_rollout_record(rollout)
        validate_reward_record(reward)
        rollout_records.append(rollout)
        reward_records.append(reward)

    rollout_records_path = package_dir / "checks" / "rollout-records.jsonl"
    reward_records_path = package_dir / "checks" / "reward-records.jsonl"
    write_jsonl(rollout_records_path, rollout_records)
    write_jsonl(reward_records_path, reward_records)
    write_jsonl(run_dir / "rollout-records.jsonl", rollout_records)
    write_jsonl(run_dir / "reward-records.jsonl", reward_records)
    return RolloutEvalResult(
        package_dir=package_dir,
        run_id=run_id,
        policy_id=policy_id,
        rollout_records_path=rollout_records_path,
        reward_records_path=reward_records_path,
        rollout_records=rollout_records,
        reward_records=reward_records,
    )


def validate_rollout_record(record: dict[str, Any]) -> None:
    required = [
        "record_id",
        "record_type",
        "environment_id",
        "release_id",
        "task_id",
        "run_id",
        "policy_id",
        "policy_kind",
        "natural_request",
        "initial_snapshot_hash",
        "final_snapshot_hash",
        "surface_trace_ref",
        "state_ref",
        "final_answer",
        "verifier_id",
        "verifier_result",
        "success",
        "dependency_path_expected",
        "dependency_path_observed",
        "tool_trace",
        "failure_class",
        "recovery_suggestion",
        "created_at",
    ]
    _require(record, required, "RolloutRecord")
    if record["record_type"] != "rollout_eval":
        raise ValueError("RolloutRecord.record_type must be rollout_eval")
    if not isinstance(record["success"], bool):
        raise ValueError("RolloutRecord.success must be boolean")
    if not isinstance(record["tool_trace"], list):
        raise ValueError("RolloutRecord.tool_trace must be a list")
    if Path(record["surface_trace_ref"]).is_absolute() or Path(record["state_ref"]).is_absolute():
        raise ValueError("RolloutRecord refs must be package-relative")
    for item in record["tool_trace"]:
        if "db_path" in item:
            raise ValueError("RolloutRecord.tool_trace must not expose runtime database paths")
    validate_no_secret_material(record)


def validate_reward_record(record: dict[str, Any]) -> None:
    required = [
        "record_id",
        "record_type",
        "environment_id",
        "release_id",
        "task_id",
        "run_id",
        "policy_id",
        "success",
        "reward",
        "reward_source",
        "verifier_id",
        "verifier_checks",
        "dependency_path_expected",
        "dependency_path_observed",
        "initial_snapshot_hash",
        "final_snapshot_hash",
        "surface_trace_ref",
        "rollout_record_ref",
        "failure_class",
        "recovery_suggestion",
        "created_at",
    ]
    _require(record, required, "RewardRecord")
    if record["record_type"] != "deterministic_reward_eval":
        raise ValueError("RewardRecord.record_type must be deterministic_reward_eval")
    if record["reward_source"] != REWARD_SOURCE:
        raise ValueError("RewardRecord.reward_source must be deterministic_verifier")
    expected_reward = 1.0 if record["success"] else 0.0
    if record["reward"] != expected_reward:
        raise ValueError("RewardRecord.reward must be derived from verifier success")
    if Path(record["surface_trace_ref"]).is_absolute():
        raise ValueError("RewardRecord.surface_trace_ref must be package-relative")
    validate_no_secret_material(record)


def validate_no_secret_material(record: dict[str, Any]) -> None:
    encoded = stable_json(record).lower()
    for marker in SECRET_VALUE_MARKERS:
        if marker in encoded:
            raise ValueError(f"Record contains secret marker: {marker}")


def _run_task_rollout(
    *,
    package_dir: Path,
    release: dict[str, Any],
    seed: Path,
    run_dir: Path,
    run_id: str,
    policy_id: str,
    task: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    task_id = task["task_id"]
    task_run_dir = run_dir / task_id
    final_db = reset_environment(seed, task_run_dir)
    trace_path = task_run_dir / "surface-trace.jsonl"
    call_group = f"{run_id}-{task_id}"
    initial_hash = snapshot_hash(final_db)
    surface = SupportDeskLite(final_db, trace_path=trace_path, task_id=task_id, call_group=call_group)
    final_answer = execute_support_desk_lite_policy(surface, task)
    final_hash = snapshot_hash(final_db)
    verifier_result = verify_task_completion(
        task_id,
        seed,
        final_db,
        final_answer=final_answer,
        surface_trace_path=trace_path,
        expected_dependency_path=task["dependency_path"],
        trace_call_group=call_group,
    )
    observed_path = _observed_dependency_path(trace_path, task_id, call_group)
    success = bool(verifier_result["success"])
    failure_class = "" if success else "deterministic_verifier_failed"
    recovery_suggestion = "" if success else "Inspect verifier_checks and surface_trace_ref for the failed deterministic assertion."
    verifier_id = task["verifier_refs"][0]
    rollout_record_ref = f"checks/rollout-records.jsonl#rollout-{run_id}-{task_id}"
    rollout = {
        "record_id": f"rollout-{run_id}-{task_id}",
        "record_type": "rollout_eval",
        "environment_id": release["environment_id"],
        "release_id": release["release_id"],
        "task_id": task_id,
        "run_id": run_id,
        "policy_id": policy_id,
        "policy_kind": "deterministic_scripted",
        "natural_request": task["natural_request"],
        "runtime_refs": release.get("runtime_refs", {}),
        "initial_snapshot_hash": initial_hash,
        "final_snapshot_hash": final_hash,
        "surface_trace_ref": _relative_ref(trace_path, package_dir),
        "state_ref": _relative_ref(final_db, package_dir),
        "final_answer": final_answer,
        "verifier_id": verifier_id,
        "verifier_result": verifier_result,
        "success": success,
        "dependency_path_expected": list(task["dependency_path"]),
        "dependency_path_observed": observed_path,
        "tool_trace": _tool_trace(trace_path, task_id, call_group),
        "failure_class": failure_class,
        "recovery_suggestion": recovery_suggestion,
        "created_at": FIXED_CREATED_AT,
    }
    reward = {
        "record_id": f"reward-{run_id}-{task_id}",
        "record_type": "deterministic_reward_eval",
        "environment_id": release["environment_id"],
        "release_id": release["release_id"],
        "task_id": task_id,
        "run_id": run_id,
        "policy_id": policy_id,
        "success": success,
        "reward": 1.0 if success else 0.0,
        "reward_source": REWARD_SOURCE,
        "verifier_id": verifier_id,
        "verifier_checks": verifier_result["checks"],
        "dependency_path_expected": list(task["dependency_path"]),
        "dependency_path_observed": observed_path,
        "initial_snapshot_hash": initial_hash,
        "final_snapshot_hash": final_hash,
        "surface_trace_ref": _relative_ref(trace_path, package_dir),
        "rollout_record_ref": rollout_record_ref,
        "failure_class": failure_class,
        "recovery_suggestion": recovery_suggestion,
        "created_at": FIXED_CREATED_AT,
    }
    return rollout, reward


def _tool_trace(trace_path: Path, task_id: str, call_group: str) -> list[dict[str, Any]]:
    trace: list[dict[str, Any]] = []
    if not trace_path.exists():
        return trace
    for line in trace_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        if record.get("task_id") != task_id or record.get("call_group") != call_group or "tool" not in record:
            continue
        trace.append(
            {
                "tool": record["tool"],
                "inputs": record.get("inputs", {}),
                "output_preview": record.get("output_preview", ""),
                "snapshot_hash": record.get("snapshot_hash", ""),
                "created_at": record.get("created_at", ""),
            }
        )
    return trace


def _observed_dependency_path(trace_path: Path, task_id: str, call_group: str) -> list[str]:
    return [record["tool"] for record in _tool_trace(trace_path, task_id, call_group)]


def _relative_ref(path: Path, package_dir: Path) -> str:
    return path.relative_to(package_dir).as_posix()


def _require(record: dict[str, Any], fields: list[str], label: str) -> None:
    missing = [field for field in fields if field not in record]
    if missing:
        raise ValueError(f"{label} missing required fields: {missing}")
