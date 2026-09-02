#!/usr/bin/env python3
"""Run the frozen 20-Need EnvironmentRelease/3 campaign with bounded concurrency."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean, median
from typing import Any

from agent_env_foundry.generation_v3 import (
    GenerationConfigV3,
    ReleasedV3,
    generate_environment_v3_internal,
)
from agent_env_foundry.release import canonical_bytes
from agent_env_foundry.release_v3 import verify_release_v3_internal
from agent_env_foundry.research import NotReleased, Unsupported

_PRINT_LOCK = threading.Lock()


def _print(document: dict[str, Any]) -> None:
    with _PRINT_LOCK:
        print(json.dumps(document, ensure_ascii=False, sort_keys=True), flush=True)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _read_suite(path: Path) -> tuple[dict[str, str], ...]:
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


def _next_attempt(need_root: Path) -> tuple[int, Path]:
    attempts = need_root / "attempts"
    attempts.mkdir(parents=True, exist_ok=True)
    indexes = [int(path.name.removeprefix("attempt-")) for path in attempts.glob("attempt-*")]
    index = max(indexes, default=0) + 1
    return index, attempts / f"attempt-{index:03d}"


def _safe_details(value: Any) -> Any:
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, default=str))
    except (TypeError, ValueError):
        return {"unserializable_details": str(value)}


def _source_metrics(actor_root: Path) -> dict[str, int]:
    source_files = tuple(sorted((actor_root / "src").rglob("*.py")))
    test_files = tuple(sorted((actor_root / "tests").rglob("test_*.py")))
    source_loc = sum(
        1
        for path in source_files
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )
    test_count = 0
    for path in test_files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        test_count += sum(
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name.startswith("test_")
            for node in ast.walk(tree)
        )
    return {
        "source_python_files": len(source_files),
        "source_nonblank_loc": source_loc,
        "test_python_files": len(test_files),
        "test_functions": test_count,
    }


def _released_record(
    base: dict[str, Any],
    generation: ReleasedV3,
    attempt: Path,
    campaign_root: Path,
) -> dict[str, Any]:
    actor_root = attempt / "generation-work/actor"
    with generation.prepared.open(attempt / "metrics-probe-instance") as session:
        tools = session.actor.tools()
    research_root = attempt / "generation-work/research/evidence"
    evidence = json.loads(
        (generation.release_root / "conformance/evidence/report.json").read_bytes()
    )
    builder_checks = evidence.get("builder_checks", [])
    return {
        **base,
        "terminal": "released",
        "release_id": generation.release_id,
        "release_root": str(generation.release_root.relative_to(campaign_root)),
        "release_archive": str(generation.archive.relative_to(campaign_root)),
        "release_archive_bytes": generation.archive.stat().st_size,
        "research_digest": generation.research_digest,
        "research_sources": len(tuple((research_root / "source-revisions").glob("*"))),
        "research_extractions": len(tuple((research_root / "extractions").glob("*.json"))),
        "research_evidence_handles": len(
            tuple((research_root / "handles/evidence").glob("*.json"))
        ),
        "actor_digest": generation.prepared.identity.actor_digest,
        "state_schema_digest": generation.prepared.identity.state_schema_digest,
        "tool_count": len(tools),
        "tool_names": [item["name"] for item in tools],
        "builder_check_count": len(builder_checks) if isinstance(builder_checks, list) else 0,
        "stage_events": [dict(item) for item in generation.events],
        **_source_metrics(actor_root),
    }


def _run_need(
    need: dict[str, str],
    campaign_root: Path,
    suite_digest: str,
    campaign_id: str,
) -> dict[str, Any]:
    need_root = campaign_root / "needs" / need["id"]
    record_path = campaign_root / "records" / f"{need['id']}.json"
    if record_path.exists():
        existing = json.loads(record_path.read_text(encoding="utf-8"))
        if (
            existing.get("campaign_id") != campaign_id
            or existing.get("suite_digest") != suite_digest
        ):
            raise ValueError(f"record identity drift for {need['id']}")
        if existing.get("terminal") == "released":
            verify_release_v3_internal(campaign_root / existing["release_root"])
            _print({"event": "need_skipped", "need_id": need["id"], "terminal": "released"})
            return existing

    attempt_index, attempt = _next_attempt(need_root)
    started_at = _utc_now()
    started = time.monotonic_ns()
    event_log = attempt / "events.jsonl"

    def emit(event: dict[str, Any]) -> None:
        envelope = {"need_id": need["id"], "attempt": attempt_index, **event}
        _append_event(event_log, envelope)
        _print(envelope)

    base: dict[str, Any] = {
        "format": "s1-v3-campaign-need-record/1",
        "campaign_id": campaign_id,
        "suite_digest": suite_digest,
        "need_id": need["id"],
        "domain": need["domain"],
        "family": need["family"],
        "attempt": attempt_index,
        "started_at": started_at,
    }
    try:
        generation = generate_environment_v3_internal(
            need["need"],
            attempt / "generation-work",
            attempt / "generation-output",
            config=GenerationConfigV3(),
            event_sink=emit,
        )
        if isinstance(generation, (NotReleased, Unsupported)):
            record = {
                **base,
                "terminal": (
                    "unsupported" if isinstance(generation, Unsupported) else "not_released"
                ),
                "owner": generation.details.get("owner"),
                "code": generation.code,
                "message": generation.message,
                "details": _safe_details(generation.details),
            }
        else:
            record = _released_record(base, generation, attempt, campaign_root)
    except Exception as exc:
        record = {
            **base,
            "terminal": "worker_failed",
            "owner": getattr(exc, "kind", "CampaignRunner"),
            "code": getattr(exc, "code", type(exc).__name__),
            "message": str(exc),
            "details": _safe_details(getattr(exc, "details", {})),
        }
    record["finished_at"] = _utc_now()
    record["elapsed_ms"] = (time.monotonic_ns() - started) // 1_000_000
    record["record_id"] = _digest(record)
    _atomic_write(attempt / "terminal.json", record)
    _atomic_write(record_path, record)
    _print(
        {
            "event": "need_terminal",
            "need_id": need["id"],
            "terminal": record["terminal"],
            "elapsed_ms": record["elapsed_ms"],
        }
    )
    return record


def _percentile(values: list[int], fraction: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    position = max(0, min(len(ordered) - 1, round((len(ordered) - 1) * fraction)))
    return ordered[position]


def _summary(
    campaign_id: str,
    suite_digest: str,
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    released = [item for item in records if item["terminal"] == "released"]
    terminals: dict[str, int] = {}
    for item in records:
        terminals[item["terminal"]] = terminals.get(item["terminal"], 0) + 1
    elapsed = [int(item["elapsed_ms"]) for item in records]
    stage_values: dict[str, list[int]] = {}
    for item in released:
        for event in item.get("stage_events", []):
            if event.get("status") == "passed" and isinstance(event.get("elapsed_ms"), int):
                stage_values.setdefault(str(event["stage"]), []).append(event["elapsed_ms"])
    stage_summary = {
        stage: {
            "count": len(values),
            "mean_ms": round(mean(values)),
            "p50_ms": _percentile(values, 0.50),
            "p95_ms": _percentile(values, 0.95),
        }
        for stage, values in sorted(stage_values.items())
    }
    summary = {
        "format": "s1-v3-campaign-summary/1",
        "campaign_id": campaign_id,
        "suite_digest": suite_digest,
        "need_count": len(records),
        "terminal_counts": terminals,
        "released": len(released),
        "release_rate": len(released) / len(records) if records else 0.0,
        "elapsed_ms": {
            "total": sum(elapsed),
            "mean": round(mean(elapsed)) if elapsed else None,
            "p50": round(median(elapsed)) if elapsed else None,
            "p95": _percentile(elapsed, 0.95),
        },
        "stage_elapsed": stage_summary,
        "total_tools": sum(int(item.get("tool_count", 0)) for item in released),
        "total_source_nonblank_loc": sum(
            int(item.get("source_nonblank_loc", 0)) for item in released
        ),
        "total_test_functions": sum(int(item.get("test_functions", 0)) for item in released),
        "total_release_archive_bytes": sum(
            int(item.get("release_archive_bytes", 0)) for item in released
        ),
        "domains_released": sorted(item["domain"] for item in released),
    }
    return {**summary, "summary_id": _digest(summary)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--suite", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.workers <= 4:
        raise ValueError("workers must be between 1 and 4")
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
        "format": "s1-v3-campaign-config/1",
        "suite_digest": suite_digest,
        "source_commit": source_commit,
        "model": "gpt-5.6-luna",
        "base_url": "http://localhost:8317/v1",
        "workers": args.workers,
    }
    campaign_id = _digest(config)
    campaign_root = args.root.resolve() / campaign_id
    campaign_root.mkdir(parents=True, exist_ok=True)
    _atomic_write(campaign_root / "campaign-config.json", {**config, "campaign_id": campaign_id})

    records: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=args.workers, thread_name_prefix="s1-v3") as executor:
        futures = {
            executor.submit(_run_need, need, campaign_root, suite_digest, campaign_id): need["id"]
            for need in needs
        }
        for future in as_completed(futures):
            need_id = futures[future]
            try:
                record = future.result()
            except Exception as exc:
                _print(
                    {
                        "event": "campaign_worker_crashed",
                        "need_id": need_id,
                        "error_type": type(exc).__name__,
                        "message": str(exc),
                    }
                )
                raise
            records.append(record)
            partial = _summary(campaign_id, suite_digest, records)
            _atomic_write(campaign_root / "summary.partial.json", partial)
    records.sort(key=lambda item: item["need_id"])
    summary = _summary(campaign_id, suite_digest, records)
    _atomic_write(campaign_root / "summary.json", summary)
    _print(summary)


if __name__ == "__main__":
    main()
