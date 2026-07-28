"""Compact, versioned Agent-facing forms for existing Rule source contracts.

The provider-facing JSON envelope deliberately stays shallow.  These protocols
replace only the generated recursive JSON Schema text copied into a prompt for
providers that have been observed to reject that text.  They are not a parser,
new Rule language, or acceptance path: the original Pydantic source models,
frozen Tool Rule bindings, and deterministic compilers remain authoritative.
"""

from __future__ import annotations

import json
from copy import deepcopy

# V8 is the provider-compatible prompt form.  The separate descriptive schema
# below is retained for deterministic contract tests only: a real v2 probe
# established that this gateway rejects JSON-Schema syntax even when it is
# acyclic, so it must never be interpolated into the provider prompt.
COMPACT_RULE_PROTOCOL_VERSION = "rule-output-protocol.v8"


_TOOL_RULE_DRAFT = """\
A RULE has only these fields:
{"family": RULE_FAMILY, "description": non-empty string,
 "boolean_operator": "all"|"any", "clauses": [CLAUSE, ...],
 "case_sensitivity": "positive_only"|"positive_and_negative",
 "evidence_claim_ids": [claim id, ...]}
Omit rule_id: framework code derives it. RULE_FAMILY must match the containing
section: precondition, postcondition, transition, error_condition, or permission.

A CLAUSE is closed by its operator. equal, not_equal, contains, and not_contains
have exactly clause_id, operator, left, right, and optional negate; they MUST omit `ordering`.
greater_than, greater_or_equal, less_than, and less_or_equal
have exactly clause_id, operator, ordering, left, right, and optional negate;
they MUST include ordering="number"|"date"|"date-time". Do not use exists,
not_exists, schema_valid, json_schema, ordering on an equality/containment
clause, or any unlisted clause field.

For this ToolSemantics protocol, a TERM is exactly one of:
* {"kind":"constant", "value_type":"null"|"boolean"|"number"|"string"|"array"|"object",
   "value": JSON value}
* {"kind":"bound_reference", "binding_id": one compact frozen alias from this tool's
   rule_context_catalog}
* {"kind":"bound_lookup_by_reference", "binding_id": one compact frozen
   lookup-reference alias}
* {"kind":"bound_lookup_by_constant", "binding_id": one compact frozen lookup alias,
   "key_value_type":"null"|"boolean"|"number"|"string"|"array"|"object",
   "key_value": JSON value}
* {"kind":"arithmetic", "operator":"add"|"subtract"|"multiply"|"divide"|"modulo",
   "left": ATOM, "right": ATOM}, where ATOM is a constant, bound_reference,
   bound_lookup_by_reference, or bound_lookup_by_constant.
Lookup keys are flat and closed: never emit a nested `key` object. Choose one
bound_lookup_by_reference alias from lookup_reference_binding_groups when the
framework has frozen a compatible reference key, or bound_lookup_by_constant
with one lookup alias and a literal key. Never emit key_binding_id.
Never emit reference, lookup_by_key, bound_lookup_by_key, source,
pointer, collection_pointer, key_field, value_pointer, raw value_type for a
binding, or free-form expression text.
"""


_TOOL_SEMANTICS_REPRESENTATION_AUDIT = """\
Pre-serialization representation audit (run it independently for every TOOL):
1. Copy the enclosing TOOL tool_id exactly into conditions.tool_id,
   state_transition.tool_id, errors.tool_id, access_observation.tool_id, and
   reliability.tool_id. No nested tool_id is implied by its parent or may be omitted.
2. These are each one non-empty JSON string, never an array or object:
   every RULE.description, ERROR.observation, permission.denied_observation,
   idempotency.duplicate_observation, transaction.commit_point,
   rollback.guarantees, concurrency.conflict_detection, and
   concurrency.ordering_guarantee.
3. In reliability, preserve primitive kinds: retry.maximum_attempts is an integer >= 1;
   retry.retryable_error_codes, rollback.rollback_trigger_codes, and
   rollback.compensation_tools are arrays; retry.requires_same_idempotency_key,
   transaction.partial_commit_observable, and rollback.supported are booleans;
   timeout.operation_timeout_seconds is a positive number; and
   concurrency.conflict_error_code is either null or one identifier string.
4. Do the same final kind check for optional numbers: idempotency_key.retention_seconds is
   null or a positive number, and observation.staleness_bound_seconds is null or a
   non-negative number. Do not turn a scalar, boolean, or null into explanatory prose.
"""


