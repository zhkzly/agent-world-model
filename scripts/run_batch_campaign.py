#!/usr/bin/env python3
"""Run the frozen 20-Need S1/S2 evidence campaign sequentially."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent_env_foundry.assessment import (
    CorpusPolicy,
    read_identity_artifact,
    run_task_foundry_product,
)
from agent_env_foundry.generation import GenerationConfig, Released, generate_environment_v2
from agent_env_foundry.release import canonical_bytes
from agent_env_foundry.research import NotReleased, Unsupported


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _read_suite(path: Path) -> tuple[dict[str, Any], ...]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or set(document) != {"format", "needs"}:
        raise ValueError("Need suite must contain exactly format and needs")
    if document["format"] != "need-suite/1" or not isinstance(document["needs"], list):
        raise ValueError("Need suite format is invalid")
    needs = tuple(document["needs"])
    if len(needs) != 20:
        raise ValueError(f"official campaign requires exactly 20 Needs, got {len(needs)}")
    ids: list[str] = []
    for index, item in enumerate(needs, 1):
        if not isinstance(item, dict) or set(item) != {"id", "domain", "family", "need"}:
            raise ValueError(f"Need {index} has an invalid shape")
        if not all(isinstance(item[key], str) and item[key].strip() for key in item):
            raise ValueError(f"Need {index} fields must be non-empty strings")
        ids.append(item["id"])
    if len(set(ids)) != len(ids):
        raise ValueError("Need IDs must be unique")
    return needs


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(("git", *args), cwd=repo, check=True, capture_output=True, text=True)
    return result.stdout.strip()


def _atomic_write(path: Path, document: dict[str, Any]) -> None:
    payload = canonical_bytes(document)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(payload)
    temporary.replace(path)


def _append_event(path: Path, event: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("ab") as stream:
        stream.write(canonical_bytes(event) + b"\n")


def _exception(exc: Exception) -> dict[str, Any]:
    details = getattr(exc, "details", {})
    try:
        safe_details = json.loads(json.dumps(details, ensure_ascii=False, default=str))
    except (TypeError, ValueError):
        safe_details = {"unserializable_details": str(details)}
    return {
        "type": type(exc).__name__,
        "kind": getattr(exc, "kind", None),
        "code": getattr(exc, "code", type(exc).__name__),
        "message": str(exc),
        "details": safe_details,
    }


def _next_attempt(need_root: Path) -> tuple[int, Path]:
    attempts = need_root / "attempts"
    attempts.mkdir(parents=True, exist_ok=True)
    indexes = [int(path.name.removeprefix("attempt-")) for path in attempts.glob("attempt-*")]
    index = max(indexes, default=0) + 1
    return index, attempts / f"attempt-{index:03d}"


def _run_need(
    need: dict[str, Any],
    campaign_root: Path,
    suite_digest: str,
    campaign_id: str,
) -> dict[str, Any]:
    need_root = campaign_root / "needs" / need["id"]
    record_path = campaign_root / "records" / f"{need['id']}.json"
    if record_path.exists():
        record = json.loads(record_path.read_text(encoding="utf-8"))
        if record.get("campaign_id") != campaign_id or record.get("suite_digest") != suite_digest:
            raise ValueError(f"terminal record identity drift for {need['id']}")
        if record.get("terminal") == "released_and_sampled":
            product_path = campaign_root / record["product_report"]
            read_identity_artifact(product_path, record["product_run_id"])
        print(json.dumps({"event": "need_skipped", "need_id": need["id"]}), flush=True)
        return record

    attempt_index, attempt = _next_attempt(need_root)
    started_at = _utc_now()
    started = time.monotonic_ns()
    event_log = attempt / "events.jsonl"

    def emit(event: dict[str, Any]) -> None:
        envelope = {"need_id": need["id"], "attempt": attempt_index, **event}
        _append_event(event_log, envelope)
        print(json.dumps(envelope, ensure_ascii=False, sort_keys=True), flush=True)

    base: dict[str, Any] = {
        "format": "campaign-need-record/1",
        "campaign_id": campaign_id,
        "suite_digest": suite_digest,
        "need_id": need["id"],
        "domain": need["domain"],
        "family": need["family"],
        "attempt": attempt_index,
        "started_at": started_at,
    }
    generation = generate_environment_v2(
        need["need"],
        attempt / "generation-work",
        attempt / "generation-output",
        config=GenerationConfig(),
        event_sink=emit,
    )
    if isinstance(generation, (NotReleased, Unsupported)):
        record = {
            **base,
            "terminal": "unsupported" if isinstance(generation, Unsupported) else "not_released",
            "owner": generation.details.get("owner"),
            "code": generation.code,
            "message": generation.message,
            "details": generation.details,
        }
    else:
        assert isinstance(generation, Released)
        try:
            product = run_task_foundry_product(
                generation.prepared,
                attempt / "s2-work",
                attempt / "s2-output",
                target_structures=3,
                assessment_trial_count=3,
                corpus_policy=CorpusPolicy("rl", 0.5, None),
                corpus_seed=0,
                max_provider_turns=12,
                candidate_attempt_limit=3,
                event_sink=emit,
            )
        except Exception as exc:
            record = {
                **base,
                "terminal": "s2_failed",
                "release_id": generation.release_id,
                "release_archive": str(generation.archive.relative_to(campaign_root)),
                "failure": _exception(exc),
            }
        else:
            product_path = attempt / "s2-output/runs" / f"{product.product_run_id}.json"
            record = {
                **base,
                "terminal": "released_and_sampled",
                "release_id": generation.release_id,
                "release_archive": str(generation.archive.relative_to(campaign_root)),
                "product_run_id": product.product_run_id,
                "product_report": str(product_path.relative_to(campaign_root)),
                "corpus_id": product.corpus.corpus_id,
                "candidate_count": product.batch.candidate_count,
                "structure_count": product.batch.structure_count,
                "admitted_count": len(product.batch.admitted),
                "rejected_count": len(product.batch.rejected),
                "goal_kinds": [item.kind for item in product.batch.admitted],
                "reliabilities": [item.reliability for item in product.assessments],
                "assessment_trials": sum(item.policy.trial_count for item in product.assessments),
                "assessment_provider_turns": sum(
                    item.provider_turns for item in product.assessments
                ),
                "assessment_tokens": sum(
                    item.input_tokens + item.output_tokens for item in product.assessments
                ),
                "assessment_latency_ms": sum(item.latency_ms for item in product.assessments),
            }
    record["finished_at"] = _utc_now()
    record["elapsed_ms"] = (time.monotonic_ns() - started) // 1_000_000
    record["record_id"] = _digest(record)
    _atomic_write(record_path, record)
    print(
        json.dumps(
            {"event": "need_terminal", "need_id": need["id"], "terminal": record["terminal"]}
        ),
        flush=True,
    )
    return record


def _summary(campaign_id: str, suite_digest: str, records: list[dict[str, Any]]) -> dict[str, Any]:
    successes = [item for item in records if item["terminal"] == "released_and_sampled"]
    terminals: dict[str, int] = {}
    for item in records:
        terminals[item["terminal"]] = terminals.get(item["terminal"], 0) + 1
    trials = sum(item.get("assessment_trials", 0) for item in successes)
    trial_successes = sum(
        round(reliability * 3)
        for item in successes
        for reliability in item.get("reliabilities", [])
    )
    summary = {
        "format": "campaign-summary/1",
        "campaign_id": campaign_id,
        "suite_digest": suite_digest,
        "need_count": len(records),
        "terminal_counts": terminals,
        "released_and_sampled": len(successes),
        "release_rate": len(successes) / len(records),
        "candidate_count": sum(item.get("candidate_count", 0) for item in successes),
        "structure_count": sum(item.get("structure_count", 0) for item in successes),
        "admitted_task_count": sum(item.get("admitted_count", 0) for item in successes),
        "rejected_attempt_count": sum(item.get("rejected_count", 0) for item in successes),
        "assessment_trials": trials,
        "assessment_successes": trial_successes,
        "assessment_success_rate": trial_successes / trials if trials else None,
    }
    return {**summary, "summary_id": _digest(summary)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--suite", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    needs = _read_suite(args.suite)
    suite_document = {"format": "need-suite/1", "needs": list(needs)}
    suite_digest = _digest(suite_document)
    print(f"SUITE_DIGEST={suite_digest}")
    if args.validate_only:
        print("NEED_COUNT=20")
        return
    if _git(repo, "status", "--porcelain"):
        raise RuntimeError("official campaign requires a clean source worktree")
    source_commit = _git(repo, "rev-parse", "HEAD")
    config = {
        "format": "campaign-config/1",
        "suite_digest": suite_digest,
        "source_commit": source_commit,
        "target_structures": 3,
        "assessment_trial_count": 3,
        "minimum_reliability": 0.5,
        "candidate_attempt_limit": 3,
        "model": "gpt-5.6-luna",
        "base_url": "http://localhost:8317/v1",
    }
    campaign_id = _digest(config)
    campaign_root = args.root.resolve() / campaign_id
    campaign_root.mkdir(parents=True, exist_ok=True)
    _atomic_write(campaign_root / "campaign-config.json", {**config, "campaign_id": campaign_id})
    records = [_run_need(need, campaign_root, suite_digest, campaign_id) for need in needs]
    summary = _summary(campaign_id, suite_digest, records)
    _atomic_write(campaign_root / "summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
