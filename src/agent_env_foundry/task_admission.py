"""Physical admission evidence for one frozen EnvironmentRelease/3 Task."""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

from jsonschema import Draft202012Validator

from agent_env_foundry.agents import AgentRoute
from agent_env_foundry.checker_author import execute_task_checker
from agent_env_foundry.environment import (
    JSONObject,
    JSONValue,
    validate_observation,
    validate_tool_catalog,
)
from agent_env_foundry.jsonvalue import is_json_object, is_json_value
from agent_env_foundry.physical_runtime import PreparationSettings
from agent_env_foundry.public_agent import ClientFactory, PublicAgentFailure, run_public_episode
from agent_env_foundry.release import canonical_bytes, sha256_hex
from agent_env_foundry.task_contract import (
    ChallengeCategory,
    TaskCheckRequest,
    TaskCheckResult,
    TaskContract,
    make_task_check_request,
)
from agent_env_foundry.task_proposal import PreparedTaskEnvironment

TASK_WITNESS_FORMAT = "task-witness/1"
TASK_CHALLENGE_FORMAT = "task-challenge/1"
CHECKED_TASK_ATTEMPT_FORMAT = "checked-task-attempt/1"
_CHALLENGE_REPORT_SCHEMA: JSONObject = {
    "type": "object",
    "properties": {"summary": {"type": "string"}},
    "required": ["summary"],
    "additionalProperties": False,
}

TaskAdmissionFailureKind = Literal[
    "EnvironmentDefect",
    "CheckerDefect",
    "FrameworkDefect",
    "InfrastructureFailure",
    "NoPublicWitness",
    "TaskRejected",
]


class TaskAdmissionFailure(RuntimeError):
    def __init__(
        self,
        kind: TaskAdmissionFailureKind,
        code: str,
        message: str,
        **details: Any,
    ) -> None:
        super().__init__(message)
        self.kind, self.code, self.details = kind, code, details


@dataclass(frozen=True, slots=True)
class TaskWitness:
    format: str
    task_id: str
    release_id: str
    witness_index: int
    reset_observation: JSONValue
    before_state: JSONValue
    after_state: JSONValue
    public_trace: tuple[JSONObject, ...]
    final_answer: JSONObject
    checker_result: TaskCheckResult
    provider_turns: int
    usage: tuple[JSONObject | None, ...]

    def __post_init__(self) -> None:
        if self.format != TASK_WITNESS_FORMAT:
            raise ValueError(f"witness format must be {TASK_WITNESS_FORMAT!r}")
        for value, role in ((self.task_id, "task_id"), (self.release_id, "release_id")):
            if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
                raise ValueError(f"witness {role} must be a sha256 digest")
        if self.witness_index <= 0 or self.provider_turns <= 0:
            raise ValueError("witness index and provider turns must be positive")
        if not all(
            is_json_value(value)
            for value in (self.reset_observation, self.before_state, self.after_state)
        ):
            raise ValueError("witness reset and states must be JSON values")
        if not self.public_trace or any(not is_json_object(item) for item in self.public_trace):
            raise ValueError("witness public_trace must be non-empty JSON objects")
        if not is_json_object(self.final_answer):
            raise ValueError("witness final_answer must be a JSON object")
        if not isinstance(self.checker_result, TaskCheckResult):
            raise TypeError("witness checker_result must be typed")
        if len(self.usage) != self.provider_turns:
            raise ValueError("witness usage must retain every provider turn")

    @property
    def witness_id(self) -> str:
        return sha256_hex(canonical_bytes(self.to_document()))

    def to_document(self) -> JSONObject:
        return {
            "format": self.format,
            "task_id": self.task_id,
            "release_id": self.release_id,
            "witness_index": self.witness_index,
            "reset_observation": _json(self.reset_observation),
            "before_state": _json(self.before_state),
            "after_state": _json(self.after_state),
            "public_trace": [_object(item) for item in self.public_trace],
            "final_answer": _object(self.final_answer),
            "checker_result": self.checker_result.to_document(),
            "provider_turns": self.provider_turns,
            "usage": [_object(item) if item is not None else None for item in self.usage],
        }


