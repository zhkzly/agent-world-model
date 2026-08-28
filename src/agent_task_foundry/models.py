"""Identity-bearing models for the goal-first Task Foundry."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Literal

import rfc8785

from agent_env_foundry.semantics import JSONObject, JSONValue

SelectorOperator = Literal["eq", "neq", "lt", "lte", "gt", "gte"]
RankDirection = Literal["min", "max"]


class TaskModelError(ValueError):
    """A Task Foundry value violates its immutable contract."""


def canonical_document(value: Any) -> JSONValue:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, tuple):
        return [canonical_document(item) for item in value]
    if isinstance(value, list):
        return [canonical_document(item) for item in value]
    if isinstance(value, dict):
        return {key: canonical_document(item) for key, item in sorted(value.items())}
    if hasattr(value, "to_document"):
        return canonical_document(value.to_document())
    raise TaskModelError(f"cannot serialize {type(value).__name__}")


def digest_document(value: Any) -> str:
    return hashlib.sha256(rfc8785.dumps(canonical_document(value))).hexdigest()


@dataclass(frozen=True, slots=True)
class StartRecipe:
    release_id: str
    start_case_id: str
    reset_input: JSONObject | None

    def to_document(self) -> JSONObject:
        return {
            "release_id": self.release_id,
            "start_case_id": self.start_case_id,
            "reset_input": canonical_document(self.reset_input),
        }


@dataclass(frozen=True, slots=True)
class SelectorPredicate:
    facet: str
    operator: SelectorOperator
    value: JSONValue

    def to_document(self) -> JSONObject:
        return {"facet": self.facet, "operator": self.operator, "value": self.value}


@dataclass(frozen=True, slots=True)
class RankSpec:
    facet: str
    direction: RankDirection

    def to_document(self) -> JSONObject:
        return {"facet": self.facet, "direction": self.direction}


@dataclass(frozen=True, slots=True)
class SelectorSpec:
    selector_id: str
    capability_id: str
    filters: tuple[SelectorPredicate, ...] = ()
    rank: RankSpec | None = None
    cardinality: Literal["one", "all"] = "one"

    def to_document(self) -> JSONObject:
        return {
            "selector_id": self.selector_id,
            "capability_id": self.capability_id,
            "filters": [item.to_document() for item in self.filters],
            "rank": self.rank.to_document() if self.rank else None,
            "cardinality": self.cardinality,
        }


@dataclass(frozen=True, slots=True)
class AtomGoal:
    capability_id: str
    selector_id: str

    def to_document(self) -> JSONObject:
        return {
            "kind": "atom",
            "capability_id": self.capability_id,
            "selector_id": self.selector_id,
        }


@dataclass(frozen=True, slots=True)
class AllGoal:
    children: tuple[GoalProgram, ...]
    composition_rule_id: str

    def __post_init__(self) -> None:
        if len(self.children) < 2:
            raise TaskModelError("AllGoal requires at least two children")

    def to_document(self) -> JSONObject:
        return {
            "kind": "all",
            "children": [item.to_document() for item in self.children],
            "composition_rule_id": self.composition_rule_id,
        }


@dataclass(frozen=True, slots=True)
class IfGoal:
    condition_id: str
    selector_id: str | None
    then_goal: GoalProgram | None
    else_goal: GoalProgram | None

    def __post_init__(self) -> None:
        if self.then_goal is None and self.else_goal is None:
            raise TaskModelError("IfGoal requires at least one goal branch")

    def to_document(self) -> JSONObject:
        return {
            "kind": "if",
            "condition_id": self.condition_id,
            "selector_id": self.selector_id,
            "then_goal": self.then_goal.to_document() if self.then_goal else None,
            "else_goal": self.else_goal.to_document() if self.else_goal else None,
        }


@dataclass(frozen=True, slots=True)
class ForEachGoal:
    selector_id: str
    atom: AtomGoal

    def to_document(self) -> JSONObject:
        return {
            "kind": "foreach",
            "selector_id": self.selector_id,
            "atom": self.atom.to_document(),
        }


type GoalProgram = AtomGoal | AllGoal | IfGoal | ForEachGoal


@dataclass(frozen=True, slots=True)
class ReportSpec:
    field_names: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.field_names or len(self.field_names) != len(set(self.field_names)):
            raise TaskModelError("report fields must be non-empty and unique")

    def to_document(self) -> JSONObject:
        return {"field_names": list(self.field_names)}


@dataclass(frozen=True, slots=True)
class TaskBlueprint:
    release_id: str
    semantics_digest: str
    start_recipe: StartRecipe
    selectors: tuple[SelectorSpec, ...]
    goal: GoalProgram
    report: ReportSpec | None = None

    def __post_init__(self) -> None:
        ids = tuple(selector.selector_id for selector in self.selectors)
        if len(ids) != len(set(ids)):
            raise TaskModelError("selector IDs must be unique")

    @property
    def blueprint_id(self) -> str:
        return digest_document(self.to_document())

    def to_document(self) -> JSONObject:
        return {
            "release_id": self.release_id,
            "semantics_digest": self.semantics_digest,
            "start_recipe": self.start_recipe.to_document(),
            "selectors": [item.to_document() for item in self.selectors],
            "goal": self.goal.to_document(),
            "report": self.report.to_document() if self.report else None,
        }


@dataclass(frozen=True, slots=True)
class ResolvedSelector:
    selector_id: str
    semantic_keys: tuple[str, ...]

    def to_document(self) -> JSONObject:
        return {"selector_id": self.selector_id, "semantic_keys": list(self.semantic_keys)}


@dataclass(frozen=True, slots=True)
class CheckerArtifact:
    blueprint_id: str
    resolved_selectors: tuple[ResolvedSelector, ...]
    checker_digest: str

    def to_document(self) -> JSONObject:
        return {
            "blueprint_id": self.blueprint_id,
            "resolved_selectors": [item.to_document() for item in self.resolved_selectors],
            "checker_digest": self.checker_digest,
        }


@dataclass(frozen=True, slots=True)
class InstructionAudit:
    accepted: bool
    findings: tuple[str, ...] = ()

    def to_document(self) -> JSONObject:
        return {"accepted": self.accepted, "findings": list(self.findings)}


@dataclass(frozen=True, slots=True)
class TaskDefinition:
    blueprint: TaskBlueprint
    checker: CheckerArtifact
    instruction: str
    answer_schema: JSONObject | None
    public_reset_context: JSONValue
    instruction_audit: InstructionAudit

    def __post_init__(self) -> None:
        if not self.instruction.strip() or not self.instruction_audit.accepted:
            raise TaskModelError("TaskDefinition requires an accepted final instruction")

    @property
    def task_definition_id(self) -> str:
        return digest_document(self.to_document())

    def to_document(self) -> JSONObject:
        return {
            "blueprint": self.blueprint.to_document(),
            "checker": self.checker.to_document(),
            "instruction": self.instruction,
            "answer_schema": canonical_document(self.answer_schema),
            "public_reset_context": canonical_document(self.public_reset_context),
            "instruction_audit": self.instruction_audit.to_document(),
        }

    def public_projection(self) -> JSONObject:
        return {
            "task_definition_id": self.task_definition_id,
            "release_id": self.blueprint.release_id,
            "instruction": self.instruction,
            "answer_schema": canonical_document(self.answer_schema),
            "public_reset_context": canonical_document(self.public_reset_context),
        }


@dataclass(frozen=True, slots=True)
class ArgumentOrigin:
    path: str
    source: Literal["instruction", "reset", "tool_schema", "tool_output", "unresolved"]
    source_path: str | None = None

    def to_document(self) -> JSONObject:
        return {"path": self.path, "source": self.source, "source_path": self.source_path}


@dataclass(frozen=True, slots=True)
class ProvenanceReport:
    origins: tuple[ArgumentOrigin, ...]

    @property
    def complete(self) -> bool:
        return all(value.source != "unresolved" for value in self.origins)

    def to_document(self) -> JSONObject:
        return {
            "origins": [item.to_document() for item in self.origins],
            "complete": self.complete,
        }


@dataclass(frozen=True, slots=True)
class PublicTraceEvent:
    seq: int
    tool_name: str
    arguments: JSONObject
    observation: JSONObject
    provenance: ProvenanceReport

    def to_document(self) -> JSONObject:
        return {
            "seq": self.seq,
            "tool_name": self.tool_name,
            "arguments": canonical_document(self.arguments),
            "observation": canonical_document(self.observation),
            "provenance": self.provenance.to_document(),
        }


@dataclass(frozen=True, slots=True)
class WitnessRun:
    run_id: str
    materialization_id: str
    task_definition_id: str
    trace: tuple[PublicTraceEvent, ...]
    final_answer: JSONValue
    checker_status: Literal["satisfied", "failed", "abstain"]
    checker_failures: tuple[str, ...] = ()

    @property
    def successful(self) -> bool:
        return (
            self.checker_status == "satisfied"
            and bool(self.trace)
            and all(event.provenance.complete for event in self.trace)
        )

    @property
    def evidence_digest(self) -> str:
        return digest_document(self.to_document())

    def to_document(self) -> JSONObject:
        return {
            "run_id": self.run_id,
            "materialization_id": self.materialization_id,
            "task_definition_id": self.task_definition_id,
            "trace": [item.to_document() for item in self.trace],
            "final_answer": canonical_document(self.final_answer),
            "checker_status": self.checker_status,
            "checker_failures": list(self.checker_failures),
        }


@dataclass(frozen=True, slots=True)
class ChallengeResult:
    challenge_id: str
    expected: Literal["satisfied", "failed", "abstain"]
    actual: Literal["satisfied", "failed", "abstain"]
    reachable: bool = True

    @property
    def passed(self) -> bool:
        return self.reachable and self.expected == self.actual

    def to_document(self) -> JSONObject:
        return {
            "challenge_id": self.challenge_id,
            "expected": self.expected,
            "actual": self.actual,
            "reachable": self.reachable,
            "passed": self.passed,
        }


@dataclass(frozen=True, slots=True)
class CheckerMutationResult:
    mutation_id: str
    reachable: bool
    killed: bool
    evidence_digest: str

    @property
    def passed(self) -> bool:
        return self.reachable and self.killed and bool(self.evidence_digest)

    def to_document(self) -> JSONObject:
        return {
            "mutation_id": self.mutation_id,
            "reachable": self.reachable,
            "killed": self.killed,
            "evidence_digest": self.evidence_digest,
            "passed": self.passed,
        }


@dataclass(frozen=True, slots=True)
class AdmissionReport:
    witness_digests: tuple[str, ...]
    challenges: tuple[ChallengeResult, ...]
    checker_mutations: tuple[CheckerMutationResult, ...]

    @property
    def accepted(self) -> bool:
        reachable_mutations = tuple(item for item in self.checker_mutations if item.reachable)
        return (
            len(self.witness_digests) >= 2
            and all(item.passed for item in self.challenges if item.reachable)
            and bool(reachable_mutations)
            and all(item.passed for item in reachable_mutations)
        )

    def to_document(self) -> JSONObject:
        return {
            "witness_digests": list(self.witness_digests),
            "challenges": [item.to_document() for item in self.challenges],
            "checker_mutations": [item.to_document() for item in self.checker_mutations],
            "accepted": self.accepted,
        }


@dataclass(frozen=True, slots=True)
class TaskPack:
    definition: TaskDefinition
    checker_payload: JSONObject
    witnesses: tuple[WitnessRun, ...]
    admission: AdmissionReport

    def __post_init__(self) -> None:
        if not self.admission.accepted:
            raise TaskModelError("cannot seal a TaskPack with failed admission")
        if not self.checker_payload:
            raise TaskModelError("TaskPack requires reconstructable protected checker payload")
        if self.checker_payload.get("checker_digest") != self.definition.checker.checker_digest:
            raise TaskModelError("checker payload does not match TaskDefinition")
        if any(
            run.task_definition_id != self.definition.task_definition_id for run in self.witnesses
        ):
            raise TaskModelError("witness belongs to another TaskDefinition")
        if len(self.witnesses) < 2 or len({run.materialization_id for run in self.witnesses}) < 2:
            raise TaskModelError("TaskPack requires two distinct fresh materializations")
        if any(not run.successful for run in self.witnesses):
            raise TaskModelError("TaskPack contains an unsuccessful witness")
        digests = tuple(run.evidence_digest for run in self.witnesses)
        if self.admission.witness_digests != digests:
            raise TaskModelError("AdmissionReport does not bind the witness evidence")
        present = {item.challenge_id for item in self.admission.challenges if item.reachable}
        missing = _required_challenges(self.definition) - present
        if missing:
            raise TaskModelError(f"TaskPack misses challenges: {sorted(missing)}")

    @property
    def taskpack_id(self) -> str:
        return digest_document(self.to_document())

    def to_document(self) -> JSONObject:
        return {
            "definition": self.definition.to_document(),
            "checker_payload": canonical_document(self.checker_payload),
            "witnesses": [item.to_document() for item in self.witnesses],
            "admission": self.admission.to_document(),
        }

    def public_projection(self) -> JSONObject:
        return {
            "taskpack_id": self.taskpack_id,
            "task": self.definition.public_projection(),
        }


def _required_challenges(definition: TaskDefinition) -> set[str]:
    required = {"positive", "no_op", "wrong_target", "collateral"}
    goal = definition.blueprint.goal
    if isinstance(goal, (AllGoal, ForEachGoal)):
        required.add("partial")
    if isinstance(goal, IfGoal):
        required.add("wrong_branch")
    if definition.blueprint.report is not None:
        required.add("wrong_answer")
    return required


@dataclass(frozen=True, slots=True)
class TaskFingerprint:
    capability_ids: tuple[str, ...]
    workflow_ids: tuple[str, ...]
    goal_shape: str
    selector_operators: tuple[str, ...]
    state_regimes: tuple[str, ...]
    answer_required: bool

    @property
    def fingerprint_id(self) -> str:
        return digest_document(self.to_document())

    def to_document(self) -> JSONObject:
        return {
            "capability_ids": list(self.capability_ids),
            "workflow_ids": list(self.workflow_ids),
            "goal_shape": self.goal_shape,
            "selector_operators": list(self.selector_operators),
            "state_regimes": list(self.state_regimes),
            "answer_required": self.answer_required,
        }


@dataclass(frozen=True, slots=True)
class TaskAssessment:
    taskpack_id: str
    policy_id: str
    attempts: int
    successes: int
    tool_calls: int
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def success_rate(self) -> float:
        return self.successes / self.attempts if self.attempts else 0.0

    @property
    def assessment_id(self) -> str:
        return digest_document(self.to_document())

    def to_document(self) -> JSONObject:
        return {
            "taskpack_id": self.taskpack_id,
            "policy_id": self.policy_id,
            "attempts": self.attempts,
            "successes": self.successes,
            "tool_calls": self.tool_calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
        }


@dataclass(frozen=True, slots=True)
class CorpusManifest:
    policy_digest: str
    taskpack_ids: tuple[str, ...]
    assessment_ids: tuple[str, ...] = ()
    rejected: JSONObject = field(default_factory=dict)

    @property
    def corpus_id(self) -> str:
        return digest_document(self.to_document())

    def to_document(self) -> JSONObject:
        return {
            "policy_digest": self.policy_digest,
            "taskpack_ids": list(self.taskpack_ids),
            "assessment_ids": list(self.assessment_ids),
            "rejected": canonical_document(self.rejected),
        }


def goal_capability_ids(goal: GoalProgram) -> tuple[str, ...]:
    if isinstance(goal, AtomGoal):
        return (goal.capability_id,)
    if isinstance(goal, ForEachGoal):
        return (goal.atom.capability_id,)
    if isinstance(goal, AllGoal):
        return tuple(
            sorted({item for child in goal.children for item in goal_capability_ids(child)})
        )
    children = tuple(value for value in (goal.then_goal, goal.else_goal) if value is not None)
    return tuple(sorted({item for child in children for item in goal_capability_ids(child)}))


def goal_shape(goal: GoalProgram) -> str:
    if isinstance(goal, AtomGoal):
        return "atom"
    if isinstance(goal, ForEachGoal):
        return "foreach(atom)"
    if isinstance(goal, AllGoal):
        return "all(" + ",".join(goal_shape(child) for child in goal.children) + ")"
    return (
        "if("
        + ",".join(
            goal_shape(value) if value is not None else "report"
            for value in (goal.then_goal, goal.else_goal)
        )
        + ")"
    )
