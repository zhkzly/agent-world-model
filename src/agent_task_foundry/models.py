"""Immutable Goal-first Task and evidence identity contracts."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Literal, cast

from agent_env_foundry.environment import JSONObject, JSONValue
from agent_env_foundry.jsonvalue import is_json_object, is_json_value
from agent_env_foundry.release import canonical_bytes
from agent_env_foundry.semantics import PublicValueSource, StartCase

SelectorOperator = Literal["eq", "neq", "lt", "lte", "gt", "gte"]
RankDirection = Literal["min", "max"]
SelectorCardinality = Literal["exactly_one", "any_one", "all"]
CheckerStatus = Literal["satisfied", "failed", "abstain"]
ChallengeVerdict = Literal["passed", "failed", "not_applicable"]
NonPublicArgumentSource = Literal["agent_choice", "unresolved", "protected"]
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
    "VerifierDefect",
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
_NON_PUBLIC_ARGUMENT_SOURCES = frozenset({"agent_choice", "unresolved", "protected"})
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
        "VerifierDefect",
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
        _validate_blueprint_goal(self.goal, self.selectors)
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
class LogicalBindingRef:
    slot: str
    capability_id: str
    semantic_key: str
    selector_id: str
    instruction_values: JSONObject

    def __post_init__(self) -> None:
        _identifier(self.slot, "logical binding slot")
        _identifier(self.capability_id, "logical binding capability_id")
        _identifier(self.semantic_key, "logical binding semantic_key")
        _identifier(self.selector_id, "logical binding selector_id")
        _object(self.instruction_values, "logical binding instruction_values")

    @property
    def logical_ref_digest(self) -> str:
        return digest_document(self.to_document())

    def to_document(self) -> JSONObject:
        return {
            "slot": self.slot,
            "capability_id": self.capability_id,
            "semantic_key": self.semantic_key,
            "selector_id": self.selector_id,
            "instruction_values": canonical_document(self.instruction_values),
        }


@dataclass(frozen=True, slots=True)
class LogicalSelection:
    selector: SelectorSpec
    semantic_keys: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.semantic_keys:
            raise TaskModelError("logical selection semantic_keys must not be empty")
        _unique(self.semantic_keys, "logical selection semantic_keys")
        for value in self.semantic_keys:
            _identifier(value, "logical selection semantic_key")
        if self.selector.cardinality in {"exactly_one", "any_one"} and len(self.semantic_keys) != 1:
            raise TaskModelError("logical selection cardinality requires exactly one member")
        if self.semantic_keys != tuple(sorted(self.semantic_keys)):
            raise TaskModelError("logical selection semantic_keys must use stable order")

    @property
    def selector_id(self) -> str:
        return self.selector.selector_id

    @property
    def selection_digest(self) -> str:
        return digest_document(self.to_document())

    def to_document(self) -> JSONObject:
        return {
            "selector": self.selector.to_document(),
            "semantic_keys": list(self.semantic_keys),
        }


@dataclass(frozen=True, slots=True)
class ResolvedBinding:
    logical_ref_digest: str
    materialization_id: str
    protected_binding: JSONObject
    public_descriptor: JSONObject
    source_evidence_digest: str

    def __post_init__(self) -> None:
        _digest(self.logical_ref_digest, "resolved logical_ref_digest")
        _digest(self.materialization_id, "resolved materialization_id")
        _digest(self.source_evidence_digest, "resolved source_evidence_digest")
        _object(self.protected_binding, "resolved protected_binding")
        _object(self.public_descriptor, "resolved public_descriptor")

    def to_document(self) -> JSONObject:
        return {
            "logical_ref_digest": self.logical_ref_digest,
            "materialization_id": self.materialization_id,
            "protected_binding": canonical_document(self.protected_binding),
            "public_descriptor": canonical_document(self.public_descriptor),
            "source_evidence_digest": self.source_evidence_digest,
        }


@dataclass(frozen=True, slots=True)
class CheckerArtifact:
    task_preimage_digest: str
    goal_program: GoalProgram
    logical_bindings: tuple[LogicalBindingRef, ...]
    logical_selections: tuple[LogicalSelection, ...]
    answer_schema: JSONObject | None
    semantics_digest: str

    def __post_init__(self) -> None:
        _digest(self.task_preimage_digest, "task_preimage_digest")
        _digest(self.semantics_digest, "semantics_digest")
        _validate_logical_binding_graph(
            self.logical_bindings,
            self.logical_selections,
            "checker",
        )
        if self.answer_schema is not None:
            _object(self.answer_schema, "answer_schema")

    @property
    def checker_digest(self) -> str:
        return digest_document(self.to_document())

    def to_document(self) -> JSONObject:
        return {
            "task_preimage_digest": self.task_preimage_digest,
            "goal_program": self.goal_program.to_document(),
            "logical_bindings": [item.to_document() for item in self.logical_bindings],
            "logical_selections": [item.to_document() for item in self.logical_selections],
            "answer_schema": canonical_document(self.answer_schema),
            "semantics_digest": self.semantics_digest,
        }


@dataclass(frozen=True, slots=True)
class TaskDefinition:
    release_id: str
    semantics_digest: str
    start_case: StartCase
    blueprint: TaskBlueprint
    logical_bindings: tuple[LogicalBindingRef, ...]
    logical_selections: tuple[LogicalSelection, ...]
    public_instruction_frame: JSONObject
    canonical_instruction: str
    answer_schema: JSONObject | None
    checker: CheckerArtifact

    def __post_init__(self) -> None:
        _digest(self.release_id, "release_id")
        _digest(self.semantics_digest, "semantics_digest")
        _validate_logical_binding_graph(
            self.logical_bindings,
            self.logical_selections,
            "Task",
        )
        blueprint_selectors = {item.selector_id: item for item in self.blueprint.selectors}
        selection_selectors = {item.selector_id: item.selector for item in self.logical_selections}
        if blueprint_selectors != selection_selectors:
            raise TaskModelError("Task logical selections differ from Blueprint selectors")
        _object(self.public_instruction_frame, "public_instruction_frame")
        _text(self.canonical_instruction, "canonical_instruction")
        if self.answer_schema is not None:
            _object(self.answer_schema, "answer_schema")
        if self.checker.semantics_digest != self.semantics_digest:
            raise TaskModelError("checker binds a different semantics_digest")
        if self.checker.goal_program != self.blueprint.goal:
            raise TaskModelError("checker goal differs from Task Blueprint goal")
        if self.checker.answer_schema != self.answer_schema:
            raise TaskModelError("checker answer schema differs from TaskDefinition")
        expected_preimage = digest_document(
            {
                "start_case_id": self.start_case.case_id,
                "blueprint": self.blueprint.to_document(),
            }
        )
        if self.checker.task_preimage_digest != expected_preimage:
            raise TaskModelError("checker task preimage differs from TaskDefinition")
        if self.checker.logical_bindings != self.logical_bindings:
            raise TaskModelError("checker binds different logical bindings")
        if self.checker.logical_selections != self.logical_selections:
            raise TaskModelError("checker binds different logical selections")
        _validate_task_goal(
            self.blueprint.goal,
            self.logical_bindings,
            self.logical_selections,
        )

    @property
    def task_id(self) -> str:
        return digest_document(self.identity_preimage_document())

    def identity_preimage_document(self) -> JSONObject:
        return {
            "release_id": self.release_id,
            "semantics_digest": self.semantics_digest,
            "start_case": self.start_case.to_document(),
            "blueprint": self.blueprint.to_document(),
            "logical_bindings": [item.to_document() for item in self.logical_bindings],
            "logical_selections": [item.to_document() for item in self.logical_selections],
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

    def to_document(self) -> JSONObject:
        return {
            "events": [item.to_document() for item in self.events],
            "model_call_allowed": self.model_call_allowed,
        }


@dataclass(frozen=True, slots=True)
class EpisodeIdentity:
    materialization_id: str
    route_digest: str
    prompt_digest: str
    runner_digest: str
    conversation_id: str

    def __post_init__(self) -> None:
        for value, role in (
            (self.materialization_id, "episode materialization_id"),
            (self.route_digest, "episode route_digest"),
            (self.prompt_digest, "episode prompt_digest"),
            (self.runner_digest, "episode runner_digest"),
        ):
            _digest(value, role)
        _identifier(self.conversation_id, "episode conversation_id")

    @property
    def episode_id(self) -> str:
        return digest_document(self.to_document())

    def to_document(self) -> JSONObject:
        return {
            "materialization_id": self.materialization_id,
            "route_digest": self.route_digest,
            "prompt_digest": self.prompt_digest,
            "runner_digest": self.runner_digest,
            "conversation_id": self.conversation_id,
        }


@dataclass(frozen=True, slots=True)
class PublicValueOccurrence:
    source: PublicValueSource
    materialization_id: str
    instruction_slot: str | None
    trace_event_seq: int | None
    json_pointer: str | None

    def __post_init__(self) -> None:
        _digest(self.materialization_id, "value occurrence materialization_id")
        if self.source.kind == "task_literal":
            if self.instruction_slot is None:
                raise TaskModelError("task_literal occurrence requires instruction_slot")
            if not self.instruction_slot.startswith("/"):
                raise TaskModelError("task_literal instruction_slot must be an RFC 6901 pointer")
            if self.trace_event_seq is not None or self.json_pointer is not None:
                raise TaskModelError("task_literal occurrence cannot use trace/json pointer")
            return
        if self.instruction_slot is not None:
            raise TaskModelError("non-literal occurrence must not declare instruction_slot")
        if self.json_pointer != self.source.json_pointer:
            raise TaskModelError("value occurrence json_pointer differs from source")
        if self.source.kind == "tool_output":
            if self.trace_event_seq is None or self.trace_event_seq <= 0:
                raise TaskModelError("tool_output occurrence requires trace_event_seq")
        elif self.trace_event_seq is not None:
            raise TaskModelError("non-output occurrence must not declare trace_event_seq")

    @property
    def occurrence_digest(self) -> str:
        return digest_document(self.to_document())

    def to_document(self) -> JSONObject:
        return {
            "source": self.source.to_document(),
            "source_digest": digest_document(self.source.to_document()),
            "materialization_id": self.materialization_id,
            "instruction_slot": self.instruction_slot,
            "trace_event_seq": self.trace_event_seq,
            "json_pointer": self.json_pointer,
        }


@dataclass(frozen=True, slots=True)
class ArgumentOrigin:
    path: str
    source: PublicValueOccurrence | NonPublicArgumentSource
    load_bearing: bool

    def __post_init__(self) -> None:
        if not self.path.startswith("/"):
            raise TaskModelError("argument path must be an RFC 6901 pointer")
        if isinstance(self.source, str) and self.source not in _NON_PUBLIC_ARGUMENT_SOURCES:
            raise TaskModelError("argument provenance source is invalid")

    def to_document(self) -> JSONObject:
        return {
            "path": self.path,
            "source": (
                self.source.to_document()
                if isinstance(self.source, PublicValueOccurrence)
                else self.source
            ),
            "load_bearing": self.load_bearing,
        }


@dataclass(frozen=True, slots=True)
class ProvenanceReport:
    origins: tuple[ArgumentOrigin, ...]

    @property
    def complete(self) -> bool:
        return all(
            not origin.load_bearing or isinstance(origin.source, PublicValueOccurrence)
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
    episode: EpisodeIdentity
    task_definition_id: str
    start_case_id: str
    reset_observation: JSONValue
    resolved_bindings: tuple[ResolvedBinding, ...]
    trace: tuple[PublicTraceEvent, ...]
    final_answer: JSONValue
    checker_digest: str
    before_facts_digest: str
    after_facts_digest: str
    checker_status: CheckerStatus
    checker_failures: tuple[str, ...]

    def __post_init__(self) -> None:
        for value, role in (
            (self.task_definition_id, "task_definition_id"),
            (self.checker_digest, "checker_digest"),
            (self.before_facts_digest, "before_facts_digest"),
            (self.after_facts_digest, "after_facts_digest"),
        ):
            _digest(value, role)
        _identifier(self.start_case_id, "start_case_id")
        _json(self.reset_observation, "reset_observation")
        _json(self.final_answer, "final_answer")
        _unique(self.checker_failures, "checker_failures")
        if self.checker_status not in _CHECKER_STATUSES:
            raise TaskModelError("checker_status is invalid")
        if not self.resolved_bindings:
            raise TaskModelError("witness requires resolved bindings")
        if any(
            item.materialization_id != self.episode.materialization_id
            for item in self.resolved_bindings
        ):
            raise TaskModelError("witness binding belongs to another materialization")
        _unique(
            tuple(item.logical_ref_digest for item in self.resolved_bindings),
            "witness logical binding resolutions",
        )
        _unique(tuple(item.seq for item in self.trace), "witness trace sequence numbers")
        self._validate_provenance_occurrences()

    def _validate_provenance_occurrences(self) -> None:
        events = {item.seq: item for item in self.trace}
        for event in self.trace:
            for origin in event.provenance.origins:
                if not isinstance(origin.source, PublicValueOccurrence):
                    continue
                occurrence = origin.source
                if occurrence.materialization_id != self.episode.materialization_id:
                    raise TaskModelError("value occurrence belongs to another materialization")
                argument_value = _resolve_pointer(event.arguments, origin.path, "tool argument")
                source = occurrence.source
                if source.kind == "task_literal":
                    expected = source.value
                elif source.kind == "reset":
                    expected = _resolve_pointer(
                        self.reset_observation,
                        cast(str, source.json_pointer),
                        "reset observation",
                    )
                elif source.kind == "tool_schema_constant":
                    expected = source.value
                else:
                    source_event = events.get(cast(int, occurrence.trace_event_seq))
                    if source_event is None or source_event.seq >= event.seq:
                        raise TaskModelError(
                            "tool_output occurrence must reference an actual prior trace event"
                        )
                    if source_event.tool_name != source.tool_name:
                        raise TaskModelError("tool_output occurrence references the wrong tool")
                    observation = source_event.observation
                    if observation.get("ok") is not True or "data" not in observation:
                        raise TaskModelError(
                            "tool_output occurrence requires successful observation"
                        )
                    expected = _resolve_pointer(
                        observation["data"],
                        cast(str, source.json_pointer),
                        "tool observation data",
                    )
                if argument_value != expected:
                    raise TaskModelError("argument value differs from its public source occurrence")

    @property
    def materialization_id(self) -> str:
        return self.episode.materialization_id

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
            "episode": self.episode.to_document(),
            "episode_id": self.episode.episode_id,
            "task_definition_id": self.task_definition_id,
            "start_case_id": self.start_case_id,
            "reset_observation": canonical_document(self.reset_observation),
            "resolved_bindings": [item.to_document() for item in self.resolved_bindings],
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
class ChallengePlan:
    challenge_id: str
    applicable: bool
    reason_code: str | None

    def __post_init__(self) -> None:
        _identifier(self.challenge_id, "planned challenge_id")
        _applicability(self.applicable, self.reason_code, "planned challenge")

    def to_document(self) -> JSONObject:
        return {
            "challenge_id": self.challenge_id,
            "applicable": self.applicable,
            "reason_code": self.reason_code,
        }


@dataclass(frozen=True, slots=True)
class CheckerMutationPlan:
    mutation_id: str
    applicable: bool
    reason_code: str | None

    def __post_init__(self) -> None:
        _identifier(self.mutation_id, "planned mutation_id")
        _applicability(self.applicable, self.reason_code, "planned mutation")

    def to_document(self) -> JSONObject:
        return {
            "mutation_id": self.mutation_id,
            "applicable": self.applicable,
            "reason_code": self.reason_code,
        }


@dataclass(frozen=True, slots=True)
class AdmissionPlan:
    task_definition_id: str
    checker_digest: str
    challenges: tuple[ChallengePlan, ...]
    checker_mutations: tuple[CheckerMutationPlan, ...]

    def __post_init__(self) -> None:
        _digest(self.task_definition_id, "admission plan task_definition_id")
        _digest(self.checker_digest, "admission plan checker_digest")
        _unique(tuple(item.challenge_id for item in self.challenges), "planned challenge IDs")
        _unique(
            tuple(item.mutation_id for item in self.checker_mutations),
            "planned mutation IDs",
        )
        if not self.challenges or not self.checker_mutations:
            raise TaskModelError("admission plan requires challenges and checker mutations")

    @property
    def plan_digest(self) -> str:
        return digest_document(self.to_document())

    def to_document(self) -> JSONObject:
        return {
            "task_definition_id": self.task_definition_id,
            "checker_digest": self.checker_digest,
            "challenges": [item.to_document() for item in self.challenges],
            "checker_mutations": [item.to_document() for item in self.checker_mutations],
        }


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
    plan_digest: str
    witness_digests: tuple[str, str]
    challenges: tuple[ChallengeResult, ...]
    checker_mutations: tuple[CheckerMutationResult, ...]

    def __post_init__(self) -> None:
        _digest(self.task_definition_id, "admission task_definition_id")
        _digest(self.checker_digest, "admission checker_digest")
        _digest(self.plan_digest, "admission plan_digest")
        for value in self.witness_digests:
            _digest(value, "admission witness_digest")
        _unique(tuple(item.challenge_id for item in self.challenges), "challenge result IDs")
        _unique(
            tuple(item.mutation_id for item in self.checker_mutations),
            "mutation result IDs",
        )

    def validate_plan(self, plan: AdmissionPlan) -> None:
        if self.plan_digest != plan.plan_digest:
            raise TaskModelError("AdmissionReport binds a different admission plan")
        if self.task_definition_id != plan.task_definition_id:
            raise TaskModelError("AdmissionReport plan belongs to another TaskDefinition")
        if self.checker_digest != plan.checker_digest:
            raise TaskModelError("AdmissionReport plan binds another checker")
        challenge_results = {item.challenge_id: item for item in self.challenges}
        if set(challenge_results) != {item.challenge_id for item in plan.challenges}:
            raise TaskModelError("AdmissionReport does not cover its planned challenges")
        for challenge_plan in plan.challenges:
            challenge_result = challenge_results[challenge_plan.challenge_id]
            if challenge_plan.applicable and challenge_result.verdict == "not_applicable":
                raise TaskModelError("applicable planned challenge was not executed")
            if not challenge_plan.applicable and (
                challenge_result.verdict != "not_applicable"
                or challenge_result.reason_code != challenge_plan.reason_code
            ):
                raise TaskModelError("non-applicable challenge differs from its plan")
        mutation_results = {item.mutation_id: item for item in self.checker_mutations}
        if set(mutation_results) != {item.mutation_id for item in plan.checker_mutations}:
            raise TaskModelError("AdmissionReport does not cover its planned mutations")
        for mutation_plan in plan.checker_mutations:
            mutation_result = mutation_results[mutation_plan.mutation_id]
            if mutation_plan.applicable and not mutation_result.reachable:
                raise TaskModelError("applicable planned mutation is unreachable")
            if not mutation_plan.applicable and (
                mutation_result.reachable
                or mutation_result.killed
                or mutation_result.reason_code != mutation_plan.reason_code
            ):
                raise TaskModelError("non-applicable mutation differs from its plan")

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
            "plan_digest": self.plan_digest,
            "witness_digests": list(self.witness_digests),
            "challenges": [item.to_document() for item in self.challenges],
            "checker_mutations": [item.to_document() for item in self.checker_mutations],
            "accepted": self.accepted,
        }


@dataclass(frozen=True, slots=True)
class TaskPack:
    definition: TaskDefinition
    witness_evidence: tuple[WitnessRun, WitnessRun]
    admission_plan: AdmissionPlan
    ordering_journal: OrderingJournal
    admission_evidence: AdmissionReport

    def __post_init__(self) -> None:
        if len(self.witness_evidence) != 2:
            raise TaskModelError("TaskPack requires exactly two witnesses")
        first, second = self.witness_evidence
        if not first.successful or not second.successful:
            raise TaskModelError("TaskPack witnesses must be successful")
        if first.materialization_id == second.materialization_id:
            raise TaskModelError("TaskPack requires distinct fresh materializations")
        if first.episode.episode_id == second.episode.episode_id:
            raise TaskModelError("TaskPack requires distinct fresh episodes")
        if first.start_case_id != second.start_case_id:
            raise TaskModelError("TaskPack witnesses must use the same start case")
        if first.start_case_id != self.definition.start_case.case_id:
            raise TaskModelError("TaskPack witnesses use another TaskDefinition start case")
        expected_refs = tuple(item.logical_ref_digest for item in self.definition.logical_bindings)
        for witness in self.witness_evidence:
            actual_refs = tuple(item.logical_ref_digest for item in witness.resolved_bindings)
            if actual_refs == expected_refs:
                continue
            if len(actual_refs) == len(expected_refs) and set(actual_refs) == set(expected_refs):
                raise TaskModelError("TaskPack witness violates stable resolution order")
            else:
                raise TaskModelError(
                    "TaskPack witness logical binding resolutions differ from TaskDefinition"
                )
        for witness in self.witness_evidence:
            for event in witness.trace:
                for origin in event.provenance.origins:
                    occurrence = origin.source
                    if (
                        isinstance(occurrence, PublicValueOccurrence)
                        and occurrence.source.kind == "task_literal"
                    ):
                        instruction_value = _resolve_pointer(
                            self.definition.public_instruction_frame,
                            cast(str, occurrence.instruction_slot),
                            "public instruction frame",
                        )
                        if instruction_value != occurrence.source.value:
                            raise TaskModelError(
                                "task literal occurrence differs from frozen instruction frame"
                            )
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
        if self.admission_plan.task_definition_id != self.definition.task_id:
            raise TaskModelError("admission plan belongs to another TaskDefinition")
        if self.admission_plan.checker_digest != self.definition.checker.checker_digest:
            raise TaskModelError("admission plan binds a different checker")
        self.admission_evidence.validate_plan(self.admission_plan)
        expected_ordering = (
            self.definition.checker.checker_digest,
            digest_document(self.definition.canonical_instruction),
            self.definition.task_id,
            self.admission_plan.plan_digest,
        )
        if (
            len(self.ordering_journal.events) != 4
            or tuple(item.artifact_digest for item in self.ordering_journal.events)
            != expected_ordering
        ):
            raise TaskModelError("TaskPack ordering evidence does not bind frozen artifacts")
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
            "admission_plan": self.admission_plan.to_document(),
            "admission_plan_digest": self.admission_plan.plan_digest,
            "ordering_journal": self.ordering_journal.to_document(),
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


def _validate_blueprint_goal(
    goal: GoalProgram,
    selectors: tuple[SelectorSpec, ...],
) -> None:
    selector_map = {item.selector_id: item for item in selectors}

    def visit(node: GoalProgram) -> None:
        if isinstance(node, ForEachGoal):
            selector = selector_map.get(node.selector_id)
            if selector is None:
                raise TaskModelError("ForEach goal references a missing selector")
            if selector.capability_id != node.capability_id:
                raise TaskModelError("ForEach goal selector uses another capability")
            if selector.cardinality != "all":
                raise TaskModelError("ForEach goal requires selector cardinality all")
            return
        if isinstance(node, AllGoal):
            for child in node.children:
                visit(child)
            return
        if isinstance(node, IfGoal):
            for branch in (node.then_goal, node.else_goal):
                if branch is not None:
                    visit(branch)

    visit(goal)


def _validate_task_goal(
    goal: GoalProgram,
    bindings: tuple[LogicalBindingRef, ...],
    selections: tuple[LogicalSelection, ...],
) -> None:
    binding_map = {item.slot: item for item in bindings}
    selection_map = {item.selector_id: item for item in selections}

    def visit(node: GoalProgram) -> set[str]:
        if isinstance(node, AtomGoal):
            binding = binding_map.get(node.binding_slot)
            if binding is None:
                raise TaskModelError("Atom goal references a missing logical binding slot")
            if binding.capability_id != node.capability_id:
                raise TaskModelError("Atom goal binding uses another capability")
            return {binding.slot}
        if isinstance(node, ForEachGoal):
            selection = selection_map.get(node.selector_id)
            if selection is None:
                raise TaskModelError("ForEach goal references a missing logical selection")
            if selection.selector.capability_id != node.capability_id:
                raise TaskModelError("ForEach logical selection uses another capability")
            return {item.slot for item in bindings if item.selector_id == selection.selector_id}
        if isinstance(node, AllGoal):
            all_consumed: set[str] = set()
            for child in node.children:
                child_consumed = visit(child)
                if all_consumed & child_consumed:
                    raise TaskModelError("AllGoal consumes logical slot more than once")
                all_consumed |= child_consumed
            return all_consumed
        if isinstance(node, IfGoal):
            if_consumed: set[str] = set()
            if node.binding_slot is not None:
                binding = binding_map.get(node.binding_slot)
                if binding is None:
                    raise TaskModelError("If goal references a missing logical binding slot")
                if_consumed.add(binding.slot)
            for branch in (node.then_goal, node.else_goal):
                if branch is not None:
                    if_consumed |= visit(branch)
            return if_consumed
        raise AssertionError(f"unhandled goal type: {type(node).__name__}")

    consumed_bindings = visit(goal)
    if consumed_bindings != set(binding_map):
        raise TaskModelError("Task Goal leaves unused logical bindings")


def _validate_logical_binding_graph(
    bindings: tuple[LogicalBindingRef, ...],
    selections: tuple[LogicalSelection, ...],
    role: str,
) -> None:
    _unique(tuple(item.slot for item in bindings), f"{role} logical slots")
    _unique(
        tuple(item.selector_id for item in selections),
        f"{role} logical selection IDs",
    )
    by_selector = {item.selector_id: item for item in selections}
    actual_members: dict[str, list[str]] = {selector_id: [] for selector_id in by_selector}
    for binding in bindings:
        selection = by_selector.get(binding.selector_id)
        if selection is None:
            raise TaskModelError(f"{role} logical binding references a missing selection")
        if binding.capability_id != selection.selector.capability_id:
            raise TaskModelError(f"{role} logical binding uses another selector capability")
        actual_members[binding.selector_id].append(binding.semantic_key)
    for selector_id, selection in by_selector.items():
        actual = tuple(actual_members[selector_id])
        if actual == selection.semantic_keys:
            continue
        if len(actual) == len(selection.semantic_keys) and set(actual) == set(
            selection.semantic_keys
        ):
            raise TaskModelError(f"{role} logical selection violates stable member order")
        else:
            raise TaskModelError(f"{role} logical selection membership is inconsistent")


def _applicability(applicable: bool, reason_code: str | None, role: str) -> None:
    if applicable and reason_code is not None:
        raise TaskModelError(f"{role} applicable item must not have reason_code")
    if not applicable:
        if reason_code is None:
            raise TaskModelError(f"{role} non-applicable item requires reason_code")
        _identifier(reason_code, f"{role} reason_code")


def _resolve_pointer(value: JSONValue, pointer: str, role: str) -> JSONValue:
    if pointer == "":
        return value
    if not pointer.startswith("/"):
        raise TaskModelError(f"{role} pointer must be RFC 6901")
    current = value
    for raw_token in pointer[1:].split("/"):
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict) and token in current:
            current = current[token]
            continue
        if isinstance(current, list) and token.isdigit() and int(token) < len(current):
            current = current[int(token)]
            continue
        raise TaskModelError(f"{role} pointer {pointer!r} does not resolve")
    return current


def _object(value: JSONObject, role: str) -> None:
    if not is_json_object(value):
        raise TaskModelError(f"{role} must be a JSON object")


def _json(value: JSONValue, role: str) -> None:
    if not is_json_value(value):
        raise TaskModelError(f"{role} must be a JSON value")