@dataclass(frozen=True, slots=True)
class TaskChallenge:
    format: str
    category: ChallengeCategory
    task_id: str
    release_id: str
    reset_observation: JSONValue
    before_state: JSONValue
    after_state: JSONValue
    public_trace: tuple[JSONObject, ...]
    final_answer: JSONObject
    policy_final_answer: JSONObject | None
    checker_result: TaskCheckResult
    provider_turns: int
    usage: tuple[JSONObject | None, ...]
    source_witness_id: str | None = None

    def __post_init__(self) -> None:
        if self.format != TASK_CHALLENGE_FORMAT:
            raise ValueError(f"challenge format must be {TASK_CHALLENGE_FORMAT!r}")
        if self.category not in {
            "no_op",
            "wrong_answer",
            "wrong_target",
            "partial",
            "collateral",
        }:
            raise ValueError("challenge category is unsupported")
        for value, role in ((self.task_id, "task_id"), (self.release_id, "release_id")):
            if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
                raise ValueError(f"challenge {role} must be a sha256 digest")
        if not all(
            is_json_value(value)
            for value in (self.reset_observation, self.before_state, self.after_state)
        ):
            raise ValueError("challenge reset and states must be JSON values")
        if any(not is_json_object(item) for item in self.public_trace):
            raise ValueError("challenge public_trace must contain JSON objects")
        if not is_json_object(self.final_answer):
            raise ValueError("challenge final_answer must be a JSON object")
        if self.policy_final_answer is not None and not is_json_object(self.policy_final_answer):
            raise ValueError("challenge policy_final_answer must be an object or null")
        if not isinstance(self.checker_result, TaskCheckResult) or self.checker_result.passed:
            raise ValueError("a retained challenge must be rejected by the checker")
        if self.provider_turns < 0 or len(self.usage) != self.provider_turns:
            raise ValueError("challenge usage must retain every nonnegative provider turn")
        if self.source_witness_id is not None and (
            len(self.source_witness_id) != 64
            or any(char not in "0123456789abcdef" for char in self.source_witness_id)
        ):
            raise ValueError("challenge source_witness_id must be a sha256 digest or null")

    @property
    def challenge_id(self) -> str:
        return sha256_hex(canonical_bytes(self.to_document()))

    def to_document(self) -> JSONObject:
        return {
            "format": self.format,
            "category": self.category,
            "task_id": self.task_id,
            "release_id": self.release_id,
            "reset_observation": _json(self.reset_observation),
            "before_state": _json(self.before_state),
            "after_state": _json(self.after_state),
            "public_trace": [_object(item) for item in self.public_trace],
            "final_answer": _object(self.final_answer),
            "policy_final_answer": (
                _object(self.policy_final_answer) if self.policy_final_answer is not None else None
            ),
            "checker_result": self.checker_result.to_document(),
            "provider_turns": self.provider_turns,
            "usage": [_object(item) if item is not None else None for item in self.usage],
            "source_witness_id": self.source_witness_id,
        }


@dataclass(frozen=True, slots=True)
class CheckedTaskAttempt:
    format: str
    task_id: str
    release_id: str
    reset_observation: JSONValue
    before_state: JSONValue
    after_state: JSONValue
    public_trace: tuple[JSONObject, ...]
    final_answer: JSONObject
    checker_final_answer: JSONObject
    checker_result: TaskCheckResult
    provider_turns: int
    usage: tuple[JSONObject | None, ...]

    @property
    def attempt_id(self) -> str:
        return sha256_hex(canonical_bytes(self.to_document()))

    def to_document(self) -> JSONObject:
        return {
            "format": self.format,
            "task_id": self.task_id,
            "release_id": self.release_id,
            "reset_observation": _json(self.reset_observation),
            "before_state": _json(self.before_state),
            "after_state": _json(self.after_state),
            "public_trace": [_object(item) for item in self.public_trace],
            "final_answer": _object(self.final_answer),
            "checker_final_answer": _object(self.checker_final_answer),
            "checker_result": self.checker_result.to_document(),
            "provider_turns": self.provider_turns,
            "usage": [_object(item) if item is not None else None for item in self.usage],
        }


