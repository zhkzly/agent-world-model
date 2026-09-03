#!/usr/bin/env python3
"""Run the frozen S2 Good-Task campaign over exactly 20 Release/3 worlds."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean, median
from typing import Any, cast

from agent_env_foundry.agents import AgentRoute
from agent_env_foundry.environment import JSONObject, JSONValue
from agent_env_foundry.preparation_v3 import prepare_release_v3_internal
from agent_env_foundry.release import canonical_bytes
from agent_env_foundry.task_admission import (
    TaskAdmissionFailure,
    filter_candidate,
    load_task_pack,
    seal_task_pack,
)
from agent_env_foundry.task_candidate import (
    CandidateMaterializationFailure,
    CandidateTask,
    materialize_candidate,
)
from agent_env_foundry.task_draft import SamplingTarget
from agent_env_foundry.task_goal import AllGoal, AtomGoal, ForEachGoal, Goal, IfGoal
from agent_env_foundry.task_proposal import SamplingFailure, sample_task_draft

_SHAPES = ("atom", "all", "if", "foreach")
_OUTCOMES = ("query", "transition", "refusal")
_PRINT_LOCK = threading.Lock()


def _print(document: JSONObject) -> None:
    with _PRINT_LOCK:
        print(json.dumps(document, ensure_ascii=False, sort_keys=True), flush=True)


def _digest(document: Any) -> str:
    return hashlib.sha256(canonical_bytes(document)).hexdigest()


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _atomic_write(path: Path, document: JSONObject) -> None:
    payload = canonical_bytes(document)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(payload)
    temporary.replace(path)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ("git", *args), cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def _campaign_config(
    *,
    s1_campaign_id: str,
    source_commit: str,
    seed: int,
    attempt_budget: int,
) -> JSONObject:
    if attempt_budget <= 0 or seed < 0:
        raise ValueError("seed and attempt budget must be non-negative/positive")
    return {
        "format": "s2-good-task-campaign-config/1",
        "s1_campaign_id": s1_campaign_id,
        "source_commit": source_commit,
        "seed": seed,
        "attempt_budget_per_release": attempt_budget,
        "model": "gpt-5.6-luna",
        "base_url": "http://127.0.0.1:8317/v1",
        "filter_runs": 5,
        "minimum_passes": 2,
    }


def _select_target(
    *,
    release_id: str,
    tool_names: tuple[str, ...],
    seed: int,
    attempt_index: int,
    prior_records: list[dict[str, object]],
) -> SamplingTarget:
    if not tool_names or len(set(tool_names)) != len(tool_names):
        raise ValueError("scheduler requires unique public tool names")
    if attempt_index != len(prior_records) + 1:
        raise ValueError("scheduler attempt_index must follow retained terminal records")
    targets = [record.get("target") for record in prior_records]
    shape_counts: Counter[str] = Counter()
    outcome_counts: Counter[str] = Counter()
    tool_counts: Counter[str] = Counter()
    structure_ids: set[str] = set()
    for target in targets:
        if not isinstance(target, dict):
            raise ValueError("prior attempt omitted its SamplingTarget")
        shape_counts[str(target.get("required_goal_shape"))] += 1
        outcome_counts[str(target.get("required_outcome"))] += 1
        focus = target.get("required_focus_tools")
        if not isinstance(focus, list) or len(focus) != 1 or focus[0] not in tool_names:
            raise ValueError("prior SamplingTarget focus tool is invalid")
        tool_counts[str(focus[0])] += 1
    for record in prior_records:
        value = record.get("structure_id")
        if isinstance(value, str):
            structure_ids.add(value)
    redirect = _redirect_target(prior_records, tool_names)
    if redirect is not None:
        shape, outcome, tool = redirect
        return SamplingTarget(
            cast(Any, shape),
            (tool,),
            cast(Any, outcome),
            tuple(sorted(structure_ids)),
        )
    shape = _underused(
        _SHAPES,
        shape_counts,
        seed=seed,
        release_id=release_id,
        attempt_index=attempt_index,
        dimension="shape",
    )
    outcome = _underused(
        _OUTCOMES,
        outcome_counts,
        seed=seed,
        release_id=release_id,
        attempt_index=attempt_index,
        dimension="outcome",
    )
    tool = _underused(
        tool_names,
        tool_counts,
        seed=seed,
        release_id=release_id,
        attempt_index=attempt_index,
        dimension="tool",
    )
    return SamplingTarget(
        cast(Any, shape),
        (tool,),
        cast(Any, outcome),
        tuple(sorted(structure_ids)),
    )


def _redirect_target(
    prior_records: list[dict[str, object]], tool_names: tuple[str, ...]
) -> tuple[str, str, str] | None:
    if not prior_records:
        return None
    latest = prior_records[-1]
    if latest.get("terminal") != "DraftRejected":
        return None
    target = latest.get("target")
    details = latest.get("details")
    if not isinstance(target, dict) or not isinstance(details, dict):
        return None
    shape = target.get("required_goal_shape")
    required_outcome = target.get("required_outcome")
    code = latest.get("code")
    actual_tools = details.get("actual")
    outcome = required_outcome
    if code != "draft_focus_tool_missing":
        actual_tools = details.get("actual_tools")
        outcome = details.get("actual_outcome")
    if shape not in _SHAPES or outcome not in _OUTCOMES or not isinstance(actual_tools, list):
        return None
    prior_cells = {
        (
            str(cast(dict[str, Any], record["target"])["required_goal_shape"]),
            str(cast(dict[str, Any], record["target"])["required_outcome"]),
            str(cast(list[Any], cast(dict[str, Any], record["target"])["required_focus_tools"])[0]),
        )
        for record in prior_records
    }
    for tool in sorted(value for value in actual_tools if isinstance(value, str)):
        cell = (str(shape), str(outcome), tool)
        if tool in tool_names and cell not in prior_cells:
            return cell
    return None


def _underused(
    values: tuple[str, ...],
    counts: Counter[str],
    *,
    seed: int,
    release_id: str,
    attempt_index: int,
    dimension: str,
) -> str:
    minimum = min(counts[value] for value in values)
    choices = [value for value in values if counts[value] == minimum]
    return min(
        choices,
        key=lambda value: hashlib.sha256(
            f"{seed}\0{release_id}\0{attempt_index}\0{dimension}\0{value}".encode()
        ).hexdigest(),
    )


def _candidate_summary(candidate: CandidateTask) -> JSONObject:
    atoms = _goal_atoms(candidate.goal_truth.goal)
    return cast(
        JSONObject,
        {
            "structure_id": candidate.structure_id,
            "goal_shape": _goal_shape(candidate.goal_truth.goal),
            "objective_tools": sorted({atom.tool_name for atom in atoms}),
            "outcome_classes": sorted({atom.outcome for atom in atoms}),
            "instruction": candidate.instruction,
        },
    )


def _goal_shape(goal: Goal) -> str:
    if isinstance(goal, AtomGoal):
        return "atom"
    if isinstance(goal, AllGoal):
        return "all"
    if isinstance(goal, IfGoal):
        return "if"
    return "foreach"


def _goal_atoms(goal: Goal) -> tuple[AtomGoal, ...]:
    if isinstance(goal, AtomGoal):
        return (goal,)
    if isinstance(goal, AllGoal):
        return tuple(atom for child in goal.children for atom in _goal_atoms(child))
    if isinstance(goal, IfGoal):
        return tuple(
            atom
            for branch in (goal.then_goal, goal.else_goal)
            if branch is not None
            for atom in _goal_atoms(branch)
        )
    assert isinstance(goal, ForEachGoal)
    return goal.children


def _read_s1_releases(campaign_root: Path) -> list[JSONObject]:
    root = Path(campaign_root).resolve()
    paths = sorted((root / "records").glob("*.json"))
    if len(paths) != 20:
        raise ValueError(f"S2 requires exactly 20 S1 records, got {len(paths)}")
    records: list[JSONObject] = []
    campaign_ids: set[str] = set()
    releases: set[str] = set()
    for path in paths:
        document = json.loads(path.read_bytes())
        if not isinstance(document, dict) or document.get("terminal") != "released":
            raise ValueError(f"S1 record is not a released environment: {path}")
        release_path = (root / str(document.get("release_root"))).resolve()
        if not release_path.is_relative_to(root) or not (release_path / "release.json").is_file():
            raise ValueError(f"S1 release path escapes or is absent: {path}")
        release_id = document.get("release_id")
        campaign_id = document.get("campaign_id")
        if not isinstance(release_id, str) or not isinstance(campaign_id, str):
            raise ValueError(f"S1 record identity is invalid: {path}")
        if release_id in releases:
            raise ValueError("S1 campaign contains duplicate Release IDs")
        releases.add(release_id)
        campaign_ids.add(campaign_id)
        records.append(
            {
                "need_id": document["need_id"],
                "domain": document["domain"],
                "release_id": release_id,
                "release_path": str(release_path),
                "tool_names": cast(JSONValue, list(document["tool_names"])),
            }
        )
    if len(campaign_ids) != 1:
        raise ValueError("S1 records do not share one campaign identity")
    return records


def _load_attempts(need_root: Path, *, campaign_id: str, release_id: str) -> list[JSONObject]:
    records: list[JSONObject] = []
    for path in sorted((need_root / "attempts").glob("attempt-*/terminal.json")):
        document = json.loads(path.read_bytes())
        if (
            not isinstance(document, dict)
            or document.get("campaign_id") != campaign_id
            or document.get("release_id") != release_id
        ):
            raise ValueError(f"attempt identity drift: {path}")
        records.append(cast(JSONObject, document))
    records.sort(key=lambda item: cast(int, item["attempt_index"]))
    if [item["attempt_index"] for item in records] != list(range(1, len(records) + 1)):
        raise ValueError("attempt terminal records are not contiguous")
    return records


def _attempt_directory(need_root: Path, attempt_index: int) -> Path:
    base = need_root / "attempts" / f"attempt-{attempt_index:03d}"
    if not base.exists():
        return base
    retry = 1
    while (candidate := base.with_name(f"{base.name}-resume-{retry:02d}")).exists():
        retry += 1
    return candidate


def _unused_path(base: Path) -> Path:
    if not base.exists() and not base.is_symlink():
        return base
    index = 1
    while (candidate := base.with_name(f"{base.name}-{index:02d}")).exists():
        index += 1
    return candidate


def _safe_details(value: Any) -> JSONValue:
    try:
        return cast(JSONValue, json.loads(json.dumps(value, ensure_ascii=False, default=str)))
    except (TypeError, ValueError):
        return {"unserializable_details": str(value)}


def _select_pending_sources(
    sources: list[JSONObject],
    *,
    existing: dict[str, JSONObject],
    seed: int,
    sample_releases: int | None,
) -> list[JSONObject]:
    pending = [source for source in sources if source["need_id"] not in existing]
    pending.sort(key=lambda source: cast(str, source["need_id"]))
    if sample_releases is None:
        return pending
    return sorted(
        pending,
        key=lambda source: hashlib.sha256(
            f"{seed}\0{source['need_id']}\0{source['release_id']}".encode()
        ).hexdigest(),
    )[:sample_releases]


def _usage_totals(values: Any) -> tuple[int, int]:
    input_tokens = output_tokens = 0
    if isinstance(values, dict):
        raw_input = values.get("input_tokens")
        raw_output = values.get("output_tokens")
        input_tokens += (
            raw_input if isinstance(raw_input, int) and not isinstance(raw_input, bool) else 0
        )
        output_tokens += (
            raw_output if isinstance(raw_output, int) and not isinstance(raw_output, bool) else 0
        )
    elif isinstance(values, (list, tuple)):
        for item in values:
            child_input, child_output = _usage_totals(item)
            input_tokens += child_input
            output_tokens += child_output
    return input_tokens, output_tokens


def _run_attempt(
    prepared: Any,
    *,
    campaign_root: Path,
    need_root: Path,
    need_id: str,
    campaign_id: str,
    attempt_index: int,
    target: SamplingTarget,
    prior_summaries: tuple[JSONObject, ...],
    route: AgentRoute,
) -> JSONObject:
    attempt = _attempt_directory(need_root, attempt_index)
    attempt.mkdir(parents=True)
    started = time.monotonic_ns()
    base: JSONObject = {
        "format": "s2-good-task-attempt/1",
        "campaign_id": campaign_id,
        "need_id": need_id,
        "release_id": prepared.identity.release_id,
        "attempt_index": attempt_index,
        "started_at": _utc_now(),
        "target": target.to_document(),
        "target_id": target.target_id,
        "terminal": "FrameworkDefect",
        "owner": "FrameworkDefect",
        "code": "attempt_not_completed",
        "details": {},
        "sampling_evidence_id": None,
        "candidate_id": None,
        "reference_replay_id": None,
        "structure_id": None,
        "public_summary": None,
        "filter_evidence_id": None,
        "five_run_vector": None,
        "task_pack_id": None,
        "task_pack_path": None,
        "sampling_provider_turns": 0,
        "filter_provider_turns": 0,
        "sampling_tool_calls": 0,
        "filter_tool_calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
    }
    try:
        sampled = sample_task_draft(
            prepared,
            development_brief=prepared.builder_projection.to_document(),
            target=target,
            instance_directory=attempt / "sampling-instance",
            route=route,
            prior_accepted_summaries=prior_summaries,
        )
        _atomic_write(
            attempt / "SampledTask.json",
            {"draft": sampled.draft.to_document(), "evidence": sampled.evidence.to_document()},
        )
        sampling_input, sampling_output = _usage_totals(sampled.usage)
        base.update(
            {
                "sampling_evidence_id": sampled.evidence.evidence_id,
                "sampling_provider_turns": sampled.provider_turns,
                "sampling_tool_calls": len(sampled.evidence.public_trace),
                "input_tokens": sampling_input,
                "output_tokens": sampling_output,
            }
        )
        materialized = materialize_candidate(
            prepared,
            sampled=sampled,
            target=target,
            builder_projection_digest=prepared.identity.builder_projection_digest,
            replay_instance=attempt / "reference-replay",
        )
        candidate = materialized.candidate
        summary = _candidate_summary(candidate)
        _atomic_write(
            attempt / "Candidate.json",
            {
                "candidate": candidate.to_document(),
                "reference_replay": materialized.replay.to_document(),
                "argument_origins": [item.to_document() for item in materialized.argument_origins],
            },
        )
        base.update(
            {
                "candidate_id": candidate.candidate_id,
                "reference_replay_id": candidate.reference_replay_id,
                "structure_id": candidate.structure_id,
                "public_summary": summary,
            }
        )
        prior_structures = {
            cast(str, item["structure_id"])
            for item in prior_summaries
            if isinstance(item.get("structure_id"), str)
        }
        if candidate.structure_id in prior_structures:
            base.update(
                {
                    "terminal": "DuplicateStructure",
                    "owner": "DuplicateStructure",
                    "code": "duplicate_task_structure",
                    "details": {"structure_id": candidate.structure_id},
                }
            )
        else:
            filtered = filter_candidate(
                prepared,
                candidate,
                instance_root=attempt / "filter-instances",
                route=route,
            )
            _atomic_write(attempt / "FilterEvidence.json", filtered.to_document())
            filter_input, filter_output = _usage_totals([run.usage for run in filtered.runs])
            vector = [run.passed for run in filtered.runs]
            base.update(
                {
                    "filter_evidence_id": filtered.evidence_id,
                    "five_run_vector": cast(JSONValue, vector),
                    "filter_provider_turns": sum(run.provider_turns for run in filtered.runs),
                    "filter_tool_calls": sum(len(run.trace) for run in filtered.runs),
                    "input_tokens": sampling_input + filter_input,
                    "output_tokens": sampling_output + filter_output,
                }
            )
            if not filtered.admitted:
                base.update(
                    {
                        "terminal": "PolicyRejected",
                        "owner": "PolicyRejected",
                        "code": "candidate_below_pass_threshold",
                        "details": {"pass_count": filtered.pass_count},
                    }
                )
            else:
                artifact = seal_task_pack(
                    attempt / "TaskPack",
                    materialized=materialized,
                    sampling_evidence=sampled.evidence,
                    filter_evidence=filtered,
                )
                base.update(
                    {
                        "terminal": "admitted",
                        "owner": None,
                        "code": None,
                        "details": {},
                        "task_pack_id": artifact.task_pack_id,
                        "task_pack_path": str(artifact.root.relative_to(campaign_root)),
                    }
                )
    except (SamplingFailure, CandidateMaterializationFailure, TaskAdmissionFailure) as exc:
        if isinstance(exc, SamplingFailure):
            turns = exc.details.get("provider_turns")
            calls = exc.details.get("public_tool_calls")
            failure_input, failure_output = _usage_totals(exc.details.get("usage"))
            base.update(
                {
                    "sampling_provider_turns": turns if isinstance(turns, int) else 0,
                    "sampling_tool_calls": calls if isinstance(calls, int) else 0,
                    "input_tokens": failure_input,
                    "output_tokens": failure_output,
                }
            )
        retained_details = _safe_details(exc.details)
        if isinstance(retained_details, dict):
            retained_details.setdefault("message", str(exc))
        base.update(
            {
                "terminal": exc.kind,
                "owner": exc.kind,
                "code": exc.code,
                "details": retained_details,
            }
        )
    except Exception as exc:
        base.update(
            {
                "terminal": "FrameworkDefect",
                "owner": "CampaignRunner",
                "code": type(exc).__name__,
                "details": {"message": str(exc)},
            }
        )
    base["elapsed_ms"] = (time.monotonic_ns() - started) // 1_000_000
    base["finished_at"] = _utc_now()
    base["record_id"] = _digest(base)
    _atomic_write(attempt / "terminal.json", base)
    _print(
        {
            "event": "attempt_terminal",
            "need_id": need_id,
            "attempt_index": attempt_index,
            "terminal": base["terminal"],
            "code": base["code"],
            "elapsed_ms": base["elapsed_ms"],
        }
    )
    return base


def _release_record(
    *,
    campaign_id: str,
    source: JSONObject,
    attempts: list[JSONObject],
) -> JSONObject:
    terminal_counts = Counter(str(item["terminal"]) for item in attempts)
    admitted = [item for item in attempts if item["terminal"] == "admitted"]
    sampled = [item for item in attempts if item["sampling_evidence_id"] is not None]
    candidates = [item for item in attempts if item["candidate_id"] is not None]
    goal_attempts = Counter(
        str(cast(dict[str, Any], item["target"])["required_goal_shape"]) for item in attempts
    )
    goal_admitted = Counter(
        str(cast(dict[str, Any], item["target"])["required_goal_shape"]) for item in admitted
    )
    outcome_attempts = Counter(
        str(cast(dict[str, Any], item["target"])["required_outcome"]) for item in attempts
    )
    outcome_admitted = Counter(
        str(cast(dict[str, Any], item["target"])["required_outcome"]) for item in admitted
    )
    record = cast(
        JSONObject,
        {
            "format": "s2-good-task-release-record/1",
            "campaign_id": campaign_id,
            "need_id": source["need_id"],
            "domain": source["domain"],
            "release_id": source["release_id"],
            "terminal": "completed",
            "started_at": min(cast(str, item["started_at"]) for item in attempts),
            "finished_at": max(cast(str, item["finished_at"]) for item in attempts),
            "public_tool_count": len(cast(list[JSONValue], source["tool_names"])),
            "attempt_count": len(attempts),
            "attempt_terminal_counts": dict(sorted(terminal_counts.items())),
            "sampled_count": len(sampled),
            "candidate_count": len(candidates),
            "admitted_count": len(admitted),
            "unique_structure_count": len({item["structure_id"] for item in admitted}),
            "sampling_tool_calls": sum(cast(int, item["sampling_tool_calls"]) for item in attempts),
            "filter_tool_calls": sum(cast(int, item["filter_tool_calls"]) for item in attempts),
            "sampling_provider_turns": sum(
                cast(int, item["sampling_provider_turns"]) for item in attempts
            ),
            "filter_provider_turns": sum(
                cast(int, item["filter_provider_turns"]) for item in attempts
            ),
            "input_tokens": sum(cast(int, item["input_tokens"]) for item in attempts),
            "output_tokens": sum(cast(int, item["output_tokens"]) for item in attempts),
            "elapsed_ms": sum(cast(int, item["elapsed_ms"]) for item in attempts),
            "goal_attempts": dict(sorted(goal_attempts.items())),
            "goal_admitted": dict(sorted(goal_admitted.items())),
            "outcome_attempts": dict(sorted(outcome_attempts.items())),
            "outcome_admitted": dict(sorted(outcome_admitted.items())),
            "focus_tools_attempted": sorted(
                {
                    cast(
                        str,
                        cast(
                            list[Any], cast(dict[str, Any], item["target"])["required_focus_tools"]
                        )[0],
                    )
                    for item in attempts
                }
            ),
            "objective_tools_admitted": sorted(
                {
                    str(tool)
                    for item in admitted
                    for tool in cast(dict[str, Any], item["public_summary"])["objective_tools"]
                }
            ),
            "five_run_vectors": [
                item["five_run_vector"]
                for item in candidates
                if item["five_run_vector"] is not None
            ],
            "task_pack_ids": sorted(cast(str, item["task_pack_id"]) for item in admitted),
            "members": [
                {
                    "need_id": source["need_id"],
                    "release_id": source["release_id"],
                    "task_pack_id": item["task_pack_id"],
                    "structure_id": item["structure_id"],
                    "path": item["task_pack_path"],
                }
                for item in admitted
            ],
        },
    )
    return {**record, "record_id": _digest(record)}


def _run_release(
    source: JSONObject,
    *,
    campaign_root: Path,
    campaign_id: str,
    attempt_budget: int,
    seed: int,
    route: AgentRoute,
) -> JSONObject:
    need_id = cast(str, source["need_id"])
    need_root = campaign_root / "needs" / need_id
    attempts = _load_attempts(
        need_root,
        campaign_id=campaign_id,
        release_id=cast(str, source["release_id"]),
    )
    record_path = campaign_root / "records" / f"{need_id}.json"
    if len(attempts) >= attempt_budget:
        record = _release_record(campaign_id=campaign_id, source=source, attempts=attempts)
        _atomic_write(record_path, record)
        return record
    prepared = prepare_release_v3_internal(
        Path(cast(str, source["release_path"])), need_root / "release-cache"
    )
    probe = _unused_path(need_root / f"catalog-probe-{len(attempts) + 1:03d}")
    with prepared.open(probe) as session:
        tool_names = tuple(item["name"] for item in session.actor.tools())
    while len(attempts) < attempt_budget:
        attempt_index = len(attempts) + 1
        prior = [cast(dict[str, object], item) for item in attempts]
        target = _select_target(
            release_id=prepared.identity.release_id,
            tool_names=tool_names,
            seed=seed,
            attempt_index=attempt_index,
            prior_records=prior,
        )
        summaries = tuple(
            cast(JSONObject, item["public_summary"])
            for item in attempts
            if item.get("terminal") == "admitted" and isinstance(item.get("public_summary"), dict)
        )
        attempts.append(
            _run_attempt(
                prepared,
                campaign_root=campaign_root,
                need_root=need_root,
                need_id=need_id,
                campaign_id=campaign_id,
                attempt_index=attempt_index,
                target=target,
                prior_summaries=summaries,
                route=route,
            )
        )
    record = _release_record(campaign_id=campaign_id, source=source, attempts=attempts)
    _atomic_write(record_path, record)
    _print(
        {
            "event": "release_terminal",
            "need_id": need_id,
            "attempts": len(attempts),
            "admitted": record["admitted_count"],
        }
    )
    return record


def _corpus_manifest(campaign_id: str, members: list[dict[str, Any]]) -> JSONObject:
    selected: dict[str, dict[str, Any]] = {}
    for member in members:
        structure_id = str(member["structure_id"])
        current = selected.get(structure_id)
        if current is None or str(member["task_pack_id"]) < str(current["task_pack_id"]):
            selected[structure_id] = dict(member)
    retained = sorted(selected.values(), key=lambda item: str(item["task_pack_id"]))
    document: JSONObject = {
        "format": "task-corpus-manifest/2",
        "campaign_id": campaign_id,
        "task_pack_count": len(retained),
        "members": cast(JSONValue, retained),
    }
    return {**document, "manifest_id": _digest(document)}


def _merge_counts(records: list[dict[str, Any]], field: str) -> dict[str, int]:
    result: Counter[str] = Counter()
    for record in records:
        result.update(cast(dict[str, int], record.get(field, {})))
    return dict(sorted(result.items()))


def _value_counts(records: list[dict[str, Any]], field: str) -> dict[str, int]:
    return dict(sorted(Counter(str(record[field]) for record in records).items()))


def _percentile(values: list[int], fraction: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    index = round((len(ordered) - 1) * fraction)
    return ordered[index]


def _campaign_summary(
    campaign_id: str,
    s1_campaign_id: str,
    records: list[dict[str, Any]],
    *,
    corpus_manifest_id: str,
) -> JSONObject:
    elapsed = [int(item["elapsed_ms"]) for item in records]
    vectors = [
        vector
        for record in records
        for vector in cast(list[list[bool]], record["five_run_vectors"])
    ]
    policy_runs = sum(len(vector) for vector in vectors)
    policy_passes = sum(sum(vector) for vector in vectors)
    input_tokens = sum(int(item["input_tokens"]) for item in records)
    output_tokens = sum(int(item["output_tokens"]) for item in records)
    sampling_calls = sum(int(item["sampling_tool_calls"]) for item in records)
    filter_calls = sum(int(item["filter_tool_calls"]) for item in records)
    sampling_turns = sum(int(item["sampling_provider_turns"]) for item in records)
    filter_turns = sum(int(item["filter_provider_turns"]) for item in records)
    admitted_count = sum(int(item["admitted_count"]) for item in records)
    wall_clock_ms = round(
        (
            max(_parse_time(str(item["finished_at"])) for item in records)
            - min(_parse_time(str(item["started_at"])) for item in records)
        ).total_seconds()
        * 1000
    )
    task_pack_ids = sorted(
        task_pack_id for item in records for task_pack_id in cast(list[str], item["task_pack_ids"])
    )
    document = cast(
        JSONObject,
        {
            "format": "s2-good-task-campaign-summary/1",
            "campaign_id": campaign_id,
            "s1_campaign_id": s1_campaign_id,
            "corpus_manifest_id": corpus_manifest_id,
            "environment_count": len(records),
            "release_terminal_coverage": _value_counts(records, "terminal"),
            "attempt_count": sum(int(item["attempt_count"]) for item in records),
            "attempt_terminal_counts": _merge_counts(records, "attempt_terminal_counts"),
            "sampled_count": sum(int(item["sampled_count"]) for item in records),
            "candidate_count": sum(int(item["candidate_count"]) for item in records),
            "reference_replay_count": sum(int(item["candidate_count"]) for item in records),
            "admitted_task_count": admitted_count,
            "unique_structure_count": sum(int(item["unique_structure_count"]) for item in records),
            "goal_attempts": _merge_counts(records, "goal_attempts"),
            "goal_admitted": _merge_counts(records, "goal_admitted"),
            "outcome_attempts": _merge_counts(records, "outcome_attempts"),
            "outcome_admitted": _merge_counts(records, "outcome_admitted"),
            "public_tool_coverage": {
                "available": sum(int(item["public_tool_count"]) for item in records),
                "attempted": len(
                    {
                        (item["release_id"], tool)
                        for item in records
                        for tool in cast(list[str], item["focus_tools_attempted"])
                    }
                ),
                "admitted": len(
                    {
                        (item["release_id"], tool)
                        for item in records
                        for tool in cast(list[str], item["objective_tools_admitted"])
                    }
                ),
            },
            "five_run_vectors": cast(JSONValue, vectors),
            "policy_success": {
                "passes": policy_passes,
                "runs": policy_runs,
                "rate": policy_passes / policy_runs if policy_runs else 0.0,
            },
            "public_tool_calls": {
                "sampling": sampling_calls,
                "filter": filter_calls,
                "total": sampling_calls + filter_calls,
            },
            "provider_turns": {
                "sampling": sampling_turns,
                "filter": filter_turns,
            },
            "tokens": {
                "input": input_tokens,
                "output": output_tokens,
                "total": input_tokens + output_tokens,
            },
            "checker_generation": {"provider_turns": 0, "tokens": 0},
            "elapsed_ms": {
                "wall_clock": wall_clock_ms,
                "total": sum(elapsed),
                "mean": round(mean(elapsed)) if elapsed else None,
                "p50": round(median(elapsed)) if elapsed else None,
                "p95": _percentile(elapsed, 0.95),
            },
            "cost_per_admitted_task": (
                {
                    "input_tokens": round(input_tokens / admitted_count),
                    "output_tokens": round(output_tokens / admitted_count),
                    "total_tokens": round((input_tokens + output_tokens) / admitted_count),
                    "public_tool_calls": round((sampling_calls + filter_calls) / admitted_count),
                    "provider_turns": round((sampling_turns + filter_turns) / admitted_count),
                    "cumulative_elapsed_ms": round(sum(elapsed) / admitted_count),
                }
                if admitted_count
                else None
            ),
            "task_pack_ids": task_pack_ids,
        },
    )
    return {**document, "summary_id": _digest(document)}


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("campaign timestamp must include a timezone")
    return parsed


def _verified_members(campaign_root: Path, records: list[JSONObject]) -> list[dict[str, Any]]:
    members = [
        cast(dict[str, Any], member)
        for record in records
        for member in cast(list[Any], record["members"])
    ]
    for member in members:
        artifact = load_task_pack(campaign_root / str(member["path"]))
        if (
            artifact.task_pack_id != member["task_pack_id"]
            or artifact.candidate.structure_id != member["structure_id"]
            or artifact.candidate.release_id != member["release_id"]
        ):
            raise ValueError("retained TaskPack identity drift")
    return members


def _write_fan_in(
    campaign_root: Path,
    *,
    campaign_id: str,
    s1_campaign_id: str,
    records: list[JSONObject],
    final: bool,
) -> None:
    members = _verified_members(campaign_root, records)
    manifest = _corpus_manifest(campaign_id, members)
    summary = _campaign_summary(
        campaign_id,
        s1_campaign_id,
        cast(list[dict[str, Any]], records),
        corpus_manifest_id=cast(str, manifest["manifest_id"]),
    )
    suffix = "" if final else ".partial"
    _atomic_write(campaign_root / f"CorpusManifest{suffix}.json", manifest)
    _atomic_write(campaign_root / f"summary{suffix}.json", summary)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--s1-campaign-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--attempt-budget", type=int, default=15)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--sample-releases", type=int)
    args = parser.parse_args()
    if args.workers <= 0 or (args.sample_releases is not None and args.sample_releases <= 0):
        parser.error("workers and sample-releases must be positive")
    repo = Path(__file__).resolve().parents[1]
    if _git(repo, "status", "--porcelain"):
        raise RuntimeError("campaign source worktree must be clean and committed")
    sources = _read_s1_releases(args.s1_campaign_root)
    s1_campaign_ids = {
        json.loads(path.read_bytes())["campaign_id"]
        for path in (args.s1_campaign_root / "records").glob("*.json")
    }
    s1_campaign_id = cast(str, next(iter(s1_campaign_ids)))
    config = _campaign_config(
        s1_campaign_id=s1_campaign_id,
        source_commit=_git(repo, "rev-parse", "HEAD"),
        seed=args.seed,
        attempt_budget=args.attempt_budget,
    )
    campaign_id = _digest(config)
    campaign_root = args.output_root.resolve() / campaign_id
    campaign_root.mkdir(parents=True, exist_ok=True)
    config_path = campaign_root / "campaign-config.json"
    saved_config = {**config, "campaign_id": campaign_id}
    if config_path.exists() and json.loads(config_path.read_bytes()) != saved_config:
        raise ValueError("campaign config identity drift")
    _atomic_write(config_path, saved_config)
    existing = {
        path.stem: cast(JSONObject, json.loads(path.read_bytes()))
        for path in (campaign_root / "records").glob("*.json")
    }
    if any(record.get("campaign_id") != campaign_id for record in existing.values()):
        raise ValueError("campaign release record identity drift")
    pending = _select_pending_sources(
        sources,
        existing=existing,
        seed=args.seed,
        sample_releases=args.sample_releases,
    )
    route = AgentRoute()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(
                _run_release,
                source,
                campaign_root=campaign_root,
                campaign_id=campaign_id,
                attempt_budget=args.attempt_budget,
                seed=args.seed,
                route=route,
            ): cast(str, source["need_id"])
            for source in pending
        }
        for future in as_completed(futures):
            record = future.result()
            existing[cast(str, record["need_id"])] = record
            records = [existing[key] for key in sorted(existing)]
            _write_fan_in(
                campaign_root,
                campaign_id=campaign_id,
                s1_campaign_id=s1_campaign_id,
                records=records,
                final=len(records) == 20,
            )
    if not pending:
        records = [existing[key] for key in sorted(existing)]
        _write_fan_in(
            campaign_root,
            campaign_id=campaign_id,
            s1_campaign_id=s1_campaign_id,
            records=records,
            final=len(records) == 20,
        )
    _print(
        {
            "event": "campaign_checkpoint",
            "campaign_id": campaign_id,
            "campaign_root": str(campaign_root),
            "terminal_releases": len(existing),
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
