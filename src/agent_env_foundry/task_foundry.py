"""Executable Atom Task compilation and two-fresh-witness proof."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from jsonschema import Draft202012Validator

from agent_env_foundry.agents import AgentRoute
from agent_env_foundry.environment import JSONObject, JSONValue
from agent_env_foundry.jsonvalue import is_json_object, is_json_value
from agent_env_foundry.preparation import OpenPreparedRelease, OpenPreparedSession
from agent_env_foundry.public_agent import PublicEpisodeRun, run_public_episode
from agent_env_foundry.release import canonical_bytes
from agent_env_foundry.semantics import (
    AtomCheckRequest,
    AtomCheckResult,
    BindingCandidate,
    EvaluationBinding,
    GoalEvaluationContext,
    StartCase,
    TraceEvent,
)

_ATOM_CHALLENGE_CATEGORIES = ("no_op", "wrong_answer", "missing_process")


class TaskFoundryError(RuntimeError):
    def __init__(self, code: str, message: str, **details: Any) -> None:
        super().__init__(message)
        self.code = code
        self.details = details


@dataclass(frozen=True, slots=True)
class AtomTask:
    release_id: str
    start_case: StartCase
    capability_id: str
    semantic_key: str
    public_descriptor: JSONObject
    checker_digest: str
    instruction: str
    instruction_digest: str
    answer_schema: JSONObject

    @property
    def task_id(self) -> str:
        return hashlib.sha256(canonical_bytes(self.to_document())).hexdigest()

    def to_document(self) -> JSONObject:
        return {
            "format": "atom-task/1",
            "release_id": self.release_id,
            "start_case": self.start_case.to_document(),
            "capability_id": self.capability_id,
            "semantic_key": self.semantic_key,
            "public_descriptor": _json_object(self.public_descriptor),
            "checker_digest": self.checker_digest,
            "instruction": self.instruction,
            "instruction_digest": self.instruction_digest,
            "answer_schema": _json_object(self.answer_schema),
        }


@dataclass(frozen=True, slots=True)
class AtomWitness:
    task_id: str
    materialization_id: str
    trace: tuple[TraceEvent, ...]
    final_answer: JSONObject
    result: AtomCheckResult
    provider_turns: int
    usage: tuple[JSONObject | None, ...]

    @property
    def witness_id(self) -> str:
        return hashlib.sha256(canonical_bytes(self.to_document())).hexdigest()

    def to_document(self) -> JSONObject:
        return {
            "format": "atom-witness/1",
            "task_id": self.task_id,
            "materialization_id": self.materialization_id,
            "trace": [item.to_document() for item in self.trace],
            "final_answer": _json_object(self.final_answer),
            "result": self.result.to_document(),
            "provider_turns": self.provider_turns,
            "usage": [_json(item) for item in self.usage],
        }


@dataclass(frozen=True, slots=True)
class AtomPlannedChallenge:
    category: str
    applicable: bool
    final_answer: JSONObject | None
    reason: str | None

    def __post_init__(self) -> None:
        if self.category not in _ATOM_CHALLENGE_CATEGORIES:
            raise TaskFoundryError(
                "admission_plan_category_unknown",
                "Atom admission plan contains an unknown challenge category",
                category=self.category,
            )
        if self.applicable == (self.reason is not None):
            raise TaskFoundryError(
                "admission_plan_disposition_invalid",
                "Applicable challenges cannot have a reason; non-applicable challenges require one",
                category=self.category,
            )
        if self.category == "wrong_answer" and self.applicable:
            if self.final_answer is None:
                raise TaskFoundryError(
                    "admission_plan_wrong_answer_missing",
                    "Applicable wrong-answer challenge requires its frozen answer",
                )
        elif self.final_answer is not None:
            raise TaskFoundryError(
                "admission_plan_answer_unexpected",
                "Only an applicable wrong-answer challenge may freeze an answer",
                category=self.category,
            )

    def to_document(self) -> JSONObject:
        return {
            "category": self.category,
            "applicable": self.applicable,
            "final_answer": None if self.final_answer is None else _json_object(self.final_answer),
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class AtomAdmissionPlan:
    task_id: str
    challenges: tuple[AtomPlannedChallenge, ...]

    def __post_init__(self) -> None:
        categories = tuple(item.category for item in self.challenges)
        if categories != _ATOM_CHALLENGE_CATEGORIES:
            raise TaskFoundryError(
                "admission_plan_incomplete",
                "Atom admission plan must freeze every current challenge exactly once",
                expected=_ATOM_CHALLENGE_CATEGORIES,
                actual=categories,
            )
        if not self.challenges[0].applicable:
            raise TaskFoundryError(
                "admission_plan_noop_missing",
                "Atom admission plan requires an applicable no-op challenge",
            )

    @property
    def plan_id(self) -> str:
        return hashlib.sha256(canonical_bytes(self._preimage())).hexdigest()

    def _preimage(self) -> JSONObject:
        return {
            "format": "atom-admission-plan/1",
            "task_id": self.task_id,
            "challenges": [item.to_document() for item in self.challenges],
        }

    def to_document(self) -> JSONObject:
        return {**self._preimage(), "plan_id": self.plan_id}


@dataclass(frozen=True, slots=True)
class SolvedAtomTask:
    task: AtomTask
    admission_plan: AtomAdmissionPlan
    witnesses: tuple[AtomWitness, AtomWitness]

    def __post_init__(self) -> None:
        if self.admission_plan.task_id != self.task.task_id:
            raise TaskFoundryError(
                "admission_plan_task_mismatch",
                "Atom admission plan belongs to another Task",
            )
        if any(item.task_id != self.task.task_id for item in self.witnesses):
            raise TaskFoundryError(
                "witness_task_mismatch",
                "Atom witness belongs to another Task",
            )
        if len({item.materialization_id for item in self.witnesses}) != 2:
            raise TaskFoundryError(
                "witness_materialization_reused",
                "Atom witnesses must use two fresh materializations",
            )
        if any(not item.result.satisfied for item in self.witnesses):
            raise TaskFoundryError(
                "witness_not_satisfied",
                "Atom witness did not satisfy the frozen checker",
            )

    def to_document(self) -> JSONObject:
        return {
            "format": "solved-atom-task/1",
            "task": self.task.to_document(),
            "admission_plan": self.admission_plan.to_document(),
            "witnesses": [item.to_document() for item in self.witnesses],
        }


@dataclass(frozen=True, slots=True)
class AtomChallengeResult:
    category: str
    applicable: bool
    materialization_id: str
    trace: tuple[TraceEvent, ...]
    final_answer: JSONObject
    result: AtomCheckResult | None
    reason: str | None

    def to_document(self) -> JSONObject:
        return {
            "format": "atom-challenge/1",
            "category": self.category,
            "applicable": self.applicable,
            "materialization_id": self.materialization_id,
            "trace": [item.to_document() for item in self.trace],
            "final_answer": _json_object(self.final_answer),
            "result": None if self.result is None else self.result.to_document(),
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class AtomChallengeReport:
    task_id: str
    admission_plan: AtomAdmissionPlan
    challenges: tuple[AtomChallengeResult, ...]

    def __post_init__(self) -> None:
        if self.admission_plan.task_id != self.task_id:
            raise TaskFoundryError(
                "challenge_plan_task_mismatch",
                "Atom challenge report plan belongs to another Task",
            )
        categories = tuple(item.category for item in self.challenges)
        planned_categories = tuple(item.category for item in self.admission_plan.challenges)
        if categories != planned_categories:
            raise TaskFoundryError(
                "challenge_plan_incomplete",
                "Atom challenge report must account for its frozen plan exactly",
            )
        for planned, item in zip(self.admission_plan.challenges, self.challenges, strict=True):
            if item.applicable != planned.applicable or (
                not item.applicable and item.reason != planned.reason
            ):
                raise TaskFoundryError(
                    "challenge_plan_drift",
                    "Atom challenge result changed its pre-witness disposition",
                    category=item.category,
                )
            if item.applicable and (item.result is None or item.result.satisfied):
                raise TaskFoundryError(
                    "challenge_false_acceptance",
                    "Atom checker accepted an applicable negative challenge",
                    category=item.category,
                )

    def to_document(self) -> JSONObject:
        return {
            "format": "atom-challenge-report/1",
            "task_id": self.task_id,
            "admission_plan_id": self.admission_plan.plan_id,
            "challenges": [item.to_document() for item in self.challenges],
        }


def compile_atom_tasks(
    prepared: OpenPreparedRelease,
    instance_root: Path,
    *,
    start_seed: int = 0,
    start_limit: int = 4,
) -> tuple[AtomTask, ...]:
    """Compile checker identity before rendering any public instruction."""

    if start_limit <= 0:
        raise ValueError("start_limit must be positive")
    goals = prepared.task_goals
    root = Path(instance_root)
    tasks: list[AtomTask] = []
    with prepared.open(root) as session:
        starts = session.trusted.start_cases(start_seed, start_limit)
        capabilities = session.trusted.capabilities()
        for start in starts:
            session.actor.reset(start.reset_input)
            facts = session.trusted.inspect(root)
            for capability in capabilities:
                goal = goals.get(capability.capability_id)
                if not isinstance(goal, str) or not goal.strip():
                    raise TaskFoundryError(
                        "task_goal_missing",
                        "admitted release has no public goal for a capability",
                        capability_id=capability.capability_id,
                    )
                bindings = session.trusted.enumerate_bindings(
                    capability.capability_id,
                    facts,
                )
                for binding in bindings:
                    if not binding.eligible:
                        continue
                    answer_schema = _answer_schema(capability.answer_fields)
                    checker_preimage: JSONObject = {
                        "release_id": prepared.identity.release_id,
                        "start_case_id": start.case_id,
                        "capability_id": capability.capability_id,
                        "semantic_key": binding.semantic_key,
                        "answer_schema": answer_schema,
                    }
                    checker_digest = hashlib.sha256(canonical_bytes(checker_preimage)).hexdigest()
                    context = _context(
                        capability.capability_id,
                        binding.semantic_key,
                        binding.protected_binding,
                    )
                    initial = session.trusted.evaluate_atom(
                        AtomCheckRequest(
                            capability.capability_id,
                            facts,
                            facts,
                            binding.protected_binding,
                            (),
                            {},
                            context,
                        )
                    )
                    if initial.satisfied:
                        raise TaskFoundryError(
                            "atom_task_initially_satisfied",
                            "compiled Atom Task is already satisfied",
                            capability_id=capability.capability_id,
                            semantic_key=binding.semantic_key,
                        )
                    instruction = _instruction(
                        goal,
                        binding.public_descriptor,
                        capability.answer_fields,
                    )
                    tasks.append(
                        AtomTask(
                            prepared.identity.release_id,
                            start,
                            capability.capability_id,
                            binding.semantic_key,
                            _json_object(binding.public_descriptor),
                            checker_digest,
                            instruction,
                            hashlib.sha256(instruction.encode()).hexdigest(),
                            answer_schema,
                        )
                    )
    ids = tuple(item.task_id for item in tasks)
    if len(ids) != len(set(ids)):
        raise TaskFoundryError(
            "atom_task_identity_collision",
            "compiled Atom Tasks are not unique",
        )
    return tuple(tasks)


def solve_atom_task_twice(
    prepared: OpenPreparedRelease,
    task: AtomTask,
    instance_root: Path,
    *,
    route: AgentRoute | None = None,
    max_provider_turns: int = 8,
) -> SolvedAtomTask:
    """Solve the exact frozen instruction on two independently reset instances."""

    if task.release_id != prepared.identity.release_id:
        raise TaskFoundryError(
            "task_release_mismatch",
            "Atom Task belongs to another release",
        )
    admission_plan = _derive_atom_admission_plan(
        prepared,
        task,
        Path(instance_root) / "admission-plan",
    )
    selected_route = route or AgentRoute(max_provider_turns=max_provider_turns)
    witnesses: list[AtomWitness] = []
    for index in (1, 2):
        instance = Path(instance_root) / f"witness-{index}"
        with prepared.open(instance) as session:
            reset = session.actor.reset(task.start_case.reset_input)
            before = session.trusted.inspect(instance)
            capabilities = {item.capability_id: item for item in session.trusted.capabilities()}
            capability = capabilities.get(task.capability_id)
            if capability is None:
                raise TaskFoundryError(
                    "task_capability_missing",
                    "live release no longer exposes the Task capability",
                )
            bindings = session.trusted.enumerate_bindings(task.capability_id, before)
            matching = [item for item in bindings if item.semantic_key == task.semantic_key]
            if len(matching) != 1:
                raise TaskFoundryError(
                    "task_binding_unresolved",
                    "fresh materialization cannot resolve the Task semantic key exactly once",
                )
            binding = matching[0]
            if binding.public_descriptor != task.public_descriptor:
                raise TaskFoundryError(
                    "task_public_descriptor_drift",
                    "fresh logical binding changed the public Task descriptor",
                )
            _verify_checker_preimage(prepared, task)
            episode = run_public_episode(
                actor=session.actor,
                instruction=task.instruction,
                reset_observation=reset,
                tool_specs=session.actor.tools(),
                answer_schema=task.answer_schema,
                route=selected_route,
                max_provider_turns=max_provider_turns,
            )
            after = session.trusted.inspect(instance)
            result = session.trusted.evaluate_atom(
                AtomCheckRequest(
                    task.capability_id,
                    before,
                    after,
                    binding.protected_binding,
                    episode.trace,
                    episode.final_answer,
                    _context(
                        task.capability_id,
                        binding.semantic_key,
                        binding.protected_binding,
                    ),
                )
            )
            if not result.satisfied:
                raise TaskFoundryError(
                    "public_witness_failed",
                    "public Agent trace did not satisfy the frozen Atom checker",
                    result=result.to_document(),
                )
            witnesses.append(_witness(task, session.identity.materialization_id, episode, result))
    return SolvedAtomTask(
        task,
        admission_plan,
        cast(tuple[AtomWitness, AtomWitness], tuple(witnesses)),
    )


def challenge_atom_task(
    prepared: OpenPreparedRelease,
    solved: SolvedAtomTask,
    instance_root: Path,
    *,
    route: AgentRoute | None = None,
    max_provider_turns: int = 8,
) -> AtomChallengeReport:
    """Execute every challenge frozen before the solved Task's witnesses."""

    task = solved.task
    if task.release_id != prepared.identity.release_id:
        raise TaskFoundryError(
            "task_release_mismatch",
            "Atom Task belongs to another release",
        )
    selected_route = route or AgentRoute(max_provider_turns=max_provider_turns)
    admission_plan = solved.admission_plan
    challenges: list[AtomChallengeResult] = []

    no_op_root = Path(instance_root) / "no-op"
    with prepared.open(no_op_root) as session:
        session.actor.reset(task.start_case.reset_input)
        before = session.trusted.inspect(no_op_root)
        binding = _resolve_binding(session, task, before)
        result = session.trusted.evaluate_atom(
            AtomCheckRequest(
                task.capability_id,
                before,
                before,
                binding.protected_binding,
                (),
                {},
                _context(
                    task.capability_id,
                    binding.semantic_key,
                    binding.protected_binding,
                ),
            )
        )
        challenges.append(
            AtomChallengeResult(
                "no_op",
                True,
                session.identity.materialization_id,
                (),
                {},
                result,
                None,
            )
        )

    active_root = Path(instance_root) / "active"
    with prepared.open(active_root) as session:
        reset = session.actor.reset(task.start_case.reset_input)
        before = session.trusted.inspect(active_root)
        binding = _resolve_binding(session, task, before)
        episode = run_public_episode(
            actor=session.actor,
            instruction=task.instruction,
            reset_observation=reset,
            tool_specs=session.actor.tools(),
            answer_schema=task.answer_schema,
            route=selected_route,
            max_provider_turns=max_provider_turns,
        )
        after = session.trusted.inspect(active_root)
        context = _context(
            task.capability_id,
            binding.semantic_key,
            binding.protected_binding,
        )
        correct = session.trusted.evaluate_atom(
            AtomCheckRequest(
                task.capability_id,
                before,
                after,
                binding.protected_binding,
                episode.trace,
                episode.final_answer,
                context,
            )
        )
        if not correct.satisfied:
            raise TaskFoundryError(
                "challenge_baseline_failed",
                "Atom challenge baseline did not satisfy the checker",
                result=correct.to_document(),
            )
        wrong_answer_plan = admission_plan.challenges[1]
        if not wrong_answer_plan.applicable:
            challenges.append(
                AtomChallengeResult(
                    "wrong_answer",
                    False,
                    session.identity.materialization_id,
                    (),
                    {},
                    None,
                    wrong_answer_plan.reason,
                )
            )
        else:
            assert wrong_answer_plan.final_answer is not None
            wrong_answer = wrong_answer_plan.final_answer
            wrong_result = session.trusted.evaluate_atom(
                AtomCheckRequest(
                    task.capability_id,
                    before,
                    after,
                    binding.protected_binding,
                    episode.trace,
                    wrong_answer,
                    context,
                )
            )
            if wrong_result.answer_ok is not False:
                raise TaskFoundryError(
                    "wrong_answer_not_discriminated",
                    "Atom checker did not reject a schema-valid wrong answer",
                )
            challenges.append(
                AtomChallengeResult(
                    "wrong_answer",
                    True,
                    session.identity.materialization_id,
                    episode.trace,
                    wrong_answer,
                    wrong_result,
                    None,
                )
            )

        missing_process_plan = admission_plan.challenges[2]
        if not missing_process_plan.applicable:
            challenges.append(
                AtomChallengeResult(
                    "missing_process",
                    False,
                    session.identity.materialization_id,
                    (),
                    {},
                    None,
                    missing_process_plan.reason,
                )
            )
        else:
            missing_result = session.trusted.evaluate_atom(
                AtomCheckRequest(
                    task.capability_id,
                    before,
                    after,
                    binding.protected_binding,
                    (),
                    episode.final_answer,
                    context,
                )
            )
            if missing_result.process_ok is not False:
                raise TaskFoundryError(
                    "missing_process_not_discriminated",
                    "Atom checker did not reject removal of the public process trace",
                )
            challenges.append(
                AtomChallengeResult(
                    "missing_process",
                    True,
                    session.identity.materialization_id,
                    (),
                    episode.final_answer,
                    missing_result,
                    None,
                )
            )
    return AtomChallengeReport(task.task_id, admission_plan, tuple(challenges))


