"""ForEach-all compilation and two-fresh-witness proof over Atom semantics."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from agent_env_foundry.agents import AgentRoute
from agent_env_foundry.environment import JSONObject, JSONValue
from agent_env_foundry.jsonvalue import is_json_object, is_json_value
from agent_env_foundry.preparation import OpenPreparedRelease, OpenPreparedSession
from agent_env_foundry.provenance import ArgumentProvenance, resolve_argument_provenance
from agent_env_foundry.public_agent import run_public_episode
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
from agent_env_foundry.task_foundry import AtomTask, TaskFoundryError


@dataclass(frozen=True, slots=True)
class ForEachTask:
    release_id: str
    start_case: StartCase
    capability_id: str
    semantic_keys: tuple[str, ...]
    public_descriptors: tuple[JSONObject, ...]
    selector_id: str
    checker_digest: str
    instruction: str
    instruction_digest: str
    member_answer_schema: JSONObject
    answer_schema: JSONObject

    def __post_init__(self) -> None:
        if (
            len(self.semantic_keys) < 2
            or self.semantic_keys != tuple(sorted(self.semantic_keys))
            or len(set(self.semantic_keys)) != len(self.semantic_keys)
        ):
            raise TaskFoundryError(
                "foreach_selection_invalid",
                "ForEach selection must contain at least two unique semantic keys "
                "in stable ordered form",
            )
        if len(self.public_descriptors) != len(self.semantic_keys):
            raise TaskFoundryError(
                "foreach_descriptor_count_mismatch",
                "ForEach public descriptors must cover the complete ordered selection",
            )

    @property
    def task_id(self) -> str:
        return hashlib.sha256(canonical_bytes(self.to_document())).hexdigest()

    def to_document(self) -> JSONObject:
        return {
            "format": "foreach-task/1",
            "release_id": self.release_id,
            "start_case": self.start_case.to_document(),
            "capability_id": self.capability_id,
            "semantic_keys": list(self.semantic_keys),
            "public_descriptors": [_json_object(item) for item in self.public_descriptors],
            "selector_id": self.selector_id,
            "checker_digest": self.checker_digest,
            "instruction": self.instruction,
            "instruction_digest": self.instruction_digest,
            "member_answer_schema": _json_object(self.member_answer_schema),
            "answer_schema": _json_object(self.answer_schema),
        }


@dataclass(frozen=True, slots=True)
class ForEachWitness:
    task_id: str
    materialization_id: str
    reset_observation: JSONValue
    trace: tuple[TraceEvent, ...]
    final_answer: JSONObject
    argument_provenance: tuple[ArgumentProvenance, ...]
    member_results: tuple[AtomCheckResult, ...]
    provider_turns: int
    usage: tuple[JSONObject | None, ...]

    @property
    def witness_id(self) -> str:
        return hashlib.sha256(canonical_bytes(self.to_document())).hexdigest()

    def to_document(self) -> JSONObject:
        return {
            "format": "foreach-witness/1",
            "task_id": self.task_id,
            "materialization_id": self.materialization_id,
            "reset_observation": _json(self.reset_observation),
            "trace": [item.to_document() for item in self.trace],
            "final_answer": _json_object(self.final_answer),
            "argument_provenance": [item.to_document() for item in self.argument_provenance],
            "member_results": [item.to_document() for item in self.member_results],
            "provider_turns": self.provider_turns,
            "usage": [_json(item) for item in self.usage],
        }


@dataclass(frozen=True, slots=True)
class SolvedForEachTask:
    task: ForEachTask
    witnesses: tuple[ForEachWitness, ForEachWitness]

    def __post_init__(self) -> None:
        if any(item.task_id != self.task.task_id for item in self.witnesses):
            raise TaskFoundryError(
                "foreach_witness_task_mismatch",
                "ForEach witness belongs to another Task",
            )
        if len({item.materialization_id for item in self.witnesses}) != 2:
            raise TaskFoundryError(
                "foreach_witness_materialization_reused",
                "ForEach witnesses must use two fresh materializations",
            )
        for witness in self.witnesses:
            if len(witness.member_results) != len(self.task.semantic_keys) or any(
                not item.satisfied for item in witness.member_results
            ):
                raise TaskFoundryError(
                    "foreach_witness_not_satisfied",
                    "Every selected ForEach member must satisfy its Atom checker",
                )

    def to_document(self) -> JSONObject:
        return {
            "format": "solved-foreach-task/1",
            "task": self.task.to_document(),
            "witnesses": [item.to_document() for item in self.witnesses],
        }


def compile_foreach_tasks(
    prepared: OpenPreparedRelease,
    atom_tasks: tuple[AtomTask, ...],
    instance_root: Path,
    *,
    max_members: int = 8,
) -> tuple[ForEachTask, ...]:
    """Compile each complete multi-binding set; never truncate or facet-filter it."""

    if max_members < 2:
        raise ValueError("max_members must be at least two")
    groups: dict[tuple[str, str], list[AtomTask]] = {}
    for atom_task in atom_tasks:
        if atom_task.release_id != prepared.identity.release_id:
            raise TaskFoundryError(
                "task_release_mismatch",
                "Atom Task belongs to another release",
            )
        groups.setdefault((atom_task.start_case.case_id, atom_task.capability_id), []).append(
            atom_task
        )

    compiled: list[ForEachTask] = []
    for index, members in enumerate(groups.values(), start=1):
        ordered = tuple(sorted(members, key=lambda item: item.semantic_key))
        if len(ordered) < 2:
            continue
        if len(ordered) > max_members:
            raise TaskFoundryError(
                "foreach_selection_too_large",
                "Complete ForEach selection exceeds the configured member bound",
                member_count=len(ordered),
                max_members=max_members,
            )
        first = ordered[0]
        if any(
            item.start_case != first.start_case or item.answer_schema != first.answer_schema
            for item in ordered
        ):
            raise TaskFoundryError(
                "foreach_member_contract_mismatch",
                "ForEach members do not share one StartCase and answer contract",
            )
        semantic_keys = tuple(item.semantic_key for item in ordered)
        descriptors = tuple(_json_object(item.public_descriptor) for item in ordered)
        selector_preimage: JSONObject = {
            "format": "foreach-all-selection/1",
            "release_id": first.release_id,
            "start_case_id": first.start_case.case_id,
            "capability_id": first.capability_id,
            "semantic_keys": list(semantic_keys),
        }
        selector_id = hashlib.sha256(canonical_bytes(selector_preimage)).hexdigest()
        checker_preimage: JSONObject = {
            "release_id": first.release_id,
            "start_case_id": first.start_case.case_id,
            "capability_id": first.capability_id,
            "semantic_keys": list(semantic_keys),
            "selector_id": selector_id,
            "member_answer_schema": first.answer_schema,
        }
        checker_digest = hashlib.sha256(canonical_bytes(checker_preimage)).hexdigest()
        answer_schema = _foreach_answer_schema(first.answer_schema, len(ordered))
        goal = prepared.task_goals.get(first.capability_id)
        if not isinstance(goal, str) or not goal.strip():
            raise TaskFoundryError(
                "task_goal_missing",
                "Admitted release has no public goal for a ForEach capability",
            )
        instruction = _instruction(goal, descriptors)
        compiled_task = ForEachTask(
            first.release_id,
            first.start_case,
            first.capability_id,
            semantic_keys,
            descriptors,
            selector_id,
            checker_digest,
            instruction,
            hashlib.sha256(instruction.encode()).hexdigest(),
            first.answer_schema,
            answer_schema,
        )
        _prove_initially_false(
            prepared,
            compiled_task,
            Path(instance_root) / f"compile-{index}",
        )
        compiled.append(compiled_task)
    ids = tuple(item.task_id for item in compiled)
    if len(ids) != len(set(ids)):
        raise TaskFoundryError(
            "foreach_task_identity_collision",
            "Compiled ForEach Tasks are not unique",
        )
    return tuple(compiled)


def solve_foreach_task_twice(
    prepared: OpenPreparedRelease,
    task: ForEachTask,
    instance_root: Path,
    *,
    route: AgentRoute | None = None,
    max_provider_turns: int = 12,
) -> SolvedForEachTask:
    """Solve the exact ForEach instruction over two fresh complete selections."""

    _verify_task(prepared, task)
    selected_route = route or AgentRoute(max_provider_turns=max_provider_turns)
    witnesses: list[ForEachWitness] = []
    for index in (1, 2):
        instance = Path(instance_root) / f"witness-{index}"
        with prepared.open(instance) as session:
            reset = session.actor.reset(task.start_case.reset_input)
            before = session.trusted.inspect(instance)
            bindings = _resolve_complete_selection(session, task, before)
            tool_specs = session.actor.tools()
            episode = run_public_episode(
                actor=session.actor,
                instruction=task.instruction,
                reset_observation=reset,
                tool_specs=tool_specs,
                answer_schema=task.answer_schema,
                route=selected_route,
                max_provider_turns=max_provider_turns,
            )
            answers = episode.final_answer.get("results")
            if not isinstance(answers, list) or len(answers) != len(bindings):
                raise TaskFoundryError(
                    "foreach_answer_count_mismatch",
                    "ForEach final answer does not cover the complete ordered selection",
                )
            after = session.trusted.inspect(instance)
            contexts = _contexts(task, bindings)
            results = tuple(
                session.trusted.evaluate_atom(
                    AtomCheckRequest(
                        task.capability_id,
                        before,
                        after,
                        binding.protected_binding,
                        episode.trace,
                        answers[position],
                        contexts[position],
                    )
                )
                for position, binding in enumerate(bindings)
            )
            if any(not item.satisfied for item in results):
                raise TaskFoundryError(
                    "foreach_public_witness_failed",
                    "Public Agent did not satisfy every selected ForEach member",
                    results=[item.to_document() for item in results],
                )
            witnesses.append(
                ForEachWitness(
                    task.task_id,
                    session.identity.materialization_id,
                    _json(reset),
                    episode.trace,
                    episode.final_answer,
                    resolve_argument_provenance(
                        trace=episode.trace,
                        instruction_values={
                            "selected_targets": [
                                _json_object(item) for item in task.public_descriptors
                            ]
                        },
                        reset_observation=reset,
                        tool_specs=tool_specs,
                    ),
                    results,
                    episode.provider_turns,
                    episode.usage,
                )
            )
    return SolvedForEachTask(
        task,
        cast(tuple[ForEachWitness, ForEachWitness], tuple(witnesses)),
    )


def _prove_initially_false(
    prepared: OpenPreparedRelease,
    task: ForEachTask,
    instance_root: Path,
) -> None:
    with prepared.open(instance_root) as session:
        session.actor.reset(task.start_case.reset_input)
        before = session.trusted.inspect(instance_root)
        bindings = _resolve_complete_selection(session, task, before)
        contexts = _contexts(task, bindings)
        for position, binding in enumerate(bindings):
            result = session.trusted.evaluate_atom(
                AtomCheckRequest(
                    task.capability_id,
                    before,
                    before,
                    binding.protected_binding,
                    (),
                    {},
                    contexts[position],
                )
            )
            if result.satisfied:
                raise TaskFoundryError(
                    "foreach_task_initially_satisfied",
                    "A selected ForEach member is already satisfied before public action",
                    semantic_key=binding.semantic_key,
                )


def _resolve_complete_selection(
    session: OpenPreparedSession,
    task: ForEachTask,
    facts: JSONValue,
) -> tuple[BindingCandidate, ...]:
    eligible = tuple(
        sorted(
            (
                item
                for item in session.trusted.enumerate_bindings(task.capability_id, facts)
                if item.eligible
            ),
            key=lambda item: item.semantic_key,
        )
    )
    actual_keys = tuple(item.semantic_key for item in eligible)
    if actual_keys != task.semantic_keys:
        raise TaskFoundryError(
            "foreach_selection_drift",
            "Fresh ForEach selection has missing, extra, or reordered semantic keys",
            expected=task.semantic_keys,
            actual=actual_keys,
        )
    if tuple(item.public_descriptor for item in eligible) != task.public_descriptors:
        raise TaskFoundryError(
            "foreach_descriptor_drift",
            "Fresh ForEach selection changed a public descriptor",
        )
    return eligible


def _contexts(
    task: ForEachTask,
    bindings: tuple[BindingCandidate, ...],
) -> tuple[GoalEvaluationContext, ...]:
    slots = tuple(f"member-{index}" for index in range(1, len(bindings) + 1))
    resolved = tuple(
        EvaluationBinding(
            slots[index],
            task.capability_id,
            binding.semantic_key,
            binding.protected_binding,
        )
        for index, binding in enumerate(bindings)
    )
    return tuple(
        GoalEvaluationContext(
            slot,
            resolved,
            None,
            task.selector_id,
            tuple(item for item in slots if item != slot),
        )
        for slot in slots
    )


def _verify_task(prepared: OpenPreparedRelease, task: ForEachTask) -> None:
    if task.release_id != prepared.identity.release_id:
        raise TaskFoundryError(
            "task_release_mismatch",
            "ForEach Task belongs to another release",
        )
    preimage: JSONObject = {
        "release_id": task.release_id,
        "start_case_id": task.start_case.case_id,
        "capability_id": task.capability_id,
        "semantic_keys": list(task.semantic_keys),
        "selector_id": task.selector_id,
        "member_answer_schema": task.member_answer_schema,
    }
    if hashlib.sha256(canonical_bytes(preimage)).hexdigest() != task.checker_digest:
        raise TaskFoundryError(
            "foreach_checker_preimage_mismatch",
            "ForEach checker preimage differs from its frozen digest",
        )
    if hashlib.sha256(task.instruction.encode()).hexdigest() != task.instruction_digest:
        raise TaskFoundryError(
            "foreach_instruction_digest_mismatch",
            "ForEach instruction differs from its frozen digest",
        )


def _foreach_answer_schema(member_schema: JSONObject, count: int) -> JSONObject:
    return {
        "type": "object",
        "properties": {
            "results": {
                "type": "array",
                "items": _json_object(member_schema),
                "minItems": count,
                "maxItems": count,
            }
        },
        "required": ["results"],
        "additionalProperties": False,
    }


def _instruction(goal: str, descriptors: tuple[JSONObject, ...]) -> str:
    return "\n".join(
        (
            f"For every selected target, {goal.strip()}",
            "Selected public target descriptors in required result order: "
            + json.dumps(
                descriptors,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
            "Return a JSON object with a results array containing one result object per "
            "target in exactly that order.",
            "Copy exact public JSON values from the instruction or observations; do not "
            "paraphrase.",
        )
    )


def _json(value: Any) -> JSONValue:
    if not is_json_value(value):
        raise TaskFoundryError("foreach_value_not_json", "ForEach value is not JSON")
    return cast(JSONValue, json.loads(json.dumps(value, ensure_ascii=False)))


def _json_object(value: Any) -> JSONObject:
    normalized = _json(value)
    if not is_json_object(normalized):
        raise TaskFoundryError("foreach_value_not_object", "ForEach value is not an object")
    return cast(JSONObject, normalized)


__all__ = [
    "ForEachTask",
    "ForEachWitness",
    "SolvedForEachTask",
    "compile_foreach_tasks",
    "solve_foreach_task_twice",
]
