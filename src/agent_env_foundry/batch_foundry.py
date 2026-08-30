"""Deterministic multi-Task compilation, admission, and artifact persistence."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol, cast

from agent_env_foundry.agents import AgentRoute
from agent_env_foundry.environment import JSONObject
from agent_env_foundry.foreach_foundry import (
    ForEachTask,
    challenge_foreach_partials,
    challenge_foreach_wrong_answer,
    challenge_foreach_wrong_target,
    compile_foreach_tasks,
    run_foreach_noop,
    seal_foreach_task_pack,
    solve_foreach_task_twice,
)
from agent_env_foundry.if_foundry import (
    IfTask,
    compile_if_tasks,
    seal_if_task_pack,
    solve_if_task_twice,
)
from agent_env_foundry.jsonvalue import is_json_object
from agent_env_foundry.preparation import OpenPreparedRelease, PreparationExecutionError
from agent_env_foundry.public_agent import PublicAgentFailure
from agent_env_foundry.release import canonical_bytes
from agent_env_foundry.task_foundry import (
    AtomTask,
    AtomTaskPack,
    TaskFoundryError,
    admit_atom_task,
    compile_atom_tasks,
)

GoalKind = Literal["atom", "foreach", "if"]
FailureKind = Literal[
    "NoPublicWitness",
    "ChallengePolicyFailure",
    "RejectedTaskPack",
]
type CandidateTask = AtomTask | ForEachTask | IfTask
_GOAL_ORDER: tuple[GoalKind, ...] = ("atom", "foreach", "if")
_HEX = frozenset("0123456789abcdef")
_RETRYABLE_TASK_CODES = frozenset(
    {
        "public_witness_failed",
        "foreach_public_witness_failed",
        "if_public_witness_failed",
        "challenge_baseline_failed",
        "wrong_target_baseline_failed",
        "foreach_partial_not_discriminated",
        "foreach_wrong_target_baseline_failed",
        "foreach_wrong_answer_baseline_failed",
    }
)


class _Pack(Protocol):
    @property
    def task_pack_id(self) -> str: ...

    def to_document(self) -> JSONObject: ...


@dataclass(frozen=True, slots=True)
class _Candidate:
    kind: GoalKind
    task: CandidateTask
    structure_id: str

    @property
    def task_id(self) -> str:
        return self.task.task_id


@dataclass(frozen=True, slots=True)
class _CandidateGroup:
    kind: GoalKind
    structure_id: str
    structure: JSONObject
    candidates: tuple[_Candidate, ...]


@dataclass(frozen=True, slots=True)
class AdmittedTaskRecord:
    kind: GoalKind
    task_id: str
    structure_id: str
    task_pack_id: str
    artifact_path: str

    def to_document(self) -> JSONObject:
        return {
            "kind": self.kind,
            "task_id": self.task_id,
            "structure_id": self.structure_id,
            "task_pack_id": self.task_pack_id,
            "artifact_path": self.artifact_path,
        }


@dataclass(frozen=True, slots=True)
class RejectedTaskRecord:
    kind: GoalKind
    task_id: str
    structure_id: str
    attempt_index: int
    failure_kind: FailureKind
    code: str
    message: str
    details: JSONObject

    def __post_init__(self) -> None:
        if self.attempt_index <= 0:
            raise ValueError("attempt_index must be positive")

    def to_document(self) -> JSONObject:
        return {
            "kind": self.kind,
            "task_id": self.task_id,
            "structure_id": self.structure_id,
            "attempt_index": self.attempt_index,
            "failure_kind": self.failure_kind,
            "code": self.code,
            "message": self.message,
            "details": _object(self.details),
        }


@dataclass(frozen=True, slots=True)
class TaskBatchReport:
    release_id: str
    target_structures: int
    candidate_attempt_limit: int
    candidate_count: int
    structure_count: int
    admitted: tuple[AdmittedTaskRecord, ...]
    dependencies: tuple[AdmittedTaskRecord, ...]
    rejected: tuple[RejectedTaskRecord, ...]

    def __post_init__(self) -> None:
        if self.candidate_attempt_limit <= 0:
            raise ValueError("candidate_attempt_limit must be positive")
        structure_ids = tuple(item.structure_id for item in self.admitted)
        if len(structure_ids) != len(set(structure_ids)):
            raise TaskFoundryError(
                "batch_duplicate_structure_admission",
                "A Task batch admitted the same structure more than once",
            )
        if any(item.attempt_index > self.candidate_attempt_limit for item in self.rejected):
            raise TaskFoundryError(
                "batch_attempt_evidence_out_of_range",
                "A rejected Task attempt exceeds the frozen batch attempt limit",
            )

    @property
    def target_reached(self) -> bool:
        return len(self.admitted) >= self.target_structures

    @property
    def run_id(self) -> str:
        return hashlib.sha256(canonical_bytes(self._preimage())).hexdigest()

    def _preimage(self) -> JSONObject:
        return {
            "format": "task-foundry-batch/2",
            "release_id": self.release_id,
            "target_structures": self.target_structures,
            "candidate_attempt_limit": self.candidate_attempt_limit,
            "candidate_count": self.candidate_count,
            "structure_count": self.structure_count,
            "target_reached": self.target_reached,
            "admitted": [item.to_document() for item in self.admitted],
            "dependencies": [item.to_document() for item in self.dependencies],
            "rejected": [item.to_document() for item in self.rejected],
        }

    def to_document(self) -> JSONObject:
        return {**self._preimage(), "run_id": self.run_id}


def task_structure_id(kind: GoalKind, task: CandidateTask) -> str:
    return hashlib.sha256(canonical_bytes(_structure_document(kind, task))).hexdigest()


def run_task_foundry_batch(
    prepared: OpenPreparedRelease,
    work_root: Path,
    output_root: Path,
    *,
    target_structures: int,
    route: AgentRoute | None = None,
    max_provider_turns: int = 12,
    candidate_attempt_limit: int = 3,
    event_sink: Callable[[JSONObject], None] | None = None,
) -> TaskBatchReport:
    if target_structures <= 0:
        raise ValueError("target_structures must be positive")
    if max_provider_turns <= 0:
        raise ValueError("max_provider_turns must be positive")
    if candidate_attempt_limit <= 0:
        raise ValueError("candidate_attempt_limit must be positive")
    work = Path(work_root)
    output = Path(output_root)
    work.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=True, exist_ok=True)
    candidates, atom_tasks = _compile_candidates(prepared, work / "compile")
    groups = _balanced_groups(_group_candidates(candidates))
    admitted: list[AdmittedTaskRecord] = []
    rejected: list[RejectedTaskRecord] = []
    atom_cache: dict[str, AtomTaskPack] = {}
    dependencies: dict[str, AdmittedTaskRecord] = {}
    for group in groups:
        if len(admitted) >= target_structures:
            break
        for candidate in group.candidates:
            candidate_admitted = False
            for attempt_index in range(1, candidate_attempt_limit + 1):
                _emit(
                    event_sink,
                    "candidate_started",
                    candidate,
                    admitted_count=len(admitted),
                    attempt_index=attempt_index,
                )
                try:
                    pack = _admit_candidate(
                        prepared,
                        candidate,
                        atom_tasks,
                        work
                        / "admission"
                        / candidate.kind
                        / candidate.task_id
                        / f"attempt-{attempt_index}",
                        output,
                        route,
                        max_provider_turns,
                        atom_cache,
                        dependencies,
                    )
                except PublicAgentFailure as exc:
                    if exc.kind == "InfrastructureFailure":
                        raise
                    record = _rejection(
                        candidate,
                        attempt_index,
                        "NoPublicWitness",
                        exc.code,
                        str(exc),
                        exc.details,
                    )
                    rejected.append(record)
                    _emit(
                        event_sink,
                        "candidate_rejected",
                        candidate,
                        rejection=record.to_document(),
                    )
                    continue
                except PreparationExecutionError:
                    raise
                except TaskFoundryError as exc:
                    failure_kind = _task_failure_kind(exc.code)
                    record = _rejection(
                        candidate,
                        attempt_index,
                        failure_kind,
                        exc.code,
                        str(exc),
                        exc.details,
                    )
                    rejected.append(record)
                    _emit(
                        event_sink,
                        "candidate_rejected",
                        candidate,
                        rejection=record.to_document(),
                    )
                    if exc.code in _RETRYABLE_TASK_CODES:
                        continue
                    break
                artifact = _persist_pack(output, candidate.kind, pack)
                admitted.append(
                    AdmittedTaskRecord(
                        candidate.kind,
                        candidate.task_id,
                        candidate.structure_id,
                        pack.task_pack_id,
                        artifact,
                    )
                )
                _emit(
                    event_sink,
                    "candidate_admitted",
                    candidate,
                    task_pack_id=pack.task_pack_id,
                    admitted_count=len(admitted),
                    attempt_index=attempt_index,
                )
                candidate_admitted = True
                break
            if candidate_admitted:
                break
    report = TaskBatchReport(
        prepared.identity.release_id,
        target_structures,
        candidate_attempt_limit,
        len(candidates),
        len(groups),
        tuple(admitted),
        tuple(sorted(dependencies.values(), key=lambda item: item.task_id)),
        tuple(rejected),
    )
    _persist_report(output, report)
    return report


def _candidate(kind: GoalKind, task: CandidateTask) -> _Candidate:
    return _Candidate(kind, task, task_structure_id(kind, task))


def _compile_candidates(
    prepared: OpenPreparedRelease,
    root: Path,
) -> tuple[tuple[_Candidate, ...], tuple[AtomTask, ...]]:
    atom_tasks = compile_atom_tasks(prepared, root / "atom")
    foreach_tasks = compile_foreach_tasks(prepared, atom_tasks, root / "foreach")
    if_tasks = compile_if_tasks(prepared, atom_tasks, root / "if")
    candidates = (
        *(_candidate("atom", task) for task in atom_tasks),
        *(_candidate("foreach", task) for task in foreach_tasks),
        *(_candidate("if", task) for task in if_tasks),
    )
    return tuple(candidates), atom_tasks


def _group_candidates(candidates: tuple[_Candidate, ...]) -> tuple[_CandidateGroup, ...]:
    grouped: dict[str, list[_Candidate]] = {}
    structures: dict[str, JSONObject] = {}
    for candidate in candidates:
        structure = _structure_document(candidate.kind, candidate.task)
        previous = structures.setdefault(candidate.structure_id, structure)
        if previous != structure:
            raise TaskFoundryError(
                "task_structure_hash_collision",
                "Different Task structures produced the same structure digest",
            )
        grouped.setdefault(candidate.structure_id, []).append(candidate)
    return tuple(
        _CandidateGroup(
            items[0].kind,
            structure_id,
            structures[structure_id],
            tuple(sorted(items, key=lambda item: item.task_id)),
        )
        for structure_id, items in grouped.items()
    )


def _balanced_groups(groups: tuple[_CandidateGroup, ...]) -> tuple[_CandidateGroup, ...]:
    buckets = {
        kind: sorted(
            (group for group in groups if group.kind == kind),
            key=lambda group: (canonical_bytes(group.structure), group.structure_id),
        )
        for kind in _GOAL_ORDER
    }
    ordered: list[_CandidateGroup] = []
    index = 0
    while any(index < len(buckets[kind]) for kind in _GOAL_ORDER):
        for kind in _GOAL_ORDER:
            if index < len(buckets[kind]):
                ordered.append(buckets[kind][index])
        index += 1
    return tuple(ordered)


def _admit_candidate(
    prepared: OpenPreparedRelease,
    candidate: _Candidate,
    atom_tasks: tuple[AtomTask, ...],
    root: Path,
    output_root: Path,
    route: AgentRoute | None,
    max_provider_turns: int,
    atom_cache: dict[str, AtomTaskPack],
    dependencies: dict[str, AdmittedTaskRecord],
) -> _Pack:
    if candidate.kind == "atom":
        atom_task = cast(AtomTask, candidate.task)
        cached = atom_cache.get(atom_task.task_id)
        if cached is not None:
            return cached
        pack = admit_atom_task(
            prepared,
            atom_task,
            atom_tasks,
            root,
            route=route,
            max_provider_turns=max_provider_turns,
        )
        atom_cache[atom_task.task_id] = pack
        return pack
    if candidate.kind == "foreach":
        foreach_task = cast(ForEachTask, candidate.task)
        solved_foreach = solve_foreach_task_twice(
            prepared,
            foreach_task,
            atom_tasks,
            root / "solve",
            route=route,
            max_provider_turns=max_provider_turns,
        )
        noop = run_foreach_noop(prepared, solved_foreach, root / "noop")
        partials = challenge_foreach_partials(
            prepared,
            solved_foreach,
            root / "partials",
            route=route,
            max_provider_turns=max_provider_turns,
        )
        wrong_target = challenge_foreach_wrong_target(
            prepared,
            solved_foreach,
            atom_tasks,
            root / "wrong-target",
            route=route,
            max_provider_turns=max_provider_turns,
        )
        wrong_answer = challenge_foreach_wrong_answer(
            prepared,
            solved_foreach,
            root / "wrong-answer",
            route=route,
            max_provider_turns=max_provider_turns,
        )
        return seal_foreach_task_pack(
            solved_foreach,
            noop,
            partials,
            wrong_target,
            wrong_answer,
        )
    if_task = cast(IfTask, candidate.task)
    matching = [item for item in atom_tasks if item.task_id == if_task.branch_task_id]
    if len(matching) != 1:
        raise TaskFoundryError(
            "if_batch_branch_task_missing",
            "If batch candidate has no unique frozen Atom branch",
            branch_task_id=if_task.branch_task_id,
        )
    branch = matching[0]
    branch_pack = atom_cache.get(branch.task_id)
    if branch_pack is None:
        branch_pack = admit_atom_task(
            prepared,
            branch,
            atom_tasks,
            root / "branch-admission",
            route=route,
            max_provider_turns=max_provider_turns,
        )
        atom_cache[branch.task_id] = branch_pack
    dependency_artifact = _persist_pack(output_root, "atom", branch_pack)
    dependencies.setdefault(
        branch.task_id,
        AdmittedTaskRecord(
            "atom",
            branch.task_id,
            task_structure_id("atom", branch),
            branch_pack.task_pack_id,
            dependency_artifact,
        ),
    )
    solved_if = solve_if_task_twice(
        prepared,
        if_task,
        atom_tasks,
        root / "solve",
        route=route,
        max_provider_turns=max_provider_turns,
    )
    return seal_if_task_pack(solved_if, branch_pack)


def _structure_document(kind: GoalKind, task: CandidateTask) -> JSONObject:
    if kind == "atom" and isinstance(task, AtomTask):
        return {
            "format": "task-structure/1",
            "goal_kind": "atom",
            "capability_id": task.capability_id,
            "regime_tags": list(task.start_case.regime_tags),
            "answer_schema": _object(task.answer_schema),
        }
    if kind == "foreach" and isinstance(task, ForEachTask):
        return {
            "format": "task-structure/1",
            "goal_kind": "foreach",
            "capability_id": task.capability_id,
            "selector": "all",
            "member_count": len(task.semantic_keys),
            "regime_tags": list(task.start_case.regime_tags),
            "answer_schema": _object(task.member_answer_schema),
        }
    if kind == "if" and isinstance(task, IfTask):
        return {
            "format": "task-structure/1",
            "goal_kind": "if",
            "condition_id": task.condition_id,
            "expected_branch": task.expected_branch,
            "true_capability_id": task.true_capability_id,
            "false_capability_id": task.false_capability_id,
            "regime_tags": list(task.start_case.regime_tags),
            "answer_schema": _object(task.answer_schema),
        }
    raise TypeError("Task kind and Task value do not match")


def _persist_pack(output_root: Path, kind: GoalKind, pack: _Pack) -> str:
    names = {
        "atom": "AtomTaskPack.json",
        "foreach": "ForEachTaskPack.json",
        "if": "IfTaskPack.json",
    }
    relative = Path("taskpacks") / pack.task_pack_id / names[kind]
    path = output_root / relative
    document = _object(pack.to_document())
    _validate_task_pack_document(document, pack.task_pack_id)
    payload = canonical_bytes(document)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_bytes() != payload:
        raise TaskFoundryError(
            "task_pack_artifact_collision",
            "Existing TaskPack artifact bytes differ from the same identity",
            task_pack_id=pack.task_pack_id,
        )
    path.write_bytes(payload)
    verify_task_pack_artifact(path, pack.task_pack_id)
    return relative.as_posix()


def verify_task_pack_artifact(path: Path, task_pack_id: str) -> None:
    """Cold-read canonical TaskPack bytes and recompute their claimed identity."""

    _task_pack_digest(task_pack_id)
    try:
        payload = Path(path).read_bytes()
        document = json.loads(payload)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise TaskFoundryError(
            "task_pack_artifact_unreadable",
            "TaskPack artifact is unreadable",
            task_pack_id=task_pack_id,
        ) from exc
    if not is_json_object(document) or payload != canonical_bytes(document):
        raise TaskFoundryError(
            "task_pack_artifact_not_canonical",
            "TaskPack artifact is not canonical JSON",
            task_pack_id=task_pack_id,
        )
    _validate_task_pack_document(cast(JSONObject, document), task_pack_id)


def _validate_task_pack_document(document: JSONObject, task_pack_id: str) -> None:
    _task_pack_digest(task_pack_id)
    if document.get("task_pack_id") != task_pack_id:
        raise TaskFoundryError(
            "task_pack_artifact_identity_mismatch",
            "TaskPack artifact identity differs from its batch record",
            task_pack_id=task_pack_id,
        )
    preimage = dict(document)
    preimage.pop("task_pack_id")
    actual = hashlib.sha256(canonical_bytes(preimage)).hexdigest()
    if actual != task_pack_id:
        raise TaskFoundryError(
            "task_pack_artifact_preimage_mismatch",
            "TaskPack artifact preimage differs from its identity",
            task_pack_id=task_pack_id,
            actual_task_pack_id=actual,
        )


def _task_pack_digest(value: str) -> None:
    if len(value) != 64 or any(character not in _HEX for character in value):
        raise TaskFoundryError(
            "task_pack_artifact_identity_invalid",
            "TaskPack artifact identity must be a sha256 digest",
            task_pack_id=value,
        )


def _persist_report(output_root: Path, report: TaskBatchReport) -> None:
    path = output_root / "runs" / f"{report.run_id}.json"
    payload = canonical_bytes(report.to_document())
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_bytes() != payload:
        raise TaskFoundryError(
            "task_batch_report_collision",
            "Existing Task batch report bytes differ from the same run identity",
            run_id=report.run_id,
        )
    path.write_bytes(payload)


def _rejection(
    candidate: _Candidate,
    attempt_index: int,
    failure_kind: FailureKind,
    code: str,
    message: str,
    details: Any,
) -> RejectedTaskRecord:
    return RejectedTaskRecord(
        candidate.kind,
        candidate.task_id,
        candidate.structure_id,
        attempt_index,
        failure_kind,
        code,
        message,
        _safe_details(details),
    )


def _task_failure_kind(code: str) -> FailureKind:
    if code in {
        "public_witness_failed",
        "foreach_public_witness_failed",
        "if_public_witness_failed",
    }:
        return "NoPublicWitness"
    if code in {
        "challenge_baseline_failed",
        "wrong_target_baseline_failed",
        "foreach_partial_not_discriminated",
        "foreach_wrong_target_baseline_failed",
        "foreach_wrong_answer_baseline_failed",
    }:
        return "ChallengePolicyFailure"
    return "RejectedTaskPack"


def _safe_details(details: Any) -> JSONObject:
    if is_json_object(details):
        return cast(JSONObject, json.loads(json.dumps(details, ensure_ascii=False)))
    return {"unserializable_details": str(details)}


def _emit(
    sink: Callable[[JSONObject], None] | None,
    event: str,
    candidate: _Candidate,
    **payload: Any,
) -> None:
    if sink is None:
        return
    document: JSONObject = {
        "event": event,
        "kind": candidate.kind,
        "task_id": candidate.task_id,
        "structure_id": candidate.structure_id,
    }
    for key, value in payload.items():
        json_value = json.loads(json.dumps(value, ensure_ascii=False))
        document[key] = cast(Any, json_value)
    sink(document)


def _object(value: Any) -> JSONObject:
    if not is_json_object(value):
        raise TypeError("expected a JSON object")
    return cast(JSONObject, json.loads(json.dumps(value, ensure_ascii=False)))


__all__ = [
    "AdmittedTaskRecord",
    "RejectedTaskRecord",
    "TaskBatchReport",
    "run_task_foundry_batch",
    "task_structure_id",
    "verify_task_pack_artifact",
]