def _derive_atom_admission_plan(
    prepared: OpenPreparedRelease,
    task: AtomTask,
    instance_root: Path,
) -> AtomAdmissionPlan:
    """Freeze deterministic challenge dispositions before any witness model call."""

    _verify_checker_preimage(prepared, task)
    with prepared.open(instance_root) as session:
        session.actor.reset(task.start_case.reset_input)
        facts = session.trusted.inspect(instance_root)
        binding = _resolve_binding(session, task, facts)
        initial = session.trusted.evaluate_atom(
            AtomCheckRequest(
                task.capability_id,
                facts,
                facts,
                binding.protected_binding,
                (),
                {},
                _context(task.capability_id, binding.semantic_key, binding.protected_binding),
            )
        )
    wrong_answer = _wrong_answer(task.answer_schema, initial.report_values)
    wrong_answer_plan = (
        AtomPlannedChallenge("wrong_answer", True, wrong_answer, None)
        if wrong_answer is not None
        else AtomPlannedChallenge(
            "wrong_answer",
            False,
            None,
            "answer schema has no schema-valid alternative value",
        )
    )
    process_plan = (
        AtomPlannedChallenge("missing_process", True, None, None)
        if initial.process_ok is not None
        else AtomPlannedChallenge(
            "missing_process",
            False,
            None,
            "capability checker declares no process outcome axis",
        )
    )
    return AtomAdmissionPlan(
        task.task_id,
        (
            AtomPlannedChallenge("no_op", True, None, None),
            wrong_answer_plan,
            process_plan,
        ),
    )


