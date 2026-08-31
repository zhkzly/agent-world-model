"""Exact serial S3 Episode execution for one current CorpusManifest."""

from __future__ import annotations

import hashlib
import json
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from agent_env_foundry.assessment import (
    AssessmentError,
    CorpusManifest,
    CorpusPolicy,
    CorpusSelectionCandidate,
    read_identity_artifact,
)
from agent_env_foundry.environment import JSONObject
from agent_env_foundry.episode_runtime import (
    EpisodeRecord,
    _load_task_authority,
    _read_episode_bundle_pair,
    run_task_episode,
    write_episode_bundle,
)
from agent_env_foundry.episodes import DefectOwner, EpisodeRequest, PolicySpec
from agent_env_foundry.jsonvalue import is_json_object
from agent_env_foundry.preparation import (
    OpenPreparedRelease,
    PreparationContractError,
    PreparationExecutionError,
)
from agent_env_foundry.public_agent import PolicyDriver
from agent_env_foundry.release import canonical_bytes
from agent_env_foundry.semantics import SemanticsContractError
from agent_env_foundry.task_foundry import TaskFoundryError

_HEX = frozenset("0123456789abcdef")
_OWNERS = frozenset(
    {
        "provider",
        "infrastructure",
        "environment",
        "task_artifact",
        "semantics",
        "verifier",
        "evidence",
    }
)
_RESULT_KEYS = {
    "task_pack_id",
    "rollout_index",
    "request_id",
    "episode_id",
    "blocked_owner",
    "blocked_code",
    "blocked_phase",
}
_AGGREGATE_KEYS = {
    "total_slots",
    "episode_count",
    "blocked_count",
    "verified_success",
    "verified_failure",
    "abstain",
    "attempted_calls",
    "dispatched_calls",
    "provider_turns",
    "input_tokens",
    "output_tokens",
    "missing_usage_turns",
    "policy_elapsed_ms",
    "abstain_owner_counts",
    "blocked_owner_counts",
}
_PACK_FILENAMES = {
    "atom": "AtomTaskPack.json",
    "foreach": "ForEachTaskPack.json",
    "if": "IfTaskPack.json",
}
_TRUST_OWNERS = frozenset({"environment", "task_artifact", "semantics", "verifier", "evidence"})


@dataclass(frozen=True, slots=True)
class EpisodeBatchManifest:
    corpus_id: str
    release_id: str
    policy_id: str
    rollouts_per_task: int
    results: tuple[JSONObject, ...]
    aggregates: JSONObject
    batch_id: str = ""

    def __post_init__(self) -> None:
        for value, role in (
            (self.corpus_id, "corpus_id"),
            (self.release_id, "release_id"),
            (self.policy_id, "policy_id"),
        ):
            _digest(value, role)
        _positive(self.rollouts_per_task, "rollouts_per_task")
        if not isinstance(self.results, tuple) or not self.results:
            raise ValueError("results must be a non-empty tuple")
        results = tuple(_result(item) for item in self.results)
        keys = tuple((item["task_pack_id"], item["rollout_index"]) for item in results)
        if len(keys) != len(set(keys)):
            raise ValueError("batch results contain a duplicate rollout slot")
        request_ids = tuple(item["request_id"] for item in results if item["request_id"])
        episode_ids = tuple(item["episode_id"] for item in results if item["episode_id"])
        if len(request_ids) != len(set(request_ids)) or len(episode_ids) != len(set(episode_ids)):
            raise ValueError("batch results contain a duplicate request or Episode")
        aggregates = _object(self.aggregates, "aggregates")
        _validate_aggregates(aggregates, len(results))
        object.__setattr__(self, "results", results)
        object.__setattr__(self, "aggregates", aggregates)
        expected = _document_digest(self._preimage())
        if self.batch_id and self.batch_id != expected:
            raise ValueError("batch_id differs from the complete batch preimage")
        object.__setattr__(self, "batch_id", expected)

    def _preimage(self) -> JSONObject:
        return {
            "format": "episode-batch-manifest/1",
            "corpus_id": self.corpus_id,
            "release_id": self.release_id,
            "policy_id": self.policy_id,
            "rollouts_per_task": self.rollouts_per_task,
            "results": [_object(item, "batch result") for item in self.results],
            "aggregates": _object(self.aggregates, "aggregates"),
        }

    def to_document(self) -> JSONObject:
        return {**self._preimage(), "batch_id": self.batch_id}


