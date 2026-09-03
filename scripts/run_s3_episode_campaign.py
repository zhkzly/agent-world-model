#!/usr/bin/env python3
"""Run the exact current multi-Release S3 Episode campaign."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

from agent_env_foundry.agents import AgentRoute
from agent_env_foundry.episode_campaign import run_episode_campaign


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _emit(document: dict[str, Any]) -> None:
    print(
        json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        flush=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--s1-campaign-root", type=Path, required=True)
    parser.add_argument("--s2-campaign-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--s1-campaign-id", required=True)
    parser.add_argument("--corpus-manifest-id", required=True)
    parser.add_argument("--rollouts-per-task", type=int, default=8)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    if _git(repo, "status", "--porcelain"):
        raise RuntimeError("S3 campaign source worktree must be clean and committed")
    result = run_episode_campaign(
        s1_campaign_root=args.s1_campaign_root,
        s2_campaign_root=args.s2_campaign_root,
        output_root=args.output_root,
        source_commit=_git(repo, "rev-parse", "HEAD"),
        expected_s1_campaign_id=args.s1_campaign_id,
        expected_corpus_manifest_id=args.corpus_manifest_id,
        route=AgentRoute(),
        rollouts_per_task=args.rollouts_per_task,
        workers=args.workers,
        event_sink=_emit,
    )
    _emit(
        {
            "event": "result",
            "root": str(result.root),
            "batch_id": result.manifest.batch_id,
            "summary_id": result.summary["summary_id"],
            "sft_ready": result.summary["sft_ready"],
        }
    )
    return 0 if result.summary["sft_ready"] is True else 2


if __name__ == "__main__":
    raise SystemExit(main())