def _verify_checker_preimage(
    prepared: OpenPreparedRelease,
    task: AtomTask,
) -> None:
    preimage: JSONObject = {
        "release_id": prepared.identity.release_id,
        "start_case_id": task.start_case.case_id,
        "capability_id": task.capability_id,
        "semantic_key": task.semantic_key,
        "answer_schema": task.answer_schema,
    }
    actual = hashlib.sha256(canonical_bytes(preimage)).hexdigest()
    if actual != task.checker_digest:
        raise TaskFoundryError(
            "checker_preimage_mismatch",
            "Atom checker preimage differs from its frozen digest",
        )
    if hashlib.sha256(task.instruction.encode()).hexdigest() != task.instruction_digest:
        raise TaskFoundryError(
            "instruction_digest_mismatch",
            "Atom instruction differs from its frozen digest",
        )


def _resolve_binding(
    session: OpenPreparedSession,
    task: AtomTask,
    facts: JSONValue,
) -> BindingCandidate:
    bindings = session.trusted.enumerate_bindings(task.capability_id, facts)
    matching = [item for item in bindings if item.semantic_key == task.semantic_key]
    if len(matching) != 1:
        raise TaskFoundryError(
            "task_binding_unresolved",
            "fresh materialization cannot resolve the Task semantic key exactly once",
        )
    binding = matching[0]
    if not binding.eligible or binding.public_descriptor != task.public_descriptor:
        raise TaskFoundryError(
            "task_binding_drift",
            "fresh logical binding changed eligibility or public descriptor",
        )
    return binding


