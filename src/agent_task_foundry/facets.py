"""Closed comparison semantics for selector facets.

Ordering is intentionally limited to homogeneous strings or homogeneous numeric
values. Integers and finite floats share one numeric domain; booleans are never
numbers for Task semantics. Equality remains available for any JSON value.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Literal, TypeGuard

from agent_env_foundry.semantics import JSONValue

OrderOperator = Literal["lt", "lte", "gt", "gte"]
ExtremeDirection = Literal["min", "max"]
Numeric = int | float


class FacetValueError(ValueError):
    """Facet values or an operator do not form a deterministic comparison."""


def compare_facet_values(left: JSONValue, operator: str, right: JSONValue) -> bool:
    """Compare two facet values under the closed selector contract.

    ``eq`` and ``neq`` preserve JSON-value equality. Ordering operators accept
    only two finite numeric values or two strings. Invalid ordering is a contract
    error, not a non-match.
    """

    if operator == "eq":
        return left == right
    if operator == "neq":
        return left != right
    if operator not in {"lt", "lte", "gt", "gte"}:
        raise FacetValueError(f"unsupported comparison operator {operator!r}")

    if _is_numeric(left) and _is_numeric(right):
        return _apply_numeric_order(left, operator, right)
    if isinstance(left, str) and isinstance(right, str):
        return _apply_string_order(left, operator, right)
    raise FacetValueError(
        "ordered facet comparison requires two finite numbers or two strings; "
        f"got {type(left).__name__} and {type(right).__name__}"
    )


def extreme_facet_value(
    values: Sequence[JSONValue],
    direction: ExtremeDirection,
) -> JSONValue:
    """Return a deterministic extreme from one homogeneous comparable domain."""

    if direction not in {"min", "max"}:
        raise FacetValueError(f"unsupported rank direction {direction!r}")
    if not values:
        raise FacetValueError("cannot rank an empty facet value sequence")

    first = values[0]
    if _is_numeric(first):
        numeric_values: list[Numeric] = [first]
        for value in values[1:]:
            if not _is_numeric(value):
                raise FacetValueError(
                    "rank facet mixes numeric and non-numeric values: "
                    f"{type(first).__name__} and {type(value).__name__}"
                )
            numeric_values.append(value)
        return min(numeric_values) if direction == "min" else max(numeric_values)

    if isinstance(first, str):
        string_values: list[str] = [first]
        for value in values[1:]:
            if not isinstance(value, str):
                raise FacetValueError(
                    f"rank facet mixes string and non-string values: str and {type(value).__name__}"
                )
            string_values.append(value)
        return min(string_values) if direction == "min" else max(string_values)

    raise FacetValueError(
        f"rank facet values must be finite numbers or strings; got {type(first).__name__}"
    )


def _is_numeric(value: object) -> TypeGuard[Numeric]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return not isinstance(value, float) or math.isfinite(value)


def _apply_numeric_order(left: Numeric, operator: OrderOperator, right: Numeric) -> bool:
    if operator == "lt":
        return left < right
    if operator == "lte":
        return left <= right
    if operator == "gt":
        return left > right
    return left >= right


def _apply_string_order(left: str, operator: OrderOperator, right: str) -> bool:
    if operator == "lt":
        return left < right
    if operator == "lte":
        return left <= right
    if operator == "gt":
        return left > right
    return left >= right
