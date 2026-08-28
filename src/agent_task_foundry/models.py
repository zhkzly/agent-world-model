"""Immutable Goal-first Task and evidence identity contracts."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Literal

from agent_env_foundry.environment import JSONObject, JSONValue
from agent_env_foundry.jsonvalue import is_json_object, is_json_value
from agent_env_foundry.release import canonical_bytes
from agent_env_foundry.semantics import StartCase

SelectorOperator = Literal["eq", "neq", "lt", "lte", "gt", "gte"]
RankDirection = Literal["min", "max"]
SelectorCardinality = Literal["exactly_one", "any_one", "all"]
CheckerStatus = Literal["satisfied", "failed", "abstain"]
ChallengeVerdict = Literal["passed", "failed", "not_applicable"]
ArgumentSource = Literal[
    "instruction",
    "reset",
    "tool_schema",
    "tool_output",
    "agent_choice",
    "unresolved",
    "protected",
]
OrderingKind = Literal[
    "checker_frozen",
    "instruction_frozen",
    "task_persisted",
    "model_call_allowed",
]
FailureKind = Literal[
    "InfrastructureFailure",
    "EnvironmentDefect",
    "SemanticsDefect",
    "UnsupportedCapability",
    "RejectedBlueprint",
    "CheckerDefect",
    "InstructionDefect",
    "NoPublicWitness",
    "RejectedTaskPack",
    "RejectedForCorpus",
]

_SELECTOR_OPERATORS = frozenset({"eq", "neq", "lt", "lte", "gt", "gte"})
_CARDINALITIES = frozenset({"exactly_one", "any_one", "all"})
_CHECKER_STATUSES = frozenset({"satisfied", "failed", "abstain"})
_CHALLENGE_VERDICTS = frozenset({"passed", "failed", "not_applicable"})
_ARGUMENT_SOURCES = frozenset(
    {
        "instruction",
        "reset",
        "tool_schema",
        "tool_output",
        "agent_choice",
        "unresolved",
        "protected",
    }
)
_ORDERING_KINDS = (
    "checker_frozen",
    "instruction_frozen",
    "task_persisted",
    "model_call_allowed",
)
_FAILURE_KINDS = frozenset(
    {
        "InfrastructureFailure",
        "EnvironmentDefect",
        "SemanticsDefect",
        "UnsupportedCapability",
        "RejectedBlueprint",
        "CheckerDefect",
        "InstructionDefect",
        "NoPublicWitness",
        "RejectedTaskPack",
        "RejectedForCorpus",
    }
)
_HEX = frozenset("0123456789abcdef")


class TaskModelError(ValueError):
    """A Task Foundry value violates its immutable contract."""


def canonical_document(value: Any) -> JSONValue:
    if value is None or isinstance(value, (bool, int, float, str)):
        if not is_json_value(value):
            raise TaskModelError("non-finite JSON number")
        return value
    if isinstance(value, (tuple, list)):
        return [canonical_document(item) for item in value]
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise TaskModelError("canonical document keys must be strings")
        return {key: canonical_document(item) for key, item in sorted(value.items())}
    if hasattr(value, "to_document"):
        return canonical_document(value.to_document())
    raise TaskModelError(f"cannot canonically serialize {type(value).__name__}")


def digest_document(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(canonical_document(value))).hexdigest()


@dataclass(frozen=True, slots=True)
class FacetPredicate:
    facet: str
    operator: SelectorOperator
    value: JSONValue

    def __post_init__(self) -> None:
        _identifier(self.facet, "facet predicate")
        if self.operator not in _SELECTOR_OPERATORS:
            raise TaskModelError("unsupported selector operator")
        _json(self.value, "selector value")

    def to_document(self) -> JSONObject:
        return {"facet": self.facet, "operator": self.operator, "value": self.value}


@dataclass(frozen=True, slots=True)
class RankSpec:
    facet: str
    direction: RankDirection

    def __post_init__(self) -> None:
        _identifier(self.facet, "rank facet")
        if self.direction not in ("min", "max"):
            raise TaskModelError("rank direction must be min or max")

    def to_document(self) -> JSONObject:
        return {"facet": self.facet, "direction": self.direction}


@dataclass(frozen=True, slots=True)
class SelectorSpec:
    selector_id: str
    capability_id: str
    filters: tuple[FacetPredicate, ...]
    rank: RankSpec | None
    cardinality: SelectorCardinality

    def __post_init__(self) -> None:
        _identifier(self.selector_id, "selector_id")
        _identifier(self.capability_id, "selector capability_id")
        if self.cardinality not in _CARDINALITIES:
            raise TaskModelError("selector cardinality is invalid")
        keys = tuple(
            (item.facet, item.operator, digest_document(item.value)) for item in self.filters
        )
        _unique(keys, "selector filters")

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
    binding_slot: str

    def __post_init__(self) -> None:
        _identifier(self.capability_id, "atom capability_id")
        _identifier(self.binding_slot, "atom binding_slot")

    def to_document(self) -> JSONObject:
        return {
            "kind": "atom",
            "capability_id": self.capability_id,
            "binding_slot": self.binding_slot,
        }


@dataclass(frozen=True, slots=True)
class AllGoal:
    composition_rule_id: str
    children: tuple[GoalProgram, ...]

    def __post_init__(self) -> None:
        _identifier(self.composition_rule_id, "composition_rule_id")
        if len(self.children) < 2:
            raise TaskModelError("AllGoal requires at least two children")

    def to_document(self) -> JSONObject:
        return {
            "kind": "all",
            "composition_rule_id": self.composition_rule_id,
            "children": [item.to_document() for item in self.children],
        }


@dataclass(frozen=True, slots=True)
class IfGoal:
    condition_id: str
    binding_slot: str | None
    then_goal: GoalProgram | None
    else_goal: GoalProgram | None

    def __post_init__(self) -> None:
        _identifier(self.condition_id, "condition_id")
        if self.binding_slot is not None:
            _identifier(self.binding_slot, "condition binding_slot")
        if self.then_goal is None and self.else_goal is None:
            raise TaskModelError("IfGoal requires at least one goal branch")

    def to_document(self) -> JSONObject:
        return {
            "kind": "if",
            "condition_id": self.condition_id,
            "binding_slot": self.binding_slot,
            "then_goal": self.then_goal.to_document() if self.then_goal else None,
            "else_goal": self.else_goal.to_document() if self.else_goal else None,
        }


@dataclass(frozen=True, slots=True)
class ForEachGoal:
    selector_id: str
    capability_id: str

    def __post_init__(self) -> None:
        _identifier(self.selector_id, "foreach selector_id")
        _identifier(self.capability_id, "foreach capability_id")

    def to_document(self) -> JSONObject:
        return {
            "kind": "foreach",
            "selector_id": self.selector_id,
            "capability_id": self.capability_id,
        }


type GoalProgram = AtomGoal | AllGoal | IfGoal | ForEachGoal


@dataclass(frozen=True, slots=True)
class AtomReportRef:
    capability_id: str
    binding_slot: str
    field_id: str

    def __post_init__(self) -> None:
        _identifier(self.capability_id, "report capability_id")
        _identifier(self.binding_slot, "report binding_slot")
        _identifier(self.field_id, "report field_id")

    def to_document(self) -> JSONObject:
        return {
            "kind": "atom",
            "capability_id": self.capability_id,
            "binding_slot": self.binding_slot,
            "field_id": self.field_id,
        }


@dataclass(frozen=True, slots=True)
class ConditionReportRef:
    condition_id: str
    binding_slot: str | None
    field_id: str

    def __post_init__(self) -> None:
        _identifier(self.condition_id, "report condition_id")
        if self.binding_slot is not None:
            _identifier(self.binding_slot, "report binding_slot")
        _identifier(self.field_id, "report field_id")

    def to_document(self) -> JSONObject:
        return {
            "kind": "condition",
            "condition_id": self.condition_id,
            "binding_slot": self.binding_slot,
            "field_id": self.field_id,
        }


type ReportSourceRef = AtomReportRef | ConditionReportRef


@dataclass(frozen=True, slots=True)
class ReportSpec:
    fields: tuple[ReportSourceRef, ...]

    def __post_init__(self) -> None:
        if not self.fields:
            raise TaskModelError("ReportSpec fields must not be empty")
        _unique(tuple(digest_document(item) for item in self.fields), "report fields")

    def to_document(self) -> JSONObject:
        return {"fields": [item.to_document() for item in self.fields]}


@dataclass(frozen=True, slots=True)
class TaskBlueprint:
    selectors: tuple[SelectorSpec, ...]
    goal: GoalProgram
    report: ReportSpec | None

    def __post_init__(self) -> None:
        _unique(tuple(selector.selector_id for selector in self.selectors), "selector IDs")
        required_reports = _goal_less_branch_reports(self.goal)
        provided_reports = (
            {
                (field.condition_id, field.binding_slot)
                for field in self.report.fields
                if isinstance(field, ConditionReportRef)
            }
            if self.report is not None
            else set()
        )
        if not required_reports <= provided_reports:
            raise TaskModelError("goal-less IfGoal branch requires a matching condition report")

    @property
    def blueprint_digest(self) -> str:
        return digest_document(self.to_document())

    def to_document(self) -> JSONObject:
        return {
            "selectors": [item.to_document() for item in self.selectors],
            "goal": self.goal.to_document(),
            "report": self.report.to_document() if self.report else None,
        }


@dataclass(frozen=True, slots=True)
class CheckerArtifact:
    task_preimage_digest: str
    goal_program: GoalProgram
    selector_resolutions: JSONObject
    protected_bindings: JSONObject
    answer_schema: JSONObject | None
    semantics_digest: str

    def __post_init__(self) -> None:
        _digest(self.task_preimage_digest, "task_preimage_digest")
        _digest(self.semantics_digest, "semantics_digest")
        _object(self.selector_resolutions, "selector_resolutions")
        _object(self.protected_bindings, "protected_bindings")
        if self.answer_schema is not None:
            _object(self.answer_schema, "answer_schema")

    @property
    def checker_digest(self) -> str:
        return digest_document(self.to_document())

    def to_document(self) -> JSONObject:
        return {
            "task_preimage_digest": self.task_preimage_digest,
            "goal_program": self.goal_program.to_document(),
            "selector_resolutions": canonical_document(self.selector_resolutions),
            "protected_bindings": canonical_document(self.protected_bindings),
            "answer_schema": canonical_document(self.answer_schema),
            "semantics_digest": self.semantics_digest,
        }


@dataclass(frozen=True, slots=True)
class TaskDefinition:
    release_id: str
    semantics_digest: str
    start_case: StartCase
    blueprint: TaskBlueprint
    protected_bindings: JSONObject
    public_instruction_frame: JSONObject
    canonical_instruction: str
    answer_schema: JSONObject | None
    checker: CheckerArtifact

    def __post_init__(self) -> None:
        _digest(self.release_id, "release_id")
        _digest(self.semantics_digest, "semantics_digest")
        _object(self.protected_bindings, "protected_bindings")
        _object(self.public_instruction_frame, "public_instruction_frame")
        _text(self.canonical_instruction, "canonical_instruction")
        if self.answer_schema is not None:
            _object(self.answer_schema, "answer_schema")
        if self.checker.semantics_digest != self.semantics_digest:
            raise TaskModelError("checker binds a different semantics_digest")

    @property
    def task_id(self) -> str:
        return digest_document(self.identity_preimage_document())

    def identity_preimage_document(self) -> JSONObject:
        return {
            "release_id": self.release_id,
            "semantics_digest": self.semantics_digest,
            "start_case": self.start_case.to_document(),
            "blueprint": self.blueprint.to_document(),
            "protected_bindings": canonical_document(self.protected_bindings),
            "public_instruction_frame": canonical_document(self.public_instruction_frame),
            "canonical_instruction": self.canonical_instruction,
            "answer_schema": canonical_document(self.answer_schema),
            "checker": self.checker.to_document(),
        }

    def protected_document(self) -> JSONObject:
        return {"task_id": self.task_id, **self.identity_preimage_document()}

    def public_document(self) -> JSONObject:
        return {
            "task_id": self.task_id,
            "release_id": self.release_id,
            "public_instruction_frame": canonical_document(self.public_instruction_frame),
            "canonical_instruction": self.canonical_instruction,
            "answer_schema": canonical_document(self.answer_schema),
        }


@dataclass(frozen=True, slots=True)
class OrderingEvent:
    seq: int
    kind: OrderingKind
    artifact_digest: str

    def __post_init__(self) -> None:
        if self.seq <= 0:
            raise TaskModelError("ordering event seq must be positive")
        if self.kind not in _ORDERING_KINDS:
            raise TaskModelError("ordering event kind is invalid")
        _digest(self.artifact_digest, "ordering artifact_digest")

    def to_document(self) -> JSONObject:
        return {"seq": self.seq, "kind": self.kind, "artifact_digest": self.artifact_digest}


@dataclass(frozen=True, slots=True)
class OrderingJournal:
    events: tuple[OrderingEvent, ...]

    def __post_init__(self) -> None:
        expected_seq = tuple(range(1, len(self.events) + 1))
        if tuple(event.seq for event in self.events) != expected_seq:
            raise TaskModelError("ordering journal sequence is not contiguous")
        kinds = tuple(event.kind for event in self.events)
        if kinds != _ORDERING_KINDS[: len(kinds)]:
            raise TaskModelError("ordering journal violates checker-before-model ordering")

    @property
    def model_call_allowed(self) -> bool:
        return bool(self.events) and self.events[-1].kind == "model_call_allowed"


@dataclass(frozen=True, slots=True)
class ArgumentOrigin:
    path: str
    source: ArgumentSource
    source_path: str | None
    load_bearing: bool

    def __post_init__(self) -> None:
        if self.source not in _ARGUMENT_SOURCES:
            raise TaskModelError("argument provenance source is invalid")

    def to_document(self) -> JSONObject:
        return {
            "path": self.path,
            "source": self.source,
            "source_path": self.source_path,
            "load_bearing": self.load_bearing,
        }


@dataclass(frozen=True, slots=True)
class ProvenanceReport:
    origins: tuple[ArgumentOrigin, ...]

    @property
    def complete(self) -> bool:
        return all(
            not origin.load_bearing
            or origin.source not in ("agent_choice", "unresolved", "protected")
            for origin in self.origins
        )

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

    def __post_init__(self) -> None:
        if self.seq <= 0:
            raise TaskModelError("trace seq must be positive")
        _identifier(self.tool_name, "trace tool_name")
        _object(self.arguments, "trace arguments")
        _object(self.observation, "trace observation")

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
    materialization_id: str
    task_definition_id: str
    start_case_id: str
    trace: tuple[PublicTraceEvent, ...]
    final_answer: JSONValue
    checker_digest: str
    before_facts_digest: str
    after_facts_digest: str
    checker_status: CheckerStatus
    checker_failures: tuple[str, ...]

    def __post_init__(self) -> None:
        for value, role in (
            (self.materialization_id, "materialization_id"),
            (self.task_definition_id, "task_definition_id"),
            (self.checker_digest, "checker_digest"),
            (self.before_facts_digest, "before_facts_digest"),
            (self.after_facts_digest, "after_facts_digest"),
        ):
            _digest(value, role)
        _identifier(self.start_case_id, "start_case_id")
        _json(self.final_answer, "final_answer")
        _unique(self.checker_failures, "checker_failures")
        if self.checker_status not in _CHECKER_STATUSES:
            raise TaskModelError("checker_status is invalid")

    @property
    def successful(self) -> bool:
        return (
            self.checker_status == "satisfied"
            and not self.checker_failures
            and bool(self.trace)
            and all(event.provenance.complete for event in self.trace)
        )

    @property
    def run_id(self) -> str:
        return digest_document(self.identity_preimage_document())

    def identity_preimage_document(self) -> JSONObject:
        return {
            "materialization_id": self.materialization_id,
            "task_definition_id": self.task_definition_id,
            "start_case_id": self.start_case_id,
            "trace": [item.to_document() for item in self.trace],
            "final_answer": canonical_document(self.final_answer),
            "checker_digest": self.checker_digest,
            "before_facts_digest": self.before_facts_digest,
            "after_facts_digest": self.after_facts_digest,
            "checker_status": self.checker_status,
            "checker_failures": list(self.checker_failures),
        }

    def to_document(self) -> JSONObject:
        return {"run_id": self.run_id, **self.identity_preimage_document()}


@dataclass(frozen=True, slots=True)
class ChallengeResult:
    challenge_id: str
    verdict: ChallengeVerdict
    reason_code: str | None
    evidence_digest: str | None

    def __post_init__(self) -> None:
        _identifier(self.challenge_id, "challenge_id")
        if self.verdict not in _CHALLENGE_VERDICTS:
            raise TaskModelError("challenge verdict is invalid")
        if self.verdict == "not_applicable":
            if self.reason_code is None:
                raise TaskModelError("not_applicable challenge requires reason_code")
            _identifier(self.reason_code, "challenge reason_code")
            if self.evidence_digest is not None:
                raise TaskModelError("not_applicable challenge must not claim evidence_digest")
        else:
            if self.evidence_digest is None:
                raise TaskModelError("applied challenge requires evidence_digest")
            _digest(self.evidence_digest, "challenge evidence_digest")
            if self.reason_code is not None:
                _identifier(self.reason_code, "challenge reason_code")

    @property
    def passed(self) -> bool:
        return self.verdict == "passed"

    def to_document(self) -> JSONObject:
        return {
            "challenge_id": self.challenge_id,
            "verdict": self.verdict,
            "reason_code": self.reason_code,
            "evidence_digest": self.evidence_digest,
        }


@dataclass(frozen=True, slots=True)
class CheckerMutationResult:
    mutation_id: str
    reachable: bool
    killed: bool
    mutant_checker_digest: str
    evidence_digest: str | None
    reason_code: str | None

    def __post_init__(self) -> None:
        _identifier(self.mutation_id, "mutation_id")
        _digest(self.mutant_checker_digest, "mutant_checker_digest")
        if self.reachable:
            if self.evidence_digest is None:
                raise TaskModelError("reachable mutation requires evidence_digest")
            _digest(self.evidence_digest, "mutation evidence_digest")
            if self.reason_code is not None:
                _identifier(self.reason_code, "mutation reason_code")
        else:
            if self.killed:
                raise TaskModelError("unreachable mutation cannot be killed")
            if self.reason_code is None:
                raise TaskModelError("unreachable mutation requires reason_code")
            _identifier(self.reason_code, "mutation reason_code")

    def to_document(self) -> JSONObject:
        return {
            "mutation_id": self.mutation_id,
            "reachable": self.reachable,
            "killed": self.killed,
            "mutant_checker_digest": self.mutant_checker_digest,
            "evidence_digest": self.evidence_digest,
            "reason_code": self.reason_code,
        }


@dataclass(frozen=True, slots=True)
class AdmissionReport:
    task_definition_id: str
    checker_digest: str
    witness_digests: tuple[str, str]
    challenges: tuple[ChallengeResult, ...]
    checker_mutations: tuple[CheckerMutationResult, ...]

    def __post_init__(self) -> None:
        _digest(self.task_definition_id, "admission task_definition_id")
        _digest(self.checker_digest, "admission checker_digest")
        for value in self.witness_digests:
            _digest(value, "admission witness_digest")

    @property
    def accepted(self) -> bool:
        reachable = tuple(item for item in self.checker_mutations if item.reachable)
        return (
            all(item.verdict in ("passed", "not_applicable") for item in self.challenges)
            and bool(reachable)
            and all(item.killed and item.evidence_digest is not None for item in reachable)
        )

    def to_document(self) -> JSONObject:
        return {
            "task_definition_id": self.task_definition_id,
            "checker_digest": self.checker_digest,
            "witness_digests": list(self.witness_digests),
            "challenges": [item.to_document() for item in self.challenges],
            "checker_mutations": [item.to_document() for item in self.checker_mutations],
            "accepted": self.accepted,
        }


@dataclass(frozen=True, slots=True)
class TaskPack:
    definition: TaskDefinition
    witness_evidence: tuple[WitnessRun, WitnessRun]
    admission_evidence: AdmissionReport

    def __post_init__(self) -> None:
        if len(self.witness_evidence) != 2:
            raise TaskModelError("TaskPack requires exactly two witnesses")
        first, second = self.witness_evidence
        if not first.successful or not second.successful:
            raise TaskModelError("TaskPack witnesses must be successful")
        if first.materialization_id == second.materialization_id:
            raise TaskModelError("TaskPack requires distinct fresh materializations")
        if first.start_case_id != second.start_case_id:
            raise TaskModelError("TaskPack witnesses must use the same start case")
        if any(
            item.task_definition_id != self.definition.task_id for item in self.witness_evidence
        ):
            raise TaskModelError("TaskPack witness belongs to another TaskDefinition")
        if any(
            item.checker_digest != self.definition.checker.checker_digest
            for item in self.witness_evidence
        ):
            raise TaskModelError("TaskPack witness used a different checker")
        if self.admission_evidence.task_definition_id != self.definition.task_id:
            raise TaskModelError("AdmissionReport belongs to another TaskDefinition")
        if self.admission_evidence.checker_digest != self.definition.checker.checker_digest:
            raise TaskModelError("AdmissionReport binds a different checker")
        actual = tuple(item.run_id for item in self.witness_evidence)
        if self.admission_evidence.witness_digests != actual:
            raise TaskModelError("AdmissionReport does not bind witness evidence")
        if not self.admission_evidence.accepted:
            raise TaskModelError("TaskPack admission evidence is not accepted")

    @property
    def taskpack_id(self) -> str:
        return digest_document(self.identity_preimage_document())

    def identity_preimage_document(self) -> JSONObject:
        return {
            "definition": self.definition.protected_document(),
            "witness_evidence": [item.to_document() for item in self.witness_evidence],
            "admission_evidence": self.admission_evidence.to_document(),
        }

    def to_document(self) -> JSONObject:
        return {"taskpack_id": self.taskpack_id, **self.identity_preimage_document()}

    def public_document(self) -> JSONObject:
        return {"taskpack_id": self.taskpack_id, "task": self.definition.public_document()}


@dataclass(frozen=True, slots=True)
class AssessmentRun:
    run_id: str
    status: CheckerStatus
    calls: int
    input_tokens: int
    output_tokens: int
    latency_ms: int
    failure_label: str | None

    def __post_init__(self) -> None:
        _digest(self.run_id, "assessment run_id")
        if self.status not in _CHECKER_STATUSES:
            raise TaskModelError("assessment status is invalid")
        for value, role in (
            (self.calls, "calls"),
            (self.input_tokens, "input_tokens"),
            (self.output_tokens, "output_tokens"),
            (self.latency_ms, "latency_ms"),
        ):
            if value < 0:
                raise TaskModelError(f"assessment {role} must be non-negative")
        if self.failure_label is not None:
            _identifier(self.failure_label, "failure_label")

    def to_document(self) -> JSONObject:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "calls": self.calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "latency_ms": self.latency_ms,
            "failure_label": self.failure_label,
        }


@dataclass(frozen=True, slots=True)
class TaskAssessment:
    taskpack_id: str
    model_id: str
    policy_digest: str
    runner_digest: str
    run_results: tuple[AssessmentRun, ...]
    reliability: float
    calls: int
    tokens: int
    latency_ms: int
    failure_labels: tuple[str, ...]

    def __post_init__(self) -> None:
        _digest(self.taskpack_id, "assessment taskpack_id")
        _identifier(self.model_id, "assessment model_id")
        _digest(self.policy_digest, "policy_digest")
        _digest(self.runner_digest, "runner_digest")
        if not 0.0 <= self.reliability <= 1.0:
            raise TaskModelError("assessment reliability must be between zero and one")
        if min(self.calls, self.tokens, self.latency_ms) < 0:
            raise TaskModelError("assessment cost fields must be non-negative")
        _unique(self.failure_labels, "assessment failure_labels")

    @property
    def assessment_id(self) -> str:
        return digest_document(self.to_document())

    def to_document(self) -> JSONObject:
        return {
            "taskpack_id": self.taskpack_id,
            "model_id": self.model_id,
            "policy_digest": self.policy_digest,
            "runner_digest": self.runner_digest,
            "run_results": [item.to_document() for item in self.run_results],
            "reliability": self.reliability,
            "calls": self.calls,
            "tokens": self.tokens,
            "latency_ms": self.latency_ms,
            "failure_labels": list(self.failure_labels),
        }


@dataclass(frozen=True, slots=True)
class TaskFingerprint:
    capability_ids: tuple[str, ...]
    workflow_ids: tuple[str, ...]
    composition_rule_ids: tuple[str, ...]
    goal_shape: str
    selector_operators: tuple[str, ...]
    relation_count: int
    public_binding_depth: int
    start_regimes: tuple[str, ...]
    answer_required: bool
    process_required: bool

    def __post_init__(self) -> None:
        if self.relation_count <= 0 or self.public_binding_depth < 0:
            raise TaskModelError("fingerprint relation/depth fields are invalid")

    @property
    def fingerprint_id(self) -> str:
        return digest_document(self.to_document())

    def to_document(self) -> JSONObject:
        return {
            "capability_ids": list(self.capability_ids),
            "workflow_ids": list(self.workflow_ids),
            "composition_rule_ids": list(self.composition_rule_ids),
            "goal_shape": self.goal_shape,
            "selector_operators": list(self.selector_operators),
            "relation_count": self.relation_count,
            "public_binding_depth": self.public_binding_depth,
            "start_regimes": list(self.start_regimes),
            "answer_required": self.answer_required,
            "process_required": self.process_required,
        }


@dataclass(frozen=True, slots=True)
class CorpusManifest:
    policy_digest: str
    seed: int
    taskpack_ids: tuple[str, ...]
    assessment_ids: tuple[str, ...]
    selection_evidence_digest: str

    def __post_init__(self) -> None:
        _digest(self.policy_digest, "corpus policy_digest")
        _digest(self.selection_evidence_digest, "selection_evidence_digest")
        for values, role in (
            (self.taskpack_ids, "taskpack_ids"),
            (self.assessment_ids, "assessment_ids"),
        ):
            _unique(values, f"corpus {role}")
            for value in values:
                _digest(value, f"corpus {role}")

    @property
    def corpus_id(self) -> str:
        return digest_document(self.to_document())

    def to_document(self) -> JSONObject:
        return {
            "policy_digest": self.policy_digest,
            "seed": self.seed,
            "taskpack_ids": list(self.taskpack_ids),
            "assessment_ids": list(self.assessment_ids),
            "selection_evidence_digest": self.selection_evidence_digest,
        }


@dataclass(frozen=True, slots=True)
class FoundryFailure:
    kind: FailureKind
    code: str
    message: str
    evidence_digests: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.kind not in _FAILURE_KINDS:
            raise TaskModelError("unknown failure kind")
        _identifier(self.code, "failure code")
        _text(self.message, "failure message")
        for value in self.evidence_digests:
            _digest(value, "failure evidence_digest")

    def to_document(self) -> JSONObject:
        return {
            "kind": self.kind,
            "code": self.code,
            "message": self.message,
            "evidence_digests": list(self.evidence_digests),
        }


def _goal_less_branch_reports(goal: GoalProgram) -> set[tuple[str, str | None]]:
    if isinstance(goal, IfGoal):
        required = {
            (goal.condition_id, goal.binding_slot)
            for branch in (goal.then_goal, goal.else_goal)
            if branch is None
        }
        for branch in (goal.then_goal, goal.else_goal):
            if branch is not None:
                required |= _goal_less_branch_reports(branch)
        return required
    if isinstance(goal, AllGoal):
        return {item for child in goal.children for item in _goal_less_branch_reports(child)}
    return set()


def _identifier(value: str, role: str) -> None:
    if not value or value.strip() != value or any(character.isspace() for character in value):
        raise TaskModelError(f"{role} must be a non-empty whitespace-free string")


def _text(value: str, role: str) -> None:
    if not value.strip():
        raise TaskModelError(f"{role} must be non-empty")


def _digest(value: str, role: str) -> None:
    if len(value) != 64 or any(character not in _HEX for character in value):
        raise TaskModelError(f"{role} must be a lowercase SHA-256 digest")


def _unique(values: tuple[Any, ...], role: str) -> None:
    if len(values) != len(set(values)):
        raise TaskModelError(f"{role} must be unique")


def _object(value: JSONObject, role: str) -> None:
    if not is_json_object(value):
        raise TaskModelError(f"{role} must be a JSON object")


def _json(value: JSONValue, role: str) -> None:
    if not is_json_value(value):
        raise TaskModelError(f"{role} must be a JSON value")