def run_task_witness(
    prepared: PreparedTaskEnvironment,
    *,
    task: TaskContract,
    checker_project_root: Path,
    instance_directory: Path,
    checker_runtime_root: Path,
    witness_index: int,
    route: AgentRoute | None = None,
    client_factory: ClientFactory | None = None,
    checker_settings: PreparationSettings | None = None,
) -> TaskWitness:
    """Run the frozen public Task once, close, reread state, then check it."""

    attempt = run_checked_task_attempt(
        prepared,
        task=task,
        checker_project_root=checker_project_root,
        instance_directory=instance_directory,
        checker_runtime_root=checker_runtime_root,
        instruction=task.instruction,
        route=route,
        client_factory=client_factory,
        checker_settings=checker_settings,
    )
    witness = TaskWitness(
        TASK_WITNESS_FORMAT,
        task.task_id,
        task.release_id,
        witness_index,
        attempt.reset_observation,
        attempt.before_state,
        attempt.after_state,
        attempt.public_trace,
        attempt.checker_final_answer,
        attempt.checker_result,
        attempt.provider_turns,
        attempt.usage,
    )
    if not attempt.checker_result.passed:
        raise TaskAdmissionFailure(
            "NoPublicWitness",
            "witness_checker_rejected",
            "public Agent completed but the frozen checker rejected the result",
            witness=witness.to_document(),
        )
    return witness


def challenge_no_op(
    prepared: PreparedTaskEnvironment,
    *,
    task: TaskContract,
    reference_final_answer: JSONObject,
    checker_project_root: Path,
    instance_directory: Path,
    checker_runtime_root: Path,
    checker_settings: PreparationSettings | None = None,
) -> TaskChallenge:
    """Prove that a fresh reset with no public actions cannot satisfy the Task."""

    if prepared.identity.release_id != task.release_id:
        raise TaskAdmissionFailure(
            "EnvironmentDefect",
            "noop_release_mismatch",
            "prepared Release differs from the frozen TaskContract",
        )
    instance = _fresh_directory(instance_directory, role="no-op challenge instance")
    try:
        with prepared.open(instance) as session:
            reset_observation = session.actor.reset(task.reset_start)
            before_state = prepared.read_state(instance)
        after_state = prepared.read_state(instance)
    except Exception as exc:
        kind: TaskAdmissionFailureKind = (
            "InfrastructureFailure"
            if getattr(exc, "kind", None) == "InfrastructureFailure"
            else "EnvironmentDefect"
        )
        raise TaskAdmissionFailure(
            kind,
            "noop_environment_failed",
            str(exc),
            original_code=type(exc).__name__,
        ) from exc
    if before_state != after_state:
        raise TaskAdmissionFailure(
            "EnvironmentDefect",
            "noop_state_changed",
            "fresh no-op challenge changed state without a public action",
        )
    request = make_task_check_request(
        task,
        before_state=before_state,
        after_state=after_state,
        public_trace=(),
        final_answer=reference_final_answer,
    )
    result = _execute_checker(
        checker_project_root,
        task=task,
        request=request,
        runtime_root=checker_runtime_root,
        settings=checker_settings,
    )
    if result.passed or all((result.goal, result.required_effects, result.process)):
        raise TaskAdmissionFailure(
            "CheckerDefect",
            "noop_not_discriminated",
            "checker did not reject the no-op on goal, required-effects or process evidence",
            checker_result=result.to_document(),
        )
    return TaskChallenge(
        TASK_CHALLENGE_FORMAT,
        "no_op",
        task.task_id,
        task.release_id,
        reset_observation,
        before_state,
        after_state,
        (),
        reference_final_answer,
        None,
        result,
        0,
        (),
    )


