from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent_world.artifacts import write_jsonl, write_yaml


@dataclass
class ArtifactStore:
    """Small local artifact store for pipeline runs."""

    root: Path | None = None
    artifacts: dict[str, dict[str, Any]] = field(default_factory=dict)
    gate_records: list[dict[str, Any]] = field(default_factory=list)
    review_records: list[dict[str, Any]] = field(default_factory=list)
    agent_invocations: list[dict[str, Any]] = field(default_factory=list)
    traces: dict[str, Any] = field(default_factory=dict)
    package_refs: list[str] = field(default_factory=list)

    def put_artifact(self, artifact_type: str, artifact: dict[str, Any]) -> None:
        self.artifacts[artifact_type] = artifact
        if self.root:
            write_yaml(self.root / "artifacts" / artifact_type / f"{artifact['id']}.yaml", artifact)

    def put_gate_records(self, records: list[dict[str, Any]]) -> None:
        self.gate_records.extend(records)
        if self.root:
            write_yaml(self.root / "checks" / "gate-records.yaml", {"gate_records": self.gate_records})

    def put_review_record(self, record: dict[str, Any]) -> None:
        self.review_records.append(record)
        if self.root:
            write_yaml(self.root / "checks" / "review-records.yaml", {"review_records": self.review_records})

    def put_agent_invocations(self, records: list[dict[str, Any]]) -> None:
        self.agent_invocations.extend(records)
        if self.root:
            write_jsonl(self.root / "checks" / "agent-invocations.jsonl", self.agent_invocations)

    def put_trace(self, name: str, value: Any) -> str:
        self.traces[name] = value
        ref = f"traces/{name}.yaml"
        if self.root:
            write_yaml(self.root / ref, value)
        return ref

    def put_package_ref(self, ref: str) -> None:
        self.package_refs.append(ref)
        if self.root:
            write_yaml(self.root / "package-refs.yaml", {"package_refs": self.package_refs})

    def write_run_record(self, record: dict[str, Any]) -> None:
        if self.root:
            write_yaml(self.root / "pipeline-run-record.yaml", record)