def run_episode_batch(
    prepared: OpenPreparedRelease,
    task_store_root: Path,
    corpus_manifest_path: Path,
    expected_corpus_id: str,
    output_root: Path,
    *,
    policy_spec: PolicySpec,
    policy_driver_factory: Callable[[], PolicyDriver],
    rollouts_per_task: int,
) -> EpisodeBatchManifest:
    """Execute one exact single-release Corpus serially without retry."""

    if not isinstance(policy_spec, PolicySpec):
        raise ValueError("policy_spec must be a PolicySpec")
    if not callable(policy_driver_factory):
        raise ValueError("policy_driver_factory must be callable")
    _positive(rollouts_per_task, "rollouts_per_task")
    root = Path(output_root)
    if root.exists() or root.is_symlink():
        raise ValueError("Episode batch output root must be absent")

    corpus = _read_corpus(corpus_manifest_path, expected_corpus_id)
    releases = {item.release_id for item in corpus.entries}
    if len(releases) != 1:
        raise TaskFoundryError(
            "episode_batch_multi_release_unsupported",
            "Episode batch supports exactly one Corpus release",
        )
    (corpus_release_id,) = tuple(releases)
    if corpus_release_id != prepared.identity.release_id:
        raise TaskFoundryError(
            "task_release_mismatch",
            "CorpusManifest belongs to another prepared release",
        )

    # A tuple is sufficient here: CP5 needs ordered frozen work, not a slot abstraction.
    frozen: list[tuple[CorpusSelectionCandidate, int, Path, EpisodeRequest | None, str | None]] = []
    request_ids: set[str] = set()
    for entry in corpus.entries:
        task_path = _task_path(Path(task_store_root), entry)
        authority_code: str | None = None
        authority = None
        try:
            authority, _task, _branch = _load_task_authority(
                prepared, task_path, entry.task_pack_id
            )
            if authority.public.goal_kind != entry.goal_kind:
                raise TaskFoundryError(
                    "task_goal_kind_mismatch",
                    "Corpus entry goal kind differs from its TaskPack",
                )
        except (
            TaskFoundryError,
            PreparationContractError,
            SemanticsContractError,
            ValueError,
        ) as exc:
            authority_code = _artifact_code(exc)
        for rollout_index in range(1, rollouts_per_task + 1):
            request = (
                None
                if authority is None
                else EpisodeRequest(
                    corpus_release_id,
                    entry.task_pack_id,
                    authority.public.task_id,
                    policy_spec.policy_id,
                    rollout_index,
                )
            )
            if request is not None:
                if request.request_id in request_ids:
                    raise ValueError("Corpus produced a duplicate logical EpisodeRequest")
                request_ids.add(request.request_id)
            frozen.append((entry, rollout_index, task_path, request, authority_code))

    # Invalid Corpus/release authority has returned before this single root creation.
    root.mkdir(parents=True)
    results: list[JSONObject] = []
    records: list[EpisodeRecord] = []
    retained_drivers: list[PolicyDriver] = []
    stopped_tasks: dict[str, tuple[DefectOwner, str]] = {}
    with tempfile.TemporaryDirectory(prefix="agent-env-foundry-episode-batch-") as runtime_root:
        runtime = Path(runtime_root)
        for entry, rollout_index, task_path, request, authority_code in frozen:
            if request is None:
                assert authority_code is not None
                results.append(
                    _blocked(
                        entry.task_pack_id,
                        rollout_index,
                        None,
                        "task_artifact",
                        authority_code,
                        "task_authority",
                    )
                )
                continue

            stopped = stopped_tasks.get(entry.task_pack_id)
            if stopped is not None:
                owner, code = stopped
                results.append(
                    _blocked(
                        entry.task_pack_id,
                        rollout_index,
                        request.request_id,
                        owner,
                        code,
                        "affected_task_authority",
                    )
                )
                continue

            try:
                driver = policy_driver_factory()
            except Exception as exc:
                failure = _pre_input_failure(exc)
                if failure is None:
                    raise
                owner, code = failure
                results.append(
                    _blocked(
                        entry.task_pack_id,
                        rollout_index,
                        request.request_id,
                        owner,
                        code,
                        "policy_driver_factory",
                    )
                )
                continue
            if any(driver is previous for previous in retained_drivers):
                driver.close()
                results.append(
                    _blocked(
                        entry.task_pack_id,
                        rollout_index,
                        request.request_id,
                        "evidence",
                        "policy_driver_reused",
                        "policy_driver_factory",
                    )
                )
                continue
            retained_drivers.append(driver)
            try:
                driver_spec = driver.policy_spec
            except Exception as exc:
                driver.close()
                failure = _pre_input_failure(exc)
                if failure is None:
                    raise
                owner, code = failure
                results.append(
                    _blocked(
                        entry.task_pack_id,
                        rollout_index,
                        request.request_id,
                        owner,
                        code,
                        "policy_spec",
                    )
                )
                continue
            if not isinstance(driver_spec, PolicySpec) or driver_spec != policy_spec:
                driver.close()
                results.append(
                    _blocked(
                        entry.task_pack_id,
                        rollout_index,
                        request.request_id,
                        "evidence",
                        "policy_spec_mismatch",
                        "policy_spec",
                    )
                )
                continue
            try:
                record = run_task_episode(
                    prepared,
                    task_path,
                    entry.task_pack_id,
                    policy_driver=driver,
                    rollout_index=rollout_index,
                    instance_root=runtime / request.request_id,
                )
            except Exception as exc:
                failure = _pre_input_failure(exc)
                if failure is None:
                    raise
                owner, code = failure
                results.append(
                    _blocked(
                        entry.task_pack_id,
                        rollout_index,
                        request.request_id,
                        owner,
                        code,
                        "episode_pre_input",
                    )
                )
                if owner in _TRUST_OWNERS:
                    stopped_tasks[entry.task_pack_id] = (owner, code)
                continue
            if record.request != request:
                results.append(
                    _blocked(
                        entry.task_pack_id,
                        rollout_index,
                        request.request_id,
                        "evidence",
                        "episode_request_mismatch",
                        "episode_result",
                    )
                )
                continue
            # Publication failure aborts immediately; no final manifest or fake remainder.
            write_episode_bundle(root, record)
            records.append(record)
            results.append(_episode_result(record))
            abstain_owner = record.reward.abstain_owner
            abstain_code = record.reward.abstain_code
            if abstain_owner in _TRUST_OWNERS and abstain_code is not None:
                stopped_tasks[entry.task_pack_id] = (abstain_owner, abstain_code)

    manifest = EpisodeBatchManifest(
        expected_corpus_id,
        corpus_release_id,
        policy_spec.policy_id,
        rollouts_per_task,
        tuple(results),
        _aggregates(tuple(records), tuple(results)),
    )
    _write_manifest(root, manifest)
    return _cold_check_manifest(root, manifest)


