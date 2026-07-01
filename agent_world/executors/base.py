from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class NodeExecutionResult:
    status: str
    fields: dict[str, Any] = field(default_factory=dict)
    invocation_records: list[dict[str, Any]] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    trace_refs: list[str] = field(default_factory=list)
    failure_class: str = ""
    recovery_suggestion: str = ""


class NodeExecutor(Protocol):
    executor_id: str

    def execute(self, context: Any, node: Any, profile: Any) -> NodeExecutionResult:
        ...

