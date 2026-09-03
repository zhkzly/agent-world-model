from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import replace
from pathlib import Path

import pytest

from agent_env_foundry.episode_artifacts import (
    EpisodeRecord,
    read_episode_bundle,
    training_view,
    write_episode_bundle,
)
from agent_env_foundry.episodes import (
    EpisodeDefect,
    EpisodeRequest,
    EpisodeToolCall,
    PolicyCompletion,
    PolicySpec,
    PolicyTurn,
    PublicEpisodeCapture,
    PublicEpisodeInput,
    RewardOutcome,
)
from agent_env_foundry.release import canonical_bytes
from agent_env_foundry.task_goal import EvaluationResult

DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
DIGEST_C = "c" * 64
DIGEST_D = "d" * 64


def _policy(system_prompt: str) -> PolicySpec:
    return PolicySpec(
        "gpt-5.6-luna",
        "openai-responses",
        "1",
        "responses:local-8317",
        hashlib.sha256(system_prompt.encode()).hexdigest(),
        12,
    )


def _public_input(system_prompt: str) -> PublicEpisodeInput:
    return PublicEpisodeInput(
        system_prompt,
        "Inspect item-001 and report its status.",
        {"item_id": "item-001"},
        (
            {
                "name": "inspect_item",
                "description": "Inspect one item.",
                "input_schema": {
                    "type": "object",
                    "properties": {"item_id": {"type": "string"}},
                    "required": ["item_id"],
                    "additionalProperties": False,
                },
                "output_schema": {
                    "type": "object",
                    "properties": {
                        "item_id": {"type": "string"},
                        "status": {"type": "string"},
                    },
                    "required": ["item_id", "status"],
                    "additionalProperties": False,
                },
            },
        ),
        {
            "type": "object",
            "properties": {"status": {"type": "string"}},
            "required": ["status"],
            "additionalProperties": False,
        },
    )


def _capture(system_prompt: str, *, terminal_code: str | None = None) -> PublicEpisodeCapture:
    observation = {
        "ok": True,
        "data": {"item_id": "item-001", "status": "available"},
        "error": None,
    }
    call = EpisodeToolCall(
        "call-1",
        "inspect_item",
        "call-1",
        "inspect_item",
        '{"item_id":"item-001"}',
        {"item_id": "item-001"},
        "valid",
        "valid",
        "dispatched",
        observation,
    )
    completion = (
        PolicyCompletion("completed", {"status": "available"}, None)
        if terminal_code is None
        else PolicyCompletion("policy_failure", None, terminal_code)
    )
    return PublicEpisodeCapture(
        _public_input(system_prompt),
        (
            PolicyTurn(1, (call,), None, {"input_tokens": 20, "output_tokens": 8}),
            PolicyTurn(
                2,
                (),
                '{"status":"available"}' if terminal_code is None else None,
                {"input_tokens": 30, "output_tokens": 5},
            ),
        ),
        completion,
        None,
    )


def _evaluation(passed: bool) -> EvaluationResult:
    return EvaluationResult(
        passed,
        True,
        True,
        passed,
        passed,
        passed,
        passed,
        ("reset", "before_state", "after_state", "answer_schema", "answer", "goal"),
        () if passed else ("after_state_mismatch",),
    )


def _record(*, passed: bool = True) -> EpisodeRecord:
    prompt = "Use only public tools."
    policy = _policy(prompt)
    request = EpisodeRequest(DIGEST_A, DIGEST_B, DIGEST_C, policy.policy_id, 1)
    return EpisodeRecord(
        request=request,
        policy=policy,
        materialization_id=DIGEST_D,
        capture=_capture(prompt, terminal_code=None if passed else "final_answer_invalid"),
        before_state={"items": [{"id": "item-001", "status": "available"}]},
        post_reopen_state={
            "items": [{"id": "item-001", "status": "available" if passed else "missing"}]
        },
        evaluation=_evaluation(passed),
        verification_defect=None,
        reward=RewardOutcome(
            "verified_success" if passed else "verified_failure",
            1.0 if passed else 0.0,
            None,
            None,
        ),
    )


def test_episode_record_and_training_view_are_current_and_non_leaking() -> None:
    record = _record()
    view = training_view(record)

    assert record.to_document()["format"] == "episode-record/3"
    assert view.to_document()["format"] == "training-episode-view/2"
    assert record.episode_id == hashlib.sha256(canonical_bytes(record.preimage())).hexdigest()
    assert view.episode_id == record.episode_id
    assert view.reward == 1.0
    assert "usage" in record.to_document()["capture"]["turns"][0]
    public = view.to_document()
    assert "before_state" not in public
    assert "post_reopen_state" not in public
    assert "evaluation" not in public
    assert "verification_defect" not in public
    assert "usage" not in public["turns"][0]
    encoded = json.dumps(public, sort_keys=True)
    for forbidden in ("expected_answer", "goal_truth", "sampling_evidence", "filter_evidence"):
        assert forbidden not in encoded


def test_episode_record_reward_must_follow_capture_evaluation_and_defects() -> None:
    success = _record()
    with pytest.raises(ValueError, match="reward"):
        replace(success, reward=RewardOutcome("verified_failure", 0.0, None, None))

    failed = _record(passed=False)
    assert failed.reward.reward == 0.0
    with pytest.raises(ValueError, match="reward"):
        replace(failed, reward=RewardOutcome("verified_success", 1.0, None, None))

    defect = EpisodeDefect("provider", "remote_429", "policy_driver_response")
    capture = replace(success.capture, completion=None, defect=defect)
    abstained = replace(
        success,
        capture=capture,
        reward=RewardOutcome("abstain", None, "provider", "remote_429"),
    )
    assert abstained.reward.reward is None
    with pytest.raises(ValueError, match="reward"):
        replace(abstained, reward=RewardOutcome("verified_failure", 0.0, None, None))


def test_episode_bundle_cold_reads_after_relocation_and_rejects_mutation(tmp_path: Path) -> None:
    record = _record()
    store = tmp_path / "store"
    store.mkdir()
    path = write_episode_bundle(store, record)

    view = read_episode_bundle(store, record.episode_id)
    assert view == training_view(record)
    relocated = tmp_path / "relocated"
    relocated.mkdir()
    shutil.copytree(path, relocated / "episodes" / record.episode_id)
    assert read_episode_bundle(relocated, record.episode_id) == view

    record_path = relocated / "episodes" / record.episode_id / "EpisodeRecord.json"
    document = json.loads(record_path.read_text())
    document["post_reopen_state"]["items"][0]["status"] = "tampered"
    record_path.write_bytes(canonical_bytes(document))
    with pytest.raises(ValueError, match="identity|projection|reward"):
        read_episode_bundle(relocated, record.episode_id)


def test_episode_bundle_rejects_old_format_and_independently_mutated_view(tmp_path: Path) -> None:
    record = _record()
    store = tmp_path / "store"
    store.mkdir()
    path = write_episode_bundle(store, record)
    record_path = path / "EpisodeRecord.json"

    old = json.loads(record_path.read_text())
    old["format"] = "episode-record/2"
    record_path.write_bytes(canonical_bytes(old))
    with pytest.raises(ValueError, match="unsupported"):
        read_episode_bundle(store, record.episode_id)

    shutil.rmtree(path)
    path = write_episode_bundle(store, record)
    public = json.loads((path / "TrainingEpisodeView.json").read_text())
    public["trusted_state"] = {"leak": True}
    (path / "TrainingEpisodeView.json").write_bytes(canonical_bytes(public))
    with pytest.raises(ValueError, match="projection"):
        read_episode_bundle(store, record.episode_id)
