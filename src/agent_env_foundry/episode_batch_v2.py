"""Multi-Release S3 Episode slot and final batch contracts."""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

from agent_env_foundry.environment import JSONObject, JSONValue
from agent_env_foundry.episode_artifacts import (
    episode_request_from_document,
    policy_spec_from_document,
)
from agent_env_foundry.episodes import EpisodeRequest, PolicySpec
from agent_env_foundry.jsonvalue import is_json_object, is_json_value
from agent_env_foundry.release import canonical_bytes

SLOT_RESULT_FORMAT = "episode-slot-result/1"
BATCH_MANIFEST_FORMAT = "episode-batch-manifest/2"

EpisodeDisposition = Literal["verified_success", "verified_failure", "abstain"]
BlockedOwner = Literal["provider", "infrastructure", "environment", "task_artifact", "evidence"]

_DISPOSITIONS = frozenset({"verified_success", "verified_failure", "abstain"})
_BLOCKED_OWNERS = frozenset(
    {"provider", "infrastructure", "environment", "task_artifact", "evidence"}
)


@dataclass(frozen=True, slots=True)
class EpisodeSlotResult:
    request: EpisodeRequest
    episode_id: str | None
    disposition: EpisodeDisposition | None
    reward: float | None
    blocked_owner: BlockedOwner | None
    blocked_code: str | None
    blocked_phase: str | None
    blocked_details: JSONObject | None

    def __post_init__(self) -> None:
        if not isinstance(self.request, EpisodeRequest):
            raise ValueError("slot result requires an EpisodeRequest")
        if self.episode_id is not None:
            _digest(self.episode_id, "episode_id")
            if any(
                value is not None
                for value in (
                    self.blocked_owner,
                    self.blocked_code,
                    self.blocked_phase,
                    self.blocked_details,
                )
            ):
                raise ValueError("Episode slot cannot also be blocked")
            _episode_reward(self.disposition, self.reward)
            return
        if self.disposition is not None or self.reward is not None:
            raise ValueError("blocked slot cannot claim an Episode disposition or reward")
        if (
            self.blocked_owner not in _BLOCKED_OWNERS
            or not self.blocked_code
            or not self.blocked_phase
            or not is_json_object(self.blocked_details)
        ):
            raise ValueError("blocked slot requires a supported owner, code, phase and details")
        object.__setattr__(
            self, "blocked_details", _copy_object(cast(JSONObject, self.blocked_details))
        )

    @classmethod
    def episode(
        cls,
        request: EpisodeRequest,
        episode_id: str,
        disposition: EpisodeDisposition,
        reward: float | None,
    ) -> EpisodeSlotResult:
        return cls(request, episode_id, disposition, reward, None, None, None, None)

    @classmethod
    def blocked(
        cls,
        request: EpisodeRequest,
        owner: BlockedOwner,
        code: str,
        *,
        phase: str = "unspecified",
        details: JSONObject | None = None,
    ) -> EpisodeSlotResult:
        return cls(request, None, None, None, owner, code, phase, details or {})

    @property
    def terminal(self) -> Literal["episode", "blocked"]:
        return "episode" if self.episode_id is not None else "blocked"

    def preimage(self) -> JSONObject:
        return {
            "format": SLOT_RESULT_FORMAT,
            "request": self.request.to_document(),
            "request_id": self.request.request_id,
            "terminal": self.terminal,
            "episode_id": self.episode_id,
            "disposition": self.disposition,
            "reward": self.reward,
            "blocked_owner": self.blocked_owner,
            "blocked_code": self.blocked_code,
            "blocked_phase": self.blocked_phase,
            "blocked_details": (
                None if self.blocked_details is None else _copy_object(self.blocked_details)
            ),
        }

    @property
    def record_id(self) -> str:
        return _document_digest(self.preimage())

    def to_document(self) -> JSONObject:
        return {**self.preimage(), "record_id": self.record_id}


