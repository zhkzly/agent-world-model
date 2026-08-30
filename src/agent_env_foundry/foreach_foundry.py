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
from agent_env_foundry.task_execution import ReloadEvidence, run_public_attempt
from agent_env_foundry.task_foundry import (
    AtomTask,
    TaskFoundryError,
    _evaluate_report_atom,
)


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
class ForEachAdmissionPlan:
    task_id: str
    omitted_member_indices: tuple[int, ...]

    def __post_init__(self) -> None:
        if self.omitted_member_indices != (0,):
            raise TaskFoundryError(
                "foreach_admission_plan_invalid",
                "ForEach admission keeps one representative omitted-member challenge",
            )

    @property
    def plan_id(self) -> str:
        return hashlib.sha256(canonical_bytes(self._preimage())).hexdigest()

    def _preimage(self) -> JSONObject:
        return {
            "format": "foreach-admission-plan/4",
            "task_id": self.task_id,
            "omitted_member_indices": list(self.omitted_member_indices),
        }

    def to_document(self) -> JSONObject:
        return {**self._preimage(), "plan_id": self.plan_id}


@dataclass(frozen=True, slots=True)
class ForEachWitness:
    task_id: str
    materialization_id: str
    reload_evidence: ReloadEvidence
    reset_observation: JSONValue
    trace: tuple[TraceEvent, ...]
    final_answer: JSONObject
    argument_provenance: tuple[ArgumentProvenance, ...]
    member_results: tuple[AtomCheckResult, ...]
    provider_turns: int
    usage: tuple[JSONObject | None, ...]

    def __post_init__(self) -> None:
        if (
            self.reload_evidence.task_id != self.task_id
            or self.reload_evidence.acting_session_id != self.materialization_id
        ):
            raise TaskFoundryError(
                "foreach_witness_reload_evidence_mismatch",
                "ForEach witness reload evidence belongs to another Task or session",
            )

    @property
    def witness_id(self) -> str:
        return hashlib.sha256(canonical_bytes(self.to_document())).hexdigest()

    def to_document(self) -> JSONObject:
        return {
            "format": "foreach-witness/2",
            "task_id": self.task_id,
            "materialization_id": self.materialization_id,
            "reload_evidence": self.reload_evidence.to_document(),
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
    admission_plan: ForEachAdmissionPlan
    witnesses: tuple[ForEachWitness, ForEachWitness]

    def __post_init__(self) -> None:
        if self.admission_plan.task_id != self.task.task_id:
            raise TaskFoundryError(
                "foreach_admission_plan_incomplete",
                "ForEach admission plan belongs to another Task",
            )
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
            "admission_plan": self.admission_plan.to_document(),
            "witnesses": [item.to_document() for item in self.witnesses],
        }


@dataclass(frozen=True, slots=True)
class ForEachPartialChallenge:
    task_id: str
    admission_plan_id: str
    omitted_member_index: int
    omitted_semantic_key: str
    materialization_id: str
    trace: tuple[TraceEvent, ...]
    final_answer: JSONObject
    argument_provenance: tuple[ArgumentProvenance, ...]
    member_results: tuple[AtomCheckResult, ...]
    reload_evidence: ReloadEvidence

    def __post_init__(self) -> None:
        if (
            self.reload_evidence.task_id != self.task_id
            or self.reload_evidence.acting_session_id != self.materialization_id
        ):
            raise TaskFoundryError(
                "foreach_partial_reload_evidence_mismatch",
                "ForEach partial challenge reload evidence belongs to another Task or session",
            )
        if not 0 <= self.omitted_member_index < len(self.member_results):
            raise TaskFoundryError(
                "foreach_partial_index_invalid",
                "ForEach partial challenge omitted index is invalid",
            )
        for index, result in enumerate(self.member_results):
            expected = index != self.omitted_member_index
            if result.satisfied != expected:
                raise TaskFoundryError(
                    "foreach_partial_not_discriminated",
                    "ForEach partial challenge must fail only the omitted member",
                    omitted_member_index=self.omitted_member_index,
                    failed_member_index=index,
                )
        omitted = self.member_results[self.omitted_member_index]
        if not omitted.collateral_ok or omitted.process_ok is True:
            raise TaskFoundryError(
                "foreach_partial_axis_invalid",
                "An omitted ForEach member must preserve collateral and have no successful "
                "process evidence",
                omitted_member_index=self.omitted_member_index,
                result=omitted.to_document(),
            )

    def to_document(self) -> JSONObject:
        return {
            "format": "foreach-partial-challenge/2",
            "task_id": self.task_id,
            "admission_plan_id": self.admission_plan_id,
            "omitted_member_index": self.omitted_member_index,
            "omitted_semantic_key": self.omitted_semantic_key,
            "materialization_id": self.materialization_id,
            "trace": [item.to_document() for item in self.trace],
            "final_answer": _json_object(self.final_answer),
            "argument_provenance": [item.to_document() for item in self.argument_provenance],
            "member_results": [item.to_document() for item in self.member_results],
            "reload_evidence": self.reload_evidence.to_document(),
        }


