"""Five-run Good-Task admission and the checker-free TaskPack artifact."""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

from agent_env_foundry.agents import AgentRoute
from agent_env_foundry.environment import JSONObject, JSONValue
from agent_env_foundry.episodes import EpisodeDefect, PublicEpisodeCapture
from agent_env_foundry.jsonvalue import is_json_object, is_json_value
from agent_env_foundry.public_agent import (
    ClientFactory,
    PolicyDriver,
    ResponsesPolicyDriver,
    capture_public_episode,
)
from agent_env_foundry.release import _hex_digest, canonical_bytes, sha256_hex
from agent_env_foundry.task_candidate import (
    ArgumentOrigin,
    CandidateMaterializationFailure,
    CandidateTask,
    MaterializedCandidate,
    argument_origin_from_document,
    candidate_task_from_document,
    derive_argument_origins,
)
from agent_env_foundry.task_goal import (
    EvaluationContext,
    EvaluationResult,
    TraceEvent,
    evaluate_goal,
)
from agent_env_foundry.task_proposal import PreparedTaskEnvironment, TaskSamplingEvidence

FILTER_EVIDENCE_FORMAT = "task-filter-evidence/1"
PUBLIC_TASK_FORMAT = "public-task/1"
TASK_PACK_FORMAT = "task-pack/1"
TRUSTED_TASK_FORMAT = "trusted-task-evidence/1"
FILTER_RUNS = 5
MINIMUM_PASSES = 2

TaskAdmissionFailureKind = Literal[
    "PolicyRejected",
    "EnvironmentDefect",
    "FrameworkDefect",
    "InfrastructureFailure",
    "TaskArtifactDefect",
]
RetryOwner = Literal["provider", "infrastructure"]
PolicyDriverFactory = Callable[[int, int], PolicyDriver]


class TaskAdmissionFailure(RuntimeError):
    def __init__(
        self,
        kind: TaskAdmissionFailureKind,
        code: str,
        message: str,
        **details: Any,
    ) -> None:
        super().__init__(message)
        self.kind, self.code, self.details = kind, code, details


@dataclass(frozen=True, slots=True)
class InfrastructureRetry:
    run_index: int
    attempt_index: int
    owner: RetryOwner
    code: str

    def __post_init__(self) -> None:
        _positive(self.run_index, "retry run_index")
        _positive(self.attempt_index, "retry attempt_index")
        if self.owner not in {"provider", "infrastructure"}:
            raise ValueError("retry owner must be provider or infrastructure")
        _text(self.code, "retry code")

    def to_document(self) -> JSONObject:
        return {
            "run_index": self.run_index,
            "attempt_index": self.attempt_index,
            "owner": self.owner,
            "code": self.code,
        }


