"""ToolSpec / ToolObservation contract types and catalog validation (Slice 1).

All environments here are mechanical fixtures exercising contract shape only;
none is a domain environment (PRD F8).
"""

from __future__ import annotations

from typing import Any

import pytest

from agent_env_foundry.environment import (
    CONTRACT_INVALID_ARGUMENTS,
    CONTRACT_UNKNOWN_TOOL,
    failure_observation,
    invalid_arguments_observation,
    is_contract_observation,
    success_observation,
    unknown_tool_observation,
    validate_observation,
    validate_tool_catalog,
)
from agent_env_foundry.errors import EnvironmentRuntimeError

OK_SPEC: dict[str, Any] = {
    "name": "t",
    "description": "mechanical tool",
    "input_schema": {"type": "object", "properties": {}, "required": []},
    "output_schema": {"type": "object"},
}


def make_spec(**overrides: Any) -> dict[str, Any]:
    spec = dict(OK_SPEC)
    spec.update(overrides)
    return spec


# ---------------------------------------------------------------- constructors


def test_success_observation_exact_shape() -> None:
    observation = success_observation({"a": 1})
    assert observation == {"ok": True, "data": {"a": 1}, "error": None}
    assert set(observation) == {"ok", "data", "error"}


def test_failure_observation_exact_shape() -> None:
    observation = failure_observation("sold_out", "no capacity", {"left": 0})
    assert observation == {
        "ok": False,
        "data": None,
        "error": {"code": "sold_out", "message": "no capacity", "details": {"left": 0}},
    }
    bare = failure_observation("sold_out", "no capacity")
    assert set(bare["error"]) == {"code", "message"}


def test_reserved_contract_observations() -> None:
    unknown = unknown_tool_observation("reserve")
    assert unknown["ok"] is False
    assert unknown["data"] is None
    assert unknown["error"]["code"] == CONTRACT_UNKNOWN_TOOL
    assert "reserve" in unknown["error"]["message"]

    invalid = invalid_arguments_observation("seed must be >= 0", tool_name="reset_world")
    assert invalid["error"]["code"] == CONTRACT_INVALID_ARGUMENTS
    assert invalid["data"] is None
    assert invalid["error"]["details"] == {"tool": "reset_world"}


def test_is_contract_observation_distinguishes_invalid_action() -> None:
    assert is_contract_observation(unknown_tool_observation("nope"))
    assert is_contract_observation(invalid_arguments_observation("bad"))
    assert not is_contract_observation(failure_observation("sold_out", "no capacity"))
    assert not is_contract_observation(success_observation(None))


# ------------------------------------------------------------------- variants


def test_validate_observation_accepts_both_valid_variants() -> None:
    validate_observation({"ok": True, "data": {}, "error": None}, OK_SPEC)
    validate_observation(
        {"ok": False, "data": None, "error": {"code": "sold_out", "message": "m"}},
        OK_SPEC,
    )
    validate_observation(
        {
            "ok": False,
            "data": None,
            "error": {"code": "sold_out", "message": "m", "details": {"left": 0}},
        },
        OK_SPEC,
    )


@pytest.mark.parametrize(
    "observation",
    [
        {"ok": True, "data": {}, "error": {"code": "x", "message": "m"}},
        {"ok": False, "data": {"v": 1}, "error": {"code": "x", "message": "m"}},
        {"ok": False, "data": None, "error": None},
        {"ok": False, "data": None},
        {"ok": True, "data": {}, "error": None, "call_id": "abc-1"},
        {"ok": "yes", "data": {}, "error": None},
        {"ok": 1, "data": {}, "error": None},
        {"ok": False, "data": None, "error": {"message": "missing code"}},
        {"ok": False, "data": None, "error": {"code": "", "message": "m"}},
        {"ok": False, "data": None, "error": {"code": 7, "message": "m"}},
        {"ok": False, "data": None, "error": {"code": "x"}},
        {"ok": False, "data": None, "error": {"code": "x", "message": "m", "extra": 1}},
        {"ok": False, "data": None, "error": "not-a-dict"},
        {"ok": False, "data": None, "error": {"code": "x", "message": "m", "details": print}},
        {"ok": True, "data": print, "error": None},
        {"ok": True, "data": 5, "error": None},  # violates object output_schema
        None,
        "observation",
        (),
    ],
)
def test_validate_observation_rejects_invalid_variants(observation: Any) -> None:
    with pytest.raises(EnvironmentRuntimeError):
        validate_observation(observation, OK_SPEC)


