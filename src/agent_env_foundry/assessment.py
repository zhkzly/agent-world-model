"""Model-relative Task assessment and deterministic corpus selection."""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

from agent_env_foundry.agents import AgentRoute
from agent_env_foundry.batch_foundry import (
    TaskBatchReport,
    _compile_candidates,
    run_task_foundry_batch,
    verify_task_pack_artifact,
)
from agent_env_foundry.environment import JSONObject
from agent_env_foundry.foreach_foundry import (
    ForEachTask,
    ForEachWitness,
    run_foreach_task_once,
)
from agent_env_foundry.if_foundry import IfTask, IfWitness, run_if_task_once
from agent_env_foundry.jsonvalue import is_json_object
from agent_env_foundry.preparation import OpenPreparedRelease
from agent_env_foundry.public_agent import (
    PUBLIC_AGENT_PROMPT_DIGEST,
    PublicAgentFailure,
)
from agent_env_foundry.release import canonical_bytes
from agent_env_foundry.task_foundry import (
    AtomTask,
    AtomWitness,
    run_atom_task_once,
)

AssessmentGoalKind = Literal["atom", "foreach", "if"]
AssessmentStatus = Literal["satisfied", "failed"]
CorpusPurpose = Literal["sft", "rl", "evaluation"]
type AssessmentTask = AtomTask | ForEachTask | IfTask
type AssessmentWitness = AtomWitness | ForEachWitness | IfWitness

_GOAL_KINDS = frozenset({"atom", "foreach", "if"})
_PURPOSES = frozenset({"sft", "rl", "evaluation"})
_HEX = frozenset("0123456789abcdef")


class AssessmentError(ValueError):
    """Assessment or corpus evidence violates its deterministic contract."""


@dataclass(frozen=True, slots=True)
class AssessmentPolicy:
    model_id: str
    route_digest: str
    public_agent_prompt_digest: str
    max_provider_turns: int
    trial_count: int

    def __post_init__(self) -> None:
        _text(self.model_id, "assessment model_id")
        _digest(self.route_digest, "assessment route_digest")
        _digest(self.public_agent_prompt_digest, "assessment prompt digest")
        _positive(self.max_provider_turns, "assessment max_provider_turns")
        _positive(self.trial_count, "assessment trial_count")

    @classmethod
    def from_route(cls, route: AgentRoute, *, trial_count: int) -> AssessmentPolicy:
        route_document = {"base_url": route.base_url, "model": route.model}
        return cls(
            route.model,
            hashlib.sha256(canonical_bytes(route_document)).hexdigest(),
            PUBLIC_AGENT_PROMPT_DIGEST,
            route.max_provider_turns,
            trial_count,
        )

    @property
    def policy_id(self) -> str:
        return _document_digest(self.to_document())

    def to_document(self) -> JSONObject:
        return {
            "format": "task-assessment-policy/1",
            "model_id": self.model_id,
            "route_digest": self.route_digest,
            "public_agent_prompt_digest": self.public_agent_prompt_digest,
            "max_provider_turns": self.max_provider_turns,
            "trial_count": self.trial_count,
        }


@dataclass(frozen=True, slots=True)
class AssessmentRun:
    trial_index: int
    status: AssessmentStatus
    materialization_id: str | None
    evidence: JSONObject
    provider_turns: int
    input_tokens: int
    output_tokens: int
    latency_ms: int
    failure_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        _positive(self.trial_index, "assessment trial_index")
        if self.status not in {"satisfied", "failed"}:
            raise AssessmentError("assessment run status is invalid")
        if self.materialization_id is not None:
            _digest(self.materialization_id, "assessment materialization_id")
        if not is_json_object(self.evidence):
            raise AssessmentError("assessment run evidence must be an object")
        for value, role in (
            (self.provider_turns, "provider_turns"),
            (self.input_tokens, "input_tokens"),
            (self.output_tokens, "output_tokens"),
            (self.latency_ms, "latency_ms"),
        ):
            _nonnegative(value, f"assessment {role}")
        _unique_text(self.failure_codes, "assessment failure codes")
        if self.status == "satisfied" and (self.materialization_id is None or self.failure_codes):
            raise AssessmentError(
                "satisfied assessment run requires a materialization and no failures"
            )
        if self.status == "failed" and not self.failure_codes:
            raise AssessmentError("failed assessment run requires failure codes")

    @property
    def run_id(self) -> str:
        return _document_digest(self._preimage())

    def _preimage(self) -> JSONObject:
        return {
            "format": "task-assessment-run/1",
            "trial_index": self.trial_index,
            "status": self.status,
            "materialization_id": self.materialization_id,
            "evidence": _object(self.evidence),
            "provider_turns": self.provider_turns,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "latency_ms": self.latency_ms,
            "failure_codes": list(self.failure_codes),
        }

    def to_document(self) -> JSONObject:
        return {**self._preimage(), "run_id": self.run_id}


