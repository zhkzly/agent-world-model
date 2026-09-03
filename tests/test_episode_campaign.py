from __future__ import annotations

from pathlib import Path

import pytest

from agent_env_foundry.episode_batch_v2 import EpisodeSlotResult
from agent_env_foundry.episode_campaign import (
    campaign_config,
    load_slot_results,
    write_slot_result,
)
from agent_env_foundry.episodes import EpisodeRequest, PolicySpec
from agent_env_foundry.public_agent import PUBLIC_AGENT_PROMPT_DIGEST


def _policy() -> PolicySpec:
    return PolicySpec(
        "gpt-5.6-luna",
        "openai-responses",
        "1",
        "responses:local-8317",
        PUBLIC_AGENT_PROMPT_DIGEST,
        24,
    )


def _request(index: int) -> EpisodeRequest:
    return EpisodeRequest(
        "a" * 64,
        f"{index:x}" * 64,
        f"{index + 8:x}" * 64,
        _policy().policy_id,
        1,
    )


def test_campaign_identity_binds_semantics_but_not_worker_scheduling() -> None:
    first = campaign_config(
        source_commit="a" * 40,
        s1_campaign_id="b" * 64,
        corpus_manifest_id="c" * 64,
        policy=_policy(),
        rollouts_per_task=8,
    )
    second = campaign_config(
        source_commit="a" * 40,
        s1_campaign_id="b" * 64,
        corpus_manifest_id="c" * 64,
        policy=_policy(),
        rollouts_per_task=8,
    )

    assert first == second
    assert first["format"] == "s3-episode-campaign-config/1"
    assert first["rollouts_per_task"] == 8
    assert "workers" not in first
    assert len(first["campaign_id"]) == 64


def test_terminal_slot_records_resume_exactly_and_reject_conflicts(tmp_path: Path) -> None:
    first = EpisodeSlotResult.episode(_request(1), "1" * 64, "verified_success", 1.0)
    second = EpisodeSlotResult.blocked(
        _request(2),
        "infrastructure",
        "credential_missing",
        phase="policy_start",
        details={"original_code": "AuthenticationError"},
    )
    write_slot_result(tmp_path, first)
    write_slot_result(tmp_path, second)

    loaded = load_slot_results(tmp_path)
    assert loaded == {
        first.request.request_id: first,
        second.request.request_id: second,
    }
    write_slot_result(tmp_path, first)
    with pytest.raises(ValueError, match="conflict"):
        write_slot_result(
            tmp_path,
            EpisodeSlotResult.episode(first.request, "9" * 64, "verified_success", 1.0),
        )