def challenge_wrong_answer(
    *,
    task: TaskContract,
    witness: TaskWitness,
    checker_project_root: Path,
    checker_runtime_root: Path,
    checker_settings: PreparationSettings | None = None,
) -> TaskChallenge:
    """Find a schema-valid answer mutation rejected only by the answer axis."""

    if (
        witness.task_id != task.task_id
        or witness.release_id != task.release_id
        or not witness.checker_result.passed
    ):
        raise TaskAdmissionFailure(
            "CheckerDefect",
            "wrong_answer_witness_invalid",
            "wrong-answer challenge requires a passing witness for the exact Task",
        )
    for index, answer in enumerate(
        _schema_valid_answer_mutants(witness.final_answer, task.final_answer_schema)
    ):
        request = make_task_check_request(
            task,
            before_state=witness.before_state,
            after_state=witness.after_state,
            public_trace=witness.public_trace,
            final_answer=answer,
        )
        result = _execute_checker(
            checker_project_root,
            task=task,
            request=request,
            runtime_root=checker_runtime_root / f"candidate-{index:03d}",
            settings=checker_settings,
        )
        if (
            not result.passed
            and not result.answer
            and all(
                (
                    result.goal,
                    result.required_effects,
                    result.forbidden_effects,
                    result.process,
                )
            )
        ):
            return TaskChallenge(
                TASK_CHALLENGE_FORMAT,
                "wrong_answer",
                task.task_id,
                task.release_id,
                witness.reset_observation,
                witness.before_state,
                witness.after_state,
                witness.public_trace,
                answer,
                None,
                result,
                0,
                (),
                witness.witness_id,
            )
    raise TaskAdmissionFailure(
        "CheckerDefect",
        "wrong_answer_not_discriminated",
        "no schema-valid final-answer mutation was rejected only by the answer axis",
    )


def challenge_partial_from_witness(
    prepared: PreparedTaskEnvironment,
    *,
    task: TaskContract,
    witness: TaskWitness,
    checker_project_root: Path,
    attempt_root: Path,
    checker_runtime_root: Path,
    checker_settings: PreparationSettings | None = None,
) -> TaskChallenge:
    """Replay the longest strict successful prefix that misses a required effect."""

    if "partial" not in task.challenge_categories:
        raise TaskAdmissionFailure(
            "TaskRejected", "challenge_not_declared", "Task does not declare partial"
        )
    if witness.task_id != task.task_id or not witness.checker_result.passed:
        raise TaskAdmissionFailure(
            "CheckerDefect",
            "partial_witness_invalid",
            "partial replay requires a passing witness for the exact Task",
        )
    root = _fresh_directory(attempt_root, role="partial replay root")
    root.mkdir(parents=True, exist_ok=True)
    for length in range(len(witness.public_trace) - 1, 0, -1):
        try:
            reset_observation, before_state, after_state, trace = _replay_prefix(
                prepared,
                task=task,
                planned=witness.public_trace[:length],
                instance_directory=root / f"prefix-{length:03d}",
            )
        except TaskAdmissionFailure:
            continue
        request = make_task_check_request(
            task,
            before_state=before_state,
            after_state=after_state,
            public_trace=trace,
            final_answer=witness.final_answer,
        )
        result = _execute_checker(
            checker_project_root,
            task=task,
            request=request,
            runtime_root=checker_runtime_root / f"prefix-{length:03d}",
            settings=checker_settings,
        )
        if not result.passed and not result.required_effects:
            return TaskChallenge(
                TASK_CHALLENGE_FORMAT,
                "partial",
                task.task_id,
                task.release_id,
                reset_observation,
                before_state,
                after_state,
                trace,
                witness.final_answer,
                None,
                result,
                0,
                (),
                witness.witness_id,
            )
    raise TaskAdmissionFailure(
        "TaskRejected",
        "partial_not_constructed",
        "no strict successful witness prefix omitted a required effect",
    )


