from __future__ import annotations

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
from agent_world.designer.rule_context import RuleContextCatalog, validate_rule_context

_BOOKING_SCHEMA = {
    "type": "object",
    "properties": {
        "booking_id": {"type": "string"},
        "status": {"type": "string"},
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