@dataclass(frozen=True, slots=True)
class TaskAssessment:
    task_pack_id: str
    release_id: str
    goal_kind: AssessmentGoalKind
    policy: AssessmentPolicy
    runs: tuple[AssessmentRun, ...]

    def __post_init__(self) -> None:
        _digest(self.task_pack_id, "assessment task_pack_id")
        _digest(self.release_id, "assessment release_id")
        if self.goal_kind not in _GOAL_KINDS:
            raise AssessmentError("assessment goal_kind is invalid")
        expected = tuple(range(1, self.policy.trial_count + 1))
        if tuple(item.trial_index for item in self.runs) != expected:
            raise AssessmentError("assessment runs must cover the exact ordered trial set")
        if len({item.run_id for item in self.runs}) != len(self.runs):
            raise AssessmentError("assessment run identities must be unique")

    @property
    def reliability(self) -> float:
        return sum(item.status == "satisfied" for item in self.runs) / len(self.runs)

    @property
    def provider_turns(self) -> int:
        return sum(item.provider_turns for item in self.runs)

    @property
    def input_tokens(self) -> int:
        return sum(item.input_tokens for item in self.runs)

    @property
    def output_tokens(self) -> int:
        return sum(item.output_tokens for item in self.runs)

    @property
    def latency_ms(self) -> int:
        return sum(item.latency_ms for item in self.runs)

    @property
    def failure_codes(self) -> tuple[str, ...]:
        return tuple(sorted({code for item in self.runs for code in item.failure_codes}))

    @property
    def difficulty(self) -> JSONObject:
        count = len(self.runs)
        return {
            "failure_rate": 1.0 - self.reliability,
            "mean_provider_turns": self.provider_turns / count,
            "mean_tokens": (self.input_tokens + self.output_tokens) / count,
        }

    @property
    def assessment_id(self) -> str:
        return _document_digest(self._preimage())

    def _preimage(self) -> JSONObject:
        return {
            "format": "task-assessment/1",
            "task_pack_id": self.task_pack_id,
            "release_id": self.release_id,
            "goal_kind": self.goal_kind,
            "policy": self.policy.to_document(),
            "runs": [item.to_document() for item in self.runs],
            "reliability": self.reliability,
            "provider_turns": self.provider_turns,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "latency_ms": self.latency_ms,
            "failure_codes": list(self.failure_codes),
            "difficulty": self.difficulty,
        }

    def to_document(self) -> JSONObject:
        return {**self._preimage(), "assessment_id": self.assessment_id}


@dataclass(frozen=True, slots=True)
class CorpusPolicy:
    purpose: CorpusPurpose
    minimum_reliability: float
    max_tasks: int | None

    def __post_init__(self) -> None:
        if self.purpose not in _PURPOSES:
            raise AssessmentError("corpus purpose is invalid")
        if not 0.0 <= self.minimum_reliability <= 1.0:
            raise AssessmentError("corpus minimum_reliability must be between zero and one")
        if self.max_tasks is not None:
            _positive(self.max_tasks, "corpus max_tasks")

    @property
    def policy_id(self) -> str:
        return _document_digest(self.to_document())

    def to_document(self) -> JSONObject:
        return {
            "format": "corpus-policy/1",
            "purpose": self.purpose,
            "minimum_reliability": self.minimum_reliability,
            "max_tasks": self.max_tasks,
        }