def _wrong_answer(schema: JSONObject, answer: JSONObject) -> JSONObject | None:
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return None
    for field, raw_schema in properties.items():
        if field not in answer or not isinstance(raw_schema, dict):
            continue
        replacement = _alternative_value(raw_schema, answer[field])
        if replacement is _NO_ALTERNATIVE:
            continue
        candidate = _json_object(answer)
        candidate[field] = cast(JSONValue, replacement)
        if not tuple(Draft202012Validator(schema).iter_errors(candidate)):
            return candidate
    return None


_NO_ALTERNATIVE = object()


def _alternative_value(schema: dict[str, Any], value: JSONValue) -> JSONValue | object:
    enum = schema.get("enum")
    if isinstance(enum, list):
        for item in enum:
            if item != value and is_json_value(item):
                return cast(JSONValue, item)
    types = schema.get("type")
    allowed = {types} if isinstance(types, str) else set(types or ())
    if isinstance(value, bool) and "boolean" in allowed:
        return not value
    if isinstance(value, int) and not isinstance(value, bool) and "integer" in allowed:
        for integer_candidate in (value + 1, value - 1):
            if not tuple(Draft202012Validator(schema).iter_errors(integer_candidate)):
                return integer_candidate
    if isinstance(value, (int, float)) and not isinstance(value, bool) and "number" in allowed:
        for number_candidate in (value + 1, value - 1):
            if not tuple(Draft202012Validator(schema).iter_errors(number_candidate)):
                return number_candidate
    if isinstance(value, str) and "string" in allowed:
        for string_candidate in (f"{value}-wrong", "wrong"):
            if string_candidate != value and not tuple(
                Draft202012Validator(schema).iter_errors(string_candidate)
            ):
                return string_candidate
    if value is not None and "null" in allowed:
        return None
    return _NO_ALTERNATIVE


