"""Framework-owned public candidate source and observation visibility policy."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Literal, Protocol

from pydantic import JsonValue

type CandidateComponentRole = Literal["runtime", "task_materializer", "public_verifier"]

_COMPONENT_DEPENDENCY_ROLES: dict[CandidateComponentRole, frozenset[str]] = {
    "runtime": frozenset({"runtime"}),
    "task_materializer": frozenset({"runtime", "task_materializer"}),
    "public_verifier": frozenset({"runtime", "task_materializer", "public_verifier"}),
}


class _RoleFile(Protocol):
    path: str
    role: str


def component_visible_paths(
    files: Iterable[_RoleFile],
    role: CandidateComponentRole,
) -> tuple[str, ...]:
    """Return the fixed one-way public source dependency closure for a component."""

    allowed_roles = _COMPONENT_DEPENDENCY_ROLES[role]
    paths = tuple(sorted(item.path for item in files if item.role in allowed_roles))
    if not paths:
        raise ValueError(f"candidate manifest declares no files for role {role}")
    return paths


def actor_projection_schema(
    schema: dict[str, JsonValue],
    visible_fields: tuple[str, ...],
) -> dict[str, Any]:
    """Compile one closed actor view while preserving local reference definitions."""

    properties = schema.get("properties")
    if not isinstance(properties, dict):
        raise ValueError("actor projection schema lacks properties")
    required_value = schema.get("required", [])
    visible = set(visible_fields)
    required = (
        [item for item in required_value if isinstance(item, str) and item in visible]
        if isinstance(required_value, list)
        else []
    )
    projected: dict[str, Any] = {
        "type": "object",
        "additionalProperties": False,
        "properties": {field: properties[field] for field in visible_fields},
        "required": required,
    }
    definitions = schema.get("$defs")
    if isinstance(definitions, dict):
        projected["$defs"] = definitions
    return projected


__all__ = [
    "CandidateComponentRole",
    "actor_projection_schema",
    "component_visible_paths",
]
