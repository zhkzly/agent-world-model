from __future__ import annotations

import hashlib
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Literal, cast

import pytest

import agent_env_foundry.episode_runtime as runtime_module
from agent_env_foundry.environment import JSONObject
from agent_env_foundry.episode_runtime import run_task_episode
from agent_env_foundry.episodes import EpisodeDefect, PolicySpec, RewardOutcome
from agent_env_foundry.foreach_foundry import ForEachTask
from agent_env_foundry.if_foundry import IfTask
from agent_env_foundry.preparation import PreparationExecutionError
from agent_env_foundry.public_agent import (
    PUBLIC_AGENT_PROMPT_DIGEST,
    DriverDecision,
    PublicEpisodeInput,
)
from agent_env_foundry.release import canonical_bytes
from agent_env_foundry.semantics import (
    AtomCheckResult,
    BindingCandidate,
    ConditionCheckResult,
    StartCase,
)
from agent_env_foundry.task_foundry import AtomTask, TaskFoundryError

RELEASE_ID = "a" * 64
ACTING_ID = "d" * 64
REOPENED_ID = "e" * 64
ANSWER_SCHEMA: JSONObject = {
    "type": "object",
    "properties": {},
    "required": [],
    "additionalProperties": False,
}
TOOL_SPEC = {
    "name": "set_value",
    "description": "Set the public value.",
    "input_schema": {
        "type": "object",
        "properties": {"value": {"type": "integer"}},
        "required": ["value"],
        "additionalProperties": False,
    },
    "output_schema": {
        "type": "object",
        "properties": {"value": {"type": "integer"}},
        "required": ["value"],
        "additionalProperties": False,
    },
}


