from __future__ import annotations

from dataclasses import replace

import pytest
from jsonschema import Draft202012Validator  # type: ignore[import-untyped]
from pydantic import BaseModel

from agent_world.designer.models import (
    CurriculumPlanSourceDraft,
    InitialStateRulesSourceDraft,
    RuleDraft,
    TaskRequirementSourceDraft,
    ToolAccessObservationSourceDraft,
    ToolConditionsSourceDraft,
    ToolErrorsSourceDraft,
    ToolReliabilitySourceDraft,
    ToolStateTransitionSourceDraft,
    WorldClosureSourceDraft,
)
from agent_world.designer.service import EnvironmentDesigner
from agent_world.judge.rules import (
    RuleEvaluationError,
    RuleExecutionContext,
    evaluate_rule,
)


def _temporal_error_source() -> dict[str, object]:
    return {
        "tool_id": "agent-world.runtime.v2.quote_availability",
        "errors": [
            {
                "error_code": "invalid_stay_window",
                "when": {
                    "rule_id": "rule:agent-world.runtime.v2.quote_availability:window",
                    "family": "error_condition",
                    "description": "Check-out must be later than check-in.",
                    "boolean_operator": "all",
                    "clauses": [
                        {
                            "clause_id": "non_increasing_window",
                            "operator": "less_or_equal",
                            "ordering": "date",
                            "left": {
                                "kind": "reference",
                                "source": "args",
                                "pointer": "/check_out_date",
                                "value_type": "string",
                            },
                            "right": {
                                "kind": "reference",
                                "source": "args",
                                "pointer": "/check_in_date",
                                "value_type": "string",
                            },
                            "negate": False,
                        }
                    ],
                    "case_sensitivity": "positive_and_negative",
                    "evidence_claim_ids": [],
                },
                "observation": "Check-out must be later than check-in.",
                "state_effect": "none",
                "retryable": False,
                "evidence_claim_ids": [],
            }
        ],
    }


def _context(*, check_in: str, check_out: str) -> RuleExecutionContext:
    return RuleExecutionContext(
        actor="guest",
        pre_state={},
        post_state={},
        args={"check_in_date": check_in, "check_out_date": check_out},
        tool_result={},
        error=None,
        observation={},
        events=[],
        reset_config={},
        task_goal={},
        seed=1,
        terminated=False,
        truncated=False,
    )


def test_agent_rule_schema_expresses_operator_specific_clause_shapes() -> None:
    schema = RuleDraft.model_json_schema(mode="validation")
    validator = Draft202012Validator(schema)
    valid = _temporal_error_source()["errors"][0]["when"]  # type: ignore[index]
    assert not tuple(validator.iter_errors(valid))

    existence_with_right = {
        **valid,  # type: ignore[arg-type]
        "clauses": [
            {
                "clause_id": "missing",
                "operator": "exists",
                "left": {
                    "kind": "reference",
                    "source": "args",
                    "pointer": "/property_id",
                    "value_type": "string",
                },
                "right": {
                    "kind": "constant",
                    "value_type": "string",
                    "value": "forbidden",
                },
                "negate": False,
            }
        ],
    }
    ordered_without_ordering = {
        **valid,  # type: ignore[arg-type]
        "clauses": [
            {
                key: value
                for key, value in valid["clauses"][0].items()  # type: ignore[index,union-attr]
                if key != "ordering"
            }
        ],
    }

    assert tuple(validator.iter_errors(existence_with_right))
    assert tuple(validator.iter_errors(ordered_without_ordering))


def test_temporal_rule_draft_compiles_and_executes_without_llm_repair() -> None:
    source = ToolErrorsSourceDraft.model_validate(_temporal_error_source())
    compiled = EnvironmentDesigner._compile_tool_errors_source(source)
    rule = compiled.errors[0].when

    assert rule.clauses[0].ordering == "date"
    assert evaluate_rule(
        rule,
        _context(check_in="2026-07-20", check_out="2026-07-19"),
    ).result
    assert not evaluate_rule(
        rule,
        _context(check_in="2026-07-20", check_out="2026-07-21"),
    ).result

    with pytest.raises(RuleEvaluationError, match="invalid date value"):
        evaluate_rule(
            rule,
            _context(check_in="not-a-date", check_out="2026-07-21"),
        )


def test_lookup_by_key_rule_compiles_and_executes_against_collection_state() -> None:
    source = ToolConditionsSourceDraft.model_validate(
        {
            "tool_id": "hotel.booking.get",
            "postconditions": [
                {
                    "rule_id": "rule:hotel.booking.get:confirmed",
                    "family": "postcondition",
                    "description": "The selected booking is confirmed.",
                    "boolean_operator": "all",
                    "clauses": [
                        {
                            "clause_id": "selected_booking_confirmed",
                            "operator": "equal",
                            "left": {
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
                            },
                            "right": {
                                "kind": "constant",
                                "value_type": "string",
                                "value": "confirmed",
                            },
                            "negate": False,
                        }
                    ],
                    "case_sensitivity": "positive_only",
                    "evidence_claim_ids": [],
                }
            ],
        }
    )
    rule = EnvironmentDesigner._compile_tool_conditions_source(source).postconditions[0]
    context = RuleExecutionContext(
        actor="guest",
        pre_state={"bookings": []},
        post_state={
            "bookings": [
                {"booking_id": "booking:other", "status": "cancelled"},
                {"booking_id": "booking:target", "status": "confirmed"},
            ]
        },
        args={"booking_id": "booking:target"},
        tool_result={},
        error=None,
        observation={},
        events=[],
        reset_config={},
        task_goal={},
        seed=1,
        terminated=False,
        truncated=False,
    )

    assert evaluate_rule(rule, context).result

    duplicate_context = replace(
        context,
        post_state={
            "bookings": [
                {"booking_id": "booking:target", "status": "confirmed"},
                {"booking_id": "booking:target", "status": "confirmed"},
            ]
        },
    )
    with pytest.raises(RuleEvaluationError, match="more than one state record"):
        evaluate_rule(rule, duplicate_context)


def test_direct_agent_source_contracts_have_no_hidden_model_validators() -> None:
    """Every direct-flow invariant must be schema-visible or compiler-owned."""

    roots = (
        InitialStateRulesSourceDraft,
        ToolConditionsSourceDraft,
        ToolStateTransitionSourceDraft,
        ToolErrorsSourceDraft,
        ToolAccessObservationSourceDraft,
        ToolReliabilitySourceDraft,
        WorldClosureSourceDraft,
        CurriculumPlanSourceDraft,
        TaskRequirementSourceDraft,
    )
    stack = list(BaseModel.__subclasses__())
    models_by_name: dict[str, list[type[BaseModel]]] = {}
    while stack:
        model = stack.pop()
        models_by_name.setdefault(model.__name__, []).append(model)
        stack.extend(model.__subclasses__())

    hidden: dict[str, tuple[str, ...]] = {}
    for root in roots:
        reachable_names = set(root.model_json_schema(mode="validation").get("$defs", ()))
        reachable_names.add(root.__name__)
        for name in reachable_names:
            for model in models_by_name.get(name, ()):
                validators = tuple(model.__pydantic_decorators__.model_validators)
                if validators:
                    hidden[f"{root.__name__}->{name}"] = validators

    assert hidden == {}