def _instruction(goal: str, descriptor: JSONObject, answer_fields: tuple[Any, ...]) -> str:
    labels = [
        {"field_id": field.field_id, "public_label": field.public_label} for field in answer_fields
    ]
    return "\n".join(
        (
            goal.strip(),
            "Selected public target descriptor: "
            + json.dumps(descriptor, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            "Return a JSON object with these fields: "
            + json.dumps(labels, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            "Copy exact public JSON values from the instruction or observations; "
            "do not paraphrase.",
        )
    )


def _answer_schema(answer_fields: tuple[Any, ...]) -> JSONObject:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            field.field_id: {
                **field.schema,
                "description": field.public_label,
            }
            for field in answer_fields
        },
        "required": [field.field_id for field in answer_fields],
    }


def _context(
    capability_id: str,
    semantic_key: str,
    protected_binding: JSONObject,
) -> GoalEvaluationContext:
    return GoalEvaluationContext(
        "target",
        (
            EvaluationBinding(
                "target",
                capability_id,
                semantic_key,
                protected_binding,
            ),
        ),
        None,
        None,
        (),
    )


def _witness(
    task: AtomTask,
    materialization_id: str,
    episode: PublicEpisodeRun,
    result: AtomCheckResult,
) -> AtomWitness:
    return AtomWitness(
        task.task_id,
        materialization_id,
        episode.trace,
        episode.final_answer,
        result,
        episode.provider_turns,
        episode.usage,
    )


def _json(value: Any) -> JSONValue:
    if not is_json_value(value):
        raise TaskFoundryError("task_value_not_json", "Task value is not JSON")
    return cast(JSONValue, json.loads(json.dumps(value, ensure_ascii=False)))


def _json_object(value: Any) -> JSONObject:
    normalized = _json(value)
    if not is_json_object(normalized):
        raise TaskFoundryError("task_value_not_object", "Task value is not a JSON object")
    return cast(JSONObject, normalized)


__all__ = [
    "AtomAdmissionPlan",
    "AtomChallengeReport",
    "AtomChallengeResult",
    "AtomPlannedChallenge",
    "AtomTask",
    "AtomWitness",
    "SolvedAtomTask",
    "TaskFoundryError",
    "challenge_atom_task",
    "compile_atom_tasks",
    "solve_atom_task_twice",
]