@dataclass(frozen=True, slots=True)
class PolicyFilterRun:
    run_index: int
    materialization_id: str
    policy_id: str
    reset_observation: JSONValue
    before_state: JSONValue
    after_state: JSONValue
    trace: tuple[TraceEvent, ...]
    final_answer: JSONObject | None
    terminal_code: str | None
    argument_origins: tuple[ArgumentOrigin, ...]
    evaluation: EvaluationResult
    policy_failure_codes: tuple[str, ...]
    provider_turns: int
    usage: tuple[JSONObject | None, ...]

    def __post_init__(self) -> None:
        _positive(self.run_index, "filter run_index")
        _digest(self.materialization_id, "materialization_id")
        _digest(self.policy_id, "policy_id")
        for value, role in (
            (self.reset_observation, "reset_observation"),
            (self.before_state, "before_state"),
            (self.after_state, "after_state"),
        ):
            if not is_json_value(value):
                raise ValueError(f"{role} must be JSON")
        if any(not isinstance(event, TraceEvent) for event in self.trace):
            raise ValueError("filter trace must contain TraceEvents")
        if self.final_answer is not None and not is_json_object(self.final_answer):
            raise ValueError("filter final_answer must be an object or null")
        if (self.final_answer is None) != (self.terminal_code is not None):
            raise ValueError("filter completion requires either answer or terminal code")
        if self.terminal_code is not None:
            _text(self.terminal_code, "terminal_code")
        if any(not isinstance(item, ArgumentOrigin) for item in self.argument_origins):
            raise ValueError("argument_origins must contain ArgumentOrigin values")
        if not isinstance(self.evaluation, EvaluationResult):
            raise ValueError("filter run requires an EvaluationResult")
        _unique_texts(self.policy_failure_codes, "policy_failure_codes", allow_empty=True)
        _positive(self.provider_turns, "provider_turns")
        for item in self.usage:
            if item is not None and not is_json_object(item):
                raise ValueError("usage entries must be objects or null")
        for name in ("reset_observation", "before_state", "after_state"):
            object.__setattr__(self, name, _copy_json(cast(JSONValue, getattr(self, name))))
        object.__setattr__(self, "final_answer", _copy_optional_object(self.final_answer))
        object.__setattr__(
            self,
            "usage",
            tuple(_copy_optional_object(item) for item in self.usage),
        )

    @property
    def passed(self) -> bool:
        return (
            self.final_answer is not None
            and self.terminal_code is None
            and not self.policy_failure_codes
            and self.evaluation.passed
        )

    @property
    def failure_owner(self) -> Literal["policy"] | None:
        return None if self.passed else "policy"

    @property
    def run_id(self) -> str:
        return _document_digest(self.to_document())

    def to_document(self) -> JSONObject:
        return {
            "run_index": self.run_index,
            "materialization_id": self.materialization_id,
            "policy_id": self.policy_id,
            "reset_observation": _copy_json(self.reset_observation),
            "before_state": _copy_json(self.before_state),
            "after_state": _copy_json(self.after_state),
            "trace": [event.to_document() for event in self.trace],
            "final_answer": _copy_optional_object(self.final_answer),
            "terminal_code": self.terminal_code,
            "argument_origins": [item.to_document() for item in self.argument_origins],
            "evaluation": self.evaluation.to_document(),
            "policy_failure_codes": list(self.policy_failure_codes),
            "failure_owner": self.failure_owner,
            "provider_turns": self.provider_turns,
            "usage": [_copy_optional_object(item) for item in self.usage],
        }


@dataclass(frozen=True, slots=True)
class TaskFilterEvidence:
    candidate_id: str
    runs: tuple[PolicyFilterRun, ...]
    infrastructure_retries: tuple[InfrastructureRetry, ...]

    def __post_init__(self) -> None:
        _digest(self.candidate_id, "candidate_id")
        if len(self.runs) != FILTER_RUNS:
            raise ValueError(f"filter requires exactly {FILTER_RUNS} semantic runs")
        if tuple(run.run_index for run in self.runs) != tuple(range(1, FILTER_RUNS + 1)):
            raise ValueError("filter run indices must be contiguous and one-based")
        if len({run.materialization_id for run in self.runs}) != FILTER_RUNS:
            raise ValueError("filter runs must use independent materializations")
        if any(not isinstance(item, InfrastructureRetry) for item in self.infrastructure_retries):
            raise ValueError("infrastructure_retries contains an invalid record")

    @property
    def pass_count(self) -> int:
        return sum(run.passed for run in self.runs)

    @property
    def admitted(self) -> bool:
        return self.pass_count >= MINIMUM_PASSES

    @property
    def evidence_id(self) -> str:
        return _document_digest(self.to_document())

    def to_document(self) -> JSONObject:
        return {
            "format": FILTER_EVIDENCE_FORMAT,
            "candidate_id": self.candidate_id,
            "required_runs": FILTER_RUNS,
            "minimum_passes": MINIMUM_PASSES,
            "pass_count": self.pass_count,
            "admitted": self.admitted,
            "runs": [run.to_document() for run in self.runs],
            "infrastructure_retries": [item.to_document() for item in self.infrastructure_retries],
        }