def test_validate_observation_rejects_contract_namespace_squat() -> None:
    squat = {
        "ok": False,
        "data": None,
        "error": {"code": "contract.sold_out", "message": "domain refusal"},
    }
    with pytest.raises(EnvironmentRuntimeError, match="contract"):
        validate_observation(squat, OK_SPEC)


# -------------------------------------------------------------------- catalog


def test_validate_tool_catalog_builds_name_index() -> None:
    other = make_spec(name="other")
    index = validate_tool_catalog((OK_SPEC, other))
    assert set(index) == {"t", "other"}
    assert index["t"] == OK_SPEC


def test_validate_tool_catalog_canonicalizes_missing_input_object_root() -> None:
    raw = make_spec(
        input_schema={
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        }
    )

    normalized = validate_tool_catalog((raw,))["t"]

    assert normalized["input_schema"] == {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    }
    assert "type" not in raw["input_schema"]


def test_validate_tool_catalog_canonicalizes_equivalent_object_schema_forms() -> None:
    raw = make_spec(input_schema={"type": ["object"]})

    normalized = validate_tool_catalog((raw,))["t"]

    assert normalized["input_schema"] == {
        "type": "object",
        "properties": {},
        "required": [],
    }


def test_validate_tool_catalog_extracts_exact_wrapped_success_data_schema() -> None:
    data_schema = {
        "type": "object",
        "properties": {"count": {"type": "integer"}},
        "required": ["count"],
    }
    wrapped = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$defs": {"detail": {"type": "string"}},
        "anyOf": [
            {
                "type": "object",
                "properties": {
                    "ok": {"const": True},
                    "data": data_schema,
                    "error": {"type": "null"},
                },
                "required": ["ok", "data", "error"],
            },
            {
                "type": "object",
                "properties": {
                    "ok": {"const": False},
                    "data": {"type": "null"},
                    "error": {"type": "object"},
                },
                "required": ["ok", "data", "error"],
            },
        ],
    }

    normalized = validate_tool_catalog((make_spec(output_schema=wrapped),))["t"]

    assert normalized["output_schema"] == {
        **data_schema,
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$defs": {"detail": {"type": "string"}},
    }
    assert "anyOf" in wrapped


@pytest.mark.parametrize(
    "specs",
    [
        (OK_SPEC, make_spec()),
        (make_spec(), make_spec()),
        (make_spec(name=""),),
        (make_spec(name=7),),
        (make_spec(description=7),),
        (make_spec(input_schema={"type": "string"}),),
        (make_spec(input_schema={"type": "object", "properties": {"a": {"$ref": "http://e/x"}}}),),
        (make_spec(output_schema={"$ref": "http://e/y"}),),
        (make_spec(input_schema={"type": 3}),),
        (make_spec(output_schema={"type": 3}),),
        ("not-a-spec",),
        (None,),
    ],
)
def test_validate_tool_catalog_rejects_faulty_catalogs(specs: Any) -> None:
    with pytest.raises(EnvironmentRuntimeError):
        validate_tool_catalog(specs)


def test_validate_tool_catalog_requires_a_tuple() -> None:
    with pytest.raises(EnvironmentRuntimeError, match="tuple"):
        validate_tool_catalog([OK_SPEC])
