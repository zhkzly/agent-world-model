from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from tests.fixtures.fx_task_execution import public_attempt_id

import agent_env_foundry.task_execution as execution_module
from agent_env_foundry.public_agent import PublicEpisodeRun
from agent_env_foundry.task_execution import (
    LifecycleEvent,
    ReloadEvidence,
    TaskExecutionError,
    run_public_attempt,
)

DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
DIGEST_C = "c" * 64
DIGEST_D = "d" * 64
DIGEST_E = "e" * 64


def _events() -> tuple[LifecycleEvent, ...]:
    kinds = (
        "acting_open",
        "reset",
        "episode_complete",
        "pre_close_inspect",
        "acting_close",
        "reopened_open",
        "post_reopen_inspect",
        "checker_evaluated",
        "reopened_close",
    )
    return tuple(
        LifecycleEvent(
            index,
            kind,
            DIGEST_D if index <= 5 else DIGEST_E,
            DIGEST_C,
        )
        for index, kind in enumerate(kinds, start=1)
    )


def _evidence() -> ReloadEvidence:
    return ReloadEvidence(
        release_id=DIGEST_A,
        task_id=DIGEST_B,
        attempt_id=public_attempt_id(DIGEST_A, DIGEST_B, DIGEST_C),
        native_instance_id=DIGEST_C,
        acting_session_id=DIGEST_D,
        reopened_session_id=DIGEST_E,
        lifecycle_events=_events(),
        pre_close_facts_digest="2" * 64,
        post_reopen_facts_digest="2" * 64,
        post_reopen_checker_result_digest="3" * 64,
    )


def test_reload_evidence_binds_exact_order_same_instance_and_distinct_sessions() -> None:
    evidence = _evidence()

    assert evidence.evidence_id
    assert evidence.to_document()["format"] == "reload-evidence/1"
    assert evidence.to_document()["lifecycle_event_digest"]
    assert evidence.to_document()["post_reopen_checker_result_digest"] == "3" * 64
    assert "checker_result_digest" not in evidence.to_document()
    assert [item["kind"] for item in evidence.to_document()["lifecycle_events"]] == [
        "acting_open",
        "reset",
        "episode_complete",
        "pre_close_inspect",
        "acting_close",
        "reopened_open",
        "post_reopen_inspect",
        "checker_evaluated",
        "reopened_close",
    ]


@pytest.mark.parametrize(
    "mutate",
    (
        lambda item: replace(item, reopened_session_id=item.acting_session_id),
        lambda item: replace(item, lifecycle_events=item.lifecycle_events[:-1]),
        lambda item: replace(
            item,
            lifecycle_events=(
                *item.lifecycle_events[:5],
                replace(item.lifecycle_events[5], kind="reset"),
                *item.lifecycle_events[6:],
            ),
        ),
        lambda item: replace(
            item,
            lifecycle_events=(
                *item.lifecycle_events[:6],
                replace(item.lifecycle_events[6], native_instance_id="4" * 64),
                *item.lifecycle_events[7:],
            ),
        ),
        lambda item: replace(
            item,
            lifecycle_events=(
                *item.lifecycle_events[:5],
                item.lifecycle_events[7],
                item.lifecycle_events[5],
                item.lifecycle_events[6],
                item.lifecycle_events[8],
            ),
        ),
    ),
)
def test_reload_evidence_rejects_fake_reopen_shapes(mutate) -> None:
    with pytest.raises((TaskExecutionError, ValueError)):
        mutate(_evidence())


def test_reload_evidence_requires_distinct_sessions_even_when_events_agree() -> None:
    evidence = _evidence()
    same_session_events = tuple(
        replace(item, session_id=evidence.acting_session_id) if item.seq > 5 else item
        for item in evidence.lifecycle_events
    )

    with pytest.raises(TaskExecutionError, match="distinct"):
        replace(
            evidence,
            reopened_session_id=evidence.acting_session_id,
            lifecycle_events=same_session_events,
        )


