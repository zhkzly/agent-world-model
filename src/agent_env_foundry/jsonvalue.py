"""Structural JSON value checks for the environment contract (S1 Slice 1).

JSON here means the I-JSON data model: ``null``, booleans, numbers, strings,
arrays and objects with string keys. Non-finite floats (NaN, Infinity) have no
JSON serialization and are rejected. These checks are structural only; schema
conformance is handled by :mod:`agent_env_foundry.schema`.
"""

from __future__ import annotations

import math
from typing import Any

__all__ = ["is_json_object", "is_json_value", "json_leaf_changes"]


def is_json_value(value: Any) -> bool:
    """Return whether ``value`` is a structural JSON value."""
    if value is None or isinstance(value, (bool, str, int)):
        return True
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, list):
        return all(is_json_value(item) for item in value)
    if isinstance(value, dict):
        return all(isinstance(key, str) and is_json_value(item) for key, item in value.items())
    return False


def is_json_object(value: Any) -> bool:
    """Return whether ``value`` is a JSON object (string-keyed dict of values)."""
    if not isinstance(value, dict):
        return False
    return all(isinstance(key, str) and is_json_value(item) for key, item in value.items())


def json_leaf_changes(before: Any, after: Any, path: str = "") -> list[dict[str, Any]]:
    """Return every changed JSON leaf with deterministic pointer ordering."""

    if not is_json_value(before) or not is_json_value(after):
        raise ValueError("json_leaf_changes requires structural JSON values")
    if before == after:
        return []
    if isinstance(before, dict) and isinstance(after, dict):
        changes: list[dict[str, Any]] = []
        for key in sorted(set(before) | set(after)):
            escaped = key.replace("~", "~0").replace("/", "~1")
            child_path = f"{path}/{escaped}"
            if key not in before:
                changes.append(_presence_change(child_path, False, None, True, after[key]))
            elif key not in after:
                changes.append(_presence_change(child_path, True, before[key], False, None))
            else:
                changes.extend(json_leaf_changes(before[key], after[key], child_path))
        return changes
    if isinstance(before, list) and isinstance(after, list):
        changes = []
        for index in range(max(len(before), len(after))):
            child_path = f"{path}/{index}"
            if index >= len(before):
                changes.append(_presence_change(child_path, False, None, True, after[index]))
            elif index >= len(after):
                changes.append(_presence_change(child_path, True, before[index], False, None))
            else:
                changes.extend(json_leaf_changes(before[index], after[index], child_path))
        return changes
    return [_presence_change(path or "/", True, before, True, after)]


def _presence_change(
    path: str,
    before_present: bool,
    before: Any,
    after_present: bool,
    after: Any,
) -> dict[str, Any]:
    return {
        "path": path,
        "before_present": before_present,
        "before": before,
        "after_present": after_present,
        "after": after,
    }
