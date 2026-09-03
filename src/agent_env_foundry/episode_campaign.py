"""Resumable multi-Release campaign for current verified S3 Episodes."""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from collections import Counter, defaultdict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from statistics import mean, median
from typing import Any, cast

from agent_env_foundry.agents import AgentRoute
from agent_env_foundry.environment import JSONObject
from agent_env_foundry.episode_artifacts import (
    read_episode_bundle,
    read_episode_record,
    write_episode_bundle,
)
from agent_env_foundry.episode_batch_v2 import (
    EpisodeBatchManifest,
    EpisodeSlotResult,
    build_episode_batch_manifest,
    read_episode_batch_manifest,
    slot_result_from_document,
    write_episode_batch_manifest,
)
from agent_env_foundry.episode_runtime_v2 import EpisodeExecutionFailure, run_task_episode
from agent_env_foundry.episode_sources import (
    EpisodeSource,
    load_episode_sources,
    plan_episode_requests,
)
from agent_env_foundry.episodes import EpisodeRequest, PolicySpec
from agent_env_foundry.jsonvalue import is_json_object
from agent_env_foundry.preparation_v3 import PreparationSettingsV3, prepare_release_v3_internal
from agent_env_foundry.public_agent import ClientFactory, ResponsesPolicyDriver
from agent_env_foundry.release import canonical_bytes

CAMPAIGN_CONFIG_FORMAT = "s3-episode-campaign-config/1"
CAMPAIGN_SUMMARY_FORMAT = "s3-episode-campaign-summary/1"
EventSink = Callable[[JSONObject], None]


@dataclass(frozen=True, slots=True)
class EpisodeCampaignResult:
    root: Path
    manifest: EpisodeBatchManifest
    summary: JSONObject


def campaign_config(
    *,
    source_commit: str,
    s1_campaign_id: str,
    corpus_manifest_id: str,
    policy: PolicySpec,
    rollouts_per_task: int,
) -> JSONObject:
    _git_commit(source_commit)
    _digest(s1_campaign_id, "s1_campaign_id")
    _digest(corpus_manifest_id, "corpus_manifest_id")
    if not isinstance(policy, PolicySpec):
        raise ValueError("policy must be a PolicySpec")
    _positive(rollouts_per_task, "rollouts_per_task")
    document: JSONObject = {
        "format": CAMPAIGN_CONFIG_FORMAT,
        "source_commit": source_commit,
        "s1_campaign_id": s1_campaign_id,
        "corpus_manifest_id": corpus_manifest_id,
        "policy": policy.to_document(),
        "rollouts_per_task": rollouts_per_task,
    }
    return {**document, "campaign_id": _document_digest(document)}


def write_slot_result(campaign_root: Path, result: EpisodeSlotResult) -> Path:
    if not isinstance(result, EpisodeSlotResult):
        raise TypeError("result must be an EpisodeSlotResult")
    root = _ordinary_directory(Path(campaign_root), "campaign_root")
    slots = root / "slots"
    if slots.is_symlink():
        raise ValueError("slots directory cannot be a symlink")
    slots.mkdir(exist_ok=True)
    path = slots / f"{result.request.request_id}.json"
    if path.exists() or path.is_symlink():
        existing = _read_slot(path)
        if existing != result:
            raise ValueError("slot result conflicts with an existing terminal record")
        return path
    _atomic_write(path, result.to_document())
    if _read_slot(path) != result:
        raise ValueError("slot result differs after cold read")
    return path


def load_slot_results(campaign_root: Path) -> dict[str, EpisodeSlotResult]:
    root = _ordinary_directory(Path(campaign_root), "campaign_root")
    slots = root / "slots"
    if not slots.exists():
        return {}
    slots = _ordinary_directory(slots, "slots")
    results: dict[str, EpisodeSlotResult] = {}
    for path in sorted(slots.iterdir()):
        if path.is_symlink() or not path.is_file() or path.suffix != ".json":
            raise ValueError("slots directory contains a non-canonical entry")
        result = _read_slot(path)
        request_id = result.request.request_id
        if path.stem != request_id or request_id in results:
            raise ValueError("slot filename or identity is invalid")
        results[request_id] = result
    return results


