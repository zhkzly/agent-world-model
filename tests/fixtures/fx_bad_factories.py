"""Mechanical fixtures with deliberately broken factories for negative tests.

These exist only so the loader can be tested against factory-spec violations.
They are not domain environments and never qualify anything (PRD F8).
"""

from __future__ import annotations

from typing import Any


class _IncompleteEnvironment:
    """Implements only ``reset``; missing tools/invoke/close."""

    def reset(self, start: dict[str, Any] | None = None) -> dict[str, Any]:
        return {"kind": "mechanical"}


def make_incomplete(instance_directory: Any) -> _IncompleteEnvironment:
    return _IncompleteEnvironment()


def make_non_environment(instance_directory: Any) -> int:
    return 42


NOT_CALLABLE: int = 7