def challenge_collateral_from_witness(
    prepared: PreparedTaskEnvironment,
    *,
    task: TaskContract,
    witness: TaskWitness,
    checker_project_root: Path,
    instance_directory: Path,
    checker_runtime_root: Path,
    route: AgentRoute | None = None,
    client_factory: ClientFactory | None = None,
    checker_settings: PreparationSettings | None = None,
) -> TaskChallenge:
    """Replay a passing solution, then ask a fresh policy for one extra forbidden effect."""

    if "collateral" not in task.challenge_categories:
        raise TaskAdmissionFailure(
            "TaskRejected", "challenge_not_declared", "Task does not declare collateral"
        )
    if witness.task_id != task.task_id or not witness.checker_result.passed:
        raise TaskAdmissionFailure(
            "CheckerDefect",
            "collateral_witness_invalid",
            "collateral replay requires a passing witness for the exact Task",
        )
    instance = _fresh_directory(instance_directory, role="collateral replay instance")
    try:
        with prepared.open(instance) as session:
            reset_observation = session.actor.reset(task.reset_start)
            before_state = prepared.read_state(instance)
            catalog = validate_tool_catalog(session.actor.tools(), role="collateral replay tools()")
            base_trace = _replay_calls(session.actor, catalog, witness.public_trace)
            episode = run_public_episode(
                actor=session.actor,
                instruction=(
                    "VERIFIER COLLATERAL CHALLENGE. The frozen task has already been "
                    "successfully replayed on this current instance. Inspect current public "
                    "state, then make exactly one additional valid persistent change unrelated "
                    "to the frozen task without undoing its requested outcome. Report only a "
                    "concise truthful summary. Frozen task for reference: "
                    f"{task.instruction}"
                ),
                reset_observation=reset_observation,
                tool_specs=session.actor.tools(),
                answer_schema=_CHALLENGE_REPORT_SCHEMA,
                route=route,
                client_factory=client_factory,
            )
            extra_trace = tuple(
                _trace_event(item.tool_name, item.arguments, item.observation)
                for item in episode.trace
            )
            pre_close_state = prepared.read_state(instance)
        after_state = prepared.read_state(instance)
    except PublicAgentFailure as exc:
        kind: TaskAdmissionFailureKind = (
            "FrameworkDefect"
            if exc.details.get("status_code") in {400, 422}
            else cast(TaskAdmissionFailureKind, exc.kind)
        )
        raise TaskAdmissionFailure(kind, exc.code, str(exc), **exc.details) from exc
    except TaskAdmissionFailure:
        raise
    except Exception as exc:
        raise TaskAdmissionFailure(
            "EnvironmentDefect",
            "collateral_replay_failed",
            str(exc),
            original_code=type(exc).__name__,
        ) from exc
    if pre_close_state != after_state:
        raise TaskAdmissionFailure(
            "EnvironmentDefect",
            "collateral_reopen_state_drift",
            "collateral state changed after close and protected reopen",
        )
    trace = (*base_trace, *extra_trace)
    request = make_task_check_request(
        task,
        before_state=before_state,
        after_state=after_state,
        public_trace=trace,
        final_answer=witness.final_answer,
    )
    result = _execute_checker(
        checker_project_root,
        task=task,
        request=request,
        runtime_root=checker_runtime_root,
        settings=checker_settings,
    )
    if not (
        not result.passed
        and result.goal
        and result.required_effects
        and not result.forbidden_effects
    ):
        raise TaskAdmissionFailure(
            "TaskRejected",
            "collateral_not_constructed",
            "post-witness public attempt did not isolate a forbidden collateral effect",
            checker_result=result.to_document(),
            trace=list(trace),
            before_state=before_state,
            after_state=after_state,
            policy_final_answer=episode.final_answer,
        )
    return TaskChallenge(
        TASK_CHALLENGE_FORMAT,
        "collateral",
        task.task_id,
        task.release_id,
        reset_observation,
        before_state,
        after_state,
        trace,
        witness.final_answer,
        episode.final_answer,
        result,
        episode.provider_turns,
        episode.usage,
        witness.witness_id,
    )


