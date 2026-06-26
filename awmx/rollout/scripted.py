from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import BaseRunner, RolloutSession, RunnerResult


class ScriptedRunner(BaseRunner):
    runner_name = "scripted"

    def __init__(self, steps: list[dict[str, Any]] | None = None) -> None:
        self._steps = steps

    def run(self, session: RolloutSession) -> RunnerResult:
        actor = self.runner_name
        session.record_event("rollout_started", {"runner": actor})
        steps = self._steps if self._steps is not None else session.run_spec.runner.get("config", {}).get("steps", [])

        final_output: dict[str, Any] = {}
        for step in steps:
            action = dict(step["action"])
            observation = dict(step.get("observation", {}))
            evidence = dict(step.get("evidence", {}))
            session.record_authorized_step(
                actor=actor,
                action=action,
                observation=observation,
                evidence=evidence,
                apply=self._apply_action,
            )
            final_output = observation

        session.record_event("rollout_completed", {"runner": actor, "step_count": session._sequence})
        return RunnerResult(
            trace_path=session.trace_path,
            events_path=session.events_path,
            final_output=final_output,
            step_count=session._sequence,
        )

    @staticmethod
    def _apply_action(action: dict[str, Any], permission: dict[str, Any]) -> None:
        kind = action["kind"]
        if kind in {"write_file", "file_edit"}:
            path = Path(permission["path"])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(action.get("content", ""), encoding="utf-8")
