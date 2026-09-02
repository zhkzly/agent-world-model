"""Single-checker Task contracts for EnvironmentRelease/3."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal, cast

from agent_env_foundry.environment import JSONObject, JSONValue, validate_observation
from agent_env_foundry.jsonvalue import is_json_object, is_json_value
from agent_env_foundry.release import (
    _entrypoint_reference,
    _hex_digest,
    canonical_bytes,
    sha256_hex,
)
from agent_env_foundry.schema import (
    SchemaError,
    require_object_root,
    validate_instance,
    validate_schema_document,
)

CANDIDATE_TASK_FORMAT = "candidate-task-contract/1"
TASK_PROPOSAL_EVIDENCE_FORMAT = "task-proposal-evidence/1"
TASK_CONTRACT_FORMAT = "task-contract/1"
PUBLIC_TASK_FORMAT = "public-task/1"
TASK_CHECK_REQUEST_FORMAT = "task-check-request/1"
TASK_CHECK_RESULT_FORMAT = "task-check-result/1"
CHECKER_FACTORY = "generated_task_checker.release:check_task"

type ChallengeCategory = Literal[
    "no_op",
    "wrong_answer",
    "wrong_target",
    "partial",
    "collateral",
]
_CHALLENGE_ORDER: tuple[ChallengeCategory, ...] = (
    "no_op",
    "wrong_answer",
    "wrong_target",
    "partial",
    "collateral",
)
_CHECK_RESULT_KEYS = frozenset(
    {
        "format",
        "passed",
        "goal",
        "answer",
        "required_effects",
        "forbidden_effects",
        "process",
        "reason_codes",
    }
)


@dataclass(frozen=True, slots=True)
class TaskProposalEvidence:
    format: str
    release_id: str
    reset_start: JSONObject | None
    reset_observation: JSONValue
    before_state: JSONValue
    after_state: JSONValue
    public_trace: tuple[JSONObject, ...]
    proposed_final_answer: JSONObject

    def __post_init__(self) -> None:
        if self.format != TASK_PROPOSAL_EVIDENCE_FORMAT:
            raise ValueError(f"proposal evidence format must be {TASK_PROPOSAL_EVIDENCE_FORMAT!r}")
        _digest(self.release_id, "release_id")
        if self.reset_start is not None and not is_json_object(self.reset_start):
            raise ValueError("proposal reset_start must be a JSON object or null")
        for value, role in (
            (self.reset_observation, "reset_observation"),
            (self.before_state, "before_state"),
            (self.after_state, "after_state"),
        ):
            if not is_json_value(value):
                raise ValueError(f"proposal {role} must be a JSON value")
        trace = _public_trace(self.public_trace, require_nonempty=True)
        if not is_json_object(self.proposed_final_answer):
            raise ValueError("proposal final answer must be a JSON object")
        object.__setattr__(
            self,
            "reset_start",
            _copy_object(self.reset_start) if self.reset_start is not None else None,
        )
        object.__setattr__(self, "reset_observation", _copy_json(self.reset_observation))
        object.__setattr__(self, "before_state", _copy_json(self.before_state))
        object.__setattr__(self, "after_state", _copy_json(self.after_state))
        object.__setattr__(
            self,
            "public_trace",
            trace,
        )
        object.__setattr__(
            self,
            "proposed_final_answer",
            _copy_object(self.proposed_final_answer),
        )

    @property
    def evidence_id(self) -> str:
        return _document_digest(self.to_document())

    def to_document(self) -> JSONObject:
        return {
            "format": self.format,
            "release_id": self.release_id,
            "reset_start": (
                _copy_object(self.reset_start) if self.reset_start is not None else None
            ),
            "reset_observation": _copy_json(self.reset_observation),
            "before_state": _copy_json(self.before_state),
            "after_state": _copy_json(self.after_state),
            "public_trace": [_copy_object(item) for item in self.public_trace],
            "proposed_final_answer": _copy_object(self.proposed_final_answer),
        }


@dataclass(frozen=True, slots=True)
class CandidateTaskContract:
    format: str
    release_id: str
    research_digest: str
    reset_start: JSONObject | None
    instruction: str
    final_answer_schema: JSONObject
    checker_brief: str
    proposal_evidence_digest: str
    challenge_categories: tuple[ChallengeCategory, ...]

    def __post_init__(self) -> None:
        if self.format != CANDIDATE_TASK_FORMAT:
            raise ValueError(f"candidate format must be {CANDIDATE_TASK_FORMAT!r}")
        _digest(self.release_id, "release_id")
        _digest(self.research_digest, "research_digest")
        _digest(self.proposal_evidence_digest, "proposal_evidence_digest")
        _text(self.instruction, "instruction")
        _text(self.checker_brief, "checker_brief")
        reset = self.reset_start
        if reset is not None and not is_json_object(reset):
            raise ValueError("reset_start must be a JSON object or null")
        schema = _answer_schema(self.final_answer_schema)
        categories = _challenges(self.challenge_categories)
        object.__setattr__(self, "reset_start", _copy_object(reset) if reset is not None else None)
        object.__setattr__(self, "final_answer_schema", schema)
        object.__setattr__(self, "challenge_categories", categories)

    @property
    def candidate_id(self) -> str:
        return _document_digest(self.to_document())

    def to_document(self) -> JSONObject:
        return {
            "format": self.format,
            "release_id": self.release_id,
            "research_digest": self.research_digest,
            "reset_start": (
                _copy_object(self.reset_start) if self.reset_start is not None else None
            ),
            "instruction": self.instruction,
            "final_answer_schema": _copy_object(self.final_answer_schema),
            "checker_brief": self.checker_brief,
            "proposal_evidence_digest": self.proposal_evidence_digest,
            "challenge_categories": list(self.challenge_categories),
        }


@dataclass(frozen=True, slots=True)
class TaskContract:
    format: str
    candidate_id: str
    release_id: str
    research_digest: str
    reset_start: JSONObject | None
    instruction: str
    final_answer_schema: JSONObject
    checker_project_digest: str
    checker_factory: str
    challenge_categories: tuple[ChallengeCategory, ...]

    def __post_init__(self) -> None:
        if self.format != TASK_CONTRACT_FORMAT:
            raise ValueError(f"task format must be {TASK_CONTRACT_FORMAT!r}")
        for value, role in (
            (self.candidate_id, "candidate_id"),
            (self.release_id, "release_id"),
            (self.research_digest, "research_digest"),
            (self.checker_project_digest, "checker_project_digest"),
        ):
            _digest(value, role)
        _text(self.instruction, "instruction")
        if _entrypoint_reference(self.checker_factory, "checker_factory") != CHECKER_FACTORY:
            raise ValueError(f"checker_factory must be {CHECKER_FACTORY!r}")
        reset = self.reset_start
        if reset is not None and not is_json_object(reset):
            raise ValueError("reset_start must be a JSON object or null")
        object.__setattr__(self, "reset_start", _copy_object(reset) if reset is not None else None)
        object.__setattr__(self, "final_answer_schema", _answer_schema(self.final_answer_schema))
        object.__setattr__(self, "challenge_categories", _challenges(self.challenge_categories))

    @property
    def task_id(self) -> str:
        return _document_digest(self.to_document())

    def to_document(self) -> JSONObject:
        return {
            "format": self.format,
            "candidate_id": self.candidate_id,
            "release_id": self.release_id,
            "research_digest": self.research_digest,
            "reset_start": (
                _copy_object(self.reset_start) if self.reset_start is not None else None
            ),
            "instruction": self.instruction,
            "final_answer_schema": _copy_object(self.final_answer_schema),
            "checker_project_digest": self.checker_project_digest,
            "checker_factory": self.checker_factory,
            "challenge_categories": list(self.challenge_categories),
        }

    def public_document(self) -> JSONObject:
        return {
            "format": PUBLIC_TASK_FORMAT,
            "task_id": self.task_id,
            "release_id": self.release_id,
            "instruction": self.instruction,
            "final_answer_schema": _copy_object(self.final_answer_schema),
        }


@dataclass(frozen=True, slots=True)
class TaskCheckRequest:
    format: str
    task_id: str
    before_state: JSONValue
    after_state: JSONValue
    public_trace: tuple[JSONObject, ...]
    final_answer: JSONObject

    def __post_init__(self) -> None:
        if self.format != TASK_CHECK_REQUEST_FORMAT:
            raise ValueError(f"check request format must be {TASK_CHECK_REQUEST_FORMAT!r}")
        _digest(self.task_id, "task_id")
        if not is_json_value(self.before_state) or not is_json_value(self.after_state):
            raise ValueError("check request states must be JSON values")
        trace = _public_trace(self.public_trace, require_nonempty=False)
        if not is_json_object(self.final_answer):
            raise ValueError("final_answer must be a JSON object")
        object.__setattr__(self, "before_state", _copy_json(self.before_state))
        object.__setattr__(self, "after_state", _copy_json(self.after_state))
        object.__setattr__(
            self,
            "public_trace",
            trace,
        )
        object.__setattr__(self, "final_answer", _copy_object(self.final_answer))

    def to_document(self) -> JSONObject:
        return {
            "format": self.format,
            "task_id": self.task_id,
            "before_state": _copy_json(self.before_state),
            "after_state": _copy_json(self.after_state),
            "public_trace": [_copy_object(item) for item in self.public_trace],
            "final_answer": _copy_object(self.final_answer),
        }


@dataclass(frozen=True, slots=True)
class TaskCheckResult:
    format: str
    passed: bool
    goal: bool
    answer: bool
    required_effects: bool
    forbidden_effects: bool
    process: bool
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.format != TASK_CHECK_RESULT_FORMAT:
            raise ValueError(f"check result format must be {TASK_CHECK_RESULT_FORMAT!r}")
        axes = (
            self.goal,
            self.answer,
            self.required_effects,
            self.forbidden_effects,
            self.process,
        )
        if not isinstance(self.passed, bool) or any(not isinstance(item, bool) for item in axes):
            raise ValueError("check result axes must be booleans")
        if self.passed is not all(axes):
            raise ValueError("passed must equal the conjunction of all checker axes")
        if (
            not isinstance(self.reason_codes, tuple)
            or any(not isinstance(item, str) or not item for item in self.reason_codes)
            or tuple(sorted(set(self.reason_codes))) != self.reason_codes
        ):
            raise ValueError("reason_codes must be a sorted unique tuple of non-empty strings")
        if self.passed is bool(self.reason_codes):
            raise ValueError("passed results have no reasons and failed results require reasons")

    def to_document(self) -> JSONObject:
        return {
            "format": self.format,
            "passed": self.passed,
            "goal": self.goal,
            "answer": self.answer,
            "required_effects": self.required_effects,
            "forbidden_effects": self.forbidden_effects,
            "process": self.process,
            "reason_codes": list(self.reason_codes),
        }


def seal_task_contract(
    candidate: CandidateTaskContract,
    *,
    checker_project_digest: str,
    checker_factory: str = CHECKER_FACTORY,
) -> TaskContract:
    if not isinstance(candidate, CandidateTaskContract):
        raise TypeError("candidate must be a CandidateTaskContract")
    return TaskContract(
        TASK_CONTRACT_FORMAT,
        candidate.candidate_id,
        candidate.release_id,
        candidate.research_digest,
        candidate.reset_start,
        candidate.instruction,
        candidate.final_answer_schema,
        checker_project_digest,
        checker_factory,
        candidate.challenge_categories,
    )


def make_task_check_request(
    task: TaskContract,
    *,
    before_state: JSONValue,
    after_state: JSONValue,
    public_trace: tuple[JSONObject, ...],
    final_answer: JSONObject,
) -> TaskCheckRequest:
    if not isinstance(task, TaskContract):
        raise TypeError("task must be a TaskContract")
    try:
        validate_instance(final_answer, task.final_answer_schema, role="task final answer")
    except SchemaError as exc:
        raise ValueError(f"final answer violates TaskContract: {exc}") from exc
    return TaskCheckRequest(
        TASK_CHECK_REQUEST_FORMAT,
        task.task_id,
        before_state,
        after_state,
        public_trace,
        final_answer,
    )


def task_check_result_from_document(document: Any) -> TaskCheckResult:
    if not is_json_object(document) or set(document) != _CHECK_RESULT_KEYS:
        actual = sorted(document) if isinstance(document, dict) else type(document).__name__
        raise ValueError(
            f"task check result must contain exactly {sorted(_CHECK_RESULT_KEYS)}, got {actual}"
        )
    reasons = document["reason_codes"]
    if not isinstance(reasons, list):
        raise ValueError("task check result reason_codes must be an array")
    return TaskCheckResult(
        format=document["format"],
        passed=document["passed"],
        goal=document["goal"],
        answer=document["answer"],
        required_effects=document["required_effects"],
        forbidden_effects=document["forbidden_effects"],
        process=document["process"],
        reason_codes=tuple(reasons),
    )


def _answer_schema(document: JSONObject) -> JSONObject:
    schema = _copy_object(document)
    try:
        require_object_root(schema, role="final_answer_schema")
        validate_schema_document(schema, role="final_answer_schema")
    except SchemaError as exc:
        raise ValueError(str(exc)) from exc
    return schema


def _public_trace(
    values: tuple[JSONObject, ...], *, require_nonempty: bool
) -> tuple[JSONObject, ...]:
    if not isinstance(values, tuple) or (require_nonempty and not values):
        requirement = "a non-empty tuple" if require_nonempty else "a tuple"
        raise ValueError(f"public_trace must be {requirement}")
    copied: list[JSONObject] = []
    for index, value in enumerate(values):
        if not is_json_object(value) or set(value) != {"tool", "arguments", "observation"}:
            raise ValueError(
                "public trace event must contain exactly tool, arguments and observation"
            )
        tool, arguments, observation = (
            value["tool"],
            value["arguments"],
            value["observation"],
        )
        if not isinstance(tool, str) or not tool or not is_json_object(arguments):
            raise ValueError(f"public trace event {index} has invalid tool or arguments")
        try:
            validate_observation(observation, role=f"public trace event {index}")
        except Exception as exc:
            raise ValueError(f"public trace event {index} has invalid observation: {exc}") from exc
        copied.append(_copy_object(value))
    return tuple(copied)


def _challenges(values: tuple[ChallengeCategory, ...]) -> tuple[ChallengeCategory, ...]:
    if not isinstance(values, tuple) or len(set(values)) != len(values):
        raise ValueError("challenge_categories must be a unique tuple")
    if any(value not in _CHALLENGE_ORDER for value in values):
        raise ValueError("challenge_categories contains an unsupported category")
    expected = tuple(value for value in _CHALLENGE_ORDER if value in values)
    if values != expected or not {"no_op", "wrong_answer"} <= set(values):
        raise ValueError(
            "challenge_categories must be canonical and include no_op and wrong_answer"
        )
    return values


def _text(value: str, role: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{role} must be non-empty text")


def _digest(value: str, role: str) -> None:
    try:
        _hex_digest(value, field=role)
    except Exception as exc:
        raise ValueError(str(exc)) from exc


def _document_digest(document: JSONObject) -> str:
    return sha256_hex(canonical_bytes(document))


def _copy_json(value: JSONValue) -> JSONValue:
    return cast(JSONValue, json.loads(json.dumps(value, ensure_ascii=False)))


def _copy_object(value: JSONObject) -> JSONObject:
    return cast(JSONObject, _copy_json(value))


__all__ = [
    "CANDIDATE_TASK_FORMAT",
    "CHECKER_FACTORY",
    "PUBLIC_TASK_FORMAT",
    "TASK_CHECK_REQUEST_FORMAT",
    "TASK_CHECK_RESULT_FORMAT",
    "TASK_CONTRACT_FORMAT",
    "TASK_PROPOSAL_EVIDENCE_FORMAT",
    "CandidateTaskContract",
    "ChallengeCategory",
    "TaskCheckRequest",
    "TaskCheckResult",
    "TaskContract",
    "TaskProposalEvidence",
    "make_task_check_request",
    "seal_task_contract",
    "task_check_result_from_document",
]
