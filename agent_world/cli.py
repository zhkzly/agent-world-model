"""Small public entry point for the Direct-only Foundry."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from agent_world import __version__
from agent_world.config import ConfigurationError
from agent_world.foundry import check_config, generate
from agent_world.observe import ObserveError, observe_run


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agent-world",
        description="Clean-break Direct environment foundry.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)

    make = commands.add_parser("generate", help="run one Direct environment request")
    make.add_argument("--config", type=Path, required=True)
    make.add_argument("--need", required=True)
    make.add_argument("--resume", dest="resume_run_id", help="resume an existing run by run_id")
    make.add_argument(
        "--from",
        dest="restart_from",
        help="re-run starting at this node (requires --resume)",
    )

    scene = commands.add_parser("observe", help="read one safe run scene")
    scene.add_argument("--config", type=Path, required=True)
    scene.add_argument("run_id")

    check = commands.add_parser("check-config", help="validate the minimal Direct configuration")
    check.add_argument("--config", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "generate":
            result = generate(
                args.need,
                args.config,
                resume_run_id=args.resume_run_id,
                restart_from=args.restart_from,
            )
        elif args.command == "observe":
            from agent_world.config import load_settings

            result = observe_run(load_settings(args.config).state_root, args.run_id)
        else:
            result = check_config(args.config)
    except (ConfigurationError, ObserveError, ValueError) as exc:
        print(json.dumps({"status": "error", "code": str(exc)}))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised by the console entry point
    raise SystemExit(main())