@dataclass(frozen=True, slots=True)
class CorpusSelectionCandidate:
    task_pack_id: str
    assessment_id: str
    release_id: str
    goal_kind: AssessmentGoalKind
    structure_id: str
    reliability: float

    def __post_init__(self) -> None:
        for value, role in (
            (self.task_pack_id, "corpus task_pack_id"),
            (self.assessment_id, "corpus assessment_id"),
            (self.release_id, "corpus release_id"),
            (self.structure_id, "corpus structure_id"),
        ):
            _digest(value, role)
        if self.goal_kind not in _GOAL_KINDS:
            raise AssessmentError("corpus goal_kind is invalid")
        if not 0.0 <= self.reliability <= 1.0:
            raise AssessmentError("corpus reliability must be between zero and one")

    def to_document(self) -> JSONObject:
        return {
            "task_pack_id": self.task_pack_id,
            "assessment_id": self.assessment_id,
            "release_id": self.release_id,
            "goal_kind": self.goal_kind,
            "structure_id": self.structure_id,
            "reliability": self.reliability,
        }


@dataclass(frozen=True, slots=True)
class CorpusManifest:
    policy: CorpusPolicy
    seed: int
    entries: tuple[CorpusSelectionCandidate, ...]
    selection_evidence_digest: str

    def __post_init__(self) -> None:
        if isinstance(self.seed, bool) or not isinstance(self.seed, int):
            raise AssessmentError("corpus seed must be an integer")
        if not self.entries:
            raise AssessmentError("CorpusManifest must select at least one TaskPack")
        _digest(self.selection_evidence_digest, "corpus selection evidence digest")
        _unique_text(
            tuple(item.task_pack_id for item in self.entries),
            "corpus task_pack IDs",
        )
        _unique_text(
            tuple(item.assessment_id for item in self.entries),
            "corpus assessment IDs",
        )
        structures = tuple((item.release_id, item.structure_id) for item in self.entries)
        if len(structures) != len(set(structures)):
            raise AssessmentError("CorpusManifest contains duplicate Task structures")

    @property
    def corpus_id(self) -> str:
        return _document_digest(self._preimage())

    def _preimage(self) -> JSONObject:
        return {
            "format": "corpus-manifest/1",
            "policy": self.policy.to_document(),
            "seed": self.seed,
            "entries": [item.to_document() for item in self.entries],
            "selection_evidence_digest": self.selection_evidence_digest,
        }

    def to_document(self) -> JSONObject:
        return {**self._preimage(), "corpus_id": self.corpus_id}


@dataclass(frozen=True, slots=True)
class TaskFoundryProductReport:
    batch: TaskBatchReport
    assessments: tuple[TaskAssessment, ...]
    corpus: CorpusManifest

    def __post_init__(self) -> None:
        admitted_ids = {item.task_pack_id for item in self.batch.admitted}
        assessment_ids = {item.task_pack_id for item in self.assessments}
        corpus_ids = {item.task_pack_id for item in self.corpus.entries}
        if len(assessment_ids) != len(self.assessments):
            raise AssessmentError("product report contains duplicate TaskAssessments")
        if admitted_ids != assessment_ids:
            raise AssessmentError("product report must assess every admitted TaskPack once")
        if not corpus_ids <= admitted_ids:
            raise AssessmentError("CorpusManifest references an unadmitted TaskPack")
        expected_assessments = {item.task_pack_id: item for item in self.assessments}
        if any(
            item.assessment_id != expected_assessments[item.task_pack_id].assessment_id
            or item.release_id != expected_assessments[item.task_pack_id].release_id
            or item.goal_kind != expected_assessments[item.task_pack_id].goal_kind
            or item.reliability != expected_assessments[item.task_pack_id].reliability
            for item in self.corpus.entries
        ):
            raise AssessmentError("CorpusManifest facts differ from the exact TaskAssessment")

    @property
    def product_run_id(self) -> str:
        return _document_digest(self._preimage())

    def _preimage(self) -> JSONObject:
        return {
            "format": "task-foundry-product-report/1",
            "batch": self.batch.to_document(),
            "assessments": [item.to_document() for item in self.assessments],
            "corpus": self.corpus.to_document(),
        }

    def to_document(self) -> JSONObject:
        return {**self._preimage(), "product_run_id": self.product_run_id}


