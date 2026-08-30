"""ForEach-all compilation and two-fresh-witness proof over Atom semantics."""

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
from agent_env_foundry.task_foundry import (
    _NO_ALTERNATIVE,
    AtomTask,
    TaskFoundryError,
    _alternative_value,
    _combine_traces,
    _context,
    _evaluate_report_atom,
    _rebound_final_answer,
    _replay_arguments,
    _resolve_binding,
    _schema_at_pointer,
    _task_by_id,
    _verify_checker_preimage,
    _wrong_answer,
)

_REVERSE_ORDER_PROMPT = (
    "For this checker challenge, complete the same full task but perform the selected targets "
    "in reverse descriptor order. Keep the required final results array in its original "
    "descriptor order."
)
_REVERSE_ORDER_PROMPT_DIGEST = hashlib.sha256(_REVERSE_ORDER_PROMPT.encode()).hexdigest()


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
    wrong_answer_member_index: int | None
    collateral_task_id: str

    def __post_init__(self) -> None:
        if self.omitted_member_indices != tuple(range(len(self.omitted_member_indices))):
            raise TaskFoundryError(
                "foreach_admission_plan_invalid",
                "ForEach partial plan must omit every member once in stable order",
            )
        if not self.collateral_task_id:
            raise TaskFoundryError(
                "foreach_collateral_plan_missing",
                "ForEach admission requires one preselected out-of-selection collateral Task",
            )
        if self.wrong_answer_member_index is not None and not (
            0 <= self.wrong_answer_member_index < len(self.omitted_member_indices)
        ):
            raise TaskFoundryError(
                "foreach_wrong_answer_plan_invalid",
                "ForEach wrong-answer member index is outside the complete selection",
            )

    @property
    def plan_id(self) -> str:
        return hashlib.sha256(canonical_bytes(self._preimage())).hexdigest()

    def _preimage(self) -> JSONObject:
        return {
            "format": "foreach-admission-plan/2",
            "task_id": self.task_id,
            "omitted_member_indices": list(self.omitted_member_indices),
            "wrong_answer_member_index": self.wrong_answer_member_index,
            "collateral_task_id": self.collateral_task_id,
            "agent_choice_policy": "perturb_each_occurrence",
            "alternative_order_policy": "reverse_first_target_occurrences",
            "alternative_order_prompt_digest": _REVERSE_ORDER_PROMPT_DIGEST,
            "checker_mutations": [
                {"mutation_id": f"ignore_member_{index}", "omitted_member_index": index}
                for index in self.omitted_member_indices
            ],
        }

    def to_document(self) -> JSONObject:
        return {**self._preimage(), "plan_id": self.plan_id}


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
    admission_plan: ForEachAdmissionPlan
    witnesses: tuple[ForEachWitness, ForEachWitness]

    def __post_init__(self) -> None:
        if (
            self.admission_plan.task_id != self.task.task_id
            or self.admission_plan.omitted_member_indices
            != tuple(range(len(self.task.semantic_keys)))
        ):
            raise TaskFoundryError(
                "foreach_admission_plan_incomplete",
                "ForEach admission plan must challenge every member before witnesses",
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

    def __post_init__(self) -> None:
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

    def to_document(self) -> JSONObject:
        return {
            "format": "foreach-partial-challenge/1",
            "task_id": self.task_id,
            "admission_plan_id": self.admission_plan_id,
            "omitted_member_index": self.omitted_member_index,
            "omitted_semantic_key": self.omitted_semantic_key,
            "materialization_id": self.materialization_id,
            "trace": [item.to_document() for item in self.trace],
            "final_answer": _json_object(self.final_answer),
            "argument_provenance": [item.to_document() for item in self.argument_provenance],
            "member_results": [item.to_document() for item in self.member_results],
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
                "ForEach partial report does not account for every frozen omission",
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
            "format": "foreach-partial-challenge-report/1",
            "task_id": self.task_id,
            "admission_plan_id": self.admission_plan.plan_id,
            "partials": [item.to_document() for item in self.partials],
        }

    def to_document(self) -> JSONObject:
        return {**self._preimage(), "report_id": self.report_id}


@dataclass(frozen=True, slots=True)
class ForEachAgentChoicePerturbation:
    witness_id: str
    materialization_id: str
    event_seq: int
    argument_pointer: str
    original_value: JSONValue
    replacement_value: JSONValue
    trace: tuple[TraceEvent, ...]
    member_results: tuple[AtomCheckResult, ...]

    def __post_init__(self) -> None:
        if self.original_value == self.replacement_value or any(
            not item.satisfied for item in self.member_results
        ):
            raise TaskFoundryError(
                "foreach_agent_choice_load_bearing",
                "Changing one ForEach AgentChoice caused a member checker to fail",
                event_seq=self.event_seq,
                argument_pointer=self.argument_pointer,
            )

    def to_document(self) -> JSONObject:
        return {
            "format": "foreach-agent-choice-perturbation/1",
            "witness_id": self.witness_id,
            "materialization_id": self.materialization_id,
            "event_seq": self.event_seq,
            "argument_pointer": self.argument_pointer,
            "original_value": _json(self.original_value),
            "replacement_value": _json(self.replacement_value),
            "trace": [item.to_document() for item in self.trace],
            "member_results": [item.to_document() for item in self.member_results],
        }


@dataclass(frozen=True, slots=True)
class ForEachAgentChoiceProof:
    task_id: str
    admission_plan_id: str
    perturbations: tuple[ForEachAgentChoicePerturbation, ...]

    @property
    def proof_id(self) -> str:
        return hashlib.sha256(canonical_bytes(self._preimage())).hexdigest()

    def _preimage(self) -> JSONObject:
        return {
            "format": "foreach-agent-choice-proof/1",
            "task_id": self.task_id,
            "admission_plan_id": self.admission_plan_id,
            "perturbations": [item.to_document() for item in self.perturbations],
        }

    def to_document(self) -> JSONObject:
        return {**self._preimage(), "proof_id": self.proof_id}


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

    def to_document(self) -> JSONObject:
        return {
            "format": "foreach-noop-challenge/1",
            "task_id": self.task_id,
            "admission_plan_id": self.admission_plan_id,
            "materialization_id": self.materialization_id,
            "member_results": [item.to_document() for item in self.member_results],
        }


@dataclass(frozen=True, slots=True)
class ForEachWrongAnswerChallenge:
    task_id: str
    admission_plan_id: str
    member_index: int
    materialization_id: str
    trace: tuple[TraceEvent, ...]
    baseline_final_answer: JSONObject
    wrong_final_answer: JSONObject
    baseline_member_results: tuple[AtomCheckResult, ...]
    member_results: tuple[AtomCheckResult, ...]

    def __post_init__(self) -> None:
        if (
            not 0 <= self.member_index < len(self.member_results)
            or len(self.baseline_member_results) != len(self.member_results)
            or any(not item.satisfied for item in self.baseline_member_results)
            or self.baseline_final_answer == self.wrong_final_answer
        ):
            raise TaskFoundryError(
                "foreach_wrong_answer_baseline_invalid",
                "ForEach wrong-answer challenge requires one valid changed member answer",
            )
        for index, result in enumerate(self.member_results):
            if index == self.member_index:
                valid = not result.satisfied and result.answer_ok is False
            else:
                valid = result.satisfied
            if not valid:
                raise TaskFoundryError(
                    "foreach_wrong_answer_not_discriminated",
                    "ForEach wrong answer must fail only the planned member",
                    member_index=self.member_index,
                    observed_index=index,
                )

    def to_document(self) -> JSONObject:
        return {
            "format": "foreach-wrong-answer-challenge/1",
            "task_id": self.task_id,
            "admission_plan_id": self.admission_plan_id,
            "member_index": self.member_index,
            "materialization_id": self.materialization_id,
            "trace": [item.to_document() for item in self.trace],
            "baseline_final_answer": _json_object(self.baseline_final_answer),
            "wrong_final_answer": _json_object(self.wrong_final_answer),
            "baseline_member_results": [
                item.to_document() for item in self.baseline_member_results
            ],
            "member_results": [item.to_document() for item in self.member_results],
        }


@dataclass(frozen=True, slots=True)
class ForEachCollateralChallenge:
    task_id: str
    admission_plan_id: str
    control_task_id: str
    materialization_id: str
    foreach_trace: tuple[TraceEvent, ...]
    control_trace: tuple[TraceEvent, ...]
    final_answer: JSONObject
    baseline_member_results: tuple[AtomCheckResult, ...]
    control_result: AtomCheckResult
    collateral_member_results: tuple[AtomCheckResult, ...]

    def __post_init__(self) -> None:
        if not self.control_result.satisfied or any(
            not item.satisfied for item in self.baseline_member_results
        ):
            raise TaskFoundryError(
                "foreach_collateral_control_failed",
                "ForEach collateral challenge requires successful baseline and control Tasks",
            )
        if len(self.baseline_member_results) != len(self.collateral_member_results) or any(
            item.satisfied
            or item.collateral_ok is not False
            or not item.required_effects_ok
            or item.process_ok is False
            for item in self.collateral_member_results
        ):
            raise TaskFoundryError(
                "foreach_collateral_not_discriminated",
                "ForEach checker did not isolate the out-of-selection state change as collateral",
            )

    def to_document(self) -> JSONObject:
        return {
            "format": "foreach-collateral-challenge/1",
            "task_id": self.task_id,
            "admission_plan_id": self.admission_plan_id,
            "control_task_id": self.control_task_id,
            "materialization_id": self.materialization_id,
            "foreach_trace": [item.to_document() for item in self.foreach_trace],
            "control_trace": [item.to_document() for item in self.control_trace],
            "final_answer": _json_object(self.final_answer),
            "baseline_member_results": [
                item.to_document() for item in self.baseline_member_results
            ],
            "control_result": self.control_result.to_document(),
            "collateral_member_results": [
                item.to_document() for item in self.collateral_member_results
            ],
        }


@dataclass(frozen=True, slots=True)
class ForEachAlternativeOrderProof:
    task_id: str
    admission_plan_id: str
    reference_witness_id: str
    materialization_id: str
    challenge_instruction_digest: str
    member_action_order: tuple[int, ...]
    trace: tuple[TraceEvent, ...]
    final_answer: JSONObject
    argument_provenance: tuple[ArgumentProvenance, ...]
    member_results: tuple[AtomCheckResult, ...]

    def __post_init__(self) -> None:
        if self.member_action_order != tuple(reversed(range(len(self.member_results)))):
            raise TaskFoundryError(
                "foreach_alternative_order_not_reversed",
                "ForEach alternative route did not first act on every member in reverse order",
            )
        if any(not item.satisfied for item in self.member_results):
            raise TaskFoundryError(
                "foreach_alternative_order_rejected",
                "ForEach checker rejected the reverse-order public route",
            )

    @property
    def proof_id(self) -> str:
        return hashlib.sha256(canonical_bytes(self._preimage())).hexdigest()

    def _preimage(self) -> JSONObject:
        return {
            "format": "foreach-alternative-order-proof/1",
            "task_id": self.task_id,
            "admission_plan_id": self.admission_plan_id,
            "reference_witness_id": self.reference_witness_id,
            "materialization_id": self.materialization_id,
            "challenge_instruction_digest": self.challenge_instruction_digest,
            "member_action_order": list(self.member_action_order),
            "trace": [item.to_document() for item in self.trace],
            "final_answer": _json_object(self.final_answer),
            "argument_provenance": [item.to_document() for item in self.argument_provenance],
            "member_results": [item.to_document() for item in self.member_results],
        }

    def to_document(self) -> JSONObject:
        return {**self._preimage(), "proof_id": self.proof_id}


@dataclass(frozen=True, slots=True)
class ForEachCheckerMutationResult:
    mutation_id: str
    omitted_member_index: int
    canonical_accepts: bool
    mutant_accepts: bool
    killed: bool

    def __post_init__(self) -> None:
        if not self.killed:
            raise TaskFoundryError(
                "foreach_checker_mutant_survived",
                "ForEach ignore-member checker mutant survived its partial challenge",
                mutation_id=self.mutation_id,
            )

    def to_document(self) -> JSONObject:
        return {
            "mutation_id": self.mutation_id,
            "omitted_member_index": self.omitted_member_index,
            "canonical_accepts": self.canonical_accepts,
            "mutant_accepts": self.mutant_accepts,
            "killed": self.killed,
        }


@dataclass(frozen=True, slots=True)
class ForEachCheckerMutationReport:
    task_id: str
    admission_plan_id: str
    mutations: tuple[ForEachCheckerMutationResult, ...]

    @property
    def report_id(self) -> str:
        return hashlib.sha256(canonical_bytes(self._preimage())).hexdigest()

    def _preimage(self) -> JSONObject:
        return {
            "format": "foreach-checker-mutation-report/1",
            "task_id": self.task_id,
            "admission_plan_id": self.admission_plan_id,
            "mutations": [item.to_document() for item in self.mutations],
        }

    def to_document(self) -> JSONObject:
        return {**self._preimage(), "report_id": self.report_id}


@dataclass(frozen=True, slots=True)
class ForEachAdmissionReport:
    solved: SolvedForEachTask
    noop: ForEachNoOpChallenge
    wrong_answer: ForEachWrongAnswerChallenge | None
    partials: ForEachPartialChallengeReport
    agent_choices: ForEachAgentChoiceProof
    alternative_order: ForEachAlternativeOrderProof
    collateral: ForEachCollateralChallenge
    checker_mutations: ForEachCheckerMutationReport

    def __post_init__(self) -> None:
        task = self.solved.task
        task_id = task.task_id
        plan_id = self.solved.admission_plan.plan_id
        component_pairs: tuple[tuple[str, str], ...] = (
            (self.noop.task_id, self.noop.admission_plan_id),
            (self.partials.task_id, self.partials.admission_plan.plan_id),
            (self.agent_choices.task_id, self.agent_choices.admission_plan_id),
            (self.alternative_order.task_id, self.alternative_order.admission_plan_id),
            (self.collateral.task_id, self.collateral.admission_plan_id),
            (self.checker_mutations.task_id, self.checker_mutations.admission_plan_id),
        )
        if self.wrong_answer is not None:
            component_pairs = (
                *component_pairs,
                (self.wrong_answer.task_id, self.wrong_answer.admission_plan_id),
            )
        if any(
            item_task != task_id or item_plan != plan_id for item_task, item_plan in component_pairs
        ):
            raise TaskFoundryError(
                "foreach_admission_identity_mismatch",
                "ForEach admission evidence does not share one Task and plan",
            )
        planned_wrong = self.solved.admission_plan.wrong_answer_member_index
        if (planned_wrong is None) != (self.wrong_answer is None) or (
            self.wrong_answer is not None and self.wrong_answer.member_index != planned_wrong
        ):
            raise TaskFoundryError(
                "foreach_wrong_answer_admission_incomplete",
                "ForEach wrong-answer evidence differs from its frozen plan",
            )
        expected_choices = {
            (witness.witness_id, item.event_seq, item.argument_pointer)
            for witness in self.solved.witnesses
            for item in witness.argument_provenance
            if item.source_kind == "agent_choice"
        }
        actual_choices = {
            (item.witness_id, item.event_seq, item.argument_pointer)
            for item in self.agent_choices.perturbations
        }
        if expected_choices != actual_choices or len(actual_choices) != len(
            self.agent_choices.perturbations
        ):
            raise TaskFoundryError(
                "foreach_admission_agent_choice_incomplete",
                "ForEach admission does not perturb every AgentChoice exactly once",
            )
        if self.collateral.control_task_id != self.solved.admission_plan.collateral_task_id:
            raise TaskFoundryError(
                "foreach_admission_collateral_target_mismatch",
                "ForEach collateral result used another control Task",
            )
        if self.alternative_order.reference_witness_id not in {
            item.witness_id for item in self.solved.witnesses
        }:
            raise TaskFoundryError(
                "foreach_admission_alternative_reference_missing",
                "ForEach alternative route does not reference an admitted witness",
            )
        if tuple(item.omitted_member_index for item in self.checker_mutations.mutations) != (
            self.solved.admission_plan.omitted_member_indices
        ):
            raise TaskFoundryError(
                "foreach_admission_mutations_incomplete",
                "ForEach checker mutation report differs from its frozen plan",
            )
        witness_materializations = {item.materialization_id for item in self.solved.witnesses}
        later_materializations = {
            self.noop.materialization_id,
            self.alternative_order.materialization_id,
            self.collateral.materialization_id,
            *(item.materialization_id for item in self.partials.partials),
            *(item.materialization_id for item in self.agent_choices.perturbations),
        }
        if self.wrong_answer is not None:
            later_materializations.add(self.wrong_answer.materialization_id)
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
            "format": "foreach-admission-report/1",
            "task_id": self.solved.task.task_id,
            "admission_plan": self.solved.admission_plan.to_document(),
            "witnesses": [item.to_document() for item in self.solved.witnesses],
            "noop": self.noop.to_document(),
            "wrong_answer": (
                None if self.wrong_answer is None else self.wrong_answer.to_document()
            ),
            "partials": self.partials.to_document(),
            "agent_choices": self.agent_choices.to_document(),
            "alternative_order": self.alternative_order.to_document(),
            "collateral": self.collateral.to_document(),
            "checker_mutations": self.checker_mutations.to_document(),
            "not_applicable": (
                {"wrong_answer": "member answer schema has no required fields"}
                if self.wrong_answer is None
                else {}
            ),
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
            "format": "foreach-task-pack/1",
            "task": self.task.to_document(),
            "admission": self.admission.to_document(),
        }

    def to_document(self) -> JSONObject:
        return {**self._preimage(), "task_pack_id": self.task_pack_id}


