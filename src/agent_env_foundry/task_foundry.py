"""Executable Atom Task compilation and two-fresh-witness proof."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, cast

from jsonschema import Draft202012Validator

from agent_env_foundry.agents import AgentRoute
from agent_env_foundry.environment import JSONObject, JSONValue, ToolSpec
from agent_env_foundry.jsonvalue import is_json_object, is_json_value
from agent_env_foundry.preparation import OpenPreparedRelease, OpenPreparedSession
from agent_env_foundry.provenance import (
    ArgumentProvenance,
    resolve_argument_provenance,
    validate_argument_provenance,
)
from agent_env_foundry.public_agent import PublicEpisodeRun, run_public_episode
from agent_env_foundry.release import canonical_bytes
from agent_env_foundry.semantics import (
    AtomCheckRequest,
    AtomCheckResult,
    BindingCandidate,
    CapabilitySpec,
    EvaluationBinding,
    GoalEvaluationContext,
    StartCase,
    TraceEvent,
)

_ATOM_CHALLENGE_CATEGORIES = (
    "no_op",
    "wrong_target",
    "wrong_answer",
    "missing_process",
    "collateral",
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
    reset_observation: JSONValue
    trace: tuple[TraceEvent, ...]
    final_answer: JSONObject
    argument_provenance: tuple[ArgumentProvenance, ...]
    result: AtomCheckResult
    provider_turns: int
    usage: tuple[JSONObject | None, ...]

    def __post_init__(self) -> None:
        if not is_json_value(self.reset_observation):
            raise TaskFoundryError(
                "witness_reset_not_json",
                "Atom witness reset observation is not JSON",
            )
        try:
            validate_argument_provenance(self.trace, self.argument_provenance)
        except Exception as exc:
            raise TaskFoundryError(
                "witness_provenance_invalid",
                "Atom witness argument provenance is incomplete or invalid",
                original_code=type(exc).__name__,
                original_message=str(exc),
            ) from exc

    @property
    def witness_id(self) -> str:
        return hashlib.sha256(canonical_bytes(self.to_document())).hexdigest()

    def to_document(self) -> JSONObject:
        return {
            "format": "atom-witness/1",
            "task_id": self.task_id,
            "materialization_id": self.materialization_id,
            "reset_observation": _json(self.reset_observation),
            "trace": [item.to_document() for item in self.trace],
            "final_answer": _json_object(self.final_answer),
            "argument_provenance": [item.to_document() for item in self.argument_provenance],
            "result": self.result.to_document(),
            "provider_turns": self.provider_turns,
            "usage": [_json(item) for item in self.usage],
        }


@dataclass(frozen=True, slots=True)
class AtomPlannedChallenge:
    category: str
    applicable: bool
    target_task_id: str | None
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
        if self.category in {"wrong_target", "collateral"} and self.applicable:
            if not self.target_task_id:
                raise TaskFoundryError(
                    f"admission_plan_{self.category}_missing",
                    f"Applicable {self.category} challenge requires its frozen target Task",
                )
        elif self.target_task_id is not None:
            raise TaskFoundryError(
                "admission_plan_target_unexpected",
                "Only an applicable wrong-target challenge may freeze a target Task",
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
            "target_task_id": self.target_task_id,
            "final_answer": None if self.final_answer is None else _json_object(self.final_answer),
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class AtomCheckerMutationSpec:
    mutation_id: str
    challenge_category: str
    result_field: str

    def __post_init__(self) -> None:
        allowed_fields = {
            "satisfied",
            "required_effects_ok",
            "collateral_ok",
            "answer_ok",
            "process_ok",
        }
        if (
            self.mutation_id != f"force_{self.result_field}"
            or self.challenge_category not in _ATOM_CHALLENGE_CATEGORIES
            or self.result_field not in allowed_fields
        ):
            raise TaskFoundryError(
                "checker_mutation_spec_invalid",
                "Atom checker mutation must force one declared result axis",
            )

    def to_document(self) -> JSONObject:
        return {
            "mutation_id": self.mutation_id,
            "challenge_category": self.challenge_category,
            "result_field": self.result_field,
        }


@dataclass(frozen=True, slots=True)
class AtomAdmissionPlan:
    task_id: str
    agent_choice_policy: str
    no_op_result: AtomCheckResult
    checker_mutations: tuple[AtomCheckerMutationSpec, ...]
    challenges: tuple[AtomPlannedChallenge, ...]

    def __post_init__(self) -> None:
        if self.agent_choice_policy != "perturb_each_occurrence":
            raise TaskFoundryError(
                "admission_agent_choice_policy_invalid",
                "Atom admission must perturb every AgentChoice occurrence",
            )
        if self.no_op_result.satisfied:
            raise TaskFoundryError(
                "admission_plan_noop_accepted",
                "Atom admission no-op result must reject the Task before witnesses",
            )
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
        expected_mutations = _derive_checker_mutation_specs(
            self.challenges,
            self.no_op_result,
        )
        if self.checker_mutations != expected_mutations:
            raise TaskFoundryError(
                "checker_mutation_plan_incomplete",
                "Atom admission plan must freeze every applicable result-axis mutation",
            )

    @property
    def plan_id(self) -> str:
        return hashlib.sha256(canonical_bytes(self._preimage())).hexdigest()

    def _preimage(self) -> JSONObject:
        return {
            "format": "atom-admission-plan/3",
            "task_id": self.task_id,
            "agent_choice_policy": self.agent_choice_policy,
            "no_op_result": self.no_op_result.to_document(),
            "checker_mutations": [item.to_document() for item in self.checker_mutations],
            "challenges": [item.to_document() for item in self.challenges],
        }

    def to_document(self) -> JSONObject:
        return {**self._preimage(), "plan_id": self.plan_id}


def _derive_checker_mutation_specs(
    challenges: tuple[AtomPlannedChallenge, ...],
    no_op_result: AtomCheckResult,
) -> tuple[AtomCheckerMutationSpec, ...]:
    by_category = {item.category: item for item in challenges}
    if no_op_result.satisfied:
        raise TaskFoundryError(
            "admission_plan_noop_accepted",
            "Atom admission cannot derive mutations from an accepted no-op",
        )
    specs = [AtomCheckerMutationSpec("force_satisfied", "no_op", "satisfied")]
    if not no_op_result.required_effects_ok:
        specs.append(
            AtomCheckerMutationSpec(
                "force_required_effects_ok",
                "no_op",
                "required_effects_ok",
            )
        )
    for category, field in (
        ("wrong_answer", "answer_ok"),
        ("missing_process", "process_ok"),
        ("collateral", "collateral_ok"),
    ):
        planned = by_category.get(category)
        if planned is not None and planned.applicable:
            specs.append(AtomCheckerMutationSpec(f"force_{field}", category, field))
    return tuple(specs)


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
    materialization_id: str | None
    trace: tuple[TraceEvent, ...]
    final_answer: JSONObject
    result: AtomCheckResult | None
    control_result: AtomCheckResult | None
    reason: str | None

    def __post_init__(self) -> None:
        if self.applicable:
            if not self.materialization_id or self.result is None or self.reason is not None:
                raise TaskFoundryError(
                    "challenge_evidence_incomplete",
                    "Applicable Atom challenge requires materialization, result and no reason",
                    category=self.category,
                )
        elif self.materialization_id is not None or self.result is not None or self.reason is None:
            raise TaskFoundryError(
                "challenge_non_applicable_evidence_invalid",
                "Non-applicable Atom challenge requires only its frozen reason",
                category=self.category,
            )
        requires_control = self.applicable and self.category in {"wrong_target", "collateral"}
        if requires_control and (self.control_result is None or not self.control_result.satisfied):
            raise TaskFoundryError(
                "challenge_control_result_missing",
                "Target-based Atom challenge requires a successful control Task result",
                category=self.category,
            )
        if not requires_control and self.control_result is not None:
            raise TaskFoundryError(
                "challenge_control_result_unexpected",
                "Only an applicable target-based challenge may carry a control result",
                category=self.category,
            )

    def to_document(self) -> JSONObject:
        return {
            "format": "atom-challenge/1",
            "category": self.category,
            "applicable": self.applicable,
            "materialization_id": self.materialization_id,
            "trace": [item.to_document() for item in self.trace],
            "final_answer": _json_object(self.final_answer),
            "result": None if self.result is None else self.result.to_document(),
            "control_result": (
                None if self.control_result is None else self.control_result.to_document()
            ),
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
        no_op = self.challenges[0]
        if no_op.result != self.admission_plan.no_op_result:
            raise TaskFoundryError(
                "challenge_noop_result_drift",
                "Physical no-op result differs from its pre-witness frozen axes",
            )

    def to_document(self) -> JSONObject:
        return {
            "format": "atom-challenge-report/1",
            "task_id": self.task_id,
            "admission_plan_id": self.admission_plan.plan_id,
            "challenges": [item.to_document() for item in self.challenges],
        }


@dataclass(frozen=True, slots=True)
class AtomCheckerMutationResult:
    spec: AtomCheckerMutationSpec
    challenge_materialization_id: str
    original_result: JSONObject
    mutant_result: JSONObject
    killed: bool

    def __post_init__(self) -> None:
        if not self.killed:
            raise TaskFoundryError(
                "checker_mutant_survived",
                "Planned Atom checker result-axis mutant survived its physical challenge",
                mutation_id=self.spec.mutation_id,
                challenge_category=self.spec.challenge_category,
            )

    def to_document(self) -> JSONObject:
        return {
            "format": "atom-checker-mutation-result/1",
            "spec": self.spec.to_document(),
            "challenge_materialization_id": self.challenge_materialization_id,
            "original_result": _json_object(self.original_result),
            "mutant_result": _json_object(self.mutant_result),
            "killed": self.killed,
        }


@dataclass(frozen=True, slots=True)
class AtomCheckerMutationReport:
    task_id: str
    admission_plan_id: str
    mutations: tuple[AtomCheckerMutationResult, ...]

    @property
    def report_id(self) -> str:
        return hashlib.sha256(canonical_bytes(self._preimage())).hexdigest()

    def _preimage(self) -> JSONObject:
        return {
            "format": "atom-checker-mutation-report/1",
            "task_id": self.task_id,
            "admission_plan_id": self.admission_plan_id,
            "mutations": [item.to_document() for item in self.mutations],
        }

    def to_document(self) -> JSONObject:
        return {**self._preimage(), "report_id": self.report_id}


def run_atom_checker_mutations(
    plan: AtomAdmissionPlan,
    challenge_report: AtomChallengeReport,
) -> AtomCheckerMutationReport:
    """Execute every pre-witness result-axis mutant against its live challenge result."""

    if (
        challenge_report.task_id != plan.task_id
        or challenge_report.admission_plan.plan_id != plan.plan_id
    ):
        raise TaskFoundryError(
            "checker_mutation_plan_mismatch",
            "Checker mutation inputs do not share one Task and AdmissionPlan",
        )
    challenges = {item.category: item for item in challenge_report.challenges}
    results: list[AtomCheckerMutationResult] = []
    for spec in plan.checker_mutations:
        challenge = challenges[spec.challenge_category]
        if not challenge.applicable or challenge.result is None or not challenge.materialization_id:
            raise TaskFoundryError(
                "checker_mutation_challenge_missing",
                "Planned checker mutant has no applicable physical challenge result",
                mutation_id=spec.mutation_id,
            )
        original = challenge.result.to_document()
        mutant = _json_object(original)
        field_was_false = mutant.get(spec.result_field) is False
        mutant[spec.result_field] = True
        results.append(
            AtomCheckerMutationResult(
                spec,
                challenge.materialization_id,
                original,
                mutant,
                field_was_false and mutant != original,
            )
        )
    if tuple(item.spec for item in results) != plan.checker_mutations:
        raise TaskFoundryError(
            "checker_mutation_report_incomplete",
            "Checker mutation report does not account for its frozen plan",
        )
    return AtomCheckerMutationReport(plan.task_id, plan.plan_id, tuple(results))


@dataclass(frozen=True, slots=True)
class AgentChoicePerturbation:
    witness_id: str
    materialization_id: str
    event_seq: int
    argument_pointer: str
    original_value: JSONValue
    replacement_value: JSONValue
    trace: tuple[TraceEvent, ...]
    result: AtomCheckResult

    def __post_init__(self) -> None:
        if (
            not self.witness_id
            or not self.materialization_id
            or self.event_seq <= 0
            or not self.argument_pointer.startswith("/")
        ):
            raise TaskFoundryError(
                "agent_choice_perturbation_identity_invalid",
                "AgentChoice perturbation identity is invalid",
            )
        if self.original_value == self.replacement_value:
            raise TaskFoundryError(
                "agent_choice_perturbation_unchanged",
                "AgentChoice perturbation must use a different schema-valid value",
            )
        if not self.result.satisfied:
            raise TaskFoundryError(
                "agent_choice_is_load_bearing",
                "Changing an AgentChoice caused the frozen checker to fail",
                event_seq=self.event_seq,
                argument_pointer=self.argument_pointer,
                result=self.result.to_document(),
            )

    def to_document(self) -> JSONObject:
        return {
            "format": "agent-choice-perturbation/1",
            "witness_id": self.witness_id,
            "materialization_id": self.materialization_id,
            "event_seq": self.event_seq,
            "argument_pointer": self.argument_pointer,
            "original_value": _json(self.original_value),
            "replacement_value": _json(self.replacement_value),
            "trace": [item.to_document() for item in self.trace],
            "result": self.result.to_document(),
        }


@dataclass(frozen=True, slots=True)
class AgentChoiceProof:
    task_id: str
    admission_plan_id: str
    perturbations: tuple[AgentChoicePerturbation, ...]

    @property
    def proof_id(self) -> str:
        return hashlib.sha256(canonical_bytes(self._preimage())).hexdigest()

    def _preimage(self) -> JSONObject:
        return {
            "format": "agent-choice-proof/1",
            "task_id": self.task_id,
            "admission_plan_id": self.admission_plan_id,
            "perturbations": [item.to_document() for item in self.perturbations],
        }

    def to_document(self) -> JSONObject:
        return {**self._preimage(), "proof_id": self.proof_id}


@dataclass(frozen=True, slots=True)
class AtomAdmissionReport:
    solved: SolvedAtomTask
    challenges: AtomChallengeReport
    agent_choices: AgentChoiceProof
    checker_mutations: AtomCheckerMutationReport

    def __post_init__(self) -> None:
        task_id = self.solved.task.task_id
        plan_id = self.solved.admission_plan.plan_id
        if (
            self.challenges.task_id != task_id
            or self.agent_choices.task_id != task_id
            or self.checker_mutations.task_id != task_id
            or self.challenges.admission_plan.plan_id != plan_id
            or self.agent_choices.admission_plan_id != plan_id
            or self.checker_mutations.admission_plan_id != plan_id
        ):
            raise TaskFoundryError(
                "atom_admission_identity_mismatch",
                "Atom admission evidence does not share one Task and AdmissionPlan",
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
                "atom_admission_agent_choice_incomplete",
                "Atom admission does not perturb every witness AgentChoice exactly once",
            )
        if tuple(item.spec for item in self.checker_mutations.mutations) != (
            self.solved.admission_plan.checker_mutations
        ):
            raise TaskFoundryError(
                "atom_admission_mutations_incomplete",
                "Atom admission mutation evidence differs from its frozen plan",
            )
        witness_materializations = {item.materialization_id for item in self.solved.witnesses}
        later_materializations = {
            item.materialization_id
            for item in self.challenges.challenges
            if item.materialization_id is not None
        } | {item.materialization_id for item in self.agent_choices.perturbations}
        if witness_materializations & later_materializations:
            raise TaskFoundryError(
                "atom_admission_materialization_reused",
                "Witness and post-witness evidence reused a materialization",
            )

    @property
    def report_id(self) -> str:
        return hashlib.sha256(canonical_bytes(self._preimage())).hexdigest()

    def _preimage(self) -> JSONObject:
        return {
            "format": "atom-admission-report/2",
            "task_id": self.solved.task.task_id,
            "admission_plan": self.solved.admission_plan.to_document(),
            "witnesses": [item.to_document() for item in self.solved.witnesses],
            "challenges": self.challenges.to_document(),
            "agent_choices": self.agent_choices.to_document(),
            "checker_mutations": self.checker_mutations.to_document(),
        }

    def to_document(self) -> JSONObject:
        return {**self._preimage(), "report_id": self.report_id}


@dataclass(frozen=True, slots=True)
class AtomTaskPack:
    task: AtomTask
    admission: AtomAdmissionReport

    def __post_init__(self) -> None:
        if self.admission.solved.task.task_id != self.task.task_id:
            raise TaskFoundryError(
                "atom_task_pack_task_mismatch",
                "Atom TaskPack admission belongs to another Task",
            )

    @property
    def task_pack_id(self) -> str:
        return hashlib.sha256(canonical_bytes(self._preimage())).hexdigest()

    def _preimage(self) -> JSONObject:
        return {
            "format": "atom-task-pack/2",
            "task": self.task.to_document(),
            "admission": self.admission.to_document(),
        }

    def to_document(self) -> JSONObject:
        return {**self._preimage(), "task_pack_id": self.task_pack_id}


def seal_atom_task_pack(
    solved: SolvedAtomTask,
    challenges: AtomChallengeReport,
    agent_choices: AgentChoiceProof,
    checker_mutations: AtomCheckerMutationReport,
) -> AtomTaskPack:
    """Seal one Atom Task only after every same-plan admission proof is complete."""

    _verify_task_preimage(solved.task)
    admission = AtomAdmissionReport(
        solved,
        challenges,
        agent_choices,
        checker_mutations,
    )
    return AtomTaskPack(solved.task, admission)


def admit_atom_task(
    prepared: OpenPreparedRelease,
    task: AtomTask,
    task_universe: tuple[AtomTask, ...],
    instance_root: Path,
    *,
    route: AgentRoute | None = None,
    max_provider_turns: int = 8,
) -> AtomTaskPack:
    """Run the existing same-plan Atom admission pipeline and seal one TaskPack."""

    root = Path(instance_root)
    solved = solve_atom_task_twice(
        prepared,
        task,
        task_universe,
        root / "solve",
        route=route,
        max_provider_turns=max_provider_turns,
    )
    challenges = challenge_atom_task(
        prepared,
        solved,
        task_universe,
        root / "challenges",
        route=route,
        max_provider_turns=max_provider_turns,
    )
    choices = prove_agent_choices_non_load_bearing(
        prepared,
        solved,
        root / "agent-choices",
    )
    mutations = run_atom_checker_mutations(solved.admission_plan, challenges)
    return seal_atom_task_pack(solved, challenges, choices, mutations)


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
                    for answer_fields in _answer_field_profiles(capability.answer_fields):
                        answer_schema = _answer_schema(answer_fields)
                        checker_preimage: JSONObject = {
                            "release_id": prepared.identity.release_id,
                            "start_case_id": start.case_id,
                            "capability_id": capability.capability_id,
                            "semantic_key": binding.semantic_key,
                            "answer_schema": answer_schema,
                        }
                        checker_digest = hashlib.sha256(
                            canonical_bytes(checker_preimage)
                        ).hexdigest()
                        instruction = _instruction(
                            goal,
                            binding.public_descriptor,
                            answer_fields,
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
    task_universe: tuple[AtomTask, ...],
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
        task_universe,
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
            result = _evaluate_report_atom(
                session,
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
                ),
                task.answer_schema,
            )
            if not result.satisfied:
                raise TaskFoundryError(
                    "public_witness_failed",
                    "public Agent trace did not satisfy the frozen Atom checker",
                    result=result.to_document(),
                )
            witnesses.append(
                _witness(
                    task,
                    session.identity.materialization_id,
                    reset,
                    tool_specs,
                    episode,
                    result,
                )
            )
    return SolvedAtomTask(
        task,
        admission_plan,
        cast(tuple[AtomWitness, AtomWitness], tuple(witnesses)),
    )


def prove_agent_choices_non_load_bearing(
    prepared: OpenPreparedRelease,
    solved: SolvedAtomTask,
    instance_root: Path,
) -> AgentChoiceProof:
    """Physically perturb every witness AgentChoice on a fresh public replay."""

    task = solved.task
    if task.release_id != prepared.identity.release_id:
        raise TaskFoundryError(
            "task_release_mismatch",
            "Atom Task belongs to another release",
        )
    if solved.admission_plan.agent_choice_policy != "perturb_each_occurrence":
        raise TaskFoundryError(
            "admission_agent_choice_policy_invalid",
            "Solved Atom Task did not precommit to perturb every AgentChoice",
        )
    choices = [
        (witness, occurrence)
        for witness in solved.witnesses
        for occurrence in witness.argument_provenance
        if occurrence.source_kind == "agent_choice"
    ]
    perturbations: list[AgentChoicePerturbation] = []
    for index, (witness, occurrence) in enumerate(choices, start=1):
        instance = Path(instance_root) / f"choice-{index}"
        with prepared.open(instance) as session:
            reset = session.actor.reset(task.start_case.reset_input)
            before = session.trusted.inspect(instance)
            binding = _resolve_binding(session, task, before)
            tool_specs = {item["name"]: item for item in session.actor.tools()}
            source_event = next(item for item in witness.trace if item.seq == occurrence.event_seq)
            source_spec = tool_specs[source_event.tool_name]
            schema = _schema_at_pointer(source_spec["input_schema"], occurrence.argument_pointer)
            replacement = _alternative_value(schema, occurrence.value)
            if replacement is _NO_ALTERNATIVE:
                raise TaskFoundryError(
                    "agent_choice_not_perturbable",
                    "AgentChoice schema has no distinct schema-valid alternative",
                    event_seq=occurrence.event_seq,
                    argument_pointer=occurrence.argument_pointer,
                )
            replay_observations: dict[int, JSONObject] = {}
            replay_trace: list[TraceEvent] = []
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
                    reset,
                    replay_observations,
                    (occurrence.event_seq, occurrence.argument_pointer),
                    cast(JSONValue, replacement),
                )
                spec = tool_specs[event.tool_name]
                errors = tuple(Draft202012Validator(spec["input_schema"]).iter_errors(arguments))
                if errors:
                    raise TaskFoundryError(
                        "replay_arguments_schema_invalid",
                        "Perturbed replay arguments violate the frozen ToolSpec",
                        event_seq=event.seq,
                        original_message=errors[0].message,
                    )
                observation = _json_object(session.actor.invoke(event.tool_name, arguments))
                replay_observations[event.seq] = observation
                replay_trace.append(TraceEvent(event.seq, event.tool_name, arguments, observation))
            after = session.trusted.inspect(instance)
            probe_result = _evaluate_report_atom(
                session,
                AtomCheckRequest(
                    task.capability_id,
                    before,
                    after,
                    binding.protected_binding,
                    tuple(replay_trace),
                    witness.final_answer,
                    _context(
                        task.capability_id,
                        binding.semantic_key,
                        binding.protected_binding,
                    ),
                ),
                task.answer_schema,
            )
            rebound_answer = _rebound_final_answer(
                probe_result,
                task.answer_schema,
            )
            result = _evaluate_report_atom(
                session,
                AtomCheckRequest(
                    task.capability_id,
                    before,
                    after,
                    binding.protected_binding,
                    tuple(replay_trace),
                    rebound_answer,
                    _context(
                        task.capability_id,
                        binding.semantic_key,
                        binding.protected_binding,
                    ),
                ),
                task.answer_schema,
            )
            perturbations.append(
                AgentChoicePerturbation(
                    witness.witness_id,
                    session.identity.materialization_id,
                    occurrence.event_seq,
                    occurrence.argument_pointer,
                    occurrence.value,
                    cast(JSONValue, replacement),
                    tuple(replay_trace),
                    result,
                )
            )
    if len(perturbations) != len(choices):
        raise TaskFoundryError(
            "agent_choice_proof_incomplete",
            "AgentChoice proof did not account for every witness occurrence",
        )
    return AgentChoiceProof(
        task.task_id,
        solved.admission_plan.plan_id,
        tuple(perturbations),
    )


def challenge_atom_task(
    prepared: OpenPreparedRelease,
    solved: SolvedAtomTask,
    task_universe: tuple[AtomTask, ...],
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
        result = _evaluate_report_atom(
            session,
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
            ),
            task.answer_schema,
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
                None,
            )
        )

    wrong_target_plan = _planned_challenge(admission_plan, "wrong_target")
    if not wrong_target_plan.applicable:
        challenges.append(
            AtomChallengeResult(
                "wrong_target",
                False,
                None,
                (),
                {},
                None,
                None,
                wrong_target_plan.reason,
            )
        )
    else:
        assert wrong_target_plan.target_task_id is not None
        target_task = _task_by_id(task_universe, wrong_target_plan.target_task_id)
        _verify_checker_preimage(prepared, target_task)
        wrong_target_root = Path(instance_root) / "wrong-target"
        with prepared.open(wrong_target_root) as session:
            reset = session.actor.reset(target_task.start_case.reset_input)
            before = session.trusted.inspect(wrong_target_root)
            current_binding = _resolve_binding(session, task, before)
            target_binding = _resolve_binding(session, target_task, before)
            episode = run_public_episode(
                actor=session.actor,
                instruction=target_task.instruction,
                reset_observation=reset,
                tool_specs=session.actor.tools(),
                answer_schema=target_task.answer_schema,
                route=selected_route,
                max_provider_turns=max_provider_turns,
            )
            after = session.trusted.inspect(wrong_target_root)
            target_result = _evaluate_report_atom(
                session,
                AtomCheckRequest(
                    target_task.capability_id,
                    before,
                    after,
                    target_binding.protected_binding,
                    episode.trace,
                    episode.final_answer,
                    _context(
                        target_task.capability_id,
                        target_binding.semantic_key,
                        target_binding.protected_binding,
                    ),
                ),
                target_task.answer_schema,
            )
            if not target_result.satisfied:
                raise TaskFoundryError(
                    "wrong_target_baseline_failed",
                    "Planned wrong-target Task did not satisfy its own frozen checker",
                    target_task_id=target_task.task_id,
                    result=target_result.to_document(),
                )
            current_result = _evaluate_report_atom(
                session,
                AtomCheckRequest(
                    task.capability_id,
                    before,
                    after,
                    current_binding.protected_binding,
                    episode.trace,
                    episode.final_answer,
                    _context(
                        task.capability_id,
                        current_binding.semantic_key,
                        current_binding.protected_binding,
                    ),
                ),
                task.answer_schema,
            )
            challenges.append(
                AtomChallengeResult(
                    "wrong_target",
                    True,
                    session.identity.materialization_id,
                    episode.trace,
                    episode.final_answer,
                    current_result,
                    target_result,
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
        correct = _evaluate_report_atom(
            session,
            AtomCheckRequest(
                task.capability_id,
                before,
                after,
                binding.protected_binding,
                episode.trace,
                episode.final_answer,
                context,
            ),
            task.answer_schema,
        )
        if not correct.satisfied:
            raise TaskFoundryError(
                "challenge_baseline_failed",
                "Atom challenge baseline did not satisfy the checker",
                result=correct.to_document(),
            )
        wrong_answer_plan = _planned_challenge(admission_plan, "wrong_answer")
        if not wrong_answer_plan.applicable:
            challenges.append(
                AtomChallengeResult(
                    "wrong_answer",
                    False,
                    None,
                    (),
                    {},
                    None,
                    None,
                    wrong_answer_plan.reason,
                )
            )
        else:
            assert wrong_answer_plan.final_answer is not None
            wrong_answer = wrong_answer_plan.final_answer
            wrong_result = _evaluate_report_atom(
                session,
                AtomCheckRequest(
                    task.capability_id,
                    before,
                    after,
                    binding.protected_binding,
                    episode.trace,
                    wrong_answer,
                    context,
                ),
                task.answer_schema,
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
                    None,
                )
            )

        missing_process_plan = _planned_challenge(admission_plan, "missing_process")
        if not missing_process_plan.applicable:
            challenges.append(
                AtomChallengeResult(
                    "missing_process",
                    False,
                    None,
                    (),
                    {},
                    None,
                    None,
                    missing_process_plan.reason,
                )
            )
        else:
            missing_result = _evaluate_report_atom(
                session,
                AtomCheckRequest(
                    task.capability_id,
                    before,
                    after,
                    binding.protected_binding,
                    (),
                    episode.final_answer,
                    context,
                ),
                task.answer_schema,
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
                    None,
                )
            )
        collateral_plan = _planned_challenge(admission_plan, "collateral")
        if not collateral_plan.applicable:
            challenges.append(
                AtomChallengeResult(
                    "collateral",
                    False,
                    None,
                    (),
                    {},
                    None,
                    None,
                    collateral_plan.reason,
                )
            )
        else:
            assert collateral_plan.target_task_id is not None
            collateral_task = _task_by_id(task_universe, collateral_plan.target_task_id)
            _verify_checker_preimage(prepared, collateral_task)
            collateral_binding = _resolve_binding(session, collateral_task, after)
            collateral_episode = run_public_episode(
                actor=session.actor,
                instruction=collateral_task.instruction,
                reset_observation=reset,
                tool_specs=session.actor.tools(),
                answer_schema=collateral_task.answer_schema,
                route=selected_route,
                max_provider_turns=max_provider_turns,
            )
            after_collateral = session.trusted.inspect(active_root)
            collateral_result = _evaluate_report_atom(
                session,
                AtomCheckRequest(
                    collateral_task.capability_id,
                    after,
                    after_collateral,
                    collateral_binding.protected_binding,
                    collateral_episode.trace,
                    collateral_episode.final_answer,
                    _context(
                        collateral_task.capability_id,
                        collateral_binding.semantic_key,
                        collateral_binding.protected_binding,
                    ),
                ),
                collateral_task.answer_schema,
            )
            if not collateral_result.satisfied:
                raise TaskFoundryError(
                    "collateral_baseline_failed",
                    "Planned collateral Task did not satisfy its own frozen checker",
                    target_task_id=collateral_task.task_id,
                    result=collateral_result.to_document(),
                )
            combined_trace = _combine_traces(episode.trace, collateral_episode.trace)
            current_with_collateral = _evaluate_report_atom(
                session,
                AtomCheckRequest(
                    task.capability_id,
                    before,
                    after_collateral,
                    binding.protected_binding,
                    combined_trace,
                    episode.final_answer,
                    context,
                ),
                task.answer_schema,
            )
            _assert_collateral_discriminated(current_with_collateral)
            challenges.append(
                AtomChallengeResult(
                    "collateral",
                    True,
                    session.identity.materialization_id,
                    combined_trace,
                    episode.final_answer,
                    current_with_collateral,
                    collateral_result,
                    None,
                )
            )
    return AtomChallengeReport(task.task_id, admission_plan, tuple(challenges))


def _derive_atom_admission_plan(
    prepared: OpenPreparedRelease,
    task: AtomTask,
    task_universe: tuple[AtomTask, ...],
    instance_root: Path,
) -> AtomAdmissionPlan:
    """Freeze deterministic challenge dispositions before any witness model call."""

    _verify_checker_preimage(prepared, task)
    task_ids = tuple(item.task_id for item in task_universe)
    if len(task_ids) != len(set(task_ids)) or task.task_id not in task_ids:
        raise TaskFoundryError(
            "admission_task_universe_invalid",
            "Atom admission requires a unique Task universe containing the current Task",
        )
    if any(item.release_id != task.release_id for item in task_universe):
        raise TaskFoundryError(
            "admission_task_universe_release_mismatch",
            "Atom admission Task universe crosses release identities",
        )
    with prepared.open(instance_root) as session:
        session.actor.reset(task.start_case.reset_input)
        facts = session.trusted.inspect(instance_root)
        binding = _resolve_binding(session, task, facts)
        capabilities = {item.capability_id: item for item in session.trusted.capabilities()}
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
    wrong_target = _select_wrong_target_task(task, task_universe, capabilities)
    wrong_target_plan = (
        AtomPlannedChallenge("wrong_target", True, wrong_target.task_id, None, None)
        if wrong_target is not None
        else AtomPlannedChallenge(
            "wrong_target",
            False,
            None,
            None,
            "no other compiled Atom Task shares this release and StartCase",
        )
    )
    wrong_answer = _wrong_answer(task.answer_schema, initial.report_values)
    wrong_answer_plan = (
        AtomPlannedChallenge("wrong_answer", True, None, wrong_answer, None)
        if wrong_answer is not None
        else AtomPlannedChallenge(
            "wrong_answer",
            False,
            None,
            None,
            "answer schema has no schema-valid alternative value",
        )
    )
    process_plan = (
        AtomPlannedChallenge("missing_process", True, None, None, None)
        if initial.process_ok is not None
        else AtomPlannedChallenge(
            "missing_process",
            False,
            None,
            None,
            "capability checker declares no process outcome axis",
        )
    )
    collateral = _select_collateral_task(task, task_universe, capabilities)
    collateral_plan = (
        AtomPlannedChallenge("collateral", True, collateral.task_id, None, None)
        if collateral is not None
        else AtomPlannedChallenge(
            "collateral",
            False,
            None,
            None,
            "no disjoint-workflow state-change Task is available",
        )
    )
    planned_challenges = (
        AtomPlannedChallenge("no_op", True, None, None, None),
        wrong_target_plan,
        wrong_answer_plan,
        process_plan,
        collateral_plan,
    )
    return AtomAdmissionPlan(
        task.task_id,
        "perturb_each_occurrence",
        initial,
        _derive_checker_mutation_specs(planned_challenges, initial),
        planned_challenges,
    )


def _select_wrong_target_task(
    task: AtomTask,
    task_universe: tuple[AtomTask, ...],
    capabilities: dict[str, CapabilitySpec],
) -> AtomTask | None:
    current = capabilities.get(task.capability_id)
    if current is None:
        raise TaskFoundryError(
            "task_capability_missing",
            "live release no longer exposes the Task capability",
        )
    candidates = [
        item
        for item in task_universe
        if item.start_case == task.start_case
        and (item.capability_id, item.semantic_key) != (task.capability_id, task.semantic_key)
    ]
    for item in candidates:
        if item.capability_id not in capabilities:
            raise TaskFoundryError(
                "admission_target_capability_missing",
                "Task universe contains a capability absent from the live release",
                capability_id=item.capability_id,
            )

    def rank(item: AtomTask) -> tuple[int, int, int, int, str, str, str]:
        candidate = capabilities[item.capability_id]
        shared_workflow = bool(set(current.workflow_ids) & set(candidate.workflow_ids))
        shared_descriptor_fields = sum(
            1
            for name, value in task.public_descriptor.items()
            if item.public_descriptor.get(name) == value
        )
        return (
            int(item.capability_id != task.capability_id),
            int(not shared_workflow),
            int(candidate.task_kind != current.task_kind),
            -shared_descriptor_fields,
            item.capability_id,
            item.semantic_key,
            item.task_id,
        )

    return min(candidates, key=rank) if candidates else None


def _select_collateral_task(
    task: AtomTask,
    task_universe: tuple[AtomTask, ...],
    capabilities: dict[str, CapabilitySpec],
) -> AtomTask | None:
    current = capabilities.get(task.capability_id)
    if current is None:
        raise TaskFoundryError(
            "task_capability_missing",
            "live release no longer exposes the Task capability",
        )
    current_workflows = set(current.workflow_ids)
    candidates = []
    for item in task_universe:
        candidate = capabilities.get(item.capability_id)
        if candidate is None:
            raise TaskFoundryError(
                "admission_target_capability_missing",
                "Task universe contains a capability absent from the live release",
                capability_id=item.capability_id,
            )
        if (
            item.task_id != task.task_id
            and item.start_case == task.start_case
            and candidate.task_kind == "state_change"
            and current_workflows.isdisjoint(candidate.workflow_ids)
        ):
            candidates.append(item)
    return min(
        candidates,
        key=lambda item: (item.capability_id, item.semantic_key, item.task_id),
        default=None,
    )


def _planned_challenge(plan: AtomAdmissionPlan, category: str) -> AtomPlannedChallenge:
    return next(item for item in plan.challenges if item.category == category)


def _task_by_id(task_universe: tuple[AtomTask, ...], task_id: str) -> AtomTask:
    matching = [item for item in task_universe if item.task_id == task_id]
    if len(matching) != 1:
        raise TaskFoundryError(
            "admission_target_task_missing",
            "Frozen wrong-target Task is not uniquely present in the Task universe",
            target_task_id=task_id,
        )
    return matching[0]


def _replay_arguments(
    event: TraceEvent,
    provenance: tuple[ArgumentProvenance, ...],
    reset_observation: JSONValue,
    replay_observations: dict[int, JSONObject],
    perturbed_occurrence: tuple[int, str],
    replacement: JSONValue,
) -> JSONObject:
    arguments = _json_object(event.arguments)
    for occurrence in provenance:
        if occurrence.event_seq != event.seq:
            raise TaskFoundryError(
                "replay_provenance_event_mismatch",
                "Replay received provenance for another trace event",
            )
        occurrence_key = (occurrence.event_seq, occurrence.argument_pointer)
        if occurrence_key == perturbed_occurrence:
            if occurrence.source_kind != "agent_choice":
                raise TaskFoundryError(
                    "replay_perturbation_not_agent_choice",
                    "Replay may perturb only an AgentChoice occurrence",
                )
            value = replacement
        elif occurrence.source_kind == "reset":
            assert occurrence.source_pointer is not None
            value = _resolve_json_pointer(reset_observation, occurrence.source_pointer)
        elif occurrence.source_kind == "tool_observation":
            assert occurrence.source_event_seq is not None
            assert occurrence.source_pointer is not None
            source = replay_observations.get(occurrence.source_event_seq)
            if source is None:
                raise TaskFoundryError(
                    "replay_source_event_missing",
                    "Replay has not produced the required prior observation",
                    source_event_seq=occurrence.source_event_seq,
                )
            value = _resolve_json_pointer(source, occurrence.source_pointer)
        else:
            value = occurrence.value
        _set_json_pointer(arguments, occurrence.argument_pointer, value)
    return arguments


def _combine_traces(
    first: tuple[TraceEvent, ...],
    second: tuple[TraceEvent, ...],
) -> tuple[TraceEvent, ...]:
    offset = max((item.seq for item in first), default=0)
    return first + tuple(
        TraceEvent(
            offset + item.seq,
            item.tool_name,
            item.arguments,
            item.observation,
        )
        for item in second
    )


def _assert_collateral_discriminated(result: AtomCheckResult) -> None:
    if result.collateral_ok is not False or result.satisfied:
        raise TaskFoundryError(
            "collateral_not_discriminated",
            "Atom checker did not reject a successful disjoint-workflow state change",
        )


def _resolve_json_pointer(value: JSONValue, pointer: str) -> JSONValue:
    current = value
    for token in _pointer_tokens(pointer):
        if isinstance(current, dict):
            if token not in current:
                raise TaskFoundryError(
                    "replay_source_pointer_missing",
                    "Replay source pointer does not resolve",
                    pointer=pointer,
                )
            current = current[token]
        elif isinstance(current, list):
            try:
                current = current[int(token)]
            except (IndexError, ValueError) as exc:
                raise TaskFoundryError(
                    "replay_source_pointer_missing",
                    "Replay source pointer does not resolve",
                    pointer=pointer,
                ) from exc
        else:
            raise TaskFoundryError(
                "replay_source_pointer_scalar",
                "Replay source pointer traverses a scalar",
                pointer=pointer,
            )
    return _json(current)


def _set_json_pointer(document: JSONObject, pointer: str, value: JSONValue) -> None:
    tokens = _pointer_tokens(pointer)
    if not tokens:
        raise TaskFoundryError(
            "replay_argument_pointer_root",
            "Replay argument pointer cannot replace the object root",
        )
    current: JSONValue = document
    for token in tokens[:-1]:
        if isinstance(current, dict):
            current = current[token]
        elif isinstance(current, list):
            current = current[int(token)]
        else:
            raise TaskFoundryError(
                "replay_argument_pointer_scalar",
                "Replay argument pointer traverses a scalar",
            )
    final = tokens[-1]
    if isinstance(current, dict):
        current[final] = _json(value)
    elif isinstance(current, list):
        current[int(final)] = _json(value)
    else:
        raise TaskFoundryError(
            "replay_argument_pointer_scalar",
            "Replay argument pointer traverses a scalar",
        )


def _pointer_tokens(pointer: str) -> tuple[str, ...]:
    if pointer == "":
        return ()
    if not pointer.startswith("/"):
        raise TaskFoundryError(
            "replay_pointer_invalid",
            "Replay value source is not an RFC 6901 pointer",
        )
    return tuple(token.replace("~1", "/").replace("~0", "~") for token in pointer[1:].split("/"))


def _schema_at_pointer(schema: JSONObject, pointer: str) -> dict[str, Any]:
    current: Any = schema
    for token in _pointer_tokens(pointer):
        if not isinstance(current, dict):
            raise TaskFoundryError(
                "agent_choice_schema_pointer_invalid",
                "AgentChoice argument pointer traverses a non-object schema",
                pointer=pointer,
            )
        properties = current.get("properties")
        if isinstance(properties, dict) and token in properties:
            current = properties[token]
            continue
        items = current.get("items")
        if isinstance(items, dict):
            try:
                int(token)
            except ValueError as exc:
                raise TaskFoundryError(
                    "agent_choice_schema_pointer_invalid",
                    "AgentChoice array pointer token is not an index",
                    pointer=pointer,
                ) from exc
            current = items
            continue
        raise TaskFoundryError(
            "agent_choice_schema_pointer_invalid",
            "AgentChoice argument pointer does not resolve in the ToolSpec",
            pointer=pointer,
        )
    if not isinstance(current, dict):
        raise TaskFoundryError(
            "agent_choice_schema_pointer_invalid",
            "AgentChoice argument schema is not an object",
            pointer=pointer,
        )
    return cast(dict[str, Any], current)


def _verify_checker_preimage(
    prepared: OpenPreparedRelease,
    task: AtomTask,
) -> None:
    if prepared.identity.release_id != task.release_id:
        raise TaskFoundryError(
            "task_release_mismatch",
            "Atom Task belongs to another release",
        )
    _verify_task_preimage(task)


def _verify_task_preimage(task: AtomTask) -> None:
    preimage: JSONObject = {
        "release_id": task.release_id,
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
    projected = {field: answer[field] for field in properties if field in answer}
    for field, raw_schema in properties.items():
        if field not in answer or not isinstance(raw_schema, dict):
            continue
        replacement = _alternative_value(raw_schema, answer[field])
        if replacement is _NO_ALTERNATIVE:
            continue
        candidate = _json_object(projected)
        candidate[field] = cast(JSONValue, replacement)
        if not tuple(Draft202012Validator(schema).iter_errors(candidate)):
            return candidate
    return None


def _rebound_final_answer(
    result: AtomCheckResult,
    answer_schema: JSONObject,
) -> JSONObject:
    properties = answer_schema.get("properties")
    if not isinstance(properties, dict) or any(
        field not in result.report_values for field in properties
    ):
        raise TaskFoundryError(
            "rebound_final_answer_fields_missing",
            "Checker report values do not cover the Task report fields",
        )
    answer = _json_object({field: result.report_values[field] for field in properties})
    errors = tuple(Draft202012Validator(answer_schema).iter_errors(answer))
    if errors:
        raise TaskFoundryError(
            "rebound_final_answer_schema_invalid",
            "Checker report values cannot rebind the perturbed run's final answer",
            original_message=errors[0].message,
        )
    return answer


_NO_ALTERNATIVE = object()


def _alternative_value(schema: dict[str, Any], value: JSONValue) -> JSONValue | object:
    enum = schema.get("enum")
    if isinstance(enum, list):
        for item in enum:
            if item != value and is_json_value(item):
                return cast(JSONValue, item)
    types = schema.get("type")
    ordered_types = (types,) if isinstance(types, str) else tuple(types or ())
    allowed = set(ordered_types)
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
    defaults: dict[str, tuple[JSONValue, ...]] = {
        "boolean": (False, True),
        "integer": (0, 1, -1),
        "number": (0, 1, -1, 0.5),
        "string": ("wrong", "alternative", "x"),
        "array": ([], [None]),
        "object": ({},),
        "null": (None,),
    }
    for allowed_type in ordered_types:
        for candidate in defaults.get(allowed_type, ()):
            if candidate != value and not tuple(
                Draft202012Validator(schema).iter_errors(candidate)
            ):
                return candidate
    return _NO_ALTERNATIVE


def _instruction(goal: str, descriptor: JSONObject, answer_fields: tuple[Any, ...]) -> str:
    labels = [
        {"field_id": field.field_id, "public_label": field.public_label} for field in answer_fields
    ]
    lines = [
        goal.strip(),
        "Selected public target descriptor: "
        + json.dumps(descriptor, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        "Return a JSON object with these fields: "
        + json.dumps(labels, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        "Copy exact public JSON values from the instruction or observations; do not paraphrase.",
    ]
    if any(
        marker in field.public_label.casefold()
        for field in answer_fields
        for marker in (" after ", " before ", "post_", "pre_")
    ):
        lines.append(
            "Respect temporal qualifiers in field labels: an observation before that event "
            "cannot fill an after-event field; return null when the qualified observation "
            "did not occur."
        )
    return "\n".join(lines)


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


def _answer_field_profiles(answer_fields: tuple[Any, ...]) -> tuple[tuple[Any, ...], ...]:
    if len(answer_fields) <= 1:
        return (answer_fields,)
    return (answer_fields, *((field,) for field in answer_fields))


def _report_field_ids(answer_schema: JSONObject) -> tuple[str, ...]:
    properties = answer_schema.get("properties")
    required = answer_schema.get("required")
    if (
        not isinstance(properties, dict)
        or not isinstance(required, list)
        or any(not isinstance(field, str) for field in required)
        or set(required) != set(properties)
    ):
        raise TaskFoundryError(
            "report_schema_invalid",
            "Task answer schema does not declare one exact report field set",
        )
    return tuple(cast(list[str], required))


def _evaluate_report_atom(
    session: OpenPreparedSession,
    request: AtomCheckRequest,
    answer_schema: JSONObject,
) -> AtomCheckResult:
    raw = session.trusted.evaluate_atom(request)
    selected_fields = _report_field_ids(answer_schema)
    if set(selected_fields) == set(raw.report_values):
        return raw
    final_answer = request.final_answer
    if not is_json_object(final_answer) or tuple(
        Draft202012Validator(answer_schema).iter_errors(final_answer)
    ):
        return raw
    final_object = cast(JSONObject, final_answer)
    if any(field not in raw.report_values for field in selected_fields):
        raise TaskFoundryError(
            "report_field_missing",
            "Release-local evaluator omitted a Task-selected report field",
            selected_fields=selected_fields,
            report_fields=tuple(raw.report_values),
        )
    reconstructed = _json_object(raw.report_values)
    for field in selected_fields:
        reconstructed[field] = final_object[field]
    projected = session.trusted.evaluate_atom(replace(request, final_answer=reconstructed))
    stable_axes = (
        "initially_satisfied",
        "required_effects_ok",
        "collateral_ok",
        "process_ok",
        "report_values",
    )
    if any(getattr(raw, field) != getattr(projected, field) for field in stable_axes):
        raise TaskFoundryError(
            "report_projection_semantics_drift",
            "Submitted report fields changed release-local environment semantics",
        )
    return projected


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
    reset_observation: JSONValue,
    tool_specs: tuple[ToolSpec, ...],
    episode: PublicEpisodeRun,
    result: AtomCheckResult,
) -> AtomWitness:
    return AtomWitness(
        task.task_id,
        materialization_id,
        _json(reset_observation),
        episode.trace,
        episode.final_answer,
        resolve_argument_provenance(
            trace=episode.trace,
            instruction_values=task.public_descriptor,
            reset_observation=reset_observation,
            tool_specs=tool_specs,
        ),
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
    "AgentChoicePerturbation",
    "AgentChoiceProof",
    "AtomAdmissionPlan",
    "AtomAdmissionReport",
    "AtomChallengeReport",
    "AtomChallengeResult",
    "AtomCheckerMutationReport",
    "AtomCheckerMutationResult",
    "AtomCheckerMutationSpec",
    "AtomPlannedChallenge",
    "AtomTask",
    "AtomTaskPack",
    "AtomWitness",
    "SolvedAtomTask",
    "TaskFoundryError",
    "admit_atom_task",
    "challenge_atom_task",
    "compile_atom_tasks",
    "prove_agent_choices_non_load_bearing",
    "run_atom_checker_mutations",
    "seal_atom_task_pack",
    "solve_atom_task_twice",
]
