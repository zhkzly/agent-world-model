"""Shared physical public-attempt lifecycle and reload evidence."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, cast

from agent_env_foundry.agents import AgentRoute
from agent_env_foundry.environment import JSONObject, JSONValue, ToolSpec
from agent_env_foundry.jsonvalue import is_json_object, is_json_value
from agent_env_foundry.preparation import OpenPreparedRelease, OpenPreparedSession
from agent_env_foundry.public_agent import PublicEpisodeRun, run_public_episode
from agent_env_foundry.release import canonical_bytes

LifecycleKind = Literal[
    "acting_open",
    "reset",
    "capture_terminal",
    "episode_complete",
    "pre_close_inspect",
    "acting_close",
    "reopened_open",
    "post_reopen_inspect",
    "checker_evaluated",
    "reopened_close",
]
_LIFECYCLE_KINDS: tuple[LifecycleKind, ...] = (
    "acting_open",
    "reset",
    "capture_terminal",
    "episode_complete",
    "pre_close_inspect",
    "acting_close",
    "reopened_open",
    "post_reopen_inspect",
    "checker_evaluated",
    "reopened_close",
)
_RELOAD_LIFECYCLE_KINDS: tuple[LifecycleKind, ...] = (
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
_HEX = frozenset("0123456789abcdef")


class TaskExecutionError(ValueError):
    """A public-attempt lifecycle or its evidence is invalid."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class LifecycleEvent:
    seq: int
    kind: LifecycleKind
    session_id: str
    native_instance_id: str

    def __post_init__(self) -> None:
        if isinstance(self.seq, bool) or not isinstance(self.seq, int) or self.seq <= 0:
            raise TaskExecutionError(
                "lifecycle_event_sequence_invalid",
                "lifecycle event sequence must be positive",
            )
        if self.kind not in _LIFECYCLE_KINDS:
            raise TaskExecutionError(
                "lifecycle_event_kind_invalid",
                "lifecycle event kind is invalid",
            )
        _digest(self.session_id, "lifecycle session_id")
        _digest(self.native_instance_id, "lifecycle native_instance_id")

    def to_document(self) -> JSONObject:
        return {
            "seq": self.seq,
            "kind": self.kind,
            "session_id": self.session_id,
            "native_instance_id": self.native_instance_id,
        }


