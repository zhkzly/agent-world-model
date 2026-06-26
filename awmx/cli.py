from __future__ import annotations

import argparse
import json
from pathlib import Path

from awmx.artifacts.schemas import RunSpec
from awmx.config import load_agent_world_config, load_workflow_config, resolve_config_path, resolve_runs_root
from awmx.harness.trace import EventLogger, create_run_directory
from awmx.workflow.runner import WorkflowDryRunRunner


def _cmd_validate_config(args: argparse.Namespace) -> int:
    config = load_agent_world_config(args.config)
    workflow_ref = config.get("defaults", {}).get("workflow")
    workflow_id = None
    if workflow_ref:
        workflow = load_workflow_config(resolve_config_path(config, args.config, workflow_ref))
        workflow_id = workflow.id

    print(
        json.dumps(
            {
                "status": "ok",
                "config_id": config["id"],
                "workflow_id": workflow_id,
            },
            sort_keys=True,
        )
    )
    return 0


def _cmd_workflow_dry_run(args: argparse.Namespace) -> int:
    workflow_path = Path(args.workflow)
    workflow = load_workflow_config(workflow_path)
    runner = WorkflowDryRunRunner()
    result = runner.run(workflow, workflow_path=workflow_path)
    print(
        json.dumps(
            {
                "status": "ok",
                "mode": "dry_run",
                "workflow_id": workflow.id,
                "run_id": result.run_id,
                "events_path": str(result.events_path),
            },
            sort_keys=True,
        )
    )
    return 0


def _cmd_create_run(args: argparse.Namespace) -> int:
    config = load_agent_world_config(args.config)
    run_spec = RunSpec(
        id=args.run_id,
        version="0.1.0",
        created_at=args.created_at,
        source={"kind": "cli", "uri": str(args.config)},
        metadata={"mode": "dry_run"},
        workflow_id=args.workflow_id,
        environment_id=args.environment_id,
        task_id=args.task_id,
        runner={"type": args.runner_type},
        budgets={},
    )

    run_dir = create_run_directory(resolve_runs_root(config, args.config), run_spec)
    EventLogger(run_dir.events_path).append(
        {
            "timestamp": args.created_at,
            "run_id": run_spec.id,
            "node_id": "foundation.create_run",
            "status": "planned",
            "detail": "run directory scaffolded",
        }
    )

    print(
        json.dumps(
            {
                "status": "ok",
                "run_id": run_spec.id,
                "run_dir": str(run_dir.path),
            },
            sort_keys=True,
        )
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AWMX - Agent World runtime extensions")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate-config", help="Validate an Agent World config")
    validate.add_argument("config", type=Path)
    validate.set_defaults(func=_cmd_validate_config)

    workflow_dry_run = subparsers.add_parser(
        "workflow-dry-run",
        help="Validate and dry-run a workflow DAG without executing nodes",
    )
    workflow_dry_run.add_argument("workflow", type=Path)
    workflow_dry_run.set_defaults(func=_cmd_workflow_dry_run)

    create_run = subparsers.add_parser("create-run", help="Create a dry-run scaffold under outputs/agent_world/runs")
    create_run.add_argument("config", type=Path)
    create_run.add_argument("--run-id", required=True)
    create_run.add_argument("--workflow-id", required=True)
    create_run.add_argument("--environment-id", required=True)
    create_run.add_argument("--task-id", required=True)
    create_run.add_argument("--runner-type", default="scripted")
    create_run.add_argument("--created-at", default="2026-06-27T00:00:00Z")
    create_run.set_defaults(func=_cmd_create_run)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    raise SystemExit(args.func(args))


if __name__ == "__main__":
    main()