def _replay_prefix(
    prepared: PreparedTaskEnvironment,
    *,
    task: TaskContract,
    planned: tuple[JSONObject, ...],
    instance_directory: Path,
) -> tuple[JSONValue, JSONValue, JSONValue, tuple[JSONObject, ...]]:
    instance = _fresh_directory(instance_directory, role="partial replay instance")
    try:
        with prepared.open(instance) as session:
            reset_observation = session.actor.reset(task.reset_start)
            before_state = prepared.read_state(instance)
            catalog = validate_tool_catalog(session.actor.tools(), role="partial replay tools()")
            trace = _replay_calls(session.actor, catalog, planned)
        after_state = prepared.read_state(instance)
    except Exception as exc:
        raise TaskAdmissionFailure(
            "EnvironmentDefect",
            "partial_replay_failed",
            str(exc),
            original_code=type(exc).__name__,
        ) from exc
    return reset_observation, before_state, after_state, trace


def _replay_calls(
    actor: Any,
    catalog: dict[str, Any],
    planned: tuple[JSONObject, ...],
) -> tuple[JSONObject, ...]:
    trace: list[JSONObject] = []
    for item in planned:
        tool = cast(str, item["tool"])
        arguments = _object(cast(JSONObject, item["arguments"]))
        if tool not in catalog:
            raise ValueError(f"witness replay references unknown tool {tool!r}")
        observation = actor.invoke(tool, arguments)
        validate_observation(observation, catalog[tool], role=f"witness replay {tool!r}")
        if not observation["ok"]:
            raise ValueError(f"witness replay call {tool!r} no longer succeeds")
        trace.append(_trace_event(tool, arguments, cast(JSONObject, observation)))
    return tuple(trace)


def challenge_wrong_target(
    prepared: PreparedTaskEnvironment,
    *,
    task: TaskContract,
    reference_final_answer: JSONObject,
    checker_project_root: Path,
    instance_directory: Path,
    checker_runtime_root: Path,
    route: AgentRoute | None = None,
    client_factory: ClientFactory | None = None,
    checker_settings: PreparationSettings | None = None,
) -> TaskChallenge:
    """Ask a fresh public policy to act on a comparable but incorrect target."""

    if "wrong_target" not in task.challenge_categories:
        raise TaskAdmissionFailure(
            "TaskRejected",
            "challenge_not_declared",
            "Task does not declare wrong_target",
        )
    attempt = run_checked_task_attempt(
        prepared,
        task=task,
        checker_project_root=checker_project_root,
        instance_directory=instance_directory,
        checker_runtime_root=checker_runtime_root,
        instruction=(
            "VERIFIER WRONG-TARGET CHALLENGE. Use only public tools and real observations. "
            "Intentionally perform a comparable operation on a different publicly discovered "
            "target while leaving the requested target outcome unsatisfied. Inspect the result "
            "and report one concise truthful summary. This challenge is the actual task for "
            "this diagnostic run and overrides conflicting clauses in the quoted original; "
            f"the original is reference only: {task.instruction}"
        ),
        route=route,
        client_factory=client_factory,
        checker_settings=checker_settings,
        policy_answer_schema=_CHALLENGE_REPORT_SCHEMA,
        checker_final_answer=reference_final_answer,
    )
    if attempt.checker_result.passed:
        raise TaskAdmissionFailure(
            "TaskRejected",
            "challenge_not_constructed",
            "public challenge completed the frozen Task instead of the requested near miss",
            category="wrong_target",
            checker_result=attempt.checker_result.to_document(),
            attempt=attempt.to_document(),
        )
    constructed = bool(attempt.public_trace) and not (
        attempt.checker_result.goal and attempt.checker_result.required_effects
    )
    if not constructed:
        raise TaskAdmissionFailure(
            "TaskRejected",
            "challenge_not_constructed",
            "public challenge did not produce a physical wrong-target near miss",
            category="wrong_target",
            checker_result=attempt.checker_result.to_document(),
            attempt=attempt.to_document(),
        )
    return TaskChallenge(
        TASK_CHALLENGE_FORMAT,
        "wrong_target",
        task.task_id,
        task.release_id,
        attempt.reset_observation,
        attempt.before_state,
        attempt.after_state,
        attempt.public_trace,
        attempt.checker_final_answer,
        attempt.final_answer,
        attempt.checker_result,
        attempt.provider_turns,
        attempt.usage,
    )


