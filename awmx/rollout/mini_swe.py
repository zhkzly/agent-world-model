from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .base import BaseRunner, RolloutSession, RunnerResult


@dataclass
class FakeMiniSweBackend:
    history: list[dict[str, Any]]


class FakeMiniSweRunner(BaseRunner):
    runner_name = "mini_swe"

    def __init__(self, backend: FakeMiniSweBackend) -> None:
        self.backend = backend

    def run(self, session: RolloutSession) -> RunnerResult:
        actor = self.runner_name
        session.record_event("rollout_started", {"runner": actor})

        for item in self.backend.history:
            action = {
                "kind": "command",
                "command": item["command"],
                "cwd": item.get("cwd"),
                "env": item.get("env", {}),
            }
            if "read_paths" in item:
                action["read_paths"] = item["read_paths"]
            if "write_paths" in item:
                action["write_paths"] = item["write_paths"]
            observation = {
                "exit_code": item["exit_code"],
                "duration_ms": item.get("duration_ms"),
                "stdout_summary": item.get("stdout_summary", _summary(item.get("stdout", ""))),
                "stderr_summary": item.get("stderr_summary", _summary(item.get("stderr", ""))),
                "stdout_path": item.get("stdout_path"),
                "stderr_path": item.get("stderr_path"),
            }
            evidence = {
                "raw_history": item,
                "command_audit": {
                    "command": item["command"],
                    "cwd": item.get("cwd"),
                    "env": item.get("env", {}),
                    "read_paths": item.get("read_paths", []),
                    "write_paths": item.get("write_paths", []),
                    "exit_code": item["exit_code"],
                    "duration_ms": item.get("duration_ms"),
                    "stdout_path": item.get("stdout_path"),
                    "stderr_path": item.get("stderr_path"),
                    "stdout_summary": observation["stdout_summary"],
                    "stderr_summary": observation["stderr_summary"],
                },
            }
            session.record_authorized_step(actor=actor, action=action, observation=observation, evidence=evidence)

        session.record_event("rollout_completed", {"runner": actor, "step_count": session._sequence})
        return RunnerResult(
            trace_path=session.trace_path,
            events_path=session.events_path,
            final_output={"history_length": len(self.backend.history)},
            step_count=session._sequence,
        )


def _summary(value: str, limit: int = 200) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + "...[truncated]"
