"""Checkpoint C1: Host materialization and fresh reference replay."""

from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_env_foundry.environment import success_observation
from agent_env_foundry.task_candidate import (
    CandidateMaterializationFailure,
    candidate_task_from_document,
    materialize_candidate,
)
from agent_env_foundry.task_draft import (
    AnswerProjection,
    AtomDraft,
    IfDraft,
    PublicValueRef,
    SamplingTarget,
    TaskDraft,
)
from agent_env_foundry.task_goal import AtomGoal, TraceEvent
from agent_env_foundry.task_proposal import (
    SampledTaskDraft,
    TaskSamplingEvidence,
)

TOOLS = (
    {
        "name": "inspect",
        "description": "Inspect one counter.",
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
        "description": "Increment one counter.",
        "input_schema": {
            "type": "object",
            "properties": {
                "counter_id": {"type": "string"},
                "amount": {"type": "integer", "minimum": 1},
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
RESET_SCHEMA = {
    "type": "object",
    "properties": {
        "counter_id": {"type": "string"},
        "count": {"type": "integer"},
    },
    "required": ["counter_id", "count"],
    "additionalProperties": False,
}
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


class Actor:
    def __init__(self, *, drift: bool = False) -> None:
        self.count = 0
        self.drift = drift

    def reset(self, start=None):
        self.count = 0
        return {"counter_id": "counter-main", "count": 0}

    def tools(self):
        return TOOLS

    def invoke(self, tool_name, arguments):
        if tool_name == "increment":
            self.count += arguments["amount"] + int(self.drift)
        return success_observation({"counter_id": arguments["counter_id"], "count": self.count})

    def close(self):
        return


class Prepared:
    def __init__(self, *, drift: bool = False) -> None:
        self.identity = SimpleNamespace(release_id="1" * 64)
        self.reset_observation_schema = RESET_SCHEMA
        self.actors: dict[Path, Actor] = {}
        self.drift = drift

    def open(self, instance: Path):
        root = Path(instance).resolve()
        actor = self.actors.setdefault(root, Actor(drift=self.drift))
        return nullcontext(SimpleNamespace(actor=actor))

    def read_state(self, instance: Path):
        actor = self.actors[Path(instance).resolve()]
        return {"counters": [{"id": "counter-main", "count": actor.count}]}


def _sample(
    *,
    instruction: str = "Increase counter-main by exactly 2 and report its result.",
    trace: tuple[TraceEvent, ...] | None = None,
    objective_step: int = 2,
    after_count: int = 2,
) -> tuple[SamplingTarget, SampledTaskDraft]:
    target = SamplingTarget("atom", ("increment",), "transition")
    events = trace or (
        TraceEvent(
            1,
            "inspect",
            {"counter_id": "counter-main"},
            success_observation({"counter_id": "counter-main", "count": 0}),
        ),
        TraceEvent(
            2,
            "increment",
            {"counter_id": "counter-main", "amount": 2},
            success_observation({"counter_id": "counter-main", "count": after_count}),
        ),
        TraceEvent(
            3,
            "inspect",
            {"counter_id": "counter-main"},
            success_observation({"counter_id": "counter-main", "count": after_count}),
        ),
    )
    draft = TaskDraft(
        target.target_id,
        instruction,
        AtomDraft(objective_step),
        AnswerProjection.from_object(
            {
                "result": AnswerProjection.from_source(
                    PublicValueRef.observation(len(events), "/data")
                )
            }
        ),
    )
    evidence = TaskSamplingEvidence(
        "1" * 64,
        target.target_id,
        None,
        {"counter_id": "counter-main", "count": 0},
        {"counters": [{"id": "counter-main", "count": 0}]},
        {"counters": [{"id": "counter-main", "count": after_count}]},
        events,
        {"result": {"counter_id": "counter-main", "count": after_count}},
        ANSWER_SCHEMA,
    )
    return target, SampledTaskDraft(draft, evidence, 3, (None, None, None))


def test_host_materializes_candidate_only_after_public_fresh_replay(tmp_path) -> None:
    target, sampled = _sample()

    result = materialize_candidate(
        Prepared(),
        sampled=sampled,
        target=target,
        builder_projection_digest="2" * 64,
        replay_instance=tmp_path / "replay",
    )

    assert isinstance(result.candidate.goal_truth.goal, AtomGoal)
    assert result.candidate.goal_truth.goal.tool_name == "increment"
    assert result.replay.evaluation.passed
    assert result.replay.before_state == sampled.evidence.before_state
    assert result.replay.after_state == sampled.evidence.after_state
    assert len(result.argument_origins) == 4
    assert candidate_task_from_document(result.candidate.to_document()) == result.candidate
    document = result.candidate.to_document()
    assert all(word not in str(document).lower() for word in ("checker", "tasksemantics"))
    with pytest.raises(ValueError, match="invalid fields"):
        candidate_task_from_document({**document, "checker": {}})


def test_hidden_argument_not_in_task_reset_or_prior_observation_is_rejected(tmp_path) -> None:
    events = (
        TraceEvent(
            1,
            "increment",
            {"counter_id": "SECRET", "amount": 2},
            success_observation({"counter_id": "SECRET", "count": 2}),
        ),
    )
    target, sampled = _sample(
        instruction="Increase the selected counter by exactly 2.",
        trace=events,
        objective_step=1,
    )

    with pytest.raises(CandidateMaterializationFailure) as caught:
        materialize_candidate(
            Prepared(),
            sampled=sampled,
            target=target,
            builder_projection_digest="2" * 64,
            replay_instance=tmp_path / "replay",
        )

    assert caught.value.code == "argument_source_unresolved"


def test_unexplained_sampling_mutation_is_not_folded_into_goal(tmp_path) -> None:
    events = (
        TraceEvent(
            1,
            "increment",
            {"counter_id": "counter-main", "amount": 1},
            success_observation({"counter_id": "counter-main", "count": 1}),
        ),
        TraceEvent(
            2,
            "increment",
            {"counter_id": "counter-main", "amount": 1},
            success_observation({"counter_id": "counter-main", "count": 2}),
        ),
    )
    target, sampled = _sample(
        instruction="Increase counter-main by exactly 1 and report the result.",
        trace=events,
        objective_step=2,
    )

    with pytest.raises(CandidateMaterializationFailure) as caught:
        materialize_candidate(
            Prepared(),
            sampled=sampled,
            target=target,
            builder_projection_digest="2" * 64,
            replay_instance=tmp_path / "replay",
        )

    assert caught.value.code == "unexplained_sampling_mutation"


def test_replay_observation_drift_is_an_environment_failure(tmp_path) -> None:
    target, sampled = _sample()

    with pytest.raises(CandidateMaterializationFailure) as caught:
        materialize_candidate(
            Prepared(drift=True),
            sampled=sampled,
            target=target,
            builder_projection_digest="2" * 64,
            replay_instance=tmp_path / "replay",
        )

    assert caught.value.kind == "EnvironmentDefect"
    assert caught.value.code == "reference_replay_observation_mismatch"


def test_replay_infrastructure_failure_keeps_its_owner(tmp_path) -> None:
    class InfrastructureUnavailable(RuntimeError):
        kind = "InfrastructureFailure"

    class UnavailablePrepared(Prepared):
        def open(self, instance: Path):
            raise InfrastructureUnavailable("runtime unavailable")

    target, sampled = _sample()
    with pytest.raises(CandidateMaterializationFailure) as caught:
        materialize_candidate(
            UnavailablePrepared(),
            sampled=sampled,
            target=target,
            builder_projection_digest="2" * 64,
            replay_instance=tmp_path / "replay",
        )

    assert caught.value.kind == "InfrastructureFailure"
    assert caught.value.code == "reference_replay_failed"


def test_if_condition_query_cannot_be_its_only_branch_objective(tmp_path) -> None:
    target = SamplingTarget("if", ("inspect",), "query")
    trace = (
        TraceEvent(
            1,
            "inspect",
            {"counter_id": "counter-main"},
            success_observation({"counter_id": "counter-main", "count": 0}),
        ),
        TraceEvent(
            2,
            "inspect",
            {"counter_id": "counter-main"},
            success_observation({"counter_id": "counter-main", "count": 0}),
        ),
    )
    draft = TaskDraft(
        target.target_id,
        "Inspect counter-main. If its count is zero, retrieve and report the same counter.",
        IfDraft(
            PublicValueRef.observation(1, "/data/count"),
            "eq",
            0,
            AtomDraft(2),
            None,
        ),
        AnswerProjection.from_object(
            {"count": AnswerProjection.from_source(PublicValueRef.observation(2, "/data/count"))}
        ),
    )
    evidence = TaskSamplingEvidence(
        "1" * 64,
        target.target_id,
        None,
        {"counter_id": "counter-main", "count": 0},
        {"counters": [{"id": "counter-main", "count": 0}]},
        {"counters": [{"id": "counter-main", "count": 0}]},
        trace,
        {"count": 0},
        {
            "type": "object",
            "properties": {"count": {"type": "integer"}},
            "required": ["count"],
            "additionalProperties": False,
        },
    )
    sampled = SampledTaskDraft(draft, evidence, 3, (None, None, None))

    with pytest.raises(CandidateMaterializationFailure) as caught:
        materialize_candidate(
            Prepared(),
            sampled=sampled,
            target=target,
            builder_projection_digest="2" * 64,
            replay_instance=tmp_path / "replay",
        )

    assert caught.value.kind == "DraftRejected"
    assert caught.value.code == "if_branch_repeats_condition_query"