@dataclass(frozen=True, slots=True)
class ForEachPartialChallengeReport:
    task_id: str
    admission_plan: ForEachAdmissionPlan
    partials: tuple[ForEachPartialChallenge, ...]

    def __post_init__(self) -> None:
        if (
            self.admission_plan.task_id != self.task_id
            or tuple(item.omitted_member_index for item in self.partials)
            != self.admission_plan.omitted_member_indices
        ):
            raise TaskFoundryError(
                "foreach_partial_report_incomplete",
                "ForEach partial report does not contain its frozen representative omission",
            )
        if any(
            item.task_id != self.task_id or item.admission_plan_id != self.admission_plan.plan_id
            for item in self.partials
        ):
            raise TaskFoundryError(
                "foreach_partial_report_identity_mismatch",
                "ForEach partial result belongs to another Task or AdmissionPlan",
            )

    @property
    def report_id(self) -> str:
        return hashlib.sha256(canonical_bytes(self._preimage())).hexdigest()

    def _preimage(self) -> JSONObject:
        return {
            "format": "foreach-partial-challenge-report/2",
            "task_id": self.task_id,
            "admission_plan_id": self.admission_plan.plan_id,
            "partials": [item.to_document() for item in self.partials],
        }

    def to_document(self) -> JSONObject:
        return {**self._preimage(), "report_id": self.report_id}


@dataclass(frozen=True, slots=True)
class ForEachNoOpChallenge:
    task_id: str
    admission_plan_id: str
    materialization_id: str
    member_results: tuple[AtomCheckResult, ...]

    def __post_init__(self) -> None:
        if not self.member_results or any(item.satisfied for item in self.member_results):
            raise TaskFoundryError(
                "foreach_noop_false_acceptance",
                "ForEach no-op challenge must fail every selected member",
            )
        if any(
            item.initially_satisfied or not item.collateral_ok or item.process_ok is True
            for item in self.member_results
        ):
            raise TaskFoundryError(
                "foreach_noop_axis_invalid",
                "ForEach no-op must be initially false, preserve collateral, and provide no "
                "successful process evidence for every member",
            )

    def to_document(self) -> JSONObject:
        return {
            "format": "foreach-noop-challenge/1",
            "task_id": self.task_id,
            "admission_plan_id": self.admission_plan_id,
            "materialization_id": self.materialization_id,
            "member_results": [item.to_document() for item in self.member_results],
        }