@dataclass(frozen=True, slots=True)
class PublicTaskView:
    task_pack_id: str
    task_id: str
    release_id: str
    instruction: str
    final_answer_schema: JSONObject

    def __post_init__(self) -> None:
        for value, role in (
            (self.task_pack_id, "task_pack_id"),
            (self.task_id, "task_id"),
            (self.release_id, "release_id"),
        ):
            _digest(value, role)
        _text(self.instruction, "instruction")
        if not is_json_object(self.final_answer_schema):
            raise ValueError("final_answer_schema must be an object")
        object.__setattr__(self, "final_answer_schema", _copy_object(self.final_answer_schema))

    def to_document(self) -> JSONObject:
        return {
            "format": PUBLIC_TASK_FORMAT,
            "task_pack_id": self.task_pack_id,
            "task_id": self.task_id,
            "release_id": self.release_id,
            "instruction": self.instruction,
            "final_answer_schema": _copy_object(self.final_answer_schema),
        }


@dataclass(frozen=True, slots=True)
class TaskPackArtifact:
    root: Path
    task_pack_id: str
    public_view: PublicTaskView
    candidate: CandidateTask
    filter_evidence: TaskFilterEvidence
    trusted_document: JSONObject


def filter_candidate(
    prepared: PreparedTaskEnvironment,
    candidate: CandidateTask,
    *,
    instance_root: Path,
    route: AgentRoute | None = None,
    client_factory: ClientFactory | None = None,
    policy_driver_factory: PolicyDriverFactory | None = None,
    infrastructure_retry_limit: int = 2,
) -> TaskFilterEvidence:
    """Run five fresh public policies; infrastructure retries are not policy outcomes."""

    if candidate.release_id != prepared.identity.release_id:
        raise TaskAdmissionFailure(
            "FrameworkDefect",
            "filter_release_mismatch",
            "Candidate and prepared Release identities differ",
        )
    if (
        not isinstance(infrastructure_retry_limit, int)
        or isinstance(infrastructure_retry_limit, bool)
        or infrastructure_retry_limit < 0
    ):
        raise ValueError("infrastructure_retry_limit must be a non-negative integer")
    root = _fresh_root(instance_root)
    root.mkdir(parents=True, exist_ok=True)
    selected_route = route or AgentRoute()
    factory = policy_driver_factory or _responses_driver_factory(
        selected_route, client_factory=client_factory
    )
    runs: list[PolicyFilterRun] = []
    retries: list[InfrastructureRetry] = []
    drivers: list[PolicyDriver] = []
    for run_index in range(1, FILTER_RUNS + 1):
        for attempt_index in range(1, infrastructure_retry_limit + 2):
            instance = root / f"run-{run_index:02d}-attempt-{attempt_index:02d}"
            try:
                run, defect = _filter_attempt(
                    prepared,
                    candidate,
                    instance=instance,
                    run_index=run_index,
                    attempt_index=attempt_index,
                    driver_factory=factory,
                    prior_drivers=drivers,
                )
            except TaskAdmissionFailure as exc:
                if exc.kind != "InfrastructureFailure":
                    raise
                defect = EpisodeDefect("infrastructure", exc.code, "filter_materialization")
                run = None
            if defect is None:
                assert run is not None
                runs.append(run)
                break
            if defect.owner not in {"provider", "infrastructure"}:
                raise _defect_failure(defect)
            retry_owner: RetryOwner = "provider" if defect.owner == "provider" else "infrastructure"
            retries.append(
                InfrastructureRetry(
                    run_index,
                    attempt_index,
                    retry_owner,
                    defect.code,
                )
            )
            if attempt_index > infrastructure_retry_limit:
                raise TaskAdmissionFailure(
                    "InfrastructureFailure",
                    "filter_infrastructure_retries_exhausted",
                    "filter could not obtain five valid semantic outcomes",
                    run_index=run_index,
                    retries=[item.to_document() for item in retries],
                )
    return TaskFilterEvidence(candidate.candidate_id, tuple(runs), tuple(retries))