_TOOL_SEMANTICS_BATCH = f"""\
Compact Rule output protocol: {COMPACT_RULE_PROTOCOL_VERSION}.

Return the original ToolSemanticsBatchSourceDraft shape, not an abbreviated
summary. The complete logical root is {{"tools":[TOOL, ...]}}. It contains one
TOOL for each frozen target tool id, in the exact target order, with no extra
or missing tools (at most two). Each TOOL has exactly these roots:
* tool_id
* conditions: {{"tool_id", "preconditions", "postconditions"}}
* state_transition: {{"tool_id", "transition"}}; transition has at least one RULE
* errors: {{"tool_id", "errors"}}; errors has at least one ERROR
* access_observation: {{"tool_id", "permission", "observation"}}
* reliability: {{"tool_id", "idempotency", "retry", "timeout", "transaction",
  "rollback", "concurrency"}}
Every nested tool_id equals the enclosing TOOL tool_id.
The uppercase names TOOL, RULE, CLAUSE, ERROR, and ATOM are explanatory names
only: never emit them, a placeholder, an ellipsis, or null for a required
identifier/text field. Use the actual frozen tool id, concrete non-empty
descriptions/observations, and concrete non-empty identifier strings. Null is
allowed only where this protocol explicitly says a field is nullable.

ERROR is {{"error_code", "when", "observation", "state_effect", "retryable",
"evidence_claim_ids"}}. state_effect is none|partial|rolled_back|unknown, and
when is a RULE with family error_condition.

permission is {{"permission_id", "required_scopes_by_actor", "condition",
"denied_observation"}}; condition is null or a RULE with family permission.
The non-empty required_scopes_by_actor map is the complete allowed-actor set:
its concrete actor-id keys are exactly the actors permitted by this tool. Do
not emit allowed_actors; framework code derives that core projection. An actor
absent from this map is not permitted. observation is {{"visible_fields_by_actor",
"consistency", "staleness_bound_seconds"}}, where consistency is
strong|read_after_write|eventual|snapshot. Every map value is an array of
concrete top-level observation field names or scope identifiers as applicable.

idempotency is either {{"mode":"not_supported","duplicate_observation"}},
{{"mode":"natural","duplicate_observation"}}, or {{"mode":"idempotency_key",
"key_field","retention_seconds","duplicate_observation"}}. retry is
{{"maximum_attempts", "backoff", "retryable_error_codes", "requires_same_idempotency_key"}}
with backoff none|fixed|exponential. timeout is {{"operation_timeout_seconds",
"timeout_error_code", "cancellation_effect"}} with cancellation_effect
no_effect|may_commit|rolled_back|unknown. transaction is {{"atomicity", "commit_point",
"partial_commit_observable"}} with atomicity atomic|best_effort|saga|none. rollback is
{{"supported", "rollback_trigger_codes", "compensation_tools", "guarantees"}}.
concurrency is {{"isolation", "conflict_detection", "conflict_error_code",
"ordering_guarantee"}} with isolation
serial|serializable|snapshot|read_committed|optimistic|last_write_wins.

{_TOOL_RULE_DRAFT}

{_TOOL_SEMANTICS_REPRESENTATION_AUDIT}
"""


