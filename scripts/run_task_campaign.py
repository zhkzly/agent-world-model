#!/usr/bin/env python3
"""Sample every unique admitted Task from released S1 environments."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent_env_foundry.builder import BuilderConfig
from agent_env_foundry.physical_runtime import PreparationSettings
from agent_env_foundry.preparation_v3 import prepare_release_v3_internal
from agent_env_foundry.release import canonical_bytes
from agent_env_foundry.task_pack import verify_task_pack
from agent_env_foundry.task_sampler import sample_good_tasks

_PRINT_LOCK = threading.Lock()


def _print(document: dict[str, Any]) -> None:
    with _PRINT_LOCK:
        print(json.dumps(document, ensure_ascii=False, sort_keys=True), flush=True)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _atomic_write(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(canonical_bytes(document))
    temporary.replace(path)


def _append_event(path: Path, event: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("ab") as stream:
        stream.write(canonical_bytes(event) + b"\n")


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(("git", *args), cwd=repo, check=True, capture_output=True, text=True)
    return result.stdout.strip()


def _campaign_config(
    s1_campaign_id: str,
    source_commit: str,
    candidate_budget: int,
) -> dict[str, Any]:
    return {
        "format": "task-sampling-campaign-config/1",
        "s1_campaign_id": s1_campaign_id,
        "source_commit": source_commit,
        "candidate_budget_per_release": candidate_budget,
        "target_count": None,
        "proposal_model": "gpt-5.6-luna",
        "checker_model": "gpt-5.6-luna",
        "base_url": "http://127.0.0.1:8317/v1",
    }


def _load_s1_sources(root: Path) -> tuple[str, tuple[dict[str, Any], ...]]:
    config_path = root / "campaign-config.json"
    if not config_path.is_file():
        raise ValueError("S1 campaign has no campaign-config.json")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    campaign_id = config.get("campaign_id")
    if not isinstance(campaign_id, str) or len(campaign_id) != 64:
        raise ValueError("S1 campaign identity is invalid")
    sources: list[dict[str, Any]] = []
    for path in sorted((root / "records").glob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        if record.get("campaign_id") != campaign_id:
            raise ValueError(f"S1 record belongs to another campaign: {path}")
        if record.get("terminal") != "released":
            continue
        required = (
            "need_id",
            "domain",
            "family",
            "release_id",
            "release_archive",
            "research_ready",
        )
        if any(not isinstance(record.get(field), str) for field in required):
            raise ValueError(f"S1 released record is incomplete: {path}")
        sources.append({field: record[field] for field in required})
    return campaign_id, tuple(sources)


def _select_sources(
    sources: tuple[dict[str, Any], ...],
    records: dict[str, dict[str, Any]],
    *,
    max_new: int | None,
) -> tuple[dict[str, Any], ...]:
    if max_new is None:
        return sources
    pending = tuple(
        source
        for source in sources
        if records.get(source["need_id"], {}).get("terminal") != "sampled"
    )
    return pending[:max_new]


def _existing_records(
    campaign_root: Path,
    *,
    campaign_id: str,
) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for path in sorted((campaign_root / "records").glob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        if record.get("campaign_id") != campaign_id or not isinstance(record.get("need_id"), str):
            raise ValueError(f"Task campaign record identity drift: {path}")
        records[record["need_id"]] = record
    return records


def _next_attempt(campaign_root: Path, need_id: str) -> tuple[int, Path]:
    attempts = campaign_root / "needs" / need_id / "attempts"
    attempts.mkdir(parents=True, exist_ok=True)
    indexes = [int(path.name.removeprefix("attempt-")) for path in attempts.glob("attempt-*")]
    index = max(indexes, default=0) + 1
    return index, attempts / f"attempt-{index:03d}"


def _safe_details(value: Any) -> Any:
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, default=str))
    except (TypeError, ValueError):
        return {"unserializable_details": str(value)}


def _sampling_metrics(
    report: dict[str, Any],
    *,
    sampling_root: Path,
    campaign_root: Path,
) -> dict[str, Any]:
    attempts = report["attempts"]
    stage_elapsed: dict[str, int] = {}
    rejection_codes: dict[str, int] = {}
    tokens = {"input": 0, "output": 0, "total": 0}
    tool_calls = 0
    packs: list[dict[str, Any]] = []
    for attempt in attempts:
        for stage, elapsed in attempt.get("stage_elapsed_ms", {}).items():
            stage_elapsed[stage] = stage_elapsed.get(stage, 0) + int(elapsed)
        tool_calls += int(attempt.get("proposal_tool_calls") or 0)
        tool_calls += sum(int(item) for item in attempt.get("witness_tool_calls", []))
        usage = attempt.get("provider_usage", {})
        _add_usage(tokens, usage.get("proposal", []))
        for witness_usage in usage.get("witnesses", []):
            _add_usage(tokens, witness_usage)
        if attempt["status"] == "rejected":
            code = str(attempt.get("code") or "unknown")
            rejection_codes[code] = rejection_codes.get(code, 0) + 1
            continue
        pack_id = str(attempt["task_pack_id"])
        pack_root = sampling_root / "packs" / pack_id
        verified = verify_task_pack(pack_root, expected_id=pack_id)
        packs.append(
            {
                "release_id": verified.task.release_id,
                "task_pack_id": pack_id,
                "structure_id": verified.structure_id,
                "path": str(pack_root.relative_to(campaign_root)),
            }
        )
    return {
        "candidate_count": len(attempts),
        "accepted_count": int(report["accepted_count"]),
        "rejected_count": int(report["rejected_count"]),
        "duplicate_count": rejection_codes.get("duplicate_task_structure", 0),
        "task_packs": packs,
        "stage_elapsed_ms": stage_elapsed,
        "tokens": tokens,
        "tool_calls": tool_calls,
        "rejection_codes": rejection_codes,
    }


def _add_usage(totals: dict[str, int], usage: Any) -> None:
    if not isinstance(usage, list):
        return
    for item in usage:
        if not isinstance(item, dict):
            continue
        totals["input"] += int(item.get("input_tokens", 0))
        totals["output"] += int(item.get("output_tokens", 0))
        totals["total"] += int(item.get("total_tokens", 0))


def _run_source(
    source: dict[str, Any],
    *,
    s1_root: Path,
    campaign_root: Path,
    campaign_id: str,
    candidate_budget: int,
) -> dict[str, Any]:
    need_id = str(source["need_id"])
    record_path = campaign_root / "records" / f"{need_id}.json"
    if record_path.exists():
        existing = json.loads(record_path.read_text(encoding="utf-8"))
        if existing.get("campaign_id") != campaign_id:
            raise ValueError(f"Task record identity drift for {need_id}")
        if existing.get("terminal") == "sampled":
            for item in existing.get("task_packs", []):
                verify_task_pack(campaign_root / item["path"], expected_id=item["task_pack_id"])
            _print({"event": "task_source_skipped", "need_id": need_id})
            return existing

    attempt_index, attempt_root = _next_attempt(campaign_root, need_id)
    attempt_root.mkdir()
    started = time.monotonic_ns()
    base = {
        "format": "task-sampling-campaign-record/1",
        "campaign_id": campaign_id,
        "need_id": need_id,
        "domain": source["domain"],
        "family": source["family"],
        "release_id": source["release_id"],
        "attempt": attempt_index,
        "started_at": _utc_now(),
    }
    try:
        prepared = prepare_release_v3_internal(
            s1_root / source["release_archive"],
            attempt_root / "release-cache",
            settings=PreparationSettings(attempt_root / "uv-cache", 300),
        )
        if prepared.identity.release_id != source["release_id"]:
            raise ValueError("prepared Release differs from S1 record")
        sampling_root = attempt_root / "sampling"
        report = sample_good_tasks(
            prepared,
            development_brief=prepared.builder_projection.to_document(),
            builder_projection_digest=prepared.identity.builder_projection_digest,
            output_root=sampling_root,
            candidate_budget=candidate_budget,
            target_count=None,
            checker_config=BuilderConfig(
                max_turns=3,
                uv_cache_dir=attempt_root / "uv-cache",
                command_timeout_seconds=300,
            ),
        )
        record = {
            **base,
            "terminal": "sampled",
            "sampling_report_id": report["report_id"],
            "sampling_report": str(
                (sampling_root / "DirectSamplingReport.json").relative_to(campaign_root)
            ),
            **_sampling_metrics(
                report,
                sampling_root=sampling_root,
                campaign_root=campaign_root,
            ),
        }
    except Exception as exc:
        record = {
            **base,
            "terminal": "worker_failed",
            "owner": getattr(exc, "kind", type(exc).__name__),
            "code": getattr(exc, "code", type(exc).__name__),
            "message": str(exc),
            "details": _safe_details(getattr(exc, "details", {})),
        }
    record["finished_at"] = _utc_now()
    record["elapsed_ms"] = (time.monotonic_ns() - started) // 1_000_000
    record["record_id"] = _digest(record)
    _atomic_write(attempt_root / "terminal.json", record)
    _atomic_write(record_path, record)
    _print(
        {
            "event": "task_source_terminal",
            "need_id": need_id,
            "terminal": record["terminal"],
            "accepted_count": record.get("accepted_count", 0),
            "elapsed_ms": record["elapsed_ms"],
        }
    )
    return record


def _summary(
    campaign_id: str,
    s1_campaign_id: str,
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    terminals: dict[str, int] = {}
    rejections: dict[str, int] = {}
    stage_elapsed: dict[str, int] = {}
    tokens = {"input": 0, "output": 0, "total": 0}
    for record in records:
        terminal = str(record["terminal"])
        terminals[terminal] = terminals.get(terminal, 0) + 1
        for code, count in record.get("rejection_codes", {}).items():
            rejections[code] = rejections.get(code, 0) + int(count)
        for stage, elapsed in record.get("stage_elapsed_ms", {}).items():
            stage_elapsed[stage] = stage_elapsed.get(stage, 0) + int(elapsed)
        for key in tokens:
            tokens[key] += int(record.get("tokens", {}).get(key, 0))
    candidate_count = sum(int(item.get("candidate_count", 0)) for item in records)
    accepted = sum(int(item.get("accepted_count", 0)) for item in records)
    preimage = {
        "format": "task-sampling-campaign-summary/1",
        "campaign_id": campaign_id,
        "s1_campaign_id": s1_campaign_id,
        "environment_count": len(records),
        "terminal_counts": terminals,
        "candidate_count": candidate_count,
        "accepted_task_count": accepted,
        "rejected_candidate_count": sum(int(item.get("rejected_count", 0)) for item in records),
        "acceptance_yield": accepted / candidate_count if candidate_count else 0.0,
        "duplicate_count": sum(int(item.get("duplicate_count", 0)) for item in records),
        "task_pack_count": sum(len(item.get("task_packs", [])) for item in records),
        "elapsed_ms": sum(int(item.get("elapsed_ms", 0)) for item in records),
        "stage_elapsed_ms": stage_elapsed,
        "tokens": tokens,
        "tool_calls": sum(int(item.get("tool_calls", 0)) for item in records),
        "rejection_codes": rejections,
        "domains_sampled": sorted(
            str(item["domain"]) for item in records if item["terminal"] == "sampled"
        ),
    }
    return {**preimage, "summary_id": _digest(preimage)}


def _corpus_manifest(campaign_id: str, records: list[dict[str, Any]]) -> dict[str, Any]:
    members = sorted(
        (
            {
                "need_id": record["need_id"],
                **pack,
            }
            for record in records
            if record["terminal"] == "sampled"
            for pack in record.get("task_packs", [])
        ),
        key=lambda item: (item["need_id"], item["task_pack_id"]),
    )
    preimage = {
        "format": "task-corpus-manifest/1",
        "campaign_id": campaign_id,
        "task_pack_count": len(members),
        "members": members,
    }
    return {**preimage, "manifest_id": _digest(preimage)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--s1-root", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--candidate-budget", type=int, default=15)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--max-new", type=int)
    args = parser.parse_args()
    if args.candidate_budget <= 0:
        raise ValueError("candidate-budget must be positive")
    if not 1 <= args.workers <= 4:
        raise ValueError("workers must be between 1 and 4")
    if args.max_new is not None and args.max_new <= 0:
        raise ValueError("max-new must be positive")
    repo = Path(__file__).resolve().parents[1]
    if _git(repo, "status", "--porcelain"):
        raise RuntimeError("official Task campaign requires a clean source worktree")
    s1_root = args.s1_root.resolve()
    s1_campaign_id, sources = _load_s1_sources(s1_root)
    source_commit = _git(repo, "rev-parse", "HEAD")
    config = _campaign_config(s1_campaign_id, source_commit, args.candidate_budget)
    campaign_id = _digest(config)
    campaign_root = args.root.resolve() / campaign_id
    campaign_root.mkdir(parents=True, exist_ok=True)
    config_document = {**config, "campaign_id": campaign_id}
    config_path = campaign_root / "campaign-config.json"
    if config_path.exists():
        if json.loads(config_path.read_text(encoding="utf-8")) != config_document:
            raise ValueError("Task campaign configuration drift")
    else:
        _atomic_write(config_path, config_document)
    records = _existing_records(campaign_root, campaign_id=campaign_id)
    selected = _select_sources(sources, records, max_new=args.max_new)
    _append_event(
        campaign_root / "campaign-events.jsonl",
        {
            "event": "task_campaign_run_started",
            "at": _utc_now(),
            "workers": args.workers,
            "max_new": args.max_new,
            "available_release_count": len(sources),
            "selected_need_ids": [item["need_id"] for item in selected],
        },
    )
    with ThreadPoolExecutor(max_workers=args.workers, thread_name_prefix="s2-task") as executor:
        futures = {
            executor.submit(
                _run_source,
                source,
                s1_root=s1_root,
                campaign_root=campaign_root,
                campaign_id=campaign_id,
                candidate_budget=args.candidate_budget,
            ): source["need_id"]
            for source in selected
        }
        for future in as_completed(futures):
            need_id = str(futures[future])
            record = future.result()
            records[need_id] = record
            values = sorted(records.values(), key=lambda item: item["need_id"])
            _atomic_write(
                campaign_root / "summary.partial.json",
                _summary(campaign_id, s1_campaign_id, values),
            )
    values = sorted(records.values(), key=lambda item: item["need_id"])
    summary = _summary(campaign_id, s1_campaign_id, values)
    corpus = _corpus_manifest(campaign_id, values)
    _atomic_write(campaign_root / "summary.json", summary)
    _atomic_write(campaign_root / "CorpusManifest.json", corpus)
    _print(summary)
    _print(corpus)


if __name__ == "__main__":
    main()