def seal_task_pack(
    destination: Path,
    *,
    materialized: MaterializedCandidate,
    sampling_evidence: TaskSamplingEvidence,
    filter_evidence: TaskFilterEvidence,
) -> TaskPackArtifact:
    """Write one canonical checker-free TaskPack and immediately cold-read it."""

    candidate = materialized.candidate
    if not filter_evidence.admitted:
        raise TaskAdmissionFailure(
            "PolicyRejected",
            "candidate_below_pass_threshold",
            "Candidate did not pass at least two of five valid public policy runs",
            pass_count=filter_evidence.pass_count,
        )
    if (
        sampling_evidence.evidence_id != candidate.sampling_evidence_id
        or materialized.replay.replay_id != candidate.reference_replay_id
        or filter_evidence.candidate_id != candidate.candidate_id
    ):
        raise TaskAdmissionFailure(
            "FrameworkDefect",
            "task_pack_evidence_identity_mismatch",
            "TaskPack inputs do not bind the same Candidate",
        )
    trusted: JSONObject = {
        "format": TRUSTED_TASK_FORMAT,
        "candidate": candidate.to_document(),
        "sampling_evidence": sampling_evidence.to_document(),
        "reference_replay": materialized.replay.to_document(),
        "argument_origins": [item.to_document() for item in materialized.argument_origins],
        "filter_evidence": filter_evidence.to_document(),
    }
    trusted_bytes = canonical_bytes(trusted)
    task_pack_id = sha256_hex(trusted_bytes)
    public = PublicTaskView(
        task_pack_id,
        candidate.candidate_id,
        candidate.release_id,
        candidate.instruction,
        candidate.final_answer_schema,
    )
    public_bytes = canonical_bytes(public.to_document())
    manifest: JSONObject = {
        "format": TASK_PACK_FORMAT,
        "task_pack_id": task_pack_id,
        "public_path": "public/task.json",
        "public_digest": sha256_hex(public_bytes),
        "trusted_path": "trusted/evidence.json",
        "trusted_digest": sha256_hex(trusted_bytes),
    }
    root = Path(destination)
    if root.exists() or root.is_symlink():
        raise TaskAdmissionFailure(
            "TaskArtifactDefect",
            "task_pack_destination_exists",
            "TaskPack destination must be new",
        )
    try:
        (root / "public").mkdir(parents=True)
        (root / "trusted").mkdir()
        _write(root / "public/task.json", public_bytes)
        _write(root / "trusted/evidence.json", trusted_bytes)
        _write(root / "task-pack.json", canonical_bytes(manifest))
        return load_task_pack(root)
    except Exception:
        shutil.rmtree(root, ignore_errors=True)
        raise


