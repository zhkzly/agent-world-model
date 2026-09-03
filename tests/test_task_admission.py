from __future__ import annotations

import hashlib
import json
import shutil
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_env_foundry.environment import success_observation
from agent_env_foundry.episodes import EpisodeDefect, PolicySpec, PublicEpisodeInput
from agent_env_foundry.public_agent import (
    PUBLIC_AGENT_PROMPT_DIGEST,
    DriverDecision,
)
from agent_env_foundry.task_admission import (
    TaskAdmissionFailure,
    filter_candidate,
    load_task_pack,
    seal_task_pack,
)
from agent_env_foundry.task_candidate import (
    ArgumentOrigin,
    CandidateTask,
    MaterializedCandidate,
    ReferenceReplay,
)
from agent_env_foundry.task_draft import PublicValueRef
from agent_env_foundry.task_goal import (
    AtomGoal,
    EvaluationContext,
    GoalTruth,
    TraceEvent,
    evaluate_goal,
)
from agent_env_foundry.task_proposal import TaskSamplingEvidence

RESET = {"counter_id": "counter-main", "count": 0}
BEFORE = {"counters": [{"id": "counter-main", "count": 0}]}
AFTER = {"counters": [{"id": "counter-main", "count": 2}]}
ANSWER = {"result": {"counter_id": "counter-main", "count": 2}}
ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "result": {
            "type": "object",
            "properties": {
                "counter_id": {"type": "string"},
                "count": {"type": "integer"},
            },
            "required": ["counter_id", "count"],
            "additionalProperties": False,
        }
    },
    "required": ["result"],
    "additionalProperties": False,
}
TOOLS = (
    {
        "name": "inspect",
        "description": "Inspect a public counter.",
        "input_schema": {
            "type": "object",
            "properties": {"counter_id": {"type": "string"}},
            "required": ["counter_id"],
            "additionalProperties": False,
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "counter_id": {"type": "string"},
                "count": {"type": "integer"},
            },
            "required": ["counter_id", "count"],
            "additionalProperties": False,
        },
    },
    {
        "name": "increment",
        "description": "Increase a public counter.",
        "input_schema": {
            "type": "object",
            "properties": {
                "counter_id": {"type": "string"},
                "amount": {"type": "integer"},
            },
            "required": ["counter_id", "amount"],
            "additionalProperties": False,
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "counter_id": {"type": "string"},
                "count": {"type": "integer"},
            },
            "required": ["counter_id", "count"],
            "additionalProperties": False,
        },
    },
)


class Actor:
    def __init__(self) -> None:
        self.count = 0

    def reset(self, start=None):
        del start
        self.count = 0
        return dict(RESET)

    def tools(self):
        return TOOLS

    def invoke(self, tool_name, arguments):
        if tool_name == "increment":
            self.count += arguments["amount"]
        return success_observation({"counter_id": arguments["counter_id"], "count": self.count})

    def close(self):
        return None


class Prepared:
    def __init__(self) -> None:
        self.identity = SimpleNamespace(release_id="1" * 64)
        self.actors: dict[Path, Actor] = {}
        self.opened: list[Path] = []

    def open(self, instance: Path):
        root = Path(instance).resolve()
        self.opened.append(root)
        actor = self.actors.setdefault(root, Actor())
        identity = SimpleNamespace(
            materialization_id=hashlib.sha256(str(root).encode()).hexdigest()
        )
        return nullcontext(SimpleNamespace(actor=actor, identity=identity))

    def read_state(self, instance: Path):
        actor = self.actors[Path(instance).resolve()]
        return {"counters": [{"id": "counter-main", "count": actor.count}]}


class ScriptedDriver:
    def __init__(self, decisions: list[DriverDecision], label: str) -> None:
        self._decisions = decisions
        self._spec = PolicySpec(
            "scripted-policy",
            "scripted",
            "1",
            f"test:{label}",
            PUBLIC_AGENT_PROMPT_DIGEST,
            4,
        )
        self.starts: list[PublicEpisodeInput] = []
        self.closed = 0

    @property
    def policy_spec(self) -> PolicySpec:
        return self._spec

    def start(self, public_input: PublicEpisodeInput) -> None:
        self.starts.append(public_input)

    def next_decision(self, prior_public_results):
        del prior_public_results
        return self._decisions.pop(0)

    def close(self) -> None:
        self.closed += 1