@dataclass(frozen=True, slots=True)
class EpisodeBatchManifest:
    s1_campaign_id: str
    corpus_manifest_id: str
    policy: PolicySpec
    rollouts_per_task: int
    results: tuple[JSONObject, ...]
    aggregates: JSONObject

    def __post_init__(self) -> None:
        _digest(self.s1_campaign_id, "s1_campaign_id")
        _digest(self.corpus_manifest_id, "corpus_manifest_id")
        if not isinstance(self.policy, PolicySpec):
            raise ValueError("batch policy must be a PolicySpec")
        _positive(self.rollouts_per_task, "rollouts_per_task")
        if not isinstance(self.results, tuple) or any(
            not is_json_object(item) for item in self.results
        ):
            raise ValueError("batch results must be JSON objects")
        if not is_json_object(self.aggregates):
            raise ValueError("batch aggregates must be a JSON object")
        object.__setattr__(self, "results", tuple(_copy_object(item) for item in self.results))
        object.__setattr__(self, "aggregates", _copy_object(self.aggregates))

    def preimage(self) -> JSONObject:
        return {
            "format": BATCH_MANIFEST_FORMAT,
            "s1_campaign_id": self.s1_campaign_id,
            "corpus_manifest_id": self.corpus_manifest_id,
            "policy": self.policy.to_document(),
            "rollouts_per_task": self.rollouts_per_task,
            "results": [_copy_object(item) for item in self.results],
            "aggregates": _copy_object(self.aggregates),
        }

    @property
    def batch_id(self) -> str:
        return _document_digest(self.preimage())

    def to_document(self) -> JSONObject:
        return {**self.preimage(), "batch_id": self.batch_id}


def build_episode_batch_manifest(
    s1_campaign_id: str,
    corpus_manifest_id: str,
    policy: PolicySpec,
    rollouts_per_task: int,
    requests: tuple[EpisodeRequest, ...],
    results: tuple[EpisodeSlotResult, ...],
) -> EpisodeBatchManifest:
    """Build one exact complete manifest independent of worker completion order."""

    _digest(s1_campaign_id, "s1_campaign_id")
    _digest(corpus_manifest_id, "corpus_manifest_id")
    if not isinstance(policy, PolicySpec):
        raise ValueError("policy must be a PolicySpec")
    _positive(rollouts_per_task, "rollouts_per_task")
    if not isinstance(requests, tuple) or any(
        not isinstance(item, EpisodeRequest) for item in requests
    ):
        raise ValueError("requests must contain EpisodeRequest values")
    if not isinstance(results, tuple) or any(
        not isinstance(item, EpisodeSlotResult) for item in results
    ):
        raise ValueError("results must contain EpisodeSlotResult values")
    request_ids = [item.request_id for item in requests]
    if len(request_ids) != len(set(request_ids)):
        raise ValueError("requests contain a duplicate slot")
    _validate_request_grid(requests, policy, rollouts_per_task)
    result_ids = [item.request.request_id for item in results]
    if len(result_ids) != len(set(result_ids)):
        raise ValueError("results contain a duplicate slot")
    if set(result_ids) != set(request_ids):
        raise ValueError(
            "results do not cover the exact requested slots; a slot is missing or extra"
        )
    ordered = tuple(sorted(results, key=lambda item: item.request.request_id))
    counts = Counter(item.terminal for item in ordered)
    dispositions = Counter(item.disposition for item in ordered if item.disposition is not None)
    aggregates: JSONObject = {
        "requested": len(requests),
        "episodes": counts["episode"],
        "verified_success": dispositions["verified_success"],
        "verified_failure": dispositions["verified_failure"],
        "abstain": dispositions["abstain"],
        "blocked": counts["blocked"],
    }
    return EpisodeBatchManifest(
        s1_campaign_id,
        corpus_manifest_id,
        policy,
        rollouts_per_task,
        tuple(item.to_document() for item in ordered),
        aggregates,
    )


def write_episode_batch_manifest(output_root: Path, manifest: EpisodeBatchManifest) -> Path:
    root = _ordinary_directory(Path(output_root), "output_root")
    if not isinstance(manifest, EpisodeBatchManifest):
        raise TypeError("manifest must be an EpisodeBatchManifest")
    path = root / "EpisodeBatchManifest.json"
    if path.exists() or path.is_symlink():
        raise ValueError("EpisodeBatchManifest destination must be new")
    path.write_bytes(canonical_bytes(manifest.to_document()))
    if read_episode_batch_manifest(path, manifest.batch_id) != manifest:
        raise ValueError("written EpisodeBatchManifest differs from its projection")
    return path


