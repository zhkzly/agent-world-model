from __future__ import annotations

import os
from pathlib import Path
from typing import cast

from agent_env_foundry.episode_runtime_v2 import run_task_episode
from agent_env_foundry.episodes import EpisodeDefect, EpisodeRequest, PolicySpec, PublicEpisodeInput
from agent_env_foundry.preparation_v3 import (
    PreparationSettingsV3,
    prepare_release_v3_internal,
)
from agent_env_foundry.public_agent import (
    PUBLIC_AGENT_PROMPT_DIGEST,
    DriverDecision,
)
from agent_env_foundry.task_admission import (
    PublicTaskView,
    TaskFilterEvidence,
    TaskPackArtifact,
)
from agent_env_foundry.task_candidate import CandidateTask
from agent_env_foundry.task_goal import AtomGoal, GoalTruth
from v3_release_factory import build_v3_release

DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
DIGEST_C = "c" * 64


class ScriptedDriver:
    def __init__(self, decisions: list[DriverDecision], policy: PolicySpec) -> None:
        self.decisions = decisions
        self._policy = policy
        self.started: list[PublicEpisodeInput] = []
        self.closed = 0

    @property
    def policy_spec(self) -> PolicySpec:
        return self._policy

    def start(self, public_input: PublicEpisodeInput) -> None:
        self.started.append(public_input)

    def next_decision(self, _results):
        return self.decisions.pop(0)

    def close(self) -> None:
        self.closed += 1


def _settings() -> PreparationSettingsV3:
    return PreparationSettingsV3(
        Path(os.environ.get("UV_CACHE_DIR", "/tmp/foundry-v3-runtime-uv-cache")),
        120.0,
    )


def _prepared(tmp_path: Path):
    release = build_v3_release(tmp_path / "source")
    return prepare_release_v3_internal(
        release.root,
        tmp_path / "cache",
        settings=_settings(),
    )


def _policy() -> PolicySpec:
    return PolicySpec(
        "scripted-policy",
        "scripted",
        "1",
        "test:scripted",
        PUBLIC_AGENT_PROMPT_DIGEST,
        4,
    )


def _task_pack(release_id: str) -> TaskPackArtifact:
    answer_schema = {
        "type": "object",
        "properties": {"count": {"type": "integer"}},
        "required": ["count"],
        "additionalProperties": False,
    }
    truth = GoalTruth(
        AtomGoal("increment", {"amount": 2}, "transition"),
        {"count": 0},
        {"count": 0},
        {"count": 2},
        {"count": 2},
        answer_schema,
    )
    candidate = CandidateTask(
        release_id,
        DIGEST_A,
        None,
        "Increment the counter by exactly 2 and report the resulting count.",
        truth,
        DIGEST_B,
        DIGEST_C,
        "d" * 64,
    )
    public = PublicTaskView(
        "e" * 64,
        candidate.candidate_id,
        release_id,
        candidate.instruction,
        answer_schema,
    )
    return TaskPackArtifact(
        Path("TaskPack"),
        public.task_pack_id,
        public,
        candidate,
        cast(TaskFilterEvidence, object()),
        {},
    )


def _request(pack: TaskPackArtifact, policy: PolicySpec) -> EpisodeRequest:
    return EpisodeRequest(
        pack.public_view.release_id,
        pack.task_pack_id,
        pack.public_view.task_id,
        policy.policy_id,
        1,
    )


def _call_then_answer(answer: str, policy: PolicySpec) -> ScriptedDriver:
    return ScriptedDriver(
        [
            DriverDecision(calls=(("call-1", "increment", '{"amount":2}'),)),
            DriverDecision(terminal_kind="final_answer", raw_public_terminal=answer),
        ],
        policy,
    )


def test_real_episode_reopens_native_state_and_rewards_correct_answer(tmp_path: Path) -> None:
    prepared = _prepared(tmp_path)
    pack = _task_pack(prepared.identity.release_id)
    policy = _policy()
    driver = _call_then_answer('{"count":2}', policy)

    record = run_task_episode(
        prepared,
        pack,
        _request(pack, policy),
        instance_directory=tmp_path / "instance-success",
        policy_driver=driver,
    )

    assert record.reward.to_document() == {
        "disposition": "verified_success",
        "reward": 1.0,
        "abstain_owner": None,
        "abstain_code": None,
    }
    assert record.before_state == {"count": 0}
    assert record.post_reopen_state == {"count": 2}
    assert record.evaluation is not None and record.evaluation.passed
    assert record.capture.turns[0].calls[0].observation == {
        "ok": True,
        "data": {"count": 2},
        "error": None,
    }
    assert driver.closed == 1


def test_real_episode_rewards_zero_when_state_is_right_but_answer_is_wrong(
    tmp_path: Path,
) -> None:
    prepared = _prepared(tmp_path)
    pack = _task_pack(prepared.identity.release_id)
    policy = _policy()

    record = run_task_episode(
        prepared,
        pack,
        _request(pack, policy),
        instance_directory=tmp_path / "instance-wrong-answer",
        policy_driver=_call_then_answer('{"count":999}', policy),
    )

    assert record.post_reopen_state == {"count": 2}
    assert record.evaluation is not None
    assert not record.evaluation.passed
    assert record.evaluation.after_state
    assert not record.evaluation.answer
    assert record.reward.disposition == "verified_failure"
    assert record.reward.reward == 0.0


def test_real_episode_abstains_on_provider_defect_even_after_correct_mutation(
    tmp_path: Path,
) -> None:
    prepared = _prepared(tmp_path)
    pack = _task_pack(prepared.identity.release_id)
    policy = _policy()
    driver = ScriptedDriver(
        [
            DriverDecision(calls=(("call-1", "increment", '{"amount":2}'),)),
            DriverDecision(
                defect=EpisodeDefect("provider", "remote_429", "policy_driver_response")
            ),
        ],
        policy,
    )

    record = run_task_episode(
        prepared,
        pack,
        _request(pack, policy),
        instance_directory=tmp_path / "instance-provider-defect",
        policy_driver=driver,
    )

    assert record.post_reopen_state == {"count": 2}
    assert record.reward.to_document() == {
        "disposition": "abstain",
        "reward": None,
        "abstain_owner": "provider",
        "abstain_code": "remote_429",
    }
