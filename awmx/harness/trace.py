from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from awmx.artifacts.ids import validate_storage_id
from awmx.artifacts.schemas import RunSpec, TraceRecord


@dataclass(frozen=True)
class RunDirectory:
    path: Path
    run_yaml_path: Path
    events_path: Path
    trace_path: Path
    logs_path: Path


def create_run_directory(runs_root: Path | str, run_spec: RunSpec) -> RunDirectory:
    run_id = validate_storage_id(run_spec.id, "run.id")
    run_path = Path(runs_root) / run_id
    logs_path = run_path / "logs"
    run_path.mkdir(parents=True, exist_ok=False)
    logs_path.mkdir(exist_ok=True)

    run_yaml_path = run_path / "run.yaml"
    events_path = run_path / "events.jsonl"
    trace_path = run_path / "trace.jsonl"

    run_yaml_path.write_text(
        yaml.safe_dump(run_spec.to_dict(), sort_keys=False),
        encoding="utf-8",
    )
    _touch_jsonl(events_path)
    _touch_jsonl(trace_path)

    return RunDirectory(
        path=run_path,
        run_yaml_path=run_yaml_path,
        events_path=events_path,
        trace_path=trace_path,
        logs_path=logs_path,
    )


def _touch_jsonl(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text("", encoding="utf-8")


class JsonlAppender:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        _touch_jsonl(self.path)

    def append(self, payload: dict[str, Any]) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=True, sort_keys=True) + "\n")


class EventLogger(JsonlAppender):
    pass


class TraceLogger(JsonlAppender):
    def append(self, payload: dict[str, Any]) -> None:
        TraceRecord.from_dict(payload)
        super().append(payload)
