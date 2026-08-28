from __future__ import annotations

import pytest

from agent_env_foundry.semantics import JSONValue
from agent_task_foundry.facets import (
    FacetValueError,
    compare_facet_values,
    extreme_facet_value,
)


def test_numeric_facets_share_one_finite_numeric_domain() -> None:
    assert compare_facet_values(1, "lt", 1.5)
    assert compare_facet_values(2.0, "gte", 2)
    assert extreme_facet_value([1, 2.5, -3], "max") == 2.5
    assert extreme_facet_value([1, 2.5, -3], "min") == -3


def test_string_facets_compare_lexically() -> None:
    assert compare_facet_values("alpha", "lt", "beta")
    assert compare_facet_values("beta", "gte", "beta")
    assert extreme_facet_value(["beta", "alpha", "gamma"], "min") == "alpha"
    assert extreme_facet_value(["beta", "alpha", "gamma"], "max") == "gamma"


@pytest.mark.parametrize(
    ("left", "right"),
    [
        (1, "2"),
        (True, 1),
        (None, 1),
        ([], []),
        ({}, {}),
    ],
)
def test_ordering_rejects_mixed_or_non_scalar_facets(
    left: JSONValue,
    right: JSONValue,
) -> None:
    with pytest.raises(FacetValueError):
        compare_facet_values(left, "lt", right)


@pytest.mark.parametrize("values", [[1, "2"], [True, 1], [None], [[]], [{}]])
def test_ranking_rejects_heterogeneous_or_non_scalar_facets(
    values: list[JSONValue],
) -> None:
    with pytest.raises(FacetValueError):
        extreme_facet_value(values, "max")


def test_equality_remains_available_for_all_json_values() -> None:
    assert compare_facet_values([1], "eq", [1])
    assert compare_facet_values({"a": 1}, "neq", {"a": 2})


def test_unsupported_operator_is_a_contract_error() -> None:
    with pytest.raises(FacetValueError, match="unsupported comparison operator"):
        compare_facet_values(1, "contains", 1)
