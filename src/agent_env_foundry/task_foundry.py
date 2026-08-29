"""Executable Atom Task compilation and two-fresh-witness proof."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from agent_env_foundry.agents import AgentRoute
from agent_env_foundry.environment import JSONObject, JSONValue
from agent_env_foundry.jsonvalue import is_json_object, is_json_value
from agent_env_foundry.preparation import OpenPreparedRelease
from agent_env_foundry.public_agent import PublicEpisodeRun, run_public_episode
from agent_env_foundry.release import canonical_bytes
from agent_env_foundry.semantics import (
    AtomCheckRequest,
    AtomCheckResult,
    EvaluationBinding,
    GoalEvaluationContext,
    StartCase,
    TraceEvent,
)


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
class SolvedAtomTask:
    task: AtomTask
    witnesses: tuple[AtomWitness, AtomWitness]

    def __post_init__(self) -> None:
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
            "witnesses": [item.to_document() for item in self.witnesses],
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
    return SolvedAtomTask(task, cast(tuple[AtomWitness, AtomWitness], tuple(witnesses)))


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
    "AtomTask",
    "AtomWitness",
    "SolvedAtomTask",
    "TaskFoundryError",
    "compile_atom_tasks",
    "solve_atom_task_twice",
]