def run_episode_campaign(
    *,
    s1_campaign_root: Path,
    s2_campaign_root: Path,
    output_root: Path,
    source_commit: str,
    expected_s1_campaign_id: str,
    expected_corpus_manifest_id: str,
    route: AgentRoute | None = None,
    rollouts_per_task: int = 8,
    workers: int = 8,
    preparation_settings: PreparationSettingsV3 | None = None,
    client_factory: ClientFactory | None = None,
    event_sink: EventSink | None = None,
) -> EpisodeCampaignResult:
    """Run or resume every fixed Episode slot, then seal one exact batch."""

    _positive(workers, "workers")
    selected_route = route or AgentRoute()
    policy = ResponsesPolicyDriver.from_route(
        selected_route, client_factory=client_factory
    ).policy_spec
    config = campaign_config(
        source_commit=source_commit,
        s1_campaign_id=expected_s1_campaign_id,
        corpus_manifest_id=expected_corpus_manifest_id,
        policy=policy,
        rollouts_per_task=rollouts_per_task,
    )
    base = Path(output_root)
    if base.is_symlink() or (base.exists() and not base.is_dir()):
        raise ValueError("output_root must be a directory path")
    base.mkdir(parents=True, exist_ok=True)
    campaign_id = cast(str, config["campaign_id"])
    campaign_root = base.resolve() / campaign_id
    campaign_root.mkdir(exist_ok=True)
    _bind_config(campaign_root, config)
    sources = load_episode_sources(
        s1_campaign_root,
        s2_campaign_root,
        expected_s1_campaign_id=expected_s1_campaign_id,
        expected_corpus_manifest_id=expected_corpus_manifest_id,
    )
    requests = plan_episode_requests(sources, policy, rollouts_per_task=rollouts_per_task)
    expected = {request.request_id: request for request in requests}
    existing = load_slot_results(campaign_root)
    _validate_existing(campaign_root, expected, existing)
    pending = tuple(request for request in requests if request.request_id not in existing)
    source_by_pack = {source.task_pack_id: source for source in sources}
    groups: dict[str, list[tuple[EpisodeSource, EpisodeRequest]]] = defaultdict(list)
    for request in pending:
        source = source_by_pack[request.task_pack_id]
        groups[request.release_id].append((source, request))

    started = time.monotonic_ns()
    _emit(
        event_sink,
        {
            "event": "campaign_start",
            "campaign_id": campaign_id,
            "requested": len(requests),
            "existing": len(existing),
            "pending": len(pending),
            "workers": workers,
        },
    )
    if groups:
        with ThreadPoolExecutor(max_workers=min(workers, len(groups))) as executor:
            futures = {
                executor.submit(
                    _run_release_group,
                    campaign_root,
                    release_id,
                    tuple(sorted(items, key=lambda item: item[1].request_id)),
                    selected_route,
                    preparation_settings,
                    client_factory,
                    event_sink,
                ): release_id
                for release_id, items in groups.items()
            }
            for future in as_completed(futures):
                future.result()
                current = load_slot_results(campaign_root)
                _write_progress(campaign_root, campaign_id, len(requests), current, workers)
    results_by_id = load_slot_results(campaign_root)
    _validate_existing(campaign_root, expected, results_by_id)
    if set(results_by_id) != set(expected):
        raise ValueError("campaign ended without every exact Episode slot")
    results = tuple(results_by_id[request.request_id] for request in requests)
    manifest = build_episode_batch_manifest(
        expected_s1_campaign_id,
        expected_corpus_manifest_id,
        policy,
        rollouts_per_task,
        requests,
        results,
    )
    manifest_path = campaign_root / "EpisodeBatchManifest.json"
    if manifest_path.exists():
        if read_episode_batch_manifest(manifest_path, manifest.batch_id) != manifest:
            raise ValueError("existing EpisodeBatchManifest conflicts with terminal slots")
    else:
        write_episode_batch_manifest(campaign_root, manifest)
    elapsed_ms = (time.monotonic_ns() - started) // 1_000_000
    summary = _campaign_summary(
        campaign_root,
        campaign_id,
        manifest,
        sources,
        workers=workers,
        elapsed_ms=elapsed_ms,
    )
    summary_path = campaign_root / "summary.json"
    if summary_path.exists():
        if _read_canonical(summary_path, "campaign summary") != summary:
            raise ValueError("existing campaign summary conflicts with terminal slots")
    else:
        _atomic_write(summary_path, summary)
    _emit(
        event_sink,
        {
            "event": "campaign_complete",
            "campaign_id": campaign_id,
            "batch_id": manifest.batch_id,
            "requested": len(requests),
            "verified_success": manifest.aggregates["verified_success"],
            "verified_failure": manifest.aggregates["verified_failure"],
            "abstain": manifest.aggregates["abstain"],
            "blocked": manifest.aggregates["blocked"],
        },
    )
    return EpisodeCampaignResult(campaign_root, manifest, summary)