def assess_task(
    prepared: OpenPreparedRelease,
    kind: AssessmentGoalKind,
    task: AssessmentTask,
    *,
    task_pack_id: str,
    atom_task_universe: tuple[AtomTask, ...],
    instance_root: Path,
    policy: AssessmentPolicy,
    route: AgentRoute | None = None,
) -> TaskAssessment:
    """Measure a frozen TaskPack with fresh public runs; never change its verdict."""

    _digest(task_pack_id, "assessment task_pack_id")
    _validate_task_kind(kind, task)
    if task.release_id != prepared.identity.release_id:
        raise AssessmentError("assessment Task belongs to another release")
    selected_route = route or AgentRoute(max_provider_turns=policy.max_provider_turns)
    if (
        AssessmentPolicy.from_route(
            selected_route,
            trial_count=policy.trial_count,
        )
        != policy
    ):
        raise AssessmentError("assessment route differs from the frozen policy")
    runs: list[AssessmentRun] = []
    for trial_index in range(1, policy.trial_count + 1):
        started = time.monotonic_ns()
        try:
            witness = _run_once(
                prepared,
                kind,
                task,
                atom_task_universe,
                Path(instance_root) / f"trial-{trial_index}",
                selected_route,
                policy.max_provider_turns,
            )
            satisfied, failure_codes = _witness_result(kind, witness)
            input_tokens, output_tokens = _usage_tokens(witness.usage)
            runs.append(
                AssessmentRun(
                    trial_index,
                    "satisfied" if satisfied else "failed",
                    witness.materialization_id,
                    _object(witness.to_document()),
                    witness.provider_turns,
                    input_tokens,
                    output_tokens,
                    _elapsed_ms(started),
                    failure_codes,
                )
            )
        except PublicAgentFailure as exc:
            if exc.kind != "NoPublicWitness":
                raise
            runs.append(
                _failed_run(
                    trial_index,
                    started,
                    exc.code,
                    {
                        "format": "assessment-public-agent-failure/1",
                        "kind": exc.kind,
                        "code": exc.code,
                        "message": str(exc),
                        "details": _safe_object(exc.details),
                    },
                )
            )
    return TaskAssessment(
        task_pack_id,
        prepared.identity.release_id,
        kind,
        policy,
        tuple(runs),
    )


def select_corpus(
    candidates: tuple[CorpusSelectionCandidate, ...],
    *,
    policy: CorpusPolicy,
    seed: int,
) -> CorpusManifest:
    """Select reliable, structurally unique Tasks without changing Task truth."""

    if isinstance(seed, bool) or not isinstance(seed, int):
        raise AssessmentError("corpus seed must be an integer")
    candidate_ids = tuple((item.task_pack_id, item.assessment_id) for item in candidates)
    if len(candidate_ids) != len(set(candidate_ids)):
        raise AssessmentError("corpus candidates must be unique")
    evidence_document = {
        "format": "corpus-selection-evidence/1",
        "policy": policy.to_document(),
        "seed": seed,
        "candidates": [item.to_document() for item in candidates],
    }
    eligible = [item for item in candidates if item.reliability >= policy.minimum_reliability]
    best_by_structure: dict[tuple[str, str], CorpusSelectionCandidate] = {}
    for item in eligible:
        key = (item.release_id, item.structure_id)
        previous = best_by_structure.get(key)
        if previous is None or (-item.reliability, item.task_pack_id) < (
            -previous.reliability,
            previous.task_pack_id,
        ):
            best_by_structure[key] = item
    buckets: dict[tuple[str, str], list[CorpusSelectionCandidate]] = {}
    for item in best_by_structure.values():
        buckets.setdefault((item.release_id, item.goal_kind), []).append(item)
    for key, values in buckets.items():
        values.sort(key=lambda item: _seeded_order(seed, key, item))
    selected: list[CorpusSelectionCandidate] = []
    keys = sorted(buckets)
    while keys and (policy.max_tasks is None or len(selected) < policy.max_tasks):
        next_keys: list[tuple[str, str]] = []
        for key in keys:
            if policy.max_tasks is not None and len(selected) >= policy.max_tasks:
                break
            values = buckets[key]
            selected.append(values.pop(0))
            if values:
                next_keys.append(key)
        keys = next_keys
    if not selected:
        raise AssessmentError("no TaskAssessment satisfies the CorpusPolicy")
    return CorpusManifest(
        policy,
        seed,
        tuple(selected),
        _document_digest(evidence_document),
    )


