"""Strict current S1/S2 source resolution for multi-Release S3 Episodes."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from agent_env_foundry.environment import JSONObject, JSONValue
from agent_env_foundry.episodes import EpisodeRequest, PolicySpec
from agent_env_foundry.jsonvalue import is_json_object, is_json_value
from agent_env_foundry.release import canonical_bytes, safe_member_path
from agent_env_foundry.release_v3 import verify_release_v3_internal
from agent_env_foundry.task_admission import TaskPackArtifact, load_task_pack

CORPUS_MANIFEST_FORMAT = "task-corpus-manifest/2"
S1_RECORD_FORMAT = "s1-v3-campaign-need-record/1"

_MEMBER_KEYS = {"need_id", "release_id", "task_pack_id", "structure_id", "path"}


@dataclass(frozen=True, slots=True)
class EpisodeSource:
    need_id: str
    release_root: Path
    task_pack: TaskPackArtifact

    def __post_init__(self) -> None:
        _text(self.need_id, "need_id")
        if not isinstance(self.release_root, Path) or not self.release_root.is_dir():
            raise ValueError("release_root must be a directory")

    @property
    def release_id(self) -> str:
        return self.task_pack.public_view.release_id

    @property
    def task_pack_id(self) -> str:
        return self.task_pack.task_pack_id

    @property
    def task_id(self) -> str:
        return self.task_pack.public_view.task_id


def load_episode_sources(
    s1_campaign_root: Path,
    s2_campaign_root: Path,
    *,
    expected_s1_campaign_id: str,
    expected_corpus_manifest_id: str,
) -> tuple[EpisodeSource, ...]:
    """Resolve every current corpus member to one exact TaskPack and Release."""

    _digest(expected_s1_campaign_id, "expected_s1_campaign_id")
    _digest(expected_corpus_manifest_id, "expected_corpus_manifest_id")
    s1_root = _ordinary_directory(Path(s1_campaign_root), "S1 campaign root")
    s2_root = _ordinary_directory(Path(s2_campaign_root), "S2 campaign root")
    manifest = _read_canonical(s2_root / "CorpusManifest.json", "CorpusManifest")
    _exact(
        manifest,
        {"format", "campaign_id", "task_pack_count", "members", "manifest_id"},
        "CorpusManifest",
    )
    if manifest["format"] != CORPUS_MANIFEST_FORMAT:
        raise ValueError("CorpusManifest format is unsupported")
    preimage: JSONObject = {
        "format": manifest["format"],
        "campaign_id": manifest["campaign_id"],
        "task_pack_count": manifest["task_pack_count"],
        "members": manifest["members"],
    }
    if (
        manifest["manifest_id"] != _document_digest(preimage)
        or manifest["manifest_id"] != expected_corpus_manifest_id
    ):
        raise ValueError("CorpusManifest identity differs from expected authority")
    members = _array(manifest["members"], "CorpusManifest members")
    count = manifest["task_pack_count"]
    if isinstance(count, bool) or not isinstance(count, int) or count != len(members):
        raise ValueError("CorpusManifest task_pack_count differs from members")

    records = _load_s1_records(s1_root, expected_s1_campaign_id)
    verified_releases: dict[str, Path] = {}
    sources: list[EpisodeSource] = []
    seen_packs: set[str] = set()
    seen_structures: set[str] = set()
    for raw_member in members:
        member = _exact(raw_member, _MEMBER_KEYS, "CorpusManifest member")
        need_id = _required_text(member["need_id"], "member need_id")
        release_id = _required_digest(member["release_id"], "member release_id")
        task_pack_id = _required_digest(member["task_pack_id"], "member task_pack_id")
        structure_id = _required_digest(member["structure_id"], "member structure_id")
        if task_pack_id in seen_packs or structure_id in seen_structures:
            raise ValueError("CorpusManifest contains duplicate TaskPack or structure identity")
        seen_packs.add(task_pack_id)
        seen_structures.add(structure_id)
        record = records.get(need_id)
        if record is None or record.get("release_id") != release_id:
            raise ValueError("Corpus member release binding has no matching S1 record")
        release_root = _contained_directory(
            s1_root, _required_text(record.get("release_root"), "S1 release_root")
        )
        known_root = verified_releases.get(release_id)
        if known_root is None:
            release = verify_release_v3_internal(release_root)
            if release.release_id != release_id:
                raise ValueError("S1 release bytes differ from the member release binding")
            verified_releases[release_id] = release_root
        elif known_root != release_root:
            raise ValueError("one Release ID resolves to multiple roots")
        task_root = _contained_directory(s2_root, _required_text(member["path"], "TaskPack path"))
        task_pack = load_task_pack(task_root)
        if (
            task_pack.task_pack_id != task_pack_id
            or task_pack.public_view.release_id != release_id
            or task_pack.candidate.release_id != release_id
            or task_pack.candidate.structure_id != structure_id
        ):
            raise ValueError("TaskPack binding differs from the Corpus member")
        sources.append(EpisodeSource(need_id, release_root, task_pack))
    return tuple(sorted(sources, key=lambda item: item.task_pack_id))


def plan_episode_requests(
    sources: tuple[EpisodeSource, ...],
    policy: PolicySpec,
    *,
    rollouts_per_task: int,
) -> tuple[EpisodeRequest, ...]:
    if not isinstance(policy, PolicySpec):
        raise ValueError("policy must be a PolicySpec")
    _positive(rollouts_per_task, "rollouts_per_task")
    if not isinstance(sources, tuple) or any(
        not isinstance(item, EpisodeSource) for item in sources
    ):
        raise ValueError("sources must contain EpisodeSource values")
    requests = tuple(
        EpisodeRequest(
            source.release_id,
            source.task_pack_id,
            source.task_id,
            policy.policy_id,
            rollout_index,
        )
        for source in sorted(sources, key=lambda item: item.task_pack_id)
        for rollout_index in range(1, rollouts_per_task + 1)
    )
    if len({item.request_id for item in requests}) != len(requests):
        raise ValueError("planned Episode requests are not unique")
    return requests


def _load_s1_records(root: Path, expected_campaign_id: str) -> dict[str, JSONObject]:
    records_root = _ordinary_directory(root / "records", "S1 records")
    records: dict[str, JSONObject] = {}
    for path in sorted(records_root.glob("*.json")):
        record = _read_canonical(path, "S1 campaign record")
        if record.get("format") != S1_RECORD_FORMAT:
            raise ValueError("S1 campaign record format is unsupported")
        record_id = record.get("record_id")
        preimage = {key: value for key, value in record.items() if key != "record_id"}
        if record_id != _document_digest(preimage):
            raise ValueError("S1 campaign record identity is invalid")
        if (
            record.get("campaign_id") != expected_campaign_id
            or record.get("terminal") != "released"
        ):
            raise ValueError("S1 campaign record is not an expected released result")
        need_id = _required_text(record.get("need_id"), "S1 need_id")
        _required_digest(record.get("release_id"), "S1 release_id")
        if need_id in records:
            raise ValueError("S1 campaign contains duplicate need_id")
        records[need_id] = record
    if not records:
        raise ValueError("S1 campaign contains no released records")
    return records


def _contained_directory(root: Path, relative: str) -> Path:
    safe = safe_member_path(relative, field="campaign member path")
    selected = root.joinpath(*safe.parts)
    current = selected
    while current != root:
        if current.is_symlink():
            raise ValueError("campaign member path cannot traverse a symlink")
        current = current.parent
    resolved = selected.resolve()
    if not resolved.is_relative_to(root) or not resolved.is_dir():
        raise ValueError("campaign member path must resolve to a contained directory")
    return resolved


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


def _required_text(value: Any, role: str) -> str:
    _text(value, role)
    return cast(str, value)


def _text(value: Any, role: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{role} must be non-empty text")


def _required_digest(value: Any, role: str) -> str:
    _digest(value, role)
    return cast(str, value)


def _digest(value: Any, role: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{role} must be a sha256 digest")


def _positive(value: Any, role: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{role} must be a positive integer")


def _document_digest(document: JSONObject) -> str:
    return hashlib.sha256(canonical_bytes(document)).hexdigest()


__all__ = [
    "CORPUS_MANIFEST_FORMAT",
    "S1_RECORD_FORMAT",
    "EpisodeSource",
    "load_episode_sources",
    "plan_episode_requests",
]
