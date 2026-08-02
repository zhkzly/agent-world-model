"""Compact, versioned Direct-LLM Prompt forms for existing Rule contracts.

Native provider schema carries the structural response shape.  This Prompt
protocol supplies only the Rule semantics that a schema cannot express:
framework-derived fields, frozen binding aliases, and cross-field meaning.
It is not a parser, new Rule language, or acceptance path: the original
Pydantic source models, frozen Tool Rule bindings, and deterministic compilers
remain authoritative.
"""

from __future__ import annotations

import json
from copy import deepcopy

# V14 is the concise logical form. The separate descriptive schema below is
# retained for deterministic contract tests only; it is never copied into the
# Direct Prompt because the provider already receives the native strict schema.
COMPACT_RULE_PROTOCOL_VERSION = "rule-output-protocol.v14"


_TOOL_RULE_DRAFT = """\
A RULE has only these Agent-authored fields:
{"description": non-empty string, "boolean_operator": "all"|"any", "clauses": [CLAUSE, ...],
 "case_sensitivity": "positive_only"|"positive_and_negative",
 "evidence_claim_ids": [claim id, ...]}
Omit rule_id and family: framework code derives both from the closed containment
path. In order: conditions.preconditions => precondition,
conditions.postconditions => postcondition, state_transition.transition => transition,
errors.errors[*].when => error_condition, and permission.condition => permission.

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
with one lookup alias and a literal key. For bound_lookup_by_constant, first
locate its binding_id in exactly one lookup_binding_groups entry: copy that
group's key_value_type byte-for-byte into key_value_type, and make key_value a
JSON value of that type. The value_bindings[*].value_type is the type retrieved
from the lookup, not the key type; never substitute it or use a literal as a
stand-in for the retrieved value. Never emit key_binding_id.
Never emit reference, lookup_by_key, bound_lookup_by_key, source,
pointer, collection_pointer, key_field, value_pointer, raw value_type for a
binding, or free-form expression text. key_value_type is the required
bound_lookup_by_constant exception, not a raw binding annotation.

For every term, frozen context also gives term_binding_aliases as the final
closed ledger keyed by the exact term kind: bound_reference,
bound_lookup_by_constant, or bound_lookup_by_reference. Copy one alias exactly
from the matching list. The longer binding groups explain the selected alias;
they do not authorize extrapolating numbers, renumbering aliases, or using an
alias from another term kind. Before serialization, independently check every
binding_id against its matching ledger list.

Frozen context also gives ordered_term_binding_aliases by returned value type.
For an ordered comparison, ordering="number" requires both sides to be number
or any (including matching typed constants or arithmetic). ordering="date" or
"date-time" requires both sides to be string or any *and* represent that
temporal meaning, not a generic identifier, status, or arbitrary text. If the
terms do not satisfy those conditions, use an equality/containment clause or a
different semantically valid comparison instead of inventing an ordering.
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
5. For every bound Rule term, select binding_id only from the matching
   term_binding_aliases list. Copy it byte-for-byte; do not infer a missing alias from a
   neighboring number or another term kind.
6. For every ordered clause, check both alias selections against the matching
   ordered_term_binding_aliases value-type list and check any constant's declared value_type.
   Do not apply number ordering to generic strings or temporal ordering to identifiers/statuses.
"""


