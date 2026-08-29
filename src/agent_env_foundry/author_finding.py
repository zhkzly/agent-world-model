"""Typed factual feedback shared by isolated generated-code authors."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent_env_foundry.release import canonical_bytes

_SOURCES = frozenset({"framework_check", "native_physical_check"})


@dataclass(frozen=True, slots=True)
class AuthorFinding:
    source: str
    code: str
    condition: str
    expected: Any
    actual: Any
    decisive_inputs: dict[str, Any]

    def __post_init__(self) -> None:
        if self.source not in _SOURCES:
            raise ValueError("Author finding source is invalid")
        if not self.code or not self.condition:
            raise ValueError("Author finding code/condition must be non-empty")
        try:
            canonical_bytes(self.to_document())
        except Exception as exc:
            raise ValueError("Author finding must be canonical JSON") from exc

    def to_document(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "code": self.code,
            "condition": self.condition,
            "expected": self.expected,
            "actual": self.actual,
            "decisive_inputs": self.decisive_inputs,
        }


__all__ = ["AuthorFinding"]