def _read_corpus(path: Path, expected_corpus_id: str) -> CorpusManifest:
    document = read_identity_artifact(Path(path), expected_corpus_id)
    if (
        set(document)
        != {
            "format",
            "policy",
            "seed",
            "entries",
            "selection_evidence_digest",
            "corpus_id",
        }
        or document.get("format") != "corpus-manifest/1"
    ):
        raise AssessmentError("CorpusManifest has an invalid current shape")
    policy_document = _object(document.get("policy"), "CorpusPolicy")
    if (
        set(policy_document)
        != {
            "format",
            "purpose",
            "minimum_reliability",
            "max_tasks",
        }
        or policy_document.get("format") != "corpus-policy/1"
    ):
        raise AssessmentError("CorpusPolicy has an invalid current shape")
    raw_entries = document.get("entries")
    if not isinstance(raw_entries, list):
        raise AssessmentError("CorpusManifest entries must be an array")
    entries: list[CorpusSelectionCandidate] = []
    for value in raw_entries:
        item = _object(value, "CorpusManifest entry")
        if set(item) != {
            "task_pack_id",
            "assessment_id",
            "release_id",
            "goal_kind",
            "structure_id",
            "reliability",
        }:
            raise AssessmentError("CorpusManifest entry has an invalid current shape")
        entries.append(
            CorpusSelectionCandidate(
                cast(str, item["task_pack_id"]),
                cast(str, item["assessment_id"]),
                cast(str, item["release_id"]),
                cast(Any, item["goal_kind"]),
                cast(str, item["structure_id"]),
                cast(float, item["reliability"]),
            )
        )
    corpus = CorpusManifest(
        CorpusPolicy(
            cast(Any, policy_document["purpose"]),
            cast(float, policy_document["minimum_reliability"]),
            cast(int | None, policy_document["max_tasks"]),
        ),
        cast(int, document["seed"]),
        tuple(entries),
        cast(str, document["selection_evidence_digest"]),
    )
    if corpus.to_document() != document:
        raise AssessmentError("CorpusManifest differs from its current projection")
    return corpus


