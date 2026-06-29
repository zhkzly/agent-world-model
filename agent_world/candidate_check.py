from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from agent_world.artifacts import stable_json
from agent_world.independent_verifier import verify_generated_bundle_independent
from agent_world.replay_contract import observation_from_independent_report


def check_generated_candidate(
    *,
    build_dir: Path,
    environment_id: str,
    accepted_tasks: list[dict[str, Any]] | None = None,
    runtime_entrypoint: str = "",
    verifier_entrypoint: str = "verifier.verify_task_completion",
    candidate_dir_ref: str = "generated",
) -> dict[str, Any]:
    """Run the framework-owned executable check over a generated candidate."""
    build_dir = Path(build_dir)
    independent = verify_generated_bundle_independent(
        environment_id,
        build_dir,
        accepted_tasks=accepted_tasks,
        runtime_entrypoint=runtime_entrypoint,
        verifier_entrypoint=verifier_entrypoint,
    )
    observation = independent.get("framework_check_observation")
    if not isinstance(observation, dict):
        observation = observation_from_independent_report(
            independent,
            candidate_dir=build_dir,
            candidate_dir_ref=candidate_dir_ref,
        )
    return {
        "check_id": "framework-generated-candidate-check",
        "success": observation.get("success") is True,
        "status": "pass" if observation.get("success") is True else "fail",
        "environment_id": environment_id,
        "candidate_dir_ref": candidate_dir_ref,
        "independent_verification_record": independent,
        "framework_check_observation": observation,
        "failure_class": "" if observation.get("success") is True else observation.get("failure_class", "framework_candidate_check_failed"),
        "recovery_suggestion": "" if observation.get("success") is True else observation.get("recovery_suggestion", "Repair generated runtime, verifier, seed, or check files and rerun framework candidate check."),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run framework-owned generated candidate check.")
    parser.add_argument("--environment-id", required=True)
    parser.add_argument("--candidate-dir", required=True)
    parser.add_argument("--runtime-entrypoint", default="")
    parser.add_argument("--verifier-entrypoint", default="verifier.verify_task_completion")
    parser.add_argument("--accepted-tasks-json", default="")
    args = parser.parse_args(argv)
    accepted_tasks = None
    if args.accepted_tasks_json:
        accepted_tasks = json.loads(Path(args.accepted_tasks_json).read_text(encoding="utf-8"))
        if not isinstance(accepted_tasks, list):
            raise SystemExit("--accepted-tasks-json must point to a JSON list")
    result = check_generated_candidate(
        build_dir=Path(args.candidate_dir),
        environment_id=args.environment_id,
        accepted_tasks=accepted_tasks,
        runtime_entrypoint=args.runtime_entrypoint,
        verifier_entrypoint=args.verifier_entrypoint,
    )
    print(stable_json(result))
    return 0 if result["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