_TOOL_SEMANTICS_BATCH = f"""\
Compact Rule output protocol: {COMPACT_RULE_PROTOCOL_VERSION}.

Return the original ToolSemanticsBatchSourceDraft shape, not an abbreviated
summary. The complete logical root is {{"tools":[TOOL]}}. It contains exactly
one TOOL for the one frozen target tool id, with no extra or missing tool. Each
TOOL has exactly these roots:
* tool_id
* conditions: {{"tool_id", "preconditions", "postconditions"}}
* state_transition: {{"tool_id", "transition"}}; transition has at least one RULE
* errors: {{"tool_id", "errors"}}; errors has at least one ERROR
* access_observation: {{"tool_id", "permission", "observation"}}
* reliability: {{"tool_id", "idempotency", "retry", "timeout", "transaction",
  "rollback", "concurrency"}}
Every nested tool_id equals the enclosing TOOL tool_id.
Return the smallest semantically sufficient closed behavior for that one tool.
Include only conditions, transitions, errors, access/observation, and
reliability facts needed to define its behavior. Do not narrate reasoning,
repeat equivalent Rules, enumerate examples or trajectories, duplicate frozen
context, or expand alternatives. Do not omit a necessary behavior merely to be
short.
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
absent from this map is not permitted. For every actor present, each scope must
be copied exactly from that actor's authorities in frozen world_boundary data;
an empty scope list is valid.

observation is {{"visible_fields_by_actor", "consistency",
"staleness_bound_seconds"}}, where consistency is strong|read_after_write|
eventual|snapshot. visible_fields_by_actor has keys exactly equal to every
frozen boundary actor, whether or not each actor has permission to call the
tool. Each value is an array of concrete top-level field names from that
target tool's frozen observation_schema only: never use output fields, state
paths, dotted paths, wildcards, resource names, or invented fields. Framework
code derives each actor's redacted-field complement, so do not emit a
redacted_fields_by_actor field.

A permission condition is optional. For one tool, use only aliases from its
frozen permission_rule_context_catalogs entry anywhere within condition; that
entry preserves aliases from the full rule_context_catalogs entry but excludes
observation, tool_result, and post_state sources. If the actor/scope map already
expresses static access, set condition to null rather than inventing a Rule. If
the map covers every frozen boundary actor and condition is non-null, set its
case_sensitivity to positive_and_negative.

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
Every timeout_error_code, retryable_error_codes entry, rollback_trigger_codes
entry, and non-null conflict_error_code must be an error_code declared in this
same TOOL's errors.errors list. A code named in retryable_error_codes must
refer to an ERROR whose retryable field is true. Every compensation_tools entry
must be a frozen tool id.

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
            "maxItems": 1,
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
                "description",
                "boolean_operator",
                "clauses",
                "case_sensitivity",
                "evidence_claim_ids",
            ],
            "additionalProperties": False,
            "properties": {
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
    """Return an isolated descriptive schema for the compact v14 Prompt form."""

    return deepcopy(_TOOL_SEMANTICS_BATCH_SHAPE)


def tool_semantics_representation_audit() -> str:
    """Return the shared final JSON-kind checklist for a ToolSemantics batch."""

    return _TOOL_SEMANTICS_REPRESENTATION_AUDIT


def tool_semantics_batch_protocol(
    *,
    target_tool_ids: tuple[str, ...] | None = None,
) -> str:
    """Return the compact v14 form for one frozen ToolSemantics batch.

    The reusable Rule section is intentionally separated above so WorldRules
    and Curriculum can adopt a future context-appropriate protocol without
    reintroducing recursive Pydantic schema text or changing their source ABI.
    The acyclic descriptive schema remains a test-only characterization rather
    than provider prompt text because the configured gateway rejects it.

    A live physical batch additionally binds its one exact target near the end
    of the provider-visible protocol.  The generic compact
    form deliberately cannot name that data, but leaving it only in the much
    earlier frozen-context JSON caused models to substitute a plausible whole
    inventory.  This is a Prompt projection, not a new semantic contract:
    the compiler still owns identity/order acceptance.
    """

    if target_tool_ids is None:
        return _TOOL_SEMANTICS_BATCH
    if (
        len(target_tool_ids) != 1
        or len(set(target_tool_ids)) != len(target_tool_ids)
        or any(not tool_id or tool_id != tool_id.strip() for tool_id in target_tool_ids)
    ):
        raise ValueError("ToolSemantics protocol requires one exact unique target tool")
    rendered_ids = json.dumps(target_tool_ids, ensure_ascii=False, separators=(",", ":"))
    return f"""{_TOOL_SEMANTICS_BATCH}

Invocation-specific final completion gate:
Exact target tools: {rendered_ids}.
Return exactly one tool in this order; do not add, omit, rename, or reorder.
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