def _sha(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _instruction_digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _atom(*, checker_digest: str | None = None) -> AtomTask:
    instruction = "Set the public value to one."
    start = StartCase("start-1", None, ())
    digest = checker_digest or _sha(
        {
            "release_id": RELEASE_ID,
            "start_case_id": start.case_id,
            "capability_id": "cap-1",
            "semantic_key": "item-1",
            "answer_schema": ANSWER_SCHEMA,
        }
    )
    return AtomTask(
        RELEASE_ID,
        start,
        "cap-1",
        "item-1",
        {},
        digest,
        instruction,
        _instruction_digest(instruction),
        ANSWER_SCHEMA,
    )


def _foreach() -> ForEachTask:
    instruction = "Set every selected public value to one."
    start = StartCase("start-1", None, ())
    member_schema = ANSWER_SCHEMA
    answer_schema: JSONObject = {
        "type": "object",
        "properties": {
            "results": {
                "type": "array",
                "items": member_schema,
                "minItems": 2,
                "maxItems": 2,
            }
        },
        "required": ["results"],
        "additionalProperties": False,
    }
    return ForEachTask(
        RELEASE_ID,
        start,
        "cap-1",
        ("item-1", "item-2"),
        ({}, {}),
        "selector-1",
        _sha(
            {
                "release_id": RELEASE_ID,
                "start_case_id": start.case_id,
                "capability_id": "cap-1",
                "semantic_keys": ["item-1", "item-2"],
                "selector_id": "selector-1",
                "member_answer_schema": member_schema,
            }
        ),
        instruction,
        _instruction_digest(instruction),
        member_schema,
        answer_schema,
    )


def _if(branch: AtomTask, *, public_descriptor: JSONObject | None = None) -> IfTask:
    instruction = "If the public condition holds, set the value to one."
    return IfTask(
        RELEASE_ID,
        branch.start_case,
        "condition-1",
        branch.semantic_key,
        branch.public_descriptor if public_descriptor is None else public_descriptor,
        branch.capability_id,
        "cap-false",
        "true",
        branch.task_id,
        _sha(
            {
                "release_id": RELEASE_ID,
                "start_case_id": branch.start_case.case_id,
                "condition_id": "condition-1",
                "semantic_key": branch.semantic_key,
                "true_capability_id": branch.capability_id,
                "false_capability_id": "cap-false",
                "expected_branch": "true",
                "branch_task_id": branch.task_id,
                "answer_schema": branch.answer_schema,
            }
        ),
        instruction,
        _instruction_digest(instruction),
        branch.answer_schema,
    )


def _pack_document(
    kind: Literal["atom", "foreach", "if"],
    *,
    bad_checker: bool = False,
    if_public_descriptor: JSONObject | None = None,
):
    atom = _atom(checker_digest="0" * 64 if bad_checker else None)
    if kind == "atom":
        task, pack_format = atom, "atom-task-pack/4"
        admission: JSONObject = {"task_id": atom.task_id}
    elif kind == "foreach":
        task, pack_format = _foreach(), "foreach-task-pack/3"
        admission = {"task_id": task.task_id}
    else:
        task, pack_format = (
            _if(atom, public_descriptor=if_public_descriptor),
            "if-task-pack/3",
        )
        branch_preimage: JSONObject = {
            "format": "atom-task-pack/4",
            "task": atom.to_document(),
            "admission": {"task_id": atom.task_id},
        }
        branch_pack = {**branch_preimage, "task_pack_id": _sha(branch_preimage)}
        plan_preimage: JSONObject = {
            "format": "if-admission-plan/2",
            "task_id": task.task_id,
        }
        report_preimage: JSONObject = {
            "format": "if-admission-report/4",
            "task_id": task.task_id,
            "admission_plan": {**plan_preimage, "plan_id": _sha(plan_preimage)},
            "witnesses": [],
            "branch_task_pack": branch_pack,
        }
        admission = {**report_preimage, "report_id": _sha(report_preimage)}
    preimage: JSONObject = {
        "format": pack_format,
        "task": task.to_document(),
        "admission": admission,
    }
    return {**preimage, "task_pack_id": _sha(preimage)}, task


def _write_pack(tmp_path: Path, kind: Literal["atom", "foreach", "if"], **kwargs):
    document, task = _pack_document(kind, **kwargs)
    path = tmp_path / f"{kind}.json"
    path.write_bytes(canonical_bytes(document))
    return path, cast(str, document["task_pack_id"]), task


class Driver:
    def __init__(self, decisions: list[DriverDecision]) -> None:
        self.decisions = decisions
        self.started: list[PublicEpisodeInput] = []
        self.close_count = 0
        self.spec_reads = 0
        self._spec = PolicySpec(
            "scripted-policy",
            "scripted",
            "1",
            "test:scripted",
            PUBLIC_AGENT_PROMPT_DIGEST,
            4,
        )

    @property
    def policy_spec(self) -> PolicySpec:
        self.spec_reads += 1
        return self._spec

    def start(self, public_input: PublicEpisodeInput) -> None:
        self.started.append(public_input)

    def next_decision(self, _results):
        return self.decisions.pop(0)

    def close(self) -> None:
        self.close_count += 1


class Actor:
    def __init__(self, state: dict[str, Any], events: list[str], label: str, mode: str) -> None:
        self.state, self.events, self.label, self.mode = state, events, label, mode

    def reset(self, _start):
        self.events.append(f"{self.label}:reset")
        self.state["reset_count"] += 1
        self.state["value"] = 0
        return {"value": 0}

    def tools(self):
        self.events.append(f"{self.label}:tools")
        return (TOOL_SPEC,)

    def invoke(self, _tool_name, arguments):
        if self.mode == "environment":
            raise PreparationExecutionError(
                "EnvironmentDefect", "actor_mutation_failed", "actor failed"
            )
        self.state["value"] = arguments["value"]
        return {"ok": True, "data": {"value": self.state["value"]}, "error": None}

    def close(self) -> None:
        return None


class Trusted:
    def __init__(self, state: dict[str, Any], label: str, members: int, mode: str) -> None:
        self.state, self.label, self.members, self.mode = state, label, members, mode
        self.inspect_count = 0

    def inspect(self, _path: Path):
        self.inspect_count += 1
        if (
            self.label == "acting"
            and self.mode == "unattributed_pre_close"
            and self.inspect_count == 2
        ):
            raise RuntimeError("unexpected pre-close failure")
        if self.label == "reopened" and self.mode == "semantics":
            raise PreparationExecutionError(
                "SemanticsDefect", "post_reopen_inspect_failed", "inspect failed"
            )
        return {"value": self.state["value"]}

    def capabilities(self):
        if self.mode == "catalog_must_not_be_read":
            raise AssertionError("this Task kind does not consume the capability catalog")
        if self.mode == "preflight":
            raise PreparationExecutionError(
                "SemanticsDefect", "preflight_failed", "preflight failed"
            )
        return (SimpleNamespace(capability_id="cap-1"),)

    def enumerate_bindings(self, _capability_id, _facts):
        return tuple(
            BindingCandidate(
                f"item-{index}",
                True,
                (),
                {"item": index},
                {},
                {},
                (),
            )
            for index in range(1, self.members + 1)
        )

    def evaluate_condition(self, _request):
        return ConditionCheckResult("true", {}, ())

    def evaluate_atom(self, _request):
        if self.mode == "verifier":
            raise PreparationExecutionError(
                "VerifierDefect", "checker_runtime_failed", "checker failed"
            )
        satisfied = self.state["value"] == 1
        return AtomCheckResult(
            False,
            satisfied,
            satisfied,
            True,
            True,
            True,
            {},
            () if satisfied else ("value_not_one",),
        )

    def close(self) -> None:
        return None


class Session:
    def __init__(
        self,
        session_id: str,
        state: dict[str, Any],
        events: list[str],
        label: str,
        members: int,
        mode: str,
    ) -> None:
        self.identity = SimpleNamespace(materialization_id=session_id)
        self.actor = Actor(state, events, label, mode)
        self.trusted = Trusted(state, label, members, mode)
        self.events, self.label = events, label

    def close(self) -> None:
        self.events.append(f"{self.label}:close")


class Prepared:
    def __init__(self, *, members: int = 1, mode: str = "healthy") -> None:
        self.identity = SimpleNamespace(release_id=RELEASE_ID)
        self.members, self.mode = members, mode
        self.state = {"value": 0, "reset_count": 0}
        self.events: list[str] = []
        self.paths: list[Path] = []

    def open(self, path: Path):
        self.paths.append(path)
        label = "acting" if len(self.paths) == 1 else "reopened"
        session_id = ACTING_ID if label == "acting" or self.mode == "same_session" else REOPENED_ID
        self.events.append(f"{label}:open")
        return Session(
            session_id,
            self.state,
            self.events,
            label,
            self.members,
            self.mode,
        )


def _completed(value: int, answer: str) -> list[DriverDecision]:
    return [
        DriverDecision(calls=(("call-1", "set_value", f'{{"value":{value}}}'),)),
        DriverDecision(terminal_kind="final_answer", raw_public_terminal=answer),
    ]


@pytest.mark.parametrize(
    ("kind", "answer", "members"),
    (("atom", "{}", 1), ("foreach", '{"results":[{},{}]}', 2), ("if", "{}", 1)),
)
def test_all_current_task_kinds_use_one_physical_lifecycle(
    tmp_path: Path,
    kind: Literal["atom", "foreach", "if"],
    answer: str,
    members: int,
) -> None:
    pack, pack_id, _task = _write_pack(tmp_path, kind)
    prepared = Prepared(members=members)
    driver = Driver(_completed(1, answer))
    instance = tmp_path / "native-instance"

    record = run_task_episode(
        prepared,  # type: ignore[arg-type]
        pack,
        pack_id,
        policy_driver=driver,
        rollout_index=1,
        instance_root=instance,
    )

    assert record.reward.to_document() == {
        "disposition": "verified_success",
        "reward": 1.0,
        "abstain_owner": None,
        "abstain_code": None,
    }
    assert set(cast(dict[str, Any], record.checker_documents)) == {kind}
    assert prepared.paths == [instance, instance]
    assert prepared.state["reset_count"] == 1
    assert "reopened:reset" not in prepared.events
    assert prepared.events.index("acting:close") < prepared.events.index("reopened:open")
    assert [event.kind for event in record.lifecycle_events] == [
        "acting_open",
        "reset",
        "capture_terminal",
        "pre_close_inspect",
        "acting_close",
        "reopened_open",
        "post_reopen_inspect",
        "checker_evaluated",
        "reopened_close",
    ]
    assert record.reload_evidence is not None
    assert record.reload_evidence.lifecycle_events[2].kind == "episode_complete"
    if kind == "if":
        if_documents = cast(dict[str, Any], record.checker_documents)["if"]
        assert if_documents["expected_branch"] == "true"
        assert if_documents["condition"]["result"]["status"] == "true"


@pytest.mark.parametrize(
    ("kind", "answer", "members"),
    (("foreach", '{"results":[{},{}]}', 2), ("if", "{}", 1)),
)
def test_foreach_and_if_add_no_capability_catalog_dependency(
    tmp_path: Path,
    kind: Literal["foreach", "if"],
    answer: str,
    members: int,
) -> None:
    pack, pack_id, _task = _write_pack(tmp_path, kind)

    record = run_task_episode(
        Prepared(members=members, mode="catalog_must_not_be_read"),  # type: ignore[arg-type]
        pack,
        pack_id,
        policy_driver=Driver(_completed(1, answer)),
        rollout_index=1,
        instance_root=tmp_path / "instance",
    )

    assert record.reward.reward == 1.0


def test_if_runtime_uses_only_existing_admission_cross_bindings(tmp_path: Path) -> None:
    pack, pack_id, _task = _write_pack(
        tmp_path,
        "if",
        if_public_descriptor={"outer_instruction_descriptor": True},
    )

    record = run_task_episode(
        Prepared(),  # type: ignore[arg-type]
        pack,
        pack_id,
        policy_driver=Driver(_completed(1, "{}")),
        rollout_index=1,
        instance_root=tmp_path / "instance",
    )

    assert record.reward.reward == 1.0


@pytest.mark.parametrize(
    ("decisions", "expected_state"),
    (
        (_completed(0, "{}"), 0),
        (
            [
                DriverDecision(calls=(("call-1", "set_value", '{"value":1}'),)),
                DriverDecision(),
            ],
            1,
        ),
    ),
)
def test_checker_failure_and_policy_failure_are_reward_zero(
    tmp_path: Path, decisions: list[DriverDecision], expected_state: int
) -> None:
    pack, pack_id, _task = _write_pack(tmp_path, "atom")

    record = run_task_episode(
        Prepared(),  # type: ignore[arg-type]
        pack,
        pack_id,
        policy_driver=Driver(decisions),
        rollout_index=1,
        instance_root=tmp_path / "instance",
    )

    assert record.reward.reward == 0.0
    result = cast(dict[str, Any], record.checker_documents)["atom"]["result"]
    assert result["satisfied"] is (expected_state == 1)
    if expected_state == 1:
        assert record.capture.completion is not None
        assert record.capture.completion.terminal_kind == "policy_failure"
        assert record.reload_evidence is None


def test_foreach_policy_failure_passes_missing_answers_to_each_checker(
    tmp_path: Path,
) -> None:
    pack, pack_id, _task = _write_pack(tmp_path, "foreach")
    decisions = [
        DriverDecision(calls=(("call-1", "set_value", '{"value":1}'),)),
        DriverDecision(),
    ]

    record = run_task_episode(
        Prepared(members=2),  # type: ignore[arg-type]
        pack,
        pack_id,
        policy_driver=Driver(decisions),
        rollout_index=1,
        instance_root=tmp_path / "instance",
    )

    members = cast(dict[str, Any], record.checker_documents)["foreach"]
    assert [item["request"]["final_answer"] for item in members] == [None, None]
    assert all(item["result"]["satisfied"] for item in members)
    assert record.reward.reward == 0.0


@pytest.mark.parametrize(
    ("mode", "decisions", "owner"),
    (
        (
            "healthy",
            [DriverDecision(defect=EpisodeDefect("provider", "remote_429", "request"))],
            "provider",
        ),
        (
            "healthy",
            [DriverDecision(defect=EpisodeDefect("infrastructure", "route_down", "request"))],
            "infrastructure",
        ),
        ("environment", _completed(1, "{}"), "environment"),
        ("semantics", _completed(1, "{}"), "semantics"),
        ("verifier", _completed(1, "{}"), "verifier"),
        ("same_session", _completed(1, "{}"), "evidence"),
    ),
)
def test_typed_defects_abstain(
    tmp_path: Path, mode: str, decisions: list[DriverDecision], owner: str
) -> None:
    pack, pack_id, _task = _write_pack(tmp_path, "atom")

    record = run_task_episode(
        Prepared(mode=mode),  # type: ignore[arg-type]
        pack,
        pack_id,
        policy_driver=Driver(decisions),
        rollout_index=1,
        instance_root=tmp_path / "instance",
    )

    assert record.reward.disposition == "abstain"
    assert record.reward.reward is None
    assert record.reward.abstain_owner == owner
    assert record.reload_evidence is None


def test_capture_defect_remains_primary_when_reopen_reuses_session(tmp_path: Path) -> None:
    pack, pack_id, _task = _write_pack(tmp_path, "atom")
    driver = Driver([DriverDecision(defect=EpisodeDefect("provider", "remote_429", "request"))])

    record = run_task_episode(
        Prepared(mode="same_session"),  # type: ignore[arg-type]
        pack,
        pack_id,
        policy_driver=driver,
        rollout_index=1,
        instance_root=tmp_path / "instance",
    )

    assert record.capture.defect is not None
    assert record.capture.defect.owner == "provider"
    assert record.lifecycle_defect is None
    assert record.reopened_session_id is None
    assert record.reward.abstain_owner == "provider"


def test_bad_checker_authority_stops_before_policy_or_instance(tmp_path: Path) -> None:
    pack, pack_id, _task = _write_pack(tmp_path, "atom", bad_checker=True)
    prepared, driver = Prepared(), Driver(_completed(1, "{}"))

    with pytest.raises(TaskFoundryError, match="preimage"):
        run_task_episode(
            prepared,  # type: ignore[arg-type]
            pack,
            pack_id,
            policy_driver=driver,
            rollout_index=1,
            instance_root=tmp_path / "instance",
        )

    assert prepared.paths == []
    assert driver.started == []
    assert driver.spec_reads == 0


def test_preflight_failure_stops_before_public_input(tmp_path: Path) -> None:
    pack, pack_id, _task = _write_pack(tmp_path, "atom")
    prepared, driver = Prepared(mode="preflight"), Driver(_completed(1, "{}"))

    with pytest.raises(PreparationExecutionError, match="preflight"):
        run_task_episode(
            prepared,  # type: ignore[arg-type]
            pack,
            pack_id,
            policy_driver=driver,
            rollout_index=1,
            instance_root=tmp_path / "instance",
        )

    assert driver.started == []
    assert driver.close_count == 1
    assert len(prepared.paths) == 1


def test_unattributed_pre_close_failure_still_closes_acting_session(tmp_path: Path) -> None:
    pack, pack_id, _task = _write_pack(tmp_path, "atom")
    prepared = Prepared(mode="unattributed_pre_close")

    with pytest.raises(RuntimeError, match="unexpected pre-close"):
        run_task_episode(
            prepared,  # type: ignore[arg-type]
            pack,
            pack_id,
            policy_driver=Driver(_completed(1, "{}")),
            rollout_index=1,
            instance_root=tmp_path / "instance",
        )

    assert prepared.events[-1] == "acting:close"
    assert len(prepared.paths) == 1


def test_policy_elapsed_covers_only_the_host_capture(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pack, pack_id, _task = _write_pack(tmp_path, "atom")
    ticks = iter((1_000_000, 6_900_000))
    monkeypatch.setattr(runtime_module.time, "monotonic_ns", lambda: next(ticks))

    record = run_task_episode(
        Prepared(),  # type: ignore[arg-type]
        pack,
        pack_id,
        policy_driver=Driver(_completed(1, "{}")),
        rollout_index=1,
        instance_root=tmp_path / "instance",
    )

    assert record.policy_elapsed_ms == 5


def test_episode_record_rejects_bound_mutations_under_old_identity(tmp_path: Path) -> None:
    pack, pack_id, _task = _write_pack(tmp_path, "atom")
    record = run_task_episode(
        Prepared(),  # type: ignore[arg-type]
        pack,
        pack_id,
        policy_driver=Driver(_completed(1, "{}")),
        rollout_index=1,
        instance_root=tmp_path / "one-path",
    )

    turn = record.capture.turns[0]
    call = turn.calls[0]
    checker = deepcopy(record.checker_documents)
    assert checker is not None
    cast(dict[str, Any], checker)["atom"]["result"]["report_values"] = {"changed": True}
    assert record.reload_evidence is not None
    mutations = (
        {"policy_elapsed_ms": record.policy_elapsed_ms + 1},
        {
            "capture": replace(
                record.capture,
                turns=(
                    replace(
                        turn,
                        calls=(replace(call, raw_arguments='{"value":2}'),),
                    ),
                    *record.capture.turns[1:],
                ),
            )
        },
        {
            "lifecycle_events": (
                replace(record.lifecycle_events[0], session_id="f" * 64),
                *record.lifecycle_events[1:],
            )
        },
        {"checker_documents": checker},
        {"policy_spec": replace(record.policy_spec, model_id="changed-policy")},
        {"request": replace(record.request, rollout_index=2)},
        {
            "reload_evidence": replace(
                record.reload_evidence,
                post_reopen_checker_result_digest="f" * 64,
            )
        },
        {"reward": replace(record.reward, disposition="verified_failure", reward=0.0)},
    )
    for mutation in mutations:
        with pytest.raises(ValueError):
            replace(record, **mutation, episode_id=record.episode_id)
    assert "one-path" not in str(record.to_document())


def test_if_condition_truth_is_load_bearing(tmp_path: Path) -> None:
    pack, pack_id, _task = _write_pack(tmp_path, "if")
    record = run_task_episode(
        Prepared(),  # type: ignore[arg-type]
        pack,
        pack_id,
        policy_driver=Driver(_completed(1, "{}")),
        rollout_index=1,
        instance_root=tmp_path / "instance",
    )
    checker = deepcopy(record.checker_documents)
    assert checker is not None
    if_group = cast(dict[str, Any], checker)["if"]
    if_group["expected_branch"] = "false"

    result_projection = {
        "condition_result": if_group["condition"]["result"],
        "branch_result": if_group["branch"]["result"],
    }
    assert record.reload_evidence is not None
    changed = replace(
        record,
        checker_documents=checker,
        reload_evidence=replace(
            record.reload_evidence,
            post_reopen_checker_result_digest=_sha(result_projection),
        ),
        reward=RewardOutcome("verified_failure", 0.0, None, None),
        episode_id="",
    )

    assert changed.reward.reward == 0.0
    assert changed.episode_id != record.episode_id


def test_episode_record_rejects_checker_trace_that_differs_from_capture(
    tmp_path: Path,
) -> None:
    pack, pack_id, _task = _write_pack(tmp_path, "atom")
    record = run_task_episode(
        Prepared(),  # type: ignore[arg-type]
        pack,
        pack_id,
        policy_driver=Driver(
            [
                DriverDecision(calls=(("call-1", "set_value", '{"value":1}'),)),
                DriverDecision(),
            ]
        ),
        rollout_index=1,
        instance_root=tmp_path / "instance",
    )
    checker = deepcopy(record.checker_documents)
    assert checker is not None
    cast(dict[str, Any], checker)["atom"]["request"]["trace_projection"] = []

    with pytest.raises(ValueError, match="checker trace"):
        replace(record, checker_documents=checker, episode_id="")
