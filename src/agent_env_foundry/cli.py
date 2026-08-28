"""Command-line entry point for the direct S1 coordinator."""

from __future__ import annotations

import argparse
import json
import tempfile
from collections.abc import Sequence
from pathlib import Path

from agent_env_foundry.api import GenerationConfig, Released, generate_environment, outcome_document
from agent_env_foundry.errors import EnvironmentContractError
from agent_env_foundry.publication import (
    PublicationError,
    extract_release_zip,
    verify_environment_release,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="foundry")
    commands = parser.add_subparsers(dest="command", required=True)

    generate = commands.add_parser("generate", help="Generate and cold-publish an environment")
    generate.add_argument("--need-file", type=Path, required=True)
    generate.add_argument("--run-store", type=Path, default=Path(".artifacts/foundry-runs"))
    generate.add_argument(
        "--release-store", type=Path, default=Path(".artifacts/environment-releases")
    )

    verify = commands.add_parser("verify-release", help="Verify an immutable release directory/ZIP")
    verify.add_argument("--release", type=Path, required=True)

    args = parser.parse_args(argv)
    if args.command == "generate":
        try:
            need_text = args.need_file.read_text(encoding="utf-8")
        except OSError as exc:
            parser.error(f"cannot read Need file: {exc}")
        outcome = generate_environment(
            need_text,
            config=GenerationConfig(run_store=args.run_store, release_store=args.release_store),
        )
        print(json.dumps(outcome_document(outcome), ensure_ascii=False, sort_keys=True))
        return 0 if isinstance(outcome, Released) else 2

    try:
        document = _verify_path(args.release)
    except (PublicationError, EnvironmentContractError) as exc:
        phase = exc.phase if isinstance(exc, PublicationError) else "verification"
        code = exc.code if isinstance(exc, PublicationError) else "release_invalid"
        print(
            json.dumps(
                {
                    "status": "not_verified",
                    "phase": phase,
                    "code": code,
                    "message": str(exc),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 2
    print(json.dumps(document, ensure_ascii=False, sort_keys=True))
    return 0


def _verify_path(path: Path) -> dict[str, str]:
    source = Path(path)
    if source.is_dir():
        release = verify_environment_release(source)
    else:
        with tempfile.TemporaryDirectory(prefix="foundry-verify-") as temporary:
            release = extract_release_zip(source, Path(temporary) / "release")
            return {
                "status": "verified",
                "release_id": release.release_id,
                "payload_digest": release.payload_digest,
                "qualification_digest": release.qualification_digest,
            }
    return {
        "status": "verified",
        "release_id": release.release_id,
        "payload_digest": release.payload_digest,
        "qualification_digest": release.qualification_digest,
    }


if __name__ == "__main__":
    raise SystemExit(main())
