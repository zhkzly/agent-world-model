"""Execute one current TaskPack as a verified checker-free S3 Episode."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from agent_env_foundry.episode_artifacts import EpisodeRecord
from agent_env_foundry.episodes import (
    EpisodeDefect,
    EpisodeRequest,
    PolicyCompletion,
    RewardOutcome,
)
from agent_env_foundry.public_agent import PolicyDriver, capture_public_episode
from agent_env_foundry.release import canonical_bytes
from agent_env_foundry.task_admission import (
    TaskPackArtifact,
    evaluation_trace_from_capture,
)
from agent_env_foundry.task_goal import EvaluationContext, EvaluationResult, evaluate_goal
from agent_env_foundry.task_proposal import PreparedTaskEnvironment

EpisodeExecutionOwner = Literal["infrastructure", "environment", "task_artifact", "evidence"]


class EpisodeExecutionFailure(RuntimeError):
    """A failure before enough public evidence exists to seal an Episode."""

    def __init__(self, owner: EpisodeExecutionOwner, code: str, phase: str, message: str) -> None:
        super().__init__(message)
        self.owner, self.code, self.phase = owner, code, phase


def run_task_episode(
    prepared: PreparedTaskEnvironment,
    task_pack: TaskPackArtifact,
    request: EpisodeRequest,
    *,
    instance_directory: Path,
    policy_driver: PolicyDriver,
) -> EpisodeRecord:
    """Run, reopen, evaluate and seal one logical policy rollout."""

    _validate_authority(prepared, task_pack, request, policy_driver)
    instance = Path(instance_directory)
    if instance.exists() or instance.is_symlink():
        raise EpisodeExecutionFailure(
            "evidence", "episode_instance_not_fresh", "episode_open", "instance must be new"
        )
    candidate = task_pack.candidate
    try:
        with prepared.open(instance) as session:
            reset = session.actor.reset(candidate.reset_start)
            before = prepared.read_state(instance)
            if not _same(reset, candidate.goal_truth.expected_reset) or not _same(
                before, candidate.goal_truth.expected_before
            ):
                raise EpisodeExecutionFailure(
                    "environment",
                    "episode_start_mismatch",
                    "episode_reset",
                    "fresh Episode did not reproduce the frozen Task start",
                )
            identity = getattr(session, "identity", None)
            materialization_id = getattr(identity, "materialization_id", None)
            if not isinstance(materialization_id, str):
                raise EpisodeExecutionFailure(
                    "evidence",
                    "materialization_identity_missing",
                    "episode_open",
                    "prepared session omitted materialization identity",
                )
            capture = capture_public_episode(
                actor=session.actor,
                instruction=task_pack.public_view.instruction,
                reset_observation=reset,
                answer_schema=task_pack.public_view.final_answer_schema,
                policy_driver=policy_driver,
            )
            preclose_state = prepared.read_state(instance)
    except EpisodeExecutionFailure:
        raise
    except Exception as exc:
        raise _pre_episode_failure(exc, "episode_act") from exc

    post_reopen_state = None
    evaluation: EvaluationResult | None = None
    verification_defect: EpisodeDefect | None = None
    try:
        with prepared.open(instance):
            post_reopen_state = prepared.read_state(instance)
    except Exception as exc:
        verification_defect = _verification_defect(exc, "episode_reopen")
    if post_reopen_state is not None:
        if not _same(preclose_state, post_reopen_state):
            verification_defect = EpisodeDefect(
                "environment", "post_reopen_state_mismatch", "episode_reopen"
            )
        try:
            completion = capture.completion
            final_answer = (
                completion.final_answer
                if completion is not None and completion.final_answer is not None
                else {}
            )
            evaluation = evaluate_goal(
                candidate.goal_truth,
                EvaluationContext(
                    reset,
                    before,
                    post_reopen_state,
                    evaluation_trace_from_capture(capture),
                    final_answer,
                ),
            )
        except Exception:
            if verification_defect is None:
                verification_defect = EpisodeDefect(
                    "evidence", "goal_evaluation_failed", "episode_evaluate"
                )
            evaluation = None
    reward = _reward(capture.completion, capture.defect, evaluation, verification_defect)
    return EpisodeRecord(
        request,
        policy_driver.policy_spec,
        materialization_id,
        capture,
        before,
        post_reopen_state,
        evaluation,
        verification_defect,
        reward,
    )


def _validate_authority(
    prepared: PreparedTaskEnvironment,
    task_pack: TaskPackArtifact,
    request: EpisodeRequest,
    policy_driver: PolicyDriver,
) -> None:
    if not isinstance(task_pack, TaskPackArtifact):
        raise EpisodeExecutionFailure(
            "task_artifact", "task_pack_invalid", "episode_authority", "TaskPack is invalid"
        )
    if not isinstance(request, EpisodeRequest):
        raise EpisodeExecutionFailure(
            "evidence", "episode_request_invalid", "episode_authority", "request is invalid"
        )
    expected = (
        prepared.identity.release_id,
        task_pack.task_pack_id,
        task_pack.public_view.task_id,
        policy_driver.policy_spec.policy_id,
    )
    actual = (request.release_id, request.task_pack_id, request.task_id, request.policy_id)
    if actual != expected or task_pack.public_view.release_id != prepared.identity.release_id:
        raise EpisodeExecutionFailure(
            "task_artifact",
            "episode_authority_mismatch",
            "episode_authority",
            "Release, TaskPack, Task or Policy identity differs",
        )


def _reward(
    completion: PolicyCompletion | None,
    capture_defect: EpisodeDefect | None,
    evaluation: EvaluationResult | None,
    verification_defect: EpisodeDefect | None,
) -> RewardOutcome:
    defect = capture_defect or verification_defect
    if defect is not None:
        return RewardOutcome("abstain", None, defect.owner, defect.code)
    if completion is None or evaluation is None:
        return RewardOutcome("abstain", None, "evidence", "episode_truth_incomplete")
    if completion.terminal_kind == "completed" and evaluation.passed:
        return RewardOutcome("verified_success", 1.0, None, None)
    return RewardOutcome("verified_failure", 0.0, None, None)


def _pre_episode_failure(exc: Exception, phase: str) -> EpisodeExecutionFailure:
    owner: EpisodeExecutionOwner = (
        "infrastructure" if getattr(exc, "kind", None) == "InfrastructureFailure" else "environment"
    )
    code = getattr(exc, "code", None)
    return EpisodeExecutionFailure(
        owner,
        code if isinstance(code, str) and code else "episode_physical_failure",
        phase,
        f"{type(exc).__name__}: {exc}",
    )


def _verification_defect(exc: Exception, phase: str) -> EpisodeDefect:
    owner: Literal["infrastructure", "environment"] = (
        "infrastructure" if getattr(exc, "kind", None) == "InfrastructureFailure" else "environment"
    )
    code = getattr(exc, "code", None)
    return EpisodeDefect(
        owner,
        code if isinstance(code, str) and code else "episode_verification_failed",
        phase,
    )


def _same(left: Any, right: Any) -> bool:
    return canonical_bytes(left) == canonical_bytes(right)


__all__ = ["EpisodeExecutionFailure", "EpisodeExecutionOwner", "run_task_episode"]
