"""Draft 2020-12 schema handling: self-containment, roots, validation (Slice 1)."""

from __future__ import annotations

import pytest

from agent_env_foundry.schema import (
    SchemaError,
    require_object_root,
    validate_instance,
    validate_schema_document,
)

LOCAL_REF_SCHEMA = {
    "type": "object",
    "properties": {"value": {"$ref": "#/$defs/thing"}},
    "additionalProperties": False,
    "$defs": {"thing": {"type": "integer"}},
}


def test_valid_document_with_local_fragment_ref() -> None:
    validate_schema_document(LOCAL_REF_SCHEMA, role="test schema")


def test_property_names_that_look_like_reference_keywords_are_legal() -> None:
    schema = {
        "type": "object",
        "properties": {
            "$ref": {"type": "string"},
            "$dynamicRef": {"type": "integer"},
        },
        "additionalProperties": False,
    }
    validate_schema_document(schema, role="literal reference-name properties")
    validate_instance(
        {"$ref": "ordinary data", "$dynamicRef": 3},
        schema,
        role="literal reference-name value",
    )


@pytest.mark.parametrize(
    "schema",
    [
        {"type": 3},
        {"properties": "no"},
        {"required": [1]},
        {"minimum": "x"},
        {"type": "object", "properties": {"a": {"type": "strin"}}},
    ],
)
def test_metaschema_violations_rejected(schema: object) -> None:
    with pytest.raises(SchemaError):
        validate_schema_document(schema, role="test schema")


def test_schema_document_must_be_a_json_object() -> None:
    # Boolean schemas are legal Draft 2020-12 but ToolSpec/start members require
    # an object schema document.
    with pytest.raises(SchemaError):
        validate_schema_document(True, role="test schema")
    with pytest.raises(SchemaError):
        validate_schema_document([], role="test schema")
    with pytest.raises(SchemaError):
        validate_schema_document({1: "non-string key"}, role="test schema")


@pytest.mark.parametrize(
    "ref",
    [
        "http://example.com/schema.json",
        "https://example.com/s.json#/definitions/x",
        "other.json",
        "other.json#/$defs/x",
        "/absolute/path.json",
        "urn:uuid:6f2f1c1c-0000-4000-8000-97a4c4bb2c11",
        "//example.com/shared",
        "",
        "schema.json",
    ],
)
def test_remote_or_nonlocal_refs_rejected(ref: str) -> None:
    schema = {"type": "object", "properties": {"v": {"$ref": ref}}}
    with pytest.raises(SchemaError, match="local"):
        validate_schema_document(schema, role="test schema")


def test_dynamic_ref_remote_rejected() -> None:
    schema = {"type": "object", "$dynamicRef": "http://example.com/d.json"}
    with pytest.raises(SchemaError, match="local"):
        validate_schema_document(schema, role="test schema")


def test_refs_inside_nested_containers_are_checked() -> None:
    schema = {
        "type": "object",
        "properties": {"a": {"type": "array", "items": {"$ref": "http://example.com/x"}}},
        "$defs": {"nested": {"allOf": [{"$ref": "../sibling.json"}]}},
    }
    with pytest.raises(SchemaError, match="local"):
        validate_schema_document(schema, role="test schema")


def test_dangling_local_ref_fails_at_validation_time() -> None:
    with pytest.raises(SchemaError, match="unresolvable|resolve"):
        validate_instance(1, {"$ref": "#/$defs/missing"}, role="dangling")


def test_require_object_root() -> None:
    require_object_root({"type": "object"}, role="start schema")
    require_object_root(LOCAL_REF_SCHEMA, role="start schema")
    for schema in (
        {},
        {"type": "string"},
        {"type": ["object", "null"]},
        {"type": ["object"]},
        {"properties": {}},
    ):
        with pytest.raises(SchemaError, match="object"):
            require_object_root(schema, role="start schema")


def test_validate_instance_accepts_valid_and_rejects_invalid() -> None:
    validate_instance({"value": 3}, LOCAL_REF_SCHEMA, role="test value")
    for bad in (5, "x", None, [], {"value": "not-an-int"}, {"value": 3, "extra": 1}):
        with pytest.raises(SchemaError):
            validate_instance(bad, LOCAL_REF_SCHEMA, role="test value")


def test_validate_instance_error_names_the_role() -> None:
    schema = {"type": "object", "properties": {"seed": {"minimum": 0}}}
    with pytest.raises(SchemaError, match="reset start"):
        validate_instance({"seed": -1}, schema, role="reset start")


def test_validate_instance_bool_is_not_integer() -> None:
    with pytest.raises(SchemaError):
        validate_instance(True, {"type": "integer"}, role="strict bool/int")