def _task_path(root: Path, entry: CorpusSelectionCandidate) -> Path:
    filename = _PACK_FILENAMES[entry.goal_kind]
    return root / "batch" / "taskpacks" / entry.task_pack_id / filename


def _artifact_code(exc: Exception) -> str:
    if isinstance(exc, TaskFoundryError):
        return exc.code
    if isinstance(exc, SemanticsContractError):
        return "task_semantics_contract_invalid"
    if isinstance(exc, PreparationContractError):
        return "task_preparation_contract_invalid"
    return "task_authority_invalid"


def _pre_input_failure(exc: Exception) -> tuple[DefectOwner, str] | None:
    if isinstance(exc, TaskFoundryError):
        return "semantics", exc.code
    if isinstance(exc, PreparationExecutionError):
        owners: dict[str, DefectOwner] = {
            "EnvironmentDefect": "environment",
            "InfrastructureFailure": "infrastructure",
            "SemanticsDefect": "semantics",
            "VerifierDefect": "verifier",
        }
        return owners[exc.kind], exc.code
    if isinstance(exc, PreparationContractError):
        return "evidence", "preparation_contract_error"
    if isinstance(exc, SemanticsContractError):
        return "semantics", "semantics_contract_error"
    if isinstance(exc, OSError):
        return "infrastructure", "infrastructure_io_error"
    if isinstance(exc, ImportError):
        return "infrastructure", "infrastructure_import_error"
    return None


def _blocked(
    task_pack_id: str,
    rollout_index: int,
    request_id: str | None,
    owner: DefectOwner,
    code: str,
    phase: str,
) -> JSONObject:
    return _result(
        {
            "task_pack_id": task_pack_id,
            "rollout_index": rollout_index,
            "request_id": request_id,
            "episode_id": None,
            "blocked_owner": owner,
            "blocked_code": code,
            "blocked_phase": phase,
        }
    )


def _episode_result(record: EpisodeRecord) -> JSONObject:
    return _result(
        {
            "task_pack_id": record.request.task_pack_id,
            "rollout_index": record.request.rollout_index,
            "request_id": record.request.request_id,
            "episode_id": record.episode_id,
            "blocked_owner": None,
            "blocked_code": None,
            "blocked_phase": None,
        }
    )


