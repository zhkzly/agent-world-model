from __future__ import annotations

import json
from pathlib import Path

from awmx.artifacts.schemas import RewardRecord, RunSpec, TaskSpec, TraceRecord, ValidationError


def export_rl_dataset(
    *,
    run_spec: RunSpec,
    task: TaskSpec,
    trace_path: Path,
    reward_path: Path,
    dataset_root: Path,
) -> Path:
    trace_rows = [
        TraceRecord.from_dict(json.loads(line))
        for line in Path(trace_path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    reward = RewardRecord.from_dict(json.loads(Path(reward_path).read_text(encoding="utf-8")))
    if run_spec.task_id != task.id:
        raise ValidationError("run_spec.task_id must match task.id for export")
    for trace in trace_rows:
        if trace.run_id != run_spec.id:
            raise ValidationError("trace.run_id must match run_spec.id for export")
    if reward.run_id != run_spec.id:
        raise ValidationError("reward.run_id must match run_spec.id for export")
    if reward.task_id != task.id:
        raise ValidationError("reward.task_id must match task.id for export")

    payload = {
        "run_id": run_spec.id,
        "task": task.to_dict(),
        "reward": reward.to_dict(),
        "trace": [row.to_dict() for row in trace_rows],
    }

    dataset_root = Path(dataset_root)
    dataset_root.mkdir(parents=True, exist_ok=True)
    export_path = dataset_root / f"{run_spec.id}.jsonl"
    with export_path.open("w", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=True, sort_keys=True))
        handle.write("\n")
    return export_path