def load_task_pack(root: Path) -> TaskPackArtifact:
    """Cold-read one exact TaskPack directory without trusting its originating cwd."""

    selected = Path(root)
    if not selected.is_dir() or selected.is_symlink():
        raise _artifact("task_pack_root_invalid", "TaskPack root must be a real directory")
    resolved = selected.resolve()
    expected = {
        Path("task-pack.json"),
        Path("public/task.json"),
        Path("trusted/evidence.json"),
    }
    actual: set[Path] = set()
    for item in resolved.rglob("*"):
        if item.is_symlink():
            raise _artifact("task_pack_symlink", "TaskPack cannot contain symlinks")
        if item.is_file():
            actual.add(item.relative_to(resolved))
    if actual != expected:
        raise _artifact(
            "task_pack_layout_invalid",
            "TaskPack file closure differs from the canonical layout",
        )
    manifest = _read_canonical(resolved / "task-pack.json", "TaskPack manifest")
    _exact(
        manifest,
        {
            "format",
            "task_pack_id",
            "public_path",
            "public_digest",
            "trusted_path",
            "trusted_digest",
        },
        "TaskPack manifest",
    )
    if (
        manifest["format"] != TASK_PACK_FORMAT
        or manifest["public_path"] != "public/task.json"
        or manifest["trusted_path"] != "trusted/evidence.json"
    ):
        raise _artifact("task_pack_manifest_invalid", "TaskPack manifest contract mismatch")
    task_pack_id = _digest_value(manifest["task_pack_id"], "task_pack_id")
    public_digest = _digest_value(manifest["public_digest"], "public_digest")
    trusted_digest = _digest_value(manifest["trusted_digest"], "trusted_digest")
    public_path = resolved / "public/task.json"
    trusted_path = resolved / "trusted/evidence.json"
    if (
        sha256_hex(public_path.read_bytes()) != public_digest
        or sha256_hex(trusted_path.read_bytes()) != trusted_digest
        or trusted_digest != task_pack_id
    ):
        raise _artifact("task_pack_digest_mismatch", "TaskPack payload digest mismatch")
    public_document = _read_canonical(public_path, "public Task view")
    trusted = _read_canonical(trusted_path, "trusted Task evidence")
    public = _public_view_from_document(public_document)
    _exact(
        trusted,
        {
            "format",
            "candidate",
            "sampling_evidence",
            "reference_replay",
            "argument_origins",
            "filter_evidence",
        },
        "trusted Task evidence",
    )
    if trusted["format"] != TRUSTED_TASK_FORMAT:
        raise _artifact("trusted_task_format_invalid", "trusted Task format mismatch")
    try:
        candidate = candidate_task_from_document(trusted["candidate"])
        filter_evidence = task_filter_evidence_from_document(trusted["filter_evidence"])
        origins_document = trusted["argument_origins"]
        if not isinstance(origins_document, list):
            raise ValueError("argument_origins must be an array")
        tuple(argument_origin_from_document(item) for item in origins_document)
    except ValueError as exc:
        raise _artifact("task_pack_trusted_invalid", str(exc)) from exc
    sampling = trusted["sampling_evidence"]
    replay = trusted["reference_replay"]
    if not is_json_object(sampling) or not is_json_object(replay):
        raise _artifact("task_pack_trusted_invalid", "sampling/replay evidence must be objects")
    sampling_document = cast(JSONObject, sampling)
    replay_document = cast(JSONObject, replay)
    if (
        _document_digest(sampling_document) != candidate.sampling_evidence_id
        or _document_digest(replay_document) != candidate.reference_replay_id
        or replay_document.get("sampling_evidence_id") != candidate.sampling_evidence_id
        or filter_evidence.candidate_id != candidate.candidate_id
    ):
        raise _artifact("task_pack_evidence_mismatch", "trusted Task evidence identity mismatch")
    expected_public = PublicTaskView(
        task_pack_id,
        candidate.candidate_id,
        candidate.release_id,
        candidate.instruction,
        candidate.final_answer_schema,
    )
    if public != expected_public:
        raise _artifact("task_pack_public_mismatch", "public Task view is not derived from truth")
    return TaskPackArtifact(
        resolved,
        task_pack_id,
        public,
        candidate,
        filter_evidence,
        _copy_object(trusted),
    )


def task_filter_evidence_from_document(document: Any) -> TaskFilterEvidence:
    value = _exact(
        document,
        {
            "format",
            "candidate_id",
            "required_runs",
            "minimum_passes",
            "pass_count",
            "admitted",
            "runs",
            "infrastructure_retries",
        },
        "TaskFilterEvidence",
    )
    if (
        value["format"] != FILTER_EVIDENCE_FORMAT
        or value["required_runs"] != FILTER_RUNS
        or value["minimum_passes"] != MINIMUM_PASSES
        or not isinstance(value["runs"], list)
        or not isinstance(value["infrastructure_retries"], list)
    ):
        raise ValueError("TaskFilterEvidence contract mismatch")
    evidence = TaskFilterEvidence(
        cast(str, value["candidate_id"]),
        tuple(_filter_run_from_document(item) for item in value["runs"]),
        tuple(_retry_from_document(item) for item in value["infrastructure_retries"]),
    )
    if value["pass_count"] != evidence.pass_count or value["admitted"] is not evidence.admitted:
        raise ValueError("TaskFilterEvidence derived verdict mismatch")
    return evidence