def _aggregates(
    records: tuple[EpisodeRecord, ...],
    results: tuple[JSONObject, ...],
) -> JSONObject:
    counts = {"verified_success": 0, "verified_failure": 0, "abstain": 0}
    attempted = dispatched = provider_turns = 0
    input_tokens = output_tokens = missing_usage = elapsed = 0
    abstain_owners: dict[str, int] = {}
    blocked_owners: dict[str, int] = {}
    for record in records:
        counts[record.reward.disposition] += 1
        elapsed += record.policy_elapsed_ms
        provider_turns += len(record.capture.turns)
        for turn in record.capture.turns:
            attempted += len(turn.calls)
            dispatched += sum(call.dispatch_status == "dispatched" for call in turn.calls)
            if turn.usage is None:
                missing_usage += 1
                continue
            for field, target in (("input_tokens", "input"), ("output_tokens", "output")):
                value = turn.usage.get(field)
                if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                    if target == "input":
                        input_tokens += value
                    else:
                        output_tokens += value
        if record.reward.abstain_owner is not None:
            owner = record.reward.abstain_owner
            abstain_owners[owner] = abstain_owners.get(owner, 0) + 1
    for result in results:
        blocked_owner = result["blocked_owner"]
        if isinstance(blocked_owner, str):
            blocked_owners[blocked_owner] = blocked_owners.get(blocked_owner, 0) + 1
    blocked_count = sum(item["episode_id"] is None for item in results)
    return {
        "total_slots": len(results),
        "episode_count": len(records),
        "blocked_count": blocked_count,
        **counts,
        "attempted_calls": attempted,
        "dispatched_calls": dispatched,
        "provider_turns": provider_turns,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "missing_usage_turns": missing_usage,
        "policy_elapsed_ms": elapsed,
        "abstain_owner_counts": {owner: abstain_owners[owner] for owner in sorted(abstain_owners)},
        "blocked_owner_counts": {owner: blocked_owners[owner] for owner in sorted(blocked_owners)},
    }


def _write_manifest(root: Path, manifest: EpisodeBatchManifest) -> None:
    directory = root / "batches" / manifest.batch_id
    if directory.exists() or directory.is_symlink():
        raise ValueError("Episode batch manifest directory must be absent")
    directory.mkdir(parents=True)
    (directory / "EpisodeBatchManifest.json").write_bytes(canonical_bytes(manifest.to_document()))


def _cold_check_manifest(
    root: Path,
    expected: EpisodeBatchManifest,
) -> EpisodeBatchManifest:
    batches = root / "batches"
    directory = batches / expected.batch_id
    path = directory / "EpisodeBatchManifest.json"
    if (
        root.is_symlink()
        or batches.is_symlink()
        or directory.is_symlink()
        or path.is_symlink()
        or not root.is_dir()
        or not batches.is_dir()
        or not directory.is_dir()
        or not path.is_file()
        or {item.name for item in directory.iterdir()} != {path.name}
    ):
        raise ValueError("Episode batch manifest directory is invalid")
    try:
        payload = path.read_bytes()
        raw = json.loads(payload)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError("EpisodeBatchManifest is unreadable") from exc
    if not is_json_object(raw) or payload != canonical_bytes(raw):
        raise ValueError("EpisodeBatchManifest is not canonical JSON")
    document = cast(JSONObject, raw)
    manifest = _decode_manifest(document)
    if manifest.to_document() != document or manifest != expected:
        raise ValueError("EpisodeBatchManifest differs from the executed batch")

    records: list[EpisodeRecord] = []
    for result in manifest.results:
        episode_id = result["episode_id"]
        if not isinstance(episode_id, str):
            continue
        record, _view = _read_episode_bundle_pair(root, episode_id)
        if (
            record.request.request_id != result["request_id"]
            or record.request.release_id != manifest.release_id
            or record.request.policy_id != manifest.policy_id
            or record.request.task_pack_id != result["task_pack_id"]
            or record.request.rollout_index != result["rollout_index"]
        ):
            raise ValueError("Episode batch result differs from its persisted Episode")
        records.append(record)
    if _aggregates(tuple(records), manifest.results) != manifest.aggregates:
        raise ValueError("Episode batch aggregates differ from retained results")
    return manifest