@dataclass(frozen=True, slots=True)
class ForEachAdmissionReport:
    solved: SolvedForEachTask
    noop: ForEachNoOpChallenge
    partials: ForEachPartialChallengeReport

    def __post_init__(self) -> None:
        task = self.solved.task
        task_id = task.task_id
        plan_id = self.solved.admission_plan.plan_id
        component_pairs: tuple[tuple[str, str], ...] = (
            (self.noop.task_id, self.noop.admission_plan_id),
            (self.partials.task_id, self.partials.admission_plan.plan_id),
        )
        if any(
            item_task != task_id or item_plan != plan_id for item_task, item_plan in component_pairs
        ):
            raise TaskFoundryError(
                "foreach_admission_identity_mismatch",
                "ForEach admission evidence does not share one Task and plan",
            )
        witness_materializations = {item.materialization_id for item in self.solved.witnesses}
        later_materializations = {
            self.noop.materialization_id,
            *(item.materialization_id for item in self.partials.partials),
        }
        if witness_materializations & later_materializations:
            raise TaskFoundryError(
                "foreach_admission_materialization_reused",
                "ForEach witness and post-witness evidence reused a materialization",
            )

    @property
    def report_id(self) -> str:
        return hashlib.sha256(canonical_bytes(self._preimage())).hexdigest()

    def _preimage(self) -> JSONObject:
        return {
            "format": "foreach-admission-report/3",
            "task_id": self.solved.task.task_id,
            "admission_plan": self.solved.admission_plan.to_document(),
            "witnesses": [item.to_document() for item in self.solved.witnesses],
            "noop": self.noop.to_document(),
            "partials": self.partials.to_document(),
        }

    def to_document(self) -> JSONObject:
        return {**self._preimage(), "report_id": self.report_id}


@dataclass(frozen=True, slots=True)
class ForEachTaskPack:
    task: ForEachTask
    admission: ForEachAdmissionReport

    def __post_init__(self) -> None:
        if self.admission.solved.task.task_id != self.task.task_id:
            raise TaskFoundryError(
                "foreach_task_pack_task_mismatch",
                "ForEach TaskPack admission belongs to another Task",
            )

    @property
    def task_pack_id(self) -> str:
        return hashlib.sha256(canonical_bytes(self._preimage())).hexdigest()

    def _preimage(self) -> JSONObject:
        return {
            "format": "foreach-task-pack/2",
            "task": self.task.to_document(),
            "admission": self.admission.to_document(),
        }

    def to_document(self) -> JSONObject:
        return {**self._preimage(), "task_pack_id": self.task_pack_id}


def seal_foreach_task_pack(
    solved: SolvedForEachTask,
    noop: ForEachNoOpChallenge,
    partials: ForEachPartialChallengeReport,
) -> ForEachTaskPack:
    _verify_task_preimage(solved.task)
    admission = ForEachAdmissionReport(
        solved,
        noop,
        partials,
    )
    return ForEachTaskPack(solved.task, admission)


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
    if any(item.release_id != prepared.identity.release_id for item in atom_tasks):
        raise TaskFoundryError(
            "task_release_mismatch",
            "Atom Task belongs to another release",
        )
    groups: dict[tuple[str, str, bytes], list[AtomTask]] = {}
    for atom_task in atom_tasks:
        groups.setdefault(
            (
                atom_task.start_case.case_id,
                atom_task.capability_id,
                canonical_bytes(atom_task.answer_schema),
            ),
            [],
        ).append(atom_task)

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
    atom_task_universe: tuple[AtomTask, ...],
    instance_root: Path,
    *,
    route: AgentRoute | None = None,
    max_provider_turns: int = 12,
) -> SolvedForEachTask:
    """Solve the exact ForEach instruction over two fresh complete selections."""

    _verify_task(prepared, task)
    admission_plan = _derive_admission_plan(
        prepared,
        task,
        atom_task_universe,
        Path(instance_root) / "admission-plan",
    )
    selected_route = route or AgentRoute(max_provider_turns=max_provider_turns)
    witnesses: list[ForEachWitness] = []
    for index in (1, 2):
        witness = run_foreach_task_once(
            prepared,
            task,
            Path(instance_root) / f"witness-{index}",
            route=selected_route,
            max_provider_turns=max_provider_turns,
        )
        if any(not item.satisfied for item in witness.member_results):
            raise TaskFoundryError(
                "foreach_public_witness_failed",
                "Public Agent did not satisfy every selected ForEach member",
                results=[item.to_document() for item in witness.member_results],
            )
        witnesses.append(witness)
    return SolvedForEachTask(
        task,
        admission_plan,
        cast(tuple[ForEachWitness, ForEachWitness], tuple(witnesses)),
    )