def run_task_foundry_product(
    prepared: OpenPreparedRelease,
    work_root: Path,
    output_root: Path,
    *,
    target_structures: int,
    assessment_trial_count: int,
    corpus_policy: CorpusPolicy,
    corpus_seed: int,
    admission_route: AgentRoute | None = None,
    assessment_route: AgentRoute | None = None,
    max_provider_turns: int = 12,
    candidate_attempt_limit: int = 3,
    event_sink: Callable[[JSONObject], None] | None = None,
) -> TaskFoundryProductReport:
    """Admit Tasks, assess them independently, then select a separate corpus."""

    _positive(assessment_trial_count, "assessment trial count")
    root = Path(work_root)
    output = Path(output_root)
    if output.exists() or output.is_symlink():
        raise AssessmentError("Task Foundry product output must be new")
    output.mkdir(parents=True)
    batch_output = output / "batch"
    batch = run_task_foundry_batch(
        prepared,
        root / "admission",
        batch_output,
        target_structures=target_structures,
        route=admission_route,
        max_provider_turns=max_provider_turns,
        candidate_attempt_limit=candidate_attempt_limit,
        event_sink=event_sink,
    )
    selected_route = assessment_route or AgentRoute(max_provider_turns=max_provider_turns)
    assessment_policy = AssessmentPolicy.from_route(
        selected_route,
        trial_count=assessment_trial_count,
    )
    candidates, atom_tasks = _compile_candidates(prepared, root / "assessment-compile")
    by_task_id: dict[str, list[Any]] = {}
    for candidate in candidates:
        by_task_id.setdefault(candidate.task_id, []).append(candidate)
    assessments: list[TaskAssessment] = []
    corpus_candidates: list[CorpusSelectionCandidate] = []
    for record in batch.admitted:
        matching = by_task_id.get(record.task_id, [])
        if (
            len(matching) != 1
            or matching[0].kind != record.kind
            or matching[0].structure_id != record.structure_id
        ):
            raise AssessmentError("admitted Task cannot be resolved from the sealed release")
        verify_task_pack_artifact(batch_output / record.artifact_path, record.task_pack_id)
        assessment = assess_task(
            prepared,
            record.kind,
            matching[0].task,
            task_pack_id=record.task_pack_id,
            atom_task_universe=atom_tasks,
            instance_root=root / "assessment" / record.task_pack_id,
            policy=assessment_policy,
            route=selected_route,
        )
        _persist_identity_document(
            output / "assessments" / assessment.assessment_id / "TaskAssessment.json",
            assessment.to_document(),
        )
        assessments.append(assessment)
        corpus_candidates.append(
            CorpusSelectionCandidate(
                record.task_pack_id,
                assessment.assessment_id,
                batch.release_id,
                record.kind,
                record.structure_id,
                assessment.reliability,
            )
        )
    corpus = select_corpus(tuple(corpus_candidates), policy=corpus_policy, seed=corpus_seed)
    _persist_identity_document(
        output / "corpora" / corpus.corpus_id / "CorpusManifest.json",
        corpus.to_document(),
    )
    report = TaskFoundryProductReport(batch, tuple(assessments), corpus)
    _persist_identity_document(
        output / "runs" / f"{report.product_run_id}.json",
        report.to_document(),
    )
    return report


def _run_once(
    prepared: OpenPreparedRelease,
    kind: AssessmentGoalKind,
    task: AssessmentTask,
    atom_task_universe: tuple[AtomTask, ...],
    instance_root: Path,
    route: AgentRoute,
    max_provider_turns: int,
) -> AssessmentWitness:
    if kind == "atom" and isinstance(task, AtomTask):
        return run_atom_task_once(
            prepared,
            task,
            instance_root,
            route=route,
            max_provider_turns=max_provider_turns,
        )
    if kind == "foreach" and isinstance(task, ForEachTask):
        return run_foreach_task_once(
            prepared,
            task,
            instance_root,
            route=route,
            max_provider_turns=max_provider_turns,
        )
    if kind == "if" and isinstance(task, IfTask):
        return run_if_task_once(
            prepared,
            task,
            atom_task_universe,
            instance_root,
            route=route,
            max_provider_turns=max_provider_turns,
        )
    raise AssessmentError("assessment Task value and goal kind differ")


