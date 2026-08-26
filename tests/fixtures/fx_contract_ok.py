"""Mechanical contract fixture for the Environment API surface.

This module implements the canonical ``reset/tools/invoke/close`` shape with a
counter/echo behavior purely so contract validation can be exercised. It is NOT
a domain environment, its release directories are NOT qualified
``EnvironmentRelease`` artifacts, and it must never be used as
product-completion evidence (PRD F8).
"""

from __future__ import annotations

from typing import Any

from release_factory import DEFAULT_RESET_OBSERVATION_SCHEMA, DEFAULT_START_SCHEMA

# Published alongside the mechanical release built by tests/release_factory.py.
START_SCHEMA: dict[str, Any] = DEFAULT_START_SCHEMA
RESET_OBSERVATION_SCHEMA: dict[str, Any] = DEFAULT_RESET_OBSERVATION_SCHEMA

NEXT_VALUE_SPEC: dict[str, Any] = {
    "name": "next_value",
    "description": "Advance the mechanical counter and observe its value.",
    "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    "output_schema": {
        "type": "object",
        "properties": {"value": {"type": "integer"}},
        "required": ["value"],
        "additionalProperties": False,
    },
}
ECHO_SPEC: dict[str, Any] = {
    "name": "echo",
    "description": "Return the supplied JSON value unchanged.",
    "input_schema": {
        "type": "object",
        "properties": {"value": {}},
        "required": ["value"],
        "additionalProperties": False,
    },
    "output_schema": {
        "type": "object",
        "properties": {"value": {}},
        "required": ["value"],
    },
}
REFUSE_SPEC: dict[str, Any] = {
    "name": "refuse",
    "description": "Return a business-refusal observation without mutating anything.",
    "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    "output_schema": {},
}


class MechanicalEnvironment:
    """Contract-conformant mechanical environment recording every call."""

    def __init__(self, instance_directory: Any) -> None:
        self.instance_directory = instance_directory
        self.calls: list[tuple[Any, ...]] = []
        self._counter = 0

    def reset(self, start: dict[str, Any] | None = None) -> dict[str, Any]:
        self.calls.append(("reset", start))
        self._counter = 0
        seed = start.get("seed") if start is not None else None
        return {"kind": "mechanical", "token": 1, "started": start is not None, "seed": seed}

    def tools(self) -> tuple[dict[str, Any], ...]:
        self.calls.append(("tools", None))
        return (NEXT_VALUE_SPEC, ECHO_SPEC, REFUSE_SPEC)

    def invoke(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("invoke", tool_name, arguments))
        if tool_name == "next_value":
            self._counter += 1
            return {"ok": True, "data": {"value": self._counter}, "error": None}
        if tool_name == "echo":
            return {"ok": True, "data": {"value": arguments["value"]}, "error": None}
        if tool_name == "refuse":
            return {
                "ok": False,
                "data": None,
                "error": {
                    "code": "mechanical_refusal",
                    "message": "refused by the mechanical fixture",
                    "details": {"permanent": True},
                },
            }
        raise AssertionError(f"mechanical fixture was dispatched unknown tool {tool_name!r}")

    def close(self) -> None:
        self.calls.append(("close", None))


def make_environment(instance_directory: Any) -> MechanicalEnvironment:
    """Standard ``module:factory`` entry point for loader tests."""
    return MechanicalEnvironment(instance_directory)