def run_foreach_task_once(
    prepared: OpenPreparedRelease,
    task: ForEachTask,
    instance_root: Path,
    *,
    route: AgentRoute | None = None,
    max_provider_turns: int = 12,
) -> ForEachWitness:
    """Run one fresh public ForEach attempt without changing Task admission."""

    _verify_task(prepared, task)
    selected_route = route or AgentRoute(max_provider_turns=max_provider_turns)

    def preflight(
        session: OpenPreparedSession,
        before: JSONValue,
    ) -> tuple[BindingCandidate, ...]:
        return _resolve_complete_selection(session, task, before)

    with run_public_attempt(
        prepared,
        Path(instance_root),
        task_id=task.task_id,
        start_input=task.start_case.reset_input,
        instruction=task.instruction,
        answer_schema=task.answer_schema,
        preflight=preflight,
        route=selected_route,
        max_provider_turns=max_provider_turns,
    ) as attempt:
        bindings = attempt.preflight_value
        answers = attempt.episode.final_answer.get("results")
        if not isinstance(answers, list) or len(answers) != len(bindings):
            raise TaskFoundryError(
                "foreach_answer_count_mismatch",
                "ForEach final answer does not cover the complete ordered selection",
            )
        contexts = _contexts(task, bindings)
        results = tuple(
            _evaluate_report_atom(
                attempt.evaluation_session,
                AtomCheckRequest(
                    task.capability_id,
                    attempt.before_facts,
                    attempt.post_reopen_facts,
                    binding.protected_binding,
                    attempt.episode.trace,
                    answers[position],
                    contexts[position],
                ),
                task.member_answer_schema,
            )
            for position, binding in enumerate(bindings)
        )
        attempt.record_checker_result({"member_results": [item.to_document() for item in results]})
    assert attempt.reload_evidence is not None
    return ForEachWitness(
        task.task_id,
        attempt.acting_session_id,
        attempt.reload_evidence,
        _json(attempt.reset_observation),
        attempt.episode.trace,
        attempt.episode.final_answer,
        resolve_argument_provenance(
            trace=attempt.episode.trace,
            instruction_values={
                "selected_targets": [_json_object(item) for item in task.public_descriptors]
            },
            reset_observation=attempt.reset_observation,
            tool_specs=attempt.tool_specs,
        ),
        results,
        attempt.episode.provider_turns,
        attempt.episode.usage,
    )


def challenge_foreach_partials(
    prepared: OpenPreparedRelease,
    solved: SolvedForEachTask,
    instance_root: Path,
    *,
    route: AgentRoute | None = None,
    max_provider_turns: int = 12,
) -> ForEachPartialChallengeReport:
    """Physically execute every preplanned one-member omission on a fresh instance."""

    task = solved.task
    _verify_task(prepared, task)
    selected_route = route or AgentRoute(max_provider_turns=max_provider_turns)
    partials: list[ForEachPartialChallenge] = []
    goal = prepared.task_goals.get(task.capability_id)
    if not isinstance(goal, str) or not goal.strip():
        raise TaskFoundryError(
            "task_goal_missing",
            "Admitted release has no public goal for a ForEach capability",
        )
    for omitted_index in solved.admission_plan.omitted_member_indices:
        instance = Path(instance_root) / f"omit-{omitted_index}"
        included_indices = tuple(
            index for index in range(len(task.semantic_keys)) if index != omitted_index
        )
        included_descriptors = tuple(task.public_descriptors[index] for index in included_indices)
        partial_instruction = _instruction(goal, included_descriptors)
        partial_answer_schema = _foreach_answer_schema(
            task.member_answer_schema,
            len(included_indices),
        )

        def partial_preflight(
            session: OpenPreparedSession,
            before: JSONValue,
        ) -> tuple[BindingCandidate, ...]:
            return _resolve_complete_selection(session, task, before)

        with run_public_attempt(
            prepared,
            instance,
            task_id=task.task_id,
            start_input=task.start_case.reset_input,
            instruction=partial_instruction,
            answer_schema=partial_answer_schema,
            preflight=partial_preflight,
            route=selected_route,
            max_provider_turns=max_provider_turns,
        ) as attempt:
            bindings = attempt.preflight_value
            partial_answers = attempt.episode.final_answer.get("results")
            if not isinstance(partial_answers, list) or len(partial_answers) != len(
                included_indices
            ):
                raise TaskFoundryError(
                    "foreach_partial_answer_count_mismatch",
                    "Partial ForEach answer does not cover every included member",
                )
            answers: list[JSONValue] = [{} for _ in task.semantic_keys]
            for position, member_index in enumerate(included_indices):
                answers[member_index] = partial_answers[position]
            contexts = _contexts(task, bindings)
            results = tuple(
                _evaluate_report_atom(
                    attempt.evaluation_session,
                    AtomCheckRequest(
                        task.capability_id,
                        attempt.before_facts,
                        attempt.post_reopen_facts,
                        binding.protected_binding,
                        attempt.episode.trace,
                        answers[position],
                        contexts[position],
                    ),
                    task.member_answer_schema,
                )
                for position, binding in enumerate(bindings)
            )
            attempt.record_checker_result(
                {"member_results": [item.to_document() for item in results]}
            )
        assert attempt.reload_evidence is not None
        partials.append(
            ForEachPartialChallenge(
                task.task_id,
                solved.admission_plan.plan_id,
                omitted_index,
                task.semantic_keys[omitted_index],
                attempt.acting_session_id,
                attempt.episode.trace,
                attempt.episode.final_answer,
                resolve_argument_provenance(
                    trace=attempt.episode.trace,
                    instruction_values={
                        "selected_targets": [_json_object(item) for item in included_descriptors]
                    },
                    reset_observation=attempt.reset_observation,
                    tool_specs=attempt.tool_specs,
                ),
                results,
                attempt.reload_evidence,
            )
        )
    return ForEachPartialChallengeReport(
        task.task_id,
        solved.admission_plan,
        tuple(partials),
    )


