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
    "require_object_root",
    "validate_instance",
    "validate_schema_document",
    "validate_strict_output_schema",
]

# Keywords whose values are URIs/URI references; release schemas may only use
# same-document fragment references for them.
_REFERENCE_KEYS = ("$ref", "$dynamicRef")


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


def validate_strict_output_schema(schema: Any, *, role: str) -> None:
    """Require the recursive shape accepted by strict Responses structured output."""

    validate_schema_document(schema, role=role)
    pending: list[tuple[Any, str]] = [(schema, "$")]
    while pending:
        node, path = pending.pop()
        if not isinstance(node, dict):
            raise SchemaError(f"{role} strict structured output schema at {path} must be an object")
        raw_types = node.get("type")
        types = (
            {raw_types}
            if isinstance(raw_types, str)
            else set(raw_types)
            if isinstance(raw_types, list)
            else set()
        )
        if "array" in types:
            items = node.get("items")
            if not isinstance(items, dict):
                raise SchemaError(f"{role} strict structured output array at {path} requires items")
            pending.append((items, f"{path}.items"))
        if "object" in types:
            properties = node.get("properties")
            required = node.get("required")
            if (
                not isinstance(properties, dict)
                or node.get("additionalProperties") is not False
                or not isinstance(required, list)
                or set(required) != set(properties)
            ):
                raise SchemaError(
                    f"{role} strict structured output object at {path} requires properties, "
                    "all properties in required, and additionalProperties=false"
                )
            pending.extend(
                (child, f"{path}.properties.{name}") for name, child in properties.items()
            )
        for keyword in ("anyOf", "oneOf", "allOf"):
            branches = node.get(keyword)
            if branches is None:
                continue
            if not isinstance(branches, list):
                raise SchemaError(
                    f"{role} strict structured output {keyword} at {path} must be an array"
                )
            pending.extend(
                (branch, f"{path}.{keyword}[{index}]") for index, branch in enumerate(branches)
            )
        definitions = node.get("$defs")
        if definitions is not None:
            if not isinstance(definitions, dict):
                raise SchemaError(
                    f"{role} strict structured output $defs at {path} must be an object"
                )
            pending.extend((child, f"{path}.$defs.{name}") for name, child in definitions.items())


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
