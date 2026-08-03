from __future__ import annotations

import json

from agent_world.contracts import (
    Rule,
    RuleClause,
    RuleConstant,
    RuleLookupByKey,
    RuleValueRef,
    StateEntitySchema,
    StateSchema,
    ToolSurface,
)
from agent_world.designer.models import (
    RuleBoundLookupByKeyDraft,
    RuleBoundReferenceDraft,
    RuleLookupByKeyDraft,
    RuleReferenceDraft,
    ToolRuleBoundLookupByReferenceDraft,
)
from agent_world.designer.rule_context import (
    RuleContextCatalog,
    _materialize_term_bindings,
    validate_rule_context,
)
from agent_world.designer.validation import StructuredSemanticIssue

_BOOKING_SCHEMA = {
    "type": "object",
    "properties": {
        "booking_id": {"type": "string"},
        "status": {"type": "string", "enum": ["confirmed", "cancelled"]},
        "total_price": {"type": "number"},
    },
    "required": ["booking_id", "status", "total_price"],
    "additionalProperties": False,
}


def _catalog() -> RuleContextCatalog:
    state = StateSchema(
        entities=(
            StateEntitySchema(
                entity="booking",
                json_schema=_BOOKING_SCHEMA,
                primary_key_fields=("booking_id",),
                mutable_fields=("status",),
            ),
        ),
        root_state_schema={
            "type": "object",
            "properties": {
                "bookings": {
                    "type": "array",
                    "items": _BOOKING_SCHEMA,
                }
            },
            "required": ["bookings"],
            "additionalProperties": False,
        },
    )
    surface = ToolSurface(
        tool_id="hotel.booking.get",
        namespace="hotel.booking",
        name="get",
        description="Get one booking.",
        transport="runtime",
        input_schema={
            "type": "object",
            "properties": {"booking_id": {"type": "string"}},
            "required": ["booking_id"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {"status": {"type": "string"}},
            "required": ["status"],
            "additionalProperties": False,
        },
        observation_schema={
            "type": "object",
            "properties": {"status": {"type": "string"}},
            "required": ["status"],
            "additionalProperties": False,
        },
    )
    return RuleContextCatalog.for_tool(state=state, surface=surface)


def _catalog_with_local_entity_refs() -> RuleContextCatalog:
    """Mirror composed WorldState: collections refer to local ``$defs``."""

    state = StateSchema(
        entities=(
            StateEntitySchema(
                entity="booking",
                json_schema=_BOOKING_SCHEMA,
                primary_key_fields=("booking_id",),
                mutable_fields=("status",),
            ),
        ),
        root_state_schema={
            "$defs": {"booking": _BOOKING_SCHEMA},
            "type": "object",
            "properties": {
                "bookings": {
                    "type": "array",
                    "items": {"$ref": "#/$defs/booking"},
                }
            },
            "required": ["bookings"],
            "additionalProperties": False,
        },
    )
    surface = ToolSurface(
        tool_id="hotel.booking.get",
        namespace="hotel.booking",
        name="get",
        description="Get one booking.",
        transport="runtime",
        input_schema={
            "type": "object",
            "properties": {"booking_id": {"type": "string"}},
            "required": ["booking_id"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {"status": {"type": "string"}},
            "required": ["status"],
            "additionalProperties": False,
        },
        observation_schema={
            "type": "object",
            "properties": {"status": {"type": "string"}},
            "required": ["status"],
            "additionalProperties": False,
        },
    )
    return RuleContextCatalog.for_tool(state=state, surface=surface)


def _rule(left: RuleValueRef | RuleLookupByKey) -> Rule:
    return Rule(
        rule_id="rule:hotel.booking.get:status",
        family="postcondition",
        description="The selected booking is confirmed.",
        boolean_operator="all",
        clauses=(
            RuleClause(
                clause_id="status_confirmed",
                left=left,
                operator="equal",
                right=RuleConstant(value_type="string", value="confirmed"),
            ),
        ),
        case_sensitivity="positive_only",
    )


def test_direct_pointer_cannot_fake_dynamic_collection_selection() -> None:
    issues = validate_rule_context(
        _rule(
            RuleValueRef(
                source="post_state",
                pointer="/bookings/status",
                value_type="string",
            )
        ),
        catalog=_catalog(),
    )

    assert [issue.code for issue in issues] == ["rule_pointer_requires_selector"]
    assert issues[0].location == ("clauses", 0, "left", "pointer")


def test_lookup_by_key_closes_collection_key_value_and_result_types() -> None:
    issues = validate_rule_context(
        _rule(
            RuleLookupByKey(
                source="post_state",
                collection_pointer="/bookings",
                key_field="booking_id",
                key=RuleValueRef(
                    source="args",
                    pointer="/booking_id",
                    value_type="string",
                ),
                value_pointer="/status",
                value_type="string",
            )
        ),
        catalog=_catalog(),
    )

    assert issues == ()


def test_rule_constant_must_fit_the_frozen_referenced_schema() -> None:
    rule = _rule(
        RuleLookupByKey(
            source="post_state",
            collection_pointer="/bookings",
            key_field="booking_id",
            key=RuleValueRef(
                source="args",
                pointer="/booking_id",
                value_type="string",
            ),
            value_pointer="/status",
            value_type="string",
        )
    ).model_copy(
        update={
            "clauses": (
                RuleClause(
                    clause_id="status_outside_domain",
                    left=RuleLookupByKey(
                        source="post_state",
                        collection_pointer="/bookings",
                        key_field="booking_id",
                        key=RuleValueRef(
                            source="args",
                            pointer="/booking_id",
                            value_type="string",
                        ),
                        value_pointer="/status",
                        value_type="string",
                    ),
                    operator="equal",
                    right=RuleConstant(value_type="string", value="ready"),
                ),
            )
        }
    )

    issues = validate_rule_context(rule, catalog=_catalog())

    assert [issue.code for issue in issues] == ["rule_constant_schema_mismatch"]
    assert issues[0].location == ("clauses", 0, "right", "value")


def test_local_defs_are_resolved_for_catalog_prompt_and_lookup_validation() -> None:
    catalog = _catalog_with_local_entity_refs()

    assert catalog.prompt_projection()["collections"] == [
        {
            "collection_pointer": "/bookings",
            "primary_key_fields": ["booking_id"],
            "item_fields": ["booking_id", "status", "total_price"],
        }
    ]
    issues = validate_rule_context(
        _rule(
            RuleLookupByKey(
                source="post_state",
                collection_pointer="/bookings",
                key_field="booking_id",
                key=RuleValueRef(
                    source="args",
                    pointer="/booking_id",
                    value_type="string",
                ),
                value_pointer="/status",
                value_type="string",
            )
        ),
        catalog=catalog,
    )

    assert issues == ()


def test_prompt_projection_uses_compact_aliases_without_losing_frozen_bindings() -> None:
    """Prompt compaction cannot alter the frozen lookup vocabulary."""

    catalog = _catalog()
    projection = catalog.prompt_projection()
    groups = projection["lookup_binding_groups"]
    assert isinstance(groups, list)
    assert "lookup_bindings" not in projection

    projected = {
        (
            group["source"],
            group["collection_pointer"],
            group["key_field"],
            group["key_value_type"],
            value["binding_id"],
            value["value_pointer"],
            value["value_type"],
        )
        for group in groups
        if isinstance(group, dict)
        for value in group["value_bindings"]
        if isinstance(value, dict)
    }
    aliases = catalog.prompt_lookup_bindings()
    frozen = {
        (
            binding.source,
            binding.collection_pointer,
            binding.key_field,
            binding.key_value_type,
            alias,
            binding.value_pointer,
            binding.value_type,
        )
        for alias, binding in aliases.items()
    }

    assert projected == frozen
    assert all(alias.startswith("lookup-") for alias in aliases)
    assert all(
        catalog.resolve_lookup_binding(alias) is binding for alias, binding in aliases.items()
    )
    lookup_reference_aliases = catalog.prompt_lookup_reference_bindings()
    projected_lookup_references = {
        (
            group["source"],
            group["collection_pointer"],
            group["key_field"],
            group["key_value_type"],
            group["value_pointer"],
            group["value_type"],
            item["binding_id"],
            item["key_source"],
            item["key_pointer"],
        )
        for group in projection["lookup_reference_binding_groups"]
        if isinstance(group, dict)
        for item in group["reference_key_bindings"]
        if isinstance(item, dict)
    }
    frozen_lookup_references = {
        (
            binding.lookup_binding.source,
            binding.lookup_binding.collection_pointer,
            binding.lookup_binding.key_field,
            binding.lookup_binding.key_value_type,
            binding.lookup_binding.value_pointer,
            binding.lookup_binding.value_type,
            alias,
            binding.key_binding.source,
            binding.key_binding.pointer,
        )
        for alias, binding in lookup_reference_aliases.items()
    }
    assert projected_lookup_references == frozen_lookup_references
    assert all(alias.startswith("lookup-ref-") for alias in lookup_reference_aliases)
    assert all(
        catalog.resolve_lookup_reference_binding(alias) is binding
        for alias, binding in lookup_reference_aliases.items()
    )
    reference_aliases = catalog.prompt_reference_bindings()
    assert all(alias.startswith("ref-") for alias in reference_aliases)
    assert all(
        catalog.resolve_reference_binding(alias) is binding
        for alias, binding in reference_aliases.items()
    )
    assert projection["term_binding_aliases"] == {
        "bound_reference": list(reference_aliases),
        "bound_lookup_by_constant": list(aliases),
        "bound_lookup_by_reference": list(lookup_reference_aliases),
    }
    ordered_aliases = projection["ordered_term_binding_aliases"]
    assert ordered_aliases["number"]["bound_reference"] == [
        alias
        for alias, binding in reference_aliases.items()
        if binding.value_type in {"number", "any"}
    ]
    assert ordered_aliases["string"]["bound_lookup_by_constant"] == [
        alias
        for alias, binding in aliases.items()
        if binding.value_type in {"string", "any"}
    ]
    serialized_projection = json.dumps(projection, sort_keys=True)
    assert "binding:reference:" not in serialized_projection
    assert "binding:lookup:" not in serialized_projection
    assert "binding:lookup_reference:" not in serialized_projection
    legacy = [
        binding.prompt_projection()
        for binding in sorted(catalog.lookup_bindings.values(), key=lambda item: item.binding_id)
    ]
    assert len(json.dumps(groups, sort_keys=True)) < len(json.dumps(legacy, sort_keys=True))


def test_prompt_projection_discloses_small_closed_literal_domains() -> None:
    """A Direct ToolSemantics call must see lifecycle/status choices, not just `string`."""

    projection = _catalog().prompt_projection()
    groups = projection["lookup_binding_groups"]
    assert isinstance(groups, list)
    status_binding = next(
        value
        for group in groups
        if isinstance(group, dict)
        and group["source"] == "post_state"
        and group["collection_pointer"] == "/bookings"
        for value in group["value_bindings"]
        if isinstance(value, dict) and value["value_pointer"] == "/status"
    )

    assert status_binding["enum_values"] == ["confirmed", "cancelled"]


def test_source_filtered_prompt_projection_preserves_full_catalog_aliases() -> None:
    """A narrower rule-family view cannot remap aliases from the full catalog."""

    catalog = _catalog()
    allowed = frozenset({"args", "pre_state"})
    projection = catalog.prompt_projection_for_sources(allowed_sources=allowed)

    reference_bindings = projection["reference_bindings"]
    assert isinstance(reference_bindings, list)
    projected_references = {
        item["binding_id"]: item["source"]
        for item in reference_bindings
        if isinstance(item, dict)
    }
    expected_references = {
        alias: binding.source
        for alias, binding in catalog.prompt_reference_bindings().items()
        if binding.source in allowed
    }
    assert projected_references == expected_references
    assert all(
        catalog.resolve_reference_binding(alias) is catalog.prompt_reference_bindings()[alias]
        for alias in projected_references
    )
    alias_ledger = projection["term_binding_aliases"]
    assert isinstance(alias_ledger, dict)
    assert alias_ledger["bound_reference"] == list(projected_references)
    ordered_ledger = projection["ordered_term_binding_aliases"]
    assert isinstance(ordered_ledger, dict)
    assert all(
        alias in alias_ledger["bound_reference"]
        for aliases in ordered_ledger.values()
        for alias in aliases["bound_reference"]
    )

    lookup_groups = projection["lookup_binding_groups"]
    assert isinstance(lookup_groups, list)
    assert all(
        isinstance(group, dict) and group["source"] in allowed for group in lookup_groups
    )
    lookup_reference_groups = projection["lookup_reference_binding_groups"]
    assert isinstance(lookup_reference_groups, list)
    assert all(
        isinstance(group, dict)
        and group["source"] in allowed
        and all(
            isinstance(item, dict) and item["key_source"] in allowed
            for item in group["reference_key_bindings"]
        )
        for group in lookup_reference_groups
    )


def test_bound_tool_terms_expand_only_from_frozen_local_defs_catalog() -> None:
    catalog = _catalog_with_local_entity_refs()
    args_booking_id = next(
        item
        for item in catalog.reference_bindings.values()
        if item.source == "args" and item.pointer == "/booking_id"
    )
    booking_status = next(
        item
        for item in catalog.lookup_bindings.values()
        if (
            item.source == "post_state"
            and item.collection_pointer == "/bookings"
            and item.key_field == "booking_id"
            and item.value_pointer == "/status"
        )
    )
    args_booking_alias = next(
        alias
        for alias, binding in catalog.prompt_reference_bindings().items()
        if binding == args_booking_id
    )
    booking_status_alias = next(
        alias
        for alias, binding in catalog.prompt_lookup_bindings().items()
        if binding == booking_status
    )
    booking_status_reference_alias = next(
        alias
        for alias, binding in catalog.prompt_lookup_reference_bindings().items()
        if (
            binding.lookup_binding == booking_status
            and binding.key_binding == args_booking_id
        )
    )
    issues: list[StructuredSemanticIssue] = []

    direct = _materialize_term_bindings(
        RuleBoundReferenceDraft(kind="bound_reference", binding_id=args_booking_alias),
        catalog=catalog,
        issues=issues,
        path=("clauses", 0, "left"),
    )
    lookup = _materialize_term_bindings(
        RuleBoundLookupByKeyDraft(
            kind="bound_lookup_by_key",
            binding_id=booking_status_alias,
            key=RuleBoundReferenceDraft(
                kind="bound_reference",
                binding_id=args_booking_alias,
            ),
        ),
        catalog=catalog,
        issues=issues,
        path=("clauses", 1, "left"),
    )
    flat_lookup = _materialize_term_bindings(
        ToolRuleBoundLookupByReferenceDraft(
            kind="bound_lookup_by_reference",
            binding_id=booking_status_reference_alias,
        ),
        catalog=catalog,
        issues=issues,
        path=("clauses", 2, "left"),
    )

    assert issues == []
    assert isinstance(direct, RuleReferenceDraft)
    assert direct.model_dump(mode="json") == {
        "kind": "reference",
        "source": "args",
        "pointer": "/booking_id",
        "value_type": "string",
    }
    assert isinstance(lookup, RuleLookupByKeyDraft)
    assert flat_lookup == lookup
    assert lookup.model_dump(mode="json") == {
        "kind": "lookup_by_key",
        "source": "post_state",
        "collection_pointer": "/bookings",
        "key_field": "booking_id",
        "key": {
            "kind": "reference",
            "source": "args",
            "pointer": "/booking_id",
            "value_type": "string",
        },
        "value_pointer": "/status",
        "value_type": "string",
    }


def test_lookup_reference_catalog_pairs_only_same_terminal_field_and_type() -> None:
    catalog = _catalog_with_local_entity_refs()

    bindings = tuple(catalog.lookup_reference_bindings.values())
    assert bindings
    assert all(
        binding.key_binding.pointer.rsplit("/", 1)[-1]
        == binding.lookup_binding.key_field
        for binding in bindings
    )
    assert all(
        binding.key_binding.value_type == binding.lookup_binding.key_value_type
        for binding in bindings
    )
    assert not any(
        binding.key_binding.pointer == "/status"
        and binding.lookup_binding.key_field == "booking_id"
        for binding in bindings
    )


def test_raw_tool_reference_is_rejected_before_core_rule_compilation() -> None:
    issues: list[StructuredSemanticIssue] = []

    _materialize_term_bindings(
        RuleReferenceDraft(
            kind="reference",
            source="post_state",
            pointer="/bookings/status",
            value_type="string",
        ),
        catalog=_catalog_with_local_entity_refs(),
        issues=issues,
        path=("clauses", 0, "left"),
    )

    assert [item.code for item in issues] == ["tool_rule_binding_required"]
    assert issues[0].location == ("clauses", 0, "left")


def test_lookup_by_key_rejects_non_primary_key_and_schema_type_drift() -> None:
    issues = validate_rule_context(
        _rule(
            RuleLookupByKey(
                source="post_state",
                collection_pointer="/bookings",
                key_field="status",
                key=RuleValueRef(
                    source="args",
                    pointer="/booking_id",
                    value_type="string",
                ),
                value_pointer="/total_price",
                value_type="string",
            )
        ),
        catalog=_catalog(),
    )

    assert {issue.code for issue in issues} == {
        "rule_lookup_key_not_primary",
        "rule_reference_type_mismatch",
        # The comparison literal is independently impossible for the selected
        # numeric field.  Keep the full diagnostic set: repairing only the
        # selector/type declaration would otherwise leave an unsatisfiable
        # Rule behind.
        "rule_constant_schema_mismatch",
    }
    assert all(issue.violated_condition for issue in issues)
    assert all(issue.expected_category for issue in issues)
    primary_issue = next(issue for issue in issues if issue.code == "rule_lookup_key_not_primary")
    assert primary_issue.expected_category == (
        "one of the frozen primary-key fields: booking_id"
    )


def test_bad_selector_target_discloses_bounded_frozen_collection_candidates() -> None:
    issues = validate_rule_context(
        _rule(
            RuleLookupByKey(
                source="post_state",
                collection_pointer="/bookings/0",
                key_field="booking_id",
                key=RuleValueRef(
                    source="args",
                    pointer="/booking_id",
                    value_type="string",
                ),
                value_pointer="/status",
                value_type="string",
            )
        ),
        catalog=_catalog(),
    )

    assert issues[0].code == "rule_lookup_collection_not_array"
    assert issues[0].expected_category == (
        "one of the frozen collection pointers: /bookings"
    )