def _witness_result(
    kind: AssessmentGoalKind,
    witness: AssessmentWitness,
) -> tuple[bool, tuple[str, ...]]:
    if kind == "atom" and isinstance(witness, AtomWitness):
        return witness.result.satisfied, witness.result.failure_codes
    if kind == "foreach" and isinstance(witness, ForEachWitness):
        failures = tuple(
            f"member_{index}_{code}"
            for index, result in enumerate(witness.member_results)
            for code in result.failure_codes
        )
        return all(item.satisfied for item in witness.member_results), failures
    if kind == "if" and isinstance(witness, IfWitness):
        failures = tuple(
            sorted(
                {
                    *witness.condition_result.failure_codes,
                    *witness.branch_result.failure_codes,
                }
            )
        )
        return witness.branch_result.satisfied and not failures, failures
    raise AssessmentError("assessment witness and goal kind differ")


def _failed_run(
    trial_index: int,
    started: int,
    code: str,
    evidence: JSONObject,
) -> AssessmentRun:
    return AssessmentRun(
        trial_index,
        "failed",
        None,
        evidence,
        0,
        0,
        0,
        _elapsed_ms(started),
        (code,),
    )


def _validate_task_kind(kind: AssessmentGoalKind, task: AssessmentTask) -> None:
    if not (
        (kind == "atom" and isinstance(task, AtomTask))
        or (kind == "foreach" and isinstance(task, ForEachTask))
        or (kind == "if" and isinstance(task, IfTask))
    ):
        raise AssessmentError("assessment Task value and goal kind differ")


def _usage_tokens(usage: tuple[JSONObject | None, ...]) -> tuple[int, int]:
    input_tokens = 0
    output_tokens = 0
    for item in usage:
        if item is None:
            continue
        for field, target in (("input_tokens", "input"), ("output_tokens", "output")):
            value = item.get(field)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                continue
            if target == "input":
                input_tokens += value
            else:
                output_tokens += value
    return input_tokens, output_tokens


def _elapsed_ms(started: int) -> int:
    return max(0, (time.monotonic_ns() - started) // 1_000_000)


def _seeded_order(
    seed: int,
    bucket: tuple[str, str],
    item: CorpusSelectionCandidate,
) -> str:
    return _document_digest(
        {
            "seed": seed,
            "bucket": list(bucket),
            "candidate": item.to_document(),
        }
    )


def _persist_identity_document(path: Path, document: JSONObject) -> None:
    payload = canonical_bytes(document)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_bytes() != payload:
        raise AssessmentError("identity artifact collision")
    path.write_bytes(payload)


def _safe_object(value: Any) -> JSONObject:
    try:
        normalized = json.loads(json.dumps(value, ensure_ascii=False))
    except (TypeError, ValueError):
        return {"unserializable_details": str(value)}
    return _object(normalized) if is_json_object(normalized) else {"details": normalized}


def _object(value: Any) -> JSONObject:
    if not is_json_object(value):
        raise AssessmentError("assessment value must be a JSON object")
    return cast(JSONObject, json.loads(json.dumps(value, ensure_ascii=False)))


def _document_digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _digest(value: str, role: str) -> None:
    if len(value) != 64 or any(character not in _HEX for character in value):
        raise AssessmentError(f"{role} must be a sha256 digest")


def _text(value: str, role: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise AssessmentError(f"{role} must be non-empty")


def _positive(value: int, role: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise AssessmentError(f"{role} must be positive")


def _nonnegative(value: int, role: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise AssessmentError(f"{role} must be non-negative")


def _unique_text(values: tuple[str, ...], role: str) -> None:
    if len(values) != len(set(values)) or any(not item for item in values):
        raise AssessmentError(f"{role} must be unique non-empty strings")


__all__ = [
    "AssessmentError",
    "AssessmentPolicy",
    "AssessmentRun",
    "CorpusManifest",
    "CorpusPolicy",
    "CorpusSelectionCandidate",
    "TaskAssessment",
    "TaskFoundryProductReport",
    "assess_task",
    "run_task_foundry_product",
    "select_corpus",
]