def _pass_driver(label: str) -> ScriptedDriver:
    return ScriptedDriver(
        [
            DriverDecision(
                calls=((f"{label}-1", "increment", '{"counter_id":"counter-main","amount":2}'),),
                usage={"input_tokens": 10, "output_tokens": 3},
            ),
            DriverDecision(
                calls=((f"{label}-2", "inspect", '{"counter_id":"counter-main"}'),),
                usage={"input_tokens": 20, "output_tokens": 3},
            ),
            DriverDecision(
                terminal_kind="final_answer",
                raw_public_terminal=json.dumps(ANSWER),
                usage={"input_tokens": 30, "output_tokens": 4},
            ),
        ],
        label,
    )


def _fail_driver(label: str) -> ScriptedDriver:
    return ScriptedDriver(
        [
            DriverDecision(calls=((f"{label}-1", "inspect", '{"counter_id":"counter-main"}'),)),
            DriverDecision(
                terminal_kind="final_answer",
                raw_public_terminal=json.dumps(
                    {"result": {"counter_id": "counter-main", "count": 0}}
                ),
            ),
        ],
        label,
    )


def _infrastructure_driver(label: str) -> ScriptedDriver:
    return ScriptedDriver(
        [
            DriverDecision(
                defect=EpisodeDefect("infrastructure", "provider_capacity", "provider_turn")
            )
        ],
        label,
    )


def _candidate() -> tuple[MaterializedCandidate, TaskSamplingEvidence]:
    trace = (
        TraceEvent(
            1,
            "increment",
            {"counter_id": "counter-main", "amount": 2},
            success_observation({"counter_id": "counter-main", "count": 2}),
        ),
        TraceEvent(
            2,
            "inspect",
            {"counter_id": "counter-main"},
            success_observation({"counter_id": "counter-main", "count": 2}),
        ),
    )
    truth = GoalTruth(
        AtomGoal("increment", {"counter_id": "counter-main", "amount": 2}, "transition"),
        RESET,
        BEFORE,
        AFTER,
        ANSWER,
        ANSWER_SCHEMA,
    )
    evaluation = evaluate_goal(truth, EvaluationContext(RESET, BEFORE, AFTER, trace, ANSWER))
    sampling = TaskSamplingEvidence(
        "1" * 64,
        "2" * 64,
        None,
        RESET,
        BEFORE,
        AFTER,
        trace,
        ANSWER,
        ANSWER_SCHEMA,
    )
    replay = ReferenceReplay(
        "1" * 64,
        sampling.evidence_id,
        RESET,
        BEFORE,
        AFTER,
        trace,
        ANSWER,
        (True, False),
        evaluation,
    )
    candidate = CandidateTask(
        "1" * 64,
        "4" * 64,
        None,
        "Increase counter-main by exactly 2 and report its resulting counter ID and count.",
        truth,
        sampling.evidence_id,
        replay.replay_id,
        "3" * 64,
    )
    origins = (
        ArgumentOrigin(1, "/counter_id", PublicValueRef.reset("/counter_id")),
        ArgumentOrigin(1, "/amount", PublicValueRef.task_literal(2)),
        ArgumentOrigin(2, "/counter_id", PublicValueRef.reset("/counter_id")),
    )
    return MaterializedCandidate(candidate, replay, origins), sampling


def _factory(outcomes: list[str], created: list[ScriptedDriver]):
    remaining = list(outcomes)

    def create(run_index: int, attempt_index: int):
        outcome = remaining.pop(0)
        label = f"run-{run_index}-attempt-{attempt_index}"
        driver = {
            "pass": _pass_driver,
            "fail": _fail_driver,
            "infra": _infrastructure_driver,
        }[outcome](label)
        created.append(driver)
        return driver

    return create


def test_exactly_five_valid_runs_and_two_passes_admit(tmp_path: Path) -> None:
    materialized, _sampling = _candidate()
    prepared = Prepared()
    drivers: list[ScriptedDriver] = []

    evidence = filter_candidate(
        prepared,
        materialized.candidate,
        instance_root=tmp_path / "filter",
        policy_driver_factory=_factory(["pass", "pass", "fail", "fail", "fail"], drivers),
    )

    assert evidence.admitted
    assert evidence.pass_count == 2
    assert len(evidence.runs) == 5
    assert [run.passed for run in evidence.runs] == [True, True, False, False, False]
    assert len({run.materialization_id for run in evidence.runs}) == 5
    assert len({id(driver) for driver in drivers}) == 5
    assert all(len(driver.starts) == 1 and driver.closed == 1 for driver in drivers)