def _filter_attempt(
    prepared: PreparedTaskEnvironment,
    candidate: CandidateTask,
    *,
    instance: Path,
    run_index: int,
    attempt_index: int,
    driver_factory: PolicyDriverFactory,
    prior_drivers: list[PolicyDriver],
) -> tuple[PolicyFilterRun | None, EpisodeDefect | None]:
    if instance.exists() or instance.is_symlink():
        raise TaskAdmissionFailure(
            "FrameworkDefect", "filter_instance_not_fresh", "filter instance must be new"
        )
    try:
        with prepared.open(instance) as session:
            reset = session.actor.reset(candidate.reset_start)
            before = prepared.read_state(instance)
            materialization_id = _session_materialization_id(session)
            driver = driver_factory(run_index, attempt_index)
            if any(driver is prior for prior in prior_drivers):
                raise TaskAdmissionFailure(
                    "FrameworkDefect",
                    "filter_policy_driver_reused",
                    "each filter attempt requires an independent policy driver",
                )
            prior_drivers.append(driver)
            capture = capture_public_episode(
                actor=session.actor,
                instruction=candidate.instruction,
                reset_observation=reset,
                answer_schema=candidate.final_answer_schema,
                policy_driver=driver,
            )
            after = prepared.read_state(instance)
    except TaskAdmissionFailure:
        raise
    except Exception as exc:
        kind: TaskAdmissionFailureKind = (
            "InfrastructureFailure"
            if getattr(exc, "kind", None) == "InfrastructureFailure"
            else "EnvironmentDefect"
        )
        raise TaskAdmissionFailure(
            kind,
            "filter_materialization_failed",
            str(exc),
            original_code=type(exc).__name__,
        ) from exc
    if capture.defect is not None:
        return None, capture.defect
    if not _same(reset, candidate.goal_truth.expected_reset) or not _same(
        before, candidate.goal_truth.expected_before
    ):
        raise TaskAdmissionFailure(
            "EnvironmentDefect",
            "filter_start_mismatch",
            "fresh filter materialization did not reproduce Candidate Start",
        )
    completion = capture.completion
    if completion is None:
        raise TaskAdmissionFailure(
            "FrameworkDefect", "filter_completion_missing", "valid capture omitted completion"
        )
    trace = evaluation_trace_from_capture(capture)
    failure_codes: list[str] = []
    try:
        origins = derive_argument_origins(
            trace,
            reset=reset,
            instruction=candidate.instruction,
        )
    except CandidateMaterializationFailure as exc:
        if exc.code not in {"argument_source_unresolved", "argument_literal_not_explicit"}:
            raise TaskAdmissionFailure("FrameworkDefect", exc.code, str(exc)) from exc
        origins = ()
        failure_codes.append(exc.code)
    final_answer = completion.final_answer
    if completion.terminal_kind != "completed":
        failure_codes.append(cast(str, completion.terminal_code))
    try:
        evaluation = evaluate_goal(
            candidate.goal_truth,
            EvaluationContext(
                reset,
                before,
                after,
                trace,
                final_answer or {},
            ),
        )
    except Exception as exc:
        raise TaskAdmissionFailure(
            "FrameworkDefect",
            "filter_evaluator_failed",
            str(exc),
            original_code=type(exc).__name__,
        ) from exc
    return (
        PolicyFilterRun(
            run_index,
            materialization_id,
            driver.policy_spec.policy_id,
            reset,
            before,
            after,
            trace,
            final_answer,
            completion.terminal_code,
            origins,
            evaluation,
            tuple(dict.fromkeys(failure_codes)),
            len(capture.turns),
            tuple(turn.usage for turn in capture.turns),
        ),
        None,
    )


def evaluation_trace_from_capture(capture: PublicEpisodeCapture) -> tuple[TraceEvent, ...]:
    """Project validated dispatched public calls onto the common evaluator trace."""

    calls = (
        call
        for turn in capture.turns
        for call in turn.calls
        if call.dispatch_status == "dispatched"
    )
    return tuple(
        TraceEvent(
            index,
            cast(str, call.tool_name),
            cast(JSONObject, call.parsed_arguments),
            cast(JSONObject, call.observation),
        )
        for index, call in enumerate(calls, 1)
    )


def _responses_driver_factory(
    route: AgentRoute, *, client_factory: ClientFactory | None
) -> PolicyDriverFactory:
    def create(_run_index: int, _attempt_index: int) -> PolicyDriver:
        return ResponsesPolicyDriver.from_route(route, client_factory=client_factory)

    return create


def _defect_failure(defect: EpisodeDefect) -> TaskAdmissionFailure:
    kind: TaskAdmissionFailureKind
    if defect.owner == "environment":
        kind = "EnvironmentDefect"
    elif defect.owner in {"provider", "infrastructure"}:
        kind = "InfrastructureFailure"
    elif defect.owner == "task_artifact":
        kind = "TaskArtifactDefect"
    else:
        kind = "FrameworkDefect"
    return TaskAdmissionFailure(kind, defect.code, "filter attempt produced a non-policy defect")