def _decode_manifest(value: JSONObject) -> EpisodeBatchManifest:
    if (
        set(value)
        != {
            "format",
            "corpus_id",
            "release_id",
            "policy_id",
            "rollouts_per_task",
            "results",
            "aggregates",
            "batch_id",
        }
        or value.get("format") != "episode-batch-manifest/1"
    ):
        raise ValueError("EpisodeBatchManifest has an invalid current shape")
    raw_results = value.get("results")
    if not isinstance(raw_results, list):
        raise ValueError("EpisodeBatchManifest results must be an array")
    return EpisodeBatchManifest(
        cast(str, value["corpus_id"]),
        cast(str, value["release_id"]),
        cast(str, value["policy_id"]),
        cast(int, value["rollouts_per_task"]),
        tuple(_object(item, "batch result") for item in raw_results),
        _object(value.get("aggregates"), "aggregates"),
        cast(str, value["batch_id"]),
    )


def _result(value: Any) -> JSONObject:
    item = _object(value, "batch result")
    if set(item) != _RESULT_KEYS:
        raise ValueError("batch result has invalid fields")
    _digest(item.get("task_pack_id"), "batch result task_pack_id")
    _positive(item.get("rollout_index"), "batch result rollout_index")
    for field in ("request_id", "episode_id"):
        candidate = item.get(field)
        if candidate is not None:
            _digest(candidate, f"batch result {field}")
    owner = item.get("blocked_owner")
    if owner is not None and owner not in _OWNERS:
        raise ValueError("batch result blocked_owner is invalid")
    code, phase = item.get("blocked_code"), item.get("blocked_phase")
    if item.get("episode_id") is not None:
        if item.get("request_id") is None or any(
            item.get(field) is not None
            for field in ("blocked_owner", "blocked_code", "blocked_phase")
        ):
            raise ValueError("Episode batch result cannot also be blocked")
    elif owner not in _OWNERS or not _is_text(code) or not _is_text(phase):
        raise ValueError("blocked batch result requires owner, code, and phase")
    return item


def _validate_aggregates(value: JSONObject, result_count: int) -> None:
    if set(value) != _AGGREGATE_KEYS:
        raise ValueError("batch aggregates have invalid fields")
    count_fields = _AGGREGATE_KEYS - {"abstain_owner_counts", "blocked_owner_counts"}
    for field in count_fields:
        _nonnegative(value.get(field), f"batch aggregate {field}")
    if value["total_slots"] != result_count:
        raise ValueError("batch total_slots differs from results")
    if cast(int, value["episode_count"]) + cast(int, value["blocked_count"]) != result_count:
        raise ValueError("batch episode and blocked counts differ from results")
    if cast(int, value["verified_success"]) + cast(int, value["verified_failure"]) + cast(
        int, value["abstain"]
    ) != cast(int, value["episode_count"]):
        raise ValueError("batch disposition counts differ from episode_count")
    for field in ("abstain_owner_counts", "blocked_owner_counts"):
        counts = _object(value.get(field), field)
        if any(owner not in _OWNERS for owner in counts):
            raise ValueError(f"{field} contains an invalid owner")
        for owner, count in counts.items():
            _nonnegative(count, f"{field} {owner}")


def _object(value: Any, role: str) -> JSONObject:
    if not is_json_object(value):
        raise ValueError(f"{role} must be a JSON object")
    try:
        copied = json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{role} must be canonical JSON") from exc
    if not is_json_object(copied):
        raise ValueError(f"{role} must be a JSON object")
    return cast(JSONObject, copied)


def _document_digest(value: JSONObject) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _digest(value: Any, role: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in _HEX for character in value)
    ):
        raise ValueError(f"{role} must be a sha256 digest")


def _positive(value: Any, role: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{role} must be a positive integer")


def _nonnegative(value: Any, role: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{role} must be a nonnegative integer")


def _is_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


__all__ = ["EpisodeBatchManifest", "run_episode_batch"]