def run_checked_task_attempt(
    prepared: PreparedTaskEnvironment,
    *,
    task: TaskContract,
    checker_project_root: Path,
    instance_directory: Path,
    checker_runtime_root: Path,
    instruction: str,
    route: AgentRoute | None,
    client_factory: ClientFactory | None,
    checker_settings: PreparationSettings | None,
    policy_answer_schema: JSONObject | None = None,
    checker_final_answer: JSONObject | None = None,
) -> CheckedTaskAttempt:
    if not isinstance(task, TaskContract):
        raise TypeError("task must be a TaskContract")
    if prepared.identity.release_id != task.release_id:
        raise TaskAdmissionFailure(
            "EnvironmentDefect",
            "task_attempt_release_mismatch",
            "prepared Release differs from the frozen TaskContract",
        )
    instance = _fresh_directory(instance_directory, role="task attempt instance")
    try:
        with prepared.open(instance) as session:
            reset_observation = session.actor.reset(task.reset_start)
            before_state = prepared.read_state(instance)
            episode = run_public_episode(
                actor=session.actor,
                instruction=instruction,
                reset_observation=reset_observation,
                tool_specs=session.actor.tools(),
                answer_schema=policy_answer_schema or task.final_answer_schema,
                route=route,
                client_factory=client_factory,
            )
            pre_close_state = prepared.read_state(instance)
        after_state = prepared.read_state(instance)
    except PublicAgentFailure as exc:
        kind: TaskAdmissionFailureKind = (
            "FrameworkDefect"
            if exc.details.get("status_code") in {400, 422}
            else cast(TaskAdmissionFailureKind, exc.kind)
        )
        raise TaskAdmissionFailure(kind, exc.code, str(exc), **exc.details) from exc
    except TaskAdmissionFailure:
        raise
    except Exception as exc:
        kind = (
            "InfrastructureFailure"
            if getattr(exc, "kind", None) == "InfrastructureFailure"
            else "EnvironmentDefect"
        )
        raise TaskAdmissionFailure(
            kind,
            "task_attempt_environment_failed",
            str(exc),
            original_code=type(exc).__name__,
        ) from exc
    if pre_close_state != after_state:
        raise TaskAdmissionFailure(
            "EnvironmentDefect",
            "task_attempt_reopen_state_drift",
            "Task state changed after actor close and protected reopen",
        )
    trace = tuple(
        _trace_event(item.tool_name, item.arguments, item.observation) for item in episode.trace
    )
    request = make_task_check_request(
        task,
        before_state=before_state,
        after_state=after_state,
        public_trace=trace,
        final_answer=checker_final_answer or episode.final_answer,
    )
    checker_result = _execute_checker(
        checker_project_root,
        task=task,
        request=request,
        runtime_root=checker_runtime_root,
        settings=checker_settings,
    )
    return CheckedTaskAttempt(
        CHECKED_TASK_ATTEMPT_FORMAT,
        task.task_id,
        task.release_id,
        reset_observation,
        before_state,
        after_state,
        trace,
        episode.final_answer,
        checker_final_answer or episode.final_answer,
        checker_result,
        episode.provider_turns,
        episode.usage,
    )


