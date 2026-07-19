"""Deterministic schema closure for executable Rule references.

The Agent chooses business relations.  Framework code proves that every direct
reference and bounded collection selector can actually resolve against the
frozen execution-context schemas before Builder receives the design.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, cast

from pydantic import JsonValue

from agent_world.contracts import (
    Rule,
    RuleArithmetic,
    RuleConstant,
    RuleLookupByKey,
    RuleTerm,
    RuleValueRef,
    RuleValueType,
    StateSchema,
    ToolSurface,
)
from agent_world.control.validation import SafeValidationIssue


@dataclass(frozen=True, slots=True)
class RuleContextCatalog:
    """Frozen schema roots and primary-key identities visible to one tool."""

    schemas: dict[str, dict[str, JsonValue]]
    collection_keys: dict[str, tuple[str, ...]]
    collection_fields: dict[str, tuple[str, ...]]

    @classmethod
    def for_tool(cls, *, state: StateSchema, surface: ToolSurface) -> RuleContextCatalog:
        collection_keys: dict[str, tuple[str, ...]] = {}
        collection_fields: dict[str, tuple[str, ...]] = {}
        properties = state.root_state_schema.get("properties")
        if isinstance(properties, dict):
            for root_name, root_schema in properties.items():
                if not isinstance(root_name, str) or not isinstance(root_schema, dict):
                    continue
                if root_schema.get("type") != "array":
                    continue
                items = root_schema.get("items")
                if not isinstance(items, dict):
                    continue
                item_properties = items.get("properties")
                if isinstance(item_properties, dict):
                    collection_fields[f"/{_escape_token(root_name)}"] = tuple(
                        sorted(str(key) for key in item_properties)
                    )
                matches = tuple(
                    entity
                    for entity in state.entities
                    if entity.json_schema == items
                )
                if len(matches) == 1:
                    collection_keys[f"/{_escape_token(root_name)}"] = matches[0].primary_key_fields
        return cls(
            schemas={
                "args": surface.input_schema,
                "tool_result": surface.output_schema,
                "observation": surface.observation_schema,
                "pre_state": state.root_state_schema,
                "post_state": state.root_state_schema,
            },
            collection_keys=collection_keys,
            collection_fields=collection_fields,
        )

    def prompt_projection(self) -> dict[str, object]:
        """Bounded non-secret selector catalog for the semantic Agent prompt."""

        return {
            "collections": [
                {
                    "collection_pointer": pointer,
                    "primary_key_fields": list(self.collection_keys.get(pointer, ())),
                    "item_fields": list(self.collection_fields.get(pointer, ())),
                }
                for pointer in sorted(self.collection_fields)
            ]
        }


@dataclass(frozen=True, slots=True)
class _Resolution:
    schema: dict[str, JsonValue] | None
    failure: Literal["missing", "selector_required", "invalid_schema"] | None = None


def validate_rule_context(
    rule: Rule,
    *,
    catalog: RuleContextCatalog,
) -> tuple[SafeValidationIssue, ...]:
    """Return every safe reference/selector closure issue in one Rule."""

    issues: list[SafeValidationIssue] = []

    def validate_term(term: RuleTerm, path: tuple[str | int, ...]) -> None:
        if isinstance(term, RuleConstant):
            return
        if isinstance(term, RuleValueRef):
            schema = catalog.schemas.get(term.source)
            if schema is None:
                return
            resolution = _resolve_schema_pointer(schema, term.pointer)
            if resolution.failure is not None:
                issues.append(
                    _reference_failure(
                        path=path,
                        pointer_path=(*path, "pointer"),
                        failure=resolution.failure,
                    )
                )
                return
            assert resolution.schema is not None
            _validate_declared_type(
                term.value_type,
                resolution.schema,
                path=(*path, "value_type"),
                issues=issues,
            )
            return
        if isinstance(term, RuleLookupByKey):
            validate_term(term.key, (*path, "key"))
            root = catalog.schemas.get(term.source)
            if root is None:
                return
            collection = _resolve_schema_pointer(root, term.collection_pointer)
            if collection.failure is not None or collection.schema is None:
                issues.append(
                    _reference_failure(
                        path=path,
                        pointer_path=(*path, "collection_pointer"),
                        failure=collection.failure or "missing",
                    )
                )
                return
            if collection.schema.get("type") != "array" or not isinstance(
                collection.schema.get("items"), dict
            ):
                issues.append(
                    SafeValidationIssue(
                        code="rule_lookup_collection_not_array",
                        location=(*path, "collection_pointer"),
                        message="lookup_by_key must target an array with an object item schema.",
                        violated_condition="the selector collection target is not an array",
                        expected_category=_allowed_collection_expectation(catalog),
                    )
                )
                return
            item_schema = collection.schema["items"]
            assert isinstance(item_schema, dict)
            item_properties = item_schema.get("properties")
            key_schema = (
                item_properties.get(term.key_field)
                if isinstance(item_properties, dict)
                else None
            )
            if not isinstance(key_schema, dict):
                declared_fields = (
                    tuple(sorted(str(key) for key in item_properties))
                    if isinstance(item_properties, dict)
                    else ()
                )
                issues.append(
                    SafeValidationIssue(
                        code="rule_lookup_key_field_missing",
                        location=(*path, "key_field"),
                        message="lookup_by_key key_field must exist in the collection item schema.",
                        violated_condition="the selector key_field is absent from item properties",
                        expected_category=_bounded_expectation(
                            "one of the item fields",
                            declared_fields,
                        ),
                    )
                )
            allowed_keys = catalog.collection_keys.get(term.collection_pointer)
            if allowed_keys is not None and term.key_field not in allowed_keys:
                issues.append(
                    SafeValidationIssue(
                        code="rule_lookup_key_not_primary",
                        location=(*path, "key_field"),
                        message="lookup_by_key must use a frozen primary-key field.",
                        violated_condition="the selector key_field is not a collection primary key",
                        expected_category=_bounded_expectation(
                            "one of the frozen primary-key fields",
                            allowed_keys,
                        ),
                    )
                )
            value = _resolve_schema_pointer(item_schema, term.value_pointer)
            if value.failure is not None or value.schema is None:
                if value.failure == "missing" and isinstance(item_properties, dict):
                    issues.append(
                        SafeValidationIssue(
                            code="rule_pointer_unreachable",
                            location=(*path, "value_pointer"),
                            message="The pointer does not resolve in the collection item schema.",
                            violated_condition="the selected-record field path does not exist",
                            expected_category=_bounded_expectation(
                                "one of the item pointers",
                                tuple(
                                    f"/{_escape_token(str(key))}"
                                    for key in sorted(item_properties)
                                ),
                            ),
                        )
                    )
                else:
                    issues.append(
                        _reference_failure(
                            path=path,
                            pointer_path=(*path, "value_pointer"),
                            failure=value.failure or "missing",
                        )
                    )
            else:
                _validate_declared_type(
                    term.value_type,
                    value.schema,
                    path=(*path, "value_type"),
                    issues=issues,
                )
            if isinstance(key_schema, dict):
                key_type = _term_declared_type(term.key)
                if key_type is not None:
                    _validate_declared_type(
                        key_type,
                        key_schema,
                        path=(*path, "key", "value_type"),
                        issues=issues,
                    )
            return
        if isinstance(term, RuleArithmetic):
            validate_term(term.left, (*path, "left"))
            validate_term(term.right, (*path, "right"))
            return
        raise TypeError(f"unsupported Rule term: {type(term).__name__}")

    for clause_index, clause in enumerate(rule.clauses):
        validate_term(clause.left, ("clauses", clause_index, "left"))
        if clause.right is not None:
            validate_term(clause.right, ("clauses", clause_index, "right"))
    return tuple(dict.fromkeys(issues))


def _resolve_schema_pointer(schema: dict[str, JsonValue], pointer: str) -> _Resolution:
    current = schema
    if pointer == "":
        return _Resolution(current)
    for raw_token in pointer.removeprefix("/").split("/"):
        token = raw_token.replace("~1", "/").replace("~0", "~")
        schema_type = current.get("type")
        if schema_type == "object":
            properties = current.get("properties")
            child = properties.get(token) if isinstance(properties, dict) else None
            if not isinstance(child, dict):
                return _Resolution(None, "missing")
            current = child
            continue
        if schema_type == "array":
            if not token.isdecimal():
                return _Resolution(None, "selector_required")
            items = current.get("items")
            if not isinstance(items, dict):
                return _Resolution(None, "invalid_schema")
            current = items
            continue
        return _Resolution(None, "missing")
    return _Resolution(current)


def _reference_failure(
    *,
    path: tuple[str | int, ...],
    pointer_path: tuple[str | int, ...],
    failure: Literal["missing", "selector_required", "invalid_schema"],
) -> SafeValidationIssue:
    if failure == "selector_required":
        return SafeValidationIssue(
            code="rule_pointer_requires_selector",
            location=pointer_path,
            message="A direct JSON pointer cannot select a dynamic collection record.",
            violated_condition="the pointer traverses an array without a fixed index or selector",
            expected_category="lookup_by_key for dynamic state records or a fixed numeric index",
        )
    if failure == "invalid_schema":
        return SafeValidationIssue(
            code="framework_rule_context_schema_invalid",
            location=path,
            message="The frozen Rule context catalog contains an unsupported array schema.",
            retryable=False,
            violated_condition="the framework context schema has no single item schema",
            expected_category="one closed array item schema",
        )
    return SafeValidationIssue(
        code="rule_pointer_unreachable",
        location=pointer_path,
        message="The pointer does not resolve in the frozen source schema.",
        violated_condition="the referenced schema path does not exist",
        expected_category="a pointer reachable from the selected source schema",
    )


def _validate_declared_type(
    declared: RuleValueType,
    schema: dict[str, JsonValue],
    *,
    path: tuple[str | int, ...],
    issues: list[SafeValidationIssue],
) -> None:
    expected = _schema_value_types(schema)
    if not expected or declared == "any" or declared in expected:
        return
    issues.append(
        SafeValidationIssue(
            code="rule_reference_type_mismatch",
            location=path,
            message="Rule reference value_type must match the frozen source schema.",
            violated_condition="the Agent-declared value_type differs from schema-derived type",
            expected_category="one of " + ", ".join(sorted(expected)),
        )
    )


def _schema_value_types(schema: dict[str, JsonValue]) -> frozenset[RuleValueType]:
    raw = schema.get("type")
    values = (raw,) if isinstance(raw, str) else tuple(raw) if isinstance(raw, list) else ()
    mapped: set[RuleValueType] = set()
    for value in values:
        if value == "integer":
            mapped.add("number")
        elif isinstance(value, str) and value in {
            "null",
            "boolean",
            "number",
            "string",
            "array",
            "object",
        }:
            mapped.add(cast(RuleValueType, value))
    return frozenset(mapped)


def _term_declared_type(term: RuleConstant | RuleValueRef) -> RuleValueType | None:
    return term.value_type


def _escape_token(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _allowed_collection_expectation(catalog: RuleContextCatalog) -> str:
    return _bounded_expectation(
        "one of the frozen collection pointers",
        tuple(sorted(catalog.collection_keys)),
    )


def _bounded_expectation(label: str, values: tuple[str, ...]) -> str:
    if not values:
        return label
    rendered = f"{label}: {', '.join(values)}"
    return rendered if len(rendered) <= 512 else f"{rendered[:509]}..."


__all__ = ["RuleContextCatalog", "validate_rule_context"]
