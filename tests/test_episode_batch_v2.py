from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_env_foundry.episode_batch_v2 import (
    EpisodeSlotResult,
    build_episode_batch_manifest,
    read_episode_batch_manifest,
    write_episode_batch_manifest,
)
from agent_env_foundry.episodes import EpisodeRequest, PolicySpec
from agent_env_foundry.public_agent import PUBLIC_AGENT_PROMPT_DIGEST
from agent_env_foundry.release import canonical_bytes


def _policy() -> PolicySpec:
    return PolicySpec(
        "gpt-5.6-luna",
        "openai-responses",
        "1",
        "responses:local-8317",
        PUBLIC_AGENT_PROMPT_DIGEST,
        24,
    )


def _requests() -> tuple[EpisodeRequest, ...]:
    policy_id = _policy().policy_id
    return tuple(
        EpisodeRequest(release, task_pack, task, policy_id, rollout)
        for release, task_pack, task in (
            ("a" * 64, "c" * 64, "e" * 64),
            ("b" * 64, "d" * 64, "f" * 64),
        )
        for rollout in (1, 2)
    )


def _results() -> tuple[EpisodeSlotResult, ...]:
    requests = _requests()
    return (
        EpisodeSlotResult.episode(requests[0], "1" * 64, "verified_success", 1.0),
        EpisodeSlotResult.episode(requests[1], "2" * 64, "verified_failure", 0.0),
        EpisodeSlotResult.episode(requests[2], "3" * 64, "abstain", None),
        EpisodeSlotResult.blocked(
            requests[3],
            "infrastructure",
            "credential_missing",
            phase="policy_start",
            details={"original_code": "AuthenticationError"},
        ),
    )


def test_batch_manifest_requires_every_exact_slot_and_is_order_independent() -> None:
    requests = _requests()
    results = _results()
    first = build_episode_batch_manifest(
        "7" * 64,
        "8" * 64,
        _policy(),
        2,
        requests,
        results,
    )
    second = build_episode_batch_manifest(
        "7" * 64,
        "8" * 64,
        _policy(),
        2,
        tuple(reversed(requests)),
        tuple(reversed(results)),
    )

    assert first == second
    assert [item["request_id"] for item in first.results] == sorted(
        request.request_id for request in requests
    )
    assert first.aggregates == {
        "requested": 4,
        "episodes": 3,
        "verified_success": 1,
        "verified_failure": 1,
        "abstain": 1,
        "blocked": 1,
    }
    assert first.to_document()["format"] == "episode-batch-manifest/2"
    blocked = next(item for item in first.results if item["terminal"] == "blocked")
    assert blocked["blocked_phase"] == "policy_start"
    assert blocked["blocked_details"] == {"original_code": "AuthenticationError"}

    with pytest.raises(ValueError, match="missing|exact"):
        build_episode_batch_manifest(
            "7" * 64,
            "8" * 64,
            _policy(),
            2,
            requests,
            results[:-1],
        )
    with pytest.raises(ValueError, match="duplicate"):
        build_episode_batch_manifest(
            "7" * 64,
            "8" * 64,
            _policy(),
            2,
            requests,
            (*results[:-1], results[0]),
        )


def test_slot_result_truth_table_is_closed() -> None:
    request = _requests()[0]
    with pytest.raises(ValueError):
        EpisodeSlotResult.episode(request, "1" * 64, "verified_success", 0.0)
    with pytest.raises(ValueError):
        EpisodeSlotResult.episode(request, "1" * 64, "verified_failure", 1.0)
    with pytest.raises(ValueError):
        EpisodeSlotResult.episode(request, "1" * 64, "abstain", 0.0)
    with pytest.raises(ValueError):
        EpisodeSlotResult.blocked(request, "policy", "wrong_answer")


def test_batch_manifest_cold_reads_and_rejects_old_or_changed_bytes(tmp_path: Path) -> None:
    manifest = build_episode_batch_manifest(
        "7" * 64,
        "8" * 64,
        _policy(),
        2,
        _requests(),
        _results(),
    )
    path = write_episode_batch_manifest(tmp_path, manifest)
    assert read_episode_batch_manifest(path, manifest.batch_id) == manifest

    document = json.loads(path.read_text())
    document["format"] = "episode-batch-manifest/1"
    path.write_bytes(canonical_bytes(document))
    with pytest.raises(ValueError, match="unsupported"):
        read_episode_batch_manifest(path, manifest.batch_id)

    path.write_bytes(canonical_bytes(manifest.to_document()))
    document = json.loads(path.read_text())
    document["aggregates"]["verified_success"] = 2
    path.write_bytes(canonical_bytes(document))
    with pytest.raises(ValueError, match="identity|projection|aggregate"):
        read_episode_batch_manifest(path, manifest.batch_id)