def read_episode_batch_manifest(path: Path, expected_batch_id: str) -> EpisodeBatchManifest:
    _digest(expected_batch_id, "expected_batch_id")
    document = _read_canonical(Path(path), "EpisodeBatchManifest")
    value = _exact(
        document,
        {
            "format",
            "s1_campaign_id",
            "corpus_manifest_id",
            "policy",
            "rollouts_per_task",
            "results",
            "aggregates",
            "batch_id",
        },
        "EpisodeBatchManifest",
    )
    if value["format"] != BATCH_MANIFEST_FORMAT:
        raise ValueError("EpisodeBatchManifest format is unsupported")
    raw_results = _array(value["results"], "batch results")
    results = tuple(slot_result_from_document(item) for item in raw_results)
    policy = policy_spec_from_document(value["policy"])
    requests = tuple(item.request for item in results)
    rebuilt = build_episode_batch_manifest(
        cast(str, value["s1_campaign_id"]),
        cast(str, value["corpus_manifest_id"]),
        policy,
        cast(int, value["rollouts_per_task"]),
        requests,
        results,
    )
    if (
        value["aggregates"] != rebuilt.aggregates
        or value["batch_id"] != rebuilt.batch_id
        or expected_batch_id != rebuilt.batch_id
        or value != rebuilt.to_document()
    ):
        raise ValueError("EpisodeBatchManifest identity, aggregate or projection is invalid")
    return rebuilt


def slot_result_from_document(document: Any) -> EpisodeSlotResult:
    value = _exact(
        document,
        {
            "format",
            "request",
            "request_id",
            "terminal",
            "episode_id",
            "disposition",
            "reward",
            "blocked_owner",
            "blocked_code",
            "blocked_phase",
            "blocked_details",
            "record_id",
        },
        "EpisodeSlotResult",
    )
    if value["format"] != SLOT_RESULT_FORMAT:
        raise ValueError("EpisodeSlotResult format is unsupported")
    request = episode_request_from_document(value["request"])
    reward = value["reward"]
    if type(reward) is int and reward in {0, 1}:
        reward = float(reward)
    result = EpisodeSlotResult(
        request,
        cast(str | None, value["episode_id"]),
        cast(Any, value["disposition"]),
        cast(float | None, reward),
        cast(Any, value["blocked_owner"]),
        cast(str | None, value["blocked_code"]),
        cast(str | None, value["blocked_phase"]),
        cast(JSONObject | None, value["blocked_details"]),
    )
    if (
        value["terminal"] != result.terminal
        or value["request_id"] != request.request_id
        or value["record_id"] != result.record_id
        or value != result.to_document()
    ):
        raise ValueError("EpisodeSlotResult identity or projection is invalid")
    return result


def _validate_request_grid(
    requests: tuple[EpisodeRequest, ...], policy: PolicySpec, rollouts_per_task: int
) -> None:
    groups: dict[str, list[EpisodeRequest]] = defaultdict(list)
    for request in requests:
        if request.policy_id != policy.policy_id:
            raise ValueError("request policy differs from batch policy")
        groups[request.task_pack_id].append(request)
    expected = list(range(1, rollouts_per_task + 1))
    for group in groups.values():
        if sorted(item.rollout_index for item in group) != expected:
            raise ValueError("request grid does not contain every exact rollout index")
        if len({(item.release_id, item.task_id) for item in group}) != 1:
            raise ValueError("one TaskPack request grid has inconsistent authority")


def _episode_reward(disposition: EpisodeDisposition | None, reward: float | None) -> None:
    if disposition not in _DISPOSITIONS:
        raise ValueError("Episode slot disposition is invalid")
    expected = {
        "verified_success": 1.0,
        "verified_failure": 0.0,
        "abstain": None,
    }[disposition]
    if reward != expected or (expected is not None and type(reward) is not float):
        raise ValueError("Episode slot reward contradicts disposition")


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


def _exact(document: Any, keys: set[str], role: str) -> JSONObject:
    if not is_json_object(document) or set(document) != keys:
        raise ValueError(f"{role} has an invalid exact shape")
    return cast(JSONObject, document)


def _array(value: Any, role: str) -> list[JSONValue]:
    if not isinstance(value, list) or not all(is_json_value(item) for item in value):
        raise ValueError(f"{role} must be a JSON array")
    return cast(list[JSONValue], value)


def _copy_object(value: JSONObject) -> JSONObject:
    return cast(JSONObject, json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False)))


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


__all__ = [
    "BATCH_MANIFEST_FORMAT",
    "SLOT_RESULT_FORMAT",
    "BlockedOwner",
    "EpisodeBatchManifest",
    "EpisodeDisposition",
    "EpisodeSlotResult",
    "build_episode_batch_manifest",
    "read_episode_batch_manifest",
    "slot_result_from_document",
    "write_episode_batch_manifest",
]