def test_reload_evidence_rejects_attempt_id_from_another_preimage() -> None:
    with pytest.raises(TaskExecutionError, match="attempt identity"):
        replace(_evidence(), attempt_id="9" * 64)


def test_public_attempt_closes_then_reopens_same_instance_before_checker(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    opened_paths: list[Path] = []
    host_events: list[str] = []

    class Actor:
        def __init__(self, label: str) -> None:
            self.label = label

        def reset(self, start):
            host_events.append(f"{self.label}:reset")
            return {"ready": True}

        def tools(self):
            return ()

    class Trusted:
        def __init__(self, facts: list[dict[str, object]]) -> None:
            self.facts = iter(facts)

        def inspect(self, _path: Path):
            value = next(self.facts)
            host_events.append(f"inspect:{value['count']}")
            return value

    class Session:
        def __init__(self, session_id: str, label: str, facts) -> None:
            self.identity = SimpleNamespace(materialization_id=session_id)
            self.actor = Actor(label)
            self.trusted = Trusted(facts)

        def __enter__(self):
            host_events.append(f"{self.actor.label}:open")
            return self

        def __exit__(self, *_args):
            host_events.append(f"{self.actor.label}:close")

    sessions = iter(
        (
            Session(DIGEST_D, "acting", [{"count": 0}, {"count": 1}]),
            Session(DIGEST_E, "reopened", [{"count": 1}]),
        )
    )

    class Prepared:
        identity = SimpleNamespace(release_id=DIGEST_A)

        def open(self, path: Path):
            opened_paths.append(path)
            return next(sessions)

    monkeypatch.setattr(
        execution_module,
        "run_public_episode",
        lambda **_kwargs: PublicEpisodeRun((), {}, 1, (None,)),
    )

    with run_public_attempt(
        Prepared(),  # type: ignore[arg-type]
        tmp_path / "instance",
        task_id=DIGEST_B,
        start_input=None,
        instruction="Complete the public task.",
        answer_schema={
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
        preflight=lambda _session, facts: {"before": facts},
    ) as attempt:
        assert attempt.preflight_value == {"before": {"count": 0}}
        assert host_events.index("acting:close") < host_events.index("reopened:open")
        attempt.record_checker_result({"satisfied": True})

    assert opened_paths == [tmp_path / "instance", tmp_path / "instance"]
    assert host_events.count("acting:reset") == 1
    assert "reopened:reset" not in host_events
    assert attempt.reload_evidence is not None
    assert attempt.reload_evidence.acting_session_id == DIGEST_D
    assert attempt.reload_evidence.reopened_session_id == DIGEST_E
    assert attempt.reload_evidence.pre_close_facts_digest == (
        attempt.reload_evidence.post_reopen_facts_digest
    )


def test_public_attempt_requires_post_reopen_checker_result(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class Session:
        def __init__(self, session_id: str) -> None:
            self.identity = SimpleNamespace(materialization_id=session_id)
            self.actor = SimpleNamespace(reset=lambda _start: {}, tools=lambda: ())
            self.trusted = SimpleNamespace(inspect=lambda _path: {"count": 0})

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    sessions = iter((Session(DIGEST_D), Session(DIGEST_E)))
    prepared = SimpleNamespace(
        identity=SimpleNamespace(release_id=DIGEST_A),
        open=lambda _path: next(sessions),
    )
    monkeypatch.setattr(
        execution_module,
        "run_public_episode",
        lambda **_kwargs: PublicEpisodeRun((), {}, 1, (None,)),
    )

    with pytest.raises(TaskExecutionError, match="checker"):
        with run_public_attempt(
            prepared,  # type: ignore[arg-type]
            tmp_path / "instance",
            task_id=DIGEST_B,
            start_input=None,
            instruction="Complete the public task.",
            answer_schema={
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
            preflight=lambda _session, facts: facts,
        ):
            pass
