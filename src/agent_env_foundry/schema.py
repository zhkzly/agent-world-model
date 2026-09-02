"""JSON Schema Draft 2020-12 handling for release-bound schemas (S1 Slice 1).

Release schemas must be self-contained: any ``$ref``/``$dynamicRef`` may point
at a local fragment (``#...``) inside the same schema document, never at a
remote or sibling resource. Validation itself is owned by the mature
``jsonschema`` library; this module adds the self-containment and object-root
rules the release contract imposes on top of Draft 2020-12.
"""

from __future__ import annotations

from typing import Any

from jsonschema.exceptions import SchemaError as MetaschemaError
from jsonschema.validators import Draft202012Validator
from referencing.exceptions import Unresolvable
from referencing.jsonschema import DRAFT202012

from agent_env_foundry.jsonvalue import is_json_object

__all__ = [
    "SchemaError",
    "project_responses_strict_schema",
    "require_object_root",
    "validate_instance",
    "validate_schema_document",
]

# Keywords whose values are URIs/URI references; release schemas may only use
# same-document fragment references for them.
_REFERENCE_KEYS = ("$ref", "$dynamicRef")
_RESPONSES_UNSUPPORTED_KEYS = frozenset(
    {
        "$anchor",
        "$dynamicAnchor",
        "$dynamicRef",
        "$id",
        "$schema",
        "additionalItems",
        "allOf",
        "contains",
        "default",
        "dependentRequired",
        "dependentSchemas",
        "deprecated",
        "else",
        "examples",
        "if",
        "maxContains",
        "maxProperties",
        "minContains",
        "minProperties",
        "not",
        "oneOf",
        "patternProperties",
        "prefixItems",
        "propertyNames",
        "readOnly",
        "then",
        "title",
        "unevaluatedItems",
        "unevaluatedProperties",
        "uniqueItems",
        "writeOnly",
    }
)


class SchemaError(ValueError):
    """A schema document or validated instance violates the schema rules."""


def validate_schema_document(schema: Any, *, role: str) -> None:
    """Check that ``schema`` is a self-contained Draft 2020-12 object schema."""
    if not is_json_object(schema):
        raise SchemaError(f"{role} schema must be a JSON object, got {type(schema).__name__}")
    try:
        Draft202012Validator.check_schema(schema)
    except MetaschemaError as exc:
        raise SchemaError(f"{role} schema is not a valid Draft 2020-12 schema: {exc}") from exc
    _require_local_references(schema, role=role)


def require_object_root(schema: Any, *, role: str) -> None:
    """Require the schema to describe object instances at its root."""
    validate_schema_document(schema, role=role)
    if not isinstance(schema, dict) or schema.get("type") != "object":
        raise SchemaError(
            f'{role} schema must have root "type": "object" '
            f"(exactly the string), got {schema.get('type')!r}"
        )


def project_responses_strict_schema(schema: Any) -> dict[str, Any]:
    """Project full Draft 2020-12 semantics onto the strict Responses wire subset.

    The original schema remains the Host validator. The projection removes
    unsupported constraints and closes every object as the wire protocol
    requires; Host validation still rejects any final value that violates the
    frozen schema. This adapter never becomes Task semantic authority.
    """

    validate_schema_document(schema, role="Responses source")
    projected = _project_responses_node(schema, path="$")
    validate_schema_document(projected, role="Responses projection")
    return projected


def validate_instance(instance: Any, schema: Any, *, role: str) -> None:
    """Validate ``instance`` against an already-validated schema document."""
    validator = Draft202012Validator(schema)
    try:
        error = next(validator.iter_errors(instance), None)
    except Unresolvable as exc:
        raise SchemaError(f"{role} schema contains an unresolvable local reference: {exc}") from exc
    if error is not None:
        location = "$" + "".join(f"[{part!r}]" for part in error.absolute_path)
        raise SchemaError(f"{role} does not match its schema at {location}: {error.message}")


def _require_local_references(node: Any, *, role: str) -> None:
    """Inspect references only at actual schema-resource positions.

    ``properties`` and similar keywords contain maps whose keys are user field
    names. A generic dict walk would therefore misread a legitimate property
    named ``$ref`` as the JSON Schema keyword. ``referencing`` owns Draft
    2020-12 subresource discovery and keeps that distinction correct.
    """

    pending = [DRAFT202012.create_resource(node)]
    while pending:
        resource = pending.pop()
        contents = resource.contents
        if isinstance(contents, dict):
            for key in _REFERENCE_KEYS:
                if key not in contents:
                    continue
                value = contents[key]
                if not isinstance(value, str) or not value.startswith("#"):
                    raise SchemaError(
                        f"{role} schema uses non-local reference {value!r}; only local "
                        "fragment references (#...) are permitted in release schemas"
                    )
        pending.extend(resource.subresources())


def _project_responses_node(node: dict[str, Any], *, path: str) -> dict[str, Any]:
    contains = node.get("contains")
    projected = {
        key: value for key, value in node.items() if key not in _RESPONSES_UNSUPPORTED_KEYS
    }
    constant = projected.get("const")
    if isinstance(constant, (dict, list)):
        projected.pop("const")
        for key, value in _json_shape(constant).items():
            projected.setdefault(key, value)
    elif "const" in projected and "type" not in projected:
        projected["type"] = _json_type(constant)

    properties = projected.get("properties")
    if isinstance(properties, dict):
        projected["properties"] = {
            key: _project_responses_node(value, path=f"{path}.properties[{key!r}]")
            for key, value in properties.items()
            if isinstance(key, str) and isinstance(value, dict)
        }
    definitions = projected.get("$defs")
    if isinstance(definitions, dict):
        projected["$defs"] = {
            key: _project_responses_node(value, path=f"{path}.$defs[{key!r}]")
            for key, value in definitions.items()
            if isinstance(key, str) and isinstance(value, dict)
        }
    items = projected.get("items")
    if isinstance(items, dict):
        projected["items"] = _project_responses_node(items, path=f"{path}.items")
    alternatives = projected.get("anyOf")
    if isinstance(alternatives, list):
        projected["anyOf"] = [
            _project_responses_node(value, path=f"{path}.anyOf[{index}]")
            for index, value in enumerate(alternatives)
            if isinstance(value, dict)
        ]

    node_type = projected.get("type")
    if node_type == "array" or isinstance(node_type, list) and "array" in node_type:
        if "items" not in projected:
            if isinstance(contains, dict):
                projected["items"] = _project_responses_node(
                    contains,
                    path=f"{path}.items",
                )
            else:
                raise SchemaError(f"Responses strict schema array at {path} requires items")
    if (
        node_type == "object"
        or isinstance(node_type, list)
        and "object" in node_type
        or "properties" in projected
    ):
        object_properties = projected.get("properties")
        if not isinstance(object_properties, dict):
            object_properties = {}
            projected["properties"] = object_properties
        projected["required"] = list(object_properties)
        projected["additionalProperties"] = False
    return projected


def _json_shape(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return {
            "type": "object",
            "properties": {key: _json_shape(child) for key, child in value.items()},
            "required": list(value),
            "additionalProperties": False,
        }
    if isinstance(value, list):
        item_types = sorted({_json_type(item) for item in value}) or ["string"]
        items = (
            {"type": item_types[0]}
            if len(item_types) == 1
            else {"anyOf": [{"type": item} for item in item_types]}
        )
        return {"type": "array", "items": items}
    return {"type": _json_type(value)}


def _json_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    return "object"
