"""IfGoal compilation and two-fresh-witness proof over qualified conditions."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

from agent_env_foundry.agents import AgentRoute
from agent_env_foundry.environment import JSONObject, JSONValue
from agent_env_foundry.jsonvalue import is_json_object, is_json_value
from agent_env_foundry.preparation import OpenPreparedRelease
from agent_env_foundry.provenance import ArgumentProvenance, resolve_argument_provenance
from agent_env_foundry.public_agent import run_public_episode
from agent_env_foundry.release import canonical_bytes
from agent_env_foundry.semantics import (
    AtomCheckRequest,
    AtomCheckResult,
    ConditionCheckRequest,
    ConditionCheckResult,
    ConditionSpec,
    StartCase,
    TraceEvent,
)
from agent_env_foundry.task_foundry import (
    AtomTask,
    TaskFoundryError,
    _context,
    _resolve_binding,
    _task_by_id,
    _verify_checker_preimage,
)

IfBranch = Literal["true", "false"]


@dataclass(frozen=True, slots=True)
class IfTask:
    release_id: str
    start_case: StartCase
    condition_id: str
    semantic_key: str
    public_descriptor: JSONObject
    true_capability_id: str
    false_capability_id: str
    expected_branch: IfBranch
    branch_task_id: str
    checker_digest: str
    instruction: str
    instruction_digest: str
    answer_schema: JSONObject

    @property
    def branch_capability_id(self) -> str:
        return (
            self.true_capability_id if self.expected_branch == "true" else self.false_capability_id
        )

    @property
    def task_id(self) -> str:
        return hashlib.sha256(canonical_bytes(self.to_document())).hexdigest()

    def to_document(self) -> JSONObject:
        return {
            "format": "if-task/1",
            "release_id": self.release_id,
            "start_case": self.start_case.to_document(),
            "condition_id": self.condition_id,
            "semantic_key": self.semantic_key,
            "public_descriptor": _json_object(self.public_descriptor),
            "true_capability_id": self.true_capability_id,
            "false_capability_id": self.false_capability_id,
            "expected_branch": self.expected_branch,
            "branch_task_id": self.branch_task_id,
            "checker_digest": self.checker_digest,
            "instruction": self.instruction,
            "instruction_digest": self.instruction_digest,
            "answer_schema": _json_object(self.answer_schema),
        }


@dataclass(frozen=True, slots=True)
class IfWitness:
    task_id: str
    materialization_id: str
    reset_observation: JSONValue
    trace: tuple[TraceEvent, ...]
    final_answer: JSONObject
    argument_provenance: tuple[ArgumentProvenance, ...]
    condition_result: ConditionCheckResult
    branch_result: AtomCheckResult
    provider_turns: int
    usage: tuple[JSONObject | None, ...]

    @property
    def witness_id(self) -> str:
        return hashlib.sha256(canonical_bytes(self.to_document())).hexdigest()

    def to_document(self) -> JSONObject:
        return {
            "format": "if-witness/1",
            "task_id": self.task_id,
            "materialization_id": self.materialization_id,
            "reset_observation": _json(self.reset_observation),
            "trace": [item.to_document() for item in self.trace],
            "final_answer": _json_object(self.final_answer),
            "argument_provenance": [item.to_document() for item in self.argument_provenance],
            "condition_result": self.condition_result.to_document(),
            "branch_result": self.branch_result.to_document(),
            "provider_turns": self.provider_turns,
            "usage": [_json(item) for item in self.usage],
        }


@dataclass(frozen=True, slots=True)
class SolvedIfTask:
    task: IfTask
    witnesses: tuple[IfWitness, IfWitness]

    def __post_init__(self) -> None:
        if any(item.task_id != self.task.task_id for item in self.witnesses):
            raise TaskFoundryError(
                "if_witness_task_mismatch",
                "If witness belongs to another Task",
            )
        if len({item.materialization_id for item in self.witnesses}) != 2:
            raise TaskFoundryError(
                "if_witness_materialization_reused",
                "If witnesses must use two fresh materializations",
            )
        if any(
            item.condition_result.status != self.task.expected_branch for item in self.witnesses
        ):
            raise TaskFoundryError(
                "if_witness_condition_mismatch",
                "If witness condition branch differs from the frozen checker",
            )
        if any(not item.branch_result.satisfied for item in self.witnesses):
            raise TaskFoundryError(
                "if_witness_branch_failed",
                "If witness did not satisfy its selected Atom branch",
            )

    def to_document(self) -> JSONObject:
        return {
            "format": "solved-if-task/1",
            "task": self.task.to_document(),
            "witnesses": [item.to_document() for item in self.witnesses],
        }


def compile_if_tasks(
    prepared: OpenPreparedRelease,
    atom_tasks: tuple[AtomTask, ...],
    instance_root: Path,
) -> tuple[IfTask, ...]:
    """Compile one conditional Task per logical referent with exactly one eligible branch."""

    if any(item.release_id != prepared.identity.release_id for item in atom_tasks):
        raise TaskFoundryError(
            "task_release_mismatch",
            "Atom Task belongs to another release",
        )
    atom_index = {(item.capability_id, item.semantic_key): item for item in atom_tasks}
    if len(atom_index) != len(atom_tasks):
        raise TaskFoundryError(
            "if_atom_universe_invalid",
            "If compiler requires a unique Atom Task per capability and semantic key",
        )
    root = Path(instance_root)
    compiled: list[IfTask] = []
    with prepared.open(root) as session:
        catalog = {item.capability_id: item for item in session.trusted.capabilities()}
        conditions = _conditions(catalog)
        starts = {item.start_case.case_id: item.start_case for item in atom_tasks}
        for start in starts.values():
            session.actor.reset(start.reset_input)
            facts = session.trusted.inspect(root)
            for condition in conditions:
                if (
                    condition.binding_scope != "selected_binding"
                    or len(condition.true_capability_ids) != 1
                    or len(condition.false_capability_ids) != 1
                ):
                    continue
                true_capability = condition.true_capability_ids[0]
                false_capability = condition.false_capability_ids[0]
                branch_atoms = tuple(
                    item
                    for item in atom_tasks
                    if item.start_case == start
                    and item.capability_id in {true_capability, false_capability}
                )
                schemas = {canonical_bytes(item.answer_schema) for item in branch_atoms}
                if len(schemas) > 1:
                    raise TaskFoundryError(
                        "if_branch_answer_contract_mismatch",
                        "If branches require one non-leaking public answer contract",
                    )
                for atom in sorted(branch_atoms, key=lambda item: item.semantic_key):
                    binding = _resolve_binding(session, atom, facts)
                    condition_result = session.trusted.evaluate_condition(
                        ConditionCheckRequest(
                            condition.condition_id,
                            facts,
                            binding.protected_binding,
                            (),
                        )
                    )
                    if condition_result.status not in {"true", "false"}:
                        raise TaskFoundryError(
                            "if_condition_abstained",
                            "If condition cannot choose one public branch for a binding",
                        )
                    expected_capability = (
                        true_capability if condition_result.status == "true" else false_capability
                    )
                    if atom.capability_id != expected_capability:
                        raise TaskFoundryError(
                            "if_condition_branch_mismatch",
                            "Eligible Atom Task disagrees with the condition-selected branch",
                            condition_id=condition.condition_id,
                            semantic_key=atom.semantic_key,
                            expected_capability=expected_capability,
                            actual_capability=atom.capability_id,
                        )
                    initial = session.trusted.evaluate_atom(
                        AtomCheckRequest(
                            atom.capability_id,
                            facts,
                            facts,
                            binding.protected_binding,
                            (),
                            {},
                            _context(
                                atom.capability_id,
                                binding.semantic_key,
                                binding.protected_binding,
                            ),
                        )
                    )
                    if initial.satisfied:
                        raise TaskFoundryError(
                            "if_task_initially_satisfied",
                            "If selected branch is already satisfied before public action",
                        )
                    instruction = _instruction(
                        condition.public_label,
                        cast(str, prepared.task_goals[true_capability]),
                        cast(str, prepared.task_goals[false_capability]),
                        atom.public_descriptor,
                    )
                    checker_preimage: JSONObject = {
                        "release_id": prepared.identity.release_id,
                        "start_case_id": start.case_id,
                        "condition_id": condition.condition_id,
                        "semantic_key": atom.semantic_key,
                        "true_capability_id": true_capability,
                        "false_capability_id": false_capability,
                        "expected_branch": condition_result.status,
                        "branch_task_id": atom.task_id,
                        "answer_schema": atom.answer_schema,
                    }
                    compiled.append(
                        IfTask(
                            prepared.identity.release_id,
                            start,
                            condition.condition_id,
                            atom.semantic_key,
                            _json_object(atom.public_descriptor),
                            true_capability,
                            false_capability,
                            condition_result.status,
                            atom.task_id,
                            hashlib.sha256(canonical_bytes(checker_preimage)).hexdigest(),
                            instruction,
                            hashlib.sha256(instruction.encode()).hexdigest(),
                            atom.answer_schema,
                        )
                    )
    ids = tuple(item.task_id for item in compiled)
    if len(ids) != len(set(ids)):
        raise TaskFoundryError("if_task_identity_collision", "Compiled If Tasks are not unique")
    return tuple(compiled)


def solve_if_task_twice(
    prepared: OpenPreparedRelease,
    task: IfTask,
    atom_task_universe: tuple[AtomTask, ...],
    instance_root: Path,
    *,
    route: AgentRoute | None = None,
    max_provider_turns: int = 12,
) -> SolvedIfTask:
    _verify_task(prepared, task)
    branch_task = _task_by_id(atom_task_universe, task.branch_task_id)
    _verify_checker_preimage(prepared, branch_task)
    selected_route = route or AgentRoute(max_provider_turns=max_provider_turns)
    witnesses: list[IfWitness] = []
    for index in (1, 2):
        instance = Path(instance_root) / f"witness-{index}"
        with prepared.open(instance) as session:
            reset = session.actor.reset(task.start_case.reset_input)
            before = session.trusted.inspect(instance)
            binding = _resolve_binding(session, branch_task, before)
            condition_result = session.trusted.evaluate_condition(
                ConditionCheckRequest(
                    task.condition_id,
                    before,
                    binding.protected_binding,
                    (),
                )
            )
            if condition_result.status != task.expected_branch:
                raise TaskFoundryError(
                    "if_condition_drift",
                    "Fresh If condition selected another branch",
                )
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
            after = session.trusted.inspect(instance)
            branch_result = session.trusted.evaluate_atom(
                AtomCheckRequest(
                    task.branch_capability_id,
                    before,
                    after,
                    binding.protected_binding,
                    episode.trace,
                    episode.final_answer,
                    _context(
                        task.branch_capability_id,
                        binding.semantic_key,
                        binding.protected_binding,
                    ),
                )
            )
            if not branch_result.satisfied:
                raise TaskFoundryError(
                    "if_public_witness_failed",
                    "Public Agent did not satisfy the condition-selected branch",
                    condition_result=condition_result.to_document(),
                    branch_result=branch_result.to_document(),
                )
            witnesses.append(
                IfWitness(
                    task.task_id,
                    session.identity.materialization_id,
                    _json(reset),
                    episode.trace,
                    episode.final_answer,
                    resolve_argument_provenance(
                        trace=episode.trace,
                        instruction_values={"selected_target": task.public_descriptor},
                        reset_observation=reset,
                        tool_specs=tool_specs,
                    ),
                    condition_result,
                    branch_result,
                    episode.provider_turns,
                    episode.usage,
                )
            )
    return SolvedIfTask(task, cast(tuple[IfWitness, IfWitness], tuple(witnesses)))


def _conditions(catalog: dict[str, Any]) -> tuple[ConditionSpec, ...]:
    by_id: dict[str, ConditionSpec] = {}
    for capability in catalog.values():
        for condition in capability.conditions:
            previous = by_id.setdefault(condition.condition_id, condition)
            if previous != condition:
                raise TaskFoundryError(
                    "if_condition_declaration_drift",
                    "Condition declaration differs across branch capabilities",
                )
    return tuple(by_id[key] for key in sorted(by_id))


def _verify_task(prepared: OpenPreparedRelease, task: IfTask) -> None:
    if task.release_id != prepared.identity.release_id:
        raise TaskFoundryError("task_release_mismatch", "If Task belongs to another release")
    preimage: JSONObject = {
        "release_id": task.release_id,
        "start_case_id": task.start_case.case_id,
        "condition_id": task.condition_id,
        "semantic_key": task.semantic_key,
        "true_capability_id": task.true_capability_id,
        "false_capability_id": task.false_capability_id,
        "expected_branch": task.expected_branch,
        "branch_task_id": task.branch_task_id,
        "answer_schema": task.answer_schema,
    }
    if hashlib.sha256(canonical_bytes(preimage)).hexdigest() != task.checker_digest:
        raise TaskFoundryError(
            "if_checker_preimage_mismatch",
            "If checker preimage differs from its frozen digest",
        )
    if hashlib.sha256(task.instruction.encode()).hexdigest() != task.instruction_digest:
        raise TaskFoundryError(
            "if_instruction_digest_mismatch",
            "If instruction differs from its frozen digest",
        )


def _instruction(
    public_condition: str,
    true_goal: str,
    false_goal: str,
    descriptor: JSONObject,
) -> str:
    return "\n".join(
        (
            f"Evaluate this public condition for the selected target: {public_condition}",
            f"If the condition holds: {true_goal.strip()}",
            f"Otherwise: {false_goal.strip()}",
            "Selected public target descriptor: "
            + json.dumps(
                descriptor,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
            "Return the JSON object required by the branch you execute.",
            "Use only public observations to choose the branch; do not guess hidden state.",
        )
    )


def _json(value: Any) -> JSONValue:
    if not is_json_value(value):
        raise TaskFoundryError("if_value_not_json", "If value is not JSON")
    return cast(JSONValue, json.loads(json.dumps(value, ensure_ascii=False)))


def _json_object(value: Any) -> JSONObject:
    normalized = _json(value)
    if not is_json_object(normalized):
        raise TaskFoundryError("if_value_not_object", "If value is not an object")
    return cast(JSONObject, normalized)


__all__ = [
    "IfTask",
    "IfWitness",
    "SolvedIfTask",
    "compile_if_tasks",
    "solve_if_task_twice",
]