def _session_materialization_id(session: Any) -> str:
    identity = getattr(session, "identity", None)
    value = getattr(identity, "materialization_id", None)
    try:
        return _digest_value(value, "materialization_id")
    except ValueError as exc:
        raise TaskAdmissionFailure(
            "FrameworkDefect",
            "filter_materialization_identity_missing",
            "prepared session must expose a materialization_id",
        ) from exc


def _filter_run_from_document(document: Any) -> PolicyFilterRun:
    value = _exact(
        document,
        {
            "run_index",
            "materialization_id",
            "policy_id",
            "reset_observation",
            "before_state",
            "after_state",
            "trace",
            "final_answer",
            "terminal_code",
            "argument_origins",
            "evaluation",
            "policy_failure_codes",
            "failure_owner",
            "provider_turns",
            "usage",
        },
        "PolicyFilterRun",
    )
    trace_document = value["trace"]
    origins_document = value["argument_origins"]
    failure_codes_document = value["policy_failure_codes"]
    usage_document = value["usage"]
    for name, item in (
        ("trace", trace_document),
        ("argument_origins", origins_document),
        ("policy_failure_codes", failure_codes_document),
        ("usage", usage_document),
    ):
        if not isinstance(item, list):
            raise ValueError(f"PolicyFilterRun {name} must be an array")
    assert isinstance(trace_document, list)
    assert isinstance(origins_document, list)
    assert isinstance(failure_codes_document, list)
    assert isinstance(usage_document, list)
    run = PolicyFilterRun(
        cast(int, value["run_index"]),
        cast(str, value["materialization_id"]),
        cast(str, value["policy_id"]),
        value["reset_observation"],
        value["before_state"],
        value["after_state"],
        tuple(_trace_event_from_document(item) for item in trace_document),
        cast(JSONObject | None, value["final_answer"]),
        cast(str | None, value["terminal_code"]),
        tuple(argument_origin_from_document(item) for item in origins_document),
        _evaluation_from_document(value["evaluation"]),
        tuple(cast(list[str], failure_codes_document)),
        cast(int, value["provider_turns"]),
        tuple(cast(list[JSONObject | None], usage_document)),
    )
    if value["failure_owner"] != run.failure_owner:
        raise ValueError("PolicyFilterRun failure owner mismatch")
    return run


def _retry_from_document(document: Any) -> InfrastructureRetry:
    value = _exact(document, {"run_index", "attempt_index", "owner", "code"}, "InfrastructureRetry")
    return InfrastructureRetry(
        cast(int, value["run_index"]),
        cast(int, value["attempt_index"]),
        cast(RetryOwner, value["owner"]),
        cast(str, value["code"]),
    )


def _trace_event_from_document(document: Any) -> TraceEvent:
    value = _exact(document, {"seq", "tool_name", "arguments", "observation"}, "TraceEvent")
    return TraceEvent(
        cast(int, value["seq"]),
        cast(str, value["tool_name"]),
        cast(JSONObject, value["arguments"]),
        cast(JSONObject, value["observation"]),
    )


def _evaluation_from_document(document: Any) -> EvaluationResult:
    value = _exact(
        document,
        {
            "passed",
            "reset",
            "before_state",
            "after_state",
            "answer_schema",
            "answer",
            "goal",
            "checked",
            "reason_codes",
        },
        "EvaluationResult",
    )
    booleans = (
        "passed",
        "reset",
        "before_state",
        "after_state",
        "answer_schema",
        "answer",
        "goal",
    )
    if any(type(value[name]) is not bool for name in booleans):
        raise ValueError("EvaluationResult flags must be booleans")
    if not isinstance(value["checked"], list) or not isinstance(value["reason_codes"], list):
        raise ValueError("EvaluationResult codes must be arrays")
    checked = tuple(cast(list[str], value["checked"]))
    reasons = tuple(cast(list[str], value["reason_codes"]))
    _unique_texts(checked, "evaluation checked")
    _unique_texts(reasons, "evaluation reason_codes", allow_empty=True)
    return EvaluationResult(
        cast(bool, value["passed"]),
        cast(bool, value["reset"]),
        cast(bool, value["before_state"]),
        cast(bool, value["after_state"]),
        cast(bool, value["answer_schema"]),
        cast(bool, value["answer"]),
        cast(bool, value["goal"]),
        checked,
        reasons,
    )


