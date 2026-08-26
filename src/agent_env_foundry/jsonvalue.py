"""Structural JSON value checks for the environment contract (S1 Slice 1).

JSON here means the I-JSON data model: ``null``, booleans, numbers, strings,
arrays and objects with string keys. Non-finite floats (NaN, Infinity) have no
JSON serialization and are rejected. These checks are structural only; schema
conformance is handled by :mod:`agent_env_foundry.schema`.
"""

from __future__ import annotations

import math
from typing import Any

__all__ = ["is_json_object", "is_json_value"]


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
