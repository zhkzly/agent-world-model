from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from awmx.artifacts.schemas import RunSpec, TaskSpec, TraceRecord, ValidationError
from awmx.harness.permissions import PermissionGate


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=True, sort_keys=True))
        handle.write("\n")


def _initialize_jsonl(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")


@dataclass
class RunnerResult:
    trace_path: Path
    events_path: Path
    final_output: dict[str, Any]
    step_count: int


@dataclass
class RolloutSession:
    run_spec: RunSpec
    task: TaskSpec
    permission_gate: PermissionGate
    output_dir: Path
    actor: str | None = None
    _sequence: int = field(default=0, init=False, repr=False)

    def __post_init__(self) -> None:
        self.output_dir = Path(self.output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        _initialize_jsonl(self.trace_path)
        _initialize_jsonl(self.events_path)

    @property
    def trace_path(self) -> Path:
        return self.output_dir / "trace.jsonl"

    @property
    def events_path(self) -> Path:
        return self.output_dir / "events.jsonl"

    def next_sequence(self) -> int:
        self._sequence += 1
        return self._sequence

    def record_event(self, event: str, payload: dict[str, Any] | None = None) -> None:
        _append_jsonl(
            self.events_path,
            {
                "run_id": self.run_spec.id,
                "event": event,
                "timestamp": _utc_now(),
                "payload": payload or {},
            },
        )

    def record_authorized_step(
        self,
        *,
        actor: str,
        action: dict[str, Any],
        observation: dict[str, Any],
        evidence: dict[str, Any],
        apply: Any | None = None,
    ) -> TraceRecord:
        permission = self.permission_gate.decide(action)
        if not permission["allowed"]:
            self.record_event(
                "permission_denied",
                {
                    "actor": actor,
                    "action": action,
                    "permission": permission,
                    "reason": permission["reason"],
                },
            )
            self.record_event(
                "rollout_failed",
                {
                    "actor": actor,
                    "reason": permission["reason"],
                },
            )
            raise ValidationError(permission["reason"])

        final_observation = dict(observation)
        if apply is not None:
            try:
                applied_observation = apply(action, permission)
            except Exception as exc:
                exception = {
                    "type": type(exc).__name__,
                    "message": str(exc),
                }
                failure_evidence = dict(evidence)
                failure_evidence["permission"] = permission
                failure_evidence["exception"] = exception
                self.record_trace(
                    actor=actor,
                    action=action,
                    observation={"status": "error", "exception": exception},
                    evidence=failure_evidence,
                    event_type="runner_failure",
                )
                self.record_event(
                    "rollout_failed",
                    {
                        "actor": actor,
                        "action": action,
                        "permission": permission,
                        "exception": exception,
                        "reason": f"runner action failed: {exception['type']}: {exception['message']}",
                    },
                )
                raise ValidationError(
                    f"runner action failed: {exception['type']}: {exception['message']}"
                ) from exc
            if applied_observation is not None:
                final_observation = applied_observation

        final_evidence = dict(evidence)
        final_evidence["permission"] = permission
        record = self.record_trace(
            actor=actor,
            action=action,
            observation=final_observation,
            evidence=final_evidence,
        )
        self.record_event("step_completed", {"sequence": record.sequence, "action_kind": action["kind"]})
        return record

    def record_trace(
        self,
        *,
        actor: str,
        action: dict[str, Any],
        observation: dict[str, Any],
        evidence: dict[str, Any],
        event_type: str = "runner_step",
    ) -> TraceRecord:
        sequence = self.next_sequence()
        record = TraceRecord(
            id=f"trace.{self.run_spec.id}.{sequence:04d}",
            version="0.1.0",
            created_at=_utc_now(),
            source={"kind": "rollout", "uri": str(self.trace_path)},
            metadata={"runner": actor},
            run_id=self.run_spec.id,
            sequence=sequence,
            event_type=event_type,
            actor=actor,
            action=action,
            observation=observation,
            evidence=evidence,
        )
        _append_jsonl(self.trace_path, record.to_dict())
        return record


class BaseRunner(ABC):
    runner_name = "base"

    @abstractmethod
    def run(self, session: RolloutSession) -> RunnerResult:
        raise NotImplementedError