def test_one_of_five_does_not_admit_or_seal(tmp_path: Path) -> None:
    materialized, sampling = _candidate()
    evidence = filter_candidate(
        Prepared(),
        materialized.candidate,
        instance_root=tmp_path / "filter",
        policy_driver_factory=_factory(["pass", "fail", "fail", "fail", "fail"], []),
    )

    assert not evidence.admitted
    assert evidence.pass_count == 1
    with pytest.raises(TaskAdmissionFailure) as caught:
        seal_task_pack(
            tmp_path / "pack",
            materialized=materialized,
            sampling_evidence=sampling,
            filter_evidence=evidence,
        )
    assert caught.value.kind == "PolicyRejected"
    assert caught.value.code == "candidate_below_pass_threshold"


def test_infrastructure_retry_is_not_counted_as_a_policy_run(tmp_path: Path) -> None:
    materialized, _sampling = _candidate()
    prepared = Prepared()
    drivers: list[ScriptedDriver] = []
    evidence = filter_candidate(
        prepared,
        materialized.candidate,
        instance_root=tmp_path / "filter",
        policy_driver_factory=_factory(["infra", "pass", "pass", "fail", "fail", "fail"], drivers),
        infrastructure_retry_limit=1,
    )

    assert evidence.admitted
    assert len(evidence.runs) == 5
    assert len(evidence.infrastructure_retries) == 1
    assert evidence.infrastructure_retries[0].owner == "infrastructure"
    assert len(prepared.opened) == 6


def test_exhausted_infrastructure_budget_never_becomes_policy_failure(tmp_path: Path) -> None:
    materialized, _sampling = _candidate()
    with pytest.raises(TaskAdmissionFailure) as caught:
        filter_candidate(
            Prepared(),
            materialized.candidate,
            instance_root=tmp_path / "filter",
            policy_driver_factory=_factory(["infra", "infra"], []),
            infrastructure_retry_limit=1,
        )

    assert caught.value.kind == "InfrastructureFailure"
    assert caught.value.code == "filter_infrastructure_retries_exhausted"


def test_task_pack_cold_reads_after_relocation_without_public_leakage(tmp_path: Path) -> None:
    materialized, sampling = _candidate()
    evidence = filter_candidate(
        Prepared(),
        materialized.candidate,
        instance_root=tmp_path / "filter",
        policy_driver_factory=_factory(["pass", "pass", "fail", "fail", "fail"], []),
    )
    written = seal_task_pack(
        tmp_path / "pack",
        materialized=materialized,
        sampling_evidence=sampling,
        filter_evidence=evidence,
    )
    shutil.copytree(written.root, tmp_path / "relocated")

    loaded = load_task_pack(tmp_path / "relocated")

    assert loaded.task_pack_id == written.task_pack_id
    assert loaded.candidate == materialized.candidate
    assert loaded.filter_evidence == evidence
    public = loaded.public_view.to_document()
    assert set(public) == {
        "format",
        "task_pack_id",
        "task_id",
        "release_id",
        "instruction",
        "final_answer_schema",
    }
    assert all(
        word not in json.dumps(public, sort_keys=True).lower()
        for word in ("goal_truth", "trace", "sampling", "expected_answer", "checker")
    )


def test_task_pack_tampering_fails_closed(tmp_path: Path) -> None:
    materialized, sampling = _candidate()
    evidence = filter_candidate(
        Prepared(),
        materialized.candidate,
        instance_root=tmp_path / "filter",
        policy_driver_factory=_factory(["pass", "pass", "fail", "fail", "fail"], []),
    )
    artifact = seal_task_pack(
        tmp_path / "pack",
        materialized=materialized,
        sampling_evidence=sampling,
        filter_evidence=evidence,
    )
    trusted = artifact.root / "trusted" / "evidence.json"
    payload = trusted.read_text()
    assert "after_state_mismatch" in payload
    trusted.write_text(payload.replace("after_state_mismatch", "forged_reason", 1))

    with pytest.raises(TaskAdmissionFailure) as caught:
        load_task_pack(artifact.root)
    assert caught.value.kind == "TaskArtifactDefect"
    assert caught.value.code == "task_pack_digest_mismatch"