@dataclass(frozen=True, slots=True)
class ReloadEvidence:
    release_id: str
    task_id: str
    attempt_id: str
    native_instance_id: str
    acting_session_id: str
    reopened_session_id: str
    lifecycle_events: tuple[LifecycleEvent, ...]
    pre_close_facts_digest: str
    post_reopen_facts_digest: str
    post_reopen_checker_result_digest: str

    def __post_init__(self) -> None:
        for value, role in (
            (self.release_id, "reload release_id"),
            (self.task_id, "reload task_id"),
            (self.attempt_id, "reload attempt_id"),
            (self.native_instance_id, "reload native_instance_id"),
            (self.acting_session_id, "reload acting_session_id"),
            (self.reopened_session_id, "reload reopened_session_id"),
            (self.pre_close_facts_digest, "reload pre_close_facts_digest"),
            (self.post_reopen_facts_digest, "reload post_reopen_facts_digest"),
            (
                self.post_reopen_checker_result_digest,
                "reload post_reopen_checker_result_digest",
            ),
        ):
            _digest(value, role)
        if self.attempt_id != _derive_attempt_id(
            self.release_id,
            self.task_id,
            self.native_instance_id,
        ):
            raise TaskExecutionError(
                "reload_attempt_identity_mismatch",
                "reload attempt identity does not bind release, Task, and native instance",
            )
        if self.acting_session_id == self.reopened_session_id:
            raise TaskExecutionError(
                "reload_session_reused",
                "reload evidence requires distinct acting and reopened sessions",
            )
        actual_kinds = tuple(item.kind for item in self.lifecycle_events)
        if actual_kinds != _RELOAD_LIFECYCLE_KINDS:
            raise TaskExecutionError(
                "reload_lifecycle_order_invalid",
                "reload lifecycle events differ from the exact close/reopen order",
            )
        if tuple(item.seq for item in self.lifecycle_events) != tuple(
            range(1, len(_RELOAD_LIFECYCLE_KINDS) + 1)
        ):
            raise TaskExecutionError(
                "reload_lifecycle_sequence_invalid",
                "reload lifecycle event sequence is not contiguous",
            )
        if any(
            item.native_instance_id != self.native_instance_id for item in self.lifecycle_events
        ):
            raise TaskExecutionError(
                "reload_native_instance_changed",
                "reload lifecycle crossed into another native instance",
            )
        if any(
            item.session_id != self.acting_session_id for item in self.lifecycle_events[:5]
        ) or any(item.session_id != self.reopened_session_id for item in self.lifecycle_events[5:]):
            raise TaskExecutionError(
                "reload_session_binding_invalid",
                "reload lifecycle events belong to the wrong session",
            )

    @property
    def lifecycle_event_digest(self) -> str:
        return _document_digest({"events": [item.to_document() for item in self.lifecycle_events]})

    @property
    def evidence_id(self) -> str:
        return _document_digest(self._preimage())

    def _preimage(self) -> JSONObject:
        return {
            "format": "reload-evidence/1",
            "release_id": self.release_id,
            "task_id": self.task_id,
            "attempt_id": self.attempt_id,
            "native_instance_id": self.native_instance_id,
            "acting_session_id": self.acting_session_id,
            "reopened_session_id": self.reopened_session_id,
            "lifecycle_events": [item.to_document() for item in self.lifecycle_events],
            "lifecycle_event_digest": self.lifecycle_event_digest,
            "pre_close_facts_digest": self.pre_close_facts_digest,
            "post_reopen_facts_digest": self.post_reopen_facts_digest,
            "post_reopen_checker_result_digest": self.post_reopen_checker_result_digest,
        }

    def to_document(self) -> JSONObject:
        return {**self._preimage(), "evidence_id": self.evidence_id}


@dataclass(slots=True)
class PublicAttemptContext[T]:
    task_id: str
    attempt_id: str
    native_instance_id: str
    acting_session_id: str
    reopened_session_id: str
    evaluation_session: OpenPreparedSession
    preflight_value: T
    reset_observation: JSONValue
    before_facts: JSONValue
    pre_close_facts: JSONValue
    post_reopen_facts: JSONValue
    tool_specs: tuple[ToolSpec, ...]
    episode: PublicEpisodeRun
    _events: list[LifecycleEvent] = field(repr=False)
    _checker_result_digest: str | None = field(default=None, init=False, repr=False)
    reload_evidence: ReloadEvidence | None = field(default=None, init=False)

    def record_checker_result(self, result: JSONObject) -> None:
        if self._checker_result_digest is not None:
            raise TaskExecutionError(
                "reload_checker_result_duplicated",
                "reload checker result may be recorded only once",
            )
        document = _object(result, "reload checker result")
        self._checker_result_digest = _document_digest(document)
        self._events.append(
            LifecycleEvent(
                len(self._events) + 1,
                "checker_evaluated",
                self.reopened_session_id,
                self.native_instance_id,
            )
        )


