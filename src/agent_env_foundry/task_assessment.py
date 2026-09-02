"""Model-relative Task assessment and identity-separated corpus selection."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

from agent_env_foundry.agents import AgentRoute
from agent_env_foundry.environment import JSONObject, JSONValue
from agent_env_foundry.jsonvalue import is_json_object
from agent_env_foundry.physical_runtime import PreparationSettings
from agent_env_foundry.public_agent import (
    PUBLIC_AGENT_PROMPT_DIGEST,
    ClientFactory,
)
from agent_env_foundry.release import canonical_bytes, sha256_hex
from agent_env_foundry.task_admission import TaskAdmissionFailure, run_checked_task_attempt
from agent_env_foundry.task_pack import TaskPack
from agent_env_foundry.task_proposal import PreparedTaskEnvironment

ASSESSMENT_RUN_FORMAT = "task-assessment-run/1"
TASK_ASSESSMENT_FORMAT = "task-assessment/1"
CORPUS_MANIFEST_FORMAT = "corpus-manifest/1"

AssessmentStatus = Literal["satisfied", "failed", "abstained"]


class TaskAssessmentError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class TaskAssessmentRun:
    format: str
    trial_index: int
    status: AssessmentStatus
    evidence_digest: str
    provider_turns: int
    input_tokens: int
    output_tokens: int
    elapsed_ms: int
    failure_kind: str | None
    failure_code: str | None

    def __post_init__(self) -> None:
        if self.format != ASSESSMENT_RUN_FORMAT:
            raise TaskAssessmentError("assessment run format is invalid")
        if (
            self.trial_index <= 0
            or min(self.provider_turns, self.input_tokens, self.output_tokens, self.elapsed_ms) < 0
        ):
            raise TaskAssessmentError("assessment run counters are invalid")
        _digest(self.evidence_digest, "assessment evidence")
        if self.status not in {"satisfied", "failed", "abstained"}:
            raise TaskAssessmentError("assessment run status is invalid")
        if self.status == "satisfied":
            if self.failure_kind is not None or self.failure_code is not None:
                raise TaskAssessmentError("satisfied assessment run cannot contain a failure")
        elif not self.failure_kind or not self.failure_code:
            raise TaskAssessmentError("failed or abstained assessment run requires attribution")

    def to_document(self) -> JSONObject:
        return {
            "format": self.format,
            "trial_index": self.trial_index,
            "status": self.status,
            "evidence_digest": self.evidence_digest,
            "provider_turns": self.provider_turns,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "elapsed_ms": self.elapsed_ms,
            "failure_kind": self.failure_kind,
            "failure_code": self.failure_code,
        }


@dataclass(frozen=True, slots=True)
class TaskAssessment:
    format: str
    task_pack_id: str
    task_id: str
    release_id: str
    policy_id: str
    structure_id: str
    runs: tuple[TaskAssessmentRun, ...]

    def __post_init__(self) -> None:
        if self.format != TASK_ASSESSMENT_FORMAT:
            raise TaskAssessmentError("TaskAssessment format is invalid")
        for value, role in (
            (self.task_pack_id, "TaskPack"),
            (self.task_id, "Task"),
            (self.release_id, "Release"),
            (self.policy_id, "policy"),
            (self.structure_id, "structure"),
        ):
            _digest(value, role)
        if not self.runs or tuple(item.trial_index for item in self.runs) != tuple(
            range(1, len(self.runs) + 1)
        ):
            raise TaskAssessmentError("assessment runs must cover the ordered trial set")

    @property
    def assessment_id(self) -> str:
        return sha256_hex(canonical_bytes(self.to_document()))

    @property
    def valid_trials(self) -> int:
        return sum(item.status != "abstained" for item in self.runs)

    @property
    def reliability(self) -> float:
        valid = self.valid_trials
        return sum(item.status == "satisfied" for item in self.runs) / valid if valid else 0.0

    def to_document(self) -> JSONObject:
        return {
            "format": self.format,
            "task_pack_id": self.task_pack_id,
            "task_id": self.task_id,
            "release_id": self.release_id,
            "policy_id": self.policy_id,
            "structure_id": self.structure_id,
            "runs": [item.to_document() for item in self.runs],
            "valid_trials": self.valid_trials,
            "reliability": self.reliability,
        }

    def artifact_document(self) -> JSONObject:
        return {**self.to_document(), "assessment_id": self.assessment_id}


@dataclass(frozen=True, slots=True)
class CorpusEntry:
    task_pack_id: str
    assessment_id: str
    task_id: str
    release_id: str
    structure_id: str
    reliability: float

    def __post_init__(self) -> None:
        for value, role in (
            (self.task_pack_id, "corpus TaskPack"),
            (self.assessment_id, "corpus assessment"),
            (self.task_id, "corpus Task"),
            (self.release_id, "corpus Release"),
            (self.structure_id, "corpus structure"),
        ):
            _digest(value, role)
        if not 0.0 <= self.reliability <= 1.0:
            raise TaskAssessmentError("corpus reliability is invalid")

    def to_document(self) -> JSONObject:
        return {
            "task_pack_id": self.task_pack_id,
            "assessment_id": self.assessment_id,
            "task_id": self.task_id,
            "release_id": self.release_id,
            "structure_id": self.structure_id,
            "reliability": self.reliability,
        }


@dataclass(frozen=True, slots=True)
class CorpusManifest:
    format: str
    minimum_reliability: float
    candidates: tuple[tuple[str, str], ...]
    entries: tuple[CorpusEntry, ...]

    def __post_init__(self) -> None:
        if self.format != CORPUS_MANIFEST_FORMAT:
            raise TaskAssessmentError("CorpusManifest format is invalid")
        if not 0.0 <= self.minimum_reliability <= 1.0 or not self.entries:
            raise TaskAssessmentError("CorpusManifest policy or entries are invalid")
        if len(set(self.candidates)) != len(self.candidates):
            raise TaskAssessmentError("CorpusManifest candidates must be unique")
        selected = {(item.task_pack_id, item.assessment_id) for item in self.entries}
        if not selected <= set(self.candidates):
            raise TaskAssessmentError("CorpusManifest selected an unconsidered pair")
        if len({item.structure_id for item in self.entries}) != len(self.entries):
            raise TaskAssessmentError("CorpusManifest contains duplicate Task structures")
        if any(item.reliability < self.minimum_reliability for item in self.entries):
            raise TaskAssessmentError("CorpusManifest selected below-policy reliability")

    @property
    def corpus_id(self) -> str:
        return sha256_hex(canonical_bytes(self.to_document()))

    def to_document(self) -> JSONObject:
        return {
            "format": self.format,
            "minimum_reliability": self.minimum_reliability,
            "candidates": [list(item) for item in self.candidates],
            "entries": [item.to_document() for item in self.entries],
        }

    def artifact_document(self) -> JSONObject:
        return {**self.to_document(), "corpus_id": self.corpus_id}


def assess_task(
    pack: TaskPack,
    prepared: PreparedTaskEnvironment,
    *,
    checker_project_root: Path,
    output_root: Path,
    trial_count: int,
    route: AgentRoute | None = None,
    client_factory: ClientFactory | None = None,
    checker_settings: PreparationSettings | None = None,
) -> TaskAssessment:
    if not isinstance(pack, TaskPack) or trial_count <= 0:
        raise TaskAssessmentError("assessment requires one TaskPack and positive trial_count")
    selected_route = route or AgentRoute()
    root = _fresh_root(output_root)
    runs: list[TaskAssessmentRun] = []
    for trial_index in range(1, trial_count + 1):
        trial_root = root / f"trial-{trial_index:03d}"
        trial_root.mkdir()
        started = time.monotonic_ns()
        try:
            attempt = run_checked_task_attempt(
                prepared,
                task=pack.task,
                checker_project_root=checker_project_root,
                instance_directory=trial_root / "instance",
                checker_runtime_root=trial_root / "checker-runtime",
                instruction=pack.task.instruction,
                route=selected_route,
                client_factory=client_factory,
                checker_settings=checker_settings,
            )
        except TaskAdmissionFailure as exc:
            failure = _failure_evidence(exc)
            evidence_bytes = canonical_bytes(failure)
            (trial_root / "Failure.json").write_bytes(evidence_bytes)
            turns, input_tokens, output_tokens = _capture_usage(failure.get("capture"))
            status: AssessmentStatus = (
                "failed" if exc.kind in {"NoPublicWitness", "TaskRejected"} else "abstained"
            )
            runs.append(
                TaskAssessmentRun(
                    ASSESSMENT_RUN_FORMAT,
                    trial_index,
                    status,
                    sha256_hex(evidence_bytes),
                    turns,
                    input_tokens,
                    output_tokens,
                    _elapsed_ms(started),
                    exc.kind,
                    exc.code,
                )
            )
            continue
        evidence_bytes = canonical_bytes(attempt.to_document())
        (trial_root / "CheckedTaskAttempt.json").write_bytes(evidence_bytes)
        input_tokens, output_tokens = _usage_tokens(attempt.usage)
        satisfied = attempt.checker_result.passed
        runs.append(
            TaskAssessmentRun(
                ASSESSMENT_RUN_FORMAT,
                trial_index,
                "satisfied" if satisfied else "failed",
                sha256_hex(evidence_bytes),
                attempt.provider_turns,
                input_tokens,
                output_tokens,
                _elapsed_ms(started),
                None if satisfied else "NoPublicWitness",
                None if satisfied else "assessment_checker_rejected",
            )
        )
    assessment = TaskAssessment(
        TASK_ASSESSMENT_FORMAT,
        pack.task_pack_id,
        pack.task.task_id,
        pack.task.release_id,
        _policy_id(selected_route),
        task_structure_id(pack),
        tuple(runs),
    )
    (root / "TaskAssessment.json").write_bytes(canonical_bytes(assessment.artifact_document()))
    return assessment


def task_structure_id(pack: TaskPack) -> str:
    proposal_tools = sorted(
        {cast(str, item["tool"]) for item in pack.proposal_evidence.public_trace}
    )
    return sha256_hex(
        canonical_bytes(
            {
                "format": "task-structure/1",
                "answer_shape": _schema_shape(pack.task.final_answer_schema),
                "challenge_categories": list(pack.task.challenge_categories),
                "proposal_tools": proposal_tools,
                "changes_state": (
                    pack.proposal_evidence.before_state != pack.proposal_evidence.after_state
                ),
            }
        )
    )


def select_corpus(
    assessments: tuple[TaskAssessment, ...], *, minimum_reliability: float
) -> CorpusManifest:
    if not assessments or not 0.0 <= minimum_reliability <= 1.0:
        raise TaskAssessmentError("corpus selection input is invalid")
    if len({item.assessment_id for item in assessments}) != len(assessments):
        raise TaskAssessmentError("corpus assessments must be unique")
    candidates = tuple(sorted((item.task_pack_id, item.assessment_id) for item in assessments))
    eligible = [
        item
        for item in assessments
        if item.valid_trials > 0 and item.reliability >= minimum_reliability
    ]
    selected: dict[str, TaskAssessment] = {}
    for item in sorted(eligible, key=lambda value: (-value.reliability, value.task_pack_id)):
        selected.setdefault(item.structure_id, item)
    if not selected:
        raise TaskAssessmentError("no TaskAssessment satisfies the corpus policy")
    entries = tuple(
        CorpusEntry(
            item.task_pack_id,
            item.assessment_id,
            item.task_id,
            item.release_id,
            item.structure_id,
            item.reliability,
        )
        for item in sorted(selected.values(), key=lambda value: value.task_pack_id)
    )
    return CorpusManifest(
        CORPUS_MANIFEST_FORMAT,
        minimum_reliability,
        candidates,
        entries,
    )


def write_corpus_manifest(manifest: CorpusManifest, path: Path) -> None:
    target = Path(path)
    if target.exists() or target.is_symlink():
        raise TaskAssessmentError("CorpusManifest destination must not exist")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(canonical_bytes(manifest.artifact_document()))
    target.chmod(0o444)


def _schema_shape(value: JSONValue) -> JSONValue:
    if isinstance(value, dict):
        shaped: JSONObject = {}
        for key in ("type", "anyOf", "oneOf", "items"):
            if key in value:
                shaped[key] = _schema_shape(value[key])
        properties = value.get("properties")
        if isinstance(properties, dict):
            shapes = [_schema_shape(item) for item in properties.values()]
            shaped["property_shapes"] = sorted(shapes, key=lambda item: canonical_bytes(item))
            required = value.get("required")
            shaped["required_count"] = len(required) if isinstance(required, list) else 0
        if "enum" in value and isinstance(value["enum"], list):
            shaped["enum_types"] = cast(
                JSONValue,
                sorted({_json_type(item) for item in value["enum"]}),
            )
        if "const" in value:
            shaped["const_type"] = _json_type(value["const"])
        return shaped
    if isinstance(value, list):
        return [_schema_shape(item) for item in value]
    return value


def _json_type(value: JSONValue) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    return "object"


def _policy_id(route: AgentRoute) -> str:
    return sha256_hex(
        canonical_bytes(
            {
                "format": "assessment-policy/1",
                "model": route.model,
                "base_url": route.base_url,
                "max_provider_turns": route.max_provider_turns,
                "prompt_digest": PUBLIC_AGENT_PROMPT_DIGEST,
            }
        )
    )


def _failure_evidence(exc: TaskAdmissionFailure) -> JSONObject:
    document: JSONObject = {
        "format": "task-assessment-failure/1",
        "kind": exc.kind,
        "code": exc.code,
    }
    capture = exc.details.get("capture")
    if is_json_object(capture):
        document["capture"] = cast(JSONObject, capture)
    return document


def _capture_usage(value: JSONValue | None) -> tuple[int, int, int]:
    if not isinstance(value, dict) or not isinstance(value.get("turns"), list):
        return 0, 0, 0
    turns = cast(list[JSONValue], value["turns"])
    usage = tuple(
        cast(JSONObject, item["usage"])
        for item in turns
        if isinstance(item, dict) and is_json_object(item.get("usage"))
    )
    input_tokens, output_tokens = _usage_tokens(usage)
    return len(turns), input_tokens, output_tokens


def _usage_tokens(values: tuple[JSONObject | None, ...]) -> tuple[int, int]:
    def total(key: str) -> int:
        result = 0
        for value in values:
            if not isinstance(value, dict):
                continue
            item = value.get(key, 0)
            if isinstance(item, int) and not isinstance(item, bool):
                result += item
        return result

    return total("input_tokens"), total("output_tokens")


def _fresh_root(path: Path) -> Path:
    root = Path(path)
    if root.is_symlink() or (root.exists() and (not root.is_dir() or any(root.iterdir()))):
        raise TaskAssessmentError("assessment output_root must be absent or empty")
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def _elapsed_ms(started: int) -> int:
    return max(0, (time.monotonic_ns() - started) // 1_000_000)


def _digest(value: str, role: str) -> None:
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise TaskAssessmentError(f"{role} identity must be a sha256 digest")


__all__ = [
    "ASSESSMENT_RUN_FORMAT",
    "CORPUS_MANIFEST_FORMAT",
    "TASK_ASSESSMENT_FORMAT",
    "AssessmentStatus",
    "CorpusEntry",
    "CorpusManifest",
    "TaskAssessment",
    "TaskAssessmentError",
    "TaskAssessmentRun",
    "assess_task",
    "select_corpus",
    "task_structure_id",
    "write_corpus_manifest",
]