def _public_view_from_document(document: Any) -> PublicTaskView:
    value = _exact(
        document,
        {
            "format",
            "task_pack_id",
            "task_id",
            "release_id",
            "instruction",
            "final_answer_schema",
        },
        "PublicTaskView",
    )
    if value["format"] != PUBLIC_TASK_FORMAT:
        raise _artifact("public_task_format_invalid", "public Task format mismatch")
    try:
        return PublicTaskView(
            cast(str, value["task_pack_id"]),
            cast(str, value["task_id"]),
            cast(str, value["release_id"]),
            cast(str, value["instruction"]),
            cast(JSONObject, value["final_answer_schema"]),
        )
    except ValueError as exc:
        raise _artifact("public_task_invalid", str(exc)) from exc


def _fresh_root(path: Path) -> Path:
    selected = Path(path)
    if selected.is_symlink() or (
        selected.exists() and (not selected.is_dir() or any(selected.iterdir()))
    ):
        raise TaskAdmissionFailure(
            "FrameworkDefect",
            "filter_root_not_fresh",
            "filter instance root must be absent or empty",
        )
    return selected.resolve()


def _read_canonical(path: Path, role: str) -> JSONObject:
    try:
        payload = path.read_bytes()
        document = json.loads(payload)
        if not is_json_object(document) or payload != canonical_bytes(document):
            raise ValueError(f"{role} must be a canonical JSON object")
        return cast(JSONObject, document)
    except TaskAdmissionFailure:
        raise
    except Exception as exc:
        raise _artifact("task_pack_document_invalid", str(exc)) from exc


def _write(path: Path, payload: bytes) -> None:
    path.write_bytes(payload)
    path.chmod(0o644)


def _artifact(code: str, message: str) -> TaskAdmissionFailure:
    return TaskAdmissionFailure("TaskArtifactDefect", code, message)


def _exact(document: Any, keys: set[str], role: str) -> JSONObject:
    if not is_json_object(document) or set(document) != keys:
        actual = sorted(document) if isinstance(document, dict) else type(document).__name__
        raise ValueError(f"{role} has invalid fields: expected {sorted(keys)}, got {actual}")
    return cast(JSONObject, document)


def _positive(value: Any, role: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{role} must be a positive integer")


def _text(value: Any, role: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{role} must be non-empty text")


def _unique_texts(values: tuple[str, ...], role: str, *, allow_empty: bool = False) -> None:
    if any(not isinstance(value, str) or not value for value in values):
        raise ValueError(f"{role} must contain non-empty strings")
    if not allow_empty and not values:
        raise ValueError(f"{role} must not be empty")
    if len(values) != len(set(values)):
        raise ValueError(f"{role} must be unique")


def _digest(value: str, role: str) -> None:
    _digest_value(value, role)


def _digest_value(value: Any, role: str) -> str:
    try:
        return _hex_digest(value, field=role)
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


def _copy_optional_object(value: JSONObject | None) -> JSONObject | None:
    return None if value is None else _copy_object(value)


__all__ = [
    "FILTER_EVIDENCE_FORMAT",
    "FILTER_RUNS",
    "MINIMUM_PASSES",
    "PUBLIC_TASK_FORMAT",
    "TASK_PACK_FORMAT",
    "InfrastructureRetry",
    "PolicyDriverFactory",
    "PolicyFilterRun",
    "PublicTaskView",
    "TaskAdmissionFailure",
    "TaskAdmissionFailureKind",
    "TaskFilterEvidence",
    "TaskPackArtifact",
    "evaluation_trace_from_capture",
    "filter_candidate",
    "load_task_pack",
    "seal_task_pack",
    "task_filter_evidence_from_document",
]
