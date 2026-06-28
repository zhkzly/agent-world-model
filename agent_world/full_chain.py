from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_world.replay import replay_package
from agent_world.rollout import RolloutEvalResult, run_release_rollouts
from agent_world.training import DatasetOnlyAdapter, TrainingConsumerRecord, TrainingExportResult, export_training_dataset
from agent_world.workflow import FirstSliceWorkflow, WorkflowResult


@dataclass(frozen=True)
class SupportDeskLiteFullChainResult:
    workflow: WorkflowResult
    replay_results: list[dict[str, Any]]
    rollout: RolloutEvalResult
    training: TrainingExportResult
    consumer_record: TrainingConsumerRecord


def run_support_desk_lite_full_chain(output_dir: Path, *, env: dict[str, str] | None = None) -> SupportDeskLiteFullChainResult:
    workflow_env = {} if env is None else env
    workflow_result = FirstSliceWorkflow().run(output_dir=Path(output_dir), env=workflow_env)
    package_dir = workflow_result.package.package_dir
    replay_results = [replay_package(package_dir, task_id) for task_id in workflow_result.artifacts["ReleaseManifest"]["task_index"]]
    failures = [result for result in replay_results if not result["success"]]
    if failures:
        raise RuntimeError(f"Replay failed for tasks: {[result['task_id'] for result in failures]}")
    rollout_result = run_release_rollouts(package_dir)
    training_result = export_training_dataset(package_dir)
    consumer_record = DatasetOnlyAdapter().consume(package_dir)
    if consumer_record.status != "pass":
        raise RuntimeError(f"DatasetOnlyAdapter failed: {consumer_record.recovery_suggestion}")
    return SupportDeskLiteFullChainResult(
        workflow=workflow_result,
        replay_results=replay_results,
        rollout=rollout_result,
        training=training_result,
        consumer_record=consumer_record,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = run_support_desk_lite_full_chain(args.output)
    print(
        {
            "package_dir": str(result.workflow.package.package_dir),
            "replay_records": len(result.replay_results),
            "rollout_records": len(result.rollout.rollout_records),
            "reward_records": len(result.rollout.reward_records),
            "sft_records": len(result.training.sft_records),
            "consumer_status": result.consumer_record.status,
        }
    )


if __name__ == "__main__":
    main()
