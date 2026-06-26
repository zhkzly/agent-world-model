from __future__ import annotations

import argparse
import json
from pathlib import Path

from awmx.config import load_agent_world_config, load_workflow_config


def _cmd_validate_config(args: argparse.Namespace) -> int:
    config = load_agent_world_config(args.config)
    workflow_ref = config.get("defaults", {}).get("workflow")
    workflow_id = None
    if workflow_ref:
        workflow = load_workflow_config(Path(workflow_ref))
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AWMX - Agent World runtime extensions")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate-config", help="Validate an Agent World config")
    validate.add_argument("config", type=Path)
    validate.set_defaults(func=_cmd_validate_config)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    raise SystemExit(args.func(args))


if __name__ == "__main__":
    main()
