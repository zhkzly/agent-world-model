"""Host materialization of sampled TaskDrafts into freshly replayed Candidates."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

from agent_env_foundry.environment import JSONObject, JSONValue
from agent_env_foundry.jsonvalue import is_json_object, json_leaf_changes
from agent_env_foundry.release import _hex_digest, canonical_bytes, sha256_hex
from agent_env_foundry.task_draft import (
    AllDraft,
    AtomDraft,
    DraftGoal,
    IfDraft,
    PublicValueRef,
    SamplingTarget,
    draft_atom_steps,
    materialize_answer,
)
from agent_env_foundry.task_goal import (
    AllGoal,
    AtomGoal,
    EvaluationContext,
    EvaluationResult,
    ForEachGoal,
    Goal,
    GoalTruth,
    GoalValueSource,
    IfGoal,
    ScalarCondition,
    TraceEvent,
    evaluate_goal,
    goal_truth_from_document,
)
from agent_env_foundry.task_proposal import (
    PreparedTaskEnvironment,
    SampledTaskDraft,
)

CANDIDATE_TASK_FORMAT = "candidate-task/2"
REFERENCE_REPLAY_FORMAT = "reference-replay/1"
CandidateFailureKind = Literal[
    "DraftRejected",
    "EnvironmentDefect",
    "FrameworkDefect",
    "InfrastructureFailure",
]


class CandidateMaterializationFailure(RuntimeError):
    def __init__(
        self,
        kind: CandidateFailureKind,
        code: str,
        message: str,
        **details: Any,
    ) -> None:
        super().__init__(message)
        self.kind, self.code, self.details = kind, code, details


@dataclass(frozen=True, slots=True)
class ArgumentOrigin:
    step: int
    argument_pointer: str
    source: PublicValueRef

    def __post_init__(self) -> None:
        if not isinstance(self.step, int) or isinstance(self.step, bool) or self.step <= 0:
            raise ValueError("argument origin step must be positive")
        if not self.argument_pointer.startswith("/"):
            raise ValueError("argument origin requires a non-root JSON pointer")
        if not isinstance(self.source, PublicValueRef):
            raise ValueError("argument origin source must be public")

    def to_document(self) -> JSONObject:
        return {
            "step": self.step,
            "argument_pointer": self.argument_pointer,
            "source": self.source.to_document(),
        }


@dataclass(frozen=True, slots=True)
class ReferenceReplay:
    release_id: str
    sampling_evidence_id: str
    reset_observation: JSONValue
    before_state: JSONValue
    after_state: JSONValue
    trace: tuple[TraceEvent, ...]
    expected_answer: JSONObject
    step_mutations: tuple[bool, ...]
    evaluation: EvaluationResult

    @property
    def replay_id(self) -> str:
        return _document_digest(self.to_document())

    def to_document(self) -> JSONObject:
        return {
            "format": REFERENCE_REPLAY_FORMAT,
            "release_id": self.release_id,
            "sampling_evidence_id": self.sampling_evidence_id,
            "reset_observation": _copy_json(self.reset_observation),
            "before_state": _copy_json(self.before_state),
            "after_state": _copy_json(self.after_state),
            "trace": [event.to_document() for event in self.trace],
            "expected_answer": _copy_object(self.expected_answer),
            "step_mutations": list(self.step_mutations),
            "evaluation": self.evaluation.to_document(),
        }


@dataclass(frozen=True, slots=True)
class CandidateTask:
    release_id: str
    builder_projection_digest: str
    reset_start: JSONObject | None
    instruction: str
    goal_truth: GoalTruth
    sampling_evidence_id: str
    reference_replay_id: str
    structure_id: str

    def __post_init__(self) -> None:
        for value, role in (
            (self.release_id, "release_id"),
            (self.builder_projection_digest, "builder_projection_digest"),
            (self.sampling_evidence_id, "sampling_evidence_id"),
            (self.reference_replay_id, "reference_replay_id"),
            (self.structure_id, "structure_id"),
        ):
            _digest(value, role)
        if self.reset_start is not None and not is_json_object(self.reset_start):
            raise ValueError("Candidate reset_start must be an object or null")
        if not isinstance(self.instruction, str) or not self.instruction.strip():
            raise ValueError("Candidate instruction must be non-empty")
        if not isinstance(self.goal_truth, GoalTruth):
            raise ValueError("Candidate requires GoalTruth")

    @property
    def candidate_id(self) -> str:
        return _document_digest(self.to_document())

    @property
    def final_answer_schema(self) -> JSONObject:
        return _copy_object(self.goal_truth.final_answer_schema)

    def to_document(self) -> JSONObject:
        return {
            "format": CANDIDATE_TASK_FORMAT,
            "release_id": self.release_id,
            "builder_projection_digest": self.builder_projection_digest,
            "reset_start": _copy_json(self.reset_start),
            "instruction": self.instruction,
            "goal_truth": self.goal_truth.to_document(),
            "sampling_evidence_id": self.sampling_evidence_id,
            "reference_replay_id": self.reference_replay_id,
            "structure_id": self.structure_id,
        }


@dataclass(frozen=True, slots=True)
class MaterializedCandidate:
    candidate: CandidateTask
    replay: ReferenceReplay
    argument_origins: tuple[ArgumentOrigin, ...]


def materialize_candidate(
    prepared: PreparedTaskEnvironment,
    *,
    sampled: SampledTaskDraft,
    target: SamplingTarget,
    builder_projection_digest: str,
    replay_instance: Path,
) -> MaterializedCandidate:
    """Derive public provenance, replay physically, and seal one Candidate."""

    if sampled.draft.sampling_target_id != target.target_id:
        raise CandidateMaterializationFailure(
            "DraftRejected", "sampling_target_mismatch", "sampled Draft belongs to another target"
        )
    _digest(builder_projection_digest, "builder_projection_digest")
    evidence = sampled.evidence
    if evidence.release_id != prepared.identity.release_id:
        raise CandidateMaterializationFailure(
            "FrameworkDefect",
            "sampling_release_mismatch",
            "sampling evidence belongs to another Release",
        )
    origins = derive_argument_origins(
        evidence.public_trace,
        reset=evidence.reset_observation,
        instruction=sampled.draft.instruction,
    )
    origin_index = {(item.step, item.argument_pointer): item.source for item in origins}
    replay_trace: list[TraceEvent] = []
    mutations: list[bool] = []
    try:
        with prepared.open(replay_instance) as session:
            reset = session.actor.reset(evidence.reset_start)
            catalog = session.actor.tools()
            before = prepared.read_state(replay_instance)
            previous = before
            for expected in evidence.public_trace:
                arguments = _resolve_arguments(
                    expected.arguments,
                    step=expected.seq,
                    origins=origin_index,
                    reset=reset,
                    trace=tuple(replay_trace),
                )
                observation = session.actor.invoke(expected.tool_name, arguments)
                actual = TraceEvent(
                    expected.seq,
                    expected.tool_name,
                    arguments,
                    cast(JSONObject, observation),
                )
                if not _same(actual.observation, expected.observation):
                    raise CandidateMaterializationFailure(
                        "EnvironmentDefect",
                        "reference_replay_observation_mismatch",
                        "fresh replay observation differs from sampling evidence",
                        step=expected.seq,
                    )
                replay_trace.append(actual)
                current = prepared.read_state(replay_instance)
                mutations.append(not _same(previous, current))
                previous = current
            after = previous
    except CandidateMaterializationFailure:
        raise
    except Exception as exc:
        kind: CandidateFailureKind = (
            "InfrastructureFailure"
            if getattr(exc, "kind", None) == "InfrastructureFailure"
            else "EnvironmentDefect"
        )
        raise CandidateMaterializationFailure(
            kind,
            "reference_replay_failed",
            str(exc),
            original_code=type(exc).__name__,
        ) from exc

    if not _same(reset, evidence.reset_observation) or not _same(before, evidence.before_state):
        raise CandidateMaterializationFailure(
            "EnvironmentDefect",
            "reference_replay_start_mismatch",
            "fresh replay did not reconstruct the sampled Start",
        )
    if not _same(after, evidence.after_state):
        raise CandidateMaterializationFailure(
            "EnvironmentDefect",
            "reference_replay_state_mismatch",
            "fresh replay final state differs from sampling evidence",
        )
    objective_steps = set(draft_atom_steps(sampled.draft.goal))
    unexplained = [
        event.seq
        for event, changed in zip(replay_trace, mutations, strict=True)
        if changed and event.seq not in objective_steps
    ]
    if unexplained:
        raise CandidateMaterializationFailure(
            "DraftRejected",
            "unexplained_sampling_mutation",
            "sampling trace contains mutation outside DraftGoal",
            steps=unexplained,
        )

    try:
        answer = materialize_answer(
            sampled.draft.answer,
            reset_observation=reset,
            reset_schema=prepared.reset_observation_schema,
            trace=tuple(replay_trace),
            tool_specs=catalog,
        )
        if not _same(answer.value, evidence.expected_answer) or not _same(
            answer.schema, evidence.final_answer_schema
        ):
            raise CandidateMaterializationFailure(
                "EnvironmentDefect",
                "reference_replay_answer_mismatch",
                "fresh replay answer projection differs from sampling evidence",
            )
        goal = _materialize_goal(
            sampled.draft.goal,
            {event.seq: event for event in replay_trace},
            dict(zip((event.seq for event in replay_trace), mutations, strict=True)),
        )
        truth = GoalTruth(
            goal,
            evidence.reset_observation,
            evidence.before_state,
            evidence.after_state,
            evidence.expected_answer,
            evidence.final_answer_schema,
        )
    except CandidateMaterializationFailure:
        raise
    except ValueError as exc:
        raise CandidateMaterializationFailure(
            "DraftRejected", "goal_materialization_invalid", str(exc)
        ) from exc
    context = EvaluationContext(
        reset,
        before,
        after,
        tuple(replay_trace),
        answer.value,
    )
    evaluation = evaluate_goal(truth, context)
    if not evaluation.passed:
        raise CandidateMaterializationFailure(
            "DraftRejected",
            "reference_goal_unsatisfied",
            "common evaluator rejected the fresh reference replay",
            reasons=list(evaluation.reason_codes),
        )
    replay = ReferenceReplay(
        prepared.identity.release_id,
        evidence.evidence_id,
        reset,
        before,
        after,
        tuple(replay_trace),
        answer.value,
        tuple(mutations),
        evaluation,
    )
    candidate = CandidateTask(
        prepared.identity.release_id,
        builder_projection_digest,
        evidence.reset_start,
        sampled.draft.instruction,
        truth,
        evidence.evidence_id,
        replay.replay_id,
        _structure_id(truth),
    )
    return MaterializedCandidate(candidate, replay, origins)


def candidate_task_from_document(document: Any) -> CandidateTask:
    value = _exact(
        document,
        {
            "format",
            "release_id",
            "builder_projection_digest",
            "reset_start",
            "instruction",
            "goal_truth",
            "sampling_evidence_id",
            "reference_replay_id",
            "structure_id",
        },
        "CandidateTask",
    )
    if value["format"] != CANDIDATE_TASK_FORMAT:
        raise ValueError(f"CandidateTask format must be {CANDIDATE_TASK_FORMAT!r}")
    return CandidateTask(
        cast(str, value["release_id"]),
        cast(str, value["builder_projection_digest"]),
        cast(JSONObject | None, value["reset_start"]),
        cast(str, value["instruction"]),
        goal_truth_from_document(value["goal_truth"]),
        cast(str, value["sampling_evidence_id"]),
        cast(str, value["reference_replay_id"]),
        cast(str, value["structure_id"]),
    )


def derive_argument_origins(
    trace: tuple[TraceEvent, ...],
    *,
    reset: JSONValue,
    instruction: str,
) -> tuple[ArgumentOrigin, ...]:
    visible: list[tuple[PublicValueRef, JSONValue]] = [
        (PublicValueRef.reset(pointer), value) for pointer, value in _leaves(reset)
    ]
    origins: list[ArgumentOrigin] = []
    for event in trace:
        for pointer, value in _leaves(event.arguments):
            source = next(
                (ref for ref, available in visible if _same(available, value)),
                None,
            )
            if source is None and _literal_disclosed(value, instruction):
                source = PublicValueRef.task_literal(value)
            if source is None:
                raise CandidateMaterializationFailure(
                    "DraftRejected",
                    "argument_source_unresolved",
                    "reference solution uses a value unavailable to the public Agent",
                    step=event.seq,
                    argument_pointer=pointer,
                )
            origins.append(ArgumentOrigin(event.seq, pointer, source))
        visible.extend(
            (PublicValueRef.observation(event.seq, pointer), value)
            for pointer, value in _leaves(event.observation)
        )
    return tuple(origins)


def _resolve_arguments(
    original: JSONObject,
    *,
    step: int,
    origins: dict[tuple[int, str], PublicValueRef],
    reset: JSONValue,
    trace: tuple[TraceEvent, ...],
) -> JSONObject:
    result = _copy_object(original)
    events = {event.seq: event for event in trace}
    for pointer, _ in _leaves(original):
        source = origins[(step, pointer)]
        if source.kind == "task_literal":
            value = source.value
        elif source.kind == "reset":
            value = _at(reset, cast(str, source.pointer))
        else:
            event = events.get(cast(int, source.step))
            if event is None:
                raise CandidateMaterializationFailure(
                    "FrameworkDefect",
                    "argument_source_order_invalid",
                    "argument source does not precede its consumer",
                )
            value = _at(event.observation, cast(str, source.pointer))
        _set(result, pointer, value)
    return result


def _materialize_goal(
    draft: DraftGoal,
    events: dict[int, TraceEvent],
    mutations: dict[int, bool],
) -> Goal:
    if isinstance(draft, AtomDraft):
        event = events[draft.step]
        if event.observation["ok"] is False:
            error = cast(JSONObject, event.observation["error"])
            return AtomGoal(event.tool_name, event.arguments, "refusal", cast(str, error["code"]))
        outcome: Literal["query", "transition"] = "transition" if mutations[draft.step] else "query"
        return AtomGoal(event.tool_name, event.arguments, outcome)
    if isinstance(draft, AllDraft):
        return AllGoal(
            tuple(_materialize_goal(child, events, mutations) for child in draft.children)
        )
    if isinstance(draft, IfDraft):
        return IfGoal(
            ScalarCondition(
                _goal_source(draft.condition, events),
                draft.operator,
                draft.value,
            ),
            _materialize_goal(draft.then_goal, events, mutations)
            if draft.then_goal is not None
            else None,
            _materialize_goal(draft.else_goal, events, mutations)
            if draft.else_goal is not None
            else None,
        )
    return ForEachGoal(
        _goal_source(draft.members, events),
        draft.member_key_pointer,
        draft.member_argument_pointer,
        tuple(
            cast(AtomGoal, _materialize_goal(child, events, mutations)) for child in draft.children
        ),
    )


def _goal_source(source: PublicValueRef, events: dict[int, TraceEvent]) -> GoalValueSource:
    if source.kind == "reset":
        return GoalValueSource.reset(cast(str, source.pointer))
    if source.kind != "observation":
        raise ValueError("Goal condition/member source cannot be a Task literal")
    event = events[cast(int, source.step)]
    return GoalValueSource.observation(event.tool_name, event.arguments, cast(str, source.pointer))


def _structure_id(truth: GoalTruth) -> str:
    changes = json_leaf_changes(truth.expected_before, truth.expected_after)
    paths = sorted({_path_shape(cast(str, item["path"])) for item in changes})
    document: JSONObject = {
        "format": "task-structure/3",
        "goal": _goal_structure(truth.goal),
        "state_paths": cast(JSONValue, paths),
        "answer_schema": truth.final_answer_schema,
    }
    return _document_digest(document)


def _goal_structure(goal: Goal) -> JSONObject:
    if isinstance(goal, AtomGoal):
        return {
            "kind": "atom",
            "tool": goal.tool_name,
            "outcome": goal.outcome,
            "argument_shape": _value_shape(goal.arguments),
            "error_code": goal.error_code,
        }
    if isinstance(goal, AllGoal):
        return {"kind": "all", "children": [_goal_structure(child) for child in goal.children]}
    if isinstance(goal, IfGoal):
        return {
            "kind": "if",
            "condition": {
                "kind": goal.condition.source.kind,
                "pointer": _path_shape(goal.condition.source.pointer),
                "operator": goal.condition.operator,
                "value_type": _value_shape(goal.condition.value),
            },
            "then": _goal_structure(goal.then_goal) if goal.then_goal else None,
            "else": _goal_structure(goal.else_goal) if goal.else_goal else None,
        }
    return {
        "kind": "foreach",
        "member_key_pointer": _path_shape(goal.member_key_pointer),
        "member_argument_pointer": _path_shape(goal.member_argument_pointer),
        "children": [_goal_structure(child) for child in goal.children],
    }


def _value_shape(value: JSONValue) -> JSONValue:
    if isinstance(value, dict):
        return {key: _value_shape(child) for key, child in value.items()}
    if isinstance(value, list):
        return [_value_shape(value[0])] if value else []
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    return "string"


def _leaves(value: JSONValue, pointer: str = "") -> list[tuple[str, JSONValue]]:
    if isinstance(value, dict):
        return [
            item
            for key, child in value.items()
            for item in _leaves(child, f"{pointer}/{_escape(key)}")
        ]
    if isinstance(value, list):
        return [
            item
            for index, child in enumerate(value)
            for item in _leaves(child, f"{pointer}/{index}")
        ]
    return [(pointer or "/", value)]


def _literal_disclosed(value: JSONValue, instruction: str) -> bool:
    if isinstance(value, (dict, list)):
        return False
    if value is None:
        return "null" in instruction.casefold()
    if isinstance(value, bool):
        return str(value).casefold() in instruction.casefold()
    token = str(value)
    if isinstance(value, (int, float)):
        return re.search(rf"(?<![\w.]){re.escape(token)}(?![\w.])", instruction) is not None
    return token in instruction


def _at(document: JSONValue, pointer: str) -> JSONValue:
    current = document
    for token in _tokens(pointer):
        if isinstance(current, dict):
            current = current[token]
        elif isinstance(current, list):
            current = current[int(token)]
        else:
            raise ValueError("JSON pointer traverses a scalar")
    return _copy_json(current)


def _set(document: JSONObject, pointer: str, value: JSONValue) -> None:
    tokens = _tokens(pointer)
    current: JSONValue = document
    for token in tokens[:-1]:
        current = (
            current[int(token)] if isinstance(current, list) else cast(JSONObject, current)[token]
        )
    last = tokens[-1]
    if isinstance(current, list):
        current[int(last)] = _copy_json(value)
    else:
        cast(JSONObject, current)[last] = _copy_json(value)


def _tokens(pointer: str) -> tuple[str, ...]:
    if not pointer.startswith("/"):
        raise ValueError("JSON pointer must start with /")
    return tuple(token.replace("~1", "/").replace("~0", "~") for token in pointer[1:].split("/"))


def _escape(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _path_shape(value: str) -> str:
    return "/".join("*" if token.isdecimal() else token for token in value.split("/"))


def _counter(values: list[JSONValue]) -> dict[bytes, int]:
    result: dict[bytes, int] = {}
    for value in values:
        key = canonical_bytes(value)
        result[key] = result.get(key, 0) + 1
    return result


def _value_ref_from_document(document: Any) -> PublicValueRef:
    value = _exact(document, set(document) if isinstance(document, dict) else set(), "source")
    kind = value.get("kind")
    if kind == "task_literal" and set(value) == {"kind", "value"}:
        return PublicValueRef.task_literal(value["value"])
    if kind == "reset" and set(value) == {"kind", "pointer"}:
        return PublicValueRef.reset(cast(str, value["pointer"]))
    if kind == "observation" and set(value) == {"kind", "step", "pointer"}:
        return PublicValueRef.observation(cast(int, value["step"]), cast(str, value["pointer"]))
    raise ValueError("ArgumentOrigin source has invalid fields")


def argument_origin_from_document(document: Any) -> ArgumentOrigin:
    value = _exact(document, {"step", "argument_pointer", "source"}, "ArgumentOrigin")
    return ArgumentOrigin(
        cast(int, value["step"]),
        cast(str, value["argument_pointer"]),
        _value_ref_from_document(value["source"]),
    )


def _exact(document: Any, keys: set[str], role: str) -> JSONObject:
    if not is_json_object(document) or set(document) != keys:
        actual = sorted(document) if isinstance(document, dict) else type(document).__name__
        raise ValueError(f"{role} has invalid fields: expected {sorted(keys)}, got {actual}")
    return cast(JSONObject, document)


def _digest(value: str, role: str) -> None:
    try:
        _hex_digest(value, field=role)
    except Exception as exc:
        raise ValueError(str(exc)) from exc


def _same(left: JSONValue, right: JSONValue) -> bool:
    return canonical_bytes(left) == canonical_bytes(right)


def _document_digest(document: JSONObject) -> str:
    return sha256_hex(canonical_bytes(document))


def _copy_json(value: JSONValue) -> JSONValue:
    return cast(JSONValue, json.loads(json.dumps(value, ensure_ascii=False)))


def _copy_object(value: JSONObject) -> JSONObject:
    return cast(JSONObject, _copy_json(value))


__all__ = [
    "CANDIDATE_TASK_FORMAT",
    "REFERENCE_REPLAY_FORMAT",
    "ArgumentOrigin",
    "CandidateMaterializationFailure",
    "CandidateTask",
    "MaterializedCandidate",
    "ReferenceReplay",
    "argument_origin_from_document",
    "candidate_task_from_document",
    "derive_argument_origins",
    "materialize_candidate",
]