def run_foreach_noop(
    prepared: OpenPreparedRelease,
    solved: SolvedForEachTask,
    instance_root: Path,
) -> ForEachNoOpChallenge:
    task = solved.task
    _verify_task(prepared, task)
    with prepared.open(instance_root) as session:
        session.actor.reset(task.start_case.reset_input)
        before = session.trusted.inspect(instance_root)
        bindings = _resolve_complete_selection(session, task, before)
        contexts = _contexts(task, bindings)
        results = tuple(
            _evaluate_report_atom(
                session,
                AtomCheckRequest(
                    task.capability_id,
                    before,
                    before,
                    binding.protected_binding,
                    (),
                    {},
                    contexts[position],
                ),
                task.member_answer_schema,
            )
            for position, binding in enumerate(bindings)
        )
        return ForEachNoOpChallenge(
            task.task_id,
            solved.admission_plan.plan_id,
            session.identity.materialization_id,
            results,
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


def _derive_admission_plan(
    prepared: OpenPreparedRelease,
    task: ForEachTask,
    atom_task_universe: tuple[AtomTask, ...],
    instance_root: Path,
) -> ForEachAdmissionPlan:
    task_ids = tuple(item.task_id for item in atom_task_universe)
    if len(task_ids) != len(set(task_ids)) or any(
        item.release_id != task.release_id for item in atom_task_universe
    ):
        raise TaskFoundryError(
            "foreach_atom_universe_invalid",
            "ForEach admission requires one unique same-release Atom Task universe",
        )
    del prepared, instance_root
    return ForEachAdmissionPlan(
        task.task_id,
        (0,),
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
    _verify_task_preimage(task)


def _verify_task_preimage(task: ForEachTask) -> None:
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
            "Respect temporal qualifiers in answer-field descriptions: an observation before "
            "that event cannot fill an after-event field; use null when the qualified "
            "observation did not occur.",
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
    "ForEachAdmissionPlan",
    "ForEachAdmissionReport",
    "ForEachNoOpChallenge",
    "ForEachPartialChallenge",
    "ForEachPartialChallengeReport",
    "ForEachTask",
    "ForEachTaskPack",
    "ForEachWitness",
    "SolvedForEachTask",
    "compile_foreach_tasks",
    "run_foreach_task_once",
    "run_foreach_noop",
    "seal_foreach_task_pack",
    "challenge_foreach_partials",
    "solve_foreach_task_twice",
]