def _run_release_group(
    campaign_root: Path,
    release_id: str,
    items: tuple[tuple[EpisodeSource, EpisodeRequest], ...],
    route: AgentRoute,
    settings: PreparationSettingsV3 | None,
    client_factory: ClientFactory | None,
    event_sink: EventSink | None,
) -> None:
    source = items[0][0]
    try:
        prepared = prepare_release_v3_internal(
            source.release_root,
            campaign_root / "release-cache" / release_id,
            settings=settings,
        )
    except Exception as exc:
        for _source, request in items:
            result = _blocked_result(request, exc, "release_prepare")
            write_slot_result(campaign_root, result)
            _emit_slot(event_sink, result)
        return
    for current_source, request in items:
        try:
            driver = ResponsesPolicyDriver.from_route(route, client_factory=client_factory)
            instance = campaign_root / "instances" / request.request_id / uuid.uuid4().hex
            record = run_task_episode(
                prepared,
                current_source.task_pack,
                request,
                instance_directory=instance,
                policy_driver=driver,
            )
            write_episode_bundle(campaign_root, record)
            result = EpisodeSlotResult.episode(
                request,
                record.episode_id,
                record.reward.disposition,
                record.reward.reward,
            )
        except Exception as exc:
            result = _blocked_result(request, exc, "episode_execute")
        write_slot_result(campaign_root, result)
        _emit_slot(event_sink, result)


def _blocked_result(
    request: EpisodeRequest, exc: Exception, default_phase: str
) -> EpisodeSlotResult:
    if isinstance(exc, EpisodeExecutionFailure):
        owner, code, phase = exc.owner, exc.code, exc.phase
    else:
        owner = (
            "infrastructure"
            if getattr(exc, "kind", None) == "InfrastructureFailure"
            else "evidence"
        )
        raw_code = getattr(exc, "code", None)
        code = raw_code if isinstance(raw_code, str) and raw_code else "unexpected_exception"
        phase = default_phase
    details: JSONObject = {
        "original_code": type(exc).__name__,
        "original_message": str(exc),
    }
    return EpisodeSlotResult.blocked(
        request,
        cast(Any, owner),
        code,
        phase=phase,
        details=details,
    )


def _validate_existing(
    campaign_root: Path,
    expected: dict[str, EpisodeRequest],
    existing: dict[str, EpisodeSlotResult],
) -> None:
    for request_id, result in existing.items():
        if request_id not in expected or result.request != expected[request_id]:
            raise ValueError("existing slot does not belong to the frozen request set")
        if result.episode_id is None:
            continue
        view = read_episode_bundle(campaign_root, result.episode_id)
        if (
            view.request != result.request
            or view.disposition != result.disposition
            or view.reward != result.reward
        ):
            raise ValueError("existing Episode differs from its terminal slot")


def _campaign_summary(
    campaign_root: Path,
    campaign_id: str,
    manifest: EpisodeBatchManifest,
    sources: tuple[EpisodeSource, ...],
    *,
    workers: int,
    elapsed_ms: int,
) -> JSONObject:
    records = [
        read_episode_record(campaign_root, result["episode_id"])
        for result in manifest.results
        if isinstance(result["episode_id"], str)
    ]
    turns = [len(record.capture.turns) for record in records]
    calls = [call for record in records for turn in record.capture.turns for call in turn.calls]
    dispatched = [call for call in calls if call.dispatch_status == "dispatched"]
    token_counts = Counter[str]()
    for record in records:
        for turn in record.capture.turns:
            usage = turn.usage or {}
            for name in ("input_tokens", "output_tokens", "total_tokens"):
                value = usage.get(name)
                if isinstance(value, int) and not isinstance(value, bool):
                    token_counts[name] += value
    successful = [record for record in records if record.reward.disposition == "verified_success"]
    success_tasks = {record.request.task_pack_id for record in successful}
    success_releases = {record.request.release_id for record in successful}
    per_task = Counter(record.request.task_pack_id for record in successful)
    lengths = [
        sum(
            call.dispatch_status == "dispatched"
            for turn in record.capture.turns
            for call in turn.calls
        )
        for record in records
    ]
    document: JSONObject = {
        "format": CAMPAIGN_SUMMARY_FORMAT,
        "campaign_id": campaign_id,
        "batch_id": manifest.batch_id,
        "s1_campaign_id": manifest.s1_campaign_id,
        "corpus_manifest_id": manifest.corpus_manifest_id,
        "policy_id": manifest.policy.policy_id,
        "rollouts_per_task": manifest.rollouts_per_task,
        "worker_limit": workers,
        "task_pack_count": len(sources),
        "release_count": len({source.release_id for source in sources}),
        "aggregates": manifest.aggregates,
        "success_task_coverage": len(success_tasks),
        "success_release_coverage": len(success_releases),
        "sft_ready": len(success_tasks) == len(sources),
        "verified_successes_per_task": dict(sorted(per_task.items())),
        "provider_turns": sum(turns),
        "attempted_tool_calls": len(calls),
        "dispatched_tool_calls": len(dispatched),
        "tokens": {
            "input": token_counts["input_tokens"],
            "output": token_counts["output_tokens"],
            "total": token_counts["total_tokens"],
        },
        "trajectory_tool_calls": _length_summary(lengths),
        "elapsed_ms": elapsed_ms,
    }
    return {**document, "summary_id": _document_digest(document)}