def _fresh_directory(path: Path, *, role: str) -> Path:
    selected = Path(path)
    if selected.is_symlink() or (
        selected.exists() and (not selected.is_dir() or any(selected.iterdir()))
    ):
        raise TaskAdmissionFailure(
            "EnvironmentDefect",
            "witness_instance_not_fresh",
            f"{role} must be absent or empty",
        )
    return selected.resolve()


def _execute_checker(
    checker_project_root: Path,
    *,
    task: TaskContract,
    request: TaskCheckRequest,
    runtime_root: Path,
    settings: PreparationSettings | None,
) -> TaskCheckResult:
    try:
        return execute_task_checker(
            checker_project_root,
            task=task,
            request=request,
            runtime_root=runtime_root,
            settings=settings
            or PreparationSettings(Path("/tmp/agent-env-foundry-task-checker-uv-cache")),
        )
    except Exception as exc:
        kind: TaskAdmissionFailureKind = (
            "InfrastructureFailure"
            if getattr(exc, "kind", None) == "InfrastructureFailure"
            else "CheckerDefect"
        )
        raise TaskAdmissionFailure(
            kind,
            "task_checker_execution_failed",
            str(exc),
            original_code=type(exc).__name__,
        ) from exc


def _schema_valid_answer_mutants(answer: JSONObject, schema: JSONObject) -> Iterator[JSONObject]:
    validator = Draft202012Validator(schema)
    seen: set[bytes] = set()
    for candidate in _value_mutants(answer):
        if not is_json_object(candidate) or next(validator.iter_errors(candidate), None):
            continue
        document = _object(cast(JSONObject, candidate))
        identity = canonical_bytes(document)
        if identity in seen:
            continue
        seen.add(identity)
        yield document
        if len(seen) >= 128:
            return


def _value_mutants(value: JSONValue) -> Iterator[JSONValue]:
    if isinstance(value, dict):
        for key in sorted(value):
            for replacement in _value_mutants(value[key]):
                object_candidate = _object(value)
                object_candidate[key] = replacement
                yield object_candidate
        for key in sorted(value):
            object_candidate = _object(value)
            del object_candidate[key]
            yield object_candidate
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            for replacement in _value_mutants(item):
                list_candidate = cast(list[JSONValue], _json(value))
                list_candidate[index] = replacement
                yield list_candidate
        for index in range(len(value)):
            list_candidate = cast(list[JSONValue], _json(value))
            del list_candidate[index]
            yield list_candidate
        return
    if isinstance(value, bool):
        yield not value
    elif isinstance(value, int):
        yield value + 1
        yield value - 1
    elif isinstance(value, float):
        yield value + 1.0
        yield value - 1.0
    elif isinstance(value, str):
        if value:
            suffix = "0" if value[-1] != "0" else "1"
            yield f"{value[:-1]}{suffix}"
        yield f"{value}-wrong"
        yield "wrong"
    elif value is None:
        yield "wrong"
        yield 0


def _json(value: JSONValue) -> JSONValue:
    return cast(JSONValue, json.loads(json.dumps(value, ensure_ascii=False)))


def _object(value: JSONObject) -> JSONObject:
    return cast(JSONObject, _json(value))


def _trace_event(tool: str, arguments: JSONObject, observation: JSONObject) -> JSONObject:
    return {
        "tool": tool,
        "arguments": _object(arguments),
        "observation": _object(observation),
    }


__all__ = [
    "CHECKED_TASK_ATTEMPT_FORMAT",
    "TASK_CHALLENGE_FORMAT",
    "TASK_WITNESS_FORMAT",
    "CheckedTaskAttempt",
    "TaskAdmissionFailure",
    "TaskAdmissionFailureKind",
    "TaskChallenge",
    "TaskWitness",
    "challenge_collateral_from_witness",
    "challenge_no_op",
    "challenge_partial_from_witness",
    "challenge_wrong_answer",
    "challenge_wrong_target",
    "run_checked_task_attempt",
    "run_task_witness",
]