@contextmanager
def run_public_attempt[T](
    prepared: OpenPreparedRelease,
    instance_root: Path,
    *,
    task_id: str,
    start_input: JSONObject | None,
    instruction: str,
    answer_schema: JSONObject,
    preflight: Callable[[OpenPreparedSession, JSONValue], T],
    route: AgentRoute | None = None,
    max_provider_turns: int | None = None,
) -> Iterator[PublicAttemptContext[T]]:
    """Run publicly, close, reopen the same instance, then expose trusted evaluation."""

    _digest(task_id, "attempt task_id")
    release_id = prepared.identity.release_id
    _digest(release_id, "attempt release_id")
    native_instance_id = _document_digest(
        {
            "format": "native-task-instance/1",
            "release_id": release_id,
            "task_id": task_id,
            "nonce": uuid.uuid4().hex,
        }
    )
    attempt_id = _derive_attempt_id(release_id, task_id, native_instance_id)
    instance = Path(instance_root)
    events: list[LifecycleEvent] = []

    with prepared.open(instance) as acting:
        acting_session_id = acting.identity.materialization_id
        events.append(LifecycleEvent(1, "acting_open", acting_session_id, native_instance_id))
        reset_observation = acting.actor.reset(start_input)
        events.append(LifecycleEvent(2, "reset", acting_session_id, native_instance_id))
        before_facts = acting.trusted.inspect(instance)
        preflight_value = preflight(acting, before_facts)
        tool_specs = acting.actor.tools()
        episode = run_public_episode(
            actor=acting.actor,
            instruction=instruction,
            reset_observation=reset_observation,
            tool_specs=tool_specs,
            answer_schema=answer_schema,
            route=route,
            max_provider_turns=max_provider_turns,
        )
        events.append(
            LifecycleEvent(
                3,
                "episode_complete",
                acting_session_id,
                native_instance_id,
            )
        )
        pre_close_facts = acting.trusted.inspect(instance)
        events.append(
            LifecycleEvent(
                4,
                "pre_close_inspect",
                acting_session_id,
                native_instance_id,
            )
        )
    events.append(LifecycleEvent(5, "acting_close", acting_session_id, native_instance_id))

    context: PublicAttemptContext[T] | None = None
    completed = False
    reopened_session_id: str | None = None
    try:
        with prepared.open(instance) as reopened:
            reopened_session_id = reopened.identity.materialization_id
            events.append(
                LifecycleEvent(
                    6,
                    "reopened_open",
                    reopened_session_id,
                    native_instance_id,
                )
            )
            post_reopen_facts = reopened.trusted.inspect(instance)
            events.append(
                LifecycleEvent(
                    7,
                    "post_reopen_inspect",
                    reopened_session_id,
                    native_instance_id,
                )
            )
            context = PublicAttemptContext(
                task_id,
                attempt_id,
                native_instance_id,
                acting_session_id,
                reopened_session_id,
                reopened,
                preflight_value,
                _json(reset_observation, "reset observation"),
                _json(before_facts, "before facts"),
                _json(pre_close_facts, "pre-close facts"),
                _json(post_reopen_facts, "post-reopen facts"),
                tool_specs,
                episode,
                events,
            )
            yield context
            completed = True
    finally:
        if reopened_session_id is not None:
            events.append(
                LifecycleEvent(
                    len(events) + 1,
                    "reopened_close",
                    reopened_session_id,
                    native_instance_id,
                )
            )

    if completed:
        assert context is not None
        if context._checker_result_digest is None:
            raise TaskExecutionError(
                "reload_checker_result_missing",
                "post-reopen checker result was not recorded",
            )
        context.reload_evidence = ReloadEvidence(
            release_id,
            task_id,
            attempt_id,
            native_instance_id,
            acting_session_id,
            context.reopened_session_id,
            tuple(events),
            _document_digest(context.pre_close_facts),
            _document_digest(context.post_reopen_facts),
            context._checker_result_digest,
        )


def _document_digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _derive_attempt_id(release_id: str, task_id: str, native_instance_id: str) -> str:
    return _document_digest(
        {
            "format": "public-task-attempt/1",
            "release_id": release_id,
            "task_id": task_id,
            "native_instance_id": native_instance_id,
        }
    )


def _digest(value: str, role: str) -> None:
    if len(value) != 64 or any(character not in _HEX for character in value):
        raise TaskExecutionError(
            "reload_digest_invalid",
            f"{role} must be a sha256 digest",
        )


def _json(value: Any, role: str) -> JSONValue:
    if not is_json_value(value):
        raise TaskExecutionError("reload_value_not_json", f"{role} must be JSON")
    return cast(JSONValue, json.loads(json.dumps(value, ensure_ascii=False)))


def _object(value: Any, role: str) -> JSONObject:
    if not is_json_object(value):
        raise TaskExecutionError("reload_value_not_object", f"{role} must be an object")
    return cast(JSONObject, json.loads(json.dumps(value, ensure_ascii=False)))


__all__ = [
    "LifecycleEvent",
    "PublicAttemptContext",
    "ReloadEvidence",
    "TaskExecutionError",
    "run_public_attempt",
]