# This is deliberately an acyclic, strict subset of the existing source-model
# schema.  It has the same JSON field names and no new expression language,
# but it omits unsupported/raw Tool terms and unneeded recursive Rule branches.
# It is a prompt construction aid only; the existing Pydantic model and
# compiler remain the sole local acceptance path.
_TOOL_SEMANTICS_BATCH_SHAPE: dict[str, object] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["tools"],
    "additionalProperties": False,
    "properties": {
        "tools": {
            "type": "array",
            "minItems": 1,
            "maxItems": 2,
            "items": {"$ref": "#/$defs/tool"},
        }
    },
    "$defs": {
        "identifier": {"type": "string", "minLength": 1},
        "identifier_array": {
            "type": "array",
            "items": {"$ref": "#/$defs/identifier"},
        },
        "constant": {
            "type": "object",
            "required": ["kind", "value_type", "value"],
            "additionalProperties": False,
            "properties": {
                "kind": {"const": "constant"},
                "value_type": {"enum": ["null", "boolean", "number", "string", "array", "object"]},
                "value": {},
            },
        },
        "bound_reference": {
            "type": "object",
            "required": ["kind", "binding_id"],
            "additionalProperties": False,
            "properties": {
                "kind": {"const": "bound_reference"},
                "binding_id": {"$ref": "#/$defs/identifier"},
            },
        },
        "bound_lookup_by_reference": {
            "type": "object",
            "required": ["kind", "binding_id"],
            "additionalProperties": False,
            "properties": {
                "kind": {"const": "bound_lookup_by_reference"},
                "binding_id": {"$ref": "#/$defs/identifier"},
            },
        },
        "bound_lookup_by_constant": {
            "type": "object",
            "required": ["kind", "binding_id", "key_value_type", "key_value"],
            "additionalProperties": False,
            "properties": {
                "kind": {"const": "bound_lookup_by_constant"},
                "binding_id": {"$ref": "#/$defs/identifier"},
                "key_value_type": {
                    "enum": ["null", "boolean", "number", "string", "array", "object"]
                },
                "key_value": {},
            },
        },
        "atom": {
            "oneOf": [
                {"$ref": "#/$defs/constant"},
                {"$ref": "#/$defs/bound_reference"},
                {"$ref": "#/$defs/bound_lookup_by_reference"},
                {"$ref": "#/$defs/bound_lookup_by_constant"},
            ]
        },
        "arithmetic": {
            "type": "object",
            "required": ["kind", "operator", "left", "right"],
            "additionalProperties": False,
            "properties": {
                "kind": {"const": "arithmetic"},
                "operator": {"enum": ["add", "subtract", "multiply", "divide", "modulo"]},
                "left": {"$ref": "#/$defs/atom"},
                "right": {"$ref": "#/$defs/atom"},
            },
        },
        "term": {
            "oneOf": [
                {"$ref": "#/$defs/atom"},
                {"$ref": "#/$defs/arithmetic"},
            ]
        },
        "ordinary_clause": {
            "type": "object",
            "required": ["clause_id", "operator", "left", "right", "negate"],
            "additionalProperties": False,
            "properties": {
                "clause_id": {"$ref": "#/$defs/identifier"},
                "operator": {"enum": ["equal", "not_equal", "contains", "not_contains"]},
                "left": {"$ref": "#/$defs/term"},
                "right": {"$ref": "#/$defs/term"},
                "negate": {"type": "boolean"},
            },
        },
        "ordered_clause": {
            "type": "object",
            "required": ["clause_id", "operator", "ordering", "left", "right", "negate"],
            "additionalProperties": False,
            "properties": {
                "clause_id": {"$ref": "#/$defs/identifier"},
                "operator": {
                    "enum": [
                        "greater_than",
                        "greater_or_equal",
                        "less_than",
                        "less_or_equal",
                    ]
                },
                "ordering": {"enum": ["number", "date", "date-time"]},
                "left": {"$ref": "#/$defs/term"},
                "right": {"$ref": "#/$defs/term"},
                "negate": {"type": "boolean"},
            },
        },
        "rule": {
            "type": "object",
            "required": [
                "family",
                "description",
                "boolean_operator",
                "clauses",
                "case_sensitivity",
                "evidence_claim_ids",
            ],
            "additionalProperties": False,
            "properties": {
                "family": {
                    "enum": [
                        "precondition",
                        "postcondition",
                        "transition",
                        "error_condition",
                        "permission",
                    ]
                },
                "description": {"type": "string", "minLength": 1},
                "boolean_operator": {"enum": ["all", "any"]},
                "clauses": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 64,
                    "items": {
                        "oneOf": [
                            {"$ref": "#/$defs/ordinary_clause"},
                            {"$ref": "#/$defs/ordered_clause"},
                        ]
                    },
                },
                "case_sensitivity": {"enum": ["positive_only", "positive_and_negative"]},
                "evidence_claim_ids": {"$ref": "#/$defs/identifier_array"},
            },
        },
        "conditions": {
            "type": "object",
            "required": ["tool_id", "preconditions", "postconditions"],
            "additionalProperties": False,
            "properties": {
                "tool_id": {"$ref": "#/$defs/identifier"},
                "preconditions": {"type": "array", "items": {"$ref": "#/$defs/rule"}},
                "postconditions": {"type": "array", "items": {"$ref": "#/$defs/rule"}},
            },
        },
        "transition": {
            "type": "object",
            "required": ["tool_id", "transition"],
            "additionalProperties": False,
            "properties": {
                "tool_id": {"$ref": "#/$defs/identifier"},
                "transition": {
                    "type": "array",
                    "minItems": 1,
                    "items": {"$ref": "#/$defs/rule"},
                },
            },
        },
        "error": {
            "type": "object",
            "required": [
                "error_code",
                "when",
                "observation",
                "state_effect",
                "retryable",
                "evidence_claim_ids",
            ],
            "additionalProperties": False,
            "properties": {
                "error_code": {"$ref": "#/$defs/identifier"},
                "when": {"$ref": "#/$defs/rule"},
                "observation": {"type": "string", "minLength": 1},
                "state_effect": {"enum": ["none", "partial", "rolled_back", "unknown"]},
                "retryable": {"type": "boolean"},
                "evidence_claim_ids": {"$ref": "#/$defs/identifier_array"},
            },
        },
        "errors": {
            "type": "object",
            "required": ["tool_id", "errors"],
            "additionalProperties": False,
            "properties": {
                "tool_id": {"$ref": "#/$defs/identifier"},
                "errors": {
                    "type": "array",
                    "minItems": 1,
                    "items": {"$ref": "#/$defs/error"},
                },
            },
        },
        "permission": {
            "type": "object",
            "required": [
                "permission_id",
                "required_scopes_by_actor",
                "condition",
                "denied_observation",
            ],
            "additionalProperties": False,
            "properties": {
                "permission_id": {"$ref": "#/$defs/identifier"},
                "required_scopes_by_actor": {
                    "type": "object",
                    "minProperties": 1,
                    "additionalProperties": {"$ref": "#/$defs/identifier_array"},
                },
                "condition": {"oneOf": [{"type": "null"}, {"$ref": "#/$defs/rule"}]},
                "denied_observation": {"type": "string", "minLength": 1},
            },
        },
        "observation": {
            "type": "object",
            "required": ["visible_fields_by_actor", "consistency", "staleness_bound_seconds"],
            "additionalProperties": False,
            "properties": {
                "visible_fields_by_actor": {
                    "type": "object",
                    "additionalProperties": {"$ref": "#/$defs/identifier_array"},
                },
                "consistency": {"enum": ["strong", "read_after_write", "eventual", "snapshot"]},
                "staleness_bound_seconds": {
                    "oneOf": [{"type": "null"}, {"type": "number", "minimum": 0}]
                },
            },
        },
        "access_observation": {
            "type": "object",
            "required": ["tool_id", "permission", "observation"],
            "additionalProperties": False,
            "properties": {
                "tool_id": {"$ref": "#/$defs/identifier"},
                "permission": {"$ref": "#/$defs/permission"},
                "observation": {"$ref": "#/$defs/observation"},
            },
        },
        "idempotency": {
            "oneOf": [
                {
                    "type": "object",
                    "required": ["mode", "duplicate_observation"],
                    "additionalProperties": False,
                    "properties": {
                        "mode": {"const": "not_supported"},
                        "duplicate_observation": {"type": "string", "minLength": 1},
                    },
                },
                {
                    "type": "object",
                    "required": ["mode", "duplicate_observation"],
                    "additionalProperties": False,
                    "properties": {
                        "mode": {"const": "natural"},
                        "duplicate_observation": {"type": "string", "minLength": 1},
                    },
                },
                {
                    "type": "object",
                    "required": [
                        "mode",
                        "key_field",
                        "retention_seconds",
                        "duplicate_observation",
                    ],
                    "additionalProperties": False,
                    "properties": {
                        "mode": {"const": "idempotency_key"},
                        "key_field": {"$ref": "#/$defs/identifier"},
                        "retention_seconds": {
                            "oneOf": [
                                {"type": "null"},
                                {"type": "number", "exclusiveMinimum": 0},
                            ]
                        },
                        "duplicate_observation": {"type": "string", "minLength": 1},
                    },
                },
            ]
        },
        "reliability": {
            "type": "object",
            "required": [
                "tool_id",
                "idempotency",
                "retry",
                "timeout",
                "transaction",
                "rollback",
                "concurrency",
            ],
            "additionalProperties": False,
            "properties": {
                "tool_id": {"$ref": "#/$defs/identifier"},
                "idempotency": {"$ref": "#/$defs/idempotency"},
                "retry": {
                    "type": "object",
                    "required": [
                        "maximum_attempts",
                        "backoff",
                        "retryable_error_codes",
                        "requires_same_idempotency_key",
                    ],
                    "additionalProperties": False,
                    "properties": {
                        "maximum_attempts": {"type": "integer", "exclusiveMinimum": 0},
                        "backoff": {"enum": ["none", "fixed", "exponential"]},
                        "retryable_error_codes": {"$ref": "#/$defs/identifier_array"},
                        "requires_same_idempotency_key": {"type": "boolean"},
                    },
                },
                "timeout": {
                    "type": "object",
                    "required": [
                        "operation_timeout_seconds",
                        "timeout_error_code",
                        "cancellation_effect",
                    ],
                    "additionalProperties": False,
                    "properties": {
                        "operation_timeout_seconds": {"type": "number", "exclusiveMinimum": 0},
                        "timeout_error_code": {"$ref": "#/$defs/identifier"},
                        "cancellation_effect": {
                            "enum": ["no_effect", "may_commit", "rolled_back", "unknown"]
                        },
                    },
                },
                "transaction": {
                    "type": "object",
                    "required": ["atomicity", "commit_point", "partial_commit_observable"],
                    "additionalProperties": False,
                    "properties": {
                        "atomicity": {"enum": ["atomic", "best_effort", "saga", "none"]},
                        "commit_point": {"type": "string", "minLength": 1},
                        "partial_commit_observable": {"type": "boolean"},
                    },
                },
                "rollback": {
                    "type": "object",
                    "required": [
                        "supported",
                        "rollback_trigger_codes",
                        "compensation_tools",
                        "guarantees",
                    ],
                    "additionalProperties": False,
                    "properties": {
                        "supported": {"type": "boolean"},
                        "rollback_trigger_codes": {"$ref": "#/$defs/identifier_array"},
                        "compensation_tools": {"$ref": "#/$defs/identifier_array"},
                        "guarantees": {"type": "string", "minLength": 1},
                    },
                },
                "concurrency": {
                    "type": "object",
                    "required": [
                        "isolation",
                        "conflict_detection",
                        "conflict_error_code",
                        "ordering_guarantee",
                    ],
                    "additionalProperties": False,
                    "properties": {
                        "isolation": {
                            "enum": [
                                "serial",
                                "serializable",
                                "snapshot",
                                "read_committed",
                                "optimistic",
                                "last_write_wins",
                            ]
                        },
                        "conflict_detection": {"type": "string", "minLength": 1},
                        "conflict_error_code": {
                            "oneOf": [
                                {"type": "null"},
                                {"$ref": "#/$defs/identifier"},
                            ]
                        },
                        "ordering_guarantee": {"type": "string", "minLength": 1},
                    },
                },
            },
        },
        "tool": {
            "type": "object",
            "required": [
                "tool_id",
                "conditions",
                "state_transition",
                "errors",
                "access_observation",
                "reliability",
            ],
            "additionalProperties": False,
            "properties": {
                "tool_id": {"$ref": "#/$defs/identifier"},
                "conditions": {"$ref": "#/$defs/conditions"},
                "state_transition": {"$ref": "#/$defs/transition"},
                "errors": {"$ref": "#/$defs/errors"},
                "access_observation": {"$ref": "#/$defs/access_observation"},
                "reliability": {"$ref": "#/$defs/reliability"},
            },
        },
    },
}