def _length_summary(values: list[int]) -> JSONObject:
    if not values:
        return {"min": None, "mean": None, "median": None, "p95": None, "max": None}
    ordered = sorted(values)
    return {
        "min": ordered[0],
        "mean": round(mean(ordered), 2),
        "median": median(ordered),
        "p95": ordered[round((len(ordered) - 1) * 0.95)],
        "max": ordered[-1],
    }


def _write_progress(
    root: Path,
    campaign_id: str,
    requested: int,
    results: dict[str, EpisodeSlotResult],
    workers: int,
) -> None:
    terminals = Counter(result.terminal for result in results.values())
    dispositions = Counter(
        result.disposition for result in results.values() if result.disposition is not None
    )
    _atomic_write(
        root / "summary.partial.json",
        {
            "format": "s3-episode-campaign-progress/1",
            "campaign_id": campaign_id,
            "requested": requested,
            "terminal": len(results),
            "pending": requested - len(results),
            "episodes": terminals["episode"],
            "blocked": terminals["blocked"],
            "verified_success": dispositions["verified_success"],
            "verified_failure": dispositions["verified_failure"],
            "abstain": dispositions["abstain"],
            "worker_limit": workers,
        },
    )


def _bind_config(root: Path, config: JSONObject) -> None:
    path = root / "campaign-config.json"
    if path.exists():
        if _read_canonical(path, "campaign config") != config:
            raise ValueError("campaign configuration conflicts with existing output")
        return
    _atomic_write(path, config)


def _read_slot(path: Path) -> EpisodeSlotResult:
    return slot_result_from_document(_read_canonical(path, "Episode slot"))


def _atomic_write(path: Path, document: JSONObject) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_bytes(canonical_bytes(document))
    temporary.replace(path)


def _read_canonical(path: Path, role: str) -> JSONObject:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{role} must be an ordinary file")
    try:
        payload = path.read_bytes()
        document = json.loads(payload)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(f"{role} is unreadable: {type(exc).__name__}: {exc}") from exc
    if not is_json_object(document) or canonical_bytes(document) != payload:
        raise ValueError(f"{role} must contain canonical JSON")
    return cast(JSONObject, document)


def _ordinary_directory(path: Path, role: str) -> Path:
    if path.is_symlink() or not path.is_dir():
        raise ValueError(f"{role} must be an ordinary directory")
    return path.resolve()


def _emit(sink: EventSink | None, document: JSONObject) -> None:
    if sink is not None:
        sink(cast(JSONObject, json.loads(json.dumps(document, ensure_ascii=False))))


def _emit_slot(sink: EventSink | None, result: EpisodeSlotResult) -> None:
    _emit(
        sink,
        {
            "event": "episode_terminal",
            "request_id": result.request.request_id,
            "release_id": result.request.release_id,
            "task_pack_id": result.request.task_pack_id,
            "rollout_index": result.request.rollout_index,
            "terminal": result.terminal,
            "disposition": result.disposition,
            "blocked_owner": result.blocked_owner,
            "blocked_code": result.blocked_code,
        },
    )


def _document_digest(document: JSONObject) -> str:
    return hashlib.sha256(canonical_bytes(document)).hexdigest()


def _positive(value: Any, role: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{role} must be a positive integer")


def _digest(value: Any, role: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{role} must be a sha256 digest")


def _git_commit(value: Any) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 40
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError("source_commit must be a full git commit")


__all__ = [
    "CAMPAIGN_CONFIG_FORMAT",
    "CAMPAIGN_SUMMARY_FORMAT",
    "EpisodeCampaignResult",
    "campaign_config",
    "load_slot_results",
    "run_episode_campaign",
    "write_slot_result",
]
