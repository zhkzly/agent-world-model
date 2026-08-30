"""Machine-readable TaskSemantics wire schemas and Host-accepted examples."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, cast

from jsonschema import Draft202012Validator

from agent_env_foundry.environment import JSONObject


def _array_of_strings() -> dict[str, Any]:
    return {"type": "array", "items": {"type": "string"}}


_PUBLIC_VALUE_SOURCE = {
    "type": "object",
    "properties": {
        "kind": {
            "type": "string",
            "enum": [
                "task_literal",
                "task_descriptor",
                "reset",
                "tool_observation",
                "tool_schema_constant",
            ],
        },
        "tool_name": {"type": ["string", "null"]},
        "json_pointer": {"type": ["string", "null"]},
        "value": {},
    },
    "required": ["kind", "tool_name", "json_pointer", "value"],
    "additionalProperties": False,
}

_ANSWER_FIELD = {
    "type": "object",
    "properties": {
        "field_id": {"type": "string"},
        "schema": {"type": "object"},
        "public_label": {"type": "string"},
        "public_source": {"$ref": "#/$defs/public_value_source"},
    },
    "required": ["field_id", "schema", "public_label", "public_source"],
    "additionalProperties": False,
}

_SCHEMAS: dict[str, Any] = {
    "start_case": {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {
            "case_id": {"type": "string"},
            "reset_input": {"type": ["object", "null"]},
            "regime_tags": _array_of_strings(),
        },
        "required": ["case_id", "reset_input", "regime_tags"],
        "additionalProperties": False,
    },
    "capability": {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$defs": {
            "public_value_source": _PUBLIC_VALUE_SOURCE,
            "answer_field": _ANSWER_FIELD,
        },
        "type": "object",
        "properties": {
            "capability_id": {"type": "string"},
            "requirement_ids": _array_of_strings(),
            "workflow_ids": _array_of_strings(),
            "composition_rules": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "rule_id": {"type": "string"},
                        "workflow_id": {"type": "string"},
                        "kind": {"const": "all"},
                        "capability_ids": _array_of_strings(),
                        "max_occurrences": {"type": "integer", "minimum": 1},
                    },
                    "required": [
                        "rule_id",
                        "workflow_id",
                        "kind",
                        "capability_ids",
                        "max_occurrences",
                    ],
                    "additionalProperties": False,
                },
            },
            "actor_role": {"type": "string"},
            "task_kind": {
                "type": "string",
                "enum": ["query", "state_change", "process"],
            },
            "intent_label": {"type": "string"},
            "protected_binding_schema": {"type": "object"},
            "public_descriptor_schema": {"type": "object"},
            "facets": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "public_label": {"type": "string"},
                        "value_schema": {"type": "object"},
                        "allowed_operators": _array_of_strings(),
                    },
                    "required": [
                        "name",
                        "public_label",
                        "value_schema",
                        "allowed_operators",
                    ],
                    "additionalProperties": False,
                },
            },
            "conditions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "condition_id": {"type": "string"},
                        "public_label": {"type": "string"},
                        "binding_scope": {
                            "type": "string",
                            "enum": ["world", "selected_binding"],
                        },
                        "true_capability_ids": _array_of_strings(),
                        "false_capability_ids": _array_of_strings(),
                        "report_field": {"$ref": "#/$defs/answer_field"},
                        "public_source": {"$ref": "#/$defs/public_value_source"},
                    },
                    "required": [
                        "condition_id",
                        "public_label",
                        "binding_scope",
                        "true_capability_ids",
                        "false_capability_ids",
                        "report_field",
                        "public_source",
                    ],
                    "additionalProperties": False,
                },
            },
            "answer_fields": {
                "type": "array",
                "items": {"$ref": "#/$defs/answer_field"},
            },
            "supported_goal_kinds": _array_of_strings(),
            "rendering": {
                "type": "object",
                "properties": {
                    "imperative": {"type": "string"},
                    "target_noun": {"type": "string"},
                    "answer_phrase": {"type": ["string", "null"]},
                },
                "required": ["imperative", "target_noun", "answer_phrase"],
                "additionalProperties": False,
            },
        },
        "required": [
            "capability_id",
            "requirement_ids",
            "workflow_ids",
            "composition_rules",
            "actor_role",
            "task_kind",
            "intent_label",
            "protected_binding_schema",
            "public_descriptor_schema",
            "facets",
            "conditions",
            "answer_fields",
            "supported_goal_kinds",
            "rendering",
        ],
        "additionalProperties": False,
    },
    "binding": {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$defs": {"public_value_source": _PUBLIC_VALUE_SOURCE},
        "type": "object",
        "properties": {
            "semantic_key": {"type": "string"},
            "eligible": {"type": "boolean"},
            "reason_codes": _array_of_strings(),
            "protected_binding": {"type": "object"},
            "public_descriptor": {"type": "object"},
            "facets": {"type": "object"},
            "public_sources": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "field_pointer": {
                            "type": "string",
                            "pattern": "^/(public_descriptor|facets)(/|$)",
                        },
                        "source": {"$ref": "#/$defs/public_value_source"},
                    },
                    "required": ["field_pointer", "source"],
                    "additionalProperties": False,
                },
            },
        },
        "required": [
            "semantic_key",
            "eligible",
            "reason_codes",
            "protected_binding",
            "public_descriptor",
            "facets",
            "public_sources",
        ],
        "additionalProperties": False,
    },
    "atom_result": {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {
            "initially_satisfied": {"type": "boolean"},
            "satisfied": {"type": "boolean"},
            "required_effects_ok": {"type": "boolean"},
            "collateral_ok": {"type": "boolean"},
            "answer_ok": {"type": ["boolean", "null"]},
            "process_ok": {"type": ["boolean", "null"]},
            "report_values": {"type": "object"},
            "failure_codes": _array_of_strings(),
        },
        "required": [
            "initially_satisfied",
            "satisfied",
            "required_effects_ok",
            "collateral_ok",
            "answer_ok",
            "process_ok",
            "report_values",
            "failure_codes",
        ],
        "additionalProperties": False,
    },
    "condition_result": {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {
            "status": {"type": "string", "enum": ["true", "false", "abstain"]},
            "report_values": {"type": "object"},
            "failure_codes": _array_of_strings(),
        },
        "required": ["status", "report_values", "failure_codes"],
        "additionalProperties": False,
    },
}

_EXAMPLES: dict[str, Any] = {
    "start_case": {"case_id": "default", "reset_input": None, "regime_tags": []},
    "capability": {
        "capability_id": "inspect-item",
        "requirement_ids": ["REQ-001"],
        "workflow_ids": ["inspect"],
        "composition_rules": [],
        "actor_role": "operator",
        "task_kind": "query",
        "intent_label": "Inspect one item",
        "protected_binding_schema": {
            "type": "object",
            "properties": {"item": {"type": "string"}},
            "required": ["item"],
            "additionalProperties": False,
        },
        "public_descriptor_schema": {
            "type": "object",
            "properties": {"item": {"type": "string"}},
            "required": ["item"],
            "additionalProperties": False,
        },
        "facets": [],
        "conditions": [],
        "answer_fields": [
            {
                "field_id": "value",
                "schema": {"type": "string"},
                "public_label": "Value",
                "public_source": {
                    "kind": "tool_observation",
                    "tool_name": "inspect_item",
                    "json_pointer": "/data/value",
                    "value": None,
                },
            }
        ],
        "supported_goal_kinds": ["atom"],
        "rendering": {
            "imperative": "Inspect the selected item",
            "target_noun": "item",
            "answer_phrase": "Report Value.",
        },
    },
    "binding": {
        "semantic_key": "item:item-1",
        "eligible": True,
        "reason_codes": [],
        "protected_binding": {"item": "item-1"},
        "public_descriptor": {"item": "item-1"},
        "facets": {},
        "public_sources": [
            {
                "field_pointer": "/public_descriptor/item",
                "source": {
                    "kind": "task_literal",
                    "tool_name": None,
                    "json_pointer": None,
                    "value": "item-1",
                },
            }
        ],
    },
    "atom_result": {
        "initially_satisfied": False,
        "satisfied": True,
        "required_effects_ok": True,
        "collateral_ok": True,
        "answer_ok": True,
        "process_ok": True,
        "report_values": {"value": "alpha"},
        "failure_codes": [],
    },
    "condition_result": {"status": "true", "report_values": {}, "failure_codes": []},
}


def semantics_wire_document() -> JSONObject:
    return cast(
        JSONObject,
        deepcopy(
            {
                "format": "task-semantics-wire/1",
                "schemas": _SCHEMAS,
                "examples": _EXAMPLES,
            }
        ),
    )


def validate_semantics_wire_items(kind: str, items: list[Any]) -> tuple[str, ...]:
    schema = _SCHEMAS.get(kind)
    if schema is None:
        raise ValueError(f"unknown TaskSemantics wire kind {kind!r}")
    validator = Draft202012Validator(schema)
    findings: list[str] = []
    for index, item in enumerate(items):
        for error in sorted(validator.iter_errors(item), key=str):
            location = f"$[{index}]" + "".join(f"[{part!r}]" for part in error.absolute_path)
            findings.append(f"{location}: {error.message}")
    return tuple(findings)


__all__ = ["semantics_wire_document", "validate_semantics_wire_items"]
