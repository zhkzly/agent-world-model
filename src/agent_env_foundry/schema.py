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