def seal_foreach_task_pack(
    solved: SolvedForEachTask,
    noop: ForEachNoOpChallenge,
    wrong_answer: ForEachWrongAnswerChallenge | None,
    partials: ForEachPartialChallengeReport,
    agent_choices: ForEachAgentChoiceProof,
    alternative_order: ForEachAlternativeOrderProof,
    collateral: ForEachCollateralChallenge,
    checker_mutations: ForEachCheckerMutationReport,
) -> ForEachTaskPack:
    _verify_task_preimage(solved.task)
    admission = ForEachAdmissionReport(
        solved,
        noop,
        wrong_answer,
        partials,
        agent_choices,
        alternative_order,
        collateral,
        checker_mutations,
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
                _evaluate_report_atom(
                    session,
                    AtomCheckRequest(
                        task.capability_id,
                        before,
                        after,
                        binding.protected_binding,
                        episode.trace,
                        answers[position],
                        contexts[position],
                    ),
                    task.member_answer_schema,
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
        admission_plan,
        cast(tuple[ForEachWitness, ForEachWitness], tuple(witnesses)),
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
        with prepared.open(instance) as session:
            reset = session.actor.reset(task.start_case.reset_input)
            before = session.trusted.inspect(instance)
            bindings = _resolve_complete_selection(session, task, before)
            tool_specs = session.actor.tools()
            episode = run_public_episode(
                actor=session.actor,
                instruction=partial_instruction,
                reset_observation=reset,
                tool_specs=tool_specs,
                answer_schema=partial_answer_schema,
                route=selected_route,
                max_provider_turns=max_provider_turns,
            )
            partial_answers = episode.final_answer.get("results")
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
            after = session.trusted.inspect(instance)
            contexts = _contexts(task, bindings)
            results = tuple(
                _evaluate_report_atom(
                    session,
                    AtomCheckRequest(
                        task.capability_id,
                        before,
                        after,
                        binding.protected_binding,
                        episode.trace,
                        answers[position],
                        contexts[position],
                    ),
                    task.member_answer_schema,
                )
                for position, binding in enumerate(bindings)
            )
            partials.append(
                ForEachPartialChallenge(
                    task.task_id,
                    solved.admission_plan.plan_id,
                    omitted_index,
                    task.semantic_keys[omitted_index],
                    session.identity.materialization_id,
                    episode.trace,
                    episode.final_answer,
                    resolve_argument_provenance(
                        trace=episode.trace,
                        instruction_values={
                            "selected_targets": [
                                _json_object(item) for item in included_descriptors
                            ]
                        },
                        reset_observation=reset,
                        tool_specs=tool_specs,
                    ),
                    results,
                )
            )
    return ForEachPartialChallengeReport(
        task.task_id,
        solved.admission_plan,
        tuple(partials),
    )


def prove_foreach_agent_choices_non_load_bearing(
    prepared: OpenPreparedRelease,
    solved: SolvedForEachTask,
    instance_root: Path,
) -> ForEachAgentChoiceProof:
    """Perturb every witness AgentChoice independently on a fresh full-selection replay."""

    task = solved.task
    _verify_task(prepared, task)
    choices = [
        (witness, occurrence)
        for witness in solved.witnesses
        for occurrence in witness.argument_provenance
        if occurrence.source_kind == "agent_choice"
    ]
    perturbations: list[ForEachAgentChoicePerturbation] = []
    for index, (witness, occurrence) in enumerate(choices, start=1):
        instance = Path(instance_root) / f"choice-{index}"
        with prepared.open(instance) as session:
            reset = session.actor.reset(task.start_case.reset_input)
            before = session.trusted.inspect(instance)
            bindings = _resolve_complete_selection(session, task, before)
            tool_specs = {item["name"]: item for item in session.actor.tools()}
            source_event = next(item for item in witness.trace if item.seq == occurrence.event_seq)
            source_spec = tool_specs[source_event.tool_name]
            schema = _schema_at_pointer(source_spec["input_schema"], occurrence.argument_pointer)
            replacement = _alternative_value(schema, occurrence.value)
            if replacement is _NO_ALTERNATIVE:
                raise TaskFoundryError(
                    "foreach_agent_choice_not_perturbable",
                    "ForEach AgentChoice schema has no distinct valid alternative",
                    event_seq=occurrence.event_seq,
                    argument_pointer=occurrence.argument_pointer,
                )
            replay_trace = _replay_witness_trace(
                session,
                witness,
                reset,
                tool_specs,
                perturbed_occurrence=(occurrence.event_seq, occurrence.argument_pointer),
                replacement=cast(JSONValue, replacement),
            )
            answers = witness.final_answer.get("results")
            if not isinstance(answers, list) or len(answers) != len(bindings):
                raise TaskFoundryError(
                    "foreach_replay_answer_count_mismatch",
                    "ForEach witness answer cannot be replayed over the complete selection",
                )
            after = session.trusted.inspect(instance)
            contexts = _contexts(task, bindings)
            results = tuple(
                _evaluate_report_atom(
                    session,
                    AtomCheckRequest(
                        task.capability_id,
                        before,
                        after,
                        binding.protected_binding,
                        replay_trace,
                        answers[position],
                        contexts[position],
                    ),
                    task.member_answer_schema,
                )
                for position, binding in enumerate(bindings)
            )
            perturbations.append(
                ForEachAgentChoicePerturbation(
                    witness.witness_id,
                    session.identity.materialization_id,
                    occurrence.event_seq,
                    occurrence.argument_pointer,
                    occurrence.value,
                    cast(JSONValue, replacement),
                    replay_trace,
                    results,
                )
            )
    if len(perturbations) != len(choices):
        raise TaskFoundryError(
            "foreach_agent_choice_proof_incomplete",
            "ForEach AgentChoice proof omitted a witness occurrence",
        )
    return ForEachAgentChoiceProof(
        task.task_id,
        solved.admission_plan.plan_id,
        tuple(perturbations),
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


def challenge_foreach_wrong_answer(
    prepared: OpenPreparedRelease,
    solved: SolvedForEachTask,
    instance_root: Path,
) -> ForEachWrongAnswerChallenge | None:
    task = solved.task
    _verify_task(prepared, task)
    member_index = solved.admission_plan.wrong_answer_member_index
    if member_index is None:
        return None
    witness = solved.witnesses[0]
    with prepared.open(instance_root) as session:
        reset = session.actor.reset(task.start_case.reset_input)
        before = session.trusted.inspect(instance_root)
        bindings = _resolve_complete_selection(session, task, before)
        contexts = _contexts(task, bindings)
        tool_specs = {item["name"]: item for item in session.actor.tools()}
        replay_trace = _replay_witness_trace(session, witness, reset, tool_specs)
        answers = witness.final_answer.get("results")
        if not isinstance(answers, list) or len(answers) != len(bindings):
            raise TaskFoundryError(
                "foreach_wrong_answer_baseline_count_mismatch",
                "ForEach wrong-answer baseline does not cover the complete selection",
            )
        after = session.trusted.inspect(instance_root)
        probe_results = tuple(
            _evaluate_report_atom(
                session,
                AtomCheckRequest(
                    task.capability_id,
                    before,
                    after,
                    binding.protected_binding,
                    replay_trace,
                    _json_object(answers[position]),
                    contexts[position],
                ),
                task.member_answer_schema,
            )
            for position, binding in enumerate(bindings)
        )
        correct_answers = [
            _rebound_final_answer(item, task.member_answer_schema) for item in probe_results
        ]
        baseline_results = tuple(
            _evaluate_report_atom(
                session,
                AtomCheckRequest(
                    task.capability_id,
                    before,
                    after,
                    binding.protected_binding,
                    replay_trace,
                    correct_answers[position],
                    contexts[position],
                ),
                task.member_answer_schema,
            )
            for position, binding in enumerate(bindings)
        )
        if any(not item.satisfied for item in baseline_results):
            raise TaskFoundryError(
                "foreach_wrong_answer_baseline_failed",
                "ForEach wrong-answer baseline did not satisfy every member",
            )
        wrong_member = _wrong_answer(
            task.member_answer_schema,
            baseline_results[member_index].report_values,
        )
        if wrong_member is None:
            raise TaskFoundryError(
                "foreach_wrong_answer_unavailable",
                "Planned ForEach member answer has no schema-valid wrong alternative",
            )
        baseline_final = _json_object({"results": correct_answers})
        wrong_answers = [_json_object(item) for item in correct_answers]
        wrong_answers[member_index] = wrong_member
        wrong_final = _json_object({"results": wrong_answers})
        wrong_results = tuple(
            _evaluate_report_atom(
                session,
                AtomCheckRequest(
                    task.capability_id,
                    before,
                    after,
                    binding.protected_binding,
                    replay_trace,
                    wrong_answers[position],
                    contexts[position],
                ),
                task.member_answer_schema,
            )
            for position, binding in enumerate(bindings)
        )
        return ForEachWrongAnswerChallenge(
            task.task_id,
            solved.admission_plan.plan_id,
            member_index,
            session.identity.materialization_id,
            replay_trace,
            baseline_final,
            wrong_final,
            baseline_results,
            wrong_results,
        )


def challenge_foreach_collateral(
    prepared: OpenPreparedRelease,
    solved: SolvedForEachTask,
    atom_task_universe: tuple[AtomTask, ...],
    instance_root: Path,
    *,
    route: AgentRoute | None = None,
    max_provider_turns: int = 12,
) -> ForEachCollateralChallenge:
    task = solved.task
    _verify_task(prepared, task)
    control_task = _task_by_id(
        atom_task_universe,
        solved.admission_plan.collateral_task_id,
    )
    _verify_checker_preimage(prepared, control_task)
    selected_route = route or AgentRoute(max_provider_turns=max_provider_turns)
    with prepared.open(instance_root) as session:
        reset = session.actor.reset(task.start_case.reset_input)
        before = session.trusted.inspect(instance_root)
        bindings = _resolve_complete_selection(session, task, before)
        contexts = _contexts(task, bindings)
        foreach_episode = run_public_episode(
            actor=session.actor,
            instruction=task.instruction,
            reset_observation=reset,
            tool_specs=session.actor.tools(),
            answer_schema=task.answer_schema,
            route=selected_route,
            max_provider_turns=max_provider_turns,
        )
        answers = foreach_episode.final_answer.get("results")
        if not isinstance(answers, list) or len(answers) != len(bindings):
            raise TaskFoundryError(
                "foreach_collateral_answer_count_mismatch",
                "ForEach collateral baseline answer does not cover the complete selection",
            )
        after_foreach = session.trusted.inspect(instance_root)
        baseline_results = tuple(
            _evaluate_report_atom(
                session,
                AtomCheckRequest(
                    task.capability_id,
                    before,
                    after_foreach,
                    binding.protected_binding,
                    foreach_episode.trace,
                    answers[position],
                    contexts[position],
                ),
                task.member_answer_schema,
            )
            for position, binding in enumerate(bindings)
        )
        control_binding = _resolve_binding(session, control_task, after_foreach)
        control_episode = run_public_episode(
            actor=session.actor,
            instruction=control_task.instruction,
            reset_observation=reset,
            tool_specs=session.actor.tools(),
            answer_schema=control_task.answer_schema,
            route=selected_route,
            max_provider_turns=max_provider_turns,
        )
        after_collateral = session.trusted.inspect(instance_root)
        control_result = _evaluate_report_atom(
            session,
            AtomCheckRequest(
                control_task.capability_id,
                after_foreach,
                after_collateral,
                control_binding.protected_binding,
                control_episode.trace,
                control_episode.final_answer,
                _context(
                    control_task.capability_id,
                    control_binding.semantic_key,
                    control_binding.protected_binding,
                ),
            ),
            control_task.answer_schema,
        )
        combined_trace = _combine_traces(foreach_episode.trace, control_episode.trace)
        collateral_results = tuple(
            _evaluate_report_atom(
                session,
                AtomCheckRequest(
                    task.capability_id,
                    before,
                    after_collateral,
                    binding.protected_binding,
                    combined_trace,
                    answers[position],
                    contexts[position],
                ),
                task.member_answer_schema,
            )
            for position, binding in enumerate(bindings)
        )
        return ForEachCollateralChallenge(
            task.task_id,
            solved.admission_plan.plan_id,
            control_task.task_id,
            session.identity.materialization_id,
            foreach_episode.trace,
            control_episode.trace,
            foreach_episode.final_answer,
            baseline_results,
            control_result,
            collateral_results,
        )


def prove_foreach_reverse_order(
    prepared: OpenPreparedRelease,
    solved: SolvedForEachTask,
    instance_root: Path,
    *,
    route: AgentRoute | None = None,
    max_provider_turns: int = 12,
) -> ForEachAlternativeOrderProof:
    task = solved.task
    _verify_task(prepared, task)
    challenge_instruction = "\n\n".join((task.instruction, _REVERSE_ORDER_PROMPT))
    selected_route = route or AgentRoute(max_provider_turns=max_provider_turns)
    with prepared.open(instance_root) as session:
        reset = session.actor.reset(task.start_case.reset_input)
        before = session.trusted.inspect(instance_root)
        bindings = _resolve_complete_selection(session, task, before)
        tool_specs = session.actor.tools()
        episode = run_public_episode(
            actor=session.actor,
            instruction=challenge_instruction,
            reset_observation=reset,
            tool_specs=tool_specs,
            answer_schema=task.answer_schema,
            route=selected_route,
            max_provider_turns=max_provider_turns,
        )
        answers = episode.final_answer.get("results")
        if not isinstance(answers, list) or len(answers) != len(bindings):
            raise TaskFoundryError(
                "foreach_reverse_answer_count_mismatch",
                "Reverse-order ForEach answer does not cover the complete selection",
            )
        provenance = resolve_argument_provenance(
            trace=episode.trace,
            instruction_values={
                "selected_targets": [_json_object(item) for item in task.public_descriptors]
            },
            reset_observation=reset,
            tool_specs=tool_specs,
        )
        member_order = _member_action_order(
            episode.trace,
            provenance,
            len(task.semantic_keys),
        )
        after = session.trusted.inspect(instance_root)
        contexts = _contexts(task, bindings)
        results = tuple(
            _evaluate_report_atom(
                session,
                AtomCheckRequest(
                    task.capability_id,
                    before,
                    after,
                    binding.protected_binding,
                    episode.trace,
                    answers[position],
                    contexts[position],
                ),
                task.member_answer_schema,
            )
            for position, binding in enumerate(bindings)
        )
        return ForEachAlternativeOrderProof(
            task.task_id,
            solved.admission_plan.plan_id,
            solved.witnesses[0].witness_id,
            session.identity.materialization_id,
            hashlib.sha256(challenge_instruction.encode()).hexdigest(),
            member_order,
            episode.trace,
            episode.final_answer,
            provenance,
            results,
        )


def run_foreach_checker_mutations(
    solved: SolvedForEachTask,
    partials: ForEachPartialChallengeReport,
) -> ForEachCheckerMutationReport:
    if (
        partials.task_id != solved.task.task_id
        or partials.admission_plan.plan_id != solved.admission_plan.plan_id
    ):
        raise TaskFoundryError(
            "foreach_mutation_plan_mismatch",
            "ForEach mutation evidence belongs to another Task or plan",
        )
    mutations = tuple(
        ForEachCheckerMutationResult(
            f"ignore_member_{item.omitted_member_index}",
            item.omitted_member_index,
            all(result.satisfied for result in item.member_results),
            all(
                result.satisfied
                for index, result in enumerate(item.member_results)
                if index != item.omitted_member_index
            ),
            not all(result.satisfied for result in item.member_results)
            and all(
                result.satisfied
                for index, result in enumerate(item.member_results)
                if index != item.omitted_member_index
            ),
        )
        for item in partials.partials
    )
    return ForEachCheckerMutationReport(
        solved.task.task_id,
        solved.admission_plan.plan_id,
        mutations,
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
    with prepared.open(instance_root) as session:
        session.actor.reset(task.start_case.reset_input)
        facts = session.trusted.inspect(instance_root)
        catalog = {item.capability_id: item for item in session.trusted.capabilities()}
        collateral_task = _select_collateral_task(
            task,
            atom_task_universe,
            catalog,
        )
        if collateral_task is None:
            raise TaskFoundryError(
                "foreach_collateral_target_missing",
                "No out-of-selection state-change Atom Task can challenge ForEach collateral",
            )
        _resolve_binding(session, collateral_task, facts)
    return ForEachAdmissionPlan(
        task.task_id,
        tuple(range(len(task.semantic_keys))),
        0 if task.member_answer_schema.get("required") else None,
        collateral_task.task_id,
    )


def _select_collateral_task(
    task: ForEachTask,
    atom_task_universe: tuple[AtomTask, ...],
    catalog: dict[str, Any],
) -> AtomTask | None:
    candidates = tuple(
        sorted(
            (
                item
                for item in atom_task_universe
                if item.start_case == task.start_case
                and item.capability_id != task.capability_id
                and item.semantic_key not in task.semantic_keys
                and catalog[item.capability_id].task_kind == "state_change"
            ),
            key=lambda item: (item.capability_id, item.semantic_key, item.task_id),
        )
    )
    return candidates[0] if candidates else None


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


def _replay_witness_trace(
    session: OpenPreparedSession,
    witness: ForEachWitness,
    reset_observation: JSONValue,
    tool_specs: dict[str, Any],
    *,
    perturbed_occurrence: tuple[int, str] = (-1, ""),
    replacement: JSONValue = None,
) -> tuple[TraceEvent, ...]:
    observations: dict[int, JSONObject] = {}
    trace: list[TraceEvent] = []
    provenance_by_event = {
        event.seq: tuple(
            item for item in witness.argument_provenance if item.event_seq == event.seq
        )
        for event in witness.trace
    }
    for event in witness.trace:
        arguments = _replay_arguments(
            event,
            provenance_by_event[event.seq],
            reset_observation,
            observations,
            perturbed_occurrence,
            replacement,
        )
        errors = tuple(
            Draft202012Validator(tool_specs[event.tool_name]["input_schema"]).iter_errors(arguments)
        )
        if errors:
            raise TaskFoundryError(
                "foreach_replay_arguments_invalid",
                "ForEach replay arguments violate the frozen ToolSpec",
                event_seq=event.seq,
                original_message=errors[0].message,
            )
        observation = _json_object(session.actor.invoke(event.tool_name, arguments))
        observations[event.seq] = observation
        trace.append(TraceEvent(event.seq, event.tool_name, arguments, observation))
    return tuple(trace)


def _member_action_order(
    trace: tuple[TraceEvent, ...],
    provenance: tuple[ArgumentProvenance, ...],
    member_count: int,
) -> tuple[int, ...]:
    prefix = "/public_descriptor/selected_targets/"
    by_event = {event.seq: event for event in trace}
    order: list[int] = []
    for occurrence in sorted(
        provenance,
        key=lambda item: (item.event_seq, item.argument_pointer),
    ):
        if occurrence.event_seq not in by_event or occurrence.source_kind != "task_literal":
            continue
        pointer = occurrence.source_pointer
        if not isinstance(pointer, str) or not pointer.startswith(prefix):
            continue
        token = pointer.removeprefix(prefix).partition("/")[0]
        if not token.isdigit():
            continue
        member_index = int(token)
        if member_index not in order:
            order.append(member_index)
    if set(order) != set(range(member_count)):
        raise TaskFoundryError(
            "foreach_alternative_order_incomplete",
            "Alternative ForEach route did not publicly act on every selected member",
            observed_order=order,
            member_count=member_count,
        )
    return tuple(order)


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
    "ForEachAgentChoicePerturbation",
    "ForEachAgentChoiceProof",
    "ForEachAlternativeOrderProof",
    "ForEachCheckerMutationReport",
    "ForEachCheckerMutationResult",
    "ForEachCollateralChallenge",
    "ForEachNoOpChallenge",
    "ForEachPartialChallenge",
    "ForEachPartialChallengeReport",
    "ForEachTask",
    "ForEachTaskPack",
    "ForEachWitness",
    "ForEachWrongAnswerChallenge",
    "SolvedForEachTask",
    "compile_foreach_tasks",
    "prove_foreach_agent_choices_non_load_bearing",
    "prove_foreach_reverse_order",
    "run_foreach_checker_mutations",
    "run_foreach_noop",
    "seal_foreach_task_pack",
    "challenge_foreach_partials",
    "challenge_foreach_wrong_answer",
    "challenge_foreach_collateral",
    "solve_foreach_task_twice",
]
