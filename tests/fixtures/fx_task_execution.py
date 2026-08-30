from __future__ import annotations

import hashlib

from agent_env_foundry.release import canonical_bytes
from agent_env_foundry.task_execution import LifecycleEvent, ReloadEvidence


def public_attempt_id(release_id: str, task_id: str, native_instance_id: str) -> str:
    return hashlib.sha256(
        canonical_bytes(
            {
                "format": "public-task-attempt/1",
                "release_id": release_id,
                "task_id": task_id,
                "native_instance_id": native_instance_id,
            }
        )
    ).hexdigest()


def reload_evidence(
    task_id: str,
    acting_session_id: str,
    *,
    release_id: str = "a" * 64,
    reopened_session_id: str | None = None,
) -> ReloadEvidence:
    selected_reopened_id = reopened_session_id or (
        "f" * 64 if acting_session_id == "e" * 64 else "e" * 64
    )
    native_instance_id = "c" * 64
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
    events = tuple(
        LifecycleEvent(
            index,
            kind,
            acting_session_id if index <= 5 else selected_reopened_id,
            native_instance_id,
        )
        for index, kind in enumerate(kinds, start=1)
    )
    return ReloadEvidence(
        release_id,
        task_id,
        public_attempt_id(release_id, task_id, native_instance_id),
        native_instance_id,
        acting_session_id,
        selected_reopened_id,
        events,
        "2" * 64,
        "2" * 64,
        "3" * 64,
    )


__all__ = ["public_attempt_id", "reload_evidence"]