def tool_semantics_batch_protocol_schema() -> dict[str, object]:
    """Return an isolated descriptive schema for the compact v8 prompt form."""

    return deepcopy(_TOOL_SEMANTICS_BATCH_SHAPE)


def tool_semantics_representation_audit() -> str:
    """Return the shared final JSON-kind checklist for a ToolSemantics batch."""

    return _TOOL_SEMANTICS_REPRESENTATION_AUDIT


def tool_semantics_batch_protocol(
    *,
    target_tool_ids: tuple[str, ...] | None = None,
) -> str:
    """Return the compact v8 form for one frozen ToolSemantics batch.

    The reusable Rule section is intentionally separated above so WorldRules
    and Curriculum can adopt a future context-appropriate protocol without
    reintroducing recursive Pydantic schema text or changing their source ABI.
    The acyclic descriptive schema remains a test-only characterization rather
    than provider prompt text because the configured gateway rejects it.

    A live physical batch may additionally bind its exact one- or two-tool
    target near the end of the provider-visible protocol.  The generic compact
    form deliberately cannot name that data, but leaving it only in the much
    earlier frozen-context JSON caused models to substitute a plausible whole
    inventory.  This is a Prompt projection, not a new semantic contract:
    the compiler still owns identity/order acceptance.
    """

    if target_tool_ids is None:
        return _TOOL_SEMANTICS_BATCH
    if (
        not 1 <= len(target_tool_ids) <= 2
        or len(set(target_tool_ids)) != len(target_tool_ids)
        or any(not tool_id or tool_id != tool_id.strip() for tool_id in target_tool_ids)
    ):
        raise ValueError("ToolSemantics protocol requires one exact unique target-tool batch")
    rendered_ids = json.dumps(target_tool_ids, ensure_ascii=False, separators=(",", ":"))
    return f"""{_TOOL_SEMANTICS_BATCH}

Invocation-specific final completion gate:
Exact target tools: {rendered_ids}.
Return exactly {len(target_tool_ids)} tools in this order; do not add, omit, rename, or reorder.
Before serializing, verify every TOOL has all five required roots: conditions, state_transition,
errors, access_observation, and reliability, then run the representation audit above for every
target. In particular, reliability.tool_id is required and rollback.guarantees is one non-empty
JSON string, never an array or object. In reliability.retry, maximum_attempts is an integer greater
than or equal to 1. A tool with no retry after its initial call still uses maximum_attempts=1 and an
empty retryable_error_codes list.
"""


__all__ = [
    "COMPACT_RULE_PROTOCOL_VERSION",
    "tool_semantics_batch_protocol",
    "tool_semantics_batch_protocol_schema",
    "tool_semantics_representation_audit",
]
