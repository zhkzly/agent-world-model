from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .base import BaseRunner, RolloutSession, RunnerResult


@dataclass
class FakeCodexBackend:
    operations: list[dict[str, Any]]
    review_result: dict[str, Any]


class FakeCodexRunner(BaseRunner):
    runner_name = "codex_sdk"

    def __init__(self, backend: FakeCodexBackend) -> None:
        self.backend = backend

    def run(self, session: RolloutSession) -> RunnerResult:
        actor = self.runner_name
        session.record_event("rollout_started", {"runner": actor})

        for operation in self.backend.operations:
            action = dict(operation)
            session.record_authorized_step(
                actor=actor,
                action=action,
                observation={},
                evidence={"operation": operation},
                apply=self._apply_operation,
            )

        session.record_event("rollout_completed", {"runner": actor, "step_count": session._sequence})
        return RunnerResult(
            trace_path=session.trace_path,
            events_path=session.events_path,
            final_output={"review": self.backend.review_result},
            step_count=session._sequence,
        )

    @staticmethod
    def _apply_operation(operation: dict[str, Any], permission: dict[str, Any]) -> dict[str, Any]:
        kind = operation["kind"]
        if kind == "file_edit":
            path = Path(permission["path"])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(operation.get("content", ""), encoding="utf-8")
            return {"status": "ok", "path": str(path)}
        if kind == "test_result":
            return {
                "exit_code": operation["exit_code"],
                "stdout": operation.get("stdout", ""),
                "stderr": operation.get("stderr", ""),
            }
        return {"status": "recorded"}
