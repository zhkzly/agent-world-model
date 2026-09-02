"""Immutable TaskPack admission artifact for the clean-break S2 path."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from agent_env_foundry.environment import JSONObject
from agent_env_foundry.project_identity import (
    ProjectIdentityError,
    compute_authored_project_digest,
    copy_authored_project,
)
from agent_env_foundry.release import canonical_bytes, sha256_hex
from agent_env_foundry.task_admission import TaskChallenge, TaskWitness
from agent_env_foundry.task_contract import (
    CandidateTaskContract,
    TaskContract,
    TaskProposalEvidence,
)

TASK_PACK_FORMAT = "task-pack/1"
PUBLIC_TASK_PACK_FORMAT = "public-task-pack/1"


class TaskPackError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class TaskPack:
    format: str
    candidate: CandidateTaskContract
    proposal_evidence: TaskProposalEvidence
    task: TaskContract
    witnesses: tuple[TaskWitness, TaskWitness]
    challenges: tuple[TaskChallenge, ...]

    def __post_init__(self) -> None:
        if self.format != TASK_PACK_FORMAT:
            raise TaskPackError(f"TaskPack format must be {TASK_PACK_FORMAT!r}")
        if not all(
            isinstance(value, expected)
            for value, expected in (
                (self.candidate, CandidateTaskContract),
                (self.proposal_evidence, TaskProposalEvidence),
                (self.task, TaskContract),
            )
        ):
            raise TaskPackError("TaskPack authority objects must be typed")
        candidate = self.candidate
        evidence = self.proposal_evidence
        task = self.task
        if (
            candidate.candidate_id != task.candidate_id
            or candidate.release_id != task.release_id
            or candidate.research_digest != task.research_digest
            or candidate.reset_start != task.reset_start
            or candidate.instruction != task.instruction
            or candidate.final_answer_schema != task.final_answer_schema
            or candidate.challenge_categories != task.challenge_categories
        ):
            raise TaskPackError("TaskContract differs from its frozen candidate")
        if (
            evidence.evidence_id != candidate.proposal_evidence_digest
            or evidence.release_id != task.release_id
            or evidence.reset_start != task.reset_start
        ):
            raise TaskPackError("proposal evidence differs from its frozen candidate")
        if tuple(item.witness_index for item in self.witnesses) != (1, 2):
            raise TaskPackError("TaskPack requires exactly witness indexes 1 and 2")
        if len({item.witness_id for item in self.witnesses}) != 2:
            raise TaskPackError("TaskPack witnesses must be distinct")
        if any(
            item.task_id != task.task_id
            or item.release_id != task.release_id
            or not item.checker_result.passed
            for item in self.witnesses
        ):
            raise TaskPackError("TaskPack contains an invalid witness")
        if tuple(item.category for item in self.challenges) != task.challenge_categories:
            raise TaskPackError("TaskPack challenges must cover the exact declared order")
        if len({item.challenge_id for item in self.challenges}) != len(self.challenges):
            raise TaskPackError("TaskPack challenges must be distinct")
        if any(
            item.task_id != task.task_id or item.release_id != task.release_id
            for item in self.challenges
        ):
            raise TaskPackError("TaskPack contains a challenge for another Task")
        self._validate_challenges()

    def _validate_challenges(self) -> None:
        by_category = {item.category: item for item in self.challenges}
        no_op = by_category["no_op"]
        if (
            no_op.public_trace
            or no_op.before_state != no_op.after_state
            or no_op.source_witness_id is not None
        ):
            raise TaskPackError("no-op challenge must retain an unchanged action-free instance")
        wrong_answer = by_category["wrong_answer"]
        source = next(
            (item for item in self.witnesses if item.witness_id == wrong_answer.source_witness_id),
            None,
        )
        if (
            source is None
            or wrong_answer.before_state != source.before_state
            or wrong_answer.after_state != source.after_state
            or wrong_answer.public_trace != source.public_trace
            or wrong_answer.final_answer == source.final_answer
            or wrong_answer.checker_result.answer
            or not all(
                (
                    wrong_answer.checker_result.goal,
                    wrong_answer.checker_result.required_effects,
                    wrong_answer.checker_result.forbidden_effects,
                    wrong_answer.checker_result.process,
                )
            )
        ):
            raise TaskPackError("wrong-answer challenge is not isolated to its answer")
        physical: list[TaskChallenge] = []
        for category in ("wrong_target", "partial", "collateral"):
            challenge = by_category.get(category)
            if challenge is None:
                continue
            physical.append(challenge)
            replayed_partial = (
                category == "partial"
                and challenge.source_witness_id in {item.witness_id for item in self.witnesses}
                and challenge.provider_turns == 0
            )
            witness_based_collateral = (
                category == "collateral"
                and challenge.source_witness_id in {item.witness_id for item in self.witnesses}
                and challenge.provider_turns > 0
            )
            if not challenge.public_trace or (
                not (replayed_partial or witness_based_collateral)
                and (challenge.source_witness_id is not None or challenge.provider_turns <= 0)
            ):
                raise TaskPackError(f"{category} challenge is not a fresh physical attempt")
            result = challenge.checker_result
            if category == "collateral":
                if not (result.goal and result.required_effects and not result.forbidden_effects):
                    raise TaskPackError("collateral challenge did not isolate forbidden effects")
            elif result.goal and result.required_effects:
                raise TaskPackError(f"{category} challenge accidentally completed the Task")
        physical_ids = {
            sha256_hex(
                canonical_bytes(
                    {
                        "before": item.before_state,
                        "after": item.after_state,
                        "trace": list(item.public_trace),
                    }
                )
            )
            for item in physical
        }
        if len(physical_ids) != len(physical):
            raise TaskPackError("physical challenge categories reused the same attempt")

    @property
    def task_pack_id(self) -> str:
        return sha256_hex(canonical_bytes(self.to_document()))

    def to_document(self) -> JSONObject:
        return {
            "format": self.format,
            "candidate": self.candidate.to_document(),
            "proposal_evidence": self.proposal_evidence.to_document(),
            "task": self.task.to_document(),
            "witnesses": [item.to_document() for item in self.witnesses],
            "challenges": [item.to_document() for item in self.challenges],
        }

    def artifact_document(self) -> JSONObject:
        return {**self.to_document(), "task_pack_id": self.task_pack_id}

    def public_document(self) -> JSONObject:
        public = self.task.public_document()
        return {
            "format": PUBLIC_TASK_PACK_FORMAT,
            "task_pack_id": self.task_pack_id,
            "task_id": public["task_id"],
            "release_id": public["release_id"],
            "instruction": public["instruction"],
            "final_answer_schema": public["final_answer_schema"],
        }


def publish_task_pack(pack: TaskPack, checker_project_root: Path, destination: Path) -> Path:
    if not isinstance(pack, TaskPack):
        raise TypeError("pack must be a TaskPack")
    try:
        checker_digest = compute_authored_project_digest(
            checker_project_root,
            "checker",
            require_locked_project=True,
        )
    except ProjectIdentityError as exc:
        raise TaskPackError(f"checker project is invalid: {exc}") from exc
    if checker_digest != pack.task.checker_project_digest:
        raise TaskPackError("checker project differs from the TaskContract identity")
    target = Path(destination)
    if target.is_symlink() or target.exists():
        raise TaskPackError("TaskPack destination must not exist")
    target.mkdir(parents=True)
    try:
        copied = copy_authored_project(checker_project_root, target / "checker", "checker")
    except ProjectIdentityError as exc:
        raise TaskPackError(f"checker project copy failed: {exc}") from exc
    if copied != checker_digest:
        raise TaskPackError("copied checker identity changed")
    document = target / "TaskPack.json"
    document.write_bytes(canonical_bytes(pack.artifact_document()))
    document.chmod(0o444)
    return target


__all__ = [
    "PUBLIC_TASK_PACK_FORMAT",
    "TASK_PACK_FORMAT",
    "TaskPack",
    "TaskPackError",
    "publish_task_pack",
]
