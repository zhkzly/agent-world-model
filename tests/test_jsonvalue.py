"""JSON value and JSON object structural enforcement (Slice 1)."""

from __future__ import annotations

import pytest

from agent_env_foundry.jsonvalue import is_json_object, is_json_value, json_leaf_changes


@pytest.mark.parametrize(
    "value",
    [
        None,
        True,
        False,
        0,
        -3,
        2.5,
        "",
        "text",
        [],
        [1, [2, {"k": None}]],
        {},
        {"a": 1, "b": [None, "x", {"c": False}]},
    ],
)
def test_accepts_json_values(value: object) -> None:
    assert is_json_value(value)


@pytest.mark.parametrize(
    "value",
    [
        float("nan"),
        float("inf"),
        float("-inf"),
        [float("nan")],
        {"a": float("inf")},
        {"a": {"b": [float("nan")]}},
    ],
)
def test_rejects_non_finite_numbers(value: object) -> None:
    # NaN/Infinity have no JSON serialization; they are not JSON values.
    assert not is_json_value(value)


@pytest.mark.parametrize(
    "value",
    [
        1j,
        b"bytes",
        bytearray(b"x"),
        object(),
        set(),
        frozenset(),
        (),
        ("a",),
        print,  # noqa: A001 - deliberately a function value
        {"a": object()},
        [[object()]],
    ],
)
def test_rejects_non_json_types(value: object) -> None:
    assert not is_json_value(value)


def test_object_keys_must_be_strings() -> None:
    assert not is_json_value({1: "a"})
    assert not is_json_value({"outer": {(1, 2): "nested"}})


def test_is_json_object_accepts_only_str_keyed_dicts() -> None:
    assert is_json_object({})
    assert is_json_object({"a": 1})
    assert not is_json_object([])
    assert not is_json_object("x")
    assert not is_json_object(None)
    assert not is_json_object(5)
    assert not is_json_object({1: "a"})
    assert not is_json_object({"a": object()})


def test_json_leaf_changes_are_complete_ordered_and_presence_aware() -> None:
    changes = json_leaf_changes(
        {"count": 1, "items": [{"id": "a", "ready": False}], "removed": 3},
        {
            "count": 2,
            "items": [{"id": "a", "ready": True}, {"id": "b"}],
            "added": None,
        },
    )

    assert [item["path"] for item in changes] == [
        "/added",
        "/count",
        "/items/0/ready",
        "/items/1",
        "/removed",
    ]
    assert changes[0] == {
        "path": "/added",
        "before_present": False,
        "before": None,
        "after_present": True,
        "after": None,
    }
    assert changes[-1]["after_present"] is False
